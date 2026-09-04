"""The >INFO pre-flight: does the PREDICTION agree with what the reader actually does?

WHY THIS EXISTS. `extract/edi_preflight.py` tells a curator, before a build runs, what an EDI's
>INFO block will do to its metadata. It does that by MIRRORING mt_metadata's own scraping in stdlib
Python instead of parsing the file, because a real parse of a 312-file delivery is half a minute of
scientific stack and the check has to run at upload time on a whole package.

A mirror is only worth having if it is provably the same computation. So these tests do not assert
that the predictor produces sensible-looking output; they run the REAL mt_metadata over the same
bytes and assert the mirror reproduces `Information.info_dict` key for key and value for value, and
that the verdict matches what the reader actually did. When mt_metadata changes its scraping, this
file goes RED and the pre-flight gets fixed. It never silently starts lying, which for a check whose
whole value is trust is the only acceptable failure mode.

MEASURED AGREEMENT BEHIND THESE TESTS, over the
two corpora that live outside this repository, every file, exact:

  GSSA Western Gawler 2023 (GAWLER_PHASE_2_MT, 312 EDIs)
      predictor 66 reads / 246 needs_repair / 0 will_not_read
      engine    66 stock / 246 fallback     / 0 failed          -> 312 of 312 agree
  the selected corpus (ausmt-surveys, 1424 EDIs across 21 surveys)
      predictor 1423 reads / 0 needs_repair / 1 will_not_read
      engine    1423 stock / 0 fallback     / 1 failed          -> 1424 of 1424 agree
      (the one failure is capricorn-2010 CP3B21.edi, reflat '--26.0322667')

`test_agreement_over_an_external_corpus` reproduces exactly that on demand; it needs a corpus this
repository does not ship, so it takes one from AUSMT_PREFLIGHT_CORPUS and otherwise skips.
"""
import hashlib
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "extract"))

import edi_preflight as pf   # noqa: E402  (stdlib-only: imported BEFORE the mt_metadata gate below)

FIX = HERE / "fixtures" / "edi-info-json"
DIALECTS = HERE / "real_dialects"
DECL = FIX / "LineNo__StationNo_11.edi"        # JSON >INFO + "Declination": 5, + empower token
STOCKJSON = FIX / "LineNo__StationNo_104.edi"  # JSON >INFO + trailing commas, NO empower token
NODECL = FIX / "LineNo__StationNo_39.edi"      # plain-text >INFO, nothing wrong with it

# Every EDI this repository ships that is a real instrument/processing dialect. MEASURED
# , because an earlier version of this comment claimed more than the files deliver: of
# the six, exactly one takes the Empower branch (LineNo__StationNo_11) and the other five take the
# standard branch. NOTHING here takes the Phoenix branch, and two of the three real_dialects files
# carry no >INFO block at all. The Empower and Phoenix branches are therefore each pinned by their
# own grafted test below, against the real library.
ALL_REAL_EDIS = sorted(FIX.glob("*.edi")) + sorted(DIALECTS.glob("*.edi"))

# capricorn-2010 CP3B21.edi's doubled minus, the one pre-existing failure in the selected corpus and
# the shape of failure the >INFO fallback cannot rescue.
DOUBLED_MINUS_REFLAT = "--26.0322667"

pytest.importorskip("mt_metadata")


def _mtm():
    import _mtm  # noqa: PLC0415
    return _mtm


def _info_dict_of(path: Path) -> tuple[dict, str]:
    """(what mt_metadata really scrapes, which branch it really took) for `path`."""
    from mt_metadata.transfer_functions.io.edi import EDI  # noqa: PLC0415
    edi = EDI()
    edi.read(path)
    dialect = "empower" if edi.Info._empower_file else ("phoenix" if edi.Info._phoenix_file else "standard")
    return dict(edi.Info.info_dict), dialect


def _comparable(info: dict) -> dict:
    """Both sides flattened the same way, so the comparison is about content and not about whether a
    value happens to be an int, a str or a list."""
    return {str(k): (",".join(str(x) for x in v) if isinstance(v, list) else str(v))
            for k, v in info.items()}


