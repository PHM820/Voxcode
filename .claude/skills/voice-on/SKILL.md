---
name: voice-on
description: 이 프로젝트의 음성모드(완료 음성 요약 + 음성 명령)를 켠다. 상주 리스너(voice/listener.py)가 안 떠 있으면 백그라운드로 띄우고, .claude/voice-settings.json의 enabled를 true로 기록한다.
---

# /voice-on — 음성모드 켜기

목적: 이 세션(관리자 세션)에서 완료 음성 요약과 음성 명령 입력을 받을 수 있게 한다.
자세한 설계 근거: `docs/architecture.md` "설정 파일과 프로세스 생명주기".

## 절차

1. **이미 떠 있는지 확인**: TCP `127.0.0.1:8765`에 연결을 시도한다. 연결되면 이미 떠 있는 것 —
   4번으로 건너뛴다.
2. **안 떠 있으면 백그라운드로 spawn**:
   ```
   .venv\Scripts\python.exe -m voice.listener
   ```
   Windows에서 터미널에 매인 채로 뜨지 않도록 분리해서 실행한다(예:
   `subprocess.Popen([...], creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)`
   또는 동등한 방식). 표준출력은 `.scratch/listener.log` 등으로 리다이렉트해 나중에 확인 가능하게 한다.
3. **기동 확인**: 1~2초 대기 후 다시 TCP 연결을 시도해 실제로 떴는지 확인한다. 안 뜨면
   `.scratch/listener.log`(또는 리다이렉트한 파일)를 읽어 원인을 그대로 사용자에게 보여준다 —
   추측으로 "됐을 것"이라고 보고하지 않는다.
4. **설정 갱신**: `voice/config.py`의 `load_settings()`/`save_settings()`를 사용해
   `.claude/voice-settings.json`의 `enabled`를 `true`로 쓴다. 파일이 없으면 새로 만들어진다
   (기본값 + `enabled: true`).
5. 결과를 한 줄로 보고한다: 새로 띄웠는지 이미 떠 있었는지, `enabled` 값.

## 확인해야 할 것

- 이 프로젝트는 `/delegate`, `/delegate-all`의 하위 작업자(워커, `.claude/worktrees/` 아래
  세션)에는 적용되지 않는다 — 그 세션들은 훅 자체가 조용히 무시하도록 이미 되어 있다
  (`hooks/on-stop.py`, `hooks/on-notification.py`의 `_is_delegate_worker()`). `/voice-on`은
  관리자 세션에서만 의미가 있다.
- `.venv`가 없으면(설치 안 된 상태) "먼저 `setup.cmd`를 실행하세요"로 안내하고 멈춘다 — 없는
  venv로 spawn을 시도하지 않는다.
