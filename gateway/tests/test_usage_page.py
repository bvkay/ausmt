"""The curator Usage page: its shell seam, its rail entry and the helpers it renders with.

Each test states what must hold and how it fails. Async bodies run under conftest.run().
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import math
import re
import time
from html.parser import HTMLParser
from pathlib import Path

import pytest

from gateway import curatorpage, serve_state, usagepage
from gateway.tests.conftest import app_client, curator_login, run
from gateway.tests.usage_helpers import (card, fetch, row_values, sections, table_head, table_rows,
                                         text, tile)

_REPO = Path(__file__).resolve().parents[2]

# SHA-256 of _head("x") and of _shell("x", "<p>b</p>", nav=_golden_nav()), as rendered before the
# page could add a style block or a shell class, with the rail label ">Analytics<" replaced by
# ">Usage<". Every page that adds neither must still render exactly these bytes.
_HEAD_DIGEST = "2f9fc67c12ecf2be01ada8ab3f327876b0c240a177cc3bdee6d2f773e1896c26"
_SHELL_DIGEST = "3945a93c30a540f6f70159fde74304156959c179d3d8f51aeba3c1c5e681dc03"


def _golden_nav() -> curatorpage.NavContext:
    return curatorpage.NavContext(active="queue", crumb="<b>Queue</b>", published_head="0123abc",
                                  published_available=True, csrf="csrf-token")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_stats(cfg) -> None:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    doc = {"schema": 2, "timer_period_min": 1440, "generated_at": now, "since": "2026-07-08",
           "last_folded_date": "2026-07-11",
           "totals": {"downloads": 3, "visits": 5, "download_bytes": 3000, "unattributed": 0},
           "countries": {"AU": 4, "unknown": 1},
           "daily": [{"date": "2026-07-11", "downloads": 3, "visits": 5}]}
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    (cfg.state_dir / serve_state.STATS_FILENAME).write_text(json.dumps(doc), encoding="utf-8")


def test_shell_matches_golden_digest_except_rail_label():
    """A page that adds no style block and no shell class renders the head and the shell byte for
    byte as before, apart from the rail label, which now reads Usage. FAILS IF the shared head, the
    rail, the context bar or the shell wrapper changes in any other byte, or the label is not Usage."""
    assert _sha(curatorpage._head("x")) == _HEAD_DIGEST
    assert _sha(curatorpage._head("x", "")) == _HEAD_DIGEST
    shell = curatorpage._shell("x", "<p>b</p>", nav=_golden_nav())
    assert ">Analytics<" not in shell and ">Usage<" in shell
    assert _sha(shell) == _SHELL_DIGEST
    assert _sha(curatorpage._shell("x", "<p>b</p>", nav=_golden_nav(), extra_head="",
                                   page_class="")) == _SHELL_DIGEST


def test_one_page_can_add_a_style_block_and_a_shell_class():
    """A page may add one block just before the end of the head and one class on the shell div, and
    nothing else moves. FAILS IF the block lands anywhere but directly before the end of the head,
    appears twice, or the class is not on the shell div."""
    block = "<style>.u-x{color:#231F20}</style>"
    head = curatorpage._head("x", block)
    assert head.count(block) == 1 and head.count("</head>") == 1
    assert "</style>" + block + "</head>" in head
    assert head.replace(block, "") == curatorpage._head("x")
    shell = curatorpage._shell("x", "<p>b</p>", nav=_golden_nav(), extra_head=block,
                               page_class="usage")
    assert '<div class="shell usage">' in shell and '<div class="shell">' not in shell
    plain = curatorpage._shell("x", "<p>b</p>", nav=_golden_nav())
    assert shell.replace(block, "").replace('<div class="shell usage">', '<div class="shell">') == plain


def test_other_pages_get_no_usage_theme(tmp_path):
    """The serve and queue pages carry neither the Usage shell class nor the Usage light tokens.
    FAILS IF the Usage theme leaks onto another curator page."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, _cfg):
            await curator_login(client)
            for path in ("/gateway/curator/serve", "/gateway/curator/queue"):
                r = await client.get(path)
                assert r.status_code == 200, path
                assert "shell usage" not in r.text and "--s-visits" not in r.text, path
                assert '<div class="shell">' in r.text, path
    run(_body())


def test_usage_heading_title_and_rail_label(tmp_path):
    """The rail entry for the analytics route reads Usage on every curator page, under Operations,
    with its key and route unchanged, and the page it leads to is titled AusMT usage with the heading
    and crumb Usage. FAILS IF the label still reads Analytics, the route moves, a page highlights the
    entry when it is not the analytics page, or the old title, heading or crumb returns."""
    entries = {key: (group, label, href) for group, items in curatorpage._RAIL
               for key, label, href in items}
    assert entries["analytics"] == ("Operations", "Usage", "/gateway/curator/analytics")
    assert all(label != "Analytics" for _g, label, _h in entries.values())

    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg)
            r = await client.get("/gateway/curator/analytics")
            assert r.status_code == 200
            assert '<a class="railitem on" href="/gateway/curator/analytics">Usage</a>' in r.text
            assert "<title>AusMT usage</title>" in r.text and "<h1>Usage</h1>" in r.text
            assert '<div class="crumb"><b>Usage</b></div>' in r.text
            assert "Usage analytics" not in r.text
            r = await client.get("/gateway/curator/serve")
            assert '<a class="railitem" href="/gateway/curator/analytics">Usage</a>' in r.text
            assert ">Analytics<" not in r.text
    run(_body())


# The system copy of the officially assigned ISO 3166-1 alpha-2 codes, shipped with the time zone
# database. XK is user-assigned, so it is never in that list but does appear in the country data.
_ISO3166_TAB = Path("/usr/share/zoneinfo/iso3166.tab")
_USER_ASSIGNED = {"XK"}


def test_country_names_resolve_and_unknown_codes_show_as_stored():
    """A stored country code reads as its English name, and any value the table does not hold reads
    exactly as stored, so the unknown bucket and an unexpected code are never renamed or dropped.
    Every entry is a two-letter upper-case code with a plain, unique name. FAILS IF a fixture code
    does not resolve, an unknown value is altered, or an entry is malformed."""
    from gateway import countrynames

    for code, name in (("AU", "Australia"), ("NZ", "New Zealand"), ("US", "United States"),
                       ("GB", "United Kingdom"), ("DE", "Germany"), ("JP", "Japan"),
                       ("CD", "Democratic Republic of the Congo"), ("XK", "Kosovo")):
        assert countrynames.country_name(code) == name, code
    for stored in ("unknown", "", "ZZ", "au", "A1", "AUS", " AU"):
        assert countrynames.country_name(stored) == stored, repr(stored)

    names = countrynames.COUNTRY_NAMES
    assert all(re.fullmatch(r"[A-Z]{2}", code) for code in names), sorted(names)
    assert all(isinstance(n, str) and n and n == n.strip() for n in names.values())
    assert len(set(names.values())) == len(names), "two codes share one name"
    assert not [n for n in names.values() if re.search("[\u2013\u2014]", n)]


def test_country_names_cover_every_assigned_iso_code():
    """The table holds every officially assigned ISO 3166-1 alpha-2 code in the system list, plus the
    user-assigned XK, and nothing else. FAILS IF an assigned code is missing or an unassigned code is
    present."""
    if not _ISO3166_TAB.is_file():
        pytest.skip(f"{_ISO3166_TAB} is not present on this host, so there is no list to compare with")
    from gateway import countrynames

    assigned = {ln.split("\t", 1)[0] for ln in _ISO3166_TAB.read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.startswith("#")}
    assert len(assigned) >= 249
    held = set(countrynames.COUNTRY_NAMES)
    assert sorted(assigned - held) == [], "assigned codes with no name"
    assert sorted(held - assigned - _USER_ASSIGNED) == [], "codes that are not assigned"
    assert _USER_ASSIGNED <= held


# ------------------------------------------------------------------------------------------------
# Day-by-day charts and their table twin, as pure functions of the daily rows.

class _Tree(HTMLParser):
    """A flat list of elements, each with its attributes, its parent's index and the text of its own
    title child, so a test can ask what a mark carries without trusting the renderer's spacing."""

    def __init__(self, text: str):
        super().__init__(convert_charrefs=True)
        self.els: list[dict] = []
        self._stack: list[int] = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        parent = self._stack[-1] if self._stack else None
        self.els.append({"tag": tag, "attrs": dict(attrs), "parent": parent, "text": "",
                         "title": None})
        self._stack.append(len(self.els) - 1)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self._stack.pop()

    def handle_endtag(self, tag):
        while self._stack:
            idx = self._stack.pop()
            if self.els[idx]["tag"] == tag:
                break

    def handle_data(self, data):
        if not self._stack:
            return
        idx = self._stack[-1]
        el = self.els[idx]
        el["text"] += data
        if el["tag"] == "title" and el["parent"] is not None:
            parent = self.els[el["parent"]]
            parent["title"] = (parent["title"] or "") + data

    def find(self, tag: str, cls: str | None = None) -> list[dict]:
        return [e for e in self.els if e["tag"] == tag
                and (cls is None or cls in e["attrs"].get("class", "").split())]


def _days(first: str, values: list, key: str = "visits") -> list[dict]:
    """Daily rows from `first`, one per value; None leaves that day without a row."""
    start = dt.date.fromisoformat(first)
    rows = []
    for i, v in enumerate(values):
        if v is None:
            continue
        row = {"date": (start + dt.timedelta(days=i)).isoformat(), "kinds": {}}
        if key == "visits":
            row["visits"] = v
        else:
            row["kinds"][key] = v
        rows.append(row)
    return rows


def _chart(rows, measure="visits"):
    from gateway import usagepage
    span = usagepage._day_span(rows, rows[-1]["date"] if rows else None)
    return usagepage._day_chart(rows, measure, *span), span


def _bar_geometry(path_d: str) -> tuple[float, float, float]:
    """(x, bar width, top y) of one column path drawn as M x,y0 V .. Q .. H .. Q .. V y0 Z."""
    m = re.fullmatch(r"M([\d.]+),114 V([\d.]+) Q([\d.]+),([\d.]+) ([\d.]+),([\d.]+) "
                     r"H([\d.]+) Q([\d.]+),([\d.]+) ([\d.]+),([\d.]+) V114 Z", path_d)
    assert m, path_d
    x, x_right, yt = float(m.group(1)), float(m.group(8)), float(m.group(4))
    return x, x_right - x, yt


def test_day_chart_geometry():
    """Each chart has exactly three integer ticks, 0, half and top, where top is the smallest of 10,
    20, 50, 100 and so on that holds the peak; one peak label above the earliest tallest column; a
    column width of 2.9 units at 184 days and 9.9 at 55; a rounded data end on a square baseline; and
    an inline minimum width of max(640, 4N + 56). FAILS IF the axis is not a 1, 2 or 5 step floored at
    10, a tick is not an integer, the peak label repeats or moves, or the column frame drifts."""
    from gateway import usagepage

    values = [(i * 7) % 60 for i in range(184)]
    values[100] = 73
    values[150] = 73
    svg, (first, last) = _chart(_days("2026-05-01", values))
    assert (last - first).days + 1 == 184
    tree = _Tree(svg)
    root = tree.find("svg")[0]["attrs"]
    assert root["viewbox"] == "0 0 960 118"
    assert root["width"] == "792" and root["style"] == "min-width:792px;width:100%"
    assert len(tree.find("line", "u-axis")) == 1 and len(tree.find("line", "u-grid")) == 2
    assert [t["text"] for t in tree.find("text", "u-tick")] == ["0", "50", "100"]
    peaks = tree.find("text", "u-vlabel")
    assert len(peaks) == 1 and peaks[0]["text"] == "73"
    bars = {int(b["attrs"]["data-i"]): b for b in tree.find("path", "u-bar")}
    x, bw, yt = _bar_geometry(bars[100]["attrs"]["d"])
    assert bw == pytest.approx(2.9, abs=0.011)
    assert x == pytest.approx(46 + 100 * 904 / 184 + (904 / 184 - 2.9) / 2, abs=0.011)
    assert yt == pytest.approx(114 - 96 * 73 / 100, abs=0.011)
    assert float(peaks[0]["attrs"]["x"]) == pytest.approx(x + bw / 2, abs=0.011)
    assert "Q" in bars[100]["attrs"]["d"] and bars[100]["attrs"]["d"].endswith("V114 Z")
    assert "u-s-visits" in bars[100]["attrs"]["class"].split()

    svg55, _span = _chart(_days("2026-05-01", [5] * 54 + [3]))
    tree55 = _Tree(svg55)
    assert tree55.find("svg")[0]["attrs"]["width"] == "640"
    _x, bw55, _yt = _bar_geometry(tree55.find("path", "u-bar")[0]["attrs"]["d"])
    assert bw55 == pytest.approx(9.9, abs=0.011)
    assert [t["text"] for t in tree55.find("text", "u-tick")] == ["0", "5", "10"]
    assert [int(p["attrs"]["data-i"]) for p in tree55.find("path", "u-bar")] == list(range(55))
    assert tree55.find("text", "u-vlabel")[0]["text"] == "5"
    assert float(tree55.find("text", "u-vlabel")[0]["attrs"]["x"]) == pytest.approx(
        46 + (904 / 55 - 9.9) / 2 + 9.9 / 2, abs=0.011)

    for peak, ticks in ((10, ["0", "5", "10"]), (11, ["0", "10", "20"]), (199, ["0", "100", "200"]),
                        (501, ["0", "500", "1,000"]), (12000, ["0", "10K", "20K"]),
                        (49000, ["0", "25K", "50K"])):
        svg_p, _s = _chart(_days("2026-05-01", [1, peak, 2]))
        assert [t["text"] for t in _Tree(svg_p).find("text", "u-tick")] == ticks, peak
    assert usagepage._axis_top(0) == 10 and usagepage._axis_top(1000) == 1000
    assert usagepage._axis_top(1001) == 2000

    tiny, _s = _chart(_days("2026-05-01", [0, 1, 0]))
    _x, _bw, yt_tiny = _bar_geometry(_Tree(tiny).find("path", "u-bar")[0]["attrs"]["d"])
    assert yt_tiny == pytest.approx(114 - 9.6, abs=0.011)
    flat, _s = _chart(_days("2026-05-01", [0, 0, 0]))
    assert _Tree(flat).find("text", "u-vlabel") == [] and _Tree(flat).find("path", "u-bar") == []


