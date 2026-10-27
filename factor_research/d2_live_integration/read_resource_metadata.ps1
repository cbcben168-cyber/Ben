param([Parameter(Mandatory=$true)][string]$OutputPath,[Parameter(Mandatory=$true)][int]$OwnerPid)
$ErrorActionPreference='Stop'
function Hash-Text([string]$value){$h=[System.Security.Cryptography.SHA256]::Create();try{([BitConverter]::ToString($h.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($value)))).Replace('-','').ToLowerInvariant()}finally{$h.Dispose()}}
$started=[DateTimeOffset]::UtcNow.ToString('o')
$snapshot=[ordered]@{schema='D2_RESOURCE_OS_SNAPSHOT_V1';observed_at_utc=$started;owner_pid=$OwnerPid;coverage_complete=$false}
function Progress([string]$stage){$line=(@{stage=$stage;utc=[DateTimeOffset]::UtcNow.ToString('o')}|ConvertTo-Json -Compress)+"`n";$f=[System.IO.File]::Open($OutputPath+'.progress.jsonl',[System.IO.FileMode]::Append,[System.IO.FileAccess]::Write);try{$b=[System.Text.Encoding]::UTF8.GetBytes($line);$f.Write($b,0,$b.Length);$f.Flush($true)}finally{$f.Dispose()}}
try {
  $stage='TASK_INVENTORY';Progress $stage
  $all=@(Get-ScheduledTask);$inventory=@();$relevant=@()
  foreach($task in $all){
    $actionText=@($task.Actions|ForEach-Object {([string]$_.Execute)+"`n"+([string]$_.Arguments)+"`n"+([string]$_.WorkingDirectory)}) -join "`n"
    $inventory+=@{key=$task.TaskPath+$task.TaskName;enabled=$task.Settings.Enabled;state=[string]$task.State;action_sha256=(Hash-Text $actionText)}
    $candidate=($task.TaskName -match 'FUTU|OpenD|TradingCodex|SPY|Clock' -or $actionText -match 'FUTU|OpenD|TradingCodex|python|powershell|pwsh|cmd.exe|wscript|cscript')
    if($candidate){
      $xml=Export-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath
      $triggers=@($task.Triggers|ForEach-Object {@{type=$_.CimClass.CimClassName;enabled=$_.Enabled;start=$_.StartBoundary;end=$_.EndBoundary;repeat=$_.Repetition.Interval}})
      $relevant+=@{key=$task.TaskPath+$task.TaskName;state=[string]$task.State;enabled=$task.Settings.Enabled;xml_sha256=(Hash-Text $xml);triggers=$triggers;start_when_available=$task.Settings.StartWhenAvailable;time_limit=$task.Settings.ExecutionTimeLimit;action_count=@($task.Actions).Count;action_sha256=(Hash-Text $actionText);allow_demand=$task.Settings.AllowDemandStart;restart_count=$task.Settings.RestartCount;multiple_instances=[int]$task.Settings.MultipleInstances;logon_mode=[string]$task.Principal.LogonType;run_level=[string]$task.Principal.RunLevel}
    }
  }
  $stage='PROCESS_INVENTORY';Progress $stage
  $processes=@(Get-CimInstance Win32_Process|ForEach-Object {@{pid=[int]$_.ProcessId;parent_pid=[int]$_.ParentProcessId;name=[string]$_.Name;image_path=[string]$_.ExecutablePath}})
  $stage='TCP_INVENTORY';Progress $stage
  # Every client of the fixed local endpoint has a corresponding server-side row.
  $tcp=@(Get-NetTCPConnection -LocalPort 11111)
  $loop=@('127.0.0.1','::1')
  $listeners=@($tcp|Where-Object {$_.State -eq 'Listen' -and $_.LocalPort -eq 11111 -and $_.LocalAddress -in $loop}|ForEach-Object {@{pid=[int]$_.OwningProcess;address=$_.LocalAddress;port=$_.LocalPort}})
  $clients=@($tcp|Where-Object {$_.State -eq 'Established' -and $_.LocalPort -eq 11111 -and $_.LocalAddress -in $loop}|ForEach-Object {@{server_pid=[int]$_.OwningProcess;local_port=$_.LocalPort;remote_port=$_.RemotePort}})
  # The parent binds each listener PID to its image with QUERY_LIMITED_INFORMATION.
  $stage='SERVER_IDENTITY_HANDOFF';Progress $stage
  $snapshot.all_task_inventory=$inventory;$snapshot.relevant_tasks=$relevant;$snapshot.processes=$processes;$snapshot.listeners=$listeners;$snapshot.clients=$clients
  $snapshot.timezone_id=(Get-TimeZone).Id;$snapshot.local_offset_minutes=[int][TimeZoneInfo]::Local.GetUtcOffset([DateTime]::Now).TotalMinutes
  $snapshot.coverage_complete=$true
} catch {$snapshot.error_code='WINDOWS_METADATA_QUERY_FAILED';$snapshot.error_stage=$stage;$snapshot.error_hresult=$_.Exception.HResult}
$snapshot.completed_at_utc=[DateTimeOffset]::UtcNow.ToString('o')
$json=$snapshot|ConvertTo-Json -Depth 9 -Compress
$bytes=[System.Text.UTF8Encoding]::new($false).GetBytes($json)
if($bytes.Length -gt 393216){exit 3}
$stream=[System.IO.File]::Open($OutputPath,[System.IO.FileMode]::CreateNew,[System.IO.FileAccess]::Write)
try{$stream.Write($bytes,0,$bytes.Length);$stream.Flush($true)}finally{$stream.Dispose()}
if(-not $snapshot.coverage_complete){exit 2}
