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
    t.upsert_from_notify("k-b", "proj-b", "k-b", "tok2", summary="b 요약")
    # Windows time.time()은 해상도가 거칠어 두 알림이 같은 시각이 될 수 있다 — 순서를 명시
    t.get("k-b").last_notify_at = t.get("k-a").last_notify_at + 1  # proj-b가 최근
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

# --- 11. inbox 완료 알림 경로(InboxWatcher): 기록 + 요약 갱신, 멈춤 유지, 조용히 모드 ---
class FakeTts:
    def __init__(self):
        self.items = []
        self.ctx = listener.ListenerContext()

    def enqueue(self, project, summary):
        self.items.append((project, summary))


t = SessionTable()
tts = FakeTts()
kinds_seen = []
watcher = listener.InboxWatcher(t, tts, classify=lambda text: kinds_seen.append(text) or ("done", 0.9))
now = __import__("time").time()
note = {"event": "notify", "session_id": "k-n", "project_name": "proj-n",
        "text": "테스트 다 통과", "socket_path": "k-n", "token": "tok", "ts": now}
assert watcher.handle(note) is False
assert t.get("k-n").last_summary == "테스트 다 통과" and tts.items == [("proj-n", "테스트 다 통과")]
t.set_paused("k-n", True)
watcher.handle(note)
assert t.get("k-n").paused, "완료 알림이 멈춘 세션을 살림"
logged = [json.loads(l) for l in LOG.read_text(encoding="utf-8").splitlines()]
assert any(e["kind"] == "notify" and e["summary"] == "테스트 다 통과" for e in logged)
assert any(e["kind"] == "notice_kind" and e.get("notice_type") == "done" and e.get("conf") == 0.9 for e in logged), "Jev 종류 판단 기록 없음"
tts.ctx.quiet = True
tts.items.clear()
watcher.handle(note)
assert tts.items == [], "조용히 모드에서 완료 요약을 읽음"
watcher.handle({**note, "kind": "notification", "text": "권한 필요"})
assert tts.items == [("proj-n", "권한 필요")], "조용히 모드에서 질문·권한 알림을 안 읽음"

# --- 11-2. 리스너가 직접 답하는 명령 (2단계): 세션에 안 보냄, 삑 없음, 읽을 문장 ---
from voice.listener import ListenerContext  # noqa: E402

t, s, ctx = two_sessions(), Sender(), ListenerContext()
t.set_paused("k-a", True)
r = route_and_send(t, "뭐 열려 있어", judge_fn=fixed("list", "listener"), send=s, ctx=ctx)
assert r["mode"] == "list" and not s.calls and not r["beep_twice"], r
assert "proj-a 멈춤" in r["say"] and "proj-b" in r["say"], r["say"]
ctx.last_said = "proj-b, 테스트 통과"
r = route_and_send(t, "다시 말해줘", judge_fn=fixed("repeat", "listener"), send=s, ctx=ctx)
assert r["say"] == "proj-b, 테스트 통과" and not s.calls
r = route_and_send(t, "a 어떻게 됐어", judge_fn=fixed("status", "k-a"), send=s, ctx=ctx)
assert "a 요약" in r["say"] and "b 요약" not in r["say"] and not s.calls, r["say"]
r = route_and_send(t, "다들 어디까지 했어", judge_fn=fixed("status", "all"), send=s, ctx=ctx)
assert "a 요약" in r["say"] and "b 요약" in r["say"], r["say"]
r = route_and_send(t, "조용히 해", judge_fn=fixed("quiet", "listener"), send=s, ctx=ctx)
assert ctx.quiet and json.loads((HOME / "state.json").read_text(encoding="utf-8"))["quiet"] is True
assert not listener.should_speak_notice(ctx, "stop") and listener.should_speak_notice(ctx, "notification")
route_and_send(t, "다 알려줘", judge_fn=fixed("verbose", "listener"), send=s, ctx=ctx)
assert not ctx.quiet and listener.should_speak_notice(ctx, "stop") and not s.calls

# --- 13. "대기": 아무 데도 안 보냄, 판단기·관리자도 안 부름, 삑 두 번 ---
def judge_must_not_run(text, sessions):
    raise AssertionError("대기인데 판단기가 호출됨")
def manager_must_not_run(q):
    raise AssertionError("대기인데 관리자가 호출됨")
