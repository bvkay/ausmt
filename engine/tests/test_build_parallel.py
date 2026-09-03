"""Build parallelism (the MTH5 worker pool) -- serial==parallel product equivalence.

The profile attributed ~68% of a cold
build and ~99% of a warm rebuild to _write_tf_mth5. The pool parallelises exactly that seam: the
tier-1 per-station fan-out (emit_station_mth5) and the tier-2 survey bundle (emit_survey_mth5),
each task a self-contained _write_tf_mth5 call that re-reads its source EDI in the worker. The
parse and XML seams, the C18 cache and every piece of manifest bookkeeping stay in the main
process; _disambiguate has already finalised every station id before the first write is
submitted, so worker scheduling can never reach an identity decision.

The contract these tests pin: a --workers N build is INDISTINGUISHABLE from a --workers 1 build
everywhere a byte can be compared, and semantically identical where HDF5 forbids byte comparison
(an .h5 embeds write-time clocks; its manifest sha256 is a this-build integrity hash, not a
cross-build invariant -- _write_tf_mth5's own NOTE). Two FRESH builds differ in exactly three
places, all of them deliberate build records rather than leaks:

  * products/*/*/station.json and products/*/survey-metadata.json: provenance.generated,
  * mtcat.json: portal.generated_at,
  * the .h5 files and the manifest sha256 rows over them,

plus the build.json / build_provenance.json / build_report.json build records (timings and wall
stamps by design). The served EDI, the served EMTF XML and BOTH zips are byte-compared with no
exemption: their published digests are cross-build invariants (C18 Amendment A5), so a
<CreateTime> or a zip-metadata leak fails here rather than being normalised away. The comparator
normalises ONLY the places above and byte-compares everything else, default-deny: a file with no
rule is byte-compared, so any NEW nondeterminism the pool introduced fails loudly instead of being
quietly excused. catalogue.json, tf.json and sci.json are byte-stable fresh-vs-fresh, so the
positional order pin on tf/sci stays byte-level.
"""
import json
import os
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("mt_metadata")
pytest.importorskip("mth5")

import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "extract"))
sys.path.insert(0, str(REPO))
import build_portal  # noqa: E402

SAMPLE_EDIS = sorted((REPO / "data" / "sample-survey" / "transfer_functions" / "edi").glob("*.edi"))


@pytest.fixture(autouse=True)
def _no_ambient_workers(monkeypatch):
    """The env default must never leak into a test's serial build."""
    monkeypatch.delenv("AUSMT_BUILD_WORKERS", raising=False)


def _make_corpus(tmp_path):
    """Two surveys from the real sample EDIs. par-b carries a DUPLICATE-station-id EDI (same DATAID
    under a second filename), so _disambiguate's order-sensitive variant tagging is exercised
    end-to-end: if worker scheduling could ever perturb identity, tf.json/sci.json (positional,
    byte-compared) and the manifest station ids would differ here."""
    assert len(SAMPLE_EDIS) >= 2, "sample survey fixture missing"
    root = tmp_path / "surveys"
    for slug, name in (("par-a", "Par A"), ("par-b", "Par B")):
        edir = root / slug / "transfer_functions" / "edi"
        edir.mkdir(parents=True)
        (root / slug / "survey.yaml").write_text(
            f"name: {name}\nslug: {slug}\ncountry: Australia\norganisation: Test Org\n"
            "access: open\nlicense: CC-BY-4.0\n", encoding="utf-8")
        for src in SAMPLE_EDIS:
            (edir / src.name).write_text(src.read_text(encoding="latin-1"), encoding="latin-1")
    dup_src = SAMPLE_EDIS[0]
    dup = root / "par-b" / "transfer_functions" / "edi" / f"{dup_src.stem}_Ohmega.edi"
    dup.write_text(dup_src.read_text(encoding="latin-1"), encoding="latin-1")
    return root


def _build(surveys, out, workers):
    rc = build_portal.main([
        "--surveys", str(surveys), "--out", str(out),
        "--bundle-edi", "--survey-h5", "--station-h5", "--no-validate",
        "--workers", str(workers)])
    assert rc == 0, f"build rc={rc} (workers={workers})"


