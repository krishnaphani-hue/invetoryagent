# run.bat: starts the dashboard server and the Inventory Agent from this folder. No administrator rights needed and
# nothing is installed system-wide.
#
# You install and start these once yourself:
#   - PostgreSQL 16+ (running)           - Python 3.10+           - Node.js 20+ (builds the dashboard)
#   - optional, for the agent: Visual Studio or Build Tools with the "Desktop development with C++" workload
#
# First run: creates .env (random passwords), the two databases, the Python environment, the tables and the
# dashboard build. Later runs just start things. Safe to re-run; things already running are left alone.
# The only possible question: the PostgreSQL "postgres" password, once, when the databases do not exist yet
# (or set $env:PG_SUPERUSER_PASSWORD beforehand).
#
# stop.bat (= this script with -Stop) stops the server and the agent. PostgreSQL is yours; it is never touched.
# Options: -NoBrowser   -SkipAgent   -Stop
param([switch]$Stop, [switch]$NoBrowser, [switch]$SkipAgent)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$data = Join-Path $root '.data'          # logs, process ids, the agent's buffer (git-ignored)
$pidFile = Join-Path $data 'pids.json'
$venvPy = Join-Path $root 'backend\.venv\Scripts\python.exe'

function Step($m) { Write-Host "`n[*] $m" -ForegroundColor Cyan }
function Info($m) { Write-Host "    $m" }
function Refresh-Path { $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User') }
function New-Secret { $b = New-Object byte[] 18; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); ([Convert]::ToBase64String($b)) -replace '[+/=]', 'x' }
function Read-DotEnv([string]$path) {
    $map = @{}
    if (Test-Path $path) { foreach ($line in Get-Content $path -Encoding UTF8) { if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') { $map[$Matches[1]] = $Matches[2] } } }
    return $map
}
function Set-EnvLine([string]$file, [string]$key, [string]$value) {
    $lines = @(Get-Content $file -Encoding UTF8)
    $found = $false
    $lines = $lines | ForEach-Object { if ($_ -match "^\s*#?\s*$key\s*=") { if (-not $found) { $found = $true; "$key=$value" } } else { $_ } }
    if (-not $found) { $lines += "$key=$value" }
    Set-Content $file $lines -Encoding UTF8
}
function Get-Pids { if (Test-Path $pidFile) { try { return (Get-Content $pidFile -Raw | ConvertFrom-Json) } catch {} }; return [pscustomobject]@{} }
function Save-Pid([string]$name, [int]$id) {
    $p = Get-Pids
    $p | Add-Member -NotePropertyName $name -NotePropertyValue $id -Force
    New-Item -ItemType Directory -Force $data | Out-Null
    $p | ConvertTo-Json | Set-Content $pidFile -Encoding ascii
}
function Test-Alive([string]$name, [string]$procName) {
    $id = (Get-Pids).$name
    if (-not $id) { return $false }
    $p = Get-Process -Id $id -ErrorAction SilentlyContinue
    return [bool]($p -and $p.ProcessName -like "$procName*")
}

# ---------------------------------------------------------------- stop
if ($Stop) {
    Step "Stopping"
    $p = Get-Pids
    foreach ($n in 'server', 'agent') {
        $id = $p.$n
        if ($id -and (Get-Process -Id $id -ErrorAction SilentlyContinue)) { Stop-Process -Id $id -Force; Info "Stopped $n (pid $id)" }
    }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
    exit 0
}

try {
Refresh-Path

# ---------------------------------------------------------------- prerequisites
Step "Checking prerequisites"
function Find-Python {
    foreach ($cmd in @('py -3', 'python')) {
        $parts = $cmd.Split(' ')
        try {
            $exe = & $parts[0] @($parts[1..9] | Where-Object { $_ }) -c "import sys; print(sys.executable if sys.version_info >= (3,10) else '')" 2>$null
            if ($exe -and (Test-Path $exe)) { return $exe }
        } catch {}
    }
    return $null
}
$python = Find-Python
if (-not $python) { throw "Python 3.10+ not found. Install it from python.org (tick 'Add python.exe to PATH'), then run run.bat again." }
Info "Python: $python"

$nodeOk = $false
try { $v = (& node --version 2>$null); $nodeOk = ($v -match '^v(\d+)' -and [int]$Matches[1] -ge 20) } catch {}
if (-not $nodeOk) { throw "Node.js 20+ not found. Install it from nodejs.org, then run run.bat again." }
Info "Node: $(& node --version)"

# PostgreSQL: psql + the server must be present and running
$pgDir = $null
$base = Join-Path $env:ProgramFiles 'PostgreSQL'
if (Test-Path $base) {
    $pgDir = Get-ChildItem $base -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'bin\psql.exe') } |
        Sort-Object { [int]($_.Name -replace '\D', '') } -Descending | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $pgDir) { throw "PostgreSQL not found under $base. Install PostgreSQL 16+ (postgresql.org), make sure its service is running, then run run.bat again." }
$psql = Join-Path $pgDir 'bin\psql.exe'
Info "PostgreSQL: $pgDir"

# ---------------------------------------------------------------- configuration
Step "Configuration"
$envFile = Join-Path $root '.env'
if (-not (Test-Path $envFile)) {
    # Port: the one PostgreSQL is listening on (the first run has to guess; override with $env:PG_PORT).
    $pgPort = $env:PG_PORT
    if (-not $pgPort) {
        $procs = @(Get-Process postgres -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
        $pgPort = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $procs -contains $_.OwningProcess } |
            Sort-Object LocalPort | Select-Object -First 1 -ExpandProperty LocalPort
    }
    if (-not $pgPort) { throw "PostgreSQL is not running. Start its service (services.msc, postgresql-x64-*) and run run.bat again." }
    Copy-Item (Join-Path $root '.env.example') $envFile
    Set-EnvLine $envFile 'DATABASE_URL' "postgresql+psycopg://inventory_app:$(New-Secret)@localhost:$pgPort/asset_inventory"
    Set-EnvLine $envFile 'AGENT_DB_URL' "postgresql://agent:$(New-Secret)@localhost:$pgPort/inventory"
    Set-EnvLine $envFile 'AGENT_POLL_MINUTES' '5'
    Info "Created .env with generated passwords (PostgreSQL port $pgPort)"
}
$envMap = Read-DotEnv $envFile
if ($envMap['DATABASE_URL'] -notmatch 'inventory_app:([^@]+)@([^:/]+):(\d+)/') { throw "DATABASE_URL in .env must look like postgresql+psycopg://inventory_app:<password>@localhost:<port>/asset_inventory" }
$appPw = $Matches[1]; $pgHost = $Matches[2]; $pgPort = [int]$Matches[3]
if (-not $envMap['AGENT_DB_URL']) { Set-EnvLine $envFile 'AGENT_DB_URL' "postgresql://agent:$(New-Secret)@${pgHost}:$pgPort/inventory"; $envMap = Read-DotEnv $envFile }
if ($envMap['AGENT_DB_URL'] -notmatch 'agent:([^@]+)@') { throw "AGENT_DB_URL in .env must look like postgresql://agent:<password>@localhost:<port>/inventory" }
$agentPw = $Matches[1]
$appPort = if ($envMap['APP_PORT']) { [int]$envMap['APP_PORT'] } else { 8080 }
$url = "http://localhost:$appPort"
New-Item -ItemType Directory -Force $data | Out-Null

# ---------------------------------------------------------------- databases
Step "Databases"
function Test-Login([string]$user, [string]$pw, [string]$db) {
    # Windows PowerShell 5.1 turns any native stderr into a terminating error under 'Stop' (even with 2>$null), so a
    # failed login (expected on the first run, before the user exists) would abort the script. Local to this function.
    $ErrorActionPreference = 'Continue'
    $old = $env:PGPASSWORD; $env:PGPASSWORD = $pw
    try { & $psql -U $user -h $pgHost -p $pgPort -d $db -tAc 'select 1' 2>$null | Out-Null; return ($LASTEXITCODE -eq 0) }
    finally { if ($null -eq $old) { Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue } else { $env:PGPASSWORD = $old } }
}
$appReady = Test-Login 'inventory_app' $appPw 'asset_inventory'
$agentReady = $SkipAgent -or (Test-Login 'agent' $agentPw 'inventory')
if ($appReady -and $agentReady) {
    Info "Already set up"
} else {
    $super = $env:PG_SUPERUSER_PASSWORD
    if (-not $super) {
        Write-Host "    The databases do not exist yet. I need the PostgreSQL 'postgres' password once to create them."
        $sec = Read-Host "    postgres password" -AsSecureString
        $super = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
    }
    if (-not (Test-Login 'postgres' $super 'postgres')) { throw "Could not log in to PostgreSQL on ${pgHost}:$pgPort as 'postgres' with that password (is the service running on that port?)." }
    $env:PGPASSWORD = $super
    try {
        & $psql -U postgres -h $pgHost -p $pgPort -d postgres -q -v ON_ERROR_STOP=1 -v "app_password=$appPw" -f (Join-Path $root 'backend\scripts\setup_db.sql') | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "creating the app database failed" }
        if (-not $SkipAgent) {
            & $psql -U postgres -h $pgHost -p $pgPort -d postgres -q -v ON_ERROR_STOP=1 -v "agent_password=$agentPw" -f (Join-Path $root 'agent\schema.sql') | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "creating the agent database failed" }
        }
    } finally { Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue }
    Info "Created asset_inventory and inventory"
}

