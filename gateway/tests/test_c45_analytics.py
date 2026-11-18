"""Usage-analytics screen (gateway half).

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


def _cells(row_html: str) -> list[str]:
    """The rendered text of each <td> in one table row, tags stripped. Lets a pin assert on ONE cell
    instead of on the whole row: the by-survey row carries several independently-degrading columns,
    so 'not measured' appearing somewhere in it says nothing about which column it came from."""
    return [re.sub(r"<[^>]+>", "", c).strip()
            for c in re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)]


def _country_cell(row_html: str) -> str:
    """The Countries cell of a Downloads-by-survey row (survey, downloads, volume, COUNTRIES, split).
    The row split passed in starts AFTER the survey name, so the country cell is the third <td>."""
    return _cells(row_html)[2]


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
    """CSP SWEEP (extended). The Analytics screen must ship no inline <script> (every
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
# Funding-detail workflow: the richer screen (per-survey volume, station/bundle split, API line, the
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
    """PER-SURVEY EXPORT PIN. The by-survey export must emit one row per (month, survey) with downloads,
    byte volume and the country count, so a funding report can quote a named survey's usage for a named
    month. FAILS IF the rows are collapsed across months or a column is missing."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v2_stats())
            r = await client.get("/gateway/curator/analytics-surveys.csv")
            assert r.status_code == 200
            rows = list(csv.reader(io.StringIO(r.text)))
            assert rows[0] == ["month", "survey", "downloads", "download_bytes", "countries",
                               "files", "bundles"]
            body = [tuple(x[:4]) for x in rows[1:]]
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
    unreachable for the custodian it exists for. FAILS IF either export link is missing."""
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
# Australian STATE workflow: a breakdown BENEATH the AU country row, rendered only when the fold actually
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


# ==================================================================================================
# Counting-honesty workflow (screen half): say what each figure covers, and never render a figure that
# was not measured.
#
# The aggregator half of this feature changed what is counted (client classes, the within-day dedupe,
# 206, the served schema as an API path, API requests joining the geo count, release bundles). The
# screen's job is to keep every caption true to that, and to stop presenting a seeded month's zeroes
# as measurements -- the same omit-rather-than-fabricate rule the state table has always applied.
# ==================================================================================================

def _seeded_month(month: str = "2026-07", **over) -> dict:
    """A month whose every folded day predates the detailed dimensions: real downloads and visits,
    and nothing else measured at all. This is the live July shape that renders '0 / 0' and '0 B'."""
    row = {"month": month, "downloads": 41, "visits": 160, "download_bytes": 0, "unattributed": 0,
           "api_requests": 0, "days": 7, "seeded_days": 7, "geo_days": 0,
           "formats": {}, "kinds": {}, "surveys": {}, "countries": {}, "by_state": {},
           "downloads_by_client": {}}
    row.update(over)
    return row


def test_a_fully_seeded_month_says_not_measured_instead_of_rendering_zeroes(tmp_path):
    """SEEDED-MONTH PIN. A month whose days were ALL folded before the detailed dimensions existed has
    no volume, no format split, no station/bundle split, no countries and no top survey. Rendering
    those as '0 B', '0 / 0' and a bare 0 states a measurement that was never taken, which is exactly
    what the state table refuses to do when it omits itself rather than show eight zeroes. Such a cell
    must read 'not measured'. FAILS IF a fabricated zero survives, or if the real downloads and visits
    of that month are suppressed along with them."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            doc = _v2_stats()
            doc["monthly"] = [_seeded_month()]
            _write_stats(cfg, doc)
            html = (await client.get("/gateway/curator/analytics")).text
            table = html.split("Quarterly breakdown", 1)[1].split("Downloads by survey", 1)[0]
            assert table.count("not measured") >= 5, \
                "every unmeasured metric of a fully seeded month must say so"
            assert ">0 B<" not in table, "a seeded month has no measured volume to render as 0 B"
            assert "0 / 0" not in table, "a seeded month has no measured station/bundle split"
            assert ">41<" in table and ">160<" in table, \
                "the downloads and visits of a seeded month ARE real and must still render"
            assert ">7<" in table, "the active-day count is real too"
    run(_body())


def test_a_measured_month_still_renders_its_real_zeroes(tmp_path):
    """NEGATIVE CONTROL for the pin above. A month that WAS measured and genuinely saw no unattributed
    downloads must render 0, not 'not measured': the degrade must distinguish 'we did not measure this'
    from 'we measured it and it was nothing'. FAILS IF the degrade fires on a fully detailed month,
    which would turn every real zero into a claim of ignorance."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            doc = _v4_stats()
            doc["monthly"] = [dict(doc["monthly"][0], seeded_days=0, unattributed=0)]
            _write_stats(cfg, doc)
            html = (await client.get("/gateway/curator/analytics")).text
            table = html.split("Quarterly breakdown", 1)[1].split("Downloads by survey", 1)[0]
            assert "not measured" not in table, "a fully measured month claims no missing measurement"
            assert "1.0 MB" in table, "its measured volume still renders"
    run(_body())


def test_the_partial_dimension_disclosures_name_countries_and_unattributed(tmp_path):
    """DISCLOSURE PIN. Both honesty lines enumerate which dimensions are partial, and both omitted
    COUNTRIES and UNATTRIBUTED, which is why a month showing 'Countries: 1' beside a headline of 11
    reads as a bug rather than as the forward-only seam it is. Both lines must name every partial
    dimension, INCLUDING the ones the later work added, and each must attach them to the seam they actually
    belong to: the caveat's dated sentence covers the v1 hinge, and the dimensions that began at the
    later fold are named in their own sentence, which does NOT claim that date. FAILS IF either line
    omits countries or unattributed, if the new dimensions land undisclosed, or if the dated sentence
    swallows them."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            doc = _v2_stats()
            doc["monthly"][-1]["seeded_days"] = 3
            _write_stats(cfg, doc)
            html = (await client.get("/gateway/curator/analytics")).text
            dated = html.split("Per-survey volume", 1)[1].split("</p>", 1)[0]
            for term in ("countr", "unattributed"):
                assert term in dated.lower(), f"the detail caveat must name {term}: {dated}"
            assert "onward" in dated, "the established 'counted from ... onward' pattern must stand"
            assert "2026-05-01" in dated, "the dated sentence names the date it is dating"
            later = html.split("A second set of dimensions", 1)[1].split("</p>", 1)[0]
            for term in ("browser", "scripted", "de-duplication", "API requests", "network peak"):
                assert term in later, f"the later-seam sentence must name {term}: {later}"
            assert "2026-05-01" not in later, \
                "the later dimensions did not begin at the v1 hinge and must not claim it"
            seeded = html.split("folded before the detailed breakdown", 1)[1].split("</p>", 1)[0]
            for term in ("countr", "unattributed"):
                assert term in seeded.lower(), f"the seeded-month note must name {term}: {seeded}"
            current = html.split("folded before the current counting rules", 1)[1].split("</p>", 1)[0]
            for term in ("browser/scripted", "peak-networks", "country counts", "geo-day"):
                assert term in current, f"the current-rules note must name {term}: {current}"
    run(_body())


def test_the_screen_names_every_machine_readable_entry_point(tmp_path):
    """API-SURFACE COPY PIN. The API line counts four documented entry points: the products manifest,
    the MTCAT document, the served JSON Schema every validator resolves from that document's own $id,
    and the stations GeoJSON a GIS opens straight from the URL. The screen
    states what the figure covers, so it must name all four or the number means something the reader
    cannot check. FAILS IF the preamble still claims two or three, or omits any of the paths."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v2_stats())
            html = (await client.get("/gateway/curator/analytics")).text
            for path in ("/data/products/manifest.json", "/data/mtcat.json",
                         "/data/mtcat.schema.json", "/data/stations.geojson"):
                assert path in html, f"the preamble must name the API path {path}"
            assert "four documented" in html
            assert "two documented" not in html and "three documented" not in html
    run(_body())


def test_the_request_scope_captions_include_api_requests(tmp_path):
    """GEO SCOPE CAPTION PIN. API requests now count toward the country map, so both tables built on
    that map must say so: the country table and the Australia-by-state table beneath it. Leaving either
    caption at 'downloads + visits' would understate its own scope, and the two must agree because the
    state rows reconcile against the AU country row. FAILS IF either caption is stale, or if they
    disagree."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v3_stats())
            html = (await client.get("/gateway/curator/analytics")).text
            assert "Requests (downloads + visits)" not in html, "the caption must state its real scope"
            assert html.count('<th class="num">Requests (downloads + visits + API)</th>') == 2, \
                "the country table and the state table must carry the SAME scope caption"
    run(_body())


def test_the_countries_card_says_it_excludes_unknown(tmp_path):
    """CARD SCOPE PIN. The Countries card counts distinct codes EXCLUDING 'unknown', while the country
    table below lists 'unknown' as a row, so the card reads one lower than the table has rows and gets
    queried every time. The card must say what it excludes. FAILS IF the card label is silent about
    it."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v2_stats())
            html = (await client.get("/gateway/curator/analytics")).text
            assert "Countries (excluding unknown)" in html
    run(_body())


def test_the_reach_note_labels_the_date_it_actually_shows(tmp_path):
    """REACH LABEL PIN. The reach note called its date 'the most recent folded day', but it is the most
    recent day carrying a NETWORK COUNT, which on a quiet service can lag the fold watermark by days
    with nothing on screen saying so. The label must describe the date it shows. FAILS IF the note
    still claims to be showing the fold watermark."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            doc = _v2_stats()
            doc["last_folded_date"] = "2026-07-20"      # the watermark has moved well past the last
            doc["daily"][-1]["date"] = "2026-07-11"     # day that carried a network count
            _write_stats(cfg, doc)
            html = (await client.get("/gateway/curator/analytics")).text
            assert "most recent day with a network count" in html
            assert "most recent folded day" not in html
    run(_body())


def test_the_monthly_csv_exposes_how_many_days_carried_geo(tmp_path):
    """CSV PARTIALITY PIN. The monthly export derives au_requests from that month's own country map,
    which is forward-only, so every state_* column reconciles to it exactly while the whole row
    under-reports the month's Australian traffic. The file looks self-consistent and is wrong, and it
    is the artefact that leaves the building. A geo_days column makes the partiality machine-visible
    beside the figure it qualifies. FAILS IF the column is absent or does not carry the aggregator's
    own count."""
    doc = _v4_stats()
    doc["monthly"][1]["geo_days"] = 29
    doc["monthly"][2]["geo_days"] = 1                    # July: one day of geo behind 4 folded days
    doc["monthly"][2]["detail_days"] = 1
    body = curatorpage.analytics_monthly_csv(doc)
    rows = list(csv.DictReader(io.StringIO(body)))
    header = list(rows[0].keys())
    assert "geo_days" in header, header
    assert header.index("geo_days") == header.index("days_without_detail") + 1, \
        "geo_days belongs beside the other coverage columns, not among the counts"
    by_month = {r["month"]: r for r in rows}
    assert by_month["2026-06"]["geo_days"] == "29"
    assert by_month["2026-07"]["geo_days"] == "1" and by_month["2026-07"]["active_days"] == "4"
    assert by_month["2026-07"]["au_requests"] == "200", "the AU figure itself is unchanged"


def test_the_monthly_csv_tolerates_a_month_written_before_geo_days_existed():
    """CSV TOLERANCE PIN. geo_days is an additive column, so a retained month written before it existed
    must export without raising and without blanking the row. It must also not export a ZERO: that
    month contributed countries on days the counter was not there to count, so a 0 read beside a real
    active_days says the month had no geography at all, which is the under-report the column exists to
    expose. The cell is EMPTY and `detail_days` says why. FAILS IF an older month row breaks the
    export, or fills the cell with a fabricated zero."""
    doc = _v2_stats()
    for row in doc["monthly"]:
        row.pop("geo_days", None)
    rows = list(csv.DictReader(io.StringIO(curatorpage.analytics_monthly_csv(doc))))
    assert all(r["geo_days"] == "" for r in rows), rows
    assert all(r["detail_days"] == "0" for r in rows), "the counter that explains the empty cell"
    assert all(int(r["downloads"]) > 0 and int(r["active_days"]) > 0 for r in rows), \
        "the counts the month DID measure are untouched"


# ==================================================================================================
# State and funding detail (screen half): the columns a report is actually written from.
#
# The request-count column and its reconciliation rows are UNTOUCHED -- the exact-total promise
# against the AU country row is load-bearing and its pins above still hold it. The new columns sit
# beside it and answer the questions that promise never could: how much was downloaded from a state,
# how many bytes, how many countries a named survey reached, and what the peak reach of a month was.
# ==================================================================================================

def _v4_stats(**over) -> dict:
    """A stats.json carrying the state DETAIL map, the per-survey country lists, the monthly reach
    peak, the client split and the served-survey denominator. The detail deliberately covers FEWER
    states than the request map: NSW and VIC were counted before the detail existed, so the screen must
    say 'not measured' for them rather than render a zero.

    Every month carries `detail_days` equal to its active days: this is the shape a box folding under
    the CURRENT rules writes, so it is the fixture against which the not-measured degrades must NOT
    fire. `_v2_stats`/`_v3_stats` deliberately carry no such counter, because that is the shape a box
    that folded before this fold existed carries, and it is what those degrades exist for."""
    doc = _v3_stats()
    doc["total_served_surveys"] = 40
    doc["by_state_detail"] = {
        "QLD": {"downloads": 25, "visits": 14, "api": 1, "bytes": 3_145_728},
        "WA": {"downloads": 12, "visits": 8, "api": 0, "bytes": 1_048_576},
        "unattributed": {"downloads": 4, "visits": 6, "api": 0, "bytes": 4096},
    }
    doc["totals"]["downloads_by_client"] = {"browser": 96, "scripted": 41}
    doc["downloads"]["by_survey"] = {
        "CI Sample Survey": {"downloads": 120, "bytes": 4_194_304,
                             "countries": ["AU", "DE", "NZ", "US", "unknown"]},
        "Burra 2017": {"downloads": 13, "bytes": 1_048_576, "countries": ["AU"]},
    }
    for row, peak, split in zip(doc["monthly"], (11, 23, 19),
                                ({"browser": 28, "scripted": 2},
                                 {"browser": 40, "scripted": 15},
                                 {"browser": 30, "scripted": 22})):
        row["networks_peak"] = peak
        row["downloads_by_client"] = split
        row["surveys"] = {k: dict(v, countries=["AU", "NZ"]) for k, v in row["surveys"].items()}
        row["detail_days"] = row["days"]
        row["geo_days"] = row["days"]
    doc["monthly"][2]["by_state_detail"] = {
        "QLD": {"downloads": 25, "visits": 14, "api": 1, "bytes": 3_145_728}}
    doc.update(over)
    return doc


def test_the_state_table_gains_downloads_visits_api_and_volume_columns(tmp_path):
    """STATE DETAIL RENDER PIN. 'Requests from Queensland' is not what a funding report asks; it asks
    how much was downloaded and how many bytes that was. The state table must carry Downloads, Visits,
    API and Volume beside the request count. FAILS IF a column is missing or a figure is misplaced."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v4_stats())
            html = (await client.get("/gateway/curator/analytics")).text
            table = html.split("Australia by state", 1)[1]
            for head in ("Downloads", "Visits", "API", "Volume"):
                assert f">{head}</th>" in table, f"the state table must carry a {head} column"
            assert "3.0 MB" in table, "Queensland's volume must render"
            assert ">25<" in table and ">14<" in table, "its downloads and visits must render"
    run(_body())


def test_states_counted_before_the_detail_existed_say_not_measured(tmp_path):
    """STATE DETAIL FORWARD-ONLY PIN. The detail columns are forward-only like every other dimension
    here, so a state whose requests were all counted before they existed has no downloads figure at
    all. Rendering 0 would read as 'nobody in New South Wales downloaded anything', which is the exact
    fabrication the state table was built to avoid. FAILS IF a pre-detail state row shows zeroes, or if
    the derived pre-table remainder row claims a measured breakdown."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v4_stats())
            html = (await client.get("/gateway/curator/analytics")).text
            table = html.split("Australia by state", 1)[1]
            nsw = table.split("New South Wales", 1)[1].split("</tr>", 1)[0]
            assert nsw.count("not measured") == 4, f"NSW has no measured detail at all: {nsw}"
            assert ">120<" in nsw, "its request count is real and must still render"
            remainder = table.split("Counted before state data existed", 1)[1].split("</tr>", 1)[0]
            assert remainder.count("not measured") == 4, remainder
    run(_body())


def test_the_state_table_still_reconciles_on_requests_alone(tmp_path):
    """STATE RECONCILIATION SCOPE PIN. The exact-total promise is a property of the REQUEST column and
    must stay one: the detail columns are forward-only and can never add up to the AU country figure,
    so letting them near the promise would break it. The requests column must still total to AU
    exactly. FAILS IF the total row moves off requests, or if the promise silently weakens."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v4_stats())
            html = (await client.get("/gateway/curator/analytics")).text
            table = html.split("Australia by state", 1)[1]
            assert "<b>300</b>" in table, "the requests column must still total to the AU figure"
            assert "adds up to the Australian figure exactly" in table
            assert "forward" in table.lower(), "the detail columns' forward-only scope must be stated"
    run(_body())


def test_no_state_detail_map_leaves_the_table_exactly_as_it_was(tmp_path):
    """STATE DETAIL ABSENCE PIN. A box that folded state requests before the detail map existed must
    still render its table, with every detail cell saying so. FAILS IF the absent map empties the
    table, 500s the screen, or fabricates zeroes across every row."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v3_stats())            # by_state, but no by_state_detail at all
            r = await client.get("/gateway/curator/analytics")
            assert r.status_code == 200
            table = r.text.split("Australia by state", 1)[1]
            assert "New South Wales" in table and ">120<" in table
            assert "not measured" in table
            assert ">0 B<" not in table
    run(_body())


def test_the_by_survey_table_reports_how_many_countries_reached_each_survey(tmp_path):
    """CUSTODIAN PROMISE PIN. "Your survey was downloaded N times from M countries" is the sentence
    this screen exists to let a survey custodian write, and M was nowhere in the pipeline. The by-survey table
    must carry the country COUNT per survey, and only the count: the list itself is a named survey
    beside a named country, which is a small cell in a community this size. FAILS IF the count is
    absent, if it counts 'unknown' as a country, or if the country list is rendered."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v4_stats())
            html = (await client.get("/gateway/curator/analytics")).text
            table = html.split("Downloads by survey", 1)[1].split("<h2>", 1)[0]
            assert ">Countries</th>" in table
            ci_row = table.split("CI Sample Survey", 1)[1].split("</tr>", 1)[0]
            assert ">4<" in ci_row, "five codes minus 'unknown' is four countries"
            for code in ("DE", "NZ", "US"):
                assert f">{code}<" not in ci_row, "the country LIST must not be rendered per survey"
    run(_body())


def test_the_quarterly_table_carries_the_reach_peak_and_the_client_split(tmp_path):
    """QUARTERLY REACH AND CLIENT PIN. The reach proxy lived only on daily rows, which expire after 92
    days, so it could never appear in a quarterly report; and the browser-versus-scripted split is the
    evidence that scripted scientific use exists at all. Both must appear per month. FAILS IF either
    row is missing, or if a month with no measured detail claims a figure for them."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v4_stats())
            html = (await client.get("/gateway/curator/analytics")).text
            table = html.split("Quarterly breakdown", 1)[1].split("Downloads by survey", 1)[0]
            assert "Peak networks in a day" in table and ">23<" in table
            assert "Browser / scripted downloads" in table and "40 / 15" in table

            doc = _v4_stats()
            doc["monthly"] = [_seeded_month()]
            _write_stats(cfg, doc)
            seeded = (await client.get("/gateway/curator/analytics")).text.split(
                "Quarterly breakdown", 1)[1].split("Downloads by survey", 1)[0]
            assert "Peak networks in a day" in seeded and seeded.count("not measured") >= 7
    run(_body())


def test_the_surveys_card_gives_the_downloaded_count_a_denominator(tmp_path):
    """DENOMINATOR PIN. "2 surveys downloaded" reads very differently against 3 served and against 300,
    and the card gave no way to tell. It must render the count against the number the build serves.
    FAILS IF the denominator is missing when the fold recorded one."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v4_stats())
            html = (await client.get("/gateway/curator/analytics")).text
            assert "2 of 40" in html and "served" in html
    run(_body())


def test_the_surveys_card_omits_the_denominator_when_the_fold_recorded_none(tmp_path):
    """DENOMINATOR TOLERANCE PIN. An older stats.json carries no served-survey figure, and a manifest
    the fold could not read yields zero. Neither may render as "2 of 0 served", which would read as an
    impossible ratio. The card must fall back to the bare count. FAILS IF a missing or zero denominator
    is rendered."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            for doc in (_v4_stats(total_served_surveys=0), _v3_stats()):
                _write_stats(cfg, doc)
                html = (await client.get("/gateway/curator/analytics")).text
                assert "of 0 served" not in html
                assert "Surveys downloaded" in html
    run(_body())


def test_the_monthly_csv_carries_the_client_split_and_the_reach_peak():
    """MONTHLY EXPORT PIN. The quarterly figures a report is built from must leave the building in the
    file, not only on the screen: the browser/scripted split and the monthly reach peak both belong in
    the monthly export. FAILS IF either column is missing or carries the wrong month's value."""
    rows = list(csv.DictReader(io.StringIO(curatorpage.analytics_monthly_csv(_v4_stats()))))
    header = list(rows[0].keys())
    assert header[:6] == ["month", "downloads", "download_bytes", "visits", "api_requests",
                          "unattributed"], "the established leading columns must not move"
    for col in ("downloads_browser", "downloads_scripted", "networks_peak"):
        assert col in header, header
    june = {r["month"]: r for r in rows}["2026-06"]
    assert june["downloads_browser"] == "40" and june["downloads_scripted"] == "15"
    assert june["networks_peak"] == "23"


def test_the_survey_csv_carries_the_country_count_per_month_and_survey():
    """PER-SURVEY EXPORT PIN. The custodian sentence is written per survey, so the count of countries
    must ride in the by-survey export beside the downloads and the volume. Only the COUNT: the export
    leaves the building and a named survey beside a named country is a small cell. FAILS IF the column
    is missing, if a country code reaches the file, or if 'unknown' is counted as a country."""
    doc = _v4_stats()
    doc["monthly"][1]["surveys"]["Burra 2017"]["countries"] = ["AU", "NZ", "unknown"]
    body = curatorpage.analytics_survey_csv(doc)
    rows = list(csv.reader(io.StringIO(body)))
    assert rows[0] == ["month", "survey", "downloads", "download_bytes", "countries",
                       "files", "bundles"]
    data = {(r[0], r[1]): r for r in rows[1:]}
    assert data[("2026-06", "Burra 2017")][4] == "2", "'unknown' is not a country"
    assert data[("2026-06", "CI Sample Survey")][4] == "2"
    assert "AU" not in body and "NZ" not in body, "no country CODE may reach the per-survey export"


def test_the_survey_csv_tolerates_rows_written_before_the_country_list():
    """PER-SURVEY EXPORT TOLERANCE PIN. A retained month written before the country list existed must
    export without raising and without dropping the row, and its country cell must be EMPTY rather than
    zero: "downloaded 30 times from 0 countries" is the custodian sentence answered with a measurement
    nobody took, and this file is the one that leaves the building. FAILS IF an older month breaks the
    export, or exports a fabricated zero."""
    doc = _v2_stats()
    rows = list(csv.DictReader(io.StringIO(curatorpage.analytics_survey_csv(doc))))
    assert rows and "countries" in rows[0]
    assert all(r["countries"] == "" for r in rows), rows
    assert all(int(r["downloads"]) > 0 for r in rows), \
        "the downloads those rows DID measure are untouched"


# ==================================================================================================
# The SECOND forward-only seam. `detail_since` is the v1 -> v2 hinge; the dimensions the counting
# work added (client split, within-day dedupe, API geography, per-survey countries, monthly network
# peak) began months after it. A month folded in between carries a real volume and a real format
# split beside NONE of those, so the seeded-month degrade above never fires for it and every one of
# those cells rendered a zero nobody measured. These pins hold the line at that second seam, on the
# screen and in the file that leaves the building.
# ==================================================================================================

def test_a_month_folded_before_the_current_rules_says_not_measured_for_them(tmp_path):
    """SECOND-SEAM PIN. The quarterly rows the counting workflow added must read 'not measured' for a
    month with no day folded under the current rules, exactly as the fully seeded month does for the
    older dimensions. Such a month is NOT seeded: it has a real volume, a real format split and a real
    top survey, so the existing degrade cannot cover it and the rows rendered '0' and '0 / 0' for
    months carrying tens of real downloads. FAILS IF either row fabricates a zero, if the degrade
    swallows the figures the month genuinely measured, or if it fires on a month folded under the
    current rules."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v2_stats())              # months with no detail_days at all
            html = (await client.get("/gateway/curator/analytics")).text
            table = html.split("Quarterly breakdown", 1)[1].split("Downloads by survey", 1)[0]
            peak = table.split("Peak networks in a day", 1)[1].split("</tr>", 1)[0]
            assert peak.count("not measured") == 3 and ">0<" not in peak, peak
            clients = table.split("Browser / scripted downloads", 1)[1].split("</tr>", 1)[0]
            assert clients.count("not measured") == 3 and "0 / 0" not in clients, clients
            assert ">30<" in table and ">55<" in table and ">52<" in table, \
                "the downloads those months DID measure must still render"
            assert "1.0 MB" in table, "so must the volume they measured"

            _write_stats(cfg, _v4_stats())              # the same months, folded under current rules
            now = (await client.get("/gateway/curator/analytics")).text.split(
                "Quarterly breakdown", 1)[1].split("Downloads by survey", 1)[0]
            assert "not measured" not in now, "the degrade must not fire on a measured month"
            assert ">23<" in now and "40 / 15" in now, "its real peak and split render"
    run(_body())


def test_the_screen_does_not_contradict_itself_about_the_peak(tmp_path):
    """SECOND-SEAM CONTRADICTION PIN. The reach note under the sparkline reads the surviving daily
    rows, which are younger than the monthly rollups, so it reports a real peak from the same page on
    which the month rows reported a peak of zero for months carrying real downloads. One page, two
    answers. FAILS IF a month row claims a numeric peak the fold never recorded for it while the note
    beside it reports one it did."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v2_stats())
            html = (await client.get("/gateway/curator/analytics")).text
            assert "peak over the window: <b>19</b>" in html, "the daily rows do carry a real peak"
            peak_row = html.split("Peak networks in a day", 1)[1].split("</tr>", 1)[0]
            assert "0" not in peak_row.replace("class=\"num\"", ""), \
                f"no month may answer the same question with a zero it never measured: {peak_row}"
    run(_body())


def test_the_monthly_csv_leaves_unmeasured_coverage_cells_empty():
    """SECOND-SEAM EXPORT PIN. geo_days was the column added to make partial geography visible, and on
    every month folded before it existed it exported 0 beside a real au_requests and real state_*
    columns: the docstring tells the reader to compare geo_days with active_days, and a reader doing
    that concludes the month contributed no country at all while the same row reports Australian
    requests split across named states. The client split and the network peak are the same fabrication
    in the same file. Those cells must be EMPTY, and `detail_days` must say why. FAILS IF any of them
    exports a zero for a month that measured nothing, or if a measured month exports a blank."""
    doc = _v4_stats()
    doc["monthly"][0].pop("detail_days")                 # May: folded before the current rules
    doc["monthly"][0].pop("geo_days")
    rows = {r["month"]: r for r in csv.DictReader(io.StringIO(
        curatorpage.analytics_monthly_csv(doc)))}
    may = rows["2026-05"]
    assert "detail_days" in may, "the coverage counter must ride in the export"
    assert may["detail_days"] == "0"
    for col in ("geo_days", "downloads_browser", "downloads_scripted", "networks_peak"):
        assert may[col] == "", f"{col} must be empty, not a fabricated zero: {may}"
    assert may["active_days"] == "20" and may["downloads"] == "30" and may["au_requests"] == "60", \
        "everything that month DID measure is untouched"
    june = rows["2026-06"]
    assert june["detail_days"] == "29"
    assert june["networks_peak"] == "23" and june["downloads_browser"] == "40", \
        "a month folded under the current rules exports its real figures"


def test_the_by_survey_table_says_not_measured_when_no_country_was_recorded(tmp_path):
    """CUSTODIAN SENTENCE PIN. The Countries column answers "downloaded N times from M countries", and
    the per-survey country list is forward-only like everything else here. A survey whose downloads
    were all counted before the list existed carries no codes, and a 0 there answers that sentence
    with a measurement nobody took. It must read 'not measured', and the export must leave the cell
    empty. FAILS IF the zero returns, or if it fires on a survey whose codes ARE recorded, which would
    turn a real 'nothing outside the unknowns' into a claim of ignorance."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v2_stats())               # by_survey rows with no country list
            table = (await client.get("/gateway/curator/analytics")).text.split(
                "Downloads by survey", 1)[1].split("<h2>", 1)[0]
            ci = table.split("CI Sample Survey", 1)[1].split("</tr>", 1)[0]
            assert _country_cell(ci) == "not measured" and ">0<" not in ci, ci
            assert ">120<" in ci, "the downloads that survey DID measure still render"

            doc = _v4_stats()                            # a survey seen ONLY from unresolved addresses
            doc["downloads"]["by_survey"]["Burra 2017"]["countries"] = ["unknown"]
            _write_stats(cfg, doc)
            measured = (await client.get("/gateway/curator/analytics")).text.split(
                "Downloads by survey", 1)[1].split("<h2>", 1)[0]
            burra = measured.split("Burra 2017", 1)[1].split("</tr>", 1)[0]
            assert _country_cell(burra) == "0", \
                f"measured-and-nothing-resolved is a real zero, not an unmeasured cell: {burra}"
    run(_body())


def test_the_survey_csv_blanks_the_country_cell_it_never_measured():
    """CUSTODIAN SENTENCE EXPORT PIN. The same distinction must survive into the file: a (month,
    survey) with no recorded codes exports an empty cell, one whose codes resolved to nothing but
    'unknown' exports 0. FAILS IF the two collapse into the same cell."""
    doc = _v4_stats()
    doc["monthly"][0]["surveys"]["CI Sample Survey"].pop("countries")
    doc["monthly"][1]["surveys"]["Burra 2017"]["countries"] = ["unknown"]
    rows = {(r[0], r[1]): r for r in list(csv.reader(io.StringIO(
        curatorpage.analytics_survey_csv(doc))))[1:]}
    assert rows[("2026-05", "CI Sample Survey")][4] == "", "no codes recorded is not zero countries"
    assert rows[("2026-06", "Burra 2017")][4] == "0", "codes recorded, none of them a country"


def test_the_country_table_says_api_requests_joined_it_later(tmp_path):
    """GEO SCOPE SEAM PIN. The caption says the map counts downloads plus visits plus API requests,
    and it does, NOW. The map is cumulative, and API requests were for a time the one counted class with no
    geography at all, so on a box with days folded before that change the caption describes only the
    later part of its own map. The table must say so where it is true, and must not say it where it is
    not. FAILS IF the seam goes unstated, or if a box with no such history carries the note anyway."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v3_stats())               # months folded before API geography
            html = (await client.get("/gateway/curator/analytics")).text
            country = html.split("<h2>By country</h2>", 1)[1]
            assert "API requests count toward a country only from" in country, country[:600]
            assert "Requests (downloads + visits + API)" in country, "the caption itself still stands"

            _write_stats(cfg, _v4_stats())               # every month folded under the current rules
            clean = (await client.get("/gateway/curator/analytics")).text.split(
                "<h2>By country</h2>", 1)[1]
            assert "API requests count toward a country only from" not in clean, \
                "a box with no such history must not carry a caveat about one"
    run(_body())


def test_the_surveys_card_drops_a_ratio_larger_than_its_denominator(tmp_path):
    """DENOMINATOR SANITY PIN. The numerator counts every survey ever downloaded and nothing prunes
    it; the denominator is restamped from the manifest being served right now. Withdraw or rename one
    survey that has historical downloads and the honest arithmetic reads "3 of 2 served", which is the
    absurd ratio the denominator was introduced to avoid. The card must fall back to the bare count.
    FAILS IF an impossible ratio renders."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v4_stats(total_served_surveys=1))   # 2 downloaded, 1 still served
            html = (await client.get("/gateway/curator/analytics")).text
            assert "2 of 1" not in html, "a numerator above its denominator is not a ratio"
            assert "Surveys downloaded" in html and "of those served" not in html
            _write_stats(cfg, _v4_stats(total_served_surveys=2))   # the boundary case still renders
            assert "2 of 2" in (await client.get("/gateway/curator/analytics")).text
    run(_body())


def _aged_out_seam_stats(**over) -> dict:
    """A stats.json whose second-seam months have AGED OUT of the three the quarterly table shows.
    Six retained months: the first three carry real downloads with no day folded under the current
    rules, the last three are fully current. Every disclosure that fires off the WHOLE retained set
    therefore fires, while the quarterly table (which only ever looks at its three columns) has
    nothing to say."""
    doc = _v4_stats()
    old = []
    for month, downloads in (("2026-02", 12), ("2026-03", 18), ("2026-04", 21)):
        old.append({"month": month, "downloads": downloads, "visits": downloads * 3,
                    "download_bytes": 1_048_576, "unattributed": 0, "api_requests": 5,
                    "days": 28, "seeded_days": 0, "geo_days": 0, "detail_days": 0,
                    "networks_peak": 0, "formats": {"edi": downloads}, "kinds": {"file": downloads},
                    "surveys": {"CI Sample Survey": {"downloads": downloads, "bytes": 1_048_576}},
                    "countries": {"AU": downloads}})
    doc["monthly"] = old + doc["monthly"]
    doc.update(over)
    return doc


def test_no_disclosure_points_at_a_note_that_is_not_on_the_page(tmp_path):
    """DANGLING-CITATION PIN. Two disclosures told the reader that "the note under the
    quarterly table names the months", but that note is built from the THREE months the quarterly
    table shows while the disclosures citing it fire off a scan of every retained month, which the
    aggregator never prunes. Once a second-seam month ages out of the three-month window the citation
    points at a note the page does not render, and the reader is sent to nothing.

    FAILS IF any text on the page cites the quarterly note while that note is absent. The fixture is
    exactly that shape and the assertions below prove it is not vacuous: the country-table seam note
    (whole-set trigger) IS rendered and the quarterly second-seam note (three-column trigger) is
    NOT."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _aged_out_seam_stats())
            html = (await client.get("/gateway/curator/analytics")).text
            # The fixture really does drive the two triggers apart.
            assert "API requests count toward a country only from" in html, \
                "the whole-set trigger must fire, or this pin proves nothing"
            assert "some days were folded before the current counting rules existed" not in html, \
                "the three-column note must be absent, or this pin proves nothing"
            assert "note under the quarterly table" not in html, \
                "no disclosure may send the reader to a note the page does not render"
            # And what they cite instead must be a column every retained month actually carries.
            assert html.count("detail_days") >= 2, \
                "both disclosures must point at the export column that covers every retained month"
            csv_text = (await client.get("/gateway/curator/analytics.csv")).text
            header = next(csv.reader(io.StringIO(csv_text)))
            assert "detail_days" in header, "the cited column must exist in the export"
            rows = list(csv.DictReader(io.StringIO(csv_text)))
            assert len(rows) == 6 and rows[0]["month"] == "2026-02", \
                "the export really does reach past the three months the screen shows"
    run(_body())


def test_the_second_seam_note_states_the_bias_in_both_directions(tmp_path):
    """TWO-SIDED-BIAS PIN. The second-seam note named ONE of the three counting-rule changes that
    separate an earlier month from a current one, and it named the only one that makes the earlier
    figure too BIG (every request counted, so a repeated or resumed transfer counted twice). The same
    days also discarded scripted clients as robots and admitted status 200 alone, and both of those
    make the earlier figure too SMALL. A funding-report reader was told the older months are inflated
    when the bias is two-sided and its net is not recoverable.

    FAILS IF the note states only the over-count direction, or omits that the net effect is
    unknown."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v2_stats())        # three visible months, none folded under the rules
            html = (await client.get("/gateway/curator/analytics")).text
            note = html.split("some days were folded before the current counting rules existed", 1)[1]
            note = note.split("</p>", 1)[0]
            assert "counted twice" in note, "the over-count direction must still be stated"
            assert "scripted" in note and "ranged" in note, \
                f"the two under-count directions must be stated as well: {note}"
            assert "both directions" in note, f"the note must say the bias is two-sided: {note}"
            assert "not recoverable" in note, \
                f"and that the net of the three is not recoverable: {note}"
    run(_body())


def test_the_screen_reports_downloads_by_collection(tmp_path):
    """COLLECTION ROLLUP RENDER PIN. The fold credits a download to the programme its survey belongs
    to (AusLAMP and its siblings, from the served mtcat.json), so "how much did this programme move"
    can be answered without joining two documents by hand. The screen must show it, with its volume,
    and must say that the rollup is forward-only: it is a THIRD starting point, younger than both
    seams the rest of the screen marks, and neither seam marker covers it.

    FAILS IF the rollup is folded but never rendered, if a box that folded none renders an empty
    heading or a zero, or if the line claims coverage it does not have."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v4_stats(by_collection={
                "auslamp": {"downloads": 96, "bytes": 3_145_728},
                "hydro": {"downloads": 12, "bytes": 1024}}))
            html = (await client.get("/gateway/curator/analytics")).text
            line = html.split("Downloads by collection", 1)[1].split("</p>", 1)[0]
            assert "auslamp" in line and ">96<" in line and "3.0 MB" in line, line
            assert line.index("auslamp") < line.index("hydro"), "biggest collection first"
            assert "sum of its member surveys" in line, "the arithmetic promise must be stated"
            assert "counted from the fold that added the rollup onward" in line, \
                f"the third forward-only seam must be disclosed on its own line: {line}"

            # A box whose fold produced no collection dimension shows nothing at all here.
            _write_stats(cfg, _v4_stats())
            bare = (await client.get("/gateway/curator/analytics")).text
            assert "Downloads by collection" not in bare, \
                "no served mtcat.json means no line, not an empty one and not a zero"
    run(_body())


