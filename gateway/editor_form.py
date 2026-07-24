"""Structured metadata-editor form assembly (C31 §2, the 2026-07-08 "hostile JSON" fix).

The curator edit form (gateway/curatorpage.py::render_edit_form) used to render every structured
survey.yaml section as a raw JSON textarea. A geophysicist is not a JSON author, so the sections are
now per-section widgets. This module is the SERVER-SIDE half that turns the widget inputs back into
the same patch the JSON textareas produced — so the preview/confirm/commit pipeline underneath is
byte-identical (the round-trip test pins that: render the form from a real survey.yaml, submit it
unchanged, and the preview shows NO diff).

It is pure stdlib (json only — NOT yaml; the gateway never parses survey content, C31 §0.1). It does
NO git and NO version logic; it only maps form fields <-> section dicts and validates the formats it
knows (ORCID via gateway.orcid, DOI "10." prefix, ISO date, access.level enum).

Field-naming scheme (all rendered by curatorpage; all consumed here):
  f_<scalar>                       top-level scalars (project_name/name/region/license/abstract) —
                                   unchanged from the pre-widget form, still handled in app._build_patch.
  s_<section>_<subkey>             a map section's scalar sub-field (organisation.name, access.contact…)
  l_<section>_<i>_<subkey>         row i of a repeatable list section (principal_investigators…)
  c_<section>_<value>             a checkbox in a set (time_series.levels_available)
  o_<section>                      HIDDEN snapshot of the ORIGINAL section value as canonical JSON —
                                   the round-trip anchor: an unchanged submit reassembles to exactly
                                   this and the section is dropped from the patch (a true no-op, same
                                   as the old "blank JSON textarea = leave unchanged").
  j_<section>                      the ADVANCED raw-JSON <details> textarea. Same name the old form
                                   used, so a non-empty value takes the EXACT legacy JSON path and
                                   OVERRIDES the widgets for that section (documented precedence).

Precedence, enforced in ONE place (assemble_section):
  1. j_<section> non-empty  -> parse as JSON (legacy path); malformed => per-field error.
  2. else assemble from the s_/l_/c_ widgets.
  3. if the assembled value == the original snapshot (o_<section>) => omit the key (no-op, round-trip).
"""
from __future__ import annotations

import json
from datetime import date

from . import orcid

# ---- section specifications ---------------------------------------------------------------------
# Each MAP section: the ordered scalar sub-keys the widget renders. Each LIST section: the per-row
# scalar sub-keys. These mirror docs/reference/survey-yaml.md exactly — no invented fields.

