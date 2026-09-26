# 설치 중 겪은 문제와 해결 기록

2026-09-25 실측 세션에서 이 PC(Windows 11, Python 3.12, C++/Rust 컴파일러 미설치, Kaspersky 백신)에
local-wake + MeloTTS-Korean + pywhispercpp를 같은 가상환경에 설치하며 겪은 문제 전부.
다른 사용자가 같은 문제를 반복하지 않도록, 그리고 `setup.*` 스크립트를 만들 때 자동화 대상 목록으로 쓴다.

## 1. pip SSL 인증서 검증 실패 (백신 SSL 검사 소프트웨어 사용자 전원 영향 가능)

**증상**
```
SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED]
certificate verify failed: self-signed certificate in certificate chain'))
```
`pip install` 전체가 실패.

**원인**
Kaspersky(또는 유사한 백신·보안 소프트웨어)가 HTTPS 트래픽을 자체 루트 인증서로 재서명해서
검사한다(SSL Inspection). `curl`이나 브라우저는 Windows 인증서 저장소를 참조해서 문제없이
통과하지만, `pip`은 자체 `certifi` 인증서 번들을 쓰기 때문에 그 백신의 자체서명 인증서를
신뢰하지 못해 실패한다. Kaspersky 외에 ESET, Avast, ZScaler, Netskope 등 SSL 검사 기능이
있는 백신·기업 보안 소프트웨어 사용자라면 동일 증상이 날 수 있다.

**해결 (실제로 검증됨)**
1. Windows 인증서 저장소에서 해당 백신의 루트 인증서를 PowerShell로 내보낸다.
2. DER → PEM으로 변환한다.
3. pip이 쓰는 certifi 번들(`<venv>\Lib\site-packages\pip\_vendor\certifi\cacert.pem`, pip
   업그레이드 후에는 `<venv>\Lib\site-packages\certifi\cacert.pem`에도 동일하게)에 이어붙인다.
   가상환경(venv) 안의 파일만 바꾸는 것이라 시스템 전체엔 영향 없고, venv를 지우면 원상복구된다.

**setup 스크립트로 자동화할 때 주의점**
- 어떤 백신을 쓰는지 모르니, Windows 루트 저장소(`Cert:\LocalMachine\Root`)에서 "자체서명이고
  pypi.org로의 연결에 관여하는" 인증서를 자동 탐지하는 로직이 필요하다 (이름으로 하드코딩하면
  Kaspersky 외 백신 사용자는 여전히 실패).
- 더 간단한 대안: `pip-system-certs` 패키지를 pip으로 설치해 Windows 인증서 저장소를 자동으로
  쓰게 만드는 방법이 있는데, **이것도 같은 SSL 문제 때문에 pip으로 못 받는 닭과 달걀 문제**가
  있다. 최초 1회는 위 수동 우회(인증서 이어붙이기)로 뚫은 뒐, 그 안에서 `pip-system-certs`를
  설치해 이후를 편하게 만드는 2단계 접근이 필요하다.

---

## 2. pip 구버전이 사전빌드 wheel을 못 찾고 소스 빌드로 빠짐

**증상**
`tokenizers`, `fugashi` 등 Rust/C++로 작성된 패키지가 버전을 고정(`==`)해서 설치하면
`error: can't find Rust compiler` 또는 `error: Microsoft Visual C++ 14.0 or greater is required`로
실패.

**원인**
`transformers==4.27.4`(MeloTTS가 지정한 오래된 버전, 2023년 초)가 요구하는 `tokenizers`의
구버전에는애초에 Python 3.12용 사전빌드 wheel이 없다(그 패키지가 나온 시점에 Python 3.12가
존재하지 않았음). `fugashi==1.3.0`도 마찬가지. 컴파일러가 없어도 최신 버전에는 wheel이 있다.

**해결 (실제로 검증됨)**
`requirements.txt`에서 문제되는 패키지의 버전 고정(`==x.x.x`)을 제거하고 최신 버전이 설치되게
둔다. `transformers`, `fugashi`, `unidic`, `unidic_lite`, `mecab-python3`, `librosa`에서 모두
같은 패턴 확인됨. 이후 실제 동작에 문제없음을 확인(아래 4번 항목 제외).

