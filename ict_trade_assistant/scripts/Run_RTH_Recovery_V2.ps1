param([switch]$DryRun,[string]$OutputPath,[switch]$Probe)
$ErrorActionPreference='Stop'
$taskRoot='C:\Users\cbcbe\TradingCodex\ict_trade_assistant'
Set-Location -LiteralPath $taskRoot
$taskArguments=@('-u','scripts/rth_recovery_v2.py','--date','2026-11-03')
if($DryRun){
    if(!$OutputPath){throw 'Dry Run需要独立目录'}
    $taskArguments+=@('--dry-run','--output',$OutputPath)
    if($Probe){$taskArguments+='--probe'}
}else{
    $taskArguments+='--live'
    $OutputPath=Join-Path $taskRoot 'data\live_rth_acceptance\20261103'
}
New-Item -ItemType Directory -Path $OutputPath -Force | Out-Null
# 每个启动日志独立命名；重复启动不覆盖运行中或已完成证据。
$taskAttempt=[Guid]::NewGuid().ToString('N')
try{
    $taskQuoted=$taskArguments | ForEach-Object {'"'+$_+'"'}
    $taskProcess=Start-Process -FilePath (Join-Path $taskRoot '.venv\Scripts\python.exe') -ArgumentList $taskQuoted -WorkingDirectory $taskRoot -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput (Join-Path $OutputPath ('entry-'+$taskAttempt+'.log')) -RedirectStandardError (Join-Path $OutputPath ('entry-'+$taskAttempt+'-error.log'))
    $taskExit=$taskProcess.ExitCode
}catch{
    $taskExit=3
    @{at=[DateTimeOffset]::Now.ToString('o');status='BLOCKED';code='ENTRY_BOOTSTRAP_FAILED';error=$_.Exception.Message} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $OutputPath ('bootstrap-'+$taskAttempt+'.json')) -Encoding UTF8
}
if($taskExit -notin @(0,9,10) -and !(Test-Path -LiteralPath (Join-Path $OutputPath 'SUMMARY.json'))){
    @{status='BLOCKED';version='RTH_RECOVERY_V2_20261103';real_rth_samples=0;simulated=[bool]$DryRun;exit_code=$taskExit;reason='入口未完成报告，详见独立启动错误日志';ict_realtime=$false} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $OutputPath 'SUMMARY.json') -Encoding UTF8
    @('【当前阶段】自动入口阻断','【执行状态】BLOCKED','【已完成】启动日志已保存。','【测试与证据】无可授予资格的实时样本。','【存在问题】入口异常，检查bootstrap及entry错误日志。','【下一步】不停止8501或OpenD；实时ICT保持关闭。') | Set-Content -LiteralPath (Join-Path $OutputPath 'FINAL_REPORT.md') -Encoding UTF8
}
exit $taskExit
