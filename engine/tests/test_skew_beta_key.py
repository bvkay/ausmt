"""The per-station diagnostic key reports the MEDIAN of |beta| (st.median in _edi_science.py),
not the mean. The emitted key name must say so: skew_beta_median_deg, never the historical
skew_beta_mean_deg.

NON-VACUOUS failure criterion: this test FAILS against the pre-rename tree, because the build
emitted "skew_beta_mean_deg" in both station.json and dimensionality.json. It asserts the honest
key is present AND the misleading key is absent in the products actually written to disk.
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


def _build_products(tmp_path):
    """Run the real pipeline with --products so the per-station station.json/dimensionality.json
    (the curator products tree) are written, then return the products dir."""
    staged = tmp_path / "surveys_src"
    shutil.copytree(SURVEYS, staged)
    out = tmp_path / "data"
    prod = tmp_path / "products"
    r = subprocess.run([sys.executable, "-m", "extract.build_portal", "--surveys", str(staged),
                        "--out", str(out), "--products", str(prod), "--no-validate"],
                       cwd=str(ROOT), capture_output=True, text=True)
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
        assert "skew_beta_median_deg" in diag, f"{sj}: honest median key missing"
        assert "skew_beta_mean_deg" not in diag, f"{sj}: stale 'mean' key must not be emitted"

    for dj in dims:
        doc = json.loads(dj.read_text(encoding="utf-8"))
        assert "skew_beta_median_deg" in doc, f"{dj}: honest median key missing"
        assert "skew_beta_mean_deg" not in doc, f"{dj}: stale 'mean' key must not be emitted"
