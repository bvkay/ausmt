"""Runs the page_fetch jsdom test: the survey page's "Build a download script" link opens the terminal
dialog in the page (portal/src/page-fetch.js over fetchcmd.js and fetchdialog.js), driven against the
SPA's own dialog markup and the shared fixture contract/fetch_handoff.json. Skips when Node or the
jsdom dev-dependency is unavailable (CI installs both - see .github/workflows/portal-ci.yml)."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEST_JS = Path(__file__).resolve().parent / "page_fetch.test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_page_fetch():
    assert TEST_JS.exists(), "page_fetch.test.js missing"
    r = subprocess.run(["node", str(TEST_JS)], capture_output=True, text=True, encoding="utf-8",
                       cwd=str(ROOT))
    out = r.stdout + r.stderr
    if r.returncode == 2:
        pytest.skip("jsdom dev-dependency not installed (run `npm ci` in portal/)")
    assert r.returncode == 0, out
    assert "ALL PASSED" in out, out
