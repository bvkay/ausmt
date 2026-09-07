"""Runs the fetch_handoff Node test: the hand-off document builder and the terminal-command composers
(portal/src/exports.js, portal/src/fetchcmd.js) against the shared fixture contract/fetch_handoff.json.
The engine pins its own emitter against the same file in engine/tests/test_entity_pages.py, so the
document a survey page fetches and the one the SPA builds cannot drift. Skips if Node is unavailable
(CI installs Node - see .github/workflows/portal-ci.yml)."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEST_JS = Path(__file__).resolve().parent / "fetch_handoff.test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_fetch_handoff():
    assert TEST_JS.exists(), "fetch_handoff.test.js missing"
    r = subprocess.run(["node", str(TEST_JS)], capture_output=True, text=True, encoding="utf-8",
                       cwd=str(ROOT))
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "ALL PASSED" in out, out
