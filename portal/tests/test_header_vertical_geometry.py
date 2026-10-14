"""The header's VERTICAL geometry, pinned on every surface that wears the site chrome.

WHY THIS FILE EXISTS. tests/test_header_geometry_parity.py pins the header HORIZONTALLY, and it does
that thoroughly: the tab group's x, the zone widths and their flex bases, the tab box's own width,
the box model the width is measured in, and the font stack the labels are measured with. Not one of
those pins can see the header get TALLER. So when the 30px identity mark landed, the identity block
outgrew its zone, the tagline dropped onto a second line, and the generated pages' header went from
57.00px to 82.47px at 1280px with every horizontal pin still green, the four-surface parity proof
still green, and the framing classification still reporting a header-identity diff. A 45 per cent
change in the height of every page's header passed the whole gate.

The gap was systematic rather than unlucky, so the close is systematic too. The header's height is

    header = padding-block + border-bottom + max(zone heights)

and the zones are built so that only ONE of them can grow. The identity zone is the 36px AuScope mark
and AusMT's name on one line,

    hleft  = max(mark height, line-box(name))  =  36px

where a line box is font-size x line-height and the name declares line-height:1, so its line box is
its 24.5px font size and the mark is the taller item. The block would wrap only if

    wraps  <=>  mark-width + gap + name-width  >  zone-width

and at 36 + 12 + about 79px it never does: the zone is 139px at 761px of viewport, and below 760px
the zones stack full width. The right zone is the tagline on one line, white-space:nowrap with its
overflow contained, so it is one line box at every width and never adds a row.

The tab group's zone grows, in whole tab rows:

    hcenter = rows x tab-min-height + (rows - 1) x row-gap
    rows    = 1 while the nav container may not wrap, whatever the width; otherwise it grows as
              soon as the tabs' own min-width floors plus their gaps exceed the zone's width

That second expression is why the nav container's flex-wrap is a term of the HEIGHT and not a detail
of the nav's own layout. A nowrap container pins rows at 1 and holds the header short while the tabs
overrun the zone sideways instead; a wrapping one stacks them and the header grows by a whole tab
row. Measured at 375px, one declaration apart: 260px with the wrap, 214px without it, and without it
the tab group's right edge lands at 366px against a 357px content edge.

Beside one tab row neither side zone is the tallest, because the mark is shorter than the tabs'
floor, so from 761px up the header is the tabs' floor plus its padding and border:

    header  = 2 x 8px + 1px + max(36px, 24.5px, line-box(tagline), 40px)  =  57px

Measured in Chrome at a device scale factor of 1, on every chrome surface: 57px from
761px up, 134px from 451px to 760px, 170px from 384px to 450px and 216px below 384px, where the
stacked zones add the mark's row, the tab rows and the tagline's line.

Every term in these expressions is a DECLARED constant except the intrinsic text widths, which are a
property of the font stack and are already pinned pairwise next door. This file pins the declared
terms, and it pins them as a set: it builds a vertical fingerprint from each surface's own source and
requires every surface to carry the SAME one. It asserts parity of the inputs rather than a pixel
count because a pixel count would be a measurement of the CI runner's font metrics, and would be red
on a developer's laptop for no defect at all. The inputs are viewport-independent, which is what lets
one comparison stand for the whole ladder: a declared constant is the same at 1280px as at 375px.

WHAT IS DELIBERATELY NOT COMPARED, AND WHAT THAT COSTS. Colours, backgrounds, sticky positioning and
z-index are surface-local and carry no vertical geometry, exactly as the horizontal pins next door
leave them alone. The border-bottom is compared by its WIDTH only, for the same reason: the width is
a term of the height, the colour is not.

Zone CONTENT is not compared here, and that is the honest limit of this pin. Agreement here means
two surfaces resolve the same height from the chrome they DECLARE; it is not a pixel measurement. The
content is held separately: tests/test_header_geometry_parity.py compares every surface's header
markup with the contract token by token, and with the contextual counts moved to the footer no zone
of the header varies by page any more.

ONE MARK BOX, ON EVERY SURFACE. The identity zone opens with the mark, so the mark's declared
box is a term of the first line and the fingerprint carries it: a mark taller than the tabs' floor
would set the header's height at every width. tests/test_header_geometry_parity.py holds the markup
half, that every identity zone is the mark and the name and nothing else.
"""
import re
from pathlib import Path

