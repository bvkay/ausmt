"""C45 usage-analytics aggregator pins (record D6 — the C45-impl lane).

These prove the load-bearing aggregator behaviours against INDEPENDENT OBSERVABLES (the emitted
stats.json bytes, the attribution over an ENGINE-TRUTH manifest, the bisect result over a fixture
CSV), Invariant-10 style. Each pin states its failure criterion; the leak + attribution pins carry an
explicit NEGATIVE CONTROL so the test can actually fail (a sweep that cannot catch a planted leak is
vacuous). Pure stdlib python + committed fixtures — runs EVERYWHERE (no caddy, no engine stack, no
network), so it never trips the CI skip tripwire.
"""
from __future__ import annotations

import datetime as dt
import gzip
import importlib.util
import json
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "deploy" / "scripts" / "aggregate_stats.py"
_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_MANIFEST = _FIXTURES / "manifest.engine-truth.json"
_DBIP = _FIXTURES / "dbip-country-lite.sample.csv"

# IP-like tokens the leak sweep hunts (record D6 leak pin): any IPv4 dotted-quad, or an IPv6 token —
# one carrying a `::` (every masked /48 compresses to one) OR >=4 hextet groups (>=3 internal colons).
# That discriminates a real address from a `HH:MM:SS` timestamp (2 colons, no `::`), so the sweep flags
# a leaked address but not the file's own generated_at — a precise, non-vacuous hunt.
_IPV4_RE = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
_IPV6_RE = re.compile(r"[0-9a-fA-F]{1,4}::[0-9a-fA-F:]*|::[0-9a-fA-F]{1,4}|"
                      r"(?:[0-9a-fA-F]{1,4}:){3,}[0-9a-fA-F]{1,4}")
# A UA fingerprint the leak sweep hunts (the exact strings the synthetic lines carry).
_UA_MARKERS = ("Mozilla", "Chrome", "Safari", "AppleWebKit", "Googlebot", "curl/", "python-requests")


def _load_agg():
    spec = importlib.util.spec_from_file_location("aggregate_stats", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


AGG = _load_agg()
_RUN = dt.datetime(2026, 7, 12, 3, 30, 0, tzinfo=dt.timezone.utc)   # a fixed run instant for the pins


def _line(uri, addr, *, status=200, size=1000, ua="Mozilla/5.0 (X11) AppleWebKit/537",
          date="2026-07-10", method="GET"):
    """One synthetic Caddy JSON access-log line for `uri` from masked address `addr` on `date` (a
    complete day relative to _RUN). `ts` is a float epoch, exactly as Caddy's default JSON encoder."""
    epoch = dt.datetime.strptime(date + "T05:00:00Z", "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=dt.timezone.utc).timestamp()
    return json.dumps({
        "ts": epoch, "status": status, "size": size,
        "request": {"method": method, "uri": uri, "client_ip": addr, "remote_ip": addr,
                    "headers": {"User-Agent": [ua], "Cookie": ["sess=SECRET"]}},
    })


def _sweep_ip_or_ua(text: str) -> list[str]:
    """Every IP-like or UA-like token in `text` (whitespace between JSON tokens excluded). Country
    codes / dates / url paths must produce NONE."""
    hits = _IPV4_RE.findall(text) + _IPV6_RE.findall(text)
    hits += [m for m in _UA_MARKERS if m in text]
    return hits


# --------------------------------------------------------------------------------------------------
# Leak pin (record D6): stats.json carries NO address (masked or not) and NO UA string.
# --------------------------------------------------------------------------------------------------
def test_leak_pin_stats_has_no_ip_or_ua_and_sweep_can_fail():
    """LEAK PIN. The emitted stats.json must contain no IPv4/IPv6 token and no user-agent string —
    only aggregates leave the pipeline (record D2). FAILS IF a masked address or a UA fingerprint
    survives into stats.json. NEGATIVE CONTROL (red-proven): the SAME sweep, run over a dict that DID
    store the address + UA, MUST report hits — a sweep that cannot fail would be vacuous."""
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    rmap = AGG.build_reverse_map(manifest)
    geoip = AGG.GeoIP.load(_DBIP)
    lines = [
        _line("/data/edi/sample-survey/Vulcan_A1.edi", "203.0.113.5"),
        _line("/data/xml/sample-survey/A1.xml", "1.2.3.0"),
        _line("/data/bundles/sample-survey-tf.h5", "198.51.100.0"),
        _line("/data/catalogue.json", "2001:db8:1234::"),
        _line("/data/edi/UNKNOWN/x.edi", "8.8.8.0"),
    ]
    stats = AGG.aggregate(None, lines, rmap, geoip, _RUN)
    emitted = json.dumps(stats, indent=1)
    hits = _sweep_ip_or_ua(emitted)
    assert hits == [], f"stats.json leaked address/UA tokens: {hits}\n{emitted}"

    # NEGATIVE CONTROL: a would-be-buggy aggregator that stored the raw addresses (v4 AND masked v6) +
    # UA. The sweep MUST catch each, proving this test is non-vacuous AND that both IP branches bite.
    assert _IPV4_RE.findall("stored 203.0.113.5 here"), "the IPv4 branch must catch a dotted quad"
    assert _IPV6_RE.findall("stored 2001:db8:1234:: here"), "the IPv6 branch must catch a masked /48"
    leaky = dict(stats)
    leaky["_debug"] = {"v4": "203.0.113.5", "v6": "2001:db8:1234::",
                       "ua": "Mozilla/5.0 (X11) AppleWebKit/537"}
    assert _sweep_ip_or_ua(json.dumps(leaky)), "the leak sweep failed to catch a planted address/UA"
    # And the sweep must NOT false-positive on the file's own ISO timestamp (a HH:MM:SS is not an IP).
    assert _sweep_ip_or_ua('"generated_at": "2026-07-12T03:30:00Z"') == []


# --------------------------------------------------------------------------------------------------
# Attribution pin (record D6): engine-truth manifest -> right survey/station/format; unknown ->
# unattributed, never dropped.
# --------------------------------------------------------------------------------------------------
def test_attribution_pin_over_engine_truth_manifest():
    """ATTRIBUTION PIN. Over a REAL engine-built manifest.json (committed fixture) + synthetic log
    lines for its real URLs, each download attributes to the correct survey/station/format; an unknown
    /data/edi path lands in `unattributed` and is NEVER dropped. FAILS IF a known URL misattributes, an
    unknown path is silently dropped (download count and unattributed disagree), or the by_dataset row
    carries the wrong station/format."""
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    rmap = AGG.build_reverse_map(manifest)
    assert rmap, "the engine-truth manifest must yield a non-empty reverse map"
    geoip = AGG.GeoIP.load(_DBIP)
    lines = [
        _line("/data/edi/sample-survey/Vulcan_A1.edi", "203.0.113.5"),   # A1 edi
        _line("/data/edi/sample-survey/Vulcan_A1.edi", "203.0.113.6"),   # A1 edi (2nd)
        _line("/data/xml/sample-survey/A2.xml", "1.2.3.0"),               # A2 emtfxml
        _line("/data/bundles/sample-survey-tf.h5", "198.51.100.0"),       # survey mth5 bundle
        _line("/data/edi/mystery-survey/ghost.edi", "8.8.8.0"),           # UNKNOWN -> unattributed
        _line("/data/catalogue.json?_=1", "203.0.113.5"),                 # visit (query stripped)
    ]
    stats = AGG.aggregate(None, lines, rmap, geoip, _RUN)
    t = stats["totals"]
    assert t["downloads"] == 5, t
    assert t["visits"] == 1, t
    assert t["unattributed"] == 1, "the unknown /data/edi path must land in unattributed, not vanish"
    # download count == attributed rows + unattributed (nothing dropped silently)
    attributed = sum(d["downloads"] for d in stats["downloads"]["by_dataset"].values())
    assert attributed + t["unattributed"] == t["downloads"], (attributed, t)

    ds = stats["downloads"]["by_dataset"]
    a1 = ds["edi/sample-survey/Vulcan_A1.edi"]
    assert a1["survey"] == "CI Sample Survey" and a1["station"] == "A1" and a1["format"] == "edi"
    assert a1["downloads"] == 2
    a2 = ds["xml/sample-survey/A2.xml"]
    assert a2["station"] == "A2" and a2["format"] == "emtfxml"
    bundle = ds["bundles/sample-survey-tf.h5"]
    assert bundle["slug"] == "sample-survey" and bundle["format"] == "mth5" and bundle["station"] is None
    assert stats["downloads"]["by_format"]["unattributed"] == 1


def test_attribution_negative_control_unknown_path_not_attributed():
    """NEGATIVE CONTROL for attribution: a purely-unknown corpus of download paths must attribute ZERO
    datasets and count them ALL as unattributed. FAILS IF an unknown path is credited to a real dataset
    (a reverse map that matched too eagerly) or is dropped (downloads != unattributed)."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    lines = [_line("/data/edi/nope/a.edi", "8.8.8.0"),
             _line("/data/bundles/nope-edi.zip", "8.8.8.0")]
    stats = AGG.aggregate(None, lines, rmap, geoip, _RUN)
    assert stats["downloads"]["by_dataset"] == {}
    assert stats["totals"]["downloads"] == 2 == stats["totals"]["unattributed"]


# --------------------------------------------------------------------------------------------------
# Country pin (record D6): bisect resolves known ranges incl a masked /24; missing/stale CSV ->
# unknown, aggregator still completes.
# --------------------------------------------------------------------------------------------------
def test_country_pin_bisect_resolves_known_ranges_including_masked():
    """COUNTRY PIN. The stdlib bisect over the fixture CSV resolves known IPv4/IPv6 ranges, INCLUDING a
    masked /24 address (last octet 0) and a masked /48 IPv6. FAILS IF a masked address in a known range
    resolves wrong, or an out-of-range address is not 'unknown'."""
    geoip = AGG.GeoIP.load(_DBIP)
    assert geoip.loaded and geoip.row_count == 7     # 7 ranges; the fixture's comment rows are skipped
    assert geoip.country("203.0.113.0") == "AU"      # masked /24, network base
    assert geoip.country("202.158.4.0") == "AU"      # AU, but absent from the state table (see below)
    assert geoip.country("203.0.113.200") == "AU"    # anywhere in the /24
    assert geoip.country("1.2.3.0") == "NZ"          # masked /24 in a wider range
    assert geoip.country("198.51.100.0") == "US"
    assert geoip.country("2001:db8::") == "DE"       # masked /48 IPv6 base
    assert geoip.country("2400:cb00::") == "AU"      # a different IPv6 range (proves the sort/bisect)
    assert geoip.country("8.8.8.0") == "unknown"     # outside every range
    assert geoip.country("not-an-ip") == "unknown"
    assert geoip.country(None) == "unknown"


def test_country_missing_csv_degrades_to_unknown_and_still_folds(tmp_path):
    """COUNTRY DEGRADATION PIN. A missing OR malformed CSV must degrade every lookup to 'unknown' and
    the aggregator must STILL complete a full fold (record D6). FAILS IF a missing/garbage CSV raises,
    or a lookup returns anything but 'unknown'."""
    # (a) missing file
    missing = AGG.GeoIP.load(tmp_path / "does-not-exist.csv")
    assert not missing.loaded and missing.country("203.0.113.0") == "unknown"
    # (b) malformed / stale content (not valid CSV ranges)
    bad = tmp_path / "bad.csv"
    bad.write_text("this is not,a valid range file\n<html>garbage</html>\n", encoding="utf-8")
    badgeo = AGG.GeoIP.load(bad)
    assert badgeo.country("203.0.113.0") == "unknown"
    # The fold still completes over a degraded geoip -> every request counts under 'unknown'.
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    lines = [_line("/data/edi/sample-survey/Vulcan_A1.edi", "203.0.113.5")]
    stats = AGG.aggregate(None, lines, rmap, badgeo, _RUN)
    assert stats["totals"]["downloads"] == 1
    assert stats["countries"] == {"unknown": 1}


# --------------------------------------------------------------------------------------------------
# Retention / absent-log pin (record D6): the aggregator tolerates an absent (already-rotated) log.
# --------------------------------------------------------------------------------------------------
def test_absent_log_is_tolerated(tmp_path):
    """RETENTION / ABSENT-LOG PIN. read_log_lines over a missing dir (logs already rotated away) yields
    no lines and never raises; a fold over zero lines still produces a valid stats.json that advances
    the watermark. FAILS IF an absent log dir raises or yields a broken stats doc."""
    assert AGG.read_log_lines(tmp_path / "no-such-caddy-dir") == []
    assert AGG.read_log_lines(None) == []
    stats = AGG.aggregate(None, [], {}, AGG.GeoIP.load(None), _RUN)
    assert stats["totals"]["downloads"] == 0 and stats["totals"]["visits"] == 0
    assert stats["last_folded_date"] == "2026-07-11"   # advanced to run-date-1 even with no lines
    assert stats["generated_at"] == "2026-07-12T03:30:00Z"


def test_rolled_plain_json_siblings_are_read_beside_the_live_log(tmp_path):
    """ROLLED-SIBLING PIN. Caddy rolls access.json to a timestamped sibling, and the fold reads a day
    exactly once, so a roll that the glob misses loses those lines permanently (the watermark advances
    regardless). Every plain rolled sibling must therefore be read alongside the live file. FAILS IF
    the glob only picks up the live access.json."""
    logdir = tmp_path / "caddy"
    logdir.mkdir()
    (logdir / "access.json").write_text(
        _line("/data/catalogue.json", "203.0.113.5") + "\n", encoding="utf-8")
    (logdir / "access-2026-07-10T03-25-11.004.json").write_text(
        _line("/data/edi/sample-survey/Vulcan_A1.edi", "203.0.113.5") + "\n", encoding="utf-8")
    lines = AGG.read_log_lines(logdir)
    assert len(lines) == 2, lines
    stats = AGG.aggregate(None, lines, AGG.build_reverse_map(
        json.loads(_MANIFEST.read_text(encoding="utf-8"))), AGG.GeoIP.load(_DBIP), _RUN)
    assert stats["totals"]["visits"] == 1 and stats["totals"]["downloads"] == 1


def test_compressed_rolled_logs_are_folded_and_a_corrupt_archive_is_skipped(tmp_path):
    """GZIP-ROLL PIN. Caddy COMPRESSES a rolled log unless `roll_uncompressed` is set, so a box that
    rolled before that setting shipped (or an operator hand-placing a salvaged archive) has whole days
    sitting in access*.json.gz. The fold reads a day once and then advances its watermark past it, so a
    .gz the glob never opens is a day lost for good. Every compressed sibling must be read, and a
    corrupt/truncated archive must be skipped SILENTLY without costing the readable ones. FAILS IF a
    .gz roll is ignored, or if one bad archive raises or suppresses the good ones."""
    logdir = tmp_path / "caddy"
    logdir.mkdir()
    (logdir / "access.json").write_text(
        _line("/data/catalogue.json", "203.0.113.5") + "\n", encoding="utf-8")
    with gzip.open(logdir / "access-2026-07-09T03-25-02.001.json.gz", "wt", encoding="utf-8") as fh:
        fh.write(_line("/data/edi/sample-survey/Vulcan_A1.edi", "203.0.113.5", date="2026-07-09") + "\n")
    with gzip.open(logdir / "access-frontdoor-2026-07-10T03-25-07.002.json.gz", "wt",
                   encoding="utf-8") as fh:
        fh.write(_line("/data/xml/sample-survey/A2.xml", "1.2.3.0", date="2026-07-10") + "\n")
    # A corrupt archive beside them: plain text under a .gz name, exactly what a truncated pull leaves.
    (logdir / "access-2026-07-08T03-25-00.000.json.gz").write_text("not gzip at all\n", encoding="utf-8")

    lines = AGG.read_log_lines(logdir)
    assert len(lines) == 3, f"the two readable archives plus the live file must all be read: {lines}"
    stats = AGG.aggregate(None, lines, AGG.build_reverse_map(
        json.loads(_MANIFEST.read_text(encoding="utf-8"))), AGG.GeoIP.load(_DBIP), _RUN)
    assert stats["totals"]["downloads"] == 2, "both compressed days must fold"
    assert stats["totals"]["visits"] == 1
    assert {d["date"] for d in stats["daily"]} == {"2026-07-09", "2026-07-10"}


def test_a_compressed_log_is_not_also_read_as_a_plain_one(tmp_path):
    """DOUBLE-READ PIN. The plain glob and the compressed glob must be disjoint: `access*.json` must
    not also match `access*.json.gz`, or every gzipped roll would be read twice (once as binary
    garbage, once decompressed) and its day would double-count. FAILS IF the same archive is read by
    both arms."""
    logdir = tmp_path / "caddy"
    logdir.mkdir()
    with gzip.open(logdir / "access-2026-07-10T03-25-02.001.json.gz", "wt", encoding="utf-8") as fh:
        fh.write(_line("/data/catalogue.json", "203.0.113.5") + "\n")
    lines = AGG.read_log_lines(logdir)
    assert len(lines) == 1, f"the archive must be read exactly once: {lines}"
    stats = AGG.aggregate(None, lines, {}, AGG.GeoIP.load(_DBIP), _RUN)
    assert stats["totals"]["visits"] == 1


# --------------------------------------------------------------------------------------------------
# Idempotency: the raw log is NOT the database — re-reading the same lines never double-counts.
# --------------------------------------------------------------------------------------------------
def test_reruns_never_double_count():
    """IDEMPOTENCY PIN. Re-folding the SAME lines (same run instant) over the produced stats must not
    change any total — only complete days AFTER last_folded_date are folded (record D4). FAILS IF a
    re-run double-counts, i.e. the cumulative totals grow on a repeated fold."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    lines = [_line("/data/edi/sample-survey/Vulcan_A1.edi", "203.0.113.5"),
             _line("/data/catalogue.json", "203.0.113.5")]
    first = AGG.aggregate(None, lines, rmap, geoip, _RUN)
    second = AGG.aggregate(first, lines, rmap, geoip, _RUN)
    assert second["totals"] == first["totals"]
    assert second["countries"] == first["countries"]
    assert second["daily"] == first["daily"]


def test_incomplete_current_day_is_not_folded_until_complete():
    """PARTIAL-DAY PIN. A line dated on the RUN date (an incomplete day) is not folded; the next day's
    run (that day now complete) folds it exactly once. FAILS IF the current day is counted early
    (risking a partial count that later double-folds)."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    lines = [_line("/data/catalogue.json", "203.0.113.5", date="2026-07-12")]   # == _RUN date
    day0 = AGG.aggregate(None, lines, rmap, geoip, _RUN)
    assert day0["totals"]["visits"] == 0, "the current (incomplete) day must not be folded"
    # Next day: 07-12 is now complete.
    run_next = dt.datetime(2026, 7, 13, 3, 30, 0, tzinfo=dt.timezone.utc)
    day1 = AGG.aggregate(day0, lines, rmap, geoip, run_next)
    assert day1["totals"]["visits"] == 1, "the now-complete day must fold exactly once"


# --------------------------------------------------------------------------------------------------
# End-to-end: main() over a real on-disk layout writes stats.json atomically (0644) and exits 0.
# --------------------------------------------------------------------------------------------------
def test_main_writes_stats_json_end_to_end(tmp_path, monkeypatch):
    """MAIN INTEGRATION PIN. main() over a temp data dir (logs + manifest + CSV + state dir) writes a
    world-readable stats.json with the expected aggregates and returns 0. FAILS IF main() raises,
    returns non-zero, or omits the atomic write."""
    data = tmp_path / "data"
    logdir = data / "logs" / "caddy"
    state = data / "gateway" / "state"
    logdir.mkdir(parents=True)
    state.mkdir(parents=True)
    (logdir / "access.json").write_text("\n".join([
        _line("/data/edi/sample-survey/Vulcan_A1.edi", "203.0.113.5"),
        _line("/data/catalogue.json", "1.2.3.0"),
    ]) + "\n", encoding="utf-8")
    stats_file = state / "stats.json"

    monkeypatch.setenv("AUSMT_DATA_DIR", str(data))
    monkeypatch.setenv("AUSMT_STATS_MANIFEST", str(_MANIFEST))
    monkeypatch.setenv("AUSMT_STATS_DBIP_CSV", str(_DBIP))
    monkeypatch.setenv("AUSMT_STATS_FILE", str(stats_file))
    monkeypatch.setenv("AUSMT_STATS_NOW", "2026-07-12T03:30:00Z")

    rc = AGG.main([])
    assert rc == 0
    assert stats_file.is_file(), "main() must write stats.json"
    doc = json.loads(stats_file.read_text(encoding="utf-8"))
    assert doc["totals"]["downloads"] == 1 and doc["totals"]["visits"] == 1
    assert doc["countries"].get("AU") == 1 and doc["countries"].get("NZ") == 1
    assert doc["timer_period_min"] == 1440
    # No leak through the real file either.
    assert _sweep_ip_or_ua(stats_file.read_text(encoding="utf-8")) == []


def test_main_never_raises_on_broken_env(monkeypatch, tmp_path):
    """TIMER-SAFETY PIN. main() must never raise into the timer: a state dir that does not exist (so no
    write can land) still returns 0 with a loud note, not a traceback. FAILS IF main() raises or
    returns non-zero on a broken environment."""
    monkeypatch.setenv("AUSMT_DATA_DIR", str(tmp_path / "nonexistent-root"))
    monkeypatch.setenv("AUSMT_STATS_MANIFEST", str(_MANIFEST))
    monkeypatch.setenv("AUSMT_STATS_DBIP_CSV", str(_DBIP))
    monkeypatch.setenv("AUSMT_STATS_NOW", "2026-07-12T03:30:00Z")
    monkeypatch.delenv("AUSMT_STATS_FILE", raising=False)
    assert AGG.main([]) == 0
    # And with AUSMT_DATA_DIR entirely unset.
    monkeypatch.delenv("AUSMT_DATA_DIR", raising=False)
    assert AGG.main([]) == 0


# ==================================================================================================
# Funding-detail lane (schema 2): per-survey volume, format/kind split over time, the API-consumer
# path class, distinct masked networks, permanent monthly rollups, and the split retention window.
# Every dimension below is derived from what the fold ALREADY reads (path + masked address + size);
# nothing new is collected and no beacon exists.
# ==================================================================================================

def _v1_stats(**over) -> dict:
    """A LIVE-SHAPE schema-1 stats.json: bare-int by_survey, no by_kind, no api_requests, no monthly,
    daily rows carrying only date/downloads/visits. This is exactly what is on the box today."""
    doc = {
        "schema": 1, "timer_period_min": 1440, "generated_at": "2026-07-10T03:30:00Z",
        "since": "2026-07-06", "last_folded_date": "2026-07-09",
        "totals": {"downloads": 9, "visits": 20, "download_bytes": 4096, "unattributed": 1},
        "downloads": {
            "by_format": {"edi": 8, "unattributed": 1},
            "by_survey": {"CI Sample Survey": 8},
            "by_dataset": {"edi/sample-survey/Vulcan_A1.edi": {
                "survey": "CI Sample Survey", "station": "A1", "slug": None,
                "format": "edi", "downloads": 8}},
        },
        "countries": {"AU": 25, "unknown": 4},
        "daily": [{"date": "2026-07-06", "downloads": 4, "visits": 9},
                  {"date": "2026-07-09", "downloads": 5, "visits": 11}],
    }
    doc.update(over)
    return doc


def test_per_survey_rows_carry_downloads_and_volume_bundles_credited_to_their_survey():
    """PER-SURVEY PIN (a). The fold must emit per-survey rows carrying BOTH a download count and a byte
    volume, with a whole-survey BUNDLE credited to its own survey exactly like a per-station file. FAILS
    IF by_survey stays a bare count, if the volume is not accumulated, or if a bundle download is not
    attributed to its survey."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    lines = [
        _line("/data/edi/sample-survey/Vulcan_A1.edi", "203.0.113.5", size=1000),
        _line("/data/edi/sample-survey/Vulcan_A2.edi", "203.0.113.5", size=2000),
        _line("/data/bundles/sample-survey-edi.zip", "1.2.3.0", size=20500),   # the survey package
    ]
    stats = AGG.aggregate(None, lines, rmap, geoip, _RUN)
    row = stats["downloads"]["by_survey"]["CI Sample Survey"]
    assert row["downloads"] == 3, "the bundle must be credited to its survey alongside the two files"
    assert row["bytes"] == 23500, row
    # Per-dataset volume too (the top-datasets table's funding column).
    assert stats["downloads"]["by_dataset"]["bundles/sample-survey-edi.zip"]["bytes"] == 20500


