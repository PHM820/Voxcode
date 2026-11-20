# -*- coding: utf-8 -*-
"""상주 리스너 프로세스.

docs/architecture.md에 확정된 것만 구현한다. 아직 미정인 세부(설정 파일
스키마 일부, 프로세스 생명주기 관리 스크립트)는 TODO로 남긴다.

이 파일이 실제로 왕복하는 것:
  1. 로컬 TCP 서버(127.0.0.1:8765)로 훅이 보내는 완료 알림 JSON을 수신
  2. 세션별 상태 테이블에 반영
  3. 여러 알림이 겹치면 큐에 쌓아 "{프로젝트명}, {요약}" 형식으로 순차 TTS
  4. (테스트 함수) 텍스트를 직접 넘겨 세션 라우팅 규칙 ①~④, "멈춰 {프로젝트명}"
     브로드캐스트 규칙을 검증
  5. 라우팅 결정된 세션에 voice/inject.js를 subprocess로 호출해 postback
  6. 실시간 마이크 루프(MicLoop): 항상 마이크를 열어 VAD+wakeword로 호출어
     대기 → 감지 시 받아쓰기(비프음 + VAD 종료 감지 + STT) → route_and_send로
     라우팅. TTS 재생 중에는 VAD만으로 바지-인 감지 → 재생 중단 + 즉시 받아쓰기
     (architecture.md "3. 유휴 상태에서 호출어로 명령", "4. TTS 재생 중 바지-인")

MicLoop은 별도 스레드(daemon)에서 돌아 asyncio TCP 서버와 동시에 동작한다
(작업 지시서 4번 요구사항).
"""
from __future__ import annotations

import asyncio
import json
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

# ---- 고정값 (이번 구현에서 확정, docs/architecture.md에 반영) ----
HOST = "127.0.0.1"
PORT = 8765  # TODO였던 포트 번호를 이 구현에서 8765로 확정 (docs/architecture.md 갱신 필요)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INJECT_JS = PROJECT_ROOT / "voice" / "inject.js"

STOP_PREFIX = "멈춰"  # known: "멈춰 {프로젝트명}" 형식만 유효, 뒤에 단어 없으면 무시


# ---------------------------------------------------------------------------
# 세션 상태 테이블
# ---------------------------------------------------------------------------

@dataclass
class SessionState:
    """세션 하나의 레코드. docs/architecture.md "세션 라우팅" 절의 필드 그대로."""

    session_id: str  # = CLAUDE_CODE_MESSAGING_SOCKET 경로 자체 (별도 uuid 없음)
    project_name: str
    socket_path: str
    token: str
    last_notify_at: float = 0.0
    last_command_at: float = 0.0
    # "멈춰" 이후 재라우팅 문제의 A안(docs/architecture.md "'멈춰' 이후 재라우팅
    # 문제와 A안" 절). 세션이 스스로 /voice-detach를 호출하면 False, /voice-attach
    # 또는 프로젝트명 직접 호출로 다시 True. 테이블에서 삭제하지 않고 플래그만
    # 바꾸는 이유: 규칙 ①(프로젝트명 직접 호출)이 active 무관하게 항상 즉시
    # 재활성화할 수 있어야 하기 때문 — 삭제하면 그 즉시 재활성화가 불가능해진다.
    active: bool = True


