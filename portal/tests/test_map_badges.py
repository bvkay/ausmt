"""Change 6 (owner, 2026-08-18) map declutter: per-survey BADGES replace proximity clustering.

Two halves, because two different things need proving and only one of them is a runtime behaviour:

SOURCE PINS (this file's first half). Leaflet.markercluster is GONE - script tag, stylesheet link and the
vendored files. That is a REMOVAL, and a removal is only provable by looking at what ships: a jsdom run
cannot observe the absence of a plugin it stubs anyway. These also pin the three thresholds as NAMED
constants so a drive-by literal edit fails a test rather than silently re-tiering the map.

BEHAVIOUR PINS (second half, via tools/map_badges_test.js). The badge rule is a pure function of
(count, zoom, bbox, AusLAMP membership, sidebar mode) and the router is a pure function of a station list,
so BOTH run for real in jsdom against the shipped src - no Leaflet needed, no stubs standing in for the
logic under test. What is NOT proven here, and is not provable in this harness: that a rendered badge is
clickable, that Leaflet places it where the centroid says, and that a real pointer reaches it. Those are
browser facts; the interaction driver asserts the call ARGUMENTS and the architect clicks the rest.

FAILS IF:
- any markercluster asset or reference survives in the shipped portal;
- a threshold stops being a named constant, or changes value without this test changing with it;
- a survey can produce two badges (the one-badge-per-survey invariant);
- a badge is placed anywhere but its survey's centroid;
- the threshold crossing does not expand a survey (compact -> badge, zoomed in -> dots);
- an AusLAMP member ever badges, or a lone station badges;
- Select & export leaves anything badged;
- the radius curve stops being monotone in zoom, breaches its floor/ceiling, or stops rendering EVERY data
  type at the same size (the per-type split was removed 2026-08-19: size encodes zoom, colour encodes type);
- the badge collision declutter stops separating overlapping badges, moves the largest badge of a colliding
  set, exceeds its travel cap, loses determinism, or renders a displaced badge without the leader tail back
  to its true centroid. That LAST clause is carried by the driver's render-path section, which drives the
  real renderBadges against a recording Leaflet stub and asserts on what reached the layer. It has to be
  behavioural: the source-shape pins here cannot see whether a computed layout is actually USED, and a gate
  review caught exactly that gap (two mutations that emptied the render path left everything green).
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent          # portal/
MAP_JS = ROOT / "src" / "map.js"
INDEX = ROOT / "index.html"
DRIVER = ROOT / "tools" / "map_badges_test.js"


def _map_src():
    return MAP_JS.read_text(encoding="utf-8")


# ---------------------------------------------------------------- source pins

def test_markercluster_is_gone_from_the_shipped_portal():
    html = INDEX.read_text(encoding="utf-8")
    assert "markercluster" not in html.lower(), \
        "index.html must not load Leaflet.markercluster any more (change 6 removed proximity clustering)"
    assert "MarkerCluster.min.css" not in html, "the MarkerCluster stylesheet link must be gone"
    for stale in (ROOT / "vendor" / "leaflet.markercluster.min.js",
                  ROOT / "vendor" / "MarkerCluster.min.css"):
        assert not stale.exists(), f"{stale.name} must be deleted with the feature that used it"


def test_no_clustering_api_calls_remain_in_src():
    src = _map_src()
    # comments may narrate the removal; CODE may not call the plugin.
    code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("//"))
    for banned in ("markerClusterGroup", "disableClusteringAtZoom", "iconCreateFunction", "maxClusterRadius"):
        assert banned not in code, f"map.js must not call the retired clustering API ({banned})"


@pytest.mark.parametrize("name,value", [("BADGE_MAX_ZOOM", "7"),
                                        ("BADGE_SPAN_PX", "64"),
                                        ("BADGE_MIN_STATIONS", "2")])
def test_thresholds_are_named_constants_with_the_ruled_values(name, value):
    m = re.search(rf"const\s+{name}\s*=\s*(\d+)\s*;", _map_src())
    assert m, f"map.js must define `const {name} = <n>;` (change 6 threshold, pinned not inlined)"
    assert m.group(1) == value, (
        f"{name} must be {value}; found {m.group(1)}. Change the value only with the owner's ruling, and "
        f"change this pin in the same commit so the decision stays written down.")


def test_threshold_rationale_rides_with_the_constants():
    # The pixel threshold is the one a future reader is most likely to "tidy" into km. Keep the reasoning
    # beside it: a km threshold means a different thing at every zoom, which is why this one is in pixels.
    src = _map_src().lower()
    assert "pixel" in src and "centroid" in src, \
        "map.js must document that badging is decided in screen PIXELS and placed at the CENTROID"


def test_zoom_rerouting_is_wired():
    # SOURCE pin, and the docstring says why it has to be one: badging is zoom-dependent, so a zoom notch
    # alone must re-route (a survey collapses or dissolves without any filter changing). The harness stubs
    # Leaflet, so `map.on("zoomend", ...)` never fires there and no runtime assertion can reach this. What
    # is checkable is that the handler is wired to the function that DOES re-route, not to the old
    # restyle-only one, which is exactly the regression a future edit would introduce.
    src = _map_src()
    assert re.search(r'map\.on\(\s*"zoomend"\s*,\s*reflowForZoom\s*\)', src), \
        'zoomend must be wired to reflowForZoom (restyle AND re-route), not to restyleForZoom alone'
    assert re.search(r"function\s+reflowForZoom\s*\(\s*\)\s*\{[^}]*routeVisibleToLayers\s*\(", src), \
        "reflowForZoom must call routeVisibleToLayers, or a zoom would restyle dots without re-badging"


def test_badge_click_opens_the_survey_and_never_bubbles():
    # SOURCE pin for the same reason: under a stubbed Leaflet a marker's click handler is never dispatched,
    # so the two guarantees the owner named can only be read off the source here. Both matter and both are
    # one edit away from breaking: a badge must open its survey through the SAME openSurvey the hash route
    # uses, and it must not let the click bubble to change 5's background handler, which would open the
    # drawer and instantly close it. The architect's browser click-through is what proves it end to end.
    # COMMENT-STRIPPED, and that is load-bearing: the comment above renderBadges explains this guarantee and
    # therefore contains the literal string, so a scan of the raw source passes even when the option itself
    # has been deleted. (Found by the mutation battery: the first version of this test was vacuous.)
    src = _map_src()
    code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("//"))
    assert "bubblingMouseEvents:false" in code.replace(" ", ""), \
        "a badge marker must set bubblingMouseEvents:false so its click never reads as a background click"
    assert re.search(r"m\.on\(\s*\"click\"\s*,\s*\(\)\s*=>\s*\{[^}]*openSurvey\(", code), \
        "a badge click must call openSurvey (the same path the #/survey/<slug> route uses)"


def test_radius_curve_is_named_not_inlined():
    src = _map_src()
    for name in ("DOT_R_FLOOR", "DOT_R_CEIL", "DOT_R_SLOPE", "DOT_R_BASE"):
        assert re.search(rf"\b{name}\b\s*=", src), f"the radius curve constant {name} must be named in map.js"


def test_the_per_type_radius_split_is_gone():
    """Uniform site dot size (owner, 2026-08-19). The per-type bases are REMOVED, not merely equalised: a
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


