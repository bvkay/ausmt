"""survey-metadata.json emission semantics, pinned against the real emitter.

The second public contract: data/products/<survey_id>/survey-metadata.json, one per survey, the
canonical public metadata of one survey dataset/release, generated from survey.yaml by
build_portal.survey_metadata_document, against engine/schema/ausmt-survey-metadata.schema.json
0.1 (LANE-CONTRACT-SURVEY-METADATA).

What this module pins, each RED-proven against the unchanged tree:

  * the PRESENCE RULE: a survey.yaml carrying only the validator's hard-required set {slug, name,
    country, organisation.name, license, access.level} emits EXACTLY {schema, version, survey_id,
    title, rights{license, access}, provenance{generated, generator}} - library defaults are never
    emitted as assertions;
  * the class rules: title = project_name else name (never the directory name); abstract, subjects,
    creators, contributors, organisations, citation, acknowledgements, dates.issued and attribution
    VERBATIM when present; no engine-appended HostingInstitution row and no engine-authored
    acknowledgement; funders (funding_doi -> award_uri); dates.coverage from the year
    range; rights {license raw, access normalised, embargo_until ISO}; extent from the curated
    geographic_extent only, WGS84 only, all-zero = placeholder, omitted under withheld
    coordinates; identifiers[] from the identity_classification mapping (case_a represents[] / case_b
    own_identifiers[]) and every other related_identifiers row to relationships[] {identifier,
    identifier_type, relation} with the DOI resolver prefix stripped, case kept, exact duplicates
    dropped; activities[] from identifiers.project_raid only; placeholders (None, "",
    TBD, TODO, the template's REPLACE sentinel) treated as absent; no nulls and no empty containers
    ever;
  * a non-served (embargoed / metadata_only) survey emits every curated class exactly as an open
    one does, and no formats or distribution facts anywhere;
  * INFERRED-REVIEW and [CONFIRM] are YAML comments and never reach a document; the marked
    values emit as curated facts;
  * the hard stop (_validate_survey_metadata raises naming the survey when
    citation.preferred_identifier has no equal designated identifier), on both classifications;
  * the LOUD SKIP: a corpus with one survey the REAL validator FAILs still builds, its
    build_report.json lists the slug under surveys_skipped_validation, and scripts/verify.py FAILs
    on the non-empty list; verify.py also validates every products/*/survey-metadata.json and pins
    the slug set to mtcat's surveys[].survey_id.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = ROOT.parent
sys.path.insert(0, str(ROOT / "extract"))
sys.path.insert(0, str(HERE))

import build_portal as bp  # noqa: E402
from _contract import SURVEY_METADATA_SCHEMA_VERSION  # noqa: E402
from test_survey_metadata_schema_v01 import (  # noqa: E402
    preferred_identifier_designated, scan_nulls_and_empties, validator as schema_validator)

EXAMPLE = HERE / "fixtures" / "example-survey"
VERIFY = ROOT / "scripts" / "verify.py"
PROV = {"pipeline": "ausmt/extract.build_portal", "pipeline_version": "0.0-test"}
GEN = "2026-01-01T00:00:00Z"

MINIMAL = {"slug": "min-survey", "name": "Minimal Survey", "country": "Australia",
           "organisation": {"name": "Example Org"}, "license": "CC-BY-4.0", "access": {"level": "open"}}
MINIMAL_KEYS = {"schema", "version", "survey_id", "title", "rights", "provenance"}


def _doc(y, served=True, coord_state="exact", label=None):
    smeta = bp.survey_meta_from_yaml(y)
    smeta["slug"] = bp.safe_component(y.get("slug", "x"))
    return bp.survey_metadata_document(label or y.get("name", "dir-name"), y, smeta, served, coord_state,
                                       prov=PROV, generated_at=GEN)


def _errors(doc):
    return [f"{'/'.join(str(p) for p in e.absolute_path)}: {e.message}"
            for e in schema_validator().iter_errors(json.loads(bp._jdump(doc)))]


def _clean(doc):
    """validates with format checking + zero nulls + zero empties, or an assertion naming what failed."""
    assert not _errors(doc), _errors(doc)
    nulls, empties = scan_nulls_and_empties(json.loads(bp._jdump(doc)))
    assert not nulls and not empties, (nulls, empties)


def _full_yaml(**over):
    """A kitchen-sink survey.yaml mapping carrying every class the emitter maps (case_a)."""
    y = {
        "slug": "full-survey", "project_name": "Full Survey Project Name", "name": "Full Survey",
        "country": "Australia", "organisation": {"name": "Example Org", "ror": "https://ror.org/00892tw58"},
        "license": "CC-BY-4.0", "access": {"level": "open"},
        "abstract": "An uncapped abstract.\n", "dates": {"start": 2014, "end": "2016-03-02", "issued": "2023-05-01"},
        "subjects": [{"code": "370602", "scheme": "ANZSRC-FoR-2020", "label": "EM methods", "uri": None}],
        "creators": [{"name": "A. Person", "name_type": "person", "orcid": "0000-0002-1825-0097"},
                     {"name": "Example Org", "name_type": "organisation", "ror": None}],
        "contributors": [{"name": "B. Person", "name_type": "person", "role": "ProjectLeader"}],
        "organisations": [{"name": "Example Org", "ror": "https://ror.org/00892tw58", "roles": ["custodian", "publisher"],
                           "primary_custodian": True},
                          {"name": "Example Repository", "roles": ["distributor"]}],
        "funding": [{"organisation": "Example Funder", "organisation_ror": "https://ror.org/0123456789",
                     "grant_id": "G-1", "grant_title": "Grant title", "funding_doi": "10.47486/XN002"},
                    {"organisation": "Name Only Funder"}],
        "identity_classification": {"case": "case_a",
                                    "represents": [{"scheme": "DOI", "identifier": "10.99999/level2-release"}]},
        "related_identifiers": [
            {"identifier": "10.99999/level2-release", "identifier_type": "DOI", "identifies": "level2", "custodian": "GA"},
            {"identifier": "10.99999/ts-release", "identifier_type": "DOI", "identifies": "raw_packed", "custodian": "GA"},
            {"identifier": "http://dx.doi.org/10.11636/Record.2020.011", "identifier_type": "DOI", "custodian": "GA"},
            {"identifier": "10.99999/collection", "identifier_type": "DOI", "identifies": "collection",
             "relation": "IsPartOf", "custodian": "NCI"},
            {"identifier": "10.99999/collection", "identifier_type": "DOI", "identifies": "collection",
             "relation": "IsPartOf", "custodian": "NCI (duplicate row)"},
            {"identifier": "https://pid.example.org/dataset/x1", "identifier_type": "URL", "identifies": "entire"},
        ],
        "citation": {"preferred_identifier": {"scheme": "DOI", "identifier": "10.99999/level2-release"},
                     "text_source": "ausmt_generated",
                     "additional": [{"identifier": {"scheme": "DOI", "identifier": "10.99999/ts-release"},
                                     "reason": "repository_product"}]},
        "acknowledgements": [{"text": "Required wording, verbatim.", "type": "required_source", "source": "Example Org"}],
        "attribution": {"declared_by": "A. Curator", "declared_date": "2026-07-25", "changes_made": True,
                        "changes_summary": "EMTF XML renditions are producer-derived."},
        "geographic_extent": {"west": 136.97, "east": 137.07, "south": -30.22, "north": -30.10, "datum": "WGS84"},
        "identifiers": {"project_raid": "https://raid.org/10.12345/AB1234", "dataset_doi": None},
    }
    y.update(over)
    return y


# ---------------------------------------------------------------- the presence rule

def test_minimal_survey_emits_exactly_the_contract_key_set():
    doc = _doc(MINIMAL)
    assert set(doc) == MINIMAL_KEYS, sorted(doc)
    assert doc["schema"] == "ausmt-survey-metadata"
    assert doc["version"] == SURVEY_METADATA_SCHEMA_VERSION
    assert doc["survey_id"] == "min-survey" and doc["title"] == "Minimal Survey"
    assert doc["rights"] == {"license": "CC-BY-4.0", "access": "open"}
    assert doc["provenance"] == {"generated": GEN, "generator": "ausmt/extract.build_portal 0.0-test"}
    _clean(doc)


def test_document_key_order_follows_the_schema():
    order = list(json.loads((ROOT / "schema" / "ausmt-survey-metadata.schema.json").read_text(encoding="utf-8"))["properties"])
    doc = _doc(_full_yaml())
    keys = list(doc)
    assert keys == [k for k in order if k in keys], keys


# ---------------------------------------------------------------- the class rules

def test_title_is_project_name_else_name_never_the_directory_name():
    assert _doc(_full_yaml(), label="dir-name")["title"] == "Full Survey Project Name"
    y = dict(MINIMAL)
    assert _doc(y, label="dir-name")["title"] == "Minimal Survey"
    y = dict(MINIMAL, project_name="TBD")
    assert _doc(y, label="dir-name")["title"] == "Minimal Survey", "a placeholder project_name is absent"


def test_dates_coverage_from_the_year_range_and_issued_verbatim():
    doc = _doc(_full_yaml())
    assert doc["dates"] == {"coverage": {"year_start": 2014, "year_end": 2016}, "issued": "2023-05-01"}
    assert "dates" not in _doc(MINIMAL)
    only_start = _doc(dict(MINIMAL, dates={"start": "2020-01-01"}))
    assert only_start["dates"] == {"coverage": {"year_start": 2020}}
    unparseable = _doc(dict(MINIMAL, dates={"start": "n/a", "end": None}))
    assert "dates" not in unparseable
    assert "dataset_version" not in _doc(_full_yaml(version="1.0.1")), "no dataset_version home yet"


def test_curated_classes_ride_through_verbatim_with_no_engine_additions():
    doc = _doc(_full_yaml())
    assert doc["abstract"] == "An uncapped abstract.\n"
    assert doc["subjects"] == [{"code": "370602", "scheme": "ANZSRC-FoR-2020", "label": "EM methods"}]
    assert doc["creators"] == [{"name": "A. Person", "name_type": "person", "orcid": "0000-0002-1825-0097"},
                               {"name": "Example Org", "name_type": "organisation"}]
    assert doc["contributors"] == [{"name": "B. Person", "name_type": "person", "role": "ProjectLeader"}], \
        "no HostingInstitution row is appended by the engine"
    assert doc["organisations"] == [
        {"name": "Example Org", "ror": "https://ror.org/00892tw58", "roles": ["custodian", "publisher"],
         "primary_custodian": True},
        {"name": "Example Repository", "roles": ["distributor"]}]
    assert doc["citation"] == {
        "preferred_identifier": {"scheme": "DOI", "identifier": "10.99999/level2-release"},
        "text_source": "ausmt_generated",
        "additional": [{"identifier": {"scheme": "DOI", "identifier": "10.99999/ts-release"},
                        "reason": "repository_product"}]}
    assert doc["acknowledgements"] == [{"text": "Required wording, verbatim.", "type": "required_source",
                                        "source": "Example Org"}], "no engine-authored row"
    assert doc["attribution"] == {"declared_by": "A. Curator", "declared_date": "2026-07-25",
                                  "changes_made": True,
                                  "changes_summary": "EMTF XML renditions are producer-derived."}
    _clean(doc)


def test_funders_map_per_d6():
    doc = _doc(_full_yaml())
    assert doc["funders"] == [
        {"name": "Example Funder", "ror": "https://ror.org/0123456789", "award_number": "G-1",
         "award_title": "Grant title", "award_uri": "https://doi.org/10.47486/XN002"},
        {"name": "Name Only Funder"}]
    assert "funders" not in _doc(dict(MINIMAL, funding=[]))
    assert "funders" not in _doc(dict(MINIMAL, funding=[{"organisation_ror": "https://ror.org/x"}])), \
        "a row without a funder name is not a funder"
    prefixed = _doc(dict(MINIMAL, funding=[{"organisation": "F", "funding_doi": "https://doi.org/10.47486/XN002"}]))
    assert prefixed["funders"] == [{"name": "F", "award_uri": "https://doi.org/10.47486/XN002"}]


def test_rights_license_raw_access_normalised_embargo_iso():
    doc = _doc(dict(MINIMAL, license="cc-by-4.0", access={"level": " Embargoed ", "embargo_until": "2027-02-01"}))
    assert doc["rights"] == {"license": "cc-by-4.0", "access": "embargoed", "embargo_until": "2027-02-01"}
    doc = _doc(dict(MINIMAL, license="TBD"))
    assert doc["rights"] == {"access": "open"}, "a placeholder licence is absent; access is always stated"
    _clean(doc)


def test_extent_is_the_curated_wgs84_bbox_only():
    doc = _doc(_full_yaml())
    assert doc["extent"] == {"bbox": {"west": 136.97, "south": -30.22, "east": 137.07, "north": -30.10}}
    gda = _full_yaml(geographic_extent={"west": 136.97, "east": 137.07, "south": -30.22, "north": -30.10,
                                        "datum": "GDA2020"})
    assert "extent" not in _doc(gda), "only a WGS84 extent is emitted; GDA2020 has no home yet"
    nodatum = _full_yaml(geographic_extent={"west": 136.97, "east": 137.07, "south": -30.22, "north": -30.10})
    assert "extent" not in _doc(nodatum), "no datum means no WGS84 assertion"
    zero = _full_yaml(geographic_extent={"west": 0, "east": 0, "south": 0, "north": 0, "datum": "WGS84"})
    assert "extent" not in _doc(zero), "the template's all-zero bbox is a placeholder"
    assert "extent" not in _doc(_full_yaml(), coord_state="withheld"), "withheld coordinates: no extent"
    assert "extent" in _doc(_full_yaml(), coord_state="generalised"), "a curated extent is not station-derived"
    assert "extent" not in _doc(MINIMAL)


def test_identifiers_and_relationships_partition_per_d12_case_a():
    doc = _doc(_full_yaml())
    assert doc["identifiers"] == [{"scheme": "DOI", "identifier": "10.99999/level2-release"}]
    assert doc["relationships"] == [
        {"identifier": "10.99999/ts-release", "identifier_type": "DOI", "relation": "IsDerivedFrom"},
        {"identifier": "10.11636/Record.2020.011", "identifier_type": "DOI"},
        {"identifier": "10.99999/collection", "identifier_type": "DOI", "relation": "IsPartOf"},
        {"identifier": "https://pid.example.org/dataset/x1", "identifier_type": "URL", "relation": "IsVariantFormOf"},
    ], ("the designated row leaves relationships; the resolver prefix is stripped and case kept; the "
        "relation derives from identifies when not explicit; exact duplicates are dropped; rows carry only "
        "the clean core")
    for row in doc["relationships"]:
        assert set(row) <= {"identifier", "identifier_type", "relation"}
    assert preferred_identifier_designated(doc)
    _clean(doc)


def test_identifiers_and_relationships_partition_per_d12_case_b():
    y = _full_yaml(identity_classification={"case": "case_b",
                                            "own_identifiers": [{"scheme": "DOI", "identifier": "https://doi.org/10.99999/ausmt-release"}]},
                   citation={"preferred_identifier": {"scheme": "DOI", "identifier": "10.99999/ausmt-release"}})
    doc = _doc(y)
    assert doc["identifiers"] == [{"scheme": "DOI", "identifier": "10.99999/ausmt-release"}]
    assert [r["identifier"] for r in doc["relationships"]] == [
        "10.99999/level2-release", "10.99999/ts-release", "10.11636/Record.2020.011", "10.99999/collection",
        "https://pid.example.org/dataset/x1"], "Case B: every source record is a relationship"
    assert preferred_identifier_designated(doc)
    _clean(doc)


def test_no_designation_means_no_identifiers_and_every_row_is_a_relationship():
    legacy = _doc(_full_yaml(identity_classification="case_a", citation=None))
    assert "identifiers" not in legacy, "a legacy scalar classification carries no designation"
    assert len(legacy["relationships"]) == 5
    absent = _doc(_full_yaml(identity_classification=None, citation=None))
    assert "identifiers" not in absent and len(absent["relationships"]) == 5
    represents_placeholder = _doc(_full_yaml(identity_classification={"case": "case_a", "represents": [
        {"scheme": "DOI", "identifier": "TBD"}]}, citation=None))
    assert "identifiers" not in represents_placeholder
    assert "relationships" not in _doc(MINIMAL)


def test_activities_from_project_raid_only():
    assert _doc(_full_yaml())["activities"] == [{"identifier": "https://raid.org/10.12345/AB1234", "scheme": "RAiD"}]
    assert "activities" not in _doc(_full_yaml(identifiers={"project_raid": None}))
    assert "activities" not in _doc(MINIMAL)


def test_placeholders_are_absent_and_nothing_is_null_or_empty():
    y = _full_yaml(abstract="TBD", subjects=[], creators=[{"name": "« REPLACE » name", "name_type": "person"}],
                   contributors=None, acknowledgements=[{"text": "", "type": "custodian"}],
                   organisations=[{"name": "TODO", "roles": ["custodian"]}, {"name": "No roles row"}],
                   funding=None, citation={"preferred_text": "", "text_source": "source_provided"},
                   attribution={"declared_by": None, "declared_date": ""})
    doc = _doc(y)
    for k in ("abstract", "subjects", "creators", "contributors", "acknowledgements", "organisations",
              "funders", "attribution"):
        assert k not in doc, k
    assert doc["citation"] == {"text_source": "source_provided"}
    _clean(doc)


def test_served_flag_withholds_no_class(monkeypatch):
    """The emitter gates nothing class-wise on the serve state; the two documents are identical."""
    y = _full_yaml(access={"level": "embargoed", "embargo_until": "2027-02-01"})
    open_doc, held_doc = _doc(y, served=True), _doc(y, served=False)
    assert open_doc == held_doc
    assert held_doc["rights"]["access"] == "embargoed"
    assert "formats" not in held_doc and "distribution" not in held_doc


# --------------------------------------------------------------- Markers never leak

MARKED_YAML = """\
slug: marked-survey
name: "Marked Survey"
country: Australia
organisation:
  name: "Example Org"
  ror: https://ror.org/00892tw58    # [CONFIRM] no ROR asserted; none verified at intake
