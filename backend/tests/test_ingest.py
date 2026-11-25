import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app import db
from app.models import InstalledSoftware, ListeningPort, Snapshot
from app.services.retention import purge_old_snapshots

MID = "43690069-62f5-4a7c-b02a-c0dd35ba49aa"


def payload(**overrides):
    body = {
        "collected_at": "2026-11-24T10:00:00Z",
        "machine": {"id": MID, "hostname": "FIN-LAPTOP-042", "os": "Windows 11"},
        "installed_software": [{"name": "Google Chrome", "version": "131.0.1", "publisher": "Google LLC"}],
        "listening_ports": [
            {"protocol": "TCP", "local_address": "0.0.0.0", "port": 445, "pid": 4, "process_name": "System"},
            {"protocol": "TCP", "local_address": "127.0.0.1", "port": 5433, "pid": 3120, "process_name": "postgres.exe"},
        ],
    }
    body.update(overrides)
    return body


def count(model):
    with db.SessionLocal() as s:
        return s.scalar(select(func.count()).select_from(model))


def test_minimal_payload_hostname_only(client):
    r = client.post("/api/v1/inventory", json={"machine": {"hostname": "box-1"}})
    assert r.status_code == 201, r.text
    snap = r.json()["snapshots"][0]
    uuid.UUID(snap["snapshot_id"])  # server generated
    assert snap["counts"] == {"installed_software": None, "listening_ports": None, "processes": None, "services": None}
    # same hostname -> same machine id
    r2 = client.post("/api/v1/inventory", json={"machine": {"hostname": "BOX-1"}})
    assert r2.json()["snapshots"][0]["machine_id"] == snap["machine_id"]


def test_missing_machine_identity_rejected(client):
    r = client.post("/api/v1/inventory", json={"machine": {"os": "Windows"}})
    assert r.status_code == 422


def test_missing_required_row_field_rejected(client):
    r = client.post("/api/v1/inventory", json=payload(listening_ports=[{"protocol": "TCP"}]))
    assert r.status_code == 422
    assert count(Snapshot) == 0


def test_extra_fields_kept(client):
    body = payload(agent_version="1.2")
    body["machine"]["domain"] = "corp.local"
    body["installed_software"][0]["install_date"] = "2026-01-02"
    assert client.post("/api/v1/inventory", json=body).status_code == 201
    with db.SessionLocal() as s:
        sw = s.scalars(select(InstalledSoftware)).one()
        snap = s.scalars(select(Snapshot)).one()
    assert sw.extra == {"install_date": "2026-01-02"}
    assert snap.extra == {"agent_version": "1.2"}
    m = client.get(f"/api/v1/machines/{MID}").json()
    assert m["extra"] == {"domain": "corp.local"}


def test_two_deliveries_keep_history_and_current_is_latest(client):
    client.post("/api/v1/inventory", json=payload())
    newer = payload(collected_at="2026-11-24T10:05:00Z",
                    installed_software=[{"name": "Google Chrome", "version": "132.0.0", "publisher": "Google LLC"}])
    client.post("/api/v1/inventory", json=newer)
    assert count(Snapshot) == 2
    assert count(InstalledSoftware) == 2  # nothing overwritten

    cur = client.get(f"/api/v1/machines/{MID}/software").json()
    assert [i["version"] for i in cur["items"]] == ["132.0.0"]

    snaps = client.get(f"/api/v1/machines/{MID}/snapshots").json()["items"]
    old_id = snaps[-1]["id"]
    old = client.get(f"/api/v1/machines/{MID}/software", params={"snapshot_id": old_id}).json()
    assert [i["version"] for i in old["items"]] == ["131.0.1"]


