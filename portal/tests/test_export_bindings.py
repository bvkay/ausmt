"""The export panel's handler bindings degrade instead of dying.

exports.js used to bind nine handlers with unguarded document.getElementById(id).onclick= at parse
time: one missing id threw, aborted the file mid-load, and silently dropped every later binding and
top-level assignment. The bindings must go through the guarded helper, and the disabled-state loop
in filters.js must tolerate a missing element the same way.
"""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"


def test_exports_bindings_are_guarded():
    src = (SRC / "exports.js").read_text(encoding="utf-8")
    bare = re.findall(r'document\.getElementById\("[^"]+"\)\.onclick\s*=', src)
    assert not bare, "unguarded onclick bindings in exports.js: %r" % bare
    assert "function bindClick(" in src, "the guarded binding helper is missing"


def test_filters_disabled_loop_is_guarded():
    src = (SRC / "filters.js").read_text(encoding="utf-8")
    assert "document.getElementById(id).disabled" not in src, (
        "the export-button disabled loop dereferences getElementById(id) without a guard")


def test_select_all_clears_drawn_shapes():
    # 'Select all filtered' replaces a shape selection, but refresh() re-derives the selection from
    # any drawn shape, so a stale shape silently discards the select-all on the next filter change.
    # The handler must clear the shapes when it takes over the selection. A source pin (the jsdom
    # harness stubs Leaflet, so the shape path is not drivable there): the selAll handler's own line
    # must clear the layer group before it rebuilds `selected`.
    src = (SRC / "filters.js").read_text(encoding="utf-8")
    m = re.search(r'getElementById\("selAll"\)\.onclick=\(\)=>\{([^\n]*)\}', src)
    assert m, "the selAll handler moved; re-anchor this pin"
    handler = m.group(1)
    assert "drawn.clearLayers()" in handler, (
        "selAll must clear drawn shapes before taking over the selection: " + handler)
    assert handler.index("drawn.clearLayers()") < handler.index("selected="), (
        "selAll must clear shapes BEFORE rebuilding the selection: " + handler)


def test_selection_hint_copy_is_single_sourced():
    # The empty-state hint used to be typed twice (index.html markup default + the filters.js
    # ternary), so a copy edit had to touch both or they diverged. The markup owns it; filters.js
    # reads it at load.
    literal = "take everything that passes the filters."
    html = (SRC.parent / "index.html").read_text(encoding="utf-8")
    filters = (SRC / "filters.js").read_text(encoding="utf-8")
    assert literal in html, "the empty-state hint must live in the markup"
    assert literal not in filters, "the empty-state hint is duplicated in filters.js"
