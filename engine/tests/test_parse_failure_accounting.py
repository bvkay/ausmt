"""Honest drop accounting: a source file the reader cannot read is a DROPPED STATION on the record.

Every neighbouring drop path in `process_edis` writes a structured record - the convention-gate
skip, the station with no recoverable coordinates or periods, the MTH5 read failure. The EDI parse
failure did not: it printed a line to stderr and continued, so a station could vanish from an
otherwise green build with nothing in build_report.json to name it. On the AusMT GDS staging that
silence covered ninety-five files and four whole surveys, and the corpus validator reports zero
items for it.

Two ledgers, because they answer different questions. `stations_dropped` answers "which stations
are not here", alongside every other drop, and is where counts are read; every row names the source
file beside the station, because the only action a drop row can lead to is opening that file and
`station` is the id the build settled on, not a path. `source_parse_failures` answers "what did the
READER say" - the negative twin of `source_parse_fallbacks`, which records the files a normalised
reparse rescued. The reader's own error is what stays exclusive to it: a drop row is one line in a
build log and a pydantic traceback is not one, and a gate refusal has no reader error at all.
"""
import json
import re
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

_IMAG_Z_BLOCKS = ("ZXXI", "ZXYI", "ZYXI", "ZYYI")
_NUM = re.compile(r"-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?")


def _conjugated(text):
    """The in-repo clean station with every imaginary Z block negated, i.e. Z -> conj(Z).

    A coherent quadrant flip in BOTH off-diagonals is exactly what the sign-convention gate
    refuses to serve (the e^{+iwt} against e^{-iwt} sense), so this is the smallest honest fixture
    for a GATE drop, as opposed to the unreadable-file drop above. Only the four imaginary data
    blocks are rewritten: the header and the rotation blocks are untouched, so the frame gate ahead
    of it still passes and the station drops for the one reason under test. The tests that use it
    assert that precondition rather than assuming it."""
    out, in_block = [], False
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith(">"):
            token = s[1:].split()[0].upper() if len(s) > 1 else ""
            in_block = token in _IMAG_Z_BLOCKS
            out.append(ln)
        elif in_block and s:
            out.append(_NUM.sub(lambda m: f"{-float(m.group()): .9E}", ln))
        else:
            out.append(ln)
    return "\n".join(out) + "\n"


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


def _gate_survey(tmp_path, slug="gated", name="a-contractors-file-name.edi"):
    """A survey whose second station is refused by the sign-convention gate, under a FILE NAME that
    appears nowhere in its own header (the fixture's DATAID is "A1"). That mismatch is the point:
    it is the shape a third-party release has, and it is what makes the drop row's `file` field
    carry information its `station` field cannot."""
    pkg = tmp_path / "surveys" / slug
    edir = pkg / "transfer_functions" / "edi"
    edir.mkdir(parents=True)
    (pkg / "survey.yaml").write_text(
        f"schema_version: \"0.1\"\nname: Gate Drop\nslug: {slug}\ncountry: Australia\n"
        "organisation: Test Org\naccess: open\nlicense: CC-BY-4.0\n"
        "abstract: Convention-gate drop accounting fixture survey.\n", encoding="utf-8")
    (edir / REAL.name).write_bytes(REAL.read_bytes())
    (edir / name).write_text(_conjugated(REAL.read_text(encoding="latin-1")), encoding="latin-1")
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


def test_a_gate_drop_names_the_source_file_beside_the_station(tmp_path):
    """FAILS against the pre-change engine: a station refused by the sign-convention gate is
    recorded as {station, reason} only, and `station` is the id the build settled on, not a path.

    A drop row is the whole record for a station the corpus does not publish, and the only action
    it can lead to is opening the source file. On the GSSA Roxby Downs 2018 release that is not a
    lookup a curator can do in their head: the withheld station is RD18-188e and the file is
    188_S__2.edi, and nothing in the row connects them. `source_parse_failures` carries a file name
    for the reader's own refusals, but a GATE drop writes no row there at all, so for the drops the
    convention gates make there is no ledger that names the file. This closes that."""
    _gate_survey(tmp_path)
    entry = _build(tmp_path, slug="gated")
    assert entry["stations_built"] == 1, "the clean twin must still build"
    drops = entry["stations_dropped"]
    assert len(drops) == 1, drops
    assert "[sign-convention]" in drops[0]["reason"], drops[0]
    assert drops[0]["station"] == "A1", "precondition: the row names the DATAID, not the file"
    assert drops[0]["file"] == "a-contractors-file-name.edi", drops[0]