def _h5_dump(hpath):
    """Reopen a built MTH5 (the roundtrip gate's own read idiom) and return, per stored station,
    the impedance/tipper arrays and coordinates. Serial and parallel builds parse the same source
    bytes with the same libraries, so the comparison is EXACT equality, not tolerance."""
    from mth5.mth5 import MTH5  # noqa: PLC0415
    m = MTH5()
    m.open_mth5(str(hpath), mode="r")
    dump = {}
    try:
        for _, row in m.tf_summary.to_dataframe().iterrows():
            build_portal._release_mth5_metadata_classes()
            sid = row["station"]
            tf = m.get_transfer_function(sid, row.get("tf_id", sid), survey=row.get("survey"))
            dump[sid] = {
                "z": np.asarray(tf.impedance) if tf.has_impedance() else None,
                "t": np.asarray(tf.tipper) if tf.has_tipper() else None,
                "lat": tf.latitude, "lon": tf.longitude, "elev": tf.elevation,
            }
    finally:
        m.close_mth5()
        build_portal._release_mth5_metadata_classes()
    return dump


def _assert_h5_equal(a, b, rel):
    da, db = _h5_dump(a), _h5_dump(b)
    assert sorted(da) == sorted(db), f"{rel}: station sets differ serial-vs-parallel"
    for sid in da:
        sa, sb = da[sid], db[sid]
        for k in ("lat", "lon", "elev"):
            assert sa[k] == sb[k], f"{rel}:{sid}: {k} differs"
        for k in ("z", "t"):
            if sa[k] is None or sb[k] is None:
                assert (sa[k] is None) == (sb[k] is None), f"{rel}:{sid}: {k} presence differs"
                continue
            assert np.array_equal(sa[k], sb[k]), f"{rel}:{sid}: {k} arrays differ"


def _norm_manifest(out):
    """Sha256 is normalised ONLY on mth5 rows, whose bytes legitimately carry HDF5 write clocks; the
    EDI, EMTF XML and both zip rows keep their digests compared, because those digests are the
    cross-build invariant the download reference publishes. Every size, h5 included, is a
    deterministic pin and stays compared.

    KNOWN LIMIT of the h5 size pin, adjudicated at corpus scale: a MULTI-TF bundle's
    size can wiggle a few KB with the writing process's accumulated history (serial corpus main
    process vs anything with a shorter history), because channel_summary's hdf5_reference columns
    encode internal file addresses; every value column stays identical and fresh single-survey
    builds are size-identical serial-and-pooled. At this fixture's scale (two tiny surveys) the
    sizes have been stable across every run; if this test ever fails on an h5 size by a small
    delta with equal content, that finding is the explanation and the right fix is to normalise
    mth5 BUNDLE row sizes here too, not to suspect the pool."""
    doc = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    for key in ("files", "bundles"):
        for row in doc.get(key, []):
            if row.get("format") == "mth5":
                row["sha256"] = "NORMALISED"
    doc.get("portal", {}).pop("generated_at", None)
    doc.pop("generated_at", None)
    return doc


def _norm_json(path, drop):
    doc = json.loads(path.read_text(encoding="utf-8"))
    cur = doc
    for k in drop[:-1]:
        cur = cur.get(k, {})
    cur.pop(drop[-1], None)
    return json.dumps(doc, sort_keys=True)


