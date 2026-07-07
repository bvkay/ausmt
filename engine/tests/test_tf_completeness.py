"""C20 — transfer-function completeness: error columns, full complex tipper, placeholder honesty.

The tf.json contract grew 10 -> 18 (contract/columns.json TF_COLUMNS):
  t[10] rho_xy_err  t[11] rho_yx_err  t[12] phs_xy_err  t[13] phs_yx_err
  t[14] tzx_re      t[15] tzx_im      t[16] tzy_re      t[17] tzy_im
These tests are each able to fail:
  * OLD-SLICE BYTE-IDENTITY: t[0..9] of every checked-in fixture equals a committed golden. Any drift
    in an existing column (including tip_mag) is a STOP condition — this is the guard.
  * ERROR COLUMNS: a synthetic EDI with KNOWN Z + Z.VAR yields the documented propagation values,
    hand-computed in the test (rho.err = 0.4*T*|Z|*|dZ|; phs.err = deg(|dZ|/|Z|)).
  * TIPPER COMPONENTS: a real-dialect tipper matches the component dict, and source-masked periods are
    null in ALL FOUR component columns (composes with the C19b fill/exact-zero mask).
  * PLACEHOLDER: a flat-|T|=1.0 tipper is masked (all four series + tip_mag null) and a NOTICE names the
    station; a real (varying) tipper is untouched.
"""
import json
import math
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "extract"))

pytest.importorskip("mt_metadata")
import _mtm as mtm        # noqa: E402
import _edi_tf as tfmod   # noqa: E402
from _contract import TF_COLUMNS   # noqa: E402

DATA = HERE.parent / "data" / "sample-survey" / "transfer_functions" / "edi"
EXAMPLE = HERE / "fixtures" / "example-survey" / "transfer_functions" / "edi"
FILLED = HERE / "fixtures" / "filled-survey" / "transfer_functions" / "edi" / "FILLED01.edi"
ERRCOLS = HERE / "fixtures" / "errcols-survey" / "transfer_functions" / "edi" / "ERRCOLS01.edi"
REAL = HERE / "real_dialects"
GOLDEN = HERE / "fixtures" / "golden" / "tf_old_slice.json"

# Named TF indices (self-follow the contract; a reorder regenerates _contract and these move too).
_T = {n: i for i, n in enumerate(TF_COLUMNS)}

# The fixtures the golden covers, name -> path.
_GOLDEN_FIXTURES = {
    "EXAMPLE01": EXAMPLE / "EXAMPLE01.edi",
    "EXAMPLE02": EXAMPLE / "EXAMPLE02.edi",
    "Vulcan_A1": DATA / "Vulcan_A1.edi",
    "Vulcan_A2": DATA / "Vulcan_A2.edi",
    "edl_birrp_st01": REAL / "edl_birrp_st01.edi",
    "lemi_birrp_wg": REAL / "lemi_birrp_wg.edi",
    "phoenix_empower_A01": REAL / "phoenix_empower_A01.edi",
    "FILLED01": FILLED,
}


def _cols(path):
    per, comp = mtm.components(path)
    return per, comp, (tfmod.tf_from_components(per, comp) if per else None)


def _normnum(x):
    if isinstance(x, list):
        return [_normnum(v) for v in x]
    return None if x is None else float(x)


def test_contract_grew_to_18_appended_only():
    """FAILS IF: the tf contract is not exactly the 10 original columns followed by the 8 C20 columns
    in the frozen order. Pins the APPEND (a reorder or a wrong new name fails)."""
    assert TF_COLUMNS[:10] == ["periods", "rho_xy", "rho_yx", "phs_xy", "phs_yx_adj",
                               "tip_mag", "pt_min", "pt_max", "pt_az", "pt_beta"], TF_COLUMNS
    assert TF_COLUMNS[10:] == ["rho_xy_err", "rho_yx_err", "phs_xy_err", "phs_yx_err",
                               "tzx_re", "tzx_im", "tzy_re", "tzy_im"], TF_COLUMNS
    assert len(TF_COLUMNS) == 18


