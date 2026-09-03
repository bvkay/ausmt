"""The map draws SITE LOCATIONS and nothing else.

Two halves, because two different things need proving and only one of them is a runtime behaviour:

SOURCE PINS (this file's first half). Leaflet.markercluster is gone, and so is the per-survey BADGE layer
that replaced it in change 6: the badge icons, the three zoom/span/count thresholds, the collision
declutter, the leader tails and the decoration panes they rode in. Those are REMOVALS, and a removal is
only provable by looking at what ships. A jsdom run cannot observe the absence of a layer the map never
draws, and the interaction driver's own dots-only pin cannot see a constant that is still declared.

BEHAVIOUR PINS (second half, via tools/map_dots_test.js). The dot geometry and the focus-dim decision are
pure functions, so both run for real against the shipped src. What is NOT proven here, and is not provable
in this harness: that a rendered dot is clickable and lands where its coordinates say. Those are browser
facts; the interaction driver asserts the call arguments and the architect clicks the rest.

THE OVERLOADED NAME, stated so a future reader does not repeat the mistake this module was warned about:
`grep -c badge` over portal/src does NOT go to zero, and must not. The DRAWER's generalised-position badge
is a coordinate-POLICY surface (test_coord_access.py owns it), the format-availability badges are a
distribution surface, and the stewardship star is its own thing. Only the MAP's survey bubbles and their
leaders were removed. test_the_drawer_badges_are_untouched below is that boundary, written down.

FAILS IF:
- any markercluster or badge asset, constant, function or style survives in the shipped portal;
- the map creates a Leaflet pane, or routes any layer into one;
- a zoom re-routes layer membership again (badging was the only thing that made membership zoom-dependent);
- the legend keys a map object that is not a data type;
- the radius curve stops being monotone in zoom, breaches its floor/ceiling, or stops rendering EVERY data
  type at the same size;
- the drawer's own badges are collateral damage.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent          # portal/
MAP_JS = ROOT / "src" / "map.js"
FILTERS_JS = ROOT / "src" / "filters.js"
MAIN_JS = ROOT / "src" / "main.js"
DRAWER_JS = ROOT / "src" / "drawer.js"
INDEX = ROOT / "index.html"
DRIVER = ROOT / "tools" / "map_dots_test.js"


def _map_src():
    return MAP_JS.read_text(encoding="utf-8")


def _code(src):
    """Source with whole-line comments stripped.

    Load-bearing everywhere below: this repo's map.js narrates its own history, so the prose names every
    object that was ever removed. A raw scan for a removed name therefore passes on the comment that
    records the removal, which is how an earlier version of this file caught itself being vacuous.
    """
    return "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("//"))


# ---------------------------------------------------------------- source pins

def test_markercluster_is_gone_from_the_shipped_portal():
    html = INDEX.read_text(encoding="utf-8")
    assert "markercluster" not in html.lower(), \
        "index.html must not load Leaflet.markercluster any more (change 6 removed proximity clustering)"
    assert "MarkerCluster.min.css" not in html, "the MarkerCluster stylesheet link must be gone"
    assert ".marker-cluster" not in html, \
        "the cluster-bubble styles must be gone too: a rule for a class nothing can carry tells a " \
        "stylesheet reader that clusters still ship"
    for stale in (ROOT / "vendor" / "leaflet.markercluster.min.js",
                  ROOT / "vendor" / "MarkerCluster.min.css"):
        assert not stale.exists(), f"{stale.name} must be deleted with the feature that used it"


def test_no_clustering_api_calls_remain_in_src():
    code = _code(_map_src())
    for banned in ("markerClusterGroup", "disableClusteringAtZoom", "iconCreateFunction", "maxClusterRadius"):
        assert banned not in code, f"map.js must not call the retired clustering API ({banned})"


@pytest.mark.parametrize("name", ["BADGE_MAX_ZOOM", "BADGE_SPAN_PX", "BADGE_MIN_STATIONS",
                                  "BADGE_SIZE_SCALE", "BADGE_GAP_PX", "BADGE_MAX_SHIFT_PX",
                                  "BADGE_DECLUTTER_PASSES", "BADGE_TAIL_MIN_PX", "BADGE_TAIL_COLOR",
                                  "BADGE_TAIL_OPACITY", "BADGE_TAIL_PANE", "BADGE_TAIL_PANE_Z",
                                  "SURV_PANE_Z"])
def test_no_badge_constant_survives(name):
    """The thresholds are the seam the feature would grow back from: a surviving constant is a rule
    somebody can wire up again in one line. They go with the layer, not after it."""
    assert not re.search(rf"\b{name}\b\s*=", _map_src()), \
        f"{name} must be gone: the per-survey badge layer was removed whole on 2026-08-24"


@pytest.mark.parametrize("name", ["badgeIcon", "badgeSizePx", "shouldBadgeSurvey", "partitionForDisplay",
                                  "declutterBadges", "renderBadges", "_badgeLayout", "_badgeBbox",
                                  "surveyCentroid", "mercatorPixelSpan", "mercatorY", "tailOpacityFor",
                                  "_survPaneFor", "_makeDecorationPane", "_decorationPaneViolation",
                                  "badgesEnabledForMode"])
def test_no_badge_function_survives(name):
    """Every function the badge layer was built from, across the two modules that held them. Named one by
    one rather than by a `badge` substring sweep, because the drawer's own badge helpers must NOT match."""
    for path in (MAP_JS, FILTERS_JS):
        assert not re.search(rf"function\s+{name}\s*\(", path.read_text(encoding="utf-8")), \
            f"{name} must be gone with the badge layer ({path.name})"


