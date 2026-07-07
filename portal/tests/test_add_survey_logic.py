"""Runs the add-survey.html pure-logic node test (parseEdi DMS-sign-bug detection, the
station-locations confirmation gate, and buildSurveyYaml coordinate_resolution + region).
Skips if Node is unavailable; CI installs Node (see .github/workflows/portal-ci.yml)."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEST_JS = Path(__file__).resolve().parent / "add_survey_logic.test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_add_survey_logic():
    assert TEST_JS.exists(), "add_survey_logic.test.js missing"
    r = subprocess.run(["node", str(TEST_JS)], capture_output=True, text=True, cwd=str(ROOT))
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "ALL PASSED" in out, out
