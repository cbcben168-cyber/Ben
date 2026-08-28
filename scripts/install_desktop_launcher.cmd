@echo off
setlocal EnableExtensions
for %%I in ("%~dp0..") do set "REPO=%%~fI"
set "PATTERN_FINDER_INSTALL_REPO=%REPO%"
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$desktop=[Environment]::GetFolderPath('Desktop'); if ([string]::IsNullOrWhiteSpace($desktop)) { $desktop=Join-Path $env:USERPROFILE 'Desktop' }; $null=[IO.Directory]::CreateDirectory($desktop); $name=''; foreach ($code in @(0x004B,0x7EBF,0x5F62,0x6001,0x7814,0x7A76,0x7CFB,0x7EDF)) { $name += [char]$code }; $target=Join-Path $desktop ($name + '.cmd'); $quote=[char]34; $newline=[Environment]::NewLine; $content='@echo off'+$newline+'chcp 65001 >nul'+$newline+'call '+$quote+$env:PATTERN_FINDER_INSTALL_REPO+'\scripts\start_pattern_finder.cmd'+$quote+$newline; [IO.File]::WriteAllText($target,$content,[Text.UTF8Encoding]::new($false)); Write-Output ('Installed Desktop launcher: ' + $target)"
exit /b %errorlevel%
