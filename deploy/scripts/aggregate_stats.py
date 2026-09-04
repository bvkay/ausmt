#!/usr/bin/env python3
"""Usage-analytics aggregator.

A host-side, STDLIB-ONLY daily job (deploy/systemd/ausmt-stats.timer fires it) that folds the Caddy
access log into a cumulative `stats.json` the workbench Analytics screen reads. It is the same
trust class as alert.sh's ops-status writer: it NEVER raises into the timer (main catches
everything and exits 0), writes atomically (tmp -> chmod 0644 -> os.replace), and stamps the shared
UTC timestamp so the gateway's staleness clock parses it identically.

WHAT IT DOES, once a day:
  * reads the Caddy access-log file(s) under the logs volume: access.json plus any rolled sibling,
    plain (access*.json) or compressed (access*.json.gz). See read_log_lines for why the compressed
    arm exists even though the shipped Caddyfiles now roll uncompressed;
  * attributes each DOWNLOAD request (`/data/edi|xml|bundles/...`, plus a frozen release bundle under
    `/data/releases/<tag>/bundles/...`) to a survey/station/format via manifest.json's reverse map
    (url -> row). An unknown download path lands in an `unattributed` bucket, never dropped silently;
  * counts a download ONCE per (day, masked network, path) while summing the bytes of every line, so
    one user action that the log records twice is one download (see `aggregate` for the two shapes
    that produce it), and admits 206 as well as 200 so a ranged/resumed transfer is not invisible;
  * classifies the CLIENT three ways from the user-agent (crawler / scripted / browser): crawlers are
    excluded from every count as bots always were, scripted clients ARE counted and their share of
    downloads is reported, because curl/wget/python-requests are the clients the published API examples
    hand people. The UA is read transiently and never stored;
  * counts portal VISITS as `/data/catalogue.json` fetches (one per SPA boot — the only
    server-observable visit proxy);
  * counts API-CONSUMER requests as fetches of the four DOCUMENTED machine-readable entry points the
    portal SPA never fetches for itself (`/data/products/manifest.json`, `/data/mtcat.json`,
    `/data/mtcat.schema.json`, `/data/stations.geojson`). This is a PATH-CLASS signal only: nothing new
    is collected. It is an upper bound on programmatic use (a human can click the footer's mtcat link
    or the About page's GeoJSON link) and is reported as its own line, never folded into visits;
  * counts a TIME-SERIES HAND-OFF (`/go/ts/<survey>/<station>/<level>`, the front door's 302 into the
    NCI THREDDS archive) as its own class. It counts REQUESTS, never completed transfers: AusMT hands
    the reader off and never learns whether a byte moved, and every published string says so. The
    BYTES and the DESTINATION HOST are JOINED from the served, register-derived ts_access.json,
    because the log can supply neither -- the `size` on a 302 line is the redirect body and the
    Location header is never logged;
  * counts DISTINCT MASKED NETWORKS per day as a privacy-safe reach proxy. Caddy has already truncated
    the address to a /24 (v4) or /48 (v6) at the edge, so the distinct set IS a network count. The set
    lives in memory for the one run that folds a day and only its SIZE is written -- no address, masked
    or otherwise, is ever retained. Days folded before this existed carry no `networks` key at all
    (absent, not zero) and the screen renders them as unavailable;
  * resolves each request's MASKED client address (IPv4 /24, IPv6 /48 — already truncated at the
    edge by Caddy) to a country via the db-ip "IP to Country Lite" CSV using a stdlib
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
    re-runs never double-count;
  * credits a download to the COLLECTION its survey belongs to (the served mtcat.json's collection_id),
    so a programme-level figure needs no join at report time. Optional: no mtcat.json, no dimension;
  * APPENDS one line per newly folded day to a permanent archive beside stats.json, at the finest
    NON-GEOGRAPHIC granularity the fold sees. Nothing reads it and nothing serves it.

RETENTION (aggregates only -- the RAW log keeps its own untouched ~7-day Caddy rotation):
  * DAILY rows are a rolling window of AUSMT_STATS_DAILY_KEEP days (default 92, i.e. a quarter) ending
    at the fold watermark. Older daily rows are pruned.
  * MONTHLY rollup rows are kept INDEFINITELY. They are tiny pure-count records (no address, no path,
    no identity) and they are what makes year-over-year funding reporting possible. Each month is
    accumulated AS ITS DAYS FOLD, never recomputed from the daily tail, so pruning a day never loses
    the month it belonged to.
  * The DAILY ARCHIVE (daily_archive.jsonl) is kept INDEFINITELY too and is never pruned or rewritten.
    It is the answer to "the aggregates are all we keep, so keep enough of them": pure counts at day
    grain, with NO geography at any grain finer than the month. See the archive section below.

WHAT IT NEVER WRITES (the leak pin enforces it): an address (masked or not) and a
user-agent string never reach stats.json. Only aggregates leave the pipeline — counts + dailies.

Config (env; every path derives from AUSMT_DATA_DIR, each overridable for tests):
  AUSMT_DATA_DIR            (required) host root. Everything below defaults under it.
  AUSMT_STATS_LOG_DIR       Caddy access-log dir           [default $AUSMT_DATA_DIR/logs/caddy]
  AUSMT_STATS_MANIFEST      served download manifest       [default $AUSMT_DATA_DIR/site-data/current/manifest.json]
  AUSMT_STATS_DBIP_CSV      db-ip IP-to-Country Lite CSV   [default $AUSMT_DATA_DIR/geoip/dbip-country-lite.csv]
  AUSMT_STATS_AU_STATES_CSV compact AU state table         [default $AUSMT_DATA_DIR/geoip/dbip-au-states.csv]
                            (produced by deploy/scripts/prep_au_states.py; absent => country only)
  AUSMT_STATS_FILE          the cumulative stats.json      [default $AUSMT_DATA_DIR/gateway/state/stats.json]
  AUSMT_STATS_DAILY_ARCHIVE the append-only day archive    [default: daily_archive.jsonl beside stats.json]
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
import gzip
import ipaddress
import json
import os
import sys
import zlib
from pathlib import Path
from urllib.parse import urlsplit

# The daily aggregation cadence, in minutes — stamped into stats.json as the staleness clock the
# gateway reads (serve_state.ops_status_stale: stale past ~2 periods => ~2 days).
TIMER_PERIOD_MIN = 1440

# The stats.json schema version. v2 adds: per-survey volume, per-dataset volume, the station-file vs
# survey-bundle split, an API-consumer request class, per-day volume/format/kind/network detail, and the
# permanent monthly rollups. v1 files are UPGRADED IN PLACE by _coerce_prev (tolerant read, no migration
# script): every v1 field is carried forward, the new dimensions simply start accruing from the next fold.
#
# The AU state breakdown (`by_state`, cumulative and per calendar month) is an ADDITIVE v2 dimension
# and does NOT bump this number: like every other optional input in this file it is detected by KEY
# PRESENCE, never by version, and a v2 file written before it existed reads back cleanly with the maps
# empty. Bumping the version would gate nothing and would only invite a migration step that is not
# needed. That also covers the reverse case: a file folded by a build that briefly wrote a `states` map
# onto each DAY row reads back fine here -- the key is simply carried forward untouched and ages out
# with the 92-day daily window (see _count_geo for why no day-by-state cell is written any more).
SCHEMA_VERSION = 2

# The rolling window (in DAYS) of daily rows kept in stats.json. 92 days is one quarter, which is what
# the quarterly funding view needs. Monthly rollups are NOT subject to this -- they are kept forever.
DEFAULT_DAILY_KEEP_DAYS = 92

# The served download families (path prefixes under /data/) and the visit proxy. `h5` was excluded here
# for as long as `/data/h5/*` was a latent Caddy force-download matcher with NO producer.
# The engine produces per-station MTH5 files there, so
# the exclusion had to go with it. It is worth naming why the interlock matters: an excluded family
# classifies as `ignore`, and an ignored path is absent from `unattributed` as well, so every
# station-h5 download vanishes from the analytics rather than surfacing as build/serve skew.
# Silent absence, not undercounting. Pinned in deploy/tests/test_aggregate_stats.py.
_DOWNLOAD_FAMILIES = ("edi", "xml", "h5", "bundles")
_DATA_PREFIX = "/data/"
_VISIT_PATH = "/data/catalogue.json"

# The RELEASE tier. A cut release freezes the citable copy of each bundle under
# /data/releases/<tag>/bundles/<file>, and that frozen copy is the one a paper's DOI resolves to. It
# must NOT classify as `ignore`, or the archival download produces no analytics at all while its
# mutable twin under /data/bundles/ is counted: exactly the wrong way round for a custodian report.
# It is a download here, attributed by bundle FILENAME against the live manifest (see
# _release_bundle_row). The small release metadata documents (releases.json, release.json,
# datacite.json, mtcat.json under /data/releases/) stay UNCOUNTED for now: they are discovery reads
# rather than data downloads, and folding them into either the download or the API line would blur a
# figure that is already an upper bound.
_RELEASE_FAMILY = "releases"
_RELEASE_BUNDLE_SEGMENT = "bundles"

# The TIME-SERIES HAND-OFF namespace.
# /go/ts/<survey>/<station>/<level> is a front-door TERMINAL route: it answers 302 with the one NCI
# THREDDS fileServer URL for that file and never reaches this box, so the only trace it leaves is the
# front door's own masked log line, which is what this fold reads. Exactly three segments below the
# prefix; anything else is not a route the generated table can name and is not counted.
_HANDOFF_PREFIX = "/go/ts/"
_HANDOFF_SEGMENTS = 3
# The status a hand-off IS. A 302 is the whole event; a 404 on one of these paths is the route table
# declining to resolve (which is how suppression works) and is not a hand-off at all.
_HANDOFF_STATUS = 302

# The archive route the BUILD publishes, restated here because this file is stdlib-only and must not
# import the engine (engine/extract/_stationcheck.py TS_ACCESS_PREFIX is the source of truth; a pin in
# deploy/tests holds the two together, exactly as one holds the bulk flag to the portal's own token).
# It is what by_destination is keyed on: the host of the access_url the build emits for a row. That
# host's cardinality is 1 today, thredds.nci.org.au being the canonical route, which is precisely when
# a missing breakdown is cheap to add and expensive to add retroactively.
_TS_ACCESS_PREFIX = "https://thredds.nci.org.au/thredds/fileServer/"

# The licence sidecar build_portal writes beside every survey MTH5 (bundles/<slug>-tf.LICENSE.txt).
# It carries no manifest row, so every fetch of one landed in `unattributed` -- and `unattributed`
# exists to detect build/serve skew, a signal nineteen structural sidecars drown. Boilerplate that
# travels with the bytes is not a data download, so it is ignored here. Aggregator-side deliberately:
# the engine keeps writing the sidecar, because the rights instrument must ship beside the file.
_LICENCE_SIDECAR_SUFFIX = ".LICENSE.txt"

# The API-CONSUMER path class: the documented machine-readable entry points that the portal's OWN
# JavaScript never fetches, so a hit is a third party reading the corpus programmatically rather than a
# browser booting the SPA. Verified against the shipped portal tree, and the exclusions are the point:
#   * /data/catalogue.json, /data/surveys.json, /data/tf.json, /data/sci.json, /data/manifest.json,
#     /data/build.json, /data/collections.json, /data/coord_policy.json, /data/build_provenance.json
#     are all fetched by portal/src/data.js on every SPA boot -- they measure browsers, not consumers;
#   * /data/products/<slug>/<station>/station.json is fetched by portal/src/drawer.js when a station
#     drawer opens -- also a browser.
# What is left is the documents About points a programmatic reader at. mtcat.schema.json is the `$id`
# the MTCAT document declares (engine/schema/mtcat.schema.json), so every validator and every harvester
# that resolves the schema fetches it: the cleanest machine-consumer signal the corpus has, and the one
# That was counted nowhere. stations.geojson is the corpus as a vector layer:
# a GIS user adds it as a layer straight from the URL and the SPA never fetches it, so it belongs on
# this line for the same reason -- and without it every QGIS reader of the corpus would count nowhere,
# because a `.geojson` at the data root is in no download family and would fall through to `ignore`.
# This is a PATH CLASS, never a user-agent test, and it is an UPPER BOUND: the mtcat and GeoJSON links
# sit on public pages, so a human click lands here too. Reported as its own line, never merged into
# visits. The published word-count of this tuple is pinned in deploy/tests (deploy/README.md and
# docs/docs/introduction/usage-analytics.md both state it), so a fifth entry point cannot land silently.
_API_PATHS = ("/data/products/manifest.json", "/data/mtcat.json", "/data/mtcat.schema.json",
              "/data/stations.geojson")

# The products/ MIRROR of an entry point. Several top-level documents are served at TWO paths and
# docs/docs/reference/index.md publishes both: /data/mtcat.json beside /data/products/mtcat.json,
# /data/stations.geojson beside /data/products/stations.geojson. Only the root path was classified, so
# a reader who used the ADVERTISED mirror counted nowhere -- `products` is in no download family, so the
# mirror fell through to `ignore`, which is the very failure this path class exists to prevent. It bites
# hardest on the GeoJSON, the first of these documents pointed at external GIS consumers.
#
# DERIVED from _API_PATHS, never listed in it. A document is ONE entry point however many paths serve
# it, and the published word ("four documented machine-readable entry points") counts documents, not
# URLs; adding the mirrors to the tuple above would make that word wrong. The derivation is also what
# keeps a future fifth entry point's mirror covered without a second edit. It cannot reach the SPA's own
# fetches: products/<slug>/<station>/station.json is a browser fetch and is not derivable from any root
# path on the list.
_API_MIRROR_PREFIX = _DATA_PREFIX + "products/"
_API_MIRROR_PATHS = tuple(_API_MIRROR_PREFIX + p[len(_DATA_PREFIX):] for p in _API_PATHS
                          if not p.startswith(_API_MIRROR_PREFIX))

# The BULK-EXPORT LABEL. The portal's THREE selection exports over a map
# selection (portal/src/exports.js SEL_ZIP_BUTTONS: the EDI, EMTF XML and MTH5 zips) each mark every file
# fetch they issue with this exact query token. It is the ONE thing in this pipeline the portal
# deliberately puts INTO the log; everything else here is read from what the server was already writing.
# It is a label on a request that already happens: no additional request, no beacon, and nothing about
# who is asking.
#
# The token says an ARCHIVE WAS TAKEN, never which format was in it: a labelled fetch resolves to its own
# manifest row like any other. The bulk figure sums all three flows and nothing here cross-tabs the select
# class against format: by_format covers every download, labelled and unlabelled alike, so the two splits
# are independent totals. Reading the flag as an EDI-export counter (the shape it had when the EDI zip was
# the only flow writing it) would under-report the derived formats by exactly the amount they are used.
#
# It is read from the RAW request line, BEFORE the query strip that produces the attribution path (see
# parse_caddy_line), and it never touches that path. That is what keeps the within-day dedupe key the
# query-stripped path, so the same file fetched with and without the label is still ONE download.
#
# The drawer's single-station downloads carry no label, which is what makes an unlabelled fetch mean
# "single" rather than merely "unknown". Change this token and portal/src/exports.js must change with
# it; a pin in portal/tests holds the two together.
_SELECT_BULK_FLAG = "sel=bulk"
_SELECT_SINGLE = "single"
_SELECT_BULK = "bulk"

# CLIENT CLASSES (record "user-agent for bot filtering only" -- read transiently, NEVER stored).
# The old binary was bot-or-human, which put curl, wget and python-requests on the bot side. Those are
# the exact clients the public API documentation hands people, so scripted scientific use was invisible
# and the API-requests figure degenerated toward a footer-click counter. Three classes now:
#   * CRAWLER -- excluded from every count, as bots always were. Self-declaring indexers, previewers,
#     scanners and uptime probes;
#   * SCRIPTED -- COUNTED, and reported separately for downloads. A documented HTTP client, or NO
#     user-agent at all (a UA-less client is a script, never a person at a browser);
#   * BROWSER -- everything else.
# Substring match on the lower-cased UA, crawler tested first so a crawler that also names an HTTP
# library stays excluded. Kept small; aggregate reporting tolerates the margin.
_CRAWLER_TOKENS = ("bot", "spider", "crawl", "slurp", "bingpreview", "facebookexternalhit",
                   "headlesschrome", "monitoring", "uptime", "scrapy", "zgrab")
_SCRIPTED_TOKENS = ("curl/", "wget/", "python-requests", "python-urllib", "go-http-client", "okhttp",
                    "java/", "axios", "node-fetch", "libwww", "aria2", "apache-httpclient", "httpx")
CLIENT_CRAWLER = "crawler"
CLIENT_SCRIPTED = "scripted"
CLIENT_BROWSER = "browser"

# The append-only daily archive, written beside stats.json in the gateway state dir. See the archive
# section further down for what it holds and, more importantly, what it deliberately does not.
_ARCHIVE_FILENAME = "daily_archive.jsonl"


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
# Geo lookup: a stdlib bisect over a flat `start,end,VALUE` range CSV (record no maxminddb, no
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
    aggregator still completes (country pin). Ranges are stored per IP-version as parallel
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

    WHY STATE, AND WHY NOT CITY -- a design decision, recorded here so it is not casually
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
# Manifest reverse map: the download-URL -> dataset resolver (- manifest.json is the
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


def _served_survey_count(reverse_map: dict[str, dict]) -> int:
    """How many distinct surveys the SERVED manifest offers: the denominator for "N surveys
    downloaded".

    Counted from the `survey` label rather than the bundle `slug` on purpose. by_survey is keyed on the
    label, so counting labels makes numerator and denominator the same vocabulary from the same map;
    counting slugs would miss any survey whose rows are all files (a bundle row is where a slug lives),
    and could then render an absurd "3 of 2 served"."""
    return len({row.get("survey") for row in reverse_map.values() if row.get("survey")})


def _norm_url(url) -> str | None:
    if not isinstance(url, str) or not url:
        return None
    return url.replace("\\", "/").lstrip("/")


def build_collection_map(mtcat: dict | None, reverse_map: dict[str, dict]) -> dict[str, str]:
    """{survey label: collection_id} for the surveys the SERVED mtcat.json places in a collection, or
    {} when that document is absent, unreadable or names no collection.

    Keyed on the survey LABEL because every other per-survey map in this file is, so a collection
    total is exactly the sum of its members' rows and a reader can check it by eye.

    MTCAT names a survey twice: `survey_id` (the slug the manifest's bundle rows carry) and `title`
    (the label every manifest row carries). Both joins are built and the SLUG is preferred, because
    a slug is an identifier and a title is prose that can be re-worded between builds. A survey the
    document does not place in a collection simply has no entry: no bucket, no zero, exactly like the
    optional state table.

    Tier-3 collection bundles do not exist yet. When they do, they arrive as ordinary manifest bundle
    rows and flow through the download path already, so a collection-level artifact will be credited
    to whatever survey label its row carries; the latent case needs no handling here, only this note
    so it is recognised rather than rediscovered."""
    out: dict[str, str] = {}
    if not isinstance(mtcat, dict):
        return out
    by_slug: dict[str, str] = {}
    by_title: dict[str, str] = {}
    for row in mtcat.get("surveys") or []:
        if not isinstance(row, dict):
            continue
        cid = row.get("collection_id")
        if not isinstance(cid, str) or not cid:
            continue
        if isinstance(row.get("survey_id"), str) and row["survey_id"]:
            by_slug[row["survey_id"]] = cid
        if isinstance(row.get("title"), str) and row["title"]:
            by_title[row["title"]] = cid
    for row in reverse_map.values():
        survey = row.get("survey")
        if not isinstance(survey, str) or not survey:
            continue
        cid = by_slug.get(row.get("slug")) or by_title.get(survey)
        if cid:
            out[survey] = cid
    return out


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
    # The bulk-export label is read from the RAW uri, before the split below throws the query away. It
    # must be an exact whole parameter: a token merely mentioned inside another value (`?ref=sel=bulk`)
    # is not the portal's label and must not be read as one.
    bulk = any(part == _SELECT_BULK_FLAG
               for part in uri.split("?", 1)[1].split("&")) if "?" in uri else False
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
            "status": status, "size": size, "address": address, "ua": ua, "bulk": bulk}


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


def classify_client(ua: str) -> str:
    """CLIENT_CRAWLER / CLIENT_SCRIPTED / CLIENT_BROWSER for a user-agent string, read transiently and
    never stored. An EMPTY or absent UA is SCRIPTED: a client that declares nothing is a script, and
    treating it as a person was the old filter's other blind spot."""
    u = (ua or "").strip().lower()
    if not u:
        return CLIENT_SCRIPTED
    if any(tok in u for tok in _CRAWLER_TOKENS):
        return CLIENT_CRAWLER
    if any(tok in u for tok in _SCRIPTED_TOKENS):
        return CLIENT_SCRIPTED
    return CLIENT_BROWSER


def _is_licence_sidecar(rel: str) -> bool:
    """True for a `.../bundles/<name>.LICENSE.txt` sidecar: the rights instrument written beside a
    bundle, in the live tree or a frozen release. Not a data download (see _LICENCE_SIDECAR_SUFFIX)."""
    parts = rel.split("/")
    return (len(parts) >= 2 and parts[-2] == _RELEASE_BUNDLE_SEGMENT
            and parts[-1].endswith(_LICENCE_SIDECAR_SUFFIX))


def classify(path: str) -> tuple[str, str | None]:
    """(kind, rel) for a request path: ('visit', None) for the catalogue fetch; ('api', None) for one of
    the documented machine-readable entry points the SPA never fetches itself; ('download', rel) for a
    `/data/edi|xml|bundles/...` or `/data/releases/<tag>/bundles/<file>` path where rel is the path
    below /data/; ('handoff', rel) for a `/go/ts/<survey>/<station>/<level>` archive hand-off where rel
    is the three-segment route below the prefix; ('ignore', None) otherwise.

    The classes are MUTUALLY EXCLUSIVE by construction (the visit path, the four API entry points with
    their products/ mirrors, the download families, the release-bundle shape and the /go/ts/ namespace
    are disjoint), so no request is ever counted twice."""
    if path == _VISIT_PATH:
        return "visit", None
    if path in _API_PATHS or path in _API_MIRROR_PATHS:
        return "api", None
    if path.startswith(_DATA_PREFIX):
        rel = path[len(_DATA_PREFIX):]
        if _is_licence_sidecar(rel):
            return "ignore", None
        family = rel.split("/", 1)[0]
        if family in _DOWNLOAD_FAMILIES and "/" in rel:
            return "download", rel
        # releases/<tag>/bundles/<file> -- the frozen citable copy. Exactly four segments: the release
        # metadata documents beside it (releases.json, release.json, datacite.json, mtcat.json) and the
        # bare directory listing all fall short of that shape and stay ignored.
        parts = rel.split("/")
        if (family == _RELEASE_FAMILY and len(parts) == 4
                and parts[2] == _RELEASE_BUNDLE_SEGMENT and parts[3]):
            return "download", rel
    # The archive hand-off. The route SHAPE is the whole test here: the survey, station and level a
    # generated table can name, and nothing shorter or longer. A bare prefix or a probe below one
    # therefore stays `ignore`, and no path this classifier admits can be anything but a route the
    # front door had to resolve to answer at all.
    if path.startswith(_HANDOFF_PREFIX):
        rel = path[len(_HANDOFF_PREFIX):]
        parts = rel.split("/")
        if len(parts) == _HANDOFF_SEGMENTS and all(parts):
            return "handoff", rel
    return "ignore", None


def _release_bundle_row(reverse_map: dict[str, dict], rel: str) -> dict | None:
    """The manifest row for a `releases/<tag>/bundles/<file>` path, matched by bundle FILENAME against
    the LIVE manifest, or None when the filename is not one the current build ships.

    A release freezes bytes under a tag-scoped url the manifest never carries, so the ordinary
    reverse-map lookup always misses. The filename is the stable identity across the freeze (cut_release
    copies the bundle verbatim), which makes it the right join key. A no-match falls through to the
    existing `unattributed` bucket exactly like any other unknown download path -- a withdrawn or
    renamed survey therefore shows up as skew rather than being silently dropped. The frozen copy keeps
    its OWN by_dataset key, so a release's usage stays distinguishable from the live copy's."""
    parts = rel.split("/")
    if len(parts) != 4 or parts[0] != _RELEASE_FAMILY or parts[2] != _RELEASE_BUNDLE_SEGMENT:
        return None
    return reverse_map.get(f"{_RELEASE_BUNDLE_SEGMENT}/{parts[3]}")


def _handoff_row(ts_access: dict, rel: str) -> dict | None:
    """The served ts_access.json entry ({bytes, url_path}) for a `<survey>/<station>/<level>` route, or
    None when the served index does not publish it.

    THE KEY IS BUILT FROM THE PATH, exactly as _release_bundle_row builds its bundle filename, and for
    the same reason: the log carries the route and the joinable identity has to be derived from it. An
    ausmt_id is `au.<survey slug>.<station id>` and both segments are already the safe shape
    build_portal.safe_component emits (gen_ts_routes.py refuses a register key that is not), so the
    three route segments name the row without ever splitting an id on its dots -- which is the
    direction that would be ambiguous.

    A no-match is DRIFT, not a crash: the table lives on the front door and the data on the box, so a
    302 can arrive for a route the served index does not publish. It is counted in the hand-off
    family's own unattributed bucket, exactly as an unknown download path is counted in that family's,
    and never dropped."""
    if not isinstance(ts_access, dict):
        return None
    parts = rel.split("/")
    if len(parts) != _HANDOFF_SEGMENTS:
        return None
    levels = ts_access.get(f"au.{parts[0]}.{parts[1]}")
    entry = levels.get(parts[2]) if isinstance(levels, dict) else None
    return entry if isinstance(entry, dict) else None


def _handoff_destination(url_path) -> str:
    """The DESTINATION HOST of one hand-off: the host of the access_url the build emits for this row
    (_TS_ACCESS_PREFIX + the register's url_path). Taken from the emitted URL rather than from the
    request, because the request never names it -- the Location header is not logged.

    The row's own path can never move the host: a leading slash is stripped, so a url_path is always
    joined BELOW the prefix and cannot present itself as an authority."""
    host = urlsplit(_TS_ACCESS_PREFIX + str(url_path or "").lstrip("/")).netloc
    return host or "unknown"


# --------------------------------------------------------------------------------------------------
# The fold. `aggregate` is a PURE function (prev_stats + log lines + reverse map + geoip + run date ->
# new_stats) so the pins can drive it deterministically without touching the filesystem or a timer.
# --------------------------------------------------------------------------------------------------
def _empty_stats() -> dict:
    return {"schema": SCHEMA_VERSION, "timer_period_min": TIMER_PERIOD_MIN, "generated_at": None,
            "since": None, "last_folded_date": None, "detail_since": None, "select_since": None,
            "totals": {"downloads": 0, "visits": 0, "download_bytes": 0, "unattributed": 0,
                       "api_requests": 0, "downloads_by_client": {},
                       "downloads_by_select": _empty_select(), "bulk_export_events": 0},
            "downloads": {"by_format": {}, "by_survey": {}, "by_dataset": {}, "by_kind": {}},
            "handoffs": _empty_handoffs(geo=True),
            "total_served_surveys": 0, "by_collection": {},
            "countries": {}, "by_country_detail": {}, "by_state": {}, "by_state_detail": {},
            "daily": [], "monthly": []}


# One row of a per-PLACE DETAIL map: what a place actually did, not merely how many requests it made.
# TWO maps share this shape, one per geographic grain:
#   * `by_country_detail`, beneath the combined `countries` map;
#   * `by_state_detail`, beneath the combined `by_state` map.
# The two COMBINED maps are untouched by either, because the screen's AU reconciliation rows and their
# exact-total promise are built on them and that promise is load-bearing. The detail maps sit BESIDE
# them and answer the question a funding report and a custodian conversation actually ask.
_CLASS_METRICS = ("downloads", "visits", "api")


def _empty_class_detail() -> dict:
    return {"downloads": 0, "visits": 0, "api": 0, "bytes": 0}


def _empty_handoffs(*, geo: bool = False) -> dict:
    """One TIME-SERIES HAND-OFF block. The same shape at every grain, which is what lets the cumulative
    figure, the month, the day row and the archive line be read against each other.

    `requests` is the count and the word is exact: a hand-off is a 302 into the NCI archive, so this
    counts what was ASKED FOR and can never count what was transferred. `bytes` is the register's size
    for the file each request was handed, never a measurement of anything served.

    `by_survey` is keyed on the survey SLUG, the segment the route itself carries, and deliberately not
    on the display label the download family uses: the route is a published URL contract, a slug is an
    identifier, and a title is prose that can be re-worded between builds (the same argument
    build_collection_map makes when it prefers the slug).

    `geo` adds the by-country map, and it is added at the CUMULATIVE and CALENDAR-MONTH grains ONLY.
    That is the one line that must not move (see _count_geo): a named country on a named day is a
    smaller cell than the named-state-in-a-named-month the small-cell rule excludes, so no day row and
    no archive line carries one."""
    out = {"requests": 0, "bytes": 0, "unattributed": 0,
           "by_survey": {}, "by_level": {}, "by_destination": {}}
    if geo:
        out["countries"] = {}
    return out


def _coerce_handoff_map(raw) -> dict[str, dict]:
    """A {key: {requests, bytes}} hand-off map from a prior file: the shape by_survey, by_level and
    by_destination share. Absent reads back empty and starts accruing, like every additive dimension
    in this file."""
    out: dict[str, dict] = {}
    if not isinstance(raw, dict):
        return out
    for key, val in raw.items():
        if not isinstance(key, str) or not isinstance(val, dict):
            continue
        out[key] = {"requests": _as_int(val.get("requests")), "bytes": _as_int(val.get("bytes"))}
    return out


def _coerce_handoffs(raw, *, geo: bool = False) -> dict:
    """A hand-off block from a prior file, clamped to the keys this fold writes so a hand-edited file
    cannot push an arbitrary column onto the screen. Tolerant of absence: the class is detected by KEY
    PRESENCE, never by a version bump (see SCHEMA_VERSION)."""
    out = _empty_handoffs(geo=geo)
    if not isinstance(raw, dict):
        return out
    for key in ("requests", "bytes", "unattributed"):
        out[key] = _as_int(raw.get(key))
    for key in ("by_survey", "by_level", "by_destination"):
        out[key] = _coerce_handoff_map(raw.get(key))
    if geo and isinstance(raw.get("countries"), dict):
        out["countries"] = {str(k): _as_int(v) for k, v in raw["countries"].items()}
    return out


def _empty_select() -> dict:
    """The bulk/single download split, DENSE at the cumulative and month grains: once a month has folded
    a day under these rules, `bulk: 0` is a real measurement of that month and must render as one. The
    ARCHIVE's copy is sparse instead, like every other map on an archive line."""
    return {_SELECT_SINGLE: 0, _SELECT_BULK: 0}


def _coerce_select(raw) -> dict:
    """A downloads_by_select map from a prior file, clamped to the two known classes and tolerant of
    absence (an ADDITIVE dimension detected by key presence, like every other on this file)."""
    return ({_SELECT_SINGLE: _as_int(raw.get(_SELECT_SINGLE)), _SELECT_BULK: _as_int(raw.get(_SELECT_BULK))}
            if isinstance(raw, dict) else _empty_select())


def _empty_month(month: str) -> dict:
    """One calendar-month rollup row. `days` counts the distinct dates with counted activity folded into
    it; `seeded_days` records how many of those came from a pre-upgrade daily row (downloads + visits
    only), so the screen can say which months carry partial detail instead of implying a real zero;
    `geo_days` counts the days that actually contributed a country, which is what makes the forward-only
    country seam MACHINE-visible rather than a matter of reading the prose beside the table;
    `networks_peak` is the largest distinct-network count any of its folded days saw. That figure used
    to live on daily rows ONLY, so it expired with the 92-day window and could never reach a quarterly
    report, which is exactly the horizon a funding report asks about. It accumulates as each day folds
    and is never recomputed from a tail that is about to be pruned.

    `detail_days` counts the days folded with THIS fold's dimensions in place, and it exists because
    there are TWO forward-only seams in this file rather than one. `seeded_days` marks the first
    (days carried over from a v1 daily tail). A month folded after that upgrade and before the client
    split, the network peak, the per-survey country list and the within-day download dedupe existed
    sits between the two: it carries a real volume and a real format split beside NONE of those. With
    no such counter the screen cannot tell that month from one that measured them and saw zero, and a
    fabricated 0 is exactly what the omit-rather-than-fabricate rule refuses."""
    return {"month": month, "downloads": 0, "visits": 0, "download_bytes": 0, "unattributed": 0,
            "api_requests": 0, "days": 0, "seeded_days": 0, "geo_days": 0, "detail_days": 0,
            "networks_peak": 0,
            "bulk_export_events": 0,
            "formats": {}, "kinds": {}, "surveys": {}, "countries": {}, "by_country_detail": {},
            "by_state": {}, "by_state_detail": {}, "downloads_by_client": {},
            "downloads_by_select": _empty_select(), "by_collection": {},
            "handoffs": _empty_handoffs(geo=True)}


def _as_int(v, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _next_day(date_str) -> str | None:
    """The ISO day after `date_str`, or None if it is not an ISO date. It stamps `detail_since` when
    a v1 file is upgraded: the richer dimensions begin the day AFTER that file's fold watermark."""
    if not isinstance(date_str, str):
        return None
    try:
        return (dt.date.fromisoformat(date_str) + dt.timedelta(days=1)).isoformat()
    except ValueError:
        return None


def _coerce_survey_map(raw) -> dict[str, dict]:
    """The by_survey map, tolerant of ALL FOUR shapes it has had: v1 `{survey: count}`, v2
    `{survey: {downloads, bytes}}`, then `{..., countries}`, and now `{..., files, bundles}`. A v1 int
    upgrades to {downloads: n, bytes: 0} -- the historical per-survey VOLUME was never recorded and is
    NOT invented; `detail_since` tells the screen from when the bytes column is real, so it can say so
    rather than show a silent undercount. The same applies to the country list: an older row reads back
    empty and starts accruing, and no country is invented for a download folded before it existed.

    The country list is the custodian promise ("downloaded N times from M countries") made derivable.
    It is stored at COUNTRY grain and nothing finer, and only its COUNT is ever rendered.

    `files` / `bundles` split a survey's own downloads the way `by_kind` splits the global figure: was
    this survey pulled station by station, or taken whole. An older row reads back with BOTH at zero
    beside a real download count, which is exactly what lets the screen distinguish "not measured" from
    "measured and none": a fully measured row has files + bundles == downloads, and a row that predates
    the split has files + bundles == 0. Nothing is apportioned after the fact."""
    out: dict[str, dict] = {}
    if not isinstance(raw, dict):
        return out
    for name, val in raw.items():
        if not isinstance(name, str):
            continue
        if isinstance(val, dict):
            codes = val.get("countries")
            out[name] = {"downloads": _as_int(val.get("downloads")), "bytes": _as_int(val.get("bytes")),
                         "countries": sorted({str(c) for c in codes if isinstance(c, str) and c})
                         if isinstance(codes, list) else [],
                         "files": _as_int(val.get("files")), "bundles": _as_int(val.get("bundles"))}
        else:
            out[name] = {"downloads": _as_int(val), "bytes": 0, "countries": [],
                         "files": 0, "bundles": 0}
    return out


def _coerce_volume_map(raw) -> dict[str, dict]:
    """A {key: {downloads, bytes}} map from a prior file: the shape the collection rollup uses, and
    the shape the daily archive writes for surveys and collections. Absent (a file written before the
    dimension existed) reads back empty and starts accruing, like every other additive dimension."""
    out: dict[str, dict] = {}
    if not isinstance(raw, dict):
        return out
    for key, val in raw.items():
        if not isinstance(key, str) or not isinstance(val, dict):
            continue
        out[key] = {"downloads": _as_int(val.get("downloads")), "bytes": _as_int(val.get("bytes"))}
    return out


def _coerce_class_detail(raw) -> dict[str, dict]:
    """A by_country_detail / by_state_detail map from a prior file, tolerant of absence (both are
    ADDITIVE dimensions detected by key presence, like by_state itself). A row is clamped to the four
    known metrics so a hand-edited file cannot push an arbitrary column onto the screen."""
    out: dict[str, dict] = {}
    if not isinstance(raw, dict):
        return out
    for code, row in raw.items():
        if not isinstance(code, str) or not isinstance(row, dict):
            continue
        out[code] = {"downloads": _as_int(row.get("downloads")), "visits": _as_int(row.get("visits")),
                     "api": _as_int(row.get("api")), "bytes": _as_int(row.get("bytes"))}
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
                  "days", "seeded_days", "geo_days", "detail_days", "networks_peak",
                  "bulk_export_events"):
            m[k] = _as_int(row.get(k))
        m["downloads_by_select"] = _coerce_select(row.get("downloads_by_select"))
        for k in ("formats", "kinds", "countries", "by_state", "downloads_by_client"):
            if isinstance(row.get(k), dict):
                m[k] = {str(kk): _as_int(vv) for kk, vv in row[k].items()}
        m["by_country_detail"] = _coerce_class_detail(row.get("by_country_detail"))
        m["by_state_detail"] = _coerce_class_detail(row.get("by_state_detail"))
        m["by_collection"] = _coerce_volume_map(row.get("by_collection"))
        m["surveys"] = _coerce_survey_map(row.get("surveys"))
        # The hand-off block is the one dimension here carried by KEY PRESENCE rather than by value: a
        # month folded before the class existed keeps NO such key, so the screen renders "not measured"
        # for it instead of a zero nobody measured. A month this fold touches starts dense from
        # _empty_month above and accrues from there.
        if isinstance(row.get("handoffs"), dict):
            m["handoffs"] = _coerce_handoffs(row["handoffs"], geo=True)
        else:
            m.pop("handoffs", None)
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
        # The browser/scripted split is an ADDITIVE dimension detected by key presence, like by_state.
        # A file written before it existed simply starts empty: its historical downloads stay in the
        # headline total and are NOT divided between the two classes, because nothing recorded which
        # they were and the raw logs that could say have long since rotated away.
        if isinstance(pt.get("downloads_by_client"), dict):
            s["totals"]["downloads_by_client"] = {str(k): _as_int(v)
                                                  for k, v in pt["downloads_by_client"].items()}
        s["totals"]["downloads_by_select"] = _coerce_select(pt.get("downloads_by_select"))
    # The bulk/single split is the one dimension here whose start date IS recorded. `detail_since` marks
    # the v1 hinge and the dimensions after it were left undated on purpose (the fold that added them is
    # written nowhere), but this one is stamped as it begins, so the screen can NAME the day instead of
    # declining to. Stamped ONCE: a prior file that already carries the stamp keeps it, and a prior file
    # that already carries the surface without a stamp is left unclaimed rather than given a date later
    # than the truth. Absent both (an older file), it is the day after that file's fold watermark, which
    # is the first day this build could have counted.
    if isinstance(prev.get("select_since"), str):
        s["select_since"] = prev["select_since"]
    elif not isinstance(pt, dict) or "downloads_by_select" not in pt:
        s["select_since"] = _next_day(s["last_folded_date"])
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
    # such key and starts empty: state counts are FORWARD-ONLY and no earlier month is ever backfilled
    # (that would need raw logs that have long since rotated away).
    if isinstance(prev.get("by_state"), dict):
        s["by_state"] = {str(k): _as_int(v) for k, v in prev["by_state"].items()}
    # The per-country and per-state DETAIL maps ride the same additive, key-presence rule: a file
    # written before either existed starts empty and no earlier month is given a detail row it never
    # measured. So does the collection rollup, which is younger again: it starts at the fold that could
    # first read a served mtcat.json, and no earlier download is credited to a collection after the fact.
    s["by_country_detail"] = _coerce_class_detail(prev.get("by_country_detail"))
    s["by_state_detail"] = _coerce_class_detail(prev.get("by_state_detail"))
    s["by_collection"] = _coerce_volume_map(prev.get("by_collection"))
    # The hand-off family, youngest of the lot and additive like every one before it: a file written
    # before the /go/ts routes existed reads back with the block empty and starts accruing. Nothing is
    # back-filled -- those days hold no hand-off because there was no route to request.
    s["handoffs"] = _coerce_handoffs(prev.get("handoffs"), geo=True)
    # Day rows are carried forward WHOLE, unknown keys and all. A row written by a build that briefly
    # recorded a per-day `states` map keeps it and simply ages out of the 92-day window; it is not
    # stripped, because rewriting history on upgrade is the one thing this file never does.
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
              au_states: "AuStates | None" = None, collections: dict[str, str] | None = None,
              served_build: str | None = None, archive_out: list | None = None,
              ts_access: dict | None = None) -> dict:
    """Fold every COMPLETE day in `lines` into `prev`, returning the new cumulative stats dict.

    Only dates d with last_folded_date < d < run_dt.date are folded (a strictly-earlier complete
    day), so the CURRENT (partial) day is never counted and re-runs never double-count. `run_dt.date`
    becomes the new last_folded_date, so a day rotated away before it could be folded is simply skipped
    (record losing a raw log loses nothing already folded, and nothing not-yet-folded is re-read).

    Each counted request lands in THREE places at once: the cumulative totals, its day row, and its
    calendar-month rollup. Accumulating the month AS THE DAY FOLDS (rather than summing the daily tail
    later) is what lets the daily window be pruned to `daily_keep` days while the monthly history stays
    complete and permanent.

    ADMISSION, and what each rule is protecting:
      * CRAWLERS are excluded and SCRIPTED clients are counted (see classify_client). A download's
        client class is also recorded, so the scripted share is reportable rather than merely admitted;
      * a DOWNLOAD admits 200 and 206. Caddy's file_server advertises byte ranges and the MTH5 bundles
        are the largest artifacts served, so 200-only made every resumed or ranged transfer vanish;
      * a HAND-OFF admits 302 and nothing else, because the 302 IS the event. It is NOT de-duplicated,
        and that is the mirror of the download rule rather than an exception to it: the dedupe exists
        because ONE download action logs two lines here (the renderer cancels, the download manager
        refetches) and a ranged transfer logs one per fragment. A hand-off is terminal at the front
        door, so one action logs exactly one line and every line is another request;
      * within ONE folded day an identical (masked network, path) counts ONCE toward the download COUNT
        while every line's BYTES still sum. One user action logs two lines on a Content-Disposition
        path (the renderer cancels, the download manager refetches) and a ranged transfer logs one line
        per fragment; counting each line was a straight double count of the headline figure. Visits and
        API requests are NOT deduped: each SPA boot and each API fetch really is another use.
      The dedupe set is run-local exactly like `networks_seen`: it is built FROM the masked network and
      nothing derived from an address is ever written.

    `au_states` is the OPTIONAL AU state table. When it is present, a request that classifies as AU also
    lands in a state bucket -- cumulatively and in its calendar month, never on the day row; when it is
    absent the fold is country-only and writes no state buckets at all: absent, never a zero (see
    AuStates for why state and not city, and _count_geo for why not by day).

    `collections` is the OPTIONAL {survey label: collection_id} map from the served mtcat.json
    (build_collection_map). Present, a download to a member survey also bumps its collection at the
    cumulative and month grains; absent, no collection dimension is written for that run.

    `ts_access` is the OPTIONAL served hand-off index ({ausmt_id: {level: {bytes, url_path}}}, written
    by the build from the verified-resource registers). It is the ONLY source of a hand-off's bytes and
    destination host, because the log carries neither. Absent, hand-offs are still counted as requests
    and land in their own unattributed bucket: a route count with no size is honest, an invented size
    would not be.

    `archive_out`, when given, receives ONE dict per day this call actually folded: the day at maximal
    NON-GEO granularity, for the append-only archive (see _archive_line). It is an out channel and not
    a second return value, so every existing caller keeps its signature; `aggregate` stays a function
    of its inputs and simply hands the caller the rows it built. `served_build` is stamped onto those
    rows when the served tree names itself."""
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
    by_country_detail = stats["by_country_detail"]
    by_state = stats["by_state"]
    by_state_detail = stats["by_state_detail"]
    by_collection = stats["by_collection"]
    handoffs = stats["handoffs"]
    collections = collections or {}
    ts_access = ts_access or {}
    daily_index = {d["date"]: d for d in stats["daily"]}
    month_index = {m["month"]: m for m in stats["monthly"]}
    # date -> set of MASKED networks seen on it, for THIS run only. Caddy already truncated the address
    # to a /24 (v4) or /48 (v6), so the distinct set is a network count. Only its SIZE is ever written;
    # the sets die with the process. A day folds exactly once, so one run sees all of that day's lines.
    networks_seen: dict[str, set] = {}
    # date -> {(masked network, download path): 'single'|'bulk'} already counted on it, for THIS run
    # only. This is the within-day download dedupe; like networks_seen it is built from the masked
    # address the edge already wrote, it is never written anywhere, and it dies with the process. The
    # VALUE is which class the one counted download currently sits in, so a later request for the same
    # file that carries the bulk label can move it rather than add a second download.
    downloads_seen: dict[str, dict] = {}
    # date -> set of MASKED networks that took at least one BULK-labelled download on it, for THIS run
    # only, and with exactly the lifecycle of networks_seen above: only the SIZE is ever written, the
    # set dies with the process, and nothing per-network is persisted. Its size is the export-EVENT
    # proxy: one export fetches many files, so counting flagged downloads would count files.
    bulk_networks_seen: dict[str, set] = {}
    # date -> month, for the "distinct active days per month" counter (a day counts once per month even
    # though it contributes many requests).
    days_seen: dict[str, str] = {}
    # date -> month, for the per-month count of days that actually contributed a country. Country
    # counting is forward-only, so a month can carry a full download figure beside one day of geo; this
    # is what lets the export state that rather than look self-consistent while under-reporting.
    geo_days_seen: dict[str, str] = {}
    # date -> the ARCHIVE row for that day, built only for the days THIS call folds. The daily rows in
    # stats.json are a 92-day window that the render path reads; these are the permanent, never-read
    # record, so they carry the finer per-survey / per-dataset / per-collection detail that has no
    # place on a rendered day row. Geography is deliberately absent from them (see _archive_line).
    archive_index: dict[str, dict] = {}

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
        client = classify_client(rec["ua"])
        if client == CLIENT_CRAWLER:
            continue
        kind, rel = classify(rec["path"])
        if kind == "ignore":
            continue
        if kind in ("visit", "api"):
            if rec["status"] not in (200, 304):
                continue
        elif kind == "handoff":
            if rec["status"] != _HANDOFF_STATUS:  # the 302 IS the hand-off; a 404 is the table refusing
                continue
        elif rec["status"] not in (200, 206):   # download: a complete OR a ranged/resumed transfer
            continue
        day = _day_row(daily_index, stats["daily"], date)
        month = _month_row(month_index, stats["monthly"], date[:7])
        arc = _archive_day(archive_index, date)
        days_seen[date] = date[:7]
        _note_network(networks_seen, date, rec["address"])

        if kind == "visit":
            totals["visits"] += 1
            day["visits"] += 1
            month["visits"] += 1
            arc["visits"] += 1
            _count_geo(geoip, au_states, rec["address"], countries, by_country_detail, by_state,
                       by_state_detail, month, metric="visits")
            geo_days_seen[date] = date[:7]
        elif kind == "api":
            totals["api_requests"] += 1
            day["api_requests"] = _as_int(day.get("api_requests")) + 1
            month["api_requests"] += 1
            arc["api"] += 1
            # The API line is a counted class WITH geography: leaving it out makes any reach claim
            # built from the country table silently exclude programmatic consumers.
            _count_geo(geoip, au_states, rec["address"], countries, by_country_detail, by_state,
                       by_state_detail, month, metric="api")
            geo_days_seen[date] = date[:7]
        elif kind == "handoff":
            # THE HAND-OFF, and the join is the whole of it. The log line says WHICH route
            # was asked for and nothing else that matters: its `size` is the redirect body and the
            # Location it sent is not logged at all. So the size and the destination host come from the
            # served, register-derived index, and a route that index does not publish is drift -- one
            # request, no bytes, no survey and no level, in this family's own unattributed bucket.
            entry = _handoff_row(ts_access, rel)
            size = max(_as_int(entry.get("bytes")), 0) if entry else 0
            survey, _station, level = rel.split("/")
            destination = _handoff_destination(entry.get("url_path")) if entry else None
            for block in (handoffs,
                          month.setdefault("handoffs", _empty_handoffs(geo=True)),
                          day.setdefault("handoffs", _empty_handoffs()),
                          arc["handoffs"]):
                block["requests"] += 1
                block["bytes"] += size
                if entry is None:
                    block["unattributed"] += 1
                    continue
                _bump_handoff(block["by_survey"], survey, size)
                _bump_handoff(block["by_level"], level, size)
                _bump_handoff(block["by_destination"], destination, size)
                if "by_route" in block:      # the archive's station-grain cell, and only there
                    _bump_handoff(block["by_route"], rel, size)
            # Geography, at the CUMULATIVE and CALENDAR-MONTH grains and nowhere finer. It is this
            # family's OWN country map: the combined `countries` map is what the AU state rows
            # reconcile against and what the screen's caption scopes to downloads, visits and API
            # requests, so a fourth class must not silently join that arithmetic.
            cc = geoip.country(rec["address"])
            _bump(handoffs["countries"], cc)
            _bump(month["handoffs"]["countries"], cc)
        else:
            size = max(rec["size"], 0)
            # WITHIN-DAY DEDUPE. The bytes of every admitted line sum (so an abort+refetch pair and a
            # set of range fragments both add up to roughly the real volume), but the COUNT increments
            # only the first time this network fetched this path today.
            dedupe_key = (rec["address"] or "", rel)
            seen_today = downloads_seen.setdefault(date, {})
            counted = dedupe_key not in seen_today
            n = 1 if counted else 0
            totals["downloads"] += n
            totals["download_bytes"] += size
            arc["downloads"] += n
            arc["download_bytes"] += size
            # THE BULK/SINGLE SPLIT. A download is bulk if ANY of that day's requests for it carried the
            # portal's label, which is why the class has to be revisable: one save action logs the
            # request twice and a ranged transfer once per fragment, so the labelled leg can arrive
            # after the one that was counted. On that arrival the download MOVES between the two
            # classes; it is never counted a second time, and the headline figure never moves.
            select = _SELECT_BULK if rec["bulk"] else _SELECT_SINGLE
            if counted:
                seen_today[dedupe_key] = select
                _bump(totals["downloads_by_select"], select)
                _bump(month["downloads_by_select"], select)
                _bump(arc["by_select"], select)
            elif select == _SELECT_BULK and seen_today.get(dedupe_key) == _SELECT_SINGLE:
                seen_today[dedupe_key] = _SELECT_BULK
                for counter in (totals["downloads_by_select"], month["downloads_by_select"],
                                arc["by_select"]):
                    _reclassify_select(counter)
            if rec["bulk"]:
                _note_network(bulk_networks_seen, date, rec["address"])
            if counted:
                _bump(totals["downloads_by_client"], client)
                _bump(month["downloads_by_client"], client)
                _bump(arc["by_client"], client)
            row = reverse_map.get(rel) or _release_bundle_row(reverse_map, rel)
            if row is None:
                totals["unattributed"] += n
                month["unattributed"] += n
                arc["unattributed"] += n
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
                                       "downloads": n, "bytes": size}
                else:
                    d["downloads"] = _as_int(d.get("downloads")) + n
                    d["bytes"] = _as_int(d.get("bytes")) + size
                # The archive's own per-dataset row: sparse (only the datasets this day touched) and
                # attributed only, exactly like the cumulative map above it.
                a = arc["by_dataset"].get(rel)
                if a is None:
                    arc["by_dataset"][rel] = {"downloads": n, "bytes": size, "format": fmt,
                                              "survey": survey}
                else:
                    a["downloads"] += n
                    a["bytes"] += size
            if counted:
                by_format[fmt] = by_format.get(fmt, 0) + 1
                by_kind[kind_key] = by_kind.get(kind_key, 0) + 1
                _bump(day.setdefault("formats", {}), fmt)
                _bump(day.setdefault("kinds", {}), kind_key)
                _bump(month["formats"], fmt)
                _bump(month["kinds"], kind_key)
                _bump(arc["by_format"], fmt)
                _bump(arc["by_kind"], kind_key)
            day["downloads"] += n
            day["download_bytes"] = _as_int(day.get("download_bytes")) + size
            month["downloads"] += n
            month["download_bytes"] += size
            cc = geoip.country(rec["address"])
            if survey:
                _bump_survey(by_survey, survey, size, counted=counted, country=cc, kind=kind_key)
                _bump_survey(month["surveys"], survey, size, counted=counted, country=cc,
                             kind=kind_key)
                # The archive's per-survey row takes the SPLIT too (it is a day fact with no geography
                # in it), so once the 92-day window has dropped the day, "file by file or taken whole"
                # is still answerable for it. The collection rows below take no split: a collection is
                # a programme rollup, and the manifest kind belongs to the artifact, not the programme.
                _bump_volume(arc["by_survey"], survey, size, counted=counted, kind=kind_key)
                # The COLLECTION rollup: the same download credited to the programme its survey
                # belongs to, so "how much did AusLAMP move" needs no join against mtcat.json at
                # report time. Keyed and counted exactly like the survey above it, so a collection
                # total is the sum of its members and nothing else.
                cid = collections.get(survey)
                if cid:
                    _bump_volume(by_collection, cid, size, counted=counted)
                    _bump_volume(month["by_collection"], cid, size, counted=counted)
                    _bump_volume(arc["by_collection"], cid, size, counted=counted)
            # Geography follows the COUNT, not the line, so `sum(countries.values())` stays exactly
            # downloads + visits + API requests and the table caption can say so and be true.
            if counted:
                _count_geo(geoip, au_states, rec["address"], countries, by_country_detail, by_state,
                           by_state_detail, month, metric="downloads", size=size)
                geo_days_seen[date] = date[:7]

    # Distinct-network counts for the days folded in THIS run. Only the SIZE of each set is written --
    # the masked addresses themselves never leave memory. The month keeps the PEAK of
    # those counts, so the reach proxy survives the pruning of the daily rows it was derived from.
    for date, nets in networks_seen.items():
        row = daily_index.get(date)
        if row is not None:
            row["networks"] = len(nets)
        m = month_index.get(date[:7])
        if m is not None:
            m["networks_peak"] = max(_as_int(m.get("networks_peak")), len(nets))
        arc = archive_index.get(date)
        if arc is not None:
            arc["networks"] = len(nets)
    # EXPORT EVENTS for the days folded in THIS run: distinct masked networks that took at least one
    # bulk-labelled download that day, summed into the cumulative total and into the month. A second
    # export from the same network on the same day is not separable from the first and is not claimed
    # to be, so this is a floor on export actions and is reported as a proxy, never as a count of them.
    # Only the SIZE of each set is written; the masked addresses never leave memory.
    for date, nets in bulk_networks_seen.items():
        totals["bulk_export_events"] = _as_int(totals.get("bulk_export_events")) + len(nets)
        m = month_index.get(date[:7])
        if m is not None:
            m["bulk_export_events"] = _as_int(m.get("bulk_export_events")) + len(nets)
        arc = archive_index.get(date)
        if arc is not None:
            arc["bulk_events"] = len(nets)
    # One increment per distinct ACTIVE date, so a month row records how much of itself it covers.
    # `detail_days` rides the same loop and counts the same days, because every day THIS fold folds is
    # folded with every dimension it knows about. The two diverge only across an upgrade: a month
    # carried forward from an older file keeps its `days` and gains detail_days only for the days
    # folded from here on, which is precisely what lets the screen refuse to render a zero for a
    # dimension that month never measured.
    for month_key in days_seen.values():
        month_index[month_key]["days"] += 1
        month_index[month_key]["detail_days"] = _as_int(month_index[month_key].get("detail_days")) + 1
    # One increment per distinct date that actually contributed a country to this month.
    for month_key in geo_days_seen.values():
        month_index[month_key]["geo_days"] = _as_int(month_index[month_key].get("geo_days")) + 1

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

    # The DENOMINATOR, restamped every fold from the manifest being served right now. "12 surveys
    # downloaded" reads very differently against 14 served and against 140, and the screen had no
    # denominator at all. It is a property of the current build, not an accumulated count, so it is
    # overwritten rather than accrued; an absent or unreadable manifest yields 0 and the screen then
    # renders the numerator alone rather than a ratio against a fabricated total.
    stats["total_served_surveys"] = _served_survey_count(reverse_map)

    stats["schema"] = SCHEMA_VERSION
    stats["generated_at"] = now_utc(run_dt)
    stats["timer_period_min"] = TIMER_PERIOD_MIN
    # The archive rows for the days this call folded, oldest first. Only days with counted activity
    # produce one, exactly as only such days produce a daily row: a day the fold passed over holds no
    # measurement, and writing an all-zero line for it would state one.
    if archive_out is not None:
        archive_out.extend(_archive_line(archive_index[d], served_build=served_build)
                           for d in sorted(archive_index))
    return stats


