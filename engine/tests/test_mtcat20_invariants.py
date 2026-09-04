"""MTCAT 2.0 invariant suite: the fixture checks, ported into the engine tests.

PERMANENT TEST STAGE (final pre-freeze review section 39): this suite runs on every later emitter
change, forever - a future feature can never silently break identity, migration, ordering or the
zero-null/zero-empty posture. Sources:

  * the executable fixture suite, whose
    migrate_12_to_20 IS the 1.2 -> 2.0 emitter-change specification and is carried here
    VERBATIM; the committed fixtures (tests/fixtures/mtcat20/) are the spec example and a
    corpus-shaped 1.2 migration input.
  * the schema-level accept/reject checks live in test_mtcat_schema_v20.py; the emitter-behaviour
    checks live in test_mtcat20_emission.py. THIS module owns the migration transform, the
    reference invariant implementations (counts, ordering, rollups, coordinate-state consistency),
    and the BUILT-OUTPUT scans.

Three layers:

  1. fixture layer (stack-free): the transform + reference invariants over the committed fixtures.
  2. built layer: a real build over the vendored fixture surveys - schema validation with format
     checking ON, the zero-null / zero-empty scans, identifier uniqueness, joins, ordering,
     rollups, derived-facet reconciliation, and the schema served byte-identically at BOTH routes
     across two consecutive builds.
  3. corpus arm (dev-box): when AUSMT_MTCAT20_DATA names a full-corpus build output dir, the same
     scans run over the REAL corpus document; when AUSMT_MTCAT20_BASELINE additionally names a
     pre-2.0 (v1.2) mtcat.json of the same corpus, the EMITTER-EQUIVALENCE dict-test runs:
     migrate_12_to_20(baseline) must equal the built document after stripping the new-in-2.0 keys
     (surveys[].description/subjects/sample_rates_hz/coordinates_state, plus the THREDDS projection
     pair stations[].has_time_series / surveys[].n_stations_time_series_verified) and
     portal.{version,generated_at}. No CI workflow has a corpus, so these skip there (allow-listed in
     ci_check_skips.py); they are the module's full-corpus proof harness and stay runnable forever.
"""
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FIX = HERE / "fixtures" / "mtcat20"
SCHEMA = json.loads((ROOT / "schema" / "mtcat.schema.json").read_text(encoding="utf-8"))
SPEC_DOC = json.loads((FIX / "spec-example.json").read_text(encoding="utf-8"))
DOC12 = json.loads((FIX / "mtcat12-sample.json").read_text(encoding="utf-8"))

CORPUS_DATA = os.environ.get("AUSMT_MTCAT20_DATA")
CORPUS_BASELINE = os.environ.get("AUSMT_MTCAT20_BASELINE")

corpus_arm = pytest.mark.skipif(
    not CORPUS_DATA,
    reason="AUSMT_MTCAT20_DATA does not name a built corpus data dir")
equivalence_arm = pytest.mark.skipif(
    not (CORPUS_DATA and CORPUS_BASELINE),
    reason="AUSMT_MTCAT20_BASELINE does not name a pre-2.0 corpus mtcat.json")


def _validator():
    jsonschema = pytest.importorskip("jsonschema")
    fc = jsonschema.FormatChecker()
    assert "date-time" in fc.checkers, "format checking must be genuinely active (rfc3339-validator)"
    return jsonschema.Draft7Validator(SCHEMA, format_checker=fc)


# ---------------------------------------------------------------- the transform (verbatim)

