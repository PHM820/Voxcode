# -*- coding: utf-8 -*-
"""Notification 훅: Claude Code가 권한 대기/유휴 등 알림을 보낼 때
상주 리스너(voice/listener.py)에게 짧은 안내 텍스트를 로컬 TCP로 전달한다.

docs/architecture.md "2. 권한 요청 → 알림" 참고. 구조는 hooks/on-stop.py와
동일 — 차이는 stdin JSON에서 추출하는 필드뿐이다.

Notification 훅 stdin의 실제 필드는 2026-09-26 이 프로젝트에서 실측 확인:
docs/decisions.md 참고. 공통 필드(session_id, transcript_path, cwd,
permission_mode, hook_event_name) 외에 `message` 필드에 사람이 읽을 안내
문구가 담겨 온다.

절대 원칙은 hooks/on-stop.py와 동일: 이 훅은 Claude Code 흐름을 절대 막지
않는다. 소켓 연결 실패(상주 프로세스 미기동)는 폴백 없이 조용히 삼키고
exit 0으로 끝난다.
"""
from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8765
# 초. hooks/on-stop.py와 동일한 이유로 짧게 고정 — 이 환경에서는 리스너 미기동 시
# ConnectionRefusedError가 아니라 TimeoutError로 걸리는 것을 실측 확인했다(2026-09-26).
CONNECT_TIMEOUT = 0.3


def main() -> int:
    try:
        # hooks/on-stop.py와 동일한 이유로 바이트로 읽어 UTF-8로 직접 디코딩한다
        # (Windows에서 sys.stdin.read()가 cp949로 잘못 디코딩하는 문제, 실측 확인).
        raw = sys.stdin.buffer.read().decode("utf-8")
        payload = json.loads(raw) if raw else {}
    except Exception:
        payload = {}

    # Notification 이벤트는 last_assistant_message가 없다 — message 필드(실측
    # 확인)를 우선 쓰고, 없으면 title을 보조로, 둘 다 없으면 조용히 종료한다.
    text = payload.get("message") or payload.get("title") or ""
    if not text:
        return 0

    socket_path = os.environ.get("CLAUDE_CODE_MESSAGING_SOCKET", "")
    token = os.environ.get("CLAUDE_CODE_MESSAGING_TOKEN", "")
    session_id = socket_path

    cwd = payload.get("cwd") or os.getcwd()
    project_name = Path(cwd).name

    message = {
        "event": "notify",
        "session_id": session_id,
        "project_name": project_name,
        "text": text,
        "socket_path": socket_path,
        "token": token,
    }

    try:
        with socket.create_connection((HOST, PORT), timeout=CONNECT_TIMEOUT) as sock:
            sock.sendall(json.dumps(message, ensure_ascii=False).encode("utf-8"))
    except ConnectionRefusedError:
        pass
    except OSError:
        pass
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
