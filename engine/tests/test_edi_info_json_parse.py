"""The >INFO JSON trailing-delimiter defect in mt_metadata 1.0.9, and the parse-only fallback.

WHY THIS EXISTS. mt_metadata 1.0.9 cannot read 246 of them. The data is fine; the reader is wrong, and it
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

FIXTURES are byte-for-byte copies out of the READ-ONLY delivery tree, custodian filenames kept. The
delivery is NOT uniform -- it mixes two >INFO dialects -- and all three are needed, because each
declines the fallback at a different guard:
  LineNo__StationNo_11.edi  -- JSON >INFO, `"Declination": 5,`, an "empower" token.
                               FAILS on stock mt_metadata 1.0.9. The defect vector.
  LineNo__StationNo_104.edi -- JSON >INFO, a `"Declination"` member, trailing commas throughout, and
                               NO "empower" token, so step 2 never fires and it READS FINE on stock.
                               The hard no-regression control: normalisation is NOT a no-op on it,
                               so only the "the read actually failed" guard keeps the retry away.
  LineNo__StationNo_39.edi  -- a PLAIN-TEXT (Phoenix/Zonge line-oriented) >INFO block: no JSON, no
                               Declination key, no trailing delimiters anywhere in the block. The
                               weaker control, and the one normalisation must leave byte-identical.
                               (Do not describe this one as a JSON >INFO file -- it is not.)

Delivery census behind those three, measured over all 312 files: 267 carry a `"Declination"` key,
246 also carry an "empower" token (these are the ones that fail stock), 21 carry the key WITHOUT the
token (104 is one of them), and 45 carry no key at all (39 is one of them).
"""
import hashlib
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "extract"))

FIX = HERE / "fixtures" / "edi-info-json"
DECL = FIX / "LineNo__StationNo_11.edi"       # JSON >INFO + "Declination": 5, + empower -> fails stock
STOCKJSON = FIX / "LineNo__StationNo_104.edi"  # JSON >INFO + Declination + commas, no empower -> parses stock
NODECL = FIX / "LineNo__StationNo_39.edi"     # plain-text >INFO, no Declination key -> parses stock

# A REAL pre-existing unrelated failure, already checked into the sibling surveys repo: capricorn
# CP3B21.edi carries reflat='--26.0322667' (a doubled minus) and raises a pydantic value_error, NOT
# a *_parsing error, and its offending input does not end in a comma. It is the natural control for
# "an unrelated failure must still fail, with its ORIGINAL error" -- see _unrelated_failure_edi below.
UNRELATED_REFLAT = "--26.0322667"

pytest.importorskip("mt_metadata")


def _mtm():
    import _mtm  # noqa: PLC0415
    return _mtm


def test_fixtures_are_present_and_carry_the_defect_shape():
    """Guards the fixtures themselves: if someone re-copies them from a corrected delivery, the
    tests below would pass vacuously. Pins the exact source line the defect keys on, AND pins what
    makes each control a control -- a fixture silently swapped for a differently-shaped file would
    otherwise leave the no-regression claim resting on a file that never had the shape it needed."""
    m = _mtm()
    assert DECL.exists() and NODECL.exists() and STOCKJSON.exists()
    decl_text = DECL.read_text(encoding="utf-8", errors="replace")
    assert '"Declination": 5,' in decl_text, "fixture no longer carries the trailing-comma member"
    assert "empower_version" in decl_text, "fixture no longer trips the Empower branch"

    # NODECL: PLAIN-TEXT >INFO. No JSON, no Declination key, and -- the property the no-op test
    # rests on -- not one trailing delimiter anywhere in the block.
    nodecl_raw = NODECL.read_bytes()
    assert b'"Declination"' not in nodecl_raw, "the plain-text control must have NO Declination key"
    assert b"empower" not in nodecl_raw.lower(), "the plain-text control must carry no empower token"
    assert m.normalise_info_json_delimiters(nodecl_raw) == nodecl_raw, \
        "the plain-text control now carries trailing delimiters; it is no longer a no-op control"

    # STOCKJSON: JSON >INFO, a Declination member, trailing delimiters present -- and NO empower
    # token, which is the only reason mt_metadata reads it. Every one of those must hold or the
    # hard no-regression control has quietly become a second copy of the defect vector.
    stock_raw = STOCKJSON.read_bytes()
    assert b'"Declination"' in stock_raw, "the JSON control must carry a Declination member"
    assert b"empower" not in stock_raw.lower(), \
        "the JSON control gained an empower token; it would now FAIL stock and prove nothing"
    assert m.normalise_info_json_delimiters(stock_raw) != stock_raw, \
        "the JSON control lost its trailing delimiters; normalisation is a no-op on it now"


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
    """No trailing delimiters in >INFO => the bytes come back IDENTICAL. This is the property guard
    3 of the retry rests on (`if fixed == raw: raise`), so it is asserted as IDENTITY -- the earlier
    idempotence form reduced to `raw == raw` on this fixture and would have stayed green even if
    normalisation had started rewriting files that do not carry the defect."""
    m = _mtm()
    raw = NODECL.read_bytes()
    assert m.normalise_info_json_delimiters(raw) == raw, \
        "normalisation is not a no-op on a file with no trailing delimiters in >INFO"


