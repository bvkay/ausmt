"""C43 Stage-3b F: EXECUTABLE JS<->Python parity pin for the candidate-picker filter (record A3, pin
10). The standing lane rule (from the Stage-2a stations-JS lesson, record D14): browser JS gets
EXECUTABLE test coverage from the start — string-only pins are banned, because a source-substring
assertion cannot catch a SEMANTICS divergence (the S2a truncated-`%` bug shipped past exactly such a
pin).

This EXTRACTS the DOM-free `matchRow(filterText, query)` from COLLECTIONS_JS, runs it in Node over a
boundary-heavy vector set, and compares against the authoritative Python reference `_match_row`. A
divergence — trim/case/substring/empty-query semantics — goes red.

Node posture (stated for the gate): pure `node`, no npm/jsdom (matchRow is DOM-free). Local dev box:
node present. Gateway CI: node preinstalled on GitHub-hosted runners. If node were ever absent the
skip below is deliberately NOT on the lane's skip-tripwire allow-list, so the lane fails LOUDLY rather
than silently hollowing this pin out (the house posture).
"""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from gateway import curatorpage

NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    NODE is None,
    reason="node not present — executable JS parity pin needs the node binary "
           "(deliberately NOT on the gateway skip-tripwire allow-list: absent node in CI must red the lane)")


def _extract_js_function(js: str, name: str) -> str:
    marker = f"function {name}("
    i = js.find(marker)
    assert i >= 0, f"function {name} not found in COLLECTIONS_JS"
    j = js.find("{", i)
    depth = 0
    for k in range(j, len(js)):
        if js[k] == "{":
            depth += 1
        elif js[k] == "}":
            depth -= 1
            if depth == 0:
                return js[i:k + 1]
    raise AssertionError(f"unbalanced braces extracting {name} from COLLECTIONS_JS")


def _match_row(filter_text, query) -> bool:
    """The authoritative Python spec the extracted JS matchRow must equal: case-insensitive substring
    of the whitespace-joined 'slug currentCollectionId', empty/whitespace query matches everything."""
    q = ("" if query is None else str(query)).strip().lower()
    if q == "":
        return True
    return q in ("" if filter_text is None else str(filter_text)).lower()


def _run_node(tmp_path, driver_js: str, payload):
    drv = tmp_path / "cand_filter_driver.mjs"
    vec = tmp_path / "vectors.json"
    drv.write_text(driver_js, encoding="utf-8")
    vec.write_text(json.dumps(payload), encoding="utf-8")
    r = subprocess.run([NODE, str(drv), str(vec)], capture_output=True, text=True,
                       encoding="utf-8", timeout=60)
    assert r.returncode == 0, f"node driver failed:\n{r.stdout}\n{r.stderr}"
    return json.loads(r.stdout)


# Boundary-heavy (filterText, query) pairs: empty/whitespace queries, case, leading/trailing space,
# a hit on the slug half vs the current-collection half, a non-match, a substring that spans the join.
_CASES = [
    ["auslamp-sa-gawler-2014 auslamp", ""],
    ["auslamp-sa-gawler-2014 auslamp", "   "],
    ["auslamp-sa-gawler-2014 auslamp", "GAWLER"],
    ["auslamp-sa-gawler-2014 auslamp", "  gawler  "],
    ["auslamp-sa-gawler-2014 auslamp", "auslamp"],
    ["capricorn-2010 capricorn", "capricorn"],
    ["capricorn-2010 capricorn", "CAPRICORN"],
    ["burra-2017 ", "no-such"],
    ["burra-2017 ", "burra"],
    ["central-delamerian-2020 ", "delamerian"],
    ["cooper-basin-2019 ", "2019"],
    ["cooper-basin-2019 ", "COOPER-basin"],
    ["x ", "x y"],
    ["", "anything"],
    ["", ""],
]


def test_js_matchrow_parity_against_python_spec(tmp_path):
    """EXECUTABLE PARITY (pin 10). The extracted COLLECTIONS_JS matchRow must agree EXACTLY with
    _match_row over the boundary set. FAILS IF the JS trim/case/substring/empty-query semantics diverge
    from the Python spec anywhere — a real semantics bug, not just a missing substring."""
    js = curatorpage.COLLECTIONS_JS
    driver = (
        "import { readFileSync } from 'fs';\n"
        + _extract_js_function(js, "matchRow") + "\n"
        + """
const cases = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const out = cases.map(function (c) { return matchRow(c[0], c[1]); });
process.stdout.write(JSON.stringify(out));
""")
    got = _run_node(tmp_path, driver, _CASES)
    want = [_match_row(ft, q) for ft, q in _CASES]
    assert got == want, (
        "JS matchRow diverged from the Python spec:\n"
        + "\n".join(f"  {c!r}: js={g} py={w}"
                    for c, g, w in zip(_CASES, got, want) if g != w))
