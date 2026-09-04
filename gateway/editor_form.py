"""Structured metadata-editor form assembly.

The curator edit form (gateway/curatorpage.py::render_edit_form) must NOT render a structured
survey.yaml section as a raw JSON textarea: a geophysicist is not a JSON author, so the sections are
per-section widgets. This module is the SERVER-SIDE half that turns the widget inputs back into
the same patch the JSON textareas produced — so the preview/confirm/commit pipeline underneath is
byte-identical (the round-trip test pins that: render the form from a real survey.yaml, submit it
unchanged, and the preview shows NO diff).

It is pure stdlib (json only - NOT yaml; the gateway never parses survey content). It does
NO git and NO version logic; it only maps form fields <-> section dicts and validates the formats it
knows (ORCID via gateway.orcid, DOI "10." prefix, ISO date, access.level enum).

Field-naming scheme (all rendered by curatorpage; all consumed here):
  f_<scalar>                       top-level scalars (project_name/name/region/license/abstract) —
                                   unchanged from the pre-widget form, still handled in app._build_patch.
  s_<section>_<subkey>             a map section's scalar sub-field (organisation.name, access.contact…)
  l_<section>_<i>_<subkey>         row i of a repeatable list section (creators, organisations…)
  c_<section>_<value>             a checkbox in a set (time_series.levels_available)
  c_<section>_<i>_<token>          a checkbox in a PER-ROW set (organisations roles[])
  c_<section>_primary              a radio across a list section's rows, valued with the row index
                                   (organisations primary_custodian: at most one row may carry it)
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
# scalar sub-keys. These mirror docs/docs/reference/survey-yaml.md exactly - no invented fields.

# Map sections rendered as labelled inputs. (key, label, placeholder, kind) per sub-field;
# kind drives the input type / validation: "text" | "doi" | "orcid" | "ror" | "date" | "email".
MAP_SECTIONS: dict[str, list[tuple[str, str, str, str]]] = {
    "organisation": [
        ("name", "Name", "University of Example", "text"),
        ("ror", "ROR id", "https://ror.org/03yghzc09", "ror"),
    ],
    # The flat dataset-identifier inputs are RETIRED from the editor UI. The typed
    # related_identifiers list (below, group (b) of the "Identifiers & PIDs" page) is now the ONLY place a
    # dataset-level DOI/PID is edited; the legacy "Related publication (+DOI)" pair is superseded by
    # publications[]; identifiers.project was a dead orphan. The schema KEYS stay readable (the engine keeps
    # its flat-key fallback reads until the corpus migration + follow-up), so a survey that still carries
    # them must ROUND-TRIP byte-clean through an unrelated edit — handled generically by the unmodelled-key
    # carry-forward in _assemble_map (proven RED by test_retired_identifier_keys_survive_unrelated_edit).
    # Only the two survey/project-level PIDs a curator legitimately sets stay modelled here.
    "identifiers": [
        ("project_raid", "Project RAiD", "https://raid.org/10.xxxx/xxxxx", "text"),
        # (identifiers design): the ONE survey/platform-level instrument PID (PIDINST, e.g.
        # 10.82388/<id>) - the survey-layer counterpart to the deep per-serial instruments[].pid.
        # Additive; the surveys validator only WARNS on its format, so it is plain "text" here
        # (a light hint, never a form block) — the same posture as project_raid above.
        ("instrument_pid", "Instrument PID (survey/platform)", "10.82388/… or an https:// URL", "text"),
    ],
    # The rights of THIS AusMT release. custodian may differ from organisation.name;
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
        # The SURVEY-LEVEL coordinate-access policy (exact/generalised/withheld). Its key
        # ("coordinates") and value vocab (COORDINATE_POLICIES) are EXACTLY what the engine's
        # extract/_coordaccess.parse_coordinate_policy reads (access.get("coordinates")), so a set
        # value is never a silent no-op. Blank/unset => the key is not written (absent => exact; the
        # record's zero-change promise). The per-station coordinate_overrides map is the Stage-4
        # stations panel, NOT here.
        ("coordinates", "Coordinate access", "", "select"),
        ("embargo_until", "Embargo until", "", "date"),
        ("contact", "Access contact", "email or role address", "email"),
    ],
    "time_series": [
        # time_series.collection_pid is RETIRED from the editor UI - a dataset-level
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
    # The CITATION block - preference and guidance over the
    # identifier set, never a duplicate bibliographic record. Only the two FLAT sub-keys are modelled
    # as ordinary scalars here; preferred_identifier is the NESTED {scheme, identifier} pair (managed
    # by _resolve_preferred_identifier, registered in _SPECIAL_MANAGED_KEYS so the carry-forward does
    # not resurrect a deliberate removal) and additional[] rides the unmodelled-key carry-forward
    # verbatim. Flat scheme/identifier sub-keys are NEVER written: the validator's CITATION_KEYS
    # allow-list would WARN them as unrecognised.
    "citation": [
        ("preferred_text", "Preferred citation text (verbatim)",
         "the custodian's own citation wording, exactly as given", "text"),
        ("text_source", "Where that wording came from", "", "text_source"),
    ],
    # identity_classification is the DESIGNATION
    # HOME - the mapping {case, represents[] (case_a) | own_identifiers[] (case_b)} that says which
    # identifiers this record IS. Only `case` is an ordinary scalar; the two pair LISTS are managed
    # (_resolve_designation_rows) with the absent-vs-empty rule, because citation.preferred_identifier
    # FAILs at the validator unless it equals one of the designated pairs.
    "identity_classification": [
        ("case", "Case", "", "identity_case"),
    ],
}

# List (repeatable-row) sections: per-row scalar sub-fields.
LIST_SECTIONS: dict[str, list[tuple[str, str, str, str]]] = {
    # the contributor-credit model (editor typed rows): creators[] - who the citation names, an ORDERED
    # editorial list (order IS the citation author order, so the row renders with up/down reorder controls
    # in curatorpage). name_type is FAIL-CLOSED (person|organisation); orcid is people-only and ror
    # organisations-only, both OPTIONAL curator hints (WARNING-only at the validator). orcid/ror sit in
    # _OPTIONAL_LIST_KEYS so an org creator (no orcid) / person creator (no ror) round-trips to _OMIT
    # rather than gaining a spray of null keys.
    "creators": [
        ("name", "Name", "Family, Given  or  Organisation name", "text"),
        ("name_type", "Person or organisation", "", "name_type"),
        ("orcid", "ORCID (people)", "0000-0002-1825-0097", "orcid"),
        ("ror", "ROR id (organisations)", "https://ror.org/03yghzc09", "ror"),
    ],
    # contributors[]: who did what, repeatable. name_type AND role are
    # both FAIL-CLOSED (role over the 8-token DataCite contributorType subset); orcid/ror optional as
    # for creators. NOT ordered (no reorder controls), unlike creators.
    "contributors": [
        ("name", "Name", "Family, Given  or  Organisation name", "text"),
        ("name_type", "Person or organisation", "", "name_type"),
        ("role", "Role (what they did)", "", "role"),
        ("orcid", "ORCID (people)", "0000-0002-1825-0097", "orcid"),
        ("ror", "ROR id (organisations)", "https://ror.org/03yghzc09", "ror"),
    ],
    # Organisations[] is the FULL role statement where the parties
    # genuinely differ (industry-collected government releases make collector / custodian / publisher /
    # distributor different parties). The scalar organisation: block keeps its meaning (primary
    # custodial responsibility, the discovery projection). Two sub-fields are NOT plain scalars: roles
    # is a PER-ROW checkbox group over ORG_ROLES_ORDERED (fail-closed) and primary_custodian is a radio
    # ACROSS the rows (at most one, and only on a row that ticks custodian). PUBLISHER is explicit and
    # never inferred.
    "organisations": [
        ("name", "Name", "e.g. Geological Survey of South Australia", "text"),
        ("ror", "ROR id", "https://ror.org/04y8k6r48", "ror"),
        ("roles", "What this organisation is", "", "org_roles"),
        ("primary_custodian", "Primary custodian", "", "primary_custodian"),
    ],
    # Acknowledgements[] rows {text, type?, source?}. The wording is
    # the row's whole payload and is preserved VERBATIM; type is the contract's CANDIDATE vocabulary, so
    # the validator WARNs rather than blocks an unknown token and the editor mirrors that (a stored
    # out-of-vocab type must round-trip, not lock the curator out of the section).
    "acknowledgements": [
        ("text", "Wording (verbatim)", "the exact wording that must appear", "text"),
        ("type", "Type", "", "ack_type"),
        ("source", "Source", "who requires this wording", "text"),
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
    # The per-row instruments[].pid input is RETIRED from the editor UI. The
    # survey/platform-level PID is recorded once as identifiers.instrument_pid (group (c) of the new page)
    # or as a typed related_identifiers row; the per-serial key stays readable (engine fallback +
    # per-row carry-forward round-trip) so an un-migrated instruments[].pid survives an unrelated edit.
    "instruments": [
        ("manufacturer", "Manufacturer", "Phoenix", "text"),
        ("model", "Model", "MTU-5C", "text"),
    ],
    # The "Source datasets" section is RETIRED from the editor UI. Its acquisition
    # fields (title, licence-as-obtained, retrieved, attribution statement, attribution profile) are now
    # OPTIONAL keys on a related_identifiers row (an upstream dataset AusMT obtained is just another typed
    # row, identifies: entire). The `sources` LIST_SECTIONS registration is GONE, so build_section_patch
    # never assembles the key — a legacy sources[] on disk is byte-preserved (never entered into any
    # patch; proven RED by test_editor_sources_section_retired_byte_preserved). The engine keeps reading
    # sources[], so nothing served changes.
    #
    # + D-L: the single typed list of provenance relations to identifiers AusMT does NOT own.
    # The primary per-row control is `identifies` (WHAT the identifier points at, in NCI Table 1 data-level
    # terms) — FIRST on the row and FAIL-CLOSED like relation/identifier_type. The DataCite `relation`
    # DERIVES from `identifies` server-side, so it is not a curator control on an identifies
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

# D-L: the related_identifiers row sub-keys that are OPTIONAL - `identifies` (absent on a legacy
# row) plus the acquisition fields merged from the retired sources[] list. Unlike the always-emitted typed
# core (identifier / identifier_type / relation / custodian), an empty optional key is written back ONLY
# when the ORIGINAL row already carried it, so a corpus row that has no acquisition fields (and a legacy
# row that has no identifies) reassembles to its snapshot -> _OMIT, instead of gaining a spray of null
# keys that would break the round-trip and strip the row's INFERRED-REVIEW comment. Keyed by section, so
# no other list section changes behaviour.
_OPTIONAL_LIST_KEYS: dict[str, frozenset] = {
    "related_identifiers": frozenset({"identifies", "title", "licence", "retrieved", "statement",
                                      "profile"}),
    # the contributor-credit model: orcid is people-only and ror organisations-only, so on any given credit
    # row one of them is legitimately absent. Marked OPTIONAL so an empty orcid/ror is written back ONLY
    # when the original row already carried it - an org creator {name, name_type: organisation, ror} and a
    # person creator {name, name_type: person, orcid} each round-trip to their snapshot (-> _OMIT) instead
    # of gaining null orcid/ror keys that would break the byte-clean round-trip.
    "creators": frozenset({"orcid", "ror"}),
    "contributors": frozenset({"orcid", "ror"}),
    # Acknowledgements type/source are optional (text is the row). An unfilled optional key is
    # written back only when the original row carried it, so a text-only row round-trips byte-clean.
    "acknowledgements": frozenset({"type", "source"}),
}

# List-section sub-keys that are OMITTED OUTRIGHT when empty - stronger than _OPTIONAL_LIST_KEYS,
# which writes null back when the original row carried the key. organisations[].ror is the one such
# key: the schema makes it optional and the corpus migration is careful NEVER to write `ror: null`
# (an absent ROR is "not recorded", a null ROR is a claim that there is none), so CLEARING a ror
# removes the key rather than nulling it.
_NEVER_NULL_LIST_KEYS: dict[str, frozenset] = {"organisations": frozenset({"ror"})}

# access.level enum (validator/normalize; mirrors add-survey.html's <select>).
ACCESS_LEVELS = ("open", "metadata_only", "embargoed")

# The access.coordinates enum - the SURVEY-LEVEL coordinate-access policy. Declared like ACCESS_LEVELS
# and IDENTICAL (key + value spellings) to the engine's extract/_coordaccess.COORDINATE_POLICIES, which
# parse_coordinate_policy reads from access["coordinates"]. "exact" is the default (absent => exact); the
# editor never WRITES the key at the default, so a survey that never sets a policy stays byte-unchanged.
# A key/spelling mismatch here would make the setting a silent no-op — pinned by the key-parity test,
# which feeds the editor-assembled block through the REAL engine parser (engine-truth, not a hand-typed
# expectation).
COORDINATE_POLICIES = ("exact", "generalised", "withheld")

# Licence vocab for the licence <select>s (the top-level `license` and each sources[].licence).
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
# Custodian attribution-profile vocab (sources[].profile). "generic" is the default synthesis;
# "ga" prescribes the Geoscience Australia form (and makes attribution.statement required at validate).
SOURCE_PROFILES = ("ga", "generic")

# (identifiers design - the related-identifiers model): the two FROZEN, FAIL-CLOSED vocabularies the
# typed relation adds. RELATION_TYPES is the curated DataCite subset as the editor presets;
# IDENTIFIER_TYPES is the small set AusMT records against. Both are BAKED copies — the gateway APP image
# is content-blind (ships only gateway/, never the surveys validator — see gateway.Dockerfile), so a
# runtime import of the sibling vocab is impossible; the copies are PINNED byte-for-byte to the surveys
# validator's RELATION_TYPES / IDENTIFIER_TYPES by test_editor_form.py (the same parity-pin discipline
# that guards LICENSE_IDS against the engine contract). Ordered tuples give the <select> a stable preset
# order; the pin compares them as sets (the validator holds frozensets). An out-of-vocab value FAILs at
# the form (SectionError) — byte-identical posture to access.coordinates, because a mis-typed relation
# publishes a WRONG provenance claim and must block, not ship.
RELATION_TYPES = ("IsDerivedFrom", "IsVariantFormOf", "IsSupplementTo", "Cites",
                  "IsPartOf", "IsSourceOf",
                  "IsDocumentedBy")   # activity-scope records (e.g. ANSIR project pages)
IDENTIFIER_TYPES = ("DOI", "Handle", "URL", "RAiD")

# "Identifiers by data level". Every related_identifiers
# row states WHAT it points at in NCI Table 1 data-level terms; the DataCite relation then DERIVES from
# the level, so `relation` is not a curator-facing control on an identifies row. IDENTIFIES_LEVELS
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
    """The DataCite relation a given `identifies` level auto-derives to. None when the level is
    absent/blank/out-of-vocab (nothing to derive). Pinned to the surveys validator's derived_relation."""
    if identifies in (None, ""):
        return None
    return IDENTIFIES_RELATION.get(str(identifies).strip())

