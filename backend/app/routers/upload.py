import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.deps import get_current_owner
from app.services.excel_parser import ExcelError, parse_workbook
from app.services.ingest import store_delivery

router = APIRouter(prefix="/api/v1", tags=["upload"])


@router.post("/uploads", status_code=201)
def upload_excel(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    owner_id: uuid.UUID | None = Depends(get_current_owner),
):
    """Upload an .xlsx workbook. All-or-nothing: any invalid row rejects the whole file."""
    name = file.filename or "upload.xlsx"
    if not name.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx files are supported.")
    content = file.file.read()  # sync route: FastAPI runs it in a worker thread
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File is larger than {settings.max_upload_mb} MB.")

    try:
        deliveries = parse_workbook(content)
    except ExcelError as exc:
        return JSONResponse(status_code=422, content={"detail": "The workbook has errors.", "errors": exc.errors})

    try:
        results = [
            store_delivery(session, d, source="upload_excel", filename=name, owner_id=owner_id) for d in deliveries
        ]
        session.commit()
    except Exception:
        session.rollback()
        raise
    return {"filename": name, "snapshots": results}
