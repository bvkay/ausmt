"""Station-drawer API section states the REAL served endpoints (Invariant 10).

The Provenance tab's collapsed "API" expander used to advertise a "Read API (planned)" over three
paths that have never existed on any AusMT deployment:

    GET /api/station/<ausmt_id>.json
    GET /api/survey/<slug>.json
    GET /api/station/<ausmt_id>/edi

There is no /api tier. What the hosted site actually serves is read-only static JSON under /data/,
which is what this section must now say, templated with the station in front of the reader.

The pins below boot the REAL src modules in a VM (the tools/*_test.js / test_drawer_copy_removals.py
idiom) against two synthetic fixtures that differ in ONE respect - whether the manifest carries a
served EDI artifact for the station - and render openStation() for each:

  * FICTIONAL-PATH ABSENCE - FAILS if "(planned)" or any /api/ path survives in the rendered drawer.
    RED-proven against the pre-change drawer.js: that build renders all three fictional paths plus the
    "(planned)" hedge, so it fails this assertion.
  * REAL-ENDPOINT PRESENCE - FAILS if the per-station product endpoints (station.json,
    dimensionality.json, both templated with the station's OWN slug and id), the survey-level
    surveys.json + products/manifest.json, or the About pointer link are missing. This is the
    non-vacuous half: a build that merely deleted the API section would pass the absence pin and
    fail here.
  * ARTIFACT-BEARING vs EMBARGOED - FAILS if the station's own EDI line is absent when the manifest
    carries an EDI row for it, or PRESENT when it does not (an embargoed survey is withheld by
    construction - it has no manifest rows at all, so there is no url to advertise).

The EDI line must come from the manifest row's url, never be templated from the station id: the
served EDI filename is genuinely not derivable from the id (live corpus: station A1 of vulcan-2022
is served as edi/vulcan-2022/Vulcan_A1.edi). The artifact-bearing fixture below reproduces exactly
that mismatch, so a re-templated path would fail the presence assertion.

Skips without Node (CI installs it)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent                 # portal/
SRC = ROOT / "src"
COLS = json.loads((ROOT.parent / "contract" / "columns.json").read_text(encoding="utf-8"))

# The literal the fixture must NOT contain, assembled so this test file's own source never carries the
# fictional path (test_no_fictional_api_paths.py greps the portal tree for it).
FICTIONAL = "/" + "api" + "/"

DRIVER = r"""
const fs=require("fs"),vm=require("vm"),path=require("path");
const SRC=process.argv[2];
const MODULES=["contract","security","state","data","plots","map","filters","drawer","exports","main","tour"];
let code=MODULES.map(f=>fs.readFileSync(path.join(SRC,f+".js"),"utf8")).join("\n");
code+="\nglobalThis.__api={boot,hydrationDone:()=>HYDRATION_DONE,openStation,nST:()=>ST.length};";
const stub=()=>new Proxy(function(){},{get:(t,p)=>{if(p==="then")return undefined;if(p===Symbol.iterator)return function*(){};return stub();},apply:()=>stub(),construct:()=>stub()});
function elStub(){const t={value:"",checked:true,textContent:"",innerHTML:"",scrollTop:0,disabled:false,style:{},dataset:{},children:[],classList:{toggle(){},add(){},remove(){},contains(){return false;}},appendChild(){},addEventListener(){},querySelectorAll(){return[];},querySelector(){return null;},closest(){return null;},setAttribute(){},getAttribute(){return null;},getBoundingClientRect(){return{left:0};},scrollIntoView(){},click(){},onclick:null};return new Proxy(t,{get:(o,p)=>(p in o?o[p]:stub()),set:(o,p,v)=>{o[p]=v;return true;}});}
const elCache={};function elFor(id){if(!elCache[id])elCache[id]=elStub();return elCache[id];}
const data=JSON.parse(fs.readFileSync(process.argv[3],"utf8"));
const ctx={document:{getElementById:id=>elFor(id),createElement:()=>elStub(),addEventListener(){},body:elStub(),querySelector:()=>null,querySelectorAll:sel=>(/typeBoxes/.test(sel)?[{value:"LPMT"},{value:"BBMT"},{value:"AMT"},{value:"GDS"},{value:"other"}]:[])},window:{addEventListener(){},open(){},innerWidth:1200,AUSMT_CONFIG:{short_name:"AusMT"}},location:{hash:"",pathname:"/",search:""},history:{replaceState(){}},navigator:{clipboard:{writeText:()=>Promise.resolve()}},localStorage:{getItem:()=>null,setItem(){},removeItem(){},clear(){}},L:stub(),JSZip:stub(),fetch:url=>Promise.resolve(data[url]?{ok:true,json:()=>Promise.resolve(data[url])}:{ok:false}),URL:{createObjectURL:()=>"x",revokeObjectURL(){}},Blob:function(){},setTimeout:f=>{try{f();}catch(e){}return 0;},clearTimeout(){},console,Math,JSON,Date,Promise,encodeURIComponent,decodeURIComponent,parseInt,parseFloat,isFinite,Set,Array,Object,String,Number};
ctx.globalThis=ctx;ctx.self=ctx;vm.createContext(ctx);vm.runInContext(code,ctx);
// Two-phase boot: boot() returns as soon as the FIRST-PAINT products are in (catalogue/surveys + the small
// optionals); tf.json/sci.json/manifest.json hydrate behind it. This probe renders surfaces that read all
// three, so it awaits hydrationDone() first; otherwise it would assert against loading states.
(async()=>{const A=ctx.__api;await A.boot();await A.hydrationDone();if(A.nST()===0){console.error("FIXTURE EMPTY");process.exit(1);}A.openStation(0);console.log("<<<STATION>>>");console.log(elFor("drawer").innerHTML);console.log("<<<END>>>");})().catch(e=>{console.error("PROBE ERROR:",(e&&e.stack)||e);process.exit(1);});
"""

# Station A1 of survey "Vulcan 2022" (slug vulcan-2022): the live corpus shape, including the served
# EDI filename that is NOT the station id (Vulcan_A1.edi for station A1).
_CAT = {"id": "A1", "survey": "Vulcan 2022", "lat": -30.5, "lon": 135.25, "period_min_s": 0.01,
        "period_max_s": 1000.0, "n_periods": 42, "comps": "ZT", "type": "BBMT", "region": "SA",
        "file": "Vulcan_A1.edi", "coord_flag": False, "ausmt_id": "au.vulcan-2022.A1",
        "edi_available": 1, "sha256": "a" * 64, "site_name": None}
_SCI = {"q": 4.2, "qb": "e", "rr": 1, "sw": "BIRRP", "alg": "robust", "dim": "2-D", "p3d": 10,
        "gd": 0, "ellip": 0.15, "skew": 3.1, "mre": 0.02, "decades": 5.0}
_TF = {"periods": [0.01, 1000.0], "rho_xy": [1.0, 2.0], "rho_yx": [3.0, 4.0], "phs_xy": [10.0, 20.0],
       "phs_yx_adj": [30.0, 40.0], "tip_mag": [0.1, 0.2], "pt_min": [5.0, 6.0], "pt_max": [7.0, 8.0],
       "pt_az": [9.0, 10.0], "pt_beta": [1.0, 2.0], "rho_xy_err": [0.1, 0.2], "rho_yx_err": [0.3, 0.4],
       "phs_xy_err": [1.0, 1.1], "phs_yx_err": [1.2, 1.3], "tzx_re": [0.2, 0.25], "tzx_im": [0.01, 0.02],
       "tzy_re": [0.3, 0.35], "tzy_im": [0.02, 0.03]}

_EDI_ROW = {"ausmt_id": "au.vulcan-2022.A1", "survey": "Vulcan 2022", "station": "A1", "format": "edi",
            "url": "edi/vulcan-2022/Vulcan_A1.edi", "size": 10953, "sha256": "b" * 64, "tier": "repo",
            "license": "CC-BY-4.0", "canon_license": "CC-BY-4.0", "custodian": "Custodian Org"}


def _fixture(*, served, access):
    """The boot payload. served=True gives the station a manifest EDI row (an open, redistributable
    survey); served=False is the embargoed shape the engine actually emits: NO manifest rows at all
    (bytes withheld by construction), with the survey's access level set accordingly."""
    meta = {"slug": "vulcan-2022", "org": "X", "country": "Australia", "lic": "CC-BY-4.0"}
    if access != "open":
        meta["access"] = access
    return {
        "data/catalogue.json": [[_CAT[c] for c in COLS["catalogue"]]],
        "data/sci.json": [[_SCI[c] for c in COLS["sci"]]],
        "data/tf.json": [[_TF[c] for c in COLS["tf"]]],
        "data/surveys.json": {"Vulcan 2022": meta},
        "data/manifest.json": {"generated_count": 1 if served else 0,
                               "files": [_EDI_ROW] if served else [], "bundles": []},
    }


