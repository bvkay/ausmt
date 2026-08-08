"""Station-id override for third-party released data (owner ruling 2026-08-08).

The defect these tests encode is real, from the GSSA/BHP Roxby Downs 2018 delivery: the contractor
reused 56 station numbers between two acquisition stages, so two DIFFERENT physical sites (the
furthest colliding pair 58.5 km apart) share one DATAID. `_disambiguate` renders that as a pair of
processing-VARIANT records (`92.v1` / `92.s1` here, the tag taken from each file's name), which
asserts two processings of ONE station and is false. AusMT serves third-party bytes unmodified, so
the id has to be overridden at ingest instead of by editing the EDI.

Every test states an INDEPENDENT observable (a built catalogue id, a served XML filename, an MTH5
station group, a build log line), never the parser's own opinion of what it parsed.
"""
import json
import re
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")
pytest.importorskip("mth5")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "extract"))
sys.path.insert(0, str(REPO))
import _stationids as stnids  # noqa: E402
import build_portal  # noqa: E402

SAMPLE_EDIS = sorted((REPO / "data" / "sample-survey" / "transfer_functions" / "edi").glob("*.edi"))

# The two colliding source files, mirroring the real delivery: the same contractor number reused
# across acquisition stages, the two files sitting ~110 km apart.
COLLIDING_DATAID = "92"


def _write_edi(dest: Path, src: Path, dataid: str, lat_shift: bool):
    """One source EDI with its DATAID forced to `dataid`, optionally relocated ~110 km south so the
    two fixture stations are unmistakably DIFFERENT physical sites. EDIs are latin-1 text; the HEAD,
    the DEFINEMEAS REFLAT and the INFO block are kept mutually consistent so the coordinate QC sees
    the same relationship it sees in the untouched fixture."""
    text = src.read_text(encoding="latin-1")
    text = re.sub(r'DATAID="[^"]*"', f'DATAID="{dataid}"', text, count=1)
    if lat_shift:
        text = text.replace("-30:8:", "-31:8:").replace("-29.8556", "-30.8556")
    dest.write_text(text, encoding="latin-1")


def _make_survey(tmp_path, *, yaml_extra="", slug="rd18-probe", name="RD18 Probe"):
    """A survey package whose TWO EDIs share one DATAID and sit far apart (the real defect shape)."""
    pkg = tmp_path / "surveys" / slug
    edir = pkg / "transfer_functions" / "edi"
    edir.mkdir(parents=True)
    _write_edi(edir / "92.edi", SAMPLE_EDIS[0], COLLIDING_DATAID, lat_shift=False)
    _write_edi(edir / "92_S1.edi", SAMPLE_EDIS[1], COLLIDING_DATAID, lat_shift=True)
    (pkg / "survey.yaml").write_text(
        f"name: {name}\nslug: {slug}\ncountry: Australia\norganisation: Test Org\n"
        f"access: open\nlicense: CC-BY-4.0\n{yaml_extra}", encoding="utf-8")
    return tmp_path / "surveys"


OVERRIDE_YAML = (
    'station_ids:\n'
    '  source: filename\n'
    '  map:\n'
    '    "92.edi": "RD18-092"\n'
    '    "92_S1.edi": "RD18-092-S1"\n'
)


def _build(surveys, out, extra=None):
    argv = ["--surveys", str(surveys), "--out", str(out), "--bundle-edi", "--no-validate"]
    return build_portal.main(argv + (extra or []))


def _catalogue(out: Path):
    """{station id: full positional row} from the built catalogue."""
    rows = json.loads((out / "catalogue.json").read_text(encoding="utf-8"))
    return {r[0]: r for r in rows}


def _col(name):
    from _contract import CATALOGUE_COLUMNS  # noqa: PLC0415
    return CATALOGUE_COLUMNS.index(name)


# --------------------------------------------------------------------------------------------
# unit: the block parser
# --------------------------------------------------------------------------------------------

def test_absent_block_yields_an_empty_map():
    """No `station_ids` in survey.yaml => no override at all, so the existing corpus is untouched."""
    for absent in (None, "", {}):
        assert stnids.parse_station_ids(absent) == ("filename", {}, {})


def test_a_good_block_parses_to_its_map():
    parsed = stnids.parse_station_ids(
        {"source": "filename", "map": {"92.edi": "RD18-092", "92_S1.edi": "RD18-092-S1"}})
    assert parsed.source == "filename"
    assert parsed.ids == {"92.edi": "RD18-092", "92_S1.edi": "RD18-092-S1"}
    assert parsed.provenance == {}


