"""The static station page of an embargoed station: when it was occupied and by which instruments.

A station page is a view of the station's own served station.json and nothing else. An embargoed
record carries a closed runs[] (the occupation window, the logger and the sensor of each magnetic
channel), so its noindex page shows exactly that through the same runs renderer an open station
uses, and nothing the record withholds: no rate, no dipole, no azimuth, no electric channel. A
metadata_only record carries no run, so its page shows none.

The survey page and every rollup page read the station documents too, and an embargoed survey's
rollups must not move: the window and the instruments are station facts on station pages only.
That is pinned as a whole-tree comparison against a control build whose withheld packages state
no run sheet, so the only pages allowed to differ are the embargoed stations' own.
"""
import copy
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "extract"))
sys.path.insert(0, str(REPO))
import _pages as pages      # noqa: E402
import build_portal         # noqa: E402

SAMPLE_EDIS = sorted((REPO / "data" / "sample-survey" / "transfer_functions" / "edi").glob("*.edi"))
BASE = "https://ausmt.auscope.org.au"
NOINDEX = '<meta name="robots" content="noindex">'

LOGGER_DOI, BX_DOI, BY_DOI = "10.82388/c7ea5dpq", "10.82388/ahbao8tk", "10.82388/1nhybg3w"
# The sheet states the rate, both dipoles and both azimuths, so each withheld value exists to be
# printed and its absence from the page is a real check.
RUN_SHEET = (
    "station_id,start,end,sample_rate_hz,dipole_length_ex_m,dipole_length_ey_m,"
    "azimuth_ex_deg,azimuth_ey_deg,logger_manufacturer,logger_model,logger_serial,logger_pid,"
    "sensor_manufacturer,sensor_model,sensor_bx_serial,sensor_bx_pid,sensor_by_serial,sensor_by_pid\n"
    f"A1,2022-02-12T07:59:23+00:00,2022-02-14T09:20:24+00:00,1000,52,51.5,0,90,"
    f"LEMI,LEMI-423,#0040,https://doi.org/{LOGGER_DOI},LEMI,LEMI-120,"
    f"125,https://doi.org/{BX_DOI},126,https://doi.org/{BY_DOI}\n"
    "A2,2022-02-13T08:16:48+00:00,2022-02-15T07:04:12+00:00,1000,50,50,0,90,"
    "LEMI,LEMI-423,#0041,https://doi.org/10.82388/ir7azuq1,LEMI,LEMI-120,127,,128,\n")
ACCESS = {"pages-emb": "access:\n  level: embargoed\n  embargo_until: '2099-09-19'\n",
          "pages-meta": "access:\n  level: metadata_only\n",
          "pages-open": "access: open\n"}
WITHHELD = ("pages-emb", "pages-meta")


def _stage(root, *, withheld_sheets):
    """One package per access level, each over the same two stations and the same run sheet. The
    control leaves the sheet out of the withheld packages only."""
    for slug, access in ACCESS.items():
        pkg = root / slug
        edir = pkg / "transfer_functions" / "edi"
        edir.mkdir(parents=True)
        (pkg / "survey.yaml").write_text(
            f"name: {slug}\nslug: {slug}\ncountry: Australia\norganisation: Test Org\n"
            f"{access}license: CC-BY-4.0\nabstract: A test survey.\n", encoding="utf-8")
        for src in SAMPLE_EDIS:
            shutil.copyfile(src, edir / src.name)
        (pkg / "run-ids.yaml").write_text("run_ids:\n  A1: [A1_001]\n  A2: [A2_001]\n",
                                          encoding="utf-8")
        if withheld_sheets or slug not in WITHHELD:
            (pkg / "run-metadata.csv").write_text(RUN_SHEET, encoding="utf-8")
    return root


def _build(surveys, out):
    rc = build_portal.main(["--surveys", str(surveys), "--out", str(out), "--bundle-edi",
                            "--no-validate", "--products", str(out / "products"),
                            "--sitemap-base", BASE])
    assert rc == 0, f"build rc={rc}"
    return out


@pytest.fixture(scope="module")
def builds(tmp_path_factory):
    root = tmp_path_factory.mktemp("withheld-pages")
    sheet = _build(_stage(root / "sheet", withheld_sheets=True), root / "sheet-out")
    control = _build(_stage(root / "control", withheld_sheets=False), root / "control-out")
    return sheet, control


def _page(out, ausmt_id):
    return (out / "pages" / "stations" / f"{ausmt_id}.html").read_text(encoding="utf-8")


def _runs_block(page):
    m = re.search(r'<h2 id="runs">Runs</h2>.*?(?=<h2 id=)', page, re.S)
    assert m, "the page carries no Runs section"
    return m.group(0)


def _doi_anchor(doi):
    return f'<a class="pidcell" href="https://doi.org/{doi}">{doi}</a>'


def test_the_embargoed_station_page_shows_its_window_logger_and_sensors(builds):
    sheet, _control = builds
    doc = json.loads((sheet / "products" / "pages-emb" / "A1" / "station.json")
                     .read_text(encoding="utf-8"))
    assert doc["withheld"] is True and doc.get("runs"), "fixture must emit a withheld record with runs"
    block = _runs_block(_page(sheet, "au.pages-emb.A1"))
    assert '<h3 class="runid">Run A1_001</h3>' in block
    assert "<dt>Deployed</dt><dd>2022-02-12 07:59</dd>" in block
    assert "<dt>Recovered</dt><dd>2022-02-14 09:20</dd>" in block
    assert "<dt>Logger</dt><dd>LEMI LEMI-423 &#183; serial #0040 &#183; " in block
    for component, serial, doi in (("hx", "125", BX_DOI), ("hy", "126", BY_DOI)):
        assert (f"<tr><td>{component}</td><td>LEMI LEMI-120 &#183; serial {serial} &#183; "
                f"{_doi_anchor(doi)}</td></tr>") in block, component