def test_replayed_old_delivery_does_not_replace_current(client):
    client.post("/api/v1/inventory", json=payload(collected_at="2026-11-24T10:05:00Z"))
    # agent replays a buffered, older delivery afterwards
    client.post("/api/v1/inventory", json=payload(
        collected_at="2026-11-24T09:00:00Z",
        installed_software=[{"name": "Old App", "version": "1"}]))
    cur = client.get(f"/api/v1/machines/{MID}/software").json()
    assert [i["name"] for i in cur["items"]] == ["Google Chrome"]


def test_partial_delivery_keeps_other_sections_current(client):
    client.post("/api/v1/inventory", json=payload())
    software_only = {"collected_at": "2026-11-24T11:00:00Z", "machine": {"id": MID},
                     "installed_software": [{"name": "Zoom", "version": "6.0"}]}
    client.post("/api/v1/inventory", json=software_only)
    ports = client.get(f"/api/v1/machines/{MID}/ports").json()
    assert {p["port"] for p in ports["items"]} == {445, 5433}
    sw = client.get(f"/api/v1/machines/{MID}/software").json()
    assert [i["name"] for i in sw["items"]] == ["Zoom"]


def test_exposed_flag(client):
    client.post("/api/v1/inventory", json=payload())
    items = {p["port"]: p["exposed"] for p in client.get(f"/api/v1/machines/{MID}/ports").json()["items"]}
    assert items == {445: True, 5433: False}
    stats = client.get("/api/v1/stats").json()
    assert stats["exposed_ports"] == 1
    assert stats["machines"] == 1 and stats["online"] == 1


def test_batch_of_machines(client):
    bodies = [{"machine": {"hostname": f"pc-{i}"}, "services": [{"name": "Spooler", "status": "Running"}]}
              for i in range(3)]
    r = client.post("/api/v1/inventory", json=bodies)
    assert r.status_code == 201
    assert len(r.json()["snapshots"]) == 3
    assert client.get("/api/v1/machines").json()["total"] == 3


def test_retention_purges_old_snapshots(client):
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    client.post("/api/v1/inventory", json=payload(collected_at=old))
    client.post("/api/v1/inventory", json=payload(collected_at=datetime.now(timezone.utc).isoformat()))
    assert purge_old_snapshots(30) == 1
    assert count(Snapshot) == 1
    assert count(ListeningPort) == 2  # only the recent snapshot's rows remain


def test_stats_filters(client):
    other = "aaaaaaaa-0000-0000-0000-000000000001"
    client.post("/api/v1/inventory", json=payload())
    client.post("/api/v1/inventory", json=payload(
        machine={"id": other, "hostname": "SRV-01", "os": "Windows Server 2022"},
        installed_software=[{"name": "IIS"}, {"name": "Google Chrome"}],
        listening_ports=[{"protocol": "TCP", "local_address": "0.0.0.0", "port": 80}],
    ))
    every = client.get("/api/v1/stats").json()
    assert every["machines"] == 2 and every["unique_apps"] == 2 and every["exposed_ports"] == 2
    assert every["period_hours"] == 24 and every["snapshots_recent"] == 2

    one = client.get("/api/v1/stats", params={"machine_id": other}).json()
    assert one["machines"] == 1 and one["exposed_ports"] == 1 and one["snapshots_recent"] == 1
    assert {s["name"] for s in one["top_software"]} == {"IIS", "Google Chrome"}
    assert [s["hostname"] for s in one["recent_snapshots"]] == ["SRV-01"]

    both = client.get("/api/v1/stats", params=[("machine_id", MID), ("machine_id", other)]).json()
    assert both["machines"] == 2

    by_os = client.get("/api/v1/stats", params={"os": "Windows 11"}).json()
    assert by_os["machines"] == 1 and [p["port"] for p in by_os["top_ports"]] == [445, 5433]

    assert client.get("/api/v1/stats", params={"status": "online"}).json()["machines"] == 2
    offline = client.get("/api/v1/stats", params={"status": "offline"}).json()
    assert offline["machines"] == 0 and offline["top_software"] == [] and offline["recent_snapshots"] == []

    assert client.get("/api/v1/stats", params={"hours": 0}).status_code == 422
