"""Store deliveries. Shared by the collector endpoint and the Excel upload.

Append-only: each delivery becomes one new snapshot per machine. Nothing is overwritten.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, insert, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import SECTIONS, Machine, Snapshot
from app.schemas import InventoryIn

# Fixed namespace so the same hostname always maps to the same machine id.
HOSTNAME_NAMESPACE = uuid.UUID("6f1c2d3e-4b5a-4c6d-8e7f-90a1b2c3d4e5")


def machine_id_for(payload: InventoryIn) -> uuid.UUID:
    if payload.machine.id is not None:
        return payload.machine.id
    return uuid.uuid5(HOSTNAME_NAMESPACE, payload.machine.hostname.strip().lower())


def _upsert_machine(session: Session, machine_id: uuid.UUID, payload: InventoryIn, owner_id: uuid.UUID | None) -> None:
    m = payload.machine
    stmt = pg_insert(Machine).values(
        id=machine_id,
        hostname=m.hostname,
        os=m.os,
        owner_id=owner_id,
        last_seen=func.now(),
        extra=m.extra_fields(),
    )
    excluded = stmt.excluded
    stmt = stmt.on_conflict_do_update(
        index_elements=[Machine.id],
        set_={
            "hostname": func.coalesce(excluded.hostname, Machine.hostname),
            "os": func.coalesce(excluded.os, Machine.os),
            "owner_id": func.coalesce(excluded.owner_id, Machine.owner_id),
            "last_seen": func.now(),
            # merge new extra keys into existing ones
            "extra": text("COALESCE(machines.extra, '{}'::jsonb) || COALESCE(excluded.extra, '{}'::jsonb)"),
        },
    )
    session.execute(stmt)


def store_delivery(
    session: Session,
    payload: InventoryIn,
    *,
    source: str,
    filename: str | None = None,
    owner_id: uuid.UUID | None = None,
) -> dict:
    """Insert one machine's delivery. The caller owns the transaction (commit/rollback)."""
    machine_id = machine_id_for(payload)
    _upsert_machine(session, machine_id, payload, owner_id)

    snapshot = Snapshot(
        machine_id=machine_id,
        source=source,
        filename=filename,
        collected_at=payload.collected_at or datetime.now(timezone.utc),
        extra=payload.extra_fields(),
    )
    counts: dict[str, int | None] = {}
    for section, (_, count_col) in SECTIONS.items():
        items = getattr(payload, section)
        counts[section] = None if items is None else len(items)
        setattr(snapshot, count_col, counts[section])
    session.add(snapshot)
    session.flush()  # assigns snapshot.id

    for section, (model, _) in SECTIONS.items():
        items = getattr(payload, section)
        if not items:
            continue
        rows = [
            {**item.known(), "extra": item.extra_fields(), "snapshot_id": snapshot.id, "machine_id": machine_id}
            for item in items
        ]
        session.execute(insert(model), rows)

    return {
        "snapshot_id": str(snapshot.id),
        "machine_id": str(machine_id),
        "hostname": payload.machine.hostname,
        "collected_at": snapshot.collected_at.isoformat(),
        "counts": counts,
    }
