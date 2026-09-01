# Snapshot spoin_db_2 (local, live) into a Neon Postgres project as a standing backup.
# Read-only against the local DB (pg_dump only); all writes land on Neon, never locally.
# Idempotent: `pg_dump --clean --if-exists` prefixes DROP statements, so re-running on a
# schedule always converges Neon to the current local state rather than erroring on rerun.
param(
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $repoRoot ".env.neon-backup"
$logFile = Join-Path $PSScriptRoot "neon_backup.log"

if (-not (Test-Path $envFile)) {
    throw "Missing $envFile -- create it with a line: NEON_DATABASE_URL=postgresql://..."
}

$neonUrl = $null
foreach ($line in Get-Content $envFile) {
    if ($line -match '^NEON_DATABASE_URL=(.+)$') { $neonUrl = $Matches[1].Trim() }
}
if (-not $neonUrl) { throw "NEON_DATABASE_URL not found in $envFile" }

function Log([string]$msg, [string]$color = 'Gray') {
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -Path $logFile -Value $line
    if (-not $Quiet) { Write-Host $line -ForegroundColor $color }
}

Push-Location $repoRoot
try {
    Log "backup starting"

    # Both pg_dump and psql run INSIDE the db container (matching Postgres 17 client,
    # egress already verified) so no client tools or the Neon URL touch the host shell
    # history. -e passes the URL as a container-process env var, not a literal arg.
    $cmd = 'pg_dump -U spoin -d spoin_db_2 --no-owner --no-privileges --clean --if-exists ' +
           '| psql "$NEON_DATABASE_URL" -v ON_ERROR_STOP=0 -q'

    $output = docker compose exec -T -e NEON_DATABASE_URL=$neonUrl db bash -c $cmd 2>&1
    $exitCode = $LASTEXITCODE
    $output | Add-Content -Path $logFile
    if (-not $Quiet) { $output | Select-Object -Last 15 | ForEach-Object { Write-Host $_ } }

    if ($exitCode -ne 0) {
        Log "backup FAILED (exit $exitCode) -- see $logFile" 'Red'
        exit 1
    }
    Log "backup completed OK" 'Green'
}
finally {
    Pop-Location
}