def test_parallel_build_products_identical_to_serial(tmp_path):
    """FAILS IF: a --workers 3 build differs from a --workers 1 build in ANY served surface beyond
    the three enumerated build records and the h5 bytes HDF5 timestamps make unrepeatable (whose
    CONTENT is compared exactly instead). Default-deny: an unmatched file is byte-compared."""
    surveys = _make_corpus(tmp_path)
    o_ser, o_par = tmp_path / "serial", tmp_path / "parallel"
    _build(surveys, o_ser, workers=1)
    pythonpath_before = os.environ.get("PYTHONPATH")
    _build(surveys, o_par, workers=3)
    # The pool start window sets PYTHONPATH so spawn children can import build_portal; it MUST be
    # restored before the build proceeds. A leak reaches every subprocess the build or a LATER
    # test shells (test_proc_info_survives_a_missing_writer_vocabulary failed exactly this way:
    # its probe requires the bare extract/ sibling to be unimportable, and the leaked path made
    # it importable).
    assert os.environ.get("PYTHONPATH") == pythonpath_before, \
        "a parallel build leaked PYTHONPATH into the parent environment"

    tree_ser = sorted(p.relative_to(o_ser).as_posix() for p in o_ser.rglob("*") if p.is_file())
    tree_par = sorted(p.relative_to(o_par).as_posix() for p in o_par.rglob("*") if p.is_file())
    assert tree_ser == tree_par, "file sets differ serial-vs-parallel"

    # Fixture guards: the run must actually have exercised what it claims to pin. Without these,
    # a silently-skipped h5 tier or a non-colliding duplicate would make the equivalence vacuous.
    man = json.loads((o_ser / "manifest.json").read_text(encoding="utf-8"))
    h5_files = [r for r in man["files"] if r["format"] == "mth5"]
    h5_bundles = [r for r in man["bundles"] if r["format"] == "mth5"]
    assert len(h5_files) >= 5, f"expected >=5 station h5 rows, got {len(h5_files)}"
    assert len(h5_bundles) == 2, f"expected 2 survey h5 bundles, got {len(h5_bundles)}"
    parb_ids = sorted({r["station"] for r in man["files"] if r["survey"] == "Par B"})
    assert len(parb_ids) == 3, f"par-b should serve 3 stations, got {parb_ids}"
    assert sum("." in s for s in parb_ids) >= 2, \
        f"duplicate-DATAID fixture did not collide (no variant tags): {parb_ids}"

    for rel in tree_ser:
        a, b = o_ser / rel, o_par / rel
        name = Path(rel).name
        if rel in ("build.json", "build_provenance.json", "build_report.json") \
                or name == "manifest.json" and rel != "manifest.json":
            continue  # build records (wall stamps + timings by design); products/ manifest mirrors root
        if name.endswith(".h5"):
            _assert_h5_equal(a, b, rel)
        elif rel == "manifest.json":
            assert _norm_manifest(o_ser) == _norm_manifest(o_par), \
                "manifest differs beyond the h5 sha256 stamps"
        elif name == "mtcat.json":
            assert _norm_json(a, ["portal", "generated_at"]) == _norm_json(b, ["portal", "generated_at"]), \
                "mtcat.json differs beyond generated_at"
        elif name == "station.json":
            assert _norm_json(a, ["provenance", "generated"]) == _norm_json(b, ["provenance", "generated"]), \
                f"{rel} differs beyond provenance.generated"
        elif name == "survey-metadata.json":
            assert _norm_json(a, ["provenance", "generated"]) == _norm_json(b, ["provenance", "generated"]), \
                f"{rel} differs beyond provenance.generated"
        else:
            assert a.read_bytes() == b.read_bytes(), f"{rel} differs serial-vs-parallel"

    # The worker count is provenance: an operator reading a build record can see how it was made.
    prov_s = json.loads((o_ser / "build_provenance.json").read_text(encoding="utf-8"))
    prov_p = json.loads((o_par / "build_provenance.json").read_text(encoding="utf-8"))
    assert prov_s["parallel"]["workers"] == 1
    assert prov_p["parallel"]["workers"] == 3


def test_mth5_write_task_captures_stderr(tmp_path, capfd):
    """FAILS IF: a worker task's WARN lines leak to the live stderr stream instead of being
    returned for the main process to replay in input order. Interleaved worker writes would make
    build logs nondeterministic under parallelism; the capture-and-replay contract is what keeps
    them stable. (C-level HDF5 error spew still goes to fd 2 and is accepted, as it is serially.)"""
    bogus = tmp_path / "not_an_edi.edi"
    bogus.write_text("JUNK, not an EDI", encoding="utf-8")
    n, err = build_portal._mth5_write_task(
        [(str(bogus), {"id": "X1"})], "par-x", "Par X", str(tmp_path / "x.h5"), None)
    assert n == 0
    assert "WARN" in err, f"expected the writer's WARN in the captured stream, got: {err!r}"
    live = capfd.readouterr()
    assert "WARN" not in live.err, "worker WARN leaked to live stderr instead of the captured return"
    assert not (tmp_path / "x.h5").exists(), "a zero-written h5 must be withheld (unlinked)"