def migrate_12_to_20(doc):
    """The 1.2 -> 2.0 migration transform; doubles as the emitter-change spec.
    Drops null-as-undeclared keys (station latitude/longitude keep their defined null,
    meaning the position is not published),
    drops empty formats arrays, drops the removed legacy blocks and fields."""
    def clean(node, keep_null=()):
        if isinstance(node, dict):
            return {k: clean(v, keep_null) for k, v in node.items()
                    if not (v is None and k not in keep_null)}
        if isinstance(node, list):
            return [clean(v, keep_null) for v in node]
        return node
    out = copy.deepcopy(doc)
    out.pop('mt_metadata_version', None); out.pop('mth5_version', None)
    for sv in out.get('surveys', []):
        for row in sv.pop('sources', None) or []:
            # sources rows MAP to relationship rows (spec 6.9); statement/licence/retrieved
            # Detail moves to survey-metadata - the workflow must capture it, so its presence
            # here is a hard stop, not a silent deletion. Live corpus: zero occurrences.
            if any(row.get(k) for k in ('statement', 'licence', 'retrieved', 'profile')):
                raise NotImplementedError(
                    'sources row carries statement/licence/retrieved/profile content; '
                    'capture it in survey-metadata before migrating this survey')
            mapped = {k: row[k] for k in ('identifier', 'identifier_type', 'relation',
                                          'identifies', 'custodian') if row.get(k) is not None}
            if mapped.get('identifier'):
                sv.setdefault('related_identifiers', []).append(mapped)
        ch = sv.pop('changes', None)
        if ch and isinstance(ch, dict):
            att = sv.setdefault('attribution', {}) or {}
            att.setdefault('changes_made', ch.get('made'))
            if ch.get('summary'):
                att.setdefault('changes_summary', ch['summary'])
            sv['attribution'] = att
        if sv.get('formats') == []:
            del sv['formats']
    out['surveys'] = clean(out['surveys'])
    out['stations'] = [clean(st, keep_null=('latitude', 'longitude')) for st in out.get('stations', [])]
    out['collections'] = clean(out.get('collections', []))
    out['portal'] = clean(out['portal']); out['portal']['version'] = "2.0"
    return out


# ---------------------------------------------------------------- reference invariant implementations

def count_invariant(survey, stations):
    """n_stations_time_series_verified equals the count of has_time_series true rows."""
    n = survey.get('n_stations_time_series_verified')
    if n is None:
        return True
    true_count = sum(1 for x in stations
                     if x.get('survey_id') == survey['survey_id'] and x.get('has_time_series') is True)
    return n == true_count and n <= survey.get('n_stations', n)


def projection_shape_ok(doc):
    """The THREDDS projection's SHAPE (contract section 2), as a reference invariant so every layer
    gets it: the flag is TRUE-OR-ABSENT (`false` is never emitted, spec:382), and a survey states its
    count exactly when that count is positive. count_invariant is the equality half and cannot see
    the other one - a survey with three true rows and no count key satisfies it vacuously - so the
    tally is walked from the stations here and both directions are stated. Returns violations."""
    out = [f"{st['station_id']}: has_time_series is {st['has_time_series']!r}, not the literal true"
           for st in doc.get('stations', [])
           if 'has_time_series' in st and st['has_time_series'] is not True]
    tally = {}
    for st in doc.get('stations', []):
        if st.get('has_time_series') is True:
            tally[st['survey_id']] = tally.get(st['survey_id'], 0) + 1
    for sv in doc.get('surveys', []):
        want = tally.get(sv['survey_id'], 0)
        got = sv.get('n_stations_time_series_verified')
        if want and got != want:
            out.append(f"{sv['survey_id']}: n_stations_time_series_verified {got!r} against {want} "
                       f"flagged station(s)")
        elif not want and got is not None:
            out.append(f"{sv['survey_id']}: n_stations_time_series_verified {got!r} with no flagged "
                       f"station; a zero count is ABSENT, never 0")
    return out


def ordering_ok(sv):
    """Period and year bounds are ordered wherever both exist."""
    a, b = sv.get('period_min_s'), sv.get('period_max_s')
    if a is not None and b is not None and a > b:
        return False
    a, b = sv.get('year_start'), sv.get('year_end')
    if a is not None and b is not None and a > b:
        return False
    return True


def collection_rollups_ok(doc):
    """Every collection's counts equal its members' facts."""
    for c in doc.get('collections', []):
        members = [sv for sv in doc['surveys'] if sv.get('collection_id') == c['collection_id']]
        if c.get('n_surveys') is not None and c['n_surveys'] != len(members):
            return False
        if c.get('n_stations') is not None and \
                c['n_stations'] != sum(sv.get('n_stations', 0) for sv in members):
            return False
    return True


