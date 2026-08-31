"""Runs the display_grammar Node test: portal/src/state.js's fmtPeriod / fmtRange / licHuman against
the SAME worked examples the engine suite pins engine/extract/_pages.py's _fmt_period / _range /
_fmt_licence against (engine/tests/test_entity_pages.py, the B9 R1/R2/R3 block). Both sides carry the
pairs as literals, so neither can be made green by editing the other's source of truth. Skips if Node
is unavailable (CI installs Node - see .github/workflows/portal-ci.yml)."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEST_JS = Path(__file__).resolve().parent / "display_grammar.test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_display_grammar_parity():
    assert TEST_JS.exists(), "display_grammar.test.js missing"
    r = subprocess.run(["node", str(TEST_JS)], capture_output=True, text=True,
                       encoding="utf-8", cwd=str(ROOT))
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "ALL PASSED" in out, out
