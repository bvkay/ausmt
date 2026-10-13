"""Fixed nav geometry: the header's tab group sits at ONE x position on every page and view.

Both headers - the SPA's (portal/index.html) and the static pages' (engine/extract/_pages.py,
_CSS) - divide into three zones: .hleft (the AuScope mark and AusMT's name), .hcenter (the tab
group and the About control), .hright (the tagline). With auto-basis sides (flex:1 1
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

from chrome_contract import (BRANDH1_RULE, BRANDMARK_RULE, INDEX_IDENTITY, LIGHT, LOCKUP, LOCKUP_DARK,
                             LOCKUP_LIGHT, LOCKUP_PIXELS, MAP_LOCKUP, MARK_DARK, MARK_LIGHT, MARK_PAIR,
                             NAME, PAGE_IDENTITY, RIGHT_ZONE, TAGLINE_RULE, THEME_RULES,
                             WORDMARK_RULES, flat, header_inner, header_markup, token_blocks, tokens)
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


# --------------------------------------------------------------------------- the identity zone
#
# The identity zone is the AuScope mark pair and AusMT's name, and nothing else, on EVERY surface: the
# mark 36px square, then the name set at the AuScope logo's own proportions scaled to it. The tagline
# is the right zone's, and the AusMT product mark is the documentation sidebar's and the social card's,
# not the site header's.
#
# The identity block sits in the zero-basis .hleft zone, so it cannot move the centre tabs: a
# flex:1 1 0 side hands its leftover space out evenly whatever it holds, so the identity block changes
# the SIDE's content, never the centre group's x. The pins above hold that geometry; these hold the
# identity itself, on every surface, for the same reason the zone rules are held on every surface: an
# edit to one must not leave another carrying a mark or a name the rest have changed.
PRODUCT_MARK = "ausmt-mark.svg"

# Every way an image can be drawn into a zone besides the mark pair's two img elements: an element
# that fetches or paints one, or a rule that paints one behind the text.
IMAGE_TAGS = ("<svg", "<picture", "<object", "<embed", "<canvas", "<image")
IMAGE_CSS = ("background-image", "background:url", "url(", "content:url")


def _identity_zones():
    """(where, the identity zone's inner markup, the surface's full text) for every chrome page and for
    the engine's header with each tab current, comments stripped so prose cannot satisfy a pin."""
    out = [(f"portal/{p.name}", header_inner(p.read_text(encoding="utf-8")), p.read_text(encoding="utf-8"))
           for p in _chrome_pages()]
    out += [(f"engine/extract/_pages.py ({active})", header_inner(site_header(active)),
             PAGES_PY.read_text(encoding="utf-8"))
            for active in ("navMap", "navSurveys", "navCollections")]
    zones = []
    for where, header, text in out:
        assert header is not None, f"{where}: carries no header"
        bare = re.sub(r"<!--.*?-->", "", header, flags=re.S)
        left = bare.split('<div class="hzone hleft">', 1)
        assert len(left) == 2, f"{where}: the header has no identity zone"
        zone = left[1].split('<div class="hzone hcenter">', 1)[0]
        zones.append((where, zone, text))
    return zones


def test_every_identity_zone_is_the_mark_pair_and_the_name():
    """FAILS IF any surface's identity zone holds anything but the AuScope mark pair followed by AusMT's
    name: the homepage's heading-wrapped name, or the root link elsewhere, as the contract states them.
    A third image, an inline svg, a picture, an object, an embed or a canvas fails, and so does an
    inline style, which would outrank the rules below; the tagline coming back fails too, because it is
    the right zone's."""
    zones = _identity_zones()
    assert len(zones) >= 4, "fewer chrome surfaces were discovered than ship; the glob or the marker moved"
    for where, zone, _text in zones:
        lowered = zone.lower()
        for tag in IMAGE_TAGS:
            assert tag not in lowered, f"{where}: the identity zone draws no other image; found {tag!r}"
        assert lowered.count("<img") == 2, f"{where}: the identity zone draws the mark pair, two images"
        assert "style=" not in lowered, f"{where}: the identity zone takes no inline style: {zone!r}"
        identity = INDEX_IDENTITY if where == "portal/index.html" else PAGE_IDENTITY
        want = tokens(f"{MARK_PAIR}{identity}</div>")
        assert tokens(zone) == want, (
            f"{where}: the identity zone is the mark pair and the name and nothing else:\n"
            f"  got  {tokens(zone)}\n  want {want}")


