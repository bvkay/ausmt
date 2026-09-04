"""Survey-metadata invariant suite: the cross-layer proofs over BUILT output, forever.

PERMANENT TEST STAGE (the MTCAT 2.0 rule, inherited by the second public contract): this suite runs
on every later emitter change, so a future feature can never silently break the identity chain, the
projection equivalences, the zero-null / zero-empty posture, the schema routes or the document
budget. Sources: AusMT_2026/AUSMT-METADATA-INTERFACE-CONTRACT.md (identity, citation and projection
equivalence contracts), run-fixture-suite.py (T24, T25, T31a/T31b), LANE-CONTRACT-SURVEY-METADATA
section 2 (the framing invariants).

Three layers:

  1. built layer, vendored fixtures: TWO consecutive real builds over engine/tests/fixtures (the
     vendored surveys). Proves: catalogue.json and surveys.json byte-identical across the two builds
     (the document rides a side channel and touches neither, D18); mtcat.json dict-equal minus
     portal.generated_at; every survey-metadata.json validates with format checking, carries no null
     and no empty container, is dict-equal across the two builds minus provenance.generated, and is
     under the 16 KB budget; the schema served at both routes byte-identical to the in-tree artifact
     and across builds; survey_id == directory component == mtcat surveys[].survey_id (set equality,
     T24); the doi / raid / organisation projection chains hold (T31 port); no manifest row names the
     document; the shared-definition guarantee (subject_row and the relationship core vs the mtcat
     schema, structurally).
  2. built layer, the 3-survey D8 corpus (open + embargoed + metadata_only, each curating every
     class): the same proofs on documents that carry every class, plus the C1c discipline (the
     curated extent is never station-derived, so no exact station coordinate reaches a non-served
     survey's document) and the projection chains on real emitted values (organisation, raid).
  3. the corpus arm (dev box): when AUSMT_SURVEY_METADATA_DATA names a full-corpus build output dir,
     the same scans run over the REAL corpus documents. No CI workflow has a corpus, so it skips there
     (allow-listed in ci_check_skips.py); it is the module's full-corpus proof harness.

The chain checkers are TEST-TIME assertions (the validator enforces citation designation at the
entry gates; the build refuses an undesignated preferred identifier); each is proven non-vacuous
against a planted violation, the ratified suite's Txxb pattern.
"""
import copy
import json
import os
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from test_survey_metadata_schema_v01 import (  # noqa: E402
    FIXTURE_NAMES, fixture, scan_nulls_and_empties, validator as schema_validator)

SM_SCHEMA = json.loads((ROOT / "schema" / "ausmt-survey-metadata.schema.json").read_text(encoding="utf-8"))
MTCAT_SCHEMA = json.loads((ROOT / "schema" / "mtcat.schema.json").read_text(encoding="utf-8"))
EXAMPLE = HERE / "fixtures" / "example-survey"
DOCUMENT_BUDGET_BYTES = 16 * 1024

CORPUS_DATA = os.environ.get("AUSMT_SURVEY_METADATA_DATA")
corpus_arm = pytest.mark.skipif(
    not CORPUS_DATA,
    reason="AUSMT_SURVEY_METADATA_DATA does not name a built corpus data dir")


# ---------------------------------------------------------------- reference chain implementations

def doi_chain_ok(mtcat_survey, doc):
    """When mtcat emits a doi, it is one of the survey-metadata identifiers[] (scheme
    DOI) AND the preferred citation identifier; a collection / report / file DOI planted as the mtcat
    doi is caught. Vacuously true when mtcat emits no doi."""
    doi = mtcat_survey.get("doi")
    if doi is None:
        return True
    pref = (doc.get("citation") or {}).get("preferred_identifier") or {}
    in_ids = any(i.get("scheme") == "DOI" and i.get("identifier") == doi for i in doc.get("identifiers", []))
    return in_ids and pref.get("scheme") == "DOI" and pref.get("identifier") == doi


def raid_rule_ok(mtcat_survey, doc):
    """Interface contract section 4: mtcat raid is present iff exactly one activities[] row with
    scheme RAiD exists, and equals it."""
    raids = [a.get("identifier") for a in doc.get("activities", []) if a.get("scheme") == "RAiD"]
    raid = mtcat_survey.get("raid")
    if len(raids) == 1:
        return raid == raids[0]
    return raid is None


