# -*- coding: utf-8 -*-
"""TTS 엔진 래퍼 (sherpa-onnx).

최소 버전: 한국어 모델(vits-mimic3-ko_KO-kss_low) 하드코딩.
언어별 모델 교체는 TODO — 지금은 이 프로젝트가 한국어만 다루므로 보류.

참고: `.scratch/sherpa_tts_test.py` (실측 검증된 원본 스크립트)를 그대로
구조만 함수화한 것. 로직 변경 없음.
"""
from __future__ import annotations

import sys
import threading

import numpy as np
import sherpa_onnx
import sounddevice as sd

# TODO: voice-settings.json에서 language 읽어 언어별 모델 디렉토리를 고르게 할 것
# (지금은 한국어 하나뿐이라 하드코딩, architecture.md 참고)
DEFAULT_MODEL_DIR = "models/tts/vits-mimic3-ko_KO-kss_low"


class TtsEngine:
    """sherpa-onnx VITS 모델을 한 번 로딩해 재사용하는 래퍼.

    상주 프로세스가 이벤트마다 모델을 새로 로딩하지 않도록(무거운 로딩은
    상주 프로세스 시작 시 1회만) 클래스로 감쌌다.
    """

    def __init__(self, model_dir: str = DEFAULT_MODEL_DIR):
        config = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=f"{model_dir}/ko_KO-kss_low.onnx",
                    tokens=f"{model_dir}/tokens.txt",
                    data_dir=f"{model_dir}/espeak-ng-data",
                ),
                num_threads=2,
                provider="cpu",
            ),
        )
        self._tts = sherpa_onnx.OfflineTts(config)
        # sounddevice 재생은 스레드-세이프하지 않을 수 있어 직렬화용 락 사용.
        # (같은 프로세스 안에서 재생 큐가 순차 호출하므로 이론상 불필요하지만,
        #  테스트 코드에서 병렬로 부를 가능성을 막는 안전장치)
        self._play_lock = threading.Lock()

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        """텍스트 -> (샘플, 샘플레이트). 재생 없이 합성만 한다."""
        audio = self._tts.generate(text, sid=0, speed=1.0)
        return audio.samples, audio.sample_rate

    def speak(self, text: str) -> None:
        """합성 + 스피커로 재생까지 동기적으로 수행(재생이 끝날 때까지 블록)."""
        samples, sample_rate = self.synthesize(text)
        with self._play_lock:
            sd.play(samples, samplerate=sample_rate)
            sd.wait()

    def stop(self) -> None:
        """재생 중인 오디오를 즉시 중단한다 (바지-인용).

        speak()는 sd.wait()로 블록 중이므로, 다른 스레드에서 이 메서드를
        부르면 sd.stop()이 재생을 끊고 sd.wait()가 곧바로 반환한다
        (sounddevice의 표준 동작 — 별도 락 없이 호출 가능).
        """
        sd.stop()


def _manual_test():
    """수동 실행 검증용: python voice/tts.py "읽을 텍스트" """
    text = " ".join(sys.argv[1:]) or "안녕하세요. 테스트입니다."
    engine = TtsEngine()
    print(f"[tts] 합성 중: {text!r}")
    engine.speak(text)
    print("[tts] 재생 완료")


if __name__ == "__main__":
    _manual_test()
