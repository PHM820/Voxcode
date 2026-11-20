# -*- coding: utf-8 -*-
"""verify.cmd에서 호출하는 음성 명령 처리(route_and_send) 자가 점검.

네트워크·node·마이크 없이: 판단 함수(judge_fn)와 전달 함수(send)를 바꿔 끼운다.
기록 파일은 임시 폴더(VOXCODE_HOME)에 쓴다. 한글 리터럴 때문에 cmd -c 대신 별도 .py(UTF-8).
실패하면 0이 아닌 코드로 종료한다.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HOME = Path(tempfile.mkdtemp(prefix="voxcode-verify-"))
os.environ["VOXCODE_HOME"] = str(HOME)
sys.path.insert(0, ".")

import voice.listener as listener  # noqa: E402
from voice.judge import Decision  # noqa: E402
from voice.listener import SessionTable, route_and_send, route_command  # noqa: E402

LOG = HOME / "log.jsonl"


class Sender:
    """send 대역: 보낸 (프로젝트명, 문장)을 모으고, 보낼 때 이미 heard가 기록됐는지 확인."""

    def __init__(self):
        self.calls = []

    def __call__(self, session, text):
        heard = [json.loads(l) for l in LOG.read_text(encoding="utf-8").splitlines()]
        assert any(e["kind"] == "heard" and e["text"] == text for e in heard), "기록 전에 전달됨"
        self.calls.append((session.project_name, text))
        return subprocess.CompletedProcess([], 0, "", "")


def two_sessions():
    t = SessionTable()
    t.upsert_from_notify("k-a", "proj-a", "k-a", "tok1", summary="a 요약")
    t.upsert_from_notify("k-b", "proj-b", "k-b", "tok2", summary="b 요약")  # proj-b가 최근
    return t


def fixed(cmd, target="unknown", cmd_conf=0.95, target_conf=0.95):
    return lambda text, sessions: Decision(cmd, cmd_conf, target, target_conf, "jev")


def paused_names(t):
    return sorted(s.project_name for s in t.all_sessions() if s.paused)


# --- 1. Jev 실패(None / 예외) + 일반 문장 -> 규칙 폴백(방금 알림 온 세션) ---
def raises(text, sessions):
    raise RuntimeError("simulated")
for jf in (lambda text, sessions: None, raises):
    t, s = two_sessions(), Sender()
    r = route_and_send(t, "다음 작업 해줘", judge_fn=jf, send=s)
    assert r["mode"] == "fallback" and s.calls == [("proj-b", "다음 작업 해줘")], r

# --- 2. 대상 애매한 멈춰 -> 아무것도 안 멈춤, 안 보냄, 삑 두 번 ---
for jf in (fixed("stop", "unknown"), fixed("stop", "k-a", target_conf=0.5), fixed("stop", "listener")):
    t, s = two_sessions(), Sender()
    r = route_and_send(t, "멈춰", judge_fn=jf, send=s)
    assert r["mode"] == "stop_ambiguous" and r["beep_twice"] and not s.calls, r
    assert paused_names(t) == [], "애매한 멈춰가 세션을 멈춤"

# --- 3. Jev 실패 + 멈춤 단어: 세션 2개면 아무것도 안 함, 1개면 그 세션 멈춤 ---
t, s = two_sessions(), Sender()
r = route_and_send(t, "번개장터 멈춰", judge_fn=lambda text, sessions: None, send=s)
assert r["mode"] == "stop_ambiguous" and r["beep_twice"] and not s.calls and paused_names(t) == [], r
one = SessionTable()
one.upsert_from_notify("k-x", "proj-x", "k-x", "tok")
s = Sender()
r = route_and_send(one, "그만해", judge_fn=lambda text, sessions: None, send=s)
assert r["mode"] == "stop" and s.calls == [("proj-x", "그만해")] and paused_names(one) == ["proj-x"], r

# --- 4. 확신 있는 멈춰 -> 그 세션 하나에만 전달, 그 세션만 멈춤 ---
t, s = two_sessions(), Sender()
r = route_and_send(t, "a 멈춰", judge_fn=fixed("stop", "k-a"), send=s)
assert r["mode"] == "stop" and s.calls == [("proj-a", "a 멈춰")] and paused_names(t) == ["proj-a"], r

# --- 5. 멈춘 세션에 완료 알림이 와도 멈춤 유지, 규칙 폴백도 고르지 않음 ---
t.upsert_from_notify("k-a", "proj-a", "k-a", "tok1", summary="정리하고 멈춤")
assert paused_names(t) == ["proj-a"], "완료 알림이 멈춘 세션을 살림"
assert route_command(t).project_name == "proj-b", "규칙 폴백이 멈춘 세션을 고름"
s = Sender()
route_and_send(t, "다음 거 해", judge_fn=lambda text, sessions: None, send=s)
assert s.calls == [("proj-b", "다음 거 해")]

# --- 6. 다시 시작 / 전체 멈춰 ---
s = Sender()
r = route_and_send(t, "a 계속해", judge_fn=fixed("resume", "k-a"), send=s)
assert r["mode"] == "resume" and s.calls == [("proj-a", "a 계속해")] and paused_names(t) == [], r
t2 = two_sessions()
t2.set_paused("k-b", True)
s = Sender()
r = route_and_send(t2, "계속해", judge_fn=fixed("resume", "unknown"), send=s)
assert r["mode"] == "resume" and s.calls == [("proj-b", "계속해")], "멈춘 세션이 하나면 그 세션 재개"
s = Sender()
r = route_and_send(t, "전부 멈춰", judge_fn=fixed("stop_all", "all"), send=s)
assert r["mode"] == "stop_all" and len(s.calls) == 2 and paused_names(t) == ["proj-a", "proj-b"], r

# --- 7. 잡음·취소 -> 버림, 삑 두 번 ---
for cmd in ("noise", "cancel"):
    t, s = two_sessions(), Sender()
    r = route_and_send(t, "시청해 주셔서 감사합니다.", judge_fn=fixed(cmd), send=s)
    assert r["mode"] == "dropped" and r["beep_twice"] and not s.calls, r

# --- 8. 확신 있는 지시는 Jev가 고른 세션으로 (알림 순서와 무관), 멈춘 세션을 직접 부르면 풀림 ---
t, s = two_sessions(), Sender()
t.set_paused("k-a", True)
r = route_and_send(t, "a에 키워드 추가해", judge_fn=fixed("instruct", "k-a"), send=s)
assert s.calls == [("proj-a", "a에 키워드 추가해")] and paused_names(t) == [], r

# --- 9. 확신도 경계값: 0.79는 판단 불가(폴백), 0.8은 실행 ---
t, s = two_sessions(), Sender()
r = route_and_send(t, "a 해", judge_fn=fixed("instruct", "k-a", cmd_conf=0.79), send=s)
assert r["mode"] == "fallback" and s.calls == [("proj-b", "a 해")], r
t, s = two_sessions(), Sender()
r = route_and_send(t, "a 해", judge_fn=fixed("instruct", "k-a", cmd_conf=0.8, target_conf=0.8), send=s)
assert r["mode"] == "instruct" and s.calls == [("proj-a", "a 해")], r

# --- 10. 기록 파일 ---
kinds = [json.loads(l)["kind"] for l in LOG.read_text(encoding="utf-8").splitlines()]
assert {"heard", "decision", "sent", "dropped"} <= set(kinds), kinds
state = json.loads((HOME / "state.json").read_text(encoding="utf-8"))
assert {x["project_name"]: x["paused"] for x in state["sessions"]} == {"proj-a": False, "proj-b": False}
assert state["listener_pid"] == os.getpid()

# --- 11. TCP 완료 알림 경로(handle_client): 기록 + 요약 갱신, 멈춤 유지, detach는 모르는 이벤트 ---
import asyncio  # noqa: E402


class FakeReader:
    def __init__(self, msg):
        self.raw = json.dumps(msg, ensure_ascii=False).encode("utf-8")

    async def read(self, n):
        return self.raw


class FakeWriter:
    def __init__(self):
        self.out = b""

    def write(self, b):
        self.out += b

    async def drain(self):
        pass

    def close(self):
        pass


class FakeTts:
    def __init__(self):
        self.items = []

    def enqueue(self, project, summary):
        self.items.append((project, summary))


def call_server(server, msg):
    w = FakeWriter()
    asyncio.run(server.handle_client(FakeReader(msg), w))
    return json.loads(w.out.decode("utf-8"))


t = SessionTable()
tts = FakeTts()
server = listener.ListenerServer(t, tts)
note = {"event": "notify", "session_id": "k-n", "project_name": "proj-n",
        "text": "테스트 다 통과", "socket_path": "k-n", "token": "tok"}
assert call_server(server, note) == {"ok": True}
assert t.get("k-n").last_summary == "테스트 다 통과" and tts.items == [("proj-n", "테스트 다 통과")]
t.set_paused("k-n", True)
call_server(server, note)
assert t.get("k-n").paused, "TCP 완료 알림이 멈춘 세션을 살림"
assert call_server(server, {**note, "event": "detach"})["ok"] is False, "detach 이벤트가 남아 있음"
logged = [json.loads(l) for l in LOG.read_text(encoding="utf-8").splitlines()]
assert any(e["kind"] == "notify" and e["summary"] == "테스트 다 통과" for e in logged)

# --- 12. 옛 규칙이 남아 있지 않음 ---
for gone in ("mark_detached", "mark_attached", "find_by_project_prefix"):
    assert not hasattr(SessionTable, gone), gone
for gone in ("parse_stop_command", "STOP_PREFIX", "should_drop_transcript"):
    assert not hasattr(listener, gone), gone

print("routing checks OK")