def organisation_rule_ok(mtcat_survey, doc):
    """Interface contract section 4: where organisations[] is curated with a primary_custodian row,
    mtcat organisation equals that row's name (the deterministic projection, never 'first element')."""
    primaries = [o for o in doc.get("organisations", []) if o.get("primary_custodian") is True]
    if not primaries:
        return True
    return len(primaries) == 1 and mtcat_survey.get("organisation") == primaries[0]["name"]


def preferred_identifier_designated(doc):
    pref = (doc.get("citation") or {}).get("preferred_identifier")
    if pref is None:
        return True
    return any(i.get("scheme") == pref.get("scheme") and i.get("identifier") == pref.get("identifier")
               for i in doc.get("identifiers", []))


def document_invariants(doc, mtcat_survey=None):
    """Every reference check over one document (plus its mtcat counterpart when given); violations."""
    out = []
    if not preferred_identifier_designated(doc):
        out.append("T25: preferred_identifier not designated in identifiers[]")
    nulls, empties = scan_nulls_and_empties(doc)
    if nulls or empties:
        out.append(f"nulls {nulls[:3]} / empties {empties[:3]}")
    for k in ("formats", "distribution", "stations", "n_stations"):
        if k in doc:
            out.append(f"{k} must not be in survey-metadata (no distribution facts, no station lists)")
    if mtcat_survey is not None:
        if mtcat_survey.get("survey_id") != doc.get("survey_id"):
            out.append("survey_id differs from mtcat")
        if not doi_chain_ok(mtcat_survey, doc):
            out.append("doi chain broken")
        if not raid_rule_ok(mtcat_survey, doc):
            out.append("raid rule broken")
        if not organisation_rule_ok(mtcat_survey, doc):
            out.append("organisation projection broken")
        if mtcat_survey.get("subjects") is not None and doc.get("subjects") is not None \
                and mtcat_survey["subjects"] != doc["subjects"]:
            out.append("subjects differ from mtcat (shared definition, same source)")
    return out


def test_reference_checks_actually_detect_violations():
    """Guard on the guards: each chain checker must CATCH its planted violation (T31b pattern)."""
    doc = fixture("t20-synthetic")
    good = copy.deepcopy(doc)
    good["identifiers"].append({"scheme": "DOI", "identifier": "10.99999/example-basin-2024"})
    good["citation"]["preferred_identifier"] = {"scheme": "DOI", "identifier": "10.99999/example-basin-2024"}
    assert doi_chain_ok({"doi": "10.99999/example-basin-2024"}, good), "T31a: the intact chain holds"
    assert not doi_chain_ok({"doi": "10.99999/level1-collection"}, doc), "T31b: planted collection DOI caught"
    assert doi_chain_ok({}, doc), "no mtcat doi: vacuous"
    assert raid_rule_ok({"raid": "https://raid.org/10.99999/example"}, doc)
    assert not raid_rule_ok({}, doc), "one activity but no mtcat raid is a projection gap"
    assert not raid_rule_ok({"raid": "https://raid.org/10.99999/other"}, doc)
    multi = fixture("synthetic-multi-activity")
    assert raid_rule_ok({}, multi), "two activities: the scalar must NOT project"
    assert not raid_rule_ok({"raid": "https://raid.org/10.99999/programme"}, multi), "an arbitrary single RAiD caught"
    assert organisation_rule_ok({"organisation": "Example Geological Survey"}, doc)
    assert not organisation_rule_ok({"organisation": "Example Repository"}, doc), "'first element' / wrong custodian caught"
    assert organisation_rule_ok({"organisation": "anything"}, fixture("synthetic-no-identifier-text")) is False
    assert organisation_rule_ok({"organisation": "Example University"}, fixture("synthetic-no-identifier-text"))
    assert document_invariants(doc, {"survey_id": "example-basin-2024", "organisation": "Example Geological Survey",
                                     "raid": "https://raid.org/10.99999/example"}) == []
    assert document_invariants(doc, {"survey_id": "other"})


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_committed_fixtures_hold_the_invariants(name):
    assert document_invariants(fixture(name)) == []


# ---------------------------------------------------------------- the shared-definition guarantee

