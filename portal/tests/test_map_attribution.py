"""The map's attribution: on the map, collapsed to one glyph, and following the layer that is drawn.

The corner line comes off the map. What goes is the LINE and the "Leaflet" flag beside it, which is
a courtesy to a library; what stays is the credit, because the basemap is OpenStreetMap data under
ODbL and every tile source this site can draw asks for credit of its own. It is met by Leaflet's
own attribution control, mounted with prefix:false and collapsed behind a small "(i)" that opens on
hover, on focus and on click.

WHY THE CONTROL AND NOT A LINE IN THE FOOTER. Two reasons stand behind that, and this module holds
the second:

  * the footer is the same box on seven surfaces, and a line only the SPA carried made it a
    different box there. tests/test_footer_regions.py holds that half;
  * a fixed line of prose cannot follow the tile source. src/map.js keeps a CARTO fallback for the
    case where the pmtiles files are absent or the renderer fails to load, so a footer naming
    Protomaps would credit the wrong provider whenever that branch ran. Leaflet's control reads each
    LAYER's own attribution, so the credit is whatever is actually drawing the map. That is the
    property this module exists to hold, and it is asserted per layer rather than as one string.

THE TWO SURFACES THAT DRAW MAPS ARE HELD TOGETHER. portal/index.html draws one and
portal/add-survey.html draws three, and all four wear the same control from the same module, with
the same rules declared character for character on both documents. A collapsed control on one
surface and a Leaflet-flagged line on the other would be two answers to one rule.

WHAT THIS MODULE CANNOT SEE, stated rather than implied: it reads source. Whether the glyph is
actually one glyph wide, whether the expanded text clears the legend, and whether a click really
opens it are DOM and browser facts. The DOM half is driven headlessly: tools/interaction_test.js
drives the SPA's control in the real document it builds, and tools/map_attribution_test.js drives
all three of add-survey's. The pixel half is a browser measurement, recorded with the round's
screenshots.

The rule: LANE-CONTRACT-ABOUT-PAGE.md.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent          # portal/
MODULE = ROOT / "src" / "mapattrib.js"
MAP_JS = ROOT / "src" / "map.js"
DRIVER = ROOT / "tools" / "map_attribution_test.js"

# The one spelling every outbound anchor on this site carries. Held as one literal so the credit's
# links cannot drift into a second spelling of the same intent.
_NEW_TAB = 'target="_blank" rel="noopener noreferrer"'

# WHAT EACH LAYER CREDITS. The pmtiles pair and the CARTO fallback render different bytes from
# different providers, so they carry different credits and the control prints whichever is on the
# map. OpenStreetMap is in both because both are rendered from OSM data.
_OSM_LINK = "https://www.openstreetmap.org/copyright"
_PMTILES_CREDIT = "Protomaps"
_CARTO_CREDIT = "CARTO"

# The two documents that draw maps. Their control rules are compared character for character.
_MAP_PAGES = ("index.html", "add-survey.html")

# The rule set that styles the control. Named selectors rather than a blob, so a missing rule fails
# by name and a surface cannot satisfy the comparison by declaring nothing at all.
_RULE_SET = (".mapattrib", ".mapattrib-toggle", ".mapattrib-toggle:hover",
             ".mapattrib-toggle:focus-visible", ".mapattrib .leaflet-control-attribution",
             ".mapattrib .leaflet-control-attribution a",
             ".mapattrib.mapattrib-open .leaflet-control-attribution")


def _text(path):
    return path.read_text(encoding="utf-8")


def _rules(where, text):
    """{selector: declarations} for the control's rule set, each required exactly once.

    Brace-matched from the selector's own line so a declaration block containing a nested rule (none
    do today) could not silently truncate, and a SECOND declaration of a selector fails here rather
    than quietly overriding the first at equal specificity."""
    out = {}
    for sel in _RULE_SET:
        hits = re.findall(r"(?m)^\s*" + re.escape(sel) + r"\{([^}]*)\}", text)
        assert len(hits) == 1, (
            f"{where}: the control's rule set declares {sel} exactly once; found {len(hits)}")
        out[sel] = " ".join(hits[0].split())
    return out


def test_one_module_builds_the_collapsed_control_for_every_map_this_site_draws():
    """ONE IMPLEMENTATION, four maps. src/mapattrib.js is the only place the control is built and
    the only place the toggle is assembled, and both documents that draw maps load it.

    WHY A WRAPPER AND NOT THE CONTROL'S OWN CONTAINER, asserted rather than commented: Leaflet
    rewrites the attribution container's innerHTML on every attribution update, which is every time
    a layer is added or removed, so a button placed inside it is discarded the next time a layer
    changes. The module must therefore never write into that container.

    FAILS if the module goes, if either document stops loading it, if a document grows a second
    implementation of the toggle, or if the module starts writing into Leaflet's own container."""
    assert MODULE.exists(), "src/mapattrib.js builds the collapsed control for every map this site draws"
    src = _text(MODULE)
    assert "prefix: false" in src or "prefix:false" in src, (
        "the control is mounted with prefix:false: the Leaflet flag and word are a courtesy to a "
        "library, not a licence term, and they stay off the map")
    assert not re.search(r"\bel\.innerHTML|container\.innerHTML", src), (
        "the module must not write into Leaflet's attribution container: Leaflet rewrites that "
        "container's innerHTML on every attribution update, so anything put inside it is lost the "
        "next time a layer is added or removed. The toggle goes in a wrapper around it")
    for name in _MAP_PAGES:
        page = _text(ROOT / name)
        assert 'src="src/mapattrib.js"' in page, (
            f"{name}: this document draws a map, so it loads the module that collapses its "
            f"attribution")
        assert "mapattrib-toggle" not in re.sub(r"<style>.*?</style>", "", page, flags=re.S), (
            f"{name}: the toggle is assembled in src/mapattrib.js and styled here; a second "
            f"assembly is a second answer to one question")


