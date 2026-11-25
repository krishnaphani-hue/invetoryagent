"""Read-only endpoints used by the dashboard."""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, distinct, func, or_, select
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.deps import get_current_owner, scope_machines
from app.models import SECTIONS, InstalledSoftware, ListeningPort, Machine, Snapshot
from app.services.queries import current_snapshot_ids, exposed_py, ilike_any, is_exposed

router = APIRouter(prefix="/api/v1", tags=["read"])

SECTION_ROUTES = {
    "software": "installed_software",
    "ports": "listening_ports",
    "processes": "processes",
    "services": "services",
}


# ---------- helpers ----------

def _row(obj, *cols: str) -> dict:
    out = {}
    for c in cols:
        v = getattr(obj, c)
        if isinstance(v, uuid.UUID):
            v = str(v)
        elif isinstance(v, datetime):
            v = v.isoformat()
        out[c] = v
    return out


MACHINE_COLS = ("id", "hostname", "os", "first_seen", "last_seen", "extra")
SNAPSHOT_COLS = ("id", "machine_id", "source", "filename", "collected_at", "received_at",
                 "software_count", "port_count", "process_count", "service_count", "extra")


def _online_cutoff() -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=settings.online_minutes)


def _latest_count(count_col: str):
    col = getattr(Snapshot, count_col)
    return (
        select(col)
        .where(Snapshot.machine_id == Machine.id, col.is_not(None))
        .order_by(Snapshot.collected_at.desc(), Snapshot.received_at.desc())
        .limit(1)
        .scalar_subquery()
    )


def _get_machine(session: Session, machine_id: uuid.UUID, owner_id) -> Machine:
    m = session.execute(scope_machines(select(Machine).where(Machine.id == machine_id), owner_id)).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="Machine not found")
    return m


def _current_rows(model, count_col: str) -> Select:
    """Rows of `model` that belong to each machine's current snapshot for that section."""
    cur = current_snapshot_ids(count_col).subquery()
    return select(model, Machine.hostname).join(cur, cur.c.snapshot_id == model.snapshot_id).join(
        Machine, Machine.id == model.machine_id
    )


# ---------- dashboard ----------

def _machine_filters(machine_id: list[uuid.UUID], os: str | None, status: str | None) -> list:
    """Dashboard filters, as conditions on Machine (every /stats query joins Machine)."""
    conds = []
    if machine_id:
        conds.append(Machine.id.in_(machine_id))
    if os:
        conds.append(Machine.os == os)
    if status == "online":
        conds.append(Machine.last_seen >= _online_cutoff())
    elif status == "offline":
        conds.append(or_(Machine.last_seen.is_(None), Machine.last_seen < _online_cutoff()))
    return conds


@router.get("/stats")
def stats(
    machine_id: list[uuid.UUID] = Query(default=[], description="Only these machines (repeat the parameter)"),
    os: str | None = Query(None, description="Only machines with exactly this OS string"),
    status: Literal["online", "offline"] | None = None,
    hours: int = Query(24, ge=1, le=24 * 90, description="Period for the snapshot count and the latest list"),
    session: Session = Depends(get_session),
    owner_id=Depends(get_current_owner),
):
    f = _machine_filters(machine_id, os, status)
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    machines_total = session.scalar(scope_machines(select(func.count(Machine.id)).where(*f), owner_id))
    online = session.scalar(
        scope_machines(select(func.count(Machine.id)).where(*f, Machine.last_seen >= _online_cutoff()), owner_id)
    )
    snapshots_recent = session.scalar(
        scope_machines(
            select(func.count(Snapshot.id)).join(Machine, Machine.id == Snapshot.machine_id)
            .where(*f, Snapshot.received_at >= since),
            owner_id,
        )
    )

    sw = scope_machines(_current_rows(InstalledSoftware, "software_count").where(*f), owner_id).subquery()
    unique_apps = session.scalar(select(func.count(distinct(func.lower(sw.c.name)))))

    ports = scope_machines(_current_rows(ListeningPort, "port_count").where(*f), owner_id).subquery()
    exposed_ports = session.scalar(
        select(func.count()).select_from(
            select(ports.c.machine_id, ports.c.protocol, ports.c.port)
            .where(is_exposed(ports.c.local_address))
            .distinct()
            .subquery()
        )
    )

    top_software = [
        {"name": r.name, "publisher": r.publisher, "machine_count": r.machine_count}
        for r in session.execute(
            select(sw.c.name, func.max(sw.c.publisher).label("publisher"),
                   func.count(distinct(sw.c.machine_id)).label("machine_count"))
            .group_by(sw.c.name)
            .order_by(func.count(distinct(sw.c.machine_id)).desc(), sw.c.name)
            .limit(10)
        )
    ]
    top_ports = [
        {"protocol": r.protocol, "port": r.port, "machine_count": r.machine_count, "exposed": r.exposed}
        for r in session.execute(
            select(ports.c.protocol, ports.c.port,
                   func.count(distinct(ports.c.machine_id)).label("machine_count"),
                   func.bool_or(is_exposed(ports.c.local_address)).label("exposed"))
            .group_by(ports.c.protocol, ports.c.port)
            .order_by(func.count(distinct(ports.c.machine_id)).desc(), ports.c.port)
            .limit(10)
        )
    ]
    recent = session.execute(
        scope_machines(
            select(Snapshot, Machine.hostname).join(Machine, Machine.id == Snapshot.machine_id)
            .where(*f, Snapshot.received_at >= since)
            .order_by(Snapshot.received_at.desc()).limit(10),
            owner_id,
        )
    ).all()

    return {
        "machines": machines_total,
        "online": online,
        "online_minutes": settings.online_minutes,
        "period_hours": hours,
        "snapshots_recent": snapshots_recent,
        "unique_apps": unique_apps,
        "exposed_ports": exposed_ports,
        "top_software": top_software,
        "top_ports": top_ports,
        "recent_snapshots": [{**_row(s, *SNAPSHOT_COLS), "hostname": h} for s, h in recent],
    }


