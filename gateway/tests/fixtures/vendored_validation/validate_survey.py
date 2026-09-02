#!/usr/bin/env python3
"""AusMT survey-package validator — the submission contract, as runnable code.

Implements Stage-2 automated validation of the submission workflow (see the AusMT docs
operations/submission.md). Emits PASS / WARNING / FAIL
per check and a machine-readable report. A FAIL blocks publication; WARNINGs go to the
human reviewer (Stage 3). This is intentionally dependency-light (stdlib + optional
mt_metadata for deep EDI parsing) so it runs anywhere, including CI.

Usage:
  python validate_survey.py path/to/survey-folder [--json report.json] [--strict]
Exit code 0 if no FAILs (1 if any FAIL, or any WARNING under --strict).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path

LEVELS = {"PASS": 0, "WARNING": 1, "FAIL": 2}


def _norm(s: str) -> str:
    """Normalise raw EDI text: CRLF/CR -> LF and left-strip each line (indented >MARKERS / KEY=).
    Single definition shared with contribute.py so the two tools normalise identically."""
    return "\n".join(ln.lstrip() for ln in s.replace("\r\n", "\n").replace("\r", "\n").split("\n"))


AUS_BBOX = (108.0, 156.0, -45.0, -8.0)  # w,e,s,n — generous; non-AU surveys override in survey.yaml
# EDI, EMTF XML and MTH5 are first-class TF inputs (Prototype 23; EMTF XML added by the owner ruling
# of 2026-08-03, which made it a submission input alongside the other two rather than a build output).
ALLOWED_TF_EXT = {".edi", ".xml", ".h5", ".mth5"}
# Processing-software products remain deferred: they are stored, never parsed into a built product,
# so a curator enables them per submission with --allow-optin-formats (--allow-mth5 is a deprecated
# alias, kept only for existing CI invocations; same dest, same effect).
OPTIN_TF_EXT = {".zmm", ".zrr", ".j"}
# EMTF XML anti-masquerade: the EarthScope root element, matched over a BOUNDED prefix (the root is
# within the first few lines of any real file; this never reads a whole multi-MB XML to decide).
EMTFXML_ROOT_RE = re.compile(r"<\s*EM_TF[\s>]", re.IGNORECASE)
EMTFXML_HEAD_SCAN_BYTES = 65536
DISALLOWED_EXT = {".exe", ".dll", ".bat", ".sh", ".scr", ".js", ".vbs", ".jar", ".com",
                  ".cmd", ".ps1", ".py", ".pl", ".php", ".so", ".dylib"}
ARCHIVE_EXT = {".zip", ".tar", ".gz", ".tgz", ".7z", ".rar", ".bz2", ".xz"}
MAX_FILE_MB = 200          # files larger than this FAIL unless a curator passes --allow-large
# C1 access enum: access.level gates byte DISTRIBUTION in the engine (open serves; metadata_only/embargoed
# withhold bytes but stay discoverable). It is a REQUIRED field, so — unlike licence, which had a legacy
# excuse — an out-of-enum value is a hard FAIL (there is no legacy corpus of bad levels). embargo_until must
# be ISO YYYY-MM-DD when present. These mirror the engine's access_serve_state; keep them behaviourally in sync.
ACCESS_LEVELS = ("open", "metadata_only", "embargoed")
# C42 (owner queue): the SURVEY-LEVEL coordinate-access policy read from access.coordinates. It gates
# how station coordinates are SERVED, so an out-of-enum value is a hard FAIL (no legacy corpus of bad
# values). Absent => exact (the record's zero-change default). Byte-identical spelling to the engine's
# extract/_coordaccess.COORDINATE_POLICIES and gateway.editor_form.COORDINATE_POLICIES.
COORDINATE_POLICIES = ("exact", "generalised", "withheld")
# Station-identifier override for third-party released data (owner ruling 2026-08-08). AusMT serves
# such data byte for byte, so a station whose contractor numbering is not a usable public identifier
# cannot be renamed by editing its EDI; survey.yaml declares the published identifier per SOURCE FILE
# instead. Byte-identical spelling to the engine's extract/_stationids.STATION_ID_SOURCES and
# ("id",) + PROVENANCE_KEYS. Every rule below is a hard FAIL because every one of them is fail-closed
# in the engine: a block this validator waves through drops the whole survey at build time, and an
# unmatched key silently publishes a station under the raw contractor DATAID.
STATION_ID_SOURCES = ("filename",)
STATION_ID_VALUE_KEYS = ("id", "source_record_id", "acquisition_stage")
# The published-identifier charset: exactly what the engine's safe_component() leaves unchanged, so a
# declared identifier is either published verbatim or refused, never silently rewritten.
STATION_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
# ...INTERSECTED with a length bound, mirroring engine/extract/_stationids.MAX_STATION_ID_LEN.
# safe_component has no bound, so an identifier of 300 legal characters passed both tools and then
# reached the filesystem as the station's product DIRECTORY name: ENAMETOOLONG, and the engine's
# whole corpus build died with no catalogue written. 96 is far beyond any real station identifier.
MAX_STATION_ID_LEN = 96
# A TOP-LEVEL `station_ids:` key in survey.yaml SOURCE TEXT. Used only to decide whether the
# no-PyYAML fallback is allowed to certify the block; a text scan is deliberate, because the parser
# being gated is the one that cannot be trusted to see the key (see _check_station_ids).
STATION_IDS_KEY_RE = re.compile(r"(?m)^station_ids[ \t]*:")
# The persistent run-id store: `run-ids.yaml` beside survey.yaml, one `run_ids` block mapping a
# published station id to that station's ordered run ids. Station-metadata scope section 9 makes the
# id ASSIGNED ONCE and STORED rather than derived: an id regenerated from mutable metadata
# (timestamps, filenames, rates, serials) silently renames a run when curation corrects a value, so
# this file is the record the build reads, never a derivation the build could repeat. The validator
# checks the store and mints nothing of its own.
RUN_IDS_FILE = "run-ids.yaml"
# The CURATED LOCAL id form, `<station>-rNN`. A SOURCE run id (mt_metadata Run.id, an MTH5 run group)
# is whatever the instrument wrote, so a mismatch is a WARNING, never a block.
RUN_ID_LOCAL_SUFFIX = r"-r\d{2}$"
# Ids echoed into one report line. A 312-row store must not print itself into a message (the
# overlong-identifier lesson in _check_station_ids: a report a human cannot read is not a report).
RUN_IDS_REPORT_SAMPLE = 6
# The TIME-SERIES REGISTER: `ts-index.yaml` beside survey.yaml, one `ts_index` block mapping a
# published station id to that station's verified archive files, one row per product level. It is
# stored rather than derived because a remote urlPath does NOT follow from a station id (a survey's
# state segment is not in the id at all), so the row is the only record of which file belongs to
# which station. Every rule below is fail-closed for that reason: a bad row hands out another
# station's bytes under this one's name. The validator checks the register and crawls nothing.
TS_INDEX_FILE = "ts-index.yaml"
# The route/chooser vocabulary, derived from (processing_level, packaging, format) and deliberately
# kept OUT of the station schema, whose processing_level enum is closed and where NetCDF is a
# FORMAT rather than a level.
TS_INDEX_LEVELS = ("raw_packed", "level0", "level1_mth5", "level1_netcdf", "level2")
# The projection gate: only `verified` publishes. `pending` is the adjudication queue and `retired`
# is withdrawn evidence that stays on file, because a row is never silently deleted.
TS_INDEX_REVIEW = ("verified", "pending", "retired")
# How the row's station was decided: `exact` = the stem IS the published id; `rule:<name>` = the
# NAMED per-survey transformation in _tools/ts_match_rules.py proved it (the name is provenance
# for the census and any re-crawl); `curator` = it could not be proven and a human ruled on it.
# A bare `rule` carries no provenance and is not a form.
TS_INDEX_MATCH_METHODS = ("exact", "curator")
TS_MATCH_RULE_RE = re.compile(r"^rule:[a-z0-9-]+$")
# Register dates are matched on SHAPE first: date.fromisoformat widened in 3.11 and now accepts
# forms the vendored fallback parser cannot read, so shape-checking is what stops a file's legality
# depending on the interpreter that reads it.
TS_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# C46 schema-0.3 capture (design §2.1). schema_version is now VALIDATED (it was carried, never
# checked); only these are known. attribution/sources are the 0.3 fields — present under 0.2 warns to
# bump. The key allow-lists are FROZEN and must stay in EXACT parity with the editor's section keys
# (gateway.editor_form MAP/LIST sections); the C46-W1c key-parity test feeds an editor-assembled patch
# through THIS validator and asserts zero unknown-key warnings (the care-field drift lesson: an
# unvalidated new section rots). SOURCE_PROFILES is the custodian attribution-profile vocab.
SCHEMA_VERSIONS = ("0.2", "0.3")
# SLUG_MAX_LEN: the LENGTH half of the slug rule (the charset half is the regex at the slug gate).
#
# WHY IT EXISTS. The station-MTH5 producer passes the slug through verbatim as the MTH5 survey id
# (engine build_portal.py -> normalize(survey_id=slug)); the HDF5 survey group name comes back
# TRUNCATED AT 45 CHARACTERS, and the round-trip gate then cannot find the group it just wrote, so it
# withholds every station .h5 in the survey. Observed live 2026-08-11 on a 54-character slug: the gate
# named the missing group as slug[:45], exactly. Nothing before it had exceeded 45 (the corpus ran
# 9-30), so the ceiling had never been reached.
#
# WHY A WARNING AND NOT A FAIL. An over-long slug is not WRONG the way a bad charset is — it does not
# fork the survey's identity, it degrades one product tier — and hard-failing would block an
# already-published package from validating at all, including the very validation run that checks its
# rename. --strict (the publication gate) escalates it to a failure, so it still cannot SHIP; and the
# Add Survey form caps the derived slug at the same number, so the normal path cannot mint one. This
# is the backstop for a hand-edited package.
SLUG_MAX_LEN = 40
ATTRIBUTION_KEYS = frozenset({"custodian", "custodian_ror", "statement", "changes_made",
                              "changes_summary", "declared_by", "declared_date"})
SOURCE_KEYS = frozenset({"title", "custodian", "identifier", "licence", "retrieved", "statement",
                         "profile", "relation", "identifier_type", "identifies", "scope"})
SOURCE_PROFILES = frozenset({"ga", "generic"})
# collection.prose: the curator paragraphs the collection PAGE renders, one list of paragraphs per
# page section. The slot names are FROZEN and must stay in exact parity with the engine's renderer
# (extract/_pages.py `_prose_of` reads these keys and no others); a paragraph is rendered verbatim as
# one escaped <p>, except that a leading "# " marks that paragraph as the section's subheading.
COLLECTION_PROSE_SLOTS = ("about", "data", "members_before", "members_after", "organisations")
# §2a (identifiers design — the related-identifiers model): the model TYPES the C46 sources[] object.
# It adds a `relation` + an `identifier_type` to the untyped upstream-dataset identifier sources[]
# already carries, rather than inventing a parallel structure ("C46 built the object; this types it").
# Both vocabularies are FROZEN and FAIL-CLOSED — an out-of-vocab value is a hard FAIL, mirroring the
# access.coordinates enum — because a mis-typed relation would publish a WRONG provenance claim, so it
# must block rather than ship. RELATION_TYPES is the curated DataCite subset ratified as the editor
# presets (design Decision 3); IDENTIFIER_TYPES is the small set AusMT records against (eCat/SARIG ids
# normalise to URL/DOI). Same vocab-select discipline as SOURCE_PROFILES above.
RELATION_TYPES = frozenset({"IsDerivedFrom", "IsVariantFormOf", "IsSupplementTo", "Cites",
                            "IsPartOf", "IsSourceOf",
                            "IsDocumentedBy"})   # activity-scope records (e.g. ANSIR project pages)
IDENTIFIER_TYPES = frozenset({"DOI", "Handle", "URL", "RAiD"})
# Entity scope of an external identifier (METADATA-INTERFACE-CONTRACT section 2, survey-metadata
# lane S1): `scope` states the KIND of thing a related identifier identifies, so a collection DOI
# never presents as a file DOI, a report DOI never as a dataset DOI, a RAiD never as dataset
# identity. Ordered as the contract lists them; the frozenset is the fail-closed membership set
# (beside identifier_type). scope is NEVER an identity designation: which identifiers ARE this
# dataset/release is curated in identity_classification (represents / own_identifiers), not here.
IDENTIFIER_SCOPES = ("dataset", "release", "collection", "resource", "report", "publication",
                     "activity", "instrument", "repository_record")
IDENTIFIER_SCOPE_TYPES = frozenset(IDENTIFIER_SCOPES)
# "Identifiers by data level" (owner-ratified 2026-07-23). A related_identifiers row gains an
# `identifies` key stating WHAT the identifier points at, expressed in NCI Table 1 data-level terms
# (reusing the time_series level names). IDENTIFIES_LEVELS is the ORDERED vocab (Table 1 order); the
# frozenset is the fail-closed membership set (an out-of-vocab value publishes a wrong level claim, so
# it blocks exactly like relation/identifier_type). IDENTIFIES_RELATION derives the DataCite relation
# from the level, so `relation` is no longer curator-facing: a row states the level and the relation
# follows. A row MAY still carry an explicit relation (hand-edited YAML); when both are present and
# disagree the validator WARNs (never blocks) and the explicit value stands.
IDENTIFIES_LEVELS = ("collection", "raw_packed", "level0", "level1", "level2", "level3", "entire")
IDENTIFIES_TYPES = frozenset(IDENTIFIES_LEVELS)
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
    """The DataCite relation a given `identifies` level auto-derives to (owner ruling, D-L2). None when
    the level is absent/blank/out-of-vocab (nothing to derive)."""
    if identifies in (None, ""):
        return None
    return IDENTIFIES_RELATION.get(str(identifies).strip())


# Contributor credit model (owner-ratified 2026-07-25; CONTRIBUTOR-CREDIT-SPEC C1-C3). Three concepts
# replace the tangled lead/principal-investigator fields: creators[] (who the citation names),
# contributors[] (who did what), and the retirement of lead_investigator + principal_investigators.
# NAME_TYPES classifies an actor (a DataCollector is often a contractor ORGANISATION, a Distributor is
# a state survey, a ProjectLeader is usually a person). CONTRIBUTOR_ROLES is the DataCite contributorType
# subset ratified for the real-world chains (state release = Distributor, miner paid = Sponsor, owned
# through embargo = RightsHolder, contractor collected = DataCollector, university = ProjectLeader/
# ProjectMember/ContactPerson/DataCurator). Both are FROZEN and FAIL-CLOSED, byte-identically to the
# access.coordinates enum and the relation/identifier_type/identifies vocabs: an out-of-vocab name_type
# or role mis-states who did what, so it blocks rather than ships. CREATOR_KEYS / CONTRIBUTOR_KEYS are
# the frozen row allow-lists (unknown keys WARN, the ATTRIBUTION_KEYS/SOURCE_KEYS drift-lesson pattern).
NAME_TYPES = frozenset({"person", "organisation"})
CONTRIBUTOR_ROLES_ORDERED = ("ProjectLeader", "ProjectMember", "DataCollector", "ContactPerson",
                             "DataCurator", "Sponsor", "RightsHolder", "Distributor")
CONTRIBUTOR_ROLES = frozenset(CONTRIBUTOR_ROLES_ORDERED)
CREATOR_KEYS = frozenset({"name", "name_type", "orcid", "ror"})
CONTRIBUTOR_KEYS = frozenset({"name", "name_type", "role", "orcid", "ror"})
# MTCAT 2.0 core, surveys side (LANE-CONTRACT-MTCAT-20-CORE S1; ratified unified design,
# 2026-08-22). survey.yaml gains homes for the curated facts the survey-metadata emitter will
# project - the emitter NEVER invents curated facts. Every field is OPTIONAL at entry
# (required-ness arrives with the censuses) and SILENT when absent, so the existing corpus's
# report is byte-unchanged. The vocabularies below are FROZEN and FAIL-CLOSED byte-identically
# to the access.coordinates / relation / role posture: an out-of-vocab value publishes a wrong
# public claim, so it blocks rather than ships. Structure problems WARN (the credit-row shape).
#
# subjects[]: rows {code, scheme, label?, uri?} (MTCAT-20-INTERCHANGE-SPEC 6.6). scheme is
# REQUIRED and explicit (the spec designates NO default scheme); SUBJECT_SCHEMES is the
# registered scheme-token registry (spec Appendix B - deliberately small at 2.0 release), and
# THIS producer-side gate is fail-closed on unknown tokens (the spec's forward tolerance is a
# consumer posture, not a licence for this corpus to mint unregistered tokens). The code format
# is checked per scheme: ANZSRC FoR codes are 2, 4 or 6 digits (division/group/field).
SUBJECT_SCHEMES = ("ANZSRC-FoR-2020",)
SUBJECT_CODE_FORMATS = {"ANZSRC-FoR-2020": re.compile(r"^\d{2}(?:\d{2}(?:\d{2})?)?$")}
SUBJECT_KEYS = frozenset({"code", "scheme", "label", "uri"})
# The ratified discovery-text gate (decision register: "abstract UNCAPPED; discovery-text gate
# (abstract <= 1200 OR discovery_description)"). 1200 is producer policy, spec uncapped; the
# engine never truncates, so an over-cap discovery_description is a surveys-side FAIL here.
DISCOVERY_DESCRIPTION_MAX = 1200
# Interface contract section 1: every survey record is Case A (represents the SAME dataset/
# release as a cited source identifier) or Case B (a DISTINCT AusMT-published release).
# OPTIONAL until the Case A/B census completes (fail-closed but never red-on-arrival).
IDENTITY_CLASSIFICATIONS = ("case_a", "case_b")
# The classification is a MAPPING (survey-metadata lane D12, owner GO 2026-08-22): the
# designation travels WITH the classification because Case A is DEFINED as sameness with a
# cited source identifier. {case: case_a|case_b (fail-closed), represents: [{scheme,
# identifier}] (case_a only: every row MUST equal a related_identifiers row, scheme ==
# identifier_type and identifier == identifier, exact), own_identifiers: [{scheme, identifier}]
# (case_b only: identifiers OF the distinct AusMT release; need not be related rows)}. A
# present list is non-empty (absent-not-empty); the retired scalar string form FAILs. The
# emitter projects identifiers[] = represents (case_a) or own_identifiers (case_b) and
# citation.preferred_identifier MUST equal one of them (interface contract section 3, T25).
IDENTITY_CLASSIFICATION_KEYS = frozenset({"case", "represents", "own_identifiers"})
IDENTITY_DESIGNATION_KEY = {"case_a": "represents", "case_b": "own_identifiers"}
# Citation block (interface contract section 3): preference/guidance over the identifier set,
# never a duplicate bibliographic record. preferred_identifier carries BOTH scheme and
# identifier when present (a half-declared identifier makes the doi/primary/preferred
# cross-layer invariant untestable); text_source states where preferred_text came from
# (fail-closed - a wrong value mis-states provenance of citation wording); additional[] rows
# REQUIRE a reason (the reason makes the layer semantically non-opaque).
CITATION_KEYS = frozenset({"preferred_identifier", "preferred_text", "text_source", "additional"})
CITATION_TEXT_SOURCES = frozenset({"source_provided", "ausmt_generated"})
CITATION_ADDITIONAL_KEYS = frozenset({"identifier", "preferred_text", "reason"})
PREFERRED_IDENTIFIER_KEYS = frozenset({"scheme", "identifier"})
# acknowledgements[] rows {text, type?, source?}: text REQUIRED non-empty (authority wording is
# the row's whole payload, preserved VERBATIM - a textless row says nothing and cannot ship).
# type is the contract's CANDIDATE vocabulary ("validated against real holdings before freeze"),
# so an unknown type WARNs rather than blocks - the one deliberately-soft vocab here.
ACKNOWLEDGEMENT_KEYS = frozenset({"text", "type", "source"})
ACKNOWLEDGEMENT_TYPES = frozenset({"required_source", "custodian", "community",
                                   "traditional_owners", "field_support", "infrastructure",
                                   "access_provider"})
# organisations[]: role-typed organisation rows {name, ror?, roles[], primary_custodian?}
# fitted to the existing organisation/credit model (survey scope section 3). The scalar
# organisation: block keeps its ratified meaning (primary custodial responsibility, the
# discovery projection); organisations[] is the FULL role statement where parties genuinely
# differ (industry-collected government releases make collector/custodian/publisher/distributor
# different parties). PUBLISHER is explicit - structured citation generation fails closed
# without one and a publisher is never inferred. primary_custodian: true on AT MOST one row
# (mtcat's organisation is a DETERMINISTIC projection of the explicitly curated primary
# custodian, never "first element of an array"), and only on a row whose roles include
# custodian (the selection selects among custodians).
ORG_ROLES_ORDERED = ("publisher", "custodian", "distributor", "data_collector",
                     "rights_holder", "hosting_institution")
ORG_ROLES = frozenset(ORG_ROLES_ORDERED)
ORGANISATION_ROW_KEYS = frozenset({"name", "ror", "roles", "primary_custodian"})
# The template/example ship the retired fields with the « REPLACE » sentinel (not null); a value-based
# deprecation (and the migration) must treat that sentinel as a placeholder so the shipped reference
# stays clean, exactly as the identifier-lane deprecation keeps the all-null example silent.
_PLACEHOLDER_MARK = "«"   # the opening guillemet of the « REPLACE » template sentinel


def _has_real_value(v) -> bool:
    """True when a field carries a curator value worth acting on: not blank/placeholder. Mirrors the
    validator's blank-is-silent posture (None/""/TBD/TODO) and also treats the template's « REPLACE »
    sentinel as a placeholder, so a deprecation WARNING fires only on a REAL retired value."""
    if v in (None, "", "TBD", "TODO"):
        return False
    return _PLACEHOLDER_MARK not in str(v)


def _check_credit_row(r, container: str, idx: int, entry, *, roled: bool) -> None:
    """Vocab- and structure-check one creators[]/contributors[] row (CONTRIBUTOR-CREDIT-SPEC §2/§3).
    FAIL-CLOSED on the VALUES (an out-of-vocab name_type or role blocks); WARNING on STRUCTURE (a
    non-mapping row, an unknown key, a missing name/name_type/role). ORCID/ROR reuse the existing
    helpers as WARNING-only hints. Shared shape for both lists so creators and contributors cannot
    drift; `roled` adds the fail-closed role check for contributors."""
    allowed = CONTRIBUTOR_KEYS if roled else CREATOR_KEYS
    if not isinstance(entry, dict):
        r.add("WARNING", container,
              f"{container}[{idx}] must be a mapping (name/name_type" + ("/role" if roled else "") + "/…)")
        return
    for k in entry:
        if k not in allowed:
            r.add("WARNING", container,
                  f"{container}[{idx}].{k} is not a recognised key (allowed: {', '.join(sorted(allowed))})")
    if not _has_real_value(entry.get("name")):
        r.add("WARNING", container, f"{container}[{idx}] has no name - a credited party needs a name")
    nt = entry.get("name_type")
    if nt in (None, ""):
        r.add("WARNING", container,
              f"{container}[{idx}] has no name_type - state person or organisation")
    elif str(nt).strip() not in NAME_TYPES:
        r.add("FAIL", container,
              f"{container}[{idx}].name_type '{nt}' is not one of {tuple(sorted(NAME_TYPES))} - the "
              f"actor type drives citation rendering, so an out-of-vocab value cannot ship")
    if roled:
        role = entry.get("role")
        if role in (None, ""):
            r.add("WARNING", container,
                  f"{container}[{idx}] has no role - state what this contributor did "
                  f"({', '.join(CONTRIBUTOR_ROLES_ORDERED)})")
        elif str(role).strip() not in CONTRIBUTOR_ROLES:
            r.add("FAIL", container,
                  f"{container}[{idx}].role '{role}' is not one of {CONTRIBUTOR_ROLES_ORDERED}; a "
                  f"contributor role is a fail-closed vocab (a mis-typed role publishes a wrong claim "
                  f"about who did what)")
    orcid = entry.get("orcid")
    if orcid not in (None, "", "TBD", "TODO") and not orcid_checksum_ok(orcid):
        r.add("WARNING", container,
              f"{container}[{idx}].orcid '{orcid}' is not a valid ORCID (bad format or failed ISO "
              f"7064 11-2 checksum) - e.g. https://orcid.org/0000-0002-1825-0097")
    ror = entry.get("ror")
    if ror not in (None, "", "TBD", "TODO") and not ror_format_ok(ror):
        r.add("WARNING", container,
              f"{container}[{idx}].ror '{ror}' does not look like a ROR id (expected a bare 9-char id "
              f"or https://ror.org/<id>)")
# anti-masquerade: the BINARY TF types must start with their real signature. The text type (.edi) is
# checked separately for binary content (a NUL byte ⇒ a renamed binary or a polyglot) in the loop below.
MAGIC = {
    ".h5": b"\x89HDF\r\n\x1a\n", ".mth5": b"\x89HDF\r\n\x1a\n",
}

# C6 licence allow-list. The validator is deliberately dependency-light and CANNOT import the engine, so
# these tables are a COPY of contract/licenses.json pinned by tests/test_contribute.py::
# test_license_list_parity_with_contract (the same parity-pin pattern that guards parse_angle/_norm). A
# licence must be a RECOGNISED id (redistributable ∪ recognised_only ∪ aliases) — WARNING by default,
# FAIL under --strict (the publication gate). Everything else is an unrecognised licence. Keep in sync by
# editing contract/licenses.json, then mirroring the change here (the parity test fails loudly otherwise).
REDISTRIBUTABLE_LICENSES = [
    "CC0-1.0", "CC-BY-3.0", "CC-BY-3.0-AU", "CC-BY-4.0", "CC-BY-SA-3.0", "CC-BY-SA-4.0",
    "CC-BY-NC-4.0", "CC-BY-NC-SA-4.0", "CC-BY-ND-4.0", "CC-BY-NC-ND-4.0", "PUBLIC DOMAIN",
    "ODBL-1.0", "ODC-BY-1.0",
]
RECOGNISED_ONLY_LICENSES = [
    "CC-BY-NC-3.0", "CC-BY-NC-SA-3.0", "CC-BY-ND-3.0", "CC-BY-NC-ND-3.0",
    "ALL RIGHTS RESERVED", "COPYRIGHT",
]
LICENSE_ALIASES = {
    "CC0": "CC0-1.0", "CC-BY": "CC-BY-4.0", "CC-BY-SA": "CC-BY-SA-4.0", "CC-BY-NC": "CC-BY-NC-4.0",
    "CC-BY-ND": "CC-BY-ND-4.0", "CC-BY-NC-SA": "CC-BY-NC-SA-4.0", "CC-BY-NC-ND": "CC-BY-NC-ND-4.0",
    "ODBL": "ODBL-1.0", "ODC-BY": "ODC-BY-1.0",
}
_RECOGNISED_UPPER = {s.upper() for s in REDISTRIBUTABLE_LICENSES + RECOGNISED_ONLY_LICENSES}
_ALIASES_UPPER = {k.upper(): v.upper() for k, v in LICENSE_ALIASES.items()}


def canon_license(license_str: str) -> str:
    """Canonical UPPER licence id (trim, collapse internal whitespace, upper, de-alias). Byte-identical
    behaviour to the engine's build_portal._canon_license — pinned by the licence-parity test."""
    s = " ".join((license_str or "").strip().split()).upper()
    return _ALIASES_UPPER.get(s, s)