# Map sections rendered as labelled inputs. (key, label, placeholder, kind) per sub-field;
# kind drives the input type / validation: "text" | "doi" | "orcid" | "ror" | "date" | "email".
MAP_SECTIONS: dict[str, list[tuple[str, str, str, str]]] = {
    "organisation": [
        ("name", "Name", "University of Example", "text"),
        ("ror", "ROR id", "https://ror.org/03yghzc09", "ror"),
    ],
    "lead_investigator": [
        ("name", "Name", "Given Family", "text"),
        ("orcid", "ORCID", "0000-0002-1825-0097", "orcid"),
    ],
    # IDCONS D2 (SPEC §3): the flat dataset-identifier inputs are RETIRED from the editor UI. The typed
    # related_identifiers list (below, group (b) of the "Identifiers & PIDs" page) is now the ONLY place a
    # dataset-level DOI/PID is edited; the legacy "Related publication (+DOI)" pair is superseded by
    # publications[]; identifiers.project was a dead orphan. The schema KEYS stay readable (the engine keeps
    # its flat-key fallback reads until the corpus migration + follow-up), so a survey that still carries
    # them must ROUND-TRIP byte-clean through an unrelated edit — handled generically by the unmodelled-key
    # carry-forward in _assemble_map (proven RED by test_retired_identifier_keys_survive_unrelated_edit).
    # Only the two survey/project-level PIDs a curator legitimately sets stay modelled here.
    "identifiers": [
        ("project_raid", "Project RAiD", "https://raid.org/10.xxxx/xxxxx", "text"),
        # §2b (identifiers design): the ONE survey/platform-level instrument PID (PIDINST, e.g.
        # 10.82388/<id>) — the survey-layer counterpart to the deep per-serial instruments[].pid. Wave-1
        # EXPAND (additive); the surveys validator only WARNS on its format, so it is plain "text" here
        # (a light hint, never a form block) — the same posture as project_raid above.
        ("instrument_pid", "Instrument PID (survey/platform)", "10.82388/… or an https:// URL", "text"),
    ],
    # C46 (schema 0.3): the rights of THIS AusMT release. custodian may differ from organisation.name;
    # changes_made is the CC-BY §3(a) "indicate if changes were made" flag (a bool checkbox); statement
    # is the verbatim custodian-required wording (REQUIRED at the validator when a source has profile
    # ga). Keys are the FROZEN attribution allow-list — byte-identical to the surveys validator's
    # ATTRIBUTION_KEYS (the key-parity test feeds this section through the REAL validator).
    "attribution": [
        ("custodian", "Custodian of record", "e.g. Geological Survey of South Australia", "text"),
        ("custodian_ror", "Custodian ROR id", "https://ror.org/04y8k6r48", "ror"),
        ("statement", "Attribution statement", "verbatim custodian-required wording (optional)", "text"),
        ("changes_made", "Changes made (CC-BY §3a)", "", "bool"),
        ("changes_summary", "Changes summary", "e.g. EMTF XML + MTH5 regenerated from custodian EDIs", "text"),
        ("declared_by", "Declared by", "who asserted the licence/attribution facts", "text"),
        ("declared_date", "Declared date", "", "date"),
    ],
    "access": [
        # level + coordinates are <select>s and embargo_until a date — rendered specially by
        # curatorpage, but the sub-keys and order live here so assembly and rendering agree.
        ("level", "Access level", "", "select"),
        # C42: the SURVEY-LEVEL coordinate-access policy (exact/generalised/withheld). Its key
        # ("coordinates") and value vocab (COORDINATE_POLICIES) are EXACTLY what the engine's
        # extract/_coordaccess.parse_coordinate_policy reads (access.get("coordinates")), so a set
        # value is never a silent no-op. Blank/unset => the key is not written (absent => exact; the
        # record's zero-change promise). The per-station coordinate_overrides map is the C43 Stage-4
        # stations-panel lane, NOT here.
        ("coordinates", "Coordinate access", "", "select"),
        ("embargo_until", "Embargo until", "", "date"),
        ("contact", "Access contact", "email or role address", "email"),
    ],
    "time_series": [
        # IDCONS D2 (SPEC §3): time_series.collection_pid is RETIRED from the editor UI — a dataset-level
        # collection DOI/handle is now recorded as a typed related_identifiers row (relation IsDerivedFrom).
        # The key stays readable (engine fallback + carry-forward round-trip); only levels_available is edited here.
        # levels_available is a checkbox set — rendered specially; listed here for order only.
        ("levels_available", "Levels available", "", "levels"),
    ],
    "processing": [
        ("software", "Software", "BIRRP / Aurora / EMTF / Phoenix EMpower", "text"),
        ("version", "Version", "e.g. 5.2", "text"),
        ("remote_reference", "Remote reference", "yes | no | unknown", "text"),
        ("notes", "Notes", "free text", "text"),
    ],
    "collection": [
        ("id", "Collection id", "auslamp", "text"),
        ("title", "Collection title", "AusLAMP", "text"),
        ("type", "Collection type", "programme", "text"),
        ("status", "Collection status", "active | completed | archived", "text"),
    ],
}

