"""One footer, three regions, the same on the SPA, on the five static pages and on the pages the engine
emits.

The rule is one footer: LEFT the machine-readable catalogue, CENTRE the AuScope acknowledgement with
the licence note, RIGHT the page's status and, on every page without the big map, the AuScope and
NCRIS lock-up after it, so the lock-up sits at the bottom right of every such page. The SPA's status
is its live station counts and its right zone holds nothing else, because its map's corner carries
the lock-up; a generated page's right zone is its contextual status markup, then the lock-up; the
other five static pages have no status, so theirs is the lock-up alone. On those six surfaces the
footer fetches the lock-up and nothing else and carries two anchors to AuScope, the centre's name
and the lock-up; the SPA's fetches nothing and carries one. The copyright clause left the
acknowledgement. The footer holds no control.

WHY THE ENGINE HALF LIVES HERE rather than in engine/tests: portal-ci runs on portal/** AND on
engine/extract/_pages.py, so an edit to either surface fires this module, where the engine workflow
triggers on engine/** alone and cannot see an index.html edit. The engine's footer is produced by
running its own _site_footer from source (tests/engine_chrome.py); the engine workflow holds its own
half of this in engine/tests/test_index_pages.py, asserted against real rendered pages.

THE SEPARATOR IS U+00B7 on every surface, spelt here as an escape so a mis-decoded read of this file
cannot let a hyphen or a dash through the pin; a page may write it literally or as a character
reference, and every spelling is resolved before comparison.

Each assertion states its failure criterion:

  * REGIONS - FAILS if a surface does not carry exactly three footer regions, or if a region holds
    something belonging to another.
  * STRINGS - FAILS if a surface's centre line drifts from the wording or from its markup (the
    organisation's name is the line's one link, and the address never appears as text), if the
    copyright clause comes back, if the left link's label stops being "MTCAT JSON" with the
    leaves-the-site arrow, or if a portal page's left link loses class="apilink" or its title.
  * TARGETS - FAILS if the surfaces stop agreeing on where the MTCAT link points. The SPA is served
    from the portal root and writes it relative, the generated pages cannot, so the pin holds the
    ROOT-RELATIVE form of both against each other.
  * THE ONE EXTERNAL TARGET - FAILS if a footer reaches any external host other than the single
    allow-listed AuScope navigation address, and FAILS if a footer FETCHES anything but the lock-up
    pair, same-origin, on the six surfaces that draw it: no other image, no stylesheet, no script
    and no url(), and nothing at all on index.html.
  * THE RIGHT ZONE - FAILS if a surface's right zone is anything but its contents: exactly the live
    counts on index.html, exactly the status then the lock-up on the engine's pages, exactly the
    lock-up on the other five.
  * THE LOCK-UP KEEPS THE FOOTER'S HEIGHT - FAILS if the lock-up's rules drift, leave a surface that
    draws it or come to one that does not, or if its margin box stops being one footer text line.
  * NO CONTROL - FAILS if any footer carries a button, an input or any other control, a control
    group, a pressed state or an inline handler the CSP would block.
  * GEOMETRY - FAILS if any surface stops being a wrapping flex row or a query container, if a side
    zone stops taking the equal zero basis, if the centre stops being content-sized or centred, if
    either state below one row goes, or if a 375px viewport collides instead of stacking.
  * ONE FOOTER RULE SET, ON ALL SEVEN SURFACES - FAILS if any surface's footer rule set drifts from
    portal/index.html's by a character, or reaches for a literal colour instead of a token.
  * THE RETIRED CONTENT STAYS RETIRED - FAILS if Releases, About this build, the disclosure popover,
    the copyright clause, the retired footer logo or the retired appearance control comes back to
    any footer.
  * THE EXTERNAL ANCHORS OPEN IN A NEW TAB - FAILS if an AuScope anchor on any surface loses
    target="_blank" or rel="noopener noreferrer", if a surface carries more or fewer of them than
    its contents call for, or if an in-site footer link takes a target.

BOTH QUERIES ASK THE FOOTER'S OWN WIDTH, not the viewport's: the sibling pages set their content in
reading columns of different widths, so no single viewport number describes "the three regions do
not fit" on more than one page kind at a time.

THE OWN-ROW BREAKPOINT IS A MEASUREMENT OF THE CONTENT, not a design constant. It was measured with a
longer acknowledgement than the line carries now, so the 1421px query fires earlier than the content
strictly needs, which only ever puts the centre on its own row a little sooner: at 1422px of footer
content the three regions share one row with the lock-up on the right, measured in Chrome. Anything
that lengthens a region again moves this number and it has to be re-measured.
"""
import hashlib
import re
import struct
from html.parser import HTMLParser
from pathlib import Path

import pytest

from chrome_contract import (FOOTER_CENTRE, FOOTER_CENTRE_MARKUP, FOOTER_LINE, LOCKUP, LOCKUP_FOOTERS,
                             LOCKUP_HEIGHT, LOCKUP_LIGHT, LOCKUP_RULES, entities, flat)
from engine_chrome import function_source, site_footer

ROOT = Path(__file__).resolve().parent.parent          # portal/
INDEX = ROOT / "index.html"
PAGES_PY = ROOT.parent / "engine" / "extract" / "_pages.py"

DOT = "·"

# The three regions, as the strings a reader sees.
CENTRE = FOOTER_CENTRE
# The centre's one link reads as the organisation's name; the address it opens is never printed.
CENTRE_LINK_TEXT = "AuScope"
ADDRESS_TEXT = "www.auscope.org.au"
LEFT_LABEL = "MTCAT JSON"
ARROW = "↗"
MTCAT = "/data/mtcat.json"

# THE ONE EXTERNAL TARGET. The organisation's name in the centre line navigates here, and it is the
# footer's only link off the site. It governs NAVIGATION ONLY: _no_external_fetch below holds the
# other half, that no footer on any surface FETCHES anything, from any host.
_EXTERNAL_NAV = ("https://www.auscope.org.au",)

