---
name: voice-on
description: 음성모드(완료 음성 요약 + 음성 명령)를 켠다. 전역 훅 등록, 상주 리스너(voice/listener.py)와 하이쿠 서브 관리자 띄우기를 voice/control.py on 한 줄로 한다.
---

# /voice-on — 음성모드 켜기

목적: 이 세션(관리자 세션)에서 완료 음성 요약과 음성 명령 입력을 받을 수 있게 한다.
자세한 설계 근거: `docs/architecture.md` "설정 파일과 프로세스 생명주기".

## 절차

0. **최초 실행이면 온보딩부터**: `voice/config.py`의 `load_settings()`로 `onboarded` 값을 확인한다.
   `false`(또는 파일 자체가 없음)면 아래 "온보딩" 섹션을 먼저 수행하고 나서 1번으로 진행한다.
   이미 `true`면 건너뛴다.
1. **켜기**: 아래 한 줄을 실행한다(프로젝트 루트에서). 결과는 JSON 한 줄이다.
   ```
   .venv\Scripts\python.exe -m voice.control on
   ```
   이 명령이 차례로 한다: 켜짐 표시(`~/.voxcode/config.json`) → **사용자 전역 설정
   `~/.claude/settings.json`에 Voxcode 훅 3개 등록**(다른 프로젝트 세션도 알림을 보내게, 끄면 해제됨,
   백업 `settings.json.voxcode.bak`) → 리스너가 안 떠 있으면 띄우고 최대 60초 기다림 → **하이쿠 서브 관리자
   창을 새 콘솔로 띄움**(계속 켜 둠 — Claude 사용량이 든다).
   - 관리자 없이 켜려면 `on --no-manager`.
   - 관리자 창이 처음 뜰 때 폴더 신뢰 확인이 나오면 사용자가 한 번 눌러야 한다고 알린다.
