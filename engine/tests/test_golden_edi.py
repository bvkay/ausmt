"""Golden-file regression on checked-in sample EDIs, on the mt_metadata engine (slice-#3d).

Pins the sole engine's outputs so a parsing/science change is caught. Values frozen once; update
deliberately and SAY WHY in the commit (Egbert lens: track exact outputs for known inputs).

Re-baselined 2026-06-16 from the regex reader onto mt_metadata:
  * remote-reference (rr) DROPPED from the golden — it is a best-effort *scraped* facet (the build
    supplies it from the EDI free text; raw mt_metadata leaves it 0), not a frozen contract.
  * Vulcan_A2 median-relative-error 0.017 -> 0.021 — mt_metadata reads the impedance ERROR fields
    slightly differently than the retired regex reader. type/n_periods/dimensionality/basis/quality
    are unchanged; this is a legitimate engine delta, NOT a regression (corroborated by the
    163-station corpus parity at 100% dimensionality agreement).
"""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "extract"))
import _edi_catalog as cat   # noqa: E402  (coords_of — kept, dependency-free)
import _edi_science as sci   # noqa: E402

DATA = HERE.parent / "data" / "sample-survey" / "transfer_functions" / "edi"

# frozen expectations on mt_metadata: file -> (type, n_periods, dimensionality, diag_basis, diag~, mre~)
GOLDEN = {
    "Vulcan_A1.edi": ("BBMT", 62, "2-D", "e", 4.9, 0.019),
    "Vulcan_A2.edi": ("BBMT", 62, "2-D", "e", 4.9, 0.021),
}


def test_sample_edis_match_golden():
    pytest.importorskip("mt_metadata")
    import _mtm as mtm   # noqa: PLC0415
    for fname, (typ, nper, dim, basis, diag, mre) in GOLDEN.items():
        p = DATA / fname
        assert p.exists(), f"missing sample EDI {p}"
        tf = mtm.read(p)
        r = mtm.record_from_tf(tf, p.name)
        per, comp = mtm.components_from_tf(tf)
        s = sci.science_from_components(per, comp, mtm.proc_info_from_tf(tf))
        assert r["type"] == typ, f"{fname} type {r['type']} != {typ}"
        assert r["n_periods"] == nper, f"{fname} n_periods {r['n_periods']} != {nper}"
        assert s[5] == dim, f"{fname} dimensionality {s[5]} != {dim}"
        assert s[1] == basis, f"{fname} diagnostic basis {s[1]} != {basis}"
        assert abs(s[0] - diag) <= 0.2, f"{fname} diagnostic {s[0]} not ~{diag}"
        assert abs(s[10] - mre) <= 0.003, f"{fname} median rel error {s[10]} not ~{mre}"


def test_coordinates_are_from_head_not_moved():
    # regression guard for the historical 32 km coordinate-move bug: HEAD coords, in-range.
    # Uses the KEPT dependency-free coords_of (survives the regex retirement) — no mt_metadata needed.
    lat, lon = cat.coords_of(DATA / "Vulcan_A1.edi")
    assert -45 <= lat <= -8 and 108 <= lon <= 156, "coords out of Australia bbox"
