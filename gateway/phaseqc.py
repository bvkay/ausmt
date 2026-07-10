"""Phase-quadrant classification for the C43 curator-workbench Stations plots (S2a-1, fix-round F4).

PURE FUNCTIONS, no I/O — the AUTHORITATIVE specification of the workbench's phase handling, so the
classification logic is unit-testable server-side (record D13 / the contract's "test the classification
logic at the JS-data seam" — a server-side helper is that seam). The browser-side STATIONS_JS mirrors
these exact rules; an EXECUTABLE Node parity pin (test_c43_stage2a_js_parity.py) runs the extracted JS
against this module over a boundary-heavy vector sweep, so the mirror cannot drift semantically (the
fix-round F1 lesson: a source-string pin let a truncated-vs-floored modulo divergence ship).

THE ONE LOAD-BEARING FACT (verified against engine/extract/_edi_tf.py:143):
  tf.json t[4] = phs_yx_adj is stored with a +180 PRESENTATION SHIFT — `norm_phase(pyx, add=180.0)`.
  So the TRUE φyx = stored − 180, re-wrapped. A station whose TRUE φyx is in Q3 (−180…−90 — the
  physically expected quadrant for yx) therefore has a STORED t[4] near 0…90. Reading the stored value
  AS the true phase would mis-classify a healthy Q3 station — the trap the φyx-unwrap pin guards.

  φxy (t[3]) carries NO shift — it is stored as the true phase and its expected quadrant is Q1 (0…90).

ENGINE-GATE ALIGNMENT (fix-round F4, architect ruling): the engine's Gate-2 convention check
(engine/extract/_conventions.py convention_check) judges MEDIANS against the quadrant bands widened by
QUADRANT_SLACK_DEG, with arg(Zyx) compared on a wrap-safe axis (values mapped to (−360, 0] so a
legitimate median near ±180 cannot straddle the atan2 representation seam). The workbench mirrors that
rule exactly:
  * per-POINT flags (the red dots) — a point is flagged only when it sits outside its band by MORE
    than the slack (band ± QUADRANT_SLACK_DEG), on the same seam-mapped axis for yx;
  * the VERDICT (the strip beneath each phase plot) — the MEDIAN of the classified points vs
    band + slack, and the strip text carries the median value.
"""
from __future__ import annotations

# The presentation shift baked into stored φyx (t[4]) by _edi_tf.norm_phase(pyx, add=180.0). The
# workbench SUBTRACTS this to recover the true phase before classifying/plotting.
YX_PRESENTATION_SHIFT_DEG = 180.0

# Expected quadrants (inclusive bounds, degrees). xy is expected in Q1; TRUE yx is expected in Q3
# (checked on the (−360, 0] seam-mapped axis, where Q3 ± slack is one contiguous window).
Q1_LO, Q1_HI = 0.0, 90.0
Q3_LO, Q3_HI = -180.0, -90.0

# Tolerance slack at the quadrant edges — MUST equal the engine gate's single-sourced constant
# (engine/extract/_conventions.py:98 QUADRANT_SLACK_DEG = 10.0); a cross-import parity pin asserts the
# two are equal so the workbench verdicts can never silently diverge from the served-corpus gate.
QUADRANT_SLACK_DEG = 10.0


def wrap180(phase: float) -> float:
    """Wrap a phase (degrees) into [−180, 180) — Python's floored % (non-negative remainder for the
    positive modulus), the same wrap _edi_tf.norm_phase applies. NOTE for the JS mirror: JS `%` is
    TRUNCATED (keeps the dividend's sign) — the fix-round F1 divergence (735 sweep mismatches) was
    exactly this. The mirror must ALSO be bit-faithful, not merely floored-in-semantics: CPython's
    float % is fmod + ONE conditional add, so the JS mirror is `floormod` (r = x % y; r < 0 && r !== 0
    ? r + y : r) — the ((x%360)+360)%360 idiom's unconditional add drifts 1 ulp on negative remainders
    and flips 1dp rounding at the slack edges (caught by the executable parity pin)."""
    return ((phase + 180.0) % 360.0) - 180.0


def true_phi_yx(stored_phs_yx_adj: float | None) -> float | None:
    """Recover the TRUE φyx from the STORED t[4] (phs_yx_adj): subtract the +180 presentation shift and
    re-wrap. None passes through (a missing point stays missing)."""
    if stored_phs_yx_adj is None:
        return None
    return round(wrap180(stored_phs_yx_adj - YX_PRESENTATION_SHIFT_DEG), 1)


