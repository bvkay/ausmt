"""Fixed nav geometry: the header's tab group sits at ONE x position on every page and view.

Both headers - the SPA's (portal/index.html) and the static pages' (engine/extract/_pages.py,
_CSS) - divide into three zones: .hleft (identity), .hcenter (the tab group and its two supporting
controls), .hright (the contextual status slot). With auto-basis sides (flex:1 1 auto) each side
zone grew with its OWN content, so the "centred" tab group was shoved to a different x position
wherever the identity block or the status slot changed width: the map view's live counter, the
surveys view's workspace line, the /surveys hub's static counts and a survey page's empty slot
each parked the tabs somewhere else. Equal ZERO-basis sides (flex:1 1 0 plus min-width:0 on BOTH
sides) hand the leftover space out evenly whatever the sides hold, so the centre group is
geometrically centred on every surface and the tabs stop moving between pages.

TWO HALVES, ONE GEOMETRY. test_both_headers_pin_the_zero_basis_geometry asserts the rule itself on
each surface (the geometry, as rendered CSS). test_the_two_headers_carry_identical_zone_rules
asserts the SPA's zone rules and the static pages' are character-identical, so an edit to one
surface cannot silently re-float the other while both stay locally plausible.

WHY THE ENGINE HALF LIVES HERE rather than in engine/tests: portal-ci runs on portal/** AND on
engine/extract/_pages.py (see .github/workflows/portal-ci.yml), so a change to either header fires
this lane; the engine lane triggers on engine/** alone and cannot see an index.html edit. The
engine half is read from _pages.py's SOURCE TEXT, the same mechanism as
test_collection_colours.py: _pages.py cannot simply be imported (it sibling-imports _au_outline
and _stationcheck, which need the engine's own path set up), and re-typing its CSS here would only
pin a third copy of it.

The narrow-width wrap is part of the bargain: at 760px and under, both headers stack their zones
full-width, which is what keeps three 112px tabs from dragging a 375px page sideways. Zero-basis
sides must not cost that, so the stacking override is pinned on both surfaces too, AFTER the zone
rules - the two selectors tie on specificity, and source order is what makes the wrap win.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # portal/
INDEX = ROOT / "index.html"
PAGES_PY = ROOT.parent / "engine" / "extract" / "_pages.py"

ZONES = ("hleft", "hcenter", "hright")

# Both surfaces, by the path a failure message should name.
SURFACES = (("portal/index.html", INDEX), ("engine/extract/_pages.py", PAGES_PY))


def _zone_rules(text, where):
    """The three zone rule bodies, each required to be declared exactly once (a second declaration
    of a zone would silently override the pinned geometry at equal specificity)."""
    out = {}
    for zone in ZONES:
        bodies = re.findall(r"\." + zone + r"\{([^}]*)\}", text)
        assert len(bodies) == 1, (
            f"{where}: expected exactly one .{zone} rule, found {len(bodies)}")
        out[zone] = bodies[0]
    return out


def test_both_headers_pin_the_zero_basis_geometry():
    """The rule itself, on each surface: equal zero-basis sides that may shrink below their
    content, a content-sized centre, and a right slot whose content stays right-aligned. FAILS IF
    either side zone regrows an auto basis (the tab group would move as side content changes), if
    min-width:0 is dropped (a long counter would refuse to shrink and shove the tabs anyway), or if
    the right slot stops right-aligning its content."""
    for where, path in SURFACES:
        rules = _zone_rules(path.read_text(encoding="utf-8"), where)
        for side in ("hleft", "hright"):
            assert "flex:1 1 0" in rules[side], (
                f"{where}: .{side} must take an equal ZERO-basis share (flex:1 1 0), "
                f"got {rules[side]!r}")
            assert "min-width:0" in rules[side], (
                f"{where}: .{side} must carry min-width:0 so it can shrink below its content "
                f"instead of displacing the tab group, got {rules[side]!r}")
        assert "flex:0 1 auto" in rules["hcenter"], (
            f"{where}: .hcenter stays content-sized (flex:0 1 auto), got {rules['hcenter']!r}")
        assert "justify-content:flex-end" in rules["hright"], (
            f"{where}: the right slot's content stays right-aligned, got {rules['hright']!r}")


def test_the_two_headers_carry_identical_zone_rules():
    """The parity: one geometry, stated once per surface, character for character. FAILS IF the two
    headers' zone rules drift apart in any way at all - a reader moving between the map and a hub
    would watch the nav jump."""
    spa = _zone_rules(INDEX.read_text(encoding="utf-8"), "portal/index.html")
    pages = _zone_rules(PAGES_PY.read_text(encoding="utf-8"), "engine/extract/_pages.py")
    for zone in ZONES:
        assert spa[zone] == pages[zone], (
            f".{zone} has drifted between the two headers:\n"
            f"  portal/index.html          {spa[zone]!r}\n"
            f"  engine/extract/_pages.py   {pages[zone]!r}")


# --------------------------------------------------------------------------- the nav itself
#
# The zone rules alone were proven insufficient at review: with both centres geometrically
# centred, the two navs still resolved DIFFERENT intrinsic widths (146px tabs on the pages vs
# 112px on the SPA, a 47.5px x offset at 1280px), because three inputs the zone rules never see
# differed between the surfaces: the box model (the SPA's universal border-box vs the pages'
# unreset content-box, which turns the shared min-width:112px into 146 rendered pixels), the nav
# container's wrap mode, and the font stack the labels measure in. A tab's rendered width is a
# function of ALL of them, so every one is pinned pairwise here.

# The geometry-bearing declarations of a tab box. Colours, hover and cursor are surface-local
# and deliberately NOT compared.
TAB_GEOMETRY = ("flex:1;", "min-width:112px", "min-height:40px", "padding:0 16px",
                "font-size:14px", "font-weight:600", "border:1px solid ")


def _rule_body(text, pattern, where):
    bodies = re.findall(pattern, text)
    assert len(bodies) == 1, f"{where}: expected exactly one match for {pattern!r}, got {len(bodies)}"
    # The SPA states some rules across several source lines; fold the line breaks away so the
    # declaration list compares as one string.
    return re.sub(r"\s*\n\s*", "", bodies[0])


def _nav_container(text, where):
    """The nav CONTAINER rule body, on either surface's spelling of the selector. Anchored on the
    brace so that `nav a{` can never answer for `nav{`."""
    sel = (r"(?m)^\s*header\.site nav\{([^}]*)\}" if where.endswith(".py")
           else r"(?m)^\s*nav\{([^}]*)\}")
    return _rule_body(text, sel, where)


def test_every_chrome_surface_carries_one_nav_container_rule():
    """The nav CONTAINER rule, character-identical on EVERY surface wearing the chrome. FAILS IF
    the wrap modes (or the gap, or the display) drift apart: a nowrap container and a wrap
    container hand the same three min-width:112px tabs different row counts and different resolved
    widths, which is exactly the 47.5px tab-group offset the C9 review measured between the SPA and
    the pages at 1280px.

    It compares all five surfaces rather than the SPA-and-pages pair this pin started as, because
    the pair is precisely what let the defect through: releases.html and about.html each keep their
    OWN hand-maintained copy of the chrome, no pin ever read either one's nav rule, and both sat on
    a bare `display:flex;gap:6px`. With no flex-wrap the three 112px tabs cannot stack, so at 375px
    those two rendered a 174px header where the SPA, the generated pages and brand.html rendered
    220px, and the nav overran its own zone by 9px (right edge 366 against a 357px content edge)."""
    prints = [(where, _nav_container(text, where)) for where, text in _chrome_surfaces()]
    assert len(prints) >= 2, (
        "fewer than two chrome surfaces were discovered; the glob or the zone marker has moved "
        "and this pin would be comparing a surface against itself")
    reference_where, reference = prints[0]
    for where, body in prints[1:]:
        assert body == reference, (
            "the nav container rule has drifted between two surfaces:\n"
            f"  {reference_where:<28} {reference!r}\n"
            f"  {where:<28} {body!r}")


def test_every_tab_box_shares_every_geometry_input():
    """Each tab rule (the SPA's nav a AND nav button, the pages' nav a) carries the full set of
    geometry-bearing declarations, so all three kinds of tab render the same box. FAILS IF any
    surface drops or alters one: the surfaces would size their tabs from different inputs and
    the group's x would split by surface again."""
    spa_text = INDEX.read_text(encoding="utf-8")
    pages_text = PAGES_PY.read_text(encoding="utf-8")
    rules = {
        "portal/index.html nav a": _rule_body(spa_text, r"(?m)^\s*nav a\{([^}]*)\}",
                                              "portal/index.html"),
        "portal/index.html nav button": _rule_body(spa_text, r"(?m)^\s*nav button\{([^}]*)\}",
                                                   "portal/index.html"),
        "engine/extract/_pages.py nav a": _rule_body(pages_text,
                                                     r"header\.site nav a\{([^}]*)\}",
                                                     "engine/extract/_pages.py"),
    }
    for where, body in rules.items():
        for decl in TAB_GEOMETRY:
            assert decl in body, f"{where}: tab rule must carry {decl!r}, got {body!r}"


