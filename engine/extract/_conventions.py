#!/usr/bin/env python3
"""C25 convention gates — per-station frame guard (Gate 1) and sign-convention check (Gate 2).

The engine serves transfer functions under a declared standard: x = geographic north, y = east,
e^{+iωt} time dependence (docs data-files.md). Nothing used to VERIFY that per file: T1.1/T1.2
(tracked C25, hard deadline = the T2.1 contract freeze). These gates run at the mt_metadata parse
seam (build_portal._parse_one_edi) on every EDI, every build.

GATE 1 — rotation/frame guard. mt_metadata 1.0.9 RECORDS rotation but never compensates it:
  * io/edi/edi.py:455-461 reads the >ZROT block (falls back to >RHOROT, else zero-fills) into
    edi_obj.rotation_angle;
  * core.py:2118/2131 + 2134-2135 copy rotation_angle -> TF._rotation_angle while the impedance is
    copied VERBATIM — no de-rotation anywhere on the read path (verified empirically: injecting
    ZROT=30 leaves Z byte-identical while _rotation_angle becomes 30);
  * the SPECTRA branch (_read_data -> _read_spectra, edi.py:341-354, 463-690) maps channels purely
    BY POSITION (tools.py index_locator), ignores HMEAS/EMEAS azimuths, never parses ROTSPEC, and
    leaves _rotation_angle None — so a rotated spectra-format file is INVISIBLE to the TF object's
    rotation metadata. The raw-text evidence parse below is therefore load-bearing, not advisory.
So the gate reads BOTH sources — the TF's _rotation_angle AND a cheap lexical parse of the source
EDI (ZROT/TROT blocks, SPECTRA ROTSPEC attributes, HMEAS azimuths) — cross-checks them, and:
  * frame declared and fully specified (uniform OR per-period ZROT/ROTSPEC) -> DE-ROTATE the
    impedance (and, under its own TROT declaration, the tipper) to geographic north:
        Z_geo(i) = R(-θi) Z(i) R(-θi)^T,   T_geo(i) = T(i) R(-θi)^T,
        R(β) = [[cosβ, sinβ], [-sinβ, cosβ]]
    with a conditioning-style honesty note + frame facts on the served station record. The formula
    and sign are pinned two independent ways: the synthetic round-trip fixtures (tests), and the
    AusLAMP-SA custodian twin proof — de-rotating the served PAX-rotated files by their per-period
    ZROT reproduces the custodian's own geographic-frame exports to machine precision (median
    residual 0.0 vs 0.15-0.39 for identity, 4 stations × 23 periods; see C25-ConventionGates.md).
  * rotation UNKNOWABLE (sentinel/missing angles at data-bearing periods, reader/text disagreement,
    ROTSPEC-vs-azimuth conflict, non-descending frequency order under a per-period rotation,
    RHOROT declared rotated while the Z frame is undeclared) -> FAIL: the station is skipped
    loudly (fail-closed, C8 posture) — never served in an unresolvable frame.
  * no declaration at all, or azimuth metadata too inconsistent to be evidence (e.g. the harness
    Tasmania files' HX AZM=180/HY AZM=90 non-orthogonal placeholders) -> serve with the frame
    facts recorded; Gate 2 still checks the convention. Azimuths on the impedance branch are
    ACQUISITION metadata, not the stored-tensor frame — the >ZROT declaration wins when present
    (USArray: physical sensor azimuths ±19° with ZROT=0 = processed-to-geographic, served as-is).

GATE 2 — sign-convention quadrant check. Under e^{+iωt} with x=north/y=east, arg(Zxy) lies in Q1
(0..90°) and arg(Zyx) in Q3 (-180..-90°). Per station the gate takes the MEDIAN phase of each
off-diagonal over the mid-band periods (central 60%, after masking absent/degenerate values) and:
  * BOTH medians coherently in wrong quadrants -> FAIL (a pure convention/frame flip: conjugation
    = e^{-iωt}, or an x/y axis swap — the message names the signature). This is what makes the C20
    induction-arrow panel's "arrows point toward conductors" claim safe.
  * ONE median out of quadrant -> WARN as an honesty note, never a failure (3D effects/galvanic
    distortion legitimately do this — e.g. TAS105/TAS106, MBN09, WG-14 on the real corpus).
  * fewer than CONVENTION_MIN_PERIODS usable mid-band periods -> an explicit "insufficient data"
    note — degenerate/masked data must never manufacture a convention verdict.
LIMIT (state it, don't discover it): Gate 2 is BLIND to ±90° frame rotations by construction — a
±90° rotation maps Zxy'=-Zyx / Zyx'=-Zxy, which preserves the Q1/Q3 structure (verified survey-wide,
n=7835 periods). Gate 2 checks the SIGN CONVENTION only; frames are Gate 1's job.

All thresholds are single-sourced here; tests and build_portal import them — never re-declare.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------------------------
# Single-sourced constants (import these; do not re-declare).
# ---------------------------------------------------------------------------------------------
# Gate 1 — rotation handling.
ROT_UNIFORM_EPS_DEG = 0.01   # angles within this of each other count as ONE uniform rotation
ROT_ZERO_EPS_DEG = 0.01      # |angle| below this is zero (no rotation)
AZIMUTH_TOL_DEG = 0.5        # HMEAS azimuth agreement tolerance (HY == HX+90, ROTSPEC == HX)
ROT_FILL_MAX = 1e8           # missing-data sentinel threshold — same convention as _mtm._FILL_MAX

# Gate 2 — quadrant check.
QUADRANT_SLACK_DEG = 10.0    # tolerance slack at the quadrant edges (single-sourced)
CONVENTION_MIN_PERIODS = 5   # N_min usable mid-band periods for a verdict; below -> insufficient
CONVENTION_MIN_ABS_Z = 1e-6  # off-diagonal |Z| magnitude floor (practical-unit impedances are far
                             # above; masked/degenerate artifacts far below — kalk-2026 class)
MIDBAND_LO_FRAC = 0.2        # the mid-band = central 60% of the USABLE periods
MIDBAND_HI_FRAC = 0.8

_NUM_RE = re.compile(r"-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?")


# ---------------------------------------------------------------------------------------------
# Raw-text frame evidence (the load-bearing half for spectra files; the cross-check for MT files).
# ---------------------------------------------------------------------------------------------
def _block_values(text: str, name: str) -> Optional[list]:
    """Numeric values of the >NAME data block (exact token: '>ZROT' matches '>ZROT //62' but not
    '>ZROT.EXP' and never a '>ZXXR ROT=ZROT' data-block header). None when the block is absent."""
    vals: list = []
    found = False
    inb = False
    for ln in text.splitlines():
        s = ln.strip()
        if inb and s.startswith(">"):
            inb = False
        if not inb and s.upper().startswith(">" + name.upper()):
            rest = s[len(name) + 1:]
            if rest[:1] in ("", " ", "\t", "/"):
                inb = True
                found = True
                continue
        if inb and s and not s.startswith(">"):
            for m in _NUM_RE.findall(s):
                try:
                    vals.append(float(m))
                except ValueError:
                    pass
    return vals if found else None


def _first_azm(text: str, meas: str, chtype: str) -> Optional[float]:
    """AZM= of the FIRST >HMEAS/>EMEAS line for a channel type (the measurement channel; remote
    HX/HY lines come later in every corpus dialect). None when absent (many dialects omit AZM)."""
    m = re.search(rf">{meas}\b[^\n]*CHTYPE\s*=\s*{chtype}\b[^\n]*?AZM\s*=\s*(-?[\d.]+)",
                  text, re.IGNORECASE)
    return float(m.group(1)) if m else None


def parse_frame_evidence(text: str) -> dict:
    """Cheap lexical parse of an EDI's frame evidence. Tolerant of the corpus dialects (GEOTOOLS,
    EDL/BIRRP, LEMI, Phoenix EMpower spectra, EMTF/USArray): spaced 'AZM = 180.', TROT vs TROT.EXP,
    per-line SPECTRA ROTSPEC attributes."""
    up = text.upper()
    spectra = (">=SPECTRASECT" in up) or re.search(r"^>SPECTRA\b", text, re.M | re.I) is not None
    rotspec = [float(x) for x in re.findall(r"ROTSPEC\s*=\s*(-?[\d.]+)", text, re.I)] or None
    tip_attr = re.search(r"^>TX[RI](?:\.EXP)?\b[^\n]*ROT\s*=\s*(\w+)", text, re.M | re.I)
    freqs = _block_values(text, "FREQ")
    return {
        "branch": "spectra" if spectra else "mt",
        "zrot": _block_values(text, "ZROT"),
        "rhorot": _block_values(text, "RHOROT"),
        "trot": (_block_values(text, "TROT") if _block_values(text, "TROT") is not None
                 else _block_values(text, "TROT.EXP")),
        "rotspec": rotspec,
        "azm_hx": _first_azm(text, "HMEAS", "HX"),
        "azm_hy": _first_azm(text, "HMEAS", "HY"),
        "azm_ex": _first_azm(text, "EMEAS", "EX"),
        "azm_ey": _first_azm(text, "EMEAS", "EY"),
        "tipper_rot_attr": tip_attr.group(1).upper() if tip_attr else None,
        "freq_descending": (freqs is None or len(freqs) < 2
                            or all(a >= b for a, b in zip(freqs, freqs[1:]))),
    }


def _mask_sentinels(vals):
    """Replace missing-data sentinels (|v| > ROT_FILL_MAX, the community ~1e32 convention) with
    None, preserving positions. None in -> None out."""
    if vals is None:
        return None
    return [None if (not math.isfinite(v) or abs(v) > ROT_FILL_MAX) else float(v) for v in vals]


def _uniq_eps(vals, eps=ROT_UNIFORM_EPS_DEG):
    """Distinct finite values (None-skipped) collapsed within eps. Sorted."""
    out: list = []
    for v in vals or []:
        if v is None:
            continue
        if not any(abs(v - u) <= eps for u in out):
            out.append(v)
    return sorted(out)


def azimuth_implied_rotation(ev: dict) -> Optional[float]:
    """The frame rotation the HMEAS azimuths imply, or None when they are not usable evidence.

    Usable = a coherent orthogonal right-handed pair: HY == HX + 90 (mod 360) within
    AZIMUTH_TOL_DEG. Then the implied rotation is HX (0 for the standard frame). Anything else —
    azimuths absent, or a non-orthogonal placeholder pair like the harness Tasmania HX=180/HY=90 —
    is NOT usable as frame evidence (returns None; the caller records the raw values as facts)."""
    hx, hy = ev.get("azm_hx"), ev.get("azm_hy")
    if hx is None or hy is None:
        return None
    if abs((hy - hx - 90.0) % 360.0) <= AZIMUTH_TOL_DEG or \
       abs(((hy - hx - 90.0) % 360.0) - 360.0) <= AZIMUTH_TOL_DEG:
        return float(hx % 360.0)
    return None


def _norm_angle(a: float) -> float:
    """Normalise an angle to (-180, 180] for reporting and comparisons."""
    a = a % 360.0
    return a - 360.0 if a > 180.0 else a


# ---------------------------------------------------------------------------------------------
# Gate 1 disposition.
# ---------------------------------------------------------------------------------------------
@dataclass
class FrameDisposition:
    """What Gate 1 decided for one station. theta_z/theta_t are per-period de-rotation SOURCE
    angles (the frame the data is stored in; de-rotation applies R(-θ)) aligned to the TF period
    axis, or None for no rotation. facts is the JSON-safe frame record for station.json; notes are
    conditioning-style honesty strings."""
    action: str                      # "pass" | "derotate" | "fail"
    theta_z: Optional[list] = None   # per-period degrees, or None
    theta_t: Optional[list] = None
    facts: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)
    fail_reason: Optional[str] = None


def _angles_summary(u: list) -> str:
    if not u:
        return "0"
    if len(u) == 1:
        return f"{_norm_angle(u[0]):g}"
    return f"per-period {min(u):g}..{max(u):g} ({len(u)} distinct)"


def frame_disposition(ev: dict, rot_mtm, z_present: list, has_tipper: bool,
                      n_periods: int) -> FrameDisposition:
    """Decide pass/derotate/fail from the combined evidence. See the module docstring for the
    ruling table; every FAIL reason names the angles and the fix (fail-closed, C8 posture)."""
    facts: dict = {
        "evidence": {
            "branch": ev["branch"],
            "zrot": _angles_summary(_uniq_eps(_mask_sentinels(ev["zrot"]))) if ev["zrot"] else None,
            "trot": _angles_summary(_uniq_eps(_mask_sentinels(ev["trot"]))) if ev["trot"] else None,
            "rotspec": _angles_summary(_uniq_eps(_mask_sentinels(ev["rotspec"]))) if ev["rotspec"] else None,
            "hmeas_azimuths": {"hx": ev["azm_hx"], "hy": ev["azm_hy"]},
            "emeas_azimuths": {"ex": ev["azm_ex"], "ey": ev["azm_ey"]},
        },
    }
    notes: list = []

    def _fail(reason: str) -> FrameDisposition:
        return FrameDisposition(action="fail", facts=facts, fail_reason=reason)

    def _done(theta_z, theta_t) -> FrameDisposition:
        rotated = (theta_z is not None) or (theta_t is not None)
        facts["impedance_rotation_deg_source"] = (
            None if theta_z is None else
            (round(_norm_angle(theta_z[0]), 4) if len(_uniq_eps(theta_z)) == 1
             else [round(_norm_angle(t), 4) for t in theta_z]))
        facts["tipper_rotation_deg_source"] = (
            None if theta_t is None else
            (round(_norm_angle(theta_t[0]), 4) if len(_uniq_eps(theta_t)) == 1
             else [round(_norm_angle(t), 4) for t in theta_t]))
        facts["derotated"] = bool(rotated)
        facts["frame_served"] = ("geographic-north (x=north; derotated at ingest)" if rotated
                                 else "geographic-north (x=north; as declared/assumed by source)")
        return FrameDisposition(action="derotate" if rotated else "pass",
                                theta_z=theta_z, theta_t=theta_t, facts=facts, notes=notes)

    # ---- SPECTRA branch: text evidence is the ONLY evidence (mt_metadata ignores ROTSPEC and
    # azimuths on this path and leaves _rotation_angle None — see module docstring). ----
    if ev["branch"] == "spectra":
        rs = _uniq_eps(_mask_sentinels(ev["rotspec"]))
        az = azimuth_implied_rotation(ev)
        if len(rs) > 1:
            return _fail(f"SPECTRA ROTSPEC varies across blocks ({rs[:4]}...) — no single frame is "
                         f"declared and the v1 gate does not per-block-derotate spectra; fix: "
                         f"re-export the file in one frame (geographic north preferred).")
        rs_th = rs[0] if rs else None
        if rs_th is not None and abs(_norm_angle(rs_th)) <= ROT_ZERO_EPS_DEG:
            rs_th = 0.0
        if az is not None and abs(_norm_angle(az)) <= ROT_ZERO_EPS_DEG:
            az = 0.0
        theta = None
        if rs_th is not None and az is not None:
            if abs(abs(_norm_angle(rs_th)) - abs(_norm_angle(az))) <= AZIMUTH_TOL_DEG:
                # Black Hill ruling: |HMEAS-implied| == |ROTSPEC| -> ONE rotation, not two.
                theta = _norm_angle(rs_th)
            else:
                return _fail(f"SPECTRA frame declarations conflict: ROTSPEC={rs_th:g} but the HMEAS "
                             f"azimuths imply {az:g} (HX={ev['azm_hx']}, HY={ev['azm_hy']}) — "
                             f"refusing to guess which rotation applies; fix: correct the metadata "
                             f"or re-export in the geographic frame.")
        elif rs_th is not None:
            theta = _norm_angle(rs_th)
        elif az is not None:
            theta = _norm_angle(az)
            if theta != 0.0:
                notes.append(f"frame: spectra HMEAS azimuths imply a {theta:g} deg frame "
                             f"(HX={ev['azm_hx']}, HY={ev['azm_hy']}); no ROTSPEC stated")
        if theta is None or theta == 0.0:
            return _done(None, None)
        notes.append(f"frame: impedance+tipper de-rotated {theta:g} deg -> geographic north "
                     f"(spectra-format source declared ROTSPEC/HMEAS frame)")
        th = [float(theta)] * n_periods
        # Spectra-derived Z and T come from the same rotated channels; both de-rotate together.
        return _done(th, th if has_tipper else None)

    # ---- MT (impedance-block) branch: the >ZROT declaration IS the stored-tensor frame. ----
    theta_z = None
    if ev["zrot"] is not None:
        zr = _mask_sentinels(ev["zrot"])
        # sentinel angles are only acceptable where there is no impedance data to serve
        if len(zr) == n_periods and any(
                v is None and i < len(z_present) and z_present[i] for i, v in enumerate(zr)):
            return _fail("ZROT carries a missing-data sentinel (~1e32) at periods that HAVE "
                         "impedance data — the frame of those estimates is unknowable; fix: "
                         "supply real per-period rotation angles or zero (geographic).")
        u = _uniq_eps(zr)
        # cross-check what the reader itself recorded (mt_metadata nulls sentinels to 0)
        if rot_mtm is not None and len(u) >= 1:
            mu = _uniq_eps([float(v) for v in rot_mtm])
            zr_expect = _uniq_eps([0.0 if v is None else v for v in zr])
            if len(mu) != len(zr_expect) or any(abs(a - b) > ROT_UNIFORM_EPS_DEG
                                                for a, b in zip(mu, zr_expect)):
                return _fail(f"the source >ZROT block ({_angles_summary(u)}) and mt_metadata's "
                             f"parsed rotation ({_angles_summary(mu)}) disagree — the file's frame "
                             f"declaration is not being read faithfully; fix: inspect the EDI's "
                             f"ZROT/RHOROT blocks (dialect issue).")
        nz = [a for a in u if abs(a) > ROT_ZERO_EPS_DEG]
        if nz:
            if len(u) > 1 and not ev["freq_descending"]:
                return _fail(f"per-period ZROT ({_angles_summary(u)}) in a NON-descending "
                             f"frequency file — the angle-to-period alignment after mt_metadata's "
                             f"reorder is unverifiable; fix: re-export with descending frequencies.")
            if len(u) == 1:
                # uniform: broadcast to the TF's period axis (the raw block may have a different
                # length when mt_metadata drops/merges periods; a single angle is order-invariant)
                theta_z = [float(u[0])] * n_periods
                notes.append(f"frame: impedance de-rotated {_norm_angle(u[0]):g} deg -> geographic "
                             f"north (source declared uniform ZROT)")
            else:
                if len(zr) != n_periods:
                    return _fail(f"per-period ZROT has {len(zr)} angles for {n_periods} periods — "
                                 f"cannot map rotation to periods; fix: re-export with one angle "
                                 f"per period.")
                theta_z = [0.0 if v is None else float(v) for v in zr]
                # NOTE text is deliberately station-invariant (no angles) so the survey-level
                # aggregation stays one line per DISTINCT note, not one per station (the ~792-line
                # noise class); the per-period angles live in station.json's frame facts.
                notes.append("frame: impedance de-rotated per period -> geographic north (source "
                             "declared per-period ZROT — principal-axis/PAX-style export; angles "
                             "in station.json frame facts)")
    elif ev["rhorot"] is not None:
        ru = [a for a in _uniq_eps(_mask_sentinels(ev["rhorot"])) if abs(a) > ROT_ZERO_EPS_DEG]
        if ru:
            return _fail(f"no ZROT block, but RHOROT declares a rotated frame "
                         f"({_angles_summary(ru)}) — the impedance frame is undeclared while the "
                         f"apparent-resistivity frame is rotated; refusing to guess; fix: state "
                         f"ZROT explicitly.")
    else:
        az = azimuth_implied_rotation(ev)
        if az is not None and abs(_norm_angle(az)) > ROT_ZERO_EPS_DEG:
            theta_z = [float(_norm_angle(az))] * n_periods
            notes.append(f"frame: impedance de-rotated {_norm_angle(az):g} deg -> geographic north "
                         f"(no ZROT; coherent HMEAS azimuths HX={ev['azm_hx']}, HY={ev['azm_hy']} "
                         f"declare the frame)")
        elif ev["azm_hx"] is not None and az is None:
            notes.append(f"frame: not machine-verifiable — no ZROT block and the HMEAS azimuths "
                         f"(HX={ev['azm_hx']}, HY={ev['azm_hy']}) do not form a coherent "
                         f"orthogonal frame; served as-is under the x=north assumption "
                         f"(sign convention still checked)")

    # ---- tipper frame (independent of Z: e.g. AusLAMP-SA serves PAX-rotated Z with TROT=0). ----
    theta_t = None
    if has_tipper:
        if ev["trot"] is not None:
            tr = _mask_sentinels(ev["trot"])
            tu = _uniq_eps(tr)
            tnz = [a for a in tu if abs(a) > ROT_ZERO_EPS_DEG]
            if any(v is None for v in tr) and tnz:
                return _fail("TROT mixes missing-data sentinels with nonzero angles — the tipper "
                             "frame is unknowable; fix: supply real angles or zero.")
            if tnz:
                if len(tu) == 1:
                    theta_t = [float(tu[0])] * n_periods
                else:
                    if not ev["freq_descending"]:
                        return _fail(f"per-period TROT ({_angles_summary(tu)}) in a NON-descending "
                                     f"frequency file — angle-to-period alignment unverifiable.")
                    if len(tr) != n_periods:
                        return _fail(f"per-period TROT has {len(tr)} angles for {n_periods} "
                                     f"periods — cannot map tipper rotation to periods.")
                    theta_t = [0.0 if v is None else float(v) for v in tr]
                if len(tu) == 1:
                    notes.append(f"frame: tipper de-rotated {_norm_angle(tu[0]):g} deg -> "
                                 f"geographic north (source declared TROT)")
                else:
                    # station-invariant wording for aggregation; angles in station.json facts
                    notes.append("frame: tipper de-rotated per period -> geographic north (source "
                                 "declared per-period TROT; angles in station.json frame facts)")
        elif ev["tipper_rot_attr"] == "ZROT" and theta_z is not None:
            theta_t = list(theta_z)
            notes.append("frame: tipper de-rotated with the impedance (tipper blocks declare "
                         "ROT=ZROT)")
        elif theta_z is not None:
            notes.append("frame: tipper NOT de-rotated (no TROT declaration) while the impedance "
                         "was — tipper assumed already geographic")

    return _done(theta_z, theta_t)


# ---------------------------------------------------------------------------------------------
# De-rotation (the math is pinned by tests AND by the AusLAMP-SA custodian-twin proof).
# ---------------------------------------------------------------------------------------------
def _rot_mat(deg: float):
    import numpy as np  # noqa: PLC0415  (house style: function-local heavy imports)
    b = math.radians(deg)
    return np.array([[math.cos(b), math.sin(b)], [-math.sin(b), math.cos(b)]])


def apply_derotation(tf, disp: FrameDisposition) -> int:
    """De-rotate the TF object's impedance/tipper (and their errors) IN MEMORY per the disposition.
    The source file is never touched (D1). Periods with PARTIAL impedance components (a fill/zero
    among finite values) cannot be rotated honestly — rotation would mix the fill into every
    element — so those periods are masked wholesale (NaN) and counted; returns that count (the
    caller notes it). Errors propagate in quadrature: var'_ij = Σ_kl (R_ik R_jl)² var_kl."""
    import numpy as np  # noqa: PLC0415

    n_masked = 0
    if disp.theta_z is not None and tf.has_impedance():
        Z = np.asarray(tf.impedance.data).copy()
        Ze = (np.asarray(tf.impedance_error.data).copy()
              if getattr(tf, "impedance_error", None) is not None else None)
        for i in range(Z.shape[0]):
            zi = Z[i]
            finite = np.isfinite(zi) & (np.abs(zi) < ROT_FILL_MAX)
            nonfill = finite & ~((zi.real == 0.0) & (zi.imag == 0.0))
            if not nonfill.any():
                continue                      # nothing real at this period; leave as-is
            if not nonfill.all():
                Z[i] = np.nan                 # partial period: rotation would smear the fill
                if Ze is not None:
                    Ze[i] = np.nan
                n_masked += 1
                continue
            R = _rot_mat(-float(disp.theta_z[i]))
            Z[i] = R @ zi @ R.T
            if Ze is not None:
                W = np.abs(np.einsum("ik,jl->ijkl", R, R))   # |R_ik R_jl|
                Ze[i] = np.sqrt(np.einsum("ijkl,kl->ij", W ** 2, Ze[i] ** 2))
        tf.impedance = Z
        if Ze is not None:
            tf.impedance_error = Ze
    if disp.theta_t is not None and tf.has_tipper():
        T = np.asarray(tf.tipper.data).copy()
        Te = (np.asarray(tf.tipper_error.data).copy()
              if getattr(tf, "tipper_error", None) is not None else None)
        for i in range(T.shape[0]):
            ti = T[i]
            finite = np.isfinite(ti) & (np.abs(ti) < ROT_FILL_MAX)
            nonfill = finite & ~((ti.real == 0.0) & (ti.imag == 0.0))
            if not nonfill.any():
                continue
            if not nonfill.all():
                T[i] = np.nan
                if Te is not None:
                    Te[i] = np.nan
                n_masked += 1
                continue
            R = _rot_mat(-float(disp.theta_t[i]))
            T[i] = ti @ R.T
            if Te is not None:
                Te[i] = np.sqrt((Te[i] ** 2) @ (R.T ** 2))
        tf.tipper = T
        if Te is not None:
            tf.tipper_error = Te
    # The in-memory TF now represents the geographic frame; keep its own metadata consistent so
    # downstream consumers of THIS object (components/record) cannot re-apply the source frame.
    if disp.theta_z is not None:
        try:
            import numpy as np  # noqa: PLC0415
            tf._rotation_angle = np.zeros(int(np.asarray(tf.period).size))
        except Exception:  # noqa: BLE001
            pass
    return n_masked