license: "CC-BY-4.0"    # [CONFIRM]
access:
  level: embargoed
  embargo_until: 2027-02-01    # [CONFIRM] first of month assumed
subjects:
  # INFERRED-REVIEW: corpus-default subject
  - code: "370602"
    scheme: ANZSRC-FoR-2020
creators:
  # INFERRED-REVIEW: confirm citation authorship
  - name: "A. Person"
    name_type: person
related_identifiers:
  - identifier: 10.25914/bzd5-n780
    identifier_type: DOI
    identifies: raw_packed    # INFERRED-REVIEW: confirm raw_packed vs collection
    custodian: NCI
"""


def test_inferred_review_and_confirm_markers_never_reach_the_document(tmp_path):
    pytest.importorskip("yaml")
    p = tmp_path / "survey.yaml"
    p.write_text(MARKED_YAML, encoding="utf-8")
    y = bp._read_yaml(p)
    doc = _doc(y)
    text = bp._jdump(doc)
    assert "INFERRED-REVIEW" not in text and "[CONFIRM]" not in text
    # The marked values are curated facts and emit as such
    assert doc["subjects"] == [{"code": "370602", "scheme": "ANZSRC-FoR-2020"}]
    assert doc["creators"] == [{"name": "A. Person", "name_type": "person"}]
    assert doc["relationships"] == [{"identifier": "10.25914/bzd5-n780", "identifier_type": "DOI",
                                     "relation": "IsDerivedFrom"}]
    assert doc["rights"] == {"license": "CC-BY-4.0", "access": "embargoed", "embargo_until": "2027-02-01"}
    _clean(doc)


# ---------------------------------------------------------------- _validate_survey_metadata

def test_validate_survey_metadata_passes_clean_documents_and_reports_violations():
    good = {"full-survey": _doc(_full_yaml()), "min-survey": _doc(MINIMAL)}
    assert bp._validate_survey_metadata(good) == []
    bad = json.loads(bp._jdump(_doc(_full_yaml())))
    bad["extent"]["bbox"].pop("north")
    nulls = json.loads(bp._jdump(_doc(_full_yaml())))
    nulls["abstract"] = None
    empties = json.loads(bp._jdump(_doc(_full_yaml())))
    empties["subjects"] = []
    errs = bp._validate_survey_metadata({"bad": bad, "nulls": nulls, "empties": empties})
    assert any("bad" in e and "north" in e for e in errs), errs
    assert any("nulls" in e and "null" in e for e in errs), errs
    assert any("empties" in e for e in errs), errs


@pytest.mark.parametrize("classification", [
    {"case": "case_a", "represents": [{"scheme": "DOI", "identifier": "10.99999/level2-release"}]},
    {"case": "case_b", "own_identifiers": [{"scheme": "DOI", "identifier": "10.99999/ausmt-release"}]},
    None,
])
def test_t25_hard_stop_names_the_survey_on_both_classifications(classification):
    y = _full_yaml(identity_classification=classification,
                   citation={"preferred_identifier": {"scheme": "DOI", "identifier": "10.99999/not-designated"}})
    doc = _doc(y)
    with pytest.raises(ValueError) as ei:
        bp._validate_survey_metadata({"full-survey": doc})
    msg = str(ei.value)
    assert "full-survey" in msg and "preferred_identifier" in msg and "10.99999/not-designated" in msg, msg


def test_t25_holds_when_the_preferred_identifier_is_designated():
    assert bp._validate_survey_metadata({"full-survey": _doc(_full_yaml())}) == []


# ---------------------------------------------------------------- built output

def _stage(root: Path, slug: str, yaml_text: str):
    d = root / slug
    shutil.copytree(EXAMPLE, d)
    (d / "survey.yaml").write_text(yaml_text, encoding="utf-8")
    return d


def _build(surveys: Path, out: Path, *extra, env=None, validate=False):
    argv = [sys.executable, "-m", "extract.build_portal", "--surveys", str(surveys), "--out", str(out),
            "--bundle-edi", *extra]
    if not validate:
        argv.append("--no-validate")
    return subprocess.run(argv, cwd=str(ROOT), capture_output=True, text=True, env=env)


def _verify(data_dir: Path):
    return subprocess.run([sys.executable, str(VERIFY), "--data-dir", str(data_dir)],
                          cwd=str(ROOT), capture_output=True, text=True)


def _read_doc(out: Path, slug: str):
    return json.loads((out / "products" / slug / "survey-metadata.json").read_text(encoding="utf-8"))


_MIN_YAML = """\
slug: min-survey
name: "Minimal Survey"
country: Australia
organisation:
  name: "Example Org"