def test_station_file_vs_survey_bundle_split_and_format_split_over_time():
    """FORMAT/KIND PIN (b). The fold must split downloads by FORMAT and by KIND (a single-station file
    vs a whole-survey bundle) both cumulatively and PER DAY, so the split can be reported over time.
    FAILS IF the kind split is absent, if a bundle is counted as a station file, or if the daily rows
    carry no per-format detail."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    lines = [
        _line("/data/edi/sample-survey/Vulcan_A1.edi", "203.0.113.5", date="2026-07-09"),
        _line("/data/xml/sample-survey/A1.xml", "203.0.113.5", date="2026-07-09"),
        _line("/data/bundles/sample-survey-edi.zip", "1.2.3.0", date="2026-07-10"),
        _line("/data/bundles/sample-survey-tf.h5", "1.2.3.0", date="2026-07-10"),
    ]
    stats = AGG.aggregate(None, lines, rmap, geoip, _RUN)
    assert stats["downloads"]["by_kind"] == {"file": 2, "bundle": 2}
    assert stats["downloads"]["by_format"] == {"edi": 1, "emtfxml": 1, "edi-zip": 1, "mth5": 1}
    daily = {d["date"]: d for d in stats["daily"]}
    assert daily["2026-07-09"]["formats"] == {"edi": 1, "emtfxml": 1}
    assert daily["2026-07-09"]["kinds"] == {"file": 2}
    assert daily["2026-07-10"]["formats"] == {"edi-zip": 1, "mth5": 1}
    assert daily["2026-07-10"]["kinds"] == {"bundle": 2}
    assert daily["2026-07-10"]["download_bytes"] == 2000


def test_api_consumer_paths_are_classified_from_the_path_alone():
    """API-CONSUMER PIN (c). The DOCUMENTED machine-readable entry points must classify as `api` and
    count on their own line, while every path the portal's own JS fetches on boot must NOT: the
    catalogue is a VISIT, and /data/manifest.json (the SPA's own copy) is neither. The class is a PATH
    class; the client class is a separate, orthogonal axis. FAILS IF an SPA-boot fetch is credited as an
    API consumer, if an API fetch inflates the visit count, or if the API line is missing."""
    assert AGG.classify("/data/products/manifest.json") == ("api", None)
    assert AGG.classify("/data/mtcat.json") == ("api", None)
    assert AGG.classify("/data/catalogue.json") == ("visit", None)
    assert AGG.classify("/data/manifest.json") == ("ignore", None)   # the SPA's own boot fetch
    assert AGG.classify("/data/surveys.json") == ("ignore", None)

    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    lines = [
        _line("/data/products/manifest.json", "8.8.8.0"),
        _line("/data/mtcat.json", "8.8.8.0"),
        _line("/data/manifest.json", "203.0.113.5"),      # SPA boot: not an API consumer
        _line("/data/catalogue.json", "203.0.113.5"),     # SPA boot: a visit
    ]
    stats = AGG.aggregate(None, lines, rmap, geoip, _RUN)
    assert stats["totals"]["api_requests"] == 2
    assert stats["totals"]["visits"] == 1, "an API fetch must not inflate portal visits"
    assert stats["totals"]["downloads"] == 0
    day = stats["daily"][0]
    assert day["api_requests"] == 2
    assert stats["monthly"][0]["api_requests"] == 2


def test_distinct_masked_networks_counted_per_day_without_retaining_any_address():
    """REACH PIN (d). Each folded day must record the COUNT of distinct masked networks seen on it (the
    /24 or /48 Caddy already truncated to), and stats.json must still contain no address. FAILS IF the
    count is wrong, if repeat requests from one network inflate it, or if any address survives the fold."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    lines = [
        _line("/data/catalogue.json", "203.0.113.0", date="2026-07-09"),
        _line("/data/catalogue.json", "203.0.113.0", date="2026-07-09"),   # same network, again
        _line("/data/edi/sample-survey/Vulcan_A1.edi", "1.2.3.0", date="2026-07-09"),
        _line("/data/catalogue.json", "2001:db8::", date="2026-07-10"),
    ]
    stats = AGG.aggregate(None, lines, rmap, geoip, _RUN)
    daily = {d["date"]: d for d in stats["daily"]}
    assert daily["2026-07-09"]["networks"] == 2, "two distinct networks, four requests"
    assert daily["2026-07-10"]["networks"] == 1
    assert _sweep_ip_or_ua(json.dumps(stats)) == [], "a network COUNT must not become a stored address"


def test_monthly_rollups_accumulate_and_survive_daily_pruning():
    """MONTHLY + RETENTION PIN (e). Calendar-month rollups must accumulate as days fold, and a daily
    prune must expire OLD DAILY rows while leaving every monthly row intact -- including months whose
    days are entirely gone from the daily window. FAILS IF the monthly arithmetic is wrong, if monthlies
    are recomputed from the (pruned) daily tail, or if a monthly row is pruned."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    # May: two days. June: one day. Folded with a generous window first.
    may = [_line("/data/edi/sample-survey/Vulcan_A1.edi", "203.0.113.5", date="2026-05-04", size=100),
           _line("/data/catalogue.json", "203.0.113.5", date="2026-05-04"),
           _line("/data/edi/sample-survey/Vulcan_A2.edi", "1.2.3.0", date="2026-05-30", size=200)]
    jun = [_line("/data/bundles/sample-survey-tf.h5", "1.2.3.0", date="2026-06-02", size=900)]
    run_may = dt.datetime(2026, 6, 1, 3, 30, tzinfo=dt.timezone.utc)
    run_jun = dt.datetime(2026, 6, 3, 3, 30, tzinfo=dt.timezone.utc)
    s1 = AGG.aggregate(None, may, rmap, geoip, run_may, daily_keep=92)
    s2 = AGG.aggregate(s1, jun, rmap, geoip, run_jun, daily_keep=92)
    months = {m["month"]: m for m in s2["monthly"]}
    assert months["2026-05"]["downloads"] == 2 and months["2026-05"]["download_bytes"] == 300
    assert months["2026-05"]["visits"] == 1 and months["2026-05"]["days"] == 2
    assert months["2026-05"]["surveys"]["CI Sample Survey"] == {"downloads": 2, "bytes": 300,
                                                              "countries": ["AU", "NZ"],
                                                              "files": 2, "bundles": 0}
    assert months["2026-06"]["downloads"] == 1 and months["2026-06"]["kinds"] == {"bundle": 1}
    assert months["2026-06"]["countries"] == {"NZ": 1}

    # Now a run far in the future with a 92-day window: every May/June daily row falls out of the
    # window, but BOTH monthly rows must survive with their arithmetic untouched.
    run_far = dt.datetime(2026, 11, 1, 3, 30, tzinfo=dt.timezone.utc)
    s3 = AGG.aggregate(s2, [], rmap, geoip, run_far, daily_keep=92)
    assert s3["daily"] == [], "daily rows older than the 92-day window must be pruned"
    months3 = {m["month"]: m for m in s3["monthly"]}
    assert set(months3) == {"2026-05", "2026-06"}, "monthly rollups are kept indefinitely"
    assert months3["2026-05"]["downloads"] == 2 and months3["2026-05"]["download_bytes"] == 300
    assert months3["2026-06"]["downloads"] == 1
    assert s3["totals"]["downloads"] == 3, "cumulative totals are unaffected by daily pruning"


def test_daily_window_keeps_92_days_and_drops_the_93rd():
    """RETENTION BOUNDARY PIN. The daily window is a rolling span of days ending at the fold watermark:
    the oldest day inside it is kept and the day one older is dropped. FAILS IF the window is measured
    in rows rather than days, or is off by one."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    run = dt.datetime(2026, 7, 12, 3, 30, tzinfo=dt.timezone.utc)      # watermark 2026-07-11
    inside = (dt.date(2026, 7, 11) - dt.timedelta(days=91)).isoformat()   # exactly 92 days inclusive
    outside = (dt.date(2026, 7, 11) - dt.timedelta(days=92)).isoformat()  # one day too old
    lines = [_line("/data/catalogue.json", "203.0.113.5", date=outside),
             _line("/data/catalogue.json", "203.0.113.5", date=inside)]
    stats = AGG.aggregate(None, lines, rmap, geoip, run, daily_keep=92)
    dates = [d["date"] for d in stats["daily"]]
    assert inside in dates and outside not in dates, dates
    # The pruned day is still fully represented in its month rollup (and in the totals).
    assert stats["totals"]["visits"] == 2
    assert sum(m["visits"] for m in stats["monthly"]) == 2


