# Register Windows Scheduled Task with built-in 15-minute Idle condition
param(
    [string]$TaskName = "SpoinIdleGenerationScanner",
    [switch]$Unregister
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Task '$TaskName' unregistered." -ForegroundColor Yellow
    exit 0
}

$pythonExe = "C:\Python313\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = (Get-Command python).Source
}

$action = New-ScheduledTaskAction `
    -Execute $pythonExe `
    -Argument "-m spoin.scan_and_generate --limit 1" `
    -WorkingDirectory "$repoRoot\apps\api"

# Daily trigger repeating every 1 hour, gated strictly by IdleSettings
$trigger = New-ScheduledTaskTrigger -Daily -At 12:00AM -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Days 3650)

# Windows Native Idle Condition: Run only when system has been idle for 15 minutes
$settings = New-ScheduledTaskSettingsSet `
    -RunOnlyIfIdle `
    -IdleDuration (New-TimeSpan -Minutes 15) `
    -IdleWaitTimeout (New-TimeSpan -Hours 2) `
    -StopIfGoingOffIdle `
    -AllowStartIfOnBatteries:$false `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Scans spoin_db for incomplete topics and runs generation pipeline when system is idle for 15 minutes." `
    -Force

Write-Host "Windows Scheduled Task '$TaskName' registered successfully!" -ForegroundColor Green
Write-Host "It will trigger when the computer has been idle for 15 minutes." -ForegroundColor Cyan
