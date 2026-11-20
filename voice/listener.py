# -*- coding: utf-8 -*-
"""상주 리스너 프로세스.

docs/architecture.md에 확정된 것만 구현한다. 아직 미정인 세부(설정 파일
스키마 일부, 프로세스 생명주기 관리 스크립트)는 TODO로 남긴다.

이 파일이 실제로 왕복하는 것:
  1. 훅이 ~/.voxcode/inbox/에 남기는 완료·알림 파일을 읽음 (InboxWatcher)
  2. 세션별 상태 테이블에 반영 (~/.voxcode/state.json 스냅숏, voice/record.py)
  3. 여러 알림이 겹치면 큐에 쌓아 "{프로젝트명}, {요약}" 형식으로 순차 TTS
  4. 받아쓴 문장 처리(route_and_send): log.jsonl에 먼저 기록 → 판단(규칙·Jev,
     voice/judge.py)으로 명령(지시·멈춰·전체 멈춰·다시 시작·취소·잡음)과 대상 결정
     → 확신이 낮으면 규칙 폴백("방금 알림 온 세션") → 대상 세션에 전달
  5. 전달은 voice/inject.js를 subprocess로 호출해 postback
  6. 실시간 마이크 루프(MicLoop): 항상 마이크를 열어 VAD+wakeword로 호출어
     대기 → 감지 시 받아쓰기(비프음 + VAD 종료 감지 + STT) → route_and_send
     (architecture.md "다음 설계" 절)

MicLoop은 별도 스레드(daemon)에서 돌고, 메인 스레드는 inbox를 지켜본다.
"""
from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from voice import record

# ---- 고정값 ----
PROJECT_ROOT = Path(__file__).resolve().parent.parent
INJECT_JS = PROJECT_ROOT / "voice" / "inject.js"

# Jev가 판단하지 못했을 때(키 없음·오류·확신 부족) 멈춤 의도로 보는 단어. 이 단어가 있으면
# 대상이 확실하지 않은 한 아무것도 보내지 않는다 — 엉뚱한 세션에 "멈춰"를 보내지 않기 위해.
STOP_WORDS = ("멈춰", "멈춰라", "그만", "스톱", "중지")


# ---------------------------------------------------------------------------
# 세션 상태 테이블
# ---------------------------------------------------------------------------

@dataclass
class SessionState:
    """세션 하나의 레코드. state.json의 sessions 항목과 같은 필드."""

    session_id: str  # = CLAUDE_CODE_MESSAGING_SOCKET 경로 자체 (별도 uuid 없음)
    project_name: str
    socket_path: str
    token: str
    last_summary: str = ""
    last_notify_at: float = 0.0
    last_command_at: float = 0.0
    # "멈춰"를 받은 세션. 다시 시작하거나 사용자가 그 세션을 직접 부를 때까지 규칙 폴백의
    # 기본 대상에서 빠진다. 완료 알림(notify)으로는 풀리지 않는다 — 멈춘 세션이 정리하며
    # 보낸 완료 알림이 다시 기본 대상으로 만들면 안 되기 때문.
    paused: bool = False


class SessionTable:
    """세션별 상태를 관리하는 dict 래퍼. 상주 프로세스 안에서 하나만 존재.
    바뀔 때마다 ~/.voxcode/state.json에 스냅숏을 쓴다."""

    def __init__(self):
        self._sessions: dict[str, SessionState] = {}
        self._lock = threading.Lock()

    def _save(self) -> None:
        record.write_state(self.all_sessions())

    def upsert_from_notify(self, session_id: str, project_name: str,
                            socket_path: str, token: str, summary: str = "",
                            at: Optional[float] = None) -> SessionState:
        """완료 알림 수신 시 세션 레코드를 갱신(없으면 생성). paused는 건드리지 않는다.
        at: 알림 시각(기본 지금). 리스너가 꺼져 있던 동안 쌓인 알림은 원래 시각을 써서 "방금 알림 온 세션"이 되지 않게."""
        with self._lock:
            st = self._sessions.get(session_id)
            if st is None:
                st = SessionState(session_id, project_name, socket_path, token)
                self._sessions[session_id] = st
            else:
                # 프로젝트명/소켓/토큰은 최신 값으로 갱신 (재시작 등으로 바뀔 수 있음)
                st.project_name = project_name
                st.socket_path = socket_path
                st.token = token
            if summary:
                st.last_summary = summary
            st.last_notify_at = time.time() if at is None else at
        self._save()
        return st

    def mark_command_sent(self, session_id: str) -> None:
        with self._lock:
            st = self._sessions.get(session_id)
            if st is not None:
                st.last_command_at = time.time()
        self._save()

    def set_paused(self, session_id: str, paused: bool) -> None:
        with self._lock:
            st = self._sessions.get(session_id)
            if st is not None:
                st.paused = paused
        self._save()

    def get(self, session_id: str) -> Optional[SessionState]:
        with self._lock:
            return self._sessions.get(session_id)

    def all_sessions(self) -> list[SessionState]:
        with self._lock:
            return list(self._sessions.values())


