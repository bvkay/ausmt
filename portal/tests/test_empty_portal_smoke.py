"""Empty-portal smoke: the static portal must boot cleanly against the empty (clean-template) data and
render its empty state — no spinner, blank map, NaN, or JS error. Runs the committed headless harness
(tools/smoke.js) with Node against the repo's own data/ directory. Skips if Node is unavailable (the
harness is JS); CI installs Node so it runs there."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SMOKE = ROOT / "tools" / "smoke.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_empty_portal_smoke():
    assert SMOKE.exists(), "tools/smoke.js missing"
    r = subprocess.run(["node", str(SMOKE), str(ROOT / "data")],
                       capture_output=True, text=True, cwd=str(ROOT))
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "SMOKE PASSED" in out, out
    assert "EMPTY portal" in out, "expected empty-state boot on the clean-template data:\n" + out