# List (repeatable-row) sections: per-row scalar sub-fields.
LIST_SECTIONS: dict[str, list[tuple[str, str, str, str]]] = {
    "principal_investigators": [
        ("name", "Name", "Given Family", "text"),
        ("orcid", "ORCID", "0000-0002-1825-0097", "orcid"),
    ],
    "publications": [
        ("author", "Author", "Family, G.", "text"),
        ("year", "Year", "2026", "text"),
        ("title", "Title", "Article title", "text"),
        ("journal", "Journal", "Journal name", "text"),
        ("doi", "DOI", "10.xxxx/xxxxx", "doi"),
    ],
    "funding": [
        ("organisation", "Funding organisation", "e.g. AuScope", "text"),
        ("organisation_ror", "Organisation ROR", "https://ror.org/03yghzc09", "ror"),
        ("grant_id", "Grant / award id", "e.g. ARC LP…", "text"),
        ("grant_title", "Grant title", "grant title", "text"),
        ("funding_doi", "Funding DOI", "10.xxxx/xxxxx", "doi"),
    ],
    # IDCONS D2 (SPEC §3): the per-row instruments[].pid input is RETIRED from the editor UI. The
    # survey/platform-level PID is recorded once as identifiers.instrument_pid (group (c) of the new page)
    # or as a typed related_identifiers row; the per-serial key stays readable (engine fallback +
    # per-row carry-forward round-trip) so an un-migrated instruments[].pid survives an unrelated edit.
    "instruments": [
        ("manufacturer", "Manufacturer", "Phoenix", "text"),
        ("model", "Model", "MTU-5C", "text"),
    ],
    # D-L3 (SPEC §9.3): the "Source datasets" section is RETIRED from the editor UI. Its acquisition
    # fields (title, licence-as-obtained, retrieved, attribution statement, attribution profile) are now
    # OPTIONAL keys on a related_identifiers row (an upstream dataset AusMT obtained is just another typed
    # row, identifies: entire). The `sources` LIST_SECTIONS registration is GONE, so build_section_patch
    # never assembles the key — a legacy sources[] on disk is byte-preserved (never entered into any
    # patch; proven RED by test_editor_sources_section_retired_byte_preserved). The engine keeps reading
    # sources[] until the ausmt follow-up (§9.3 note), so nothing served changes this wave.
    #
    # §2a + D-L (SPEC §9): the single typed list of provenance relations to identifiers AusMT does NOT own.
    # The primary per-row control is `identifies` (WHAT the identifier points at, in NCI Table 1 data-level
    # terms) — FIRST on the row and FAIL-CLOSED like relation/identifier_type. The DataCite `relation`
    # DERIVES from `identifies` server-side (D-L2), so it is no longer a curator control on an identifies
    # row; a legacy row that carries an explicit relation but no identifies still edits its relation
    # (backward compatible). The acquisition fields are the ex-sources[] payload, OPTIONAL (only written
    # back when non-empty or already present) so a corpus row without them round-trips to _OMIT.
    "related_identifiers": [
        ("identifies", "What does this identifier point at?", "", "identifies"),
        ("identifier", "Identifier (DOI / handle / URL)", "10.25914/… or an https:// URL", "text"),
        ("identifier_type", "Identifier type", "", "identifier_type"),
        ("relation", "Relation", "", "relation"),
        ("custodian", "Custodian", "e.g. NCI / AuScope", "text"),
        ("title", "Title", "e.g. AusLAMP SA – NCI/AuScope archive", "text"),
        ("licence", "Licence (as obtained)", "", "license"),
        ("retrieved", "Retrieved (date or year)", "2016 or 2016-05-01", "text"),
        ("statement", "Attribution statement", "verbatim required wording, if prescribed (optional)", "text"),
        ("profile", "Attribution profile", "", "profile"),
    ],
}

# D-L (SPEC §9): the related_identifiers row sub-keys that are OPTIONAL — `identifies` (absent on a legacy
# row) plus the acquisition fields merged from the retired sources[] list. Unlike the always-emitted typed
# core (identifier / identifier_type / relation / custodian), an empty optional key is written back ONLY
# when the ORIGINAL row already carried it, so a corpus row that has no acquisition fields (and a legacy
# row that has no identifies) reassembles to its snapshot -> _OMIT, instead of gaining a spray of null
# keys that would break the round-trip and strip the row's INFERRED-REVIEW comment. Keyed by section, so
# no other list section changes behaviour.
_OPTIONAL_LIST_KEYS: dict[str, frozenset] = {
    "related_identifiers": frozenset({"identifies", "title", "licence", "retrieved", "statement",
                                      "profile"}),
}

# access.level enum (validator/normalize; mirrors add-survey.html's <select>).
ACCESS_LEVELS = ("open", "metadata_only", "embargoed")

# C42 access.coordinates enum — the SURVEY-LEVEL coordinate-access policy. Declared like ACCESS_LEVELS
# and IDENTICAL (key + value spellings) to the engine's extract/_coordaccess.COORDINATE_POLICIES, which
# parse_coordinate_policy reads from access["coordinates"]. "exact" is the default (absent => exact); the
# editor never WRITES the key at the default, so a survey that never sets a policy stays byte-unchanged.
# A key/spelling mismatch here would make the setting a silent no-op — pinned by the key-parity test,
# which feeds the editor-assembled block through the REAL engine parser (engine-truth, not a hand-typed
# expectation).
COORDINATE_POLICIES = ("exact", "generalised", "withheld")

