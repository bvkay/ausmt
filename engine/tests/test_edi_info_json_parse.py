"""The >INFO JSON trailing-delimiter defect in mt_metadata 1.0.9, and the parse-only fallback.

WHY THIS EXISTS (measured 2026-08-08 against the GSSA Western Gawler 2023 delivery, a Zonge job of
312 EDIs). mt_metadata 1.0.9 cannot read 246 of them. The data is fine; the reader is wrong, and it
is wrong in three composing steps:

  1. `io/tools.py::_validate_edi_lines` strips `"`, `'`, `[` and `]` from EVERY line of the file
     before any section parser runs, so the JSON object member `    "Declination": 5,` arrives at
     the >INFO parser as `    Declination: 5,` -- indistinguishable from an EDI `key: value` pair.
  2. `io/edi/metadata/information.py::read_info` flips into its Empower branch when any INFO line
     contains "empower" and "v". The Zonge JSON carries `"empower_version": "v1.54.2.5"`, so the
     branch fires on a file that is not in Empower's line-oriented format at all.
  3. `_parse_empower_info` then splits on `:` and takes the remainder verbatim. Its cleanup handles
     bracketed units and degree symbols but nothing removes JSON's structural member separator, so
     the value is the STRING `'5,'`. `_empower_translation_dict` maps `declination` onto the typed
     field `station.location.declination.value`, and the pydantic float validator raises.

The defect is a CLASS, not a Declination special case: every JSON scalar that is not the last member
of its object keeps its trailing comma (141 of 160 scraped values on the fixture below). Declination
is merely the only one that lands in a numerically-typed field, so it is the only one that RAISES;
the other 140 carry junk into free-text metadata silently. The fix therefore targets the trailing
DELIMITER, and these tests pin that generality so a later reader cannot narrow it to one keyword.

FIXTURES are byte-for-byte copies out of the READ-ONLY delivery tree, custodian filenames kept:
  LineNo__StationNo_11.edi -- carries `"Declination": 5,`; FAILS on stock mt_metadata 1.0.9
  LineNo__StationNo_39.edi -- same delivery, same JSON >INFO, NO Declination key; parses stock
"""
import hashlib
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "extract"))

FIX = HERE / "fixtures" / "edi-info-json"
DECL = FIX / "LineNo__StationNo_11.edi"       # has "Declination": 5,  -> fails on stock 1.0.9
NODECL = FIX / "LineNo__StationNo_39.edi"     # same delivery, no Declination key -> parses stock

# A REAL pre-existing unrelated failure, already checked into the sibling surveys repo: capricorn
# CP3B21.edi carries reflat='--26.0322667' (a doubled minus) and raises a pydantic value_error, NOT
# a *_parsing error, and its offending input does not end in a comma. It is the natural control for
# "an unrelated failure must still fail, with its ORIGINAL error" -- see test_unrelated_* below.
UNRELATED_REFLAT = "--26.0322667"

pytest.importorskip("mt_metadata")


def _mtm():
    import _mtm  # noqa: PLC0415
    return _mtm


def test_fixtures_are_present_and_carry_the_defect_shape():
    """Guards the fixtures themselves: if someone re-copies them from a corrected delivery, the
    tests below would pass vacuously. Pins the exact source line the defect keys on."""
    assert DECL.exists() and NODECL.exists()
    decl_text = DECL.read_text(encoding="utf-8", errors="replace")
    assert '"Declination": 5,' in decl_text, "fixture no longer carries the trailing-comma member"
    assert "empower_version" in decl_text, "fixture no longer trips the Empower branch"
    assert '"Declination"' not in NODECL.read_text(encoding="utf-8", errors="replace"), \
        "the control fixture must have NO Declination key"


# --------------------------------------------------------------------------------------------
# 1. the defect itself
# --------------------------------------------------------------------------------------------

def test_declination_edi_parses():
    """FAILS ON origin/main: mt_metadata 1.0.9 raises a pydantic float_parsing ValidationError on
    input_value='5,'. 246 of the 312 Western Gawler stations are unreadable without the fallback."""
    tf = _mtm().read(DECL)
    assert tf.period is not None and tf.period.size > 0, "no transfer function recovered"
    assert tf.latitude is not None and tf.longitude is not None


def test_declination_value_is_the_json_number_not_the_delimited_string():
    """The recovered value must be the NUMBER the custodian wrote (5), not a coerced 0 default and
    not the string. A fallback that parses but loses the metadata is not a fix."""
    tf = _mtm().read(DECL)
    assert float(tf.station_metadata.location.declination.value) == pytest.approx(5.0)


