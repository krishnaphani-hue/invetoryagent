import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import get_current_owner, require_ingest_key
from app.schemas import InventoryIn
from app.services.ingest import store_delivery

router = APIRouter(prefix="/api/v1", tags=["collector"], dependencies=[Depends(require_ingest_key)])


@router.post("/inventory", status_code=201)
def receive_inventory(
    payload: InventoryIn | list[InventoryIn],
    session: Session = Depends(get_session),
    owner_id: uuid.UUID | None = Depends(get_current_owner),
):
    """Collector endpoint. Accepts one machine's delivery, or a list of them.

    Each delivery becomes a new snapshot (id generated here and returned).
    """
    deliveries = payload if isinstance(payload, list) else [payload]
    try:
        results = [store_delivery(session, d, source="agent", owner_id=owner_id) for d in deliveries]
        session.commit()
    except Exception:
        session.rollback()
        raise
    return {"snapshots": results}