def _engine_outcome(path: Path) -> str:
    """What the ENGINE does with this file today, in the pre-flight's own vocabulary: a stock read,
    a read that needed the >INFO fallback, or no read at all."""
    m = _mtm()
    try:
        m._read_once(path)
        return pf.READS
    except Exception:  # noqa: BLE001  (any stock failure; the fallback decides what happens next)
        try:
            _tf, reason = m.read_with_fallback(path)
        except Exception:  # noqa: BLE001
            return pf.WILL_NOT_READ
        return pf.NEEDS_REPAIR if reason else pf.READS


# =============================================================================================
# The mirror. Everything else in this file rests on these two.
# =============================================================================================

@pytest.mark.parametrize("path", ALL_REAL_EDIS, ids=lambda p: p.name)
def test_the_mirror_reproduces_what_mt_metadata_really_scrapes(path):
    """THE load-bearing test. The predictor re-implements `read_info`, `_parse_empower_info`,
    `_parse_standard_info` and `_parse_phoenix_info` in stdlib Python; this asserts that
    re-implementation against the real library, on every real EDI the repository ships, key for key
    and value for value -- including which of the three branches the file is routed down.

    A mirror that drifts is worse than no pre-flight at all, because a curator would be told about
    fields the reader never produces and told nothing about the ones it does."""
    real_info, real_dialect = _info_dict_of(path)
    mine, dialect, _trigger = pf.scrape_info(path.read_bytes())
    assert dialect == real_dialect, f"{path.name}: predicted the {dialect} branch, reader took {real_dialect}"
    assert _comparable(mine) == _comparable(real_info), f"{path.name}: the >INFO mirror has drifted"


@pytest.mark.parametrize("path", ALL_REAL_EDIS, ids=lambda p: p.name)
def test_the_verdict_matches_what_the_reader_actually_does(path):
    """The three-way verdict, checked against the engine rather than against expectations. Covers
    the two Western Gawler shapes that differ ONLY in whether an 'empower' token is present, which is
    the distinction the whole defect turns on."""
    assert pf.preflight_file(path)["outcome"] == _engine_outcome(path)


def test_the_mirror_is_pinned_to_the_mt_metadata_it_was_read_from():
    """If the lock moves, the mirror has to be re-read from the new source before it can be trusted.
    This is the tripwire that says so out loud instead of leaving a stale re-implementation in place."""
    import mt_metadata  # noqa: PLC0415
    assert mt_metadata.__version__ == pf.MIRRORED_MT_METADATA, (
        f"edi_preflight mirrors mt_metadata {pf.MIRRORED_MT_METADATA} but {mt_metadata.__version__} "
        "is installed: re-read io/tools.py, io/edi/metadata/information.py and "
        "io/edi/metadata/define_measurement.py, then move MIRRORED_MT_METADATA")


# A real Empower-dialect >INFO block, in the line-oriented shape the branch was actually written
# for. The fixtures this repository ships reach the Empower branch only through an "empower" token,
# so without this the OTHER two trigger words are untested, and so is the value cleanup: mt_metadata
# strips " m" and " V" from Empower values (unanchored, anywhere in the string), which is why
# `Length: 100 m` is stored as `100`. Grafted rather than shipped as a fourth EDI so what is under
# test is readable in one place.
EMPOWER_BLOCK = b"""
    Electrics
    EX
    Length: 100 m
    AC: 12 V
    Negative res: 2.5 kilo-ohms
    Azimuth: 0 deg
    Magnetics
    HX
    Sensor serial: 1234
    Detected sensor type: MTC-150"""


def _grafted_empower_edi(tmp_path) -> Path:
    path = tmp_path / "empower_block.edi"
    path.write_bytes(NODECL.read_bytes().replace(b">INFO", b">INFO" + EMPOWER_BLOCK, 1))
    return path


def test_the_other_empower_triggers_and_the_value_cleanup_are_mirrored_too(tmp_path):
    """`read_info` routes a file into the Empower branch on ANY of three tokens, not just "empower":
    the bare words "electrics" and "magnetics" do it as well, which is how four
    newer-volcanic-province-2019 EDIs end up there on the phrase "bad electrics" in a site comment.
    This pins that arm, and with it the branch's value cleanup, against the real library."""
    path = _grafted_empower_edi(tmp_path)
    real_info, real_dialect = _info_dict_of(path)
    mine, dialect, trigger = pf.scrape_info(path.read_bytes())

    assert real_dialect == dialect == "empower"
    assert trigger == "Electrics", "the report must quote the line that routed the file, verbatim"
    assert _comparable(mine) == _comparable(real_info)
    # The cleanup, spelled out: units are stripped off a length and a voltage but NOT off a
    # resistance, because "kilo-ohms" is not one of the strings mt_metadata removes.
    assert real_info["run.ex.dipole_length"] == "100"
    assert real_info["run.ex.ac.end"] == "12"
    assert real_info["run.ex.contact_resistance.start"] == "2.5 kilo-ohms"


