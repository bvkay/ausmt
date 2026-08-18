"""MTCAT v1.2: the schema DESCRIBES what the portal serves, and CONSTRAINS it.

v1.1 leaked: creators/contributors, related_identifiers (with their `identifies` level and `resolution`
state), the collection rollup facets (status/start_year/last_updated/description), the collection
bbox/centroid inner keys and the document-level tool versions were all SERVED but rode through
`additionalProperties: true` undescribed, so nothing could be said about their shape and nothing could
catch a bad value. v1.2 types every one of them and adds the purely derived per-survey discovery facets
(n_stations, data_types, period range, tipper count, distributed formats, year range).

This module is deliberately STACK-FREE (no mt_metadata/mth5 importorskip at module level) so the schema
gate still runs on a machine with no ingest stack. It has two halves:

  1. a corpus-shaped document that must VALIDATE. It carries every newly described surface at once,
     which is what makes the RED half below non-vacuous: each mutation differs from a PASSING document
     by exactly the field under test.
  2. the RED proof: one mutation per described field, each of which must FAIL. A schema that merely
     MENTIONED these fields while tolerating any value for them would sail through half 1 and could not
     pass a single case in half 2, which is the point: describing a field and constraining it are not
     the same act, and only the second one catches a bad build.

RED evidence (measured, not asserted): replaying these cases against the v1.1 schema shows 42 of the 45
riding through untouched, because their enclosing objects were `additionalProperties: true` with nothing
said about the key. The remaining 3 (sources as an array, the collection survey count, the portal version
pattern) were already constrained and are kept here as regression guards.

Validation uses the REAL draft-07 validator (jsonschema), the same one the build's product self-check
and scripts/verify.py run, so a case that fails here is a build that fails there. The stdlib mini-checker
in test_mtcat.py covers the no-jsonschema case.
"""
import copy
import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCHEMA = json.loads((ROOT / "schema" / "mtcat.schema.json").read_text(encoding="utf-8"))


def _validator():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft7Validator.check_schema(SCHEMA)   # the schema itself must be legal draft-07
    return jsonschema.Draft7Validator(SCHEMA)


