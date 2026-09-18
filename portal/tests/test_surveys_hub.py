"""Runs the surveys_hub jsdom test: the surveys hub's controls search, filter and sort the cards in the
page (portal/src/surveys-hub.js over the markup the engine renders), driven against a hub-shaped
fixture that mirrors the engine's ids, names and data attributes. Skips when Node or the jsdom
dev-dependency is unavailable (CI installs both - see .github/workflows/portal-ci.yml)."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEST_JS = Path(__file__).resolve().parent / "surveys_hub.test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_surveys_hub():
    assert TEST_JS.exists(), "surveys_hub.test.js missing"
    r = subprocess.run(["node", str(TEST_JS)], capture_output=True, text=True, encoding="utf-8",
                       cwd=str(ROOT))
    out = r.stdout + r.stderr
    if r.returncode == 2:
        pytest.skip("jsdom dev-dependency not installed (run `npm ci` in portal/)")
    assert r.returncode == 0, out
    assert "ALL PASSED" in out, out
