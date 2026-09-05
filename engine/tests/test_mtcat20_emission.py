"""MTCAT 2.0 emission semantics, implemented at the source (the migrate_12_to_20
transform IS the emitter-change specification).

The 2.0 breaking list, each pinned here against the real emitter:

  * null-as-undeclared is REMOVED: an optional survey key the survey does not declare is OMITTED,
    never emitted null; the ONE defined null is the paired stations[].latitude/longitude (position
    not published). Relationship rows carry no null-valued keys either (the 110-error class).
  * formats is emitted only when at least one format is actually distributed (never []); an
  *     embargoed/withheld survey OMITS the key ([] would falsely assert that no formats are KNOWN
  *     when the holdings exist and are merely withheld).
  * sources[]/changes are never emitted: a sources row maps to a related_identifiers row (spec
    6.9); a row carrying statement/licence/retrieved/profile content is a HARD STOP (that content
    must be captured in survey-metadata, not silently deleted).
  * the top-level mt_metadata_version/mth5_version keys are gone (legacy 1.x, removed from core).

And the 2.0 additions:

  * surveys[].description: survey.yaml discovery_description, else the abstract when it is already
    <= 1200 chars; the engine NEVER truncates (an over-long abstract with no discovery text is a
    surveys-side validation failure, not an engine decision).
  * surveys[].subjects[]: verbatim from survey.yaml.
  * surveys[].sample_rates_hz[]: ONLY from explicit acquisition metadata (mt_metadata-parsed run
    metadata; MTH5 run tables), canonicalised round-to-6-significant-figures + dedupe + sort
    ascending (RED-proven against a float-artefact fixture below); NEVER inferred from instrument
    model or period coverage.
  * surveys[].coordinates_state: projected from the survey's access.coordinates policy where
    DECLARED (absent policy => no key, no assertion), aggregated over the per-station effective
    policies: all exact => exact, all withheld => withheld, any other mixture => generalised.
    A withheld state omits bbox/centroid (they would republish the withheld footprint).

stations[].has_time_series and surveys[].n_stations_time_series_verified project from the
verified-resource register stamp (the THREDDS workflow): true-or-absent, count present iff positive.
"""
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "extract"))

import build_portal as bp  # noqa: E402
import _mtm as mtm  # noqa: E402


def _doc(meta, stations, **kw):
    return bp.mtcat_document(meta, stations, generated_at="2026-01-01T00:00:00Z", **kw)


def _st(survey, aid, sid, lat=-30.1, lon=137.0, **extra):
    r = {"survey": survey, "ausmt_id": aid, "id": sid, "lat": lat, "lon": lon, "type": "BBMT"}
    r.update(extra)
    return (Path(sid + ".edi"), r)


_BASE = {"org": "UoX", "country": "Australia", "lic": "CC-BY-4.0", "access": "open"}


