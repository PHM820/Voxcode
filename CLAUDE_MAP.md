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
| 완료 훅 (Stop 이벤트 → 요약 → listener에 TCP 전달) | `hooks/on-stop.py` | **구현+왕복 검증 완료** (2026-09-26). `.claude/settings.json` 등록, `verify.cmd` 통과. **실제로 훅을 실행해 listener.py(TCP:8765) 도달 + TTS 큐 처리를 `.scratch/listener.log`로 직접 확인**, listener 강제종료 후에도 exit 0으로 조용히 성공 종료하는 것까지 실측 확인 |
| 권한요청 훅 (Notification 이벤트 → listener에 TCP 전달) | `hooks/on-notification.py` | **구현 완료**, 등록·import 체크 통과. stdin `message` 필드 실사용 로그 증거는 **여전히 없음**(known-issues.md 11번, `permission_mode: auto` 세션에서는 재현 불가 — 다음 세션 과제) |
| STT 엔진 래퍼 (whisper.cpp / pywhispercpp, `language='ko'` 고정) | `voice/stt.py` | **최소 구현 있음** (2026-09-26, import 성공 확인) — 이번 세션 API 한도로 작업 중단, **실제 마이크/왕복 실행은 미검증** |
| VAD (발화 감지, 바지-인용) | `voice/vad.py` | **최소 구현 있음** (2026-09-26, import 성공 확인) — 위와 동일하게 **실제 동작 미검증** |
| 호출어 감지 ("자비스", local-wake, 온보딩 포함) | `voice/wakeword.py` | **최소 구현 있음** (2026-09-26, import 성공 확인) — 위와 동일하게 **실제 동작 미검증**, 온보딩 흐름도 미검증 |
| 상주 리스너 프로세스 (TCP 서버+세션 상태 테이블+TTS 큐+라우팅+마이크 루프 통합 코드, 라우팅 로직만 실측 검증됨) | `voice/listener.py` | **마이크 루프 통합 코드 추가됨** (2026-09-26, API 한도로 중단) — import·verify.cmd 통과했지만 **실시간 마이크 감지·바지인 동작은 다음 세션에서 사람이 실제로 말해가며 재검증 필요** |
| TTS 엔진 래퍼 (sherpa-onnx, 한국어 모델 하드코딩) | `voice/tts.py` | **최소 버전 구현 완료** (2026-09-26) — 언어별 모델 교체는 TODO |
| 입력 주입 (Claude Code cross-session messaging 소켓 postback, 실패 시 pywinauto 폴백) | `voice/inject.js` | **검증 완료**, 실제 세션 postback도 listener.py 통합 후 2026-09-26 재검증 성공 |
| 음성모드 on/off 스킬 (`/voice-on`, `/voice-off`, listener.py를 subprocess.Popen으로 spawn/종료) | `.claude/skills/voice-mode/` | 예정 |
| 설정 (음성 on/off, 호출어, 벨 병행 여부, 프로젝트 별칭) | `.claude/voice-settings.json` | 스키마 확정 (2026-09-26), 파일 자체는 예정 |
| 설치 스크립트 (venv+패키지+TTS/STT 모델 다운로드, 클린 설치·재실행 스킵 둘 다 실측 검증) | `setup.cmd` | **구현 완료** (2026-09-26). 호출어 온보딩 녹음은 아직 없음(local-wake 온보딩 자체가 미구현) |
| Python 의존성 목록 (버전 느슨히 고정, known-issues.md 2번 교훈 반영) | `requirements.txt` | **구현 완료** (2026-09-26) |
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
