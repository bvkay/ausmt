"""The one projection from the verified-resource register to every surface that renders it.

Four questions, answered here and nowhere else. The last three part ways on purpose
(INTERFACE-CONTRACT:126-132 evidence permanence; :150-153 route detail is its own assertion
class; the THREDDS rule), and they all rest on the first:

  projects       does this ONE register row publish anything: `review: verified` and a level
                   this module routes. Asked by the three below AND by station.json's emitter, so
                   the publication rule is stated once rather than restated per surface.
  station_flag   does a verified time-series resource EXIST for this station? Existence
                   semantics: follows the register for EVERY station, withheld included;
                   an embargo never flips it, an outage never flips it, and the only lawful way
                   down is curation - a row retired with its dated reason stops projecting, and
                   when it was the station's last verified row the flag goes with it.
  survey_counts  the per-survey tally of true flags (spec: stable across access transitions,
                   never derivable by subtraction).
  route_rows     the PUBLIC route detail: level token to {bytes, url_path}. Only for an OPEN
                   station (the caller passes the same served/gated verdict the access gate
                   computed; policy before emission), only `review: verified`, and never
                   level2: a transfer-function copy in the archive is not a time series and
                   must not open a route.

ts_access.json, the mtcat keys, and deploy/scripts/gen_ts_routes.py all render from these
functions; the route table's membership IS route_rows()'s answer, which is what makes the R5
suppression one predicate instead of three opinions.
"""
from __future__ import annotations

# level2 rows are register EVIDENCE (a curator may record one by hand) but never time-series
# claims: not the flag, not a resource row, not a route, not a chooser token.
NEVER_PROJECTS = ("level2",)


def projects(row) -> bool:
    """Does ONE register row publish anything at all: `review: verified` and a routable level.

    PUBLIC because the emitter asks it too. station.json's `time_series` rows, the flag, the boot
    artifact and the front door's route table are four renderings of this one answer, and a second
    statement of it - even a correct one - is a rule that has to be changed in two places and will
    one day be changed in one."""
    return row.get("review") == "verified" and row.get("level") not in NEVER_PROJECTS


def station_flag(rows) -> bool:
    """EXISTENCE: any live register row proves it, whatever the station's access state."""
    return any(projects(r) for r in rows or ())


def survey_counts(flags_by_survey) -> dict:
    """{survey slug: count of true flags}, entries only where the count is positive
    (omit-by-default: an absent count asserts nothing, a zero would)."""
    out = {}
    for slug, flags in flags_by_survey.items():
        n = sum(1 for f in flags if f)
        if n:
            out[slug] = n
    return out


def route_rows(rows, station_open) -> dict:
    """{level token: {bytes, url_path}} for the surfaces that publish ROUTE DETAIL. Empty for a
    non-open station however the register reads: suppression lives in resolution, and this
    return value is the resolution."""
    if not station_open:
        return {}
    out = {}
    for r in rows or ():
        if not projects(r):
            continue
        entry = {"url_path": r["url_path"]}
        if r.get("bytes"):
            entry["bytes"] = r["bytes"]
        out[r["level"]] = entry
    return out
