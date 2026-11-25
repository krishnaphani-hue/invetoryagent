# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A PoC server that stores Windows machine inventory (installed software, listening ports, processes, services) and
shows it in a React dashboard. Data arrives from the C++ Inventory Agent in `agent/` (it writes to its
own PostgreSQL database that the server polls, or can POST JSON to `/api/v1/inventory`) or from Excel uploads (`POST /api/v1/uploads`). No login yet.
**No Docker on the dev laptop:** PostgreSQL runs natively on Windows on **port 5433**.

## Documentation (keep these three in sync with the code)

| File | Audience | Update when |
|---|---|---|
| `README.md` | Anyone running the server | Setup, scripts, `.env` keys, tools or deployment steps change |
| `docs/DESIGN.md` | Manager and developers | Architecture, tables, current-state rules, API list, Excel format or security change |
| `docs/COLLECTOR_API.md` | Agent developers (Krishna) | Anything in `POST /api/v1/inventory`: fields, validation, responses, auth header |

Don't add other docs files; extend these. `.env.example` documents every setting inline.

## Commands (PowerShell, repo root)

```powershell
run.bat                                                         # start server + agent (first run: .env, DBs, venv, UI build, agent build); stop.bat stops them
powershell -ExecutionPolicy Bypass -File scripts\setup_db.ps1   # one-time: .env, role, DBs, venv, migrations
powershell -ExecutionPolicy Bypass -File scripts\run.ps1        # build UI, migrate, `python -m app`: UI+API on HOST:APP_PORT (8080)
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1        # two windows: uvicorn --reload :8000 + Vite :5173
cd backend; .\.venv\Scripts\python.exe -m pytest -q             # all tests (asset_inventory_test DB)
cd backend; .\.venv\Scripts\python.exe -m pytest tests\test_excel.py::test_missing_hostname -q   # one test
cd backend; .\.venv\Scripts\python.exe -m alembic revision -m "..."   # new migration (hand-written)
cd frontend; npm run build                                      # tsc type-check + vite build
backend\.venv\Scripts\python.exe tools\fake_collector.py --machines 5 --runs 3   # default URL :8080
cd agent; cmd /c .\build.bat                                   # build the agent into agent\out (auto-detects PostgreSQL)
```

`run.ps1` and `dev.ps1` reload PATH from the machine/user environment (VS Code terminals can have a stale PATH
without `npm`). Do the same in an ad-hoc shell if `node`/`npm` aren't found. The user may have their own server
running on 8080; check before starting another one, and don't stop processes you didn't start.

## Architecture

- **Append-only snapshots.** Each delivery creates one `snapshots` row per machine (server-generated UUID), and
  rows in `installed_software` / `listening_ports` / `processes` / `services` point to it. Nothing is updated in
  place except `machines` (upsert, `last_seen`). Don't add code that deletes or overwrites section rows. History
  is removed only by `services/retention.py` (`RETENTION_DAYS`).
- **Current state** = per machine and per section, the latest snapshot **by `collected_at`** whose count column
  (`software_count`, `port_count`, ...) is not NULL. NULL means "section not included in this delivery". Keep it
  that way: the agent replays buffered data late with original timestamps, and partial deliveries must not
  blank other sections. Implemented in `services/queries.py::current_snapshot_ids` and mirrored by the
  `current_*` SQL views in the initial migration.
- **One ingest path.** `services/ingest.py::store_delivery` is used by both the collector route and the Excel
  route. Excel is converted to the same `schemas.InventoryIn` payloads by `services/excel_parser.py` (grouped by
  hostname, all-or-nothing, errors carry sheet + row).
- **Flexible schema.** Payload models allow unknown fields (`extra="allow"`); they are stored in each row's
  `extra` JSONB. Required: machine `id` or `hostname`, `name` (software/process/service), `port`. When adding a
  real column: `models.py`, `schemas.py`, a new Alembic migration (and the `current_*` view if needed), the Excel
  parser's text columns, `frontend/src/api.ts`, and the field tables in DESIGN.md and COLLECTOR_API.md.
- **Machine id** = the agent's Windows `MachineGuid`; without one, a UUIDv5 of the lowercased hostname.
- **Ownership hooks for future auth.** Every route takes `deps.get_current_owner()` (returns None) and filters
  through `deps.scope_machines()`. New read queries must go through `scope_machines` too.
- **Ingest key.** If `INGEST_API_KEY` is set, `POST /api/v1/inventory` requires header `X-API-Key`
  (`deps.require_ingest_key`, router-level dependency). Uploads and reads stay open until login exists (a key in
  the browser bundle would be public).
- **Same setup everywhere.** `python -m app` (`app/__main__.py`) starts uvicorn from `.env` (`HOST`, default
  `127.0.0.1` = local only; `APP_PORT`). The dashboard uses relative `/api/v1` URLs, so there is no
  per-environment frontend config and no CORS. In dev, Vite proxies `/api` to :8000; in run mode `app/main.py`
  serves `frontend/dist` with an SPA fallback. On a hosted server nginx (`deploy/nginx.conf`) only adds HTTPS.
  Agents choose the server via `ServerUrl` / `ApiKey` in their `config.ini`.
- **Sync stack.** SQLAlchemy 2 sync + psycopg 3, sync FastAPI routes (thread pool).
- **Tests** derive their DB from `DATABASE_URL` + `_test` (`tests/conftest.py`), point `app.db` at it via
  `db.configure()`, and truncate `machines CASCADE` before each test. Never point tests at the real DB.
- **Frontend.** `frontend/src/api.ts` holds all types + TanStack Query hooks (types mirror `routers/read.py`).
  Library versions are new (MUI 9, MUI X 9, React Router 8 imported from `react-router`, TS 7). Layouts use Box
  CSS grid rather than MUI Grid.
- "Exposed" port = `local_address` not loopback (`127.*`, `::1`).
- `deploy/` (Dockerfile, compose, nginx.conf) is for a future server; the Docker files are untested.
