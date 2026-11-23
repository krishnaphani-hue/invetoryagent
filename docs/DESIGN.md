# Inventory Agent: Design Document

Status: proof of concept, working end to end on a single Windows machine.

## 1. Purpose

Give one queryable view of what runs on each Windows machine: services, running applications,
the ports they listen on, their versions, and installed software. A small agent on each machine
collects this on a schedule and writes it to a central PostgreSQL database.

### Goals
- Run unattended: start at boot, need no logged-in user, restart after a failure.
- Capture the application and version behind every listening port.
- Survive a database outage without losing data.
- Depend on nothing beyond Windows and the PostgreSQL client library.

### Non-goals (for this version)
- Multiple-machine fleet management, an agent update mechanism, or a dashboard.
- Change-only storage (every cycle stores a full snapshot).
- Production-grade credential handling (see section 9).

## 2. Constraints and decisions

| Decision | Reason |
|---|---|
| C++17, Win32 API only | Requested. No managed runtime to install on endpoints. |
| UTF-8 for all external text | Requested. Win32 wide (UTF-16) calls are used internally and converted with `WideCharToMultiByte(CP_UTF8)`. Database, config, log and buffer files are UTF-8; the manifest sets the process code page to UTF-8. |
| PostgreSQL via `libpq` | The only non-Win32 dependency. It is the official client and ships with PostgreSQL. |
| Direct database writes | Simplest for a POC. The upload step is isolated so an HTTP API can replace it later. |
| One source file | The agent is small; a single translation unit keeps the build to one command. |

## 3. Architecture

```
 Windows machine                                           Database server
 +--------------------------------------------+            +-----------------+
 | InventoryAgent.exe (Windows service)       |            |                 |
 |                                            |   libpq    |   PostgreSQL    |
 |  Collectors --> Snapshot --> SQL builder --+----------->|   "inventory"   |
 |   services      (in memory)     |          |  (retry)   |                 |
 |   processes                     v          |            +-----------------+
 |   ports + versions       Uploader          |
 |   installed software       | on failure    |
 |                            v               |
 |                  buffer\*.sql (disk)       |
 +--------------------------------------------+
```

Each cycle: collect, build one SQL script, upload; on failure, write the script to the buffer folder
and send it first on the next cycle.

## 4. Components

### 4.1 Service host
- Entry point `wmain`. With no arguments it calls `StartServiceCtrlDispatcherW`.
- If that fails with `ERROR_FAILED_SERVICE_CONTROLLER_CONNECT`, a person launched the exe, not the Service Control Manager, so it opens the setup dialog instead of exiting. (An earlier version simply exited, which looked like a crash on double-click.)
- `ServiceMain` registers a control handler, reports `RUNNING`, and runs the agent loop. A stop or shutdown control sets an event that wakes the loop.
- Built with the Windows GUI subsystem so no console window appears. For command-line modes it attaches to the parent console so output still shows.

### 4.2 Collectors

| Collector | Win32 API | Notes |
|---|---|---|
| Services | `OpenSCManagerW`, `EnumServicesStatusExW`, `QueryServiceConfigW` | Status from the enumeration; start type from each service's config. |
| Processes | `CreateToolhelp32Snapshot`, `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`, `QueryFullProcessImageNameW` | Protected processes cannot be opened; their path stays empty and the row is still stored. |
| Versions | `GetFileVersionInfoW`, `VerQueryValueW` | `ProductVersion` string first, fixed file version as a fallback. Cached per path within the process. |
| Ports | `GetExtendedTcpTable` (listener state), `GetExtendedUdpTable`, for IPv4 and IPv6 | Each port is joined to its owning process by PID to get application, path and version. |
| Installed software | Registry `HKLM\...\Uninstall`, 64-bit and 32-bit views | De-duplicated by name and version. Machine-wide installs only. |
| Machine identity | Registry `MachineGuid`, `GetComputerNameExW`, `RtlGetVersion` | `MachineGuid` survives reboots and renames, so it is the machine ID. |

### 4.3 SQL builder and uploader
- A snapshot becomes one script: `BEGIN; ...; COMMIT;`, run as a single transaction so a snapshot is stored completely or not at all.
- Rows are inserted in multi-row `INSERT` statements of up to 500 rows.
- The machine row is an upsert (`ON CONFLICT (id) DO UPDATE`) that refreshes `last_seen`.
- Text values are escaped by doubling single quotes with `standard_conforming_strings=on`; NUL bytes are removed. The connection uses client encoding UTF-8.
- Upload retries 4 times with backoff (2 s, 4 s, 8 s). The wait is interruptible, so a service stop is not delayed.
- If all attempts fail, the script is saved as `buffer\<UTC timestamp>.sql`. At the start of the next upload, buffered scripts are sent oldest first, and each is deleted only after it succeeds. Original timestamps are preserved, so history stays correct.