**setup 스크립트로 자동화할 때 주의점**
- pip 자체도 먼저 `pip install --upgrade pip`로 최신화해두면 최신 wheel 탐색 로직이 개선되어
  일부는 저절로 해결된다(전부는 아님 — 버전 고정 자체가 문제일 때는 pip 업그레이드로도 안 풀림).
- MeloTTS 원본 `requirements.txt`를 그대로 쓰지 말고, 이 프로젝트가 자체 `requirements.txt`
  (버전 고정을 푼 버전)를 유지해서 배포해야 한다.

---

## 3. `pkg_resources` 없음 (최신 setuptools 사용자 전원 영향)

**증상**
```
ModuleNotFoundError: No module named 'pkg_resources'
```
`pykakasi`(MeloTTS의 일본어 처리 경로, 한국어를 써도 로드됨) import 시 발생.

**원인**
`setuptools` 81 버전부터 `pkg_resources` 모듈이 제거됐다(deprecated 처리 완료). `pykakasi`가
오래된 관행대로 이 모듈을 직접 import하고 있어서, 최신 `setuptools`가 깔린 환경(신규 Python
설치 등)에서는 무조건 이 에러가 난다.

**해결 (실제로 검증됨)**
```
pip install "setuptools<81"
```
경고 메시지(`pkg_resources is deprecated... slated for removal as early as 2025-11-30`)는
뜨지만 정상 동작한다. 단, **2025-11-30 이후 배포되는 setuptools에서는 pkg_resources 자체가
아예 사라질 수 있다고 예고돼 있어**, 이 우회가 영구적이지 않을 수 있다 — MeloTTS나 pykakasi가
그 전에 코드를 고치지 않으면 이 프로젝트도 다시 막힐 수 있음. 배포 시점에 재확인 필요.

---

## 4. 한국어 처리 핵심 의존성(`eunjeon`)이 Windows에서 컴파일 필요 — **미해결**

**증상**
```
error: Microsoft Visual C++ 14.0 or greater is required.
Get it with "Microsoft C++ Build Tools"
```
`g2pkk`(MeloTTS의 한국어 발음 변환 핵심 모듈)가 Windows에서 `eunjeon` 패키지를 요구하는데,
이 패키지는 PyPI에 소스 배포판만 있고 Python 3.12용 사전빌드 wheel이 없다.

**시도했지만 안 된 우회**
- 대체 패키지 `python-mecab-ko`(사전빌드 wheel 있음)를 설치 시도 → **실패**. Windows는
  파일시스템이 대소문자를 구분하지 않는데, 이미 설치된 `mecab-python3`(fugashi의 의존성,
  `MeCab` 패키지 제공)와 `python-mecab-ko`(`mecab` 패키지 제공)가 설치하는 실제 파일명이
  대소문자만 다르게 겹쳐서(`_MeCab.*.pyd` vs `_mecab.*.pyd`) 서로 덮어씀. 결과적으로 두
  패키지 다 깨짐.
- `g2pkk` 소스코드(`g2pkk.py`)를 확인해보니 Windows에서는 `eunjeon`을 쓰도록 하드코딩되어
  있어(`platform.system()=='Windows'` 분기), 코드 수정 없이는 대체 불가.

**남은 선택지 (다음 세션에서 결정 필요)**
1. Visual Studio Build Tools 설치 후 `eunjeon` 직접 컴파일 — 확실하지만 사용자에게 1GB+
   추가 설치를 요구해 접근성 도구의 진입장벽을 높임
2. `g2pkk`를 별도 가상환경으로 완전히 분리(별도 프로세스로 실행, 결과만 IPC로 받기) —
   mecab 파일명 충돌을 원천 차단하지만 구조가 복잡해짐
3. `g2pkk.py`를 패치해서 Windows에서도 `python-mecab-ko`(모듈명 `mecab`)를 쓰도록 강제 —
   fugashi(`mecab-python3`, 일본어용)를 빼거나 이름 충돌을 우회하는 별도 설치 순서 필요
