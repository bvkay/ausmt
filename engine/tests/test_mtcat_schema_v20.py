"""MTCAT 2.0: the schema DESCRIBES what the portal serves, and CONSTRAINS it.

Successor to the retired v1.2 acceptance module. MTCAT 2.0 is a MAJOR version; its breaking list is small and
deliberate: null-as-undeclared removed (one defined null: the paired withheld station
coordinates), the empty-array state for formats removed (minItems 1), sources[]/changes removed,
and the top-level library-version keys removed. 2.0 also adds description, subjects[],
sample_rates_hz[], coordinates_state, and the (defined, deliberately unemitted-today)
has_time_series / n_stations_time_series_verified pair.

Two halves, as before:

  1. a corpus-shaped 2.0 document that must VALIDATE, carrying every described surface at once,
     which is what makes the RED half non-vacuous: each mutation differs from a PASSING document
     by exactly the field under test.
  2. the RED proof: one mutation per constraint, each of which must FAIL. Describing a field and
     constraining it are not the same act, and only the second one catches a bad build.

The RED set keeps every 1.2-era case whose constraint survives into 2.0 and adds the 2.0 cases
from the executable fixture suite: subject rows
without a scheme, duplicate/empty/non-positive sample rates, has_time_series false, unknown
coordinates_state, the withheld-footprint leak, empty formats/subjects arrays, identifier-less
relationship rows, half-null coordinate pairs, and a malformed generated_at (which requires
FORMAT CHECKING to be genuinely on - rfc3339-validator is a dev dependency exactly so that case
can never pass vacuously).

This module is deliberately STACK-FREE at module level so the schema gate still runs on a machine
with no ingest stack. Validation uses the REAL draft-07 validator (jsonschema) with format
checking enabled, the same gate the build's product self-check and scripts/verify.py run.
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
# The version the schema's title displays (the display of the single-source constant; the full
# cross-surface pin lives in test_mtcat_version_parity.py).
SCHEMA_VERSION = re.match(r"^MTCAT v(\d+\.\d+):", SCHEMA["title"]).group(1)


def _validator():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft7Validator.check_schema(SCHEMA)   # the schema itself must be legal draft-07
    fc = jsonschema.FormatChecker()
    assert "date-time" in fc.checkers, (
        "format checking for date-time is not active (install rfc3339-validator, a declared dev "
        "dependency); without it the generated_at RED case would pass vacuously")
    return jsonschema.Draft7Validator(SCHEMA, format_checker=fc)


# A corpus-shaped MTCAT 2.0 document: the served surfaces as the real corpus carries them under
# the 2.0 emitter (omit-when-undeclared throughout; an open survey with credit, typed identifiers,
# a rights block and the new 2.0 facets; an embargoed survey that OMITS formats; a programme
# collection). Values mirror the live catalogue's own vocabulary usage rather than being invented.
CORPUS_SHAPED = {
    "portal": {
        "portal_id": "ausmt",
        "portal_name": "AusMT, Australia's Magnetotelluric Data Portal",
        "schema": "mtcat",
        "version": SCHEMA_VERSION,
        "schema_url": "mtcat.schema.json",
        "metadata_license": "CC0-1.0",
        "generated_at": "2026-08-21T00:00:00Z",
    },
    "surveys": [
        {
            "survey_id": "auslamp-sa-gawler-2014",
            "title": "AusLAMP South Australia Gawler 2014",
            "organisation": "Geological Survey of South Australia",
            "organisation_ror": "https://ror.org/00892tw58",
            "country": "Australia",
            "version": "1.0.0",
            "collection_id": "auslamp",
            "doi": "10.25914/example",
            "license": "CC-BY-4.0",
            "access": "open",
            "coordinates_state": "exact",
            "bbox": {"west": 133.0, "south": -32.0, "east": 137.0, "north": -29.0},
            "centroid": {"latitude": -30.5, "longitude": 135.0},
            "n_stations": 3,
            "data_types": {"BBMT": 1, "LPMT": 1, "AMT": 1},
            "period_min_s": 0.0005,
            "period_max_s": 12000.0,
            "n_stations_tipper": 2,
            "year_start": 2014,
            "year_end": 2015,
            "description": "Long-period magnetotelluric survey over the Gawler Craton.",
            "subjects": [
                {"code": "370602", "scheme": "ANZSRC-FoR-2020",
                 "label": "Electrical and electromagnetic methods in geophysics",
                 "uri": "https://linked.data.gov.au/def/anzsrc-for/2020/370602"},
            ],
            "sample_rates_hz": [10, 150, 24000],
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
                # an activity-scope documentation row (ANSIR project record): IsDocumentedBy is
                # in-vocabulary and documents the activity, not the data bytes
                {"identifier": "https://www.auscope.org.au/ansir-projects?id=ANSIR-2022-001",
                 "identifier_type": "URL", "relation": "IsDocumentedBy", "custodian": "AuScope"},
                # a legacy row: no level stated, no relation derived, resolution unknown - each is
                # expressed by ABSENCE (2.0 removed null-as-undeclared from relationship rows too).
                {"identifier": "10.25914/legacy", "identifier_type": "DOI", "custodian": "NCI"},
            ],
            "attribution": {
                "custodian": "Geological Survey of South Australia",
                "statement": "Geological Survey of South Australia (2025)",
                "changes_made": True,
                "changes_summary": "Reprocessed to a common period band.",
                "declared_by": "Ben Kay",
                "declared_date": "2026-07-25",
            },
            "formats": ["edi", "edi-zip", "emtfxml", "mth5", "xml-zip"],
        },
        {
            "survey_id": "embargoed-survey-2025",
            "title": "Embargoed Survey 2025",
            "organisation": "Example University",
            "country": "Australia",
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
            # discovery is universal, distribution is not: the footprint and station rows are
            # Public while the bytes are withheld. 2.0 OMITS formats here: an
            # empty list would falsely assert that no formats are KNOWN for the withheld holdings.
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
         "latitude": -37.5, "longitude": 140.5, "data_type": "GDS",
         "has_time_series": True},
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
}


def test_schema_self_identifies_as_the_versioned_immutable_uri():
    """The $id policy (final walk-through s49): the canonical identifier is the
    VERSION-SPECIFIC immutable URI under /data/schemas/mtcat/<version>/; the unversioned
    /data/mtcat.schema.json remains the latest-convenience route (portal.schema_url still names
    it, and the build serves BOTH). This supersedes the 1.2-era unversioned-$id rule; the pin
    that forbade a versioned $id requires it."""
    want = f"https://ausmt.auscope.org.au/data/schemas/mtcat/{SCHEMA_VERSION}/mtcat.schema.json"
    assert SCHEMA["$id"] == want, f"$id must be the versioned immutable URI {want}; got {SCHEMA['$id']}"
    assert SCHEMA["title"].startswith(f"MTCAT v{SCHEMA_VERSION}:")
    # the deliberate openness posture survives 2.0 (record objects stay additionalProperties:true)
    assert SCHEMA["additionalProperties"] is True


def test_no_version_string_in_any_field_description():
    """The editorial gate: ZERO version strings in field descriptions (the schema text
    must be timeless; the version lives in the title/$id alone)."""
    offenders = []

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "description" and isinstance(v, str) and re.search(r"v?\d+\.\d+", v):
                    offenders.append((path, v[:80]))
                else:
                    walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(SCHEMA.get("properties", {}), "$")
    assert not offenders, f"field descriptions must carry no version strings: {offenders}"


def test_corpus_shaped_document_validates():
    """The GREEN half: every described 2.0 surface at once, format checking on."""
    errs = sorted(_validator().iter_errors(CORPUS_SHAPED), key=lambda e: list(e.path))
    assert not errs, "\n".join(f"{list(e.path)}: {e.message}" for e in errs)


def test_the_schema_never_forces_a_value_the_producer_does_not_have():
    """Honesty under 2.0's omit-when-undeclared: a producer with nothing to say OMITS the key and
    must stay conformant - no facet is required into existence. The one defined null (the paired
    withheld station position) also validates."""
    doc = copy.deepcopy(CORPUS_SHAPED)
    s = doc["surveys"][0]
    for k in ("period_min_s", "period_max_s", "data_types", "year_start", "year_end", "formats",
              "description", "subjects", "sample_rates_hz", "coordinates_state", "bbox",
              "centroid", "doi", "organisation_ror", "version", "collection_id"):
        s.pop(k, None)
    doc["stations"][0]["latitude"] = doc["stations"][0]["longitude"] = None
    c = doc["collections"][0]
    for k in ("bbox", "centroid", "start_year", "last_updated", "status", "description"):
        c.pop(k, None)
    errs = sorted(_validator().iter_errors(doc), key=lambda e: list(e.path))
    assert not errs, "\n".join(f"{list(e.path)}: {e.message}" for e in errs)


_DELETE = object()   # sentinel: "remove this key" rather than "set it to something wrong"


def _mutate(path, value):
    doc = copy.deepcopy(CORPUS_SHAPED)
    node = doc
    for step in path[:-1]:
        node = node[step]
    if value is _DELETE:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return doc


# One mutation per constraint. The 1.2-era cases whose constraints survive are kept; the 2.0 cases
# are ported from the fixture suite (and friends).
RED_CASES = [
    # ---- derived discovery facets ---------------------------------------------------------------
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
    (("surveys", 0, "data_types"), {},
     "2.0 forbids the empty-object state: no band mix means NO key (minProperties 1)"),
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
    (("surveys", 0, "formats"), [],
     "T10b: 2.0 removed the empty-array state entirely (omission enforced, minItems 1)"),
    (("surveys", 0, "year_start"), "2014",
     "a stringified year cannot be range-filtered, which is the only reason the facet exists"),
    (("surveys", 0, "year_end"), 2014.5,
     "a fractional year is not a year"),
    (("surveys", 1, "embargo_until"), 20270101,
     "an integer date is not an ISO date and would silently sort against strings elsewhere"),
    (("surveys", 1, "embargo_until"), "not-a-date",
     "format checking is ON: a non-ISO embargo date must fail, not ride through as a string"),
    # ---- the 2.0 additions ----------------------------------------------------------------------
    (("surveys", 0, "subjects", 0, "scheme"), _DELETE,
     "T5: a subject row without an explicit scheme is uninterpretable across producers"),
    (("surveys", 0, "subjects", 0, "code"), "",
     "an empty code classifies nothing"),
    (("surveys", 0, "subjects"), [],
     "T30a: 2.0 forbids the empty-array state for subjects (absence means no assertion)"),
    (("surveys", 0, "sample_rates_hz"), [10, 10, 150],
     "T6: sample rates are the SET of acquisition modes (uniqueItems)"),
    (("surveys", 0, "sample_rates_hz"), [],
     "an empty rates list is forbidden: nothing known means NO key"),
    (("surveys", 0, "sample_rates_hz"), [0],
     "a zero rate is not a rate (exclusiveMinimum 0)"),
    (("surveys", 0, "sample_rates_hz"), ["150"],
     "a stringified rate cannot be filtered numerically"),
    (("surveys", 0, "coordinates_state"), "fuzzy",
     "T10: an out-of-vocabulary coordinates_state makes an unparseable disclosure claim"),
    (("surveys", 0, "n_stations_time_series_verified"), -1,
     "a negative verified count is not a count"),
    (("surveys", 0, "description"), 42,
     "a non-string description is not discovery text"),
    (("stations", 3, "has_time_series"), False,
     "T7: has_time_series is TRUE-OR-ABSENT (const true); false is never emitted - absence makes "
     "no assertion and a false would be read as verified absence"),
    # ---- credit surface -------------------------------------------------------------------------
    (("surveys", 0, "contributors", 0, "role"), "Chief",
     "an out-of-vocabulary role publishes a WRONG provenance claim about who did what"),
    (("surveys", 0, "contributors", 0, "name_type"), "human",
     "a mis-typed name_type mis-classifies the actor and mis-renders the citation"),
    (("surveys", 0, "contributors", 0, "name"), "",
     "a nameless contributor credits nobody"),
    (("surveys", 0, "creators", 0, "name_type"), "Person",
     "the vocabulary is case-sensitive; 'Person' is not 'person'"),
    (("surveys", 0, "creators", 0, "name"), _DELETE,
     "a creator row with no name cannot be an author of anything"),
    (("surveys", 0, "creators"), {"name": "Kay, Ben"},
     "creators is an ORDERED list; a bare object destroys the citation author order"),
    (("surveys", 0, "creators"), [],
     "2.0 forbids the empty-array state (minItems 1): no creators means NO key"),
    # ---- typed identifiers ----------------------------------------------------------------------
    (("surveys", 0, "related_identifiers", 0, "identifies"), "level9",
     "an out-of-vocabulary data level mislabels WHAT the identifier points at"),
    (("surveys", 0, "related_identifiers", 0, "identifies"), None,
     "unknown level is expressed by OMITTING the key; an explicit null claims a level called null"),
    (("surveys", 0, "related_identifiers", 0, "relation"), "Compiles",
     "T9: an out-of-vocabulary relation publishes a WRONG provenance claim (fail-closed vocabulary)"),
    (("surveys", 0, "related_identifiers", 0, "identifier_type"), "ARK",
     "an identifier type AusMT does not record cannot be resolved by a harvester"),
    (("surveys", 0, "related_identifiers", 0, "resolution"), "unknown",
     "unknown resolution is expressed by OMITTING the key, never by a third token"),
    (("surveys", 0, "related_identifiers", 0, "identifier"), _DELETE,
     "T30b: an identifier-less relationship row relates nothing"),
    (("surveys", 0, "related_identifiers"), [],
     "2.0 forbids the empty-array state (minItems 1): no relations means NO key"),
    # ---- rights block ---------------------------------------------------------------------------
    (("surveys", 0, "attribution", "changes_made"), "yes",
     "a stringy boolean makes the CC-BY changes-made flag truthy in every language that has truthiness"),
    (("surveys", 0, "attribution", "declared_date"), "July 2026",
     "format checking is ON: a prose date is not an ISO date"),
    # ---- stations -------------------------------------------------------------------------------
    (("stations", 0, "data_type"), "XYZ",
     "an out-of-vocabulary band would break every filter the band drives"),
    (("stations", 0, "data_type"), "bbmt",
     "the band vocabulary is case-sensitive"),
    (("stations", 0, "latitude"), -95.0,
     "a latitude beyond the poles is a parsing bug reaching the map"),
    (("stations", 0, "longitude"), 200.0,
     "same, for longitude"),
    (("stations", 0, "latitude"), None,
     "T34a: a HALF-null position is invalid - latitude and longitude are both numeric or both "
     "null (the paired defined null)"),
    (("stations", 0, "station_id"), "",
     "an empty station_id identifies nothing"),
    # ---- collections ----------------------------------------------------------------------------
    (("collections", 0, "bbox"), {"west": "133.0", "south": -32.0, "east": 137.0, "north": -29.0},
     "a stringified corner is not a coordinate"),
    (("collections", 0, "bbox"), {"west": 133.0, "south": -32.0, "east": 137.0},
     "a bbox missing a corner is not a bbox"),
    (("collections", 0, "centroid"), {"latitude": -30.2},
     "a centroid with no longitude is not a position"),
    (("collections", 0, "start_year"), "2013",
     "a stringified programme start year cannot be compared with a survey year_start"),
    (("collections", 0, "n_surveys"), "1",
     "a stringified rollup count breaks the same arithmetic as n_stations"),
    (("collections", 0, "last_updated"), 20260712,
     "an integer date is not an ISO date"),
    # ---- document / portal level ----------------------------------------------------------------
    (("portal", "version"), "1.2.0",
     "the portal version is MAJOR.MINOR by contract; a three-part version breaks the pattern"),
    (("portal", "generated_at"), "yesterday-ish",
     "T34c: format checking is ON, so a malformed build timestamp fails instead of riding through"),
    (("portal", "portal_id"), "",
     "an empty portal_id is no identity at all, and global keys pair it with every record id"),
]


@pytest.mark.parametrize(("path", "value", "why"), RED_CASES,
                         ids=[".".join(str(p) for p in c[0])
                              + ("=<DELETE>" if c[1] is _DELETE else f"={c[1]!r}"[:40])
                              for c in RED_CASES])
def test_red_wrong_value_fails_validation(path, value, why):
    """RED proof: the described fields CONSTRAIN, they do not merely document."""
    v = _validator()
    doc = _mutate(path, value)
    errs = list(v.iter_errors(doc))
    assert errs, f"{'.'.join(str(p) for p in path)} = {value!r} MUST fail validation: {why}"
    # and the failure must be AT the mutated field, not incidental damage somewhere else
    assert any(list(e.path)[:len(path)] == list(path) or list(e.path) == list(path[:-1])
               for e in errs), \
        f"expected an error at {list(path)}, got {[list(e.path) for e in errs]}"


def test_red_cases_are_non_vacuous():
    """Guard on the guard: every RED case must differ from the PASSING document by exactly one
    value, so a case can never 'fail' because the baseline was broken all along."""
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
            # a case may ADD a key the baseline omits (e.g. a bad value for a defined-but-unemitted
            # field): that still differs from the baseline by exactly one value.
            if not (isinstance(base, dict) and path[-1] not in base):
                assert node[path[-1]] != base[path[-1]], f"{path}: the mutation equals the baseline value"


def test_withheld_coordinates_state_forbids_bbox_and_centroid():
    """A withheld coordinates_state with a bbox/centroid present is a FOOTPRINT LEAK - the
    schema's if/then makes it invalid (the error lands on the bbox/centroid keys, which is why
    this is not a RED_CASES row: the error path is not the mutated path)."""
    v = _validator()
    doc = copy.deepcopy(CORPUS_SHAPED)
    doc["surveys"][0]["coordinates_state"] = "withheld"
    assert list(v.iter_errors(doc)), "withheld + bbox/centroid must be rejected (footprint leak)"
    # and the same survey WITHOUT a footprint validates: the state itself is legal
    doc["surveys"][0].pop("bbox")
    doc["surveys"][0].pop("centroid")
    assert not list(v.iter_errors(doc))


def test_generalised_survey_with_full_coordinates_is_valid():
    """The state is public, the reason is private - a generalised survey still publishes
    (generalised) coordinates, so full-looking positions with state generalised are legal."""
    doc = copy.deepcopy(CORPUS_SHAPED)
    doc["surveys"][0]["coordinates_state"] = "generalised"
    assert not list(_validator().iter_errors(doc))


def test_both_null_position_with_declared_state_is_valid():
    """The one defined null - a station whose position is not published carries BOTH
    latitude and longitude as null and the document stays valid."""
    doc = copy.deepcopy(CORPUS_SHAPED)
    doc["stations"][0]["latitude"] = None
    doc["stations"][0]["longitude"] = None
    doc["surveys"][0]["coordinates_state"] = "generalised"
    assert not list(_validator().iter_errors(doc))


def test_has_metadata_relation_with_scheme_accepted():
    """The widened relation vocabulary accepts HasMetadata plus a scheme token (the future
    survey-metadata document is the genuine target; AusMT emits no such row TODAY, which
    test_mtcat20_emission pins from the emitter side)."""
    doc = copy.deepcopy(CORPUS_SHAPED)
    doc["surveys"][0]["related_identifiers"][0]["relation"] = "HasMetadata"
    doc["surveys"][0]["related_identifiers"][0]["scheme"] = "ausmt-survey-metadata"
    assert not list(_validator().iter_errors(doc))


def test_policy_transition_open_to_embargoed_still_validates():
    """An access-policy transition neither breaks validation nor alters identity."""
    doc = copy.deepcopy(CORPUS_SHAPED)
    sv = doc["surveys"][0]
    sv["access"] = "embargoed"
    sv["embargo_until"] = "2027-02-01"
    sv.pop("formats")
    assert not list(_validator().iter_errors(doc))
    assert sv["survey_id"] == CORPUS_SHAPED["surveys"][0]["survey_id"], \
        "a policy transition must not alter persistent identity"


def test_access_description_names_no_phantom_level():
    """The schema is SERVED, so a wrong sentence in it is a published wrong claim. The 2.0 access description names the three well-known values and deliberately does NOT enum-pin
    (an unrecognised value means a withheld survey, not a broken document). Both halves survive
    from the 1.2 gate: the named values must equal the producer's ACCESS_LEVELS set-for-set, and
    NO description anywhere in the schema may name the phantom 'legacy' level."""
    bp = _bp()
    real = set(bp.ACCESS_LEVELS)
    assert real == {"open", "metadata_only", "embargoed"}, f"ACCESS_LEVELS moved: {sorted(real)}"

    desc = SCHEMA["properties"]["surveys"]["items"]["properties"]["access"]["description"]
    m = re.search(r"([^.;]+) are the well-known values", desc)
    assert m, ("the access description must name the well-known values in the form "
               f"'X, Y and Z are the well-known values'; got: {desc}")
    named = {t.strip() for t in re.split(r",|\band\b", m.group(1)) if t.strip()}
    assert named == real, (
        "the documented access levels must equal the producer's ACCESS_LEVELS exactly.\n"
        f"  documented not emitted: {sorted(named - real)}\n"
        f"  emitted not documented: {sorted(real - named)}")

    def _descriptions(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "description" and isinstance(v, str):
                    yield v
                else:
                    yield from _descriptions(v)
        elif isinstance(node, list):
            for v in node:
                yield from _descriptions(v)

    phantoms = [d for d in _descriptions(SCHEMA) if re.search(r"\blegacy\b", d)
                and "access" in d.lower()]
    assert not phantoms, f"a schema description names a phantom access level: {phantoms}"


# --- the emitter side: carried over from the retired v1.2 module ----------------------------------

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
    """n_stations / data_types / period range / tipper count are DERIVED in the walk
    mtcat_document was already doing. The survey metadata here declares NONE of them, so a value
    that appears can only have come from the station rows."""
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
    assert e["data_types"] == {"BBMT": 2, "LPMT": 1, "AMT": 1}
    assert list(e["data_types"]) == ["BBMT", "LPMT", "AMT"], "canonical band order is load-bearing"
    assert e["period_min_s"] == 0.0005 and e["period_max_s"] == 12000.0
    assert e["n_stations_tipper"] == 2, "only the two 'ZT' stations carry a tipper"
    assert e["year_start"] == 2014 and e["year_end"] == 2016
    doc = bp.mtcat_document(meta, stations, generated_at="2026-01-01T00:00:00Z")
    assert e["n_stations"] == len([s for s in doc["stations"] if s["survey_id"] == e["survey_id"]])


def test_derived_facets_are_honest_when_there_is_nothing_to_derive():
    """A station with no period range must not fabricate one, and a band the canonical order does
    not name must still be counted rather than dropped."""
    bp = _bp()
    stations = [_station("S", "A1", -30.0, 137.0, "unknown", None, None, "")]
    e = bp.mtcat_document({"S": {"org": "Org", "access": "open"}}, stations,
                          generated_at="2026-01-01T00:00:00Z")["surveys"][0]
    assert e["n_stations"] == 1
    assert e["data_types"] == {"unknown": 1}, "an unnamed band is counted, never silently dropped"
    # 2.0: a bound/year with nothing to derive from is OMITTED, never emitted null.
    assert "period_min_s" not in e and "period_max_s" not in e
    assert e["n_stations_tipper"] == 0
    assert "year_start" not in e and "year_end" not in e


def test_formats_are_read_off_the_manifest_and_omitted_for_a_withheld_survey():
    """`formats` is derived from the download manifest, the one authority on what is distributed.
    The access/licence gate writes NO manifest row for a withheld survey, so under 2.0 its key is
    OMITTED by construction: there is no second withholding rule here that could drift."""
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
    assert "formats" not in by_id["held"], "a withheld survey omits formats under 2.0 (finding 62)"
    assert by_id["held"]["embargo_until"] == "2027-01-01"
    assert by_id["open"]["n_stations"] == 1, "discovery stays universal even where bytes are withheld"
    assert "embargo_until" not in by_id["open"]


def test_formats_key_never_appears_empty():
    """2.0 removed the empty-array state for formats entirely (schema minItems 1): a manifest with
    zero rows for a survey, or no manifest at all, both OMIT the key."""
    bp = _bp()
    stations = [_station("S", "A1", -30.0, 137.0, "BBMT", 0.01, 100.0, "ZT")]
    meta = {"S": {"org": "Org", "access": "open"}}
    e = bp.mtcat_document(meta, stations, generated_at="2026-01-01T00:00:00Z",
                          manifest_doc={"generated_count": 0, "files": [], "bundles": []})["surveys"][0]
    assert "formats" not in e, "an empty derivation must OMIT the key (2.0 forbids the [] state)"
    e2 = bp.mtcat_document(meta, stations, generated_at="2026-01-01T00:00:00Z")["surveys"][0]
    assert "formats" not in e2, "no manifest at all: 'not known' is never served as 'nothing distributed'"


def test_self_check_validates_the_bytes_that_ship_not_the_object_in_memory():
    """LAYER 3 of the unquoted-date bug family (LAYERS 1 and 2 are in
    test_json_date_robustness.py). PyYAML implicit-types a bare ISO date, so survey.yaml
    `declared_date:` unquoted puts a datetime.date into the attribution block, which
    SMETA and mtcat_document pass through VERBATIM. _jdump's default hook ISO-formats it on the
    way out, so the SERVED mtcat.json holds the string "" and is conformant. The
    product self-check must therefore validate the SERIALISED bytes, not the in-memory object."""
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


def test_emitted_document_validates_against_the_v20_schema():
    """The emitter and the schema agree: a document built by mtcat_document with every derived
    facet populated passes the REAL validator (format checking on), which is the same gate the
    build's product self-check runs."""
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
                                           "identifies": "raw_packed", "resolution": "ok"}],
                  "subjects": [{"code": "370602", "scheme": "ANZSRC-FoR-2020"}],
                  "discovery_description": "Two-station demonstration survey."}}
    doc = bp.mtcat_document(meta, stations, generated_at="2026-01-01T00:00:00Z",
                            manifest_doc={"files": [{"survey": "S", "format": "edi"}], "bundles": []})
    errs = sorted(_validator().iter_errors(doc), key=lambda e: list(e.path))
    assert not errs, "\n".join(f"{list(e.path)}: {e.message}" for e in errs)
    assert doc["portal"]["version"] == SCHEMA_VERSION
    s = doc["surveys"][0]
    assert s["contributors"][-1]["role"] == "HostingInstitution", "the export row still rides last"
    assert s["data_types"] == {"BBMT": 1, "GDS": 1}
    assert s["description"] == "Two-station demonstration survey."
    assert s["subjects"] == [{"code": "370602", "scheme": "ANZSRC-FoR-2020"}]