def test_the_two_headers_share_one_box_model():
    """min-width:112px means one rendered width only if both surfaces measure it in the same box
    model. The SPA resets everything to border-box; the pages sheet deliberately has no universal
    reset, so its header carries its own scoped one. FAILS IF either goes missing: content-box
    turns the same declarations into 146px tabs (112 + 32 padding + 2 border), the dominant term
    of the measured 47.5px offset."""
    assert "*{box-sizing:border-box" in INDEX.read_text(encoding="utf-8"), (
        "portal/index.html: the universal border-box reset is gone; the SPA tab boxes would "
        "resolve min-width:112px in a different box model than the pages'")
    assert "header.site,header.site *{box-sizing:border-box}" in PAGES_PY.read_text(
        encoding="utf-8"), (
        "engine/extract/_pages.py: the header-scoped border-box rule is gone; the pages tab "
        "boxes would render 146px against the SPA's 112px")


def test_the_two_headers_measure_text_in_one_font_stack():
    """The tab and control labels must measure identically on both surfaces, so the header on
    the pages declares the SPA's own --sans stack. FAILS IF either side's stack moves without
    the other: About and Contribute rendered ~2.4 and ~4.6px wider on the SPA under system-ui
    than the pages' -apple-system-first stack, a ~3.5px centre-group offset on its own."""
    spa = re.findall(r"--sans:([^;}]*)[;}]", INDEX.read_text(encoding="utf-8"))
    assert len(spa) == 1, f"portal/index.html: expected exactly one --sans, got {len(spa)}"
    pages_header = _rule_body(PAGES_PY.read_text(encoding="utf-8"),
                              r"(?m)^\s*header\.site\{([^}]*)\}", "engine/extract/_pages.py")
    m = re.search(r"font-family:([^;}]*)", pages_header)
    assert m, ("engine/extract/_pages.py: header.site declares no font-family; the pages "
               "header would measure its labels in the page body's stack instead of the SPA's")
    assert m.group(1) == spa[0], (
        "the header font stacks have drifted between the two surfaces:\n"
        f"  portal/index.html --sans           {spa[0]!r}\n"
        f"  engine/extract/_pages.py header.site {m.group(1)!r}")


