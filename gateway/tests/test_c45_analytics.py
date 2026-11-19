"""Usage analytics (gateway half): the CSV exports, the pure label rules, and the counting, grain
and privacy rules as the curator Usage page renders them.

The gateway reads stats.json server-side (serve_state.read_stats, the ops-status.json seam). These
pins hold each rule against an independent observable: the exported CSV, a pure helper's return value,
or the page as its route renders it. Async bodies run under conftest.run() (no pytest-asyncio).

Each pin states its failure criterion.
"""
from __future__ import annotations

import csv
import io
import re
import time

from pathlib import Path

from gateway import curatorpage, serve_state
from gateway.tests.conftest import app_client, curator_login, run
from gateway.tests.usage_helpers import (card, fetch, row_values, sections, table_head, table_rows,
                                         text, tile, write_stats)

_REPO = Path(__file__).resolve().parents[2]
_write_stats = write_stats


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


# --------------------------------------------------------------------------------------------------
# Render: a fresh stats.json paints the cards, tables, and the SVG sparkline.
# --------------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------------
# Staleness: old generated_at -> STALE banner, still 200 (fail-closed both directions).
# --------------------------------------------------------------------------------------------------
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
# --------------------------------------------------------------------------------------------------
# Unit: the sparkline + helpers (no framework needed).
# --------------------------------------------------------------------------------------------------
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


def _operator_only_month(doc: dict) -> dict:
    """`doc` with a labelled August that so far holds only an operator visit and a crawler visit:
    no counted day, so no day counter, but the operator and crawler lines the fold wrote."""
    doc["monthly"].append({
        "month": "2026-08", "downloads": 0, "visits": 0, "download_bytes": 0, "days": 0,
        "operator": {"downloads": 0, "visits": 1, "api": 0, "handoffs": 0, "download_bytes": 0},
        "crawler_excluded": {"downloads": 0, "visits": 1, "api": 0, "handoffs": 0}})
    return doc


# ==================================================================================================
# The rules above, held on the Usage page. Every page test fetches the page through its route.
# ==================================================================================================

def _page(tmp_path, doc) -> str:
    return run(fetch(tmp_path, doc))


def _month_rows(page: str) -> dict[str, list[str]]:
    """{month: cells} of the month table, keyed on the month without its to or from day."""
    return {re.sub(r" \(.*$", "", cells[0]): cells[1:]
            for cells in table_rows(sections(page)["months"])}


_MONTH_COLUMNS = ["Month", "Visits", "Downloads", "Export files", "Exports at least", "Bundles",
                  "Single files", "API", "Hand-offs", "Countries", "Volume"]


def _col(page: str, month: str, column: str) -> str:
    return _month_rows(page)[month][_MONTH_COLUMNS.index(column) - 1]


def test_analytics_stale_stats_shows_stale_banner_and_200(tmp_path):
    """STALENESS PIN. A stats.json older than about two timer periods renders with status 200, the
    header reads stale and never 'updated nightly', and the health warning shows. FAILS IF a stale
    file renders as current, or 500s."""
    page = _page(tmp_path, _fresh_stats(generated_at="2020-01-01T00:00:00Z"))
    header = sections(page)["header"]
    assert 'class="u-asof u-stale">data to 11 Jul 2026, stale<' in header
    assert "updated nightly" not in page
    notes = sections(page)["notes"]
    assert "Warning: no count" in text(notes)
    fresh = _page(tmp_path / "b", _fresh_stats())
    assert "updated nightly" in sections(fresh)["header"] and "stale" not in text(
        sections(fresh)["header"])


def test_analytics_missing_stats_shows_empty_state_not_500(tmp_path):
    """EMPTY-STATE PIN. With no stats.json the page renders 200 with the empty sentence and no figure:
    no digit appears in any tile or table, and there are none. FAILS IF a missing file 500s or
    renders a fabricated figure."""
    page = _page(tmp_path, None)
    assert "No usage figures yet: the nightly count has not written its file." in text(page)
    assert "no data yet" in sections(page)["header"]
    assert 'class="u-tiles"' not in page
    assert "<table" not in page.split('<div class="u-inner">', 1)[1]
    assert "ausmt-stats" in text(sections(page)["notes"]), "the warning names the timer"


