"""C25 convention gates (T1.1 rotation/frame guard + T1.2 sign-convention quadrant check).

Every fixture here is generated AT RUNTIME by text-transforming the in-repo clean stations
(data/sample-survey Vulcan_A1 for the impedance branch; tests/real_dialects phoenix_empower_A01
for the spectra branch) — no rotated real-survey file is copied into the repo (rights). Each
transform test asserts its own PRECONDITION (the fixture really is rotated/conjugated as-read),
so a test cannot pass vacuously against an unrotated fixture; and one adversarial meta-pin proves
the round-trip assertion CAN fail (a wrong-signed de-rotation is caught), permanently — not just
in a one-off red run (Invariant 10).

De-rotation ground truth: beyond these synthetic pins, the formula Z' = R(-θ) Z R(-θ)^T was
verified against the AusLAMP-SA custodian twins (the served PAX-rotated files de-rotate onto the
custodian's own geographic exports to machine precision) — see maintainer/C25-ConventionGates.md.
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


# ---------------------------------------------------------------------------------------------
# Gate 1 — de-rotation round-trip pins
# ---------------------------------------------------------------------------------------------
def test_uniform_zrot_derotation_roundtrip(tmp_path):
    """FAILS IF: the de-rotation is wrong-signed, misapplied, or skipped. A file whose Z is
    re-expressed at azimuth +30 with ZROT=30 declared must ingest to the SAME derived products as
    the unrotated original (the gate's whole job: the frame we serve is geographic north)."""
    base = bp._parse_one_edi(VULCAN)
    rot_text = _vulcan_rotated(30.0)
    # PRECONDITION: as-read (no gate) the fixture really is rotated — pt_az shifted by +30
    tf_raw = mtm.read(_write(tmp_path, "raw_check.edi", rot_text))
    assert np.allclose(np.asarray(tf_raw._rotation_angle), 30.0)
    parsed = _parse(tmp_path, "rot30.edi", rot_text)
    assert "skip" not in parsed
    assert parsed["frame"]["derotated"] is True
    assert parsed["frame"]["impedance_rotation_deg_source"] == 30.0
    assert any("de-rotated 30 deg" in n for n in parsed["frame_notes"])
    az0, az1 = _pt_az_row(base), _pt_az_row(parsed)
    assert len(az0) == len(az1) and len(az0) > 10
    worst = max(_circ180(a, b) for a, b in zip(az0, az1))
    assert worst <= 0.2, f"pt_az mismatch after de-rotation (worst {worst} deg) — wrong sign gives ~60"
    for col in ("phs_xy", "phs_yx_adj", "rho_xy", "rho_yx"):
        i = bp.tfmod.TF_COLUMNS.index(col)
        a0, a1 = parsed["tf"][i], base["tf"][i]
        pairs = [(x, y) for x, y in zip(a0, a1) if x is not None and y is not None]
        assert pairs and all(math.isclose(x, y, rel_tol=5e-3, abs_tol=0.2) for x, y in pairs), col


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="latin-1")
    return p


def test_per_period_zrot_derotation_roundtrip(tmp_path):
    """FAILS IF: per-period (PAX-style) de-rotation does not reproduce the unrotated original.
    This pins the disposition that keeps the served AusLAMP-SA flagship (396 stations, per-period
    ZROT, ROTATION=PAX) SERVABLE by exact per-period de-rotation — the reading confirmed against
    the custodian twins. If the architect overrules per-period de-rotation in favour of FAIL,
    THIS is the test to flip."""
    base = bp._parse_one_edi(VULCAN)
    n = len(_read_block(VULCAN.read_text(encoding="latin-1"), "ZROT"))
    theta = [5.0 + (35.0 * i / (n - 1)) for i in range(n)]
    parsed = _parse(tmp_path, "pax.edi", _vulcan_rotated(theta))
    assert "skip" not in parsed
    assert parsed["frame"]["derotated"] is True
    assert isinstance(parsed["frame"]["impedance_rotation_deg_source"], list)
    assert any("per period" in note for note in parsed["frame_notes"])
    az0, az1 = _pt_az_row(base), _pt_az_row(parsed)
    worst = max(_circ180(a, b) for a, b in zip(az0, az1))
    assert worst <= 0.2, f"per-period de-rotation failed to restore pt_az (worst {worst} deg)"