def test_v1_stats_file_upgrades_in_place_without_losing_or_inventing_anything():
    """MIGRATION PIN. A LIVE schema-1 stats.json must be read tolerantly and upgraded in place: every v1
    total/format/dataset carries forward, by_survey grows a volume field WITHOUT inventing historical
    bytes, monthly rollups are SEEDED from the days already folded (marked seeded_days), and
    detail_since marks where the new dimensions actually begin. FAILS IF a v1 field is lost, if a month
    absent from the daily tail is invented, or if a seeded month claims byte/format detail it lacks."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    run = dt.datetime(2026, 7, 11, 3, 30, tzinfo=dt.timezone.utc)   # folds 2026-07-10
    lines = [_line("/data/edi/sample-survey/Vulcan_A1.edi", "203.0.113.5", date="2026-07-10", size=50)]
    stats = AGG.aggregate(_v1_stats(), lines, rmap, geoip, run)

    assert stats["schema"] == 2
    # v1 cumulative counts survive and keep accruing.
    assert stats["totals"]["downloads"] == 10 and stats["totals"]["visits"] == 20
    assert stats["totals"]["api_requests"] == 0
    assert stats["downloads"]["by_format"]["edi"] == 9
    # by_survey migrates int -> {downloads, bytes}; the historical volume is NOT fabricated.
    assert stats["downloads"]["by_survey"]["CI Sample Survey"] == {"downloads": 9, "bytes": 50,
                                                                  "countries": ["AU"],
                                                                  "files": 1, "bundles": 0}
    assert stats["downloads"]["by_dataset"]["edi/sample-survey/Vulcan_A1.edi"]["downloads"] == 9
    # detail_since is the day after the v1 watermark: everything before it predates the new dimensions.
    assert stats["detail_since"] == "2026-07-10"
    # Monthly rollups seeded ONLY from the days the v1 file actually held -- no earlier month invented.
    months = {m["month"]: m for m in stats["monthly"]}
    assert set(months) == {"2026-07"}
    assert months["2026-07"]["seeded_days"] == 2, "both v1 daily rows are marked as seeded"
    assert months["2026-07"]["days"] == 3, "two seeded days plus the day folded now"
    assert months["2026-07"]["downloads"] == 4 + 5 + 1
    assert months["2026-07"]["visits"] == 9 + 11
    # The seeded portion carried no volume, so the month's byte figure covers ONLY the folded day.
    assert months["2026-07"]["download_bytes"] == 50


def test_upgrade_is_stable_and_does_not_reseed_or_restamp_on_later_runs():
    """MIGRATION IDEMPOTENCY PIN. Folding again over an already-upgraded file must NOT re-seed the
    monthly rows (double counting) nor re-stamp detail_since, and a FRESH install (no prior file) must
    never claim a detail_since at all. FAILS IF a second run doubles a month or moves the caveat line."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    run1 = dt.datetime(2026, 7, 11, 3, 30, tzinfo=dt.timezone.utc)
    run2 = dt.datetime(2026, 7, 12, 3, 30, tzinfo=dt.timezone.utc)
    once = AGG.aggregate(_v1_stats(), [], rmap, geoip, run1)
    twice = AGG.aggregate(once, [], rmap, geoip, run2)
    assert twice["monthly"] == once["monthly"], "a later run must not re-seed the rollups"
    assert twice["detail_since"] == once["detail_since"] == "2026-07-10"
    # A fresh install: nothing predates the detail, so there is no caveat to raise.
    fresh = AGG.aggregate(None, [], rmap, geoip, run1)
    assert fresh["detail_since"] is None and fresh["monthly"] == []
    assert fresh["schema"] == 2


def test_v2_fold_still_leaks_nothing():
    """LEAK PIN (schema 2). The richer aggregate must still contain no address and no user-agent: the
    network reach proxy is an integer, the API line is a path-class count, and the per-survey volume is
    a byte sum. FAILS IF any new dimension smuggles an identifier into stats.json."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    lines = [_line("/data/products/manifest.json", "203.0.113.5"),
             _line("/data/mtcat.json", "2001:db8:1234::"),
             _line("/data/bundles/sample-survey-tf.h5", "198.51.100.0"),
             _line("/data/catalogue.json", "1.2.3.0")]
    stats = AGG.aggregate(None, lines, rmap, geoip, _RUN)
    assert _sweep_ip_or_ua(json.dumps(stats, indent=1)) == []


# ==================================================================================================
# Australian STATE lane (schema 2, additive): a second-level breakdown BENEATH the AU country row.
#
# State, never city -- the ratified design decision. The address resolved here was already truncated
# at the edge (IPv4 /24, IPv6 /48): a /24 geolocates to a city unreliably (carrier and CGNAT pools
# span a state from one prefix), and in a research community this small a city cell is
# quasi-identifying ("3 downloads from Hobart" names a group). These pins fix state as the grain.
#
# Everything below still derives from the SAME masked address the fold already reads. No new
# collection, no per-individual row, and an absent state table is silently country-only.
# ==================================================================================================
_AU_STATES_CSV = _FIXTURES / "dbip-au-states.sample.csv"

# Fixture addresses, by what the two committed tables say about them:
_AU_NSW = "203.0.113.5"          # country AU, state NSW
_AU_NSW2 = "203.0.113.200"       # country AU, state NSW (a second masked network in the same state)
_AU_NOSTATE = "202.158.4.0"      # country AU, NO row in the state table -> unattributed-state
_AU_WA_V6 = "2400:cb00:1234::"   # country AU (v6 /48), state WA
_NZ = "1.2.3.0"                  # not AU: never reaches the state lookup


def _au_lines():
    """One log window touching every AU state case plus a non-AU control."""
    return [
        _line("/data/edi/sample-survey/Vulcan_A1.edi", _AU_NSW, size=100),
        _line("/data/catalogue.json", _AU_NSW2),
        _line("/data/edi/sample-survey/Vulcan_A2.edi", _AU_NOSTATE, size=200),
        _line("/data/catalogue.json", _AU_WA_V6),
        _line("/data/catalogue.json", _NZ),
    ]


def test_au_state_breakdown_folds_from_the_masked_prefix_at_the_month_and_cumulative_grains():
    """STATE PIN. With the compact state table present, every request that classifies as AU must ALSO
    land in a state bucket -- cumulatively and in its calendar-month rollup, the TWO grains that are
    kept -- with the v6 /48 resolving exactly like the v4 /24. The DAILY grain is deliberately not
    recorded at all (see the no-daily-grain pin below). FAILS IF by_state is absent, if a state is
    misattributed, if a v6 prefix is not resolved, or if a non-AU request is given a state."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    states = AGG.AuStates.load(_AU_STATES_CSV)
    assert states.loaded, "the fixture state table must load"

    stats = AGG.aggregate(None, _au_lines(), rmap, geoip, _RUN, au_states=states)
    assert stats["by_state"] == {"NSW": 2, "WA": 1, "unattributed": 1}, stats["by_state"]
    assert stats["countries"] == {"AU": 4, "NZ": 1}
    month = stats["monthly"][0]
    assert month["by_state"] == {"NSW": 2, "WA": 1, "unattributed": 1}, month["by_state"]
    # A state code is a two/three-letter label, never an address: the leak sweep must still be clean.
    assert _sweep_ip_or_ua(json.dumps(stats, indent=1)) == []


def test_no_day_row_ever_records_a_state_breakdown():
    """NO-DAILY-GRAIN PIN. A day-by-state cell would be the FINEST-grained cell in the whole file, and
    the small-cell argument that rules out a city column rules it out at the daily grain too: a single
    Tasmanian download on a named day is quasi-identifying in a community this size. Nothing renders or
    exports it, so it is not recorded in the first place. FAILS IF any day row gains a `states` key,
    with the state table loaded or without it."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    states = AGG.AuStates.load(_AU_STATES_CSV)
    assert states.loaded, "the fixture state table must load"

    with_table = AGG.aggregate(None, _au_lines(), rmap, geoip, _RUN, au_states=states)
    without = AGG.aggregate(None, _au_lines(), rmap, geoip, _RUN)
    assert with_table["by_state"], "the cumulative breakdown must still be recorded"
    for stats in (with_table, without):
        for day in stats["daily"]:
            assert "states" not in day, f"a day row must carry no state buckets: {day}"


def test_a_prior_file_carrying_legacy_day_states_folds_and_is_left_to_age_out():
    """TOLERANT-READ PIN. A box that folded with the build which briefly wrote a per-day `states` map has
    those keys sitting in its stats.json already. The next fold must read that file without a murmur:
    the legacy key is carried forward EXACTLY as written and ages out with the 92-day daily window
    (rewriting history on upgrade is the one thing this file never does), while no new day row gains
    one. FAILS IF such a file raises, if the legacy key is stripped or mutated, or if the daily grain
    starts being written again."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    states = AGG.AuStates.load(_AU_STATES_CSV)
    run1 = dt.datetime(2026, 6, 2, 3, 30, tzinfo=dt.timezone.utc)   # folds up to 2026-06-01
    run2 = dt.datetime(2026, 6, 4, 3, 30, tzinfo=dt.timezone.utc)   # folds up to 2026-06-03

    s1 = AGG.aggregate(None, [_line("/data/catalogue.json", _AU_NSW, date="2026-06-01")],
                       rmap, geoip, run1, au_states=states)
    s1["daily"][0]["states"] = {"NSW": 1}                    # exactly what the pre-drop code wrote
    s1 = json.loads(json.dumps(s1))                          # round-trip: a real file read off disk

    s2 = AGG.aggregate(s1, [_line("/data/catalogue.json", _AU_WA_V6, date="2026-06-03")],
                       rmap, geoip, run2, au_states=states)
    rows = {d["date"]: d for d in s2["daily"]}
    assert rows["2026-06-01"]["states"] == {"NSW": 1}, "a legacy key is left exactly as it was written"
    assert "states" not in rows["2026-06-03"], "the newly folded day must not gain a states key"
    assert s2["by_state"] == {"NSW": 1, "WA": 1}, s2["by_state"]


def test_au_state_rows_plus_unattributed_reconcile_with_the_country_row():
    """RECONCILIATION PIN. The state breakdown sits BENEATH the AU country row, so the state counts plus
    the explicit unattributed bucket must equal the AU country figure exactly -- an AU prefix the table
    does not cover is BUCKETED, never dropped. FAILS IF the two totals disagree (a dropped prefix would
    make the screen's breakdown quietly under-report its own parent row)."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    states = AGG.AuStates.load(_AU_STATES_CSV)
    lines = _au_lines() + [
        _line("/data/edi/sample-survey/Vulcan_A1.edi", _AU_NOSTATE, size=5),   # a 2nd uncovered AU hit
        _line("/data/mtcat.json", _AU_NSW),                    # api: a geo class like every other
    ]
    stats = AGG.aggregate(None, lines, rmap, geoip, _RUN, au_states=states)
    au = stats["countries"]["AU"]
    assert sum(stats["by_state"].values()) == au, (stats["by_state"], au)
    assert stats["by_state"]["unattributed"] == 2, "an uncovered AU prefix must be bucketed, not dropped"
    for m in stats["monthly"]:
        assert sum(m["by_state"].values()) == m["countries"]["AU"], m


def test_absent_state_table_degrades_silently_to_country_only():
    """TOLERANCE PIN. The state table is an OPTIONAL input like every other: absent, unreadable or
    empty, the fold must behave exactly as it does today -- countries counted, no state buckets, no
    warning, no crash. FAILS IF a missing table changes any country/download figure, invents an empty
    state bucket, or raises."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    baseline = AGG.aggregate(None, _au_lines(), rmap, geoip, _RUN)          # no au_states at all
    missing = AGG.AuStates.load(_FIXTURES / "no-such-state-table.csv")
    assert not missing.loaded and missing.state(_AU_NSW) is None
    with_missing = AGG.aggregate(None, _au_lines(), rmap, geoip, _RUN, au_states=missing)

    for stats in (baseline, with_missing):
        assert stats["countries"] == {"AU": 4, "NZ": 1}
        assert stats["totals"]["downloads"] == 2
        assert stats["by_state"] == {}, "no table means no state buckets, not empty-labelled ones"
        assert stats["monthly"][0]["by_state"] == {}
        assert "states" not in stats["daily"][0], "no day row carries state buckets, table or no table"