@dataclass
class ListenerContext:
    """세션 밖 리스너 상황. TtsQueue·route_and_send·알림 처리가 함께 쓴다."""

    quiet: bool = False   # 조용히 모드: 질문·권한 알림(kind=notification)만 읽고 완료 요약은 기록만
    last_said: str = ""   # "다시 말해줘"용 — 마지막으로 읽기 시작한 문장
    last_catchup: str = ""  # "밀린 거 듣기"를 마지막으로 한 시각(ISO) — 그 뒤 소식만 읽는다
    # 전체 지시 확인 대기: (보낼 문장, 대상 session_id 목록, 만료 monotonic 시각)
    pending_all: Optional[tuple] = None

    def set_quiet(self, quiet: bool) -> None:
        self.quiet = quiet
        record.set_state_field("quiet", quiet)

    def set_last_catchup(self, ts: str) -> None:
        self.last_catchup = ts
        record.set_state_field("last_catchup", ts)


def should_speak_notice(ctx: ListenerContext, kind: str) -> bool:
    """조용히 모드에서는 질문·권한 알림만 읽는다 (Jev 종류 판단은 처음 1주 기록만 — 4단계)."""
    return not ctx.quiet or kind == "notification"


# ---------------------------------------------------------------------------
# 규칙 폴백 (Jev가 판단 못 했을 때)
# ---------------------------------------------------------------------------

def route_command(table: SessionTable) -> Optional[SessionState]:
    """규칙만으로 기본 대상을 고른다.

      ① 세션이 하나뿐이면 그 세션 (멈춤이어도 — 잘못 갈 다른 세션이 없다)
      ② 멈추지 않은 세션 중 last_notify_at이 가장 최근인 세션 ("방금 알림 온 세션")
      ③ 알림이 전혀 없었으면 멈추지 않은 세션 중 last_command_at이 가장 최근인 세션
    """
    sessions = table.all_sessions()
    if len(sessions) == 1:
        return sessions[0]
    live = [s for s in sessions if not s.paused]
    for attr in ("last_notify_at", "last_command_at"):
        candidates = [s for s in live if getattr(s, attr) > 0]
        if candidates:
            return max(candidates, key=lambda s: getattr(s, attr))
    return None


def _has_stop_word(text: str) -> bool:
    return any(w in text for w in STOP_WORDS)


# "대기": 아무 데도 보내지 않고 다시 호출어를 기다린다. 문장 전체가 이 말일 때만 —
# "대기열 기능 만들어" 같은 지시를 삼키지 않게 부분 일치는 쓰지 않는다.
WAIT_WORDS = ("대기", "대기해", "대기해줘", "대기해요", "대기할게", "대기상태")


def _is_wait(text: str) -> bool:
    return re.sub(r"[\s.,!?~…]", "", text) in WAIT_WORDS


# ---------------------------------------------------------------------------
# inject.js 호출 (postback)
# ---------------------------------------------------------------------------