def test_the_phoenix_branch_is_mirrored_too(tmp_path):
    """The third >INFO branch, which NO EDI in this repository reaches: `read_info` flips the whole
    block to `_parse_phoenix_info` on the words "run information", and nothing here says them. One
    grafted marker line is enough, because the plain-text fixture's own block is already Phoenix
    shaped: read that way it exercises the two-pairs-per-line column split, the `pot resist` trim,
    the `AC=..,DC=..` voltage split and the sensor manufacturer/type synthesis, all at once.

    Without this the branch was mirrored on nobody's authority but the author's reading of the
    source, which is exactly the thing the rest of this file refuses to accept anywhere else."""
    path = tmp_path / "phoenix_block.edi"
    path.write_bytes(NODECL.read_bytes().replace(b">INFO", b">INFO\n    RUN INFORMATION", 1))

    real_info, real_dialect = _info_dict_of(path)
    mine, dialect, _trigger = pf.scrape_info(path.read_bytes())
    assert real_dialect == dialect == "phoenix"
    assert _comparable(mine) == _comparable(real_info)
    # Spelled out, so a mirror that matched an EMPTY dict could not pass: the split halves of a
    # two-column line, a resistance with its units trimmed off, and a synthesised sensor make.
    assert real_info["run.ex.contact_resistance.start"] == "142.1"
    assert real_info["run.ex.ac.start"] == "12.8"
    assert real_info["hx.sensor.manufacturer"] == "Phoenix Geophysics"
    assert pf.preflight_file(path)["outcome"] == _engine_outcome(path)


def test_an_empower_block_reports_the_resistance_that_will_be_lost(tmp_path):
    """The same block, read as a curator would: the one field whose units survive the cleanup is the
    one that will not populate, and it is the only thing reported."""
    finding = pf.preflight_file(_grafted_empower_edi(tmp_path))
    assert finding["outcome"] == pf.READS
    assert [s["field"] for s in finding["silent_numeric_fields"]] == \
        ["run.ex.contact_resistance.start"]


# =============================================================================================
# The fatal case, and the SILENT cases nothing tells a curator about today.
# =============================================================================================

def test_the_unreadable_file_names_the_field_the_value_and_the_repair():
    """The Western Gawler vector. A curator has to be told three things: which station, which field,
    and that AusMT can still read it without the custodian's file being touched."""
    finding = pf.preflight_file(DECL)
    assert finding["outcome"] == pf.NEEDS_REPAIR
    assert finding["blocking_fields"][0]["field"] == "station.location.declination.value"
    assert finding["blocking_fields"][0]["field_plain"] == "magnetic declination"
    assert finding["blocking_fields"][0]["value"] == "5,"
    assert "magnetic declination" in finding["reason"]
    # The exporter token that routed a JSON block down the Empower branch, quoted back verbatim so
    # the curator can see WHY the reader treated the file as something it is not.
    assert "empower_version" in finding["empower_trigger"]


def test_the_silent_delimiter_class_is_counted_not_only_the_one_that_raises():
    """Declination is merely the only scraped value that lands in a numerically-typed field, so it is
    the only one that stops the read. On this fixture 141 of the 159 values mt_metadata STORES keep a
    trailing comma, and the other 140 ride into free-text metadata without a word to anyone. (The
    fallback module's docstring says '141 of 160'; the stored dict is 159 keys. Measured here, on the
    dict itself, so the two sides of the comparison cannot disagree.)"""
    real_info, _ = _info_dict_of(DECL)
    really_delimited = sum(1 for v in real_info.values() if isinstance(v, str) and v.rstrip().endswith(","))
    finding = pf.preflight_file(DECL)
    assert len(finding["delimited_values"]) == really_delimited == 141
    assert finding["scraped_values"] == len(real_info) == 159


