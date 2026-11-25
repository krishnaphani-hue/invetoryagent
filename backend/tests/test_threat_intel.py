"""Matching installed software against Advanced-Threat-Intelligence (services/threat_intel.py, routers/threat.py).

ATI (CVE search) and NVD (affected version ranges) are replaced by httpx MockTransports: no network needed."""
import httpx
import pytest
from sqlalchemy import func, select

from app import db
from app.config import settings
from app.models import CveRange, ThreatMatch
from app.services import threat_intel as ti
from app.services.threat_intel import (
    AtiClient, NvdClient, compare_versions, in_range, judge, lead_token, parse_nvd_ranges, parse_version, run_scan,
    scan_now,
)

M1 = "aaaaaaaa-0000-0000-0000-000000000001"
M2 = "aaaaaaaa-0000-0000-0000-000000000002"

# What the fake ATI knows. Keys are the search words ATI is asked for.
CVES = {
    "acrobat": [
        {"cve_id": "CVE-2026-0001", "affected_vendor": "Adobe", "affected_product": "Acrobat_reader", "severity": "Critical",
         "cvss_v3_score": 9.8, "epss_score": 0.4, "is_cisa_kev": 1, "has_public_poc": 1, "ai_summary": "Use-after-free."},
        {"cve_id": "CVE-2026-0002", "affected_vendor": "Adobe", "affected_product": "Acrobat", "severity": "High",
         "cvss_v3_score": 7.0, "epss_score": 0.01, "is_cisa_kev": 0, "has_public_poc": 0},
        # same product word, unrelated vendor: must be ignored
        {"cve_id": "CVE-2026-0003", "affected_vendor": "Notadobe", "affected_product": "Acrobat", "severity": "High",
         "cvss_v3_score": 8.0},
    ],
    "chrome": [
        {"cve_id": "CVE-2026-0004", "affected_vendor": "Google", "affected_product": "Chrome", "severity": "Medium",
         "cvss_v3_score": 6.5, "epss_score": 0.02},
        {"cve_id": "CVE-2026-0005", "affected_vendor": "Google", "affected_product": "Chrome", "severity": "High",
         "cvss_v3_score": 8.8, "epss_score": 0.1},
    ],
}


def cpe(vendor, product, version="*", **bounds):
    """One vulnerable NVD cpeMatch."""
    m = {"vulnerable": True, "criteria": f"cpe:2.3:a:{vendor}:{product}:{version}:*:*:*:*:*:*:*"}
    m.update({"versionStartIncluding": bounds.get("si"), "versionStartExcluding": bounds.get("se"),
              "versionEndIncluding": bounds.get("ei"), "versionEndExcluding": bounds.get("ee")})
    return {k: v for k, v in m.items() if v is not None}


# What the fake NVD lists as affected, per CVE (cpeMatch entries). A CVE missing here has no product data yet.
NVD = {
    # affected from 24.0 up to (not including) 25.1.0: older versions are NOT affected
    "CVE-2026-0001": [cpe("adobe", "acrobat_reader", si="24.0", ee="25.1.0")],
    "CVE-2026-0002": [cpe("adobe", "acrobat", ee="20.0")],
    # two release branches, like PostgreSQL: 100.x before 110.0 and 120.x before 125.0
    "CVE-2026-0005": [cpe("google", "chrome", si="100", ee="110.0"), cpe("google", "chrome", si="120", ee="125.0")],
}


def nvd_json(cve_id: str) -> dict:
    matches = NVD.get(cve_id, [])
    conf = [{"nodes": [{"cpeMatch": matches}]}] if matches else []
    return {"vulnerabilities": [{"cve": {"id": cve_id, "configurations": conf}}]}


class FakeServers:
    """Fake ATI and NVD in one request handler."""

    def __init__(self):
        self.ati_calls: list[str] = []
        self.nvd_calls: list[str] = []
        self.fail_search: set[str] = set()
        self.ati_down = False
        self.nvd_status: dict[str, int] = {}  # cve -> HTTP status to answer with

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "nvd.test":
            cve = request.url.params["cveId"]
            self.nvd_calls.append(cve)
            if cve in self.nvd_status:
                return httpx.Response(self.nvd_status[cve])
            return httpx.Response(200, json=nvd_json(cve))
        if self.ati_down:
            raise httpx.ConnectError("ATI is down", request=request)
        assert request.url.path == "/api/cves"
        term = request.url.params["search"]
        self.ati_calls.append(term)
        if term in self.fail_search:
            return httpx.Response(500, json={"detail": "boom"})
        return httpx.Response(200, json={"items": CVES.get(term, []), "total_pages": 1})

    def ati(self) -> AtiClient:
        return AtiClient("http://ati.test", transport=httpx.MockTransport(self))

    def nvd(self) -> NvdClient:
        return NvdClient(url="https://nvd.test/cves", api_key="", min_interval=0, transport=httpx.MockTransport(self))

    def scan(self, **kw) -> dict:
        return run_scan(self.ati(), nvd=self.nvd(), **kw)


