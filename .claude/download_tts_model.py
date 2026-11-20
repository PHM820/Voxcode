# -*- coding: utf-8 -*-
"""TTS 모델(Supertonic 3, 약 383MB)을 models/tts/supertonic3/에 내려받는다.

모든 언어·목소리가 이 한 벌을 같이 쓰므로 받는 것은 늘 같다. setup.cmd와 /voice-on 온보딩이 부른다.
배치 파일 안에서 다운로드·검증을 인라인으로 하면 known-issues.md 9/10/12번 같은 버그가 반복될 수 있어
.py로 분리했다.

사용법:
    <venv_python> .claude\\download_tts_model.py
    (예전 호출 형식 `<voice_id>`·`--language <code>`도 받는다 — 인자는 무시, 같은 모델을 받는다)

성공하면 exit 0, 이미 받아져 있으면 메시지 출력 후 exit 0, 실패하면 exit 1 + 에러 메시지를 stderr로.
중간에 끊긴 파일은 .part로 남았다가 지워지므로 다시 실행하면 이어서 받는다(받은 파일은 건너뜀).
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice.languages import SUPERTONIC_DIR_NAME, SUPERTONIC_FILES, SUPERTONIC_HELPER, SUPERTONIC_HF  # noqa: E402
from voice.tts import MODELS_ROOT, supertonic_dir  # noqa: E402


def main() -> None:
    found = supertonic_dir(MODELS_ROOT)
    if found is not None:
        print(f"Already downloaded: {found}")
        return
    target = MODELS_ROOT / SUPERTONIC_DIR_NAME
    jobs = [(SUPERTONIC_HELPER, target / "helper.py")]
    jobs += [(SUPERTONIC_HF + rel, target / rel) for rel in SUPERTONIC_FILES]
    for url, dest in jobs:
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        print(f"Downloading {url}")
        try:
            urllib.request.urlretrieve(url, part)
            part.replace(dest)
        except Exception as e:
            part.unlink(missing_ok=True)
            print(f"SETUP FAILED: download error: {e}\nTry manually: {url}", file=sys.stderr)
            sys.exit(1)
    if supertonic_dir(MODELS_ROOT) is None:
        print(f"SETUP FAILED: files downloaded but layout unexpected: {target}", file=sys.stderr)
        sys.exit(1)
    print(f"OK: {target}")


if __name__ == "__main__":
    main()
