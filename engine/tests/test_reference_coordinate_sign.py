"""A coordinate written with a doubled sign, and the station it has been costing.

mt_metadata's DefineMeasurement sets reflat/reflon through an UNGUARDED setattr whose validator
refuses anything that is neither a float nor a DD:MM:SS string, so a reference latitude written
"--26.0322667" stops the read dead. One file in the corpus carries it: capricorn-2010's CP3B21.edi,
whose HEAD states the same coordinate correctly, and which has therefore published nothing at all.

Measured against the pinned reader, and it is the measurement that decides the key set. On the
DEFINEMEAS reference position a doubled sign is FATAL. On the HEAD LAT/LONG it is SILENT: the value
is dropped, and the station either falls back to the reference position or, with no reference
position behind it, publishes latitude 0.0. Neither key carries the defect anywhere in the corpus
today, so covering both is inert and closes the silent case before it arrives.

The rule these tests pin: a run of two or more IDENTICAL leading sign characters collapses to one ON
A TEMPORARY COPY, the collapse is recorded as parse provenance, and nothing else about the file is
touched. A MIXED run is not a repeated keystroke and is left refused, because collapsing it would
choose a hemisphere the custodian did not write.
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
FIX = HERE / "fixtures" / "coordinate-sign"
sys.path[:0] = [str(ROOT), str(ROOT / "extract")]

import _mtm as mtm            # noqa: E402
import build_portal           # noqa: E402
import edi_preflight as pf    # noqa: E402

REFLAT = FIX / "capricorn-cp3b21-reflat.edi"    # REFLAT="--26.0322667": the reader refuses it
SAMPLE = ROOT / "data" / "sample-survey" / "transfer_functions" / "edi" / "Vulcan_A1.edi"
WORKFLOW = ROOT.parent / ".github" / "workflows" / "build-products.yml"

# The custodian's own coordinate, stated correctly in the HEAD of the same file.
CP3B21_LAT, CP3B21_LON = -26.032267, 116.605467


def _rewrite(dest: Path, src: Path, key: str, value: str) -> Path:
    """A copy of `src` whose `key` line carries `value`, the whole value replaced and the key matched
    at the start of its line so LAT does not also match REFLAT. Minting the value is honest here: the
    claim under test is about what the reader does with a sign run, not about custodian bytes."""
    text = re.sub(rf"(?m)^(\s*){key}\s*=\s*\S+", rf"\g<1>{key}={value}",
                  src.read_text(encoding="latin-1"), count=1)
    dest.write_text(text, encoding="latin-1")
    return dest


# --------------------------------------------------------------------------------------------
# the measurement: what the pinned reader does with a sign run, per key
# --------------------------------------------------------------------------------------------

def test_the_reference_latitude_is_what_stops_the_read(tmp_path):
    """The defect itself, measured rather than asserted from the library's source."""
    work = _rewrite(tmp_path / "reflat.edi", SAMPLE, "REFLAT", "--30.5")
    with pytest.raises(Exception) as exc:
        mtm._read_once(work)
    assert "reflat" in str(exc.value).lower()


def test_a_head_latitude_sign_run_is_silent_not_fatal(tmp_path):
    """The other half of the measurement, and the reason the HEAD keys are covered too: a stock read
    of a doubled HEAD latitude SUCCEEDS and publishes 0.0 when no reference position backs it up."""
    text = SAMPLE.read_text(encoding="latin-1")
    text = re.sub(r"(?m)^\s*REFLAT\s*=.*$\n", "", text, count=1)
    text = re.sub(r"(?m)^\s*REFLONG\s*=.*$\n", "", text, count=1)
    text = re.sub(r"LAT\s*=\s*", "LAT=--", text, count=1)
    work = tmp_path / "headlat.edi"
    work.write_text(text, encoding="latin-1")
    assert mtm._read_once(work).station_metadata.location.latitude == 0.0


# --------------------------------------------------------------------------------------------
# the rescue
# --------------------------------------------------------------------------------------------

def test_the_custodian_file_reads_and_yields_the_coordinate_it_states():
    """R5, the whole point. FAILS IF the reader still refuses the doubled minus: that is what keeps
    this station out of the corpus today."""
    tf = mtm.read(REFLAT)
    loc = tf.station_metadata.location
    assert round(loc.latitude, 6) == CP3B21_LAT
    assert round(loc.longitude, 6) == CP3B21_LON


