"""Survey metadata 0.1: the ratified schema DESCRIBES what the build serves, and CONSTRAINS it.

The second public contract, data/products/<survey_id>/survey-metadata.json, ships with the ratified
0.1-draft artifact AusMT_2026/schemas-draft/ausmt-survey-metadata.schema.json copied byte-for-byte to
engine/schema/ausmt-survey-metadata.schema.json (the MTCAT 2.0 core pattern). This module is the
schema gate, the sibling of test_mtcat_schema_v20.py:

  1. the artifact's own shape: legal draft-07, the required set {schema, version, survey_id, title},
     every array property minItems 1 (the zero-empty posture is enforced by the schema, not only by
     the emitter), the versioned $id (D3), the open top level;
  2. four committed fixtures that must VALIDATE with format checking on: the ratified suite's T20
     document verbatim, a synthetic Case B release, a synthetic multi-activity survey and a synthetic
     no-identifier survey cited by source-provided text (the matrix rows the real corpus cannot
     instantiate today);
  3. the RED proof: the ratified T21-T23 rejections plus a mutation set, one mutation per constraint,
     each differing from a PASSING document by exactly the field under test;
  4. the T25 reference check (citation.preferred_identifier designated in identifiers[]) and the
     zero-null / zero-empty scanner the emission and invariant suites reuse.

STACK-FREE at module level: the schema gate runs on a machine with no ingest stack. Validation uses
the REAL draft-07 validator with format checking enabled (rfc3339-validator is a declared dev
dependency so the date / date-time RED cases can never pass vacuously).
"""
import copy
import json
import re
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCHEMA_FILE = ROOT / "schema" / "ausmt-survey-metadata.schema.json"
SCHEMA = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
FIX = HERE / "fixtures" / "survey-metadata"
FIXTURE_NAMES = ("t20-synthetic", "synthetic-case-b", "synthetic-multi-activity",
                 "synthetic-no-identifier-text")
SCHEMA_VERSION = re.match(r"^AusMT Survey Metadata (\d+\.\d+)", SCHEMA["title"]).group(1)


def fixture(name):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def validator():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft7Validator.check_schema(SCHEMA)   # the schema itself must be legal draft-07
    fc = jsonschema.FormatChecker()
    assert "date-time" in fc.checkers and "date" in fc.checkers, (
        "format checking for date / date-time is not active (install rfc3339-validator, a declared "
        "dev dependency); without it the issued / embargo_until / generated RED cases pass vacuously")
    return jsonschema.Draft7Validator(SCHEMA, format_checker=fc)


def errors(doc):
    return [f"{'/'.join(str(p) for p in e.absolute_path)}: {e.message}" for e in validator().iter_errors(doc)]


def scan_nulls_and_empties(doc):
    """The zero-null / zero-empty scan for ONE survey-metadata document: every null anywhere and every
    empty array/object anywhere, as JSON-pointer-ish paths. The document defines no null at all (unlike
    mtcat's paired station coordinates), so the scan has no exemptions."""
    nulls, empties = [], []

    def walk(node, path):
        if isinstance(node, dict):
            if not node:
                empties.append(path)
            for k, v in node.items():
                if v is None:
                    nulls.append(f"{path}.{k}")
                else:
                    walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            if not node:
                empties.append(path)
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(doc, "$")
    return nulls, empties


def preferred_identifier_designated(doc):
    """T25 reference check: when citation.preferred_identifier is present, an EQUAL {scheme, identifier}
    row exists in identifiers[] (the designated identifiers OF this dataset/release)."""
    pref = (doc.get("citation") or {}).get("preferred_identifier")
    if pref is None:
        return True
    return any(i.get("scheme") == pref.get("scheme") and i.get("identifier") == pref.get("identifier")
               for i in doc.get("identifiers", []))


# ---------------------------------------------------------------- 1. the artifact's own shape