for said in ("대기", "대기해.", " 대기 해 줘 ", "대기!"):
    t, s = two_sessions(), Sender()
    r = route_and_send(t, said, judge_fn=judge_must_not_run, send=s, ask_manager=manager_must_not_run)
    assert r["mode"] == "wait" and r["beep_twice"] and not s.calls and not r["say"], (said, r)
# 전체 지시 확인 중에 "대기" → 확인을 버리고 아무것도 안 보냄
t, s, ctx = two_sessions(), Sender(), listener.ListenerContext()
route_and_send(t, "다들 커밋해", judge_fn=fixed("instruct_all", "all"), send=s, ctx=ctx)
r = route_and_send(t, "대기", judge_fn=judge_must_not_run, send=s, ctx=ctx)
assert r["mode"] == "wait" and not s.calls and ctx.pending_all is None, r
# "대기"가 들어간 지시는 삼키지 않는다
t, s = two_sessions(), Sender()
r = route_and_send(t, "대기열 기능 만들어줘", judge_fn=fixed("instruct", "k-a"), send=s)
assert r["mode"] == "instruct" and s.calls == [("proj-a", "대기열 기능 만들어줘")], r

# --- 12. 옛 규칙이 남아 있지 않음 ---
for gone in ("mark_detached", "mark_attached", "find_by_project_prefix"):
    assert not hasattr(SessionTable, gone), gone
for gone in ("parse_stop_command", "STOP_PREFIX", "should_drop_transcript"):
    assert not hasattr(listener, gone), gone

# --- 14. 호출어: 받아쓴 글자로 확인 (마이크·모델 없이 VAD와 받아쓰기를 바꿔 끼움) ---
import numpy as np  # noqa: E402
from voice import wakeword  # noqa: E402

for t in ("자비스", "자비스.", "자비스야!", " 자 비 스 ", "Jarvis?", "자비수", "쟈비스"):
    assert wakeword.is_wake_text(t), t
for t in ("안녕하세요", "서비스", "사비스", "타비스", "자비로운 사람", "", "(음악)"):
    assert not wakeword.is_wake_text(t), t
assert wakeword.is_wake_text("헤이 보이스", "보이스") and not wakeword.is_wake_text("자비스", "보이스"), "다른 호출어 설정 무시"


class FakeVad:
    """청크 값이 1이면 말소리, 0이면 침묵. 침묵 2청크면 끝."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.has_speech_started, self.is_finished, self._quiet = False, False, 0

    def push(self, chunk):
        if chunk[0] > 0:
            self.has_speech_started, self._quiet = True, 0
        elif self.has_speech_started:
            self._quiet += 1
            self.is_finished = self._quiet >= 2


heard = []


def fake_stt(audio):
    heard.append(len(audio))
    return {1: "자비스.", 2: "안녕하세요"}.get(int(audio.max() * 10) // 10 or 1, "")


CH = 512
rejects = []
sp = wakeword.WakeSpotter(fake_stt, FakeVad, chunk_samples=CH, sample_rate=16000, wake_word="자비스",
                          on_reject=rejects.append)
on, off = np.ones(CH, np.float32), np.zeros(CH, np.float32)


def feed(chunks):
    return [r for r in (sp.push(c) for c in chunks) if r is not None]


assert feed([off] * 20 + [on] * 10 + [off] * 3) == ["자비스."], "짧은 말 속 호출어를 못 찾음"
assert heard[-1] == (sp._preroll.maxlen + 10 + 2) * CH, f"말 앞 소리(preroll)·뒤 침묵이 안 붙음: {heard[-1]}"
n = len(heard)
assert feed([on * 2] * 10 + [off] * 3) == [] and rejects == ["안녕하세요"], "호출어 아닌 말을 받아들임"
long_chunks = int(wakeword.WAKE_MAX_S * 16000 / CH) + 5
assert feed([on] * long_chunks + [off] * 3) == [] and len(heard) == n + 1, "긴 말을 받아썼음(호출어 아님·CPU 낭비)"
assert feed([off] * 30) == [], "침묵에 반응"
assert feed([on] * 8 + [off] * 3) == ["자비스."], "긴 말 다음 호출어를 못 찾음(상태가 안 풀림)"

print("routing checks OK")
