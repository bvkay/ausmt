"""C42 Amendment A2 — executable JS pin for the base-station-id resolver (the override-fieldset key).

The C43-S2a standing rule requires stations-panel behaviour to be pinned with EXECUTABLE JS (the
function actually runs under node), never a string match alone. This pins baseStationId — the DOM-free
helper that resolves a station's BASE id (the id the coordinate-override fieldset MUST key by, D2
fix-round-2: base ids only, never file stems, never variant-suffixed ids) from the boot-loaded
base_ids.json map, falling back to the station's own catalogue id when absent (a non-variant station is
its own base; a variant-free corpus has no base_ids.json => empty map => every station its own base).

Red on pre-change code: baseStationId did not exist in STATIONS_JS (the extraction assert raises), so
the workbench had no authoritative base id and could not build a base-keyed fieldset — the A2 gap.
"""
from __future__ import annotations

from gateway import curatorpage
from gateway.tests.test_c43_stage2a_js_parity import (  # reuse the pure-node driver harness
    _extract_js_function,
    _run_node,
    pytestmark,  # node-absent skip (deliberately NOT on the gateway skip tripwire)
)

__all__ = ["pytestmark"]


def _base_id_driver() -> str:
    js = curatorpage.STATIONS_JS
    return (
        "import { readFileSync } from 'fs';\n"
        + _extract_js_function(js, "baseStationId") + "\n"
        + """
const cases = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const out = cases.map(function (c) { return baseStationId(c.map, c.ausmtId, c.catId); });
process.stdout.write(JSON.stringify(out));
""")


def test_js_base_station_id_resolver(tmp_path):
    """EXECUTABLE BASE-ID PIN. baseStationId returns the boot map's base id for a variant station, and the
    station's OWN catalogue id when the id is absent from the map (a non-variant station is its own base;
    a variant-free corpus has no base_ids.json => empty map => every station its own base). FAILS IF a
    variant station is not collapsed to its engine-derived base, or a non-variant station is not keyed by
    its own catalogue id (the two ways a fieldset could emit a key the engine's D2 gate forbids)."""
    cases = [
        # variant station: present in the boot map -> its engine-derived base id.
        {"map": {"au.s.site1.lemigraph": "SITE1"}, "ausmtId": "au.s.site1.lemigraph", "catId": "SITE1.lemigraph"},
        # its sibling variant collapses to the SAME base (one control for the physical site).
        {"map": {"au.s.site1.lemigraph": "SITE1", "au.s.site1.ohmega": "SITE1"},
         "ausmtId": "au.s.site1.ohmega", "catId": "SITE1.ohmega"},
        # non-variant station in a corpus that HAS variants (map non-empty, this id absent) -> own catId.
        {"map": {"au.s.site1.lemigraph": "SITE1"}, "ausmtId": "au.s.plain", "catId": "PLAIN"},
        # variant-free corpus: empty map -> every station is its own base (own catId).
        {"map": {}, "ausmtId": "au.s.plain", "catId": "PLAIN"},
    ]
    got = _run_node(tmp_path, _base_id_driver(), cases)
    assert got[0] == "SITE1", "a variant station must collapse to its engine-derived base id"
    assert got[1] == "SITE1", "both variants of one site collapse to the same base"
    assert got[2] == "PLAIN", "a non-variant station (absent from the map) is keyed by its own catalogue id"
    assert got[3] == "PLAIN", "an empty map (variant-free corpus) keys every station by its own id"
