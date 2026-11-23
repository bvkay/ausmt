"""The MTH5 writers store the parse the engine reader returns.

The station file, the survey bundle, the collection bundle and the round-trip gate's reference all
read a source EDI through extract/_mtm.py, so a multi-section EPI-KIT file stores its section of
record and a file whose DATAID the stock reader refuses still gets an MTH5.
Requires the mt_metadata/mth5 build stack; skips cleanly otherwise.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("mt_metadata")
pytest.importorskip("mth5")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FIX = HERE / "fixtures" / "epikit"
sys.path[:0] = [str(ROOT), str(ROOT / "extract")]

import _mtm as mtm                                         # noqa: E402
import build_portal as bp                                  # noqa: E402
from test_epikit_dataid_charset import _with_dataid        # noqa: E402
from test_epikit_section_of_record import _section_zxyr    # noqa: E402

TWO_SECTION = FIX / "copper-two-section.edi"      # Wp01_avg then XPR-0, both fully populated
NO_AVG = FIX / "copper-no-avg-section.edi"        # XPR-0 then XPR-99, the last one empty
CHARSET = FIX / "roxby-dataid-charset.edi"        # DATAID "53(RR)", which the stock reader refuses
SINGLE = ROOT / "data" / "sample-survey" / "transfer_functions" / "edi" / "Vulcan_A1.edi"
OTHER = SINGLE.with_name("Vulcan_A2.edi")

SLUG, LABEL = "epikit-probe", "EPI-KIT Probe"


def _z(tf):
    """The impedance tensor as a complex array, or None when the object holds none."""
    return np.asarray(tf.impedance.values) if tf.has_impedance() else None


def _engine_tf(path):
    return mtm.read_with_parse_facts(Path(path))[0]


def _stock_tf(path):
    """The stock reader's own parse, with none of the engine reader's conditioning."""
    from mt_metadata.transfer_functions.core import TF  # noqa: PLC0415
    tf = TF(fn=str(path))
    tf.read()
    return tf


def _same(a, b):
    return a is not None and b is not None and a.shape == b.shape \
        and bool(np.array_equal(a, b, equal_nan=True))


def _stored(hpath):
    """{(survey, station): {z, comments}} for every transfer function in a built MTH5."""
    from mth5.mth5 import MTH5  # noqa: PLC0415
    m = MTH5()
    m.open_mth5(str(hpath), mode="r")
    out = {}
    try:
        for _, row in m.tf_summary.to_dataframe().iterrows():
            tf = m.get_transfer_function(row["station"], row["tf_id"], survey=row["survey"])
            assert tf.survey_metadata.id == row["survey"] and tf.station_metadata.id == row["station"]
            out[(row["survey"], row["station"])] = {
                "z": _z(tf), "comments": str(tf.station_metadata.comments.value or "")}
    finally:
        m.close_mth5()
    return out


def _assert_engine_parse(z, path, sectid):
    """`z` is the engine reader's parse of `path` and carries the named section's own ZXYR block."""
    assert _same(z, _z(_engine_tf(path))), f"{path.name}: not the engine reader's parse"
    assert [float(v) for v in z[:, 0, 1].real] == _section_zxyr(path, sectid)


def _assert_no_source_path(hpath, source, marker):
    """No stored string names the source file or a temporary copy of it. `marker` is a string the
    file must hold, which proves the scan reads stored strings at all."""
    data = Path(hpath).read_bytes()
    assert marker.encode("utf-8") in data, f"the scan cannot see stored strings: {marker!r} not found"
    assert Path(source).name.encode("utf-8") not in data
    assert b"ausmt-edi-" not in data


def _store(tf, hpath, station_id):
    """Write one transfer function into a new MTH5 with the library alone, not the engine writer."""
    from mth5.mth5 import MTH5  # noqa: PLC0415
    tf.survey_metadata.id = SLUG
    tf.station_metadata.id = station_id
    m = MTH5()
    m.open_mth5(str(hpath), mode="w")
    try:
        m.add_transfer_function(tf)
    finally:
        m.close_mth5()


def _alter_one_stored_value(hpath):
    import h5py  # noqa: PLC0415
    targets = []
    with h5py.File(hpath, "r+") as f:
        f.visititems(lambda name, obj: targets.append(name)
                     if isinstance(obj, h5py.Dataset) and name.endswith("transfer_function") else None)
        assert targets, "expected a transfer_function dataset in the built file"
        d = f[targets[0]]
        d[0, 1, 0] = d[0, 1, 0] + (1.0e6 + 1.0e6j)


# --------------------------------------------------------------------------- the three tiers

def test_a_station_file_stores_the_averaged_section(tmp_path):
    """Fails if the per-station file holds the last section the stock reader met."""
    rows = []
    written = bp.emit_station_mth5([(TWO_SECTION, {"id": "WP01"})], SLUG, LABEL, tmp_path / "h5",
                                   failure_rows=rows)
    assert rows == [] and list(written) == ["WP01"], (rows, written)
    stored = _stored(written["WP01"])
    assert list(stored) == [(SLUG, "WP01")]
    z = stored[(SLUG, "WP01")]["z"]
    _assert_engine_parse(z, TWO_SECTION, "Wp01_avg")
    assert not _same(z, _z(_stock_tf(TWO_SECTION))), "the file holds the stock reader's last section"
    _assert_no_source_path(written["WP01"], TWO_SECTION, SLUG)


def test_a_survey_bundle_stores_the_averaged_section(tmp_path):
    """Fails if the bundle holds the last section for a multi-section member, or changes what a
    single-section member stores."""
    stations = [(TWO_SECTION, {"id": "WP01"}), (SINGLE, {"id": "VulcanA1"})]
    rows = []
    _rel, hp, n = bp.emit_survey_mth5(stations, SLUG, LABEL, tmp_path, failure_rows=rows)
    assert n == 2 and rows == [], (n, rows)
    stored = _stored(hp)
    assert sorted(stored) == [(SLUG, "VulcanA1"), (SLUG, "WP01")]
    z = stored[(SLUG, "WP01")]["z"]
    _assert_engine_parse(z, TWO_SECTION, "Wp01_avg")
    assert not _same(z, _z(_stock_tf(TWO_SECTION))), "the bundle holds the stock reader's last section"
    assert _same(stored[(SLUG, "VulcanA1")]["z"], _z(_stock_tf(SINGLE)))


def test_with_no_averaged_section_the_file_stores_the_first(tmp_path):
    """Fails if the file holds the last section, which in this fixture carries only the empty-value
    sentinel and so stores no impedance at all."""
    assert _z(_stock_tf(NO_AVG)) is None, "the fixture's last section must hold no impedance"
    hp = tmp_path / "WP01.h5"
    rows = []
    assert bp._write_tf_mth5([(NO_AVG, {"id": "WP01"})], SLUG, LABEL, hp, failure_rows=rows) == 1
    assert rows == []
    z = _stored(hp)[(SLUG, "WP01")]["z"]
    assert z is not None, "the file stores no impedance"
    _assert_engine_parse(z, NO_AVG, "XPR-0")


def test_a_dataid_the_stock_reader_refuses_still_gets_a_file(tmp_path):
    """Fails if the station is recorded as a write failure and gets no file. The stored station id,
    survey id and source provenance are the record's, as for any other station."""
    with pytest.raises(Exception, match="invalid characters"):
        _stock_tf(CHARSET)
    record = {"id": "RD18-053a",
              "source_provenance": {"original_filename": "53(RR).edi", "source_record_id": "53(RR)"}}
    hp = tmp_path / "RD18-053a.h5"
    rows = []
    n = bp._write_tf_mth5([(CHARSET, record)], SLUG, LABEL, hp, failure_rows=rows)
    assert rows == [] and n == 1 and hp.exists(), (n, rows)
    stored = _stored(hp)
    assert list(stored) == [(SLUG, "RD18053a")]
    one = stored[(SLUG, "RD18053a")]
    _assert_engine_parse(one["z"], CHARSET, "53(RR)_avg")
    assert "ausmt_source_file=53(RR).edi" in one["comments"]
    assert "ausmt_source_record_id=53(RR)" in one["comments"]
    _assert_no_source_path(hp, CHARSET, "ausmt_source_file=53(RR).edi")