def test_state_data_is_forward_only_and_never_backfills_a_folded_day():
    """FORWARD-ONLY PIN. Months folded before the state table was installed carry NO state data and must
    stay that way: installing the table later must not rewrite an existing daily row, invent state
    counts for an earlier month, or make the cumulative breakdown claim to cover the whole history.
    FAILS IF a day row gains a states key, if an earlier month gains state counts, or if the cumulative
    state total silently claims every AU request ever counted."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    states = AGG.AuStates.load(_AU_STATES_CSV)
    run1 = dt.datetime(2026, 6, 2, 3, 30, tzinfo=dt.timezone.utc)   # folds up to 2026-06-01
    run2 = dt.datetime(2026, 7, 12, 3, 30, tzinfo=dt.timezone.utc)  # folds up to 2026-07-11

    before = [_line("/data/catalogue.json", _AU_NSW, date="2026-06-01"),
              _line("/data/catalogue.json", _AU_NSW2, date="2026-06-01")]
    after = [_line("/data/catalogue.json", _AU_WA_V6, date="2026-07-10")]
    s1 = AGG.aggregate(None, before, rmap, geoip, run1)                        # no table yet
    s2 = AGG.aggregate(s1, after, rmap, geoip, run2, au_states=states)         # table installed

    june = [d for d in s2["daily"] if d["date"] == "2026-06-01"][0]
    assert "states" not in june, "no day row records state buckets, and none is ever backfilled"
    months = {m["month"]: m for m in s2["monthly"]}
    assert months["2026-06"]["by_state"] == {}, "an earlier month must not gain state counts"
    assert months["2026-07"]["by_state"] == {"WA": 1}
    # The cumulative breakdown covers only what was counted with the table in place; the difference
    # against the AU country row is real and is what the screen names rather than hides.
    assert s2["countries"]["AU"] == 3
    assert s2["by_state"] == {"WA": 1}
    assert sum(s2["by_state"].values()) < s2["countries"]["AU"]


def test_state_table_rejects_anything_that_is_not_one_of_the_eight_codes():
    """VOCABULARY PIN. The fold accepts only the eight state/territory codes from the table file, so a
    hand-edited or mangled table cannot push an arbitrary label onto the analytics screen. FAILS IF a
    junk code, a city name, or a lowercase stray is accepted as a state."""
    assert set(AGG.AU_STATE_CODES) == {"NSW", "VIC", "QLD", "SA", "WA", "TAS", "NT", "ACT"}
    t = _FIXTURES.parent / "_junk-states.csv"
    try:
        t.write_text("203.0.113.0,203.0.113.255,Hobart\n"
                     "192.0.2.0,192.0.2.255,<script>\n"
                     "1.0.0.0,1.0.0.255,qld\n", encoding="utf-8")
        table = AGG.AuStates.load(t)
        assert table.state("203.0.113.5") is None, "a city name is not a state code"
        assert table.state("192.0.2.1") is None, "junk must never reach the screen"
        assert table.state("1.0.0.1") == "QLD", "a lowercase code is normalised, not rejected"
    finally:
        t.unlink(missing_ok=True)


def test_main_wires_the_state_table_through_the_env(tmp_path, monkeypatch):
    """WIRING PIN. main() must find the state table by env (or the documented default beside the
    country CSV) and fold state buckets into the written stats.json. FAILS IF the table is read but
    never reaches the fold, or if the env override is ignored."""
    data = tmp_path / "data"
    logdir = data / "logs" / "caddy"
    state = data / "gateway" / "state"
    logdir.mkdir(parents=True)
    state.mkdir(parents=True)
    (logdir / "access.json").write_text("\n".join([
        _line("/data/edi/sample-survey/Vulcan_A1.edi", _AU_NSW),
        _line("/data/catalogue.json", _AU_WA_V6),
        _line("/data/catalogue.json", _NZ),
    ]) + "\n", encoding="utf-8")
    stats_file = state / "stats.json"

    monkeypatch.setenv("AUSMT_DATA_DIR", str(data))
    monkeypatch.setenv("AUSMT_STATS_MANIFEST", str(_MANIFEST))
    monkeypatch.setenv("AUSMT_STATS_DBIP_CSV", str(_DBIP))
    monkeypatch.setenv("AUSMT_STATS_AU_STATES_CSV", str(_AU_STATES_CSV))
    monkeypatch.setenv("AUSMT_STATS_FILE", str(stats_file))
    monkeypatch.setenv("AUSMT_STATS_NOW", "2026-07-12T03:30:00Z")

    assert AGG.main([]) == 0
    doc = json.loads(stats_file.read_text(encoding="utf-8"))
    assert doc["by_state"] == {"NSW": 1, "WA": 1}
    assert doc["countries"]["AU"] == 2 and doc["countries"]["NZ"] == 1
    assert _sweep_ip_or_ua(stats_file.read_text(encoding="utf-8")) == []

    # And with the override removed the DEFAULT path (beside the country CSV under the data dir) is
    # what is consulted -- absent there, the run is country-only and still exits 0.
    monkeypatch.delenv("AUSMT_STATS_AU_STATES_CSV")
    assert AGG.main([]) == 0


# ==================================================================================================
# Counting-honesty lane: what the numbers actually mean.
#
# Five defects shared one root: the fold's admission rules were written for "a person in a browser"
# and every other real client was either dropped or double counted.
#   * a THREE-WAY client class replaces the bot/not-bot binary. Crawlers are still excluded; SCRIPTED
#     clients (curl, wget, python-requests, and an ABSENT user-agent) are counted and reported
#     separately, because those are exactly the clients the public API documentation teaches;
#   * a download admits status 206 as well as 200, so a resumed or ranged transfer stops vanishing;
#   * within one folded day the same (masked network, path) counts ONCE, which kills the verified
#     abort-then-refetch double count, while the bytes of every line still sum;
#   * the served JSON Schema is an API path, and release-tier bundles are downloads;
#   * the LICENSE sidecars beside each survey MTH5 are not data downloads and stop polluting
#     `unattributed`, which exists to detect build/serve skew.
# Every dimension is still derived from what the fold already reads. Nothing new is collected.
# ==================================================================================================

def test_client_classes_split_crawlers_from_scripted_consumers_from_browsers():
    """CLIENT-CLASS PIN. The user-agent must resolve to exactly one of three classes. A crawler is
    excluded from every count as it always was; a SCRIPTED client is counted, because curl, wget and
    python-requests are the clients the published API examples hand people, and dropping them as bots
    made programmatic scientific use invisible; an ABSENT user-agent is scripted, not human. FAILS IF a
    crawler is admitted, if a documented scripting client is still classed as a crawler, or if a blank
    UA is treated as a browser."""
    for ua in ("Googlebot/2.1", "Mozilla/5.0 (compatible; AhrefsBot/7.0)", "Bytespider",
               "facebookexternalhit/1.1", "HeadlessChrome/120.0", "Scrapy/2.11",
               "zgrab/0.x", "uptime-kuma/1.23", "Datadog/monitoring"):
        assert AGG.classify_client(ua) == "crawler", ua
    for ua in ("curl/8.4.0", "Wget/1.21.4", "python-requests/2.31.0", "Python-urllib/3.12",
               "Go-http-client/2.0", "okhttp/4.12.0", "Java/17.0.9", "axios/1.6.2",
               "node-fetch/3.3", "libwww-perl/6.68", "aria2/1.36.0",
               "Apache-HttpClient/5.3", "python-httpx/0.27.0", "", "   "):
        assert AGG.classify_client(ua) == "scripted", repr(ua)
    for ua in ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
               "Mozilla/5.0 (Macintosh) AppleWebKit/605.1.15 Version/17.0 Safari/605.1.15"):
        assert AGG.classify_client(ua) == "browser", ua


def test_scripted_clients_are_counted_and_reported_beside_browsers():
    """SCRIPTED-COUNTING PIN. A download by curl / wget / python-requests must reach the totals AND be
    attributed to a survey exactly like a browser download, with the browser-vs-scripted split written
    at the cumulative and month grains. A crawler must still change nothing at all. FAILS IF a scripted
    download is dropped, if it is folded into the browser figure with no way to tell them apart, or if
    a crawler is admitted."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    lines = [
        _line("/data/edi/sample-survey/Vulcan_A1.edi", "203.0.113.5", size=100),
        _line("/data/edi/sample-survey/Vulcan_A2.edi", "1.2.3.0", size=200, ua="curl/8.4.0"),
        _line("/data/xml/sample-survey/A1.xml", "198.51.100.0", size=300, ua=""),
        _line("/data/catalogue.json", "8.8.8.0", ua="python-requests/2.31.0"),
        _line("/data/edi/sample-survey/Vulcan_A1.edi", "2001:db8::", ua="Googlebot/2.1"),
        _line("/data/catalogue.json", "2001:db8::", ua="Googlebot/2.1"),
    ]
    stats = AGG.aggregate(None, lines, rmap, geoip, _RUN)
    assert stats["totals"]["downloads"] == 3, "the curl and blank-UA downloads must count"
    assert stats["totals"]["visits"] == 1, "the python-requests catalogue fetch is a real visit"
    assert stats["totals"]["downloads_by_client"] == {"browser": 1, "scripted": 2}
    assert stats["monthly"][0]["downloads_by_client"] == {"browser": 1, "scripted": 2}
    assert stats["downloads"]["by_survey"]["CI Sample Survey"]["downloads"] == 3
    assert "crawler" not in stats["totals"]["downloads_by_client"], \
        "a crawler is excluded, never reported as a counted class"


def test_a_v2_file_without_the_client_split_gains_it_forward_only():
    """CLIENT-SPLIT MIGRATION PIN. A stats.json written before the split existed must read back cleanly
    and start accruing the new counters from the next fold, with no attempt to divide its historical
    downloads between the two classes. FAILS IF an older file raises, or if the split claims to cover
    downloads that were counted before it existed."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    prior = AGG.aggregate(None, [_line("/data/edi/sample-survey/Vulcan_A1.edi", "203.0.113.5",
                                       date="2026-07-09")], rmap, geoip,
                          dt.datetime(2026, 7, 10, 3, 30, tzinfo=dt.timezone.utc))
    prior["totals"].pop("downloads_by_client")
    for m in prior["monthly"]:
        m.pop("downloads_by_client")
    prior = json.loads(json.dumps(prior))
    after = AGG.aggregate(prior, [_line("/data/xml/sample-survey/A1.xml", "1.2.3.0",
                                        date="2026-07-10", ua="curl/8.4.0")], rmap, geoip, _RUN)
    assert after["totals"]["downloads"] == 2, "the historical download is not lost"
    assert after["totals"]["downloads_by_client"] == {"scripted": 1}, \
        "only downloads folded with the split in place may appear in it"


def test_a_ranged_or_resumed_download_is_counted():
    """206 PIN. Caddy's file_server advertises byte ranges and the MTH5 bundles are the largest things
    served, so a download manager, `curl -C -` or aria2 gets 206 Partial Content. Admitting only 200
    made those downloads vanish entirely, not merely undercount their bytes. FAILS IF a 206 download is
    dropped, or if 206 leaks into the visit/API classes (which are cache-revalidation shaped, not
    range shaped)."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    lines = [
        _line("/data/bundles/sample-survey-tf.h5", "203.0.113.5", status=206, size=4000),
        _line("/data/edi/sample-survey/Vulcan_A1.edi", "1.2.3.0", status=404, size=0),
        _line("/data/catalogue.json", "198.51.100.0", status=206),
    ]
    stats = AGG.aggregate(None, lines, rmap, geoip, _RUN)
    assert stats["totals"]["downloads"] == 1, "the 206 download counts; the 404 does not"
    assert stats["totals"]["download_bytes"] == 4000
    assert stats["totals"]["visits"] == 0, "a 206 is not a visit shape"
    assert stats["downloads"]["by_format"] == {"mth5": 1}


def test_within_a_day_the_same_network_and_path_counts_once_while_bytes_still_sum():
    """WITHIN-DAY DEDUPE PIN. The browser download hand-off logs the SAME 200 GET twice for one user
    action: the renderer sees Content-Disposition and cancels (a 0-byte line), the download manager
    refetches (the full line). Range fragments do the same. Within one folded day an identical (masked
    network, path) therefore counts ONCE, while every line's bytes still sum so the volume stays true.
    FAILS IF the double count survives, if the deduped line's bytes are lost, if two DIFFERENT networks
    fetching the same file collapse into one, or if the dedupe leaks across days."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    lines = [
        # One user action, two logged lines: the cancelled leg then the refetch.
        _line("/data/bundles/sample-survey-tf.h5", "203.0.113.5", size=0, date="2026-07-09"),
        _line("/data/bundles/sample-survey-tf.h5", "203.0.113.5", size=5000, date="2026-07-09"),
        # Two range fragments of one transfer.
        _line("/data/bundles/sample-survey-edi.zip", "203.0.113.5", status=206, size=300,
              date="2026-07-09"),
        _line("/data/bundles/sample-survey-edi.zip", "203.0.113.5", status=206, size=700,
              date="2026-07-09"),
        # A DIFFERENT network fetching the same file is a different download.
        _line("/data/bundles/sample-survey-tf.h5", "1.2.3.0", size=5000, date="2026-07-09"),
        # The same network and path on the NEXT day is a new download.
        _line("/data/bundles/sample-survey-tf.h5", "203.0.113.5", size=5000, date="2026-07-10"),
    ]
    stats = AGG.aggregate(None, lines, rmap, geoip, _RUN)
    assert stats["totals"]["downloads"] == 4, "6 lines, 4 distinct (day, network, path) downloads"
    assert stats["totals"]["download_bytes"] == 0 + 5000 + 300 + 700 + 5000 + 5000
    ds = stats["downloads"]["by_dataset"]
    assert ds["bundles/sample-survey-tf.h5"]["downloads"] == 3
    assert ds["bundles/sample-survey-tf.h5"]["bytes"] == 15000
    assert ds["bundles/sample-survey-edi.zip"]["downloads"] == 1, "the range fragments are one download"
    assert ds["bundles/sample-survey-edi.zip"]["bytes"] == 1000, "both fragments' bytes still sum"
    assert stats["downloads"]["by_format"] == {"mth5": 3, "edi-zip": 1}
    daily = {d["date"]: d for d in stats["daily"]}
    assert daily["2026-07-09"]["downloads"] == 3 and daily["2026-07-09"]["download_bytes"] == 11000
    assert daily["2026-07-10"]["downloads"] == 1
    assert stats["downloads"]["by_survey"]["CI Sample Survey"] == {"downloads": 4, "bytes": 16000,
                                                                  "countries": ["AU", "NZ"],
                                                                  "files": 0, "bundles": 4}


def test_visits_and_api_requests_are_not_deduped():
    """DEDUPE SCOPE PIN. The dedupe exists because ONE download action can log two lines; a portal boot
    and an API fetch have no such duplication, and each really is another use. They must be counted
    every time. FAILS IF the dedupe is applied to the visit or API class, which would silently turn the
    visit metric into a distinct-network-per-day count."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    lines = ([_line("/data/catalogue.json", "203.0.113.5")] * 3
             + [_line("/data/mtcat.json", "203.0.113.5")] * 2)
    stats = AGG.aggregate(None, lines, rmap, geoip, _RUN)
    assert stats["totals"]["visits"] == 3, "each SPA boot is a visit"
    assert stats["totals"]["api_requests"] == 2


def test_the_served_json_schema_is_an_api_path():
    """SCHEMA-PATH PIN. /data/mtcat.schema.json is the `$id` every validator and harvester resolves
    when it reads the MTCAT document, which makes it the cleanest programmatic-consumer signal the
    corpus has, and it was counted nowhere. It must classify as `api`. FAILS IF the schema fetch is
    still ignored, or if it is mistaken for a download or a visit."""
    assert AGG.classify("/data/mtcat.schema.json") == ("api", None)
    assert "/data/mtcat.schema.json" in AGG._API_PATHS
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    stats = AGG.aggregate(None, [_line("/data/mtcat.schema.json", "8.8.8.0", ua="python-httpx/0.27")],
                          rmap, AGG.GeoIP.load(_DBIP), _RUN)
    assert stats["totals"]["api_requests"] == 1
    assert stats["totals"]["visits"] == 0 and stats["totals"]["downloads"] == 0


def test_the_served_stations_geojson_is_an_api_path():
    """GEOJSON-PATH PIN (owner ruling 2026-08-02). /data/stations.geojson is the corpus as a vector
    layer: a GIS user adds it as a layer straight from the URL, and the portal's own JavaScript never
    fetches it, so every hit is a third party reading the corpus programmatically. It is the fourth
    documented machine-readable entry point and must classify as `api`. FAILS IF the new document is
    counted nowhere (which is what would happen by default: `.geojson` is not a download family and
    would fall through to `ignore`), or if it is mistaken for a download or a visit."""
    assert AGG.classify("/data/stations.geojson") == ("api", None)
    assert "/data/stations.geojson" in AGG._API_PATHS
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    stats = AGG.aggregate(None, [_line("/data/stations.geojson", "8.8.8.0", ua="QGIS/3.34")],
                          rmap, AGG.GeoIP.load(_DBIP), _RUN)
    assert stats["totals"]["api_requests"] == 1
    assert stats["totals"]["visits"] == 0 and stats["totals"]["downloads"] == 0


def test_the_published_api_line_copy_counts_what_the_code_counts():
    """API-SURFACE COPY PIN (aggregator half). Two published descriptions state the scope of the API
    line in words: the operator runbook (deploy/README.md) and the public analytics page
    (docs/docs/introduction/usage-analytics.md). Both name the entry points one by one and both spell
    out how many there are, so a path added to _API_PATHS without the copy moving leaves two documents
    understating a figure a custodian is asked to trust. FAILS IF either page omits a path that is in
    _API_PATHS, or still says 'three documented' now that there are four.

    The word is derived from len(_API_PATHS), never hard-coded, so a fifth entry point fails this pin
    rather than silently passing a stale 'four'."""
    _count_word = {2: "two", 3: "three", 4: "four", 5: "five"}[len(AGG._API_PATHS)]
    for page in (_REPO / "deploy" / "README.md",
                 _REPO / "docs" / "docs" / "introduction" / "usage-analytics.md"):
        text = page.read_text(encoding="utf-8")
        assert f"{_count_word} documented machine-readable entry points" in text, (
            f"{page.name} must say '{_count_word} documented machine-readable entry points'")
        for path in AGG._API_PATHS:
            assert path in text, f"{page.name} does not name the API path {path}"