def test_a_file_that_reads_perfectly_well_can_still_be_carrying_damaged_metadata():
    """The case with no error anywhere: fixture 104 has the same JSON >INFO block and the same
    trailing commas, but no 'empower' token, so the reader never routes it into the branch that
    raises. It builds green today, and 35 of its stored values carry a stray comma. This is the
    finding a curator can act on and currently has no way to see."""
    finding = pf.preflight_file(STOCKJSON)
    assert finding["outcome"] == pf.READS
    assert len(finding["delimited_values"]) == 35
    advisory = " ".join(pf._advisory_lines(finding))
    assert "35 of 49 metadata values will be stored with a trailing comma" in advisory


def test_units_in_a_number_field_are_reported_and_really_do_vanish(tmp_path):
    """The kilo-ohms class, the second silent case. `run.ex.contact_resistance.start` is a number;
    the AusMT-enriched corpus EDIs write '2.5 kilo-ohms' into it. mt_metadata catches the coercion
    failure, logs it, and carries on -- so the file reads and the station is published with NO
    contact resistance at all.

    The test proves BOTH halves on the same bytes: the pre-flight names the field, and the real
    reader really does leave it empty. Built by grafting the line onto the plain-text fixture rather
    than shipping another EDI, so what is being tested is visible in one line."""
    graft = NODECL.read_bytes().replace(
        b">INFO", b">INFO\n    run.ex.contact_resistance.start = 2.5 kilo-ohms", 1)
    edi = tmp_path / "kilo_ohms.edi"
    edi.write_bytes(graft)

    finding = pf.preflight_file(edi)
    assert finding["outcome"] == pf.READS, "units in a number field are silent, never fatal"
    silent = finding["silent_numeric_fields"]
    assert [(s["field"], s["component"], s["value"]) for s in silent] == [
        ("run.ex.contact_resistance.start", "EX", "2.5 kilo-ohms")]
    words = " ".join(pf._advisory_lines(finding))
    assert "electrode contact resistance at the start of the run" in words
    assert "2.5 kilo-ohms" in words

    # ... and now the same claim, checked against the reader instead of asserted about it, WITH a
    # control that carries the identical line minus the units. Without the control the assertion
    # below would pass just as happily on a fixture where the key never reached the channel at all,
    # and would prove nothing about units.
    lost = _mtm().read(edi).station_metadata.runs[0].channels["ex"].contact_resistance.start
    assert lost in (None, 0, 0.0), "the field populated after all; this no longer shows the silent class"

    control = tmp_path / "plain_number.edi"
    control.write_bytes(NODECL.read_bytes().replace(
        b">INFO", b">INFO\n    run.ex.contact_resistance.start = 2.5", 1))
    kept = _mtm().read(control).station_metadata.runs[0].channels["ex"].contact_resistance.start
    assert kept == 2.5, "the control did not populate either; the graft point is wrong, not the units"
    assert not pf.preflight_file(control)["silent_numeric_fields"]


def test_a_broken_reference_latitude_is_predicted_unreadable_and_really_is(tmp_path):
    """capricorn-2010 CP3B21.edi's shape: `REFLAT=--26.0322667`, a doubled minus. `read_measurement`
    sets reference positions WITHOUT a try/except, and the >INFO fallback has nothing to offer, so
    this is the 'fix it upstream' verdict -- the one the pre-flight must never confuse with the
    repairable one, because the advice a curator acts on is completely different."""
    broken = tmp_path / "doubled_minus.edi"
    broken.write_bytes(NODECL.read_bytes().replace(
        b"REFLAT=", f"REFLAT={DOUBLED_MINUS_REFLAT}#".encode(), 1))

    finding = pf.preflight_file(broken)
    assert finding["outcome"] == pf.WILL_NOT_READ
    assert finding["blocking_fields"][0]["field_plain"] == "reference latitude"
    assert DOUBLED_MINUS_REFLAT in finding["reason"]
    assert _engine_outcome(broken) == pf.WILL_NOT_READ


def test_a_declination_that_is_not_a_number_at_all_is_not_promised_a_repair(tmp_path):
    """The near-miss that separates 'needs the repair' from 'will not read': the same field, the same
    trailing comma, but a value normalisation cannot rescue. Predicting a repair here would send a
    curator away believing AusMT had it covered."""
    broken = tmp_path / "unfixable.edi"
    broken.write_bytes(DECL.read_bytes().replace(b'"Declination": 5,', b'"Declination": "north-ish",'))
    assert pf.preflight_file(broken)["outcome"] == pf.WILL_NOT_READ
    assert _engine_outcome(broken) == pf.WILL_NOT_READ


