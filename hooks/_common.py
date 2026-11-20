# -*- coding: utf-8 -*-
"""훅 3개(on-stop, on-notification, on-user-prompt-submit)의 공통 부분.

절대 원칙: 훅은 Claude Code 흐름을 막거나 늦추면 안 된다 — 어떤 예외도 밖으로
내보내지 않고, 리스너가 꺼져 있어도 조용히 넘어간다.
"""
from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from voice.config import is_enabled  # noqa: E402,F401 - 훅들이 여기서 가져다 쓴다

HOST = "127.0.0.1"
PORT = 8765
# 리스너가 꺼져 있으면 이 환경에선 즉시 거부되지 않고 타임아웃까지 기다린다(2026-09-26 실측)
# — 이 값이 곧 "리스너가 꺼져 있을 때 훅이 늦추는 최대 시간"이라 짧게 둔다.
CONNECT_TIMEOUT = 0.3


def read_payload() -> dict:
    """stdin JSON. Windows에서 sys.stdin.read()는 cp949로 디코딩해 한글이 깨지므로 바이트로 읽는다."""
    try:
        raw = sys.stdin.buffer.read().decode("utf-8")
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def is_delegate_worker(cwd: str) -> bool:
    """/delegate 작업자 세션(.claude/worktrees/ 아래)이면 음성 알림 대상이 아니다."""
    return "\\.claude\\worktrees\\" in cwd or "/.claude/worktrees/" in cwd


def notify_listener(text: str, cwd: str, kind: str = "stop") -> None:
    """리스너에 완료·알림 텍스트를 보낸다. 응답은 기다리지 않는다.

    session_id는 별도로 만들지 않고 이 세션의 메시징 소켓 경로를 그대로 쓴다.
    """
    socket_path = os.environ.get("CLAUDE_CODE_MESSAGING_SOCKET", "")
    message = {
        "event": "notify",
        "kind": kind,
        "session_id": socket_path,
        "project_name": Path(cwd).name,
        "text": text,
        "socket_path": socket_path,
        "token": os.environ.get("CLAUDE_CODE_MESSAGING_TOKEN", ""),
    }
    try:
        with socket.create_connection((HOST, PORT), timeout=CONNECT_TIMEOUT) as sock:
            sock.sendall(json.dumps(message, ensure_ascii=False).encode("utf-8"))
    except Exception:
        pass  # 리스너가 꺼져 있는 것도 정상 경로 — 공식 터미널 벨이 최소 신호를 준다