def test_api_requests_are_counted_geographically_like_every_other_request():
    """API GEO PIN. The country table is the reach evidence, and the API line was the one counted class
    that never reached it, so any reach claim built from countries excluded programmatic consumers
    entirely. An API request must count toward its country and, for AU, its state, exactly as a
    download or a visit does. FAILS IF an API request adds no country, or if it adds a country without
    the matching state bucket (which would break the reconciliation the state table promises)."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    states = AGG.AuStates.load(_AU_STATES_CSV)
    lines = [_line("/data/products/manifest.json", _AU_NSW),
             _line("/data/mtcat.schema.json", _AU_WA_V6),
             _line("/data/mtcat.json", _NZ)]
    stats = AGG.aggregate(None, lines, rmap, geoip, _RUN, au_states=states)
    assert stats["totals"]["api_requests"] == 3
    assert stats["countries"] == {"AU": 2, "NZ": 1}
    assert stats["by_state"] == {"NSW": 1, "WA": 1}
    assert sum(stats["by_state"].values()) == stats["countries"]["AU"]
    month = stats["monthly"][0]
    assert sum(month["by_state"].values()) == month["countries"]["AU"]


def test_the_country_total_equals_every_counted_request():
    """GEO SCOPE PIN. After the API class joined the geo count, the country map must total EXACTLY the
    counted downloads plus visits plus API requests, so the screen's caption can state its scope and be
    true. In particular a download that the within-day dedupe collapsed must not leave a stray country
    behind it. FAILS IF the identity breaks in either direction."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    lines = [
        _line("/data/bundles/sample-survey-tf.h5", "203.0.113.5", size=0),
        _line("/data/bundles/sample-survey-tf.h5", "203.0.113.5", size=900),   # the same action
        _line("/data/catalogue.json", "203.0.113.5"),
        _line("/data/catalogue.json", "1.2.3.0"),
        _line("/data/mtcat.schema.json", "198.51.100.0"),
    ]
    stats = AGG.aggregate(None, lines, rmap, geoip, _RUN)
    t = stats["totals"]
    assert sum(stats["countries"].values()) == t["downloads"] + t["visits"] + t["api_requests"]
    assert t["downloads"] == 1, "the abort-then-refetch pair is one download"
    assert sum(stats["monthly"][0]["countries"].values()) == 4


def test_release_tier_bundles_count_and_attribute_by_bundle_filename():
    """RELEASE-TIER PIN. A cut release freezes the citable copy of a bundle under
    /data/releases/<tag>/bundles/, and that is the copy a paper's DOI resolves to, yet the whole family
    classified as `ignore`: the archival download produced no analytics at all while its mutable twin
    under /data/bundles/ was counted. A release bundle must count as a download and attribute to its
    survey by bundle FILENAME against the live manifest; an unmatched filename lands in `unattributed`
    like any other unknown download. The small release JSONs stay uncounted. FAILS IF a release bundle
    is dropped, misattributed, or if the release metadata documents start counting as downloads."""
    assert AGG.classify("/data/releases/v1.2.0/bundles/sample-survey-tf.h5") == (
        "download", "releases/v1.2.0/bundles/sample-survey-tf.h5")
    for ignored in ("/data/releases/releases.json", "/data/releases/v1.2.0/release.json",
                    "/data/releases/v1.2.0/datacite.json", "/data/releases/v1.2.0/mtcat.json",
                    "/data/releases/v1.2.0/bundles"):
        assert AGG.classify(ignored) == ("ignore", None), ignored

    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    lines = [_line("/data/releases/v1.2.0/bundles/sample-survey-tf.h5", "203.0.113.5", size=700),
             _line("/data/releases/v1.2.0/bundles/gone-from-the-manifest.zip", "1.2.3.0", size=9)]
    stats = AGG.aggregate(None, lines, rmap, geoip, _RUN)
    assert stats["totals"]["downloads"] == 2
    assert stats["totals"]["unattributed"] == 1, "an unmatched release bundle is bucketed, not dropped"
    assert stats["downloads"]["by_format"] == {"mth5": 1, "unattributed": 1}
    assert stats["downloads"]["by_kind"] == {"bundle": 1, "unattributed": 1}
    assert stats["downloads"]["by_survey"]["CI Sample Survey"] == {"downloads": 1, "bytes": 700,
                                                                  "countries": ["AU"],
                                                                  "files": 0, "bundles": 1}
    row = stats["downloads"]["by_dataset"]["releases/v1.2.0/bundles/sample-survey-tf.h5"]
    assert row["slug"] == "sample-survey" and row["format"] == "mth5" and row["kind"] == "bundle"
    assert "bundles/sample-survey-tf.h5" not in stats["downloads"]["by_dataset"], \
        "the frozen release copy keeps its own row rather than merging into the live one"


def test_licence_sidecars_beside_a_bundle_are_not_data_downloads():
    """SIDECAR PIN. build_portal writes bundles/<slug>-tf.LICENSE.txt beside every survey MTH5 and adds
    no manifest row for it, so every fetch of one landed in `unattributed`. That bucket exists to
    detect build/serve skew, and nineteen structural sidecars drown the signal it is there to give.
    A licence sidecar is boilerplate travelling with the bytes, not a data download, so it is ignored.
    FAILS IF a sidecar is counted at all, or if the exclusion over-reaches onto a real bundle."""
    assert AGG.classify("/data/bundles/sample-survey-tf.LICENSE.txt") == ("ignore", None)
    assert AGG.classify("/data/releases/v1.2.0/bundles/sample-survey-tf.LICENSE.txt") == \
        ("ignore", None)
    assert AGG.classify("/data/bundles/sample-survey-tf.h5")[0] == "download"
    assert AGG.classify("/data/edi/sample-survey/Vulcan_A1.edi")[0] == "download"

    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    stats = AGG.aggregate(None, [_line("/data/bundles/sample-survey-tf.LICENSE.txt", "203.0.113.5")],
                          rmap, AGG.GeoIP.load(_DBIP), _RUN)
    assert stats["totals"]["downloads"] == 0 and stats["totals"]["unattributed"] == 0
    assert stats["countries"] == {}, "an ignored path is dropped before any counter is touched"


def test_each_month_records_how_many_of_its_days_carried_geo():
    """GEO-DAYS PIN. Per-month country counts are forward-only, so a month can hold a full download
    figure and one day's worth of countries, and an export built from it looks internally consistent
    while under-reporting. Each month must therefore record how many folded days actually contributed
    geo, so the partiality is machine-visible and not a matter of reading prose. FAILS IF the counter
    is absent, counts days with no geo, or double counts a day across runs."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    run1 = dt.datetime(2026, 7, 10, 3, 30, tzinfo=dt.timezone.utc)
    s1 = AGG.aggregate(None, [_line("/data/catalogue.json", "203.0.113.5", date="2026-07-08"),
                              _line("/data/catalogue.json", "1.2.3.0", date="2026-07-09")],
                       rmap, geoip, run1)
    assert s1["monthly"][0]["geo_days"] == 2
    s2 = AGG.aggregate(s1, [_line("/data/catalogue.json", "203.0.113.5", date="2026-07-10")],
                       rmap, geoip, _RUN)
    assert s2["monthly"][0]["geo_days"] == 3, "a later fold adds only its own new days"
    s3 = AGG.aggregate(s2, [], rmap, geoip, _RUN)
    assert s3["monthly"][0]["geo_days"] == 3, "a re-run must not re-count a folded day"
    # A month seeded from a v1 daily tail carries days it has no geo for: that is the whole point.
    seeded = AGG.aggregate(_v1_stats(), [], rmap, geoip,
                           dt.datetime(2026, 7, 11, 3, 30, tzinfo=dt.timezone.utc))
    assert seeded["monthly"][0]["days"] == 2 and seeded["monthly"][0]["geo_days"] == 0


def test_each_month_records_how_many_days_carried_the_current_dimensions():
    """CURRENT-DETAIL PIN. This file has TWO forward-only seams, not one. `seeded_days` marks the
    first (days carried over from a v1 daily tail). A month folded AFTER that upgrade but BEFORE the
    client split, the monthly network peak, the per-survey country list and the within-day download
    dedupe existed sits between them: real volume, real formats, none of those. Without a counter for
    the second seam the screen cannot tell such a month from one that measured them and saw nothing,
    and it renders a fabricated zero. Each month must therefore record how many of its days were
    folded with the current dimensions in place. FAILS IF the counter is absent, counts a day this
    fold did not fold, double counts a day across runs, or credits days carried in from an older
    file."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    run1 = dt.datetime(2026, 7, 10, 3, 30, tzinfo=dt.timezone.utc)
    s1 = AGG.aggregate(None, [_line("/data/catalogue.json", "203.0.113.5", date="2026-07-08"),
                              _line("/data/catalogue.json", "1.2.3.0", date="2026-07-09")],
                       rmap, geoip, run1)
    assert s1["monthly"][0]["detail_days"] == 2 == s1["monthly"][0]["days"], \
        "every day this fold folds is folded with every dimension it knows about"
    s2 = AGG.aggregate(s1, [_line("/data/catalogue.json", "203.0.113.5", date="2026-07-10")],
                       rmap, geoip, _RUN)
    assert s2["monthly"][0]["detail_days"] == 3, "a later fold adds only its own new days"
    s3 = AGG.aggregate(s2, [], rmap, geoip, _RUN)
    assert s3["monthly"][0]["detail_days"] == 3, "a re-run must not re-count a folded day"
    # THE CASE THE SCREEN NEEDS: a month carried in from a file written before these dimensions. Its
    # twenty folded days are real and stay real; only the day THIS fold adds carries the detail.
    prior = {"schema": 2, "last_folded_date": "2026-07-09", "since": "2026-07-01",
             "totals": {"downloads": 30, "visits": 90, "download_bytes": 1048576, "unattributed": 0,
                        "api_requests": 12},
             "downloads": {"by_format": {}, "by_survey": {}, "by_dataset": {}, "by_kind": {}},
             "countries": {"AU": 60}, "daily": [],
             "monthly": [{"month": "2026-07", "downloads": 30, "visits": 90, "days": 20,
                          "seeded_days": 0, "download_bytes": 1048576, "api_requests": 12}]}
    mixed = AGG.aggregate(prior, [_line("/data/catalogue.json", "203.0.113.5", date="2026-07-10")],
                          rmap, geoip, _RUN)
    row = mixed["monthly"][0]
    assert row["days"] == 21, "the days folded before are not forgotten"
    assert row["detail_days"] == 1, "only the day folded with the dimensions in place carries them"
    assert row["seeded_days"] == 0, "the second seam is not the first one and must not borrow it"


def test_the_honesty_lane_still_leaks_nothing():
    """LEAK PIN (counting-honesty lane). The new dimensions are a client class label, a status code, a
    run-local dedupe set and a per-month day count: none of them may put an address or a user-agent
    into stats.json. The dedupe key in particular is built FROM the masked network and must stay in
    memory. FAILS IF any of it reaches the emitted file."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    states = AGG.AuStates.load(_AU_STATES_CSV)
    lines = [
        _line("/data/bundles/sample-survey-tf.h5", "203.0.113.5", size=0),
        _line("/data/bundles/sample-survey-tf.h5", "203.0.113.5", size=900),
        _line("/data/edi/sample-survey/Vulcan_A1.edi", "2001:db8:1234::", status=206,
              ua="curl/8.4.0"),
        _line("/data/mtcat.schema.json", "198.51.100.0", ua="python-requests/2.31.0"),
        _line("/data/releases/v1.2.0/bundles/sample-survey-edi.zip", "1.2.3.0", ua=""),
        _line("/data/catalogue.json", "203.0.113.5", ua="Googlebot/2.1"),
    ]
    stats = AGG.aggregate(None, lines, rmap, geoip, _RUN, au_states=states)
    emitted = json.dumps(stats, indent=1)
    assert _sweep_ip_or_ua(emitted) == [], emitted
    assert "downloads_by_client" in stats["totals"]


# ==================================================================================================
# State and funding detail: what a report is actually asked for.
#
# The existing by_state map answers "how many requests from each state" and the reconciliation rows
# depend on it, so it is untouched. Beside it now sits a PARALLEL detail map answering "how many
# DOWNLOADS, how many visits, how much VOLUME", plus the per-survey country count behind the custodian
# promise ("downloaded N times from M countries"), a monthly reach figure that can survive the 92-day
# daily window, and the denominator that turns "12 surveys downloaded" into "12 of 40 served".
#
# All of it forward-only, all of it at the two grains that are kept, and none of it at day-by-state or
# city grain: those exclusions are ratified and the pins above hold them.
# ==================================================================================================

def test_state_rows_carry_downloads_visits_api_and_volume_beside_the_request_count():
    """STATE DETAIL PIN. A funding report asks how much was DOWNLOADED from a state and how many bytes
    that was, not merely how many requests it made. A parallel by_state_detail map must record
    downloads, visits, API requests and bytes per state, at the cumulative and month grains, including
    the uncovered-prefix bucket. FAILS IF the detail is absent, if a metric lands in the wrong column,
    if bytes are credited to a non-download class, or if the two grains disagree."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    states = AGG.AuStates.load(_AU_STATES_CSV)
    lines = [
        _line("/data/edi/sample-survey/Vulcan_A1.edi", _AU_NSW, size=100),
        _line("/data/bundles/sample-survey-tf.h5", _AU_NSW2, size=900),
        _line("/data/catalogue.json", _AU_NSW),
        _line("/data/mtcat.schema.json", _AU_WA_V6),
        _line("/data/edi/sample-survey/Vulcan_A2.edi", _AU_NOSTATE, size=7),
        _line("/data/catalogue.json", _NZ),
    ]
    stats = AGG.aggregate(None, lines, rmap, geoip, _RUN, au_states=states)
    detail = stats["by_state_detail"]
    assert detail["NSW"] == {"downloads": 2, "visits": 1, "api": 0, "bytes": 1000}
    assert detail["WA"] == {"downloads": 0, "visits": 0, "api": 1, "bytes": 0}
    assert detail["unattributed"] == {"downloads": 1, "visits": 0, "api": 0, "bytes": 7}
    assert "NZ" not in detail and "AU" not in detail, "the detail is a breakdown BENEATH the AU row"
    assert stats["monthly"][0]["by_state_detail"] == detail, \
        "the month grain must agree with the cumulative one over a single-month window"
    # The request map the reconciliation rows depend on is untouched, and the two agree.
    assert stats["by_state"] == {"NSW": 3, "WA": 1, "unattributed": 1}
    for code, row in detail.items():
        assert row["downloads"] + row["visits"] + row["api"] == stats["by_state"][code], code


def test_state_detail_is_forward_only_and_never_reaches_a_day_row():
    """STATE DETAIL SCOPE PIN. The detail map is a new dimension and obeys every rule the request map
    already does: it starts at the fold that first wrote it, no earlier month gains it, and it exists at
    the cumulative and month grains ONLY. A day-by-state cell is the finest cell in the file and the
    small-cell argument that rules out a city rules it out too. FAILS IF an earlier month is backfilled,
    if a day row gains state detail, or if an older file cannot be read."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    states = AGG.AuStates.load(_AU_STATES_CSV)
    run1 = dt.datetime(2026, 6, 2, 3, 30, tzinfo=dt.timezone.utc)
    run2 = dt.datetime(2026, 7, 12, 3, 30, tzinfo=dt.timezone.utc)
    s1 = AGG.aggregate(None, [_line("/data/catalogue.json", _AU_NSW, date="2026-06-01")],
                       rmap, geoip, run1, au_states=states)
    # A file written before the detail map existed, read back off disk.
    s1.pop("by_state_detail")
    for m in s1["monthly"]:
        m.pop("by_state_detail")
    s1 = json.loads(json.dumps(s1))

    s2 = AGG.aggregate(s1, [_line("/data/catalogue.json", _AU_WA_V6, date="2026-07-10")],
                       rmap, geoip, run2, au_states=states)
    months = {m["month"]: m for m in s2["monthly"]}
    assert months["2026-06"]["by_state_detail"] == {}, "an earlier month must not be backfilled"
    assert months["2026-06"]["by_state"] == {"NSW": 1}, "its request map is untouched"
    assert months["2026-07"]["by_state_detail"] == {
        "WA": {"downloads": 0, "visits": 1, "api": 0, "bytes": 0}}
    assert s2["by_state_detail"] == {"WA": {"downloads": 0, "visits": 1, "api": 0, "bytes": 0}}
    for day in s2["daily"]:
        assert "states" not in day and "by_state_detail" not in day, day


def test_no_state_table_means_no_state_detail_either():
    """STATE DETAIL TOLERANCE PIN. The detail map is conditional on exactly the same optional input as
    the request map: no state table, no buckets at all, no empty-labelled zeroes. FAILS IF a box with no
    table starts emitting a detail map, which would render as measured zeroes for every state."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    stats = AGG.aggregate(None, _au_lines(), rmap, geoip, _RUN)
    assert stats["by_state_detail"] == {} and stats["monthly"][0]["by_state_detail"] == {}
    assert stats["countries"] == {"AU": 4, "NZ": 1}, "the country figures are unaffected"


