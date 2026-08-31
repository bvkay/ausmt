"""Runs the collection_colours Node test: portal/src/state.js's memberColours against the engine's
_member_colours rule (engine/extract/_pages.py), which decides what colour each member survey gets in a
collection footprint. The static collection page and the SPA draw the same collection, so a survey that
is teal on one must be teal on the other; past the shared eight-entry palette both lay the same evenly
spaced hue ramp rather than cycling. Skips if Node is unavailable (CI installs Node - see
.github/workflows/portal-ci.yml)."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEST_JS = Path(__file__).resolve().parent / "collection_colours.test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_collection_colour_parity():
    assert TEST_JS.exists(), "collection_colours.test.js missing"
    r = subprocess.run(["node", str(TEST_JS)], capture_output=True, text=True,
                       encoding="utf-8", cwd=str(ROOT))
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "ALL PASSED" in out, out
