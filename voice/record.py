# -*- coding: utf-8 -*-
"""Voxcode 파일 기록: ~/.voxcode/log.jsonl(사건, 한 줄씩 덧붙임)과 state.json(지금 상황 스냅숏).

docs/architecture.md "파일 기록 (~/.voxcode/)" 절. 말한 내용은 여기 먼저 기록한 뒤 전달한다 —
기록이 진실의 원본이고, 나중에 "밀린 거 듣기"·"상황 묻기"·기준선 조정의 자료가 된다.

기록 실패가 마이크 루프·서버를 죽이면 안 되므로 어떤 예외도 밖으로 내보내지 않는다.
state.json에는 세션 소켓 토큰이 들어간다(사용자 폴더 안, 설계상 허용).
테스트는 환경변수 VOXCODE_HOME으로 폴더를 바꾼다.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path

_lock = threading.Lock()


def home() -> Path:
    path = Path(os.environ.get("VOXCODE_HOME") or Path.home() / ".voxcode")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def log_event(kind: str, **fields) -> None:
    try:
        line = json.dumps({"ts": _now(), "kind": kind, **fields}, ensure_ascii=False)
        with _lock, open(home() / "log.jsonl", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:  # noqa: BLE001
        print(f"[record] log 기록 실패: {e}", file=sys.stderr)


def write_state(sessions) -> None:
    try:
        data = {
            "updated": _now(),
            "listener_pid": os.getpid(),
            "sessions": [asdict(s) if is_dataclass(s) else dict(s) for s in sessions],
        }
        with _lock:
            target = home() / "state.json"
            tmp = target.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, target)  # 반쯤 쓴 파일이 남지 않게
    except Exception as e:  # noqa: BLE001
        print(f"[record] state 기록 실패: {e}", file=sys.stderr)