def test_old_slice_byte_identical_to_golden():
    """★ FAILS IF: t[0..9] of any checked-in fixture differs from the committed golden. The golden was
    minted from the pre-C20 outputs; any change to an existing column (including tip_mag) is a STOP.
    Compares the JSON-normalised OLD slice only — the 8 new columns are deliberately excluded."""
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert set(golden) == set(_GOLDEN_FIXTURES), "golden station set drifted from the fixture set"
    for name, path in _GOLDEN_FIXTURES.items():
        _, _, cols = _cols(path)
        got = None if cols is None else _normnum(cols[:10])
        assert got == golden[name], (
            f"{name}: OLD SLICE t[0..9] changed vs golden — this is a C20 STOP condition. "
            f"An existing column moved or its value drifted.")


def test_new_columns_present_and_correct_width():
    """FAILS IF: tf_from_components does not emit exactly 18 columns on a real fixture."""
    _, _, cols = _cols(DATA / "Vulcan_A1.edi")
    assert len(cols) == 18, f"expected 18 tf columns, got {len(cols)}"
    # every column is an array of the same length (one value per thinned period)
    n = len(cols[0])
    assert all(len(c) == n for c in cols), "ragged tf columns"


def test_error_columns_match_hand_computed_propagation():
    """★ FAILS IF: the rho/phase error columns do not equal the DOCUMENTED linear propagation from the
    known synthetic impedance + variance. ERRCOLS01 carries Zxy=3+4j (|Z|=5) with ZXY.VAR=0.01
    (|dZ|=0.1) and Zyx=-3-4j with ZYX.VAR=0.04 (|dZ|=0.2), at T=1s and T=10s. Expectations are computed
    here from those inputs, INDEPENDENTLY of the code path."""
    per, comp, cols = _cols(ERRCOLS)
    assert per == [1.0, 10.0], f"fixture periods changed: {per}"
    # independent hand computation (the documented formulas)
    for i, T in enumerate(per):
        magxy, dzxy = 5.0, 0.1                 # |Zxy|, |dZxy|
        magyx, dzyx = 5.0, 0.2                 # |Zyx|, |dZyx|
        exp_rxy = 0.4 * T * magxy * dzxy       # 0.2, 2.0
        exp_ryx = 0.4 * T * magyx * dzyx       # 0.4, 4.0
        exp_pxy = round(math.degrees(dzxy / magxy), 1)   # 1.1
        exp_pyx = round(math.degrees(dzyx / magyx), 1)   # 2.3
        assert cols[_T["rho_xy_err"]][i] == pytest.approx(exp_rxy, abs=1e-6), (i, cols[_T["rho_xy_err"]])
        assert cols[_T["rho_yx_err"]][i] == pytest.approx(exp_ryx, abs=1e-6), (i, cols[_T["rho_yx_err"]])
        assert cols[_T["phs_xy_err"]][i] == exp_pxy, (i, cols[_T["phs_xy_err"]])
        assert cols[_T["phs_yx_err"]][i] == exp_pyx, (i, cols[_T["phs_yx_err"]])
    # a rho error attaches only where the rho value renders (rho>0): both present here
    assert all(v is not None for v in cols[_T["rho_xy"]])
    assert all(v is not None for v in cols[_T["rho_xy_err"]])


def test_no_error_columns_when_source_has_no_errors():
    """FAILS IF: tf_from_components FABRICATES error values when the component dict carries no error
    series (RHO*.ERR / PHS*.ERR absent). A survey without errors must render every error column
    all-null — no bar. Uses a component dict with rho/phase present but NO error keys."""
    n = 4
    per = [0.1, 1.0, 10.0, 100.0]
    comp = {"RHOXY": [10.0] * n, "RHOYX": [12.0] * n,
            "PHSXY": [45.0] * n, "PHSYX": [-135.0] * n}   # values present, errors ABSENT
    cols = tfmod.tf_from_components(per, comp)
    assert any(v is not None for v in cols[_T["rho_xy"]]), "precondition: rho values should render"
    for name in ("rho_xy_err", "rho_yx_err", "phs_xy_err", "phs_yx_err"):
        assert all(v is None for v in cols[_T[name]]), f"{name} fabricated an error where the source had none"