def test_the_collapse_is_recorded_as_parse_provenance():
    """A silent repair is not acceptable: the parse facts name the field, what the file says, and
    what the reader was given, so station.json and build_report can carry it."""
    tf, reason, facts = mtm.read_with_parse_facts(REFLAT)
    rows = facts["coordinate_signs_collapsed"]
    assert rows == [{"field": "REFLAT", "value": "--26.0322667", "read_as": "-26.0322667"}], rows
    assert reason and "sign" in reason.lower()
    assert Path(tf.fn) == REFLAT, f"the TF must point at the custodian's file, not a scratch copy: {tf.fn}"


def test_the_custodian_bytes_are_never_touched():
    """D1: the conditioning lives on a temporary copy that is destroyed inside the read."""
    before = REFLAT.read_bytes()
    mtm.read(REFLAT)
    assert REFLAT.read_bytes() == before
    assert b"REFLAT=--26.0322667" in before


@pytest.mark.parametrize("key,value", [("LAT", "--30.5"), ("LONG", "++136.9"),
                                       ("REFLAT", "--30.5"), ("REFLONG", "++136.9")])
def test_every_covered_key_collapses(tmp_path, key, value):
    """The key set, one file per key, so a regression on any one of the four is named."""
    work = _rewrite(tmp_path / f"{key}.edi", SAMPLE, key, value)
    _tf, _reason, facts = mtm.read_with_parse_facts(work)
    assert [r["field"] for r in facts["coordinate_signs_collapsed"]] == [key]
    assert facts["coordinate_signs_collapsed"][0]["read_as"] == value[1:]


# --------------------------------------------------------------------------------------------
# the boundaries: narrow by construction
# --------------------------------------------------------------------------------------------

def test_a_sound_file_takes_no_conditioning_at_all():
    """The inertness control, and the reason the corpus framing holds: every EDI in the corpus but
    one writes one sign, so every one of them reads exactly as it does today."""
    _tf, reason, facts = mtm.read_with_parse_facts(SAMPLE)
    assert reason is None
    assert "coordinate_signs_collapsed" not in facts


def test_a_mixed_sign_run_is_left_refused(tmp_path):
    """The stated boundary. "--" is a repeated keystroke; "-+" is not, and choosing one of its two
    signs would invent a hemisphere. The file keeps failing, loudly, with the reader's own error."""
    work = _rewrite(tmp_path / "mixed.edi", SAMPLE, "REFLAT", "-+30.5")
    _cond, facts, _reasons = mtm._pre_read_conditioning(work, work.read_bytes())
    assert "coordinate_signs_collapsed" not in facts
    with pytest.raises(Exception):
        mtm.read(work)


def test_a_malformed_reference_position_is_still_refused(tmp_path):
    """Nothing here rescues a coordinate that is not a number: only the sign run is touched."""
    work = _rewrite(tmp_path / "words.edi", SAMPLE, "REFLAT", "south")
    with pytest.raises(Exception):
        mtm.read(work)


# --------------------------------------------------------------------------------------------
# the preflight vocabulary
# --------------------------------------------------------------------------------------------

def test_preflight_calls_the_doubled_sign_a_repair_ausmt_makes():
    """R5's preflight clause: the class was will_not_read while it was terminal, and AusMT now
    rescues it, so the curator report must say needs_repair and say what AusMT does."""
    finding = pf.preflight_file(REFLAT)
    assert finding["outcome"] == pf.NEEDS_REPAIR, finding
    assert [row["field"] for row in finding["blocking_fields"]] == [">=DEFINEMEAS REFLAT"]
    assert "temporary copy" in finding["reason"]


def test_preflight_still_refuses_a_reference_position_that_is_not_a_number(tmp_path):
    """The vocabulary's other half stays where it was: a value nothing can read is will_not_read."""
    work = _rewrite(tmp_path / "words.edi", SAMPLE, "REFLAT", "south")
    assert pf.preflight_file(work)["outcome"] == pf.WILL_NOT_READ


