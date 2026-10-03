param([switch]$Once, [int]$MaxCycles = 0)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Project virtual environment is missing; follow the runbook.' }
$taskPreviousPath = $env:PYTHONPATH
Push-Location $taskRoot
try {
    $env:PYTHONPATH = Join-Path $taskRoot 'src'
    $taskArguments = @('-m', 'spy_research.cli', 'paper', '--version', 'diagnostic_v2')
    if ($Once) { $taskArguments += '--once' }
    if ($MaxCycles -gt 0) { $taskArguments += @('--max-cycles', "$MaxCycles") }
    & $taskPython @taskArguments
    if ($LASTEXITCODE -ne 0) { throw 'Shadow runner failed; inspect local logs/workflow.' }
} finally {
    $env:PYTHONPATH = $taskPreviousPath
    Pop-Location
}