def send_postback(session: SessionState, text: str) -> subprocess.CompletedProcess:
    """voice/inject.js를 subprocess로 실행해 해당 세션에 텍스트를 postback.

    inject.js는 CLAUDE_CODE_MESSAGING_SOCKET / CLAUDE_CODE_MESSAGING_TOKEN
    환경변수를 읽으므로, 대상 세션의 값을 해당 프로세스의 env로 넘긴다.
    실제 postback이 성공하려면 진짜 Claude Code 세션이 그 소켓을 열고 있어야 한다.
    """
    import os

    env = os.environ.copy()
    env["CLAUDE_CODE_MESSAGING_SOCKET"] = session.socket_path
    env["CLAUDE_CODE_MESSAGING_TOKEN"] = session.token

    return subprocess.run(
        ["node", str(INJECT_JS), text],
        env=env,
        capture_output=True,
        encoding="utf-8",  # Windows 기본(cp949)로 두면 한글 stdout/stderr 디코딩 시 죽음 (실측 확인)
        errors="replace",
        timeout=10,
    )


# ---------------------------------------------------------------------------
# 받아쓴 문장 처리: 기록 → 판단(규칙·Jev) → 전달
# ---------------------------------------------------------------------------

def _deliver(table: SessionTable, targets: list[SessionState], text: str, send) -> list[dict]:
    results = []
    for st in targets:
        try:
            proc = send(st, text)
            ok = proc.returncode == 0
            detail = (proc.stderr or "").strip()[-300:]
        except Exception as e:  # noqa: BLE001 - 한 세션 실패가 나머지 전달을 막으면 안 됨
            ok, detail = False, str(e)
        table.mark_command_sent(st.session_id)
        results.append({"project_name": st.project_name, "ok": ok, "detail": detail})
    record.log_event("sent", text=text, results=results)
    return results


LISTENER_COMMANDS = ("list", "repeat", "quiet", "verbose", "status", "catch_up")
CONFIRM_TIMEOUT_S = 30.0
YES_WORDS = ("응", "네", "예", "그래", "보내", "좋아", "ㅇㅇ")
NO_WORDS = ("아니", "취소", "하지 마", "하지마", "말아", "보내지 마")
CATCH_UP_RAW_MAX = 5  # 서브 관리자가 없을 때 그대로 읽을 최근 소식 수


def _summarize(ask_manager, instruction: str, items: list) -> str:
    """서브 관리자에게 귀로 들을 한두 문장 요약을 부탁한다. 못 받으면 빈 문자열."""
    ans = ask_manager({"type": "summarize", "instruction": instruction, "items": items})
    say = ans.get("say") if isinstance(ans, dict) else None
    return say.strip() if isinstance(say, str) else ""


def _listener_reply(table: SessionTable, ctx: ListenerContext, command: str,
                    target: Optional[SessionState], ask_manager) -> str:
    """리스너가 세션에 보내지 않고 직접 답하는 명령의 읽을 문장."""
    sessions = table.all_sessions()
    if command == "list":
        if not sessions:
            return "열린 프로젝트가 없습니다."
        names = [s.project_name + (" 멈춤" if s.paused else "") for s in sessions]
        return "열린 프로젝트는 " + ", ".join(names) + "입니다."
    if command == "repeat":
        return ctx.last_said or "다시 읽을 안내가 없습니다."
    if command == "quiet":
        ctx.set_quiet(True)
        return "조용히 할게요. 질문만 읽어 드립니다."
    if command == "verbose":
        ctx.set_quiet(False)
        return "이제 다 알려 드릴게요."
    if command == "catch_up":
        news = [{"project": e.get("project_name"), "summary": e.get("summary"), "ts": e.get("ts")}
                for e in record.read_events(ctx.last_catchup, kind="notify")]
        ctx.set_last_catchup(record.now_iso())
        if not news:
            return "새로 들어온 소식이 없습니다."
        said = _summarize(ask_manager, "자리를 비운 동안 프로젝트들에서 온 소식이다. 프로젝트별로 한두 문장에 묶어라.", news)
        if said:
            return said
        recent = news[-CATCH_UP_RAW_MAX:]
        head = f"소식 {len(news)}개 중 최근 {len(recent)}개입니다. " if len(news) > len(recent) else ""
        return head + " ".join(f"{n['project']}: {n['summary']}" for n in recent)
    # status: 대상 하나면 그 세션 요약 그대로, 여럿이면 서브 관리자가 묶고 못 하면 이어 읽기
    picked = [target] if target else sessions
    if not picked:
        return "열린 프로젝트가 없습니다."
    raw = " ".join(f"{s.project_name}: {s.last_summary or '아직 요약이 없습니다.'}" for s in picked)
    if len(picked) > 1:
        said = _summarize(ask_manager, "프로젝트별 마지막 상황이다. 한두 문장으로 묶어라.",
                          [{"project": s.project_name, "paused": s.paused, "summary": s.last_summary}
                           for s in picked])
        return said or raw
    return raw


