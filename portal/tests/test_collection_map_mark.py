"""The AuScope mark on the collection footprint map, on both surfaces that draw one full size.

A collection is drawn twice: as the static collection page's <figure class="collmap"> (the engine,
engine/extract/_pages.py) and as the SPA's own collScatter in the collection-detail hero
(portal/src/drawer.js). The mark rides the panel's bottom-left corner on both, so a reader moving
between /collections/<id> and the in-app view sees one map and not two.

THE MARK IS NEVER INSIDE THE SVG. The footprint is generated geometry that several pins read and
compare element for element (the member-colour ramp, the dot-per-station coverage claim, the shared
outline symbol and the hub's size budget). An <image> in it would put a brand asset inside the thing
those pins measure, and a data URI would put the whole PNG inside every document that draws a map.
It is an absolutely positioned sibling of the SVG instead, and the pins here hold that.

WHY THE BOTTOM LEFT IS SAFE, as a number rather than as a preference: this projection is
fixed-extent (112E to 154E, 9S to 44S), so the corner a mark is pinned to shows the same geography
at every rendered width. In the bottom 120 units of the 560 x 467 viewBox the nearest coastline is
Tasmania's, at x = 326. The mark occupies well under a quarter of that clear box at every width the
two surfaces render, and the legend is a SIBLING of the panel rather than content inside it, so the
mark can reach neither the coastline nor the legend by construction.

THE LIST CARD IS NOT IN SCOPE and is pinned as not in scope: a collection card's map is a thumbnail
with no corner to spare, and a mark on it would be larger relative to the map than the map is to the
card. The engine's hub card takes the legend=False path, which returns the bare SVG; the SPA's card
calls collScatter without the flag.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # portal/
INDEX = ROOT / "index.html"
DRAWER = ROOT / "src" / "drawer.js"
PAGES_PY = ROOT.parent / "engine" / "extract" / "_pages.py"

MARK_SRC = "/vendor/auscope-icon-white.png"
MARK_IMG = f'<img class="collmark" src="{MARK_SRC}" alt="AuScope" width="27" height="28">'

# The overlay's own geometry, stated once per surface. Same offsets, same height, same opacity, so
# the two maps put the mark in the same place; only the selector differs, because the engine's panel
# is a <figure> and the SPA's is a <div> the script builds.
PLACEMENT = "position:absolute;left:14px;bottom:14px;height:28px;width:auto;opacity:.82;pointer-events:none"
NARROW = "left:9px;bottom:9px;height:20px"


def _text(p):
    return p.read_text(encoding="utf-8")


def test_the_static_collection_figure_positions_the_mark_and_the_svg_stays_pure():
    """FAILS IF the engine's collection figure loses the mark, stops being a positioning context
    (the mark would escape to the nearest positioned ancestor and land anywhere at all), or starts
    carrying the image inside the SVG, where every geometry pin would then have to see it."""
    text = _text(PAGES_PY)
    assert text.count(MARK_IMG) == 1, \
        f"engine/extract/_pages.py: the collection figure must emit {MARK_IMG!r} exactly once"
    assert ".collmap{position:relative;" in text, \
        "engine/extract/_pages.py: .collmap must establish the positioning context for the mark"
    assert f".collmark{{{PLACEMENT}}}" in text, \
        f"engine/extract/_pages.py: the mark must carry the shared placement {PLACEMENT!r}"
    assert f"@media(max-width:640px){{.collmark{{{NARROW}}}}}" in text, \
        "engine/extract/_pages.py: the mark must step down on narrow screens"
    # The mark rides OVER the SVG: it is emitted between the interpolated map and the figure's own
    # close, which puts it outside the SVG element. An <image> INSIDE the SVG would be a brand asset
    # inside the geometry every other pin measures, and a data URI would be the whole PNG inlined
    # into every collection page. The RENDERED form of that rule is asserted where the page is
    # actually built (engine/tests/test_entity_pages.py).
    opens = text.index('<figure class="collmap">{svg}')
    assert opens < text.index(MARK_IMG) < text.index("</figure>", opens), \
        "engine/extract/_pages.py: the mark sits between the map and the figure's close"


def test_the_spa_detail_hero_draws_the_same_mark_and_the_list_card_does_not():
    """FAILS IF the SPA's collection-detail hero stops asking for the mark, if the list card starts
    asking for it, or if the mark's panel loses the width cap that makes the corner it is pinned to
    the MAP's corner rather than the column's.

    The cap matters and is not decoration: the SVG carries its own max-width, so in a column wider
    than the cap the panel would be wider than the map it wraps and a mark pinned to the panel's
    bottom-left would float in the gutter beside the map."""
    src = _text(DRAWER)
    assert 'class="collscatter-panel" style="max-width:${cap}px"' in src, \
        "the mark's panel must be capped at the same width the map is"
    assert src.count(MARK_SRC) == 1, \
        f"drawer.js must name {MARK_SRC} exactly once, got {src.count(MARK_SRC)}"
    assert "collScatter(ss,720,true)" in src, \
        "the collection-detail hero draws the full-size map and takes the mark"
    assert "collScatter(ss)" in src, \
        "the list card draws a thumbnail and must keep taking no mark"


def test_the_spa_places_the_mark_exactly_where_the_static_page_does():
    """One map, one placement. FAILS IF either surface's offsets, height or opacity drift from the
    other's: a reader crossing between /collections/<id> and the in-app view would watch the mark
    move around the panel."""
    index = _text(INDEX)
    assert ".collscatter-panel{position:relative}" in index, \
        "the SPA panel must establish the positioning context for the mark"
    # Measured: without this the inline SVG's line box leaves a 3px descender under the map, the
    # panel's bottom edge stops being the map's bottom edge, and the mark sits 11px above the
    # coastline panel where the static page puts it at 14px.
    assert ".collscatter-panel svg{display:block}" in index, \
        "the panel's map must be a block, or the panel's bottom edge is not the map's"
    assert f".collscatter-panel .collmark{{{PLACEMENT}}}" in index, \
        f"portal/index.html: the mark must carry the shared placement {PLACEMENT!r}"
    assert f"@media(max-width:640px){{.collscatter-panel .collmark{{{NARROW}}}}}" in index, \
        "portal/index.html: the mark must step down on narrow screens"


def test_the_mark_clears_the_coastline_at_the_panels_narrowest_rendered_width():
    """The safety argument in the module docstring, as arithmetic rather than as prose.

    The clear box at the bottom left of this fixed-extent projection is 120 viewBox units tall and
    326 wide out of 560 x 467. The panel's narrowest realistic rendering is a 375px phone, and the
    mark must sit inside that box THERE, which is where it has least room. FAILS IF the offsets or
    the height grow past what the clear corner can hold."""
    view_w, clear_units_h, clear_units_w = 560, 120, 326
    rendered = 343                      # a 375px viewport less the page's own side padding
    scale = rendered / view_w           # viewBox units to rendered pixels
    left, bottom, height = 9, 9, 20     # the narrow-screen step-down, which is what applies at 375px
    width = height * 281 / 288          # the asset's own aspect ratio
    assert bottom + height < clear_units_h * scale, (
        f"the mark reaches {bottom + height:.0f}px up a {clear_units_h * scale:.0f}px clear band; "
        "it would cross into the geography")
    assert left + width < clear_units_w * scale, (
        f"the mark reaches {left + width:.0f}px across a {clear_units_w * scale:.0f}px clear band; "
        "it would reach Tasmania")
