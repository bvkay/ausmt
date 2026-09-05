"""One footer, three regions, the same on the SPA, on the five chrome pages and on the static pages
the engine emits.

The two surfaces had drifted into two different footers. The SPA carried the MTCAT link, then one
run-on span holding the copyright, the licence note, Releases and the About-this-build control. The
static pages carried a two-row grid with different wording again ("Machine-readable catalogue",
"an AuScope service", "each download carries its licence") and a per-page-kind left link, so no two
page kinds even agreed with each other. The rule is one footer: LEFT the machine-readable
catalogue, CENTRE the AuScope acknowledgement with the attribution and the licence note, RIGHT the
AuScope-NCRIS lockup. Releases and About this build leave the footer on every surface; about.html
carries the running build's identity and the route to the releases page in its own body, which is
pinned in test_about_uniform_chrome.py.

WHY THE ENGINE HALF LIVES HERE rather than in engine/tests, and why it reads _pages.py's SOURCE
text: the same two reasons test_header_geometry_parity.py gives. portal-ci runs on portal/** AND on
engine/extract/_pages.py, so an edit to either surface fires this module, where the engine workflow
triggers on engine/** alone and cannot see an index.html edit; and _pages.py cannot simply be
imported (it sibling-imports _au_outline and _stationcheck, which need the engine's own path set
up). The engine workflow holds its own half of this in engine/tests/test_index_pages.py, asserted
against real rendered pages; this module is what stops the two surfaces diverging again.

THE SEPARATOR IS U+00B7 on every surface, spelt here as an escape so a mis-decoded read of this
file cannot let a hyphen or a dash through the pin. index.html, about.html and add-survey.html write
the character literally, releases.html, brand.html and 404.html write the named reference and
_pages.py writes the numeric one; all are asserted as the codepoint.

Each assertion states its failure criterion:

  * REGIONS - FAILS if either surface does not carry exactly three footer regions, or if a region
    holds something belonging to another (the licence note in with the acknowledgement's link, the
    lockup outside its own zone).
  * STRINGS - FAILS if either surface's centre line drifts from the wording, or if the
    left link's label stops being the MTCAT one.
  * TARGETS - FAILS if the two surfaces stop agreeing on where a region's links point. The MTCAT
    document is one target expressed twice: the SPA is served from the portal root and writes it
    relative, the static pages are served from /surveys/<slug> and cannot, so the pin holds the
    ROOT-RELATIVE form of both against each other rather than the raw strings.
  * THE ONE EXTERNAL TARGET - FAILS if a footer reaches any external host other than the single
    allow-listed AuScope navigation address, and FAILS in the other direction if a footer FETCHES
    anything from an external host. See _EXTERNAL_NAV below: the rule adds a navigation href, not
    a runtime dependency, and the two are held apart rather than conflated.
  * THE LOCKUP IS A COMMITTED FILE - FAILS if portal/vendor/auscope-ncris-white.png is missing or
    has been resized, re-encoded or recoloured. A footer image is a promise about a file, and this
    one is a third-party trademark asset that must ship as its rights holder published it.
  * GEOMETRY - FAILS if any surface stops being a wrapping flex row or stops being a query
    container, if a side zone stops taking the equal zero basis, if the centre stops being
    content-sized or stops centring its text, if either state below one row goes and the
    acknowledgement is left centred in the space beside the machine-readable link, or a 375px
    viewport collides instead of stacking.
  * THE LOCKUP NEVER OUTGROWS ITS ZONE - FAILS if the image loses its max-width cap, which is what
    keeps it inside the stacked 375px row whatever the committed file's own width becomes.
  * PARITY ACROSS THE PORTAL - FAILS if any HTML document the portal ships stops carrying the three
    regions, or drifts on a string, a target or a separator.
  * THE RETIRED CONTROLS STAY RETIRED - FAILS if Releases, About this build or the disclosure
    popover (markup or CSS) comes back to any footer.
  * THE TWO EXTERNAL ANCHORS OPEN IN A NEW TAB - FAILS if either AuScope anchor on any surface
    loses target="_blank" or rel="noopener noreferrer", spells the pair differently, or if an
    in-site footer link takes a target of its own.
  * ONE FOOTER RULE - FAILS if the five documents that share the portal's token layer stop
    declaring the IDENTICAL footer rule, or if a second document leaves that layer. The content
    pins cannot see the footer's box, which is where the surfaces drifted apart on height.
  * ONE FOOTER RULE SET, ON ALL SEVEN SURFACES - FAILS if any surface's footer rule set drifts from
    portal/index.html's by a character, once the token layer is resolved to the colours it carries.
    The rule above held the box across the five token surfaces and could not reach 404.html or the
    generated tier, which write the same colours as literals; those two carried a rule set of their
    own in rem units with no bottom padding, and that is what showed as the footers sitting
    differently and aligning differently between the Map, the hubs and About. Measured in Chrome
    before this pin, at 2560px the centre sentence's midpoint sat 245.55px left of the viewport's on
    the portal and 274.66px left of it on the generated tier; the footer stood 48.75px on one tier
    and 46.02px on the other, with the text baseline 4.69px apart.
  * THE SIDE ZONES TAKE EQUAL ZERO BASIS - FAILS if either side zone stops declaring flex:1 1 0 with
    min-width:0, or if the centre stops being content-sized. This is the header lesson restated:
    zones that size to their content leave the centre centred in the LEFTOVER space, not on the
    page. With both sides growing from the same zero basis they are always the same width, so the
    centre is page-centred whatever the machine-readable link and the lockup happen to measure.
    After it, the midpoint delta is 0.00px on all six surfaces at 2560, 1280 and 1024.

BOTH QUERIES ASK THE FOOTER'S OWN WIDTH, not the viewport's. On the static tier main is 840px on an
entity page, 920px on a hub and 1120px above 1180px of viewport, and on the portal the sibling pages
set their footers inside reading columns of 760px to 980px, so no single viewport number describes
"the three regions do not fit" on more than one page kind at a time.

THE OWN-ROW BREAKPOINT IS A MEASUREMENT OF THE CONTENT, not a design constant, and there is now ONE
of it because there is one rule set. Two side zones of the same width need twice the WIDER one, so
the equal zero basis lengthened what the row wants: measured in Chrome, the widest surface's centre
is 813.22px and its machine-readable link 285.98px, which puts one row at 1457.18px of footer. The
number is stated as the CONTENT width the query actually asks (1421px, 36px of padding narrower) and
verified either side of it. The acknowledgement lengthened the centre once when it replaced the bare
copyright line and again when it went bold; anything that changes a region's content moves this
number and it has to be re-measured.

The rule and every number this module holds it to: LANE-CONTRACT-FOOTER-AUSCOPE.md.
"""
import hashlib
import re
import struct
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # portal/
INDEX = ROOT / "index.html"
PAGES_PY = ROOT.parent / "engine" / "extract" / "_pages.py"

