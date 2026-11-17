"""runs[] on an embargoed station record, over a real build of a staged fixture package.

tests/test_withheld_runs.py pins the projection and the closed key sets at the function level. This
file pins what the producer actually writes, because the source rule lives at the build's call site
and a function-level test cannot see which inputs that site hands over:

  * an embargoed station.json carries the run sheet's window, logger and magnetic sensors under the
    stored run id, and nothing else about the acquisition;
  * nothing read out of the station's own file reaches it. The staged EDIs state a logger in >INFO
    and four measured components, and the open build of the same package publishes both, so their
    absence from the embargoed build is the source rule and not an empty fixture;
  * a metadata_only build writes the bare stub, and the curation notes of an embargoed build are
    exactly those the full assembly raises, none added and none lost by the withheld one;
  * the deploy gate passes the built tree and refuses a withheld run carrying a rate, a dipole or a
    position.

NON-VACUOUS: every build runs the real producer as a subprocess over a staged copy of
fixtures/example-survey, and every expected value below was read out of such a build.
"""
import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCHEMA = json.loads((ROOT / "schema" / "ausmt-station.schema.json").read_text(encoding="utf-8"))
VERIFY = ROOT / "scripts" / "verify.py"
sys.path.insert(0, str(ROOT / "extract"))
sys.path.insert(0, str(HERE))
import _stationcheck as stcheck                 # noqa: E402
from test_run_facts import qualify_lemimt       # noqa: E402

SLUG = "example-survey"
_ACCESS = {
    "open": "access:\n  level: open",
    "embargoed": 'access:\n  level: embargoed\n  embargo_until: "2099-01-01"',
    "metadata_only": "access:\n  level: metadata_only",
}

# The rate, the dipoles and the azimuths are values no other member of a station record states, so
# a text search for them cannot match by accident.
_HEADER = ("station_id,start,end,time_basis,sample_rate_hz,dipole_length_ex_m,dipole_length_ey_m,"
           "azimuth_ex_deg,azimuth_ey_deg,logger_manufacturer,logger_model,logger_serial,"
           "logger_pid,sensor_manufacturer,sensor_model,sensor_bx_serial,sensor_bx_pid,"
           "sensor_by_serial,sensor_by_pid,sensor_bz_serial,sensor_bz_pid")
_FULL = ("EXAMPLE01,2022-02-12T07:59:23+00:00,2022-02-14T09:20:24+00:00,utc,1024,52.7,51.3,"
         "2.5,92.75,LEMI,LEMI-423,#0040,https://doi.org/10.82388/c7ea5dpq,LEMI,LEMI-120,"
         "125,https://doi.org/10.82388/ahbao8tk,126,https://doi.org/10.82388/1nhybg3w,"
         "127,https://doi.org/10.82388/fixture-bz")
# A window and nothing else: no logger, no sensor, no rate.
_WINDOW_ONLY = "EXAMPLE02,2022-02-12T08:30:00+00:00,2022-02-14T10:00:00+00:00" + "," * 18
WITHHELD_VALUES = {"sample_rate_hz": "1024", "dipole_length_ex_m": "52.7",
                   "dipole_length_ey_m": "51.3", "azimuth_ex_deg": "2.5",
                   "azimuth_ey_deg": "92.75"}

# EXAMPLE02 has no row: its only acquisition facts are the ones its own file states.
SHEET_ONE_ROW = _HEADER + "\n" + _FULL + "\n"
SHEET_TWO_ROWS = SHEET_ONE_ROW + _WINDOW_ONLY + "\n"

# What the staged EDIs state about their own acquisition (qualify_lemimt's >INFO logger line) and
# the components their transfer functions measured.
FILE_LOGGER = {"model": "LEMI-424"}
FILE_COMPONENTS = ["ex", "ey", "hx", "hy"]


def _instrument(model, serial, doi=None):
    out = {"manufacturer": "LEMI", "model": model, "serial_number": serial}
    if doi:
        out["identifiers"] = [{"scheme": "DOI", "identifier": doi}]
    return out


