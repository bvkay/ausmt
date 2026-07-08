"""Server-rendered status page (design §6). stdlib string.Template, no framework, no JS, inline
style in the portal palette. Reports are shown verbatim MINUS absolute paths.

Two hard rules enforced here:
  1. Submitter fields (name/email/orcid) are NEVER rendered — a leaked status URL must not leak PII
     (design §6). The render function is not even given the submitter fields.
  2. Everything interpolated from a report is HTML-escaped (html.escape) — reports derive from
     submitted bytes and must not be able to inject markup into the operator/submitter's browser.
"""
from __future__ import annotations

import html
import re
from string import Template

from . import states

# Portal palette (grepped from portal/*.html): navy surfaces, orange accent, state colours.
_PALETTE = {
    "bg": "#13202B", "panel": "#1B2C3A", "ink": "#E8EDF1", "muted": "#8FA3B0",
    "accent": "#E0782F", "ok": "#5BAE6A", "warn": "#D9A23B", "bad": "#A85454",
}

_STATE_COLOUR = {
    states.RECEIVED: _PALETTE["muted"],
    states.SCANNED: _PALETTE["accent"],
    states.VALIDATED: _PALETTE["ok"],
    states.QUARANTINED: _PALETTE["warn"],
    states.REJECTED_AV: _PALETTE["bad"],
    # C11 curator-outcome states shown to the submitter.
    states.PUBLISHING: _PALETTE["accent"],
    states.PUBLISHED: _PALETTE["ok"],
    states.PUBLISH_FAILED: _PALETTE["warn"],
    states.RETURNED: _PALETTE["warn"],
    states.REJECTED: _PALETTE["bad"],
}

_STATE_BLURB = {
    states.RECEIVED: "Received. Virus scan pending — the submission advances once the scanner reports.",
    states.SCANNED: "Scanned clean. Validation and preview build are queued.",
    states.VALIDATED: "Validated. The package passed the validator and built a preview. Awaiting curator review.",
    states.QUARANTINED: "Quarantined. Validation or the preview build did not complete cleanly.",
    states.REJECTED_AV: "Rejected. The uploaded archive matched a virus signature and was deleted.",
    # C11: PUBLISHED means committed to the survey repository, NOT yet on the live map — do not
    # overstate it (design §5). Since C40 the serve-reconcile timer runs that rebuild automatically.
    states.PUBLISHING: "Publishing. The curator approved this submission; it is being committed.",
    states.PUBLISHED: ("Published. Committed to the AusMT survey repository. It will appear on the "
                       "live map after the next automatic data rebuild (typically within about "
                       "15 minutes)."),
    states.PUBLISH_FAILED: "Publish failed. The commit did not complete; the curator will retry.",
    states.RETURNED: "Returned. The curator asked for changes — see the note below; resubmit a revised package.",
    states.REJECTED: "Rejected. The curator declined this submission — see the note below.",
}

# Strip anything that looks like an absolute path from report text before display (design §6): a
# posix /a/b or a windows C:\a\b. Belt-and-braces — the runner already writes relative refs, but
# reports embed tool output we do not control.
_ABS_POSIX = re.compile(r"(?<![\w])/(?:[\w.\-]+/)*[\w.\-]+")
_ABS_WIN = re.compile(r"[A-Za-z]:\\(?:[\w.\- ]+\\)*[\w.\- ]+")

# The ONLY states whose last-transition note renders publicly (C11b Amendment A1 / review finding 2):
# these are the states where the note is INTENDED for the submitter — the AV verdict, the quarantine
# cause, the curator's return/reject explanation. Publish-cycle reasons (PUBLISHING / PUBLISHED /
# PUBLISH_FAILED) are curator/audit/internal text — the PII-ACK acknowledgement prefix with its
# flagged file names, raw curator decision notes, git failure output — and must NEVER render on the
# public page. Before this gate, ANY state with a truthy note rendered it, so the PII-ACK audit
# reason leaked to the submitter during the real PUBLISHING window; gating by state also closes the
# pre-existing leak of raw curator notes and git internals (a deliberate strict improvement). The DB
# reason itself is unchanged — it stays the audit channel; only the public render is gated.
_PUBLIC_NOTE_STATES = frozenset({
    states.QUARANTINED, states.REJECTED_AV, states.RETURNED, states.REJECTED,
})


def _strip_abs_paths(text: str) -> str:
    text = _ABS_WIN.sub("[path]", text)
    text = _ABS_POSIX.sub("[path]", text)
    return text