def coord_state_consistent(survey, stations):
    """A withheld coordinates_state means every station position is unpublished."""
    st_rows = [x for x in stations if x.get('survey_id') == survey['survey_id']]
    if survey.get('coordinates_state') == 'withheld':
        return all(x.get('latitude') is None and x.get('longitude') is None for x in st_rows)
    return True


def scan_nulls_and_empties(doc):
    """The corpus-wide zero-null / zero-empty scan. Returns (nulls, half_null_ids, empties):
    every null outside the paired station latitude/longitude, every half-null pair, and every
    empty array/object anywhere in the document."""
    nulls, empties = [], []

    def walk(node, path, station_row=False):
        if isinstance(node, dict):
            if not node:
                empties.append(path)
            for k, v in node.items():
                if v is None:
                    if station_row and k in ("latitude", "longitude"):
                        continue
                    nulls.append(f"{path}.{k}")
                else:
                    walk(v, f"{path}.{k}", station_row)
        elif isinstance(node, list):
            if not node:
                empties.append(path)
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]", station_row)

    walk(doc.get("portal", {}), "portal")
    walk(doc.get("surveys", []), "surveys")
    if "collections" in doc:
        walk(doc["collections"], "collections")
    for i, st in enumerate(doc.get("stations", [])):
        walk(st, f"stations[{i}]", station_row=True)
    half = [st.get("station_id") for st in doc.get("stations", [])
            if (st.get("latitude") is None) != (st.get("longitude") is None)]
    return nulls, half, empties


def _document_invariants(doc):
    """Every reference check over one 2.0 document; returns a list of violation strings."""
    out = []
    ids = [x["station_id"] for x in doc["stations"]]
    if len(ids) != len(set(ids)):
        out.append("duplicate station_id")
    svids = [s["survey_id"] for s in doc["surveys"]]
    if len(svids) != len(set(svids)):
        out.append("duplicate survey_id")
    dangling = [x["station_id"] for x in doc["stations"] if x["survey_id"] not in set(svids)]
    if dangling:
        out.append(f"dangling stations->surveys joins: {dangling[:5]}")
    cids = {c["collection_id"] for c in doc.get("collections", [])}
    bad_coll = [s["survey_id"] for s in doc["surveys"]
                if s.get("collection_id") is not None and s["collection_id"] not in cids]
    if bad_coll:
        out.append(f"dangling surveys->collections joins: {bad_coll[:5]}")
    for s in doc["surveys"]:
        if not ordering_ok(s):
            out.append(f"{s['survey_id']}: period/year ordering violated")
        if not count_invariant(s, doc["stations"]):
            out.append(f"{s['survey_id']}: verified time-series count violated")
        if not coord_state_consistent(s, doc["stations"]):
            out.append(f"{s['survey_id']}: withheld coordinates_state vs published coordinates")
        r = s.get("sample_rates_hz")
        if r is not None and r != sorted(set(r)):
            out.append(f"{s['survey_id']}: sample_rates_hz not unique-sorted")
        if s.get("coordinates_state") == "withheld" and ("bbox" in s or "centroid" in s):
            out.append(f"{s['survey_id']}: withheld state with a footprint")
    out += projection_shape_ok(doc)
    if not collection_rollups_ok(doc):
        out.append("collection rollups disagree with members")
    n_by_survey = {}
    for st in doc["stations"]:
        n_by_survey[st["survey_id"]] = n_by_survey.get(st["survey_id"], 0) + 1
    for s in doc["surveys"]:
        if s.get("n_stations") is not None and s["n_stations"] != n_by_survey.get(s["survey_id"], 0):
            out.append(f"{s['survey_id']}: n_stations disagrees with stations[]")
        bb = s.get("bbox")
        if bb:
            for st in doc["stations"]:
                if st["survey_id"] != s["survey_id"] or st.get("latitude") is None:
                    continue
                if not (bb["west"] <= st["longitude"] <= bb["east"]
                        and bb["south"] <= st["latitude"] <= bb["north"]):
                    out.append(f"{st['station_id']}: outside its survey bbox")
        mix = s.get("data_types")
        if mix is not None:
            tally = {}
            for st in doc["stations"]:
                if st["survey_id"] == s["survey_id"]:
                    tally[st["data_type"]] = tally.get(st["data_type"], 0) + 1
            if mix != tally:
                out.append(f"{s['survey_id']}: data_types disagrees with stations[]")
    return out


