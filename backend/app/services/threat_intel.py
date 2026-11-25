"""Match the installed software against Advanced-Threat-Intelligence (ATI), a separate CVE intelligence app.

ATI collects CVEs (NVD, CISA KEV, EPSS, public exploits) into its own database and serves them over HTTP. It does
not know what is installed on our machines, so this module does the correlation:

1. Take each distinct installed application (name, version, publisher) from the machines' current software.
2. Derive the product word from its name and ask ATI for CVEs whose product matches (`GET /api/cves?search=`).
   A candidate is kept only if ATI's product contains that word and ATI's vendor agrees with the publisher/name.
   ATI is the source of the risk data: severity, CVSS, EPSS, CISA KEV, public-exploit flags, AI summary.
3. Fetch each candidate CVE's exact affected products and version ranges from NVD. ATI keeps only the first
   version bound of a CVE, which gives wrong answers for products with several release branches (PostgreSQL 16.2
   looked "fixed" because ATI reported `< 12.21`), so the ranges come from NVD directly. NVD is rate limited, so at
   most `NVD_MAX_LOOKUPS` CVEs are fetched per scan, riskiest first (CISA KEV, public exploit, CVSS), and results
   are cached for `NVD_RANGE_TTL_DAYS`. Scans converge over time.
4. Compare the installed version with every range NVD lists for that product and store one `threat_matches` row
   per application and CVE.

Status of a finding:
  vulnerable  the installed version is inside an affected range and the product name matches well
  review      product matches but the version cannot be decided yet (no ranges fetched, unreadable version,
              NVD has no product data for the CVE, partial name match)
  ruled_out   the installed version is outside every affected range (kept so analysts can see why it was dropped)

Known limits (also in docs/DESIGN.md): products are matched by name, not by CPE identifier, so look-alike product
names can match; CVEs that ATI stored with vendor/product "Unknown" (NVD had not analysed them yet) cannot be matched.
"""
import asyncio
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import delete, func, literal_column, select, tuple_
from starlette.concurrency import run_in_threadpool

from app import db
from app.config import settings
from app.models import CveRange, InstalledSoftware, ThreatMatch
from app.services.queries import current_snapshot_ids

log = logging.getLogger("uvicorn.error.threat_intel")

# Shown in /api/health and /api/v1/vulnerabilities/status.
status: dict = {"running": False, "last_run": None, "last_error": None, "last_result": None}
_run_lock = threading.Lock()

# ---------------------------------------------------------------- names and versions

# Words that say nothing about which product it is (company suffixes, packaging words, bitness, ...).
NOISE = {
    "the", "and", "for", "with", "inc", "corp", "corporation", "ltd", "limited", "llc", "co", "company", "gmbh",
    "software", "edition", "editions", "client", "runtime", "redistributable", "update", "updates", "hotfix",
    "security", "package", "packages", "tools", "tool", "driver", "drivers", "service", "services", "pack",
    "external", "desktop", "platform", "agent", "library", "libraries", "sdk", "kit", "development", "bit",
    "x64", "x86", "amd64", "arm64", "windows", "win", "installer", "setup", "language", "languages", "english",
    "extension", "extensions", "component", "components", "helper", "utility", "utilities", "application",
    "app", "apps", "free", "pro", "professional", "enterprise", "standard", "home", "community", "version",
    "build", "release", "beta", "preview", "kb", "user", "users", "system", "global", "group",
}
_WORD = re.compile(r"[a-z0-9]+")


def tokens(text: str | None) -> list[str]:
    return _WORD.findall((text or "").lower().replace("++", "pp").replace("#", "sharp"))


def _useful(tok: str) -> bool:
    """Not noise, not a bare number / version-like word, long enough to identify something."""
    if tok in NOISE or tok.isdigit() or len(tok) < 2:
        return False
    return not re.fullmatch(r"v\d+|x?\d+(bit)?|kb\d+", tok)  # versions, bitness, Windows update ids


def name_tokens(name: str) -> list[str]:
    return [t for t in tokens(name) if _useful(t)]


