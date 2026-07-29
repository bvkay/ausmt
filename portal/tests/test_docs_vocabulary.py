"""House vocabulary for the documentation corpus: time series, never "waveform".

"Waveform" is seismology's word for a recorded trace. Magnetotellurics records time series of
electric and magnetic field components, and the MT literature, the MTH5 specification and
mt_metadata all say "time series". Two lines of docs/docs/index.md's out-of-scope section had
drifted into the seismic term ("AusMT is not a waveform archive", "the portal links to the
waveforms without duplicating them"), which reads as borrowed vocabulary to the exact audience
AusMT is for. Both lines now say time series.

The rule is worth pinning rather than just fixing because the drift is easy to repeat: FDSN and
seismic-adjacent prose is a common source when writing about linking out to national facilities,
and one paste puts the word back. This scan FAILS if "waveform" (any case, any inflection)
appears anywhere under docs/docs/.

RED-proven: run against the parent commit and it reports docs/docs/index.md:44 and :47.

The scan reads the mkdocs content tree ONLY, never portal/, so this module's own prose can name
the word it forbids without exempting itself.

DELIBERATE ALLOWANCE, none today. If a future passage genuinely needs the word (an explicit FDSN
comparison, say, or quoting an external schema field named `waveform`), add the file to _ALLOWED
below WITH the justification, in the same commit as the passage. The point of the pin is that the
word can only enter on purpose.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent    # portal/
DOCS = ROOT.parent / "docs" / "docs"             # the mkdocs content tree

FORBIDDEN = re.compile("waveform", re.IGNORECASE)

# path (relative to docs/docs) -> why the word is allowed there. Empty on purpose.
_ALLOWED: dict[str, str] = {}


def _markdown_files():
    files = sorted(p for p in DOCS.rglob("*.md"))
    assert files, f"no markdown found under {DOCS}; the scan would pass vacuously"
    return files


def test_docs_say_time_series_not_the_seismic_word():
    hits = []
    for p in _markdown_files():
        rel = p.relative_to(DOCS).as_posix()
        if rel in _ALLOWED:
            continue
        for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
            if FORBIDDEN.search(line):
                hits.append(f"docs/docs/{rel}:{lineno}: {line.strip()[:160]}")
    assert not hits, (
        "the documentation must say 'time series', not the seismic term, for MT recordings. Found:\n"
        + "\n".join(hits)
        + "\n\nIf a passage genuinely needs the word (an FDSN comparison, an external field name), add "
          "its path to _ALLOWED in this module with the justification, in the same commit.")


def test_the_scan_reaches_the_page_that_carried_the_drift():
    """Guards the guard: the scan passes trivially if its file walk collects nothing, so pin that it
    reaches index.md (which held both original occurrences) and a nested page."""
    seen = {p.relative_to(DOCS).as_posix() for p in _markdown_files()}
    for expected in ("index.md", "interoperability/external-archives.md"):
        assert expected in seen, f"the vocabulary scan must cover {expected}; it walked {sorted(seen)}"


def test_index_states_the_out_of_scope_rule_in_house_vocabulary():
    """Over-deletion guard. The fix must keep the claim, not drop it: AusMT still has to tell a reader
    it does not hold the raw recordings and links out instead."""
    raw = (DOCS / "index.md").read_text(encoding="utf-8")
    assert "## Out of scope" in raw, "index.md must keep its out-of-scope section"
    body = raw.split("## Out of scope", 1)[1].split("\n## ", 1)[0]
    flat = re.sub(r"\s+", " ", body)
    assert "Time series remain in their original repositories" in flat, (
        "index.md must still say the raw recordings stay with their original repositories")
    assert "links to the time series without duplicating them" in flat, (
        "index.md must still say AusMT links out rather than copying")
