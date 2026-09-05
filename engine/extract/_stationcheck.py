#!/usr/bin/env python3
"""The station-record semantic layer: the station.json rules JSON Schema cannot state.

SCOPE:377-380 asks for emitter-side validation beyond the schema, and this is that layer: referential
integrity of a resource's run references, unique run and resource ids, time_period ordering, channel
shape per component family, archive-row containment, withheld-branch rejection, DOI syntax, the
zero-null rule over everything this module adds, plus the 1.x pin that keeps `distribution.edi_path`
and the served EDI resource row stating one path (SCOPE:71-73).

ONE implementation, two enforcement points: build_portal._validate_station_metadata runs it over the
documents the build is about to publish, and scripts/verify.py runs it again over a built tree before
a deployment swaps `current`. Stdlib only, so the verify gate never depends on the ingest stack.

The withheld rules restate what the schema's closed-world branch already forbids. That is deliberate:
jsonschema is an optional dependency and both self-checks degrade to a note without it, so the leak
protection must not rest on the schema alone.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import quote, unquote

# The withheld stub's WHOLE key set (schema oneOf[0]): the nine frozen keys plus the three promotion
# markers. Closed world, so any other key in a withheld record is a leak, never an extension.
WITHHELD_KEYS = frozenset({"schema", "version", "ausmt_id", "station", "survey", "survey_id",
                           "country", "organisation", "access", "distribution", "withheld", "note"})
_WITHHELD_BLOCK_KEYS = {"access": frozenset({"level", "embargo_until", "served"}),
                        "distribution": frozenset({"edi_available", "license", "edi_path"})}
# Bare canonical form, the only form AusMT publishes: a resolver prefix makes a DOI a URL.
_BARE_DOI = re.compile(r"^10\.\d{4,9}/\S+$")
# The electrode-circuit members. They attach to the electric measurement circuit and to nothing else.
_ELECTRIC_ONLY = ("positive", "negative", "dipole_length_m", "contact_resistance")
# {archive resource id: the rendition whose presence proves this station's bytes are IN that bundle}.
# An `archive` row is a CONTAINMENT claim, and containment is decided per station, not per survey:
# the coordinate byte gate withholds a non-exact station's EDI and EMTF XML, so it is in neither zip
# its survey still publishes. The emitter reads the same map when it builds resources[], so the rule
# is stated once and enforced at both ends.
#
# survey-mth5 is the one approximate row. The tier-2 bundle is written by the SAME writer over the
# SAME coordinate-gated station set as the tier-1 per-station files, so the tier-1 row proves tier-2
# membership whenever both are enabled, which is what deployment does (deploy/Makefile passes
# --survey-h5 AND --station-h5). A build passing only --survey-h5 publishes no survey-mth5 row at
# all: under-claiming is open-world and safe, claiming containment we cannot demonstrate is not.
ARCHIVE_MEMBER_FORMAT = {"edi-zip": "edi", "xml-zip": "emtfxml", "survey-mth5": "mth5"}
# The one route a `time_series` row may carry. Stated HERE, and read by the emitter as well as by the
# rules below, so the canonical host cannot drift between what is published and what is checked. The
# fileServer path is the VERIFIED route: OPeNDAP answers 500 on this archive's MTH5, so a dodsC URL
# would be a published dead end, and the prefix makes one structurally impossible.
TS_ACCESS_PREFIX = "https://thredds.nci.org.au/thredds/fileServer/"
# What a `time_series` row must state. The row describes bytes on ANOTHER host: it names no local
# path and restates no checksum, so the route and the product level ARE the claim.
_TS_REQUIRED = ("access_url", "processing_level")
# What a percent-encoded path may contain: the unreserved set, the separator, and %XX. A literal
# space or bracket means the route was assembled by concatenation instead of encoded, and only the
# encoded form resolves (NVP_2019's `C5 [REMOTE].zip`), so the unencoded one is a dead download.
_TS_ENCODED = re.compile(r"^(?:[A-Za-z0-9/_.~-]|%[0-9A-Fa-f]{2})+$")
# Fail-CLOSED rather than merely unemitted: the archive's level_2 tree holds
# TRANSFER FUNCTIONS, so a level2 row under this kind asserts a recorded time series for a station
# that has none. The emitter routes no such row; this refuses one that arrives by any other path.
_TS_EXCLUDED_LEVEL = "level2"
# What this module ADDS. Section 2's zero-null rule is scoped to it: the frozen keys carry eight
# legitimate nulls (remote_site, coordinate_qc, rotspec, the emeas azimuths, the two rotation sources,
# convention_check.detail), so the survey-metadata document's corpus-wide rule cannot be imported.
# The fold is an addition too, and the scan reaches INTO `diagnostics` for exactly its members:
# an undetermined call is OMITTED here, never copied across as the sidecar's null.
_NEW_BLOCKS = ("runs", "resources")
_FOLDED_DIAGNOSTICS = ("classification", "skew_beta_median_deg", "pct_periods_3d", "method", "note")


def ts_encode_path(url_path) -> str:
    """One register `url_path` as the percent-encoded fileServer PATH.

    THE ONE ENCODER: it lives here, not in the emitter, because the front door's route-table
    generator renders the same string without the ingest stack, and two encoders would put a
    working route in station.json beside a dead one at the edge. Encoding happens once, where the
    verbatim register string becomes a URL (corpus case: only `C5%20%5BREMOTE%5D.zip` answers
    200), and the output is held to _TS_ENCODED, the same rule the published route is checked
    against."""
    return quote(str(url_path).strip().lstrip("/"), safe="/")


def ts_path_walks_up(url_path) -> bool:
    """True when a fileServer path climbs OUT of the archive root.

    _TS_ENCODED admits `.` and `/` (real archive names carry both), so traversal is refused by
    name: browsers normalise `..` before sending, making the link resolve to an arbitrary path on
    the archive host under an AusMT byline. Read on DECODED segments - the server decodes before
    it resolves, so a literal-only test passes `%2E%2E` straight through."""
    return any(seg == ".." for seg in unquote(str(url_path or "").strip()).split("/"))


def ts_access_url(url_path) -> str:
    """The absolute, public download route for one register `url_path`: the one host this archive
    serves these files on, plus the encoded path."""
    return TS_ACCESS_PREFIX + ts_encode_path(url_path)


def violations(doc) -> list:
    """Every semantic violation in ONE station document, as human-readable strings (empty = clean).

    Shape problems are reported, never raised: a caller checking a whole corpus has to name every bad
    document, not stop at the first one."""
    if not isinstance(doc, dict):
        return [f"not a JSON object ({type(doc).__name__})"]
    # Routing is on the marker's PRESENCE, not its truth: `withheld: false` is forbidden on a full
    # record (a false property schema), and this layer exists because jsonschema is optional, so a
    # record carrying the key must be judged here rather than only there.
    if "withheld" in doc:
        return _withheld_violations(doc)
    runs = doc.get("runs") or []
    resources = doc.get("resources") or []
    return (_run_violations(runs)
            + _resource_violations(resources, {r.get("id") for r in runs if isinstance(r, dict)})
            + _doi_violations(doc)
            + _edi_path_violations(doc, resources)
            + _new_block_violations(doc))


def _instant(value):
    """One ISO 8601 instant as an aware datetime, or None where the string is not one. `Z` is
    rewritten because datetime.fromisoformat only learned to read it in 3.11; a naive value is read as
    UTC so two instants are always comparable."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _withheld_violations(doc) -> list:
    out = [f"withheld record carries `{k}`, which the withheld branch does not define"
           for k in sorted(set(doc) - WITHHELD_KEYS)]
    for block, allowed in _WITHHELD_BLOCK_KEYS.items():
        value = doc.get(block)
        if isinstance(value, dict):
            out += [f"withheld record's `{block}` carries `{k}`" for k in sorted(set(value) - allowed)]
    if (doc.get("distribution") or {}).get("edi_path") is not None:
        out.append("withheld record states a distribution.edi_path; nothing is distributed for it")
    return out


