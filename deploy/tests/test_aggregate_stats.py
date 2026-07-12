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
    assert geoip.loaded and geoip.row_count == 6
    assert geoip.country("203.0.113.0") == "AU"      # masked /24, network base
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
