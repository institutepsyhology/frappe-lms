param(
    [Parameter(Mandatory = $true)][int]$ParentPid,
    [Parameter(Mandatory = $true)][int]$ChildPid,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
$parent = Get-CimInstance Win32_Process -Filter "ProcessId = $ParentPid"
$child = Get-CimInstance Win32_Process -Filter "ProcessId = $ChildPid"
if (-not $parent -or -not $child -or $child.ParentProcessId -ne $ParentPid -or
    $parent.CommandLine -notmatch 'run_background\.py.*--recipients-nov11' -or
    $child.CommandLine -notmatch 'import_recipient_selection\.py') {
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
$process = Start-Process -FilePath $exe -ArgumentList @(('"' + $worker + '"'), '--recipients-nov11') -WindowStyle Hidden -PassThru
Write-Output "restarted_worker_pid=$($process.Id)"