4. 한국어 TTS를 MeloTTS 외 다른 엔진으로 교체 (Kokoro는 한국어 미지원, Piper는 한국어
   비공식 커뮤니티 모델만 있어 이번 조사에서는 기각)

---

## 5. whisper.cpp는 16000Hz 오디오만 받음 (해결됨, 설계에 반영 필요)

**증상**
```
Exception: WAV file must be 16000 Hz
```
sherpa-onnx가 생성한 wav(22050Hz)를 pywhispercpp에 바로 넣으면 실패.

**원인**
whisper.cpp는 입력 오디오가 정확히 16000Hz여야 한다는 제약이 있다(모델 학습 조건). TTS 엔진(sherpa-onnx)과 STT 엔진(whisper.cpp)은 서로 다른 목적(하나는 스피커 출력용, 하나는 마이크 입력용)이라 실제 사용에서 이 둘이 오디오를 주고받을 일은 없지만, 테스트나 디버깅 중 TTS 출력을 STT로 검증하려면 리샘플링이 필요하다.

**해결**
`numpy.interp` 기반 선형 보간으로 충분히 해결됨(테스트 목적). 다만 **실제 마이크 입력 경로 설계 시 확인 필요**: local-wake가 쓰는 sounddevice나 다른 마이크 캡처 라이브러리가 몇 Hz로 녹음하는지 맞춰서, STT로 넘기기 전 필요하면 리샘플링 단계를 `voice/stt.*` 래퍼 안에 넣어야 한다.

---

## 6. whisper.cpp `language` 파라미터 생략 시 완전히 엉뚱한 언어로 오인식 (설계에 반드시 반영)

**증상**
한국어 문장("모든 구성요소가 한 프로세스에서 잘 동작합니다.")을 `transcribe(audio)`처럼 `language` 파라미터
없이 넘기면, 전혀 관련 없는 영어 문장("All 9 women are active in the group.")으로 인식됨. 에러 없이
조용히 틀린 결과를 반환하므로 눈치채기 어렵다.

**원인**
`language`를 생략하면 whisper가 오디오 앞부분만 보고 언어를 자동 감지하는데, 이 자동 감지가 짧은
문장이나 정확도가 떨어지는 base 모델에서 실패할 수 있다.

**해결 (검증됨)**
`transcribe(audio, language='ko')`처럼 **항상 언어를 명시적으로 고정**한다. 이렇게 하니 원문과 의미가
거의 일치하는 결과가 나왔다(왕복 테스트 재현 확인).

**설계 반영 필요**
`voice/stt.*` 래퍼는 항상 `language='ko'`를 하드코딩해서 호출해야 한다(다국어 지원 시에도 자동 감지에
맡기지 말고, 사용자가 설정한 언어를 명시적으로 넘기는 구조로).

---

## 7. Cross-session messaging 소켓에 auth+user 메시지를 나눠 쓰면 조용히 drop됨 (해결됨, 설계에 반영 필요)

**증상**
`voice/inject.js`에서 `socket.write({type:"auth",...})`와 `socket.write({type:"user",...})`를
따로 두 번 호출하면, 소켓 `write()` 자체는 에러 없이 성공(콜백/이벤트 정상)하지만 실제로는
메시지가 세션에 전혀 도착하지 않는다. 에러도 없고 로그도 안 남아 원인 파악이 어렵다.

**원인**
claude.exe 바이너리의 디버그 문자열 확인 결과, uds-messaging 서버는 "완전한 한 줄"이 도착하기를
기다리며, 연결 후 일정 시간 내 완전한 줄이 오지 않으면 조용히 연결을 닫는다
(`[uds-messaging] Closing a connection that sent no complete line within ... ms`). 공식 예제
코드도 힌트로 "run the command first, then connect and write its output as ONE line"이라고
명시한다. `write()`를 두 번 나눠 호출하면 OS/네트워크 계층에서 별도 패킷으로 쪼개져 도착할 수
있어, 서버가 완전한 한 줄로 못 묶고 드롭하는 것으로 추정된다.

