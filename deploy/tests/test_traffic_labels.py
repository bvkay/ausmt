"""Request label pins: operator, client class and network type on the usage statistics.

Every address in this file is a documentation address (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24,
2001:db8::/32) or one of the internal ranges the operator rule names. Pure stdlib python and committed
fixtures, so the file runs everywhere and never trips the CI skip tripwire.
"""
from __future__ import annotations

import copy
import datetime as dt
import importlib.util
import json
from pathlib import Path

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