# ==================================================================================================
# COUNTRY-CLASS DETAIL and the PER-SURVEY KIND SPLIT.
#
# The state table already answers "what did this place DO"; the country table above it answered only
# "how many requests". These pins hold the same three properties there that they hold beneath the AU
# row: the detail columns render, a country counted before they existed says so rather than showing a
# zero, and the REQUEST column keeps its combined semantics untouched (the AU reconciliation is built
# on it). The per-survey rows gain the file-versus-bundle split the global map already carried.
# ==================================================================================================
def _v5_stats(**over) -> dict:
    """A stats.json carrying the per-country DETAIL map and the per-survey kind split.

    The country detail deliberately covers FEWER countries than the country map: US and `unknown` were
    counted before it existed, so the screen must say 'not measured' for them rather than render four
    zeroes. The same asymmetry runs through the surveys: CI Sample Survey carries a split that adds up
    to its download count exactly, and Burra 2017 carries none at all."""
    doc = _v4_stats()
    doc["by_country_detail"] = {
        "AU": {"downloads": 90, "visits": 200, "api": 10, "bytes": 3_145_728},
        "NZ": {"downloads": 12, "visits": 26, "api": 2, "bytes": 1_048_576},
    }
    doc["downloads"]["by_survey"]["CI Sample Survey"].update({"files": 95, "bundles": 25})
    doc["monthly"][2]["by_country_detail"] = {
        "AU": {"downloads": 30, "visits": 160, "api": 10, "bytes": 2_097_152},
        "NZ": {"downloads": 4, "visits": 8, "api": 0, "bytes": 4096},
    }
    doc["monthly"][2]["surveys"]["CI Sample Survey"].update({"files": 40, "bundles": 12})
    doc.update(over)
    return doc


