# -*- coding: utf-8 -*-
"""온보딩(최초 /voice-on 실행)에서 선택 가능한 언어·목소리 목록.

TTS는 Supertonic 3(Supertone, 로컬 실행) 하나만 쓴다(2026-11-20, sherpa-onnx에서 교체).
모델 한 벌(약 383MB)이 31개 언어를 모두 읽고, 목소리는 언어와 무관한 스타일 파일(M1~M5, F1~F5)이다.
그래서 목소리 목록은 모든 언어가 같이 쓴다.

여기 넣는 언어 = Supertonic TTS와 whisper STT가 둘 다 지원하는 언어 중 실사용 빈도가 높은 것.
중국어는 whisper는 지원하지만 Supertonic이 지원하지 않아 뺐다 — 다시 넣는 방법은 UNSUPPORTED_TTS_NOTE["zh"].
"""
from __future__ import annotations

from typing import NamedTuple


class VoiceOption(NamedTuple):
    id: str  # voice-settings.json의 voice_id
    label: str  # 사용자에게 보여줄 이름
    style: str  # Supertonic voice_styles/<style>.json


class LanguageOption(NamedTuple):
    code: str  # whisper 언어 코드 = Supertonic 언어 코드
    name_ko: str  # 온보딩에 보여줄 한국어 이름
    name_en: str
    voices: tuple[VoiceOption, ...]


VOICES: tuple[VoiceOption, ...] = (
    VoiceOption("supertonic3-M1", "남성 1 (기본값)", "M1"),
    VoiceOption("supertonic3-F1", "여성 1", "F1"),
    VoiceOption("supertonic3-M2", "남성 2", "M2"),
    VoiceOption("supertonic3-F2", "여성 2", "F2"),
)

LANGUAGES: tuple[LanguageOption, ...] = tuple(
    LanguageOption(code, ko, en, VOICES) for code, ko, en in (
        ("en", "영어", "English"),
        ("ko", "한국어", "Korean"),
        ("ja", "일본어", "Japanese"),
        ("es", "스페인어", "Spanish"),
        ("fr", "프랑스어", "French"),
        ("de", "독일어", "German"),
        ("ru", "러시아어", "Russian"),
        ("it", "이탈리아어", "Italian"),
        ("pt", "포르투갈어", "Portuguese"),
        ("hi", "힌디어", "Hindi"),
        ("ar", "아랍어", "Arabic"),
        ("vi", "베트남어", "Vietnamese"),
        ("tr", "터키어", "Turkish"),
        ("pl", "폴란드어", "Polish"),
    )
)

DEFAULT_LANGUAGE_CODE = "en"

# 자주 기대되지만 TTS가 없어 목록에 못 넣는 언어에 대한 안내 문구.
UNSUPPORTED_TTS_NOTE = {
    "zh": (
        "중국어는 음성 명령(받아쓰기)은 되지만 Supertonic이 중국어를 읽지 못해 음성 요약은 지원하지 않습니다. "
        "넣는 방법: sherpa-onnx의 중국어 모델(sherpa-onnx-vits-zh-ll, lexicon.txt 필요)을 voice/tts.py에 "
        "두 번째 엔진으로 붙이면 됩니다 — 2026-11-20 이전 커밋(ad514bf)에 그 코드가 그대로 있습니다."
    ),
}


def find_language(code: str) -> LanguageOption | None:
    for lang in LANGUAGES:
        if lang.code == code:
            return lang
    return None


def find_voice(language_code: str, voice_id: str) -> VoiceOption | None:
    lang = find_language(language_code)
    if lang is None:
        return None
    for voice in lang.voices:
        if voice.id == voice_id:
            return voice
    return None


# Supertonic 3: 공식 Hugging Face 저장소의 고정 리비전 + 공식 추론 helper.py(MIT).
SUPERTONIC_DIR_NAME = "supertonic3"
SUPERTONIC_HF = ("https://huggingface.co/supertone-oss-archive/supertonic-3/resolve/"
                 "aafc6e32416a594460b32413efc49d7fe4ce6d46/")
SUPERTONIC_HELPER = "https://raw.githubusercontent.com/supertone-oss-archive/supertonic/main/py/helper.py"
SUPERTONIC_FILES = (
    "onnx/duration_predictor.onnx", "onnx/text_encoder.onnx", "onnx/vector_estimator.onnx",
    "onnx/vocoder.onnx", "onnx/tts.json", "onnx/unicode_indexer.json", "LICENSE",
    *(f"voice_styles/{v.style}.json" for v in VOICES),
)
