"""Fixed nav geometry: the header's tab group sits at ONE x position on every page and view.

Both headers - the SPA's (portal/index.html) and the static pages' (engine/extract/_pages.py,
_CSS) - divide into three zones: .hleft (the AuScope mark and AusMT's name), .hcenter (the tab group
and the About control), .hright (the AuScope and NCRIS lock-up). With auto-basis sides (flex:1 1
auto) each side zone grew with its OWN content, so the "centred" tab group was shoved to a different
x position wherever a side zone changed width: while the right zone carried the contextual counts,
the map view's live counter, the surveys view's workspace line and a survey page's empty slot each
parked the tabs somewhere else. Equal ZERO-basis sides (flex:1 1 0 plus min-width:0 on BOTH sides)
hand the leftover space out evenly whatever the sides hold, so the centre group is geometrically
centred on every surface and the tabs stop moving between pages.

TWO HALVES, ONE GEOMETRY. test_both_headers_pin_the_zero_basis_geometry asserts the rule itself on
each surface (the geometry, as rendered CSS). test_the_two_headers_carry_identical_zone_rules
asserts the SPA's zone rules and the static pages' are character-identical, so an edit to one
surface cannot silently re-float the other while both stay locally plausible.

WHY THE ENGINE HALF LIVES HERE rather than in engine/tests: portal-ci runs on portal/** AND on
engine/extract/_pages.py (see .github/workflows/portal-ci.yml), so a change to either header fires
this module; the engine workflow triggers on engine/** alone and cannot see an index.html edit. The
engine half is read from _pages.py's SOURCE TEXT, the same mechanism as
test_collection_colours.py: _pages.py cannot simply be imported (it sibling-imports _au_outline
and _stationcheck, which need the engine's own path set up), and re-typing its CSS here would only
pin a third copy of it.

The narrow-width wrap is part of the bargain: at 760px and under, both headers stack their zones
full-width, which is what keeps three 112px tabs from dragging a 375px page sideways. Zero-basis
sides must not cost that, so the stacking override is pinned on both surfaces too, AFTER the zone
rules - the two selectors tie on specificity, and source order is what makes the wrap win.
"""
import hashlib
import re
import struct
from pathlib import Path

from chrome_contract import (LIGHT, LOCKUP, LOCKUP_DARK, LOCKUP_LIGHT, LOCKUP_PIXELS, LOCKUP_RULES,
                             MARK_DARK, MARK_LIGHT, MARK_PAIR, MARK_RULE, PAGE_IDENTITY, THEME_RULES,
                             flat, header_inner, header_markup, token_blocks, tokens)
from engine_chrome import site_header

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
    widths, which is exactly the 47.5px tab-group offset the review measured between the SPA and
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
    """The tab and control labels must measure identically on both surfaces, so the header on the
    pages declares the SPA's own --sans stack, either spelt out or as var(--sans) over a token block
    that declares the same stack. FAILS IF either side's stack moves without the other: About rendered
    ~2.4px wider on the SPA under system-ui than under the pages' -apple-system-first stack, a
    centre-group offset on its own."""
    spa = re.findall(r"--sans:([^;}]*)[;}]", INDEX.read_text(encoding="utf-8"))
    assert len(spa) == 1, f"portal/index.html: expected exactly one --sans, got {len(spa)}"
    assert spa[0] == LIGHT["--sans"], f"portal/index.html: --sans is {spa[0]!r}, not the contract stack"
    pages_text = PAGES_PY.read_text(encoding="utf-8")
    pages_header = _rule_body(pages_text, r"(?m)^\s*header\.site\{([^}]*)\}", "engine/extract/_pages.py")
    m = re.search(r"font-family:([^;}]*)", pages_header)
    assert m, ("engine/extract/_pages.py: header.site declares no font-family; the pages "
               "header would measure its labels in the page body's stack instead of the SPA's")
    stack = m.group(1)
    if stack == "var(--sans)":
        stack = token_blocks(pages_text)[0].get("--sans", stack)
    assert stack == spa[0], (
        "the header font stacks have drifted between the two surfaces:\n"
        f"  portal/index.html --sans             {spa[0]!r}\n"
        f"  engine/extract/_pages.py header.site {stack!r}")