def test_the_country_table_gains_downloads_visits_api_and_volume_columns(tmp_path):
    """COUNTRY DETAIL RENDER PIN. "Requests from New Zealand" is not the custodian conversation; "how
    much was downloaded, and how many bytes" is. The country table must carry Downloads, Visits, API
    and Volume beside the request count, exactly as the state table beneath it does. FAILS IF a column
    is missing or a figure lands in the wrong one."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v5_stats())
            html = (await client.get("/gateway/curator/analytics")).text
            table = html.split("<h2>By country</h2>", 1)[1].split("<h2>Australia by state", 1)[0]
            for head in ("Downloads", "Visits", "API", "Volume"):
                assert f">{head}</th>" in table, f"the country table must carry a {head} column"
            au = table.split(">AU<", 1)[1].split("</tr>", 1)[0]
            assert ">300<" in au, "its combined request count must still render"
            assert ">90<" in au and ">200<" in au and ">10<" in au and "3.0 MB" in au, au
    run(_body())


def test_countries_counted_before_the_detail_existed_say_not_measured(tmp_path):
    """COUNTRY DETAIL FORWARD-ONLY PIN. The detail columns are forward-only like every other dimension
    on this screen, so a country whose requests were all counted before they existed has no download
    figure at all. Rendering 0 would read as 'nobody in the United States downloaded anything', the
    exact fabrication the state table was built to refuse. FAILS IF a pre-detail country row shows
    zeroes instead of saying it was not measured."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v5_stats())
            html = (await client.get("/gateway/curator/analytics")).text
            table = html.split("<h2>By country</h2>", 1)[1].split("<h2>Australia by state", 1)[0]
            us = table.split(">US<", 1)[1].split("</tr>", 1)[0]
            assert us.count("not measured") == 4, f"US has no measured detail at all: {us}"
            assert ">120<" in us, "its request count is real and must still render"
            unknown = table.split(">unknown<", 1)[1].split("</tr>", 1)[0]
            assert unknown.count("not measured") == 4, unknown
            assert ">0 B<" not in table, "an unmeasured volume is never a measured zero"
    run(_body())