def is_recognised_license(license_str: str) -> bool:
    """True iff the licence canonicalises to a recognised id (redistributable ∪ recognised_only ∪ aliases)."""
    return canon_license(license_str) in _RECOGNISED_UPPER


_ORCID_RE = re.compile(r"^(?:https?://orcid\.org/)?(\d{4})-(\d{4})-(\d{4})-(\d{3}[\dX])$")
_ROR_RE = re.compile(r"^0[a-hj-km-np-tv-z0-9]{6}[0-9]{2}$")   # the bare-id form (Crockford base32 + 2 check digits)


def orcid_checksum_ok(orcid: str) -> bool:
    """ISO 7064 11-2 check-digit validation, the algorithm ORCID identifiers use: double-add-double
    over the first 15 digits mod 11, expressed as a check digit in 0-9/X. A bare id or a full
    https://orcid.org/... URL are both accepted (the survey.yaml comment shows the bare form)."""
    m = _ORCID_RE.match((orcid or "").strip())
    if not m:
        return False
    digits = "".join(m.groups())            # 16 chars: 15 digits + 1 check char (may be 'X')
    total = 0
    for d in digits[:-1]:
        total = (total + int(d)) * 2
    remainder = total % 11
    result = (12 - remainder) % 11
    check = "X" if result == 10 else str(result)
    return check == digits[-1]


def ror_format_ok(ror: str) -> bool:
    """Format sanity for a ROR id: either the bare 9-char Crockford-base32-ish id, or a full
    https://ror.org/<id> URL. Deliberately light (no registry lookup) — this is a curator hint, not a
    resolvability guarantee, mirroring the RAiD check below."""
    s = (ror or "").strip()
    if s.lower().startswith(("http://ror.org/", "https://ror.org/")):
        s = s.split("/")[-1]
    return bool(_ROR_RE.match(s))


_RAID_RE = re.compile(r"^https?://raid\.org/\S+$", re.I)


def raid_format_ok(raid: str) -> bool:
    """Format sanity for a RAiD (Research Activity Identifier): RAiD is a resolvable URL/handle
    (https://raid.org/<prefix>/<suffix>), not a fixed-charset id like ORCID/ROR — so this is a light
    URL-shape regex only, per the C7 contract note ('RAiD is a URL/handle — light regex only')."""
    return bool(_RAID_RE.match((raid or "").strip()))


# PID-schema: an instrument-system PID (AuScope Instrument Registry). Like RAiD it is a resolvable
# URL/handle rather than a fixed-charset id, so the check is deliberately light and only a curator hint:
# an https:// URL, or a bare handle/DOI (a prefix/suffix pair, optionally an `hdl:` prefix) that the
# portal resolves against the handle/DOI resolver. Rejects whitespace and non-http(s) schemes (the exact
# shapes — javascript:, data:, a bare word — a curator would want flagged before it ships as a link).
_INSTRUMENT_PID_URL_RE = re.compile(r"^https?://[^\s/]+/\S+$", re.I)
_INSTRUMENT_PID_HANDLE_RE = re.compile(r"^(?:hdl:)?\d[\w.]*\/\S+$", re.I)   # e.g. 10.25914/x, 20.500/x, hdl:20.500/x


def instrument_pid_format_ok(pid: str) -> bool:
    """Format sanity for instruments[].pid — an https:// URL OR a bare handle/DOI. Deliberately light
    (no registry lookup), mirroring raid_format_ok: a curator hint, not a resolvability guarantee."""
    s = (pid or "").strip()
    return bool(_INSTRUMENT_PID_URL_RE.match(s) or _INSTRUMENT_PID_HANDLE_RE.match(s))


def _check_typed_relation(r, container: str, idx: int, entry: dict) -> None:
    """§2a: vocab-check the two TYPED fields the related-identifiers model adds to a source/relation
    entry — `relation` (the curated DataCite subset) and `identifier_type` (the small mint set).
    FAIL-CLOSED, byte-identically to the access.coordinates enum check: an out-of-vocab value would
    publish a wrong/ambiguous provenance claim, so it blocks. Absent/blank values are silent — the
    check validates the VALUE, not its presence (a typed source may legitimately omit either). Shared
    by the sources[] and related_identifiers[] loops so the two can never drift."""
    rel = entry.get("relation")
    if rel not in (None, "") and str(rel).strip() not in RELATION_TYPES:
        r.add("FAIL", container,
              f"{container}[{idx}].relation '{rel}' is not one of {tuple(sorted(RELATION_TYPES))} — a "
              f"typed provenance relation must use the ratified vocabulary (a mis-typed relation "
              f"publishes a wrong claim; an out-of-enum value cannot ship)")
    it = entry.get("identifier_type")
    if it not in (None, "") and str(it).strip() not in IDENTIFIER_TYPES:
        r.add("FAIL", container,
              f"{container}[{idx}].identifier_type '{it}' is not one of {tuple(sorted(IDENTIFIER_TYPES))}")
    # Entity scope (interface contract section 2): fail-closed beside identifier_type. Absent is
    # silent (scope is optional); a value outside the contract's list cannot ship.
    sc = entry.get("scope")
    if sc not in (None, "") and str(sc).strip() not in IDENTIFIER_SCOPE_TYPES:
        r.add("FAIL", container,
              f"{container}[{idx}].scope '{sc}' is not one of {IDENTIFIER_SCOPES}; scope is the "
              f"KIND of thing the identifier identifies (its entity scope), never an identity "
              f"designation (which identifiers ARE this dataset/release is curated in "
              f"identity_classification), so an out-of-vocab scope cannot ship")
    # "Identifiers by data level" (D-L1/D-L2): `identifies` states WHAT the identifier points at, in
    # NCI Table 1 level terms. FAIL-CLOSED like relation/identifier_type above: an out-of-vocab level
    # would auto-derive a wrong (or no) relation, so a mis-typed value publishes a wrong provenance
    # claim and must block rather than ship. Absent/blank is silent (a legacy row without `identifies`
    # keeps its standalone relation, fully backward compatible).
    idf = entry.get("identifies")
    if idf not in (None, "") and str(idf).strip() not in IDENTIFIES_TYPES:
        r.add("FAIL", container,
              f"{container}[{idx}].identifies '{idf}' is not one of {IDENTIFIES_LEVELS}; the level a "
              f"related identifier points at (NCI Table 1 order) drives the DataCite relation, so an "
              f"out-of-vocab level cannot ship")
    else:
        # When BOTH `identifies` and an explicit `relation` are present and disagree, WARN (never block):
        # the row is hand-edited, the relation now derives from the level, and the two should agree.
        derived = derived_relation(idf)
        if (derived is not None and rel not in (None, "")
                and str(rel).strip() in RELATION_TYPES and str(rel).strip() != derived):
            r.add("WARNING", container,
                  f"{container}[{idx}].relation '{str(rel).strip()}' does not match the relation "
                  f"'{derived}' that identifies '{str(idf).strip()}' derives to; the explicit relation "
                  f"stands, but confirm the row (relation now follows identifies)")


def _is_typed_provenance_entry(entry) -> bool:
    """§2a: does this sources[]/related_identifiers[] entry stand as a typed provenance CLAIM — i.e. does
    it point at a real identifier WITH a relation? AusMT is a curator, not the primary publisher, so a
    survey may legitimately carry no dataset DOI; its provenance is instead a well-formed typed relation.
    The relation counts on EITHER route the model ratifies (D-L2): an explicit in-vocab `relation`, or an
    in-vocab `identifies` level from which derived_relation() resolves one; the identifies-only shape is
    what _tools/migrate_identifies.py mints and what the engine publishes the derived relation for.
    Still deliberately strict on the fail-closed vocab posture: a bare identifier with neither route is
    not yet a claim, so it does not count toward provenance-completeness."""
    if not isinstance(entry, dict):
        return False
    ident = entry.get("identifier")
    if ident in (None, "", "TBD", "TODO"):
        return False
    rel = entry.get("relation")
    if rel not in (None, "") and str(rel).strip() in RELATION_TYPES:
        return True
    return derived_relation(entry.get("identifies")) is not None


def _declared_station_ids(block) -> dict:
    """{source filename: published station id} for the `station_ids` entries that declare an id.

    Empty for an absent, malformed or provenance-only block. Shape rules belong to
    _check_station_ids; this only reads the ids out of a block that has them, so the two cannot
    disagree about what a block declares."""
    raw = block.get("map") if isinstance(block, dict) else None
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key, value in raw.items():
        sid = value.get("id") if isinstance(value, dict) else value
        if sid not in (None, ""):
            out[str(key)] = str(sid)
    return out


def _edi_dataids(edis) -> dict:
    """{EDI filename: HEAD DATAID}, for the files whose DATAID resolves. The published station id
    IS the DATAID wherever station_ids does not override it, and this validator already reads
    every EDI HEAD in the same run, so the register authority parses the real id rather than
    guessing from filename stems (section-2 D5: the old claim that this validator "never parses
    the DATAID" was false, and it left the fail-closed branch armed for 1 of 18 surveys)."""
    out = {}
    for p in edis:
        try:
            raw = _norm(p.read_text(encoding="latin-1", errors="replace"))
        except OSError:
            continue
        did = _grab(raw, "DATAID")
        if did not in (None, ""):
            out[p.name] = str(did).strip()
    return out


def _station_id_authority(block, edis) -> tuple:
    """(the ids this package publishes, whether that set is COMPLETE), for the per-station files
    that key on a published id. Shared so run-ids.yaml and ts-index.yaml cannot drift into two
    different answers about which ids exist.

    The authority, per source file: the station_ids map value where one is declared, else the
    EDI's HEAD DATAID (the published id), else the filename stem as a last-resort proxy. COMPLETE
    when every EDI resolves through the first two; a stem is never authoritative. A complete
    authority fail-closes the register checks; an incomplete one degrades them to reviewer
    WARNINGs (see _check_run_ids). An overridden DATAID is deliberately NOT in the set: the map
    replaced it, so a register keyed by it names an id this package no longer publishes."""
    declared = _declared_station_ids(block)
    names = {p.name for p in edis}
    if bool(declared) and names <= set(declared):
        return set(declared.values()), True
    dataids = _edi_dataids(edis)
    known = set(declared.values()) | {d for f, d in dataids.items() if f not in declared}
    if edis and all(f in declared or f in dataids for f in names):
        return known, True
    return known | {p.stem for p in edis if p.name not in declared and p.name not in dataids}, False


