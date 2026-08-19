"""Runs the shared DOI citation-harvest core node test (src/doi_harvest.js - the single source reused by
the public Add Survey form and the curator metadata editor, CONTRIBUTOR-CREDIT-SPEC §6). Skips if Node is
unavailable; CI installs Node (see .github/workflows/portal-ci.yml)."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEST_JS = Path(__file__).resolve().parent / "doi_harvest.test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_doi_harvest():
    assert TEST_JS.exists(), "doi_harvest.test.js missing"
    r = subprocess.run(["node", str(TEST_JS)], capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT))
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "ALL PASSED" in out, out
