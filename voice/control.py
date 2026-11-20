# -*- coding: utf-8 -*-
"""음성모드 켜기·끄기·상태 (/voice-on, /voice-off 스킬이 부른다).

    .venv\\Scripts\\python.exe -m voice.control on [--no-manager]
    .venv\\Scripts\\python.exe -m voice.control off
    .venv\\Scripts\\python.exe -m voice.control status

on : 켜짐 표시(~/.voxcode/config.json) → 전역 훅 등록 → 리스너 띄우기(안 떠 있으면) → 하이쿠 관리자 띄우기
off: 켜짐 해제 → 전역 훅 해제 → 리스너에 종료 신호(inbox) → 관리자 창 끄기
결과는 JSON 한 줄로 출력한다. 리스너가 안 뜨면 로그 끝부분을 함께 내보낸다(추측으로 "됐다"고 하지 않게).
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from voice import hooks_install, manager, record
from voice.config import is_enabled, set_enabled

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LISTENER_START_TIMEOUT_S = 60.0  # TTS·STT 모델 로딩 시간 포함
LISTENER_STOP_TIMEOUT_S = 8.0


def listener_log() -> Path:
    return record.home() / "listener.log"


def _alive() -> bool:
    from voice.listener import is_listener_alive
    return is_listener_alive()


def _tail(path: Path, n: int = 20) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
    except OSError:
        return ""


def start_listener() -> dict:
    if _alive():
        return {"listener": "already_running"}
    log = open(listener_log(), "a", encoding="utf-8")
    subprocess.Popen(
        [str(hooks_install.VENV_PY), "-m", "voice.listener"], cwd=str(PROJECT_ROOT),
        stdout=log, stderr=subprocess.STDOUT,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    deadline = time.monotonic() + LISTENER_START_TIMEOUT_S
    while time.monotonic() < deadline:
        if _alive():
            return {"listener": "started"}
        time.sleep(0.5)
    return {"listener": "failed", "log_tail": _tail(listener_log())}


def stop_listener() -> dict:
    if not _alive():
        return {"listener": "not_running"}
    sys.path.insert(0, str(PROJECT_ROOT / "hooks"))
    from _common import write_inbox
    write_inbox({"event": "shutdown", "ts": time.time()})
    deadline = time.monotonic() + LISTENER_STOP_TIMEOUT_S
    while time.monotonic() < deadline:
        if not _alive():
            return {"listener": "stopped"}
        time.sleep(0.3)
    return {"listener": "stop_timeout", "log_tail": _tail(listener_log())}


def on(with_manager: bool = True) -> dict:
    if not hooks_install.VENV_PY.exists():
        return {"ok": False, "error": "가상환경 없음 — 먼저 setup.cmd를 실행하세요"}
    set_enabled(True)
    hooks_install.install()
    result = {"ok": True, "enabled": True, "hooks": "installed", **start_listener()}
    if with_manager:
        result["manager"] = "already_running" if manager.is_running() else f"started pid={manager.launch()}"
    result["ok"] = result["listener"] != "failed"
    return result


def off() -> dict:
    set_enabled(False)  # 먼저 꺼 두면 아래가 실패해도 훅은 아무것도 안 남긴다
    removed = hooks_install.uninstall()
    result = {"ok": True, "enabled": False, "hooks": "removed" if removed else "not_installed",
              **stop_listener(), "manager": "stopped" if manager.stop() else "not_running"}
    result["ok"] = result["listener"] != "stop_timeout"
    return result


def status() -> dict:
    return {"enabled": is_enabled(), "hooks_installed": hooks_install.is_installed(),
            "listener_alive": _alive(), "manager_running": manager.is_running(),
            "manager_registered": manager.load_session() is not None}


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "status"
    if cmd == "on":
        result = on(with_manager="--no-manager" not in argv)
    elif cmd == "off":
        result = off()
    elif cmd == "status":
        result = status()
    else:
        result = {"ok": False, "error": f"알 수 없는 명령: {cmd} (on|off|status)"}
    sys.stdout.buffer.write((json.dumps(result, ensure_ascii=False) + "\n").encode("utf-8"))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
