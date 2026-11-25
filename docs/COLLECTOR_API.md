# Collector API: sending inventory to the server

For developers of the Inventory Agent, or any other collector. It describes what to send, where, and how to handle
the response.

Related: [README.md](../README.md) (running the server) · [DESIGN.md](DESIGN.md) (how the server stores data)

## Contents

1. [Summary](#1-summary)
2. [Configuration on the agent](#2-configuration-on-the-agent)
3. [Request](#3-request)
4. [Body](#4-body)
5. [Responses and retries](#5-responses-and-retries)
6. [Rules and behaviour](#6-rules-and-behaviour)
7. [Examples](#7-examples)
8. [Changes for the Inventory Agent](#8-changes-for-the-inventory-agent)
9. [Testing](#9-testing)

## 1. Summary

- After each collection cycle, send **one HTTP POST** with **one JSON object** describing the machine.
- Endpoint: `POST {ServerUrl}/api/v1/inventory`
- Send the header `X-API-Key: {ApiKey}` if the server has a key configured.
- `201` = stored. `401` = wrong key. `422` = bad body. Network error or `5xx` = buffer and retry later.
- Always send the **original collection time** in `collected_at`, also when replaying buffered data.

The server stores each delivery as a new snapshot, so history is kept, and returns the snapshot id it generated.

## 2. Configuration on the agent

Two settings decide where data goes. Changing servers means editing these values and restarting the agent; no
rebuild.

| Setting | Example | Meaning |
|---|---|---|
| `ServerUrl` | `http://localhost:8080` | Base address of the server, without a trailing slash and without `/api/v1` |
| `ApiKey` | `k3Jd9...` | Shared key from the server admin (the server's `INGEST_API_KEY`). Empty if the server has none. |

| Where the server runs | `ServerUrl` | `ApiKey` |
|---|---|---|
| Same computer as the agent (development) | `http://localhost:8080` | empty |
| Another computer on the network | `http://<server-ip>:8080` | from the server admin |
| Hosted server (HTTPS) | `https://<server-domain>` | from the server admin |

## 3. Request

```
POST {ServerUrl}/api/v1/inventory
Content-Type: application/json; charset=utf-8
X-API-Key: {ApiKey}            ← only when ApiKey is not empty
```

- The body is UTF-8 JSON (section 4).
- Support both `http://` and `https://` in `ServerUrl`. With WinHTTP, pass `WINHTTP_FLAG_SECURE` to
  `WinHttpOpenRequest` when the scheme is `https`.
- Use a timeout (for example 30 seconds) so a slow server never blocks the next cycle.
- A typical cycle (around 900 rows) is a few hundred KB. Compression isn't needed.

## 4. Body

One object per machine per cycle. Every section is optional (see section 6).

```json
{
  "collected_at": "2026-11-24T10:00:00Z",
  "machine": {
    "id": "43690069-62f5-4a7c-b02a-c0dd35ba4901",
    "hostname": "FIN-LAPTOP-042",
    "os": "Windows 11 Enterprise 10.0.26300"
  },
  "installed_software": [
    {"name": "Google Chrome", "version": "131.0.6778.86", "publisher": "Google LLC"}
  ],
  "listening_ports": [
    {"protocol": "TCP", "local_address": "0.0.0.0", "port": 445, "pid": 4,
     "process_name": "System", "path": null, "version": null}
  ],
  "processes": [
    {"name": "svchost.exe", "pid": 1996, "path": "C:\\Windows\\System32\\svchost.exe", "version": "10.0.26100.1"}
  ],
  "services": [
    {"name": "Spooler", "display_name": "Print Spooler", "status": "Running", "start_type": "Auto"}
  ]
}
```

### Fields

**Top level**

| Field | Type | Required | Notes |
|---|---|---|---|
| `collected_at` | string, ISO 8601 | recommended | When the data was collected, in UTC (`Z`). If it has no time zone, UTC is assumed. If missing, the server uses the time it received the request, which is wrong for replayed data. |
| `machine` | object | **yes** | See below |
| `installed_software` | array | no | Leave out if not collected this cycle |
| `listening_ports` | array | no | |
| `processes` | array | no | |
| `services` | array | no | |

**`machine`**

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string, UUID | **yes, or `hostname`** | Windows `MachineGuid` (`HKLM\SOFTWARE\Microsoft\Cryptography\MachineGuid`). Stays the same when the machine is renamed, so always send it if you can. |
| `hostname` | string | **yes, or `id`** | Without `id`, the server derives the machine id from the hostname. |
| `os` | string | no | For example `Windows 11 Enterprise 10.0.26300` |

**`installed_software[]`**

| Field | Type | Required |
|---|---|---|
| `name` | string, not empty | **yes** |
| `version` | string | no |
| `publisher` | string | no |

**`listening_ports[]`**

| Field | Type | Required | Notes |
|---|---|---|---|
| `port` | integer 0–65535 | **yes** | |
| `protocol` | string | no | `TCP`, `TCP6`, `UDP`, `UDP6` (stored as sent) |
| `local_address` | string | no | `0.0.0.0`, `::`, `127.0.0.1`, ... Anything other than loopback (`127.*`, `::1`) is shown as **exposed**. |
| `pid` | integer | no | Owning process id |
| `process_name` | string | no | |
| `path` | string | no | Full path of the owning executable |
| `version` | string | no | File version of that executable |

**`processes[]`**

| Field | Type | Required |
|---|---|---|
| `name` | string, not empty | **yes** |
| `pid` | integer | no |
| `path` | string | no |
| `version` | string | no |

**`services[]`**

| Field | Type | Required |
|---|---|---|
| `name` | string, not empty | **yes** (the service key name, e.g. `Spooler`) |
| `display_name` | string | no |
| `status` | string | no (e.g. `Running`, `Stopped`) |
| `start_type` | string | no (e.g. `Auto`, `Manual`, `Disabled`) |

Optional fields can be omitted, `null`, or an empty string. Integers must be JSON numbers, not strings.

## 5. Responses and retries

| Status | Meaning | What the agent should do |
|---|---|---|
| `201 Created` | Stored | Done. Optionally log the snapshot id. |
| `401 Unauthorized` | `X-API-Key` missing or wrong | Log an error. Keep buffering so no data is lost, but don't retry rapidly: it fails until `ApiKey` is fixed. |
| `422 Unprocessable Content` | The body is invalid | **Don't retry**: the same body always fails. Log the response (it names the field) and drop or quarantine that delivery. |
| `5xx`, timeout, connection refused | Server or network problem | Buffer the body and retry later with backoff, as the agent does today. |

**201 response:**

```json
{
  "snapshots": [
    {
      "snapshot_id": "b2fc74b9-3317-4666-8a99-3d578a1b2b44",
      "machine_id": "43690069-62f5-4a7c-b02a-c0dd35ba4901",
      "hostname": "FIN-LAPTOP-042",
      "collected_at": "2026-11-24T10:00:00+00:00",
      "counts": {"installed_software": 120, "listening_ports": 147, "processes": 210, "services": 290}
    }
  ]
}
```

A section that wasn't sent has a count of `null`.

**401 response:**

```json
{"detail": "Missing or invalid X-API-Key header."}
```

**422 response:** `detail` lists the problems. `loc` is the path to the bad field:

```json
{
  "detail": [
    {"type": "missing", "loc": ["body", "InventoryIn", "listening_ports", 0, "port"], "msg": "Field required", "input": {"protocol": "TCP"}},
    {"type": "list_type", "loc": ["body", "list[InventoryIn]"], "msg": "Input should be a valid list", "input": {"...": "..."}}
  ]
}
```

The endpoint accepts either one object or a list, so a 422 also contains an entry saying the body "should be a valid
list". Ignore that entry; the useful one is the other. In this example, the first port has no `port` number.

## 6. Rules and behaviour

**Each POST creates a new snapshot.** The server never overwrites earlier data. History is kept for the server's
`RETENTION_DAYS` (default 30).

**Every section is optional.**

| You send | Server does |
|---|---|
| A section with items | Stores them as that section's new current state |
| A section as an empty list `[]` | Records "collected, none found" (current state becomes empty) |
| No section key at all | "Not collected this cycle": the machine keeps its previous data for that section |

You can therefore send sections at different rates. For example: ports, processes and services every 5 minutes,
installed software once an hour (it rarely changes, and it's often the biggest list).

**Send the original `collected_at`.** The server decides the current state by `collected_at`, not by arrival time.
A buffered delivery replayed hours later lands in history at its real time and doesn't replace newer data. Replay
buffered deliveries oldest first. Keep the agent's clock correct (Windows time sync): a wrong clock puts snapshots
at the wrong place in history.

**Unknown fields are accepted.** Any field not listed in section 4, at any level, is stored as-is (in an `extra`
column). You can add new fields to the agent before the server knows about them; nothing is rejected or lost.

**Batching.** The body may also be a JSON array of objects, for example several buffered cycles in one request.
Each element becomes its own snapshot. The whole request is validated and stored together: if one element is
invalid, the request is rejected with `422` and nothing is stored.

**Duplicates.** If a request reaches the server but the response is lost and the agent retries, the delivery is
stored twice. This doesn't affect the current state and is acceptable for now.

**JSON encoding.** Escape strings properly: `"` → `\"`, `\` → `\\` (paths are full of backslashes), and control
characters as `\uXXXX`. Send UTF-8; software names can contain non-ASCII characters.

## 7. Examples

PowerShell, from any Windows machine (the server must be reachable):

```powershell
$body = @{
  collected_at = (Get-Date).ToUniversalTime().ToString("o")
  machine = @{ hostname = $env:COMPUTERNAME; os = "Windows 11" }
  installed_software = @(@{ name = "7-Zip 24.08 (x64)"; version = "24.08"; publisher = "Igor Pavlov" })
  listening_ports = @(@{ protocol = "TCP"; local_address = "0.0.0.0"; port = 445; pid = 4; process_name = "System" })
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Method Post -Uri "http://localhost:8080/api/v1/inventory" `
  -ContentType "application/json; charset=utf-8" -Body $body `
  -Headers @{ "X-API-Key" = "<key, or remove this header>" }
```

curl:

```bash
curl -X POST "http://localhost:8080/api/v1/inventory" \
  -H "Content-Type: application/json" -H "X-API-Key: <key>" \
  -d '{"collected_at":"2026-11-24T10:00:00Z","machine":{"hostname":"TEST-PC"},"listening_ports":[{"protocol":"TCP","port":3389,"local_address":"0.0.0.0"}]}'
```

You can also send test requests from the browser at `{ServerUrl}/api/docs` (Swagger UI → `POST /api/v1/inventory`
→ "Try it out").

## 8. Changes for the Inventory Agent

The Inventory Agent (C++ Windows service) currently writes each cycle directly into its own PostgreSQL database. To
send to this server, only its **upload step** changes. The collectors (services, processes, ports, installed
software) stay as they are, and the JSON keys match its current table and column names.

1. **Upload:** replace the libpq SQL upload with a WinHTTP `POST` of the JSON body above.
2. **Buffering:** keep the retry and backoff. On final failure, save the **JSON body** to
   `buffer\<UTC timestamp>.json` (instead of `.sql`) and replay oldest first, unchanged (same `collected_at`).
   Apply the table in section 5: drop or quarantine on `422`, keep buffering on `401`.
3. **`config.ini`:** replace `ConnectionString` with:
   ```ini
   # Where to send inventory. Same computer: http://localhost:8080   Hosted: https://<server-domain>
   ServerUrl=http://localhost:8080
   # Shared key from the server admin. Leave empty if the server has none.
   ApiKey=
   IntervalMinutes=5
   ```
   Read both in the config loader, next to `IntervalMinutes`. Since `config.ini` holds the key, keep its file
   permissions restricted.
4. **Remove** the libpq DLLs and the database password from `config.ini`; they're no longer needed.
5. **Optional:** send `installed_software` only once an hour (section 6).

Until this change is made, the server can import what the agent already wrote to its database with
`tools/import_from_agent_db.py` (see the README).

## 9. Testing

- Run the server locally (README, section 3). `ServerUrl=http://localhost:8080`, no key.
- Send a request (section 7) and check the dashboard at `http://localhost:8080`: the machine appears under
  **Machines**, and each request adds a row under **Snapshots**.
- `tools/fake_collector.py` in the server repo sends realistic requests in exactly this format. It's a working
  reference for the body.
- To test the key: set `INGEST_API_KEY=test123` in the server's `.env`, restart it, and confirm that requests without
  the header get `401` and requests with `X-API-Key: test123` get `201`.