from chrome_contract import MARK_SIZE

ROOT = Path(__file__).resolve().parent.parent          # portal/
PAGES_PY = ROOT.parent / "engine" / "extract" / "_pages.py"

# The tabs' floor and the header's own box at one row, the terms of the 57px desktop height.
TAB_FLOOR = 40
HEADER_PADDING_BLOCK = 8
HEADER_BORDER = 1
DESKTOP_HEADER = 57


def _rule(text, pattern, where, what, must_contain=None):
    """One rule body, required to be declared exactly once: a second declaration of the same
    selector would silently override the pinned value at equal specificity.

    must_contain narrows a selector that is legitimately declared more than once to the BASE rule.
    .hzone is the case that needs it: the narrow-width stacking override restates the selector
    inside the 760px block to give the zones a full-width basis, which is the wrap behaviour the
    parity file pins on purpose. The base rule is the one that declares display."""
    bodies = re.findall(pattern, text)
    if must_contain is not None:
        bodies = [b for b in bodies if must_contain in b]
    assert len(bodies) == 1, (
        f"{where}: expected exactly one {what} rule, found {len(bodies)}")
    # Some surfaces state a rule across several source lines; fold the breaks away so the
    # declaration list parses as one string.
    return re.sub(r"\s*\n\s*", "", bodies[0])


def _decl(body, prop, where, what):
    """One declaration's value out of a rule body. Anchored on a semicolon or the start of the
    body so that asking for `gap` cannot match `row-gap`, or `border` match `border-bottom`."""
    m = re.search(r"(?:^|;)\s*" + re.escape(prop) + r"\s*:\s*([^;]+)", body)
    assert m, f"{where}: the {what} rule declares no {prop}; got {body!r}"
    return m.group(1).strip()


def _surfaces():
    """Every surface carrying the three-zone chrome, as (where, text, is_pages_sheet). Discovered
    from the filesystem rather than from a list, so a new page wearing the chrome is pinned the day
    it appears rather than the day someone remembers this file."""
    out = [("engine/extract/_pages.py", PAGES_PY.read_text(encoding="utf-8"), True)]
    for page in sorted(ROOT.glob("*.html")):
        text = page.read_text(encoding="utf-8")
        if ".hzone{" in text:
            out.append((f"portal/{page.name}", text, False))
    return out