def test_the_country_table_says_the_new_columns_break_down_the_same_requests(tmp_path):
    """COUNTRY DETAIL SCOPE PIN. The Requests column keeps its COMBINED semantics (downloads + visits
    + API), because the AU state table beneath reconciles against its AU row and that promise is
    load-bearing. The caption must therefore say the new columns are a breakdown of those same
    requests and not an additional measurement, and must not weaken the request column's scope. FAILS
    IF the scope caption changes, or if the breakdown is presented as a second measurement."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v5_stats())
            html = (await client.get("/gateway/curator/analytics")).text
            table = html.split("<h2>By country</h2>", 1)[1].split("<h2>Australia by state", 1)[0]
            assert f">{curatorpage._REQUEST_SCOPE}</th>" in table, \
                "the request column keeps the combined scope the AU reconciliation depends on"
            assert "breakdown of the same requests" in table, table[:600]
            assert "not an additional measurement" in table, table[:600]
            # And the state table beneath it still reconciles on requests alone: untouched.
            state = html.split("Australia by state", 1)[1]
            assert "<b>300</b>" in state and "adds up to the Australian figure exactly" in state
    run(_body())


def test_a_box_with_no_country_detail_renders_the_country_table_exactly_as_it_was(tmp_path):
    """COUNTRY DETAIL ABSENCE PIN. A box that folded country requests before the detail map existed
    must still render its table, with every detail cell saying so. FAILS IF the absent map empties the
    table, 500s the screen, or fabricates zeroes across every row."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v4_stats())          # countries, but no by_country_detail at all
            r = await client.get("/gateway/curator/analytics")
            assert r.status_code == 200
            table = r.text.split("<h2>By country</h2>", 1)[1].split("<h2>Australia by state", 1)[0]
            assert ">AU<" in table and ">300<" in table
            assert "not measured" in table and ">0 B<" not in table
    run(_body())