def lead_token(name: str, publisher: str | None) -> str | None:
    """The word that identifies the product: the first word of the name that is not just the publisher's name."""
    words = name_tokens(name)
    if not words:
        return None
    pub = {t for t in tokens(publisher) if t not in NOISE}
    for w in words:
        if w not in pub:
            return w
    return words[0]  # the name is only the publisher's name (e.g. 'VMware' by 'VMware, Inc.')


def vendor_agrees(vendor: set[str], lead: str, publisher: str | None, words: set[str]) -> bool:
    """The CVE's vendor is the application's publisher (or named in its name), or is the product itself."""
    pub = {t for t in tokens(publisher) if t not in NOISE}
    return bool(vendor & (pub | words)) or lead in vendor


def parse_version(v: str | None) -> tuple[int, ...] | None:
    """Leading dotted number of a version string ('26.0.1 build-123' -> (26, 0, 1)); None if there is none."""
    m = re.match(r"\s*v?(\d+(?:[._-]\d+)*)", v or "")
    return tuple(int(p) for p in re.split(r"[._-]", m.group(1))) if m else None


def compare_versions(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    n = max(len(a), len(b))
    a, b = a + (0,) * (n - len(a)), b + (0,) * (n - len(b))
    return (a > b) - (a < b)


# ---------------------------------------------------------------- NVD version ranges

BOUNDS = (("start_incl", ">="), ("start_excl", ">"), ("end_incl", "<="), ("end_excl", "<"))


def parse_nvd_ranges(data: dict) -> list[dict]:
    """Affected CPE matches of a CVE (NVD API 2.0 response): vendor, product, version and the four bounds."""
    out = []
    for item in data.get("vulnerabilities", [])[:1]:
        for conf in item.get("cve", {}).get("configurations", []):
            for node in conf.get("nodes", []):
                for m in node.get("cpeMatch", []):
                    parts = (m.get("criteria") or "").split(":")
                    if not m.get("vulnerable") or len(parts) < 6:
                        continue
                    out.append({
                        "vendor": parts[3], "product": parts[4], "version": parts[5],
                        "start_incl": m.get("versionStartIncluding"), "start_excl": m.get("versionStartExcluding"),
                        "end_incl": m.get("versionEndIncluding"), "end_excl": m.get("versionEndExcluding"),
                    })
    return out


def describe_range(r: dict) -> str:
    bounds = [f"{op} {r[k]}" for k, op in BOUNDS if r.get(k)]
    if bounds:
        return ", ".join(bounds)
    return "all versions" if r.get("version") in (None, "*", "") else f"= {r['version']}"


def in_range(installed: tuple[int, ...], r: dict) -> bool | None:
    """True/False, or None if the range cannot be compared (unreadable bound, 'not applicable' version)."""
    for key, op in BOUNDS:
        if not r.get(key):
            continue
        bound = parse_version(r[key])
        if bound is None:
            return None
        c = compare_versions(installed, bound)
        if not {">=": c >= 0, ">": c > 0, "<=": c <= 0, "<": c < 0}[op]:
            return False
    if any(r.get(k) for k, _ in BOUNDS) or r.get("version") in (None, "*", ""):
        return True
    exact = parse_version(r["version"])  # a single listed version
    return None if exact is None else compare_versions(installed, exact) == 0


def judge(installed: str | None, ranges: list[dict], lead: str, publisher: str | None, words: set[str]) -> dict:
    """Compare an installed version with the NVD ranges that belong to this product.

    Returns {"verdict": 'in' | 'out' | 'unknown', "range": text, "fixed": version | None, "why": text}.
    """
    have = parse_version(installed)
    mine = [r for r in ranges
            if lead in set(tokens(r["product"])) and vendor_agrees(set(tokens(r["vendor"])), lead, publisher, words)]
    if not ranges:
        return {"verdict": "unknown", "range": None, "fixed": None, "why": "NVD has no product data for this CVE yet"}
    if not mine:
        return {"verdict": "unknown", "range": None, "fixed": None,
                "why": "NVD's product list for this CVE does not include this application"}
    texts = list(dict.fromkeys(describe_range(r) for r in mine))
    shown = "; ".join(texts[:8]) + (f"; (+{len(texts) - 8} more)" if len(texts) > 8 else "")
    if have is None:
        return {"verdict": "unknown", "range": shown, "fixed": None, "why": "installed version unknown"}
    results = [(in_range(have, r), r) for r in mine]
    hit = next((r for ok, r in results if ok), None)
    if hit is not None:
        return {"verdict": "in", "range": describe_range(hit), "fixed": hit.get("end_excl"), "why": ""}
    if any(ok is None for ok, _ in results):
        return {"verdict": "unknown", "range": shown, "fixed": None, "why": "a version bound in NVD could not be read"}
    return {"verdict": "out", "range": shown, "fixed": None, "why": ""}


# ---------------------------------------------------------------- clients

class AtiClient:
    """Thin client for the part of ATI's HTTP API used here."""

    def __init__(self, base_url: str, timeout: float = 60, transport: httpx.BaseTransport | None = None):
        self._http = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport)

    def close(self) -> None:
        self._http.close()

    def search_cves(self, term: str, max_pages: int = 3) -> list[dict]:
        """CVEs whose vendor / product / summary contains `term`, highest CVSS first."""
        items: list[dict] = []
        for page in range(1, max_pages + 1):
            r = self._http.get("/api/cves", params={
                "search": term, "limit": 100, "page": page, "sort_by": "cvss_v3_score", "sort_order": "desc",
            })
            r.raise_for_status()
            data = r.json()
            items += data.get("items", [])
            if page >= data.get("total_pages", 1):
                break
        return items


