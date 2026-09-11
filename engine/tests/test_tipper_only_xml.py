"""The tipper-only canonical XML: a station with no impedance must still get an EMTF-XML product.

Two library faults meet on the legacy GDS class (three magnetic channels, no electric channels, so a
vertical field transfer function and nothing else), and between them they cost every such station its
canonical XML:

  * mt_metadata's EMTF-XML writer picks the statistical-estimate glossary from the impedance slot
    FIRST and only falls through to the tipper when that slot is absent. A tipper-only TF carries a
    zero-filled impedance variance rather than none, so the fall-through never happens, the glossary
    is written childless, and the reader's `input_dict["statistical_estimates"]["estimate"]` subscripts
    the None an empty element parses to. TypeError, on the library's own output.
  * the round-trip gate then read `tf.impedance.data` unconditionally, which is None for the same
    station. AttributeError, one line further on.

Both are pinned here on MINTED fixtures (no custodian bytes), with the variance-printed and the
variance-omitted shapes covered separately, plus the negative that a station WITH an impedance is
untouched. Requires the core mt_metadata stack; importorskips when absent.
"""
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))  # make the ausmt_science package importable from a source checkout

from ausmt_science.ingest.normalize import normalize  # noqa: E402

# The repair's own names are imported INSIDE the tests that need them, not at module scope: on the
# unfixed engine they do not exist, and a collection-time ImportError would replace the library
# TypeError this suite exists to pin with a failure that says nothing about the defect.

FIXTURES = HERE / "fixtures" / "tipper-only"
WITH_VAR = FIXTURES / "tipper-only-with-variance.edi"
NO_VAR = FIXTURES / "tipper-only-no-variance.edi"
# A station that HAS an impedance, to hold the untouched path honest.
STANDARD = REPO / "data" / "sample-survey" / "transfer_functions" / "edi" / "Vulcan_A1.edi"


@pytest.mark.parametrize("src,station,n_periods", [(WITH_VAR, "TOV", 4), (NO_VAR, "TON", 5)])
def test_tipper_only_station_gets_a_canonical_xml(tmp_path, src, station, n_periods):
    """RED-PROOF. FAILS IF: a tipper-only station cannot be normalised. On the unfixed engine this
    raises TypeError ('NoneType' object is not subscriptable) from the reader's statistical-estimates
    parse, and with that repaired alone it raises AttributeError from the impedance-only round-trip
    gate. Green requires BOTH: a glossary the reader accepts, and a gate that leads with the field
    this station actually serves."""
    assert src.exists(), f"fixture missing: {src}"
    res = normalize(src, tmp_path, survey_id="gds-fixture", station_id=station)
    assert res.canonical_xml.exists() and res.canonical_xml.stat().st_size > 0
    assert res.derived_edi.exists() and res.derived_edi.stat().st_size > 0
    assert res.n_periods == n_periods, res.n_periods
    # The gate led with the tipper (there is no impedance), and it agreed to within tolerance.
    assert res.roundtrip_maxdiff < 1e-3, res.roundtrip_maxdiff


@pytest.mark.parametrize("src,station", [(WITH_VAR, "TOV"), (NO_VAR, "TON")])
def test_tipper_only_glossary_is_rebuilt_and_reported(tmp_path, src, station):
    """The written glossary names the estimate block the document carries, and the repair is REPORTED.
    FAILS IF: the element is still childless (unreadable), or the variance block is declared nowhere,
    or the conditioning note is missing so the build log could call this a clean station."""
    from ausmt_science.ingest.normalize import NOTE_ESTIMATES_REBUILT

    res = normalize(src, tmp_path, survey_id="gds-fixture", station_id=station)
    text = res.canonical_xml.read_text(encoding="utf-8")
    assert "<StatisticalEstimates/>" not in text
    assert '<Estimate name="VAR" type="real">' in text
    assert "<T.VAR" in text, "the block the glossary entry describes must actually be in the document"
    assert NOTE_ESTIMATES_REBUILT in res.conditioned, res.conditioned