def test_the_persistent_identifiers_link_exactly_as_on_an_open_station_page(builds):
    sheet, _control = builds
    embargoed, open_page = _page(sheet, "au.pages-emb.A1"), _page(sheet, "au.pages-open.A1")
    for doi in (LOGGER_DOI, BX_DOI, BY_DOI):
        assert _doi_anchor(doi) in open_page, f"sensitivity: the open page links {doi}"
        assert _doi_anchor(doi) in embargoed, doi


def test_the_embargoed_station_page_shows_no_rate_dipole_azimuth_or_electric_row(builds):
    sheet, _control = builds
    open_block = _runs_block(_page(sheet, "au.pages-open.A1"))
    # Sensitivity: the open station over the same sheet renders every one of these.
    for shown in ("Sample rate", "1,000 Hz", "<th>Dipole</th>", "52 m", "<th>Azimuth</th>",
                  "90&#176;", "<td>ex</td>", "<td>ey</td>"):
        assert shown in open_block, shown
    page = _page(sheet, "au.pages-emb.A1")
    for withheld in ("Sample rate", " Hz", "Dipole", "52 m", "51.5 m", "Azimuth", "&#176;",
                     "Contact resistance", "<td>ex</td>", "<td>ey</td>", "<td>hz</td>"):
        assert withheld not in page, withheld


def test_the_embargoed_station_page_stays_noindex_and_states_no_position_or_science(builds):
    sheet, control = builds
    page = _page(sheet, "au.pages-emb.A1")
    assert page.count(NOINDEX) == 1
    assert "<dt>Location</dt><dd>withheld or generalised by the data custodian</dd>" in page
    for science in ("Data type", "Period range", "Time series"):
        assert science not in page, science
    # Apart from the Runs section the page is the one the record had without a run.
    assert page.replace(_runs_block(page), "") == _page(control, "au.pages-emb.A1")


def test_a_metadata_only_station_page_shows_no_run(builds):
    sheet, control = builds
    assert "runs" not in json.loads((sheet / "products" / "pages-meta" / "A1" / "station.json")
                                    .read_text(encoding="utf-8"))
    for station in ("A1", "A2"):
        page = _page(sheet, f"au.pages-meta.{station}")
        assert 'id="runs"' not in page and NOINDEX in page
        assert page == _page(control, f"au.pages-meta.{station}")


def test_only_the_embargoed_station_pages_move_and_the_survey_page_does_not(builds):
    """Every page under pages/, survey pages, hubs, collections and cards included, is byte for
    byte the control's, except the embargoed survey's station pages."""
    sheet, control = builds
    files = sorted(p.relative_to(sheet / "pages") for p in (sheet / "pages").rglob("*")
                   if p.is_file())
    assert files == sorted(p.relative_to(control / "pages") for p in (control / "pages").rglob("*")
                           if p.is_file())
    moved = [str(p) for p in files
             if (sheet / "pages" / p).read_bytes() != (control / "pages" / p).read_bytes()]
    assert moved == ["stations/au.pages-emb.A1.html", "stations/au.pages-emb.A2.html"]
    survey = (sheet / "pages" / "surveys" / "pages-emb.html").read_text(encoding="utf-8")
    for absent in ("LEMI", LOGGER_DOI, "A1_001", "Sample rate"):
        assert absent not in survey, absent


def test_the_page_renders_only_what_the_withheld_branch_emits():
    """The emitter's withheld branch, handed a full run, feeds the page: whatever the run carried
    beyond the closed key sets never reaches the HTML."""
    full = {"id": "S01_001",
            "time_period": {"start": "2024-03-09T23:14:51+00:00",
                            "end": "2024-03-11T21:09:00+00:00"},
            "sample_rate_hz": 1000.0,
            "data_logger": {"manufacturer": "LEMI LLC", "model": "LEMI-423",
                            "serial_number": "#0040", "firmware": "fw-9.7.3",
                            "identifiers": [{"scheme": "DOI", "identifier": LOGGER_DOI}]},
            "channels": [
                {"component": "ex", "dipole_length_m": 50.0, "measurement_azimuth_deg": 0.0,
                 "contact_resistance": {"source_value": "1.8 kOhm", "value": 1800.0,
                                        "unit": "ohm"}},
                {"component": "hx", "measurement_azimuth_deg": 0.0,
                 "sensor": {"manufacturer": "LEMI LLC", "model": "LEMI-120", "serial_number": "261",
                            "identifiers": [{"scheme": "DOI", "identifier": BX_DOI}]}}]}
    doc = build_portal.station_document(
        {"ausmt_id": "au.embargoed-survey.S01", "id": "S01"}, None, "Embargoed Survey", "Org",
        {"access": "embargoed", "embargo_until": "2099-09-19"}, "CC-BY-4.0", "embargoed-survey",
        None, None, {}, False, {}, [copy.deepcopy(full)])
    page = pages.station_page(doc=doc, survey_slug="embargoed-survey", base=BASE)
    block = _runs_block(page)
    assert "<dt>Deployed</dt><dd>2024-03-09 23:14</dd>" in block
    assert _doi_anchor(LOGGER_DOI) in block and _doi_anchor(BX_DOI) in block
    for withheld in ("Sample rate", "fw-9.7.3", "Dipole", "Azimuth", "Contact resistance", "1.8 kOhm",
                     "<td>ex</td>"):
        assert withheld not in page, withheld
    assert NOINDEX in page
