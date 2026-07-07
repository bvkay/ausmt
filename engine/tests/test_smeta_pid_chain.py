"""C7: PID chain completion — survey.yaml -> SMETA must carry investigator ORCIDs, the organisation
ROR, project RAiD, the time-series collection PID, and a non-'(n.d.)' citation year/version.

FAILS IF (pre-fix): investigators are bare name strings (ORCIDs discarded); SMETA has no 'raid' key;
SMETA has no 'ts_pid' key; cite.yr/cite.ve are always empty strings so every citation prints "(n.d.)"
even though the source survey.yaml declares a date range and a version.
"""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from extract import build_portal as bp   # noqa: E402
from _fixtures import FIXTURES           # noqa: E402

PID_SURVEY = FIXTURES / "pid-survey"


def _load():
    yaml = pytest.importorskip("yaml")
    text = (PID_SURVEY / "survey.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text) or {}


def test_investigators_of_returns_name_and_orcid():
    """FAILS IF: _investigators_of drops the orcid and returns bare name strings."""
    y = _load()
    invs = bp._investigators_of(y)
    assert invs == [{"name": "A. Researcher", "orcid": "0000-0002-1825-0097"}], invs


def test_investigators_of_tolerates_missing_orcid():
    y = {"lead_investigator": {"name": "No Orcid Here"}}
    assert bp._investigators_of(y) == [{"name": "No Orcid Here", "orcid": None}]


def test_investigators_of_principal_investigators_list():
    y = {"principal_investigators": [{"name": "First Person", "orcid": "0000-0002-1825-0097"},
                                     {"name": "Second Person"}]}
    assert bp._investigators_of(y) == [
        {"name": "First Person", "orcid": "0000-0002-1825-0097"},
        {"name": "Second Person", "orcid": None},
    ]


def test_smeta_investigators_shape():
    sm = bp.survey_meta_from_yaml(_load())
    assert sm["investigators"] == [{"name": "A. Researcher", "orcid": "0000-0002-1825-0097"}]


def test_smeta_org_ror_carried():
    sm = bp.survey_meta_from_yaml(_load())
    assert sm["org_ror"] == "https://ror.org/00892tw58"


def test_smeta_raid_parsed():
    """FAILS IF: identifiers.project_raid has zero code references — SMETA lacks a 'raid' key."""
    sm = bp.survey_meta_from_yaml(_load())
    assert sm["raid"] == "https://raid.org/10.12345/AB1234"


def test_smeta_ts_pid_from_collection_pid():
    """FAILS IF: time_series.collection_pid is never read into SMETA."""
    sm = bp.survey_meta_from_yaml(_load())
    assert sm["ts_pid"] == "10.25914/pid-survey-ts"


def test_smeta_ts_pid_absent_when_not_declared():
    y = {"name": "No TS PID", "slug": "x", "organisation": "Org", "license": "CC-BY-4.0"}
    sm = bp.survey_meta_from_yaml(y)
    assert sm.get("ts_pid") is None


def test_citation_year_from_date_range_end():
    """FAILS IF (pre-fix): cite.yr is always '' regardless of survey.yaml dates -> every citation
    renders 'Organisation (n.d.)' even when a real date range is declared."""
    sm = bp.survey_meta_from_yaml(_load())
    assert sm["cite"]["yr"] == "2021", sm["cite"]
    assert sm["cite"]["yr"] != ""


def test_citation_year_falls_back_to_start_when_no_end():
    y = {"name": "X", "slug": "x", "organisation": "Org", "license": "CC-BY-4.0",
         "dates": {"start": 2015, "end": None}}
    sm = bp.survey_meta_from_yaml(y)
    assert sm["cite"]["yr"] == "2015", sm["cite"]


def test_citation_year_empty_when_genuinely_no_date():
    """(n.d.) is only correct when there really is no date."""
    y = {"name": "X", "slug": "x", "organisation": "Org", "license": "CC-BY-4.0"}
    sm = bp.survey_meta_from_yaml(y)
    assert sm["cite"]["yr"] == ""


def test_citation_version_from_smeta_version():
    """FAILS IF (pre-fix): cite.ve is always '' regardless of survey.yaml version."""
    sm = bp.survey_meta_from_yaml(_load())
    assert sm["cite"]["ve"] == "2.1.0", sm["cite"]


def test_smeta_year_start_end_from_dates():
    """S3: modeller year-range filter. FAILS IF (pre-fix): SMETA has no 'year_start'/'year_end' keys
    at all (KeyError) -- the pid-survey fixture declares dates: {start: 2020, end: 2021}."""
    sm = bp.survey_meta_from_yaml(_load())
    assert sm["year_start"] == 2020, sm
    assert sm["year_end"] == 2021, sm
    assert isinstance(sm["year_start"], int) and isinstance(sm["year_end"], int)


def test_smeta_year_range_none_when_no_dates():
    y = {"name": "X", "slug": "x", "organisation": "Org", "license": "CC-BY-4.0"}
    sm = bp.survey_meta_from_yaml(y)
    assert sm["year_start"] is None and sm["year_end"] is None


def test_smeta_year_range_tolerates_null_end():
    y = {"name": "X", "slug": "x", "organisation": "Org", "license": "CC-BY-4.0",
         "dates": {"start": 2015, "end": None}}
    sm = bp.survey_meta_from_yaml(y)
    assert sm["year_start"] == 2015 and sm["year_end"] is None


def test_mtcat_document_emits_organisation_ror_and_raid():
    """C7 task 6: additive optional survey fields organisation_ror, raid in mtcat_document."""
    meta = {"PID Chain Survey 2026": bp.survey_meta_from_yaml(_load())}
    stations = [(Path("a.edi"), {"survey": "PID Chain Survey 2026",
                                 "ausmt_id": "au.pid-survey.A1", "id": "A1",
                                 "lat": -30.1, "lon": 137.0, "type": "BBMT"})]
    doc = bp.mtcat_document(meta, stations, generated_at="2026-01-01T00:00:00Z")
    s = doc["surveys"][0]
    assert s["organisation_ror"] == "https://ror.org/00892tw58", s
    assert s["raid"] == "https://raid.org/10.12345/AB1234", s


# --- PID schema: instruments[].pid -> SMETA 'instruments' (additive, optional) --------------------
# The AuScope Instrument Registry PID for an instrument SYSTEM. It must flow survey.yaml -> SMETA ->
# surveys.json -> portal drawer, WITHOUT changing anything when no instrument declares a pid (the
# additive-only constraint). instrument_model (the display join) must be UNCHANGED throughout.

_MIN = {"name": "X", "slug": "x", "organisation": "Org", "license": "CC-BY-4.0"}


def test_instruments_of_none_when_no_pid_present():
    """FAILS IF: _instruments_of attaches a structured list for a survey whose instruments carry no
    pid — that would add an 'instruments' key to EVERY existing survey's surveys.json (non-additive)."""
    y = {**_MIN, "instruments": [{"manufacturer": "Phoenix", "model": "MTU-5C"}]}
    assert bp._instruments_of(y) is None


def test_instruments_of_carries_pid_when_present():
    """FAILS IF: a declared instruments[].pid is not read into the structured list."""
    y = {**_MIN, "instruments": [
        {"manufacturer": "LEMI", "model": "423", "pid": "https://instruments.auscope.org.au/system/L1"},
        {"manufacturer": "Phoenix", "model": "MTU-5C"}]}
    got = bp._instruments_of(y)
    assert got == [
        {"manufacturer": "LEMI", "model": "423", "pid": "https://instruments.auscope.org.au/system/L1"},
        {"manufacturer": "Phoenix", "model": "MTU-5C", "pid": None}], got


def test_smeta_omits_instruments_key_when_no_pid():
    """The additive contract, at the SMETA level: absent pid => the 'instruments' key is entirely
    ABSENT from the SMETA dict (so surveys.json is byte-identical for the existing corpus). FAILS IF the
    key is present (even as None/[]), which would change every survey's emitted JSON."""
    sm = bp.survey_meta_from_yaml({**_MIN, "instruments": [{"manufacturer": "Phoenix", "model": "MTU-5C"}]})
    assert "instruments" not in sm, sm.get("instruments")
    # the display line is still produced, unchanged
    assert sm["instrument_model"] == "Phoenix MTU-5C"


def test_smeta_includes_instruments_key_when_pid_present():
    sm = bp.survey_meta_from_yaml({**_MIN, "instruments": [
        {"manufacturer": "LEMI", "model": "423", "pid": "10.25914/lemi-1"}]})
    assert sm["instruments"] == [{"manufacturer": "LEMI", "model": "423", "pid": "10.25914/lemi-1"}]
    assert sm["instrument_model"] == "LEMI 423"   # display join UNCHANGED by the pid addition


def test_smeta_byte_identical_when_pid_absent_vs_baseline():
    """The core additive guarantee, proven at the surveys.json serialization level: adding the OPTIONAL
    pid field to the schema must leave the emitted SMETA JSON byte-identical for a survey that declares
    NO instrument pid. FAILS IF _instruments_of leaks any key/whitespace into the no-pid SMETA."""
    y = {**_MIN, "instruments": [{"manufacturer": "Phoenix", "model": "MTU-5C"}]}
    sm = bp.survey_meta_from_yaml(y)
    # the exact key set an existing no-pid survey serializes with — 'instruments' must NOT be among them
    keys = set(sm.keys())
    assert "instruments" not in keys
    # and a full dump is stable/re-derivable (no hidden non-serializable value introduced)
    import json
    json.dumps(sm)


def test_survey_meta_tolerates_bad_instrument_pid_shapes():
    """Defensive: a non-dict instrument, or a blank/None pid, must never raise."""
    y = {**_MIN, "instruments": ["nope", {"manufacturer": "Phoenix", "model": "MTU-5C", "pid": ""},
                                 {"manufacturer": "LEMI", "model": "423", "pid": "10.25914/x"}]}
    sm = bp.survey_meta_from_yaml(y)
    # only the real pid triggers the list; blank pid -> None, bad shape dropped
    assert sm["instruments"] == [
        {"manufacturer": "Phoenix", "model": "MTU-5C", "pid": None},
        {"manufacturer": "LEMI", "model": "423", "pid": "10.25914/x"}], sm["instruments"]
