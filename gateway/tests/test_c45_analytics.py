"""C45 usage-analytics screen (gateway half — record D4/D5).

The consumer side of the aggregator: the gateway reads stats.json SERVER-side (serve_state.read_stats,
the ops-status.json seam) and renders the READ-ONLY Analytics screen (Operations rail). These pins
prove the load-bearing behaviours against INDEPENDENT OBSERVABLES (the rendered HTML, the staleness
boolean, the response status), mirroring test_c43_stage2b_ops.py. Async bodies run under conftest.run()
(no pytest-asyncio). ZERO JS on the screen (a server-rendered SVG), enforced by a CSP sweep.

Each pin states its failure criterion (Invariant 10). Pure gateway stack — no new skips.
"""
from __future__ import annotations

import csv
import io
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


# ==================================================================================================
# Funding-detail lane: the richer screen (per-survey volume, station/bundle split, API line, the
# quarterly view) + the CSV export, over BOTH aggregate schemas.
# ==================================================================================================

def _v2_stats(**over) -> dict:
    """A schema-2 stats.json: the v1 blocks plus per-survey volume, by_kind, the API line, per-day
    detail, and the permanent monthly rollups spanning three calendar months."""
    doc = _fresh_stats()
    doc["schema"] = 2
    doc["detail_since"] = "2026-05-01"
    doc["totals"]["api_requests"] = 61
    doc["downloads"]["by_survey"] = {"CI Sample Survey": {"downloads": 120, "bytes": 4_194_304},
                                     "Burra 2017": {"downloads": 13, "bytes": 1_048_576}}
    doc["downloads"]["by_kind"] = {"file": 100, "bundle": 33}
    doc["downloads"]["by_dataset"]["edi/sample-survey/Vulcan_A1.edi"]["bytes"] = 1_310_720
    doc["daily"] = [{"date": "2026-07-08", "downloads": 10, "visits": 40, "download_bytes": 1024,
                     "api_requests": 2, "networks": 7, "formats": {"edi": 10}, "kinds": {"file": 10}},
                    {"date": "2026-07-11", "downloads": 42, "visits": 152, "download_bytes": 4096,
                     "api_requests": 9, "networks": 19, "formats": {"edi": 30, "mth5": 12},
                     "kinds": {"file": 30, "bundle": 12}}]
    doc["monthly"] = [
        {"month": "2026-05", "downloads": 30, "visits": 90, "download_bytes": 1_048_576,
         "unattributed": 1, "api_requests": 12, "days": 20, "seeded_days": 0,
         "formats": {"edi": 25, "mth5": 5}, "kinds": {"file": 25, "bundle": 5},
         "surveys": {"CI Sample Survey": {"downloads": 30, "bytes": 1_048_576}},
         "countries": {"AU": 60, "unknown": 3}},
        {"month": "2026-06", "downloads": 55, "visits": 210, "download_bytes": 2_097_152,
         "unattributed": 2, "api_requests": 27, "days": 29, "seeded_days": 0,
         "formats": {"edi": 40, "emtfxml": 10, "mth5": 5}, "kinds": {"file": 50, "bundle": 5},
         "surveys": {"CI Sample Survey": {"downloads": 40, "bytes": 1_500_000},
                     "Burra 2017": {"downloads": 15, "bytes": 597_152}},
         "countries": {"AU": 150, "US": 60}},
        {"month": "2026-07", "downloads": 52, "visits": 212, "download_bytes": 2_097_152,
         "unattributed": 1, "api_requests": 22, "days": 4, "seeded_days": 0,
         "formats": {"edi": 40, "mth5": 12}, "kinds": {"file": 40, "bundle": 12},
         "surveys": {"CI Sample Survey": {"downloads": 52, "bytes": 2_097_152}},
         "countries": {"AU": 200, "NZ": 12}},
    ]
    doc.update(over)
    return doc


