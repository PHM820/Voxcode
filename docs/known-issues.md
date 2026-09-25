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

## 참고: 최종 venv 용량 (이 세션 실측치, 문제 있는 상태 포함)

| 시점 | venv 용량 |
|---|---|
| local-wake만 설치 | 1.2GB |
| + MeloTTS 의존성(에러 상태 포함) | 2.2GB |
| + pywhispercpp | 3.1GB |

MeCab 계열 충돌로 현재 venv는 한국어 TTS가 정상 동작하지 않는 상태다. 다음 세션에서
위 4번 항목을 해결하며 venv를 새로 만들 가능성이 높다.
