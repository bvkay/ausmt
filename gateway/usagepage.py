"""The curator Usage page.

Every figure comes from stats.json as read by serve_state.read_stats. The page is server-rendered and
complete without any script: charts are SVG, every value is also printed or listed in a table. One
same-origin script, gateway/static/usage.js, adds a hover read-out that copies values the server
already wrote into data attributes, so the page renders the same bytes whether or not it loads.

The day-by-day charts and their table twin are pure functions of the daily rows. A daily row may
carry more than the page shows; only its date, visits, bundles, station files, API requests and
hand-off requests are ever read here, so no place, label, survey or format reaches the day grain.
Request labels appear only in the who card, at month grain, and never beside a place, survey,
dataset or day.
"""
from __future__ import annotations

import datetime as dt
import html
from pathlib import Path

from . import countrynames
from .curatorpage import (_AU_STATE_NAMES, _CLIENT_NAMES, _MONTH_NAMES, _NETTYPE_NAMES,
                          _audience_split, _block_sum, _by_label, _has_handoff_class, _human_bytes,
                          _is_labelled, _label_counts, _labels_since, _month_has_no_detail,
                          _month_long, _monthly_rows, _select_figures, _select_measured, _shell)

_NOT_MEASURED = "not measured"
_NO_ROW = "no row"
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# Chart frame in viewBox units. The plot band is fixed so every chart shares one vertical scale shape.
_W, _LEFT, _RIGHT, _TOP, _PLOT = 960, 46, 10, 18, 96
_Y0 = _TOP + _PLOT
_SPAN = _W - _LEFT - _RIGHT
_MAX_DRAWN_DAYS = 366
_DATE_GAP = 44

# (key, heading, colour class), in the order the charts stack. The last carries the date axis.
_CHARTS = (("visits", "Portal visits", "u-s-visits"),
           ("bundles", "Whole-survey bundles downloaded", "u-s-down"),
           ("files", "Station files downloaded", "u-s-down"))
_CHART_NAMES = {key: name for key, name, _cls in _CHARTS}
_CHART_CLASSES = {key: cls for key, _name, cls in _CHARTS}


def _esc(value) -> str:
    return html.escape(str(value), quote=True)


def _iso_day(value) -> dt.date | None:
    """A real calendar day written as YYYY-MM-DD, or None for anything else."""
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def _n(value: int) -> str:
    return f"{value:,}"


def _day_label(day: dt.date) -> str:
    return f"{day.day} {_MONTHS[day.month - 1]}"


def _date_long(day: dt.date) -> str:
    return f"{day.day} {_MONTHS[day.month - 1]} {day.year}"


def _u(value: float) -> str:
    """A viewBox coordinate to two decimals with no trailing zeros."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def _count(value) -> int | None:
    """A stored count, or None when the value is not a non-negative integer."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _kind(row: dict, kind: str) -> int | None:
    kinds = row.get("kinds")
    if not isinstance(kinds, dict):
        return None
    return _count(kinds.get(kind, 0))


def _measure(row: dict, measure: str) -> int | None:
    """One day-grain figure of a daily row, or None when the row does not measure it."""
    if measure == "visits":
        return _count(row.get("visits"))
    if measure == "bundles":
        return _kind(row, "bundle")
    if measure == "files":
        return _kind(row, "file")
    if measure == "api":
        return _count(row.get("api_requests"))
    raise ValueError(measure)


def _day_handoffs(row: dict, handoff_months: set[str]) -> int | None:
    """A day's hand-off requests. The fold adds the day block on first use and the month block
    densely, so a day with no block is a measured 0 only inside a month that carries one."""
    block = row.get("handoffs")
    if isinstance(block, dict):
        return _count(block.get("requests"))
    return 0 if row["date"][:7] in handoff_months else None


def _dated_rows(rows) -> list[tuple[dt.date, dict]]:
    out = []
    for row in rows or ():
        if isinstance(row, dict):
            day = _iso_day(row.get("date"))
            if day is not None:
                out.append((day, row))
    return out


def _day_span(rows, last_folded) -> tuple[dt.date, dt.date] | None:
    """(first, last) calendar days the charts draw: from the oldest daily row to the data date, at
    most the latest 366 days. None when no row falls on or before the data date."""
    days = [day for day, _row in _dated_rows(rows)]
    last = _iso_day(last_folded) or (max(days) if days else None)
    held = [day for day in days if last is not None and day <= last]
    if not held:
        return None
    first = max(min(held), last - dt.timedelta(days=_MAX_DRAWN_DAYS - 1))
    return first, last


def _axis_top(peak: int) -> int:
    """The smallest of 10, 20, 50, 100, 200, 500 and so on that is at least `peak`."""
    scale = 10
    while True:
        for step in (1, 2, 5):
            if step * scale >= max(peak, 10):
                return step * scale
        scale *= 10


def _tick_text(value: int) -> str:
    return f"{value / 1000:g}K" if value >= 10000 else _n(value)


def _bar_width(slot: float) -> float:
    return round(min(slot, max(1.0, min(11.0, 0.6 * slot))), 1)


def _date_axis(first: dt.date, count: int, slot: float) -> list[tuple[float, str]]:
    """(x, label) for the date axis: every seventh day up to 45 days, otherwise the first day and each
    month's first day, dropping any label within the minimum gap of the last one kept."""
    if count <= 45:
        picks = range(0, count, 7)
    else:
        picks = [0] + [i for i in range(1, count) if (first + dt.timedelta(days=i)).day == 1]
    kept: list[tuple[float, str]] = []
    for i in picks:
        x = _LEFT + i * slot + slot / 2
        if kept and x - kept[-1][0] < _DATE_GAP:
            continue
        kept.append((x, _day_label(first + dt.timedelta(days=i))))
    return kept


