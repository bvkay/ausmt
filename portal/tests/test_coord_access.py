"""C42 lane 3 — portal handles masked coordinates (Invariant 10).

The engine masks a custodian-withheld station to null lat/lon and a generalised station to a 0.1deg
cell, AND (C42 Amendment A1) emits an explicit coordinate-policy marker for the non-exact stations on a
boot-loaded artifact (coord_policy.json). This boots the REAL portal modules in jsdom
(tools/coord_access_test.js) over ENGINE-BUILT fixtures (tests/fixtures/c42/, produced by
tools/gen_c42_fixtures.py) and drives the null-coord + generalised-badge paths.

It FAILS if:
- a withheld station produces a map marker, a (null,null)/NaN marker point, or a NaN fitBounds set;
- the withheld drawer throws, omits the "coordinates withheld (custodian policy)" line, prints
  null/undefined, or leaks a lat/lon-like decimal pair (the DOM-layer leak sweep);
- a generalised station's drawer omits the "position generalised to ~0.1°" badge or leaks its true
  6-dp coordinates (the A1 badge + DOM-layer leak pin);
- a withheld station is spatially selected (bbox/polygon) or is no longer findable by text;
- the survey station count drops the withheld station.

Skips when Node or the jsdom dev-dependency is absent (CI runs `npm ci` in portal/ first)."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent                 # portal/
DRIVER = ROOT / "tools" / "coord_access_test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_portal_coord_access():
    r = subprocess.run(["node", str(DRIVER)], cwd=str(ROOT), capture_output=True, text=True)
    if "Cannot find module 'jsdom'" in (r.stderr or ""):
        pytest.skip("jsdom not installed (run `npm ci` in portal/)")
    assert r.returncode == 0, f"coord-access driver failed:\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
    assert "COORD ACCESS OK" in r.stdout, r.stdout
