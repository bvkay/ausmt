"""C32/UX4 zoom threshold pin (Invariant 10).

Owner's rule (UX4, supersedes C32's continental-ONLY): MT sites are grouped at CONTINENTAL (z<=4) AND
STATE (z5-6) zoom; from REGIONAL zoom (z>=7) down every site shows individually. That is encoded in
map.js as a NAMED constant DISABLE_CLUSTERING_AT_ZOOM = 7, wired into L.markerClusterGroup's
disableClusteringAtZoom option. (C32 shipped 6 = continental only; UX4 moved it to 7 so state zoom is
grouped too — the grid/count-bubble view persists one zoom level deeper.)

This pins the value at the SOURCE level so a drive-by revert (back to 6 or 12, or inlining a different
literal) fails a test rather than silently re-tiering the map. A source scan (not jsdom) because the
vendored Leaflet stub in the interaction harness discards markerClusterGroup options — the observable we
care about is the value shipped in the source, which this reads directly.

FAILS IF:
- the named constant is missing, or is set to anything other than 7;
- disableClusteringAtZoom is given a raw numeric literal instead of the named constant (a revert path);
- disableClusteringAtZoom stops referencing the named constant at all;
- the map.js comment stops documenting the state-zoom decision trail.
"""
import re
from pathlib import Path

MAP_JS = Path(__file__).resolve().parent.parent / "src" / "map.js"


def _src():
    return MAP_JS.read_text(encoding="utf-8")


def test_named_constant_is_seven():
    src = _src()
    m = re.search(r"const\s+DISABLE_CLUSTERING_AT_ZOOM\s*=\s*(\d+)\s*;", src)
    assert m, "map.js must define `const DISABLE_CLUSTERING_AT_ZOOM = <n>;` (the owner's UX4 clustering-tier rule)"
    assert m.group(1) == "7", (
        f"DISABLE_CLUSTERING_AT_ZOOM must be 7 (grouped at continental z<=4 AND state z5-6 — individual "
        f"sites from regional zoom z>=7 down, UX4); found {m.group(1)}")


def test_disable_clustering_uses_the_named_constant_not_a_literal():
    src = _src()
    # the markerClusterGroup option must reference the NAMED constant (not a bare number a revert would use)
    assert re.search(r"disableClusteringAtZoom\s*:\s*DISABLE_CLUSTERING_AT_ZOOM", src), \
        "disableClusteringAtZoom must be wired to the named constant DISABLE_CLUSTERING_AT_ZOOM"
    # and must NOT carry an inline numeric literal (e.g. the old `disableClusteringAtZoom:12`)
    assert not re.search(r"disableClusteringAtZoom\s*:\s*\d", src), \
        "disableClusteringAtZoom must not use an inline numeric literal — use the named constant"


def test_owner_rule_documented_in_comment():
    # the owner's UX4 rule text must ride with the constant so intent survives future edits: state zoom is
    # now grouped too (the change from C32's continental-only). Pinning "state" here fails a silent revert
    # of the comment back to the continental-only rationale even if the literal 7 were kept.
    src = _src()
    assert "state" in src.lower() and "regional" in src.lower(), \
        "map.js must document the UX4 rule (grouped at continental AND state zoom; individual from regional) beside the constant"