def test_analytics_screen_has_no_inline_js(tmp_path):
    """CSP SWEEP. On the fresh, empty, stale and labelled pages every script carries src and no
    element carries an on* handler; both are dead under the strictPages CSP. FAILS IF any state ships
    inline script."""
    for i, doc in enumerate((_fresh_stats(), None, _fresh_stats(generated_at="2020-01-01T00:00:00Z"),
                             _label_stats())):
        page = _page(tmp_path / str(i), doc)
        for m in re.finditer(r"<script\b[^>]*>", page):
            assert re.search(r"\bsrc\s*=", m.group(0)), f"inline <script>: {m.group(0)}"
        assert re.findall(r"<[^>]*\son\w+\s*=", page) == []


def test_analytics_renders_survey_volume_kind_split_api_line_and_reach(tmp_path):
    """FUNDING-DETAIL PIN. The last full month shows its downloads split into selection-export files,
    whole-survey bundles and single files, and its API requests; the month table carries volume and
    API per month. The reach figure is held in the monthly CSV (pinned there). FAILS IF the split,
    the API figure or the volume is missing or wrong."""
    doc = _v6_stats(last_folded_date="2026-07-31", select_since=None)
    page = _page(tmp_path, doc)
    downloads = text(tile(page, "Downloads"))
    assert "33 files in at least 7 selection exports" in downloads
    assert "12 whole-survey bundles" in downloads and "7 single files" in downloads
    assert text(tile(page, "API requests")).startswith("API requests 22")
    assert _col(page, "July 2026", "Volume") == "2.0 MB"
    assert _col(page, "June 2026", "API") == "27"


def test_analytics_renders_last_three_calendar_months_side_by_side(tmp_path):
    """MONTH TABLE PIN. Every month held renders, newest first, and no month is invented. FAILS IF a
    held month is missing, the order is wrong, or a month the fold never wrote appears."""
    doc = _v2_stats()
    doc["monthly"].insert(0, {"month": "2026-04", "downloads": 9, "visits": 9, "download_bytes": 10,
                              "unattributed": 0, "api_requests": 0, "days": 3, "seeded_days": 0,
                              "formats": {}, "kinds": {}, "surveys": {}, "countries": {}})
    rows = [cells[0] for cells in table_rows(sections(_page(tmp_path, doc))["months"])]
    assert rows == ["July 2026 (to 11th) (from 8th)", "June 2026", "May 2026", "April 2026"]


def test_analytics_does_not_fabricate_months_before_the_fold(tmp_path):
    """BACKFILL-HONESTY PIN. With no monthly rollups the month section says so rather than render
    empty or invented months, and no tile is drawn. FAILS IF a month the fold never wrote appears."""
    page = _page(tmp_path, _fresh_stats())
    assert "No months yet; the first fills in at the next nightly count." in text(page)
    assert 'class="u-tiles"' not in page and "<h2>Month by month</h2><div" not in page
    assert "No full month yet." in text(page)


def test_analytics_renders_v1_stats_without_breaking(tmp_path):
    """SCHEMA-TOLERANCE PIN. A schema-1 stats.json (bare-int surveys, no monthly, daily rows without
    detail) renders without a 500 and without inventing figures: the surveys card still ranks, and
    the day charts read not measured for the bundle and file series. FAILS IF the older file 500s or
    a figure is fabricated."""
    page = _page(tmp_path, _fresh_stats())
    assert row_values(card(page, "Most downloaded surveys")) == [("CI Sample Survey", "120"),
                                                                  ("Burra 2017", "13")]
    twin = table_rows(sections(page)["days"])
    assert twin[0] == ["11 Jul 2026", "152", "not measured", "not measured", "not measured",
                       "not measured"]


def test_analytics_detail_caveat_names_the_date_detail_began(tmp_path):
    """HONESTY PIN. When some month cell reads not measured, the caption under the month table names
    the day detail began; without detail_since it names no date. FAILS IF the date is missing, or
    a date is invented."""
    doc = _v2_stats()
    doc["monthly"][0]["seeded_days"] = 20
    page = _page(tmp_path, doc)
    caption = text(sections(page)["months"].split('<p class="u-sub">', 1)[1])
    assert caption.startswith("Not measured means counted before that figure existed: detail from "
                              "1 May 2026.")
    bare = _page(tmp_path / "b", dict(doc, detail_since=None))
    assert "Not measured means counted before that figure existed." in text(bare)
    assert "1 May 2026" not in text(sections(bare)["months"])


