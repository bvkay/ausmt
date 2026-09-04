"""A DATAID the reader's own name validator refuses, and the station it costs.

mt_metadata 1.0.10's utils/validators.validate_station_name strips the DATAID, rewrites space, '-',
'.' and '+' to '_', then requires the result to match ^[a-zA-Z0-9_]+$. A parenthesis or a slash
survives that rewrite and raises, and io/edi/metadata/header.py::read_header calls the validator
OUTSIDE the try/except that guards the assignment, so the read stops before anything else is
attempted. The file is well formed; the reader's identifier policy is what refuses it.

Measured on the GSSA/BHP Roxby Downs 2018 release: nine of the 764 served files carry
such a DATAID, the build prints PARSE FAIL for each, emits no SKIP, exits 0, and publishes 755
stations. Nine transfer functions with declared ids, coordinates and run ids never reach the
catalogue at all. The four space-only unsafe DATAIDs in the same release ("222 ", "222 error",
"245 ", "769 R") read perfectly well, and nothing here may touch them.

The rule these tests pin: the DATAID is normalised to the reader's charset ON A TEMPORARY COPY, and
ONLY when the reader would otherwise refuse it; the original DATAID stays the source fact and is
what the catalogue keeps as site_name; the custodian's file is never edited.
"""
import json
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

import _mtm as mtm            # noqa: E402
import build_portal           # noqa: E402
import edi_preflight as pf    # noqa: E402

CHARSET = FIX / "roxby-dataid-charset.edi"                  # DATAID "53(RR)": the reader refuses it
SAMPLE = ROOT / "data" / "sample-survey" / "transfer_functions" / "edi" / "Vulcan_A1.edi"


def _with_dataid(dest: Path, src: Path, dataid: str) -> Path:
    """A copy of `src` whose HEAD DATAID is `dataid`. Used for the space-only control, which needs a
    DATAID the reader ACCEPTS: minting it is honest here because the claim under test is about the
    reader's charset, not about any custodian's bytes."""
    text = src.read_text(encoding="latin-1")
    text = re.sub(r'DATAID\s*=\s*"?[^"\n]*"?', f'DATAID="{dataid}"', text, count=1)
    dest.write_text(text, encoding="latin-1")
    return dest


# --------------------------------------------------------------------------------------------
# the measurement: which DATAIDs the pinned reader actually refuses
# --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("dataid", ["53(RR)", "500/4759", "49R stage 1 (", "99 stage 1 (5"])
def test_the_reader_refuses_these_dataids(dataid):
    """Measured against the PINNED library, not asserted from its source: these are the four values
    the Roxby Downs release carries that stop the read."""
    assert mtm.dataid_needs_normalising(dataid) is True


@pytest.mark.parametrize("dataid", ["222 ", "222 error", "245 ", "769 R", "Wp01", "A1", "MT-01",
                                    "MT.01", "MT+01", "MT_01"])
def test_the_reader_accepts_these_dataids_so_nothing_touches_them(dataid):
    """The negative control the contract insists on: measure, do not normalise what already reads.
    The four space-only unsafe ids from the same release are in this list."""
    assert mtm.dataid_needs_normalising(dataid) is False


def test_normalisation_replaces_only_the_characters_the_reader_refuses():
    """Each offending character becomes '_', and the result is what mt_metadata's own rewrite
    produces where it does not raise: the space/hyphen/stop/plus class it already maps, extended to
    the class it refuses. Nothing else moves."""
    assert mtm.normalise_dataid("53(RR)") == "53_RR_"
    assert mtm.normalise_dataid("500/4759") == "500_4759"
    assert mtm.normalise_dataid("49R stage 1 (") == "49R_stage_1__"
    assert mtm.normalise_dataid("Wp01") == "Wp01"


# --------------------------------------------------------------------------------------------
# the reader seam
# --------------------------------------------------------------------------------------------

def test_the_refused_file_reads_and_says_so():
    """FAILS IF the read raises, which is what it does today for all nine of the release's files."""
    tf, reason, facts = mtm.read_with_parse_facts(CHARSET)
    assert tf.has_impedance(), "the parse returned no impedance"
    assert facts["dataid_normalised"] == {"original": "53(RR)", "read_as": "53_RR_"}
    assert "the reader's station-name charset" in (reason or "")


