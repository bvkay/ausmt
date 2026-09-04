"""The station semantic layer: what JSON Schema cannot state, enforced in the build and again by verify.

SCOPE:377-380 asks for emitter-side validation beyond the schema, and the workflow contract names the set:
referential integrity of a resource's run references, unique run and resource ids, `time_period.start
<= end`, channel shape per component family, withheld-branch rejection, DOI syntax, and the 1.x pin
that keeps `distribution.edi_path` and the served EDI resource row stating one path (SCOPE:71-73).

TWO enforcement points, both pinned here, because either one alone is a hole:

  * the build refuses to publish a violating document (`_validate_station_metadata`, the sibling of
    `_validate_survey_metadata`) - exit 2, before any consumer ever sees it;
  * `scripts/verify.py` re-checks the BUILT tree, at BOTH of its wiring sites. `--data-dir` is the
    post-build gate deploy/Makefile reads before swapping `current`; the self-building path is the
    one a developer runs. Wiring only the first leaves a self-building run passing a corpus the
    deployment gate would reject, silently, so the self-building arm is proven armed here.

A withheld record's rules restate the schema's closed-world branch on purpose: jsonschema is an
optional dependency and both self-checks degrade to a note without it, so leak protection that rested
on the schema alone would evaporate on a box that has no validator installed.
"""
import copy
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                                  # engine/
SURVEYS = HERE / "fixtures"                         # vendored, self-contained (as in test_mtcat.py)
VERIFY = ROOT / "scripts" / "verify.py"
sys.path.insert(0, str(ROOT / "extract"))

import _stationcheck as stcheck  # noqa: E402
import build_portal as bp  # noqa: E402

# A full record carrying every member the semantic layer has an opinion about, so each mutation below
# differs from a PASSING document by exactly the field under test (the suite's Txxb pattern).
CLEAN = {
    "schema": "ausmt-station", "version": "0.1", "ausmt_id": "au.example-basin-2024.EB077",
    "station": "EB077", "survey": "Example Basin MT", "survey_id": "example-basin-2024",
    "distribution": {"edi_available": True, "license": "CC-BY-4.0",
                     "edi_path": "edi/example-basin-2024/EB077.edi"},
    # The dimensionality fold and two of the eight frozen legitimate nulls, so the null scan's
    # SCOPE is provable in both directions: the fold members are covered, the frozen keys are not.
    "diagnostics": {"median_relative_error": 0.03, "remote_reference": True, "tipper_available": True,
                    "completeness_smoothness_diagnostic": {
                        "value": 0.91, "basis": "e",
                        "note": "not a quality or geological-value judgement"},
                    "classification": "2-D", "skew_beta_median_deg": 0.7, "pct_periods_3d": 0,
                    "method": "phase-tensor (Caldwell 2004)",
                    "note": "screening diagnostic, not an interpretation product"},
    "processing": {"software": None, "algorithm": None, "remote_reference": True,
                   "remote_site": None, "file_written_by": {"name": None, "version": None},
                   "note": None},
    "coordinate_qc": None,
    "runs": [
        {"id": "EB077-r01",
         "time_period": {"start": "2024-05-01T00:00:00Z", "end": "2024-05-03T00:00:00Z"},
         "sample_rate_hz": 10,
         "data_logger": {"manufacturer": "LEMI", "model": "LEMI-423", "serial_number": "1234",
                         "identifiers": [{"scheme": "DOI", "identifier": "10.82388/u3jf7ztm"}]},
         "channels": [
             {"component": "ex", "dipole_length_m": 43.0,
              "contact_resistance": {"source_value": "1.82 kilo-ohms", "value": 1820.0, "unit": "ohm"}},
             {"component": "hx", "measurement_azimuth_deg": 0.0,
              "sensor": {"manufacturer": "LEMI", "model": "LEMI-120", "serial_number": "112"}}]},
    ],
    "resources": [
        {"id": "edi", "kind": "transfer_function", "format": "edi", "provenance_role": "source",
         "representation_role": "original", "path": "edi/example-basin-2024/EB077.edi",
         "represents_runs": ["EB077-r01"],
         "related_collection_identifiers": [{"scheme": "DOI", "identifier": "10.25914/bzd5-n780",
                                             "identifies": "raw_packed"}]},
        {"id": "emtfxml", "kind": "transfer_function", "format": "emtfxml", "provenance_role": "derived",
         "representation_role": "alternate", "path": "xml/example-basin-2024/EB077.xml"},
        {"id": "ts-raw_packed", "kind": "time_series", "format": "zip", "provenance_role": "source",
         "representation_role": "original",
         "access_url": stcheck.TS_ACCESS_PREFIX + "my80/AuScope/Example/EB077%20%5BREMOTE%5D.zip",
         "repository": "NCI", "processing_level": "raw", "packaging": "packed_archive",
         "bytes": 9868836788, "note": "verified against NCI THREDDS on 2026-08-24"},
    ],
}

