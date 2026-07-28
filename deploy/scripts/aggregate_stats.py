#!/usr/bin/env python3
"""C45 usage-analytics aggregator (record D4/D5 — the C45-impl lane).

A host-side, STDLIB-ONLY daily job (deploy/systemd/ausmt-stats.timer fires it) that folds the Caddy
access log into a cumulative `stats.json` the workbench Analytics screen reads. It is the same
trust class as alert.sh's ops-status writer: it NEVER raises into the timer (main() catches
everything and exits 0), writes atomically (tmp -> chmod 0644 -> os.replace), and stamps the shared
UTC timestamp so the gateway's staleness clock parses it identically.

WHAT IT DOES, once a day:
  * reads the Caddy access-log file(s) under the logs volume (access.json + any rolled siblings);
  * attributes each DOWNLOAD request (`/data/edi|xml|bundles/...`) to a survey/station/format via
    manifest.json's reverse map (url -> row). An unknown download path lands in an `unattributed`
    bucket — never dropped silently;
  * counts portal VISITS as `/data/catalogue.json` fetches (one per SPA boot — the only
    server-observable visit proxy, record D3);
  * counts API-CONSUMER requests as fetches of the two DOCUMENTED machine-readable entry points the
    portal SPA never fetches for itself (`/data/products/manifest.json`, `/data/mtcat.json`). This is a
    PATH-CLASS signal only: no user-agent is inspected, nothing new is collected. It is an upper bound
    on programmatic use (a human can click the footer's mtcat link) and is reported as its own line,
    never folded into visits;
  * counts DISTINCT MASKED NETWORKS per day as a privacy-safe reach proxy. Caddy has already truncated
    the address to a /24 (v4) or /48 (v6) at the edge, so the distinct set IS a network count. The set
    lives in memory for the one run that folds a day and only its SIZE is written -- no address, masked
    or otherwise, is ever retained. Days folded before this existed carry no `networks` key at all
    (absent, not zero) and the screen renders them as unavailable;
  * resolves each request's MASKED client address (IPv4 /24, IPv6 /48 — already truncated at the
    edge by Caddy, record D2) to a country via the db-ip "IP to Country Lite" CSV using a stdlib
    bisect. A missing/unreadable CSV degrades every lookup to `unknown` — it never crashes;
  * for a request that resolves to AUSTRALIA, and ONLY when the compact AU state table is present,
    takes a second-level lookup to a STATE/TERRITORY code and counts it beneath the AU country row.
    STATE, NOT CITY, deliberately: see the AuStates class for the full rationale. An AU prefix the
    table does not cover is counted in an explicit `unattributed` bucket so the state rows always
    reconcile with the AU country figure. No table => no state buckets at all, silently;
  * FOLDS each complete day into a cumulative stats.json (running totals + a bounded daily tail + a
    permanent per-calendar-month rollup). The raw log lines are NOT the database: once a day is folded
    it is never re-read, so losing a rotated log loses nothing already folded. Idempotent: only days
    AFTER `last_folded_date` and STRICTLY BEFORE the run's UTC date (i.e. complete days) are folded, so
    re-runs never double-count.

RETENTION (aggregates only -- the RAW log keeps its own untouched ~7-day Caddy rotation):
  * DAILY rows are a rolling window of AUSMT_STATS_DAILY_KEEP days (default 92, i.e. a quarter) ending
    at the fold watermark. Older daily rows are pruned.
  * MONTHLY rollup rows are kept INDEFINITELY. They are tiny pure-count records (no address, no path,
    no identity) and they are what makes year-over-year funding reporting possible. Each month is
    accumulated AS ITS DAYS FOLD, never recomputed from the daily tail, so pruning a day never loses
    the month it belonged to.

WHAT IT NEVER WRITES (record D2/D6, the leak pin enforces it): an address (masked or not) and a
user-agent string never reach stats.json. Only aggregates leave the pipeline — counts + dailies.

Config (env; every path derives from AUSMT_DATA_DIR, each overridable for tests):
  AUSMT_DATA_DIR            (required) host root. Everything below defaults under it.
  AUSMT_STATS_LOG_DIR       Caddy access-log dir           [default $AUSMT_DATA_DIR/logs/caddy]
  AUSMT_STATS_MANIFEST      served download manifest       [default $AUSMT_DATA_DIR/site-data/current/manifest.json]
  AUSMT_STATS_DBIP_CSV      db-ip IP-to-Country Lite CSV   [default $AUSMT_DATA_DIR/geoip/dbip-country-lite.csv]
  AUSMT_STATS_AU_STATES_CSV compact AU state table         [default $AUSMT_DATA_DIR/geoip/dbip-au-states.csv]
                            (produced by deploy/scripts/prep_au_states.py; absent => country only)
  AUSMT_STATS_FILE          the cumulative stats.json      [default $AUSMT_DATA_DIR/gateway/state/stats.json]
  AUSMT_STATS_DAILY_KEEP    daily-row retention, in DAYS   [default 92; monthly rollups are never pruned]
  AUSMT_STATS_NOW           run instant (ISO %Y-%m-%dT%H:%M:%SZ or %Y-%m-%d) — TEST hook for determinism

Exit code is ALWAYS 0 on the normal path (best-effort, timer-safe); a genuinely broken environment
prints ONE loud note to stderr and still exits 0 so the timer never flaps.
"""
from __future__ import annotations

import bisect
import csv
import datetime as dt
import glob
import ipaddress
import json
import os
import sys
from pathlib import Path

