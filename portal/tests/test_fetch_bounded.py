"""The bulk-zip fetcher's pins, via its node driver (the packaged-yaml driver pattern)."""
import shutil
import subprocess
from pathlib import Path

import pytest

PORTAL = Path(__file__).resolve().parents[1]


def test_fetch_bounded_driver():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available on this host")
    r = subprocess.run([node, str(PORTAL / "tools" / "fetch_bounded_test.js")],
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FETCH-BOUNDED PASSED" in r.stdout