WITHHELD = {
    "schema": "ausmt-station", "version": "0.1", "ausmt_id": "au.vulcan-2024-25.Vul24-13",
    "station": "Vul24-13", "survey": "Vulcan 2024-25", "survey_id": "vulcan-2024-25",
    "country": "Australia", "organisation": "University of Adelaide",
    "access": {"level": "embargoed", "embargo_until": "2027-02-01", "served": False},
    "distribution": {"edi_available": False, "license": "CC-BY-4.0", "edi_path": None},
    "withheld": True, "note": "This survey's access state withholds its derived science products.",
}


def _drop_end(doc):
    doc["runs"][0]["time_period"].pop("end")


def _end_before_start(doc):
    doc["runs"][0]["time_period"]["end"] = "2024-04-01T00:00:00Z"


def _duplicate_run_id(doc):
    doc["runs"].append(copy.deepcopy(doc["runs"][0]))


def _duplicate_resource_id(doc):
    doc["resources"][1]["id"] = "edi"


def _dangling_run_reference(doc):
    doc["resources"][0]["represents_runs"] = ["EB077-r09"]


def _sensor_on_an_electric_channel(doc):
    doc["runs"][0]["channels"][0]["sensor"] = {"model": "LEMI-120"}


def _electrode_circuit_on_a_magnetic_channel(doc):
    doc["runs"][0]["channels"][1]["dipole_length_m"] = 43.0


def _resolver_prefixed_doi(doc):
    doc["resources"][0]["related_collection_identifiers"][0]["identifier"] = \
        "https://doi.org/10.25914/bzd5-n780"


def _edi_path_disagrees_with_the_resource(doc):
    doc["distribution"]["edi_path"] = "edi/example-basin-2024/OTHER.edi"


def _edi_resource_without_the_legacy_path(doc):
    doc["distribution"]["edi_path"] = None


def _null_inside_a_run(doc):
    doc["runs"][0]["data_logger"]["serial_number"] = None


def _empty_channel_list(doc):
    doc["runs"][0]["channels"] = []


def _null_fold_member(doc):
    """An `indeterminate` classification has no skew statistic, and the sidecar states that as
    null. The fold OMITS the member; copying the null across is what this rejects."""
    doc["diagnostics"]["skew_beta_median_deg"] = None


def _archive_row(rid, fmt="zip"):
    return {"id": rid, "kind": "archive", "format": fmt,
            "path": f"bundles/example-basin-2024-{rid}.zip"}


def _archive_row_the_record_put_no_bytes_into(doc):
    """The shape: the survey builds a survey MTH5, this station's bytes are not in it, and the
    record has no mth5 rendition to prove otherwise."""
    doc["resources"].append(_archive_row("survey-mth5", fmt="mth5"))


def _archive_row_with_no_membership_rule(doc):
    doc["resources"].append(_archive_row("tarball"))


def _ts_row(doc):
    return next(r for r in doc["resources"] if r["kind"] == "time_series")


def _time_series_without_a_route(doc):
    """A row whose whole job is to name where the bytes are, not naming it."""
    _ts_row(doc).pop("access_url")


def _time_series_without_a_processing_level(doc):
    """Which product of this station the file IS. Nothing downstream can guess it, and a chooser
    button, a route and a drawer row all key off it."""
    _ts_row(doc).pop("processing_level")


def _time_series_route_with_a_literal_space(doc):
    """NVP_2019's `C5 [REMOTE].zip`: only the encoded form answers 200, so an unencoded route is a
    published dead download."""
    _ts_row(doc)["access_url"] = stcheck.TS_ACCESS_PREFIX + "my80/AuScope/Example/C5 [REMOTE].zip"


