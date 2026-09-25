@echo off
REM eyes-free-coding installer.
REM What this does: create venv, install Python deps, download TTS/STT models.
REM Known issues this script does NOT auto-fix (see docs/known-issues.md #1):
REM   pip SSL certificate errors caused by antivirus SSL inspection (Kaspersky etc).
REM   If pip install fails below, this script prints the manual fix and stops.
setlocal enabledelayedexpansion

set VENV_DIR=.venv
set MODELS_DIR=models
set TTS_MODEL_DIR=%MODELS_DIR%\tts\vits-mimic3-ko_KO-kss_low
set TTS_MODEL_URL=https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-mimic3-ko_KO-kss_low.tar.bz2
set STT_MODEL_DIR=%MODELS_DIR%\stt
set STT_MODEL_URL=https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin

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

echo === 3/4: TTS model (Korean, ~64MB) ===
if exist "%TTS_MODEL_DIR%\ko_KO-kss_low.onnx" (
    echo Already downloaded: %TTS_MODEL_DIR%
) else (
    if not exist "%MODELS_DIR%\tts" mkdir "%MODELS_DIR%\tts"
    echo Downloading %TTS_MODEL_URL%
    "%VENV_PY%" -c "import urllib.request; urllib.request.urlretrieve('%TTS_MODEL_URL%', 'models/tts/_tts.tar.bz2')"
    if errorlevel 1 (
        echo SETUP FAILED: TTS model download failed. Check your internet connection
        echo and retry, or download manually from:
        echo   %TTS_MODEL_URL%
        exit /b 1
    )
    "%VENV_PY%" -c "import tarfile; tarfile.open('models/tts/_tts.tar.bz2').extractall('models/tts')"
    del "models\tts\_tts.tar.bz2"
    if not exist "%TTS_MODEL_DIR%\ko_KO-kss_low.onnx" (
        echo SETUP FAILED: TTS model extracted but expected file not found:
        echo   %TTS_MODEL_DIR%\ko_KO-kss_low.onnx
        echo The archive layout may have changed upstream - check %MODELS_DIR%\tts manually.
        exit /b 1
    )
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
echo Wake-word onboarding and voice/vad.py, voice/wakeword.py, voice/stt.py are not
echo built yet - see docs/architecture.md ("Implementation status" section) for scope.
exit /b 0