license: "CC-BY-4.0"
access:
  level: open
"""

_FUT = (date.today() + timedelta(days=365)).isoformat()


def _rich_yaml(slug, name, access_block):
    return f"""\
slug: {slug}
project_name: "{name}"
name: "{name}"
country: Australia
organisation:
  name: "Example Org"
  ror: https://ror.org/00892tw58
license: "CC-BY-4.0"
{access_block}
abstract: "Rich survey abstract."
dates: {{ start: 2014, end: 2016 }}
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


_RICH_CLASSES = ("abstract", "dates", "identifiers", "subjects", "creators", "contributors", "organisations",
                 "funders", "citation", "acknowledgements", "rights", "extent", "relationships", "attribution")


def test_defaults_build_emits_exactly_the_minimal_key_set_under_the_served_root(tmp_path):
    """The presence rule on BUILT output, and the document lands under out/products/<slug>/ (the
    served root) on every build, even with --products pointing elsewhere, and not under --products."""
    pytest.importorskip("mt_metadata")
    surveys = tmp_path / "surveys"
    surveys.mkdir()
    _stage(surveys, "min-survey", _MIN_YAML)
    out, prod = tmp_path / "data", tmp_path / "elsewhere"
    r = _build(surveys, out, "--products", str(prod))
    assert r.returncode == 0, r.stderr
    doc = _read_doc(out, "min-survey")
    assert set(doc) == MINIMAL_KEYS, sorted(doc)
    assert doc["survey_id"] == "min-survey" and doc["title"] == "Minimal Survey"
    assert doc["rights"] == {"license": "CC-BY-4.0", "access": "open"}
    prov = json.loads((out / "build_provenance.json").read_text(encoding="utf-8"))
    assert doc["provenance"]["generator"] == f"{prov['pipeline']} {prov['pipeline_version']}"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", doc["provenance"]["generated"])
    assert not (prod / "min-survey" / "survey-metadata.json").exists(), "never under --products"
    _clean(doc)
    # the schema routes: immutable versioned + latest, byte-identical to the in-tree artifact
    in_tree = (ROOT / "schema" / "ausmt-survey-metadata.schema.json").read_bytes()
    assert (out / "ausmt-survey-metadata.schema.json").read_bytes() == in_tree
    assert (out / "schemas" / "ausmt-survey-metadata" / SURVEY_METADATA_SCHEMA_VERSION
            / "ausmt-survey-metadata.schema.json").read_bytes() == in_tree
    # the mtcat schema copy lines are untouched (the portal pin) and still served
    assert (out / "mtcat.schema.json").read_bytes() == (ROOT / "schema" / "mtcat.schema.json").read_bytes()
    # build_report carries the loud-skip list, empty on a clean build; verify passes
    rep = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    assert rep["surveys_skipped_validation"] == []
    v = _verify(out)
    assert v.returncode == 0, v.stdout + v.stderr
    assert "survey-metadata" in v.stdout