# A corpus-shaped MTCAT 1.2 document: the served surfaces as the real corpus carries them (an open
# survey with credit, typed identifiers and rights blocks; an embargoed survey that honestly distributes
# nothing; a programme collection; the band mix the classifier produces). Values mirror the live
# catalogue's own vocabulary usage rather than being invented for the test.
CORPUS_SHAPED = {
    "portal": {
        "portal_id": "ausmt",
        "portal_name": "AusMT, Australia's Magnetotelluric Data Portal",
        "schema": "mtcat",
        "version": "1.2",
        "schema_url": "mtcat.schema.json",
        "metadata_license": "CC0-1.0",
        "generated_at": "2026-07-28T00:00:00Z",
    },
    "surveys": [
        {
            "survey_id": "auslamp-sa-gawler-2014",
            "title": "AusLAMP South Australia Gawler 2014",
            "organisation": "Geological Survey of South Australia",
            "organisation_ror": "https://ror.org/00892tw58",
            "raid": None,
            "country": "Australia",
            "version": "1.0.0",
            "collection_id": "auslamp",
            "doi": "10.25914/example",
            "license": "CC-BY-4.0",
            "access": "open",
            "bbox": {"west": 133.0, "south": -32.0, "east": 137.0, "north": -29.0},
            "centroid": {"latitude": -30.5, "longitude": 135.0},
            "n_stations": 3,
            "data_types": {"BBMT": 1, "LPMT": 1, "AMT": 1},
            "period_min_s": 0.0005,
            "period_max_s": 12000.0,
            "n_stations_tipper": 2,
            "year_start": 2014,
            "year_end": 2015,
            "creators": [
                {"name": "Kay, Ben", "name_type": "person", "orcid": "0000-0002-9738-7277"},
                {"name": "Geological Survey of South Australia", "name_type": "organisation",
                 "ror": "https://ror.org/00892tw58"},
            ],
            "contributors": [
                {"name": "Thiel, Stephan", "name_type": "person", "role": "ProjectLeader",
                 "orcid": "0000-0002-8678-412X"},
                {"name": "Zonge Engineering", "name_type": "organisation", "role": "DataCollector"},
                {"name": "Kay, Ben", "name_type": "person", "role": "DataCurator"},
                {"name": "AusMT", "name_type": "organisation", "role": "HostingInstitution"},
            ],
            "related_identifiers": [
                {"identifier": "10.25914/bzd5-n780", "identifier_type": "DOI",
                 "relation": "IsDerivedFrom", "custodian": "NCI",
                 "identifies": "raw_packed", "resolution": "ok"},
                {"identifier": "10.25914/parent", "identifier_type": "DOI",
                 "relation": "IsPartOf", "custodian": "NCI",
                 "identifies": "collection", "resolution": "reserved"},
                # a legacy row: no level was stated and no relation was derived, and the resolution cache
                # knows nothing about it, so `identifies`/`resolution` are ABSENT and not null.
                {"identifier": "10.25914/legacy", "identifier_type": "DOI",
                 "relation": None, "custodian": "NCI"},
            ],
            "attribution": {
                "custodian": "Geological Survey of South Australia",
                "statement": "Geological Survey of South Australia (2025)",
                "changes_made": True,
                "changes_summary": "Reprocessed to a common period band.",
                "declared_by": "Ben Kay",
                "declared_date": "2026-07-25",
            },
            "sources": [
                {"title": "AusLAMP SA, NCI archive", "custodian": "Geoscience Australia",
                 "identifier": "10.25914/abc123", "identifier_type": "DOI",
                 "relation": "IsDerivedFrom", "identifies": "raw_packed",
                 "licence": "CC-BY-3.0-AU", "retrieved": "2016-05", "profile": "ga"},
            ],
            "changes": {"made": True, "summary": "Reprocessed to a common period band."},
            "formats": ["edi", "edi-zip", "emtfxml", "mth5", "xml-zip"],
        },
        {
            "survey_id": "embargoed-survey-2025",
            "title": "Embargoed Survey 2025",
            "organisation": "Example University",
            "organisation_ror": None,
            "raid": None,
            "country": "Australia",
            "version": None,
            "collection_id": None,
            "doi": None,
            "license": "CC-BY-4.0",
            "access": "embargoed",
            "embargo_until": "2027-01-01",
            "bbox": {"west": 140.0, "south": -38.0, "east": 141.0, "north": -37.0},
            "centroid": {"latitude": -37.5, "longitude": 140.5},
            "n_stations": 1,
            "data_types": {"GDS": 1},
            "period_min_s": 8.0,
            "period_max_s": 4096.0,
            "n_stations_tipper": 1,
            "year_start": 2025,
            "year_end": 2025,
            "contributors": [
                {"name": "AusMT", "name_type": "organisation", "role": "HostingInstitution"},
            ],
            # discovery is universal, distribution is not: the footprint and the station rows above are
            # public while the bytes are withheld, so `formats` is honestly EMPTY rather than absent.
            "formats": [],
        },
    ],
    "stations": [
        {"station_id": "au.auslamp-sa-gawler-2014.SA084", "survey_id": "auslamp-sa-gawler-2014",
         "latitude": -30.1, "longitude": 135.0, "data_type": "LPMT"},
        {"station_id": "au.auslamp-sa-gawler-2014.SA085", "survey_id": "auslamp-sa-gawler-2014",
         "latitude": -31.0, "longitude": 134.0, "data_type": "BBMT"},
        {"station_id": "au.auslamp-sa-gawler-2014.SA086", "survey_id": "auslamp-sa-gawler-2014",
         "latitude": -29.5, "longitude": 136.5, "data_type": "AMT"},
        {"station_id": "au.embargoed-survey-2025.E01", "survey_id": "embargoed-survey-2025",
         "latitude": -37.5, "longitude": 140.5, "data_type": "GDS"},
    ],
    "collections": [
        {
            "collection_id": "auslamp",
            "title": "AusLAMP",
            "type": "programme",
            "status": "active",
            "start_year": 2013,
            "last_updated": "2026-07-12",
            "description": "Australia's national long-period magnetotelluric programme.",
            "n_surveys": 1,
            "n_stations": 3,
            "bbox": {"west": 133.0, "south": -32.0, "east": 137.0, "north": -29.0},
            "centroid": {"latitude": -30.2, "longitude": 135.166667},
        },
    ],
    "mt_metadata_version": "1.0.9",
    "mth5_version": "0.6.8",
}