def _run_violations(runs) -> list:
    out, seen = [], set()
    for run in runs:
        if not isinstance(run, dict):
            out.append(f"runs[] carries a {type(run).__name__}, not a run object")
            continue
        rid = run.get("id")
        if rid in seen:
            out.append(f"run id {rid!r} appears twice; run ids are unique within a station record")
        seen.add(rid)
        period = run.get("time_period") or {}
        start, end = _instant(period.get("start")), _instant(period.get("end"))
        for key, value, parsed in (("start", period.get("start"), start), ("end", period.get("end"), end)):
            if value is not None and parsed is None:
                out.append(f"run {rid}: time_period.{key} {value!r} is not an ISO 8601 instant")
        if start and end and end < start:
            out.append(f"run {rid}: time_period ends ({period['end']}) before it starts ({period['start']})")
        out += _channel_violations(rid, run.get("channels") or [])
    return out


def _channel_violations(rid, channels) -> list:
    """The crosswalk places every physical quantity where its scientific meaning lives: an electric
    channel's instrument is its electrode circuit, a magnetic channel's is a sensor."""
    out = []
    for channel in channels:
        if not isinstance(channel, dict):
            out.append(f"run {rid}: channels[] carries a {type(channel).__name__}, not a channel object")
            continue
        component = str(channel.get("component") or "")
        family = component[:1].lower()
        if family == "e" and "sensor" in channel:
            out.append(f"run {rid} channel {component}: an electric channel carries no `sensor`")
        if family in ("h", "b"):
            out += [f"run {rid} channel {component}: a magnetic channel carries no `{k}`"
                    for k in _ELECTRIC_ONLY if k in channel]
    return out


