"""Tests run against a separate database: DATABASE_URL with "_test" appended to the database name
(asset_inventory_test, created by scripts/setup_db.ps1). Tests empty every table, so never point them at real data."""
import os

os.environ["RUN_BACKGROUND_TASKS"] = "false"

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pathlib import Path  # noqa: E402
from sqlalchemy import make_url, text  # noqa: E402

from app import db  # noqa: E402
from app.config import settings  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]


def _test_url() -> str:
    url = make_url(settings.database_url)
    if not url.database.endswith("_test"):
        url = url.set(database=f"{url.database}_test")
    return url.render_as_string(hide_password=False)


@pytest.fixture(scope="session", autouse=True)
def _test_database():
    url = _test_url()
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    db.configure(url)
    yield


@pytest.fixture(autouse=True)
def _clean():
    with db.engine.begin() as conn:
        conn.execute(text("TRUNCATE machines RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c
