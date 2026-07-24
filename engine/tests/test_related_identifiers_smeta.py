"""§2a/§2b (identifiers design — the related-identifiers model): survey.yaml -> SMETA must carry the
top-level related_identifiers list (typed-core keys only) and the survey/platform-level
identifiers.instrument_pid, and mtcat_document must federate related_identifiers when present.

FAILS IF (pre-fix): SMETA has no 'related_identifiers' key (related_identifiers[] discarded); SMETA has
no 'instrument_pid' key; a non-mapping entry crashes/leaks; mtcat surveys omit related_identifiers.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from extract import build_portal as bp   # noqa: E402

_MIN = {"name": "X", "slug": "x", "organisation": "Org", "license": "CC-BY-4.0"}

# A populated typed list mirroring vulcan-2022's real survey.yaml: a DOI-typed IsDerivedFrom with a
# custodian. The stored entry may carry wider SOURCE_KEYS; only the four typed-core keys are served.
_RI_SURVEY = {**_MIN, "related_identifiers": [
    {"identifier": "10.25914/sv5r-zw68", "identifier_type": "DOI",
     "relation": "IsDerivedFrom", "custodian": "NCI",
     # extra SOURCE_KEYS the drawer does not render — must be dropped, not shipped:
     "title": "AusLAMP SA archive", "licence": "CC-BY-4.0", "retrieved": "2022"}]}


def test_related_identifiers_of_serves_typed_core_only():
    """FAILS IF: the pass-through leaks non-typed-core keys (title/licence/retrieved) into SMETA, or
    drops one of the four the drawer renders."""
    got = bp._related_identifiers_of(_RI_SURVEY)
    assert got == [{"identifier": "10.25914/sv5r-zw68", "identifier_type": "DOI",
                    "relation": "IsDerivedFrom", "custodian": "NCI"}], got


def test_related_identifiers_of_emits_identifies_verbatim_when_present():
    """D-L1 (SPEC §9): a row's `identifies` (WHAT it points at, NCI Table 1 level) is emitted VERBATIM
    into SMETA alongside the four typed-core keys — the drawer/files-tab key off it. FAILS IF the
    recognised-key allowlist was not extended and identifies is dropped."""
    y = {**_MIN, "related_identifiers": [
        {"identifier": "10.25914/sv5r-zw68", "identifies": "raw_packed", "identifier_type": "DOI",
         "relation": "IsDerivedFrom", "custodian": "NCI",
         # acquisition keys still dropped (the drawer does not render them):
         "title": "AusLAMP SA archive", "licence": "CC-BY-4.0"}]}
    assert bp._related_identifiers_of(y) == [
        {"identifier": "10.25914/sv5r-zw68", "identifier_type": "DOI", "relation": "IsDerivedFrom",
         "custodian": "NCI", "identifies": "raw_packed"}]


def test_related_identifiers_of_omits_identifies_when_absent():
    """Back-compat: a legacy row without identifies yields the byte-identical four-key dict — no null
    identifies key is introduced (absent -> omitted per entry)."""
    got = bp._related_identifiers_of(_RI_SURVEY)
    assert "identifies" not in got[0]


def test_related_identifiers_of_absent_is_empty_list():
    """Funders convention: always a list, [] when the survey declares none (the drawer treats [] as
    'render nothing')."""
    assert bp._related_identifiers_of(_MIN) == []


def test_related_identifiers_of_skips_non_mapping_entries():
    """Defensive (mirrors _funders_of): a bare string / non-dict entry is skipped, never crashes."""
    y = {**_MIN, "related_identifiers": [
        "not-a-mapping", 42,
        {"identifier": "10.1/x", "identifier_type": "DOI", "relation": "Cites", "custodian": None}]}
    assert bp._related_identifiers_of(y) == [
        {"identifier": "10.1/x", "identifier_type": "DOI", "relation": "Cites", "custodian": None}]


def test_smeta_carries_related_identifiers():
    sm = bp.survey_meta_from_yaml(_RI_SURVEY)
    assert sm["related_identifiers"] == [{"identifier": "10.25914/sv5r-zw68", "identifier_type": "DOI",
                                          "relation": "IsDerivedFrom", "custodian": "NCI"}]


def test_smeta_related_identifiers_empty_when_absent():
    sm = bp.survey_meta_from_yaml(_MIN)
    assert sm["related_identifiers"] == []


# --- §2b: identifiers.instrument_pid (survey/platform-level; distinct from per-instrument pid) -----

def test_instrument_pid_of_verbatim():
    y = {**_MIN, "identifiers": {"instrument_pid": "10.82388/bt6orvhn"}}
    assert bp._instrument_pid_of(y) == "10.82388/bt6orvhn"


def test_instrument_pid_of_none_when_absent():
    assert bp._instrument_pid_of(_MIN) is None
    assert bp._instrument_pid_of({**_MIN, "identifiers": {"dataset_doi": "10.1/x"}}) is None


def test_smeta_carries_instrument_pid():
    sm = bp.survey_meta_from_yaml({**_MIN, "identifiers": {"instrument_pid": "10.82388/bt6orvhn"}})
    assert sm["instrument_pid"] == "10.82388/bt6orvhn"


def test_smeta_instrument_pid_none_when_absent():
    sm = bp.survey_meta_from_yaml(_MIN)
    assert sm["instrument_pid"] is None


def test_smeta_json_serializable_with_related_identifiers():
    import json
    json.dumps(bp.survey_meta_from_yaml(_RI_SURVEY))


# --- mtcat federation: related_identifiers present-only (byte-identical when absent) ---------------

def _stations(label):
    return [(Path("a.edi"), {"survey": label, "ausmt_id": "au.x.A1", "id": "A1",
                             "lat": -30.1, "lon": 137.0, "type": "BBMT"})]


def test_mtcat_emits_related_identifiers_when_present():
    meta = {"S": bp.survey_meta_from_yaml(_RI_SURVEY)}
    doc = bp.mtcat_document(meta, _stations("S"), generated_at="2026-01-01T00:00:00Z")
    s = doc["surveys"][0]
    assert s["related_identifiers"] == [{"identifier": "10.25914/sv5r-zw68", "identifier_type": "DOI",
                                         "relation": "IsDerivedFrom", "custodian": "NCI"}], s


def test_mtcat_carries_identifies_when_present():
    """mtcat federates the SMETA related_identifiers verbatim, so D-L1's identifies rides along."""
    y = {**_MIN, "related_identifiers": [
        {"identifier": "10.25914/sv5r-zw68", "identifies": "raw_packed", "identifier_type": "DOI",
         "relation": "IsDerivedFrom", "custodian": "NCI"}]}
    meta = {"S": bp.survey_meta_from_yaml(y)}
    doc = bp.mtcat_document(meta, _stations("S"), generated_at="2026-01-01T00:00:00Z")
    assert doc["surveys"][0]["related_identifiers"][0]["identifies"] == "raw_packed"


def test_mtcat_omits_related_identifiers_when_absent():
    """Byte-identical posture: a survey with no typed relations gets no related_identifiers key in mtcat
    (matches the sources/attribution/changes present-only blocks)."""
    meta = {"S": bp.survey_meta_from_yaml(_MIN)}
    doc = bp.mtcat_document(meta, _stations("S"), generated_at="2026-01-01T00:00:00Z")
    assert "related_identifiers" not in doc["surveys"][0]
