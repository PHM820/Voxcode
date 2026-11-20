# -*- coding: utf-8 -*-
"""훅 3개(on-stop, on-notification, on-user-prompt-submit)의 공통 부분.

절대 원칙: 훅은 Claude Code 흐름을 막거나 늦추면 안 된다 — 어떤 예외도 밖으로
내보내지 않고, 리스너가 꺼져 있어도 조용히 넘어간다.
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from voice.config import is_enabled  # noqa: E402,F401 - 훅들이 여기서 가져다 쓴다
from voice import manager, record  # noqa: E402


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
    """완료·알림을 ~/.voxcode/inbox/에 파일로 남긴다. 리스너가 폴더를 지켜보다 읽어 간다.

    리스너가 꺼져 있어도 사라지지 않고 다음에 켤 때 세션 등록에 쓰인다. 반쯤 쓴 파일을 읽지 않게
    .tmp로 쓰고 이름을 바꾼다(리스너는 *.json만 읽음).

    session_id는 별도로 만들지 않고 이 세션의 메시징 소켓 경로를 그대로 쓴다.
    서브 관리자 세션(~/.voxcode/manager/)이면 프로젝트로 알리지 않고 자기 연결 정보만 등록한다.
    """
    socket_path = os.environ.get("CLAUDE_CODE_MESSAGING_SOCKET", "")
    if manager.is_manager_cwd(cwd):
        try:
            if socket_path:
                manager.register(socket_path, os.environ.get("CLAUDE_CODE_MESSAGING_TOKEN", ""))
        except Exception:
            pass
        return
    message = {
        "event": "notify",
        "kind": kind,
        "session_id": socket_path,
        "project_name": Path(cwd).name,
        "text": text,
        "socket_path": socket_path,
        "token": os.environ.get("CLAUDE_CODE_MESSAGING_TOKEN", ""),
        "ts": time.time(),
    }
    try:
        write_inbox(message)
    except Exception:
        pass  # 기록 실패도 조용히 — 공식 터미널 벨이 최소 신호를 준다


def write_inbox(message: dict) -> Path:
    inbox = record.home() / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    name = f"{time.time_ns()}-{uuid.uuid4().hex[:6]}"
    tmp = inbox / f"{name}.tmp"
    tmp.write_text(json.dumps(message, ensure_ascii=False), encoding="utf-8")
    return Path(os.replace(tmp, inbox / f"{name}.json") or inbox / f"{name}.json")
