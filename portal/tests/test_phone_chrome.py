"""The portal on phones and touch screens: tap targets, safe areas, the phone header and reachability.

jsdom does no layout and evaluates no media query, so these are SOURCE pins on the rules a browser
applies at a phone width or under a coarse pointer. The geometry they produce is measured in a real
browser and recorded in docs/docs/reference/portal-internals.md; what this file holds is that the
rules are there, where they must be, and that the desktop rules they override are left alone.

Each assertion states its failure criterion:

  * VIEWPORT - FAILS if any page the portal ships or the engine emits loses viewport-fit=cover, which
    is what lets a page read the safe-area insets at all.
  * SAFE AREAS - FAILS if a surface with a footer stops carrying the one safe-area rule, or if the
    phone header stops clearing the top inset.
  * TAP TARGETS - FAILS if the coarse-pointer block on the map page stops giving every named control
    a 44px floor in both directions, or if an inline control (a footer link) loses the display that
    lets a floor apply to it.
  * INPUTS - FAILS if a text input or select on the map page or the /surveys controls is under 16px
    on a coarse pointer, the size below which iOS Safari zooms the page on focus.
  * ABOUT - FAILS if the map page's panel stops ending with an About link while the header hides
    About at a phone width.
"""
import re
from pathlib import Path

from chrome_contract import PHONE_BREAKPOINT, PHONE_HEADER, SAFE_AREA, TAP_TARGET

ROOT = Path(__file__).resolve().parent.parent          # portal/
INDEX = ROOT / "index.html"
PAGES_PY = ROOT.parent / "engine" / "extract" / "_pages.py"
PAGES = ("404.html", "about.html", "add-survey.html", "brand.html", "index.html", "releases.html")

# The controls the coarse-pointer block must lift to a 44px floor, by the selector the block names.
# .seg button covers the Browse and Select control and the drawer's tabs; the Leaflet bar anchors
# are the zoom and draw controls.
COARSE_TARGETS = (".typegrid label", ".collgroup .coll", ".seg button", ".leaflet-touch .leaflet-bar a",
                  ".maplegend-toggle", ".maplegend .legtype", ".dhead .close", ".plotexp", "footer a")
COARSE_INPUTS = ("#find", "#availSel", "#surveySearch", "#yearFrom", "#yearTo", "#sortSel")


def _text(path):
    return path.read_text(encoding="utf-8")


def _blocks(text, prelude):
    """The bodies of every at-rule whose prelude is exactly `prelude`, brace-matched."""
    out, i = [], 0
    while True:
        at = text.find(prelude + "{", i)
        if at < 0:
            return out
        j = start = at + len(prelude) + 1
        depth = 1
        while depth:
            depth += {"{": 1, "}": -1}.get(text[j], 0)
            j += 1
        out.append(text[start:j - 1])
        i = j


def _rules(css):
    """{selector: declarations} for a flat run of rules, each selector of a group listed on its own."""
    out = {}
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for sels, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        for sel in sels.split(","):
            out.setdefault(" ".join(sel.split()), []).append(body)
    return out


def _decls(bodies):
    return ";".join(bodies).replace(" ", "")


def _outside_queries(text):
    """`text` with every @media block removed, brace-matched."""
    out, i = [], 0
    while True:
        at = text.find("@media", i)
        if at < 0:
            out.append(text[i:])
            return "".join(out)
        out.append(text[i:at])
        j = text.index("{", at) + 1
        depth = 1
        while depth:
            depth += {"{": 1, "}": -1}.get(text[j], 0)
            j += 1
        i = j


def test_every_page_declares_viewport_fit_cover():
    """FAILS if a page's viewport meta stops reading width=device-width with viewport-fit=cover:
    without it iOS letterboxes the page inside the safe area and env() reads 0 everywhere."""
    sources = [(name, _text(ROOT / name)) for name in PAGES]
    sources.append(("engine/extract/_pages.py", _text(PAGES_PY)))
    for where, text in sources:
        metas = re.findall(r'<meta name="viewport" content="([^"]*)">', text)
        assert len(metas) == 1, f"{where}: expected one viewport meta, found {metas}"
        parts = [p.strip() for p in metas[0].split(",")]
        assert "width=device-width" in parts and "viewport-fit=cover" in parts, (
            f"{where}: the viewport meta must declare viewport-fit=cover: {metas[0]!r}")


