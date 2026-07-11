"""C25-V3 portal frame line (Invariant 10).

The station drawer shows a terse, honest frame line when the engine served a station's impedances AS
STORED in a declared acquisition frame (frame policy v3: the engine never de-rotates). This boots the
REAL portal modules in jsdom (tools/frame_line_test.js) and drives the pure frameLineText() plus the
lazy loadStationFrameLine() fetch/inject/stale-guard path.

It FAILS if:
- a non-zero declared angle does not render (or a zero/absent/null frame is not silent);
- the V3-B "mixed declared frames" clause is missing when the survey carries the note;
- frameLineText emits markup for a hostile survey_frame_note (injection surface);
- loadStationFrameLine does not inject via textContent, or a stale async write clobbers the drawer.

Skips when Node or the jsdom dev-dependency is absent (CI runs `npm ci` in portal/ first)."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent                 # portal/
DRIVER = ROOT / "tools" / "frame_line_test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_portal_frame_line():
    r = subprocess.run(["node", str(DRIVER)], cwd=str(ROOT), capture_output=True, text=True)
    if "Cannot find module 'jsdom'" in (r.stderr or ""):
        pytest.skip("jsdom not installed (run `npm ci` in portal/)")
    assert r.returncode == 0, f"frame-line driver failed:\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
    assert "FRAME LINE OK" in r.stdout, r.stdout