@pytest.fixture
def fake():
    return FakeServers()


def send(client, machine: str, host: str, software: list[dict], ports: list[dict] | None = None, at="2026-11-25T10:00:00Z"):
    body = {"collected_at": at, "machine": {"id": machine, "hostname": host, "os": "Windows 11"}, "installed_software": software}
    if ports is not None:
        body["listening_ports"] = ports
    assert client.post("/api/v1/inventory", json=body).status_code == 201


def findings(client, **params):
    r = client.get("/api/v1/vulnerabilities", params=params)
    assert r.status_code == 200, r.text
    return r.json()["items"]


ACROBAT = {"name": "Adobe Acrobat (64-bit)", "version": "24.2.1", "publisher": "Adobe"}
CHROME = {"name": "Google Chrome", "version": "131.0.1", "publisher": "Google LLC"}
ACRO_PORT = {"protocol": "TCP", "local_address": "0.0.0.0", "port": 8080, "pid": 7,
             "process_name": "AdobeCollabSync.exe", "path": "C:\\Program Files\\Adobe\\Acrobat DC\\Acrobat\\AdobeCollabSync.exe"}
OTHER_PORT = {"protocol": "TCP", "local_address": "0.0.0.0", "port": 445, "pid": 4, "process_name": "System"}


# ---------------------------------------------------------------- names and versions

def test_lead_token_skips_publisher_and_noise():
    assert lead_token("Adobe Acrobat (64-bit)", "Adobe") == "acrobat"
    assert lead_token("Google Chrome", "Google LLC") == "chrome"
    assert lead_token("VMware", "VMware, Inc.") == "vmware"  # name is only the publisher
    assert lead_token("CrowdStrike Windows Sensor", "Keysight") == "crowdstrike"
    assert lead_token("PostgreSQL 16", "PostgreSQL Global Development Group") == "postgresql"
    assert lead_token("Microsoft Visual C++ 2015-2022 Redistributable (x64)", "Microsoft") == "visual"
    assert lead_token("Update for Windows 10 (KB5001234)", None) is None  # nothing identifying left


def test_parse_and_compare_versions():
    assert parse_version("26.0.1 build-25688693") == (26, 0, 1)
    assert parse_version("16.16-2") == (16, 16, 2)
    assert parse_version("v1.2") == (1, 2)
    assert parse_version("beta") is None and parse_version(None) is None
    assert compare_versions((1, 2), (1, 2, 0)) == 0
    assert compare_versions((1, 10), (1, 9)) == 1
    assert compare_versions((24, 2, 1), (25, 1, 0)) == -1


def test_parse_nvd_ranges_keeps_only_vulnerable_entries():
    data = {"vulnerabilities": [{"cve": {"configurations": [{"nodes": [{"cpeMatch": [
        cpe("postgresql", "postgresql", si="16.0", ee="16.5"),
        {"vulnerable": False, "criteria": "cpe:2.3:o:microsoft:windows_11:-:*:*:*:*:*:*:*"},  # a platform, not affected
        cpe("acme", "tool", "1.2.3"),
    ]}]}]}}]}
    assert parse_nvd_ranges(data) == [
        {"vendor": "postgresql", "product": "postgresql", "version": "*", "start_incl": "16.0", "start_excl": None,
         "end_incl": None, "end_excl": "16.5"},
        {"vendor": "acme", "product": "tool", "version": "1.2.3", "start_incl": None, "start_excl": None,
         "end_incl": None, "end_excl": None},
    ]
    assert parse_nvd_ranges({"vulnerabilities": []}) == []


