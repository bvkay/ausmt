"""The per-station diagnostic key reports the MEDIAN of |beta| (st.median in _edi_science.py),
not the mean. The emitted key name must say so: skew_beta_median_deg, never the historical
skew_beta_mean_deg.

NON-VACUOUS failure criterion: this test FAILS against the pre-rename tree, because the build
emitted "skew_beta_mean_deg" in both station.json and dimensionality.json.

2026-08-14: station.json stopped RESTATING the dimensionality call and its skew statistic, because
the copy beside it travelled without the "screening diagnostic, not an interpretation product"
caveat that qualifies them.

2026-08-23 (D1, the station promotion): the call is FOLDED BACK IN, and the caveat and the method
string come with it, so the qualification travels with the numbers rather than sitting one file
away. The sidecar keeps being written byte-unchanged through 1.x (D14) because deleting a served
file is a deprecation, not a refactor. So the two surfaces now state the same thing, and the pin
that used to forbid the restatement forbids DISAGREEMENT instead: both carry the honest median key,
neither carries the misleading mean key, and every member the fold covers is equal on both. A
withheld station has no dimensionality.json and no diagnostics block at all, which is what keeps
the interpretation product out of a withheld record (pinned in test_access_gate.py).
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SURVEYS = ROOT / "data"          # data/sample-survey: CC-BY-4.0, access.level=open => products emitted

# The members station.json's `diagnostics` and dimensionality.json must state identically (D1). The
# sidecar's own `screening_diagnostic` flag is not folded: the caveat text carries that meaning.
FOLDED = ("classification", "skew_beta_median_deg", "pct_periods_3d", "method", "note")


def _build_products(tmp_path):
    """Run the real pipeline with --products so the per-station station.json/dimensionality.json
    (the curator products tree) are written, then return the products dir."""
    staged = tmp_path / "surveys_src"
    shutil.copytree(SURVEYS, staged)
    out = tmp_path / "data"
    prod = tmp_path / "products"
    r = subprocess.run([sys.executable, "-m", "extract.build_portal", "--surveys", str(staged),
                        "--out", str(out), "--products", str(prod), "--no-validate"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return prod


def test_skew_beta_key_is_median_not_mean(tmp_path):
    pytest.importorskip("mt_metadata")
    prod = _build_products(tmp_path)

    stations = list(prod.rglob("station.json"))
    dims = list(prod.rglob("dimensionality.json"))
    assert stations, "expected per-station station.json products to be written"
    assert dims, "expected per-station dimensionality.json products to be written"

    for sj in stations:
        diag = json.loads(sj.read_text(encoding="utf-8"))["diagnostics"]
        assert "skew_beta_mean_deg" not in diag, f"{sj}: stale 'mean' key must not be emitted"
        assert "skew_beta_median_deg" in diag, f"{sj}: honest median key missing from the fold"

    for dj in dims:
        doc = json.loads(dj.read_text(encoding="utf-8"))
        assert "skew_beta_median_deg" in doc, f"{dj}: honest median key missing"
        assert "skew_beta_mean_deg" not in doc, f"{dj}: stale 'mean' key must not be emitted"


def test_the_fold_and_the_sidecar_state_the_same_call(tmp_path):
    """D1/D14: one computation, two surfaces, no drift. FAILS against a fold that recomputed the call
    for station.json, and against a sidecar left behind by a later change to the fold."""
    pytest.importorskip("mt_metadata")
    prod = _build_products(tmp_path)
    dims = list(prod.rglob("dimensionality.json"))
    assert dims, "expected per-station dimensionality.json products to be written"
    for dj in dims:
        sidecar = json.loads(dj.read_text(encoding="utf-8"))
        diag = json.loads((dj.parent / "station.json").read_text(encoding="utf-8"))["diagnostics"]
        disagree = {k: (diag.get(k), sidecar.get(k)) for k in FOLDED if diag.get(k) != sidecar.get(k)}
        assert not disagree, f"{dj.parent.name}: the fold and the sidecar disagree: {disagree}"
        assert sidecar["note"] == "screening diagnostic, not an interpretation product"
        assert diag["method"] == "phase-tensor (Caldwell 2004)"
