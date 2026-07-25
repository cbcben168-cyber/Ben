[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$StrategyConfig,
    [switch]$AuditOnly,
    [switch]$SkipDataRefresh,
    [switch]$SmokeTestData,
    [string]$DataRoot = "data/raw",
    [string]$ReportRoot = "reports/runs",
    [string]$RunDirectory
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location -LiteralPath $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $pythonCommand = Get-Command python -ErrorAction Stop
    $python = $pythonCommand.Source
}

$arguments = @(
    "-m", "tv_quant.pipeline_cli",
    "--strategy-config", $StrategyConfig,
    "--data-root", $DataRoot,
    "--report-root", $ReportRoot
)
if ($AuditOnly) { $arguments += "--audit-only" }
if ($SkipDataRefresh) { $arguments += "--skip-data-refresh" }
if ($SmokeTestData) { $arguments += "--smoke-test-data" }
if ($RunDirectory) { $arguments += @("--run-directory", $RunDirectory) }

$env:PYTHONPATH = Join-Path $root "src"
& $python @arguments
exit $LASTEXITCODE
