# -*- coding: utf-8 -*-
"""/voice-on·/voice-off를 어느 프로젝트 세션에서나 쓸 수 있게 사용자 전역 스킬(~/.claude/skills/)을 만든다.

전역 스킬은 얇은 안내문이다: "Voxcode 설치 폴더로 가서 그 폴더의 같은 이름 스킬을 따르라".
설치 폴더 경로는 설치하는 순간 이 파일 위치에서 계산해 넣는다 — 저장소에는 개인 경로가 들어가지 않는다.

안전 규칙:
- 우리가 만든 파일(MARKER가 든 SKILL.md)만 덮어쓰거나 지운다. 같은 이름의 다른 스킬이 있으면 건드리지 않는다.
- 테스트는 VOXCODE_CLAUDE_SKILLS로 다른 폴더를 가리킨다.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MARKER = "<!-- voxcode:global-skill -->"
SKILLS = {
    "voice-on": "음성모드(완료 음성 요약 + 음성 명령)를 켠다. 어느 프로젝트 세션에서나 쓸 수 있다.",
    "voice-off": "음성모드를 끈다. 어느 프로젝트 세션에서나 쓸 수 있다.",
}


def skills_dir() -> Path:
    override = os.environ.get("VOXCODE_CLAUDE_SKILLS")
    return Path(override) if override else Path.home() / ".claude" / "skills"


def _body(name: str, description: str) -> str:
    src = PROJECT_ROOT / ".claude" / "skills" / name / "SKILL.md"
    return f"""---
name: {name}
description: {description}
---
{MARKER}

# /{name} (전역 연결)

이 파일은 Voxcode 설치 때 자동으로 만들어진 연결용 안내문이다. 실제 절차는 아래 파일에 있다.

1. `{src}` 를 읽고 그 절차를 그대로 따른다.
2. 그 절차의 모든 명령(`.venv\\Scripts\\python.exe ...`)은 **Voxcode 설치 폴더에서** 실행한다 —
   지금 세션의 작업 폴더가 아니다. 예: `cd /d "{PROJECT_ROOT}" && .venv\\Scripts\\python.exe -m voice.control status`
3. 위 파일이 없으면 Voxcode 폴더가 옮겨졌거나 지워진 것이다 — 그렇게 알리고 멈춘다
   (새 위치에서 `.venv\\Scripts\\python.exe -m voice.control install-skills`를 다시 실행하면 고쳐진다).
"""


def _ours(path: Path) -> bool:
    try:
        return MARKER in path.read_text(encoding="utf-8")
    except OSError:
        return False


def install() -> dict:
    """결과: {스킬 이름: "installed" | "skipped_foreign"}."""
    out = {}
    for name, desc in SKILLS.items():
        f = skills_dir() / name / "SKILL.md"
        if f.exists() and not _ours(f):
            out[name] = "skipped_foreign"  # 사용자가 따로 만든 같은 이름 스킬 — 건드리지 않음
            continue
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(_body(name, desc), encoding="utf-8")
        out[name] = "installed"
    return out


def uninstall() -> dict:
    """결과: {스킬 이름: "removed" | "not_installed" | "skipped_foreign"}."""
    out = {}
    for name in SKILLS:
        d = skills_dir() / name
        f = d / "SKILL.md"
        if not f.exists():
            out[name] = "not_installed"
        elif not _ours(f):
            out[name] = "skipped_foreign"
        elif any(p.name != "SKILL.md" for p in d.iterdir()):
            f.unlink()  # 폴더에 다른 파일이 있으면 우리 파일만 지운다
            out[name] = "removed"
        else:
            shutil.rmtree(d)
            out[name] = "removed"
    return out