# ---------- machines ----------

@router.get("/machines")
def list_machines(
    q: str | None = None,
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
    owner_id=Depends(get_current_owner),
):
    snapshot_count = select(func.count(Snapshot.id)).where(Snapshot.machine_id == Machine.id).scalar_subquery()
    stmt = select(
        Machine,
        snapshot_count.label("snapshot_count"),
        _latest_count("software_count").label("software_count"),
        _latest_count("port_count").label("port_count"),
        _latest_count("process_count").label("process_count"),
        _latest_count("service_count").label("service_count"),
    )
    if q:
        stmt = stmt.where(ilike_any(q, Machine.hostname, Machine.os))
    stmt = scope_machines(stmt, owner_id)
    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = session.execute(stmt.order_by(Machine.hostname).limit(limit).offset(offset)).all()
    cutoff = _online_cutoff()
    items = []
    for r in rows:
        m = r[0]
        items.append({
            **_row(m, *MACHINE_COLS),
            "online": bool(m.last_seen and m.last_seen >= cutoff),
            "snapshot_count": r.snapshot_count,
            "software_count": r.software_count,
            "port_count": r.port_count,
            "process_count": r.process_count,
            "service_count": r.service_count,
        })
    return {"total": total, "items": items}


@router.get("/machines/{machine_id}")
def get_machine(machine_id: uuid.UUID, session: Session = Depends(get_session), owner_id=Depends(get_current_owner)):
    m = _get_machine(session, machine_id, owner_id)
    snapshot_count = session.scalar(select(func.count(Snapshot.id)).where(Snapshot.machine_id == m.id))
    return {
        **_row(m, *MACHINE_COLS),
        "online": bool(m.last_seen and m.last_seen >= _online_cutoff()),
        "snapshot_count": snapshot_count,
    }


@router.get("/machines/{machine_id}/snapshots")
def machine_snapshots(
    machine_id: uuid.UUID,
    limit: int = Query(500, ge=1, le=5000),
    session: Session = Depends(get_session),
    owner_id=Depends(get_current_owner),
):
    _get_machine(session, machine_id, owner_id)
    rows = session.execute(
        select(Snapshot).where(Snapshot.machine_id == machine_id)
        .order_by(Snapshot.collected_at.desc(), Snapshot.received_at.desc()).limit(limit)
    ).scalars()
    return {"items": [_row(s, *SNAPSHOT_COLS) for s in rows]}


@router.get("/machines/{machine_id}/{section}")
def machine_section(
    machine_id: uuid.UUID,
    section: Literal["software", "ports", "processes", "services"],
    snapshot_id: uuid.UUID | None = None,
    session: Session = Depends(get_session),
    owner_id=Depends(get_current_owner),
):
    """Rows of one section for a machine: the current snapshot by default, or a specific one."""
    _get_machine(session, machine_id, owner_id)
    table = SECTION_ROUTES[section]
    model, count_col = SECTIONS[table]

    if snapshot_id is not None:
        snap = session.execute(
            select(Snapshot).where(Snapshot.id == snapshot_id, Snapshot.machine_id == machine_id)
        ).scalar_one_or_none()
        if snap is None:
            raise HTTPException(status_code=404, detail="Snapshot not found for this machine")
    else:
        snap = session.execute(
            select(Snapshot).where(Snapshot.machine_id == machine_id, getattr(Snapshot, count_col).is_not(None))
            .order_by(Snapshot.collected_at.desc(), Snapshot.received_at.desc()).limit(1)
        ).scalar_one_or_none()

    if snap is None:
        return {"snapshot": None, "included": False, "items": []}

    order_cols = {
        "installed_software": ["name"],
        "listening_ports": ["port", "protocol"],
        "processes": ["name", "pid"],
        "services": ["name"],
    }[table]
    order = [getattr(model, c) for c in order_cols]
    rows = session.execute(select(model).where(model.snapshot_id == snap.id).order_by(*order)).scalars()
    cols = [c.key for c in model.__table__.columns if c.key not in ("snapshot_id", "machine_id")]
    items = []
    for r in rows:
        d = _row(r, *cols)
        if table == "listening_ports":
            d["exposed"] = exposed_py(r.local_address)
        items.append(d)
    return {
        "snapshot": _row(snap, *SNAPSHOT_COLS),
        "included": getattr(snap, count_col) is not None,
        "items": items,
    }