def _manager_decision(ans: dict, sessions: list[SessionState], judge_mod):
    """서브 관리자 답을 Decision으로. 되물을 문장이 있으면 (None, 문장)."""
    ask_back = ans.get("ask_back") if isinstance(ans.get("ask_back"), str) else ""
    command, target = ans.get("command"), ans.get("target")
    if command not in judge_mod.COMMANDS:
        return None, ask_back.strip()
    specials = (judge_mod.TARGET_ALL, judge_mod.TARGET_LISTENER, judge_mod.TARGET_UNKNOWN)
    if target in specials:
        key, conf = target, (0.0 if target == judge_mod.TARGET_UNKNOWN else 1.0)
    else:
        hits = [s for s in sessions if s.project_name.lower() == str(target).lower()]
        key, conf = (hits[0].session_id, 1.0) if len(hits) == 1 else (judge_mod.TARGET_UNKNOWN, 0.0)
    if conf == 0.0 and ask_back.strip() and command not in LISTENER_COMMANDS + ("noise", "cancel", "stop_all"):
        return None, ask_back.strip()
    return judge_mod.Decision(command, 1.0, key, conf, "manager"), ""


def _is_reply(text: str, words) -> bool:
    t = text.strip().strip(".!?, ")
    return any(t.startswith(w) for w in words)