class NvdRateLimited(Exception):
    pass


class NvdClient:
    """Fetches one CVE's affected ranges from NVD, spacing requests to stay inside its rate limit."""

    def __init__(self, url: str | None = None, api_key: str | None = None, min_interval: float | None = None,
                 timeout: float = 30, transport: httpx.BaseTransport | None = None):
        key = settings.nvd_api_key if api_key is None else api_key
        self._url = url or settings.nvd_url
        self._headers = {"apiKey": key} if key else {}
        # NVD allows 5 requests / 30 s without a key, 50 with one.
        self._gap = (0.7 if key else 6.5) if min_interval is None else min_interval
        self._last = 0.0
        self._http = httpx.Client(timeout=timeout, transport=transport)

    def close(self) -> None:
        self._http.close()

    def ranges(self, cve_id: str) -> list[dict]:
        wait = self._last + self._gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            r = self._http.get(self._url, params={"cveId": cve_id}, headers=self._headers)
        finally:
            self._last = time.monotonic()
        if r.status_code in (403, 429):
            raise NvdRateLimited(f"NVD refused the request ({r.status_code}); try again later or set NVD_API_KEY")
        r.raise_for_status()
        return parse_nvd_ranges(r.json())


# ---------------------------------------------------------------- matching

def _risk_key(c: dict) -> tuple:
    exploit = bool(c.get("has_public_poc") or c.get("has_metasploit") or c.get("has_nuclei"))
    return (bool(c.get("is_cisa_kev")), exploit, c.get("cvss_v3_score") or 0.0, c.get("epss_score") or 0.0)


def _candidates(client: AtiClient, name: str, publisher: str | None, cache: dict[str, list[dict] | None]):
    """(lead word, [(CVE row, strong?)]) for one application; None if the name gives nothing to search for.

    The list is None when ATI's search for the lead word failed: the caller then keeps the application's
    earlier findings instead of replacing them with nothing.
    """
    lead = lead_token(name, publisher)
    if lead is None:
        return None
    if lead not in cache:
        try:
            cache[lead] = client.search_cves(lead)
        except httpx.HTTPStatusError as e:  # ATI answered with an error for this word: skip it, keep going
            log.warning("threat intel: ATI search for %r failed: %s", lead, e)
            cache[lead] = None
    if cache[lead] is None:
        return lead, None
    words = set(name_tokens(name))
    out = []
    for c in cache[lead]:
        product, vendor = set(tokens(c.get("affected_product"))), set(tokens(c.get("affected_vendor")))
        if lead not in product or not vendor_agrees(vendor, lead, publisher, words):
            continue  # not this product, or the same product word from an unrelated vendor
        out.append((c, words <= (product | vendor)))
    return lead, out