# C46 licence vocab for the licence <select>s (the top-level `license` and each sources[].licence).
# This is the full recognised-id vocab: redistributable ∪ recognised_only, in contract order. It is a
# BAKED copy because the gateway APP image is CONTENT-BLIND (it ships only gateway/, never engine/ or
# contract/ — see deploy/docker/gateway.Dockerfile), so a runtime import of the engine/portal contract
# seam is impossible here; the copy is instead PINNED to engine/extract/_contract.py::LICENSES by
# test_editor_form.py::test_license_vocab_matches_engine_contract (the same load-the-engine-seam-by-path
# parity discipline that guards COORDINATE_POLICIES against _coordaccess). REDISTRIBUTABLE first, then
# RECOGNISED_ONLY; the portal add-survey form reads the SAME vocab live from portal/src/contract.js.
LICENSE_IDS = (
    "CC0-1.0", "CC-BY-3.0", "CC-BY-3.0-AU", "CC-BY-4.0", "CC-BY-SA-3.0", "CC-BY-SA-4.0",
    "CC-BY-NC-4.0", "CC-BY-NC-SA-4.0", "CC-BY-ND-4.0", "CC-BY-NC-ND-4.0", "PUBLIC DOMAIN",
    "ODBL-1.0", "ODC-BY-1.0",
    "CC-BY-NC-3.0", "CC-BY-NC-SA-3.0", "CC-BY-ND-3.0", "CC-BY-NC-ND-3.0",
    "ALL RIGHTS RESERVED", "COPYRIGHT",
)
# The redistributable subset (first 13) — used only to GROUP the <select> (redistributable vs
# recognised metadata-only). The gate itself is the engine's; this is a display grouping.
LICENSE_REDISTRIBUTABLE = LICENSE_IDS[:13]
# C46 custodian attribution-profile vocab (sources[].profile). "generic" is the default synthesis;
# "ga" prescribes the Geoscience Australia form (and makes attribution.statement required at validate).
SOURCE_PROFILES = ("ga", "generic")

# §2a (identifiers design — the related-identifiers model): the two FROZEN, FAIL-CLOSED vocabularies the
# typed relation adds. RELATION_TYPES is the curated DataCite subset ratified as the editor presets;
# IDENTIFIER_TYPES is the small set AusMT records against. Both are BAKED copies — the gateway APP image
# is content-blind (ships only gateway/, never the surveys validator — see gateway.Dockerfile), so a
# runtime import of the sibling vocab is impossible; the copies are PINNED byte-for-byte to the surveys
# validator's RELATION_TYPES / IDENTIFIER_TYPES by test_editor_form.py (the same parity-pin discipline
# that guards LICENSE_IDS against the engine contract). Ordered tuples give the <select> a stable preset
# order; the pin compares them as sets (the validator holds frozensets). An out-of-vocab value FAILs at
# the form (SectionError) — byte-identical posture to access.coordinates, because a mis-typed relation
# publishes a WRONG provenance claim and must block, not ship.
RELATION_TYPES = ("IsDerivedFrom", "IsVariantFormOf", "IsSupplementTo", "Cites",
                  "IsPartOf", "IsSourceOf")
IDENTIFIER_TYPES = ("DOI", "Handle", "URL", "RAiD")

# "Identifiers by data level" (D-L1/D-L2, owner-ratified 2026-07-23; SPEC §9). Every related_identifiers
# row states WHAT it points at in NCI Table 1 data-level terms; the DataCite relation then DERIVES from
# the level, so `relation` is no longer a curator-facing control on an identifies row. IDENTIFIES_LEVELS
# is the ORDERED vocab (Table 1 order) baked for the <select>; it is a fail-closed preset like relation /
# identifier_type — an out-of-vocab level publishes a WRONG provenance claim, so it FAILs at the form
# (SectionError). BAKED copies, PINNED to the surveys validator's IDENTIFIES_TYPES / IDENTIFIES_RELATION
# (and per-level derived_relation) by test_editor_form.py::test_related_identifiers_vocab_matches_vendored_-
# validator — the RELATION_TYPES gain (IsPartOf + IsSourceOf) is exactly the derived-relation range this
# map introduces, so the two vocabularies stay consistent.
IDENTIFIES_LEVELS = ("collection", "raw_packed", "level0", "level1", "level2", "level3", "entire")
IDENTIFIES_RELATION = {
    "collection": "IsPartOf",       # the parent record (e.g. an NCI parent collection)
    "raw_packed": "IsDerivedFrom",  # raw/packed time series
    "level0": "IsDerivedFrom",      # edited time series
    "level1": "IsDerivedFrom",      # transformed time series
    "level2": "IsVariantFormOf",    # derived frequency-domain processed data (EDI/TF)
    "level3": "IsSourceOf",         # models (the model derives FROM this dataset)
    "entire": "IsVariantFormOf",    # a single record covering all levels (a GA eCAT / state landing page)
}


def derived_relation(identifies) -> str | None:
    """The DataCite relation a given `identifies` level auto-derives to (D-L2). None when the level is
    absent/blank/out-of-vocab (nothing to derive). Pinned to the surveys validator's derived_relation."""
    if identifies in (None, ""):
        return None
    return IDENTIFIES_RELATION.get(str(identifies).strip())

# time_series.levels_available known values (docs example). A hinted free-text "other" is NOT offered
# — the checkboxes plus the advanced JSON fallback cover the rest.
TIME_SERIES_LEVELS = ("raw_packed", "level0", "level1")

# All sections this module models with widgets (map + list). Anything else stays JSON-only.
WIDGET_SECTIONS = tuple(MAP_SECTIONS) + tuple(LIST_SECTIONS)