def _strip_descriptions(node):
    if isinstance(node, dict):
        return {k: _strip_descriptions(v) for k, v in node.items() if k != "description"}
    if isinstance(node, list):
        return [_strip_descriptions(v) for v in node]
    return node


def test_subject_row_is_structurally_the_mtcat_definition():
    """Scope gate 10: subjects[] rows share ONE definition with mtcat. The two artifacts are not
    byte-identical (mtcat's rows carry per-property descriptions), so equivalence is STRUCTURAL:
    identical with every description stripped."""
    ours = _strip_descriptions(SM_SCHEMA["definitions"]["subject_row"])
    theirs = _strip_descriptions(MTCAT_SCHEMA["properties"]["surveys"]["items"]["properties"]["subjects"]["items"])
    assert ours == theirs, (ours, theirs)


def test_relationship_core_is_the_mtcat_core_without_the_legacy_extensions():
    """The relationship core {identifier, identifier_type, relation} is shared with mtcat's rows
    structurally (identifier and identifier_type identical minus descriptions; relation a string in
    both, mtcat additionally enum-pinned for its producer vocabulary), and MTCAT's legacy extensions
    custodian / identifies / resolution are NOT part of this schema."""
    ours = _strip_descriptions(SM_SCHEMA["definitions"]["relationship_core"])
    theirs = _strip_descriptions(MTCAT_SCHEMA["properties"]["surveys"]["items"]["properties"]["related_identifiers"]["items"])
    assert set(ours["properties"]) == {"identifier", "identifier_type", "relation"}
    for k in ("identifier", "identifier_type"):
        assert ours["properties"][k] == theirs["properties"][k], k
    assert ours["properties"]["relation"]["type"] == theirs["properties"]["relation"]["type"] == "string"
    assert ours["required"] == theirs["required"] == ["identifier"]
    for legacy in ("custodian", "identifies", "resolution", "scheme"):
        assert legacy not in ours["properties"], f"{legacy} is an MTCAT-only extension"
        assert legacy in theirs["properties"], f"mtcat still carries {legacy} (the pin's premise)"


# ---------------------------------------------------------------- layer 1: two builds of the vendored fixtures