def _fresh(r: CveRange | None) -> bool:
    if r is None:
        return False
    ttl = timedelta(days=settings.nvd_range_ttl_days if r.ranges else 1)  # retry sooner while NVD has no data
    return r.fetched_at >= datetime.now(timezone.utc) - ttl


def _decide(version: str | None, rng: CveRange | None, lead: str, publisher: str | None, words: set[str],
            strong: bool) -> tuple[str, str, str | None, str | None]:
    """(status, reason, range text, fixed version)."""
    if rng is None:
        return "review", ("Affected versions not fetched from NVD yet (lookups are limited per scan); "
                          "they will be checked on a later scan."), None, None
    j = judge(version, rng.ranges, lead, publisher, words)
    if j["verdict"] == "unknown":
        return "review", f"Product matches but the version cannot be checked: {j['why']}.", j["range"], None
    if j["verdict"] == "out":
        return "ruled_out", f"Installed {version} is outside every affected range NVD lists ({j['range']}).", j["range"], None
    if not strong:
        return "review", (f"Installed {version} is in the affected range {j['range']}, but only part of the "
                          "product name matched."), j["range"], j["fixed"]
    fixed = f" Fixed in {j['fixed']}." if j["fixed"] else ""
    return "vulnerable", f"Installed {version} is inside the affected range {j['range']} (NVD).{fixed}", j["range"], j["fixed"]