2. **결과 보고**: JSON의 `listener`가 `failed`면 `log_tail`을 그대로 보여 준다(추측 금지). 성공이면
   "리스너 새로 띄움/이미 떠 있음, 전역 훅 등록, 관리자 띄움" 한 줄로 보고한다.
   이미 열려 있던 다른 프로젝트 세션도 보통 자동으로 훅이 붙는다(공식 문서: 설정 파일의 훅 직접 수정은 "normally picked up
   automatically by the file watcher" — 보장은 아님). 어떤 세션이 알림을 안 보내면 그 세션을 재시작하라고 안내한다.

## 온보딩 (최초 1회)

목적: TTS(sherpa-onnx)와 STT(whisper.cpp)가 **둘 다** 지원하는 언어 중 미리 검증해 둔
목록(`voice/languages.py`의 `LANGUAGES`)에서 사용자가 언어+목소리를 고르면 그 모델을
내려받아 설정에 반영한다. 기본 추천값은 "지금 이 세션이 사용자와 대화하고 있는 언어"다
(Claude Code는 이미 그 언어를 알고 있으므로 별도로 감지할 필요 없음, 2026-09-26 결정).

1. **먼저 추천값만 짧게 확인한다** (목록은 아직 안 보여줌):
   - 지금 이 대화의 언어가 `voice/languages.py`의 `LANGUAGES`에 있는 언어와 일치하면
     (예: 한국어로 대화 중이면 `ko`), 그 언어로 진행할지만 짧게 텍스트로 묻는다:
     ```
     음성모드를 처음 켭니다. 지금처럼 한국어로 진행할까요? (다른 언어를 원하면 "다른 언어"라고 답하세요)
     ```
   - 대화 언어가 `LANGUAGES`에 없으면(교집합 밖 언어) 추천 없이 바로 2번 목록으로 간다.
   - 사용자가 그 언어를 받아들이면(긍정 답변) 그 언어로 확정하고 3번으로 건너뛴다.
2. **"다른 언어"라고 답했을 때만 전체 목록을 보여준다**: `voice/languages.py`의
   `LANGUAGES`를 "코드 - 한국어 이름 (영어 이름)" 형태로 번호 매겨 텍스트로 보여준다
   (AskUserQuestion 카드 UI 아님 — 13개라 카드 UI에 안 맞음). 일본어를 찾을 사용자를 위해
   목록 아래에 "일본어는 STT만 가능하고 TTS(음성 요약)는 아직 지원하지 않습니다"를
   덧붙인다(`voice/languages.py`의 `UNSUPPORTED_TTS_NOTE["ja"]`).
3. 언어가 정해지면, 그 언어의 `voices` 목록(대개 1~3개)을 보여주고 목소리를 고르게 한다.
   목소리가 1개뿐이면 그것으로 바로 확정하고 다시 묻지 않는다.
   - **한국어(ko)/아랍어(ar)/힌디어(hi)를 고른 경우**: "완료 음성 요약은 정상 재생되지만, 음성
     명령(받아쓰기) 인식 정확도가 다른 언어보다 낮게 나올 수 있습니다"를 한 줄 덧붙인다. 특히
     **힌디어는 정확도가 크게 낮음**(2026-09-26 13개 언어 전수 실측: 유사도 0.17 — 문자 체계
     자체가 틀리게 인식되는 수준)이 확인됐으니 "정확도가 특히 낮게 나올 수 있습니다"로 강조한다.
     베트남어(vi)는 부분적으로만 낮음(유사도 0.7대), 나머지 언어(en/es/fr/de/ru/it/pt/zh/tr/pl)는
     실측상 거의 완벽해 안내 불필요. 패턴: **로마자(라틴 문자) 언어는 대부분 정확, 비라틴 문자
     언어(한국어/아랍어/힌디어)만 정확도가 급락** — TTS 모델 계열(mimic3 vs piper)과는 무관함이
     전수 실측으로 확인됨(`docs/decisions.md` 참고). 받아쓰기가 안 먹히는 걸 "설치가 잘못됐다"고
     오인하지 않게 하기 위함.
4. 확정되면:
   - `.venv\Scripts\python.exe .claude\download_tts_model.py <voice_id>` 실행 (voice_id는
     선택된 `VoiceOption.id`). 실패하면 에러 메시지를 그대로 보여주고 멈춘다(추측 금지).
   - `voice/config.py`의 `save_settings()`로 `language`, `voice_id`를 저장하고
     `onboarded: true`로 기록한다.
   - 확정 문구를 TTS로 한 번 들려주는 건 이번 온보딩 범위 밖(리스너가 아직 안 떠 있는
     시점) — 텍스트로 "OK, {언어} {목소리}로 설정했습니다"만 보고한다.
5. **호출어 녹음 확인** (`onboarded`와 별개로 매번 확인 — 녹음 파일은 저장소에 없어서 새로 받은 사람은
   늘 비어 있다): `.venv\Scripts\python.exe -c "from voice.wakeword import WakeWordDetector as W; print(W().is_onboarded())"`
   가 `False`면, 사용자에게 **본인 터미널에서** 아래를 실행하라고 안내한다(사람이 신호에 맞춰 말해야 해서
   Claude가 대신 실행하지 않는다). 녹음 전에는 완료 음성 요약만 되고 음성 명령은 시작되지 않는다고 덧붙인다.
   ```
   .venv\Scripts\python.exe -m voice.wakeword onboard
   ```
   호출어 기본값은 "자비스"(4번 녹음, 한 번에 2초). 다른 호출어를 쓰려면 명령 끝에 붙인다.

## 확인해야 할 것

- 작업자 세션(`.claude/worktrees/` 아래)과 서브 관리자 세션(`~/.voxcode/manager/`)은 훅이 프로젝트로
  알리지 않는다(`hooks/_common.py`).
- `.venv`가 없으면(설치 안 된 상태) "먼저 `setup.cmd`를 실행하세요"로 안내하고 멈춘다 — 없는
  venv로 spawn을 시도하지 않는다.
