# -*- coding: utf-8 -*-
"""Stop 훅: Claude Code 응답이 끝나면 상주 리스너(voice/listener.py)에게
완료 요약을 로컬 TCP로 전달한다.

docs/architecture.md "1. 작업 완료 → 음성 요약", docs/decisions.md 2026-09-25
"Stop 훅 payload 실측 완료" 항목 참고.

절대 원칙 (작업 지시서, docs/architecture.md "상주 프로세스가 죽었을 때 훅의
동작" 참고): 이 훅은 Claude Code의 응답 흐름을 절대 막거나 늦추면 안 된다.
- 소켓 연결 타임아웃은 짧게(0.3초 — 아래 CONNECT_TIMEOUT 주석의 실측 근거 참고)
- 상주 프로세스가 안 떠 있을 때 이 환경에서 실제로 나는 예외는
  ConnectionRefusedError가 아니라 TimeoutError였다(2026-09-26 실측, 아래
  CONNECT_TIMEOUT 주석 참고) — 어느 쪽이든 별도 폴백 없이 조용히 삼키고
  exit 0으로 끝난다(공식 터미널 벨이 이미 최소 신호를 주므로 이 훅이 대신할
  필요 없음).
- 그 외 어떤 예외가 나도 훅은 항상 exit 0으로 끝난다.
"""
from __future__ import annotations

import json
import os
import re
import socket
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from voice.config import is_enabled  # noqa: E402

HOST = "127.0.0.1"
PORT = 8765
# 초. 훅이 Claude Code 응답을 지연시키면 안 되므로 짧게 고정.
# 실측 확인(2026-09-26): 이 환경에서 listener.py가 안 떠 있을 때 즉시
# ConnectionRefusedError가 나지 않고 연결 자체가 TimeoutError로 걸린다(Windows
# 루프백 방화벽 설정 등의 영향으로 추정, RST 없이 조용히 무응답). 그래서
# 타임아웃 값이 곧 "리스너가 꺼져 있을 때 이 훅이 지연시키는 최대 시간"이 된다
# — 2초처럼 길게 두면 매 Stop 이벤트마다 체감 가능한 지연이 생기므로 0.3초로 짧게 잡는다.
CONNECT_TIMEOUT = 0.3


def _is_delegate_worker(cwd: str) -> bool:
    """`/delegate`, `/delegate-all`의 작업자(워커) 세션인지 판별.

    작업자는 항상 `.claude/worktrees/<이름>/` 아래 독립 복사본에서 실행된다
    (~/.claude/skills/delegate/SKILL.md, harness 스킬의 `.git/info/exclude`
    관례와 동일 경로). 관리자 세션은 이 경로 밖에서 돈다.
    """
    return "\\.claude\\worktrees\\" in cwd or "/.claude/worktrees/" in cwd


def last_paragraph(text: str) -> str:
    """응답의 마지막 문단만 TTS용으로 남긴다(마크다운 강조·코드 표시 기호 제거).

    응답 전체를 보내면 표·목록까지 전부 읽힌다. 음성모드 지침이 "끝을 1~2문장 요약으로
    맺으라"고 하므로 마지막 문단이 곧 요약이다.
    """
    paragraphs = [p.strip() for p in text.replace("\r\n", "\n").split("\n\n") if p.strip()]
    if not paragraphs:
        return ""
    return re.sub(r"[*`#]", "", paragraphs[-1]).strip()


def main() -> int:
    try:
        # sys.stdin.read()는 Windows에서 로케일 코드페이지(cp949 등)로 디코딩을
        # 시도해 UTF-8 JSON(한글 포함)을 깨뜨린다(2026-09-26 이 훅 작성 중 실측
        # 확인, known-issues.md 8/10번과 같은 "cmd/Windows와 UTF-8이 만나면
        # 깨진다" 계열의 새 사례) — 항상 바이트로 읽어 UTF-8로 직접 디코딩한다.
        raw = sys.stdin.buffer.read().decode("utf-8")
        payload = json.loads(raw) if raw else {}
    except Exception:
        # stdin이 비었거나 JSON이 아니어도 훅은 실패로 죽지 않는다.
        payload = {}

    text = last_paragraph(payload.get("last_assistant_message") or "")
    if not text:
        # 요약할 내용이 없으면 알릴 것도 없으니 조용히 종료.
        return 0

    cwd_for_check = payload.get("cwd") or os.getcwd()
    if _is_delegate_worker(cwd_for_check):
        # /delegate, /delegate-all의 하위 작업자(워커) 세션 — 사용자가 직접
        # /voice-on을 켠 적 없는 세션이므로 음성 알림을 내지 않는다.
        # docs/architecture.md "/delegate, /delegate-all 서브에이전트와의 관계" 참고.
        return 0

    if not is_enabled():
        # /voice-on을 실행한 적 없거나 /voice-off로 끈 상태 — TCP 시도조차
        # 하지 않는다(listener.py가 안 떠 있을 게 뻔한데 매번 타임아웃까지
        # 기다릴 이유가 없다).
        return 0

    socket_path = os.environ.get("CLAUDE_CODE_MESSAGING_SOCKET", "")
    token = os.environ.get("CLAUDE_CODE_MESSAGING_TOKEN", "")
    # session_id는 architecture.md 결정대로 별도로 만들지 않고 소켓 경로 자체를 그대로 쓴다.
    session_id = socket_path

    project_name = Path(cwd_for_check).name

    message = {
        "event": "notify",
        "session_id": session_id,
        "project_name": project_name,
        "text": text,
        "socket_path": socket_path,
        "token": token,
    }

    try:
        with socket.create_connection((HOST, PORT), timeout=CONNECT_TIMEOUT) as sock:
            sock.sendall(json.dumps(message, ensure_ascii=False).encode("utf-8"))
            # 응답은 기다리지 않는다 — 훅은 빠르게 끝나야 한다 (전송만 하고 바로 반환).
    except ConnectionRefusedError:
        # 상주 프로세스(listener.py)가 안 떠 있을 때의 정상 경로. 폴백 없음(확정 사항).
        pass
    except OSError:
        # 타임아웃 등 그 외 소켓 오류도 훅 흐름을 막지 않도록 동일하게 삼킨다.
        pass
    except Exception:
        # 예상 못한 오류까지 전부 삼켜서 훅이 Claude Code를 절대 막지 않게 한다.
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
