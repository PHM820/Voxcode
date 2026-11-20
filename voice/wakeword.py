# -*- coding: utf-8 -*-
"""호출어("자비스") 감지: 짧은 말소리를 whisper로 받아써서 "자비스"라는 글자가 있는지 본다.

왜 이 방식인가 (2026-11-20, docs/decisions.md):
  - 예전 local-wake(녹음 샘플과 소리 모양 비교)는 실측에서 "자비스"와 조용할 때·"안녕하세요"를
    구별하지 못했다(거리 차이 0.01 안팎) — 기준값으로는 못 고친다.
  - 무료·로컬·한국어로 바로 쓸 전용 호출어 엔진은 조사에서 못 찾았다(Porcupine 상용 키,
    openWakeWord 직접 학습, sherpa-onnx KWS 중·영만).
  - whisper small + audio_ctx=256(짧은 소리용으로 처리 범위 축소)이 실제 녹음 "자비스" 8/8,
    한 번 0.6초, "안녕하세요·서비스·자비로운" 등은 "자비스"로 안 바뀜(실측).

흐름: 마이크 청크 → VAD로 말소리 구간 자르기 → 2.5초 이하만 받아쓰기 → WAKE_FORMS 포함 여부.
녹음 온보딩은 더 필요 없다.
"""
from __future__ import annotations

import collections
import json
import logging
import re
from pathlib import Path
from typing import Callable, Optional

import numpy as np

logger = logging.getLogger("voice.wakeword")

DEFAULT_WAKE_WORD = "자비스"
# whisper가 "자비스"를 이렇게도 받아쓴다. "사비스·서비스·타비스"는 넣지 않는다 — "서비스" 같은
# 흔한 말에 반응하게 된다(실측: "서비스"를 small이 "사비스"로 받아씀).
WAKE_FORMS = ("자비스", "자비수", "자비쓰", "쟈비스", "짜비스", "jarvis", "javis", "jarvice")
WAKE_MAX_S = 2.5        # 이보다 긴 말은 호출어가 아니라 보고 받아쓰지 않는다(CPU 절약·오탐 방지)
WAKE_PREROLL_S = 0.3    # VAD가 말 시작을 조금 늦게 잡으므로 그 앞 소리도 붙인다
WAKE_SILENCE_S = 0.3    # 말이 끝났다고 볼 침묵 길이
VOICE_SETTINGS_PATH = Path(".claude/voice-settings.json")


def get_configured_wake_word() -> str:
    """.claude/voice-settings.json의 wake_word 키를 읽는다. 파일 없으면 기본값 "자비스"."""
    if not VOICE_SETTINGS_PATH.exists():
        return DEFAULT_WAKE_WORD
    try:
        data = json.loads(VOICE_SETTINGS_PATH.read_text(encoding="utf-8"))
        return data.get("wake_word", DEFAULT_WAKE_WORD) or DEFAULT_WAKE_WORD
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("voice-settings.json 읽기 실패, 기본 호출어 사용: %s", e)
        return DEFAULT_WAKE_WORD


def _normalize(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.lower())


def is_wake_text(text: str, wake_word: str = DEFAULT_WAKE_WORD) -> bool:
    """받아쓴 글자에 호출어가 들어 있으면 True. 기본 호출어면 WAKE_FORMS 중 하나만 있어도 된다."""
    forms = WAKE_FORMS if wake_word == DEFAULT_WAKE_WORD else (wake_word,)
    t = _normalize(text)
    return any(_normalize(f) in t for f in forms)


class WakeSpotter:
    """마이크 청크를 하나씩 받아 호출어를 찾는다(마이크·모델 없이 테스트할 수 있게 둘 다 주입).

    :param transcribe: audio(np.float32, 16kHz) -> 받아쓴 글자
    :param detector_factory: () -> push(chunk)/is_finished/has_speech_started/reset()을 가진 VAD
    push(chunk)는 호출어를 찾은 순간 받아쓴 글자를, 아니면 None을 돌려준다.
    on_reject(text)는 받아썼지만 호출어가 아니었을 때 불린다(기록용).
    """

    def __init__(self, transcribe: Callable[[np.ndarray], str], detector_factory: Callable[[], object],
                 chunk_samples: int, sample_rate: int = 16000, wake_word: Optional[str] = None,
                 on_reject: Optional[Callable[[str], None]] = None):
        self._transcribe = transcribe
        self._detector = detector_factory()
        self.sample_rate = sample_rate
        self.wake_word = wake_word or get_configured_wake_word()
        self._on_reject = on_reject
        self._preroll = collections.deque(maxlen=max(1, int(WAKE_PREROLL_S * sample_rate / chunk_samples)))
        self._max_chunks = int(WAKE_MAX_S * sample_rate / chunk_samples)
        self._seg: list[np.ndarray] = []
        self._too_long = False

    def _reset(self) -> None:
        self._detector.reset()
        self._seg = []
        self._too_long = False

    def push(self, chunk: np.ndarray) -> Optional[str]:
        was_started = self._detector.has_speech_started
        self._detector.push(chunk)
        if self._detector.has_speech_started:
            if not was_started:
                self._seg = list(self._preroll)
            if not self._too_long:
                self._seg.append(chunk)
                if len(self._seg) > self._max_chunks:
                    self._too_long, self._seg = True, []  # 긴 말 — 끝날 때까지 기다렸다 버린다
        else:
            self._preroll.append(chunk)
        if not self._detector.is_finished:
            return None
        audio = np.concatenate(self._seg) if self._seg else None
        self._reset()
        if audio is None:
            return None
        text = self._transcribe(audio)
        if is_wake_text(text, self.wake_word):
            return text
        if self._on_reject and text.strip():
            self._on_reject(text)
        return None
