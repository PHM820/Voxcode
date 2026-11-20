# CLAUDE_MAP — Voxcode (구 eyes-free-coding)

Claude Code 위에 얹는 음성 애드온: ① 응답이 끝나면 짧은 음성 요약(TTS) ② 호출어 + 음성 명령(STT)을
알맞은 세션에 전달. 여러 프로젝트 세션을 화면 없이 지휘하는 게 목표. 전체 설계: `docs/architecture.md`,
결정 이유: `docs/decisions.md`, 겪은 문제: `docs/known-issues.md`.

## 음성 요약 (훅 → 리스너 → TTS)
- 개요: Stop·Notification 훅이 텍스트를 로컬 TCP(127.0.0.1:8765)로 리스너에 보내고, 리스너가 "{프로젝트명}, {내용}"을 순서대로 읽는다.
- 시작점: `hooks/on-stop.py`(`last_paragraph`), `hooks/on-notification.py`, `hooks/_common.py`(`notify_listener`), `voice/listener.py`(`ListenerServer`, `TtsQueue`), 등록은 `.claude/settings.json`.
- 함정:
  - 훅은 절대 Claude Code를 막으면 안 된다 — 예외를 삼키고 항상 exit 0, 연결 타임아웃 0.3초(리스너가 꺼져 있으면 이 환경에선 거부가 아니라 타임아웃이 난다).
  - Windows에서 stdin/stdout은 cp949로 처리돼 한글이 깨진다 — 항상 바이트로 읽고 UTF-8로 쓴다.
  - Stop 훅은 응답의 **마지막 문단만** 보낸다. 그래서 음성모드에서는 응답을 1~2문장 요약으로 맺어야 한다(`hooks/on-user-prompt-submit.py`가 매 턴 이 지시를 넣고, 프로젝트 `CLAUDE.md`에도 같은 문단이 있다 — 문구를 바꾸면 둘 다).
  - `.claude/worktrees/` 아래(/delegate 작업자) 세션과 `enabled: false`면 아무것도 보내지 않는다.

## 음성 명령 (호출어 → 받아쓰기 → 라우팅 → 주입)
- 개요: 리스너 안의 `MicLoop` 스레드가 마이크를 계속 열고, "자비스"를 감지하면 비프 → 녹음(VAD로 끝 감지) → whisper 받아쓰기 → 세션 선택 → `voice/inject.js`로 그 세션에 사용자 메시지로 넣는다. TTS 재생 중 말을 시작하면 호출어 없이 바로 받아쓰기(바지-인).
- 시작점: `voice/listener.py`(`MicLoop`, `_dictation_cycle`, `route_command`, `route_and_send`, `parse_stop_command`), `voice/wakeword.py`, `voice/vad.py`, `voice/stt.py`, `voice/inject.js`.
- 함정:
  - `lwake.listen()`은 콜백에서 난 `Exception`을 삼킨다 — 호출어 감지 탈출용 예외는 `BaseException`을 상속해야 한다(known-issues 17).
  - 비프가 0.3초보다 짧으면 이 PC 오디오 드라이버에서 안 들린다.
  - 라우팅은 규칙만 쓴다(내용 이해 없음): 세션 1개면 그 세션 → 발화가 프로젝트명으로 시작 → 최근 완료 알림 세션 → 최근 명령 세션. "멈춰 {프로젝트}"는 전 세션 브로드캐스트.
  - `/voice-detach`·`/voice-attach`는 세션이 스스로 라우팅 후보에서 빠지고 돌아오는 장치("멈춰" 뒤 재라우팅 문제). 프로젝트명으로 직접 부르면 detach 상태여도 즉시 복귀.
  - 호출어 온보딩(`models/wakeword/<호출어>/*.wav`)이 없으면 마이크 루프는 로그만 남기고 끝난다(음성 요약은 계속 동작).
  - `voice/judge.py`(Jev 환각 필터)는 코드만 있고 연결은 끊겨 있다 — 다시 쓰려면 `_dictation_cycle`에서 `should_drop_transcript` 호출.

## TTS·STT 엔진과 언어
- 시작점: `voice/tts.py`(`TtsEngine`), `voice/stt.py`(`SttEngine`), `voice/languages.py`(`LANGUAGES`, `VoiceOption`), `.claude/download_tts_model.py`.
- 함정: 모델은 `models/`(git 제외). mimic3 계열(ko, vi)도 espeak-ng-data가 필요하고 중국어는 lexicon.txt가 필요하다. 한국어 인식 정확도가 낮은 건 whisper 모델 크기 문제가 아니다(small로도 그대로).

## 켜기·끄기·설정
- 시작점: `.claude/skills/voice-on/SKILL.md`(리스너 spawn + 최초 언어·목소리 온보딩), `.claude/skills/voice-off/SKILL.md`(shutdown 이벤트), `voice/config.py`(`load_settings`), `.claude/voice-settings.json`.
- 함정: 설정 파일이 없거나 깨져도 기본값으로 동작해야 한다(`enabled` 기본 false). 리스너는 Windows 서비스가 아니라 분리된 프로세스로 띄운다.

## 설치·검증
- 시작점: `setup.cmd`, `requirements.txt`, `.claude/verify.cmd`(+ `verify_routing.py`, `verify_judge.py`, `verify_hooks.py`).
- 함정: `.cmd`는 CRLF로 저장해야 하고, 배치 안에서 한글 인라인 인자나 stdin 파이프를 쓰면 조용히 깨진다 — 로직은 별도 .py로 뺀다. verify는 오디오·네트워크 없이 도는 점검만 한다(실제 마이크·스피커는 직접 확인).