def test_tipper_survives_the_canonical_round_trip(tmp_path):
    """The point of serving the XML at all: the transfer function in it is the one that went in."""
    import numpy as np
    from mt_metadata.transfer_functions.core import TF

    res = normalize(WITH_VAR, tmp_path, survey_id="gds-fixture", station_id="TOV")
    src_tf = TF()
    src_tf.read(str(WITH_VAR))
    rt = TF()
    rt.read(str(res.canonical_xml))
    assert rt.tipper is not None, "the re-read canonical XML dropped the tipper"
    assert np.allclose(np.asarray(src_tf.tipper.data), np.asarray(rt.tipper.data),
                       rtol=1e-3, atol=1e-6)


def test_station_with_an_impedance_is_untouched(tmp_path):
    """The negative. FAILS IF: the repair fires on a station whose glossary the writer populated
    itself, which would mean served XML bytes changing for the stations that already had one."""
    from ausmt_science.ingest.normalize import NOTE_ESTIMATES_DROPPED, NOTE_ESTIMATES_REBUILT

    if not STANDARD.exists():  # pragma: no cover - the in-repo sample survey is always present
        pytest.skip(f"sample survey missing: {STANDARD}")
    res = normalize(STANDARD, tmp_path, survey_id="vulcan")
    assert NOTE_ESTIMATES_REBUILT not in res.conditioned, res.conditioned
    assert NOTE_ESTIMATES_DROPPED not in res.conditioned, res.conditioned


def _minimal_emtf_xml(estimates_block: str, data_block: str) -> str:
    return ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            "<EM_TF>\n"
            "    <ProductId>FIX.TON.1981</ProductId>\n"
            f"{estimates_block}"
            "    <Data count=\"1\">\n"
            "        <Period value=\"9.000000000000e+02\" units=\"secs\">\n"
            f"{data_block}"
            "        </Period>\n"
            "    </Data>\n"
            "</EM_TF>\n")


def test_empty_glossary_with_no_estimate_block_is_removed(tmp_path):
    """A document that carries NO estimate block has no glossary entry to write truthfully, so the
    unreadable empty element is removed rather than filled with a type the file does not contain.
    FAILS IF: an entry is invented, or the empty element survives (the reader cannot parse it)."""
    from ausmt_science.ingest.normalize import NOTE_ESTIMATES_DROPPED, _fix_statistical_estimates

    xml = tmp_path / "TON.xml"
    xml.write_text(_minimal_emtf_xml(
        "    <StatisticalEstimates/>\n",
        "            <T type=\"complex\" size=\"1 2\" units=\"[]\">\n"
        "                <value name=\"Tx\" output=\"Hz\" input=\"Hx\">1.0 0.0</value>\n"
        "            </T>\n"), encoding="utf-8")
    assert _fix_statistical_estimates(xml) == NOTE_ESTIMATES_DROPPED
    text = xml.read_text(encoding="utf-8")
    assert "StatisticalEstimates" not in text
    assert "<Estimate" not in text


def test_populated_glossary_is_left_alone(tmp_path):
    """FAILS IF: the repair rewrites a glossary the writer already populated."""
    from ausmt_science.ingest.normalize import _fix_statistical_estimates

    populated = ("    <StatisticalEstimates>\n"
                 "        <Estimate name=\"VAR\" type=\"real\">\n"
                 "            <Description>Variance</Description>\n"
                 "        </Estimate>\n"
                 "    </StatisticalEstimates>\n")
    xml = tmp_path / "OK.xml"
    before = _minimal_emtf_xml(populated, "            <Z.VAR type=\"real\" size=\"2 2\"/>\n")
    xml.write_text(before, encoding="utf-8")
    assert _fix_statistical_estimates(xml) is None
    assert xml.read_text(encoding="utf-8") == before