def test_every_drop_row_names_its_source_file(tmp_path):
    """The field is a property of the LEDGER, not of one drop path. `process_edis` and
    `process_emtfxml` write a drop row from several places (the unreadable file, the gate refusals,
    the station with no recoverable coordinates or periods), and a row that omits the file is worse
    than one that never carried it: a consumer cannot tell 'no file' from 'this drop has none'.
    Both fixture surveys are swept, so a new drop path that forgets the field is caught here."""
    _survey(tmp_path)
    _gate_survey(tmp_path)
    for slug in ("mixed", "gated"):
        entry = _build(tmp_path, slug=slug)
        assert entry["stations_dropped"], slug
        for row in entry["stations_dropped"]:
            assert row.get("file"), (slug, row)
            assert row["file"].endswith(".edi"), (slug, row)


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
    _gate_survey(tmp_path)     # both drop shapes in the one report the schema must accept
    out = tmp_path / "out"
    rc = build_portal.main(["--surveys", str(tmp_path / "surveys"), "--out", str(out),
                            "--no-validate", "--products", str(out / "products")])
    assert rc == 0
    report = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    jsonschema.validate(report, SCHEMA)
    items = SCHEMA["definitions"]["survey"]["properties"]["source_parse_failures"]["items"]
    assert items["required"] == ["station", "file", "error"]
    assert items["additionalProperties"] is False
    # The drop row learned `file`. It is NOT in `required`: verify.py --data-dir validates a
    # build_report that is already ON DISK, which during a rollback or a pre-swap check is one an
    # older engine wrote with no file names in it, and a required field would fail that report for
    # a gap the current build cannot have. What the current build emits is pinned above instead.
    drop_items = SCHEMA["definitions"]["survey"]["properties"]["stations_dropped"]["items"]
    assert drop_items["required"] == ["station", "reason"]
    assert drop_items["additionalProperties"] is False
    assert "file" in drop_items["properties"]


# An .edi whose DEFINEMEAS declares an impossible reference latitude: mt_metadata's model refuses it
# with a pydantic ValidationError, whose text is FOUR lines (a header, the field, the message and a
# docs URL). Minted, never custodian bytes; it reproduces the shape of the staged files whose
# out-of-range REFLAT the reader declines.
MULTILINE_ERROR = (b">HEAD\n  DATAID=\"BADREF\"\n  LAT=-30.0\n  LONG=136.0\n"
                   b">=DEFINEMEAS\n  REFLAT=-999.0\n  REFLONG=136.0\n>END\n")


def test_the_survey_warning_for_an_unreadable_file_is_one_line(tmp_path):
    """A survey warning is a log line and a curator-page row, so it must be one line. The reader's
    exception is not: pydantic answers an out-of-range REFLAT with four lines including a docs URL,
    and the raw text was being pasted into the warning intact. source_parse_failures carries the
    full untruncated error, so the echo loses nothing by collapsing its whitespace."""
    pkg = tmp_path / "surveys" / "badref"
    edir = pkg / "transfer_functions" / "edi"
    edir.mkdir(parents=True)
    (pkg / "survey.yaml").write_text(
        "schema_version: \"0.1\"\nname: Bad Ref\nslug: badref\ncountry: Australia\n"
        "organisation: Test Org\naccess: open\nlicense: CC-BY-4.0\n"
        "abstract: Multi-line reader error fixture survey.\n", encoding="utf-8")
    (edir / "badref.edi").write_bytes(MULTILINE_ERROR)
    (edir / REAL.name).write_bytes(REAL.read_bytes())
    entry = _build(tmp_path, slug="badref")

    named = [w for w in entry["warnings"] if "unreadable by mt_metadata" in w]
    assert len(named) == 1, entry["warnings"]
    assert "\n" not in named[0], named[0]
    assert all("\n" not in w for w in entry["warnings"]), entry["warnings"]
    assert "ValidationError" in named[0], named[0]

    rows = [f for f in entry["source_parse_failures"] if f["file"] == "badref.edi"]
    assert len(rows) == 1, entry["source_parse_failures"]
    assert "\n" in rows[0]["error"], "the structured ledger keeps the reader's full error verbatim"


WORKFLOW = REPO.parent / ".github" / "workflows" / "build-products.yml"


@pytest.mark.skipif(not WORKFLOW.is_file(),
                    reason="engine image build: workflow tree not shipped "
                           "(designed topology; the CI guards are pinned from checkout lanes)")
def test_this_file_is_in_the_pr_gate_subset():
    """Rule 8: the PR gate enumerates test files BY NAME, and this file carries the assertions the
    two deploy gates read, so it has to run on the pull request that changes them."""
    steps = re.split(r"\n(?=      - name: )", WORKFLOW.read_text(encoding="utf-8"))
    subset = [s for s in steps if "PR gate subset" in s.split("\n")[0]]
    assert len(subset) == 1, [s.split("\n")[0] for s in steps]
    assert f"tests/{Path(__file__).name}" in subset[0]
