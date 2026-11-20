# -*- coding: utf-8 -*-
"""verify.cmd에서 호출하는 4단계(듣기 파일화·전역 훅 등록·켜고 끄기) 자가 점검.

실제 ~/.claude/settings.json, 실제 리스너·관리자 실행은 건드리지 않는다:
VOXCODE_HOME과 VOXCODE_CLAUDE_SETTINGS를 임시 폴더로 돌린다. 실패하면 0이 아닌 코드로 종료한다.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

HOME = Path(tempfile.mkdtemp(prefix="voxcode-verify-ctl-"))
SETTINGS = HOME / "claude-settings.json"
os.environ["VOXCODE_HOME"] = str(HOME)
os.environ["VOXCODE_CLAUDE_SETTINGS"] = str(SETTINGS)
SKILLS_DIR = HOME / "skills"
os.environ["VOXCODE_CLAUDE_SKILLS"] = str(SKILLS_DIR)
sys.path.insert(0, ".")

from voice import config, control, hooks_install, listener  # noqa: E402

assert hooks_install.settings_path() == SETTINGS, "테스트가 실제 전역 설정을 가리킴"

# --- 1. 전역 켜짐 표시 ---
assert config.is_enabled() is False, "파일 없으면 꺼짐"
config.set_enabled(True)
assert config.is_enabled() is True
(HOME / "config.json").write_text("{broken", encoding="utf-8")
assert config.is_enabled() is False, "깨진 파일은 꺼짐"

# --- 2. 전역 훅 등록·해제: 사용자의 다른 훅·설정은 그대로 ---
original = {
    "model": "opus",
    "hooks": {
        "Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "python my-own-check.py"}]}],
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "guard.cmd"}]}],
    },
}
SETTINGS.write_text(json.dumps(original), encoding="utf-8")
hooks_install.install()
hooks_install.install()  # 두 번 등록해도 중복 없음
data = json.loads(SETTINGS.read_text(encoding="utf-8"))
for event, script in hooks_install.EVENTS.items():
    ours = [h["command"] for g in data["hooks"][event] for h in g["hooks"] if script in h["command"]]
    assert len(ours) == 1, (event, ours)
    assert ours[0].startswith('"') and ours[0].count('"') == 4, f"공백 경로 따옴표 없음: {ours[0]}"
assert data["hooks"]["Stop"][0]["hooks"][0]["command"] == "python my-own-check.py", "사용자 Stop 훅이 바뀜"
assert data["hooks"]["PreToolUse"] == original["hooks"]["PreToolUse"] and data["model"] == "opus"
assert hooks_install.is_installed()
assert (HOME / "claude-settings.json.voxcode.bak").exists(), "백업 없음"
assert hooks_install.uninstall() is True
assert json.loads(SETTINGS.read_text(encoding="utf-8")) == original, "해제 후 원래 설정과 다름"
before = SETTINGS.read_bytes()
assert hooks_install.uninstall() is False and SETTINGS.read_bytes() == before, "등록 안 됐는데 파일을 다시 씀"

# 사용자가 우리 훅과 자기 훅을 한 묶음에 섞어 둔 경우: 해제하면 자기 훅만 남는다
ours = hooks_install._command("on-stop.py")
mixed = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "mine.cmd"},
                                       {"type": "command", "command": ours}]}]}}
SETTINGS.write_text(json.dumps(mixed), encoding="utf-8")
assert hooks_install.uninstall() is True
assert json.loads(SETTINGS.read_text(encoding="utf-8")) == {
    "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "mine.cmd"}]}]}}, "섞인 묶음에서 사용자 훅까지 지움"

# 설정 파일이 깨져 있으면 아무것도 쓰지 않는다
SETTINGS.write_text('{"hooks": {', encoding="utf-8")
try:
    hooks_install.install()
    raise AssertionError("깨진 설정에 훅을 씀")
except ValueError:
    pass
assert SETTINGS.read_text(encoding="utf-8") == '{"hooks": {', "깨진 설정 파일이 바뀜"

# 설정 파일이 없으면 새로 만들고, 해제하면 hooks 키까지 지운다
SETTINGS.unlink()
hooks_install.install()
hooks_install.uninstall()
assert json.loads(SETTINGS.read_text(encoding="utf-8")) == {}


# --- 3. inbox 처리: 정상·깨진 파일·쓰는 중 파일·오래된 알림·오래된 종료 신호 ---
class FakeTts:
    def __init__(self):
        self.items = []
        self.ctx = listener.ListenerContext()

    def enqueue(self, project, summary):
        self.items.append((project, summary))


inbox = HOME / "inbox"
inbox.mkdir(exist_ok=True)
started = time.time()
table, tts = listener.SessionTable(), FakeTts()
w = listener.InboxWatcher(table, tts, started_at=started, classify=lambda text: None)


def drop(name, content):
    (inbox / name).write_text(content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
                              encoding="utf-8")


note = {"event": "notify", "kind": "stop", "session_id": "s1", "socket_path": "s1", "token": "t",
        "project_name": "proj-a", "text": "끝났어요", "ts": started}
drop("1.json", note)
drop("2.json", "{깨짐")
drop("3.json", "[1, 2]")
drop("4.json", {**note, "event": "detach"})
drop("5.tmp", note)  # 쓰는 중 — 읽지 않음
drop("6.json", {**note, "session_id": "s-old", "project_name": "proj-old", "ts": started - 600})
drop("7.json", {"event": "shutdown", "ts": started - 5})  # 리스너가 켜지기 전 신호
assert w.process_once() is False, "켜지기 전 종료 신호로 꺼짐"
assert tts.items == [("proj-a", "끝났어요")], tts.items
assert table.get("s-old") is not None, "오래된 알림의 세션이 등록 안 됨"
assert table.get("s-old").last_notify_at == started - 600, "오래된 알림이 방금 온 알림처럼 기록됨"
assert listener.route_command(table).project_name == "proj-a", "꺼져 있던 동안의 세션이 기본 대상이 됨"
assert sorted(p.name for p in (inbox / "bad").iterdir()) == ["2.json", "3.json", "4.json"]
assert sorted(p.name for p in inbox.iterdir() if p.is_file()) == ["5.tmp"], "처리한 파일이 남음"
assert w.process_once() is False, "깨진 파일을 다시 읽음"
drop("8.json", {"event": "shutdown", "ts": time.time()})
assert w.process_once() is True, "종료 신호를 못 받음"

# 살아 있음 표시
assert listener.is_listener_alive()
os.utime(listener.alive_file(), (time.time() - 60, time.time() - 60))
assert not listener.is_listener_alive(), "오래된 alive 파일을 살아 있다고 봄"

# --- 4. 끄기: 켜짐 해제 + 훅 해제 (리스너·관리자는 없음) ---
config.set_enabled(True)
hooks_install.install()
r = control.off()
assert r["ok"] and r["enabled"] is False and r["hooks"] == "removed", r
assert r["listener"] == "not_running" and r["manager"] == "not_running", r
assert not config.is_enabled() and not hooks_install.is_installed()
s = control.status()
assert set(s) == {"enabled", "hooks_installed", "listener_alive", "manager_running", "manager_registered"}, s

# --- 5. 전역 스킬 연결: 설치 폴더 경로가 들어감, 남의 같은 이름 스킬은 안 건드림 ---
from voice import skills_install  # noqa: E402

assert skills_install.skills_dir() == SKILLS_DIR, "테스트가 실제 전역 스킬 폴더를 가리킴"
foreign = SKILLS_DIR / "voice-off" / "SKILL.md"
foreign.parent.mkdir(parents=True)
foreign.write_text("---\nname: voice-off\n---\n내 스킬", encoding="utf-8")
assert skills_install.install() == {"voice-on": "installed", "voice-off": "skipped_foreign"}
on_md = (SKILLS_DIR / "voice-on" / "SKILL.md").read_text(encoding="utf-8")
src = Path(".claude/skills/voice-on/SKILL.md").resolve()
assert str(src) in on_md and src.exists(), "전역 스킬이 실제 절차 파일을 가리키지 않음"
assert on_md.startswith("---\nname: voice-on\n"), "스킬 머리말 형식이 깨짐"
assert skills_install.install()["voice-on"] == "installed", "두 번째 설치가 우리 파일을 남의 것으로 봄"
assert skills_install.uninstall() == {"voice-on": "removed", "voice-off": "skipped_foreign"}
assert not (SKILLS_DIR / "voice-on").exists(), "해제 후 폴더가 남음"
assert foreign.read_text(encoding="utf-8").endswith("내 스킬"), "남의 스킬이 바뀜"
assert skills_install.uninstall()["voice-on"] == "not_installed"

# --- 6. Supertonic 모델 폴더 찾기: 기본 위치 / .path로 가리킨 다른 폴더(assets/ 아래 구조) / 없음 ---
from voice import languages, tts  # noqa: E402

for v in (v for lang in languages.LANGUAGES for v in lang.voices):
    assert f"voice_styles/{v.style}.json" in languages.SUPERTONIC_FILES, f"받지 않는 목소리 스타일: {v.id}"
assert languages.find_language("zh") is None and "zh" in languages.UNSUPPORTED_TTS_NOTE, "중국어 처리 바뀜"


def fake_model(base: Path, helper_at: Path):
    (base / "onnx").mkdir(parents=True)
    (base / "onnx" / "tts.json").write_text("{}", encoding="utf-8")
    (base / "voice_styles").mkdir()
    helper_at.mkdir(parents=True, exist_ok=True)
    (helper_at / "helper.py").write_text("", encoding="utf-8")


MROOT = HOME / "models-tts"
MROOT.mkdir()
assert tts.supertonic_dir(MROOT) is None, "모델이 없는데 찾았다고 함"
elsewhere = HOME / "다른 폴더" / "supertonic3"
fake_model(elsewhere / "assets", elsewhere)
(MROOT / "supertonic3.path").write_text(f'"{elsewhere}"\n', encoding="utf-8")
assert tts.supertonic_dir(MROOT) == elsewhere / "assets", ".path로 가리킨 폴더를 못 찾음"
fake_model(MROOT / "supertonic3", MROOT / "supertonic3")
assert tts.supertonic_dir(MROOT) == MROOT / "supertonic3", "기본 위치보다 .path를 먼저 씀"
(MROOT / "supertonic3" / "helper.py").unlink()
assert tts.supertonic_dir(MROOT) == elsewhere / "assets", "helper.py 없는 기본 폴더를 씀"

print("control checks OK")
