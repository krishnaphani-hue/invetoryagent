"""Shared defaults for the tools that POST to the server."""
import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def default_api_key() -> str | None:
    """INGEST_API_KEY from the environment, else from the repo-root .env, else None."""
    if os.environ.get("INGEST_API_KEY"):
        return os.environ["INGEST_API_KEY"]
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == "INGEST_API_KEY" and value.strip():
                return value.strip()
    return None


def headers(api_key: str | None) -> dict[str, str]:
    return {"X-API-Key": api_key} if api_key else {}
