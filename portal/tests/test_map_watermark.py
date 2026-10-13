"""The AuScope mark as a watermark in the SPA map's bottom-right corner.

WHY THE MAP CARRIES IT AS WELL AS THE HEADER. The map is the surface people screenshot into talks and
reports, and a screenshot of the map carries no header and no footer with it. A corner mark is
attribution that travels with the image.

TWO VARIANTS, ONE SHOWN. The mark ships in Royal Blue for the light basemap and in white for the dark
one, and the theme switch shows exactly one: the white mark sits only on a dark ground. The files are
the AuScope brand kit's vector icon in portal/vendor/auscope/, with the fills the kit states
(portal/vendor/auscope/PROVENANCE.md).

THE STYLE GUIDE'S RULES, APPLIED AS NUMBERS (AuScope Style Guide, Identity):
  * CLEAR SPACE. The guide asks for breathing space of at least the full height of the logo on all
    sides. The mark is 48px tall, so its inset is 48px from the map's bottom and right edges, and the
    corner holds nothing else: the collapsed attribution control moved to the top-right corner for
    exactly that reason (tests/test_map_attribution.py) and the legend sits bottom-left.
  * OPACITY AND TINTING. The guide sets no rule permitting either, so the mark renders at full opacity
    and in its own colours. FAILS here if an opacity, a filter or a blend is introduced.
  * MINIMUM SIZE. The guide states none, so the specified 44px to 48px band stands and the mark takes
    the top of it, which is what a screenshot needs to stay legible after scaling.

IT CANNOT INTERCEPT ANYTHING. pointer-events:none takes it out of hit testing entirely, which is the
assertion that actually protects a zoom, a draw, a popup and the tour; the z-index is held below
Leaflet's control and popup layers as well, so a stacking regression cannot put a brand mark over a
control the reader is trying to press.

THE COLOUR PNG IT REPLACES stays committed, byte for byte, and no surface names it.
"""
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # portal/
INDEX = ROOT / "index.html"
PAGES_PY = ROOT.parent / "engine" / "extract" / "_pages.py"
DRAWER = ROOT / "src" / "drawer.js"
VENDOR_README = ROOT / "vendor" / "README.md"
LEAFLET_CSS = ROOT / "vendor" / "leaflet.css"

MARK_LIGHT = "/vendor/auscope/auscope-mark.svg"
MARK_DARK = "/vendor/auscope/auscope-mark-white.svg"
MARK_IMG = (f'<img class="mapmark theme-light" src="{MARK_LIGHT}" alt="AuScope" width="42" height="42">'
            f'<img class="mapmark theme-dark" src="{MARK_DARK}" alt="AuScope" width="42" height="42">')

# The colour PNG the watermark once was. It stays committed as the brand kit published it.
PNG_SRC = "/vendor/auscope-icon-colour.png"
PNG_ASSET = ROOT / "vendor" / "auscope-icon-colour.png"
PNG_SHA256 = "edfe057070656636011977270e4d4ba60461937add2f36048626e161c81aa132"
PNG_BYTES = 7392
PNG_PIXELS = (281, 288)

# The placement, as one literal. 48px is the mark's height AND its inset, which is the guide's clear
# space expressed as a number on the two sides that have an edge near it.
PLACEMENT = ("position:absolute;right:48px;bottom:48px;height:48px;width:auto;"
             "z-index:500;pointer-events:none")
# Below the footer's own breakpoint the map is a phone-width strip and a corner mark costs more map
# than it buys attribution, so it is not drawn at all. The id is what lets the rule outrank the theme
# switch's display:block on the dark variant.
NARROW = "@media(max-width:560px){#map .mapmark{display:none}}"

# Every portal document that is not index.html. The watermark is index-only, and a new page copying
# the map block is exactly how it would spread.
OTHER_PAGES = ("about.html", "add-survey.html", "brand.html", "releases.html", "404.html")


def _text(p):
    return p.read_text(encoding="utf-8")


def test_the_map_carries_the_mark_pair_once_and_nothing_else_inside_its_container():
    """FAILS IF index.html loses either variant, carries the pair twice, draws it outside the Leaflet
    map container, or puts anything else in the container's markup. The container assertion is
    positional: the pair must BE the container's content, which is the only place a screenshot of
    the map includes."""
    text = _text(INDEX)
    assert text.count(MARK_IMG) == 1, (
        f"index.html must carry the map watermark exactly once, as {MARK_IMG!r}; "
        f"found {text.count(MARK_IMG)}")
    m = re.search(r'<div id="map">(.*?)</div>', text, re.S)
    assert m, "index.html must carry the Leaflet map container"
    assert m.group(1) == MARK_IMG, (
        f"the map container carries the AuScope mark pair and nothing else: {m.group(1)[:300]!r}")
    for src in (MARK_LIGHT, MARK_DARK):
        asset = ROOT / src.lstrip("/")
        assert asset.is_file(), f"the watermark names {src}, which the portal does not ship"
        assert "<path" in _text(asset), f"{src} must be the vector mark"