def _check_run_ids(doc, known_ids, r, *, authority_complete: bool) -> None:
    """Validate the run-id store against the station identifiers this package publishes.

    FAIL-CLOSED like _check_station_ids and for the same reason: the build reads this file as the
    only record of which run id belongs to which station, so a row waved through here publishes a
    run under an identifier nothing ever assigned.

    ID AUTHORITY: _station_id_authority's set - station_ids map values plus the DATAIDs of
    unmapped EDIs. When every EDI resolves through one of those two, the set is COMPLETE and a key
    outside it FAILs. Only when some EDI yields neither (no DATAID in its HEAD and no map entry)
    does the check degrade: the stem is then a proxy, a key outside the set WARNs to the reviewer
    instead of blocking, and the PASS summary is withheld (nothing was confirmed).

    ABSENT file: this is never called, so every existing package's report is unchanged."""
    if not isinstance(doc, dict) or not isinstance(doc.get("run_ids"), dict):
        r.add("FAIL", "run_ids", f"{RUN_IDS_FILE} must be a mapping carrying a 'run_ids' block of "
                                 f"{{published station id: [run ids]}}")
        return
    unknown_keys = sorted(k for k in doc if k != "run_ids")
    if unknown_keys:
        r.add("FAIL", "run_ids", f"{RUN_IDS_FILE} has unknown key(s) {unknown_keys}; only 'run_ids' "
                                 f"is defined")
    rows = doc["run_ids"]
    unknown, misformed, seen, total = [], [], {}, 0
    for station, run_ids in rows.items():
        sid = str(station)
        if sid not in known_ids:
            unknown.append(sid)
        if run_ids in (None, "", [], ()):
            # Reported as "no run ids" rather than by type name: a key written with nothing after
            # the colon is a half-finished edit, and naming its Python type sends a curator hunting
            # for an identifier the file does not contain (the station_ids null-value lesson).
            r.add("FAIL", "run_ids", f"{RUN_IDS_FILE}['{sid}'] has no run ids. A row states the ids "
                                     f"assigned to this station; to assign none, remove the row "
                                     f"(a partial store is legal)")
            continue
        if not isinstance(run_ids, (list, tuple)):
            r.add("FAIL", "run_ids", f"{RUN_IDS_FILE}['{sid}'] must be a list of run ids, got "
                                     f"{type(run_ids).__name__}")
            continue
        for raw in run_ids:
            rid = str(raw).strip() if raw not in (None, "") else ""
            if not rid:
                r.add("FAIL", "run_ids", f"{RUN_IDS_FILE}['{sid}'] carries an empty run id; a row "
                                         f"states the ids assigned to this station or is removed")
                continue
            total += 1
            seen.setdefault(rid, []).append(sid)
            if not re.match(f"^{re.escape(sid)}{RUN_ID_LOCAL_SUFFIX}", rid):
                misformed.append(f"{sid}: {rid}")
    for rid, stations in sorted(seen.items()):
        if len(stations) > 1:
            r.add("FAIL", "run_ids", f"{RUN_IDS_FILE} assigns run id '{rid}' to {stations}; a run id "
                                     f"identifies one acquisition and is never shared or repeated")
    if unknown:
        shown = _sample(unknown)
        if authority_complete:
            r.add("FAIL", "run_ids", f"{RUN_IDS_FILE} names {len(unknown)} station(s) this package "
                                     f"does not publish: {shown}. The published ids are the "
                                     f"station_ids map values plus each unmapped EDI's DATAID, and "
                                     f"every source file resolved, so that set is complete")
        else:
            r.add("WARNING", "run_ids", f"{RUN_IDS_FILE} names {len(unknown)} station(s) matching "
                                        f"no published id: {shown}. Not every EDI yields a DATAID "
                                        f"or a station_ids entry, so the id set cannot be "
                                        f"confirmed complete here; check the rows against the "
                                        f"catalogue")
    if misformed:
        r.add("WARNING", "run_ids", f"{len(misformed)} run id(s) are not of the curated local form "
                                    f"<station>-rNN: {_sample(misformed)}. A source run id "
                                    f"legitimately is not; a curated one should be")
    # The summary PASS only when every key was CONFIRMED against the authority: printing
    # "PASS ... N station(s)" beside a warning that none could be confirmed read as endorsement.
    if not unknown and not [i for i in r.items if i["check"] == "run_ids" and i["level"] == "FAIL"]:
        r.add("PASS", "run_ids", f"{RUN_IDS_FILE}: {len(rows)} station(s), {total} run id(s), no "
                                 f"duplicates")


def _ts_iso_date(value) -> bool:
    """Whether a register date is an ISO YYYY-MM-DD day.

    PyYAML resolves an unquoted date to a date OBJECT while the vendored fallback yields a string,
    so both are normalised through str() before the shape test. Shape is tested BEFORE
    fromisoformat because that parser widened in 3.11; without the regex a `20260823` would pass
    under one interpreter and fail under another."""
    text = str(value).strip()
    if not TS_ISO_DATE_RE.match(text):
        return False
    from datetime import date as _date  # noqa: PLC0415 (dependency-light; import where used)
    try:
        _date.fromisoformat(text)
    except ValueError:
        return False
    return True


def _check_ts_index_row(r, label, row) -> str:
    """One register row. Returns its level token ("" when unusable), so the caller can pin the
    one-route-per-(station, level) rule on a token that is known to be in vocabulary."""
    level = str(row.get("level")).strip() if row.get("level") not in (None, "") else ""
    if not level:
        r.add("FAIL", "ts_index", f"{label} has no level; a row states WHICH product level of this "
                                  f"station the file is, and nothing downstream can guess it")
    elif level not in TS_INDEX_LEVELS:
        r.add("FAIL", "ts_index", f"{label}.level '{level}' is not one of {TS_INDEX_LEVELS}; the "
                                  f"token is what a route, a chooser button and a drawer row key "
                                  f"off, so an out-of-vocab one is stored and never published")
        level = ""
    if row.get("url_path") in (None, "") or not str(row.get("url_path")).strip():
        r.add("FAIL", "ts_index", f"{label} has no url_path; that string IS the remote file's "
                                  f"identity, stored verbatim, and is never rebuilt by joining "
                                  f"catalog segments")
    # `bytes`, mirroring the engine's own row reader verbatim (engine/extract/_tsindex.py): a bool
    # is NOT an int here, because `bytes: true` is an int to isinstance and a nonsense size to a
    # reader. Absent stays silent, as it does there. Stated as a FAIL because the engine REFUSES
    # the whole register over one such row while the figure is published beside the file in the
    # public drawer, so a value waved through here is a fatal register handed on green.
    size = row.get("bytes")
    if size is not None:
        # `is not None`, not blank-silent: the engine raises on `bytes: ""` too (only absence is
        # tolerated), and both parsers read a bare `bytes:` as None, so a quoted empty string is
        # always a curator's typo and never a parser artefact.
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            r.add("FAIL", "ts_index", f"{label}.bytes {size!r} is not a positive integer; the "
                                      f"engine refuses the entire register over this row at build "
                                      f"time, and the figure is published beside the file, so a "
                                      f"wrong one is both a lost survey and a wrong claim")
    ver = row.get("verified")
    if ver in (None, "") or not str(ver).strip():
        r.add("FAIL", "ts_index", f"{label} has no verified date; the crawler writes the day it read "
                                  f"the file, and that day is what the published fieldnote names")
    elif not _ts_iso_date(ver):
        r.add("FAIL", "ts_index", f"{label}.verified '{str(ver).strip()}' is not an ISO date "
                                  f"(YYYY-MM-DD)")
    review = str(row.get("review")).strip() if row.get("review") not in (None, "") else ""
    if not review:
        r.add("FAIL", "ts_index", f"{label} has no review state; the state is the publication gate, "
                                  f"so a row without one cannot be read as either held or cleared")
    elif review not in TS_INDEX_REVIEW:
        r.add("FAIL", "ts_index", f"{label}.review '{review}' is not one of {TS_INDEX_REVIEW}; only "
                                  f"'verified' publishes, and an out-of-vocab state reads as 'not "
                                  f"verified' to one reader and 'unknown' to the next")
    elif review == "retired":
        absent = [k for k in ("retired", "retired_reason")
                  if row.get(k) in (None, "") or not str(row.get(k)).strip()]
        if absent:
            r.add("FAIL", "ts_index", f"{label} is retired without {' and '.join(absent)}; "
                                      f"retirement is a dated curator act, not a deletion, and the "
                                      f"row stays as evidence recording when and why it was "
                                      f"withdrawn")
    method = (str(row.get("match_method")).strip()
              if row.get("match_method") not in (None, "") else "")
    if method and method not in TS_INDEX_MATCH_METHODS and not TS_MATCH_RULE_RE.match(method):
        r.add("WARNING", "ts_index", f"{label}.match_method '{method}' is not 'exact', 'curator' "
                                     f"or 'rule:<name>'; the row still stands or falls on its "
                                     f"review state, but it cannot reach the adjudication queue")
    if method == "curator" and review == "pending":
        r.add("WARNING", "ts_index", f"{label} is a curator match awaiting review: the match could "
                                     f"not be proven from the names, so the row is stored and stays "
                                     f"unpublished until someone rules on it")
    return level


def _check_ts_index(doc, known_ids, r, *, authority_complete: bool) -> None:
    """Validate the time-series register against the station identifiers this package publishes.

    FAIL-CLOSED like _check_run_ids and for the same stated reason: the build reads this file as
    the only record of which remote file belongs to which station, so a row waved through here
    publishes bytes under an identifier nothing ever matched them to.

    ID AUTHORITY: the run-id store's rule, shared verbatim, because both files key on the
    published station id (see _check_run_ids: station_ids map values plus unmapped EDI DATAIDs;
    fail-closed when complete, reviewer WARNING with the PASS withheld when not).

    ABSENT file: this is never called, so every existing package's report is unchanged."""
    if not isinstance(doc, dict) or not isinstance(doc.get("ts_index"), dict):
        r.add("FAIL", "ts_index", f"{TS_INDEX_FILE} must be a mapping carrying a 'ts_index' block "
                                  f"of {{published station id: [rows]}}")
        return
    unknown_keys = sorted(k for k in doc if k != "ts_index")
    if unknown_keys:
        r.add("FAIL", "ts_index", f"{TS_INDEX_FILE} has unknown key(s) {unknown_keys}; only "
                                  f"'ts_index' is defined")
    stations = doc["ts_index"]
    unknown, routes, total = [], {}, 0
    # url_path -> the stations that named it, collected survey-wide because the collision that
    # matters crosses stations (see below); the (station, level) map cannot see it.
    paths = {}
    for station, rows in stations.items():
        sid = str(station)
        if sid not in known_ids:
            unknown.append(sid)
        if rows in (None, "", [], ()):
            # Reported as "no rows" rather than by type name, the run-id store's null-value lesson:
            # naming the Python type sends a curator hunting for content the file does not have.
            r.add("FAIL", "ts_index", f"{TS_INDEX_FILE}['{sid}'] has no rows. A row states one "
                                      f"verified file; to register none for a station, remove the "
                                      f"station (a partial register is legal)")
            continue
        if not isinstance(rows, (list, tuple)):
            r.add("FAIL", "ts_index", f"{TS_INDEX_FILE}['{sid}'] must be a list of rows, got "
                                      f"{type(rows).__name__}")
            continue
        for idx, row in enumerate(rows):
            label = f"{TS_INDEX_FILE}['{sid}'][{idx}]"
            if not isinstance(row, dict):
                # The enumerated set is what THIS checker judges, no wider: a message naming
                # `filename` and `modified` sent a curator writing keys nothing here reads, and a
                # row corrected to a specification that does not exist is a row corrected blind.
                r.add("FAIL", "ts_index", f"{label} must be a mapping. The keys validated here are "
                                          f"{{level, url_path, bytes, verified, match_method, "
                                          f"review}}, plus retired and retired_reason once review "
                                          f"is 'retired'; a row's remaining keys (filename, "
                                          f"modified, data_size) are stored and read downstream "
                                          f"but are not validated here")
                continue
            total += 1
            level = _check_ts_index_row(r, label, row)
            if level:
                routes[(sid, level)] = routes.get((sid, level), 0) + 1
            path = str(row.get("url_path")).strip() if row.get("url_path") not in (None, "") else ""
            if path:
                paths.setdefault(path, []).append(sid)
    for (sid, level), count in sorted(routes.items()):
        if count > 1:
            r.add("FAIL", "ts_index", f"{TS_INDEX_FILE} carries {count} rows for station '{sid}' at "
                                      f"level '{level}'; one (station, level) names one file, so a "
                                      f"second row leaves nothing able to choose between them")
    # The register's own stated failure mode, in the constants comment above: a bad row hands out
    # another station's bytes under this one's name. Two DIFFERENT stations naming one url_path is
    # exactly that and nothing caught it. Keyed on the url_path STRING alone, so a repeat within
    # one station is caught too: the register maps one remote file to one (station, level), and one
    # file cannot be two levels of the same station either.
    for path, owners in sorted(paths.items()):
        if len(owners) > 1:
            named = ", ".join(sorted(set(owners)))
            r.add("FAIL", "ts_index", f"{TS_INDEX_FILE} gives url_path '{path}' to {len(owners)} "
                                      f"rows across station(s) {named}; that string IS one remote "
                                      f"file's identity, so a shared one publishes those bytes "
                                      f"under more than one station's name")
    if unknown:
        shown = _sample(unknown)
        if authority_complete:
            r.add("FAIL", "ts_index", f"{TS_INDEX_FILE} names {len(unknown)} station(s) this "
                                      f"package does not publish: {shown}. The published ids are "
                                      f"the station_ids map values plus each unmapped EDI's "
                                      f"DATAID, and every source file resolved, so that set is "
                                      f"complete")
        else:
            r.add("WARNING", "ts_index", f"{TS_INDEX_FILE} names {len(unknown)} station(s) "
                                         f"matching no published id: {shown}. Not every EDI "
                                         f"yields a DATAID or a station_ids entry, so the id set "
                                         f"cannot be confirmed complete here; check the rows "
                                         f"against the catalogue")
    # Summary PASS only when every key was CONFIRMED (the run-id store's rule): a "PASS ... N
    # station(s)" beside a warning that none could be confirmed read as endorsement.
    if not unknown and not [i for i in r.items if i["check"] == "ts_index" and i["level"] == "FAIL"]:
        r.add("PASS", "ts_index", f"{TS_INDEX_FILE}: {len(stations)} station(s), {total} row(s) "
                                  f"confirmed; no repeated (station, level), no shared url_path, "
                                  f"bytes well-formed")


def _sample(values) -> str:
    """The first RUN_IDS_REPORT_SAMPLE values, comma-joined, with a count when there are more."""
    head = ", ".join(values[:RUN_IDS_REPORT_SAMPLE])
    extra = len(values) - RUN_IDS_REPORT_SAMPLE
    return f"{head} (+{extra} more)" if extra > 0 else head


def _as_list(v) -> list:
    """A metadata key that should be a list, read tolerantly for ITERATION: any non-list (a scalar,
    a mapping, None) reads as empty rather than crashing the loop. `or []` was not enough: a truthy
    scalar (`instruments: 5`) passed straight into iteration, and the engine calls validate()
    in-process with no guard, so the TypeError aborted the whole corpus build (section-2 D1)."""
    return v if isinstance(v, list) else []


def _http_s(u) -> bool:
    """True when a value is an http(s) URL (scheme check only - resolvability is not this
    dependency-light validator's job)."""
    return str(u).strip().lower().startswith(("http://", "https://"))


def _check_identifier_pair(r, check: str, label: str, entry) -> None:
    """MTCAT 2.0 identifier pair {scheme, identifier}: BOTH keys required non-empty when the
    object is present (interface contract section 3 - the doi/primary/preferred chain is only
    mechanically testable over complete pairs). Unknown keys WARN."""
    if not isinstance(entry, dict):
        r.add("WARNING", check, f"{label} must be a mapping {{scheme, identifier}}")
        return
    for k in entry:
        if k not in PREFERRED_IDENTIFIER_KEYS:
            r.add("WARNING", check, f"{label}.{k} is not a recognised key (allowed: identifier, scheme)")
    missing = [k for k in ("scheme", "identifier") if entry.get(k) in (None, "", "TBD", "TODO")]
    if missing:
        r.add("FAIL", check,
              f"{label} requires BOTH scheme and identifier (missing: {', '.join(missing)}) - a "
              f"half-declared identifier cannot anchor the citation invariant")


_IC_SHAPE = ("a mapping {case: case_a | case_b, represents: [{scheme, identifier}, ...] "
             "(case_a only), own_identifiers: [{scheme, identifier}, ...] (case_b only)}")


def _check_identity_classification(meta: dict, r, ic) -> list:
    """identity_classification (interface contract section 1; survey-metadata lane D12): the
    mapping that carries the Case A/B classification AND the identifier designation. Returns
    the list of well-formed designated {scheme, identifier} pairs (represents for case_a,
    own_identifiers for case_b; [] when none) for the citation chain check. Silent when absent;
    fail-closed once stated."""
    if ic in (None, ""):
        return []
    if not isinstance(ic, dict):
        r.add("FAIL", "identity",
              f"identity_classification '{ic}' is not a mapping (the scalar string form is retired); "
              f"identity_classification is now {_IC_SHAPE} - case_a: this record represents the SAME "
              f"dataset/release as the "
              f"cited source identifier(s) listed in represents; case_b: a DISTINCT AusMT-published "
              f"release whose own identifiers are listed in own_identifiers")
        return []
    for k in ic:
        if k not in IDENTITY_CLASSIFICATION_KEYS:
            r.add("WARNING", "identity",
                  f"identity_classification.{k} is not a recognised key (allowed: "
                  f"{', '.join(sorted(IDENTITY_CLASSIFICATION_KEYS))})")
    case = ic.get("case")
    if case in (None, ""):
        r.add("FAIL", "identity",
              f"identity_classification has no case - case is REQUIRED, one of "
              f"{IDENTITY_CLASSIFICATIONS} (case_a: represents the SAME dataset/release as a cited "
              f"source identifier; case_b: a DISTINCT AusMT-published release)")
        return []
    case = str(case).strip()
    if case not in IDENTITY_CLASSIFICATIONS:
        r.add("FAIL", "identity",
              f"identity_classification.case '{case}' is not one of {IDENTITY_CLASSIFICATIONS} - "
              f"case_a: represents the SAME dataset/release as a cited source identifier; "
              f"case_b: a DISTINCT AusMT-published release. Optional until the census "
              f"completes, fail-closed once stated")
        return []
    key = IDENTITY_DESIGNATION_KEY[case]
    other = "own_identifiers" if key == "represents" else "represents"
    if ic.get(other) is not None:
        r.add("FAIL", "identity",
              f"identity_classification.{other} is present under case {case}, but {other} belongs "
              f"to {'case_b' if other == 'own_identifiers' else 'case_a'} only (case_a designates "
              f"represents: the cited source identifiers this record is the SAME dataset/release "
              f"as; case_b designates own_identifiers: identifiers OF the distinct AusMT release). "
              f"Use {key} under {case}")
    rows = ic.get(key)
    if rows is None:
        return []
    if not isinstance(rows, list) or not rows:
        r.add("FAIL", "identity",
              f"identity_classification.{key} must be a NON-EMPTY list of {{scheme, identifier}} rows "
              f"when present (absent-not-empty: omit the key when no identifier is designated yet)")
        return []
    # represents rows are checked against the survey's own related_identifiers rows, exactly
    # (scheme == identifier_type, identifier == identifier, whitespace-trimmed; the validator
    # applies no DOI normalisation, so the row is cited and designated in one form).
    related = meta.get("related_identifiers")
    cited = set()
    if isinstance(related, list):
        for ri in related:
            if isinstance(ri, dict) and ri.get("identifier") not in (None, "") \
                    and ri.get("identifier_type") not in (None, ""):
                cited.add((str(ri["identifier_type"]).strip(), str(ri["identifier"]).strip()))
    designated = []
    for idx, row in enumerate(rows):
        label = f"identity_classification.{key}[{idx}]"
        if not isinstance(row, dict):
            r.add("FAIL", "identity", f"{label} must be a mapping {{scheme, identifier}}")
            continue
        missing = [k for k in ("scheme", "identifier") if row.get(k) in (None, "", "TBD", "TODO")]
        if missing:
            r.add("FAIL", "identity",
                  f"{label} requires BOTH scheme and identifier (missing: {', '.join(missing)}) - "
                  f"a half-declared designation cannot anchor identifiers[] or the citation chain")
            continue
        for k in row:
            if k not in PREFERRED_IDENTIFIER_KEYS:
                r.add("WARNING", "identity",
                      f"{label}.{k} is not a recognised key (allowed: identifier, scheme)")
        pair = (str(row["scheme"]).strip(), str(row["identifier"]).strip())
        if key == "represents" and pair not in cited:
            r.add("FAIL", "identity",
                  f"{label} {pair[0]}:{pair[1]} does not equal any related_identifiers row (a "
                  f"represents row must match a related_identifiers row exactly: scheme == "
                  f"identifier_type and identifier == identifier). case_a designates sameness with "
                  f"a CITED source identifier, so cite the identifier as a related_identifiers row "
                  f"first (or correct the represents row)")
            continue
        designated.append(pair)
    return designated


