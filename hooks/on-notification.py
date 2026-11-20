# -*- coding: utf-8 -*-
"""Notification 훅: 권한 요청 등 알림 문구를 리스너(voice/listener.py)에 보내 TTS로 읽게 한다.

stdin의 `message` 필드는 아직 실제 로그로 확인하지 못한 추정이다(known-issues.md 11번) —
없으면 `title`, 둘 다 없으면 아무것도 하지 않는다. 항상 exit 0.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import is_delegate_worker, is_enabled, notify_listener, read_payload  # noqa: E402


def main() -> int:
    payload = read_payload()
    text = payload.get("message") or payload.get("title") or ""
    cwd = payload.get("cwd") or os.getcwd()
    if text and not is_delegate_worker(cwd) and is_enabled():
        notify_listener(text, cwd, kind="notification")
    return 0


if __name__ == "__main__":
    sys.exit(main())
