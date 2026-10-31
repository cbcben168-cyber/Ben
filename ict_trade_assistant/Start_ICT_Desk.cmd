@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start_ICT_Desk.ps1"
if errorlevel 1 pause
