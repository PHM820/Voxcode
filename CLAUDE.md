# eyes-free-coding

화면을 안 보고도 Claude Code로 작업할 수 있게, 완료 음성 요약과 음성 명령 입력을 더하는 애드온.
접근성(눈이 안 좋은 사용자)에 국한되지 않는다 — 기본 가치는 "다른 일을 하며 여러 프로젝트를
음성으로 지휘하는 비서"이고, 접근성은 그 일반 기능의 부분집합이다. 자세한 설계: `docs/architecture.md`.

## 먼저 볼 것
- 아키텍처 전체 그림: `docs/architecture.md`
- 기능별 파일 지도: `CLAUDE_MAP.md`
- 검증: `.claude/verify.cmd` (작업 완료 보고 전에 실행)
- 결정 기록: `docs/decisions.md`

## 실행 방법
- (설치 스크립트 확정 후 채움)

## 공통 규칙
- Claude Code 공식 스크린리더 모드·터미널 벨 알림이 이미 하는 일은 다시 만들지 않는다 — 그 위에 훅으로 얹는다.
- TTS는 sherpa-onnx(언어별 모델 교체), STT는 whisper.cpp(pywhispercpp)를 기본으로 한다(실측 검증됨, `docs/decisions.md` 참고).
- 공개 배포 예정 프로젝트이므로 키·개인 경로를 코드에 하드코딩하지 않는다.

## 하지 말 것
- 키·비밀번호를 코드에 넣지 않는다 (.env 사용)
- 테스트를 건너뛰거나 주석 처리해서 통과시키지 않는다
