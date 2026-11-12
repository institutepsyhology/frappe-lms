param(
    [Parameter(Mandatory = $true)][int]$ParentPid,
    [Parameter(Mandatory = $true)][int]$ChildPid,
    [switch]$CheckOnly,
    [switch]$Batch,
    [switch]$Pilot,
    [switch]$RequeueValidation
)
$ErrorActionPreference = 'Stop'
$parent = Get-CimInstance Win32_Process -Filter "ProcessId = $ParentPid"
$child = Get-CimInstance Win32_Process -Filter "ProcessId = $ChildPid"
if (-not $parent -or -not $child -or $child.ParentProcessId -ne $ParentPid -or
    $parent.CommandLine -notmatch 'run_background\.py.*--recipients-(nov11|batch)' -or
    $child.CommandLine -notmatch 'import_recipient_(selection|batches)\.py') {
    throw 'Selected import process identity changed; no process was stopped.'
}
if ($CheckOnly) { Write-Output 'process_identity_verified'; exit 0 }

# The caller has paused the child immediately after a verified journal entry.
# Stop the supervisor first so it cannot restart a child during the handover.
Stop-Process -Id $ParentPid -ErrorAction Stop
Stop-Process -Id $ChildPid -ErrorAction Stop
Wait-Process -Id $ParentPid,$ChildPid -ErrorAction SilentlyContinue
$exe = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
$worker = Join-Path $PSScriptRoot 'run_background.py'
if ($RequeueValidation) {
    & $exe (Join-Path $PSScriptRoot 'requeue_batch_conflicts.py')
    if ($LASTEXITCODE -ne 0) { throw 'Unable to requeue validation conflicts.' }
}
if ($Pilot) {
    if (-not $Batch) { throw 'Pilot requires batch mode.' }
    $output = & $exe (Join-Path $PSScriptRoot 'import_recipient_batches.py') --apply --limit 3
    if ($LASTEXITCODE -ne 0) { throw 'Pilot exited with an error.' }
    $result = $output | Select-Object -Last 1 | ConvertFrom-Json
    if ($result.stopped -or $result.created -ne 3) { throw 'Pilot did not verify three contacts.' }
    Write-Output 'pilot_verified=3'
}
$mode = if ($Batch) { '--recipients-batch' } else { '--recipients-nov11' }
$process = Start-Process -FilePath $exe -ArgumentList @(('"' + $worker + '"'), $mode) -WindowStyle Hidden -PassThru
Write-Output "restarted_worker_pid=$($process.Id)"
