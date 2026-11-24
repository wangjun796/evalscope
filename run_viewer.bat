@echo off
setlocal
cd /d %~dp0
set "PY="

rem 1) prefer evalscope offline venv (../.venv or ./venv)
if exist "..\.venv\Scripts\python.exe" set "PY=..\.venv\Scripts\python.exe"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

rem 2) if venv python lacks pyarrow, fall back to system python
if defined PY "%PY%" -c "import pyarrow" >nul 2>nul && goto run
set "PY=python"
python -c "import pyarrow" >nul 2>nul && goto run

rem 3) no pyarrow anywhere: create a dedicated venv and install offline from wheels\
echo [arrow-viewer] pyarrow not found, creating .venv and installing offline wheels...
py -3.11 -m venv .venv 2>nul || python -m venv .venv
if not exist ".venv\Scripts\python.exe" (
  echo [arrow-viewer] ERROR: python 3.11 not found. Run install_windows.bat first or install Python 3.11.
  exit /b 1
)
set "PY=.venv\Scripts\python.exe"
"%PY%" -m pip install --no-index --find-links wheels pyarrow || (
  echo [arrow-viewer] ERROR: offline install failed.
  exit /b 1
)

:run
echo [arrow-viewer] using %PY%
echo [arrow-viewer] open http://127.0.0.1:8765  (Ctrl+C to stop)
"%PY%" arrow_viewer.py %*
