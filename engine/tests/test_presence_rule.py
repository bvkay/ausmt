"""The presence rule (station scope, freeze gate 15): no mt_metadata default is ever emitted as a
source assertion, and every default the parse carried is REPORTED rather than silently dropped.

mt_metadata 1.0.9 is pydantic-based and instantiates a complete Run for every EDI it reads, whether
or not the file states one. The values it invents are the defaults fixture this suite pins, measured
on the vendored fixture corpus:

    run.id                              '<station>a', synthesised from the station name
    run.sample_rate                     0.0
    run.time_period.start / .end        1980-01-01T00:00:00+00:00 (the MTime epoch)
    run.data_logger.*                   empty strings / zeros
    channels[].contact_resistance.start 0.0 on every electric channel
    channels[] rrhx / rrhy              remote-reference channels no source declares

ERRCOLS01 is the defaults station: its >INFO carries a SITE line and nothing else, so every one of
those values is a library default and the source asserts none of them.

NON-VACUOUS (Invariant 10): the unit half reads the values off a REAL mt_metadata parse of that
fixture (so a library change that stopped inventing them fails here rather than passing silently),
and the build half reads build_report.json from an actual build and cross-checks its rows against
the survey-level [presence] NOTICE lines on captured stderr - two independent observables of the
same aggregation.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SURVEYS = HERE / "fixtures"                         # vendored, self-contained (as in test_mtcat.py)
DEFAULTS_EDI = SURVEYS / "errcols-survey" / "transfer_functions" / "edi" / "ERRCOLS01.edi"
sys.path.insert(0, str(ROOT / "extract"))
sys.path.insert(0, str(ROOT))
import _presence as presence  # noqa: E402
import _mtm as mtm            # noqa: E402


def _defaults_run():
    return mtm.read(DEFAULTS_EDI).station_metadata.runs[0]


# ---- the rule itself, over the mt_metadata values the defaults fixture really carries ------------

def test_the_defaults_fixture_still_carries_every_row_of_the_inventory():
    """The fixture is only a fixture while mt_metadata keeps inventing these. Read them back off a
    real parse so a library move retires the test loudly instead of leaving it vacuous."""
    run = _defaults_run()
    assert run.id == "ERRCOLS01a"
    assert run.sample_rate == 0.0
    assert str(run.time_period.end).startswith("1980-01-01")
    assert (run.data_logger.firmware.name or "") == ""
    electric = [c for c in run.channels if str(c.component).lower().startswith("e")]
    assert electric and all(c.contact_resistance.start == 0.0 for c in electric)


def test_no_inventory_value_is_asserted_by_that_source():
    """Every predicate reads False on the defaults fixture: the emitter has nothing to publish."""
    run = _defaults_run()
    assert presence.asserted_run_id(run.id, "ERRCOLS01") is False
    assert presence.asserted_sample_rate(run.sample_rate) is False
    assert presence.asserted_time(run.time_period.start) is False
    assert presence.asserted_time(run.time_period.end) is False
    assert presence.asserted_instrument(run.data_logger) is False
    for c in run.channels:
        assert presence.asserted_resistance(getattr(c, "contact_resistance", None)) is False


def test_a_real_value_is_asserted():
    """The predicates are not constant-False: a source-stated rate, window, id and logger all pass."""
    assert presence.asserted_run_id("A1_001", "A1") is True
    assert presence.asserted_sample_rate(1000.0) is True
    assert presence.asserted_time("2019-08-20T10:53:03+00:00") is True


def test_remote_reference_channels_are_run_defaults():
    """The rr* channels are mt_metadata RUN DEFAULTS, not acquired channels - the corpus CHTYPE
    census carries no RRHX at all, so DEFINEMEAS cannot be their source."""
    assert presence.is_run_default_component("rrhx") is True
    assert presence.is_run_default_component("RRHY") is True
    assert presence.is_run_default_component("hx") is False


def test_the_defaults_fixture_produces_the_whole_inventory_as_notes():
    """The reported layer: one note per default the parse carried, in the inventory's order."""
    notes = presence.run_default_notes(mtm.read(DEFAULTS_EDI))
    joined = " || ".join(notes)
    for fragment in ("run.id", "sample_rate", "time_period", "data_logger", "contact_resistance"):
        assert fragment in joined, f"{fragment!r} missing from the presence notes: {notes}"
    assert all("NOT asserted by source" in n for n in notes), notes


def test_the_rr_channel_default_is_reported_where_the_parse_carries_it():
    """ERRCOLS01's parse carries no rr* pair, EXAMPLE01's does; the note follows the parse, not the
    survey, which is what makes it evidence rather than boilerplate."""
    example = SURVEYS / "example-survey" / "transfer_functions" / "edi" / "EXAMPLE01.edi"
    assert not any("remote-reference" in n for n in presence.run_default_notes(mtm.read(DEFAULTS_EDI)))
    assert any("remote-reference" in n for n in presence.run_default_notes(mtm.read(example)))


# ---- the reported layer, over a real build ------------------------------------------------------

def _surveys_root(tmp_path):
    """Two packages: the vendored example survey, and a defaults survey carrying ERRCOLS01 alone.
    ERRCOLS01 lives in a fixture directory with no survey.yaml (it is a unit fixture), so it is
    given one here rather than added to the shared fixture root, where a third package would move
    every station count the other build tests pin."""
    root = tmp_path / "surveys"
    src = SURVEYS / "example-survey"
    shutil.copytree(src, root / "example-survey")
    pkg = root / "defaults-survey"
    (pkg / "transfer_functions" / "edi").mkdir(parents=True)
    (pkg / "survey.yaml").write_text(
        (src / "survey.yaml").read_text(encoding="utf-8")
        .replace("slug: example-survey", "slug: defaults-survey")
        .replace('name: "Example MT Survey 2026"', 'name: "Defaults Survey 2026"'), encoding="utf-8")
    shutil.copy2(DEFAULTS_EDI, pkg / "transfer_functions" / "edi" / DEFAULTS_EDI.name)
    return root