def _fingerprint(where, text, is_pages):
    """Every declared term of the two expressions above, read from one surface's own source."""
    header_sel = r"(?m)^\s*header\.site\{([^}]*)\}" if is_pages else r"(?m)^\s*header\{([^}]*)\}"
    nav_sel = (r"(?m)^\s*header\.site nav\{([^}]*)\}" if is_pages
               else r"(?m)^\s*nav\{([^}]*)\}")
    tab_sel = (r"(?m)^\s*header\.site nav a\{([^}]*)\}" if is_pages
               else r"(?m)^\s*nav a\{([^}]*)\}")
    header = _rule(text, header_sel, where, "header")
    navbar = _rule(text, nav_sel, where, "nav container")
    hzone = _rule(text, r"(?m)^\s*\.hzone\{([^}]*)\}", where, ".hzone", must_contain="display:")
    wordmark = _rule(text, r"(?m)^\s*\.wordmark\{([^}]*)\}", where, ".wordmark")
    tagline = _rule(text, r"(?m)^\s*\.tagline\{([^}]*)\}", where, ".tagline")
    tab = _rule(text, tab_sel, where, "nav tab")
    mark = _rule(text, r"(?m)^\s*\.brandmark\{([^}]*)\}", where, ".brandmark")

    return {
        # The header box itself: the padding and the border are added to the tallest zone, the
        # row half of the gap is what separates the zones once the header itself wraps, and
        # align-items decides whether a short zone is centred against a tall one.
        "header align-items": _decl(header, "align-items", where, "header"),
        "header padding": _decl(header, "padding", where, "header"),
        "header gap": _decl(header, "gap", where, "header"),
        "header flex-wrap": _decl(header, "flex-wrap", where, "header"),
        "header line-height": _decl(header, "line-height", where, "header"),
        # Width only. The colour is surface-local and is not a term of the height.
        "header border-bottom width": _decl(
            header, "border-bottom", where, "header").split()[0],
        # Every zone: its gap is the 12px between the mark and the name, and the row gap between a
        # zone's items once they wrap, which flex-wrap is what allows at all.
        "hzone align-items": _decl(hzone, "align-items", where, ".hzone"),
        "hzone gap": _decl(hzone, "gap", where, ".hzone"),
        "hzone flex-wrap": _decl(hzone, "flex-wrap", where, ".hzone"),
        # The identity zone's two items. The mark's declared box is the zone's height; the name's
        # font size, line height and family set its line box, and with the weight and tracking its
        # width, which is what decides the wrap in the first place.
        "brandmark height": _decl(mark, "height", where, ".brandmark"),
        "brandmark width": _decl(mark, "width", where, ".brandmark"),
        "wordmark font-family": _decl(wordmark, "font-family", where, ".wordmark"),
        "wordmark font-size": _decl(wordmark, "font-size", where, ".wordmark"),
        "wordmark font-weight": _decl(wordmark, "font-weight", where, ".wordmark"),
        "wordmark letter-spacing": _decl(wordmark, "letter-spacing", where, ".wordmark"),
        "wordmark line-height": _decl(wordmark, "line-height", where, ".wordmark"),
        # The right zone's one item: its font size sets its line box, and its white-space decides
        # whether it can ever take a second line.
        "tagline font-size": _decl(tagline, "font-size", where, ".tagline"),
        "tagline white-space": _decl(tagline, "white-space", where, ".tagline"),
        # The floor under the whole header: while the identity block fits on one line, the tab
        # boxes are the tallest thing in the header and this is the number that shows.
        "tab min-height": _decl(tab, "min-height", where, "nav tab"),
        # The nav CONTAINER's wrap, which decides how many ROWS of tab boxes the centre zone
        # holds. Each row is a tab min-height, so at any viewport too narrow for one row this is
        # the term that sets max(zone heights), and it is declared rather than left to the
        # initial nowrap for the same reason line-height is: an undeclared term is still a term.
        "nav flex-wrap": _decl(navbar, "flex-wrap", where, "nav container"),
    }


def test_every_chrome_surface_shares_one_vertical_fingerprint():
    """One set of declared chrome terms, carried by every surface that wears the chrome. FAILS IF
    any surface drifts on any declared term of the header's height, of its identity block's wrap or
    of its tab group's row count: a line-height, a font size, a gap, the padding, the border's
    width, the tab boxes' floor, the mark's box, the name's line height or family, the tagline's
    white-space or the nav container's wrap. This is the pin the 57.00px to 82.47px reflow needed
    and did not have, and it fails on the TERM rather than on a pixel count, so it means the same
    thing on a CI runner and on a laptop with different fonts installed.

    Because every term is a declared constant, one comparison covers every viewport: what agrees at
    1280px agrees at 375px. What it does NOT cover is zone content, which is contextual by design
    and can still separate two headers by a line; the module docstring names that limit."""
    surfaces = _surfaces()
    assert len(surfaces) >= 2, (
        "fewer than two chrome surfaces were discovered; the glob or the zone marker has moved "
        "and this pin would be comparing a surface against itself")
    prints = [(where, _fingerprint(where, text, is_pages)) for where, text, is_pages in surfaces]
    reference_where, reference = prints[0]
    for where, got in prints[1:]:
        drifted = {k: (reference[k], got[k]) for k in reference if reference[k] != got[k]}
        assert not drifted, (
            "the header's vertical geometry has drifted between two surfaces:\n"
            + "".join(f"  {k}\n"
                      f"      {reference_where:<28} {ref!r}\n"
                      f"      {where:<28} {mine!r}\n"
                      for k, (ref, mine) in sorted(drifted.items())))


