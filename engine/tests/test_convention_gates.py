"""C25 convention gates (T1.1 rotation/frame guard + T1.2 sign-convention quadrant check).

Every fixture here is generated AT RUNTIME by text-transforming the in-repo clean stations
(data/sample-survey Vulcan_A1 for the impedance branch; tests/real_dialects phoenix_empower_A01
for the spectra branch) — no rotated real-survey file is copied into the repo (rights). Each
transform test asserts its own PRECONDITION (the fixture really is rotated/conjugated as-read),
so a test cannot pass vacuously against an unrotated fixture; and one adversarial meta-pin proves
the round-trip assertion CAN fail (a wrong-signed de-rotation is caught), permanently — not just
in a one-off red run (Invariant 10).

POLICY v3 (owner ruling 2026-07-11): the engine NEVER rotates served data. A survey-uniform declared
frame of ANY magnitude serves AS STORED with the angle recorded (V3-A); survey-inconsistent frames
serve as-stored per station with a survey "mixed declared frames" note (V3-B); per-period frame
mixing (PAX) is REFUSED at the gate (V3-C). The de-rotation math (Z' = R(-θ) Z R(-θ)^T) is retained
DIAGNOSTIC-ONLY and pinned here (test_diagnostic_derotation_*) + against the AusLAMP-SA custodian
twins (test_convention_gates_realdata.py) — see maintainer/C25-ConventionGates.md.
"""
import math
import re
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

VULCAN = HERE.parent / "data" / "sample-survey" / "transfer_functions" / "edi" / "Vulcan_A1.edi"
PHOENIX = HERE / "real_dialects" / "phoenix_empower_A01.edi"

Z_BLOCKS = ["ZXXR", "ZXXI", "ZXYR", "ZXYI", "ZYXR", "ZYXI", "ZYYR", "ZYYI"]
_NUM = re.compile(r"-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?")


# ---------------------------------------------------------------------------------------------
# text-transform helpers (fixture builders)
# ---------------------------------------------------------------------------------------------
def _find_block(lines, name):
    """(header_idx, [data line indices]) of the >NAME block (exact token, not a prefix)."""
    start = None
    data = []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if start is None:
            if s.upper().startswith(">" + name.upper()):
                rest = s[len(name) + 1:]
                if rest[:1] in ("", " ", "\t", "/"):
                    start = i
            continue
        if s.startswith(">"):
            break
        if s:
            data.append(i)
    if start is None:
        raise AssertionError(f"fixture base has no >{name} block")
    return start, data


def _read_block(text, name):
    lines = text.splitlines()
    _, data = _find_block(lines, name)
    vals = []
    for i in data:
        vals.extend(float(m) for m in _NUM.findall(lines[i]))
    return vals


def _write_block(text, name, values):
    lines = text.splitlines()
    start, data = _find_block(lines, name)
    rows = [" ".join(f"{v: .9E}" for v in values[i:i + 6]) for i in range(0, len(values), 6)]
    new = lines[:data[0]] + rows + lines[data[-1] + 1:] if data else \
        lines[:start + 1] + rows + lines[start + 1:]
    return "\n".join(new) + "\n"


def _rot(deg):
    b = math.radians(deg)
    return np.array([[math.cos(b), math.sin(b)], [-math.sin(b), math.cos(b)]])


def _z_from_text(text):
    series = {k: _read_block(text, k) for k in Z_BLOCKS}
    n = len(series["ZXXR"])
    Z = np.empty((n, 2, 2), dtype=complex)
    Z[:, 0, 0] = np.array(series["ZXXR"]) + 1j * np.array(series["ZXXI"])
    Z[:, 0, 1] = np.array(series["ZXYR"]) + 1j * np.array(series["ZXYI"])
    Z[:, 1, 0] = np.array(series["ZYXR"]) + 1j * np.array(series["ZYXI"])
    Z[:, 1, 1] = np.array(series["ZYYR"]) + 1j * np.array(series["ZYYI"])
    return Z


def _z_to_text(text, Z):
    for k, (i, j, part) in {
        "ZXXR": (0, 0, "real"), "ZXXI": (0, 0, "imag"), "ZXYR": (0, 1, "real"),
        "ZXYI": (0, 1, "imag"), "ZYXR": (1, 0, "real"), "ZYXI": (1, 0, "imag"),
        "ZYYR": (1, 1, "real"), "ZYYI": (1, 1, "imag"),
    }.items():
        text = _write_block(text, k, list(getattr(Z[:, i, j], part)))
    return text


def _vulcan_rotated(theta_per_period):
    """A self-consistent rotated Vulcan_A1: Z re-expressed in a frame at azimuth θ(i) AND the ZROT
    block declaring exactly that — the shape a legitimately-exported rotated EDI has."""
    text = VULCAN.read_text(encoding="latin-1")
    Z = _z_from_text(text)
    n = Z.shape[0]
    th = list(theta_per_period) if hasattr(theta_per_period, "__len__") \
        else [float(theta_per_period)] * n
    assert len(th) == n
    assert np.all(np.abs(Z) < 1e8) and np.all(np.isfinite(Z)), \
        "fixture base must be clean (no fills) or the rotation would smear them"
    Zr = np.array([_rot(th[i]) @ Z[i] @ _rot(th[i]).T for i in range(n)])
    text = _z_to_text(text, Zr)
    text = _write_block(text, "ZROT", th)
    return text


def _parse(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="latin-1")
    return bp._parse_one_edi(p)


def _pt_az_row(parsed):
    az = parsed["tf"][bp.tfmod.TF_COLUMNS.index("pt_az")]
    return [a for a in az if a is not None]