def _render(tmp_path, payload, tag):
    driver = tmp_path / f"api_probe_{tag}.js"
    driver.write_text(DRIVER, encoding="utf-8")
    datafile = tmp_path / f"data_{tag}.json"
    datafile.write_text(json.dumps(payload), encoding="utf-8")
    r = subprocess.run(["node", str(driver), str(SRC), str(datafile)],
                       capture_output=True, text=True, encoding="utf-8")
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "<<<STATION>>>" in out and "<<<END>>>" in out, "probe did not render the drawer:\n" + out
    return out.split("<<<STATION>>>")[1].split("<<<END>>>")[0]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_drawer_api_section_drops_the_fictional_api_tier(tmp_path):
    for served in (True, False):
        html = _render(tmp_path, _fixture(served=served, access="open" if served else "embargoed"),
                       "served" if served else "embargoed")
        assert "(planned)" not in html, (
            f"served={served}: the drawer still hedges the API section with '(planned)'; the /data "
            f"endpoints it now lists are live")
        assert FICTIONAL not in html, (
            f"served={served}: the drawer still advertises a fictional {FICTIONAL} path; no such tier "
            f"has ever existed on an AusMT deployment")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_drawer_api_section_lists_the_real_endpoints(tmp_path):
    html = _render(tmp_path, _fixture(served=True, access="open"), "served")
    for endpoint in ("/data/products/vulcan-2022/A1/station.json",
                     "/data/products/vulcan-2022/A1/dimensionality.json",
                     "/data/surveys.json",
                     "/data/products/manifest.json"):
        assert endpoint in html, f"the drawer API section must list {endpoint}; rendered:\n{html[-2500:]}"
    # Docs wave, stage 2 (owner ruling 3): the depth pointer is the docs site's API reference, and it must
    # be the SAME url About links, so a reader is never sent to two different "for depth" pages. Read off
    # about.html rather than typed twice, which is what makes the two surfaces provably agree.
    about = (ROOT / "about.html").read_text(encoding="utf-8")
    doc_api = "https://ausmt.readthedocs.io/en/latest/interoperability/api-reference/"
    assert doc_api in about, f"about.html must link the docs API reference ({doc_api})"
    assert doc_api in html, f"the drawer API section must link the same docs API reference ({doc_api})"
    assert "about.html#api" not in html, (
        "the drawer's depth pointer moved off About and onto the docs API reference; the old anchor link "
        "must not come back alongside it")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_drawer_edi_line_tracks_the_manifest_row_not_the_station_id(tmp_path):
    """The station's own EDI endpoint is the manifest row's url, joined under /data/. The fixture's
    served filename (Vulcan_A1.edi) deliberately differs from the station id (A1), so a path templated
    from the id would fail here."""
    html = _render(tmp_path, _fixture(served=True, access="open"), "served")
    assert "/data/edi/vulcan-2022/Vulcan_A1.edi" in html, (
        "the artifact-bearing station must advertise its OWN served EDI url from the manifest row; "
        f"rendered:\n{html[-2500:]}")
    assert "/data/edi/vulcan-2022/A1.edi" not in html, (
        "the EDI endpoint must come from the manifest row, not be templated from the station id")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_drawer_edi_line_absent_for_an_embargoed_station(tmp_path):
    """An embargoed survey is withheld by construction: the engine emits no manifest rows for it, so
    there is no EDI url to advertise and the line must simply not be rendered (never a dead link).
    The survey-level endpoints stay: the catalogue record itself is still public."""
    html = _render(tmp_path, _fixture(served=False, access="embargoed"), "embargoed")
    assert "/data/edi/" not in html, (
        "an embargoed station has no manifest artifact row, so the API section must render NO EDI "
        f"endpoint line; rendered:\n{html[-2500:]}")
    assert "/data/products/manifest.json" in html, (
        "the survey-level endpoints must survive for an embargoed station (its record is still public)")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
