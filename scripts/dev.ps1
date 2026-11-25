# Development mode: backend (hot reload, :8000) + frontend (Vite, :5173) in two new windows.
# Open http://localhost:5173  (Vite forwards /api to the backend)
$root = Split-Path -Parent $PSScriptRoot
# Reload PATH so node/npm are found even in a terminal opened before Node.js was installed (e.g. VS Code).
# The new windows below inherit this PATH.
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')

Start-Process powershell -WorkingDirectory "$root\backend" -ArgumentList '-NoExit', '-Command',
    '.\.venv\Scripts\Activate.ps1; python -m alembic upgrade head; python -m uvicorn app.main:app --reload --port 8000'

Start-Process powershell -WorkingDirectory "$root\frontend" -ArgumentList '-NoExit', '-Command',
    'if (-not (Test-Path node_modules)) { npm install }; npm run dev'

Write-Host "Started backend (http://localhost:8000/api/docs) and frontend (http://localhost:5173)."
