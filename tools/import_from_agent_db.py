"""Bridge: copy data from Krishna's agent database (direct-DB mode) into this server via the API.

His agent (demo/invetoryagent) writes full snapshots to a Postgres database `inventory`, one set of
rows per cycle sharing a `collected_at`. This script groups rows by (machine_id, collected_at) and
POSTs each group to /api/v1/inventory, so the dashboard shows real machines before the agent is
switched to HTTP. Original timestamps are preserved.

Examples (backend venv):
  python tools/import_from_agent_db.py --agent-db "postgresql://agent:change_me@localhost:5432/inventory" --latest-only
  python tools/import_from_agent_db.py --agent-db "..." --since 2026-11-20
Note: running it twice imports the same cycles twice (no de-duplication in this PoC).
"""
import argparse
from collections import defaultdict
from datetime import datetime

import httpx
import psycopg
from psycopg.rows import dict_row

from client_config import default_api_key, headers

SECTIONS = {
    "installed_software": ["name", "version", "publisher"],
    "listening_ports": ["protocol", "local_address", "port", "pid", "process_name", "path", "version"],
    "processes": ["name", "pid", "path", "version"],
    "services": ["name", "display_name", "status", "start_type"],
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agent-db", required=True, help="libpq URL of the agent's database")
    ap.add_argument("--url", default="http://localhost:8080", help="this server's base URL (run.ps1: 8080, dev.ps1: 8000)")
    ap.add_argument("--api-key", default=default_api_key(), help="X-API-Key (default: INGEST_API_KEY from .env)")
    ap.add_argument("--since", help="only cycles collected on/after this date (YYYY-MM-DD)")
    ap.add_argument("--latest-only", action="store_true", help="only the newest cycle per machine and section")
    args = ap.parse_args()

    since = datetime.fromisoformat(args.since) if args.since else None
    deliveries: dict[tuple, dict] = defaultdict(dict)

    with psycopg.connect(args.agent_db, row_factory=dict_row) as conn:
        machines = {r["id"]: r for r in conn.execute("SELECT id, hostname, os FROM machines")}
        for table, cols in SECTIONS.items():
            where, params = ["name IS NOT NULL" if "name" in cols else "port IS NOT NULL"], []
            if since:
                where.append("collected_at >= %s")
                params.append(since)
            if args.latest_only:
                where.append(f"(machine_id, collected_at) IN (SELECT machine_id, max(collected_at) FROM {table} GROUP BY machine_id)")
            sql = f"SELECT machine_id, collected_at, {', '.join(cols)} FROM {table} WHERE {' AND '.join(where)}"
            for r in conn.execute(sql, params):
                key = (r["machine_id"], r["collected_at"])
                deliveries[key].setdefault(table, []).append({c: r[c] for c in cols})

    if not deliveries:
        print("Nothing to import.")
        return

    endpoint = args.url.rstrip("/") + "/api/v1/inventory"
    with httpx.Client(timeout=60, headers=headers(args.api_key)) as client:
        for (machine_id, collected_at), sections in sorted(deliveries.items(), key=lambda kv: kv[0][1]):
            m = machines.get(machine_id, {})
            body = {
                "collected_at": collected_at.isoformat(),
                "machine": {"id": str(machine_id), "hostname": m.get("hostname"), "os": m.get("os")},
                **sections,
            }
            r = client.post(endpoint, json=body)
            r.raise_for_status()
            counts = {k: len(v) for k, v in sections.items()}
            print(f"{collected_at.isoformat()}  {m.get('hostname')}: {counts}")
    print(f"Imported {len(deliveries)} deliveries.")


if __name__ == "__main__":
    main()
