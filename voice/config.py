# -*- coding: utf-8 -*-
"""voice-settings.json 읽기/쓰기 헬퍼.

docs/architecture.md "설정 파일과 프로세스 생명주기" 참고. 파일이 없으면
기본값으로 동작해야 한다(설치 직후 별도 설정 없이 /voice-on만 실행하면 됨).

훅(hooks/on-stop.py 등)과 /voice-on, /voice-off 스킬이 공유해서 쓴다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "wake_word": "자비스",
    "language": "ko",
    "play_official_bell": True,
    "project_alias": None,
}

SETTINGS_PATH = Path(".claude/voice-settings.json")


def load_settings(path: Path = SETTINGS_PATH) -> dict[str, Any]:
    """설정 파일을 읽는다. 없거나 파싱 실패하면 기본값을 그대로 반환한다.

    파일 하나가 깨졌다고 음성 기능 전체가 죽으면 안 되므로(사용자가 직접
    편집하다 JSON을 깨뜨릴 수 있음), 예외를 삼키고 기본값으로 안전하게
    폴백한다.
    """
    settings = dict(DEFAULTS)
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                settings.update(data)
    except Exception:
        pass
    return settings


def save_settings(settings: dict[str, Any], path: Path = SETTINGS_PATH) -> None:
    """설정 파일에 기록한다. 부모 디렉토리(.claude/)는 항상 존재한다고 가정."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
        f.write("\n")


def is_enabled(path: Path = SETTINGS_PATH) -> bool:
    """훅에서 쓰는 짧은 경로: 음성모드가 켜져 있는지만 빠르게 확인."""
    return bool(load_settings(path).get("enabled", False))