# ---------------------------------------------------------------- layer 1: fixtures

def test_spec_example_validates_and_holds_its_invariants():
    """+ the interchange spec's worked example validates against the schema and
    passes every reference invariant (in-bbox stations, represented bands, ordered periods,
    unique sorted rates, reconciling counts)."""
    errs = list(_validator().iter_errors(SPEC_DOC))
    assert not errs, "\n".join(f"{list(e.path)}: {e.message}" for e in errs)
    assert not _document_invariants(SPEC_DOC)


def test_migration_input_is_really_a_break_and_migrates_clean():
    """+ the corpus-shaped 1.2 fixture does NOT validate raw against the 2.0 schema (the
    break is real: nulls-as-undeclared, empty formats, legacy blocks), and migrate_12_to_20 over
    it DOES validate, with zero nulls (outside the defined pair), zero empties, and every
    reference invariant holding."""
    v = _validator()
    assert list(v.iter_errors(DOC12)), "the 1.2 fixture must NOT validate raw against 2.0"
    migrated = migrate_12_to_20(DOC12)
    errs = list(v.iter_errors(migrated))
    assert not errs, "\n".join(f"{list(e.path)}: {e.message}" for e in errs)
    nulls, half, empties = scan_nulls_and_empties(migrated)
    assert not nulls and not half and not empties, (nulls, half, empties)
    assert not _document_invariants(migrated)


def test_migration_maps_sources_and_changes_per_the_spec():
    """The transform's row mapping is behaviourally pinned: the sources row becomes a
    related_identifiers row (nulls dropped), changes folds into attribution without overriding
    declared values, the empty formats array disappears, and the legacy top-level keys are gone."""
    migrated = migrate_12_to_20(DOC12)
    sv = migrated["surveys"][0]
    assert "sources" not in sv and "changes" not in sv
    assert {"identifier": "10.25914/abc123", "identifier_type": "DOI", "relation": "IsDerivedFrom",
            "identifies": "raw_packed", "custodian": "Geoscience Australia"} in sv["related_identifiers"]
    assert sv["attribution"]["changes_made"] is True
    held = migrated["surveys"][1]
    assert "formats" not in held
    assert "mt_metadata_version" not in migrated and "mth5_version" not in migrated
    assert migrated["portal"]["version"] == "2.0"


def test_migration_hard_stops_on_rights_content_in_a_sources_row():
    doc = copy.deepcopy(DOC12)
    doc["surveys"][0]["sources"][0]["statement"] = "Wording to reproduce verbatim."
    with pytest.raises(NotImplementedError):
        migrate_12_to_20(doc)