def test_the_zones_can_still_wrap_and_the_tagline_cannot_spill_on_every_surface():
    """The zones' wrap is load-bearing and must stay possible: at 375px the tab group and About must be
    free to stack, and a header that refuses to wrap drags a phone-width page sideways. The tagline
    is the one item held to one line, so it must contain its own overflow instead.

    FAILS IF a surface reaches for flex-wrap:nowrap on the zones, or if the tagline's one line loses
    min-width:0, overflow:hidden or text-overflow:ellipsis: without them the line sizes its zero-basis
    zone's item to its full width, spills out of the zone's left edge and paints over the centre
    zone's right end, 92px of it at 761px of viewport: all of the About control and the end of the
    Collections tab."""
    for where, text, is_pages in _surfaces():
        hzone = _rule(text, r"(?m)^\s*\.hzone\{([^}]*)\}", where, ".hzone",
                      must_contain="display:")
        assert _decl(hzone, "flex-wrap", where, ".hzone") == "wrap", (
            f"{where}: the zones must stay free to wrap; without it three 112px tabs and the About "
            "control drag a 375px page sideways")
        tagline = _rule(text, r"(?m)^\s*\.tagline\{([^}]*)\}", where, ".tagline")
        for prop, value in (("white-space", "nowrap"), ("min-width", "0"), ("overflow", "hidden"),
                            ("text-overflow", "ellipsis")):
            assert _decl(tagline, prop, where, ".tagline") == value, (
                f"{where}: the tagline must declare {prop}:{value}, got {tagline!r}")


def _px(where, what, raw):
    m = re.fullmatch(r"(\d+(?:\.\d+)?)px", raw)
    assert m, f"{where}: {what} must be a px length, got {raw!r}"
    return float(m.group(1))


def test_the_tabs_floor_sets_the_desktop_header_on_every_surface():
    """From 761px up the header is one row, and its height is the tabs' floor plus its own padding and
    border, 57px, because no other zone is taller than the tabs. FAILS IF the mark's declared box
    reaches the tabs' 40px floor (it would set the header's height at every width), if the name's
    line box, font size times its unitless line height, outgrows the mark, if the tabs' floor or the
    header's padding or border moves, or if the mark stops being square. The tagline's line box is the
    one term read from font metrics rather than declared; at 14px it is well under the floor in any
    face this stack can resolve to."""
    for where, text, is_pages in _surfaces():
        print_ = _fingerprint(where, text, is_pages)
        tab = _px(where, "the tabs' floor", print_["tab min-height"])
        mark_h = _px(where, "the mark's height", print_["brandmark height"])
        mark_w = _px(where, "the mark's width", print_["brandmark width"])
        name = _px(where, "the name's size", print_["wordmark font-size"])
        line = float(print_["wordmark line-height"])
        assert tab == TAB_FLOOR, f"{where}: the tabs' floor is {TAB_FLOOR}px, got {tab}"
        assert mark_h == mark_w == MARK_SIZE < tab, (
            f"{where}: the mark is {MARK_SIZE}px square, shorter than the tabs' floor, got {mark_w}x{mark_h}")
        assert name * line <= mark_h, (
            f"{where}: the name's line box ({name * line}px) must not outgrow the mark ({mark_h}px)")
        assert print_["header padding"] == f"{HEADER_PADDING_BLOCK}px 18px", (
            f"{where}: the header's padding is a term of the 57px height, got {print_['header padding']!r}")
        assert print_["header border-bottom width"] == f"{HEADER_BORDER}px", (
            f"{where}: the header's border is a term of the 57px height")
        assert 2 * HEADER_PADDING_BLOCK + HEADER_BORDER + max(tab, mark_h, name * line) == DESKTOP_HEADER