def test_schema_self_identifies_as_v12_at_its_served_url():
    """The $id is the URL the schema is ACTUALLY served from. v1.1 pointed $id at ausmt.org, a domain
    AusMT does not own, so the canonical identifier of the published schema was unresolvable by anyone
    who tried to dereference it. Owner ruling: the identifier is the served location.

    Identifier migration (owner ruling 2026-08-18): the served location moved from ausmt.au to the
    canonical ausmt.auscope.org.au, and the $id moved WITH it, in the demo phase, while no DOI is
    minted and no external consumer of the v1.2 $id exists; the old URL keeps resolving through the
    permanent legacy 301. The version did NOT bump: v1.2 stays v1.2, because nothing but the
    identifier changed (see docs/docs/reference/mtcat-schema.md, "Identifier migration note").

    The "1.2" literals here are DELIBERATE and are not the hardcoded-default class that
    test_mtcat_version_parity.py eliminates: this module is the v1.2 acceptance suite (its corpus
    document, its 45 RED mutations and these assertions are all written against that release), so it
    pins its own subject and is meant to fail loudly at the next bump so somebody decides what happens
    to it. The MOVING version, the one every emitter and config derives, lives in the schema title and
    is pinned across every surface by test_mtcat_version_parity.py. Do not "fix" these into a read of
    the title: a suite that reads its subject's version from its subject asserts nothing."""
    assert SCHEMA["$id"] == "https://ausmt.auscope.org.au/data/mtcat.schema.json"
    assert SCHEMA["title"].startswith("MTCAT v1.2:")
    assert "1.2" in SCHEMA["description"]
    # the deliberate openness posture must be STATED, not left for a reader to infer from the keywords
    assert SCHEMA["additionalProperties"] is True
    assert "$comment" in SCHEMA and "additionalproperties" in SCHEMA["$comment"].lower()


def test_corpus_shaped_document_validates():
    """The GREEN half. Every newly described surface at once: both credit lists (with the export-only
    HostingInstitution row), typed related_identifiers including a level, a resolution state and a
    legacy row that declares neither, the rights blocks, the derived facets, an honestly empty formats
    list on the embargoed survey, and a fully typed collection rollup."""
    errs = sorted(_validator().iter_errors(CORPUS_SHAPED), key=lambda e: list(e.path))
    assert not errs, "\n".join(f"{list(e.path)}: {e.message}" for e in errs)


def test_the_schema_never_forces_a_value_the_producer_does_not_have():
    """The other half of honesty. Tightening the types must not make the schema demand a number where
    the build genuinely has none: a survey whose stations report no period range, an unlocated station,
    a survey with no declared dates, a collection with no located member, a build with no ingest stack.
    Every one of those must still validate as null (or empty), so the producer is never pushed into
    inventing a value to stay conformant."""
    doc = copy.deepcopy(CORPUS_SHAPED)
    doc["surveys"][0]["period_min_s"] = doc["surveys"][0]["period_max_s"] = None
    doc["surveys"][0]["data_types"] = {}
    doc["surveys"][0]["year_start"] = doc["surveys"][0]["year_end"] = None
    doc["surveys"][0]["n_stations"] = 0
    doc["surveys"][0]["n_stations_tipper"] = 0
    doc["surveys"][0]["formats"] = []
    doc["stations"][0]["latitude"] = doc["stations"][0]["longitude"] = None
    doc["collections"][0]["bbox"] = doc["collections"][0]["centroid"] = None
    doc["collections"][0]["start_year"] = doc["collections"][0]["last_updated"] = None
    doc["collections"][0]["status"] = doc["collections"][0]["description"] = None
    doc["mt_metadata_version"] = doc["mth5_version"] = None
    errs = sorted(_validator().iter_errors(doc), key=lambda e: list(e.path))
    assert not errs, "\n".join(f"{list(e.path)}: {e.message}" for e in errs)


_DELETE = object()   # sentinel: "remove this key" rather than "set it to something wrong"


def _mutate(path, value):
    """A copy of the corpus-shaped document with ONE value replaced. `path` is a sequence of keys and
    indexes; the sentinel _DELETE removes the key instead."""
    doc = copy.deepcopy(CORPUS_SHAPED)
    node = doc
    for step in path[:-1]:
        node = node[step]
    if value is _DELETE:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return doc


