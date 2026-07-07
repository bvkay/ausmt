#!/usr/bin/env python3
"""AusMT science layer: per-station diagnostics from a parsed EDI (importable library; the build
pipeline calls science_from_components).

Per station: [q, qb, rr, sw, alg, dim, p3d, gd, ellip, skew, mre, decades]
  q    quality score 0-5 (one dp) | qb basis: 'e'=error-based, 's'=shape-based
  rr   remote reference: 1=stated, 0=unknown (absence of INFO != "no RR")
  sw   processing software string | null      alg algorithm string | null
  dim  "1-D"/"2-D"/"3-D" | null (phase-tensor)  p3d % periods |beta|>3 deg
  gd   galvanic/static-shift heuristic 1/0      ellip median PT ellipticity
  skew median |beta| (deg)                      mre median relative impedance error | null
  decades  period coverage in log10 decades
All metrics are AUTOMATED, INDICATIVE. The schema keeps a separate curated rating.

The component dict is built by mt_metadata (`_mtm.components_from_tf`); the phase-tensor math and
the impedance->rho/phase fallback are shared with `_edi_tf` via `_ediparse`, so the TF and science
layers cannot diverge. `science_from_components` is the diagnostics entry; `proc_info` is the
best-effort processing-metadata text scrape (mt_metadata leaves sw/alg/rr empty for many dialects).
"""
import math
import statistics as st

import _ediparse as ep  # noqa: E402  (shared math: pt_params/drho/dphase)

# Authoritative sci.json column order (one row per station, aligned to catalogue.json) — SINGLE-SOURCED
# in contract/columns.json, imported here. Consumed BY POSITION in build_portal.py and the portal JS
# (portal/src/contract.js SC.* map). Regenerate with `python contract/generate.py`. APPEND, never reorder.
from _contract import SCI_COLUMNS  # noqa: E402  (used by the sci-row projection; also re-exported as sci.SCI_COLUMNS)

# --- Dimensionality decision-boundary parameters (SINGLE SOURCE OF TRUTH) ----------------------
# These thresholds define the phase-tensor dimensionality screening in science_from_components.
# build_portal._build_prov() READS these constants (and _ediparse.PT_MIN_REZ_ROW_SINE) for the
# provenance block, so the parameters recorded in build_provenance.json CANNOT drift from the ones
# actually applied here. Change a value in exactly one place. The provenance JSON key names mirror
# these constants (the "_deg" suffix on ELLIP_2D is a back-compat misnomer: ellipticity is
# dimensionless, but the published provenance key is "ellip_2d_deg").
BETA_PER_PERIOD_DEG = 3.0        # a period counts toward %3-D when |beta| exceeds this (deg)
SKEW_3D_DEG = 5.0                # median |beta| above this => 3-D (deg)
PCT_PERIODS_3D_THRESHOLD = 40    # OR this percent of usable periods exceeding BETA_PER_PERIOD_DEG => 3-D
ELLIP_2D_DEG = 0.10             # median ellipticity above this (when not 3-D) => 2-D (dimensionless)
BETA_PHYSICAL_CAP_DEG = 15.0    # |beta| at/above this is non-physical (bad data), excluded from the vote
MIN_USABLE_PERIOD_FRAC = 0.5    # < this fraction of usable periods => "indeterminate"
SKEW_AGGREGATION = "median"     # survey-level skew aggregation (median resists saturated outliers)


def proc_info(text):
    import re
    sw = re.search(r"[Pp]rocessing\s+code\s*:\s*(\S+)", text)
    alg = re.search(r"[Aa]lgorithm\s*:\s*(.+)", text)
    rr = bool(re.search(r"remote\s*reference", text, re.I))
    return (sw.group(1) if sw else None,
            alg.group(1).strip() if alg else None,
            1 if rr else 0)


