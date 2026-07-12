"""C45 usage-analytics screen (gateway half — record D4/D5).

The consumer side of the aggregator: the gateway reads stats.json SERVER-side (serve_state.read_stats,
the ops-status.json seam) and renders the READ-ONLY Analytics screen (Operations rail). These pins
prove the load-bearing behaviours against INDEPENDENT OBSERVABLES (the rendered HTML, the staleness
boolean, the response status), mirroring test_c43_stage2b_ops.py. Async bodies run under conftest.run()
(no pytest-asyncio). ZERO JS on the screen (a server-rendered SVG), enforced by a CSP sweep.

Each pin states its failure criterion (Invariant 10). Pure gateway stack — no new skips.
"""
from __future__ import annotations

import json
import re
import time

from gateway import curatorpage, serve_state
from gateway.tests.conftest import app_client, curator_login, run


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _fresh_stats(**over) -> dict:
    """A schema-valid, FRESH stats.json (generated now). Tests override one block to drive a case."""
    doc = {
        "schema": 1, "timer_period_min": 1440, "generated_at": _now_iso(),
        "since": "2026-07-08", "last_folded_date": "2026-07-11",
        "totals": {"downloads": 137, "visits": 512, "download_bytes": 5_242_880, "unattributed": 4},
        "downloads": {
            "by_format": {"edi": 80, "emtfxml": 40, "mth5": 13, "unattributed": 4},
            "by_survey": {"CI Sample Survey": 120, "Burra 2017": 13},
            "by_dataset": {
                "edi/sample-survey/Vulcan_A1.edi": {"survey": "CI Sample Survey", "station": "A1",
                                                    "slug": None, "format": "edi", "downloads": 42},
                "bundles/sample-survey-tf.h5": {"survey": "CI Sample Survey", "station": None,
                                                "slug": "sample-survey", "format": "mth5",
                                                "downloads": 13},
            },
        },
        "countries": {"AU": 300, "US": 120, "NZ": 40, "unknown": 52},
        "daily": [{"date": "2026-07-08", "downloads": 10, "visits": 40},
                  {"date": "2026-07-09", "downloads": 30, "visits": 120},
                  {"date": "2026-07-10", "downloads": 55, "visits": 200},
                  {"date": "2026-07-11", "downloads": 42, "visits": 152}],
    }
    doc.update(over)
    return doc


def _write_stats(cfg, doc: dict) -> None:
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    (cfg.state_dir / serve_state.STATS_FILENAME).write_text(json.dumps(doc), encoding="utf-8")


# --------------------------------------------------------------------------------------------------
# Render: a fresh stats.json paints the cards, tables, and the SVG sparkline.
# --------------------------------------------------------------------------------------------------
def test_analytics_renders_cards_tables_and_sparkline(tmp_path):
    """RENDER PIN. A fresh stats.json renders the summary cards (downloads/visits), the top-datasets
    table (survey/station/format/count), the country table, and a server-rendered SVG sparkline. FAILS
    IF a headline number, a dataset row, a country, or the <svg> is absent."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _fresh_stats())
            r = await client.get("/gateway/curator/analytics")
            assert r.status_code == 200
            html = r.text
            assert "Usage analytics" in html
            assert "137" in html and "512" in html, "download/visit totals must render"
            assert "CI Sample Survey" in html and ">A1<" in html and ">42<" in html
            assert "sample-survey" in html and "(bundle)" in html   # a bundle row
            assert ">AU<" in html and ">300<" in html               # the country table
            assert "<svg" in html and "polyline" in html            # the server-rendered sparkline
            assert "5.0 MB" in html                                 # the human download volume
            assert "Updated" in html                                # the fresh chip
    run(_body())


def test_analytics_rail_link_present(tmp_path):
    """NAV PIN. The Analytics screen sits under the Operations rail group and links to its route. FAILS
    IF the rail entry is missing (the screen would be unreachable via the nav)."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _fresh_stats())
            r = await client.get("/gateway/curator/analytics")
            assert 'href="/gateway/curator/analytics"' in r.text
            assert ">Analytics<" in r.text
    run(_body())