def _circ180(a, b):
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="latin-1")
    return p


# ---------------------------------------------------------------------------------------------
# Gate 1 — POLICY v3: serve AS STORED (V3-A), refuse per-period (V3-C). The engine never rotates.
# ---------------------------------------------------------------------------------------------
def test_uniform_zrot_served_as_stored_v3a(tmp_path):
    """V3-A. FAILS IF: a survey-uniform declared frame (here +30°) is DE-ROTATED, mislabelled, or
    served without the declared angle recorded. Owner ruling 2026-07-11: the engine serves data as
    stored and reports the frame — it does not de-rotate. The served products must therefore EQUAL
    the as-read (rotated) fixture, i.e. shifted ~+30° vs the unrotated original.
    Historical red: v2 de-rotated this to match the original (worst pt_az ~0 vs base)."""
    base = bp._parse_one_edi(VULCAN)
    rot_text = _vulcan_rotated(30.0)
    # PRECONDITION: as-read (no gate) the fixture really is rotated — _rotation_angle == 30
    tf_raw = mtm.read(_write(tmp_path, "raw_check.edi", rot_text))
    assert np.allclose(np.asarray(tf_raw._rotation_angle), 30.0)
    parsed = _parse(tmp_path, "rot30.edi", rot_text)
    assert "skip" not in parsed
    fr = parsed["frame"]
    assert fr["derotated"] is False, "V3-A must serve AS STORED — nothing de-rotated"
    assert fr["frame_served"] == "declared-azimuth"
    assert fr["declared_azimuth_deg"] == 30.0
    assert fr["impedance_rotation_deg_source"] is None   # nothing was rotated
    assert any("declared acquisition frame" in n and "NOT rotated" in n for n in parsed["frame_notes"])
    # served products EQUAL the as-read (rotated) fixture, NOT the unrotated original
    az_base, az_srv = _pt_az_row(base), _pt_az_row(parsed)
    n = min(len(az_base), len(az_srv))
    assert n > 10
    worst_vs_base = max(_circ180(a, b) for a, b in zip(az_base[:n], az_srv[:n]))
    assert worst_vs_base > 5.0, (
        "served pt_az matches the UNROTATED original — the station was silently de-rotated; "
        "V3-A requires as-stored serving")


def test_olympic_dam_class_neg60_served_as_stored_v3a(tmp_path):
    """V3-A pin (olympic-dam class: uniform ZROT −60, beyond any declination — the old R4 class).
    FAILS IF: the −60° station is served de-rotated. Compares the served pt_az against the SAME
    fixture built at angle 0 (the de-rotated target): they must DIFFER in the rotated way (~60°),
    proving the served values are the SOURCE (as-stored) values, not the de-rotated ones. Both go
    through the identical mt_metadata path so the comparison is index-aligned.
    Historical red: v2 de-rotated −60 (R4) so the served pt_az matched the angle-0 fixture (~0)."""
    az_zero = _pt_az_row(bp._parse_one_edi(VULCAN))        # angle-0 = the de-rotated target
    rot_text = _vulcan_rotated(-60.0)
    tf_raw = mtm.read(_write(tmp_path, "od_raw.edi", rot_text))
    assert np.allclose(np.asarray(tf_raw._rotation_angle), -60.0)   # PRECONDITION: really rotated
    parsed = _parse(tmp_path, "od.edi", rot_text)
    assert "skip" not in parsed
    fr = parsed["frame"]
    assert fr["derotated"] is False, "V3-A: −60° must serve AS STORED (no de-rotation)"
    assert fr["frame_served"] == "declared-azimuth"
    assert fr["declared_azimuth_deg"] == -60.0
    assert fr["impedance_rotation_deg_source"] is None
    az_srv = _pt_az_row(parsed)
    n = min(len(az_srv), len(az_zero))
    assert n > 10
    worst = max(_circ180(a, b) for a, b in zip(az_srv[:n], az_zero[:n]))
    assert worst > 5.0, (
        "served pt_az matches the angle-0 (de-rotated) fixture — the −60° station was de-rotated; "
        "V3-A requires byte-as-stored serving")


def test_per_period_zrot_refused_v3c(tmp_path):
    """V3-C. FAILS IF: a per-period (PAX-style) ZROT station is SERVED. A single served curve from
    period-varying frames is misleading-by-construction, so the station is REFUSED at the gate with
    a reason naming the per-period rotation and the fix.
    Historical red: v2 de-rotated per period (R1) and SERVED it (derotated True)."""
    n = len(_read_block(VULCAN.read_text(encoding="latin-1"), "ZROT"))
    theta = [5.0 + (35.0 * i / (n - 1)) for i in range(n)]
    parsed = _parse(tmp_path, "pax.edi", _vulcan_rotated(theta))
    assert "skip" in parsed, "per-period ZROT must be REFUSED (V3-C), not served"
    assert parsed["skip"]["gate"] == "rotation-frame"
    reason = parsed["skip"]["reason"]
    assert "per-period ZROT" in reason
    assert "re-export in a single coherent frame" in reason
    assert "misleading-by-construction" in reason