# One mutation per described field. Each is a value v1.1 accepted in silence (its enclosing object was
# `additionalProperties: true` with nothing said about the key) and v1.2 must reject. The `why` text is
# the harm the constraint prevents, not a restatement of the type.
RED_CASES = [
    # ---- the MTCAT 1.2 derived discovery facets -------------------------------------------------
    (("surveys", 0, "n_stations"), "3",
     "a stringified count silently breaks any consumer that sums or sorts on survey size"),
    (("surveys", 0, "n_stations"), -1,
     "a negative station count is not a count"),
    (("surveys", 0, "data_types"), {"BBMT": "1"},
     "a stringified band count breaks the same arithmetic one level down"),
    (("surveys", 0, "data_types"), {"XBMT": 1},
     "an out-of-vocabulary band would invent a data type no consumer can map"),
    (("surveys", 0, "data_types"), ["BBMT"],
     "the band mix is a map of counts, not a bare list of bands"),
    (("surveys", 0, "period_min_s"), "0.0005",
     "a stringified period cannot be range-filtered; the discovery facet exists to be filtered on"),
    (("surveys", 0, "period_max_s"), 0,
     "a period of zero seconds is not physical"),
    (("surveys", 0, "n_stations_tipper"), -1,
     "a negative tipper count is not a count"),
    (("surveys", 0, "formats"), ["pdf"],
     "an unknown format token would advertise a distribution AusMT does not produce"),
    (("surveys", 0, "formats"), "edi",
     "a bare string would be read character by character by a consumer expecting a list"),
    (("surveys", 0, "formats"), ["edi", "edi"],
     "formats is the SET of what is distributed; a repeat would read as a tally it is not"),
    (("surveys", 0, "year_start"), "2014",
     "a stringified year cannot be range-filtered, which is the only reason the facet exists"),
    (("surveys", 0, "year_end"), 2014.5,
     "a fractional year is not a year"),
    (("surveys", 1, "embargo_until"), 20270101,
     "an integer date is not an ISO date and would silently sort against strings elsewhere"),
    # ---- the credit surface (served since the credit model, described only now) ------------------
    (("surveys", 0, "contributors", 0, "role"), "Chief",
     "an out-of-vocabulary role publishes a WRONG provenance claim about who did what"),
    (("surveys", 0, "contributors", 0, "name_type"), "human",
     "a mis-typed name_type mis-classifies the actor and mis-renders the citation"),
    (("surveys", 0, "contributors", 0, "name"), "",
     "a nameless contributor credits nobody"),
    (("surveys", 0, "creators", 0, "name_type"), "Person",
     "the vocabulary is case-sensitive; 'Person' is not 'person'"),
    (("surveys", 0, "creators", 0, "orcid"), 12345,
     "a numeric ORCID is not an ORCID"),
    (("surveys", 0, "creators", 0, "name"), _DELETE,
     "a creator row with no name cannot be an author of anything"),
    (("surveys", 0, "creators"), {"name": "Kay, Ben"},
     "creators is an ORDERED list; a bare object destroys the citation author order"),
    # ---- the typed identifiers surface ----------------------------------------------------------
    (("surveys", 0, "related_identifiers", 0, "identifies"), "level9",
     "an out-of-vocabulary data level mislabels WHAT the identifier points at"),
    (("surveys", 0, "related_identifiers", 0, "identifies"), None,
     "unknown level is expressed by OMITTING the key; an explicit null claims a level called null"),
    (("surveys", 0, "related_identifiers", 0, "relation"), "IsFriendOf",
     "an out-of-vocabulary relation publishes a WRONG provenance claim"),
    (("surveys", 0, "related_identifiers", 0, "identifier_type"), "ARK",
     "an identifier type AusMT does not record cannot be resolved by a harvester"),
    (("surveys", 0, "related_identifiers", 0, "resolution"), "unknown",
     "unknown resolution is expressed by OMITTING the key, never by a third token"),
    (("surveys", 0, "related_identifiers", 0, "resolution"), None,
     "same: null is not a resolution state"),
    # ---- the rights blocks (carried opaquely by v1.1, typed by v1.2) ----------------------------
    (("surveys", 0, "attribution", "changes_made"), "yes",
     "a stringy boolean makes the CC-BY changes-made flag truthy in every language that has truthiness"),
    (("surveys", 0, "changes", "made"), "true",
     "same flag, same harm, in the normalised descriptor"),
    (("surveys", 0, "sources", 0, "licence"), 4,
     "a numeric licence identifies no licence"),
    (("surveys", 0, "sources", 0, "relation"), "IsFriendOf",
     "the source rows carry the same ratified relation vocabulary as related_identifiers"),
    (("surveys", 0, "sources"), {"title": "one source"},
     "sources is a list of obtained datasets, not a single object"),
    # ---- stations -------------------------------------------------------------------------------
    (("stations", 0, "data_type"), "XYZ",
     "an out-of-vocabulary band was accepted by v1.1's bare `string`; the band drives every filter"),
    (("stations", 0, "data_type"), "bbmt",
     "the band vocabulary is case-sensitive"),
    (("stations", 0, "latitude"), -95.0,
     "a latitude beyond the poles is a parsing bug reaching the map"),
    (("stations", 0, "longitude"), 200.0,
     "same, for longitude"),
    # ---- collections (rollup facets and the untyped bbox/centroid v1.1 left bare) ---------------
    (("collections", 0, "bbox"), {"west": "133.0", "south": -32.0, "east": 137.0, "north": -29.0},
     "v1.1 typed collections bbox as a bare object, so a stringified corner rode straight through"),
    (("collections", 0, "bbox"), {"west": 133.0, "south": -32.0, "east": 137.0},
     "a bbox missing a corner is not a bbox; v1.1 could not say so"),
    (("collections", 0, "centroid"), {"latitude": -30.2},
     "a centroid with no longitude is not a position"),
    (("collections", 0, "start_year"), "2013",
     "a stringified programme start year cannot be compared with a survey year_start"),
    (("collections", 0, "n_surveys"), "1",
     "a stringified rollup count breaks the same arithmetic as n_stations"),
    (("collections", 0, "last_updated"), 20260712,
     "an integer date is not an ISO date"),
    # ---- document level -------------------------------------------------------------------------
    (("mt_metadata_version",), 1.09,
     "a float version number loses the patch component: 1.0.9 is not 1.09"),
    (("mth5_version",), 0.68,
     "same for the mth5 pin"),
    (("portal", "version"), "1.2.0",
     "the portal version is MAJOR.MINOR by contract; a three-part version breaks the pattern"),
]