def _check_mtcat20_fields(meta: dict, r) -> None:
    """MTCAT 2.0 core survey.yaml field homes (LANE-CONTRACT-MTCAT-20-CORE S1). Every field is
    optional and SILENT when absent; values are fail-closed per the frozen vocabularies, structure
    WARNs (the credit-row posture). See the constants block above for the design citations."""
    # --- subjects[] (interchange spec 6.6 + Appendix B) ---
    subjects = meta.get("subjects")
    if subjects is not None:
        if not isinstance(subjects, list):
            r.add("WARNING", "subjects",
                  "subjects must be a LIST of {code, scheme, label?, uri?} rows")
        else:
            for idx, s in enumerate(subjects):
                if not isinstance(s, dict):
                    r.add("WARNING", "subjects",
                          f"subjects[{idx}] must be a mapping (code/scheme/label?/uri?)")
                    continue
                for k in s:
                    if k not in SUBJECT_KEYS:
                        r.add("WARNING", "subjects",
                              f"subjects[{idx}].{k} is not a recognised key (allowed: "
                              f"{', '.join(sorted(SUBJECT_KEYS))})")
                scheme = s.get("scheme")
                if scheme in (None, ""):
                    r.add("FAIL", "subjects",
                          f"subjects[{idx}] has no scheme - scheme is REQUIRED and explicit "
                          f"(no default scheme exists; registered: {', '.join(SUBJECT_SCHEMES)})")
                    scheme = None
                elif str(scheme).strip() not in SUBJECT_SCHEMES:
                    r.add("FAIL", "subjects",
                          f"subjects[{idx}].scheme '{scheme}' is not a registered scheme token "
                          f"({', '.join(SUBJECT_SCHEMES)}) - this producer gate is fail-closed; "
                          f"an unregistered token cannot ship from this corpus")
                    scheme = None
                code = s.get("code")
                if code in (None, ""):
                    r.add("FAIL", "subjects",
                          f"subjects[{idx}] has no code - a subject row is (code, scheme)")
                elif scheme is not None:
                    fmt = SUBJECT_CODE_FORMATS.get(str(scheme).strip())
                    if fmt is not None and not fmt.match(str(code).strip()):
                        r.add("FAIL", "subjects",
                              f"subjects[{idx}].code '{code}' is not a valid {str(scheme).strip()} "
                              f"code (expected 2, 4 or 6 digits, e.g. 37 / 3706 / 370602)")
                uri = s.get("uri")
                if uri not in (None, "") and not _http_s(uri):
                    r.add("FAIL", "subjects",
                          f"subjects[{idx}].uri '{uri}' is not an http(s) URI - a subject uri is "
                          f"a governed, resolvable concept URI")
    # --- discovery_description (the ratified discovery-text gate) ---
    dd_text = meta.get("discovery_description")
    if dd_text is not None:
        if not isinstance(dd_text, str):
            r.add("WARNING", "discovery", "discovery_description must be a string")
        elif len(dd_text.strip()) > DISCOVERY_DESCRIPTION_MAX:
            r.add("FAIL", "discovery",
                  f"discovery_description is {len(dd_text.strip())} characters; the discovery-text "
                  f"policy cap is {DISCOVERY_DESCRIPTION_MAX}. The engine never truncates - shorten "
                  f"it here (the full story belongs in abstract, which is uncapped)")
    # --- the discovery-text gate itself: abstract <= 1200 OR discovery_description ---
    # (ratified: the abstract is UNCAPPED and never truncated by the engine; a long abstract
    # simply requires an explicit concise discovery_description for the discovery layer)
    abstract_text = meta.get("abstract")
    if (dd_text in (None, "") and isinstance(abstract_text, str)
            and len(abstract_text.strip()) > DISCOVERY_DESCRIPTION_MAX):
        r.add("FAIL", "discovery",
              f"abstract is {len(abstract_text.strip())} characters and no discovery_description "
              f"is declared; the discovery-text gate requires abstract <= "
              f"{DISCOVERY_DESCRIPTION_MAX} OR an explicit discovery_description <= "
              f"{DISCOVERY_DESCRIPTION_MAX}. The abstract itself stays uncapped - add a concise "
              f"discovery_description rather than cutting the abstract")
    # --- identity_classification (interface contract section 1; survey-metadata lane D12) ---
    # The mapping {case, represents | own_identifiers}; `designated` collects the well-formed
    # designated identifier pairs for the citation chain check below.
    ic = meta.get("identity_classification")
    designated = _check_identity_classification(meta, r, ic)
    # --- dates.issued (interface contract section 6: never inferred; unknown = absent) ---
    dates = meta.get("dates")
    if isinstance(dates, dict):
        issued = dates.get("issued")
        if issued not in (None, "") and not _iso_date_ok(issued):
            r.add("FAIL", "dates",
                  f"dates.issued '{issued}' is not an ISO calendar date (YYYY-MM-DD). issued is "
                  f"the PUBLICATION/RELEASE date of the dataset/release - never acquisition "
                  f"coverage, never a bare year; when the publication date is unknown, leave it "
                  f"absent (it is never inferred)")
    # --- citation block (interface contract section 3) ---
    cit = meta.get("citation")
    if cit is not None:
        if not isinstance(cit, dict):
            r.add("WARNING", "citation",
                  "citation must be a mapping (preferred_identifier/preferred_text/text_source/"
                  "additional) - guidance over the identifier set, never a bibliographic record")
        else:
            for k in cit:
                if k not in CITATION_KEYS:
                    r.add("WARNING", "citation",
                          f"citation.{k} is not a recognised key (allowed: "
                          f"{', '.join(sorted(CITATION_KEYS))})")
            pref = cit.get("preferred_identifier")
            if pref is not None:
                _check_identifier_pair(r, "citation", "citation.preferred_identifier", pref)
                # The citation chain (interface contract section 3, T25; D20 FAIL): a complete
                # preferred_identifier MUST equal one of the designated identifiers - represents
                # (case_a) or own_identifiers (case_b) in identity_classification. Nothing
                # designated (home absent, case only, or every row malformed) fails the same way.
                if isinstance(pref, dict) and pref.get("scheme") not in (None, "", "TBD", "TODO") \
                        and pref.get("identifier") not in (None, "", "TBD", "TODO"):
                    pair = (str(pref["scheme"]).strip(), str(pref["identifier"]).strip())
                    if pair not in designated:
                        r.add("FAIL", "citation",
                              f"citation.preferred_identifier {pair[0]}:{pair[1]} does not equal any "
                              f"designated identifier of this survey; the designation home is "
                              f"identity_classification (represents for case_a, own_identifiers "
                              f"for case_b) and it currently designates "
                              f"{', '.join(f'{s}:{i}' for s, i in designated) or 'nothing'}. Designate the "
                              f"identifier there (a represents row must also be a "
                              f"related_identifiers row) or change preferred_identifier; mtcat doi, "
                              f"the primary identifier and the preferred citation identifier are "
                              f"ONE mechanically testable chain, so this fails closed")
            tsrc = cit.get("text_source")
            if tsrc not in (None, "") and str(tsrc).strip() not in CITATION_TEXT_SOURCES:
                r.add("FAIL", "citation",
                      f"citation.text_source '{tsrc}' is not one of "
                      f"{tuple(sorted(CITATION_TEXT_SOURCES))} - where citation wording came from "
                      f"is a fail-closed provenance claim")
            add = cit.get("additional")
            if add is not None:
                if not isinstance(add, list):
                    r.add("WARNING", "citation",
                          "citation.additional must be a LIST of {identifier?, preferred_text?, "
                          "reason} rows")
                else:
                    for idx, row in enumerate(add):
                        if not isinstance(row, dict):
                            r.add("WARNING", "citation",
                                  f"citation.additional[{idx}] must be a mapping")
                            continue
                        for k in row:
                            if k not in CITATION_ADDITIONAL_KEYS:
                                r.add("WARNING", "citation",
                                      f"citation.additional[{idx}].{k} is not a recognised key "
                                      f"(allowed: {', '.join(sorted(CITATION_ADDITIONAL_KEYS))})")
                        if row.get("reason") in (None, "", "TBD", "TODO"):
                            r.add("FAIL", "citation",
                                  f"citation.additional[{idx}] has no reason - the reason (e.g. "
                                  f"derived_product, repository_product, required_source_credit, "
                                  f"companion_release) is REQUIRED; it makes the additional-"
                                  f"citation layer semantically non-opaque")
                        if row.get("identifier") is not None:
                            _check_identifier_pair(r, "citation",
                                                   f"citation.additional[{idx}].identifier",
                                                   row.get("identifier"))
    # --- acknowledgements[] (interface contract section 3: plural, verbatim, never citation) ---
    acks = meta.get("acknowledgements")
    if acks is not None:
        if not isinstance(acks, list):
            r.add("WARNING", "acknowledgements",
                  "acknowledgements must be a LIST of {text, type?, source?} rows")
        else:
            for idx, a in enumerate(acks):
                if not isinstance(a, dict):
                    r.add("WARNING", "acknowledgements",
                          f"acknowledgements[{idx}] must be a mapping (text/type?/source?)")
                    continue
                for k in a:
                    if k not in ACKNOWLEDGEMENT_KEYS:
                        r.add("WARNING", "acknowledgements",
                              f"acknowledgements[{idx}].{k} is not a recognised key (allowed: "
                              f"{', '.join(sorted(ACKNOWLEDGEMENT_KEYS))})")
                text = a.get("text")
                if text in (None, "") or not str(text).strip():
                    r.add("FAIL", "acknowledgements",
                          f"acknowledgements[{idx}] has no text - the (verbatim) wording IS the "
                          f"row; a textless acknowledgement says nothing and cannot ship")
                atype = a.get("type")
                if atype not in (None, "") and str(atype).strip() not in ACKNOWLEDGEMENT_TYPES:
                    r.add("WARNING", "acknowledgements",
                          f"acknowledgements[{idx}].type '{atype}' is not a candidate type "
                          f"({', '.join(sorted(ACKNOWLEDGEMENT_TYPES))}) - the type vocabulary is "
                          f"validated against real holdings, so unknown types WARN, never block")
    # --- organisations[] (survey scope section 3: role-typed rows; explicit primary custodian) ---
    orgs = meta.get("organisations")
    if orgs is not None:
        if not isinstance(orgs, list):
            r.add("WARNING", "organisations",
                  "organisations must be a LIST of {name, ror?, roles[], primary_custodian?} rows "
                  "(the scalar organisation: block stays the custodial discovery value)")
        else:
            primaries = []
            for idx, o in enumerate(orgs):
                if not isinstance(o, dict):
                    r.add("WARNING", "organisations",
                          f"organisations[{idx}] must be a mapping (name/ror?/roles/primary_custodian?)")
                    continue
                for k in o:
                    if k not in ORGANISATION_ROW_KEYS:
                        r.add("WARNING", "organisations",
                              f"organisations[{idx}].{k} is not a recognised key (allowed: "
                              f"{', '.join(sorted(ORGANISATION_ROW_KEYS))})")
                if not _has_real_value(o.get("name")):
                    r.add("WARNING", "organisations",
                          f"organisations[{idx}] has no name - a role-typed organisation needs a name")
                roles = o.get("roles")
                if roles in (None, "", []):
                    r.add("WARNING", "organisations",
                          f"organisations[{idx}] has no roles - state what this organisation is "
                          f"({', '.join(ORG_ROLES_ORDERED)})")
                elif not isinstance(roles, list):
                    r.add("WARNING", "organisations",
                          f"organisations[{idx}].roles must be a LIST of role tokens")
                else:
                    for role in roles:
                        if str(role).strip() not in ORG_ROLES:
                            r.add("FAIL", "organisations",
                                  f"organisations[{idx}].roles value '{role}' is not one of "
                                  f"{ORG_ROLES_ORDERED}; an organisation role is a fail-closed "
                                  f"vocab (a mis-typed role publishes a wrong claim about who "
                                  f"holds/publishes/collected the data)")
                oror = o.get("ror")
                if oror not in (None, "", "TBD", "TODO") and not ror_format_ok(oror):
                    r.add("WARNING", "organisations",
                          f"organisations[{idx}].ror '{oror}' does not look like a ROR id "
                          f"(expected a bare 9-char id or https://ror.org/<id>)")
                pc = o.get("primary_custodian")
                if pc is not None and not isinstance(pc, bool):
                    r.add("WARNING", "organisations",
                          f"organisations[{idx}].primary_custodian must be boolean true/false, "
                          f"got '{pc}'")
                elif pc is True:
                    primaries.append(idx)
                    row_roles = roles if isinstance(roles, list) else []
                    if "custodian" not in [str(x).strip() for x in row_roles]:
                        r.add("FAIL", "organisations",
                              f"organisations[{idx}] is flagged primary_custodian but its roles "
                              f"do not include custodian - the explicit primary-custodian "
                              f"selection selects among custodial rows")
            if len(primaries) > 1:
                r.add("FAIL", "organisations",
                      f"organisations rows {primaries} are ALL flagged primary_custodian: true - "
                      f"mtcat's organisation is a deterministic projection of ONE explicitly "
                      f"curated primary custodian, so at most one row may carry the flag")


def parse_angle(tok: str):
    tok = (tok or "").strip().strip('"')
    if not tok:
        return None
    try:
        if ":" in tok:
            p = tok.split(":")
            sign = -1.0 if tok.lstrip().startswith("-") else 1.0
            mag = abs(float(p[0])) + (abs(float(p[1])) / 60 if len(p) > 1 and p[1] else 0) \
                + (abs(float(p[2])) / 3600 if len(p) > 2 and p[2] else 0)
            return sign * mag
        return float(tok)
    except ValueError:
        return None


# INFO-block angles are decimal ("LATITUDE: -29.3675") or DMS ("LATITUDE : -28:31:33.45"). A
# decimal-only pattern truncates a DMS value at the first colon, which manufactures whole-degree
# coordinates, so the optional :MM:SS tail is part of the match.
_NUM = r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
_INFO_ANGLE = _NUM + r"(?::\d+(?:\.\d+)?){0,2}"


def _info_coords(raw):
    """INFO-block (lat, lon), or (None, None)."""
    mi_lat = re.search(r"LATITUDE\s*:\s*(" + _INFO_ANGLE + ")", raw)
    mi_lon = re.search(r"LONGITUDE\s*:\s*(" + _INFO_ANGLE + ")", raw)
    return (parse_angle(mi_lat.group(1)) if mi_lat else None,
            parse_angle(mi_lon.group(1)) if mi_lon else None)


COORD_TIERS = ("HEAD", "REF", "INFO")


def edi_coords_resolved(raw):
    """((lat, lat_tier), (lon, lon_tier)) from an EDI, each axis resolved independently down the
    HEAD LAT/LONG -> DEFINEMEAS REFLAT/REFLONG -> INFO LATITUDE/LONGITUDE chain. The tier is the
    name of the field that supplied the value, or None where the axis resolves nowhere.

    Mirrors the coordinate read of the catalogue reader the build itself runs
    (engine extract/_edi_catalog.coords_of), so the gate is never stricter than that reader: a file
    this rejects would otherwise have been read. Legacy conversion output spells the HEAD longitude
    key LON= and carries the coordinate in REFLONG=; reprocessed output spells it LON= with no REF
    fallback at all, so LON= is read at the HEAD tier beside LONG=. Semantics are mirrored, not
    imported: the two repos are independent, and a parity test would need a cross-repo checkout.

    What is mirrored is the FALLBACK CHAIN. The reference also rounds its pair to 6 dp, which is a
    catalogue-storage concern; rounding here would perturb coordinates the gate already reads, so
    the parsed values are returned as they always were.

    The converse is NOT true, and the tier is returned so the caller can say so. coords_of is a
    light QC read (state bucketing); the coordinate a station is PUBLISHED at comes from
    mt_metadata, which reads HEAD and DEFINEMEAS and never the INFO block. So for the INFO tier
    alone this chain is more permissive than the build, which publishes such a file at 0.0, 0.0 -
    hence the caller's warning. Measured where it matters: of the 2631 corpus EDIs all 2631 resolve
    on HEAD, and of the 579 staged legacy-GDS EDIs 155 resolve on HEAD and 424 need REF on the
    longitude, so no file AusMT holds reaches the INFO tier at all.
    """
    info_lat, info_lon = _info_coords(raw)
    # LONG and LON are both HEAD spellings of the same field, so they share a tier: a file
    # carrying either resolves at HEAD rather than falling through to REF.
    head_lon = _grab(raw, "LONG")
    if head_lon is None:
        head_lon = _grab(raw, "LON")
    chains = ((parse_angle(_grab(raw, "LAT")), parse_angle(_grab(raw, "REFLAT")), info_lat),
              (parse_angle(head_lon), parse_angle(_grab(raw, "REFLONG")), info_lon))
    return tuple(next(((v, t) for t, v in zip(COORD_TIERS, chain) if v is not None), (None, None))
                 for chain in chains)


def edi_coords(raw):
    """(lat, lon) from an EDI via the tier chain in edi_coords_resolved, which owns the semantics."""
    (lat, _lt), (lon, _ln) = edi_coords_resolved(raw)
    return lat, lon


class Report:
    def __init__(self):
        self.items = []
        self.manifest = []

    def add(self, level, check, msg):
        self.items.append({"level": level, "check": check, "message": msg})

    def worst(self):
        return max((LEVELS[i["level"]] for i in self.items), default=0)

    def counts(self):
        c = {"PASS": 0, "WARNING": 0, "FAIL": 0}
        for i in self.items:
            c[i["level"]] += 1
        return c


