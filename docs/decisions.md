# 결정 기록

| 날짜 | 결정 | 이유 |
|---|---|---|
| 2026-09-25 | Claude Code 공식 스크린리더 모드(`--ax-screen-reader`) 위에 훅으로 얹는 구조로 간다 | 터미널 평문화·벨 알림은 이미 공식 지원. 완료 음성 요약과 음성 명령 입력만 빈 자리 |
| 2026-09-25 | ~~STT: Windows 내장 음성 인식~~ → **whisper.cpp (base/small 모델)로 교체** | Windows 내장은 한국어 정확도가 낮음. whisper.cpp는 CPU 전용으로도 small 모델이 실시간 대비 6배 빠르고 RAM 2GB만 사용 — 이 PC(i5-1340P, RAM16GB, GPU 없음)에 무리 없음. 설치도 모델 파일 하나 받는 수준이라 가벼움 유지 |
| 2026-09-25 | TTS: MeloTTS-Korean (MIT) | CPU로 실시간 동작, 한국어 전용 모델 존재, 설치 용량 가벼움(~500MB) |
| 2026-09-25 | 프로젝트명 eyes-free-coding, 영문 kebab-case | 공개 GitHub 배포 예정 — 인코딩/경로 문제 방지 |
| 2026-09-25 | VAD(발화 감지): Silero VAD (MIT) | 모델 2MB, CPU 0.5% 미만, 다국어. TTS 재생 중 사용자가 말 시작하면 바로 끊는 바지-인(barge-in)에 사용 |
| 2026-09-25 | 호출어 감지: local-wake (학습 불필요 방식) | openWakeWord는 영어 TTS 데이터로만 학습 가능해 한국어("자비스") 불가. local-wake는 Google 음성 임베딩 + DTW 패턴매칭이라 언어 무관, 본인 목소리 3~4회 녹음만으로 온보딩 완료 |
| 2026-09-25 | 트리거 로직 확정 | TTS 재생 중: 호출어 없이 VAD 감지만으로 즉시 끊고 받아쓰기. TTS 없음(유휴·작업중 불문): "자비스" 호출 필수 → 받아쓰기 → 엔터 자동 전송(기존 작업 중지 안 함) |
| 2026-09-25 | 호출어는 단어별로 다른 동작에 매핑 (local-wake가 단어마다 콜백 등록 가능한 구조) | 1단계는 "자비스"(받아쓰기 시작) + "그만"(현재 작업 중단)만. 오탐 증가·온보딩(단어별 목소리 녹음) 부담 때문에 더 늘리지 않고 실사용 후 필요하면 추가 |
| 2026-09-25 | (환경 이슈) 이 PC의 Kaspersky 백신이 HTTPS를 자체 루트 인증서로 재서명(SSL 검사)해서 pip 설치가 `CERTIFICATE_VERIFY_FAILED`로 실패 | 원인: pip은 Windows 인증서 저장소가 아니라 자체 certifi 번들을 씀. 해결: Kaspersky 루트 인증서를 Windows 저장소에서 내보내 PEM 변환 후 `.venv/Lib/site-packages/pip/_vendor/certifi/cacert.pem`에 추가(가상환경 국한, 시스템 미변경). **setup 스크립트 작성 시 이 우회를 자동화해야 함** — 다른 Kaspersky 사용자도 같은 문제를 겪을 것 |
| 2026-09-25 | ~~TTS: MeloTTS 하나로 다국어 통일~~ → **언어별로 다른 TTS 엔진 연결(A안)** | 실측 결과 MeloTTS는 언어마다 무거운 컴파일 의존성 요구(한국어=eunjeon/mecab, 일본어=fugashi/mecab, 중국어=jieba 등) — 이 PC(C++ 컴파일러 없음)에서 한국어 경로(`eunjeon`)가 사전빌드 wheel이 없어 설치 실패, Visual C++ Build Tools 필요. 이걸 전세계 사용자에게 요구하는 건 접근성 도구의 진입장벽을 크게 높임. 게다가 MeloTTS-Korean 모델은 한국어 전용 학습이라 **영어 텍스트를 한국어 발음으로 억지로 읽음**(korean.py의 normalize_english가 44개 사전 단어만 한글 치환, 나머지는 알파벳 그대로 남아 한국어 음소로 어색하게 발음됨) — 애초에 다국어 겸용이 코드 구조상 불가능했음 |
| 2026-09-25 | 한국어 TTS는 MeloTTS-Korean 유지, eunjeon 설치 문제는 별도 해결 필요(미해결) | Kokoro(한국어 미지원), Piper(한국어 비공식 커뮤니티 모델뿐)도 조사했지만 한국어 품질/공식성에서 MeloTTS가 나음. eunjeon 컴파일 문제는 Visual Studio Build Tools 설치 또는 다른 mecab 대체제로 해결 필요 — 다음 세션 과제 |