def test_wrong_signed_derotation_is_caught_by_the_roundtrip(tmp_path, monkeypatch):
    """Adversarial meta-pin (permanent red evidence): FAILS IF the round-trip comparison above
    could pass with a WRONG-SIGNED rotation matrix — i.e. proves the round-trip pin can fail.
    Monkeypatches _rot_mat to the transpose (sign-flipped angle) and asserts the de-rotated
    products now DISAGREE with the original."""
    base = bp._parse_one_edi(VULCAN)

    def _wrong(deg):  # the transposed (sign-flipped) rotation matrix

        b = math.radians(deg)
        return np.array([[math.cos(b), -math.sin(b)], [math.sin(b), math.cos(b)]])
    monkeypatch.setattr(conv, "_rot_mat", _wrong, raising=True)
    parsed = _parse(tmp_path, "rot30_wrong.edi", _vulcan_rotated(30.0))
    assert "skip" not in parsed
    az0, az1 = _pt_az_row(base), _pt_az_row(parsed)
    worst = max(_circ180(a, b) for a, b in zip(az0, az1))
    assert worst > 30.0, (
        f"wrong-signed de-rotation went UNDETECTED (worst pt_az diff {worst} deg) — "
        f"the round-trip pin is vacuous")


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


def test_spectra_rotated_blackhill_shape_is_derotated(tmp_path):
    """FAILS IF: a rotated SPECTRA-format station (the Black Hill 2005 GEOTOOLS shape: 7-channel,
    HX AZM=90/HY AZM=180, ROTSPEC=90, data on grid axes) is served un-derotated OR fails ingest.
    mt_metadata reads this class with NO rotation metadata at all (_rotation_angle None, azimuths
    ignored — edi.py _read_spectra maps channels by position), so ONLY the raw-text evidence path
    can catch it; after de-rotation the derived products must match the unrotated original."""
    base = bp._parse_one_edi(PHOENIX)
    assert "skip" not in base
    rot_text = _rotate_spectra_text(PHOENIX.read_text(encoding="latin-1"), 90.0)
    # PRECONDITION: as-read the fixture is genuinely rotated — mt_metadata sees no rotation
    # metadata, and the derived pt_az is shifted ~90 vs the original
    p_raw = _write(tmp_path, "bh_raw.edi", rot_text)
    tf_raw = mtm.read(p_raw)
    assert getattr(tf_raw, "_rotation_angle", None) is None or \
        not np.any(np.asarray(tf_raw._rotation_angle))
    parsed = _parse(tmp_path, "blackhill.edi", rot_text)
    assert "skip" not in parsed, f"rotated spectra must be de-rotated, not failed: {parsed.get('skip')}"
    assert parsed["frame"]["derotated"] is True
    assert parsed["frame"]["impedance_rotation_deg_source"] == 90.0
    az0, az1 = _pt_az_row(base), _pt_az_row(parsed)
    n = min(len(az0), len(az1))
    assert n > 10
    worst = max(_circ180(a, b) for a, b in zip(az0[:n], az1[:n]))
    assert worst <= 0.5, f"spectra de-rotation did not restore the original frame (worst {worst})"


def test_spectra_rotspec_vs_azimuth_conflict_fails(tmp_path):
    """FAILS IF: a spectra file whose ROTSPEC and HMEAS azimuths declare DIFFERENT frames is
    served on a guess. Per the ruling: |HMEAS-implied| == |ROTSPEC| is ONE rotation (Black Hill);
    anything else must FAIL loudly naming both values."""
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
    assert r["frame"]["frame_served"].startswith("geographic-north")
