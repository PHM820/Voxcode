@echo off
REM Project health check - run by /delegate judge and before reporting work as done.
setlocal

set VENV_PY=.venv\Scripts\python.exe
if not exist "%VENV_PY%" set VENV_PY=.venv_sherpa_test\Scripts\python.exe

if not exist "%VENV_PY%" (
    echo VERIFY SKIPPED: no venv found - run setup.cmd first
    exit /b 3
)

echo === voice/listener.py syntax + import check ===
"%VENV_PY%" -c "import sys; sys.path.insert(0, '.'); import voice.listener; import voice.tts; import voice.config; import voice.languages; import voice.stt; import voice.vad; import voice.wakeword; import voice.judge; import voice.record; import voice.manager; import voice.hooks_install; import voice.control; print('import OK')"
if errorlevel 1 (
    echo VERIFY FAILED: import error
    exit /b 1
)

echo === voice/listener.py routing unit checks (no audio, no TCP) ===
"%VENV_PY%" .claude\verify_routing.py
if errorlevel 1 (
    echo VERIFY FAILED: routing logic
    exit /b 1
)

echo === voice/judge.py command judge checks (no network) ===
"%VENV_PY%" .claude\verify_judge.py
if errorlevel 1 (
    echo VERIFY FAILED: judge logic
    exit /b 1
)

echo === voice/manager.py sub-manager + stage 3 command checks (no claude, no node) ===
"%VENV_PY%" .claude\verify_manager.py
if errorlevel 1 (
    echo VERIFY FAILED: manager logic
    exit /b 1
)

echo === stage 4: inbox, global hook install, on/off (temp folders only) ===
"%VENV_PY%" .claude\verify_control.py
if errorlevel 1 (
    echo VERIFY FAILED: control logic
    exit /b 1
)

echo === node inject.js syntax check ===
node --check voice\inject.js
if errorlevel 1 (
    echo VERIFY FAILED: inject.js syntax
    exit /b 1
)

echo === hooks/on-stop.py, hooks/on-notification.py syntax + import check ===
REM NOTE: giving the hook stdin via pipe/redirect directly in this batch file
REM broke execution silently past this point (found 2026-09-27). Moved to a
REM separate .py file that uses subprocess instead - see verify_hooks.py.
"%VENV_PY%" .claude\verify_hooks.py
if errorlevel 1 (
    echo VERIFY FAILED: hooks check failed
    exit /b 1
)

echo ALL CHECKS PASSED
exit /b 0