# ---------------------------------------------------------------- backend
Step "Backend (Python environment, migrations)"
if (-not (Test-Path $venvPy)) {
    & $python -m venv (Join-Path $root 'backend\.venv')
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPy)) { throw "creating the Python environment failed" }
}
$req = Join-Path $root 'backend\requirements.txt'
$reqStamp = Join-Path $root 'backend\.venv\.requirements.sha'
$reqHash = (Get-FileHash $req).Hash
if (-not (Test-Path $reqStamp) -or (Get-Content $reqStamp -Raw).Trim() -ne $reqHash) {
    Info "Installing Python packages ..."
    & $venvPy -m pip install -q --disable-pip-version-check -r $req
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
    Set-Content $reqStamp $reqHash -Encoding ascii
}
Push-Location (Join-Path $root 'backend')
$ErrorActionPreference = 'Continue'   # alembic logs to stderr
& $venvPy -m alembic upgrade head 2>&1 | ForEach-Object { "    $_" }
$alembicExit = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
Pop-Location
if ($alembicExit -ne 0) { throw "alembic failed (exit $alembicExit)" }

# ---------------------------------------------------------------- dashboard
Step "Dashboard (web UI)"
$fe = Join-Path $root 'frontend'
$distIndex = Join-Path $fe 'dist\index.html'
$needBuild = -not (Test-Path $distIndex)
if (-not $needBuild) {
    $newest = Get-ChildItem (Join-Path $fe 'src'), (Join-Path $fe 'package.json'), (Join-Path $fe 'index.html') -Recurse -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $needBuild = $newest.LastWriteTime -gt (Get-Item $distIndex).LastWriteTime
}
if ($needBuild) {
    Push-Location $fe
    $ErrorActionPreference = 'Continue'   # npm warnings go to stderr
    if (-not (Test-Path 'node_modules')) { & npm install --no-audit --no-fund 2>&1 | ForEach-Object { "    $_" }; $ni = $LASTEXITCODE } else { $ni = 0 }
    if ($ni -eq 0) { & npm run build 2>&1 | ForEach-Object { "    $_" }; $feExit = $LASTEXITCODE } else { $feExit = $ni }
    $ErrorActionPreference = 'Stop'
    Pop-Location
    if ($feExit -ne 0) { throw "dashboard build failed" }
} else { Info "Up to date" }

