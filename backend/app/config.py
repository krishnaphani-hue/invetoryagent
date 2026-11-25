from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """All settings come from environment variables or the repo-root .env file."""

    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://inventory_app:change_me@localhost:5433/asset_inventory"

    # Where `python -m app` listens. 127.0.0.1 = this computer only (local mode);
    # 0.0.0.0 = accept connections from other machines (hosted mode, or behind nginx on the same host).
    host: str = "127.0.0.1"
    app_port: int = 8080
    # Shared key agents must send as X-API-Key to POST /api/v1/inventory. Empty = no key required.
    ingest_api_key: str = ""
    retention_days: int = 30          # 0 = keep history forever
    run_background_tasks: bool = True  # retention cleanup loop; disabled in tests
    online_minutes: int = 15          # a machine counts as online if seen within this window
    max_upload_mb: int = 20
    # The agent's own PostgreSQL database (direct-DB mode). Set = poll it every agent_poll_minutes and import
    # new cycles (services/agent_poller.py). Empty = no polling (agents POST to /api/v1/inventory instead).
    agent_db_url: str = ""
    agent_poll_minutes: int = 30

    frontend_dist: Path = REPO_ROOT / "frontend" / "dist"


settings = Settings()
