# Inventory Agent

A background Windows service that records what is running on a machine and stores it in PostgreSQL.
Written in C++17 against the Win32 API, with UTF-8 used for all text that leaves the process.

Every cycle (default 5 minutes) it collects:

| Data | Fields |
|---|---|
| Windows services | name, display name, status, start type |
| Running processes | name, PID, executable path, file version |
| Listening ports | protocol (TCP/TCP6/UDP/UDP6), address, port, owning PID, application, path, version |
| Installed software | name, version, publisher (registry uninstall keys, 64-bit and 32-bit) |

Each row carries a machine ID and a collection timestamp, so you can query any machine at any point in time.

See [docs/DESIGN.md](docs/DESIGN.md) for architecture and design decisions.

## Requirements

- Windows 10/11 x64 (tested on Windows 11)
- To build: Visual Studio 2022 Build Tools (C++ workload) and PostgreSQL 16 (for `libpq` headers and libraries)
- To run: a reachable PostgreSQL server and `libpq.dll` with its dependencies beside the exe (`build.bat` copies them)

## Build

```bat
build.bat
```

Output goes to `out\`: `InventoryAgent.exe`, `config.ini` and the libpq DLLs. Run `build.bat` from this folder.

## Set up the database

New database (run as the `postgres` superuser):

```
psql -U postgres -f schema.sql
```

Existing database from an earlier version (adds the `listening_ports` table and `processes.version`):

```
psql -U postgres -d inventory -f migrate_ports.sql
```

`schema.sql` creates the `inventory` database, the tables, and a limited `agent` user with
INSERT, UPDATE and SELECT only. **Change the `change_me` password** in `schema.sql` and `config.ini`.

## Install

Double-click `out\InventoryAgent.exe`. Windows asks for administrator rights, then a dialog offers to install.
Installing copies the files to `C:\Program Files\InventoryAgent`, registers the `InventoryAgent` service
(automatic start, restart on failure) and starts it. Running it again offers reinstall or uninstall.

Command line equivalents (run from an elevated shell):

| Command | Effect |
|---|---|
| `InventoryAgent.exe --setup` | Open the setup dialog |
| `InventoryAgent.exe --install` | Install or update the service without a dialog |
| `InventoryAgent.exe --uninstall` | Stop and remove the service (data and files are kept) |
| `InventoryAgent.exe --console` | Run in the foreground and log to the console; stop with Ctrl+C |

## Configure

Edit `config.ini` beside the installed exe, then restart the service. The file is UTF-8; lines starting with `#` are comments.

| Key | Default | Meaning |
|---|---|---|
| `ConnectionString` | local `inventory` DB as `agent` | libpq connection string |
| `IntervalMinutes` | `5` | Minutes between collections (minimum 1) |
| `CollectInstalledSoftware` | `true` | Set `false` to skip the registry software scan |
| `BufferDirectory` | `C:\ProgramData\InventoryAgent\buffer` | Where snapshots wait when the database is down |

Logs are written to `C:\ProgramData\InventoryAgent\agent.log`.

## View the data

- `.\view.ps1` prints the latest inventory as tables (needs `psql`).
- Or use pgAdmin 4 and open the `inventory` database.

Useful queries:

```sql
-- Listening ports with the application and version
select protocol, port, process_name as application, version, path, pid
from listening_ports
where collected_at = (select max(collected_at) from listening_ports)
order by port, protocol;

-- Currently running services
select name, display_name, start_type from services
where collected_at = (select max(collected_at) from services) and status = 'Running';
```

## Project layout

| File | Purpose |
|---|---|
| `main.cpp` | The whole agent: collectors, SQL builder, uploader, service and setup code |
| `build.bat` | MSVC build script |
| `InventoryAgent.manifest` | Sets the process code page to UTF-8 |
| `config.ini` | Settings template |
| `schema.sql` | Full database setup |
| `migrate_ports.sql` | Upgrade for databases created before ports were added |
| `view.ps1` | Prints the latest data as tables |
| `docs/DESIGN.md` | Design document |

## Known limitations

- The database password is stored in plain text in `config.ini`. Restrict file permissions, or put an API in front of the database.
- Each cycle stores a full snapshot, so tables grow quickly (about 900 rows per cycle on a typical PC).
- Processes owned by other accounts hide their path from a non-elevated user. The service runs as LocalSystem and sees them.
- The Windows `System` process (ports 139, 445, 5985) has no executable, so it has no version.