# --------------------------------------------------------------------------- the identity mark
#
# Brand-assets lane E3: the header identity is the AusMT mark on EVERY surface, replacing the
# AuScope-derived symbol the SPA carried alone. The relationship with AuScope stays explicit in
# footer and About content; it is no longer embedded in the lockup.
#
# The mark is a fixed 30 x 30 box, which is why it can join the zero-basis .hleft zone without
# moving the centre tabs: a flex:1 1 0 side hands its leftover space out evenly whatever it holds,
# so a wider identity block changes the SIDE's content, never the centre group's x. The pins above
# hold that geometry; these hold the identity itself, pairwise, for the same reason the zone rules
# are held pairwise - an edit to one surface must not leave the other on a different mark.
MARK_SRC = "/vendor/brand/ausmt-mark.svg"
MARK_RULE = ".brandmark{height:30px;width:30px;display:block;flex:none}"


def test_both_headers_carry_the_same_ausmt_mark():
    """FAILS IF either surface loses the mark, points at a different file, or drifts to a different
    sizing rule. Same-origin only: an http, https, protocol-relative or data src fails here, which is
    the half of the pages' old zero-src rule that was ever load-bearing."""
    for where, path in SURFACES:
        text = path.read_text(encoding="utf-8")
        assert f'<img class="brandmark" src="{MARK_SRC}" alt="AusMT" width="30" height="30">' in text, (
            f"{where}: the header identity must be the AusMT mark at {MARK_SRC}")
        assert MARK_RULE in text, f"{where}: the mark must carry the shared sizing rule {MARK_RULE!r}"
        for scheme in ("http://", "https://", '"//', "data:"):
            assert f'<img class="brandmark" src="{scheme}' not in text, (
                f"{where}: the identity mark is same-origin only; {scheme!r} is never a mark src")


