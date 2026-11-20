# -*- coding: utf-8 -*-
"""VAD(발화 감지) 래퍼 (Silero VAD).

requirements.txt의 `silero-vad`(2026-11-20까지는 local-wake가 함께 설치해 줬다).

호출어 말소리 구간 자르기(voice/wakeword.py)와 받아쓰기 종료 시점을 판단한다 — 침묵이 일정 시간 이상 지속되면
발화가 끝났다고 본다(SpeechEndDetector). 내부적으로 Silero VAD의 `VADIterator`(청크 단위 스트리밍 API)를 쓴다.
마이크에서 오는 실시간 청크를 한 번에 하나씩 넣는 구조라 listener.py의
마이크 루프와 자연스럽게 맞물린다.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

SAMPLE_RATE = 16000  # Silero VAD 권장 샘플레이트(8000 또는 16000). 마이크 입력도 이에 맞춘다.
# VADIterator는 16kHz에서 정확히 512 샘플(32ms) 청크를 요구한다(문서/구현 확인).
CHUNK_SAMPLES = 512


_model_cache = None


def _get_model():
    """Silero VAD 모델을 프로세스당 1회만 로딩(functools.cache처럼 동작)."""
    global _model_cache
    if _model_cache is None:
        from silero_vad import load_silero_vad
        _model_cache = load_silero_vad()
    return _model_cache


class SpeechEndDetector:
    """호출어 감지 후 받아쓰기 모드에서 "발화 종료(침묵)"를 판단한다.

    사용법: 마이크 청크가 들어올 때마다 push(chunk)를 호출한다.
    발화가 시작된 뒤 silence_duration_s 이상 침묵이 이어지면
    is_finished가 True가 된다.
    """

    def __init__(self, silence_duration_s: float = 0.8,
                 threshold: float = 0.5,
                 sample_rate: int = SAMPLE_RATE):
        self._model = _get_model()
        self._iterator_threshold = threshold
        self._sample_rate = sample_rate
        self._silence_duration_s = silence_duration_s

        from silero_vad import VADIterator
        self._vad_iter = VADIterator(
            self._model, threshold=threshold, sampling_rate=sample_rate,
        )

        self._speech_started = False
        # 벽시계(time.monotonic) 대신 "지금까지 처리한 오디오 샘플 수"로 시간을
        # 잰다 — 청크가 마이크 콜백처럼 실제 오디오 속도로 들어오면 결과가
        # 같지만, 배치/비실시간 재생(테스트 등)에서 청크를 CPU 속도로 빠르게
        # 밀어넣어도 올바르게 동작한다(벽시계 기준은 이 경우 절대 안 끝남).
        self._samples_processed = 0
        self._last_speech_end_samples: Optional[int] = None
        self._finished = False

    def push(self, chunk: np.ndarray) -> None:
        """CHUNK_SAMPLES 길이의 float32 청크 하나를 넣는다."""
        if self._finished:
            return
        result = self._vad_iter(chunk, return_seconds=False)
        self._samples_processed += len(chunk)

        if result is not None and "start" in result:
            self._speech_started = True
            self._last_speech_end_samples = None  # 다시 말하는 중이므로 침묵 카운트 리셋
        elif result is not None and "end" in result:
            self._last_speech_end_samples = self._samples_processed

        if self._speech_started and self._last_speech_end_samples is not None:
            silence_samples = self._samples_processed - self._last_speech_end_samples
            if silence_samples / self._sample_rate >= self._silence_duration_s:
                self._finished = True

    @property
    def is_finished(self) -> bool:
        return self._finished

    @property
    def has_speech_started(self) -> bool:
        return self._speech_started

    def reset(self) -> None:
        self._vad_iter.reset_states()
        self._speech_started = False
        self._samples_processed = 0
        self._last_speech_end_samples = None
        self._finished = False


def detect_speech_segments(audio: np.ndarray, sample_rate: int = SAMPLE_RATE,
                            threshold: float = 0.5) -> list[dict]:
    """오프라인 배치 분석: 전체 오디오에서 발화 구간(start/end 샘플)을 전부 찾는다.

    실시간 루프에는 쓰지 않는다(스트리밍은 위 두 클래스가 담당) — 테스트/
    검증용으로 get_speech_timestamps를 그대로 노출한 것.
    """
    from silero_vad import get_speech_timestamps

    model = _get_model()
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    return get_speech_timestamps(
        audio, model, sampling_rate=sample_rate, threshold=threshold,
        return_seconds=False,
    )


def _synthesize_silence_speech_silence(sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """검증용: 무음 1초 + 사인파(발화 대역 유사 주파수) 1초 + 무음 1초 합성."""
    silence = np.zeros(sample_rate, dtype=np.float32)
    t = np.linspace(0, 1.0, sample_rate, endpoint=False)
    # 사람 목소리 기본 주파수대와 겹치는 200Hz 사인파 + 배음을 섞어 변조를 줌
    # (순수 단일 사인파는 VAD가 발화로 인식하지 않을 수 있어, 여러 하모닉으로 변조 흉내)
    tone = (
        0.5 * np.sin(2 * np.pi * 200 * t)
        + 0.3 * np.sin(2 * np.pi * 400 * t)
        + 0.2 * np.sin(2 * np.pi * 800 * t)
    ).astype(np.float32)
    # 진폭을 살짝 흔들어 정적 톤보다 발화에 가깝게(무변조 사인파는 VAD가 못 잡을 수 있음)
    envelope = (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t)).astype(np.float32)
    tone = tone * envelope
    return np.concatenate([silence, tone, silence]).astype(np.float32)


def _manual_test():
    """수동 실행 검증용: 무음+톤+무음 합성 오디오로 발화 구간 경계 확인.

    python voice/vad.py
    """
    audio = _synthesize_silence_speech_silence()
    print(f"[vad-test] 합성 오디오 길이: {len(audio)/SAMPLE_RATE:.1f}s")

    segments = detect_speech_segments(audio)
    print(f"[vad-test] 감지된 발화 구간(샘플): {segments}")
    for seg in segments:
        print(
            f"[vad-test]   {seg['start']/SAMPLE_RATE:.2f}s ~ "
            f"{seg['end']/SAMPLE_RATE:.2f}s"
        )

    # 스트리밍 API(SpeechEndDetector)로도 같은 오디오를 청크 단위로 흘려서 확인
    print("[vad-test] --- 스트리밍(SpeechEndDetector) 확인 ---")
    detector = SpeechEndDetector(silence_duration_s=0.5)
    n_chunks = len(audio) // CHUNK_SAMPLES
    finished_at_chunk = None
    started_at_chunk = None
    for i in range(n_chunks):
        chunk = audio[i * CHUNK_SAMPLES:(i + 1) * CHUNK_SAMPLES]
        was_started = detector.has_speech_started
        detector.push(chunk)
        if not was_started and detector.has_speech_started:
            started_at_chunk = i
        if detector.is_finished and finished_at_chunk is None:
            finished_at_chunk = i
    if started_at_chunk is not None:
        print(f"[vad-test] 발화 시작 감지: 약 {started_at_chunk * CHUNK_SAMPLES / SAMPLE_RATE:.2f}s")
    else:
        print("[vad-test] 발화 시작 감지 안 됨")
    if finished_at_chunk is not None:
        print(f"[vad-test] 발화 종료(침묵) 감지: 약 {finished_at_chunk * CHUNK_SAMPLES / SAMPLE_RATE:.2f}s")
    else:
        print("[vad-test] 발화 종료 감지 안 됨(오디오 끝까지 미종료)")


if __name__ == "__main__":
    _manual_test()