def _no_nones(node, path="$"):
    """Recursively assert no None value anywhere (the caller excludes station lat/lon rows)."""
    if isinstance(node, dict):
        for k, v in node.items():
            assert v is not None, f"{path}.{k} is null (null-as-undeclared is removed in 2.0)"
            _no_nones(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _no_nones(v, f"{path}[{i}]")


# ---------------------------------------------------------------- null-as-undeclared removed

def test_undeclared_optional_keys_are_omitted_never_null():
    """A survey that declares no doi/licence/version/collection/ror/raid/year range emits NONE of
    those keys; the 1.2 emitter wrote them all as null."""
    meta = {"Demo Survey": dict(_BASE)}
    doc = _doc(meta, [_st("Demo Survey", "au.demo-survey.A1", "A1")])
    s = doc["surveys"][0]
    for k in ("doi", "organisation_ror", "raid", "version", "collection_id",
              "year_start", "year_end", "embargo_until"):
        assert k not in s, f"{k} must be OMITTED when undeclared, not emitted null"
    _no_nones(doc["surveys"])
    _no_nones(doc["portal"])
    _no_nones(doc.get("collections", []))


def test_station_position_nulls_are_the_one_defined_null():
    """A withheld/unlocated station keeps BOTH latitude and longitude present as null (the one
    defined null in 2.0); every other station key is non-null."""
    meta = {"Demo Survey": dict(_BASE)}
    doc = _doc(meta, [_st("Demo Survey", "au.demo-survey.A1", "A1", lat=None, lon=None)])
    st = doc["stations"][0]
    assert "latitude" in st and st["latitude"] is None
    assert "longitude" in st and st["longitude"] is None
    for k, v in st.items():
        if k not in ("latitude", "longitude"):
            assert v is not None


def test_survey_with_no_located_station_omits_bbox_and_centroid():
    meta = {"Demo Survey": dict(_BASE)}
    doc = _doc(meta, [_st("Demo Survey", "au.demo-survey.A1", "A1", lat=None, lon=None)])
    s = doc["surveys"][0]
    assert "bbox" not in s and "centroid" not in s
    assert "period_min_s" not in s and "period_max_s" not in s


# ---------------------------------------------------------------- formats

def test_formats_omitted_when_nothing_is_distributed():
    """With a manifest present, a survey with NO rows (an embargoed/withheld survey) OMITS formats;
    a survey with rows emits the sorted set. Without any manifest, everyone omits it."""
    meta = {"Open Survey": dict(_BASE), "Held Survey": dict(_BASE, access="embargoed")}
    stations = [_st("Open Survey", "au.open-survey.A1", "A1"),
                _st("Held Survey", "au.held-survey.B1", "B1")]
    man = {"files": [{"survey": "Open Survey", "format": "edi"}], "bundles": []}
    doc = _doc(meta, stations, manifest_doc=man)
    by_id = {s["survey_id"]: s for s in doc["surveys"]}
    assert by_id["open-survey"]["formats"] == ["edi"]
    assert "formats" not in by_id["held-survey"], (
        "an embargoed survey must OMIT formats (finding 62): [] would falsely assert no known formats")
    doc2 = _doc(meta, stations)
    assert all("formats" not in s for s in doc2["surveys"])


# ---------------------------------------------------------------- sources/changes removed

def test_sources_and_changes_are_never_emitted_and_sources_rows_map_to_related_identifiers():
    meta = {"Demo Survey": dict(
        _BASE,
        sources=[{"identifier": "10.99999/upstream", "identifier_type": "DOI",
                  "relation": "IsDerivedFrom", "custodian": "GA", "identifies": None}],
        attribution={"custodian": "GA", "changes_made": True, "changes_summary": "Served verbatim."},
        changes={"made": True, "summary": "Served verbatim."})}
    doc = _doc(meta, [_st("Demo Survey", "au.demo-survey.A1", "A1")])
    s = doc["surveys"][0]
    assert "sources" not in s and "changes" not in s
    rows = s["related_identifiers"]
    assert {"identifier": "10.99999/upstream", "identifier_type": "DOI",
            "relation": "IsDerivedFrom", "custodian": "GA"} in rows
    for row in rows:
        assert all(v is not None for v in row.values()), "relationship rows carry no null keys"
    assert s["attribution"] == {"custodian": "GA", "changes_made": True,
                                "changes_summary": "Served verbatim."}


def test_sources_row_with_rights_content_is_a_hard_stop():
    """A sources row carrying statement/licence/retrieved/profile content must HARD STOP the build
    (per the transform): that content moves to survey-metadata, never silently deleted."""
    import pytest
    meta = {"Demo Survey": dict(_BASE, sources=[
        {"identifier": "10.99999/upstream", "statement": "Attribution wording to reproduce."}])}
    with pytest.raises(NotImplementedError):
        _doc(meta, [_st("Demo Survey", "au.demo-survey.A1", "A1")])


# ---------------------------------------------------------------- top-level legacy keys

def test_top_level_library_version_keys_are_gone():
    meta = {"Demo Survey": dict(_BASE)}
    doc = _doc(meta, [_st("Demo Survey", "au.demo-survey.A1", "A1")])
    assert "mt_metadata_version" not in doc
    assert "mth5_version" not in doc


# ---------------------------------------------------------------- description

def test_description_prefers_discovery_description_verbatim():
    meta = {"Demo Survey": dict(_BASE, discovery_description="Short discovery text.",
                                blurb="A" * 2000)}
    s = _doc(meta, [_st("Demo Survey", "au.demo-survey.A1", "A1")])["surveys"][0]
    assert s["description"] == "Short discovery text."


def test_description_falls_back_to_abstract_only_when_short_enough():
    meta = {"Demo Survey": dict(_BASE, blurb="A concise abstract.")}
    s = _doc(meta, [_st("Demo Survey", "au.demo-survey.A1", "A1")])["surveys"][0]
    assert s["description"] == "A concise abstract."
    long_meta = {"Demo Survey": dict(_BASE, blurb="A" * 1201)}
    s2 = _doc(long_meta, [_st("Demo Survey", "au.demo-survey.A1", "A1")])["surveys"][0]
    assert "description" not in s2, (
        "an over-1200 abstract with no discovery_description must be OMITTED, never truncated: "
        "the discovery-text gate is a surveys-side validation, not an engine edit")
    edge = {"Demo Survey": dict(_BASE, blurb="B" * 1200)}
    s3 = _doc(edge, [_st("Demo Survey", "au.demo-survey.A1", "A1")])["surveys"][0]
    assert s3["description"] == "B" * 1200, "exactly 1200 chars is within the gate"


# ---------------------------------------------------------------- subjects

def test_subjects_pass_through_verbatim_and_absent_means_absent():
    row = {"code": "370602", "scheme": "ANZSRC-FoR-2020",
           "label": "Electrical and electromagnetic methods in geophysics",
           "uri": "https://linked.data.gov.au/def/anzsrc-for/2020/370602"}
    meta = {"Demo Survey": dict(_BASE, subjects=[row])}
    s = _doc(meta, [_st("Demo Survey", "au.demo-survey.A1", "A1")])["surveys"][0]
    assert s["subjects"] == [row]
    bare = {"Demo Survey": dict(_BASE)}
    s2 = _doc(bare, [_st("Demo Survey", "au.demo-survey.A1", "A1")])["surveys"][0]
    assert "subjects" not in s2


# ---------------------------------------------------------------- sample_rates_hz

def test_sample_rates_canonicalised_from_float_artefacts():
    """The float-artefact fixture (RED-proof mandated by the plan): binary-float noise on
    the same physical rate collapses under round-to-6-significant-figures; the result is deduped
    and sorted ascending."""
    meta = {"Demo Survey": dict(_BASE)}
    stations = [
        _st("Demo Survey", "au.demo-survey.A1", "A1",
            sample_rates_hz=[149.99999999999997, 24000.000000000004]),
        _st("Demo Survey", "au.demo-survey.A2", "A2",
            sample_rates_hz=[150.00000000000003, 10.0, 150.0]),
    ]
    s = _doc(meta, stations)["surveys"][0]
    assert s["sample_rates_hz"] == [10, 150, 24000]


def test_sample_rates_absent_when_no_explicit_run_metadata_exists():
    """No station carries explicit run rates => the key is ABSENT. The survey deliberately declares
    an instrument model and the stations a period range: neither may ever synthesise a rate."""
    meta = {"Demo Survey": dict(_BASE, instrument_model="LEMI-423")}
    stations = [_st("Demo Survey", "au.demo-survey.A1", "A1",
                    period_min_s=0.0025, period_max_s=3200.0)]
    s = _doc(meta, stations)["surveys"][0]
    assert "sample_rates_hz" not in s, (
        "sample rates must come ONLY from explicit acquisition metadata, never inferred from "
        "instrument capability or period coverage")


def test_record_from_tf_reads_only_explicit_positive_run_rates():
    """The per-station extraction: a run's declared sample_rate > 0 is explicit metadata; the
    mt_metadata default 0.0 (undeclared) is NOT. A record with no explicit rate carries no key."""
    def _tf(rates):
        runs = [types.SimpleNamespace(id=f"{i:03d}", sample_rate=r) for i, r in enumerate(rates)]
        return types.SimpleNamespace(
            period=None, station="ST01", latitude=-30.0, longitude=137.0, elevation=100.0,
            has_impedance=lambda: False, has_tipper=lambda: False,
            station_metadata=types.SimpleNamespace(runs=runs))
    r = mtm.record_from_tf(_tf([150.0, 0.0, 10.0, 150.0]), "st01.edi")
    assert r["sample_rates_hz"] == [10.0, 150.0]
    r2 = mtm.record_from_tf(_tf([0.0, 0.0]), "st01.edi")
    assert "sample_rates_hz" not in r2
    r3 = mtm.record_from_tf(_tf([]), "st01.edi")
    assert "sample_rates_hz" not in r3


def test_real_enriched_edi_yields_no_fabricated_rate():
    """HONESTY PIN against a real dialect file: the enriched >INFO fixture carries a sample-rate
    line in its free text, but the pinned mt_metadata (1.0.9) does not surface it as parsed run
    metadata (run.sample_rate stays at its 0.0 default). The engine must therefore emit NOTHING
    for it: the source is 'what mt_metadata parses', never a private re-scrape of the text."""
    import pytest
    pytest.importorskip("mt_metadata")
    fixture = HERE / "fixtures" / "edi-info-json" / "LineNo__StationNo_104.edi"
    tf, _fb = mtm.read_with_fallback(fixture)
    r = mtm.record_from_tf(tf, fixture.name)
    assert "sample_rates_hz" not in r


# ---------------------------------------------------------------- coordinates_state

def test_coordinates_state_omitted_when_policy_undeclared():
    meta = {"Demo Survey": dict(_BASE)}
    s = _doc(meta, [_st("Demo Survey", "au.demo-survey.A1", "A1")])["surveys"][0]
    assert "coordinates_state" not in s, "absence of a declared policy makes no assertion"


def test_coordinates_state_aggregation_rule():
    """all exact => exact; all withheld => withheld; any mixture => generalised. Effective
    per-station policies are read off the post-mask records (r['coord_policy'], stamped by the one
    mask seam; exact stations are unstamped)."""
    def _meta(**kw):
        return {"Demo Survey": dict(_BASE, coord_policy_declared=True, **kw)}

    all_exact = _doc(_meta(coord_policy_default="exact"),
                     [_st("Demo Survey", "au.demo-survey.A1", "A1"),
                      _st("Demo Survey", "au.demo-survey.A2", "A2", lat=-30.3, lon=137.4)])
    assert all_exact["surveys"][0]["coordinates_state"] == "exact"

    mixed = _doc(_meta(coord_policy_default="withheld"),
                 [_st("Demo Survey", "au.demo-survey.A1", "A1"),
                  _st("Demo Survey", "au.demo-survey.A2", "A2",
                      lat=None, lon=None, coord_policy="withheld")])
    assert mixed["surveys"][0]["coordinates_state"] == "generalised"

    gen = _doc(_meta(coord_policy_default="generalised"),
               [_st("Demo Survey", "au.demo-survey.A1", "A1",
                    lat=-30.1, lon=137.0, coord_policy="generalised")])
    assert gen["surveys"][0]["coordinates_state"] == "generalised"


def test_coordinates_state_withheld_omits_bbox_and_centroid():
    meta = {"Demo Survey": dict(_BASE, coord_policy_declared=True, coord_policy_default="withheld")}
    doc = _doc(meta, [_st("Demo Survey", "au.demo-survey.A1", "A1",
                          lat=None, lon=None, coord_policy="withheld")])
    s = doc["surveys"][0]
    assert s["coordinates_state"] == "withheld"
    assert "bbox" not in s and "centroid" not in s, (
        "a withheld footprint must not be republished as a bbox/centroid (schema-enforced too)")


def test_smeta_carries_the_new_curation_fields_absent_to_absent():
    """survey_meta_from_yaml threads discovery_description / subjects / the declared coordinate
    policy into SMETA when declared, and adds NO key when not (the default-stability discipline:
    the whole existing corpus yields byte-identical SMETA)."""
    y = {"name": "Demo Survey", "organisation": "UoX",
         "discovery_description": "Short discovery text.",
         "subjects": [{"code": "370602", "scheme": "ANZSRC-FoR-2020"}],
         "access": {"level": "open", "coordinates": "generalised"}}
    sm = bp.survey_meta_from_yaml(y)
    assert sm["discovery_description"] == "Short discovery text."
    assert sm["subjects"] == [{"code": "370602", "scheme": "ANZSRC-FoR-2020"}]
    assert sm["coord_policy_declared"] is True
    assert sm["coord_policy_default"] == "generalised"
    bare = bp.survey_meta_from_yaml({"name": "Demo Survey", "organisation": "UoX"})
    for k in ("discovery_description", "subjects", "coord_policy_declared", "coord_policy_default"):
        assert k not in bare, f"{k} must be absent when undeclared (default stability)"


# ---------------------------------------------------------------- deferred projections stay out

def test_time_series_projection_follows_the_register_stamp():
    """The THREDDS projection: a station row the build stamped from the verified-resource register
    emits `has_time_series: true`; an unstamped row emits NOTHING (absence asserts nothing, false is
    never emitted); the survey count is present exactly when positive and equals the true rows."""
    meta = {"Demo Survey": dict(_BASE), "Bare Survey": dict(_BASE)}
    doc = _doc(meta, [_st("Demo Survey", "au.demo-survey.A1", "A1", has_ts=True),
                      _st("Demo Survey", "au.demo-survey.A2", "A2"),
                      _st("Bare Survey", "au.bare-survey.B1", "B1")])
    st = {s["station_id"]: s for s in doc["stations"]}
    assert st["au.demo-survey.A1"].get("has_time_series") is True
    assert "has_time_series" not in st["au.demo-survey.A2"]
    assert "has_time_series" not in st["au.bare-survey.B1"]
    sv = {s["survey_id"]: s for s in doc["surveys"]}
    assert sv["demo-survey"].get("n_stations_time_series_verified") == 1
    assert "n_stations_time_series_verified" not in sv["bare-survey"], \
        "a zero count is ABSENT, never 0 (omit-by-default)"


def test_time_series_projection_absent_without_a_register():
    """No stamp anywhere: both keys absent everywhere, which is what a registerless corpus emits."""
    meta = {"Demo Survey": dict(_BASE)}
    doc = _doc(meta, [_st("Demo Survey", "au.demo-survey.A1", "A1")])
    assert all("has_time_series" not in st for st in doc["stations"])
    assert all("n_stations_time_series_verified" not in s for s in doc["surveys"])