def test_d8_every_class_is_emitted_for_open_embargoed_and_metadata_only_alike(tmp_path):
    """No new withholding. The 3-survey corpus (open + embargoed + metadata_only), each curating
    every class: documents for all three, every class present on all three, no formats or distribution
    key anywhere, and the slug set equals mtcat's surveys[].survey_id."""
    pytest.importorskip("mt_metadata")
    surveys = tmp_path / "surveys"
    surveys.mkdir()
    corpus = {"open-s": "access: { level: open }",
              "embargo-s": f"access: {{ level: embargoed, embargo_until: {_FUT} }}",
              "metaonly-s": "access: { level: metadata_only }"}
    for slug, acc in corpus.items():
        _stage(surveys, slug, _rich_yaml(slug, f"{slug} title", acc))
    out = tmp_path / "data"
    r = _build(surveys, out, "--products", str(out / "products"))
    assert r.returncode == 0, r.stderr
    mtcat = json.loads((out / "mtcat.json").read_text(encoding="utf-8"))
    assert {s["survey_id"] for s in mtcat["surveys"]} == set(corpus)
    docs = {slug: _read_doc(out, slug) for slug in corpus}
    for slug, doc in docs.items():
        for cls in _RICH_CLASSES:
            assert cls in doc, f"{slug}: {cls} missing; every curated class rides on every survey"
        assert "formats" not in doc and "distribution" not in doc
        assert doc["identifiers"] == [{"scheme": "DOI", "identifier": f"10.99999/{slug}-level2"}]
        assert doc["relationships"] == [{"identifier": f"10.99999/{slug}-ts", "identifier_type": "DOI",
                                         "relation": "IsDerivedFrom"}]
        assert doc["extent"]["bbox"] == {"west": 136.97, "south": -30.22, "east": 137.07, "north": -30.10}
        _clean(doc)
    assert docs["open-s"]["rights"] == {"license": "CC-BY-4.0", "access": "open"}
    assert docs["embargo-s"]["rights"] == {"license": "CC-BY-4.0", "access": "embargoed", "embargo_until": _FUT}
    assert docs["metaonly-s"]["rights"] == {"license": "CC-BY-4.0", "access": "metadata_only"}
    # the three documents differ ONLY in survey-specific values: same key set
    assert set(docs["open-s"]) == set(docs["embargo-s"]) == set(docs["metaonly-s"])
    assert _verify(out).returncode == 0