@pytest.mark.parametrize("installed,bounds,expected", [
    ("24.2.1", {"si": "24.0", "ee": "25.1.0"}, True),
    ("23.8", {"si": "24.0", "ee": "25.1.0"}, False),    # below the lower bound
    ("25.1.0", {"si": "24.0", "ee": "25.1.0"}, False),  # end is exclusive
    ("25.1.0", {"si": "24.0", "ei": "25.1.0"}, True),   # end is inclusive
    ("24.0", {"se": "24.0", "ee": "25"}, False),        # start is exclusive
    ("9.9", {}, True),                                  # '*' with no bounds = every version
])
def test_in_range_bounds(installed, bounds, expected):
    r = parse_nvd_ranges({"vulnerabilities": [{"cve": {"configurations": [{"nodes": [{"cpeMatch": [cpe("v", "p", **bounds)]}]}]}}]})[0]
    assert in_range(parse_version(installed), r) is expected


def test_in_range_single_listed_version_and_unreadable():
    exact = {"vendor": "acme", "product": "tool", "version": "1.2.3", "start_incl": None, "start_excl": None, "end_incl": None, "end_excl": None}
    assert in_range((1, 2, 3), exact) is True and in_range((1, 2, 4), exact) is False
    assert in_range((1, 0), {**exact, "version": "-"}) is None          # 'not applicable': cannot decide
    assert in_range((1, 0), {**exact, "version": "*", "end_excl": "soon"}) is None  # unreadable bound


def test_judge_picks_only_this_products_entries():
    ranges = parse_nvd_ranges({"vulnerabilities": [{"cve": {"configurations": [{"nodes": [{"cpeMatch": [
        cpe("microsoft", "edge", ee="100.0"), cpe("google", "chrome", ee="100.0"),
    ]}]}]}}]})
    words = {"google", "chrome"}
    assert judge("90.0", ranges, "chrome", "Google LLC", words)["verdict"] == "in"
    assert judge("120.0", ranges, "chrome", "Google LLC", words)["verdict"] == "out"
    assert judge("90.0", ranges, "firefox", "Mozilla", {"firefox"})["verdict"] == "unknown"  # not in NVD's list
    assert judge("90.0", [], "chrome", "Google LLC", words)["verdict"] == "unknown"           # NVD has no data yet


# ---------------------------------------------------------------- matching

def test_scan_classifies_findings(client, fake):
    send(client, M1, "PC-ONE", [ACROBAT, CHROME], [ACRO_PORT, OTHER_PORT])
    send(client, M2, "PC-TWO", [{**ACROBAT, "version": "26.0"}])
    result = fake.scan()

    assert result["applications"] == 3 and result["lookups"] == 4 and result["candidate_cves"] == 4
    assert result["vulnerable"] == 1 and result["review"] == 1 and result["ruled_out"] == 4

    actionable = findings(client)
    assert [(f["cve_id"], f["status"], f["hostname"]) for f in actionable] == [
        ("CVE-2026-0001", "vulnerable", "PC-ONE"),
        ("CVE-2026-0004", "review", "PC-ONE"),  # NVD has no product data for this CVE
    ]
    top = actionable[0]
    assert top["software_version"] == "24.2.1" and top["fixed_version"] == "25.1.0"
    assert top["vulnerable_range"] == ">= 24.0, < 25.1.0"
    assert top["is_cisa_kev"] and top["has_public_poc"] and top["severity"] == "Critical"
    assert top["risk"] == 100  # 9.8*5 + 30 (KEV) + 15 (public exploit) + 0.4*15 = 100, capped at 100
    assert actionable[1]["risk"] == 33  # 6.5*5 + 0.02*15 = 32.8
    assert "25.1.0" in top["reason"] and "no product data" in actionable[1]["reason"]
    assert top["matched_vendor"] == "Adobe" and top["matched_product"] == "Acrobat_reader"
    # the listening port whose program lives under Acrobat is tied to the finding; System/445 is not
    assert top["ports"] == [{"protocol": "TCP", "port": 8080, "exposed": True}] and top["exposed"] is True
    assert actionable[1]["ports"] == []
    assert "CVE-2026-0003" not in {f["cve_id"] for f in findings(client, status="all")}  # unrelated vendor

    assert {(f["hostname"], f["software_version"], f["cve_id"]) for f in findings(client, status="ruled_out")} == {
        ("PC-ONE", "24.2.1", "CVE-2026-0002"), ("PC-TWO", "26.0", "CVE-2026-0001"), ("PC-TWO", "26.0", "CVE-2026-0002"),
        ("PC-ONE", "131.0.1", "CVE-2026-0005"),
    }
    assert len(findings(client, status="all")) == 6


def test_versions_below_the_lower_bound_are_not_affected(client, fake):
    send(client, M1, "PC-ONE", [{**ACROBAT, "version": "23.8"}])  # older than the 24.0 where the bug appeared
    fake.scan()
    st = {f["cve_id"]: f["status"] for f in findings(client, status="all")}
    assert st["CVE-2026-0001"] == "ruled_out"


