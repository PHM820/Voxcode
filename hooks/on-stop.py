# -*- coding: utf-8 -*-
"""Stop 훅: Claude 응답이 끝나면 마지막 문단을 리스너(voice/listener.py)에 보내 TTS로 읽게 한다.

docs/architecture.md "1. 작업 완료 → 음성 요약" 참고. 항상 exit 0.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import is_delegate_worker, is_enabled, notify_listener, read_payload  # noqa: E402


def last_paragraph(text: str) -> str:
    """응답의 마지막 문단만 TTS용으로 남긴다(마크다운 강조·코드 표시 기호 제거).

    응답 전체를 보내면 표·목록까지 전부 읽힌다. 음성모드 지침이 "끝을 1~2문장 요약으로
    맺으라"고 하므로 마지막 문단이 곧 요약이다.
    """
    paragraphs = [p.strip() for p in text.replace("\r\n", "\n").split("\n\n") if p.strip()]
    if not paragraphs:
        return ""
    return re.sub(r"[*`#]", "", paragraphs[-1]).strip()


def main() -> int:
    payload = read_payload()
    text = last_paragraph(payload.get("last_assistant_message") or "")
    cwd = payload.get("cwd") or os.getcwd()
    if text and not is_delegate_worker(cwd) and is_enabled():
        notify_listener(text, cwd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
