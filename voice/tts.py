# -*- coding: utf-8 -*-
"""TTS 엔진 래퍼 (sherpa-onnx, 한국어 기본은 Supertonic 3 — VoiceOption.engine으로 고른다).

언어별 모델은 voice/languages.py의 VoiceOption 메타데이터로 고른다(온보딩에서
사용자가 언어+목소리를 고르면 models/tts/<voice_id>/에 받아 두고 voice-settings.json에
voice_id를 저장). voice_id가 없거나 못 찾으면 그 언어의 첫 번째 목소리를 쓴다.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import numpy as np
import sherpa_onnx
import sounddevice as sd

from voice.languages import DEFAULT_LANGUAGE_CODE, SUPERTONIC_DIR_NAME, find_language, find_voice

MODELS_ROOT = Path("models/tts")
SUPERTONIC_STEPS = 8  # 품질↔속도: 5면 한 문장 약 1초, 12면 약 2~3초(2026-11-20 이 PC 실측)
SUPERTONIC_SPEED = 1.1


def supertonic_dir(models_root: Path = MODELS_ROOT) -> Path | None:
    """Supertonic 모델 폴더(helper.py + onnx/ + voice_styles/)를 찾는다. 없으면 None.

    기본 위치는 models/tts/supertonic3/. 다른 곳에 이미 받아 둔 모델을 쓰려면(디스크 절약)
    models/tts/supertonic3.path 파일에 그 폴더 경로 한 줄을 적는다 — models/는 git 제외라
    개인 경로가 저장소에 들어가지 않는다. 그 폴더는 onnx/를 바로 아래 또는 assets/ 아래에 둬도 된다.
    """
    candidates = [models_root / SUPERTONIC_DIR_NAME]
    pointer = models_root / f"{SUPERTONIC_DIR_NAME}.path"
    if pointer.exists():
        candidates.append(Path(pointer.read_text(encoding="utf-8").strip().strip('"')))
    for root in candidates:
        if not (root / "helper.py").exists():
            continue
        for base in (root, root / "assets"):
            if (base / "onnx" / "tts.json").exists() and (base / "voice_styles").is_dir():
                return base
    return None


class _SupertonicTts:
    """Supertonic 3 (Supertone 공식 helper.py를 그대로 불러 쓴다)."""

    def __init__(self, base: Path, style_name: str, language_code: str):
        import importlib.util

        import onnxruntime as ort

        helper_py = base / "helper.py" if (base / "helper.py").exists() else base.parent / "helper.py"
        spec = importlib.util.spec_from_file_location("supertonic_helper", helper_py)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        opt = ort.SessionOptions()
        opt.intra_op_num_threads = 2
        opt.inter_op_num_threads = 1
        onnx_dir = str(base / "onnx")
        self._tts = helper.TextToSpeech(helper.load_cfgs(onnx_dir), helper.load_text_processor(onnx_dir),
                                        *helper.load_onnx_all(onnx_dir, opt, ["CPUExecutionProvider"]))
        self._style = helper.load_voice_style([str(base / "voice_styles" / f"{style_name}.json")])
        self._lang = language_code

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        audio, dur = self._tts(text, self._lang, self._style, SUPERTONIC_STEPS, SUPERTONIC_SPEED)
        sr = self._tts.sample_rate
        return np.asarray(audio[0, :int(sr * float(dur[0]))], dtype=np.float32), sr


class TtsEngine:
    """sherpa-onnx VITS 모델을 한 번 로딩해 재사용하는 래퍼.

    상주 프로세스가 이벤트마다 모델을 새로 로딩하지 않도록(무거운 로딩은
    상주 프로세스 시작 시 1회만) 클래스로 감쌌다.
    """

    def __init__(self, language_code: str = DEFAULT_LANGUAGE_CODE, voice_id: str | None = None):
        voice = find_voice(language_code, voice_id) if voice_id else None
        if voice is None:
            lang = find_language(language_code) or find_language(DEFAULT_LANGUAGE_CODE)
            voice = lang.voices[0]
        # sounddevice 재생은 스레드-세이프하지 않을 수 있어 직렬화용 락 사용.
        # (같은 프로세스 안에서 재생 큐가 순차 호출하므로 이론상 불필요하지만,
        #  테스트 코드에서 병렬로 부를 가능성을 막는 안전장치)
        self._play_lock = threading.Lock()
        self._supertonic = None
        self.voice = voice
        if voice.engine == "supertonic":
            base = supertonic_dir()
            if base is None:
                raise FileNotFoundError(
                    "Supertonic 모델이 없습니다: .claude\\download_tts_model.py " + voice.id + " 를 실행하세요")
            self._supertonic = _SupertonicTts(base, voice.onnx_name, language_code)
            return
        model_dir = MODELS_ROOT / voice.id

        vits_kwargs = dict(
            model=f"{model_dir}/{voice.onnx_name}",
            tokens=f"{model_dir}/tokens.txt",
        )
        if voice.needs_espeak:
            vits_kwargs["data_dir"] = f"{model_dir}/espeak-ng-data"
        if voice.needs_lexicon:
            vits_kwargs["lexicon"] = f"{model_dir}/lexicon.txt"

        config = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(**vits_kwargs),
                num_threads=2,
                provider="cpu",
            ),
        )
        self._tts = sherpa_onnx.OfflineTts(config)

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        """텍스트 -> (샘플, 샘플레이트). 재생 없이 합성만 한다."""
        if self._supertonic is not None:
            return self._supertonic.synthesize(text)
        audio = self._tts.generate(text, sid=0, speed=1.0)
        # sherpa_onnx는 audio.samples를 list[float]로 반환한다(np.ndarray 아님) —
        # 타입 힌트와 실제 반환값이 어긋나던 것을 여기서 정정(docs/decisions.md 참고).
        # 호출부(voice/stt.py의 resample_to_16k)가 np.asarray()로 이미 방어하고
        # 있어 실사용 경로는 원래도 안전했음.
        return np.asarray(audio.samples, dtype=np.float32), audio.sample_rate

    def speak(self, text: str) -> None:
        """합성 + 스피커로 재생까지 동기적으로 수행(재생이 끝날 때까지 블록)."""
        samples, sample_rate = self.synthesize(text)
        with self._play_lock:
            sd.play(samples, samplerate=sample_rate)
            sd.wait()

    def stop(self) -> None:
        """재생 중인 오디오를 즉시 중단한다 (호출어로 재생을 끊을 때).

        speak()는 sd.wait()로 블록 중이므로, 다른 스레드에서 이 메서드를
        부르면 sd.stop()이 재생을 끊고 sd.wait()가 곧바로 반환한다
        (sounddevice의 표준 동작 — 별도 락 없이 호출 가능).
        """
        sd.stop()


def _manual_test():
    """수동 실행 검증용: python voice/tts.py "읽을 텍스트" """
    text = " ".join(sys.argv[1:]) or "안녕하세요. 테스트입니다."
    engine = TtsEngine(language_code="ko")
    print(f"[tts] 합성 중: {text!r}")
    engine.speak(text)
    print("[tts] 재생 완료")


if __name__ == "__main__":
    _manual_test()
