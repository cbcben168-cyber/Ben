param([int]$Port = 8765, [string]$PythonPath = '')
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
if (-not $PythonPath) {
    $PythonPath = Join-Path $ProjectRoot '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $PythonPath)) {
        $PythonPath = 'C:\Users\cbcbe\Documents\ChatGPT\Futu\spy_intraday_research\.venv\Scripts\python.exe'
    }
}
if (-not (Test-Path -LiteralPath $PythonPath)) { throw 'Python runtime unavailable; specify -PythonPath.' }
$PreviousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $ProjectRoot 'src'
    & $PythonPath -m es_mes.dashboard --root $ProjectRoot --port $Port
} finally { $env:PYTHONPATH = $PreviousPythonPath }
