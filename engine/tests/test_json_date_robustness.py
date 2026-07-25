"""JSON date-serialisation robustness across the three build layers (fix/engine-json-date-serialization).

Root cause: the add-survey form emitted attribution.declared_date as a BARE unquoted ISO date; PyYAML
safe_load implicit-types a bare ISO date to datetime.date; survey_meta_from_yaml threads the attribution
block VERBATIM into SMETA; main() serialised surveys.json/mtcat via _jdump (json.dumps with NO default
hook) -> `TypeError: Object of type date is not JSON serializable` -> the whole build crashed and the
gateway preview quarantined the submission with station_count 0. The served corpus never hit it because
curator yamls quote their dates; it was UNIVERSAL to form submissions (the licence tick is effectively
always on). The gateway hit the same bug class earlier and got a _json_default hook; the engine never did.

  LAYER 1  test_jdump_serialises_date_as_isostring / test_build_with_unquoted_declared_date_is_green:
           _jdump now ISO-formats a date instead of crashing; the full build emits surveys.json with the
           declared_date carried as the STRING "YYYY-MM-DD". RED on origin/main (the build crashed).
  LAYER 2  test_unserialisable_survey_is_dropped_not_fatal: a survey whose assembled SMETA carries an
           alien (un-serialisable) value is DROPPED alone — a sibling survey still builds, rc stays 0,
           and build_report.json records the drop. RED on origin/main (one alien value killed the corpus).

Requires the mt_metadata/mth5 build engine (importorskip otherwise); runs in the build CI job.
"""
import datetime
import json
import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")
pytest.importorskip("mth5")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SAMPLE_EDI = ROOT / "data" / "sample-survey" / "transfer_functions" / "edi"
sys.path.insert(0, str(ROOT / "extract"))
sys.path.insert(0, str(ROOT))
import build_portal as bp  # noqa: E402


def _make_package(surveys_dir: Path, slug: str, yaml_body: str) -> Path:
    """A minimal survey package: the two real sample EDIs + the given survey.yaml body."""
    pkg = surveys_dir / slug
    edi = pkg / "transfer_functions" / "edi"
    edi.mkdir(parents=True)
    for src in sorted(SAMPLE_EDI.glob("*.edi")):
        shutil.copy(src, edi / src.name)
    (pkg / "survey.yaml").write_text(yaml_body, encoding="utf-8")
    return pkg


def _yaml(slug: str, name: str, *, extra: str = "") -> str:
    return (
        'schema_version: "0.3"\n'
        f"slug: {slug}\n"
        f'name: "{name}"\n'
        "country: Australia\n"
        'organisation: "AusMT CI"\n'
        'abstract: "Robustness fixture."\n'
        'license: "CC-BY-4.0"\n'
        "data_type: BBMT\n"
        "access: { level: open }\n"
        "time_series: { levels_available: [raw_packed] }\n"
        + extra
    )


# ---------------- LAYER 1 ----------------

def test_jdump_serialises_date_as_isostring():
    """The load-bearing fix in isolation: _jdump ISO-formats a datetime.date/datetime/time instead of
    raising. On origin/main json.dumps had NO default hook, so this raised TypeError."""
    doc = {"declared_date": datetime.date(2026, 7, 25),
           "stamp": datetime.datetime(2026, 7, 25, 13, 30, 0),
           "clock": datetime.time(13, 30)}
    got = json.loads(bp._jdump(doc))
    assert got == {"declared_date": "2026-07-25", "stamp": "2026-07-25T13:30:00", "clock": "13:30:00"}


def test_jdump_still_raises_on_a_genuinely_alien_type():
    """A non-date/decimal object is a real bug and must still surface as TypeError (never blind-str()ed
    into a served product) — that raise is exactly what LAYER 2's per-survey dry-run catches."""
    with pytest.raises(TypeError):
        bp._jdump({"x": object()})