def z_present_mask(tf) -> list:
    """Per-period 'any real impedance element present' mask (same missing convention as
    _mtm._is_missing: NaN / ~1e32 fill / exact complex zero are absent)."""
    import numpy as np  # noqa: PLC0415
    if not tf.has_impedance():
        return []
    Z = np.asarray(tf.impedance.data)
    out = []
    for i in range(Z.shape[0]):
        zi = Z[i]
        present = np.isfinite(zi) & (np.abs(zi) < ROT_FILL_MAX) \
            & ~((zi.real == 0.0) & (zi.imag == 0.0))
        out.append(bool(present.any()))
    return out


# ---------------------------------------------------------------------------------------------
# Gate 2 — sign-convention quadrant check (on the SERVED, post-derotation components).
# ---------------------------------------------------------------------------------------------
def convention_check(comp: Optional[dict]) -> dict:
    """Quadrant verdict from the canonical component dict (_mtm.components_from_tf output — the
    exact arrays the portal serves). Returns a JSON-safe dict:
        {verdict, phs_xy_median_deg, phs_yx_median_deg, n_periods_used, detail}
    verdict: "ok" | "warn_xy" | "warn_yx" | "fail" | "insufficient".
    Medians over the mid-band (central 60%) of USABLE periods only — a period is usable when both
    off-diagonal phases exist and both |Z| clear CONVENTION_MIN_ABS_Z (degenerate/masked artifacts
    must never manufacture a verdict). arg(Zyx) is compared on a wrap-safe axis (values mapped to
    (-360, 0]) so a legitimate median at ±180 does not straddle the representation seam."""
    def _series(k):
        v = (comp or {}).get(k)
        return v if v else []

    pxy, pyx = _series("PHSXY"), _series("PHSYX")
    zxyr, zxyi = _series("ZXYR"), _series("ZXYI")
    zyxr, zyxi = _series("ZYXR"), _series("ZYXI")
    n = max(len(pxy), len(pyx))
    usable = []
    for i in range(n):
        try:
            a, b = pxy[i], pyx[i]
            xr, xi, yr, yi = zxyr[i], zxyi[i], zyxr[i], zyxi[i]
        except IndexError:
            continue
        if a is None or b is None or None in (xr, xi, yr, yi):
            continue
        if math.hypot(xr, xi) < CONVENTION_MIN_ABS_Z or math.hypot(yr, yi) < CONVENTION_MIN_ABS_Z:
            continue
        usable.append((float(a), float(b)))
    if len(usable) < CONVENTION_MIN_PERIODS:
        return {"verdict": "insufficient", "phs_xy_median_deg": None, "phs_yx_median_deg": None,
                "n_periods_used": len(usable),
                "detail": f"only {len(usable)} usable period(s) (< {CONVENTION_MIN_PERIODS}) — "
                          f"no convention verdict"}
    lo = int(len(usable) * MIDBAND_LO_FRAC)
    hi = max(int(math.ceil(len(usable) * MIDBAND_HI_FRAC)), lo + 1)
    mid = usable[lo:hi]

    def _median(vals):
        s = sorted(vals)
        m = len(s) // 2
        return s[m] if len(s) % 2 else 0.5 * (s[m - 1] + s[m])

    med_xy = _median([a for a, _ in mid])
    # wrap-safe axis for yx: map to (-360, 0] so Q3 (with slack) is one contiguous window and a
    # legitimate median near ±180 cannot straddle the atan2 representation seam
    med_yx_mapped = _median([(b if b <= 0 else b - 360.0) for _, b in mid])
    xy_ok = -QUADRANT_SLACK_DEG <= med_xy <= 90.0 + QUADRANT_SLACK_DEG
    yx_ok = (-180.0 - QUADRANT_SLACK_DEG) <= med_yx_mapped <= (-90.0 + QUADRANT_SLACK_DEG)
    med_yx_report = round(med_yx_mapped + 360.0, 2) if med_yx_mapped < -180.0 else round(med_yx_mapped, 2)
    base = {"phs_xy_median_deg": round(med_xy, 2), "phs_yx_median_deg": med_yx_report,
            "n_periods_used": len(usable)}
    if xy_ok and yx_ok:
        return {"verdict": "ok", **base, "detail": None}
    if not xy_ok and not yx_ok:
        # both coherently wrong: name the signature (the convention-specific message). Ranges are
        # in the (-180,180] reporting representation, slack-widened.
        s = QUADRANT_SLACK_DEG
        if (-100.0 - s) <= med_xy <= 0.0 and (80.0 - s) <= med_yx_report <= 180.0:
            sig = "e^{-i omega t} conjugation signature (arg Zxy in Q4, arg Zyx in Q2)"
        elif (-190.0 <= med_xy <= (-80.0 + s)) and (0.0 <= med_yx_report <= (100.0 + s)):
            sig = "x/y axis-swap signature (arg Zxy in Q3, arg Zyx in Q1)"
        else:
            sig = "coherent out-of-quadrant phases"
        return {"verdict": "fail", **base,
                "detail": f"BOTH off-diagonal phase medians violate the e^{{+i omega t}} "
                          f"x=north/y=east quadrants (arg Zxy={med_xy:.1f} deg not in Q1, "
                          f"arg Zyx={med_yx_report:.1f} deg not in Q3; slack "
                          f"{QUADRANT_SLACK_DEG:g} deg) — {sig}; fix: verify the processing "
                          f"sign convention / channel mapping and re-export."}
    which = "warn_xy" if not xy_ok else "warn_yx"
    comp_name, med = ("arg(Zxy)", med_xy) if not xy_ok else ("arg(Zyx)", med_yx_report)
    return {"verdict": which, **base,
            "detail": f"{comp_name} mid-band median {med:.1f} deg is outside its expected quadrant "
                      f"while the other off-diagonal is in-quadrant — possible 3D/distortion "
                      f"effect, served with this note (not a convention failure)"}
