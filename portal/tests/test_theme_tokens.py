"""Treatment D+ palette pin (owner-approved AuScope Style Guide palette).

The five surface/accent tokens live in a :root block that is DUPLICATED verbatim across index.html,
about.html and add-survey.html. This pins the D+ target values AND that the three copies agree, so a
future edit to one file's :root that forgets the other two fails here rather than shipping a split-brain
palette.

Each assertion states its failure criterion:

  * D+ targets — FAILS if any of the five tokens (--ink/--panel/--panel-2/--line/--copper) in any of the
    three files is not exactly its D+ value. Non-vacuous: the pre-D+ palette (--ink #13202B, --copper
    #E0782F, ...) would trip every line.
  * cross-file parity — FAILS if the five-token declaration is not byte-identical across the three files.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent   # portal/
FILES = [ROOT / "index.html", ROOT / "about.html", ROOT / "add-survey.html"]

DPLUS = {
    "--ink": "#11182D",
    "--panel": "#18213D",
    "--panel-2": "#1E2B4F",
    "--line": "#2B3557",
    "--copper": "#EF7256",
}


def _token(css, name):
    m = re.search(re.escape(name) + r"\s*:\s*(#[0-9A-Fa-f]{6})", css)
    assert m, f"{name} not found"
    return m.group(1).upper()


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_dplus_targets(path):
    css = path.read_text()
    for name, want in DPLUS.items():
        assert _token(css, name) == want, f"{path.name}: {name} is {_token(css, name)}, want {want}"


def test_cross_file_parity():
    seen = {p.name: {n: _token(p.read_text(), n) for n in DPLUS} for p in FILES}
    ref = seen[FILES[0].name]
    for name, vals in seen.items():
        assert vals == ref, f"{name} :root tokens diverge from {FILES[0].name}: {vals} != {ref}"
