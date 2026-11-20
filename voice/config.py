# -*- coding: utf-8 -*-
"""설정 읽기/쓰기 헬퍼.

- 켜짐 여부(`enabled`)는 전역: `~/.voxcode/config.json`. 훅이 모든 프로젝트 세션에서 돌기 때문에
  프로젝트 폴더의 파일로는 판단할 수 없다(4단계, 2026-11-20).
- 언어·목소리 등 나머지는 이 프로젝트의 `.claude/voice-settings.json` (리스너가 이 폴더에서 돈다).

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
    "language": "en",  # 코드 경로의 fallback일 뿐 - 실제 최초 실행은 /voice-on 온보딩이 "지금 세션이 대화 중인 언어"를 추천해 결정(2026-09-26). 온보딩을 거치면 이 값이 그 언어로 덮어써짐
    "voice_id": None,  # 온보딩에서 고른 목소리(voice/languages.py의 VoiceOption.id). None이면 tts.py가 첫 목소리(남성 1)를 쓴다
    "onboarded": False,  # /voice-on 최초 실행에서 언어+목소리 선택을 마쳤는지
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


def _global_config_path() -> Path:
    from voice import record
    return record.home() / "config.json"


def is_enabled() -> bool:
    """훅에서 쓰는 짧은 경로: 음성모드가 켜져 있는지(전역). 파일이 없거나 깨졌으면 꺼짐."""
    try:
        return bool(json.loads(_global_config_path().read_text(encoding="utf-8")).get("enabled"))
    except Exception:
        return False


def set_enabled(enabled: bool) -> None:
    _global_config_path().write_text(json.dumps({"enabled": enabled}), encoding="utf-8")