def test_threshold_death_14_vs_16_serve_identically_as_stored(tmp_path):
    """Threshold-death pin. FAILS IF: any serve-path behaviour differs at 14° vs 16° — the old
    v2 FRAME_KEEP_MAX_DEG=15 boundary (R3 record ≤15 vs R4 de-rotate >15) is GONE. Under v3 both
    are survey-uniform declarations served AS STORED, each recording its own angle; neither is
    de-rotated. Also proves FRAME_KEEP_MAX_DEG no longer exists as a constant."""
    assert not hasattr(conv, "FRAME_KEEP_MAX_DEG"), "the v2 15° threshold constant must be gone"
    for ang in (14.0, 16.0):
        parsed = _parse(tmp_path, f"a{ang}.edi", _vulcan_rotated(ang))
        assert "skip" not in parsed
        fr = parsed["frame"]
        assert fr["derotated"] is False, f"{ang}°: must serve AS STORED (no de-rotation)"
        assert fr["frame_served"] == "declared-azimuth"
        assert fr["declared_azimuth_deg"] == ang
        assert fr["impedance_rotation_deg_source"] is None


# ---------------------------------------------------------------------------------------------
# De-rotation MATH — DIAGNOSTIC-ONLY under v3 (no serve-path caller). Pinned so the transform stays
# documented + verified for future diagnostic use (per the C25-V3 ruling).
# ---------------------------------------------------------------------------------------------
def test_diagnostic_derotation_math_roundtrip():
    """FAILS IF: the retained de-rotation math (Z' = R(-θ) Z R(-θ)^T) stops reproducing the
    unrotated tensor. Builds a per-period FrameDisposition BY HAND (never via the serve path, which
    refuses per-period) and applies apply_derotation to a rotated TF; the de-rotated impedance must
    match the unrotated original to machine precision."""
    text = VULCAN.read_text(encoding="latin-1")
    Z0 = _z_from_text(text)
    n = Z0.shape[0]
    theta = [5.0 + (35.0 * i / (n - 1)) for i in range(n)]
    tf = mtm.read(VULCAN)
    Zr = np.array([_rot(theta[i]) @ Z0[i] @ _rot(theta[i]).T for i in range(n)])
    tf.impedance = Zr
    disp = conv.FrameDisposition(action="derotate", theta_z=[float(t) for t in theta])
    conv.apply_derotation(tf, disp)
    Zback = np.asarray(tf.impedance.data)
    keep = np.isfinite(Z0) & (np.abs(Z0) > 0) & (np.abs(Z0) < 1e8)
    rel = np.abs(Zback - Z0)[keep] / np.abs(Z0)[keep]
    assert rel.size and float(np.median(rel)) < 1e-9, \
        f"diagnostic de-rotation math no longer round-trips (median rel {float(np.median(rel)):.2e})"


def test_diagnostic_derotation_wrong_sign_is_caught():
    """Adversarial meta-pin (permanent red evidence) for the diagnostic math: FAILS IF a
    WRONG-SIGNED de-rotation could pass the round-trip above — i.e. proves that pin can fail. The
    correct de-rotation of an as-stored Zr = R(θ) Z0 R(θ)^T applies R(-θ); the WRONG sign applies
    R(+θ) (= R(-θ)ᵀ), yielding a 2θ over-rotation that must DIVERGE from the unrotated original."""
    text = VULCAN.read_text(encoding="latin-1")
    Z0 = _z_from_text(text)
    n = Z0.shape[0]
    theta = 30.0
    Zr = np.array([_rot(theta) @ Z0[i] @ _rot(theta).T for i in range(n)])   # as-stored
    R_wrong = _rot(-theta).T                        # sign-flipped: R(+θ), not the correct R(-θ)
    Zback_wrong = np.array([R_wrong @ Zr[i] @ R_wrong.T for i in range(n)])
    keep = np.isfinite(Z0) & (np.abs(Z0) > 0) & (np.abs(Z0) < 1e8)
    rel = np.abs(Zback_wrong - Z0)[keep] / np.abs(Z0)[keep]
    assert float(np.median(rel)) > 0.1, \
        "wrong-signed de-rotation went UNDETECTED — the diagnostic round-trip pin is vacuous"


def test_zrot_sentinel_at_data_periods_fails(tmp_path):
    """FAILS IF: a station whose ZROT carries the ~1e32 missing-data sentinel at periods that HAVE
    impedance data is served — the frame of those estimates is unknowable (fail-closed). (The
    sentinel at data-FREE periods is legitimate — kalk-2026 has 23 such files, all pass.)"""
    text = VULCAN.read_text(encoding="latin-1")
    zrot = _read_block(text, "ZROT")
    zrot[5] = 1.0e32                      # period 5 has real impedance data in the base station
    parsed = _parse(tmp_path, "sentinel.edi", _write_block(text, "ZROT", zrot))
    assert "skip" in parsed, "sentinel-at-data ZROT must FAIL ingest"
    assert parsed["skip"]["gate"] == "rotation-frame"
    assert "sentinel" in parsed["skip"]["reason"]


def test_tipper_derotation_mapping():
    """FAILS IF: the tipper de-rotation formula deviates from T' = T·R(-θ)^T — at θ=+90 that is
    exactly Tzx' = -Tzy, Tzy' = +Tzx (the second addendum's stated mapping), and the impedance
    mapping at θ=+90 is Z' = [[Zyy, -Zyx], [-Zxy, Zxx]]."""
    T = np.array([[[0.11 + 0.02j, -0.31 + 0.07j]]])
    Z = np.array([[[1.0 + 1j, 40.0 + 30.0j], [-42.0 - 28.0j, -2.0 + 0.5j]]])
    R = conv._rot_mat(-90.0)
    Tp = T[0] @ R.T
    assert np.allclose(Tp[0, 0], -T[0, 0, 1]) and np.allclose(Tp[0, 1], T[0, 0, 0])
    Zp = R @ Z[0] @ R.T
    assert np.allclose(Zp, np.array([[Z[0, 1, 1], -Z[0, 1, 0]], [-Z[0, 0, 1], Z[0, 0, 0]]]))


