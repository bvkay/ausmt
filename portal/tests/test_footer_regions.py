"""One footer, three regions, the same on the SPA, on the five chrome pages and on the static pages
the engine emits.

The two surfaces had drifted into two different footers. The SPA carried the MTCAT link, then one
run-on span holding the copyright, the licence note, Releases and the About-this-build control. The
static pages carried a two-row grid with different wording again ("Machine-readable catalogue",
"an AuScope service", "each download carries its licence") and a per-page-kind left link, so no two
page kinds even agreed with each other. The owner's ruling is one footer: LEFT the machine-readable
catalogue, CENTRE the AuScope acknowledgement with the attribution and the licence note, RIGHT the
AuScope-NCRIS lockup. Releases and About this build leave the footer on every surface; about.html
carries the running build's identity and the route to the releases page in its own body, which is
pinned in test_about_uniform_chrome.py.

WHY THE ENGINE HALF LIVES HERE rather than in engine/tests, and why it reads _pages.py's SOURCE
text: the same two reasons test_header_geometry_parity.py gives. portal-ci runs on portal/** AND on
engine/extract/_pages.py, so an edit to either surface fires this lane, where the engine lane
triggers on engine/** alone and cannot see an index.html edit; and _pages.py cannot simply be
imported (it sibling-imports _au_outline and _stationcheck, which need the engine's own path set
up). The engine lane holds its own half of this in engine/tests/test_index_pages.py, asserted
against real rendered pages; this module is what stops the two surfaces diverging again.

THE SEPARATOR IS U+00B7 on every surface, spelt here as an escape so a mis-decoded read of this
file cannot let a hyphen or a dash through the pin. index.html, about.html and add-survey.html write
the character literally, releases.html, brand.html and 404.html write the named reference and
_pages.py writes the numeric one; all are asserted as the codepoint.

Each assertion states its failure criterion:

  * REGIONS - FAILS if either surface does not carry exactly three footer regions, or if a region
    holds something belonging to another (the licence note in with the acknowledgement's link, the
    lockup outside its own zone).
  * STRINGS - FAILS if either surface's centre line drifts from the owner's wording, or if the
    left link's label stops being the MTCAT one.
  * TARGETS - FAILS if the two surfaces stop agreeing on where a region's links point. The MTCAT
    document is one target expressed twice: the SPA is served from the portal root and writes it
    relative, the static pages are served from /surveys/<slug> and cannot, so the pin holds the
    ROOT-RELATIVE form of both against each other rather than the raw strings.
  * THE ONE EXTERNAL TARGET - FAILS if a footer reaches any external host other than the single
    allow-listed AuScope navigation address, and FAILS in the other direction if a footer FETCHES
    anything from an external host. See _EXTERNAL_NAV below: the ruling adds a navigation href, not
    a runtime dependency, and the two are held apart rather than conflated.
  * THE LOCKUP IS A COMMITTED FILE - FAILS if portal/vendor/auscope-ncris-white.png is missing or
    has been resized, re-encoded or recoloured. A footer image is a promise about a file, and this
    one is a third-party trademark asset that must ship as its owner published it.
  * GEOMETRY - FAILS if either surface stops being a wrapping flex row or stops being a query
    container, if the left link becomes shrinkable (it is then broken mid-phrase at the static
    pages' 840px reading measure, where the three regions do not all fit on one row), if the right
    zone stops growing (on a wrapped row its lockup falls under the left one instead of against the
    right edge), if either state below one row goes and the acknowledgement is left centred in the
    space beside the machine-readable link, or a 375px viewport collides instead of stacking.
  * THE LOCKUP NEVER OUTGROWS ITS ZONE - FAILS if the image loses its max-width cap, which is what
    keeps it inside the stacked 375px row whatever the committed file's own width becomes.
  * PARITY ACROSS THE PORTAL - FAILS if any HTML document the portal ships stops carrying the three
    regions, or drifts on a string, a target or a separator.
  * THE RETIRED CONTROLS STAY RETIRED - FAILS if Releases, About this build or the disclosure
    popover (markup or CSS) comes back to any footer.

BOTH QUERIES ASK THE FOOTER'S OWN WIDTH, not the viewport's. On the static tier main is 840px on an
entity page, 920px on a hub and 1120px above 1180px of viewport, and on the portal the sibling pages
set their footers inside reading columns of 760px to 980px, so no single viewport number describes
"the three regions do not fit" on more than one page kind at a time.

THE OWN-ROW BREAKPOINT IS A MEASUREMENT OF THE CONTENT, not a design constant. Measured in Chrome
with the ruled strings at the ruled weight, the three regions want 1301px of footer on the portal
and 1249px on the static tier; the rules fire just above each, as they did at every shorter number
this footer has carried. The acknowledgement lengthened the centre once when it replaced the bare
copyright line and again when it went bold.

The ruling and every number this module holds it to: AusMT_2026/LANE-CONTRACT-FOOTER-AUSCOPE.md.
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

# The owner's three regions, as the strings a reader sees. The centre and the right are asserted
# character-for-character; the left's label is, and its target is asserted separately because the
# two surfaces necessarily spell the same URL differently.
CENTRE = (f"AusMT is enabled by AuScope {DOT} www.auscope.org.au {DOT} "
          f"© 2026 AuScope and the AusMT contributors {DOT} Data licences vary by survey")
LEFT_LABEL = "Machine-readable record (MTCAT JSON)"
MTCAT = "/data/mtcat.json"

# THE ONE EXTERNAL TARGET. The ruling links the AuScope relationship from the footer, so the centre's
# URL text and the lockup both navigate here. It is an exact allow-list of ONE address and it governs
# NAVIGATION ONLY: _no_external_fetch below holds the other half, that no footer on any surface may
# FETCH a resource (src, a stylesheet link, @import, url()) from a host that is not this site. A CDN
# outage or a compromise of a third-party host can tamper with a fetched byte; it cannot tamper with
# an <a href>, which is why the two are separate rules rather than one host list.
_EXTERNAL_NAV = ("https://www.auscope.org.au",)

# The lockup, as the file the footer promises. Recorded from the AuScope brand kit's own bytes; see
# portal/vendor/README.md, which carries the same four facts beside the file.
LOGO_SRC = "/vendor/auscope-ncris-white.png"
LOGO_ALT = "AuScope and NCRIS"
LOGO_SHA256 = "595a564ece1151d94347331c1521381df987da437aa3080cff47a5280cf818f6"
LOGO_BYTES = 35628
LOGO_PIXELS = (1919, 325)

# What the ruling took OUT of every footer. Held as a negative so the two controls cannot drift back
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
    """index.html's <footer> with HTML comments stripped, so prose inside it cannot satisfy a pin."""
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
    """{region: inner html} for the three zone divs/spans, each required exactly once."""
    out = {}
    for name, cls in classes.items():
        hits = re.findall(r'class="' + re.escape(cls) + r'"[^>]*>(.*?)</(?:div|span)>', footer, re.S)
        assert len(hits) == 1, (
            f"the footer must carry exactly one {name} region (class {cls!r}); found {len(hits)}")
        out[name] = hits[0].strip()
    return out


