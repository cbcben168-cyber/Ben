[CmdletBinding()]
param(
    [ValidateRange(1024,65535)][int]$Port = 8506,
    [string]$Python = '',
    [string]$Config = '',
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot 'data') -Force | Out-Null
$taskPython = if ($Python) { $Python } else { Join-Path $PSScriptRoot '.venv\Scripts\python.exe' }
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
$taskPort = $Port
if ($taskPort -eq 8501) { throw '禁止使用8501；请保留原服务。' }
$taskConfig = if ($Config) { (Resolve-Path -LiteralPath $Config).Path } else { Join-Path $PSScriptRoot 'data/history-runtime.json' }
$taskChecked = & $taskPython -X utf8 'scripts/run_server.py' --history --config $taskConfig --check-history-config --port $taskPort
if ($LASTEXITCODE -ne 0) { throw '历史配置校验失败，未启动服务；请核对 data/history-runtime.json。' }
$taskExpected = $taskChecked | ConvertFrom-Json
$taskUrl = "http://127.0.0.1:$taskPort"
$taskListener = Get-NetTCPConnection -LocalPort $taskPort -State Listen -ErrorAction SilentlyContinue
$taskExisting = $false
try { $taskExisting = (Invoke-WebRequest "$taskUrl/_stcore/health" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 } catch {}
if ($taskListener -or $taskExisting) {
    $taskRuntime = Join-Path $PSScriptRoot "data/runtime-$taskPort.json"
    if (Test-Path -LiteralPath $taskRuntime) {
        $taskInfo = Get-Content -LiteralPath $taskRuntime -Raw | ConvertFrom-Json
        $taskRunning = Get-Process -Id $taskInfo.pid -ErrorAction SilentlyContinue
        if ($taskInfo.root -eq $PSScriptRoot -and $taskInfo.port -eq $taskPort -and $taskRunning -and
            (!$taskListener -or $taskInfo.pid -in $taskListener.OwningProcess) -and
            ([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - $taskInfo.at) -lt 30) {
            if ($taskInfo.history_config_sha256 -ne $taskExpected.sha256) {
                throw '当前服务未加载本次历史配置；请按批准的部署流程重启，不能直接复用旧页面。'
            }
            if (!$NoBrowser) { Start-Process $taskUrl }
            exit 0
        }
    }
    throw "端口 $taskPort 已被占用；请核对服务，勿关闭其他进程。"
}
$taskArgs = @('-X','utf8','scripts/run_server.py','--history','--port',"$taskPort",'--config',('"'+$taskConfig+'"'))
$taskProcess = Start-Process -FilePath $taskPython -ArgumentList $taskArgs -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "data/streamlit-$taskPort-out.log" -RedirectStandardError "data/streamlit-$taskPort-error.log"
$taskReady = $false
for ($taskIndex = 0; $taskIndex -lt 60; $taskIndex++) {
    if ($taskProcess.HasExited) { throw "看板已退出，请检查 data/streamlit-$taskPort-error.log。" }
    try {
        $taskResponse = Invoke-WebRequest "$taskUrl/_stcore/health" -UseBasicParsing -TimeoutSec 1
        if ($taskResponse.StatusCode -eq 200) { $taskReady = $true; break }
    } catch { }
    Start-Sleep -Milliseconds 500
}
if (!$taskReady) { throw '看板启动超时，请检查 data 目录中的日志。' }
$taskStarted = Get-Content -LiteralPath (Join-Path $PSScriptRoot "data/runtime-$taskPort.json") -Raw | ConvertFrom-Json
if ($taskStarted.root -ne $PSScriptRoot -or $taskStarted.history_config_sha256 -ne $taskExpected.sha256) {
    throw '启动后的服务身份或历史配置不符，请检查隔离日志。'
}
if (!$NoBrowser) { Start-Process $taskUrl }
Write-Host "ICT 交易工作台已启动：$taskUrl；服务进程 $($taskStarted.pid)，启动进程 $($taskProcess.Id)。历史路径已从持久化配置恢复。"
