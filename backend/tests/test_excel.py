from io import BytesIO

from openpyxl import Workbook


def workbook(sheets: dict[str, list[list]]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def upload(client, content: bytes, name="inv.xlsx"):
    return client.post(
        "/api/v1/uploads",
        files={"file": (name, content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )


GOOD = {
    "machines": [["hostname", "os", "location"], ["PC-A", "Windows 11", "Pune"], ["PC-B", "Windows 10", None]],
    "installed_software": [
        ["hostname", "name", "version", "publisher"],
        ["PC-A", "Google Chrome", "131.0.1", "Google LLC"],
        ["PC-A", ".NET Runtime", 8, "Microsoft"],  # Excel turned the version into a number
        ["PC-B", "Notepad++", "8.9.1", "Notepad++ Team"],
    ],
    "listening_ports": [
        ["hostname", "protocol", "local_address", "port", "pid", "process_name"],
        ["PC-A", "TCP", "0.0.0.0", 445, 4, "System"],
        ["PC-B", "TCP6", "::", 3389.0, 1100, "svchost.exe"],
    ],
}


def test_excel_creates_one_snapshot_per_machine(client):
    r = upload(client, workbook(GOOD))
    assert r.status_code == 201, r.text
    snaps = r.json()["snapshots"]
    assert {s["hostname"] for s in snaps} == {"PC-A", "PC-B"}
    a = next(s for s in snaps if s["hostname"] == "PC-A")
    assert a["counts"] == {"installed_software": 2, "listening_ports": 1, "processes": None, "services": None}

    sw = client.get(f"/api/v1/machines/{a['machine_id']}/software").json()["items"]
    assert {(i["name"], i["version"]) for i in sw} == {("Google Chrome", "131.0.1"), (".NET Runtime", "8")}
    m = client.get(f"/api/v1/machines/{a['machine_id']}").json()
    assert m["os"] == "Windows 11" and m["extra"] == {"location": "Pune"}
    listed = client.get("/api/v1/snapshots", params={"source": "upload_excel"}).json()["items"]
    assert len(listed) == 2 and listed[0]["filename"] == "inv.xlsx"


def test_bad_row_reports_sheet_and_row_and_saves_nothing(client):
    bad = dict(GOOD)
    bad["listening_ports"] = GOOD["listening_ports"] + [["PC-B", "TCP", "0.0.0.0", "not-a-port", None, None]]
    r = upload(client, workbook(bad))
    assert r.status_code == 422
    errors = r.json()["errors"]
    assert errors[0]["sheet"] == "listening_ports" and errors[0]["row"] == 4
    assert client.get("/api/v1/machines").json()["total"] == 0


def test_missing_hostname(client):
    r = upload(client, workbook({"installed_software": [["hostname", "name"], [None, "Chrome"]]}))
    assert r.status_code == 422
    assert r.json()["errors"][0] == {"sheet": "installed_software", "row": 2, "error": "hostname is empty"}


def test_no_known_sheets(client):
    r = upload(client, workbook({"Sheet1": [["a"], [1]]}))
    assert r.status_code == 422


def test_only_xlsx_accepted(client):
    r = upload(client, b"a,b", name="inv.csv")
    assert r.status_code == 400