# ---------- snapshots ----------

@router.get("/snapshots")
def list_snapshots(
    source: str | None = None,
    limit: int = Query(500, ge=1, le=5000),
    session: Session = Depends(get_session),
    owner_id=Depends(get_current_owner),
):
    stmt = select(Snapshot, Machine.hostname).join(Machine, Machine.id == Snapshot.machine_id)
    if source:
        stmt = stmt.where(Snapshot.source == source)
    stmt = scope_machines(stmt, owner_id).order_by(Snapshot.received_at.desc()).limit(limit)
    return {"items": [{**_row(s, *SNAPSHOT_COLS), "hostname": h} for s, h in session.execute(stmt).all()]}


@router.get("/snapshots/{snapshot_id}")
def get_snapshot(snapshot_id: uuid.UUID, session: Session = Depends(get_session), owner_id=Depends(get_current_owner)):
    row = session.execute(
        scope_machines(
            select(Snapshot, Machine.hostname).join(Machine, Machine.id == Snapshot.machine_id)
            .where(Snapshot.id == snapshot_id),
            owner_id,
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return {**_row(row[0], *SNAPSHOT_COLS), "hostname": row[1]}


# ---------- fleet-wide inventory ----------

def _machines_agg(sub, *extra_keys):
    """JSON array of {id, hostname, ...} for the machines in a group."""
    pairs = []
    for key in ("id", "hostname", *extra_keys):
        col = sub.c.machine_id if key == "id" else sub.c[key]
        pairs += [key, col]
    return func.jsonb_agg(aggregate_order_by(func.jsonb_build_object(*pairs), sub.c.hostname))


@router.get("/software")
def fleet_software(
    q: str | None = None,
    limit: int = Query(2000, ge=1, le=20000),
    session: Session = Depends(get_session),
    owner_id=Depends(get_current_owner),
):
    """Current installed software across all machines, grouped by name / publisher / version."""
    base = scope_machines(_current_rows(InstalledSoftware, "software_count"), owner_id)
    if q:
        base = base.where(ilike_any(q, InstalledSoftware.name, InstalledSoftware.publisher))
    sub = base.subquery()
    rows = session.execute(
        select(sub.c.name, sub.c.publisher, sub.c.version,
               func.count(distinct(sub.c.machine_id)).label("machine_count"),
               _machines_agg(sub).label("machines"))
        .group_by(sub.c.name, sub.c.publisher, sub.c.version)
        .order_by(func.count(distinct(sub.c.machine_id)).desc(), sub.c.name, sub.c.version)
        .limit(limit)
    ).all()
    return {"items": [
        {"name": r.name, "publisher": r.publisher, "version": r.version,
         "machine_count": r.machine_count, "machines": r.machines}
        for r in rows
    ]}


@router.get("/ports")
def fleet_ports(
    q: str | None = None,
    exposed_only: bool = False,
    limit: int = Query(2000, ge=1, le=20000),
    session: Session = Depends(get_session),
    owner_id=Depends(get_current_owner),
):
    """Current listening ports across all machines, grouped by protocol / port / process."""
    base = scope_machines(_current_rows(ListeningPort, "port_count"), owner_id)
    if q:
        base = base.where(ilike_any(q, ListeningPort.process_name, ListeningPort.path))
    if exposed_only:
        base = base.where(is_exposed(ListeningPort.local_address))
    sub = base.subquery()
    rows = session.execute(
        select(sub.c.protocol, sub.c.port, sub.c.process_name,
               func.count(distinct(sub.c.machine_id)).label("machine_count"),
               func.bool_or(is_exposed(sub.c.local_address)).label("exposed"),
               _machines_agg(sub, "local_address", "version").label("machines"))
        .group_by(sub.c.protocol, sub.c.port, sub.c.process_name)
        .order_by(sub.c.port, sub.c.protocol)
        .limit(limit)
    ).all()
    return {"items": [
        {"protocol": r.protocol, "port": r.port, "process_name": r.process_name,
         "machine_count": r.machine_count, "exposed": r.exposed, "machines": r.machines}
        for r in rows
    ]}
