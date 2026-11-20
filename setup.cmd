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
set STT_MODEL_URL=https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin
REM TTS 모델(Supertonic 3)은 모든 언어·목소리가 한 벌을 같이 쓴다 - 언어는 /voice-on 최초
REM 실행 때 고르지만 받을 모델은 같으므로 여기서 미리 받는다 (voice/languages.py 참고).

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

echo === 3/4: TTS model (Supertonic 3, all languages, ~383MB) ===
"%VENV_PY%" .claude\download_tts_model.py
if errorlevel 1 (
    echo SETUP FAILED: see error above.
    exit /b 1
)

echo === 4/4: STT model (whisper.cpp small, ~488MB - also used to hear the wake word) ===
if exist "%STT_MODEL_DIR%\ggml-small.bin" (
    echo Already downloaded: %STT_MODEL_DIR%\ggml-small.bin
) else (
    if not exist "%STT_MODEL_DIR%" mkdir "%STT_MODEL_DIR%"
    echo Downloading %STT_MODEL_URL%
    "%VENV_PY%" -c "import urllib.request; urllib.request.urlretrieve('%STT_MODEL_URL%', 'models/stt/ggml-small.bin')"
    if errorlevel 1 (
        echo SETUP FAILED: STT model download failed. Check your internet connection
        echo and retry, or download manually from:
        echo   %STT_MODEL_URL%
        exit /b 1
    )
)

echo === Global /voice-on, /voice-off (usable from any project session) ===
"%VENV_PY%" -m voice.control install-skills
REM Undo: "%VENV_PY%" -m voice.control uninstall-skills

echo.
echo SETUP OK
echo Next: run .claude\verify.cmd to confirm everything imports correctly.
echo Then run /voice-on in Claude Code and say the wake word "Jarvis" to give a voice command.
exit /b 0