def test_day_chart_empty_and_gaps():
    """No daily row draws no chart. A day with no row keeps its hover slot but draws no column and
    reads 'no row'; a row without the measure reads 'not measured'; a measured zero reads 0 and draws
    no column. FAILS IF an empty series draws an SVG, a gap or an unmeasured day draws a column, or
    any of the three reads as another."""
    from gateway import usagepage

    assert usagepage._day_span([], "2026-07-11") is None
    assert usagepage._day_span([{"date": "not a day"}, "x", None], None) is None

    rows = [{"date": "2026-07-01", "visits": 4, "kinds": {"bundle": 2}},
            {"date": "2026-07-03", "kinds": {}},
            {"date": "2026-07-04", "visits": 0},
            {"date": "2026-07-05", "visits": 6, "kinds": {"file": 9}}]
    first, last = usagepage._day_span(rows, "2026-07-05")
    assert (first, last) == (dt.date(2026, 7, 1), dt.date(2026, 7, 5))
    visits = _Tree(usagepage._day_chart(rows, "visits", first, last))
    hits = {int(h["attrs"]["data-i"]): h for h in visits.find("rect", "u-hit")}
    assert sorted(hits) == [0, 1, 2, 3, 4]
    assert [hits[i]["attrs"]["data-v"] for i in range(5)] == ["4", "no row", "not measured", "0", "6"]
    assert hits[1]["title"] == "2 Jul: no row" and hits[2]["title"] == "3 Jul: not measured"
    assert hits[3]["title"] == "4 Jul: 0"
    assert sorted(int(b["attrs"]["data-i"]) for b in visits.find("path", "u-bar")) == [0, 4]

    bundles = _Tree(usagepage._day_chart(rows, "bundles", first, last))
    hits = {int(h["attrs"]["data-i"]): h for h in bundles.find("rect", "u-hit")}
    assert [hits[i]["attrs"]["data-v"] for i in range(5)] == ["2", "no row", "0", "not measured", "0"]
    assert sorted(int(b["attrs"]["data-i"]) for b in bundles.find("path", "u-bar")) == [0]
    files = _Tree(usagepage._day_chart(rows, "files", first, last))
    hits = {int(h["attrs"]["data-i"]): h for h in files.find("rect", "u-hit")}
    assert [hits[i]["attrs"]["data-v"] for i in range(5)] == ["0", "no row", "0", "not measured", "9"]

    for bad in ("7", -1, True, 2.5, None, [3]):
        tree = _Tree(usagepage._day_chart([{"date": "2026-07-01", "visits": bad}], "visits",
                                          dt.date(2026, 7, 1), dt.date(2026, 7, 1)))
        assert tree.find("rect", "u-hit")[0]["attrs"]["data-v"] == "not measured", repr(bad)
        assert tree.find("path", "u-bar") == []

    assert usagepage._day_span([{"date": "2026-07-09"}], None) == (dt.date(2026, 7, 9),
                                                                    dt.date(2026, 7, 9))
    assert usagepage._day_span([{"date": "2026-07-20"}], "2026-07-11") is None


def test_day_chart_axis_labels_thin_out():
    """Only the station files chart, the last of the three, carries the date axis. Up to 45 days it
    labels every seventh day from the first; beyond that it labels the first day and each month's
    first day; a label within 44 units of the one before it is dropped. FAILS IF another chart draws
    dates, the step is wrong, or two labels crowd each other."""
    from gateway import usagepage

    def dates(rows, measure):
        span = usagepage._day_span(rows, rows[-1]["date"])
        tree = _Tree(usagepage._day_chart(rows, measure, *span))
        return tree, [(t["text"], float(t["attrs"]["x"])) for t in tree.find("text", "u-date")]

    short = [{"date": (dt.date(2026, 7, 1) + dt.timedelta(days=i)).isoformat(), "visits": 1,
              "kinds": {"file": 1}} for i in range(30)]
    tree, labels = dates(short, "files")
    assert [t for t, _x in labels] == ["1 Jul", "8 Jul", "15 Jul", "22 Jul", "29 Jul"]
    assert tree.find("svg")[0]["attrs"]["viewbox"] == "0 0 960 138"
    assert dates(short, "visits")[1] == [] and dates(short, "bundles")[1] == []
    assert _Tree(usagepage._day_chart(short, "visits", dt.date(2026, 7, 1),
                                      dt.date(2026, 7, 30))).find("svg")[0]["attrs"][
        "viewbox"] == "0 0 960 118"

    long_rows = [{"date": (dt.date(2026, 5, 31) + dt.timedelta(days=i)).isoformat(),
                  "kinds": {"file": 2}} for i in range(184)]
    _tree, labels = dates(long_rows, "files")
    assert [t for t, _x in labels] == ["31 May", "1 Jul", "1 Aug", "1 Sep", "1 Oct", "1 Nov"]
    assert all(b - a >= 44 for (_t1, a), (_t2, b) in zip(labels, labels[1:]))
    assert labels[0][1] == pytest.approx(46 + 904 / 184 / 2, abs=0.011)

    exact = [{"date": (dt.date(2026, 7, 1) + dt.timedelta(days=i)).isoformat(),
              "kinds": {"file": 1}} for i in range(45)]
    assert [t for t, _x in dates(exact, "files")[1]] == [
        "1 Jul", "8 Jul", "15 Jul", "22 Jul", "29 Jul", "5 Aug", "12 Aug"]
    over = exact + [{"date": "2026-08-15", "kinds": {"file": 1}}]
    assert [t for t, _x in dates(over, "files")[1]] == ["1 Jul", "1 Aug"]


def test_day_chart_caps_span_at_366_days():
    """With pruning switched off the daily rows can outgrow a year; the charts then draw the latest
    366 days ending at the data date, and the table twin still lists every row. FAILS IF a chart
    draws more than 366 slots, the drawn span does not end at the data date, or the twin drops a row."""
    from gateway import usagepage

    start = dt.date(2025, 6, 1)
    rows = [{"date": (start + dt.timedelta(days=i)).isoformat(), "visits": i % 9,
             "kinds": {"bundle": 1, "file": 3}} for i in range(400)]
    last_day = start + dt.timedelta(days=399)
    first, last = usagepage._day_span(rows, last_day.isoformat())
    assert last == last_day and (last - first).days + 1 == 366
    tree = _Tree(usagepage._day_chart(rows, "visits", first, last))
    hits = tree.find("rect", "u-hit")
    assert len(hits) == 366
    assert hits[0]["attrs"]["data-day"] == first.isoformat()
    assert hits[-1]["attrs"]["data-day"] == last_day.isoformat()
    assert tree.find("svg")[0]["attrs"]["width"] == str(4 * 366 + 56)
    wide = _Tree(usagepage._day_chart(rows, "visits", start, last_day))
    assert len(wide.find("rect", "u-hit")) == 366
    twin = _Tree(usagepage._day_table(rows, [], first, last))
    assert len(twin.find("th", None)) - 6 == 400


def test_every_mark_has_a_title():
    """Every column and every transparent hover slot carries a title of the form 'd Mon: value', and
    the slot carries the hover data the read-out uses, including the slot centre the server wrote.
    Each chart is an image labelled by its own title, names its measure, and has one hidden
    crosshair. FAILS IF a mark is untitled, a title disagrees with its data, the centre is wrong, or
    the chart is not labelled."""
    from gateway import usagepage

    rows = [{"date": "2026-10-30", "visits": 1200, "kinds": {"bundle": 3, "file": 40}},
            {"date": "2026-11-01", "visits": 1200, "kinds": {"bundle": 0, "file": 41}},
            {"date": "2026-11-02", "visits": 5, "kinds": {"bundle": 1}}]
    first, last = usagepage._day_span(rows, "2026-11-02")
    names = {"visits": "Portal visits", "bundles": "Whole-survey bundles downloaded",
             "files": "Station files downloaded"}
    ids = set()
    for measure, name in names.items():
        tree = _Tree(usagepage._day_chart(rows, measure, first, last))
        svg = tree.find("svg")[0]["attrs"]
        assert svg["role"] == "img" and svg["data-u-chart"] == measure
        assert svg["data-u-name"] == name
        titles = [t for t in tree.find("title") if tree.els[t["parent"]]["tag"] == "svg"]
        assert len(titles) == 1 and titles[0]["attrs"]["id"] == svg["aria-labelledby"]
        ids.add(svg["aria-labelledby"])
        assert titles[0]["text"].startswith(f"{name} per day, 30 Oct 2026 to 2 Nov 2026; ")
        assert titles[0]["text"].endswith("; table below")
        crosses = tree.find("line", "u-cross")
        assert len(crosses) == 1 and crosses[0]["attrs"].get("visibility") == "hidden"
        slot = 904 / 4
        for h in tree.find("rect", "u-hit"):
            i = int(h["attrs"]["data-i"])
            day = first + dt.timedelta(days=i)
            assert h["attrs"]["data-day"] == day.isoformat()
            assert h["attrs"]["data-label"] == f"{day.day} {day:%b}"
            assert h["title"] == f'{h["attrs"]["data-label"]}: {h["attrs"]["data-v"]}'
            assert float(h["attrs"]["data-cx"]) == pytest.approx(46 + i * slot + slot / 2, abs=0.011)
            assert float(h["attrs"]["x"]) == pytest.approx(46 + i * slot, abs=0.011)
        hits = {h["attrs"]["data-i"]: h for h in tree.find("rect", "u-hit")}
        for b in tree.find("path", "u-bar"):
            assert b["title"] and b["title"] == hits[b["attrs"]["data-i"]]["title"]
    assert len(ids) == 3
    visits = _Tree(usagepage._day_chart(rows, "visits", first, last))
    assert [h["attrs"]["data-v"] for h in visits.find("rect", "u-hit")] == ["1,200", "no row",
                                                                            "1,200", "5"]
    head = [t for t in visits.find("title") if visits.els[t["parent"]]["tag"] == "svg"][0]["text"]
    assert head == "Portal visits per day, 30 Oct 2026 to 2 Nov 2026; peak 1,200 on 30 Oct; table below"
    files = _Tree(usagepage._day_chart(rows, "files", first, last))
    assert [h["attrs"]["data-v"] for h in files.find("rect", "u-hit")] == ["40", "no row", "41", "0"]
    nothing = _Tree(usagepage._day_chart([{"date": "2026-11-02", "visits": 0}], "visits",
                                         dt.date(2026, 11, 2), dt.date(2026, 11, 2)))
    head = [t for t in nothing.find("title") if nothing.els[t["parent"]]["tag"] == "svg"][0]["text"]
    assert "peak" not in head and head.endswith("; table below")


def _twin_rows(tree: _Tree) -> list[list[str]]:
    out = []
    for idx in [i for i, e in enumerate(tree.els) if e["tag"] == "tr"]:
        cells = [e["text"] for e in tree.els if e["parent"] == idx and e["tag"] in ("th", "td")]
        out.append(cells)
    return out