# --------------------------------------------------------------------------- the identity mark
#
# The header opens with the AuScope mark on EVERY surface, a light and a dark variant of which the
# theme switch shows one, and AusMT's own name and tagline stand beside it. The AusMT product mark is
# the documentation sidebar's and the social card's, not the site header's.
#
# The mark is a fixed 30 x 30 box, which is why it can sit in the zero-basis .hleft zone without
# moving the centre tabs: a flex:1 1 0 side hands its leftover space out evenly whatever it holds, so
# the identity block changes the SIDE's content, never the centre group's x. The pins above hold that
# geometry; these hold the identity itself, on every surface, for the same reason the zone rules are
# held on every surface - an edit to one must not leave another on a different mark.
PRODUCT_MARK = "ausmt-mark.svg"


def test_every_surface_opens_its_header_with_the_auscope_mark_pair():
    """FAILS IF any surface loses either variant, points at a different file, reorders the pair, or
    drifts to a different sizing rule. Same-origin only: an http, https, protocol-relative or data src
    on a mark fails here."""
    surfaces = [(f"portal/{p.name}", header_inner(p.read_text(encoding="utf-8")),
                  p.read_text(encoding="utf-8")) for p in _chrome_pages()]
    surfaces.append(("engine/extract/_pages.py", site_header("navMap"), PAGES_PY.read_text(encoding="utf-8")))
    assert len(surfaces) >= 2, "no chrome page was discovered; the glob or the header marker has moved"
    for where, header, text in surfaces:
        assert header is not None, f"{where}: carries no header"
        left = re.sub(r"<!--.*?-->", "", header, flags=re.S).split('<div class="hzone hleft">', 1)
        assert len(left) == 2, f"{where}: the header has no identity zone"
        assert left[1].lstrip().startswith(MARK_PAIR), (
            f"{where}: the identity zone must open with the AuScope mark pair {MARK_PAIR!r}")
        assert header.count('class="brandmark') == 2, f"{where}: the header carries exactly the two variants"
        assert MARK_RULE in text, f"{where}: the mark must carry the shared sizing rule {MARK_RULE!r}"
        for scheme in ("http://", "https://", '"//', "data:"):
            assert f'class="brandmark theme-light" src="{scheme}' not in header, (
                f"{where}: the identity mark is same-origin only; {scheme!r} is never a mark src")


def test_the_marks_the_headers_name_are_real_committed_vectors():
    """FAILS IF a header's mark points at a file the portal does not ship, or at something that is not
    a vector. Every surface is served from the same origin by the portal image, so one missing file is
    a broken mark on every page of the site at once."""
    for src in (MARK_LIGHT, MARK_DARK):
        asset = ROOT / src.lstrip("/")
        assert asset.is_file(), f"the header names {src}, which the portal does not ship"
        body = asset.read_text(encoding="utf-8")
        assert body.lstrip().startswith("<svg") and "<path" in body, f"{src} must be the vector mark"


# The lock-up pair as the AuScope brand kit published it ("2025 AuScope Logos"): each file's SHA-256
# and byte count, the colour file for the light theme and the white file for the dark.
LOCKUP_FILES = {
    LOCKUP_LIGHT: ("2025 AuScope-NCRIS Logo - Colour.png",
                   "249d99861d37a8796acdd1b2eff73aaa4279436cbca31012d65bad9ce1190ec4", 39960),
    LOCKUP_DARK: ("2025 AuScope-NCRIS Logo - White.png",
                  "595a564ece1151d94347331c1521381df987da437aa3080cff47a5280cf818f6", 35628),
}


