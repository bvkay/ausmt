"""Runs the C13 add-survey direct-upload interaction driver (tools/add_survey_submit_test.js): the
healthz-probe UI gate, the in-flight double-submit guard, the escaped 201 status link, the XSS-inert
handling of a hostile 400 detail / status_url, the fail-fast empty-key + bad-ORCID gates, and the
design §5 CENTREPIECE — the submit key travels ONLY in the X-AusMT-Submit-Key header (absent from the
zip bytes, every track() payload, the DOM, and every URL).

Needs jsdom (a dev-only dependency; CI restores it with `npm ci` in portal/, see portal-ci.yml). The
driver exits 2 when jsdom is unavailable, which this wrapper turns into a SKIP — matching
test_add_survey_logic.py / test_interactions.py. Skips too if Node itself is absent."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent                       # portal/
DRIVER = ROOT / "tools" / "add_survey_submit_test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_add_survey_submit_flow():
    assert DRIVER.exists(), "add_survey_submit_test.js missing"
    r = subprocess.run(["node", str(DRIVER)], capture_output=True, text=True, cwd=str(ROOT))
    out = r.stdout + r.stderr
    if r.returncode == 2:
        pytest.skip("jsdom dev-dependency not installed (run `npm ci` in portal/)")
    assert r.returncode == 0, out
    assert "SUBMIT-TEST PASSED" in out, out
