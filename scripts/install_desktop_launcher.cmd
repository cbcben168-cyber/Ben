@echo off
setlocal EnableExtensions
for %%I in ("%~dp0..") do set "REPO=%%~fI"
for /f "usebackq delims=" %%D in (`powershell.exe -NoProfile -NonInteractive -Command "[Environment]::GetFolderPath('Desktop')"`) do set "DESKTOP=%%D"
if not defined DESKTOP set "DESKTOP=%USERPROFILE%\Desktop"
if not exist "%DESKTOP%" mkdir "%DESKTOP%"
set "TARGET=%DESKTOP%\K线形态研究系统.cmd"
>"%TARGET%" echo @echo off
>>"%TARGET%" echo call "%REPO%\scripts\start_pattern_finder.cmd"
echo Installed Desktop launcher: %TARGET%