def _build(tmp_path):
    """Run the build in a subprocess so stdout+stderr are cleanly capturable as text (the idiom
    test_build_report.py uses; PYTHONIOENCODING keeps the NOTICE em dash round-tripping)."""
    out = tmp_path / "data"
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    r = subprocess.run(
        [sys.executable, "-m", "extract.build_portal", "--surveys", str(_surveys_root(tmp_path)),
         "--out", str(out), "--products", str(tmp_path / "products"), "--no-validate"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", env=env)
    assert r.returncode == 0, r.stderr
    return json.loads((out / "build_report.json").read_text(encoding="utf-8")), r


def test_build_report_carries_the_presence_rows_for_the_defaults_survey(tmp_path):
    """FAILS against the build: build_report.json had no `presence` field at all, so the
    defaults the parse dropped were invisible to a curator."""
    rep, _r = _build(tmp_path)
    rows = rep["surveys"]["defaults-survey"]["presence"]
    assert rows, "the defaults survey must report the library defaults its parse carried"
    for row in rows:
        assert "NOT asserted by source" in row["note"]
        assert row["count"] >= 1
        assert set(row) == {"note", "count", "stations", "except"}, row


def test_the_presence_rows_match_the_survey_notice_lines(tmp_path):
    """Report and log come from ONE aggregation, so a divergence between them fails here."""
    rep, r = _build(tmp_path)
    logged = [ln for ln in r.stderr.splitlines() if "[presence] NOTICE defaults-survey:" in ln]
    assert logged, f"no [presence] NOTICE lines on stderr: {r.stderr[-2000:]}"
    assert len(logged) == len(rep["surveys"]["defaults-survey"]["presence"])
    for row in rep["surveys"]["defaults-survey"]["presence"]:
        assert any(row["note"] in ln for ln in logged), row["note"]


def test_the_rule_is_per_fact_not_per_survey(tmp_path):
    """example-survey's HEAD states an acquisition date, so its run window start is a source value
    and carries no default row, while the run id neither survey states does. the defaults survey states
    no date at all and reports the window default too."""
    rep, _r = _build(tmp_path)
    example = " || ".join(row["note"] for row in rep["surveys"]["example-survey"]["presence"])
    defaults = " || ".join(row["note"] for row in rep["surveys"]["defaults-survey"]["presence"])
    assert "run.id" in example and "run.id" in defaults
    assert "time_period.start" not in example, example
    assert "time_period.start" in defaults, defaults


def test_the_rows_aggregate_by_distinct_note_across_stations(tmp_path):
    """example-survey builds two stations and both carry the run.id default, so the family's shared
    aggregation reports ONE row of count 2, never two rows."""
    rep, _r = _build(tmp_path)
    rows = [row for row in rep["surveys"]["example-survey"]["presence"] if "run.id" in row["note"]]
    assert len(rows) == 1, rows
    assert rows[0]["count"] == 2, rows[0]


# The comment-hygiene pin exempts a dotted head that is a LIBRARY CLASS from its
# "a name wearing a capital it does not have" rule, because mt_metadata's own spelling of
# Run.id and Channel.contact_resistance carries that capital. An exemption list is a claim
# about the library, so it is checked against the installed library rather than trusted.
def _hygiene_pin():
    import importlib.util
    pin = Path(__file__).with_name("test_comment_hygiene.py")
    spec = importlib.util.spec_from_file_location("_hygiene_pin", pin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resolve(name):
    """The mt_metadata class of that name, or None. Walks the package because the classes the
    engine names live in four different sub-packages."""
    import importlib
    import inspect
    import pkgutil

    import mt_metadata
    for found in pkgutil.walk_packages(mt_metadata.__path__, "mt_metadata."):
        try:
            module = importlib.import_module(found.name)
        except Exception:  # noqa: BLE001 - an optional sub-package must not fail the proof
            continue
        candidate = getattr(module, name, None)
        if inspect.isclass(candidate):
            return candidate
    return None


def test_every_exempted_class_head_is_a_real_mt_metadata_class():
    """FAILS IF a name in the pin's exemption list is not a class in the installed library: an
    exemption that names nothing is a hole in the capital rule with no library behind it."""
    heads = _hygiene_pin().LIBRARY_CLASS_HEAD
    assert heads, "the exemption list is empty, so this would prove nothing"
    missing = [name for name in heads if _resolve(name) is None]
    assert not missing, f"exempted as library classes but not classes in mt_metadata: {missing}"


def test_the_fields_the_presence_rule_names_exist_on_those_classes():
    """FAILS IF a field _presence.py names is not a field of the class the comment names: the
    capital is only right while the library spells it that way. contact_resistance is declared on
    the ELECTRIC channel rather than the base Channel, which is the channel the rule reads."""
    for class_name, field in (("Run", "id"), ("Run", "sample_rate"),
                              ("Channel", None), ("Electric", "contact_resistance")):
        owner = _resolve(class_name)
        assert owner is not None, f"mt_metadata has no class {class_name}"
        if field is None:
            continue
        assert hasattr(owner(), field), f"{class_name} has no {field}"