class SessionTable:
    """세션별 상태를 관리하는 dict 래퍼. 상주 프로세스 안에서 하나만 존재."""

    def __init__(self):
        self._sessions: dict[str, SessionState] = {}
        self._lock = threading.Lock()

    def upsert_from_notify(self, session_id: str, project_name: str,
                            socket_path: str, token: str) -> SessionState:
        """완료 알림 수신 시 세션 레코드를 갱신(없으면 생성)하고 last_notify_at 찍기.

        기존에 detach된 세션이라도 실제로 완료 알림을 다시 보냈다는 건 사용자가
        그 프로젝트에 새로 뭔가를 시켰다는 뜻이므로 active를 True로 되돌린다
        ("'멈춰' 이후 재라우팅 문제와 A안" 절의 "해제 조건" 참고).
        """
        with self._lock:
            st = self._sessions.get(session_id)
            if st is None:
                st = SessionState(
                    session_id=session_id,
                    project_name=project_name,
                    socket_path=socket_path,
                    token=token,
                )
                self._sessions[session_id] = st
            else:
                # 프로젝트명/소켓/토큰은 최신 값으로 갱신 (재시작 등으로 바뀔 수 있음)
                st.project_name = project_name
                st.socket_path = socket_path
                st.token = token
            st.last_notify_at = time.time()
            st.active = True
            return st

    def mark_command_sent(self, session_id: str) -> None:
        with self._lock:
            st = self._sessions.get(session_id)
            if st is not None:
                st.last_command_at = time.time()

    def mark_detached(self, session_id: str) -> bool:
        """/voice-detach: 세션이 스스로 라우팅 후보에서 빠짐. 찾았으면 True."""
        with self._lock:
            st = self._sessions.get(session_id)
            if st is None:
                return False
            st.active = False
            return True

    def mark_attached(self, session_id: str, project_name: str,
                       socket_path: str, token: str) -> SessionState:
        """/voice-attach: notify와 동일 로직(재사용) — 세션 정보를 갱신하고
        active=True로 되돌린다. 별도 이벤트지만 upsert 의미가 같아 위임한다."""
        return self.upsert_from_notify(session_id, project_name, socket_path, token)

    def all_sessions(self) -> list[SessionState]:
        with self._lock:
            return list(self._sessions.values())

    def find_by_project_prefix(self, spoken_text: str) -> Optional[SessionState]:
        """발화가 프로젝트명으로 '시작'하면 그 세션 반환 (라우팅 규칙 ①).

        active 무관하게 항상 찾고, 찾으면 그 즉시 재활성화한다 — "프로젝트명을
        직접 부르면 언제든 즉시 부활"이 사용자 재량 원칙과 일치("'멈춰' 이후
        재라우팅 문제와 A안" 절).
        """
        with self._lock:
            for st in self._sessions.values():
                if spoken_text.startswith(st.project_name):
                    st.active = True
                    return st
        return None

    def most_recent_by_notify(self) -> Optional[SessionState]:
        """규칙 ②: active인 세션만 후보로 삼는다 — detach된 세션은 제외
        ("'멈춰' 이후 재라우팅 문제와 A안" 절)."""
        sessions = [s for s in self.all_sessions() if s.active]
        if not sessions:
            return None
        return max(sessions, key=lambda s: s.last_notify_at)

    def most_recent_by_command(self) -> Optional[SessionState]:
        """규칙 ③도 ②와 같은 원칙 — detach된 세션은 후보에서 제외."""
        sessions = self.all_sessions()
        if not sessions:
            return None
        candidates = [s for s in sessions if s.last_command_at > 0 and s.active]
        if not candidates:
            return None
        return max(candidates, key=lambda s: s.last_command_at)


# ---------------------------------------------------------------------------
# 세션 라우팅 (docs/architecture.md "세션 라우팅" 절, 기계적 규칙만 사용)
# ---------------------------------------------------------------------------

def route_command(table: SessionTable, spoken_text: str) -> Optional[SessionState]:
    """일반 음성 명령을 어느 세션으로 보낼지 결정한다. LLM 판단 없이 규칙만.

    우선순위:
      ④ 세션이 하나뿐이면 무조건 그 세션 (먼저 체크하는 게 더 빠르고 규칙과 동치.
         detach 상태와 무관 — 세션이 하나뿐이면 "잘못된 세션으로 갈 위험" 자체가
         없으므로 active 필터를 적용할 이유가 없다)
      ① 발화가 프로젝트명으로 시작하면 그 세션 (active 무관, 즉시 재활성화)
      ② 없으면 last_notify_at이 가장 최근인 active 세션
      ③ 알림이 전혀 없었으면(모든 세션 last_notify_at==0) last_command_at 최신 active 세션
    """
    sessions = table.all_sessions()
    if not sessions:
        return None
    if len(sessions) == 1:
        return sessions[0]

    hit = table.find_by_project_prefix(spoken_text)
    if hit is not None:
        return hit

    most_notified = table.most_recent_by_notify()
    if most_notified is not None and most_notified.last_notify_at > 0:
        return most_notified

    return table.most_recent_by_command()