def test_a_collection_bundle_stores_the_section_of_record(tmp_path):
    """Fails if the collection writer holds the last section for either member. The two members
    share a station id, so each is compared with its own survey's source."""
    members = [("survey-a", "Survey A", [(TWO_SECTION, {"id": "WP01"})]),
               ("survey-b", "Survey B", [(NO_AVG, {"id": "WP01"})])]
    _rel, hp, n = bp.emit_collection_mth5(members, "collx", tmp_path)
    assert n == 2 and hp and hp.exists()
    stored = _stored(hp)
    assert sorted(stored) == [("survey-a", "WP01"), ("survey-b", "WP01")]
    _assert_engine_parse(stored[("survey-a", "WP01")]["z"], TWO_SECTION, "Wp01_avg")
    assert not _same(stored[("survey-a", "WP01")]["z"], _z(_stock_tf(TWO_SECTION)))
    assert stored[("survey-b", "WP01")]["z"] is not None, "the second member stores no impedance"
    _assert_engine_parse(stored[("survey-b", "WP01")]["z"], NO_AVG, "XPR-0")


def test_only_a_source_that_does_not_parse_is_recorded_and_skipped(tmp_path):
    """Fails if an unreadable source raises out of the writer or costs another station its place,
    or if a source the engine reader reads is recorded as a failure beside it."""
    junk = tmp_path / "not_an_edi.edi"
    junk.write_text("JUNK, not an EDI", encoding="utf-8")
    stations = [(junk, {"id": "X1"}), (CHARSET, {"id": "RD18-053a"}), (TWO_SECTION, {"id": "WP01"})]
    rows = []
    hp = tmp_path / "bundle-tf.h5"
    n = bp._write_tf_mth5(stations, SLUG, LABEL, hp, failure_rows=rows, context="survey bundle")
    assert [(r["producer"], r["file"], r["context"]) for r in rows] == \
        [("h5", "not_an_edi.edi", "survey bundle")], rows
    assert n == 2 and sorted(_stored(hp)) == [(SLUG, "RD18053a"), (SLUG, "WP01")]


