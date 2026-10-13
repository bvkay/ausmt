"""The AuScope and NCRIS lock-up as a watermark in the SPA map's bottom-right corner.

WHY THE MAP CARRIES IT. The map is the surface people screenshot into talks and reports, and a
screenshot of the map carries no header and no footer with it. A corner lock-up is attribution that
travels with the image, naming both AuScope and NCRIS. It is the map page's one lock-up: the header
opens with the AuScope mark, and the map page's footer carries its live counts alone.

TWO VARIANTS, ONE SHOWN. The lock-up ships as the brand kit's colour PNG for the light basemap and its
white PNG for the dark one, and the theme switch shows exactly one: the white file sits only on a dark
ground. They are the same files the footers draw (portal/vendor/README.md records their digests).

THE STYLE GUIDE'S RULES, APPLIED AS NUMBERS (AuScope Style Guide, Identity):
  * CLEAR SPACE. The guide asks for breathing space of at least the full height of the logo on all
    sides. The lock-up is 44px tall, so its inset is 44px from the map's bottom and right edges, and
    the corner holds nothing else: the collapsed attribution control sits in the top-right corner for
    exactly that reason (tests/test_map_attribution.py) and the legend sits bottom-left.
  * OPACITY, AND NOTHING ELSE. The lock-up renders at 80 per cent opacity, opacity:.8 exactly, and in
    its own colours: opacity is the one change permitted on it, so both files keep the bytes the brand
    kit published. FAILS here if the opacity drifts from .8 or is declared twice, or if a filter, a
    blend or any other rule that recolours the lock-up is introduced.
  * MINIMUM SIZE. The guide states none, so the lock-up's height is the 44px the corner was
    specified at, the width following the artwork.

THE LEGEND MEETS IT ON A NARROW MAP. The lock-up is about 260px wide, so with its 44px of clear space
it needs about 348px of map beside the legend's corner. Measured in Chrome with the rail open, the
expanded legend overlaps the lock-up's left end from 761px to about 852px of viewport, and the 44px of
clear space against the legend holds from about 897px. The legend stacks above the lock-up there, so
it stays readable, and that stacking order is pinned below. Below 760px the legend collapses to its
toggle and clears the lock-up; below 560px the lock-up is not drawn.

IT CANNOT INTERCEPT ANYTHING. pointer-events:none takes it out of hit testing entirely, which is the
assertion that actually protects a zoom, a draw, a popup and the tour; the z-index is held below
Leaflet's control and popup layers as well, so a stacking regression cannot put a brand image over a
control the reader is trying to press.

THE COLOUR ICON PNG the corner once drew stays committed, byte for byte, and no surface names it; the
AuScope mark pair is the header's and the collection figures', and the map's corner names neither.
"""
import hashlib
import re
from pathlib import Path

from chrome_contract import LOCKUP_DARK, LOCKUP_LIGHT, MAP_LOCKUP, MARK_DARK, MARK_LIGHT

ROOT = Path(__file__).resolve().parent.parent          # portal/
INDEX = ROOT / "index.html"
PAGES_PY = ROOT.parent / "engine" / "extract" / "_pages.py"
DRAWER = ROOT / "src" / "drawer.js"
VENDOR_README = ROOT / "vendor" / "README.md"
LEAFLET_CSS = ROOT / "vendor" / "leaflet.css"

# The colour PNG the corner once drew. It stays committed as the brand kit published it.
PNG_SRC = "/vendor/auscope-icon-colour.png"
PNG_ASSET = ROOT / "vendor" / "auscope-icon-colour.png"
PNG_SHA256 = "edfe057070656636011977270e4d4ba60461937add2f36048626e161c81aa132"
PNG_BYTES = 7392
PNG_PIXELS = (281, 288)

# The placement, as one literal. 44px is the lock-up's height AND its inset, which is the guide's
# clear space expressed as a number on the two sides that have an edge near it.
HEIGHT = 44
PLACEMENT = ("position:absolute;right:44px;bottom:44px;height:44px;width:auto;"
             "z-index:500;pointer-events:none")
