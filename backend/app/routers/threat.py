"""Vulnerable software per machine: installed applications matched against Advanced-Threat-Intelligence CVEs.

Findings are stored per application (threat_matches, see services/threat_intel.py) and joined here with each
machine's current software, so every machine that has an affected version installed gets the finding.
"""
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import Integer, Select, and_, case, distinct, func, literal_column, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.deps import get_current_owner, scope_machines
from app.models import CveRange, InstalledSoftware, ListeningPort, Machine, ThreatMatch
from app.services import threat_intel
from app.services.queries import current_snapshot_ids, exposed_py, ilike_any

router = APIRouter(prefix="/api/v1/vulnerabilities", tags=["threat-intel"])

ACTIONABLE = ("vulnerable", "review")
TM = ThreatMatch
_HAS_EXPLOIT = or_(TM.has_public_poc, TM.has_metasploit, TM.has_nuclei)

# 0-100, higher = fix first. CVSS dominates; CISA KEV (known exploited), a public exploit and EPSS raise it.
RISK = func.least(
    100,
    func.round(
        func.coalesce(TM.cvss_v3, 0) * 5
        + case((TM.is_cisa_kev, 30), else_=0)
        + case((_HAS_EXPLOIT, 15), else_=0)
        + func.coalesce(TM.epss, 0) * 15
    ).cast(Integer),
)


def _findings(owner_id, status: str, machine_id: list[uuid.UUID], q: str | None, kev_only: bool,
              exploit_only: bool, severity: list[str]) -> Select:
    """Matches joined with the current software of every machine, with the filters applied."""
    cur = current_snapshot_ids("software_count").subquery()
    version = func.coalesce(InstalledSoftware.version, literal_column("''"))
    stmt = (
        select(
            InstalledSoftware.machine_id, Machine.hostname,
            InstalledSoftware.name.label("software_name"), InstalledSoftware.version.label("software_version"),
            InstalledSoftware.publisher, TM, RISK.label("risk"),
        )
        .join(cur, cur.c.snapshot_id == InstalledSoftware.snapshot_id)
        .join(Machine, Machine.id == InstalledSoftware.machine_id)
        .join(TM, and_(TM.software_name == InstalledSoftware.name, TM.software_version == version))
    )
    if status == "actionable":
        stmt = stmt.where(TM.status.in_(ACTIONABLE))
    elif status != "all":
        stmt = stmt.where(TM.status == status)
    if machine_id:
        stmt = stmt.where(InstalledSoftware.machine_id.in_(machine_id))
    if q:
        stmt = stmt.where(ilike_any(q, InstalledSoftware.name, TM.cve_id, Machine.hostname, TM.product))
    if kev_only:
        stmt = stmt.where(TM.is_cisa_kev)
    if exploit_only:
        stmt = stmt.where(_HAS_EXPLOIT)
    if severity:
        stmt = stmt.where(func.lower(TM.severity).in_([s.lower() for s in severity]))
    return scope_machines(stmt, owner_id)


