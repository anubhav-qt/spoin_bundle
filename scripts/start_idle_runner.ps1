# PowerShell script to run the Idle Generation Runner in the background or foreground
param(
    [int]$IdleMinutes = 15,
    [double]$CpuThreshold = 15.0,
    [int]$Limit = 1,
    [switch]$Background
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot

$pythonExe = "C:\Python313\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = (Get-Command python).Source
}

$env:PYTHONPATH = "$repoRoot\apps\api\src"
$env:SPOIN_DATABASE_URL = "postgresql+asyncpg://spoin:spoin@localhost:5432/spoin_db"

$scriptPath = "$repoRoot\scripts\idle_generation_runner.py"

if ($Background) {
    Write-Host "Starting Idle Generation Runner in the background..." -ForegroundColor Green
    Start-Process -FilePath $pythonExe -ArgumentList "`"$scriptPath`" --idle-minutes $IdleMinutes --cpu-threshold $CpuThreshold --limit $Limit" -WindowStyle Hidden
    Write-Host "Runner started in the background. It will automatically detect 15m of CPU idle (<$CpuThreshold%) and generate missing cards." -ForegroundColor Cyan
} else {
    Write-Host "Starting Idle Generation Runner (Ctrl+C to stop)..." -ForegroundColor Green
    & $pythonExe -u $scriptPath --idle-minutes $IdleMinutes --cpu-threshold $CpuThreshold --limit $Limit
}