# The one change permitted on the lock-up, and its value: 80 per cent, written as the shortest literal.
OPACITY = "opacity:.8"
# The whole rule, placement then opacity, as index.html declares it.
RULE = f".maplock{{{PLACEMENT};{OPACITY}}}"
# What may never touch the lock-up: anything that recolours it rather than fading it.
NEVER = ("filter", "mix-blend-mode", "background-blend-mode", "mask", "isolation", "color-scheme")
# Below the footer's own breakpoint the map is a phone-width strip and a corner lock-up costs more map
# than it buys attribution, so it is not drawn at all. The id is what lets the rule outrank the theme
# switch's display:block on the dark variant.
NARROW = "@media(max-width:900px){#map .maplock{display:none}}"
# The class the corner's mark pair carried. It is retired from every surface.
RETIRED_CLASS = "mapmark"

# Every portal document that is not index.html. The watermark is index-only, and a new page copying
# the map block is exactly how it would spread.
OTHER_PAGES = ("about.html", "add-survey.html", "brand.html", "releases.html", "404.html")


def _text(p):
    return p.read_text(encoding="utf-8")


def test_the_map_carries_the_lockup_pair_once_and_nothing_else_inside_its_container():
    """FAILS IF index.html loses either variant, carries the pair twice, draws it outside the Leaflet
    map container, or puts anything else in the container's markup, the AuScope mark pair included.
    The container assertion is positional: the pair must BE the container's content, which is the only
    place a screenshot of the map includes."""
    text = _text(INDEX)
    assert text.count(MAP_LOCKUP) == 1, (
        f"index.html must carry the map watermark exactly once, as {MAP_LOCKUP!r}; "
        f"found {text.count(MAP_LOCKUP)}")
    m = re.search(r'<div id="map">(.*?)</div>', text, re.S)
    assert m, "index.html must carry the Leaflet map container"
    assert m.group(1) == MAP_LOCKUP, (
        f"the map container carries the lock-up pair and nothing else: {m.group(1)[:300]!r}")
    for src in (MARK_LIGHT, MARK_DARK):
        assert src not in m.group(1), f"the map's corner draws the lock-up, not the mark {src}"
    for src in (LOCKUP_LIGHT, LOCKUP_DARK):
        asset = ROOT / src.lstrip("/")
        assert asset.is_file(), f"the watermark names {src}, which the portal does not ship"
        assert asset.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", f"{src} must be the brand kit's PNG"


def test_the_lockup_is_not_a_link_and_names_both_organisations_in_its_alt_text():
    """FAILS IF the lock-up is wrapped in an anchor. The footers link AuScope, and a link inside the
    map takes a tab stop in the middle of the application's primary surface and can be dragged into a
    navigation by a mis-aimed pan. The alt text is the attribution for a reader who cannot see it, so
    each variant names both organisations the artwork carries."""
    text = _text(INDEX)
    before = text[:text.index(MAP_LOCKUP)]
    open_anchors = before.count("<a ") - before.count("</a>")
    assert open_anchors == 0, (
        f"the watermark must not sit inside an anchor; {open_anchors} anchor(s) are open at it")
    assert MAP_LOCKUP.count('alt="AuScope and NCRIS"') == 2 and 'alt=""' not in MAP_LOCKUP, (
        "the lock-up is attribution, so each variant's alt text names both organisations")


def test_the_placement_honours_the_style_guide_clear_space_and_intercepts_nothing():
    """The geometry, as one literal, and the reasons it is those numbers.

    FAILS IF the lock-up leaves the bottom-right corner, if its height leaves the specified 44px, if
    the inset drops below one logo height (the guide's clear space), if the width stops following the
    artwork, if pointer-events:none goes, or if the narrow-width rule that hides both variants below
    560px goes."""
    text = _text(INDEX)
    assert text.count(RULE) == 1, f"the watermark must carry the shared placement, as {RULE!r}"
    assert "top:" not in PLACEMENT and "left:" not in PLACEMENT, "the lock-up sits in the bottom-right corner"
    assert NARROW in text, "the lock-up must not be drawn below the 560px breakpoint the footer uses"
    container = re.search(r"#map\{([^}]*)\}", text)
    assert container and "position:relative" in container.group(1), (
        "the map container must establish the positioning context; without it the absolutely "
        f"positioned lock-up escapes to the nearest positioned ancestor: "
        f"{container.group(0) if container else None!r}")
    height = int(re.search(r"height:(\d+)px", PLACEMENT).group(1))
    assert height == HEIGHT, f"the lock-up is drawn {HEIGHT}px tall, got {height}px"
    assert "width:auto" in PLACEMENT, "the width follows the artwork's own proportion"
    for edge in ("bottom", "right"):
        inset = int(re.search(edge + r":(\d+)px", PLACEMENT).group(1))
        assert inset >= height, (
            f"the style guide asks for at least the full height of the logo of clear space on all "
            f"sides; the {edge} inset is {inset}px against a {height}px lock-up")