def test_t25_hard_stop_fails_the_build_naming_the_survey(tmp_path):
    """Reachable only without a validator (the validator FAILs an undesignated preferred_identifier at
    the entry gates); the emitter's own last line still refuses to publish."""
    pytest.importorskip("mt_metadata")
    surveys = tmp_path / "surveys"
    surveys.mkdir()
    bad = _rich_yaml("t25-survey", "T25 survey", "access: { level: open }").replace(
        'identifier: "10.99999/t25-survey-level2"\n  text_source',
        'identifier: "10.99999/somewhere-else"\n  text_source')
    assert "somewhere-else" in bad
    _stage(surveys, "t25-survey", bad)
    out = tmp_path / "data"
    r = _build(surveys, out)
    assert r.returncode != 0, "the build must not publish a document whose preferred identifier is undesignated"
    assert "t25-survey" in r.stderr and "preferred_identifier" in r.stderr, r.stderr[-2000:]


# --------------------------------------------------------------- The loud skip

IMAGE_TOPOLOGY_SKIP_REASON = ("engine image build: gateway tree not shipped "
                              "(designed topology; vendored oracle lives in gateway/tests)")


def _resolve_validator_dir() -> Path:
    """The REAL survey validator (the sibling ausmt-surveys checkout), else the committed vendored
    copy (the PINNED contract), else the designed engine-image skip (test_validator_gate.py)."""
    sibling = REPO.parent / "ausmt-surveys" / "_validation"
    if (sibling / "validate_survey.py").is_file():
        return sibling
    vendored = REPO / "gateway" / "tests" / "fixtures" / "vendored_validation"
    if (vendored / "validate_survey.py").is_file():
        return vendored
    if not (REPO / "gateway").is_dir():
        pytest.skip(IMAGE_TOPOLOGY_SKIP_REASON)
    raise AssertionError(f"no validator: neither {sibling} nor the vendored copy {vendored} exists, yet the "
                         f"gateway tree IS present (a broken checkout, not a legitimate skip)")


