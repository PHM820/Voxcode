---
name: voice-off
description: 이 프로젝트의 음성모드를 끈다. 상주 리스너(voice/listener.py)에 종료 신호를 보내고, .claude/voice-settings.json의 enabled를 false로 기록한다.
---

# /voice-off — 음성모드 끄기

## 절차

1. **설정 갱신 먼저**: `voice/config.py`의 `save_settings()`로 `.claude/voice-settings.json`의
   `enabled`를 `false`로 쓴다. 이걸 먼저 해두면, 아래 종료 신호가 실패하더라도 이후 훅이
   `is_enabled()` 체크에서 걸려 더 이상 TCP를 시도하지 않는다(안전한 순서).
2. **상주 프로세스에 종료 신호**: TCP `127.0.0.1:8765`에 연결해
   `{"event": "shutdown", "session_id": "voice-off"}` (JSON, UTF-8, 한 번의 write로) 전송한다.
   `session_id`/`socket_path`/`token` 등은 `voice/listener.py`의 `shutdown` 이벤트 처리에서
   검사하지 않으므로 최소 필드만 보내면 된다.
3. 연결이 안 되면(`ConnectionRefusedError`/타임아웃) 이미 꺼져 있는 것으로 보고 그냥 넘어간다 —
   에러로 취급하지 않는다.
4. 결과를 한 줄로 보고한다: 종료 신호가 실제로 전달됐는지, 이미 꺼져 있었는지.

## 주의

- known-issues.md 7번(소켓 write는 반드시 한 번에 합쳐서)과 동일한 원칙 — JSON을 한 번의
  `sendall()`로 보낸다.
