# -*- coding: utf-8 -*-
"""verify.cmd에서 호출하는 음성 명령 판단기(voice/judge.py) 자가 점검 (네트워크 없음).

실제 Jev 호출은 하지 않는다 — ask 함수를 바꿔 끼워 규칙·키 없음·오류·응답 해석만 확인.
실패하면 0이 아닌 코드로 종료한다.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, ".")

import voice.judge as judge  # noqa: E402

SESSIONS = [
    {"key": "SECRET-SOCKET-PATH-1", "project": "proj-a", "summary": "로그인 고침", "paused": False},
    {"key": "SECRET-SOCKET-PATH-2", "project": "bunjang-bot", "summary": "키워드 추가함", "paused": True},
]


def must_not_call(payload, key):
    raise AssertionError("Jev가 호출되면 안 되는 경우에 호출됨")


def answers(cmd="stop", cmd_conf=0.9, target="s2", target_conf=0.85):
    return {
        "command": {"type": "choice", "choice": cmd, "confidence": cmd_conf},
        "target": {"type": "choice", "choice": target, "confidence": target_conf},
    }


# --- 1. 규칙: 괄호 표기·빈 문장은 Jev 없이 잡음 ---
for t in ("(음악)", "[두 번째]", "   "):
    d = judge.judge(t, SESSIONS, ask=must_not_call)
    assert d is not None and d.command == "noise" and d.source == "rule", t

# --- 2. 키 없음 -> None, Jev 호출 안 함 ---
os.environ.pop("TYPESAFE_API_KEY", None)
judge.ENV_FILE = Path(".claude/__no_such_env_file__")
assert judge.judge("번개장터 멈춰", SESSIONS, ask=must_not_call) is None

os.environ["TYPESAFE_API_KEY"] = "dummy"

# --- 3. Jev 예외 -> None (예외가 밖으로 안 샘) ---
def boom(payload, key):
    raise TimeoutError("simulated")
assert judge.judge("번개장터 멈춰", SESSIONS, ask=boom) is None

# --- 4. 형식 이상 -> None ---
assert judge.judge("x", SESSIONS, ask=lambda p, k: answers(cmd="explode")) is None, "옵션 밖 명령"
assert judge.judge("x", SESSIONS, ask=lambda p, k: answers(target="s9")) is None, "옵션 밖 대상"
assert judge.judge("x", SESSIONS, ask=lambda p, k: {"command": answers()["command"]}) is None, "target 누락"
no_conf = answers()
del no_conf["command"]["confidence"]
assert judge.judge("x", SESSIONS, ask=lambda p, k: no_conf) is None, "확신도 없음"

# --- 5. 정상 응답: s2 -> 두 번째 세션 key로 되돌림 ---
d = judge.judge("번개장터 멈춰", SESSIONS, ask=lambda p, k: answers())
assert d == judge.Decision("stop", 0.9, "SECRET-SOCKET-PATH-2", 0.85, "jev"), d
d = judge.judge("멈춰 (proj-a)", SESSIONS, ask=lambda p, k: answers())
assert d is not None and d.source == "jev", "문장 일부만 괄호면 규칙 대상 아님"
d = judge.judge("전부 멈춰", SESSIONS, ask=lambda p, k: answers("stop_all", 0.95, "all", 0.9))
assert d.target == judge.TARGET_ALL and d.command == "stop_all"

# --- 6. confidence 없이 probabilities만 오면 최댓값 ---
probs_only = answers()
del probs_only["command"]["confidence"]
probs_only["command"]["probabilities"] = {"stop": 0.7, "instruct": 0.2, "noise": 0.1}
d = judge.judge("x", SESSIONS, ask=lambda p, k: probs_only)
assert d is not None and abs(d.command_conf - 0.7) < 1e-9

# --- 7. 외부로 나가는 내용에 세션 key(소켓 경로)가 없음, 모델 고정 ---
seen = {}
def capture(payload, key):
    seen["payload"] = payload
    return answers()
judge.judge("번개장터 멈춰", SESSIONS, ask=capture)
sent = json.dumps(seen["payload"], ensure_ascii=False)
assert "SECRET-SOCKET-PATH" not in sent, "세션 key가 외부 전송 내용에 들어감"
assert seen["payload"]["model"] == "jev-1.13.0"
assert "bunjang-bot" in seen["payload"]["state"] and "멈춤 상태" in seen["payload"]["state"]

# --- 8. 옵션 구성 ---
qs = seen["payload"]["questions"]
assert tuple(qs["command"]["criteria"]) == judge.COMMANDS
assert set(qs["target"]["criteria"]) == {"s1", "s2", "all", "listener", "unknown"}
empty_payload, _ = judge.build_payload("안녕", [])
assert set(empty_payload["questions"]["target"]["criteria"]) == {"all", "listener", "unknown"}

# --- 9. 알림 종류 판단(4단계, 기록용): 정상 / 옵션 밖 / 예외 / 키 없음 ---
kind_ans = {"kind": {"type": "choice", "choice": "failed", "confidence": 0.93}}
assert judge.classify_notice("테스트가 실패했습니다", ask=lambda p, k: kind_ans) == ("failed", 0.93)
assert judge.classify_notice("x", ask=lambda p, k: {"kind": {"choice": "weird", "confidence": 1}}) is None
assert judge.classify_notice("x", ask=boom) is None
os.environ.pop("TYPESAFE_API_KEY", None)
assert judge.classify_notice("x", ask=must_not_call) is None
print("judge checks OK")
