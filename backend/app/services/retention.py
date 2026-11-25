"""Delete snapshots older than RETENTION_DAYS (their rows go with them via ON DELETE CASCADE)."""
import asyncio
import logging

from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from app import db
from app.config import settings

log = logging.getLogger("retention")


def purge_old_snapshots(days: int | None = None) -> int:
    days = settings.retention_days if days is None else days
    if days <= 0:
        return 0
    with db.SessionLocal() as session:
        result = session.execute(
            text("DELETE FROM snapshots WHERE collected_at < now() - make_interval(days => :days)"),
            {"days": days},
        )
        session.commit()
        return result.rowcount or 0


async def retention_loop(interval_seconds: int = 24 * 3600) -> None:
    while True:
        try:
            deleted = await run_in_threadpool(purge_old_snapshots)
            if deleted:
                log.info("retention: deleted %s snapshots older than %s days", deleted, settings.retention_days)
        except Exception:  # never let the loop die
            log.exception("retention cleanup failed")
        await asyncio.sleep(interval_seconds)