@pytest.mark.parametrize("version,status,fixed", [
    ("108.0.1", "vulnerable", "110.0"),    # first branch
    ("115.0", "ruled_out", None),          # between the branches: not affected
    ("121.0", "vulnerable", "125.0"),      # second branch
    ("131.0.1", "ruled_out", None),        # newer than both
    ("99.0", "ruled_out", None),           # older than both
])
def test_several_release_branches(client, fake, version, status, fixed):
    """The PostgreSQL case: 16.2 must be flagged when NVD lists '16.x before 16.5' after '12.x before 12.21'."""
    send(client, M1, "PC-ONE", [{**CHROME, "version": version}])
    fake.scan()
    f = {x["cve_id"]: x for x in findings(client, status="all")}["CVE-2026-0005"]
    assert f["status"] == status and f["fixed_version"] == fixed


def test_filters_and_summary(client, fake):
    send(client, M1, "PC-ONE", [ACROBAT, CHROME])
    send(client, M2, "PC-TWO", [ACROBAT])
    fake.scan()

    assert len(findings(client)) == 3  # CVE-0001 on both machines + chrome review on one
    assert {f["cve_id"] for f in findings(client, kev_only=True)} == {"CVE-2026-0001"}
    assert {f["cve_id"] for f in findings(client, exploit_only=True)} == {"CVE-2026-0001"}
    assert {f["cve_id"] for f in findings(client, severity="medium")} == {"CVE-2026-0004"}
    assert {f["hostname"] for f in findings(client, machine_id=M2)} == {"PC-TWO"}
    assert {f["hostname"] for f in findings(client, q="pc-one", status="vulnerable")} == {"PC-ONE"}

    s = client.get("/api/v1/vulnerabilities/summary").json()
    assert (s["findings"], s["machines"], s["applications"], s["cves"]) == (3, 2, 2, 2)
    assert (s["vulnerable"], s["review"], s["kev"], s["exploit"]) == (2, 1, 2, 2)
    assert s["by_severity"] == {"Critical": 2, "Medium": 1}
    assert s["top_cves"][0]["cve_id"] == "CVE-2026-0001" and s["top_cves"][0]["machines"] == 2


def test_lookup_budget_riskiest_first_and_cache(client, fake):
    send(client, M1, "PC-ONE", [ACROBAT, CHROME])
    first = fake.scan(max_lookups=1)
    assert fake.nvd_calls == ["CVE-2026-0001"]  # CISA KEV + public exploit goes first
    assert first["lookups"] == 1 and first["lookups_pending"] == 3
    by_cve = {f["cve_id"]: f for f in findings(client, status="all")}
    assert by_cve["CVE-2026-0001"]["status"] == "vulnerable"
    assert by_cve["CVE-2026-0002"]["status"] == "review" and "not fetched from NVD yet" in by_cve["CVE-2026-0002"]["reason"]

    second = fake.scan(max_lookups=10)
    assert second["lookups"] == 3 and second["lookups_pending"] == 0  # CVE-0001 came from the cache
    assert len(fake.nvd_calls) == 4
    assert {f["cve_id"]: f["status"] for f in findings(client, status="all")} == {
        "CVE-2026-0001": "vulnerable", "CVE-2026-0002": "ruled_out", "CVE-2026-0004": "review", "CVE-2026-0005": "ruled_out",
    }

    fake.scan()
    assert len(fake.nvd_calls) == 4  # everything cached now (CVE-0004's empty answer is retried only after a day)


def test_findings_follow_the_installed_version(client, fake):
    send(client, M1, "PC-ONE", [ACROBAT], at="2026-11-25T10:00:00Z")
    fake.scan()
    assert [f["status"] for f in findings(client)] == ["vulnerable"]

    # the machine updates Acrobat past the fix: a newer snapshot replaces the current software
    send(client, M1, "PC-ONE", [{**ACROBAT, "version": "25.2.0"}], at="2026-11-25T11:00:00Z")
    assert findings(client) == []  # old version no longer installed: finding gone before any rescan
    fake.scan()
    assert findings(client) == []
    assert {f["status"] for f in findings(client, status="all")} == {"ruled_out"}
    with db.SessionLocal() as s:  # findings for the old version were deleted, not kept
        assert s.scalar(select(func.count()).select_from(ThreatMatch).where(ThreatMatch.software_version == "24.2.1")) == 0