# --------------------------------------------------------------------------------------------
# the build: the station publishes
# --------------------------------------------------------------------------------------------

def _survey(tmp_path):
    pkg = tmp_path / "surveys" / "reflat-probe"
    edir = pkg / "transfer_functions" / "edi"
    edir.mkdir(parents=True)
    shutil.copy2(REFLAT, edir / "CP3B21.edi")
    (pkg / "survey.yaml").write_text(
        "name: Reference Sign Probe\nslug: reflat-probe\ncountry: Australia\n"
        "organisation: Test Org\naccess: open\nlicense: CC-BY-4.0\n", encoding="utf-8")
    return tmp_path / "surveys"


def _catalogue(out: Path):
    from _contract import CATALOGUE_COLUMNS  # noqa: PLC0415
    rows = json.loads((out / "catalogue.json").read_text(encoding="utf-8"))
    return [dict(zip(CATALOGUE_COLUMNS, r)) for r in rows]


def test_the_station_publishes_with_the_coordinate_its_head_states(tmp_path):
    """Over BUILT output: the catalogue row exists, at the custodian's own coordinate, and the build
    records no parse failure and no drop. FAILS IF the build still prints PARSE FAIL and exits 0
    with an empty catalogue, which is what it does today."""
    out = tmp_path / "out"
    assert build_portal.main(["--surveys", str(_survey(tmp_path)), "--out", str(out),
                              "--bundle-edi", "--no-validate"]) == 0
    rows = _catalogue(out)
    assert [r["id"] for r in rows] == ["CP3B21"], rows
    assert (round(rows[0]["lat"], 6), round(rows[0]["lon"], 6)) == (CP3B21_LAT, CP3B21_LON)
    entry = json.loads((out / "build_report.json").read_text(
        encoding="utf-8"))["surveys"]["reflat-probe"]
    assert entry["source_parse_failures"] == []
    assert entry["stations_dropped"] == []
    assert entry["stations_built"] == 1


def test_the_station_document_carries_the_collapse_beside_its_input_file(tmp_path):
    """The provenance clause: what the reader was given is published beside which file it came from,
    in the same place the section of record is published."""
    out = tmp_path / "out"
    assert build_portal.main(["--surveys", str(_survey(tmp_path)), "--out", str(out),
                              "--products", str(out / "products"),
                              "--bundle-edi", "--no-validate"]) == 0
    doc = json.loads((out / "products" / "reflat-probe" / "CP3B21" / "station.json").read_text(
        encoding="utf-8"))
    prov = doc["provenance"]
    assert prov["input_file"] == "CP3B21.edi"
    assert prov["coordinate_signs_collapsed"] == [
        {"field": "REFLAT", "value": "--26.0322667", "read_as": "-26.0322667"}]


def test_the_served_edi_is_the_custodian_file_byte_for_byte(tmp_path):
    """The served bytes keep the doubled minus, and the build's own integrity gate says so."""
    out = tmp_path / "out"
    assert build_portal.main(["--surveys", str(_survey(tmp_path)), "--out", str(out),
                              "--bundle-edi", "--no-validate"]) == 0
    served = list((out / "edi" / "reflat-probe").glob("*.edi"))
    assert len(served) == 1 and served[0].read_bytes() == REFLAT.read_bytes()
    integrity = json.loads((out / "build_report.json").read_text(
        encoding="utf-8"))["surveys"]["reflat-probe"]["source_integrity"]
    assert integrity["checked"] == integrity["verified"] == 1 and integrity["mismatches"] == []


@pytest.mark.skipif(not WORKFLOW.is_file(),
                    reason="engine image build: workflow tree not shipped "
                           "(designed topology; the CI guards are pinned from checkout lanes)")
def test_this_file_is_in_the_pr_gate_subset():
    """Rule 8: the PR gate enumerates test files BY NAME, so a reader-seam test that is not listed
    runs only on push to main, and this seam decides whether a station exists at all."""
    steps = re.split(r"\n(?=      - name: )", WORKFLOW.read_text(encoding="utf-8"))
    subset = [s for s in steps if "PR gate subset" in s.split("\n")[0]]
    assert len(subset) == 1, [s.split("\n")[0] for s in steps]
    assert f"tests/{Path(__file__).name}" in subset[0]