def test_analytics_renders_australia_by_state_beneath_the_country_row(tmp_path):
    """STATE CARD PIN. With state figures the card names the full state, never a city, and closes
    with the Australian total. FAILS IF a state is unnamed, a state the fold never saw appears, or
    the total is missing."""
    doc = _v4_stats()
    doc["by_country_detail"] = {"AU": {"downloads": 9, "visits": 40}}
    rows = dict(row_values(card(_page(tmp_path, doc), "Australian visits by state")))
    assert rows["Queensland"] == "14" and rows["Western Australia"] == "8"
    assert rows["New South Wales"] == "not measured"
    assert "Northern Territory" not in rows and rows["Australia"] == "40"
    assert not [name for name in rows if "city" in name.lower()]


def test_analytics_omits_the_state_table_when_the_fold_produced_none(tmp_path):
    """STATE ABSENCE PIN. With no state figures the card says not measured yet and shows no state
    name and no zero. FAILS IF eight zeroes or a state name appear."""
    state = card(_page(tmp_path, _v2_stats()), "Australian visits by state")
    assert "Not measured yet." in text(state) and row_values(state) == []
    for name in ("New South Wales", "Queensland", "Tasmania"):
        assert name not in state


def test_analytics_tolerates_a_stats_file_that_still_carries_legacy_day_states(tmp_path):
    """LEGACY-DAY-STATES PIN. A day row that still carries a states map renders without a 500, and no
    state name or code reaches the charts, the twin or any data attribute. FAILS IF a day-grain
    state figure reaches the page."""
    doc = _v4_stats()
    doc["daily"][0]["states"] = {"TAS": 7}
    days = sections(_page(tmp_path, doc))["days"]
    assert "Tasmania" not in days and "TAS" not in days and ">7<" not in days.split("<table", 1)[0]


def test_analytics_state_table_says_why_it_is_state_and_not_city(tmp_path):
    """RATIONALE PIN. No city appears on the page, and the notes say state is the finest place. The
    reasoning lives in the documentation (pinned by the caveat home test). FAILS IF a city appears
    or the note is lost."""
    page = _page(tmp_path, _v4_stats())
    assert "city" not in text(page.split('<div class="u-inner">', 1)[1]).lower()
    assert "state is the finest place" in text(sections(page)["notes"])


def test_a_fully_seeded_month_says_not_measured_instead_of_rendering_zeroes(tmp_path):
    """SEEDED-MONTH PIN. A month whose every day predates the detailed dimensions reads not measured
    for bundles, single files, API, countries and volume, while its real visits and downloads still
    render. FAILS IF a fabricated zero survives or the real figures are suppressed."""
    doc = _v2_stats(last_folded_date="2026-07-31")
    doc["monthly"] = [_seeded_month()]
    page = _page(tmp_path, doc)
    cells = _month_rows(page)["July 2026"]
    for column in ("Bundles", "Single files", "API", "Countries", "Volume"):
        assert cells[_MONTH_COLUMNS.index(column) - 1] == "not measured", column
    assert cells[:2] == ["160", "41"]
    assert "0 B" not in cells
    assert "not measured" in text(tile(page, "API requests"))


def test_a_measured_month_still_renders_its_real_zeroes(tmp_path):
    """NEGATIVE CONTROL. A fully measured month renders its measured figures and real zeroes, never
    not measured. FAILS IF the degrade fires on a measured month."""
    doc = _v4_stats(last_folded_date="2026-05-31")
    doc["monthly"] = [dict(doc["monthly"][0], seeded_days=0, unattributed=0, api_requests=0)]
    cells = _month_rows(_page(tmp_path, doc))["May 2026"]
    assert cells[_MONTH_COLUMNS.index("API") - 1] == "0"
    assert cells[_MONTH_COLUMNS.index("Volume") - 1] == "1.0 MB"
    assert cells[_MONTH_COLUMNS.index("Bundles") - 1] == "5"


