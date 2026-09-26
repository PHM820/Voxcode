# -*- coding: utf-8 -*-
"""온보딩(최초 /voice-on 실행)에서 선택 가능한 언어·목소리 목록.

TTS(sherpa-onnx)와 STT(whisper.cpp)가 **둘 다** 지원하는 언어의 교집합은
52개(2026-09-26 실측 조사, GitHub releases 자산 목록 + whisper tokenizer.py
LANGUAGES 딕셔너리 대조)이지만, 언어마다 tar.bz2 내부 파일명·구조를 일일이
확인해야 정확한 다운로드 URL을 만들 수 있어 한 번에 전부 채우지 않았다.
1차로는 실사용 빈도가 높은 언어만 검증해서 넣고, 나머지는 필요해지면 같은
구조로 추가한다(사용자 결정, 2026-09-26).

각 항목의 onnx/tokens 파일 경로는 실제로 tar.bz2를 받아 내부 구조를 확인한
값이다(추측 아님). 두 계열의 구조 차이:
- piper 계열: espeak-ng-data/ 필요 (자체 g2p 없음, espeak-ng에 의존)
- mimic3 계열: espeak-ng-data 불필요 (onnx+tokens.txt만으로 동작)

일본어는 whisper(STT)는 지원하지만 sherpa-onnx TTS 쪽에 모델 자체가 없어
교집합에서 빠진다 — 온보딩에서 "TTS 미지원, STT만 가능" 안내로 대체.
"""
from __future__ import annotations

from typing import NamedTuple

RELEASE_BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models"


class VoiceOption(NamedTuple):
    id: str  # tar.bz2 파일명(확장자 제외) = 압축 해제 폴더명
    label: str  # 사용자에게 보여줄 이름 (성별/느낌 포함)
    onnx_name: str  # 폴더 안의 onnx 파일명 (확장자 포함)
    needs_espeak: bool  # espeak-ng-data 필요 여부(piper·mimic3 계열=True)
    needs_lexicon: bool = False  # lexicon.txt 필요 여부(중국어 vits-zh-ll 계열=True). espeak와 배타적으로 실측 확인됨(2026-09-26)


class LanguageOption(NamedTuple):
    code: str  # whisper 언어 코드(STT language= 인자와 동일)
    name_ko: str  # 온보딩에 보여줄 한국어 이름
    name_en: str
    voices: tuple[VoiceOption, ...]


LANGUAGES: tuple[LanguageOption, ...] = (
    LanguageOption("en", "영어", "English", (
        VoiceOption("vits-piper-en_US-amy-medium", "Amy (미국, 여성)", "en_US-amy-medium.onnx", True),
        VoiceOption("vits-piper-en_US-ryan-medium", "Ryan (미국, 남성)", "en_US-ryan-medium.onnx", True),
        VoiceOption("vits-piper-en_GB-alan-medium", "Alan (영국, 남성)", "en_GB-alan-medium.onnx", True),
    )),
    LanguageOption("ko", "한국어", "Korean", (
        VoiceOption("vits-mimic3-ko_KO-kss_low", "kss (여성, 기본값)", "ko_KO-kss_low.onnx", True),
    )),
    LanguageOption("zh", "중국어", "Chinese", (
        VoiceOption("sherpa-onnx-vits-zh-ll", "zh-ll (여성, 5화자 중 0번)", "model.onnx", False, needs_lexicon=True),
    )),
    LanguageOption("es", "스페인어", "Spanish", (
        VoiceOption("vits-piper-es_ES-davefx-medium", "davefx (스페인, 남성)", "es_ES-davefx-medium.onnx", True),
    )),
    LanguageOption("fr", "프랑스어", "French", (
        VoiceOption("vits-piper-fr_FR-siwis-medium", "siwis (여성)", "fr_FR-siwis-medium.onnx", True),
    )),
    LanguageOption("de", "독일어", "German", (
        VoiceOption("vits-piper-de_DE-thorsten-medium", "thorsten (남성)", "de_DE-thorsten-medium.onnx", True),
    )),
    LanguageOption("ru", "러시아어", "Russian", (
        VoiceOption("vits-piper-ru_RU-ruslan-medium", "ruslan (남성)", "ru_RU-ruslan-medium.onnx", True),
    )),
    LanguageOption("it", "이탈리아어", "Italian", (
        VoiceOption("vits-piper-it_IT-paola-medium", "paola (여성)", "it_IT-paola-medium.onnx", True),
    )),
    LanguageOption("pt", "포르투갈어", "Portuguese", (
        VoiceOption("vits-piper-pt_BR-faber-medium", "faber (브라질, 남성)", "pt_BR-faber-medium.onnx", True),
    )),
    LanguageOption("hi", "힌디어", "Hindi", (
        VoiceOption("vits-piper-hi_IN-pratham-medium", "pratham (남성)", "hi_IN-pratham-medium.onnx", True),
    )),
    LanguageOption("ar", "아랍어", "Arabic", (
        VoiceOption("vits-piper-ar_JO-kareem-medium", "kareem (요르단, 남성)", "ar_JO-kareem-medium.onnx", True),
    )),
    LanguageOption("vi", "베트남어", "Vietnamese", (
        VoiceOption("vits-mimic3-vi_VN-vais1000_low", "vais1000", "vi_VN-vais1000_low.onnx", True),
    )),
    LanguageOption("tr", "터키어", "Turkish", (
        VoiceOption("vits-piper-tr_TR-fahrettin-medium", "fahrettin (남성)", "tr_TR-fahrettin-medium.onnx", True),
    )),
    LanguageOption("pl", "폴란드어", "Polish", (
        VoiceOption("vits-piper-pl_PL-darkman-medium", "darkman (남성)", "pl_PL-darkman-medium.onnx", True),
    )),
)

DEFAULT_LANGUAGE_CODE = "en"

# 자주 기대되지만 TTS 쪽 모델이 없어 목록에 못 넣는 언어에 대한 안내 문구.
UNSUPPORTED_TTS_NOTE = {
    "ja": (
        "일본어는 STT(음성 명령)는 가능하지만 sherpa-onnx에 TTS 모델이 "
        "없어 음성 요약은 지원하지 않습니다. 대안: (1) VOICEVOX 등 별도 "
        "일본어 TTS 엔진을 추후 통합, (2) 그때까지는 다른 언어로 요약 청취. "
        "필요하면 알려주세요 — 별도 작업으로 검토합니다."
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


def download_url(voice_id: str) -> str:
    return f"{RELEASE_BASE}/{voice_id}.tar.bz2"
