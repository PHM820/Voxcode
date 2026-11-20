# -*- coding: utf-8 -*-
"""받아쓴 음성 명령의 "명령 종류"와 "대상 세션"을 Jev 호출 한 번으로 판단.

docs/architecture.md "다음 설계: 판단 3단계" 절의 1·2단계(규칙 → Jev)다.
  1. 규칙: 문장 전체가 괄호 표기("(음악)", "[두 번째]")거나 비어 있으면 잡음(noise).
  2. Jev(TypeSafe 판단 모델): 키가 있을 때만. 질문 두 개(command, target)를 한 요청에.
     키가 없거나 오류·타임아웃·형식 이상이면 None — 호출부(listener.route_and_send)가
     규칙(방금 알림 온 세션)으로 돌아간다. 확신도 기준선(CONFIDENCE_THRESHOLD) 적용도 호출부 몫.

주의: 키가 설정돼 있으면 받아쓴 문장과 열린 프로젝트 이름·마지막 요약이 TypeSafe(미국)
서버로 전송된다(README 참고). 소켓 경로·토큰·세션 key는 보내지 않는다 — 대상 옵션은 s1, s2…로
바꿔 보내고 답을 받은 뒤 되돌린다.
이 모듈은 마이크 스레드에서 불리므로 어떤 예외도 밖으로 내보내지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-1.13.0"  # 별칭(jev-latest)은 코드 변경 없이 답이 바뀔 수 있어 버전 고정
JEV_TIMEOUT_S = 3.0
ENV_FILE = Path(".env")

# 판단을 그대로 실행할 확신도 기준선. 처음 0.8, 실사용 로그(log.jsonl)로 조정.
CONFIDENCE_THRESHOLD = 0.8

COMMANDS = (
    "instruct", "stop", "stop_all", "resume", "cancel", "noise",
    # 리스너가 직접 답하는 명령 (2단계)
    "list", "repeat", "quiet", "verbose", "status",
    # 서브 관리자가 함께 쓰는 명령 (3단계)
    "catch_up", "instruct_all",
)
TARGET_ALL = "all"
TARGET_LISTENER = "listener"
TARGET_UNKNOWN = "unknown"

SUMMARY_MAX_CHARS = 300

_BRACKETED = re.compile(r"\s*[\[\(（【].*[\]\)）】]\s*")

_COMMAND_OPTIONS = {
    "instruct": "프로젝트에 시키는 작업 지시나 대답(기본). 예: '키워드 추가해', '응', '1번', '고쳐'",
    "stop": "특정 프로젝트 하나를 멈추라는 말. 예: '번개장터 멈춰', '그거 그만해'",
    "stop_all": "모든 작업을 멈추라는 말. 예: '전부 멈춰', '다 그만'",
    "resume": "멈췄던 프로젝트를 다시 하라는 말. 예: '번개장터 계속해', '다시 시작해'",
    "cancel": "방금 한 말을 취소. 예: '아니야 취소', '방금 거 무시해'",
    "noise": (
        "음성인식이 무음·잡음에서 지어낸 문장이나 의미 없는 조각. 예: '시청해 주셔서 감사합니다.' "
        "사람이 한 짧은 대답(응, 고고, 1번, 고쳐)은 noise가 아니라 instruct"
    ),
    "list": "음성 비서에게 열린 프로젝트 목록을 묻는 말. 예: '뭐 열려 있어?', '프로젝트 뭐 있어'",
    "repeat": "음성 비서에게 방금 읽어 준 안내를 다시 읽으라는 말. 예: '방금 거 다시', '다시 말해줘'",
    "quiet": "음성 비서에게 알림을 줄이라는 말. 예: '조용히 해', '중요한 것만 알려줘'",
    "verbose": "음성 비서에게 알림을 다시 다 읽으라는 말. 예: '다 알려줘', '조용히 모드 꺼'",
    "status": "프로젝트 진행 상황을 묻는 말. 예: '번개장터 어떻게 됐어?', '다들 어디까지 했어?'",
    "catch_up": "자리를 비운 동안 들어온 소식을 몰아서 듣고 싶다는 말. 예: '나 없는 동안 뭐 했어?', '밀린 거 알려줘'",
    "instruct_all": "열린 모든 프로젝트에 같은 작업을 시키는 말. 예: '다들 커밋하고 정리해', '전부 테스트 돌려'",
}

COMMAND_HELP = _COMMAND_OPTIONS  # 서브 관리자에게도 같은 설명을 준다

_TARGET_INSTRUCTIONS = (
    "이 음성 명령이 어느 프로젝트를 향한 말인지 고르라. 프로젝트 이름은 영어 폴더명이고 사용자는 "
    "한국어로 부르므로 뜻·발음·마지막 요약 내용으로 연결하라. 모든 프로젝트를 향하면 all, "
    "특정 프로젝트가 아니라 음성 비서 자신에게 하는 말이면 listener, 문장에 어느 프로젝트인지 "
    "단서가 없으면 unknown."
)


# 완료·알림 문장의 종류 (4단계 듣기). 처음 1주는 기록만 하고 읽기 동작에는 쓰지 않는다.
NOTICE_KINDS = {
    "done": "작업을 끝냈다는 보고",
    "failed": "실패·오류·막힘 보고",
    "question": "사용자에게 묻거나 승인·선택을 기다림",
    "progress": "아직 진행 중이라는 중간 보고",
}


@dataclass(frozen=True)
class Decision:
    command: str        # COMMANDS 중 하나
    command_conf: float
    target: str         # 세션 key, 또는 TARGET_ALL / TARGET_LISTENER / TARGET_UNKNOWN
    target_conf: float
    source: str         # "rule" | "jev"


AskFn = Callable[[dict, str], dict]


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


def _ask_jev(payload: dict, key: str) -> dict:
    req = urllib.request.Request(
        JEV_URL,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=JEV_TIMEOUT_S) as r:
        return json.loads(r.read().decode("utf-8")).get("answers", {})


def build_payload(text: str, sessions: list[dict]) -> tuple[dict, dict[str, str]]:
    """Jev 요청 본문과 (옵션명 → 세션 key) 표를 만든다. 외부로 나가는 내용은 여기서만 정한다."""
    alias: dict[str, str] = {}
    target_options: dict[str, str] = {}
    lines = [f"받아쓴 문장: {text}", "열린 프로젝트:"]
    for i, s in enumerate(sessions, start=1):
        name = f"s{i}"
        alias[name] = s["key"]
        paused = " (멈춤 상태)" if s.get("paused") else ""
        summary = (s.get("summary") or "").strip()[:SUMMARY_MAX_CHARS]
        target_options[name] = f"{s['project']} 프로젝트{paused}. 마지막 요약: {summary or '없음'}"
        lines.append(f"- {name}: {s['project']}{paused} / 마지막 요약: {summary or '없음'}")
    if not sessions:
        lines.append("- (없음)")
    target_options[TARGET_ALL] = "열린 모든 프로젝트"
    target_options[TARGET_LISTENER] = "특정 프로젝트가 아니라 음성 비서 자신"
    target_options[TARGET_UNKNOWN] = "어느 프로젝트인지 알 수 없음"

    payload = {
        "model": JEV_MODEL,
        "state": "\n".join(lines),
        "questions": {
            "command": {
                "type": "choice",
                "instructions": "사용자가 음성으로 한 이 말이 어떤 명령인지 고르라.",
                "criteria": dict(_COMMAND_OPTIONS),
            },
            "target": {
                "type": "choice",
                "instructions": _TARGET_INSTRUCTIONS,
                "criteria": target_options,
            },
        },
    }
    return payload, alias


def _choice_and_conf(answer: dict, allowed) -> tuple[str, float]:
    choice = answer["choice"]
    if choice not in allowed:
        raise ValueError(f"옵션 밖 답: {choice!r}")
    conf = answer.get("confidence")
    if not isinstance(conf, (int, float)):
        probs = answer.get("probabilities")
        if not isinstance(probs, dict) or not probs:
            raise ValueError("확신도 없음")
        conf = max(float(v) for v in probs.values())
    return choice, float(conf)


def judge(text: str, sessions: list[dict], ask: Optional[AskFn] = None) -> Optional[Decision]:
    """sessions 각 항목: {"key", "project", "summary", "paused"}. 판단 못 하면 None.

    ask는 테스트에서 네트워크 없이 바꿔 끼우는 용도: ask(payload, key) -> answers dict.
    """
    try:
        if not text.strip() or _BRACKETED.fullmatch(text):
            return Decision("noise", 1.0, TARGET_UNKNOWN, 1.0, "rule")
        key = _load_key()
        if not key:
            return None
        payload, alias = build_payload(text, sessions)
        answers = (ask or _ask_jev)(payload, key)
        command, command_conf = _choice_and_conf(answers["command"], COMMANDS)
        target_allowed = set(alias) | {TARGET_ALL, TARGET_LISTENER, TARGET_UNKNOWN}
        target, target_conf = _choice_and_conf(answers["target"], target_allowed)
        return Decision(command, command_conf, alias.get(target, target), target_conf, "jev")
    except Exception:  # noqa: BLE001 - 판단 실패는 None(규칙 폴백), 마이크 스레드로 새면 안 됨
        return None


def classify_notice(text: str, ask: Optional[AskFn] = None) -> Optional[tuple[str, float]]:
    """완료·알림 문장의 종류와 확신도. 키 없음·오류면 None. 예외를 밖으로 내보내지 않는다."""
    try:
        key = _load_key()
        if not key or not text.strip():
            return None
        payload = {
            "model": JEV_MODEL,
            "state": f"코딩 작업 세션이 보낸 알림: {text[:SUMMARY_MAX_CHARS]}",
            "questions": {"kind": {"type": "choice", "instructions": "이 알림의 종류를 고르라.",
                                   "criteria": dict(NOTICE_KINDS)}},
        }
        return _choice_and_conf((ask or _ask_jev)(payload, key)["kind"], NOTICE_KINDS)
    except Exception:  # noqa: BLE001
        return None
