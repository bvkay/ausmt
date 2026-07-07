"""MTH5 ingestion round-trip (Prototype 14, Priority 2).

Evidence that AusMT can ingest MTH5 and produce the same products as the EDI path:
EDI -> MTH5 -> products must match EDI -> products. Skips cleanly if mth5 is not installed.
"""
import math
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "extract"))
DATA = HERE.parent / "data" / "sample-survey" / "transfer_functions" / "edi"

pytest.importorskip("mth5", reason="mth5 not installed")
pytest.importorskip("mt_metadata", reason="mt_metadata not installed")
import _edi_tf as tfmod          # noqa: E402
import _edi_science as sci       # noqa: E402
import _mtm as mtm               # noqa: E402
import _mth5 as m5               # noqa: E402


def _rms(a, b):
    pairs = [(x, y) for x, y in zip(a or [], b or []) if x is not None and y is not None]
    return math.sqrt(sum((x - y) ** 2 for x, y in pairs) / len(pairs)) if pairs else 0.0


def test_edi_to_mth5_roundtrip_matches_edi_products():
    edis = sorted(DATA.glob("Vulcan_*.edi"))
    assert edis, "sample EDIs present"
    with tempfile.TemporaryDirectory() as td:
        h5 = Path(td) / "rt.h5"
        nw = m5.build_mth5_from_edis(edis, h5)
        assert nw == len(edis)
        mth5_by_station = {r["id"]: (r, p, c) for r, p, c in m5.records_and_components(h5)}

    for p in edis:
        er = mtm.parse_edi(p)
        assert er["id"] in mth5_by_station, f"{er['id']} round-tripped through MTH5"
        mr, mp, mc = mth5_by_station[er["id"]]
        # metadata preserved
        assert er["n_periods"] == mr["n_periods"]
        assert er["type"] == mr["type"]
        assert er["components"] == mr["components"]
        assert abs(er["lat"] - mr["lat"]) < 1e-4 and abs(er["lon"] - mr["lon"]) < 1e-4
        # products identical through the shared science
        ep, ec = mtm.components(p)
        et = tfmod.tf_from_components(ep, ec)
        mt = tfmod.tf_from_components(mp, mc)
        assert _rms(et[1], mt[1]) < 1e-3      # rho_xy
        assert _rms(et[3], mt[3]) < 1e-3      # phase_xy
        es = sci.science_from_components(ep, ec, mtm.proc_info(p))
        ms = sci.science_from_components(mp, mc, None)
        assert es[5] == ms[5]                 # dimensionality label
