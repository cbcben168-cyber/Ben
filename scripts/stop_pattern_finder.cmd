@echo off
setlocal
for %%I in ("%~dp0..") do set "REPO=%%~fI"
set "PYTHONPATH=%REPO%\src"
set "PATTERN_FINDER_REPOSITORY_ROOT=%REPO%"
"%REPO%\.venv\Scripts\python.exe" -m tv_quant.pattern_finder.runtime stop
if errorlevel 1 pause
