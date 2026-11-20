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

## 지침 회수(강제 해제)가 "자동으로" 완전히 되는지 확인 (2026-09-26)

`enabled: false`로 쓰는 순간 아래 세 지점이 전부 빠짐없이 회수되어야 한다 — 켤 때 넣은 지침·훅
동작이 끌 때 하나라도 남으면 "꺼졌는데 계속 짧게 답한다"는 혼란이 생긴다. 확인된 사실:

1. **`hooks/on-user-prompt-submit.py`** (3중 재주입 우선순위 1): 매 프롬프트마다 실행되지만
   `is_enabled()`가 `false`면 `additionalContext`를 아예 출력하지 않고 exit 0 — **자동 회수됨**,
   추가 조치 불필요(실측 검증 완료, 2026-09-26).
2. **`CLAUDE.md`의 응답 스타일 지침** (3중 재주입 우선순위 2): 이 문단은 **켤 때마다 지웠다 썼다
   하지 않고 항상 파일에 남겨둔다** — 대신 문단 자체에 "`enabled: false`면 이 지침은 무시할 것"이라는
   조건을 명시해 두었다(`CLAUDE.md` "공통 규칙" 참고). `/voice-on`/`/voice-off`는 이 문단을 절대
   건드리지 않는다 — 값(`enabled`)만 바뀌면 지침의 적용 여부가 저절로 갈린다.
3. **`hooks/on-stop.py`, `hooks/on-notification.py`**: 이미 `is_enabled()` 체크로 TCP 시도 자체를
   안 함 — 기존에 검증된 그대로.

**결론**: `/voice-off`가 `enabled: false`만 정확히 쓰면 위 세 지점이 전부 자동으로 회수된다 — 이
스킬이 별도로 CLAUDE.md를 편집하거나 훅 등록을 해제하는 등의 추가 작업을 할 필요는 없다. 단, 이
표는 **"3중 재주입"에 새 지점이 추가될 때마다(예: 우선순위 3의 SessionStart-compact 훅을 나중에
구현하면) 그 지점도 `enabled: false`에서 자동으로 조용해지는지 반드시 같이 확인하고 이 표에
추가할 것** — 새 훅을 만들 때 이 회수 원칙을 빠뜨리기 쉬우므로 체크리스트로 남겨둠.

## 세션 "멈춤" 표시도 별도 회수가 필요 없음 (2026-11-20 갱신)

음성 "멈춰"로 세션에 붙는 `paused` 표시(`SessionTable`)는 `voice/listener.py` 프로세스의
**메모리에만** 기준이 있다 — `~/.voxcode/state.json`에도 스냅숏이 쓰이지만 리스너는 시작할 때
이 파일을 읽어 복원하지 않는다. `/voice-off`가 `shutdown` 이벤트로 프로세스를 끝내면 다음
`/voice-on`은 빈 테이블로 시작하므로 별도 초기화 코드 불필요.
