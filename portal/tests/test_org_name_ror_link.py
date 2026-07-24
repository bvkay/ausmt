"""Owner-requested (2026-07-22): the organisation NAME is the ROR link — render pins.

The separate little ROR logo badge (vendor/ror-logo.png, appended after the org name) was dropped. Instead,
when a survey carries an org ROR the organisation NAME itself becomes an <a class="orglink"> to the canonical
ror.org landing page; with NO org ROR the name renders as plain (non-anchor) escaped text.

Boots the REAL src modules in a VM (the smoke.js / copy-removals idiom) against a synthetic one-survey
fixture and renders BOTH the station drawer (openStation) and the survey story (openSurvey), asserting on the
OBSERVABLE HTML. Runs twice: once WITH a full https://ror.org/... org_ror (name is a linked anchor, no <img>
badge) and once WITHOUT (plain name, no anchor). The shared orgNameLink helper backs all three org surfaces.

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


def _render(tmp_path, org_ror):
    cat = {"id": "ST1", "survey": "Demo Survey", "lat": -30.5, "lon": 135.25, "period_min_s": 0.01,
           "period_max_s": 1000.0, "n_periods": 42, "comps": "ZT", "type": "BBMT", "region": "SA",
           "file": "ST1.edi", "coord_flag": False, "ausmt_id": "au.demo.ST1", "edi_available": 1,
           "sha256": "a" * 64, "site_name": None}
    sci = {"q": 4.2, "qb": "e", "rr": 1, "sw": "BIRRP", "alg": "robust", "dim": "2-D", "p3d": 10,
           "gd": 0, "ellip": 0.15, "skew": 3.1, "mre": 0.02, "decades": 5.0}
    tf = {"periods": [0.01, 1000.0], "rho_xy": [1.0, 2.0], "rho_yx": [3.0, 4.0], "phs_xy": [10.0, 20.0],
          "phs_yx_adj": [30.0, 40.0], "tip_mag": [0.1, 0.2], "pt_min": [5.0, 6.0], "pt_max": [7.0, 8.0],
          "pt_az": [9.0, 10.0], "pt_beta": [1.0, 2.0], "rho_xy_err": [0.1, 0.2], "rho_yx_err": [0.3, 0.4],
          "phs_xy_err": [1.0, 1.1], "phs_yx_err": [1.2, 1.3], "tzx_re": [0.2, 0.25], "tzx_im": [0.01, 0.02],
          "tzy_re": [0.3, 0.35], "tzy_im": [0.02, 0.03]}
    survey = {"slug": "demo", "org": "Geoscience Australia", "country": "Australia", "lic": "CC-BY-4.0"}
    if org_ror is not None:
        survey["org_ror"] = org_ror
    data = {
        "data/catalogue.json": [[cat[c] for c in COLS["catalogue"]]],
        "data/sci.json": [[sci[c] for c in COLS["sci"]]],
        "data/tf.json": [[tf[c] for c in COLS["tf"]]],
        "data/surveys.json": {"Demo Survey": survey},
        "data/build.json": {"build_id": "e-s-2026", "engine_commit": "e", "source_commit": "s",
                            "generated": "2026-07-05T00:00:00+00:00"},
    }
    driver = tmp_path / "orgror_probe.js"
    driver.write_text(DRIVER, encoding="utf-8")
    datafile = tmp_path / "data.json"
    datafile.write_text(json.dumps(data), encoding="utf-8")
    r = subprocess.run(["node", str(driver), str(SRC), str(datafile)],
                       capture_output=True, text=True, encoding="utf-8")
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "<<<STATION>>>" in out and "<<<END>>>" in out, "probe did not render the drawer:\n" + out
    station = out.split("<<<STATION>>>")[1].split("<<<SURVEY>>>")[0]
    story = out.split("<<<SURVEY>>>")[1].split("<<<END>>>")[0]
    return station, story


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_org_name_is_ror_link_when_present(tmp_path):
    station, story = _render(tmp_path, "https://ror.org/00892tw58")
    for surface, html in (("station header", station), ("survey story", story)):
        # org name is an anchor to the served ror.org URL, carrying the .orglink class
        assert '<a class="orglink" href="https://ror.org/00892tw58"' in html, \
            f"{surface}: org name is not the ROR anchor:\n" + html
        assert ">Geoscience Australia</a>" in html, \
            f"{surface}: the org NAME is not the link text:\n" + html
        # the old logo badge is gone: no ROR <img> / vendor asset referenced anywhere
        assert "vendor/ror-logo.png" not in html, f"{surface}: the dropped ROR logo image is still rendered"
        assert 'class="ror-logo"' not in html and 'class="ror-ico"' not in html, \
            f"{surface}: a ROR logo/badge element is still rendered"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_org_name_is_plain_text_when_no_ror(tmp_path):
    station, story = _render(tmp_path, None)
    for surface, html in (("station header", station), ("survey story", story)):
        assert "Geoscience Australia" in html, f"{surface}: the org name went missing:\n" + html
        assert "orglink" not in html, f"{surface}: org name is an anchor despite no org_ror:\n" + html
        assert "vendor/ror-logo.png" not in html, f"{surface}: a ROR logo image rendered with no org_ror"
