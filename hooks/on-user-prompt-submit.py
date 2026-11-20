# -*- coding: utf-8 -*-
"""UserPromptSubmit 훅: 음성모드가 켜져 있으면 매 프롬프트마다 "응답 끝을 TTS용으로 짧게 맺어라"를 넣는다.

CLAUDE.md의 같은 지침은 세션 시작 때 한 번만 읽혀 대화가 길어지면 잊히므로 매 턴 다시 넣는다
(docs/architecture.md "3중 재주입 설계"). CLAUDE.md 쪽 문구를 바꾸면 여기도 맞출 것. 항상 exit 0.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import is_delegate_worker, is_enabled, read_payload  # noqa: E402

VOICE_MODE_REMINDER = (
    "[음성모드 켜짐] 이 응답의 끝은 TTS로 읽힙니다. 코드블록·파일 경로 나열 "
    "없이 1~2문장의 짧고 자연스러운 한국어 요약으로 맺으세요."
)


def main() -> int:
    payload = read_payload()
    cwd = payload.get("cwd") or os.getcwd()
    if is_delegate_worker(cwd) or not is_enabled():
        return 0
    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": VOICE_MODE_REMINDER,
        }
    }
    try:
        # stdout도 cp949로 인코딩돼 한글이 깨지므로 바이트로 직접 쓴다
        sys.stdout.buffer.write(json.dumps(output, ensure_ascii=False).encode("utf-8"))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
