# -*- coding: utf-8 -*-
"""verify.cmd에서 호출하는 받아쓰기 환각 필터 자가 점검 (네트워크 없음).

실제 Jev 호출은 하지 않는다 — 키 유무·오류·점수별 분기만 판단 함수를 바꿔 끼워 확인.
실패하면 0이 아닌 코드로 종료한다.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, ".")

import voice.judge as judge  # noqa: E402
from voice.listener import should_drop_transcript  # noqa: E402

# --- 규칙: 괄호로 감싼 표기는 키 없이도 환각 ---
assert judge.hallucination_score("(음악)") == 1.0
assert judge.hallucination_score("[두 번째]") == 1.0
assert judge.hallucination_score("멈춰 (proj-a)") != 1.0, "문장 일부만 괄호면 규칙 대상 아님"

# --- 키 없음 -> None (통과) ---
os.environ.pop("TYPESAFE_API_KEY", None)
judge.ENV_FILE = Path(".claude/__no_such_env_file__")
assert judge.hallucination_score("다음 작업 해줘") is None

# --- Jev 호출 예외 -> None (fail-open, 마이크 스레드로 예외가 새면 안 됨) ---
os.environ["TYPESAFE_API_KEY"] = "dummy"
real_ask = judge._ask_jev
def _boom(text, key):
    raise TimeoutError("simulated")
judge._ask_jev = _boom
assert judge.hallucination_score("다음 작업 해줘") is None
judge._ask_jev = real_ask
os.environ.pop("TYPESAFE_API_KEY", None)

# --- 점수별 분기 (게이트) ---
assert should_drop_transcript("시청해 주셔서 감사합니다.", judge=lambda t: 0.8) == (True, 0.8)
assert should_drop_transcript("고쳐", judge=lambda t: 0.1) == (False, 0.1)
assert should_drop_transcript("응", judge=lambda t: None) == (False, None)
assert should_drop_transcript("경계값", judge=lambda t: 0.5)[0] is True, "기준선 이상이면 버림"

# --- "멈춰"는 판정 자체를 하지 않는다 ---
def _must_not_call(text):
    raise AssertionError("멈춰 명령에 판단 모델이 호출됨")
assert should_drop_transcript("멈춰 proj-a", judge=_must_not_call) == (False, None)

print("judge checks OK")