# Contributor credit model. The typed
# creators[]/contributors[] editor rows. Both are FROZEN, FAIL-CLOSED vocabs - BAKED copies (the gateway
# APP image is content-blind: it ships only gateway/, never the surveys validator), PINNED to the surveys
# validator's NAME_TYPES / CONTRIBUTOR_ROLES by test_editor_form.py (the same parity-pin discipline that
# guards RELATION_TYPES / IDENTIFIER_TYPES). Ordered tuples give the <select> a stable preset order; the
# pin compares them as sets (the validator holds frozensets). An out-of-vocab value FAILs at the form
# (SectionError) - byte-identical posture to access.coordinates / relation, because a mis-typed name_type
# mis-classifies the actor (wrong citation rendering) and a mis-typed role publishes a wrong provenance
# claim about who did what, so both must block rather than ship.
NAME_TYPES = ("person", "organisation")
CONTRIBUTOR_ROLES = ("ProjectLeader", "ProjectMember", "DataCollector", "ContactPerson",
                     "DataCurator", "Sponsor", "RightsHolder", "Distributor")

# MTCAT 2.0 curated homes. BAKED copies of the surveys validator's frozen vocabularies - the
# gateway APP image is content-blind (it ships only gateway/, never the sibling validator), so a
# runtime import is impossible; test_editor_form.py::test_mtcat20_vocabs_match_the_vendored_validator
# pins every one of them (membership AND, where the validator declares an order, the order). The
# POSTURE of each mirrors the validator exactly:
#   ORG_ROLES_ORDERED       FAIL-CLOSED (a mis-typed role publishes a wrong claim about who holds,
#                           publishes or collected the data).
#   CITATION_TEXT_SOURCES   FAIL-CLOSED (where citation wording came from is a provenance claim).
#   IDENTITY_CLASSIFICATIONS FAIL-CLOSED (the case decides which designation list is legal).
#   ACKNOWLEDGEMENT_TYPES   WARN-only at the validator (a CANDIDATE vocabulary still being validated
#                           against real holdings), so the editor does NOT fail-close on it either -
#                           a stored unknown type must round-trip rather than lock the section.
ORG_ROLES_ORDERED = ("publisher", "custodian", "distributor", "data_collector",
                     "rights_holder", "hosting_institution")
