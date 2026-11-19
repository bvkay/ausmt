"""The curator Usage page.

The day-by-day charts and their table twin are pure functions of the daily rows in stats.json. A daily
row may carry more than the page shows; only its date, visits, bundles, station files, API requests
and hand-off requests are ever read here, so no place, label, survey or format reaches the day grain.
Every chart is server-drawn SVG and reads the same without any script.
"""
from __future__ import annotations

import datetime as dt
import html

from .curatorpage import _AU_STATE_NAMES

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
