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


def test_the_two_navs_carry_identical_container_rules():
    """The nav CONTAINER rule, character-identical across the surfaces. FAILS IF the wrap modes
    (or the gap, or the display) drift apart: a nowrap container and a wrap container hand
    zero-basis flex children different resolved widths, which is exactly the 47.5px tab-group
    offset the C9 review measured between the SPA and the pages at 1280px."""
    spa = _rule_body(INDEX.read_text(encoding="utf-8"), r"(?m)^\s*nav\{([^}]*)\}",
                     "portal/index.html")
    pages = _rule_body(PAGES_PY.read_text(encoding="utf-8"),
                       r"header\.site nav\{([^}]*)\}", "engine/extract/_pages.py")
    assert spa == pages, (
        "the nav container rules have drifted between the two headers:\n"
        f"  portal/index.html          {spa!r}\n"
        f"  engine/extract/_pages.py   {pages!r}")


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
# about.html is the ONE carve-out, by name: its header is a separate pending owner ruling and this
# lane does not touch it. 404.html is a bare error document with no header at all.
MARK_IMG = f'<img class="brandmark" src="{MARK_SRC}" alt="AusMT" width="30" height="30">'
MARK_EXEMPT = {"about.html"}


def _chrome_pages():
    """Every portal document that ships the site chrome, by name."""
    return [p for p in sorted(ROOT.glob("*.html")) if "<header>" in p.read_text(encoding="utf-8")]


def test_every_static_chrome_page_carries_the_ausmt_mark():
    """FAILS IF a portal page that wears the chrome shows anything but the AusMT mark as its
    identity, and equally if a NEW page appears wearing the chrome without one. Discovered from the
    filesystem rather than from a list, so adding a page cannot quietly add a sixth identity."""
    seen = []
    for page in _chrome_pages():
        if page.name in MARK_EXEMPT:
            continue
        seen.append(page.name)
        text = page.read_text(encoding="utf-8")
        assert MARK_IMG in text, (
            f"portal/{page.name}: the header identity must be the AusMT mark at {MARK_SRC}")
        assert MARK_RULE in text, (
            f"portal/{page.name}: the mark must carry the shared sizing rule {MARK_RULE!r}")
        assert "auscope-icon-white.png" not in text, (
            f"portal/{page.name}: the AuScope symbol is no longer this site's header identity; the "
            "relationship stays in footer and About content, in words")
    assert seen, "no chrome page was discovered; the glob or the header marker has moved"


def test_the_auscope_symbol_survives_on_exactly_one_page_and_it_is_the_carved_out_one():
    """The carve-out is a DECISION, so it is pinned as one. FAILS IF about.html quietly loses the
    AuScope symbol before the owner has ruled on its header, and equally if a second page picks it
    back up. Either way the owner's pending ruling would have been pre-empted by a drift."""
    holders = [p.name for p in sorted(ROOT.glob("*.html"))
               if "auscope-icon-white.png" in p.read_text(encoding="utf-8")]
    assert holders == sorted(MARK_EXEMPT), (
        f"exactly {sorted(MARK_EXEMPT)} may still carry the AuScope symbol as a header identity "
        f"pending the owner's ruling on that header, got {holders}")


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