def test_each_survey_accumulates_the_countries_that_downloaded_it():
    """PER-SURVEY COUNTRY PIN. The custodian promise is "your survey was downloaded N times from M
    countries", and M did not exist anywhere in the pipeline. Each survey row must accumulate a sorted,
    de-duplicated list of country codes, at the cumulative and month grains, so the count is derivable.
    The list is held at COUNTRY grain only and only its COUNT is rendered. FAILS IF the list is absent,
    unsorted, duplicated, or if a download with no resolvable country pollutes it with a real code."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    lines = [
        _line("/data/edi/sample-survey/Vulcan_A1.edi", "1.2.3.0", size=1),        # NZ
        _line("/data/edi/sample-survey/Vulcan_A2.edi", "203.0.113.5", size=2),    # AU
        _line("/data/xml/sample-survey/A1.xml", "198.51.100.0", size=3),          # US
        _line("/data/xml/sample-survey/A2.xml", "203.0.113.200", size=4),         # AU again
        _line("/data/bundles/sample-survey-tf.h5", "8.8.8.0", size=5),            # unresolvable
    ]
    stats = AGG.aggregate(None, lines, rmap, geoip, _RUN)
    row = stats["downloads"]["by_survey"]["CI Sample Survey"]
    assert row["downloads"] == 5
    assert row["countries"] == ["AU", "NZ", "US", "unknown"], row["countries"]
    assert stats["monthly"][0]["surveys"]["CI Sample Survey"]["countries"] == \
        ["AU", "NZ", "US", "unknown"]


def test_a_survey_map_written_before_the_country_list_reads_back_and_starts_accruing():
    """PER-SURVEY COUNTRY MIGRATION PIN. by_survey has already migrated once (a bare int to
    {downloads, bytes}); the country list is the third shape and must be just as tolerant. An older row
    reads back with an empty list and starts accruing, and no historical country is invented. FAILS IF
    an older survey map raises, loses its counts, or claims countries it never recorded."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    prior = {"schema": 2, "last_folded_date": "2026-07-09", "monthly": [], "detail_since": None,
             "totals": {"downloads": 4, "visits": 0, "download_bytes": 40, "unattributed": 0,
                        "api_requests": 0},
             "downloads": {"by_format": {"edi": 4}, "by_kind": {"file": 4}, "by_dataset": {},
                           "by_survey": {"CI Sample Survey": {"downloads": 4, "bytes": 40}}},
             "countries": {"AU": 4}, "daily": []}
    after = AGG.aggregate(prior, [_line("/data/edi/sample-survey/Vulcan_A1.edi", "1.2.3.0",
                                        date="2026-07-10", size=5)], rmap, geoip, _RUN)
    row = after["downloads"]["by_survey"]["CI Sample Survey"]
    assert row["downloads"] == 5 and row["bytes"] == 45
    assert row["countries"] == ["NZ"], "only downloads folded with the list in place appear in it"


def test_each_month_records_its_peak_daily_network_count():
    """MONTHLY REACH PIN. The distinct-network reach proxy lived only on daily rows, so it died with the
    92-day window and could never reach a quarterly report, which is exactly the horizon a funding
    report asks about. Each month must record the PEAK of its folded days' network counts, accumulated
    as each day folds and never recomputed from a tail that is about to be pruned. FAILS IF the peak is
    absent, if it is an average or a sum, if it is recomputed from the daily rows, or if pruning those
    rows loses it."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    may = [_line("/data/catalogue.json", "203.0.113.5", date="2026-05-04"),
           _line("/data/catalogue.json", "1.2.3.0", date="2026-05-04"),
           _line("/data/catalogue.json", "198.51.100.0", date="2026-05-04"),
           _line("/data/catalogue.json", "203.0.113.5", date="2026-05-30")]
    run_may = dt.datetime(2026, 6, 1, 3, 30, tzinfo=dt.timezone.utc)
    s1 = AGG.aggregate(None, may, rmap, geoip, run_may, daily_keep=92)
    months = {m["month"]: m for m in s1["monthly"]}
    assert months["2026-05"]["networks_peak"] == 3, "the peak day, not the total and not the last day"
    # Far in the future: every May daily row is pruned, and the month keeps its peak.
    run_far = dt.datetime(2026, 11, 1, 3, 30, tzinfo=dt.timezone.utc)
    s2 = AGG.aggregate(s1, [], rmap, geoip, run_far, daily_keep=92)
    assert s2["daily"] == []
    assert {m["month"]: m["networks_peak"] for m in s2["monthly"]} == {"2026-05": 3}


def test_the_served_survey_denominator_is_recorded_at_fold_time():
    """DENOMINATOR PIN. "12 surveys downloaded" reads very differently against 14 served and against
    140, and the screen had no denominator at all. The fold must stamp how many surveys the SERVED
    manifest offers, so the ratio is honest at the moment it was measured. FAILS IF the figure is
    absent, or counts anything other than the distinct surveys the current manifest resolves."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    stats = AGG.aggregate(None, [], rmap, geoip, _RUN)
    assert stats["total_served_surveys"] == 1, "the fixture manifest serves exactly one survey"
    # An absent or unreadable manifest must not fabricate a denominator.
    assert AGG.aggregate(None, [], {}, geoip, _RUN)["total_served_surveys"] == 0


def test_the_state_and_funding_detail_still_leaks_nothing():
    """LEAK PIN (state and funding detail). The new dimensions are per-state counters, a list of
    two-letter country codes, a peak integer and a survey count. None may put an address or a
    user-agent into stats.json, and in particular the per-survey country list must stay at COUNTRY
    grain. FAILS IF any of it reaches the emitted file."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    states = AGG.AuStates.load(_AU_STATES_CSV)
    lines = _au_lines() + [
        _line("/data/mtcat.schema.json", _AU_NSW, ua="curl/8.4.0"),
        _line("/data/bundles/sample-survey-tf.h5", _AU_WA_V6, size=900),
        _line("/data/edi/sample-survey/Vulcan_A1.edi", "2001:db8:1234::", size=3),
    ]
    stats = AGG.aggregate(None, lines, rmap, geoip, _RUN, au_states=states)
    emitted = json.dumps(stats, indent=1)
    assert _sweep_ip_or_ua(emitted) == [], emitted
    assert stats["by_state_detail"], "the new maps really are populated (a vacuous sweep proves nothing)"
    assert stats["downloads"]["by_survey"]["CI Sample Survey"]["countries"]
    for code in stats["by_state_detail"]:
        assert code in AGG.AU_STATE_CODES or code == AGG.AU_STATE_UNATTRIBUTED, code
    # The per-country detail map and the per-survey kind split ride the same promise. A country code is
    # a short label and the split is two integers; neither may carry an address or a user-agent, and a
    # detail key must be a country code (the shape the country map already uses), never anything finer.
    assert stats["by_country_detail"], "the country detail is populated too"
    assert stats["downloads"]["by_survey"]["CI Sample Survey"]["files"] >= 1
    for code in stats["by_country_detail"]:
        assert code == "unknown" or (code.isalpha() and code.isupper() and len(code) == 2), code
        assert set(stats["by_country_detail"][code]) == {"downloads", "visits", "api", "bytes"}, code


# ==================================================================================================
# The APPEND-ONLY DAILY ARCHIVE lane (owner ruling 2026-07-30).
#
# The raw log rotates in a week and the daily rows roll off after 92 days, so the only permanent
# record was the calendar month. Every question finer than a month became unanswerable RETROACTIVELY:
# we had the data, we folded it, and we discarded the detail. The archive is one JSON line per folded
# day at maximal NON-GEO granularity, appended beside stats.json, read by nothing and served by
# nothing.
#
# The boundary these pins hold is the geographic one. The owner's ratified exclusion of day-by-state
# data generalises: no country and no state below month grain, RENDERED OR ARCHIVED. A named country
# on a named day is a smaller cell than a named state in a named month.
# ==================================================================================================
_MTCAT = _FIXTURES / "mtcat.sample.json"


def _archive_of(prev, lines, *, rmap=None, geoip=None, run=_RUN, **kw) -> list[dict]:
    """The archive rows one fold produces, via the out channel `aggregate` fills."""
    rows: list[dict] = []
    AGG.aggregate(prev, lines,
                  rmap if rmap is not None else AGG.build_reverse_map(
                      json.loads(_MANIFEST.read_text(encoding="utf-8"))),
                  geoip if geoip is not None else AGG.GeoIP.load(_DBIP),
                  run, archive_out=rows, **kw)
    return rows


def test_a_fold_archives_each_new_day_once_and_a_rerun_archives_nothing():
    """ARCHIVE APPEND PIN. The fold must hand back exactly one row per day it actually folded, oldest
    first, and a rerun over the same lines must hand back NOTHING: the watermark already guarantees a
    day folds once, and the archive is append-only, so a second row for a day would be a permanent
    duplicate nothing can clean up. FAILS IF a day is archived twice, if the rows are unordered, or if
    a rerun produces any row at all."""
    lines = [_line("/data/edi/sample-survey/Vulcan_A1.edi", "203.0.113.5", date="2026-07-09"),
             _line("/data/catalogue.json", "1.2.3.0", date="2026-07-09"),
             _line("/data/xml/sample-survey/A2.xml", "198.51.100.0", date="2026-07-10")]
    rows: list[dict] = []
    stats = AGG.aggregate(None, lines, AGG.build_reverse_map(
        json.loads(_MANIFEST.read_text(encoding="utf-8"))), AGG.GeoIP.load(_DBIP), _RUN,
        archive_out=rows)
    assert [r["date"] for r in rows] == ["2026-07-09", "2026-07-10"], rows
    assert rows[0]["downloads"] == 1 and rows[0]["visits"] == 1
    assert rows[1]["downloads"] == 1 and "visits" not in rows[1]

    again = _archive_of(stats, lines)
    assert again == [], f"a rerun must append nothing: {again}"


def test_an_archive_line_is_sparse_and_an_active_day_matches_the_fold():
    """ARCHIVE SHAPE PIN. Only NONZERO entries are written: a day of visits alone must carry no
    by_dataset, no by_format and no download keys, so a quiet day is a short line rather than a wall
    of zeroes that reads as measured absence. An ACTIVE day's per-dataset rows must agree with the
    counts the same fold wrote into stats.json. FAILS IF an idle day carries download noise, or if the
    archive and the cumulative maps disagree about the same day."""
    idle = _archive_of(None, [_line("/data/catalogue.json", "203.0.113.5", date="2026-07-09")])
    assert idle[0]["visits"] == 1
    for absent in ("downloads", "download_bytes", "unattributed", "by_dataset", "by_format",
                   "by_kind", "by_survey", "by_collection"):
        assert absent not in idle[0], f"an idle day must not carry {absent}: {idle[0]}"

    lines = [_line("/data/edi/sample-survey/Vulcan_A1.edi", "203.0.113.5", size=100),
             _line("/data/edi/sample-survey/Vulcan_A1.edi", "1.2.3.0", size=100),
             _line("/data/bundles/sample-survey-tf.h5", "203.0.113.5", size=900)]
    rows: list[dict] = []
    stats = AGG.aggregate(None, lines, AGG.build_reverse_map(
        json.loads(_MANIFEST.read_text(encoding="utf-8"))), AGG.GeoIP.load(_DBIP), _RUN,
        archive_out=rows)
    day = rows[0]
    assert day["downloads"] == stats["totals"]["downloads"] == 3
    assert day["download_bytes"] == stats["totals"]["download_bytes"] == 1100
    assert day["by_dataset"]["edi/sample-survey/Vulcan_A1.edi"] == {
        "downloads": 2, "bytes": 200, "format": "edi", "survey": "CI Sample Survey"}
    assert day["by_survey"]["CI Sample Survey"] == {"downloads": 3, "bytes": 1100,
                                                    "files": 2, "bundles": 1}
    assert day["by_format"] == stats["downloads"]["by_format"]
    assert day["networks"] == 2, "the scalar network count is the only per-network datum archived"


def test_no_archive_line_ever_carries_a_country_or_a_state():
    """ARCHIVE GEO PIN. Geography stops at the MONTH, rendered or archived. The day rows here are the
    finest-grained record in the whole pipeline, and a named country on a named day is a smaller cell
    than the named-state-in-a-named-month the owner already ruled out. FAILS IF any geographic key or
    value reaches an archive line, even though the very same fold is counting countries and states
    into stats.json beside it."""
    states = AGG.AuStates.load(_AU_STATES_CSV)
    rows: list[dict] = []
    stats = AGG.aggregate(None, _au_lines(), AGG.build_reverse_map(
        json.loads(_MANIFEST.read_text(encoding="utf-8"))), AGG.GeoIP.load(_DBIP), _RUN,
        au_states=states, archive_out=rows)
    assert stats["countries"] and stats["by_state"] and stats["by_country_detail"], \
        "the same fold must really be counting geography, or this pin is vacuous"
    assert rows, "and it must really have archived something"
    # Every geographic key the fold writes into stats.json, banned at ANY depth of an archive line. The
    # per-country DETAIL map is on this list for exactly the reason the country map itself is: it is a
    # geographic cell, and one attached to a named day is the finest cell the pipeline could produce.
    _BANNED = ("countries", "country", "by_state", "state", "states",
               "by_country_detail", "country_detail", "by_state_detail", "state_detail")
    def _walk(obj, path="$"):
        if isinstance(obj, dict):
            for k, v in obj.items():
                assert k not in _BANNED, \
                    f"the archive must carry no geography: key {k!r} at {path}"
                _walk(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                _walk(v, f"{path}[{i}]")
    _walk(rows)


def test_the_daily_archive_leaks_no_address_and_no_user_agent():
    """LEAK PIN (daily archive). The archive is a SECOND file leaving the fold, kept forever, so the
    record D2/D6 promise has to hold over it exactly as it holds over stats.json: no address, masked
    or not, and no user-agent string. FAILS IF either survives into an archive line. Non-vacuous by
    the same negative control the stats.json sweep uses."""
    states = AGG.AuStates.load(_AU_STATES_CSV)
    lines = [
        _line("/data/edi/sample-survey/Vulcan_A1.edi", "203.0.113.5", size=100),
        _line("/data/edi/sample-survey/Vulcan_A1.edi", "2001:db8:1234::", status=206,
              ua="curl/8.4.0"),
        _line("/data/mtcat.schema.json", "198.51.100.0", ua="python-requests/2.31.0"),
        _line("/data/catalogue.json", "1.2.3.0", ua="Mozilla/5.0 (X11) AppleWebKit/537"),
    ]
    rows = _archive_of(None, lines, au_states=states,
                       collections={"CI Sample Survey": "auslamp"})
    emitted = "\n".join(json.dumps(r, sort_keys=True) for r in rows)
    assert _sweep_ip_or_ua(emitted) == [], emitted
    assert rows[0]["by_client"] and rows[0]["by_collection"], \
        "the maps really are populated (a vacuous sweep proves nothing)"
    assert _sweep_ip_or_ua(emitted + ' "v4": "203.0.113.5"'), \
        "the sweep must still catch a planted address over the archive text"


def test_collection_downloads_reconcile_with_their_member_surveys():
    """COLLECTION ROLLUP PIN. A collection bump must be exactly the sum of its member surveys' bumps
    for the same fold, at the cumulative grain, the month grain and in the archive line, or a
    programme figure quoted in a report will not survive being checked against the surveys under it.
    FAILS IF the three grains disagree, or if a survey the served mtcat.json does not place in a
    collection is credited to one anyway."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    collections = AGG.build_collection_map(json.loads(_MTCAT.read_text(encoding="utf-8")), rmap)
    assert collections == {"CI Sample Survey": "auslamp"}, collections
    lines = [_line("/data/edi/sample-survey/Vulcan_A1.edi", "203.0.113.5", size=100),
             _line("/data/bundles/sample-survey-tf.h5", "1.2.3.0", size=900),
             _line("/data/edi/UNKNOWN/x.edi", "198.51.100.0", size=7)]     # unattributed: no survey
    rows: list[dict] = []
    stats = AGG.aggregate(None, lines, rmap, AGG.GeoIP.load(_DBIP), _RUN,
                          collections=collections, archive_out=rows)
    member = stats["downloads"]["by_survey"]["CI Sample Survey"]
    assert stats["by_collection"] == {"auslamp": {"downloads": member["downloads"],
                                                  "bytes": member["bytes"]}}
    assert stats["monthly"][0]["by_collection"] == stats["by_collection"]
    assert rows[0]["by_collection"] == stats["by_collection"]
    assert stats["by_collection"]["auslamp"]["downloads"] == 2, \
        "the unattributed download belongs to no survey and so to no collection"


