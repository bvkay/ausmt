"""One footer, three regions, the same on the SPA and on the static pages the engine emits.

The two surfaces had drifted into two different footers. The SPA carried the MTCAT link, then one
run-on span holding the copyright, the licence note, Releases and the About-this-build control. The
static pages carried a two-row grid with different wording again ("Machine-readable catalogue",
"an AuScope service", "each download carries its licence") and a per-page-kind left link, so no two
page kinds even agreed with each other. The owner's ruling is one footer: LEFT the machine-readable
catalogue, CENTRE the attribution and the licence note, RIGHT Releases and About this build.

WHY THE ENGINE HALF LIVES HERE rather than in engine/tests, and why it reads _pages.py's SOURCE
text: the same two reasons test_header_geometry_parity.py gives. portal-ci runs on portal/** AND on
engine/extract/_pages.py, so an edit to either surface fires this lane, where the engine lane
triggers on engine/** alone and cannot see an index.html edit; and _pages.py cannot simply be
imported (it sibling-imports _au_outline and _stationcheck, which need the engine's own path set
up). The engine lane holds its own half of this in engine/tests/test_index_pages.py, asserted
against real rendered pages; this module is what stops the two surfaces diverging again.

THE SEPARATOR IS U+00B7 on both surfaces, spelt here as an escape so a mis-decoded read of this
file cannot let a hyphen or a dash through the pin. index.html writes the character literally and
_pages.py writes it as the numeric reference; both are asserted as the codepoint.

Each assertion states its failure criterion:

  * REGIONS - FAILS if either surface does not carry exactly three footer regions, or if a region
    holds something belonging to another (a link in the attribution line, the licence note in with
    the navigation).
  * STRINGS - FAILS if either surface's centre line drifts from the owner's wording, or if the
    left link's label stops being the MTCAT one.
  * TARGETS - FAILS if the two surfaces stop agreeing on where a region's links point. The MTCAT
    document is one target expressed twice: the SPA is served from the portal root and writes it
    relative, the static pages are served from /surveys/<slug> and cannot, so the pin holds the
    ROOT-RELATIVE form of both against each other rather than the raw strings.
  * GEOMETRY - FAILS if either surface stops being a wrapping flex row or stops being a query
    container, if the left link becomes shrinkable (it is then broken mid-phrase at the static
    pages' 840px reading measure, where the three regions do not all fit on one row), if the right
    zone stops growing (on a wrapped row its links fall under the left ones instead of against the
    right edge), or if either state below one row goes and the attribution is left centred in the
    space beside the machine-readable link, or a 375px viewport collides instead of stacking.
  * PARITY ACROSS THE PORTAL - FAILS if any HTML document the portal ships stops carrying the three
    regions, or drifts on a string, a target or a separator.

BOTH QUERIES ASK THE FOOTER'S OWN WIDTH, not the viewport's. On the static tier main is 840px on an
entity page, 920px on a hub and 1120px above 1180px of viewport, and on the portal the sibling pages
set their footers inside reading columns of 760px to 980px, so no single viewport number describes
"the three regions do not fit" on more than one page kind at a time.
"""
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # portal/
INDEX = ROOT / "index.html"
PAGES_PY = ROOT.parent / "engine" / "extract" / "_pages.py"

DOT = "·"

# The owner's three regions, as the strings a reader sees. The centre and the right are asserted
# character-for-character; the left's label is, and its target is asserted separately because the
# two surfaces necessarily spell the same URL differently.
CENTRE = f"© 2026 AuScope and the AusMT contributors {DOT} Data licences vary by survey"
LEFT_LABEL = "Machine-readable record (MTCAT JSON)"
MTCAT = "/data/mtcat.json"
RELEASES = "/releases.html"
ABOUT = "/about.html"


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
    """The named/numeric character references a page writes, resolved, so the two surfaces can be
    compared as the characters a reader sees rather than as two spellings of them."""
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
    # The right region nests a <details>, so the class-scoped span regex above would stop at the
    # popover's first close tag. It is taken as everything from the opening tag to the footer's end.
    right = foot.split('<span class="foot-right">', 1)
    assert len(right) == 2, "index.html's footer must carry a foot-right region"
    return {"left": left[0].strip(),
            "centre": _regions(foot, {"centre": "foot-main"})["centre"],
            "right": right[1].rsplit("</span>", 1)[0].strip()}