CITATION_TEXT_SOURCES = ("source_provided", "ausmt_generated")
IDENTITY_CLASSIFICATIONS = ("case_a", "case_b")
ACKNOWLEDGEMENT_TYPES = ("required_source", "custodian", "community", "traditional_owners",
                         "field_support", "infrastructure", "access_provider")
# The two sub-keys of every MTCAT 2.0 identifier pair (citation.preferred_identifier and each
# identity_classification designation row). BOTH are required when the pair is present: a half-
# declared identifier cannot anchor the doi/primary/preferred chain, so the editor fail-closes.
IDENTIFIER_PAIR_KEYS = ("scheme", "identifier")
# The two designation lists identity_classification may carry, and the case each belongs to.
IDENTITY_DESIGNATION_LISTS = ("represents", "own_identifiers")

# the contributor-credit model (the unified People & credit panel: "one huge
# list which makes no sense"): the served schema keeps creators[] (citation authors) and contributors[]
# (who-did-what roles) as TWO lists, but the editor presents them as ONE panel of unified rows
# (one row per person/org). The panel is the `people` section: its rows POST as l_people_<i>_<subkey>
# (name / name_type / orcid / ror), a cited-author checkbox l_people_<i>_cited, and one checkbox per role
# l_people_<i>_role_<Token>. assemble_people() DECOMPOSES those rows back into the two lists, so
# the served creators[]/contributors[] shape is byte-for-byte unchanged (UI/assembly only). The two lists
# stay registered as LIST_SECTIONS above for the per-list advanced-JSON escape and the vocab pins; they
# are NOT assembled by the generic build_section_patch loop (they are decomposed here instead).
PEOPLE_SECTION = "people"
_PEOPLE_DECOMPOSED = ("creators", "contributors")
# There is NO Convert action. The corpus migration has run (creators/contributors are
# seeded and the two retired flat keys deleted), the engine reads neither, and the editor models
# neither, so there is nothing to convert and no delete directive to carry. A survey
# that somehow still carries a retired key is simply an unmodelled key: byte-preserved, never patched.

