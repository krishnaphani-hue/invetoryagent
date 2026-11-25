import asyncio
import contextlib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app import db
from app.config import settings
from app.routers import ingest, read, threat, upload
from app.services import agent_poller, threat_intel
from app.services.retention import retention_loop


def _agent_poll_enabled() -> bool:
    return bool(settings.agent_db_url) and settings.agent_poll_minutes > 0


def _ati_loop_enabled() -> bool:
    return bool(settings.ati_url) and settings.ati_poll_minutes > 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = []
    if settings.run_background_tasks:
        tasks.append(asyncio.create_task(retention_loop()))
        if _agent_poll_enabled():
            tasks.append(asyncio.create_task(agent_poller.agent_poll_loop()))
        if _ati_loop_enabled():
            tasks.append(asyncio.create_task(threat_intel.ati_loop()))
    yield
    for task in tasks:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="Asset Inventory Server",
    description="Receives software / port / process / service inventory from collectors and Excel uploads.",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.include_router(ingest.router)
app.include_router(upload.router)
app.include_router(read.router)
app.include_router(threat.router)


@app.get("/api/health", tags=["system"])
def health():
    with db.engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    result = {"status": "ok", "retention_days": settings.retention_days}
    if _agent_poll_enabled():
        result["agent_poll"] = {"every_minutes": settings.agent_poll_minutes, **agent_poller.status}
    if settings.ati_url:
        result["threat_intel"] = {"ati_url": settings.ati_url, "every_minutes": settings.ati_poll_minutes, **threat_intel.status}
    return result


# ---- Serve the built React app (frontend/dist) when it exists: one process, one port. ----
dist: Path = settings.frontend_dist
if (dist / "index.html").exists():
    if (dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")  # client-side routing fallback