def test_the_monthly_country_csv_has_one_row_per_month_and_country(tmp_path):
    """COUNTRY EXPORT PIN. The funding-report affordance for the country breakdown: every retained
    month, every country it saw, as one row carrying the combined request count and the four-way split
    beside it. FAILS IF the export is not served, is not an attachment, or loses a month or a
    country."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v5_stats())
            r = await client.get("/gateway/curator/analytics-countries.csv")
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/csv")
            assert "attachment" in r.headers["content-disposition"]
            rows = list(csv.DictReader(io.StringIO(r.text)))
            assert [f for f in rows[0]] == ["month", "country", "requests", "downloads", "visits",
                                            "api", "download_bytes", "geo_days"], rows[0]
            assert {r["month"] for r in rows} == {"2026-05", "2026-06", "2026-07"}
            jul = {r["country"]: r for r in rows if r["month"] == "2026-07"}
            assert jul["AU"]["requests"] == "200" and jul["NZ"]["requests"] == "12"
            assert jul["AU"]["downloads"] == "30" and jul["AU"]["visits"] == "160"
            assert jul["AU"]["api"] == "10" and jul["AU"]["download_bytes"] == "2097152"
            assert jul["AU"]["geo_days"] == "4", "the geo-coverage marker rides every row"
    run(_body())


def test_the_country_csv_leaves_an_unmeasured_cell_empty_rather_than_zero(tmp_path):
    """COUNTRY EXPORT HONESTY PIN. The detail is forward-only, so a (month, country) the fold counted
    before it existed has no download figure. This file is what a funding report is built from, and a
    zero there outlives the screen that says 'not measured' -- every spreadsheet reads an
    empty cell as missing and a zero as measured. FAILS IF an unmeasured cell exports as 0, or if the
    combined request count is blanked along with it."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v5_stats())
            rows = list(csv.DictReader(io.StringIO(
                (await client.get("/gateway/curator/analytics-countries.csv")).text)))
            may = {r["country"]: r for r in rows if r["month"] == "2026-05"}
            assert may["AU"]["requests"] == "60", "the combined count is real and always exports"
            for col in ("downloads", "visits", "api", "download_bytes"):
                assert may["AU"][col] == "", f"{col} was never measured for May: {may['AU']}"
    run(_body())


def test_the_country_csv_is_session_gated_and_empty_safe(tmp_path):
    """COUNTRY EXPORT GATE PIN. The export carries the same data the session-gated screen does, so it
    takes the same gate, and a missing stats.json yields the header row alone. FAILS IF an anonymous
    caller gets a body, or if an absent aggregate 500s instead of exporting an honest empty file."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            anon = await client.get("/gateway/curator/analytics-countries.csv")
            assert anon.status_code in (302, 303, 401, 403), anon.status_code
            await curator_login(client)
            r = await client.get("/gateway/curator/analytics-countries.csv")
            assert r.status_code == 200
            assert r.text.strip().splitlines() == ["month,country,requests,downloads,visits,api,"
                                                   "download_bytes,geo_days"]
    run(_body())


def test_the_export_links_include_the_monthly_country_csv(tmp_path):
    """EXPORT LINK PIN. An export nothing links to is an export nobody finds. FAILS IF the country CSV
    is served but absent from the 'Download report data' row."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v5_stats())
            html = (await client.get("/gateway/curator/analytics")).text
            assert 'href="/gateway/curator/analytics-countries.csv"' in html
            assert 'href="/gateway/curator/analytics.csv"' in html
            assert 'href="/gateway/curator/analytics-surveys.csv"' in html
    run(_body())


def test_the_by_survey_table_splits_each_survey_into_files_and_bundles(tmp_path):
    """PER-SURVEY KIND RENDER PIN. "Was my survey pulled station by station or taken whole" is a
    question about ONE survey, and the split existed only as a global counter. The Downloads-by-survey
    table must carry a Files / bundles column. FAILS IF the column is missing or the two numbers are
    swapped."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v5_stats())
            html = (await client.get("/gateway/curator/analytics")).text
            table = html.split("<h2>Downloads by survey</h2>", 1)[1]
            assert ">Files / bundles</th>" in table, "the split column must be in the header"
            row = table.split("CI Sample Survey", 1)[1].split("</tr>", 1)[0]
            assert "95 / 25" in row, f"files first, bundles second: {row}"
    run(_body())


def test_a_survey_row_with_no_kind_split_says_not_measured(tmp_path):
    """PER-SURVEY KIND FORWARD-ONLY PIN. The split is forward-only, so a survey whose downloads were
    all counted before it existed carries files and bundles both at zero beside a real download count.
    Rendering '0 / 0' would state that thirteen downloads were neither files nor bundles, which is not
    a measurement anybody took. FAILS IF such a row renders zeroes, or if the note does not say the
    split can cover fewer downloads than the count beside it."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v5_stats())
            html = (await client.get("/gateway/curator/analytics")).text
            table = html.split("<h2>Downloads by survey</h2>", 1)[1]
            burra = table.split("Burra 2017", 1)[1].split("</tr>", 1)[0]
            assert "not measured" in burra, f"an unmeasured split is not a zero: {burra}"
            assert "0 / 0" not in burra
            assert ">13<" in burra, "its download count is real and must still render"
            assert "fewer downloads than the count beside it" in table, \
                "a partially covered row must be disclosed, not left to look complete"
    run(_body())


def test_the_survey_csv_carries_the_files_and_bundles_split(tmp_path):
    """PER-SURVEY KIND EXPORT PIN. The split must reach the file a funding report is built from, and an
    unmeasured split must export EMPTY rather than as two zeroes, exactly as the country count beside
    it already does. FAILS IF the columns are absent, or if a row that never measured the split
    exports 0."""
    doc = _v5_stats()
    doc["monthly"][1]["surveys"]["Burra 2017"].pop("files", None)
    doc["monthly"][1]["surveys"]["Burra 2017"].pop("bundles", None)
    rows = list(csv.DictReader(io.StringIO(curatorpage.analytics_survey_csv(doc))))
    assert [f for f in rows[0]] == ["month", "survey", "downloads", "download_bytes", "countries",
                                    "files", "bundles"], rows[0]
    jul = [r for r in rows if r["month"] == "2026-07" and r["survey"] == "CI Sample Survey"][0]
    assert jul["files"] == "40" and jul["bundles"] == "12"
    jun = [r for r in rows if r["month"] == "2026-06" and r["survey"] == "Burra 2017"][0]
    assert jun["files"] == "" and jun["bundles"] == "", f"an unmeasured split exports empty: {jun}"
    assert jun["downloads"] == "15", "its real download count still exports"


# ==================================================================================================
# The BULK-EXPORT LABEL on the screen.
#
# The portal marks its own multi-file export fetches with a query flag so the fold can tell a
# drag-selected bulk export from a single station download. That is the FIRST thing this pipeline puts
# INTO the log rather than reading out of it, so the screen's own claim about itself has to change:
# "nothing new is collected" was true and now needs one honest exception. These pins hold the figure,
# the claim, and the seam date, and they hold the citation-pack sentence to what the portal actually
# does rather than to what a bulk export might be assumed to imply.
# ==================================================================================================
def _v6_stats(**over) -> dict:
    """A stats.json carrying the bulk/single download split, the export-event proxy and the recorded
    seam date the screen is now able to name."""
    doc = _v5_stats()
    doc["select_since"] = "2026-08-01"
    doc["totals"]["downloads_by_select"] = {"single": 104, "bulk": 33}
    doc["totals"]["bulk_export_events"] = 7
    doc["monthly"][2]["downloads_by_select"] = {"single": 19, "bulk": 33}
    doc["monthly"][2]["bulk_export_events"] = 7
    doc.update(over)
    return doc