# NO FOOTER CARRIES A MAP CREDIT, on any surface. The basemap's attribution is a licence obligation
# met where the map is, in the map's own attribution control: the footer is the same box on seven
# surfaces, and a fixed line of prose cannot follow the tile source when map.js falls back to CARTO.
# Held as a negative by the class AND by the two hrefs: a page could drop the class and still be
# making the claim.
_NO_CREDIT_MARKS = ("mapcredit", "https://www.openstreetmap.org/copyright", "https://protomaps.com")

# HOW THE EXTERNAL ANCHOR OPENS. It leaves the site, so it opens in a new tab and hands the opened
# page no handle on this one: target="_blank" alone gives the opened document window.opener, and the
# referrer would leak the reader's path through the catalogue to a third party. Asserted as ONE
# literal string in ONE order so seven surfaces cannot each spell it differently.
_NEW_TAB = 'target="_blank" rel="noopener noreferrer"'

# The SPA's status: the live station counts, painted by src/filters.js into #countSlot, then the short
# data build id main.js renderBuildId writes into #buildId. The wrapper carries the counts' own styling;
# the slot's content changes with the view.
INDEX_STATUS = ('<div class="counts" id="footerCounts"><span id="countSlot" title="stations passing the '
                'current filters · stations selected · total stations in the catalogue">'
                '<b id="nVis">0</b> shown · <b id="nSel">0</b> selected · <span id="nTot">0</span> '
                'total</span><span id="buildId"></span></div>')
# A generated page's status, as a probe the engine's footer must carry verbatim at the head of its
# right zone, before the lock-up.
ENGINE_STATUS = '<span class="counts">probe status</span>'

# The white lock-up, committed as its rights holder published it because the raster cards draw a crop
# of it (engine/tests/test_og_cards.py); portal/vendor/README.md records the same facts. No footer
# names it: it was drawn only on a dark ground.
LOGO_SRC = "/vendor/auscope-ncris-white.png"
LOGO_SHA256 = "595a564ece1151d94347331c1521381df987da437aa3080cff47a5280cf818f6"
LOGO_BYTES = 35628
LOGO_PIXELS = (1919, 325)

# What the rules took OUT of every footer. Held as a negative so nothing drifts back in one page at a
# time: the popover's CSS is swept as well as its markup, because a rule left behind is an invitation
# to re-add the element it styles. The lock-up's own class is orglockup; orglogo is the retired logo.
RETIRED = ("aboutbuild", "About this build", ">Releases<", "releases.html", "orglogo",
           "©", "AusMT contributors", "Machine-readable record", "Light", "Dark")
# The classes and the hook of the retired footer control, swept from the whole document or the
# engine's source with the popover's and the retired footer logo's: a rule or an attribute left behind
# is an invitation to re-add the element it served.
RETIRED_CLASSES = ("aboutbuild", "orglogo", "themectl", "themesep", "data-theme-choice")

_ZONE_CLASSES = {"left": "fzone fleft", "centre": "fzone fcenter", "right": "fzone fright"}

_PORTAL_PAGES = ("404.html", "about.html", "add-survey.html", "brand.html", "index.html",
                 "releases.html")


def _index_text():
    return INDEX.read_text(encoding="utf-8")


def _pages_text():
    return PAGES_PY.read_text(encoding="utf-8")


def _portal_pages():
    return sorted(p.name for p in ROOT.glob("*.html"))


def _engine_footer(status=ENGINE_STATUS):
    """The footer the engine's own _site_footer writes around `status`."""
    out = site_footer(status)
    assert out.count("<footer") == 1, "engine/extract/_pages.py: _site_footer must write one footer"
    inner = out.split("<footer", 1)[1].split(">", 1)[1].split("</footer>", 1)[0]
    return re.sub(r"<!--.*?-->", "", "<footer>" + inner + "</footer>", flags=re.S)


def _outside_queries(text):
    """`text` with every @media and @container block removed, brace-matched rather than
    regex-bounded. The base rules and their narrower-width overrides use the SAME selectors, so an
    "exactly one" pin must exclude the query blocks, and excluding them is also what makes that pin
    mean what it says: a SECOND unconditional declaration would override the pinned rule."""
    out, i = [], 0
    while True:
        hits = [at for at in (text.find("@media", i), text.find("@container", i)) if at >= 0]
        if not hits:
            out.append(text[i:])
            return "".join(out)
        at = min(hits)
        out.append(text[i:at])
        depth, j = 0, text.index("{", at)
        while True:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        i = j + 1


class _FooterRegions(HTMLParser):
    """The footer's TOP-LEVEL children, each with the html it encloses.

    Depth-tracked rather than regex-split because the right region nests markup of its own, whose
    first close tag ends a class-scoped pattern early and would let a missing region pass as present."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.children = []          # (tag, attrs-dict, inner html)
        self._depth = 0             # nesting depth inside <footer>
        self._open = None           # (tag, attrs, start offset) of the child being collected
        self.raw = ""

    def handle_starttag(self, tag, attrs):
        if self._depth == 0:
            if tag == "footer":
                self._depth = 1
            return
        if self._depth == 1 and self._open is None:
            self._open = (tag, {k: (v or "") for k, v in attrs}, self.getpos())
        if tag not in _VOID:
            self._depth += 1

    def handle_startendtag(self, tag, attrs):
        return

    def handle_endtag(self, tag):
        if self._depth == 0:
            return
        self._depth -= 1
        if self._depth == 1 and self._open is not None:
            tag_, attrs, start = self._open
            self.children.append((tag_, attrs, _slice(self.raw, start, self.getpos())))
            self._open = None


_VOID = {"img", "br", "hr", "input", "meta", "link", "source", "area", "base", "col", "embed",
         "param", "track", "wbr"}


def _offset(text, pos):
    """A parser (line, col) position as an index into `text`."""
    line, col = pos
    return sum(len(row) + 1 for row in text.split("\n")[:line - 1]) + col


def _slice(text, start, end):
    """The html between a child's own tags, from the parser's (line, col) positions."""
    return text[text.index(">", _offset(text, start)) + 1:_offset(text, end)]


def _footer_html(name):
    """A portal page's one footer, comments stripped so prose inside it cannot satisfy a pin."""
    text = (ROOT / name).read_text(encoding="utf-8")
    assert text.count("<footer") == 1, f"{name}: expected exactly one footer, found {text.count('<footer')}"
    foot = "<footer>" + text.split("<footer>", 1)[1].split("</footer>", 1)[0] + "</footer>"
    return re.sub(r"<!--.*?-->", "", foot, flags=re.S)


