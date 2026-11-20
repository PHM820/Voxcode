# CLAUDE_MAP — Voxcode (구 eyes-free-coding)

Claude Code 위에 얹는 음성 애드온: ① 응답이 끝나면 짧은 음성 요약(TTS) ② 호출어 + 음성 명령(STT)을
알맞은 세션에 전달. 여러 프로젝트 세션을 화면 없이 지휘하는 게 목표. 전체 설계: `docs/architecture.md`,
결정 이유: `docs/decisions.md`, 겪은 문제: `docs/known-issues.md`.

## 음성 요약 (훅 → 리스너 → TTS)
- 개요: Stop·Notification 훅이 `~/.voxcode/inbox/`에 JSON 파일을 남기고, 리스너(`InboxWatcher`)가 읽어 리스너가 "{프로젝트명}, {내용}"을 순서대로 읽는다.
- 시작점: `hooks/on-stop.py`(`last_paragraph`), `hooks/on-notification.py`, `hooks/_common.py`(`notify_listener`), `voice/listener.py`(`InboxWatcher`, `TtsQueue`), 등록은 사용자 전역 `~/.claude/settings.json`(`voice/hooks_install.py`, 켤 때 등록·끌 때 해제 — 프로젝트 `.claude/settings.json`에는 없다).
- 함정:
  - 훅은 절대 Claude Code를 막으면 안 된다 — 예외를 삼키고 항상 exit 0. 훅은 모든 프로젝트 세션에서 돌므로 가볍게 유지.
  - inbox 파일은 `.tmp`로 쓰고 이름을 바꾼다(리스너는 `*.json`만 읽음). 못 읽는 파일은 `inbox/bad/`로 옮긴다. 리스너가 켜지기 전 종료 신호는 무시, 60초 넘은 알림은 세션 등록만 하고 안 읽는다.
  - 받아쓰는 동안(`TtsQueue.hold`)은 TTS를 미룬다. 알림마다 Jev 종류 판단(`classify_notice`)을 기록만 한다.
  - Windows에서 stdin/stdout은 cp949로 처리돼 한글이 깨진다 — 항상 바이트로 읽고 UTF-8로 쓴다.
  - Stop 훅은 응답의 **마지막 문단만** 보낸다. 그래서 음성모드에서는 응답을 1~2문장 요약으로 맺어야 한다(`hooks/on-user-prompt-submit.py`가 매 턴 이 지시를 넣고, 프로젝트 `CLAUDE.md`에도 같은 문단이 있다 — 문구를 바꾸면 둘 다).
  - `.claude/worktrees/` 아래(/delegate 작업자) 세션, 서브 관리자 폴더, 전역 `enabled: false`(`~/.voxcode/config.json`)면 아무것도 남기지 않는다.

## 음성 명령 (호출어 → 받아쓰기 → 라우팅 → 주입)
- 개요: 리스너 안의 `MicLoop` 스레드가 마이크를 계속 열고, "자비스"를 감지하면 비프 → 녹음(VAD로 끝 감지) → whisper 받아쓰기 → `~/.voxcode/log.jsonl`에 먼저 기록 → 판단(규칙·Jev)으로 명령과 대상 결정 → `voice/inject.js`로 그 세션에 사용자 메시지로 넣는다.
- 시작점: `voice/listener.py`(`MicLoop`, `_dictation_cycle`, `route_and_send`, `route_command`, `SessionTable`), `voice/judge.py`(`judge`, `Decision`), `voice/record.py`(`log_event`, `write_state`), `voice/wakeword.py`, `voice/vad.py`, `voice/stt.py`, `voice/inject.js`.
- 함정:
  - `lwake.listen()`은 콜백에서 난 `Exception`을 삼킨다 — 호출어 감지 탈출용 예외는 `BaseException`을 상속해야 한다(known-issues 17).
  - 비프가 0.3초보다 짧으면 이 PC 오디오 드라이버에서 안 들린다.
  - 판단은 Jev 호출 한 번(명령 + 대상). 확신도 0.8 미만·키 없음·오류면 규칙 폴백: 세션 1개면 그 세션 → 멈추지 않은 세션 중 최근 완료 알림 → 최근 명령. Jev에는 프로젝트명·요약만 보내고 세션 key(소켓 경로)·토큰은 `s1, s2…`로 숨긴다.
  - "멈춰"는 강제 중단이 아니라 그 세션에 문장을 그대로 전달 + `paused` 표시. 대상이 애매하면(Jev 실패 시 멈춤 단어 포함) 아무것도 안 보내고 삑 두 번. **완료 알림(notify)은 `paused`를 풀지 않는다** — 풀리는 건 다시 시작·그 세션을 직접 지시할 때뿐.
  - "대기"(`WAIT_WORDS`, 문장 전체가 일치할 때만)는 Jev보다 먼저 규칙으로 끝낸다 — 판단기에 넘기면 키가 없을 때 폴백으로 "대기"라는 문장이 세션에 전달된다. 부분 일치로 바꾸면 "대기열 만들어" 같은 지시를 삼킨다.
  - 목록·다시 말해줘·조용히·상황 묻기는 `_listener_reply`가 세션에 안 보내고 읽어 준다. 조용히 모드는 `ListenerContext.quiet` → `should_speak_notice`(지금은 훅 종류 기준).
  - 서브 관리자(`voice/manager.py`, `ask`·`launch`·`stop`)는 Jev가 애매할 때만 부른다. 주고받기는 `~/.voxcode/manager/questions·answers/` 파일 — 관리자에 주입하는 건 id 한 줄뿐. 관리자 폴더의 훅은 프로젝트로 알리지 않고 `session.json`만 등록한다(`hooks/_common.py`). 테스트는 `ask_manager`를 바꿔 끼운다.
  - 기록이 먼저: `heard`를 쓰고 나서 전달한다. `record`는 예외를 밖으로 내지 않는다(마이크 스레드 보호). 테스트는 `VOXCODE_HOME`으로 폴더를 바꾼다.
  - 호출어 온보딩(`models/wakeword/<호출어>/*.wav`)이 없으면 마이크 루프는 로그만 남기고 끝난다(음성 요약은 계속 동작). 녹음 파일은 git에 없으니 새로 받은 사람은 `python -m voice.wakeword onboard`를 본인 터미널에서 한 번 실행해야 한다(사람이 신호에 맞춰 말해야 하므로 Claude가 대신 실행하지 않음).

