"""Station metadata 0.1: the schema DESCRIBES the promoted station.json, and CONSTRAINS it.

The third public contract, data/products/<slug>/<station>/station.json, ships with the 0.1-draft artifact AusMT_2026/schemas-draft/ausmt-station.schema.json copied byte-for-byte to
engine/schema/ausmt-station.schema.json (the MTCAT 2.0 / survey-metadata pattern). This module is the
schema gate, the sibling of test_survey_metadata_schema_v01.py:

  1. the artifact's own shape: legal draft-07, the two-branch oneOf, both branch required sets, the
     versioned $id, the withheld branch closed-world (top level AND its nested blocks) and the full
     branch open with `withheld` forbidden outright;
  2. three committed fixtures that must VALIDATE with format checking on: the live open station and
     the live withheld stub, each seeded from the suite's own live fixture plus the three
     promotion markers, and the suite's T15 synthetic full record (the runs[]/resources[]
     shape no live station instantiates yet);
  3. the RED proof: the T12b-T19b, T28a-d, T29a-e and T34d rejections, each differing from a
     PASSING document by exactly the field under test.

The in-tree artifact is a byte copy, so running the suite's own checks against it is what
proves the copy is the design rather than a lookalike: every rejection below is the frozen
suite's case, seeded from the frozen suite's documents.

STACK-FREE at module level: the schema gate runs on a machine with no ingest stack. Validation uses
the REAL draft-07 validator with format checking enabled (rfc3339-validator is a declared dev
dependency so the date-time RED cases can never pass vacuously).
"""
import copy
import json
import re
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCHEMA_FILE = ROOT / "schema" / "ausmt-station.schema.json"
SCHEMA = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
FIX = HERE / "fixtures" / "station"
FIXTURE_NAMES = ("promoted-a23", "promoted-vul24-13", "t15-synthetic-full")
SCHEMA_VERSION = re.match(r"^AusMT Station Metadata (\d+\.\d+)", SCHEMA["title"]).group(1)
WITHHELD_BRANCH, FULL_BRANCH = SCHEMA["oneOf"][0], SCHEMA["oneOf"][1]
MARKERS = ("schema", "version", "survey_id")


def fixture(name):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def validator():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft7Validator.check_schema(SCHEMA)   # the schema itself must be legal draft-07
    fc = jsonschema.FormatChecker()
    assert "date-time" in fc.checkers, (
        "format checking for date-time is not active (install rfc3339-validator, a declared dev "
        "dependency); without it the run time_period RED cases pass vacuously")
    return jsonschema.Draft7Validator(SCHEMA, format_checker=fc)


def errors(doc):
    return [f"{'/'.join(str(p) for p in e.absolute_path)}: {e.message}" for e in validator().iter_errors(doc)]


# ---------------------------------------------------------------- 1. the artifact's own shape

