"""C43 Stage-4 — executable JS pin for the per-station EFFECTIVE coordinate-policy marker.

The C43-S2a standing rule requires the stations-panel behaviour to be pinned with EXECUTABLE JS (the
functions actually run under node), never a string match alone. This pins the two DOM-free helpers the
Stage-4 marker rests on: effectivePolicy (coord_policy.json override-or-'exact') and positionText (the
Position fact row's '(exact)' / '(generalised)' / '(withheld)' marker). The node-driver mechanics are
reused from test_c43_stage2a_js_parity (pure `node`, no jsdom/npm).

Reds on pre-change code: positionText hardcoded '(exact)' and effectivePolicy did not exist, so a
non-exact station showed '(exact)' — the honesty defect this pin exists to catch.
"""
from __future__ import annotations

from gateway import curatorpage
from gateway.tests.test_c43_stage2a_js_parity import (  # reuse the node-driver harness
    _extract_js_function,
    _run_node,
    pytestmark,  # node-absent skip (deliberately NOT on the gateway skip tripwire)
)

__all__ = ["pytestmark"]


def _marker_driver() -> str:
    js = curatorpage.STATIONS_JS
    return (
        "import { readFileSync } from 'fs';\n"
        + _extract_js_function(js, "num") + "\n"
        + _extract_js_function(js, "effectivePolicy") + "\n"
        + _extract_js_function(js, "positionText") + "\n"
        + """
const cases = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const out = cases.map(function (c) {
  const pol = effectivePolicy(c.map, c.ausmtId);
  return { pol: pol, text: positionText(c.lat, c.lon, c.flag, pol) };
});
process.stdout.write(JSON.stringify(out));
""")


def test_js_effective_policy_marker(tmp_path):
    """EXECUTABLE MARKER PIN. The Position fact shows the station's EFFECTIVE coordinate policy — its
    coord_policy.json override if present, else 'exact' (absent from the boot map). A withheld station's
    masked null coords render '-, - (withheld)'; a generalised station shows its 0.1deg cell VERBATIM
    with '(generalised)'; an exact station keeps '(exact)'. FAILS IF a non-exact station is mislabelled
    '(exact)' (the pre-change static-marker defect), or the map lookup diverges."""
    cases = [
        # exact: absent from the boot map => 'exact'.
        {"map": {}, "ausmtId": "au.s.a", "lat": -24.9024, "lon": 117.3312, "flag": None},
        # generalised: 0.1deg cell, marked '(generalised)'.
        {"map": {"au.s.b": "generalised"}, "ausmtId": "au.s.b", "lat": -24.9, "lon": 117.3, "flag": None},
        # withheld: null coords, marked '(withheld)'.
        {"map": {"au.s.c": "withheld"}, "ausmtId": "au.s.c", "lat": None, "lon": None, "flag": None},
        # exact station in a corpus that HAS non-exact siblings (map non-empty but this id absent).
        {"map": {"au.s.b": "generalised"}, "ausmtId": "au.s.a", "lat": 1.0, "lon": 2.0, "flag": None},
        # the coord-PARSE QC flag is a separate fact, appended AND independent of policy.
        {"map": {}, "ausmtId": "au.s.a", "lat": -24.9024, "lon": 117.3312, "flag": True},
    ]
    got = _run_node(tmp_path, _marker_driver(), cases)
    assert got[0]["pol"] == "exact" and "(exact)" in got[0]["text"]
    assert got[1]["pol"] == "generalised" and "(generalised)" in got[1]["text"]
    # the generalised value renders VERBATIM (no client re-rounding): the 0.1deg cell survives.
    assert "-24.9000, 117.3000" in got[1]["text"]
    assert got[2]["pol"] == "withheld" and "(withheld)" in got[2]["text"]
    assert got[2]["text"].startswith("-, - (withheld)")
    assert got[3]["pol"] == "exact" and "(exact)" in got[3]["text"]
    assert got[4]["pol"] == "exact" and "(exact)" in got[4]["text"]
    assert "coordinate flag set" in got[4]["text"]