**해결 (실제로 검증됨)**
`auth` JSON과 `user` JSON을 각각 `\n`으로 끝나는 문자열로 만든 뒤, **하나의 문자열로 이어붙여
`socket.write()`를 단 한 번만 호출**한다. 이렇게 바꾸자 즉시 메시지 도착 확인됨(Stop 훅 실제
트리거로 검증).

```js
const payload =
  JSON.stringify({ type: "auth", token: TOKEN }) + "\n" +
  JSON.stringify({ type: "user", message: { role: "user", content: text } }) + "\n";
socket.write(payload);
```

**설계 반영 필요**
`voice/inject.js`(및 향후 비슷한 소켓 통신 코드)는 항상 여러 프레임을 하나의 `write()` 호출로
합쳐 보내야 한다. 여러 번 나눠 쓰는 패턴은 겉보기엔 성공한 것처럼 보이지만 실제로는 실패하므로
특히 위험하다(known-issues.md 6번의 whisper language 버그와 같은 "조용히 틀림" 유형).

---

## 8. Python `subprocess.run(text=True)`로 Node 자식 프로세스의 한글 stdout/stderr를 읽으면 예외 발생 (해결됨)

**증상**
`voice/listener.py`가 `subprocess.run(["node", "inject.js", ...], capture_output=True, text=True)`로
`inject.js`를 실행하면, `inject.js`가 한글 메시지(`전송 실패: ...` 등)를 stdout/stderr로 찍는
순간 `UnicodeDecodeError: 'cp949' codec can't decode byte ...`가 별도 리더 스레드에서 발생하고,
`result.stdout`/`result.stderr`가 `None`으로 남아 이후 `.strip()` 호출 시
`'NoneType' object has no attribute 'strip'`로 2차 오류가 남(원인이 완전히 가려짐).

**원인**
`text=True`만 주면 Python이 OS 기본 인코딩(Windows에서는 로캘에 따라 cp949 등)으로 디코딩을
시도한다. Node 프로세스는 UTF-8로 출력하므로 한글이 섞이면 깨진다. known-issues.md 6/7번과
같은 "조용히 틀린 결과" 유형 — 에러 메시지가 진짜 원인(인코딩)을 안 보여주고 엉뚱한
`NoneType` 오류로 나타나 원인 파악에 시간이 걸림.

**해결 (검증됨)**
`text=True` 대신 `encoding="utf-8", errors="replace"`를 명시한다:
```python
subprocess.run([...], capture_output=True, encoding="utf-8", errors="replace", timeout=10)
```
`voice/listener.py`의 `send_postback()`에 반영됨.

**설계 반영 필요**
Python에서 Node(또는 다른 UTF-8 출력 프로세스)를 subprocess로 부르는 모든 곳에서
`text=True` 대신 `encoding="utf-8"`을 명시적으로 고정한다.

---

## 9. `.cmd` 파일을 LF로 저장하면 cmd.exe가 줄 단위 파싱을 깨뜨림 (해결됨)

**증상**
`.claude/verify.cmd`를 UTF-8 LF(유닉스 줄바꿈)로 저장한 뒤 `cmd /c verify.cmd`로 실행하면
"'ect' is not recognized...", "'V_PY' is not recognized..." 처럼 명령어가 단어 중간에서
잘려 완전히 엉뚱한 토큰으로 인식됨.

**원인**
Windows `cmd.exe`의 배치 파서는 CRLF(`\r\n`) 줄바꿈을 전제로 하며, LF만 있는 파일에서는
줄 경계를 제대로 못 잡고 이전 줄과 다음 줄이 섞여 파싱된다. 에디터/도구가 기본으로 LF를
쓰는 환경(WSL, 이 프로젝트의 Write 도구 등)에서 `.bat`/`.cmd` 파일을 만들면 재현된다.

**해결 (검증됨)**
`.cmd`/`.bat` 파일은 항상 CRLF로 저장한다. `unix2dos <file>` 또는 `sed -i 's/$/\r/' <file>`로
변환 가능. `python voice/listener.py` 같은 `.py` 파일은 Python 인터프리터가 두 줄바꿈 모두
허용하므로 영향 없음 — **배치 파일에서만** 문제.