def test_the_toggle_is_a_real_button_a_keyboard_can_reach():
    """KEYBOARD-REACHABLE, and announced. The glyph is a <button> with an explicit type, an
    aria-label (its text is one letter and says nothing on its own) and an aria-expanded that
    tracks the state, so a reader who cannot hover reaches the credit on the same terms as one who
    can.

    FAILS if the glyph becomes a div or a span, if it loses its label, or if aria-expanded stops
    being written on both states."""
    src = _text(MODULE)
    assert 'createElement("button")' in src, (
        "the glyph is a real button: a div takes no focus, fires on no key and is announced as "
        "nothing")
    assert 'btn.type = "button"' in src or 'type="button"' in src, (
        "the button states its type, so it can never submit a form it is placed inside")
    assert 'setAttribute("aria-label"' in src, (
        "the glyph's text is one letter; the label is what says what it opens")
    assert src.count('setAttribute("aria-expanded"') >= 2, (
        "aria-expanded is written on construction and on every change; one write is a state that "
        "goes stale the first time the control opens")
    assert '"pointerdown"' in src, (
        "a click toggles from the state the POINTER found: a mouse click arrives after the hover "
        "that already opened the control, and a tap arrives after the focus that did, so a toggle "
        "reading the state at click time closes what the pointer just opened and makes a tap do "
        "nothing at all")
    for event in ("pointerdown", "click", "mouseenter", "mouseleave", "focusin", "focusout"):
        assert f'"{event}"' in src, (
            f"the control opens on hover, on focus and on click and closes the same three ways; "
            f"no {event} handler")