def test_the_countries_card_says_it_excludes_unknown(tmp_path):
    """SCOPE PIN. The tile reads 'Countries, unknown left out' and counts codes other than unknown;
    the countries card ranks without unknown and counts N the same way. FAILS IF unknown is counted
    or the label is silent about it."""
    doc = _v5_stats(last_folded_date="2026-05-31")
    doc["monthly"] = [dict(doc["monthly"][0], countries={"AU": 60, "NZ": 2, "unknown": 3})]
    page = _page(tmp_path, doc)
    assert text(tile(page, "Countries, unknown left out")).startswith(
        "Countries, unknown left out 2")
    countries = card(page, "Countries")
    names = [name for name, _v in row_values(countries)]
    assert "unknown" not in names and "top 3 of 3" in text(countries)


def test_states_counted_before_the_detail_existed_say_not_measured(tmp_path):
    """STATE DETAIL FORWARD-ONLY PIN. A state counted before the visit detail existed reads not
    measured, never 0. FAILS IF a pre-detail state renders a zero."""
    rows = dict(row_values(card(_page(tmp_path, _v5_stats()), "Australian visits by state")))
    assert rows["New South Wales"] == rows["Victoria"] == "not measured"


def test_the_state_table_still_reconciles_on_requests_alone(tmp_path):
    """RECONCILIATION SCOPE PIN. The state card is in visits and claims no request total; the exact
    request-grain sum stays a property of the monthly CSV (pinned there). FAILS IF the card names a
    request figure or the request-grain promise."""
    state = text(card(_page(tmp_path, _v5_stats()), "Australian visits by state"))
    assert "visits, all time" in state
    assert "request" not in state.lower() and "300" not in state


def test_no_state_detail_reads_not_measured(tmp_path):
    """STATE DETAIL ABSENCE PIN. With state requests but no state detail map, every state reads not
    measured and the card still closes with the Australian total. FAILS IF zeroes are fabricated or
    the card empties."""
    doc = _v5_stats()
    del doc["by_state_detail"]
    rows = row_values(card(_page(tmp_path, doc), "Australian visits by state"))
    states = [v for name, v in rows if name not in ("Not placed in a state", "Australia")]
    assert states and set(states) == {"not measured"}
    assert dict(rows)["Australia"] == "200"


def test_no_country_is_named_beside_a_survey(tmp_path):
    """GRAIN PIN. The surveys card carries only each survey's downloads: no country name, code or
    count, and no export or label figure, sits beside a survey. FAILS IF anything beyond the survey
    label and its download figure appears in a survey row."""
    surveys = card(_page(tmp_path, _label_stats()), "Most downloaded surveys")
    for name, value in row_values(surveys):
        assert re.fullmatch(r"[\d,]+", value), (name, value)
    for word in ("Australia", "New Zealand", ">AU<", ">NZ<", "People", "Automated", "export"):
        assert word not in surveys, word


def test_top_surveys_of_n_is_never_smaller_than_rows_shown(tmp_path):
    """DENOMINATOR PIN. The surveys card reads 'top k of N' with N the surveys the fold attributed
    downloads to, so N is never smaller than the rows shown, and no zero survey is listed. FAILS IF
    N is smaller than k, or a ratio against the served count returns."""
    doc = _v4_stats(total_served_surveys=1)
    doc["downloads"]["by_survey"].update({f"Survey {i}": {"downloads": i + 1} for i in range(12)})
    doc["downloads"]["by_survey"]["Quiet"] = {"downloads": 0}
    surveys = card(_page(tmp_path, doc), "Most downloaded surveys")
    shown = row_values(surveys)
    k, n = map(int, re.search(r"top (\d+) of (\d+)", text(surveys)).groups())
    assert k == len(shown) == 10 and n == 15 and n >= k
    assert "Quiet" not in surveys and "served" not in surveys


