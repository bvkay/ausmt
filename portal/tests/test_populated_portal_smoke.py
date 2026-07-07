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
                "ausmt_id": "au.demo.ST1", "edi_available": 1, "sha256": "a" * 64}
    sci_vals = {"q": 4.2, "qb": "e", "rr": 1, "sw": "BIRRP", "alg": "robust", "dim": "2-D",
                "p3d": 10, "gd": 0, "ellip": 0.15, "skew": 3.1, "mre": 0.02, "decades": 5.0}
    cat_row = [cat_vals[c] for c in COLS["catalogue"]]
    sci_row = [sci_vals[c] for c in COLS["sci"]]
    # tf entry: 10 arrays in TF_COLUMNS order (periods first)
    tf_row = [[0.01, 1000.0], [1.0, 2.0], [3.0, 4.0], [10.0, 20.0], [30.0, 40.0],
              [0.1, 0.2], [5.0, 6.0], [7.0, 8.0], [9.0, 10.0], [1.0, 2.0]]

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

    # (b) exports.js CSV row for ST0 — value-binds the EXPORT call site's sc[SC.*] derefs; the ONLY
    # coverage of qb/rr/sw (buildState/drawer don't expose them). Column order per the exports.js header.
    me = re.search(r"^EXPORT0 (\[.*\])\s*$", out, re.M)
    assert me, "smoke.js did not emit EXPORT0 (CSV row):\n" + out
    ex = json.loads(me.group(1))
    assert ex[12] == 4.2, ex                            # quality        <- sc[SC.q]
    assert ex[13] == "error", ex                        # quality_basis  <- sc[SC.qb] == "e"
    assert ex[14] == "yes", ex                          # remote_ref     <- sc[SC.rr]
    assert ex[15] == "2-D", ex                          # dimensionality <- sc[SC.dim]
    assert ex[16] == "BIRRP", ex                        # software       <- sc[SC.sw]
    # C6: the licence column travels with the exported row (sourced from SMETA[survey].lic). It is the
    # LAST column; a wrong/missing SMETA.lic deref (or dropping the column) makes this FAIL, not just crash.
    assert ex[-1] == "CC-BY-4.0", ex                    # license        <- SMETA["Demo Survey"].lic

    # (c) C12: the footer's build-id text is a pure function of BUILDID (loaded from build.json) —
    # value-binds main.js's buildIdText() against the KNOWN fixture build_id/generated above, so a
    # wrong slice/format (or a dropped build.json fetch) fails here, not just "no crash".
    mb = re.search(r"^BUILDID_TEXT (\".*\")\s*$", out, re.M)
    assert mb, "smoke.js did not emit BUILDID_TEXT:\n" + out
    build_txt = json.loads(mb.group(1))
    assert build_txt == " · data build eng1234-src5 · 2026-07-05", build_txt