def test_normalisation_is_idempotent_where_it_actually_changes_bytes():
    """Idempotence is only meaningful on a file normalisation DOES rewrite: a second pass over an
    already-normalised >INFO block must not eat a second character."""
    m = _mtm()
    raw = DECL.read_bytes()
    once = m.normalise_info_json_delimiters(raw)
    assert once != raw, "the defect fixture is no longer changed by normalisation; this is vacuous"
    assert m.normalise_info_json_delimiters(once) == once, "normalisation is not idempotent"


# --------------------------------------------------------------------------------------------
# 3. the retry is NARROW -- unrelated failures still fail, with their original error.
#
# `_read_with_fallback` advertises FOUR independent guards. Each one is pinned INDIVIDUALLY below,
# by counting calls to `_read_once`: exactly one call means the retry never happened. A guard that
# is only pinned "in combination" is not pinned at all -- deleting it leaves the suite green, which
# is what an earlier revision of this file did for three of the four.
#
# Isolating one guard means neutralising the others (they are ANDed, so any of them can mask the one
# under test). Where a test does that it monkeypatches the *other* guards and says which, so what is
# actually being asserted stays legible.
# --------------------------------------------------------------------------------------------

def _count_reads(monkeypatch, m):
    """Wrap `_mtm._read_once` in a call counter and return the list it appends to. len(list) == 1
    means the file was read once and never retried; == 2 means the retry ran."""
    real = m._read_once
    seen: list = []

    def counting(path):
        seen.append(Path(path))
        return real(path)

    monkeypatch.setattr(m, "_read_once", counting)
    return seen


def _unrelated_failure_edi(tmp_path):
    """The DECL fixture broken for a reason the fallback has nothing to do with: the capricorn
    CP3B21 shape (reflat='--26.0322667', a doubled minus) grafted onto it. Crucially it KEEPS the
    fixture's trailing >INFO delimiters, so it is not declined for lack of anything to normalise --
    it is declined because its error is a pydantic value_error, not a scalar-parsing one."""
    broken = tmp_path / "unrelated.edi"
    broken.write_bytes(DECL.read_bytes().replace(b"REFLAT=", f"REFLAT={UNRELATED_REFLAT}#".encode(), 1))
    return broken


def _unfixable_declination_edi(tmp_path):
    """A file that carries the defect SIGNATURE but that normalisation cannot rescue: the declination
    member is non-numeric, so the value is 'north-ish,' before the retry and 'north-ish' after it.
    This is the ONLY vector that reaches the fourth guard (retry ran, retry failed)."""
    broken = tmp_path / "unfixable.edi"
    broken.write_bytes(DECL.read_bytes().replace(b'"Declination": 5,', b'"Declination": "north-ish",'))
    return broken