### 4.4 Installer
- `DoInstall` stops any running copy, copies the exe, DLLs and `config.ini` to `C:\Program Files\InventoryAgent` (an existing `config.ini` is never overwritten), then creates or updates the service: automatic start, restart after 5 seconds on failure, a description, and start.
- `DoUninstall` stops and deletes the service. Files and database data are left in place.
- The GUI path re-launches itself with the `runas` verb to get a UAC prompt, so no elevated shell is needed.

### 4.5 Configuration and logging
- `config.ini` beside the exe: simple `Key=Value` lines, UTF-8, comments with `#`.
- Log: `C:\ProgramData\InventoryAgent\agent.log`, UTF-8, one line per event with a UTC timestamp.

## 5. Data model

```
machines (id uuid PK, hostname, os, last_seen)
   ^
   | machine_id (FK)
   +-- services           (name, display_name, status, start_type, collected_at)
   +-- processes          (name, pid, path, version, collected_at)
   +-- listening_ports    (protocol, local_address, port, pid, process_name, path, version, collected_at)
   +-- installed_software (name, version, publisher, collected_at)
```

- The four child tables are append-only: one set of rows per cycle, all sharing that cycle's `collected_at`.
- To see the current state, filter on `collected_at = (select max(collected_at) ...)`.
- Each child table has an index on `(machine_id, collected_at DESC)`.
- The agent's database user has INSERT, UPDATE and SELECT only. It cannot drop or alter tables, and it has no DELETE.

## 6. Runtime behaviour

```
start --> load config --> loop:
            collect all  --> build SQL --> flush buffer --> upload (retry x4)
                                                |                |
                                                |           fail |--> save to buffer
            wait IntervalMinutes (or stop event) <----------------+
```

- An exception in one cycle is logged and the loop continues.
- A failing collector returns what it could gather (for example a protected process with no path); it does not abort the cycle.
- The service runs as LocalSystem so it can read paths and versions of processes owned by other accounts.

## 7. Failure handling

| Failure | Behaviour |
|---|---|
| Database down or unreachable | 4 retries, then buffer the snapshot to disk and continue; flushed oldest-first when the database returns. |
| Service killed or crashes | Windows restarts it after 5 seconds; the next cycle runs normally. |
| Protected process or service config unreadable | Path or start type left empty or "Unknown"; the row is still stored. |
| Machine reboot | Automatic start brings the service up with no user logged in. |
| Bad `config.ini` value | Falls back to the default for that key. |

## 8. Verification done

- Built clean with no warnings (MSVC, `/W3`).
- Console run against a local PostgreSQL 16: services, processes, ports and software rows arrive and match the machine.
- Installed as a service; uploads every 5 minutes at exact 5-minute spacing.
- As LocalSystem, 129 of 147 listening-port rows had a path and version. The empty rows include the `System` process (ports 139, 445, 5985), which has no executable.
- Tested on Windows 11 only.

Not yet tested: the C++ agent's retry and disk-buffer path with the database down, reboot with no user logged in, a remote database, TLS, other Windows versions, and multi-machine use.

## 9. Security considerations

- **Credentials:** the database password sits in plain text in `config.ini`. Mitigate with NTFS permissions on the install folder, or move to an API (section 10).
- **Least privilege:** the database user is limited to INSERT, UPDATE and SELECT.
- **Transport:** the connection string can request TLS (`sslmode=require`); it is not enabled in the default config.
- **SQL construction:** values are escaped, not parameterised, because one transaction script is buffered to disk and replayed. All text is attacker-influenced (process names, display names), so escaping is covered by `standard_conforming_strings` and quote doubling; moving to parameterised `COPY` is a possible hardening.
- **Disclosure:** the data lists installed software and open ports, which is sensitive. Protect the database accordingly.
- **Service account:** LocalSystem is required for complete data but is highly privileged. The agent only reads system state and writes to the network.

## 10. Known limitations and future work

| Item | Direction |
|---|---|
| Full snapshot every cycle grows tables quickly | Store only changes, or keep a "current" table plus a history table; add retention (delete or partition old snapshots). |
| Plain-text credentials on each endpoint | An HTTP API (for example behind Apache) between agents and the database, with per-machine tokens. |
| Escaped-SQL uploads | Parameterised or binary `COPY` for the database, with a separate on-disk buffer format. |
| Installed software is machine-wide only | Add per-user (`HKCU`) and MSIX/Store apps. |
| Ports: only listening TCP and bound UDP | Optionally include established connections. |
| Single file, no tests | Split into modules; add unit tests for the SQL builder and config parser. |
| Not an MSI | Package with WiX; sign the exe and installer. |
| No dashboard | A read-only web view over the database. |
