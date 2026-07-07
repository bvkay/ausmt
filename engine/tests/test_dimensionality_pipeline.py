"""Unit tests for the SHIPPING dimensionality classifier — `_edi_science.science_from_components`,
which the build pipeline actually runs. These lock the robustness fixes on the live path: the
near-singular Re(Z) guard, the |beta| physical cap, median aggregation, and the
'<50% usable periods -> indeterminate' rule.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "extract"))
import _ediparse as ep   # noqa: E402
import _edi_science as sci   # noqa: E402

DIM = 5   # index of the dimensionality label in the sci row


def _comp(zlist):
    comp = {k: None for k in ep.COMPONENT_KEYS}
    for key in ("ZXXR", "ZXXI", "ZXYR", "ZXYI", "ZYXR", "ZYXI", "ZYYR", "ZYYI"):
        comp[key] = []
    for zxx, zxy, zyx, zyy in zlist:
        comp["ZXXR"].append(zxx.real); comp["ZXXI"].append(zxx.imag)
        comp["ZXYR"].append(zxy.real); comp["ZXYI"].append(zxy.imag)
        comp["ZYXR"].append(zyx.real); comp["ZYXI"].append(zyx.imag)
        comp["ZYYR"].append(zyy.real); comp["ZYYI"].append(zyy.imag)
    return comp


def _dim(zlist):
    n = len(zlist)
    periods = [10.0 ** (i - n / 2) for i in range(n)]
    return sci.science_from_components(periods, _comp(zlist), None)[DIM]


def test_antisymmetric_is_1d():
    """Anti-symmetric Z with zero diagonal -> phase tensor = identity -> beta=0, ellipticity=0 -> 1-D."""
    z = [(0 + 0j, 10 + 10j, -10 - 10j, 0 + 0j)] * 10
    assert _dim(z) == "1-D"


def test_dead_channel_is_indeterminate():
    """A dead polarisation (Zyx ~ 0) makes Re(Z) rows near-collinear, so the near-singular guard
    fires on every period -> <50% usable -> 'indeterminate', NOT a confident '3-D' off saturated
    skew. This is the exact failure mode the stress test surfaced on real data (WA-MT MBN09)."""
    z = [(0.01 + 0j, 10 + 5j, 1e-6 + 1e-6j, 3 + 3j)] * 10
    assert _dim(z) == "indeterminate"


def test_empty_periods_no_dim():
    """No periods -> no dimensionality, no crash."""
    assert sci.science_from_components([], {}, None)[DIM] is None


def test_provenance_params_match_science_source_of_truth():
    """build_provenance.json must report the dimensionality thresholds the science ACTUALLY used.
    _build_prov reads them from the single source of truth (_edi_science constants +
    _ediparse.PT_MIN_REZ_ROW_SINE) rather than re-typing literals. This test FAILS if anyone
    re-hardcodes a provenance value so it can drift from the thresholds science_from_components
    applies (the exact provenance-fidelity hazard the consolidation removed)."""
    import build_portal as bp   # noqa: PLC0415
    dim = bp._build_prov("mt_metadata")["parameters"]["dimensionality"]
    assert dim["beta_per_period_deg"] == sci.BETA_PER_PERIOD_DEG
    assert dim["skew_3d_deg"] == sci.SKEW_3D_DEG
    assert dim["pct_periods_3d_threshold"] == sci.PCT_PERIODS_3D_THRESHOLD
    assert dim["ellip_2d_deg"] == sci.ELLIP_2D_DEG
    assert dim["beta_physical_cap_deg"] == sci.BETA_PHYSICAL_CAP_DEG
    assert dim["min_usable_period_frac"] == sci.MIN_USABLE_PERIOD_FRAC
    assert dim["skew_aggregation"] == sci.SKEW_AGGREGATION
    assert dim["min_rez_row_sine"] == ep.PT_MIN_REZ_ROW_SINE