def test_the_normalisation_model_is_the_engine_fallback_byte_for_byte():
    """`edi_preflight` carries its own copy of the fallback's normalisation so it stays stdlib-only
    and importable in the gateway runner. Two copies of one rule is a drift risk, so it is pinned:
    on every real EDI here, the two produce identical bytes. If they ever diverge, the pre-flight
    would promise a repair the build does not perform."""
    m = _mtm()
    for path in ALL_REAL_EDIS:
        raw = path.read_bytes()
        assert pf._drop_trailing_delimiters(raw) == m.normalise_info_json_delimiters(raw), path.name


# =============================================================================================
# ADVERSARIAL CASES the six shipped EDIs do not exercise.
#
# The corpus-scale agreement proof needs corpora this repository cannot ship, so it skips by
# default. Everything below is a case CONSTRUCTED to break the prediction, checked against the real
# reader on every run, so a mirror gap the six real files happen not to contain still turns the
# suite red. "Not filled in" is the first class that belongs here: it is the commonest thing a
# metadata field carries, and it reaches every one of the six fields the module calls fatal.
# =============================================================================================

def _null_ish_cases() -> list[tuple[str, bytes]]:
    """Every field `_FATAL_INFO_FIELDS` models, carrying the ordinary ways a file says "empty".

    Three of them come through a JSON >INFO block, because that is what the Western Gawler shape
    actually produces and the sanitiser turns `"declination": "",` into `declination: ,` before any
    parser sees it. The rest are grafted into the plain-text fixture, one field at a time."""
    decl = DECL.read_bytes()
    plain = NODECL.read_bytes()
    cases = [
        ("json_declination_empty_last_member",
         decl.replace(b'"Declination": 5,', b'"Declination": ""')),
        ("json_declination_empty_mid_object",
         decl.replace(b'"Declination": 5,', b'"Declination": "",')),
        ("json_declination_json_null",
         decl.replace(b'"Declination": 5,', b'"Declination": null')),
    ]
    for key in sorted(pf._FATAL_INFO_FIELDS):
        for tag, value in (("empty", b""), ("the_word_None", b"None")):
            cases.append((f"{key}_{tag}",
                          plain.replace(b">INFO", b">INFO\n    " + key.encode() + b": " + value, 1)))
    return cases


@pytest.mark.parametrize("case", _null_ish_cases(), ids=lambda c: c[0])
def test_a_null_ish_value_in_a_fatal_field_is_not_a_false_alarm(case, tmp_path):
    """Proven failing on abc82d2: all 15 of these were predicted `will_not_read` while
    the reader opened every one of them, because the prediction did not mirror the NULL_VALUES skip
    `edi.py::station_metadata` performs before it assigns anything.

    A false alarm is the expensive direction for this module: the sentence shipped to the curator
    and to the submitter's status page said `magnetic declination is written as "", which is not a
    number, so no reader can open this file` about a file that opens today. Checked against the
    engine rather than against an expectation, so this cannot go green on a wrong belief."""
    name, raw = case
    path = tmp_path / f"{name}.edi"
    path.write_bytes(raw)
    predicted = pf.preflight_file(path)
    engine = _engine_outcome(path)
    assert predicted["outcome"] == engine, (
        f"{name}: predicted {predicted['outcome']}, the reader did {engine} "
        f"({predicted['reason'] or 'no reason given'})")


def test_the_null_value_list_is_pinned_to_the_one_mt_metadata_actually_uses():
    """The skip above is only right while the two lists agree. A tripwire, in the same spirit as the
    version pin: if mt_metadata adds a null-ish spelling, the mirror has to learn it rather than
    quietly start reporting that spelling fatal."""
    from mt_metadata import NULL_VALUES  # noqa: PLC0415
    assert pf._NULL_VALUES == tuple(NULL_VALUES)


def test_mt_metadata_really_skips_a_null_ish_value_before_it_reaches_a_field(tmp_path):
    """The rule both detectors mirror, OBSERVED instead of read off the source. `station_metadata`
    drops every info_dict entry whose value is in NULL_VALUES before it assigns anything, so the
    literal string "None" never lands in a field. The control carries the identical line with a real
    value, so the assertion cannot pass on a graft that never reached the field at all."""
    def _with_site_name(name: str, value: bytes) -> Path:
        path = tmp_path / name
        path.write_bytes(NODECL.read_bytes().replace(
            b">INFO", b">INFO\n    station.geographic_name: " + value, 1))
        return path

    skipped = _mtm().read(_with_site_name("null_ish.edi", b"None")).station_metadata
    assert skipped.geographic_name != "None", "the null-ish value reached the field after all"

    kept = _mtm().read(_with_site_name("real.edi", b"Coober Pedy")).station_metadata
    assert kept.geographic_name == "Coober Pedy", "the control never reached the field; the graft is wrong"


