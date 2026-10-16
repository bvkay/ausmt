"""The portal on phones and touch screens: tap targets, safe areas, the phone header and reachability.

jsdom does no layout and evaluates no media query, so these are SOURCE pins on the rules a browser
applies at a phone width or under a coarse pointer. The geometry they produce is measured in a real
browser and recorded in docs/docs/reference/portal-internals.md; what this file holds is that the
rules are there, where they must be, and that the desktop rules they override are left alone.

Each assertion states its failure criterion:

  * TAP TARGETS - FAILS if the coarse-pointer block on the map page stops giving every named control
    a 44px floor in both directions, or if an inline control (a footer link) loses the display that
    lets a floor apply to it.
  * INPUTS - FAILS if a text input or select on the map page or the /surveys controls is under 16px
    on a coarse pointer, the size below which iOS Safari zooms the page on focus.
"""
import re
from pathlib import Path

from chrome_contract import TAP_TARGET

ROOT = Path(__file__).resolve().parent.parent          # portal/
INDEX = ROOT / "index.html"
PAGES_PY = ROOT.parent / "engine" / "extract" / "_pages.py"

# The controls the coarse-pointer block must lift to a 44px floor, by the selector the block names.
# .seg button covers the Browse and Select control and the drawer's tabs; the Leaflet bar anchors
# are the zoom and draw controls.
COARSE_TARGETS = (".typegrid label", ".collgroup .coll", ".seg button", ".leaflet-touch .leaflet-bar a",
                  ".maplegend-toggle", ".maplegend .legtype", ".dhead .close", ".plotexp", "footer a")
COARSE_INPUTS = ("#find", "#availSel", "#surveySearch", "#yearFrom", "#yearTo", "#sortSel")


def _text(path):
    return path.read_text(encoding="utf-8")


def _blocks(text, prelude):
    """The bodies of every at-rule whose prelude is exactly `prelude`, brace-matched."""
    out, i = [], 0
    while True:
        at = text.find(prelude + "{", i)
        if at < 0:
            return out
        j = start = at + len(prelude) + 1
        depth = 1
        while depth:
            depth += {"{": 1, "}": -1}.get(text[j], 0)
            j += 1
        out.append(text[start:j - 1])
        i = j


def _rules(css):
    """{selector: declarations} for a flat run of rules, each selector of a group listed on its own."""
    out = {}
    for sels, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        for sel in sels.split(","):
            out.setdefault(" ".join(sel.split()), []).append(body)
    return out


def _decls(bodies):
    return ";".join(bodies).replace(" ", "")


def test_the_coarse_pointer_block_gives_every_named_control_a_44px_floor():
    """FAILS if index.html has no pointer:coarse block, if a named control is missing from it, or if
    its rule declares less than a 44px floor in either direction."""
    blocks = _blocks(_text(INDEX), "@media (pointer:coarse)")
    assert blocks, "index.html must carry a @media (pointer:coarse) block"
    rules = _rules("".join(blocks))
    floor = f"{TAP_TARGET}px"
    for sel in COARSE_TARGETS:
        assert sel in rules, f"index.html: the coarse-pointer block must name {sel!r}"
        decls = _decls(rules[sel])
        for prop in ("min-height", "min-width"):
            assert f"{prop}:{floor}" in decls, f"index.html: {sel} must declare {prop}:{floor}: {decls!r}"
    assert "display:inline-flex" in _decls(rules["footer a"]), (
        "index.html: a footer link is inline, where min-height does nothing; it must become an "
        "inline flex box under a coarse pointer")


def test_coarse_pointer_inputs_are_16px_on_the_map_page_and_the_surveys_page():
    """FAILS if a named input on the map page, or the /surveys inputs and selects, are under 16px on a
    coarse pointer."""
    rules = _rules("".join(_blocks(_text(INDEX), "@media (pointer:coarse)")))
    for sel in COARSE_INPUTS:
        assert sel in rules and "font-size:16px" in _decls(rules[sel]), (
            f"index.html: {sel} must be 16px under a coarse pointer")
    pages = _rules("".join(_blocks(_text(PAGES_PY), "@media (pointer:coarse)")))
    for sel in (".idxctl input", ".idxctl select"):
        assert sel in pages and "font-size:16px" in _decls(pages[sel]), (
            f"engine/extract/_pages.py: {sel} must be 16px under a coarse pointer")