def _engine_regions():
    foot = _engine_footer()
    return _regions(foot, {"left": "fzone fleft", "centre": "fzone fcenter",
                           "right": "fzone fright"})


def test_both_surfaces_carry_the_same_three_regions_with_the_owners_strings():
    """REGIONS and STRINGS. Non-vacuous in both halves: run against the pre-ruling surfaces, the
    engine side fails on its two-row .frow grid and the SPA side on a footer with no foot-right
    region at all (its centre and right ran together in one span)."""
    for where, regions in (("portal/index.html", _index_regions()),
                           ("engine/extract/_pages.py", _engine_regions())):
        left = _entity(regions["left"])
        assert LEFT_LABEL in left, f"{where}: the left region must read {LEFT_LABEL!r}, got {left!r}"
        assert "↗" in left, (
            f"{where}: the left link carries the leaves-this-page arrow (U+2197), got {left!r}")

        centre = " ".join(_entity(regions["centre"]).split())
        assert centre == CENTRE, f"{where}: centre must read {CENTRE!r}, got {centre!r}"
        assert "<a" not in regions["centre"], (
            f"{where}: the attribution line is prose, not navigation, and carries no link: "
            f"{regions['centre']!r}")

        right = _entity(regions["right"])
        assert ">Releases<" in right, f"{where}: the right region must offer Releases: {right!r}"
        assert "About this build" in right, (
            f"{where}: the right region must offer About this build: {right!r}")
        assert DOT in right, (
            f"{where}: Releases and About this build are separated by U+00B7: {right!r}")
        assert right.index(">Releases<") < right.index("About this build"), (
            f"{where}: Releases comes first, beside About this build: {right!r}")


def test_the_two_surfaces_agree_on_where_the_footer_points():
    """TARGETS. The MTCAT document, the releases page and the about page are each ONE destination
    reached from two surfaces, so they are compared as root-relative paths. FAILS if a surface
    retargets a region's link, or if the SPA's relative form stops resolving to the engine's
    absolute one."""
    idx, eng = _index_regions(), _engine_regions()

    def href(region, where):
        hits = re.findall(r'href="([^"]+)"', region)
        assert hits, f"{where}: no link in {region!r}"
        return hits

    # index.html's own href sits on the <a class="apilink"> tag, which _index_regions strips.
    idx_left = re.findall(r'<a class="apilink" href="([^"]+)"', _index_footer())
    assert idx_left == ["data/mtcat.json"], (
        f"index.html's MTCAT link must stay at data/mtcat.json, got {idx_left}")
    assert "/" + idx_left[0] == MTCAT, (
        f"the SPA's relative MTCAT link must resolve to the engine's {MTCAT}, got {idx_left[0]}")
    assert href(eng["left"], "engine/extract/_pages.py") == [MTCAT], (
        f"the engine footer's MTCAT link must target {MTCAT}")

    assert href(idx["right"], "portal/index.html") == ["releases.html"], (
        "index.html's footer must link Releases at releases.html and carry no other right-region link "
        "(About this build is the SPA's own disclosure popover, not a link)")
    assert href(eng["right"], "engine/extract/_pages.py") == [RELEASES, ABOUT], (
        f"the engine footer's right region must link {RELEASES} then {ABOUT}: the static tier ships "
        f"no script, so About this build resolves to the page that carries the build's identity")


# --------------------------------------------------------------- every page the portal ships
#
# The SPA was held against the engine above; these hold the five sibling documents against the SPA.
# They were the drift the ruling did not reach: each carried its own footer, and the "About this
# build" the new footer points at landed on one of them.
#
# 404.html is the ONE difference, and it is a decision rather than an omission. Caddy rewrites any
# unmatched path to that document, so a relative link there would resolve against the address that
# was not found and every one of its links is root-absolute. It also loads no script and carries no
# version chip, so About this build is a LINK to the page that does carry the build's identity,
# which is what the static tier the engine emits does for the same reason.
_POPOVER_PAGES = ("about.html", "add-survey.html", "brand.html", "index.html", "releases.html")
_LINK_PAGES = ("404.html",)


def _portal_pages():
    return sorted(p.name for p in ROOT.glob("*.html"))