def test_every_surface_declares_the_identity_rules_verbatim_before_the_switch():
    """The identity zone's rules, character for character on every surface, and in an order the switch
    can win. FAILS IF a surface drops or edits the mark's 36px box, the name's size, weight, tracking,
    line height or family stack, or the heavy "Aus"; if the homepage's heading rule goes or another
    surface grows one; or if the mark's rule follows the switch: .brandmark sets display:block and ties
    with .theme-dark on specificity, so placed after the switch it would show the white mark on the
    light ground. FAILS too if a rule for the identity zone or its items paints a background image,
    which would draw a second mark without a single img."""
    for where, text in _surfaces_text():
        for rule in (BRANDMARK_RULE, *WORDMARK_RULES):
            assert text.count(rule) == 1, f"{where}: expected exactly one {rule!r}, found {text.count(rule)}"
        assert text.index(BRANDMARK_RULE) < text.index(THEME_RULES[0]), (
            f"{where}: the mark's rule must come before the theme switch it ties with")
        if where == "portal/index.html":
            assert text.count(BRANDH1_RULE) == 1, f"{where}: the heading must take no type of its own"
        else:
            assert ".brandh1{" not in text, f"{where}: only the homepage wraps its name in a heading"
        for sel in (r"\.hleft", r"\.brandmark", r"\.wordmark", r"\.wordmark b", r"\.brandh1"):
            for body in re.findall(r"(?m)(?:^|\})\s*" + sel + r"\{([^}]*)\}", text):
                for paint in IMAGE_CSS:
                    assert paint not in body.replace(" ", ""), (
                        f"{where}: {sel.replace(chr(92), '')} paints an image: {body!r}")


def test_every_header_names_the_mark_pair_once_and_no_lockup_file():
    """FAILS IF a header names either mark file other than once, as its own variant, or names either
    lock-up file in any slot: the lock-up closes the footers and takes the map's corner, and a header
    that carried it again would put two AuScope images in one band."""
    headers = [(f"portal/{p.name}", header_inner(p.read_text(encoding="utf-8"))) for p in _chrome_pages()]
    headers += [(f"engine/extract/_pages.py ({a})", header_inner(site_header(a)))
                for a in ("navMap", "navSurveys", "navCollections")]
    for where, header in headers:
        bare = re.sub(r"<!--.*?-->", "", header, flags=re.S)
        for src, variant in ((MARK_LIGHT, "theme-light"), (MARK_DARK, "theme-dark")):
            tags = [tag for tag in re.findall(r"<img\b[^>]*>", bare) if f'src="{src}"' in tag]
            assert len(tags) == 1 and f'class="brandmark {variant}"' in tags[0], (
                f"{where}: the header names {src} once, as the {variant} mark: {tags!r}")
        for src in (LOCKUP_LIGHT, LOCKUP_DARK):
            assert src not in bare, f"{where}: no header names the lock-up {src}"
        assert "orglockup" not in bare, f"{where}: the lock-up anchor left every header"


def test_the_mark_pair_ships_for_every_header_the_figures_and_the_icons():
    """The two mark files are drawn by every header, by the collection figure on both surfaces
    (portal/src/drawer.js and the engine's collection page) and by the icons
    tools/gen_auscope_icons.py renders. The map's corner draws the lock-up instead. FAILS IF either
    file goes, stops being the vector mark, if a consumer stops naming it, or if the map's container
    names it again."""
    for src in (MARK_LIGHT, MARK_DARK):
        asset = ROOT / src.lstrip("/")
        assert asset.is_file(), f"{src} is drawn by every header and the collection figures and must ship"
        body = asset.read_text(encoding="utf-8")
        assert body.lstrip().startswith("<svg") and "<path" in body, f"{src} must be the vector mark"
        consumers = (("portal/index.html (the header)", header_inner(INDEX.read_text(encoding="utf-8"))),
                     ("portal/src/drawer.js (the collection figure)",
                      (ROOT / "src" / "drawer.js").read_text(encoding="utf-8")),
                     ("engine/extract/_pages.py (the header)", site_header("navMap")),
                     ("engine/extract/_pages.py (the collection figure)",
                      "".join(re.findall(r'<img class="collmark [^>]*>',
                                         PAGES_PY.read_text(encoding="utf-8")))))
        for label, text in consumers:
            assert text.count(src) >= 1, f"{label} must still draw {src}"
    corner = re.search(r'<div id="map">(.*?)</div>', INDEX.read_text(encoding="utf-8"), re.S)
    assert corner and corner.group(1) == MAP_LOCKUP, "the map's corner draws the lock-up pair alone"
    icons = (ROOT / "tools" / "gen_auscope_icons.py").read_text(encoding="utf-8")
    assert MARK_LIGHT.rsplit("/", 1)[-1] in icons, (
        "tools/gen_auscope_icons.py renders the icons from the mark and must still read it")


