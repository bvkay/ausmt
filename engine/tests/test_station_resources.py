"""Resources[] on the promoted station.json: what represents this station, and what merely contains it.

An open station's resources are the SERVED, ADDRESSABLE things - its transfer function as EDI,
as canonical EMTF XML and as MTH5, plus the per-survey archives those files are bundled into. Each
carries the path the download manifest records for the same bytes, and none carries `identifiers[]`,
because a DOI identifying THIS EXACT file does not exist for anything AusMT serves today.

The role question splits in two, and the engine emits both axes only where they are mechanically
certain: the served EDI is the never-edited source in its original form; the EMTF XML and the MTH5
are engine conversions of it, so they are derived alternates. The bundle archives carry NEITHER
axis, because whether a zip of source EDIs is source or derived is a semantics call this module must
not improvise.

`related_collection_identifiers[]` is the containing-collection hook, and it is projected ONLY from
rows whose ENTITY SCOPE the curation states, because placement verification is mandatory and this
workflow resolves no DOIs. A row carrying no `identifies`, a row that is not a DOI, and a DOI a survey
declares at two different levels are all REFUSED and reported for curation instead: an unplaceable
row would publish a wrong citation claim.

NON-VACUOUS (Invariant 10): every assertion reads a BUILT document, cross-checks its paths against
the build's own manifest.json rather than against the emitter's constants, and validates the result
against the shipped 0.1 schema artifact.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SURVEYS = HERE / "fixtures"                         # vendored, self-contained (as in test_mtcat.py)
SCHEMA = json.loads((ROOT / "schema" / "ausmt-station.schema.json").read_text(encoding="utf-8"))
sys.path.insert(0, str(ROOT / "extract"))
sys.path.insert(0, str(ROOT))
import build_portal as bp  # noqa: E402

pytestmark = pytest.mark.usefixtures()


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    pytest.importorskip("mt_metadata")
    tmp = tmp_path_factory.mktemp("resources")
    out = tmp / "data"
    r = subprocess.run(
        [sys.executable, "-m", "extract.build_portal", "--surveys", str(SURVEYS),
         "--out", str(out), "--bundle-edi", "--no-validate"],
        cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out


def _station(out, slug, station):
    return json.loads((out / "products" / slug / station / "station.json").read_text(encoding="utf-8"))


def _manifest(out):
    return json.loads((out / "manifest.json").read_text(encoding="utf-8"))


# ---- the rows ------------------------------------------------------------------------------------

def test_an_open_station_publishes_its_served_renditions(built):
    """FAILS against the pre-A8 emitter, which published no resources[] at all."""
    doc = _station(built, "example-survey", "EXAMPLE01")
    rows = {r["id"]: r for r in doc["resources"]}
    assert "edi" in rows and "emtfxml" in rows
    assert rows["edi"]["kind"] == "transfer_function" and rows["edi"]["format"] == "edi"
    assert rows["emtfxml"]["format"] == "emtfxml"
    assert all("identifiers" not in r for r in doc["resources"]), \
        "no DOI identifies any exact file AusMT serves today (D3)"


def test_the_role_axes_are_emitted_only_where_they_are_certain(built):
    """The level-2 rule at its default."""
    rows = {r["id"]: r for r in _station(built, "example-survey", "EXAMPLE01")["resources"]}
    assert (rows["edi"]["provenance_role"], rows["edi"]["representation_role"]) == ("source", "original")
    assert (rows["emtfxml"]["provenance_role"],
            rows["emtfxml"]["representation_role"]) == ("derived", "alternate")
    for archive in [r for r in rows.values() if r["kind"] == "archive"]:
        assert "provenance_role" not in archive and "representation_role" not in archive, archive


def test_the_survey_archives_ride_every_station_whose_bytes_are_in_them(built):
    """An archive row is a CONTAINMENT claim, so a bundle rides the stations that actually put bytes
    into it, not every station of its survey. In this all-exact fixture that is every station; the
    Arm in test_station_emission.py is where the two differ."""
    doc = _station(built, "example-survey", "EXAMPLE01")
    archives = [r for r in doc["resources"] if r["kind"] == "archive"]
    assert {r["format"] for r in archives} == {"zip"}
    assert {r["id"] for r in archives} >= {"edi-zip", "xml-zip"}
    served = {r["id"] for r in doc["resources"] if r["kind"] == "transfer_function"}
    assert {"edi", "emtfxml"} <= served, "the two zips are the bundles of exactly these renditions"


def test_every_path_is_the_one_the_manifest_records_for_the_same_bytes(built):
    """The manifest stays the checksum/inventory authority: station.json references its paths and
    never restates a hash or invents a second location for the same file."""
    man = _manifest(built)
    doc = _station(built, "example-survey", "EXAMPLE01")
    by_format = {r["format"]: r for r in man["files"] if r["ausmt_id"] == doc["ausmt_id"]}
    bundles = {r["format"]: r for r in man["bundles"] if r["slug"] == "example-survey"}
    rows = {r["id"]: r for r in doc["resources"]}
    assert rows["edi"]["path"] == by_format["edi"]["url"]
    assert rows["emtfxml"]["path"] == by_format["emtfxml"]["url"]
    assert rows["edi-zip"]["path"] == bundles["edi-zip"]["url"]
    assert all("sha256" not in r and "size" not in r for r in doc["resources"])


def test_the_edi_path_equivalence_pin(built):
    """SCOPE:71-73: distribution.edi_path becomes compatibility-only once resources[] exists, and
    the two must agree for the whole of 1.x. This is the pin that keeps them agreeing."""
    for path in sorted((built / "products").rglob("station.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        edi_rows = [r for r in doc.get("resources", []) if r["id"] == "edi"]
        legacy = (doc.get("distribution") or {}).get("edi_path")
        if legacy:
            assert [r["path"] for r in edi_rows] == [legacy], path
        else:
            assert edi_rows == [], f"{path} advertises an EDI resource its distribution denies"


def test_a_withheld_record_carries_no_resources(built):
    """The withheld branch is closed-world; resources are exactly the detail an embargo withholds."""
    for path in sorted((built / "products").rglob("station.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("withheld"):
            assert "resources" not in doc, path


def test_the_built_document_validates_against_the_shipped_schema(built):
    jsonschema = pytest.importorskip("jsonschema")
    validator = jsonschema.Draft7Validator(SCHEMA, format_checker=jsonschema.FormatChecker())
    for path in sorted((built / "products").rglob("station.json")):
        validator.validate(json.loads(path.read_text(encoding="utf-8")))


# ---- related_collection_identifiers --------------------------------------------------------------

def _placeable(meta):
    return bp.station_collection_identifiers(meta)


def test_a_curated_collection_doi_is_projected_with_its_scope():
    """The AusLAMP SA raw_packed DOI, shared by seven surveys, is the model case: it plainly does
    not identify any one file, and the curation states what it does identify."""
    rows, declined = _placeable({"related_identifiers": [
        {"identifier": "10.25914/bzd5-n780", "identifier_type": "DOI", "identifies": "raw_packed"}]})
    assert rows == [{"scheme": "DOI", "identifier": "10.25914/bzd5-n780", "identifies": "raw_packed"}]
    assert declined == []


def test_a_row_with_no_curated_scope_is_refused():
    """auslamp-nsw-2016-21's publication-record row: a DOI in URL form whose `identifies` is null.
    Nothing states what it identifies, so nothing may place it."""
    rows, declined = _placeable({"related_identifiers": [
        {"identifier": "http://dx.doi.org/10.11636/Record.2020.011", "identifier_type": "DOI"}]})
    assert rows == []
    assert len(declined) == 1 and "identifies" in declined[0]


def test_a_row_whose_scope_names_no_collection_and_no_level_is_refused():
    """auslamp-vic-2013-2018's second row, a GA publication Record DOI carried as `identifies:
    entire`. MTCAT defines `entire` as one record covering all levels: it states the scope of a
    RECORD and asserts no containment, so it names neither a collection nor a product level and
    nothing places it. Without this it rode all four resource rows of all 96 open stations."""
    rows, declined = _placeable({"related_identifiers": [
        {"identifier": "10.11636/Record.2018.021", "identifier_type": "DOI",
         "identifies": "entire"}]})
    assert rows == []
    assert len(declined) == 1 and "entire" in declined[0]


def test_the_placeable_scopes_are_the_collection_and_the_product_levels():
    """The permitted set is derived from the gate 12 crosswalk rather than restated, so a level added
    there cannot be silently unplaceable here."""
    assert bp._PLACEABLE_SCOPES == {"collection", "raw_packed", "level0", "level1", "level2", "level3"}
    assert not (bp._PLACEABLE_SCOPES & {"entire"}), "`entire` states scope, not containment"


def test_a_non_doi_row_is_refused():
    """western-gawler-2023's SARIG rows are identifier_type URL; the DOI placement policy governs
    DOIs, and a landing-page URL is not a collection identifier."""
    rows, declined = _placeable({"related_identifiers": [
        {"identifier": "https://pid.sarig.sa.gov.au/dataset/mesac487", "identifier_type": "URL",
         "identifies": "entire"}]})
    assert rows == [] and len(declined) == 1


def test_a_doi_declared_at_two_levels_is_refused_on_both_rows():
    """auslamp-qld-phase-3 reuses 10.26186/150000 for both raw_packed and level2. The curated scope
    contradicts itself, so neither row is placeable."""
    rows, declined = _placeable({"related_identifiers": [
        {"identifier": "10.26186/150000", "identifier_type": "DOI", "identifies": "raw_packed"},
        {"identifier": "10.26186/150000", "identifier_type": "DOI", "identifies": "level2"}]})
    assert rows == []
    assert len(declined) == 2 and all("two" in d or "level" in d for d in declined)


def test_a_survey_with_no_related_identifiers_projects_nothing():
    rows, declined = _placeable({})
    assert rows == [] and declined == []


# ---- the gate 12 crosswalk -----------------------------------------------------------------------

def test_the_crosswalk_maps_the_station_vocabularies_out_never_in():
    """Gate 12: the clean station vocabularies are crosswalked to NCI's level names and to MTCAT's
    legacy `identifies` values. Direction of dependency: the station concepts are the source and the
    legacy values are the target, so MTCAT's heterogeneous vocabulary is never inherited."""
    table = bp.STATION_VOCABULARY_CROSSWALK
    assert table[("raw", "packed_archive")]["mtcat_identifies"] == "raw_packed"
    assert table[("level2", None)]["nci"] == "level_2"
    assert {k[0] for k in table} <= set(SCHEMA["definitions"]["resource"]["properties"]
                                        ["processing_level"]["enum"])
    assert {k[1] for k in table if k[1]} <= set(SCHEMA["definitions"]["resource"]["properties"]
                                                ["packaging"]["enum"])


def test_the_crosswalk_names_the_legacy_values_it_refuses_to_inherit():
    """`collection` and `entire` are SCOPE, not processing level: mapping them onto a station
    processing_level is exactly the identifies debt the clean vocabularies exist to refuse."""
    assert set(bp.STATION_VOCABULARY_UNMAPPED) == {"collection", "entire"}
    assert not [v for v in bp.STATION_VOCABULARY_CROSSWALK.values()
                if v["mtcat_identifies"] in bp.STATION_VOCABULARY_UNMAPPED]
