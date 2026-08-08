#!/usr/bin/env python3
"""Station-id override for third-party released data (owner ruling 2026-08-08).

AusMT serves third-party released data BYTE-IDENTICAL (D1), so a station whose contractor numbering
is not a usable public identifier cannot be renamed by editing its EDI. The custodian declares the
id AusMT should publish in survey.yaml instead, keyed by the SOURCE FILE the record is parsed from:

    station_ids:
      source: filename          # enum; only 'filename' today. Reserved for future keys
                                # (e.g. 'dataid', 'raw_recording') so the block can grow.
      map:
        "92.edi":    "RD18-092"
        "92_S1.edi": "RD18-092-S1"

A map value may instead be a mapping, carrying the custodian's own provenance for that file
alongside the optional published id (see PROVENANCE_KEYS below). The provenance travels in AusMT's
own records only; the source file is never rewritten.

Semantics, all fail-closed (the refuse-to-serve posture the C25 convention gates and the C42
coordinate policy already take):

  * an ABSENT block leaves the EDI DATAID authoritative for every station, exactly as before. The
    whole existing corpus builds byte-identically; nothing in this module runs for it.
  * a map key naming a file the package does not contain is a survey-level build FAILURE that names
    the filename (a typo must never be a silent no-op, which is how the wrong site gets published
    under the right name).
  * two map values colliding is a survey-level build FAILURE naming BOTH keys: colliding published
    ids are exactly the defect this block exists to fix.
  * a file in edi/ with NO map entry, while the block is present, is NOT an error. Partial maps are
    legal and such a station simply keeps DATAID behaviour.

Ordering matters and is pinned by test: the override is applied AFTER the DATAID parse and BEFORE
build_portal._disambiguate, so _disambiguate sees already-unique ids and never invents a `.a`/`.b`
processing-variant tag. In the GSSA/BHP Roxby Downs 2018 delivery the contractor reused 56 station
numbers between two acquisition stages (the furthest colliding pair 58.5 km apart), and a variant
tag there would assert that two DIFFERENT physical sites are two processings of one station.

The EDI's own DATAID is preserved on the record as `site_name` by the SAME mechanism the DATAID
overwrite at build_portal:1406-1415 already uses, so the catalogue keeps its one convention for
"the id we display is not the id the source carried". The source bytes are never touched.

Stdlib-only leaf (the _license_text pattern): no build_portal import, so it stays unit-testable
without the mt_metadata stack and cannot create an import cycle.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

# The `source` enum. Only filename-keyed maps exist in this lane; the enum is declared as a tuple so
# a future key ('dataid', 'raw_recording') is an addition here rather than a shape change.
STATION_ID_SOURCES = ("filename",)

# The per-file provenance a third-party ingest carries. The map VALUE may be a bare published id
# (the common case) or a mapping carrying these alongside an optional `id`:
#
#     map:
#       "84.edi": "RD18-084"                    # id only
#       "84R.edi":                               # id + provenance
#         id: "RD18-084-S1-b"
#         source_record_id: "2781110A"           # the custodian's own opaque record handle
#         acquisition_stage: "1"                 # free text; the delivery's own stage label
#
# `original_filename` is deliberately NOT a declarable key: it IS the map key, so deriving it here
# makes the two impossible to disagree. `id` is optional inside the mapping form, so a file may carry
# provenance while keeping its DATAID.
PROVENANCE_KEYS = ("source_record_id", "acquisition_stage")
_VALUE_KEYS = ("id",) + PROVENANCE_KEYS


class StationIds(NamedTuple):
    """A survey's parsed `station_ids` block.

    * `source`     - the key discipline; 'filename' today.
    * `ids`        - {source filename: published station id} for the files that declare one.
    * `provenance` - {source filename: {original_filename, source_record_id, acquisition_stage}} for
      the files that declare provenance. Keyed identically to `ids` but INDEPENDENT of it: a file may
      appear in one, the other, or both.
    """

    source: str
    ids: dict
    provenance: dict

# The published-id charset, expressed as the FIXED POINT of build_portal.safe_component: a value is
# acceptable only when safe_component would return it unchanged. safe_component keeps
# [A-Za-z0-9._-], neutralises '..', strips leading dots/dashes and never returns empty; the pattern
# plus the two guards below are that exact post-condition, checked as a PREDICATE so an id the
# sanitiser would mangle FAILS LOUDLY instead of being silently rewritten (owner's ids are not ours
# to mangle). tests/test_station_ids.py pins the two in agreement over the shared safe_component
# vector fixture, so they cannot drift apart.
_SAFE_ID = re.compile(r"\A[A-Za-z0-9._-]+\Z")


class StationIdError(ValueError):
    """A survey's `station_ids` block is invalid: an unknown key, a bad `source`, a map key that is
    not a bare filename, a value outside the id charset, colliding values, or a key naming a file the
    package does not contain. Raised so the caller drops the survey LOUDLY rather than publishing
    under an id it could not honour."""


def station_id_is_safe(value) -> bool:
    """True when `value` is a published station id that survives build_portal.safe_component
    UNCHANGED. Rejects the empty string, path separators, whitespace, markup, '..' anywhere, and a
    leading '.' or '-' (safe_component strips those, so accepting one would mean publishing a
    different id than the custodian declared)."""
    s = str(value) if value is not None else ""
    if not _SAFE_ID.match(s):
        return False
    if ".." in s:
        return False
    return s[0] not in ".-"


def _check_map_key(key) -> str:
    """One map key: a BARE source filename, no path component. Rejects separators and the '..' and
    '.'/'' traversal shapes outright, so a map can never reach outside transfer_functions/edi/."""
    k = str(key) if key is not None else ""
    if not k.strip():
        raise StationIdError("station_ids.map has an EMPTY key; keys are bare source filenames "
                             "such as \"92.edi\" (refusing to build this survey; fail closed).")
    if "/" in k or "\\" in k or k in (".", ".."):
        raise StationIdError(
            f"station_ids.map key {k!r} is not a bare filename. Keys name a file INSIDE this "
            f"package's transfer_functions/edi/ directory and must carry no path separator and no "
            f"'..' component (refusing to build this survey; fail closed).")
    if Path(k).name != k:
        raise StationIdError(
            f"station_ids.map key {k!r} is not a bare filename (its path component would be "
            f"ignored). Use just the file name, e.g. \"92.edi\" (fail closed).")
    return k


def _parse_value(key: str, value):
    """One map VALUE, in either accepted form. Returns (published id or None, provenance or None).

    A bare scalar is the published id. A mapping carries an optional `id` plus the provenance keys;
    an unknown key inside it is a FAILURE, not a silent drop (the frozen-allow-list discipline the
    attribution/sources blocks already use). A mapping with neither an id nor any provenance says
    nothing at all and is refused, because it is almost certainly a half-finished edit."""
    if isinstance(value, dict):
        unknown = sorted(k for k in value if k not in _VALUE_KEYS)
        if unknown:
            raise StationIdError(
                f"station_ids.map[{key!r}] has unknown key(s) {unknown}; only {list(_VALUE_KEYS)} "
                f"are defined (fail closed, so a typo cannot silently drop provenance).")
        raw_id = value.get("id")
        prov = {}
        for pk in PROVENANCE_KEYS:
            pv = value.get(pk)
            if pv not in (None, ""):
                prov[pk] = str(pv).strip()
        if raw_id in (None, "") and not prov:
            raise StationIdError(
                f"station_ids.map[{key!r}] is an empty mapping: it declares neither an `id` nor any "
                f"of {list(PROVENANCE_KEYS)} (fail closed).")
        # original_filename is the KEY, never a declared field, so the two cannot disagree.
        if prov:
            prov = {"original_filename": key, **prov}
        return (raw_id if raw_id not in (None, "") else None), (prov or None)
    return value, None


def parse_station_ids(block) -> StationIds:
    """Read a StationIds(source, ids, provenance) from a survey.yaml top-level `station_ids` value.

    Returns StationIds("filename", {}, {}) for an ABSENT/empty block: the caller then applies no
    override at all and every station keeps DATAID behaviour, so an existing survey is byte-identical.

    Raises StationIdError for: a non-mapping block, an unknown top-level key, a `source` outside
    STATION_ID_SOURCES, a non-mapping `map`, a key that is not a bare filename, an unknown key inside
    a mapping-form value, a value outside the published-id charset, or two keys mapping to the SAME
    published id. Key EXISTENCE is validated separately by validate_station_ids, against the package's
    real files (the same split the C42 coordinate policy uses: enum shape at discovery, identity
    against reality in the build loop)."""
    if block in (None, "", {}):
        return StationIds(STATION_ID_SOURCES[0], {}, {})
    if not isinstance(block, dict):
        raise StationIdError(
            f"station_ids must be a mapping with `source` and `map`, got "
            f"{type(block).__name__} (refusing to build this survey; fail closed).")
    unknown = sorted(k for k in block if k not in ("source", "map"))
    if unknown:
        raise StationIdError(
            f"station_ids has unknown key(s) {unknown}; only 'source' and 'map' are defined "
            f"(refusing to build this survey; fail closed, so a typo cannot silently do nothing).")
    raw_source = block.get("source")
    source = str(raw_source).strip().lower() if raw_source not in (None, "") else STATION_ID_SOURCES[0]
    if source not in STATION_ID_SOURCES:
        raise StationIdError(
            f"station_ids.source={raw_source!r} is not one of {list(STATION_ID_SOURCES)} "
            f"(refusing to build this survey; fail closed).")
    raw_map = block.get("map")
    if raw_map in (None, "", {}):
        return StationIds(source, {}, {})
    if not isinstance(raw_map, dict):
        raise StationIdError(
            f"station_ids.map must be a mapping of {{source filename: published station id}}, got "
            f"{type(raw_map).__name__} (refusing to build this survey; fail closed).")
    mapping: dict = {}
    provenance: dict = {}
    for key, value in raw_map.items():
        k = _check_map_key(key)
        if k in mapping or k in provenance:
            raise StationIdError(f"station_ids.map names the file {k!r} twice (fail closed).")
        raw_id, prov = _parse_value(k, value)
        if prov:
            provenance[k] = prov
        if raw_id is None:
            continue                       # provenance-only entry: this file keeps its DATAID
        sid = str(raw_id).strip()
        if not station_id_is_safe(sid):
            raise StationIdError(
                f"station_ids.map[{k!r}]={raw_id!r} is not a usable published station id. Allowed "
                f"characters are letters, digits, '.', '_' and '-'; the id may not be empty, may "
                f"not start with '.' or '-', and may not contain '..'. AusMT refuses to publish a "
                f"mangled form of an id you declared (fail closed).")
        mapping[k] = sid
    dupes = {}
    for k, sid in mapping.items():
        dupes.setdefault(sid, []).append(k)
    collided = {sid: sorted(keys) for sid, keys in dupes.items() if len(keys) > 1}
    if collided:
        detail = "; ".join(f"{sid!r} <- {keys}" for sid, keys in sorted(collided.items()))
        raise StationIdError(
            f"station_ids.map assigns the same published id to more than one source file: {detail}. "
            f"Two files that are two DIFFERENT physical sites need two different ids; two files "
            f"that are the same site need one of them removed from the package (fail closed).")
    return StationIds(source, mapping, provenance)


def _all_keys(station_ids):
    """Every source filename the block names, whether it declares an id, provenance or both. Accepts
    a StationIds or a bare {filename: id} mapping so unit callers stay simple."""
    if isinstance(station_ids, StationIds):
        return set(station_ids.ids) | set(station_ids.provenance)
    return set(station_ids or {})


def validate_station_ids(station_ids, source_paths):
    """Every map key must name a file actually present in this survey's ingest set.

    `source_paths` is the list of source files the build is about to parse (the package's
    transfer_functions/edi/*.edi). A key naming no such file is a survey-level FAILURE: silently
    ignoring it would publish that station under its raw DATAID while the custodian believed it was
    renamed, or drop the provenance the custodian declared. The message names the unmatched key(s)
    and lists the package's real filenames so the fix is immediate.

    The reverse direction is deliberately NOT an error: a file with no map entry keeps DATAID
    behaviour, so partial maps are legal."""
    keys = _all_keys(station_ids)
    if not keys:
        return
    present = {Path(str(p)).name for p in (source_paths or ())}
    missing = sorted(k for k in keys if k not in present)
    if missing:
        raise StationIdError(
            f"station_ids.map names source file(s) {missing} that this survey's "
            f"transfer_functions/edi/ does not contain. Map keys are bare source FILENAMES, and an "
            f"unmatched key would leave that station published under its raw DATAID (fail closed). "
            f"This package's EDI files: {sorted(present)}.")


def override_for(mapping, source_path):
    """The published station id declared for THIS source file, or None when the file has no entry
    (DATAID behaviour is kept). Matching is on the bare filename, the one key discipline the
    validator checks, so a validated key can never be a no-op at application time."""
    if not mapping:
        return None
    return mapping.get(Path(str(source_path)).name)


def apply_override(record, source_path, mapping) -> bool:
    """Apply this source file's declared id to `record` IN PLACE; return True when one applied.

    The pre-override id (the EDI's own DATAID, as parsed and Phoenix-unpacked at
    build_portal:1406-1415) is retained as `site_name` under the SAME "only when the overwrite
    actually changes it" convention that block already uses, so the catalogue keeps ONE mechanism for
    a displayed id that differs from the source's. The caller still runs the result through
    safe_component, exactly as it does for a DATAID; parse_station_ids has already refused any value
    that the sanitiser would change, so that pass is a belt-and-braces no-op rather than a mangler."""
    new_id = override_for(mapping, source_path)
    if new_id is None:
        return False
    previous = record.get("id")
    record["id"] = new_id
    if previous and str(previous) != str(new_id):
        record["site_name"] = previous
    return True


def provenance_for(station_ids, source_path):
    """The declared source provenance for THIS file, or None. Same bare-filename key discipline as
    the id map, so a validated key is never a no-op at application time."""
    if not isinstance(station_ids, StationIds) or not station_ids.provenance:
        return None
    return station_ids.provenance.get(Path(str(source_path)).name)


def apply(record, source_path, station_ids) -> bool:
    """Apply this source file's declared id AND its declared provenance to `record` IN PLACE.

    The provenance rides on the record as `source_provenance` and travels into AusMT's OWN records
    (station.json, build_report, the derived MTH5 and EMTF XML). It is NEVER written into the source
    file: for a third-party release the served EDI is the custodian's published record and stays
    byte-identical, which is the guarantee the whole no-editing posture rests on."""
    if station_ids is None:
        return False
    ids = station_ids.ids if isinstance(station_ids, StationIds) else station_ids
    changed = apply_override(record, source_path, ids)
    prov = provenance_for(station_ids, source_path)
    if prov:
        record["source_provenance"] = dict(prov)
        changed = True
    return changed