## TTS·STT 엔진과 언어
- 시작점: `voice/tts.py`(`TtsEngine`), `voice/stt.py`(`SttEngine`), `voice/languages.py`(`LANGUAGES`, `VoiceOption`), `.claude/download_tts_model.py`.
- 한국어 기본 목소리는 Supertonic 3(`VoiceOption.engine == "supertonic"`, `onnx_name` 자리에 스타일 이름 M1·F1…). 모델 한 벌(약 380MB)을 모든 목소리가 같이 쓰고, 추론은 Supertone 공식 `helper.py`를 모델 폴더에서 불러 쓴다(저장소에 복사하지 않음). 다른 곳에 받아 둔 모델은 `models/tts/supertonic3.path`에 경로 한 줄로 가리킨다(`supertonic_dir`). sherpa 모델보다 메모리를 더 쓰고 합성이 느리다(`SUPERTONIC_STEPS`).
- 함정: 모델은 `models/`(git 제외). mimic3 계열(ko, vi)도 espeak-ng-data가 필요하고 중국어는 lexicon.txt가 필요하다. 한국어 인식 정확도가 낮은 건 whisper 모델 크기 문제가 아니다(small로도 그대로).

## 켜기·끄기·설정
- 시작점: `voice/control.py`(`on`·`off`·`status` — 스킬이 이 한 줄을 부른다), `voice/hooks_install.py`, `.claude/skills/voice-on/SKILL.md`(최초 언어·목소리 온보딩), `voice/config.py`(`is_enabled`·`set_enabled` 전역, `load_settings` 프로젝트).
- 함정: 켜짐 표시는 전역 `~/.voxcode/config.json`, 언어·목소리는 프로젝트 `.claude/voice-settings.json`. 없거나 깨지면 꺼짐·기본값. 리스너 살아 있음은 `~/.voxcode/listener.alive` 파일의 갱신 시각으로 본다(PID 재사용 걱정 없음). 전역 설정 등록은 이 프로젝트 hooks 경로가 든 항목만 건드리고, 깨진 JSON이면 쓰지 않는다. 테스트는 `VOXCODE_HOME`·`VOXCODE_CLAUDE_SETTINGS`·`VOXCODE_CLAUDE_SKILLS`로 임시 폴더를 쓴다 — 실제 전역 설정을 건드리는 검사를 만들지 말 것.
- 전역 `/voice-on`·`/voice-off`: `voice/skills_install.py`가 `~/.claude/skills/`에 "설치 폴더의 같은 이름 스킬을 따르라"는 얇은 안내문을 만든다(`setup.cmd`가 호출). 설치 폴더 경로는 설치 순간 계산해 넣으므로 저장소엔 개인 경로가 없다 — 실제 절차는 계속 `.claude/skills/*/SKILL.md` 한 곳에서만 고친다. `MARKER`가 없는 같은 이름 스킬은 사용자 것이라 덮어쓰거나 지우지 않는다. 폴더를 옮기면 `install-skills`를 다시 실행해야 한다.

## 설치·검증
- 시작점: `setup.cmd`, `requirements.txt`, `.claude/verify.cmd`(+ `verify_routing.py`, `verify_judge.py`, `verify_hooks.py`).
- 함정: `.cmd`는 CRLF로 저장해야 하고, 배치 안에서 한글 인라인 인자나 stdin 파이프를 쓰면 조용히 깨진다 — 로직은 별도 .py로 뺀다. verify는 오디오·네트워크 없이 도는 점검만 한다(실제 마이크·스피커는 직접 확인).
