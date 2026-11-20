---
name: voice-off
description: 음성모드를 끈다. voice/control.py off 한 줄로 전역 훅 해제, 리스너 종료 신호, 서브 관리자 창 끄기를 한다.
---

# /voice-off — 음성모드 끄기

## 절차

1. 아래 한 줄을 실행한다(프로젝트 루트에서). 결과는 JSON 한 줄이다.
   ```
   .venv\Scripts\python.exe -m voice.control off
   ```
   차례로: 켜짐 해제(먼저 — 아래가 실패해도 훅은 아무것도 안 남긴다) → 전역 `~/.claude/settings.json`에서
   Voxcode 훅만 제거(다른 훅은 그대로) → 리스너에 종료 신호(`~/.voxcode/inbox/`) → 서브 관리자 창 끄기.
2. 결과를 한 줄로 보고한다. `listener`가 `stop_timeout`이면 `log_tail`을 보여 준다.

## 지침 회수(강제 해제)가 "자동으로" 완전히 되는지 확인 (2026-09-26, 2026-11-20 갱신)

2026-11-20부터 켜짐 표시는 전역(`~/.voxcode/config.json`)이고, 훅 자체도 끌 때 전역 설정에서 해제된다 —
아래 1·3은 해제 실패에 대비한 2중 안전장치가 됐다.

`enabled: false`로 쓰는 순간 아래 세 지점이 전부 빠짐없이 회수되어야 한다 — 켤 때 넣은 지침·훅
동작이 끌 때 하나라도 남으면 "꺼졌는데 계속 짧게 답한다"는 혼란이 생긴다. 확인된 사실:

1. **`hooks/on-user-prompt-submit.py`** (3중 재주입 우선순위 1): 매 프롬프트마다 실행되지만
   `is_enabled()`가 `false`면 `additionalContext`를 아예 출력하지 않고 exit 0 — **자동 회수됨**,
   추가 조치 불필요(실측 검증 완료, 2026-09-26).
2. **`CLAUDE.md`의 응답 스타일 지침** (3중 재주입 우선순위 2): 이 문단은 **켤 때마다 지웠다 썼다
   하지 않고 항상 파일에 남겨둔다** — 대신 문단 자체에 "`enabled: false`면 이 지침은 무시할 것"이라는
   조건을 명시해 두었다(`CLAUDE.md` "공통 규칙" 참고). `/voice-on`/`/voice-off`는 이 문단을 절대
   건드리지 않는다 — 값(`enabled`)만 바뀌면 지침의 적용 여부가 저절로 갈린다.
3. **`hooks/on-stop.py`, `hooks/on-notification.py`**: 이미 `is_enabled()` 체크로 inbox 파일을
   쓰지 않음 — `.claude/verify_hooks.py`가 확인.

**결론**: `/voice-off`가 `enabled: false`만 정확히 쓰면 위 세 지점이 전부 자동으로 회수된다 — 이
스킬이 별도로 CLAUDE.md를 편집할 필요는 없다(훅 해제는 `voice.control off`가 함께 한다). 단, 이
표는 **"3중 재주입"에 새 지점이 추가될 때마다(예: 우선순위 3의 SessionStart-compact 훅을 나중에
구현하면) 그 지점도 `enabled: false`에서 자동으로 조용해지는지 반드시 같이 확인하고 이 표에
추가할 것** — 새 훅을 만들 때 이 회수 원칙을 빠뜨리기 쉬우므로 체크리스트로 남겨둠.

## 세션 "멈춤" 표시도 별도 회수가 필요 없음 (2026-11-20 갱신)

음성 "멈춰"로 세션에 붙는 `paused` 표시(`SessionTable`)는 `voice/listener.py` 프로세스의
**메모리에만** 기준이 있다 — `~/.voxcode/state.json`에도 스냅숏이 쓰이지만 리스너는 시작할 때
이 파일을 읽어 복원하지 않는다. `/voice-off`가 `shutdown` 이벤트로 프로세스를 끝내면 다음
`/voice-on`은 빈 테이블로 시작하므로 별도 초기화 코드 불필요.