def _children(foot):
    """[(tag, attrs, inner)] for the footer's top-level children."""
    parser = _FooterRegions()
    parser.raw = foot
    parser.feed(foot)
    return parser.children


def _regions(where, foot):
    """{region: inner html} for the three zone divs, in order, each exactly once."""
    kids = _children(foot)
    assert len(kids) == 3, (
        f"{where}: the footer is exactly three regions, found {len(kids)}: "
        f"{[(t, a.get('class')) for t, a, _ in kids]}")
    out = {}
    for (tag, attrs, inner), (region, cls) in zip(kids, _ZONE_CLASSES.items()):
        assert tag == "div" and attrs.get("class") == cls, (
            f"{where}: the {region} region must be <div class={cls!r}>, got <{tag} "
            f"class={attrs.get('class')!r}>")
        out[region] = inner.strip()
    return out


def _root_relative(href, name):
    """A footer target as the ONE path it names. The pages served from the portal root write their
    targets relative; 404.html and the generated pages write them absolute.

    The single allow-listed external navigation address passes through unchanged; every OTHER external
    form is refused here, which keeps this rule from becoming a licence to point the footer off-site."""
    if href in _EXTERNAL_NAV:
        return href
    if href.startswith("/"):
        return href
    assert not href.startswith(("http://", "https://", "//")), (
        f"{name}: a footer target must stay on this site, or be the one allow-listed AuScope "
        f"navigation address {_EXTERNAL_NAV[0]!r}; got {href!r}")
    return "/" + href


ENGINE = "engine/extract/_pages.py"
# Every surface wearing the footer, one test case each: a surface that drifts fails on its own line
# rather than masking the others.
SURFACES = _PORTAL_PAGES + (ENGINE,)


def _foot(where):
    """The footer html a surface writes."""
    return _engine_footer() if where == ENGINE else _footer_html(where)


def _text(where):
    """The document (or the engine's source) that styles a surface's footer."""
    return _pages_text() if where == ENGINE else (ROOT / where).read_text(encoding="utf-8")


def _expected_right(where):
    """The whole right zone: the live counts on the SPA, the probe status then the lock-up on the
    engine's footer, the lock-up alone on the other five pages."""
    if where == "index.html":
        return INDEX_STATUS
    if where.startswith("engine/"):
        return ENGINE_STATUS + LOCKUP
    return LOCKUP


def test_the_lockup_footers_are_every_surface_without_the_big_map():
    """FAILS IF the contract's list of lock-up footers stops being every footer surface but the SPA's,
    which is how a new page would be left without the lock-up at its bottom right."""
    assert sorted(LOCKUP_FOOTERS) == sorted(s for s in SURFACES if s != "index.html")


def test_the_pin_enumerates_every_page_the_portal_ships():
    """FAILS if a page is added to portal/ without the pins below reaching it."""
    assert _portal_pages() == sorted(_PORTAL_PAGES), (
        f"the portal ships {_portal_pages()}, which is not the set this pin enumerates; a new page "
        f"carries the one footer too, so add it to _PORTAL_PAGES")


# The left link as each surface writes it. The six portal pages style it by class="apilink" and explain
# it with a title, both required; the engine's footer is the one surface that need not carry them.
_LEFT_LINK = r'<a class="apilink" href="([^"]+)" title="[^"]*">(.*)</a>'
_ENGINE_LEFT_LINK = r'<a (?:class="apilink" )?href="([^"]+)"(?: title="[^"]*")?>(.*)</a>'


