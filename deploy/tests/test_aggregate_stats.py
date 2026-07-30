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
    """API-CONSUMER PIN (c). The two DOCUMENTED machine-readable entry points must classify as `api`
    and count on their own line, while every path the portal's own JS fetches on boot must NOT: the
    catalogue is a VISIT, and /data/manifest.json (the SPA's own copy) is neither. Classification is by
    PATH ONLY -- no user-agent is consulted. FAILS IF an SPA-boot fetch is credited as an API consumer,
    if an API fetch inflates the visit count, or if the API line is missing."""
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
    assert months["2026-05"]["surveys"]["CI Sample Survey"] == {"downloads": 2, "bytes": 300}
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
    assert stats["downloads"]["by_survey"]["CI Sample Survey"] == {"downloads": 9, "bytes": 50}
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
        _line("/data/mtcat.json", _AU_NSW),                                     # api: not a geo class
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
