"""C25 convention gates — real-corpus pins (dev-box only; the corpus is not in the repo).

Gated on AUSMT_REALDATA pointing at the .audit/realdata harness (and, for the twin pin, a sibling
ausmt-surveys checkout). In CI these skip with an allow-listed reason (tests/ci_check_skips.py):
the corpus lives only on the dev box, exactly like the sibling-validator skip class.

These are the architect-mandated negative controls: three REAL convention-flipped USArray
stations, pinned BY NAME, prove forever that Gate 2 can fail on real bytes — and the ccmt/AusLAMP
pins prove the de-rotation against real declared-rotation surveys, including the custodian-twin
machine-precision ground truth.
"""
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "extract"))

pytest.importorskip("mt_metadata")
mtm = pytest.importorskip("_mtm")
conv = pytest.importorskip("_conventions")
bp = pytest.importorskip("build_portal")
np = pytest.importorskip("numpy")

_REALDATA = os.environ.get("AUSMT_REALDATA", "")
pytestmark = pytest.mark.skipif(
    not (_REALDATA and Path(_REALDATA).is_dir()),
    reason="realdata corpus not present (AUSMT_REALDATA unset) — dev-box-only real-corpus pins")

REALDATA = Path(_REALDATA) if _REALDATA else Path(".")

# The three REAL convention-flipped stations (both off-diagonal medians coherently out of
# quadrant: arg Zxy ~ -140..-124 (Q3), arg Zyx ~ +34..+44 (Q1) — the axis-swap/convention class).
# Pinned BY NAME per the adjudication: Gate 2 FAILING these is the living proof it can fail.
NEGATIVE_CONTROLS = [
    "USArray.TTW52.2016.edi",
    "USArray.VAS56.2016.edi",
    "USMTArray.CAR05.2019.edi",
]


def _find(root, name):
    for f in Path(root).rglob(name):
        return f
    raise AssertionError(f"{name} not found under {root}")


def test_negative_controls_fail_gate2():
    """FAILS IF: the gate stops catching ANY of the three real convention-flipped USArray
    stations — i.e. Gate 2 lost the ability to fail on real bytes (Invariant 10). One test (not
    parametrized) so the skip-accounting tripwire's one-line-per-skip arithmetic holds; each
    control is still pinned by name in its assert message."""
    for name in NEGATIVE_CONTROLS:
        parsed = bp._parse_one_edi(_find(REALDATA / "usarray", name))
        assert "skip" in parsed, f"{name} must FAIL the sign-convention gate"
        assert parsed["skip"]["gate"] == "sign-convention", name
        assert "BOTH off-diagonal phase medians" in parsed["skip"]["reason"], name


def test_no_other_usarray_station_fails():
    """FAILS IF: the gate starts catching anything in the usarray harness beyond the three named
    negative controls — the harness false-positive budget is exactly those three. (Full scan;
    ~2 min on the dev box, opt-in by construction.)"""
    fails = []
    for f in sorted((REALDATA / "usarray").rglob("*.edi")):
        try:
            parsed = bp._parse_one_edi(f)
        except Exception:  # noqa: BLE001  (unreadable files are the legacy skip path, not a gate)
            continue
        if "skip" in parsed:
            fails.append(f.name)
    assert sorted(fails) == sorted(NEGATIVE_CONTROLS), (
        f"usarray gate failures diverged from the pinned negative controls: {fails}")