def test_analytics_renders_survey_volume_kind_split_api_line_and_reach(tmp_path):
    """FUNDING-DETAIL RENDER PIN. The screen must surface the funding-grade breakdowns: downloads BY
    SURVEY with a volume column, the single-station vs whole-survey-bundle split, the API-consumer line
    (distinct from visits), and the distinct-network reach proxy. FAILS IF any of those is missing from
    the rendered page."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v2_stats())
            r = await client.get("/gateway/curator/analytics")
            assert r.status_code == 200
            html = r.text
            assert "API requests" in html and ">61<" in html, "the API-consumer line must render"
            assert "Downloads by survey" in html
            assert "Burra 2017" in html and "1.0 MB" in html, "per-survey volume must render"
            assert "Single-station files" in html and ">100<" in html and ">33<" in html
            assert "Distinct networks" in html and ">19<" in html, "the reach proxy must render"
            assert "/24" in html, "the reach proxy must say what a network is"
    run(_body())


def test_analytics_renders_last_three_calendar_months_side_by_side(tmp_path):
    """QUARTERLY PIN. The screen must show the last THREE calendar months side by side with the funding
    metrics down the left, and must not invent a month that was never folded. FAILS IF fewer than the
    retained months render, if a fourth month appears, or if the per-month metrics are absent."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            doc = _v2_stats()
            doc["monthly"].insert(0, {"month": "2026-04", "downloads": 9, "visits": 9,
                                      "download_bytes": 10, "unattributed": 0, "api_requests": 0,
                                      "days": 3, "seeded_days": 0, "formats": {}, "kinds": {},
                                      "surveys": {}, "countries": {}})
            _write_stats(cfg, doc)
            r = await client.get("/gateway/curator/analytics")
            html = r.text
            assert "Quarterly breakdown" in html
            for label in ("May 2026", "Jun 2026", "Jul 2026"):
                assert label in html, f"the quarterly view must show {label}"
            assert "Apr 2026" not in html, "only the last three calendar months sit side by side"
            assert "Active days folded" in html and "Station files / bundles" in html
            assert "4 month(s) of rollups are retained" in html
    run(_body())


def test_analytics_does_not_fabricate_months_before_the_fold(tmp_path):
    """BACKFILL-HONESTY PIN. With no monthly rollups yet (a box that has only ever run the older fold),
    the quarterly section must say the rollups have not started rather than render empty or invented
    months, and a month carrying pre-detail days must be flagged as partial. FAILS IF the screen shows a
    month it never folded, or presents a partial month's volume as complete."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _fresh_stats())                     # schema 1: no monthly block at all
            r = await client.get("/gateway/curator/analytics")
            assert r.status_code == 200
            assert "No monthly rollups yet" in r.text
            assert "nothing earlier is backfilled" in r.text

            partial = _v2_stats()
            partial["monthly"][-1]["seeded_days"] = 3
            _write_stats(cfg, partial)
            r2 = await client.get("/gateway/curator/analytics")
            assert "folded before the detailed breakdown" in r2.text
            assert "Jul 2026" in r2.text
    run(_body())


def test_analytics_renders_v1_stats_without_breaking(tmp_path):
    """SCHEMA-TOLERANCE PIN. The screen must render a LIVE schema-1 stats.json (by_survey as bare ints,
    no monthly, no by_kind, no api_requests, daily rows without detail) without a 500 and without
    inventing figures: the survey table still lists surveys, the API card reads zero, and no reach line
    is claimed for days that never counted networks. FAILS IF the older file 500s or fabricates data."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _fresh_stats())          # by_survey = {"CI Sample Survey": 120, ...}
            r = await client.get("/gateway/curator/analytics")
            assert r.status_code == 200
            html = r.text
            assert "Downloads by survey" in html and "CI Sample Survey" in html
            assert "Distinct networks" not in html, "no reach figure may be claimed for older days"
            assert "Single-station files" not in html, "no kind split may be claimed for older days"
    run(_body())


