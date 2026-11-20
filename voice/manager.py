# -*- coding: utf-8 -*-
"""서브 관리자: 계속 켜 둔 Haiku Claude Code 세션 하나 (docs/architecture.md "서브 관리자").

판단 3단계의 마지막 단계. Jev가 애매하다고 한 문장의 판단과, Jev가 못 하는 글 만들기
(밀린 기록 요약, 여러 프로젝트 상황 묶기)를 맡는다.

주고받기 (모두 ~/.voxcode/manager/ 안 — 관리자 세션의 작업 폴더라 권한 확인 없이 읽고 쓴다):
  1. 리스너가 questions/<id>.json을 쓰고, 관리자 세션에 "[Voxcode 질문 <id>]" 메시지를 주입
  2. 관리자가 answers/<id>.json에 JSON 하나를 씀
  3. 리스너가 그 파일을 ASK_TIMEOUT_S까지 기다림 — 넘거나 관리자가 없으면 None(호출부가 규칙으로)

관리자 세션의 소켓·토큰은 그 세션의 Stop 훅이 session.json에 등록한다(hooks/_common.py).
이 모듈은 마이크 스레드에서 불리므로 ask()는 예외를 밖으로 내보내지 않는다.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

from voice import record

ASK_TIMEOUT_S = 20.0
POLL_S = 0.2
# CLI 별칭 — 정확한 모델 ID를 박아 두면 새 Haiku가 나와도 옛 모델에 묶인다
MANAGER_MODEL = "haiku"
FIRST_PROMPT = "CLAUDE.md를 읽고, 질문 메시지가 올 때까지 대기해. 지금은 '대기'라고만 답해."

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INJECT_JS = PROJECT_ROOT / "voice" / "inject.js"

CLAUDE_MD = """# Voxcode 음성 명령 중재자

너는 음성 비서(Voxcode 리스너)를 돕는 중재자다. 사람은 이 창을 보지 않는다.

## 할 일
- `[Voxcode 질문 <id>]` 메시지가 오면 `questions/<id>.json`을 읽고, 답을 `answers/<id>.json`에
  **JSON 하나만** 써라(Write 도구). 다른 설명은 쓰지 말고 응답 텍스트는 "완료" 한 단어.
- 질문 `type`이 `judge`면:
  `{"command": "<commands 중 하나>", "target": "<sessions의 project 그대로 | all | listener | unknown>", "ask_back": "<모르겠으면 사용자에게 되물을 짧은 한국어 문장, 알면 빈 문자열>", "meaning": "<사용자가 하려는 말을 받아쓰기 오류까지 고려해 풀어쓴 한국어 한 문장>"}`
  - `meaning`은 원문과 함께 그 세션에 참고용으로 전달된다. 받아쓰기가 틀린 단어는 바로잡아 써라
    (예: "박스코드" → "Voxcode", "영상 모드" → 아마 "음성 모드"). 확실하지 않은 부분은 "아마"라고 써라.
  - `commands`는 {명령: 설명}이다. 설명을 따라 골라라.
  - 사용자는 한국어로 말하고 프로젝트 이름은 영어 폴더명이다. 뜻·발음·요약·최근 기록으로 연결하라.
  - `noise`는 사람이 비서나 프로젝트에게 한 말이 아닐 때만(TV·다른 사람 말·음성인식이 지어낸 문장).
    사용자의 감상·피드백·혼잣말 같은 지시("잘 되네", "이거 너무 쉽게 버리는 것 같아")는 noise가 아니라 instruct.
  - `target: listener`는 list·repeat·quiet·verbose·status·catch_up처럼 비서가 직접 답하는 명령에만 쓴다.
    음성 비서(Voxcode) 자체에 대한 의견·고칠 점은 sessions 중 그 비서를 만드는 프로젝트(이름·요약에
    Voxcode·음성·호출어·리스너)로 보내라. 그런 프로젝트가 없으면 unknown + ask_back.
  - 확신이 없으면 추측하지 말고 ask_back에 "번개장터요, 축구요?"처럼 고를 수 있게 물어라.
- `type`이 `reroute`면: 앞서 보낸 음성 지시를 `rejected_by` 프로젝트가 "자기 일이 아니다"(`reason`)라고
  돌려보낸 것이다. `sessions`(거절한 곳은 빠져 있음) 중 맞는 곳을 judge와 같은 JSON으로 골라라.
  맞는 곳이 없으면 target을 unknown으로 하고 ask_back에 어느 프로젝트인지 물어라.
- `type`이 `summarize`면: `{"say": "<instruction대로 쓴 한두 문장 한국어>"}` — 귀로 듣는 문장이니
  기호·경로·목록 없이 짧게.

## 하지 말 것
- 이 폴더 밖 파일을 읽거나 고치지 않는다. 코드를 고치지 않는다. 명령을 실행하지 않는다.
- 사용자 전역 지침의 작업 절차는 이 폴더에 적용하지 않는다: 하네스 자동 적용(git init, CLAUDE_MAP.md,
  verify.cmd 만들기), /phm-delegate 제안, advisor 호출, 완료 전 검증 보고, 밤모드·알림 모드 등.
  이 세션은 코딩 세션이 아니라 판단기다.
