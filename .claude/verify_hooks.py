# -*- coding: utf-8 -*-
"""verify.cmd에서 호출하는 훅(hooks/*.py) 자가 점검.

`.claude/verify_routing.py`와 같은 이유로 별도 파일로 분리했다: 배치 파일
안에서 훅에 stdin을 넘기려고 파이프(`echo {}| program`)나 파일 리다이렉트를
쓰면 batch 실행이 그 지점 이후로 조용히 멈추는 문제를 겪었다(2026-09-27,
원인은 끝내 못 좁혔고 재현만 확인 — cmd.exe 파이프가 배치 파일 자체를
서브프로세스로 다시 파싱하면서 나머지 줄을 건너뛰는 것으로 추정되는 알려진
종류의 현상). subprocess로 훅을 실행하면 이 문제 자체가 없다.

각 훅은 항상 exit 0이어야 한다(설계 확정 사항 — Claude Code 흐름을 절대
막지 않음). 여기서는 "빈 payload로 실행해도 죽지 않는지"만 확인한다.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

VENV_PY = sys.executable
# 실제 ~/.voxcode를 건드리지 않게 임시 폴더 (훅은 전역 켜짐 표시와 inbox를 여기서 본다)
HOME = Path(tempfile.mkdtemp(prefix="voxcode-verify-hooks-"))
ENV = {**os.environ, "VOXCODE_HOME": str(HOME),
       "CLAUDE_CODE_MESSAGING_SOCKET": r"\\.\pipe\hook-test", "CLAUDE_CODE_MESSAGING_TOKEN": "hook-token"}


def run(hook, payload):
    return subprocess.run([VENV_PY, hook], input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                          capture_output=True, env=ENV, timeout=10)


for hook in ("hooks/on-stop.py", "hooks/on-notification.py", "hooks/on-user-prompt-submit.py"):
    result = subprocess.run(
        [VENV_PY, hook],
        env=ENV,
        input="{}",
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    if result.returncode != 0:
        print(f"FAILED: {hook} exited {result.returncode}")
        print("stdout:", result.stdout)
        print("stderr:", result.stderr)
        sys.exit(1)

# on-stop.py는 응답의 마지막 문단만(마크다운 기호 제거) TTS로 보낸다
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("on_stop", "hooks/on-stop.py")
on_stop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(on_stop)
msg = "| 표 | 내용 |\n|---|---|\n\n- 목록\n\n**마이크 루프를 연결**했고 `verify`도 통과했습니다.\n"
assert on_stop.last_paragraph(msg) == "마이크 루프를 연결했고 verify도 통과했습니다.", on_stop.last_paragraph(msg)
assert on_stop.last_paragraph("한 문단뿐") == "한 문단뿐"
assert on_stop.last_paragraph("\n\n") == ""

# --- 꺼져 있으면 아무것도 남기지 않음, 켜져 있으면 inbox에 파일 하나 ---
inbox = HOME / "inbox"
proj = str(HOME / "proj-a")
run("hooks/on-stop.py", {"cwd": proj, "last_assistant_message": "끝났습니다."})
assert not list(HOME.glob("inbox/*.json")), "꺼져 있는데 inbox에 씀"
assert run("hooks/on-user-prompt-submit.py", {"cwd": proj}).stdout == b"", "꺼져 있는데 지침을 넣음"
(HOME / "config.json").write_text('{"enabled": true}', encoding="utf-8")
run("hooks/on-stop.py", {"cwd": proj, "last_assistant_message": "표\n\n**끝났습니다.**"})
run("hooks/on-notification.py", {"cwd": proj, "message": "권한이 필요합니다"})
files = sorted(inbox.glob("*.json"))
msgs = [json.loads(f.read_text(encoding="utf-8")) for f in files]
assert [(m["kind"], m["text"]) for m in msgs] == [("stop", "끝났습니다."), ("notification", "권한이 필요합니다")], msgs
assert msgs[0]["project_name"] == "proj-a" and msgs[0]["token"] == "hook-token" and msgs[0]["event"] == "notify"
assert not list(inbox.glob("*.tmp")), "임시 파일이 남음"
assert "음성모드 켜짐" in run("hooks/on-user-prompt-submit.py", {"cwd": proj}).stdout.decode("utf-8")
# 작업자(worktree)·관리자 폴더에서는 inbox에 안 씀
for f in files:
    f.unlink()
run("hooks/on-stop.py", {"cwd": proj + r"\.claude\worktrees\dlg-x", "last_assistant_message": "작업자"})
run("hooks/on-stop.py", {"cwd": str(HOME / "manager"), "last_assistant_message": "완료"})
assert not list(inbox.glob("*.json")), "작업자·관리자 세션이 프로젝트로 알림"
assert json.loads((HOME / "manager" / "session.json").read_text(encoding="utf-8"))["token"] == "hook-token"
assert run("hooks/on-user-prompt-submit.py", {"cwd": str(HOME / "manager")}).stdout == b"", "관리자에 음성 지침을 넣음"

print("hooks import + run OK")