# The lock-up pair as the AuScope brand kit published it ("2025 AuScope Logos"): each file's SHA-256
# and byte count, the colour file for the light theme and the white file for the dark.
LOCKUP_FILES = {
    LOCKUP_LIGHT: ("2025 AuScope-NCRIS Logo - Colour.png",
                   "249d99861d37a8796acdd1b2eff73aaa4279436cbca31012d65bad9ce1190ec4", 39960),
    LOCKUP_DARK: ("2025 AuScope-NCRIS Logo - White.png",
                  "595a564ece1151d94347331c1521381df987da437aa3080cff47a5280cf818f6", 35628),
}


def test_the_lockup_the_footers_and_the_map_name_is_the_brand_kits_png_pair():
    """FAILS IF the lock-up points at a file the portal does not ship, or at bytes that are not the
    brand kit's file: a resize, a re-encode, a recolour or a metadata strip each change the digest.
    FAILS too if a file stops being an 8-bit RGBA PNG of the 1919 by 325 the markup declares, because
    the width and height attributes reserve the box before the image loads and must be its own
    proportion."""
    assert set(LOCKUP_FILES) == {LOCKUP_LIGHT, LOCKUP_DARK}
    for src, (kit_name, digest, size) in LOCKUP_FILES.items():
        asset = ROOT / src.lstrip("/")
        assert asset.is_file(), f"the lock-up names {src}, which the portal does not ship"
        raw = asset.read_bytes()
        assert raw[:8] == b"\x89PNG\r\n\x1a\n", f"{src} must be a PNG"
        assert len(raw) == size and hashlib.sha256(raw).hexdigest() == digest, (
            f"{src} must be the brand kit's {kit_name!r} byte for byte ({size} B, sha256 {digest})")
        assert struct.unpack(">II", raw[16:24]) == LOCKUP_PIXELS, (
            f"{src} must be {LOCKUP_PIXELS[0]}x{LOCKUP_PIXELS[1]}, got {struct.unpack('>II', raw[16:24])}")
        assert raw[24] == 8 and raw[25] == 6, f"{src} must be 8-bit RGBA (PNG colour type 6)"
        for label, pair in (("footer", LOCKUP), ("map corner", MAP_LOCKUP)):
            assert (f'src="{src}" alt="AuScope and NCRIS" '
                    f'width="{LOCKUP_PIXELS[0]}" height="{LOCKUP_PIXELS[1]}"') in pair, (
                f"the contract's {label} lock-up must declare {src} at its intrinsic size")


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
    count or the lock-up in the right zone, a third image, the retired Contribute control, a different
    tagline."""
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
# wrapper takes no type of its own, and the 36px mark beside it sets the block's height, so the block
# measures as it does everywhere else. Declared here rather than left to be invisible, so a header
# that grows a SECOND heading fails a pin instead of passing three.
HOMEPAGE_H1_OPEN = f'<h1 class="brandh1"><span class="wordmark">{NAME}</span>'
HOMEPAGE_H1_RULE = BRANDH1_RULE


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


# ------------------------------------------------------------- the right zone and the switch
#
# The right zone carries the tagline on every surface and nothing else: the counts left it for the
# footer and the lock-up for the footers and the map's corner. The mark pair and the lock-up pair each
# ship a variant per ground, the white one sits only on the dark ground, and the switch below shows
# exactly one of each.
def _surfaces_text():
    """Every chrome surface's text, the engine's sheet last so each portal page is checked first."""
    out = [(f"portal/{p.name}", p.read_text(encoding="utf-8")) for p in _chrome_pages()]
    out.append(("engine/extract/_pages.py", PAGES_PY.read_text(encoding="utf-8")))
    return out


def _switch_surfaces_text():
    """Every surface that draws a light and a dark variant: the chrome pages, the engine's sheet and
    404.html, whose footer lock-up is its one pair."""
    out = _surfaces_text()
    out.insert(0, ("portal/404.html", (ROOT / "404.html").read_text(encoding="utf-8")))
    return out


def test_the_right_zone_is_the_tagline_alone_on_every_surface():
    """FAILS IF a surface's right zone carries anything but the tagline, including the counts that moved
    to the footer and the lock-up that moved to the footers and the map, or if its wording drifts."""
    headers = [(f"portal/{p.name}", header_inner(p.read_text(encoding="utf-8"))) for p in _chrome_pages()]
    headers.append(("engine/extract/_pages.py", header_inner(site_header("navMap"))))
    for where, header in headers:
        right = flat(header).split('<div class="hzone hright">', 1)
        assert len(right) == 2, f"{where}: the header has no right zone"
        assert '<div class="hzone hright">' + right[1].strip() == RIGHT_ZONE, (
            f"{where}: the right zone is the tagline and nothing else: {right[1]!r}")
        for gone in ("counts", "countSlot", "corpusCounts", "orglockup"):
            assert gone not in header, f"{where}: {gone!r} left the header"


def test_every_surface_declares_the_tagline_rule_verbatim():
    """The tagline sits on one line in a zero-basis zone, so where the zone is narrower than the line it
    must end in an ellipsis inside the zone: without min-width:0, overflow:hidden and
    text-overflow:ellipsis the line spills out of the zone's left edge and paints over the About
    control, 92px of it at 761px of viewport. FAILS IF any surface's rule drifts by a character."""
    for where, text in _surfaces_text():
        assert text.count(TAGLINE_RULE) == 1, (
            f"{where}: expected exactly one {TAGLINE_RULE!r}, found {text.count(TAGLINE_RULE)}")
        assert len(re.findall(r"(?m)^\s*\.tagline\{", text)) == 1, f"{where}: one .tagline rule"


