"""Pretend to be Krishna's agent: POST inventory JSON to the server.

Examples (backend venv):
  python tools/fake_collector.py                               # 3 sample machines, 1 run
  python tools/fake_collector.py --machines 5 --runs 3         # 5 machines, 3 runs each (versions drift)
  python tools/fake_collector.py --runs 0 --interval 300       # forever, every 5 minutes like the agent
"""
import argparse
import time
from datetime import datetime, timezone

import httpx

from client_config import default_api_key, headers
from sample_data import MACHINES, inventory_for, random_machine


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:8080", help="server base URL (run.ps1: 8080, dev.ps1: 8000)")
    ap.add_argument("--api-key", default=default_api_key(), help="X-API-Key (default: INGEST_API_KEY from .env)")
    ap.add_argument("--machines", type=int, default=3, help="number of machines (first 3 are the realistic samples)")
    ap.add_argument("--runs", type=int, default=1, help="deliveries per machine (0 = forever)")
    ap.add_argument("--interval", type=float, default=2.0, help="seconds between runs")
    args = ap.parse_args()

    machines = MACHINES[: args.machines] + [random_machine(i) for i in range(1, max(0, args.machines - len(MACHINES)) + 1)]
    endpoint = args.url.rstrip("/") + "/api/v1/inventory"
    run = 0
    with httpx.Client(timeout=30, headers=headers(args.api_key)) as client:
        while args.runs == 0 or run < args.runs:
            run += 1
            for m in machines:
                body = inventory_for(m, drift=run > 1)
                body["collected_at"] = datetime.now(timezone.utc).isoformat()
                r = client.post(endpoint, json=body)
                r.raise_for_status()
                snap = r.json()["snapshots"][0]
                print(f"run {run}: {m['hostname']:<16} -> snapshot {snap['snapshot_id']}  {snap['counts']}")
            if args.runs == 0 or run < args.runs:
                time.sleep(args.interval)


if __name__ == "__main__":
    main()