class SectionError(Exception):
    """A per-field/section validation or parse failure, surfaced back on the form (not a blanket
    failure). `message` is curator-facing (escaped by the renderer)."""

    def __init__(self, section: str, message: str):
        super().__init__(message)
        self.section = section
        self.message = message


# ---- format validators (only where the format is known) -----------------------------------------

def _valid_doi(value: str) -> bool:
    """A DOI (or DOI-bearing string) must contain a '10.' prefix somewhere (accepts a bare
    '10.xxxx/…' or a full https://doi.org/10.… URL). Deliberately loose — a WARNING-grade curator
    hint, not a resolver check (matches the validator's own DOI leniency)."""
    return "10." in value


def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _validate_scalar(section: str, subkey: str, kind: str, value: str) -> None:
    """Raise SectionError if a KNOWN-format field is non-empty and malformed. Unknown-format fields
    (plain text) never raise."""
    if not value:
        return
    if kind == "orcid" and not orcid.is_valid_orcid(value):
        raise SectionError(section, f"{subkey}: '{value}' is not a valid ORCID "
                                    "(expected 0000-0002-1825-0097 with a correct checksum)")
    if kind == "doi" and not _valid_doi(value):
        raise SectionError(section, f"{subkey}: '{value}' does not look like a DOI "
                                    "(expected a '10.' prefix, e.g. 10.5281/zenodo.123)")
    if kind == "date" and not _valid_date(value):
        raise SectionError(section, f"{subkey}: '{value}' is not an ISO date (YYYY-MM-DD)")
    if kind == "select" and section == "access":
        # Two selects live in the access section: level and (C42) coordinates. Each validates against
        # its OWN vocab — a single 'not in ACCESS_LEVELS' check would reject every coordinates value.
        if subkey == "coordinates" and value not in COORDINATE_POLICIES:
            raise SectionError(section, f"coordinate access '{value}' is not one of "
                                        f"{', '.join(COORDINATE_POLICIES)}")
        if subkey == "level" and value not in ACCESS_LEVELS:
            raise SectionError(section, f"access level '{value}' is not one of "
                                        f"{', '.join(ACCESS_LEVELS)}")
    # C46: sources[].licence is vocab-validated against the SAME contract vocab as the top-level
    # licence (killing the free-text seam), and profile against the attribution-profile vocab. The
    # <select> only offers vocab values, so a normal submit is always valid; this fail-closes a
    # hand-crafted out-of-vocab POST (the same fail-closed-at-the-form posture as access.coordinates).
    if kind == "license" and value not in LICENSE_IDS:
        raise SectionError(section, f"licence '{value}' is not a recognised AusMT licence id "
                                    "(pick one from the list)")
    if kind == "profile" and value not in SOURCE_PROFILES:
        raise SectionError(section, f"attribution profile '{value}' is not one of "
                                    f"{', '.join(SOURCE_PROFILES)}")
    # §2a: the typed related-identifiers presets. Fail-closed like access.coordinates / profile — the
    # <select> only offers vocab values, so a normal submit is always valid; this rejects a hand-crafted
    # out-of-vocab POST (a mis-typed relation would publish a wrong provenance claim).
    if kind == "relation" and value not in RELATION_TYPES:
        raise SectionError(section, f"relation '{value}' is not one of "
                                    f"{', '.join(RELATION_TYPES)}")
    if kind == "identifier_type" and value not in IDENTIFIER_TYPES:
        raise SectionError(section, f"identifier type '{value}' is not one of "
                                    f"{', '.join(IDENTIFIER_TYPES)}")
    # D-L1: the data level a related_identifiers row points at. Fail-closed like relation/identifier_type
    # — an out-of-vocab level auto-derives a wrong relation, so it must block, not ship.
    if kind == "identifies" and value not in IDENTIFIES_LEVELS:
        raise SectionError(section, f"data level '{value}' is not one of "
                                    f"{', '.join(IDENTIFIES_LEVELS)}")


# ---- assembly -----------------------------------------------------------------------------------

def _form_get(form: dict, key: str) -> str:
    v = form.get(key)
    if v is None:
        return ""
    # Textarea/CRLF hygiene, matching app._build_patch: never embed a bare \r into the yaml.
    return str(v).replace("\r\n", "\n").replace("\r", "\n").strip()


def _original_snapshot(form: dict, section: str):
    """Parse the hidden o_<section> snapshot of the ORIGINAL value (canonical JSON). Absent/blank =>
    the section was not present in the original (sentinel: the module returns a distinct marker)."""
    raw = form.get(f"o_{section}")
    if raw is None or raw == "":
        return _ABSENT
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return _ABSENT


_ABSENT = object()  # the section had no original value (distinct from a real null)