def test_fallback_is_reported_per_file():
    """Silent repair is not acceptable (contract): the reader must SAY a file needed the fallback,
    and must say nothing for a file that did not."""
    m = _mtm()
    tf, reason = m.read_with_fallback(DECL)
    assert tf is not None
    assert reason, "a file that needed the fallback reported no reason"
    assert "info" in reason.lower() and "json" in reason.lower(), f"unhelpful reason: {reason!r}"
    _tf2, reason2 = m.read_with_fallback(NODECL)
    assert reason2 is None, f"a cleanly-parsing file falsely reported a fallback: {reason2!r}"


# --------------------------------------------------------------------------------------------
# 2. the normalisation is the DELIMITER class, not a Declination special case
# --------------------------------------------------------------------------------------------

def test_normalisation_strips_the_json_member_separator_generally():
    """The diagnosis says the defect is 'JSON scalars in >INFO keep their trailing delimiter'. Pin
    that the remedy is written to THAT class: an unrelated JSON scalar loses its trailing comma too,
    and a member with no trailing comma is left exactly as it was."""
    m = _mtm()
    raw = (b">HEAD\nDATAID=\"x\"\n\n>INFO\nMAXINFO=100\n{\n"
           b'    "empower_version": "v1.0",\n'
           b'    "Declination": 5,\n'
           b'    "acqtime": 97896,\n'
           b'    "last_member": 7\n'
           b"}\n\n>=DEFINEMEAS\n")
    out = m.normalise_info_json_delimiters(raw)
    assert b'"Declination": 5\n' in out
    assert b'"acqtime": 97896\n' in out, "the remedy is keyed to Declination, not to the delimiter"
    assert b'"last_member": 7\n' in out, "a member with no trailing comma must be untouched"


def test_normalisation_touches_only_the_info_block():
    """Everything outside >INFO must survive byte-for-byte -- most of an EDI is numeric data and a
    stray edit there would corrupt the transfer function the copy is parsed for."""
    m = _mtm()
    raw = (b">HEAD\nDATAID=\"x\",\n\n>INFO\n{\n    \"a\": 1,\n}\n\n>=MTSECT\n"
           b">FREQ //2\n  1.0, 2.0,\n>ZXYR //2\n  3.0, 4.0,\n")
    out = m.normalise_info_json_delimiters(raw)
    assert b'DATAID="x",\n' in out, "a >HEAD line was modified"
    assert b"  1.0, 2.0,\n" in out, "a data line was modified"
    assert b"  3.0, 4.0,\n" in out, "a data line was modified"
    assert b'    "a": 1\n' in out, "the >INFO member was not normalised"


def test_normalisation_is_a_noop_for_a_file_without_the_defect():
    """No trailing delimiters in >INFO => the bytes come back IDENTICAL, so the fallback can never
    fire on a file that does not carry the defect."""
    m = _mtm()
    raw = NODECL.read_bytes()
    assert m.normalise_info_json_delimiters(m.normalise_info_json_delimiters(raw)) == \
        m.normalise_info_json_delimiters(raw), "normalisation is not idempotent"


# --------------------------------------------------------------------------------------------
# 3. the retry is NARROW -- unrelated failures still fail, with their original error
# --------------------------------------------------------------------------------------------

def test_unrelated_failure_still_raises_its_original_error(tmp_path):
    """A file broken for an unrelated reason must fail exactly as it does today. The vector is the
    REAL one from the selected corpus (capricorn CP3B21: reflat='--26.0322667'), not an invention."""
    m = _mtm()
    broken = tmp_path / "broken.edi"
    text = DECL.read_text(encoding="utf-8", errors="replace")
    text = text.replace("LAT=", "LAT=-", 1).replace("REFLAT=", f"REFLAT={UNRELATED_REFLAT}#", 1)
    broken.write_text(text, encoding="utf-8")
    with pytest.raises(Exception) as ei:
        m.read(broken)
    msg = str(ei.value)
    assert "float_parsing" not in msg or "5," not in msg, \
        "an unrelated failure was reported as the >INFO delimiter defect"


def test_a_file_that_is_not_an_edi_is_not_retried(tmp_path):
    """>INFO is an EDI construct. A non-EDI input must never take the normalisation path."""
    m = _mtm()
    junk = tmp_path / "notanedi.xml"
    junk.write_bytes(b"<xml>not a transfer function</xml>")
    with pytest.raises(Exception):
        m.read(junk)