def route_and_send(table: SessionTable, text: str, judge_fn=None, send=None,
                   ctx: Optional[ListenerContext] = None, ask_manager=None) -> dict:
    """받아쓴 문장 하나를 처리한다 (docs/architecture.md "다음 설계" 1~3단계).

    순서: 기록 → (전체 지시 확인 대기 중이면 응/아니 규칙) → 규칙·Jev 판단 → 애매하면 서브 관리자
    → 그래도 모르면 규칙 폴백. judge_fn·send·ask_manager는 테스트에서 바꿔 끼우는 용도.
    반환: {"mode", "beep_twice", "targets"(보낸 프로젝트명), "say"(읽을 문장), "results", "decision"}.
    """
    from voice import judge as judge_mod
    from voice import manager as manager_mod

    judge_fn = judge_fn or judge_mod.judge
    send = send or send_postback
    ctx = ctx or ListenerContext()
    ask_manager = ask_manager or manager_mod.ask

    record.log_event("heard", text=text)  # 기록이 항상 먼저

    sessions = table.all_sessions()
    mode, targets, reason, say = "", [], "", ""
    pause_after: Optional[bool] = None
    d = None

    # 전체 지시 확인 대기 중: "응"이면 보내고, "아니"면 취소, 다른 말이면 확인을 버리고 평소대로
    pending, ctx.pending_all = ctx.pending_all, None
    if pending and time.monotonic() < pending[2]:
        if _is_reply(text, YES_WORDS):
            mode, targets = "instruct_all", [s for s in (table.get(k) for k in pending[1]) if s]
            text_to_send = pending[0]
        elif _is_reply(text, NO_WORDS):
            mode, say = "instruct_all_cancelled", "보내지 않았습니다."
    if mode:
        record.log_event("decision", text=text, mode=mode, target=[t.project_name for t in targets],
                         source="rule", reason="전체 지시 확인 응답", say=say)
        results = _deliver(table, targets, text_to_send, send) if targets else []
        return {"mode": mode, "beep_twice": not targets and not say,
                "targets": [t.project_name for t in targets], "say": say,
                "results": results, "decision": None}

    # "대기"는 규칙으로 바로 끝낸다 — Jev·관리자를 부르지 않고, 폴백으로 세션에 새지 않게
    if _is_wait(text):
        record.log_event("decision", text=text, mode="wait", target=[], source="rule", reason="대기")
        return {"mode": "wait", "beep_twice": True, "targets": [], "say": "",
                "results": [], "decision": None}

    try:
        d = judge_fn(text, [
            {"key": s.session_id, "project": s.project_name,
             "summary": s.last_summary, "paused": s.paused}
            for s in sessions
        ])
    except Exception:  # noqa: BLE001
        d = None

    threshold = judge_mod.CONFIDENCE_THRESHOLD
    ok_cmd = d is not None and d.command_conf >= threshold
    ok_target = d is not None and d.target_conf >= threshold

    # 3단계: Jev가 애매하면(판단 불가·명령 확신 부족, 또는 멈춰·다시 시작의 대상 애매) 서브 관리자에게
    target_unclear = (ok_cmd and d.command in ("stop", "resume") and len(sessions) > 1
                      and not (ok_target and (table.get(d.target) or d.target == judge_mod.TARGET_ALL)))
    if not ok_cmd or target_unclear:
        ans = ask_manager({
            "type": "judge", "text": text, "commands": list(judge_mod.COMMANDS),
            "jev": None if d is None else {"command": d.command, "command_conf": d.command_conf,
                                           "target_conf": d.target_conf},
            "sessions": [{"project": s.project_name, "paused": s.paused, "summary": s.last_summary}
                         for s in sessions],
            "recent": record.tail_events(20),
        })
        if isinstance(ans, dict):
            md, ask_back = _manager_decision(ans, sessions, judge_mod)
            if md is not None:
                d, ok_cmd, ok_target = md, True, md.target_conf >= threshold
            elif ask_back:
                mode, say = "ask_back", ask_back
        if not mode and not ok_cmd:
            reason = "판단 불가(관리자 없음·시간 초과)" if d is None else f"명령 확신 부족({d.command_conf:.2f})"

    def target_session() -> Optional[SessionState]:
        """세션 하나를 향한 명령의 대상. 세션이 하나뿐이면 규칙으로 확정."""
        if len(sessions) == 1:
            return sessions[0]
        if ok_target:
            return table.get(d.target)
        return None

    if mode:
        pass  # 서브 관리자가 되물음
    elif not ok_cmd:
        if _has_stop_word(text):
            only = sessions[0] if len(sessions) == 1 else None
            mode, targets, pause_after = ("stop", [only], True) if only else ("stop_ambiguous", [], None)
        else:
            fb = route_command(table)
            mode, targets = ("fallback", [fb]) if fb else ("no_target", [])
    elif d.command in ("noise", "cancel"):
        mode = "dropped"
    elif d.command in LISTENER_COMMANDS:
        mode = d.command
        say = _listener_reply(table, ctx, d.command, table.get(d.target) if ok_target else None, ask_manager)
    elif d.command == "instruct_all":
        live = [s for s in sessions if not s.paused]
        if live:
            # 확인 문장은 템플릿 — 서브 관리자에게 맡기면 매번 최대 20초를 더 기다린다
            ctx.pending_all = (text, [s.session_id for s in live], time.monotonic() + CONFIRM_TIMEOUT_S)
            mode, say = "confirm_all", f"프로젝트 {len(live)}개에 '{text}'를 보낼까요?"
        else:
            mode, say = "no_target", "보낼 프로젝트가 없습니다."
    elif d.command == "instruct":
        st = target_session() or route_command(table)
        mode, targets = ("instruct", [st]) if st else ("no_target", [])
        if st is not None and st.paused and (ok_target or len(sessions) == 1):
            pause_after = False  # 사용자가 그 세션을 직접 불렀다
    elif d.command == "stop_all" or (d.command == "stop" and ok_target and d.target == judge_mod.TARGET_ALL):
        mode, targets, pause_after = "stop_all", list(sessions), True
    elif d.command == "stop":
        st = target_session()
        mode, targets, pause_after = ("stop", [st], True) if st else ("stop_ambiguous", [], None)
    elif d.command == "resume":
        st = target_session()
        if st is None:
            paused = [s for s in sessions if s.paused]
            st = paused[0] if len(paused) == 1 else None
        mode, targets, pause_after = ("resume", [st], False) if st else ("resume_ambiguous", [], None)
    else:  # judge가 COMMANDS 밖 값을 줄 일은 없지만 안전하게
        mode = "dropped"

    record.log_event(
        "decision", text=text, mode=mode,
        command=d.command if d else None, target=[t.project_name for t in targets],
        command_conf=d.command_conf if d else None, target_conf=d.target_conf if d else None,
        source=(d.source if ok_cmd else "fallback") if d else "fallback", reason=reason, say=say,
    )

    if mode == "dropped":
        record.log_event("dropped", text=text, reason=d.command)
    if pause_after is not None:
        for st in targets:
            table.set_paused(st.session_id, pause_after)
    results = _deliver(table, targets, text, send) if targets else []

    return {
        "mode": mode,
        "beep_twice": not targets and not say,
        "targets": [t.project_name for t in targets],
        "say": say,
        "results": results,
        "decision": d,
    }


