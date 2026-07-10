"""C43-S2a fix round F3: EXECUTABLE JS↔Python parity pins for the Stations-tab classification and
URL construction (modelled on portal/tests/test_interactions.py's node-driver pattern).

WHY EXECUTABLE: the fix round's F1 (JS truncated `%` vs Python floored `%` on negatives — 362 trueYx
mismatches and a verdict flip at stored≈−0.05) SHIPPED PAST the source-string parity pin, which only
asserted the JS *contains* certain substrings. These pins EXECUTE the extracted JS functions in Node
and compare against gateway.phaseqc (the authoritative spec) over a boundary-heavy vector set, so a
semantics divergence — not just a missing substring — goes red.

Node dependency posture (stated for the gate): pure `node` only — NO jsdom, NO npm install, no new
deps (the extracted functions are DOM-free). Local dev box: node v22 present. Gateway CI
(gateway-ci.yml, ubuntu-latest): node is preinstalled on GitHub-hosted runners, so these pins RUN in
CI. If node were ever absent, the pytest.skip reason below is deliberately NOT on the gateway lane's
skip-tripwire allow-list (engine/tests/ci_check_skips.py --allow "real engine stack / ..."), so the
lane would fail LOUDLY rather than silently hollowing these pins out — the house tripwire posture.

Vector-set note: the sweep uses 0.5°-step values plus 2dp seam values (0, ±0.05, ±90, ±180, …).
Exact x.25-style binary-representable decimal halves are deliberately excluded — Python round() is
round-half-even while JS Math.round is half-up, and the pin exists to catch MODULO/BAND semantics
divergence, not decimal-rounding-convention differences on inputs the 1dp tf.json data cannot carry.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from gateway import curatorpage, phaseqc

NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    NODE is None,
    reason="node not present — executable JS parity pins need the node binary "
           "(deliberately NOT on the gateway skip-tripwire allow-list: absent node in CI must red the lane)")


# --------------------------------------------------------------------------------------------------
# JS extraction helpers (brace-balanced, so multi-line functions extract whole)
# --------------------------------------------------------------------------------------------------
def _extract_js_function(js: str, name: str) -> str:
    marker = f"function {name}("
    i = js.find(marker)
    assert i >= 0, f"function {name} not found in STATIONS_JS"
    j = js.find("{", i)
    depth = 0
    for k in range(j, len(js)):
        if js[k] == "{":
            depth += 1
        elif js[k] == "}":
            depth -= 1
            if depth == 0:
                return js[i:k + 1]
    raise AssertionError(f"unbalanced braces extracting {name} from STATIONS_JS")


def _extract_constants(js: str) -> str:
    m = re.search(r"var YX_SHIFT[^;]*;", js)
    assert m, "the phase-constant declaration (var YX_SHIFT = ...) not found in STATIONS_JS"
    return m.group(0)


def _run_node(tmp_path, driver_js: str, payload) -> dict:
    drv = tmp_path / "parity_driver.mjs"
    vec = tmp_path / "vectors.json"
    drv.write_text(driver_js, encoding="utf-8")
    vec.write_text(json.dumps(payload), encoding="utf-8")
    r = subprocess.run([NODE, str(drv), str(vec)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"node driver failed:\n{r.stdout}\n{r.stderr}"
    return json.loads(r.stdout)


def _sweep_vectors() -> list:
    """Full ±360 sweep at 0.5° steps plus the seam values the fix round names (0, −0.05, ±90, ±180)
    and their near-boundary neighbours (band edges ± slack edges)."""
    vals = [x / 2.0 for x in range(-720, 721)]                       # -360.0 .. 360.0 step 0.5
    vals += [0.0, -0.05, 0.05, 90.0, -90.0, 180.0, -180.0,
             -0.1, 0.1, 89.95, 90.05, -89.95, -90.05, 179.95, -179.95,
             10.0, -10.0, 100.0, -100.0, 99.95, 100.05, -190.0, -80.0,
             -10.05, -9.95, 109.95, 110.05]                          # slack-edge probes
    return vals


# --------------------------------------------------------------------------------------------------
# F1: wrap180 / trueYx / inQ1 / inQ3 parity (executable — Node vs phaseqc)
# --------------------------------------------------------------------------------------------------
def test_js_wrap180_trueyx_quadrant_parity_sweep(tmp_path):
    """EXECUTABLE PARITY (F1). The extracted STATIONS_JS wrap180/trueYx/inQ1/inQ3 must agree EXACTLY
    with phaseqc over the full ±360 sweep + seam values. FAILS IF the JS modulo/band semantics diverge
    from the Python spec anywhere in the domain — in particular the truncated-% bug: JS `%` keeps the
    dividend's sign, so a negative stored t[4] (exactly the wrong-convention stations this feature
    exists to catch) unwraps to the wrong value and flips the verdict (shown red against the pre-fix
    JS: 362 trueYx mismatches, verdict flip at stored≈−0.05)."""
    js = curatorpage.STATIONS_JS
    driver = (
        "import { readFileSync } from 'fs';\n"
        + _extract_constants(js) + "\n"
        + _extract_js_function(js, "floormod") + "\n"
        + _extract_js_function(js, "wrap180") + "\n"
        + _extract_js_function(js, "trueYx") + "\n"
        + _extract_js_function(js, "mapYx") + "\n"
        + _extract_js_function(js, "inQ1") + "\n"
        + _extract_js_function(js, "inQ3") + "\n"
        + """