# ---------------------------------------------------------------------------------------------
# Gate 2 — sign-convention pins
# ---------------------------------------------------------------------------------------------
def test_conjugated_z_fails_with_convention_message(tmp_path):
    """FAILS IF: an e^{-iωt} (conjugated) station is served, or the failure message does not name
    the convention. Conjugation flips BOTH off-diagonals coherently out of quadrant (Zxy Q1->Q4,
    Zyx Q3->Q2) — the exact hazard that would invert the C20 induction-arrow claim."""
    text = VULCAN.read_text(encoding="latin-1")
    Z = _z_from_text(text)
    # PRECONDITION: the base really is e^{+iωt} (Q1/Q3)
    assert 0 < np.median(np.degrees(np.angle(Z[:, 0, 1]))) < 90
    assert -180 < np.median(np.degrees(np.angle(Z[:, 1, 0]))) < -90
    parsed = _parse(tmp_path, "conj.edi", _z_to_text(text, np.conj(Z)))
    assert "skip" in parsed, "a conjugated (wrong sign convention) station must FAIL ingest"
    assert parsed["skip"]["gate"] == "sign-convention"
    assert "conjugation signature" in parsed["skip"]["reason"]
    assert "e^{-i omega t}" in parsed["skip"]["reason"]


def test_axis_swapped_z_fails(tmp_path):
    """FAILS IF: an x/y axis-swapped station (Zxy<->Zyx, Zxx<->Zyy — the reflection Gate 1 cannot
    see and a ±90° rotation does NOT produce) is served. Signature: arg Zxy lands in Q3, arg Zyx
    in Q1 — the exact shape of the three real USArray negative controls."""
    text = VULCAN.read_text(encoding="latin-1")
    Z = _z_from_text(text)
    Zs = Z[:, ::-1, ::-1]                 # swap x/y axes: rows and columns
    parsed = _parse(tmp_path, "swap.edi", _z_to_text(text, Zs))
    assert "skip" in parsed and parsed["skip"]["gate"] == "sign-convention"
    assert "axis-swap signature" in parsed["skip"]["reason"]


def test_single_component_distortion_warns_not_fails(tmp_path):
    """FAILS IF: a station with ONE off-diagonal out of quadrant (a legitimate 3D/distortion
    shape — TAS105/MBN09/WG-14 class) is FAILED, or served with no honesty note."""
    text = VULCAN.read_text(encoding="latin-1")
    Z = _z_from_text(text)
    Z[:, 1, 0] = np.conj(Z[:, 1, 0])      # flip Zyx alone: Q3 -> Q2; Zxy stays Q1
    parsed = _parse(tmp_path, "distort.edi", _z_to_text(text, Z))
    assert "skip" not in parsed, "single-component out-of-quadrant must be WARN, never FAIL"
    ck = parsed["frame"]["convention_check"]
    assert ck["verdict"] == "warn_yx"
    assert any(n.startswith("convention:") and "outside its expected quadrant" in n
               for n in parsed["frame_notes"])


def test_insufficient_data_gets_note_never_verdict(tmp_path):
    """FAILS IF: masked/degenerate data manufactures a convention verdict. With fewer than
    CONVENTION_MIN_PERIODS usable periods the check must return 'insufficient' and the station
    must serve with the explicit honesty note (kalk-2026 degenerate class)."""
    text = VULCAN.read_text(encoding="latin-1")
    Z = _z_from_text(text)
    keep = conv.CONVENTION_MIN_PERIODS - 1
    Z[keep:, 0, 1] = 1e32                 # off-diagonals filled beyond the first keep periods
    Z[keep:, 1, 0] = 1e32
    parsed = _parse(tmp_path, "thin.edi", _z_to_text(text, Z))
    assert "skip" not in parsed
    ck = parsed["frame"]["convention_check"]
    assert ck["verdict"] == "insufficient"
    assert ck["n_periods_used"] == keep
    assert any("insufficient" in n or "no convention verdict" in n for n in parsed["frame_notes"])


def test_quadrant_constants_single_sourced():
    """FAILS IF: the gate thresholds stop being importable single-source constants (tests and any
    future validator mirror must read THESE, never re-declare)."""
    assert conv.QUADRANT_SLACK_DEG == 10.0
    assert conv.CONVENTION_MIN_PERIODS == 5
    assert conv.ROT_UNIFORM_EPS_DEG == 0.01
    assert conv.AZIMUTH_TOL_DEG == 0.5


# ---------------------------------------------------------------------------------------------
# clean corpus stays green
# ---------------------------------------------------------------------------------------------
def test_clean_sample_station_is_untouched():
    """FAILS IF: the gates alter or annotate a clean station (sample-survey Vulcan_A1: uniform
    ZROT=0, HX=0/HY=90, Q1/Q3 phases). The clean corpus is the false-positive budget: zero."""
    parsed = bp._parse_one_edi(VULCAN)
    assert "skip" not in parsed
    fr = parsed["frame"]
    assert fr["derotated"] is False
    assert fr["impedance_rotation_deg_source"] is None
    assert fr["convention_check"]["verdict"] == "ok"
    assert not [n for n in parsed["frame_notes"] if n.startswith("frame:")], \
        "a clean station must carry no frame notes"