# ---------------------------------------------------------------------------
# TTS 재생 큐 (여러 알림이 겹치면 순서대로)
# ---------------------------------------------------------------------------

class TtsQueue:
    """도착 순서대로 TTS를 순차 재생하는 큐.

    threading.Thread 하나가 큐를 소비한다 (TTS 재생은 블로킹이라 inbox 감시와 분리).
    받아쓰는 동안(hold)은 다음 문장을 시작하지 않고 미룬다 — 마이크에 TTS 소리가 섞이지 않게.
    """

    def __init__(self, tts_engine, ctx: Optional[ListenerContext] = None):
        self.ctx = ctx or ListenerContext()
        self._q: queue.Queue[str] = queue.Queue()
        self._tts = tts_engine
        self._thread = threading.Thread(target=self._run, daemon=True)
        # 호출어로 재생을 끊을 때 쓰는 상태. sounddevice 재생은 self._tts.speak()가
        # 블로킹으로 처리하므로, "지금 재생 중"임을 MicLoop이 확인할 플래그가 필요하다.
        self._speaking = threading.Event()
        self._interrupt_requested = threading.Event()
        self.hold = threading.Event()  # MicLoop이 받아쓰는 동안 set

    def start(self) -> None:
        self._thread.start()

    def enqueue(self, project_name: str, summary: str) -> None:
        self.say(f"{project_name}, {summary}")

    def say(self, utterance: str) -> None:
        self._q.put(utterance)

    @property
    def is_speaking(self) -> bool:
        """MicLoop이 호출어 감지 시 재생 중인지 확인할 때 쓴다."""
        return self._speaking.is_set()

    def interrupt(self) -> None:
        """현재 재생 중인 TTS를 즉시 중단시킨다 (호출어 감지 시 MicLoop이 호출)."""
        self._interrupt_requested.set()
        try:
            self._tts.stop()
        except Exception as e:  # noqa: BLE001 - 중단 실패해도 루프는 계속돼야 함
            print(f"[tts-queue] 중단 실패: {e}", file=sys.stderr)

    def _run(self) -> None:
        while True:
            utterance = self._q.get()
            while self.hold.is_set():
                time.sleep(0.1)
            print(f"[tts-queue] 재생: {utterance!r}")
            self.ctx.last_said = utterance
            self._interrupt_requested.clear()
            self._speaking.set()
            try:
                self._tts.speak(utterance)
            except Exception as e:  # noqa: BLE001 - 재생 실패가 큐 전체를 죽이면 안 됨
                print(f"[tts-queue] 재생 실패: {e}", file=sys.stderr)
            finally:
                self._speaking.clear()
            self._q.task_done()


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
# 실시간 마이크 루프 (architecture.md "3. 유휴 상태에서 호출어로 명령")
# ---------------------------------------------------------------------------

MIC_SAMPLE_RATE = 16000  # voice/vad.py, voice/stt.py 모두 16kHz 기준
DICTATION_MAX_S = 15.0  # 받아쓰기 최대 길이 안전장치 (무한정 녹음 방지)


