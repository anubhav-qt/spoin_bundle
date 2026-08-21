# Windows shim for the Makefile. `make` is not present on a stock Windows box, and
# the README promises a machine with only Docker and git is enough.
#
#     ./make.ps1 setup
#     ./make.ps1 dev
#     ./make.ps1 migration -m "add foo"
#
# Keep the target list in sync with the Makefile.

param(
    [Parameter(Position = 0)]
    [string]$Target = 'help',

    [Parameter()]
    [string]$m = ''
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Invoke-Compose {
    param([string[]]$ComposeArgs)
    & docker compose @ComposeArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$api = @('run', '--rm', '--no-deps', 'api')

switch ($Target) {
    'setup' {
        Invoke-Compose @('build')
        Invoke-Compose @('up', '-d', 'db')
        Invoke-Compose @('run', '--rm', 'seed')
        Write-Host ''
        Write-Host '  API   http://localhost:8000/docs'
        Write-Host '  Web   http://localhost:3000'
        Write-Host ''
        Write-Host '  Now run: ./make.ps1 dev'
    }
    'dev'       { Invoke-Compose @('up') }
    'seed'      { Invoke-Compose @('run', '--rm', 'seed') }
    'test'      { Invoke-Compose @('--profile', 'test', 'run', '--rm', 'test') }
    'lint'      { Invoke-Compose ($api + @('ruff', 'check', 'src', 'tests')) }
    'fmt'       { Invoke-Compose ($api + @('ruff', 'format', 'src', 'tests')) }
    'types'     { Invoke-Compose ($api + @('mypy', 'src')) }
    'check' {
        Invoke-Compose ($api + @('ruff', 'check', 'src', 'tests'))
        Invoke-Compose ($api + @('mypy', 'src'))
        Invoke-Compose @('--profile', 'test', 'run', '--rm', 'test')
    }
    'migrate'   { Invoke-Compose @('run', '--rm', 'seed', 'alembic', 'upgrade', 'head') }
    'migration' {
        if (-not $m) { throw 'Usage: ./make.ps1 migration -m "describe the change"' }
        Invoke-Compose @('run', '--rm', 'seed', 'alembic', 'revision', '--autogenerate', '-m', $m)
    }
    'worker'    { Invoke-Compose @('--profile', 'worker', 'run', '--rm', 'worker') }
    'scan'      { Invoke-Compose ($api + @('python', '-m', 'spoin.scan_and_generate', '--limit', '1')) }
    'api-types' {
        & npx --yes openapi-typescript http://localhost:8000/openapi.json -o packages/api-types/schema.d.ts
    }
    'down'      { Invoke-Compose @('down') }
    'clean'     { Invoke-Compose @('down', '-v') }
    default {
        Write-Host 'Targets:'
        @(
            'setup       Build images and bring up the stack, blank spoin_db (first-run entrypoint)'
            'dev         Run the whole stack with hot reload'
            'seed        Apply migrations to spoin_db (no fixtures -- see CLAUDE.md)'
            'test        Run the test suite'
            'lint        ruff check'
            'fmt         ruff format'
            'types       mypy --strict'
            'check       Everything CI runs'
            'migrate     Apply migrations'
            'migration   Autogenerate a migration: ./make.ps1 migration -m "add foo"'
            'worker      Run one batch pass of the worker, then exit'
            'api-types   Regenerate packages/api-types from the live OpenAPI schema'
            'down        Stop everything'
            'clean       Stop everything and delete the database volume'
        ) | ForEach-Object { Write-Host "  $_" }
    }
}
