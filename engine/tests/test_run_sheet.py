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
