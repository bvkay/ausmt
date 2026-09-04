"""engine/extract/_au_outline.py and portal/vendor/au-outline.js are ONE coastline, in two languages.

Both files say they carry the same geometry so the survey minimap, the link-preview cards and the SPA
collections footprint draw one map. That claim must not rest on two hand-maintained coordinate lists
and a comment asking the reader to believe it. Both are now GENERATED in a single pass by
engine/extract/_au_outline_build.py from Natural Earth, and these pins hold the arrangement:

  * the JS is EXECUTED and its arrays compared to the Python's, number for number. A drift of one
    vertex fails, which is the failure a comment can never catch.
  * the ring ORDER is the contract. portal/tools/gen_brand.py and test_brand_source_of_truth.py
    address COAST[0] as the mainland and COAST[1] as Tasmania by POSITION, so a re-derivation that
    reordered the rings would silently rasterise the wrong shape into the brand mark.
  * the borders are pinned to their literal values. They are the legislated meridian and parallel
    segments - geographic facts, not a simplification - so a coastline re-derivation must never move
    them, and a future edit to the generator that swept them into the derived output fails here.
  * every ring is closed and lies inside the declared EXTENT, which is what lets the rasteriser and
    the even-odd fill in both surfaces assume a well-formed polygon.

Re-deriving from Natural Earth needs the source layer, so it is a deliberate manual step
(`python3 engine/extract/_au_outline_build.py`) rather than a test: these pins check the committed
pair is self-consistent, which is the part that can rot silently between derivations.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent          # portal/
REPO = ROOT.parent
JS = ROOT / "vendor" / "au-outline.js"
PY = REPO / "engine" / "extract" / "_au_outline.py"

sys.path.insert(0, str(REPO / "engine" / "extract"))
from _au_outline import BORDERS, COAST, EXTENT  # noqa: E402  (sibling engine module, stdlib-only)

# The legislated segments, restated here as literals so the pin does not read them from the file it
# checks. These are meridians and parallels (and the Murray, approximated), not derived geometry.
LEGISLATED = [
    [[129, -14.8], [129, -31.9]],
    [[129, -26], [141, -26]],
    [[138, -26], [138, -17.7]],
    [[141, -29], [141, -38]],
    [[141, -29], [148.9, -29], [151, -28.9], [152.5, -28.2]],
    [[141, -34.1], [143.5, -35.3], [144.5, -35.9], [146, -36.1], [147, -36.1], [148.1, -36.8],
     [149.9, -37.8]],
]


def _js_outline():
    """window.AU_OUTLINE, as the browser would see it: the file is RUN, not parsed with a regex."""
    driver = ("const fs=require('fs'),vm=require('vm');"
              "const ctx={window:{}};vm.createContext(ctx);"
              f"vm.runInContext(fs.readFileSync({json.dumps(str(JS))},'utf8'),ctx);"
              "process.stdout.write(JSON.stringify(ctx.window.AU_OUTLINE));")
    r = subprocess.run(["node", "-e", driver], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, f"au-outline.js did not execute:\n{r.stderr}"
    return json.loads(r.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_the_two_surfaces_carry_the_same_coastline_number_for_number():
    """FAILS IF the Python and the JavaScript coastlines differ by a single vertex. This is the pin
    the 'SAME GEOMETRY' claim in both file headers actually rests on."""
    js = _js_outline()
    py_coast = [[list(p) for p in ring] for ring in COAST]
    assert len(js["coast"]) == len(py_coast), (
        f"ring count differs: JS has {len(js['coast'])}, Python has {len(py_coast)}")
    for i, (a, b) in enumerate(zip(py_coast, js["coast"])):
        assert a == b, (f"coast ring {i} differs between the two files "
                        f"({len(a)} vs {len(b)} points); re-run _au_outline_build.py")
    assert [[list(p) for p in r] for r in BORDERS] == js["borders"], \
        "the inter-state borders differ between the two files"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_the_js_declares_one_global_and_fetches_nothing():
    """The SPA loads this as a classic script under a script-src 'self' CSP. FAILS IF it grows a
    fetch, an import or a second global, any of which would be blocked or would change how
    collScatter gets its geometry."""
    text = JS.read_text(encoding="utf-8")
    for banned in ("fetch(", "XMLHttpRequest", "import ", "require(", "eval("):
        assert banned not in text, f"au-outline.js must stay an inert data literal, found {banned!r}"
    assert len(re.findall(r"^window\.\w+\s*=", text, re.M)) == 1, \
        "the asset assigns exactly one global"


def test_the_ring_order_is_the_contract_the_brand_mark_addresses_by_position():
    """gen_brand.py and the brand pin name COAST[0] and COAST[1] by POSITION. FAILS IF a
    re-derivation reorders the rings, which would rasterise an island into the mark as the mainland
    and would not otherwise announce itself."""
    assert len(COAST) >= 2, "the mainland and Tasmania are always present"

    def area(ring):
        return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:]))) / 2

    areas = [area(r) for r in COAST]
    # Largest first is the generator's ordering rule, so "the mainland then Tasmania" is a
    # CONSEQUENCE of that rule rather than a coincidence a future island could quietly break.
    assert areas == sorted(areas, reverse=True), \
        f"rings must be emitted largest first, got areas {[round(a, 3) for a in areas]}"
    lons = [p[0] for p in COAST[1]]
    lats = [p[1] for p in COAST[1]]
    assert 144 < min(lons) and max(lons) < 149 and -44 < min(lats) and max(lats) < -40, \
        f"COAST[1] must be Tasmania, got lon {min(lons)}..{max(lons)} lat {min(lats)}..{max(lats)}"
    assert max(p[1] for p in COAST[0]) > -11, "the mainland ring must reach Cape York"


def test_every_ring_is_closed_and_inside_the_declared_extent():
    """FAILS IF a ring stops being a closed polygon (both surfaces fill it, and an open ring fills to
    an arbitrary chord) or if geometry appears outside the extent the projection maps, which would
    draw outside the minimap's own box."""
    for i, ring in enumerate(COAST):
        assert ring[0] == ring[-1], f"coast ring {i} is not closed"
        assert len(ring) >= 4, f"coast ring {i} is not a polygon ({len(ring)} points)"
        for lon, lat in ring:
            assert EXTENT["w"] <= lon <= EXTENT["e"] and EXTENT["s"] <= lat <= EXTENT["n"], \
                f"coast ring {i} leaves the declared extent at ({lon}, {lat})"


def test_the_borders_are_the_legislated_segments_and_the_derivation_never_touches_them():
    """FAILS IF a coastline re-derivation moves an inter-state border. They are meridians, parallels
    and the Murray: facts about where the lines were drawn, not a generalisation of a coastline, so
    a new Natural Earth release must leave them exactly where they are."""
    assert [[list(p) for p in r] for r in BORDERS] == LEGISLATED, \
        "the inter-state borders moved; they are legislated segments and are not derived"


def test_both_files_record_where_the_geometry_came_from():
    """A generated file that does not say what it was generated FROM is a file nobody can re-derive.
    FAILS IF the provenance stops naming the layer, the licence, the tolerance or the generator."""
    for path in (PY, JS):
        head = path.read_text(encoding="utf-8")[:3000]
        for needle in ("Natural Earth", "ne_50m_admin_0_countries", "public domain",
                       "Douglas-Peucker", "_au_outline_build.py"):
            assert needle in head, f"{path.name} must record {needle!r} in its header"
