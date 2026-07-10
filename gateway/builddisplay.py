"""Build-id DISPLAY shortener for the curator chrome (C43 S2a-5, owner feedback from the live box).

PURE FUNCTIONS, no I/O — the AUTHORITATIVE specification of how a build id is shortened for display,
so the transform is unit-testable server-side (the sanctioned "test at the seam" option, same as
phaseqc). The browser-side CONTEXT_BAR_JS (drift chip) and SERVE_PANEL_JS (Served-build card) mirror
this exact algorithm; this module is the single source of truth a pin exercises, and a source-level
assertion checks both JS constants embed the mirror.

THE FORMAT (engine build_identity, build_portal.py:1553):
    build_id = "<engine_commit>-<source_commit>-<generated_iso>"
e.g. "252a96fed49c74477ed24e159e6689c8100fcb4c-b898f26-2026-07-10T06:00:39.252632+00:00"

DISPLAY-ONLY (never mutates the underlying data): show "<source short-sha> · <HH:MM> UTC"
(e.g. "b898f26 · 06:00 UTC"), with the FULL id available on hover via a title attribute. The
timestamp barrel itself contains '-' (the date) and '+' (the tz offset), so the id is NOT split on
'-'; it is parsed structurally (engine barrel, source barrel, then the ISO timestamp from its 'T').

DEFENSIVE: any id that does not match the expected three-barrel shape falls back to the id VERBATIM —
never hide information on an unexpected format (an operator must always be able to read the raw id)."""
from __future__ import annotations

import re

# engine-sha barrel '-' source-sha barrel '-' ISO timestamp (starting YYYY-MM-DDTHH:MM:SS...).
# The engine/source barrels are hex shas or the literal 'unknown' (build_identity's None fallback);
# the timestamp is captured whole (it may carry fractional seconds + a +HH:MM / Z tz suffix).
_BUILD_ID_RE = re.compile(
    r"^(?P<engine>[0-9a-fA-F]+|unknown)-(?P<source>[0-9a-fA-F]+|unknown)-"
    r"(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[0-9.]*(?:Z|[+-]\d{2}:?\d{2})?)$"
)

_SOURCE_SHORT_LEN = 7


def short_build_id(build_id) -> str:
    """The short DISPLAY form of a build id: '<source short-sha> · <HH:MM> UTC'. Falls back to the id
    VERBATIM (as a string) when it does not match the expected engine-source-timestamp shape, or when
    build_id is falsy/None (returns '' for None so a caller can decide the placeholder).

    'UTC' is a LABEL, not a conversion: the engine writes `generated` as an aware UTC-or-offset ISO
    timestamp; we display its clock HH:MM and tag it UTC (the box runs UTC and the engine stamps
    timezone.utc). If a future build ever stamped a non-UTC offset, the HH:MM would be that offset's
    clock time labelled UTC — acceptable for an at-a-glance chip; the full id on hover carries the
    exact offset, and the verbatim fallback covers any shape this regex does not recognise."""
    if not build_id:
        return ""
    s = str(build_id)
    m = _BUILD_ID_RE.match(s)
    if not m:
        return s  # unexpected shape => verbatim, never hide information
    source = m.group("source")
    short = source[:_SOURCE_SHORT_LEN] if source != "unknown" else "unknown"
    # HH:MM is the 12th..16th chars of the ISO timestamp (YYYY-MM-DD T HH:MM) — index 11..16.
    ts = m.group("ts")
    hhmm = ts[11:16]
    return f"{short} · {hhmm} UTC"