def test_a_month_folded_before_the_current_rules_says_not_measured_for_them(tmp_path):
    """SECOND-SEAM PIN. A month with no day folded under the current rules reads not measured for
    the selection split it could not carry, while the figures it did measure render. FAILS IF a
    zero is fabricated or a measured figure is swallowed."""
    doc = _v6_stats(last_folded_date="2026-07-31")
    for row in doc["monthly"]:
        row["detail_days"] = 0
    page = _page(tmp_path, doc)
    for month in ("July 2026", "June 2026", "May 2026"):
        assert _col(page, month, "Export files") == "not measured", month
        assert _col(page, month, "Single files") == "not measured", month
    assert _col(page, "June 2026", "Downloads") == "55" and _col(page, "May 2026", "Volume") == "1.0 MB"
    assert "Selection exports: not measured" in text(tile(page, "Downloads"))


def test_chart_peak_label_equals_table_twin_maximum(tmp_path):
    """ONE-ANSWER PIN. Each chart's peak label equals the largest value of its column in the table
    twin, so the page cannot answer the same question twice. FAILS IF a peak label and the twin
    disagree."""
    days = sections(_page(tmp_path, _v4_stats()))["days"]
    twin = table_rows(days)
    for chart, column in (("visits", 1), ("bundles", 2), ("files", 3)):
        svg = days.split(f'data-u-chart="{chart}"', 1)[1].split("</svg>", 1)[0]
        values = [int(r[column].replace(",", "")) for r in twin if r[column].replace(",", "").isdigit()]
        peak = re.findall(r'class="u-vlabel"[^>]*>([\d,]+)<', svg)
        assert peak == ([f"{max(values):,}"] if values and max(values) else []), chart


def test_not_measured_is_never_rendered_as_zero_anywhere(tmp_path):
    """NOT-MEASURED PIN. Across tiles, the month table, the cards and the twin, a figure the fold did
    not measure reads not measured and a measured figure reads its number; the two are never
    swapped. FAILS IF any unmeasured cell renders 0, or a measured zero renders not measured."""
    doc = _v2_stats(last_folded_date="2026-07-31")
    doc["monthly"][2]["seeded_days"] = 4
    page = _page(tmp_path, doc)
    cells = _month_rows(page)["July 2026"]
    for column in ("Export files", "Exports at least", "Bundles", "Single files", "API", "Hand-offs",
                   "Countries", "Volume"):
        assert cells[_MONTH_COLUMNS.index(column) - 1] == "not measured", column
    for label in ("API requests", "Countries, unknown left out", "Time-series hand-offs"):
        assert "not measured" in text(tile(page, label)), label
    june = _month_rows(page)["June 2026"]
    assert june[_MONTH_COLUMNS.index("Bundles") - 1] == "5"
    no_kinds = _v2_stats()
    no_kinds["daily"][0].pop("kinds")
    twin = table_rows(sections(_page(tmp_path / "b", no_kinds))["days"])
    assert twin[-1][2:4] == ["not measured", "not measured"]


def test_countries_counted_before_the_detail_existed_say_not_measured(tmp_path):
    """COUNTRY DETAIL FORWARD-ONLY PIN. A country with no detail row reads not measured for visits
    and downloads and draws no bar. FAILS IF it shows zeroes or a bar."""
    countries = card(_page(tmp_path, _v5_stats()), "Countries")
    us = countries.split("United States", 1)[1].split('<div class="u-cr">', 1)[0]
    assert text(us).count("not measured") == 2 and "u-rk-b" not in us


def test_no_country_detail_reads_not_measured(tmp_path):
    """COUNTRY DETAIL ABSENCE PIN. With country requests but no detail map, every country still
    renders by name with not measured beside it, no bar, no foot line and no Australian share. FAILS
    IF zeroes are fabricated or the card empties."""
    countries = card(_page(tmp_path, _v4_stats()), "Countries")
    assert "Australia" in countries and "u-rk-b" not in countries
    assert text(countries).count("not measured") == 6
    assert "% of visits" not in countries and "u-foot" not in countries


def test_the_screen_reports_bulk_map_exports_as_events_and_files(tmp_path):
    """BULK LINE PIN. The downloads tile carries both the export files and the exports, with the
    export count as a floor; a fold that never took the split shows not measured. FAILS IF either
    figure is missing or swapped, or a zero is shown for an unmeasured split."""
    downloads = text(tile(_page(tmp_path, _v6_stats(last_folded_date="2026-07-31", select_since=None)),
                          "Downloads"))
    assert "33 files in at least 7 selection exports" in downloads
    plain = text(tile(_page(tmp_path / "b", _v5_stats(last_folded_date="2026-07-31")), "Downloads"))
    assert "Selection exports: not measured" in plain and "0 files" not in plain


