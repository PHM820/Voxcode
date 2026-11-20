# -*- coding: utf-8 -*-
"""STT 엔진 래퍼 (whisper.cpp / pywhispercpp).

voice/tts.py의 TtsEngine과 같은 패턴: 모델을 1회 로딩해 재사용한다.

known-issues.md 5번, 6번 반영:
  - 5번: whisper.cpp는 16000Hz 오디오만 받는다 — transcribe() 호출 전에
    16kHz가 아닌 입력은 선형 보간으로 리샘플링한다.
  - 6번: language 파라미터를 생략하면 조용히 엉뚱한 언어로 오인식한다 —
    transcribe()는 항상 language='ko'를 기본값으로 고정한다(호출부에서
    다른 언어를 넘기지 않는 한).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

# 모델 경로: setup.cmd가 이미 이 경로에 다운로드해둔다 (docs/decisions.md 참고).
DEFAULT_MODEL_PATH = "models/stt/ggml-base.bin"

WHISPER_SAMPLE_RATE = 16000  # known-issues.md 5번: whisper.cpp 고정 요구사항


def resample_to_16k(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    """audio(1D float32)를 16000Hz로 선형 보간 리샘플링한다.

    이미 16000Hz면 원본을 그대로 반환(불필요한 보간 방지).
    known-issues.md 5번에서 검증된 numpy.interp 방식 그대로.
    """
    if sample_rate == WHISPER_SAMPLE_RATE:
        return audio
    duration = len(audio) / float(sample_rate)
    target_len = int(round(duration * WHISPER_SAMPLE_RATE))
    if target_len <= 0:
        return np.zeros(0, dtype=np.float32)
    src_x = np.linspace(0.0, duration, num=len(audio), endpoint=False)
    dst_x = np.linspace(0.0, duration, num=target_len, endpoint=False)
    return np.interp(dst_x, src_x, audio).astype(np.float32)


class SttEngine:
    """pywhispercpp(whisper.cpp) 모델을 한 번 로딩해 재사용하는 래퍼.

    상주 프로세스가 받아쓰기마다 모델을 새로 로딩하지 않도록(로딩이
    수 초 걸림, decisions.md 실측 16.7초 참고), 클래스로 감쌌다.
    """

    def __init__(self, model_path: str = DEFAULT_MODEL_PATH):
        from pywhispercpp.model import Model  # 지연 임포트: 무거운 네이티브 확장

        if not Path(model_path).exists():
            raise FileNotFoundError(
                f"STT 모델을 찾을 수 없습니다: {model_path} "
                f"(setup.cmd로 모델을 먼저 받아야 합니다)"
            )
        # model에 direct file path를 주면 models_dir은 무시된다 (pywhispercpp 문서 확인).
        self._model = Model(model_path)

    def transcribe(self, audio_samples: np.ndarray, sample_rate: int,
                   language: str = "ko") -> str:
        """오디오 샘플(1D float32, [-1, 1])을 텍스트로 변환한다.

        :param audio_samples: 마이크 등에서 얻은 1D float32 PCM 샘플
        :param sample_rate: audio_samples의 실제 샘플레이트 (16000이 아니면 리샘플링)
        :param language: whisper 언어 코드. known-issues.md 6번 — 항상 명시 필요,
            생략(자동 감지)하면 조용히 엉뚱한 언어로 오인식할 수 있다.
        """
        audio = np.asarray(audio_samples, dtype=np.float32).reshape(-1)
        audio = resample_to_16k(audio, sample_rate)

        segments = self._model.transcribe(audio, language=language)
        return "".join(seg.text for seg in segments).strip()


def _manual_roundtrip_test():
    """수동 실행 검증용: TTS로 문장을 만들고 STT로 되읽어 왕복 확인.

    python voice/stt.py
    """
    from voice.tts import TtsEngine

    text_in = "안녕하세요. 작업이 끝났습니다."
    print(f"[stt-test] TTS 합성: {text_in!r}")
    tts = TtsEngine(language_code="ko")
    samples, sample_rate = tts.synthesize(text_in)
    print(f"[stt-test] 합성 샘플레이트: {sample_rate}Hz, 길이: {len(samples)}")

    print("[stt-test] STT 모델 로딩...")
    stt = SttEngine()
    print("[stt-test] 인식 중 (language='ko' 고정)...")
    text_out = stt.transcribe(samples, sample_rate, language="ko")
    print(f"[stt-test] 인식 결과: {text_out!r}")


if __name__ == "__main__":
    _manual_roundtrip_test()