def test_every_surface_declares_the_theme_switch_verbatim_and_in_order():
    """FAILS IF a switch rule drifts by a character, goes missing or is declared twice, or if the three
    leave their order: the default hide, then the light variant hidden and the dark one shown under
    <html data-theme="dark">."""
    for where, text in _switch_surfaces_text():
        for rule in THEME_RULES:
            assert text.count(rule) == 1, f"{where}: expected exactly one {rule!r}, found {text.count(rule)}"
        at = [text.index(rule) for rule in THEME_RULES]
        assert at == sorted(at), f"{where}: the three theme rules must keep their order: {at}"


def test_no_rule_that_selects_a_variant_outranks_the_switch():
    """The light theme shows exactly one of each pair. .theme-dark{display:none} is one class, so a rule
    of higher specificity that sets display on a variant shows the white file in the light theme as
    well, and a one-class rule that sets display ties with it and loses only by coming first. FAILS IF
    a lock-up, map-corner or figure rule that selects the images declares display at all; the mark's
    own .brandmark rule, which must set display:block, is held to coming before the switch above."""
    for where, text in _switch_surfaces_text():
        for sel in (r"\.orglockup img", r"\.collmark", r"\.maplock", r"#map \.maplock"):
            for body in re.findall(r"(?m)(?:^|\})\s*" + sel + r"\{([^}]*)\}", _outside_media(text)):
                assert "display" not in body, (
                    f"{where}: {sel.replace(chr(92), '')} sets display, which the switch cannot "
                    f"override: {body!r}")


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
# relationship is carried by the mark pair that opens every header and the lock-up that closes the
# footers, and stated in words in the footer and in About's "Who enables AusMT" section.
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


def test_no_chrome_page_is_exempt_from_the_identity_zone_pins():
    """The guard over the per-surface identity pins above: they may not be hollowed out by skipping a
    page. FAILS IF the discovered chrome pages stop being the five that ship a header, or if any of
    them carries anything but the mark pair's two images in its header's identity zone."""
    pages = _chrome_pages()
    assert {p.name for p in pages} == {"index.html", "about.html", "add-survey.html", "brand.html",
                                       "releases.html"}, [p.name for p in pages]
    covered = {where for where, _zone, _text in _identity_zones()}
    for page in pages:
        assert f"portal/{page.name}" in covered, f"portal/{page.name}: no page is exempt"
        header = re.sub(r"<!--.*?-->", "", header_inner(page.read_text(encoding="utf-8")), flags=re.S)
        zone = header.split('<div class="hzone hleft">', 1)[1].split('<div class="hzone hcenter">', 1)[0]
        assert re.findall(r"<img\b[^>]*>", zone) == re.findall(r"<img\b[^>]*>", MARK_PAIR), (
            f"portal/{page.name}: the identity zone's images are the mark pair; no page is exempt")


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
    """FAILS IF a chrome page carries the AuScope icon PNG in any slot. The header draws the vector
    mark pair, and the footers and the map's corner the lock-up PNGs; the icon PNG is a committed file
    that no page names."""
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
