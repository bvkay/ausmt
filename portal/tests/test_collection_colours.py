"""Collection member colours, pinned on BOTH sides of the pair they are supposed to keep together.

A collection is drawn twice - as the static collection page's scatter (engine/extract/_pages.py
_member_colours) and as the SPA's collScatter (portal/src/state.js memberColours) - and a reader moving
between them is entitled to find the same survey the same colour. Past the shared eight-entry palette both
stop cycling (which gave two surveys one colour and made the legend useless) and lay the same evenly spaced
hue ramp.

TWO TESTS, ONE PAIR OF VECTORS. The first runs the Node driver, which carries the expected lists as
literals on the JS side. The second runs the ENGINE's own rule against the SAME literals. Without the
second, the parity was one-sided: editing _pages.py's ramp constants (the 0.62 / 0.46 lightness bands, the
0.58 saturation, the i/n hue step or the rounding) left both suites green while the two surfaces diverged,
because the engine's own test asserts only that fourteen members get fourteen DISTINCT colours and that the
result is deterministic - never a hex value. That is the exact defect this parity exists to remove.

WHY THE ENGINE HALF LIVES HERE rather than in engine/tests. Same reason test_type_palette_separability.py
carries the _TYPE_COL parity: portal-ci runs on portal/** AND on engine/extract/_pages.py (see
.github/workflows/portal-ci.yml), so a change to either half fires this module. The engine workflow triggers on
engine/** alone and cannot see a state.js edit.

The rule is EXECUTED, not re-implemented: the two definitions are lifted out of _pages.py's source text and
run, so a constant edited there changes what this test computes. _pages.py cannot simply be imported - it
sibling-imports _au_outline and _stationcheck, which need the engine's own path set up - and re-typing the
ramp in this file would only pin a third copy of it.

Skips the Node half if Node is unavailable (CI installs Node - see .github/workflows/portal-ci.yml)."""
import colorsys
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEST_JS = Path(__file__).resolve().parent / "collection_colours.test.js"
PAGES_PY = ROOT.parent / "engine" / "extract" / "_pages.py"

# The three member counts contract C7 names: 8 is the last count the shared palette covers, 9 is the first
# that must fall through to the ramp, 14 is a real AusLAMP-scale collection. These are the SAME literals
# collection_colours.test.js carries for the JS side; the two lists are the parity.
EXPECTED = {
    8: ["#2E8FA3", "#EF7256", "#8A5FC0", "#5BAE6A", "#3F6FC4", "#C255A0", "#D9A23B", "#A85454"],
    9: ["#D66666", "#B98C31", "#B1D666", "#31B931", "#66D6B1", "#318CB9", "#6666D6", "#8C31B9",
        "#D666B1"],
    14: ["#D66666", "#B96C31", "#D6C666", "#92B931", "#86D666", "#31B945", "#66D6A6", "#31B9B9",
         "#66A6D6", "#3145B9", "#8666D6", "#9231B9", "#D666C6", "#B9316C"],
}


def _engine_member_colours():
    """The engine's own _member_colours, executed from _pages.py's source text."""
    src = PAGES_PY.read_text(encoding="utf-8")
    pal = re.search(r"^_COLL_PAL\s*=\s*\(.*?\)$", src, re.M)
    assert pal, "engine/extract/_pages.py must define `_COLL_PAL = (...)` on one line"
    fn = re.search(r"^def _member_colours\(n\):\n(?:[ \t].*\n|\n)*", src, re.M)
    assert fn, "engine/extract/_pages.py must define `def _member_colours(n):`"
    ns = {"colorsys": colorsys}
    exec(compile(pal.group(0) + "\n\n" + fn.group(0), str(PAGES_PY), "exec"), ns)  # noqa: S102
    return ns["_member_colours"]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_collection_colour_parity():
    assert TEST_JS.exists(), "collection_colours.test.js missing"
    r = subprocess.run(["node", str(TEST_JS)], capture_output=True, text=True,
                       encoding="utf-8", cwd=str(ROOT))
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "ALL PASSED" in out, out


def test_the_engine_half_of_the_parity_carries_the_same_vectors():
    """The PYTHON side of the pair, held to the lists the Node driver pins on the JS side.

    FAILS IF _pages.py's ramp moves: the palette, the two lightness bands, the saturation, the hue step or
    the rounding. Before this existed, any of those edits left every suite green and simply made the
    static page and the SPA draw one collection two ways.
    """
    member_colours = _engine_member_colours()
    for n, want in EXPECTED.items():
        got = member_colours(n)
        assert got == want, (
            f"engine _member_colours({n}) has drifted from the lists "
            f"portal/tests/collection_colours.test.js pins for the SPA.\n  want {want}\n  got  {got}")


def test_the_engine_ramp_gives_every_member_its_own_colour():
    """The property the vectors above are a witness for, asserted well past the palette's eight.

    The eight-entry palette must not cycle, or the ninth member takes the first member's colour and a legend
    could not tell two surveys apart. Distinctness is what the ramp buys; the vectors pin WHICH colours.
    """
    member_colours = _engine_member_colours()
    for n in (9, 12, 14, 20, 33):
        cols = member_colours(n)
        assert len(cols) == n, f"_member_colours({n}) returned {len(cols)} colours"
        assert len(set(cols)) == n, (
            f"a collection of {n} members needs {n} colours, got {len(set(cols))} distinct")
        assert all(re.fullmatch(r"#[0-9A-F]{6}", c) for c in cols), (
            f"colours must be six-digit uppercase hex, got {cols[:3]}")
