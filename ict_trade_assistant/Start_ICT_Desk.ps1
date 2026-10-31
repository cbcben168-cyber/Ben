$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot 'data') -Force | Out-Null
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $taskPython)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw '需要安装 Python 3.11 或更高版本。' }
}
if (!(Test-Path -LiteralPath (Join-Path $PSScriptRoot '.venv\desk-ready'))) {
    & $taskPython -m pip install -r requirements-lock.txt
    if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请检查网络及安装日志。' }
    New-Item -ItemType File -Path '.venv\desk-ready' -Force | Out-Null
}
$taskPort = 8501
if (Get-NetTCPConnection -LocalPort $taskPort -State Listen -ErrorAction SilentlyContinue) {
    throw '端口 8501 已被占用，请先关闭现有看板或冲突服务。'
}
$taskProcess = Start-Process -FilePath $taskPython -ArgumentList @('scripts/run_server.py') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput 'data\streamlit-out.log' -RedirectStandardError 'data\streamlit-error.log'
$taskReady = $false
for ($taskIndex = 0; $taskIndex -lt 60; $taskIndex++) {
    if ($taskProcess.HasExited) { throw '看板已退出，请检查日志 data\streamlit-error.log.' }
    try {
        $taskResponse = Invoke-WebRequest 'http://127.0.0.1:8501/_stcore/health' -UseBasicParsing -TimeoutSec 1
        if ($taskResponse.StatusCode -eq 200) { $taskReady = $true; break }
    } catch { }
    Start-Sleep -Milliseconds 500
}
if (!$taskReady) { throw '看板启动超时，请检查 data 目录中的日志。' }
Start-Process 'http://127.0.0.1:8501'
Write-Host "ICT 交易工作台已启动（进程编号 $($taskProcess.Id)). ）。停止命令：Stop-Process -Id $($taskProcess.Id)."