def _map_yx(true_yx: float) -> float:
    """The engine gate's wrap-safe yx axis: map a TRUE φyx from (−180, 180] to (−360, 0] so Q3 ± slack
    is one contiguous window and a value/median near ±180 cannot straddle the representation seam
    (mirrors _conventions.convention_check's `b if b <= 0 else b - 360.0`)."""
    return true_yx if true_yx <= 0 else true_yx - 360.0


def in_quadrant_xy(phs_xy: float | None) -> bool | None:
    """True iff φxy (t[3], stored = true) is within Q1 widened by the slack (−slack … 90+slack — the
    engine gate's xy band). None => no flag for a missing point. A False drives a RED dot: the point is
    outside the band by MORE than the slack (fix-round F4b)."""
    if phs_xy is None:
        return None
    return (Q1_LO - QUADRANT_SLACK_DEG) <= phs_xy <= (Q1_HI + QUADRANT_SLACK_DEG)


def in_quadrant_yx(stored_phs_yx_adj: float | None) -> bool | None:
    """True iff the TRUE φyx (after unwrapping the +180 shift from the stored t[4]) is within Q3
    widened by the slack, judged on the seam-mapped (−360, 0] axis (−180−slack … −90+slack — the
    engine gate's yx band; a true value of +175 maps to −185, within slack of the −180 edge). None =>
    no flag. Reading the stored value directly is the bug the φyx-unwrap pin catches."""
    true_yx = true_phi_yx(stored_phs_yx_adj)
    if true_yx is None:
        return None
    mapped = _map_yx(true_yx)
    return (Q3_LO - QUADRANT_SLACK_DEG) <= mapped <= (Q3_HI + QUADRANT_SLACK_DEG)


def _median(vals: list) -> float:
    """The engine gate's median (sorted; middle element, or the mean of the two middles) — mirrored
    from _conventions.convention_check._median so the two verdicts share one definition."""
    s = sorted(vals)
    m = len(s) // 2
    return s[m] if len(s) % 2 else 0.5 * (s[m - 1] + s[m])


def classify_series(values: list, *, mode: str) -> dict:
    """Classify a whole phase series (a tf column) into per-point flags + the MEDIAN verdict (fix-round
    F4c — engine-rule alignment). `mode` is 'xy' (values are stored=true φxy, expected Q1) or 'yx'
    (values are stored phs_yx_adj, unwrapped to true φyx, expected Q3 on the seam-mapped axis).

    Returns {points, any_out, n_classified, median, median_in}:
      * points   — per-point bool|None (band ± slack; False = a RED dot);
      * any_out  — True iff at least one classified point is outside band+slack;
      * median   — the RAW (unrounded) median of the classified TRUE values; for yx it is computed on
        the seam-mapped (−360, 0] axis and reported back in (−180, 180] (the engine's med_yx_report
        rule: mapped + 360 when the mapped median is below −180). None when nothing classified.
        Raw, not rounded: the JS parity pin compares medians EXACTLY (identical doubles in, identical
        sort + 0.5*(a+b) arithmetic out); display rounding is presentation-only, in the strip.
      * median_in — the VERDICT: the median (seam-mapped for yx) within band + slack. This is what the
        strip beneath the plot shows ('median φyx −134.8° — in quadrant ✓' / 'out of quadrant ⚠').
    A series of all-None yields points all-None, any_out=False, median=None, median_in=None."""
    if mode == "xy":
        points = [in_quadrant_xy(v) for v in (values or [])]
        trues = [v for v in (values or []) if v is not None]
        if not trues:
            return {"points": points, "any_out": False, "n_classified": 0,
                    "median": None, "median_in": None}
        med = _median(trues)
        med_in = (Q1_LO - QUADRANT_SLACK_DEG) <= med <= (Q1_HI + QUADRANT_SLACK_DEG)
        med_report = med
    elif mode == "yx":
        points = [in_quadrant_yx(v) for v in (values or [])]
        raw_trues = [true_phi_yx(v) for v in (values or [])]
        trues = [t for t in raw_trues if t is not None]
        if not trues:
            return {"points": points, "any_out": False, "n_classified": 0,
                    "median": None, "median_in": None}
        med_mapped = _median([_map_yx(t) for t in trues])
        med_in = (Q3_LO - QUADRANT_SLACK_DEG) <= med_mapped <= (Q3_HI + QUADRANT_SLACK_DEG)
        med_report = med_mapped + 360.0 if med_mapped < -180.0 else med_mapped
    else:
        raise ValueError(f"mode must be 'xy' or 'yx', got {mode!r}")
    classified = [p for p in points if p is not None]
    return {"points": points,
            "any_out": any(p is False for p in classified),
            "n_classified": len(classified),
            "median": med_report,
            "median_in": med_in}