# time_series.levels_available known values (docs example). A hinted free-text "other" is NOT offered
# — the checkboxes plus the advanced JSON fallback cover the rest.
TIME_SERIES_LEVELS = ("raw_packed", "level0", "level1")

# All sections this module models with widgets (map + list). Anything else stays JSON-only.
WIDGET_SECTIONS = tuple(MAP_SECTIONS) + tuple(LIST_SECTIONS)

# Sections rendered as a raw-JSON panel ONLY (schema too nested/open-ended for widgets), still
# assembled into the patch: j_<section> JSON with the o_<section> round-trip anchor, blank means
# unchanged. `care` must NOT sit outside the assembly loop: the panel renders, prefilled and
# editable, and the curator's Indigenous data-governance edit would be silently discarded.
# A rendered control is a promise that the edit lands, so this register is
# what build_section_patch iterates BESIDE the widget sections.
JSON_SECTIONS = ("care",)


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
        # Two selects live in the access section: level and coordinates. Each validates against
        # its OWN vocab — a single 'not in ACCESS_LEVELS' check would reject every coordinates value.
        if subkey == "coordinates" and value not in COORDINATE_POLICIES:
            raise SectionError(section, f"coordinate access '{value}' is not one of "
                                        f"{', '.join(COORDINATE_POLICIES)}")
        if subkey == "level" and value not in ACCESS_LEVELS:
            raise SectionError(section, f"access level '{value}' is not one of "
                                        f"{', '.join(ACCESS_LEVELS)}")
    # Sources[].licence is vocab-validated against the SAME contract vocab as the top-level
    # licence (killing the free-text seam), and profile against the attribution-profile vocab. The
    # <select> only offers vocab values, so a normal submit is always valid; this fail-closes a
    # hand-crafted out-of-vocab POST (the same fail-closed-at-the-form posture as access.coordinates).
    if kind == "license" and value not in LICENSE_IDS:
        raise SectionError(section, f"licence '{value}' is not a recognised AusMT licence id "
                                    "(pick one from the list)")
    if kind == "profile" and value not in SOURCE_PROFILES:
        raise SectionError(section, f"attribution profile '{value}' is not one of "
                                    f"{', '.join(SOURCE_PROFILES)}")
    # the typed related-identifiers presets. Fail-closed like access.coordinates / profile - the
    # <select> only offers vocab values, so a normal submit is always valid; this rejects a hand-crafted
    # out-of-vocab POST (a mis-typed relation would publish a wrong provenance claim).
    if kind == "relation" and value not in RELATION_TYPES:
        raise SectionError(section, f"relation '{value}' is not one of "
                                    f"{', '.join(RELATION_TYPES)}")
    if kind == "identifier_type" and value not in IDENTIFIER_TYPES:
        raise SectionError(section, f"identifier type '{value}' is not one of "
                                    f"{', '.join(IDENTIFIER_TYPES)}")
    # A related_identifiers row's "identifies" field names the data level the row points at, and is
    # fail-closed like relation and identifier_type: an out-of-vocabulary level derives a wrong
    # relation, so it must block rather than ship.
    if kind == "identifies" and value not in IDENTIFIES_LEVELS:
        raise SectionError(section, f"data level '{value}' is not one of "
                                    f"{', '.join(IDENTIFIES_LEVELS)}")
    # the contributor-credit model - the typed credit-row presets. Fail-closed like the vocabs above: the
    # <select> only offers vocab values, so a normal submit is always valid; this rejects a hand-crafted
    # out-of-vocab POST. A mis-typed name_type mis-classifies the actor (wrong citation rendering) and a
    # mis-typed role publishes a wrong provenance claim about who did what, so each must block, not ship.
    if kind == "name_type" and value not in NAME_TYPES:
        raise SectionError(section, f"'{value}' is not one of {', '.join(NAME_TYPES)} "
                                    "(person or organisation)")
    if kind == "role" and value not in CONTRIBUTOR_ROLES:
        raise SectionError(section, f"role '{value}' is not one of {', '.join(CONTRIBUTOR_ROLES)}")
    # The MTCAT 2.0 curated-home presets. Fail-closed exactly where the validator is: a wrong
    # text_source mis-states the provenance of published citation wording, and a wrong case makes the
    # designation list illegal. ack_type is deliberately NOT here (WARN-only at the validator).
    if kind == "text_source" and value not in CITATION_TEXT_SOURCES:
        raise SectionError(section, f"citation text source '{value}' is not one of "
                                    f"{', '.join(CITATION_TEXT_SOURCES)}")
    if kind == "identity_case" and value not in IDENTITY_CLASSIFICATIONS:
        raise SectionError(section, f"identity classification case '{value}' is not one of "
                                    f"{', '.join(IDENTITY_CLASSIFICATIONS)}")


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

