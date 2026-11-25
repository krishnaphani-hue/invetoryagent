# Asset Inventory Server

Collects inventory from Windows machines (installed software, listening ports, processes, services) and shows it
in a web dashboard.

- **Agents** (the Inventory Agent, or any other collector) send JSON to `POST /api/v1/inventory`.
- **Excel upload:** for machines without an agent, upload an `.xlsx` file on the dashboard's Upload page.
- Every delivery is kept as a **snapshot**, so history is preserved (30 days by default). The dashboard shows each
  machine's current state and any past snapshot.

| Document | For |
|---|---|
| **README.md** (this file) | Setting up, running, testing and deploying the server |
| [docs/DESIGN.md](docs/DESIGN.md) | How the system works: architecture, data model, decisions, future work |
| [docs/COLLECTOR_API.md](docs/COLLECTOR_API.md) | Agent developers: what to send, which API to call, how to handle responses |

> **No login yet.** Anyone who can reach the server can view the dashboard and upload files. Keep it on a trusted
> network and use test data until authentication is added.

**Stack:** Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL · React 19 · MUI 9 · Vite · TypeScript.
No Docker needed.

## Quick start

Install once, yourself: **PostgreSQL 16+** (service running), **Python 3.10+** and **Node.js 20+**. To also run the
agent you need Visual Studio or the Build Tools with the "Desktop development with C++" workload (the agent is
compiled from `agent/`); without it the server and dashboard still run.

```bat
git clone <repo>
cd asset-inventory-server
run.bat
```

`run.bat` needs no administrator rights and installs nothing system-wide. It creates `.env` (random passwords),
the databases, the Python environment and the dashboard build, builds the agent, then starts the **server** and
the **Inventory Agent** in the background and opens http://localhost:8080. The only question it can ask is the
PostgreSQL `postgres` password, once, to create the databases. Later runs just start things; `stop.bat` stops the
server and the agent (PostgreSQL is never touched). Logs and the agent's buffer are in `.data\`.

Options: `run.bat -NoBrowser`, `run.bat -SkipAgent`. The agent collects every 5 minutes and the server imports it
every 5 minutes (`AGENT_POLL_MINUTES` in `.env`). The steps below are the manual route.

## Contents