OCCUPIED_EXAMPLE01 = [{
    "id": "EXAMPLE01-r01",
    "time_period": {"start": "2022-02-12T07:59:23+00:00", "end": "2022-02-14T09:20:24+00:00",
                    "time_basis": "utc"},
    "data_logger": _instrument("LEMI-423", "#0040", "10.82388/c7ea5dpq"),
    "channels": [
        {"component": "hx", "sensor": _instrument("LEMI-120", "125", "10.82388/ahbao8tk")},
        {"component": "hy", "sensor": _instrument("LEMI-120", "126", "10.82388/1nhybg3w")},
        {"component": "hz", "sensor": _instrument("LEMI-120", "127", "10.82388/fixture-bz")},
    ],
}]

OCCUPIED_EXAMPLE02 = [{
    "id": "EXAMPLE02-r01",
    "time_period": {"start": "2022-02-12T08:30:00+00:00", "end": "2022-02-14T10:00:00+00:00"},
}]


def _stage(root: Path, level: str, sheet: str, run_ids: str = None) -> Path:
    staged = root / "surveys"
    package = staged / SLUG
    shutil.copytree(HERE / "fixtures" / SLUG, package)
    qualify_lemimt(package)
    yaml_path = package / "survey.yaml"
    text = yaml_path.read_text(encoding="utf-8")
    assert _ACCESS["open"] in text
    yaml_path.write_text(text.replace(_ACCESS["open"], _ACCESS[level], 1), encoding="utf-8")
    (package / "run-metadata.csv").write_text(sheet, encoding="utf-8")
    if run_ids is not None:
        (package / "run-ids.yaml").write_text(run_ids, encoding="utf-8")
    return staged