def test_the_mark_the_two_headers_name_is_a_real_committed_asset():
    """FAILS IF the header points at a file the portal does not ship. Both surfaces are served from
    the same origin by the portal image, so one missing file is a broken mark on every page of the
    site at once."""
    asset = ROOT / MARK_SRC.lstrip("/")
    assert asset.is_file(), f"the header names {MARK_SRC}, which the portal does not ship"
    assert "<circle" in asset.read_text(encoding="utf-8"), \
        f"{MARK_SRC} must be the generated vector mark, not a placeholder"


# EVERY surface, not just the pair above. The two pins above compare the SPA against the pages
# sheet, which is where the zone geometry can drift; they cannot see releases.html or
# add-survey.html, each of which carries its OWN copy of the chrome. Those two kept the AuScope
# symbol after the SPA and the 2,655 generated pages had switched, so a reader following the
# header's own "Contribute a survey" link watched the site's identity change under them.
#
# NO PAGE IS EXEMPT. about.html was the last one, its identity slot held open while the owner ruled
# on that header; the ruling is that about wears the chrome every other surface wears. There is no
# exemption list here any more, and the pages are discovered from the filesystem, so a page cannot
# arrive with an identity of its own. 404.html is a bare error document with no header at all.
MARK_IMG = f'<img class="brandmark" src="{MARK_SRC}" alt="AusMT" width="30" height="30">'

# The IDENTITY SLOT, by the class that expressed the one exception to it. A page's identity is
# .brandmark; .auscope-logo was the AuScope symbol standing in for one. Keyed on the CLASS rather
# than on the filename of the image, because EVERY page names that file as the parent-organisation
# mark below: the two are different slots doing different jobs, and only one of them is an identity.
IDENTITY_CLASS = 'class="auscope-logo"'


def _chrome_pages():
    """Every portal document that ships the site chrome, by name."""
    return [p for p in sorted(ROOT.glob("*.html")) if "<header>" in p.read_text(encoding="utf-8")]


def test_every_static_chrome_page_carries_the_ausmt_mark():
    """FAILS IF a portal page that wears the chrome shows anything but the AusMT mark as its
    identity, and equally if a NEW page appears wearing the chrome without one. Discovered from the
    filesystem rather than from a list, so adding a page cannot quietly add a sixth identity, and
    no page is skipped."""
    seen = []
    for page in _chrome_pages():
        seen.append(page.name)
        text = page.read_text(encoding="utf-8")
        assert MARK_IMG in text, (
            f"portal/{page.name}: the header identity must be the AusMT mark at {MARK_SRC}")
        assert MARK_RULE in text, (
            f"portal/{page.name}: the mark must carry the shared sizing rule {MARK_RULE!r}")
        assert IDENTITY_CLASS not in text, (
            f"portal/{page.name}: the AuScope symbol is not this site's header IDENTITY; it states "
            "the parent organisation from the right zone instead (.orgmark)")
    assert seen, "no chrome page was discovered; the glob or the header marker has moved"


def test_no_header_stands_the_auscope_symbol_in_for_an_identity():
    """The ruling that closed the carve-out, pinned as one. FAILS IF any page carries the AuScope
    symbol in its identity slot: the AusMT mark opens every header, and the symbol states the parent
    organisation from the right zone instead. A header copied from the pre-ruling about.html is
    exactly how the old slot comes back.

    Scoped to the identity CLASS, not to the image file: every page carries that file, as the
    parent-organisation mark in the right zone, which is a different slot and not an identity."""
    holders = [p.name for p in sorted(ROOT.glob("*.html"))
               if IDENTITY_CLASS in p.read_text(encoding="utf-8")]
    assert holders == [], (
        "no page may carry the AuScope symbol as its header identity; the AusMT mark opens every "
        f"header and the symbol closes it from the right zone, got {holders}")


