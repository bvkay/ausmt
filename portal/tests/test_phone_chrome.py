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
  * THE SHEET - FAILS if, at 900px and narrower, the map stops filling the screen under the header,
    the panel leaves its sheet, the sheet loses its handle, its peek row or its Back control, a snap
    height drifts from peek, half and full, or the sheet stops falling back to half
    and scrolling inside itself when no script runs.
  * THE DRAWER IN THE SHEET - FAILS if the sheet stops hiding the filters while it hosts the drawer,
    or the drawer keeps its desktop slide and width inside the sheet.
  * THE TABLET CARD - FAILS if, from 761px to 900px, the sheet stops being a 420px card at the
    bottom left with the map showing beside it.
  * THE FOOTER'S CONTENTS - FAILS if the map page's footer stays on screen at 900px and narrower, or
    if the sheet stops ending with the About link, the MTCAT link and the AuScope line, the last two
    as the footer writes them.
  * PLOTS - FAILS if a drawer plot can be wider than the drawer at a phone width.
  * REDUCED MOTION - FAILS if the sheet's slide escapes the reduced-motion rule.
  * SURVEYS - FAILS if a /surveys control label or select can push the page sideways at a phone width.
  * DRAW TOOLBAR - FAILS if the Leaflet draw toolbar is drawn at 900px and narrower.
  * DESKTOP - FAILS if any of these overrides leaks out of its query into the base rules.
"""
import re
from pathlib import Path

from chrome_contract import (FOOTER_CENTRE_MARKUP, FOOTER_LEFT, PHONE_BREAKPOINT, PHONE_HEADER, SAFE_AREA,
                             TAP_TARGET)

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
INTERIM_BELOW = 760
# The snap heights: peek holds the handle, the counts and the Browse and Select control.
PEEK = "120px"
HALF = "50dvh"
FULL = "100dvh - 52px"
CARD_FROM = 761
CARD_WIDTH = "420px"


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


def _phone(text):
    return _rules("".join(_blocks(text, f"@media (max-width:{PHONE_BREAKPOINT}px)")))


def _sheet_markup(text):
    m = re.search(r'<section class="sheet"[^>]*>(.*?)</section><!-- /#sheet -->', text, re.S)
    assert m, 'index.html: the panel must sit in <section class="sheet" ...> closed by <!-- /#sheet -->'
    return m.group(0)


def test_the_panel_sits_in_a_sheet_with_a_handle_a_peek_row_and_a_back_control():
    """FAILS if #filterPane leaves the sheet, if the sheet does not open at half with the filters as
    its host, if the handle is not a labelled button stating the height and whether the sheet is
    expanded, or if the peek row or the Back control is missing or carries an inline handler."""
    text = _text(INDEX)
    sheet = _sheet_markup(text)
    head = re.match(r"<section ([^>]*)>", sheet).group(1)
    for attr in ('id="sheet"', 'data-snap="half"', 'data-host="filters"'):
        assert attr in head, f"index.html: the sheet must declare {attr}: {head!r}"
    assert '<aside class="filters" id="filterPane">' in sheet, "index.html: #filterPane sits in the sheet"
    handle = re.search(r'<button ([^>]*id="sheetHandle"[^>]*)>', sheet)
    assert handle, "index.html: the sheet opens with its handle, a <button id=\"sheetHandle\">"
    attrs = handle.group(1)
    for attr in ('type="button"', 'aria-controls="sheet"', 'aria-expanded="true"'):
        assert attr in attrs, f"index.html: the handle must declare {attr}: {attrs!r}"
    label = re.search(r'aria-label="([^"]*)"', attrs)
    assert label and "half" in label.group(1), "index.html: the handle's label names the current height"
    order = [sheet.index(k) for k in ('id="sheetHandle"', 'id="sheetPeek"', 'id="sheetBack"', 'id="filterPane"')]
    assert order == sorted(order), "index.html: handle, peek row, Back control, then the panel"
    assert re.search(r'<button type="button" class="sheetback" id="sheetBack">[^<]*Filters</button>', sheet), (
        "index.html: the Back control is a button that names where it returns to")
    assert not re.search(r"\son[a-z]+=", sheet), "index.html: no inline handler in the sheet (CSP)"


def test_the_sheet_ends_with_the_footers_contents_and_about():
    """FAILS if the end of the sheet's content stops carrying the About link, the MTCAT link and the
    AuScope line, or if either of the last two drifts from the footer's own wording and markup."""
    text = _text(INDEX)
    aside = re.search(r'<aside class="filters"[^>]*>(.*?)</aside>', text, re.S).group(1)
    foot = re.search(r'<div class="sheetfoot" id="sheetFoot">(.*?)</div><!-- /#sheetFoot -->', aside, re.S)
    assert foot, "index.html: the panel ends with <div class=\"sheetfoot\" id=\"sheetFoot\">"
    assert aside.index("<!-- /#selectMode -->") < foot.start() < aside.index('id="sidebarCollapse"')
    body = " ".join(re.sub(r"<!--.*?-->", "", foot.group(1), flags=re.S).split())
    assert '<a class="sheetabout" href="about.html">About</a>' in body, "the sheet's About link"
    assert (f'<a class="apilink" href="data/mtcat.json" title="MTCAT discovery document (JSON)">'
            f'{FOOTER_LEFT}</a>') in body, "the sheet's MTCAT link is the footer's"
    assert FOOTER_CENTRE_MARKUP in body, "the sheet's AuScope line is the footer's centre line"
    assert "panelabout" not in text, "the interim panel About link is replaced by the sheet's"
    base = _rules(_outside_queries(text))
    assert "display:none" in _decls(base.get(".sheetfoot", [])), "hidden above 900px, where the footer shows"
    phone = _phone(text)
    assert "display:flex" in _decls(phone.get(".sheetfoot", []))
    for sel in (".sheetfoot a",):
        decls = _decls(phone.get(sel, []))
        assert f"min-height:{TAP_TARGET}px" in decls and "display:inline-flex" in decls, (
            f"index.html: {sel} is a {TAP_TARGET}px target: {decls!r}")
    assert "display:none" in _decls(phone.get("footer", [])), (
        "index.html: at 900px and narrower the map page's footer leaves the viewport")