def test_the_spa_map_mounts_the_collapsed_control_and_credits_the_layer_it_draws():
    """THE SPA. The map is created with Leaflet's own control switched off, because the one Leaflet
    mounts by default carries the flag and the word; the collapsed control is mounted explicitly in
    its place with prefix:false.

    THE CREDIT IS THE LAYER'S, which is the whole point of the control. The pmtiles pair credits
    OpenStreetMap and Protomaps; the CARTO fallback credits OpenStreetMap and CARTO. A deployment
    that flips basemap.provider now credits what it draws, which the footer line it replaces could
    not do.

    FAILS if the control stops being mounted, if a layer stops stating its own credit, if a credit
    names the wrong provider, or if a credit link stops opening in the one spelling this site
    uses."""
    src = _text(MAP_JS)
    assert re.search(r'L\.map\("map",\s*\{[^}]*attributionControl:\s*false', src), (
        "the map is created with attributionControl:false: Leaflet's default control carries the "
        "flag and the word that stay off the map")
    assert "AusmtMapAttrib.mount(" in src, (
        "the SPA mounts the collapsed control in place of the default one")
    attributions = re.findall(r"attribution:\s*([A-Za-z_0-9]+|\"[^\"]*\")", src)
    assert len(attributions) >= 2, (
        f"both basemap branches state a credit of their own, found {attributions}")
    pmtiles = src.split("if(_bmCfg.provider===")[1].split("}else{")[0]
    carto = src.split("}else{")[1].split("\n}", 1)[0]
    assert "attribution:" in pmtiles and _PMTILES_CREDIT in src, (
        "the pmtiles layers credit OpenStreetMap and Protomaps")
    assert "attribution:" in carto, (
        "the CARTO fallback states its OWN credit; it is the branch a footer line naming Protomaps "
        "would have mis-credited")
    credits = dict(re.findall(r"(?m)^const (_[A-Z_]+CREDIT)\s*=\s*(.+);\s*$", src))
    assert set(credits) >= {"_OSM_CREDIT", "_PM_CREDIT", "_CARTO_CREDIT"}, (
        f"the credits are named constants, so the OpenStreetMap half is stated once and each "
        f"provider adds its own to it; found {sorted(credits)}")
    joined = " ".join(credits.values())
    assert _OSM_LINK in joined, "every credit links OpenStreetMap's copyright page"
    assert _PMTILES_CREDIT in joined and _CARTO_CREDIT in joined, (
        f"both providers are credited by name: {credits}")
    assert "Leaflet" not in joined, (
        "the Leaflet prefix goes with the flag; it is a courtesy to a library, not a licence term")
    for tag in re.findall(r"<a [^>]*>", joined):
        assert _NEW_TAB in tag, (
            f"a credit link leaves the site, so it opens in a new tab and hands it no opener; "
            f"expected {_NEW_TAB!r} in {tag!r}")


def test_the_dormant_user_layer_path_still_guards_and_still_escapes():
    """THE OTHER HALF OF THE PIN THIS MODULE INHERITED. userLayer() feeds a fetched GeoJSON's source
    field to addAttribution, which Leaflet renders as HTML, so that string is escaped; and the call
    is guarded on a control existing, because a document that failed to load src/mapattrib.js draws
    a map with no control and a layer added there must degrade rather than throw.

    THE PATH IS DORMANT: the layer control below it is built but never added to the map, so the
    fetch never runs today. The guard and the escaping are pinned anyway, and the escaping is
    DRIVEN through a stub by tests/test_url_guard.py, precisely so a later change that re-enables the
    control cannot re-open the sink by omission.

    FAILS if the guard goes, or if the source reaches addAttribution unescaped."""
    src = _text(MAP_JS)
    assert re.search(r"&&\s*map\.attributionControl\b", src), (
        "the user-layer path must guard the control it reaches: a document that failed to load the "
        "module has no control, and a layer added there must degrade rather than throw")
    assert re.search(r"function _layerAttribution\([^)]*\)\s*\{\s*return esc\(", src), (
        "the layer name and its fetched source both reach addAttribution ESCAPED; Leaflet renders "
        "an attribution as HTML")