def _time_series_route_walking_up(doc):
    """The encoded-route rule admits `.` and `/` because real archive filenames carry both, so a
    `..` segment passes it: the host stays fixed, but a browser normalises the path before sending
    and the published link resolves to an arbitrary file on thredds.nci.org.au. That is a wrong
    claim under an AusMT byline, and it is also the one string the front door's route table refuses,
    so without this rule station.json can publish a route the edge can never serve."""
    _ts_row(doc)["access_url"] = stcheck.TS_ACCESS_PREFIX + "my80/../../../../etc/passwd"


def _time_series_route_walking_up_percent_encoded(doc):
    """The same walk written `%2E%2E`, which a literal-only test would let through: the check reads
    the DECODED segments, because the server decodes before it resolves."""
    _ts_row(doc)["access_url"] = stcheck.TS_ACCESS_PREFIX + "my80/%2E%2E/%2E%2E/etc/passwd"


def _time_series_route_on_another_host(doc):
    _ts_row(doc)["access_url"] = "https://example.invalid/thredds/fileServer/my80/x.zip"


def _time_series_route_over_http(doc):
    _ts_row(doc)["access_url"] = stcheck.TS_ACCESS_PREFIX.replace("https://", "http://") + "my80/x.zip"


def _time_series_route_through_opendap(doc):
    """IMPLEMENTATION:23: this archive answers 500 on dodsC for these files. The prefix rule makes
    the substitution structurally impossible; this is the pin that proves it."""
    _ts_row(doc)["access_url"] = "https://thredds.nci.org.au/thredds/dodsC/my80/x.h5"


def _opendap_service_url(doc):
    _ts_row(doc)["service_urls"] = [{"kind": "opendap", "url": "https://thredds.nci.org.au/thredds/dodsC/x"}]


def _time_series_at_level2(doc):
    """Fail-closed. The archive's level_2 tree holds TRANSFER FUNCTIONS, so a level2 row under
    this kind asserts a recorded time series for a station that has none. The emitter routes no such
    row; this makes the exclusion a rule rather than an emitter habit."""
    _ts_row(doc)["processing_level"] = "level2"


def _time_series_naming_a_run_this_record_does_not_publish(doc):
    _ts_row(doc)["derived_from_runs"] = ["EB077-r09"]


REJECTED = [
    ("run time_period ends before it starts", _end_before_start),
    ("duplicate run id", _duplicate_run_id),
    ("duplicate resource id", _duplicate_resource_id),
    ("a resource references a run the record does not publish", _dangling_run_reference),
    ("an electric channel carries a sensor", _sensor_on_an_electric_channel),
    ("a magnetic channel carries the electrode circuit", _electrode_circuit_on_a_magnetic_channel),
    ("a DOI carries its resolver prefix", _resolver_prefixed_doi),
    ("distribution.edi_path disagrees with the served EDI resource", _edi_path_disagrees_with_the_resource),
    ("a served EDI resource with no legacy edi_path", _edi_resource_without_the_legacy_path),
    ("a null inside runs[]", _null_inside_a_run),
    ("an empty container inside runs[]", _empty_channel_list),
    ("a null fold member in diagnostics", _null_fold_member),
    ("an archive row this record put no bytes into", _archive_row_the_record_put_no_bytes_into),
    ("an archive row with no membership rule", _archive_row_with_no_membership_rule),
    ("a time_series row with no route", _time_series_without_a_route),
    ("a time_series row with no processing level", _time_series_without_a_processing_level),
    ("a time_series route carrying a literal space", _time_series_route_with_a_literal_space),
    ("a time_series route walking up out of the fileServer root", _time_series_route_walking_up),
    ("a time_series route walking up in percent-encoded form",
     _time_series_route_walking_up_percent_encoded),
    ("a time_series route on another host", _time_series_route_on_another_host),
    ("a time_series route that is not https", _time_series_route_over_http),
    ("a time_series route through the OPeNDAP service", _time_series_route_through_opendap),
    ("an OPeNDAP service_urls entry", _opendap_service_url),
    ("a time_series row at level 2", _time_series_at_level2),
    ("a time_series row naming a run the record does not publish",
     _time_series_naming_a_run_this_record_does_not_publish),
]

