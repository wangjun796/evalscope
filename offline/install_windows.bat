@echo off
REM EvalScope offline install (Windows x64 + Python 3.11)
REM Run this script from the "offline" directory on the intranet machine.
setlocal
set OFFLINE_DIR=%~dp0
set VENV_DIR=%OFFLINE_DIR%.venv

py -3.11 -m venv "%VENV_DIR%"
if errorlevel 1 (
    echo [ERROR] Failed to create venv. Make sure Python 3.11 is installed ("py -3.11 --version").
    exit /b 1
)

call "%VENV_DIR%\Scripts\activate.bat"

echo [1/2] Upgrading pip / setuptools / wheel from local wheels ...
python -m pip install --no-index --find-links "%OFFLINE_DIR%wheels" --upgrade pip setuptools wheel
if errorlevel 1 (
    echo [ERROR] pip bootstrap failed.
    exit /b 1
)

echo [2/2] Installing evalscope (core + perf + app + service) from local wheels ...
python -m pip install --no-index --find-links "%OFFLINE_DIR%wheels" "evalscope[perf,app,service]"
if errorlevel 1 (
    echo [ERROR] evalscope install failed.
    exit /b 1
)

echo.
echo Done. Verify with:  evalscope eval --model Qwen/Qwen2.5-0.5B-Instruct --datasets gsm8k --limit 1 --eval-type mock_llm
echo Activate later with:  "%VENV_DIR%\Scripts\activate"
