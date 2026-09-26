# -*- coding: utf-8 -*-
"""언어+목소리 선택에 맞는 TTS 모델을 내려받아 models/tts/에 압축 해제한다.

setup.cmd/온보딩 스킬에서 호출한다. 배치 파일 안에서 다운로드+압축해제+
파일 존재 검증까지 인라인으로 하면 known-issues.md 9/10/12번과 같은 종류의
버그를 반복할 위험이 있어(CLAUDE.md "cmd.exe 안에서 복잡한 프로세스 I/O를
직접 하지 않는다" 원칙), 처음부터 .py로 분리했다.

사용법:
    <venv_python> .claude\\download_tts_model.py <voice_id>
    <venv_python> .claude\\download_tts_model.py --language <code>  (그 언어의 첫 목소리)

성공하면 exit 0, 이미 받아져 있으면 메시지 출력 후 exit 0, 실패하면 exit 1
+ 에러 메시지를 stderr로.
"""
from __future__ import annotations

import sys
import tarfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice.languages import LANGUAGES, download_url, find_language, find_voice  # noqa: E402

MODELS_ROOT = Path("models/tts")


def resolve_voice(args: list[str]):
    if not args:
        print("usage: download_tts_model.py <voice_id> | --language <code>", file=sys.stderr)
        sys.exit(1)
    if args[0] == "--language":
        if len(args) < 2:
            print("--language requires a code, e.g. --language en", file=sys.stderr)
            sys.exit(1)
        lang = find_language(args[1])
        if lang is None:
            print(f"unknown language code: {args[1]}", file=sys.stderr)
            sys.exit(1)
        return lang.voices[0]
    # voice_id로 직접 지정한 경우: 어느 언어 소속인지 찾는다.
    voice_id = args[0]
    for lang in LANGUAGES:
        v = find_voice(lang.code, voice_id)
        if v is not None:
            return v
    print(f"unknown voice_id: {voice_id}", file=sys.stderr)
    sys.exit(1)


def main():
    voice = resolve_voice(sys.argv[1:])
    target_dir = MODELS_ROOT / voice.id
    onnx_path = target_dir / voice.onnx_name

    if onnx_path.exists():
        print(f"Already downloaded: {target_dir}")
        return

    MODELS_ROOT.mkdir(parents=True, exist_ok=True)
    url = download_url(voice.id)
    archive_path = MODELS_ROOT / "_download.tar.bz2"

    print(f"Downloading {url}")
    try:
        urllib.request.urlretrieve(url, archive_path)
    except Exception as e:
        print(f"SETUP FAILED: download error: {e}", file=sys.stderr)
        print(f"Try manually: {url}", file=sys.stderr)
        sys.exit(1)

    try:
        with tarfile.open(archive_path) as tf:
            # filter="data"로 경로 탈출(path traversal, CVE-2007-4559 계열)·
            # 심볼릭 링크·디바이스 파일 등을 차단한다 — 이 URL은 고정된 신뢰
            # 소스(sherpa-onnx 공식 릴리스)라 실제 위험은 낮지만, 외부에서
            # 받은 압축 파일을 검증 없이 풀지 않는다는 원칙 자체는 지킨다
            # (2026-09-26 밤모드 코드 리뷰로 발견·추가, Python 3.12+ 지원 API).
            tf.extractall(MODELS_ROOT, filter="data")
    except Exception as e:
        print(f"SETUP FAILED: extract error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        archive_path.unlink(missing_ok=True)

    if not onnx_path.exists():
        print(
            f"SETUP FAILED: extracted but expected file not found: {onnx_path}\n"
            f"The archive layout may have changed upstream - check {target_dir} manually.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"OK: {target_dir}")


if __name__ == "__main__":
    main()