def parse_stop_command(spoken_text: str) -> Optional[str]:
    """"멈춰 {프로젝트명}" 형식이면 프로젝트명을, 아니면 None을 반환.

    형식 검사만 한다 (의미 이해 불필요 원칙, docs/architecture.md 5번 참고).
    """
    text = spoken_text.strip()
    if not text.startswith(STOP_PREFIX):
        return None
    rest = text[len(STOP_PREFIX):].strip()
    if not rest:
        return None  # "멈춰"만 있고 프로젝트명 없음 -> 무시
    # 첫 단어(공백 기준)를 프로젝트명으로 취급
    project_name = rest.split()[0]
    return project_name


def should_drop_transcript(spoken_text: str, judge=None) -> tuple[bool, Optional[float]]:
    """받아쓴 문장을 whisper 환각으로 보고 버릴지 판정 (voice/judge.py).

    "멈춰"로 시작하면 판정 없이 통과 — 이 필터가 낼 수 있는 가장 나쁜 실패가
    중단 명령을 버리는 것이라, 규칙으로 잡히는 제어 명령은 판단 모델에 맡기지 않는다.
    판정 못 함(None)은 통과(기존 동작 유지). judge는 테스트에서 네트워크 없이 바꿔 끼우는 용도.
    """
    if spoken_text.strip().startswith(STOP_PREFIX):
        return False, None
    from voice.judge import hallucination_score, is_hallucination
    score = (judge or hallucination_score)(spoken_text)
    return is_hallucination(spoken_text, score), score


# ---------------------------------------------------------------------------
# inject.js 호출 (postback)
# ---------------------------------------------------------------------------

def send_postback(session: SessionState, text: str) -> subprocess.CompletedProcess:
    """voice/inject.js를 subprocess로 실행해 해당 세션에 텍스트를 postback.

    inject.js는 CLAUDE_CODE_MESSAGING_SOCKET / CLAUDE_CODE_MESSAGING_TOKEN
    환경변수를 읽으므로, 대상 세션의 값을 해당 프로세스의 env로 넘긴다.

    주의: 실제 postback이 성공하려면 진짜 Claude Code 세션이 그 소켓을 열고
    있어야 한다. 가짜 세션(테스트용 socket_path/token)으로 호출하면
    inject.js가 연결 실패로 종료한다 — 이 함수는 "subprocess 호출까지"를
    검증하는 것이고, 실제 세션 환경에서 재검증이 필요하다.
    """
    import os

    env = os.environ.copy()
    env["CLAUDE_CODE_MESSAGING_SOCKET"] = session.socket_path
    env["CLAUDE_CODE_MESSAGING_TOKEN"] = session.token

    result = subprocess.run(
        ["node", str(INJECT_JS), text],
        env=env,
        capture_output=True,
        encoding="utf-8",  # Windows 기본(cp949)로 두면 한글 stdout/stderr 디코딩 시 죽음 (실측 확인)
        errors="replace",
        timeout=10,
    )
    return result