def test_real_dialects_evidence_parse():
    """FAILS IF: the evidence text-parser misreads the real dialect specimens the repo carries
    (Phoenix EMpower spectra with per-line ROTSPEC; EDL/BIRRP and LEMI impedance-branch files) —
    the addendum requires dialect tolerance, pinned here on real bytes."""
    ph = conv.parse_frame_evidence(PHOENIX.read_text(encoding="latin-1"))
    assert ph["branch"] == "spectra"
    assert ph["rotspec"] is not None and set(ph["rotspec"]) == {0.0}
    assert ph["azm_hx"] == 0.0 and ph["azm_hy"] == 90.0
    for name in ("edl_birrp_st01.edi", "lemi_birrp_wg.edi"):
        ev = conv.parse_frame_evidence((HERE / "real_dialects" / name).read_text(encoding="latin-1"))
        assert ev["branch"] == "mt", name
    # spaced Tasmania-harness-style azimuth junk: parsed, but NOT usable frame evidence
    tas = (">HMEAS ID= 1001.001 CHTYPE=HX X = 0.  Y = 0.  AZM = 180.\n"
           ">HMEAS ID= 1002.001 CHTYPE=HY X = 0.  Y = 0.  AZM= 90.\n")
    ev = conv.parse_frame_evidence(tas)
    assert ev["azm_hx"] == 180.0 and ev["azm_hy"] == 90.0
    assert conv.azimuth_implied_rotation(ev) is None, \
        "non-orthogonal placeholder azimuths must not be treated as a frame declaration"


# ---------------------------------------------------------------------------------------------
# spectra branch (synthetic Black Hill shape — no real Black Hill bytes in the repo)
# ---------------------------------------------------------------------------------------------
_SPECTRA_COMPS = 7   # [hx, hy, hz, ex, ey, rhx, rhy] — mt_metadata's positional comp_list


def _rotate_spectra_text(text, theta):
    """Re-express every >SPECTRA cross-power matrix in a frame rotated by theta (rotating the
    (hx,hy), (ex,ey), (rhx,rhy) channel pairs), set ROTSPEC=theta, and point the HMEAS azimuths at
    the rotated axes — the synthetic Black Hill shape. Packing convention mirrors mt_metadata
    edi.py _read_spectra (upper triangle = imag of the conjugated lower): M[jj][ii]=Re(S[jj,ii]),
    M[ii][jj]=Im(S[jj,ii]) for ii<jj."""
    R = _rot(theta)
    U = np.eye(_SPECTRA_COMPS)
    for a, b in ((0, 1), (3, 4), (5, 6)):
        U[a, a], U[a, b] = R[0, 0], R[0, 1]
        U[b, a], U[b, b] = R[1, 0], R[1, 1]
    lines = text.splitlines()
    out = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.strip().upper().startswith(">SPECTRA"):
            header = re.sub(r"ROTSPEC=\S+", f"ROTSPEC={theta:g}", ln)
            vals = []
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith(">"):
                vals.extend(float(m) for m in _NUM.findall(lines[j]))
                j += 1
            M = np.array(vals).reshape(_SPECTRA_COMPS, _SPECTRA_COMPS)
            S = np.zeros_like(M, dtype=complex)
            for a in range(_SPECTRA_COMPS):
                S[a, a] = M[a, a]
                for b in range(a + 1, _SPECTRA_COMPS):
                    S[b, a] = complex(M[b, a], M[a, b])
                    S[a, b] = np.conj(S[b, a])
            Sp = U @ S @ U.T
            Mp = np.zeros_like(M)
            for a in range(_SPECTRA_COMPS):
                Mp[a, a] = Sp[a, a].real
                for b in range(a + 1, _SPECTRA_COMPS):
                    Mp[b, a] = Sp[b, a].real
                    Mp[a, b] = Sp[b, a].imag
            out.append(header)
            flat = Mp.flatten()
            out.extend(" ".join(f"{v: .9E}" for v in flat[k:k + 7]) for k in range(0, len(flat), 7))
            i = j
            continue
        out.append(ln)
        i += 1
    text = "\n".join(out) + "\n"
    text = re.sub(r"(CHTYPE=HX[^\n]*AZM=)0\b", rf"\g<1>{theta:g}", text)
    text = re.sub(r"(CHTYPE=HY[^\n]*AZM=)90\b", rf"\g<1>{90 + theta:g}", text)
    return text


def test_spectra_rotated_blackhill_shape_served_as_stored_v3a(tmp_path):
    """V3-A (spectra). FAILS IF: a uniform-rotated SPECTRA-format station (the Black Hill 2005
    GEOTOOLS shape: 7-channel, ROTSPEC=90, HMEAS azimuths at the rotated axes) is DE-ROTATED, fails
    ingest, or is served without the declared angle recorded. mt_metadata reads this class with NO
    rotation metadata (_rotation_angle None, azimuths ignored), so ONLY the raw-text evidence path
    sees the frame — and under v3 it RECORDS it and serves as stored. The served pt_az must equal
    the as-stored (rotated) shape, i.e. shifted ~90° vs the unrotated original.
    Historical red: v2 de-rotated ROTSPEC=90 (R4) so the served pt_az matched the original."""
    base = bp._parse_one_edi(PHOENIX)                      # unrotated original (~ the de-rot target)
    assert "skip" not in base
    rot_text = _rotate_spectra_text(PHOENIX.read_text(encoding="latin-1"), 90.0)
    # PRECONDITION: mt_metadata sees NO rotation metadata for this spectra shape
    p_raw = _write(tmp_path, "bh_raw.edi", rot_text)
    tf_raw = mtm.read(p_raw)
    assert getattr(tf_raw, "_rotation_angle", None) is None or \
        not np.any(np.asarray(tf_raw._rotation_angle))
    parsed = _parse(tmp_path, "blackhill.edi", rot_text)
    assert "skip" not in parsed, f"uniform-rotated spectra must serve as-stored, not fail: {parsed.get('skip')}"
    fr = parsed["frame"]
    assert fr["derotated"] is False, "V3-A (spectra): serve AS STORED — no de-rotation"
    assert fr["frame_served"] == "declared-azimuth"
    assert fr["declared_azimuth_deg"] == 90.0
    assert fr["impedance_rotation_deg_source"] is None
    az0, az1 = _pt_az_row(base), _pt_az_row(parsed)
    n = min(len(az0), len(az1))
    assert n > 10
    worst = max(_circ180(a, b) for a, b in zip(az0[:n], az1[:n]))
    assert worst > 5.0, (
        "served spectra pt_az matches the unrotated original — the station was de-rotated; "
        "V3-A requires as-stored serving")


