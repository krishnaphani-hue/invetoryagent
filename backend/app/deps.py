"""Ownership hooks, prepared for future login / API keys.

Today there is no authentication: get_current_owner() returns None and scope_machines()
returns everything. Later, get_current_owner() will resolve an X-API-Key header (collector)
or a login session (dashboard) to an owner id, ingest will store it on machines.owner_id,
and scope_machines() will filter by it. Endpoints call these two functions already, so
adding auth will not change any route.
"""
import secrets
import uuid

from fastapi import Header, HTTPException
from sqlalchemy import Select

from app.config import settings
from app.models import Machine


def require_ingest_key(x_api_key: str | None = Header(default=None)) -> None:
    """If INGEST_API_KEY is set, collector deliveries must send it in the X-API-Key header.

    One shared key for all agents. Later this becomes per-owner keys resolved by get_current_owner().
    """
    expected = settings.ingest_api_key
    if expected and not (x_api_key and secrets.compare_digest(x_api_key, expected)):
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key header.")


def get_current_owner() -> uuid.UUID | None:
    return None


def scope_machines(stmt: Select, owner_id: uuid.UUID | None) -> Select:
    """Restrict a query that involves the machines table to the caller's machines."""
    if owner_id is None:
        return stmt
    return stmt.where(Machine.owner_id == owner_id)
