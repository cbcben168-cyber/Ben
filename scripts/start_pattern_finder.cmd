@echo off
setlocal
for %%I in ("%~dp0..") do set "REPO=%%~fI"
if not exist "%REPO%\app\Home.py" (
  echo [ERROR] Pattern Finder repository was not found: %REPO%
  pause
  exit /b 2
)
if not exist "%REPO%\.venv\Scripts\python.exe" (
  echo [ERROR] Missing virtual environment: %REPO%\.venv
  echo Run: py -m venv .venv ^&^& .venv\Scripts\python -m pip install -r requirements.txt
  pause
  exit /b 3
)
set "PYTHONPATH=%REPO%\src"
set "PATTERN_FINDER_REPOSITORY_ROOT=%REPO%"
"%REPO%\.venv\Scripts\python.exe" -m tv_quant.pattern_finder.runtime start
if errorlevel 1 pause