def test_source_defaults_to_filename_when_omitted():
    assert stnids.parse_station_ids({"map": {"a.edi": "X1"}}) == ("filename", {"a.edi": "X1"}, {})


@pytest.mark.parametrize("block", [
    {"source": "dataid", "map": {"a.edi": "X1"}},          # not in the enum (reserved, not implemented)
    {"source": "filename", "mapp": {"a.edi": "X1"}},        # typo'd key must not silently do nothing
    {"source": "filename", "map": ["a.edi"]},               # map is not a mapping
    "filename",                                             # block is not a mapping
])
def test_a_malformed_block_fails_closed(block):
    with pytest.raises(stnids.StationIdError):
        stnids.parse_station_ids(block)


@pytest.mark.parametrize("key", ["../../etc/passwd", "sub/92.edi", "sub\\92.edi", "..", " "])
def test_a_traversal_shaped_key_fails_closed(key):
    with pytest.raises(stnids.StationIdError):
        stnids.parse_station_ids({"source": "filename", "map": {key: "RD18-092"}})


@pytest.mark.parametrize("value", ["", "RD18 092", "RD18/092", "-RD18", ".RD18", "RD18..092",
                                   "<img onerror=x>"])
def test_a_value_the_sanitiser_would_mangle_fails_closed(value):
    """The owner's ids are not ours to rewrite: a value safe_component would change is a FAILURE,
    never a silent mangling into something the custodian did not declare."""
    with pytest.raises(stnids.StationIdError):
        stnids.parse_station_ids({"source": "filename", "map": {"92.edi": value}})


def test_colliding_values_fail_closed_naming_both_keys():
    with pytest.raises(stnids.StationIdError) as ei:
        stnids.parse_station_ids({"source": "filename",
                                  "map": {"92.edi": "RD18-092", "92_S1.edi": "RD18-092"}})
    msg = str(ei.value)
    assert "92.edi" in msg and "92_S1.edi" in msg and "RD18-092" in msg


def test_a_key_naming_no_file_fails_closed_with_the_filename():
    with pytest.raises(stnids.StationIdError) as ei:
        stnids.validate_station_ids({"93.edi": "RD18-093"}, [Path("/pkg/92.edi")])
    assert "93.edi" in str(ei.value) and "92.edi" in str(ei.value)


def test_an_unmapped_file_is_not_an_error():
    """Partial maps are legal: a file with no entry keeps DATAID behaviour."""
    stnids.validate_station_ids({"92.edi": "RD18-092"}, [Path("/pkg/92.edi"), Path("/pkg/93.edi")])


# --------------------------------------------------------------------------------------------
# unit: the id charset agrees with the sanitiser it claims to be the fixed point of
# --------------------------------------------------------------------------------------------

def test_station_id_charset_is_the_safe_component_fixed_point():
    """_stationids.station_id_is_safe() is DEFINED as 'safe_component would return this unchanged'.
    It is implemented separately (stdlib-only leaf, no import cycle), so the two are pinned in
    agreement over the shared vector fixture plus the owner's own id scheme. Divergence here is the
    bug class where a value passes validation and is then silently rewritten."""
    vectors = json.loads((HERE / "fixtures" / "safe_component_vectors.json").read_text(encoding="utf-8"))
    cases = [c["input"] for c in vectors["vectors"]]
    cases += ["RD18-092", "RD18-092-S1", "RD18-106-S1-a", "RD18-092-P2-b", "A1", "SA282B",
              "", " ", "..", ".x", "-x", "x..y", "a/b", "a b"]
    for v in cases:
        expected = (build_portal.safe_component(v) == v)
        assert stnids.station_id_is_safe(v) == expected, (
            f"charset predicate disagrees with safe_component on {v!r}: "
            f"predicate={stnids.station_id_is_safe(v)} safe_component={build_portal.safe_component(v)!r}")


def test_the_owner_id_scheme_survives_safe_component_unchanged():
    """Reported to the owner BEFORE the scheme was adopted: safe_component keeps [A-Za-z0-9._-], so
    hyphenated RD18 ids pass through untouched (no silent mangling to RD18092S1 in the catalogue)."""
    for sid in ("RD18-092", "RD18-092-S1", "RD18-106-S1-a", "RD18-000", "RD18-092-P2"):
        assert build_portal.safe_component(sid) == sid


