"""The curator Usage page: its shell seam, its rail entry and the helpers it renders with.

Each test states what must hold and how it fails. Async bodies run under conftest.run().
"""
from __future__ import annotations

import hashlib
import json
import re
import time
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