@router.get("")
def list_vulnerabilities(
    status: Literal["actionable", "vulnerable", "review", "ruled_out", "all"] = "actionable",
    machine_id: list[uuid.UUID] = Query(default=[]),
    q: str | None = None,
    kev_only: bool = False,
    exploit_only: bool = False,
    severity: list[str] = Query(default=[], description="Critical / High / Medium / Low (repeat the parameter)"),
    limit: int = Query(1000, ge=1, le=10000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
    owner_id=Depends(get_current_owner),
):
    """Findings, riskiest first: one row per machine, application and CVE."""
    base = _findings(owner_id, status, machine_id, q, kev_only, exploit_only, severity)
    total = session.scalar(select(func.count()).select_from(base.subquery()))
    rank = case((TM.status == "vulnerable", 0), (TM.status == "review", 1), else_=2)
    rows = session.execute(
        base.order_by(rank, RISK.desc(), TM.cve_id, Machine.hostname).limit(limit).offset(offset)
    ).all()

    # Listening ports of the same machines whose program path / name contains the application's product word.
    ports: dict[uuid.UUID, list[tuple]] = {}
    machine_ids = {r.machine_id for r in rows}
    if machine_ids:
        pcur = current_snapshot_ids("port_count").subquery()
        for p in session.execute(
            select(ListeningPort).join(pcur, pcur.c.snapshot_id == ListeningPort.snapshot_id)
            .where(ListeningPort.machine_id.in_(machine_ids))
        ).scalars():
            ports.setdefault(p.machine_id, []).append(
                (p.protocol, p.port, exposed_py(p.local_address), f"{p.path or ''} {p.process_name or ''}".lower())
            )

    items = []
    for r in rows:
        m: ThreatMatch = r.ThreatMatch
        tied = []
        for proto, port, exposed, hay in ports.get(r.machine_id, []):
            if m.match_token and m.match_token in hay and (proto, port) not in {(t["protocol"], t["port"]) for t in tied}:
                tied.append({"protocol": proto, "port": port, "exposed": exposed})
        tied.sort(key=lambda t: (not t["exposed"], t["port"]))
        items.append({
            "machine_id": str(r.machine_id), "hostname": r.hostname,
            "software_name": r.software_name, "software_version": r.software_version, "publisher": r.publisher,
            "cve_id": m.cve_id, "status": m.status, "reason": m.reason, "risk": r.risk,
            "severity": m.severity, "cvss_v3": m.cvss_v3, "epss": m.epss,
            "is_cisa_kev": m.is_cisa_kev, "has_public_poc": m.has_public_poc,
            "has_metasploit": m.has_metasploit, "has_nuclei": m.has_nuclei,
            "vulnerable_range": m.vulnerable_range, "fixed_version": m.fixed_version,
            "matched_vendor": m.vendor, "matched_product": m.product, "ai_summary": m.ai_summary,
            "exposed": any(t["exposed"] for t in tied), "ports": tied[:8],
        })
    return {"total": total, "items": items}


@router.get("/summary")
def summary(
    machine_id: list[uuid.UUID] = Query(default=[]),
    session: Session = Depends(get_session),
    owner_id=Depends(get_current_owner),
):
    """Headline numbers for findings that need action (status vulnerable or review)."""
    sub = _findings(owner_id, "actionable", machine_id, None, False, False, []).subquery()
    t = sub.c
    agg = session.execute(
        select(
            func.count().label("findings"),
            func.count(distinct(t.machine_id)).label("machines"),
            func.count(distinct(t.software_name)).label("applications"),
            func.count(distinct(t.cve_id)).label("cves"),
            func.count().filter(t.status == "vulnerable").label("vulnerable"),
            func.count().filter(t.status == "review").label("review"),
            func.count().filter(t.is_cisa_kev).label("kev"),
            func.count().filter(or_(t.has_public_poc, t.has_metasploit, t.has_nuclei)).label("exploit"),
        )
    ).one()
    by_severity = {
        (sev or "Unknown"): n
        for sev, n in session.execute(select(t.severity, func.count()).group_by(t.severity))
    }
    top = session.execute(
        select(t.cve_id, func.max(t.severity).label("severity"), func.max(t.cvss_v3).label("cvss_v3"),
               func.bool_or(t.is_cisa_kev).label("is_cisa_kev"), func.max(t.risk).label("risk"),
               func.count(distinct(t.machine_id)).label("machines"), func.min(t.software_name).label("software"))
        .group_by(t.cve_id).order_by(func.max(t.risk).desc(), t.cve_id).limit(10)
    ).all()
    return {
        "findings": agg.findings, "machines": agg.machines, "applications": agg.applications, "cves": agg.cves,
        "vulnerable": agg.vulnerable, "review": agg.review, "kev": agg.kev, "exploit": agg.exploit,
        "by_severity": by_severity,
        "top_cves": [dict(r._mapping) for r in top],
    }


@router.get("/status")
def threat_status(session: Session = Depends(get_session)):
    """Is the ATI integration on, when did it last run, what did it find."""
    return {
        "enabled": bool(settings.ati_url),
        "ati_url": settings.ati_url or None,
        "poll_minutes": settings.ati_poll_minutes,
        "max_range_lookups": settings.nvd_max_lookups,
        "cached_ranges": session.scalar(select(func.count()).select_from(CveRange)),
        "stored_findings": session.scalar(select(func.count()).select_from(ThreatMatch)),
        **threat_intel.status,
    }


@router.post("/scan", status_code=202)
def start_scan():
    """Match the installed software against ATI now (runs in the background; poll /status)."""
    if not settings.ati_url:
        raise HTTPException(status_code=503, detail="ATI_URL is not set. Point it at a running Advanced-Threat-Intelligence server.")
    if not threat_intel.start_scan_in_background():
        return JSONResponse(status_code=409, content={"detail": "A scan is already running."})
    return {"status": "started"}