def test_spectra_rotspec_vs_azimuth_conflict_fails(tmp_path):
    """FAILS IF: a spectra file whose ROTSPEC and HMEAS azimuths declare DIFFERENT frames is
    served on a guess. Per the ruling: |HMEAS-implied| == |ROTSPEC| is ONE rotation (Black Hill);
    anything else must FAIL loudly naming both values (the stored frame is unknowable)."""
    text = PHOENIX.read_text(encoding="latin-1")
    conflicted = re.sub(r"ROTSPEC=\S+", "ROTSPEC=90", text)   # azimuths stay HX=0/HY=90
    parsed = _parse(tmp_path, "conflict.edi", conflicted)
    assert "skip" in parsed and parsed["skip"]["gate"] == "rotation-frame"
    assert "ROTSPEC=90" in parsed["skip"]["reason"] and "imply 0" in parsed["skip"]["reason"]


# ---------------------------------------------------------------------------------------------
# process_edis integration: structured drops + frame notes reach the caller
# ---------------------------------------------------------------------------------------------
def test_process_edis_reports_gate_drops(tmp_path):
    """FAILS IF: a gate-failed station vanishes silently — the structured drop record (station +
    gate + reason) must reach the caller's report dict (build_report.json's stations_dropped) and
    the survivor must carry its frame facts."""
    text = VULCAN.read_text(encoding="latin-1")
    Z = _z_from_text(text)
    _write(tmp_path, "GOOD1.edi", text)
    _write(tmp_path, "BAD1.edi", _z_to_text(text, np.conj(Z)))
    report = {}
    stations, tf_rows, sci_rows = bp.process_edis(
        sorted(tmp_path.glob("*.edi")), "T", "org", "t-slug", report=report)
    assert len(stations) == 1
    drops = report.get("stations_dropped", [])
    assert len(drops) == 1 and "[sign-convention]" in drops[0]["reason"]
    (_p, r) = stations[0]
    assert r["frame"]["convention_check"]["verdict"] == "ok"
    assert r["frame"]["frame_served"] == "declared-zero"
    assert r["frame"]["declared_azimuth_deg"] == 0.0


# ---------------------------------------------------------------------------------------------
# POLICY v3 (owner-ruled 2026-07-11): V3-A serve-as-stored (any angle) + V3-B survey-inconsistency
# ---------------------------------------------------------------------------------------------
def test_small_uniform_angle_served_as_stored_v3a(tmp_path):
    """V3-A. FAILS IF: a survey-uniform declared frame (here 8° — the ccmt-2017 class) is ROTATED,
    mislabelled, or served without the declared angle recorded. Owner ruling: the archive respects
    acquisition frames — serve AS STORED, record honestly. The precondition assert proves the
    fixture really is rotated as-read, so a gate that rotates it would visibly diverge (pin can fail)."""
    base = bp._parse_one_edi(VULCAN)
    rot_text = _vulcan_rotated(8.0)
    # PRECONDITION: as-read the fixture pt_az really is shifted vs the original (~ -8 deg)
    p_raw = _write(tmp_path, "v3a_raw_check.edi", rot_text)
    tf_raw = mtm.read(p_raw)
    assert np.allclose(np.asarray(tf_raw._rotation_angle), 8.0)
    parsed = _parse(tmp_path, "v3a.edi", rot_text)
    assert "skip" not in parsed
    fr = parsed["frame"]
    assert fr["derotated"] is False, "V3-A must serve AS STORED — no rotation"
    assert fr["frame_served"] == "declared-azimuth"
    assert fr["declared_azimuth_deg"] == 8.0
    assert fr["impedance_rotation_deg_source"] is None   # nothing was rotated
    assert any("declared acquisition frame" in n and "NOT rotated" in n
               for n in parsed["frame_notes"])
    # served products EQUAL the as-read (rotated) fixture, i.e. shifted ~8 deg vs the original
    az_base, az_srv = _pt_az_row(base), _pt_az_row(parsed)
    n = min(len(az_base), len(az_srv))
    worst_vs_base = max(_circ180(a, b) for a, b in zip(az_base[:n], az_srv[:n]))
    assert worst_vs_base > 5.0, (
        "served pt_az matches the UNROTATED original — the station was silently de-rotated; "
        "V3-A requires as-stored serving")
    assert fr["convention_check"]["verdict"] == "ok"