def test_no_served_mtcat_means_no_collection_dimension_at_all():
    """COLLECTION ABSENCE PIN. The collection map is OPTIONAL exactly as the state table is: an absent
    or unreadable mtcat.json must leave the maps EMPTY rather than inventing a bucket, and must not
    stop the fold. FAILS IF a missing document fabricates a collection or raises."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    assert AGG.build_collection_map(None, rmap) == {}
    assert AGG.build_collection_map({"surveys": "not a list"}, rmap) == {}
    assert AGG.build_collection_map({"surveys": [{"survey_id": "sample-survey"}]}, rmap) == {}, \
        "a survey in no collection gets no bucket, not an empty-string one"
    stats = AGG.aggregate(None, [_line("/data/edi/sample-survey/Vulcan_A1.edi", "203.0.113.5")],
                          rmap, AGG.GeoIP.load(_DBIP), _RUN)
    assert stats["by_collection"] == {} and stats["monthly"][0]["by_collection"] == {}


def test_the_collection_map_prefers_the_slug_over_the_title():
    """COLLECTION JOIN PIN. MTCAT names a survey twice and the manifest's bundle rows carry the SLUG,
    which is an identifier, while the title is prose that can be re-worded between builds. The slug
    join must win. FAILS IF a re-worded title silently drops a survey out of its collection, or if a
    title collision overrides a slug match."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    retitled = {"surveys": [{"survey_id": "sample-survey", "title": "Renamed Between Builds",
                             "collection_id": "auslamp"}]}
    assert AGG.build_collection_map(retitled, rmap) == {"CI Sample Survey": "auslamp"}
    # And with no slug to join on, the title still carries it (a survey with only file rows).
    files_only = {k: v for k, v in rmap.items() if v.get("kind") == "file"}
    assert AGG.build_collection_map(
        {"surveys": [{"survey_id": "not-this-one", "title": "CI Sample Survey",
                      "collection_id": "auslamp"}]}, files_only) == {"CI Sample Survey": "auslamp"}


def test_an_unreadable_log_file_is_named_and_counted_rather_than_swallowed(tmp_path, capsys):
    """UNREADABLE-LOG PIN (verified incident, 2026-07-30). The box's access.json was root:root 0600;
    every open raised, this reader swallowed it, and the fold ran for DAYS on the shipped front-door
    file alone while producing a complete-looking stats.json. Tolerant must not mean silent: a file
    the glob matched but could not open must be NAMED on stderr and counted, while the readable
    siblings still fold and nothing raises. FAILS IF the skip is silent, uncounted, or fatal."""
    logdir = tmp_path / "caddy"
    logdir.mkdir()
    (logdir / "access.json").write_text(
        _line("/data/catalogue.json", "203.0.113.5") + "\n", encoding="utf-8")
    locked = logdir / "access-2026-07-09T03-25-02.001.json"
    locked.write_text(_line("/data/edi/sample-survey/Vulcan_A1.edi", "1.2.3.0",
                            date="2026-07-09") + "\n", encoding="utf-8")
    locked.chmod(0o000)
    try:
        skipped: list[str] = []
        lines = AGG.read_log_lines(logdir, skipped=skipped)
        err = capsys.readouterr().err
        assert len(lines) == 1, f"the readable sibling must still fold: {lines}"
        assert skipped == [str(locked)], f"the unreadable file must be counted: {skipped}"
        assert "access-2026-07-09T03-25-02.001.json" in err, f"and named on stderr: {err}"
        # A corrupt gz is a different case and stays a silent skip: it is the documented salvage
        # path, not an operational fault, and it must not become a nightly warning.
        (logdir / "access-2026-07-08T03-25-00.000.json.gz").write_text("not gzip", encoding="utf-8")
        quiet: list[str] = []
        AGG.read_log_lines(logdir, skipped=quiet)
        capsys.readouterr()
        assert quiet == [str(locked)], f"a corrupt archive is not an unreadable file: {quiet}"
    finally:
        locked.chmod(0o644)


def test_main_writes_the_archive_beside_stats_json_outside_the_served_tree(tmp_path, monkeypatch):
    """ARCHIVE LOCATION PIN. The archive must land in the gateway STATE dir beside stats.json and NOT
    anywhere under site-data, because everything under site-data is served to the public web and this
    file is the finest-grained record the pipeline holds. Its journal line must also report how many
    days it archived. FAILS IF the default path falls inside the served tree, if main() does not write
    it, or if a second run duplicates a day already in the file."""
    data = tmp_path / "data"
    logdir = data / "logs" / "caddy"
    state = data / "gateway" / "state"
    served = data / "site-data" / "current"
    logdir.mkdir(parents=True)
    state.mkdir(parents=True)
    served.mkdir(parents=True)
    (served / "manifest.json").write_text(_MANIFEST.read_text(encoding="utf-8"), encoding="utf-8")
    (served / "mtcat.json").write_text(_MTCAT.read_text(encoding="utf-8"), encoding="utf-8")
    (served / "build.json").write_text(json.dumps({"build_id": "abc123-7776900-2026-07-11"}),
                                       encoding="utf-8")
    (logdir / "access.json").write_text("\n".join([
        _line("/data/edi/sample-survey/Vulcan_A1.edi", "203.0.113.5", date="2026-07-09", size=100),
        _line("/data/catalogue.json", "1.2.3.0", date="2026-07-10"),
    ]) + "\n", encoding="utf-8")

    monkeypatch.setenv("AUSMT_DATA_DIR", str(data))
    monkeypatch.setenv("AUSMT_STATS_MANIFEST", str(served / "manifest.json"))
    monkeypatch.setenv("AUSMT_STATS_DBIP_CSV", str(_DBIP))
    monkeypatch.setenv("AUSMT_STATS_NOW", "2026-07-12T03:30:00Z")
    monkeypatch.delenv("AUSMT_STATS_FILE", raising=False)
    monkeypatch.delenv("AUSMT_STATS_DAILY_ARCHIVE", raising=False)
    assert AGG.main([]) == 0

    archive = state / "daily_archive.jsonl"
    assert archive.is_file(), f"main() must write the archive beside stats.json: {list(state.iterdir())}"
    assert (data / "site-data") not in archive.parents, "the archive must never sit in the served tree"
    rows = [json.loads(ln) for ln in archive.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert [r["date"] for r in rows] == ["2026-07-09", "2026-07-10"], rows
    assert rows[0]["by_collection"] == {"auslamp": {"downloads": 1, "bytes": 100}}
    assert all(r["served_build"] == "abc123-7776900-2026-07-11" for r in rows), \
        "the served tree names itself, so each line carries that name"
    assert _sweep_ip_or_ua(archive.read_text(encoding="utf-8")) == []

    # A second run folds no new day and must therefore append nothing.
    assert AGG.main([]) == 0
    assert archive.read_text(encoding="utf-8").count("\n") == 2, "append-only means appended ONCE"


def test_an_unwritable_archive_warns_and_still_lets_stats_json_land(tmp_path, monkeypatch, capsys):
    """ARCHIVE NEVER-RAISE PIN. The archive is a bonus record, not the fold. An archive path that
    cannot be written (a directory in its place, a read-only mount) must produce a loud note and leave
    stats.json exactly as it would have been. FAILS IF the run raises, returns non-zero, or costs the
    stats write."""
    data = tmp_path / "data"
    logdir = data / "logs" / "caddy"
    state = data / "gateway" / "state"
    logdir.mkdir(parents=True)
    state.mkdir(parents=True)
    (logdir / "access.json").write_text(
        _line("/data/catalogue.json", "203.0.113.5") + "\n", encoding="utf-8")
    blocked = state / "daily_archive.jsonl"
    blocked.mkdir()                     # a DIRECTORY where the archive file should be

    monkeypatch.setenv("AUSMT_DATA_DIR", str(data))
    monkeypatch.setenv("AUSMT_STATS_MANIFEST", str(_MANIFEST))
    monkeypatch.setenv("AUSMT_STATS_DBIP_CSV", str(_DBIP))
    monkeypatch.setenv("AUSMT_STATS_FILE", str(state / "stats.json"))
    monkeypatch.setenv("AUSMT_STATS_NOW", "2026-07-12T03:30:00Z")
    monkeypatch.delenv("AUSMT_STATS_DAILY_ARCHIVE", raising=False)

    assert AGG.main([]) == 0
    err = capsys.readouterr().err
    assert "daily archive" in err, f"the failure must be loud: {err}"
    doc = json.loads((state / "stats.json").read_text(encoding="utf-8"))
    assert doc["totals"]["visits"] == 1, "stats.json still lands in full"


def test_nothing_in_the_gateway_reads_the_daily_archive():
    """NEVER-SERVED PIN. The archive is written by the host timer and read by NOTHING: no gateway
    route, no render path, no export. It holds the finest-grained record in the pipeline precisely
    because nothing consumes it, so a reference to it from the serving stack is the change that must
    be caught here rather than in review. FAILS IF any gateway source names the archive file."""
    gateway = _REPO / "gateway"
    assert gateway.is_dir(), "this pin runs from a full checkout (gateway-ci lane), never skipped"
    offenders = [str(p.relative_to(_REPO)) for p in sorted(gateway.rglob("*.py"))
                 if "daily_archive" in p.read_text(encoding="utf-8", errors="replace")]
    assert offenders == [], f"the gateway must not read the daily archive: {offenders}"


# ==================================================================================================
# COUNTRY-CLASS DETAIL and the PER-SURVEY KIND SPLIT (owner rulings 2026-08-01).
#
# The AU state table already answers "what did this place DO" -- downloads, visits, API requests and
# bytes -- while the country table beside it answered only "how many requests". Every country now
# carries the same four-column breakdown, at the SAME two grains the state detail uses (cumulative and
# calendar month) and NOWHERE ELSE: a named country on a named day is the smaller cell, and the
# small-cell argument that keeps the state detail off the daily grain keeps this off it too.
#
# The per-survey rows gain the split the format/kind maps already carried globally: how many of a
# survey's downloads were single-station files and how many were whole-survey packages.
# ==================================================================================================
_US = "198.51.100.0"        # country US
_UNRESOLVED = "8.8.8.0"     # in no range of the country fixture -> the 'unknown' code


def _country_class_lines():
    """One window touching every request class against three real countries and the unknown code."""
    return [
        _line("/data/edi/sample-survey/Vulcan_A1.edi", _AU_NSW, size=100),
        _line("/data/bundles/sample-survey-tf.h5", _AU_NSW, size=900),
        _line("/data/catalogue.json", _AU_NSW),
        _line("/data/mtcat.schema.json", _US),
        _line("/data/edi/sample-survey/Vulcan_A2.edi", _US, size=7),
        _line("/data/catalogue.json", _NZ),
        _line("/data/catalogue.json", _UNRESOLVED),
    ]


def test_country_rows_carry_downloads_visits_api_and_volume_beside_the_request_count():
    """COUNTRY DETAIL PIN. "Requests from Germany" is not what a custodian conversation asks; it asks
    how much was DOWNLOADED from there and how many bytes that was. A parallel by_country_detail map
    must record downloads, visits, API requests and bytes per country, at the cumulative and month
    grains, for every country the fold sees including the unresolved `unknown` code. FAILS IF the
    detail is absent, if a metric lands in the wrong column, if bytes are credited to a non-download
    class, if the two grains disagree, or if the combined `countries` map the AU-state reconciliation
    depends on is disturbed."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    stats = AGG.aggregate(None, _country_class_lines(), rmap, geoip, _RUN)
    detail = stats["by_country_detail"]
    assert detail["AU"] == {"downloads": 2, "visits": 1, "api": 0, "bytes": 1000}
    assert detail["US"] == {"downloads": 1, "visits": 0, "api": 1, "bytes": 7}
    assert detail["NZ"] == {"downloads": 0, "visits": 1, "api": 0, "bytes": 0}
    assert detail["unknown"] == {"downloads": 0, "visits": 1, "api": 0, "bytes": 0}
    assert stats["monthly"][0]["by_country_detail"] == detail, \
        "the month grain must agree with the cumulative one over a single-month window"
    # The COMBINED map is untouched: it is what the AU state rows reconcile against, and the detail is
    # a breakdown of exactly those same requests, never an additional measurement.
    assert stats["countries"] == {"AU": 3, "US": 2, "NZ": 1, "unknown": 1}
    for code, row in detail.items():
        assert row["downloads"] + row["visits"] + row["api"] == stats["countries"][code], code


def test_country_detail_needs_no_state_table_and_covers_countries_with_no_state_grain():
    """COUNTRY DETAIL SCOPE PIN. The state detail is conditional on the OPTIONAL AU state table; the
    country detail is not, because the country lookup is the fold's own and every counted request
    already resolves through it. A box with no state table must still get the full country breakdown.
    FAILS IF the country detail is gated on the state table, or if a non-AU country is denied one."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    without = AGG.aggregate(None, _country_class_lines(), rmap, geoip, _RUN)
    states = AGG.AuStates.load(_AU_STATES_CSV)
    with_table = AGG.aggregate(None, _country_class_lines(), rmap, geoip, _RUN, au_states=states)
    assert without["by_state"] == {} and without["by_state_detail"] == {}
    assert without["by_country_detail"] == with_table["by_country_detail"], \
        "the state table must change nothing about the country breakdown"
    assert with_table["by_state_detail"]["NSW"] == {"downloads": 2, "visits": 1, "api": 0,
                                                    "bytes": 1000}


def test_country_detail_is_forward_only_and_never_reaches_a_day_row():
    """COUNTRY DETAIL SEAM PIN. The detail map is a new dimension and obeys every rule its siblings do:
    it starts at the fold that first wrote it, no earlier month gains it, and it exists at the
    cumulative and month grains ONLY. A day-by-country cell is a smaller cell than the day-by-state one
    already ruled out. FAILS IF an older file cannot be read, if an earlier month is backfilled, or if
    a day row gains country detail."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    run1 = dt.datetime(2026, 6, 2, 3, 30, tzinfo=dt.timezone.utc)
    run2 = dt.datetime(2026, 7, 12, 3, 30, tzinfo=dt.timezone.utc)
    s1 = AGG.aggregate(None, [_line("/data/catalogue.json", _AU_NSW, date="2026-06-01")],
                       rmap, geoip, run1)
    # A file written before the country detail existed, read back off disk.
    s1.pop("by_country_detail", None)
    for m in s1["monthly"]:
        m.pop("by_country_detail", None)
    s1 = json.loads(json.dumps(s1))

    s2 = AGG.aggregate(s1, [_line("/data/edi/sample-survey/Vulcan_A1.edi", _NZ, date="2026-07-10",
                                  size=42)], rmap, geoip, run2)
    months = {m["month"]: m for m in s2["monthly"]}
    assert months["2026-06"]["by_country_detail"] == {}, "an earlier month must not be backfilled"
    assert months["2026-06"]["countries"] == {"AU": 1}, "its combined country map is untouched"
    assert months["2026-07"]["by_country_detail"] == {
        "NZ": {"downloads": 1, "visits": 0, "api": 0, "bytes": 42}}
    assert s2["by_country_detail"] == {"NZ": {"downloads": 1, "visits": 0, "api": 0, "bytes": 42}}
    assert s2["countries"] == {"AU": 1, "NZ": 1}, "the cumulative combined map still covers both"
    for day in s2["daily"]:
        assert "countries" not in day and "by_country_detail" not in day, day


def test_each_survey_splits_its_downloads_into_station_files_and_whole_survey_bundles():
    """PER-SURVEY KIND PIN. The station-file vs survey-bundle split existed only as a GLOBAL counter,
    so "was this survey pulled file by file or taken whole" was unanswerable per survey -- which is the
    form the question actually takes. Each survey row must carry the split at the cumulative and month
    grains and in the daily archive, and a de-duplicated repeat must not bump it. FAILS IF the split is
    absent, if a bundle is counted as a file, if the grains disagree, or if the dedupe leaks into it."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    lines = [
        _line("/data/edi/sample-survey/Vulcan_A1.edi", _AU_NSW, size=100),
        _line("/data/xml/sample-survey/A2.xml", _NZ, size=200),
        _line("/data/bundles/sample-survey-tf.h5", _NZ, size=900),
        # The same network fetching the same file again on the same day: bytes sum, nothing counts.
        _line("/data/edi/sample-survey/Vulcan_A1.edi", _AU_NSW, size=50),
    ]
    rows: list[dict] = []
    stats = AGG.aggregate(None, lines, rmap, geoip, _RUN, archive_out=rows)
    row = stats["downloads"]["by_survey"]["CI Sample Survey"]
    assert row["downloads"] == 3 and row["bytes"] == 1250
    assert (row["files"], row["bundles"]) == (2, 1), row
    month = stats["monthly"][0]["surveys"]["CI Sample Survey"]
    assert (month["files"], month["bundles"]) == (2, 1), month
    # The archive's own per-survey row carries it too: it is a NON-GEO day fact, exactly the kind of
    # detail the archive exists to keep once the 92-day window has dropped the day it came from.
    assert rows[0]["by_survey"]["CI Sample Survey"] == {"downloads": 3, "bytes": 1250,
                                                        "files": 2, "bundles": 1}
    assert stats["downloads"]["by_kind"] == {"file": 2, "bundle": 1}, "the global split is unchanged"