def test_analytics_detail_caveat_names_the_date_detail_began(tmp_path):
    """HONESTY PIN. When the aggregator upgraded an existing stats.json in place, the screen must name
    the date from which the detailed dimensions are real, so an older download counted in the headline
    total is not read as having a volume/format breakdown it never had. FAILS IF the caveat is missing
    when detail_since is set, or is shown when it is not."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v2_stats())
            r = await client.get("/gateway/curator/analytics")
            assert "2026-05-01" in r.text and "onward" in r.text
            _write_stats(cfg, _v2_stats(detail_since=None))
            r2 = await client.get("/gateway/curator/analytics")
            assert "onward. Earlier" not in r2.text
    run(_body())


# --------------------------------------------------------------------------------------------------
# CSV export: the "download report data" affordance.
# --------------------------------------------------------------------------------------------------
def test_analytics_monthly_csv_export_downloads_every_retained_month(tmp_path):
    """EXPORT PIN. GET /gateway/curator/analytics.csv must return a text/csv ATTACHMENT carrying EVERY
    retained month (not just the three on screen) with the funding columns and per-format columns.
    FAILS IF the export is not an attachment, omits a retained month, or drops a metric."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v2_stats())
            r = await client.get("/gateway/curator/analytics.csv")
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/csv")
            assert "attachment" in r.headers["content-disposition"]
            assert "ausmt-usage-monthly.csv" in r.headers["content-disposition"]
            rows = list(csv.reader(io.StringIO(r.text)))
            header, data = rows[0], rows[1:]
            assert header[:6] == ["month", "downloads", "download_bytes", "visits",
                                  "api_requests", "unattributed"]
            assert "format_mth5" in header and "kind_bundle" in header
            assert [d[0] for d in data] == ["2026-05", "2026-06", "2026-07"]
            june = dict(zip(header, data[1]))
            assert june["downloads"] == "55" and june["download_bytes"] == "2097152"
            assert june["api_requests"] == "27" and june["format_emtfxml"] == "10"
            assert june["countries"] == "2"
    run(_body())


def test_analytics_survey_csv_export_has_one_row_per_month_and_survey(tmp_path):
    """PER-SURVEY EXPORT PIN. The by-survey export must emit one row per (month, survey) with downloads
    and byte volume, so a funding report can quote a named survey's usage for a named month. FAILS IF
    the rows are collapsed across months or the volume is missing."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v2_stats())
            r = await client.get("/gateway/curator/analytics-surveys.csv")
            assert r.status_code == 200
            rows = list(csv.reader(io.StringIO(r.text)))
            assert rows[0] == ["month", "survey", "downloads", "download_bytes"]
            body = [tuple(x) for x in rows[1:]]
            assert ("2026-06", "CI Sample Survey", "40", "1500000") in body
            assert ("2026-06", "Burra 2017", "15", "597152") in body
            assert ("2026-05", "CI Sample Survey", "30", "1048576") in body
    run(_body())


def test_analytics_csv_export_is_session_gated_and_empty_safe(tmp_path):
    """EXPORT SAFETY PIN. The export sits behind the SAME curator session gate as the screen, and with
    NO stats.json it returns the header row alone rather than a 500 or a fabricated month. FAILS IF an
    unauthenticated request is served the numbers, or a missing aggregate errors instead of exporting
    an honest empty file."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            anon = await client.get("/gateway/curator/analytics.csv")
            assert anon.status_code != 200, "the export must not serve numbers without a session"
            await curator_login(client)
            r = await client.get("/gateway/curator/analytics.csv")
            assert r.status_code == 200
            rows = list(csv.reader(io.StringIO(r.text)))
            assert len(rows) == 1 and rows[0][0] == "month", rows
    run(_body())


def test_analytics_csv_neutralises_spreadsheet_formula_injection():
    """CSV-SAFETY PIN. A cell whose text starts with =, +, -, or @ is executed as a formula when the
    file is opened in Excel or Sheets, so the export must neutralise it. FAILS IF a survey name
    beginning with one of those characters reaches the file unquoted. NEGATIVE CONTROL: an ordinary
    name must pass through untouched (a blanket quote would corrupt every report)."""
    stats = {"monthly": [{"month": "2026-06", "surveys": {
        "=cmd|'/c calc'!A1": {"downloads": 3, "bytes": 9},
        "Burra 2017": {"downloads": 1, "bytes": 4}}}]}
    out = curatorpage.analytics_survey_csv(stats)
    rows = {r[1] for r in csv.reader(io.StringIO(out))}
    assert "'=cmd|'/c calc'!A1" in rows, "a formula-leading cell must be quoted"
    assert "Burra 2017" in rows, "an ordinary name must NOT be mangled"


