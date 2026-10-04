param([string]$PythonPath = '')
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
if (-not $PythonPath) {
    $localPython = Join-Path $project '.venv\Scripts\python.exe'
    $futuPython = 'C:\Users\cbcbe\Documents\ChatGPT\Futu\spy_intraday_research\.venv\Scripts\python.exe'
    $PythonPath = if (Test-Path -LiteralPath $localPython) { $localPython } else { $futuPython }
}
if (-not (Test-Path -LiteralPath $PythonPath)) { throw 'Project Python unavailable; pass -PythonPath.' }
$previousPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $project 'src'
    Write-Host 'ES/MES research selector — no orders; no automatic strategy start'
    Write-Host '0 = Disabled, 1 = ES, 2 = MES, 3 = Both'
    $answer = Read-Host 'Select'
    $choices = @{ '0'='none'; '1'='ES'; '2'='MES'; '3'='both' }
    if (-not $choices.ContainsKey($answer)) { throw 'Invalid choice; no setting changed.' }
    & $PythonPath -W once::DeprecationWarning -m es_mes.cli select --root $project --choice $choices[$answer]
    if ($LASTEXITCODE -ne 0) { throw 'Selection failed.' }
    & $PythonPath -m es_mes.cli status --root $project
} finally { $env:PYTHONPATH = $previousPath }
