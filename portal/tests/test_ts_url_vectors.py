"""Runs the ts_url_vectors Node test: portal/src/data.js tsArchiveUrl against the shared engine
vector file (engine/tests/fixtures/ts_url_vectors.json). The engine side pins its own encoder
(_stationcheck.ts_access_url) against the same file in engine/tests/test_ts_url_vectors.py, and the
deploy generator's arm is in deploy/tests/test_frontdoor_ts_routes.py, so the three renderings of a
hand-off address cannot drift. Skips if Node is unavailable (CI installs Node - see
.github/workflows/portal-ci.yml)."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEST_JS = Path(__file__).resolve().parent / "ts_url_vectors.test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_ts_url_vectors():
    assert TEST_JS.exists(), "ts_url_vectors.test.js missing"
    r = subprocess.run(["node", str(TEST_JS)], capture_output=True, text=True, encoding="utf-8",
                       cwd=str(ROOT))
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "ALL PASSED" in out, out