# --------------------------------------------------------------------------------------------
# integration: the defect, and the override that fixes it
# --------------------------------------------------------------------------------------------

def test_without_the_block_a_dataid_collision_becomes_false_variants(tmp_path):
    """The DEFECT, pinned as the control for the test below: two different physical sites sharing one
    DATAID are published as `92.v1` / `92.s1`, which reads as two processings of one station."""
    surveys = _make_survey(tmp_path)
    out = tmp_path / "out"
    assert _build(surveys, out) == 0
    cat = _catalogue(out)
    assert sorted(cat) == ["92.s1", "92.v1"], f"expected the variant-tag defect, got {sorted(cat)}"
    lats = sorted(r[_col("lat")] for r in cat.values())
    assert abs(lats[1] - lats[0]) > 0.5, "the fixture must be two genuinely different sites"


def test_the_override_publishes_the_declared_ids_and_creates_no_variants(tmp_path):
    """THE lane's load-bearing assertion. With the block declared, the published ids are the
    custodian's, and `_disambiguate` sees already-unique ids so it invents NO `.a`/`.b` tag.

    FAILS on unmodified code: the block is unknown there, both stations keep DATAID '92' and are
    disambiguated into 92.a / 92.b."""
    surveys = _make_survey(tmp_path, yaml_extra=OVERRIDE_YAML)
    out = tmp_path / "out"
    assert _build(surveys, out) == 0
    cat = _catalogue(out)
    assert sorted(cat) == ["RD18-092", "RD18-092-S1"], f"published ids are {sorted(cat)}"
    for row in cat.values():
        assert "." not in row[_col("id")], f"_disambiguate invented a variant tag: {row[_col('id')]!r}"
    assert {r[_col("ausmt_id")] for r in cat.values()} == {
        "au.rd18-probe.RD18-092", "au.rd18-probe.RD18-092-S1"}


def test_the_override_keeps_the_edi_dataid_as_site_name(tmp_path):
    """The EDI is served unmodified, so its own DATAID must stay recoverable from AusMT's record.
    Reuses the EXISTING site_name convention (catalogue column 15), not a parallel mechanism."""
    surveys = _make_survey(tmp_path, yaml_extra=OVERRIDE_YAML)
    out = tmp_path / "out"
    assert _build(surveys, out) == 0
    cat = _catalogue(out)
    for sid in ("RD18-092", "RD18-092-S1"):
        assert cat[sid][_col("site_name")] == COLLIDING_DATAID, (
            f"{sid} lost the source DATAID: site_name={cat[sid][_col('site_name')]!r}")


def test_a_partial_map_leaves_unmapped_stations_on_dataid(tmp_path):
    """Partial maps are legal and must not be a silent all-or-nothing switch."""
    partial = ('station_ids:\n  source: filename\n  map:\n    "92_S1.edi": "RD18-092-S1"\n')
    surveys = _make_survey(tmp_path, yaml_extra=partial)
    out = tmp_path / "out"
    assert _build(surveys, out) == 0
    assert sorted(_catalogue(out)) == ["92", "RD18-092-S1"]


def test_a_map_key_naming_no_file_drops_the_survey_loudly(tmp_path, capsys):
    """Fail closed: a typo'd key must never leave that station published under its raw DATAID."""
    bad = ('station_ids:\n  source: filename\n  map:\n    "93.edi": "RD18-093"\n')
    surveys = _make_survey(tmp_path, yaml_extra=bad)
    out = tmp_path / "out"
    _build(surveys, out, extra=["--allow-empty"])
    err = capsys.readouterr().err
    assert "93.edi" in err and "SKIP" in err
    assert not (out / "catalogue.json").exists() or json.loads(
        (out / "catalogue.json").read_text(encoding="utf-8")) == []


def test_colliding_map_values_drop_the_survey_loudly(tmp_path, capsys):
    dup = ('station_ids:\n  source: filename\n  map:\n'
           '    "92.edi": "RD18-092"\n    "92_S1.edi": "RD18-092"\n')
    surveys = _make_survey(tmp_path, yaml_extra=dup)
    out = tmp_path / "out"
    _build(surveys, out, extra=["--allow-empty"])
    err = capsys.readouterr().err
    assert "92.edi" in err and "92_S1.edi" in err and "SKIP" in err


