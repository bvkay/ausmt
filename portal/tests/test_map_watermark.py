"""The AuScope colour icon as a watermark on the SPA map, and nowhere else on the site.

WHY THE MAP AND NOT THE CHROME. The header's AuScope org-mark left every surface: the relationship
is stated in words, in the footer and in About's "Who enables AusMT" section, and a symbol repeated
in a corner said nothing either of those does not. The map is the exception the rule is, for a
reason the chrome could not give: it is the surface people screenshot into talks and reports, and a
screenshot carries no footer with it. A corner mark is attribution that travels with the image.

SCOPE, HELD FROM BOTH ENDS. One document draws it, portal/index.html, inside the Leaflet map
container. No static page, no generated page and no hub minimap does, which is asserted here rather
than assumed: the file is new, so every surface that could grow one is a surface that has never had
one, and the pins below name each of them.

THE THIRD-PARTY ASSET IS COMMITTED VERBATIM. It is a trademark file from the AuScope brand kit, so
it is never resized, re-encoded or recoloured: the bytes, the byte count, the pixel dimensions and
the alpha channel are all held, and portal/vendor/README.md carries the same facts beside the file.

THE STYLE GUIDE'S RULES, APPLIED AS NUMBERS (AuScope+Style+Guide.pdf, Identity | AuScope):
  * CLEAR SPACE. The guide asks for "'breathing space' around the logo i.e. at least the full height
    of logo, on all sides". The mark is 32px tall, so its inset is 32px from the map's top and right
    edges, which is one full logo height and not Leaflet's own 10px control inset. The guide is the
    stricter of the two and the contract says to honour it.
  * OPACITY AND TINTING. The guide sets no rule on either, so the mark renders at full opacity and
    in the committed colours. FAILS here if an opacity is introduced.
  * MINIMUM SIZE. The guide states none, so the ruled 28px to 32px band stands and the mark takes
    the top of it, which is what a screenshot needs to stay legible after scaling.

IT CANNOT INTERCEPT ANYTHING. pointer-events:none takes it out of hit testing entirely, which is
the assertion that actually protects a zoom, a draw, a popup and the tour; the z-index is held below
Leaflet's control and popup layers as well, so a stacking regression cannot put a brand mark over a
control the reader is trying to press.
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

MARK_SRC = "/vendor/auscope-icon-colour.png"
MARK_ASSET = ROOT / "vendor" / "auscope-icon-colour.png"
MARK_IMG = f'<img class="mapmark" src="{MARK_SRC}" alt="AuScope" width="31" height="32">'

# The committed bytes, from the AuScope brand kit's own file. Recorded here and in
# portal/vendor/README.md, which the last pin holds equal to these four facts.
MARK_SHA256 = "edfe057070656636011977270e4d4ba60461937add2f36048626e161c81aa132"
MARK_BYTES = 7392
MARK_PIXELS = (281, 288)

# The placement, as one literal. 32px is the mark's height AND its inset, which is the guide's clear
# space expressed as a number: one full logo height on the two sides that have an edge near it.
PLACEMENT = ("position:absolute;top:32px;right:32px;height:32px;width:auto;"
             "z-index:500;pointer-events:none")
# The footer's own breakpoint. Below it the map is a phone-width strip and a corner mark costs more
# map than it buys attribution, so it is not drawn at all rather than shrunk.
NARROW = "@media(max-width:560px){.mapmark{display:none}}"

# Every portal document that is not index.html. The mark is index-only, and a new page copying the
# map block is exactly how it would spread.
OTHER_PAGES = ("about.html", "add-survey.html", "brand.html", "releases.html", "404.html")


def _text(p):
    return p.read_text(encoding="utf-8")


def test_the_map_carries_the_mark_once_inside_the_map_container():
    """FAILS IF index.html loses the mark, carries it twice, or draws it outside the Leaflet map
    container, where it would be a page decoration rather than something a map screenshot picks up.

    The container assertion is positional and not just a substring: the mark must sit between the
    opening <div id="map"> and its close, which is the only place a screenshot of the map includes."""
    text = _text(INDEX)
    assert text.count(MARK_IMG) == 1, (
        f"index.html must carry the map watermark exactly once, as {MARK_IMG!r}; "
        f"found {text.count(MARK_IMG)}")
    m = re.search(r'<div id="map">(.*?)</div>', text, re.S)
    assert m, "index.html must carry the Leaflet map container"
    assert MARK_IMG in m.group(1), (
        f"the watermark belongs INSIDE the map container, so a screenshot of the map carries it: "
        f"{m.group(1)[:300]!r}")


def test_the_mark_is_not_a_link_and_names_the_organisation_in_its_alt_text():
    """FAILS IF the mark is wrapped in an anchor. The footer already links AuScope from every page,
    and a link inside the map takes a tab stop in the middle of the application's primary surface
    and can be dragged into a navigation by a mis-aimed pan. The alt text is the attribution for a
    reader who cannot see it, so it must be there and must name the organisation."""
    text = _text(INDEX)
    before = text[:text.index(MARK_IMG)]
    open_anchors = before.count("<a ") - before.count("</a>")
    assert open_anchors == 0, (
        f"the watermark must not sit inside an anchor; {open_anchors} anchor(s) are open at it")
    assert 'alt="AuScope"' in MARK_IMG and 'alt=""' not in MARK_IMG, (
        "the mark is attribution, so its alt text names the organisation rather than being empty")


def test_the_placement_honours_the_style_guide_clear_space_and_intercepts_nothing():
    """The geometry, as one literal, and the reasons it is those numbers.

    FAILS IF the inset drops below one logo height (the guide's clear space), if the height leaves
    the ruled 28px to 32px band, if pointer-events:none goes (the mark would then be able to swallow
    a click meant for the map), or if the narrow-width rule that hides it below 560px goes."""
    text = _text(INDEX)
    assert f".mapmark{{{PLACEMENT}}}" in text, (
        f"the watermark must carry the shared placement {PLACEMENT!r}")
    assert NARROW in text, (
        "the mark must not be drawn below the 560px breakpoint the footer uses")
    # Read as a DECLARATION rather than as a prefix: the rule also carries the flex and background
    # the map has always had, and the order they are written in is not the assertion.
    container = re.search(r"#map\{([^}]*)\}", text)
    assert container and "position:relative" in container.group(1), (
        "the map container must establish the positioning context; without it the absolutely "
        f"positioned mark escapes to the nearest positioned ancestor and lands anywhere at all: "
        f"{container.group(0) if container else None!r}")
    # The clear space, read back off the rule rather than restated: the inset on each edge the mark
    # is near must be at least the mark's own height.
    height = int(re.search(r"height:(\d+)px", PLACEMENT).group(1))
    assert 28 <= height <= 32, f"the mark's height must sit in the ruled band, got {height}px"
    for edge in ("top", "right"):
        inset = int(re.search(edge + r":(\d+)px", PLACEMENT).group(1))
        assert inset >= height, (
            f"the style guide asks for at least the full height of the logo of clear space on all "
            f"sides; the {edge} inset is {inset}px against a {height}px mark")


def test_the_mark_renders_at_full_opacity_and_is_never_tinted():
    """The style guide sets no rule permitting an opacity or a tint on the icon, and the contract
    ruled full opacity unless it did. FAILS IF an opacity, a filter or a mix-blend-mode is added to
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


def test_no_other_surface_on_the_site_draws_the_colour_icon():
    """The rule is map-only, and every surface that could grow a copy is named. FAILS IF another
    portal document, the engine's pages sheet (which draws the generated collection page's own
    footprint mark) or the SPA's collection scatter starts naming the file.

    The hub and card minimaps are covered by the same assertion on the two sheets that draw them:
    neither may name the file at all, in any slot."""
    for name in OTHER_PAGES:
        page = ROOT / name
        assert MARK_SRC.rsplit("/", 1)[-1] not in _text(page), (
            f"portal/{name}: the colour icon is the SPA map's watermark and belongs on no other "
            "surface")
    for label, path in (("engine/extract/_pages.py", PAGES_PY), ("portal/src/drawer.js", DRAWER)):
        assert MARK_SRC.rsplit("/", 1)[-1] not in _text(path), (
            f"{label}: the generated tier and the collection scatter draw the WHITE icon on their "
            "own panels; the colour icon is the SPA map's alone")


def test_the_committed_file_is_the_brand_kit_asset_byte_for_byte():
    """A trademark asset is a promise about a file. FAILS IF it is missing, resized, re-encoded,
    recoloured or stripped of its alpha channel: it is white-bordered artwork that has to sit on a
    pale basemap, and a re-encode that flattened the alpha would paint a box over the map."""
    assert MARK_ASSET.is_file(), f"the portal must ship {MARK_SRC}"
    data = MARK_ASSET.read_bytes()
    assert len(data) == MARK_BYTES, (
        f"{MARK_SRC} must be the brand kit's file unchanged: {MARK_BYTES} B, got {len(data)}")
    assert hashlib.sha256(data).hexdigest() == MARK_SHA256, (
        f"{MARK_SRC} does not match the recorded digest; it has been re-encoded or replaced")
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{MARK_SRC} must be a PNG"
    # Colour type 6 is RGBA. The mark is drawn over a live basemap, so its transparency is what
    # keeps it a mark rather than a tile.
    assert data[25] == 6, f"{MARK_SRC} must keep its alpha channel (PNG colour type 6)"
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    assert (width, height) == MARK_PIXELS, (
        f"{MARK_SRC} must keep the committed resolution {MARK_PIXELS}, got {(width, height)}")


def test_the_vendor_inventory_records_the_asset_beside_it():
    """The README is where an operator looks to answer "where did this file come from and is it the
    one the brand kit published". FAILS IF it stops naming the file, its source, its digest or its
    byte count, which is the same four facts the pin above holds against the bytes themselves."""
    readme = _text(VENDOR_README)
    assert "auscope-icon-colour.png" in readme, (
        "portal/vendor/README.md must record the map watermark like every other vendored asset")
    assert MARK_SHA256 in readme, "the README must record the asset's SHA-256"
    assert f"{MARK_BYTES} B" in readme, "the README must record the asset's byte count"
    assert "2025 AuScope Logo Icon - Colour.png" in readme, (
        "the README must name the brand kit file the bytes were taken from")
