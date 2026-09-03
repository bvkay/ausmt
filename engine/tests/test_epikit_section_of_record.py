"""The EPI-KIT section of record: which >=MTSECT block an EDI's transfer function comes from.

An EPI-KIT file records its solution TWICE OVER. One >=MTSECT block carries the averaged solution,
named <DATAID>_avg, and after it come the per-frequency realisations the processor's own
"EstimationsPerFrequency" setting produced, named XPR-0 to XPR-n. The averaged block is the transfer
function of record; the realisations are its inputs, and the late ones are mostly the EMPTY sentinel.

mt_metadata reads a multi-section file by scanning EVERY data block in it and keeping the LAST value
it meets for each label (io/edi/edi.py::_read_mt rebinds data_dict[key] on each new block header), so
the parse returns the FINAL realisation and nothing says so. Measured across the three GSSA EPI-KIT
packages (932 files, 2026-09-03): the reader returned the averaged block 0 times out of 75 sampled
and the last realisation 75 times; on copper-coast-2020 that is 440 of 3847 impedance values, with
four stations left holding no resistivity at all.

The rule these tests pin: when a file carries more than one section, the reader returns the section
named <DATAID>_avg, else the section named for the DATAID, else the FIRST section. It is applied by
conditioning a TEMPORARY COPY that keeps the head, the info block, the measurement definitions and
exactly the chosen section, exactly as the >INFO delimiter and impedance-block fallbacks do. The
custodian's file is never touched, and what AusMT serves stays byte-identical to what was released.
"""
import re
import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FIX = HERE / "fixtures" / "epikit"
sys.path[:0] = [str(ROOT), str(ROOT / "extract")]

import _mtm as mtm  # noqa: E402

TWO_SECTION = FIX / "copper-two-section.edi"          # Wp01_avg then XPR-0, both fully populated
NO_AVG = FIX / "copper-no-avg-section.edi"            # XPR-0 then XPR-99, no solution of record
SINGLE = ROOT / "data" / "sample-survey" / "transfer_functions" / "edi" / "Vulcan_A1.edi"

# The two sections' own ZXYR blocks, read off the fixture text rather than restated here, so the
# expectation cannot drift from the bytes the test reads.
_BLOCK = re.compile(r"^>ZXYR\b[^\n]*\n([^>]*)", re.MULTILINE)


def _section_zxyr(path, sectid):
    """The ZXYR values written in ONE named section of an EDI, as floats in file order."""
    text = path.read_text(encoding="utf-8")
    starts = [m.start() for m in re.finditer(r"^>=MTSECT", text, re.MULTILINE)]
    for n, start in enumerate(starts):
        stop = starts[n + 1] if n + 1 < len(starts) else len(text)
        chunk = text[start:stop]
        if re.search(rf"SECTID\s*=\s*\"?{re.escape(sectid)}\"?\s*$", chunk, re.MULTILINE):
            return [float(v) for v in _BLOCK.search(chunk).group(1).split()]
    raise AssertionError(f"{path.name} carries no section {sectid!r}")


def _read_zxyr(path):
    tf = mtm.read(Path(path))
    assert tf.has_impedance(), f"{path.name}: the parse returned no impedance at all"
    return [float(v) for v in tf.impedance.data[:, 0, 1].real]


def test_the_fixture_really_carries_two_distinct_solutions():
    """The fixture is only evidence if the two sections actually disagree. Both blocks are fully
    populated here on purpose: a reader could pass the test below by preferring whichever block holds
    data, and this is what forbids that reading of the result."""
    avg = _section_zxyr(TWO_SECTION, "Wp01_avg")
    xpr = _section_zxyr(TWO_SECTION, "XPR-0")
    assert len(avg) == len(xpr) == 7
    assert all(v not in (0.0, 1.0e32) for v in avg + xpr), (avg, xpr)
    assert all(a != b for a, b in zip(avg, xpr)), list(zip(avg, xpr))


def test_read_returns_the_averaged_section_not_the_last_one():
    """R1, the defect itself. FAILS IF the parse returns the last section the reader met (XPR-0 here,
    XPR-99 in the custodian's file) instead of the averaged solution of record."""
    assert _read_zxyr(TWO_SECTION) == _section_zxyr(TWO_SECTION, "Wp01_avg")