1. [Prerequisites](#1-prerequisites)
2. [First-time setup](#2-first-time-setup)
3. [Running the app](#3-running-the-app)
4. [Loading test data](#4-loading-test-data)
5. [Running the tests](#5-running-the-tests)
6. [Configuration](#6-configuration-env)
7. [Letting other machines connect](#7-letting-other-machines-connect)
8. [Deploying to a server](#8-deploying-to-a-server)
9. [Troubleshooting](#9-troubleshooting)
10. [Project layout](#10-project-layout)
11. [Vulnerability matching with Advanced-Threat-Intelligence (optional)](#11-vulnerability-matching-with-advanced-threat-intelligence-optional)

## 1. Prerequisites

Windows 10/11 with:

| Tool | Version | Notes |
|---|---|---|
| Python | 3.12 | `python` must be on PATH |
| Node.js | 22 or newer (tested with 26) | Includes `npm` |
| PostgreSQL | 16 or newer (tested with 19) | Installer from postgresql.org. This repo assumes **port 5433**; change `DATABASE_URL` if yours differs. Remember the `postgres` password you set during install. |
| Git | any | |

pgAdmin (installed with PostgreSQL) is useful for looking at the data but not required.

## 2. First-time setup (manual; `run.bat` does this for you)

From the repo root in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_db.ps1
```

The script:

1. Creates `.env` from `.env.example`, with a random password for the app's own database user (skipped if
   `.env` already exists).
2. Connects as `postgres` (**asks for that password once**) and creates the user `inventory_app` and two
   databases: `asset_inventory` (the app) and `asset_inventory_test` (used only by the tests).
3. Creates the Python virtual environment `backend\.venv`, installs the requirements, and creates the tables
   (`alembic upgrade head`).

You can run it again safely; it only creates what's missing. The frontend packages (`npm install`) are installed
automatically the first time you run the app.

## 3. Running the app

There are two modes. Both use the same code; they differ only in who serves the dashboard.

### Run mode: one process, one port (demos, servers)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run.ps1
```

| | URL |
|---|---|
| Dashboard | http://localhost:8080 |
| API | http://localhost:8080/api/v1/... |
| API docs (Swagger) | http://localhost:8080/api/docs |

What it does: builds the dashboard into static files (`npm run build` → `frontend/dist`), updates the database
tables, then starts the server with `python -m app`. FastAPI serves both the dashboard files and the API on one
port. Stop it with `Ctrl+C`.

### Dev mode: live reload while you change code

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

Opens two windows:

| Window | URL | Reloads on save |
|---|---|---|
| Dashboard (Vite dev server) | http://localhost:5173 | React/TypeScript changes |
| API (uvicorn `--reload`) | http://localhost:8000/api/docs | Python changes |

Vite forwards every `/api` request from 5173 to 8000, so the browser only talks to one address.

### How the dashboard finds the API

The dashboard calls the API with relative URLs (`/api/v1/...`), so it always uses the address it was loaded from.
There is no API URL to configure and no CORS setup, in any mode or environment.

## 4. Loading test data

The dashboard starts empty. With the app running (run mode, port 8080):

**Fake agent.** It sends realistic data in the same format as a real agent:

```powershell
backend\.venv\Scripts\python.exe tools\fake_collector.py --machines 5 --runs 3
```

| Option | Default | Meaning |
|---|---|---|
| `--url` | `http://localhost:8080` | Server address (use `http://localhost:8000` in dev mode) |
| `--machines` | 3 | Number of machines. The first 3 are detailed samples, the rest are generated. |
| `--runs` | 1 | Deliveries per machine. Versions change slightly between runs. `0` = forever. |
| `--interval` | 2 | Seconds between runs |
| `--api-key` | `INGEST_API_KEY` from `.env` | Sent as `X-API-Key` |

**Excel upload.** Open the dashboard's **Upload Excel** page and drop in
[samples/sample_inventory.xlsx](samples/sample_inventory.xlsx) (3 machines). To regenerate the file:
`backend\.venv\Scripts\python.exe tools\make_sample_excel.py`. The workbook format is described in
[docs/DESIGN.md](docs/DESIGN.md#52-excel-upload).

**Real data from the Inventory Agent's own database.** The agent currently writes to its own PostgreSQL database
instead of calling this API. Until it switches, the server can read that database itself: set `AGENT_DB_URL` in
`.env` (and `ONLINE_MINUTES` above `AGENT_POLL_MINUTES`) and restart. Every `AGENT_POLL_MINUTES` (default 30) it
imports the cycles collected since the last import, without duplicates. `GET /api/health` shows the last poll and
any error. The dashboard refreshes its data every 5 minutes.

To copy data once by hand instead (for example older history):

```powershell
backend\.venv\Scripts\python.exe tools\import_from_agent_db.py --agent-db "postgresql://agent:<password>@localhost:5432/inventory" --latest-only
```

`--latest-only` imports only the newest collection per machine; `--since 2026-11-20` imports everything from that
date. Running it twice imports the same data twice.

## 5. Running the tests

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q                                          # all tests
.\.venv\Scripts\python.exe -m pytest tests\test_excel.py::test_missing_hostname -q  # one test
```

The tests use the `asset_inventory_test` database (the `DATABASE_URL` database name plus `_test`) and empty it
before every test. They never touch the real `asset_inventory` data.

Frontend type check and build:

```powershell
cd frontend
npm run build
```

## 6. Configuration (`.env`)

All settings live in `.env` in the repo root (created by the setup script; never commit it). Defaults are in
`.env.example`.

| Key | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://inventory_app:<pw>@localhost:5433/asset_inventory` | App database. The tests use the same server with `_test` appended to the database name. |
| `HOST` | `127.0.0.1` | Where the server listens. `127.0.0.1` = this computer only. `0.0.0.0` = other machines can connect. |
| `APP_PORT` | `8080` | Port for run mode (`run.ps1` / `python -m app`) |
| `INGEST_API_KEY` | empty | If set, agents must send it in the `X-API-Key` header. Empty = no key needed. |
| `RETENTION_DAYS` | `30` | How many days of snapshots to keep. `0` = keep forever. |
| `ONLINE_MINUTES` | `15` | A machine is shown as online if it sent data within this many minutes |
| `MAX_UPLOAD_MB` | `20` | Largest Excel file accepted |
| `AGENT_DB_URL` | empty | libpq URL of the agent's own database, e.g. `postgresql://agent:<pw>@localhost:5432/inventory`. Set = poll it and import new cycles. Empty = no polling. |
| `AGENT_POLL_MINUTES` | `30` | How often the agent database is polled. Keep `ONLINE_MINUTES` above it (e.g. 35). |
| `ATI_URL` | empty | Address of a running Advanced-Threat-Intelligence server, e.g. `http://127.0.0.1:8001`. Set = vulnerability matching on ([section 11](#11-vulnerability-matching-with-advanced-threat-intelligence-optional)). |
| `ATI_POLL_MINUTES` | `60` | Minutes between automatic scans. `0` = only when you press **Scan now**. |
| `NVD_API_KEY` | empty | Optional free NVD key: raises NVD's limit from 5 to 50 requests per 30 s. |
| `NVD_MAX_LOOKUPS` | `15` | CVEs whose affected versions are fetched from NVD per scan (riskiest first). Raise it with a key. |
| `NVD_RANGE_TTL_DAYS` | `7` | How long a CVE's fetched version ranges are reused. |
| `PG_BIN` | newest folder under `C:\Program Files\PostgreSQL` | Optional. Folder with `psql.exe`, used only by `setup_db.ps1`. |

Restart the server after changing `.env`.

Generate a key for `INGEST_API_KEY`:

```powershell
backend\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(24))"
```

## 7. Letting other machines connect

By default (`HOST=127.0.0.1`) only your own computer can reach the server. An agent installed on the same machine
sends to `http://localhost:8080`, and nothing is exposed to the network.

| | Local (default) | Network demo | Hosted server |
|---|---|---|---|
| `HOST` | `127.0.0.1` | `0.0.0.0` | `127.0.0.1` (nginx in front) |
| `INGEST_API_KEY` | empty | set one | set one |
| Agents send to | `http://localhost:8080` | `http://<this-pc-ip>:8080` | `https://<your-domain>` |
| Also needed | nothing | a firewall rule (below) | see [section 8](#8-deploying-to-a-server) |

For a network demo, allow port 8080 through Windows Firewall (admin PowerShell, needs permission on a managed laptop):

```powershell
New-NetFirewallRule -DisplayName "Asset Inventory 8080" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow -Profile Domain,Private
```

Find your IP with `ipconfig`. Windows blocks incoming connections on networks marked **Public**. Set the network to
Private, or use a Domain network.

`INGEST_API_KEY` protects only agent deliveries. The dashboard and Excel upload stay open until login is added: a
key built into the web page would be visible to anyone who opens it.

## 8. Deploying to a server

On a server the app runs exactly as in run mode. nginx in front adds HTTPS and forwards every request unchanged, so
URLs keep the same paths:

```
Agents + browsers ──https──> nginx (443) ──http──> app on 127.0.0.1:8080 ──> PostgreSQL
```

- **nginx** only handles HTTPS. It runs as an operating-system service and reads
  [deploy/nginx.conf](deploy/nginx.conf) after you copy it to `/etc/nginx/conf.d/`.
- **The app** must be kept running by a service manager: a systemd unit on Linux, or a Windows service (for example
  with NSSM) on Windows. The service runs `python -m app` from the `backend` folder.
- **PostgreSQL** runs as its own service (Linux default port 5432; set `DATABASE_URL` accordingly).

### Option A: without Docker (recommended)

Same steps as on the laptop, using Linux equivalents:

1. Install PostgreSQL, Python 3.12, Node.js 22+ and nginx (e.g. `sudo apt install postgresql nginx python3-venv nodejs npm`).
2. As `postgres`, run [backend/scripts/setup_db.sql](backend/scripts/setup_db.sql) with a password for the app user:
   `sudo -u postgres psql -v app_password='<pw>' -f backend/scripts/setup_db.sql`
3. Create `.env` from `.env.example`: set `DATABASE_URL` (port 5432 and the password), `HOST=127.0.0.1` and an
   `INGEST_API_KEY`.
4. Build and migrate:
   ```bash
   cd frontend && npm ci && npm run build && cd ..
   cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python -m alembic upgrade head
   ```
5. Create a systemd service that runs `/path/to/backend/.venv/bin/python -m app` with `WorkingDirectory=/path/to/backend`
   and `Restart=always`, then `sudo systemctl enable --now asset-inventory`.
6. Copy `deploy/nginx.conf` to `/etc/nginx/conf.d/asset-inventory.conf`, set `server_name` and the certificate paths,
   then `sudo nginx -t && sudo systemctl reload nginx`.

To update: `git pull`, repeat step 4, then `sudo systemctl restart asset-inventory`.

### Option B: Docker (untested)

[deploy/Dockerfile](deploy/Dockerfile) and [deploy/docker-compose.yml](deploy/docker-compose.yml) are for a Linux
server where Docker is allowed. They have **not been tested**; Docker isn't used on the development laptop.

```bash
export POSTGRES_PASSWORD='<strong password>' INGEST_API_KEY='<key>'
docker compose -f deploy/docker-compose.yml up -d --build
```

This starts PostgreSQL and the app (it runs migrations on start). The app is published on `127.0.0.1:8080` only, so
nginx on the host (step 6 above) is still needed. Data lives in the `pgdata` Docker volume. Back it up with
`docker compose -f deploy/docker-compose.yml exec db pg_dump -U inventory_app asset_inventory > backup.sql`.

## 9. Troubleshooting

| Problem | Fix |
|---|---|
| `npm is not recognized` | The scripts reload PATH themselves. In a manual shell, open a new terminal, or restart VS Code after installing Node.js. |
| `setup_db.ps1`: `password authentication failed for user "postgres"` | Use the password you chose in the PostgreSQL installer. |
| `setup_db.ps1`: `psql.exe not found` | Add `PG_BIN=<folder containing psql.exe>` to `.env`. |
| Server won't start: port already in use | Another copy is running. Stop it, or change `APP_PORT`. Check with `Get-NetTCPConnection -LocalPort 8080`. |
| Dashboard loads but shows no machines | No data yet; see [section 4](#4-loading-test-data). |
| Other machines can't connect | `HOST=0.0.0.0` in `.env`, firewall rule added, network not set to Public; see [section 7](#7-letting-other-machines-connect). |
| Agent gets `401` | Its key doesn't match `INGEST_API_KEY`. |
| Dashboard shows an old version | In run mode the UI is rebuilt on every start of `run.ps1`; reload the page with `Ctrl+F5`. |

## 10. Project layout

```
backend/
  app/
    main.py              FastAPI app; serves the API and the built dashboard
    __main__.py          `python -m app`: starts uvicorn with HOST/APP_PORT from .env
    config.py            settings from .env
    db.py, models.py     database connection and tables
    schemas.py           incoming JSON format (validation)
    deps.py              API key check; ownership hooks for future login
    routers/             ingest.py (agents), upload.py (Excel), read.py (dashboard), threat.py (vulnerabilities)
    services/            ingest.py (store a delivery), excel_parser.py, queries.py, retention.py,
                         agent_poller.py, threat_intel.py (match software against ATI + NVD)
  alembic/               database migrations
  scripts/setup_db.sql   creates the database user and databases
  tests/                 pytest tests
  requirements.txt
frontend/
  src/                   React dashboard: api.ts (API calls), pages/, components/
  vite.config.ts         dev server on 5173, forwards /api to 8000
agent/                   Inventory Agent (C++): main.cpp, build.bat, schema.sql, config.ini (see agent/README.md)
run.bat, stop.bat        start / stop the server and the agent (scripts/launch.ps1)
scripts/                 launch.ps1, setup_db.ps1, run.ps1, dev.ps1
tools/                   fake_collector.py, import_from_agent_db.py, make_sample_excel.py
samples/                 sample_inventory.xlsx
deploy/                  nginx.conf, Dockerfile, docker-compose.yml (for a future server)
docs/                    DESIGN.md, COLLECTOR_API.md
```

## 11. Vulnerability matching with Advanced-Threat-Intelligence (optional)

The **Vulnerabilities** page shows which installed software is affected by known CVEs, per machine, ordered by risk
(CVSS, CISA "known exploited", public exploit code, EPSS), with the listening ports of the affected application.
It uses **Advanced-Threat-Intelligence (ATI)**, a separate app that collects CVEs. This server asks ATI which CVEs
mention each installed product, then reads the exact affected versions from NVD and compares them with the installed
version. Off by default; the rest of the dashboard works without it. How it decides is in
[docs/DESIGN.md](docs/DESIGN.md#54-threat-intelligence-advanced-threat-intelligence).

**1. Run ATI** (its own folder and virtual environment; its repo is separate from this one):

```powershell
git clone https://github.com/chiranjib2001/Advanced-Threat-Intelligence.git
cd Advanced-Threat-Intelligence
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py --gui --port 8001       # port 8000 is used by this repo's dev mode
```

ATI starts with an empty database, so load CVEs before matching: use the **scan** controls in its web page at
http://127.0.0.1:8001, or the CLI, for example `python main.py --cve CVE-2024-10979` for one CVE or
`python main.py --active-week-exploits` for recent exploited ones (see ATI's own README). AI keys are optional; without
them ATI skips its AI summaries and still stores CVEs, scores and exploit flags.

**2. Point this server at it** (add to `.env`, then restart with `stop.bat` and `run.bat`):

```
ATI_URL=http://127.0.0.1:8001
```

Optional: `NVD_API_KEY` (free, from nvd.nist.gov) so scans can check many more CVEs.

**3. Scan.** Open **Vulnerabilities** and press **Scan now** (it also runs every `ATI_POLL_MINUTES`). The first scans
check at most `NVD_MAX_LOOKUPS` CVEs each, riskiest first; the page says how many are still waiting, and those
findings show as **Needs review** until a later scan settles them. API:

```powershell
curl.exe -X POST http://localhost:8080/api/v1/vulnerabilities/scan
curl.exe http://localhost:8080/api/v1/vulnerabilities/status
curl.exe "http://localhost:8080/api/v1/vulnerabilities?status=vulnerable&kev_only=true"
```

Reading the results: **Vulnerable** = the installed version is inside an affected range NVD lists for that product.
**Needs review** = the product matches but the version can't be decided yet. **Ruled out** = the version is outside
every range (hidden by default). Products are matched by name, so click a row to check the matched product.

Tests for this feature use a fake ATI and a fake NVD (no network): `cd backend; .\.venv\Scripts\python.exe -m pytest tests\test_threat_intel.py -q`.