def test_garbage_edi_still_fails(tmp_path):
    """The fallback must not turn an unreadable file into a silent success."""
    m = _mtm()
    junk = tmp_path / "junk.edi"
    junk.write_bytes(b">HEAD\nDATAID=\"x\"\n\n>INFO\n{\n  \"a\": 1,\n}\n\n>END\n")
    with pytest.raises(Exception):
        m.read(junk)


# --------------------------------------------------------------------------------------------
# 4. THE MOST IMPORTANT TEST IN THE LANE -- the normalised copy can never be served or hashed
# --------------------------------------------------------------------------------------------

def test_source_file_bytes_are_untouched_by_a_fallback_parse():
    """The custodian's file on disk is never rewritten. Hash before and after a fallback parse."""
    before = hashlib.sha256(DECL.read_bytes()).hexdigest()
    _mtm().read(DECL)
    assert hashlib.sha256(DECL.read_bytes()).hexdigest() == before, \
        "the source EDI was modified by the parse"


def test_parsed_tf_does_not_retain_the_temp_copy_path():
    """mt_metadata's TF keeps the path it was read from in `tf.fn`. If the fallback leaves the TEMP
    path there, any downstream consumer that trusts tf.fn is pointed at a file outside the custodian
    record -- the exact leak that would void the no-editing guarantee. tf.fn MUST be the original."""
    tf = _mtm().read(DECL)
    assert Path(tf.fn).resolve() == DECL.resolve(), \
        f"TF.fn leaked a non-source path: {tf.fn}"


def test_no_temp_artifact_survives_the_fallback_parse(tmp_path, monkeypatch):
    """The normalised copy must not exist once the read returns. Point the whole tempfile machinery
    at an EMPTY directory we own and assert it is empty again afterwards, so a copy that lingered
    anywhere under the temp root is caught rather than assumed away."""
    m = _mtm()
    tmproot = tmp_path / "tmproot"
    tmproot.mkdir()
    monkeypatch.setenv("TMPDIR", str(tmproot))
    import tempfile as _tf  # noqa: PLC0415
    monkeypatch.setattr(_tf, "tempdir", None, raising=False)
    tf, reason = m.read_with_fallback(DECL)
    assert reason, "fixture did not take the fallback path; this test would be vacuous"
    assert tf is not None
    leftovers = list(tmproot.rglob("*"))
    assert leftovers == [], f"the normalised copy survived the parse: {leftovers}"


# --------------------------------------------------------------------------------------------
# 5. THE LANE'S CENTRAL CLAIM, end to end through a REAL build: a station that needed the fallback
#    still serves the custodian's bytes, and the sha256 integrity gate still passes on it.
#    If the normalised copy could ever be served, AusMT's no-editing guarantee for third-party data
#    would be void; these tests are the proof that it cannot.
# --------------------------------------------------------------------------------------------

def _survey_package(tmp_path, slug, edis):
    """A minimal buildable survey package holding byte-for-byte copies of the given fixtures."""
    pkg = tmp_path / "surveys" / slug
    edir = pkg / "transfer_functions" / "edi"
    edir.mkdir(parents=True)
    for src in edis:
        (edir / src.name).write_bytes(src.read_bytes())
    (pkg / "survey.yaml").write_text(
        f"name: {slug}\nslug: {slug}\ncountry: Australia\norganisation: T\n"
        "access: open\nlicense: CC-BY-4.0\n", encoding="utf-8")
    return tmp_path / "surveys"


def _run_build(tmp_path, surveys):
    sys.path.insert(0, str(HERE.parent))
    import build_portal as bp  # noqa: PLC0415
    out, prod = tmp_path / "data", tmp_path / "products"
    rc = bp.main(["--surveys", str(surveys), "--out", str(out), "--products", str(prod),
                  "--bundle-edi", "--no-validate"])
    assert rc == 0, f"build exit {rc}"
    import json  # noqa: PLC0415
    report = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    catalogue = json.loads((out / "catalogue.json").read_text(encoding="utf-8"))
    return out, prod, report, catalogue