def test_the_override_reaches_the_manifest_and_the_served_edi_row(tmp_path):
    surveys = _make_survey(tmp_path, yaml_extra=OVERRIDE_YAML)
    out = tmp_path / "out"
    assert _build(surveys, out) == 0
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    edi_rows = {row["station"]: row for row in manifest["files"] if row["format"] == "edi"}
    assert sorted(edi_rows) == ["RD18-092", "RD18-092-S1"]
    assert edi_rows["RD18-092"]["ausmt_id"] == "au.rd18-probe.RD18-092"
    # the served bytes are still the custodian's file, under its OWN filename
    assert edi_rows["RD18-092"]["url"].endswith("/92.edi")


def test_the_override_reaches_the_served_emtf_xml(tmp_path):
    """The served XML is a DERIVED product, so it carries the published id: in its filename, in
    Site.id (alnum-stripped by the EMTF-XML pattern, as every AusMT id is) and, because that strip
    is lossy, verbatim in the Site Name source-id marker normalize() already writes."""
    surveys = _make_survey(tmp_path, yaml_extra=OVERRIDE_YAML)
    out = tmp_path / "out"
    assert _build(surveys, out) == 0
    xmls = {p.stem: p for p in (out / "xml" / "rd18-probe").glob("*.xml")}
    assert sorted(xmls) == ["RD18-092", "RD18-092-S1"], f"served XML files: {sorted(xmls)}"
    text = xmls["RD18-092"].read_text(encoding="utf-8")
    assert "<Id>RD18092</Id>" in text, "Site.id does not carry the published id"
    assert "RD18-092" in text, "the unsanitised published id is not recoverable from the XML"


def test_the_override_reaches_the_station_mth5(tmp_path):
    surveys = _make_survey(tmp_path, yaml_extra=OVERRIDE_YAML)
    out = tmp_path / "out"
    assert _build(surveys, out, extra=["--station-h5"]) == 0
    h5s = {p.stem: p for p in (out / "h5" / "rd18-probe").glob("*.h5")}
    assert sorted(h5s) == ["RD18-092", "RD18-092-S1"], f"served MTH5 files: {sorted(h5s)}"
    from mth5.mth5 import MTH5  # noqa: PLC0415
    m = MTH5()
    m.open_mth5(str(h5s["RD18-092"]), mode="r")
    try:
        stations = list(m.tf_summary.to_dataframe()["station"])
    finally:
        m.close_mth5()
    assert stations == ["RD18092"], f"MTH5 station groups: {stations}"


def test_the_override_reaches_station_json(tmp_path):
    surveys = _make_survey(tmp_path, yaml_extra=OVERRIDE_YAML)
    out = tmp_path / "out"
    prod = tmp_path / "products"
    assert _build(surveys, out, extra=["--products", str(prod)]) == 0
    doc = json.loads((prod / "rd18-probe" / "RD18-092" / "station.json").read_text(encoding="utf-8"))
    assert doc["station"] == "RD18-092"
    assert doc["ausmt_id"] == "au.rd18-probe.RD18-092"
    # provenance still names the SOURCE file, which is what the served bytes are
    assert doc["provenance"]["input_file"] == "92.edi"


def test_the_block_parses_identically_without_pyyaml():
    """The stdlib `_mini_yaml` fallback (the parser a no-PyYAML env falls back to) must read the SAME
    map PyYAML reads. Quoting is not optional for this block: real source filenames carry spaces and
    parentheses ("49R stage 1.edi", "53(RR).edi" in the Roxby delivery), which YAML can express only
    as quoted keys. A fallback that drops them would build the survey with NO override at all and
    publish the raw contractor DATAIDs, silently."""
    yaml = pytest.importorskip("yaml")
    text = (
        'name: X\nslug: x\nlicense: CC-BY-4.0\n'
        'station_ids:\n  source: filename\n  map:\n'
        '    "92.edi": "RD18-092"\n'
        '    "92_S1.edi": "RD18-092-S1"\n'
        '    "49R stage 1.edi": "RD18-049-S1"\n'
        "    '53(RR).edi': RD18-053\n"
        'country: Australia\n'
    )
    from_pyyaml = stnids.parse_station_ids((yaml.safe_load(text) or {}).get("station_ids"))
    from_mini = stnids.parse_station_ids(build_portal._mini_yaml(text).get("station_ids"))
    assert from_pyyaml.ids == {"92.edi": "RD18-092", "92_S1.edi": "RD18-092-S1",
                              "49R stage 1.edi": "RD18-049-S1", "53(RR).edi": "RD18-053"}
    assert from_mini == from_pyyaml