def test_badge_declutter_source_shape():
    """Badge collision declutter (owner, 2026-08-19): SOURCE-SHAPE pins, and ONLY source shape.

    SCOPE CORRECTED after the gate review (2026-08-19). An earlier version of this test claimed it would
    fail if "the render path stops running the declutter", or if "the tail stops running from the displaced
    position back to the TRUE centroid". It would not, and the gate proved it: neutering _badgeLayout to
    return true centroids with no tails, and disabling the tail draw with `if(false&&at.tail)`, each left
    this file AND the node driver fully green. A textual scan can see that a call is WRITTEN; it can never
    see that the result is USED. The docstring was making a claim the assertions did not support, which is
    the failure mode this repo treats as worse than no test at all.

    Those behavioural claims now belong to tools/map_badges_test.js, which drives the real renderBadges
    against a recording Leaflet stub with genuine Web Mercator project/unproject, and asserts on what
    actually reached the layer: marker positions equal to the DECLUTTERED pixels (not the centroids), one
    leader per displaced badge, each ending at its true centroid, tail before marker. Both gate mutations
    fail there with 12 assertions each.

    FAILS IF, and only if, the named pieces go missing from the source: declutterBadges deleted, the layout
    pass no longer feeding it the badge list, renderBadges no longer calling _badgeLayout, or the leader
    polyline losing interactive:false or its literal endpoint expression. COMMENT-STRIPPED, because the
    narration above renderBadges contains these very words and a raw scan would pass on the prose alone."""
    src = _map_src()
    code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("//"))
    flat = code.replace(" ", "")
    assert "functiondeclutterBadges(" in flat, "map.js must define declutterBadges"
    assert "declutterBadges(list.map(" in flat, "the layout pass must feed the badge list to declutterBadges"
    assert re.search(r"function\s+renderBadges\s*\([^)]*\)\s*\{[^}]*_badgeLayout\s*\(", code), \
        "renderBadges must call _badgeLayout, or badges would render un-decluttered at their centroids"
    assert "L.polyline(at.tail" in flat, "the leader tail must be drawn as a polyline from the layout"
    # SCOPED to the polyline's OWN option bag. A bare `"interactive:false" in src` was vacuous: the survey
    # footprint polygon and the geoJSON overlay each carry one too, so the pin passed with the tail's flag
    # deleted. (Found by the control battery, which is the second time this file has caught itself.)
    assert re.search(r"L\.polyline\(at\.tail\s*,\s*\{[^}]*interactive:\s*false", code), \
        "the leader tail polyline must itself set interactive:false, or it will intercept clicks meant " \
        "for the badge it points at or for the map background (which closes the drawer)"
    # The tail runs displaced -> true centroid, in that order. Since the leaders moved above every badge
    # (owner, 2026-08-19) the START is trimmed to the badge rim, so the first vertex is `from` rather than
    # the displaced lat/lng literally - but `from` still STARTS at the displaced position and is only ever
    # walked TOWARD the centroid. The end vertex is unchanged and is the claim the feature exists to keep.
    # The geometry itself (start on the rim, never past the centroid) is behavioural and is pinned in the
    # driver's render section, which measures it in pixels.
    assert re.search(r"tail:\s*\[\s*from\s*,\s*\[\s*b\.lat\s*,\s*b\.lon\s*\]\s*\]", code), \
        "the leader tail must run from the badge back to the survey's TRUE centroid"
    assert re.search(r"let\s+from\s*=\s*\[\s*ll\.lat\s*,\s*ll\.lng\s*\]", code), \
        "the tail start must DEFAULT to the displaced badge position, so a failed trim degrades to the " \
        "un-trimmed leader rather than to no leader or to a wrong one"