@pytest.mark.parametrize("access", ["embargoed", "metadata_only"])
def test_drawer_omits_dimensionality_for_a_non_served_station(tmp_path, access):
    """A NON-SERVED survey (embargoed with any date, or metadata_only) gets a WITHHELD station.json and
    NO dimensionality.json at all: the engine returns before writing it (build_portal.py
    _write_station_products, "no dimensionality.json for a non-served survey"), because a dimensionality
    classification is pure interpretation of the embargoed transfer function. Advertising that path here
    would hand ~17% of catalogue stations a GET line that 404s, which is the same fictional-endpoint
    defect this module exists to prevent, only smaller.

    station.json is the OTHER half and must SURVIVE: it is emitted for a non-served survey as a withheld
    stub that names the access state, so it resolves and is worth pointing at. Asserting both directions
    keeps the fix from being satisfied by deleting the per-station block outright."""
    html = _render(tmp_path, _fixture(served=False, access=access), "nonserved_" + access)
    assert "dimensionality.json" not in html, (
        f"access={access}: the engine emits NO dimensionality.json for a non-served survey, so the API "
        f"section must not advertise one; rendered:\n{html[-2500:]}")
    assert "/data/products/vulcan-2022/A1/station.json" in html, (
        f"access={access}: station.json IS emitted for a non-served survey (a withheld stub stating the "
        f"access state), so the per-station line must stay")
