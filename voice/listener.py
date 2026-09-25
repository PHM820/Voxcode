# -*- coding: utf-8 -*-
"""상주 리스너 프로세스 (최소 버전).

docs/architecture.md에 확정된 것만 구현한다. 아직 미정인 세부(받아쓰기
피드백음, 설정 파일 스키마, 프로세스 생명주기 관리)는 TODO로 남긴다.

이 최소 버전이 실제로 왕복하는 것:
  1. 로컬 TCP 서버(127.0.0.1:8765)로 훅이 보내는 완료 알림 JSON을 수신
  2. 세션별 상태 테이블에 반영
  3. 여러 알림이 겹치면 큐에 쌓아 "{프로젝트명}, {요약}" 형식으로 순차 TTS
  4. (테스트 함수) 텍스트를 직접 넘겨 세션 라우팅 규칙 ①~④, "멈춰 {프로젝트명}"
     브로드캐스트 규칙을 검증
  5. 라우팅 결정된 세션에 voice/inject.js를 subprocess로 호출해 postback

범위 밖(스텁):
  - 실시간 마이크 VAD/wakeword/STT — voice/vad.py, voice/wakeword.py, voice/stt.py는
    아직 없음. 이 파일에는 텍스트를 직접 받는 route_and_send()만 있고, 마이크 입력은
    다루지 않는다.
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


class SessionTable:
    """세션별 상태를 관리하는 dict 래퍼. 상주 프로세스 안에서 하나만 존재."""

    def __init__(self):
        self._sessions: dict[str, SessionState] = {}
        self._lock = threading.Lock()

    def upsert_from_notify(self, session_id: str, project_name: str,
                            socket_path: str, token: str) -> SessionState:
        """완료 알림 수신 시 세션 레코드를 갱신(없으면 생성)하고 last_notify_at 찍기."""
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
            return st

    def mark_command_sent(self, session_id: str) -> None:
        with self._lock:
            st = self._sessions.get(session_id)
            if st is not None:
                st.last_command_at = time.time()

    def all_sessions(self) -> list[SessionState]:
        with self._lock:
            return list(self._sessions.values())

    def find_by_project_prefix(self, spoken_text: str) -> Optional[SessionState]:
        """발화가 프로젝트명으로 '시작'하면 그 세션 반환 (라우팅 규칙 ①)."""
        with self._lock:
            for st in self._sessions.values():
                if spoken_text.startswith(st.project_name):
                    return st
        return None

    def most_recent_by_notify(self) -> Optional[SessionState]:
        sessions = self.all_sessions()
        if not sessions:
            return None
        return max(sessions, key=lambda s: s.last_notify_at)

    def most_recent_by_command(self) -> Optional[SessionState]:
        sessions = self.all_sessions()
        if not sessions:
            return None
        candidates = [s for s in sessions if s.last_command_at > 0]
        if not candidates:
            return None
        return max(candidates, key=lambda s: s.last_command_at)


# ---------------------------------------------------------------------------
# 세션 라우팅 (docs/architecture.md "세션 라우팅" 절, 기계적 규칙만 사용)
# ---------------------------------------------------------------------------

def route_command(table: SessionTable, spoken_text: str) -> Optional[SessionState]:
    """일반 음성 명령을 어느 세션으로 보낼지 결정한다. LLM 판단 없이 규칙만.

    우선순위:
      ④ 세션이 하나뿐이면 무조건 그 세션 (먼저 체크하는 게 더 빠르고 규칙과 동치)
      ① 발화가 프로젝트명으로 시작하면 그 세션
      ② 없으면 last_notify_at이 가장 최근인 세션
      ③ 알림이 전혀 없었으면(모든 세션 last_notify_at==0) last_command_at 최신 세션
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

    def start(self) -> None:
        self._thread.start()

    def enqueue(self, project_name: str, summary: str) -> None:
        utterance = f"{project_name}, {summary}"
        self._q.put(utterance)

    def _run(self) -> None:
        while True:
            utterance = self._q.get()
            print(f"[tts-queue] 재생: {utterance!r}")
            self._history.append(utterance)
            try:
                self._tts.speak(utterance)
            except Exception as e:  # noqa: BLE001 - 재생 실패가 큐 전체를 죽이면 안 됨
                print(f"[tts-queue] 재생 실패: {e}", file=sys.stderr)
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
# TCP 서버
# ---------------------------------------------------------------------------

# 메시지 스키마 (이번 구현에서 확정, docs/architecture.md 반영 필요):
# {
#   "event": "notify" | "command",   # notify=완료 알림, command=음성 명령(테스트 경로에서는 안 씀)
#   "session_id": "<CLAUDE_CODE_MESSAGING_SOCKET 경로>",
#   "project_name": "<cwd 폴더명>",
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

    print("[listener] TTS 모델 로딩 중...")
    tts_engine = TtsEngine()
    print("[listener] TTS 모델 로딩 완료")

    table = SessionTable()
    tts_queue = TtsQueue(tts_engine)
    tts_queue.start()

    server = ListenerServer(table, tts_queue)

    async def _main():
        await server.start()
        print(f"[listener] 대기 중... (Ctrl+C로 종료)")
        # TODO: 실시간 마이크 VAD/wakeword/STT 루프는 이 최소 버전 범위 밖.
        # TODO: 상주 프로세스 시작/종료 방법(/voice-on, /voice-off)은 미정 (architecture.md).
        await server._server.serve_forever()

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\n[listener] 종료")


if __name__ == "__main__":
    main()