class _FooterRegions(HTMLParser):
    """The footer's TOP-LEVEL children, each with the html it encloses.

    Depth-tracked rather than regex-split because the right region nests a <details>, whose first
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
    targets relative; 404.html is served for any address at any depth and writes them absolute."""
    if href.startswith("/"):
        return href
    assert not href.startswith(("http://", "https://", "//")), (
        f"{name}: a footer target must stay on this site, got {href!r}")
    return "/" + href


def test_every_portal_page_carries_the_one_footer():
    """PARITY ACROSS THE PORTAL. Every HTML document the portal ships carries the same three
    regions, in order, with the owner's strings, the same targets and U+00B7 between them.

    FAILS if a page carries fewer or more than three regions, if a region's string drifts, if the
    attribution grows a link, if a target moves, if a separator stops being the middle dot, or if a
    new page is added to portal/ without this pin reaching it."""
    assert _portal_pages() == sorted(_POPOVER_PAGES + _LINK_PAGES), (
        f"the portal ships {_portal_pages()}, which is not the set this pin enumerates; a new page "
        f"carries the one footer too, so add it to _POPOVER_PAGES or _LINK_PAGES")

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
        assert label == f"{LEFT_LABEL} \u2197", (
            f"{name}: the left region must read {LEFT_LABEL!r} with the leaves-this-page arrow, "
            f"got {label!r}")
        assert _root_relative(lattrs.get("href", ""), name) == MTCAT, (
            f"{name}: the left link must resolve to {MTCAT}, got {lattrs.get('href')!r}")

        # CENTRE. The owner's attribution line, and no link: it is prose, not navigation.
        assert ctag == "span" and cattrs.get("class") == "foot-main", (
            f"{name}: the second region is the attribution, got <{ctag} "
            f"class={cattrs.get('class')!r}>")
        centre = " ".join(_entity(cinner).split())
        assert centre == CENTRE, f"{name}: centre must read {CENTRE!r}, got {centre!r}"
        assert "<a" not in cinner, (
            f"{name}: the attribution line is prose and carries no link: {cinner!r}")

        # RIGHT. Releases, the middle dot, then About this build.
        assert rtag == "span" and rattrs.get("class") == "foot-right", (
            f"{name}: the third region is Releases beside About this build, got <{rtag} "
            f"class={rattrs.get('class')!r}>")
        right = _entity(rinner)
        # The popover BODY is disclosure, not the visible line, and it carries its own links on the
        # pages that explain a licence there. Only what a reader sees on the footer's row is held.
        visible = right.split("<details", 1)[0]
        links = re.findall(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', visible, re.S)
        assert links and " ".join(links[0][1].split()) == "Releases", (
            f"{name}: the right region must open with Releases, got {visible!r}")
        assert _root_relative(links[0][0], name) == RELEASES, (
            f"{name}: Releases must resolve to {RELEASES}, got {links[0][0]!r}")
        assert "About this build" in right, (
            f"{name}: the right region must offer About this build: {right!r}")
        between = right[right.index("</a>") + 4:right.index("About this build")]
        assert DOT in between, (
            f"{name}: Releases and About this build are separated by U+00B7, got {between!r}")

        if name in _POPOVER_PAGES:
            assert re.search(r'<details class="aboutbuild">\s*<summary>About this build</summary>',
                             right), (
                f"{name}: this page ships script, so About this build is the disclosure popover the "
                f"SPA carries: {right!r}")
            assert len(links) == 1, (
                f"{name}: the visible right region links Releases and nothing else; About this "
                f"build is the popover control, got {[h for h, _ in links]}")
        else:
            assert "<details" not in right, (
                f"{name}: this page ships no script, so About this build is a link, not a popover "
                f"that could only restate the line above it: {right!r}")
            assert [(_root_relative(h, name), " ".join(t.split())) for h, t in links] == [
                (RELEASES, "Releases"), (ABOUT, "About this build")], (
                f"{name}: the right region must link {RELEASES} then {ABOUT}, got {links!r}")


def test_both_footers_are_wrapping_flex_rows_that_give_at_the_centre():
    """GEOMETRY. The centre is the region that yields: the left link and the right links are each a
    short fixed phrase that reads badly broken, and the attribution line is prose that does not.

    There are two states below one row and each is pinned. Below the width the three regions need,
    the centre takes a row of its own UNDER the two side phrases, where it spans the footer and is
    centred on its axis; below the width the two side phrases need, every region takes a row and
    aligns left, which is the 375px stack. Measured in Chrome, the state that was missing left the
    attribution 135px off the axis on an entity page at any viewport under 1180px.

    FAILS if either footer stops being a wrapping flex row or stops establishing the query container
    its own rules ask about, if the left link becomes shrinkable, if the right zone stops growing,
    if either state below one row goes, if one stops following the rules it overrides, or if a
    viewport rule comes back in their place."""
    surfaces = (
        ("portal/index.html", _index_text(), r"footer\{([^}]*)\}",
         {"left": r"(?m)^\s*footer \.apilink\{([^}]*)\}",
          "centre": r"(?m)^\s*footer \.foot-main\{([^}]*)\}",
          "right": r"(?m)^\s*footer \.foot-right\{([^}]*)\}"},
         "@container (max-width:950px){footer .foot-main{order:1;flex:1 1 100%}}",
         "@container (max-width:520px){footer .apilink,footer .foot-main,footer .foot-right"
         "{order:0;flex:1 1 100%;text-align:left}}",
         "@media(max-width:760px){footer .apilink"),
        ("engine/extract/_pages.py", _pages_text(), r"\n  footer\{([^}]*)\}",
         {"left": r"(?m)^\s*\.fleft\{([^}]*)\}",
          "centre": r"(?m)^\s*\.fcenter\{([^}]*)\}",
          "right": r"(?m)^\s*\.fright\{([^}]*)\}"},
         "@container (max-width:900px){.fcenter{order:1;flex:1 1 100%}}",
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
            f"{where}: the right zone grows, so on a WRAPPED row its links still sit against the "
            f"right edge rather than under the left ones: {zones['right']!r}")
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
            f"{where}: every region must take a full row and align left once the two side phrases "
            f"cannot share one, in a rule that FOLLOWS the centre's own-row rule: the two tie on "
            f"specificity, so placed above it the stack would not restore the 375px reading order")
        assert re.search(zone_res["right"], text).start() < centre_row, (
            f"{where}: both states below one row must follow the zone rules they override; the "
            f"selectors tie on specificity and source order alone decides")
        assert retired not in text, (
            f"{where}: the footer's width is not the viewport's on either surface, so the rules "
            f"below one row must not go back to asking the viewport: found {retired!r}")


def test_the_about_this_build_popover_stays_on_screen_at_both_widths():
    """The About-this-build control moved from a centred span to the footer's RIGHT region, so a
    popover still centred on its own summary hangs off the right edge. Anchored to that edge it is
    right on a wide screen and wrong on a narrow one, where the region stacks and the control sits
    near the LEFT of its own row: measured at 375px the popover then started at x=-164. (It was
    already off-screen there before the regions were split, at x=-42.) Below the breakpoint it is
    anchored to the footer instead, which is the only box on that row wide enough to hold it.

    FAILS if the wide-screen anchor goes back to centring on the control, if the width cap goes, or
    if the narrow-width override is lost or stops following the rule it overrides (the two tie on
    specificity, so an override placed ABOVE its base rule silently does nothing)."""
    text = _index_text()
    body = re.findall(r"(?m)^\s*footer \.aboutbuild-body\{([^}]*)\}", _outside_queries(text), re.S)
    assert len(body) == 1, f"expected exactly one base .aboutbuild-body rule, found {len(body)}"
    rule = " ".join(body[0].split())
    assert "right:0" in rule and "left:50%" not in rule, (
        f"the popover must open back from the footer's right edge, not centre on its control: {rule!r}")
    assert "width:min(440px,90vw)" in rule, (
        f"the popover must stay inside a narrow viewport: {rule!r}")

    assert "position:relative" in " ".join(re.findall(r"(?m)^\s*footer\{([^}]*)\}",
                                                     _outside_queries(text))), (
        "the footer must carry position:relative unconditionally: a container query cannot style "
        "the element that establishes it, so the anchor cannot be declared inside the stack rule")
    narrow = re.search(r"@container \(max-width:520px\)\{footer details\.aboutbuild\{position:static\}\s*"
                       r"footer \.aboutbuild-body\{left:18px;right:18px;width:auto\}\}", text)
    assert narrow, (
        "in the stacked state the popover must be anchored to the footer (the details static, the "
        "body inset to the footer's own padding), or it opens off-screen")
    assert text.index("footer .aboutbuild-body{position:absolute") < narrow.start(), (
        "the stacked-state override must FOLLOW the base rule it overrides: the two tie on "
        "specificity, so placed above it the override does nothing at all")
