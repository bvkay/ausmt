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
  * GEOMETRY - FAILS if either surface stops being a wrapping flex row, if the left link becomes
    shrinkable (it is then broken mid-phrase at the static pages' 840px reading measure, where the
    three regions do not all fit on one row), if the right zone stops growing (on a wrapped row its
    links fall under the left ones instead of against the right edge), or if the narrow-width
    stacking rule goes and a 375px viewport collides instead of stacking.
"""
import re
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


def _outside_media(text):
    """`text` with every @media block removed, brace-matched rather than regex-bounded.

    The base rules and their narrow-width overrides use the SAME selectors, so a pattern that does
    not exclude the media blocks finds each rule twice and an "exactly one" pin fails on a correct
    stylesheet. Excluding them is also what makes the exactly-one pin mean what it says: a SECOND
    unconditional declaration of a zone would override the pinned geometry at equal specificity."""
    out, i = [], 0
    while True:
        at = text.find("@media", i)
        if at < 0:
            out.append(text[i:])
            return "".join(out)
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


def test_both_footers_are_wrapping_flex_rows_that_give_at_the_centre():
    """GEOMETRY. The centre is the region that yields: the left link and the right links are each a
    short fixed phrase that reads badly broken, and the attribution line is prose that does not.

    FAILS if either footer stops being a wrapping flex row, if the left link becomes shrinkable, if
    the right zone stops growing, or if the narrow-width stacking rule goes."""
    surfaces = (
        ("portal/index.html", _index_text(), r"footer\{([^}]*)\}",
         {"left": r"(?m)^\s*footer \.apilink\{([^}]*)\}",
          "centre": r"(?m)^\s*footer \.foot-main\{([^}]*)\}",
          "right": r"(?m)^\s*footer \.foot-right\{([^}]*)\}"},
         r"@media\(max-width:760px\)\{footer \.apilink,footer \.foot-main,footer \.foot-right"
         r"\{flex:1 1 100%;text-align:left\}\}"),
        ("engine/extract/_pages.py", _pages_text(), r"\n  footer\{([^}]*)\}",
         {"left": r"(?m)^\s*\.fleft\{([^}]*)\}",
          "centre": r"(?m)^\s*\.fcenter\{([^}]*)\}",
          "right": r"(?m)^\s*\.fright\{([^}]*)\}"},
         r"@media\(max-width:760px\)\{\.fzone\{flex:1 1 100%;text-align:left\}\}"),
    )
    for where, text, row_re, zone_res, stack_re in surfaces:
        # The narrow-width overrides restate these selectors, so the base rules are read with the
        # @media blocks removed; the stacking rule is then read from the full text.
        base = _outside_media(text)
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

        assert re.search(stack_re, text), (
            f"{where}: each region must take a full row below the header's own 760px breakpoint, so "
            f"a 375px viewport stacks them instead of overlapping")


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
    body = re.findall(r"(?m)^\s*footer \.aboutbuild-body\{([^}]*)\}", _outside_media(text), re.S)
    assert len(body) == 1, f"expected exactly one base .aboutbuild-body rule, found {len(body)}"
    rule = " ".join(body[0].split())
    assert "right:0" in rule and "left:50%" not in rule, (
        f"the popover must open back from the footer's right edge, not centre on its control: {rule!r}")
    assert "width:min(440px,90vw)" in rule, (
        f"the popover must stay inside a narrow viewport: {rule!r}")

    narrow = re.search(r"@media\(max-width:760px\)\{footer\{position:relative\}\s*"
                       r"footer details\.aboutbuild\{position:static\}\s*"
                       r"footer \.aboutbuild-body\{left:18px;right:18px;width:auto\}\}", text)
    assert narrow, (
        "below the breakpoint the popover must be anchored to the footer (footer position:relative, "
        "the details static, the body inset to the footer's own padding), or it opens off-screen")
    assert text.index("footer .aboutbuild-body{position:absolute") < narrow.start(), (
        "the narrow-width override must FOLLOW the base rule it overrides: the two tie on "
        "specificity, so placed above it the override does nothing at all")