def test_an_untouched_survey_is_byte_identical_with_the_feature_present(tmp_path):
    """Default stability: a package with no `station_ids` block must build exactly as before."""
    surveys = _make_survey(tmp_path, slug="plain", name="Plain")
    out = tmp_path / "out"
    assert _build(surveys, out) == 0
    cat = _catalogue(out)
    assert sorted(cat) == ["92.s1", "92.v1"]
    for row in cat.values():
        assert row[_col("site_name")] is None or row[_col("site_name")] == COLLIDING_DATAID


# --------------------------------------------------------------------------------------------
# COMMIT 2: provenance for third-party ingests, and the served-bytes integrity gate
# --------------------------------------------------------------------------------------------

PROVENANCE_YAML = (
    'station_ids:\n'
    '  source: filename\n'
    '  map:\n'
    '    "92.edi":\n'
    '      id: "RD18-092"\n'
    '      source_record_id: "4572110A"\n'
    '      acquisition_stage: "2"\n'
    '    "92_S1.edi":\n'
    '      id: "RD18-092-S1"\n'
    '      source_record_id: "2781110A"\n'
    '      acquisition_stage: "1"\n'
)


def test_the_mapping_form_parses_id_and_provenance():
    parsed = stnids.parse_station_ids({"source": "filename", "map": {
        "84.edi": "RD18-084",
        "84R.edi": {"id": "RD18-084-S1-b", "source_record_id": "2781110A",
                    "acquisition_stage": "1"}}})
    assert parsed.ids == {"84.edi": "RD18-084", "84R.edi": "RD18-084-S1-b"}
    assert parsed.provenance == {"84R.edi": {"original_filename": "84R.edi",
                                             "source_record_id": "2781110A",
                                             "acquisition_stage": "1"}}


def test_original_filename_is_derived_from_the_key_not_declared():
    """It is the map KEY, so the record and the declaration can never disagree about which file the
    bytes came from. Declaring it is an unknown key and fails."""
    with pytest.raises(stnids.StationIdError):
        stnids.parse_station_ids({"source": "filename", "map": {
            "84R.edi": {"id": "X1", "original_filename": "something-else.edi"}}})


def test_provenance_without_an_id_keeps_the_dataid():
    parsed = stnids.parse_station_ids({"source": "filename",
                                       "map": {"84.edi": {"acquisition_stage": "2"}}})
    assert parsed.ids == {}
    assert parsed.provenance["84.edi"]["acquisition_stage"] == "2"


@pytest.mark.parametrize("value", [
    {"id": "X1", "stage": "1"},        # unknown key inside the mapping form
    {},                                 # says nothing at all
])
def test_a_malformed_mapping_value_fails_closed(value):
    with pytest.raises(stnids.StationIdError):
        stnids.parse_station_ids({"source": "filename", "map": {"84.edi": value}})


def test_a_provenance_only_key_naming_no_file_fails_closed():
    parsed = stnids.parse_station_ids({"source": "filename",
                                       "map": {"nope.edi": {"acquisition_stage": "1"}}})
    with pytest.raises(stnids.StationIdError) as ei:
        stnids.validate_station_ids(parsed, [Path("/pkg/92.edi")])
    assert "nope.edi" in str(ei.value)


def test_provenance_reaches_station_json(tmp_path):
    surveys = _make_survey(tmp_path, yaml_extra=PROVENANCE_YAML)
    out, prod = tmp_path / "out", tmp_path / "products"
    assert _build(surveys, out, extra=["--products", str(prod)]) == 0
    doc = json.loads((prod / "rd18-probe" / "RD18-092-S1" / "station.json").read_text(encoding="utf-8"))
    src = doc["provenance"]["source"]
    assert src == {"original_filename": "92_S1.edi", "source_record_id": "2781110A",
                   "acquisition_stage": "1"}
    # the served bytes are still the custodian's file under its own name
    assert doc["provenance"]["input_file"] == "92_S1.edi"


def test_a_survey_without_provenance_gains_no_station_json_key(tmp_path):
    """ADDITIVE and absent-means-absent: no declaration, no key, so the corpus is byte-unchanged."""
    surveys = _make_survey(tmp_path, yaml_extra=OVERRIDE_YAML)
    out, prod = tmp_path / "out", tmp_path / "products"
    assert _build(surveys, out, extra=["--products", str(prod)]) == 0
    doc = json.loads((prod / "rd18-probe" / "RD18-092" / "station.json").read_text(encoding="utf-8"))
    assert "source" not in doc["provenance"]