# Keys a section's assembler MANAGES itself - so their absence from the assembled
# value is INTENTIONAL and the unmodelled-key carry-forward must NOT resurrect them. access.coordinate_-
# overrides is the one such key: _resolve_coordinate_overrides may deliberately DROP it (set-all-
# to-inherit-removes-the-key path), so carrying it back from the snapshot would un-delete a curator's
# removal. Every other section is fully covered by "modelled subfields ∪ nothing", so the map is sparse.
# Adds two more: citation.preferred_identifier (the nested pair, assembled both-or-neither by
# _resolve_preferred_identifier, which may deliberately DROP the key) and identity_classification's two
# designation lists (_resolve_designation_rows, same absent-vs-empty discipline).
_SPECIAL_MANAGED_KEYS: dict[str, set[str]] = {
    "access": {"coordinate_overrides"},
    "citation": {"preferred_identifier"},
    "identity_classification": {"represents", "own_identifiers"},
}


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
            # A checkbox (attribution.changes_made) submits its value when CHECKED and is ABSENT
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
            # Preserve a key the original carried as null; do not introduce an absent one.
            if original_is_str and subkey == "name":
                # organisation-as-string: the name carried the string; empty name + no ror => the
                # section becomes empty (handled by the snapshot compare in assemble_section).
                continue
            if subkey in original_keys:
                out[subkey] = None
            continue
        out[subkey] = value

    # The per-station coordinate-access overrides live inside the access section, beside
    # the #53 survey-level `coordinates` select. Only ONE of the access-editing forms models the map:
    # the stations-panel coord-policy-form POSTs s_access_coordinate_overrides; the Metadata-tab per-
    # section access form does NOT render that field at all. So the field's ABSENCE and an explicit
    # EMPTY map mean OPPOSITE things and are resolved apart (_resolve_coordinate_overrides) — else an
    # ordinary access edit (change level/embargo/contact) silently drops a withheld/generalised station
    # back to the survey default, serving its TRUE coordinates (a coordinate-privacy leak).
    if section == "access":
        overrides = _resolve_coordinate_overrides(form, original)
        if overrides:
            out["coordinate_overrides"] = overrides

    # citation.preferred_identifier is the NESTED {scheme, identifier} pair, assembled both-or-
    # neither and resolved with the SAME absent-vs-empty discipline as coordinate_overrides (a form
    # that does not render the pair PRESERVES the stored one; a rendered-and-emptied pair deletes it).
    if section == "citation":
        pref = _resolve_preferred_identifier(form, original)
        if pref:
            out["preferred_identifier"] = pref
        # text_source states where preferred_text came from, so it cannot stand alone.
        if out.get("text_source") and not out.get("preferred_text"):
            raise SectionError(section,
                               "citation text source states where the preferred citation TEXT came "
                               "from; add the preferred citation text, or clear the source")

    # identity_classification's two designation lists, same absent-vs-empty discipline. A present
    # list is NON-EMPTY at the validator (absent-not-empty), so an emptied list drops its key.
    if section == "identity_classification":
        for key in IDENTITY_DESIGNATION_LISTS:
            rows = _resolve_designation_rows(form, original, key)
            if rows:
                out[key] = rows

    # - carry forward UNMODELLED original keys verbatim. Any key the source section
    # carried that the widget does not model (the retired flat identifier keys dataset_doi / project /
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
    the coordinate-privacy contract (a withheld/generalised station must NEVER silently un-mask).

      * field ABSENT (form.get is None): the submitting form does not model overrides (the Metadata-
        tab per-section access form), so an unrelated access edit must PRESERVE the survey's existing
        map. Re-emit it verbatim from the o_access snapshot (`original`); apply_patch's surgical merge
        then leaves it byte-clean. Absent + no original map => {} (nothing to preserve; byte-unchanged).
      * field PRESENT (the stations-panel coord-policy-form): assemble it. A non-empty map is written
        verbatim; an empty / all-inherit map returns {} so apply_patch DELETES a pinned key
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


