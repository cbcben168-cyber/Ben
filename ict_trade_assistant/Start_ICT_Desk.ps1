$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot 'data') -Force | Out-Null
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $taskPython)) {
    $taskPython = Join-Path (Split-Path $PSScriptRoot -Parent) 'ict_trade_assistant\.venv\Scripts\python.exe'
}
if (!(Test-Path -LiteralPath $taskPython)) {
    throw 'Missing existing Python environment. No environment was changed.'
}
& $taskPython -c 'import streamlit, pandas, plotly, futu'
if ($LASTEXITCODE -ne 0) {
    throw 'Existing dependencies unavailable. No packages were changed.'
}
$taskPort = 8506
$env:ICT_V04_HISTORY = Join-Path $PSScriptRoot 'data\v04\history.json'
$env:ICT_V04_DB = Join-Path $PSScriptRoot 'data\v04\desk.sqlite3'
if (!(Test-Path -LiteralPath $env:ICT_V04_HISTORY)) { throw 'Missing saved history; no OpenD fallback.' }
if (Get-NetTCPConnection -LocalPort $taskPort -State Listen -ErrorAction SilentlyContinue) {
    $taskRuntime = Join-Path $PSScriptRoot 'data\runtime-8506.json'
    if (Test-Path -LiteralPath $taskRuntime) {
        $taskInfo = Get-Content -LiteralPath $taskRuntime -Raw | ConvertFrom-Json
        $taskListener = Get-NetTCPConnection -LocalPort $taskPort -State Listen
        if ($taskInfo.root -eq $PSScriptRoot -and $taskInfo.pid -in $taskListener.OwningProcess) {
            Start-Process 'http://127.0.0.1:8506'
            exit 0
        }
    }
    throw '隔离端口 8506 已被占用；请核对v0.4服务，勿关闭v0.3。'
}
$taskProcess = Start-Process -FilePath $taskPython -ArgumentList @('scripts/run_server.py', '--history') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput 'data\streamlit-out.log' -RedirectStandardError 'data\streamlit-error.log'
$taskReady = $false
for ($taskIndex = 0; $taskIndex -lt 60; $taskIndex++) {
    if ($taskProcess.HasExited) { throw '看板已退出，请检查日志 data\streamlit-error.log.' }
    try {
        $taskResponse = Invoke-WebRequest 'http://127.0.0.1:8506/_stcore/health' -UseBasicParsing -TimeoutSec 1
        if ($taskResponse.StatusCode -eq 200) { $taskReady = $true; break }
    } catch { }
    Start-Sleep -Milliseconds 500
}
if (!$taskReady) { throw '看板启动超时，请检查 data 目录中的日志。' }
Start-Process 'http://127.0.0.1:8506'
Write-Host "ICT 交易工作台已启动（进程编号 $($taskProcess.Id)). ）。停止命令：Stop-Process -Id $($taskProcess.Id)."