**설계 반영 필요**
앞으로 `.cmd`/`.bat` 파일을 새로 만들거나 수정할 때는 저장 직후 `xxd`나 `file` 명령으로
CRLF인지 확인하는 습관을 들인다(`file` 출력에 "CRLF line terminators"가 없으면 의심).

---

## 10. `.cmd`에서 `python -c "..."`에 한글 문자열을 직접 넘기면 콘솔 코드페이지로 깨짐 (해결됨)

**증상**
`.claude/verify.cmd`에서 `"%VENV_PY%" -c "... assert parse_stop_command('멈춰')is None ..."`처럼
한글 리터럴을 `-c` 인자에 직접 박아 넣으면, `AssertionError`가 나며 `print()`로 찍은 문자열도
콘솔에 `????`로 깨져 보인다. 로직 자체(`voice/listener.py`)는 정상인데도 검증이 실패한다.

**원인**
cmd.exe가 배치 파일의 문자열 인자를 자식 프로세스(python.exe)에 넘길 때 시스템 로캘
코드페이지(한국어 Windows에서는 cp949)를 거친다. `.cmd` 파일 자체는 UTF-8로 저장돼 있어도,
`-c` 인자로 전달되는 순간 그 경로를 타면서 한글이 깨진다. known-issues.md 8/9번과 같은
"cmd.exe와 UTF-8/한글이 만나면 깨진다" 계열이지만, 이번엔 subprocess 호출이 아니라
**cmd.exe 자신이 자식에게 인자를 넘기는 경로**에서 발생해 원인 지점이 다르다.

**해결 (검증됨)**
한글이 섞인 테스트 코드는 `-c` 인자로 넘기지 않고, 별도 `.py` 파일(UTF-8로 저장, harness의
"verify.cmd는 ASCII만" 규칙은 `.cmd` 파일 자체에만 적용되고 그 안에서 실행하는 `.py` 파일에는
해당 없음)로 분리해 `"%VENV_PY%" 파일경로.py`처럼 파일 자체를 인터프리터에 넘긴다. Python이
파일을 읽을 때는 `# -*- coding: utf-8 -*-`(또는 기본 UTF-8 처리)로 정상 디코딩되어 cmd.exe의
인자 전달 경로를 타지 않는다. `.claude/verify_routing.py`로 분리해 해결 확인.

**설계 반영 필요**
`.cmd`/`.bat`에서 Python 등 자식 프로세스를 호출할 때, 한글(또는 비ASCII)이 포함된 코드는
인라인 `-c` 인자로 넘기지 말고 항상 별도 파일로 분리해서 파일 경로만 인자로 넘긴다.

---

## 11. Notification 훅 stdin 필드 — 아직 실측 캡처 로그 없음 (미해결, 확인 필요)

**상태**
`hooks/on-notification.py`는 `message` 필드(없으면 `title`)를 읽도록 작성돼 있고,
`docs/decisions.md`의 2026-09-25 항목에 "Notification 훅 stdin의 실제 필드는 실측 확인"이라고
적혀 있다. 하지만 2026-09-26 재검증 시점에 `.scratch/notification_dump.txt`(캡처용으로
`.claude/settings.local.json`에 걸어둔 임시 훅 `.scratch/dump_notification.py`의 출력 파일)가
**존재하지 않았다** — 즉 이 프로젝트 저장소 안에 Notification 이벤트의 실제 stdin JSON을
눈으로 확인한 로그 파일 증거가 남아있지 않다.

**원인 추정**
Notification 이벤트는 Stop과 달리 권한 확인 대기·장시간 유휴 등 특정 상황에서만 발생해서,
매 세션 자연 발생을 보장할 수 없다. 이전 세션에서 캡처했더라도 검증 후 파일을 정리했을
가능성, 또는 애초에 이 프로젝트 저장소가 아닌 다른 경로에서 캡처했을 가능성이 있다.