const vectors = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const out = vectors.map(function (v) {
  return { v: v, trueYx: trueYx(v), inQ1: inQ1(v), inQ3: inQ3(v) };
});
process.stdout.write(JSON.stringify(out));
""")
    vectors = _sweep_vectors()
    got = _run_node(tmp_path, driver, vectors)
    mismatches = []
    for row in got:
        v = row["v"]
        exp_true = phaseqc.true_phi_yx(v)
        exp_q1 = phaseqc.in_quadrant_xy(v)
        exp_q3 = phaseqc.in_quadrant_yx(v)
        if row["trueYx"] != exp_true or row["inQ1"] != exp_q1 or row["inQ3"] != exp_q3:
            mismatches.append(
                f"stored={v}: JS trueYx={row['trueYx']} inQ1={row['inQ1']} inQ3={row['inQ3']} "
                f"!= py trueYx={exp_true} inQ1={exp_q1} inQ3={exp_q3}")
    assert not mismatches, (
        f"{len(mismatches)} JS/Python mismatches over {len(vectors)} vectors; first 8:\n"
        + "\n".join(mismatches[:8]))


# --------------------------------------------------------------------------------------------------
# F2: URL construction parity (executable — absolute /data/... URLs, tricky slug/id encoding)
# --------------------------------------------------------------------------------------------------
def test_js_data_urls_absolute(tmp_path):
    """EXECUTABLE URL PIN (F2). The extracted STATIONS_JS dataUrl/stationJsonUrl must produce the
    exact expected ABSOLUTE strings for a tricky slug/id (space, plus, hash — hash unencoded would
    truncate the URL at a fragment). ALSO asserts (source-level) that EVERY fetchJson target in the
    JS is absolute (/data/... or a variable built from these helpers). FAILS IF any fetch is
    page-relative — from /gateway/curator/survey/<slug> a relative 'data/...' resolves to
    /gateway/curator/survey/data/... → 404 → the whole Stations tab is dead (the shipped pre-fix
    state, shown red)."""
    js = curatorpage.STATIONS_JS
    # Source-level half: every literal fetchJson('...') target must start /data/.
    literals = re.findall(r"fetchJson\('([^']+)'", js)
    relative = [u for u in literals if not u.startswith("/data/")]
    assert not relative, f"page-relative fetch targets in STATIONS_JS (dead in deployment): {relative}"
    # Executable half: the URL helpers produce exactly the expected absolute encoded strings.
    driver = (
        "import { readFileSync } from 'fs';\n"
        + _extract_js_function(js, "dataUrl") + "\n"
        + _extract_js_function(js, "stationJsonUrl") + "\n"
        + """