@pytest.mark.parametrize("name,value", [("BADGE_GAP_PX", "4"),
                                        ("BADGE_MAX_SHIFT_PX", "88"),
                                        ("BADGE_TAIL_MIN_PX", "2")])
def test_declutter_constants_are_named_with_the_stated_values(name, value):
    """The declutter's three geometry decisions are stated numbers, not literals buried in the loop. The
    travel cap especially: it is the point where the design ACCEPTS overlap rather than moving a badge
    further from its survey, so it has to be visible to a reader and changeable only on purpose."""
    m = re.search(rf"const\s+{name}\s*=\s*(\d+)\s*[;,]", _map_src())
    assert m, f"map.js must define `const {name} = <n>;`"
    assert m.group(1) == value, (
        f"{name} must be {value}; found {m.group(1)}. Change it only deliberately, and change this pin in "
        f"the same commit so the decision stays written down.")


def test_decoration_panes_are_created_pointer_dead():
    """PRODUCTION REGRESSION (2026-08-19): no station on the deployed map could be opened, and only two of
    thirteen survey badges answered a click.

    CAUSE, measured in a real browser against the live corpus: the per-survey panes sit at z-index 600 and
    used to hold only divIcon badges. The declutter lane added leader tails as L.polyline, and adding an
    L.Path to a pane makes Leaflet build a CANVAS RENDERER inside it - a full-map-size <canvas> with the
    default pointer-events:auto. Station dots are circleMarkers on the default canvas in overlayPane at
    z-index 400, so ten such canvases ended up over the station canvas. Every click was captured by the
    topmost survey canvas, hit-tested against that survey's own non-interactive layers, and stopped there.

    This pins the FIX AT ITS PLACEMENT: pane creation, not a stylesheet rule keyed on the generated pane
    class (which is one rename from lapsing silently). FAILS IF the pointer rule is dropped from the pane
    factory, if a pane is created outside that factory, or if the z-order it relies on stops being named.
    What it cannot prove is the browser behaviour itself - that a pointer now reaches the station canvas is
    a real-browser fact, measured and reported by the lane, not asserted here."""
    src = _map_src()
    code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("//"))
    flat = code.replace(" ", "")
    assert re.search(r"function\s+_makeDecorationPane\s*\(", code), \
        "map.js must funnel decoration-pane creation through _makeDecorationPane, so the pointer rule has " \
        "exactly one place to live"
    assert 'p.style.pointerEvents="none"' in flat, \
        "a decoration pane must be created pointer-dead: its canvas renderer would otherwise swallow every " \
        "click meant for the station layer beneath it"
    # createPane must not be called anywhere else: a second call site is a pane without the rule.
    assert code.count("map.createPane(") == 1, (
        f"map.createPane must be called ONLY inside _makeDecorationPane (found "
        f"{code.count('map.createPane(')} call sites); a pane created elsewhere carries no pointer rule")
    for name in ("SURV_PANE_Z", "BADGE_TAIL_PANE_Z"):
        assert re.search(rf"const\s+{name}\s*=\s*(\d+)\s*[;,]", src), \
            f"{name} must be a named constant: the whole defect was a z-order relationship nobody had written down"


