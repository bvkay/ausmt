"""coords_of() — the light coordinate read for AusLAMP state-bucketing / QC, built from only the
KEPT coord helpers (read_norm/grab/parse_angle/info_coords). Dependency-free; runs in the core suite.

Also covers the Phoenix DATAID / processing-note helpers (parse_dataid, proc_note) that the
mt_metadata extractor relies on for station-id recovery and remote-reference scraping.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "extract"))
import _edi_catalog as cat  # noqa: E402

EDIS = sorted((HERE.parent / "data" / "sample-survey" / "transfer_functions" / "edi").glob("*.edi"))


def test_coords_of_returns_valid_coords():
    assert EDIS, "sample EDIs missing"
    for p in EDIS:
        lat, lon = cat.coords_of(p)
        assert lat is not None and lon is not None, p.name
        assert -45 <= lat <= -8 and 108 <= lon <= 156, (p.name, lat, lon)  # AU bbox (sample survey)


def test_parse_dataid_phoenix_compound():
    # Phoenix remote-reference DATAID -> (real station, remote site); plain ids pass through.
    assert cat.parse_dataid("P=2027 R=K20_RR (H)") == ("2027", "K20_RR")
    assert cat.parse_dataid("P=2031 R=KK_RR (H)") == ("2031", "KK_RR")
    assert cat.parse_dataid("MBI21") == ("MBI21", None)
    assert cat.parse_dataid("Vulcan_A1") == ("Vulcan_A1", None)
    assert cat.parse_dataid("") == ("", None)
    assert cat.parse_dataid(None) == (None, None)


def test_proc_note_extracts_remote_and_cleans():
    # remote site from the DATAID; INFO block becomes the note with mojibake cleaned.
    text = '>HEAD\nDATAID="P=2027 R=K20_RR (H)"\n>INFO MAXINFO=2\nROBUST ALGORITHM: x\nDECLINATION: 7.5Â°\n>END\n'
    note, remote = cat.proc_note(text, 'P=2027 R=K20_RR (H)')
    assert remote == "K20_RR"
    assert note and "ROBUST ALGORITHM" in note and "Â°" not in note  # mojibake cleaned


def test_proc_note_redacts_email():
    # C3 (PII scrub): a real operator email in the raw >INFO free text (this has happened in
    # committed sample data, e.g. a curator's institutional address) must never survive into the
    # returned note, which build_portal writes verbatim into the PUBLIC station.json
    # processing.note (not licence-gated). Conservative regex; only the email token is replaced,
    # nothing else in the note is altered, and the (note, remote) contract is unchanged.
    text = ('>HEAD\nDATAID="A01"\n>INFO MAXINFO=3\n'
            'Contact: Contact.Person@example.gov.au for queries\nProcessing code: LEMIMT\n>END\n')
    note, remote = cat.proc_note(text, "A01")
    assert note is not None
    assert "Contact.Person@example.gov.au" not in note, note      # the raw address must not survive
    assert "[email removed]" in note, note                 # replaced with the redaction marker
    assert "Processing code: LEMIMT" in note               # rest of the note is untouched
    assert remote is None                                  # plain DATAID -> remote contract unchanged