# ------------------------------------------------------------------- the parent-organisation mark
#
# The AuScope mark closes the header, top right, on every surface of the site. It is NOT an identity
# and it is not interchangeable with the pins above: the left zone says what this site IS, and this
# says whose service it is. Held on every surface for the reason the identity is, and character for
# character, because the two surfaces are one header.
#
# The GEOMETRY argument is the identity mark's, restated on the other side. A fixed-height box inside
# the zero-basis .hright zone changes that SIDE's content, never the centre tab group's x, so adding
# it cannot move the nav that the whole module above exists to hold still.
ORG_SRC = "/vendor/auscope-icon-white.png"
ORG_IMG = (f'<a class="orgmark" href="https://www.auscope.org.au" target="_blank" '
           f'rel="noopener noreferrer" title="AuScope">'
           f'<img src="{ORG_SRC}" alt="AuScope" width="29" height="30"></a>')
ORG_RULE = ".orgmark{display:flex;align-items:center;flex:none;margin-left:16px}"
ORG_IMG_RULE = ".orgmark img{height:30px;width:auto;display:block}"

# NO SURFACE IS EXEMPT from the parent mark either, and that is the same ruling seen from the other
# side. about.html was exempt for a stated reason: it carried the AuScope symbol as its header
# IDENTITY, and a parent mark beside it would have put the same image in one header twice. The
# ruling took the symbol out of that identity slot, so the exemption went with it and every surface
# now closes its header the same way.


def test_no_chrome_page_is_exempt_from_either_mark():
    """The guard over the two per-surface pins around it: neither may be hollowed out by skipping a
    page. FAILS IF any discovered chrome page is missing either mark, the AusMT mark that opens its
    header or the AuScope mark that closes it.

    It replaces the pin that held the two carve-out names equal. That pin was worth running only
    while each side could move on its own; with no carve-out left, what is worth holding is that
    every page satisfies BOTH, which is the stronger half of what the pair used to say."""
    pages = _chrome_pages()
    assert pages, "no chrome page was discovered; the glob or the header marker has moved"
    for page in pages:
        text = page.read_text(encoding="utf-8")
        assert MARK_IMG in text, (
            f"portal/{page.name}: the AusMT mark must open this header; no page is exempt")
        assert text.count(ORG_IMG) == 1, (
            f"portal/{page.name}: the AuScope mark must close this header exactly once; no page "
            f"is exempt, found {text.count(ORG_IMG)}")


def test_every_chrome_surface_carries_the_auscope_mark_exactly_once():
    """FAILS IF a surface wearing the chrome loses the parent-organisation mark, carries it twice,
    points it at a different file or a different destination, or drifts off the shared sizing rule.
    A second copy is a real failure mode here and not a tidiness one: the mark is added at the END
    of a zone, so a careless edit appends rather than replaces and the header grows two of them.

    Same-origin only for the image, for the reason the identity mark is: these documents are served
    beside /vendor by the portal image, and an external src would be a third-party fetch on every
    page of the site at once. The LINK is external by definition and carries the new-tab pairing
    (rel noopener noreferrer) the rest of the site's outbound links do."""
    surfaces = [("engine/extract/_pages.py", PAGES_PY.read_text(encoding="utf-8"))]
    surfaces += [(f"portal/{p.name}", p.read_text(encoding="utf-8")) for p in _chrome_pages()]
    assert len(surfaces) >= 2, "no chrome surface was discovered; the glob or the marker has moved"
    for where, text in surfaces:
        assert text.count(ORG_IMG) == 1, (
            f"{where}: the header must carry the AuScope mark exactly once, as {ORG_IMG!r}; "
            f"found {text.count(ORG_IMG)}")
        assert ORG_RULE in text, f"{where}: the mark must carry the shared rule {ORG_RULE!r}"
        assert ORG_IMG_RULE in text, f"{where}: the mark must carry {ORG_IMG_RULE!r}"


# The FILE, bounded per page. Every pin above is scoped to a slot: to the .auscope-logo class, to
# the parent mark's whole anchor literal, or to the carved-out page's header alone. None of them
# says how often the IMAGE may be named, so a second loose copy of it, in a body, in a url() or as a
# preload, satisfies the lot. Counting the filename is what makes one mark per page a statement
# about the image rather than about one spelling of it in one slot.
ORG_ASSET = ORG_SRC.rsplit("/", 1)[-1]