_BAD_ACCESS_YAML = _MIN_YAML.replace("slug: min-survey", "slug: bad-survey").replace(
    "level: open", "level: not-a-level")


def test_loud_skip_records_the_slug_and_verify_fails(tmp_path):
    """A survey the REAL validator FAILs is skipped by the build (exit 0, the rest builds), the
    slug is recorded in build_report.json surveys_skipped_validation, and scripts/verify.py FAILs on
    the non-empty list so `make rebuild-data` never swaps a build that silently lost a survey."""
    pytest.importorskip("mt_metadata")
    vdir = _resolve_validator_dir()
    sys.path.insert(0, str(vdir))
    import validate_survey  # noqa: PLC0415  (the real validator, run here to prove the fixture FAILs)
    surveys = tmp_path / "surveys"
    surveys.mkdir()
    good = _stage(surveys, "min-survey", _MIN_YAML)
    bad = _stage(surveys, "bad-survey", _BAD_ACCESS_YAML)
    assert validate_survey.validate(bad).worst() == 2, "the fixture must FAIL the real validator"
    assert validate_survey.validate(good).worst() < 2, "the control must not FAIL the real validator"
    env = dict(os.environ, AUSMT_VALIDATOR_PATH=str(vdir))
    out = tmp_path / "data"
    r = _build(surveys, out, env=env, validate=True)
    assert r.returncode == 0, r.stderr
    assert "SKIP bad-survey" in r.stderr
    rep = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    assert rep["surveys_skipped_validation"] == ["bad-survey"]
    assert (out / "products" / "min-survey" / "survey-metadata.json").is_file()
    assert not (out / "products" / "bad-survey").exists()
    v = _verify(out)
    assert v.returncode != 0, "verify.py must FAIL on a non-empty surveys_skipped_validation"
    assert "bad-survey" in v.stdout and "VERIFY: FAIL" in v.stdout, v.stdout + v.stderr


