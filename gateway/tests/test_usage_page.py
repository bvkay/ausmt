"""The curator Usage page: its shell seam, its rail entry and the helpers it renders with.

Each test states what must hold and how it fails. Async bodies run under conftest.run().
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import time
from html.parser import HTMLParser
from pathlib import Path

import pytest

from gateway import curatorpage, serve_state
from gateway.tests.conftest import app_client, curator_login, run

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
    with its key and route unchanged. FAILS IF the label still reads Analytics, the route moves, or a
    page highlights the entry when it is not the analytics page."""
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
