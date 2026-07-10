"""Phase-quadrant classification for the C43 curator-workbench Stations plots (S2a-1).

PURE FUNCTIONS, no I/O — the AUTHORITATIVE specification of the workbench's phase handling, so the
classification logic is unit-testable server-side (record D13 / the contract's "test the classification
logic at the JS-data seam" — a server-side helper is that seam). The browser-side STATIONS_JS mirrors
these exact rules (the +180 unwrap and the Q1/Q3 bounds); this module is the single source of truth a
pin exercises with synthetic tf rows, and a source-level assertion checks the JS embeds the same
constants.

THE ONE LOAD-BEARING FACT (verified against engine/extract/_edi_tf.py:143):
  tf.json t[4] = phs_yx_adj is stored with a +180 PRESENTATION SHIFT — `norm_phase(pyx, add=180.0)`.
  So the TRUE φyx = stored − 180, re-wrapped to (−180, 180]. A station whose TRUE φyx is in Q3
  (−180…−90 — the physically expected quadrant for yx) therefore has a STORED t[4] near 0…90. Reading
  the stored value AS the true phase would mis-classify a healthy Q3 station as Q1 — the exact trap the
  φyx-unwrap pin guards.

  φxy (t[3]) carries NO shift — it is stored as the true phase and its expected quadrant is Q1 (0…90).
"""
from __future__ import annotations

# The presentation shift baked into stored φyx (t[4]) by _edi_tf.norm_phase(pyx, add=180.0). The
# workbench SUBTRACTS this to recover the true phase before classifying/plotting.
YX_PRESENTATION_SHIFT_DEG = 180.0

# Expected quadrants (inclusive bounds, degrees). xy is expected in Q1; TRUE yx is expected in Q3.
Q1_LO, Q1_HI = 0.0, 90.0
Q3_LO, Q3_HI = -180.0, -90.0


def wrap180(phase: float) -> float:
    """Wrap a phase (degrees) into (−180, 180] — the same wrap _edi_tf.norm_phase applies. Idempotent
    on already-wrapped values; used to re-wrap after removing the yx presentation shift."""
    return ((phase + 180.0) % 360.0) - 180.0


def true_phi_yx(stored_phs_yx_adj: float | None) -> float | None:
    """Recover the TRUE φyx from the STORED t[4] (phs_yx_adj): subtract the +180 presentation shift and
    re-wrap to (−180, 180]. None passes through (a missing point stays missing)."""
    if stored_phs_yx_adj is None:
        return None
    return round(wrap180(stored_phs_yx_adj - YX_PRESENTATION_SHIFT_DEG), 1)


def in_quadrant_xy(phs_xy: float | None) -> bool | None:
    """True iff φxy (t[3], stored = true) is in the expected Q1 (0…90). None => no verdict for a
    missing point (excluded from the aggregate verdict)."""
    if phs_xy is None:
        return None
    return Q1_LO <= phs_xy <= Q1_HI


def in_quadrant_yx(stored_phs_yx_adj: float | None) -> bool | None:
    """True iff the TRUE φyx (after unwrapping the +180 shift from the stored t[4]) is in the expected
    Q3 (−180…−90). None => no verdict for a missing point. This is the function that must read the
    STORED value, unwrap it, and classify the TRUE phase — reading the stored value directly is the
    bug the φyx-unwrap pin catches."""
    true_yx = true_phi_yx(stored_phs_yx_adj)
    if true_yx is None:
        return None
    return Q3_LO <= true_yx <= Q3_HI


def classify_series(values: list, *, mode: str) -> dict:
    """Classify a whole phase series (a tf column) into per-point in/out-of-quadrant flags + an
    aggregate verdict. `mode` is 'xy' (values are stored=true φxy, expected Q1) or 'yx' (values are
    stored phs_yx_adj, unwrapped to true φyx, expected Q3).

    Returns {points: [bool|None,...], any_out: bool, all_in: bool, n_classified: int}. `any_out` is
    True iff at least one CLASSIFIED point is out of quadrant (drives the ⚠ verdict + red points);
    `all_in` iff every classified point is in quadrant (the ✓ verdict). A series of all-None (no phase
    data) yields any_out=False, all_in=False, n_classified=0 (no verdict)."""
    if mode == "xy":
        classify = in_quadrant_xy
    elif mode == "yx":
        classify = in_quadrant_yx
    else:
        raise ValueError(f"mode must be 'xy' or 'yx', got {mode!r}")
    points = [classify(v) for v in (values or [])]
    classified = [p for p in points if p is not None]
    any_out = any(p is False for p in classified)
    all_in = bool(classified) and all(classified)
    return {"points": points, "any_out": any_out, "all_in": all_in,
            "n_classified": len(classified)}
