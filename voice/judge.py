# -*- coding: utf-8 -*-
"""받아쓴 문장이 whisper 환각인지 판정 (known-issues.md 15번 완화책).

whisper는 무음·잡음에서도 "[두 번째]", "시청해 주셔서 감사합니다." 같은 문장을
지어낸다. 그대로 라우팅되면 엉뚱한 텍스트가 세션에 주입되므로, STT 직후·라우팅
직전에 한 번 거른다. docs/architecture.md "받아쓰기 환각 필터" 절 참고.

판정 순서(최소성 사다리):
  1. 규칙: 문장 전체가 괄호로 감싸인 표기("(음악)", "[두 번째]")면 바로 환각.
  2. Jev(TypeSafe 판단 모델): 키가 있을 때만. 환각 확률을 noul로 받는다.
     키가 없거나 오류·타임아웃이면 None — 호출부는 "판정 못 함 = 통과"로 처리한다.

주의: 키가 설정돼 있으면 받아쓴 문장이 TypeSafe(미국) 서버로 전송된다(README 참고).
이 모듈은 마이크 스레드에서 불리므로 어떤 예외도 밖으로 내보내지 않는다 — 여기서
예외가 새면 MicLoop._run_safe까지 올라가 마이크 루프가 통째로 죽는다.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Optional

JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-1.13.0"  # 별칭(jev-latest)은 코드 변경 없이 답이 바뀔 수 있어 버전 고정
JEV_TIMEOUT_S = 3.0
ENV_FILE = Path(".env")

# 이 이상이면 환각으로 보고 버린다. 2026-11-20 실호출 14건(합성 문장)에서 환각
# 0.58~0.80, 실제 발화 0.05~0.31로 갈림 — 실제 마이크 로그가 쌓이면 다시 조정.
HALLUCINATION_THRESHOLD = 0.5

_BRACKETED = re.compile(r"\s*[\[\(（【].*[\]\)）】]\s*")

_QUESTION = {
    "halluc": {
        "type": "noul",
        "instructions": (
            "whisper 같은 음성인식 모델은 무음이나 잡음만 들어와도 그럴듯한 문장을 지어낸다(환각). "
            "예: 대괄호·괄호 표기, 영상 자막 끝인사, 맥락 없이 잘린 조각. 아래 '받아쓴 문장'이 그런 "
            "환각일 확률을 답하라. 사람이 한 짧은 대답(응, 고고, 1번, 고쳐)은 환각이 아니다."
        ),
    }
}


def _load_key() -> Optional[str]:
    key = os.environ.get("TYPESAFE_API_KEY")
    if key:
        return key.strip()
    try:
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() == "TYPESAFE_API_KEY" and value.strip():
                return value.strip().strip('"').strip("'")
    except OSError:
        pass
    return None


def _ask_jev(text: str, key: str) -> Optional[float]:
    payload = {"model": JEV_MODEL, "state": f"받아쓴 문장: {text}", "questions": _QUESTION}
    req = urllib.request.Request(
        JEV_URL,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=JEV_TIMEOUT_S) as r:
        answers = json.loads(r.read().decode("utf-8")).get("answers", {})
    return float(answers["halluc"]["noul"])


def hallucination_score(text: str) -> Optional[float]:
    """환각 확률(0~1)을 반환. 판정할 수 없으면 None."""
    try:
        if _BRACKETED.fullmatch(text):
            return 1.0
        key = _load_key()
        if not key:
            return None
        return _ask_jev(text, key)
    except Exception:  # noqa: BLE001 - fail-open: 판정 실패가 받아쓰기를 막으면 안 됨
        return None


def is_hallucination(text: str, score: Optional[float]) -> bool:
    return score is not None and score >= HALLUCINATION_THRESHOLD