def test_add_surveys_three_maps_all_wear_the_control_and_keep_their_own_credit():
    """ADD-SURVEY DRAWS THREE MAPS and every one of them wears the same control: the footprint
    picker, the station preview that plots files as they land, and the confirmation map.

    THEIR CREDIT IS THEIR OWN and is unchanged: those three draw raster tiles from OpenStreetMap
    directly, so "(c) OpenStreetMap contributors" is what they carry and what the control prints.

    FAILS if a map is added or removed without this pin being taught about it, if any of them
    leaves Leaflet's default control on (which would print the flag and the word), if one of them
    stops mounting the collapsed control, or if a tile layer drops its credit."""
    page = _text(ROOT / "add-survey.html")
    maps = re.findall(r'L\.map\("([a-z0-9]+)",\s*\{([^}]*)\}', page)
    assert len(maps) == 3, (
        f"add-survey.html draws three maps (the picker, the station preview and the confirmation "
        f"map); found {len(maps)}: {[m[0] for m in maps]}")
    for name, opts in maps:
        assert "attributionControl:false" in opts.replace(" ", ""), (
            f"add-survey.html #{name}: Leaflet's default control carries the flag and the word; "
            f"the map is created without one, got {opts!r}")
    assert page.count("AusmtMapAttrib.mount(") == 3, (
        "each of the three maps mounts the collapsed control; a map without one is the corner "
        "line this control replaces")
    tiles = re.findall(r"L\.tileLayer\((.*?)\)\.addTo", page, re.S)
    assert len(tiles) == 3, f"three tile layers, one per map; found {len(tiles)}"
    for tile in tiles:
        assert "attribution:" in tile and "OpenStreetMap contributors" in tile, (
            f"a tile layer states the credit the control prints: {tile!r}")


def test_both_map_documents_declare_the_one_control_rule_set():
    """ONE RULE SET on both documents that draw maps, character for character. The SPA's map and
    add-survey's three are the same control and must look and behave the same; two copies that
    drift are how the footer's seven surfaces drifted before the rule that this module exists to
    carry out.

    THE COLLAPSED STATE IS THE DEFAULT, asserted rather than assumed: the credit is hidden by the
    base rule and revealed by the open state's rule, so a document that failed to load the module
    shows the glyph and nothing else rather than the line that came off the map.

    FAILS if either document's rule set drifts by a character, if a rule is declared twice, if the
    collapsed state stops hiding the text, or if the open state stops showing it."""
    sets = {name: _rules(name, _text(ROOT / name)) for name in _MAP_PAGES}
    master = sets["index.html"]
    for name, got in sets.items():
        for sel in _RULE_SET:
            assert got[sel] == master[sel], (
                f"{name}: {sel} must be portal/index.html's rule, character for character.\n"
                f"  master: {master[sel]!r}\n  {name}: {got[sel]!r}")
    assert "display:none" in master[".mapattrib .leaflet-control-attribution"], (
        "the credit is hidden until it is asked for; that is what collapsed means")
    assert "display:block" in master[".mapattrib.mapattrib-open .leaflet-control-attribution"], (
        "the open state is what shows the credit, so the base rule can stay a negative")
    assert "max-width" in master[".mapattrib .leaflet-control-attribution"], (
        "the expanded text is capped, so at the narrowest width the map is drawn it cannot reach "
        "the legend in the opposite corner")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_add_survey_maps_are_driven():
    """THE DRIVEN HALF for add-survey: all three maps built in a real DOM, each control found,
    measured collapsed, opened by click and by keyboard focus, and read for what it credits.

    Source pins cannot see any of that. Exit 2 is the jsdom dev-dependency being absent, which is a
    SKIP rather than a failure, exactly as the other node drivers here treat it."""
    assert DRIVER.exists(), "tools/map_attribution_test.js drives add-survey's three maps"
    r = subprocess.run(["node", str(DRIVER)], capture_output=True, text=True,
                       encoding="utf-8", cwd=str(ROOT))
    out = r.stdout + r.stderr
    if r.returncode == 2:
        pytest.skip("jsdom dev-dependency not installed (run `npm ci` in portal/)")
    assert r.returncode == 0, out
    assert "ALL PASSED" in out, out
