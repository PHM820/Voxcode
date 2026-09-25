# CLAUDE_MAP — eyes-free-coding

기능별 파일 지도. 파일이 생기면 이 표를 함께 갱신한다.

## 개요
Claude Code의 공식 스크린리더 모드(`--ax-screen-reader`) 위에 얹는 애드온.
공식 모드가 이미 하는 것(터미널 UI를 평문화, 완료/권한요청 시 벨 소리)은 다시 만들지 않는다.
이 프로젝트가 새로 더하는 것 두 가지만 담당한다:
1. 완료 시 "무슨 일이 있었는지" 짧은 한국어 음성 요약 (TTS)
2. 텍스트 대신 음성으로 명령 입력 (STT)

공식 문서: https://code.claude.com/docs/en/accessibility

## 기능별 파일

| 기능 | 파일 경로 | 상태 |
|---|---|---|
| 완료 훅 (Stop 이벤트 → 요약 → TTS) | `hooks/on-stop.*` | 예정 |
| 권한요청 훅 (Notification 이벤트 → TTS) | `hooks/on-notification.*` | 예정 |
| TTS 엔진 래퍼 (MeloTTS-Korean) | `voice/tts.*` | 예정 |
| STT 엔진 래퍼 (Windows 내장 음성인식) | `voice/stt.*` | 예정 |
| 음성모드 on/off 스킬 (`/voice-on`, `/voice-off`) | `.claude/skills/voice-mode/` | 예정 |
| 설정 (음성 on/off, 벨 병행 여부 등) | `.claude/settings.json` | 예정 |
| 설치 스크립트 | `setup.*` | 예정 |
| 검증 | `.claude/verify.cmd` | 이번 harness에서 생성 |
| 결정 기록 | `docs/decisions.md` | 이번 harness에서 생성 |

## 스택 (확정)
- 훅 실행: Claude Code Hooks (settings.json에 등록, Stop/Notification 이벤트)
- TTS: MeloTTS-Korean (MIT, CPU 동작)
- STT: Windows 내장 음성 인식 (별도 설치 불필요)
- 대상 OS: Windows (1차), macOS/Linux는 추후 고려