def test_reference_checks_actually_detect_violations():
    """Guard on the guards (the suite's Txxb pattern): each reference implementation must
    CATCH a planted violation, or a green scan proves nothing."""
    assert not count_invariant({"survey_id": "s", "n_stations_time_series_verified": 7,
                                "n_stations": 9}, SPEC_DOC["stations"])
    assert not projection_shape_ok(SPEC_DOC), "the ratified example satisfies the projection shape"
    false_flag = copy.deepcopy(SPEC_DOC)
    false_flag["stations"][0]["has_time_series"] = False
    assert any("not the literal true" in v for v in projection_shape_ok(false_flag))
    dropped = copy.deepcopy(SPEC_DOC)
    for sv in dropped["surveys"]:
        sv.pop("n_stations_time_series_verified", None)
    assert any("against 1 flagged station" in v for v in projection_shape_ok(dropped)), \
        "a survey with true rows and NO count is what count_invariant cannot see"
    zeroed = copy.deepcopy(SPEC_DOC)
    for st in zeroed["stations"]:
        st.pop("has_time_series", None)
    assert any("a zero count is ABSENT" in v for v in projection_shape_ok(zeroed))
    assert not ordering_ok({"period_min_s": 100, "period_max_s": 1})
    assert not ordering_ok({"year_start": 2020, "year_end": 2014})
    assert not collection_rollups_ok({"surveys": [{"survey_id": "a", "collection_id": "c",
                                                   "n_stations": 3}],
                                      "collections": [{"collection_id": "c", "n_surveys": 2,
                                                       "n_stations": 3}]})
    w = {"survey_id": "w1", "coordinates_state": "withheld"}
    assert coord_state_consistent(w, [{"survey_id": "w1", "latitude": None, "longitude": None}])
    assert not coord_state_consistent(w, [{"survey_id": "w1", "latitude": -30.0, "longitude": 135.0}])
    bad = copy.deepcopy(SPEC_DOC)
    bad["stations"][0]["latitude"] = -45.0   # outside the example bbox
    assert any("outside its survey bbox" in v for v in _document_invariants(bad))
    dup = copy.deepcopy(SPEC_DOC)
    dup["stations"][1]["station_id"] = dup["stations"][0]["station_id"]
    assert any("duplicate station_id" in v for v in _document_invariants(dup))
    nulls, half, empties = scan_nulls_and_empties(
        {"portal": {}, "surveys": [{"doi": None, "formats": []}],
         "stations": [{"station_id": "x", "latitude": None, "longitude": -30.0}]})
    assert nulls and half and empties, "the scanner must catch planted null/half-null/empty states"


# ---------------------------------------------------------------- layer 2: the built output