@pytest.mark.parametrize("where", SURFACES)
def test_every_surface_carries_the_same_three_regions_with_the_contract_strings(where):
    """REGIONS and STRINGS, on all seven surfaces. FAILS if a region is missing, out of order or holds
    another's content, if a portal page's left link loses class="apilink" or its title, if the left
    label or the centre line drifts, or if the right region is anything but the surface's contents:
    its status, then the lock-up on every surface without the big map.

    Non-vacuous in every half: the earlier footers fail the left label (it read "Machine-readable
    record (MTCAT JSON)"), the centre (it carried the copyright clause, and then the address as the
    link's text) and the right region (it held the appearance control, and then nothing)."""
    regions = _regions(where, _foot(where))
    link = re.fullmatch(_ENGINE_LEFT_LINK if where == ENGINE else _LEFT_LINK, regions["left"], re.S)
    assert link, f"{where}: the left zone holds the MTCAT link and nothing else: {regions['left']!r}"
    label = " ".join(entities(link.group(2)).split())
    assert label == f"{LEFT_LABEL} {ARROW}", (
        f"{where}: the left region must read {LEFT_LABEL!r} with the leaves-the-site arrow, "
        f"got {label!r}")
    assert _root_relative(link.group(1), where) == MTCAT, (
        f"{where}: the left link must resolve to {MTCAT}, got {link.group(1)!r}")

    centre = " ".join(entities(re.sub(r"<[^>]+>", "", regions["centre"])).split())
    assert centre == CENTRE, f"{where}: centre must read {CENTRE!r}, got {centre!r}"
    clinks = re.findall(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', regions["centre"], re.S)
    assert [(h, " ".join(t.split())) for h, t in clinks] == [
        (_EXTERNAL_NAV[0], CENTRE_LINK_TEXT)], (
        f"{where}: the acknowledgement carries exactly one link, the AuScope address under the "
        f"organisation's name: {regions['centre']!r}")
    assert flat(regions["centre"]) == FOOTER_CENTRE_MARKUP, (
        f"{where}: the centre must be the contract's markup, character for character once "
        f"references are resolved:\n  got  {flat(regions['centre'])!r}\n  want {FOOTER_CENTRE_MARKUP!r}")
    assert ADDRESS_TEXT not in re.sub(r"<[^>]+>", "", regions["centre"]), (
        f"{where}: the address is the link's target, never printed as text: {regions['centre']!r}")

    right = flat(regions["right"])
    assert right == flat(_expected_right(where)), (
        f"{where}: the right region must be the surface's status and lock-up as its contents call "
        "for, and nothing else:\n"
        f"  got  {right!r}\n  want {flat(_expected_right(where))!r}")


def test_a_generated_page_without_status_keeps_the_lockup_alone():
    """The engine's status is contextual and may be empty. FAILS IF an empty status leaves a
    placeholder behind or takes the lock-up with it: the right zone is then the lock-up alone, exactly
    as on the five static pages without a status."""
    right = _regions("engine/extract/_pages.py", _engine_footer(""))["right"]
    assert flat(right) == LOCKUP, f"an empty status must leave the lock-up alone: {right!r}"


def test_the_surfaces_agree_on_where_the_footer_points():
    """TARGETS. The MTCAT document is ONE destination reached from every surface, compared as a
    root-relative path. FAILS if a surface retargets it, or if the SPA's relative form stops
    resolving to the engine's absolute one."""
    idx_left = re.findall(r'<a class="apilink" href="([^"]+)"', _footer_html("index.html"))
    assert idx_left == ["data/mtcat.json"], (
        f"index.html's MTCAT link must stay at data/mtcat.json, got {idx_left}")
    assert "/" + idx_left[0] == MTCAT, (
        f"the SPA's relative MTCAT link must resolve to the engine's {MTCAT}, got {idx_left[0]}")
    eng_left = _regions("engine/extract/_pages.py", _engine_footer())["left"]
    assert re.findall(r'href="([^"]+)"', eng_left) == [MTCAT], (
        f"the engine footer's MTCAT link must target {MTCAT}")


def test_the_white_lockup_png_stays_committed_unaltered_and_no_footer_names_it():
    """The white PNG lock-up is committed as its rights holder published it. FAILS if the file is
    missing or its bytes change (a resize, a re-encode, a recolour, a metadata strip), or if any
    footer names it."""
    path = ROOT / LOGO_SRC.lstrip("/")
    assert path.is_file(), f"{LOGO_SRC} stays committed"
    raw = path.read_bytes()
    assert len(raw) == LOGO_BYTES, f"{LOGO_SRC}: expected {LOGO_BYTES} bytes, found {len(raw)}"
    assert hashlib.sha256(raw).hexdigest() == LOGO_SHA256, (
        f"{LOGO_SRC}: the committed bytes are not the brand kit's; it must never be re-encoded")
    assert raw[:8] == b"\x89PNG\r\n\x1a\n", f"{LOGO_SRC}: not a PNG"
    width, height = struct.unpack(">II", raw[16:24])
    assert (width, height) == LOGO_PIXELS, (
        f"{LOGO_SRC}: expected {LOGO_PIXELS[0]}x{LOGO_PIXELS[1]}, found {width}x{height}")
    assert raw[24] == 8 and raw[25] == 6, (
        f"{LOGO_SRC}: expected 8-bit RGBA (colour type 6), found bit depth {raw[24]} type {raw[25]}")
    name = LOGO_SRC.rsplit("/", 1)[-1]
    for where in SURFACES:
        assert name not in _foot(where), f"{where}: the footer names the white lock-up {name}"


def _no_external_fetch(where, footer_html, sheet):
    """THE ONE EXTERNAL TARGET, second half. A footer may NAVIGATE to the allow-listed AuScope
    address; what it FETCHES is the lock-up, same-origin and root-absolute, on the surfaces that
    draw it, and nothing else on any surface: no other image, no stylesheet, no script, no url() in
    the rules that style it."""
    want = [LOCKUP_LIGHT] if where in LOCKUP_FOOTERS else []
    srcs = re.findall(r"""\bsrc\s*=\s*["']?([^"'\s>]+)""", footer_html)
    assert srcs == want, f"{where}: the footer fetches {want} and nothing else, found {srcs}"
    assert footer_html.count("src=") == len(want), f"{where}: every src in the footer is counted"
    assert "<link" not in footer_html and "@import" not in footer_html, (
        f"{where}: a footer fetches no stylesheet of its own: {footer_html!r}")
    assert "<script" not in footer_html, f"{where}: a footer loads no script"
    assert "url(" not in sheet, f"{where}: a footer rule must not fetch a resource: {sheet!r}"
    assert "@import" not in sheet, f"{where}: the footer's rules must not @import"


@pytest.mark.parametrize("where", SURFACES)
def test_no_footer_fetches_anything_but_the_lockup(where):
    """THE ONE EXTERNAL TARGET, held on every surface. See _no_external_fetch."""
    sheet = "".join(f"{sel}{{{body}}}" for sel, body in _SET_RE.findall(_outside_queries(_text(where))))
    _no_external_fetch(where, _foot(where), sheet)


@pytest.mark.parametrize("where", SURFACES)
def test_the_retired_content_has_left_every_footer(where):
    """THE RETIRED CONTENT STAYS RETIRED. FAILS if Releases, About this build, the disclosure popover,
    the copyright clause, the old left label or the retired footer logo (orglogo) comes back to a
    footer on any surface. Swept from the whole document for the popover's class and the retired
    logo's, because a rule left behind styles an element someone will re-add."""
    foot = _foot(where)
    for gone in RETIRED:
        assert gone not in entities(foot), f"{where}: {gone!r} left the footer and must not come back"
    for cls in RETIRED_CLASSES:
        assert cls not in _text(where), f"{where}: the {cls} markup and its CSS are retired"


# What makes an element a control, by tag and by attribute. A footer carries text and links only.
_CONTROL_TAGS = {"button", "input", "select", "textarea", "fieldset", "details", "summary", "label",
                 "form"}
_CONTROL_ATTRS = ("aria-pressed", "aria-checked", "role", "tabindex", "contenteditable")


class _Tags(HTMLParser):
    """(tag, attrs) for every start tag in a fragment, comments excluded by the parser."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


@pytest.mark.parametrize("where", SURFACES)
def test_no_footer_carries_a_control(where):
    """NO CONTROL, on all seven surfaces. FAILS if a footer carries a button, an input or any other
    form control, a control group or a pressed state, or an inline handler, which the deployed CSP
    would block. Non-vacuous: a labelled group of two buttons carrying aria-pressed, the shape a
    footer appearance control takes, fails it on every surface by tag, by role and by pressed
    state."""
    foot = _foot(where)
    parser = _Tags()
    parser.feed(foot)
    assert parser.tags, f"{where}: the footer parsed to no elements, so this pin would hold nothing"
    controls = [(tag, attrs) for tag, attrs in parser.tags
                if tag in _CONTROL_TAGS or any(a in attrs for a in _CONTROL_ATTRS)]
    assert not controls, f"{where}: a footer carries text and links only, found {controls}"
    handlers = [(tag, a) for tag, attrs in parser.tags for a in attrs if a.startswith("on")]
    assert not handlers, f"{where}: the footer carries an inline handler: {handlers}"
    assert not re.search(r"\son[a-z]+\s*=", foot), f"{where}: the footer carries an inline handler"


@pytest.mark.parametrize("where", SURFACES)
def test_every_footer_is_a_wrapping_flex_row_whose_side_zones_take_equal_zero_basis(where):
    """GEOMETRY, on every surface at once. The centre is the region that yields: the left link and
    the right zone are each a fixed object that reads badly broken, and the acknowledgement line is
    prose that does not.

    THE SIDE ZONES TAKE EQUAL ZERO BASIS, which is what page-centres the acknowledgement: zones that
    size to their own content leave the centre centred in the LEFTOVER space. flex:1 1 0 on both sides
    makes them the same width whatever they hold, the lock-up on six surfaces and the live counts on
    the map page included; min-width:0 lets a side zone go under its own content rather than force a
    wrap. The right zone is a row of its own, so what it holds sits against the right edge.

    There are two states below one row and each is pinned. Below the width the three regions need,
    the centre takes a row of its own UNDER the other two; below the width those two need, every
    region takes a row, which is the 375px stack.

    FAILS if a footer stops being a wrapping flex row or a query container, if either side zone stops
    taking the zero basis, if the right zone stops holding its content against the right edge, if the
    centre stops being content-sized or centred, if either state below one row goes, if one stops
    following the rules it overrides, or if a viewport rule comes back in their place."""
    text = _text(where)
    rules = _rule_set(where, text)
    box = rules["footer"]
    for decl in ("display:flex", "flex-wrap:wrap", "align-items:center"):
        assert decl in box, f"{where}: the footer must declare {decl}: {box!r}"
    assert "container-type:inline-size" in box, (
        f"{where}: the footer must establish the query container its own rules ask about; "
        f"without it neither @container rule can ever match: {box!r}")

    for side in (".fleft", ".fright"):
        assert "flex:1 1 0" in rules[side], (
            f"{where}: {side} must grow from a zero basis, or it sizes to its own content and "
            f"the acknowledgement is centred in what is left over rather than on the page: "
            f"{rules[side]!r}")
        assert "min-width:0" in rules[side], (
            f"{where}: {side} must be allowed under its own content, or the equal basis it "
            f"takes above forces a wrap instead: {rules[side]!r}")
    for decl in ("display:flex", "justify-content:flex-end", "align-items:center"):
        assert decl in rules[".fright"], (
            f"{where}: the right zone holds its status in a row against the right edge: "
            f"{rules['.fright']!r}")
    assert "flex:0 1 auto" in rules[".fcenter"], (
        f"{where}: the centre is content-sized between the two equal side zones; growing it "
        f"too would take a third of the free space and push the axis: {rules['.fcenter']!r}")
    for decl in ("min-width:0", "text-align:center"):
        assert decl in rules[".fcenter"], (
            f"{where}: the centre zone must declare {decl}: {rules['.fcenter']!r}")

    centre_row, stacked = text.find(_CENTRE_ROW_RULE), text.find(_STACK_RULE)
    assert centre_row > 0 and stacked > centre_row, (
        f"{where}: every region must take a full row once the left link and the right zone "
        f"cannot share one, in a rule that FOLLOWS the centre's own-row rule: the two tie on "
        f"specificity, so placed above it the stack would not restore the 375px order")
    for zone in (".fleft{", ".fcenter{", ".fright{"):
        assert 0 < text.index(zone) < centre_row, (
            f"{where}: both states below one row must follow the zone rules they override, {zone}"
            f" included; the selectors tie on specificity and source order alone decides")
    for retired in ("@media(max-width:760px){.fzone", "@media (max-width:760px){.fzone",
                    "footer .apilink{", "footer .foot-main{", "footer .foot-right{"):
        assert retired not in text, (
            f"{where}: the footer's width is not the viewport's on any surface and its zones "
            f"are named the same everywhere: found the retired {retired!r}")


# THE CONSTANT FOOTER and THE BOLD CENTRE, held on every surface at once.
#
# The footer is always at the bottom of the VIEWPORT, not at the end of the scroll: content passes
# beneath it and the last line of that content is never left under it, because a sticky box keeps
# its own place in flow and simply comes to rest there. That needs three things together and each is
# pinned below: a page-height column, a growing block above the footer, and the sticky rule itself.
#
# WHY STICKY AND NOT FIXED: a fixed footer leaves no box in flow, so every page would owe it a
# body padding-bottom equal to a height that changes with the wrap state and with the viewport.
#
# THE RETURN TO FLOW IS A MEASUREMENT: at 560px and below at least one surface is a three-row footer,
# which on a phone would sit over most of the screen, so below it the footer is an ordinary block at
# the end of the document.
_FLOW_BELOW = 560
_STICKY = ("position:sticky", "bottom:0")

# The block that GROWS to fill the column. The footer is a SIBLING of main on every surface, so main
# is that block everywhere; it also states a width, because a flex item with an auto width and auto
# side margins shrinks to its content instead of stretching to the reading measure.
_GROWS = {
    "404.html": ("main", "flex:1 0 auto"),
    "about.html": ("main", "flex:1 0 auto"),
    "add-survey.html": ("main", "flex:1 0 auto"),
    "brand.html": ("main", "flex:1 0 auto"),
    "index.html": ("main", "flex:1"),
    "releases.html": ("main", "flex:1 0 auto"),
}
_ENGINE_GROWS = ("main", "flex:1 0 auto")

# The opaque ground under the footer: the --surface token, the ground every chrome surface (header,
# footer, cards) shares. A sticky footer with a transparent background shows the
# content sliding under it.
_GROUND = "background:var(--surface)"

# The centre line's weight, as ONE declaration on the zone rather than a span around the sentence.
# 700 is the sans family's bold; the header wordmark's 800 is a display weight for its heavy "Aus".
_CENTRE_WEIGHT = "font-weight:700"

_FOOTER_RULE = r"(?m)^\s*footer\{([^}]*)\}"
_FLOW_RULE = f"@media (max-width:{_FLOW_BELOW}px){{footer{{position:static}}}}"
_CENTRE_ROW_RULE = "@container (max-width:1421px){.fcenter{order:1;flex:1 1 100%}}"
_STACK_RULE = "@container (max-width:520px){.fzone{order:0;flex:1 1 100%;text-align:left}}"

# The selectors that ARE the footer's rule set, longest first so the alternation cannot take the
# short form of a longer selector.
_SET_RE = re.compile(r"(?m)(?:^[ \t]*|(?<=\}))"
                     r"(footer a|footer|\.fleft|\.fcenter|\.fright)"
                     r"\{([^}]*)\}")
_RULE_SET = ("footer", "footer a", ".fleft", ".fcenter", ".fright")


def _rule_set(where, text):
    """{selector: declarations} for the footer's whole rule set, queries removed.

    The two @container states and the return-to-flow rule restate these selectors, so the base rules
    are read with the query blocks stripped and the three queries are then required, once each, from
    the full text."""
    out = {}
    for sel, body in _SET_RE.findall(_outside_queries(text)):
        assert sel not in out, (
            f"{where}: {sel} is declared twice; a second declaration overrides the pinned rule at "
            f"equal specificity and is exactly how the surfaces drifted apart")
        out[sel] = " ".join(body.split())
    missing = [s for s in _RULE_SET if s not in out]
    assert not missing, (
        f"{where}: the footer rule set is one set on every surface; this one is missing {missing}")
    for query in (_CENTRE_ROW_RULE, _STACK_RULE, _FLOW_RULE):
        assert text.count(query) == 1, (
            f"{where}: expected exactly one {query!r}, found {text.count(query)}")
    return out


def _footer_rule(where, text):
    rules = re.findall(_FOOTER_RULE, _outside_queries(text))
    assert len(rules) == 1, f"{where}: expected exactly one footer rule, found {len(rules)}"
    return " ".join(rules[0].split())


@pytest.mark.parametrize("where", SURFACES)
def test_every_surface_pins_the_footer_to_the_viewport_bottom(where):
    """THE CONSTANT FOOTER. FAILS if any surface's footer stops being sticky to the bottom edge, if
    it loses the opaque ground that keeps scrolling content from showing through it, or if it loses
    the stacking order that keeps a frozen table column from painting over it."""
    rule = _footer_rule(where, _text(where))
    for decl in _STICKY:
        assert decl in rule, (
            f"{where}: the footer must declare {decl}, or it only appears at the end of the "
            f"scroll instead of staying on screen: {rule!r}")
    assert _GROUND in rule, (
        f"{where}: a sticky footer needs the chrome's opaque ground under it, or the content "
        f"passing beneath shows through the text: expected {_GROUND!r} in {rule!r}")
    assert re.search(r"z-index:[1-9]", rule), (
        f"{where}: the footer must name its own stacking order; a table's frozen first column "
        f"declares z-index:2 and would otherwise paint over it: {rule!r}")


def test_every_surface_makes_the_page_a_full_height_column():
    """THE COLUMN THE STICKY FOOTER NEEDS. A sticky box is never pushed DOWN from where it sits in
    flow, so on a document shorter than the screen the footer would sit halfway up the page unless
    the page itself is a viewport-tall column with a growing block above the footer.

    FAILS if any surface stops being that column, or if the block above the footer stops growing."""
    surfaces = [(name, (ROOT / name).read_text(encoding="utf-8"), _GROWS[name])
                for name in _portal_pages()]
    surfaces.append(("engine/extract/_pages.py", _pages_text(), _ENGINE_GROWS))
    for where, text, (selector, growth) in surfaces:
        base = _outside_queries(text)
        body = re.findall(r"(?m)^\s*body\{([^}]*)\}", base)
        assert len(body) == 1, f"{where}: expected exactly one body rule, found {len(body)}"
        body = " ".join(body[0].split())
        for decl in ("display:flex", "flex-direction:column"):
            assert decl in body, (
                f"{where}: the page must be a column, or the footer cannot be pushed to the "
                f"bottom of a short one: {body!r}")
        assert "min-height:100vh" in body or re.search(r"(?m)^\s*html,body\{[^}]*height:100%", base), (
            f"{where}: the column must be at least a viewport tall, or a short page ends above the "
            f"screen's bottom edge and the footer with it: {body!r}")
        rules = re.findall(rf"(?m)^\s*{re.escape(selector)}\{{([^}}]*)\}}", base)
        grows = [r for r in rules if growth in r]
        assert len(grows) == 1, (
            f"{where}: exactly one {selector} rule must declare {growth}, so the free space above "
            f"the footer is taken by content and not left under it; found {len(grows)} of "
            f"{len(rules)}: {rules!r}")
        assert "width:min(" in grows[0] or "display:flex" in grows[0], (
            f"{where}: {selector} must state a width; as a flex item with auto side margins an "
            f"auto width shrinks to the content instead of holding the reading measure: "
            f"{grows[0]!r}")


def test_the_footer_is_a_sibling_of_main_on_every_surface():
    """THE FOOTER IS THE PAGE'S BOTTOM EDGE, not the reading column's. Inside main it is neither a
    contentinfo landmark nor wide enough to hold the bold acknowledgement on one line.

    FAILS if any page moves its footer back inside main."""
    for name in _portal_pages():
        text = (ROOT / name).read_text(encoding="utf-8")
        body = text.split("<body", 1)[1]
        assert body.index("</main>") < body.index("<footer"), (
            f"{name}: the footer must follow </main>, not sit inside the reading column")
    shell = function_source("_shell")
    call = re.search(r"_site_footer\(", shell)
    assert call, "engine/extract/_pages.py: _shell must write the footer"
    assert shell.index('"</main>') < call.start(), (
        "engine/extract/_pages.py: _shell must close main before it writes the footer")


def test_every_surface_returns_the_footer_to_flow_below_the_measured_width():
    """THE NARROW-WIDTH RETURN TO FLOW. FAILS if a surface loses the rule, if the breakpoint drifts
    off the measured width, or if the rule is placed where source order lets the sticky rule win it
    back (the two tie on specificity)."""
    surfaces = [(name, (ROOT / name).read_text(encoding="utf-8")) for name in _portal_pages()]
    surfaces.append(("engine/extract/_pages.py", _pages_text()))
    for where, text in surfaces:
        at = text.find(_FLOW_RULE)
        assert at > 0, f"{where}: expected the return-to-flow rule {_FLOW_RULE!r}"
        assert text.count(_FLOW_RULE) == 1, f"{where}: the return-to-flow rule must be declared once"
        assert at > re.search(_FOOTER_RULE, text).start(), (
            f"{where}: the return-to-flow rule must FOLLOW the footer's own rule, or the sticky "
            f"declaration wins at equal specificity and the narrow-width footer stays pinned")


@pytest.mark.parametrize("where", SURFACES)
def test_the_centre_line_is_bold_on_every_surface(where):
    """THE BOLD CENTRE, as ONE declaration on the zone. The linked organisation's name inherits it,
    so the whole line reads at one weight. FAILS if any surface's centre zone loses the weight, or if
    another rule in the footer's set (the link rule included) takes a weight of its own, which would
    set the name apart from its sentence."""
    rules = _rule_set(where, _text(where))
    assert _CENTRE_WEIGHT in rules[".fcenter"], (
        f"{where}: the centre zone must declare {_CENTRE_WEIGHT}: {rules['.fcenter']!r}")
    for sibling in (s for s in _RULE_SET if s != ".fcenter"):
        assert "font-weight" not in rules[sibling], (
            f"{where}: the weight belongs to the centre zone alone; a second declaration "
            f"in {sibling!r} is a second place for the surfaces to drift: {rules[sibling]!r}")


def _anchors(where, footer_html):
    """(href, whole opening tag) for every anchor in a footer, in source order."""
    out = []
    for tag in re.findall(r"<a\b[^>]*>", footer_html):
        href = re.search(r'href="([^"]*)"', tag)
        assert href, f"{where}: a footer anchor carries no href: {tag!r}"
        out.append((href.group(1), tag))
    assert out, f"{where}: the footer carries no anchor at all"
    return out


@pytest.mark.parametrize("where", SURFACES)
def test_the_auscope_anchors_open_in_a_new_tab_on_every_surface(where):
    """THE EXTERNAL ANCHORS LEAVE THE TAB, and hand the opened page nothing. The organisation's name
    in the centre sentence links the AuScope address on every surface, and the lock-up links it
    again on the six surfaces that draw it; each carries target="_blank" rel="noopener noreferrer"
    in that one spelling.

    FAILS if a surface loses either attribute on either anchor, spells the pair differently, links
    the address more or fewer times than its contents call for (twice where the lock-up is drawn,
    once on the SPA), or gives an IN-SITE footer link a target of its own."""
    anchors = _anchors(where, _foot(where))
    external = [tag for href, tag in anchors if href in _EXTERNAL_NAV]
    want = 2 if where in LOCKUP_FOOTERS else 1
    assert len(external) == want, (
        f"{where}: the footer carries {want} anchor(s) to {_EXTERNAL_NAV[0]}, the organisation's "
        f"name{' and the lock-up' if want == 2 else ''}; found {len(external)}: {external!r}")
    for tag in external:
        assert _NEW_TAB in tag, (
            f"{where}: an anchor that leaves the site opens in a new tab and hands it no opener; "
            f"expected {_NEW_TAB!r} in {tag!r}")
    if want == 2:
        assert 'class="orglockup"' in external[1], (
            f"{where}: the second AuScope anchor is the lock-up, after the centre's name: {external!r}")
    for href, tag in anchors:
        if href in _EXTERNAL_NAV:
            continue
        assert "target=" not in tag, f"{where}: an in-site footer link stays in this tab, got {tag!r}"


def test_every_portal_page_declares_one_footer_rule_in_tokens():
    """ONE FOOTER MEANS ONE RULE, not six rules that happen to agree. A footer whose content is
    pinned character for character but whose box is declared six times drifts in the only dimension
    the content pins cannot see: its height.

    EVERY PORTAL PAGE IS A TOKEN SURFACE NOW. 404.html, which Caddy serves for any unmatched path,
    once wrote its footer in literal colours; it carries the token block like every other page, so
    the tokens reach it too. FAILS if any page's footer rule drifts by a character, or if a page
    falls back to literal colours."""
    rules = {name: _footer_rule(name, (ROOT / name).read_text(encoding="utf-8")) for name in _portal_pages()}
    literal = [name for name, rule in rules.items() if re.search(r"#[0-9A-Fa-f]{3,6}\b", rule)]
    assert literal == [], f"every footer rule reads the token layer; these write literals: {literal}"
    assert len(set(rules.values())) == 1, (
        "the portal pages must declare the IDENTICAL footer rule; found "
        + "\n".join(f"  {n}: {r}" for n, r in sorted(rules.items())))


@pytest.mark.parametrize("where", SURFACES)
def test_every_surface_declares_the_one_footer_rule_set(where):
    """ONE FOOTER MEANS ONE RULE SET, on ALL SEVEN surfaces. portal/index.html is the master; every
    other document and the engine's _CSS carry the same rules, character for character, plus the same
    two @container states and the same return-to-flow rule. Every colour in the set is a token, so the
    one set reads the same tokens on every surface.

    FAILS if any surface's footer rule set drifts by a character, if a surface declares one of the
    rules twice, if a rule goes missing, if a rule writes a literal colour, or if either query or the
    flow rule drifts."""
    assert len(SURFACES) == 7, f"seven surfaces wear this footer, found {len(SURFACES)}"
    master = _rule_set("portal/index.html", _index_text())
    for sel, body in master.items():
        assert not re.search(r"#[0-9A-Fa-f]{3,6}\b", body), (
            f"portal/index.html: {sel} writes a literal colour instead of a token: {body!r}")
    got = _rule_set(where, _text(where))
    for sel in _RULE_SET:
        assert got[sel] == master[sel], (
            f"{where}: {sel} must be portal/index.html's rule, character for character.\n"
            f"  master: {master[sel]!r}\n  {where}: {got[sel]!r}")


def test_no_footer_on_any_surface_carries_a_map_credit():
    """NO FOOTER CREDITS A BASEMAP, on any of the seven surfaces. The obligation is met where the map
    is, in its own attribution control (tests/test_map_attribution.py holds that half). FAILS if any
    portal document or the engine's emitter reintroduces the credit, by class or by either link."""
    for name in _portal_pages():
        text = (ROOT / name).read_text(encoding="utf-8")
        for mark in _NO_CREDIT_MARKS:
            assert mark not in text, (
                f"{name}: the basemap credit belongs to the map's own attribution control, not to a "
                f"footer that seven surfaces share; found {mark!r}")
    eng = _pages_text()
    for mark in _NO_CREDIT_MARKS:
        assert mark not in eng, (
            f"engine/extract/_pages.py: the generated tier draws no map and credits no basemap; "
            f"found {mark!r}")


@pytest.mark.parametrize("where", SURFACES)
def test_the_centre_zone_holds_the_same_markup_on_every_surface(where):
    """ONE FOOTER MEANS ONE BOX, and a box is its rules AND its contents. The rule set is held
    identical above; this holds the acknowledgement's own markup identical, separator spellings
    resolved. The centre zone sets the footer's height and baseline below the one-row breakpoint, so
    with the rule set and this markup identical the seven footers are the same box by construction.

    FAILS if any surface adds, drops or reorders anything inside the acknowledgement: a second line,
    a span, a wrapper, a stray nbsp."""
    master = " ".join(entities(_regions("index.html", _footer_html("index.html"))["centre"]).split())
    got = " ".join(entities(_regions(where, _foot(where))["centre"]).split())
    assert got == master, (
        f"{where}: the acknowledgement must hold portal/index.html's markup once the "
        f"separator's spelling is resolved.\n  master: {master!r}\n  {where}: {got!r}")


# THE LOCK-UP KEEPS THE FOOTER'S HEIGHT. The lock-up is drawn 30px tall, and the footer's text line is
# 18.75px, 12.5px at line-height 1.5. Without a margin the 30px box sets the height of the row it
# stands in and grows every sticky footer by 11.25px; the anchor's negative block margin makes its
# margin box exactly one text line, so the row is as tall as its text and the artwork overhangs into
# the footer's own 7px padding. Measured in Chrome at a device scale factor of 1: a
# lock-up footer is 33.75px on one row (1458px of viewport and up) and 56.5px on two (557px to
# 1457px), the heights it had with an empty right zone. Below 557px the footer has returned to flow
# and its zones stack, so the lock-up's row adds one text line there.
_LOCKUP_RULE_RE = re.compile(r"(?m)^\s*\.orglockup\{([^}]*)\}")


def _texts():
    return {where: _text(where) for where in SURFACES}


def test_the_lockup_rules_ride_every_surface_whose_footer_draws_it():
    """FAILS IF a lock-up footer's two rules drift by a character, go missing or are declared twice,
    or if the SPA declares them: its footer draws no lock-up, so a rule there would style nothing."""
    for where, text in _texts().items():
        for rule in LOCKUP_RULES:
            want = 1 if where in LOCKUP_FOOTERS else 0
            assert text.count(rule) == want, (
                f"{where}: expected {want} {rule!r}, found {text.count(rule)}")
    assert ".orglockup" not in _index_text(), "index.html draws no .orglockup and declares no rule for one"


@pytest.mark.parametrize("where", LOCKUP_FOOTERS)
def test_the_lockups_margin_box_is_one_footer_text_line(where):
    """THE LOCK-UP KEEPS THE FOOTER'S HEIGHT, as arithmetic over the surface's own rules. FAILS IF the
    lock-up's declared height, its anchor's block margins, or the footer's font size or line height
    move apart, so that the lock-up's margin box stops being one footer text line: taller and it sets
    the row's height, 11.25px taller than the text at the 30px lock-up with no margin."""
    text = _text(where)
    footer = _footer_rule(where, text)
    size = float(re.search(r"(?:^|;)font-size:([\d.]+)px", footer).group(1))
    line = float(re.search(r"(?:^|;)line-height:([\d.]+)(?:;|$)", footer).group(1))
    assert size * line == FOOTER_LINE, f"{where}: the footer's text line is {FOOTER_LINE}px: {footer!r}"
    anchor = _LOCKUP_RULE_RE.findall(_outside_queries(text))
    assert len(anchor) == 1, f"{where}: one .orglockup rule, found {len(anchor)}"
    margin = re.search(r"(?:^|;)margin:(-?[\d.]+)px 0(?:;|$)", anchor[0])
    assert margin, f"{where}: the lock-up's anchor takes a block margin and no inline one: {anchor[0]!r}"
    img = re.findall(r"(?m)^\s*\.orglockup img\{([^}]*)\}", text)
    height = re.search(r"(?:^|;)height:(\d+)px", img[0]) if len(img) == 1 else None
    assert height and int(height.group(1)) == LOCKUP_HEIGHT, f"{where}: the lock-up is {LOCKUP_HEIGHT}px tall"
    assert LOCKUP_HEIGHT + 2 * float(margin.group(1)) == size * line, (
        f"{where}: the lock-up's margin box must be one footer text line, {size * line}px; got "
        f"{LOCKUP_HEIGHT}px with {margin.group(1)}px margins")
    assert "line-height:0" in anchor[0] and "display:inline-block" in anchor[0], (
        f"{where}: the anchor takes no line box of its own, so the image box is its whole height")