WITHHELD_REJECTED = [
    ("injected runs[]", lambda d: d.update({"runs": [{"id": "001"}]})),
    ("injected coordinates", lambda d: d.update({"location": {"lat": -31.0, "lon": 140.0}})),
    ("bare latitude/longitude keys", lambda d: d.update({"latitude": -31.0, "longitude": 140.0})),
    ("coordinates nested in access", lambda d: d["access"].update({"coords": [-31.0, 140.0]})),
    ("runs under a renamed key", lambda d: d.update({"acquisitions": [{"id": "001"}]})),
    ("a live edi_path", lambda d: d["distribution"].update({"edi_path": "edi/x/y.edi"})),
]


def _violations(doc):
    """The build's own self-check over one document, which is the semantic layer's entry point."""
    return bp._validate_station_metadata({"products/x/y/station.json": doc})


# ---------------------------------------------------------------- the layer itself

def test_a_clean_full_record_and_a_clean_withheld_stub_have_no_violations():
    assert _violations(copy.deepcopy(CLEAN)) == []
    assert _violations(copy.deepcopy(WITHHELD)) == []
    # absence is the open-world statement, so a run with no `end` is clean, not a missing value
    doc = copy.deepcopy(CLEAN)
    _drop_end(doc)
    assert _violations(doc) == []
    # non-vacuity for the two archive rejections below: the archive row a record DID put bytes into
    # (it publishes the `edi` rendition the zip was built from) is clean.
    doc = copy.deepcopy(CLEAN)
    doc["resources"].append(_archive_row("edi-zip"))
    assert _violations(doc) == []


def test_the_null_scan_reaches_the_fold_and_stops_at_the_frozen_keys():
    """Section 2 scopes the zero-null rule to what this module ADDS, and the fold is one of those
    additions. The frozen keys beside it carry eight legitimate nulls, so a scan widened to the whole
    document would reject every record the corpus publishes. Both directions in one test, because
    each alone passes for the wrong reason."""
    doc = copy.deepcopy(CLEAN)
    assert doc["coordinate_qc"] is None and doc["processing"]["remote_site"] is None
    assert stcheck.violations(doc) == [], "a frozen legitimate null is not this rule's business"
    _null_fold_member(doc)
    assert [v for v in stcheck.violations(doc) if "skew_beta_median_deg" in v], (
        "the fold member is inside the scan; a null there is a copied sidecar value")


def test_the_marker_routes_on_its_presence_not_on_its_truth():
    """`withheld: false` on a full record is schema-forbidden (a false property schema), and the
    module exists because jsonschema is optional and the protection must not rest on the schema
    alone. Routing on the value let a record carrying the key take the FULL branch, so the stdlib
    layer stayed silent on exactly the document the schema was there to catch. Checked against the
    layer directly: the build's self-check runs the schema too, which would mask it."""
    doc = copy.deepcopy(CLEAN)
    doc["withheld"] = False
    assert stcheck.violations(doc), "a full record carrying the marker must be rejected"
    assert stcheck.violations(copy.deepcopy(CLEAN)) == [], "non-vacuity: the clean record is clean"


@pytest.mark.parametrize("why,mutate", REJECTED, ids=[w for w, _ in REJECTED])
def test_the_full_branch_semantic_rejections(why, mutate):
    doc = copy.deepcopy(CLEAN)
    mutate(doc)
    assert _violations(doc), why


@pytest.mark.parametrize("why,mutate", WITHHELD_REJECTED, ids=[w for w, _ in WITHHELD_REJECTED])
def test_the_withheld_branch_rejections_hold_without_a_schema_validator(why, mutate):
    """The closed world is the leak protection, so it must not rest on an optional dependency."""
    doc = copy.deepcopy(WITHHELD)
    mutate(doc)
    assert _violations(doc), why


def test_the_violation_names_the_document_it_came_from():
    doc = copy.deepcopy(CLEAN)
    _duplicate_run_id(doc)
    assert all(v.startswith("products/x/y/station.json: ") for v in _violations(doc))


# ---------------------------------------------------------------- the build site

def _build(tmp_path, surveys=SURVEYS, products=True):
    out = tmp_path / "data"
    argv = ["--surveys", str(surveys), "--out", str(out), "--bundle-edi", "--no-validate"]
    if products:
        argv += ["--products", str(out / "products")]
    return out, argv


