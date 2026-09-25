@echo off
REM Project health check - run by /delegate judge and before reporting work as done.
setlocal

set VENV_PY=.venv_sherpa_test\Scripts\python.exe

if not exist "%VENV_PY%" (
    echo VERIFY SKIPPED: %VENV_PY% not found - run setup first
    exit /b 3
)

echo === voice/listener.py syntax + import check ===
"%VENV_PY%" -c "import sys; sys.path.insert(0, '.'); import voice.listener; import voice.tts; print('import OK')"
if errorlevel 1 (
    echo VERIFY FAILED: import error
    exit /b 1
)

echo === voice/listener.py routing unit checks (no audio, no TCP) ===
"%VENV_PY%" -c "import sys; sys.path.insert(0, '.'); from voice.listener import SessionTable, route_command, parse_stop_command; t=SessionTable(); t.upsert_from_notify('s1','proj-x','s1','tok1'); assert route_command(t,'anything').project_name=='proj-x'; assert parse_stop_command('멈춰')is None; assert parse_stop_command('멈춰 proj-x')=='proj-x'; print('routing checks OK')"
if errorlevel 1 (
    echo VERIFY FAILED: routing logic
    exit /b 1
)

echo === node inject.js syntax check ===
node --check voice\inject.js
if errorlevel 1 (
    echo VERIFY FAILED: inject.js syntax
    exit /b 1
)

echo ALL CHECKS PASSED
exit /b 0