# The _DELETE sentinel needs an EXPLICIT id: repr(object()) embeds the process-local memory address,
# and pytest-xdist refuses to run when workers collect different test ids (each worker is its own
# process, so the address, and with it the generated id, differed per worker). A stable "<DELETE>"
# keeps every id deterministic; all other cases keep their repr-derived id, truncated as before.
@pytest.mark.parametrize(("path", "value", "why"), RED_CASES,
                         ids=[".".join(str(p) for p in c[0])
                              + ("=<DELETE>" if c[1] is _DELETE else f"={c[1]!r}"[:40])
                              for c in RED_CASES])
def test_red_wrong_value_fails_validation(path, value, why):
    """RED proof: the described fields CONSTRAIN, they do not merely document. Every case here rode
    through v1.1 untouched (the enclosing objects are all additionalProperties:true), so each assertion
    below fails against the previous schema and passes only because v1.2 typed that field."""
    v = _validator()
    doc = _mutate(path, value)
    errs = list(v.iter_errors(doc))
    assert errs, f"{'.'.join(str(p) for p in path)} = {value!r} MUST fail validation: {why}"
    # and the failure must be AT the mutated field, not incidental damage somewhere else
    assert any(list(e.path)[:len(path)] == list(path) or list(e.path) == list(path[:-1])
               for e in errs), \
        f"expected an error at {list(path)}, got {[list(e.path) for e in errs]}"


def test_red_cases_are_non_vacuous():
    """Guard on the guard: every RED case must differ from the PASSING document by exactly one value,
    so a case can never 'fail' because the baseline was broken all along."""
    v = _validator()
    assert not list(v.iter_errors(CORPUS_SHAPED)), "the baseline document must validate"
    for path, value, _why in RED_CASES:
        doc = _mutate(path, value)
        node, base = doc, CORPUS_SHAPED
        for step in path[:-1]:
            node, base = node[step], base[step]
        if value is _DELETE:
            assert path[-1] in base and path[-1] not in node, f"{path}: nothing was actually deleted"
        else:
            assert node[path[-1]] is value or node[path[-1]] == value, f"{path}: nothing was set"
            assert node[path[-1]] != base[path[-1]], f"{path}: the mutation equals the baseline value"


# --- the emitter side: the derived facets must be DERIVED, not declared ---------------------------

def _bp():
    sys.path.insert(0, str(ROOT / "extract"))
    import build_portal as bp
    return bp