def test_survey_inconsistent_angles_served_as_stored_with_note_v3b(tmp_path):
    """V3-B. FAILS IF: a survey whose per-station uniform angles disagree beyond
    SURVEY_ANGLE_SPREAD_MAX_DEG (the tumby-bay class) is de-rotated OR refused, or the survey does
    NOT gain the 'mixed declared frames' note. Owner ruling: each station is served in its OWN
    declared frame (nothing de-rotated); the survey merely reports that it mixes frames — the note
    reaches build_report's frame array AND every member's station.json frame block (for the portal).
    Historical red: v2 de-rotated the whole survey to zero (R2)."""
    t8, t20 = _vulcan_rotated(8.0), _vulcan_rotated(20.0)
    # PRECONDITION: standalone the 8-deg file already records its own frame (as-stored)
    solo = _parse(tmp_path, "solo8.edi", t8)
    assert solo["frame"]["derotated"] is False
    assert solo["frame"]["frame_served"] == "declared-azimuth"
    assert solo["frame"].get("survey_frame_note") is None   # no survey context standalone
    # survey context: 8 vs 20 -> spread 12 > 5 -> V3-B mixed; BOTH still served AS STORED
    sdir = tmp_path / "survey"
    sdir.mkdir()
    (sdir / "A.edi").write_text(t8, encoding="latin-1")
    (sdir / "B.edi").write_text(t20, encoding="latin-1")
    report = {}
    stations, tf_rows, sci_rows = bp.process_edis(
        sorted(sdir.glob("*.edi")), "T", "org", "t-slug", report=report)
    assert len(stations) == 2
    base_az = _pt_az_row(bp._parse_one_edi(VULCAN))
    seen_angles = set()
    for (_p, r), row in zip(stations, tf_rows):
        fr = r["frame"]
        assert fr["derotated"] is False, f"{_p.name}: V3-B must NOT de-rotate — serve as stored"
        assert fr["frame_served"] == "declared-azimuth"
        seen_angles.add(fr["declared_azimuth_deg"])
        # each station's survey.json frame carries the mixed-frames note (portal-reachable)
        assert "mixed declared frames across stations" in (fr.get("survey_frame_note") or ""), \
            f"{_p.name}: missing the V3-B survey_frame_note in station.json frame"
        # served products DIFFER from the unrotated original (as-stored, not de-rotated)
        az = [a for a in row[bp.tfmod.TF_COLUMNS.index("pt_az")] if a is not None]
        n = min(len(az), len(base_az))
        worst = max(_circ180(a, b) for a, b in zip(az[:n], base_az[:n]))
        assert worst > 5.0, f"{_p.name}: served pt_az matches the original — the station was de-rotated"
    assert seen_angles == {8.0, 20.0}, "each station must record its OWN declared angle"
    # the survey-level note reaches build_report's frame_notes (aggregated into the `frame` array)
    fnotes = report.get("frame_notes", {})
    all_notes = [n for lst in fnotes.values() for n in lst]
    assert any("mixed declared frames across stations" in n for n in all_notes), \
        "the V3-B mixed-frames note must reach the caller's report (build_report frame array)"


# ---------------------------------------------------------------------------------------------
# Fix round F1: declared-zero stations participate in the V3-B vote as angle 0.0
# ---------------------------------------------------------------------------------------------
def test_classify_survey_frame_declared_zero_participates_f1():
    """F1 (panel table). FAILS IF: declared-zero (kind 'none') stations are excluded from the V3-B
    spread vote or the note's min/max range. A served station always sits in SOME declared frame —
    zero serves under the declared-zero reference — so [0°, 20°] mixes frames exactly as [8°, 20°]
    does, and the stamped range must include the 0° members.
    Historical red: pre-F1 code voted over kind=='uniform' only — [0°, 20°] got NO note and
    [0°, 8°, 20°] understated the range as '8°…20°'."""
    z = ("none", 0.0)
    u = lambda a: ("uniform", float(a))  # noqa: E731
    n1 = conv.classify_survey_frame([z, u(20)])
    assert n1 and "0°…20°" in n1, f"[0, 20] must fire with the full range: {n1!r}"
    n2 = conv.classify_survey_frame([z, z, u(20)])
    assert n2 and "0°…20°" in n2, f"[0, 0, 20] must fire with the full range: {n2!r}"
    n3 = conv.classify_survey_frame([z, u(8), u(20)])
    assert n3 and "0°…20°" in n3, \
        f"[0, 8, 20] must state the FULL range including the 0° members: {n3!r}"
    n4 = conv.classify_survey_frame([u(8), u(20)])
    assert n4 and "8°…20°" in n4, f"[8, 20] unchanged: {n4!r}"
    assert conv.classify_survey_frame([z, z, z]) is None, "[0, 0, 0]: spread 0 — no note"
    assert conv.classify_survey_frame([z, u(4)]) is None, "spread 4 <= 5 — no note"
    # per-period (V3-C) stations are refused, never served — they cannot mix a SERVED frame
    assert conv.classify_survey_frame([("per-period", None), z]) is None
    assert conv.classify_survey_frame([]) is None


def test_survey_zero_member_gets_mixed_frames_note_f1(tmp_path):
    """F1 integration. FAILS IF: a survey mixing a declared-zero station with a 20° one gets NO
    mixed-frames note (the pre-F1 defect: zero members were invisible to the vote), or the note's
    range omits the 0° member it is stamped on. Both stations still serve AS STORED.
    Historical red: pre-F1 code emitted no note for [0°, 20°]."""
    sdir = tmp_path / "survey"
    sdir.mkdir()
    (sdir / "A.edi").write_text(VULCAN.read_text(encoding="latin-1"), encoding="latin-1")  # ZROT=0
    (sdir / "B.edi").write_text(_vulcan_rotated(20.0), encoding="latin-1")
    report = {}
    stations, tf_rows, sci_rows = bp.process_edis(
        sorted(sdir.glob("*.edi")), "T", "org", "t-slug", report=report)
    assert len(stations) == 2
    for (_p, r) in stations:
        fr = r["frame"]
        assert fr["derotated"] is False, f"{_p.name}: still served as stored"
        note = fr.get("survey_frame_note") or ""
        assert "mixed declared frames across stations" in note, \
            f"{_p.name}: the zero-member survey must carry the V3-B note (pre-F1 red)"
        assert "0°…20°" in note, \
            f"{_p.name}: the note's range must include the 0° member: {note!r}"
    served = {r["frame"]["declared_azimuth_deg"] for (_p, r) in stations}
    assert served == {0.0, 20.0}, "each station still records its OWN declared angle"


