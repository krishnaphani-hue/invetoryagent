# One-time database setup (Windows, native PostgreSQL, no Docker).
#  - creates .env from .env.example with a random password for the app user (if .env is missing)
#  - creates role inventory_app and databases asset_inventory + asset_inventory_test
#  - runs Alembic migrations (creates the tables)
# psql will ask for the *postgres* superuser password you chose in the PostgreSQL installer.
# Usage (from the repo root):  powershell -ExecutionPolicy Bypass -File scripts\setup_db.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Read-DotEnv([string]$path) {
    $map = @{}
    if (Test-Path $path) {
        foreach ($line in Get-Content $path -Encoding UTF8) {
            if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') { $map[$Matches[1]] = $Matches[2] }
        }
    }
    return $map
}

if (-not (Test-Path '.env')) {
    $bytes = New-Object byte[] 18
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $pw = ([Convert]::ToBase64String($bytes)) -replace '[+/=]', 'x'
    (Get-Content '.env.example' -Encoding UTF8) -replace 'inventory_app:change_me@', "inventory_app:$pw@" |
        Set-Content '.env' -Encoding UTF8
    Write-Host "[+] Created .env with a generated password for inventory_app"
}

$envMap = Read-DotEnv '.env'
if ($envMap['DATABASE_URL'] -notmatch 'inventory_app:([^@]+)@') { throw "Could not read the app password from DATABASE_URL in .env" }
$appPw = $Matches[1]
# Host and port come from DATABASE_URL; we connect as the postgres superuser to create the role and databases.
if ($envMap['DATABASE_URL'] -notmatch '@([^:/]+):(\d+)/') { throw "Could not read host:port from DATABASE_URL in .env" }
$pgHost = $Matches[1]; $pgPort = $Matches[2]
# psql.exe is not on PATH by default. Optional override: PG_BIN=<folder containing psql.exe> in .env
$pgBin = if ($envMap['PG_BIN']) { $envMap['PG_BIN'] } else {
    $d = Get-ChildItem (Join-Path $env:ProgramFiles 'PostgreSQL') -Directory -ErrorAction SilentlyContinue |
        Where-Object { Test-Path (Join-Path $_.FullName 'bin\psql.exe') } |
        Sort-Object { [int]($_.Name -replace '\D', '') } -Descending | Select-Object -First 1
    if ($d) { Join-Path $d.FullName 'bin' } else { 'C:\Program Files\PostgreSQL\18\bin' }
}
$psql = Join-Path $pgBin 'psql.exe'
if (-not (Test-Path $psql)) { throw "psql.exe not found at $psql. Add PG_BIN=<folder with psql.exe> to .env." }

Write-Host "[*] Creating role and databases (enter the postgres superuser password when asked)..."
& $psql -U postgres -h $pgHost -p $pgPort -d postgres -v ON_ERROR_STOP=1 -v "app_password=$appPw" -f 'backend\scripts\setup_db.sql'
if ($LASTEXITCODE -ne 0) { throw "psql failed (exit $LASTEXITCODE)" }

Write-Host "[*] Preparing Python virtual environment and running migrations..."
Set-Location backend
if (-not (Test-Path '.venv')) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install -q -r requirements.txt
& .\.venv\Scripts\python.exe -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw "alembic failed (exit $LASTEXITCODE)" }
Write-Host "[+] Database ready."