def test_failed_search_keeps_earlier_findings(client, fake):
    send(client, M1, "PC-ONE", [ACROBAT, CHROME])
    fake.scan()
    fake.fail_search = {"chrome"}
    result = fake.scan()
    assert result["applications"] == 2
    assert {f["cve_id"] for f in findings(client)} == {"CVE-2026-0001", "CVE-2026-0004"}  # chrome finding kept


def test_ati_down_raises_and_keeps_findings(client, fake, monkeypatch):
    monkeypatch.setattr(settings, "ati_url", "http://ati.test")
    send(client, M1, "PC-ONE", [ACROBAT])
    fake.scan()
    fake.ati_down = True
    with pytest.raises(httpx.ConnectError):
        fake.scan()
    out = scan_now(fake.ati(), nvd=fake.nvd())
    assert "error" in out and ti.status["last_error"] and ti.status["running"] is False
    assert len(findings(client)) == 1


def test_nvd_error_leaves_review_and_is_not_cached(client, fake):
    send(client, M1, "PC-ONE", [ACROBAT])
    fake.nvd_status = {"CVE-2026-0001": 502}
    result = fake.scan()
    assert result["lookup_errors"] == 1 and result["nvd_rate_limited"] is False
    st = {f["cve_id"]: f["status"] for f in findings(client, status="all")}
    assert st["CVE-2026-0001"] == "review" and st["CVE-2026-0002"] == "ruled_out"
    with db.SessionLocal() as s:
        assert s.get(CveRange, "CVE-2026-0001") is None  # a failed lookup is not cached


def test_nvd_rate_limit_stops_lookups_and_keeps_going_next_time(client, fake):
    send(client, M1, "PC-ONE", [ACROBAT, CHROME])
    fake.nvd_status = {"CVE-2026-0001": 403}  # riskiest CVE is refused first
    result = fake.scan()
    assert result["nvd_rate_limited"] is True and result["lookups"] == 0 and fake.nvd_calls == ["CVE-2026-0001"]
    assert {f["status"] for f in findings(client, status="all")} == {"review"}

    fake.nvd_status = {}
    result = fake.scan()
    assert result["nvd_rate_limited"] is False and result["lookups"] == 4
    assert {f["cve_id"]: f["status"] for f in findings(client)} == {"CVE-2026-0001": "vulnerable", "CVE-2026-0004": "review"}


def test_unknown_version_and_weak_name_need_review(client, fake):
    send(client, M1, "PC-ONE", [
        {"name": "Adobe Acrobat", "version": None, "publisher": "Adobe"},
        {"name": "Acrobat Pro Studio Plugin", "version": "24.0", "publisher": "Adobe"},  # extra words ATI's product lacks
    ])
    fake.scan()
    rows = {(f["software_name"], f["cve_id"]): f for f in findings(client, status="all")}
    unknown = rows[("Adobe Acrobat", "CVE-2026-0001")]
    assert unknown["status"] == "review" and "version unknown" in unknown["reason"]
    weak = rows[("Acrobat Pro Studio Plugin", "CVE-2026-0001")]
    assert weak["status"] == "review" and "part of the product name" in weak["reason"]


# ---------------------------------------------------------------- API

def test_status_scan_and_health(client, fake, monkeypatch):
    monkeypatch.setattr(settings, "ati_url", "")
    assert client.get("/api/v1/vulnerabilities/status").json()["enabled"] is False
    assert client.post("/api/v1/vulnerabilities/scan").status_code == 503
    assert "threat_intel" not in client.get("/api/health").json()

    monkeypatch.setattr(settings, "ati_url", "http://ati.test")
    started = []
    monkeypatch.setattr(ti, "start_scan_in_background", lambda: started.append(1) or True)
    assert client.post("/api/v1/vulnerabilities/scan").status_code == 202 and started
    monkeypatch.setattr(ti, "start_scan_in_background", lambda: False)
    assert client.post("/api/v1/vulnerabilities/scan").status_code == 409

    send(client, M1, "PC-ONE", [ACROBAT])
    fake.scan()
    st = client.get("/api/v1/vulnerabilities/status").json()
    assert st["enabled"] and st["ati_url"] == "http://ati.test" and st["stored_findings"] == 2 and st["cached_ranges"] == 2
    assert client.get("/api/health").json()["threat_intel"]["ati_url"] == "http://ati.test"


def test_no_ati_url_cannot_scan(monkeypatch):
    monkeypatch.setattr(settings, "ati_url", "")
    with pytest.raises(RuntimeError):
        run_scan()
