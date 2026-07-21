"""UX7a rail-layout STRUCTURE pins (Invariant 10) for index.html.

jsdom does no layout, so the runtime interaction driver cannot observe scroll geometry; these are static
STYLE + DOM-order assertions parsed from index.html. Each states its failure criterion, and each is proven
non-vacuous against the pre-UX7a source (the exact thing it forbids USED to be present):

  * A4 tree flex-fill/scroll — the base .tree rule must flex-grow and scroll internally, with NO fixed
    height and NO resize handle. Pre-UX7a it was `height:300px;max-height:60vh;resize:vertical` and had no
    `flex:` — so this rule FAILS on the old CSS.
  * A4 flex chain — #browseMode and #treeSection must carry `min-height:0` (so the tree can shrink below
    its content and scroll instead of pushing the rail into an outer scrollbar). Pre-UX7a neither selector
    existed — FAILS on the old CSS.
  * A2 collapse anchored bottom — #sidebarCollapse must be the LAST child of <aside class="filters">
    (after both mode panes) and .railcollapse must carry `margin-top:auto`. Pre-UX7a the button was the
    FIRST child and had no margin-top — FAILS on the old markup/CSS.
  * A3 collections above the tree — #collGroup must appear BEFORE #treeSection/#tree in source order.
    Pre-UX7a there was no #collGroup at all — FAILS on the old markup.
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


# ---- A4: the tree flex-fills and scrolls internally -------------------------------------------------

def test_tree_flex_fills_and_scrolls_internally():
    body = _rule(_style(_html()), ".tree")
    assert body is not None, "index.html lost its base .tree{...} rule"
    assert "flex:1" in body, f".tree must flex-grow to fill the rail (flex:1); got: {body}"
    assert "overflow-y:auto" in body, f".tree must scroll internally (overflow-y:auto); got: {body}"
    assert "min-height:0" in body, f".tree needs min-height:0 to shrink-and-scroll; got: {body}"


def test_tree_has_no_fixed_height_or_resize_handle():
    # FAILS if the retired fixed-height / resizable-box treatment reappears (it would break flex-fill and
    # could reintroduce the outer rail scrollbar). Non-vacuous: pre-UX7a .tree carried both.
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


# ---- A2: the collapse control is anchored bottom-right ----------------------------------------------

def test_collapse_control_is_last_child_of_the_rail():
    # FAILS if #sidebarCollapse is not the LAST element in the rail (i.e. anchored below both mode panes).
    # Non-vacuous: pre-UX7a the button was the FIRST child, ahead of #modeSeg.
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


# ---- A3: the collections block sits above the tree (static source order) ----------------------------

def test_collections_block_is_above_the_tree_in_source():
    # Complements the runtime driver pin (interaction_test.js C2): statically, #collGroup must appear
    # BEFORE #treeSection/#tree. Non-vacuous: pre-UX7a there was no #collGroup element at all.
    html = _html()
    i_cg = html.find('id="collGroup"')
    i_ts = html.find('id="treeSection"')
    assert i_cg >= 0, "index.html has no #collGroup block"
    assert i_ts >= 0, "index.html has no #treeSection"
    assert i_cg < i_ts, "#collGroup must appear before #treeSection (collections render above the tree)"


# ---- UX9 item 3: equal-width nav min-width token ----------------------------------------------------

def test_nav_button_min_width_fits_collections_label_across_pages():
    """UX9 (item 3). The equal-width header nav (nav button on index, nav a on about) must reserve
    min-width:112px so the widest label ("Collections", ~109.7px) is not clipped, mirrored across both
    pages. FAILS if either page falls back below 112px. Non-vacuous: the pre-UX9 token was 92px, which
    this asserts against — a red-proof on the old CSS trips here."""
    idx = _rule(_style(_html()), "nav button")
    assert idx is not None, "index.html lost its `nav button{...}` rule"
    assert "min-width:112px" in idx, f"index nav button must reserve min-width:112px (fit 'Collections'); got: {idx}"
    ab = _rule(_style(ABOUT.read_text(encoding="utf-8")), "nav a")
    assert ab is not None, "about.html lost its `nav a{...}` rule"
    assert "min-width:112px" in ab, f"about nav link must mirror min-width:112px; got: {ab}"