def test_the_screen_names_the_day_the_selection_split_begins(tmp_path):
    """THIRD-SEAM PIN. The month caption names the recorded day the selection split began, and a box
    with no stamp has no date invented. FAILS IF the date is missing or guessed."""
    page = _page(tmp_path, _v6_stats())
    assert "selection split from 1 Aug 2026" in text(sections(page)["months"])
    bare = _page(tmp_path / "b", _v6_stats(select_since=None))
    assert "Aug 2026" not in text(sections(bare)["months"])


def test_the_bulk_line_does_not_claim_the_export_produces_a_citation_pack(tmp_path):
    """CITATION-PACK HONESTY PIN. The export flow writes the station files and nothing else; the
    citation pack is a separate button. No page text may say an export generates, produces or counts
    a citation pack, and the documentation sentence about the pack must name it as a separate export
    the log cannot count. FAILS IF the page or the documentation claims the causal link."""
    page = text(_page(tmp_path, _v6_stats(last_folded_date="2026-07-31")))
    assert "citation pack" not in page.lower()
    docs = (_REPO / "docs" / "docs" / "introduction" / "usage-analytics.md").read_text("utf-8")
    sentence = [s for s in re.split(r"(?<=\.)\s", docs) if "citation pack" in s]
    assert len(sentence) == 1 and "separate" in sentence[0] and "cannot count" in sentence[0]
    for overclaim in ("each export also generates", "every export generates",
                      "generates a citation pack", "produces a citation pack"):
        assert overclaim not in sentence[0] and overclaim not in page


def test_the_screen_reports_time_series_hand_offs_as_requests_not_transfers(tmp_path):
    """HAND-OFF PIN. The hand-off tile and month column carry the request count, and the notes say in
    words that these are requests to NCI THREDDS, not completed transfers. A month with no hand-off
    class reads not measured. FAILS IF the figure is missing, claims transfers, or a zero appears for
    a month that never measured it."""
    page = _page(tmp_path, _v7_stats(last_folded_date="2026-07-31"))
    assert text(tile(page, "Time-series hand-offs")).startswith("Time-series hand-offs 21")
    assert ("hand-offs are requests to NCI THREDDS, not completed transfers"
            in text(sections(page)["notes"]))
    assert "transferred" not in text(page).lower()


def test_a_month_folded_before_hand_offs_existed_says_not_measured(tmp_path):
    """SEAM PIN. A month with no hand-off key reads not measured, never 0, and the month that has
    one renders its figure. FAILS IF a zero is fabricated or the measured month is degraded."""
    page = _page(tmp_path, _v7_stats())
    assert _col(page, "July 2026", "Hand-offs") == "21"
    assert _col(page, "June 2026", "Hand-offs") == _col(page, "May 2026", "Hand-offs") == "not measured"


def test_headline_not_measured_before_labels(tmp_path):
    """WHO PLACEHOLDER PIN. A box whose fold has never labelled a day shows the three audiences as
    pills and says the split is not measured yet, with no audience figure anywhere. FAILS IF a
    people, automated or unclassified figure is claimed."""
    who = sections(_page(tmp_path, _v7_stats()))["who"]
    assert ("Not measured yet; each figure above splits three ways once labels start."
            in text(who))
    assert 'class="u-who-row"' not in who and not re.search(r"\d", text(who))


def test_headline_separates_people_automated_operator(tmp_path):
    """WHO PIN. A labelled last full month splits each measure into people, automated and
    unclassified, with numbers beside every bar, and the left-out line names the operator's own
    requests and declared crawlers apart from every figure. FAILS IF a split or the left-out line is
    wrong."""
    who = sections(_page(tmp_path, _label_stats(last_folded_date="2026-07-31")))["who"]
    lines = text(who)
    for want in ("Downloads People 20 · Automated 24 · Unclassified 8",
                 "Portal visits People 200 · Automated 2 · Unclassified 10",
                 "API requests People 0 · Automated 20 · Unclassified 2",
                 "Time-series hand-offs People 12 · Automated 6 · Unclassified 3",
                 "Left out: your own requests 75, declared crawlers 2,310."):
        assert want in lines, want
    assert "People is a floor: unclassified requests may include people." in text(
        _page(tmp_path / "b", _label_stats()))