# IDCONS D2 (SPEC §3): keys a section's assembler MANAGES itself — so their absence from the assembled
# value is INTENTIONAL and the unmodelled-key carry-forward must NOT resurrect them. access.coordinate_-
# overrides is the one such key: _resolve_coordinate_overrides may deliberately DROP it (the C42 set-all-
# to-inherit-removes-the-key path), so carrying it back from the snapshot would un-delete a curator's
# removal. Every other section is fully covered by "modelled subfields ∪ nothing", so the map is sparse.
_SPECIAL_MANAGED_KEYS: dict[str, set[str]] = {"access": {"coordinate_overrides"}}


def _assemble_map(form: dict, section: str):
    """Build a MAP section dict from its s_<section>_<subkey> inputs. A sub-field left empty becomes
    None IF that sub-key was present in the original section (clearing it), and is OMITTED if the
    original section did not carry it (never introduce an empty key the source lacked — mirrors
    apply_patch's own rule one level down, so an unchanged submit round-trips exactly).

    organisation may have been a BARE STRING in the original (0.1 flat form): when the original was a
    string and only the name is filled (ror empty), re-emit the bare string so an unchanged submit is
    a true no-op; a filled ror upgrades it to a map."""
    subfields = MAP_SECTIONS[section]
    original = _original_snapshot(form, section)
    original_keys: set[str] = set()
    original_is_str = isinstance(original, str)
    if isinstance(original, dict):
        original_keys = set(original.keys())

    out: dict = {}
    for subkey, _label, _ph, kind in subfields:
        if kind == "levels":
            levels = _collect_levels(form, section, subkey, original)
            # Include only when non-empty or the original carried the key (mirrors the scalar rule:
            # never introduce an empty list the source lacked, so an all-empty map assembles to {}).
            if levels or subkey in original_keys:
                out[subkey] = levels
            continue
        if kind == "bool":
            # A checkbox (C46 attribution.changes_made) submits its value when CHECKED and is ABSENT
            # when unchecked (mirrors _collect_levels' `is not None` test). Present => True. Unchecked:
            # null it to False only if the original carried the key (a real change); never INTRODUCE
            # it on a section that lacked it (the round-trip / never-introduce-an-absent-key rule).
            if form.get(f"s_{section}_{subkey}") is not None:
                out[subkey] = True
            elif subkey in original_keys:
                out[subkey] = False
            continue
        value = _form_get(form, f"s_{section}_{subkey}")
        _validate_scalar(section, subkey, kind, value)
        if value == "":
            # Preserve a previously-present key as null; do not introduce an absent one.
            if original_is_str and subkey == "name":
                # organisation-as-string: the name carried the string; empty name + no ror => the
                # section becomes empty (handled by the snapshot compare in assemble_section).
                continue
            if subkey in original_keys:
                out[subkey] = None
            continue
        out[subkey] = value

    # C43 Stage-4: the per-station coordinate-access overrides live inside the access section, beside
    # the #53 survey-level `coordinates` select. Only ONE of the access-editing forms models the map:
    # the stations-panel coord-policy-form POSTs s_access_coordinate_overrides; the Metadata-tab per-
    # section access form does NOT render that field at all. So the field's ABSENCE and an explicit
    # EMPTY map mean OPPOSITE things and are resolved apart (_resolve_coordinate_overrides) — else an
    # ordinary access edit (change level/embargo/contact) silently drops a withheld/generalised station
    # back to the survey default, serving its TRUE coordinates (a coordinate-privacy leak, C42).
    if section == "access":
        overrides = _resolve_coordinate_overrides(form, original)
        if overrides:
            out["coordinate_overrides"] = overrides

    # IDCONS D2 (SPEC §3) — carry forward UNMODELLED original keys verbatim. Any key the source section
    # carried that the widget no longer models (the retired flat identifier keys dataset_doi / project /
    # related_publication(_doi), OR any unknown/legacy key the editor never modelled) is re-emitted exactly
    # as stored, so the assembled value still equals the o_<section> snapshot on an untouched section
    # (-> _OMIT, byte-preserved) and, on a real edit elsewhere in the section, apply_patch's surgical merge
    # leaves the carried key's line untouched. Managed keys (access.coordinate_overrides) are excluded so a
    # deliberate removal is not undone. This is the "assembler keeps round-tripping unknown/legacy keys" rule.
    if isinstance(original, dict):
        managed = {sk for sk, *_ in subfields} | _SPECIAL_MANAGED_KEYS.get(section, set())
        for k, v in original.items():
            if k not in managed and k not in out:
                out[k] = v

    # organisation bare-string round-trip: original was a string, curator left ror empty, name set.
    if section == "organisation" and original_is_str:
        ror = out.get("ror")
        name = out.get("name")
        if not ror and isinstance(name, str):
            return name  # re-emit the bare string exactly
    return out