# ---------------------------------------------------------------- agent
if (-not $SkipAgent) {
    Step "Inventory Agent"
    $agentDir = Join-Path $root 'agent'
    $exe = Join-Path $agentDir 'out\InventoryAgent.exe'
    $srcTime = (Get-Item (Join-Path $agentDir 'main.cpp')).LastWriteTime
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    $hasMsvc = (Test-Path $vswhere) -and [bool](& $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath)
    if ($hasMsvc -and (-not (Test-Path $exe) -or (Get-Item $exe).LastWriteTime -lt $srcTime)) {
        Info "Building InventoryAgent.exe ..."
        $env:PG = $pgDir
        Push-Location $agentDir
        $ErrorActionPreference = 'Continue'
        & cmd /c ".\build.bat" 2>&1 | ForEach-Object { "    $_" }
        $b = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
        Pop-Location
        Remove-Item Env:\PG -ErrorAction SilentlyContinue
        if ($b -ne 0) { Write-Warning "Agent build failed." }
    }
    if (-not (Test-Path $exe)) {
        Write-Warning "InventoryAgent.exe is not built and Visual Studio / Build Tools (C++ workload) was not found, so the agent is skipped. The server and dashboard still work. Install the C++ Build Tools and run run.bat again to add the agent."
    } else {
        $agentData = Join-Path $data 'agent'
        New-Item -ItemType Directory -Force (Join-Path $agentData 'buffer') | Out-Null
        $conn = "host=$pgHost port=$pgPort dbname=inventory user=agent password=$agentPw client_encoding=UTF8"
        $cfg = Get-Content (Join-Path $agentDir 'config.ini') -Encoding UTF8 | Where-Object { $_ -notmatch '^\s*#?\s*BufferDirectory\s*=' } |
            ForEach-Object { if ($_ -match '^\s*ConnectionString\s*=') { "ConnectionString=$conn" } else { $_ } }
        $cfg += "BufferDirectory=$(Join-Path $agentData 'buffer')"
        [IO.File]::WriteAllLines((Join-Path $agentDir 'out\config.ini'), $cfg, (New-Object Text.UTF8Encoding($false)))
        if (Test-Alive 'agent' 'InventoryAgent') { Info "Already running" }
        else {
            $env:INVENTORY_AGENT_DATA = $agentData
            $proc = Start-Process -FilePath $exe -ArgumentList '--console' -WorkingDirectory (Join-Path $agentDir 'out') -WindowStyle Hidden -PassThru
            Remove-Item Env:\INVENTORY_AGENT_DATA -ErrorAction SilentlyContinue
            Save-Pid 'agent' $proc.Id
            Info "Started (pid $($proc.Id)). It collects every 5 minutes. Log: .data\agent\agent.log"
        }
    }
}