def _run_build(surveys, out, *extra):
    r = subprocess.run([sys.executable, "-m", "extract.build_portal", "--surveys", str(surveys),
                        "--out", str(out), "--bundle-edi", "--no-validate", *extra],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out


def _docs(out):
    return {p.parent.name: json.loads(p.read_text(encoding="utf-8"))
            for p in sorted((out / "products").glob("*/survey-metadata.json"))}


def _mtcat(out):
    return json.loads((out / "mtcat.json").read_text(encoding="utf-8"))


def _minus_generated(doc):
    d = copy.deepcopy(doc)
    d.get("provenance", {}).pop("generated", None)
    return d


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """TWO consecutive real builds over the vendored fixture surveys."""
    pytest.importorskip("mt_metadata")
    return [_run_build(HERE / "fixtures", tmp_path_factory.mktemp(f"sm-{tag}") / "data") for tag in ("one", "two")]


_FUT = (date.today() + timedelta(days=365)).isoformat()


def _rich_yaml(slug, access_block):
    return f"""\
slug: {slug}
project_name: "{slug} project title"
name: "{slug} title"
country: Australia
organisation:
  name: "Example Org"
  ror: https://ror.org/00892tw58
license: "CC-BY-4.0"
{access_block}
abstract: "Rich survey abstract for {slug}."
dates: {{ start: 2014, end: 2016, issued: "2023-05-01" }}
geographic_extent: {{ west: 136.97, east: 137.07, south: -30.22, north: -30.10, datum: WGS84 }}
subjects:
  - code: "370602"
    scheme: ANZSRC-FoR-2020
creators:
  - name: "A. Person"
    name_type: person
contributors:
  - name: "B. Person"
    name_type: person
    role: ProjectLeader
organisations:
  - name: "Example Org"
    roles: [custodian, publisher]
    primary_custodian: true
funding:
  - organisation: "Example Funder"
    funding_doi: "10.47486/XN002"
identifiers:
  project_raid: "https://raid.org/10.12345/{slug}"
identity_classification:
  case: case_a
  represents:
    - scheme: DOI
      identifier: "10.99999/{slug}-level2"
related_identifiers:
  - identifier: "10.99999/{slug}-level2"
    identifier_type: DOI
    identifies: level2
    custodian: GA
  - identifier: "10.99999/{slug}-ts"
    identifier_type: DOI
    identifies: raw_packed
    custodian: GA
citation:
  preferred_identifier:
    scheme: DOI
    identifier: "10.99999/{slug}-level2"
  text_source: ausmt_generated
acknowledgements:
  - text: "Required wording for {slug}."
    type: required_source
attribution:
  declared_by: "A. Curator"
  declared_date: "2026-07-25"
"""


_D8_CORPUS = {"open-s": "access: { level: open }",
              "embargo-s": f"access: {{ level: embargoed, embargo_until: {_FUT} }}",
              "metaonly-s": "access: { level: metadata_only }"}


@pytest.fixture(scope="module")
def built_d8(tmp_path_factory):
    """The 3-survey D8 corpus (open + embargoed + metadata_only, every class curated), built with
    --products INSIDE the served root as deploy/Makefile does."""
    pytest.importorskip("mt_metadata")
    root = tmp_path_factory.mktemp("sm-d8")
    surveys = root / "surveys"
    surveys.mkdir()
    for slug, acc in _D8_CORPUS.items():
        d = surveys / slug
        shutil.copytree(EXAMPLE, d)
        (d / "survey.yaml").write_text(_rich_yaml(slug, acc), encoding="utf-8")
    out = root / "data"
    return _run_build(surveys, out, "--products", str(out / "products"))


def _assert_documents_clean(out):
    docs = _docs(out)
    assert docs, "the build must emit at least one document"
    v = schema_validator()
    mt = {s["survey_id"]: s for s in _mtcat(out)["surveys"]}
    for slug, doc in docs.items():
        errs = [f"{list(e.path)}: {e.message}" for e in v.iter_errors(doc)]
        assert not errs, f"{slug}: {errs}"
        assert doc["survey_id"] == slug, "survey_id == directory component (T24)"
        assert slug in mt, "every document names a catalogued survey"
        assert document_invariants(doc, mt[slug]) == [], (slug, document_invariants(doc, mt[slug]))
        size = len((out / "products" / slug / "survey-metadata.json").read_bytes())
        assert size <= DOCUMENT_BUDGET_BYTES, f"{slug}: {size} bytes exceeds the 16 KB budget"
    assert set(docs) == set(mt), "document slug set == mtcat surveys[].survey_id (T24, both directions)"
    return docs


def test_built_documents_validate_scan_clean_and_join_mtcat(built):
    _assert_documents_clean(built[0])


def test_built_documents_are_dict_equal_across_builds_minus_generated(built):
    a, b = _docs(built[0]), _docs(built[1])
    assert set(a) == set(b)
    for slug in a:
        assert _minus_generated(a[slug]) == _minus_generated(b[slug]), slug


def test_catalogue_and_surveys_are_byte_identical_across_builds_and_mtcat_dict_equal(built):
    """The framing proof's shape between two builds of THIS tree: the document rides a side channel
    and touches neither catalogue.json nor surveys.json (D18), and mtcat is unchanged but for its
    wall-clock generated_at."""
    for name in ("catalogue.json", "surveys.json"):
        assert (built[0] / name).read_bytes() == (built[1] / name).read_bytes(), name
    a, b = _mtcat(built[0]), _mtcat(built[1])
    a["portal"]["generated_at"] = b["portal"]["generated_at"] = "NORMALISED"
    assert a == b


def test_schema_served_at_both_routes_and_byte_stable(built):
    in_tree = (ROOT / "schema" / "ausmt-survey-metadata.schema.json").read_bytes()
    v = SM_SCHEMA["title"].split("AusMT Survey Metadata ", 1)[1].split("-draft", 1)[0].split(":", 1)[0]
    for out in built:
        latest = (out / "ausmt-survey-metadata.schema.json").read_bytes()
        versioned = (out / "schemas" / "ausmt-survey-metadata" / v / "ausmt-survey-metadata.schema.json").read_bytes()
        assert latest == in_tree and versioned == in_tree
        doc = next(iter(_docs(out).values()))
        assert doc["version"] == v
    a = (built[0] / "schemas" / "ausmt-survey-metadata" / v / "ausmt-survey-metadata.schema.json").read_bytes()
    b = (built[1] / "schemas" / "ausmt-survey-metadata" / v / "ausmt-survey-metadata.schema.json").read_bytes()
    assert a == b


def test_no_manifest_row_names_the_document(built):
    man = json.loads((built[0] / "manifest.json").read_text(encoding="utf-8"))
    rows = man.get("files", []) + man.get("bundles", [])
    assert rows, "the fixture build distributes something, so the manifest is non-empty"
    assert not any("survey-metadata" in json.dumps(r) for r in rows), \
        "survey-metadata.json is a metadata contract, not a download artifact; it gets no manifest row"


def test_the_mtcat_schema_copy_lines_are_textually_intact():
    """The portal pin (portal/tests/test_mtcat_machine_contract.py) reads these lines; the sibling
    survey-metadata copy block must leave them untouched."""
    src = (ROOT / "extract" / "build_portal.py").read_text(encoding="utf-8")
    assert '(out / "mtcat.schema.json").write_bytes(_schema_bytes)' in src
    assert '(out / "ausmt-survey-metadata.schema.json").write_bytes(_sm_schema_bytes)' in src


# ---------------------------------------------------------------- layer 2: the D8 corpus

def test_d8_corpus_documents_validate_and_hold_every_chain(built_d8):
    docs = _assert_documents_clean(built_d8)
    assert set(docs) == set(_D8_CORPUS)
    mt = {s["survey_id"]: s for s in _mtcat(built_d8)["surveys"]}
    for slug, doc in docs.items():
        # every class present on open, embargoed and metadata_only alike
        for cls in ("identifiers", "activities", "abstract", "subjects", "creators", "contributors",
                    "organisations", "funders", "citation", "acknowledgements", "rights", "extent",
                    "relationships", "attribution", "dates"):
            assert cls in doc, f"{slug}: {cls}"
        # the projection chains on REAL emitted values
        assert mt[slug]["raid"] == doc["activities"][0]["identifier"]
        assert mt[slug]["organisation"] == "Example Org"
        assert raid_rule_ok(mt[slug], doc) and organisation_rule_ok(mt[slug], doc)
        assert mt[slug]["subjects"] == doc["subjects"]
    assert docs["embargo-s"]["rights"]["access"] == "embargoed"
    assert docs["metaonly-s"]["rights"]["access"] == "metadata_only"
    assert "formats" not in mt["embargo-s"] and "formats" not in mt["metaonly-s"]
    # the title chain: survey-metadata title is project_name, mtcat title is the name label
    assert docs["open-s"]["title"] == "open-s project title" and mt["open-s"]["title"] == "open-s title"


def test_d8_no_exact_station_coordinate_reaches_a_non_served_document(built_d8):
    """The curated extent is never station-derived, so no exact catalogue coordinate string of a
    non-served survey appears in its document (the test_access_gate.py sweep, applied here)."""
    sys.path.insert(0, str(ROOT / "extract"))
    from _contract import CATALOGUE_COLUMNS  # noqa: PLC0415
    cat = json.loads((built_d8 / "catalogue.json").read_text(encoding="utf-8"))
    lat_i, lon_i = CATALOGUE_COLUMNS.index("lat"), CATALOGUE_COLUMNS.index("lon")
    coords = {str(row[lat_i]) for row in cat} | {str(row[lon_i]) for row in cat}
    coords = {c for c in coords if c not in ("None", "")}
    assert coords, "the catalogue carries exact positions"
    for slug in ("embargo-s", "metaonly-s"):
        txt = (built_d8 / "products" / slug / "survey-metadata.json").read_text(encoding="utf-8")
        leaked = [c for c in coords if c in txt]
        assert not leaked, f"{slug}: exact station coordinates {leaked} in survey-metadata.json"
        for key in ("dimensionality", "classification", "median_relative_error", "input_sha256"):
            assert f'"{key}"' not in txt


# ---------------------------------------------------------------- layer 3: the corpus arm

@corpus_arm
def test_corpus_documents_validate_scan_clean_and_join_mtcat():
    out = Path(CORPUS_DATA)
    docs = _assert_documents_clean(out)
    assert len(docs) == len(_mtcat(out)["surveys"])
    total = sum(len((out / "products" / s / "survey-metadata.json").read_bytes()) for s in docs)
    assert total > 0
