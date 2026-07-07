#!/usr/bin/env python3
"""Shared EDI text + transfer-function math, used by the kept `_edi_*` helpers.

After the regex retirement, mt_metadata does the EDI parsing; this module is the single
source of truth for the read-time helpers and the downstream math that BOTH the TF builder
(`_edi_tf`) and the science layer (`_edi_science`) consume, so they cannot diverge:

  * `_norm`            — read-time normalisation (CRLF/CR endings, indented markers)
  * `read_norm`        — read a file and normalise it (cached, so the same EDI is read
                         from disk once even when the coord-QC and processing-note helpers
                         all need it in the same build)
  * `pt_params`        — THE Caldwell phase-tensor implementation (shared, with the
                         near-singular guard)
  * `drho` / `dphase`  — the impedance -> apparent-resistivity / phase fallback
  * `COMPONENT_KEYS` / `EMPTY_TF` — the canonical component-key superset and the empty TF row

Stdlib only and no project imports, so it is safe to import from any module on the
`extract/` path.
"""
from functools import lru_cache
import math
from pathlib import Path

NUM = r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
_EMPTY = 1e30  # EDI 'no data' sentinel magnitude

# One canonical empty transfer-function row: 18 component arrays (C20 grew tf.json 10 -> 18 with the
# error columns + full complex tipper). Module-level so the many placeholder sites share a single
# definition; kept literal here because _ediparse imports NO project module (it must be safe to import
# from anywhere on the extract/ path) so it can't read TF_COLUMNS from the generated contract. The
# build's width guard (build_portal, driven BY TF_COLUMNS) is the check that this literal stays in
# lockstep with the contract. TF rows are only serialised, never mutated, so sharing the object is
# safe; do NOT mutate it in place.
EMPTY_TF = [[] for _ in range(18)]

# The component blocks both consumers may need, as one superset. `tf_from_components`
# reads RHO/PHS/Z/T; `science_from_components` reads RHO/PHS/<.ERR>/Z. Parsing the union
# once lets a single parse feed both, with `None` for any block the EDI omits.
COMPONENT_KEYS = (
    "RHOXY", "RHOYX", "PHSXY", "PHSYX", "RHOXY.ERR", "RHOYX.ERR",
    "PHSXY.ERR", "PHSYX.ERR",
    "ZXXR", "ZXXI", "ZXYR", "ZXYI", "ZYXR", "ZYXI", "ZYYR", "ZYYI",
    "TXR", "TXI", "TYR", "TYI",
)


def _norm(s):
    # Real-world EDIs vary: CRLF/CR endings and leading indentation before >MARKERS / KEY=
    # lines (e.g. EDL/BIRRP). Normalise endings and left-strip each line so the ^-anchored
    # regexes match.
    return "\n".join(ln.lstrip() for ln in s.replace("\r\n", "\n").replace("\r", "\n").split("\n"))


@lru_cache(maxsize=16)
def read_norm(path: Path) -> str:
    """Read an EDI (latin-1, lenient) and normalise it, in one place.

    Cached (small, bounded): within a build the catalogue parse, the TF parse and the
    science parse all want the same normalised text in quick succession, so this turns the
    historical three reads-per-station into one. The cache holds strings (immutable), so it
    is safe; the bound keeps memory trivial even for the large bulk seed.
    """
    return _norm(Path(path).read_text(encoding="latin-1", errors="replace"))


def drho(periods, zr, zi):
    """Apparent resistivity rho = 0.2*T*|Z|^2 derived from impedance, per period.

    Used as a fallback when an EDI carries Z but omits the RHOXY/PHSXY blocks
    (impedance-only EDL/BIRRP). Shared verbatim by the TF and science layers.
    """
    return [(0.2 * periods[i] * (zr[i] ** 2 + zi[i] ** 2))
            if (zr and zi and i < len(zr) and i < len(zi)
                and zr[i] is not None and zi[i] is not None and periods[i]) else None
            for i in range(len(periods))]


def dphase(periods, zr, zi):
    """Phase phi = atan2(Im Z, Re Z) in degrees, per period (impedance fallback)."""
    return [math.degrees(math.atan2(zi[i], zr[i]))
            if (zr and zi and i < len(zr) and i < len(zi)
                and zr[i] is not None and zi[i] is not None) else None
            for i in range(len(periods))]


# Near-singular guard: skip a period when the two rows of Re(Z) are within this sine of collinear
# (a dead channel), which would otherwise produce a spurious |beta|->45 deg. Named once so the
# single phase-tensor implementation below has one definition of "degenerate".
PT_MIN_REZ_ROW_SINE = 1e-2


def pt_params(zxxr, zxxi, zxyr, zxyi, zyxr, zyxi, zyyr, zyyi):
    """THE phase-tensor implementation (Caldwell et al. 2004): Phi = Re(Z)^-1 Im(Z).

    Returns (phimin, phimax, azimuth, beta) in degrees, UNROUNDED, or (None,)*4 for a missing or
    near-singular (dead-channel) period. This is the single source of truth shared by the TF builder
    (`_edi_tf.pt_params`, which rounds for the plottable row) and the science layer
    (`_edi_science.pt_per_period`); keep all phase-tensor math here so the convention cannot diverge.
    """
    try:
        if any(v is None for v in (zxxr, zxxi, zxyr, zxyi, zyxr, zyxi, zyyr, zyyi)):
            return (None,) * 4
        det = zxxr * zyyr - zxyr * zyxr
        nr1 = math.hypot(zxxr, zxyr)
        nr2 = math.hypot(zyxr, zyyr)
        if det == 0 or nr1 == 0 or nr2 == 0 or abs(det) < PT_MIN_REZ_ROW_SINE * nr1 * nr2:
            return (None,) * 4
        xi00, xi01, xi10, xi11 = zyyr / det, -zxyr / det, -zyxr / det, zxxr / det
        p11 = xi00 * zxxi + xi01 * zyxi
        p12 = xi00 * zxyi + xi01 * zyyi
        p21 = xi10 * zxxi + xi11 * zyxi
        p22 = xi10 * zxyi + xi11 * zyyi
        pi1 = 0.5 * math.hypot(p11 - p22, p12 + p21)
        pi2 = 0.5 * math.hypot(p11 + p22, p12 - p21)
        phimax = math.degrees(math.atan(pi2 + pi1))
        phimin = math.degrees(math.atan(pi2 - pi1))
        alpha = 0.5 * math.degrees(math.atan2(p12 + p21, p11 - p22))
        beta = 0.5 * math.degrees(math.atan2(p12 - p21, p11 + p22))
        return (phimin, phimax, alpha - beta, beta)
    except (ZeroDivisionError, ValueError, TypeError):
        return (None,) * 4