def test_ccmt_uniform_zrot_derotation_acceptance():
    """FAILS IF: a ccmt-2017 station (served survey; uniform ZROT=8, ROTATION=FIX) is not
    de-rotated, its quadrants break after de-rotation, or its PT azimuth does not shift by
    exactly the de-rotation angle (axial +8 deg — the empirically-pinned sign)."""
    f = _find(REALDATA / "ccmt-2017", "CC01.edi")
    # as-read (no gate): PT azimuth in the source (rotated) frame
    tf_raw = mtm.read(f)
    per, comp_raw = mtm.components_from_tf(tf_raw)
    import _ediparse as ep  # noqa: PLC0415
    def _az_series(comp):
        out = []
        for i in range(len(per)):
            vals = [comp[k][i] if comp.get(k) else None for k in
                    ("ZXXR", "ZXXI", "ZXYR", "ZXYI", "ZYXR", "ZYXI", "ZYYR", "ZYYI")]
            a = ep.pt_params(*vals)[2]
            if a is not None:
                out.append(a)
        return out
    az_raw = _az_series(comp_raw)

    parsed = bp._parse_one_edi(f)
    assert "skip" not in parsed
    fr = parsed["frame"]
    assert fr["derotated"] is True and fr["impedance_rotation_deg_source"] == 8.0
    ck = fr["convention_check"]
    assert ck["verdict"] == "ok", "quadrants must remain Q1/Q3 after de-rotation"
    assert 0 < ck["phs_xy_median_deg"] < 90 and -180 < ck["phs_yx_median_deg"] < -90
    # axial shift: de-rotating a frame at +8 deg moves pt_az by exactly +8 (mod 180)
    tf_d = mtm.read(f)
    ev = conv.parse_frame_evidence(__import__("_ediparse").read_norm(f))
    disp = conv.frame_disposition(ev, tf_d._rotation_angle, conv.z_present_mask(tf_d),
                                  bool(tf_d.has_tipper()), int(tf_d.period.size))
    conv.apply_derotation(tf_d, disp)
    _, comp_d = mtm.components_from_tf(tf_d)
    az_d = _az_series(comp_d)
    assert len(az_d) == len(az_raw)
    diffs = [((b - a) % 180.0) for a, b in zip(az_raw, az_d)]
    diffs = [d - 180.0 if d > 90 else d for d in diffs]
    assert max(abs(d - 8.0) for d in diffs) < 0.01, "pt_az must shift by exactly +8 deg per period"


def test_auslamp_pax_derotation_matches_custodian_twin():
    """FAILS IF: per-period (PAX) de-rotation of a served AusLAMP-SA station does not reproduce
    the custodian's own geographic-frame export (the harness twin) to near machine precision —
    the strongest available ground truth for the de-rotation formula AND for the per-period
    disposition that keeps the flagship servable."""
    served_root = Path(__file__).resolve()
    for up in served_root.parents:
        cand = up / "ausmt-surveys" / "surveys" / "auslamp-sa"
        if cand.is_dir():
            served = cand
            break
    else:
        pytest.skip("realdata corpus not present (AUSMT_REALDATA unset) — sibling ausmt-surveys "
                    "checkout with auslamp-sa not found for the twin pin")
    pairs = 0
    for name in ("SA066.edi", "SA069.edi", "SA227.edi", "SA242.edi"):
        sp = served / "transfer_functions" / "edi" / name
        hp = None
        for sub in ("auslamp-sa-1-musgraves", "auslamp-sa-2-gawler"):
            c = REALDATA / sub / "transfer_functions" / "edi" / name
            if c.exists():
                hp = c
                break
        if not (sp.exists() and hp):
            continue
        tf_s = mtm.read(sp)
        ev = conv.parse_frame_evidence(__import__("_ediparse").read_norm(sp))
        assert ev["zrot"] and len(conv._uniq_eps(conv._mask_sentinels(ev["zrot"]))) > 1, \
            f"{name}: served twin must carry per-period ZROT (PAX) for this pin to mean anything"
        disp = conv.frame_disposition(ev, tf_s._rotation_angle, conv.z_present_mask(tf_s),
                                      bool(tf_s.has_tipper()), int(tf_s.period.size))
        assert disp.action == "derotate", f"{name}: expected per-period de-rotation"
        conv.apply_derotation(tf_s, disp)
        Zs = np.asarray(tf_s.impedance.data)
        Zh = np.asarray(mtm.read(hp).impedance.data)
        assert Zs.shape == Zh.shape
        keep = np.isfinite(Zs) & np.isfinite(Zh) & (np.abs(Zh) > 0) & (np.abs(Zh) < 1e8) \
            & (np.abs(Zs) < 1e8)
        rel = np.abs(Zs - Zh)[keep] / np.abs(Zh)[keep]
        assert rel.size and float(np.median(rel)) < 1e-6, (
            f"{name}: de-rotated served Z does not match the custodian twin "
            f"(median rel {float(np.median(rel)):.2e})")
        pairs += 1
    assert pairs >= 3, "too few twin pairs found — the pin lost its ground truth"
