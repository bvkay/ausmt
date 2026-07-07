"""Real-world dialect robustness, on the mt_metadata engine (slice-#3d).

Three instrument/processing dialects (EDL/BIRRP, LEMI/BIRRP, Phoenix EMpower spectra) must parse and
yield usable Z/rho under the sole mt_metadata engine — including the Phoenix spectra-section dialect
(cross-power SPECTRA, no >FREQ/impedance section) that the retired regex reader needed _spectra for.

Re-baselined 2026-06-16 from the regex reader onto mt_metadata. The Phoenix golden Z values were
always mt_metadata-derived, so they hold unchanged; the old regex-vs-mt_metadata parity test is
removed (it would now compare mt_metadata to itself).
"""
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "extract"))
import _mtm as mtm        # noqa: E402
import _edi_tf as tfmod   # noqa: E402

FIX = HERE / "real_dialects"


def _read(p):
    tf = mtm.read(p)
    r = mtm.record_from_tf(tf, p.name)
    per, comp = mtm.components_from_tf(tf)
    cols = tfmod.tf_from_components(per, comp) if per else [None] * len(tfmod.TF_COLUMNS)
    return r, per, comp, cols


def test_edl_birrp_parses():
    """EDL/BIRRP: indented markers + CRLF + impedance-only. Parses and yields rho from Z."""
    r, _per, _comp, cols = _read(FIX / "edl_birrp_st01.edi")
    assert r["lat"] is not None and r["n_periods"] > 0
    assert r["type"] in {"LPMT", "BBMT", "AMT"}
    assert len([x for x in cols[1] if x is not None]) > 0   # apparent resistivity from impedance


def test_lemi_birrp_parses():
    """LEMI/BIRRP: parses fully under mt_metadata."""
    r, _per, _comp, _cols = _read(FIX / "lemi_birrp_wg.edi")
    assert r["lat"] is not None and r["n_periods"] > 0


# Golden impedances for phoenix_empower_A01.edi (mt_metadata 1.0.9) — lock the spectra-section read.
PHOENIX_GOLDEN = [
    # (period_s, Zxy.re, Zxy.im, Zyx.re, Zyx.im)
    (0.0001,              414.579,  660.9926, -318.6408, -527.6611),
    (0.5818181818181818,   6.8377,    1.1434,   -7.7062,   -1.1171),
    (2912.710720057042,    0.1132,    0.1698,    0.0147,   -0.1077),
]


def test_phoenix_spectra_parses_and_matches_golden():
    """Phoenix EMpower spectra-section EDI: mt_metadata recovers Z (+ tipper) from the cross-power
    SPECTRA — no >FREQ/impedance section — and reproduces the committed golden impedance."""
    p = FIX / "phoenix_empower_A01.edi"
    r, per, comp, _cols = _read(p)
    assert r["lat"] is not None and r["n_periods"] > 0
    assert per and comp.get("ZXYR")
    for T, zxyr, zxyi, zyxr, zyxi in PHOENIX_GOLDEN:
        j = min(range(len(per)), key=lambda i: abs(per[i] - T))
        assert abs(per[j] - T) <= 1e-6 * max(T, 1.0)
        got_xy = complex(comp["ZXYR"][j], comp["ZXYI"][j])
        got_yx = complex(comp["ZYXR"][j], comp["ZYXI"][j])
        assert abs(got_xy - complex(zxyr, zxyi)) <= 0.005 * abs(complex(zxyr, zxyi)) + 1e-3
        assert abs(got_yx - complex(zyxr, zyxi)) <= 0.005 * abs(complex(zyxr, zyxi)) + 1e-3