class MicLoop:
    """상시 마이크 루프: 호출어 대기 → 받아쓰기 → 라우팅. TTS 재생 중 호출어가 들리면 재생을 끊는다.

    별도 스레드(daemon)에서 run()을 실행해 inbox 감시와 동시에 돈다
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
        except Exception as e:  # noqa: BLE001 - 마이크 루프가 죽어도 음성 요약(inbox)은 살아있어야 함
            print(f"[mic-loop] 치명적 오류로 중단: {e}", file=sys.stderr)

    def run(self) -> None:
        """상시 루프: sounddevice 입력 스트림 하나를 열어 계속 청크를 읽는다."""
        import sounddevice as sd
        from voice.vad import CHUNK_SAMPLES

        if not self._wake_detector.is_onboarded():
            print(
                f"[mic-loop] 호출어 '{self._wake_detector.wake_word}' 온보딩이 안 돼 "
                f"있어 마이크 루프를 시작하지 않습니다. 프로젝트 루트에서 "
                f"'.venv\\Scripts\\python.exe -m voice.wakeword onboard'를 먼저 실행하세요.",
                file=sys.stderr,
            )
            return

        print("[mic-loop] 마이크 루프 시작 (호출어 대기)")
        with sd.InputStream(samplerate=self.sample_rate, channels=1,
                             dtype=np.float32, blocksize=CHUNK_SAMPLES) as stream:
            while not self._stop.is_set():
                # TTS 재생 중에도 호출어로만 받아쓰기에 들어간다. 말소리만으로 끼어들게(바지-인)
                # 했더니 노트북 내장 마이크가 TTS 소리 자체를 사람 말로 착각할 수 있어 뺐다(2026-11-20).
                self._wait_for_wakeword(stream)
                if self._stop.is_set():
                    break
                print("[mic-loop] 호출어 감지: 받아쓰기 진입")
                if self.tts_queue.is_speaking:
                    self.tts_queue.interrupt()
                self.tts_queue.hold.set()
                try:
                    self._dictation_cycle(stream, play_entry_beep=True)
                finally:
                    self.tts_queue.hold.clear()

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

        def _on_detect(detection: dict) -> None:
            # 임계값 조정용 기록 — 오탐이 나면 이 거리와 직후 heard를 보고 판단한다.
            record.log_event("wake", distance=round(float(detection.get("distance", -1)), 4))
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

        result = route_and_send(self.table, text, ctx=self.tts_queue.ctx)
        self.last_route_result = result
        print(f"[mic-loop] 처리 결과: mode={result['mode']} targets={result['targets']}")
        if result["say"]:
            self.tts_queue.say(result["say"])
        if result["beep_twice"]:  # 버림·대상 애매 — 아무 데도 안 보냈다는 신호
            play_beep_blocking(BEEP_LOW_HZ)
            time.sleep(0.12)
            play_beep_blocking(BEEP_LOW_HZ)


# ---------------------------------------------------------------------------
# 훅 → 리스너: ~/.voxcode/inbox/ 파일 (4단계, TCP 서버 대체)
# ---------------------------------------------------------------------------

# inbox 파일 하나 = JSON 하나:
# {
#   "event": "notify" | "shutdown",
#     # notify=완료·알림(hooks/_common.py), shutdown=/voice-off 종료 신호(voice/control.py)
#   "kind": "stop" | "notification",   # notify만: Stop 훅(완료 요약) / Notification 훅(권한·질문)
#   "session_id", "socket_path": "<CLAUDE_CODE_MESSAGING_SOCKET>",  # 지금은 같은 값
#   "project_name": "<cwd 폴더명>", "text": "<요약·알림 문구>",
#   "token": "<CLAUDE_CODE_MESSAGING_TOKEN>", "ts": <time.time()>
# }

INBOX_POLL_S = 0.3
HEARTBEAT_S = 2.0      # 살아 있음 표시(alive 파일) 갱신 간격
STALE_NOTICE_S = 60.0  # 리스너가 켜지기 이만큼 전에 온 알림은 세션 등록만 하고 읽지 않는다


def inbox_dir() -> Path:
    return record.home() / "inbox"


def alive_file() -> Path:
    return record.home() / "listener.alive"


def is_listener_alive(max_age_s: float = HEARTBEAT_S * 3) -> bool:
    """리스너가 살아 있는지: alive 파일이 최근에 갱신됐는지로 본다(PID 재사용 걱정 없음)."""
    try:
        return time.time() - alive_file().stat().st_mtime < max_age_s
    except OSError:
        return False


class InboxWatcher:
    """inbox 폴더를 주기적으로 읽어 알림을 처리한다. shutdown 이벤트를 받으면 process_once가 True."""

    def __init__(self, table: SessionTable, tts_queue: "TtsQueue", started_at: Optional[float] = None,
                 classify=None):
        self.table = table
        self.tts_queue = tts_queue
        self.started_at = time.time() if started_at is None else started_at
        self._classify = classify  # 테스트 주입용. None이면 voice.judge.classify_notice
        self._last_beat = 0.0

    def beat(self) -> None:
        now = time.time()
        if now - self._last_beat >= HEARTBEAT_S:
            try:
                alive_file().write_text(str(os.getpid()), encoding="utf-8")
            except OSError:
                pass
            self._last_beat = now

    def process_once(self) -> bool:
        self.beat()
        shutdown = False
        for path in sorted(inbox_dir().glob("*.json")):
            try:
                msg = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(msg, dict):
                    raise ValueError("JSON 객체가 아님")
                shutdown = self.handle(msg) or shutdown
                path.unlink()
            except Exception as e:  # noqa: BLE001 - 파일 하나가 깨져도 계속, 같은 파일을 반복해 읽지 않게 치움
                print(f"[inbox] 처리 실패 {path.name}: {e}", file=sys.stderr)
                bad = inbox_dir() / "bad"
                bad.mkdir(exist_ok=True)
                try:
                    os.replace(path, bad / path.name)
                except OSError:
                    pass
        return shutdown

    def handle(self, msg: dict) -> bool:
        event = msg.get("event", "notify")
        ts = float(msg.get("ts") or 0)
        if event == "shutdown":
            # 리스너가 꺼져 있을 때 남은 종료 신호로 새 리스너가 바로 꺼지면 안 된다
            return ts >= self.started_at
        if event != "notify":
            raise ValueError(f"알 수 없는 이벤트: {event}")
        session_id = msg.get("session_id")
        if not session_id:
            raise ValueError("session_id 없음")
        project_name = msg.get("project_name", "알 수 없는 프로젝트")
        text = msg.get("text", "")
        kind = msg.get("kind", "stop")  # stop=완료 요약, notification=권한·질문 알림
        stale = ts < self.started_at - STALE_NOTICE_S
        record.log_event("notify", project_name=project_name, summary=text, notice=kind, stale=stale)
        # 멈춘 세션의 완료 알림도 요약은 갱신하지만 멈춤은 풀지 않는다
        self.table.upsert_from_notify(session_id, project_name, msg.get("socket_path", session_id),
                                      msg.get("token", ""), summary=text, at=ts if stale else None)
        if stale:
            return False
        # 4단계: Jev 종류 판단은 처음 1주 기록만 (읽기 기준은 아직 훅 종류)
        from voice import judge as judge_mod
        judged = (self._classify or judge_mod.classify_notice)(text)
        if judged is not None:
            record.log_event("notice_kind", project_name=project_name, notice_type=judged[0], conf=judged[1])
        if should_speak_notice(self.tts_queue.ctx, kind):
            self.tts_queue.enqueue(project_name, text)
        return False


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------

def main():
    from voice.tts import TtsEngine  # 지연 임포트: 모델 로딩이 무거워서 main()에서만
    from voice.config import load_settings

    started_at = time.time()
    settings = load_settings()
    language_code, voice_id = settings["language"], settings["voice_id"]

    print(f"[listener] TTS 모델 로딩 중... (language={language_code}, voice={voice_id})")
    tts_engine = TtsEngine(language_code=language_code, voice_id=voice_id)
    print("[listener] TTS 모델 로딩 완료")

    table = SessionTable()
    tts_queue = TtsQueue(tts_engine)
    tts_queue.start()
    inbox_dir().mkdir(parents=True, exist_ok=True)
    watcher = InboxWatcher(table, tts_queue, started_at=started_at)
    record.write_state([])

    # 마이크 루프(호출어 → 받아쓰기 → 처리). 무거운 STT 모델은 스레드 안에서 로딩되고,
    # 호출어 온보딩이 안 돼 있으면 로그만 남기고 스스로 끝난다 — 음성 요약(inbox)은 그대로 동작.
    mic_loop = MicLoop(table, tts_queue)
    mic_loop.start()

    print("[listener] 대기 중... (Ctrl+C 또는 /voice-off로 종료)")
    try:
        while not watcher.process_once():
            time.sleep(INBOX_POLL_S)
    except KeyboardInterrupt:
        pass
    mic_loop.stop()
    try:
        alive_file().unlink()
    except OSError:
        pass
    print("\n[listener] 종료")


if __name__ == "__main__":
    main()