def test_guard1_a_non_edi_input_is_never_retried(tmp_path, monkeypatch):
    """GUARD 1 (.edi only), isolated: the signature and bytes-changed guards are forced OPEN, so the
    suffix check is the only thing left that can refuse. mt_metadata's own dispatcher would raise a
    ParseError on a .xml long before the declination error, which is why forcing the other guards is
    the only way to make this guard the sole reason for the outcome."""
    m = _mtm()
    monkeypatch.setattr(m, "_is_info_delimiter_defect", lambda exc: True)
    monkeypatch.setattr(m, "normalise_info_json_delimiters", lambda raw: raw + b"\n")
    seen = _count_reads(monkeypatch, m)
    junk = tmp_path / "notanedi.xml"
    junk.write_bytes(b"<xml>not a transfer function</xml>")
    with pytest.raises(Exception):
        m.read(junk)
    assert len(seen) == 1, f"a non-.edi input was retried through the >INFO normalisation: {seen}"


def test_guard2_a_failure_without_the_defect_signature_is_never_retried(tmp_path, monkeypatch):
    """GUARD 2 (the signature predicate), not isolated and not needing to be: the vector is a real
    .edi that DOES have normalisable >INFO bytes, so the suffix and bytes-changed guards both say
    'go'. Only the predicate stands between it and a retry."""
    m = _mtm()
    broken = _unrelated_failure_edi(tmp_path)
    assert m.normalise_info_json_delimiters(broken.read_bytes()) != broken.read_bytes(), \
        "vector has nothing to normalise; it would be declined by guard 3 and prove nothing"
    seen = _count_reads(monkeypatch, m)
    with pytest.raises(Exception) as ei:
        m.read(broken)
    assert len(seen) == 1, f"a failure with no defect signature was retried: {seen}"
    assert UNRELATED_REFLAT in str(ei.value), f"the reported error is not the reflat one: {ei.value}"


def test_guard3_no_byte_change_means_no_retry(monkeypatch):
    """GUARD 3 (normalisation must actually change bytes), isolated by forcing normalisation to be
    the identity: the read still fails with the genuine defect signature, so guards 1 and 2 both say
    'go', and only 'there is nothing to fix' can stop the retry."""
    m = _mtm()
    monkeypatch.setattr(m, "normalise_info_json_delimiters", lambda raw: raw)
    seen = _count_reads(monkeypatch, m)
    with pytest.raises(Exception) as ei:
        m.read(DECL)
    assert len(seen) == 1, f"a file with nothing to normalise was retried anyway: {seen}"
    assert "5," in str(ei.value), f"the reported error is not the original declination one: {ei.value}"


def test_guard4_a_failed_retry_reports_the_original_error_not_the_retrys(tmp_path, monkeypatch):
    """GUARD 4 (retry failed -> re-raise the ORIGINAL), the arm no earlier test reached. The retry
    genuinely RUNS here (two reads) and genuinely fails, and what surfaces must be the pre-retry
    error -- input 'north-ish,' WITH the delimiter, never the retry's 'north-ish' without it. A bare
    `raise` in that arm would surface the retry's error and silently rewrite what the curator sees."""
    m = _mtm()
    broken = _unfixable_declination_edi(tmp_path)
    seen = _count_reads(monkeypatch, m)
    with pytest.raises(Exception) as ei:
        m.read(broken)
    assert len(seen) == 2, f"the retry arm was never reached, so this test proves nothing: {seen}"
    rows = [r.get("input") for r in ei.value.errors()] if hasattr(ei.value, "errors") else []
    assert "north-ish," in rows, \
        f"the RETRY's error was reported instead of the original: {rows or str(ei.value)}"


@pytest.mark.parametrize("make_broken", [_unrelated_failure_edi, _unfixable_declination_edi],
                         ids=["declined-at-the-signature-guard", "retried-then-failed"])
