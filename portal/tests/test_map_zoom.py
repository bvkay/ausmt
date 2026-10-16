"""The map stops zooming out at the continent, stays near the data, and never repeats the world.

Three constraints, driven on the real vendored Leaflet by tools/map_zoom_test.js:

- the zoom floor (minZoom 3) is the smallest zoom at which the home frame fits the measured map panes
  (824 x 686 and 655 x 654 beside the desktop sidebar, 375 x 760 on a phone), so a phone still sees the
  whole continent and no viewport reaches a world view;
- the pan box (maxBounds, viscosity 1) holds the served extent with at least 10 degrees to spare, is
  centred on the home frame so the fitted home view never moves, and is dropped by a build that serves a
  station outside it;
- at the floor the world is wider than every measured pane, so its copies never sit side by side, and
  every tile the floor view covers is drawn, including the strip past 180 E a desktop pane reaches.

FAILS IF any of the three regresses. Exit 2 from the driver is jsdom being absent, a SKIP.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent          # portal/
DRIVER = ROOT / "tools" / "map_zoom_test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_zoom_floor_pan_box_and_floor_basemap_are_driven():
    r = subprocess.run(["node", str(DRIVER)], capture_output=True, text=True,
                       encoding="utf-8", cwd=str(ROOT))
    out = r.stdout + r.stderr
    if r.returncode == 2:
        pytest.skip("jsdom dev-dependency not installed (run `npm ci` in portal/)")
    assert r.returncode == 0, out
    assert "MAP ZOOM OK" in out, out
