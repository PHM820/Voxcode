# CLAUDE_MAP — Voxcode (구 eyes-free-coding)

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
| 완료 훅 (Stop 이벤트 → 요약 → listener에 TCP 전달, /delegate 워커·enabled=false 필터링) | `hooks/on-stop.py` | **구현+왕복 검증 완료** (2026-09-27). `.claude/settings.json` 등록, `verify.cmd` 통과. 관리자 경로(TCP 도달)/워커(`.claude/worktrees/`, 조용히 무시)/`enabled=false`(TCP 시도 자체 안 함) 세 갈래 전부 probe 서버로 실측 확인 |
| 권한요청 훅 (Notification 이벤트 → listener에 TCP 전달, 동일 필터링) | `hooks/on-notification.py` | **구현 완료**, 필터링 로직은 on-stop.py와 동일하게 반영. stdin `message` 필드 실사용 로그 증거는 **여전히 없음**(known-issues.md 11번, `permission_mode: auto` 세션에서는 재현 불가 — 다음 세션 과제) |
| 음성모드 응답 스타일 강제 훅 (매 프롬프트마다 `additionalContext`로 "TTS 듣기 적합한 1~2문장으로 맺어라" 재주입, 3중 재주입 설계의 우선순위 1) | `hooks/on-user-prompt-submit.py` | **구현+실측 검증 완료** (2026-09-26). `.claude/settings.json`에 `UserPromptSubmit` 등록, `_is_delegate_worker()` 재사용. `enabled: false/true` 두 상태 모두 직접 실행 확인, stdout UTF-8 인코딩 버그 발견·수정 |
| STT 엔진 래퍼 (whisper.cpp / pywhispercpp, `language='ko'` 고정) | `voice/stt.py` | **최소 구현 있음** (2026-09-26, import 성공 확인) — 이번 세션 API 한도로 작업 중단, **실제 마이크/왕복 실행은 미검증** |
| VAD (발화 감지, 바지-인용) | `voice/vad.py` | **최소 구현 있음** (2026-09-26, import 성공 확인) — 위와 동일하게 **실제 동작 미검증** |
| 호출어 감지 ("자비스", local-wake, 온보딩 포함) | `voice/wakeword.py` | **최소 구현 있음** (2026-09-26, import 성공 확인) — 위와 동일하게 **실제 동작 미검증**, 온보딩 흐름도 미검증 |
| 상주 리스너 프로세스 (TCP 서버+세션 상태 테이블+TTS 큐+라우팅+마이크 루프 통합 코드) | `voice/listener.py` | **마이크 루프 통합 코드 추가됨** (2026-09-26, API 한도로 중단) — import·verify.cmd 통과했지만 **실시간 마이크 감지·바지인 동작은 다음 세션에서 사람이 실제로 말해가며 재검증 필요**. 받아쓰기 진입/완료 비프음(`play_beep_blocking`)은 **실측 검증 완료**(2026-09-26) — 원래 0.15초였던 게 이 PC MME 드라이버에서 무음 재생되는 버그를 발견, 사용자가 직접 들으며 0.3초로 확정. Stop 훅→TCP→TTS 큐 왕복도 **실측 검증 완료**(2026-09-26, 로그로 재생 호출까지 확인 — 원격 환경이라 실제 소리는 미확인). "멈춰" A안(`active` 필드, detach/attach 이벤트, 라우팅 규칙 ①②③ 반영)도 **구현+실측 검증 완료**(2026-09-26, probe TCP로 왕복 확인). `voice/vad.py`는 합성 오디오로 실제 실행 검증 완료(발화 경계 정확히 감지), `_wait_for_wakeword()`는 정적 리뷰로 발견한 잠재적 조용한 무한 루프(known-issues.md 14번)에 방어 코드 추가(2026-09-26 밤모드) |
| TTS 엔진 래퍼 (sherpa-onnx, 언어별 모델 동적 선택) | `voice/tts.py` | **다국어 지원 완료+실측 검증** (2026-09-26) — `language_code`+`voice_id`로 `voice/languages.py` 메타데이터를 찾아 모델 로딩. 영어 모델 실제 다운로드+합성 왕복 확인, 기존 한국어 레거시 경로(인자 없이 생성) 회귀 없음 확인 |
| 언어·목소리 메타데이터 (TTS×STT 교집합 52개 중 13개 1차 등록) | `voice/languages.py` | **구현 완료** (2026-09-26). `LANGUAGES` 튜플에 언어별 `VoiceOption`(onnx 파일명, espeak-ng-data 필요 여부 등 실측값). 나머지 39개 언어는 필요 시 같은 구조로 추가 |
| TTS 모델 다운로드 (voice_id 기준, setup.cmd/온보딩 공용) | `.claude/download_tts_model.py` | **구현+실측 검증 완료** (2026-09-26) — 영어 모델 실제 다운로드·압축해제·파일 존재 검증까지 확인 |
| 입력 주입 (Claude Code cross-session messaging 소켓 postback, 실패 시 pywinauto 폴백) | `voice/inject.js` | **검증 완료**, 실제 세션 postback도 listener.py 통합 후 2026-09-26 재검증 성공. write-완료 확인 없이 소켓을 닫던 잠재 버그(2026-09-26 밤모드 코드 리뷰로 발견)를 콜백 방식으로 수정, 로컬 named pipe 왕복으로 재검증 완료 |
| 음성모드 켜기 (listener.py 기동 확인/spawn, enabled=true 기록, 최초 실행 시 언어+목소리 온보딩) | `.claude/skills/voice-on/SKILL.md` | **구현+왕복 검증 완료** (2026-09-26) — spawn/enabled는 2026-09-27, 온보딩 절차(대화 언어 추천→확정→다운로드→저장)도 2026-09-26 실제 스킬 실행으로 왕복 검증 완료. 한국어/아랍어/힌디어(비라틴 문자) 선택 시 "인식 정확도 낮을 수 있음" 안내 문구 추가(2026-09-26 밤모드, 13개 언어 전수 TTS→STT 왕복 실측 — mimic3 계열 문제 가설은 기각되고 "비라틴 문자 언어 전반의 문제"로 정정) |
| 음성모드 끄기 (listener.py에 shutdown 이벤트, enabled=false 기록, 3중 재주입·A안 회수 체크리스트) | `.claude/skills/voice-off/SKILL.md` | **구현+왕복 검증 완료** (2026-09-27) — listener.py 실제 프로세스 종료까지 확인 |
| "멈춰" 이후 이 세션을 음성 라우팅 후보에서 스스로 뺌 (A안) | `.claude/skills/voice-detach/SKILL.md` | **구현+실측 검증 완료** (2026-09-26) |
| detach된 세션을 스스로 라우팅 후보로 복귀 (A안) | `.claude/skills/voice-attach/SKILL.md` | **구현+실측 검증 완료** (2026-09-26) |
| 설정 읽기/쓰기 헬퍼 (기본값 제공, 파일 없어도 안전하게 동작) | `voice/config.py` | **구현 완료** (2026-09-27), 훅 2개 + voice-on/off가 공유 |
| 설정 (음성 on/off, 호출어, 벨 병행 여부, 프로젝트 별칭) | `.claude/voice-settings.json` | 스키마 확정 (`enabled` 기본값 `false`로 2026-09-27 정정). 파일은 `/voice-on` 최초 실행 시 생성됨(그 전까진 존재 안 해도 기본값으로 동작) |
| 설치 스크립트 (venv+패키지+TTS/STT 모델 다운로드, 클린 설치·재실행 스킵 둘 다 실측 검증) | `setup.cmd` | **구현 완료** (2026-09-26). 호출어 온보딩 녹음은 아직 없음(local-wake 온보딩 자체가 미구현) |
| Python 의존성 목록 (버전 느슨히 고정, known-issues.md 2번 교훈 반영) | `requirements.txt` | **구현 완료** (2026-09-26) |
| 검증 | `.claude/verify.cmd` | 이번 harness에서 생성 |
| 결정 기록 | `docs/decisions.md` | 이번 harness에서 생성 |
| 설치 중 겪은 문제·해결 기록 (setup 스크립트 자동화 대상 목록) | `docs/known-issues.md` | 2026-09-25 실측 세션에서 생성, 이후 계속 추가(2026-09-26 기준 13개 항목). eunjeon 컴파일 문제(4번)는 미해결, Notification stdin 필드(11번)도 미확인 |
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
