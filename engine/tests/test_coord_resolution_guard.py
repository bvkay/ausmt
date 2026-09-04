"""A declared dms_sign resolution that cannot be applied must not stamp the station resolved.

The stamp block ran unconditionally: with `dms_sign: info` declared but no usable INFO pair, the
swap was skipped yet the station was stamped dms_sign_resolved, its conflict figure erased and a
coord_resolution published for a resolution that never happened - reopening the DMS sign-bug class
(~140 km mislocation) the flag exists to catch.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "extract"))
import build_portal as bp  # noqa: E402


def _amb(cands):
    return {"id": "S1", "lat": -30.0, "lon": 136.0, "coord_flag": "dms_sign_ambiguous",
            "coord_conflict_deg": 0.9, "coord_candidates": cands}


def test_unusable_info_candidate_keeps_the_flag():
    r = _amb({"info": [-30.5, None]})     # parseable LATITUDE, no LONGITUDE: a legal catalog state
    bp._apply_coord_resolution([("s.edi", r)], {"dms_sign": "info", "basis": "ground truth"})
    assert r["coord_flag"] == "dms_sign_ambiguous", r
    assert r["coord_conflict_deg"] == 0.9, "the outstanding conflict must not be erased"
    assert "coord_resolution" not in r, "no resolution happened, so none may be published"
    assert (r["lat"], r["lon"]) == (-30.0, 136.0)


def test_usable_info_candidate_swaps_and_stamps():
    r = _amb({"info": [-30.5, 136.5]})
    bp._apply_coord_resolution([("s.edi", r)], {"dms_sign": "info", "basis": "ground truth"})
    assert (r["lat"], r["lon"]) == (-30.5, 136.5)
    assert r["coord_flag"] == "dms_sign_resolved"
    assert r["coord_resolution"]["chosen"] == "info"


def test_qc_file_identity_is_single_sourced():
    """The fid rule that binds the qc de-leak to the coordinate mask exists ONCE, in _coordaccess
    (the module whose doctrine is that validation and application share one derivation). qc_pass
    must not re-derive it with a divergent fallback (str(p) vs None), or a record with no `file`
    key and a non-Path p had its 3-dp true-position derivative survive the mask."""
    import inspect
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "extract"))
    import _coordaccess as coordacc
    assert hasattr(coordacc, "fid"), "_coordaccess must export the single fid derivation"
    src = (Path(__file__).resolve().parent.parent / "extract" / "build_portal.py").read_text(encoding="utf-8")
    assert "coordacc.fid(" in src, "qc_pass must delegate to the shared derivation"
    assert 'r.get("file") or getattr' not in src, "a second fid derivation survives in build_portal"
    assert "masked_ids" not in inspect.signature(coordacc._mask_qc_report).parameters, (
        "_mask_qc_report's unused masked_ids parameter should be gone")