def run_scan(client: AtiClient | None = None, max_lookups: int | None = None, nvd: NvdClient | None = None) -> dict:
    """One full matching run. Returns counts. Raises if ATI is unreachable (previous results are kept)."""
    owned: list = []
    if client is None:
        if not settings.ati_url:
            raise RuntimeError("ATI_URL is not set")
        client = AtiClient(settings.ati_url, settings.ati_timeout_seconds)
        owned.append(client)
    if nvd is None:
        nvd = NvdClient()
        owned.append(nvd)
    budget = settings.nvd_max_lookups if max_lookups is None else max_lookups
    try:
        # 1. distinct applications installed anywhere right now
        version_col = func.coalesce(InstalledSoftware.version, literal_column("''"))  # same text in SELECT and GROUP BY
        with db.SessionLocal() as session:
            cur = current_snapshot_ids("software_count").subquery()
            apps = session.execute(
                select(InstalledSoftware.name, version_col, func.max(InstalledSoftware.publisher))
                .join(cur, cur.c.snapshot_id == InstalledSoftware.snapshot_id)
                .group_by(InstalledSoftware.name, version_col)
            ).all()
            ranges = {r.cve_id: r for r in session.execute(select(CveRange)).scalars()}

        # 2. candidate CVEs per application (network: ATI search)
        search_cache: dict[str, list[dict] | None] = {}
        found: list[tuple[str, str, str | None, str, bool, dict]] = []  # name, version, publisher, lead, strong, cve
        keep: list[tuple[str, str]] = []  # applications whose search failed: their earlier findings stay as they are
        for name, version, publisher in apps:
            res = _candidates(client, name, publisher, search_cache)
            if res is None:
                continue
            lead, cands = res
            if cands is None:
                keep.append((name, version))
            else:
                found += [(name, version, publisher, lead, strong, c) for c, strong in cands]

        # 3. affected version ranges from NVD, riskiest CVEs first, within the budget (network: NVD)
        pending: dict[str, dict] = {}
        for *_, c in found:
            if not _fresh(ranges.get(c["cve_id"])):
                pending.setdefault(c["cve_id"], c)
        looked_up = lookup_errors = 0
        rate_limited = False
        new_ranges: list[CveRange] = []
        for cve_id in sorted(pending, key=lambda i: _risk_key(pending[i]), reverse=True):
            if looked_up >= budget:
                break
            try:
                fetched = nvd.ranges(cve_id)
            except NvdRateLimited as e:
                rate_limited = True
                log.warning("threat intel: %s", e)
                break
            except httpx.HTTPError as e:
                lookup_errors += 1
                log.warning("threat intel: NVD lookup for %s failed: %s", cve_id, e)
                continue
            looked_up += 1
            rng = CveRange(cve_id=cve_id, ranges=fetched, fetched_at=datetime.now(timezone.utc))
            new_ranges.append(rng)
            ranges[cve_id] = rng

        # 4. decide and store (one transaction; nothing is replaced if an earlier step raised)
        counts = {"vulnerable": 0, "review": 0, "ruled_out": 0}
        with db.SessionLocal() as session:
            for rng in new_ranges:
                session.merge(rng)
            # Every installed application was just re-evaluated, so replace all findings (this also drops findings
            # for applications no longer installed anywhere) except those of applications whose search failed.
            stmt = delete(ThreatMatch)
            if keep:
                stmt = stmt.where(~tuple_(ThreatMatch.software_name, ThreatMatch.software_version).in_(keep))
            session.execute(stmt)
            seen: set[tuple[str, str, str]] = set()
            for name, version, publisher, lead, strong, c in found:
                key = (name, version, c["cve_id"])
                if key in seen:
                    continue
                seen.add(key)
                st, reason, rng_text, fixed = _decide(version, ranges.get(c["cve_id"]), lead, publisher,
                                                      set(name_tokens(name)), strong)
                counts[st] += 1
                session.add(ThreatMatch(
                    software_name=name, software_version=version, cve_id=c["cve_id"], status=st, reason=reason,
                    match_token=lead, vendor=c.get("affected_vendor"), product=c.get("affected_product"),
                    vulnerable_range=rng_text, fixed_version=fixed,
                    severity=c.get("severity"), cvss_v3=c.get("cvss_v3_score"), epss=c.get("epss_score"),
                    is_cisa_kev=bool(c.get("is_cisa_kev")), has_public_poc=bool(c.get("has_public_poc")),
                    has_metasploit=bool(c.get("has_metasploit")), has_nuclei=bool(c.get("has_nuclei")),
                    ai_summary=(c.get("ai_summary") or "")[:600] or None,
                ))
            session.commit()
        return {"applications": len(apps), "candidate_cves": len({k[2] for k in seen}), "lookups": looked_up,
                "lookup_errors": lookup_errors, "lookups_pending": max(0, len(pending) - looked_up - lookup_errors),
                "nvd_rate_limited": rate_limited, **counts}
    finally:
        for c in owned:
            c.close()


def scan_now(client: AtiClient | None = None, max_lookups: int | None = None, nvd: NvdClient | None = None) -> dict | None:
    """run_scan with status bookkeeping. Returns None if a scan is already running."""
    if not _run_lock.acquire(blocking=False):
        return None
    try:
        status.update(running=True, last_run=datetime.now(timezone.utc).isoformat())
        try:
            result = run_scan(client, max_lookups, nvd)
            status.update(last_result=result, last_error=None)
            log.info("threat intel: %s", result)
            return result
        except Exception as e:  # ATI down, wrong URL, ...: keep the previous findings, report the error
            status["last_error"] = str(e) or e.__class__.__name__
            log.exception("threat intel scan failed")
            return {"error": status["last_error"]}
    finally:
        status["running"] = False
        _run_lock.release()


def start_scan_in_background() -> bool:
    """Start a scan in its own thread. False if one is already running."""
    if _run_lock.locked():
        return False
    threading.Thread(target=scan_now, name="threat-intel-scan", daemon=True).start()
    return True


async def ati_loop() -> None:
    interval = settings.ati_poll_minutes * 60
    log.info("threat intel: matching installed software against ATI at %s every %s min",
             settings.ati_url, settings.ati_poll_minutes)
    await asyncio.sleep(30)  # let the first agent import land before the first scan
    while True:
        await run_in_threadpool(scan_now)
        await asyncio.sleep(interval)
