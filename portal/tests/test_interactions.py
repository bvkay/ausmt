"""Portal INTERACTION coverage (Invariant 10) — the sidebar tree toggles, #/collection routing, and Find.

These paths shipped with ZERO automated coverage: smoke.js stubs querySelectorAll()->[] so buildTree() never
makes a checkbox and only #/station routes. That is exactly how the value-less-checkbox toggle no-op reached
a release. This boots the REAL portal in jsdom (tools/interaction_test.js) against a KNOWN fixture —
4 stations / 2 countries / 3 orgs / 3 surveys / 1 collection — and drives the UI.

The driver FAILS (and so does this test) if:
- a Country or Organisation checkbox toggle does not sync its survey boxes + filter their stations
  (the hostile-audit must-fix: a value-less checkbox has .value === "on", so the old `if(inp.value)return`
  skipped binding the toggle handler entirely);
- the #/collection/<id> hash does not open the full-width collection page over the map, or browser-Back
  (hash -> '') does not restore the map view;
- a survey-name Find query blanks the map (passes() must also match s.survey).

Skips when Node or the jsdom dev-dependency is absent (CI runs `npm ci` in portal/ first)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent                 # portal/
DRIVER = ROOT / "tools" / "interaction_test.js"
COLS = json.loads((ROOT.parent / "contract" / "columns.json").read_text())


def _row(cols, vals):
    return [vals[c] for c in cols]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_portal_interactions(tmp_path):
    base_cat = {"period_min_s": 0.01, "period_max_s": 1000.0, "n_periods": 30, "comps": "ZT",
                "type": "BBMT", "region": "NA", "file": "x.edi", "coord_flag": False,
                "edi_available": 1, "sha256": "a" * 64}
    base_sci = {"q": 4.0, "qb": "e", "rr": 1, "sw": "BIRRP", "alg": "robust", "dim": "2-D",
                "p3d": 0, "gd": 0, "ellip": 0.1, "skew": 2.0, "mre": 0.02, "decades": 5.0}
    # 2 countries (Australia: OrgX+OrgY+OrgW, New Zealand: OrgZ); OrgX owns 2 stations so the org toggle
    # drops >1. edi_available mix (Alpha+Gamma=1, Beta+Delta=0) drives the "downloadable here only" filter
    # test; distinct year_start/year_end per survey (Gamma+Delta undated) drive the year-range filter +
    # recently-added tests. C1b: Delta Survey is EMBARGOED (access!=open) with no embargo_until — its
    # station D1 drives the drawer access-panel test (no plots; verbatim embargo copy). Its curves are
    # withheld at the ENGINE (empty tf series); the fixture mirrors that so the driver sees what ships.
    stations = [
        {"id": "A1", "survey": "Alpha Survey", "lat": -30.0, "lon": 136.0, "ausmt_id": "au.alpha.A1", "edi_available": 1},
        {"id": "A2", "survey": "Alpha Survey", "lat": -31.0, "lon": 137.0, "ausmt_id": "au.alpha.A2", "edi_available": 1},
        {"id": "B1", "survey": "Beta Survey", "lat": -29.0, "lon": 135.0, "ausmt_id": "au.beta.B1", "edi_available": 0},
        {"id": "G1", "survey": "Gamma Survey", "lat": -41.0, "lon": 174.0, "ausmt_id": "nz.gamma.G1", "edi_available": 1},
        {"id": "D1", "survey": "Delta Survey", "lat": -28.0, "lon": 138.0, "ausmt_id": "au.delta.D1", "edi_available": 0},
    ]
    cat = [_row(COLS["catalogue"], {**base_cat, **s}) for s in stations]
    sci = [_row(COLS["sci"], base_sci) for _ in stations]
    # 10 arrays in TF order (periods first) for the OPEN stations; the embargoed Delta station D1 gets the
    # WITHHELD shape the engine now emits for a non-open survey — every series column an EMPTY ARRAY.
    tf = []
    for s in stations:
        if s["survey"] == "Delta Survey":
            tf.append([[] for _ in COLS["tf"]])          # C1b: withheld display curves (all series empty)
        else:
            tf.append([[0.01, 1000.0]] + [[1.0, 2.0]] * 9)
    surveys = {
        # Alpha carries the PID chain fields the drawer renders as links: survey_pid (m.pid),
        # collection_pid (m.ts_pid), and the additive instruments[] list with a per-instrument pid —
        # PLUS a hostile pid value that must render INERT (escUrl guard). The driver's section P asserts
        # each renders as a real <a href> (or, for the hostile value, a NON-executable href).
        "Alpha Survey": {"slug": "alpha", "org": "OrgX", "country": "Australia",
                         "year_start": 2010, "year_end": 2012,
                         "pid": "https://hdl.handle.net/survey/alpha-pid",
                         "ts": "ok",   # so provGraph renders the collection_pid as a link (goal 2)
                         "ts_pid": "10.25914/alpha-timeseries",
                         "instrument_model": "LEMI 423; Phoenix MTU-5C",
                         "instruments": [
                             {"manufacturer": "LEMI", "model": "423",
                              "pid": "https://instruments.auscope.org.au/system/LEMI-423-007"},
                             {"manufacturer": "Phoenix", "model": "MTU-5C",
                              "pid": "javascript:alert(1)"}],  # HOSTILE — must render inert
                         "release_notes": [{"version": "1.0.0", "date": "2012-05-01", "note": "Initial."}]},
        "Beta Survey": {"slug": "beta", "org": "OrgY", "country": "Australia",
                        "year_start": 2018, "year_end": 2019},
        "Gamma Survey": {"slug": "gamma", "org": "OrgZ", "country": "New Zealand",
                         "year_start": None, "year_end": None},
        # C1b: an embargoed survey with NO embargo_until — the drawer must render the no-date verbatim
        # embargo panel in place of the four plots. Undated so it stays out of year/recently-added counts.
        "Delta Survey": {"slug": "delta", "org": "OrgW", "country": "Australia",
                         "year_start": None, "year_end": None,
                         "access": "embargoed", "embargo_until": None},
    }
    collections = {"auslamp": {"title": "AusLAMP", "type": "programme", "status": "active",
                               "surveys": ["Alpha Survey", "Beta Survey"], "n_surveys": 2, "n_stations": 3,
                               "bbox": {"west": 134, "east": 138, "south": -32, "north": -28}}}

    data = tmp_path / "data"
    data.mkdir()
    (data / "catalogue.json").write_text(json.dumps(cat))
    (data / "sci.json").write_text(json.dumps(sci))
    (data / "tf.json").write_text(json.dumps(tf))
    (data / "surveys.json").write_text(json.dumps(surveys))
    (data / "collections.json").write_text(json.dumps(collections))

    r = subprocess.run(["node", str(DRIVER), str(data)], capture_output=True, text=True, cwd=str(ROOT))
    out = r.stdout + r.stderr
    if r.returncode == 2:
        pytest.skip("jsdom dev-dependency not installed (run `npm ci` in portal/)")
    assert r.returncode == 0, out
    assert "INTERACTION PASSED" in out, out