def test_analytics_export_links_are_on_the_screen(tmp_path):
    """AFFORDANCE PIN. The screen must offer the 'download report data' links, else the export is
    unreachable for the owner it exists for. FAILS IF either export link is missing."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v2_stats())
            r = await client.get("/gateway/curator/analytics")
            assert 'href="/gateway/curator/analytics.csv"' in r.text
            assert 'href="/gateway/curator/analytics-surveys.csv"' in r.text
            assert "Download report data" in r.text
    run(_body())


# ==================================================================================================
# Australian STATE lane: a breakdown BENEATH the AU country row, rendered only when the fold actually
# produced it. State is the finest grain by design (a /24-masked prefix does not place a request in a
# city, and a city cell in a community this small is quasi-identifying) -- these pins hold that line.
# ==================================================================================================

def _v3_stats(**over) -> dict:
    """A schema-2 stats.json that ALSO carries the AU state breakdown, cumulatively and per month.
    The cumulative states sum to 260 against an AU country row of 300: the 40-request difference is
    real (those days folded before the state table existed) and the screen must name it, not hide it."""
    doc = _v2_stats()
    doc["by_state"] = {"NSW": 120, "VIC": 60, "QLD": 40, "WA": 20, "ACT": 10, "unattributed": 10}
    doc["monthly"][0]["by_state"] = {}                                        # May: before the table
    doc["monthly"][1]["by_state"] = {"NSW": 100, "VIC": 40, "unattributed": 10}   # June: exact (150)
    doc["monthly"][2]["by_state"] = {"NSW": 20, "VIC": 20, "QLD": 40, "WA": 20, "ACT": 10}   # 110/200
    doc.update(over)
    return doc


def test_analytics_renders_australia_by_state_beneath_the_country_row(tmp_path):
    """STATE RENDER PIN. When the fold produced a state breakdown the screen must show an 'Australia by
    state' table with the full state names and counts, and it must reconcile with the AU country row it
    sits beneath: the states plus the unattributed bucket plus the pre-table remainder equal AU. FAILS
    IF the table is missing, a state is unlabelled, or the rows do not add up to the country figure."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v3_stats())
            r = await client.get("/gateway/curator/analytics")
            assert r.status_code == 200
            html = r.text
            assert "Australia by state" in html
            assert "New South Wales" in html and ">120<" in html
            assert "Australian Capital Territory" in html and "Northern Territory" not in html, \
                "only states the fold actually saw may appear"
            assert "Not in the state table" in html, "the uncovered-prefix bucket must be shown"
            assert "Counted before state data existed" in html, \
                "the pre-table remainder must be named, not hidden"
            assert "<b>300</b>" in html, "the table must total to the AU country figure"
            # The AU country row itself is untouched -- the states are a breakdown BENEATH it.
            assert "By country" in html and ">300<" in html
    run(_body())


def test_analytics_state_table_reconciles_with_the_au_country_figure(tmp_path):
    """STATE RECONCILIATION PIN. Whatever the fold produced, the numbers the state table renders must
    sum to the AU country count exactly -- so a reader can never find the breakdown quietly smaller than
    its parent. FAILS IF the rendered rows do not add up to AU (checked directly on the row builder, so
    the arithmetic is pinned rather than the prose around it)."""
    for by_state, au, remainder in (
        ({"NSW": 120, "VIC": 60, "QLD": 40, "WA": 20, "ACT": 10, "unattributed": 10}, 300, 40),
        ({"NSW": 200, "unattributed": 100}, 300, 0),          # exactly attributed: no remainder row
        ({"TAS": 3}, 3, 0),
    ):
        rows = curatorpage._au_state_rows(by_state, au)       # noqa: SLF001
        assert sum(n for _code, _label, n in rows) == au, (rows, au)
        tail = [n for code, _label, n in rows if code == "not_counted"]
        assert tail == ([remainder] if remainder else []), (rows, remainder)