def test_inputs_missing_line_when_days_short(tmp_path):
    """INPUTS PIN. A month short of an input on some labelled days says so in one warning line naming
    only the inputs that were short, and shows nothing when none was. FAILS IF the line is absent,
    names a complete input, or appears when nothing was short."""
    doc = _label_stats(last_folded_date="2026-07-31")
    assert ("Warning: no network type 1 days; no operator list 2 days; hosting-only 2 days."
            in text(sections(_page(tmp_path, doc))["who"]))
    doc["monthly"][2].update(nettype_days=4, nettype_full_days=4, operator_list_days=4)
    assert "u-warn" not in sections(_page(tmp_path / "b", doc))["who"]


def test_who_detail_marginals_describe_the_tile_month(tmp_path):
    """WHO DETAIL PIN. The collapsed table describes the month the who card names, one row per client
    class then one per network type, each summed over the other label. FAILS IF the month, a row or
    a sum is wrong."""
    who = sections(_page(tmp_path, _label_stats(last_folded_date="2026-07-31")))["who"]
    assert "<summary>By client and network</summary>" in who
    assert "July 2026, requests by label" in text(who)
    rows = {r[0]: r[1:] for r in table_rows(who)}
    assert rows["Portal session"] == ["15", "200", "0", "12"]
    assert rows["Landing page"] == ["5", "0", "0", "0"]
    assert rows["Tool"] == ["20", "0", "20", "6"]
    assert rows["Unknown client"] == ["12", "12", "2", "3"]
    assert rows["Hosting"] == ["24", "202", "0", "6"]
    assert rows["Education or research"] == ["6", "0", "0", "12"]
    assert rows["Access provider"] == ["15", "0", "20", "0"]
    assert rows["Other"] == ["5", "0", "2", "0"]
    assert rows["Unknown network"] == ["2", "10", "0", "3"]
    june = sections(_page(tmp_path / "b", _label_stats()))["who"]
    assert "June 2026, requests by label" in text(june)
    assert {r[0]: r[1:] for r in table_rows(june)}["Tool"] == ["40", "0", "27", "not measured"]


def test_unlabelled_tile_month_shows_no_label_figure(tmp_path):
    """LABEL SEAM PIN. When neither the last full month nor the month in progress is labelled the who
    card is the placeholder, and no label figure, row or table appears anywhere on the page. FAILS
    IF an unlabelled month renders a label figure."""
    doc = _label_stats(last_folded_date="2026-05-31")
    doc["monthly"] = doc["monthly"][:1]
    page = _page(tmp_path, doc)
    assert 'class="u-who-row"' not in page and "requests by label" not in page
    assert "Not measured yet" in text(sections(page)["who"])


def test_attribution_present_when_nettype_days(tmp_path):
    """ATTRIBUTION PIN. When any held month used the network table the who card credits the hosting
    ranges with the labels branch wording, and PeeringDB and iptoasn.com only when a full table was
    used. No licence is named for the hosting lists. FAILS IF the credit is missing when a table was
    used, claims the full sources when none was used, appears when no table was used, or names the
    MIT licence."""
    hosting = ("Hosting ranges: X4BNet lists_vpn, built in part from IPLocate.io data "
               "(CC BY-SA 4.0).")
    full = " Network types: PeeringDB. Prefix to network: iptoasn.com."
    who = text(sections(_page(tmp_path, _label_stats()))["who"])
    assert hosting + full in who and not re.search(r"\bMIT\b", who)
    hosting_only = _label_stats()
    hosting_only["monthly"][2]["nettype_full_days"] = 0
    who = text(sections(_page(tmp_path / "b", hosting_only))["who"])
    assert hosting in who and "PeeringDB" not in who
    none = _label_stats()
    for m in none["monthly"][1:]:
        m.update(nettype_days=0, nettype_full_days=0)
    assert "X4BNet" not in _page(tmp_path / "c", none)