def test_the_source_file_is_never_edited(tmp_path):
    """For this fallback too: the conditioning is on a temporary copy destroyed inside the read."""
    work = tmp_path / CHARSET.name
    shutil.copy2(CHARSET, work)
    before = work.read_bytes()
    tf, _reason, _facts = mtm.read_with_parse_facts(work)
    assert work.read_bytes() == before
    assert Path(tf.fn) == work, f"the TF must point at the custodian's file, not a scratch copy: {tf.fn}"


def test_a_readable_dataid_takes_no_conditioning_at_all(tmp_path):
    """The space-only case, end to end: '769 R' reads today, so the fallback must never fire for it
    and the station name must stay mt_metadata's own rewrite of the custodian's value."""
    work = _with_dataid(tmp_path / "769R.edi", SAMPLE, "769 R")
    tf, reason, facts = mtm.read_with_parse_facts(work)
    assert reason is None
    assert "dataid_normalised" not in facts
    assert tf.station == "769_R"


# --------------------------------------------------------------------------------------------
# the build: the station publishes, under its declared id, keeping the custodian's DATAID
# --------------------------------------------------------------------------------------------

def _survey(tmp_path, edi_name, published_id):
    pkg = tmp_path / "surveys" / "epikit-probe"
    edir = pkg / "transfer_functions" / "edi"
    edir.mkdir(parents=True)
    shutil.copy2(CHARSET, edir / edi_name)
    (pkg / "survey.yaml").write_text(
        "name: EPI-KIT Probe\nslug: epikit-probe\ncountry: Australia\n"
        "organisation: Test Org\naccess: open\nlicense: CC-BY-4.0\n"
        "station_ids:\n  source: filename\n  map:\n"
        f'    "{edi_name}": "{published_id}"\n', encoding="utf-8")
    return tmp_path / "surveys"


def _catalogue(out: Path):
    from _contract import CATALOGUE_COLUMNS  # noqa: PLC0415
    rows = json.loads((out / "catalogue.json").read_text(encoding="utf-8"))
    return [dict(zip(CATALOGUE_COLUMNS, r)) for r in rows]


def test_the_station_publishes_under_its_declared_id_with_the_custodian_dataid_as_site_name(tmp_path):
    """The whole point, over BUILT output: the row exists, it carries the id survey.yaml declares, and
    site_name carries the DATAID the custodian wrote, parentheses and all. FAILS IF the build drops
    the station (today: PARSE FAIL, no catalogue row, exit 0)."""
    surveys = _survey(tmp_path, "53(RR).edi", "RD18-053a")
    out = tmp_path / "out"
    assert build_portal.main(["--surveys", str(surveys), "--out", str(out),
                              "--bundle-edi", "--no-validate"]) == 0
    rows = _catalogue(out)
    assert [r["id"] for r in rows] == ["RD18-053a"], rows
    assert rows[0]["site_name"] == "53(RR)", rows[0]
    report = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    entry = report["surveys"]["epikit-probe"]
    assert entry["source_parse_failures"] == []
    assert entry["stations_dropped"] == []
    assert entry["stations_built"] == 1


def test_the_served_bytes_stay_the_custodian_s_file(tmp_path):
    """The served EDI is byte-identical to the fixture, and the build's own integrity gate says so."""
    surveys = _survey(tmp_path, "53(RR).edi", "RD18-053a")
    out = tmp_path / "out"
    assert build_portal.main(["--surveys", str(surveys), "--out", str(out),
                              "--bundle-edi", "--no-validate"]) == 0
    served = list((out / "edi" / "epikit-probe").glob("*.edi"))
    assert len(served) == 1, served
    assert served[0].read_bytes() == CHARSET.read_bytes()
    integrity = json.loads((out / "build_report.json").read_text(
        encoding="utf-8"))["surveys"]["epikit-probe"]["source_integrity"]
    assert integrity["checked"] == integrity["verified"] == 1 and integrity["mismatches"] == []