def test_the_mark_is_not_a_link_and_names_the_organisation_in_its_alt_text():
    """FAILS IF the mark is wrapped in an anchor. The header already links AuScope from every page,
    and a link inside the map takes a tab stop in the middle of the application's primary surface
    and can be dragged into a navigation by a mis-aimed pan. The alt text is the attribution for a
    reader who cannot see it, so each variant names the organisation."""
    text = _text(INDEX)
    before = text[:text.index(MARK_IMG)]
    open_anchors = before.count("<a ") - before.count("</a>")
    assert open_anchors == 0, (
        f"the watermark must not sit inside an anchor; {open_anchors} anchor(s) are open at it")
    assert MARK_IMG.count('alt="AuScope"') == 2 and 'alt=""' not in MARK_IMG, (
        "the mark is attribution, so each variant's alt text names the organisation")


def test_the_placement_honours_the_style_guide_clear_space_and_intercepts_nothing():
    """The geometry, as one literal, and the reasons it is those numbers.

    FAILS IF the mark leaves the bottom-right corner, if the inset drops below one logo height (the
    guide's clear space), if the height leaves the specified 44px to 48px band, if pointer-events:none
    goes, or if the narrow-width rule that hides both variants below 560px goes."""
    text = _text(INDEX)
    assert f".mapmark{{{PLACEMENT}}}" in text, (
        f"the watermark must carry the shared placement {PLACEMENT!r}")
    assert "top:" not in PLACEMENT and "left:" not in PLACEMENT, "the mark sits in the bottom-right corner"
    assert NARROW in text, "the mark must not be drawn below the 560px breakpoint the footer uses"
    container = re.search(r"#map\{([^}]*)\}", text)
    assert container and "position:relative" in container.group(1), (
        "the map container must establish the positioning context; without it the absolutely "
        f"positioned mark escapes to the nearest positioned ancestor: "
        f"{container.group(0) if container else None!r}")
    height = int(re.search(r"height:(\d+)px", PLACEMENT).group(1))
    assert 44 <= height <= 48, f"the mark's height must sit in the declared band, got {height}px"
    for edge in ("bottom", "right"):
        inset = int(re.search(edge + r":(\d+)px", PLACEMENT).group(1))
        assert inset >= height, (
            f"the style guide asks for at least the full height of the logo of clear space on all "
            f"sides; the {edge} inset is {inset}px against a {height}px mark")


def test_nothing_else_is_placed_in_the_marks_corner():
    """The clear space holds nothing. FAILS IF the attribution control is mounted anywhere but
    Leaflet's top-right corner, or if the legend leaves the bottom-left."""
    attrib = _text(ROOT / "src" / "mapattrib.js")
    assert 'position: "topright"' in attrib, "the attribution control is mounted top-right"
    legend = re.search(r"\.maplegend\{([^}]*)\}", _text(INDEX))
    assert legend and "left:10px" in legend.group(1) and "bottom:10px" in legend.group(1), (
        "the legend sits bottom-left, clear of the mark's corner")
    assert "right:" not in legend.group(1), "the legend must not be anchored to the right edge"


def test_the_mark_renders_at_full_opacity_and_is_never_tinted():
    """The style guide sets no rule permitting an opacity or a tint on the icon, and the contract
    requires full opacity unless it does. FAILS IF an opacity, a filter or a mix-blend-mode is added to
    the mark: a faded trademark is a modified trademark, and the whole point of the mark is that it
    survives being screenshotted and rescaled."""
    text = _text(INDEX)
    block = re.search(r"\.mapmark\{[^}]*\}", text)
    assert block, "index.html must declare the .mapmark rule"
    for banned in ("opacity", "filter", "mix-blend-mode"):
        assert banned not in block.group(0), (
            f"the mark renders as committed: {banned} is not permitted by the style guide, got "
            f"{block.group(0)!r}")


def test_the_mark_sits_below_leaflets_controls_and_popups():
    """Read from BOTH stylesheets and compared as numbers, not restated as literals. FAILS IF the
    mark's z-index reaches Leaflet's control layer or its popup layer: a brand mark painted over a
    zoom button, a draw toolbar or an open popup is a defect a reader meets on the first click.

    pointer-events:none already makes interception impossible; this is the other half, which is what
    the reader SEES rather than what the browser hit-tests."""
    mark = re.search(r"\.mapmark\{[^}]*z-index:(\d+)", _text(INDEX))
    assert mark, "the .mapmark rule must declare a z-index"
    mine = int(mark.group(1))
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
    """FAILS IF another portal document starts drawing the map watermark, or if any surface (a portal
    page, the engine's pages sheet or the SPA's collection scatter) names the colour PNG it replaced:
    the site's marks are the vector pair."""
    png = PNG_SRC.rsplit("/", 1)[-1]
    for name in OTHER_PAGES:
        page = _text(ROOT / name)
        assert "mapmark" not in page, f"portal/{name}: the map watermark belongs to the map page alone"
        assert png not in page, f"portal/{name}: no surface names the colour PNG"
    assert png not in _text(INDEX), "index.html: the watermark is the vector pair, not the colour PNG"
    for label, path in (("engine/extract/_pages.py", PAGES_PY), ("portal/src/drawer.js", DRAWER)):
        assert png not in _text(path), f"{label}: no surface names the colour PNG"


def test_the_retired_png_stays_committed_byte_for_byte():
    """A trademark asset is a promise about a file, and this one stays committed after the vector
    pair replaced it on the map. FAILS IF it is missing, resized, re-encoded, recoloured or stripped
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