def test_below_900px_the_map_fills_the_screen_and_the_sheet_slides_over_it():
    """FAILS if the page stops being one screen tall at a phone width, if the sheet is not a fixed
    box moved by translateY, or if a snap height drifts from peek 120px, half 50dvh and full the
    screen less the 52px header. The default (no data-snap, as with no script) is half."""
    rules = _phone(_text(INDEX))
    assert "height:100dvh" in _decls(rules.get("body", [])), "index.html: the page is one screen tall"
    sheet = _decls(rules.get(".sheet", []))
    for decl in ("display:flex", "flex-direction:column", "position:fixed", "bottom:0",
                 f"--sheet-peek:calc({PEEK}+env(safe-area-inset-bottom,0px))", f"--sheet-snap:{HALF}",
                 f"--sheet-full:calc({FULL}-env(safe-area-inset-top,0px))".replace(" ", ""),
                 "height:var(--sheet-full)", "transform:translateY(calc(var(--sheet-full)-var(--sheet-snap)))",
                 "transition:transform"):
        assert decl.replace(" ", "") in sheet, f"index.html: below 900px the sheet must declare {decl}: {sheet!r}"
    assert "--sheet-snap:var(--sheet-peek)" in _decls(rules.get('.sheet[data-snap="peek"]', []))
    assert "--sheet-snap:var(--sheet-full)" in _decls(rules.get('.sheet[data-snap="full"]', []))
    spacer = _decls(rules.get(".sheet::after", []))
    assert "height:calc(var(--sheet-full)-var(--sheet-snap))" in spacer, (
        "index.html: the off-screen part of the sheet is a spacer, so the panel scrolls within what shows")
    panel = _decls(rules.get(".sheet aside.filters", []))
    for decl in ("width:auto!important", "flex:1 1 auto", "min-height:0"):
        assert decl.replace(" ", "") in panel, f"index.html: in the sheet the panel must declare {decl}: {panel!r}"
    for sel in (".sheet #browseMode", ".sheet #treeSection", ".sheet .tree"):
        decls = _decls(rules.get(sel, []))
        assert "flex:none" in decls and "overflow:visible" in decls, (
            f"index.html: in the sheet {sel} takes its own height, so the sheet scrolls and not the tree")
    seg = _decls(rules.get(".sheet #modeSeg", []))
    assert "position:sticky" in seg and "top:0" in seg, "Browse and Select stays at the top of the sheet"
    handle = _decls(rules.get(".sheethandle", []))
    assert f"min-height:{TAP_TARGET}px" in handle and "touch-action:none" in handle, handle


def test_the_sheet_hosts_the_drawer_in_place_of_the_filters():
    """FAILS if the filters and the peek row stay drawn while the drawer is the host, or if the
    drawer keeps its desktop slide, width or hidden state inside the sheet."""
    rules = _phone(_text(INDEX))
    for sel in ('.sheet[data-host="drawer"] aside.filters', '.sheet[data-host="drawer"] .sheetpeek'):
        assert "display:none" in _decls(rules.get(sel, [])), f"index.html: {sel} must be hidden"
    drawer = _decls(rules.get(".sheet #drawer", []))
    for decl in ("position:static", "transform:none", "width:auto!important", "flex:1 1 auto", "min-height:0",
                 "display:none"):
        assert decl.replace(" ", "") in drawer, f"index.html: in the sheet the drawer must declare {decl}: {drawer!r}"
    assert "display:block" in _decls(rules.get('.sheet[data-host="drawer"] #drawer', []))
    assert "display:flex" in _decls(rules.get('.sheet[data-host="drawer"] .sheetbar', []))
    svg = _decls(rules.get("#drawer svg", []))
    assert "max-width:100%" in svg and "height:auto" in svg, (
        f"index.html: a drawer plot must scale to the drawer: {svg!r}")


