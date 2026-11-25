import pytest

from app.config import settings

BODY = {"machine": {"hostname": "KEY-TEST-PC"}, "installed_software": [{"name": "7-Zip"}]}


@pytest.fixture
def ingest_key(monkeypatch):
    monkeypatch.setattr(settings, "ingest_api_key", "s3cret")
    return "s3cret"


def test_no_key_configured_accepts_anonymous(client):
    assert client.post("/api/v1/inventory", json=BODY).status_code == 201


def test_key_configured_rejects_missing_or_wrong_key(client, ingest_key):
    assert client.post("/api/v1/inventory", json=BODY).status_code == 401
    assert client.post("/api/v1/inventory", json=BODY, headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/api/v1/machines").json()["total"] == 0


def test_key_configured_accepts_correct_key(client, ingest_key):
    r = client.post("/api/v1/inventory", json=BODY, headers={"X-API-Key": ingest_key})
    assert r.status_code == 201


def test_key_does_not_block_dashboard_reads(client, ingest_key):
    assert client.get("/api/v1/stats").status_code == 200
