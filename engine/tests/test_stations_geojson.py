"""The served stations GeoJSON: the corpus as a vector layer a GIS can open from the URL.

The rule: serve a stations GeoJSON so a user can load AusMT into QGIS and friends
without first writing a script against the positional catalogue. The document is a plain RFC 7946
FeatureCollection at `/data/stations.geojson`, mirrored under `/data/products/` like the other
top-level documents.

The whole risk of this product is that it becomes a SECOND coordinate surface. Every other served
position passes through the coordinate mask seam; a document that derives its own geometry can disclose a
position the catalogue withholds and nothing would notice, because a GeoJSON is not something the
leak sweep's JSON parse reads as a catalogue row. So the pins here are coordinate-access pins first
and GIS-shape pins second:

  * a WITHHELD station is ABSENT. Not a null-geometry feature: GeoJSON allows one, but no GIS renders
    it, so it would be an invisible attribute row AND a second place a withheld station is described.
    Absence is the honest answer, and coord_policy.json remains the record that the station exists.
  * a GENERALISED station ships the SAME 0.1 degree cell the catalogue serves, byte-for-byte, with no
    re-rounding of its own. The true position must not appear anywhere in the file.
  * an EMBARGOED survey keeps DISCOVERY. Its bytes are withheld; its record, its stations and its
    footprint are public, so its stations are on this map exactly as the catalogue carries them. A
    build that dropped them here would quietly contradict the access record.

These drive the REAL pipeline (subprocess build) over the engine-produced coordinate fixtures the
coordinate-policy fixture already stages, so no catalogue row is ever hand-typed (house rule). Requires the
mt_metadata/mth5 build stack; skips cleanly otherwise.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")
pytest.importorskip("mth5")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "extract"))
from _contract import CATALOGUE_COLUMNS   # noqa: E402  (the positional column map, never hand-counted)
# The module's engine-produced coordinate fixtures: one EDI per station with distinctive, mutually
# consistent HEAD/INFO/DEFINEMEAS positions, plus the survey.yaml writer that declares the access +
# Coordinate policy. Reused rather than re-typed so the two workflows can never disagree about what a
# generalised or withheld station looks like on the way in.
from test_coord_access import EXACT, GEN, GEN_CELL, HID, _stage_survey   # noqa: E402

LAT = CATALOGUE_COLUMNS.index("lat")
LON = CATALOGUE_COLUMNS.index("lon")
AUSMT_ID = CATALOGUE_COLUMNS.index("ausmt_id")

# The property set the document promises: identity, the survey it belongs to, what kind of data it is
# and the period band. Lean and FLAT on purpose - a GIS attribute table has no useful nesting, and
# credit/licence belong to the survey (surveys.json, mtcat.json), not to 1418 copies of themselves.
EXPECTED_PROPS = {"ausmt_id", "station", "survey", "survey_id",
                  "data_type", "period_min_s", "period_max_s"}


def _build(tmp_path):
    """Two surveys under one --surveys root: an OPEN one carrying the exact/generalised/withheld
    coordinate trio, and an EMBARGOED one whose station must still reach the map. Returns
    (out_dir, geojson_doc, catalogue_rows)."""
    base = tmp_path / "surveys"
    base.mkdir(parents=True)
    _stage_survey(base, [EXACT, GEN, HID], slug="open-survey", name="Open Survey")
    _stage_survey(base, [{**EXACT, "id": "EMBARGOONE"}], slug="embargoed-survey",
                  name="Embargoed Survey", declare_policy=False)
    y = base / "embargoed-survey" / "survey.yaml"
    y.write_text(y.read_text(encoding="utf-8").replace(
        "  level: open", "  level: embargoed\n  embargo_until: 2099-01-01"), encoding="utf-8")
    out = tmp_path / "out"
    # --products is passed because production does (deploy/Makefile writes products/ INSIDE the served
    # build dir), and the mirror pin below is a statement about that served tree.
    r = subprocess.run([sys.executable, "-m", "extract.build_portal", "--surveys", str(base),
                        "--out", str(out), "--products", str(out / "products"),
                        "--bundle-edi", "--no-validate"],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    gj = json.loads((out / "stations.geojson").read_text(encoding="utf-8"))
    cat = json.loads((out / "catalogue.json").read_text(encoding="utf-8"))
    return out, gj, cat


def _by_id(gj):
    return {f["properties"]["ausmt_id"]: f for f in gj["features"]}


# --------------------------------------------------------------------------- GIS shape

def test_the_document_is_a_valid_point_feature_collection(tmp_path):
    """RFC 7946 shape, because that is the entire point: a GIS reads this or it is useless. FAILS if
    the top-level type is not FeatureCollection, if a feature is not a Feature, or if any geometry is
    not a two-element [lon, lat] Point (a lat/lon transposition would place the whole corpus in the
    Indian Ocean and still parse)."""
    _out, gj, _cat = _build(tmp_path)
    assert gj["type"] == "FeatureCollection"
    assert isinstance(gj["features"], list) and gj["features"], "an empty map is not a product"
    for f in gj["features"]:
        assert f["type"] == "Feature"
        g = f["geometry"]
        assert g["type"] == "Point", f"{f['properties']['ausmt_id']} is not a Point"
        lon, lat = g["coordinates"]
        assert len(g["coordinates"]) == 2, "positions are [lon, lat]; no third element is emitted"
        assert -180 <= lon <= 180 and -90 <= lat <= 90, f"out-of-range position {g['coordinates']}"
        # The fixture corpus is in South Australia: lon ~135, lat ~-32. A transposed pair would still
        # be in range, so pin the hemisphere the fixture actually occupies.
        assert lat < 0 < lon, f"lon/lat look transposed: {g['coordinates']}"


def test_feature_properties_are_the_lean_flat_set(tmp_path):
    """The attribute table a GIS user sees. FAILS if a property is added or dropped without this pin
    moving with it, or if any value is a nested object/array (a QGIS attribute column cannot render
    one, and nesting is how per-feature bloat starts)."""
    _out, gj, _cat = _build(tmp_path)
    for f in gj["features"]:
        assert set(f["properties"]) == EXPECTED_PROPS, \
            f"{f['properties'].get('ausmt_id')}: {sorted(f['properties'])}"
        for k, v in f["properties"].items():
            assert not isinstance(v, (dict, list)), f"property {k} is nested: {v!r}"
    ex = _by_id(gj)["au.open-survey." + EXACT["id"]]["properties"]
    assert ex["station"] == EXACT["id"]
    assert ex["survey"] == "Open Survey" and ex["survey_id"] == "open-survey", \
        "both the display label and the slug are carried: a GIS user joins on one or the other"


def test_the_products_mirror_carries_the_same_document(tmp_path):
    """The other top-level documents are mirrored under products/; this one follows the pattern, and
    reference/index.md publishes both paths. FAILS if the mirror is missing or has drifted."""
    out, gj, _cat = _build(tmp_path)
    mirror = out / "products" / "stations.geojson"
    assert mirror.exists(), "the products/ mirror must be written beside the other documents"
    assert json.loads(mirror.read_text(encoding="utf-8")) == gj


# --------------------------------------------------------------------------- coordinate access

def test_a_withheld_station_is_absent_not_a_null_geometry(tmp_path):
    """A custodian-withheld position has no usable geometry. FAILS if the withheld station
    appears at all (as a null-geometry feature or, far worse, with a position), and equally if the
    exact/generalised stations went missing with it."""
    _out, gj, _cat = _build(tmp_path)
    ids = set(_by_id(gj))
    assert "au.open-survey." + HID["id"] not in ids, \
        "a withheld station must be ABSENT, never a null-geometry row"
    assert "au.open-survey." + EXACT["id"] in ids and "au.open-survey." + GEN["id"] in ids
    for f in gj["features"]:
        assert f["geometry"] is not None, "no feature may carry a null geometry"


def test_the_feature_set_is_the_catalogue_minus_withheld_positions(tmp_path):
    """The document is derived from the SAME masked records the catalogue is projected from, so its
    membership is exactly the catalogue's minus the stations with no position. FAILS if the emitter
    grew its own filter (an access test, a licence test) that could drop a discoverable station."""
    _out, gj, cat = _build(tmp_path)
    positioned = {row[AUSMT_ID] for row in cat if row[LAT] is not None and row[LON] is not None}
    assert set(_by_id(gj)) == positioned, "one feature per catalogue station that has a position"


def test_a_generalised_station_ships_the_served_cell_and_nothing_finer(tmp_path):
    """The generalised station's geometry must be the SAME 0.1 degree cell the catalogue serves, and
    the true position must not appear anywhere in the file. FAILS if the emitter read an unmasked
    record, or re-derived (and so re-rounded) a position of its own."""
    out, gj, cat = _build(tmp_path)
    gid = "au.open-survey." + GEN["id"]
    lon, lat = _by_id(gj)[gid]["geometry"]["coordinates"]
    assert (round(lat, 6), round(lon, 6)) == GEN_CELL, \
        f"generalised station must ship {GEN_CELL}, got {(lat, lon)}"
    crow = next(row for row in cat if row[AUSMT_ID] == gid)
    assert (lat, lon) == (crow[LAT], crow[LON]), "the geometry must be the catalogue's served value"
    raw = (out / "stations.geojson").read_text(encoding="utf-8")
    for st in (GEN, HID):
        for val in (st["lat"], st["lon"], st["elev"]):
            assert f"{val}" not in raw, f"true value {val} of {st['id']} leaked into stations.geojson"


def test_an_embargoed_surveys_stations_stay_on_the_map(tmp_path):
    """An embargo withholds BYTES, never discovery: an embargoed survey keeps its catalogue record,
    its stations and its footprint. This document carries no bytes, so its stations belong here
    exactly as the catalogue serves them. FAILS if the emitter borrowed the byte gate."""
    _out, gj, _cat = _build(tmp_path)
    f = _by_id(gj).get("au.embargoed-survey.EMBARGOONE")
    assert f is not None, "an embargoed survey's stations must still appear (discovery is universal)"
    assert f["geometry"]["type"] == "Point"
    assert f["properties"]["survey_id"] == "embargoed-survey"