def test_nothing_else_is_placed_in_the_lockups_corner():
    """The clear space holds nothing. FAILS IF the attribution control is mounted anywhere but
    Leaflet's top-right corner, if the legend leaves the bottom-left, or if the legend stops stacking
    above the lock-up: where a narrow map brings the two together, the legend must stay readable."""
    attrib = _text(ROOT / "src" / "mapattrib.js")
    assert 'position: "topright"' in attrib, "the attribution control is mounted top-right"
    legend = re.search(r"\.maplegend\{([^}]*)\}", _text(INDEX))
    assert legend and "left:10px" in legend.group(1) and "bottom:10px" in legend.group(1), (
        "the legend sits bottom-left, clear of the lock-up's corner")
    assert "right:" not in legend.group(1), "the legend must not be anchored to the right edge"
    legend_z = int(re.search(r"z-index:(\d+)", legend.group(1)).group(1))
    lockup_z = int(re.search(r"z-index:(\d+)", PLACEMENT).group(1))
    assert legend_z > lockup_z, (
        f"the legend ({legend_z}) must stack above the lock-up ({lockup_z}) where a narrow map "
        "brings them together")


def _rules_selecting_the_lockup(text):
    """Every rule in index.html's stylesheets whose selector names the watermark, as (selector, body),
    the narrow-width query's inner rule included."""
    css = "".join(re.findall(r"<style>(.*?)</style>", text, re.S))
    return [(sel.strip(), body) for sel, body in re.findall(r"([^{}]*maplock[^{}]*)\{([^{}]*)\}", css)]


def test_the_lockup_renders_at_eighty_percent_opacity_and_is_never_tinted():
    """Opacity is the one change permitted on the lock-up, and its value is .8 exactly. FAILS IF the
    .maplock rule loses the declaration, declares it twice or at any other value (1, .80 written as
    80%, .75), or if any rule that selects the watermark adds a filter, a blend, a mask or a second
    opacity: a lock-up that is faded stays the lock-up, a lock-up that is recoloured does not. FAILS
    too if either image carries an inline style, which would outrank the rule."""
    text = _text(INDEX)
    block = re.findall(r"(?m)^\s*\.maplock\{([^}]*)\}", text)
    assert len(block) == 1, f"index.html must declare the .maplock rule exactly once, found {len(block)}"
    decls = [d.strip() for d in block[0].split(";") if d.strip()]
    opacity = [d for d in decls if d.split(":", 1)[0].strip() == "opacity"]
    assert opacity == [OPACITY], (
        f"the lock-up renders at {OPACITY} and nothing else; the rule declares {opacity!r}")
    rules = _rules_selecting_the_lockup(text)
    assert len(rules) >= 2, f"the base rule and the narrow-width rule must both be read, got {rules!r}"
    for sel, body in rules:
        for banned in NEVER:
            assert banned not in body, (
                f"the lock-up keeps its own colours: {banned} is not permitted, got {sel}{{{body}}}")
        if sel != ".maplock":
            assert "opacity" not in body, (
                f"the lock-up's opacity is declared once, on .maplock; {sel} restates it: {body!r}")
    for img in re.findall(r'<img class="maplock[^>]*>', text):
        assert "style=" not in img, f"a watermark image carries an inline style: {img!r}"