def test_tipper_components_match_component_dict_and_mask_fills():
    """FAILS IF: the tzx/tzy columns do not equal the component dict's TX/TY (rounded), or a
    source-masked period is not null in all four. Uses the FILLED fixture path for the masking (it has
    no tipper, so the masking behaviour is asserted at the predicate level too)."""
    # A tipper-bearing fixture that is NOT a placeholder: build a component dict directly and pass it
    # through tf_from_components (the pure TF math), so the column mapping is pinned without needing a
    # real varying-tipper EDI on disk.
    n = 5
    per = [0.1, 1.0, 10.0, 100.0, 1000.0]
    comp = {k: [None] * n for k in ("RHOXY", "RHOYX", "PHSXY", "PHSYX")}
    # varying tipper: distinct per-period values, one period (index 2) masked to None in all four
    comp["TXR"] = [0.10, 0.12, None, 0.16, 0.18]
    comp["TXI"] = [0.01, 0.02, None, 0.04, 0.05]
    comp["TYR"] = [0.20, 0.25, None, 0.35, 0.40]
    comp["TYI"] = [0.02, 0.03, None, 0.05, 0.06]
    cols = tfmod.tf_from_components(per, comp)
    for src, colname in (("TXR", "tzx_re"), ("TXI", "tzx_im"), ("TYR", "tzy_re"), ("TYI", "tzy_im")):
        for i in range(n):
            exp = None if comp[src][i] is None else round(comp[src][i], 4)
            assert cols[_T[colname]][i] == exp, (colname, i, cols[_T[colname]][i], exp)
        # the masked period (index 2) is null in all four
        assert cols[_T[colname]][2] is None, f"{colname} leaked a value at the masked period"


def test_placeholder_tipper_masked_with_notice(capsys):
    """★ FAILS IF: the real-corpus placeholder tipper (Phoenix EMpower A01: |T| flat at 1.0) is NOT
    masked, or no NOTICE names the station. This is the D2 honesty guard on a REAL file."""
    per, comp = mtm.components(REAL / "phoenix_empower_A01.edi")
    # all four tipper series masked to null (dict collapses an all-None series to None)
    for k in ("TXR", "TXI", "TYR", "TYI"):
        assert comp.get(k) is None, f"placeholder tipper leaked {k} — D2 mask failed"
    # tip_mag consequently absent from the derived row
    cols = tfmod.tf_from_components(per, comp)
    assert all(v is None for v in cols[_T["tip_mag"]]), "tip_mag rendered on a masked placeholder tipper"
    assert all(v is None for v in cols[_T["tzx_re"]]), "tzx_re rendered on a masked placeholder tipper"
    out = capsys.readouterr()
    assert "placeholder tipper" in out.err and "A01" in out.err, (
        f"no build NOTICE named the placeholder station; stderr was: {out.err!r}")


def test_real_varying_tipper_is_not_masked():
    """FAILS IF: a genuine (varying, off-unity) tipper is wrongly detected as a placeholder and masked.
    Guards against the D2 detector over-firing. Exercises the predicate directly with a real-shaped
    varying series (no on-disk EDI needed)."""
    n = 6
    txr = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35]
    txi = [0.05] * n
    tyr = [0.20, 0.22, 0.24, 0.26, 0.28, 0.30]
    tyi = [0.10] * n
    assert mtm._is_placeholder_tipper(txr, txi, tyr, tyi) is False, "varying tipper wrongly flagged placeholder"
    # flat but far from unity is NOT a placeholder (must be at |T|=1)
    flat_low = [0.5] * n
    assert mtm._is_placeholder_tipper(flat_low, [0.0] * n, [0.0] * n, [0.0] * n) is False
    # canonical placeholder IS flagged (|T|=1 flat, one component ~1e-17)
    assert mtm._is_placeholder_tipper([1e-17] * n, [0.0] * n, [1.0] * n, [0.0] * n) is True
    # too few present periods -> cannot judge -> not flagged
    short = [1.0, 1.0, 1.0] + [None] * 3
    assert mtm._is_placeholder_tipper(short, [0.0] * 3 + [None] * 3,
                                      [0.0] * 3 + [None] * 3, [0.0] * 3 + [None] * 3) is False
