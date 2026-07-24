"""Populated-portal VALUE binding (Invariant 10).

The committed test_empty_portal_smoke only exercises the EMPTY branch; the contract-converted dereferences
(r[C.*], sc[SC.*], t[T.*]) live exclusively in the POPULATED path and shipped untested. This boots the
real portal (tools/smoke.js) against a tiny dataset whose values are KNOWN and distinctive, then asserts
(a) the fields buildState() derives THROUGH the contract maps (STATION0: r[C.*] + sc[SC.q/dim]) and
(b) the columns exports.js builds at its OWN sc[SC.*] call site (EXPORT0: q/qb/rr/dim/sw) equal the
source. So a wrong call-site index (r[C.lon] where lat was meant, or a swapped sc[SC.sw]->sc[SC.alg])
makes a value wrong and FAILS here — a crash is not required. NOT exhaustive: drawer.js has further
sc[SC.*] derefs (skew/mre/ellip/p3d/gd) that remain unbound. Rows are laid out
in contract/columns.json order, so a correct generated C/SC map + a correct call site are both required
to pass. Skips without Node (CI installs it)."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent                 # portal/
SMOKE = ROOT / "tools" / "smoke.js"
COLS = json.loads((ROOT.parent / "contract" / "columns.json").read_text())


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_populated_portal_value_binding(tmp_path):
    cat_vals = {"id": "ST1", "survey": "Demo Survey", "lat": -30.5, "lon": 135.25,
                "period_min_s": 0.01, "period_max_s": 1000.0, "n_periods": 42, "comps": "ZT",
                "type": "BBMT", "region": "SA", "file": "ST1.edi", "coord_flag": False,
                "ausmt_id": "au.demo.ST1", "edi_available": 1, "sha256": "a" * 64, "site_name": None}
    sci_vals = {"q": 4.2, "qb": "e", "rr": 1, "sw": "BIRRP", "alg": "robust", "dim": "2-D",
                "p3d": 10, "gd": 0, "ellip": 0.15, "skew": 3.1, "mre": 0.02, "decades": 5.0}
    cat_row = [cat_vals[c] for c in COLS["catalogue"]]
    sci_row = [sci_vals[c] for c in COLS["sci"]]
    # tf entry: 18 arrays in TF_COLUMNS order (C20). Built by NAME and projected through COLS["tf"] so
    # it self-follows the contract; the smoke test asserts on catalogue/sci/build values, not tf columns.
    tf_vals = {"periods": [0.01, 1000.0], "rho_xy": [1.0, 2.0], "rho_yx": [3.0, 4.0],
               "phs_xy": [10.0, 20.0], "phs_yx_adj": [30.0, 40.0], "tip_mag": [0.1, 0.2],
               "pt_min": [5.0, 6.0], "pt_max": [7.0, 8.0], "pt_az": [9.0, 10.0], "pt_beta": [1.0, 2.0],
               "rho_xy_err": [0.1, 0.2], "rho_yx_err": [0.3, 0.4], "phs_xy_err": [1.0, 1.1],
               "phs_yx_err": [1.2, 1.3], "tzx_re": [0.2, 0.25], "tzx_im": [0.01, 0.02],
               "tzy_re": [0.3, 0.35], "tzy_im": [0.02, 0.03]}
    tf_row = [tf_vals[c] for c in COLS["tf"]]

    data = tmp_path / "data"
    data.mkdir()
    (data / "catalogue.json").write_text(json.dumps([cat_row]))
    (data / "sci.json").write_text(json.dumps([sci_row]))
    (data / "tf.json").write_text(json.dumps([tf_row]))
    (data / "surveys.json").write_text(json.dumps(
        {"Demo Survey": {"slug": "demo", "org": "X", "country": "Australia", "lic": "CC-BY-4.0"}}))
    # C12: build.json — a KNOWN, distinctive build_id/generated so the footer's VALUE binding
    # (BUILDID -> buildIdText()) can be asserted against the source, not just "didn't crash".
    (data / "build.json").write_text(json.dumps(
        {"build_id": "eng1234-src5678-2026-07-05T01:02:03+00:00",
         "engine_commit": "eng1234", "source_commit": "src5678",
         "generated": "2026-07-05T01:02:03+00:00"}))

    # encoding pinned: node emits UTF-8; text=True alone decodes with the Windows locale (cp1252),
    # which mangles the footer's U+00B7 separator into 'Â·' and fails the BUILDID_TEXT value-bind.
    r = subprocess.run(["node", str(SMOKE), str(data)], capture_output=True, text=True,
                       encoding="utf-8", cwd=str(ROOT))
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "POPULATED portal" in out, "expected the populated boot path, not the empty one:\n" + out
    m = re.search(r"^STATION0 (\{.*\})\s*$", out, re.M)
    assert m, "smoke.js did not emit STATION0 values:\n" + out
    st = json.loads(m.group(1))

    # each field ties a portal state value to the KNOWN source at its NAMED contract column
    assert st["id"] == "ST1", st                       # r[C.id]
    assert st["lat"] == -30.5, st                      # r[C.lat]  (a lat/lon swap would yield 135.25)
    assert st["lon"] == 135.25, st                     # r[C.lon]
    assert st["type"] == "BBMT", st                    # r[C.type]
    assert st["ausmt_id"] == "au.demo.ST1", st         # r[C.ausmt_id]
    assert st["q"] == 4.2, st                          # sc[SC.q]
    assert st["dim"] == "2-D", st                      # sc[SC.dim]

    # (b) exports.js CSV row for ST0 — value-binds the EXPORT call site. UX8 (W3b, owner directive) DROPPED
    # six columns from the station CSV (quality, quality_basis, remote_ref, dimensionality, software, file),
    # leaving a lean identity/geometry/rights row of 19 columns. Column order per the exports.js header:
    #   0 ausmt_id 1 station 2 country 3 organisation 4 survey 5 lat 6 lon 7 type 8 components 9 n_periods
    #   10 period_min_s 11 period_max_s 12 source_doi 13 timeseries_collection_doi 14 survey_version
    #   15 collection 16 license 17 license_url 18 attribution
    me = re.search(r"^EXPORT0 (\[.*\])\s*$", out, re.M)
    assert me, "smoke.js did not emit EXPORT0 (CSV row):\n" + out
    ex = json.loads(me.group(1))
    assert len(ex) == 19, ("expected 19 CSV columns after the W3b drop, got %d: %r" % (len(ex), ex))
    assert ex[12] == "", ex                             # source_doi (Demo Survey has no DOI)
    assert ex[13] == "10.25914/mtjg-jp22", ex           # timeseries_collection_doi <- TS_COLLECTION.doi
    # C6: the licence column travels with the exported row (sourced from SMETA[survey].lic). A
    # wrong/missing SMETA.lic deref (or dropping the column) makes this FAIL, not just crash.
    assert ex[16] == "CC-BY-4.0", ex                    # license        <- SMETA["Demo Survey"].lic
    # C46: the deed URL (resolved via the canonical LICENSES.urls table, not a startsWith guess) and the
    # rendered attribution line ride at the END so rights travel with a shared CSV. Demo Survey declares
    # no attribution.statement and no dates, so the attribution falls back to the org with no year.
    assert ex[17] == "https://creativecommons.org/licenses/by/4.0/", ex  # license_url <- canonical table
    assert ex[18] == "X", ex                            # attribution <- org (no statement/date)
    # W3b DROP is real (not just reordered): the six removed values are absent from the row. sc[SC.q]=4.2,
    # sc[SC.sw]="BIRRP", sc[SC.dim]="2-D" and the file "ST1.edi" would all be present pre-drop.
    for gone in (4.2, "BIRRP", "2-D", "ST1.edi", "error"):
        assert gone not in ex, ("dropped CSV field %r still present: %r" % (gone, ex))

    # (c) C12: the footer's build-id text is a pure function of BUILDID (loaded from build.json) —
    # value-binds main.js's buildIdText() against the KNOWN fixture build_id/generated above, so a
    # wrong slice/format (or a dropped build.json fetch) fails here, not just "no crash".
    mb = re.search(r"^BUILDID_TEXT (\".*\")\s*$", out, re.M)
    assert mb, "smoke.js did not emit BUILDID_TEXT:\n" + out
    build_txt = json.loads(mb.group(1))
    assert build_txt == " · data build eng1234-src5 · 2026-07-05", build_txt