def _station(survey, sid, lat, lon, typ, pmin, pmax, comps):
    return (Path(f"{sid}.edi"),
            {"survey": survey, "ausmt_id": f"au.{survey.lower().replace(' ', '-')}.{sid}", "id": sid,
             "lat": lat, "lon": lon, "type": typ,
             "period_min_s": pmin, "period_max_s": pmax, "comps": comps})


def test_derived_facets_come_from_the_stations_not_the_metadata():
    """n_stations / data_types / period range / tipper count are DERIVED in the walk mtcat_document was
    already doing. The survey metadata here declares NONE of them, so a value that appears can only have
    come from the station rows. Mixed bands, a mixed tipper population and a widened period range across
    stations are all exercised at once."""
    bp = _bp()
    stations = [
        _station("S", "A1", -30.0, 137.0, "BBMT", 0.01, 1000.0, "ZT"),
        _station("S", "A2", -31.0, 138.0, "BBMT", 0.005, 500.0, "Z"),
        _station("S", "A3", -32.0, 139.0, "LPMT", 8.0, 12000.0, "ZT"),
        _station("S", "A4", -33.0, 140.0, "AMT", 0.0005, 10.0, "Z"),
    ]
    meta = {"S": {"org": "Org", "access": "open", "year_start": 2014, "year_end": 2016}}
    e = bp.mtcat_document(meta, stations, generated_at="2026-01-01T00:00:00Z")["surveys"][0]
    assert e["n_stations"] == 4
    # canonical band order, and the counts are per-station tallies
    assert e["data_types"] == {"BBMT": 2, "LPMT": 1, "AMT": 1}
    assert list(e["data_types"]) == ["BBMT", "LPMT", "AMT"], "canonical band order is load-bearing"
    assert e["period_min_s"] == 0.0005 and e["period_max_s"] == 12000.0
    assert e["n_stations_tipper"] == 2, "only the two 'ZT' stations carry a tipper"
    assert e["year_start"] == 2014 and e["year_end"] == 2016
    # and the derived counts must agree with the station rows the same document serves
    doc = bp.mtcat_document(meta, stations, generated_at="2026-01-01T00:00:00Z")
    assert e["n_stations"] == len([s for s in doc["stations"] if s["survey_id"] == e["survey_id"]])


def test_derived_facets_are_honest_when_there_is_nothing_to_derive():
    """A station with no period range must not fabricate one, and a band the canonical order does not
    name must still be counted rather than dropped."""
    bp = _bp()
    stations = [_station("S", "A1", -30.0, 137.0, "unknown", None, None, "")]
    e = bp.mtcat_document({"S": {"org": "Org", "access": "open"}}, stations,
                          generated_at="2026-01-01T00:00:00Z")["surveys"][0]
    assert e["n_stations"] == 1
    assert e["data_types"] == {"unknown": 1}, "an unnamed band is counted, never silently dropped"
    assert e["period_min_s"] is None and e["period_max_s"] is None
    assert e["n_stations_tipper"] == 0
    assert e["year_start"] is None and e["year_end"] is None


def test_formats_are_read_off_the_manifest_and_are_empty_for_a_withheld_survey():
    """`formats` is derived from the download manifest, the one authority on what is distributed. The
    access/licence gate writes NO manifest row for a withheld survey, so its format list comes out empty
    by construction: there is no second withholding rule here that could drift out of step."""
    bp = _bp()
    stations = [_station("Open", "A1", -30.0, 137.0, "BBMT", 0.01, 100.0, "ZT"),
                _station("Held", "B1", -35.0, 140.0, "LPMT", 8.0, 4096.0, "Z")]
    meta = {"Open": {"org": "Org", "access": "open"},
            "Held": {"org": "Org", "access": "embargoed", "embargo_until": "2027-01-01"}}
    manifest = {"files": [{"survey": "Open", "format": "edi"}, {"survey": "Open", "format": "emtfxml"}],
                "bundles": [{"survey": "Open", "format": "edi-zip"},
                            {"survey": "Open", "format": "mth5"}]}
    by_id = {s["survey_id"]: s for s in bp.mtcat_document(
        meta, stations, generated_at="2026-01-01T00:00:00Z", manifest_doc=manifest)["surveys"]}
    assert by_id["open"]["formats"] == ["edi", "edi-zip", "emtfxml", "mth5"]
    assert by_id["held"]["formats"] == [], "a withheld survey distributes nothing, and says so"
    assert by_id["held"]["embargo_until"] == "2027-01-01"
    assert by_id["open"]["n_stations"] == 1, "discovery stays universal even where bytes are withheld"
    assert "embargo_until" not in by_id["open"]