def test_the_pane_guard_is_wired_to_layeradd():
    """The guard that stops the regression coming back. A future edit that adds an interactive Path to a
    decoration pane rebuilds the same blinding canvas, so the invariant is checked at runtime rather than
    trusted. FAILS IF the guard stops being wired to the map event that sees every layer, or if the check
    stops reading the pane REGISTRY (pattern-matching a pane name instead would drift with the name)."""
    src = _map_src()
    code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("//"))
    assert re.search(r'map\.on\(\s*"layeradd"\s*,', code), \
        'the pane guard must be wired to map.on("layeradd"), the one event every layer passes through ' \
        "(a LayerGroup on the map delegates its adds to Map.addLayer)"
    assert re.search(r"function\s+_decorationPaneViolation\s*\(", code), \
        "the guard decision must be a named pure function, so it is testable without Leaflet or a DOM"
    assert "_decorationPanes.has(" in code, \
        "the guard must consult the pane REGISTRY the factory writes, not a pattern over pane names"


def test_leader_tails_ride_one_pane_above_every_badge():
    """OWNER (2026-08-19), on the SA pile-up: "what about the arrow type pointers for the clusters? they
    should really be on top, not underneath some clusters." A leader used to be created into its own
    survey's pane, so whether it painted above another survey's badge depended on the order those surveys
    first reached the router. ONE tail pane above every badge pane makes it structural.

    FAILS IF a leader goes back into a survey pane, or if the tail pane stops sitting above the badge panes.
    The pairwise invariant itself (for any two badges, a leader paints above both) is asserted in the driver
    against what actually reached the layer."""
    src = _map_src()
    code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("//"))
    assert re.search(r"L\.polyline\(at\.tail\s*,\s*\{\s*pane:\s*_badgeTailPane\(\)", code), \
        "the leader must be created into the dedicated tail pane, never into _survPaneFor(...) again"
    zs = {n: int(re.search(rf"const\s+{n}\s*=\s*(\d+)\s*[;,]", src).group(1))
          for n in ("SURV_PANE_Z", "BADGE_TAIL_PANE_Z")}
    assert zs["BADGE_TAIL_PANE_Z"] > zs["SURV_PANE_Z"], (
        f"the tail pane z ({zs['BADGE_TAIL_PANE_Z']}) must be ABOVE every badge pane z "
        f"({zs['SURV_PANE_Z']}) - that ordering IS the owner requirement")
    # Leaving the survey pane costs the tails the pane-inherited focus dim, so the dim must be re-applied
    # per tail. Without this the "View on map" focus would leave every leader at full strength.
    assert re.search(r"function\s+tailOpacityFor\s*\(", code), \
        "the tails no longer inherit the pane dim, so a per-tail opacity rule must exist"
    assert re.search(r"_badgeTails\.forEach\s*\(", code), \
        "applySurveyDim must walk the tail registry, or a focus change with no re-render leaves leaders undimmed"


def test_badge_circles_shrank_but_the_label_did_not():
    """OWNER (2026-08-19): "make the cluster circles 10% smaller, the text inside can stay the same size."

    Two separate authorities, which is what makes this expressible at all: badgeSizePx sizes the DISC (it
    feeds the divIcon iconSize), and the LABEL size is a CSS font-size on .ausmt-badge.svbadge-* in
    index.html. FAILS IF the scale is not the ruled 0.90, if the disc ramp is re-inlined as three new
    numbers, or if a badge font-size moves with it."""
    src = _map_src()
    m = re.search(r"const\s+BADGE_SIZE_SCALE\s*=\s*([\d.]+)\s*[;,]", src)
    assert m, "map.js must define `const BADGE_SIZE_SCALE = <n>;` (the owner's 10% reduction, named not baked in)"
    assert float(m.group(1)) == 0.90, (
        f"BADGE_SIZE_SCALE must be 0.90 (circles 10% smaller); found {m.group(1)}. Change it only with the "
        f"owner's ruling, and change this pin in the same commit.")
    assert "(n<10?34:n<100?42:52)*BADGE_SIZE_SCALE" in src.replace(" ", ""), \
        "the disc ramp must stay the 34/42/52 base times the named scale, so the reduction reads as a " \
        "reduction rather than as three new magic numbers"
    # The LABEL is the half the owner said not to touch. These are the shipped font sizes; they must not
    # move with the circle.
    html = INDEX.read_text(encoding="utf-8")
    for cls, size in (("svbadge-small", "12px"), ("svbadge-medium", "13px"), ("svbadge-large", "14px")):
        assert re.search(rf"\.ausmt-badge\.{cls} div\{{[^}}]*font-size:{size}", html), (
            f"the {cls} label must stay at {size}: the owner shrank the CIRCLE and said the text stays the "
            f"same size, so a font change here is out of contract")


# ------------------------------------------------------------- behaviour pins

@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_badge_rule_and_router_behaviour():
    r = subprocess.run(["node", str(DRIVER)], cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8")
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode == 0, f"badge driver failed:\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
    assert "MAP BADGES OK" in out, out
