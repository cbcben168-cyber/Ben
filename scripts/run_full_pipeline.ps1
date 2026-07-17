[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

New-Item -ItemType Directory -Force 'logs', 'reports', 'data\raw' | Out-Null
$logFile = Join-Path $root 'logs\full_pipeline.log'
Start-Transcript -Path $logFile -Append | Out-Null
try {
    $python = Join-Path $root '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        $bootstrap = Get-Command python -ErrorAction Stop
        & $bootstrap.Source -m venv (Join-Path $root '.venv')
    }
    if (-not (Test-Path -LiteralPath $python)) { throw 'Unable to create project virtual environment.' }

    $env:PYTHONPATH = (Join-Path $root 'src')
    # Futu SDK always writes a client log below APPDATA; keep it project-local.
    $env:APPDATA = (Join-Path $root 'logs\futu_sdk_appdata')
    New-Item -ItemType Directory -Force $env:APPDATA | Out-Null

    & $python -m pip install --upgrade pip
    & $python -m pip install -r requirements.txt
    & $python -c "import pandas, numpy, pytest, yfinance, futu; print('Dependency imports verified')"
    if ($LASTEXITCODE -ne 0) { throw 'Dependency import verification failed.' }

    & $python -m tv_quant.cli download --tickers SPY QQQ --out-dir data\raw
    if ($LASTEXITCODE -ne 0) { throw 'Futu daily download failed.' }

    $baseTemp = Join-Path $env:LOCALAPPDATA ('tv_quant_pytest_' + [guid]::NewGuid().ToString('N'))
    & $python -m pytest tests -q -p no:cacheprovider --basetemp="$baseTemp"
    $testExit = $LASTEXITCODE
    Remove-Item -LiteralPath $baseTemp -Recurse -Force -ErrorAction SilentlyContinue
    if ($testExit -ne 0) { throw "pytest failed with exit code $testExit." }

    foreach ($ticker in 'SPY', 'QQQ') {
        & $python -m tv_quant.cli backtest --input "data\raw\${ticker}_daily.csv" --out-dir "reports\$ticker" --initial-cash 100000 --commission-bps 1 --slippage-bps 2
        if ($LASTEXITCODE -ne 0) { throw "$ticker backtest failed." }
    }

    $rows = foreach ($ticker in 'SPY', 'QQQ') {
        $latest = Get-ChildItem -LiteralPath (Join-Path $root "reports\$ticker") -Directory | Sort-Object Name -Descending | Select-Object -First 1
        if ($null -eq $latest) { throw "No report directory found for $ticker." }
        $summaryPath = Join-Path $latest.FullName 'summary.json'
        $summary = Get-Content -Raw $summaryPath | ConvertFrom-Json
        $csv = Import-Csv (Join-Path $root "data\raw\${ticker}_daily.csv")
        [pscustomobject]@{
            ticker = $ticker; data_start_utc = $csv[0].timestamp_utc; data_end_utc = $csv[-1].timestamp_utc; data_rows = $csv.Count
            total_return = $summary.total_return; cagr = $summary.cagr; max_drawdown = $summary.max_drawdown; sharpe_ratio = $summary.sharpe_ratio
            trade_count = $summary.trade_count; win_rate = $summary.win_rate; buy_and_hold_return = $summary.buy_and_hold_return
            strategy_minus_buy_hold = ([double]$summary.total_return - [double]$summary.buy_and_hold_return)
            buy_and_hold_comparison = $summary.buy_and_hold_comparison
            commission_bps = 1; slippage_bps = 2; report_directory = $latest.FullName; pipeline_timestamp_utc = [DateTime]::UtcNow.ToString('o')
        }
    }
    $summaryJson = Join-Path $root 'reports\latest_pipeline_summary.json'
    $summaryCsv = Join-Path $root 'reports\latest_pipeline_summary.csv'
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($summaryJson, ($rows | ConvertTo-Json -Depth 4), $utf8NoBom)
    [System.IO.File]::WriteAllText($summaryCsv, (($rows | ConvertTo-Csv -NoTypeInformation) -join [Environment]::NewLine), $utf8NoBom)
    Write-Host "Pipeline complete: $summaryJson"
}
finally {
    Stop-Transcript | Out-Null
}