# ---------------------------------------------------------------------------------------------
# Fix round F2: divergent tipper/impedance declared frames are REPORTED (never rotated)
# ---------------------------------------------------------------------------------------------
_N_VULCAN = 62   # Vulcan_A1's period count (>FREQ //62)


def _vulcan_with_tipper(zrot_deg, trot_deg):
    """Vulcan_A1 + a synthetic varying tipper (TXR/TXI/TYR/TYI .EXP blocks) + a uniform declared
    TROT — the runtime text-transform pattern (no real tipper EDI is in the repo; the Phoenix
    spectra tipper is a masked placeholder). zrot_deg nonzero re-expresses Z + declares ZROT via
    _vulcan_rotated; the tipper VALUES are irrelevant to the frame gate (declarations only) but
    vary so nothing resembles the flat-|T| placeholder class."""
    n = _N_VULCAN
    text = _vulcan_rotated(zrot_deg) if abs(zrot_deg) > 1e-9 \
        else VULCAN.read_text(encoding="latin-1")

    def _rows(vals):
        return "\n".join(" ".join(f"{v: .9E}" for v in vals[i:i + 6])
                         for i in range(0, len(vals), 6))

    txr = [0.10 + 0.20 * i / (n - 1) for i in range(n)]
    txi = [-0.05 + 0.10 * i / (n - 1) for i in range(n)]
    tyr = [0.30 - 0.15 * i / (n - 1) for i in range(n)]
    tyi = [0.02 + 0.05 * i / (n - 1) for i in range(n)]
    block = (f">TROT  //{n}\n{_rows([float(trot_deg)] * n)}\n"
             f">TXR.EXP //{n}\n{_rows(txr)}\n>TXI.EXP //{n}\n{_rows(txi)}\n"
             f">TYR.EXP //{n}\n{_rows(tyr)}\n>TYI.EXP //{n}\n{_rows(tyi)}\n")
    assert ">END" in text
    return text.replace(">END", block + ">END")


def test_divergent_tipper_frame_reported_f2(tmp_path):
    """F2 (panel case d: TROT=-60, ZROT=0). FAILS IF: a station whose uniform declared tipper frame
    DIVERGES from its impedance declared azimuth is refused, rotated, or served with the divergence
    UNREPORTED. Owner doctrine: "if we know any details about the coordinate frame we report it" —
    the divergent tipper frame must land first-class in station.json
    (frame.tipper_declared_azimuth_deg) AND as a frame note (build_report/QA + the portal line).
    Historical red: pre-F2 the -60° tipper frame lived only in frame.evidence.trot."""
    fx = _vulcan_with_tipper(0.0, -60.0)
    # PRECONDITION: the fixture really has a tipper and really declares TROT=-60 uniform
    p_raw = _write(tmp_path, "cased_raw.edi", fx)
    assert mtm.read(p_raw).has_tipper(), "fixture must carry a real tipper"
    ev = conv.parse_frame_evidence(fx)
    assert conv._uniq_eps(conv._mask_sentinels(ev["trot"])) == [-60.0]
    parsed = _parse(tmp_path, "cased.edi", fx)
    assert "skip" not in parsed, f"case d must SERVE (divergence is reported, not refused): {parsed.get('skip')}"
    fr = parsed["frame"]
    assert fr["derotated"] is False and fr["frame_served"] == "declared-zero"
    assert fr["tipper_declared_azimuth_deg"] == -60.0, \
        "the divergent tipper frame must be a first-class station.json field"
    assert any("tipper" in n and "divergent" in n and "NOT rotated" in n
               for n in parsed["frame_notes"]), \
        f"the divergence must be a frame note: {parsed['frame_notes']}"
    # the reverse shape (AusLAMP-SA class: rotated Z, zero tipper) reports too
    parsed2 = _parse(tmp_path, "rev.edi", _vulcan_with_tipper(-60.0, 0.0))
    assert "skip" not in parsed2
    fr2 = parsed2["frame"]
    assert fr2["declared_azimuth_deg"] == -60.0
    assert fr2["tipper_declared_azimuth_deg"] == 0.0, \
        "a zero tipper frame under a rotated impedance is equally divergent — report it"


def test_equal_tipper_frame_not_reported_f2(tmp_path):
    """F2 negative space. FAILS IF: an EQUAL tipper/impedance declaration (ZROT=TROT=-60) or a
    zero/zero one produces the divergence field or note — equal-or-absent TROT means no change, no
    noise (mutation-proof for the F2 pin: the field appears ONLY on divergence)."""
    for name, zr, tr in (("eq60.edi", -60.0, -60.0), ("eq0.edi", 0.0, 0.0)):
        parsed = _parse(tmp_path, name, _vulcan_with_tipper(zr, tr))
        assert "skip" not in parsed, name
        fr = parsed["frame"]
        assert "tipper_declared_azimuth_deg" not in fr, \
            f"{name}: equal declarations must NOT emit the divergence field"
        assert not any("divergent" in n for n in parsed["frame_notes"]), \
            f"{name}: equal declarations must NOT emit the divergence note"
