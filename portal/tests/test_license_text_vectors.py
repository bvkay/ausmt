"""Runs the license_text_vectors Node test: portal/src/exports.js licenseInstrumentText vs the shared
engine vector file (engine/tests/fixtures/license_instrument_vectors.json). The engine side pins the
Python leaf against the same file (engine/tests/test_license_instrument_vectors.py), so the two mirrors
cannot drift. Skips if Node is unavailable (CI installs Node — see .github/workflows/portal-ci.yml)."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEST_JS = Path(__file__).resolve().parent / "license_text_vectors.test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_license_text_vectors():
    assert TEST_JS.exists(), "license_text_vectors.test.js missing"
    r = subprocess.run(["node", str(TEST_JS)], capture_output=True, text=True, cwd=str(ROOT))
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "ALL PASSED" in out, out
