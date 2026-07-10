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


def test_ccmt_uniform_zrot_served_as_stored_r3():
    """FAILS IF: a ccmt-2017 station (served survey; survey-uniform ZROT=8, ROTATION=FIX — the
    declination-class R3 case of frame POLICY v2) is ROTATED, or served without the declared
    angle recorded, or its quadrants break as-stored. Owner ruling: the archive respects
    acquisition frames; 8 deg ~ the local declination. (Supersedes the v1 '+8 deg shift' pin —
    the de-rotation SIGN is now pinned by the twin test below and the synthetic round-trips.)"""
    f = _find(REALDATA / "ccmt-2017", "CC01.edi")
    # as-read pt_az (the source acquisition frame)
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
    assert fr["derotated"] is False, "R3: ccmt must be served AS STORED (declination-class angle)"
    assert fr["frame_served"] == "declared-azimuth"
    assert fr["declared_azimuth_deg"] == 8.0
    assert any("declared acquisition frame" in n and "NOT rotated" in n
               for n in parsed["frame_notes"])
    ck = fr["convention_check"]
    assert ck["verdict"] == "ok", "quadrants must hold in the as-stored frame"
    assert 0 < ck["phs_xy_median_deg"] < 90 and -180 < ck["phs_yx_median_deg"] < -90
    # served products EQUAL the as-read source: per-period pt_az unshifted (no silent rotation)
    tf_chk = mtm.read(f)
    _, comp_chk = mtm.components_from_tf(tf_chk)
    az_chk = _az_series(comp_chk)
    assert az_chk == az_raw


def test_auslamp_pax_derotation_matches_custodian_twin():
    """FAILS IF: per-period (R1/PAX) de-rotation of a PAX-rotated AusLAMP-SA specimen does not
    reproduce the custodian's own zero-reference export to near machine precision — the strongest
    available ground truth for the de-rotation formula AND the R1 per-period disposition.

    RELOCATED (2026-07-10, architect-directed): the pin used to read the served
    ausmt-surveys/auslamp-sa files, which are scheduled for retirement (replaced by seven
    individual campaign surveys). The four twin pairs now live in the local harness at
    .audit/realdata/_specimens/auslamp-pax/{pax,zero}/ (see its README.txt) so the pin survives
    the corpus swap. _specimens is underscore-prefixed, so discover_work never builds it."""
    spec = REALDATA / "_specimens" / "auslamp-pax"
    if not spec.is_dir():
        pytest.skip("realdata corpus not present (AUSMT_REALDATA unset) — _specimens/auslamp-pax "
                    "twin specimens not found")
    import _ediparse as ep  # noqa: PLC0415
    pairs = 0
    for sp in sorted((spec / "pax").glob("*.edi")):
        hp = spec / "zero" / sp.name
        if not hp.exists():
            continue
        tf_s = mtm.read(sp)
        ev = conv.parse_frame_evidence(ep.read_norm(sp))
        assert ev["zrot"] and len(conv._uniq_eps(conv._mask_sentinels(ev["zrot"]))) > 1,             f"{sp.name}: specimen must carry per-period ZROT (PAX) for this pin to mean anything"
        disp = conv.frame_disposition(ev, tf_s._rotation_angle, conv.z_present_mask(tf_s),
                                      bool(tf_s.has_tipper()), int(tf_s.period.size))
        assert disp.action == "derotate", f"{sp.name}: expected per-period de-rotation (R1)"
        conv.apply_derotation(tf_s, disp)
        Zs = np.asarray(tf_s.impedance.data)
        Zh = np.asarray(mtm.read(hp).impedance.data)
        assert Zs.shape == Zh.shape
        keep = np.isfinite(Zs) & np.isfinite(Zh) & (np.abs(Zh) > 0) & (np.abs(Zh) < 1e8)             & (np.abs(Zs) < 1e8)
        rel = np.abs(Zs - Zh)[keep] / np.abs(Zh)[keep]
        assert rel.size and float(np.median(rel)) < 1e-6, (
            f"{sp.name}: de-rotated specimen Z does not match the custodian twin "
            f"(median rel {float(np.median(rel)):.2e})")
        pairs += 1
    assert pairs >= 3, "too few twin pairs found — the pin lost its ground truth"