def test_an_empty_channel_number_is_not_blamed_on_its_units(tmp_path):
    """Proven failing on abc82d2: an empty contact resistance produced the sentence
    `the file supplies ""; the units make it unreadable as a number`.

    The silent class is about a value that CARRIES ITS UNITS into a number field, and the sentence
    says so. A field nobody filled in is skipped by the reader before it is ever assigned, so there
    is nothing to report and certainly no units to blame. The control keeps the units case reporting,
    so this cannot go green by silencing the whole detector."""
    def _with_resistance(name: str, value: bytes) -> Path:
        path = tmp_path / name
        path.write_bytes(NODECL.read_bytes().replace(
            b">INFO", b">INFO\n    run.ex.contact_resistance.start = " + value, 1))
        return path

    blank = pf.preflight_file(_with_resistance("blank.edi", b""))
    assert blank["silent_numeric_fields"] == [], (
        "an empty field was reported as units: " + " | ".join(pf._advisory_lines(blank)))
    assert blank["outcome"] == pf.READS == _engine_outcome(_with_resistance("blank2.edi", b""))

    units = pf.preflight_file(_with_resistance("units.edi", b"2.5 kilo-ohms"))
    assert [s["value"] for s in units["silent_numeric_fields"]] == ["2.5 kilo-ohms"]


def test_a_number_written_in_non_ascii_digits_is_predicted_unreadable_and_really_is(tmp_path):
    """Proven failing on abc82d2: predicted `reads`, the reader raised.

    The FALSE-CLEAN direction, and the only one measured anywhere in this module. `float` accepts
    any Unicode decimal digit, so `float("١٢٣")` is 123.0, but the reader's scalar
    validator refuses the same string. The control is a non-breaking space around an ASCII 5, which
    both sides accept: without it this test would pass just as happily on a predictor that called
    every non-ASCII value unreadable."""
    def _with_declination(name: str, value: str) -> Path:
        path = tmp_path / name
        line = "\n    station.location.declination.value: " + value
        path.write_bytes(NODECL.read_bytes().replace(b">INFO", b">INFO" + line.encode("utf-8"), 1))
        return path

    for name, value in (("arabic_indic.edi", "١٢٣"),
                        ("devanagari.edi", "१२३"),
                        ("fullwidth.edi", "５")):
        path = _with_declination(name, value)
        assert pf.preflight_file(path)["outcome"] == pf.WILL_NOT_READ == _engine_outcome(path), name

    padded = _with_declination("nbsp_padded.edi", " 5 ")
    assert pf.preflight_file(padded)["outcome"] == pf.READS == _engine_outcome(padded)


def test_the_bounded_advisory_names_a_file_that_will_not_read_even_when_it_sorts_last(tmp_path):
    """Proven failing on abc82d2: the one verdict that is a reason to HOLD a package was
    pushed off the end of the bounded list by files whose only problem is a stray comma.

    `preflight_tree` returns findings in path order, and the gateway advisory sliced the first
    `limit` off that list, so a will-not-read station whose filename sorts late was never named
    anywhere the submitter or the curator can see. The only trace left was the count on line one,
    which does not say WHICH file. The CLI report has always ordered worst first; this is the
    bounded surface catching up with it."""
    package = tmp_path / "package"
    package.mkdir()
    for i in range(14):
        (package / f"A{i:02d}.edi").write_bytes(DECL.read_bytes())
    (package / "ZZZ_broken.edi").write_bytes(NODECL.read_bytes().replace(
        b"REFLAT=", f"REFLAT={DOUBLED_MINUS_REFLAT}#".encode(), 1))

    report = pf.preflight_tree(package)
    assert report["summary"] == {**report["summary"], "needs_repair": 14, "will_not_read": 1}
    lines = pf.advisory_summary(report, limit=12)
    assert any("ZZZ_broken.edi" in line for line in lines), (
        "the one file that must be fixed upstream is never named: " + " | ".join(lines))


