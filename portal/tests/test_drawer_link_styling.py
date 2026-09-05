"""Drawer-polish workflow: the survey data-level grid's links.

The grid shipped with THREE anchor sites that no CSS rule ever coloured - the tile identifier links
(.dl-id), the "Levels per Rees et al. 2019" citation link (.dl-cite) and the instruments platform-PID link
(.dl-instr). With no author colour declared they fell back to the user agent's link colours, which on the
navy (--panel-2 #1E2B4F) tiles are a near-invisible dark blue, going browser-purple once followed. It is
the same defect the `.meta td a` rule already fixed for the summary tables, and it takes the same fix.

WHAT EACH LAYER PROVES (the three are deliberately different failure modes, not three spellings of one):

  * here, test_data_level_link_rules_reuse_the_established_treatment - the SHEET declares the styling for
    all three containers, at the value the portal's established link rules already use (read out of the
    sheet, never hard-coded here: the module's instruction was reuse, not a new colour), with :visited stated
    explicitly. FAILS IF a rule is missing, if someone invents a second accent, or if :visited is left to
    the browser. Needs no Node - it reads index.html.
  * here, test_unrecorded_tile_state_text_stays_muted_not_link_coloured - the negative: an absent level's
    "not yet recorded" is a statement, not a link, and must not be painted the accent.
  * tools/interaction_test.js (section DP) - the CASCADE: every anchor the grid actually renders is
    SELECTED by an accent rule, asserted with element.matches() against the real index.html stylesheet in
    jsdom. That is the layer that catches a container being renamed or a new link site being added out of
    the rules' reach; a string pin here could not.

Neither layer proves the RENDERED colour (jsdom resolves no custom properties and computes no cascade
beyond selector matching) - that remains a browser-eye check, and the screenshot is the report.
"""
import re
import shutil
from pathlib import Path

import pytest

from test_related_identifiers_render import _render

ROOT = Path(__file__).resolve().parent.parent          # portal/
INDEX = ROOT / "index.html"

# The three containers the grid puts links in, with the drawer.js site that emits each.
LINK_CONTAINERS = {
    ".dl-id": "the tile identifier links (DOIs / SARIG PIDs)",
    ".dl-cite": "the 'Levels per Rees et al. 2019' citation link",
    ".dl-instr": "the instruments platform-PID link",
}


def _stylesheet():
    css = INDEX.read_text(encoding="utf-8")
    css = css.split("<style>", 1)[1].split("</style>", 1)[0]
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _rules(css):
    """Flat (selector_list, declarations) pairs, descending into @media/@supports blocks.

    A naive `([^{}]+)\\{([^{}]*)\\}` scan would mis-parse this sheet - it carries @media and @keyframes
    blocks - so walk the braces instead and recurse one level into any at-rule that holds rules.
    """
    out, i, n = [], 0, len(css)
    while i < n:
        brace = css.find("{", i)
        if brace < 0:
            break
        prelude = css[i:brace].strip()
        depth, j = 1, brace + 1
        while j < n and depth:
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
            j += 1
        body = css[brace + 1:j - 1]
        if prelude.startswith("@"):
            if not prelude.startswith("@keyframes"):    # keyframe stops are not selectors
                out.extend(_rules(body))
        else:
            out.append((prelude, body))
        i = j
    return out


def _colour_for(rules, selector):
    """The `color:` value declared by the rule whose selector list contains `selector`, else None."""
    for prelude, body in rules:
        if selector in [s.strip() for s in prelude.split(",")]:
            m = re.search(r"(?:^|;)\s*color\s*:\s*([^;]+)", body)
            if m:
                return m.group(1).strip()
    return None


def test_data_level_link_rules_reuse_the_established_treatment():
    """Each of the grid's three link containers gets a descendant-anchor colour AND an explicit :visited
    colour, both equal to the value the portal's established link rules already carry. FAILS (RED before
    this module) IF any container has no colour rule - which is exactly how the DOI, citation and
    platform-PID links shipped in the UA default - or IF a new accent is invented instead of reused."""
    rules = _rules(_stylesheet())
    # The established styling, READ OUT OF THE SHEET: the organisation ROR link in the drawer subline and
    # the publication DOIs inside .surveymeta. If those two ever disagree, this pin says so before comparing.
    org = _colour_for(rules, ".dsub a.orglink")
    pubs = _colour_for(rules, ".surveymeta a")
    assert org and pubs, "the established link rules (.dsub a.orglink / .surveymeta a) are gone from index.html"
    assert org == pubs, f"the two link colours disagree: {org!r} vs {pubs!r}"
    for cls, what in LINK_CONTAINERS.items():
        got = _colour_for(rules, f"{cls} a")
        assert got, f"{what}: index.html declares no colour for '{cls} a' - the UA default ships"
        assert got == org, f"{what}: '{cls} a' uses {got!r}, not the shared colour {org!r}"
        vis = _colour_for(rules, f"{cls} a:visited")
        assert vis, f"{what}: no ':visited' colour for '{cls} a' - a followed link may go browser-purple"
        assert vis == org, f"{what}: '{cls} a:visited' uses {vis!r}, not the shared colour {org!r}"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_unrecorded_tile_state_text_stays_muted_not_link_coloured(tmp_path):
    """The muted tiles' 'not yet recorded' state is a STATEMENT OF ABSENCE, not a link. It must stay in
    the .dl-state span with no anchor, and no rule may paint .dl-state the accent (which would read as a
    followable identifier). FAILS IF the state text is ever wrapped in an anchor or accent-coloured."""
    _station, story, _card = _render(tmp_path, {})      # nothing recorded: all six tiles muted
    states = re.findall(r'<small class="dl-state">(.*?)</small>', story)
    assert len(states) == 6, f"expected six muted state lines, got {len(states)}:\n{story}"
    for s in states:
        assert s.strip() == "not yet recorded", f"unexpected state copy: {s!r}"
        assert "<a " not in s, f"the 'not yet recorded' state became a link: {s!r}"
    rules = _rules(_stylesheet())
    org = _colour_for(rules, ".dsub a.orglink")
    for prelude, body in rules:
        if any(s.strip().endswith(".dl-state") for s in prelude.split(",")):
            m = re.search(r"(?:^|;)\s*color\s*:\s*([^;]+)", body)
            assert not m or m.group(1).strip() != org, \
                f"the muted state text is painted the link accent by rule '{prelude.strip()}'"