def test_provenance_reaches_the_station_mth5(tmp_path):
    """MTH5 carries it in station_metadata.comments, the one station-level free-text slot MEASURED to
    survive the mth5 write/read round trip on the pinned stack (provenance.comments and
    provenance.log do not; see the lane report)."""
    surveys = _make_survey(tmp_path, yaml_extra=PROVENANCE_YAML)
    out = tmp_path / "out"
    assert _build(surveys, out, extra=["--station-h5"]) == 0
    from mth5.mth5 import MTH5  # noqa: PLC0415
    m = MTH5()
    m.open_mth5(str(out / "h5" / "rd18-probe" / "RD18-092-S1.h5"), mode="r")
    try:
        row = m.tf_summary.to_dataframe().iloc[0]
        tfo = m.get_transfer_function(row["station"], row["tf_id"], survey=row["survey"])
        comments = str(tfo.station_metadata.comments.value or "")
    finally:
        m.close_mth5()
    assert "ausmt_source_file=92_S1.edi" in comments, comments[-400:]
    assert "ausmt_source_record_id=2781110A" in comments
    assert "ausmt_acquisition_stage=1" in comments


def test_provenance_reaches_the_served_emtf_xml(tmp_path):
    """EMTF XML has exactly one station-level free-text slot that survives its write/read round trip
    on the pinned mt_metadata: the Site Name, which normalize() already uses for the source-id
    marker. The source FILENAME rides the same convention so the served XML says which custodian file
    it was derived from; the rest of the provenance stays in AusMT's own records."""
    surveys = _make_survey(tmp_path, yaml_extra=PROVENANCE_YAML)
    out = tmp_path / "out"
    assert _build(surveys, out) == 0
    text = (out / "xml" / "rd18-probe" / "RD18-092-S1.xml").read_text(encoding="utf-8")
    assert "ausmt_src_file:92_S1.edi" in text, text[:1500]


def test_a_survey_without_provenance_gains_no_xml_marker(tmp_path):
    surveys = _make_survey(tmp_path, yaml_extra=OVERRIDE_YAML)
    out = tmp_path / "out"
    assert _build(surveys, out) == 0
    text = (out / "xml" / "rd18-probe" / "RD18-092.xml").read_text(encoding="utf-8")
    assert "ausmt_src_file" not in text


# ---- the served-bytes integrity gate -------------------------------------------------------

def test_build_report_records_the_source_integrity_gate(tmp_path):
    """The no-editing posture rests on ONE guarantee: what AusMT serves for an EDI-sourced station is
    byte-for-byte what the custodian supplied. That is asserted per build and recorded, not assumed."""
    surveys = _make_survey(tmp_path, yaml_extra=PROVENANCE_YAML)
    out = tmp_path / "out"
    assert _build(surveys, out) == 0
    report = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    gate = report["surveys"]["rd18-probe"]["source_integrity"]
    assert gate["checked"] == 2 and gate["verified"] == 2 and gate["mismatches"] == []


def test_the_integrity_gate_withholds_a_station_whose_served_bytes_differ(tmp_path, monkeypatch, capsys):
    """FAILS IF the gate is decorative. The COPY is replaced with one that flips a byte; the gate
    itself is untouched, so this is an independent observable of the gate, not of the copier. The
    station must serve NOTHING (no file on disk, no manifest row) and the build report must name it."""
    surveys = _make_survey(tmp_path, yaml_extra=PROVENANCE_YAML)
    out = tmp_path / "out"

    real_copy = build_portal._copy_source_bytes

    def _tampering_copy(src, dest):
        real_copy(src, dest)
        if dest.name == "92_S1.edi":
            dest.write_bytes(dest.read_bytes() + b"\n# tampered\n")

    monkeypatch.setattr(build_portal, "_copy_source_bytes", _tampering_copy)
    assert _build(surveys, out) == 0
    err = capsys.readouterr().err
    assert "92_S1.edi" in err and "integrity" in err.lower()

    report = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    gate = report["surveys"]["rd18-probe"]["source_integrity"]
    assert gate["checked"] == 2 and gate["verified"] == 1
    assert [m["station"] for m in gate["mismatches"]] == ["RD18-092-S1"]

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    edi_stations = sorted(r["station"] for r in manifest["files"] if r["format"] == "edi")
    assert edi_stations == ["RD18-092"], "a station whose served bytes differ was still manifested"
    assert not (out / "edi" / "rd18-probe" / "92_S1.edi").exists(), \
        "the non-identical copy is still fetchable in the served tree"
