# -*- coding: utf-8 -*-
"""verify.cmd에서 호출하는 서브 관리자(voice/manager.py)와 3단계 명령 자가 점검.

실제 Claude 세션·node·네트워크 없이: 주입 함수(send)와 관리자 답(ask_manager)을 바꿔 끼운다.
기록·관리자 폴더는 임시 폴더(VOXCODE_HOME). 실패하면 0이 아닌 코드로 종료한다.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HOME = Path(tempfile.mkdtemp(prefix="voxcode-verify-mgr-"))
os.environ["VOXCODE_HOME"] = str(HOME)
sys.path.insert(0, ".")
sys.path.insert(0, "hooks")

from voice import listener, manager, record  # noqa: E402
from voice.judge import Decision  # noqa: E402
from voice.listener import ListenerContext, SessionTable, route_and_send  # noqa: E402

MDIR = HOME / "manager"

# --- 1. 관리자 없음 -> None, 바로 돌아옴 ---
t0 = time.monotonic()
assert manager.ask({"type": "judge"}, send=lambda *a: True) is None
assert time.monotonic() - t0 < 1

# --- 2. 준비: 역할 문서·권한 설정 ---
manager.prepare()
assert "도구를 쓰지 말고" in (MDIR / "CLAUDE.md").read_text(encoding="utf-8")
assert "하네스 자동 적용" in (MDIR / "CLAUDE.md").read_text(encoding="utf-8"), "전역 하네스 규칙 제외 문구 없음"
assert json.loads((MDIR / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]["allow"] == []

# --- 3. 훅이 관리자 폴더에서 불리면 등록만 하고 프로젝트로 알리지 않는다 ---
import _common  # noqa: E402
os.environ["CLAUDE_CODE_MESSAGING_SOCKET"] = r"\\.\pipe\mgr-test"
os.environ["CLAUDE_CODE_MESSAGING_TOKEN"] = "mgr-token"
_common.notify_listener("대기", str(MDIR))
sess = manager.load_session()
assert sess["socket_path"] == r"\\.\pipe\mgr-test" and sess["token"] == "mgr-token", sess
assert not list(HOME.glob("inbox/*.json")), "관리자 세션이 프로젝트로 리스너에 알림"
_common.notify_listener("완료", str(HOME))  # 관리자 폴더가 아니면 inbox에 남는다 (대조군)
assert len(list(HOME.glob("inbox/*.json"))) == 1
for f in HOME.glob("inbox/*.json"):
    f.unlink()
assert manager.is_manager_cwd(str(MDIR)) and not manager.is_manager_cwd(".")


# --- 4. 묻고 답 받기: 질문은 메시지 본문에 → 관리자 답장 → Stop 훅(save_reply)이 답 파일로 → dict ---
def answering_send(answer, wrap=lambda body: body):
    def send(sock, token, message):
        assert sock == r"\\.\pipe\mgr-test" and token == "mgr-token"
        qid = message.split("[Voxcode 질문 ")[1].split("]")[0]
        q = json.loads(message.split("\n", 1)[1])
        assert q["type"] == "judge" and q["id"] == qid
        if answer is not None:
            body = json.dumps({"id": qid, **answer} if isinstance(answer, dict) else answer, ensure_ascii=False)
            manager.save_reply(wrap(body))
        return True
    return send


ans = manager.ask({"type": "judge", "text": "x"}, send=answering_send({"command": "stop"}))
assert ans == {"command": "stop"}, ans
assert not list((MDIR / "answers").iterdir()), "답 파일이 남음"
# 답장 앞뒤에 말·코드블록 표시가 붙어도 JSON을 찾는다
ans = manager.ask({"type": "judge"}, send=answering_send({"say": "네"}, lambda b: f"답입니다\n```json\n{b}\n```"))
assert ans == {"say": "네"}, ans
assert manager.ask({"type": "judge"}, send=lambda *a: False) is None, "전달 실패"
t0 = time.monotonic()
assert manager.ask({"type": "judge"}, timeout=0.5, send=answering_send(None)) is None, "시간 초과"
assert time.monotonic() - t0 < 2 and not list((MDIR / "answers").iterdir())
assert manager.ask({"type": "judge"}, timeout=0.5, send=answering_send([1, 2])) is None, "id 없는 답"
# save_reply: 답 두 개를 한 번에, 파일 이름이 될 id는 형식 검사
assert manager.save_reply('{"id": "aaaaaaaaaaaa", "say": "1"} 그리고 {"id": "bbbbbbbbbbbb", "say": "2"}') == 2
assert manager.save_reply('{"id": "../../evil", "say": "x"}') == 0, "id 형식 검사 없음"
assert manager.save_reply("완료") == 0 and manager.save_reply("{깨진") == 0
for f in (MDIR / "answers").iterdir():
    f.unlink()

# Stop 훅: 관리자 폴더에서 끝난 답장은 자르지 않고 답 파일로 (on-stop.py를 실제 프로세스로)
reply = '설명 한 줄\n\n{"id": "cccccccccccc", "say": "#1 `코드`"}\n\n끝'
subprocess.run([sys.executable, "hooks/on-stop.py"], env={**os.environ, "VOXCODE_HOME": str(HOME)},
               input=json.dumps({"cwd": str(MDIR), "last_assistant_message": reply}), encoding="utf-8", check=True)
got = json.loads((MDIR / "answers" / "cccccccccccc.json").read_text(encoding="utf-8"))
assert got["say"] == "#1 `코드`", got
(MDIR / "answers" / "cccccccccccc.json").unlink()


# --- 5. route_and_send와 연결 ---
class Sender:
    def __init__(self):
        self.calls = []

    def __call__(self, session, text):
        self.raw = getattr(self, "raw", []) + [text]
        self.calls.append((session.project_name, listener.unwrap_voice(text)))
        return subprocess.CompletedProcess([], 0, "", "")


def two_sessions():
    t = SessionTable()
    t.upsert_from_notify("k-a", "proj-a", "k-a", "tok1", summary="a 요약")
    t.upsert_from_notify("k-b", "proj-b", "k-b", "tok2", summary="b 요약")
    t.get("k-b").last_notify_at = t.get("k-a").last_notify_at + 1
    return t


none_judge = lambda text, sessions: None  # noqa: E731
asked = []


def mgr(answer):
    def ask(question):
        asked.append(question)
        return answer
    return ask


# Jev 실패 → 관리자가 대상 확정
t, s = two_sessions(), Sender()
r = route_and_send(t, "에이 그만", judge_fn=none_judge, send=s, ask_manager=mgr({"command": "stop", "target": "proj-a"}))
assert r["mode"] == "stop" and s.calls == [("proj-a", "에이 그만")] and t.get("k-a").paused, r
assert asked[-1]["type"] == "judge" and asked[-1]["sessions"][0]["project"] == "proj-a"
assert "tok1" not in json.dumps(asked[-1], ensure_ascii=False), "질문에 토큰이 들어감"

# Jev는 멈춰라고 했지만 대상 애매 → 관리자가 되물음 (보내지 않음, 삑 없음, 읽음)
t, s = two_sessions(), Sender()
r = route_and_send(t, "그거 멈춰", judge_fn=lambda x, y: Decision("stop", 0.95, "unknown", 0.95, "jev"), send=s,
                   ask_manager=mgr({"command": "stop", "target": "unknown", "ask_back": "proj-a요, proj-b요?"}))
assert r["mode"] == "ask_back" and r["say"] == "proj-a요, proj-b요?" and not s.calls and not r["beep_twice"], r
assert not any(x.paused for x in t.all_sessions())

# 관리자가 모르는 프로젝트 이름을 대면 대상 애매 → 아무것도 안 멈춤
t, s = two_sessions(), Sender()
r = route_and_send(t, "그거 멈춰", judge_fn=none_judge, send=s, ask_manager=mgr({"command": "stop", "target": "nope"}))
assert r["mode"] == "stop_ambiguous" and not s.calls and r["beep_twice"], r

# 관리자 없음·시간 초과(None) → 1단계 폴백 그대로
t, s = two_sessions(), Sender()
r = route_and_send(t, "다음 거", judge_fn=none_judge, send=s, ask_manager=mgr(None))
assert r["mode"] == "fallback" and s.calls == [("proj-b", "다음 거")], r

# 확신 있는 Jev 판단은 관리자에게 묻지 않는다
n = len(asked)
route_and_send(two_sessions(), "a 멈춰", judge_fn=lambda x, y: Decision("stop", 0.9, "k-a", 0.9, "jev"),
               send=Sender(), ask_manager=mgr(None))
assert len(asked) == n, "확신 있는 판단인데 관리자에게 물음"

# --- 6. 전체 지시: 확인 문장 → "응"이면 멈추지 않은 세션 모두에, "아니"면 취소 ---
all_judge = lambda x, y: Decision("instruct_all", 0.95, "all", 0.95, "jev")  # noqa: E731
t, s, ctx = two_sessions(), Sender(), ListenerContext()
t.set_paused("k-a", True)
t.upsert_from_notify("k-c", "proj-c", "k-c", "tok3")
r = route_and_send(t, "다들 커밋해", judge_fn=all_judge, send=s, ctx=ctx, ask_manager=mgr(None))
assert r["mode"] == "confirm_all" and "2개" in r["say"] and not s.calls, r
r = route_and_send(t, "응 보내", judge_fn=none_judge, send=s, ctx=ctx, ask_manager=mgr(None))
assert r["mode"] == "instruct_all" and sorted(s.calls) == [("proj-b", "다들 커밋해"), ("proj-c", "다들 커밋해")], r
assert ctx.pending_all is None
s = Sender()
route_and_send(t, "다들 커밋해", judge_fn=all_judge, send=s, ctx=ctx, ask_manager=mgr(None))
r = route_and_send(t, "아니 취소", judge_fn=none_judge, send=s, ctx=ctx, ask_manager=mgr(None))
assert r["mode"] == "instruct_all_cancelled" and not s.calls, r
# 확인 대기 중 다른 말 → 확인은 버리고 평소대로
route_and_send(t, "다들 커밋해", judge_fn=all_judge, send=s, ctx=ctx, ask_manager=mgr(None))
r = route_and_send(t, "b 테스트 돌려", judge_fn=lambda x, y: Decision("instruct", 0.9, "k-b", 0.9, "jev"),
                   send=s, ctx=ctx, ask_manager=mgr(None))
assert s.calls == [("proj-b", "b 테스트 돌려")] and ctx.pending_all is None, r
# 만료된 확인은 "응"이어도 보내지 않는다
route_and_send(t, "다들 커밋해", judge_fn=all_judge, send=s, ctx=ctx, ask_manager=mgr(None))
ctx.pending_all = ctx.pending_all[:2] + (time.monotonic() - 1,)
s = Sender()
r = route_and_send(t, "응", judge_fn=lambda x, y: Decision("instruct", 0.9, "k-b", 0.9, "jev"), send=s, ctx=ctx,
                   ask_manager=mgr(None))
assert r["mode"] == "instruct" and s.calls == [("proj-b", "응")], "만료된 확인으로 전체 전달됨"

# --- 7. 밀린 거 듣기: 관리자 요약 / 없으면 최근 소식 그대로 / 다시 물으면 새 소식 없음 ---
catch = lambda x, y: Decision("catch_up", 0.95, "listener", 0.95, "jev")  # noqa: E731
ctx = ListenerContext()
record.log_event("notify", project_name="proj-a", summary="로그인 고침")
record.log_event("notify", project_name="proj-b", summary="테스트 통과")
r = route_and_send(two_sessions(), "밀린 거", judge_fn=catch, send=Sender(), ctx=ctx, ask_manager=mgr(None))
assert "로그인 고침" in r["say"] and "테스트 통과" in r["say"] and not r["beep_twice"], r
r = route_and_send(two_sessions(), "밀린 거", judge_fn=catch, send=Sender(), ctx=ctx, ask_manager=mgr(None))
assert r["say"] == "새로 들어온 소식이 없습니다.", r
time.sleep(0.01)
record.log_event("notify", project_name="proj-a", summary="배포 끝")
r = route_and_send(two_sessions(), "밀린 거", judge_fn=catch, send=Sender(), ctx=ctx,
                   ask_manager=mgr({"say": "a가 배포를 끝냈어요."}))
assert r["say"] == "a가 배포를 끝냈어요." and asked[-1]["type"] == "summarize", r
assert [i["summary"] for i in asked[-1]["items"]] == ["배포 끝"], asked[-1]

# --- 8. 상황 묻기(여럿): 관리자가 묶음, 못 하면 이어 읽기 ---
st = lambda x, y: Decision("status", 0.95, "all", 0.95, "jev")  # noqa: E731
r = route_and_send(two_sessions(), "다들 어때", judge_fn=st, send=Sender(), ask_manager=mgr({"say": "둘 다 순조로워요."}))
assert r["say"] == "둘 다 순조로워요.", r

print("manager checks OK")
