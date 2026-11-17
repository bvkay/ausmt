"""runs[] on an embargoed station record: the occupation window and the instruments, and no more.

An embargoed survey withholds its transfer functions and everything derived from them. When a
station was occupied, and by which logger and sensors, is not derived from them: the survey's own
run-metadata.csv states it. So an embargoed record publishes that much, through a projection that
is closed at every level, and a metadata_only record publishes none.

Two rules are pinned here, because each alone leaves a leak open:

  * the SOURCE rule: a withheld record's run is assembled from the run sheet row alone, so nothing
    read out of the withheld file (its >INFO block, the components its transfer function measured)
    can reach it;
  * the SHAPE rule: the emitter projects through the same closed key sets the semantic layer and
    the schema check, so a rate, a dipole, an azimuth or an electric channel never rides a run.
"""
import copy
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCHEMA = json.loads((ROOT / "schema" / "ausmt-station.schema.json").read_text(encoding="utf-8"))
sys.path.insert(0, str(ROOT / "extract"))
sys.path.insert(0, str(ROOT))
import _runsheet as runsheet        # noqa: E402
import _stationcheck as stcheck     # noqa: E402
import build_portal as bp           # noqa: E402

LOGGER_DOI, BX_DOI, BY_DOI = "10.82388/logger01", "10.82388/coilbx01", "10.82388/coilby01"
RUN_IDS = {"S01": ["S01_001"]}


def _sheet_row(**over):
    row = {c: "" for c in runsheet.COLUMNS if c != "station_id"}
    row.update({
        "start": "2024-03-09T23:14:51+00:00", "end": "2024-03-11T21:09:00+00:00",
        "sample_rate_hz": "1000", "dipole_length_ex_m": "50", "dipole_length_ey_m": "48",
        "azimuth_ex_deg": "0", "azimuth_ey_deg": "90",
        "logger_manufacturer": "LEMI LLC", "logger_model": "LEMI-423", "logger_serial": "#0040",
        "logger_pid": LOGGER_DOI,
        "sensor_manufacturer": "LEMI LLC", "sensor_model": "LEMI-120",
        "sensor_bx_serial": "261", "sensor_bx_pid": BX_DOI,
        "sensor_by_serial": "262", "sensor_by_pid": BY_DOI,
    })
    row.update(over)
    return row


def _logger():
    return {"manufacturer": "LEMI LLC", "model": "LEMI-423", "serial_number": "#0040",
            "identifiers": [{"scheme": "DOI", "identifier": LOGGER_DOI}]}


def _coil(serial, doi):
    return {"manufacturer": "LEMI LLC", "model": "LEMI-120", "serial_number": serial,
            "identifiers": [{"scheme": "DOI", "identifier": doi}]}


OCCUPIED = [{
    "id": "S01_001",
    "time_period": {"start": "2024-03-09T23:14:51+00:00", "end": "2024-03-11T21:09:00+00:00"},
    "data_logger": _logger(),
    "channels": [{"component": "hx", "sensor": _coil("261", BX_DOI)},
                 {"component": "hy", "sensor": _coil("262", BY_DOI)}],
}]

STUB = {
    "schema": "ausmt-station", "version": bp.STATION_SCHEMA_VERSION,
    "ausmt_id": "au.embargoed-survey.S01", "station": "S01", "survey": "Embargoed Survey",
    "survey_id": "embargoed-survey", "country": "Australia", "organisation": "Adelaide University",
    "access": {"level": "embargoed", "embargo_until": "2027-09-19", "served": False},
    "distribution": {"edi_available": False, "license": "CC-BY-4.0", "edi_path": None},
    "withheld": True, "note": "withheld",
}


def _record(level="embargoed", runs=None):
    """The withheld branch of the emitter itself, for one station."""
    meta = {"access": level, "embargo_until": "2027-09-19" if level == "embargoed" else None}
    return bp.station_document({"ausmt_id": "au.embargoed-survey.S01", "id": "S01"}, None,
                               "Embargoed Survey", "Adelaide University", meta, "CC-BY-4.0",
                               "embargoed-survey", None, None, {}, False, {}, runs)


def _validator():
    jsonschema = pytest.importorskip("jsonschema")
    return jsonschema.Draft7Validator(SCHEMA, format_checker=jsonschema.FormatChecker())


# ---- the source rule ----------------------------------------------------------------------------

def test_an_embargoed_station_publishes_its_window_and_instruments_from_the_run_sheet():
    assert bp.withheld_station_runs(True, _sheet_row(), RUN_IDS, "S01") == OCCUPIED


def test_the_rate_the_dipoles_and_the_azimuths_never_reach_a_withheld_run():
    """The sheet row states all of them; the projection carries none, and no electric channel."""
    text = json.dumps(bp.withheld_station_runs(True, _sheet_row(), RUN_IDS, "S01"))
    for withheld in ("sample_rate_hz", "dipole_length_m", "measurement_azimuth_deg", '"ex"', '"ey"'):
        assert withheld not in text, withheld