def test_build_with_unquoted_declared_date_is_green(tmp_path):
    """End-to-end: a survey.yaml carrying a BARE unquoted attribution.declared_date (the exact form
    emission) builds GREEN and surveys.json carries the date as the STRING "2026-07-25". On origin/main
    this crashed the entire build (SystemExit) and the gateway quarantined the submission."""
    surveys = tmp_path / "surveys"
    _make_package(surveys, "date-survey",
                  _yaml("date-survey", "Unquoted Date Survey",
                        extra=('attribution:\n'
                               '  declared_by: "Test Curator"\n'
                               "  declared_date: 2026-07-25\n")))   # BARE ISO date -> datetime.date

    out = tmp_path / "out"
    rc = bp.main(["--surveys", str(surveys), "--out", str(out), "--no-validate"])
    assert rc == 0, "the build must not crash on an unquoted declared_date"

    surveys_json = json.loads((out / "surveys.json").read_text(encoding="utf-8"))
    entry = surveys_json["Unquoted Date Survey"]
    dd = entry["attribution"]["declared_date"]
    assert dd == "2026-07-25" and isinstance(dd, str), \
        f"declared_date must be carried as the STRING '2026-07-25', got {dd!r}"

    # mtcat threads the SAME attribution block verbatim; it too must be a plain JSON string now.
    mtcat = json.loads((out / "mtcat.json").read_text(encoding="utf-8"))
    dsets = mtcat.get("datasets") or mtcat.get("surveys") or []
    hit = next((d for d in dsets if d.get("attribution", {}).get("declared_date")), None)
    assert hit is not None and hit["attribution"]["declared_date"] == "2026-07-25"


# ---------------- LAYER 2 ----------------

def test_unserialisable_survey_is_dropped_not_fatal(tmp_path, monkeypatch, capsys):
    """A single survey whose assembled SMETA carries a value _jdump cannot serialise (an alien type
    LAYER 1's date/decimal hook does NOT cover) is DROPPED alone — the SIBLING survey still builds, the
    build returns 0, and build_report.json records the drop naming the survey. On origin/main one alien
    value crashed the corpus build at the surveys.json emit, taking every innocent survey down with it."""
    surveys = tmp_path / "surveys"
    _make_package(surveys, "good-survey", _yaml("good-survey", "Good Survey"))
    _make_package(surveys, "poison-survey", _yaml("poison-survey", "Poison Survey"))

    # Inject an un-serialisable SMETA value for the poison survey ONLY (a genuinely alien object the
    # LAYER 1 hook re-raises on). survey_meta_from_yaml is the single seam that builds each survey's SMETA.
    _real = bp.survey_meta_from_yaml

    def _poisoned(y):
        sm = _real(y)
        if y.get("slug") == "poison-survey":
            sm["alien"] = object()   # not JSON-serialisable, and not a date/decimal
        return sm

    monkeypatch.setattr(bp, "survey_meta_from_yaml", _poisoned)

    out = tmp_path / "out"
    rc = bp.main(["--surveys", str(surveys), "--out", str(out), "--no-validate"])
    assert rc == 0, "one survey's alien metadata must not crash the whole build"

    surveys_json = json.loads((out / "surveys.json").read_text(encoding="utf-8"))
    assert "Good Survey" in surveys_json, "the healthy sibling survey must still be served"
    assert "Poison Survey" not in surveys_json, "the un-serialisable survey must be withheld entirely"

    # the drop is on the record: build_report.json names the survey and the cause.
    report = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    poison = report["surveys"].get("poison-survey")
    assert poison is not None, "the dropped survey must still appear in build_report.json (never vanish silently)"
    assert poison["stations_built"] == 0
    assert any("not JSON-serializable" in w for w in poison["warnings"]), \
        f"the report warning must name the serialisation cause, got {poison['warnings']!r}"

    # and a loud stderr line named it.
    err = capsys.readouterr().err
    assert "poison-survey" in err and "not JSON-serializable" in err, \
        "the drop must be announced loudly on stderr"
