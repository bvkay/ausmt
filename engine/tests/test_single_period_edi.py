"""The single-period rescue: an EDI declaring NFREQ=1 is well formed and the reader is not.

`edi.EDI._assert_descending_frequency` compares `frequency[0]` with `frequency[1]` without asking
how many frequencies there are, so a one-period EDI raises IndexError before the transfer function
is ever built and the station is lost outright. Nothing in the file is wrong, which is why this
fallback conditions the READER for one read instead of conditioning a copy of the bytes the way its
two siblings do (the >INFO delimiter fallback and the impedance-block one).

The corpus has no single-period file today, so this path is unexercised there; the AusMT GDS
staging has seventy-eight, several of them AusMT-minted digitisations of published array tables
where one period is all the source printed. The same defect is fixed upstream in the mt_metadata
fork as well; this fallback exists so a corpus push never waits on a release.

Both fixtures are MINTED and name their provenance in their own >INFO block. The two-period twin is
the negative control: same station shape, one more period, and it must read exactly as it does
today with no fallback at all.
"""
import json
import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "extract"))
sys.path.insert(0, str(REPO))
import _mtm as mtm          # noqa: E402
import build_portal         # noqa: E402

ONE = HERE / "fixtures" / "single-period" / "single-period-tipper.edi"
TWO = HERE / "fixtures" / "single-period" / "two-period-tipper.edi"
REAL = REPO / "data" / "sample-survey" / "transfer_functions" / "edi" / "Vulcan_A1.edi"


def test_a_single_period_edi_reads_and_says_why_it_needed_the_fallback():
    """FAILS against the shipped reader with `IndexError: index 1 is out of bounds for axis 0 with
    size 1`. The rescue is RECORDED, never silent, and it recovers the whole station: the one
    period, the tipper the source carries and the coordinates."""
    tf, reason = mtm.read_with_fallback(ONE)
    assert reason == mtm.SINGLE_PERIOD_ORDERING_DEFECT, reason
    assert tf.period.size == 1
    assert tf.has_tipper() and not tf.has_impedance()
    assert tf.latitude == pytest.approx(-37.3167)
    assert str(tf.fn) == str(ONE)
    _per, comp = mtm.components_from_tf(tf)
    assert comp["TXR"] == [pytest.approx(0.55)]
    assert comp["TYR"] == [pytest.approx(-0.12)]


def test_the_two_period_twin_is_read_exactly_as_before_and_takes_no_fallback():
    """The negative control. One more period and the shipped path handles it, so the fallback must
    not fire: the reason is None, which is the only observable that says the reader was never
    conditioned."""
    tf, reason = mtm.read_with_fallback(TWO)
    assert reason is None, reason
    assert tf.period.size == 2
    _per, comp = mtm.components_from_tf(tf)
    assert comp["TXR"] == [pytest.approx(0.48), pytest.approx(0.55)]


def test_the_ordering_assertion_is_restored_after_the_rescue():
    """The neutralisation is installed for ONE read and removed in a finally. Pinned by identity on
    the class attribute across the rescue, because a leaked patch would silently stop reordering
    ascending-frequency files for the rest of the process - which is most of the GDS staging."""
    from mt_metadata.transfer_functions.io.edi.edi import EDI
    before = EDI._assert_descending_frequency
    mtm.read_with_fallback(ONE)
    assert EDI._assert_descending_frequency is before, \
        "the descending-frequency assertion was not put back after the rescue"


def test_an_ascending_multi_period_file_is_still_reordered_after_a_rescue_ran():
    """The consequence the previous test protects, asserted on data rather than on an attribute: an
    ORDER=INC file read AFTER a single-period rescue still comes back highest frequency first. The
    Vulcan sample is the ordinary path; the assertion is that the rescue left it alone."""
    mtm.read_with_fallback(ONE)
    tf = mtm.read(REAL)
    freq = 1.0 / tf.period
    assert freq[0] > freq[-1], "frequencies are no longer descending after a rescue ran"


def test_a_multi_period_failure_is_never_taken_for_the_single_period_defect(tmp_path):
    """The NFREQ guard, the counterpart of 'normalisation must change bytes'. A file that fails for
    any other reason must surface its own error rather than be retried with the assertion off."""
    broken = tmp_path / "broken.edi"
    broken.write_bytes(b">HEAD\n  DATAID=\"X\"\n  NFREQ= 30\n>END\n")
    with pytest.raises(Exception) as ei:
        mtm.read(broken)
    assert not isinstance(ei.value, IndexError) or "size 1" not in str(ei.value)


def test_a_single_period_station_builds_end_to_end(tmp_path):
    """Over the real producer: the station a length gate would lose lands in the catalogue as a
    GDS station with its one period, and the fallback is recorded per station in build_report.json.
    A survey whose files ALL fail this way built zero stations and was dropped from the portal
    entirely, taking its whole survey page with it."""
    pkg = tmp_path / "surveys" / "sp"
    edir = pkg / "transfer_functions" / "edi"
    edir.mkdir(parents=True)
    (pkg / "survey.yaml").write_text(
        "schema_version: \"0.1\"\nname: Single Period\nslug: sp\ncountry: Australia\n"
        "organisation: Test Org\naccess: open\nlicense: CC-BY-4.0\n"
        "abstract: Single-period fixture survey.\n", encoding="utf-8")
    shutil.copy(ONE, edir / ONE.name)
    out = tmp_path / "out"
    rc = build_portal.main(["--surveys", str(tmp_path / "surveys"), "--out", str(out),
                            "--no-validate", "--products", str(out / "products")])
    assert rc == 0
    row = json.loads((out / "catalogue.json").read_text(encoding="utf-8"))[0]
    assert row[build_portal.CATALOGUE_COLUMNS.index("comps")] == "T"
    assert row[build_portal.CATALOGUE_COLUMNS.index("n_periods")] == 1
    report = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    entry = report["surveys"]["sp"]
    assert entry["stations_built"] == 1
    assert entry["stations_dropped"] == []
    rows = entry["source_parse_fallbacks"]
    assert rows and rows[0]["file"] == ONE.name, rows
    assert "descending-frequency" in rows[0]["defect"], rows[0]
