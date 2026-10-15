"""Survey-declared run metadata (run-metadata.csv, extract/_runsheet): the whitelist, the merge
precedence, and the built document.

The csv is the custodian's curated per-station acquisition record, distilled from field sheets.
Two properties carry all the safety: (1) WHITELIST - only the named columns ever cross into a
served document, because raw field sheets carry crew names and free-text deployment notes; (2)
ID DISCIPLINE - the sheet supplies facts only, never run ids, so the run-id store stays the sole
id authority and a sheet without a stored id still publishes no runs (the run gate is unchanged).

NON-VACUOUS: the build half writes a real csv into a staged fixture package, runs the actual
producer, validates the emitted station.json against the shipped schema artifact, and greps the
whole output tree for the forbidden field-sheet strings.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SURVEYS = HERE / "fixtures"
SCHEMA = json.loads((ROOT / "schema" / "ausmt-station.schema.json").read_text(encoding="utf-8"))
sys.path.insert(0, str(ROOT / "extract"))
sys.path.insert(0, str(HERE))
import _runfacts as rf     # noqa: E402
import _runsheet as rs     # noqa: E402
import build_portal as bp  # noqa: E402
from test_run_facts import qualify_lemimt  # noqa: E402

RUNFACTS = HERE / "fixtures" / "runfacts"

_HEADER = ("station_id,start,end,sample_rate_hz,dipole_length_ex_m,dipole_length_ey_m,"
           "azimuth_ex_deg,azimuth_ey_deg,logger_manufacturer,logger_model,logger_serial,"
           "logger_pid,sensor_manufacturer,sensor_model,sensor_bx_serial,sensor_bx_pid,"
           "sensor_by_serial,sensor_by_pid")

_ROW = ("EXAMPLE01,2022-02-12T07:59:23+00:00,2022-02-14T09:20:24+00:00,1000,52,51.5,0,90,"
        "LEMI,LEMI-423,#0040,https://doi.org/10.82388/c7ea5dpq,LEMI,LEMI-120,"
        "125,https://doi.org/10.82388/ahbao8tk,126,https://doi.org/10.82388/1nhybg3w")


def _write_sheet(pkg: Path, text: str):
    (pkg / "run-metadata.csv").write_text(text, encoding="utf-8")


# ---- the loader ---------------------------------------------------------------------------------

def test_a_package_with_no_sheet_asserts_nothing(tmp_path):
    rows, notes = rs.load(tmp_path)
    assert rows == {} and notes == []


def test_non_whitelist_columns_are_ignored_and_reported(tmp_path):
    """A raw field sheet committed by mistake must be loud AND harmless: the crew and comment
    columns never reach the row dict, and the note names them."""
    _write_sheet(tmp_path, _HEADER + ",station.acquired_by.name,station.comments\n"
                 + _ROW + ",Goran Boren,Electric channels possibly swapped\n")
    rows, notes = rs.load(tmp_path)
    assert "EXAMPLE01" in rows
    blob = json.dumps(rows)
    assert "Goran Boren" not in blob and "swapped" not in blob
    assert any("non-whitelist" in n and "station.comments" in n for n in notes), notes


def test_a_duplicate_station_id_refuses_the_whole_sheet(tmp_path):
    _write_sheet(tmp_path, _HEADER + "\n" + _ROW + "\n" + _ROW + "\n")
    rows, notes = rs.load(tmp_path)
    assert rows == {}
    assert any("repeats station_id" in n for n in notes), notes


def test_a_sheet_without_station_id_refuses_whole(tmp_path):
    _write_sheet(tmp_path, "start,end\n2022-01-01,2022-01-02\n")
    rows, notes = rs.load(tmp_path)
    assert rows == {}
    assert any("required column" in n for n in notes), notes


def test_dash_and_empty_cells_assert_nothing(tmp_path):
    _write_sheet(tmp_path, _HEADER + "\nEXAMPLE01,-,,-,-,,,,,,,,,,,,,\n")
    rows, _notes = rs.load(tmp_path)
    doc = rs.merge(None, rows["EXAMPLE01"], "EXAMPLE01", [])
    assert doc["facts"] == [] and doc["run"] == {} and doc["channels"] == {}


# ---- the merge ----------------------------------------------------------------------------------

def _row_dict(tmp_path):
    _write_sheet(tmp_path, _HEADER + "\n" + _ROW + "\n")
    rows, _notes = rs.load(tmp_path)
    return rows["EXAMPLE01"]


def test_a_sheet_only_station_qualifies_for_runs(tmp_path):
    """Vulcan-shaped: the EDI asserts nothing, the sheet asserts the acquisition. The merged
    document qualifies under the run gate and carries the whole curated record."""
    doc = rs.merge(None, _row_dict(tmp_path), "EXAMPLE01", [])
    assert "time_period" in doc["facts"] and "sensor" in doc["facts"]
    runs, _notes = bp.station_runs(doc, {"EXAMPLE01": ["EXAMPLE01-r01"]}, "EXAMPLE01", "Z")
    run = runs[0]
    assert run["id"] == "EXAMPLE01-r01"
    assert run["sample_rate_hz"] == 1000.0
    assert run["data_logger"]["identifiers"] == [{"scheme": "DOI", "identifier": "10.82388/c7ea5dpq"}]
    channels = {c["component"]: c for c in run["channels"]}
    assert channels["ex"]["dipole_length_m"] == 52.0
    assert channels["hx"]["sensor"]["identifiers"] == [{"scheme": "DOI",
                                                        "identifier": "10.82388/ahbao8tk"}]
    assert channels["hy"]["sensor"]["serial_number"] == "126"


def test_the_sheet_never_supplies_an_id(tmp_path):
    """The run gate: curated facts without a stored id publish nothing, and the gap is reported."""
    doc = rs.merge(None, _row_dict(tmp_path), "EXAMPLE01", [])
    runs, notes = bp.station_runs(doc, {}, "EXAMPLE01", "Z")
    assert runs == []
    assert any("run-id store" in n for n in notes), notes


def test_the_curated_value_outranks_the_header_and_the_conflict_is_reported(tmp_path):
    edi = rf.run_facts((RUNFACTS / "enriched-dotted.info").read_text(encoding="utf-8"))
    assert edi["run"]["sample_rate_hz"] == 1000.0
    row = _row_dict(tmp_path)
    row["sample_rate_hz"] = "500"
    notes: list = []
    doc = rs.merge(edi, row, "EXAMPLE01", notes)
    assert doc["run"]["sample_rate_hz"] == 500.0
    assert any("differs" in n and "500" in n for n in notes), notes


def test_the_header_fills_what_the_sheet_leaves_unsaid(tmp_path):
    """The EDI's contact resistance survives the merge: the sheet does not carry it (whitelist),
    and merging must never cost a station a fact it already asserted."""
    edi = rf.run_facts((RUNFACTS / "enriched-dotted.info").read_text(encoding="utf-8"))
    doc = rs.merge(edi, _row_dict(tmp_path), "EXAMPLE01", [])
    assert doc["channels"]["ex"]["contact_resistance"]["value"] == 1820.0
    assert doc["channels"]["ex"]["dipole_length_m"] == 52.0   # sheet value, not the header's 43.0


# ---- over a real build --------------------------------------------------------------------------

def _build(tmp_path, sheet_text=None):
    staged = tmp_path / "surveys"
    shutil.copytree(SURVEYS, staged)
    for package in sorted(p.parent for p in staged.glob("*/survey.yaml")):
        qualify_lemimt(package)
    if sheet_text is not None:
        (staged / "example-survey" / "run-metadata.csv").write_text(sheet_text, encoding="utf-8")
    out = tmp_path / "data"
    r = subprocess.run(
        [sys.executable, "-m", "extract.build_portal", "--surveys", str(staged),
         "--out", str(out), "--no-validate"],
        cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out


def test_a_built_station_carries_the_curated_run_and_validates(tmp_path):
    pytest.importorskip("mt_metadata")
    jsonschema = pytest.importorskip("jsonschema")
    out = _build(tmp_path, _HEADER + "\n" + _ROW + "\n")
    doc = json.loads((out / "products" / "example-survey" / "EXAMPLE01" / "station.json")
                     .read_text(encoding="utf-8"))
    run = doc["runs"][0]
    assert run["time_period"]["start"] == "2022-02-12T07:59:23+00:00"
    assert run["sample_rate_hz"] == 1000.0
    channels = {c["component"]: c for c in run["channels"]}
    assert channels["ey"]["dipole_length_m"] == 51.5
    assert channels["hy"]["sensor"]["identifiers"] == [{"scheme": "DOI",
                                                        "identifier": "10.82388/1nhybg3w"}]
    jsonschema.Draft7Validator(SCHEMA, format_checker=jsonschema.FormatChecker()).validate(doc)


def test_forbidden_sheet_columns_never_reach_the_output_tree(tmp_path):
    """The leak gate, whole-tree: a raw-sheet upload with crew names and free-text notes builds
    green, is reported, and not one forbidden string appears anywhere under out/."""
    pytest.importorskip("mt_metadata")
    crew, note = "Goran Boren", "coil 131 is in box for 134"
    out = _build(tmp_path, _HEADER + ",station.acquired_by.name,station.comments\n"
                 + _ROW + f",{crew},{note}\n")
    hits = []
    for path in sorted(out.rglob("*")):
        if path.is_file() and path.suffix in (".json", ".html", ".xml", ".txt", ".csv"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if crew in text or note in text:
                hits.append(str(path))
    assert hits == [], hits


def test_an_orphan_sheet_row_is_reported_by_name(tmp_path):
    """The sheet goes into pid-survey, whose slug is UNIQUE in the fixtures: two fixture packages
    deliberately publish under the example-survey slug, and build_report keys surveys by slug, so
    the second package's row would replace the one carrying this warning."""
    pytest.importorskip("mt_metadata")
    staged = tmp_path / "surveys"
    shutil.copytree(SURVEYS, staged)
    for package in sorted(p.parent for p in staged.glob("*/survey.yaml")):
        qualify_lemimt(package)
    (staged / "pid-survey" / "run-metadata.csv").write_text(
        _HEADER + "\n" + _ROW.replace("EXAMPLE01", "RR", 1) + "\n", encoding="utf-8")
    out = tmp_path / "data"
    r = subprocess.run(
        [sys.executable, "-m", "extract.build_portal", "--surveys", str(staged),
         "--out", str(out), "--no-validate"],
        cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    report = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    blob = json.dumps(report)
    assert "matched no station" in blob and "RR" in blob


def test_date_only_and_inverted_time_windows_go_absent_with_notes():
    """The station schema types time_period as format: date-time, and fromisoformat accepts a
    bare date - so a sheet's date-only retrieve entry must go ABSENT (not published as a
    non-time), and an end at or before its start (a sheet data-entry error) drops the end. Both
    leave a curation note naming the station and the offending value."""
    import _runsheet as rs
    notes = []
    doc = rs._sheet_doc({"start": "2014-09-20T07:12:00Z", "end": "2014-10-18"},
                        station_id="SA121", notes=notes)
    period = doc["run"]["time_period"]
    assert period == {"start": "2014-09-20T07:12:00Z"}, period
    assert any("SA121" in n and "'2014-10-18'" in n and "date-time" in n for n in notes), notes

    notes = []
    doc = rs._sheet_doc({"start": "2014-10-19T00:05:31Z", "end": "2014-10-18T06:00:00Z"},
                        station_id="SA107", notes=notes)
    period = doc["run"]["time_period"]
    assert period == {"start": "2014-10-19T00:05:31Z"}, period
    assert any("SA107" in n and "not after start" in n for n in notes), notes

    # a well-formed window is untouched and un-noted
    notes = []
    doc = rs._sheet_doc({"start": "2014-10-17T05:30:45Z", "end": "2014-12-10T02:00:00Z"},
                        station_id="OK1", notes=notes)
    assert doc["run"]["time_period"]["end"] == "2014-12-10T02:00:00Z"
    assert notes == []


# ---- the extended contract: Bz coil, magnetometer, time basis -----------------------------------
#
# sensor_* columns are induction coils, one per axis; magnetometer_* is ONE three-axis fluxgate unit
# that becomes the sensor of every h axis naming no coil. time_basis records how a row's times
# reached UTC. Every new column is optional, so a file written to the 18-column contract must
# publish exactly what it published before the extension: the golden pins below were captured from
# the 18-column engine and are compared byte for byte.

LEGACY = HERE / "fixtures" / "runsheet" / "legacy-18.csv"
LEGACY_GOLDEN = HERE / "fixtures" / "runsheet" / "legacy-18-runs.json"
LEGACY_BUILD_GOLDEN = HERE / "fixtures" / "runsheet" / "legacy-18-built-runs.json"
# The last fixture station's transfer function carries a tipper, so hz is corroborated with no
# sensor named for it.
_LEGACY_COMPS = {"L05": "ZT"}

_NEW = ("sensor_bz_serial,sensor_bz_pid,magnetometer_manufacturer,magnetometer_model,"
        "magnetometer_serial,magnetometer_pid,time_basis")
_CORRECTED = "corrected -8 h from a local clock"


def legacy_runs_blob(sheet_dir) -> str:
    """Every station of a sheet through load, merge and station_runs, serialised as the build
    serialises station.json, with the curation notes each produced."""
    rows, notes = rs.load(sheet_dir)
    out = {"load_notes": notes}
    for sid in sorted(rows):
        station_notes: list = []
        doc = rs.merge(None, rows[sid], sid, station_notes)
        runs, rnotes = bp.station_runs(doc, {sid: [f"{sid}-r01"]}, sid, _LEGACY_COMPS.get(sid, "Z"))
        out[sid] = {"runs": runs, "notes": station_notes + rnotes}
    return json.dumps(out, indent=1, ensure_ascii=False) + "\n"


def built_runs_blob(out) -> str:
    doc = json.loads((out / "products" / "example-survey" / "EXAMPLE01" / "station.json")
                     .read_text(encoding="utf-8"))
    return json.dumps(doc["runs"], indent=1, ensure_ascii=False) + "\n"


def _row(**cells) -> dict:
    """One loaded sheet row: every whitelisted column present, blank unless named."""
    return {c: cells.get(c, "") for c in rs.COLUMNS if c != "station_id"}


def _channels(row, comps="Z", notes=None):
    doc = rs.merge(None, row, "S1", notes if notes is not None else [])
    runs, _ = bp.station_runs(doc, {"S1": ["S1-r01"]}, "S1", comps)
    return runs[0], {c["component"]: c for c in runs[0].get("channels") or []}


_COIL = dict(sensor_manufacturer="LEMI", sensor_model="LEMI-120",
             sensor_bx_serial="125", sensor_bx_pid="https://doi.org/10.82388/fixture-bx",
             sensor_by_serial="126", sensor_by_pid="https://doi.org/10.82388/fixture-by")
_MAG = dict(magnetometer_manufacturer="Bartington", magnetometer_model="Mag03MS70",
            magnetometer_serial="4440", magnetometer_pid="https://doi.org/10.82388/fixture-mag")
_MAG_SENSOR = {"manufacturer": "Bartington", "model": "Mag03MS70", "serial_number": "4440",
               "identifiers": [{"scheme": "DOI", "identifier": "10.82388/fixture-mag"}]}


def test_a_legacy_18_column_sheet_publishes_byte_identical_runs(tmp_path):
    shutil.copy(LEGACY, tmp_path / rs.FILENAME)
    assert legacy_runs_blob(tmp_path) == LEGACY_GOLDEN.read_text(encoding="utf-8")


def test_a_legacy_18_column_sheet_builds_byte_identical_station_runs(tmp_path):
    pytest.importorskip("mt_metadata")
    out = _build(tmp_path, _HEADER + "\n" + _ROW + "\n")
    assert built_runs_blob(out) == LEGACY_BUILD_GOLDEN.read_text(encoding="utf-8")


def test_the_extended_columns_are_whitelisted_and_unknown_ones_still_ignored(tmp_path):
    """Forward tolerance: an unknown column is read past, never ingested, and named in a
    curation note. Every extended column is on the whitelist, so none of them is named."""
    _write_sheet(tmp_path, _HEADER + "," + _NEW + ",next_column\n" + _ROW
                 + ",127,https://doi.org/10.82388/fixture-bz,,,,,utc,anything\n")
    rows, notes = rs.load(tmp_path)
    assert rows["EXAMPLE01"]["sensor_bz_serial"] == "127"
    assert rows["EXAMPLE01"]["time_basis"] == "utc"
    assert "next_column" not in rows["EXAMPLE01"]
    unknown = [n for n in notes if "non-whitelist" in n]
    assert len(unknown) == 1 and "next_column" in unknown[0], notes
    for column in _NEW.split(","):
        assert column not in unknown[0]


def test_a_bz_coil_becomes_the_hz_sensor():
    run, ch = _channels(_row(**_COIL, sensor_bz_serial="127",
                             sensor_bz_pid="https://doi.org/10.82388/fixture-bz"))
    assert ch["hz"]["sensor"] == {"manufacturer": "LEMI", "model": "LEMI-120",
                                  "serial_number": "127",
                                  "identifiers": [{"scheme": "DOI",
                                                   "identifier": "10.82388/fixture-bz"}]}
    assert ch["hx"]["sensor"]["serial_number"] == "125"


def test_the_shared_coil_columns_alone_never_imply_a_bz_coil():
    """Manufacturer and model are shared by all three coils, and most stations deployed no Bz coil,
    so hz gains a coil only from a bz cell of its own."""
    _run, ch = _channels(_row(**_COIL))
    assert "hz" not in ch


def test_a_magnetometer_is_the_sensor_of_every_h_axis():
    _run, ch = _channels(_row(**_MAG))
    for axis in ("hx", "hy", "hz"):
        assert ch[axis]["sensor"] == _MAG_SENSOR, axis


def test_a_coil_wins_over_the_magnetometer_on_an_axis_that_names_both():
    notes: list = []
    _run, ch = _channels(_row(**_COIL, **_MAG), notes=notes)
    assert ch["hx"]["sensor"]["serial_number"] == "125"
    assert ch["hy"]["sensor"]["serial_number"] == "126"
    assert ch["hz"]["sensor"] == _MAG_SENSOR
    assert any("S1" in n and "hx" in n and "hy" in n and "magnetometer" in n for n in notes), notes

    notes = []
    _run, ch = _channels(_row(**_COIL, **_MAG, sensor_bz_serial="127"), notes=notes)
    assert ch["hz"]["sensor"]["serial_number"] == "127"
    assert all(c["sensor"] != _MAG_SENSOR for c in ch.values() if "sensor" in c)


def test_the_time_basis_is_carried_on_the_time_period():
    run, _ = _channels(_row(start="2022-02-12T02:09:58+00:00", time_basis=_CORRECTED))
    assert run["time_period"] == {"start": "2022-02-12T02:09:58+00:00", "time_basis": _CORRECTED}
    run, _ = _channels(_row(start="2022-02-12T02:09:58+00:00", end="2022-02-13T02:00:00+00:00",
                            time_basis="utc"))
    assert run["time_period"]["time_basis"] == "utc"
    run, _ = _channels(_row(start="2022-02-12T02:09:58+00:00"))
    assert "time_basis" not in run["time_period"]


def test_a_time_basis_outside_the_vocabulary_withholds_the_window():
    """The basis says whether the times are UTC at all, so a value the vocabulary does not hold
    leaves the window unpublishable; the cell is free text and never reaches the document."""
    notes: list = []
    doc = rs.merge(None, _row(start="2022-02-12T10:09:58+00:00", time_basis="local, see notes"),
                   "S1", notes)
    assert "time_period" not in doc["run"]
    assert "local, see notes" not in json.dumps(doc)
    assert any("S1" in n and "time_basis" in n for n in notes), notes


def _edi_with_window():
    edi = rf._Doc()
    edi.run("time_period", {"start": "2022-02-12T02:09:58+00:00",
                            "end": "2022-02-13T02:00:00+00:00"},
            rf.STRUCTURED_DIALECT, fact="time_period")
    return edi.doc


def test_a_window_withheld_for_its_basis_is_not_refilled_from_the_header():
    """The sheet decided the station's window cannot be published as UTC; the header's window is
    the same logger's clock, so the merge must not publish it in the sheet's place."""
    notes: list = []
    doc = rs.merge(_edi_with_window(),
                   _row(start="2022-02-12T10:09:58+00:00", time_basis="local, see notes"),
                   "S1", notes)
    assert "time_period" not in doc["run"]
    assert "time_period" not in doc["facts"]
    assert any("S1" in n and "left absent" in n for n in notes), notes


def test_a_sheet_row_without_times_still_takes_the_header_window():
    doc = rs.merge(_edi_with_window(), _row(sample_rate_hz="500"), "S1", [])
    assert doc["run"]["time_period"]["start"] == "2022-02-12T02:09:58+00:00"


def test_a_time_basis_without_a_window_asserts_nothing():
    doc = rs.merge(None, _row(time_basis=_CORRECTED), "S1", [])
    assert doc["run"] == {} and doc["facts"] == []


def test_the_schema_vocabulary_is_the_engine_vocabulary():
    prop = SCHEMA["definitions"]["time_period"]["properties"]["time_basis"]
    assert tuple(prop["enum"]) == rs.TIME_BASES


def test_an_extended_sheet_builds_a_valid_station(tmp_path):
    pytest.importorskip("mt_metadata")
    jsonschema = pytest.importorskip("jsonschema")
    row = _ROW + ",127,https://doi.org/10.82388/fixture-bz," + ",".join(_MAG.values()) + "," + _CORRECTED
    out = _build(tmp_path, _HEADER + "," + _NEW + "\n" + row + "\n")
    doc = json.loads((out / "products" / "example-survey" / "EXAMPLE01" / "station.json")
                     .read_text(encoding="utf-8"))
    run = doc["runs"][0]
    assert run["time_period"]["time_basis"] == _CORRECTED
    channels = {c["component"]: c for c in run["channels"]}
    assert channels["hz"]["sensor"]["identifiers"] == [{"scheme": "DOI",
                                                        "identifier": "10.82388/fixture-bz"}]
    validator = jsonschema.Draft7Validator(SCHEMA, format_checker=jsonschema.FormatChecker())
    validator.validate(doc)
    run["time_period"]["time_basis"] = "local clock"
    assert list(validator.iter_errors(doc)), "the schema must refuse a basis outside its vocabulary"


def test_an_embargoed_survey_serves_no_runs_from_the_extended_sheet(tmp_path):
    pytest.importorskip("mt_metadata")
    staged = tmp_path / "surveys"
    shutil.copytree(SURVEYS / "example-survey", staged / "example-survey")
    package = qualify_lemimt(staged / "example-survey")
    yaml_path = package / "survey.yaml"
    yaml_path.write_text(yaml_path.read_text(encoding="utf-8").replace(
        "access:\n  level: open", 'access:\n  level: embargoed\n  embargo_until: "2099-01-01"', 1),
        encoding="utf-8")
    row = _ROW + ",127,https://doi.org/10.82388/fixture-bz," + ",".join(_MAG.values()) + ",utc"
    (package / "run-metadata.csv").write_text(_HEADER + "," + _NEW + "\n" + row + "\n",
                                              encoding="utf-8")
    out = tmp_path / "data"
    r = subprocess.run(
        [sys.executable, "-m", "extract.build_portal", "--surveys", str(staged),
         "--out", str(out), "--no-validate"],
        cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    doc = json.loads((out / "products" / "example-survey" / "EXAMPLE01" / "station.json")
                     .read_text(encoding="utf-8"))
    assert doc.get("withheld") is True and "runs" not in doc
    for path in sorted(out.rglob("*")):
        if path.is_file() and path.suffix in (".json", ".html", ".xml", ".txt", ".csv"):
            assert "fixture-mag" not in path.read_text(encoding="utf-8", errors="ignore"), path