def test_schema_is_legal_draft7_with_the_ratified_required_set():
    validator()
    assert SCHEMA["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert SCHEMA["required"] == ["schema", "version", "survey_id", "title"]
    assert SCHEMA["additionalProperties"] is True, "the top level is open (additive 0.x -> 1.x)"
    assert SCHEMA["properties"]["schema"] == {"const": "ausmt-survey-metadata"}


def test_schema_id_is_the_versioned_immutable_uri_and_the_title_displays_the_same_version():
    assert SCHEMA["$id"] == (f"https://ausmt.auscope.org.au/data/schemas/ausmt-survey-metadata/"
                             f"{SCHEMA_VERSION}/ausmt-survey-metadata.schema.json")
    assert SCHEMA["title"].startswith(f"AusMT Survey Metadata {SCHEMA_VERSION}")


def test_every_array_property_requires_at_least_one_item():
    """The zero-empty posture is a SCHEMA constraint: an emitter that wrote [] for any array would
    fail validation, not merely a scan."""
    props = SCHEMA["properties"]
    arrays = {k for k, v in props.items() if v.get("type") == "array"}
    assert arrays == {"identifiers", "activities", "subjects", "creators", "contributors",
                      "organisations", "funders", "acknowledgements", "relationships"}
    for k in arrays:
        assert props[k].get("minItems") == 1, f"{k} must carry minItems 1"
    assert props["citation"]["properties"]["additional"]["minItems"] == 1
    assert props["organisations"]["items"]["properties"]["roles"]["minItems"] == 1


def test_the_date_annotations_are_present_so_format_checking_has_teeth():
    assert SCHEMA["properties"]["dates"]["properties"]["issued"]["format"] == "date"
    assert SCHEMA["properties"]["rights"]["properties"]["embargo_until"]["format"] == "date"
    assert SCHEMA["properties"]["provenance"]["properties"]["generated"]["format"] == "date-time"


# ---------------------------------------------------------------- 2. the fixtures validate

@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixture_validates_with_format_checking_and_scans_clean(name):
    doc = fixture(name)
    assert not errors(doc), errors(doc)
    nulls, empties = scan_nulls_and_empties(doc)
    assert not nulls and not empties, (nulls, empties)
    assert doc["schema"] == "ausmt-survey-metadata" and doc["version"] == SCHEMA_VERSION
    assert preferred_identifier_designated(doc), f"{name}: T25 must hold on a committed fixture"


def test_t20_fixture_is_the_ratified_suite_document_verbatim():
    """The committed T20 document is the ratified suite's `svm` (run-fixture-suite.py T20); the
    load-bearing values are pinned so a silent edit to the fixture is a visible one."""
    doc = fixture("t20-synthetic")
    assert doc["survey_id"] == "example-basin-2024"
    assert doc["identifiers"] == [{"scheme": "URL",
                                   "identifier": "https://repository.example.org/releases/example-basin-2024"}]
    assert doc["activities"] == [{"identifier": "https://raid.org/10.99999/example", "scheme": "RAiD"}]
    assert doc["organisations"][0]["primary_custodian"] is True
    assert doc["citation"]["additional"][0]["reason"] == "repository_product"
    assert doc["acknowledgements"][0]["type"] == "access_provider"
    assert doc["relationships"] == [{"identifier": "10.99999/source-release", "identifier_type": "DOI",
                                     "relation": "IsDerivedFrom"}]


def test_case_b_fixture_carries_its_own_identifier_and_sources_as_relationships():
    """Case B: identifiers[] holds the AusMT release's OWN identifier; every source record is a
    relationship, never an identifier OF this dataset; the preferred identifier is the own one."""
    doc = fixture("synthetic-case-b")
    own = {(i["scheme"], i["identifier"]) for i in doc["identifiers"]}
    rel = {(r["identifier_type"], r["identifier"]) for r in doc["relationships"]}
    assert own and rel and not (own & rel), "an identifier cannot be both OF the dataset and a relationship"
    assert (doc["citation"]["preferred_identifier"]["scheme"],
            doc["citation"]["preferred_identifier"]["identifier"]) in own
    assert doc["dataset_version"], "a Case B release carries the AusMT release's own version"


def test_multi_activity_fixture_holds_two_activities():
    doc = fixture("synthetic-multi-activity")
    assert len(doc["activities"]) == 2
    assert {a["scheme"] for a in doc["activities"]} == {"RAiD"}


def test_no_identifier_fixture_is_citable_by_source_provided_text_alone():
    doc = fixture("synthetic-no-identifier-text")
    assert "identifiers" not in doc and "relationships" not in doc
    assert doc["citation"]["text_source"] == "source_provided" and doc["citation"]["preferred_text"]
    assert "preferred_identifier" not in doc["citation"]


# ---------------------------------------------------------------- 3. the RED proof

def _base():
    return fixture("t20-synthetic")


def _rejected(mutate, why):
    doc = _base()
    mutate(doc)
    assert errors(doc), f"the schema accepted a document that must be REJECTED: {why}"


def test_t21_citation_additional_without_reason_rejected():
    _rejected(lambda d: d["citation"]["additional"][0].pop("reason"), "T21 additional row without reason")


def test_t22_organisation_row_without_roles_rejected():
    _rejected(lambda d: d["organisations"][0].pop("roles"), "T22 organisation row without roles")


def test_t23_acknowledgement_without_text_rejected():
    _rejected(lambda d: d["acknowledgements"][0].pop("text"), "T23 acknowledgement without text")


@pytest.mark.parametrize("why,mutate", [
    ("schema const wrong", lambda d: d.__setitem__("schema", "mtcat")),
    ("version not a string", lambda d: d.__setitem__("version", 0.1)),
    ("survey_id missing", lambda d: d.pop("survey_id")),
    ("survey_id empty", lambda d: d.__setitem__("survey_id", "")),
    ("title missing", lambda d: d.pop("title")),
    ("title empty", lambda d: d.__setitem__("title", "")),
    ("identifiers empty array", lambda d: d.__setitem__("identifiers", [])),
    ("identifier row without scheme", lambda d: d["identifiers"][0].pop("scheme")),
    ("identifier row without identifier", lambda d: d["identifiers"][0].pop("identifier")),
    ("identifier row empty identifier", lambda d: d["identifiers"][0].__setitem__("identifier", "")),
    ("activities empty array", lambda d: d.__setitem__("activities", [])),
    ("activity row without scheme", lambda d: d["activities"][0].pop("scheme")),
    ("activity row without identifier", lambda d: d["activities"][0].pop("identifier")),
    ("subjects empty array", lambda d: d.__setitem__("subjects", [])),
    ("subject row without scheme", lambda d: d["subjects"][0].pop("scheme")),
    ("subject row without code", lambda d: d["subjects"][0].pop("code")),
    ("creators empty array", lambda d: d.__setitem__("creators", [])),
    ("creator row without name", lambda d: d["creators"][0].pop("name")),
    ("creator name_type out of enum", lambda d: d["creators"][0].__setitem__("name_type", "group")),
    ("contributors empty array", lambda d: d.__setitem__("contributors", [])),
    ("contributor role out of enum", lambda d: d.__setitem__(
        "contributors", [{"name": "X", "name_type": "person", "role": "Author"}])),
    ("organisations empty array", lambda d: d.__setitem__("organisations", [])),
    ("organisation row without name", lambda d: d["organisations"][0].pop("name")),
    ("organisation roles empty", lambda d: d["organisations"][0].__setitem__("roles", [])),
    ("organisation role out of enum", lambda d: d["organisations"][0].__setitem__("roles", ["owner"])),
    ("primary_custodian false", lambda d: d["organisations"][0].__setitem__("primary_custodian", False)),
    ("funders empty array", lambda d: d.__setitem__("funders", [])),
    ("funder row without name", lambda d: d["funders"][0].pop("name")),
    ("citation.additional empty array", lambda d: d["citation"].__setitem__("additional", [])),
    ("citation.text_source out of enum", lambda d: d["citation"].__setitem__("text_source", "guessed")),
    ("preferred_identifier without identifier", lambda d: d["citation"]["preferred_identifier"].pop("identifier")),
    ("acknowledgements empty array", lambda d: d.__setitem__("acknowledgements", [])),
    ("acknowledgement empty text", lambda d: d["acknowledgements"][0].__setitem__("text", "")),
    ("relationships empty array", lambda d: d.__setitem__("relationships", [])),
    ("relationship row without identifier", lambda d: d["relationships"][0].pop("identifier")),
    ("relationship identifier_type out of enum", lambda d: d["relationships"][0].__setitem__(
        "identifier_type", "ISBN")),
    ("extent bbox missing north", lambda d: d["extent"]["bbox"].pop("north")),
    ("extent bbox west not a number", lambda d: d["extent"]["bbox"].__setitem__("west", "135.0")),
    ("dates.coverage.year_start not an integer", lambda d: d["dates"]["coverage"].__setitem__(
        "year_start", "2024")),
    ("dates.issued malformed (format date)", lambda d: d["dates"].__setitem__("issued", "2026-3-1")),
    ("dates.issued bare year (format date)", lambda d: d["dates"].__setitem__("issued", "2026")),
    ("rights.embargo_until malformed (format date)", lambda d: d["rights"].__setitem__(
        "embargo_until", "next year")),
    ("attribution.changes_made not boolean", lambda d: d["attribution"].__setitem__("changes_made", "yes")),
    ("provenance.generated malformed (format date-time)", lambda d: d["provenance"].__setitem__(
        "generated", "yesterday-ish")),
])
def test_mutation_rejected(why, mutate):
    _rejected(mutate, why)


def test_the_mutation_set_differs_from_a_passing_document_by_exactly_the_field_under_test():
    """Non-vacuity: the base document VALIDATES, so each rejection above is caused by its mutation."""
    assert not errors(_base())


def test_a_withheld_embargoed_document_validates_with_the_same_schema():
    """Policy transition keeps identity (T38c/T38d pattern): the same survey_id, an embargoed rights
    block with a dated embargo, no extent, still a valid document."""
    doc = _base()
    doc["rights"] = {"license": "CC-BY-4.0", "access": "embargoed", "embargo_until": "2027-02-01"}
    doc.pop("extent")
    assert not errors(doc), errors(doc)
    assert doc["survey_id"] == _base()["survey_id"]


# ---------------------------------------------------------------- 4. the reference checks on the guards

def test_reference_checks_actually_detect_violations():
    """Guard on the guards (the ratified suite's Txxb pattern): the scanner must catch a planted null
    and a planted empty container, and the T25 check must catch a preferred identifier that is not
    designated in identifiers[]."""
    nulls, empties = scan_nulls_and_empties({"a": None, "b": [], "c": {"d": {}}, "e": [{"f": None}]})
    assert nulls == ["$.a", "$.e[0].f"] and empties == ["$.b", "$.c.d"]
    doc = copy.deepcopy(_base())
    doc["citation"]["preferred_identifier"] = {"scheme": "DOI", "identifier": "10.99999/level1-collection"}
    assert not preferred_identifier_designated(doc), "T25 must detect a preferred identifier not in identifiers[]"
    doc["identifiers"] = []
    assert not preferred_identifier_designated(doc)
    doc.pop("citation")
    assert preferred_identifier_designated(doc), "no preferred identifier means nothing to check"