def test_the_lockup_the_headers_name_is_the_brand_kits_png_pair():
    """FAILS IF a header's lock-up points at a file the portal does not ship, or at bytes that are not
    the brand kit's file: a resize, a re-encode, a recolour or a metadata strip each change the digest.
    FAILS too if a file stops being an 8-bit RGBA PNG of the 1919 by 325 the markup declares, because
    the width and height attributes reserve the box before the image loads and must be its own
    proportion."""
    assert set(LOCKUP_FILES) == {LOCKUP_LIGHT, LOCKUP_DARK}
    for src, (kit_name, digest, size) in LOCKUP_FILES.items():
        asset = ROOT / src.lstrip("/")
        assert asset.is_file(), f"the header names {src}, which the portal does not ship"
        raw = asset.read_bytes()
        assert raw[:8] == b"\x89PNG\r\n\x1a\n", f"{src} must be a PNG"
        assert len(raw) == size and hashlib.sha256(raw).hexdigest() == digest, (
            f"{src} must be the brand kit's {kit_name!r} byte for byte ({size} B, sha256 {digest})")
        assert struct.unpack(">II", raw[16:24]) == LOCKUP_PIXELS, (
            f"{src} must be {LOCKUP_PIXELS[0]}x{LOCKUP_PIXELS[1]}, got {struct.unpack('>II', raw[16:24])}")
        assert raw[24] == 8 and raw[25] == 6, f"{src} must be 8-bit RGBA (PNG colour type 6)"
        assert (f'src="{src}" alt="AuScope and NCRIS" '
                f'width="{LOCKUP_PIXELS[0]}" height="{LOCKUP_PIXELS[1]}"') in LOCKUP, (
            f"the contract lock-up must declare {src} at its intrinsic size")


def test_the_vendor_inventory_records_the_lockup_pair():
    """portal/vendor/README.md is where an operator answers "where did this file come from and is it
    the one the brand kit published". FAILS IF it stops naming either lock-up file, the kit file it was
    taken from, its digest or its byte count, the facts the pin above holds against the bytes."""
    readme = (ROOT / "vendor" / "README.md").read_text(encoding="utf-8")
    for src, (kit_name, digest, size) in LOCKUP_FILES.items():
        name = src.rsplit("/", 1)[-1]
        row = [line for line in readme.splitlines() if line.startswith(f"| `{name}` |")]
        assert len(row) == 1, f"portal/vendor/README.md must carry one inventory row for {name}"
        for fact in (kit_name, digest, f"{size} B", f"{LOCKUP_PIXELS[0]}x{LOCKUP_PIXELS[1]}"):
            assert fact in row[0], f"the README's row for {name} must record {fact!r}: {row[0]!r}"


# The cuts from the AuScope Style Guide that stood in for the brand kit's files. The guide's page
# carried the mark without Tasmania, so they are gone from the tree and no surface may name them.
RETIRED_CUTS = ("auscope-logo.svg", "auscope-logo-white.svg", "auscope-ncris-lockup.svg",
                "auscope-ncris-lockup-white.svg")


def test_no_surface_names_the_retired_style_guide_cuts():
    """FAILS IF a cut comes back to vendor/auscope/, or if any chrome page, the engine's emitter or the
    drawer's figure names one: a header restored from an earlier revision names two of them at once."""
    for name in RETIRED_CUTS:
        assert not (ROOT / "vendor" / "auscope" / name).exists(), (
            f"vendor/auscope/{name} is retired; the header draws the brand kit's files")
    surfaces = [(f"portal/{p.name}", p.read_text(encoding="utf-8")) for p in _chrome_pages()]
    surfaces += [("engine/extract/_pages.py", PAGES_PY.read_text(encoding="utf-8")),
                 ("portal/src/drawer.js", (ROOT / "src" / "drawer.js").read_text(encoding="utf-8"))]
    for where, text in surfaces:
        for name in RETIRED_CUTS:
            assert name not in text, f"{where}: names the retired cut {name}"


def test_no_header_carries_the_ausmt_product_mark():
    """The rule that moved the identity slot, pinned as one. FAILS IF any header on any surface names
    the AusMT product mark: it is the documentation sidebar's and the social card's mark, and a
    header copied from a page that predates the AuScope identity is exactly how it would come back."""
    for p in _chrome_pages():
        header = header_inner(p.read_text(encoding="utf-8")) or ""
        assert PRODUCT_MARK not in header, f"portal/{p.name}: the header names the AusMT product mark"
    assert PRODUCT_MARK not in site_header("navMap"), (
        "engine/extract/_pages.py: the generated header names the AusMT product mark")


def _chrome_pages():
    """Every portal document that ships the site chrome, by name."""
    return [p for p in sorted(ROOT.glob("*.html")) if "<header>" in p.read_text(encoding="utf-8")]


