# -*- coding: utf-8 -*-
"""호출어("자비스") 감지 래퍼 (local-wake, PyPI 패키지명 `local-wake`, import명 `lwake`).

주의: PyPI 배포명은 `local-wake`이지만 실제로 import하는 모듈명은 `lwake`다
(`pip show local-wake` -> Location의 dist-info는 `local_wake-*`이지만 RECORD의
top_level.txt는 `lwake` 하나뿐 — 실측 확인, requirements.txt의 `local-wake>=0.1.0`
은 그대로 두고 이 파일에서만 `import lwake`).

lwake가 실제로 제공하는 것(설치된 0.1.2 소스로 확인):
  - lwake.record(output, duration, trim_silence=True, stream=None)
      마이크에서 duration초 녹음 후 Silero VAD로 무음 트리밍, wav로 저장
  - lwake.compare(file1, file2, method="embedding")
      두 오디오 파일의 DTW 코사인 거리 계산
  - lwake.listen(support_folder, threshold, method="embedding",
                 buffer_size=2.0, slide_size=0.25, callback=None, stream=None)
      마이크를 계속 읽으며 support_folder의 각 참조 wav와 DTW 거리를 비교,
      threshold 미만이면 callback(detection, stream) 호출. 기본은 무한 루프
      (blocking) — 콜백 안에서 별도 처리를 하거나, 콜백이 예외/특수 신호로
      빠져나오게 해야 한다.

온보딩(docs/decisions.md: "본인 목소리 3~4회 녹음만으로 온보딩 완료"):
  local-wake는 학습이 아니라 "참조 파일 폴더"를 쓰는 방식이라, 온보딩은
  사용자 목소리로 호출어를 3~4회 녹음해 support_folder(예:
  models/wakeword/<wake_word>/)에 wav로 저장하는 것으로 끝난다. 이후 listen()이
  이 폴더를 참조 세트로 읽는다.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("voice.wakeword")

DEFAULT_WAKE_WORD = "자비스"
DEFAULT_THRESHOLD = 0.65  # lwake listen_cmd 예제 기본값 부재 — compare 실측 후 임계값 정할 것(TODO)
DEFAULT_ONBOARD_COUNT = 4  # decisions.md: "3~4회 녹음"
DEFAULT_SAMPLE_DIR = Path("models/wakeword")
VOICE_SETTINGS_PATH = Path(".claude/voice-settings.json")


def get_configured_wake_word() -> str:
    """.claude/voice-settings.json의 wake_word 키를 읽는다. 파일 없으면 기본값 "자비스".

    작업 지시서 요구사항: "설정 파일이 없으면 기본값 사용".
    """
    if not VOICE_SETTINGS_PATH.exists():
        return DEFAULT_WAKE_WORD
    try:
        data = json.loads(VOICE_SETTINGS_PATH.read_text(encoding="utf-8"))
        return data.get("wake_word", DEFAULT_WAKE_WORD) or DEFAULT_WAKE_WORD
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("voice-settings.json 읽기 실패, 기본 호출어 사용: %s", e)
        return DEFAULT_WAKE_WORD


def _sample_dir_for(wake_word: str, base_dir: Path = DEFAULT_SAMPLE_DIR) -> Path:
    return base_dir / wake_word


def onboard(wake_word: Optional[str] = None, count: int = DEFAULT_ONBOARD_COUNT,
            duration: int = 2, base_dir: Path = DEFAULT_SAMPLE_DIR) -> Path:
    """본인 목소리로 호출어를 count회 녹음해 참조 세트(support_folder)를 만든다.

    :param wake_word: 녹음할 호출어(폴더명으로도 씀). None이면 설정 파일 값(또는 기본값)
    :param count: 녹음 횟수 (decisions.md: 3~4회)
    :param duration: 1회 녹음 길이(초)
    :return: 생성된 참조 세트 폴더 경로
    """
    import lwake  # 지연 임포트: 마이크/onnxruntime 등 무거운 의존성

    word = wake_word or get_configured_wake_word()
    out_dir = _sample_dir_for(word, base_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for i in range(1, count + 1):
        out_path = out_dir / f"sample_{i}.wav"
        input(f"[{i}/{count}] Enter를 누르고 바로 '{word}'라고 말하세요 ({duration}초 녹음)... ")
        lwake.record(str(out_path), duration=duration, trim_silence=True)
        print(f"  저장: {out_path}")

    return out_dir


class WakeWordDetector:
    """local-wake listen()을 감싸 "감지 콜백" 스타일로 쓸 수 있게 한다.

    lwake.listen()은 자체적으로 무한 blocking 루프를 도는 구조라, 이 클래스는
    사용자가 준 on_detect 콜백을 그대로 전달한다. listener.py의 마이크 루프는
    이 클래스를 별도 스레드에서 실행해야 한다(작업 지시서 4번: "별도 스레드/
    asyncio task로 돌려서 TCP 서버와 동시에 동작").

    stop()은 lwake.listen() 내부에 정식 종료 훅이 없어(무한 while True),
    별도 스레드를 daemon=True로 돌리는 것으로 프로세스 종료 시 자연 정리되는
    방식에 의존한다 — 단일 발화 감지 후 상위 루프가 스레드를 다시 만드는
    방식으로 우회한다(listener.py 쪽 설계, 아래 참고).
    """

    def __init__(self, wake_word: Optional[str] = None,
                 threshold: float = DEFAULT_THRESHOLD,
                 base_dir: Path = DEFAULT_SAMPLE_DIR):
        self.wake_word = wake_word or get_configured_wake_word()
        self.threshold = threshold
        self.support_folder = _sample_dir_for(self.wake_word, base_dir)

    def is_onboarded(self) -> bool:
        """참조 세트가 준비돼 있는지(온보딩 완료 여부)."""
        if not self.support_folder.exists():
            return False
        return any(self.support_folder.glob("*.wav"))

    def listen_blocking(self, on_detect: Callable[[dict], None],
                         stream=None) -> None:
        """마이크를 열어 감지 시 on_detect(detection)을 호출한다. 이 호출은 블로킹된다.

        listener.py의 마이크 루프 스레드 안에서 호출해야 한다.
        """
        import lwake

        if not self.is_onboarded():
            raise RuntimeError(
                f"호출어 '{self.wake_word}' 온보딩이 안 됐습니다. "
                f"먼저 onboard()를 실행하세요 (참조 폴더: {self.support_folder})"
            )

        def _callback(detection: dict, _stream) -> None:
            on_detect(detection)

        lwake.listen(
            str(self.support_folder),
            self.threshold,
            callback=_callback,
            stream=stream,
        )


def _manual_import_check():
    """수동 실행 검증용: import와 초기화만 확인 (마이크 실시간 테스트는 별도).

    python voice/wakeword.py
    """
    import lwake  # noqa: F401 — import 자체가 검증 대상

    print("[wakeword-test] lwake import 성공")
    word = get_configured_wake_word()
    print(f"[wakeword-test] 설정된 호출어: {word!r} (voice-settings.json 없으면 기본값)")

    detector = WakeWordDetector(wake_word=word)
    print(f"[wakeword-test] WakeWordDetector 초기화 성공, 참조 폴더: {detector.support_folder}")
    print(f"[wakeword-test] 온보딩 여부: {detector.is_onboarded()}")
    print("[wakeword-test] 주의: 마이크 실시간 감지(listen_blocking)는 사람이 실제로")
    print("[wakeword-test] 말해야 검증 가능 — 이 스크립트는 import/초기화까지만 확인함")


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    if sys.argv[1:2] == ["onboard"]:
        # 사람이 직접 터미널에서 실행한다: python -m voice.wakeword onboard [호출어]
        folder = onboard(sys.argv[2] if len(sys.argv) > 2 else None)
        print(f"호출어 녹음 완료: {folder}")
    else:
        _manual_import_check()