def _bump(counter: dict, key: str, n: int = 1) -> None:
    counter[key] = _as_int(counter.get(key)) + n


def _reclassify_select(counter: dict) -> None:
    """Move one already-counted download from `single` to `bulk`. Used when a later request for the same
    file on the same day carries the portal's bulk label: the download is already in the headline total,
    so the split has to MOVE it rather than count it again."""
    counter[_SELECT_SINGLE] = _as_int(counter.get(_SELECT_SINGLE)) - 1
    counter[_SELECT_BULK] = _as_int(counter.get(_SELECT_BULK)) + 1


def _bump_volume(index: dict, key: str, size: int, *, counted: bool = True,
                 kind: str | None = None) -> None:
    """One download line of `size` bytes against `key` in a {key: {downloads, bytes}} map: the shape
    the collection rollup and the archive's per-survey map share. `counted` is False for a line the
    within-day dedupe already saw, whose bytes still sum because they really were served.

    `kind` ('file' / 'bundle' from the manifest row) additionally splits the counted downloads into
    `files` and `bundles`. It is passed ONLY by the archive's per-survey call site: those two keys
    exist on a row that has them and are simply absent from one that does not, so the collection
    rollup keeps the exact shape it has always written."""
    row = index.get(key)
    if not isinstance(row, dict):
        row = {"downloads": 0, "bytes": 0}
        index[key] = row
    row["downloads"] = _as_int(row.get("downloads")) + (1 if counted else 0)
    row["bytes"] = _as_int(row.get("bytes")) + size
    if kind is not None:
        for k in ("files", "bundles"):
            row[k] = _as_int(row.get(k))
        if counted and kind in ("file", "bundle"):
            row[kind + "s"] += 1


