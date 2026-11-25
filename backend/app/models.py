"""Database tables.

machines 1─N snapshots 1─N {installed_software, listening_ports, processes, services}

Every collector run or Excel upload creates one snapshot per machine. Rows are never
overwritten; "current state" is the latest snapshot (by collected_at) that included a section.
"""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Machine(Base):
    __tablename__ = "machines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    hostname: Mapped[str | None] = mapped_column(Text)
    os: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)  # future: login / API key owner
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extra: Mapped[dict | None] = mapped_column(JSONB)


class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    machine_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)  # 'agent' | 'upload_excel'
    filename: Mapped[str | None] = mapped_column(Text)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # NULL = that section was not part of this delivery (so it does not replace the current state)
    software_count: Mapped[int | None] = mapped_column(Integer)
    port_count: Mapped[int | None] = mapped_column(Integer)
    process_count: Mapped[int | None] = mapped_column(Integer)
    service_count: Mapped[int | None] = mapped_column(Integer)
    extra: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (Index("ix_snapshots_machine_collected", "machine_id", collected_at.desc()),)


def _snapshot_fk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("snapshots.id", ondelete="CASCADE"), nullable=False, index=True)


def _machine_fk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), nullable=False, index=True)


class InstalledSoftware(Base):
    __tablename__ = "installed_software"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[uuid.UUID] = _snapshot_fk()
    machine_id: Mapped[uuid.UUID] = _machine_fk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str | None] = mapped_column(Text)
    publisher: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[dict | None] = mapped_column(JSONB)


class ListeningPort(Base):
    __tablename__ = "listening_ports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[uuid.UUID] = _snapshot_fk()
    machine_id: Mapped[uuid.UUID] = _machine_fk()
    protocol: Mapped[str | None] = mapped_column(Text)
    local_address: Mapped[str | None] = mapped_column(Text)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    pid: Mapped[int | None] = mapped_column(Integer)
    process_name: Mapped[str | None] = mapped_column(Text)
    path: Mapped[str | None] = mapped_column(Text)
    version: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[dict | None] = mapped_column(JSONB)


class Process(Base):
    __tablename__ = "processes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[uuid.UUID] = _snapshot_fk()
    machine_id: Mapped[uuid.UUID] = _machine_fk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    pid: Mapped[int | None] = mapped_column(Integer)
    path: Mapped[str | None] = mapped_column(Text)
    version: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[dict | None] = mapped_column(JSONB)


class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[uuid.UUID] = _snapshot_fk()
    machine_id: Mapped[uuid.UUID] = _machine_fk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    start_type: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[dict | None] = mapped_column(JSONB)


class ThreatMatch(Base):
    """A CVE from Advanced-Threat-Intelligence that applies to an installed application.

    Keyed by the application (name + version), not by machine: the API joins it with each machine's current
    software, so the same finding shows up on every machine that has that version installed.
    """
    __tablename__ = "threat_matches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    software_name: Mapped[str] = mapped_column(Text, nullable=False)
    software_version: Mapped[str] = mapped_column(Text, nullable=False, default="")  # '' = version unknown
    cve_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)  # 'vulnerable' | 'review' | 'ruled_out'
    reason: Mapped[str | None] = mapped_column(Text)
    match_token: Mapped[str | None] = mapped_column(Text)  # product word used to tie the finding to listening ports
    vendor: Mapped[str | None] = mapped_column(Text)
    product: Mapped[str | None] = mapped_column(Text)
    vulnerable_range: Mapped[str | None] = mapped_column(Text)
    fixed_version: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str | None] = mapped_column(Text)
    cvss_v3: Mapped[float | None] = mapped_column(Float)
    epss: Mapped[float | None] = mapped_column(Float)
    is_cisa_kev: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_public_poc: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_metasploit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_nuclei: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("software_name", "software_version", "cve_id", name="uq_threat_matches_software_cve"),
        Index("ix_threat_matches_software", "software_name", "software_version"),
        Index("ix_threat_matches_cve", "cve_id"),
    )


class CveRange(Base):
    """Cache of the affected products and version ranges NVD lists for a CVE (one NVD request per CVE).

    ranges is a list of {vendor, product, version, start_incl, start_excl, end_incl, end_excl}, one per vulnerable
    CPE match; [] means NVD has not attached product data to the CVE yet.
    """
    __tablename__ = "threat_cve_ranges"

    cve_id: Mapped[str] = mapped_column(Text, primary_key=True)
    ranges: Mapped[list] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# Section name (as used in payloads / Excel sheets) -> (model, snapshot count column)
SECTIONS: dict[str, tuple[type[Base], str]] = {
    "installed_software": (InstalledSoftware, "software_count"),
    "listening_ports": (ListeningPort, "port_count"),
    "processes": (Process, "process_count"),
    "services": (Service, "service_count"),
}