"""

SETTINGS = {
    "permissions": {
        "allow": ["Read(./questions/**)", "Write(./answers/**)", "Edit(./answers/**)"],
    }
}

SendFn = Callable[[str, str, str], bool]  # (socket_path, token, text) -> 성공 여부


def manager_dir() -> Path:
    return record.home() / "manager"


def is_manager_cwd(cwd: str) -> bool:
    try:
        return Path(cwd).resolve() == manager_dir().resolve()
    except Exception:  # noqa: BLE001
        return False


def prepare() -> Path:
    """관리자 폴더·역할 문서·권한 설정을 만든다(매번 덮어써 최신 상태로)."""
    d = manager_dir()
    for sub in ("questions", "answers", ".claude"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    (d / "CLAUDE.md").write_text(CLAUDE_MD, encoding="utf-8")
    (d / ".claude" / "settings.json").write_text(
        json.dumps(SETTINGS, ensure_ascii=False, indent=2), encoding="utf-8")
    return d


def register(socket_path: str, token: str) -> None:
    """관리자 세션의 Stop 훅이 부른다: 주입에 쓸 소켓·토큰을 session.json에."""
    d = manager_dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "session.json.tmp"
    tmp.write_text(json.dumps({"socket_path": socket_path, "token": token, "ts": time.time()}),
                   encoding="utf-8")
    os.replace(tmp, d / "session.json")


def load_session() -> Optional[dict]:
    try:
        data = json.loads((manager_dir() / "session.json").read_text(encoding="utf-8"))
        return data if data.get("socket_path") and data.get("token") else None
    except Exception:  # noqa: BLE001
        return None


def _inject(socket_path: str, token: str, text: str) -> bool:
    env = {**os.environ, "CLAUDE_CODE_MESSAGING_SOCKET": socket_path,
           "CLAUDE_CODE_MESSAGING_TOKEN": token}
    proc = subprocess.run(["node", str(INJECT_JS), text], env=env, capture_output=True,
                          encoding="utf-8", errors="replace", timeout=10)
    return proc.returncode == 0


def ask(question: dict, timeout: float = ASK_TIMEOUT_S, send: Optional[SendFn] = None) -> Optional[dict]:
    """관리자에게 묻고 답(dict)을 받는다. 관리자 없음·전달 실패·시간 초과·형식 오류면 None."""
    qid = uuid.uuid4().hex[:12]
    d = manager_dir()
    qfile, afile = d / "questions" / f"{qid}.json", d / "answers" / f"{qid}.json"
    try:
        sess = load_session()
        if sess is None:
            return None
        qfile.parent.mkdir(parents=True, exist_ok=True)
        afile.parent.mkdir(parents=True, exist_ok=True)
        qfile.write_text(json.dumps({"id": qid, **question}, ensure_ascii=False, indent=1),
                         encoding="utf-8")
        message = f"[Voxcode 질문 {qid}] questions/{qid}.json을 읽고 answers/{qid}.json에 답을 써라."
        if not (send or _inject)(sess["socket_path"], sess["token"], message):
            record.log_event("manager", id=qid, result="send_failed")
            return None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if afile.exists():
                try:
                    answer = json.loads(afile.read_text(encoding="utf-8"))
                except ValueError:
                    time.sleep(POLL_S)  # 쓰는 도중일 수 있다 — 한 번 더 기다림
                    continue
                if isinstance(answer, dict):
                    record.log_event("manager", id=qid, result="answered", answer=answer)
                    return answer
                break
            time.sleep(POLL_S)
        record.log_event("manager", id=qid, result="timeout")
        return None
    except Exception as e:  # noqa: BLE001
        record.log_event("manager", id=qid, result="error", error=str(e))
        return None
    finally:
        for f in (qfile, afile):
            try:
                f.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# 띄우기·끄기 (voice/control.py가 /voice-on, /voice-off에서 부른다)
# ---------------------------------------------------------------------------

def launch() -> int:
    """새 PowerShell 창(최소화)에서 Haiku 관리자 세션을 띄우고 PowerShell PID를 기록한다. 사용량이 드는 실행.

    cmd는 학교·회사 정책으로 막힌 컴퓨터가 있어 PowerShell을 쓴다. 프롬프트는 따옴표 문제를 피하려고
    환경변수로 넘긴다. 창은 최소화 상태로, 작업 표시줄에서 열어 볼 수 있다.
    """
    d = prepare()
    env = dict(os.environ, VOX_MODEL=MANAGER_MODEL, VOX_PROMPT=FIRST_PROMPT)
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 7  # SW_SHOWMINNOACTIVE: 최소화, 포커스 안 뺏음
    proc = subprocess.Popen(
        ["powershell", "-NoLogo", "-NoExit", "-ExecutionPolicy", "Bypass", "-Command",
         "& claude --model $env:VOX_MODEL --permission-mode acceptEdits $env:VOX_PROMPT"],
        cwd=str(d), env=env, creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=si,
    )
    (d / "pid").write_text(str(proc.pid), encoding="utf-8")
    return proc.pid


def is_running() -> bool:
    pid = _read_pid()
    return pid is not None and _is_shell_process(pid)


def stop() -> bool:
    """띄운 관리자 창(셸과 그 아래 claude)을 끈다. 끈 게 있으면 True."""
    d = manager_dir()
    pid = _read_pid()
    stopped = False
    if pid is not None and _is_shell_process(pid):
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        stopped = True
    for name in ("pid", "session.json"):
        try:
            (d / name).unlink()
        except OSError:
            pass
    return stopped


def _read_pid() -> Optional[int]:
    try:
        return int((manager_dir() / "pid").read_text(encoding="utf-8").strip())
    except Exception:  # noqa: BLE001
        return None


def _is_shell_process(pid: int) -> bool:
    """PID가 다른 프로그램에 재사용됐으면 끄지 않도록 이름까지 확인."""
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                         capture_output=True, encoding="utf-8", errors="replace").stdout
    return any(n in out.lower() for n in ('"powershell.exe"', '"cmd.exe"'))   # 예전에 cmd로 띄운 관리자도 끈다