def test_only_an_embargoed_survey_publishes_a_withheld_run():
    """metadata_only is the other non-served state, and it keeps no run at all."""
    assert bp.withheld_station_runs(False, _sheet_row(), RUN_IDS, "S01") == []


def test_a_station_the_run_sheet_does_not_name_publishes_no_run():
    """There is no second source: the station's own file is what the embargo withholds."""
    assert bp.withheld_station_runs(True, None, RUN_IDS, "S01") == []
    assert bp.withheld_station_runs(True, {}, RUN_IDS, "S01") == []


def test_the_run_id_still_comes_from_the_store_alone():
    assert bp.withheld_station_runs(True, _sheet_row(), {}, "S01") == []


def test_a_sheet_row_stating_no_window_and_no_instrument_publishes_no_run():
    """A rate and two dipoles are acquisition facts, so the full record would publish a run for
    them. None of them survives the projection, and a bare run id says nothing."""
    bare = {c: "" for c in runsheet.COLUMNS if c != "station_id"}
    bare.update({"sample_rate_hz": "1000", "dipole_length_ex_m": "50", "dipole_length_ey_m": "48"})
    assert bp.withheld_station_runs(True, bare, RUN_IDS, "S01") == []


def test_a_three_axis_magnetometer_is_the_sensor_of_every_axis_it_covers():
    row = _sheet_row(sensor_manufacturer="", sensor_model="", sensor_bx_serial="", sensor_bx_pid="",
                     sensor_by_serial="", sensor_by_pid="",
                     magnetometer_manufacturer="Bartington", magnetometer_model="Mag-03",
                     magnetometer_serial="77", magnetometer_pid="10.82388/flux0077")
    (run,) = bp.withheld_station_runs(True, row, RUN_IDS, "S01")
    assert [ch["component"] for ch in run["channels"]] == ["hx", "hy", "hz"]
    assert {ch["sensor"]["serial_number"] for ch in run["channels"]} == {"77"}


def test_a_window_whose_time_basis_is_not_recognised_stays_absent():
    (run,) = bp.withheld_station_runs(True, _sheet_row(time_basis="local, offset unknown"),
                                      RUN_IDS, "S01")
    assert "time_period" not in run and run["data_logger"] == _logger()


def test_the_time_basis_rides_the_window():
    basis = runsheet.TIME_BASES[1]
    (run,) = bp.withheld_station_runs(True, _sheet_row(time_basis=basis), RUN_IDS, "S01")
    assert run["time_period"]["time_basis"] == basis


# ---- the shape rule, at the emitter -------------------------------------------------------------

FULL_RUN = {
    "id": "S01_001",
    "time_period": {"start": "2024-03-09T23:14:51+00:00", "end": "2024-03-11T21:09:00+00:00",
                    "source": "header"},
    "sample_rate_hz": 1000.0,
    "data_logger": {**_logger(), "firmware": "1.2"},
    "channels": [
        {"component": "ex", "dipole_length_m": 50.0, "measurement_azimuth_deg": 0.0,
         "contact_resistance": {"source_value": "1.8 kOhm"}},
        {"component": "hx", "measurement_azimuth_deg": 0.0, "sample_rate_hz": 1000.0,
         "sensor": {**_coil("261", BX_DOI),
                    "identifiers": [{"scheme": "DOI", "identifier": BX_DOI, "landing": "x"}]}},
        {"component": "hy", "sensor": _coil("262", BY_DOI)},
        {"component": "hz"},
    ],
}


def test_the_withheld_branch_projects_whatever_run_it_is_handed():
    """The source rule lives at the call site; this is the guarantee underneath it. A full run
    reaching the withheld branch leaves with the closed members only."""
    doc = _record(runs=[copy.deepcopy(FULL_RUN)])
    assert doc["runs"] == OCCUPIED
    assert stcheck.violations(doc) == []


def test_runs_is_appended_so_no_frozen_key_moves():
    bare, occupied = _record(), _record(runs=copy.deepcopy(OCCUPIED))
    assert "runs" not in bare
    assert list(occupied) == list(bare) + ["runs"]
    assert {k: v for k, v in occupied.items() if k != "runs"} == bare


def test_a_metadata_only_record_gains_no_run_whatever_it_is_handed():
    doc = _record(level="metadata_only", runs=copy.deepcopy(OCCUPIED))
    assert "runs" not in doc and stcheck.violations(doc) == []


def test_the_emitted_record_validates_on_the_withheld_branch():
    doc = _record(runs=copy.deepcopy(OCCUPIED))
    assert [e.message for e in _validator().iter_errors(doc)] == []


def test_the_emitter_projects_through_the_checked_key_sets():
    """One statement of the closed world, read at both ends."""
    run = bp.withheld_run(copy.deepcopy(FULL_RUN))
    assert set(run) <= stcheck.WITHHELD_RUN_KEYS
    assert set(run["time_period"]) <= stcheck.WITHHELD_PERIOD_KEYS
    assert set(run["data_logger"]) <= stcheck.WITHHELD_INSTRUMENT_KEYS
    for channel in run["channels"]:
        assert set(channel) == stcheck.WITHHELD_CHANNEL_KEYS
        assert set(channel["sensor"]) <= stcheck.WITHHELD_INSTRUMENT_KEYS
        for row in channel["sensor"]["identifiers"]:
            assert set(row) == stcheck.WITHHELD_IDENTIFIER_KEYS


