"""Request label pins: operator, client class and network type on the usage statistics.

Every address in this file is a documentation address (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24,
2001:db8::/32) or one of the internal ranges the operator rule names. Pure stdlib python and committed
fixtures, so the file runs everywhere and never trips the CI skip tripwire.
"""
from __future__ import annotations

import copy
import datetime as dt
import gzip
import importlib.util
import json
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "deploy" / "scripts" / "aggregate_stats.py"
_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_DBIP = _FIXTURES / "dbip-country-lite.sample.csv"


def _load_agg():
    spec = importlib.util.spec_from_file_location("aggregate_stats", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


AGG = _load_agg()
_RUN = dt.datetime(2026, 7, 12, 3, 30, 0, tzinfo=dt.timezone.utc)
_BROWSER = "Mozilla/5.0 (X11) AppleWebKit/537"


def _line(uri, addr, *, status=200, size=1000, ua=_BROWSER, date="2026-07-10", method="GET"):
    """One synthetic Caddy JSON access-log line for `uri` from masked address `addr` on `date`."""
    epoch = dt.datetime.strptime(date + "T05:00:00Z", "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=dt.timezone.utc).timestamp()
    return json.dumps({
        "ts": epoch, "status": status, "size": size,
        "request": {"method": method, "uri": uri, "client_ip": addr, "remote_ip": addr,
                    "headers": {"User-Agent": [ua]}},
    })


def _geoip():
    return AGG.GeoIP.load(_DBIP)


# A prior stats.json holding every label block at both grains, as a labelled fold writes them.
_LABELLED_PRIOR = {
    "schema": 2, "since": "2026-06-01", "last_folded_date": "2026-07-09",
    "labels_since": "2026-07-01",
    "totals": {
        "downloads": 40, "visits": 12, "download_bytes": 4000, "unattributed": 0, "api_requests": 3,
        "labels": {"downloads": {"portal_session|hosting": 5, "tool|unknown": 30,
                                 "landing_page|access_provider": 5},
                   "visits": {"portal_session|education_research": 12},
                   "api": {"tool|other": 3},
                   "handoffs": {"unknown|unknown": 2}},
        "operator": {"downloads": 4, "visits": 9, "api": 1, "handoffs": 0, "download_bytes": 400},
        "crawler_excluded": {"downloads": 7, "visits": 2, "api": 0, "handoffs": 1},
    },
    "daily": [],
    "monthly": [{
        "month": "2026-07", "downloads": 40, "visits": 12, "download_bytes": 4000, "days": 9,
        "detail_days": 9,
        "labels": {"downloads": {"portal_session|hosting": 5, "tool|unknown": 30,
                                 "landing_page|access_provider": 5},
                   "visits": {"portal_session|education_research": 12}},
        "operator": {"downloads": 4, "visits": 9, "api": 1, "handoffs": 0, "download_bytes": 400},
        "crawler_excluded": {"downloads": 7, "visits": 2, "api": 0, "handoffs": 1},
        "label_days": 9, "nettype_days": 8, "nettype_full_days": 0, "operator_list_days": 9,
    }],
}

_LABEL_BLOCKS = ("labels", "operator", "crawler_excluded")
_DAY_COUNTERS = ("label_days", "nettype_days", "nettype_full_days", "operator_list_days")


# --------------------------------------------------------------------------------------------------
# Carrying the label blocks forward across folds.
# --------------------------------------------------------------------------------------------------
def test_label_blocks_survive_a_second_fold():
    """A prior stats.json holding every label block, folded again with labels off, keeps every block
    and every day counter exactly. Fails if the tolerant read drops a dict-valued totals key or
    rebuilds a month row without the label keys."""
    prior = copy.deepcopy(_LABELLED_PRIOR)
    stats = AGG.aggregate(prior, [], {}, _geoip(), _RUN)
    assert stats["labels_since"] == "2026-07-01"
    for block in _LABEL_BLOCKS:
        assert stats["totals"][block] == _LABELLED_PRIOR["totals"][block], block
    month = stats["monthly"][0]
    for block in _LABEL_BLOCKS:
        assert month[block] == _LABELLED_PRIOR["monthly"][0][block], block
    for counter in _DAY_COUNTERS:
        assert month[counter] == _LABELLED_PRIOR["monthly"][0][counter], counter
    again = AGG.aggregate(json.loads(json.dumps(stats)), [], {}, _geoip(),
                          _RUN + dt.timedelta(days=1))
    for block in _LABEL_BLOCKS:
        assert again["totals"][block] == stats["totals"][block], block
        assert again["monthly"][0][block] == month[block], block


def test_coerce_clamps_label_keys_to_closed_sets():
    """A hand-edited prior file cannot push an arbitrary label onto the screen: a joint key outside
    the closed client and network sets, a metric outside the four, and an operator or crawler key
    outside its own block are all dropped, and a non-integer value reads as an integer."""
    prior = copy.deepcopy(_LABELLED_PRIOR)
    prior["totals"]["labels"] = {
        "downloads": {"portal_session|hosting": "4", "browser|cloud": 2,
                      "portal_session|AS64500": 1, "tool": 3, "tool|unknown|extra": 1},
        "pageviews": {"tool|unknown": 9},
        "visits": "not a map",
    }
    prior["totals"]["operator"] = {"downloads": 2, "pageviews": 5, "download_bytes": "10"}
    prior["totals"]["crawler_excluded"] = {"visits": 1, "download_bytes": 7, "AS64500": 3}
    prior["monthly"][0]["labels"] = {"api": {"unknown|other": 1, "crawler|other": 4}}
    prior["monthly"][0]["operator"] = {"handoffs": 1, "networks": 3}
    prior["monthly"][0]["crawler_excluded"] = {"api": 2, "203.0.113.0": 1}
    stats = AGG.aggregate(prior, [], {}, _geoip(), _RUN)
    t = stats["totals"]
    assert t["labels"] == {"downloads": {"portal_session|hosting": 4}}
    assert t["operator"] == {"downloads": 2, "download_bytes": 10}
    assert t["crawler_excluded"] == {"visits": 1}
    m = stats["monthly"][0]
    assert m["labels"] == {"api": {"unknown|other": 1}}
    assert m["operator"] == {"handoffs": 1}
    assert m["crawler_excluded"] == {"api": 2}
    # A block that is not a map is not carried at all.
    prior2 = copy.deepcopy(_LABELLED_PRIOR)
    prior2["totals"]["operator"] = [1, 2]
    prior2["monthly"][0]["labels"] = "x"
    stats2 = AGG.aggregate(prior2, [], {}, _geoip(), _RUN)
    assert "operator" not in stats2["totals"]
    assert "labels" not in stats2["monthly"][0]


def test_month_without_labels_gains_no_label_keys():
    """A month and a file folded without labels stay without them: no label block, no day counter
    and no labels_since appear from a carried file or a fresh unlabelled fold."""
    prior = {"schema": 2, "last_folded_date": "2026-07-08", "daily": [],
             "totals": {"downloads": 1, "visits": 0},
             "monthly": [{"month": "2026-06", "downloads": 1, "days": 1}]}
    lines = [_line("/data/catalogue.json", "203.0.113.0"),
             _line("/data/edi/s/a.edi", "198.51.100.0")]
    stats = AGG.aggregate(prior, lines, {}, _geoip(), _RUN)
    assert "labels_since" not in stats
    for block in _LABEL_BLOCKS:
        assert block not in stats["totals"], block
    assert [m["month"] for m in stats["monthly"]] == ["2026-06", "2026-07"]
    for m in stats["monthly"]:
        for key in _LABEL_BLOCKS + _DAY_COUNTERS:
            assert key not in m, (m["month"], key)


def test_labels_since_carried_by_name():
    """labels_since is carried when it is a string and dropped when it is anything else."""
    prior = copy.deepcopy(_LABELLED_PRIOR)
    assert AGG.aggregate(prior, [], {}, _geoip(), _RUN)["labels_since"] == "2026-07-01"
    for bad in (5, None, ["2026-07-01"], {"d": "2026-07-01"}):
        prior = copy.deepcopy(_LABELLED_PRIOR)
        prior["labels_since"] = bad
        assert "labels_since" not in AGG.aggregate(prior, [], {}, _geoip(), _RUN), bad


# --------------------------------------------------------------------------------------------------
# Operator label, the month-aligned switch and the label guard.
# --------------------------------------------------------------------------------------------------
_OPS_SAMPLE = _FIXTURES / "operator-networks.sample.txt"
_GOLDEN = _FIXTURES / "traffic-labels-off"
_IPV4_RE = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
_IPV6_RE = re.compile(r"[0-9a-fA-F]{1,4}::[0-9a-fA-F:]*|::[0-9a-fA-F]{1,4}|"
                      r"(?:[0-9a-fA-F]{1,4}:){3,}[0-9a-fA-F]{1,4}")

# A served manifest small enough to read: two station files and one survey bundle.
_MANIFEST_DOC = {
    "base_url": "", "generated_count": 3,
    "files": [{"survey": "Label Survey", "station": "L1", "format": "edi",
               "url": "edi/label-survey/L1.edi"},
              {"survey": "Label Survey", "station": "L2", "format": "edi",
               "url": "edi/label-survey/L2.edi"}],
    "bundles": [{"survey": "Label Survey", "slug": "label-survey", "format": "edi-zip",
                 "url": "bundles/label-survey-edi.zip"}],
}
_RMAP = AGG.build_reverse_map(_MANIFEST_DOC)


def _mixed_day(date, addr="203.0.113.0"):
    """Front-door traffic of every counted class on `date`, from documentation networks."""
    return [
        _line("/data/catalogue.json", addr, date=date),
        _line("/data/edi/label-survey/L1.edi", addr, date=date, size=300),
        _line("/data/edi/label-survey/L2.edi?sel=bulk", "2001:db8:6::", date=date, size=200),
        _line("/data/bundles/label-survey-edi.zip", "2001:db8:5::", date=date, size=900,
              ua="curl/8.0"),
        _line("/data/mtcat.json", addr, date=date, ua="python-requests/2.31"),
        _line("/go/ts/label-survey/L1/l1", addr, date=date, status=302),
        _line("/data/catalogue.json", "203.0.113.0", date=date, ua="Googlebot/2.1"),
    ]


def _box_day(date):
    """Box-log traffic of every counted class on `date`, from a documentation network."""
    return [
        _line("/data/catalogue.json", "2001:db8:44::", date=date),
        _line("/data/edi/label-survey/L1.edi", "2001:db8:44::", date=date, size=50),
        _line("/data/mtcat.json", "2001:db8:44::", date=date),
        _line("/go/ts/label-survey/L2/l1", "2001:db8:44::", date=date, status=302),
    ]


def _strip_labels(stats):
    """`stats` with every label key removed, for comparing a labelled fold with an unlabelled one."""
    out = copy.deepcopy(stats)
    out.pop("labels_since", None)
    for row in [out["totals"], *out["monthly"]]:
        for key in _LABEL_BLOCKS + _DAY_COUNTERS:
            row.pop(key, None)
    return out


def _fold(lines, *, prev=None, run=_RUN, **kw):
    archive: list = []
    stats = AGG.aggregate(prev, lines, _RMAP, _geoip(), run, archive_out=archive, **kw)
    return stats, archive


def _nets(path=_OPS_SAMPLE):
    return AGG.OperatorNetworks.load(path)


# ---- the byte-identity pin ------------------------------------------------------------------------
def _identity_scenario(root: Path) -> dict:
    """A data dir whose logs hold box, box-roll, front-door and other-named files, with traffic from
    internal ranges, the operator client name and documentation networks, plus an operator list at
    its default path. Returns the environment main() reads."""
    data = root / "data"
    logs = data / "logs" / "caddy"
    logs.mkdir(parents=True)
    (data / "gateway" / "state").mkdir(parents=True)
    served = data / "site-data" / "current"
    served.mkdir(parents=True)
    (served / "manifest.json").write_text(json.dumps(_MANIFEST_DOC), encoding="utf-8")
    private = data / "stats-private"
    private.mkdir()
    (private / "operator-networks.txt").write_text(_OPS_SAMPLE.read_text(encoding="utf-8"),
                                                    encoding="utf-8")
    days = ("2026-07-10", "2026-07-11", "2026-07-12", "2026-07-13")
    (logs / "access.json").write_text("\n".join(
        [_line("/data/catalogue.json", "10.1.2.0", date=days[0]),
         _line("/data/edi/label-survey/L1.edi", "127.0.0.0", date=days[1]),
         _line("/data/catalogue.json", "192.0.2.0", date=days[2], ua="ausmt-ops/1-manual")]
        + _box_day(days[3])) + "\n", encoding="utf-8")
    (logs / "access-2026-07-11T00-00-00.000.json").write_text(
        "\n".join(_box_day(days[1])) + "\n", encoding="utf-8")
    (logs / "access-frontdoor.json").write_text(
        "\n".join(ln for d in days for ln in _mixed_day(d)) + "\n", encoding="utf-8")
    with gzip.open(logs / "access-salvage.json.gz", "wt", encoding="utf-8") as fh:
        fh.write(_line("/data/edi/label-survey/L2.edi", "100.64.1.0", date=days[2]) + "\n")
    return {"AUSMT_DATA_DIR": str(data), "AUSMT_STATS_DBIP_CSV": str(_DBIP)}


def _run_main(monkeypatch, env: dict, now: str, **extra) -> None:
    for k in ("AUSMT_STATS_LABELS_FROM", "AUSMT_STATS_OPERATOR_NETWORKS"):
        monkeypatch.delenv(k, raising=False)
    for k, v in {**env, **extra, "AUSMT_STATS_NOW": now}.items():
        monkeypatch.setenv(k, v)
    assert AGG.main([]) == 0


def _identity_outputs(monkeypatch, root: Path) -> dict[str, bytes]:
    env = _identity_scenario(root)
    state = Path(env["AUSMT_DATA_DIR"]) / "gateway" / "state"
    _run_main(monkeypatch, env, "2026-07-12T03:30:00Z")
    first = (state / "stats.json").read_bytes()
    _run_main(monkeypatch, env, "2026-07-14T03:30:00Z")
    return {"stats-1.json": first, "stats-2.json": (state / "stats.json").read_bytes(),
            "archive.jsonl": (state / "daily_archive.jsonl").read_bytes()}


def test_labels_off_by_default_output_identical(tmp_path, monkeypatch, capsys):
    """With AUSMT_STATS_LABELS_FROM unset, two successive folds write stats.json and the archive
    byte for byte as the fold did before labels existed. The golden files under
    fixtures/traffic-labels-off are that fold's output for this same scenario. Fails if any label
    code path reaches an unlabelled fold, including a box-log, internal-range or operator-named line."""
    got = _identity_outputs(monkeypatch, tmp_path)
    for name, data in got.items():
        assert data == (_GOLDEN / name).read_bytes(), name
    err = capsys.readouterr().err
    assert "labels=off" in err
    assert "operator_list=" not in err


# ---- the switch --------------------------------------------------------------------------------
def test_labels_switch_reads_a_month_aligned_date():
    """The switch is the first day of a month. Absent, malformed or mid-month means labels off."""
    assert AGG._labels_from_cfg("2026-08-01") == "2026-08-01"
    assert AGG._labels_from_cfg(" 2027-01-01 ") == "2027-01-01"
    for bad in ("", "2026-08-02", "2026-8-01", "2026-13-01", "01-08-2026", "yes", "2026-08-01x"):
        assert AGG._labels_from_cfg(bad) is None, bad


def test_days_before_labels_from_fold_as_today():
    """Days before labels_from fold exactly as an unlabelled fold folds them, box lines included;
    from labels_from the box lines leave every figure."""
    run = dt.datetime(2026, 8, 3, 3, 30, tzinfo=dt.timezone.utc)
    july, aug = ("2026-07-30", "2026-07-31"), ("2026-08-01", "2026-08-02")
    front = [ln for d in july + aug for ln in _mixed_day(d)]
    box = [("box", ln) for d in july + aug for ln in _box_day(d)]
    off, off_arc = _fold(front + box, run=run)
    on, on_arc = _fold(front + box, run=run, labels_from="2026-08-01", operator_nets=_nets())
    assert [r for r in on["daily"] if r["date"] < "2026-08-01"] == \
        [r for r in off["daily"] if r["date"] < "2026-08-01"]
    assert [m for m in on["monthly"] if m["month"] == "2026-07"] == \
        [m for m in off["monthly"] if m["month"] == "2026-07"]
    assert [a for a in on_arc if a["date"] < "2026-08-01"] == \
        [a for a in off_arc if a["date"] < "2026-08-01"]
    # August: the box lines are on the operator line, and nowhere else.
    aug_on = next(m for m in on["monthly"] if m["month"] == "2026-08")
    assert aug_on["operator"] == {"downloads": 2, "visits": 2, "api": 2, "handoffs": 2,
                                  "download_bytes": 100}
    assert on["totals"]["downloads"] == off["totals"]["downloads"] - 2
    assert on["totals"]["visits"] == off["totals"]["visits"] - 2
    assert "operator" not in next(m for m in on["monthly"] if m["month"] == "2026-07")


# ---- the box log ---------------------------------------------------------------------------------
def test_box_log_lines_are_operator_and_reach_no_existing_figure():
    """Every admitted line from the box log lands on the operator line at month and cumulative grain
    and in no existing figure: totals, day rows, month rows, archive lines, networks, countries,
    surveys, datasets and hand-off maps all equal a fold without those lines."""
    days = ("2026-07-10", "2026-07-11")
    front = [ln for d in days for ln in _mixed_day(d)]
    box = [("box", ln) for d in days for ln in _box_day(d)]
    kw = {"labels_from": "2026-07-01", "operator_nets": _nets()}
    with_box, arc_with = _fold(front + box, **kw)
    without, arc_without = _fold(front, **kw)
    assert _strip_labels(with_box) == _strip_labels(without)
    assert arc_with == arc_without
    expect = {"downloads": 2, "visits": 2, "api": 2, "handoffs": 2, "download_bytes": 100}
    assert with_box["totals"]["operator"] == expect
    assert with_box["monthly"][0]["operator"] == expect
    assert without["totals"]["operator"] == dict.fromkeys(expect, 0)


def test_box_roll_names_match_positively_other_names_are_public(tmp_path):
    """Only the box listener's own names are the box: access.json and a Caddy roll of it. A
    front-door name is front door, and any other name is treated as front door, never operator,
    and counted as an other file."""
    src = AGG._log_source
    for name in ("access.json", "access-2026-07-11T00-00-00.000.json",
                 "access-2026-07-11T00-00-00.000.log", "access-2026-07-11T00-00-00.000.json.gz"):
        assert src(name) == "box", name
    for name in ("access-frontdoor.json", "access-frontdoor-2026-07-11T00-00-00.000.json",
                 "access-frontdoor.json.gz"):
        assert src(name) == "frontdoor", name
    for name in ("access.log", "access-salvage.json.gz", "access-2026-07-11.json",
                 "access.json.gz", "access-2026-07-11T00-00-00.000.json.bak", "accessx.json"):
        assert src(name) == "other", name
    logs = tmp_path / "caddy"
    logs.mkdir()
    for name in ("access.json", "access-frontdoor.json", "access-salvage.json", "access.log"):
        (logs / name).write_text(_line("/data/catalogue.json", "203.0.113.0") + "\n",
                                 encoding="utf-8")
    other: list = []
    pairs = AGG.read_log_lines(logs, with_source=True, other_files=other)
    assert sorted(s for s, _ in pairs) == ["box", "frontdoor", "other", "other"]
    assert len(other) == 2
    assert AGG.read_log_lines(logs) == [ln for _, ln in pairs]
    stats, _ = _fold(pairs, labels_from="2026-07-01", operator_nets=_nets())
    assert stats["totals"]["visits"] == 3
    assert stats["totals"]["operator"]["visits"] == 1


# ---- the client name and the internal ranges -----------------------------------------------------
def test_internal_ranges_are_operator_documentation_ranges_are_not():
    """The fixed internal list makes loopback, unspecified, shared and private addresses operator,
    and leaves every documentation range public. Fails if the rule leans on is_private, which also
    covers the documentation ranges."""
    op = AGG._operator_label
    for addr in ("127.0.0.0", "::", "100.64.1.0", "10.1.2.0", "172.16.5.0", "192.168.1.0",
                 "169.254.1.0", "fd00:1::", "fe80::"):
        assert op("frontdoor", addr, _BROWSER, _nets()) == "yes", addr
    for addr in ("192.0.2.0", "203.0.113.0", "2001:db8::", "198.51.100.0"):
        assert op("frontdoor", addr, _BROWSER, AGG.OperatorNetworks()) == "unknown", addr
    lines = [_line("/data/catalogue.json", a) for a in ("127.0.0.0", "::", "100.64.1.0",
                                                         "10.1.2.0", "203.0.113.0")]
    stats, _ = _fold(lines, labels_from="2026-07-01", operator_nets=_nets())
    assert stats["totals"]["visits"] == 1
    assert stats["totals"]["operator"]["visits"] == 4


def test_operator_client_name_from_any_address():
    """A user-agent opening with ausmt-ops/ is operator from any address, in any case. The name
    elsewhere in the string is not."""
    lines = [_line("/data/catalogue.json", "203.0.113.0", ua="ausmt-ops/1-doctor-frontdoor"),
             _line("/data/mtcat.json", "2001:db8:7::", ua="AUSMT-OPS/1-smoke"),
             _line("/data/catalogue.json", "203.0.113.0", ua="Mozilla/5.0 ausmt-ops/1-manual")]
    stats, _ = _fold(lines, labels_from="2026-07-01", operator_nets=_nets())
    assert stats["totals"]["operator"]["visits"] == 1
    assert stats["totals"]["operator"]["api"] == 1
    assert stats["totals"]["visits"] == 1
    assert stats["totals"]["api_requests"] == 0


# ---- the operator list ---------------------------------------------------------------------------
def test_operator_list_matches_masked_prefix_and_widens(tmp_path):
    """An entry matches the masked address it contains, and a narrower entry is widened to its /24
    or /48 first, so the masked network base of a /32 or /64 entry matches."""
    nets = _nets()
    assert nets.state == "loaded"
    for addr in ("192.0.2.0", "198.51.100.0", "2001:db8:1::"):
        assert nets.contains(addr), addr
    for addr in ("203.0.113.0", "2001:db8:2::", "not-an-address", None, ""):
        assert not nets.contains(addr), addr
    assert AGG._operator_label("frontdoor", "203.0.113.0", _BROWSER, nets) == "no"
    lines = [_line("/data/catalogue.json", a) for a in ("192.0.2.0", "198.51.100.0",
                                                         "2001:db8:1::", "203.0.113.0")]
    stats, _ = _fold(lines, labels_from="2026-07-01", operator_nets=nets)
    assert stats["totals"]["operator"]["visits"] == 3
    assert stats["totals"]["visits"] == 1
    assert stats["monthly"][0]["operator_list_days"] == 1


def test_operator_list_comments_only_is_empty_and_reads_no(tmp_path):
    """A comments-only list is a deliberate empty list: state empty, operator reads no, and the day
    counts as having an operator list."""
    p = tmp_path / "ops.txt"
    p.write_text("# no static networks\n\n   # indented comment\n", encoding="utf-8")
    nets = AGG.OperatorNetworks.load(p)
    assert nets.state == "empty"
    assert AGG._operator_label("frontdoor", "192.0.2.0", _BROWSER, nets) == "no"
    stats, _ = _fold([_line("/data/catalogue.json", "192.0.2.0")], labels_from="2026-07-01",
                     operator_nets=nets)
    assert stats["totals"]["visits"] == 1
    assert stats["monthly"][0]["label_days"] == 1
    assert stats["monthly"][0]["operator_list_days"] == 1


@pytest.mark.parametrize("kind", ["absent", "directory", "junk"])
def test_operator_list_absent_or_unreadable_keeps_request_counted(tmp_path, kind):
    """An absent or unreadable list reads unknown, the request stays counted, and the day is not
    counted as having an operator list. A file whose every line is invalid is unreadable, not
    empty, so a mangled list is never taken for a deliberate empty one."""
    p = tmp_path / "ops.txt"
    if kind == "directory":
        p.mkdir()
    elif kind == "junk":
        p.write_text("not a network\n192.0.2.0/99\n", encoding="utf-8")
    nets = AGG.OperatorNetworks.load(p)
    assert nets.state == ("absent" if kind == "absent" else "unreadable")
    assert AGG._operator_label("frontdoor", "192.0.2.0", _BROWSER, nets) == "unknown"
    stats, _ = _fold([_line("/data/catalogue.json", "192.0.2.0")], labels_from="2026-07-01",
                     operator_nets=nets)
    assert stats["totals"]["visits"] == 1
    assert stats["totals"]["operator"]["visits"] == 0
    assert stats["monthly"][0]["label_days"] == 1
    assert stats["monthly"][0]["operator_list_days"] == 0


def test_operator_list_partial_state(tmp_path):
    """A list with a valid entry and a skipped line is partial; its valid entries still match."""
    p = tmp_path / "ops.txt"
    p.write_text("192.0.2.0/24\nnot a network\n", encoding="utf-8")
    nets = AGG.OperatorNetworks.load(p)
    assert nets.state == "partial"
    assert nets.contains("192.0.2.0")


def _labelled_main(monkeypatch, root: Path, ops_text: str | None, *, ops_name="ops.txt"):
    """main() over a front-door log of documentation traffic with labels on from July."""
    env = _identity_scenario(root)
    extra = {"AUSMT_STATS_LABELS_FROM": "2026-07-01"}
    if ops_text is not None:
        ops = root / ops_name
        ops.write_text(ops_text, encoding="utf-8")
        extra["AUSMT_STATS_OPERATOR_NETWORKS"] = str(ops)
    _run_main(monkeypatch, env, "2026-07-12T03:30:00Z", **extra)
    state = Path(env["AUSMT_DATA_DIR"]) / "gateway" / "state"
    return state


def test_operator_list_values_never_written_or_printed(tmp_path, monkeypatch, capsys):
    """No entry, entry count or line number of the list reaches stats.json, the archive or the
    journal. Fails if any address token or the list's own prefix text appears in any of them."""
    text = "# private list\n192.0.2.0/24\n2001:db8:1::/48\n198.51.100.7/32\n"
    state = _labelled_main(monkeypatch, tmp_path, text)
    err = capsys.readouterr().err
    outputs = {"stats": (state / "stats.json").read_text(encoding="utf-8"),
               "archive": (state / "daily_archive.jsonl").read_text(encoding="utf-8"),
               "stderr": err}
    for name, out in outputs.items():
        assert _IPV4_RE.findall(out) == [], name
        assert _IPV6_RE.findall(out) == [], name
        for token in ("192.0.2", "2001:db8", "198.51.100", "/24", "/48", "/32", "ausmt-ops"):
            assert token not in out, (name, token)
    assert json.loads(outputs["stats"])["totals"]["operator"]["visits"] >= 1


def test_journal_operator_list_state_has_no_number(tmp_path, monkeypatch, capsys):
    """The journal names the list state and nothing about its size: lists of one and of three
    entries in the same state print the same journal line."""
    lines = []
    for n, text in enumerate(("192.0.2.0/24\n", "192.0.2.0/24\n192.0.2.0/24\n2001:db8:9::/48\n")):
        root = tmp_path / f"r{n}"
        root.mkdir()
        _labelled_main(monkeypatch, root, text)
        err = capsys.readouterr().err
        line = next(ln for ln in err.splitlines() if "folded up to" in ln)
        lines.append(line.replace(str(root), "<root>"))
    assert lines[0] == lines[1]
    assert re.search(r"(?:^|\s)operator_list=loaded(?:\s|$)", lines[0])
    assert re.search(r"(?:^|\s)labels=on from=2026-07-01(?:\s|$)", lines[0])
    assert re.search(r"(?:^|\s)other_files=1(?:\s|$)", lines[0])
    assert re.search(r"(?:^|\s)label_fallbacks=0(?:\s|$)", lines[0])
    for state_text, state in (("# none\n", "empty"), ("192.0.2.0/24\nnot a network\n", "partial"),
                              ("not a network\n", "unreadable")):
        root = tmp_path / state
        root.mkdir()
        _labelled_main(monkeypatch, root, state_text)
        err = capsys.readouterr().err
        assert re.search(r"(?:^|\s)operator_list=%s(?:\s|$)" % state, err), state
    root = tmp_path / "absent"
    root.mkdir()
    env = _identity_scenario(root)
    (Path(env["AUSMT_DATA_DIR"]) / "stats-private" / "operator-networks.txt").unlink()
    _run_main(monkeypatch, env, "2026-07-12T03:30:00Z", AUSMT_STATS_LABELS_FROM="2026-07-01")
    assert re.search(r"(?:^|\s)operator_list=absent(?:\s|$)", capsys.readouterr().err)


def test_journal_says_waiting_before_the_first_labelled_day(tmp_path, monkeypatch, capsys):
    """A switch set for a coming month reads waiting until a day of that month has folded."""
    env = _identity_scenario(tmp_path)
    _run_main(monkeypatch, env, "2026-07-12T03:30:00Z", AUSMT_STATS_LABELS_FROM="2026-08-01")
    err = capsys.readouterr().err
    assert re.search(r"(?:^|\s)labels=waiting from=2026-08-01(?:\s|$)", err)
    stats = json.loads((Path(env["AUSMT_DATA_DIR"]) / "gateway" / "state" / "stats.json")
                       .read_text(encoding="utf-8"))
    assert "labels_since" not in stats and "operator" not in stats["totals"]


# ---- grain and stamping -------------------------------------------------------------------------
def test_operator_blocks_month_and_cumulative_only():
    """The operator block lives in totals and on the month row only: no day row and no archive line
    carries an operator key."""
    days = ("2026-07-10", "2026-07-11")
    lines = [ln for d in days for ln in _mixed_day(d)] + \
        [("box", ln) for d in days for ln in _box_day(d)]
    stats, archive = _fold(lines, labels_from="2026-07-01", operator_nets=_nets())
    assert stats["totals"]["operator"]["visits"] == 2
    assert stats["monthly"][0]["operator"]["visits"] == 2
    for row in stats["daily"]:
        assert not set(row) & {"operator", "labels", "crawler_excluded"}, row
    assert archive
    for line in archive:
        assert "operator" not in json.dumps(line), line


def test_labels_since_stamped_once():
    """labels_since is the first labelled day folded, and a later fold never moves it, even with a
    different switch date or with labels switched off."""
    first, _ = _fold(_mixed_day("2026-07-10"), labels_from="2026-07-01", operator_nets=_nets())
    assert first["labels_since"] == "2026-07-01"
    run2 = _RUN + dt.timedelta(days=2)
    second, _ = _fold(_mixed_day("2026-07-12"), prev=json.loads(json.dumps(first)), run=run2,
                      labels_from="2026-07-12", operator_nets=_nets())
    assert second["labels_since"] == "2026-07-01"
    third, _ = _fold(_mixed_day("2026-07-13"), prev=json.loads(json.dumps(second)),
                     run=run2 + dt.timedelta(days=1))
    assert third["labels_since"] == "2026-07-01"
    # An existing file is stamped at the first day this fold could label, never earlier.
    prior = {"schema": 2, "last_folded_date": "2026-07-08", "daily": [], "monthly": []}
    late, _ = _fold(_mixed_day("2026-07-10"), prev=prior, labels_from="2026-07-01",
                    operator_nets=_nets())
    assert late["labels_since"] == "2026-07-09"


def test_label_code_exception_falls_back_to_unknown(tmp_path, monkeypatch, capsys):
    """A fault in the label code costs the label, never the fold: with the operator lookup raising,
    stats.json is written, the totals equal an unlabelled fold, and the journal counts one fallback
    for the one admitted line on a labelled day."""
    def explode(*_a, **_k):
        raise RuntimeError("label lookup fault")

    root_off, root_on = tmp_path / "off", tmp_path / "on"
    for root in (root_off, root_on):
        root.mkdir()
        logs = root / "data" / "logs" / "caddy"
        logs.mkdir(parents=True)
        (root / "data" / "gateway" / "state").mkdir(parents=True)
        (logs / "access.json").write_text(
            _line("/data/catalogue.json", "198.51.100.0", date="2026-07-11") + "\n"
            + _line("/data/catalogue.json", "198.51.100.0", date="2026-07-12") + "\n",
            encoding="utf-8")
    base = {"AUSMT_STATS_DBIP_CSV": str(_DBIP)}
    _run_main(monkeypatch, {**base, "AUSMT_DATA_DIR": str(root_off / "data")},
              "2026-07-12T03:30:00Z")
    capsys.readouterr()
    monkeypatch.setattr(AGG, "_operator_label", explode)
    _run_main(monkeypatch, {**base, "AUSMT_DATA_DIR": str(root_on / "data")},
              "2026-07-12T03:30:00Z", AUSMT_STATS_LABELS_FROM="2026-07-01")
    err = capsys.readouterr().err
    off = json.loads((root_off / "data" / "gateway" / "state" / "stats.json").read_text("utf-8"))
    on = json.loads((root_on / "data" / "gateway" / "state" / "stats.json").read_text("utf-8"))
    assert on["totals"]["visits"] == 1
    assert _strip_labels(on)["totals"] == off["totals"]
    assert on["totals"]["operator"]["visits"] == 0
    assert re.search(r"(?:^|\s)label_fallbacks=1(?:\s|$)", err), err
    assert "label lookup fault" not in err