def _header_markup(text):
    """The <header> element's own markup, or "" for a document that carries none."""
    if "<header" not in text:
        return ""
    return text.split("<header", 1)[1].split("</header>", 1)[0]


def test_every_header_is_the_contract_header_character_for_character():
    """One header on every surface, compared element by element, attribute by attribute and word by
    word with the contract (tests/chrome_contract.py), apart from the differences the contract names:
    the identity is a link with no heading off the homepage, Map is a link off the homepage, the
    current page's control is marked active, and the engine root-anchors About. Comments may differ.

    FAILS IF any surface adds, drops, reorders or rewords anything in its header: a fifth control, a
    count in the right zone, a second mark, the retired Contribute control, a different tagline."""
    expected = {"index.html": ("index", None), "about.html": ("page", "about")}
    pages = _chrome_pages()
    assert {p.name for p in pages} == {"index.html", "about.html", "add-survey.html", "brand.html",
                                       "releases.html"}, [p.name for p in pages]
    for p in pages:
        surface, active = expected.get(p.name, ("page", None))
        got = tokens(header_inner(p.read_text(encoding="utf-8")))
        want = tokens(header_markup(surface, active))
        assert got == want, (
            f"portal/{p.name}: the header differs from the contract at token "
            f"{next(i for i, (a, b) in enumerate(zip(got + [None], want + [None])) if a != b)}:\n"
            f"  got  {got}\n  want {want}")
    for active in ("navMap", "navSurveys", "navCollections"):
        got = tokens(header_inner(site_header(active)))
        want = tokens(header_markup("engine", active))
        assert got == want, (
            f"engine/extract/_pages.py: the header with {active} current differs from the contract:\n"
            f"  got  {got}\n  want {want}")


# THE ONE DECLARED DIFFERENCE between the homepage's identity block and every other surface's. The
# map page is the only document on this site whose body names it in no heading of its own, so its
# wordmark is wrapped in the page's h1 and the page name rides inside it in a clipped span. The
# wrapper takes no type of its own, so its line box is the wordmark's and the block measures as it
# does everywhere else. Declared here rather than left to be invisible, so a header that grows a
# SECOND heading fails a pin instead of passing three.
HOMEPAGE_H1_OPEN = '<h1 class="brandh1"><span class="wordmark">AusMT</span>'
HOMEPAGE_H1_RULE = ".brandh1{flex:none;font-size:inherit}"


def test_only_the_homepage_wraps_its_wordmark_in_a_heading():
    """FAILS IF the homepage loses the wrapper, if the wrapper stops holding the wordmark, if it takes
    a type size of its own (the h1's default 2em would set a taller line box than every other
    surface's), or if any other header grows a heading. Every other document names itself in its own
    main content, and a heading in one of their headers would give that document two top level names."""
    index_text = INDEX.read_text(encoding="utf-8")
    index_header = _header_markup(index_text)
    assert HOMEPAGE_H1_OPEN in index_header, (
        f"the map page's wordmark must be wrapped in the page heading: {HOMEPAGE_H1_OPEN}")
    assert index_header.count("<h1") == 1, (
        f"the map page's header carries exactly one heading, found {index_header.count('<h1')}")
    assert HOMEPAGE_H1_RULE in index_text, f"the heading must take no type of its own: {HOMEPAGE_H1_RULE}"
    for page in _chrome_pages():
        if page.name == "index.html":
            continue
        header = _header_markup(page.read_text(encoding="utf-8"))
        assert "<h1" not in header, (
            f"portal/{page.name}: this document names itself in its own body, so its header must "
            "carry no heading")
        assert PAGE_IDENTITY in header, f"portal/{page.name}: the identity is the link {PAGE_IDENTITY!r}"
    assert "<h1" not in site_header("navMap"), (
        "engine/extract/_pages.py: the generated pages name themselves in their own body, so the "
        "shared header must carry no heading")


# --------------------------------------------------------------- the lock-up and the switch
#
# The right zone carries the AuScope and NCRIS lock-up on every surface and nothing else: the counts
# left it for the footer. Two variants ship for the two grounds, the white one sits only on the dark
# ground, and the switch below shows exactly one of them.
def _surfaces_text():
    """Every chrome surface's text, the engine's sheet last so each portal page is checked first."""
    out = [(f"portal/{p.name}", p.read_text(encoding="utf-8")) for p in _chrome_pages()]
    out.append(("engine/extract/_pages.py", PAGES_PY.read_text(encoding="utf-8")))
    return out