def _resolve_preferred_identifier(form: dict, original) -> dict:
    """citation.preferred_identifier, the NESTED {scheme, identifier} pair: the emitter carries the
    designation mapping, so the curator editor writes the pair.

    ABSENT-vs-EMPTY, the coordinate_overrides precedent: a form that does NOT render the pair inputs
    (neither s_citation_preferred_identifier_scheme nor _identifier is in the POST) PRESERVES the
    stored pair from the o_citation snapshot - load-bearing because apply_patch's surgical map merge
    DELETES a sub-key the assembled map lacks, so an unrelated preferred_text edit would otherwise
    silently un-declare the survey's preferred citation identifier. A rendered pair left EMPTY on both
    halves returns {} so the key is dropped (the deliberate removal).

    BOTH-OR-NEITHER: exactly one half filled is a SectionError. The validator FAILs a half-declared
    pair ("a half-declared identifier cannot anchor the citation invariant"), and silently dropping the
    typed half would lose curator input, so the form refuses it with a curator-facing message.

    The pair is NOT checked against identity_classification here: that cross-section invariant is the
    validator's (emitter FAIL) and the runner refuses the merge with the validator's own message.
    """
    scheme_raw = form.get("s_citation_preferred_identifier_scheme")
    ident_raw = form.get("s_citation_preferred_identifier_identifier")
    if scheme_raw is None and ident_raw is None:
        if isinstance(original, dict):
            stored = original.get("preferred_identifier")
            if isinstance(stored, dict) and stored:
                return dict(stored)
        return {}
    scheme = _form_get(form, "s_citation_preferred_identifier_scheme")
    identifier = _form_get(form, "s_citation_preferred_identifier_identifier")
    if scheme and identifier:
        return {"scheme": scheme, "identifier": identifier}
    if scheme or identifier:
        missing = "identifier" if scheme else "scheme"
        raise SectionError("citation",
                           f"preferred citation identifier: both scheme and identifier are required "
                           f"(missing: {missing}); a half-declared identifier cannot anchor the "
                           f"citation invariant. Fill both, or clear both.")
    return {}


def _resolve_designation_rows(form: dict, original, key: str) -> list:
    """One identity_classification designation list (`represents` for case_a, `own_identifiers` for
    case_b) as a list of complete {scheme, identifier} pairs.

    ABSENT-vs-EMPTY, the coordinate_overrides precedent: a form carrying NO
    l_identity_classification_<key>_* inputs did not render the list, so the stored designation is
    PRESERVED verbatim (an unrelated case edit must never un-designate the survey - that would turn a
    perfectly good citation.preferred_identifier into a validator FAIL). A rendered list whose rows are
    all blank returns [] so the key is dropped (a present list is non-empty at the validator).

    Each row is BOTH-OR-NEITHER: a wholly blank row is dropped (the spare-row degradation), a half row
    is a SectionError (the validator FAILs it, and dropping it would lose curator input)."""
    prefix = f"l_identity_classification_{key}_"
    if not any(k.startswith(prefix) for k in form):
        if isinstance(original, dict):
            stored = original.get(key)
            if isinstance(stored, list) and stored:
                return [dict(r) if isinstance(r, dict) else r for r in stored]
        return []
    rows: list = []
    for i in _row_indices(form, f"identity_classification_{key}"):
        scheme = _form_get(form, f"{prefix}{i}_scheme")
        identifier = _form_get(form, f"{prefix}{i}_identifier")
        if not scheme and not identifier:
            continue
        if not (scheme and identifier):
            missing = "identifier" if scheme else "scheme"
            raise SectionError("identity_classification",
                               f"{key} row {i + 1}: both scheme and identifier are required "
                               f"(missing: {missing}); a designated identifier is a COMPLETE pair")
        rows.append({"scheme": scheme, "identifier": identifier})
    return rows


def _collect_org_roles(form: dict, index: int, orig_row: dict) -> list:
    """organisations[<index>].roles from the per-row c_organisations_<i>_<role> checkbox group.

    FAIL-CLOSED: the rendered group offers ORG_ROLES_ORDERED only, so any other c_organisations_<i>_*
    token in the POST is hand-crafted and is REFUSED (a mis-typed role publishes a wrong claim about
    who holds, publishes or collected the data - the validator FAILs it, and so does the form).

    ORDER: the roles the ORIGINAL row already listed keep their stored order (so an untouched row
    reassembles equal to its snapshot and produces no diff); newly ticked roles are appended in the
    canonical ORG_ROLES_ORDERED order."""
    prefix = f"c_organisations_{index}_"
    ticked = set()
    for k in form:
        if not k.startswith(prefix):
            continue
        token = k[len(prefix):]
        if token not in ORG_ROLES_ORDERED:
            raise SectionError("organisations",
                               f"organisation role '{token}' is not one of "
                               f"{', '.join(ORG_ROLES_ORDERED)}")
        ticked.add(token)
    stored = orig_row.get("roles")
    stored_order = [str(r) for r in stored if isinstance(stored, list)] if isinstance(stored, list) else []
    out = [r for r in stored_order if r in ticked]
    out += [r for r in ORG_ROLES_ORDERED if r in ticked and r not in out]
    return out


def _org_primary_index(form: dict):
    """The row index the organisations primary-custodian RADIO selected, or None. The radio is ONE
    control across the whole list (mtcat's organisation is a deterministic projection of ONE explicitly
    curated primary custodian), valued with the row index; an unselected group posts nothing."""
    raw = _form_get(form, "c_organisations_primary")
    if not raw.isdigit():
        return None            # "" / the explicit "none" option / anything non-numeric: no selection
    return int(raw)


