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
- the radius curve stops being monotone in zoom, breaches its floor/ceiling, or stops keeping the LP
  fabric under the BB/AMT dots.
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
    for name in ("DOT_R_FLOOR", "DOT_R_CEIL", "DOT_R_SLOPE", "DOT_R_BASE_LP", "DOT_R_BASE_STD"):
        assert re.search(rf"\b{name}\b\s*=", src), f"the radius curve constant {name} must be named in map.js"


# ------------------------------------------------------------- behaviour pins

@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_badge_rule_and_router_behaviour():
    r = subprocess.run(["node", str(DRIVER)], cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8")
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode == 0, f"badge driver failed:\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
    assert "MAP BADGES OK" in out, out