# The daily aggregation cadence, in minutes — stamped into stats.json as the staleness clock the
# gateway reads (serve_state.ops_status_stale: stale past ~2 periods => ~2 days, record D4).
TIMER_PERIOD_MIN = 1440

# The stats.json schema version. v2 adds: per-survey volume, per-dataset volume, the station-file vs
# survey-bundle split, an API-consumer request class, per-day volume/format/kind/network detail, and the
# permanent monthly rollups. v1 files are UPGRADED IN PLACE by _coerce_prev (tolerant read, no migration
# script): every v1 field is carried forward, the new dimensions simply start accruing from the next fold.
#
# The AU state breakdown (`by_state`, and `states` on a day row) is an ADDITIVE v2 dimension and does
# NOT bump this number: like every other optional input in this file it is detected by KEY PRESENCE,
# never by version, and a v2 file written before it existed reads back cleanly with the maps empty.
# Bumping the version would gate nothing and would only invite a migration step that is not needed.
SCHEMA_VERSION = 2

# The rolling window (in DAYS) of daily rows kept in stats.json. 92 days is one quarter, which is what
# the quarterly funding view needs. Monthly rollups are NOT subject to this -- they are kept forever.
DEFAULT_DAILY_KEEP_DAYS = 92

# The three served download families (path prefixes under /data/) and the visit proxy. `/data/h5/*`
# is a latent Caddy matcher with NO producer (record D1) — deliberately NOT a download family here.
_DOWNLOAD_FAMILIES = ("edi", "xml", "bundles")
_DATA_PREFIX = "/data/"
_VISIT_PATH = "/data/catalogue.json"

# The API-CONSUMER path class: the documented machine-readable entry points that the portal's OWN
# JavaScript never fetches, so a hit is a third party reading the corpus programmatically rather than a
# browser booting the SPA. Verified against the shipped portal tree, and the exclusions are the point:
#   * /data/catalogue.json, /data/surveys.json, /data/tf.json, /data/sci.json, /data/manifest.json,
#     /data/build.json, /data/collections.json, /data/coord_policy.json, /data/build_provenance.json
#     are all fetched by portal/src/data.js on every SPA boot -- they measure browsers, not consumers;
#   * /data/products/<slug>/<station>/station.json is fetched by portal/src/drawer.js when a station
#     drawer opens -- also a browser.
# What is left is the pair About documents as the programmatic surface. This is a PATH CLASS, never a
# user-agent test, and it is an UPPER BOUND: the mtcat link sits in every page footer, so a human click
# lands here too. Reported as its own line, never merged into visits.
_API_PATHS = ("/data/products/manifest.json", "/data/mtcat.json")

# A conservative bot filter (record D2: "user-agent for bot filtering only"). The UA is read
# transiently and NEVER stored. Kept small and lower-cased; aggregate reporting tolerates the margin.
_BOT_TOKENS = ("bot", "spider", "crawl", "slurp", "bingpreview", "facebookexternalhit",
               "headlesschrome", "python-requests", "curl/", "wget/", "monitoring", "uptime")


# --------------------------------------------------------------------------------------------------
# Timestamp helpers (the shared UTC shape, kept identical to alert.sh / serve_state so the gateway's
# staleness clock parses stats.json the same way it parses ops-status.json).
# --------------------------------------------------------------------------------------------------
_UTC_FMT = "%Y-%m-%dT%H:%M:%SZ"


def now_utc(now: dt.datetime | None = None) -> str:
    return (now or dt.datetime.now(dt.timezone.utc)).strftime(_UTC_FMT)


def _run_datetime() -> dt.datetime:
    """The run instant as an aware UTC datetime. AUSMT_STATS_NOW pins it for deterministic tests
    (accepts a full ISO stamp or a bare date); otherwise it is wall-clock UTC now."""
    raw = os.environ.get("AUSMT_STATS_NOW", "").strip()
    if raw:
        for fmt in (_UTC_FMT, "%Y-%m-%d"):
            try:
                return dt.datetime.strptime(raw, fmt).replace(tzinfo=dt.timezone.utc)
            except ValueError:
                continue
    return dt.datetime.now(dt.timezone.utc)