def test_from_761_to_900px_the_sheet_is_a_card_at_the_bottom_left():
    """FAILS if the tablet band loses its card: 420px wide, 16px in from the left and the bottom."""
    text = _text(INDEX)
    rules = _rules("".join(_blocks(text, f"@media (min-width:{CARD_FROM}px) and (max-width:{PHONE_BREAKPOINT}px)")))
    card = _decls(rules.get(".sheet", []))
    for decl in ("left:16px", "right:auto", "bottom:16px", f"width:{CARD_WIDTH}", "border-radius:14px"):
        assert decl.replace(" ", "") in card, f"index.html: from {CARD_FROM}px the sheet must declare {decl}: {card!r}"


def test_above_900px_the_sheet_takes_no_part_in_the_layout():
    """FAILS if the sheet wrapper or its phone-only parts draw anything above 900px, where the
    side-by-side layout must be exactly what it was."""
    base = _rules(_outside_queries(_text(INDEX)))
    assert "display:contents" in _decls(base.get(".sheet", [])), (
        "index.html: above 900px the sheet is display:contents, so the panel stays a flex child of main")
    for sel in (".sheethandle", ".sheetpeek", ".sheetbar", ".sheetfoot"):
        assert "display:none" in _decls(base.get(sel, [])), f"index.html: {sel} is hidden above 900px"


def test_the_interim_stacked_layout_is_gone():
    """FAILS if the scrolling stacked layout the sheet replaces comes back at 760px and narrower."""
    rules = _rules("".join(_blocks(_text(INDEX), f"@media (max-width:{INTERIM_BELOW}px)")))
    assert "overflow:visible" not in _decls(rules.get("body", []))
    assert "55svh" not in _decls(rules.get(".content", []))
    assert "inset:0" not in _decls(rules.get("#drawer", []))


def test_reduced_motion_stops_the_sheet_sliding():
    """FAILS if the reduced-motion rule stops covering every transition, the sheet's included."""
    text = _text(INDEX)
    assert "@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}" in text


def test_the_draw_toolbar_is_hidden_at_phone_widths():
    """FAILS if the Leaflet draw toolbar is not hidden at 900px and narrower."""
    shown = _rules("".join(_blocks(_text(INDEX), f"@media (max-width:{PHONE_BREAKPOINT}px)")))
    assert "display:none" in _decls(shown.get(".leaflet-draw.leaflet-control", [])), (
        "index.html: the draw toolbar is hidden at 900px and narrower")


def test_the_surveys_controls_cannot_push_the_page_sideways():
    """FAILS if a /surveys control label keeps its content-sized floor, or a select its intrinsic width,
    at a phone width: the Organisation select reached 474px on a 375px screen."""
    rules = _rules("".join(_blocks(_text(PAGES_PY), f"@media (max-width:{INTERIM_BELOW}px)")))
    assert "min-width:0" in _decls(rules.get(".idxctl label", [])), (
        "engine/extract/_pages.py: a /surveys control label must be free to shrink")
    assert "max-width:100%" in _decls(rules.get(".idxctl select", [])), (
        "engine/extract/_pages.py: a /surveys select must not outgrow its label")


def test_no_phone_override_leaks_into_the_desktop_rules():
    """FAILS if any override above is written into a base rule, which would change the desktop
    layout this work must leave as it is."""
    base = _rules(_outside_queries(_text(INDEX)))
    for sel in ("body", "aside.filters", ".content", "#drawer"):
        decls = _decls(base.get(sel, []))
        for leak in ("overflow:visible", "max-height:none", "55svh", "position:fixed", "env(safe-area"):
            assert leak not in decls, f"index.html: {sel} carries the phone override {leak!r} at every width"
    assert "#drawer svg" not in base, "index.html: the drawer plot rule belongs to the phone query"
    assert "pointer:coarse" not in _outside_queries(_text(INDEX)), "no coarse rule may sit outside a query"


def test_the_sheet_script_is_a_served_file_and_its_controls_carry_no_inline_handler():
    """FAILS if the sheet's behaviour moves into an inline script or handler, which the page's CSP
    (script-src 'self') blocks, or if index.html stops loading src/sheet.js before drawer.js, whose
    openers call it."""
    text = _text(INDEX)
    tags = re.findall(r'<script src="src/([a-z-]+)\.js"></script>', text)
    assert "sheet" in tags and tags.index("sheet") < tags.index("drawer"), tags
    src = (ROOT / "src" / "sheet.js").read_text(encoding="utf-8")
    assert "const _sheetPhoneMq=_sheetMq(SHEET_QUERY);" in src and 'SHEET_QUERY="(max-width:900px)"' in src, (
        "src/sheet.js: the phone branch is gated on one matchMedia query")
    assert "innerHTML" not in src and "eval(" not in src and "setAttribute(\"on" not in src
