"""The header's VERTICAL geometry, pinned on every surface that wears the site chrome.

WHY THIS FILE EXISTS. tests/test_header_geometry_parity.py pins the header HORIZONTALLY, and it does
that thoroughly: the tab group's x, the zone widths and their flex bases, the tab box's own width,
the box model the width is measured in, and the font stack the labels are measured with. Not one of
those pins can see the header get TALLER. So when the 30px identity mark landed, the identity block
outgrew its zone, the tagline dropped onto a second line, and the generated pages' header went from
57.00px to 82.47px at 1280px with every horizontal pin still green, the C9 four-surface parity proof
still green, and the framing classification still reporting a header-identity diff. A 45 per cent
change in the height of every page's header passed the whole gate.

The gap was systematic rather than unlucky, so the close is systematic too. The header's height is

    header = padding-block + border-bottom + max(zone heights)

and TWO of the zones can grow. The identity zone, once its content wraps, is

    hleft  = line-box(first line) + row-gap + line-box(tagline)

where a line box is font-size x line-height and the first line is the taller of the mark box and the
wordmark's own line box. WHETHER it wraps at a given viewport is the other half:

    wraps  <=>  mark-width + gap + wordmark-width + gap + tagline-width  >  zone-width

The tab group's zone grows the same way, in whole tab rows:

    hcenter = rows x tab-min-height + (rows - 1) x row-gap
    rows    = 1 while the nav container may not wrap, whatever the width; otherwise it grows as
              soon as the tabs' own min-width floors plus their gaps exceed the zone's width

That second expression is why the nav container's flex-wrap is a term of the HEIGHT and not a detail
of the nav's own layout. A nowrap container pins rows at 1 and holds the header short while the tabs
overrun the zone sideways instead; a wrapping one stacks them and the header grows by a whole tab
row. Measured at 375px, one declaration apart: 220px with the wrap, 174px without it, and without it
the tab group's right edge lands at 366px against a 357px content edge.

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

Zone CONTENT is not compared either, and that is the honest limit of this pin. Agreement here means
two surfaces resolve the same height from the chrome they DECLARE; it is not a promise that two
headers measure the same number of pixels, because the right zone is contextual by design. The SPA's
status slot carries a live counter, and at 375px that one 15px line renders index.html's header at
235px against brand.html's 220px with every term in this file in agreement. That is the pin working
as intended, not a drift: the chrome is shared, the contents of the contextual slot are not.

NO CARVE-OUT. about.html carried the AuScope symbol as its identity mark, under a rule of its own,
while the rule is on that header; this file must not read the mark's height from whichever of the
two rules a surface happened to use. The rule put the AusMT mark in that slot like everywhere
else, so there is one rule to read and every surface must carry it. The height is the only thing a
mark contributes to the header's height, and every surface declares it as 30px.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # portal/
PAGES_PY = ROOT.parent / "engine" / "extract" / "_pages.py"

# The identity mark rule. One spelling, on every surface: the AusMT mark opens every header.
MARK_RULE = ".brandmark"


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

    found = re.findall(r"(?m)^\s*" + re.escape(MARK_RULE) + r"\{([^}]*)\}", text)
    assert len(found) == 1, (
        f"{where}: expected exactly one {MARK_RULE} rule, found {len(found)}; it is where the "
        "header's first line takes its height from")
    mark = re.sub(r"\s*\n\s*", "", found[0])

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
        # The identity zone: its row-gap is the space between the wordmark's line and the
        # tagline's once the block wraps, and flex-wrap is what allows the wrap at all.
        "hzone align-items": _decl(hzone, "align-items", where, ".hzone"),
        "hzone gap": _decl(hzone, "gap", where, ".hzone"),
        "hzone flex-wrap": _decl(hzone, "flex-wrap", where, ".hzone"),
        # The three identity items. Their font metrics set the line boxes, and their widths are
        # what decide the wrap in the first place.
        "mark height": _decl(mark, "height", where, "identity mark"),
        "wordmark font-size": _decl(wordmark, "font-size", where, ".wordmark"),
        "wordmark font-weight": _decl(wordmark, "font-weight", where, ".wordmark"),
        "wordmark letter-spacing": _decl(wordmark, "letter-spacing", where, ".wordmark"),
        "tagline font-size": _decl(tagline, "font-size", where, ".tagline"),
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
    of its tab group's row count: a line-height, a font size, a gap, the mark's height, the padding,
    the border's width, the tab boxes' floor or the nav container's wrap. This is the pin the
    57.00px to 82.47px reflow needed and did not have, and it fails on the TERM rather than on a
    pixel count, so it means the same thing on a CI runner and on a laptop with different fonts
    installed.

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


def test_the_identity_block_can_still_wrap_on_every_surface():
    """The wrap itself is load-bearing and must stay possible. FAILS IF a surface reaches for
    flex-wrap:nowrap or a nowrap white-space on the identity block to force one line: at 375px the
    identity block MUST be free to stack, and a header that refuses to wrap drags a phone-width page
    sideways instead. The fix for an unwanted wrap is the zone's width or the block's own width,
    never taking the wrap away."""
    for where, text, is_pages in _surfaces():
        hzone = _rule(text, r"(?m)^\s*\.hzone\{([^}]*)\}", where, ".hzone",
                      must_contain="display:")
        assert _decl(hzone, "flex-wrap", where, ".hzone") == "wrap", (
            f"{where}: the identity zone must stay free to wrap; without it three 112px tabs and a "
            "38 character tagline drag a 375px page sideways")
        tagline = _rule(text, r"(?m)^\s*\.tagline\{([^}]*)\}", where, ".tagline")
        assert "nowrap" not in tagline, (
            f"{where}: the tagline must not be pinned to one line with white-space:nowrap; on a "
            f"narrow viewport it would overflow the header instead of wrapping, got {tagline!r}")
