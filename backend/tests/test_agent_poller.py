"""Polling the agent's own database (services/agent_poller.py).

The fake agent database is a separate schema ("agent_fake") inside the test database, reached through a libpq
URL with search_path set, because its table names clash with ours."""
import uuid
from datetime import datetime
from urllib.parse import quote

import psycopg
import pytest
from sqlalchemy import make_url

from app import db
from app.config import settings
from app.services.agent_poller import _libpq_url, poll_agent_db

AGENT_SCHEMA = """
DROP SCHEMA IF EXISTS agent_fake CASCADE;
CREATE SCHEMA agent_fake;
SET search_path = agent_fake;
CREATE TABLE machines (id uuid PRIMARY KEY, hostname text, os text, last_seen timestamptz);
CREATE TABLE services (machine_id uuid, name text, display_name text, status text, start_type text, collected_at timestamptz);
CREATE TABLE processes (machine_id uuid, name text, pid int, path text, version text, collected_at timestamptz);
CREATE TABLE listening_ports (machine_id uuid, protocol text, local_address text, port int, pid int,
                              process_name text, path text, version text, collected_at timestamptz);
CREATE TABLE installed_software (machine_id uuid, name text, version text, publisher text, collected_at timestamptz);
"""
MID = uuid.UUID("11111111-2222-3333-4444-555555555555")


@pytest.fixture
def agent_db():
    base = _libpq_url(db.engine.url.render_as_string(hide_password=False))
    with psycopg.connect(base, autocommit=True) as conn:
        conn.execute(AGENT_SCHEMA)
        conn.execute("INSERT INTO agent_fake.machines VALUES (%s, 'AGENT-PC', 'Windows 11', now())", (MID,))
    url = base + ("&" if "?" in base else "?") + "options=" + quote("-csearch_path=agent_fake")

    def add_cycle(ts: str, software: bool = True):
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("INSERT INTO services VALUES (%s, 'Spooler', 'Print Spooler', 'Running', 'Auto', %s)", (MID, ts))
            conn.execute("INSERT INTO processes VALUES (%s, 'svchost.exe', 100, NULL, NULL, %s)", (MID, ts))
            conn.execute("INSERT INTO listening_ports VALUES (%s, 'TCP', '0.0.0.0', 445, 4, 'System', NULL, NULL, %s)", (MID, ts))
            if software:
                conn.execute("INSERT INTO installed_software VALUES (%s, 'App', %s, 'Acme', %s)", (MID, ts[11:16], ts))

    yield url, add_cycle
    with psycopg.connect(base, autocommit=True) as conn:
        conn.execute("DROP SCHEMA agent_fake CASCADE")


def test_imports_new_cycles_only(client, agent_db):
    url, add_cycle = agent_db
    add_cycle("2026-11-24T10:00:00+00:00")
    add_cycle("2026-11-24T10:05:00+00:00")
    assert poll_agent_db(url) == 2
    assert poll_agent_db(url) == 0  # nothing new: no duplicates

    add_cycle("2026-11-24T10:10:00+00:00")
    assert poll_agent_db(url) == 1

    snaps = client.get(f"/api/v1/machines/{MID}/snapshots").json()["items"]
    assert [datetime.fromisoformat(s["collected_at"]) for s in snaps] == [
        datetime.fromisoformat(f"2026-11-24T10:{mm}:00+00:00") for mm in ("10", "05", "00")
    ]
    assert all(s["source"] == "agent" for s in snaps)
    m = client.get(f"/api/v1/machines/{MID}").json()
    assert m["hostname"] == "AGENT-PC" and m["online"] is True
    sw = client.get(f"/api/v1/machines/{MID}/software").json()["items"]
    assert [r["version"] for r in sw] == ["10:10"]


def test_cycle_without_software_keeps_previous(client, agent_db):
    url, add_cycle = agent_db
    add_cycle("2026-11-24T10:00:00+00:00")
    add_cycle("2026-11-24T10:05:00+00:00", software=False)  # CollectInstalledSoftware=false
    assert poll_agent_db(url) == 2
    latest = client.get(f"/api/v1/machines/{MID}/snapshots").json()["items"][0]
    assert latest["software_count"] is None and latest["port_count"] == 1
    sw = client.get(f"/api/v1/machines/{MID}/software").json()["items"]
    assert [r["version"] for r in sw] == ["10:00"]


def test_no_url_does_nothing(agent_db, monkeypatch):
    monkeypatch.setattr(settings, "agent_db_url", "")  # independent of AGENT_DB_URL in .env
    agent_db[1]("2026-11-24T10:00:00+00:00")
    assert poll_agent_db() == 0
