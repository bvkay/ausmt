"""The test suite must decode bytes the same way on every machine, not the way the shell happens to be set.

WHY THIS EXISTS. tests/test_theme_tokens.py read index.html with a bare read-text call. That decodes with
the LOCALE codec: UTF-8 in CI, cp1252 on a default Windows shell. index.html carries UTF-8 superscript tick
labels whose lead bytes (0x81, 0x90) are undefined in cp1252, so three tests raised UnicodeDecodeError
locally while the same commit was green in CI. A suite that is red only on the maintainer's own machine
costs more than the bug it was meant to catch, because the next real red gets read as "that Windows thing
again". The sweep that fixed it touched 17 files; this test is what stops the eighteenth.

Two patterns are banned, both the same defect:

  * a text read or write with no encoding argument. Silent mis-decoding is the worse half of this: cp1252
    maps most bytes to SOMETHING, so a file can decode without raising and simply be wrong.
  * subprocess.run with text mode and no encoding. The child here is always node, which writes UTF-8; text
    mode decodes it with the locale codec, so a driver that prints a degree sign or a tick can crash, or
    mojibake a passing run into a confusing failure.

FAILS IF either pattern appears anywhere in portal/tests. The message names the file and line, so the fix is
mechanical. If a future test genuinely needs bytes, read_bytes is not matched here.

SCANS CODE ONLY. String literals and comments are blanked before matching, because the first version of this
guard flagged its own prose: a docstring that NAMES the banned call is documentation, not a defect. That
false positive is now itself pinned (test_the_guard_ignores_prose_and_still_sees_code).

Deliberately NOT checked: whether the declared encoding is utf-8 specifically. A test reading a latin-1
fixture on purpose is fine; what is not fine is leaving the choice to the environment.
"""
import io
import re
import tokenize
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
SELF = Path(__file__).name

_TEXT_IO = re.compile(r"\.(?:read_text|write_text)\(\s*\)")


def _code_only(src):
    """`src` with every string literal and comment blanked to spaces, offsets and line numbers preserved.

    Without this the scanners match their own documentation. Newlines are kept so reported line numbers
    stay true; a tokenize failure degrades to the raw source rather than silently scanning nothing.
    """
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return src
    starts, off = [], 0
    for line in src.splitlines(keepends=True):
        starts.append(off)
        off += len(line)
    blanked = list(src)
    kinds = {tokenize.STRING, tokenize.COMMENT}
    for name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):   # py3.12+ splits f-strings
        if hasattr(tokenize, name):
            kinds.add(getattr(tokenize, name))
    for t in toks:
        if t.type not in kinds:
            continue
        a = starts[t.start[0] - 1] + t.start[1]
        b = starts[t.end[0] - 1] + t.end[1]
        for i in range(a, min(b, len(blanked))):
            if blanked[i] != "\n":
                blanked[i] = " "
    return "".join(blanked)


def _py_files():
    return sorted(p for p in TESTS.glob("*.py") if p.name != SELF)


def _subprocess_calls(src):
    """(offset, call_text) for every subprocess.run(...) in src, paren-matched so multi-line calls work."""
    out = []
    for m in re.finditer(r"subprocess\.run\(", src):
        depth, end = 0, len(src)
        for k in range(m.end() - 1, len(src)):
            if src[k] == "(":
                depth += 1
            elif src[k] == ")":
                depth -= 1
                if depth == 0:
                    end = k + 1
                    break
        out.append((m.start(), src[m.start():end]))
    return out


@pytest.mark.parametrize("path", _py_files(), ids=lambda p: p.name)
def test_file_reads_declare_an_encoding(path):
    """FAILS IF a test reads or writes text without saying how to decode it."""
    code = _code_only(path.read_text(encoding="utf-8"))
    bad = [code[:m.start()].count("\n") + 1 for m in _TEXT_IO.finditer(code)]
    assert not bad, (
        f"{path.name}: {len(bad)} text read/write with no encoding argument, at line(s) "
        + ", ".join(str(ln) for ln in bad)
        + '. Add encoding="utf-8" - a bare read decodes with the locale codec (cp1252 on a default '
          "Windows shell), which is how three theme-token tests came to be red locally and green in CI.")


@pytest.mark.parametrize("path", _py_files(), ids=lambda p: p.name)
def test_subprocess_text_mode_declares_an_encoding(path):
    """FAILS IF a node driver is run in text mode with no encoding: its UTF-8 stdout would be decoded with
    the locale codec, turning a passing run into a mojibake failure on a cp1252 shell."""
    code = _code_only(path.read_text(encoding="utf-8"))
    bad = [code[:off].count("\n") + 1
           for off, call in _subprocess_calls(code)
           if "text=True" in call and "encoding=" not in call]
    assert not bad, (
        f"{path.name}: subprocess.run in text mode with no encoding at line(s) "
        + ", ".join(str(ln) for ln in bad)
        + '. Add encoding="utf-8": the child process writes UTF-8, and text mode otherwise decodes it '
          "with whatever codec the shell locale supplies.")


def test_the_guard_ignores_prose_and_still_sees_code():
    """A guard that matches nothing guards nothing, and one that matches its own documentation cries wolf.
    Pin BOTH directions on constructed samples. FAILS IF a future tidy-up breaks the detectors into no-ops,
    or re-introduces the docstring false positive that the first version of this file shipped with."""
    offending = (
        "from pathlib import Path\n"
        "import subprocess\n"
        "x = Path('a').read_text()\n"
        "r = subprocess.run(['node', 'd.js'],\n"
        "                   capture_output=True, text=True)\n")
    code = _code_only(offending)
    assert _TEXT_IO.search(code), "the read detector no longer matches a bare read-text call"
    calls = _subprocess_calls(code)
    assert len(calls) == 1, f"the subprocess scanner found {len(calls)} calls, expected 1"
    assert "text=True" in calls[0][1] and "encoding=" not in calls[0][1], \
        "the subprocess scanner no longer sees a multi-line text-mode call as encoding-less"

    # Correctly-encoded code must NOT be flagged, or the guard would be unsatisfiable.
    clean = ('x = Path("a").read_text(encoding="utf-8")\n'
             'r = subprocess.run(["node"], capture_output=True, text=True, encoding="utf-8")\n')
    clean_code = _code_only(clean)
    assert not _TEXT_IO.search(clean_code), "the detector flags a correctly-encoded read"
    assert all("encoding=" in c for _, c in _subprocess_calls(clean_code)), \
        "the scanner flags a correctly-encoded subprocess call"

    # PROSE must not be flagged. This is the exact bug the first version of this guard had: its own
    # docstring named the banned call and the parametrised test went red on this file's neighbour.
    prose = ('"""Docs that mention .read_text() and subprocess.run(x, text=True) in words."""\n'
             "# and a comment naming .read_text() too\n"
             "y = 1\n")
    prose_code = _code_only(prose)
    assert not _TEXT_IO.search(prose_code), \
        "a docstring or comment NAMING the banned call is documentation, not a defect, and must not be flagged"
    assert not _subprocess_calls(prose_code), "a docstring naming subprocess.run must not be scanned as a call"