def test_the_map_builds_no_badge_layer_and_no_pane():
    """The two Leaflet calls the feature needed, and the pane machinery that made the outage
    possible. A pane is what puts a full-map-size canvas over the station canvas; the map creating none is
    what makes the retired pane guard safe to delete rather than merely unused."""
    code = _code(_map_src())
    assert "createPane" not in code, \
        "map.js must create no pane: a pane sits over the station canvas at z 400 and swallows the clicks " \
        "the stations need (the production outage of 2026-08-19)"
    assert "divIcon" not in code, "a divIcon is a badge; the map draws canvas circleMarkers only"
    assert "L.polyline" not in code, "L.polyline was the leader tail; nothing draws one now"
    assert "badgeLayer" not in code, "the badge layer group must be gone"
    assert re.search(r"const\s+dotLayer\s*=\s*L\.layerGroup\(\)", code), \
        "the ONE dot container must survive (change 6's own simplification)"


def test_a_zoom_restyles_but_does_not_reroute():
    """Badging was the only thing that made layer membership zoom-dependent: a survey collapsed or
    dissolved on a zoom notch alone. Membership is a FILTER answer now, so zoomend goes back to the
    restyle it was before change 6. FAILS IF a re-route is wired back onto zoom, which would silently
    reintroduce the idea that zoom decides what the map shows."""
    src = _map_src()
    code = _code(src)
    assert re.search(r'map\.on\(\s*"zoomend"\s*,\s*restyleForZoom\s*\)', code), \
        'zoomend must be wired to restyleForZoom (radius and weight track the zoom tier)'
    assert "reflowForZoom" not in code, \
        "reflowForZoom (restyle AND re-route) was the badge era's zoom handler and must be gone"
    m = re.search(r"function\s+routeVisibleToLayers\s*\(\s*\)\s*\{(.*?)\n\}", code, re.S)
    assert m, "map.js must still define routeVisibleToLayers (refresh paints through it)"
    assert "curZoom" not in m.group(1), \
        "the paint pass must not read the zoom: which stations are on the map is a filter answer"