def test_a_broken_file_fails_with_byte_identical_stock_behaviour(tmp_path, make_broken):
    """THE CONTRACT ITSELF, asserted directly rather than by absence: for a file the fallback cannot
    fix, `read` must be indistinguishable from stock mt_metadata. Both arms are covered -- the one
    that never retries and the one that retries and fails -- and the comparison is against the error
    STOCK actually raises (captured here from `_read_once`), not against a hand-written expectation."""
    m = _mtm()
    broken = make_broken(tmp_path)
    with pytest.raises(Exception) as stock:
        m._read_once(broken)
    with pytest.raises(Exception) as through_fallback:
        m.read(broken)
    assert type(through_fallback.value) is type(stock.value), \
        f"error CLASS changed: stock {type(stock.value).__name__} -> {type(through_fallback.value).__name__}"
    assert str(through_fallback.value) == str(stock.value), \
        f"error MESSAGE changed:\n  stock: {stock.value}\n  fallback: {through_fallback.value}"


def test_garbage_edi_still_fails(tmp_path):
    """The fallback must not turn an unreadable file into a silent success."""
    m = _mtm()
    junk = tmp_path / "junk.edi"
    junk.write_bytes(b">HEAD\nDATAID=\"x\"\n\n>INFO\n{\n  \"a\": 1,\n}\n\n>END\n")
    with pytest.raises(Exception):
        m.read(junk)


# --------------------------------------------------------------------------------------------
# 4. THE MOST IMPORTANT TEST HERE -- the normalised copy can never be served or hashed
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
# 5. THE CENTRAL CLAIM, end to end through a REAL build: a station that needed the fallback
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
    assert any("trailing delimiter" in w for w in entry["warnings"]), \
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
    """NO-REGRESSION: the control fixture is a plain-text >INFO file from the SAME delivery. It must
    build with an EMPTY fallback ledger and no warning, i.e. the new path is inert for every file
    mt_metadata can already read. (`test_a_json_info_survey_that_parses_stock_records_no_fallback`
    below is the harder no-regression control: JSON >INFO, Declination key, trailing commas, and it
    still must not take the fallback.)"""
    import json  # noqa: PLC0415
    surveys = _survey_package(tmp_path, "clean", [NODECL])
    _out, _prod, report, _cat = _run_build(tmp_path, surveys)
    entry = report["surveys"]["clean"]
    assert entry["stations_built"] == 1
    assert entry.get("source_parse_fallbacks") == [], \
        f"a cleanly-read survey reported a fallback: {entry.get('source_parse_fallbacks')}"
    assert not any("trailing delimiter" in w for w in entry["warnings"]), \
        f"a cleanly-read survey raised the fallback warning: {entry['warnings']}"
    assert json.dumps(entry)  # the entry stays JSON-serialisable


def test_a_json_info_survey_that_parses_stock_records_no_fallback(tmp_path):
    """THE HARD NO-REGRESSION CONTROL. `NODECL` above has a plain-text >INFO block, so it exercises
    the inert path only weakly. `STOCKJSON` is the case that actually matters: a JSON >INFO block,
    a `"Declination"` member, trailing commas throughout (normalisation is NOT a no-op on it) -- and
    mt_metadata 1.0.9 reads it FINE, because it carries no "empower" token so step 2 of the defect
    never fires. It must build with an empty fallback ledger: the retry is gated on the READ having
    failed, never on the file merely looking like it could carry the defect."""
    import json  # noqa: PLC0415
    m = _mtm()
    raw = STOCKJSON.read_bytes()
    assert m.normalise_info_json_delimiters(raw) != raw, \
        "STOCKJSON no longer carries trailing delimiters; it is no longer the hard control"
    surveys = _survey_package(tmp_path, "stockjson", [STOCKJSON])
    _out, _prod, report, _cat = _run_build(tmp_path, surveys)
    entry = report["surveys"]["stockjson"]
    assert entry["stations_built"] == 1
    assert entry.get("source_parse_fallbacks") == [], \
        f"a stock-readable JSON >INFO survey reported a fallback: {entry.get('source_parse_fallbacks')}"
    assert not any("trailing delimiter" in w for w in entry["warnings"]), \
        f"a stock-readable JSON >INFO survey raised the fallback warning: {entry['warnings']}"
    assert json.dumps(entry)