DOT = "·"

# The three regions, as the strings a reader sees. The centre and the right are asserted
# character-for-character; the left's label is, and its target is asserted separately because the
# two surfaces necessarily spell the same URL differently.
CENTRE = (f"AusMT is enabled by AuScope {DOT} www.auscope.org.au {DOT} "
          f"© 2026 AuScope and the AusMT contributors {DOT} Data licences vary by survey")
LEFT_LABEL = "Machine-readable record (MTCAT JSON)"
MTCAT = "/data/mtcat.json"

# THE ONE EXTERNAL TARGET. The rule links the AuScope relationship from the footer, so the centre's
# URL text and the lockup both navigate here. It is an exact allow-list of ONE address and it governs
# NAVIGATION ONLY: _no_external_fetch below holds the other half, that no footer on any surface may
# FETCH a resource (src, a stylesheet link, @import, url()) from a host that is not this site. A CDN
# outage or a compromise of a third-party host can tamper with a fetched byte; it cannot tamper with
# an <a href>, which is why the two are separate rules rather than one host list.
_EXTERNAL_NAV = ("https://www.auscope.org.au",)

# NO FOOTER CARRIES A MAP CREDIT, on any surface. The basemap's attribution is a licence obligation
# (OpenStreetMap data under ODbL, tiles rendered from Protomaps' build) and it is met where the map
# is: in the map's own attribution control, collapsed behind an (i) in the corner. It cannot be met
# in the footer, for the two reasons below.
#
# ONE: the footer is the same box on seven surfaces, and a line only the SPA carries makes it a
# different box there. Measured in Chrome with the credit in place, the SPA's footer stood 90.80px
# against 74.30px everywhere else at 1280 and 1024, and its acknowledgement's baseline sat 21.64px
# from the footer's top against 29.89px elsewhere at 2560.
#
# TWO: a fixed line of prose cannot follow the tile source. map.js keeps a CARTO fallback for the
# case where the pmtiles files are absent or the renderer fails to load, and a footer naming
# Protomaps would credit the wrong provider on that branch. The control reads each layer's own
# attribution, so the credit is whatever is actually drawing the map.
#
# Held as a negative on every surface, by the class AND by the two hrefs: a page could drop the class
# and still be making the claim.
_NO_CREDIT_MARKS = ("mapcredit", "https://www.openstreetmap.org/copyright", "https://protomaps.com")

# HOW THE TWO EXTERNAL ANCHORS OPEN. Both leave the site, so both open in a new tab and neither
# hands the opened page a handle on this one: target="_blank" gives the opened document
# window.opener, from which it can navigate the tab it was opened from to a look-alike, and the
# referrer would leak the reader's path through the catalogue to a third party. The pair is asserted
# as ONE literal string in ONE order so six documents and the engine's emitter cannot each spell it
# differently; it is the spelling every outbound anchor on this site carries, About's route to
# AuScope included. In-site links keep the same tab, which is why this is a per-anchor rule and not
# a document-wide base target.
_NEW_TAB = 'target="_blank" rel="noopener noreferrer"'

# The lockup, as the file the footer promises. Recorded from the AuScope brand kit's own bytes; see
# portal/vendor/README.md, which carries the same four facts beside the file.
LOGO_SRC = "/vendor/auscope-ncris-white.png"
LOGO_ALT = "AuScope and NCRIS"
LOGO_SHA256 = "595a564ece1151d94347331c1521381df987da437aa3080cff47a5280cf818f6"
LOGO_BYTES = 35628
LOGO_PIXELS = (1919, 325)

# What the rule took OUT of every footer. Held as a negative so the two controls cannot drift back
# in one page at a time: the popover's CSS is swept as well as its markup, because a rule left behind
# is an invitation to re-add the element it styles.
RETIRED = ("aboutbuild", "About this build", ">Releases<", "releases.html")


def _index_text():
    return INDEX.read_text(encoding="utf-8")


def _pages_text():
    return PAGES_PY.read_text(encoding="utf-8")


def _outside_queries(text):
    """`text` with every @media and @container block removed, brace-matched rather than
    regex-bounded.

    The base rules and their narrower-width overrides use the SAME selectors, so a pattern that does
    not exclude the query blocks finds each rule twice and an "exactly one" pin fails on a correct
    stylesheet. Excluding them is also what makes the exactly-one pin mean what it says: a SECOND
    unconditional declaration of a zone would override the pinned geometry at equal specificity."""
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


def _index_footer():
    """index.html's <footer> with HTML comments stripped, so prose inside it cannot satisfy a pin.

    NOTHING ELSE IS STRIPPED. This footer once had the SPA's basemap credit removed before any
    comparison, which is what let one surface carry a line the other six did not while every
    "identical everywhere" pin still passed. The credit is gone from every footer, so the readers
    compare what is there."""
    raw = _index_text().split("\n<footer>", 1)[1].split("</footer>", 1)[0]
    return re.sub(r"<!--.*?-->", "", raw, flags=re.S)


def _engine_footer():
    """The footer _site_footer() emits, assembled from the literal fragments in its return
    expression. Read from source, not rendered: this module cannot import _pages.py."""
    src = _pages_text()
    body = src.split("def _site_footer(", 1)[1].split('return ("\\n<footer>\\n"', 1)[1]
    body = body.split('"</footer>\\n")', 1)[0]
    # Every single- or double-quoted fragment in the return expression, joined in source order,
    # with the two module constants it interpolates resolved from their own definitions. An
    # UNRESOLVED brace is a hard failure: a new placeholder must be taught to this reader rather
    # than silently emptying a region and passing a substring pin.
    out = []
    for frag in re.findall(r"""(?:f?)'([^']*)'|(?:f?)"([^"]*)\"""", body):
        out.append(frag[0] or frag[1])
    text = "".join(out).replace("\\n", "\n")
    for name in ("_MTCAT_HREF", "_ARROW_OUT"):
        value = re.findall(rf'^{name} = "([^"]*)"', src, re.M)
        assert len(value) == 1, f"engine/extract/_pages.py: {name} is not a single string literal"
        text = text.replace("{" + name + "}", value[0])
    assert "{" not in text, (
        f"engine/extract/_pages.py: the footer interpolates something this reader cannot resolve, "
        f"so a region would be asserted empty: {text!r}")
    return text


def _entity(text):
    """The named/numeric character references a page writes, resolved, so the surfaces can be
    compared as the characters a reader sees rather than as three spellings of them."""
    text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
    return text.replace("&middot;", DOT).replace("&copy;", "©")


def _regions(footer, classes):
    """{region: inner html} for the three zone divs, each required exactly once."""
    out = {}
    for name, cls in classes.items():
        hits = re.findall(r'class="' + re.escape(cls) + r'"[^>]*>(.*?)</(?:div|span)>', footer, re.S)
        assert len(hits) == 1, (
            f"the footer must carry exactly one {name} region (class {cls!r}); found {len(hits)}")
        out[name] = hits[0].strip()
    return out