def test_the_build_refuses_to_publish_a_violating_document(tmp_path, monkeypatch):
    """The gate is ARMED in the build, not merely importable: a document the semantic layer rejects
    exits 2 instead of shipping. The emitter is correct, so the violation is injected at the render
    seam - which is exactly the class of regression this gate exists to catch."""
    pytest.importorskip("mt_metadata")
    real = bp.station_document

    def _duplicating(*a, **kw):
        doc = real(*a, **kw)
        if doc.get("resources"):
            doc["resources"].append(dict(doc["resources"][0]))
        return doc

    monkeypatch.setattr(bp, "station_document", _duplicating)
    out, argv = _build(tmp_path)
    assert bp.main(argv) == 2, "a duplicated resource id must fail the build"


def test_the_build_refuses_to_publish_an_unresolvable_hand_off_route(tmp_path, monkeypatch):
    """THE FIRST ENFORCEMENT SITE for the hand-off rules. Nothing local corroborates a route to
    another host, so the gate is the only thing between a mis-assembled URL and a published dead
    download. Injected at the render seam, as above, because the emitter is correct."""
    pytest.importorskip("mt_metadata")
    real = bp.station_document

    def _unencoded(*a, **kw):
        doc = real(*a, **kw)
        if doc.get("resources"):
            doc["resources"].append({**copy.deepcopy(CLEAN["resources"][-1]),
                                     "access_url": stcheck.TS_ACCESS_PREFIX + "my80/C5 [REMOTE].zip"})
        return doc

    monkeypatch.setattr(bp, "station_document", _unencoded)
    out, argv = _build(tmp_path)
    assert bp.main(argv) == 2, "an unencoded hand-off route must fail the build"


def test_the_clean_build_publishes_and_the_gate_stays_quiet(tmp_path, capsys):
    pytest.importorskip("mt_metadata")
    out, argv = _build(tmp_path)
    assert bp.main(argv) == 0
    err = capsys.readouterr().err
    assert "station self-check failed" not in err, err
    assert list((out / "products").rglob("station.json")), "the build published nothing to check"


# ---------------------------------------------------------------- the verify.py sites

