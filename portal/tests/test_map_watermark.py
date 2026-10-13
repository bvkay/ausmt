"""The AuScope mark as a watermark in the SPA map's bottom-right corner.

WHY THE MAP CARRIES IT. The map is the surface people screenshot into talks and reports, and a
screenshot of the map carries no header and no footer with it. A corner mark is attribution that
travels with the image. It is the one place the site chrome of the map page draws the AuScope mark:
the header's identity zone carries none, and the lock-up at the header's right is the header's only
AuScope presence.

TWO VARIANTS, ONE SHOWN. The mark ships in Royal Blue for the light basemap and in white for the dark
one, and the theme switch shows exactly one: the white mark sits only on a dark ground. The files are
the AuScope brand kit's vector icon in portal/vendor/auscope/, with the fills the kit states
(portal/vendor/auscope/PROVENANCE.md).

THE STYLE GUIDE'S RULES, APPLIED AS NUMBERS (AuScope Style Guide, Identity):
  * CLEAR SPACE. The guide asks for breathing space of at least the full height of the logo on all
    sides. The mark is 48px tall, so its inset is 48px from the map's bottom and right edges, and the
    corner holds nothing else: the collapsed attribution control moved to the top-right corner for
    exactly that reason (tests/test_map_attribution.py) and the legend sits bottom-left.
  * OPACITY, AND NOTHING ELSE. The mark renders at 80 per cent opacity, opacity:.8 exactly, and in
    its own colours: opacity is the one change permitted on it, so both files of the pair keep the
    fills they were committed with. FAILS here if the opacity drifts from .8 or is declared twice, or
    if a filter, a blend or any other rule that recolours the mark is introduced.
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
# The one change permitted on the mark, and its value: 80 per cent, written as the shortest literal.
OPACITY = "opacity:.8"
# The whole rule, placement then opacity, as index.html declares it.
RULE = f".mapmark{{{PLACEMENT};{OPACITY}}}"
# What may never touch the mark: anything that recolours it rather than fading it.
NEVER = ("filter", "mix-blend-mode", "background-blend-mode", "mask", "isolation", "color-scheme")
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
    assert text.count(RULE) == 1, f"the watermark must carry the shared placement, as {RULE!r}"
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


def _rules_selecting_the_mark(text):
    """Every rule in index.html's stylesheets whose selector names the watermark, as (selector, body),
    the narrow-width query's inner rule included."""
    css = "".join(re.findall(r"<style>(.*?)</style>", text, re.S))
    return [(sel.strip(), body) for sel, body in re.findall(r"([^{}]*mapmark[^{}]*)\{([^{}]*)\}", css)]


def test_the_mark_renders_at_eighty_percent_opacity_and_is_never_tinted():
    """Opacity is the one change permitted on the mark, and its value is .8 exactly. FAILS IF the
    .mapmark rule loses the declaration, declares it twice or at any other value (1, .80 written as
    80%, .75), or if any rule that selects the watermark adds a filter, a blend, a mask or a second
    opacity: a mark that is faded stays the mark, a mark that is recoloured does not. FAILS too if
    either image carries an inline style, which would outrank the rule."""
    text = _text(INDEX)
    block = re.findall(r"(?m)^\s*\.mapmark\{([^}]*)\}", text)
    assert len(block) == 1, f"index.html must declare the .mapmark rule exactly once, found {len(block)}"
    decls = [d.strip() for d in block[0].split(";") if d.strip()]
    opacity = [d for d in decls if d.split(":", 1)[0].strip() == "opacity"]
    assert opacity == [OPACITY], (
        f"the mark renders at {OPACITY} and nothing else; the rule declares {opacity!r}")
    rules = _rules_selecting_the_mark(text)
    assert len(rules) >= 2, f"the base rule and the narrow-width rule must both be read, got {rules!r}"
    for sel, body in rules:
        for banned in NEVER:
            assert banned not in body, (
                f"the mark keeps its own colours: {banned} is not permitted, got {sel}{{{body}}}")
        if sel != ".mapmark":
            assert "opacity" not in body, (
                f"the mark's opacity is declared once, on .mapmark; {sel} restates it: {body!r}")
    for img in re.findall(r'<img class="mapmark[^>]*>', text):
        assert "style=" not in img, f"a watermark image carries an inline style: {img!r}"


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