# =============================================================================================
# It is a REPORTER. It touches nothing, blocks nothing, and reads like a geophysicist wrote it.
# =============================================================================================

def test_the_check_never_writes_to_the_files_it_reads(tmp_path):
    """The never-edit rule in miniature. Anything that edits an EDI is out of scope for this module, so
    the whole tree is hashed before and after both entry points, the CLI included."""
    package = tmp_path / "package"
    package.mkdir()
    for src in (DECL, STOCKJSON, NODECL):
        (package / src.name).write_bytes(src.read_bytes())
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(package.iterdir())}

    pf.preflight_tree(package)
    assert pf.main([str(package), "--quiet", "--json", str(tmp_path / "r.json")]) == 0

    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(package.iterdir())}
    assert after == before
    assert sorted(p.name for p in package.iterdir()) == sorted(before), "the check created a file"


def test_the_cli_reports_and_never_blocks(tmp_path, capsys):
    """Exit status 0 whatever it finds, on the delivery that is 246-of-312 unreadable. A metadata
    advisory that fails somebody's pipeline step would get switched off within a week, and then the
    240 silent findings go back to being invisible. Gating belongs to the validator."""
    package = tmp_path / "package"
    package.mkdir()
    for src in (DECL, STOCKJSON, NODECL):
        (package / src.name).write_bytes(src.read_bytes())
    out_json = tmp_path / "preflight.json"

    assert pf.main([str(package), "--json", str(out_json)]) == 0
    printed = capsys.readouterr().out
    assert "needs the repair" in printed and "will not read" in printed
    assert out_json.is_file()

    report = pf.preflight_tree(package)
    assert report["summary"]["files"] == 3
    assert report["summary"]["needs_repair"] == 1
    assert report["summary"]["reads"] == 2
    assert report["summary"]["will_not_read"] == 0


def test_the_report_talks_to_a_geophysicist_not_to_a_developer(tmp_path):
    """The report has to be actionable by the person who owns the data. It names the station, the
    field and the consequence; it does not name the machinery."""
    package = tmp_path / "package"
    package.mkdir()
    for src in (DECL, STOCKJSON):
        (package / src.name).write_bytes(src.read_bytes())
    text = pf.render(pf.preflight_tree(package), root_label="package")

    assert "station 1_039" in text                    # which station, named as the BUILD names it
    assert "magnetic declination" in text             # which field, in words
    assert "never changes the file on disk" in text   # what AusMT will do about it
    assert "stray comma" in text                      # what is wrong, in words
    for jargon in ("pydantic", "ValidationError", "float_parsing", "info_dict", "Traceback"):
        assert jargon not in text, f"the report leaks implementation vocabulary: {jargon}"


@pytest.mark.parametrize("path", ALL_REAL_EDIS, ids=lambda p: p.name)
def test_the_station_named_in_the_report_is_the_station_the_build_names(path):
    """A finding a curator cannot match to a station is a finding they cannot act on. mt_metadata
    rewrites a DATAID (`1-64R` becomes `1_64R`), so the report has to rewrite it the same way."""
    assert pf.preflight_file(path)["station"] == _mtm().read(path).station


def test_a_station_id_the_reader_refuses_stops_the_file_and_is_predicted(tmp_path):
    """`read_header` validates DATAID OUTSIDE the try/except that guards the assignment, so a station
    called `MT01(a)` never opens on a stock reader. Hyphens and spaces are fine (they become
    underscores); brackets, `#` and `/` are not. Both halves checked against the reader, with a
    passing control so the test cannot go green by refusing everything.

    The VERDICT is needs_repair, not terminal: AusMT normalises the id on a temporary copy and keeps
    the custodian's own value as site_name, so the file reads. The engine oracle is what decides
    that here, exactly as it decides every other verdict in this module."""
    def _with_dataid(name: str, value: bytes) -> Path:
        path = tmp_path / name
        path.write_bytes(re.sub(rb"DATAID=\S+", b"DATAID=" + value, NODECL.read_bytes(), count=1))
        return path

    bad = _with_dataid("bad.edi", b"MT01(a)")
    finding = pf.preflight_file(bad)
    assert finding["outcome"] == pf.NEEDS_REPAIR
    assert finding["blocking_fields"][0]["field_plain"] == "station id"
    assert _engine_outcome(bad) == pf.NEEDS_REPAIR

    fine = _with_dataid("fine.edi", b"MT-01")
    assert pf.preflight_file(fine)["outcome"] == pf.READS == _engine_outcome(fine)
    assert pf.preflight_file(fine)["station"] == "MT_01"