def _resolve_coordinate_overrides(form: dict, original) -> dict:
    """The access.coordinate_overrides map to emit, distinguishing field-ABSENT from field-EMPTY —
    the C42 coordinate-privacy contract (a withheld/generalised station must NEVER silently un-mask).

      * field ABSENT (form.get is None): the submitting form does not model overrides (the Metadata-
        tab per-section access form), so an unrelated access edit must PRESERVE the survey's existing
        map. Re-emit it verbatim from the o_access snapshot (`original`); apply_patch's surgical merge
        then leaves it byte-clean. Absent + no original map => {} (nothing to preserve; byte-unchanged).
      * field PRESENT (the stations-panel coord-policy-form): assemble it. A non-empty map is written
        verbatim; an empty / all-inherit map returns {} so apply_patch DELETES a previously-pinned key
        (the intended set-all-to-inherit-removes-the-key — NO over-preservation regression).

    The preserved values are NOT re-validated here: they came from the survey's own stored access
    section (the same o_access anchor the four modelled scalars round-trip through), and the engine
    validator runs on the merged result at preview time. The field-PRESENT branch fail-closes on vocab
    exactly as before (_assemble_coordinate_overrides)."""
    if form.get("s_access_coordinate_overrides") is None:
        if isinstance(original, dict):
            orig = original.get("coordinate_overrides")
            if isinstance(orig, dict) and orig:
                return dict(orig)
        return {}
    return _assemble_coordinate_overrides(form)


def _assemble_coordinate_overrides(form: dict) -> dict:
    """Assemble access.coordinate_overrides (C43 Stage-4) from the stations-panel fieldset. The panel
    builds a {BASE_station_id: policy} map from REAL served station records — keys are NEVER free-text
    — and submits it as ONE canonical-JSON field, s_access_coordinate_overrides; a station left at
    INHERIT is simply ABSENT from the map (it follows the survey default). Returns {} for an absent or
    empty payload (the caller then writes no key — the byte-unchanged promise).

    Fail-closed like the #53 survey-level select: each VALUE must be a member of COORDINATE_POLICIES
    (an unknown policy, a non-mapping payload, or malformed JSON is a SectionError — never silently
    assembled or dropped). Override KEYS are NOT validated here: the gateway APP image is content-blind
    (it never imports engine/ and has no authoritative station list), so it cannot derive a survey's
    real BASE station ids — the authoritative key gate is the engine's validate_overrides at build time
    (fail-closed, survey-granularity drop) plus the validator the merge runs. The KEY-PARITY pin feeds
    THIS assembly through the real engine validator so a mis-keyed / variant-suffixed override is caught
    engine-truth, not by a hand-typed expectation."""
    raw = _form_get(form, "s_access_coordinate_overrides")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        raise SectionError("access",
                           "coordinate overrides: the per-station policy map is not valid JSON")
    if not isinstance(parsed, dict):
        raise SectionError("access",
                           "coordinate overrides: expected a {station id: policy} mapping")
    overrides: dict = {}
    for sid, pol in parsed.items():
        policy = str(pol).strip().lower() if pol not in (None, "") else ""
        if policy not in COORDINATE_POLICIES:
            raise SectionError("access", f"coordinate override for '{sid}': '{pol}' is not one of "
                                         f"{', '.join(COORDINATE_POLICIES)}")
        overrides[str(sid)] = policy
    return overrides


def _collect_levels(form: dict, section: str, subkey: str, original) -> list[str]:
    """time_series.levels_available: gather the checked c_<section>_<value> boxes, preserving the
    canonical order. An original value that carried levels outside the known set is preserved via the
    advanced-JSON fallback, not here (a curator who needs an exotic level uses the raw box)."""
    checked = []
    for level in TIME_SERIES_LEVELS:
        if form.get(f"c_{section}_{subkey}_{level}") is not None:
            checked.append(level)
    return checked