const out = {
  cat: dataUrl('catalogue.json'),
  tf: dataUrl('tf.json'),
  station: stationJsonUrl('my survey+2026', 'S01 A#7'),
};
process.stdout.write(JSON.stringify(out));
""")
    got = _run_node(tmp_path, driver, {})
    assert got["cat"] == "/data/catalogue.json", got
    assert got["tf"] == "/data/tf.json", got
    assert got["station"] == "/data/products/my%20survey%2B2026/S01%20A%237/station.json", got


# --------------------------------------------------------------------------------------------------
# F4d: classify (slack + median) parity (executable — series semantics, seam-straddling medians)
# --------------------------------------------------------------------------------------------------
def test_js_classify_median_parity(tmp_path):
    """EXECUTABLE SERIES PARITY (F4d). The extracted STATIONS_JS classify (slack-widened per-point
    flags + seam-mapped median + median-vs-band verdict) must agree exactly with
    phaseqc.classify_series over boundary-heavy series, including a yx cluster straddling the ±180
    seam (where a naive median of (−180,180]-wrapped values is catastrophically wrong). FAILS IF the
    JS median/slack semantics diverge from the pinned Python spec."""
    js = curatorpage.STATIONS_JS
    driver = (
        "import { readFileSync } from 'fs';\n"
        + _extract_constants(js) + "\n"
        + _extract_js_function(js, "floormod") + "\n"
        + _extract_js_function(js, "wrap180") + "\n"
        + _extract_js_function(js, "trueYx") + "\n"
        + _extract_js_function(js, "mapYx") + "\n"
        + _extract_js_function(js, "inQ1") + "\n"
        + _extract_js_function(js, "inQ3") + "\n"
        + _extract_js_function(js, "medianOf") + "\n"
        + _extract_js_function(js, "classify") + "\n"
        + """
const cases = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const out = cases.map(function (c) { return classify(c.values, c.mode); });
process.stdout.write(JSON.stringify(out));
""")
    def _stored_for_true_yx(t):
        return round(phaseqc.wrap180(t + phaseqc.YX_PRESENTATION_SHIFT_DEG), 1)

    cases = [
        # xy: in-band, slack-band, and beyond-slack points; median inside the band.
        {"mode": "xy", "values": [10.0, 45.0, 95.0, -5.0, 200.0, None]},
        # xy: median beyond band+slack (coherent wrong quadrant).
        {"mode": "xy", "values": [-120.0, -130.0, -140.0]},
        # yx: healthy Q3 cluster (stored values for true -135/-100/-170).
        {"mode": "yx", "values": [_stored_for_true_yx(t) for t in (-135.0, -100.0, -170.0)]},
        # yx: SEAM-STRADDLING cluster — true values -179, -178, +179 (stored 1.0, 2.0, -1.0). A naive
        # (-180,180] median would average across the seam; the engine's (-360,0] mapping keeps it sane.
        {"mode": "yx", "values": [_stored_for_true_yx(t) for t in (-179.0, -178.0, 179.0)]},
        # yx: coherent wrong quadrant (true +45/+30 => stored -135/-150).
        {"mode": "yx", "values": [_stored_for_true_yx(t) for t in (45.0, 30.0)]},
        # yx: slack-edge points (true -85 => within slack; true -75 => beyond slack).
        {"mode": "yx", "values": [_stored_for_true_yx(t) for t in (-85.0, -75.0, -135.0)]},
        # all-None: no verdict.
        {"mode": "xy", "values": [None, None]},
    ]
    got = _run_node(tmp_path, driver, cases)
    for i, case in enumerate(cases):
        exp = phaseqc.classify_series(case["values"], mode=case["mode"])
        g = got[i]
        assert g["points"] == exp["points"], (i, case, g, exp)
        assert g["any_out"] == exp["any_out"], (i, case, g, exp)
        assert g["n"] == exp["n_classified"], (i, case, g, exp)
        assert g["median"] == exp["median"], (i, case, g["median"], exp["median"])
        assert g["medianIn"] == exp["median_in"], (i, case, g, exp)
