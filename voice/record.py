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
_last_sessions: list = []
_extra: dict = {}  # 세션 밖 상황(조용히 모드 등) — write_state가 함께 쓴다


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


def read_events(since_ts: str = "", kind: str = "") -> list[dict]:
    """log.jsonl에서 since_ts(ISO 문자열) 이후 사건을 읽는다. 깨진 줄은 건너뛴다."""
    events = []
    try:
        with open(home() / "log.jsonl", encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("ts", "") > since_ts and (not kind or e.get("kind") == kind):
                    events.append(e)
    except OSError:
        pass
    return events


def tail_events(n: int, max_bytes: int = 65536) -> list[dict]:
    """log.jsonl 끝부분에서 최근 n개 사건만 읽는다(파일 전체를 읽지 않음)."""
    try:
        with open(home() / "log.jsonl", "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            chunk = f.read().decode("utf-8", errors="ignore")
    except OSError:
        return []
    events = []
    for line in chunk.splitlines()[1 if size > max_bytes else 0:]:  # 잘린 첫 줄 버림
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return events[-n:]


def now_iso() -> str:
    return _now()


def set_state_field(name: str, value) -> None:
    """세션 밖 상황 값을 바꾸고 state.json을 다시 쓴다."""
    _extra[name] = value
    write_state()


def write_state(sessions=None) -> None:
    global _last_sessions
    try:
        if sessions is not None:
            _last_sessions = list(sessions)
        data = {
            "updated": _now(),
            "listener_pid": os.getpid(),
            **_extra,
            "sessions": [asdict(s) if is_dataclass(s) else dict(s) for s in _last_sessions],
        }
        with _lock:
            target = home() / "state.json"
            tmp = target.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, target)  # 반쯤 쓴 파일이 남지 않게
    except Exception as e:  # noqa: BLE001
        print(f"[record] state 기록 실패: {e}", file=sys.stderr)