def test_formats_absence_is_documented_as_a_foreign_producer_case_not_an_ausmt_one():
    """The `formats` key has TWO honest states and the schema must not confuse them.

      * EMPTY  = this build distributes nothing for this survey. True of a withheld survey, and equally
        true of a build run with no distribution flags, where the manifest is written but carries zero
        rows. It is a statement about the build, never 'unknown'.
      * ABSENT = the producer had no manifest at all, so it cannot say (proved separately by
        test_formats_key_is_omitted_when_there_is_no_manifest_to_derive_from). Reachable through the
        public mtcat_document() signature, whose manifest_doc defaults to None, but NOT through AusMT's
        own build: main() writes the manifest first and always passes it, so an AusMT document always
        carries the key. The schema now says exactly that, rather than implying AusMT ever omits it.

    Fix round. The description previously said only 'absent when the producer had no manifest', which read
    as a state an AusMT consumer might meet. It cannot: a build with every distribution flag off emits
    `formats: []` for all 21 surveys, and a consumer must read that as 'nothing distributed', not 'unknown'."""
    bp = _bp()
    stations = [_station("S", "A1", -30.0, 137.0, "BBMT", 0.01, 100.0, "ZT")]
    meta = {"S": {"org": "Org", "access": "open"}}
    # a manifest that exists but distributes nothing: a build run with no --bundle-edi / --survey-h5,
    # which is what main() hands over when every distribution flag is off. The key must still be there.
    e = bp.mtcat_document(meta, stations, generated_at="2026-01-01T00:00:00Z",
                          manifest_doc={"generated_count": 0, "files": [], "bundles": []})["surveys"][0]
    assert e["formats"] == [], "an empty manifest means nothing distributed, and the key stays present"
    desc = SCHEMA["properties"]["surveys"]["items"]["properties"]["formats"]["description"]
    assert "ALWAYS PRESENT" in desc, (
        "the schema must state that an AusMT document always carries formats, so a consumer does not "
        "write an absence branch it will never reach")
    assert "never means 'unknown'" in desc, (
        "the schema must state that an EMPTY list is a fact about the build, not a missing value")


def test_access_description_names_no_phantom_level():
    """The schema is SERVED, so a wrong sentence in it is a published wrong claim.

    Its description of surveys[].access used to say AusMT emits "open, metadata_only, embargoed or
    legacy". There is no `legacy` level and there never was: ACCESS_LEVELS is a three-value tuple, shared
    by the emitter, gateway/editor_form.py and the surveys validator, and a value outside it fails closed.
    The phantom also survived in two stale comments (build_portal.py's SMETA line and drawer.js's C1b
    note), which is where the schema text came from.

    Two halves. The first is SET-FOR-SET against the producer, in both directions, so an added level that
    goes undocumented fails here just as loudly as a documented one that does not exist. The second scans
    EVERY description in the schema for the phantom token, because the wrong claim survived in three
    separate places at once and the next one will too."""
    bp = _bp()
    real = set(bp.ACCESS_LEVELS)
    assert real == {"open", "metadata_only", "embargoed"}, f"ACCESS_LEVELS moved: {sorted(real)}"

    desc = SCHEMA["properties"]["surveys"]["items"]["properties"]["access"]["description"]
    m = re.search(r"AusMT emits exactly one of ([^.(]+)", desc)
    assert m, ("the access description must enumerate what the producer emits in the form "
               f"'AusMT emits exactly one of ...', so this test can compare it. Got: {desc}")
    named = {t.strip() for t in re.split(r",|\bor\b", m.group(1)) if t.strip()}
    assert named == real, (
        "the documented access levels must equal the producer's ACCESS_LEVELS exactly.\n"
        f"  documented not emitted: {sorted(named - real)}\n"
        f"  emitted not documented: {sorted(real - named)}")

    def _descriptions(node):
        if isinstance(node, dict):
            d = node.get("description")
            if isinstance(d, str):
                yield d
            for v in node.values():
                yield from _descriptions(v)
        elif isinstance(node, list):
            for v in node:
                yield from _descriptions(v)

    for d in _descriptions(SCHEMA):
        if "access level" not in d and "ACCESS_LEVELS" not in d:
            continue
        assert "legacy" not in d, (
            "a schema description names a 'legacy' access level; no such level exists and a value "
            f"outside ACCESS_LEVELS fails closed.\n  in: {d}")