def test_the_screen_reports_bulk_map_exports_as_events_and_files(tmp_path):
    """BULK LINE PIN. One export fetches many files, so a file count alone would read as far more
    exports than happened and a bare event count would hide the volume. The line must carry BOTH, under
    the station/bundle split it extends. FAILS IF either figure is missing, if files and events are
    swapped, or if the line appears on a box whose fold never took the split."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v6_stats())
            html = (await client.get("/gateway/curator/analytics")).text
            line = html.split("Bulk map exports", 1)[1].split("</p>", 1)[0]
            assert "<b>7</b>" in line and "event" in line, f"the export-event proxy must render: {line}"
            assert "<b>33</b>" in line and "file" in line, f"the file count must render: {line}"
            assert html.index("whole-survey bundles") < html.index("Bulk map exports"), \
                "the line sits under the split it extends"

            _write_stats(cfg, _v5_stats())      # a fold that never took the split
            assert "Bulk map exports" not in (await client.get(
                "/gateway/curator/analytics")).text, "no split means no line, not a zero"
    run(_body())


def test_the_bulk_line_does_not_claim_the_export_produces_a_citation_pack(tmp_path):
    """CITATION-PACK HONESTY PIN. A citation pack IS generated in the browser and IS uncountable here,
    and the line must say so. What it must NOT say is that the bulk export produces one: in
    portal/src/exports.js the export flow (#dlZip) writes EDIs, a per-survey LICENSE.txt and the
    not-included pointer file, and nothing else; the citation pack is #dlCite, a separate button the
    reader clicks separately. A line asserting the causal link would put a claim on a funding screen
    that the shipped code does not make true.

    FAILS IF the line implies the export generates a pack, or if it implies packs are counted."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v6_stats())
            line = (await client.get("/gateway/curator/analytics")).text.split(
                "Bulk map exports", 1)[1].split("</p>", 1)[0]
            assert "citation pack" in line, "the pack is worth naming; it is simply not caused by this"
            assert "separate" in line, f"it must read as its own action, not a consequence: {line}"
            assert "not counted" in line or "counts none" in line, \
                f"a client-generated pack is uncountable and the line must say so: {line}"
            for overclaim in ("each export also generates", "every export generates",
                              "generates a citation pack"):
                assert overclaim not in line, f"the line must not assert the causal link: {line}"
    run(_body())


def test_the_screen_states_the_one_thing_the_portal_adds_to_the_log(tmp_path):
    """DISCLOSURE PIN. The preamble states that nothing here is a beacon and nothing new is
    collected. The bulk label is the first thing the portal deliberately puts INTO the log, so
    the second half of that sentence is not true as written and must be restated rather than left
    standing. The restatement has to be specific: WHAT is added (a query flag), to WHAT (fetches that
    already happen), and what is NOT added (a request, an identity).

    FAILS IF the screen still claims nothing new is collected, if the beacon claim is dropped along
    with it (it is still true), or if the restatement is vague about what the flag is."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v6_stats())
            html = (await client.get("/gateway/curator/analytics")).text
            assert "nothing new is collected" not in html, \
                "the claim is no longer true as written and must not survive verbatim"
            assert "Nothing here is a beacon" in html, "that half is still true and must stay"
            assert "sel=bulk" in html, "the amendment must name the flag it is disclosing"
            assert "no new request" in html and "no identity" in html, \
                "and must say what it is NOT: a request, or anything about who is asking"
    run(_body())


def test_the_screen_names_the_day_the_selection_split_begins(tmp_path):
    """THIRD-SEAM PIN. This screen declines to date the second seam because that fold date is recorded
    nowhere. This one IS recorded, by the fold, in `select_since`, so declining to name it here would
    be a false modesty that leaves the reader unable to place the figure. The seam line must name the
    date; a box with no stamp must still say nothing rather than guess.

    FAILS IF the date is not named, or if a box that never recorded one has a date invented for it."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v6_stats())
            html = (await client.get("/gateway/curator/analytics")).text
            assert "2026-08-01" in html, "the recorded seam date must be named on the screen"
            seam = html.split("2026-08-01", 1)[0].rsplit("<p", 1)[1]
            assert "selection" in seam or "bulk" in seam, \
                f"the date must sit on the sentence about the split, not float free: {seam}"

            _write_stats(cfg, _v6_stats(select_since=None))
            bare = (await client.get("/gateway/curator/analytics")).text
            assert "2026-08-01" not in bare, "no stamp, no date: nothing is guessed"
            assert "Bulk map exports" in bare, "the figures themselves still render"
    run(_body())


# --------------------------------------------------------------------------------------------------
# TIME-SERIES HAND-OFFS. The front door 302s a reader into the NCI
# THREDDS archive and AusMT hosts none of those bytes, so the figure is REQUESTS and the screen must
# never let it read as completed transfers. The class is younger than every seam this screen already
# marks, so a month that predates it carries no hand-off key at all and must read "not measured".
# --------------------------------------------------------------------------------------------------
def _v7_stats(**over) -> dict:
    """A stats.json carrying the hand-off family. The LAST month has it; the two before it do not,
    which is the shape a box folding across the seam actually writes and the reason the cell degrade
    exists at all."""
    doc = _v6_stats()
    doc["handoffs"] = {
        "requests": 48, "bytes": 21_474_836_480, "unattributed": 2,
        "by_survey": {"auslamp-musgraves-apy-2016": {"requests": 30, "bytes": 12_884_901_888},
                      "vulcan-2022": {"requests": 16, "bytes": 8_589_934_592}},
        "by_level": {"raw_packed": {"requests": 33, "bytes": 19_327_352_832},
                     "level1_mth5": {"requests": 13, "bytes": 2_147_483_648}},
        "by_destination": {"thredds.nci.org.au": {"requests": 46, "bytes": 21_474_836_480}},
        "countries": {"AU": 40, "NZ": 6, "unknown": 2},
    }
    doc["monthly"][2]["handoffs"] = {
        "requests": 21, "bytes": 10_737_418_240, "unattributed": 0,
        "by_survey": {"vulcan-2022": {"requests": 21, "bytes": 10_737_418_240}},
        "by_level": {"raw_packed": {"requests": 21, "bytes": 10_737_418_240}},
        "by_destination": {"thredds.nci.org.au": {"requests": 21, "bytes": 10_737_418_240}},
        "countries": {"AU": 21},
    }
    doc.update(over)
    return doc


def test_the_screen_reports_time_series_hand_offs_as_requests_not_transfers(tmp_path):
    """HAND-OFF LINE PIN. The line must carry the request count and the volume handed off, and it must
    say IN WORDS that these are requests and not completed transfers: AusMT answers a 302 and never
    learns whether a byte moved, so any wording that implies a download would be a claim the pipeline
    cannot support. It must also name the archive it hands off to.

    FAILS IF the line is missing, if it claims transfers or downloads, or if it renders on a box whose
    fold never took the class (absent, never a zero)."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v7_stats())
            html = (await client.get("/gateway/curator/analytics")).text
            assert "time-series hand-offs to NCI THREDDS (requests, not completed transfers)" in html
            line = html.split("time-series hand-offs to NCI THREDDS", 1)[1].split("</p>", 1)[0]
            assert "<b>48</b>" in line, f"the request count must render: {line}"
            assert "20.0 GB" in line, f"the volume handed off must render: {line}"
            assert "thredds.nci.org.au" in line, f"the destination must be named: {line}"
            assert "AusMT" in line and "host" in line, \
                f"the line must say the bytes are not AusMT's: {line}"

            _write_stats(cfg, _v6_stats())      # a fold that never saw a hand-off
            assert "hand-off" not in (await client.get(
                "/gateway/curator/analytics")).text.lower(), "no hand-offs means no line, not a zero"
    run(_body())


def test_a_month_folded_before_hand_offs_existed_says_not_measured(tmp_path):
    """SEAM PIN. The hand-off class is younger than every dimension this screen already marks, so a
    month folded before it carries no such key. Its cell must read 'not measured', never 0: a zero
    would state that nobody was handed off in a month when nothing could hand anyone off.

    FAILS IF a month with no hand-off key renders a zero, or if the month that HAS one is degraded."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_stats(cfg, _v7_stats())
            html = (await client.get("/gateway/curator/analytics")).text
            row = html.split("Time-series hand-offs", 1)[1].split("</tr>", 1)[0]
            cells = _cells(row)
            assert len(cells) == 3, f"one cell per month shown: {cells}"
            assert cells[-1] == "21", f"the month that measured hand-offs renders its figure: {cells}"
            assert cells.count(curatorpage._NOT_MEASURED) == 2, \
                f"the two months that predate the class must read not measured: {cells}"
    run(_body())


# --------------------------------------------------------------------------------------------------
# REQUEST LABELS. From `labels_since` the fold stores, per month, joint client|nettype counts, an
# operator line, a declared-crawler tally and four day counters. The screen derives people, automated
# and unclassified from those joint counts with a pure audience rule, shows the operator and crawler
# lines apart from every figure, and says where an input was missing. A month without `label_days`
# was never labelled and reads "not measured" on every label row, never zero.
# --------------------------------------------------------------------------------------------------
def _label_stats(**over) -> dict:
    """The hand-off fixture with labels from its June month on. June is labelled on every active day
    with a hosting-only table; July is labelled on all four of its days but had the network-type table
    on three of them (one built with every source) and the operator list on two. May predates the
    labels and carries none of their keys."""
    doc = _v7_stats()
    doc["labels_since"] = "2026-06-01"
    june, july = doc["monthly"][1], doc["monthly"][2]
    june.update({
        "labels": {"downloads": {"tool|unknown": 40, "unknown|unknown": 15},
                   "visits": {"portal_session|unknown": 210},
                   "api": {"tool|unknown": 27}, "handoffs": {}},
        "operator": {"downloads": 0, "visits": 3, "api": 0, "handoffs": 0, "download_bytes": 0},
        "crawler_excluded": {"downloads": 1, "visits": 0, "api": 0, "handoffs": 0},
        "label_days": 29, "nettype_days": 29, "nettype_full_days": 0, "operator_list_days": 29})
    july.update({
        "labels": {"downloads": {"tool|hosting": 20, "portal_session|access_provider": 15,
                                 "landing_page|other": 5, "unknown|hosting": 4,
                                 "unknown|education_research": 6, "unknown|unknown": 2},
                   "visits": {"portal_session|hosting": 200, "unknown|hosting": 2,
                              "unknown|unknown": 10},
                   "api": {"tool|access_provider": 20, "unknown|other": 2},
                   "handoffs": {"portal_session|education_research": 12, "tool|hosting": 6,
                                "unknown|unknown": 3}},
        "operator": {"downloads": 14, "visits": 51, "api": 6, "handoffs": 4,
                     "download_bytes": 1_048_576},
        "crawler_excluded": {"downloads": 2000, "visits": 300, "api": 10, "handoffs": 0},
        "label_days": 4, "nettype_days": 3, "nettype_full_days": 1, "operator_list_days": 2})
    doc["totals"]["operator"] = {"downloads": 14, "visits": 54, "api": 6, "handoffs": 4,
                                 "download_bytes": 1_048_576}
    doc["totals"]["crawler_excluded"] = {"downloads": 2001, "visits": 300, "api": 10, "handoffs": 0}
    doc.update(over)
    return doc


def _text(fragment: str) -> str:
    """The reader-visible text of an HTML fragment: tags dropped, entities decoded, runs of white
    space collapsed, so a pin reads the sentence a curator reads."""
    import html as _html
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", fragment))).replace(" .", ".")


def _quarterly(html: str) -> str:
    return html.split("Quarterly breakdown", 1)[1].split("Downloads by survey", 1)[0]


def _row_cells(table: str, label: str) -> list[str]:
    return _cells(table.split(label, 1)[1].split("</tr>", 1)[0])


async def _analytics(tmp_path, doc) -> str:
    tmp_path.mkdir(parents=True, exist_ok=True)
    async with app_client(tmp_path) as (client, _app, _gw, cfg):
        await curator_login(client)
        _write_stats(cfg, doc)
        r = await client.get("/gateway/curator/analytics")
        assert r.status_code == 200
        return r.text


def test_headline_not_measured_before_labels(tmp_path):
    """HEADLINE SEAM PIN. A box whose fold has never labelled a day must say the question is not
    measured, before the cards, rather than leave the cards to answer it. FAILS IF the line is missing,
    or sits below the cards, or if any people or automated figure is claimed."""
    html = run(_analytics(tmp_path, _v7_stats()))
    text = _text(html)
    line = "Who made these requests: not measured. Request labels have not started."
    assert line in text, text[:2000]
    assert html.index("Who made these requests") < html.index('class="cards"')
    headline = html.split("Who made these requests", 1)[1].split('class="cards"', 1)[0]
    assert "people" not in headline and "automated" not in headline, headline
    assert "Cumulative figures include the operator" not in text


def test_headline_separates_people_automated_operator(tmp_path):
    """HEADLINE PIN. The latest labelled month is split into people, automated and unclassified per
    metric, the operator line is shown apart with the date it left every figure, and declared crawlers
    stay a separate excluded line. FAILS IF a split, the operator line, the crawler line or the floor
    sentence is missing or wrong, or the block is not ahead of the cards."""
    html = run(_analytics(tmp_path, _label_stats()))
    text = _text(html)
    for want in ("Who made these requests, July 2026 (4 of 4 active days labelled)",
                 "Downloads 52: people 20, automated 24, unclassified 8.",
                 "Portal visits 212: people 200, automated 2, unclassified 10.",
                 "API requests 22: people 0, automated 20, unclassified 2.",
                 "Time-series hand-offs 21: people 12, automated 6, unclassified 3.",
                 "Operator, excluded from every figure on this page since 2026-06-01: downloads 14, "
                 "visits 51, API requests 6, hand-offs 4.",
                 "Declared crawlers, excluded as before: 2,310 requests.",
                 "People is a floor. Unclassified requests may include people."):
        assert want in text, f"missing {want!r}"
    assert html.index("Who made these requests") < html.index('class="cards"')
    assert "month in progress" not in text

    no_handoff = _label_stats()
    no_handoff["monthly"][2].pop("handoffs")
    assert "Time-series hand-offs 21" not in _text(curatorpage._labels_headline(no_handoff))  # noqa: SLF001

    in_progress = _label_stats(generated_at="2026-07-20T03:35:00Z")
    assert "(4 of 4 active days labelled; month in progress)" in _text(
        curatorpage._labels_headline(in_progress))                                    # noqa: SLF001


def test_audience_rule_from_joint_keys():
    """AUDIENCE UNIT. The rule is a pure function of the stored joint key, so a later reading of it
    needs no refold. FAILS IF any pairing maps to the wrong audience."""
    audience = curatorpage.audience
    assert audience("tool", "access_provider") == "automated"
    assert audience("portal_session", "hosting") == "people"
    assert audience("landing_page", "other") == "people"
    assert audience("unknown", "hosting") == "automated"
    assert audience("unknown", "education_research") == "unclassified"
    assert audience("unknown", "unknown") == "unclassified"
    assert audience("tool", "unknown") == "automated"


def test_inputs_missing_line_when_days_short(tmp_path):
    """INPUTS PIN. A month whose network-type table or operator list was unavailable on some labelled
    days must say so beside the split it weakens, in the warning style, naming only the inputs that
    were short. FAILS IF the line is absent when days are short, names an input that was complete, or
    appears when nothing was short."""
    text = _text(run(_analytics(tmp_path, _label_stats())))
    assert ("Inputs missing: the network-type table was unavailable on 1 of 4 labelled days; the "
            "operator list was unavailable on 2 of 4 labelled days.") in text

    only_list = _label_stats()
    only_list["monthly"][2]["nettype_days"] = 4
    one = _text(curatorpage._labels_headline(only_list))                             # noqa: SLF001
    assert "Inputs missing: the operator list was unavailable on 2 of 4 labelled days." in one
    assert "network-type table was unavailable" not in one

    full = _label_stats()
    full["monthly"][2].update(nettype_days=4, operator_list_days=4)
    assert "Inputs missing" not in curatorpage._labels_headline(full)                  # noqa: SLF001
    assert _PALETTE_WARN in curatorpage._labels_headline(_label_stats())               # noqa: SLF001


_PALETTE_WARN = curatorpage._PALETTE["warn"]                                           # noqa: SLF001


def test_classification_table_from_latest_labelled_month(tmp_path):
    """CLASSIFICATION TABLE PIN. Built from the latest labelled month alone, after the format
    breakdown: one row per client class and one per network type, each summed over the other label,
    across downloads, visits, API requests and hand-offs. FAILS IF the month, a row or a sum is wrong,
    or the hosting-only note is missing when some days had a hosting-only table."""
    html = run(_analytics(tmp_path, _label_stats()))
    assert "How requests were classified, July 2026" in html
    section = html.split("How requests were classified", 1)[1].split("Quarterly breakdown", 1)[0]
    assert html.index("whole-survey bundles") < html.index("How requests were classified")
    assert _row_cells(section, "Portal session") == ["15", "200", "0", "12"]
    assert _row_cells(section, "Landing page") == ["5", "0", "0", "0"]
    assert _row_cells(section, "Tool") == ["20", "0", "20", "6"]
    assert _row_cells(section, "Unknown client") == ["12", "12", "2", "3"]
    assert _row_cells(section, "Hosting") == ["24", "202", "0", "6"]
    assert _row_cells(section, "Education or research") == ["6", "0", "0", "12"]
    assert _row_cells(section, "Access provider") == ["15", "0", "20", "0"]
    assert _row_cells(section, "Other") == ["5", "0", "2", "0"]
    assert _row_cells(section, "Unknown network") == ["2", "10", "0", "3"]
    assert ("Network type covered hosting only on 2 days; on those days every other network reads "
            "unknown.") in _text(section)

    assert "How requests were classified" not in run(_analytics(tmp_path / "b", _v7_stats()))


def test_label_rows_not_measured_before_labels_since(tmp_path):
    """MONTHLY LABEL ROWS PIN. The label rows follow the browser and scripted row, and a month folded
    before labels began reads "not measured" on every one of them, never zero. The browser and
    scripted row stays and says what it is not. FAILS IF a row is missing or out of place, if the
    unlabelled month renders a figure, or if a labelled month's figure is wrong."""
    table = _quarterly(run(_analytics(tmp_path, _label_stats())))
    nm = curatorpage._NOT_MEASURED                                                     # noqa: SLF001
    expect = {
        "Downloads: people / automated / unclassified": [nm, "0 / 40 / 15", "20 / 24 / 8"],
        "Portal visits: people / automated / unclassified": [nm, "210 / 0 / 0", "200 / 2 / 10"],
        "API requests: people / automated / unclassified": [nm, "0 / 27 / 0", "0 / 20 / 2"],
        "Hand-offs: people / automated / unclassified": [nm, nm, "12 / 6 / 3"],
        "Operator requests (excluded)": [nm, "3", "75"],
        "Declared crawler requests (excluded)": [nm, "1", "2310"],
        "Download client: portal session / landing page / tool / unknown":
            [nm, "0 / 0 / 40 / 15", "15 / 5 / 20 / 12"],
        "Download network: hosting / education and research / access provider / other / unknown":
            [nm, "0 / 0 / 0 / 0 / 55", "24 / 6 / 15 / 5 / 2"],
        "Labelled days": [nm, "29", "4"],
    }
    for label, cells in expect.items():
        assert _row_cells(table, label) == cells, label
    order = [table.index(label) for label in expect]
    assert table.index("Browser / scripted downloads") < order[0] and order == sorted(order)
    assert ("User-agent only. A browser-like user-agent is not evidence of a person; see the people "
            "/ automated rows.") in _text(table)

    plain = _quarterly(run(_analytics(tmp_path / "b", _v7_stats())))
    assert "Labelled days" not in plain and "people / automated" not in plain


def test_seam_notes_name_partial_inputs(tmp_path):
    """SEAM NOTES PIN. Under the quarterly table each shown month says how much of it was labelled and
    which inputs it lacked, in exact words. FAILS IF a note is missing for a short month, or written
    for a month that was not short."""
    doc = _label_stats()
    doc["monthly"][2]["days"] = 6
    doc["monthly"][2]["detail_days"] = 6
    text = _text(_quarterly(run(_analytics(tmp_path, doc))))
    for want in (
            "Jul 2026: labels cover 4 of 6 active days; the rest are not labelled and include the "
            "operator's own requests.",
            "Jul 2026: the network-type table was unavailable on 1 labelled days (missing, or a "
            "source older than 45 days); those requests read unknown network, so automated is a "
            "floor.",
            "Jul 2026: network type covered hosting only on 2 labelled days.",
            "Jul 2026: the operator list was unavailable on 2 labelled days; operator browsing from "
            "the operator's own networks may be counted on those days.",
            "Jun 2026: network type covered hosting only on 29 labelled days."):
        assert want in text, f"missing {want!r}"
    for absent in ("Jun 2026: labels cover", "Jun 2026: the network-type table",
                   "Jun 2026: the operator list", "May 2026: labels cover"):
        assert absent not in text, absent


def test_scope_line_on_country_state_survey_tables(tmp_path):
    """SCOPE PIN. Every table that carries no label breakdown says that operator requests left it on
    the day labels began, and the cards say their cumulative figures straddle that day. FAILS IF a
    table lacks the line once labels have begun, or carries it before."""
    doc = _label_stats()
    html = run(_analytics(tmp_path, doc))
    scope = "From 2026-06-01, operator requests are excluded."
    for start, end in (("<h2>Downloads by survey</h2>", "<h2>Daily downloads"),
                       ("<h2>Top datasets</h2>", "<h2>By country</h2>"),
                       ("<h2>By country</h2>", "<h2>Australia by state</h2>"),
                       ("<h2>Australia by state</h2>", None)):
        section = html.split(start, 1)[1]
        section = section if end is None else section.split(end, 1)[0]
        assert scope in _text(section), start
    cards = html.split('class="cards"', 1)[1].split("Quarterly breakdown", 1)[0]
    assert ("Cumulative figures include the operator's own requests before 2026-06-01 and exclude "
            "them from that day.") in _text(cards)

    plain = _text(run(_analytics(tmp_path / "b", _v7_stats())))
    assert "operator requests are excluded" not in plain


def test_monthly_csv_label_columns_in_order_and_empty_not_zero_before_labels():
    """CSV LABEL COLUMNS PIN. The fixed label columns sit after detail_days and before the dynamic
    format and kind columns, in the stated order, and a month without labels leaves every one empty.
    FAILS IF a column is missing or moved, a value is wrong, or an unlabelled month exports 0."""
    cols = ["label_days", "nettype_days", "nettype_full_days", "operator_list_days",
            "downloads_people", "downloads_automated", "downloads_unclassified",
            "visits_people", "visits_automated", "visits_unclassified",
            "api_people", "api_automated", "api_unclassified",
            "handoffs_people", "handoffs_automated", "handoffs_unclassified",
            "operator_downloads", "operator_visits", "operator_api", "operator_handoffs",
            "operator_download_bytes",
            "crawler_excluded_downloads", "crawler_excluded_visits", "crawler_excluded_api",
            "crawler_excluded_handoffs",
            "downloads_client_portal_session", "downloads_client_landing_page",
            "downloads_client_tool", "downloads_client_unknown",
            "downloads_net_hosting", "downloads_net_education_research",
            "downloads_net_access_provider", "downloads_net_other", "downloads_net_unknown"]
    rows = list(csv.reader(io.StringIO(curatorpage.analytics_monthly_csv(_label_stats()))))
    header = rows[0]
    at = header.index("detail_days") + 1
    assert header[at:at + len(cols)] == cols
    first_dynamic = min(i for i, h in enumerate(header) if h.startswith(("format_", "kind_")))
    assert first_dynamic >= at + len(cols), "the label columns precede every dynamic column"
    by_month = {r[0]: dict(zip(header, r)) for r in rows[1:]}
    assert all(by_month["2026-05"][c] == "" for c in cols), "an unlabelled month exports empty"
    july = by_month["2026-07"]
    assert [july[c] for c in cols] == [
        "4", "3", "1", "2", "20", "24", "8", "200", "2", "10", "0", "20", "2", "12", "6", "3",
        "14", "51", "6", "4", "1048576", "2000", "300", "10", "0", "15", "5", "20", "12",
        "24", "6", "15", "5", "2"]
    june = by_month["2026-06"]
    assert [june[c] for c in cols[13:16]] == ["", "", ""], "no hand-off class, no hand-off cells"
    assert june["downloads_unclassified"] == "15" and june["downloads_net_unknown"] == "55"
    assert by_month["2026-07"]["downloads_browser"] == "30", "the user-agent split is unchanged"


def test_no_label_column_in_survey_or_country_csv():
    """GRAIN PIN. Labels are reported at month grain only and never crossed with survey or country, so
    neither of those exports gains a column. FAILS IF either header changes."""
    doc = _label_stats()
    assert next(csv.reader(io.StringIO(curatorpage.analytics_survey_csv(doc)))) == [
        "month", "survey", "downloads", "download_bytes", "countries", "files", "bundles"]
    assert next(csv.reader(io.StringIO(curatorpage.analytics_country_csv(doc)))) == [
        "month", "country", "requests", "downloads", "visits", "api", "download_bytes", "geo_days"]


def test_attribution_present_when_nettype_days(tmp_path):
    """ATTRIBUTION PIN. The hosting lists are MIT and built in part from CC BY-SA data, so the page
    that shows a network type credits them, and credits PeeringDB and iptoasn.com only when a shown
    month used the full table. FAILS IF the credit is missing when a table was used, claims the full
    sources when none was used, or appears when no table was used."""
    hosting = ("Hosting ranges: X4BNet lists_vpn (MIT licence), built in part from IPLocate.io data "
               "(CC BY-SA 4.0).")
    full = " Network types: PeeringDB. Prefix to network: iptoasn.com."
    text = _text(run(_analytics(tmp_path, _label_stats())))
    assert hosting + full in text

    hosting_only = _label_stats()
    hosting_only["monthly"][2]["nettype_full_days"] = 0
    text = _text(run(_analytics(tmp_path / "b", hosting_only)))
    assert hosting in text and "PeeringDB" not in text

    none = _label_stats()
    for m in none["monthly"][1:]:
        m.update(nettype_days=0, nettype_full_days=0)
    assert "X4BNet" not in run(_analytics(tmp_path / "c", none))


_RULING_CAVEATS = (
    "no addresses or user-agents are stored",
    "the portal renders them client-side with no per-navigation request (record D3)",
    "the portal marks its own file requests with a query flag (<code>sel=bulk</code>)",
    "It is a path-class signal and it is an upper bound",
    "crawlers, previewers and uptime probes are excluded from every figure",
    "A download is counted <b>once per day per masked network per file</b>",
    "the countries themselves are not reported per survey",
    "API requests count toward a country only from the fold that began counting them",
    "There is deliberately no city breakdown, and no state figure for any single day.",
    "some days were folded before the current counting rules existed",
)


def test_every_ruling_caveat_survives(tmp_path):
    """CAVEAT SURVIVAL PIN. The labels add wording; they remove none. Every existing caveat on this
    screen still renders, word for word, on a labelled box. FAILS IF any of them is reworded or lost."""
    doc = _label_stats()
    doc["monthly"][0]["detail_days"] = 0
    doc["by_country_detail"] = {"AU": {"downloads": 1, "visits": 1, "api": 1, "bytes": 1}}
    html = run(_analytics(tmp_path, doc))
    for caveat in _RULING_CAVEATS:
        assert caveat in html, caveat
    assert ("Scripted clients are now reported as tool; see the labels.") in _text(html)


def test_intro_caveat_paragraph_states_the_three_labels(tmp_path):
    """INTRO PIN. A labelled box carries the labels paragraph after the existing three, word for word,
    and an unlabelled box carries neither it nor the sentence on scripted clients. FAILS IF the
    paragraph is missing, out of place, or shown before labels began."""
    html = run(_analytics(tmp_path, _label_stats()))
    text = _text(html)
    assert ("From 2026-06-01, each counted request carries three labels, worked out when the log is "
            "folded and never stored per request.") in text
    assert ("Labels are reported at month grain only and are never crossed with country, state, "
            "survey or dataset.") in text
    assert html.index("so the volume covers what was actually served") < html.index(
        "each counted request carries three labels")
    plain = _text(run(_analytics(tmp_path / "b", _v7_stats())))
    assert "three labels" not in plain and "now reported as tool" not in plain


def test_new_wording_has_no_dash_characters():
    """WORDING PIN. The label wording carries no dash character, rendered or as an entity. FAILS IF
    any label surface contains one."""
    doc = _label_stats()
    doc["monthly"][2]["days"] = 6
    parts = [curatorpage._labels_headline(doc),                                        # noqa: SLF001
             curatorpage._labels_headline(_v7_stats()),                                # noqa: SLF001
             curatorpage._classification_table(doc),                                   # noqa: SLF001
             curatorpage._labels_intro(doc),                                           # noqa: SLF001
             curatorpage._label_seam_notes(doc["monthly"]),                            # noqa: SLF001
             curatorpage._labels_scope_line(doc),                                      # noqa: SLF001
             curatorpage._labels_card_note(doc)]                                       # noqa: SLF001
    for part in parts:
        assert part, "every label surface renders for a labelled box"
        for dash in ("\u2014", "\u2013", "&mdash;", "&ndash;", "&#8212;", "&#8211;"):
            assert dash not in part, (dash, part)


# --------------------------------------------------------------------------------------------------
# SELECTION EXPORTS beside the download figures. A selection export fetches each selected station's
# file separately under the export label, so one export can add thousands of counted downloads. The
# fold already holds the month's bulk and single split and its export-event count; these pins hold
# them on the quarterly table, in the headline and in the monthly export, never crossed with
# geography, survey or dataset, and "not measured" for a month before the split began.
# --------------------------------------------------------------------------------------------------
def _select_stats(**over) -> dict:
    """The labelled fixture with the selection split from its June month on. May predates it and
    carries the dense zeroes a carried-forward month holds, which must not read as measured."""
    doc = _label_stats()
    doc["select_since"] = "2026-06-01"
    doc["monthly"][0].update(downloads_by_select={"single": 0, "bulk": 0}, bulk_export_events=0)
    doc["monthly"][1].update(downloads_by_select={"single": 50, "bulk": 5}, bulk_export_events=1)
    doc.update(over)
    return doc


def test_selection_exports_row_follows_station_files_row(tmp_path):
    """QUARTERLY ROW PIN. Directly after the station files and bundles row, each shown month gives
    its export files and export events, and a month before the split began reads "not measured".
    A box whose fold never took the split shows no row. FAILS IF the row is missing, misplaced,
    wrong, or renders a zero for an unmeasured month."""
    table = _quarterly(run(_analytics(tmp_path, _select_stats())))
    nm = curatorpage._NOT_MEASURED                                                     # noqa: SLF001
    assert _row_cells(table, "Selection exports: files / exports") == [nm, "5 / 1", "33 / 7"]
    after = table.split("Station files / bundles", 1)[1].split("</tr>", 1)[1]
    assert after.lstrip().startswith("<tr><td>Selection exports: files / exports"), after[:120]

    unstamped = _select_stats(select_since=None)
    cells = _row_cells(_quarterly(run(_analytics(tmp_path / "b", unstamped))),
                       "Selection exports: files / exports")
    assert cells == ["0 / 0", "5 / 1", "33 / 7"], "no stamp: the split counts from the first fold"

    never = _select_stats()
    never["totals"].pop("downloads_by_select")
    assert "Selection exports" not in run(_analytics(tmp_path / "c", never))


def test_headline_selection_exports_line_under_downloads(tmp_path):
    """HEADLINE PIN. Directly under the Downloads line the latest labelled month says how many of its
    files came from selection exports and in how many exports. FAILS IF the line is missing, out of
    place, wrong, or claims a figure for a month the split did not cover."""
    text = _text(run(_analytics(tmp_path, _select_stats())))
    downloads = "Downloads 52: people 20, automated 24, unclassified 8."
    line = "Selection exports: 33 files in 7 exports. One export is one action by one person."
    assert downloads + " " + line + " Portal visits 212" in text, text[text.find(downloads) - 5:][:400]

    late = _text(curatorpage._labels_headline(_select_stats(select_since="2026-08-01")))  # noqa: SLF001
    assert "Selection exports: not measured." in late and "33 files" not in late
    assert "Selection exports" not in _text(curatorpage._labels_headline(_v7_stats()))   # noqa: SLF001


def test_monthly_csv_selection_columns_after_label_columns():
    """CSV PIN. downloads_select_bulk, downloads_select_single and bulk_export_events follow the
    label columns, and a month the split did not cover leaves all three empty. FAILS IF a column is
    missing, misplaced, wrong, or an unmeasured month exports 0."""
    cols = ["downloads_select_bulk", "downloads_select_single", "bulk_export_events"]
    rows = list(csv.reader(io.StringIO(curatorpage.analytics_monthly_csv(_select_stats()))))
    header = rows[0]
    at = header.index("downloads_net_unknown") + 1
    assert header[at:at + 3] == cols and header[at + 3].startswith("format_")
    assert header.count("bulk_export_events") == 1
    by_month = {r[0]: dict(zip(header, r)) for r in rows[1:]}
    assert [by_month["2026-05"][c] for c in cols] == ["", "", ""]
    assert [by_month["2026-06"][c] for c in cols] == ["5", "50", "1"]
    assert [by_month["2026-07"][c] for c in cols] == ["33", "19", "7"]

    never = _select_stats()
    never["totals"].pop("downloads_by_select")
    rows = list(csv.DictReader(io.StringIO(curatorpage.analytics_monthly_csv(never))))
    assert all(r[c] == "" for r in rows for c in cols)


def test_intro_caveat_names_selection_exports(tmp_path):
    """INTRO PIN. The labels paragraph says what one export does to the download count. FAILS IF the
    sentence is missing from a labelled box or shown on an unlabelled one."""
    sentence = ("A selection export fetches each selected station's file separately, so one export "
                "can add thousands of downloads; the selection exports row shows how many.")
    html = run(_analytics(tmp_path, _select_stats()))
    intro = _text(html.split("each counted request carries three labels", 1)[1].split("</p>", 1)[0])
    assert sentence in intro
    assert sentence not in _text(run(_analytics(tmp_path / "b", _v7_stats())))


def test_selection_exports_not_crossed_with_geography_or_survey(tmp_path):
    """GRAIN PIN. The export figures are month and cumulative only: no survey, top-dataset, country
    or state table carries one, and neither the survey nor the country export gains a column. FAILS
    IF an export figure appears beside a place, a survey or a dataset."""
    doc = _select_stats()
    html = run(_analytics(tmp_path, doc))
    for start, end in (("<h2>Downloads by survey</h2>", "<h2>Daily downloads"),
                       ("<h2>Top datasets</h2>", "<h2>By country</h2>"),
                       ("<h2>By country</h2>", None)):
        section = html.split(start, 1)[1]
        section = section if end is None else section.split(end, 1)[0]
        assert "Selection export" not in section and "sel=bulk" not in section, start
        assert "export event" not in section.lower(), start
    assert next(csv.reader(io.StringIO(curatorpage.analytics_survey_csv(doc)))) == [
        "month", "survey", "downloads", "download_bytes", "countries", "files", "bundles"]
    assert next(csv.reader(io.StringIO(curatorpage.analytics_country_csv(doc)))) == [
        "month", "country", "requests", "downloads", "visits", "api", "download_bytes", "geo_days"]


def test_export_label_caveat_survives_unchanged(tmp_path):
    """CAVEAT PIN. The existing wording on the export label, in the intro and on the bulk export
    line, still renders word for word beside the new figures. FAILS IF any of it is reworded."""
    html = run(_analytics(tmp_path, _select_stats()))
    for caveat in (
            "That is a label on requests that already happen: no new request, no beacon, no "
            "identity. The flag is stripped off before the file is attributed, so a labelled and "
            "an unlabelled fetch of the same file are still one download.",
            "Bulk map exports: <b>7</b> event(s), <b>33</b> file(s). An export is a map selection "
            "the portal zips in the browser, and it labels its own file requests so they can be "
            "told apart from single downloads. The event figure counts distinct networks per day, "
            "so two exports from one network on one day read as one: it is a floor, not a count "
            "of actions.",
            "The selection split is counted from <b>2026-06-01</b> onward"):
        assert caveat in html, caveat