def test_month_table_export_columns_and_not_measured(tmp_path):
    """MONTH TABLE EXPORT PIN. Export files and exports sit after downloads; a month before the split
    began reads not measured; no stamp means the split counts from the first fold; a fold that never
    took the split reads not measured throughout. FAILS IF a column is misplaced or an unmeasured
    month renders a zero."""
    page = _page(tmp_path, _select_stats())
    assert table_head(sections(page)["months"]) == _MONTH_COLUMNS
    rows = _month_rows(page)
    assert rows["July 2026"][2:4] == ["33", "7"]
    assert rows["June 2026"][2:4] == ["5", "1"] and rows["May 2026"][2:4] == ["not measured"] * 2
    unstamped = _month_rows(_page(tmp_path / "b", _select_stats(select_since=None)))
    assert unstamped["May 2026"][2:4] == ["0", "0"]
    never = _select_stats()
    never["totals"].pop("downloads_by_select")
    assert all(cells[2:4] == ["not measured"] * 2
               for cells in _month_rows(_page(tmp_path / "c", never)).values())


def test_headline_selection_exports_line_under_downloads(tmp_path):
    """SPLIT PIN. Directly under the downloads figure the tile says how many files came from
    selection exports and in at least how many exports, never as a count of actions; a month the
    split did not cover reads not measured. FAILS IF the line is missing, wrong or overclaims."""
    page = _page(tmp_path, _select_stats(last_folded_date="2026-07-31"))
    split = tile(page, "Downloads").split('<ul class="u-split">', 1)[1]
    assert text(split).startswith("33 files in at least 7 selection exports")
    assert "one action" not in text(page)
    late = _page(tmp_path / "b", _select_stats(last_folded_date="2026-07-31",
                                               select_since="2026-08-01"))
    assert "Selection exports: not measured" in text(tile(late, "Downloads"))


def test_selection_exports_not_crossed_with_geography_or_survey(tmp_path):
    """GRAIN PIN. Export figures appear only in the tile split and the month table: no survey,
    country or state card carries one, and the survey and country exports gain no column. FAILS IF
    an export figure sits beside a place or a survey."""
    doc = _select_stats()
    where = sections(_page(tmp_path, doc))["where"]
    assert "export" not in text(where).lower() and "sel=bulk" not in where
    assert next(csv.reader(io.StringIO(curatorpage.analytics_survey_csv(doc)))) == [
        "month", "survey", "downloads", "download_bytes", "countries", "files", "bundles"]
    assert next(csv.reader(io.StringIO(curatorpage.analytics_country_csv(doc)))) == [
        "month", "country", "requests", "downloads", "visits", "api", "download_bytes", "geo_days"]


def test_headline_selection_line_says_it_covers_the_whole_month(tmp_path):
    """WHOLE-MONTH PIN. On a month labelled on only some of its days the warning's first clause says
    the rest include your requests, so the export figure above is not read as a labelled subset; a
    fully labelled month carries no such clause. FAILS IF a partly labelled month reads as complete."""
    part = _select_stats(last_folded_date="2026-07-31")
    part["monthly"][2].update(days=6, detail_days=6)
    who = text(sections(_page(tmp_path, part))["who"])
    assert "Warning: labels on 4 of 6 days, rest include your requests;" in who
    full = text(sections(_page(tmp_path / "b", _select_stats(last_folded_date="2026-07-31")))["who"])
    assert "labels on" not in full


def test_operator_only_month_shows_its_measured_operator_and_crawler_lines(tmp_path):
    """OPERATOR-ONLY MONTH PIN. A labelled month whose only admitted requests were the operator's or
    a crawler's reads none on every audience row, and the left-out line shows its measured figures;
    the monthly export carries them. FAILS IF those figures read not measured or export empty."""
    doc = _operator_only_month(_label_stats(last_folded_date="2026-08-31"))
    who = text(sections(_page(tmp_path, doc))["who"])
    for name in ("Downloads", "Portal visits", "API requests"):
        assert f"{name} none" in who, name
    assert "Left out: your own requests 1, declared crawlers 1." in who
    rows = {r["month"]: r for r in csv.DictReader(io.StringIO(curatorpage.analytics_monthly_csv(doc)))}
    assert rows["2026-08"]["operator_visits"] == "1"
    assert rows["2026-08"]["crawler_excluded_visits"] == "1"
    assert rows["2026-08"]["label_days"] == "0"
