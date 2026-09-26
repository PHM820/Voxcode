---
name: voice-attach
description: /voice-detach로 음성 라우팅 후보에서 빠졌던 이 세션을 스스로 다시 복귀시킨다. 대기(ScheduleWakeup 등) 후 다시 음성 명령을 받고 싶을 때 이 세션 자신이 호출한다.
---

# /voice-attach — 이 세션을 음성 라우팅 후보로 복귀시킨다

목적: `docs/architecture.md` "'멈춰' 이후 재라우팅 문제와 A안" 절 참고. `/voice-detach`로 빠진
세션이, 아직 완료 알림(notify)을 내기 전인데도 스스로 판단해 다시 라우팅 후보로 돌아오고 싶을
때 쓴다.

## 언제 호출하는가

- 이 세션이 `ScheduleWakeup` 등으로 스스로 대기했다가 깨어나, 사용자가 다시 이 프로젝트에
  음성으로 말을 걸 수 있는 상태로 돌아가고 싶을 때.
- **대부분의 경우는 이 스킬을 직접 부를 필요가 없다** — detach된 세션이 실제로 새 작업을
  완료해 평소처럼 완료 알림(`notify`)을 내면 `voice/listener.py`가 자동으로 `active=True`로
  되돌린다. `/voice-attach`는 "아직 아무 작업도 안 했지만 다시 라우팅 대상이 되고 싶다"는,
  그보다 드문 경우를 위한 것.

## 절차

1. **음성모드가 꺼져 있으면 아무것도 하지 않는다**: `voice/config.py`의 `is_enabled()`가
   `False`면 조용히 종료.
2. **TCP로 attach 이벤트 전송**: `127.0.0.1:8765`에 연결해 아래 JSON을 한 번의 `sendall()`로
   전송:
   ```json
   {
     "event": "attach",
     "session_id": "<CLAUDE_CODE_MESSAGING_SOCKET>",
     "project_name": "<cwd 폴더명>",
     "socket_path": "<CLAUDE_CODE_MESSAGING_SOCKET>",
     "token": "<CLAUDE_CODE_MESSAGING_TOKEN>"
   }
   ```
   `notify` 이벤트와 같은 필드가 필요하다 — `voice/listener.py`의 `mark_attached()`가
   `upsert_from_notify()`를 그대로 재사용하기 때문(처음 attach하는 세션이라도 이 정보만으로
   테이블에 새로 등록될 수 있음).
3. 연결이 안 되면 이미 꺼져 있는 것으로 보고 그냥 넘어간다 — 에러로 취급하지 않는다.
4. 결과를 짧게 응답에 반영한다.

## 주의

- 프로젝트명을 사용자가 음성으로 직접 부르는 것(라우팅 규칙 ①)만으로도 `active`가 즉시
  재활성화되므로, 실사용에서는 이 스킬을 쓸 일이 A안 설계 중 가장 드물 것으로 예상된다.