# ---------------------------------------------------------------- server
Step "Server"
$inUse = Get-NetTCPConnection -State Listen -LocalPort $appPort -ErrorAction SilentlyContinue
$answers = $false
if ($inUse) { try { $answers = (Invoke-WebRequest "$url/api/v1/stats" -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200 } catch {} }
if ($answers) { Info "A server is already running on port $appPort" }
elseif ($inUse) { throw "Port $appPort is used by another program. Set APP_PORT in .env to a free port and run again." }
else {
    $proc = Start-Process -FilePath $venvPy -ArgumentList '-m', 'app' -WorkingDirectory (Join-Path $root 'backend') -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $data 'server.log') -RedirectStandardError (Join-Path $data 'server.err.log')
    Save-Pid 'server' $proc.Id
    $up = $false
    for ($i = 0; $i -lt 40 -and -not $up; $i++) {
        Start-Sleep 1
        try { $up = (Invoke-WebRequest "$url/api/v1/stats" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch {}
    }
    if (-not $up) { throw "The server did not start. See .data\server.err.log" }
    Info "Started (pid $($proc.Id))"
}
Write-Host "`n[+] Running. Dashboard: $url" -ForegroundColor Green
Write-Host "    Stop the server and agent with stop.bat. Logs are in .data\"
if (-not $NoBrowser) { Start-Process $url }
} catch {
    Write-Host "`n[x] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