def _index_regions():
    foot = _index_footer()
    left = re.findall(r'<a class="apilink"[^>]*>(.*?)</a>', foot, re.S)
    assert len(left) == 1, f"index.html's footer must carry exactly one MTCAT link; found {len(left)}"
    zones = _regions(foot, {"centre": "foot-main", "right": "foot-right"})
    return {"left": left[0].strip(), "centre": zones["centre"], "right": zones["right"]}


def _engine_regions():
    foot = _engine_footer()
    return _regions(foot, {"left": "fzone fleft", "centre": "fzone fcenter",
                           "right": "fzone fright"})


def test_both_surfaces_carry_the_same_three_regions_with_the_owners_strings():
    """REGIONS and STRINGS. Non-vacuous in both halves: run against the pre-ruling surfaces, both
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
            r'<a class="orglogo" href="' + re.escape(_EXTERNAL_NAV[0]) + r'" rel="[^"]*noopener[^"]*">'
            r'<img src="[^"]*auscope-ncris-white\.png" alt="' + re.escape(LOGO_ALT) + r'"[^>]*></a>',
            right, re.S), (
            f"{where}: the right region is the AuScope-NCRIS lockup, linked where the centre's URL "
            f"text links and carrying rel=noopener, and nothing else: {right!r}")


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
    and that image is a third-party trademark asset: it ships as its owner published it or it is not
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
# They were the drift the ruling did not reach: each carried its own footer, and the "About this
# build" the old footer pointed at landed on one of them.
#
# 404.html used to be the ONE difference, because About this build could only be a link there: Caddy
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
    this one ruling from becoming a general licence to point the footer off-site."""
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
    ruling introduced one anchor and no runtime dependency, and this is what keeps it that way."""
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
    regions, in order, with the owner's strings, the same targets and U+00B7 between them.

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

        # LEFT. One machine-readable link, the whole catalogue, with the leaves-this-page arrow.
        assert ltag == "a" and "apilink" in lattrs.get("class", "").split(), (
            f"{name}: the first region is the MTCAT link, got <{ltag} class={lattrs.get('class')!r}>")
        label = " ".join(_entity(linner).split())
        assert label == f"{LEFT_LABEL} ↗", (
            f"{name}: the left region must read {LEFT_LABEL!r} with the leaves-this-page arrow, "
            f"got {label!r}")
        assert _root_relative(lattrs.get("href", ""), name) == MTCAT, (
            f"{name}: the left link must resolve to {MTCAT}, got {lattrs.get('href')!r}")

        # CENTRE. The owner's acknowledgement line, carrying exactly one link: the AuScope address
        # under its own URL text. The rest is prose and stays prose.
        assert ctag == "span" and cattrs.get("class") == "foot-main", (
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
        assert rtag == "span" and rattrs.get("class") == "foot-right", (
            f"{name}: the third region is the AuScope-NCRIS lockup, got <{rtag} "
            f"class={rattrs.get('class')!r}>")
        assert re.fullmatch(
            r'<a class="orglogo" href="' + re.escape(_EXTERNAL_NAV[0]) + r'" rel="[^"]*noopener[^"]*">'
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
    """THE RETIRED CONTROLS STAY RETIRED. The ruling took both out of the footer on every surface;
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