def _resource_violations(resources, run_ids) -> list:
    out, seen = [], set()
    for resource in resources:
        if not isinstance(resource, dict):
            out.append(f"resources[] carries a {type(resource).__name__}, not a resource object")
            continue
        rid = resource.get("id")
        if rid in seen:
            out.append(f"resource id {rid!r} appears twice; resource ids are stable within the document")
        seen.add(rid)
        for key in ("represents_runs", "derived_from_runs"):
            out += [f"resource {rid}: {key} names run {ref!r}, which this record does not publish"
                    for ref in (resource.get(key) or []) if ref not in run_ids]
        out += [f"resource {rid}: service_urls advertises {str(entry.get('kind') or '')!r}. A "
                f"resource states a direct route or nothing: a service endpoint is operational "
                f"state, and the one this record could name (OPeNDAP) answers 500 for the archive's "
                f"MTH5, so the row would advertise a dead endpoint"
                for entry in (resource.get("service_urls") or []) if isinstance(entry, dict)]
        if resource.get("kind") == "time_series":
            out += _time_series_violations(rid, resource)
    return out + _archive_membership_violations(resources)


def _time_series_violations(rid, resource) -> list:
    """A hand-off row's own rules. AusMT stores none of these bytes, so nothing local corroborates
    the row: an unresolvable route publishes a dead download and a wrong level mis-attributes a
    file to a product it is not."""
    out = [f"resource {rid}: a time_series row states no {key}; it describes bytes on another host, "
           f"so the route and the product level are the whole claim"
           for key in _TS_REQUIRED if not str(resource.get(key) or "").strip()]
    if resource.get("processing_level") == _TS_EXCLUDED_LEVEL:
        out.append(f"resource {rid}: level 2 is not a time series; that tree holds transfer "
                   f"functions, so this row would assert a recording the station has none of")
    url = str(resource.get("access_url") or "").strip()
    if url and not url.startswith(TS_ACCESS_PREFIX):
        out.append(f"resource {rid}: access_url {url!r} is not an absolute route under "
                   f"{TS_ACCESS_PREFIX}, the one route this archive serves these files on")
    elif url and not _TS_ENCODED.match(url[len(TS_ACCESS_PREFIX):]):
        out.append(f"resource {rid}: access_url {url!r} is not percent-encoded; only the encoded "
                   f"form resolves, so this route is a dead download")
    elif url and ts_path_walks_up(url[len(TS_ACCESS_PREFIX):]):
        out.append(f"resource {rid}: access_url {url!r} walks up out of the fileServer root. The "
                   f"client normalises the path before it asks, so this publishes a claim about "
                   f"some other file on that host - and the route table refuses the same string, "
                   f"so the edge could never serve it either")
    return out