def test_the_right_zone_is_the_lockup_alone_on_every_surface():
    """FAILS IF a surface's right zone carries anything but the lock-up, including the counts that
    moved to the footer, or if a variant's file, size or alt text drifts."""
    headers = [(f"portal/{p.name}", header_inner(p.read_text(encoding="utf-8"))) for p in _chrome_pages()]
    headers.append(("engine/extract/_pages.py", header_inner(site_header("navMap"))))
    for where, header in headers:
        right = flat(header).split('<div class="hzone hright">', 1)
        assert len(right) == 2, f"{where}: the header has no right zone"
        assert right[1].strip() == LOCKUP + "</div>", (
            f"{where}: the right zone is the lock-up and nothing else: {right[1]!r}")
        for gone in ("counts", "countSlot", "corpusCounts"):
            assert gone not in header, f"{where}: {gone!r} left the header for the footer"


def test_every_surface_declares_the_lockup_rules_and_the_theme_switch_verbatim():
    """FAILS IF a surface's lock-up rules or switch rules drift by a character, or if the switch's
    first rule comes before a one-class rule that also sets display on a variant (.brandmark): the
    two tie on specificity, and source order alone decides which wins."""
    for where, text in _surfaces_text():
        for rule in LOCKUP_RULES + THEME_RULES:
            assert text.count(rule) == 1, f"{where}: expected exactly one {rule!r}, found {text.count(rule)}"
        assert text.index(MARK_RULE) < text.index(THEME_RULES[0]), (
            f"{where}: the theme switch must follow {MARK_RULE!r}, which it ties on specificity")


def test_no_rule_that_selects_a_variant_outranks_the_switch():
    """The light theme shows exactly one of each pair. .theme-dark{display:none} is one class, so any
    rule of higher specificity that sets display on a variant shows the dark lock-up in the light
    theme as well. FAILS IF a lock-up or watermark rule that selects the images declares display."""
    for where, text in _surfaces_text():
        for sel in (r"\.orglockup img", r"\.collmark", r"#map \.mapmark"):
            for body in re.findall(r"(?m)(?:^|\})\s*" + sel + r"\{([^}]*)\}", _outside_media(text)):
                assert "display" not in body, (
                    f"{where}: {sel.replace(chr(92), '')} sets display at a specificity the switch "
                    f"cannot override: {body!r}")


def _outside_media(text):
    return re.sub(r"@media[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", text)


def test_the_contribute_control_has_left_every_header():
    """FAILS IF the Contribute control or its rule comes back to any surface's header. add-survey.html
    stays served and About links it from its own body."""
    for where, text in _surfaces_text():
        assert ".contribute" not in text, f"{where}: the .contribute rule is retired"
        header = flat(_header_markup(text) if where.startswith("portal/") else site_header("navMap"))
        assert "add-survey.html" not in header and "Contribute" not in header, (
            f"{where}: the header no longer carries the Contribute control")
    about = (ROOT / "about.html").read_text(encoding="utf-8").split("<main>", 1)[1]
    assert 'href="add-survey.html"' in about, "About must keep its in-body route to add-survey.html"


# ------------------------------------------------------- the parent-organisation icon, WITHDRAWN
#
# The AuScope icon PNG that once closed every header from the right zone stays withdrawn. The
# relationship is carried by the lock-up in the right zone and stated in words in the footer and in
# About's "Who enables AusMT" section.
#
# THE PINS BELOW ARE THE OLD ONES INVERTED, NOT DROPPED. What was held before was presence,
# position, count and sizing on every surface; what is held now is ABSENCE on every surface, by the
# anchor literal, by the class, by both CSS rules and by the image's filename.
ORG_SRC = "/vendor/auscope-icon-white.png"
ORG_IMG = (f'<a class="orgmark" href="https://www.auscope.org.au" target="_blank" '
           f'rel="noopener noreferrer" title="AuScope">'
           f'<img src="{ORG_SRC}" alt="AuScope" width="29" height="30"></a>')