def test_both_footers_are_wrapping_flex_rows_that_give_at_the_centre():
    """GEOMETRY. The centre is the region that yields: the left link and the right lockup are each a
    fixed-width object that reads badly broken, and the acknowledgement line is prose that does not.

    There are two states below one row and each is pinned. Below the width the three regions need,
    the centre takes a row of its own UNDER the left link and the lockup, where it spans the footer
    and is centred on its axis; below the width those two need, every region takes a row and aligns
    left, which is the 375px stack. Measured in Chrome, the state that was missing left the
    acknowledgement 135px off the axis on an entity page at any viewport under 1180px.

    FAILS if either footer stops being a wrapping flex row or stops establishing the query container
    its own rules ask about, if the left link becomes shrinkable, if the right zone stops growing,
    if either state below one row goes, if one stops following the rules it overrides, or if a
    viewport rule comes back in their place."""
    surfaces = (
        ("portal/index.html", _index_text(), r"footer\{([^}]*)\}",
         {"left": r"(?m)^\s*footer \.apilink\{([^}]*)\}",
          "centre": r"(?m)^\s*footer \.foot-main\{([^}]*)\}",
          "right": r"(?m)^\s*footer \.foot-right\{([^}]*)\}"},
         "@container (max-width:1330px){footer .foot-main{order:1;flex:1 1 100%}}",
         "@container (max-width:520px){footer .apilink,footer .foot-main,footer .foot-right"
         "{order:0;flex:1 1 100%;text-align:left}}",
         "@media(max-width:760px){footer .apilink"),
        ("engine/extract/_pages.py", _pages_text(), r"\n  footer\{([^}]*)\}",
         {"left": r"(?m)^\s*\.fleft\{([^}]*)\}",
          "centre": r"(?m)^\s*\.fcenter\{([^}]*)\}",
          "right": r"(?m)^\s*\.fright\{([^}]*)\}"},
         "@container (max-width:1280px){.fcenter{order:1;flex:1 1 100%}}",
         "@container (max-width:500px){.fzone{order:0;flex:1 1 100%;text-align:left}}",
         "@media(max-width:760px){.fzone"),
    )
    for where, text, row_re, zone_res, centre_rule, stack_rule, retired in surfaces:
        # The narrower-width overrides restate these selectors, so the base rules are read with the
        # query blocks removed; the two overrides are then read from the full text.
        base = _outside_queries(text)
        rows = re.findall(row_re, base)
        assert len(rows) == 1, f"{where}: expected exactly one footer rule, found {len(rows)}"
        for decl in ("display:flex", "flex-wrap:wrap"):
            assert decl in rows[0], f"{where}: the footer must declare {decl}: {rows[0]!r}"

        zones = {}
        for name, pattern in zone_res.items():
            hits = re.findall(pattern, base)
            assert len(hits) == 1, (
                f"{where}: expected exactly one {name} zone rule, found {len(hits)} "
                f"(a second declaration would override the pinned geometry at equal specificity)")
            zones[name] = hits[0]
        assert "flex:0 0 auto" in zones["left"], (
            f"{where}: the left link is content-sized and must not shrink, or it is broken "
            f"mid-phrase wherever the three regions do not all fit: {zones['left']!r}")
        assert "flex:1 1 auto" in zones["centre"] and "text-align:center" in zones["centre"], (
            f"{where}: the centre takes the remaining space and centres its text in it, got "
            f"{zones['centre']!r}")
        assert "min-width:0" in zones["centre"], (
            f"{where}: the centre is the region that gives when the row is tight, so it must be "
            f"allowed below its content: {zones['centre']!r}")
        assert "flex:1 0 auto" in zones["right"] and "text-align:right" in zones["right"], (
            f"{where}: the right zone grows, so on a WRAPPED row the lockup still sits against the "
            f"right edge rather than under the left link: {zones['right']!r}")
        for side in ("left", "right"):
            assert "min-width:0" not in zones[side], (
                f"{where}: the {side} zone must NOT shrink under its own content; the row wraps "
                f"instead: {zones[side]!r}")

        assert "container-type:inline-size" in rows[0], (
            f"{where}: the footer must establish the query container its own rules ask about; "
            f"without it neither @container rule can ever match: {rows[0]!r}")

        centre_row = text.find(centre_rule)
        assert centre_row > 0, (
            f"{where}: below the width the three regions need, the centre must take a full row of "
            f"its own, or it is centred in the space left over beside the machine-readable link "
            f"instead of on the footer's axis: expected {centre_rule!r}")
        stacked = text.find(stack_rule)
        assert stacked > centre_row, (
            f"{where}: every region must take a full row and align left once the left link and the "
            f"lockup cannot share one, in a rule that FOLLOWS the centre's own-row rule: the two "
            f"tie on specificity, so placed above it the stack would not restore the 375px order")
        assert re.search(zone_res["right"], text).start() < centre_row, (
            f"{where}: both states below one row must follow the zone rules they override; the "
            f"selectors tie on specificity and source order alone decides")
        assert retired not in text, (
            f"{where}: the footer's width is not the viewport's on either surface, so the rules "
            f"below one row must not go back to asking the viewport: found {retired!r}")