# One appearance per chrome page: the parent mark in the right zone, and nowhere else. It was one
# number covering two slots while the carved-out page named the file as its identity instead; there
# is one slot now, and the number is still one.
ORG_ASSET_PER_PAGE = 1


def test_no_chrome_page_names_the_auscope_image_more_than_its_one_slot():
    """FAILS IF a chrome page carries the AuScope image a second time, in any slot and by either
    spelling. The mark is appended to a zone, so a careless edit adds rather than replaces, and a
    header holding two copies of the same image reads as a mistake to every visitor while passing
    every slot-scoped pin above it."""
    pages = _chrome_pages()
    assert pages, "no chrome page was discovered; the glob or the header marker has moved"
    for page in pages:
        count = page.read_text(encoding="utf-8").count(ORG_ASSET)
        assert count == ORG_ASSET_PER_PAGE, (
            f"portal/{page.name}: the AuScope image may be named {ORG_ASSET_PER_PAGE} time on a "
            f"chrome page, as the parent mark that closes it; found {count}")


def test_the_auscope_mark_closes_the_header_after_the_primary_nav():
    """Position and tab order in one pin, read off the ORDER of the header's own markup. FAILS IF
    the mark moves ahead of the centre zone (the nav lives there, so the mark would take a tab stop
    before the site's primary controls) or out of the right zone (it would stop being the top-right
    corner). The engine surface is read from its source literal, which is the string it emits."""
    for where, path in SURFACES:
        # The engine's header is a source EXPRESSION, so the zone that carries the mark holds the
        # name of the literal rather than the literal. Resolving it here is what makes the two
        # surfaces comparable by ORDER; that the name resolves to this exact string is the pin
        # above, which counts the literal itself.
        text = path.read_text(encoding="utf-8").replace("{_ORG_MARK}", ORG_IMG)
        header = text.split("hzone hleft", 1)[1].split("</header>", 1)[0]
        assert ORG_IMG in header, f"{where}: the mark must sit inside the header itself"
        for zone in ("hzone hcenter", "hzone hright"):
            assert zone in header and header.index(zone) < header.index(ORG_IMG), (
                f"{where}: the mark must follow the {zone!r} zone; it belongs to the right zone, "
                f"after the nav, and never ahead of it")


def test_the_auscope_mark_names_a_real_committed_asset():
    """FAILS IF the header points at a file the portal does not ship. Both surfaces are served from
    the same origin by the portal image, so one missing file is a broken mark on every page of the
    site at once. The size assertion is what tells a placeholder from the real artefact."""
    asset = ROOT / ORG_SRC.lstrip("/")
    assert asset.is_file(), f"the header names {ORG_SRC}, which the portal does not ship"
    data = asset.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{ORG_SRC} must be a PNG"
    # Colour type 6 is RGBA: the mark is white, so it reads on this chrome only because it carries
    # its own transparency rather than a background it would paint over the header.
    assert data[25] == 6, f"{ORG_SRC} must keep its alpha channel (PNG colour type 6)"


def test_the_narrow_width_stacking_still_wins_under_760px():
    """The wrap behaviour the zero-basis rule must not cost. FAILS IF either surface loses the
    760px full-width stacking override, or if it stops coming AFTER the zone rules (the selectors
    tie on specificity, so source order alone decides which wins under 760px)."""
    for where, path in SURFACES:
        text = path.read_text(encoding="utf-8")
        base = text.index(".hleft{")
        # Anchored past the zone rules: an earlier, unrelated 760px block (the pages' hero-map
        # stack) must not satisfy this pin on the zones' behalf.
        media = re.search(r"@media\s*\(max-width:760px\)", text[base:])
        assert media, f"{where}: the 760px stacking block must follow the zone rules"
        stack = text.find(".hzone{flex:1 1 100%;justify-content:flex-start}",
                          base + media.start())
        assert stack > 0, (
            f"{where}: the full-width stacking override must live inside the 760px block that "
            f"follows the zone rules; without it three 112px tabs drag a 375px page sideways")