def _assemble_coordinate_overrides(form: dict) -> dict:
    """Assemble access.coordinate_overrides (Stage-4) from the stations-panel fieldset. The panel
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
    never_null = _NEVER_NULL_LIST_KEYS.get(section, frozenset())
    original = _original_snapshot(form, section)
    primary_idx = _org_primary_index(form) if section == "organisations" else None
    rows: list[dict] = []
    for i in _row_indices(form, section):
        row: dict = {}
        any_value = False
        # The correspondingly-indexed original row (the render assigns row index i to original[i]).
        # It decides whether an EMPTY optional key was already present (keep it null) or is being
        # newly introduced (skip it), so an unchanged row round-trips to its snapshot rather than
        # gaining nulls.
        orig_row = (original[i] if isinstance(original, list) and i < len(original)
                    and isinstance(original[i], dict) else {})
        for subkey, _label, _ph, kind in subfields:
            # Two organisations sub-fields are not l_ scalars at all.
            if kind == "org_roles":
                roles = _collect_org_roles(form, i, orig_row)
                if roles:
                    row[subkey] = roles
                    any_value = True
                elif subkey in orig_row:
                    row[subkey] = []       # the curator cleared every role on a row that had some
                continue
            if kind == "primary_custodian":
                # Written ONLY on the selected row, and only as `true`. Never primary_custodian: false
                # (the corpus never carries it and the validator reads absence as "not primary"), so
                # unselecting the radio simply removes the key when the list is replaced. The flag does
                # NOT count as row content: a spare blank row whose radio happens to be selected stays
                # a spare and is dropped, rather than becoming a nameless organisation.
                if primary_idx == i:
                    row[subkey] = True
                continue
            value = _form_get(form, f"l_{section}_{i}_{subkey}")
            if value:
                _validate_scalar(section, subkey, kind, value)
                any_value = True
            # A NEVER-NULL key (organisations[].ror) is omitted outright when blank - clearing it
            # removes the key rather than writing `ror: null`.
            if subkey in never_null and not value:
                continue
            # D-L: an OPTIONAL sub-key (identifies + the acquisition fields) is written back only
            # when it has a value OR the original row already carried it — never introduce an empty one the
            # source row lacked (mirrors the map scalar rule; keeps a corpus row's round-trip byte-clean).
            if subkey in optional and not value and subkey not in orig_row:
                continue
            row[subkey] = value if value else None
        # When the row states a data LEVEL, the DataCite relation DERIVES from it - the
        # relation control is not shown on an identifies row, so the form carries no explicit relation and
        # the server writes the derived value. A legacy row (no identifies) keeps whatever relation it
        # posted, untouched (backward compatible). An out-of-vocab identifies already FAILed above.
        idf = row.get("identifies")
        if idf and str(idf).strip() in IDENTIFIES_LEVELS:
            row["relation"] = derived_relation(idf)
            any_value = True
        # - carry forward UNMODELLED per-row keys from the correspondingly-indexed
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
    # (validate_survey.py: the primary-custodian selection selects AMONG custodial rows): the radio
    # is refused on a row that does not tick custodian. Fail-closed at the form so the curator sees why,
    # rather than meeting the validator FAIL only at preview.
    if section == "organisations" and primary_idx is not None:
        for row in rows:
            if row.get("primary_custodian") is True and "custodian" not in (row.get("roles") or []):
                raise SectionError(section,
                                   f"'{row.get('name') or 'this organisation'}' is marked the primary "
                                   f"custodian but is not ticked as a custodian; the primary-custodian "
                                   f"selection selects among custodial rows")
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


# ---- unified People & credit assembly (the contributor-credit model) ------------------------------

def normalize_orcid(value) -> str:
    """The merge-key form of an ORCID: lower-cased, with any URL wrapper (https://orcid.org/...) and
    surrounding slashes stripped, so `0000-0002-1825-0097` and `https://orcid.org/0000-0002-1825-0097`
    key to the SAME person (the case/URL-form-insensitive rule). Empty when absent. This is used ONLY
    for keying/dedupe; the row still STORES the curator's exact typed ORCID verbatim (byte-stable)."""
    s = str(value or "").strip().lower()
    for pfx in ("https://orcid.org/", "http://orcid.org/", "orcid.org/"):
        if s.startswith(pfx):
            s = s[len(pfx):]
            break
    return s.strip("/")


def _people_key(name, name_type, orcid):
    """The unified-row merge key: an ORCID (normalised) when present, else the EXACT trimmed
    name + name_type (an organisation and a person sharing a spelling never collide)."""
    o = normalize_orcid(orcid)
    if o:
        return ("orcid", o)
    return ("name", str(name or "").strip(), str(name_type or "person").strip())


def _new_people_row(name, name_type, orcid, ror):
    return {"name": str(name or "").strip(),
            "name_type": (str(name_type).strip() if name_type else "person") or "person",
            "orcid": str(orcid or "").strip(), "ror": str(ror or "").strip(),
            "cited": False, "roles": [],
            "creator_idx": None, "contrib_idxs": []}


def merge_people(creators, contributors) -> list[dict]:
    """LOAD: merge the two lists into ordered unified rows (one per person/org). Keyed by
    normalised ORCID else exact name+name_type. A creators[] row sets cited=True (and records its
    creators index for chip attribution); each contributors[] row ticks that role (and records its
    contributors index). Creators are added FIRST so the cited rows keep the citation author order,
    then contributor-only people are appended in their list order - the display order that
    _decompose_people reproduces byte-for-byte on an unchanged save."""
    rows: list[dict] = []
    index: dict = {}

    def get_row(name, name_type, orcid, ror):
        key = _people_key(name, name_type, orcid)
        row = index.get(key)
        if row is None:
            row = _new_people_row(name, name_type, orcid, ror)
            rows.append(row)
            index[key] = row
        else:
            # Fill an ORCID/ROR the first-seen occurrence lacked (a later list may carry it).
            if not row["orcid"] and orcid:
                row["orcid"] = str(orcid).strip()
            if not row["ror"] and ror:
                row["ror"] = str(ror).strip()
        return row

    for i, c in enumerate(creators or []):
        if not isinstance(c, dict) or not str(c.get("name") or "").strip():
            continue
        row = get_row(c.get("name"), c.get("name_type"), c.get("orcid"), c.get("ror"))
        row["cited"] = True
        row["creator_idx"] = i
    for j, ct in enumerate(contributors or []):
        if not isinstance(ct, dict) or not str(ct.get("name") or "").strip():
            continue
        row = get_row(ct.get("name"), ct.get("name_type"), ct.get("orcid"), ct.get("ror"))
        role = ct.get("role")
        if role and role not in row["roles"]:
            row["roles"].append(str(role))
        row["contrib_idxs"].append(j)
    return rows


def _credit_dict(row: dict, role: str | None) -> dict:
    """One decomposed creators[]/contributors[] entry from a unified row, in the key order
    (name, name_type, [role], orcid?, ror?). ORCID/ROR are emitted only when non-empty, so a person
    row (no ror) and an organisation row (no orcid) reproduce their stored shape - the byte-clean
    round-trip. The name is emitted VERBATIM as the curator typed it."""
    out: dict = {"name": row["name"], "name_type": row["name_type"] or "person"}
    if role is not None:
        out["role"] = role
    if row.get("orcid"):
        out["orcid"] = row["orcid"]
    if row.get("ror"):
        out["ror"] = row["ror"]
    return out


def _decompose_people(rows: list[dict]) -> tuple[list, list]:
    """SAVE: decompose the unified rows back into (creators[], contributors[]). creators[] = the cited
    rows in DISPLAY order (so the citation order is the order among the cited rows only). contributors[]
    = one entry per (row, ticked role), stable-ordered by ROW order then the role order, with
    exact duplicates dropped. The two served lists come straight out of here."""
    creators = [_credit_dict(r, None) for r in rows if r["cited"]]
    contributors: list = []
    seen: set = set()
    for r in rows:
        for role in CONTRIBUTOR_ROLES:
            if role in r["roles"]:
                entry = _credit_dict(r, role)
                sig = tuple(sorted(entry.items()))
                if sig in seen:
                    continue
                seen.add(sig)
                contributors.append(entry)
    return creators, contributors


def _people_rows_from_form(form: dict) -> list[dict]:
    """Read the unified rows the curator submitted (l_people_<i>_*, the cited checkbox, the role
    checkboxes). A row with no name is dropped (the spare-blank-row degradation). name_type FAIL-CLOSES
    and defaults to person; a non-empty ORCID/ROR is format-checked (a WARNING-grade curator hint,
    SectionError-at-the-form like the other typed rows)."""
    rows: list[dict] = []
    for i in _row_indices(form, PEOPLE_SECTION):
        name = _form_get(form, f"l_{PEOPLE_SECTION}_{i}_name")
        if not name:
            continue
        name_type = _form_get(form, f"l_{PEOPLE_SECTION}_{i}_name_type") or "person"
        _validate_scalar("people", "name_type", "name_type", name_type)
        orcid = _form_get(form, f"l_{PEOPLE_SECTION}_{i}_orcid")
        ror = _form_get(form, f"l_{PEOPLE_SECTION}_{i}_ror")
        _validate_scalar("people", "orcid", "orcid", orcid)
        _validate_scalar("people", "ror", "ror", ror)
        row = _new_people_row(name, name_type, orcid, ror)
        row["cited"] = form.get(f"l_{PEOPLE_SECTION}_{i}_cited") is not None
        row["roles"] = [r for r in CONTRIBUTOR_ROLES
                        if form.get(f"l_{PEOPLE_SECTION}_{i}_role_{r}") is not None]
        rows.append(row)
    return rows


def assemble_people(form: dict) -> tuple:
    """Assemble the unified People & credit panel into (creators_value, contributors_value), each the
    assembled value or the _OMIT sentinel. Precedence per underlying list: a non-empty j_<list> advanced
    JSON OVERRIDES the panel for THAT list; otherwise the panel's unified rows are decomposed. Each list
    is then snapshot-compared against its o_<list> anchor -> _OMIT when unchanged (the byte-clean
    round-trip). Raises SectionError on a bad name_type/orcid/ror or malformed advanced JSON.

    A form that does NOT carry the panel (no l_people_* rows, no o_/j_ credit fields) yields
    (_OMIT, _OMIT): the per-section hub posts one section at a time, so a non-people form must contribute
    nothing to creators/contributors (the no-clobber promise)."""
    decomposed: dict = {}
    for key in _PEOPLE_DECOMPOSED:
        adv = _form_get(form, f"j_{key}")
        if adv:
            try:
                decomposed[key] = json.loads(adv)
            except ValueError:
                raise SectionError(key, f"the advanced JSON for {key} is not valid JSON")
    if len(decomposed) < len(_PEOPLE_DECOMPOSED):
        rows = _people_rows_from_form(form)
        creators_asm, contributors_asm = _decompose_people(rows)
        decomposed.setdefault("creators", creators_asm)
        decomposed.setdefault("contributors", contributors_asm)

    out = []
    for key in _PEOPLE_DECOMPOSED:
        value = decomposed[key]
        original = _original_snapshot(form, key)
        if original is not _ABSENT and value == original:
            out.append(_OMIT)
        elif original is _ABSENT and value in (None, "", [], {}):
            out.append(_OMIT)
        else:
            out.append(value)
    return tuple(out)


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
    else:
        # A JSON-only section (JSON_SECTIONS) with a blank j_<section>: the panel's own copy says
        # blank means unchanged, so it contributes nothing. Reachable care fix.
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
    with the scalar fields and, if errors is non-empty, re-renders the form with them.

    creators[]/contributors[] are NOT assembled in the generic loop: the unified People & credit panel
    (assemble_people) owns them, decomposing its unified rows back into the two served lists.
    there is no delete directive any more - the legacy Convert is gone with the keys it
    converted, so a patch can only ever carry editable field values."""
    patch: dict = {}
    errors: list[SectionError] = []
    for section in WIDGET_SECTIONS + JSON_SECTIONS:
        if section in _PEOPLE_DECOMPOSED:
            continue  # owned by the unified People & credit panel (assemble_people), assembled below
        try:
            value = assemble_section(form, section)
        except SectionError as exc:
            errors.append(exc)
            continue
        if value is not _OMIT:
            patch[section] = value
    try:
        creators_val, contributors_val = assemble_people(form)
        if creators_val is not _OMIT:
            patch["creators"] = creators_val
        if contributors_val is not _OMIT:
            patch["contributors"] = contributors_val
    except SectionError as exc:
        errors.append(exc)
    return patch, errors
