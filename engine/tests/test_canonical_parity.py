"""Slice-#3 parity gate: routing the portal products through the canonical EMTF XML store must
preserve the SCIENCE. For each fixture we derive the portal products (tf.json row + sci.json row,
via the shared _edi_tf / _edi_science math) two ways and compare:

  A. from the ORIGINAL EDI (mt_metadata)                  — today's `--extractor mt_metadata` path
  B. from the NORMALIZED canonical EMTF XML (mt_metadata)  — the Phase-1 D6 path

If A == B, routing the build through the canonical store is science-preserving — the safety property
that underwrote the regex retirement and that guards the Phase-1 D6 canonical store.

KNOWN, DOCUMENTED edge case (not a science issue): where a tipper is MISSING, the EDI carries a
placeholder (tip_mag 1.0) while EMTF XML uses its large missing-data fill (~1e32). Neither is a real
measurement, so non-physical cells (|v| > 1e8) are excluded from the tf comparison. The integration
that routes tf.json through the canonical store must null these fills (slice-#3 follow-up).

Requires the core mt_metadata/mth5 engine; importorskips otherwise; runs in the build CI job's suite.
"""
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")
pytest.importorskip("mth5")

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "extract"))
sys.path.insert(0, str(REPO))

import _mtm as mtm            # noqa: E402
import _edi_tf as tfmod       # noqa: E402
import _edi_science as scimod  # noqa: E402
from ausmt_science.ingest.normalize import normalize  # noqa: E402

FIXTURES = [
    ("vulcan", REPO / "data" / "sample-survey" / "transfer_functions" / "edi" / "Vulcan_A1.edi"),
    ("jupiter", HERE / "real_dialects" / "phoenix_empower_A01.edi"),
]
NONPHYSICAL = 1e8   # |value| above this is a missing-data fill, not a measurement


def _products(tf):
    periods, comp = mtm.components_from_tf(tf)
    t = tfmod.tf_from_components(periods, comp)
    s = scimod.science_from_components(periods, comp, mtm.proc_info_from_tf(tf))
    return t, s


@pytest.mark.parametrize("survey,edi", FIXTURES)
def test_canonical_xml_preserves_science(tmp_path, survey, edi):
    assert edi.exists(), edi
    t_edi, s_edi = _products(mtm.read(edi))
    res = normalize(edi, tmp_path, survey_id=survey)
    t_xml, s_xml = _products(mtm.read(res.canonical_xml))

    # --- tf.json: every cell must match in presence AND value. Only tip_mag (col 5) tolerates a
    # missing-data representation difference: where a tipper is absent the EDI carries a placeholder
    # (|T| 1.0) while EMTF XML uses its ~1e32 fill (now nulled by _mtm._is_missing) — not science.
    TIP_MAG = 5
    compared = skipped = 0
    for ci, (col_a, col_b) in enumerate(zip(t_edi, t_xml)):
        if col_a is None and col_b is None:
            continue
        assert (col_a is None) == (col_b is None), f"tf col {ci} None-mismatch"
        for av, bv in zip(col_a, col_b):
            if av is None and bv is None:
                continue
            if ci == TIP_MAG and (av is None or bv is None
                                  or (av is not None and abs(float(av)) > NONPHYSICAL)
                                  or (bv is not None and abs(float(bv)) > NONPHYSICAL)):
                skipped += 1
                continue
            assert (av is None) == (bv is None), f"tf col {ci}: presence mismatch {av} vs {bv}"
            compared += 1
            assert np.allclose(float(av), float(bv), rtol=1e-3, atol=1e-6), f"tf col {ci}: {av} != {bv}"
    assert compared > 0, "vacuous tf comparison"

    # --- sci.json: dimensionality + the numeric science fields must be identical ---
    assert s_edi[5] == s_xml[5], f"dimensionality drift: {s_edi[5]} vs {s_xml[5]}"
    for i in (0, 6, 8, 9, 10, 11):   # q, p3d, ellip, skew, mre, decades
        a, b = s_edi[i], s_xml[i]
        if a is None and b is None:
            continue
        assert np.allclose(np.nan if a is None else float(a),
                           np.nan if b is None else float(b),
                           rtol=1e-3, atol=1e-6, equal_nan=True), f"sci[{i}] {a} != {b}"
