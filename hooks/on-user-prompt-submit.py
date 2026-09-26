# -*- coding: utf-8 -*-
"""UserPromptSubmit 훅: 음성모드가 켜진 프로젝트에서 매 프롬프트마다
"응답 끝을 TTS로 듣기 적합하게 짧게 맺어라"는 지침을 재주입한다.

docs/architecture.md "음성모드 응답 스타일 강제 — '3중 재주입' 설계" 참고.
이 훅은 3중 중 우선순위 1(핵심) — 매 턴 강제되는 유일한 지점이다. CLAUDE.md
(우선순위 2)는 세션 시작 시 1회 로드라 대화가 길어지면 그 지침 자체를 Claude가
잊는 사례가 실측 확인됐기 때문에, 대화 길이와 무관하게 매번 다시 심어준다.

절대 원칙 (hooks/on-stop.py와 동일): 이 훅도 Claude Code 흐름을 막거나
늦추면 안 되고, 어떤 예외가 나도 항상 exit 0으로 끝난다. 단, UserPromptSubmit은
공식 기본 타임아웃이 30초(다른 이벤트의 600초보다 짧음)이므로 원래도 여유가
있지만, 이 훅은 네트워크 호출 없이 로컬 파일 읽기 하나뿐이라 지연 자체가 거의
없다.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from voice.config import is_enabled  # noqa: E402

# additionalContext로 주입할 지침 문구. CLAUDE.md의 같은 취지 지침과 문구를
# 맞춰 둔다(우선순위 1, 2가 서로 다른 말을 하면 혼란을 주므로) — CLAUDE.md 쪽
# 지침을 수정하면 이 문구도 함께 맞출 것.
VOICE_MODE_REMINDER = (
    "[음성모드 켜짐] 이 응답의 끝은 TTS로 읽힙니다. 코드블록·파일 경로 나열 "
    "없이 1~2문장의 짧고 자연스러운 한국어 요약으로 맺으세요."
)


def _is_delegate_worker(cwd: str) -> bool:
    """hooks/on-stop.py와 동일한 판별 로직(중복이지만 훅 파일은 서로 독립
    프로세스로 실행되어 공유 모듈로 묶을 실익이 적어 그대로 복제)."""
    return "\\.claude\\worktrees\\" in cwd or "/.claude/worktrees/" in cwd


def main() -> int:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8")
        payload = json.loads(raw) if raw else {}
    except Exception:
        payload = {}

    cwd_for_check = payload.get("cwd") or os.getcwd()
    if _is_delegate_worker(cwd_for_check):
        # /delegate, /delegate-all 워커 세션 — 음성모드와 무관, 지침 주입 불필요.
        return 0

    if not is_enabled():
        # 음성모드가 꺼져 있으면 이 훅은 할 일이 없다 — 매 프롬프트마다
        # 실행은 되지만(프로젝트 단위 등록이라 피할 수 없음), 파일 하나 읽고
        # 즉시 끝나는 구조라 실질 비용은 무시할 수준.
        return 0

    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": VOICE_MODE_REMINDER,
        }
    }
    try:
        # sys.stdout.write()는 Windows에서 콘솔 로케일 코드페이지(cp949 등)로
        # 인코딩되어 한글이 깨진다(hooks/on-stop.py의 stdin 디코딩 문제와
        # 대칭되는 stdout 버전, 2026-09-26 이 훅 작성 중 실측 확인) — 항상
        # 바이트로 직접 UTF-8 인코딩해 sys.stdout.buffer에 쓴다.
        sys.stdout.buffer.write(json.dumps(output, ensure_ascii=False).encode("utf-8"))
    except Exception:
        # stdout 쓰기 실패해도 훅 흐름은 막지 않는다.
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