_PAGE = Template(
    """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AusMT submission $sid_short</title>
<style>
 body{margin:0;background:$bg;color:$ink;font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif}
 .wrap{max-width:820px;margin:0 auto;padding:2rem 1.25rem}
 h1{font-size:1.15rem;font-weight:600;margin:0 0 .25rem}
 .sub{color:$muted;font-size:.85rem;margin:0 0 1.5rem}
 .badge{display:inline-block;padding:.2rem .6rem;border-radius:999px;font-weight:600;
   font-size:.8rem;color:$bg;background:$state_colour}
 .panel{background:$panel;border-radius:8px;padding:1rem 1.25rem;margin:1rem 0}
 .blurb{color:$ink;margin:.75rem 0 0}
 table{border-collapse:collapse;width:100%;font-size:.85rem;overflow-x:auto;display:block}
 th,td{text-align:left;padding:.35rem .5rem;border-bottom:1px solid #2E4254;vertical-align:top}
 th{color:$muted;font-weight:600}
 pre{white-space:pre-wrap;word-break:break-word;background:$bg;padding:.75rem;border-radius:6px;
   font-size:.8rem;color:$muted;overflow-x:auto}
 .k{color:$muted}
</style></head>
<body><div class="wrap">
 <h1>Submission status</h1>
 <p class="sub">id $sid_short · updated $updated</p>
 <p><span class="badge">$state</span></p>
 <p class="blurb">$blurb</p>
 $sections
</div></body></html>
"""
)


def _esc(value) -> str:
    return html.escape(str(value), quote=True)


def _validator_section(report: dict) -> str:
    # The real validator (ausmt-surveys/_validation/validate_survey.py --json) writes {"items":[...]}
    # (review #8); accept that FIRST, then the historical checks/rows shapes so a shape change on
    # either side degrades gracefully rather than silently dropping the whole table. Every rendered
    # cell is html.escaped AND absolute-path-stripped (design §6 — a leaked status URL must not leak
    # a server path; keeping the strip on these rows is why fixing the key does not re-open a leak).
    rows = report.get("items") or report.get("checks") or report.get("rows") or []
    if not isinstance(rows, list) or not rows:
        return ""
    body = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        level = _esc(_strip_abs_paths(str(row.get("level") or row.get("status") or "")))
        name = _esc(_strip_abs_paths(str(row.get("name") or row.get("check") or row.get("id") or "")))
        msg = _esc(_strip_abs_paths(str(
            row.get("message") or row.get("detail") or row.get("msg") or "")))
        body.append(f"<tr><td>{level}</td><td>{name}</td><td>{msg}</td></tr>")
    if not body:
        return ""
    return ("<div class=\"panel\"><h1>Validator</h1><table><tr><th>Level</th><th>Check</th>"
            "<th>Message</th></tr>" + "".join(body) + "</table></div>")


def _preview_section(summary: dict) -> str:
    if not summary:
        return ""
    items = []
    for key in ("station_count", "types", "coord_flags", "warnings"):
        if key in summary:
            # Strip absolute paths from preview values too (review #11) — warnings can echo a build
            # path; the strip keeps design §6's "no absolute paths in the status page" invariant
            # uniform across validator rows, the AV note, AND preview values.
            value = _esc(_strip_abs_paths(str(summary[key])))
            items.append(f"<tr><td class=\"k\">{_esc(key)}</td><td>{value}</td></tr>")
    if not items:
        return ""
    return "<div class=\"panel\"><h1>Preview summary</h1><table>" + "".join(items) + "</table></div>"


def _av_section(reason: str) -> str:
    if not reason:
        return ""
    return f"<div class=\"panel\"><h1>Notes</h1><pre>{_esc(_strip_abs_paths(reason))}</pre></div>"


def render(*, submission_id: str, state: str, updated_utc: str,
           validator_report: dict | None = None, preview_summary: dict | None = None,
           note: str = "") -> str:
    """Render the status HTML. Deliberately takes NO submitter fields (design §6)."""
    sections = ""
    if state in (states.VALIDATED, states.QUARANTINED):
        sections += _validator_section(validator_report or {})
        sections += _preview_section(preview_summary or {})
    if state in _PUBLIC_NOTE_STATES:
        sections += _av_section(note)
    return _PAGE.substitute(
        bg=_PALETTE["bg"], panel=_PALETTE["panel"], ink=_PALETTE["ink"], muted=_PALETTE["muted"],
        state_colour=_STATE_COLOUR.get(state, _PALETTE["muted"]),
        sid_short=_esc(submission_id[:10]),
        updated=_esc(updated_utc),
        state=_esc(state),
        blurb=_esc(_STATE_BLURB.get(state, "")),
        sections=sections,
    )