# --------------------------------------------------------------------------- the header's HEIGHT
#
# EVERY pin above measures the header HORIZONTALLY: the tab group's x, the zone widths, the tab box's
# own width, the font stack the labels are measured in. A header can therefore change shape
# VERTICALLY and pass all of them at once, which is exactly what the 30px identity mark did. The mark
# pushed the identity block past the width of its own zone, the tagline dropped onto a second line,
# and the generated pages' header grew from 57.00px to 82.47px at 1280px while nothing horizontal
# moved by a single pixel. Measured in Chrome at a device scale factor of 1.
#
# THE HEIGHT FORMULA. The header is a wrapping flex row of three zones, so
#
#     header  = padding-block + border-bottom + max(zone heights)
#
# and once the identity block wraps, that zone's own height is
#
#     hleft   = line-box(wordmark) + row-gap + line-box(tagline)
#
# Every term on the right is a declared constant except the two line boxes, and a line box is
# font-size x line-height. The font sizes are declared, and identical on every surface. The
# LINE-HEIGHT was not declared at all: the header inherited it from whatever the host document had
# set on body, and the documents carrying this header set three different things. The SPA leaves body
# at normal; the static pages' sheet sets font:16px/1.55; releases, about and brand set
# line-height:1.6. So one header rule rendered three different heights at 1280px:
#
#     portal/index.html          74.00px   line-height normal
#     engine/extract/_pages.py   82.47px   1.55, inherited from body
#     portal/brand.html          84.19px   1.6, inherited from body
#
# A global component must not take its vertical rhythm from the prose of whichever page it is dropped
# into. The header declares its own, and line-height is pinned on every surface that wears the chrome
# because it is the one term of the formula a host document can change from the outside.
HEADER_LINE_HEIGHT = "line-height:normal"


def _chrome_surfaces():
    """Every surface carrying the three-zone header, by the path a failure message should name: the
    static pages' sheet, plus every portal document that declares the zones. Discovered from the
    filesystem rather than from a list, so a new page wearing the chrome is pinned the day it
    appears rather than the day someone remembers to add it here."""
    out = [("engine/extract/_pages.py", PAGES_PY.read_text(encoding="utf-8"))]
    for page in sorted(ROOT.glob("*.html")):
        text = page.read_text(encoding="utf-8")
        if ".hzone{" in text:
            out.append((f"portal/{page.name}", text))
    return out


def _header_rule(text, where):
    """The header's own rule body, on either surface's spelling of the selector."""
    return _rule_body(text, r"(?m)^\s*header(?:\.site)?\{([^}]*)\}", where)


def test_every_chrome_surface_declares_the_headers_own_line_height():
    """The header's vertical rhythm belongs to the header. FAILS IF any surface leaves line-height
    to be inherited from its host document's body: the identity block's two line boxes are
    font-size x line-height, so an inherited 1.55 or 1.6 renders the SAME header 8.47px or 10.19px
    taller than the SPA's the moment that block wraps. Different heights on different pages is a
    different header on different pages, and the standing ruling is one header on every surface."""
    surfaces = _chrome_surfaces()
    assert len(surfaces) >= 2, "no chrome surfaces were discovered; the glob or the zone marker moved"
    for where, text in surfaces:
        body = _header_rule(text, where)
        assert HEADER_LINE_HEIGHT in body, (
            f"{where}: the header rule must declare {HEADER_LINE_HEIGHT!r}, so that the host "
            f"document's body prose line-height cannot change the header's height; got {body!r}")


def test_every_chrome_surface_carries_the_same_zone_geometry():
    """The zone rules, character-identical on EVERY surface wearing the chrome, not just across the
    pair above. The pair covers the SPA and the generated pages, which is where the geometry was
    ruled; releases.html and about.html each carry their OWN copy of the chrome, and both kept the
    auto-basis sides the C9 ruling replaced. An auto basis sizes each side zone from its own content,
    so on those two pages the identity block set the width of its own zone and shoved the tab group
    out to x=525.63 and x=525.27 at 1280px, while the SPA, the generated pages and brand.html all
    sat at x=350.83. A reader following the header's own Releases or About link watched the nav jump
    roughly 175px sideways and jump back on the way out. FAILS IF any surface's zone rules drift from
    the SPA's in any way at all."""
    reference = _zone_rules(INDEX.read_text(encoding="utf-8"), "portal/index.html")
    for where, text in _chrome_surfaces():
        rules = _zone_rules(text, where)
        for zone in ZONES:
            assert rules[zone] == reference[zone], (
                f".{zone} has drifted from the ruled zone geometry:\n"
                f"  portal/index.html            {reference[zone]!r}\n"
                f"  {where:<28} {rules[zone]!r}")
