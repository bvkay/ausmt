"""Runs the display_grammar Node test: portal/src/state.js's fmtPeriod / fmtRange / licHuman against
the SAME worked examples the engine suite pins engine/extract/_pages.py's _fmt_period / _range /
_fmt_licence against (engine/tests/test_entity_pages.py, the B9 R1/R2/R3 block). Both sides carry the
pairs as literals, so neither can be made green by editing the other's source of truth. Skips if Node
is unavailable (CI installs Node - see .github/workflows/portal-ci.yml).

R3's DOMAIN is pinned here as well, on the engine's own leaf. The worked examples held the two helpers
to the same reading of every identifier the corpus declares; what they could not see was an identifier
it does not. The JS derived a reader's form from the CC grammar alone while _fmt_licence looks its
input up in a table built from contract/licenses.json, so a survey released under a CC id the
instrument does not carry printed "CC BY 2.0" in the workspace and "CC-BY-2.0" on its own survey page.
One identifier, two surfaces, two readings. test_the_engine_echoes_an_unrecognised_cc_id runs the
engine's rule over the same vectors display_grammar.test.js now carries for the SPA, so the domains
cannot drift apart again silently.

Executing _pages.py's source text rather than importing it: the module sibling-imports _au_outline and
_stationcheck, which need the engine's own path set up. Same idiom as test_collection_colours.py.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEST_JS = Path(__file__).resolve().parent / "display_grammar.test.js"
ENGINE = ROOT.parent / "engine" / "extract"
PAGES_PY = ENGINE / "_pages.py"
CONTRACT_PY = ENGINE / "_contract.py"

# The vectors display_grammar.test.js pins on the JS side. Left: recognised ids, which BOTH sides read
# in the human form. Right: CC-grammar ids the instrument does not carry, which BOTH sides echo.
RECOGNISED = {"CC-BY-4.0": "CC BY 4.0", "CC0-1.0": "CC0 1.0", "CC-BY-NC-SA-4.0": "CC BY-NC-SA 4.0",
              "CC-BY-3.0-AU": "CC BY 3.0 AU", "CC-BY-SA-4.0": "CC BY-SA 4.0",
              "ODBL-1.0": "ODBL-1.0", "PUBLIC DOMAIN": "PUBLIC DOMAIN"}
UNRECOGNISED = ["CC-BY-2.0", "CC0-2.0", "CC-BY-ND-2.5", "CC-BY-NC-SA-2.0", "CC-BY-4.0-NZ",
                "NOT-A-LICENCE-9.9"]


def _engine_fmt_licence():
    """The engine's own _fmt_licence, executed from _pages.py's source text."""
    ns = {"re": re}
    exec(compile(CONTRACT_PY.read_text(encoding="utf-8"), str(CONTRACT_PY), "exec"), ns)  # noqa: S102
    assert "LICENSES" in ns, "engine/extract/_contract.py must define LICENSES"
    # The body sweep matches indented lines and blank lines, so it must NOT run under re.S: with
    # DOTALL a single `[ \t].*\n` runs to the last newline in the file and the "block" becomes the
    # whole module, which then fails on whatever the module's later imports need. The leading span
    # spells its own any-character class instead of borrowing the flag.
    block = re.search(r"^_CC_ID = re\.compile\([\s\S]*?^def _fmt_licence\(lic\)[^\n]*\n"
                      r"(?:[ \t][^\n]*\n|\n)*",
                      PAGES_PY.read_text(encoding="utf-8"), re.M)
    assert block, "engine/extract/_pages.py must define _CC_ID ... _fmt_licence"
    exec(compile(block.group(0), str(PAGES_PY), "exec"), ns)  # noqa: S102
    return ns["_fmt_licence"]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_display_grammar_parity():
    assert TEST_JS.exists(), "display_grammar.test.js missing"
    r = subprocess.run(["node", str(TEST_JS)], capture_output=True, text=True,
                       encoding="utf-8", cwd=str(ROOT))
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "ALL PASSED" in out, out


def test_the_engine_reads_a_recognised_licence_the_way_the_workspace_does():
    """The engine half of R3's worked examples, over the ids the instrument carries."""
    fmt = _engine_fmt_licence()
    for identifier, shown in RECOGNISED.items():
        assert fmt(identifier) == shown, (
            f"engine _fmt_licence({identifier!r}) reads {fmt(identifier)!r}; "
            f"display_grammar.test.js pins the SPA at {shown!r}")


def test_the_engine_echoes_an_unrecognised_cc_id():
    """The DOMAIN half, which nothing pinned and which the two sides disagreed on.

    FAILS IF _fmt_licence starts humanising an identifier outside contract/licenses.json without
    licHuman moving with it, or the other way about. Either way the same survey would read one way in
    the workspace and another on its own page.
    """
    fmt = _engine_fmt_licence()
    for identifier in UNRECOGNISED:
        assert fmt(identifier) == identifier, (
            f"engine _fmt_licence({identifier!r}) reads {fmt(identifier)!r}; an identifier the "
            f"instrument does not carry is echoed on both surfaces")
