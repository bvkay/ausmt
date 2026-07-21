"""Owner-requested drawer copy removals — render pins (Invariant 10).

Two placeholder/aggregate lines were removed from portal/src/drawer.js:
  (1) the SURVEY-summary "Automated completeness/smoothness check" row (the qavg mean-of-per-station-Q
      aggregate) — a not-a-verdict number the owner did not want at the survey-level 10-second view;
  (2) the STATION-drawer Tier-3 "Advanced analysis · Tier 3, generated offline" placeholder block
      (McNeice-Jones / Groom-Bailey decomposition ... "planned AusMT pipeline products ... Not computed
      in the browser.") — a not-yet-produced-products stub.

This boots the REAL src modules in a VM (smoke.js idiom) against a synthetic one-survey/one-station
fixture carrying a q value, keeps a stable per-id element cache so drawer.innerHTML persists, then renders
BOTH the station drawer (openStation) and the survey summary (openSurvey) and asserts on the OBSERVABLE
HTML — so it fails if the copy comes back, and (retained-content pins) if the removal over-deleted.

SCOPE GUARD: the PER-STATION completeness/smoothness line in the station drawer science section is NOT
part of this removal; the station-drawer retained pin asserts it still renders (exactly once).

Skips without Node (CI installs it)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent                 # portal/
SRC = ROOT / "src"
COLS = json.loads((ROOT.parent / "contract" / "columns.json").read_text())

DRIVER = r"""
const fs=require("fs"),vm=require("vm"),path=require("path");
const SRC=process.argv[2];
const MODULES=["contract","security","state","data","plots","map","filters","drawer","exports","main","tour"];
let code=MODULES.map(f=>fs.readFileSync(path.join(SRC,f+".js"),"utf8")).join("\n");
code+="\nglobalThis.__api={boot,openStation,openSurvey,nST:()=>ST.length,firstSurvey:()=>surveys[0]};";
const stub=()=>new Proxy(function(){},{get:(t,p)=>{if(p==="then")return undefined;if(p===Symbol.iterator)return function*(){};return stub();},apply:()=>stub(),construct:()=>stub()});
function elStub(){const t={value:"",checked:true,textContent:"",innerHTML:"",scrollTop:0,disabled:false,style:{},dataset:{},children:[],classList:{toggle(){},add(){},remove(){},contains(){return false;}},appendChild(){},addEventListener(){},querySelectorAll(){return[];},querySelector(){return null;},closest(){return null;},setAttribute(){},getAttribute(){return null;},getBoundingClientRect(){return{left:0};},scrollIntoView(){},click(){},onclick:null};return new Proxy(t,{get:(o,p)=>(p in o?o[p]:stub()),set:(o,p,v)=>{o[p]=v;return true;}});}
const elCache={};function elFor(id){if(!elCache[id])elCache[id]=elStub();return elCache[id];}
const data=JSON.parse(fs.readFileSync(process.argv[3],"utf8"));
const ctx={document:{getElementById:id=>elFor(id),createElement:()=>elStub(),addEventListener(){},body:elStub(),querySelector:()=>null,querySelectorAll:sel=>(/typeBoxes/.test(sel)?[{value:"LPMT"},{value:"BBMT"},{value:"AMT"},{value:"GDS"},{value:"other"}]:[])},window:{addEventListener(){},open(){},innerWidth:1200,AUSMT_CONFIG:{short_name:"AusMT"}},location:{hash:"",pathname:"/",search:""},history:{replaceState(){}},navigator:{clipboard:{writeText:()=>Promise.resolve()}},localStorage:{getItem:()=>null,setItem(){},removeItem(){},clear(){}},L:stub(),JSZip:stub(),fetch:url=>Promise.resolve(data[url]?{ok:true,json:()=>Promise.resolve(data[url])}:{ok:false}),URL:{createObjectURL:()=>"x",revokeObjectURL(){}},Blob:function(){},setTimeout:f=>{try{f();}catch(e){}return 0;},clearTimeout(){},console,Math,JSON,Date,Promise,encodeURIComponent,decodeURIComponent,parseInt,parseFloat,isFinite,Set,Array,Object,String,Number};
ctx.globalThis=ctx;ctx.self=ctx;vm.createContext(ctx);vm.runInContext(code,ctx);
(async()=>{const A=ctx.__api;await A.boot();if(A.nST()===0){console.error("FIXTURE EMPTY");process.exit(1);}A.openStation(0);const stationHtml=elFor("drawer").innerHTML;A.openSurvey(A.firstSurvey());const surveyHtml=elFor("drawer").innerHTML;console.log("<<<STATION>>>");console.log(stationHtml);console.log("<<<SURVEY>>>");console.log(surveyHtml);console.log("<<<END>>>");})().catch(e=>{console.error("PROBE ERROR:",(e&&e.stack)||e);process.exit(1);});
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_drawer_copy_removals(tmp_path):
    cat = {"id": "ST1", "survey": "Demo Survey", "lat": -30.5, "lon": 135.25, "period_min_s": 0.01,
           "period_max_s": 1000.0, "n_periods": 42, "comps": "ZT", "type": "BBMT", "region": "SA",
           "file": "ST1.edi", "coord_flag": False, "ausmt_id": "au.demo.ST1", "edi_available": 1,
           "sha256": "a" * 64}
    sci = {"q": 4.2, "qb": "e", "rr": 1, "sw": "BIRRP", "alg": "robust", "dim": "2-D", "p3d": 10,
           "gd": 0, "ellip": 0.15, "skew": 3.1, "mre": 0.02, "decades": 5.0}
    tf = {"periods": [0.01, 1000.0], "rho_xy": [1.0, 2.0], "rho_yx": [3.0, 4.0], "phs_xy": [10.0, 20.0],
          "phs_yx_adj": [30.0, 40.0], "tip_mag": [0.1, 0.2], "pt_min": [5.0, 6.0], "pt_max": [7.0, 8.0],
          "pt_az": [9.0, 10.0], "pt_beta": [1.0, 2.0], "rho_xy_err": [0.1, 0.2], "rho_yx_err": [0.3, 0.4],
          "phs_xy_err": [1.0, 1.1], "phs_yx_err": [1.2, 1.3], "tzx_re": [0.2, 0.25], "tzx_im": [0.01, 0.02],
          "tzy_re": [0.3, 0.35], "tzy_im": [0.02, 0.03]}
    data = {
        "data/catalogue.json": [[cat[c] for c in COLS["catalogue"]]],
        "data/sci.json": [[sci[c] for c in COLS["sci"]]],
        "data/tf.json": [[tf[c] for c in COLS["tf"]]],
        "data/surveys.json": {"Demo Survey": {"slug": "demo", "org": "X", "country": "Australia",
                                              "lic": "CC-BY-4.0"}},
        "data/build.json": {"build_id": "e-s-2026", "engine_commit": "e", "source_commit": "s",
                            "generated": "2026-07-05T00:00:00+00:00"},
    }
    driver = tmp_path / "drawer_probe.js"
    driver.write_text(DRIVER, encoding="utf-8")
    datafile = tmp_path / "data.json"
    datafile.write_text(json.dumps(data), encoding="utf-8")

    r = subprocess.run(["node", str(driver), str(SRC), str(datafile)],
                       capture_output=True, text=True, encoding="utf-8")
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "<<<STATION>>>" in out and "<<<END>>>" in out, "probe did not render the drawer:\n" + out
    station = out.split("<<<STATION>>>")[1].split("<<<SURVEY>>>")[0]
    survey = out.split("<<<SURVEY>>>")[1].split("<<<END>>>")[0]

    # (a) survey-summary completeness/smoothness row removed
    assert "completeness/smoothness check" not in survey, \
        "survey summary still renders the completeness/smoothness row:\n" + survey
    assert "not a quality verdict" not in survey, \
        "survey summary still renders the '(not a quality verdict)' aggregate:\n" + survey

    # (b) station-drawer Tier-3 advanced-analysis placeholder removed
    assert "Advanced analysis" not in station, "station drawer still renders the Tier-3 placeholder header"
    assert "pipeline products" not in station, "station drawer still renders the 'planned pipeline products' copy"
    assert "Not computed in the browser" not in station, "station drawer still renders the Tier-3 body copy"

    # (c) retained content — the removal did not over-delete
    assert survey.count("Survey summary") == 1, "survey-summary heading missing"
    assert "processing software" in survey, "survey 'processing software' row missing"
    assert "tipper availability" in survey, "survey 'tipper availability' row missing"
    assert "Screening indicators" in station, "station 'Screening indicators' section missing"
    assert "Related products" in station, "station 'Related products' section missing"
    # SCOPE GUARD: the per-station completeness/smoothness line stays (it is NOT the removed survey row)
    assert station.count("Automated completeness/smoothness check") == 1, \
        "per-station completeness/smoothness line was wrongly removed (out of scope)"