# --------------------------------------------------------------------------------------------
# 6. THE SECOND SEAM. `_mtm.read` is NOT the only place the engine hands an EDI path to
#    mt_metadata: `ausmt_science.ingest.normalize` opens the source itself, and it is what produces
#    the canonical EMTF XML (and the served .xml download). A fallback wired into only one seam
#    still BUILDS the station -- from the catalogue's point of view everything is green -- and then
#    books it into build_report.xml_failures as an EDI-only station. That failure is LOUD, not
#    silent; it is simply WRONG, because it reports as unreadable a file the engine reads perfectly
#    well one function over. At Western Gawler scale it was 246 of 312 stations. These tests pin
#    BOTH seams, on the report field and on the written file, so the gap cannot be re-opened.
# --------------------------------------------------------------------------------------------

def test_normalize_reads_a_source_that_needs_the_fallback(tmp_path):
    """The unit form: normalize itself must not raise on a file that only the fallback can read."""
    from ausmt_science.ingest.normalize import normalize  # noqa: PLC0415
    res = normalize(DECL, tmp_path / "xml", survey_id="declfix", station_id="1039")
    assert Path(res.canonical_xml).exists(), "no canonical EMTF-XML was written"
    assert res.n_periods > 0, f"canonical XML certified with no periods: {res.n_periods}"


def test_the_canonical_xml_carries_the_declination_the_custodian_wrote(tmp_path):
    """Not merely "it did not raise": the value recovered by the fallback must reach the canonical
    artefact. A degenerate parse that produced an XML with a defaulted declination would satisfy the
    test above and would still be wrong."""
    import re as _re  # noqa: PLC0415
    from ausmt_science.ingest.normalize import normalize  # noqa: PLC0415
    res = normalize(DECL, tmp_path / "xml", survey_id="declfix", station_id="1039")
    xml = Path(res.canonical_xml).read_text(encoding="utf-8", errors="replace")
    found = _re.search(r"<Declination[^>]*>([^<]+)</Declination>", xml)
    assert found, "the canonical XML carries no Declination element"
    assert float(found.group(1)) == pytest.approx(5.0), \
        f"canonical XML declination is {found.group(1)!r}, not the custodian's 5"


def test_normalize_leaves_the_source_bytes_untouched(tmp_path):
    """D1 through the SECOND seam too: normalize reads the custodian's file, never rewrites it."""
    from ausmt_science.ingest.normalize import normalize  # noqa: PLC0415
    before = hashlib.sha256(DECL.read_bytes()).hexdigest()
    normalize(DECL, tmp_path / "xml", survey_id="declfix", station_id="1039")
    assert hashlib.sha256(DECL.read_bytes()).hexdigest() == before, \
        "normalize() modified the source EDI"


def test_a_fallback_parsed_station_still_serves_its_canonical_xml(tmp_path):
    """The end-to-end form, through a real build: a fallback-parsed station must appear in
    out/xml/<slug>/ and must NOT be counted as an XML-emission failure. This is the assertion that
    catches a fallback wired into the catalogue seam only."""
    surveys = _survey_package(tmp_path, "declfix", [DECL])
    out, _prod, report, _cat = _run_build(tmp_path, surveys)
    entry = report["surveys"]["declfix"]
    assert entry["stations_built"] == 1, f"the fallback station did not build: {entry}"
    assert entry["xml_failures"] == [], \
        f"the fallback station failed EMTF-XML emission: {entry['xml_failures']}"
    assert not any("EMTF-XML emission failed" in w for w in entry["warnings"]), \
        f"the build reported an XML-emission failure: {entry['warnings']}"
    written = sorted(p.name for p in (out / "xml" / "declfix").glob("*.xml"))
    assert written == ["1_039.xml"], f"canonical XML not served for the fallback station: {written}"