def _day_chart(rows, measure: str, first: dt.date, last: dt.date, *,
               date_axis: bool | None = None) -> str:
    """One day-by-day column chart of `measure` over the calendar days first to last, as SVG.

    A day with no row keeps its hover slot and draws no column; so do an unmeasured day and a measured
    zero, each titled for what it is. Every value is printed in a title, so the chart never relies on
    colour or on the hover script."""
    if date_axis is None:
        date_axis = measure == _CHARTS[-1][0]
    first = max(first, last - dt.timedelta(days=_MAX_DRAWN_DAYS - 1))
    count = (last - first).days + 1
    if count < 1:
        return ""
    index: dict[dt.date, dict] = {}
    for day, row in _dated_rows(rows):
        index.setdefault(day, row)
    days = [first + dt.timedelta(days=i) for i in range(count)]
    values = [(_measure(index[day], measure) if day in index else None) for day in days]
    shown = [_NO_ROW if day not in index else (_NOT_MEASURED if v is None else _n(v))
             for day, v in zip(days, values)]
    measured = [v for v in values if v is not None]
    peak = max(measured) if measured else 0
    top = _axis_top(peak)
    slot = _SPAN / count
    bw = _bar_width(slot)
    height = _Y0 + (24 if date_axis else 4)
    width = max(640, 4 * count + 56)
    name = _CHART_NAMES[measure]
    title_id = f"u-c-{measure}-title"
    if peak > 0:
        at = days[values.index(peak)]
        summary = f"; peak {_n(peak)} on {_day_label(at)}"
    else:
        summary = ""
    title = f"{name} per day, {_date_long(first)} to {_date_long(last)}{summary}; table below"

    out = [f'<svg class="u-chart" viewBox="0 0 {_W} {height}" width="{width}" '
           f'style="min-width:{width}px;width:100%" role="img" aria-labelledby="{title_id}" '
           f'data-u-chart="{_esc(measure)}" data-u-name="{_esc(name)}">'
           f'<title id="{title_id}">{_esc(title)}</title>']
    for tick in (0, top // 2, top):
        y = _Y0 - _PLOT * tick / top
        out.append(f'<line class="{"u-axis" if tick == 0 else "u-grid"}" x1="{_LEFT}" '
                   f'x2="{_W - _RIGHT}" y1="{_u(y)}" y2="{_u(y)}"/>'
                   f'<text class="u-tick" x="{_LEFT - 8}" y="{_u(y + 3.5)}" '
                   f'text-anchor="end">{_esc(_tick_text(tick))}</text>')
    cls = _CHART_CLASSES[measure]
    peak_drawn = False
    for i, (day, v) in enumerate(zip(days, values)):
        if not v:
            continue
        x = _LEFT + i * slot + (slot - bw) / 2
        h = max(1.5, _PLOT * v / top)
        r = min(2.5, bw / 2, h)
        yt = _Y0 - h
        out.append(f'<path class="u-bar {cls}" data-i="{i}" d="M{_u(x)},{_Y0} V{_u(yt + r)} '
                   f'Q{_u(x)},{_u(yt)} {_u(x + r)},{_u(yt)} H{_u(x + bw - r)} '
                   f'Q{_u(x + bw)},{_u(yt)} {_u(x + bw)},{_u(yt + r)} V{_Y0} Z">'
                   f'<title>{_esc(_day_label(day))}: {_esc(shown[i])}</title></path>')
        if v == peak and not peak_drawn:
            peak_drawn = True
            out.append(f'<text class="u-vlabel" x="{_u(x + bw / 2)}" y="{_u(yt - 5)}" '
                       f'text-anchor="middle">{_esc(_n(v))}</text>')
    out.append(f'<line class="u-cross" x1="0" x2="0" y1="{_TOP - 6}" y2="{_Y0}" '
               f'visibility="hidden"/>')
    for i, day in enumerate(days):
        label = _day_label(day)
        out.append(f'<rect class="u-hit" x="{_u(_LEFT + i * slot)}" y="0" width="{_u(slot)}" '
                   f'height="{height}" data-i="{i}" data-day="{day.isoformat()}" '
                   f'data-label="{_esc(label)}" data-v="{_esc(shown[i])}" '
                   f'data-cx="{_u(_LEFT + i * slot + slot / 2)}">'
                   f'<title>{_esc(label)}: {_esc(shown[i])}</title></rect>')
    if date_axis:
        for x, label in _date_axis(first, count, slot):
            out.append(f'<text class="u-tick u-date" x="{_u(x)}" y="{_Y0 + 16}" '
                       f'text-anchor="middle">{_esc(label)}</text>')
    out.append("</svg>")
    return "".join(out)


def _cell(value: int | None) -> str:
    return _NOT_MEASURED if value is None else _n(value)


def _day_table(rows, monthly, first: dt.date, last: dt.date, *, labels_since=None) -> str:
    """The table twin of the charts: every daily row held, newest first, in a collapsed block. It
    lists rows the charts leave out when they cap their span, and is the keyboard and screen reader
    path to every value."""
    dated = sorted(_dated_rows(rows), key=lambda pair: pair[0], reverse=True)
    if not dated:
        return ""
    handoff_months = {m["month"] for m in monthly or ()
                      if isinstance(m, dict) and isinstance(m.get("month"), str)
                      and isinstance(m.get("handoffs"), dict)}
    held = {day for day, _row in dated}
    caption = "Every daily row held, newest first"
    if any(first + dt.timedelta(days=i) not in held for i in range((last - first).days + 1)):
        caption += "; days with no row are blank on the charts"
    since = _iso_day(labels_since)
    if since is not None and first <= since <= last:
        caption += f"; your own requests left out from {_day_label(since)}"
    head = "".join(f'<th scope="col">{name}</th>' for name in
                   ("Day", "Visits", "Bundles", "Station files", "Hand-offs", "API"))
    body = []
    for day, row in dated:
        cells = (_measure(row, "visits"), _measure(row, "bundles"), _measure(row, "files"),
                 _day_handoffs(row, handoff_months), _measure(row, "api"))
        body.append(f'<tr><th scope="row">{_esc(_date_long(day))}</th>'
                    + "".join(f"<td>{_esc(_cell(v))}</td>" for v in cells) + "</tr>")
    return ('<details class="u-twin"><summary>Show as a table</summary><div class="u-scroll">'
            f'<table><caption>{_esc(caption)}</caption><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div></details>')


def _state_visit_rows(stats) -> tuple[list[tuple[str, str, int | None]], int | None, int | None, bool]:
    """(rows, remainder, total, ok) for the state card, all in visits over all time.

    rows holds each named state or territory the fold counted, as (code, name, visits), biggest
    visits first; a state with no detail row has visits None and follows the measured ones. total is
    the Australian visits of the country detail, the figure the countries card prints. remainder is
    total less the named visits, so it covers the unattributed bucket and every day counted before
    the state table was loaded. ok is false when the named visits exceed total, or when state detail
    exists with no Australian detail; the card then withholds its rows. rows is empty when the fold
    counted no named state."""
    stats = stats if isinstance(stats, dict) else {}
    country = stats.get("by_country_detail")
    au = country.get("AU") if isinstance(country, dict) else None
    total = _count(au.get("visits")) if isinstance(au, dict) else None
    by_state = stats.get("by_state")
    by_state = by_state if isinstance(by_state, dict) else {}
    detail = stats.get("by_state_detail")
    detail = detail if isinstance(detail, dict) else {}
    order = [code for code, _name in _AU_STATE_NAMES]
    rows = []
    for code, name in _AU_STATE_NAMES:
        if not _count(by_state.get(code)):
            continue
        row = detail.get(code)
        rows.append((code, name, _count(row.get("visits")) if isinstance(row, dict) else None))
    if not rows:
        return [], None, total, True
    rows.sort(key=lambda r: (r[2] is None, -(r[2] or 0), order.index(r[0])))
    named = [v for _code, _name, v in rows if v is not None]
    if total is None:
        return rows, None, None, not named
    remainder = total - sum(named)
    return rows, remainder, total, remainder >= 0


# ------------------------------------------------------------------------------------------------
# The page.

_TITLE = "AusMT usage"

# The hover read-out, served at its own same-origin route. The page carries only the tag, as the
# last element of the body, never the script's text.
USAGE_JS = (Path(__file__).resolve().parent / "static" / "usage.js").read_text(encoding="utf-8")
_USAGE_JS_TAG = '<script src="/gateway/curator/usage.js" defer></script>'
_BODY_END = "</body></html>"
_DOCS_URL = ("https://ausmt.readthedocs.io/en/latest/introduction/usage-analytics/"
             "#reading-the-curator-usage-page")
_FORMAT_NAMES = {"mth5": "MTH5", "edi": "EDI", "emtfxml": "EMTF XML", "edi-zip": "EDI zip",
                 "xml-zip": "XML zip", "unattributed": "Unattributed"}
_WHO_ROWS = (("downloads", "Downloads"), ("visits", "Portal visits"), ("api", "API requests"),
             ("handoffs", "Time-series hand-offs"))
_AUDIENCE_NAMES = (("people", "People"), ("automated", "Automated"),
                   ("unclassified", "Unclassified"))
_TOP_SURVEYS = 10
_TOP_COUNTRIES = 8

# Light tokens and the rules that scope them to this page. Every selector sits under .shell.usage or
# names a class of this page's own prefix, so no other curator page changes; the shared head is left
# exactly as it is.
USAGE_CSS = (
    ":root{--page:#F1F2F1;--surface:#FFFFFF;--ink:#231F20;--ink2:#4d4b47;--muted:#6f6d67;"
    "--grid:#E7E7E4;--axis:#C6C6C1;--line:#DCDDDA;--brand:#282572;--rail:#282572;"
    "--rail-ink:#FFFFFF;--rail-on:#59C2AA;--link:#206B82;--s-visits:#3F88C8;--s-down:#2FA58B;"
    "--track:#EEF0EF;--up:#006300;--down:#B3261E;--note:#F7F4EC;--tip:#231F20;--tip-ink:#FFFFFF;"
    "--who-auto:#EF7256;--who-unc:#8E8C86}"
    "body{background:var(--page);color:var(--ink);"
    "font:15px/1.45 system-ui,-apple-system,\"Segoe UI\",Roboto,Arial,sans-serif}"
    ".shell.usage .rail{background:var(--rail);color:var(--rail-ink);border-right:0}"
    ".shell.usage .rail .grp{color:var(--rail-ink);opacity:.65}"
    ".shell.usage .rail a{color:var(--rail-ink)}"
    ".shell.usage .rail a:hover{background:rgba(255,255,255,.08)}"
    ".shell.usage .rail a.on{border-left-color:var(--rail-on);background:rgba(255,255,255,.10)}"
    ".shell.usage .main{min-width:0}"
    ".shell.usage .ctxbar{background:var(--surface);border-bottom:1px solid var(--line)}"
    ".shell.usage .crumb{color:var(--muted)}"
    ".shell.usage .crumb b{color:var(--ink)}"
    ".shell.usage .chip{background:var(--surface);border-color:var(--line);color:var(--muted)}"
    ".shell.usage .chip code{color:var(--ink)}"
    ".shell.usage a{color:var(--link)}"
    ".shell.usage .rail a{color:var(--rail-ink)}"
    ".shell.usage :focus-visible{outline:2px solid var(--link);outline-offset:2px}"
    ".shell.usage .rail a:focus-visible{outline-color:var(--rail-on)}"
    ".shell.usage h1{font-size:24px;font-weight:600;margin:0;color:var(--brand)}"
    ".shell.usage h2{font-size:16px;font-weight:600;margin:26px 0 10px;color:var(--brand)}"
    ".shell.usage h2 small{font-weight:400;color:var(--muted);font-size:13px;margin-left:6px}"
    ".shell.usage h3{font-size:13px;font-weight:600;margin:0 0 2px;color:var(--ink)}"
    ".shell.usage table{border-collapse:collapse;width:100%;font-size:13px}"
    ".shell.usage th,.shell.usage td{padding:6px 10px;border-bottom:1px solid var(--grid);"
    "text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap;color:var(--ink)}"
    ".shell.usage th[scope=row],.shell.usage th:first-child{text-align:left;font-weight:500}"
    ".shell.usage thead th{color:var(--muted);font-weight:600;font-size:12px}"
    ".shell.usage caption{text-align:left;color:var(--muted);font-size:12px;padding:4px 0}"
    ".shell.usage details{margin-top:10px;font-size:13px}"
    ".shell.usage summary{cursor:pointer;color:var(--ink2);font-size:13px}"
    ".shell.usage .k{color:var(--muted)}"
    ".shell.usage code{color:var(--ink)}"
    ".u-inner{max-width:1040px;margin:0 auto}"
    ".u-top{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 16px;margin-bottom:6px}"
    ".u-asof,.u-csv{color:var(--muted);font-size:13px}"
    ".u-asof.u-stale{color:var(--down);font-weight:600}"
    ".u-spacer{flex:1 1 auto}"
    ".u-card{background:var(--surface);border:1px solid var(--line);border-radius:4px;"
    "padding:14px 16px;min-width:0}"
    ".u-card-sub{font-weight:400;color:var(--muted);font-size:12px}"
    ".u-tiles{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:12px}"
    ".u-tile{background:var(--surface);border:1px solid var(--line);border-radius:4px;"
    "padding:12px 14px;min-width:0}"
    ".u-tile.wide{grid-column:span 2}"
    ".u-t-l{font-size:12px;color:var(--muted)}"
    ".u-t-v{font-size:30px;font-weight:600;line-height:1.15;margin-top:2px}"
    ".u-t-v.u-nm{font-size:15px;font-weight:400;color:var(--muted)}"
    ".u-t-d{font-size:12px;margin-top:2px;color:var(--muted)}"
    ".u-t-d.u-up{color:var(--up)}.u-t-d.u-down{color:var(--down)}"
    ".u-vh{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);"
    "white-space:nowrap}"
    ".u-split{list-style:none;margin:8px 0 0;padding:8px 0 0;border-top:1px solid var(--grid);"
    "font-size:12.5px;color:var(--ink2)}"
    ".u-sofar{font-size:13px;color:var(--ink2);margin:10px 2px 0}"
    ".u-sub,.u-foot,.u-who-note,.u-left{font-size:12px;color:var(--muted);margin:8px 0 0}"
    ".u-empty{font-size:13px;color:var(--muted);margin:8px 0}"
    ".u-warn{font-size:12.5px;color:var(--down);margin:8px 0 0}"
    ".u-who{margin-top:12px}"
    ".u-pills{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}"
    ".u-pill{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);"
    "border-radius:999px;padding:1px 9px;font-size:12px;background:var(--surface)}"
    ".u-sw{width:9px;height:9px;border-radius:2px;display:inline-block}"
    ".u-sw-p,.u-seg-p{background:var(--s-visits)}"
    ".u-sw-a,.u-seg-a{background:var(--who-auto)}"
    ".u-sw-u,.u-seg-u{background:var(--who-unc)}"
    ".u-who-row{display:grid;grid-template-columns:minmax(0,11em) minmax(4em,1fr) auto;gap:10px;"
    "align-items:center;padding:4px 0;font-size:13px}"
    ".u-who-n{color:var(--ink2)}"
    ".u-who-t{display:flex;height:10px;background:var(--track);border-radius:2px;overflow:hidden}"
    ".u-seg{display:block;height:10px;border-right:2px solid var(--surface)}"
    ".u-seg:last-child{border-right:0}"
    ".u-who-v{font-variant-numeric:tabular-nums;color:var(--ink2);font-size:12.5px}"
    ".u-scroll{overflow-x:auto;min-width:0}"
    ".u-twin .u-scroll{max-height:280px;overflow-y:auto}"
    ".u-mult{margin-top:10px}.u-mult:first-child{margin-top:4px}"
    ".u-chart{display:block;height:auto}"
    ".u-chart .u-grid{stroke:var(--grid);stroke-width:1}"
    ".u-chart .u-axis{stroke:var(--axis);stroke-width:1}"
    ".u-chart .u-tick{fill:var(--muted);font-size:10.5px;font-variant-numeric:tabular-nums}"
    ".u-chart .u-vlabel{fill:var(--ink2);font-size:10.5px;font-weight:600}"
    ".u-chart .u-bar.u-s-visits{fill:var(--s-visits)}.u-chart .u-bar.u-s-down{fill:var(--s-down)}"
    ".u-chart .u-bar.u-dim{opacity:.35}"
    ".u-chart .u-hit{fill:transparent}"
    ".u-chart .u-cross{stroke:var(--axis);stroke-width:1}"
    ".u-tip{position:fixed;z-index:10;pointer-events:none;background:var(--tip);"
    "color:var(--tip-ink);border-radius:4px;padding:7px 10px;font-size:12px;line-height:1.5;"
    "box-shadow:0 2px 8px rgba(0,0,0,.25);min-width:150px}"
    ".u-tip[hidden]{display:none}"
    ".u-grid2{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px}"
    ".u-ranked{margin-top:10px;font-size:13px}"
    ".u-rk{display:grid;grid-template-columns:minmax(0,13.5em) minmax(0,1fr) 4.6em;"
    "align-items:center;gap:10px;padding:3px 0}"
    ".u-rk-n{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--ink2)}"
    ".u-rk-t{display:block;height:10px;background:var(--track);border-radius:0 4px 4px 0}"
    ".u-rk-b{display:block;height:10px;border-radius:0 4px 4px 0}"
    ".u-rk-b.u-s-visits{background:var(--s-visits)}.u-rk-b.u-s-down{background:var(--s-down)}"
    ".u-rk-v{text-align:right;font-variant-numeric:tabular-nums}"
    ".u-rk.u-total{border-top:1px solid var(--grid);font-weight:600}"
    ".u-ch,.u-cr{display:grid;grid-template-columns:minmax(0,7.5em) minmax(0,1fr) minmax(0,1fr);"
    "gap:14px;align-items:center;padding:3px 0}"
    ".u-ch{color:var(--muted);font-size:12px;font-weight:600}"
    ".u-cc{display:grid;grid-template-columns:minmax(0,1fr) 4.6em;gap:8px;align-items:center}"
    ".u-notes{margin-top:22px}"
    ".u-notes ul{margin:8px 0 0;padding-left:18px;color:var(--ink2)}"
    ".u-health{font-size:12px;color:var(--muted);margin-top:14px}"
    ".u-dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#0CA30C;"
    "margin-right:6px}"
    ".u-dot.u-dot-warn{background:var(--down)}"
    "@media (max-width:900px){.shell.usage{display:block}"
    ".shell.usage .rail{flex-basis:auto;border-bottom:1px solid var(--line)}"
    ".u-tiles{grid-template-columns:repeat(3,minmax(0,1fr))}"
    ".u-tile.wide{grid-column:span 2}"
    ".u-grid2{grid-template-columns:1fr}}"
    "@media (max-width:600px){.u-tiles{grid-template-columns:minmax(0,1fr)}"
    ".u-tile.wide{grid-column:auto}"
    ".u-who-row{grid-template-columns:minmax(4em,1fr);gap:4px}}"
)


def _month_key(day: dt.date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def _prev_month(month: str) -> str:
    year, mon = int(month[:4]), int(month[5:7])
    return f"{year - 1:04d}-12" if mon == 1 else f"{year:04d}-{mon - 1:02d}"


def _is_month_end(day: dt.date) -> bool:
    return (day + dt.timedelta(days=1)).month != day.month


def _month_name(month: str) -> str:
    """'2026-10' as 'October'; an unparseable value reads as stored."""
    try:
        return _MONTH_NAMES[int(month[5:7]) - 1]
    except (ValueError, IndexError):
        return month


def _day_month(day: dt.date) -> str:
    """'1 December', the form used where the year is plain from context."""
    return f"{day.day} {_MONTH_NAMES[day.month - 1]}"


def _ordinal(n: int) -> str:
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _partly_counted(month: str, since: dt.date | None) -> dt.date | None:
    """The first counted day when counting began inside `month` after its first day, else None."""
    if since is None or _month_key(since) != month or since.day == 1:
        return None
    return since


def _nm(value: int | None) -> str:
    return _NOT_MEASURED if value is None else _n(value)


def _generated(value) -> str | None:
    """'19 Nov 2026, 03:39 UTC' for a stored generated_at, or None when it is not that shape."""
    if not isinstance(value, str):
        return None
    try:
        stamp = dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None
    return f"{_date_long(stamp.date())}, {stamp:%H:%M} UTC"


def _timer_hours(stats) -> float | None:
    raw = stats.get("timer_period_min") if isinstance(stats, dict) else None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw <= 0:
        return None
    return 2 * raw / 60


# ---- Month figures. Each returns None when the month does not measure the figure.

def _m_visits(row: dict) -> int | None:
    return _count(row.get("visits"))


def _m_downloads(row: dict) -> int | None:
    return _count(row.get("downloads"))


def _m_api(row: dict) -> int | None:
    return None if _month_has_no_detail(row) else _count(row.get("api_requests"))


def _m_countries(row: dict) -> int | None:
    countries = row.get("countries")
    if _month_has_no_detail(row) or not isinstance(countries, dict):
        return None
    return len([code for code in countries if code and code != "unknown"])


def _m_handoffs(row: dict) -> int | None:
    block = row.get("handoffs")
    return _count(block.get("requests")) if isinstance(block, dict) else None


def _m_kind(row: dict, kind: str) -> int | None:
    return None if _month_has_no_detail(row) else _kind(row, kind)


def _m_select(stats: dict, row: dict) -> tuple[int, int] | None:
    """(selection export files, exports at least) for a month, or None when the split misses it."""
    return _select_figures(row) if _select_measured(stats, row) else None


def _m_single(stats: dict, row: dict) -> int | None:
    """Station files less selection export files. The fold never crosses the two, so this reads
    not measured whenever either input is missing or the difference would be negative."""
    files, select = _m_kind(row, "file"), _m_select(stats, row)
    if files is None or select is None or files - select[0] < 0:
        return None
    return files - select[0]


def _m_volume(row: dict) -> str:
    return _NOT_MEASURED if _month_has_no_detail(row) else _human_bytes(row.get("download_bytes"))


class _Frame:
    """The dates every section reads: D the data date, T the last full month when held, P the month
    before it, C the month in progress, and the first counted day."""

    def __init__(self, stats: dict):
        self.stats = stats
        self.rows = _monthly_rows(stats)
        self.by_month = {row["month"]: row for row in self.rows}
        self.d = _iso_day(stats.get("last_folded_date"))
        self.since = _iso_day(stats.get("since"))
        self.t = self.p = self.c = None
        if self.d is not None:
            month = _month_key(self.d)
            self.t = month if _is_month_end(self.d) else _prev_month(month)
            self.c = None if _is_month_end(self.d) else month
            self.p = _prev_month(self.t)
        self.t_row = self.by_month.get(self.t) if self.t else None
        self.c_row = self.by_month.get(self.c) if self.c else None
        self.network = any(_count(row.get("nettype_days")) for row in self.rows)
        self.network_full = any(_count(row.get("nettype_full_days")) for row in self.rows)

    def partly(self, month: str | None) -> dt.date | None:
        return _partly_counted(month, self.since) if month else None


# ---- Section 1: header.

def _header(stats, stale: bool) -> str:
    day = _iso_day(stats.get("last_folded_date")) if isinstance(stats, dict) else None
    if day is None:
        asof = '<span class="u-asof">no data yet</span>'
    elif stale:
        asof = f'<span class="u-asof u-stale">data to {_esc(_date_long(day))}, stale</span>'
    else:
        asof = f'<span class="u-asof">data to {_esc(_date_long(day))}, updated nightly</span>'
    links = " · ".join(
        f'<a href="/gateway/curator/{path}">{name}</a>'
        for path, name in (("analytics.csv", "by month"), ("analytics-surveys.csv", "by survey"),
                           ("analytics-countries.csv", "by country")))
    return (f'<div class="u-top"><h1>Usage</h1>{asof}<span class="u-spacer"></span>'
            f'<span class="u-csv">Download CSV: {links}</span></div>')


# ---- Section 2: tiles for the last full month.

def _change(frame: _Frame, fn) -> str:
    """The change line of one tile, the last full month against the month before."""
    value = fn(frame.t_row)
    if value is None:
        return ""
    name = _month_name(frame.p)
    p_row = frame.by_month.get(frame.p)
    cls = ""
    if p_row is None:
        text = f"no row for {_esc(name)}"
    else:
        before = fn(p_row)
        if before is None:
            text = f"{_esc(name)} not measured"
        elif before == value:
            text = f"no change on {_esc(name)}"
        elif before == 0:
            text, cls = f"up from 0 in {_esc(name)}", " u-up"
        else:
            pct = round(abs(value - before) * 100 / before)
            up = value > before
            cls = " u-up" if up else " u-down"
            text = (f'<span aria-hidden="true">{"&#9650;" if up else "&#9660;"}</span>'
                    f'<span class="u-vh">{"up" if up else "down"}</span> {pct}% on {_esc(name)}')
        partly = frame.partly(frame.p)
        if partly is not None:
            text += f" (from {_esc(_day_label(partly))})"
    return f'<div class="u-t-d{cls}">{text}</div>'


def _tile(label: str, value: int | None, change: str, extra: str = "", wide: bool = False) -> str:
    shown = (f'<div class="u-t-v">{_esc(_n(value))}</div>' if value is not None
             else f'<div class="u-t-v u-nm">{_NOT_MEASURED}</div>')
    return (f'<div class="u-tile{" wide" if wide else ""}"><div class="u-t-l">{_esc(label)}</div>'
            f'{shown}{change}{extra}</div>')


def _downloads_split(stats: dict, row: dict) -> str:
    downloads = _m_downloads(row)
    if not downloads:
        return ""
    select = _m_select(stats, row)
    first = (f"{_n(select[0])} files in at least {_n(select[1])} selection exports"
             if select is not None else f"Selection exports: {_NOT_MEASURED}")
    bundles = _m_kind(row, "bundle")
    second = (f"{_n(bundles)} whole-survey bundles" if bundles is not None
              else f"Whole-survey bundles: {_NOT_MEASURED}")
    single = _m_single(stats, row)
    third = f"{_n(single)} single files" if single is not None else f"Single files: {_NOT_MEASURED}"
    return ('<ul class="u-split">' + "".join(f"<li>{_esc(line)}</li>"
                                             for line in (first, second, third)) + "</ul>")


def _tiles(frame: _Frame) -> str:
    row = frame.t_row
    partly = frame.partly(frame.t)
    small = ("last full month" if partly is None
             else f"last full month, counted from {_day_label(partly)}")
    tiles = (
        _tile("Portal visits", _m_visits(row), _change(frame, _m_visits))
        + _tile("Downloads", _m_downloads(row), _change(frame, _m_downloads),
                _downloads_split(frame.stats, row), wide=True)
        + _tile("API requests", _m_api(row), _change(frame, _m_api))
        + _tile("Countries, unknown left out", _m_countries(row), _change(frame, _m_countries))
        + _tile("Time-series hand-offs", _m_handoffs(row), _change(frame, _m_handoffs)))
    return (f'<h2>{_esc(_month_long(frame.t))} <small>{_esc(small)}</small></h2>'
            f'<div class="u-tiles">{tiles}</div>')


# ---- Section 3: the month in progress.

def _so_far(frame: _Frame) -> str:
    if frame.c is None:
        return ""
    name = _month_name(frame.c)
    row = frame.c_row
    if row is None:
        return f'<p class="u-sofar">{_esc(name)} so far: no counted requests yet.</p>'
    clauses = [f"{_nm(_m_visits(row))} visits", f"{_nm(_m_downloads(row))} downloads"]
    select = _m_select(frame.stats, row)
    if select is not None:
        clauses.append(f"{_n(select[0])} selection-export files" if select[0]
                       else "no selection exports")
    return (f'<p class="u-sofar">{_esc(name)} so far, to the {_ordinal(frame.d.day)}: '
            f'{_esc(", ".join(clauses))}.</p>')


def _months_head(frame: _Frame) -> str:
    """Sections 2 and 3, or the no-full-month heading when the last full month has no row."""
    if frame.d is None:
        return ""
    if frame.t_row is not None:
        return _tiles(frame) + _so_far(frame)
    empty = '<p class="u-empty">No full month yet.</p>'
    if frame.c is None:
        # The data date closes its month, so nothing is in progress to name in a heading.
        return empty
    return (f'<h2>{_esc(_month_long(frame.c))} <small>month in progress</small></h2>'
            + empty + _so_far(frame))


# ---- Section 4: who made the requests.

def _who_month(frame: _Frame) -> tuple[dict | None, bool]:
    """(month, in_progress): the last full month when labelled, else the month in progress when it
    carries labelled days, else (None, False)."""
    if frame.t_row is not None and _is_labelled(frame.t_row):
        return frame.t_row, False
    if frame.c_row is not None and _is_labelled(frame.c_row):
        return frame.c_row, True
    return None, False


def _who_placeholder(stats: dict) -> str:
    pills = "".join(f'<span class="u-pill"><span class="u-sw u-sw-{key[0]}"></span>{name}</span>'
                    for key, name in _AUDIENCE_NAMES)
    configured = _iso_day(stats.get("labels_configured_from"))
    note = (f"Measured from {_day_month(configured)}, when each figure above splits three ways with "
            "your own requests left out." if configured is not None else
            "Not measured yet; each figure above splits three ways once labels start.")
    return (f'<div class="u-card u-who"><h3>Who made the requests</h3>'
            f'<div class="u-pills">{pills}</div><p class="u-who-note">{_esc(note)}</p></div>')


def _who_row(month: dict, metric: str, name: str) -> str:
    labels = month.get("labels")
    if metric == "handoffs" and not (_has_handoff_class(month) and isinstance(labels, dict)
                                     and isinstance(labels.get("handoffs"), dict)):
        return (f'<div class="u-who-row"><span class="u-who-n">{_esc(name)}</span>'
                f'<span class="u-who-t"></span><span class="u-who-v">{_NOT_MEASURED}</span></div>')
    split = _audience_split(_label_counts(month, metric))
    total = sum(split.values())
    if total == 0:
        return (f'<div class="u-who-row"><span class="u-who-n">{_esc(name)}</span>'
                '<span class="u-who-t"></span><span class="u-who-v">none</span></div>')
    segments = "".join(
        f'<span class="u-seg u-seg-{key[0]}" style="width:{split[key] * 100 / total:.1f}%;'
        f'min-width:2px" data-n="{split[key]}"></span>'
        for key, _label in _AUDIENCE_NAMES if split[key])
    aria = ", ".join(f"{label.lower() if i else label} {_n(split[key])}"
                     for i, (key, label) in enumerate(_AUDIENCE_NAMES))
    shown = " · ".join(f"{label} {_n(split[key])}" for key, label in _AUDIENCE_NAMES)
    return (f'<div class="u-who-row"><span class="u-who-n">{_esc(name)}</span>'
            f'<span class="u-who-t" role="img" aria-label="{_esc(aria)}">{segments}</span>'
            f'<span class="u-who-v">{_esc(shown)}</span></div>')


def _who_warning(month: dict, network: bool) -> str:
    days, labelled = _count(month.get("days")) or 0, _count(month.get("label_days")) or 0
    nettype = _count(month.get("nettype_days")) or 0
    full = _count(month.get("nettype_full_days")) or 0
    listed = _count(month.get("operator_list_days")) or 0
    clauses = []
    if labelled < days:
        clauses.append(f"labels on {labelled} of {days} days, rest include your requests")
    if network and nettype < labelled:
        clauses.append(f"no network type {labelled - nettype} days")
    if listed < labelled:
        clauses.append(f"no operator list {labelled - listed} days")
    if network and full < nettype:
        clauses.append(f"hosting-only {nettype - full} days")
    if not clauses:
        return ""
    return f'<p class="u-warn">Warning: {_esc("; ".join(clauses))}.</p>'


def _who_detail(month: dict, network: bool) -> str:
    counts = {metric: _label_counts(month, metric) for metric, _name in _WHO_ROWS}
    handoffs = _has_handoff_class(month)
    groups = [(0, _CLIENT_NAMES)] + ([(1, _NETTYPE_NAMES)] if network else [])
    body = []
    for index, names in groups:
        keys = [key for key, _name in names]
        sums = {metric: _by_label(counts[metric], index, keys) for metric, _name in _WHO_ROWS}
        for key, name in names:
            cells = "".join(
                f"<td>{_NOT_MEASURED if metric == 'handoffs' and not handoffs else _n(sums[metric][key])}"
                "</td>" for metric, _name in _WHO_ROWS)
            body.append(f'<tr><th scope="row">{_esc(name)}</th>{cells}</tr>')
    head = "".join(f'<th scope="col">{name}</th>'
                   for name in ("Label", "Downloads", "Visits", "API", "Hand-offs"))
    summary = "By client and network" if network else "By client"
    return (f'<details class="u-who-detail"><summary>{summary}</summary><div class="u-scroll">'
            f'<table><caption>{_esc(_month_long(month["month"]))}, requests by label</caption>'
            f'<thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div></details>')


def _credit(frame: _Frame) -> str:
    """The hosting range credit, shown wherever a network type figure can appear."""
    if not frame.network:
        return ""
    out = ('<p class="u-foot">Hosting ranges: X4BNet lists_vpn, built in part from IPLocate.io data '
           '(CC BY-SA 4.0).</p>')
    if frame.network_full:
        out += ('<p class="u-foot">Network types: PeeringDB.</p>'
                '<p class="u-foot">Prefix to network: iptoasn.com.</p>')
    return out


def _who_card(frame: _Frame) -> str:
    month, in_progress = _who_month(frame)
    if month is None:
        return _who_placeholder(frame.stats)
    heading = ("Who made the requests" if not in_progress
               else f"Who made the requests, {_month_name(month['month'])} so far")
    rows = "".join(_who_row(month, metric, name) for metric, name in _WHO_ROWS)
    left = (f'<p class="u-left">Left out: your own requests {_n(_block_sum(month, "operator"))}, '
            f'declared crawlers {_n(_block_sum(month, "crawler_excluded"))}.</p>')
    return (f'<div class="u-card u-who"><h3>{_esc(heading)}</h3>{rows}{left}'
            + _who_warning(month, frame.network) + _who_detail(month, frame.network)
            + _credit(frame) + '</div>')


# ---- Section 5: day by day.

def _day_by_day(frame: _Frame) -> str:
    daily = frame.stats.get("daily")
    span = _day_span(daily, frame.stats.get("last_folded_date"))
    if span is None:
        return '<h2>Day by day</h2><p class="u-empty">No daily rows yet.</p>'
    first, last = span
    small = f"{_date_long(first)} to {_date_long(last)}"
    labels_since = _iso_day(frame.stats.get("labels_since"))
    if labels_since is not None and first <= labels_since <= last:
        small += f"; your own requests left out from {_day_label(labels_since)}"
    charts = "".join(f'<div class="u-mult"><h3>{_esc(name)}</h3>{_day_chart(daily, key, first, last)}'
                     '</div>' for key, name, _cls in _CHARTS)
    twin = _day_table(daily, frame.rows, first, last, labels_since=frame.stats.get("labels_since"))
    return (f'<h2>Day by day <small>{_esc(small)}</small></h2>'
            f'<div class="u-card u-days"><div class="u-scroll">{charts}</div>{twin}'
            '<div class="u-tip" id="u-tip" hidden aria-hidden="true"></div></div>')


# ---- Section 6: month by month.

def _month_table(frame: _Frame) -> str:
    if not frame.rows:
        return ('<h2>Month by month</h2>'
                '<p class="u-empty">No months yet; the first fills in at the next nightly count.</p>')
    stats = frame.stats
    head = "".join(f'<th scope="col">{name}</th>' for name in (
        "Month", "Visits", "Downloads", "Export files",
        'Exports <span class="k">at least</span>', "Bundles", "Single files", "API", "Hand-offs",
        "Countries", "Volume"))
    body, unmeasured = [], False
    for row in reversed(frame.rows):
        month = row["month"]
        label = _month_long(month)
        if month == frame.c and frame.d is not None:
            label += f" (to {_ordinal(frame.d.day)})"
        partly = frame.partly(month)
        if partly is not None:
            label += f" (from {_ordinal(partly.day)})"
        select = _m_select(stats, row)
        cells = [_nm(_m_visits(row)), _nm(_m_downloads(row)),
                 _nm(select[0] if select else None), _nm(select[1] if select else None),
                 _nm(_m_kind(row, "bundle")), _nm(_m_single(stats, row)), _nm(_m_api(row)),
                 _nm(_m_handoffs(row)), _nm(_m_countries(row)), _m_volume(row)]
        unmeasured = unmeasured or _NOT_MEASURED in cells
        body.append(f'<tr><th scope="row">{_esc(label)}</th>'
                    + "".join(f"<td>{_esc(cell)}</td>" for cell in cells) + "</tr>")
    caption = ""
    if unmeasured:
        # A seam is named only when a shown month falls before it.
        clauses = []
        detail = _iso_day(stats.get("detail_since"))
        if detail is not None and any(_month_has_no_detail(row) for row in frame.rows):
            clauses.append(f"detail from {_date_long(detail)}")
        select_since = _iso_day(stats.get("select_since"))
        if select_since is not None and not all(_select_measured(stats, row) for row in frame.rows):
            clauses.append(f"selection split from {_date_long(select_since)}")
        caption = ("Not measured means counted before that figure existed"
                   + (": " + ", ".join(clauses) if clauses else "") + ".")
        caption = f'<p class="u-sub">{_esc(caption)}</p>'
    return ('<h2>Month by month</h2><div class="u-card u-scroll"><table>'
            '<caption class="u-vh">Every retained month, newest first</caption>'
            f'<thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>' + caption)


# ---- Section 7: what and where.

def _bar(value: int, top: int, cls: str) -> str:
    width = value * 100 / top if top else 0
    inner = f'<span class="u-rk-b {cls}" style="width:{width:.1f}%"></span>' if value else ""
    return f'<span class="u-rk-t">{inner}</span>'


def _ranked(rows: list[tuple[str, int | None]], cls: str, *, total: tuple[str, int | None] | None
            = None, fixed: tuple[str, int | None] | None = None) -> str:
    """Ranked bars as spans, the value printed beside every bar. A value of None reads not
    measured and draws no bar. Row names come from the data and are marked u-dl; `fixed` is one
    more barred row whose name is page wording, and `total` closes the list without a bar."""
    marked = [(name, value, True) for name, value in rows]
    if fixed is not None:
        marked.append((fixed[0], fixed[1], False))
    top = max([v for _name, v, _dl in marked if v is not None] or [0])
    out = []
    for name, value, data_label in marked:
        bar = _bar(value, top, cls) if value is not None else '<span class="u-rk-t"></span>'
        label = f'<span class="u-dl">{_esc(name)}</span>' if data_label else _esc(name)
        out.append(f'<div class="u-rk"><span class="u-rk-n">{label}</span>{bar}'
                   f'<span class="u-rk-v">{_esc(_nm(value))}</span></div>')
    if total is not None:
        out.append(f'<div class="u-rk u-total"><span class="u-rk-n">{_esc(total[0])}</span>'
                   f'<span></span><span class="u-rk-v">{_esc(_nm(total[1]))}</span></div>')
    return '<div class="u-ranked">' + "".join(out) + "</div>"


def _card(title: str, sub: str, body: str) -> str:
    sub_html = f'<div class="u-card-sub">{_esc(sub)}</div>' if sub else ""
    return f'<div class="u-card"><h3>{_esc(title)}</h3>{sub_html}{body}</div>'


def _surveys_card(stats: dict) -> str:
    by_survey = (stats.get("downloads") or {}).get("by_survey") if isinstance(
        stats.get("downloads"), dict) else None
    by_survey = by_survey if isinstance(by_survey, dict) else {}
    rows = []
    for name, value in by_survey.items():
        if not isinstance(name, str):
            continue
        n = _count(value.get("downloads")) if isinstance(value, dict) else _count(value)
        if n:
            rows.append((name, n))
    rows.sort(key=lambda r: (-r[1], r[0]))
    held = len([name for name in by_survey if isinstance(name, str)])
    if not rows:
        return _card("Most downloaded surveys", "",
                     '<p class="u-empty">No attributed downloads yet.</p>')
    sub = f"files and bundles, top {min(_TOP_SURVEYS, len(rows))} of {held}"
    return _card("Most downloaded surveys", sub, _ranked(rows[:_TOP_SURVEYS], "u-s-down"))


def _detail_figure(detail: dict, code: str, key: str) -> int | None:
    row = detail.get(code)
    return _count(row.get(key)) if isinstance(row, dict) else None


def _countries_card(stats: dict) -> str:
    countries = stats.get("countries")
    countries = countries if isinstance(countries, dict) else {}
    ranked = sorted(((code, _count(n) or 0) for code, n in countries.items()
                     if isinstance(code, str) and code and code != "unknown"),
                    key=lambda r: (-r[1], r[0]))
    if not ranked:
        return _card("Countries", "", '<p class="u-empty">No country figures yet.</p>')
    detail = stats.get("by_country_detail")
    detail = detail if isinstance(detail, dict) else {}
    top = ranked[:_TOP_COUNTRIES]
    sub = f"top {len(top)} of {len(ranked)}"
    au = _detail_figure(detail, "AU", "visits")
    all_visits = sum(_detail_figure(detail, code, "visits") or 0 for code in detail)
    if au is not None and all_visits > 0:
        sub += f"; Australia is {round(au * 100 / all_visits)}% of visits"
    visits = {code: _detail_figure(detail, code, "visits") for code, _n_ in top}
    downloads = {code: _detail_figure(detail, code, "downloads") for code, _n_ in top}
    vmax = max([v for v in visits.values() if v is not None] or [0])
    dmax = max([v for v in downloads.values() if v is not None] or [0])

    def cell(value, peak, cls):
        bar = _bar(value, peak, cls) if value is not None else '<span class="u-rk-t"></span>'
        return f'<span class="u-cc">{bar}<span class="u-rk-v">{_esc(_nm(value))}</span></span>'

    out = ['<div class="u-ranked"><div class="u-ch"><span></span><span>Visits</span>'
           '<span>Downloads</span></div>']
    for code, _n_ in top:
        out.append(f'<div class="u-cr"><span class="u-rk-n"><span class="u-dl">'
                   f'{_esc(countrynames.country_name(code))}</span></span>'
                   f'{cell(visits[code], vmax, "u-s-visits")}'
                   f'{cell(downloads[code], dmax, "u-s-down")}</div>')
    out.append("</div>")
    shown = {code for code, _n_ in top}
    rest = [code for code in detail if code not in shown and isinstance(detail.get(code), dict)]
    if rest:
        v = sum(_detail_figure(detail, code, "visits") or 0 for code in rest)
        d = sum(_detail_figure(detail, code, "downloads") or 0 for code in rest)
        others = len(ranked) - len(top)
        unplaced = any(code == "unknown" or code not in countries for code in rest)
        if others:
            who = f"The other {others} {'country' if others == 1 else 'countries'}"
            who += " and unplaced requests" if unplaced else ""
        else:
            who = "Unplaced requests"
        out.append(f'<p class="u-foot">{_esc(who)}: {_n(v)} visits, {_n(d)} downloads.</p>')
    return _card("Countries", sub, "".join(out))


def _states_card(stats: dict) -> str:
    rows, remainder, total, ok = _state_visit_rows(stats)
    title, sub = "Australian visits by state", "visits, all time"
    if not rows:
        return _card(title, sub, '<p class="u-empty">Not measured yet.</p>')
    if not ok:
        return _card(title, sub, '<p class="u-empty">Not reconciled with the Australian total; the '
                                 'CSV carries the state figures.</p>')
    ranked = [(name, visits) for _code, name, visits in rows]
    fixed = ("Not placed in a state", remainder) if remainder is not None else None
    return _card(title, sub, _ranked(ranked, "u-s-visits", fixed=fixed, total=("Australia", total)))


def _formats_card(frame: _Frame) -> str:
    if frame.t_row is not None:
        row, sub = frame.t_row, f"downloads in {_month_long(frame.t)}"
    elif frame.c_row is not None:
        row, sub = frame.c_row, f"{_month_long(frame.c)} so far"
    else:
        return _card("Formats", "", '<p class="u-empty">No months yet.</p>')
    formats = row.get("formats")
    if _month_has_no_detail(row) or not isinstance(formats, dict):
        return _card("Formats", sub, f'<p class="u-empty">Formats {_NOT_MEASURED} this month.</p>')
    ranked = sorted(((_FORMAT_NAMES.get(key, str(key)), _count(n)) for key, n in formats.items()
                     if _count(n)), key=lambda r: (-r[1], r[0]))
    if not ranked:
        return _card("Formats", sub, '<p class="u-empty">No downloads this month.</p>')
    return _card("Formats", sub, _ranked(ranked, "u-s-down"))


def _what_and_where(frame: _Frame) -> str:
    stats = frame.stats
    parts = []
    if frame.since is not None:
        parts.append(f"since counting began in {_month_long(_month_key(frame.since))}")
    labels_since = _iso_day(_labels_since(stats))
    parts.append(f"your own requests left out from {_date_long(labels_since)}"
                 if labels_since is not None else "your own requests included")
    return (f'<h2>What and where <small>{_esc("; ".join(parts))}</small></h2>'
            '<div class="u-grid2">' + _surveys_card(stats) + _countries_card(stats)
            + _states_card(stats) + _formats_card(frame) + '</div>')


# ---- Section 8: notes and the health line.

def _notes(stats) -> list[str]:
    since = _iso_day(_labels_since(stats)) if isinstance(stats, dict) else None
    fourth = (f"Declared crawlers are left out, and your own requests are left out from "
              f"{_date_long(since)}." if since is not None else
              "Declared crawlers are left out; your own requests are counted until labels start.")
    return [
        "Addresses are cut to the network before anything is written; no address or user-agent is "
        "stored, and nothing here identifies a person.",
        "A download is one file, counted once per day per masked network; a visit is one start of "
        "the portal.",
        "A selection export fetches each station's file separately, so one export can be thousands "
        "of files; the export count is a floor.",
        fourth,
        "API requests are fetches of the documented machine-readable files; hand-offs are requests "
        "to NCI THREDDS, not completed transfers.",
        "Places are counted by month or overall, never by day; state is the finest place, and no "
        "country is named beside a survey.",
        "People is a floor: unclassified requests may include people.",
        "A figure counted before its rule existed reads not measured, never zero; nothing is "
        "backfilled.",
    ]


def _health(stats, stale: bool) -> str:
    """The health line and at most one warning. The archive date is read only as a YYYY-MM-DD day."""
    if not isinstance(stats, dict):
        line = "Data to: none · last count: never"
        warning = "Warning: no count has finished yet; check the ausmt-stats timer."
    else:
        day = _iso_day(stats.get("last_folded_date"))
        through = _iso_day(stats.get("archive_through"))
        generated = _generated(stats.get("generated_at"))
        line = " · ".join((
            f"Data to {_date_long(day)}" if day is not None else "Data to: none",
            f"last count {generated}" if generated else "last count: never",
            f"archive written to {_date_long(through)}" if through is not None
            else "archive written to: not recorded"))
        behind = through is None or (day is not None and through < day)
        hours = _timer_hours(stats)
        late = (f"Warning: no count has finished for over {hours:g} hours; check the ausmt-stats "
                "timer." if hours is not None else
                "Warning: no count has finished yet; check the ausmt-stats timer.")
        where = ("the archive date is not recorded" if through is None
                 else f"the archive stops at {_date_long(through)}")
        if stale and behind:
            warning = f"Warning: no count on time, and {where}."
        elif stale:
            warning = late
        elif behind:
            warning = (f"Warning: {where}; see the fold journal." if through is None else
                       f"Warning: {where}; later days are not in the permanent record, see the "
                       "fold journal.")
        else:
            warning = ""
    dot = "u-dot u-dot-warn" if warning else "u-dot"
    return (f'<div class="u-health"><span class="{dot}"></span>{_esc(line)}</div>'
            + (f'<p class="u-warn">{_esc(warning)}</p>' if warning else ""))


def _notes_card(stats, stale: bool) -> str:
    items = "".join(f"<li>{_esc(note)}</li>" for note in _notes(stats))
    return ('<div class="u-card u-notes"><details><summary>How these numbers are counted</summary>'
            f'<ul>{items}</ul></details>'
            f'<p class="u-foot"><a href="{_DOCS_URL}">Full method and every counting rule</a></p>'
            + _health(stats, stale) + '</div>')


def render_usage_page(*, stats, stats_stale: bool, nav) -> str:
    """The Usage page over one parsed stats.json, or the empty state when there is none. Stale data
    renders in full with the header marker and the health warning, never as current."""
    if not isinstance(stats, dict):
        body = (_header(None, True)
                + '<div class="u-card"><p class="u-empty">No usage figures yet: the nightly count '
                  'has not written its file.</p></div>'
                + _notes_card(None, True))
    else:
        frame = _Frame(stats)
        body = (_header(stats, stats_stale) + _months_head(frame) + _who_card(frame)
                + _day_by_day(frame) + _month_table(frame) + _what_and_where(frame)
                + _notes_card(stats, stats_stale))
    page = _shell(_TITLE, f'<div class="u-inner">{body}</div>', nav=nav,
                  extra_head=f"<style>{USAGE_CSS}</style>", page_class="usage")
    head, end, tail = page.rpartition(_BODY_END)
    if not end or tail.strip():
        return page
    return head + _USAGE_JS_TAG + _BODY_END + tail
