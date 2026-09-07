# Register an hourly Windows Scheduled Task that snapshots local spoin_db_2 into Neon
# via scripts/backup_to_neon.ps1. Runs independently of Claude Code / any session --
# native OS scheduler, so the backup keeps happening even if this app is closed.
param(
    [string]$TaskName = "SpoinNeonBackup",
    [int]$IntervalHours = 1,
    [switch]$Unregister
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $PSScriptRoot "backup_to_neon.ps1"
$vbsPath = Join-Path $PSScriptRoot "run_backup_silent.vbs"

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Task '$TaskName' unregistered." -ForegroundColor Yellow
    exit 0
}

$action = New-ScheduledTaskAction `
    -Execute "wscript.exe" `
    -Argument "`"$vbsPath`"" `
    -WorkingDirectory $repoRoot

# One-time trigger (starting now) repeating every $IntervalHours, indefinitely -- no idle
# gate, unlike the idle generation scanner: a backup should run on a clock, not wait for the
# machine to be idle. (-Daily with -RepetitionInterval hits a PS 5.1 parameter-set ambiguity
# on this box; -Once is the compatible way to express "run every N hours forever".)
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Hours $IntervalHours) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Snapshots local spoin_db_2 into a Neon Postgres backup every $IntervalHours hour(s) via scripts/backup_to_neon.ps1." `
    -Force

Write-Host "Windows Scheduled Task '$TaskName' registered: runs every $IntervalHours hour(s)." -ForegroundColor Green
Write-Host "Log: $PSScriptRoot\neon_backup.log" -ForegroundColor Cyan
Write-Host "Unregister with: .\register_neon_backup_task.ps1 -Unregister" -ForegroundColor Cyan
