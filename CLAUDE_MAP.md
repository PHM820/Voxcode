# CLAUDE_MAP — eyes-free-coding

기능별 파일 지도. 파일이 생기면 이 표를 함께 갱신한다.

## 개요
Claude Code의 공식 스크린리더 모드(`--ax-screen-reader`)·터미널 벨 위에 얹는 애드온.
공식 기능이 이미 하는 것(터미널 UI 평문화, 완료/권한요청 시 벨 소리)은 다시 만들지 않는다.
이 프로젝트가 새로 더하는 것 두 가지만 담당한다:
1. 완료 시 "무슨 일이 있었는지" 짧은 한국어 음성 요약 (TTS)
2. 텍스트 대신 음성으로 명령 입력 (STT)

**대상은 접근성(눈이 안 좋은 사용자)에 국한되지 않는다** — 기본 가치는 "여러 프로젝트를 화면 없이
음성으로 동시에 지휘하는 비서"이고, 접근성은 그 부분집합이다(2026-09-26 재정의). 상주 프로세스
하나가 여러 Claude Code 세션(프로젝트)의 완료 알림을 순차 안내하고, 음성 명령을 올바른 세션으로
라우팅하는 다중 세션 확장을 지향한다. 전체 그림: `docs/architecture.md`.

공식 문서: https://code.claude.com/docs/en/accessibility

## 기능별 파일

| 기능 | 파일 경로 | 상태 |
|---|---|---|
| 완료 훅 (Stop 이벤트 → 요약 → TTS) | `hooks/on-stop.*` | 예정 |
| 권한요청 훅 (Notification 이벤트 → TTS) | `hooks/on-notification.*` | 예정 |
| TTS 엔진 래퍼 (sherpa-onnx, 언어별 모델 교체) | `voice/tts.*` | 예정 |
| STT 엔진 래퍼 (whisper.cpp / pywhispercpp) | `voice/stt.*` | 예정 |
| VAD (발화 감지, 바지-인용) | `voice/vad.*` | 예정 |
| 호출어 감지 ("자비스", local-wake) | `voice/wakeword.*` | 예정 |
| 상주 리스너 프로세스 (VAD+wakeword+STT 오케스트레이션 + 세션 소켓 postback) | `voice/listener.*` | 예정 |
| 입력 주입 (Claude Code cross-session messaging 소켓 postback, 실패 시 pywinauto 폴백) | `voice/inject.js` | **검증 완료** |
| 음성모드 on/off 스킬 (`/voice-on`, `/voice-off`) | `.claude/skills/voice-mode/` | 예정 |
| 설정 (음성 on/off, 벨 병행 여부 등) | `.claude/settings.json` | 예정 |
| 설치 스크립트 (모델 다운로드, 호출어 온보딩 녹음 포함) | `setup.*` | 예정 |
| 검증 | `.claude/verify.cmd` | 이번 harness에서 생성 |
| 결정 기록 | `docs/decisions.md` | 이번 harness에서 생성 |
| 설치 중 겪은 문제·해결 기록 (setup 스크립트 자동화 대상 목록) | `docs/known-issues.md` | 2026-09-25 실측 세션에서 생성. eunjeon 컴파일 문제는 미해결 |
| 전체 아키텍처 설계 (프로세스 구조, 이벤트별 데이터 흐름, 미정 항목 목록) | `docs/architecture.md` | 2026-09-25 작성 |

## 스택 (확정)
- 훅 실행: Claude Code Hooks (settings.json에 등록, Stop/Notification 이벤트)
- TTS: sherpa-onnx 런타임(런타임 123MB, 컴파일러 불필요, 실측 검증됨) + 언어별 모델 파일
  - 한국어: `vits-mimic3-ko_KO-kss_low` (63MB, 여성 화자 1명, CC-BY-NC-SA 4.0 — 비상업 전제로 사용)
  - 다른 언어: 필요 시 Piper 계열(영어 등 40개 이상 언어, 536개 모델 중 선택)
  - ~~MeloTTS-Korean~~ 폐기: 설치 2.2GB+eunjeon 컴파일 필요(미해결), 한국어 모델로 영어 읽으면 발음 깨짐 확인됨
- STT: whisper.cpp (pywhispercpp 바인딩, cp312 사전빌드 wheel 확인됨, 컴파일러 불필요)
- VAD: Silero VAD (MIT, local-wake에 내장되어 있어 별도 설치 불필요)
- 호출어: local-wake (학습 없이 본인 목소리 녹음만으로 온보딩, 실측 CPU 3.4%/RAM 325MB)
- 입력 주입: Claude Code 공식 cross-session messaging 소켓에 자기 세션 postback (**실측 검증 완료** — 실제 Stop 훅 트리거로 메시지 도착 확인) — 실패 시 pywinauto(가짜 키입력) 폴백
- 아키텍처: 상주 프로세스 하나(`voice/listener.*`)로 VAD+호출어+STT+TTS+소켓 통신 전부 처리. Claude Code 훅↔상주 프로세스는 로컬 TCP 소켓(127.0.0.1 고정 포트)
- 대상 OS: Windows (1차), macOS/Linux는 추후 고려