def test_a_normalised_id_the_summary_table_cannot_address_is_recorded_and_skipped(tmp_path, capsys):
    """Fails if a DATAID the engine reader normalises to more than the summary table's tf_id column
    is written: the gate cannot find it again and withholds the whole file, the other station too."""
    long_id = _with_dataid(tmp_path / "long.edi", SINGLE, "P=A1 M=A2 R=REMOTE REFERENCE SITE (H)")
    rows = []
    hp = tmp_path / "bundle-tf.h5"
    n = bp._write_tf_mth5([(long_id, {"id": "A1"}), (OTHER, {"id": "A2"})], SLUG, LABEL, hp,
                          failure_rows=rows, context="survey bundle")
    assert [(r["file"], r["error"]) for r in rows] == [("long.edi", "ValueError")], rows
    assert "summary table" in rows[0]["message"], rows
    assert n == 1 and list(_stored(hp)) == [(SLUG, "A2")]
    alone = []
    assert bp.emit_station_mth5([(long_id, {"id": "A1"})], SLUG, LABEL, tmp_path / "h5",
                                failure_rows=alone) == {}
    assert [(r["file"], r["error"]) for r in alone] == [("long.edi", "ValueError")], alone
    assert "WITHHOLD" not in capsys.readouterr().err, "the station is skipped, not caught by the gate"


def test_a_collection_skips_a_member_the_summary_table_cannot_address(tmp_path, capsys):
    """Fails if the collection writer stores an id longer than the summary table's tf_id column,
    as the source carries it or as the engine reader normalises it: the gate cannot find it again
    and withholds the whole collection."""
    carried = _with_dataid(tmp_path / "carried.edi", SINGLE, "VULCAN_A1_MERGED_WITH_VULCAN_A2_REMOTE")
    normalised = _with_dataid(tmp_path / "normalised.edi", SINGLE,
                              "P=A1 M=A2 R=REMOTE REFERENCE SITE (H)")
    members = [("survey-a", "Survey A", [(carried, {"id": "A1"}), (OTHER, {"id": "A2"})]),
               ("survey-b", "Survey B", [(normalised, {"id": "B1"}), (SINGLE, {"id": "B2"})])]
    _rel, hp, n = bp.emit_collection_mth5(members, "collx", tmp_path)
    err = capsys.readouterr().err
    assert "WITHHOLD" not in err, "the members are skipped, not caught by the gate"
    assert "WARN carried.edi: ValueError" in err and "WARN normalised.edi: ValueError" in err, err
    assert n == 2 and hp and hp.exists()
    assert sorted(_stored(hp)) == [("survey-a", "A2"), ("survey-b", "B2")]