def test_the_check_runs_without_the_scientific_stack_and_stays_fast(tmp_path):
    """SPEED IS A REQUIREMENT: this has to run at upload time over a whole package, so it must never
    reach for mt_metadata. That is asserted structurally, in a subprocess, because the guarantee is
    'the module does not import it' rather than 'it happens to be quick' -- and it is what lets the
    gateway runner import this module at all. The timing bound is deliberately loose (60 copies of
    the largest fixture, which measures ~0.25 s, against a 20 s ceiling): it is there to catch a
    change that reintroduces a real parse, not to police a laptop."""
    package = tmp_path / "package"
    package.mkdir()
    raw = DECL.read_bytes()
    for i in range(60):
        (package / f"station_{i:03d}.edi").write_bytes(raw)

    started = time.perf_counter()
    report = pf.preflight_tree(package)
    elapsed = time.perf_counter() - started
    assert report["summary"]["needs_repair"] == 60
    assert elapsed < 20.0, f"60 files took {elapsed:.1f}s; the prediction is no longer lightweight"

    probe = ("import sys; sys.path.insert(0, %r); import edi_preflight; "
             "edi_preflight.preflight_tree(%r); "
             "assert 'mt_metadata' not in sys.modules, 'edi_preflight pulled in the science stack'"
             % (str(HERE.parent / "extract"), str(package)))
    # cwd is pinned to a directory that certainly still exists: an earlier test in the suite may have
    # chdir'd into its own tmp_path, and a child process inheriting a deleted cwd fails to start at
    # all, which would look exactly like this assertion failing.
    done = subprocess.run([sys.executable, "-c", probe], cwd=str(HERE), capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_a_clean_package_says_so_plainly(tmp_path):
    """The commonest outcome must not read like a problem. A pre-flight that always prints a wall of
    text trains people to skip it."""
    package = tmp_path / "package"
    package.mkdir()
    (package / NODECL.name).write_bytes(NODECL.read_bytes())
    text = pf.render(pf.preflight_tree(package))
    assert "Nothing to report" in text


def test_an_unreadable_file_is_a_finding_not_a_crash(tmp_path):
    """A pre-flight over a package must always produce a finding list. A file it cannot open at all
    is reported as one more row, because a check that dies halfway through tells the curator nothing
    about the other 300 files."""
    package = tmp_path / "package"
    package.mkdir()
    (package / "good.edi").write_bytes(NODECL.read_bytes())
    unreadable = package / "locked.edi"
    unreadable.write_bytes(b"")
    unreadable.chmod(0o000)
    try:
        report = pf.preflight_tree(package)
    finally:
        unreadable.chmod(0o600)
    assert report["summary"]["files"] == 2
    assert {f["file"] for f in report["findings"]} == {"good.edi", "locked.edi"}


# =============================================================================================
# The corpus-scale claim, reproducible on demand.
# =============================================================================================

@pytest.mark.skipif(not __import__("os").environ.get("AUSMT_PREFLIGHT_CORPUS"),
                    reason="set AUSMT_PREFLIGHT_CORPUS to a directory of EDIs to re-prove the "
                           "predictor-versus-engine agreement at corpus scale")
def test_agreement_over_an_external_corpus():
    """Per-file, exact agreement between the prediction and the engine over a whole corpus. This is
    the claim the module's value rests on, and it is reproducible rather than merely recorded:

        AUSMT_PREFLIGHT_CORPUS=<dir> pytest -q tests/test_edi_preflight.py -k external_corpus

    Measured: 312 of 312 on the GSSA Western Gawler 2023 delivery, 1424 of 1424 on the
    selected corpus. ANY disagreement fails here, loudly, with the file named."""
    import os  # noqa: PLC0415
    root = Path(os.environ["AUSMT_PREFLIGHT_CORPUS"])
    edis = sorted(root.rglob("*.edi"))
    assert edis, f"no EDIs under {root}"
    disagreements = [(p.name, pf.preflight_file(p)["outcome"], _engine_outcome(p))
                     for p in edis]
    disagreements = [d for d in disagreements if d[1] != d[2]]
    assert not disagreements, f"{len(disagreements)} of {len(edis)} disagree: {disagreements[:10]}"