def _pyyaml_available() -> bool:
    """Whether the real parser is installed. `_load_yaml` falls back to the vendored `_mini_yaml`
    when it is not, and that fallback is reduced-fidelity: it matches a mapping key as bare-word or
    QUOTED, while YAML's plain scalar keys are wider, so a `station_ids.map` keyed on an unquoted
    filename carrying a space or a bracket is read by PyYAML and silently DROPPED here. Checks that
    depend on having read a block COMPLETELY ask this before certifying it."""
    try:
        import yaml  # noqa: F401, PLC0415
        return True
    except ModuleNotFoundError:
        return False


def _load_yaml(path: Path):
    # encoding STATED, never the locale default: survey.yaml and the two register files are UTF-8
    # by convention and carry non-ASCII (organisation names, quoted attribution wording). Under a
    # C or POSIX locale the default read raised UnicodeDecodeError on 23 corpus files, out of a
    # gate whose callers report it as "not valid YAML".
    try:
        import yaml  # noqa: PLC0415
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except ModuleNotFoundError:
        # tolerant fallback for CI without pyyaml
        return _mini_yaml(path.read_text(encoding="utf-8"))


# >>> BEGIN generated _mini_yaml (vendored from ausmt engine; sync_validator_mini_yaml.py) >>>
# DO NOT EDIT BY HAND. This function is VENDORED verbatim from the ausmt engine's
# build_portal.py (engine/tests/test_mini_yaml_parity.py pins IT against PyYAML). Refresh with
#   python _validation/sync_validator_mini_yaml.py --write
# from a checkout with the ausmt monorepo beside this repo. MINI_YAML_PIN records the source
# commit + sha256; the surveys test-suite asserts this block matches the PIN (no silent drift).
def _mini_yaml(text: str) -> dict:
    """Small YAML-subset parser used only when PyYAML is unavailable, sufficient for AusMT
    `survey.yaml`. Handles nested maps, block sequences (of scalars and of maps), inline ``[]`` /
    ``{}`` and simple flow collections, block scalars (``>`` / ``|`` collapsed to one line), quotes,
    booleans/numbers, and ``#`` comments. It is NOT a general YAML parser; the build also accepts
    PyYAML and the two agree on the AusMT schema (guarded by ``tests/test_mini_yaml_parity.py``).
    Keep it in step with the survey.yaml schema."""
    import re

    def _strip_comment(v: str) -> str:
        v = v.strip()
        if not v:
            return v
        if v[0] == "#":
            # The whole value is a comment ('data_types:  # pick one'). YAML forbids an unquoted
            # scalar starting with '#' after a space, so this is always a comment, never data.
            # Before 2026-08-25 this case leaked through (the mid-string scan below needs ' #'),
            # so a commented key line swallowed its nested block and truncated the document.
            return ""
        if v[0] in "\"'":
            # A quoted scalar may carry a trailing comment AFTER its closing quote
            # ('name: "Stephan Thiel"  # note'). Walk to the closing quote (honouring
            # backslash escapes inside double quotes) and drop a trailing comment; a hash
            # INSIDE the quotes is data and survives. Found live 2026-07-25: the credit
            # migration's inline review note read as part of the value on the no-PyYAML path.
            q, i = v[0], 1
            while i < len(v):
                if q == '"' and v[i] == "\\":
                    i += 2
                    continue
                if v[i] == q:
                    break
                i += 1
            rest = v[i + 1:].lstrip()
            if rest == "" or rest.startswith("#"):
                return v[:i + 1]
            return v
        i = v.find(" #")
        return (v[:i] if i >= 0 else v).strip()

    def _flow_split(s: str):
        out, depth, cur = [], 0, ""
        for ch in s:
            if ch in "[{":
                depth += 1; cur += ch
            elif ch in "]}":
                depth -= 1; cur += ch
            elif ch == "," and depth == 0:
                out.append(cur); cur = ""
            else:
                cur += ch
        if cur.strip():
            out.append(cur)
        return [x.strip() for x in out]

    def _scalar(v):
        v = _strip_comment(v)
        if v == "":
            return None
        if (v[0] == '"' and v[-1:] == '"') or (v[0] == "'" and v[-1:] == "'"):
            return v[1:-1]
        if v == "[]":
            return []
        if v == "{}":
            return {}
        if v[0] == "[" and v[-1:] == "]":
            inner = v[1:-1].strip()
            return [_scalar(x) for x in _flow_split(inner)] if inner else []
        if v[0] == "{" and v[-1:] == "}":
            d = {}
            for part in _flow_split(v[1:-1]):
                if ":" in part:
                    kk, _, vv = part.partition(":")
                    d[kk.strip()] = _scalar(vv)
            return d
        low = v.lower()
        if low in ("true", "false"):
            return low == "true"
        if low in ("null", "~"):
            return None
        try:
            return int(v)
        except ValueError:
            try:
                return float(v)
            except ValueError:
                return v

    toks = []
    for ln in text.splitlines():
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        toks.append((len(ln) - len(ln.lstrip(" ")), ln.strip()))
    n = len(toks)
    pos = [0]
    # A mapping key: bare, or QUOTED. The quoted form is not a nicety: the `station_ids.map` keys are
    # source FILENAMES, and real ones carry spaces and parentheses ("49R stage 1.edi", "53(RR).edi"),
    # which YAML can express only quoted. Before this alternation the fallback matched neither and
    # silently dropped the whole map, so a no-PyYAML build published the raw contractor DATAIDs.
    # The closing quote must be followed IMMEDIATELY by ':', so a quoted list-item SCALAR that happens
    # to contain a colon (- "a: b") is still a scalar, not a one-key map (pinned by test).
    key_re = re.compile(r"""^("[^"]+"|'[^']+'|[\w.\-]+):\s*(.*)$""")

    def _key(k: str) -> str:
        """Unquote a matched mapping key; a bare key passes through unchanged."""
        return k[1:-1] if (len(k) >= 2 and k[0] == k[-1] and k[0] in "\"'") else k

    def _block_scalar(min_indent, style=">"):
        buf = []
        while pos[0] < n and toks[pos[0]][0] >= min_indent:
            buf.append(toks[pos[0]][1]); pos[0] += 1
        joiner = "\n" if style[0] == "|" else " "       # | literal keeps newlines; > folds to spaces
        text_out = joiner.join(buf)
        if not style.endswith("-") and text_out:        # clip (default) keeps one trailing newline
            text_out += "\n"
        return text_out

    def parse(min_indent):
        node = None
        while pos[0] < n:
            indent, content = toks[pos[0]]
            if indent < min_indent:
                break
            if content.startswith("- "):
                if node is None:
                    node = []
                if not isinstance(node, list):
                    break
                item = content[2:].strip()
                m = key_re.match(item)
                if m:
                    sub = {}
                    # _strip_comment BEFORE the structural tests: a trailing comment must not stop
                    # 'val' reading as empty (nested block follows) or as a block-scalar header.
                    k, val = _key(m.group(1)), _strip_comment(m.group(2))
                    if val in (">", "|", ">-", "|-"):
                        pos[0] += 1; sub[k] = _block_scalar(indent + 2, val)
                    elif val == "":
                        pos[0] += 1
                        sub[k] = parse(indent + 3) if (pos[0] < n and toks[pos[0]][0] > indent + 1) else None
                    else:
                        sub[k] = _scalar(val); pos[0] += 1
                    while pos[0] < n:                       # sibling keys of the same list item
                        i2, c2 = toks[pos[0]]
                        if i2 == indent + 2 and not c2.startswith("- "):
                            m2 = key_re.match(c2)
                            if m2:
                                k2, v2 = _key(m2.group(1)), _strip_comment(m2.group(2))
                                if v2 in (">", "|", ">-", "|-"):
                                    pos[0] += 1; sub[k2] = _block_scalar(indent + 4, v2)
                                elif v2 == "":
                                    pos[0] += 1
                                    sub[k2] = parse(indent + 3) if (pos[0] < n and toks[pos[0]][0] > indent + 2) else None
                                else:
                                    sub[k2] = _scalar(v2); pos[0] += 1
                                continue
                        break
                    node.append(sub)
                else:
                    node.append(_scalar(item)); pos[0] += 1
                continue
            m = key_re.match(content)
            if not m:
                pos[0] += 1; continue
            if node is None:
                node = {}
            if not isinstance(node, dict):
                break
            k, val = _key(m.group(1)), _strip_comment(m.group(2))
            if val in (">", "|", ">-", "|-"):
                pos[0] += 1; node[k] = _block_scalar(indent + 1, val)
            elif val == "":
                pos[0] += 1
                node[k] = parse(indent + 1) if (pos[0] < n and toks[pos[0]][0] > indent) else None
            else:
                node[k] = _scalar(val); pos[0] += 1
        return node if node is not None else {}

    result = parse(0)
    return result if isinstance(result, dict) else {}
# <<< END generated _mini_yaml <<<


def _iso_date_ok(v) -> bool:
    """True iff `v` is an ISO calendar date (YYYY-MM-DD). Dependency-light: datetime.date.fromisoformat,
    the same check the C1 embargo gate uses. A non-string / malformed value is False, never a crash."""
    try:
        from datetime import date as _date  # noqa: PLC0415
        _date.fromisoformat(str(v).strip())
        return True
    except (ValueError, TypeError):
        return False


def _iso_date_or_year_ok(v) -> bool:
    """True for an ISO date (YYYY-MM-DD) OR a bare 4-digit year (YYYY). sources[].retrieved may be
    either (a dataset is often cited by acquisition year, not an exact retrieval date). A YAML-unquoted
    year loads as an int, so str()-coerce before matching (the mini_yaml fallback numeric-coerces too)."""
    s = str(v).strip()
    return bool(re.match(r"^\d{4}$", s)) or _iso_date_ok(s)


def _check_station_ids(block, edi_names, r, *, complete_read=True, declared_in_text=False) -> None:
    """Validate the `station_ids` block against the package's real EDI filenames.

    Mirrors the engine's extract/_stationids.py rule for rule, and for the same reason each is a
    FAIL rather than a WARNING: in the engine every one of them drops the whole survey from the
    build, so a block this validator waves through is a package that cannot publish. The one
    deliberately-legal shape is a PARTIAL map: a file with no entry keeps its DATAID, so an unmatched
    FILE is silent while an unmatched KEY fails (an unmatched key would leave that station published
    under the raw contractor identifier, which is the mis-identification the block exists to prevent).

    ABSENT block: nothing is added at all, so every existing package's report is unchanged.

    `complete_read` is False when survey.yaml came from the reduced-fidelity `_mini_yaml` fallback.
    The block is then refused outright rather than certified from a possibly PARTIAL map: a partial
    map is a LEGAL shape, so an under-read would have produced a clean PASS over half a block, and
    the unread stations would publish under the raw contractor DATAID with no warning anywhere. The
    engine drops the same survey for the same reason.

    `declared_in_text` comes from scanning the survey.yaml SOURCE for a top-level `station_ids:`,
    not from `block`. The fallback has a second, pre-existing limitation unrelated to this block: a
    top-level block SEQUENCE whose key line carries a TRAILING COMMENT takes the comment as its
    value, orphans the list items and drops every later top-level key. That is the shipped
    _template/survey.yaml's own shape (`data_types:  # select all that apply`), so on the example
    package the fallback returns 11 of 21 top-level keys and `block` arrives here as None even when
    the package plainly declares one. Gating on the parse would mean asking the parser being gated
    whether it saw the key.
    """
    if not complete_read and (declared_in_text or block not in (None, "", {})):
        r.add("FAIL", "station_ids", "station_ids requires PyYAML, which is not installed. The "
                                     "stdlib fallback parser cannot read this block faithfully "
                                     "(an unquoted filename carrying a space or a bracket is "
                                     "dropped, and top-level keys after the first list are not read "
                                     "at all), so it cannot be checked without silently accepting a "
                                     "partial map. Install PyYAML (pip install PyYAML) and re-run")
        return
    if block in (None, "", {}):
        return
    if not isinstance(block, dict):
        r.add("FAIL", "station_ids", f"station_ids must be a mapping with 'source' and 'map', got "
                                     f"{type(block).__name__}")
        return
    unknown = sorted(k for k in block if k not in ("source", "map"))
    if unknown:
        r.add("FAIL", "station_ids", f"station_ids has unknown key(s) {unknown}; only 'source' and "
                                     f"'map' are defined")
    src = block.get("source")
    if src not in (None, "") and str(src).strip().lower() not in STATION_ID_SOURCES:
        r.add("FAIL", "station_ids", f"station_ids.source '{src}' is not one of "
                                     f"{list(STATION_ID_SOURCES)} - map keys are source FILENAMES")
    raw_map = block.get("map")
    if raw_map in (None, "", {}):
        return
    if not isinstance(raw_map, dict):
        r.add("FAIL", "station_ids", f"station_ids.map must be a mapping of "
                                     f"{{source filename: published station id}}, got "
                                     f"{type(raw_map).__name__}")
        return
    seen: dict = {}
    for key, value in raw_map.items():
        k = str(key)
        if not k.strip() or "/" in k or "\\" in k or k in (".", "..") or Path(k).name != k:
            r.add("FAIL", "station_ids", f"station_ids.map key '{k}' is not a bare filename - keys "
                                         f"name a file inside transfer_functions/edi/ and carry no "
                                         f"path separator and no '..' component")
            continue
        if k not in edi_names:
            r.add("FAIL", "station_ids", f"station_ids.map names source file '{k}', which this "
                                         f"package's transfer_functions/edi/ does not contain - an "
                                         f"unmatched key leaves that station published under its raw "
                                         f"DATAID. This package's EDI files: {sorted(edi_names)}")
            continue
        sid = value
        if value is None:
            # A key written with nothing after the colon. It declares neither an identifier nor any
            # provenance, so it says exactly what an empty mapping says and fails the same way (the
            # engine refuses it too). Without this branch str(None) becomes the literal 'None',
            # which matches STATION_ID_RE: one null produced a PASS line for a mapping that does not
            # exist, and two collided as a duplicate identifier nobody declared.
            r.add("FAIL", "station_ids", f"station_ids.map['{k}'] has no value - a key written with "
                                         f"nothing after the colon declares neither an 'id' nor any "
                                         f"provenance. To keep this file's DATAID, remove the key "
                                         f"entirely; a partial map is legal")
            continue
        if isinstance(value, dict):
            bad = sorted(x for x in value if x not in STATION_ID_VALUE_KEYS)
            if bad:
                r.add("FAIL", "station_ids", f"station_ids.map['{k}'] has unknown key(s) {bad}; only "
                                             f"{list(STATION_ID_VALUE_KEYS)} are defined "
                                             f"(original_filename is the map key, never declared)")
                continue
            if not any(value.get(x) not in (None, "") for x in STATION_ID_VALUE_KEYS):
                r.add("FAIL", "station_ids", f"station_ids.map['{k}'] declares neither an 'id' nor "
                                             f"any provenance - it says nothing")
                continue
            sid = value.get("id")
            if sid in (None, ""):
                continue                     # provenance-only entry: this file keeps its DATAID
        if (not STATION_ID_RE.match(str(sid)) or ".." in str(sid) or str(sid)[0] in ".-"
                or len(str(sid)) > MAX_STATION_ID_LEN):
            shown = str(sid) if len(str(sid)) <= 60 else f"{str(sid)[:60]}... ({len(str(sid))} chars)"
            r.add("FAIL", "station_ids", f"station_ids.map['{k}'] published id '{shown}' is outside "
                                         f"the identifier charset [A-Za-z0-9._-], starts with '.' or "
                                         f"'-', contains '..', or is longer than "
                                         f"{MAX_STATION_ID_LEN} characters - AusMT refuses to "
                                         f"publish a mangled form of an id you declared")
            continue
        seen.setdefault(str(sid), []).append(k)
    for sid, keys in sorted(seen.items()):
        if len(keys) > 1:
            r.add("FAIL", "station_ids", f"station_ids.map assigns the published id '{sid}' to more "
                                         f"than one source file {sorted(keys)} - two files that are "
                                         f"two different physical sites need two different ids")
    if not [i for i in r.items if i["check"] == "station_ids" and i["level"] == "FAIL"]:
        r.add("PASS", "station_ids", f"station_ids: {len(raw_map)} source file(s) mapped, all "
                                     f"present in transfer_functions/edi/, no duplicate ids")


def _check_collection_prose(prose, r) -> None:
    """Check an OPTIONAL collection.prose block: a mapping of section name to a list of paragraphs.

    Why this is checked at all, when the rest of the collection block is not: the engine's collection
    rollup takes the FIRST member that declares a field and ignores the other members entirely, so a
    block that is malformed, or declared but empty, in any ONE member can become the whole
    collection's prose without any member disagreeing out loud. The corpus convention is therefore to
    OMIT a slot with nothing in it, never to write it empty, and every member of a collection must
    carry a byte-identical block.
    """
    if prose is None:
        return
    if not isinstance(prose, dict):
        r.add("FAIL", "collection",
              f"collection.prose must be a mapping of section name to a list of paragraphs, got "
              f"{type(prose).__name__}")
        return
    if not prose:
        r.add("FAIL", "collection",
              "collection.prose is declared with no sections. The rollup reads a declared empty "
              "block as the collection's prose and suppresses every other member's, so a member "
              "with nothing to say must omit the key")
        return
    unknown = sorted(str(k) for k in prose if str(k) not in COLLECTION_PROSE_SLOTS)
    if unknown:
        r.add("WARNING", "collection",
              f"collection.prose declares unrendered section(s) {unknown}; the page renders only "
              f"{list(COLLECTION_PROSE_SLOTS)}, so these paragraphs would never reach a reader")
    n_para = 0
    for slot, paras in prose.items():
        if not isinstance(paras, list):
            r.add("FAIL", "collection",
                  f"collection.prose['{slot}'] must be a LIST of paragraph strings, got "
                  f"{type(paras).__name__}. A bare string here is a sequence of characters, not a "
                  f"sequence of paragraphs")
            continue
        if not paras:
            r.add("FAIL", "collection",
                  f"collection.prose['{slot}'] is declared with no paragraphs; to say nothing in a "
                  f"section, omit the section")
            continue
        for n, para in enumerate(paras, 1):
            where = f"collection.prose['{slot}'][{n}]"
            if not isinstance(para, str) or not para.strip():
                r.add("FAIL", "collection", f"{where} is not a non-empty paragraph string")
                continue
            s = para.strip()
            n_para += 1
            # "# " is the ONE structural sigil the renderer honours, and only at the start of a
            # paragraph. A hash written any other way renders as a literal hash in served prose.
            if s.startswith("#") and not s.startswith("# "):
                r.add("FAIL", "collection",
                      f"{where} opens with '#' but not '# '. A subheading is written as "
                      f"'# Heading text' and needs text after the space; anything else publishes a "
                      f"literal hash")
            bad = sorted({ch for ch in s if ch in ("\u2013", "\u2014")})
            if bad:
                r.add("WARNING", "collection",
                      f"{where} carries {[f'U+{ord(c):04X}' for c in bad]}. House style is ASCII "
                      f"punctuation, and pasted prose is where these arrive; --strict FAILs this")
    if not [i for i in r.items if i["check"] == "collection" and i["level"] == "FAIL"]:
        r.add("PASS", "collection",
              f"collection.prose: {len(prose)} section(s), {n_para} paragraph(s), well-formed")