ORG_CLASS = 'class="orgmark"'
ORG_RULE = ".orgmark{display:flex;align-items:center;flex:none;margin-left:16px}"
ORG_IMG_RULE = ".orgmark img{height:30px;width:auto;display:block}"


def test_no_chrome_page_is_exempt_from_the_identity_mark():
    """The guard over the per-surface identity pin above: it may not be hollowed out by skipping a
    page. FAILS IF any discovered chrome page is missing the AuScope mark pair that opens its header."""
    pages = _chrome_pages()
    assert pages, "no chrome page was discovered; the glob or the header marker has moved"
    for page in pages:
        assert MARK_PAIR in page.read_text(encoding="utf-8"), (
            f"portal/{page.name}: the AuScope mark must open this header; no page is exempt")


def test_no_chrome_surface_carries_the_org_mark_in_its_header():
    """FAILS IF the anchor literal, the .orgmark class or either of its two CSS rules comes back to
    the SPA, to any static chrome page or to the engine's pages sheet."""
    surfaces = [("engine/extract/_pages.py", PAGES_PY.read_text(encoding="utf-8"))]
    surfaces += [(f"portal/{p.name}", p.read_text(encoding="utf-8")) for p in _chrome_pages()]
    assert len(surfaces) >= 2, "no chrome surface was discovered; the glob or the marker has moved"
    for where, text in surfaces:
        for label, needle in (("the anchor", ORG_IMG), ("the class", ORG_CLASS),
                              ("the zone rule", ORG_RULE), ("the sizing rule", ORG_IMG_RULE)):
            assert needle not in text, (
                f"{where}: the header's AuScope org-mark is withdrawn from every surface; "
                f"{label} is back as {needle!r}")


ORG_ASSET = ORG_SRC.rsplit("/", 1)[-1]
ORG_ASSET_PER_PAGE = 0


def test_no_chrome_page_names_the_auscope_image_at_all():
    """FAILS IF a chrome page carries the AuScope icon PNG in any slot. The site chrome draws the
    vector mark pair and the lock-up PNGs; the icon PNG is a committed file that no page names."""
    pages = _chrome_pages()
    assert pages, "no chrome page was discovered; the glob or the header marker has moved"
    for page in pages:
        count = page.read_text(encoding="utf-8").count(ORG_ASSET)
        assert count == ORG_ASSET_PER_PAGE, (
            f"portal/{page.name}: no chrome page may name the AuScope icon PNG, found {count}")


def test_the_withdrawn_asset_is_still_the_real_committed_file_its_other_consumers_need():
    """The file STAYS committed, and this holds it to being the artefact it was. FAILS IF it is
    deleted, replaced by a placeholder or re-encoded without its alpha channel. The documentation
    site's sidebar copy is made from these bytes (tests/test_docs_branding.py) and
    tools/gen_social_card.py composites it into the social card."""
    asset = ROOT / ORG_SRC.lstrip("/")
    assert asset.is_file(), f"{ORG_SRC} still has consumers outside the site chrome and must ship"
    data = asset.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{ORG_SRC} must be a PNG"
    # Colour type 6 is RGBA: the mark is white, so it reads on a dark ground only because it carries
    # its own transparency rather than a background it would paint over.
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
    different header on different pages, and the standing rule is one header on every surface."""
    surfaces = _chrome_surfaces()
    assert len(surfaces) >= 2, "no chrome surfaces were discovered; the glob or the zone marker moved"
    for where, text in surfaces:
        body = _header_rule(text, where)
        assert HEADER_LINE_HEIGHT in body, (
            f"{where}: the header rule must declare {HEADER_LINE_HEIGHT!r}, so that the host "
            f"document's body prose line-height cannot change the header's height; got {body!r}")


def test_every_chrome_surface_carries_the_same_zone_geometry():
    """The zone rules, character-identical on EVERY surface wearing the chrome, not just across the
    pair above. The pair covers the SPA and the generated pages, which is where the geometry is
    specified; releases.html and about.html each carry their OWN copy of the chrome, and both kept
    the auto-basis sides the zone rule replaced. An auto basis sizes each side zone from its own content,
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
                f".{zone} has drifted from the declared zone geometry:\n"
                f"  portal/index.html            {reference[zone]!r}\n"
                f"  {where:<28} {rules[zone]!r}")
