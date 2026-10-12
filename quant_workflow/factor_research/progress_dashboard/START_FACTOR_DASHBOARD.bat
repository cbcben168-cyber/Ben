@echo off
setlocal
cd /d "%~dp0\..\..\.."
py -3.14 -m quant_workflow.factor_research.progress_dashboard --port 8766
if errorlevel 1 (
  echo.
  echo Failed to start the dashboard. Review the error above.
  pause
)
endlocal