def _bump_handoff(index: dict, key: str, size: int) -> None:
    """One hand-off REQUEST of `size` register bytes against `key` in a {key: {requests, bytes}} map:
    the shape by_survey, by_level, by_destination and the archive's by_route all share. There is no
    `counted` flag here and there must not be one -- a hand-off is terminal at the front door, so
    every admitted line is another request rather than another leg of one (see `aggregate`)."""
    row = index.get(key)
    if not isinstance(row, dict):
        row = {"requests": 0, "bytes": 0}
        index[key] = row
    row["requests"] = _as_int(row.get("requests")) + 1
    row["bytes"] = _as_int(row.get("bytes")) + size


def _bump_survey(index: dict, survey: str, size: int, *, counted: bool = True,
                 country: str | None = None, kind: str | None = None) -> None:
    """One download line of `size` bytes against `survey` in a
    {survey: {downloads, bytes, countries, files, bundles}} map. Bundles land here under their OWN
    survey (the manifest bundle row carries it), so a whole-survey package download is credited to that
    survey exactly like a per-station file.

    `counted` is False for a line the within-day dedupe already saw (the second leg of an abort+refetch
    pair, a further range fragment): its BYTES still sum, because they really were served, but it adds
    no second download to the survey's count.

    `country` accrues into a sorted, de-duplicated list of country codes for this survey. That list is
    the custodian promise made derivable ("downloaded N times from M countries"). It is stored at
    COUNTRY grain and nothing finer, and only its COUNT is ever rendered or exported: a named survey
    beside a named country is already a small cell in a community this size, and the same small-cell
    argument that rules out a city column rules out publishing the list itself.

    `kind` is the manifest row's 'file' / 'bundle', which splits this survey's own counted downloads
    into `files` and `bundles` -- the per-survey form of the global by_kind map, and the form the
    question actually takes ("was my survey pulled station by station or taken whole"). A de-duplicated
    line adds bytes and no split, exactly as it adds no download."""
    row = index.get(survey)
    if not isinstance(row, dict):
        row = {"downloads": _as_int(row), "bytes": 0, "countries": [], "files": 0, "bundles": 0}
        index[survey] = row
    row["downloads"] = _as_int(row.get("downloads")) + (1 if counted else 0)
    row["bytes"] = _as_int(row.get("bytes")) + size
    for k in ("files", "bundles"):
        row[k] = _as_int(row.get(k))
    if counted and kind in ("file", "bundle"):
        row[kind + "s"] += 1
    if country:
        codes = row.get("countries")
        if not isinstance(codes, list):
            codes = []
        if country not in codes:
            codes.append(country)
            codes.sort()
        row["countries"] = codes