**다음 세션에서 할 일**
`.claude/settings.local.json`에 이미 `Notification → .scratch/dump_notification.py` 임시
훅이 등록돼 있으므로, 권한 확인이 실제로 뜨는 명령(예: 미승인 Bash 도구)을 실행해 Notification
이벤트를 의도적으로 유발한 뒤 `.scratch/notification_dump.txt`가 생성되는지, `message` 필드가
실제로 존재하는지 눈으로 재확인한다. 확인되면 이 항목을 "해결"로 갱신하고 임시 훅은 삭제한다.

---

## 12. `.cmd` 안에서 프로세스에 파이프/리다이렉트로 stdin을 주면 그 지점 이후 배치 실행이 조용히 멈춤 (해결됨)

**증상**
`.claude/verify.cmd`에서 `echo {}| "%VENV_PY%" hooks\on-stop.py`(파이프)와
`"%VENV_PY%" hooks\on-stop.py < payload.json`(리다이렉트) 둘 다, 그 명령 자체는
`errorlevel 0`으로 정상 종료하는데도 **그 줄 이후의 배치 파일 나머지 내용이 전혀 실행되지
않는다**(다음 `echo`도 안 찍히고 에러 메시지도 없음). 파일을 이분법으로 잘라가며 재현
범위를 좁혀봐도, 최소 재현(짧은 테스트 `.cmd`)에서는 똑같은 코드가 정상 동작해 원인을
끝내 특정하지 못했다.

**시도했지만 원인 규명에 실패한 것**
- REM 주석에서 `|` 문자 제거 → 재현 유지
- 파이프를 파일 리다이렉트(`<`)로 교체 → 재현 유지
- `if not exist` 블록, `node --check` 등 앞선 단계들을 하나씩 제거/추가하며 최소 재현 시도
  → 실제 파일 전체를 실행할 때만 재현되고, 그 앞부분만 잘라 별도 파일로 실행하면 통과함
  (즉 "실제 파일 안에서, 이 지점까지 도달한 실행 컨텍스트에서만" 재현되는 것으로 보이나,
  정확한 트리거는 못 찾음)
- 웹 검색(`windows batch pipe silently stops script`)으로도 이 정확한 현상의 공식 문서화된
  원인은 못 찾음 — cmd.exe가 파이프 좌우를 별도 서브프로세스로 실행하며 배치 파일을 다시
  파싱하는 과정에서 발생하는, 널리 알려지진 않은 종류의 현상으로 추정만 함

**해결 (실제로 검증됨) — 원인 규명 대신 우회**
known-issues.md 10번(cmd -c 인자 한글 깨짐)과 같은 패턴: **stdin을 줘야 하는 프로세스 실행은
배치 파일 안에서 직접 하지 않고, `subprocess`를 쓰는 별도 `.py` 파일로 옮겨서 그 파일
하나만 배치에서 호출**한다. `.claude/verify_hooks.py`가 `subprocess.run([...], input="{}")`로
훅을 실행하도록 분리하자 문제가 사라짐(`ALL CHECKS PASSED`까지 정상 도달 확인).

**설계 반영 필요**
`.cmd`/`.bat` 파일 안에서 어떤 프로세스에 stdin을 파이프나 리다이렉트로 직접 공급하는 코드는
작성하지 않는다. 항상 그 프로세스 실행 자체를 `.py`(또는 다른 스크립트) 파일로 옮기고, 배치
파일은 그 파일 하나만 인자 없이 호출한다. 이건 known-issues.md 9(CRLF), 10(한글 인자 깨짐)에
이어 **"cmd.exe 배치 파일 안에서 복잡한 프로세스 실행/입출력 제어를 직접 하지 않는다"**는 더
일반적인 원칙으로 굳혀도 될 만큼 반복되는 패턴이다.

---

## 참고: 최종 venv 용량 (이 세션 실측치, 문제 있는 상태 포함)

| 시점 | venv 용량 |
|---|---|
| local-wake만 설치 | 1.2GB |
| + MeloTTS 의존성(에러 상태 포함) | 2.2GB |
| + pywhispercpp | 3.1GB |

MeCab 계열 충돌로 현재 venv는 한국어 TTS가 정상 동작하지 않는 상태다. 다음 세션에서
위 4번 항목을 해결하며 venv를 새로 만들 가능성이 높다.
