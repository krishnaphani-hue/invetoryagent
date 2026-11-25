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

    # Advanced-Threat-Intelligence (ATI) integration (services/threat_intel.py). ATI runs as its own app; this server
    # reads CVE intelligence from its HTTP API and matches it against the installed software. Empty URL = disabled.
    ati_url: str = ""                 # e.g. http://127.0.0.1:8001
    ati_poll_minutes: int = 60        # how often the match run repeats (0 = only when started from the dashboard)
    ati_timeout_seconds: int = 60
    # Exact affected version ranges come straight from NVD (ATI only exposes the first bound of each CVE).
    nvd_url: str = "https://services.nvd.nist.gov/rest/json/cves/2.0"
    nvd_api_key: str = ""             # optional; raises NVD's limit from 5 to 50 requests per 30 s
    nvd_max_lookups: int = 15         # NVD requests per scan (riskiest CVEs first); the rest wait for the next scan
    nvd_range_ttl_days: int = 7       # how long a CVE's looked-up ranges are reused

    frontend_dist: Path = REPO_ROOT / "frontend" / "dist"


settings = Settings()