def test_every_surface_with_a_footer_carries_the_safe_area_rule():
    """FAILS if any surface drops or edits the one safe-area rule, or places it where the footer's
    own base rule would win it back at equal specificity."""
    sources = [(name, _text(ROOT / name)) for name in PAGES]
    sources.append(("engine/extract/_pages.py", _text(PAGES_PY)))
    for where, text in sources:
        assert text.count(SAFE_AREA) == 1, f"{where}: expected exactly one {SAFE_AREA!r}"
        base = re.search(r"(?m)^\s*footer\{", text)
        assert base and base.start() < text.index(SAFE_AREA), (
            f"{where}: the safe-area rule must follow the footer's base rule")


def test_the_phone_header_clears_the_top_inset():
    """FAILS if the phone header stops padding its top by the top inset and growing by the same."""
    assert "padding:env(safe-area-inset-top,0px)" in PHONE_HEADER
    assert "height:calc(52px + env(safe-area-inset-top,0px))" in PHONE_HEADER


def test_the_coarse_pointer_block_gives_every_named_control_a_44px_floor():
    """FAILS if index.html has no pointer:coarse block, if a named control is missing from it, or if
    its rule declares less than a 44px floor in either direction."""
    blocks = _blocks(_text(INDEX), "@media (pointer:coarse)")
    assert blocks, "index.html must carry a @media (pointer:coarse) block"
    rules = _rules("".join(blocks))
    floor = f"{TAP_TARGET}px"
    for sel in COARSE_TARGETS:
        assert sel in rules, f"index.html: the coarse-pointer block must name {sel!r}"
        decls = _decls(rules[sel])
        for prop in ("min-height", "min-width"):
            assert f"{prop}:{floor}" in decls, f"index.html: {sel} must declare {prop}:{floor}: {decls!r}"
    assert "display:inline-flex" in _decls(rules["footer a"]), (
        "index.html: a footer link is inline, where min-height does nothing; it must become an "
        "inline flex box under a coarse pointer")


def test_coarse_pointer_inputs_are_16px_on_the_map_page_and_the_surveys_page():
    """FAILS if a named input on the map page, or the /surveys inputs and selects, are under 16px on a
    coarse pointer."""
    rules = _rules("".join(_blocks(_text(INDEX), "@media (pointer:coarse)")))
    for sel in COARSE_INPUTS:
        assert sel in rules and "font-size:16px" in _decls(rules[sel]), (
            f"index.html: {sel} must be 16px under a coarse pointer")
    pages = _rules("".join(_blocks(_text(PAGES_PY), "@media (pointer:coarse)")))
    for sel in (".idxctl input", ".idxctl select"):
        assert sel in pages and "font-size:16px" in _decls(pages[sel]), (
            f"engine/extract/_pages.py: {sel} must be 16px under a coarse pointer")


def test_the_panel_ends_with_an_about_link_shown_only_where_the_header_hides_about():
    """FAILS if the panel's About link goes, is not the panel's last content before the collapse
    control, or shows at desktop widths where the header still carries About."""
    text = _text(INDEX)
    aside = re.search(r'<aside class="filters"[^>]*>(.*?)</aside>', text, re.S).group(1)
    link = '<a class="panelabout" href="about.html">About</a>'
    assert aside.count(link) == 1, f"index.html: the panel must end with {link}"
    assert aside.index("<!-- /#selectMode -->") < aside.index(link) < aside.index('id="sidebarCollapse"')
    assert "display:none" in _decls(_rules(_outside_queries(text)).get(".panelabout", [])), (
        "index.html: the panel's About link is hidden at desktop widths")
    shown = _rules("".join(_blocks(text, f"@media (max-width:{PHONE_BREAKPOINT}px)")))
    assert "display:inline-flex" in _decls(shown.get(".panelabout", [])), (
        "index.html: at 900px and narrower the panel's About link is shown")
    assert f"min-height:{TAP_TARGET}px" in _decls(shown.get(".panelabout", []))