def _distinct_slug_corpus(root: Path) -> Path:
    """The two vendored packages with DISTINCT slugs. fixtures/filled-survey declares example-survey's
    slug, which collides in the download manifest and FAILs the real validator, so a verify run over
    the whole fixtures directory FAILs for reasons that have nothing to do with the station gate."""
    surveys = root / "surveys"
    surveys.mkdir()
    for pkg in ("example-survey", "pid-survey"):
        shutil.copytree(SURVEYS / pkg, surveys / pkg)
    return surveys


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    pytest.importorskip("mt_metadata")
    root = tmp_path_factory.mktemp("station-semantics")
    out = root / "data"
    r = subprocess.run([sys.executable, "-m", "extract.build_portal", "--surveys",
                        str(_distinct_slug_corpus(root)), "--out", str(out),
                        "--products", str(out / "products"), "--bundle-edi", "--no-validate"],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out


def _verify_data_dir(data_dir: Path):
    return subprocess.run([sys.executable, str(VERIFY), "--data-dir", str(data_dir)],
                          cwd=str(ROOT), capture_output=True, text=True)


def test_verify_data_dir_passes_a_clean_build_and_says_so(built):
    v = _verify_data_dir(built)
    assert v.returncode == 0, v.stdout + v.stderr
    assert re.search(r"station-metadata: PASS", v.stdout), v.stdout


def test_verify_data_dir_fails_a_tampered_station_document(built, tmp_path):
    """The --data-dir gate is what deploy/Makefile reads before swapping `current`, so a corpus
    carrying a duplicated run id must leave `current` untouched."""
    tree = tmp_path / "tampered"
    shutil.copytree(built, tree)
    victim = sorted((tree / "products").rglob("station.json"))[0]
    doc = json.loads(victim.read_text(encoding="utf-8"))
    doc.setdefault("runs", [{"id": "x-r01"}])
    doc["runs"].append(dict(doc["runs"][0]))
    victim.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    v = _verify_data_dir(tree)
    assert v.returncode != 0, v.stdout
    assert "station-metadata: FAIL" in v.stdout and "VERIFY: FAIL" in v.stdout, v.stdout


TS_PLANTED = [
    ("a route carrying a literal space", _time_series_route_with_a_literal_space),
    ("a route walking up out of the fileServer root", _time_series_route_walking_up),
    ("a route on another host", _time_series_route_on_another_host),
    ("a level 2 time_series row", _time_series_at_level2),
]


@pytest.mark.parametrize("why,mutate", TS_PLANTED, ids=[w for w, _ in TS_PLANTED])
def test_verify_data_dir_fails_a_planted_time_series_row(built, tmp_path, why, mutate):
    """THE SECOND ENFORCEMENT SITE, over BUILT output. The build's own self-check and the
    pre-deployment gate run ONE implementation, so a route the emitter could never produce is still
    refused if it reaches a tree by any other path: a hand edit, a partial rebuild, a restored
    backup. Planted onto a served record rather than built, because the emitter is correct."""
    tree = tmp_path / f"planted-{abs(hash(why))}"
    shutil.copytree(built, tree)
    victim = next(p for p in sorted((tree / "products").rglob("station.json"))
                  if json.loads(p.read_text(encoding="utf-8")).get("resources"))
    doc = json.loads(victim.read_text(encoding="utf-8"))
    doc["resources"].append(copy.deepcopy(CLEAN["resources"][-1]))
    clean = json.dumps(doc, indent=1)
    victim.write_text(clean, encoding="utf-8")
    ok = _verify_data_dir(tree)
    assert ok.returncode == 0, "sensitivity: a well-formed planted row passes\n" + ok.stdout
    mutate(doc)
    victim.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    v = _verify_data_dir(tree)
    assert v.returncode != 0, why + "\n" + v.stdout
    assert "station-metadata: FAIL" in v.stdout and "VERIFY: FAIL" in v.stdout, v.stdout


def test_verify_data_dir_fails_a_withheld_document_carrying_a_coordinate(built, tmp_path):
    """The leak case, over a BUILT document: a withheld stub that gains a position is rejected by the
    gate itself, with no schema validator required for the verdict."""
    tree = tmp_path / "leaky"
    shutil.copytree(built, tree)
    victim = sorted((tree / "products").rglob("station.json"))[0]
    victim.write_text(json.dumps({**WITHHELD, "location": {"lat": -31.0, "lon": 140.0}}, indent=1),
                      encoding="utf-8")
    v = _verify_data_dir(tree)
    assert v.returncode != 0, v.stdout
    assert "station-metadata: FAIL" in v.stdout, v.stdout


def test_verify_self_building_runs_the_station_gate(tmp_path):
    """THE SECOND WIRING SITE. `_check_survey_metadata` is called twice, and so is this one: a
    verify.py run that builds its own corpus must run the station gate too, or a developer's green
    run means less than the deployment gate's.

    The self-building path passes no --products, so this is also where earns its keep: without the
    unconditional served-root write there would be no station.json for the gate to read.

    AUSMT_VALIDATOR_PATH is pinned through the four-arm seam so the run is hermetic in
    every workflow: sibling checkout on the dev box, the vendored copy on a monorepo CI checkout, and
    the engine image's designed topology (no gateway tree shipped) SKIPs with its allow-listed
    reason rather than tripping the never-fall-through error. The gate under proof is the STATION
    gate; the surveys validator's currency is the resync discipline's job, not this test's. And
    the PASS line must count documents: a gate passing on a zero-station build proves only that it
    printed."""
    pytest.importorskip("mt_metadata")
    from test_validator_gate import _resolve_validator_dir  # noqa: PLC0415 - the validator seam
    env = dict(os.environ, AUSMT_VALIDATOR_PATH=str(_resolve_validator_dir()))
    v = subprocess.run([sys.executable, str(VERIFY), "--skip-tests", "--surveys",
                        str(_distinct_slug_corpus(tmp_path))],
                       cwd=str(ROOT), capture_output=True, text=True, env=env)
    m = re.search(r"station-metadata: PASS - (\d+) document", v.stdout)
    assert m, v.stdout + v.stderr
    assert int(m.group(1)) > 0, "PASS on zero documents proves nothing:\n" + v.stdout
    assert v.returncode == 0, v.stdout + v.stderr