def test_a_survey_map_written_before_the_kind_split_reads_back_and_starts_accruing():
    """PER-SURVEY KIND MIGRATION PIN. by_survey has migrated twice already (a bare int to
    {downloads, bytes}, then the country list); the kind split is the fourth shape and must be just as
    tolerant. An older row reads back with an EMPTY split -- files and bundles both zero beside a real
    download count -- and starts accruing, so the screen can tell "not measured" from "measured and
    none". FAILS IF an older survey map raises, loses its counts, or claims a split it never took."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    prior = {"schema": 2, "last_folded_date": "2026-07-09", "monthly": [], "detail_since": None,
             "totals": {"downloads": 4, "visits": 0, "download_bytes": 40, "unattributed": 0,
                        "api_requests": 0},
             "downloads": {"by_format": {"edi": 4}, "by_kind": {"file": 4}, "by_dataset": {},
                           "by_survey": {"CI Sample Survey": {"downloads": 4, "bytes": 40,
                                                              "countries": ["AU"]}}},
             "countries": {"AU": 4}, "daily": []}
    carried = AGG.aggregate(prior, [], rmap, geoip, _RUN)["downloads"]["by_survey"]["CI Sample Survey"]
    assert carried == {"downloads": 4, "bytes": 40, "countries": ["AU"], "files": 0, "bundles": 0}, \
        "an older row keeps every figure it had and takes an empty, not a fabricated, split"
    after = AGG.aggregate(prior, [_line("/data/bundles/sample-survey-tf.h5", _AU_NSW,
                                        date="2026-07-10", size=5)], rmap, geoip, _RUN)
    row = after["downloads"]["by_survey"]["CI Sample Survey"]
    assert row["downloads"] == 5 and row["bytes"] == 45
    assert (row["files"], row["bundles"]) == (0, 1), \
        "only downloads folded with the split in place appear in it; the earlier four are not guessed"


# ==================================================================================================
# The BULK-EXPORT LABEL (owner ruling 2026-08-01).
#
# The portal's multi-file export marks its OWN file fetches with a query flag (sel=bulk), so the fold
# can tell a drag-selected bulk export from a single station download. It is a label on a request that
# already happens: no new request, no beacon, no identity. These pins hold the four properties that
# make the label mean something:
#   * it is read from the RAW request line, BEFORE the query strip that produces the attribution path;
#   * the dedupe key stays the query-stripped path, so one file fetched with and without the flag is
#     still ONE download;
#   * a deduped download counts as bulk if ANY of its requests that day carried the flag, whichever
#     order they arrived in;
#   * the export-event count is distinct (network, day) pairs, held in memory for the fold exactly like
#     networks_seen and never persisted per network.
# ==================================================================================================
_BULK = "?sel=bulk"


def test_the_bulk_flag_is_read_from_the_raw_line_before_the_query_is_stripped():
    """FLAG READ PIN. The attribution path is the query-STRIPPED one, and it has to stay that way or a
    flagged fetch would attribute to a different dataset than the same file fetched plainly. So the
    flag must be read from the RAW uri first and handed on beside the stripped path. FAILS IF the flag
    is invisible to the parser, if reading it disturbs the path, or if a query that merely mentions the
    token in another parameter is accepted."""
    plain = AGG.parse_caddy_line(_line("/data/edi/sample-survey/Vulcan_A1.edi", _AU_NSW))
    flagged = AGG.parse_caddy_line(_line("/data/edi/sample-survey/Vulcan_A1.edi" + _BULK, _AU_NSW))
    assert plain["path"] == flagged["path"] == "/data/edi/sample-survey/Vulcan_A1.edi", \
        "the flag must never reach the path the manifest is looked up by"
    assert plain["bulk"] is False and flagged["bulk"] is True
    # Other query strings are not the label, and neither is the token buried in another parameter.
    for uri in ("/data/edi/sample-survey/Vulcan_A1.edi?v=2",
                "/data/edi/sample-survey/Vulcan_A1.edi?ref=sel=bulk",
                "/data/edi/sample-survey/Vulcan_A1.edi?sel=single"):
        assert AGG.parse_caddy_line(_line(uri, _AU_NSW))["bulk"] is False, uri
    # It survives a companion parameter on either side of it.
    for uri in ("/data/edi/sample-survey/Vulcan_A1.edi?sel=bulk&v=2",
                "/data/edi/sample-survey/Vulcan_A1.edi?v=2&sel=bulk"):
        assert AGG.parse_caddy_line(_line(uri, _AU_NSW))["bulk"] is True, uri


def test_the_same_file_with_and_without_the_flag_is_still_one_download():
    """DEDUPE PIN. The within-day dedupe key is the query-stripped path, and adding a label must not
    quietly double the headline figure by making the same file look like two. One network fetching one
    file twice on one day, once labelled and once not, is ONE download whose bytes both sum. FAILS IF
    the flag enters the dedupe key, or if the bytes stop summing."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    lines = [_line("/data/edi/sample-survey/Vulcan_A1.edi", _AU_NSW, size=100),
             _line("/data/edi/sample-survey/Vulcan_A1.edi" + _BULK, _AU_NSW, size=40)]
    stats = AGG.aggregate(None, lines, rmap, geoip, _RUN)
    assert stats["totals"]["downloads"] == 1, "one file, one network, one day: one download"
    assert stats["totals"]["download_bytes"] == 140, "every admitted line's bytes still sum"
    assert stats["downloads"]["by_survey"]["CI Sample Survey"]["downloads"] == 1


def test_a_deduped_download_counts_as_bulk_if_any_of_its_requests_carried_the_flag():
    """ANY-FLAGGED PIN. A browser saving a file logs the request twice (cancel, then the download
    manager refetches) and a ranged transfer logs one line per fragment, so the ONE download the fold
    keeps may have arrived flagged or unflagged first. It counts as bulk if ANY of that day's requests
    for it carried the label, which means the classification must be revisable after the count is
    already taken. FAILS IF the class is fixed by whichever line happened to arrive first, or if a
    reclassification loses or duplicates the download."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    for order in (("", _BULK), (_BULK, "")):
        lines = [_line("/data/edi/sample-survey/Vulcan_A1.edi" + q, _AU_NSW, size=10) for q in order]
        stats = AGG.aggregate(None, lines, rmap, geoip, _RUN)
        assert stats["totals"]["downloads"] == 1, order
        assert stats["totals"]["downloads_by_select"] == {"single": 0, "bulk": 1}, \
            f"either arrival order must classify the one download as bulk: {order}"
        assert stats["monthly"][0]["downloads_by_select"] == {"single": 0, "bulk": 1}, order
    # And a wholly unflagged download stays single.
    solo = AGG.aggregate(None, [_line("/data/edi/sample-survey/Vulcan_A1.edi", _AU_NSW, size=10)],
                         rmap, geoip, _RUN)
    assert solo["totals"]["downloads_by_select"] == {"single": 1, "bulk": 0}


def test_bulk_export_events_count_distinct_networks_per_day_and_sum_into_the_month():
    """EXPORT EVENT PIN. One export action fetches many files, so counting flagged downloads counts
    files, not exports. The event proxy is distinct (network, day) pairs that carried at least one bulk
    download, summed into the month: a second export from the same network on the same day is not
    separable from the first and is not claimed to be. FAILS IF events count files, if two networks on
    one day collapse to one event, if one network across two days collapses, or if the month does not
    sum its days."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    lines = [
        # Day 1: TWO networks export. The first takes three files, the second one: 2 events, 4 files.
        _line("/data/edi/sample-survey/Vulcan_A1.edi" + _BULK, _AU_NSW, date="2026-07-09", size=1),
        _line("/data/edi/sample-survey/Vulcan_A2.edi" + _BULK, _AU_NSW, date="2026-07-09", size=1),
        _line("/data/xml/sample-survey/A1.xml" + _BULK, _AU_NSW, date="2026-07-09", size=1),
        _line("/data/edi/sample-survey/Vulcan_A1.edi" + _BULK, _NZ, date="2026-07-09", size=1),
        # ... plus an ordinary single download from a third network, which is no event at all.
        _line("/data/xml/sample-survey/A2.xml", _US, date="2026-07-09", size=1),
        # Day 2: the FIRST network again. A different day is a different event.
        _line("/data/edi/sample-survey/Vulcan_A1.edi" + _BULK, _AU_NSW, date="2026-07-10", size=1),
    ]
    stats = AGG.aggregate(None, lines, rmap, geoip, _RUN)
    assert stats["totals"]["downloads_by_select"] == {"single": 1, "bulk": 5}
    assert stats["totals"]["bulk_export_events"] == 3, "2 networks on day 1, the same one again on day 2"
    month = stats["monthly"][0]
    assert month["bulk_export_events"] == 3 and month["downloads_by_select"] == {"single": 1, "bulk": 5}
    # Nothing per-network is persisted: the sets die with the fold, exactly like networks_seen.
    assert _sweep_ip_or_ua(json.dumps(stats, indent=1)) == []


def test_the_select_split_accumulates_across_folds_and_is_never_backfilled():
    """SELECT SEAM PIN. The split is forward-only like every other dimension here: a file written
    before it existed reads back with no split at all, no earlier month gains one, and the fold stamps
    `select_since` so the screen can NAME the day it begins instead of declining to. FAILS IF an older
    file raises, if an earlier month is backfilled, if the stamp is missing, or if it is re-stamped on
    every later run (which would walk the disclosed date forward forever)."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    run1 = dt.datetime(2026, 6, 2, 3, 30, tzinfo=dt.timezone.utc)    # folds up to 2026-06-01
    run2 = dt.datetime(2026, 7, 12, 3, 30, tzinfo=dt.timezone.utc)
    run3 = dt.datetime(2026, 7, 14, 3, 30, tzinfo=dt.timezone.utc)

    first = AGG.aggregate(None, [_line("/data/edi/sample-survey/Vulcan_A1.edi", _AU_NSW,
                                       date="2026-06-01", size=9)], rmap, geoip, run1)
    assert first["select_since"] is None, "a first-ever fold has nothing predating the split to caveat"
    # A file written before the split existed, read back off disk.
    first["totals"].pop("downloads_by_select", None)
    first["totals"].pop("bulk_export_events", None)
    first.pop("select_since", None)
    for m in first["monthly"]:
        m.pop("downloads_by_select", None)
        m.pop("bulk_export_events", None)
    first = json.loads(json.dumps(first))

    s2 = AGG.aggregate(first, [_line("/data/xml/sample-survey/A1.xml" + _BULK, _NZ,
                                     date="2026-07-10", size=3)], rmap, geoip, run2)
    assert s2["select_since"] == "2026-06-02", "the day after the watermark the older file left"
    months = {m["month"]: m for m in s2["monthly"]}
    assert months["2026-06"]["downloads_by_select"] == {"single": 0, "bulk": 0}, \
        "an earlier month takes an empty split, never a backfilled one"
    assert months["2026-06"]["downloads"] == 1, "its real download figure is untouched"
    assert months["2026-07"]["downloads_by_select"] == {"single": 0, "bulk": 1}
    assert s2["totals"]["downloads_by_select"] == {"single": 0, "bulk": 1}, \
        "the cumulative split covers only what was folded with it in place"
    assert s2["totals"]["downloads"] == 2, "the headline total still covers the whole history"

    s3 = AGG.aggregate(s2, [], rmap, geoip, run3)
    assert s3["select_since"] == "2026-06-02", "the stamp is written once and carried, never re-stamped"


def test_the_archive_carries_the_select_split_and_the_event_count_and_still_no_geography():
    """ARCHIVE SELECT PIN. The split and the event count are NON-GEO day facts, which is exactly the
    class of detail the archive exists to keep once the 92-day window has dropped the day. They must
    ride the archive line, and the geographic boundary must not move an inch to let them. FAILS IF the
    archive loses them, if a day with no bulk download carries a fabricated zero pair, or if any
    geography arrives alongside."""
    rmap = AGG.build_reverse_map(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    geoip = AGG.GeoIP.load(_DBIP)
    states = AGG.AuStates.load(_AU_STATES_CSV)
    lines = [
        _line("/data/edi/sample-survey/Vulcan_A1.edi" + _BULK, _AU_NSW, date="2026-07-09", size=5),
        _line("/data/xml/sample-survey/A1.xml" + _BULK, _AU_NSW, date="2026-07-09", size=5),
        _line("/data/edi/sample-survey/Vulcan_A2.edi", _NZ, date="2026-07-09", size=5),
        _line("/data/edi/sample-survey/Vulcan_A1.edi", _NZ, date="2026-07-10", size=5),
    ]
    rows: list[dict] = []
    AGG.aggregate(None, lines, rmap, geoip, _RUN, au_states=states, archive_out=rows)
    day1, day2 = rows
    assert day1["by_select"] == {"single": 1, "bulk": 2} and day1["bulk_events"] == 1
    assert day2["by_select"] == {"single": 1}, "a sparse line carries only what it counted"
    assert "bulk_events" not in day2, "a day with no export claims no event, not a zero"
    emitted = "\n".join(json.dumps(r, sort_keys=True) for r in rows)
    assert _sweep_ip_or_ua(emitted) == [], emitted
    for banned in ("countries", "country", "by_state", "by_country_detail"):
        assert banned not in emitted, f"the archive still carries no geography: {banned}"


def test_the_aggregator_and_the_portal_agree_on_the_bulk_flag():
    """CROSS-SUBSYSTEM PIN (mirror). The label is a constant shared by two subsystems whose CI lanes
    never run each other's suites: portal/src/exports.js writes it, this file reads it. Edited on one
    side alone, the split degenerates SILENTLY -- the fold keeps working and every bulk export simply
    counts as a single download. This lane (gateway-ci: deploy/** and gateway/**) holds the pin for an
    aggregator-side edit; portal/tests/test_bulk_export_label.py holds it for a portal-side one.

    FAILS IF the two tokens drift, or if the portal stops declaring one at all."""
    exports_js = _REPO / "portal" / "src" / "exports.js"
    assert exports_js.is_file(), "this pin runs from a full checkout (gateway-ci lane), never skipped"
    m = re.search(r"""SEL_BULK_FLAG\s*=\s*["']([^"']+)["']""", exports_js.read_text(encoding="utf-8"))
    assert m, "portal/src/exports.js must declare SEL_BULK_FLAG; the label has no other source"
    assert m.group(1) == AGG._SELECT_BULK_FLAG, (
        f"the portal writes {m.group(1)!r} and this fold reads {AGG._SELECT_BULK_FLAG!r}; "
        f"every bulk export would be counted as a single download")
