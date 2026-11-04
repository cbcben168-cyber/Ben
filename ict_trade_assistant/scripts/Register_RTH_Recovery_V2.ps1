param([switch]$DeploymentTest)
$ErrorActionPreference='Stop'
$taskRoot='C:\Users\cbcbe\TradingCodex\ict_trade_assistant'
$taskEvidence=Join-Path $taskRoot 'data\rth_recovery_v2\deployment_20261103'
$taskName='ICT_DESK_RTH_ACCEPTANCE_20261103'+$(if($DeploymentTest){'_REPAIR_TEST'}else{''})
$taskAccount=[Security.Principal.WindowsIdentity]::GetCurrent().Name
$taskDesktopUser=(Get-CimInstance Win32_ComputerSystem).UserName
try{
    if($taskDesktopUser -ine $taskAccount){throw 'INTERACTIVE_LOGIN_SESSION_NOT_CONFIRMED'}
    $taskGate=Get-Content -LiteralPath (Join-Path $taskEvidence 'P3_GATE.json') -Raw | ConvertFrom-Json
    if(!$taskGate.suite_passed -or !$taskGate.matrix_A_H_passed){throw 'P3_NOT_PASSED'}
    foreach($taskFile in $taskGate.tested_files.PSObject.Properties){
        if((Get-FileHash -LiteralPath (Join-Path $taskRoot $taskFile.Name) -Algorithm SHA256).Hash.ToLower() -ne $taskFile.Value){throw 'TESTED_CODE_DRIFT'}
    }
    if(!$DeploymentTest){
        $taskProof=Get-Content -LiteralPath (Join-Path $taskEvidence 'DRY_RUN_VERIFIED.json') -Raw | ConvertFrom-Json
        if(!$taskProof.success){throw 'DRY_RUN_NOT_PASSED'}
        foreach($taskFile in $taskProof.tested_files.PSObject.Properties){
            if((Get-FileHash -LiteralPath (Join-Path $taskRoot $taskFile.Name) -Algorithm SHA256).Hash.ToLower() -ne $taskFile.Value){throw 'DRY_RUN_CODE_DRIFT'}
        }
    }
    if(Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue){throw 'TASK_ALREADY_EXISTS_NO_OVERWRITE'}
    $taskLocal=[TimeZoneInfo]::ConvertTime([DateTimeOffset]::Parse('2026-11-03T22:15:00+08:00'),[TimeZoneInfo]::Local).DateTime
    if($DeploymentTest){$taskLocal=(Get-Date).AddMinutes(1)}
    $taskArgs='-NoProfile -NonInteractive -WindowStyle Hidden -File "'+$taskRoot+'\scripts\Run_RTH_Recovery_V2.ps1"'
    if($DeploymentTest){$taskArgs+=' -DryRun -Probe -OutputPath "'+$taskEvidence+'\scheduled-dry-run"'}
    $taskAction=New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument $taskArgs -WorkingDirectory $taskRoot
    $taskTrigger=New-ScheduledTaskTrigger -Once -At $taskLocal
    $taskTrigger.EndBoundary=$(if($DeploymentTest){$taskLocal.AddMinutes(10)}else{[TimeZoneInfo]::ConvertTime([DateTimeOffset]::Parse('2026-11-04T05:10:00+08:00'),[TimeZoneInfo]::Local).DateTime}).ToString('s')
    $taskPrincipal=New-ScheduledTaskPrincipal -UserId $taskAccount -LogonType Interactive -RunLevel Limited
    $taskLimit=if($DeploymentTest){New-TimeSpan -Minutes 5}else{New-TimeSpan -Hours 6 -Minutes 55}
    $taskSettings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit $taskLimit
    $taskDefinition=New-ScheduledTask -Action $taskAction -Trigger $taskTrigger -Principal $taskPrincipal -Settings $taskSettings -Description 'RTH恢复控制器v2；冻结v0.3只读行情；分钟契约未决，ICT关闭'
    Register-ScheduledTask -TaskName $taskName -InputObject $taskDefinition | Out-Null
    $task=Get-ScheduledTask -TaskName $taskName;$taskInfo=Get-ScheduledTaskInfo -TaskName $taskName
    Export-ScheduledTask -TaskName $taskName | Set-Content -LiteralPath (Join-Path $taskEvidence ($taskName+'.xml')) -Encoding UTF8
    $taskResult=@{status='REGISTERED_SESSION_REQUIRED';name=$taskName;account=$taskAccount;confirmed_desktop_user=$taskDesktopUser;logon=$task.Principal.LogonType.ToString();run_level=$task.Principal.RunLevel.ToString();state=$task.State.ToString();trigger=$task.Triggers[0].StartBoundary;windows_timezone=[TimeZoneInfo]::Local.Id;next_run=$taskInfo.NextRunTime.ToString('o');last_result=$taskInfo.LastTaskResult;execute=$task.Actions[0].Execute;arguments=$task.Actions[0].Arguments;working_directory=$task.Actions[0].WorkingDirectory;multiple_instances=$task.Settings.MultipleInstances.ToString();execution_limit=$task.Settings.ExecutionTimeLimit}
}catch{
    $taskResult=@{status='AUTOMATION_NOT_ARMED';name=$taskName;account=$taskAccount;error=$_.Exception.Message}
}
$taskResult | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $taskEvidence ($taskName+'-readback.json')) -Encoding UTF8
$taskResult | ConvertTo-Json -Depth 6
if($taskResult.status -eq 'AUTOMATION_NOT_ARMED'){exit 2}
