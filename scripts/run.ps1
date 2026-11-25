# Single process: builds the dashboard, then FastAPI serves UI + API on one port.
# Where it listens comes from .env: HOST (127.0.0.1 = this computer only, 0.0.0.0 = other machines too)
# and APP_PORT (default 8080). Open http://localhost:8080
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
# Reload PATH so node/npm are found even in a terminal opened before Node.js was installed (e.g. VS Code).
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "npm not found. Install Node.js 22+ from nodejs.org." }

Set-Location "$root\frontend"
if (-not (Test-Path node_modules)) { npm install }
npm run build
if ($LASTEXITCODE -ne 0) { throw "frontend build failed" }

Set-Location "$root\backend"
$ErrorActionPreference = 'Continue'  # alembic logs to stderr; don't treat that as an error
& .\.venv\Scripts\python.exe -m alembic upgrade head 2>&1 | ForEach-Object { "$_" }
if ($LASTEXITCODE -ne 0) { throw "alembic failed (exit $LASTEXITCODE)" }
& .\.venv\Scripts\python.exe -m app
