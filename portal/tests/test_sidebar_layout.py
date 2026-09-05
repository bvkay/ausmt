"""Rail-layout STRUCTURE pins (Invariant 10) for index.html.

jsdom does no layout, so the runtime interaction driver cannot observe scroll geometry; these are static
STYLE + DOM-order assertions parsed from index.html. Each states its failure criterion, and each is proven
non-vacuous against a source that carries the exact thing it forbids:

  * tree flex-fill/scroll: the base .tree rule must flex-grow and scroll internally, with NO fixed
    height and NO resize handle. In the old CSS it is `height:300px;max-height:60vh;resize:vertical` with no
    `flex:` — so this rule FAILS on the old CSS.
  * Flex chain: #browseMode and #treeSection must carry `min-height:0` (so the tree can shrink below
    its content and scroll instead of pushing the rail into an outer scrollbar). In the old CSS neither selector
    existed — FAILS on the old CSS.
  * Collapse anchored bottom: #sidebarCollapse must be the LAST child of <aside class="filters">
    (after both mode panes) and .railcollapse must carry `margin-top:auto`. In the old markup the button was the
    FIRST child and had no margin-top — FAILS on the old markup/CSS.
  * Collections above the tree: #collGroup must appear BEFORE #treeSection/#tree in source order.
    In the old markup there was no #collGroup at all - FAILS on it.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # portal/
INDEX = ROOT / "index.html"
ABOUT = ROOT / "about.html"


def _html():
    return INDEX.read_text(encoding="utf-8")


def _style(html):
    m = re.search(r"<style>(.*?)</style>", html, re.S)
    assert m, "index.html has no <style> block"
    return m.group(1)


def _rule(css, selector):
    """Return the declaration body of the FIRST `selector{...}` block, or None. `selector` is matched
    literally and must be immediately followed by `{` (so '.tree' will not match '.tree .survey' or
    '.treegroup')."""
    m = re.search(re.escape(selector) + r"\{([^}]*)\}", css)
    return m.group(1) if m else None


def _aside_block(html):
    """The raw <aside class="filters" ...> ... </aside> source (the filter rail)."""
    m = re.search(r"<aside class=\"filters\"[^>]*>(.*?)</aside>", html, re.S)
    assert m, "index.html has no <aside class=\"filters\">"
    return m.group(1)


# ---- The tree flex-fills and scrolls internally -----------------------------------------------------

def test_tree_flex_fills_and_scrolls_internally():
    body = _rule(_style(_html()), ".tree")
    assert body is not None, "index.html lost its base .tree{...} rule"
    assert "flex:1" in body, f".tree must flex-grow to fill the rail (flex:1); got: {body}"
    assert "overflow-y:auto" in body, f".tree must scroll internally (overflow-y:auto); got: {body}"
    assert "min-height:0" in body, f".tree needs min-height:0 to shrink-and-scroll; got: {body}"


def test_tree_has_no_fixed_height_or_resize_handle():
    # FAILS if the retired fixed-height / resizable-box styling reappears (it would break flex-fill and
    # could reintroduce the outer rail scrollbar). Non-vacuous: pre-tree carried both.
    body = _rule(_style(_html()), ".tree")
    # a fixed/capped height (height:300px, max-height:60vh, ...) must be gone; min-height:0 is allowed.
    assert re.search(r"(?<!min-)height:\s*[0-9]", body) is None, \
        f".tree must not pin a fixed/max height (flex-fill instead); got: {body}"
    assert "resize:" not in body, f".tree must not be a resize:vertical box any more; got: {body}"
    # the Surveys-view height override must be gone too (flex-fill supersedes it)
    assert re.search(r"\.tree-tall\s+\.tree\{", _style(_html())) is None, \
        ".tree-tall .tree height override must be removed (flex-fill supersedes it)"


def test_browse_and_tree_flex_chain_has_min_height_zero():
    css = _style(_html())
    for sel in ("#browseMode", "#treeSection"):
        body = _rule(css, sel)
        assert body is not None, f"index.html lost the {sel}{{...}} flex-chain rule"
        assert "min-height:0" in body, f"{sel} needs min-height:0 so the tree can scroll (no outer rail scroll); got: {body}"


# ---- The collapse control is anchored bottom-right --------------------------------------------------

def test_collapse_control_is_last_child_of_the_rail():
    # FAILS if #sidebarCollapse is not the LAST element in the rail (i.e. anchored below both mode panes).
    # Non-vacuous: in the old markup the button was the FIRST child, ahead of #modeSeg.
    aside = _aside_block(_html())
    i_btn = aside.find('id="sidebarCollapse"')
    i_sel = aside.find('id="selectMode"')
    i_browse = aside.find('id="browseMode"')
    assert i_btn >= 0, "the rail has no #sidebarCollapse control"
    assert i_sel >= 0 and i_browse >= 0, "the rail lost a mode pane (#browseMode/#selectMode)"
    assert i_btn > i_sel and i_btn > i_browse, \
        "#sidebarCollapse must come AFTER both mode panes (anchored at the bottom of the rail)"
    # nothing but whitespace/comments may follow the button's element before </aside>
    tail = aside[aside.find("<button", i_btn):]
    assert tail.count("<section") == 0 and tail.count('class="railmodepane"') == 0, \
        "no rail section may follow the collapse control (it must be the last child)"


def test_collapse_control_css_anchors_to_bottom():
    body = _rule(_style(_html()), ".railcollapse")
    assert body is not None, "index.html lost the .railcollapse rule"
    assert "margin-top:auto" in body, \
        f".railcollapse must use margin-top:auto to anchor the control at the bottom of the rail; got: {body}"


# ---- The collections block sits above the tree (static source order) --------------------------------

def test_collections_block_is_above_the_tree_in_source():
    # Complements the runtime driver pin (interaction_test.js): statically, #collGroup must appear
    # BEFORE #treeSection/#tree. Non-vacuous: in the old markup there was no #collGroup element at all.
    html = _html()
    i_cg = html.find('id="collGroup"')
    i_ts = html.find('id="treeSection"')
    assert i_cg >= 0, "index.html has no #collGroup block"
    assert i_ts >= 0, "index.html has no #treeSection"
    assert i_cg < i_ts, "#collGroup must appear before #treeSection (collections render above the tree)"


# ---- Equal-width nav min-width token ----------------------------------------------------------------

def test_nav_button_min_width_fits_collections_label_across_pages():
    """The equal-width header nav (nav button on index, nav a on about) must reserve
    min-width:112px so the widest label ("Collections", ~109.7px) is not clipped, mirrored across both
    pages. FAILS if either page falls back below 112px. Non-vacuous: the pre-token was 92px, which
    this asserts against — a red-proof on the old CSS trips here."""
    idx = _rule(_style(_html()), "nav button")
    assert idx is not None, "index.html lost its `nav button{...}` rule"
    assert "min-width:112px" in idx, f"index nav button must reserve min-width:112px (fit 'Collections'); got: {idx}"
    # LANE-ADDENDUM-HUB-FEEDBACK.md: index's Surveys and Collections controls are LINKS to the
    # served hub pages now, so index carries both shapes and the token has to hold in both. Without
    # this leg the widest label could be clipped on the two controls that changed tag.
    idxa = _rule(_style(_html()), "nav a")
    assert idxa is not None, "index.html must style its `nav a{...}` links alongside `nav button`"
    assert "min-width:112px" in idxa, f"index nav link must mirror min-width:112px; got: {idxa}"
    ab = _rule(_style(ABOUT.read_text(encoding="utf-8")), "nav a")
    assert ab is not None, "about.html lost its `nav a{...}` rule"
    assert "min-width:112px" in ab, f"about nav link must mirror min-width:112px; got: {ab}"
