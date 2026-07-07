"""C32 portal bundle tiles (Invariant 10).

The survey drawer renders per-survey download tiles from the manifest's `bundles` rows. C32 adds a
second always-on bundle (EMTF-XML zip) beside the EDI zip, and re-labels the flag-gated survey MTH5 as
TRANSFER FUNCTIONS ONLY (it holds TFs, never time series — matching the engine's <slug>-tf.h5 file).

This boots the REAL portal modules in jsdom (tools/bundle_tiles_test.js) against a synthetic MANIFEST
and drives surveyBundleTiles(). It FAILS if:
- a served survey does not render all three tiles with the right urls/labels;
- the MTH5 tile does not say "transfer functions" (or implies "time series");
- a survey with no bundle rows (embargoed/withheld) renders anything but the empty state;
- a hostile slug that reached a bundle url is not HTML-escaped in the emitted markup (no live <img>).

Skips when Node or the jsdom dev-dependency is absent (CI runs `npm ci` in portal/ first)."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent                 # portal/
DRIVER = ROOT / "tools" / "bundle_tiles_test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_portal_bundle_tiles():
    r = subprocess.run(["node", str(DRIVER)], cwd=str(ROOT), capture_output=True, text=True)
    if "Cannot find module 'jsdom'" in (r.stderr or ""):
        pytest.skip("jsdom not installed (run `npm ci` in portal/)")
    assert r.returncode == 0, f"bundle-tiles driver failed:\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
    assert "BUNDLE TILES OK" in r.stdout, r.stdout