def _bump_class_detail(index: dict, code: str, metric: str, size: int) -> None:
    """One request against `code` in a per-place DETAIL map: which metric it was, and its bytes. The
    country and state detail maps share this shape and this bump (see _empty_class_detail)."""
    row = index.get(code)
    if not isinstance(row, dict):
        row = _empty_class_detail()
        index[code] = row
    if metric in _CLASS_METRICS:
        row[metric] = _as_int(row.get(metric)) + 1
    row["bytes"] = _as_int(row.get("bytes")) + size


def _count_geo(geoip: GeoIP, au_states, address, countries: dict, by_country_detail: dict,
               by_state: dict, by_state_detail: dict, month: dict, *, metric: str,
               size: int = 0) -> None:
    """Resolve the masked address to a country (and, for AU, to a state) and count it. The address
    itself is discarded immediately -- only the country code and the state code are ever counted.
    `metric` says which class of request this was ('downloads' / 'visits' / 'api') and `size` its bytes,
    which is what the per-place detail maps are built from.

    TWO maps are written at COUNTRY grain, side by side, for every counted request: `countries`, a bare
    request count per country, which the country table and the AU-row reconciliation beneath it are
    built on and which is therefore left exactly as it was; and `by_country_detail`, which splits those
    same requests into downloads, visits, API requests and bytes. The detail is unconditional -- the
    country lookup is the fold's own and every counted request already goes through it -- so a box with
    no AU state table still gets the full country breakdown.

    The state half is entirely conditional on the OPTIONAL state table being loaded. When it is:
      * every AU request lands in exactly ONE bucket -- its state, or the explicit `unattributed`
        bucket when the table does not cover that prefix. Nothing is dropped, so the state rows plus
        `unattributed` reconcile exactly with the AU country row they sit beneath;
      * TWO maps are written side by side: `by_state`, a bare request count per state, which the
        screen's reconciliation rows and their exact-total promise are built on and which is therefore
        left exactly as it was; and `by_state_detail`, which splits the same requests into downloads,
        visits, API requests and bytes, because "how much was downloaded from Western Australia, and
        how many bytes" is the question a funding report actually asks;
      * both go to the cumulative map and the calendar-month rollup, and NOWHERE ELSE. There is
        deliberately NO day-by-state cell: it would be the finest-grained cell in the whole file, and
        the small-cell argument that rules out a city column (see AuStates) rules out a named day in a
        named state just as squarely. Nothing renders or exports such a cell, so it is not recorded in
        the first place rather than recorded and then withheld.
    When the table is NOT loaded, nothing at all is written: no bucket, no zero. Months folded before
    it was installed are therefore ABSENT from the breakdown rather than reading as a measured zero,
    and they are never backfilled (the raw logs are long gone).

    ALL FOUR maps live at the cumulative and calendar-month grains and NOWHERE ELSE. The day-grain
    exclusion is not a state-only rule: a named COUNTRY on a named day is a smaller cell than a named
    state in a named month, so the country detail is barred from the daily rows and from the daily
    archive for exactly the reason the state detail is."""
    cc = geoip.country(address)
    _bump(countries, cc)
    _bump(month["countries"], cc)
    _bump_class_detail(by_country_detail, cc, metric, size)
    _bump_class_detail(month.setdefault("by_country_detail", {}), cc, metric, size)
    if cc != "AU" or au_states is None or not au_states.loaded:
        return
    code = au_states.state(address) or AU_STATE_UNATTRIBUTED
    _bump(by_state, code)
    _bump(month.setdefault("by_state", {}), code)
    _bump_class_detail(by_state_detail, code, metric, size)
    _bump_class_detail(month.setdefault("by_state_detail", {}), code, metric, size)


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
    # The hand-off block is added on FIRST USE, not here (see `aggregate`): a day row is created for
    # every counted request of any class, and a dense zeroed block on a day that saw no hand-off would
    # state a measurement rather than the absence of one. It carries no by-country map and no station
    # grain -- both are barred below the month (the geo boundary) or belong to the archive.
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
# The APPEND-ONLY DAILY ARCHIVE: capture maximal non-geo granularity at day
# grain now, so a report nobody has asked for yet can still be derived later).
#
# WHY IT EXISTS. The raw log rotates in about a week and the daily rows in stats.json roll off after 92
# days, so today the only permanent record is the calendar-month rollup. Every question finer than a
# month becomes unanswerable the moment the window passes, and it becomes unanswerable RETROACTIVELY:
# the data existed, we folded it, and we threw the detail away. This file is the durable aggregate.
#
# WHAT IT IS NOT. It is not read by anything. The gateway never opens it, no route serves it, and it
# lives in the gateway state dir, outside the published site-data tree. It is not pruned, and it is
# not rewritten: a day is appended once, when it folds, and the fold watermark guarantees that happens
# exactly once. Nothing here is ever backfilled.
#
# THE GEO BOUNDARY, which is the one line that must not move. The exclusion of
# day-by-state data generalises: NO country and NO state below month grain, rendered OR archived. A
# named country on a named day is a smaller cell than a named state on a named month, and the
# small-cell argument that excludes a city column excludes it too. So these rows carry counts,
# volumes, formats, kinds, client classes, surveys, datasets and collections, and no geography at all.
# The leak sweep is extended over the archive for the same reason it covers stats.json.
# --------------------------------------------------------------------------------------------------
def _archive_day(index: dict, date: str) -> dict:
    """The run-local working row for `date`, created on first use. Dense while it accumulates; the
    zero counters and empty maps are dropped when it is serialised (see _archive_line)."""
    row = index.get(date)
    if row is None:
        row = {"date": date, "downloads": 0, "visits": 0, "api": 0, "networks": 0,
               "bulk_events": 0, "download_bytes": 0, "unattributed": 0, "by_format": {},
               "by_kind": {}, "by_client": {}, "by_select": {}, "by_survey": {}, "by_dataset": {},
               "by_collection": {}, "handoffs": _empty_handoffs()}
        # The hand-off family's STATION-GRAIN cell, keyed on <survey>/<station>/<level>: the by_dataset
        # of this family, and archive-only for the same reason. The 92-day window is exactly what
        # otherwise loses "which station, on which day" forever, and this file is never served.
        row["handoffs"]["by_route"] = {}
        index[date] = row
    return row