def test_the_legend_keys_only_data_types():
    """A legend states what the map draws. The badge swatch (and the .legcluster it was renamed from) key
    objects that no longer exist, so both must be gone from the markup AND the stylesheet."""
    main = MAIN_JS.read_text(encoding="utf-8")
    html = INDEX.read_text(encoding="utf-8")
    for gone in ("legbadge", "legcluster"):
        assert gone not in main, f"the legend must not render a .{gone} row"
        assert gone not in html, f"the .{gone} style must be gone with the row it painted"
    assert "zoom to expand" not in main, \
        "the legend must not promise that anything expands on zoom; nothing collapses any more"


def test_no_badge_styles_survive():
    html = INDEX.read_text(encoding="utf-8")
    for gone in (".ausmt-badge", "svbadge-small", "svbadge-medium", "svbadge-large"):
        assert gone not in html, f"{gone} styled a survey badge and must be gone with it"


def test_the_drawer_badges_are_untouched():
    """THE OVERLOADED-NAME GUARD, and the reason this file does not sweep for the word `badge`.

    Three surfaces share the name and NONE of them is map furniture: the drawer's generalised-position
    badge is coordinate POLICY (C42), the format-availability badges are a distribution claim, and both
    render through the same `.badge` CSS. A future tidy-up that greps `badge` to zero would delete a
    coordinate-policy disclosure and a served-format claim, which is why the boundary is a test."""
    html = INDEX.read_text(encoding="utf-8")
    drawer = DRAWER_JS.read_text(encoding="utf-8")
    assert re.search(r"^\s*\.badge\{", html, re.M), "the drawer's .badge style must survive"
    assert re.search(r"^\s*\.badges\{", html, re.M), "the drawer's .badges row style must survive"
    assert re.search(r"function\s+badge\s*\(", drawer), \
        "drawer.js's badge() helper renders the format-availability claims and is not map furniture"
    assert "position generalised" in drawer, \
        "the drawer's generalised-position disclosure is a coordinate-POLICY surface, not a map badge"


def test_radius_curve_is_named_not_inlined():
    src = _map_src()
    for name in ("DOT_R_FLOOR", "DOT_R_CEIL", "DOT_R_SLOPE", "DOT_R_BASE"):
        assert re.search(rf"\b{name}\b\s*=", src), f"the radius curve constant {name} must be named in map.js"


def test_the_per_type_radius_split_is_gone():
    """Uniform site dot size. The per-type bases are REMOVED, not merely equalised: a
    surviving DOT_R_BASE_LP/DOT_R_BASE_STD pair is exactly the shape a future edit would re-diverge. FAILS
    IF either name comes back, or if radiusForZoom regains a second parameter."""
    src = _map_src()
    for gone in ("DOT_R_BASE_LP", "DOT_R_BASE_STD"):
        assert gone not in src, (
            f"{gone} must be gone: data type is carried by COLOUR now, and a per-type radius constant is "
            f"the seam a future edit would widen back into two sizes.")
    m = re.search(r"function\s+radiusForZoom\s*\(([^)]*)\)", src)
    assert m, "map.js must define radiusForZoom"
    params = [p.strip() for p in m.group(1).split(",") if p.strip()]
    assert params == ["z"], (
        f"radiusForZoom must take ZOOM ALONE, got parameters {params}. Size encodes zoom; type encodes "
        f"colour. A `type` parameter is how the split returns.")


def test_station_markers_carry_their_own_click_and_never_bubble():
    """The click-through class the outage belonged to. A station dot must open its station, and
    must not ALSO read as a background click (which closes the drawer). COMMENT-STRIPPED, because the prose
    beside it explains the guarantee and would satisfy a raw scan with the option deleted."""
    code = _code(_map_src()).replace(" ", "")
    assert "s.marker.options.bubblingMouseEvents=false" in code, \
        "a station marker must set bubblingMouseEvents:false, or its click opens the drawer and the " \
        "background handler immediately closes it"
    assert 's.marker.on("click",()=>openStation(s.i))' in code, \
        "a station marker click must open that station"


# ------------------------------------------------------------- behaviour pins

@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_dot_geometry_and_dim_behaviour():
    r = subprocess.run(["node", str(DRIVER)], cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8")
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode == 0, f"map dots driver failed:\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
    assert "MAP DOTS OK" in out, out
