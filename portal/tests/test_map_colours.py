"""What the SPA map draws outside the stylesheet, and where its colours come from.

The stylesheet colours everything CSS can reach. Three things the map draws are outside it: the
basemap, which is a canvas the protomaps renderer paints in a named flavour; the station dots, which
Leaflet strokes on a canvas; and the selection shapes, which leaflet.draw styles from options. The
basemap is the light flavour the house style sits on, and the dots and shapes read their colours from
the tokens with getComputedStyle when they are built.

SOURCE PINS hold the shape of that wiring; tools/map_colours_test.js boots the shipped map.js with
Leaflet and protomaps stubbed and asserts what was drawn. It needs no jsdom.

FAILS IF:
  * the pmtiles pair is built in any flavour but light, or is built more than once;
  * the dots or the shapes go back to a literal colour;
  * the tour's demo shapes stop matching the hand-drawn ones;
  * the driven boot draws another flavour, another shape colour, or listens for anything on document.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent          # portal/
MAP_JS = ROOT / "src" / "map.js"
TOUR_JS = ROOT / "src" / "tour.js"
DRIVER = ROOT / "tools" / "map_colours_test.js"


def _code(path):
    """Source with whole-line comments stripped, so prose about a pattern cannot satisfy a pin."""
    return "\n".join(ln for ln in path.read_text(encoding="utf-8").splitlines()
                     if not ln.strip().startswith("//"))


def test_the_basemap_pair_is_the_light_flavour():
    code = _code(MAP_JS)
    assert code.count("protomapsL.leafletLayer(") == 2, "the pmtiles pair is two layers, built in one place"
    assert code.count('flavor:"light"') == 2, "both pmtiles layers take the light flavour"
    assert "flavor:" in code and not re.search(r'flavor:(?!"light")', code), "no layer takes another flavour"


def test_the_dots_and_shapes_read_their_colours_from_the_tokens():
    code = _code(MAP_JS)
    assert 'edge=themeToken("--dot-edge")' in code, "buildMarkers reads the dot edge from --dot-edge"
    marker = re.search(r"L\.circleMarker\([^;]*\);", code)
    assert marker and "color:edge" in marker.group(0), "every station marker is stroked with the token"
    assert not re.search(r'color:"#[0-9A-Fa-f]{6}"', code.split("L.control.layers(")[0]), (
        "no dot or shape colour is a literal; the dormant overlay layers below the layer control "
        "are data encodings and are not read here")
    assert 'function shapeStyle(){return {color:themeToken("--accent"),weight:2};}' in code, (
        "the selection shapes take the --accent token")
    assert code.count("shapeOptions:shapeStyle()") == 2, "both draw tools take the token's shape style"


def test_the_tour_draws_its_demo_shapes_in_the_hand_drawn_style():
    code = _code(TOUR_JS)
    assert "#EF7256" not in code, "the tour's demo shapes take the token, not the old accent literal"
    assert "L.rectangle([[b.south,b.west],[b.north,b.east]],shapeStyle())" in code, (
        "the demo rectangle matches a hand-drawn one")
    assert 'L.rectangle(ll,Object.assign(shapeStyle(),{dashArray:"6 5",fill:false}))' in code, (
        "the growing outline is the hand-drawn style, dashed and unfilled")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_the_shipped_map_is_driven_through_its_boot():
    r = subprocess.run(["node", str(DRIVER)], cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8")
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode == 0, f"map colours driver failed:\n{out}"
    assert "MAP COLOURS OK" in out, out