def _assemble_list(form: dict, section: str) -> list:
    """Build a LIST section from its l_<section>_<i>_<subkey> rows. A row whose every sub-field is
    empty is DROPPED (the spare-blank-row degradation: extra empty rows never pollute the yaml). A
    partially-filled row is kept and its known-format fields validated."""
    subfields = LIST_SECTIONS[section]
    modelled = {sk for sk, *_ in subfields}
    optional = _OPTIONAL_LIST_KEYS.get(section, frozenset())
    original = _original_snapshot(form, section)
    rows: list[dict] = []
    for i in _row_indices(form, section):
        row: dict = {}
        any_value = False
        # The correspondingly-indexed original row (the render assigns row index i to original[i]) — used
        # to decide whether an EMPTY optional key was already present (keep it null) or is being newly
        # introduced (skip it), so an unchanged row round-trips to its snapshot rather than gaining nulls.
        orig_row = (original[i] if isinstance(original, list) and i < len(original)
                    and isinstance(original[i], dict) else {})
        for subkey, _label, _ph, kind in subfields:
            value = _form_get(form, f"l_{section}_{i}_{subkey}")
            if value:
                _validate_scalar(section, subkey, kind, value)
                any_value = True
            # D-L (SPEC §9): an OPTIONAL sub-key (identifies + the acquisition fields) is written back only
            # when it has a value OR the original row already carried it — never introduce an empty one the
            # source row lacked (mirrors the map scalar rule; keeps a corpus row's round-trip byte-clean).
            if subkey in optional and not value and subkey not in orig_row:
                continue
            row[subkey] = value if value else None
        # D-L2 (SPEC §9.2): when the row states a data LEVEL, the DataCite relation DERIVES from it — the
        # relation control is not shown on an identifies row, so the form carries no explicit relation and
        # the server writes the derived value. A legacy row (no identifies) keeps whatever relation it
        # posted, untouched (backward compatible). An out-of-vocab identifies already FAILed above.
        idf = row.get("identifies")
        if idf and str(idf).strip() in IDENTIFIES_LEVELS:
            row["relation"] = derived_relation(idf)
            any_value = True
        # IDCONS D2 (SPEC §3) — carry forward UNMODELLED per-row keys from the correspondingly-indexed
        # original row (the render assigns row index i to original[i]). The retired instruments[].pid — and
        # any unknown/legacy per-row key — is re-emitted verbatim, so an untouched list reassembles equal to
        # its o_<section> snapshot (-> _OMIT, byte-preserved) instead of the wholesale-replace dropping it.
        # A carried non-empty value also keeps an otherwise-blank row alive. Guarded on a dict original row
        # so a bare-string list item (e.g. a template publication) never misaligns.
        if isinstance(original, list) and i < len(original) and isinstance(original[i], dict):
            for k, v in original[i].items():
                if k not in modelled and k not in row:
                    row[k] = v
                    if v not in (None, ""):
                        any_value = True
        if any_value:
            rows.append(row)
    return rows


def _row_indices(form: dict, section: str) -> list[int]:
    """The row indices present in the form for a list section, sorted. Rows are discovered from the
    l_<section>_<i>_<subkey> field names so the count is not fixed server-side (JS can add rows; the
    no-JS fallback renders a fixed set)."""
    prefix = f"l_{section}_"
    idx: set[int] = set()
    for key in form:
        if not key.startswith(prefix):
            continue
        rest = key[len(prefix):]
        num, _, _sub = rest.partition("_")
        if num.isdigit():
            idx.add(int(num))
    return sorted(idx)


def assemble_section(form: dict, section: str):
    """Assemble ONE section's value, applying the precedence:
      1. j_<section> non-empty  -> legacy JSON path (overrides the widgets).
      2. else s_/l_/c_ widgets.
      3. if the result == the original snapshot -> return _OMIT (no-op; drop from the patch).

    Returns either the assembled value or the _OMIT sentinel. Raises SectionError on a malformed
    advanced-JSON blob or a bad known-format field."""
    advanced = _form_get(form, f"j_{section}")
    if advanced:
        try:
            value = json.loads(advanced)
        except ValueError:
            raise SectionError(section, f"the advanced JSON for {section} is not valid JSON")
    elif section in MAP_SECTIONS:
        value = _assemble_map(form, section)
    elif section in LIST_SECTIONS:
        value = _assemble_list(form, section)
    else:  # pragma: no cover -- callers only pass WIDGET_SECTIONS
        return _OMIT

    original = _original_snapshot(form, section)
    if original is not _ABSENT and value == original:
        return _OMIT  # unchanged -> leave the key exactly as it was (round-trip)
    if original is _ABSENT and value in (None, "", [], {}):
        return _OMIT  # never introduce an empty section the source did not carry
    return value


_OMIT = object()  # assemble_section: this section contributes nothing to the patch


def build_section_patch(form: dict) -> tuple[dict, list[SectionError]]:
    """Assemble every widget section into a patch fragment, collecting per-section errors instead of
    failing on the first. Returns (patch_fragment, errors). The caller (app._build_patch) merges this
    with the scalar fields and, if errors is non-empty, re-renders the form with them."""
    patch: dict = {}
    errors: list[SectionError] = []
    for section in WIDGET_SECTIONS:
        try:
            value = assemble_section(form, section)
        except SectionError as exc:
            errors.append(exc)
            continue
        if value is not _OMIT:
            patch[section] = value
    return patch, errors