# --------------------------------------------------------------------------------------------------
# Staleness: old generated_at -> STALE banner, still 200 (fail-closed both directions).
# --------------------------------------------------------------------------------------------------
def test_analytics_stale_stats_shows_stale_banner_and_200(tmp_path):
    """STALENESS PIN. A stats.json older than ~2 aggregation periods must flip the screen to a STALE
    banner (the serve_state band) and still 200 — never a 500, never rendering the old figures as live.
    FAILS IF a stale file renders without the STALE banner, or 500s."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _fresh_stats(generated_at="2020-01-01T00:00:00Z"))   # ancient -> stale
            r = await client.get("/gateway/curator/analytics")
            assert r.status_code == 200
            assert "STALE" in r.text, "an old generated_at must show the STALE banner"
            assert "Updated" not in r.text, "a stale file must NOT render the fresh 'Updated' chip"
    run(_body())


def test_analytics_missing_stats_shows_empty_state_not_500(tmp_path):
    """EMPTY-STATE PIN. With NO stats.json (the aggregator not installed / not yet run), the screen
    renders an honest empty state and still 200s — never a 500. FAILS IF a missing stats.json 500s or
    renders fabricated figures."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            r = await client.get("/gateway/curator/analytics")
            assert r.status_code == 200
            assert "No usage analytics yet" in r.text
            assert "ausmt-stats" in r.text   # points the operator at the timer to install
    run(_body())


def test_analytics_stale_staleness_is_fail_closed_both_directions():
    """STALENESS UNIT (fail-closed both directions, reusing the serve_state band). A missing generated_at
    is STALE; a FUTURE generated_at is STALE; a within-window one is fresh. FAILS IF stale data could
    render as live in any of these."""
    base = {"timer_period_min": 1440}
    now = 1_800_000_000.0

    def iso(epoch):
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))
    assert serve_state.ops_status_stale(None) is True
    assert serve_state.ops_status_stale(dict(base)) is True                          # no generated_at
    assert serve_state.ops_status_stale(dict(base, generated_at=iso(now + 3600)),
                                        now_epoch=now) is True                        # future -> stale
    assert serve_state.ops_status_stale(dict(base, generated_at=iso(now - 3600)),
                                        now_epoch=now) is False                       # 1h old -> fresh
    assert serve_state.ops_status_stale(dict(base, generated_at=iso(now - 3 * 86400)),
                                        now_epoch=now) is True                        # 3 days -> stale


# --------------------------------------------------------------------------------------------------
# CSP sweep: the Analytics route ships NO inline JS (server-rendered SVG only).
# --------------------------------------------------------------------------------------------------
def test_analytics_screen_has_no_inline_js(tmp_path):
    """CSP SWEEP (record D13 extended). The Analytics screen must ship no inline <script> (every
    <script> carries src=) and no on*= handlers — both dead under the strictPages CSP (script-src
    'self'). The daily series is a server-rendered inline SVG with no scripting. FAILS IF the screen
    ships any inline JS (fresh OR empty state)."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            for setup in (lambda: _write_stats(cfg, _fresh_stats()), lambda: None):
                setup()
                r = await client.get("/gateway/curator/analytics")
                assert r.status_code == 200
                html = r.text
                for m in re.finditer(r"<script\b[^>]*>", html):
                    assert re.search(r"\bsrc\s*=", m.group(0)), f"inline <script>: {m.group(0)}"
                handlers = re.findall(r"<[^>]*\son\w+\s*=", html)
                assert handlers == [], f"inline handlers on the analytics screen: {handlers}"
    run(_body())


# --------------------------------------------------------------------------------------------------
# Unit: the sparkline + helpers (no framework needed).
# --------------------------------------------------------------------------------------------------
def test_sparkline_degrades_and_escapes():
    """SPARKLINE UNIT. Empty daily -> a note (no SVG); a populated series -> an <svg> with two polylines;
    a single-day series -> markers not a degenerate line. FAILS IF an empty series emits a broken SVG or
    a populated one omits the series."""
    assert "<svg" not in curatorpage._daily_sparkline([])              # noqa: SLF001
    one = curatorpage._daily_sparkline([{"date": "2026-07-10", "downloads": 3, "visits": 5}])  # noqa: SLF001
    assert "<svg" in one and "circle" in one and "polyline" not in one
    many = curatorpage._daily_sparkline(                               # noqa: SLF001
        [{"date": "2026-07-10", "downloads": 3, "visits": 5},
         {"date": "2026-07-11", "downloads": 8, "visits": 9}])
    assert many.count("polyline") == 2


def test_human_bytes_scales():
    """HUMAN-BYTES UNIT. Byte counts render in a sensible unit; a non-number degrades to '—'."""
    assert curatorpage._human_bytes(512) == "512 B"           # noqa: SLF001
    assert curatorpage._human_bytes(5_242_880) == "5.0 MB"     # noqa: SLF001
    assert curatorpage._human_bytes(None) == "—"               # noqa: SLF001