def _archive_membership_violations(resources) -> list:
    """An archive row may only ride a record that also publishes the rendition the bundle was built
    from. Fail-closed on an unrecognised archive id: a bundle nothing in this map names has no stated
    membership rule, so it cannot be claimed."""
    served = {r.get("id") for r in resources
              if isinstance(r, dict) and r.get("kind") == "transfer_function"}
    out = []
    for resource in resources:
        if not isinstance(resource, dict) or resource.get("kind") != "archive":
            continue
        rid = resource.get("id")
        member = ARCHIVE_MEMBER_FORMAT.get(rid)
        if member is None:
            out.append(f"resource {rid!r} is an archive with no stated membership rule, so this "
                       f"record cannot claim to be in it")
        elif member not in served:
            out.append(f"resource {rid!r} claims an archive this record put no bytes into: it "
                       f"publishes no {member!r} rendition")
    return out


def _identifier_rows(node):
    """Every {scheme, identifier} row at any depth. Instrument PIDs, electrode PIDs and a resource's
    related_collection_identifiers share ONE definition, so one walk covers all three."""
    if isinstance(node, dict):
        if "scheme" in node and "identifier" in node:
            yield node
        for value in node.values():
            yield from _identifier_rows(value)
    elif isinstance(node, list):
        for value in node:
            yield from _identifier_rows(value)


def _doi_violations(doc) -> list:
    return [f"DOI {row.get('identifier')!r} is not in bare canonical form "
            f"(10.<prefix>/<suffix>, never a resolver URL)"
            for row in _identifier_rows(doc)
            if str(row.get("scheme") or "").upper() == "DOI"
            and not _BARE_DOI.match(str(row.get("identifier") or ""))]


def _edi_path_violations(doc, resources) -> list:
    """SCOPE:71-73: distribution.edi_path is the legacy form of the served EDI resource's path and
    stays byte-compatible through 1.x, so the two state one path or neither states any."""
    legacy = (doc.get("distribution") or {}).get("edi_path")
    paths = [r.get("path") for r in resources if isinstance(r, dict)
             and r.get("kind") == "transfer_function" and r.get("format") == "edi"]
    if legacy and paths != [legacy]:
        return [f"distribution.edi_path {legacy!r} does not match the served EDI resource path(s) {paths}"]
    if not legacy and paths:
        return [f"a served EDI resource {paths} is published while distribution.edi_path states none"]
    return []


def _scan(node, path, nulls, empties):
    if isinstance(node, dict):
        items = [(f"{path}.{k}", v) for k, v in node.items()]
    elif isinstance(node, list):
        items = [(f"{path}[{i}]", v) for i, v in enumerate(node)]
    else:
        return
    if not items:
        empties.append(path)
    for child, value in items:
        if value is None:
            nulls.append(child)
        else:
            _scan(value, child, nulls, empties)


def _added_violations(value, path, subject) -> list:
    """The zero-null, zero-empty rule over one ADDED member. The member itself is checked too: a
    scalar null never reaches _scan, so a scoping that only descended missed the fold entirely."""
    nulls, empties = [], []
    if value is None:
        nulls.append(path)
    else:
        _scan(value, path, nulls, empties)
    return ([f"null value at {p} ({subject} states absence by omission)" for p in nulls]
            + [f"empty container at {p} ({subject} states absence by omission)" for p in empties])


def _new_block_violations(doc) -> list:
    out = []
    for block in _NEW_BLOCKS:
        if block in doc:
            out += _added_violations(doc[block], f"$.{block}", f"{block}[]")
    diagnostics = doc.get("diagnostics")
    if isinstance(diagnostics, dict):
        for member in _FOLDED_DIAGNOSTICS:
            if member in diagnostics:
                out += _added_violations(diagnostics[member], f"$.diagnostics.{member}", "the fold")
    return out
