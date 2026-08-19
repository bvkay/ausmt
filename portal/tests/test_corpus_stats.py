"""About header corpus-totals block, behavioural pin (Invariant 10).

api-docs lane. The About page's header right zone now carries the mono stats block that used to be
index-only, stating CORPUS totals ("N stations · N surveys") rather than index's live map state. The
numbers are read from the served catalogue at load time, so the block has exactly one way to be wrong:
showing something when it does not actually know. tools/corpus_stats_test.js drives the REAL
corpus-stats.js against the REAL about.html in jsdom and fails if:

- a published corpus does not REVEAL the block with the catalogue's own totals (1,418 stations /
  21 surveys in the fixture, which is what the deployed build serves);
- a rejected fetch or a 404 does not leave the block HIDDEN (file://, an unpublished deployment);
- an empty build does not leave it HIDDEN (it must never read "0 stations · 0 surveys").

The companion static pins live in test_about_uniform_chrome.py
(test_about_corpus_stats_are_fetched_not_hardcoded): no digit in the markup, external script only.

Skips when Node or the jsdom dev-dependency is absent (CI runs `npm ci` in portal/ first)."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent                 # portal/
DRIVER = ROOT / "tools" / "corpus_stats_test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_about_corpus_stats_block():
    r = subprocess.run(["node", str(DRIVER)], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
    if "Cannot find module 'jsdom'" in (r.stderr or ""):
        pytest.skip("jsdom not installed (run `npm ci` in portal/)")
    assert r.returncode == 0, f"corpus-stats driver failed:\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
    assert "CORPUS STATS OK" in r.stdout, r.stdout