def pt_per_period(zr, zi):
    """Per-period (pmin,pmax,az,beta) in degrees from Z real/imag component dicts. Delegates each
    period to the single phase-tensor implementation in `_ediparse.pt_params` (which carries the
    near-singular guard), so the science layer and the TF builder cannot diverge."""
    n = max((len(v) for v in zr.values() if v), default=0)
    out = []
    for i in range(n):
        try:
            args = (zr["xx"][i], zi["xx"][i], zr["xy"][i], zi["xy"][i],
                    zr["yx"][i], zi["yx"][i], zr["yy"][i], zi["yy"][i])
        except (IndexError, KeyError, TypeError):
            out.append((None, None, None, None))
            continue
        out.append(ep.pt_params(*args))
    return out


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def science_from_components(periods, comp, proc):
    """Diagnostics from a canonical component dict — SHARED by the regex and mt_metadata
    extractors, so dimensionality/diagnostic differences trace purely to parsing."""
    if not periods:
        # no periods -> a NULL sci row, built by name + projected through SCI_COLUMNS (self-following,
        # so a reorder of contract/columns.json can't silently mis-place these values).
        empty = {"q": None, "qb": "s", "rr": 0, "sw": None, "alg": None, "dim": None,
                 "p3d": None, "gd": 0, "ellip": None, "skew": None, "mre": None, "decades": 0}
        return [empty[c] for c in SCI_COLUMNS]
    valid_per = [p for p in periods if p]
    decades = (math.log10(max(valid_per)) - math.log10(min(valid_per))) if len(valid_per) > 1 else 0
    rxy, ryx = comp.get("RHOXY"), comp.get("RHOYX")
    pxy, pyx = comp.get("PHSXY"), comp.get("PHSYX")
    exy, eyx = comp.get("RHOXY.ERR"), comp.get("RHOYX.ERR")
    sw, alg, rr = proc or (None, None, 0)

    # Same fallback as the TF builder: derive rho/phi from impedance when the EDI omits the
    # RHOXY/PHSXY blocks (impedance-only EDL/BIRRP), so completeness/smoothness reflect real data.
    zfb = {c: (comp.get("Z" + c.upper() + "R"), comp.get("Z" + c.upper() + "I")) for c in ("xy", "yx")}
    if not rxy and zfb["xy"][0] and zfb["xy"][1]:
        rxy = ep.drho(periods, *zfb["xy"])
    if pxy is None and zfb["xy"][0] and zfb["xy"][1]:
        pxy = ep.dphase(periods, *zfb["xy"])
    if not ryx and zfb["yx"][0] and zfb["yx"][1]:
        ryx = ep.drho(periods, *zfb["yx"])
    if pyx is None and zfb["yx"][0] and zfb["yx"][1]:
        pyx = ep.dphase(periods, *zfb["yx"])

    n = len(periods)
    def at(a, i):
        return a[i] if a and i < len(a) else None

    # completeness: periods with usable rho+phase
    good = sum(1 for i in range(n) if at(rxy, i) and at(rxy, i) > 0 and at(pxy, i) is not None)
    completeness = good / n if n else 0
    coverage = clamp(decades / 4.0)

    # phase smoothness (second-difference roughness on xy phase)
    ph = [at(pxy, i) for i in range(n) if at(pxy, i) is not None]
    if len(ph) >= 3:
        d2 = [abs(ph[k - 1] - 2 * ph[k] + ph[k + 1]) for k in range(1, len(ph) - 1)]
        rough = st.median(d2)
        smooth = clamp(1 - rough / 25.0)
    else:
        smooth = 0.5

    # error-based score where errors exist
    rel = []
    for i in range(n):
        for r, e in ((at(rxy, i), at(exy, i)), (at(ryx, i), at(eyx, i))):
            if r and r > 0 and e is not None and e >= 0:
                rel.append(e / r)
    if rel:
        med = st.median(rel)
        errscore = clamp((math.log10(0.30) - math.log10(max(med, 1e-3))) / (math.log10(0.30) - math.log10(0.02)))
        q = 5 * (0.45 * errscore + 0.18 * coverage + 0.15 * completeness + 0.22 * smooth)
        qb = "e"
        mre = round(med, 3)
    else:
        q = 5 * (0.40 * coverage + 0.30 * completeness + 0.30 * smooth)
        qb = "s"
        mre = None

    # phase tensor dimensionality
    zr = {c: comp.get("Z" + c.upper() + "R") for c in ("xx", "xy", "yx", "yy")}
    zi = {c: comp.get("Z" + c.upper() + "I") for c in ("xx", "xy", "yx", "yy")}
    # |beta| above this is non-physical: phase-tensor skew of real structure is a few degrees,
    # whereas a dead channel or trace(Phi)->0 degeneracy drives |beta| toward its 45 deg ceiling.
    # Such periods are evidence of bad data, NOT of 3-D structure, so they are excluded from the
    # vote and counted as unusable (the near-singular Re(Z) guard in pt_per_period catches the
    # row-collinear case; this cap also catches the trace-degenerate case).
    BETA_CAP = BETA_PHYSICAL_CAP_DEG
    dim = p3d = ellip = skew = None
    if zr["xy"]:
        pts = pt_per_period(zr, zi)
        raw_n = sum(1 for v in zr["xy"] if v is not None)   # periods that carry an xy impedance
        good = [(mn, mx, abs(b)) for (mn, mx, _az, b) in pts
                if b is not None and abs(b) < BETA_CAP]     # physical periods only
        betas = [b for (_mn, _mx, b) in good]
        ells = [abs(mx - mn) / (abs(mx) + abs(mn)) for (mn, mx, _b) in good
                if (abs(mx) + abs(mn)) > 1e-6]
        if betas:
            # median, not mean: a few residual saturated periods must not drag the survey-level
            # skew (the mean turned noisy broadband sites into false "3-D").
            skew = round(st.median(betas), 1)
            p3d = round(100 * sum(1 for b in betas if b > BETA_PER_PERIOD_DEG) / len(betas))
            ellip = round(st.median(ells), 3) if ells else 0.0
        if raw_n and len(betas) < MIN_USABLE_PERIOD_FRAC * raw_n:
            # Most periods are missing, near-singular, or beta-saturated: the data do not support
            # a dimensionality call. Say so, rather than defaulting to "3-D" off saturated skew.
            dim = "indeterminate"
        elif not betas:
            dim = None
        elif skew > SKEW_3D_DEG or p3d > PCT_PERIODS_3D_THRESHOLD:
            dim = "3-D"
        elif ellip > ELLIP_2D_DEG:
            dim = "2-D"
        else:
            dim = "1-D"

    # galvanic / static-shift heuristic: rho modes offset by a near-constant
    # factor in log space while phases coincide (classic static shift signature)
    gd = 0
    lr, pdif = [], []
    for i in range(n):
        a, b = at(rxy, i), at(ryx, i)
        pa, pb = at(pxy, i), at(pyx, i)
        if a and b and a > 0 and b > 0:
            lr.append(math.log10(a / b))
        if pa is not None and pb is not None:
            # pb is yx phase (3rd quadrant); compare magnitude to xy
            pdif.append(abs(pa - (pb + 180 if pb < -90 else pb)))
    if len(lr) >= 5 and abs(st.mean(lr)) > math.log10(1.6) and st.pstdev(lr) < 0.15 \
            and pdif and st.mean(pdif) < 10:
        gd = 1

    # Build the row BY NAME, then project through SCI_COLUMNS so the emit order self-follows the
    # contract (a reorder regenerates _contract.py and this projection tracks it). Byte-identical.
    row = {"q": round(q, 1), "qb": qb, "rr": rr, "sw": sw, "alg": alg, "dim": dim,
           "p3d": p3d, "gd": gd, "ellip": ellip, "skew": skew, "mre": mre, "decades": round(decades, 1)}
    return [row[c] for c in SCI_COLUMNS]