def test_the_lockup_is_sized_in_css_and_never_outgrows_its_zone():
    """THE LOCKUP NEVER OUTGROWS ITS ZONE. The committed file is 1919px wide because it is the brand
    kit's own raster; what a reader sees is a 28px-high mark, and the width follows from the height.

    FAILS if the height rule goes (the page would then paint the file at full size), if the width
    stops following it, or if the max-width cap is lost. The cap is what holds the mark inside the
    stacked 375px row whatever the committed file's own width becomes, and object-fit keeps its
    proportions in the state where the cap bites."""
    for where, text, pattern in (
            ("portal/index.html", _index_text(), r"(?m)^\s*footer \.orglogo img\{([^}]*)\}"),
            ("engine/extract/_pages.py", _pages_text(), r"(?m)^\s*\.orglogo img\{([^}]*)\}")):
        rules = re.findall(pattern, _outside_queries(text))
        assert len(rules) == 1, f"{where}: expected exactly one lockup sizing rule, found {len(rules)}"
        rule = " ".join(rules[0].split())
        for decl in ("height:28px", "width:auto", "max-width:100%", "object-fit:contain"):
            assert decl in rule, f"{where}: the lockup rule must declare {decl}: {rule!r}"


def test_every_portal_page_sizes_the_lockup_the_same_way():
    """PARITY, the CSS half. The six documents each carry their own stylesheet, so a rule added to
    one and forgotten on another is exactly how the footer diverged before. FAILS if any page ships
    the lockup markup without the rule that sizes it."""
    for name in _portal_pages():
        text = (ROOT / name).read_text(encoding="utf-8")
        rules = re.findall(r"(?m)^\s*footer \.orglogo img\{([^}]*)\}", _outside_queries(text))
        assert len(rules) == 1, (
            f"{name}: expected exactly one footer .orglogo img rule, found {len(rules)}")
        rule = " ".join(rules[0].split())
        for decl in ("height:28px", "width:auto", "max-width:100%", "object-fit:contain"):
            assert decl in rule, f"{name}: the lockup rule must declare {decl}: {rule!r}"


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
# the owner ruled the whole line bold, the anchor included, and a single declaration is what lets
# these pins hold it as one fact. 700 is the sans family's bold, the weight the word names; the
# header wordmark's 800 is a display weight for a 22px mark and would smear at 12.5px.
_CENTRE_WEIGHT = "font-weight:700"