# --------------------------------------------------------------------------------------------------
# Geo lookup: a stdlib bisect over a flat `start,end,VALUE` range CSV (record D2: no maxminddb, no
# geoipupdate, no MaxMind EULA custody). Two tables ride this one shape:
#   * GeoIP     - the db-ip "IP to Country Lite" CSV (start,end,CC), covering the whole internet;
#   * AuStates  - the compact AU-only state table deploy/scripts/prep_au_states.py distils from the
#                 db-ip "IP to City Lite" CSV (start,end,STATE).
# Each CSV covers BOTH IPv4 and IPv6, so it is split into two sorted range tables and the right one is
# bisected per address. Both tables are OPTIONAL inputs: absent or unreadable, every lookup misses and
# the fold completes with that dimension simply unavailable.
# --------------------------------------------------------------------------------------------------
class _RangeTable:
    """A sorted per-IP-version range table over a `start,end,VALUE` CSV. Construct via `load(path)`; an
    absent, unreadable, empty or malformed CSV yields an EMPTY table whose every lookup misses; the
    aggregator still completes (record D6 country pin). Ranges are stored per IP-version as parallel
    sorted lists (starts[] for the bisect, plus (start,end,value) records) so a lookup is one bisect +
    one bounds check. Comment rows (a leading '#') and short rows are skipped."""

    def __init__(self) -> None:
        # version -> (sorted_start_ints, [(start_int, end_int, value), ...] aligned to sorted_start_ints)
        self._starts: dict[int, list[int]] = {4: [], 6: []}
        self._ranges: dict[int, list[tuple[int, int, str]]] = {4: [], 6: []}
        self.loaded = False
        self.row_count = 0

    @staticmethod
    def _coerce_value(raw: str) -> str | None:
        """The third column as this table's value, or None to skip the row. Subclasses narrow it."""
        v = raw.strip().upper()
        return v or None

    @classmethod
    def load(cls, path) -> "_RangeTable":
        g = cls()
        if not path:
            return g
        p = Path(path)
        if not p.is_file():
            return g
        raw4: list[tuple[int, int, str]] = []
        raw6: list[tuple[int, int, str]] = []
        try:
            with open(p, encoding="utf-8", newline="") as fh:
                for row in csv.reader(fh):
                    if len(row) < 3 or row[0].lstrip().startswith("#"):
                        continue
                    start_s, end_s = row[0].strip(), row[1].strip()
                    value = cls._coerce_value(row[2])
                    if not start_s or not end_s or value is None:
                        continue
                    try:
                        start = ipaddress.ip_address(start_s)
                        end = ipaddress.ip_address(end_s)
                    except ValueError:
                        continue
                    if start.version != end.version:
                        continue
                    (raw4 if start.version == 4 else raw6).append((int(start), int(end), value))
        except OSError:
            return g            # unreadable mid-stream => degrade to an empty (miss-everything) table
        for ver, raw in ((4, raw4), (6, raw6)):
            raw.sort(key=lambda r: r[0])
            g._ranges[ver] = raw
            g._starts[ver] = [r[0] for r in raw]
        g.row_count = len(raw4) + len(raw6)
        g.loaded = g.row_count > 0
        return g

    def lookup(self, address: str | None) -> str | None:
        """The value whose range contains `address` (a masked IPv4/IPv6 string), or None, for an empty
        table, an unparseable address, or an address that falls in no range."""
        if not address:
            return None
        try:
            ip = ipaddress.ip_address(address.strip())
        except ValueError:
            return None
        ver = ip.version
        starts = self._starts.get(ver) or []
        if not starts:
            return None
        n = int(ip)
        idx = bisect.bisect_right(starts, n) - 1
        if idx < 0:
            return None
        start, end, value = self._ranges[ver][idx]
        return value if start <= n <= end else None


class GeoIP(_RangeTable):
    """Country lookup for a (masked) address, over the db-ip "IP to Country Lite" CSV."""

    def country(self, address: str | None) -> str:
        """The 2-letter country code for `address`, or 'unknown' when nothing resolves."""
        return self.lookup(address) or "unknown"


# The eight Australian states and territories, in the conventional listing order. This tuple is the
# WHOLE vocabulary the fold will accept from the state table, so a hand-edited or mangled table cannot
# push an arbitrary label onto the analytics screen.
AU_STATE_CODES = ("NSW", "VIC", "QLD", "SA", "WA", "TAS", "NT", "ACT")

# The bucket an AU request lands in when the state table IS present but its prefix resolves to no
# state. It is counted, never dropped: the state rows plus this bucket must reconcile with the AU
# country row, or the screen's breakdown would quietly under-report its own parent figure.
AU_STATE_UNATTRIBUTED = "unattributed"


class AuStates(_RangeTable):
    """AU STATE lookup for a (masked) address, over the compact table deploy/scripts/prep_au_states.py
    distils from the db-ip "IP to City Lite" CSV.

    WHY STATE, AND WHY NOT CITY -- a ratified design decision, recorded here so it is not casually
    "improved" into a city breakdown later:
      * the address resolved here was ALREADY TRUNCATED at the edge (IPv4 /24, IPv6 /48). A /24 prefix
        does not place a request in a city reliably -- mobile carrier and CGNAT pools routinely serve a
        whole state from one prefix -- so a city figure would be confidently wrong;
      * the Australian magnetotelluric research community is small. A city cell is QUASI-IDENTIFYING:
        "3 downloads from Hobart" names a research group. A state cell is not.
    State is the finest grain that is BOTH defensible from a /24 and non-identifying at this
    community's scale. Do not add a city dimension here.

    Like the country CSV this is an OPTIONAL input: absent, unreadable or empty, every lookup misses,
    no state buckets are written at all, and the fold is country-only exactly as it was before."""

    @staticmethod
    def _coerce_value(raw: str) -> str | None:
        code = raw.strip().upper()
        return code if code in AU_STATE_CODES else None

    def state(self, address: str | None) -> str | None:
        """The state/territory code for `address`, or None when the table does not cover it."""
        return self.lookup(address)


# --------------------------------------------------------------------------------------------------
# Manifest reverse map: the download-URL -> dataset resolver (record D1 — manifest.json is the
# authoritative reverse map). Keys are the manifest's portal-relative urls (e.g. 'edi/slug/A1.edi');
# tier=nci rows carry ABSOLUTE urls that never match a /data path, so they self-exclude harmlessly.
# --------------------------------------------------------------------------------------------------
def build_reverse_map(manifest: dict | None) -> dict[str, dict]:
    """{normalised_url: {survey, station, slug, format, kind}} over manifest files[] + bundles[]. A
    file row resolves to a station (station set, slug None); a bundle to a survey package (slug set,
    station None). Returns {} for a missing/malformed manifest — every download then falls to
    `unattributed`, never a crash."""
    out: dict[str, dict] = {}
    if not isinstance(manifest, dict):
        return out
    for row in manifest.get("files") or []:
        if not isinstance(row, dict):
            continue
        url = _norm_url(row.get("url"))
        if url:
            out[url] = {"survey": row.get("survey"), "station": row.get("station"),
                        "slug": None, "format": row.get("format"), "kind": "file"}
    for row in manifest.get("bundles") or []:
        if not isinstance(row, dict):
            continue
        url = _norm_url(row.get("url"))
        if url:
            out[url] = {"survey": row.get("survey"), "station": None,
                        "slug": row.get("slug"), "format": row.get("format"), "kind": "bundle"}
    return out