# The five channels the build understands, keyed by the normalised name both survey-wide masks test
# and valued by the corpus spelling the survey page prints. This set IS the vocabulary: a declared
# name outside it is inert to the masks. Mirrors the engine's _pages._CHANNEL_LABELS.
CHANNEL_LABELS = {"ex": "Ex", "ey": "Ey", "hx": "Bx", "hy": "By", "hz": "Bz"}

# The eight impedance blocks, in the order a fabrication recogniser reads them.
Z_COMPONENTS = ("ZXXR", "ZXXI", "ZXYR", "ZXYI", "ZYXR", "ZYXI", "ZYYR", "ZYYI")


def _channel_key(name) -> str:
    """One declared channel name in the normalised form the impedance and tipper masks use.

    Case, order and duplication are all irrelevant to the build; the corpus spelling B for the
    magnetic channels folds onto the mt_metadata H. Copied from the engine so the two agree.
    """
    key = str(name).strip().lower()
    return "h" + key[1:] if key.startswith("b") else key


def _check_channels_recorded(channels, r):
    """Check the OPTIONAL channels_recorded declaration; return the normalised channel keys or None.

    This field is an assertion the build acts on, not a label. A declaration without a vertical coil
    masks any file-borne tipper survey-wide, and a declaration without either horizontal electric
    channel masks the impedance and every product derived from it. Most of the corpus does not
    declare the field at all and an absent declaration masks nothing, which is why a name outside
    the vocabulary is a WARNING and not a FAIL: it is inert to the masks rather than a breach, and a
    field the corpus has been using without a hard rule does not acquire one retrospectively.

    The shape, by contrast, is a FAIL: the build drops anything that is not a non-empty list, so a
    survey writing another shape is asking for a mask it will silently not get.
    """
    if channels is None:
        return None
    if not isinstance(channels, list):
        r.add("FAIL", "channels",
              f"channels_recorded must be a list of channel names, got {type(channels).__name__}. "
              f"The build drops any other shape, so the declared mask would silently not apply")
        return None
    if not channels:
        r.add("FAIL", "channels",
              "channels_recorded is declared with no channels. The build drops an empty list, so "
              "this declares nothing while reading as a declaration; to declare nothing, omit the key")
        return None
    keys, malformed = set(), False
    for n, c in enumerate(channels, 1):
        if not isinstance(c, str) or not c.strip():
            r.add("FAIL", "channels",
                  f"channels_recorded[{n}] is not a non-empty channel-name string")
            malformed = True
            continue
        key = _channel_key(c)
        keys.add(key)
        if key not in CHANNEL_LABELS:
            r.add("WARNING", "channels",
                  f"channels_recorded[{n}] '{c}' is outside the vocabulary the build understands "
                  f"({', '.join(CHANNEL_LABELS.values())}, or the mt_metadata spellings "
                  f"{', '.join(CHANNEL_LABELS)}; case is ignored). The masks cannot see it, though "
                  f"its presence still arms them, so it changes nothing the build serves")
    return None if malformed else keys


def _edi_block(raw, *names):
    """The numbers of the first >NAME block present in a normalised EDI, as floats.

    Names are tried in order, which is how the suffixed (>TXR.EXP) and bare (>TXR) spellings of one
    block are both read. A block runs from its marker line to the next line opening with '>'. An
    absent block, and a token that is not a number, both contribute nothing.
    """
    for name in names:
        m = re.search(r"^>" + re.escape(name) + r"(?:[ \t][^\n]*)?\n(.*?)(?=^>|\Z)", raw, re.M | re.S)
        if m is None:
            continue
        out = []
        for tok in m.group(1).split():
            try:
                out.append(float(tok))
            except ValueError:
                pass
        return out
    return []


def _flat(vals) -> bool:
    """True when a block's spread is at or below float noise.

    The absolute floor is load-bearing: one fabrication dialect writes an exact constant alongside
    components at 1e-8 to 1e-9 rounding noise, which is constant in every sense that matters.
    """
    if not vals:
        return True
    lo, hi = min(vals), max(vals)
    return (hi - lo) <= max(1e-6, 1e-6 * max(abs(lo), abs(hi)))


def _z_is_converter_constant(z) -> bool:
    """The 2002 GDS converter's twelve constants, written for WinGLink and never measured.

    ZXX and ZYY are 0.2+0.2i and ZXY and ZYX are 1.0+1.0i at every period, in every station, in
    every survey it converted. Keyed on the numbers, never on the banner comment: one re-rendered
    file carries the constants with no banner, and the tolerance is what catches its 1.999999e-01.
    """
    diag = z["ZXXR"] + z["ZXXI"] + z["ZYYR"] + z["ZYYI"]
    off = z["ZXYR"] + z["ZXYI"] + z["ZYXR"] + z["ZYXI"]
    if not diag or not off:
        return False
    return (all(abs(v - 0.2) <= 1e-6 for v in diag)
            and all(abs(v - 1.0) <= 1e-6 for v in off))


def _z_is_period_invariant(freqs, z) -> bool:
    """An impedance that does not vary across period, which implies no earth at all.

    Two further fabrication dialects sit here that the constant test does not reach. The
    two-frequency floor is what stops a genuine single-period impedance being called fabricated on
    the strength of having only one value to be constant over.
    """
    if len(set(freqs)) < 2:
        return False
    return all(_flat(z[c]) for c in Z_COMPONENTS)


def _z_is_synthetic_rho_ramp(freqs, z) -> bool:
    """The synthetic ramp that renders a flat apparent resistivity at every period.

    An impedance built as a multiple of sqrt(f) gives one constant apparent resistivity across the
    whole band. The three-frequency floor is essential: without it the test is vacuously true of
    every single-period file and would swallow real data.
    """
    if len({f for f in freqs if f > 0}) < 3:
        return False
    zr, zi = z["ZXYR"], z["ZXYI"]
    if len(zr) != len(freqs) or len(zi) != len(freqs):
        return False
    rho = [0.2 * (zr[i] ** 2 + zi[i] ** 2) / f for i, f in enumerate(freqs) if f > 0]
    if len(rho) < 3 or min(rho) <= 0:
        return False
    return (max(rho) - min(rho)) <= 0.01 * max(rho)


def _edi_impedance_is_real(raw) -> bool:
    """True when an EDI carries an impedance that is a measurement rather than a known fabrication.

    Only such a file is evidence that an impedance mask is discarding data. An absent or all-zero
    impedance is missing data, not masked data, and the corpus carries hundreds of files whose
    impedance was fabricated by a converter; warning on those would be noise on every legacy GDS
    survey, which is exactly the population the mask exists to serve.
    """
    z = {c: _edi_block(raw, c) for c in Z_COMPONENTS}
    if not any(abs(v) > 1e-6 for c in Z_COMPONENTS for v in z[c]):
        return False
    if _z_is_converter_constant(z):
        return False
    freqs = _edi_block(raw, "FREQ")
    return not (_z_is_period_invariant(freqs, z) or _z_is_synthetic_rho_ramp(freqs, z))


def _edi_has_tipper(raw) -> bool:
    """True when an EDI carries a non-zero tipper.

    An all-zero TXR/TXI/TYR/TYI block is absent data presented as measurement, not a measurement a
    mask would discard.
    """
    for base in ("TXR", "TXI", "TYR", "TYI"):
        if any(v != 0.0 for v in _edi_block(raw, base + ".EXP", base)):
            return True
    return False