# ---- the shape rule, at the semantic layer and the schema ---------------------------------------

def _stub(runs=OCCUPIED, level="embargoed"):
    doc = copy.deepcopy(STUB)
    doc["access"]["level"] = level
    if level != "embargoed":
        doc["access"]["embargo_until"] = None
    doc["runs"] = copy.deepcopy(runs)
    return doc


def _run(doc):
    return doc["runs"][0]


REJECTED = [
    ("runs on a metadata_only record", lambda d: d.update(_stub(level="metadata_only"))),
    ("a run stating only its id", lambda d: d.update({"runs": [{"id": "S01_001"}]})),
    ("an empty runs list", lambda d: d.update({"runs": []})),
    ("the run's nominal rate", lambda d: _run(d).update({"sample_rate_hz": 1000.0})),
    ("a position under the run", lambda d: _run(d).update({"location": {"lat": -33.4, "lon": 136.4}})),
    ("an electric channel", lambda d: _run(d)["channels"].append({"component": "ex"})),
    ("a dipole on a channel",
     lambda d: _run(d)["channels"].append({"component": "ex", "dipole_length_m": 50.0})),
    ("an azimuth on a magnetic channel",
     lambda d: _run(d)["channels"][0].update({"measurement_azimuth_deg": 12.0})),
    ("a magnetic channel naming no sensor", lambda d: _run(d)["channels"].append({"component": "hz"})),
    ("free text inside the logger", lambda d: _run(d)["data_logger"].update({"comments": "x"})),
    ("free text inside a sensor",
     lambda d: _run(d)["channels"][0]["sensor"].update({"comments": "x"})),
    ("an extra member on an identifier row",
     lambda d: _run(d)["data_logger"]["identifiers"][0].update({"landing": "x"})),
    ("an extra member in the window", lambda d: _run(d)["time_period"].update({"source": "header"})),
    ("a null end", lambda d: _run(d)["time_period"].update({"end": None})),
    ("a window that is not an object", lambda d: _run(d).update({"time_period": "2024-03-09"})),
    ("channels that are not a list", lambda d: _run(d).update({"channels": {"hx": {}}})),
    ("a run that is not an object", lambda d: d.update({"runs": ["S01_001"]})),
    ("runs that is not a list", lambda d: d.update({"runs": {"id": "S01_001"}})),
]
# Rules the schema cannot state; the semantic layer alone holds them.
SEMANTIC_ONLY = [
    ("a DOI in resolver form",
     lambda d: _run(d)["data_logger"]["identifiers"][0].update(
         {"identifier": "https://doi.org/" + LOGGER_DOI})),
    ("a repeated run id", lambda d: d["runs"].append(copy.deepcopy(_run(d)))),
    ("a window ending before it starts",
     lambda d: _run(d)["time_period"].update({"end": "2024-03-01T00:00:00+00:00"})),
]


def test_a_clean_embargoed_record_with_runs_has_no_violations():
    assert stcheck.violations(_stub()) == []
    assert [e.message for e in _validator().iter_errors(_stub())] == []


@pytest.mark.parametrize("why,mutate", REJECTED + SEMANTIC_ONLY,
                         ids=[w for w, _ in REJECTED + SEMANTIC_ONLY])
def test_the_semantic_layer_rejects_it_without_a_schema_validator(why, mutate):
    """The closed world is the leak protection, so it must not rest on an optional dependency,
    and a malformed record is reported, never raised on."""
    doc = _stub()
    mutate(doc)
    assert stcheck.violations(doc), why


@pytest.mark.parametrize("why,mutate", REJECTED, ids=[w for w, _ in REJECTED])
def test_the_schema_rejects_it_too(why, mutate):
    doc = _stub()
    mutate(doc)
    assert list(_validator().iter_errors(doc)), why


def test_the_schema_and_the_semantic_layer_state_one_closed_world():
    definitions = SCHEMA["definitions"]
    run, instrument = definitions["withheld_run"], definitions["withheld_instrument"]
    channel = run["properties"]["channels"]["items"]
    assert set(SCHEMA["oneOf"][0]["properties"]) == stcheck.WITHHELD_KEYS
    assert set(run["properties"]) == stcheck.WITHHELD_RUN_KEYS
    assert set(run["properties"]["time_period"]["properties"]) == stcheck.WITHHELD_PERIOD_KEYS
    assert set(instrument["properties"]) == stcheck.WITHHELD_INSTRUMENT_KEYS
    assert (set(instrument["properties"]["identifiers"]["items"]["properties"])
            == stcheck.WITHHELD_IDENTIFIER_KEYS)
    assert set(channel["properties"]) == stcheck.WITHHELD_CHANNEL_KEYS
    for node in (run, run["properties"]["time_period"], instrument, channel,
                 instrument["properties"]["identifiers"]["items"]):
        assert node["additionalProperties"] is False
