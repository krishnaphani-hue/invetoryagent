"""Poll the agent's own database and import new cycles (bridge until the agent POSTs to /api/v1/inventory).

Krishna's agent (../invetoryagent) writes each collection cycle straight into its PostgreSQL database
`inventory`: rows in services / processes / listening_ports / installed_software that share one
(machine_id, collected_at). Every AGENT_POLL_MINUTES this module reads the cycles collected after the newest
agent snapshot we already have for that machine, and stores each one through `store_delivery` (source "agent",
original collected_at), oldest first, one commit per cycle.

Because only newer cycles are read, polling never creates duplicates. Cycles the agent buffered while its
database was unreachable are still picked up: it flushes them oldest first, before the current cycle.
"""
import asyncio
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.rows import dict_row
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from app import db
from app.config import settings
from app.models import Snapshot
from app.schemas import InventoryIn
from app.services.ingest import store_delivery

# Child of uvicorn's logger so INFO lines show in the server console.
log = logging.getLogger("uvicorn.error.agent_poll")

# Agent table -> columns copied (the same names as our payload fields).
SECTIONS = {
    "installed_software": ["name", "version", "publisher"],
    "listening_ports": ["protocol", "local_address", "port", "pid", "process_name", "path", "version"],
    "processes": ["name", "pid", "path", "version"],
    "services": ["name", "display_name", "status", "start_type"],
}

# Shown in /api/health.
status: dict = {"last_run": None, "last_imported": None, "last_error": None}


def _libpq_url(url: str) -> str:
    """Accept SQLAlchemy-style URLs too (postgresql+psycopg://...)."""
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _watermarks() -> dict[uuid.UUID, datetime]:
    """Newest agent snapshot per machine already stored here."""
    with db.SessionLocal() as session:
        rows = session.execute(
            select(Snapshot.machine_id, func.max(Snapshot.collected_at))
            .where(Snapshot.source == "agent")
            .group_by(Snapshot.machine_id)
        )
        return {m: ts for m, ts in rows}


def poll_agent_db(agent_db_url: str | None = None) -> int:
    """Import cycles that are new since the last import. Returns the number of snapshots stored."""
    url = agent_db_url or settings.agent_db_url
    if not url:
        return 0
    marks = _watermarks()
    # Machines never imported: only cycles inside the retention window (older ones would be purged anyway).
    floor = (
        datetime.now(timezone.utc) - timedelta(days=settings.retention_days)
        if settings.retention_days > 0
        else datetime(1970, 1, 1, tzinfo=timezone.utc)
    )
    ids, seen = list(marks), [marks[m] for m in marks]

    cycles: dict[tuple, dict] = defaultdict(dict)
    with psycopg.connect(_libpq_url(url), row_factory=dict_row, connect_timeout=10) as conn:
        machines = {r["id"]: r for r in conn.execute("SELECT id, hostname, os FROM machines")}
        for table, cols in SECTIONS.items():
            required = "t.name IS NOT NULL" if "name" in cols else "t.port IS NOT NULL"
            sql = (
                f"SELECT t.machine_id, t.collected_at, {', '.join('t.' + c for c in cols)} FROM {table} t "
                "LEFT JOIN unnest(%s::uuid[], %s::timestamptz[]) AS w(machine_id, seen) ON w.machine_id = t.machine_id "
                f"WHERE t.collected_at > COALESCE(w.seen, %s) AND {required}"
            )
            for r in conn.execute(sql, (ids, seen, floor)):
                cycles[(r["machine_id"], r["collected_at"])].setdefault(table, []).append({c: r[c] for c in cols})

    stored = 0
    for (machine_id, collected_at), sections in sorted(cycles.items(), key=lambda kv: kv[0][1]):
        m = machines.get(machine_id, {})
        payload = InventoryIn.model_validate({
            "collected_at": collected_at,
            "machine": {"id": machine_id, "hostname": m.get("hostname"), "os": m.get("os")},
            **sections,
        })
        with db.SessionLocal() as session:
            store_delivery(session, payload, source="agent")
            session.commit()
        stored += 1
    return stored


async def agent_poll_loop() -> None:
    interval = settings.agent_poll_minutes * 60
    log.info("agent poll: reading the agent database every %s min", settings.agent_poll_minutes)
    if settings.online_minutes <= settings.agent_poll_minutes:
        log.warning(
            "agent poll: ONLINE_MINUTES (%s) <= AGENT_POLL_MINUTES (%s): machines will show offline between polls",
            settings.online_minutes, settings.agent_poll_minutes,
        )
    while True:
        status["last_run"] = datetime.now(timezone.utc).isoformat()
        try:
            n = await run_in_threadpool(poll_agent_db)
            status["last_imported"], status["last_error"] = n, None
            log.info("agent poll: imported %s new cycle(s)", n)
        except Exception as e:  # never let the loop die (agent DB down, wrong password, ...)
            status["last_error"] = str(e)
            log.exception("agent poll failed")
        await asyncio.sleep(interval)