def test_the_choice_is_recorded_with_the_count_it_dropped():
    """A selection nobody can see is a silent rewrite. The parse facts carry the SECTID taken and how
    many sections were left behind, so the choice travels into station.json and build_report."""
    _tf, _reason, facts = mtm.read_with_parse_facts(TWO_SECTION)
    assert facts["section_selected"] == {"sectid": "Wp01_avg", "sections_dropped": 1}


def test_with_no_averaged_section_the_first_one_stands():
    """The rule's last clause, and its negative control: this file names no <DATAID>_avg section and
    no section for its DATAID, so the FIRST section is the one that stands. FAILS IF the reader falls
    back to the last section, which here holds nothing but the EMPTY sentinel."""
    assert _read_zxyr(NO_AVG) == _section_zxyr(NO_AVG, "XPR-0")
    _tf, _reason, facts = mtm.read_with_parse_facts(NO_AVG)
    assert facts["section_selected"] == {"sectid": "XPR-0", "sections_dropped": 1}


def test_a_single_section_edi_is_untouched():
    """The inertness control, on the repo's own vendored fixture: a file carrying ONE section takes no
    conditioning at all, records no selection, and reads exactly what it reads today."""
    assert SINGLE.read_text(encoding="utf-8").count(">=MTSECT") == 1
    tf, reason, facts = mtm.read_with_parse_facts(SINGLE)
    assert reason is None
    assert "section_selected" not in facts
    assert [float(v) for v in tf.impedance.data[:, 0, 1].real] == _read_zxyr(SINGLE)


def test_the_source_file_is_never_edited(tmp_path):
    """D1. The conditioning happens on a temporary copy that is destroyed inside the read; the bytes
    on disk are the custodian's before and after, and the TF points back at them."""
    work = tmp_path / TWO_SECTION.name
    shutil.copy2(TWO_SECTION, work)
    before = work.read_bytes()
    tf, _reason, _facts = mtm.read_with_parse_facts(work)
    assert work.read_bytes() == before
    assert Path(tf.fn) == work, f"the TF must point at the custodian's file, not a scratch copy: {tf.fn}"


def test_the_conditioned_copy_keeps_the_head_and_the_measurements():
    """The normaliser's own contract, stated over bytes: the copy keeps the head, the info block, the
    measurement definitions and exactly ONE section, and drops the realisations. Everything the
    station record needs beyond the impedance (coordinates, channel ids, the processing metadata the
    build scrapes) lives outside the sections and must survive."""
    raw = TWO_SECTION.read_bytes()
    kept = mtm.keep_single_section(raw, "Wp01_avg")
    assert kept.count(b">=MTSECT") == 1
    assert b"SECTID=Wp01_avg" in kept and b"SECTID=XPR-0" not in kept
    for marker in (b">HEAD", b"DATAID=Wp01", b">INFO", b">=DEFINEMEAS", b"REFLAT=", b">HMEAS",
                   b">EMEAS", b">END"):
        assert marker in kept, marker
    assert mtm.keep_single_section(raw, "XPR-0").count(b">=MTSECT") == 1


def test_the_normaliser_returns_the_original_bytes_for_a_single_section_file():
    """The fourth guard the reader's other fallbacks all carry: conditioning that changes nothing is
    not conditioning, and the caller must be able to tell. Identity, not equality."""
    raw = SINGLE.read_bytes()
    assert mtm.keep_single_section(raw, mtm.section_of_record(raw)[0]) is raw


def test_the_selection_rule_prefers_avg_then_the_dataid_then_the_first():
    """The rule as a rule, over minted section listings rather than one file's accident of ordering."""
    def pick(dataid, sectids):
        raw = ("\n".join([">HEAD", f"    DATAID={dataid}", ">=DEFINEMEAS"]
                         + [f">=MTSECT\n    SECTID={s}\n>FREQ NFREQ=1 // 1\n  1.0" for s in sectids]
                         + [">END", ""])).encode("utf-8")
        return mtm.section_of_record(raw)
    assert pick("MT01", ["XPR-0", "MT01_avg", "MT01"]) == ("MT01_avg", 1, 3)
    assert pick("MT01", ["XPR-0", "MT01", "XPR-1"]) == ("MT01", 1, 3)
    assert pick("MT01", ["XPR-0", "XPR-1"]) == ("XPR-0", 0, 2)
    assert pick("MT01", ["MT01_avg"]) == ("MT01_avg", 0, 1)