def _handoff_archive_block(row) -> dict:
    """One day's hand-off block as the archive writes it: SPARSE, like every other map on an archive
    line, and EMPTY (so the key is omitted entirely) for a day that saw no hand-off. It carries the
    route detail and no geography at all -- the by-country map lives at the month and above."""
    if not isinstance(row, dict):
        return {}
    out: dict = {}
    for key in ("requests", "bytes", "unattributed"):
        if _as_int(row.get(key)):
            out[key] = _as_int(row[key])
    for key in ("by_survey", "by_level", "by_destination", "by_route"):
        if row.get(key):
            out[key] = row[key]
    return out


def _archive_line(row: dict, *, served_build: str | None = None) -> dict:
    """One archive row as it is written: SPARSE, so a quiet day is a short line rather than a wall of
    zeroes and an empty map. `date` is always present; every other key appears only when it carries
    something. `served_build` is stamped when the served tree names itself and the key is simply
    omitted when it does not (see _served_build_id: this reads an identifier, it never makes one).

    There is deliberately no country, state, address or user-agent key here, and no per-network datum
    beyond the scalar `networks` and `bulk_events` counts. Both are sizes of a run-local set of masked
    networks; neither is a per-network record, and the sets die with the process.

    `by_select` and `bulk_events` belong here for the same reason the format and client splits do: they
    are day facts with no geography in them, and the day grain is exactly what is otherwise lost once
    the 92-day window drops the row."""
    out: dict = {"date": row["date"]}
    for key in ("downloads", "visits", "api", "networks", "bulk_events", "download_bytes",
                "unattributed"):
        if _as_int(row.get(key)):
            out[key] = _as_int(row[key])
    for key in ("by_format", "by_kind", "by_client", "by_select", "by_survey", "by_dataset",
                "by_collection"):
        if row.get(key):
            out[key] = row[key]
    handoffs = _handoff_archive_block(row.get("handoffs"))
    if handoffs:
        out["handoffs"] = handoffs
    if served_build:
        out["served_build"] = served_build
    return out