_ZONE_CLASSES = {"left": "fzone fleft", "centre": "fzone fcenter", "right": "fzone fright"}


def _index_regions():
    foot = _index_footer()
    left = re.findall(r'<a class="apilink"[^>]*>(.*?)</a>', foot, re.S)
    assert len(left) == 1, f"index.html's footer must carry exactly one MTCAT link; found {len(left)}"
    zones = _regions(foot, _ZONE_CLASSES)
    return {"left": left[0].strip(), "centre": zones["centre"], "right": zones["right"]}


def _engine_regions():
    return _regions(_engine_footer(), _ZONE_CLASSES)


def test_both_surfaces_carry_the_same_three_regions_with_the_owners_strings():
    """REGIONS and STRINGS. Non-vacuous in both halves: run against the pre-rule surfaces, both
    fail on the centre string (neither carried the AuScope acknowledgement) and both fail again on
    the right region, which held Releases and About this build rather than the lockup."""
    for where, regions in (("portal/index.html", _index_regions()),
                           ("engine/extract/_pages.py", _engine_regions())):
        left = _entity(regions["left"])
        assert LEFT_LABEL in left, f"{where}: the left region must read {LEFT_LABEL!r}, got {left!r}"
        assert "↗" in left, (
            f"{where}: the left link carries the leaves-this-page arrow (U+2197), got {left!r}")

        centre = " ".join(_entity(re.sub(r"<[^>]+>", "", regions["centre"])).split())
        assert centre == CENTRE, f"{where}: centre must read {CENTRE!r}, got {centre!r}"
        links = re.findall(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', regions["centre"], re.S)
        assert [(h, " ".join(t.split())) for h, t in links] == [
            (_EXTERNAL_NAV[0], "www.auscope.org.au")], (
            f"{where}: the acknowledgement carries exactly one link, the AuScope address under its "
            f"own URL text, and the rest of the line is prose: {regions['centre']!r}")

        right = regions["right"]
        assert re.fullmatch(
            r'<a class="orglogo" href="' + re.escape(_EXTERNAL_NAV[0]) + r'" ' + re.escape(_NEW_TAB)
            + r'>'
            r'<img src="[^"]*auscope-ncris-white\.png" alt="' + re.escape(LOGO_ALT) + r'"[^>]*></a>',
            right, re.S), (
            f"{where}: the right region is the AuScope-NCRIS lockup, linked where the centre's URL "
            f"text links and carrying {_NEW_TAB}, and nothing else: {right!r}")


def test_the_two_surfaces_agree_on_where_the_footer_points():
    """TARGETS. The MTCAT document is ONE destination reached from two surfaces, so it is compared as
    a root-relative path; so is the lockup file. FAILS if a surface retargets a region's link, if the
    SPA's relative form stops resolving to the engine's absolute one, or if the two surfaces stop
    naming the same committed image."""
    idx, eng = _index_regions(), _engine_regions()

    # index.html's own href sits on the <a class="apilink"> tag, which _index_regions strips.
    idx_left = re.findall(r'<a class="apilink" href="([^"]+)"', _index_footer())
    assert idx_left == ["data/mtcat.json"], (
        f"index.html's MTCAT link must stay at data/mtcat.json, got {idx_left}")
    assert "/" + idx_left[0] == MTCAT, (
        f"the SPA's relative MTCAT link must resolve to the engine's {MTCAT}, got {idx_left[0]}")
    assert re.findall(r'href="([^"]+)"', eng["left"]) == [MTCAT], (
        f"the engine footer's MTCAT link must target {MTCAT}")

    for where, region in (("portal/index.html", idx["right"]),
                          ("engine/extract/_pages.py", eng["right"])):
        srcs = [_root_relative(s, where) for s in re.findall(r'<img [^>]*src="([^"]+)"', region)]
        assert srcs == [LOGO_SRC], f"{where}: the lockup must resolve to {LOGO_SRC}, got {srcs}"
        assert re.findall(r'<a[^>]*href="([^"]+)"', region) == [_EXTERNAL_NAV[0]], (
            f"{where}: the lockup links where the centre's URL text links: {region!r}")


def test_the_committed_lockup_is_the_brand_kit_file_unaltered():
    """THE LOCKUP IS A COMMITTED FILE. The footer promises an image on every page of both surfaces,
    and that image is a third-party trademark asset: it ships as its rights holder published it or it is not
    the mark at all.

    FAILS if the file is missing, if its bytes change (a resize, a re-encode, a recolour, a
    metadata strip), or if its raster stops being the recorded 1919x325 8-bit RGBA. Display size is
    CSS, which is why a smaller committed file is a defect here rather than an optimisation."""
    path = ROOT / LOGO_SRC.lstrip("/")
    assert path.is_file(), f"the footer promises {LOGO_SRC}, which is not committed"
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


# --------------------------------------------------------------- every page the portal ships
#
# The SPA was held against the engine above; these hold the five sibling documents against the SPA.
# They were the drift the rule did not reach: each carried its own footer, and the "About this
# build" the old footer pointed at landed on one of them.
#
# 404.html was once the ONE difference, because About this build could only be a link there: Caddy
# rewrites any unmatched path to that document, so every link it carries is root-absolute, and it
# loads no script and so could never fill a version chip. With Releases and About this build out of
# the footer, that difference is gone and all six documents carry the identical three regions; the
# root-absolute spelling of the left link is the only thing left that distinguishes it, and
# _root_relative resolves it away.
_PORTAL_PAGES = ("404.html", "about.html", "add-survey.html", "brand.html", "index.html",
                 "releases.html")


def _portal_pages():
    return sorted(p.name for p in ROOT.glob("*.html"))


class _FooterRegions(HTMLParser):
    """The footer's TOP-LEVEL children, each with the html it encloses.

    Depth-tracked rather than regex-split because a region may nest markup of its own, whose first
    close tag ends a class-scoped pattern early and would let a missing region pass as present."""

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


def _footer_children(name):
    """[(tag, attrs, inner)] for the one <footer> in a portal page, comments stripped first so
    prose inside the footer cannot satisfy a pin."""
    text = (ROOT / name).read_text(encoding="utf-8")
    assert text.count("<footer") == 1, f"{name}: expected exactly one footer, found {text.count('<footer')}"
    foot = "<footer>" + text.split("<footer>", 1)[1].split("</footer>", 1)[0] + "</footer>"
    foot = re.sub(r"<!--.*?-->", "", foot, flags=re.S)
    parser = _FooterRegions()
    parser.raw = foot
    parser.feed(foot)
    return parser.children


def _root_relative(href, name):
    """A footer target as the ONE path it names. The pages served from the portal root write their
    targets relative; 404.html is served for any address at any depth and writes them absolute.

    The single allow-listed external navigation address passes through unchanged, so a caller can
    compare it against _EXTERNAL_NAV; every OTHER external form is refused here, which is what keeps
    this one rule from becoming a general licence to point the footer off-site."""
    if href in _EXTERNAL_NAV:
        return href
    if href.startswith("/"):
        return href
    assert not href.startswith(("http://", "https://", "//")), (
        f"{name}: a footer target must stay on this site, or be the one allow-listed AuScope "
        f"navigation address {_EXTERNAL_NAV[0]!r}; got {href!r}")
    return "/" + href


def _no_external_fetch(where, footer_html, sheet):
    """THE ONE EXTERNAL TARGET, second half. A footer may NAVIGATE to the allow-listed AuScope
    address; nothing in it, or in the rules that style it, may FETCH from any host but this site.

    FAILS on an external src, an external stylesheet link, an @import or a url() naming a host. The
    rule introduced one anchor and no runtime dependency, and this is what keeps it that way."""
    for src in re.findall(r'<img [^>]*src="([^"]+)"', footer_html):
        assert not src.startswith(("http://", "https://", "//", "data:")), (
            f"{where}: a footer image must be served from this site, got {src!r}")
    assert "<link" not in footer_html and "@import" not in footer_html, (
        f"{where}: a footer fetches no stylesheet of its own: {footer_html!r}")
    for url in re.findall(r"url\(\s*['\"]?([^'\")]+)", sheet):
        assert not url.startswith(("http://", "https://", "//")), (
            f"{where}: a footer rule must not fetch from an external host, got {url!r}")
    assert "@import" not in sheet, f"{where}: the footer's rules must not @import"


def test_every_portal_page_carries_the_one_footer():
    """PARITY ACROSS THE PORTAL. Every HTML document the portal ships carries the same three
    regions, in order, with the same strings, the same targets and U+00B7 between them.

    FAILS if a page carries fewer or more than three regions, if a region's string drifts, if the
    acknowledgement's one link moves, if the lockup is missing or retargeted, if a separator stops
    being the middle dot, or if a new page is added to portal/ without this pin reaching it."""
    assert _portal_pages() == sorted(_PORTAL_PAGES), (
        f"the portal ships {_portal_pages()}, which is not the set this pin enumerates; a new page "
        f"carries the one footer too, so add it to _PORTAL_PAGES")

    for name in _portal_pages():
        kids = _footer_children(name)
        assert len(kids) == 3, (
            f"{name}: the footer is exactly three regions, found {len(kids)}: "
            f"{[(t, a.get('class')) for t, a, _ in kids]}")
        (ltag, lattrs, linner), (ctag, cattrs, cinner), (rtag, rattrs, rinner) = kids

        # LEFT. One zone, carrying one machine-readable link to the whole catalogue, with the
        # leaves-this-page arrow. The zone is an element of its own on every surface: the equal
        # zero basis that page-centres the acknowledgement is a rule on a BOX, and a bare anchor
        # gave the portal no box to put it on where the generated tier had one.
        assert ltag == "div" and lattrs.get("class") == _ZONE_CLASSES["left"], (
            f"{name}: the first region is the MTCAT link's zone, got <{ltag} "
            f"class={lattrs.get('class')!r}>")
        link = re.fullmatch(r'<a class="apilink" href="([^"]+)" title="[^"]*">(.*)</a>',
                            linner.strip(), re.S)
        assert link, f"{name}: the left zone holds the MTCAT link and nothing else: {linner!r}"
        label = " ".join(_entity(link.group(2)).split())
        assert label == f"{LEFT_LABEL} ↗", (
            f"{name}: the left region must read {LEFT_LABEL!r} with the leaves-this-page arrow, "
            f"got {label!r}")
        assert _root_relative(link.group(1), name) == MTCAT, (
            f"{name}: the left link must resolve to {MTCAT}, got {link.group(1)!r}")

        # CENTRE. The acknowledgement line, carrying exactly one link: the AuScope address
        # under its own URL text. The rest is prose and stays prose.
        assert ctag == "div" and cattrs.get("class") == _ZONE_CLASSES["centre"], (
            f"{name}: the second region is the acknowledgement, got <{ctag} "
            f"class={cattrs.get('class')!r}>")
        centre = " ".join(_entity(re.sub(r"<[^>]+>", "", cinner)).split())
        assert centre == CENTRE, f"{name}: centre must read {CENTRE!r}, got {centre!r}"
        clinks = re.findall(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', cinner, re.S)
        assert [(h, " ".join(t.split())) for h, t in clinks] == [
            (_EXTERNAL_NAV[0], "www.auscope.org.au")], (
            f"{name}: the acknowledgement carries exactly one link, the AuScope address under its "
            f"own URL text: {cinner!r}")

        # RIGHT. The AuScope-NCRIS lockup, linked where the centre's URL text links.
        assert rtag == "div" and rattrs.get("class") == _ZONE_CLASSES["right"], (
            f"{name}: the third region is the AuScope-NCRIS lockup, got <{rtag} "
            f"class={rattrs.get('class')!r}>")
        assert re.fullmatch(
            r'<a class="orglogo" href="' + re.escape(_EXTERNAL_NAV[0]) + r'" ' + re.escape(_NEW_TAB)
            + r'>'
            r'<img src="[^"]*auscope-ncris-white\.png" alt="' + re.escape(LOGO_ALT) + r'"[^>]*></a>',
            rinner.strip(), re.S), (
            f"{name}: the right region is the lockup anchor and nothing else: {rinner!r}")
        img_src = re.findall(r'<img [^>]*src="([^"]+)"', rinner)
        assert [_root_relative(s, name) for s in img_src] == [LOGO_SRC], (
            f"{name}: the lockup must resolve to {LOGO_SRC}, got {img_src}")


def test_no_footer_reaches_an_external_host_for_anything_it_fetches():
    """THE ONE EXTERNAL TARGET, held on every surface. See _no_external_fetch."""
    for name in _portal_pages():
        text = (ROOT / name).read_text(encoding="utf-8")
        foot = text.split("<footer>", 1)[1].split("</footer>", 1)[0]
        sheet = "".join(re.findall(r"(?ms)^\s*footer[^{]*\{[^}]*\}", text))
        _no_external_fetch(name, foot, sheet)
    _no_external_fetch("engine/extract/_pages.py", _engine_footer(),
                       "".join(re.findall(r"(?ms)^\s*\.(?:fzone|fleft|fcenter|fright|orglogo)"
                                          r"[^{]*\{[^}]*\}", _pages_text())))


def test_releases_and_about_this_build_have_left_every_footer():
    """THE RETIRED CONTROLS STAY RETIRED. The rule took both out of the footer on every surface;
    about.html carries the running build's identity and the route to the releases page in its own
    body instead, which test_about_uniform_chrome.py pins.

    FAILS if either control, or the disclosure popover's markup or CSS, comes back to a footer on
    any surface. Swept from the whole document for the popover's class, because a rule left behind
    styles an element someone will re-add."""
    for name in _portal_pages():
        text = (ROOT / name).read_text(encoding="utf-8")
        foot = re.sub(r"<!--.*?-->", "", text.split("<footer>", 1)[1].split("</footer>", 1)[0],
                      flags=re.S)
        for gone in RETIRED:
            assert gone not in foot, f"{name}: {gone!r} left the footer and must not come back"
        assert "aboutbuild" not in text, (
            f"{name}: the About-this-build popover and its CSS are retired; a rule left behind "
            f"styles an element someone will re-add")
    eng = _engine_footer()
    for gone in RETIRED:
        assert gone not in eng, f"engine/extract/_pages.py: {gone!r} left the footer"
    assert "aboutbuild" not in _pages_text(), "engine/extract/_pages.py: the popover class is retired"


def test_every_footer_is_a_wrapping_flex_row_whose_side_zones_take_equal_zero_basis():
    """GEOMETRY, on every surface at once. The centre is the region that yields: the left link and
    the right lockup are each a fixed-width object that reads badly broken, and the acknowledgement
    line is prose that does not.

    THE SIDE ZONES TAKE EQUAL ZERO BASIS, which is what page-centres the acknowledgement. Zones
    that size to their own content leave the centre centred in the LEFTOVER space: measured in
    Chrome at 2560px before this, the sentence's midpoint sat 245.55px left of the viewport's on
    the portal and 274.66px left of it on the generated tier, because the machine-readable link is
    285.98px wide and the lockup 165.33px. flex:1 1 0 on both sides makes them the same width
    whatever they hold, so the centre sits on the page's axis; min-width:0 lets a side zone go
    under its own content rather than force a wrap, and the two states below one row are what stop
    that overflow reaching the next zone (measured: no zone's ink overlaps another's at any width).

    There are two states below one row and each is pinned. Below the width the three regions need,
    the centre takes a row of its own UNDER the left link and the lockup, where it spans the footer
    and is centred on its axis; below the width those two need, every region takes a row and aligns
    left, which is the 375px stack.

    FAILS if a footer stops being a wrapping flex row or stops establishing the query container its
    own rules ask about, if either side zone stops taking the zero basis, if the centre stops being
    content-sized or stops centring its text, if either state below one row goes, if one stops
    following the rules it overrides, or if a viewport rule comes back in their place."""
    surfaces = [(name, (ROOT / name).read_text(encoding="utf-8")) for name in _portal_pages()]
    surfaces.append(("engine/extract/_pages.py", _pages_text()))
    for where, text in surfaces:
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
        assert "text-align:right" in rules[".fright"], (
            f"{where}: the lockup sits against the right edge of its zone: {rules['.fright']!r}")
        assert "flex:0 1 auto" in rules[".fcenter"], (
            f"{where}: the centre is content-sized between the two equal side zones; growing it "
            f"too would take a third of the free space and push the axis: {rules['.fcenter']!r}")
        for decl in ("min-width:0", "text-align:center"):
            assert decl in rules[".fcenter"], (
                f"{where}: the centre zone must declare {decl}: {rules['.fcenter']!r}")

        centre_row, stacked = text.find(_CENTRE_ROW_RULE), text.find(_STACK_RULE)
        assert centre_row > 0 and stacked > centre_row, (
            f"{where}: every region must take a full row and align left once the left link and the "
            f"lockup cannot share one, in a rule that FOLLOWS the centre's own-row rule: the two "
            f"tie on specificity, so placed above it the stack would not restore the 375px order")
        for zone in (".fleft{", ".fcenter{", ".fright{"):
            assert 0 < text.index(zone) < centre_row, (
                f"{where}: both states below one row must follow the zone rules they override, {zone}"
                f" included; the selectors tie on specificity and source order alone decides")
        for retired in ("@media(max-width:760px){.fzone", "@media (max-width:760px){.fzone",
                        "footer .apilink{", "footer .foot-main{", "footer .foot-right{"):
            assert retired not in text, (
                f"{where}: the footer's width is not the viewport's on any surface and its zones "
                f"are named the same everywhere: found the retired {retired!r}")


def test_the_lockup_is_sized_in_css_and_never_outgrows_its_zone():
    """THE LOCKUP NEVER OUTGROWS ITS ZONE. The committed file is 1919px wide because it is the brand
    kit's own raster; what a reader sees is a 30.8px-high mark, and the width follows from the height.

    FAILS if the height rule goes (the page would then paint the file at full size), if the width
    stops following it, or if the max-width cap is lost. The cap is what holds the mark inside the
    stacked 375px row whatever the committed file's own width becomes, and object-fit keeps its
    proportions in the state where the cap bites."""
    for where, text in ([(name, (ROOT / name).read_text(encoding="utf-8"))
                         for name in _portal_pages()]
                        + [("engine/extract/_pages.py", _pages_text())]):
        rule = _rule_set(where, text)[".orglogo img"]
        for decl in (LOCKUP_HEIGHT, "width:auto", "max-width:100%", "object-fit:contain"):
            assert decl in rule, f"{where}: the lockup rule must declare {decl}: {rule!r}"


# THE CONSTANT FOOTER and THE BOLD CENTRE, held on every surface at once.
#
# The footer is always at the bottom of the VIEWPORT, not at the end of the scroll: content passes
# beneath it and the last line of that content is never left under it, because a sticky box keeps
# its own place in flow and simply comes to rest there. That needs three things together and each is
# pinned below, because any one of them alone is a footer that floats mid-page on a short document:
# a page-height column, a growing block above the footer, and the sticky rule itself.
#
# WHY STICKY AND NOT FIXED: a fixed footer leaves no box in flow, so every page would owe it a
# body padding-bottom equal to a height that changes with the wrap state and with the viewport. The
# sticky box reserves exactly its own height, so the guarantee holds without a second number to keep
# in step with the first.
#
# THE RETURN TO FLOW IS A MEASUREMENT. Measured in Chrome across all eleven surfaces, the three
# regions stop sharing rows at a viewport of 540px on the static tier and 556px to 560px on the
# portal (the container queries ask 500px and 520px of FOOTER width, and the surfaces reach that at
# different viewports because their columns and paddings differ). At 560px and below at least one
# surface is a three-row footer of 113px to 136px, which on a phone would sit over most of the
# screen; above it every surface is at most two rows. So 560px is where the pin puts the switch:
# the constant footer holds above it, and below it the footer is an ordinary block at the end of the
# document.
_FLOW_BELOW = 560
_STICKY = ("position:sticky", "bottom:0")

# The block that GROWS to fill the column. The footer is a SIBLING of main on every surface, so main
# is that block everywhere: it takes the free space and the footer lands on the viewport's bottom
# edge on a document shorter than the screen. main also states a width, because a flex item with an
# auto width and auto side margins shrinks to its content instead of stretching to the reading
# measure.
_GROWS = {
    "404.html": ("main", "flex:1 0 auto"),
    "about.html": ("main", "flex:1 0 auto"),
    "add-survey.html": ("main", "flex:1 0 auto"),
    "brand.html": ("main", "flex:1 0 auto"),
    "index.html": ("main", "flex:1"),
    "releases.html": ("main", "flex:1 0 auto"),
}
_ENGINE_GROWS = ("main", "flex:1 0 auto")

# The opaque ground each surface paints under the footer. A sticky footer with a transparent
# background shows the content sliding under it; these are each page's own body colour, so the
# footer reads as the page's own bottom edge rather than as a panel over it.
_INK = {
    "404.html": "background:#11182D",
    "about.html": "background:var(--ink)",
    "add-survey.html": "background:var(--ink)",
    "brand.html": "background:var(--ink)",
    "index.html": "background:var(--ink)",
    "releases.html": "background:var(--ink)",
}
_ENGINE_INK = "background:#11182D"

# The centre line's weight, as ONE declaration on the zone rather than a span around the sentence:
# the whole line is bold, the anchor included, and a single declaration is what lets
# these pins hold it as one fact. 700 is the sans family's bold, the weight the word names; the
# header wordmark's 800 is a display weight for a 22px mark and would smear at 12.5px.
_CENTRE_WEIGHT = "font-weight:700"

# The lockup's rendered height, as ONE declaration in the master rule. The committed raster is
# 1919x325, so the width follows from the height. The brief asked for it 10 percent taller: it stood
# 28.00px (measured, matching the declaration) and now stands 30.80px, which carries the width from
# 165.33px to 181.86px. The number is written exactly, not rounded: a rounded 31px is a different
# ratio, and the ratio is what the rule fixes.
LOCKUP_HEIGHT = "height:30.8px"

_FOOTER_RULE = r"(?m)^\s*footer\{([^}]*)\}"
_FLOW_RULE = f"@media (max-width:{_FLOW_BELOW}px){{footer{{position:static}}}}"

# ---------------------------------------------------------------- the footer's ONE rule set
#
# THE OWN-ROW BREAKPOINT IS A MEASUREMENT, and it moved with the equal zero basis. Two side zones of
# the same width need twice the WIDER one, not one of each, so the three regions want more footer
# than they did: measured in Chrome with the specified strings at the specified weight, the widest surface's
# centre is 813.22px and its machine-readable link 285.98px, so one row needs
# 813.22 + 2x285.98 + two 18px gaps + two 18px paddings = 1457.18px of footer. A container query
# asks the CONTENT box, which is 36px narrower, so the rule fires at or below 1421px and the three
# regions share a row from a footer of 1458px up. Verified at 1456/1457 (two rows) and 1458/1459
# (one row, no zone over its box) on about.html, a survey page and 404.html.
#
# THE STACK BREAKPOINT DID NOT MOVE. Below 520px of CONTENT (556px of footer) every region takes a
# row and aligns left. Between 557px and 643px the left link is wider than its equal-basis box and
# overflows it, which is why min-width:0 is stated: measured across those widths the overflow runs
# into empty space and no zone's ink ever reaches another's, so the row does not have to break
# earlier than the reading order wants it to.
_CENTRE_ROW_RULE = "@container (max-width:1421px){.fcenter{order:1;flex:1 1 100%}}"
_STACK_RULE = "@container (max-width:520px){.fzone{order:0;flex:1 1 100%;text-align:left}}"

# The seven selectors that ARE the footer's rule set, longest first so the alternation cannot take
# the short form of a longer selector.
_SET_RE = re.compile(r"(?m)(?:^[ \t]*|(?<=\}))"
                     r"(footer a|footer|\.orglogo img|\.orglogo|\.fleft|\.fcenter|\.fright)"
                     r"\{([^}]*)\}")
_RULE_SET = ("footer", "footer a", ".fleft", ".fcenter", ".fright", ".orglogo", ".orglogo img")

# THE TOKEN LAYER, RESOLVED. Five documents write these colours as var() and two cannot: 404.html is
# served by Caddy for any unmatched path at any depth and carries no token layer, and the generated
# tier's shell writes literals throughout. Comparing the rule sets with the tokens resolved is what
# lets "identical everywhere" be asserted across all seven rather than across the five that happen
# to share a spelling. The values are index.html's own :root, and a drift in them fails here.
_TOKEN_VALUES = {"--ink": "#11182D", "--line": "#2B3557", "--muted": "#8FA3B0",
                 "--copper": "#EF7256"}


def _resolved(rule):
    for name, value in _TOKEN_VALUES.items():
        rule = rule.replace(f"var({name})", value)
    assert "var(--" not in rule, (
        f"the footer rule set may only reach for the four colour tokens this pin resolves; "
        f"an unresolved one cannot be compared with the two surfaces that have no token layer: "
        f"{rule!r}")
    return rule


def _rule_set(where, text):
    """{selector: declarations} for the footer's whole rule set, tokens resolved, queries removed.

    The two @container states and the return-to-flow rule restate these selectors, so the base
    rules are read with the query blocks stripped and the three queries are then required, once
    each, from the full text."""
    out = {}
    for sel, body in _SET_RE.findall(_outside_queries(text)):
        assert sel not in out, (
            f"{where}: {sel} is declared twice; a second declaration overrides the pinned rule at "
            f"equal specificity and is exactly how the surfaces drifted apart")
        out[sel] = _resolved(" ".join(body.split()))
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


def test_every_surface_pins_the_footer_to_the_viewport_bottom():
    """THE CONSTANT FOOTER. FAILS if any surface's footer stops being sticky to the bottom edge, if
    it loses the opaque ground that keeps scrolling content from showing through it, or if it loses
    the stacking order that keeps a frozen table column from painting over it."""
    surfaces = [(name, (ROOT / name).read_text(encoding="utf-8"), _INK[name])
                for name in _portal_pages()]
    surfaces.append(("engine/extract/_pages.py", _pages_text(), _ENGINE_INK))
    for where, text, ink in surfaces:
        rule = _footer_rule(where, text)
        for decl in _STICKY:
            assert decl in rule, (
                f"{where}: the footer must declare {decl}, or it only appears at the end of the "
                f"scroll instead of staying on screen: {rule!r}")
        assert ink in rule, (
            f"{where}: a sticky footer needs the page's own opaque ground under it, or the content "
            f"passing beneath shows through the text: expected {ink!r} in {rule!r}")
        assert re.search(r"z-index:[1-9]", rule), (
            f"{where}: the footer must name its own stacking order; a table's frozen first column "
            f"declares z-index:2 and would otherwise paint over it: {rule!r}")


def test_every_surface_makes_the_page_a_full_height_column():
    """THE COLUMN THE STICKY FOOTER NEEDS. A sticky box is never pushed DOWN from where it sits in
    flow, so on a document shorter than the screen the footer would sit halfway up the page unless
    the page itself is a viewport-tall column with a growing block above the footer.

    FAILS if any surface stops being that column, or if the block above the footer stops growing:
    either one alone leaves the Collections hub's footer floating mid-page."""
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
    contentinfo landmark nor wide enough to hold the bold acknowledgement on one line: measured, the
    sentence wants 813px and about.html's column is 780px, so a footer set in the column is two rows
    where the Map's is one.

    FAILS if any page moves its footer back inside main, which is where the two surfaces last
    diverged on height."""
    for name in _portal_pages():
        text = (ROOT / name).read_text(encoding="utf-8")
        body = text.split("<body", 1)[1]
        assert body.index("</main>") < body.index("<footer"), (
            f"{name}: the footer must follow </main>, not sit inside the reading column")
    emitter = _pages_text()
    shell = emitter.split("def _shell(", 1)[1]
    assert shell.index('"</main>') < shell.index("_site_footer(build)"), (
        "engine/extract/_pages.py: _shell must close main before it writes the footer")


def test_every_surface_returns_the_footer_to_flow_below_the_measured_width():
    """THE NARROW-WIDTH RETURN TO FLOW, on both sides of the measured breakpoint. Below it the
    footer is three rows on at least one surface, which on a phone would cover most of the screen,
    so it goes back to being an ordinary block at the end of the document.

    FAILS if a surface loses the rule, if the breakpoint drifts off the measured width, or if the
    rule is placed where source order lets the sticky rule win it back (the two tie on
    specificity)."""
    surfaces = [(name, (ROOT / name).read_text(encoding="utf-8")) for name in _portal_pages()]
    surfaces.append(("engine/extract/_pages.py", _pages_text()))
    for where, text in surfaces:
        flow = _FLOW_RULE
        at = text.find(flow)
        assert at > 0, f"{where}: expected the return-to-flow rule {flow!r}"
        assert text.count(flow) == 1, f"{where}: the return-to-flow rule must be declared once"
        assert at > re.search(_FOOTER_RULE, text).start(), (
            f"{where}: the return-to-flow rule must FOLLOW the footer's own rule, or the sticky "
            f"declaration wins at equal specificity and the narrow-width footer stays pinned")


def test_the_centre_line_is_bold_on_every_surface():
    """THE BOLD CENTRE, as ONE declaration on the zone. The whole acknowledgement is
    bold, the anchor included; a span around part of the sentence would put the fact in the markup
    of six documents and the engine's emitter instead of in one rule per surface.

    FAILS if any surface's centre zone loses the weight, if it is written somewhere other than the
    zone rule, or if the anchor is given a weight of its own."""
    surfaces = [(name, (ROOT / name).read_text(encoding="utf-8")) for name in _portal_pages()]
    surfaces.append(("engine/extract/_pages.py", _pages_text()))
    for where, text in surfaces:
        rules = _rule_set(where, text)
        assert _CENTRE_WEIGHT in rules[".fcenter"], (
            f"{where}: the centre zone must declare {_CENTRE_WEIGHT}: {rules['.fcenter']!r}")
        for sibling in (s for s in _RULE_SET if s != ".fcenter"):
            assert "font-weight" not in rules[sibling], (
                f"{where}: the weight belongs to the centre zone alone; a second declaration "
                f"in {sibling!r} is a second place for the surfaces to drift: "
                f"{rules[sibling]!r}")


def _footer_html(name):
    """A portal page's footer with comments stripped, so prose inside it cannot satisfy a pin.

    Nothing else is removed: every surface's footer is compared as the whole of what it carries."""
    text = (ROOT / name).read_text(encoding="utf-8")
    foot = text.split("<footer>", 1)[1].split("</footer>", 1)[0]
    return re.sub(r"<!--.*?-->", "", foot, flags=re.S)


def _anchors(where, footer_html):
    """(href, whole opening tag) for every anchor in a footer, in source order.

    The opening tag is carried whole rather than parsed into attributes so a caller can assert the
    target/rel pair as the one literal string it must be on every surface."""
    out = []
    for tag in re.findall(r"<a\b[^>]*>", footer_html):
        href = re.search(r'href="([^"]*)"', tag)
        assert href, f"{where}: a footer anchor carries no href: {tag!r}"
        out.append((href.group(1), tag))
    assert out, f"{where}: the footer carries no anchor at all"
    return out


def test_the_two_auscope_anchors_open_in_a_new_tab_on_every_surface():
    """THE TWO EXTERNAL ANCHORS LEAVE THE TAB, and hand the opened page nothing. Both footer links
    to the AuScope address, the centre sentence's URL text and the lockup, carry
    target="_blank" rel="noopener noreferrer" in that one spelling on all six documents the portal
    ships and in the footer the engine emits.

    WHY rel IS NOT OPTIONAL BESIDE target: a document opened with target="_blank" is given
    window.opener unless rel says otherwise, and can navigate the tab it came from; noreferrer also
    keeps the reader's path through the catalogue off a third party's logs.

    FAILS if a surface loses either attribute, spells the pair differently, adds the target to only
    one of the two anchors, or gives an IN-SITE footer link a target of its own: the machine-readable
    record is this site's own document and opening it in a new tab would be a second behaviour for a
    reader to learn. Non-vacuous: at the tip before this pin, neither anchor carried a target on any
    of the seven surfaces and the lockup's rel was noopener alone."""
    surfaces = [(name, _footer_html(name)) for name in _portal_pages()]
    surfaces.append(("engine/extract/_pages.py", _engine_footer()))
    for where, foot in surfaces:
        anchors = _anchors(where, foot)
        external = [tag for href, tag in anchors if href in _EXTERNAL_NAV]
        assert len(external) == 2, (
            f"{where}: the footer carries exactly two anchors to {_EXTERNAL_NAV[0]}, the centre "
            f"sentence's URL text and the lockup; found {len(external)}: {external!r}")
        for tag in external:
            assert _NEW_TAB in tag, (
                f"{where}: an anchor that leaves the site opens in a new tab and hands it no "
                f"opener; expected {_NEW_TAB!r} in {tag!r}")
        for href, tag in anchors:
            if href in _EXTERNAL_NAV:
                continue
            assert "target=" not in tag, (
                f"{where}: an in-site footer link stays in this tab, got {tag!r}")


def test_the_token_surfaces_declare_one_footer_rule():
    """ONE FOOTER MEANS ONE RULE, not five rules that happen to agree. A footer whose content is
    pinned character for character but whose box is declared five times drifts in the only dimension
    the content pins cannot see: its height. Measured in Chrome at 1280px before this pin, the six
    documents and the generated tier spread over 4.36px, because about.html and releases.html had
    kept a padding and a margin of their own (16px 20px 0 and margin-top:30px) where the other three
    carried the SPA's 7px 18px.

    404.html IS THE ONE SURFACE OUTSIDE THIS COMPARISON, and its exclusion is asserted rather than
    assumed. Caddy serves it for any unmatched path at any depth, so it carries no token layer and
    writes its footer in literal colours; there is no character-for-character form of the VAR
    SPELLING it could share. The pin below reaches it, and the generated tier, by resolving the
    tokens to the colours they carry.

    FAILS if any token surface's footer rule drifts by a single character, or if a second document
    leaves the token layer."""
    shared, standalone = {}, []
    for name in _portal_pages():
        rule = _footer_rule(name, (ROOT / name).read_text(encoding="utf-8"))
        if "var(--" in rule:
            shared[name] = rule
        else:
            standalone.append(name)
    assert standalone == ["404.html"], (
        f"404.html is the one surface that carries no token layer; these do not either: "
        f"{standalone}")
    assert len(shared) == 5, f"expected five token surfaces, found {sorted(shared)}"
    assert len(set(shared.values())) == 1, (
        "the token surfaces must declare the IDENTICAL footer rule; found "
        + "\n".join(f"  {n}: {r}" for n, r in sorted(shared.items())))


def test_every_surface_declares_the_one_footer_rule_set():
    """ONE FOOTER MEANS ONE RULE SET, on ALL SEVEN surfaces, not one rule on the five that share a
    spelling. portal/index.html is the master; every other document and the engine's _CSS carry the
    same seven rules, character for character once the four colour tokens are resolved, plus the
    same two @container states and the same return-to-flow rule.

    THIS IS THE PIN THE REVIEW ASKED FOR. The rule above could only see the five token
    surfaces, so 404.html and the generated tier kept a rule set of their own: rem units, a
    12.8px face, .7rem of top padding and NO bottom padding, and a 2.2rem margin above. That is
    what the Map, the hubs and About were being compared across when the footers were reported as
    sitting and aligning differently. Measured in Chrome at 2560px before this: footer height
    48.75px on the portal against 46.02px on the generated tier, with the text baseline 4.69px
    apart; after it, height, baseline and midpoint agree to 0.00px at 2560, 1280 and 1024.

    THE SEPARATION ABOVE THE FOOTER BELONGS TO THE COLUMN, not to the footer. The generated tier
    and 404.html carried it as the footer's own margin-top, which the SPA cannot have (its body
    does not scroll, so a margin there takes height from the map). It moves to main's bottom
    padding on those two surfaces, where the portal's own content pages already keep it.

    FAILS if any surface's footer rule set drifts by a character, if a surface declares one of the
    seven rules twice, if a rule goes missing, or if either query or the flow rule drifts."""
    surfaces = [(name, (ROOT / name).read_text(encoding="utf-8")) for name in _portal_pages()]
    surfaces.append(("engine/extract/_pages.py", _pages_text()))
    assert len(surfaces) == 7, f"seven surfaces wear this footer, found {len(surfaces)}"
    master = _rule_set("portal/index.html", _index_text())
    for where, text in surfaces:
        got = _rule_set(where, text)
        for sel in _RULE_SET:
            assert got[sel] == master[sel], (
                f"{where}: {sel} must be portal/index.html's rule, character for character once "
                f"the token layer is resolved.\n  master: {master[sel]!r}\n  {where}: {got[sel]!r}")


def test_no_footer_on_any_surface_carries_a_map_credit():
    """NO FOOTER CREDITS A BASEMAP, on any of the seven surfaces.

    THE OBLIGATION IS NOT WAIVED, it is met where the map is. The corner control is back, collapsed
    behind an (i), reading each tile layer's own attribution, which is what makes the credit follow
    whichever provider is actually drawing the map: map.js keeps a CARTO fallback for the case where
    the pmtiles files are absent or the renderer fails to load, and a fixed footer line naming
    Protomaps would credit the wrong source on that branch. portal/tests/test_map_attribution.py
    holds that half.

    THE FOOTER IS ONE BOX ON SEVEN SURFACES, which is the other half of the reason. A line only the
    SPA carried made it a different box there: measured in Chrome with the credit in place, the
    SPA's footer stood 90.80px against 74.30px on every other surface at 1280 and 1024, and its
    acknowledgement's baseline sat 21.64px from the footer's top against 29.89px elsewhere at 2560.

    HELD BY THE LINKS AS WELL AS THE CLASS: a surface could drop the class name and still carry the
    copyright href, and still be making the claim. FAILS if any portal document or the engine's
    emitter reintroduces either.

    Non-vacuous: at the tip before this pin, portal/index.html carried all three marks."""
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


def test_the_centre_zone_holds_the_same_markup_on_every_surface():
    """ONE FOOTER MEANS ONE BOX, and a box is its rules AND its contents. The rule set is held
    identical two pins above; this holds the acknowledgement's own markup identical, which is the
    half the SPA's basemap credit broke while every other pin stayed green.

    WHY THIS IS THE HEIGHT AND BASELINE PIN. Height and baseline are browser measurements and no
    module here can take one. The centre zone is what sets both: it is the tallest zone below the
    one-row breakpoint, it is the zone whose first line the baseline is measured from, and it is
    where a second line would go. With the rule set identical and this markup identical, the seven
    footers are the same box by construction and a measurement confirms rather than guarantees it.
    Measured in Chrome with the credit in place, the SPA stood 90.80px against 74.30px on every
    other surface at 1280 and 1024, with the baseline 21.64px from the footer's top against
    29.89px; after this pin the spread is under 1px at 2560, 1280 and 1024.

    THE THREE SPELLINGS ARE RESOLVED FIRST: the separator is written literally on four documents,
    as &middot; on two and as a numeric reference by the engine.

    THE CENTRE ZONE AND NOT ALL THREE. The left zone's link carries class="apilink" and a title on
    the six portal documents and neither on the generated tier, which predates this rule and is
    held as it stands by the two region pins above; the right zone's lockup src is necessarily
    written differently by a page served from the root and a page served from /surveys. Widening
    this pin to those two would restate what they already hold and would fail on a difference that
    has not been settled.

    FAILS if any surface adds, drops or reorders anything inside the acknowledgement: a second
    line, a span, a wrapper, a stray nbsp. Non-vacuous: at the tip before this pin, index.html's
    centre zone carried the basemap credit's <span> and the other six did not."""
    surfaces = [(name, _footer_html(name)) for name in _portal_pages()]
    surfaces.append(("engine/extract/_pages.py", _engine_footer()))
    assert len(surfaces) == 7, f"seven surfaces wear this footer, found {len(surfaces)}"
    master = " ".join(_entity(_regions(_index_footer(), _ZONE_CLASSES)["centre"]).split())
    for where, foot in surfaces:
        got = " ".join(_entity(_regions(foot, _ZONE_CLASSES)["centre"]).split())
        assert got == master, (
            f"{where}: the acknowledgement must hold portal/index.html's markup once the "
            f"separator's spelling is resolved.\n  master: {master!r}\n  {where}: {got!r}")