def test_analytics_omits_the_state_table_when_the_fold_produced_none(tmp_path):
    """STATE ABSENCE PIN. A box with no state table installed (or one that has not folded a day since)
    must see NO state section at all -- the screen omits rather than showing eight zeroes, which would
    read as 'no traffic from Victoria' instead of 'not measured'. FAILS IF an empty breakdown renders a
    table, a zero, or a state name."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v2_stats())          # schema 2, no by_state anywhere
            r = await client.get("/gateway/curator/analytics")
            assert r.status_code == 200
            html = r.text
            assert "Australia by state" not in html
            for name in ("New South Wales", "Queensland", "Tasmania"):
                assert name not in html, f"{name} must not appear when no state data exists"
            assert "By country" in html, "the country table is unaffected"
    run(_body())


def test_analytics_tolerates_a_stats_file_that_still_carries_legacy_day_states(tmp_path):
    """LEGACY-DAY-STATES PIN. The daily state grain was dropped (it is the finest cell in the file, and
    the small-cell argument that rules out a city rules it out too), but a box that folded before the
    drop still has a `states` map on its day rows until they age out of the 92-day window. The screen
    reads day rows for the sparkline and the reach note only, so that residue must be INERT. FAILS IF
    such a file 500s the screen, or if a day-level state figure reaches the page."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            doc = _v3_stats()
            doc["daily"][0]["states"] = {"TAS": 1}      # exactly what the pre-drop fold wrote
            _write_stats(cfg, doc)
            r = await client.get("/gateway/curator/analytics")
            assert r.status_code == 200
            html = r.text
            assert "Australia by state" in html, "the kept grains still render"
            assert "Tasmania" not in html, "a day-level state count must not reach the screen"
            assert "Distinct networks" in html, "the daily-derived panels still render"
    run(_body())


def test_analytics_state_table_says_why_it_is_state_and_not_city(tmp_path):
    """RATIONALE PIN. The screen must carry the reason the breakdown stops at state, so the next person
    reading it does not file 'add cities' as an obvious improvement. FAILS IF the note loses either
    limb of the reason: the masked /24 cannot place a request in a city, and a city cell in a community
    this small identifies a group."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v3_stats())
            html = (await client.get("/gateway/curator/analytics")).text
            assert "/24" in html
            low = html.lower()
            assert "city" in low and "state is the finest" in low
    run(_body())


def test_analytics_monthly_csv_gains_state_columns_that_reconcile_per_row(tmp_path):
    """STATE CSV PIN. The monthly export must gain one column per state seen, plus the unattributed
    bucket, plus the pre-table remainder, and every row must reconcile: the state columns sum to that
    month's AU figure. FAILS IF a state column is missing, if the columns are not in the canonical
    state order, or if a row does not add up (a funding report would then carry a silent undercount)."""
    body = curatorpage.analytics_monthly_csv(_v3_stats())
    rows = list(csv.DictReader(io.StringIO(body)))
    header = list(rows[0].keys())
    assert [h for h in header if h.startswith("state_") or h == "au_requests"] == [
        "au_requests", "state_NSW", "state_VIC", "state_QLD", "state_WA", "state_ACT",
        "state_unattributed", "state_not_counted"], header
    by_month = {r["month"]: r for r in rows}
    assert by_month["2026-06"]["state_NSW"] == "100" and by_month["2026-06"]["state_not_counted"] == "0"
    assert by_month["2026-05"]["state_not_counted"] == "60", "a pre-table month is all remainder"
    assert by_month["2026-07"]["state_QLD"] == "40" and by_month["2026-07"]["state_not_counted"] == "90"
    for r in rows:
        cols = sum(int(r[h]) for h in header if h.startswith("state_"))
        assert cols == int(r["au_requests"]), r


def test_analytics_monthly_csv_has_no_state_columns_without_state_data():
    """CSV ABSENCE PIN. A box that never folded a state must export the SAME columns it exports today --
    no empty state columns implying a measured zero. FAILS IF the state columns appear unconditionally."""
    header = curatorpage.analytics_monthly_csv(_v2_stats()).splitlines()[0]
    assert "state_" not in header and "au_requests" not in header
    assert "countries" in header, "the existing columns are untouched"
    # And an entirely absent stats.json still yields a header row alone, not an error.
    assert curatorpage.analytics_monthly_csv(None).strip().splitlines()[0].startswith("month,")
