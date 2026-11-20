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
import subprocess
import sys

VENV_PY = sys.executable

for hook in ("hooks/on-stop.py", "hooks/on-notification.py", "hooks/on-user-prompt-submit.py"):
    result = subprocess.run(
        [VENV_PY, hook],
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

print("hooks import + run OK")
