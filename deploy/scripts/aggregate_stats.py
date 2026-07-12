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
  * resolves each request's MASKED client address (IPv4 /24, IPv6 /48 — already truncated at the
    edge by Caddy, record D2) to a country via the db-ip "IP to Country Lite" CSV using a stdlib
    bisect. A missing/unreadable CSV degrades every lookup to `unknown` — it never crashes;
  * FOLDS each complete day into a cumulative stats.json (running totals + a bounded daily tail).
    The raw log lines are NOT the database: once a day is folded it is never re-read, so losing a
    rotated log loses nothing already folded. Idempotent: only days AFTER `last_folded_date` and
    STRICTLY BEFORE the run's UTC date (i.e. complete days) are folded, so re-runs never double-count.

WHAT IT NEVER WRITES (record D2/D6, the leak pin enforces it): an address (masked or not) and a
user-agent string never reach stats.json. Only aggregates leave the pipeline — counts + dailies.

Config (env; every path derives from AUSMT_DATA_DIR, each overridable for tests):
  AUSMT_DATA_DIR            (required) host root. Everything below defaults under it.
  AUSMT_STATS_LOG_DIR       Caddy access-log dir           [default $AUSMT_DATA_DIR/logs/caddy]
  AUSMT_STATS_MANIFEST      served download manifest       [default $AUSMT_DATA_DIR/site-data/current/manifest.json]
  AUSMT_STATS_DBIP_CSV      db-ip IP-to-Country Lite CSV   [default $AUSMT_DATA_DIR/geoip/dbip-country-lite.csv]
  AUSMT_STATS_FILE          the cumulative stats.json      [default $AUSMT_DATA_DIR/gateway/state/stats.json]
  AUSMT_STATS_DAILY_KEEP    daily-series tail length       [default 90]
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

# The three served download families (path prefixes under /data/) and the visit proxy. `/data/h5/*`
# is a latent Caddy matcher with NO producer (record D1) — deliberately NOT a download family here.
_DOWNLOAD_FAMILIES = ("edi", "xml", "bundles")
_DATA_PREFIX = "/data/"
_VISIT_PATH = "/data/catalogue.json"

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
# GeoIP: a stdlib bisect over the db-ip "IP to Country Lite" CSV (record D2 — no maxminddb, no
# geoipupdate, no MaxMind EULA custody). The CSV is a flat list of ranges `start,end,CC` covering
# BOTH IPv4 and IPv6; we split it into two sorted range tables and bisect the right one per address.
# --------------------------------------------------------------------------------------------------
class GeoIP:
    """Country lookup for a (masked) address. Construct via `GeoIP.load(path)`; an absent, unreadable,
    empty, or malformed CSV yields an EMPTY table whose every lookup returns 'unknown' — the aggregator
    still completes (record D6 country pin). Ranges are stored per IP-version as parallel sorted lists
    (starts[] for the bisect, plus (start,end,cc) records) so a lookup is one bisect + one bounds check."""

    def __init__(self) -> None:
        # version -> (sorted_start_ints, [(start_int, end_int, cc), ...] aligned to sorted_start_ints)
        self._starts: dict[int, list[int]] = {4: [], 6: []}
        self._ranges: dict[int, list[tuple[int, int, str]]] = {4: [], 6: []}
        self.loaded = False
        self.row_count = 0

    @classmethod
    def load(cls, path) -> "GeoIP":
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
                    if len(row) < 3:
                        continue
                    start_s, end_s, cc = row[0].strip(), row[1].strip(), row[2].strip().upper()
                    if not start_s or not end_s or not cc:
                        continue
                    try:
                        start = ipaddress.ip_address(start_s)
                        end = ipaddress.ip_address(end_s)
                    except ValueError:
                        continue
                    if start.version != end.version:
                        continue
                    (raw4 if start.version == 4 else raw6).append((int(start), int(end), cc))
        except OSError:
            return g            # unreadable mid-stream => degrade to an empty (unknown) table
        for ver, raw in ((4, raw4), (6, raw6)):
            raw.sort(key=lambda r: r[0])
            g._ranges[ver] = raw
            g._starts[ver] = [r[0] for r in raw]
        g.row_count = len(raw4) + len(raw6)
        g.loaded = g.row_count > 0
        return g

    def country(self, address: str | None) -> str:
        """The 2-letter country code for `address` (a masked IPv4/IPv6 string), or 'unknown' — for an
        empty table, an unparseable address, or an address that falls in no range."""
        if not address:
            return "unknown"
        try:
            ip = ipaddress.ip_address(address.strip())
        except ValueError:
            return "unknown"
        ver = ip.version
        starts = self._starts.get(ver) or []
        if not starts:
            return "unknown"
        n = int(ip)
        idx = bisect.bisect_right(starts, n) - 1
        if idx < 0:
            return "unknown"
        start, end, cc = self._ranges[ver][idx]
        return cc if start <= n <= end else "unknown"


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
    """(kind, rel) for a request path: ('visit', None) for the catalogue fetch; ('download', rel) for a
    `/data/edi|xml|bundles/...` path where rel is the manifest-relative url; ('ignore', None) otherwise."""
    if path == _VISIT_PATH:
        return "visit", None
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
    return {"schema": 1, "timer_period_min": TIMER_PERIOD_MIN, "generated_at": None,
            "since": None, "last_folded_date": None,
            "totals": {"downloads": 0, "visits": 0, "download_bytes": 0, "unattributed": 0},
            "downloads": {"by_format": {}, "by_survey": {}, "by_dataset": {}},
            "countries": {}, "daily": []}