def test_day_twin_lists_every_row_newest_first():
    """The table twin sits in a collapsed details block summarised 'Show as a table' and lists every
    daily row held, newest first, with the columns Day, Visits, Bundles, Station files, Hand-offs and
    API. Its caption says when the drawn span has days with no row and when your own requests are left
    out from a day inside it. A missing figure reads 'not measured'. FAILS IF a row is dropped or out
    of order, the details opens by default, a header lacks its scope, or a missing figure reads 0."""
    from gateway import usagepage

    rows = [{"date": "2026-07-01", "visits": 4, "kinds": {"bundle": 2, "file": 1300},
             "api_requests": 3},
            {"date": "2026-07-04", "visits": 2, "api_requests": 0},
            {"date": "2026-07-03", "visits": 1, "kinds": {}}]
    first, last = usagepage._day_span(rows, "2026-07-04")
    out = usagepage._day_table(rows, [], first, last)
    tree = _Tree(out)
    details = tree.find("details")
    assert len(details) == 1 and "open" not in details[0]["attrs"]
    assert [s["text"] for s in tree.find("summary")] == ["Show as a table"]
    assert len(tree.find("div", "u-scroll")) == 1
    assert tree.find("caption")[0]["text"] == ("Every daily row held, newest first; days with no row "
                                               "are blank on the charts")
    table = _twin_rows(tree)
    assert table[0] == ["Day", "Visits", "Bundles", "Station files", "Hand-offs", "API"]
    assert all(th["attrs"].get("scope") == "col" for th in tree.find("th")
               if th["text"] in table[0])
    assert table[1:] == [["4 Jul 2026", "2", "not measured", "not measured", "not measured", "0"],
                         ["3 Jul 2026", "1", "0", "0", "not measured", "not measured"],
                         ["1 Jul 2026", "4", "2", "1,300", "not measured", "3"]]
    assert [th["attrs"].get("scope") for th in tree.find("th") if th["text"].endswith("2026")] == [
        "row"] * 3

    full = usagepage._day_table(rows + [{"date": "2026-07-02"}], [], first, last,
                                labels_since="2026-07-03")
    assert _Tree(full).find("caption")[0]["text"] == (
        "Every daily row held, newest first; your own requests left out from 3 Jul")
    outside = usagepage._day_table(rows, [], first, last, labels_since="2026-06-30")
    assert "your own requests" not in outside
    assert "your own requests" not in usagepage._day_table(rows, [], first, last,
                                                           labels_since="soon")
    assert usagepage._day_table([], [], dt.date(2026, 7, 4), dt.date(2026, 7, 4)) == ""
    assert usagepage._day_table([{"date": "bad"}], [], dt.date(2026, 7, 4),
                                dt.date(2026, 7, 4)) == ""


def test_day_handoffs_read_zero_only_inside_a_measured_month():
    """A day's hand-off cell shows the day's own count when the day carries a hand-off block. A day
    with no block reads 0 only when its calendar month carries a hand-off block, and not measured
    otherwise. FAILS IF a day in a month counted before hand-offs existed reads 0, or a day in a
    measured month with no hand-off reads not measured."""
    from gateway import usagepage

    rows = [{"date": "2026-06-30", "visits": 1},
            {"date": "2026-07-01", "visits": 1},
            {"date": "2026-07-02", "visits": 1, "handoffs": {"requests": 7, "bytes": 9}}]
    monthly = [{"month": "2026-06", "visits": 1},
               {"month": "2026-07", "visits": 2, "handoffs": {"requests": 7}},
               "not a month"]
    tree = _Tree(usagepage._day_table(rows, monthly, dt.date(2026, 6, 30), dt.date(2026, 7, 2)))
    cells = {r[0]: r[4] for r in _twin_rows(tree)[1:]}
    assert cells == {"2 Jul 2026": "7", "1 Jul 2026": "0", "30 Jun 2026": "not measured"}
    odd = [{"date": "2026-07-03", "handoffs": {"requests": "7"}}]
    tree = _Tree(usagepage._day_table(odd, monthly, dt.date(2026, 7, 3), dt.date(2026, 7, 3)))
    assert _twin_rows(tree)[1][4] == "not measured"


def test_day_grain_carries_only_its_five_measures():
    """Only the date, visits, bundles, station files, API requests and hand-off requests of a daily
    row reach a chart, the table twin or any data attribute. A place, a label, a survey, a format, a
    byte count or any other field a daily row may carry never does. FAILS IF a planted value from
    any other field appears anywhere in the output."""
    from gateway import usagepage

    planted = {"downloads": 913517, "download_bytes": 913518, "formats": {"mth5": 913519},
               "countries": {"NZ": 913520}, "by_state": {"TAS": 913521},
               "by_country_detail": {"NZ": {"visits": 913522}}, "networks": 913523,
               "labels": {"downloads": {"operator": 913524}}, "surveys": {"Planted survey": 913525},
               "downloads_by_client": {"browser": 913526}, "by_collection": {"Planted col": 913527},
               "unattributed": 913528, "kinds": {"bundle": 2, "file": 3, "zz-kind": 913529},
               "handoffs": {"requests": 4, "bytes": 913530, "by_survey": {"planted-slug": 913531},
                            "by_route": {"r": 913532}}}
    rows = [dict({"date": "2026-07-01", "visits": 5, "api_requests": 6}, **planted)]
    span = (dt.date(2026, 7, 1), dt.date(2026, 7, 1))
    out = "".join([usagepage._day_chart(rows, m, *span) for m in ("visits", "bundles", "files")]
                  + [usagepage._day_table(rows, [{"month": "2026-07", "handoffs": {}}], *span)])
    for needle in ("9135", "913,", "mth5", "NZ", "TAS", "Planted", "planted", "zz-kind", "operator",
                   "browser", "New Zealand", "Tasmania"):
        assert needle not in out, needle
    values = {v for e in _Tree(out).els for k, v in e["attrs"].items() if k == "data-v"}
    assert values == {"5", "2", "3"}
    cells = _twin_rows(_Tree(usagepage._day_table(rows, [], *span)))[1]
    assert cells == ["1 Jul 2026", "5", "2", "3", "4", "6"]
    data_keys = {k for e in _Tree(out).els for k in e["attrs"] if k.startswith("data-")}
    assert data_keys == {"data-u-chart", "data-u-name", "data-i", "data-day", "data-label",
                         "data-v", "data-cx"}


# ------------------------------------------------------------------------------------------------
# The state card's visit figures, reconciled with the Australian visits of the countries card.

def _state_stats(au_visits=20, **over):
    stats = {"countries": {"AU": 40, "NZ": 3, "unknown": 2},
             "by_country_detail": {"AU": {"visits": au_visits, "downloads": 9},
                                   "NZ": {"visits": 3}},
             "by_state": {"NSW": 10, "VIC": 5, "TAS": 3, "QLD": 0, "unattributed": 2},
             "by_state_detail": {"NSW": {"visits": 6, "downloads": 1}, "VIC": {"visits": 9},
                                 "unattributed": {"visits": 1}}}
    if au_visits is None:
        del stats["by_country_detail"]["AU"]
    stats.update(over)
    return stats


def test_state_card_reconciles_with_the_countries_card():
    """The state rows name only the eight states and territories the fold counted, biggest visits
    first, with a state that has no detail row reading not measured after them. The remainder 'Not
    placed in a state' is the Australian visits less the named state visits, and the total is the
    Australian visits of the country detail, the same figure the countries card prints. When the
    named states exceed that total, or state detail exists with no Australian detail, the rows are
    withheld as not reconciled. FAILS IF named rows plus the remainder do not equal the total, the
    total is not the country detail figure, the unattributed bucket or a zero state becomes a row,
    or a figure that cannot reconcile is shown."""
    from gateway import usagepage

    stats = _state_stats()
    rows, remainder, total, ok = usagepage._state_visit_rows(stats)
    assert ok is True
    assert rows == [("VIC", "Victoria", 9), ("NSW", "New South Wales", 6), ("TAS", "Tasmania", None)]
    assert total == stats["by_country_detail"]["AU"]["visits"] == 20
    assert remainder == 5
    assert sum(v for _c, _n, v in rows if v is not None) + remainder == total

    rows, remainder, total, ok = usagepage._state_visit_rows(_state_stats(au_visits=15))
    assert (remainder, total, ok) == (0, 15, True)
    _rows, _rem, _total, ok = usagepage._state_visit_rows(_state_stats(au_visits=14))
    assert ok is False
    _rows, _rem, _total, ok = usagepage._state_visit_rows(_state_stats(au_visits=None))
    assert ok is False
    _rows, _rem, _total, ok = usagepage._state_visit_rows(
        _state_stats(by_country_detail={"AU": {"downloads": 4}}))
    assert ok is False

    tied = _state_stats(by_state={"WA": 1, "SA": 1, "ACT": 1},
                        by_state_detail={"WA": {"visits": 2}, "SA": {"visits": 2},
                                         "ACT": {"visits": "2"}})
    rows, remainder, total, ok = usagepage._state_visit_rows(tied)
    assert [code for code, _n, _v in rows] == ["SA", "WA", "ACT"]
    assert rows[2] == ("ACT", "Australian Capital Territory", None)
    assert (remainder, total, ok) == (16, 20, True)

    no_detail = _state_stats(by_state_detail={})
    rows, remainder, total, ok = usagepage._state_visit_rows(no_detail)
    assert [v for _c, _n, v in rows] == [None, None, None]
    assert (remainder, total, ok) == (20, 20, True)
    rows, remainder, total, ok = usagepage._state_visit_rows(
        _state_stats(au_visits=None, by_state_detail={}))
    assert len(rows) == 3 and (remainder, total, ok) == (None, None, True)

    for by_state in (None, {}, {"NSW": 0, "unattributed": 0}, {"unattributed": 4}, "NSW",
                     {"Hobart": 5, "nsw": 2}):
        rows, remainder, total, ok = usagepage._state_visit_rows(_state_stats(by_state=by_state))
        assert rows == [] and remainder is None and ok is True, by_state
        assert total == 20
    assert usagepage._state_visit_rows(None) == ([], None, None, True)
    assert usagepage._state_visit_rows({"by_state": {"NSW": True}}) == ([], None, None, True)


# ------------------------------------------------------------------------------------------------
# The page, fetched through its route. Fixtures are invented and carry no address, network or name.

def _month(month: str, days: int, n: int, **over) -> dict:
    """One month row measured under the current rules, its figures scaled by `n`."""
    row = {"month": month, "downloads": 40 * n, "visits": 10 * n, "download_bytes": 1_048_576 * n,
           "unattributed": 0, "api_requests": 3 * n, "days": days, "seeded_days": 0,
           "detail_days": days, "geo_days": days,
           "formats": {"mth5": 12 * n, "edi": 10 * n, "emtfxml": 8 * n, "edi-zip": 5 * n,
                       "xml-zip": 3 * n, "unattributed": 2 * n},
           "kinds": {"file": 30 * n, "bundle": 10 * n},
           "countries": {"AU": 8 * n, "NZ": n, "unknown": 1},
           "handoffs": {"requests": 2 * n, "bytes": 4096 * n},
           "downloads_by_select": {"single": 20 * n, "bulk": 20 * n}, "bulk_export_events": n}
    row.update(over)
    return row


def _labels(n: int, **over) -> dict:
    block = {"labels": {"downloads": {"portal_session|access_provider": 20 * n, "tool|hosting": 15 * n,
                                      "unknown|unknown": 5 * n},
                        "visits": {"portal_session|unknown": 8 * n, "unknown|hosting": n,
                                   "unknown|other": n},
                        "api": {"tool|unknown": 3 * n},
                        "handoffs": {"portal_session|education_research": n, "tool|hosting": n}},
             "operator": {"downloads": 2, "visits": 5, "api": 1, "handoffs": 0, "download_bytes": 9},
             "crawler_excluded": {"downloads": 30, "visits": 4, "api": 0, "handoffs": 0},
             "label_days": 20, "nettype_days": 15, "nettype_full_days": 10, "operator_list_days": 12}
    block.update(over)
    return block


_D = dt.date(2026, 11, 18)