def test_verify_validates_every_document_and_pins_the_slug_set(tmp_path):
    pytest.importorskip("mt_metadata")
    surveys = tmp_path / "surveys"
    surveys.mkdir()
    _stage(surveys, "min-survey", _MIN_YAML)
    out = tmp_path / "data"
    assert _build(surveys, out).returncode == 0
    assert _verify(out).returncode == 0
    p = out / "products" / "min-survey" / "survey-metadata.json"
    pristine = p.read_text(encoding="utf-8")
    doc = json.loads(pristine)
    doc["identifiers"] = []
    p.write_text(json.dumps(doc), encoding="utf-8")
    v = _verify(out)
    assert v.returncode != 0 and "min-survey" in v.stdout, "a document that fails the schema must fail verify"
    doc = json.loads(pristine)
    doc["provenance"]["generated"] = "yesterday-ish"
    p.write_text(json.dumps(doc), encoding="utf-8")
    assert _verify(out).returncode != 0, "format checking must be on in verify"
    p.write_text(pristine, encoding="utf-8")
    stray = out / "products" / "stray-survey"
    stray.mkdir()
    (stray / "survey-metadata.json").write_text(pristine, encoding="utf-8")
    assert _verify(out).returncode != 0, "a document for a survey mtcat does not list must fail verify"
    shutil.rmtree(stray)
    p.unlink()
    assert _verify(out).returncode != 0, "a mtcat survey without a document must fail verify"


def test_designation_dedup_folds_scheme_case():
    """A case-mismatched scheme must not let the SAME identifier be emitted both as an identifier
    OF the dataset and as a relationship TO it - the dedup key once compared schemes raw, so
    scheme 'doi' beside identifier_type 'DOI' published the dataset IsIdenticalTo itself (the exact
    self-reference the partition exists to prevent). The fold reuses the normalisation
    _sm_bare_identifier already applies for its own DOI test."""
    y = _full_yaml(identity_classification={
        "case": "case_a",
        "represents": [{"scheme": "doi", "identifier": "10.99999/level2-release"}]})
    y["related_identifiers"] = [
        {"identifier": "https://doi.org/10.99999/level2-release",
         "identifier_type": "DOI", "relation": "IsIdenticalTo"}]
    doc = _doc(y)
    assert doc["identifiers"] == [{"scheme": "doi", "identifier": "10.99999/level2-release"}], (
        "the designated row publishes the curated scheme spelling verbatim")
    assert not doc.get("relationships"), (
        "the designated identifier leaked back in as a self-relationship: %r" % doc.get("relationships"))
    _clean(doc)