def _norm_url(url) -> str | None:
    if not isinstance(url, str) or not url:
        return None
    return url.replace("\\", "/").lstrip("/")


# --------------------------------------------------------------------------------------------------
# Caddy log-line parsing. The JSON encoder logs one object per request; we read only the minimal
# fields the record permits (ts / method / uri / status / size / masked-address / UA-for-bot-only).
# --------------------------------------------------------------------------------------------------
def parse_caddy_line(line: str) -> dict | None:
    """Extract {date, method, path, status, size, address, ua} from one Caddy JSON access-log line, or
    None for a blank/non-JSON/irrelevant line. `date` is the UTC date (YYYY-MM-DD) from the `ts` field
    (float epoch by default; an ISO string is tolerated). `address` is the MASKED client address Caddy
    already truncated at the edge — used only for country + bot filtering, never stored."""
    line = line.strip()
    if not line or line[0] != "{":
        return None
    try:
        rec = json.loads(line)
    except ValueError:
        return None
    if not isinstance(rec, dict):
        return None
    req = rec.get("request")
    if not isinstance(req, dict):
        return None
    ts = rec.get("ts")
    date = _ts_to_date(ts)
    if date is None:
        return None
    uri = req.get("uri") or ""
    if not isinstance(uri, str):
        return None
    path = uri.split("?", 1)[0]
    try:
        from urllib.parse import unquote
        path = unquote(path)
    except Exception:  # noqa: BLE001 -- a decode quirk must never drop a line; use the raw path
        pass
    status = rec.get("status")
    try:
        status = int(status)
    except (TypeError, ValueError):
        status = 0
    size = rec.get("size")
    try:
        size = int(size)
    except (TypeError, ValueError):
        size = 0
    # Masked client address: prefer the resolved client_ip, fall back to the direct peer remote_ip.
    address = req.get("client_ip") or req.get("remote_ip") or None
    if not isinstance(address, str):
        address = None
    # User-Agent header (Caddy logs headers as arrays) — read for bot filtering only, never stored.
    ua = ""
    headers = req.get("headers")
    if isinstance(headers, dict):
        h = headers.get("User-Agent") or headers.get("user-agent")
        if isinstance(h, list) and h:
            ua = str(h[0])
        elif isinstance(h, str):
            ua = h
    return {"date": date, "method": (req.get("method") or "").upper(), "path": path,
            "status": status, "size": size, "address": address, "ua": ua}


def _ts_to_date(ts) -> str | None:
    if isinstance(ts, (int, float)):
        try:
            return dt.datetime.fromtimestamp(float(ts), dt.timezone.utc).strftime("%Y-%m-%d")
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(ts, str) and ts:
        for fmt in (_UTC_FMT, "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d"):
            try:
                return dt.datetime.strptime(ts, fmt).replace(tzinfo=dt.timezone.utc).strftime("%Y-%m-%d")
            except ValueError:
                continue
        # An ISO-with-offset stamp (Caddy's rfc3339 time_format option) — take the leading date.
        if len(ts) >= 10 and ts[4] == "-" and ts[7] == "-":
            return ts[:10]
    return None


def is_bot(ua: str) -> bool:
    u = (ua or "").lower()
    return any(tok in u for tok in _BOT_TOKENS)


def classify(path: str) -> tuple[str, str | None]:
    """(kind, rel) for a request path: ('visit', None) for the catalogue fetch; ('api', None) for one of
    the documented machine-readable entry points the SPA never fetches itself; ('download', rel) for a
    `/data/edi|xml|bundles/...` path where rel is the manifest-relative url; ('ignore', None) otherwise.

    The classes are MUTUALLY EXCLUSIVE by construction (the visit path, the two API paths, and the three
    download families are disjoint), so no request is ever counted twice."""
    if path == _VISIT_PATH:
        return "visit", None
    if path in _API_PATHS:
        return "api", None
    if path.startswith(_DATA_PREFIX):
        rel = path[len(_DATA_PREFIX):]
        family = rel.split("/", 1)[0]
        if family in _DOWNLOAD_FAMILIES and "/" in rel:
            return "download", rel
    return "ignore", None


# --------------------------------------------------------------------------------------------------
# The fold. `aggregate` is a PURE function (prev_stats + log lines + reverse map + geoip + run date ->
# new_stats) so the pins can drive it deterministically without touching the filesystem or a timer.
# --------------------------------------------------------------------------------------------------
def _empty_stats() -> dict:
    return {"schema": SCHEMA_VERSION, "timer_period_min": TIMER_PERIOD_MIN, "generated_at": None,
            "since": None, "last_folded_date": None, "detail_since": None,
            "totals": {"downloads": 0, "visits": 0, "download_bytes": 0, "unattributed": 0,
                       "api_requests": 0},
            "downloads": {"by_format": {}, "by_survey": {}, "by_dataset": {}, "by_kind": {}},
            "countries": {}, "by_state": {}, "daily": [], "monthly": []}


def _empty_month(month: str) -> dict:
    """One calendar-month rollup row. `days` counts the distinct dates with counted activity folded into
    it; `seeded_days` records how many of those came from a pre-upgrade daily row (downloads + visits
    only), so the screen can say which months carry partial detail instead of implying a real zero."""
    return {"month": month, "downloads": 0, "visits": 0, "download_bytes": 0, "unattributed": 0,
            "api_requests": 0, "days": 0, "seeded_days": 0,
            "formats": {}, "kinds": {}, "surveys": {}, "countries": {}, "by_state": {}}


