@echo off
REM Voxcode (formerly eyes-free-coding) installer.
REM What this does: create venv, install Python deps, download TTS/STT models.
REM Known issues this script does NOT auto-fix (see docs/known-issues.md #1):
REM   pip SSL certificate errors caused by antivirus SSL inspection (Kaspersky etc).
REM   If pip install fails below, this script prints the manual fix and stops.
setlocal enabledelayedexpansion

set VENV_DIR=.venv
set MODELS_DIR=models
set STT_MODEL_DIR=%MODELS_DIR%\stt
set STT_MODEL_URL=https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin
REM TTS 모델은 언어 선택에 따라 다르므로 하드코딩하지 않는다. setup.cmd 시점엔
REM 아직 /voice-on 온보딩(대화 언어 추천 방식, 2026-09-26 결정)을 거치지 않았으므로
REM 3/4 단계는 영어를 임시로 받아 둘 뿐 - 실제 사용 언어는 /voice-on 최초 실행 때
REM 확정되고, 그 스킬이 같은 다운로드 스크립트를 그 언어의 voice_id로 다시 호출한다
REM (voice/languages.py 참고).

echo === 1/4: Python venv ===
if exist "%VENV_DIR%\Scripts\python.exe" (
    echo Already exists: %VENV_DIR%
) else (
    python -m venv "%VENV_DIR%" || (
        echo SETUP FAILED: could not create venv. Is Python 3.12+ installed and on PATH?
        exit /b 1
    )
)
set VENV_PY=%VENV_DIR%\Scripts\python.exe

echo === 2/4: Python packages ===
"%VENV_PY%" -m pip install --upgrade pip >nul
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 goto :pip_failed
goto :pip_ok

:pip_failed
echo.
echo SETUP FAILED: pip install did not finish. If you see CERTIFICATE_VERIFY_FAILED
echo or SSLCertVerificationError above, this is almost always caused by antivirus
echo software (Kaspersky, ESET, Avast, ZScaler, Netskope, etc.^) intercepting HTTPS
echo with its own certificate ^(SSL inspection^), which pip does not trust by default.
echo.
echo Manual fix ^(see docs/known-issues.md #1 for full detail^):
echo   1. Export your antivirus's root certificate from the Windows certificate
echo      store ^(PowerShell: Cert:\LocalMachine\Root^) and convert it to PEM.
echo   2. Append that PEM to this venv's certifi bundle:
echo      %VENV_DIR%\Lib\site-packages\pip\_vendor\certifi\cacert.pem
echo      ^(and %VENV_DIR%\Lib\site-packages\certifi\cacert.pem if present^)
echo   3. Re-run this script.
echo   This only changes files inside %VENV_DIR% - nothing system-wide, and
echo   deleting %VENV_DIR% undoes it completely.
exit /b 1
:pip_ok

echo === 3/4: TTS model (default: English, ~64MB) ===
echo Other languages/voices are downloaded later by the /voice-on onboarding
echo (first run) - see voice\languages.py for the full list.
"%VENV_PY%" .claude\download_tts_model.py --language en
if errorlevel 1 (
    echo SETUP FAILED: see error above.
    exit /b 1
)

echo === 4/4: STT model (whisper.cpp base, ~147MB) ===
if exist "%STT_MODEL_DIR%\ggml-base.bin" (
    echo Already downloaded: %STT_MODEL_DIR%\ggml-base.bin
) else (
    if not exist "%STT_MODEL_DIR%" mkdir "%STT_MODEL_DIR%"
    echo Downloading %STT_MODEL_URL%
    "%VENV_PY%" -c "import urllib.request; urllib.request.urlretrieve('%STT_MODEL_URL%', 'models/stt/ggml-base.bin')"
    if errorlevel 1 (
        echo SETUP FAILED: STT model download failed. Check your internet connection
        echo and retry, or download manually from:
        echo   %STT_MODEL_URL%
        exit /b 1
    )
)

echo.
echo SETUP OK
echo Next: run .claude\verify.cmd to confirm everything imports correctly.
echo Then run /voice-on in Claude Code. For voice commands, record the wake word once:
echo   .venv\Scripts\python.exe -m voice.wakeword onboard
exit /b 0
