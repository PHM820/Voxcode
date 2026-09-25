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
| STT 엔진 래퍼 (whisper.cpp) | `voice/stt.*` | 예정 |
| VAD (발화 감지, 바지-인용) | `voice/vad.*` | 예정 |
| 호출어 감지 ("자비스", local-wake) | `voice/wakeword.*` | 예정 |
| 상주 리스너 프로세스 (VAD+wakeword+STT 오케스트레이션) | `voice/listener.*` | 예정 |
| 음성모드 on/off 스킬 (`/voice-on`, `/voice-off`) | `.claude/skills/voice-mode/` | 예정 |
| 설정 (음성 on/off, 벨 병행 여부 등) | `.claude/settings.json` | 예정 |
| 설치 스크립트 (모델 다운로드, 호출어 온보딩 녹음 포함) | `setup.*` | 예정 |
| 검증 | `.claude/verify.cmd` | 이번 harness에서 생성 |
| 결정 기록 | `docs/decisions.md` | 이번 harness에서 생성 |
| 설치 중 겪은 문제·해결 기록 (setup 스크립트 자동화 대상 목록) | `docs/known-issues.md` | 2026-09-25 실측 세션에서 생성. eunjeon 컴파일 문제는 미해결 |

## 스택 (확정)
- 훅 실행: Claude Code Hooks (settings.json에 등록, Stop/Notification 이벤트)
- TTS: MeloTTS-Korean (MIT, CPU 동작)
- STT: whisper.cpp (base/small 모델, CPU 전용)
- VAD: Silero VAD (MIT, 바지-인 감지용)
- 호출어: local-wake (학습 없이 본인 목소리 녹음만으로 온보딩)
- 대상 OS: Windows (1차), macOS/Linux는 추후 고려