def test_the_station_record_carries_the_section_of_record(tmp_path):
    """Provenance travelling into the published product: the fixture carries the averaged
    solution and one realisation, and station.json says which one the numbers came from."""
    surveys = _survey(tmp_path, "53(RR).edi", "RD18-053a")
    out = tmp_path / "out"
    assert build_portal.main(["--surveys", str(surveys), "--out", str(out), "--bundle-edi",
                              "--no-validate", "--products", str(out / "products")]) == 0
    doc = json.loads((out / "products" / "epikit-probe" / "RD18-053a" / "station.json")
                     .read_text(encoding="utf-8"))
    assert doc["provenance"]["section_selected"] == {"sectid": "53(RR)_avg", "sections_dropped": 1}


# --------------------------------------------------------------------------------------------
# the pre-flight vocabulary: AusMT rescues this class, so it is not terminal
# --------------------------------------------------------------------------------------------

def test_preflight_calls_a_refused_dataid_needs_repair_not_will_not_read():
    """The pre-flight tells a curator what a delivery will do BEFORE a build runs, so its verdict has
    to move with the reader. Until this class was WILL_NOT_READ, which was true then and is a lie
    now: AusMT reads the file by conditioning a temporary copy."""
    finding = pf.preflight_file(CHARSET)
    assert finding["outcome"] == pf.NEEDS_REPAIR, finding
    assert finding["blocking_fields"][0]["value"] == "53(RR)"
    assert "temporary copy" in finding["reason"]
    assert "site_name" in finding["reason"]


def test_preflight_names_the_station_the_build_names():
    """The module's own rule, extended to the class the rescue created: a finding a curator cannot
    match to a station is a finding they cannot act on. The pre-flight's mirror of the station name
    now has to carry the AusMT normalisation too, or it reports "53(RR)" for a station the build
    calls 53_RR_. Held against the reader itself, never against an expectation, and the repository's
    other real EDIs carry no refused DATAID, so nothing else pins this."""
    assert pf.preflight_file(CHARSET)["station"] == mtm.read(CHARSET).station == "53_RR_"


@pytest.mark.parametrize("dataid", ["222 ", "769 R", "MT-01", "MT.01", "MT+01", "Wp01"])
def test_the_station_name_mirror_still_agrees_on_a_dataid_the_reader_accepts(dataid, tmp_path):
    """The sweep is only safe because it AGREES with mt_metadata wherever mt_metadata is defined.
    Checked against the real reader on each accepted shape, or the widened mirror could be renaming
    stations the reader was perfectly happy with."""
    work = _with_dataid(tmp_path / "ok.edi", SAMPLE, dataid)
    assert pf.station_name(dataid) == mtm.read(work).station


def test_preflight_still_calls_an_unreadable_reference_position_terminal(tmp_path):
    """The verdict that must NOT move: a reference position mt_metadata refuses is set unguarded in
    read_measurement and no AusMT conditioning touches it, so it stays terminal. Without this the
    test above could be passed by weakening the whole vocabulary."""
    work = tmp_path / "badref.edi"
    text = SAMPLE.read_text(encoding="latin-1").replace("REFLAT=-30:8:45.208", "REFLAT=south")
    work.write_text(text, encoding="latin-1")
    assert pf.preflight_file(work)["outcome"] == pf.WILL_NOT_READ


def test_a_terminal_surface_still_wins_over_the_rescued_dataid(tmp_path):
    """The ordering the rescue changed. While a refused DATAID was terminal it could return first and
    lose nothing; now that it is repaired, returning first would report a file as repairable when
    something further down it is not readable at all. Both rows are reported, and the verdict is the
    worse of the two."""
    work = tmp_path / "both.edi"
    text = CHARSET.read_text(encoding="latin-1").replace("REFLAT=-30:38:26.937", "REFLAT=south")
    work.write_text(text, encoding="latin-1")
    finding = pf.preflight_file(work)
    assert finding["outcome"] == pf.WILL_NOT_READ
    assert [row["field"] for row in finding["blocking_fields"]] == [">HEAD DATAID",
                                                                    ">=DEFINEMEAS REFLAT"]
