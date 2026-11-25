"""Shared query building blocks for "current state"."""
from sqlalchemy import Select, and_, or_, select

from app.models import Snapshot

LOOPBACK_PREFIXES = ("127.",)
LOOPBACK_EXACT = ("::1", "localhost")


def current_snapshot_ids(count_col: str) -> Select:
    """Latest snapshot per machine that included the given section (count column not NULL).

    Ordered by collected_at so replayed/buffered old deliveries never replace newer data.
    """
    col = getattr(Snapshot, count_col)
    return (
        select(Snapshot.id.label("snapshot_id"), Snapshot.machine_id.label("machine_id"))
        .where(col.is_not(None))
        .distinct(Snapshot.machine_id)
        .order_by(Snapshot.machine_id, Snapshot.collected_at.desc(), Snapshot.received_at.desc())
    )


def is_exposed(address_col):
    """Listening on something other than loopback = reachable from the network."""
    return and_(
        address_col.is_not(None),
        address_col.not_in(LOOPBACK_EXACT),
        *[~address_col.startswith(p) for p in LOOPBACK_PREFIXES],
    )


def exposed_py(address: str | None) -> bool:
    if not address:
        return False
    return address not in LOOPBACK_EXACT and not address.startswith(LOOPBACK_PREFIXES)


def ilike_any(term: str, *cols):
    pattern = f"%{term}%"
    return or_(*[c.ilike(pattern) for c in cols])
