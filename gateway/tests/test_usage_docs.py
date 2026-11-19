"""Documentation pins for the curator Usage page and the fold settings it depends on.

Each test reads committed text only, so it runs on every checkout without a stack.
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_DOCS = _REPO / "docs" / "docs" / "introduction" / "usage-analytics.md"
_README = _REPO / "deploy" / "README.md"
_ENV_EXAMPLE = _REPO / "deploy" / ".env.example"
_C45 = _REPO / "maintainer" / "C45-UsageAnalytics.md"
_FOLD = _REPO / "deploy" / "scripts" / "aggregate_stats.py"

# The superseded daily window, written as a length of days or as one quarter.
_OLD_WINDOW = re.compile(r"\b92[- ]days?\b|\bdefault 92\b|\bKEEP=92\b|roll off after a quarter")


def _read(path: Path) -> str:
    assert path.is_file(), f"this pin runs from a full checkout, never skipped: {path}"
    return path.read_text(encoding="utf-8")


def test_docs_and_settings_state_184_days():
    """The daily window is 184 days by default. No document, setting example, decision record, fold
    comment or gateway source may still state the old 92-day window; the explicit boundary test in
    deploy/tests passes daily_keep=92 on purpose and is not scanned. FAILS IF any scanned file names
    the old window, or if the docs, README or settings example do not state the new one."""
    scanned = [_DOCS, _README, _ENV_EXAMPLE, _C45, _FOLD]
    scanned += [p for p in sorted((_REPO / "gateway").rglob("*.py")) if p != Path(__file__).resolve()]
    offenders = []
    for path in scanned:
        for no, line in enumerate(_read(path).splitlines(), 1):
            if _OLD_WINDOW.search(line):
                offenders.append(f"{path.relative_to(_REPO)}:{no}: {line.strip()}")
    assert offenders == [], "the old daily window is still stated:\n" + "\n".join(offenders)

    assert "| Daily aggregate rows | 184 days |" in _read(_DOCS)
    assert "**184-day**" in _read(_README)
    env = _read(_ENV_EXAMPLE)
    assert "AUSMT_STATS_DAILY_KEEP=184" in env and "default 184" in env
    assert "default 184" in _read(_FOLD)


def test_log_expiry_is_documented():
    """The pulled front-door copies expire, and every place that states the raw-log retention says so
    and names the setting. FAILS IF the README, the settings example, the docs retention table or the
    decision record omits it, or a comment still calls the box copy the durable record."""
    for path in (_README, _ENV_EXAMPLE, _C45, _FOLD):
        assert "AUSMT_STATS_LOG_RETAIN_DAYS" in _read(path), path.name
    assert "AUSMT_STATS_LOG_RETAIN_DAYS=7" in _read(_ENV_EXAMPLE)
    assert "logs_expired=" in _read(_README)
    row = [ln for ln in _read(_DOCS).splitlines() if ln.startswith("| Raw access log")]
    assert len(row) == 1 and "copies" in row[0], row
    assert "*Pulled log copies expire.*" in _read(_C45)
    caddy = _read(_REPO / "deploy" / "frontdoor" / "Caddyfile")
    assert "copy on the box is the durable record" not in caddy


# One row per caveat that left the Usage page: (row, phrase that states it, heading it lives under).
# The phrase must appear exactly once in the whole documentation page, so each caveat has one home.
_CAVEAT_HOMES = (
    (1, "IP addresses are masked at the edge", "Privacy design"),
    (2, "An upper bound (a person can click the footer link)", "What is measured"),
    (3, "A download is counted once per day, per masked network, per file", "What is measured"),
    (4, "The tool class includes what earlier versions of the", "Client class"),
    (5, "each counted request is first checked for being one of these", "Operator requests"),
    (6, "Before the first nightly count has written its file the page says so", "Operating it"),
    (7, "A count is late when none has finished for two timer periods", "Health line"),
    (8, "Before any labelled month the card gives the configured start date",
     "Who made the requests"),
    (9, "it is a floor, not a count of export actions", "Who made the requests"),
    (10, "People is therefore a floor.", "Who made the requests"),
    (11, "leaves unknown out of every country count", "The figures on the page"),
    (12, "The cumulative figures include the", "Who made the requests"),
    (13, "Single files are the station files less the selection export files",
     "The figures on the page"),
    (14, "The\ncitation pack is a separate export", "Who made the requests"),
    (15, "is register drift", "The figures on the page"),
    (16, "The publisher of the X4BNet lists states no licence for them.",
     "Network type data attribution"),
    (17, "counted forward only from the fold that began reading collections", "What is measured"),
    (18, "The first is\n`detail_since`", "Seams in the record"),
    (19, "| Daily aggregate rows | 184 days |", "Retention of the aggregates"),
    (20, "a browser-like user-agent is not evidence of a person", "Who made the requests"),
    (21, "These are **requests, not completed transfers**", "What is measured"),
    (22, "a month folded before the detailed breakdown existed", "Seams in the record"),
    (23, "Its bias runs in both directions", "Seams in the record"),
    (24, "so there is no single fixed cause", "Who made the requests"),
    (25, "every export carries\nevery retained month too", "What the page leaves to the CSV exports"),
    (26, "describes each export column by\ncolumn", "What the page leaves to the CSV exports"),
    (27, "Only the count: a named survey beside a named country", "What is measured"),
    (28, "operator requests are excluded from them", "Who made the requests"),
    (29, "export carries the reach figure, `networks_peak`",
     "What the page leaves to the CSV exports"),
    (30, "API requests count toward a country only from the fold that began counting them",
     "Seams in the record"),
    (31, "\"Not placed in a state\"", "Australian traffic by state, and why not by city"),
    (32, "an older day carries no\nnetwork count (absent, not zero)", "Retention of the aggregates"),
)


def _heading_at(doc: str, index: int) -> str:
    headings = re.findall(r"^#{1,3} (.+)$", doc[:index], re.M)
    return headings[-1] if headings else ""


def test_every_moved_caveat_has_one_docs_home():
    """Every caveat that left the curator Usage page has exactly one home in the public usage
    documentation, under the heading its move names, so the page can stay short without losing a
    rule. FAILS IF a caveat is missing, stated twice, or filed under another heading."""
    doc = _read(_DOCS)
    assert [row for row, _p, _h in _CAVEAT_HOMES] == list(range(1, 33))
    misplaced = []
    for row, phrase, heading in _CAVEAT_HOMES:
        count = doc.count(phrase)
        where = _heading_at(doc, doc.find(phrase)) if count else None
        if count != 1 or where != heading:
            misplaced.append(f"row {row}: {count} found, under {where!r}, want {heading!r}")
    assert misplaced == [], "\n".join(misplaced)


def test_docs_name_the_usage_page():
    """The public documentation and the operator guide call the page the curator Usage page and its
    month table the month table. FAILS IF the old screen name or the quarterly table survives."""
    for path in (_DOCS, _README):
        body = _read(path)
        for old in ("Analytics screen", "Analytics** screen", "quarterly table", "Quarterly view",
                    "Operations → Analytics"):
            assert old not in body, (path.name, old)
    assert "curator Usage page" in _read(_DOCS) and "Usage page" in _read(_README)


def test_decision_record_says_caveats_live_in_the_docs():
    """The decision record states that the caveats live in the public documentation and that the
    page carries eight notes and a link, and that each earlier clause whose screen surface went
    points to it. FAILS IF that record or a pointer is missing."""
    c45 = _read(_C45)
    d10 = " ".join(c45.split("## D10. The Usage page", 1)[1].split())
    assert "*Caveats live in the documentation.*" in d10
    assert "eight notes" in d10 and "Reading the curator Usage page" in d10
    for pointer in ("D4 amended", "D7 amended", "D7.1 amended", "D8 amended", "D9 amended (the page)",
                    "*Day grain.*", "*Light page.*", "*Lost archive days.*"):
        assert pointer in d10, pointer
    audience = c45.split("### Audience rule and the page", 1)[1].split("### History", 1)[0]
    assert "See D10." in audience and "Analytics screen" not in audience


def test_decision_record_names_the_read_out_script():
    """The decision record states that the page loads one same-origin read-out script that reads only
    the data attributes the server wrote, and that the page is complete without it. FAILS IF that
    record is missing or the record still says the page carries no script."""
    d10 = " ".join(_read(_C45).split("## D10. The Usage page", 1)[1].split())
    assert "*One read-out script.*" in d10 and "*No script needed.*" not in d10
    record = d10.split("*One read-out script.*", 1)[1].split("- *", 1)[0]
    for phrase in ("/gateway/curator/usage.js", "same origin", "data attributes",
                   "complete without it"):
        assert phrase in record, phrase


def _section(doc: str, heading: str) -> str:
    body = doc.split(f"\n{heading}\n", 1)[1]
    return re.split(r"\n#{2,3} ", body, maxsplit=1)[0]


def _export_headers() -> set[str]:
    """Every column the three curator exports can write, from a month that carries every optional
    breakdown, including states, collections, datasets, hand-off volume and a served-survey count."""
    from gateway import curatorpage
    month = {"month": "2026-10", "downloads": 5, "visits": 2, "days": 31, "detail_days": 31,
             "geo_days": 31, "formats": {"edi": 5}, "kinds": {"file": 5},
             "countries": {"AU": 5}, "by_state": {"NSW": 3},
             "handoffs": {"requests": 2, "bytes": 4096}, "by_collection": {"c": 5},
             "downloads_by_select": {"single": 3, "bulk": 2}, "bulk_export_events": 1}
    stats = {"monthly": [month], "total_served_surveys": 9,
             "downloads": {"by_dataset": {"d": 5}, "by_collection": {"c": 5}}}
    columns = set()
    for build in (curatorpage.analytics_monthly_csv, curatorpage.analytics_survey_csv,
                  curatorpage.analytics_country_csv):
        columns |= set(build(stats).splitlines()[0].split(","))
    return columns


def test_figures_named_as_exported_are_export_columns():
    """The docs name a figure as exported only when an export has a column for it, and say plainly
    that the figures kept in stats.json alone are in no export. FAILS IF the docs name a column no
    export writes, or claim an export for the top datasets, the collection rollup, hand-off volume
    or the served-survey count."""
    doc = _read(_DOCS)
    section = _section(doc, "### What the page leaves to the CSV exports")
    exported, kept = [p for p in section.split("\n\n") if p.strip()][:2]
    columns = _export_headers()
    named = re.findall(r"`([a-z_*]+)`", exported)
    assert len(named) >= 9, named
    missing = [n for n in named if not (n in columns or (n.endswith("*")
                                                         and any(c.startswith(n[:-1]) for c in columns)))]
    assert missing == [], missing
    kept = " ".join(kept.split())
    assert "kept in `stats.json` only" in kept and "neither shown nor exported" in kept
    for figure in ("top datasets", "downloads by collection", "hand-off volume",
                   "count of served surveys"):
        assert figure in kept, figure
    for fragment in ("dataset", "collection", "served", "handoffs_bytes", "handoff_bytes"):
        assert not [c for c in columns if fragment in c], fragment
    flat = " ".join(doc.split())
    assert "lives in the monthly CSV" not in flat
    assert "country rows in the monthly country export (`analytics-countries.csv`)" in flat
    assert "unattributed hand-offs, a figure kept in `stats.json` only" in flat


def test_the_page_section_states_each_rule_once_and_as_rendered():
    """The page section links the general no-backfill rule rather than restating it, the who card
    section says what a partly labelled month means for the figures above it, the health line
    section describes each archive warning the page prints, and the retention row says when pulled
    copies expire. FAILS IF a rule gains a second home or a passage says what the page does not."""
    doc = _read(_DOCS)
    flat = " ".join(doc.split())
    assert flat.lower().count("nothing is backfilled") == 1
    seams = " ".join(_section(doc, "### Seams in the record").split())
    assert seams.startswith("The general rule is in [retention](#retention-of-the-aggregates). Two")
    who = " ".join(_section(doc, "## Who made the requests").split())
    assert ("every figure above the who card, the selection export figures included, also counts "
            "the operator's requests on the unlabelled days") in who
    assert 'otherwise reads "Not measured yet"' in who
    health = " ".join(_section(doc, "### Health line").split())
    for warning in ("the archive stops at that date", "the date is not recorded",
                    "one warning names both"):
        assert warning in health, warning
    row = [ln for ln in doc.splitlines() if ln.startswith("| Raw access log")][0]
    assert "removed once counted and more than 7 days old" in row


# Operator-facing files that describe the page the fold feeds.
_OPERATOR_FILES = ("deploy/scripts/aggregate_stats.py", "deploy/systemd/ausmt-stats.service",
                   "deploy/frontdoor/RUNBOOK.md", "gateway/serve_state.py")


def test_operator_comments_name_the_usage_page():
    """Comments and docstrings an operator reads call the page the curator Usage page. FAILS IF the
    old screen name survives in any of them, including across a wrapped comment line."""
    for name in _OPERATOR_FILES:
        flat = " ".join(re.sub(r"(?m)^\s*#", " ", _read(_REPO / name)).split())
        assert not re.search(r"analytics screen", flat, re.I), name


def test_readme_explains_the_archive_date_not_recorded_warning():
    """The operator guide's troubleshooting table has a row for the health warning that the archive
    date is not recorded, which is expected after an upgrade until the first nightly append. FAILS IF
    that warning has no row."""
    rows = [ln for ln in _read(_README).splitlines() if ln.startswith("| Usage health line")]
    assert any("not recorded" in ln and "first nightly append" in ln for ln in rows), rows