def validate(folder: Path, *, allow_large=False, allow_mth5=False) -> Report:
    r = Report()
    root = folder.resolve()

    # --- structure ---
    sy = folder / "survey.yaml"
    if not sy.exists():
        r.add("FAIL", "structure", "survey.yaml is missing")
        return r
    for req in ("README.md", "LICENSE.md"):
        r.add("PASS" if (folder / req).exists() else "WARNING", "structure",
              f"{req} {'present' if (folder/req).exists() else 'missing'}")
    tf_dir = folder / "transfer_functions" / "edi"
    edis = sorted(tf_dir.glob("*.edi")) if tf_dir.exists() else []
    xml_dir = folder / "transfer_functions" / "emtfxml"
    xml_files = sorted(xml_dir.glob("*.xml")) if xml_dir.exists() else []
    mh_dir = folder / "transfer_functions" / "mth5"
    mh_files = (sorted(mh_dir.glob("*.h5")) + sorted(mh_dir.glob("*.mth5"))) if mh_dir.exists() else []
    # A package needs transfer functions in at least ONE of the three accepted homes. emtfxml/ counts
    # since the 2026-08-03 ruling: an EMTF-XML-only survey is a complete submission, and the engine
    # builds it into the same product set an EDI survey gets.
    if not edis and not xml_files and not mh_files:
        r.add("FAIL", "structure", "no transfer functions under transfer_functions/edi/, "
              "transfer_functions/emtfxml/ or transfer_functions/mth5/")

    # --- metadata ---
    # Tolerant of both the Prototype-20 structured schema (project_name; organisation as a map with
    # name/ror; data_types list) and the older flat schema (name; organisation string; data_type).
    try:
        meta = _load_yaml(sy) or {}
    except Exception as e:  # malformed YAML -> a clear FAIL at the contributor gate, not a raw traceback
        r.add("FAIL", "structure", f"survey.yaml is not valid YAML: {e}")
        return r
    # Said ONCE, report-wide, the moment the document is in hand. Without PyYAML the WHOLE file
    # was read by the reduced-fidelity fallback, yet only _check_station_ids declared it, so every
    # other FAIL in the report stood unqualified beside a parser that silently drops shapes PyYAML
    # reads. A reader had no way to tell a fault in the file from an artefact of the parser.
    if not _pyyaml_available():
        r.add("WARNING", "structure",
              "survey.yaml was read with the LIMITED stdlib fallback parser because PyYAML is not "
              "installed. It is reduced-fidelity across the whole document, so any required-field "
              "or register FAIL below may be an artefact of the parser rather than a fault in the "
              "file. Install PyYAML for an authoritative report")
    if not isinstance(meta, dict):
        r.add("FAIL", "structure", "survey.yaml must be a YAML mapping (key: value pairs), not a list or scalar")
        return r
    name = meta.get("project_name") or meta.get("name")
    org = meta.get("organisation")
    org_name = org.get("name") if isinstance(org, dict) else org
    acc = meta.get("access")
    acc_val = acc.get("level") if isinstance(acc, dict) else acc
    required = [("slug", meta.get("slug")), ("project name", name), ("country", meta.get("country")),
                ("organisation", org_name), ("access", acc_val)]
    for label, val in required:
        present = val not in (None, "", "TBD", "TODO")
        r.add("PASS" if present else "FAIL", "metadata",
              f"required field '{label}' {'set' if present else 'missing/placeholder'}")
    # C1 access gate — enum + embargo date. Only run once access is present (the required-field loop above
    # already FAILs a missing access). access.level must be one of the enum (FAIL — required field, no legacy
    # excuse); embargo_until must be ISO YYYY-MM-DD when present (FAIL if malformed). A non-open level is a
    # WARNING (curator attention: the engine will withhold this survey's bytes). An embargoed level whose
    # embargo_until is in the PAST is a stale-embargo WARNING (the engine still withholds — a curator flips
    # level->open to release; it never auto-publishes on a lapsed date). Mirrors engine access_serve_state.
    if acc_val not in (None, "", "TBD", "TODO"):
        acc_norm = str(acc_val).strip().lower()
        if acc_norm not in ACCESS_LEVELS:
            r.add("FAIL", "metadata",
                  f"access.level '{acc_val}' is not one of {ACCESS_LEVELS} — this is a required, enumerated field")
        else:
            emb = acc.get("embargo_until") if isinstance(acc, dict) else None
            emb_raw = str(emb).strip() if emb not in (None, "") else ""
            emb_date = None
            if emb_raw:
                try:
                    from datetime import date as _date  # noqa: PLC0415 (dependency-light; import where used)
                    emb_date = _date.fromisoformat(emb_raw)
                except ValueError:
                    r.add("FAIL", "metadata",
                          f"access.embargo_until '{emb_raw}' is not an ISO date (YYYY-MM-DD)")
            if acc_norm != "open":
                r.add("WARNING", "metadata",
                      f"access.level is '{acc_norm}' (not open) — AusMT will list this survey but WITHHOLD its "
                      f"data bytes until a curator sets level=open")
            if acc_norm == "embargoed" and emb_date is not None:
                from datetime import date as _date2  # noqa: PLC0415
                if emb_date < _date2.today():
                    r.add("WARNING", "metadata",
                          f"access.embargo_until {emb_raw} is in the PAST but level is still 'embargoed' — the "
                          f"survey stays withheld; flip level to open to release it (embargo is not auto-lifted)")
    # C42 (owner queue): access.coordinates gates how station coordinates are SERVED by the engine
    # (exact / generalised to ~11 km / withheld). When present it MUST be one of the enum — an
    # out-of-vocab value would silently fall back to 'exact' and serve exact coordinates the curator
    # meant to protect, so FAIL it (no legacy corpus of bad values). Absent => exact (silent, the
    # record's zero-change default). Mirrors engine extract/_coordaccess.parse_coordinate_policy.
    if isinstance(acc, dict):
        coord_pol = acc.get("coordinates")
        if coord_pol not in (None, ""):
            if str(coord_pol).strip().lower() not in COORDINATE_POLICIES:
                r.add("FAIL", "metadata",
                      f"access.coordinates '{coord_pol}' is not one of {COORDINATE_POLICIES} — it gates "
                      f"how station coordinates are served; an out-of-enum value silently serves them exactly")
    # The same policy MIS-PLACED at document level (the shape an un-indented template comment
    # produced when uncommented). Nothing reads a top-level `coordinates:` key, validator or
    # engine, so `coordinates: withheld` here would publish EXACT station coordinates against the
    # curator's stated intent. Same fail-closed rationale as the enum above; no corpus package
    # carries the key, so there is no legacy cost (section-2 D2).
    if "coordinates" in meta:
        r.add("FAIL", "metadata",
              f"top-level 'coordinates:' is read by NOTHING - the coordinate policy lives at "
              f"access.coordinates (one of {COORDINATE_POLICIES}). Move it inside the access: "
              f"block; left here, station coordinates are served exactly regardless of the value")
    # Station-identifier override for third-party released data. Checked against the package's REAL
    # EDI filenames, which are already in hand, so a key that names nothing is caught here rather
    # than dropping the survey at build time.
    try:
        _declares_station_ids = bool(STATION_IDS_KEY_RE.search(sy.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError):
        # UnicodeDecodeError is NOT an OSError: a non-UTF-8 byte here escaped the guard entirely
        # and crashed validate() out of the engine's in-process call. Still narrow: this raw scan
        # answers one question, and an unreadable file simply does not declare the block.
        _declares_station_ids = False
    _check_station_ids(meta.get("station_ids"), {p.name for p in edis}, r,
                       complete_read=_pyyaml_available(),
                       declared_in_text=_declares_station_ids)
    # The persistent run-id store, read against the ids the station_ids block declares and, where it
    # declares none for a file, that file's stem (see _check_run_ids for why the stem is a proxy).
    run_ids_path = folder / RUN_IDS_FILE
    ts_index_path = folder / TS_INDEX_FILE
    known, complete = _station_id_authority(meta.get("station_ids"), edis)
    if run_ids_path.exists():
        try:
            run_ids_doc = _load_yaml(run_ids_path) or {}
        except Exception as e:  # malformed YAML -> a clear FAIL, not a raw traceback (the survey.yaml posture)
            r.add("FAIL", "run_ids", f"{RUN_IDS_FILE} is not valid YAML: {e}")
        else:
            _check_run_ids(run_ids_doc, known, r, authority_complete=complete)
    # The time-series register, read against the SAME authority: both files key on the published
    # station id, so computing it twice would be two answers to one question.
    if ts_index_path.exists():
        try:
            ts_index_doc = _load_yaml(ts_index_path) or {}
        except Exception as e:
            r.add("FAIL", "ts_index", f"{TS_INDEX_FILE} is not valid YAML: {e}")
        else:
            _check_ts_index(ts_index_doc, known, r, authority_complete=complete)
    # The slug MUST equal the package folder name: the directory IS the slug, and every downstream
    # identifier/URL is au.<slug>.<station>. A divergence silently forks the survey's identity, so
    # this is a FAIL (the _template states the slug must equal the folder name).
    slug_val = meta.get("slug")
    if slug_val not in (None, "", "TBD", "TODO"):
        folder_name = folder.resolve().name
        r.add("PASS" if slug_val == folder_name else "FAIL", "metadata",
              f"slug '{slug_val}' {'matches' if slug_val == folder_name else 'does NOT match'} "
              f"folder name '{folder_name}'")
        # Charset gate: the slug becomes `au.<slug>.<station>` in every id/URL. Anything outside
        # [a-z0-9-] would be silently rewritten by the pipeline's safe_component(), forking the survey's
        # identity between what the contributor declared and what the catalogue/portal publish. FAIL it.
        if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", str(slug_val)):
            r.add("FAIL", "metadata",
                  f"slug '{slug_val}' must be lowercase-hyphenated [a-z0-9-] (no spaces, dots, slashes, "
                  f"underscores or uppercase) — other characters fork the survey identity downstream")
        # Length gate (see SLUG_MAX_LEN). Reported SEPARATELY from the charset gate: "too long" and
        # "wrong characters" are different mistakes with different fixes, and merging them sends a
        # curator hunting for a bad character that is not there.
        if len(str(slug_val)) > SLUG_MAX_LEN:
            r.add("WARNING", "metadata",
                  f"slug '{slug_val}' is {len(str(slug_val))} characters; the limit is {SLUG_MAX_LEN}. "
                  f"A longer slug validates and publishes, then silently withholds every station MTH5 "
                  f"at build time — the HDF5 survey group name truncates at 45 characters, so the "
                  f"round-trip gate cannot find the group it wrote. Shorten it (the folder must be "
                  f"renamed to match); --strict treats this as a failure")
    lic = meta.get("license", "")
    if str(lic).startswith("TBD"):
        r.add("WARNING", "metadata", "license is 'TBD' — must be set before publication")
    elif lic in (None, "", "TODO"):
        r.add("FAIL", "metadata", "required field 'licence' missing/placeholder")
    elif is_recognised_license(lic):
        # Recognised id (allow-list ∪ aliases). Note whether AusMT will redistribute the bytes or only
        # list the station (metadata-only) — the same gate the engine's redistributable() applies.
        served = "redistributable" if canon_license(lic) in {s.upper() for s in REDISTRIBUTABLE_LICENSES} else "recognised (metadata-only — download routes to the source archive)"
        r.add("PASS", "metadata", f"licence '{lic}' is a recognised id ({served})")
    else:
        # Set but NOT a recognised id: a typo like 'CC-BY-4.O' or free text. WARNING keeps the legacy-friendly
        # posture; under --strict (the publication gate) main() escalates every WARNING to a FAIL, so an
        # unrecognised licence CANNOT be published. This is the hole C6 closes: the old build gate redistributed
        # anything starting 'CC', and the validator accepted ANY non-placeholder string.
        r.add("WARNING", "metadata",
              f"licence '{lic}' is not a recognised AusMT licence id (see contract/licenses.json) — "
              f"fix the id before publication; --strict FAILs this")
    # LICENSE.md <-> survey.yaml consistency (design §2.5 — closes the silent-divergence seam). Parse the
    # C34-generated instrument's machine "Licence:  <id>" line (extract/_license_text emits exactly that);
    # WARN if its canonical id disagrees with survey.yaml `license` (survey.yaml is the machine source of
    # truth). A hand-authored LICENSE.md carries no such machine line and is NOT machine-checkable — the
    # check stays SILENT there (no false alarm, no report churn for the existing hand-authored corpus). It
    # emits an item ONLY on a real divergence, which is the seam this closes.
    lic_md = folder / "LICENSE.md"
    if lic_md.exists() and lic not in (None, "", "TODO") and not str(lic).startswith("TBD"):
        try:
            md_text = lic_md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            md_text = ""
        m_lic = re.search(r"^\s*Licence:\s+(\S.*?)\s*$", md_text, re.M)
        if m_lic and canon_license(m_lic.group(1)) != canon_license(lic):
            r.add("WARNING", "license_md",
                  f"LICENSE.md states licence '{m_lic.group(1).strip()}' but survey.yaml license is "
                  f"'{lic}' — the two must agree (survey.yaml is the machine source of truth)")
    # C46 (design §2.1): schema_version validation + attribution/sources capture. Every check here is
    # SILENT on a clean 0.2 survey (no C46 fields, valid version, consistent LICENSE.md) so the existing
    # corpus's report is byte-unchanged; items are emitted only for a NEW field or a real problem.
    sv = meta.get("schema_version")
    attribution = meta.get("attribution")
    sources = meta.get("sources")
    has_c46 = attribution is not None or sources is not None
    if sv is not None:
        sv_str = str(sv).strip()
        if sv_str not in SCHEMA_VERSIONS:
            r.add("WARNING", "schema",
                  f"schema_version '{sv_str}' is not a known AusMT schema ({', '.join(SCHEMA_VERSIONS)})")
        elif sv_str == "0.2" and has_c46:
            r.add("WARNING", "schema",
                  'attribution/sources are schema-0.3 fields but schema_version is "0.2" — bump '
                  'schema_version to "0.3" so the C46 rules apply')
    # attribution: a nested map with a FROZEN key allow-list (the care-field drift lesson). Unknown keys
    # WARN by name; changes_made must be a bool; declared_date ISO-shape when present.
    if attribution is not None:
        if not isinstance(attribution, dict):
            r.add("WARNING", "attribution",
                  "attribution must be a mapping (key: value pairs), not a list or scalar")
        else:
            for k in attribution:
                if k not in ATTRIBUTION_KEYS:
                    r.add("WARNING", "attribution",
                          f"attribution.{k} is not a recognised attribution key (allowed: "
                          f"{', '.join(sorted(ATTRIBUTION_KEYS))})")
            cm = attribution.get("changes_made")
            if cm is not None and not isinstance(cm, bool):
                r.add("WARNING", "attribution",
                      f"attribution.changes_made must be a boolean true/false, got '{cm}'")
            dd = attribution.get("declared_date")
            if dd not in (None, "") and not _iso_date_ok(dd):
                r.add("WARNING", "attribution",
                      f"attribution.declared_date '{dd}' is not an ISO date (YYYY-MM-DD)")
    # sources: a LIST of upstream-dataset maps. Per entry: FROZEN key allow-list; licence validated
    # against the SAME vocab as the top-level license (unrecognised WARNs, FAILs under --strict);
    # retrieved ISO-date-or-year shape; profile vocab. A "ga" profile makes attribution.statement
    # REQUIRED (the GA form mandates exact wording).
    any_ga = False
    if sources is not None:
        if not isinstance(sources, list):
            r.add("WARNING", "sources",
                  "sources must be a LIST of upstream-dataset entries (one map per source dataset)")
        else:
            for idx, s in enumerate(sources):
                if not isinstance(s, dict):
                    r.add("WARNING", "sources",
                          f"sources[{idx}] must be a mapping (title/custodian/identifier/licence/…)")
                    continue
                for k in s:
                    if k not in SOURCE_KEYS:
                        r.add("WARNING", "sources",
                              f"sources[{idx}].{k} is not a recognised source key (allowed: "
                              f"{', '.join(sorted(SOURCE_KEYS))})")
                slic = s.get("licence")
                if slic not in (None, "", "TBD", "TODO"):
                    if is_recognised_license(slic):
                        r.add("PASS", "sources", f"sources[{idx}] licence '{slic}' is a recognised id")
                    else:
                        r.add("WARNING", "sources",
                              f"sources[{idx}] licence '{slic}' is not a recognised AusMT licence id "
                              f"(see contract/licenses.json) — fix it before publication; --strict FAILs this")
                ret = s.get("retrieved")
                if ret not in (None, "") and not _iso_date_or_year_ok(ret):
                    r.add("WARNING", "sources",
                          f"sources[{idx}].retrieved '{ret}' is not an ISO date (YYYY-MM-DD) or a year (YYYY)")
                prof = s.get("profile")
                if prof not in (None, "") and str(prof) not in SOURCE_PROFILES:
                    r.add("WARNING", "sources",
                          f"sources[{idx}].profile '{prof}' is not a recognised attribution profile "
                          f"({', '.join(sorted(SOURCE_PROFILES))})")
                if str(prof) == "ga":
                    any_ga = True
                # §2a: a sources[] entry MAY carry the typed relation/identifier_type (it IS the object
                # the related-identifiers model types) — vocab-check them fail-closed wherever they appear.
                _check_typed_relation(r, "sources", idx, s)
    # A GA-profile source mandates the exact custodian wording — attribution.statement REQUIRED.
    if any_ga:
        stmt = attribution.get("statement") if isinstance(attribution, dict) else None
        if stmt in (None, "", "TBD", "TODO"):
            r.add("WARNING", "attribution",
                  "a sources[].profile is 'ga' (Geoscience Australia), which mandates exact attribution "
                  "wording, but attribution.statement is not set — fix it before publication; --strict FAILs this")
    # §2a (identifiers design — the related-identifiers model): a repeatable list of TYPED provenance
    # relations to identifiers AusMT does NOT own. It TYPES the C46 sources[] object — SAME key allow-list
    # (SOURCE_KEYS), not a parallel structure — adding a `relation` and an `identifier_type`, both
    # FAIL-CLOSED vocabs (like access.coordinates). This is the wave-1 EXPAND field: it lands ALONGSIDE the
    # flat identifiers.dataset_doi + time_series.collection_pid, which keep being populated until a later
    # wave switches consumers over. SILENT when absent (the existing corpus carries no related_identifiers).
    related = meta.get("related_identifiers")
    if related is not None:
        if not isinstance(related, list):
            r.add("WARNING", "related_identifiers",
                  "related_identifiers must be a LIST of typed relation entries "
                  "({identifier, identifier_type, relation, custodian})")
        else:
            for idx, ri in enumerate(related):
                if not isinstance(ri, dict):
                    r.add("WARNING", "related_identifiers",
                          f"related_identifiers[{idx}] must be a mapping "
                          f"(identifier/identifier_type/relation/custodian)")
                    continue
                for k in ri:
                    if k not in SOURCE_KEYS:
                        r.add("WARNING", "related_identifiers",
                              f"related_identifiers[{idx}].{k} is not a recognised key (allowed: "
                              f"{', '.join(sorted(SOURCE_KEYS))})")
                _check_typed_relation(r, "related_identifiers", idx, ri)
    # Contributor credit model (CONTRIBUTOR-CREDIT-SPEC C1/C2): creators[] (who the citation names, an
    # ORDERED editorial list) and contributors[] (who did what, repeatable). Both are NEW additive lists;
    # SILENT when absent (the existing corpus carries neither). name_type is FAIL-CLOSED for both; role is
    # FAIL-CLOSED for contributors; structure warns; ORCID/ROR reuse the existing helpers. creators empty/
    # absent leaves the org-year citation synthesis as the fallback (owner ruling: honest for state data).
    creators = meta.get("creators")
    if creators is not None:
        if not isinstance(creators, list):
            r.add("WARNING", "creators",
                  "creators must be a LIST of ordered citation-name entries ({name, name_type, orcid?/ror?})")
        else:
            for idx, c in enumerate(creators):
                _check_credit_row(r, "creators", idx, c, roled=False)
    contributors = meta.get("contributors")
    if contributors is not None:
        if not isinstance(contributors, list):
            r.add("WARNING", "contributors",
                  "contributors must be a LIST of role entries ({name, name_type, role, orcid?/ror?})")
        else:
            for idx, c in enumerate(contributors):
                _check_credit_row(r, "contributors", idx, c, roled=True)
    # MTCAT 2.0 core field homes (S1): subjects[], discovery_description, identity_classification,
    # dates.issued, citation, acknowledgements[], organisations[]. All optional, silent when absent.
    _check_mtcat20_fields(meta, r)
    # §2b (identifiers design): identifiers.instrument_pid — the ONE survey/platform-level instrument PID
    # (PIDINST, e.g. 10.82388/<id>), the survey-layer counterpart to the deep per-serial EDI DOIs. Same
    # light format posture as instruments[].pid / RAiD above: an https:// URL or a bare handle/DOI,
    # WARNING-only (a curator hint, no registry lookup) — an additive/optional field must never BLOCK.
    # Absent/blank/placeholder is silent.
    ids = meta.get("identifiers") if isinstance(meta.get("identifiers"), dict) else {}
    inst_pid = ids.get("instrument_pid")
    if inst_pid not in (None, "", "TBD", "TODO") and not instrument_pid_format_ok(inst_pid):
        r.add("WARNING", "metadata",
              f"identifiers.instrument_pid '{inst_pid}' does not look like a survey/platform instrument "
              f"PID (expected an https:// URL or a bare handle/DOI, e.g. 10.82388/<id>)")
    # §2a (the AusLAMP-SA redundancy the inventory found): identifiers.dataset_doi and the raw-TS
    # time_series.collection_pid carrying the BYTE-IDENTICAL value is the systematic pattern (all 7
    # AusLAMP-SA surveys reuse one NCI collection DOI as both) — a symptom of an empty dataset-DOI slot
    # papered over with the collection pointer. Surface it at curation time as a WARNING (never a FAIL —
    # the data is publishable): the fix is to model the shared value as a single related_identifiers
    # relation row, not to keep it in two roles. Trimmed-string compare (a stray space is not a real
    # distinction).
    ts = meta.get("time_series") if isinstance(meta.get("time_series"), dict) else {}
    dd, cp = ids.get("dataset_doi"), ts.get("collection_pid")
    if dd not in (None, "") and cp not in (None, "") and str(dd).strip() == str(cp).strip():
        r.add("WARNING", "provenance",
              f"identifiers.dataset_doi and time_series.collection_pid are byte-identical ('{dd}') — the "
              f"systematic AusLAMP-SA redundancy (one NCI collection DOI reused as both the dataset DOI and "
              f"the raw-TS pointer). Model it as a single related_identifiers relation row, not two roles")
    # Identifier consolidation (idcons lane, SPEC §3 / §4.4): the flat identifier keys below are RETIRED
    # from the editor UI and are migrated into the typed related_identifiers list (+ publications[]) by
    # _tools/migrate_identifiers.py. They stay READABLE by the engine this wave, so an un-migrated survey
    # still PUBLISHES — hence WARNING, never FAIL (retiring the reader before the data is migrated would
    # blank the DOI/collection facets). Value-based, matching the validator's blank-is-silent house
    # posture: a deprecation WARNING fires only when a retired key carries a REAL value a curator must
    # move, so the all-null shipped _example stays clean while a real un-migrated corpus survey surfaces.
    _MIGRATE = "run _tools/migrate_identifiers.py to move it into the typed related_identifiers list"
    if dd not in (None, "", "TBD", "TODO"):
        r.add("WARNING", "deprecation",
              f"identifiers.dataset_doi ('{dd}') is a RETIRED flat identifier key — {_MIGRATE} "
              f"(still read this wave; retires after the corpus migration)")
    if cp not in (None, "", "TBD", "TODO"):
        r.add("WARNING", "deprecation",
              f"time_series.collection_pid ('{cp}') is a RETIRED flat identifier key — {_MIGRATE} "
              f"(still read this wave; retires after the corpus migration)")
    if ids.get("related_publication") not in (None, "", "TBD", "TODO") \
            or ids.get("related_publication_doi") not in (None, "", "TBD", "TODO"):
        r.add("WARNING", "deprecation",
              "identifiers.related_publication / related_publication_doi are RETIRED legacy keys "
              "(superseded by publications[]) — move any DOI into publications[] and drop the free text "
              "(run _tools/migrate_identifiers.py)")
    if ids.get("project") not in (None, "", "TBD", "TODO"):
        r.add("WARNING", "deprecation",
              "identifiers.project is a RETIRED orphan key (read by nothing) — remove it "
              "(run _tools/migrate_identifiers.py)")
    for _inst in _as_list(meta.get("instruments")):
        if isinstance(_inst, dict) and _inst.get("pid") not in (None, "", "TBD", "TODO"):
            r.add("WARNING", "deprecation",
                  "instruments[].pid (per-row instrument PID) is RETIRED from the editor — record the "
                  "survey/platform PID as identifiers.instrument_pid or a typed related_identifiers row "
                  "(run _tools/migrate_identifiers.py)")
            break
    # "Identifiers by data level" (D-L3): sources[] is DEPRECATED. Its acquisition fields (title,
    # licence, retrieved, statement, profile, custodian) are now OPTIONAL keys on a related_identifiers
    # row (identifies: entire), so the two provenance lists merge into ONE typed carrier. WARNING, never
    # FAIL (same posture as the flat keys): a survey still carrying sources[] PUBLISHES until migrated.
    # Value-based: fires only when sources[] actually carries an entry, so the all-null example stays
    # clean. The row-level checks above still run over sources[] entries so nothing goes unvalidated.
    if isinstance(sources, list) and sources:
        r.add("WARNING", "deprecation",
              "sources[] is DEPRECATED (identifiers-by-level): its acquisition fields (licence, "
              "retrieved, statement, profile, title, custodian) are now optional keys on a "
              "related_identifiers row with identifies: entire. Run _tools/migrate_identifies.py to "
              "merge each source into the typed list; sources[] is still read this wave")
    # Contributor credit model (CONTRIBUTOR-CREDIT-SPEC C3): lead_investigator and principal_investigators
    # are RETIRED. lead_investigator's meaning moves to a contributors row (role: ProjectLeader);
    # principal_investigators seeds creators[]. WARNING, never FAIL (the flat-key pattern): the engine
    # still reads both until the ausmt follow-up, so an un-migrated survey PUBLISHES. Value-based, and the
    # « REPLACE » template sentinel counts as a placeholder, so the shipped example/template stay silent
    # while a real name (or a real PI list) surfaces.
    _CREDIT_MIGRATE = "run _tools/migrate_credit.py to seed creators[]/contributors[] and retire it"
    li_dep = meta.get("lead_investigator")
    if isinstance(li_dep, dict) and _has_real_value(li_dep.get("name")):
        r.add("WARNING", "deprecation",
              f"lead_investigator ('{str(li_dep.get('name')).strip()}') is a RETIRED field - its meaning "
              f"moves to a contributors row with role: ProjectLeader; {_CREDIT_MIGRATE} "
              f"(still read this wave; retires after the corpus migration)")
    pis_dep = meta.get("principal_investigators")
    if isinstance(pis_dep, list) and any(
            isinstance(p, dict) and _has_real_value(p.get("name")) for p in pis_dep):
        r.add("WARNING", "deprecation",
              f"principal_investigators is a RETIRED field - it seeds the ordered creators[] citation "
              f"list; {_CREDIT_MIGRATE} (still read this wave; retires after the corpus migration)")
    # C7 / §2a: a survey is provenance-incomplete ONLY when it carries NEITHER a flat identifier (dataset
    # DOI or survey PID) NOR a typed provenance relation. Because AusMT curates records whose provenance
    # lives in related identifiers rather than a minted DOI, a well-formed related_identifiers entry — or a
    # typed sources[] entry, the SAME object (a non-blank identifier + an in-vocab relation) — satisfies it
    # too. Crediting either route keeps this WARNING consistent with the add-survey badge fix, which already
    # stopped treating 'no dataset DOI' as incomplete provenance. Absent both routes, it still warns.
    # `ids` (the isinstance-guarded read above) rather than a fresh meta.get: a bare `identifiers:`
    # key reads as None, and .get on it crashed validate() out of the engine's in-process call.
    has_flat_id = ids.get("dataset_doi") or ids.get("survey_pid")
    typed_pool = (related if isinstance(related, list) else []) + (sources if isinstance(sources, list) else [])
    has_typed_relation = any(_is_typed_provenance_entry(e) for e in typed_pool)
    if not has_flat_id and not has_typed_relation:
        # The SUGGESTION names live carriers only. It read "identifiers.dataset_doi or ... sources",
        # both of which this same report warns about as RETIRED and DEPRECATED respectively, so a
        # curator following the validator's advice earned a second warning for doing so. Either
        # route still SATISFIES the gate above (back-compat is unchanged); neither is where a new
        # identifier goes.
        r.add("WARNING", "provenance",
              "no provenance identifier - record will be badged 'provenance incomplete'. Satisfy it "
              "with identifiers.survey_pid, or with a typed related_identifiers[] row: a non-blank "
              "identifier plus either an in-vocab relation or an `identifies` level (the relation "
              "derives from the level). identifiers.dataset_doi is RETIRED and sources[] is "
              "DEPRECATED; both are still read, but neither takes a new identifier")
    # C7: ORCID (ISO 7064 11-2 checksum) + ROR + RAiD format sanity — WARNING only (a curator hint;
    # these federated identifiers have real external registries this dependency-light validator does
    # not query). Absent/blank values are silent — these fields are optional, not required.
    li = meta.get("lead_investigator")
    orcid = li.get("orcid") if isinstance(li, dict) else None
    if orcid not in (None, "", "TBD", "TODO"):
        if not orcid_checksum_ok(orcid):
            r.add("WARNING", "metadata",
                  f"lead_investigator.orcid '{orcid}' is not a valid ORCID (bad format or failed ISO "
                  f"7064 11-2 checksum) — e.g. https://orcid.org/0000-0002-1825-0097")
    for pi in _as_list(meta.get("principal_investigators")):
        pi_orcid = pi.get("orcid") if isinstance(pi, dict) else None
        if pi_orcid not in (None, "", "TBD", "TODO") and not orcid_checksum_ok(pi_orcid):
            r.add("WARNING", "metadata",
                  f"principal_investigators ORCID '{pi_orcid}' is not a valid ORCID (bad format or "
                  f"failed ISO 7064 11-2 checksum)")
    org = meta.get("organisation")
    ror = org.get("ror") if isinstance(org, dict) else None
    if ror not in (None, "", "TBD", "TODO") and not ror_format_ok(ror):
        r.add("WARNING", "metadata",
              f"organisation.ror '{ror}' does not look like a ROR id (expected a bare 9-char id or "
              f"https://ror.org/<id>, e.g. https://ror.org/00892tw58)")
    raid = meta.get("identifiers", {}).get("project_raid") if isinstance(meta.get("identifiers"), dict) else None
    if raid not in (None, "", "TBD", "TODO") and not raid_format_ok(raid):
        r.add("WARNING", "metadata",
              f"identifiers.project_raid '{raid}' does not look like a RAiD URL (expected "
              f"https://raid.org/<prefix>/<suffix>)")
    # PID-schema: instruments[].pid (optional) — a persistent identifier for an instrument SYSTEM (the
    # AuScope Instrument Registry URL/handle). Same posture as ROR/RAiD above: WARNING-only curator hint,
    # deliberately light (no registry lookup — this validator is dependency-light and cannot resolve the
    # external registry). Absent/blank/placeholder values are silent (the field is optional, not required).
    for inst in _as_list(meta.get("instruments")):
        pid = inst.get("pid") if isinstance(inst, dict) else None
        if pid not in (None, "", "TBD", "TODO") and not instrument_pid_format_ok(pid):
            label = " ".join(str(x) for x in [inst.get("manufacturer"), inst.get("model")] if x) or "instrument"
            r.add("WARNING", "metadata",
                  f"instruments[].pid '{pid}' ({label}) does not look like an instrument-registry PID "
                  f"(expected an https:// URL or a bare handle/DOI, e.g. "
                  f"https://instruments.auscope.org.au/... or 10.25914/<id>)")
    ver = meta.get("version")
    if not ver:
        r.add("WARNING", "metadata", "no version — recommend semantic versioning, e.g. 1.0.0")
    elif not re.match(r"^\d+\.\d+\.\d+$", str(ver)):
        r.add("WARNING", "metadata", f"version '{ver}' is not semantic (expected MAJOR.MINOR.PATCH)")
    coll = meta.get("collection")
    if isinstance(coll, dict) and coll.get("id"):
        cid = str(coll["id"])
        if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", cid):
            r.add("WARNING", "collection",
                  f"collection id '{cid}' is not lowercase-hyphenated — see the AusMT docs developer/collection-ids.md "
                  f"(curator confirms it is the correct, existing programme id)")
        else:
            r.add("PASS", "collection", f"collection id '{cid}' well-formed")
        status = coll.get("status")
        if status is not None and str(status) not in ("active", "completed", "archived"):
            r.add("WARNING", "collection",
                  f"collection status '{status}' is not one of active/completed/archived")
        _check_collection_prose(coll.get("prose"), r)
    # channels_recorded (optional): shape and vocabulary here, the two survey-wide masks it arms
    # below. Both masks are EDI-only in the build, so the silent-loss checks read the EDIs alone.
    declared_channels = _check_channels_recorded(meta.get("channels_recorded"), r)
    mask_tipper = bool(declared_channels) and not ({"hz"} & declared_channels)
    mask_impedance = bool(declared_channels) and not ({"ex", "ey"} & declared_channels)
    # nci_base (optional): a contributor-supplied NCI THREDDS fileServer dir concatenated into the
    # published download URL. Validate scheme + host so a typo'd or non-http(s) value can't ship a
    # broken/unsafe link (the engine also drops a non-http(s) nci_base defensively).
    nci_base = meta.get("nci_base")
    if nci_base is not None and str(nci_base).strip():
        if re.match(r"^https?://[^\s/]+/.+", str(nci_base).strip()):
            r.add("PASS", "distribution", "nci_base is a well-formed absolute http(s) URL")
        else:
            r.add("FAIL", "distribution",
                  f"nci_base must be an absolute http(s) URL to a NCI THREDDS fileServer directory, got "
                  f"'{nci_base}' — a typo'd scheme/host would publish broken or unsafe download links")
    rn = meta.get("release_notes")
    if rn is not None:
        if not isinstance(rn, list):
            r.add("WARNING", "metadata", "release_notes should be a list of {version, date, note}")
        else:
            for entry in rn:
                if not (isinstance(entry, dict) and entry.get("version")):
                    r.add("WARNING", "metadata", "each release_notes entry needs at least a 'version'")
                    break

    # --- security: traversal, symlinks, archives, extensions, size, magic bytes ---
    for f in folder.rglob("*"):
        rel = f.relative_to(folder)
        # path traversal / absolute / parent escapes
        if ".." in rel.parts or f.is_symlink():
            r.add("FAIL", "security", f"unsafe path or symlink: {rel}")
            continue
        try:
            if not str(f.resolve()).startswith(str(root)):
                r.add("FAIL", "security", f"path escapes survey root: {rel}")
                continue
        except OSError:
            r.add("FAIL", "security", f"unresolvable path: {rel}")
            continue
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext in DISALLOWED_EXT:
            r.add("FAIL", "security", f"disallowed executable/script type: {rel}")
        if ext in ARCHIVE_EXT:
            r.add("FAIL", "security", f"archives not accepted in a survey package (submit extracted files): {rel}")
        if f.stat().st_size > MAX_FILE_MB * 1e6:
            lvl = "WARNING" if allow_large else "FAIL"
            r.add(lvl, "security", f"file exceeds {MAX_FILE_MB} MB: {rel}"
                  + ("" if allow_large else " (curator may override with --allow-large)"))
        # magic-byte / anti-masquerade for declared binary TF types
        if ext in MAGIC:
            with f.open("rb") as fh:
                head = fh.read(len(MAGIC[ext]))
            if head != MAGIC[ext]:
                r.add("FAIL", "security", f"{rel}: declared {ext} but content is not {ext} (magic-byte mismatch)")
        # anti-masquerade for .edi (a TEXT format): EDIs are printable text (>MARKERS / KEY=VALUE). A NUL
        # byte means binary content — a renamed executable/zip/image, or a polyglot with a valid-looking
        # HEAD and an appended binary payload that the coordinate parse alone would not catch.
        if ext == ".edi" and b"\x00" in f.read_bytes():
            r.add("FAIL", "security", f"{rel}: declared .edi but content is binary (NUL byte) — possible masquerade")
        # anti-masquerade for .xml under transfer_functions/: an EMTF XML is TEXT whose root element
        # is <EM_TF> (the EarthScope schema). A .xml there that never opens that element is not a
        # transfer function whatever it is named, and now that EMTF XML is a standard accepted input
        # it would otherwise be handed to the engine to fail per-station at build time, where the
        # station simply goes missing from the catalogue. Fail it here, at the gate, like the .edi
        # NUL-byte check above. Reads a bounded prefix, so a large file is not slurped to decide this.
        if ext == ".xml" and "transfer_functions" in rel.parts:
            with f.open("rb") as fh:
                head = fh.read(EMTFXML_HEAD_SCAN_BYTES)
            if not EMTFXML_ROOT_RE.search(head.decode("utf-8", "replace")):
                r.add("FAIL", "security", f"{rel}: declared .xml under transfer_functions/ but it is "
                      "not an EMTF XML transfer function (no <EM_TF> root element)")
    # Antivirus is a CI responsibility, not this validator's. If CI has already run ClamAV it
    # sets AUSMT_CLAMAV_RAN=1, and we record PASS so --strict does not fail an already-scanned
    # survey. Outside CI we stay honest: a WARNING that the scan was NOT performed here.
    if os.environ.get("AUSMT_CLAMAV_RAN") == "1":
        r.add("PASS", "security", "antivirus handled upstream (ClamAV ran in CI)")
    else:
        r.add("WARNING", "security",
              "antivirus (ClamAV) scan is NOT performed by this validator; it runs as a CI step "
              "(see .github/workflows). Set AUSMT_CLAMAV_RAN=1 once scanned to clear this.")
    accepted = ALLOWED_TF_EXT | (OPTIN_TF_EXT if allow_mth5 else set())
    tf_files = list((folder / "transfer_functions").rglob("*")) if (folder / "transfer_functions").exists() else []
    for f in tf_files:
        if not f.is_file():
            continue
        # A dotfile is repository plumbing, never a transfer function: .gitkeep is the only way an
        # empty transfer_functions/ folder is tracked at all, and the shipped _template carries
        # three, so the README recipe produced a package that could not validate. Exempt from THIS
        # suffix scan only; every security check above (traversal, symlink, disallowed extension,
        # archive, size, magic bytes) has already read the file, and the ClamAV posture is untouched.
        if f.name.startswith("."):
            continue
        if f.suffix.lower() not in accepted:
            extra = ("" if allow_mth5 else
                     " (.edi, .xml and .mth5 accepted; enable .zmm/.zrr/.j with --allow-optin-formats)")
            r.add("FAIL", "security", f"unaccepted file type in transfer_functions/: {f.relative_to(folder)}{extra}")

    # generated provenance manifest: SHA256 for every accepted file (anti-tamper / canonicalisation record)
    man = []
    for f in sorted(folder.rglob("*")):
        if f.is_file() and not f.is_symlink():
            try:
                man.append({"path": str(f.relative_to(folder)),
                            "sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
                            "bytes": f.stat().st_size})
            except OSError:
                pass
    r.manifest = man
    r.add("PASS", "manifest", f"SHA256 manifest generated for {len(man)} files")

    # --- EDI parse + coordinates + duplicates (lightweight; mt_metadata used if available) ---
    seen_xy = {}
    extent = meta.get("geographic_extent") or {}
    if not isinstance(extent, dict):
        extent = {}   # mini_yaml fallback leaves an inline {…} unparsed; fall back to the national box
    def _flt(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None   # a quoted/garbage bound (west: "136.97") -> treated as undeclared, never a str<float crash
    w, e, s, n = (_flt(extent.get("west")), _flt(extent.get("east")), _flt(extent.get("south")), _flt(extent.get("north")))
    box = (w, e, s, n) if None not in (w, e, s, n) else AUS_BBOX
    n_parse_fail = 0
    n_masked_tipper, masked_impedance = 0, []
    for p in edis:
        raw = p.read_text(encoding="latin-1", errors="replace")
        # tolerate CRLF/CR and indented >markers / KEY= lines (EDL/BIRRP) — same normalisation
        # the science readers use, so the validator and the pipeline agree on what is parseable.
        raw = _norm(raw)
        # Counted before any parse gate, because a file the build masks is masked whether or not it
        # also has a coordinate problem.
        if mask_tipper and _edi_has_tipper(raw):
            n_masked_tipper += 1
        if mask_impedance and _edi_impedance_is_real(raw):
            masked_impedance.append(p.name)
        (lat, _lat_tier), (lon, _lon_tier) = edi_coords_resolved(raw)
        if lat is None or lon is None:
            n_parse_fail += 1
            r.add("FAIL", "edi_parse",
                  f"{p.name}: missing coordinates (LAT/LONG in HEAD, REFLAT/REFLONG in "
                  f"DEFINEMEAS, or LATITUDE/LONGITUDE in INFO)")
            continue
        # The one tier where mirroring the reference reader makes this gate MORE permissive than the
        # build. mt_metadata, which the build parses with, reads HEAD and DEFINEMEAS only, so an
        # axis that resolves nowhere but the INFO block passes here and is then published at 0.0.
        # Still a PASS (the reference reader does resolve it, and the gate must not be stricter than
        # its reader), but never a silent one.
        if "INFO" in (_lat_tier, _lon_tier):
            _axes = " and ".join(a for a, t in (("latitude", _lat_tier), ("longitude", _lon_tier))
                                 if t == "INFO")
            r.add("WARNING", "coordinates",
                  f"{p.name}: {_axes} read only from the >INFO block. The build parses with "
                  f"mt_metadata, which reads HEAD LAT/LONG and DEFINEMEAS REFLAT/REFLONG only, so "
                  f"this station would publish at 0.0. Put the coordinate in one of those fields.")
        if not re.search(r"^>FREQ", raw, re.M):
            if re.search(r"SPECTRA", raw):
                # Phoenix EMpower spectra-section EDI: no >FREQ/impedance block, but the AusMT
                # extractor recovers Z + tipper from the cross-power SPECTRA directly (dependency-
                # free), so this is a supported, first-class format — not a failure or a special case.
                r.add("PASS", "edi_parse",
                      f"{p.name}: spectra-section EDI (cross-power SPECTRA) — supported; "
                      f"impedance is recovered from the spectra at build time")
            else:
                n_parse_fail += 1
                r.add("FAIL", "edi_parse", f"{p.name}: missing FREQ block (no impedance found)")
                continue
        if not (box[2] <= lat <= box[3] and box[0] <= lon <= box[1]):
            r.add("WARNING", "coordinates", f"{p.name}: lat/lon {lat:.3f},{lon:.3f} outside declared extent")
        key = (round(lat, 4), round(lon, 4))
        if key in seen_xy:
            r.add("WARNING", "duplicates", f"{p.name}: ~same location as {seen_xy[key]} (<~10 m)")
        else:
            seen_xy[key] = p.name
    if edis and n_parse_fail == 0:
        r.add("PASS", "edi_parse", f"all {len(edis)} EDIs parsed with coordinates")

    # --- channels_recorded: what the declared masks would withhold from the served files ---
    if n_masked_tipper:
        r.add("WARNING", "channels",
              f"channels_recorded declares no {CHANNEL_LABELS['hz']} yet {n_masked_tipper} of "
              f"{len(edis)} EDIs carry a non-zero tipper. The build masks the tipper survey-wide, "
              f"so it and every product derived from it are withheld; the source files are still "
              f"served byte for byte. Declare the vertical coil if it was recorded")
    if masked_impedance:
        shown = ", ".join(masked_impedance[:8])
        more = f", and {len(masked_impedance) - 8} more" if len(masked_impedance) > 8 else ""
        r.add("WARNING", "channels",
              f"channels_recorded declares neither {CHANNEL_LABELS['ex']} nor "
              f"{CHANNEL_LABELS['ey']} yet {len(masked_impedance)} of {len(edis)} EDIs carry an "
              f"impedance that is not a recognised fabrication ({shown}{more}). The build masks "
              f"the impedance, the resistivity, the phase and every other derived product; the "
              f"source files are still served byte for byte")
    if declared_channels and not [i for i in r.items
                                  if i["check"] == "channels" and i["level"] == "FAIL"]:
        labels = [lab for key, lab in CHANNEL_LABELS.items() if key in declared_channels]
        labels += sorted(key for key in declared_channels if key not in CHANNEL_LABELS)
        masked = [what for what, on in (("tipper", mask_tipper), ("impedance", mask_impedance)) if on]
        r.add("PASS", "channels",
              f"channels_recorded: {len(declared_channels)} channel(s) declared "
              f"({' '.join(labels)}); "
              f"{' and '.join(masked) + ' masked survey-wide' if masked else 'no survey-wide mask'}")

    # --- MTH5 transfer-function validation (structure / version / TF groups / station metadata) ---
    for h5 in mh_files:
        _validate_mth5(h5, r)

    # --- citation/DOI sanity ---
    for pub in _as_list(meta.get("publications")):
        doi = pub.get("doi") if isinstance(pub, dict) else None
        if doi and not re.match(r"^10\.\d{4,9}/\S+$", str(doi)):
            r.add("WARNING", "citation", f"publication DOI looks malformed: {doi}")

    return r


def _grab(text, key):
    # [ \t] rather than \s around '=': \s matches the NEWLINE, so an EMPTY value line ('DATAID=')
    # silently captured the NEXT header line as the value (found arming the D5 id authority).
    # Leading whitespace is legal in EDI and real generators indent their header keys, so the
    # anchor tolerates it. The key must still open the line's content, so a REFLAT= line can
    # never satisfy a LAT= read.
    m = re.search(rf"^[ \t]*{key}[ \t]*=[ \t]*(.+?)[ \t]*$", text, re.M | re.I)
    return m.group(1).strip().strip('"') if m else None


_HDF5_MAGIC = b"\x89HDF\r\n\x1a\n"


def _validate_mth5(path: Path, r) -> None:
    """Validate an MTH5 transfer-function file: HDF5 signature, then (if mth5/mt_metadata are
    installed) supported version, transfer-function groups present, and station metadata
    extractable. AusMT reads only transfer functions + metadata from MTH5 — never raw time series.
    Corrupt/unsupported files FAIL; missing-but-non-fatal metadata WARNs; absent libraries WARN
    (CI installs them and is authoritative)."""
    try:
        with open(path, "rb") as fh:
            sig = fh.read(8)
    except OSError as exc:
        r.add("FAIL", "mth5", f"{path.name}: cannot read file ({exc})")
        return
    if sig != _HDF5_MAGIC:
        r.add("FAIL", "mth5", f"{path.name}: not a valid HDF5/MTH5 file (bad signature)")
        return

    try:
        from mth5.mth5 import MTH5  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        r.add("WARNING", "mth5",
              f"{path.name}: HDF5 signature OK; mth5/mt_metadata not installed here so structure, "
              f"version and TF groups are validated in CI (pip install mth5 mt_metadata).")
        return

    m = MTH5()
    try:
        m.open_mth5(str(path), mode="r")
    except Exception as exc:  # noqa: BLE001
        r.add("FAIL", "mth5", f"{path.name}: not a readable MTH5 file ({exc})")
        return
    try:
        ver = getattr(m, "file_version", None)
        if ver:
            r.add("PASS", "mth5", f"{path.name}: MTH5 v{ver}")
        tf_ids = []
        try:
            df = m.tf_summary.to_dataframe() if getattr(m, "tf_summary", None) is not None else None
            if df is not None and len(df):
                tf_ids = list(df["station"]) if "station" in df.columns else list(range(len(df)))
        except Exception:  # noqa: BLE001
            tf_ids = []
        if not tf_ids:
            # fall back to walking the groups
            try:
                tf_ids = [k for k in m.transfer_functions_group.groups_list] if getattr(
                    m, "transfer_functions_group", None) is not None else []
            except Exception:  # noqa: BLE001
                tf_ids = []
        if tf_ids:
            r.add("PASS", "mth5", f"{path.name}: {len(tf_ids)} transfer-function group(s) present")
        else:
            r.add("FAIL", "mth5", f"{path.name}: no transfer-function groups found")
        # station metadata extractable?
        try:
            stns = list(m.station_list) if getattr(m, "station_list", None) is not None else []
        except Exception:  # noqa: BLE001
            stns = []
        if not stns and not tf_ids:
            r.add("WARNING", "mth5", f"{path.name}: station metadata not extractable")
    finally:
        try:
            m.close_mth5()
        except Exception:  # noqa: BLE001
            pass


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--json", default=None)
    ap.add_argument("--strict", action="store_true", help="treat WARNINGs as failures")
    ap.add_argument("--allow-large", action="store_true",
                    help="curator override: downgrade >MAX_FILE_MB from FAIL to WARNING")
    ap.add_argument("--allow-optin-formats", dest="allow_mth5", action="store_true",
                    help="also accept .zmm/.zrr/.j (EDI, EMTF XML and MTH5 are accepted by default)")
    ap.add_argument("--allow-mth5", dest="allow_mth5", action="store_true", help=argparse.SUPPRESS)  # deprecated alias, same dest
    a = ap.parse_args(argv)
    rep = validate(Path(a.folder), allow_large=a.allow_large, allow_mth5=a.allow_mth5)
    for i in rep.items:
        print(f"[{i['level']:7}] {i['check']:12} {i['message']}")
    c = rep.counts()
    print(f"\n{c['PASS']} PASS · {c['WARNING']} WARNING · {c['FAIL']} FAIL")
    if a.json:
        Path(a.json).write_text(json.dumps({"counts": c, "items": rep.items, "manifest": rep.manifest}, indent=2))
    fail = rep.worst() == LEVELS["FAIL"] or (a.strict and rep.worst() >= LEVELS["WARNING"])
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
