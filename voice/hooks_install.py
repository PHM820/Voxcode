# -*- coding: utf-8 -*-
"""Voxcode 훅을 사용자 전역 Claude Code 설정(~/.claude/settings.json)에 등록·해제한다.

/voice-on이 등록하고 /voice-off가 해제한다 — 꺼 두면 다른 프로젝트 세션에서 훅이 아예 돌지 않는다
(docs/decisions.md 2026-11-20 "켤 때 전역 등록, 끌 때 해제").

안전 규칙 (사용자의 다른 훅·설정을 절대 망가뜨리지 않는다):
- 우리 항목은 명령 문자열에 이 프로젝트의 hooks 폴더 경로가 들어 있는 것만으로 알아본다. 그 외는 건드리지 않는다.
- 등록은 먼저 우리 항목을 지우고 다시 넣는다(두 번 등록해도 중복 없음).
- JSON이 깨져 있으면 아무것도 쓰지 않고 예외를 낸다.
- 쓸 때는 백업(settings.json.voxcode.bak)을 남기고 임시 파일 → 교체로 쓴다.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = PROJECT_ROOT / "hooks"
VENV_PY = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"

EVENTS = {
    "Stop": "on-stop.py",
    "Notification": "on-notification.py",
    "UserPromptSubmit": "on-user-prompt-submit.py",
}


def settings_path() -> Path:
    """테스트는 VOXCODE_CLAUDE_SETTINGS로 다른 파일을 가리킨다."""
    override = os.environ.get("VOXCODE_CLAUDE_SETTINGS")
    return Path(override) if override else Path.home() / ".claude" / "settings.json"


def _command(script: str) -> str:
    # 경로에 공백("Claude code")이 있으므로 둘 다 따옴표로 감싼다
    return f'"{VENV_PY}" "{HOOKS_DIR / script}"'


def _is_ours(hook: dict) -> bool:
    return str(HOOKS_DIR).lower() in str(hook.get("command", "")).lower()


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))  # 깨졌으면 여기서 예외 → 쓰지 않음
    if not isinstance(data, dict):
        raise ValueError(f"{path}가 JSON 객체가 아님")
    return data


def _strip_ours(data: dict) -> dict:
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return data
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        kept = []
        changed = False
        for g in groups:
            inner = g.get("hooks") if isinstance(g, dict) else None
            if isinstance(inner, list) and any(_is_ours(h) for h in inner if isinstance(h, dict)):
                changed = True
                rest = [h for h in inner if not (isinstance(h, dict) and _is_ours(h))]
                if rest:
                    kept.append({**g, "hooks": rest})
            else:
                kept.append(g)
        if changed:
            if kept:
                hooks[event] = kept
            else:
                del hooks[event]
    if not hooks:
        del data["hooks"]
    return data


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".voxcode.bak"))
    tmp = path.with_name(path.name + ".voxcode.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def is_installed(path: Path | None = None) -> bool:
    try:
        data = _load(path or settings_path())
    except Exception:  # noqa: BLE001
        return False
    hooks = data.get("hooks") if isinstance(data.get("hooks"), dict) else {}
    return any(
        isinstance(h, dict) and _is_ours(h)
        for groups in hooks.values() if isinstance(groups, list)
        for g in groups if isinstance(g, dict)
        for h in (g.get("hooks") if isinstance(g.get("hooks"), list) else [])
    )


def install(path: Path | None = None) -> None:
    path = path or settings_path()
    data = _strip_ours(_load(path))
    hooks = data.setdefault("hooks", {})
    for event, script in EVENTS.items():
        hooks.setdefault(event, []).append({"hooks": [{"type": "command", "command": _command(script)}]})
    _write(path, data)


def uninstall(path: Path | None = None) -> bool:
    """우리 항목을 지운다. 지운 게 있으면 True (없으면 파일을 다시 쓰지 않는다)."""
    path = path or settings_path()
    if not is_installed(path):
        return False
    _write(path, _strip_ours(_load(path)))
    return True