def _full_stats(**over) -> dict:
    """The fullest page: twelve months to the month in progress, the last full month labelled with
    every warning clause, a partly counted month before it, ten surveys, nine countries, seven
    states, six formats and 184 daily rows that span the label start."""
    months = []
    year, mon = 2025, 12
    for i in range(12):
        key = f"{year:04d}-{mon:02d}"
        days = 18 if key == "2026-11" else 30
        row = _month(key, days, i + 1)
        if key == "2026-10":
            row.update(_labels(11, days=31))
            row["days"] = 31
        if key == "2026-11":
            row.update(_labels(12, label_days=18, nettype_days=18, nettype_full_days=18,
                               operator_list_days=18))
        months.append(row)
        year, mon = (year + 1, 1) if mon == 12 else (year, mon + 1)
    daily = []
    for i in range(184):
        day = _D - dt.timedelta(days=183 - i)
        daily.append({"date": day.isoformat(), "visits": (i * 7) % 23, "downloads": (i * 5) % 40,
                      "api_requests": i % 4, "kinds": {"file": (i * 11) % 90, "bundle": i % 6},
                      "handoffs": {"requests": i % 3}})
    surveys = {f"Survey {chr(65 + i)} {2000 + i}": {"downloads": 500 - 40 * i} for i in range(10)}
    surveys["Survey K 2010"] = {"downloads": 7}
    countries = {code: 900 - 90 * i for i, code in
                 enumerate(("AU", "JP", "US", "NZ", "DE", "GB", "CN", "IT", "SG", "BR"))}
    countries["unknown"] = 40
    detail = {code: {"visits": max(1, n // 9), "downloads": n} for code, n in countries.items()}
    states = ("NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT")
    doc = {"schema": 2, "timer_period_min": 1440, "generated_at": "2026-11-01T03:39:00Z",
           "since": "2026-09-10", "last_folded_date": _D.isoformat(), "labels_since": "2026-10-01",
           "archive_through": "2026-11-12", "detail_since": "2025-12-01",
           "select_since": "2025-12-01",
           "totals": {"downloads": 9000, "visits": 900,
                      "downloads_by_select": {"single": 4000, "bulk": 5000}},
           "downloads": {"by_survey": surveys}, "countries": countries,
           "by_country_detail": detail,
           "by_state": {code: 10 + i for i, code in enumerate(states)},
           "by_state_detail": {code: {"visits": 5 + i} for i, code in enumerate(states)},
           "monthly": months, "daily": daily}
    doc.update(over)
    return doc


def _fresh(doc: dict) -> dict:
    return dict(doc, generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                archive_through=doc["last_folded_date"])


def _get(tmp_path, doc) -> str:
    return run(fetch(tmp_path, doc))


def _states(tmp_path) -> dict[str, str]:
    """The page in every state the simplicity rules are held in."""
    full = _full_stats()
    before = _fresh(_full_stats(labels_since=None, labels_configured_from="2026-12-01"))
    for row in before["monthly"]:
        for key in ("labels", "operator", "crawler_excluded", "label_days"):
            row.pop(key, None)
    first = _fresh(_full_stats(labels_since="2026-11-03"))
    for key in ("labels", "operator", "crawler_excluded", "label_days"):
        first["monthly"][-2].pop(key, None)
    early = _fresh(_full_stats(monthly=[_month("2026-11", 18, 1)]))
    docs = {"full": full, "empty": None, "stale": _full_stats(archive_through=None),
            "before-labels": before, "first-labelled-month": first, "no-full-month": early,
            "fresh": _fresh(full)}
    return {name: _get(tmp_path / name, doc) for name, doc in docs.items()}


# ---- The simplicity measure.

_SKIP_TAGS = {"script", "style", "svg", "table", "title", "head"}
_BLOCKS = {"p", "li", "h1", "h2", "h3", "summary"}


class _Words(HTMLParser):
    """Text of the page body by element, skipping the rail, the context bar, scripts, styles, charts,
    tables, data-derived names and the collapsed notes. Each recorded run knows whether it sits in
    the notes card and in which leaf block."""

    def __init__(self, page: str):
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, set[str], int]] = []
        self.blocks: list[dict] = []
        self.runs: list[tuple[str, bool, bool]] = []
        self.paras: list[dict] = []
        self.feed(page)

    def _skipped(self) -> bool:
        for i, (tag, classes, _b) in enumerate(self.stack):
            if tag in _SKIP_TAGS or "u-dl" in classes or "rail" in classes or "ctxbar" in classes:
                return True
            if tag == "details" and any("u-notes" in c for _t, c, _x in self.stack[:i]):
                return True
        return False

    def _in(self, cls: str) -> bool:
        return any(cls in classes for _t, classes, _b in self.stack)

    def handle_starttag(self, tag, attrs):
        if tag in ("meta", "input", "link", "br", "img"):
            return
        classes = set((dict(attrs).get("class") or "").split())
        block = -1
        if tag in _BLOCKS or tag in ("div", "span"):
            self.blocks.append({"tag": tag, "text": "", "leaf": True, "notes": self._in("u-notes"),
                                "classes": classes})
            block = len(self.blocks) - 1
            for _t, _c, b in self.stack:
                if b >= 0 and tag in _BLOCKS | {"div"}:
                    self.blocks[b]["leaf"] = False
        self.stack.append((tag, classes, block))

    def handle_startendtag(self, tag, attrs):
        if tag in ("meta", "input", "link", "br", "img"):
            return
        self.handle_starttag(tag, attrs)
        self.stack.pop()

    def handle_endtag(self, tag):
        while self.stack:
            if self.stack.pop()[0] == tag:
                break

    def handle_data(self, data):
        if not self.stack or self._skipped():
            return
        health = self._in("u-health") or (self._in("u-notes") and self.stack[-1][0] == "p"
                                           and "u-warn" in self.stack[-1][1])
        self.runs.append((data, self._in("u-notes"), health))
        for _t, _c, b in self.stack:
            if b >= 0:
                self.blocks[b]["text"] += data


def _letter_words(page: str) -> int:
    words = _Words(page)
    counted = " ".join(data for data, notes, health in words.runs if not notes or health)
    return len([tok for tok in html.unescape(counted).split() if re.search(r"[A-Za-z]", tok)])


def _measured_blocks(page: str) -> list[dict]:
    """Text blocks above the notes card: every p, li, heading and summary, and every div or span
    with no block child."""
    return [b for b in _Words(page).blocks if not b["notes"]
            and (b["tag"] in _BLOCKS or b["leaf"]) and b["text"].strip()]


def _sentences(value: str) -> int:
    """Sentence ends: a full stop, question or exclamation mark followed by white space or the end.
    A dot inside a word or a number, as in IPLocate.io or 1.5, is followed by neither."""
    return len(re.findall(r"[.!?](?=\s|$)", value.strip()))


def test_usage_page_word_ceiling(tmp_path):
    """At most 300 letter-bearing words above the notes card plus the health line and its
    warning, on the fullest fixture and in the empty, stale, before-labels, first-labelled-month and
    no-full-month states. The mockup measured 157 words of page copy by the same method;
    the itemised budget for what the build adds comes to about 262. FAILS IF any state goes over."""
    counts = {name: _letter_words(page) for name, page in _states(tmp_path).items()}
    assert all(n <= 300 for n in counts.values()), counts
    assert counts["full"] > 150, counts


def test_usage_page_no_long_text_block(tmp_path):
    """No text block above the notes card exceeds 25 tokens. The mockup's longest block was 17
    tokens and the warnings are capped at 25. FAILS IF any block in any state is longer."""
    for name, page in _states(tmp_path).items():
        for block in _measured_blocks(page):
            tokens = html.unescape(block["text"]).split()
            assert len(tokens) <= 25, (name, " ".join(tokens))


_P_CLASSES = {"u-sofar", "u-sub", "u-foot", "u-warn", "u-empty", "u-who-note", "u-left"}


def test_usage_page_no_prose_above_notes(tmp_path):
    """Every paragraph above the notes card carries exactly one class from the closed list and
    holds one sentence; the downloads split is a list, not prose. FAILS IF a paragraph is
    unclassed, carries two classes from the list, or holds more than one sentence."""
    for name, page in _states(tmp_path).items():
        paras = [b for b in _Words(page).blocks if b["tag"] == "p" and not b["notes"]]
        assert paras, name
        for p in paras:
            assert len(p["classes"] & _P_CLASSES) == 1 and p["classes"] <= _P_CLASSES, (name, p)
            assert _sentences(html.unescape(p["text"])) == 1, (name, p["text"])
    assert '<ul class="u-split">' in _states(tmp_path / "again")["full"]


def test_usage_notes_at_most_eight_short_lines(tmp_path):
    """The notes hold at most eight items, each at most 25 tokens and at most 200 in all, and the
    card carries exactly one link, to the documentation. The mockup's longest note was 22 tokens.
    FAILS IF a note is added past eight, grows past 25 tokens, or a second link appears."""
    for name, page in _states(tmp_path).items():
        notes = sections(page)["notes"]
        items = [text(li) for li in re.findall(r"<li>(.*?)</li>", notes, re.S)]
        assert 1 <= len(items) <= 8, name
        assert all(len(item.split()) <= 25 for item in items), items
        assert sum(len(item.split()) for item in items) <= 200
        assert re.findall(r'<a href="([^"]+)"', notes) == [usagepage._DOCS_URL], name


_DASHES = ("\u2014", "\u2013", "&mdash;", "&ndash;", "&#8212;", "&#8211;")


def test_usage_page_has_no_dash_characters(tmp_path):
    """No em dash or en dash, as a character or an entity, in the text or any attribute of the
    page body in any state, nor anywhere in the page's own sources. The shared head's style comments
    are not page text and are skipped. FAILS IF a dash appears."""
    for name, page in _states(tmp_path).items():
        body = page.split("</head>", 1)[1]
        body = re.sub(r"<(script|style)\b.*?</\1>", "", body, flags=re.S)
        for dash in _DASHES:
            assert dash not in body, (name, dash)
            assert dash not in html.unescape(body), (name, dash)
    for source in ("usagepage.py", "countrynames.py", "static/usage.js"):
        raw = (Path(curatorpage.__file__).parent / source).read_text(encoding="utf-8")
        assert not [d for d in _DASHES if d in raw], source


# ---- Shell, title and theme.

def test_light_tokens_and_no_dark_variant(tmp_path):
    """The page carries the light tokens of the mockup once, in its own style block, with no dark
    variant, no colour-scheme query and no theme switch. FAILS IF a token changes or a dark path
    appears."""
    css = usagepage.USAGE_CSS
    for token in ("--page:#F1F2F1", "--surface:#FFFFFF", "--ink:#231F20", "--ink2:#4d4b47",
                  "--muted:#6f6d67", "--grid:#E7E7E4", "--axis:#C6C6C1", "--line:#DCDDDA",
                  "--brand:#282572", "--rail:#282572", "--rail-ink:#FFFFFF", "--rail-on:#59C2AA",
                  "--link:#206B82", "--s-visits:#3F88C8", "--s-down:#2FA58B", "--track:#EEF0EF",
                  "--up:#006300", "--down:#B3261E", "--note:#F7F4EC", "--tip:#231F20",
                  "--tip-ink:#FFFFFF", "--who-auto:#EF7256", "--who-unc:#8E8C86"):
        assert css.count(token) == 1, token
    for dark in ("prefers-color-scheme", "data-theme", "#13202B", "Show dark"):
        assert dark not in css, dark
    page = _get(tmp_path, _full_stats())
    assert page.count("<style>" + css + "</style>") == 1
    assert '<div class="shell usage">' in page and "data-theme" not in page


def test_usage_theme_rules_present():
    """The light page overrides the shared dark element and shell rules under its own scope, and
    borrows no value from the shared palette or head. FAILS IF a scoped rule is missing, or a dark
    value from the shared head appears in the page's style block."""
    css = usagepage.USAGE_CSS
    for selector in (".shell.usage .rail{", ".shell.usage .rail .grp{", ".shell.usage .rail a{",
                     ".shell.usage .rail a:hover{", ".shell.usage .rail a.on{",
                     ".shell.usage .ctxbar{", ".shell.usage .crumb{", ".shell.usage .crumb b{",
                     ".shell.usage .chip{", ".shell.usage .chip code{", ".shell.usage a{",
                     ".shell.usage :focus-visible{", ".shell.usage h1{", ".shell.usage h2{",
                     ".shell.usage h2 small{", ".shell.usage h3{", ".shell.usage table{",
                     ".shell.usage th,.shell.usage td{",
                     ".shell.usage th[scope=row],.shell.usage th:first-child{",
                     ".shell.usage thead th{", ".shell.usage details{", ".shell.usage summary{",
                     ".shell.usage .k{", ".shell.usage code{", ".u-inner{max-width:1040px",
                     "body{background:var(--page)"):
        assert selector in css, selector
    for value in list(curatorpage._PALETTE.values()) + ["#152430", "#1B2C3A", "#2E4254"]:
        assert value.lower() not in css.lower(), value
    assert "Inter" not in css and "system-ui" in css


def test_small_screen_and_focus_rules():
    """Below 900px the rail stacks above the page instead of hiding, tiles fall to two columns and
    the grid to one; focus is always visible; only the scroll wrappers scroll sideways. FAILS IF the
    rail is hidden or a rule is missing."""
    css = usagepage.USAGE_CSS
    small = css.split("@media (max-width:900px){", 1)[1]
    for rule in (".shell.usage{display:block}", ".shell.usage .rail{flex-basis:auto",
                 ".u-tiles{grid-template-columns:repeat(2,minmax(0,1fr))}",
                 ".u-tile.wide{grid-column:span 2}", ".u-grid2{grid-template-columns:1fr}"):
        assert rule in small, rule
    assert "display:none" not in small
    assert ".shell.usage :focus-visible{outline:2px solid var(--link);outline-offset:2px}" in css
    assert [m for m in re.findall(r"\.([\w-]+)\{[^}]*overflow-x:auto", css)] == ["u-scroll"]


def _token(css: str, name: str) -> tuple[int, int, int]:
    value = re.search(rf"{re.escape(name)}:#([0-9A-Fa-f]{{6}})", css).group(1)
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _contrast(a, b) -> float:
    lum = [0.2126 * _channel(c[0]) + 0.7152 * _channel(c[1]) + 0.0722 * _channel(c[2]) for c in (a, b)]
    hi, lo = max(lum), min(lum)
    return (hi + 0.05) / (lo + 0.05)


def test_focus_ring_is_visible_on_the_rail_and_the_page():
    """The focus ring on the navy rail uses the rail's own highlight, and every ring colour clears
    3:1 against what it sits on. FAILS IF a rail link's ring keeps the page link colour, which is
    about 2.2:1 on the rail."""
    css = usagepage.USAGE_CSS
    assert ".shell.usage .rail a:focus-visible{outline-color:var(--rail-on)}" in css
    assert _contrast(_token(css, "--rail-on"), _token(css, "--rail")) >= 3
    for ground in ("--surface", "--page"):
        assert _contrast(_token(css, "--link"), _token(css, ground)) >= 3, ground


def test_day_twin_scrolls_inside_a_short_box():
    """The day twin opens into a box about 280 px tall that scrolls, so six months of rows do not
    push the rest of the page down. FAILS IF the twin opens to its full length."""
    assert ".u-twin .u-scroll{max-height:280px;overflow-y:auto}" in usagepage.USAGE_CSS


# ---- Sections.

def test_usage_sections_render_in_order(tmp_path):
    """Header, last full month tiles, month in progress, who card, day by day, month by month, what
    and where, then the notes. FAILS IF a section is missing or out of order."""
    page = _get(tmp_path, _full_stats())
    assert list(sections(page)) == ["header", "tiles", "sofar", "who", "days", "months", "where",
                                    "notes"]
    assert "<h2>October 2026 <small>last full month</small></h2>" in page


def test_header_carries_the_three_csv_links(tmp_path):
    """The header offers the three exports in every state, the empty one included. FAILS IF a link
    is missing or moves off the header."""
    for name, doc in (("full", _full_stats()), ("empty", None)):
        header = sections(_get(tmp_path / name, doc))["header"]
        assert text(header).endswith("Download CSV: by month · by survey · by country"), name
        for href in ("analytics.csv", "analytics-surveys.csv", "analytics-countries.csv"):
            assert f'href="/gateway/curator/{href}"' in header, (name, href)


def test_tiles_use_the_last_full_month(tmp_path):
    """The tiles describe the last full month: the month before the data date's month, or the data
    date's month when it is a month end. FAILS IF a tile reads the month in progress."""
    page = _get(tmp_path, _full_stats())
    assert text(tile(page, "Portal visits")).startswith("Portal visits 110")
    assert text(tile(page, "Downloads")).startswith("Downloads 440")
    end = _get(tmp_path / "end", _full_stats(last_folded_date="2026-10-31"))
    assert "<h2>October 2026 <small>last full month</small></h2>" in end
    assert "u-sofar" not in end.split("</style>")[-1]


def test_tile_change_states(tmp_path):
    """The change line compares with the month before in every state: up and down in whole percent
    with a hidden word for the arrow, no change, up from 0, not measured, no row, nothing when the
    tile itself is not measured, and the partly counted note. FAILS IF a state reads wrongly."""
    doc = _full_stats()
    page = _get(tmp_path / "a", doc)
    visits = tile(page, "Portal visits")
    assert '<span aria-hidden="true">&#9650;</span><span class="u-vh">up</span> 10% on September' in visits
    assert "(from 10 Sep)" in text(visits)
    doc["monthly"][-2]["visits"] = 50
    assert "down 50% on September" in text(tile(_get(tmp_path / "b", doc), "Portal visits"))
    doc["monthly"][-2]["visits"] = doc["monthly"][-3]["visits"]
    assert "no change on September" in text(tile(_get(tmp_path / "c", doc), "Portal visits"))
    doc["monthly"][-3]["visits"] = 0
    assert "up from 0 in September" in text(tile(_get(tmp_path / "d", doc), "Portal visits"))
    doc["monthly"][-3].pop("handoffs")
    assert "September not measured" in text(tile(_get(tmp_path / "e", doc), "Time-series hand-offs"))
    doc["monthly"][-2].pop("handoffs")
    assert 'class="u-t-d' not in tile(_get(tmp_path / "f", doc), "Time-series hand-offs")
    gap = _full_stats()
    del gap["monthly"][-3]
    assert "no row for September" in text(tile(_get(tmp_path / "g", gap), "Portal visits"))


def test_downloads_tile_split_wording(tmp_path):
    """The downloads tile lists selection-export files with the floor wording, whole-survey bundles
    and single files, as three list items. FAILS IF the wording or a figure is wrong."""
    split = tile(_get(tmp_path, _full_stats()), "Downloads").split('<ul class="u-split">', 1)[1]
    items = [text(li) for li in re.findall(r"<li>(.*?)</li>", split)]
    assert items == ["220 files in at least 11 selection exports", "110 whole-survey bundles",
                     "110 single files"]


def test_split_not_measured_before_select_since(tmp_path):
    """A last full month wholly before the selection split began reads not measured for the export
    files and for single files, which derive from them; bundles stay measured. FAILS IF a zero is
    shown or bundles are swallowed."""
    split = text(tile(_get(tmp_path, _full_stats(select_since="2026-11-01")), "Downloads"))
    assert "Selection exports: not measured" in split and "Single files: not measured" in split
    assert "110 whole-survey bundles" in split


def test_single_files_not_measured_when_negative_or_missing(tmp_path):
    """Single files are station files less export files and read not measured when the difference is
    negative or the station file count is missing. FAILS IF a negative or invented figure shows."""
    doc = _full_stats()
    doc["monthly"][-2]["downloads_by_select"]["bulk"] = 9999
    assert "Single files: not measured" in text(tile(_get(tmp_path / "a", doc), "Downloads"))
    doc = _full_stats()
    doc["monthly"][-2]["kinds"] = {"bundle": 4}
    assert "Single files: not measured" in text(tile(_get(tmp_path / "b", doc), "Downloads"))
    doc["monthly"][-2].pop("kinds")
    page = text(tile(_get(tmp_path / "c", doc), "Downloads"))
    assert "Single files: not measured" in page and "Whole-survey bundles: not measured" in page


def test_month_in_progress_line(tmp_path):
    """The month in progress reads its visits, downloads and export files to the data date's day;
    a measured zero reads no selection exports; no row reads no counted requests yet. FAILS IF the
    line is wrong."""
    page = _get(tmp_path / "a", _full_stats())
    assert text(sections(page)["sofar"]) == ("November so far, to the 18th: 120 visits, 480 "
                                             "downloads, 240 selection-export files.")
    doc = _full_stats()
    doc["monthly"][-1]["downloads_by_select"]["bulk"] = 0
    assert "480 downloads, no selection exports." in text(_get(tmp_path / "b", doc))
    doc["monthly"].pop()
    assert "November so far: no counted requests yet." in text(_get(tmp_path / "c", doc))


def test_no_month_in_progress_on_a_month_end(tmp_path):
    """On a month end the data date's month is the last full month and nothing is in progress.
    FAILS IF a month in progress line or row suffix appears."""
    page = _get(tmp_path, _full_stats(last_folded_date="2026-10-31"))
    assert "so far" not in text(page.split('<div class="u-inner">', 1)[1]) and "(to " not in page


def test_no_full_month_yet_state(tmp_path):
    """With only the month in progress held, its heading says so, a short line says there is no
    full month yet, and the month in progress line follows. FAILS IF a tile is drawn."""
    page = _get(tmp_path, _fresh(_full_stats(monthly=[_month("2026-11", 18, 1)])))
    assert "<h2>November 2026 <small>month in progress</small></h2>" in page
    assert "No full month yet." in text(page) and 'class="u-tiles"' not in page
    assert "November so far, to the 18th" in text(page)


def test_a_finished_month_without_a_row_is_not_called_in_progress(tmp_path):
    """When the data date is a month end and that month has no row, nothing is in progress, so no
    heading may call that finished month in progress; the short no-full-month line still shows.
    FAILS IF the page labels a finished month as in progress or draws a tile."""
    doc = _fresh(_full_stats(last_folded_date="2026-10-31"))
    doc["monthly"] = [row for row in doc["monthly"] if row["month"] < "2026-10"]
    page = _get(tmp_path, doc)
    assert "month in progress" not in page and "so far" not in text(page)
    assert "No full month yet." in text(page) and 'class="u-tiles"' not in page


def test_month_with_no_downloads_state(tmp_path):
    """A last full month with no downloads shows a measured 0 and no split. FAILS IF a split or a
    not measured appears for a measured zero."""
    doc = _full_stats()
    doc["monthly"][-2]["downloads"] = 0
    downloads = tile(_get(tmp_path, doc), "Downloads")
    assert text(downloads).startswith("Downloads 0") and "u-split" not in downloads


# ---- Who made the requests.

def _unlabelled(doc: dict) -> dict:
    for row in doc["monthly"]:
        for key in ("labels", "operator", "crawler_excluded", "label_days"):
            row.pop(key, None)
    doc.pop("labels_since", None)
    return doc


def test_who_card_placeholder_with_and_without_configured_date(tmp_path):
    """Before any labelled month the who card shows the three audiences as pills and one note: the
    configured start date when the fold recorded one, otherwise not measured yet. FAILS IF a figure
    is shown or the note is wrong."""
    who = sections(_get(tmp_path / "a", _unlabelled(_full_stats(
        labels_configured_from="2026-12-01"))))["who"]
    assert text(who) == ("Who made the requests People Automated Unclassified Measured from 1 "
                         "December, when each figure above splits three ways with your own "
                         "requests left out.")
    who = sections(_get(tmp_path / "b", _unlabelled(_full_stats())))["who"]
    assert text(who).endswith("Not measured yet; each figure above splits three ways once labels "
                              "start.")


def test_who_card_after_labels_start_before_a_full_month(tmp_path):
    """When the last full month is not labelled but the month in progress carries labelled days, the
    card describes the month in progress under its own heading, with the same rows; the tiles stay
    on the last full month. FAILS IF the card stays a placeholder or reads the wrong month."""
    doc = _full_stats(labels_since="2026-11-03")
    for key in ("labels", "operator", "crawler_excluded", "label_days"):
        doc["monthly"][-2].pop(key)
    page = _get(tmp_path, doc)
    who = sections(page)["who"]
    assert "<h3>Who made the requests, November so far</h3>" in who
    assert "Downloads People 240 · Automated 180 · Unclassified 60" in text(who)
    assert "November 2026, requests by label" in text(who)
    assert "<h2>October 2026 <small>last full month</small></h2>" in page


def test_who_card_rows_print_numbers_beside_bars(tmp_path):
    """Each of the four rows prints People, Automated and Unclassified beside its bar, the bar is an
    image with the same figures in its label, and a hand-off row without the class reads not
    measured with an empty track. FAILS IF a figure is only in colour."""
    who = sections(_get(tmp_path / "a", _full_stats()))["who"]
    rows = re.findall(r'<div class="u-who-row">(.*?)</div>', who)
    assert [text(r).split(" People")[0] for r in rows] == [
        "Downloads", "Portal visits", "API requests", "Time-series hand-offs"]
    assert 'role="img" aria-label="People 220, automated 165, unclassified 55"' in rows[0]
    assert text(rows[3]) == "Time-series hand-offs People 11 · Automated 11 · Unclassified 0"
    doc = _full_stats()
    doc["monthly"][-2].pop("handoffs")
    who = sections(_get(tmp_path / "b", doc))["who"]
    last = re.findall(r'<div class="u-who-row">(.*?)</div>', who)[3]
    assert text(last) == "Time-series hand-offs not measured" and "u-seg" not in last


def test_who_bar_totals_equal_label_counts(tmp_path):
    """The segments of every bar sum to the month's label counts for that measure, and each segment's
    width is its share. FAILS IF a bar drops or invents requests."""
    doc = _full_stats()
    who = sections(_get(tmp_path, doc))["who"]
    month = doc["monthly"][-2]
    for row, metric in zip(re.findall(r'<div class="u-who-row">(.*?)</div>', who),
                           ("downloads", "visits", "api", "handoffs")):
        segs = [(float(w), int(n)) for w, n in
                re.findall(r'style="width:([\d.]+)%;min-width:2px" data-n="(\d+)"', row)]
        total = sum(month["labels"][metric].values())
        assert sum(n for _w, n in segs) == total, metric
        assert all(abs(w - n * 100 / total) < 0.06 for w, n in segs), metric


def test_who_warning_clauses(tmp_path):
    """One warning line holds the clauses in order, labelled days, network type, operator list,
    hosting only; the four-clause worst case is at most 25 words and never truncated. FAILS IF a
    clause is missing, out of order, or the line is too long."""
    who = sections(_get(tmp_path, _full_stats()))["who"]
    warning = text(who.split('<p class="u-warn">', 1)[1].split("</p>", 1)[0])
    assert warning == ("Warning: labels on 20 of 31 days, rest include your requests; no network "
                       "type 5 days; no operator list 8 days; hosting-only 5 days.")
    assert len(warning.split()) <= 25


def test_who_card_without_network_table(tmp_path):
    """With no month that used the network table the detail lists client classes only under 'By
    client', the warning names no network clause, no credit line appears, and the words network type
    appear nowhere above the notes. FAILS IF a network figure or wording leaks onto such a page."""
    doc = _full_stats()
    for row in doc["monthly"]:
        row.update(nettype_days=0, nettype_full_days=0)
    page = _get(tmp_path, doc)
    above = text(page.split('<div class="u-card u-notes">', 1)[0].split("</style>")[-1])
    assert "network type" not in above.lower() and "X4BNet" not in above
    who = sections(page)["who"]
    assert "<summary>By client</summary>" in who
    assert [r[0] for r in table_rows(who)] == ["Portal session", "Landing page", "Tool",
                                               "Unknown client"]
    assert "hosting-only" not in who and "Warning: labels on 20 of 31 days" in text(who)


def _network_only_in(months: tuple[str, ...]) -> dict:
    doc = _full_stats()
    for row in doc["monthly"]:
        if row["month"] in months:
            row.update(nettype_days=4, nettype_full_days=0)
        else:
            row.update(nettype_days=0, nettype_full_days=0)
    return doc


def test_network_rows_follow_any_held_month_not_only_the_shown_ones(tmp_path):
    """The network rows, the network clauses and the hosting range credit appear when any month held
    in the stats file used the network table, whether that is an older month or the newest. FAILS IF
    the gate looks only at the months the card or tiles show."""
    for name, months in (("older", ("2026-03",)), ("newest", ("2026-11",))):
        who = sections(_get(tmp_path / name, _network_only_in(months)))["who"]
        assert "<summary>By client and network</summary>" in who, name
        assert [r[0] for r in table_rows(who)][4:] == ["Hosting", "Education or research",
                                                       "Access provider", "Other",
                                                       "Unknown network"], name
        assert "Hosting ranges: X4BNet lists_vpn" in text(who), name
        assert "no network type" in text(who), name


def _channel(c: float) -> float:
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lab(rgb) -> tuple[float, float, float]:
    x = 0.4124 * rgb[0] + 0.3576 * rgb[1] + 0.1805 * rgb[2]
    y = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    z = 0.0193 * rgb[0] + 0.1192 * rgb[1] + 0.9505 * rgb[2]

    def f(t):
        return t ** (1 / 3) if t > (6 / 29) ** 3 else t / (3 * (6 / 29) ** 2) + 4 / 29
    fx, fy, fz = f(x / 0.95047), f(y), f(z / 1.08883)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


# Machado, Oliveira and Fernandes (2009) simulation matrices at full severity, in linear RGB.
_CVD = {"normal": ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
        "protanopia": ((0.152286, 1.052583, -0.204868), (0.114503, 0.786281, 0.099216),
                       (-0.003882, -0.048116, 1.051998)),
        "deuteranopia": ((0.367322, 0.860646, -0.227968), (0.280085, 0.672501, 0.047413),
                         (-0.011820, 0.042940, 0.968881)),
        "tritanopia": ((1.255528, -0.076749, -0.178779), (-0.078411, 0.930809, 0.147602),
                       (0.004733, 0.691367, 0.303900))}


def test_who_colours_are_distinct_under_colour_vision_deficiency():
    """People, automated and unclassified stay at least 20 apart in CIE Lab under normal vision and
    each simulated dichromacy, and the page uses exactly those three colours. FAILS IF a colour
    changes to one that two audiences would share."""
    css = usagepage.USAGE_CSS
    colours = {"people": "#3F88C8", "automated": "#EF7256", "unclassified": "#8E8C86"}
    assert "--s-visits:#3F88C8" in css and "--who-auto:#EF7256" in css and "--who-unc:#8E8C86" in css
    for name, matrix in _CVD.items():
        labs = []
        for value in colours.values():
            lin = [_channel(int(value[i:i + 2], 16)) for i in (1, 3, 5)]
            sim = [min(1.0, max(0.0, sum(matrix[r][c] * lin[c] for c in range(3)))) for r in range(3)]
            labs.append(_lab(sim))
        for i in range(3):
            for j in range(i + 1, 3):
                assert math.dist(labs[i], labs[j]) >= 20, (name, i, j)


def test_no_label_beside_place_survey_dataset_or_day(tmp_path):
    """Label figures appear only in the who card: the tiles, charts, table twin, month table and what
    and where carry no audience, client class or network type figure. FAILS IF a label figure sits
    beside a place, a survey, a dataset or a day."""
    page = _get(tmp_path, _full_stats())
    for name, part in sections(page).items():
        if name in ("who", "notes"):
            continue
        for word in ("People", "Automated", "Unclassified", "Portal session", "Landing page",
                     "Hosting", "Access provider", "u-who", "u-seg"):
            assert word not in text(part) and word not in part.replace("u-who-", ""), (name, word)


# ---- Day by day and month by month.

def test_day_chart_small_names_the_labels_seam(tmp_path):
    """The day by day heading names the drawn span and, when labels began inside it, the day your own
    requests were left out from; otherwise it adds nothing. FAILS IF the seam is hidden or invented."""
    page = _get(tmp_path / "a", _full_stats())
    assert ("<h2>Day by day <small>19 May 2026 to 18 Nov 2026; your own requests left out from 1 "
            "Oct</small></h2>") in page
    plain = _get(tmp_path / "b", _full_stats(labels_since=None))
    assert "<h2>Day by day <small>19 May 2026 to 18 Nov 2026</small></h2>" in plain


def test_each_chart_has_a_collapsed_table_twin_with_every_value(tmp_path):
    """The three charts sit in one card with one collapsed table twin that lists every daily row,
    newest first, with each chart's value for that day. FAILS IF the twin is open, missing a row, or
    disagrees with a chart's titles."""
    doc = _full_stats()
    days = sections(_get(tmp_path, doc))["days"]
    assert days.count("<svg") == 3 and days.count('<details class="u-twin">') == 1
    assert "<details open" not in days
    rows = table_rows(days)
    assert len(rows) == 184 and rows[0][0] == "18 Nov 2026"
    titles = {}
    for chart, column in (("visits", 1), ("bundles", 2), ("files", 3)):
        svg = days.split(f'data-u-chart="{chart}"', 1)[1].split("</svg>", 1)[0]
        titles = dict(re.findall(r'data-label="([^"]+)" data-v="([^"]+)"', svg))
        for row in rows:
            day = row[0].rsplit(" ", 1)[0]
            assert titles[day] == row[column], (chart, row)


def test_month_table_columns_and_order(tmp_path):
    """The month table has the eleven columns in order and every held month, newest first, with the
    month in progress and a partly counted month marked by their day. FAILS IF a column or month is
    missing or out of order."""
    months = sections(_get(tmp_path, _full_stats()))["months"]
    assert table_head(months) == ["Month", "Visits", "Downloads", "Export files", "Exports at least",
                                  "Bundles", "Single files", "API", "Hand-offs", "Countries",
                                  "Volume"]
    labels = [r[0] for r in table_rows(months)]
    assert labels[:3] == ["November 2026 (to 18th)", "October 2026", "September 2026 (from 10th)"]
    assert len(labels) == 12 and labels[-1] == "December 2025"
    assert table_rows(months)[1][1:] == ["110", "440", "220", "11", "110", "110", "33", "22", "2",
                                         "11.0 MB"]


def _month_caption(page: str) -> str:
    months = sections(page)["months"]
    return text(months.split('<p class="u-sub">', 1)[1]) if '<p class="u-sub">' in months else ""


def test_month_caption_names_only_the_seams_that_apply(tmp_path):
    """The caption under the month table names the detail seam only when a shown month was folded
    wholly before detail existed, and the selection split seam only when a shown month predates the
    split. FAILS IF the caption blames a seam for a month it does not touch."""
    doc = _fresh(_full_stats())
    doc["monthly"][-3].pop("handoffs")
    caption = _month_caption(_get(tmp_path / "a", doc))
    assert caption == "Not measured means counted before that figure existed.", caption

    seeded = _fresh(_full_stats())
    seeded["monthly"][0]["seeded_days"] = seeded["monthly"][0]["days"]
    caption = _month_caption(_get(tmp_path / "b", seeded))
    assert "detail from 1 Dec 2025" in caption and "selection split" not in caption, caption

    late = _fresh(_full_stats(select_since="2026-03-01"))
    caption = _month_caption(_get(tmp_path / "c", late))
    assert "selection split from 1 Mar 2026" in caption and "detail from" not in caption, caption


def test_month_table_has_an_accessible_name(tmp_path):
    """The month table, like the day twin and the who detail, carries a caption, kept visually
    hidden because the heading above it already says what it is. FAILS IF a table on the page has
    no caption."""
    page = _get(tmp_path, _full_stats())
    months = sections(page)["months"]
    assert '<table><caption class="u-vh">Every retained month, newest first</caption>' in months
    assert page.count("<table>") == page.count("<table><caption")


def test_tables_have_header_scope(tmp_path):
    """Every header cell on the page carries a scope. FAILS IF a th lacks one."""
    for name, page in _states(tmp_path).items():
        for th in re.findall(r"<th\b[^>]*>", page):
            assert re.search(r'scope="(col|row)"', th), (name, th)


# ---- What and where.

def test_what_and_where_cards(tmp_path):
    """Four cards: the ten most downloaded surveys of all attributed, the countries, the Australian
    states and the formats of the last full month, each a ranked list with the value printed beside
    every bar. FAILS IF a card is missing, a value is unprinted, or a survey is ranked wrongly."""
    page = _get(tmp_path, _full_stats())
    where = sections(page)["where"]
    assert re.findall(r"<h3>(.*?)</h3>", where) == ["Most downloaded surveys", "Countries",
                                                    "Australian visits by state", "Formats"]
    surveys = card(page, "Most downloaded surveys")
    assert "files and bundles, top 10 of 11" in text(surveys)
    rows = row_values(surveys)
    assert rows[0] == ("Survey A 2000", "500") and len(rows) == 10
    assert where.count('class="u-rk-b') == where.count("u-rk-b ")
    assert "downloads in October 2026" in text(card(page, "Formats"))


def test_what_and_where_scope_caption(tmp_path):
    """The what and where heading names when counting began and, once, whether your own requests are
    left out and from when. FAILS IF the scope line is missing, repeated, or wrong."""
    page = _get(tmp_path / "a", _full_stats())
    assert ("<h2>What and where <small>since counting began in September 2026; your own requests "
            "left out from 1 Oct 2026</small></h2>") in page
    assert text(page).count("your own requests left out from 1 Oct 2026") == 1
    plain = _get(tmp_path / "b", _full_stats(labels_since=None))
    assert "since counting began in September 2026; your own requests included" in plain


def test_countries_card_rows_and_rest_line(tmp_path):
    """The countries card ranks the top eight by name with visits and downloads, says how many there
    are and Australia's share of visits, and sums the rest, unknown included, in one line. FAILS IF
    a code shows instead of a name, unknown is ranked, or the rest line is wrong."""
    doc = _full_stats()
    countries = card(_get(tmp_path, doc), "Countries")
    names = re.findall(r'<span class="u-dl">(.*?)</span>', countries)
    assert names == ["Australia", "Japan", "United States", "New Zealand", "Germany",
                     "United Kingdom", "China", "Italy"]
    detail = doc["by_country_detail"]
    share = round(detail["AU"]["visits"] * 100 / sum(r["visits"] for r in detail.values()))
    assert f"top 8 of 10; Australia is {share}% of visits" in text(countries)
    rest = [code for code in detail if code not in ("AU", "JP", "US", "NZ", "DE", "GB", "CN", "IT")]
    v, d = (sum(detail[c][k] for c in rest) for k in ("visits", "downloads"))
    assert f"The other 2 countries and unplaced requests: {v:,} visits, {d:,} downloads." in text(
        countries)


def test_state_card_page_total_equals_the_countries_card(tmp_path):
    """On the page, the state card's named rows plus 'Not placed in a state' equal its Australia
    total, which is the Australian visits the countries card prints. FAILS IF the two cards
    disagree or the card does not add up."""
    page = _get(tmp_path / "a", _full_stats())
    rows = row_values(card(page, "Australian visits by state"))
    values = {name: int(v.replace(",", "")) for name, v in rows}
    total = values.pop("Australia")
    assert sum(values.values()) == total
    countries = card(page, "Countries")
    au = countries.split("Australia</span>", 1)[1].split('<div class="u-cr">', 1)[0]
    assert text(au).split()[0].replace(",", "") == str(total)
    doc = _full_stats()
    doc["by_country_detail"]["AU"]["visits"] = 1
    state = card(_get(tmp_path / "b", doc), "Australian visits by state")
    assert "Not reconciled with the Australian total; the CSV carries the state figures." in text(state)
    assert row_values(state) == []


def test_formats_card_display_names(tmp_path):
    """Format keys read as their display names, xml-zip and unattributed included, biggest first; an
    unknown key reads as stored. FAILS IF a key shows raw or a name is wrong."""
    doc = _full_stats()
    doc["monthly"][-2]["formats"]["newfmt"] = 1
    rows = row_values(card(_get(tmp_path, doc), "Formats"))
    assert [name for name, _v in rows] == ["MTH5", "EDI", "EMTF XML", "EDI zip", "XML zip",
                                           "Unattributed", "newfmt"]


# ---- Notes and health.

def test_usage_notes_text(tmp_path):
    """The notes are the eight agreed lines, collapsed by default, with the labels line following the
    label start. FAILS IF a note is reworded, dropped or open by default."""
    notes = sections(_get(tmp_path / "a", _full_stats()))["notes"]
    assert "<details><summary>How these numbers are counted</summary>" in notes
    items = [text(li) for li in re.findall(r"<li>(.*?)</li>", notes)]
    assert items == usagepage._notes(_full_stats())
    assert items[2] == ("A selection export fetches each station's file separately, so one export "
                        "can be thousands of files; the export count is a floor.")
    assert items[3] == ("Declared crawlers are left out, and your own requests are left out from 1 "
                        "Oct 2026.")
    before = sections(_get(tmp_path / "b", _full_stats(labels_since=None)))["notes"]
    assert ("Declared crawlers are left out; your own requests are counted until labels start."
            in text(before))


def test_notes_link_targets_the_docs_section(tmp_path):
    """The notes link to the documentation section that holds every counting rule, and that anchor
    exists in the documentation. FAILS IF the link or the heading moves."""
    notes = sections(_get(tmp_path, _full_stats()))["notes"]
    assert ('<a href="https://ausmt.readthedocs.io/en/latest/introduction/usage-analytics/'
            '#reading-the-curator-usage-page">Full method and every counting rule</a>') in notes
    docs = (_REPO / "docs" / "docs" / "introduction" / "usage-analytics.md").read_text("utf-8")
    assert "\n## Reading the curator Usage page\n" in docs


def _health(page: str) -> tuple[str, str]:
    notes = sections(page)["notes"]
    line = text(notes.split('<div class="u-health">', 1)[1].split("</div>", 1)[0])
    warn = notes.split('<p class="u-warn">', 1)
    return line, text(warn[1].split("</p>", 1)[0]) if len(warn) > 1 else ""


def test_health_line_fresh(tmp_path):
    """A fresh file whose archive reaches the data date reads the data date, the last count and the
    archive date, with a fresh dot and no warning. FAILS IF a warning shows or a date is wrong."""
    doc = _fresh(_full_stats())
    page = _get(tmp_path, doc)
    line, warning = _health(page)
    stamp = dt.datetime.strptime(doc["generated_at"], "%Y-%m-%dT%H:%M:%SZ")
    assert line == (f"Data to 18 Nov 2026 · last count {stamp.day} {stamp:%b %Y, %H:%M} UTC · "
                    "archive written to 18 Nov 2026")
    assert warning == "" and '<span class="u-dot"></span>' in page


def test_health_line_stale(tmp_path):
    """A stale file with its archive current warns that no count finished for over two timer periods
    and names the timer. FAILS IF the warning is missing or wrong."""
    doc = _full_stats(archive_through=_D.isoformat())
    line, warning = _health(_get(tmp_path, doc))
    assert line.startswith("Data to 18 Nov 2026 · last count 1 Nov 2026, 03:39 UTC")
    assert warning == "Warning: no count has finished for over 48 hours; check the ausmt-stats timer."


def test_health_line_stale_without_timer_period(tmp_path):
    """Without a recorded timer period the warning names no hours, so no default cadence is
    claimed; with no stats file it reads the same. FAILS IF a number of hours is guessed."""
    doc = _full_stats(archive_through=_D.isoformat())
    del doc["timer_period_min"]
    _line, warning = _health(_get(tmp_path / "a", doc))
    assert warning == "Warning: no count has finished yet; check the ausmt-stats timer."
    line, warning = _health(_get(tmp_path / "b", None))
    assert line == "Data to: none · last count: never"
    assert warning == "Warning: no count has finished yet; check the ausmt-stats timer."


def test_health_line_archive_behind(tmp_path):
    """An archive date before the data date warns that later days are not in the permanent record;
    with the file also stale both are said in one line. FAILS IF the warning is missing or doubled."""
    _line, warning = _health(_get(tmp_path / "a", _fresh(_full_stats()) | {
        "archive_through": "2026-11-12"}))
    assert warning == ("Warning: the archive stops at 12 Nov 2026; later days are not in the "
                       "permanent record, see the fold journal.")
    _line, warning = _health(_get(tmp_path / "b", _full_stats()))
    assert warning == "Warning: no count on time, and the archive stops at 12 Nov 2026."


def test_health_line_archive_not_recorded(tmp_path):
    """Without an archive date the line says not recorded and warns; with the file stale too the one
    warning says both. FAILS IF an absent date reads as current."""
    line, warning = _health(_get(tmp_path / "a", _fresh(_full_stats()) | {"archive_through": None}))
    assert line.endswith("archive written to: not recorded")
    assert warning == "Warning: the archive date is not recorded; see the fold journal."
    _line, warning = _health(_get(tmp_path / "b", _full_stats(archive_through=None)))
    assert warning == "Warning: no count on time, and the archive date is not recorded."


def test_the_gateway_reads_only_the_archive_date(tmp_path):
    """The gateway names archive_through only in the Usage page renderer, and renders it only when
    it is a real YYYY-MM-DD day; any other value reads not recorded. FAILS IF another gateway source
    names it, or a malformed value reaches the page."""
    gateway = Path(curatorpage.__file__).parent
    named = sorted(p.name for p in gateway.rglob("*.py")
                   if "archive_through" in p.read_text(encoding="utf-8") and "tests" not in p.parts)
    assert named == ["usagepage.py"], named
    for i, value in enumerate(("2026-11-31", "<b>x</b>", "2026-11-12T00:00:00Z", 20261112, "")):
        line, _w = _health(_get(tmp_path / str(i), _fresh(_full_stats()) | {"archive_through": value}))
        assert line.endswith("archive written to: not recorded"), value


def test_human_bytes_scales_without_a_dash():
    """Byte counts render in a sensible unit, and a value that is not a number reads not measured,
    never a dash. FAILS IF a dash or an invented size appears."""
    assert curatorpage._human_bytes(512) == "512 B"
    assert curatorpage._human_bytes(5_242_880) == "5.0 MB"
    assert curatorpage._human_bytes(None) == curatorpage._human_bytes("x") == "not measured"


# Header rows of the three exports for a labelled, selection-split fixture. They are a guard: the
# Usage page leaves the exports exactly as they were.
_MONTHLY_HEAD = (
    "month,downloads,download_bytes,visits,api_requests,unattributed,downloads_browser,"
    "downloads_scripted,networks_peak,countries,active_days,days_without_detail,geo_days,"
    "detail_days,label_days,nettype_days,nettype_full_days,operator_list_days,downloads_people,"
    "downloads_automated,downloads_unclassified,visits_people,visits_automated,visits_unclassified,"
    "api_people,api_automated,api_unclassified,handoffs_people,handoffs_automated,"
    "handoffs_unclassified,operator_downloads,operator_visits,operator_api,operator_handoffs,"
    "operator_download_bytes,crawler_excluded_downloads,crawler_excluded_visits,"
    "crawler_excluded_api,crawler_excluded_handoffs,downloads_client_portal_session,"
    "downloads_client_landing_page,downloads_client_tool,downloads_client_unknown,"
    "downloads_net_hosting,downloads_net_education_research,downloads_net_access_provider,"
    "downloads_net_other,downloads_net_unknown,downloads_select_bulk,downloads_select_single,"
    "bulk_export_events,format_edi,format_edi-zip,format_emtfxml,format_mth5,format_unattributed,"
    "format_xml-zip,kind_bundle,kind_file")


def test_csv_routes_and_headers_unchanged(tmp_path):
    """The three export routes still answer with the same header rows, session gated. FAILS IF a
    route moves or a header changes."""
    doc = _full_stats()

    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            r = await client.get("/gateway/curator/analytics.csv", follow_redirects=False)
            assert r.status_code != 200
            await curator_login(client)
            cfg.state_dir.mkdir(parents=True, exist_ok=True)
            (cfg.state_dir / serve_state.STATS_FILENAME).write_text(json.dumps(doc), "utf-8")
            heads = {}
            for path in ("analytics.csv", "analytics-surveys.csv", "analytics-countries.csv"):
                r = await client.get(f"/gateway/curator/{path}")
                assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
                heads[path] = r.text.splitlines()[0]
            return heads
    heads = run(_body())
    assert heads["analytics.csv"] == _MONTHLY_HEAD
    assert heads["analytics-surveys.csv"] == "month,survey,downloads,download_bytes,countries,files,bundles"
    assert heads["analytics-countries.csv"] == ("month,country,requests,downloads,visits,api,"
                                                "download_bytes,geo_days")


# ---- The hover read-out script.

_USAGE_JS = Path(curatorpage.__file__).parent / "static" / "usage.js"
_JS_ROUTE = "/gateway/curator/usage.js"
_JS_TAG = f'<script src="{_JS_ROUTE}" defer></script>'
_JS_READS = {"data-u-chart", "data-u-name", "data-i", "data-day", "data-label", "data-v", "data-cx"}
_JS_FORBIDDEN = ("fetch", "XMLHttpRequest", "WebSocket", "EventSource", "sendBeacon", "import(",
                 "Worker", "eval", "Function(", "setInterval", "innerHTML", "outerHTML",
                 "insertAdjacentHTML", "document.write", "localStorage", "sessionStorage",
                 "indexedDB", "document.cookie", "://", "http:", "https:")
_JS_GEOMETRY = ("getBBox", "getCTM", "getScreenCTM", "getBoundingClientRect", "getAttributeNS",
                ".attributes", "getComputedStyle")


def test_usage_js_route_session_gated_and_no_store(tmp_path):
    """The read-out script is served from its own same-origin route, only to a signed-in curator, as
    raw JavaScript that is never cached, byte for byte the bundled file. FAILS IF the route answers
    without a session, is cached, wraps the script, or serves other bytes."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, _cfg):
            anon = await client.get(_JS_ROUTE, follow_redirects=False)
            assert anon.status_code == 303
            await curator_login(client)
            r = await client.get(_JS_ROUTE)
            return r.status_code, dict(r.headers), r.text
    status, headers, body = run(_body())
    assert status == 200
    assert headers["content-type"] == "application/javascript; charset=utf-8"
    assert headers["cache-control"] == "no-store"
    assert "<script" not in body
    assert body == usagepage.USAGE_JS == _USAGE_JS.read_text(encoding="utf-8")


def test_usage_js_has_no_forbidden_token():
    """The script makes no request, stores nothing, writes no markup and names no other origin.
    FAILS IF any banned token or URL form appears in it, a string literal included."""
    js = _USAGE_JS.read_text(encoding="utf-8")
    assert js.strip()
    assert [t for t in _JS_FORBIDDEN if t in js] == []
    assert re.findall(r"""["'`]//""", js) == []
    assert not [d for d in _DASHES if d in js]


def test_usage_js_reads_only_data_attributes():
    """Every attribute the script reads is one of the data attributes the server wrote for it, named
    as a literal; it reads no geometry. FAILS IF it reads any other attribute, reads one through a
    computed name, or measures the chart."""
    js = _USAGE_JS.read_text(encoding="utf-8")
    calls = re.findall(r"getAttribute\s*\(([^)]*)\)", js)
    assert calls, "the script reads no attribute, so this would pass over nothing"
    names = []
    for arg in calls:
        m = re.fullmatch(r"""\s*["']([a-z-]+)["']\s*""", arg)
        assert m, f"attribute read through a computed name: {arg}"
        names.append(m.group(1))
    assert set(names) <= _JS_READS, set(names) - _JS_READS
    for key in re.findall(r"\.dataset\.(\w+)", js):
        kebab = "data-" + re.sub(r"[A-Z]", lambda c: "-" + c.group(0).lower(), key)
        assert kebab in _JS_READS, kebab
    assert "dataset[" not in js
    for selector in re.findall(r"\[(data-[a-z-]+)", js):
        assert selector in _JS_READS, selector
    assert [g for g in _JS_GEOMETRY if g in js] == []


# What the script may create, set and attach. Anything else could load a resource or touch a figure.
_JS_ELEMENTS = {"div", "b"}
_JS_SET_ATTRIBUTES = {"x1", "x2", "visibility"}
_JS_ASSIGNED = {"hidden", "textContent", "left", "top", "exports"}
_JS_PARENTS = {"div", "tip"}
_JS_NEVER = ("navigator", "location", "Image(", "open(", "document.head", "document.body",
             "createElementNS", "setAttributeNS", "insertBefore", "replaceChild", "replaceWith",
             ".append(", ".prepend(", ".before(", ".after(", "cloneNode", "importNode", "cssText",
             "Reflect", "defineProperty", "Object.assign", "srcset", "postMessage")


def test_usage_js_writes_only_its_own_elements():
    """The script may create only div and b elements, set only the crosshair attributes, assign only
    the tip's text, visibility and position, and attach only to the tip and its own lines; it names no
    resource-bearing property and no API that could reach the network. FAILS IF it creates any other
    element, sets any other attribute or property, or attaches anywhere else, such as an image whose
    source would make a request."""
    js = _USAGE_JS.read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", " ", js, flags=re.S)
    created = re.findall(r"createElement\s*\(([^)]*)\)", code)
    assert created, "the script creates no element, so this would pass over nothing"
    for arg in created:
        m = re.fullmatch(r"""\s*["']([a-z]+)["']\s*""", arg)
        assert m and m.group(1) in _JS_ELEMENTS, arg
    for arg in re.findall(r"setAttribute\s*\(([^,)]*)", code):
        m = re.fullmatch(r"""\s*["']([a-z0-9]+)["']\s*""", arg)
        assert m and m.group(1) in _JS_SET_ATTRIBUTES, arg
    assigned = re.findall(r"\.([A-Za-z_$][\w$]*)\s*=(?!=)", code)
    assert assigned, "the script assigns no property, so this would pass over nothing"
    assert set(assigned) <= _JS_ASSIGNED, set(assigned) - _JS_ASSIGNED
    for line in re.findall(r"^.*\]\s*=(?!=).*$", code, re.M):
        assert line.strip().startswith("byKey["), line
    assert set(re.findall(r"(\w+)\.appendChild\b", code)) <= _JS_PARENTS
    assert not re.findall(r"\.(src|href|action|data|rel|poster|style)\s*=(?!=)", code)
    assert [t for t in _JS_NEVER if t in code] == []
    assert not re.findall(r"\bnew\s+(?!Array\b)\w+", code)


_DOM_STUB = r"""
const fs = require("fs");
const vm = require("vm");
function el(tag, attrs) {
  const node = {tag, attrs: Object.assign({}, attrs || {}), children: [], hidden: false,
    style: {}, textContent: "", offsetWidth: 80, offsetHeight: 40, listeners: {},
    classes: new Set(String((attrs || {}).class || "").split(" ").filter(Boolean)),
    getAttribute(n) { return n in this.attrs ? String(this.attrs[n]) : null; },
    setAttribute(n, v) { this.attrs[n] = String(v); },
    addEventListener(n, f) { this.listeners[n] = f; },
    appendChild(c) { this.children.push(c); return c; },
    removeChild(c) { this.children.splice(this.children.indexOf(c), 1); return c; },
    get firstChild() { return this.children[0] || null; },
    querySelectorAll(sel) {
      const cls = sel.slice(1);
      const out = [];
      (function walk(n) { for (const c of n.children) { if (c.classes.has(cls)) out.push(c); walk(c); } })(this);
      return out;
    },
    querySelector(sel) { return this.querySelectorAll(sel)[0] || null; },
    closest(sel) { return this.classes.has(sel.slice(1)) ? this : null; }};
  node.classList = {add: (c) => node.classes.add(c), remove: (c) => node.classes.delete(c)};
  return node;
}
const spec = JSON.parse(process.argv[3]);
const svgs = spec.charts.map((c) => {
  const svg = el("svg", {"data-u-chart": c.key, "data-u-name": c.name});
  svg.children.push(el("line", {class: "u-cross", x1: "0", x2: "0", visibility: "hidden"}));
  for (const s of c.slots) {
    svg.children.push(el("path", {class: "u-bar", "data-i": s.i}));
    svg.children.push(el("rect", {class: "u-hit", "data-i": s.i, "data-day": s.day,
      "data-label": s.label, "data-v": s.v, "data-cx": s.cx}));
  }
  return svg;
});
const tip = el("div", {id: "u-tip"});
tip.hidden = true;
const document = {readyState: "complete",
  querySelectorAll: (sel) => (sel === "svg[data-u-chart]" ? svgs : []),
  getElementById: (id) => (id === "u-tip" ? tip : null),
  createElement: (tag) => el(tag), addEventListener() {}};
const window = {innerWidth: 1200, innerHeight: 800};
vm.runInNewContext(fs.readFileSync(process.argv[2], "utf8"), {document, window});
function snap() {
  return {hidden: tip.hidden,
    lines: tip.children.map((d) => (d.children.length ? d.children[0].textContent : d.textContent)),
    heads: tip.children.map((d) => (d.children.length ? d.children[0].tag : "")),
    cross: svgs.map((s) => { const c = s.querySelector(".u-cross");
      return [c.attrs.x1, c.attrs.x2, c.attrs.visibility]; }),
    dim: svgs.map((s) => s.querySelectorAll(".u-bar").filter((b) => b.classes.has("u-dim"))
      .map((b) => b.attrs["data-i"]))};
}
const target = svgs[0].querySelectorAll(".u-hit")[spec.hover];
svgs[0].listeners.pointermove({target, clientX: 100, clientY: 100});
const over = snap();
svgs[0].listeners.pointerleave({});
process.stdout.write(JSON.stringify({over, left: snap()}));
"""


def test_usage_js_hover_reads_the_day_label_and_moves_every_crosshair(tmp_path):
    """Driven over a stub of the chart markup, a pointer on one slot shows the tip with that slot's
    day label as its bold heading and one line per chart in order with the chart name and its own
    value, moves each chart's crosshair to that chart's own slot centre, dims every other column,
    and clears all of it when the pointer leaves. FAILS IF the heading comes from any attribute
    other than the day label, a value or position is taken from the wrong chart, or the leave does
    not clear the read-out. An absent Node fails, never skips."""
    import shutil
    import subprocess
    node = shutil.which("node")
    assert node, "node is required to run the read-out script's executable pin"
    slots = [{"i": "0", "day": "2026-06-27", "label": "27 Jun", "cx": "48.5"},
             {"i": "1", "day": "2026-06-28", "label": "28 Jun", "cx": "53.5"}]
    charts = [{"key": key, "name": name,
               "slots": [dict(s, v=f"{k}{s['i']}", cx=str(float(s["cx"]) + k)) for s in slots]}
              for k, (key, name) in enumerate((("files", "Station files downloaded"),
                                               ("visits", "Portal visits"),
                                               ("bundles", "Whole-survey bundles downloaded")))]
    driver = tmp_path / "dom_driver.js"
    driver.write_text(_DOM_STUB, encoding="utf-8")
    out = subprocess.run([node, str(driver), str(_USAGE_JS),
                          json.dumps({"charts": charts, "hover": 1})],
                         capture_output=True, text=True, timeout=30, check=False)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    over = got["over"]
    assert over["hidden"] is False
    assert over["lines"] == ["28 Jun", "Portal visits: 11", "Whole-survey bundles downloaded: 21",
                             "Station files downloaded: 01"]
    assert over["heads"] == ["b", "", "", ""]
    assert over["cross"] == [["53.5", "53.5", "visible"], ["54.5", "54.5", "visible"],
                             ["55.5", "55.5", "visible"]]
    assert over["dim"] == [["0"], ["0"], ["0"]]
    left = got["left"]
    assert left["hidden"] is True and left["dim"] == [[], [], []]
    assert [c[2] for c in left["cross"]] == ["hidden"] * 3


def test_usage_js_readout_copies_only_given_values(tmp_path):
    """formatReadout, run under Node, returns the day label then one line per chart holding the
    chart name and the value exactly as given, in the order given; it computes, rounds or invents
    nothing and drops an entry it cannot read. FAILS IF a value is altered, reordered or invented, or
    Node is absent (an absent Node must fail, never skip)."""
    import shutil
    import subprocess
    node = shutil.which("node")
    assert node, "node is required to run the read-out script's executable pin"
    vectors = [
        ["18 Nov", [["Portal visits", "1,234"], ["Whole-survey bundles downloaded", "not measured"],
                    ["Station files downloaded", "no row"]]],
        ["1 Oct", [["Portal visits", "0"], ["Station files downloaded", "0012"]]],
        ["2 Oct", [["Portal visits", "<b>7</b>"], ["Station files downloaded", "1.50"]]],
        ["3 Oct", [["Portal visits", 5], [None, "4"], ["Station files downloaded", "9"], "x"]],
        ["4 Oct", []],
    ]
    expected = [
        ["18 Nov", "Portal visits: 1,234", "Whole-survey bundles downloaded: not measured",
         "Station files downloaded: no row"],
        ["1 Oct", "Portal visits: 0", "Station files downloaded: 0012"],
        ["2 Oct", "Portal visits: <b>7</b>", "Station files downloaded: 1.50"],
        ["3 Oct", "Station files downloaded: 9"],
        ["4 Oct"],
    ]
    driver = tmp_path / "readout_driver.js"
    driver.write_text(
        "const m = require(process.argv[2]);\n"
        "const v = JSON.parse(process.argv[3]);\n"
        "process.stdout.write(JSON.stringify(v.map(([l, e]) => m.formatReadout(l, e))));\n",
        encoding="utf-8")
    out = subprocess.run([node, str(driver), str(_USAGE_JS), json.dumps(vectors)],
                         capture_output=True, text=True, timeout=30, check=False)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == expected


def _hits(svg: str) -> list[dict]:
    return [dict(zip(("i", "day", "label", "v", "cx", "title"), m)) for m in re.findall(
        r'<rect class="u-hit" [^>]*data-i="(\d+)" data-day="([^"]+)" data-label="([^"]+)" '
        r'data-v="([^"]+)" data-cx="([^"]+)"><title>(.*?)</title></rect>', svg)]


def test_hover_values_match_table_twin(tmp_path):
    """For every day slot the read-out shows exactly what the table twin and the slot's own title
    show, and one index names the same day and the same crosshair position in all three charts.
    FAILS IF a hover value, a title and the twin disagree, or the charts' slots are out of step."""
    doc = _full_stats()
    doc["daily"] = [row for row in doc["daily"] if row["date"] not in ("2026-10-02", "2026-10-03")]
    doc["daily"][5].pop("kinds")
    days = sections(_get(tmp_path, doc))["days"]
    twin = {row[0]: row for row in table_rows(days)}
    slots: dict[str, list[dict]] = {}
    for chart, column in (("visits", 1), ("bundles", 2), ("files", 3)):
        svg = days.split(f'data-u-chart="{chart}"', 1)[1].split("</svg>", 1)[0]
        hits = _hits(svg)
        assert len(hits) == 184, chart
        slots[chart] = hits
        for hit in hits:
            assert html.unescape(hit["title"]) == f'{hit["label"]}: {html.unescape(hit["v"])}'
            day = dt.date.fromisoformat(hit["day"])
            row = twin.get(f"{day.day} {usagepage._MONTHS[day.month - 1]} {day.year}")
            if row is None:
                assert hit["v"] == "no row", hit
            else:
                assert html.unescape(hit["v"]) == row[column], (chart, hit)
        bars = dict(re.findall(r'<path class="u-bar [^"]*" data-i="(\d+)"[^>]*><title>(.*?)</title>',
                               svg))
        by_i = {h["i"]: h for h in hits}
        for i, title in bars.items():
            assert title == by_i[i]["title"], (chart, i)
    assert {h["v"] for h in slots["visits"]} >= {"no row"}
    assert "not measured" in {h["v"] for h in slots["files"]}
    for a, b, c in zip(slots["visits"], slots["bundles"], slots["files"]):
        assert (a["i"], a["day"], a["label"], a["cx"]) == (b["i"], b["day"], b["label"], b["cx"]) \
            == (c["i"], c["day"], c["label"], c["cx"])


def test_usage_page_has_one_own_script_and_no_inline_script(tmp_path):
    """In every state the page loads exactly one script of its own, the read-out, as the last element
    of the body, beside the shell's shared scripts; no script is inline and no data island is
    embedded. FAILS IF the tag is missing, doubled or misplaced, a script has no src, or the
    script's text is embedded in the page."""
    body_js = usagepage.USAGE_JS.strip()
    for name, page in _states(tmp_path).items():
        tags = re.findall(r"<script\b[^>]*>(.*?)</script>", page, re.S)
        assert all(inner == "" for inner in tags), name
        srcs = re.findall(r'<script\b[^>]*\bsrc="([^"]+)"[^>]*>', page)
        assert len(srcs) == len(re.findall(r"<script\b", page)), name
        assert srcs.count(_JS_ROUTE) == 1, name
        assert set(srcs) == {"/gateway/curator/context-bar.js", "/gateway/curator/ui.js", _JS_ROUTE}
        assert page.rstrip().endswith(_JS_TAG + "</body></html>"), name
        assert body_js[:80] not in page, name
        assert 'type="application/json"' not in page and "<template" not in page, name


def test_usage_page_requests_no_other_origin(tmp_path):
    """Every script, stylesheet, image and frame the page loads comes from this origin, and the only
    absolute link is the navigation link to the counting rules. FAILS IF any resource names another
    origin or a protocol-relative path, or a second absolute link appears."""
    for name, page in _states(tmp_path).items():
        for attr, value in re.findall(r'\b(src|srcset|data|poster|action)="([^"]*)"', page):
            assert value.startswith("/") and not value.startswith("//"), (name, attr, value)
        for tag in re.findall(r"<link\b[^>]*>", page):
            href = re.search(r'href="([^"]*)"', tag)
            if href:
                assert href.group(1).startswith("/") and not href.group(1).startswith("//"), tag
        absolute = [h for h in re.findall(r'href="([^"]*)"', page)
                    if "://" in h or h.startswith("//")]
        assert absolute == [usagepage._DOCS_URL], (name, absolute)
        assert re.findall(r"url\(\s*['\"]?(?:[a-z]+:|//)", page, re.I) == [], name
        assert "@import" not in page, name


def test_usage_page_renders_same_figures_without_script(monkeypatch):
    """The page is the same bytes whether or not the read-out script is available, so every figure in
    the tiles, tables and titles is server-rendered. FAILS IF the page depends on the script's
    content, or a figure is left for the script to fill."""
    nav = _golden_nav()
    for doc in (_full_stats(), None, _fresh(_full_stats())):
        with_js = usagepage.render_usage_page(stats=doc, stats_stale=doc is None, nav=nav)
        monkeypatch.setattr(usagepage, "USAGE_JS", "")
        without = usagepage.render_usage_page(stats=doc, stats_stale=doc is None, nav=nav)
        monkeypatch.undo()
        assert with_js == without
    page = usagepage.render_usage_page(stats=_full_stats(), stats_stale=False, nav=nav)
    parts = sections(page)
    assert text(tile(page, "Portal visits")).startswith("Portal visits 110")
    days = parts["days"]
    assert len(table_rows(days)) == 184
    assert len(table_rows(parts["months"])) == 12
    hits = _hits(days.split('data-u-chart="visits"', 1)[1].split("</svg>", 1)[0])
    assert hits and all(h["title"].endswith(h["v"]) for h in hits)
    assert '<div class="u-tip" id="u-tip" hidden aria-hidden="true"></div>' in days
