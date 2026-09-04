"""runs[] on the promoted station.json: the D2 gate, the D9 channel rule, and the run ids.

A run is an ACQUISITION, so a run may be published only where a source states one. D2: a station
gets runs[] when its own >INFO asserts a source run id or a real acquisition fact, and never from
the placeholder run mt_metadata instantiates for every file it reads. The identifier comes from the
persistent per-survey run-id store in the surveys package (`run-ids.yaml`), assigned once and never
regenerated: where the store has no row the station publishes no runs at all, because the emitter is
not allowed to invent an id at build time.

D9 decides which channels ride the run: a channel enters channels[] only when corroborated beyond
DEFINEMEAS alone, which here means the >INFO names it or the transfer function measured it. A source
assertion CONTRADICTING the channel list wins over both, and the corpus fixture for that is
newer-volcanic-province-2019's A1.edi, which states that its HZ/RX/RY channel declarations are
exporter template artifacts.

NON-VACUOUS (Invariant 10): the unit half assembles runs from the REAL >INFO bytes of the dialect
fixtures, and the build half reads station.json out of an actual build and validates it against the
shipped 0.1 schema artifact, so a run that violated the run-nominal-rate conditional or published a
library default would fail on the document rather than on a mock.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SURVEYS = HERE / "fixtures"                         # vendored, self-contained (as in test_mtcat.py)
RUNFACTS = HERE / "fixtures" / "runfacts"
SCHEMA = json.loads((ROOT / "schema" / "ausmt-station.schema.json").read_text(encoding="utf-8"))
sys.path.insert(0, str(ROOT / "extract"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import _runfacts as rf   # noqa: E402
import _runids as runids  # noqa: E402
import build_portal as bp  # noqa: E402
from test_run_facts import qualify_lemimt  # noqa: E402


def _facts(name):
    return rf.run_facts((RUNFACTS / f"{name}.info").read_text(encoding="utf-8"))


# ---- the run-facts gate ---------------------------------------------------------------------------

def test_a_station_asserting_no_acquisition_fact_publishes_no_runs():
    """The Geotools survey header states nothing, so there is no run to publish and no id to look
    up. A placeholder run for structural uniformity is exactly what the scope forbids."""
    runs, notes = bp.station_runs(_facts("ga-geotools"), {"OCCD30": ["OCCD30-r01"]}, "OCCD30", "Z")
    assert runs == []
    assert notes == []


def test_a_qualifying_station_with_no_stored_id_publishes_no_runs_and_says_so():
    """Fail closed: the store is the id authority (assigned once, never regenerated), so a missing
    row is a curation gap the build REPORTS, never one the emitter fills in."""
    runs, notes = bp.station_runs(_facts("enriched-dotted"), {}, "A1", "Z")
    assert runs == []
    assert any("run-id store" in n for n in notes), notes


def test_the_source_run_id_is_the_stored_one_not_the_parsed_placeholder():
    """The store carries the SOURCE id verbatim where the source declares one."""
    runs, _notes = bp.station_runs(_facts("enriched-dotted"), {"A1": ["A1_001"]}, "A1", "Z")
    assert [r["id"] for r in runs] == ["A1_001"]


def test_only_one_run_is_published_and_a_longer_row_is_reported():
    """No corpus source describes two acquisitions for one station, so a second stored id is a
    curation signal rather than a licence to split the facts across runs."""
    runs, notes = bp.station_runs(_facts("enriched-dotted"), {"A1": ["A1_001", "A1_002"]}, "A1", "Z")
    assert len(runs) == 1
    assert any("A1_002" in n for n in notes), notes


# ---- the run document ---------------------------------------------------------------------------

def test_the_enriched_run_carries_the_whole_source_record():
    runs, _notes = bp.station_runs(_facts("enriched-dotted"), {"A1": ["A1_001"]}, "A1", "Z")
    run = runs[0]
    assert run["sample_rate_hz"] == 1000.0
    assert run["time_period"] == {"start": "2019-08-20T10:53:03.000000+00:00",
                                  "end": "2019-08-22T09:42:38.534000+00:00"}
    assert run["data_logger"]["serial_number"] == "#0034"
    assert run["data_logger"]["identifiers"] == [{"scheme": "DOI",
                                                  "identifier": "10.82388/u3jf7ztm"}]
    ex = next(c for c in run["channels"] if c["component"] == "ex")
    assert ex["dipole_length_m"] == 43.0
    assert ex["contact_resistance"] == {"source_value": "1.82 kilo-ohms", "value": 1820.0,
                                        "unit": "ohm"}


def test_end_is_absent_when_unknown_and_never_null():
    """The schema types `end` as a date-time string with no null branch: absence is the open-world
    statement that the source did not say when the acquisition stopped."""
    facts = _facts("enriched-dotted")
    facts["run"]["time_period"].pop("end")
    runs, _notes = bp.station_runs(facts, {"A1": ["A1_001"]}, "A1", "Z")
    assert "end" not in runs[0]["time_period"]
    assert runs[0]["time_period"]["start"]


def test_a_window_with_no_start_is_not_published_at_all():
    """time_period requires start; an end alone is not an acquisition window."""
    facts = _facts("enriched-dotted")
    facts["run"]["time_period"] = {"end": "2019-08-22T09:42:38.534000+00:00"}
    runs, _notes = bp.station_runs(facts, {"A1": ["A1_001"]}, "A1", "Z")
    assert "time_period" not in runs[0]


# --- Which channels ride the run ------------------------------------------------------------

def test_the_channel_list_is_corroborated_never_taken_from_definemeas():
    """The >INFO names four channels and the transfer function measured an impedance; DEFINEMEAS is
    not consulted at all, so nothing rides in on a declaration alone."""
    runs, _notes = bp.station_runs(_facts("enriched-dotted"), {"A1": ["A1_001"]}, "A1", "Z")
    assert [c["component"] for c in runs[0]["channels"]] == ["ex", "ey", "hx", "hy"]


def test_a_source_note_contradicting_the_channel_list_wins():
    """D9's exclusion rule and its corpus fixture: A1.edi's own caveat removes HZ/RX/RY even when
    the transfer function carries a tipper, which would otherwise corroborate hz."""
    runs, _notes = bp.station_runs(_facts("enriched-dotted"), {"A1": ["A1_001"]}, "A1", "ZT")
    assert "hz" not in [c["component"] for c in runs[0]["channels"]]


def test_a_tipper_corroborates_hz_where_no_note_excludes_it():
    """The same rule the other way, so the exclusion above is not vacuous."""
    facts = _facts("enriched-dotted")
    facts["excluded_components"] = []
    runs, _notes = bp.station_runs(facts, {"A1": ["A1_001"]}, "A1", "ZT")
    assert "hz" in [c["component"] for c in runs[0]["channels"]]


def test_remote_reference_channels_never_enter_the_run():
    """The rr* channels are governed by the presence rule, not by corroboration. They are
    mt_metadata run defaults and no corpus source declares them."""
    facts = _facts("enriched-dotted")
    facts["named_components"] = facts["named_components"] + ["rrhx", "rrhy"]
    runs, _notes = bp.station_runs(facts, {"A1": ["A1_001"]}, "A1", "Z")
    assert not [c for c in runs[0]["channels"] if c["component"].startswith("rr")]


def test_electrode_circuit_fields_never_land_on_a_magnetic_channel():
    """The schema rejects the combination; the emitter refuses it first, so a future extractor
    cannot produce a document that only the validator catches."""
    facts = _facts("enriched-dotted")
    facts["channels"]["hx"]["dipole_length_m"] = 43.0
    facts["channels"]["ex"]["sensor"] = {"model": "not-a-sensor"}
    runs, _notes = bp.station_runs(facts, {"A1": ["A1_001"]}, "A1", "Z")
    channels = {c["component"]: c for c in runs[0]["channels"]}
    assert "dipole_length_m" not in channels["hx"]
    assert "sensor" not in channels["ex"]


def test_the_run_nominal_rate_conditional_is_honoured():
    """schema: a run whose channels declare a rate MUST declare its own nominal rate, so the survey
    rate rollup can never silently lose one. With no run rate the channel rate is dropped."""
    facts = _facts("enriched-dotted")
    facts["run"].pop("sample_rate_hz")
    facts["channels"]["ex"]["sample_rate_hz"] = 1000.0
    runs, notes = bp.station_runs(facts, {"A1": ["A1_001"]}, "A1", "Z")
    channels = {c["component"]: c for c in runs[0]["channels"]}
    assert "sample_rate_hz" not in channels["ex"]
    assert any("nominal" in n for n in notes), notes


# ---- the store ----------------------------------------------------------------------------------

def test_the_store_is_read_from_the_survey_package(tmp_path):
    pkg = tmp_path / "s"
    pkg.mkdir()
    (pkg / "run-ids.yaml").write_text("run_ids:\n  A1: [A1_001]\n  A2: [A2-r01]\n", encoding="utf-8")
    assert runids.load(pkg) == {"A1": ["A1_001"], "A2": ["A2-r01"]}


def test_a_package_with_no_store_asserts_nothing(tmp_path):
    pkg = tmp_path / "s"
    pkg.mkdir()
    assert runids.load(pkg) == {}


def test_a_duplicate_run_id_is_refused(tmp_path):
    """Run ids are unique within a station record and the store is the authority; a store that
    hands the same id to two stations is refused rather than half-applied."""
    pkg = tmp_path / "s"
    pkg.mkdir()
    (pkg / "run-ids.yaml").write_text("run_ids:\n  A1: [X_001]\n  A2: [X_001]\n", encoding="utf-8")
    with pytest.raises(runids.RunIdError):
        runids.load(pkg)


# ---- over a real build --------------------------------------------------------------------------

def _build(tmp_path):
    """The vendored packages, STAGED and given the LEMIMT logger line. The shipped EDIs are real
    Vulcan bytes stating only the DECLINED band token, so an in-place build would publish no runs at
    all and the pins below would prove nothing."""
    staged = tmp_path / "surveys"
    shutil.copytree(SURVEYS, staged)
    for package in sorted(p.parent for p in staged.glob("*/survey.yaml")):
        qualify_lemimt(package)
    out = tmp_path / "data"
    r = subprocess.run(
        [sys.executable, "-m", "extract.build_portal", "--surveys", str(staged),
         "--out", str(out), "--no-validate"],
        cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out


def _station(out, slug, station):
    return json.loads((out / "products" / slug / station / "station.json").read_text(encoding="utf-8"))


def test_a_built_station_publishes_its_run_and_validates(tmp_path):
    """FAILS against the pre-A7 emitter, which published no runs[] at all."""
    pytest.importorskip("mt_metadata")
    jsonschema = pytest.importorskip("jsonschema")
    out = _build(tmp_path)
    doc = _station(out, "example-survey", "EXAMPLE01")
    assert doc["runs"] == [{"id": "EXAMPLE01-r01", "data_logger": {"model": "LEMI-424"},
                            "channels": [{"component": "ex"}, {"component": "ey"},
                                         {"component": "hx"}, {"component": "hy"}]}]
    jsonschema.Draft7Validator(SCHEMA, format_checker=jsonschema.FormatChecker()).validate(doc)


def test_no_built_run_carries_a_library_default(tmp_path):
    """Freeze gate 15 over emitted bytes: the placeholder run id, the 0 Hz rate, the 1980 epoch, the
    empty logger and the rr* channels are absent from every published run."""
    pytest.importorskip("mt_metadata")
    out = _build(tmp_path)
    for path in sorted((out / "products").rglob("station.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        station = doc.get("station", "")
        for run in doc.get("runs", []):
            assert run["id"] != f"{station}a", path
            assert run.get("sample_rate_hz", 1) > 0, path
            assert "1980-01-01" not in json.dumps(run.get("time_period", {})), path
            assert run.get("data_logger", {"x": 1}) != {}, path
            assert not [c for c in run.get("channels", []) if c["component"].startswith("rr")], path