@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """TWO consecutive real builds over the vendored fixture surveys (the schema byte-stability
    proof needs both)."""
    pytest.importorskip("mt_metadata")
    outs = []
    for tag in ("one", "two"):
        out = tmp_path_factory.mktemp(f"mtcat20-{tag}") / "data"
        r = subprocess.run([sys.executable, "-m", "extract.build_portal",
                            "--surveys", str(HERE / "fixtures"),
                            "--out", str(out), "--no-validate"],
                           cwd=ROOT, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        outs.append(out)
    return outs


def test_built_document_validates_with_format_checking(built):
    doc = json.loads((built[0] / "mtcat.json").read_text(encoding="utf-8"))
    errs = list(_validator().iter_errors(doc))
    assert not errs, "\n".join(f"{list(e.path)}: {e.message}" for e in errs)


def test_built_document_zero_null_zero_empty(built):
    doc = json.loads((built[0] / "mtcat.json").read_text(encoding="utf-8"))
    nulls, half, empties = scan_nulls_and_empties(doc)
    assert not nulls, f"nulls outside the defined station pair: {nulls[:10]}"
    assert not half, f"half-null coordinate pairs: {half[:10]}"
    assert not empties, f"empty arrays/objects: {empties[:10]}"


def test_built_document_invariants_hold(built):
    doc = json.loads((built[0] / "mtcat.json").read_text(encoding="utf-8"))
    violations = _document_invariants(doc)
    assert not violations, violations


def test_built_document_emits_no_time_series_projection(built):
    """THIS corpus carries no verified-resource register (--ts-index is not passed), so the two
    projection keys are absent everywhere: absence asserts nothing, and nothing here was
    verified. The register-carrying arms live in test_station_invariants' projection tests."""
    doc = json.loads((built[0] / "mtcat.json").read_text(encoding="utf-8"))
    assert all("has_time_series" not in st for st in doc["stations"])
    assert all("n_stations_time_series_verified" not in s for s in doc["surveys"])


def test_schema_served_at_both_routes_and_byte_stable(built):
    """The $id policy in the served tree: the versioned immutable route and the latest-convenience
    route both exist, byte-identical to the in-tree artifact, and the versioned artifact is
    byte-identical across two consecutive builds."""
    in_tree = (ROOT / "schema" / "mtcat.schema.json").read_bytes()
    for out in built:
        doc = json.loads((out / "mtcat.json").read_text(encoding="utf-8"))
        v = doc["portal"]["version"]
        latest = (out / "mtcat.schema.json").read_bytes()
        versioned = (out / "schemas" / "mtcat" / v / "mtcat.schema.json").read_bytes()
        assert latest == in_tree and versioned == in_tree
    v1 = json.loads((built[0] / "mtcat.json").read_text(encoding="utf-8"))["portal"]["version"]
    a = (built[0] / "schemas" / "mtcat" / v1 / "mtcat.schema.json").read_bytes()
    b = (built[1] / "schemas" / "mtcat" / v1 / "mtcat.schema.json").read_bytes()
    assert a == b, "the versioned schema artifact must be byte-identical across consecutive builds"


# ---------------------------------------------------------------- layer 3: the corpus arms

def _strip_new_keys(doc):
    """The equivalence arm's normaliser: everything 2.0 ADDS, removed, so what remains must equal the
    migrated 1.2 document exactly. The THREDDS projection pair is new-in-2.0 too and, unlike the rest
    of this list, is now genuinely EMITTED - migrate_12_to_20 only deletes and moves, so a 1.2
    baseline can never carry it, and leaving it in would read every projected station as a residual
    diff. Those are the framing invariant's TWO exceptions and this is where they are
    normalised away; their SHAPE is pinned by projection_shape_ok, not waived."""
    out = copy.deepcopy(doc)
    for sv in out.get("surveys", []):
        for k in ("description", "subjects", "sample_rates_hz", "coordinates_state",
                  "n_stations_time_series_verified"):
            sv.pop(k, None)
    for st in out.get("stations", []):
        st.pop("has_time_series", None)
    out["portal"].pop("version", None)
    out["portal"].pop("generated_at", None)
    return out


@corpus_arm
def test_corpus_build_validates_and_scans_clean():
    doc = json.loads((Path(CORPUS_DATA) / "mtcat.json").read_text(encoding="utf-8"))
    errs = list(_validator().iter_errors(doc))
    assert not errs, "\n".join(f"{list(e.path)}: {e.message}" for e in errs[:10])
    nulls, half, empties = scan_nulls_and_empties(doc)
    assert not nulls and not half and not empties, (nulls[:10], half[:10], empties[:10])
    violations = _document_invariants(doc)
    assert not violations, violations[:10]
    # THE PROJECTION AT CORPUS SCALE. Its shape is a reference invariant above, so what is left for
    # a built TREE to witness is the one thing a document alone cannot: a station the build ROUTED
    # carries the flag. The containment is deliberately ONE-directional - a withheld, embargoed or
    # pending station keeps its flag while serving no route (CONTRACT:126-132), so the reverse
    # would be false by design. ts_access.json is emitted only when non-empty, and a corpus whose
    # register is all withheld or all pending flags stations while publishing none, so its absence
    # is a legitimate state rather than a missing artifact.
    flagged = {st["station_id"] for st in doc["stations"] if st.get("has_time_series") is True}
    ts_access = Path(CORPUS_DATA) / "ts_access.json"
    if ts_access.exists():
        routed = set(json.loads(ts_access.read_text(encoding="utf-8")))
        assert routed, "ts_access.json exists but is empty; it is written only when non-empty"
        assert routed <= flagged, (
            f"stations carry a published route with no has_time_series: {sorted(routed - flagged)[:5]}")


@equivalence_arm
def test_corpus_emitter_equivalence_dict_test():
    """THE framing proof: migrate_12_to_20(previous-build mtcat.json) equals the new build's
    document after stripping the new-in-2.0 keys and portal.{version,generated_at}. Dict
    equality, not eyeballing; any residual diff is a finding. With the THREDDS projection live the
    normaliser carries its TWO exceptions, which is what makes the framing invariant
    measurable on a register-carrying corpus instead of only on a registerless one."""
    baseline = json.loads(Path(CORPUS_BASELINE).read_text(encoding="utf-8"))
    new_doc = json.loads((Path(CORPUS_DATA) / "mtcat.json").read_text(encoding="utf-8"))
    migrated = migrate_12_to_20(baseline)
    migrated["portal"].pop("version", None)
    migrated["portal"].pop("generated_at", None)
    assert _strip_new_keys(new_doc) == migrated