def _build(root: Path, level: str, sheet: str, run_ids: str = None) -> Path:
    pytest.importorskip("mt_metadata")
    out = root / "data"
    r = subprocess.run(
        [sys.executable, "-m", "extract.build_portal", "--surveys",
         str(_stage(root, level, sheet, run_ids)), "--out", str(out),
         "--products", str(out / "products"), "--no-validate"],
        cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out


def _path(out: Path, station: str) -> Path:
    return out / "products" / SLUG / station / "station.json"


def _doc(out: Path, station: str) -> dict:
    return json.loads(_path(out, station).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def builds(tmp_path_factory):
    """Each staged package built once; the tests below only read the trees."""
    made = {}

    def get(name):
        if name not in made:
            level, sheet = {"embargoed": ("embargoed", SHEET_ONE_ROW),
                            "open": ("open", SHEET_ONE_ROW),
                            "embargoed-two-rows": ("embargoed", SHEET_TWO_ROWS),
                            "open-two-rows": ("open", SHEET_TWO_ROWS),
                            "metadata_only": ("metadata_only", SHEET_ONE_ROW)}[name]
            made[name] = _build(tmp_path_factory.mktemp(name), level, sheet)
        return made[name]
    return get


# ---- a: what an embargoed build publishes -------------------------------------------------------

def test_an_embargoed_build_publishes_the_run_sheets_window_and_instruments(builds):
    doc = _doc(builds("embargoed"), "EXAMPLE01")
    assert doc["withheld"] is True and doc["access"]["level"] == "embargoed"
    assert doc["runs"] == OCCUPIED_EXAMPLE01


def test_the_built_embargoed_record_holds_the_semantic_layer_and_the_schema(builds):
    jsonschema = pytest.importorskip("jsonschema")
    validator = jsonschema.Draft7Validator(SCHEMA, format_checker=jsonschema.FormatChecker())
    for station in ("EXAMPLE01", "EXAMPLE02"):
        doc = _doc(builds("embargoed"), station)
        assert stcheck.violations(doc) == [], station
        assert [e.message for e in validator.iter_errors(doc)] == [], station


def test_runs_is_the_only_member_an_embargoed_record_gains(builds):
    """The record with a run is the stub without one, plus `runs` appended last."""
    with_run, without = _doc(builds("embargoed"), "EXAMPLE01"), _doc(builds("embargoed"), "EXAMPLE02")
    assert list(with_run) == list(without) + ["runs"]
    assert list(without) == ["schema", "version", "ausmt_id", "station", "survey", "survey_id",
                             "country", "organisation", "access", "distribution", "withheld",
                             "note"]


# ---- b: the source rule -------------------------------------------------------------------------

def test_a_station_with_no_sheet_row_publishes_no_run_when_embargoed(builds):
    """EXAMPLE02's own file states a logger and four components, and the open build publishes a run
    from them. The embargoed build publishes none: that file is the withheld product."""
    (opened,) = _doc(builds("open"), "EXAMPLE02")["runs"]
    assert opened["data_logger"] == FILE_LOGGER
    assert [ch["component"] for ch in opened["channels"]] == FILE_COMPONENTS
    assert "runs" not in _doc(builds("embargoed"), "EXAMPLE02")


def test_a_member_the_sheet_leaves_unsaid_is_not_refilled_from_the_withheld_file(builds):
    """EXAMPLE02's row states a window only. The open build fills the logger and the channels from
    the station's own file; the embargoed build keeps the window and nothing more."""
    (opened,) = _doc(builds("open-two-rows"), "EXAMPLE02")["runs"]
    assert opened["time_period"] == OCCUPIED_EXAMPLE02[0]["time_period"]
    assert opened["data_logger"] == FILE_LOGGER
    assert [ch["component"] for ch in opened["channels"]] == FILE_COMPONENTS
    assert _doc(builds("embargoed-two-rows"), "EXAMPLE02")["runs"] == OCCUPIED_EXAMPLE02


def test_no_fact_read_out_of_a_withheld_file_reaches_any_built_file(builds):
    """Whole tree: the logger the staged files name appears nowhere in an embargoed build."""
    assert FILE_LOGGER["model"] in _path(builds("open"), "EXAMPLE02").read_text(encoding="utf-8")
    hits = [str(p) for p in sorted(builds("embargoed-two-rows").rglob("*"))
            if p.is_file() and FILE_LOGGER["model"] in p.read_text(encoding="utf-8", errors="ignore")]
    assert hits == []


# ---- c: the rate, the dipoles and the azimuths --------------------------------------------------

def test_the_sheets_rate_dipoles_and_azimuths_appear_nowhere_in_the_embargoed_record(builds):
    opened = _path(builds("open"), "EXAMPLE01").read_text(encoding="utf-8")
    embargoed = _path(builds("embargoed"), "EXAMPLE01").read_text(encoding="utf-8")
    for column, value in WITHHELD_VALUES.items():
        assert value in opened, f"sensitivity: the open record states {column}"
        assert value not in embargoed, column
    for key in ("sample_rate_hz", "dipole_length_m", "measurement_azimuth_deg", '"ex"', '"ey"'):
        assert key in opened, f"sensitivity: the open record carries {key}"
        assert key not in embargoed, key


# ---- d: metadata_only ---------------------------------------------------------------------------

METADATA_ONLY_EXAMPLE01 = {
    "schema": "ausmt-station", "version": "0.1", "ausmt_id": "au.example-survey.EXAMPLE01",
    "station": "EXAMPLE01", "survey": "Example MT Survey 2026", "survey_id": "example-survey",
    "country": "Australia", "organisation": "Example Organisation",
    "access": {"level": "metadata_only", "embargo_until": None, "served": False},
    "distribution": {"edi_available": False, "license": "CC-BY-4.0", "edi_path": None},
    "withheld": True,
    "note": "This survey's access state withholds its derived science products (embargoed or "
            "metadata_only). Discovery metadata remains in the catalogue; the science is released "
            "when the survey's access.level is opened.",
}


def test_a_metadata_only_build_writes_the_bare_stub(builds):
    """The same sheet row that gives the embargoed record its run gives this one nothing, byte for
    byte."""
    text = _path(builds("metadata_only"), "EXAMPLE01").read_text(encoding="utf-8")
    assert text == json.dumps(METADATA_ONLY_EXAMPLE01, indent=1, ensure_ascii=False)
    for station in ("EXAMPLE01", "EXAMPLE02"):
        assert list(_doc(builds("metadata_only"), station)) == list(METADATA_ONLY_EXAMPLE01)


# ---- e: the build report ------------------------------------------------------------------------

# Every curation note the run sheet and the run-id store can raise for a station, so that a note the
# withheld assembly added or dropped would show.
_RICH_SHEET = (
    "station_id,start,end,sample_rate_hz,logger_manufacturer,logger_model,logger_serial,"
    "sensor_manufacturer,sensor_model,sensor_bx_serial,sensor_by_serial,magnetometer_manufacturer,"
    "magnetometer_model,magnetometer_serial,station.comments\n"
    "EXAMPLE01,2022-02-12T07:59:23+00:00,2022-02-14T09:20:24+00:00,1000,LEMI,LEMI-423,#0040,LEMI,"
    "LEMI-120,125,126,Bartington,Mag03MS70,4440,coil swapped\n"
    "EXAMPLE02,2022-02-12T08:30:00+00:00,2022-02-14,,,,,,,,,,,,\n"
    "RR,2022-02-12T08:30:00+00:00,,,,,,,,,,,,,\n")
_RICH_RUN_IDS = "run_ids:\n  EXAMPLE01: [EXAMPLE01-r01]\n"
# The build report's warnings for this package. The withheld assembly reports nothing of its own,
# so these are the full assembly's notes exactly, the same whatever the survey's access level.
RICH_WARNINGS = [
    "5 run-metadata curation note(s) for this survey ["
    "curation: run-metadata.csv carries non-whitelist column(s) station.comments; they are IGNORED - "
    "if this is a raw field sheet, replace it with the distiller's output; "
    "curation: EXAMPLE01 names a coil and a magnetometer on hx, hy; the coil is published as the "
    "sensor there; "
    "curation: EXAMPLE02 run end '2022-02-14' is not a full date-time; left absent (schema types "
    "time_period as date-time); "
    "curation: EXAMPLE02 asserts acquisition facts (time_period, data_logger) but the run-id store "
    "has no row for it, so no runs[] is published; assign one with _tools/assign_run_ids.py; "
    "curation: 1 run-metadata.csv row(s) matched no station in this survey [RR]; station_id must "
    "equal the corpus station id byte-for-byte (the distiller owns the sheet-to-corpus join)]",
]


def test_the_curation_notes_of_an_embargoed_build_are_unchanged(tmp_path):
    out = _build(tmp_path, "embargoed", _RICH_SHEET, _RICH_RUN_IDS)
    report = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    assert report["surveys"][SLUG]["warnings"] == RICH_WARNINGS
    assert "runs" in _doc(out, "EXAMPLE01"), "sensitivity: the embargoed record carries a run"


# ---- f: the deploy gate -------------------------------------------------------------------------

def _verify(data_dir: Path):
    return subprocess.run([sys.executable, str(VERIFY), "--data-dir", str(data_dir)],
                          cwd=str(ROOT), capture_output=True, text=True)


def test_the_deploy_gate_passes_an_embargoed_build(builds):
    assert "runs" in _doc(builds("embargoed"), "EXAMPLE01")
    v = _verify(builds("embargoed"))
    assert v.returncode == 0, v.stdout + v.stderr
    assert "station-metadata: PASS - 2 document(s)" in v.stdout, v.stdout


PLANTED = [
    ("a rate on the withheld run", lambda run: run.update({"sample_rate_hz": 1024.0})),
    ("a dipole on a withheld channel",
     lambda run: run["channels"][0].update({"dipole_length_m": 52.7})),
    ("a position on the withheld run", lambda run: run.update({"location": {"lat": -30.1,
                                                                             "lon": 136.9}})),
]


@pytest.mark.parametrize("why,mutate", PLANTED, ids=[w for w, _ in PLANTED])
def test_the_deploy_gate_refuses_a_withheld_run_carrying_more(builds, tmp_path, why, mutate):
    tree = tmp_path / "planted"
    shutil.copytree(builds("embargoed"), tree)
    victim = _path(tree, "EXAMPLE01")
    doc = json.loads(victim.read_text(encoding="utf-8"))
    planted = copy.deepcopy(doc)
    mutate(planted["runs"][0])
    assert planted != doc
    victim.write_text(json.dumps(planted, indent=1, ensure_ascii=False), encoding="utf-8")
    v = _verify(tree)
    assert v.returncode != 0, why + "\n" + v.stdout
    assert "station-metadata: FAIL" in v.stdout and "VERIFY: FAIL" in v.stdout, v.stdout
