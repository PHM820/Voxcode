# Voxcode (구 eyes-free-coding)

화면을 안 보고도 Claude Code로 작업할 수 있게, 완료 음성 요약과 음성 명령 입력을 더하는 애드온.
접근성(눈이 안 좋은 사용자)에 국한되지 않는다 — 기본 가치는 "다른 일을 하며 여러 프로젝트를
음성으로 지휘하는 비서"이고, 접근성은 그 일반 기능의 부분집합이다. 자세한 설계: `docs/architecture.md`.
GitHub: https://github.com/PHM820/Voxcode (비공개)

## 먼저 볼 것
- 아키텍처 전체 그림: `docs/architecture.md`
- 기능별 파일 지도: `CLAUDE_MAP.md`
- 검증: `.claude/verify.cmd` (작업 완료 보고 전에 실행)
- 결정 기록: `docs/decisions.md`

## 실행 방법
- 설치: `setup.cmd` (venv 생성 + 의존성 설치 + TTS/STT 모델 다운로드)
- 음성모드 켜기/끄기: `/voice-on`, `/voice-off` 스킬

## 공통 규칙
- Claude Code 공식 스크린리더 모드·터미널 벨 알림이 이미 하는 일은 다시 만들지 않는다 — 그 위에 훅으로 얹는다.
- TTS는 sherpa-onnx(언어별 모델 교체), STT는 whisper.cpp(pywhispercpp)를 기본으로 한다(실측 검증됨, `docs/decisions.md` 참고).
- 공개 배포 예정 프로젝트이므로 키·개인 경로를 코드에 하드코딩하지 않는다.
- **음성모드가 켜진 이 프로젝트에서 응답할 때(`.claude/voice-settings.json`의 `enabled: true`)만
  적용, `enabled: false`(기본값)면 아래 지침은 무시할 것 — 켤 때마다 이 문단을 지웠다 썼다 하지
  않고 항상 두되 값으로만 켜고 끈다**:
  이 응답의 끝(`last_assistant_message`)은 상주 리스너가 그대로 TTS로 읽는다(`hooks/on-stop.py`).
  코드블록·파일 경로 나열 없이 **응답 끝을 1~2문장의 짧고 자연스러운 한국어 요약으로 맺을 것**
  — 별도 요약 태그를 만들지 않고 응답 원문을 그대로 쓰는 설계이므로, 이 스타일 자체가 음성 요약의
  품질이다. (같은 지침이 `hooks/on-user-prompt-submit.py`로 매 프롬프트마다도 재주입되지만, 이것도
  `enabled: false`면 훅이 아무것도 출력하지 않는다 — `docs/architecture.md` "음성모드 응답 스타일
  강제 — 3중 재주입 설계" 참고, 이건 그중 CLAUDE.md 몫)

## 하지 말 것
- 키·비밀번호를 코드에 넣지 않는다 (.env 사용)
- 테스트를 건너뛰거나 주석 처리해서 통과시키지 않는다