def route_and_send(table: SessionTable, spoken_text: str) -> dict:
    """테스트/실사용 공통 진입점: 텍스트 -> 라우팅 -> postback.

    STT가 아직 없는 최소 버전이므로, 실시간 마이크 대신 이 함수에 텍스트를
    직접 넘겨서 라우팅 로직을 검증한다 (작업 지시서 6번 요구사항).

    반환값은 테스트에서 눈으로 확인하기 쉽게 dict로: 무슨 경로를 탔는지,
    누구에게 보냈는지, postback 결과가 어땠는지.
    """
    stop_project = parse_stop_command(spoken_text)
    if stop_project is not None:
        # 제어 명령: 라우팅 판단 없이 전 세션 브로드캐스트
        targets = table.all_sessions()
        results = []
        for st in targets:
            try:
                proc = send_postback(st, spoken_text)
                results.append({
                    "session_id": st.session_id,
                    "project_name": st.project_name,
                    "postback_ok": proc.returncode == 0,
                    "stdout": proc.stdout.strip(),
                    "stderr": proc.stderr.strip(),
                })
            except Exception as e:  # noqa: BLE001 - 테스트 가시성 위해 넓게 잡음
                results.append({
                    "session_id": st.session_id,
                    "project_name": st.project_name,
                    "postback_ok": False,
                    "error": str(e),
                })
            table.mark_command_sent(st.session_id)
        return {
            "mode": "broadcast_stop",
            "stop_project_token": stop_project,
            "targets": results,
        }

    # "멈춰"로 시작하지만 프로젝트명이 없는 경우도 parse_stop_command가 None을
    # 반환하므로 여기로 떨어져 일반 라우팅을 타지 않도록 별도 체크가 필요하다.
    if spoken_text.strip().startswith(STOP_PREFIX):
        return {"mode": "stop_ignored_no_project", "text": spoken_text}

    target = route_command(table, spoken_text)
    if target is None:
        return {"mode": "route", "target": None, "reason": "활성 세션 없음"}

    try:
        proc = send_postback(target, spoken_text)
        table.mark_command_sent(target.session_id)
        return {
            "mode": "route",
            "target": {
                "session_id": target.session_id,
                "project_name": target.project_name,
            },
            "postback_ok": proc.returncode == 0,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }
    except Exception as e:  # noqa: BLE001
        return {
            "mode": "route",
            "target": {
                "session_id": target.session_id,
                "project_name": target.project_name,
            },
            "postback_ok": False,
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# TTS 재생 큐 (여러 알림이 겹치면 순서대로)
# ---------------------------------------------------------------------------

class TtsQueue:
    """도착 순서대로 TTS를 순차 재생하는 큐.

    threading.Thread 하나가 큐를 소비한다 (asyncio TCP 서버와 별도 스레드 —
    TTS 재생(sounddevice, 블로킹)이 이벤트 루프를 막지 않도록 분리).
    """

    def __init__(self, tts_engine):
        self._q: queue.Queue[str] = queue.Queue()
        self._tts = tts_engine
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._history: list[str] = []  # 테스트 검증용: 실제 재생된 멘트 기록
        # 바지-인(architecture.md 4번) 지원용 상태. sounddevice 재생은 self._tts.speak()가
        # 블로킹으로 처리하므로, "지금 재생 중"임을 MicLoop이 확인할 플래그가 필요하다.
        self._speaking = threading.Event()
        self._interrupt_requested = threading.Event()

    def start(self) -> None:
        self._thread.start()

    def enqueue(self, project_name: str, summary: str) -> None:
        utterance = f"{project_name}, {summary}"
        self._q.put(utterance)

    @property
    def is_speaking(self) -> bool:
        """MicLoop이 바지-인 감지 대상 구간인지 판단할 때 쓴다."""
        return self._speaking.is_set()

    def interrupt(self) -> None:
        """현재 재생 중인 TTS를 즉시 중단시킨다 (바지-인 트리거 시 MicLoop이 호출)."""
        self._interrupt_requested.set()
        try:
            self._tts.stop()
        except Exception as e:  # noqa: BLE001 - 중단 실패해도 루프는 계속돼야 함
            print(f"[tts-queue] 중단 실패: {e}", file=sys.stderr)

    def _run(self) -> None:
        while True:
            utterance = self._q.get()
            print(f"[tts-queue] 재생: {utterance!r}")
            self._history.append(utterance)
            self._interrupt_requested.clear()
            self._speaking.set()
            try:
                self._tts.speak(utterance)
            except Exception as e:  # noqa: BLE001 - 재생 실패가 큐 전체를 죽이면 안 됨
                print(f"[tts-queue] 재생 실패: {e}", file=sys.stderr)
            finally:
                self._speaking.clear()
            self._q.task_done()

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """테스트용: 큐가 다 소비될 때까지 대기. join()에 timeout이 없어 폴링으로 구현."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._q.unfinished_tasks == 0:
                return True
            time.sleep(0.1)
        return False

    @property
    def history(self) -> list[str]:
        return list(self._history)


# ---------------------------------------------------------------------------
# 받아쓰기 피드백 비프음 (architecture.md 확정: 진입 시 높은 톤, 완료 시 낮은 톤)
# ---------------------------------------------------------------------------

BEEP_SAMPLE_RATE = 16000
# 0.15s는 이 PC의 MME 오디오 드라이버에서 실제로 소리가 안 들리는 문제를
# 실측으로 확인함(2026-09-26) - 재생 요청이 스트림 오픈+버퍼 채움보다 먼저
# 끝나버리는 것으로 추정(짧을수록 잘림). 사용자가 직접 들으며 0.15s(안 들림) →
# 0.5s(들림) → 0.4s(들림) → 0.3s(들림)까지 실측 확인 후 0.3s로 확정.
BEEP_DURATION_S = 0.3
BEEP_HIGH_HZ = 880.0  # 받아쓰기 진입
BEEP_LOW_HZ = 440.0   # 받아쓰기 완료


def _make_beep(freq_hz: float, duration_s: float = BEEP_DURATION_S,
               sample_rate: int = BEEP_SAMPLE_RATE) -> np.ndarray:
    """짧은 사인파 비프음을 생성한다. 새 사운드 파일 리소스는 만들지 않는다(작업 지시서 확정 사항)."""
    t = np.linspace(0, duration_s, int(duration_s * sample_rate), endpoint=False)
    tone = np.sin(2 * np.pi * freq_hz * t)
    # 클릭 노이즈 방지용 짧은 페이드 인/아웃
    fade_len = max(1, int(0.01 * sample_rate))
    fade = np.linspace(0, 1, fade_len)
    tone[:fade_len] *= fade
    tone[-fade_len:] *= fade[::-1]
    return (tone * 0.3).astype(np.float32)  # 과도한 볼륨 방지


def play_beep_blocking(freq_hz: float) -> None:
    import sounddevice as sd

    audio = _make_beep(freq_hz)
    sd.play(audio, samplerate=BEEP_SAMPLE_RATE)
    sd.wait()


# ---------------------------------------------------------------------------
# 실시간 마이크 루프 (architecture.md "3. 유휴 상태에서 호출어로 명령",
# "4. TTS 재생 중 바지-인")
# ---------------------------------------------------------------------------

MIC_SAMPLE_RATE = 16000  # voice/vad.py, voice/stt.py 모두 16kHz 기준
DICTATION_MAX_S = 15.0  # 받아쓰기 최대 길이 안전장치 (무한정 녹음 방지)


class MicLoop:
    """상시 마이크 루프: 유휴 상태에서는 호출어 대기, TTS 재생 중에는 바지-인 감지.

    별도 스레드(daemon)에서 run()을 실행해 asyncio TCP 서버와 동시에 돈다
    (작업 지시서 4번). 무거운 모델(SttEngine, WakeWordDetector)은 스레드
    시작 시 1회만 로딩한다.
    """

    def __init__(self, table: SessionTable, tts_queue: TtsQueue,
                 stt_engine=None, wake_detector=None,
                 sample_rate: int = MIC_SAMPLE_RATE):
        self.table = table
        self.tts_queue = tts_queue
        self.sample_rate = sample_rate
        self._stt_engine = stt_engine
        self._wake_detector = wake_detector
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # 테스트 가시성용: 마지막으로 처리한 받아쓰기 결과와 라우팅 결과 기록
        self.last_transcript: Optional[str] = None
        self.last_route_result: Optional[dict] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run_safe, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _ensure_models(self) -> None:
        if self._stt_engine is None:
            from voice.stt import SttEngine
            print("[mic-loop] STT 모델 로딩 중...")
            self._stt_engine = SttEngine()
            print("[mic-loop] STT 모델 로딩 완료")
        if self._wake_detector is None:
            from voice.wakeword import WakeWordDetector
            self._wake_detector = WakeWordDetector()

    def _run_safe(self) -> None:
        try:
            self._ensure_models()
            self.run()
        except Exception as e:  # noqa: BLE001 - 마이크 루프가 죽어도 TCP 서버는 살아있어야 함
            print(f"[mic-loop] 치명적 오류로 중단: {e}", file=sys.stderr)

    def run(self) -> None:
        """상시 루프: sounddevice 입력 스트림 하나를 열어 계속 청크를 읽는다."""
        import sounddevice as sd
        from voice.vad import SpeechStartDetector, CHUNK_SAMPLES

        if not self._wake_detector.is_onboarded():
            print(
                f"[mic-loop] 호출어 '{self._wake_detector.wake_word}' 온보딩이 안 돼 "
                f"있어 마이크 루프를 시작하지 않습니다. wakeword.onboard()를 먼저 실행하세요.",
                file=sys.stderr,
            )
            return

        print("[mic-loop] 마이크 루프 시작 (호출어 대기)")
        with sd.InputStream(samplerate=self.sample_rate, channels=1,
                             dtype=np.float32, blocksize=CHUNK_SAMPLES) as stream:
            barge_in_detector = SpeechStartDetector(sample_rate=self.sample_rate)
            while not self._stop.is_set():
                if self.tts_queue.is_speaking:
                    # 4. TTS 재생 중 바지-인: VAD로 발화 시작만 감지, 호출어 불필요
                    chunk, _overflow = stream.read(CHUNK_SAMPLES)
                    chunk = chunk[:, 0]
                    if barge_in_detector.push(chunk):
                        print("[mic-loop] 바지-인 감지: TTS 중단 + 받아쓰기 진입")
                        self.tts_queue.interrupt()
                        barge_in_detector.reset()
                        self._dictation_cycle(stream, play_entry_beep=True)
                    continue
                barge_in_detector.reset()

                # 3. 유휴 상태: 호출어 감지 대기 (lwake.listen()은 blocking이라
                # 감지 콜백 안에서 예외를 던져 빠져나온다)
                self._wait_for_wakeword(stream)
                if self._stop.is_set():
                    break
                print("[mic-loop] 호출어 감지: 받아쓰기 진입")
                self._dictation_cycle(stream, play_entry_beep=True)

        print("[mic-loop] 마이크 루프 종료")

    def _wait_for_wakeword(self, stream) -> None:
        """호출어가 감지될 때까지 블록. 감지되거나 stop()이 호출되면 반환."""

        # 2026-09-27 실측으로 발견한 버그: lwake.listen()의 감지 루프는
        # callback() 호출을 통째로 try/except Exception으로 감싸고 있어서
        # (.venv/Lib/site-packages/lwake/listen.py), 콜백이 Exception 계열
        # 예외를 던지면 "DTW comparison failed"로 로그만 찍히고 조용히
        # 삼켜진다 — 호출어가 반복 감지돼도 _dictation_cycle로 못 넘어가고
        # while True가 무한히 도는 실제 재현된 무한 루프의 원인이었다.
        # BaseException을 직접 상속(Exception 미상속)하면 그 except 절을
        # 그대로 통과해 밖으로 빠져나온다 — KeyboardInterrupt/SystemExit와
        # 같은 방식.
        class _WakeDetected(BaseException):
            pass

        def _on_detect(_detection: dict) -> None:
            raise _WakeDetected()

        # lwake.listen()은 자체 while True 루프라, self._stop을 주기적으로
        # 확인할 수 없다. 대신 짧은 슬라이스로 나눠 반복 호출해 stop() 반응성을 확보한다.
        # (listen()이 stream.read()를 계속 호출하므로, 완전한 인터럽트는 불가능하지만
        # 예외로 빠져나오는 구조 자체는 정상 동작한다 — 마이크 실시간 검증은 별도 확인 필요)
        while not self._stop.is_set():
            try:
                self._wake_detector.listen_blocking(_on_detect, stream=stream)
                # known-issues.md 14번: lwake.listen()은 참조 파일이 전부 로딩
                # 실패(손상 등)하면 예외 없이 조용히 return한다 — 여기서 잡지
                # 않으면 이 while 루프가 "감지 안 됨"을 CPU만 계속 태우며 무한
                # 반복하고, 사용자는 원인을 알 길이 없다. 예외 없는 리턴도
                # 이상 상황으로 보고 로그를 남긴 뒤 짧게 쉬고 재시도한다.
                print(
                    "[mic-loop] wakeword listen이 감지 없이 조용히 끝남 "
                    "(참조 파일이 손상됐을 수 있음 — models/wakeword/ 확인 권장), 재시도",
                    file=sys.stderr,
                )
                time.sleep(0.5)
            except _WakeDetected:
                return
            except Exception as e:  # noqa: BLE001
                print(f"[mic-loop] wakeword listen 오류, 재시도: {e}", file=sys.stderr)
                time.sleep(0.5)

    def _dictation_cycle(self, stream, play_entry_beep: bool) -> None:
        """받아쓰기 모드 한 사이클: 진입 비프 -> 녹음(VAD 종료 감지) -> 완료 비프 -> STT -> 라우팅."""
        from voice.vad import SpeechEndDetector, CHUNK_SAMPLES

        if play_entry_beep:
            play_beep_blocking(BEEP_HIGH_HZ)

        detector = SpeechEndDetector(sample_rate=self.sample_rate)
        recorded_chunks: list[np.ndarray] = []
        max_chunks = int(DICTATION_MAX_S * self.sample_rate / CHUNK_SAMPLES)

        for _ in range(max_chunks):
            if self._stop.is_set():
                return
            chunk, _overflow = stream.read(CHUNK_SAMPLES)
            chunk = chunk[:, 0].copy()
            recorded_chunks.append(chunk)
            detector.push(chunk)
            if detector.is_finished:
                break

        play_beep_blocking(BEEP_LOW_HZ)

        if not recorded_chunks:
            return
        audio = np.concatenate(recorded_chunks)
        if not detector.has_speech_started:
            print("[mic-loop] 발화 없음(무음만 녹음됨), 라우팅 생략")
            return

        print("[mic-loop] STT 인식 중...")
        from voice.config import load_settings
        stt_language = load_settings().get("language", "ko")
        text = self._stt_engine.transcribe(audio, self.sample_rate, language=stt_language)
        print(f"[mic-loop] 인식 결과: {text!r}")
        self.last_transcript = text

        if not text.strip():
            print("[mic-loop] 빈 인식 결과, 라우팅 생략")
            return

        # 환각 필터(should_drop_transcript, voice/judge.py)는 연결 해제 상태(2026-11-20) —
        # 실제 사용에서 환각이 문제로 확인되면 여기서 다시 호출한다.

        result = route_and_send(self.table, text)
        self.last_route_result = result
        print(f"[mic-loop] 라우팅 결과: {result}")


# ---------------------------------------------------------------------------
# TCP 서버
# ---------------------------------------------------------------------------

# 메시지 스키마 (이번 구현에서 확정, docs/architecture.md 반영 필요):
# {
#   "event": "notify" | "command" | "detach" | "attach" | "shutdown",
#     # notify=완료 알림, command=음성 명령(테스트 경로에서는 안 씀),
#     # detach/attach=/voice-detach·/voice-attach 스킬이 보내는 자기 상태 관리
#     # 이벤트("'멈춰' 이후 재라우팅 문제와 A안" 절)
#   "session_id": "<CLAUDE_CODE_MESSAGING_SOCKET 경로>",
#   "project_name": "<cwd 폴더명>",  # attach에는 필요, detach는 session_id만 있으면 충분
#   "text": "<요약 또는 명령 텍스트>",
#   "socket_path": "<대상 세션의 CLAUDE_CODE_MESSAGING_SOCKET>",
#   "token": "<대상 세션의 CLAUDE_CODE_MESSAGING_TOKEN>"
# }
# session_id와 socket_path는 architecture.md 결정대로 동일한 값(소켓 경로 자체)이지만,
# 필드를 분리해둔 이유: session_id는 "테이블의 키"라는 의미, socket_path는 "postback 시
# 실제로 연결할 주소"라는 의미로 역할이 다르다 (지금은 같은 문자열이라도 나중에 달라질
# 여지를 남김 — 과설계는 아니고 이미 의미가 다른 두 용도라 필드를 합치지 않음).

class ListenerServer:
    def __init__(self, table: SessionTable, tts_queue: TtsQueue,
                 host: str = HOST, port: int = PORT):
        self.table = table
        self.tts_queue = tts_queue
        self.host = host
        self.port = port
        self._server: Optional[asyncio.base_events.Server] = None
        self._shutdown_requested = False

    async def handle_client(self, reader: asyncio.StreamReader,
                             writer: asyncio.StreamWriter) -> None:
        try:
            raw = await reader.read(65536)
            if not raw:
                return
            try:
                msg = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as e:
                writer.write(json.dumps({"ok": False, "error": f"invalid json: {e}"}).encode())
                await writer.drain()
                return

            event = msg.get("event", "notify")
            session_id = msg.get("session_id")
            project_name = msg.get("project_name", "알 수 없는 프로젝트")
            text = msg.get("text", "")
            socket_path = msg.get("socket_path", session_id)
            token = msg.get("token", "")

            if not session_id:
                writer.write(json.dumps({"ok": False, "error": "session_id 없음"}).encode())
                await writer.drain()
                return

            if event == "notify":
                self.table.upsert_from_notify(session_id, project_name, socket_path, token)
                self.tts_queue.enqueue(project_name, text)
                writer.write(json.dumps({"ok": True}).encode())
            elif event == "detach":
                # /voice-detach: 세션이 스스로 라우팅 후보에서 빠짐
                # ("'멈춰' 이후 재라우팅 문제와 A안" 절). 테이블에 없는
                # session_id면 그냥 False(무시) — 아직 notify로 등록된 적
                # 없는 세션이 detach를 보내는 건 정상 경로가 아니지만, 이 경우도
                # 에러로 취급하지 않고 조용히 넘어간다(다른 이벤트들과 동일한
                # 관대한 처리 원칙).
                found = self.table.mark_detached(session_id)
                writer.write(json.dumps({"ok": True, "found": found}).encode())
            elif event == "attach":
                # /voice-attach: 세션이 스스로 라우팅 후보로 복귀. notify와
                # 동일한 정보(project_name, socket_path, token)가 필요하다 —
                # 처음 attach하는 세션(이전에 notify를 한 번도 안 보낸 경우)도
                # 이 이벤트만으로 테이블에 새로 등록될 수 있다.
                self.table.mark_attached(session_id, project_name, socket_path, token)
                writer.write(json.dumps({"ok": True}).encode())
            elif event == "shutdown":
                # /voice-off가 보내는 종료 신호. session_id 등은 형식만 맞으면
                # 되고 내용은 검사하지 않는다(로컬 127.0.0.1 전용이라 이 정도로
                # 충분 — architecture.md "상주 프로세스 생명주기" 참고).
                writer.write(json.dumps({"ok": True}).encode())
                await writer.drain()
                writer.close()
                self._shutdown_requested = True
                if self._server is not None:
                    self._server.close()
                return
            else:
                writer.write(json.dumps({"ok": False, "error": f"unknown event: {event}"}).encode())

            await writer.drain()
        finally:
            writer.close()

    async def start(self) -> None:
        self._server = await asyncio.start_server(self.handle_client, self.host, self.port)
        addr = self._server.sockets[0].getsockname()
        print(f"[listener] TCP 서버 시작: {addr}")

    async def serve_forever(self) -> None:
        await self.start()
        async with self._server:
            await self._server.serve_forever()


def run_server_in_background(table: SessionTable, tts_queue: TtsQueue,
                              host: str = HOST, port: int = PORT):
    """테스트/수동 실행에서 쓰기 쉽게, 별도 스레드에서 asyncio 서버를 돌린다.

    반환값: (asyncio.AbstractEventLoop, threading.Thread) — 종료 시
    loop.call_soon_threadsafe(loop.stop)으로 멈출 수 있다.
    """
    loop = asyncio.new_event_loop()

    def _run():
        asyncio.set_event_loop(loop)
        server = ListenerServer(table, tts_queue, host, port)
        loop.run_until_complete(server.start())
        loop.run_forever()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    time.sleep(0.3)  # 서버 bind 대기 (테스트 편의용 짧은 대기)
    return loop, thread


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------

def main():
    from voice.tts import TtsEngine  # 지연 임포트: 모델 로딩이 무거워서 main()에서만
    from voice.config import load_settings

    settings = load_settings()
    language_code = settings.get("language", "ko")
    voice_id = settings.get("voice_id")

    print(f"[listener] TTS 모델 로딩 중... (language={language_code}, voice={voice_id})")
    if voice_id:
        tts_engine = TtsEngine(language_code=language_code, voice_id=voice_id)
    else:
        # voice_id가 아직 없으면(온보딩 전 기존 설치) 레거시 기본 모델 경로로 폴백.
        tts_engine = TtsEngine()
    print("[listener] TTS 모델 로딩 완료")

    table = SessionTable()
    tts_queue = TtsQueue(tts_engine)
    tts_queue.start()

    server = ListenerServer(table, tts_queue)
    # 마이크 루프(호출어 → 받아쓰기 → 라우팅). 무거운 STT 모델은 스레드 안에서 로딩되고,
    # 호출어 온보딩이 안 돼 있으면 로그만 남기고 스스로 끝난다 — 음성 요약(TCP)은 그대로 동작.
    mic_loop = MicLoop(table, tts_queue)
    mic_loop.start()

    async def _main():
        await server.start()
        print(f"[listener] 대기 중... (Ctrl+C 또는 /voice-off로 종료)")
        try:
            await server._server.serve_forever()
        except asyncio.CancelledError:
            pass

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
    mic_loop.stop()
    print("\n[listener] 종료")


if __name__ == "__main__":
    main()