def test_the_lockup_sits_below_leaflets_controls_and_popups():
    """Read from BOTH stylesheets and compared as numbers, not restated as literals. FAILS IF the
    lock-up's z-index reaches Leaflet's control layer or its popup layer: a brand image painted over a
    zoom button, a draw toolbar or an open popup is a defect a reader meets on the first click.

    pointer-events:none already makes interception impossible; this is the other half, which is what
    the reader SEES rather than what the browser hit-tests."""
    lockup = re.search(r"\.maplock\{[^}]*z-index:(\d+)", _text(INDEX))
    assert lockup, "the .maplock rule must declare a z-index"
    mine = int(lockup.group(1))
    css = _text(LEAFLET_CSS)
    layers = {}
    for sel in (r"\.leaflet-control \{[^}]*?z-index: (\d+)",
                r"\.leaflet-top,\s*\n\.leaflet-bottom \{[^}]*?z-index: (\d+)",
                r"\.leaflet-popup-pane\s*\{ z-index: (\d+); \}"):
        m = re.search(sel, css)
        assert m, f"leaflet.css must declare the layer this pin compares against: {sel!r}"
        layers[sel] = int(m.group(1))
    for sel, z in layers.items():
        assert mine < z, (
            f"the watermark's z-index ({mine}) must stay below Leaflet's own ({z}, from {sel!r})")


def test_the_watermark_class_is_the_map_pages_alone_and_no_surface_names_the_png():
    """FAILS IF another portal document starts drawing the map watermark, if the retired corner class
    comes back to any surface, or if any surface (a portal page, the engine's pages sheet or the SPA's
    collection scatter) names the colour icon PNG the corner once drew."""
    png = PNG_SRC.rsplit("/", 1)[-1]
    for name in OTHER_PAGES:
        page = _text(ROOT / name)
        assert "maplock" not in page, f"portal/{name}: the map watermark belongs to the map page alone"
        assert png not in page, f"portal/{name}: no surface names the colour PNG"
    for name in OTHER_PAGES + ("index.html",):
        assert RETIRED_CLASS not in _text(ROOT / name), f"portal/{name}: the .{RETIRED_CLASS} class is retired"
    assert png not in _text(INDEX), "index.html: the watermark is the lock-up pair, not the colour icon PNG"
    for label, path in (("engine/extract/_pages.py", PAGES_PY), ("portal/src/drawer.js", DRAWER)):
        assert png not in _text(path), f"{label}: no surface names the colour PNG"
        assert RETIRED_CLASS not in _text(path), f"{label}: the .{RETIRED_CLASS} class is retired"


def test_the_retired_png_stays_committed_byte_for_byte():
    """A trademark asset is a promise about a file, and this one stays committed though the map's
    corner draws the lock-up pair. FAILS IF it is missing, resized, re-encoded, recoloured or stripped
    of its alpha channel."""
    assert PNG_ASSET.is_file(), f"the portal keeps {PNG_SRC} committed"
    data = PNG_ASSET.read_bytes()
    assert len(data) == PNG_BYTES, (
        f"{PNG_SRC} must be the brand kit's file unchanged: {PNG_BYTES} B, got {len(data)}")
    assert hashlib.sha256(data).hexdigest() == PNG_SHA256, (
        f"{PNG_SRC} does not match the recorded digest; it has been re-encoded or replaced")
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{PNG_SRC} must be a PNG"
    assert data[25] == 6, f"{PNG_SRC} must keep its alpha channel (PNG colour type 6)"
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    assert (width, height) == PNG_PIXELS, (
        f"{PNG_SRC} must keep the committed resolution {PNG_PIXELS}, got {(width, height)}")


def test_the_vendor_inventory_records_the_png_beside_it():
    """The README is where an operator looks to answer "where did this file come from and is it the
    one the brand kit published". FAILS IF it stops naming the file, its source, its digest or its
    byte count, the same four facts the pin above holds against the bytes themselves."""
    readme = _text(VENDOR_README)
    assert "auscope-icon-colour.png" in readme, "portal/vendor/README.md must record the colour PNG"
    assert PNG_SHA256 in readme, "the README must record the asset's SHA-256"
    assert f"{PNG_BYTES} B" in readme, "the README must record the asset's byte count"
    assert "2025 AuScope Logo Icon - Colour.png" in readme, (
        "the README must name the brand kit file the bytes were taken from")