def _coerce_prev(prev: dict | None) -> dict:
    """Start from a fresh skeleton and merge a well-formed prior stats.json over it (defensive against a
    truncated/older-schema file). Anything unparseable falls back to the empty skeleton — a corrupt
    prior must not crash the fold (worst case, cumulative counts restart; the daily tail re-accrues)."""
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
        for k in ("by_format", "by_survey", "by_dataset"):
            if isinstance(pd.get(k), dict):
                s["downloads"][k] = dict(pd[k])
    if isinstance(prev.get("countries"), dict):
        s["countries"] = dict(prev["countries"])
    if isinstance(prev.get("daily"), list):
        s["daily"] = [d for d in prev["daily"] if isinstance(d, dict) and isinstance(d.get("date"), str)]
    return s


def aggregate(prev: dict | None, lines, reverse_map: dict[str, dict], geoip: GeoIP,
              run_dt: dt.datetime, *, daily_keep: int = 90) -> dict:
    """Fold every COMPLETE day in `lines` into `prev`, returning the new cumulative stats dict.

    Only dates d with last_folded_date < d < run_dt.date() are folded (a strictly-earlier complete
    day), so the CURRENT (partial) day is never counted and re-runs never double-count. `run_dt.date()`
    becomes the new last_folded_date, so a day rotated away before it could be folded is simply skipped
    (record D4: losing a raw log loses nothing already folded — and nothing not-yet-folded is re-read)."""
    stats = _coerce_prev(prev)
    prev_folded = stats.get("last_folded_date")
    cutoff_date = (run_dt.date() - dt.timedelta(days=1))  # last complete day
    cutoff = cutoff_date.isoformat()

    totals = stats["totals"]
    by_format = stats["downloads"]["by_format"]
    by_survey = stats["downloads"]["by_survey"]
    by_dataset = stats["downloads"]["by_dataset"]
    countries = stats["countries"]
    daily_index = {d["date"]: d for d in stats["daily"]}

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
        if kind == "visit":
            if rec["status"] not in (200, 304):
                continue
            totals["visits"] += 1
            cc = geoip.country(rec["address"])
            countries[cc] = countries.get(cc, 0) + 1
            day = _day_row(daily_index, stats["daily"], date)
            day["visits"] += 1
        elif kind == "download":
            if rec["status"] != 200:            # only a completed full download counts
                continue
            totals["downloads"] += 1
            totals["download_bytes"] += max(rec["size"], 0)
            row = reverse_map.get(rel)
            if row is None:
                totals["unattributed"] += 1
                fmt = "unattributed"
                survey = None
            else:
                fmt = row.get("format") or "unknown"
                survey = row.get("survey")
                key = rel
                d = by_dataset.get(key)
                if d is None:
                    by_dataset[key] = {"survey": survey, "station": row.get("station"),
                                       "slug": row.get("slug"), "format": fmt, "downloads": 1}
                else:
                    d["downloads"] = int(d.get("downloads", 0)) + 1
            by_format[fmt] = by_format.get(fmt, 0) + 1
            if survey:
                by_survey[survey] = by_survey.get(survey, 0) + 1
            cc = geoip.country(rec["address"])
            countries[cc] = countries.get(cc, 0) + 1
            day = _day_row(daily_index, stats["daily"], date)
            day["downloads"] += 1

    # Advance the fold watermark to the run's date-1 (the cutoff), always — a window with no lines
    # still advances so old dates are never re-scanned.
    if prev_folded is None or cutoff > prev_folded:
        stats["last_folded_date"] = cutoff
    if stats["since"] is None and stats["daily"]:
        stats["since"] = min(d["date"] for d in stats["daily"])

    # Bounded, date-sorted daily tail.
    stats["daily"].sort(key=lambda d: d["date"])
    if daily_keep and len(stats["daily"]) > daily_keep:
        stats["daily"] = stats["daily"][-daily_keep:]

    stats["generated_at"] = now_utc(run_dt)
    stats["timer_period_min"] = TIMER_PERIOD_MIN
    return stats


def _day_row(index: dict, daily: list, date: str) -> dict:
    row = index.get(date)
    if row is None:
        row = {"date": date, "downloads": 0, "visits": 0}
        index[date] = row
        daily.append(row)
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
    stats_file = _cfg("AUSMT_STATS_FILE", str(Path(data_dir) / "gateway" / "state" / "stats.json"))
    try:
        daily_keep = int(_cfg("AUSMT_STATS_DAILY_KEEP", "90"))
    except ValueError:
        daily_keep = 90

    try:
        run_dt = _run_datetime()
        reverse_map = build_reverse_map(_load_json(manifest_path))
        geoip = GeoIP.load(dbip_csv)
        prev = _load_json(stats_file)
        lines = read_log_lines(log_dir)
        stats = aggregate(prev, lines, reverse_map, geoip, run_dt, daily_keep=daily_keep)
        dest_dir = Path(stats_file).parent
        if not dest_dir.is_dir():
            print(f"aggregate_stats: state dir {dest_dir} does not exist -- not writing stats.json "
                  f"(is the gateway state dir created?)", file=sys.stderr)
            return 0
        write_stats_atomic(stats_file, stats)
        print(f"aggregate_stats: folded up to {stats.get('last_folded_date')} -- "
              f"downloads={stats['totals']['downloads']} visits={stats['totals']['visits']} "
              f"manifest_rows={len(reverse_map)} geoip_rows={geoip.row_count} "
              f"log_lines={len(lines)} -> {stats_file}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 -- never raise into the timer; note loudly and exit 0
        print(f"aggregate_stats: aborted without writing ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