_FOOTER_RULE = r"(?m)^\s*footer\{([^}]*)\}"
_PORTAL_FLOW_RULE = f"@media (max-width:{_FLOW_BELOW}px){{footer{{position:static}}}}"
_ENGINE_FLOW_RULE = f"@media(max-width:{_FLOW_BELOW}px){{footer{{position:static}}}}"


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
    surfaces = [(name, (ROOT / name).read_text(encoding="utf-8"), _PORTAL_FLOW_RULE)
                for name in _portal_pages()]
    surfaces.append(("engine/extract/_pages.py", _pages_text(), _ENGINE_FLOW_RULE))
    for where, text, flow in surfaces:
        at = text.find(flow)
        assert at > 0, f"{where}: expected the return-to-flow rule {flow!r}"
        assert text.count(flow) == 1, f"{where}: the return-to-flow rule must be declared once"
        assert at > re.search(_FOOTER_RULE, text).start(), (
            f"{where}: the return-to-flow rule must FOLLOW the footer's own rule, or the sticky "
            f"declaration wins at equal specificity and the narrow-width footer stays pinned")


def test_the_centre_line_is_bold_on_every_surface():
    """THE BOLD CENTRE, as ONE declaration on the zone. The owner ruled the whole acknowledgement
    bold, the anchor included; a span around part of the sentence would put the fact in the markup
    of six documents and the engine's emitter instead of in one rule per surface.

    FAILS if any surface's centre zone loses the weight, if it is written somewhere other than the
    zone rule, or if the anchor is given a weight of its own."""
    portal_siblings = (r"(?m)^\s*footer\{([^}]*)\}", r"(?m)^\s*footer a\{([^}]*)\}",
                       r"(?m)^\s*footer \.apilink\{([^}]*)\}",
                       r"(?m)^\s*footer \.foot-right\{([^}]*)\}")
    surfaces = [(name, (ROOT / name).read_text(encoding="utf-8"),
                 r"(?m)^\s*footer \.foot-main\{([^}]*)\}", portal_siblings)
                for name in _portal_pages()]
    surfaces.append(("engine/extract/_pages.py", _pages_text(), r"(?m)^\s*\.fcenter\{([^}]*)\}",
                     (r"(?m)^\s*footer\{([^}]*)\}", r"(?m)^\s*\.fleft\{([^}]*)\}",
                      r"(?m)^\s*\.fright\{([^}]*)\}")))
    for where, text, pattern, siblings in surfaces:
        base = _outside_queries(text)
        rules = re.findall(pattern, base)
        assert len(rules) == 1, f"{where}: expected exactly one centre zone rule, found {len(rules)}"
        assert _CENTRE_WEIGHT in rules[0], (
            f"{where}: the centre zone must declare {_CENTRE_WEIGHT}: {rules[0]!r}")
        for sibling in siblings:
            for rule in re.findall(sibling, base):
                assert "font-weight" not in rule, (
                    f"{where}: the weight belongs to the centre zone alone; a second declaration "
                    f"in {sibling!r} is a second place for the surfaces to drift: {rule!r}")