def test_schema_is_legal_draft7_with_two_branches_and_the_ratified_required_sets():
    validator()
    assert SCHEMA["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert len(SCHEMA["oneOf"]) == 2, "the record has exactly two formal branches (withheld, full)"
    assert WITHHELD_BRANCH["title"] == "withheld station record"
    assert FULL_BRANCH["title"] == "full station record"
    assert WITHHELD_BRANCH["required"] == ["schema", "version", "ausmt_id", "station", "survey",
                                           "survey_id", "withheld"]
    assert FULL_BRANCH["required"] == ["schema", "version", "ausmt_id", "station", "survey", "survey_id"]
    for branch in (WITHHELD_BRANCH, FULL_BRANCH):
        assert branch["properties"]["schema"] == {"const": "ausmt-station"}


def test_schema_id_is_the_versioned_immutable_uri_and_the_title_displays_the_same_version():
    assert SCHEMA["$id"] == (f"https://ausmt.auscope.org.au/data/schemas/ausmt-station/"
                             f"{SCHEMA_VERSION}/ausmt-station.schema.json")
    assert SCHEMA["title"].startswith(f"AusMT Station Metadata {SCHEMA_VERSION}")


def test_the_withheld_branch_is_closed_world_top_level_and_nested():
    """The one deliberate exception to the open-schema rule: an open withheld record would let
    coordinates, runs or instrument identity ride in under unbanned key names."""
    assert WITHHELD_BRANCH["additionalProperties"] is False
    for block in ("access", "distribution"):
        assert WITHHELD_BRANCH["properties"][block]["additionalProperties"] is False, (
            f"the withheld branch's nested {block} block must be closed too")
    assert WITHHELD_BRANCH["properties"]["withheld"] == {"const": True}
    assert WITHHELD_BRANCH["properties"]["access"]["properties"]["served"] == {"const": False}
    assert WITHHELD_BRANCH["properties"]["distribution"]["properties"]["edi_available"] == {"const": False}
    assert WITHHELD_BRANCH["properties"]["distribution"]["properties"]["edi_path"] == {"enum": [None]}


def test_the_full_branch_is_open_and_forbids_the_withheld_marker_outright():
    """The 1.2-era keys stay permitted through the open schema; `withheld` is a false property schema,
    so a full record carrying it validates under NEITHER branch."""
    assert FULL_BRANCH["additionalProperties"] is True
    assert FULL_BRANCH["properties"]["withheld"] is False


def test_the_embargo_date_is_string_or_null_but_conditional_on_the_level():
    """The null is metadata_only's alone; an embargoed level still requires a real date, so a
    dropped or nulled date on the one live embargoed survey is rejected rather than accepted."""
    access = WITHHELD_BRANCH["properties"]["access"]
    assert access["properties"]["embargo_until"]["type"] == ["string", "null"]
    assert access["if"]["properties"]["level"] == {"const": "embargoed"}
    assert access["then"]["required"] == ["embargo_until"]
    assert access["then"]["properties"]["embargo_until"] == {"type": "string", "minLength": 1}


def test_the_station_vocabularies_are_closed():
    """Processing_level and packaging are closed on the tokens the scope declares, so an
    NCI-native or legacy-mtcat token cannot be inherited into the station vocabulary."""
    resource = SCHEMA["definitions"]["resource"]["properties"]
    assert resource["processing_level"]["enum"] == ["raw", "level0", "level1", "level2", "level3"]
    assert resource["packaging"]["enum"] == ["packed_archive"]
    assert resource["kind"]["enum"] == ["time_series", "transfer_function", "archive", "metadata", "plot"]
    assert resource["provenance_role"]["enum"] == ["source", "derived"]
    assert resource["representation_role"]["enum"] == ["original", "alternate", "archival_copy"]


# ---------------------------------------------------------------- 2. the fixtures validate

@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixture_validates_with_format_checking(name):
    doc = fixture(name)
    assert not errors(doc), errors(doc)
    assert doc["schema"] == "ausmt-station" and doc["version"] == SCHEMA_VERSION
    assert all(m in doc for m in MARKERS), f"{name}: the three promotion markers are required on both branches"


def test_t11_the_live_open_station_validates_on_the_full_branch_with_its_frozen_nulls():
    """The live record's legitimate nulls (remote_site, coordinate_qc, the rotation sources, the
    convention detail, the emeas azimuths) are the reason the survey-metadata module's document-wide
    zero-null rule cannot be imported here: they are frozen bytes on a valid document."""
    doc = fixture("promoted-a23")
    assert not errors(doc), errors(doc)
    assert "withheld" not in doc and doc["survey_id"] == "auslamp-nsw-2016-21"
    assert doc["processing"]["remote_site"] is None and doc["coordinate_qc"] is None
    assert doc["frame"]["convention_check"]["detail"] is None
    assert doc["frame"]["evidence"]["emeas_azimuths"] == {"ex": None, "ey": None}
    assert doc["frame"]["evidence"]["rotspec"] is None
    assert doc["frame"]["impedance_rotation_deg_source"] is None
    assert doc["frame"]["tipper_rotation_deg_source"] is None


def test_t12_the_live_withheld_stub_validates_on_the_withheld_branch():
    """The stub carries the nine frozen keys plus the three markers and nothing else: any twelfth
    key name would be rejected by the closed world, which is what the rejections below prove."""
    doc = fixture("promoted-vul24-13")
    assert not errors(doc), errors(doc)
    assert doc["withheld"] is True and doc["survey_id"] == "vulcan-2024-25"
    assert set(doc) == {"ausmt_id", "station", "survey", "country", "organisation", "access",
                        "distribution", "withheld", "note"} | set(MARKERS)


def test_t15_the_synthetic_full_record_carries_the_runs_and_resources_shape():
    """No live station instantiates runs[]/resources[] yet, so the canonical model's own shape is
    pinned on the suite's synthetic record: a multi-run MTH5 that both represents and derives
    from its runs, an electric channel with electrodes and contact resistance, a magnetic one with a
    sensor."""
    doc = fixture("t15-synthetic-full")
    assert not errors(doc), errors(doc)
    assert [r["id"] for r in doc["runs"]] == ["001", "002"]
    assert doc["resources"][0]["represents_runs"] == doc["resources"][0]["derived_from_runs"] == ["001", "002"]


# ---------------------------------------------------------------- 3. the RED proof

def _rejected(base, mutate, why):
    doc = copy.deepcopy(base)
    mutate(doc)
    assert errors(doc), f"the schema accepted a document that must be REJECTED: {why}"


@pytest.mark.parametrize("why,mutate", [
    ("T12c EMBARGOED stub with a null embargo_until (the null is metadata_only's alone)",
     lambda d: d["access"].__setitem__("embargo_until", None)),
    ("T12d EMBARGOED stub with the embargo date DROPPED (fail-closed on the live embargoed survey)",
     lambda d: d["access"].pop("embargo_until")),
    ("T13 withheld stub with injected runs[]", lambda d: d.__setitem__("runs", [{"id": "001"}])),
    ("T14 withheld stub with injected coordinates",
     lambda d: d.__setitem__("location", {"lat": -31.0, "lon": 140.0})),
    ("T28a withheld + bare latitude/longitude keys",
     lambda d: d.update({"latitude": -31.0, "longitude": 140.0})),
    ("T28b withheld + coordinates nested in access",
     lambda d: d["access"].__setitem__("coords", [-31.0, 140.0])),
    ("T28c withheld + runs under a renamed key",
     lambda d: d.__setitem__("acquisitions", [{"id": "001", "data_logger": {"serial_number": "1234"}}])),
    ("T28d withheld + live edi_path (distribution closed and pinned)",
     lambda d: d["distribution"].__setitem__("edi_path", "edi/vulcan-2024-25/Vul24-13.edi")),
    ("the withheld marker set to false", lambda d: d.__setitem__("withheld", False)),
    ("a marker dropped from the withheld branch", lambda d: d.pop("survey_id")),
])
def test_withheld_branch_rejection(why, mutate):
    _rejected(fixture("promoted-vul24-13"), mutate, why)


def test_t12b_a_metadata_only_stub_with_a_null_embargo_until_validates():
    """The metadata_only stub's emitted bytes carry the key with a null value, and they must
    validate as emitted; only the embargoed level forces a real date."""
    doc = fixture("promoted-vul24-13")
    doc["access"]["level"] = "metadata_only"
    doc["access"]["embargo_until"] = None
    assert not errors(doc), errors(doc)


@pytest.mark.parametrize("why,mutate", [
    ("T16 electric channel carrying sensor",
     lambda d: d["runs"][0]["channels"][1].__setitem__("sensor", {"model": "LEMI-120"})),
    ("T17 magnetic channel carrying electrode",
     lambda d: d["runs"][0]["channels"][0].__setitem__("positive", {"model": "Pb-PbCl2"})),
    ("T18 unit_value with value but no unit",
     lambda d: d["runs"][0]["channels"][1].__setitem__(
         "contact_resistance", {"source_value": "1.82 kilo-ohms", "value": 1820})),
    ("T19 resource without stable id", lambda d: d["resources"][0].pop("id")),
    ("T19a NCI-native processing_level token (crosswalked, never inherited)",
     lambda d: d["resources"][0].__setitem__("processing_level", "level_1")),
    ("T19b legacy mtcat identifies token as packaging",
     lambda d: d["resources"][0].__setitem__("packaging", "raw_packed")),
    ("T29a Phoenix e1 channel carrying sensor (pattern guard)",
     lambda d: d["runs"][0]["channels"].append({"component": "e1", "sensor": {"model": "LEMI-120"}})),
    ("T29b mixed-case Ex carrying sensor (case-insensitive guard)",
     lambda d: d["runs"][0]["channels"].append({"component": "Ex", "sensor": {"model": "LEMI-120"}})),
    ("T29c channel rate without run nominal rate",
     lambda d: d["runs"].__setitem__(1, {"id": "002", "channels": [{"component": "hx", "sample_rate_hz": 10}]})),
    ("T29d negative contact resistance",
     lambda d: d["runs"][0]["channels"][1].__setitem__(
         "contact_resistance", {"source_value": "-5 ohms", "value": -5, "unit": "ohm"})),
    ("T29e empty-string unit",
     lambda d: d["runs"][0]["channels"][1].__setitem__(
         "contact_resistance", {"source_value": "1.82 kilo-ohms", "value": 1820, "unit": ""})),
    ("T34d derived resource claiming representation_role original",
     lambda d: d["resources"][2].__setitem__("representation_role", "original")),
    ("a run without an id", lambda d: d["runs"][1].pop("id")),
    ("a resource without a kind", lambda d: d["resources"][1].pop("kind")),
    ("a run time_period end that is not a date-time",
     lambda d: d["runs"][0]["time_period"].__setitem__("end", "some time in May")),
    ("the withheld marker on a full record (schema-forbidden outright)",
     lambda d: d.__setitem__("withheld", False)),
])
def test_full_branch_rejection(why, mutate):
    _rejected(fixture("t15-synthetic-full"), mutate, why)


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_the_mutation_sets_differ_from_a_passing_document_by_exactly_the_field_under_test(name):
    """Non-vacuity: every base document above VALIDATES, so each rejection is caused by its mutation."""
    assert not errors(fixture(name))
