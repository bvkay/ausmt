"""C3 (PII scrub): an email address in a source EDI's raw >INFO block must never survive into the
DERIVED, publicly-consumed processing_note (station.json processing.note is NOT licence-gated), and
must be surfaced as a loud per-survey WARNING so a curator can look at the ORIGINAL upstream file
(which this build never mutates -- D1). This is the build_portal.process_edis() integration point;
the regex-only unit coverage for proc_note() itself lives in test_coords_of.py (stack-less lane).
"""
import re
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "extract"))
import build_portal   # noqa: E402
import _edi_catalog as cat  # noqa: E402

BASE = (HERE.parent / "data" / "sample-survey" / "transfer_functions" / "edi" / "Vulcan_A1.edi").read_text(
    encoding="latin-1")
EMAIL = "Contact.Person@example.gov.au"   # synthetic; the scrub must remove any such address


def _with_email_in_info(tmp_path):
    # Inject a contact line into the existing >INFO block (keep everything else -- MAXINFO/SITE/etc --
    # identical, so this isolates the email as the only change).
    injected = BASE.replace("  Processing code: LEMIMT",
                            f"  Contact     : {EMAIL}\n  Processing code: LEMIMT", 1)
    assert EMAIL in injected and injected != BASE, "fixture injection did not take"
    edi = tmp_path / "edi"; edi.mkdir()
    p = edi / "email_leak.edi"
    p.write_text(injected, encoding="latin-1")
    return p


def test_proc_note_email_redacted_in_build(tmp_path):
    """Direct catalog-path check (coords_of/proc_note), matching the C3 contract wording."""
    p = _with_email_in_info(tmp_path)
    raw = cat.ep.read_norm(p) if hasattr(cat, "ep") else p.read_text(encoding="latin-1")
    did = cat.grab(raw, "DATAID")
    note, _remote = cat.proc_note(raw, did)
    assert note is not None
    assert EMAIL not in note, note                # pre-fix: FAILS here, address present verbatim
    assert "[email removed]" in note, note


def test_build_redacts_note_and_warns(tmp_path, capsys):
    """Full process_edis() path: processing_note on the returned record is scrubbed, AND a per-survey
    WARNING naming the offending source file is printed to stderr (curator signal; the source EDI
    itself is never modified -- checked via untouched bytes on disk)."""
    p = _with_email_in_info(tmp_path)
    before_bytes = p.read_bytes()
    stations, tf_rows, sci_rows = build_portal.process_edis(
        [p], "EmailScrubSurvey", "TestOrg", "email-scrub-survey", "mt_metadata")
    assert len(stations) == len(tf_rows) == len(sci_rows) == 1
    _pth, r = stations[0]
    note = r.get("processing_note")
    assert note is not None
    assert EMAIL not in note, note                 # pre-fix: FAILS here, address present verbatim
    assert "[email removed]" in note, note

    err = capsys.readouterr().err
    assert re.search(r"WARNING.*EmailScrubSurvey.*email_leak\.edi", err, re.S), err   # loud curator flag
    assert p.read_bytes() == before_bytes           # D1: original EDI bytes are NEVER modified