# --------------------------------------------------------------------------- the round-trip gate

def test_the_gate_passes_a_file_holding_the_section_of_record(tmp_path):
    """Fails if the gate's reference is the stock reader's parse, which refuses the correct file."""
    hp = tmp_path / "of-record.h5"
    _store(_engine_tf(TWO_SECTION), hp, "WP01")
    ok, rep = bp.mth5_survey_roundtrip_ok(hp, [(TWO_SECTION, {"id": "WP01"})])
    assert ok, rep
    assert rep["checked"] == 1 and rep["z_max_abs_diff"] == 0.0, rep


def test_the_gate_withholds_a_file_holding_the_last_section(tmp_path):
    """Fails if the gate compares a file with the same stock parse that wrote it, so a file holding
    a realisation in place of the averaged solution passes."""
    hp = tmp_path / "last-section.h5"
    _store(_stock_tf(TWO_SECTION), hp, "WP01")
    ok, rep = bp.mth5_survey_roundtrip_ok(hp, [(TWO_SECTION, {"id": "WP01"})])
    assert ok is False, rep
    assert any("impedance" in mm["reason"] for mm in rep["mismatches"]), rep


def test_the_gate_withholds_a_written_file_whose_values_are_altered(tmp_path):
    """Fails if the writer's own file does not hold the section of record, if the gate refuses that
    file, or if the gate passes it after one stored impedance value is changed."""
    stations = [(TWO_SECTION, {"id": "WP01"})]
    hp = tmp_path / "WP01.h5"
    assert bp._write_tf_mth5(stations, SLUG, LABEL, hp) == 1
    _assert_engine_parse(_stored(hp)[(SLUG, "WP01")]["z"], TWO_SECTION, "Wp01_avg")
    ok, rep = bp.mth5_survey_roundtrip_ok(hp, stations)
    assert ok and rep["checked"] == 1 and rep["z_max_abs_diff"] == 0.0, rep
    _alter_one_stored_value(hp)
    ok, rep = bp.mth5_survey_roundtrip_ok(hp, stations)
    assert ok is False, "an altered impedance value must fail the round-trip gate"
    assert any("impedance" in mm["reason"] for mm in rep["mismatches"]), rep


# --------------------------------------------------------------------------- the worker pool

def test_the_worker_pool_stores_what_the_serial_writer_stores(tmp_path):
    """Fails if a pool worker stores a different parse from the serial path, or either path stores
    the last section."""
    stations = [(TWO_SECTION, {"id": "WP01"}), (NO_AVG, {"id": "WP02"})]
    serial = bp.emit_station_mth5(stations, SLUG, LABEL, tmp_path / "serial")
    assert bp._mth5_pool_start(2) == 2, "the pool did not start, so the pool path is not exercised"
    try:
        pooled = bp.emit_station_mth5(stations, SLUG, LABEL, tmp_path / "pooled")
    finally:
        bp._mth5_pool_stop()
    assert sorted(serial) == sorted(pooled) == ["WP01", "WP02"], (serial, pooled)
    for sid, path, sectid in (("WP01", TWO_SECTION, "Wp01_avg"), ("WP02", NO_AVG, "XPR-0")):
        z_serial = _stored(serial[sid])[(SLUG, sid)]["z"]
        z_pooled = _stored(pooled[sid])[(SLUG, sid)]["z"]
        assert _same(z_serial, z_pooled), f"{sid}: the pool and the serial path store different values"
        _assert_engine_parse(z_pooled, path, sectid)