def _as_int(v, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _next_day(date_str) -> str | None:
    """The ISO day after `date_str`, or None if it is not an ISO date. Used to stamp `detail_since` when
    a v1 file is upgraded: the richer dimensions begin the day AFTER that file's fold watermark."""
    if not isinstance(date_str, str):
        return None
    try:
        return (dt.date.fromisoformat(date_str) + dt.timedelta(days=1)).isoformat()
    except ValueError:
        return None


def _coerce_survey_map(raw) -> dict[str, dict]:
    """The by_survey map, tolerant of BOTH shapes: v1 `{survey: count}` and v2
    `{survey: {downloads, bytes}}`. A v1 int upgrades to {downloads: n, bytes: 0} -- the historical
    per-survey VOLUME was never recorded and is NOT invented; `detail_since` tells the screen from when
    the bytes column is real, so it can say so rather than show a silent undercount."""
    out: dict[str, dict] = {}
    if not isinstance(raw, dict):
        return out
    for name, val in raw.items():
        if not isinstance(name, str):
            continue
        if isinstance(val, dict):
            out[name] = {"downloads": _as_int(val.get("downloads")), "bytes": _as_int(val.get("bytes"))}
        else:
            out[name] = {"downloads": _as_int(val), "bytes": 0}
    return out


def _coerce_dataset_map(raw) -> dict[str, dict]:
    """The by_dataset map, tolerant of v1 rows (no `bytes` key). A v1 row keeps its counts and gains a
    zero byte accumulator that accrues from the next fold on."""
    out: dict[str, dict] = {}
    if not isinstance(raw, dict):
        return out
    for url, row in raw.items():
        if not isinstance(url, str) or not isinstance(row, dict):
            continue
        out[url] = {"survey": row.get("survey"), "station": row.get("station"),
                    "slug": row.get("slug"), "format": row.get("format"),
                    "kind": row.get("kind"), "downloads": _as_int(row.get("downloads")),
                    "bytes": _as_int(row.get("bytes"))}
    return out


def _coerce_month_rows(raw) -> list[dict]:
    """Well-formed monthly rollup rows from a prior file, date-sorted. A malformed row is dropped rather
    than allowed to poison the arithmetic."""
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    for row in raw:
        if not isinstance(row, dict) or not isinstance(row.get("month"), str):
            continue
        m = _empty_month(row["month"])
        for k in ("downloads", "visits", "download_bytes", "unattributed", "api_requests",
                  "days", "seeded_days"):
            m[k] = _as_int(row.get(k))
        for k in ("formats", "kinds", "countries", "by_state"):
            if isinstance(row.get(k), dict):
                m[k] = {str(kk): _as_int(vv) for kk, vv in row[k].items()}
        m["surveys"] = _coerce_survey_map(row.get("surveys"))
        out.append(m)
    out.sort(key=lambda r: r["month"])
    return out


def _seed_monthly_from_daily(daily: list) -> list[dict]:
    """Bootstrap the monthly rollups from a v1 file's existing daily tail, carrying ONLY the two fields
    those rows actually hold (downloads + visits) and marking each seeded day in `seeded_days`.

    This is aggregation of data we already have, NOT backfill: no month that is absent from the daily
    tail is invented, and the fields the v1 daily rows never carried (volume, formats, kinds, per-survey,
    countries, API) stay at zero WITH the seeded_days marker beside them, so the screen annotates those
    months instead of presenting a partial figure as complete."""
    index: dict[str, dict] = {}
    for d in daily:
        date = d.get("date")
        if not isinstance(date, str) or len(date) < 7:
            continue
        row = index.get(date[:7])
        if row is None:
            row = _empty_month(date[:7])
            index[date[:7]] = row
        row["downloads"] += _as_int(d.get("downloads"))
        row["visits"] += _as_int(d.get("visits"))
        row["days"] += 1
        row["seeded_days"] += 1
    return [index[m] for m in sorted(index)]


def _coerce_prev(prev: dict | None) -> dict:
    """Start from a fresh skeleton and merge a well-formed prior stats.json over it (defensive against a
    truncated/older-schema file). Anything unparseable falls back to the empty skeleton — a corrupt
    prior must not crash the fold (worst case, cumulative counts restart; the daily tail re-accrues).

    This is ALSO the v1 -> v2 migration seam: it is a TOLERANT READ, not a migration script. A v1 file
    (no `monthly`, by_survey as bare ints, no by_kind/api_requests) is carried forward whole, its monthly
    rollups are seeded from its daily tail, and `detail_since` is stamped at the day after its fold
    watermark so the screen can be explicit about which figures predate the detailed dimensions."""
    s = _empty_stats()
    if not isinstance(prev, dict):
        return s
    for k in ("since", "last_folded_date"):
        if isinstance(prev.get(k), str):
            s[k] = prev[k]
    pt = prev.get("totals")
    if isinstance(pt, dict):
        for k in s["totals"]:
            if isinstance(pt.get(k), int):
                s["totals"][k] = pt[k]
    pd = prev.get("downloads")
    if isinstance(pd, dict):
        if isinstance(pd.get("by_format"), dict):
            s["downloads"]["by_format"] = dict(pd["by_format"])
        if isinstance(pd.get("by_kind"), dict):
            s["downloads"]["by_kind"] = dict(pd["by_kind"])
        s["downloads"]["by_survey"] = _coerce_survey_map(pd.get("by_survey"))
        s["downloads"]["by_dataset"] = _coerce_dataset_map(pd.get("by_dataset"))
    if isinstance(prev.get("countries"), dict):
        s["countries"] = dict(prev["countries"])
    # The AU state breakdown, carried forward whole. A file written before it existed simply has no
    # such key and starts empty: state counts are FORWARD-ONLY and no earlier day is ever backfilled
    # (that would need raw logs that have long since rotated away).
    if isinstance(prev.get("by_state"), dict):
        s["by_state"] = {str(k): _as_int(v) for k, v in prev["by_state"].items()}
    if isinstance(prev.get("daily"), list):
        s["daily"] = [d for d in prev["daily"] if isinstance(d, dict) and isinstance(d.get("date"), str)]
    # The v1 -> v2 hinge. Key on the PRESENCE of `monthly`, never on its emptiness: a genuinely fresh v2
    # file has monthly == [] and must not be re-seeded or mis-stamped on every later run.
    if "monthly" in prev:
        s["monthly"] = _coerce_month_rows(prev.get("monthly"))
        ds = prev.get("detail_since")
        s["detail_since"] = ds if isinstance(ds, str) else None
    else:
        s["monthly"] = _seed_monthly_from_daily(s["daily"])
        # None on a first-ever fold (nothing predates the detail, so there is nothing to caveat).
        s["detail_since"] = _next_day(s["last_folded_date"])
    return s


def aggregate(prev: dict | None, lines, reverse_map: dict[str, dict], geoip: GeoIP,
              run_dt: dt.datetime, *, daily_keep: int = DEFAULT_DAILY_KEEP_DAYS,
              au_states: "AuStates | None" = None) -> dict:
    """Fold every COMPLETE day in `lines` into `prev`, returning the new cumulative stats dict.

    Only dates d with last_folded_date < d < run_dt.date() are folded (a strictly-earlier complete
    day), so the CURRENT (partial) day is never counted and re-runs never double-count. `run_dt.date()`
    becomes the new last_folded_date, so a day rotated away before it could be folded is simply skipped
    (record D4: losing a raw log loses nothing already folded, and nothing not-yet-folded is re-read).

    Each counted request lands in THREE places at once: the cumulative totals, its day row, and its
    calendar-month rollup. Accumulating the month AS THE DAY FOLDS (rather than summing the daily tail
    later) is what lets the daily window be pruned to `daily_keep` days while the monthly history stays
    complete and permanent.

    `au_states` is the OPTIONAL AU state table. When it is present, a request that classifies as AU also
    lands in a state bucket (at all three grains); when it is absent the fold is country-only and writes
    no state buckets at all: absent, never a zero (see AuStates for why state and not city)."""
    stats = _coerce_prev(prev)
    prev_folded = stats.get("last_folded_date")
    cutoff_date = (run_dt.date() - dt.timedelta(days=1))  # last complete day
    cutoff = cutoff_date.isoformat()

    totals = stats["totals"]
    by_format = stats["downloads"]["by_format"]
    by_survey = stats["downloads"]["by_survey"]
    by_dataset = stats["downloads"]["by_dataset"]
    by_kind = stats["downloads"]["by_kind"]
    countries = stats["countries"]
    by_state = stats["by_state"]
    daily_index = {d["date"]: d for d in stats["daily"]}
    month_index = {m["month"]: m for m in stats["monthly"]}
    # date -> set of MASKED networks seen on it, for THIS run only. Caddy already truncated the address
    # to a /24 (v4) or /48 (v6), so the distinct set is a network count. Only its SIZE is ever written;
    # the sets die with the process. A day folds exactly once, so one run sees all of that day's lines.
    networks_seen: dict[str, set] = {}
    # date -> month, for the "distinct active days per month" counter (a day counts once per month even
    # though it contributes many requests).
    days_seen: dict[str, str] = {}

    for raw in lines:
        rec = parse_caddy_line(raw) if isinstance(raw, str) else None
        if rec is None:
            continue
        date = rec["date"]
        # Only fold strictly-new, strictly-complete days.
        if date > cutoff:
            continue
        if prev_folded is not None and date <= prev_folded:
            continue
        if rec["method"] not in ("GET", ""):
            continue
        if is_bot(rec["ua"]):
            continue
        kind, rel = classify(rec["path"])
        if kind == "ignore":
            continue
        if kind in ("visit", "api"):
            if rec["status"] not in (200, 304):
                continue
        elif rec["status"] != 200:              # download: only a completed full transfer counts
            continue
        day = _day_row(daily_index, stats["daily"], date)
        month = _month_row(month_index, stats["monthly"], date[:7])
        days_seen[date] = date[:7]
        _note_network(networks_seen, date, rec["address"])

        if kind == "visit":
            totals["visits"] += 1
            day["visits"] += 1
            month["visits"] += 1
            _count_geo(geoip, au_states, rec["address"], countries, by_state, month, day)
        elif kind == "api":
            totals["api_requests"] += 1
            day["api_requests"] = _as_int(day.get("api_requests")) + 1
            month["api_requests"] += 1
        else:
            size = max(rec["size"], 0)
            totals["downloads"] += 1
            totals["download_bytes"] += size
            row = reverse_map.get(rel)
            if row is None:
                totals["unattributed"] += 1
                month["unattributed"] += 1
                fmt = "unattributed"
                survey = None
                kind_key = "unattributed"
            else:
                fmt = row.get("format") or "unknown"
                survey = row.get("survey")
                # 'file' = one station's own artifact, 'bundle' = a whole-survey package. The reverse map
                # already carries the distinction; this is what makes the single-station vs survey-bundle
                # split derivable with no new collection.
                kind_key = row.get("kind") or "file"
                d = by_dataset.get(rel)
                if d is None:
                    by_dataset[rel] = {"survey": survey, "station": row.get("station"),
                                       "slug": row.get("slug"), "format": fmt, "kind": kind_key,
                                       "downloads": 1, "bytes": size}
                else:
                    d["downloads"] = _as_int(d.get("downloads")) + 1
                    d["bytes"] = _as_int(d.get("bytes")) + size
            by_format[fmt] = by_format.get(fmt, 0) + 1
            by_kind[kind_key] = by_kind.get(kind_key, 0) + 1
            day["downloads"] += 1
            day["download_bytes"] = _as_int(day.get("download_bytes")) + size
            _bump(day.setdefault("formats", {}), fmt)
            _bump(day.setdefault("kinds", {}), kind_key)
            month["downloads"] += 1
            month["download_bytes"] += size
            _bump(month["formats"], fmt)
            _bump(month["kinds"], kind_key)
            if survey:
                _bump_survey(by_survey, survey, size)
                _bump_survey(month["surveys"], survey, size)
            _count_geo(geoip, au_states, rec["address"], countries, by_state, month, day)

    # Distinct-network counts for the days folded in THIS run. Only the SIZE of each set is written --
    # the masked addresses themselves never leave memory (record D2/D6).
    for date, nets in networks_seen.items():
        row = daily_index.get(date)
        if row is not None:
            row["networks"] = len(nets)
    # One increment per distinct ACTIVE date, so a month row records how much of itself it covers.
    for month_key in days_seen.values():
        month_index[month_key]["days"] += 1

    # Advance the fold watermark to the run's date-1 (the cutoff), always — a window with no lines
    # still advances so old dates are never re-scanned.
    if prev_folded is None or cutoff > prev_folded:
        stats["last_folded_date"] = cutoff
    if stats["since"] is None and stats["daily"]:
        stats["since"] = min(d["date"] for d in stats["daily"])

    # RETENTION, aggregates only. Daily rows: a rolling window of `daily_keep` days ending at the fold
    # watermark. Monthly rollups: NEVER pruned -- they are the permanent funding record and are already
    # complete for every day that has ever folded, including days this prune is about to drop.
    stats["daily"].sort(key=lambda d: d["date"])
    stats["daily"] = _prune_daily(stats["daily"], stats["last_folded_date"], daily_keep)
    stats["monthly"].sort(key=lambda m: m["month"])

    stats["schema"] = SCHEMA_VERSION
    stats["generated_at"] = now_utc(run_dt)
    stats["timer_period_min"] = TIMER_PERIOD_MIN
    return stats


def _bump(counter: dict, key: str, n: int = 1) -> None:
    counter[key] = _as_int(counter.get(key)) + n


def _bump_survey(index: dict, survey: str, size: int) -> None:
    """One download of `size` bytes against `survey` in a {survey: {downloads, bytes}} map. Bundles land
    here under their OWN survey (the manifest bundle row carries it), so a whole-survey package download
    is credited to that survey exactly like a per-station file."""
    row = index.get(survey)
    if not isinstance(row, dict):
        row = {"downloads": _as_int(row), "bytes": 0}
        index[survey] = row
    row["downloads"] = _as_int(row.get("downloads")) + 1
    row["bytes"] = _as_int(row.get("bytes")) + size


def _count_geo(geoip: GeoIP, au_states, address, countries: dict, by_state: dict,
               month: dict, day: dict) -> None:
    """Resolve the masked address to a country (and, for AU, to a state) and count it. The address
    itself is discarded immediately -- only the country code and the state code are ever counted.

    The state half is entirely conditional on the OPTIONAL state table being loaded. When it is:
      * every AU request lands in exactly ONE bucket -- its state, or the explicit `unattributed`
        bucket when the table does not cover that prefix. Nothing is dropped, so the state rows plus
        `unattributed` reconcile exactly with the AU country row they sit beneath;
      * the count goes to the cumulative map, the calendar-month rollup, and the day row.
    When it is NOT loaded, nothing at all is written: no bucket, no zero, no key on the day row.
    Days folded before the table was installed are therefore ABSENT from the breakdown rather than
    reading as a measured zero, and they are never backfilled (the raw logs are long gone)."""
    cc = geoip.country(address)
    _bump(countries, cc)
    _bump(month["countries"], cc)
    if cc != "AU" or au_states is None or not au_states.loaded:
        return
    code = au_states.state(address) or AU_STATE_UNATTRIBUTED
    _bump(by_state, code)
    _bump(month.setdefault("by_state", {}), code)
    # setdefault, never a skeleton field: a daily row folded before state counting existed is left
    # exactly as it was written (the forward-only pin).
    _bump(day.setdefault("states", {}), code)


def _note_network(seen: dict[str, set], date: str, address) -> None:
    """Record a masked network for `date` in the RUN-LOCAL set. The address is a /24 or /48 already
    truncated at the edge, it is never written anywhere, and the set is discarded when the process
    exits: what survives is a single integer per day."""
    if not isinstance(address, str) or not address.strip():
        return
    seen.setdefault(date, set()).add(address.strip())


def _prune_daily(daily: list, last_folded, keep_days: int) -> list:
    """The daily rolling window: keep rows dated within `keep_days` days ending at the fold watermark
    (the count cap is a belt-and-braces backstop against a clock-skewed future date). keep_days <= 0
    disables pruning. Monthly rollups are deliberately NOT touched here."""
    if not keep_days or keep_days <= 0:
        return daily
    if isinstance(last_folded, str):
        try:
            cutoff = (dt.date.fromisoformat(last_folded) - dt.timedelta(days=keep_days - 1)).isoformat()
            daily = [d for d in daily if d.get("date", "") >= cutoff]
        except ValueError:
            pass
    return daily[-keep_days:] if len(daily) > keep_days else daily


def _day_row(index: dict, daily: list, date: str) -> dict:
    row = index.get(date)
    if row is None:
        row = {"date": date, "downloads": 0, "visits": 0, "download_bytes": 0, "api_requests": 0,
               "formats": {}, "kinds": {}}
        index[date] = row
        daily.append(row)
    return row


def _month_row(index: dict, monthly: list, month: str) -> dict:
    row = index.get(month)
    if row is None:
        row = _empty_month(month)
        index[month] = row
        monthly.append(row)
    return row


# --------------------------------------------------------------------------------------------------
# I/O: read the log dir, load inputs, write stats.json atomically (tmp -> chmod 0644 -> os.replace).
# --------------------------------------------------------------------------------------------------
def read_log_lines(log_dir) -> list[str]:
    """Every line of every Caddy access-log file under `log_dir` (access.json + rolled siblings
    access*.json). Tolerant of an absent dir / already-rotated files (record D6 retention pin): a
    missing dir or unreadable file yields no lines, never an exception."""
    lines: list[str] = []
    if not log_dir:
        return lines
    d = Path(log_dir)
    if not d.is_dir():
        return lines
    files = sorted(glob.glob(str(d / "access*.json")) + glob.glob(str(d / "access*.log")))
    for f in files:
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                lines.extend(fh.read().splitlines())
        except OSError:
            continue
    return lines


def _load_json(path) -> dict | None:
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        return doc if isinstance(doc, dict) else None
    except (OSError, ValueError):
        return None


def write_stats_atomic(stats_file, stats: dict) -> None:
    """Atomic write: tmp under the dest dir -> chmod 0644 (the gateway uid 10002 reads it via the shared
    state dir, the alert.sh posture) -> os.replace. The dest dir must exist (the operator prep creates
    the state dir); a missing dir raises, caught by main()."""
    dest = Path(stats_file)
    tmp = dest.with_name(f"{dest.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(stats, indent=1), encoding="utf-8")
    try:
        os.chmod(tmp, 0o644)
    except OSError:
        pass
    os.replace(tmp, dest)


def _cfg(name: str, default: str) -> str:
    v = os.environ.get(name, "").strip()
    return v if v else default


def main(argv=None) -> int:
    """The timer entry point. Best-effort by contract: any failure prints ONE loud stderr note and
    still returns 0 so the daily timer never flaps. The atomic write is the only externally visible
    effect; a stale/absent input degrades a metric, it does not abort the run."""
    data_dir = os.environ.get("AUSMT_DATA_DIR", "").strip()
    if not data_dir:
        print("aggregate_stats: AUSMT_DATA_DIR unset -- nothing to aggregate; exiting 0", file=sys.stderr)
        return 0
    log_dir = _cfg("AUSMT_STATS_LOG_DIR", str(Path(data_dir) / "logs" / "caddy"))
    manifest_path = _cfg("AUSMT_STATS_MANIFEST", str(Path(data_dir) / "site-data" / "current" / "manifest.json"))
    dbip_csv = _cfg("AUSMT_STATS_DBIP_CSV", str(Path(data_dir) / "geoip" / "dbip-country-lite.csv"))
    au_states_csv = _cfg("AUSMT_STATS_AU_STATES_CSV",
                         str(Path(data_dir) / "geoip" / "dbip-au-states.csv"))
    stats_file = _cfg("AUSMT_STATS_FILE", str(Path(data_dir) / "gateway" / "state" / "stats.json"))
    try:
        daily_keep = int(_cfg("AUSMT_STATS_DAILY_KEEP", str(DEFAULT_DAILY_KEEP_DAYS)))
    except ValueError:
        daily_keep = DEFAULT_DAILY_KEEP_DAYS

    try:
        run_dt = _run_datetime()
        reverse_map = build_reverse_map(_load_json(manifest_path))
        geoip = GeoIP.load(dbip_csv)
        # The AU state table is OPTIONAL in exactly the way the country CSV is: absent, the fold is
        # country-only and silent about it (deploy/scripts/prep_au_states.py is what produces it).
        au_states = AuStates.load(au_states_csv)
        prev = _load_json(stats_file)
        lines = read_log_lines(log_dir)
        stats = aggregate(prev, lines, reverse_map, geoip, run_dt, daily_keep=daily_keep,
                          au_states=au_states)
        dest_dir = Path(stats_file).parent
        if not dest_dir.is_dir():
            print(f"aggregate_stats: state dir {dest_dir} does not exist -- not writing stats.json "
                  f"(is the gateway state dir created?)", file=sys.stderr)
            return 0
        write_stats_atomic(stats_file, stats)
        print(f"aggregate_stats: folded up to {stats.get('last_folded_date')} -- "
              f"downloads={stats['totals']['downloads']} visits={stats['totals']['visits']} "
              f"api={stats['totals']['api_requests']} months={len(stats['monthly'])} "
              f"days_kept={len(stats['daily'])} "
              f"manifest_rows={len(reverse_map)} geoip_rows={geoip.row_count} "
              f"au_state_rows={au_states.row_count} "
              f"log_lines={len(lines)} -> {stats_file}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 -- never raise into the timer; note loudly and exit 0
        print(f"aggregate_stats: aborted without writing ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