def test_formats_key_is_omitted_when_there_is_no_manifest_to_derive_from():
    """Unknown must not be served as empty. Without a manifest the producer cannot know what is
    distributed, so it omits the key rather than claiming nothing is."""
    bp = _bp()
    stations = [_station("S", "A1", -30.0, 137.0, "BBMT", 0.01, 100.0, "Z")]
    e = bp.mtcat_document({"S": {"org": "Org", "access": "open"}}, stations,
                          generated_at="2026-01-01T00:00:00Z")["surveys"][0]
    assert "formats" not in e


def test_self_check_validates_the_bytes_that_ship_not_the_object_in_memory():
    """LAYER 3 of the unquoted-date bug family (LAYERS 1 and 2 are in test_json_date_robustness.py).

    PyYAML implicit-types a bare ISO date, so a survey.yaml carrying `declared_date: 2026-07-25`
    unquoted puts a datetime.date into the attribution block, which SMETA and mtcat_document pass
    through VERBATIM. _jdump's default hook ISO-formats it on the way out, so the SERVED mtcat.json
    holds the string "2026-07-25" and is perfectly conformant. The build's product self-check, however,
    validated the IN-MEMORY object, where the value is still a datetime.date, so the moment v1.2 typed
    declared_date the real corpus failed its own gate over a file that was correct on disk. Serialising
    first makes the gate read what is actually published.

    RED before the fix: the real corpus build exited 2 with
    "mtcat.json: datetime.date(2026, 7, 25) is not of type 'string', 'null'"."""
    bp = _bp()
    pytest.importorskip("jsonschema")
    import datetime
    doc = copy.deepcopy(CORPUS_SHAPED)
    doc["surveys"][0]["attribution"]["declared_date"] = datetime.date(2026, 7, 25)
    assert not bp._validate_products(doc, {"generated_count": 0, "files": [], "bundles": []}), \
        "a date the serialiser turns into a conformant ISO string must not fail the self-check"
    # and the gate must still BITE on a value that is wrong in the served bytes too
    bad = copy.deepcopy(CORPUS_SHAPED)
    bad["surveys"][0]["attribution"]["declared_date"] = 20260725
    errs = bp._validate_products(bad, {"generated_count": 0, "files": [], "bundles": []})
    assert errs and "declared_date" in errs[0], errs


def test_emitted_document_validates_against_the_v12_schema():
    """The emitter and the schema agree: a document built by mtcat_document with every derived facet
    populated passes the REAL validator, which is the same gate the build's product self-check runs."""
    bp = _bp()
    stations = [_station("S", "A1", -30.0, 137.0, "BBMT", 0.01, 1000.0, "ZT"),
                _station("S", "A2", -31.0, 138.0, "GDS", 8.0, 4096.0, "T")]
    meta = {"S": {"org": "Org", "access": "open", "year_start": 2014, "year_end": 2014,
                  "creators": [{"name": "Kay, Ben", "name_type": "person",
                                "orcid": "0000-0002-9738-7277"}],
                  "contributors": [{"name": "Thiel, Stephan", "name_type": "person",
                                    "role": "ProjectLeader"}],
                  "related_identifiers": [{"identifier": "10.25914/x", "identifier_type": "DOI",
                                           "relation": "IsDerivedFrom", "custodian": "NCI",
                                           "identifies": "raw_packed", "resolution": "ok"}]}}
    doc = bp.mtcat_document(meta, stations, generated_at="2026-01-01T00:00:00Z",
                            manifest_doc={"files": [{"survey": "S", "format": "edi"}], "bundles": []},
                            lib_vers={"mt_metadata": "1.0.9", "mth5": "0.6.8"})
    errs = sorted(_validator().iter_errors(doc), key=lambda e: list(e.path))
    assert not errs, "\n".join(f"{list(e.path)}: {e.message}" for e in errs)
    assert doc["portal"]["version"] == "1.2"
    s = doc["surveys"][0]
    assert s["contributors"][-1]["role"] == "HostingInstitution", "the export row still rides last"
    assert s["data_types"] == {"BBMT": 1, "GDS": 1}
