"""Honest drop accounting: a source file the reader cannot read is a DROPPED STATION on the record.

Every neighbouring drop path in `process_edis` writes a structured record - the C25 convention-gate
skip, the station with no recoverable coordinates or periods, the MTH5 read failure. The EDI parse
failure did not: it printed a line to stderr and continued, so a station could vanish from an
otherwise green build with nothing in build_report.json to name it. On the AusMT GDS staging that
silence covered ninety-five files and four whole surveys, and the corpus validator reports zero
items for it.

Two ledgers, because they answer different questions. `stations_dropped` answers "which stations
are not here", alongside every other drop, and is where counts are read. `source_parse_failures`
answers "which FILE, and what did the reader say" - the negative twin of `source_parse_fallbacks`,
which records the files a normalised reparse rescued. `stations_dropped` rows are {station, reason}
under `additionalProperties: false` and have no room for a file name or an error class, which is
why the second key exists rather than a widened first one.
"""
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "extract"))
sys.path.insert(0, str(REPO))
import build_portal         # noqa: E402

SCHEMA = json.loads((REPO / "schema" / "build_report.schema.json").read_text(encoding="utf-8"))
REAL = REPO / "data" / "sample-survey" / "transfer_functions" / "edi" / "Vulcan_A1.edi"

# An .edi mt_metadata cannot read and that no fallback rescues: a >HEAD with no measurement or data
# section at all. Deliberately NOT one of the three recognised defects - this is the residue case,
# the file whose failure the build must report rather than repair.
UNREADABLE = b">HEAD\n  DATAID=\"NOPE\"\n  LAT=-30.0\n  LONG=136.0\n>END\n"


def _survey(tmp_path, slug="mixed", with_good=True):
    pkg = tmp_path / "surveys" / slug
    edir = pkg / "transfer_functions" / "edi"
    edir.mkdir(parents=True)
    (pkg / "survey.yaml").write_text(
        f"schema_version: \"0.1\"\nname: Drop Accounting\nslug: {slug}\ncountry: Australia\n"
        "organisation: Test Org\naccess: open\nlicense: CC-BY-4.0\n"
        "abstract: Parse-failure accounting fixture survey.\n", encoding="utf-8")
    (edir / "unreadable.edi").write_bytes(UNREADABLE)
    if with_good:
        (edir / REAL.name).write_bytes(REAL.read_bytes())
    return pkg


def _build(tmp_path, slug="mixed"):
    out = tmp_path / "out"
    rc = build_portal.main(["--surveys", str(tmp_path / "surveys"), "--out", str(out),
                            "--no-validate", "--products", str(out / "products")])
    assert rc == 0
    return json.loads((out / "build_report.json").read_text(encoding="utf-8"))["surveys"][slug]


def test_an_unreadable_source_file_is_named_in_the_drop_ledger(tmp_path):
    """FAILS against the pre-fix engine, whose stations_dropped is empty for this build: the station
    is simply absent, with a stderr line as the only trace."""
    _survey(tmp_path)
    entry = _build(tmp_path)
    assert entry["stations_built"] == 1, "the readable station must still build"
    drops = entry["stations_dropped"]
    assert [d["station"] for d in drops] == ["unreadable"], drops
    assert "unreadable by mt_metadata" in drops[0]["reason"], drops[0]


def test_the_failure_carries_the_file_and_the_readers_own_error(tmp_path):
    """The typed ledger. The file name and the exception class are what tell a curator whether this
    is a malformed source or a reader defect worth a fallback, and neither fits in a drop row."""
    _survey(tmp_path)
    entry = _build(tmp_path)
    rows = entry["source_parse_failures"]
    assert len(rows) == 1, rows
    assert rows[0]["station"] == "unreadable"
    assert rows[0]["file"] == "unreadable.edi"
    assert rows[0]["error"], rows[0]
    assert ":" in rows[0]["error"], "the error must name its exception class"


def test_one_lost_station_raises_exactly_one_warning(tmp_path):
    """A green build must not be able to hide a dropped station, and must not count it twice
    either. The drop goes through the per-drop echo every stations_dropped row already goes
    through, so the warning comes from there and the typed ledger adds none of its own. Pinned
    because the first version of this change raised a second aggregate warning beside the echo,
    which the framing build pair caught as 68 survey warnings becoming 70 for one lost station."""
    _survey(tmp_path)
    entry = _build(tmp_path)
    named = [w for w in entry["warnings"] if "unreadable" in w]
    assert len(named) == 1, named
    assert "unreadable by mt_metadata" in named[0], named[0]


def test_a_survey_whose_files_all_read_reports_no_failures(tmp_path):
    """The negative control: the key exists and is empty, so its presence is not itself a signal.
    Pinned because an emitter that only writes the key when something went wrong makes 'no key' and
    'no failures' indistinguishable to a consumer."""
    pkg = tmp_path / "surveys" / "clean"
    edir = pkg / "transfer_functions" / "edi"
    edir.mkdir(parents=True)
    (pkg / "survey.yaml").write_text(
        "schema_version: \"0.1\"\nname: Clean\nslug: clean\ncountry: Australia\n"
        "organisation: Test Org\naccess: open\nlicense: CC-BY-4.0\n"
        "abstract: Clean fixture survey.\n", encoding="utf-8")
    (edir / REAL.name).write_bytes(REAL.read_bytes())
    entry = _build(tmp_path, slug="clean")
    assert entry["source_parse_failures"] == []
    assert entry["stations_dropped"] == []
    assert not any("could not read" in w for w in entry["warnings"]), entry["warnings"]


def test_the_report_still_validates_against_its_own_schema(tmp_path):
    """The additive key is in build_report.schema.json, and the survey object refuses unknown
    properties, so this both proves the schema was updated and that nothing else drifted."""
    jsonschema = pytest.importorskip("jsonschema")
    _survey(tmp_path)
    out = tmp_path / "out"
    rc = build_portal.main(["--surveys", str(tmp_path / "surveys"), "--out", str(out),
                            "--no-validate", "--products", str(out / "products")])
    assert rc == 0
    report = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    jsonschema.validate(report, SCHEMA)
    items = SCHEMA["definitions"]["survey"]["properties"]["source_parse_failures"]["items"]
    assert items["required"] == ["station", "file", "error"]
    assert items["additionalProperties"] is False