# --------------------------------------------------------------------------------------------------
# I/O: read the log dir, load inputs, write stats.json atomically (tmp -> chmod 0644 -> os.replace).
# --------------------------------------------------------------------------------------------------
def read_log_lines(log_dir, *, skipped: list | None = None) -> list[str]:
    """Every line of every Caddy access-log file under `log_dir`: the live access.json, its PLAIN
    rolled siblings (access*.json / access*.log), and its COMPRESSED rolled siblings (access*.json.gz).

    The compressed arm is the salvage path. Caddy gzips a rolled log unless `roll_uncompressed` is set,
    which both shipped Caddyfiles now do, so new rolls stay plain and both this glob and the front-door
    ship filter see them. A box that rolled BEFORE that setting shipped, or an operator placing a
    recovered archive by hand, still has whole days sitting in .gz. Reading them here matters more than
    it looks: a day is folded exactly once and the watermark then advances past it regardless (see
    `aggregate`), so a roll this function never opens is not late data, it is lost data.

    The two globs are DISJOINT by construction (`access*.json` cannot match a name ending `.json.gz`),
    so no archive is read twice.

    Tolerant, as the whole file is (retention pin): a missing dir, an unreadable file, or a
    truncated/non-gzip archive contributes no lines from THAT file and never raises.

    TOLERANT IS NOT SILENT, and the difference cost real days. On the box's own access.json
    was root:root 0600, every open raised, and this function swallowed it: the fold ran for days on the
    shipped front-door file alone and produced a plausible, complete-looking stats.json the whole time.
    A file that the glob MATCHED but that could not be OPENED is an operational fault, so it is named
    on stderr and recorded in `skipped` (an optional list the caller passes to get the count into the
    journal line). Never raising is unchanged; being quiet about it is not.

    A gzip archive gets the distinction it earns. Failing to OPEN it is the same fault as above and is
    reported. Opening it and finding it is not a gzip stream (or is truncated mid-stream) is the
    already-documented salvage case, expected of a hand-placed or half-pulled archive, and stays a
    silent skip: it must not turn a routine recovery into a nightly warning."""
    lines: list[str] = []
    if not log_dir:
        return lines
    d = Path(log_dir)
    if not d.is_dir():
        return lines

    def _unreadable(path, exc) -> None:
        print(f"aggregate_stats: cannot read log file {path} ({type(exc).__name__}: {exc}) -- "
              f"its lines are NOT in this fold", file=sys.stderr)
        if skipped is not None:
            skipped.append(str(path))

    files = sorted(glob.glob(str(d / "access*.json")) + glob.glob(str(d / "access*.log")))
    for f in files:
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                lines.extend(fh.read().splitlines())
        except OSError as exc:
            _unreadable(f, exc)
    for f in sorted(glob.glob(str(d / "access*.json.gz"))):
        try:
            raw = open(f, "rb")
        except OSError as exc:      # permissions, a vanished file: the same fault as above
            _unreadable(f, exc)
            continue
        try:
            with gzip.open(raw, "rt", encoding="utf-8", errors="replace") as fh:
                lines.extend(fh.read().splitlines())
        except (OSError, EOFError, zlib.error):
            # Not a gzip stream, truncated, or corrupt mid-stream. Skip this archive and keep the
            # readable ones: one bad file must never cost a whole fold (gzip.BadGzipFile is an OSError).
            continue
        finally:
            raw.close()
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
    the state dir); a missing dir raises, caught by main."""
    dest = Path(stats_file)
    tmp = dest.with_name(f"{dest.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(stats, indent=1), encoding="utf-8")
    try:
        os.chmod(tmp, 0o644)
    except OSError:
        pass
    os.replace(tmp, dest)


def _served_build_id(served_dir) -> str | None:
    """The identifier the SERVED tree already carries, or None. Read from build.json's `build_id`
    (the build root writes it beside manifest.json), falling back to build_report.json's `build_id`
    and then its `generated` stamp.

    This READS an identifier, it never makes one: no machinery is added to stamp a build that does not
    stamp itself, and a tree that names itself nowhere simply archives no such key."""
    for name, keys in (("build.json", ("build_id",)),
                       ("build_report.json", ("build_id", "generated"))):
        doc = _load_json(Path(served_dir) / name)
        for key in (keys if isinstance(doc, dict) else ()):
            val = doc.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


def append_daily_archive(archive_file, rows) -> int:
    """Append one JSON line per newly folded day to the archive, oldest first. Returns the number
    of day lines actually written (0 when there was nothing to write or the append failed), so the
    journal line reports what landed rather than what was offered.

    APPEND-ONLY and never rewritten, so this cannot corrupt what is already there. It is called only
    AFTER stats.json has landed, which is what makes a duplicate impossible: if the stats write fails,
    the watermark never advances, the same days fold again next run, and they must not already be in
    the file. The reverse failure (stats written, this append fails) loses that day from the archive,
    which is the tolerable direction and is why it is noted loudly.

    Never raises, like everything else the timer calls: a warning on stderr, and the fold still
    counts as done."""
    if not archive_file or not rows:
        return 0
    try:
        with open(archive_file, "a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
    except OSError as exc:
        print(f"aggregate_stats: could not append {len(rows)} day(s) to the daily archive at "
              f"{archive_file} ({type(exc).__name__}: {exc}) -- stats.json is unaffected, but those "
              f"days are not in the permanent archive", file=sys.stderr)
        return 0
    return len(rows)


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
    # The permanent daily archive lives BESIDE stats.json, i.e. in the gateway state dir and outside
    # the published site-data tree, because nothing serves it and nothing should be able to.
    archive_file = _cfg("AUSMT_STATS_DAILY_ARCHIVE",
                        str(Path(stats_file).parent / _ARCHIVE_FILENAME))
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
        # The collection rollup and the build stamp both come from the SERVED tree beside the manifest
        # (mtcat.json, build.json). Both optional, both read tolerantly: absent, the fold simply
        # writes no collection dimension and stamps no build on the archive rows.
        served_dir = Path(manifest_path).parent
        collections = build_collection_map(_load_json(served_dir / "mtcat.json"), reverse_map)
        served_build = _served_build_id(served_dir)
        # The hand-off index, read from the SERVED tree beside the manifest exactly as mtcat.json and
        # build.json are, and optional in exactly the same way: the build emits it only when a station
        # actually has a verified, open archive route (a deployment with none serves no such file).
        # Absent, hand-offs still count as requests and carry no bytes -- see `aggregate`.
        ts_access = _load_json(served_dir / "ts_access.json") or {}
        prev = _load_json(stats_file)
        skipped_logs: list[str] = []
        lines = read_log_lines(log_dir, skipped=skipped_logs)
        archive_rows: list[dict] = []
        stats = aggregate(prev, lines, reverse_map, geoip, run_dt, daily_keep=daily_keep,
                          au_states=au_states, collections=collections,
                          served_build=served_build, archive_out=archive_rows,
                          ts_access=ts_access)
        dest_dir = Path(stats_file).parent
        if not dest_dir.is_dir():
            print(f"aggregate_stats: state dir {dest_dir} does not exist -- not writing stats.json "
                  f"(is the gateway state dir created?)", file=sys.stderr)
            return 0
        write_stats_atomic(stats_file, stats)
        # AFTER the stats write, deliberately: a failed stats write leaves the watermark where it was,
        # so those days fold again next run and must not already sit in the append-only archive.
        archived = append_daily_archive(archive_file, archive_rows)
        print(f"aggregate_stats: folded up to {stats.get('last_folded_date')} -- "
              f"downloads={stats['totals']['downloads']} visits={stats['totals']['visits']} "
              f"api={stats['totals']['api_requests']} "
              f"handoffs={stats['handoffs']['requests']} months={len(stats['monthly'])} "
              f"days_kept={len(stats['daily'])} "
              f"manifest_rows={len(reverse_map)} geoip_rows={geoip.row_count} "
              f"au_state_rows={au_states.row_count} collections={len(collections)} "
              f"log_lines={len(lines)} files_skipped={len(skipped_logs)} "
              f"archived_days={archived} -> {stats_file}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 -- never raise into the timer; note loudly and exit 0
        print(f"aggregate_stats: aborted without writing ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