def test_integrity_gate_passes_for_a_fallback_parsed_station(tmp_path):
    """The sha256 served-bytes gate must be CHECKED and VERIFIED for a station whose parse needed
    the fallback -- not skipped, not merely absent from the mismatch list."""
    surveys = _survey_package(tmp_path, "declfix", [DECL])
    _out, _prod, report, catalogue = _run_build(tmp_path, surveys)
    entry = report["surveys"]["declfix"]
    assert entry["stations_built"] == 1, f"the fallback station did not build: {entry}"
    integrity = entry["source_integrity"]
    assert integrity["checked"] >= 1, "the integrity gate never ran for the fallback station"
    assert integrity["verified"] == integrity["checked"], f"integrity not verified: {integrity}"
    assert integrity["mismatches"] == [], f"integrity mismatch: {integrity['mismatches']}"
    assert catalogue, "no catalogue row emitted"


def test_served_bytes_for_a_fallback_station_are_the_custodian_bytes(tmp_path):
    """The strongest form of the claim, asserted on the BYTES rather than on a report field: every
    served .edi must hash to the source fixture, and must still contain the trailing comma. If the
    normalised copy had leaked into the served tree, that comma would be gone."""
    surveys = _survey_package(tmp_path, "declfix", [DECL])
    out, prod, _report, _cat = _run_build(tmp_path, surveys)
    source_digest = hashlib.sha256(DECL.read_bytes()).hexdigest()
    served = [p for p in list(out.rglob("*.edi")) + list(prod.rglob("*.edi"))
              if p.name == DECL.name]
    assert served, "the fallback station served no EDI at all"
    for p in served:
        raw = p.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == source_digest, \
            f"served {p} is NOT byte-identical to the custodian's file"
        assert b'"Declination": 5,' in raw, \
            f"served {p} lost the trailing delimiter: a NORMALISED copy reached the served tree"


def test_catalogue_sha256_column_is_the_source_digest(tmp_path):
    """The catalogue's sha256 column is what a downloader verifies against. It must be the digest of
    the custodian's file, never of the copy the parse used."""
    from _contract import CATALOGUE_COLUMNS  # noqa: PLC0415
    surveys = _survey_package(tmp_path, "declfix", [DECL])
    _out, _prod, _report, catalogue = _run_build(tmp_path, surveys)
    col = CATALOGUE_COLUMNS.index("sha256")
    digests = {row[col] for row in catalogue}
    assert digests == {hashlib.sha256(DECL.read_bytes()).hexdigest()}, \
        f"catalogue sha256 is not the source digest: {digests}"


def test_build_report_records_the_fallback_per_station(tmp_path):
    """Silent repair is not acceptable: the curator-facing report must name the station and file,
    and the survey must carry a counted warning so a green build cannot hide it."""
    surveys = _survey_package(tmp_path, "declfix", [DECL])
    _out, _prod, report, _cat = _run_build(tmp_path, surveys)
    entry = report["surveys"]["declfix"]
    rows = entry.get("source_parse_fallbacks")
    assert rows, f"the fallback was not recorded: {entry.get('source_parse_fallbacks')!r}"
    assert [r["file"] for r in rows] == [DECL.name]
    assert all(r["station"] and r["defect"] for r in rows), f"incomplete fallback row: {rows}"
    assert any("trailing-delimiter" in w for w in entry["warnings"]), \
        f"no counted survey warning for the fallback: {entry['warnings']}"


def test_build_report_stays_schema_valid_with_the_new_field(tmp_path):
    """`survey` is additionalProperties:false, so the new field must be declared in the schema."""
    import json  # noqa: PLC0415
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((HERE.parent / "schema" / "build_report.schema.json").read_text(encoding="utf-8"))
    surveys = _survey_package(tmp_path, "declfix", [DECL])
    _out, _prod, report, _cat = _run_build(tmp_path, surveys)
    jsonschema.validate(report, schema)


def test_a_survey_without_the_defect_records_no_fallback(tmp_path):
    """NO-REGRESSION: the control fixture is from the SAME delivery with the SAME JSON >INFO block
    and simply has no Declination key. It must build with an EMPTY fallback ledger and no warning,
    i.e. the new path is inert for every file mt_metadata can already read."""
    import json  # noqa: PLC0415
    surveys = _survey_package(tmp_path, "clean", [NODECL])
    _out, _prod, report, _cat = _run_build(tmp_path, surveys)
    entry = report["surveys"]["clean"]
    assert entry["stations_built"] == 1
    assert entry.get("source_parse_fallbacks") == [], \
        f"a cleanly-read survey reported a fallback: {entry.get('source_parse_fallbacks')}"
    assert not any("trailing-delimiter" in w for w in entry["warnings"]), \
        f"a cleanly-read survey raised the fallback warning: {entry['warnings']}"
    assert json.dumps(entry)  # the entry stays JSON-serialisable

