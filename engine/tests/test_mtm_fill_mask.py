"""C19b: masked source periods must be GAPS in the tf series, never zeros.

Production incident (TAS120, auslamp-tas, 2026-07-07): the EDI masks 10 of 24 periods with the
1.0E+32 missing-data sentinel. mt_metadata converts those fills to EXACT ZEROS on read, which sail
past _mtm._is_missing's magnitude threshold (>1e8) — so the portal plotted phase=0deg points, rho=0
points and tipper zero-dips at every masked period ("almost like some parts are masked" — they ARE,
and we painted them as data at zero). An estimated Z/T element is never exactly 0+0j, so exact
complex zero is treated as missing. Single-component zeros (e.g. a tiny tipper with TYI crossing
0.0 while TYR is finite) remain VALID — only both-parts-exactly-zero is masked.

The fixture FILLED01.edi is EXAMPLE01 with 1.0E+32 injected into the first TWO values of
ZXYR/ZXYI/ZYXR/ZYXI — the exact shape TAS120 has in production (leading masked band).
"""
import math
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "extract"))

mtm = pytest.importorskip("_mtm")
pytest.importorskip("mt_metadata")

FILLED = HERE / "fixtures" / "filled-survey" / "transfer_functions" / "edi" / "FILLED01.edi"


def test_zero_filled_periods_are_gaps_not_zeros():
    """FAILS IF: a source-masked (1e32 -> mt_metadata zero) period appears in the derived series as
    a 0.0 data point instead of None. This is the TAS120 leak, reproduced end-to-end through the
    same mt_metadata read path production uses."""
    periods, comp = mtm.components(FILLED)
    assert periods and comp, "fixture must parse"
    for key in ("RHOXY", "PHSXY", "RHOYX", "PHSYX", "ZXYR", "ZYXR"):
        series = comp.get(key)
        assert series is not None, f"{key} missing entirely — fixture shape changed?"
        assert series[0] is None and series[1] is None, (
            f"{key}[0:2] are source-MASKED periods and must be None (a gap); got "
            f"{series[0]!r}, {series[1]!r} — the zero-fill leak (C19b) is back.")
        # the rest of the band is real data and must survive the masking untouched
        present = [v for v in series[2:] if v is not None]
        assert present, f"{key}: masking wiped real data — over-masking"
        assert all(v != 0.0 for v in present), f"{key}: unexpected exact zero in real data"


def test_is_missing_predicate_exact_zero_vs_component_zero():
    """FAILS IF: exact 0+0j is accepted as data, or a legitimate single-component zero is masked.
    The predicate is shared by the impedance AND tipper paths, so this pins the tipper behaviour
    the fixture (which has no T blocks) cannot exercise end-to-end."""
    assert mtm._is_missing(complex(0.0, 0.0)) is True, "exact complex zero must read as MISSING"
    assert mtm._is_missing(complex(1e32, 0.0)) is True
    assert mtm._is_missing(complex(0.0, 1e32)) is True
    assert mtm._is_missing(complex(float("nan"), 0.1)) is True
    assert mtm._is_missing(complex(0.0, 0.3)) is False, "single-component zero is VALID data"
    assert mtm._is_missing(complex(-0.05, 0.0)) is False, "single-component zero is VALID data"
    assert mtm._is_missing(complex(-2.1, 1.7)) is False
    assert mtm._is_missing(None) is True


def test_phase_never_pinned_at_exact_zero_degrees():
    """FAILS IF: any derived phase value is exactly 0.0 degrees on the filled fixture — the visual
    signature of the leak (atan2(0,0) == 0). Real phases are never exactly 0.0 to double precision
    on estimated data."""
    _, comp = mtm.components(FILLED)
    for key in ("PHSXY", "PHSYX"):
        vals = [v for v in (comp.get(key) or []) if v is not None]
        assert vals, f"{key} empty"
        assert all(not math.isclose(v, 0.0, abs_tol=1e-12) for v in vals), (
            f"{key} carries an exact-zero phase point — masked period leaking as data")
