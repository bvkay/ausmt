"""What the SPA map redraws when the appearance changes.

The stylesheet themes everything CSS can reach. Three things the map draws are outside it: the
basemap, which is a canvas the protomaps renderer paints in a named flavour; the station dots, which
Leaflet strokes on a canvas; and the selection shapes, which leaflet.draw styles from options. Each
reads its colour from the theme tokens with getComputedStyle when it is built and again when
src/theme.js announces a change with "ausmt:theme".

SOURCE PINS hold the shape of that wiring; tools/map_theme_test.js drives the shipped map.js through a
theme change with Leaflet and protomaps stubbed and asserts what was redrawn. It needs no jsdom.

FAILS IF:
  * the pmtiles pair is built anywhere but the one function that takes the flavour, or keeps a
    literal flavour;
  * the dots or the shapes go back to a literal colour, or stop following a theme change;
  * the tour's demo shapes stop matching the hand-drawn ones;
  * the driven change does not remount the basemap, restyle the dots or restyle the shapes.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent          # portal/
MAP_JS = ROOT / "src" / "map.js"
TOUR_JS = ROOT / "src" / "tour.js"
DRIVER = ROOT / "tools" / "map_theme_test.js"


def _code(path):
    """Source with whole-line comments stripped, so prose about a pattern cannot satisfy a pin."""
    return "\n".join(ln for ln in path.read_text(encoding="utf-8").splitlines()
                     if not ln.strip().startswith("//"))


def test_the_basemap_pair_is_built_in_one_flavoured_function():
    code = _code(MAP_JS)
    assert code.count("protomapsL.leafletLayer(") == 2, "the pmtiles pair is two layers, built in one place"
    body = re.search(r"function mountBasemap\(flavor\)\{(.*?)\n\}", code, re.S)
    assert body and body.group(1).count("protomapsL.leafletLayer(") == 2, (
        "both pmtiles layers are built inside mountBasemap(flavor)")
    assert body.group(1).count("flavor,") == 2, "both layers take the flavour they are given"
    assert 'flavor:"light"' not in code and 'flavor:"dark"' not in code, "no layer keeps a literal flavour"
    assert "map.removeLayer(" in body.group(1), "a remount removes the old pair before it adds the new one"
    assert "mountBasemap(resolvedTheme())" in code, "the pair is mounted at start in the resolved theme"
    assert re.search(r'getAttribute\("data-theme"\)==="dark"\?"dark":"light"', code), (
        "the resolved theme is read from the attribute src/theme.js writes before first paint")


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


def test_a_theme_change_reaches_every_drawn_colour():
    code = _code(MAP_JS)
    handler = re.search(r'document\.addEventListener\("ausmt:theme",e=>\{(.*?)\n\}\);', code, re.S)
    assert handler, 'map.js must listen for "ausmt:theme" on document'
    body = handler.group(1)
    for needle, what in (("mountBasemap(e.detail.theme)", "the basemap is remounted in the new flavour"),
                         ("s.marker.setStyle({color:edge})", "every marker takes the new edge"),
                         ("drawControl.setDrawingOptions(", "the draw tool takes the new accent"),
                         ("drawn.eachLayer(", "shapes already drawn are restyled")):
        assert needle in body, f"the theme handler is missing: {what}"


def test_the_tour_draws_its_demo_shapes_in_the_hand_drawn_style():
    code = _code(TOUR_JS)
    assert "#EF7256" not in code, "the tour's demo shapes take the token, not the old accent literal"
    assert "L.rectangle([[b.south,b.west],[b.north,b.east]],shapeStyle())" in code, (
        "the demo rectangle matches a hand-drawn one")
    assert 'L.rectangle(ll,Object.assign(shapeStyle(),{dashArray:"6 5",fill:false}))' in code, (
        "the growing outline is the hand-drawn style, dashed and unfilled")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_a_theme_change_is_driven_through_the_shipped_map():
    r = subprocess.run(["node", str(DRIVER)], cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8")
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode == 0, f"map theme driver failed:\n{out}"
    assert "MAP THEME OK" in out, out
