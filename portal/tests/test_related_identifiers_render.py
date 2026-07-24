"""§2a/§2b (identifiers design — the related-identifiers model): drawer render pins.

Boots the REAL src modules in a VM (the org_name_ror_link / smoke.js idiom) against a synthetic
one-survey fixture and renders BOTH the station drawer (openStation) and the survey story (openSurvey),
asserting on the OBSERVABLE HTML. Three shapes:

  A. A curator survey — dataset_doi NULL, but a DOI-typed related_identifier (IsDerivedFrom, custodian
     NCI) — vulcan-2022's real shape — plus a survey-level identifiers.instrument_pid. Pins: the Related
     identifiers block renders the relation as a human label with a doi.org anchor and the muted
     custodian; the Platform/instrument PID line renders a doi.org anchor; the DOI badge lights "ok"
     DESPITE no dataset_doi (the typed DOI satisfies the provenance-chain reading).
  B. A hostile identifier value — must NEVER become an executable anchor (escUrl -> href "#").
  C. A survey with NEITHER a dataset_doi NOR any related_identifiers — the block does not render and the
     DOI badge is "no".

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
code+="\nglobalThis.__api={boot,openStation,openSurvey,surveyCard,nST:()=>ST.length,firstSurvey:()=>surveys[0]};";
const stub=()=>new Proxy(function(){},{get:(t,p)=>{if(p==="then")return undefined;if(p===Symbol.iterator)return function*(){};return stub();},apply:()=>stub(),construct:()=>stub()});
function elStub(){const t={value:"",checked:true,textContent:"",innerHTML:"",scrollTop:0,disabled:false,style:{},dataset:{},children:[],classList:{toggle(){},add(){},remove(){},contains(){return false;}},appendChild(){},addEventListener(){},querySelectorAll(){return[];},querySelector(){return null;},closest(){return null;},setAttribute(){},getAttribute(){return null;},getBoundingClientRect(){return{left:0};},scrollIntoView(){},click(){},onclick:null};return new Proxy(t,{get:(o,p)=>(p in o?o[p]:stub()),set:(o,p,v)=>{o[p]=v;return true;}});}
const elCache={};function elFor(id){if(!elCache[id])elCache[id]=elStub();return elCache[id];}
const data=JSON.parse(fs.readFileSync(process.argv[3],"utf8"));
const ctx={document:{getElementById:id=>elFor(id),createElement:()=>elStub(),addEventListener(){},body:elStub(),querySelector:()=>null,querySelectorAll:sel=>(/typeBoxes/.test(sel)?[{value:"LPMT"},{value:"BBMT"},{value:"AMT"},{value:"GDS"},{value:"other"}]:[])},window:{addEventListener(){},open(){},innerWidth:1200,AUSMT_CONFIG:{short_name:"AusMT"}},location:{hash:"",pathname:"/",search:""},history:{replaceState(){}},navigator:{clipboard:{writeText:()=>Promise.resolve()}},localStorage:{getItem:()=>null,setItem(){},removeItem(){},clear(){}},L:stub(),JSZip:stub(),fetch:url=>Promise.resolve(data[url]?{ok:true,json:()=>Promise.resolve(data[url])}:{ok:false}),URL:{createObjectURL:()=>"x",revokeObjectURL(){}},Blob:function(){},setTimeout:f=>{try{f();}catch(e){}return 0;},clearTimeout(){},console,Math,JSON,Date,Promise,encodeURIComponent,decodeURIComponent,parseInt,parseFloat,isFinite,Set,Array,Object,String,Number};
ctx.globalThis=ctx;ctx.self=ctx;vm.createContext(ctx);vm.runInContext(code,ctx);
(async()=>{const A=ctx.__api;await A.boot();if(A.nST()===0){console.error("FIXTURE EMPTY");process.exit(1);}A.openStation(0);const stationHtml=elFor("drawer").innerHTML;A.openSurvey(A.firstSurvey());const surveyHtml=elFor("drawer").innerHTML;const cardHtml=A.surveyCard(A.firstSurvey());console.log("<<<STATION>>>");console.log(stationHtml);console.log("<<<SURVEY>>>");console.log(surveyHtml);console.log("<<<CARD>>>");console.log(cardHtml);console.log("<<<END>>>");})().catch(e=>{console.error("PROBE ERROR:",(e&&e.stack)||e);process.exit(1);});
"""


def _render(tmp_path, survey_extra):
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
    survey.update(survey_extra)
    data = {
        "data/catalogue.json": [[cat[c] for c in COLS["catalogue"]]],
        "data/sci.json": [[sci[c] for c in COLS["sci"]]],
        "data/tf.json": [[tf[c] for c in COLS["tf"]]],
        "data/surveys.json": {"Demo Survey": survey},
        "data/build.json": {"build_id": "e-s-2026", "engine_commit": "e", "source_commit": "s",
                            "generated": "2026-07-05T00:00:00+00:00"},
    }
    driver = tmp_path / "relid_probe.js"
    driver.write_text(DRIVER, encoding="utf-8")
    datafile = tmp_path / "data.json"
    datafile.write_text(json.dumps(data), encoding="utf-8")
    r = subprocess.run(["node", str(driver), str(SRC), str(datafile)],
                       capture_output=True, text=True, encoding="utf-8")
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "<<<STATION>>>" in out and "<<<END>>>" in out, "probe did not render the drawer:\n" + out
    station = out.split("<<<STATION>>>")[1].split("<<<SURVEY>>>")[0]
    story = out.split("<<<SURVEY>>>")[1].split("<<<CARD>>>")[0]
    card = out.split("<<<CARD>>>")[1].split("<<<END>>>")[0]
    return station, story, card


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_curator_survey_related_block_and_doi_badge(tmp_path):
    # vulcan-2022's real shape: dataset_doi null, the DOI lives in the typed provenance list.
    extra = {"related_identifiers": [{"identifier": "10.25914/sv5r-zw68", "identifier_type": "DOI",
                                      "relation": "IsDerivedFrom", "custodian": "NCI"}],
             "instrument_pid": "10.82388/bt6orvhn"}
    station, story, card = _render(tmp_path, extra)
    # The Related identifiers block renders on the survey story (identifiersHtml rollup).
    assert "Related identifiers:" in story, "the Related identifiers block did not render:\n" + story
    # relation -> human label, identifier -> doi.org anchor, custodian -> muted text.
    assert 'href="https://doi.org/10.25914/sv5r-zw68"' in story, \
        "the DOI-typed identifier is not a doi.org anchor:\n" + story
    assert "Derived from:" in story, "the relation is not rendered as a human label:\n" + story
    assert "(NCI)" in story, "the custodian is not rendered:\n" + story
    # survey-level instrument/platform PID renders its own doi.org-linked line.
    assert "Platform/instrument PID:" in story, "the survey-level instrument PID line is missing:\n" + story
    assert 'href="https://doi.org/10.82388/bt6orvhn"' in story, \
        "the instrument PID is not a doi.org anchor:\n" + story
    # R8: the station format-availability DOI badge is dropped (dataset-DOI presence is conveyed by the
    # maturity star + identifiers block). The survey-card DOI badge remains and lights "ok" for a
    # typed-DOI-only survey (the typed DOI satisfies the provenance-chain reading).
    assert "✓ DOI" in card, "survey-card DOI badge is not 'ok' for a typed-DOI-only survey:\n" + card
    assert "✗ DOI" not in card, "a DOI badge still reads 'no' on the card"
    assert "✓ DOI" not in station and "✗ DOI" not in station, \
        "R8: the station Format availability block must no longer carry a DOI badge:\n" + station


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_hostile_related_identifier_is_never_an_anchor(tmp_path):
    # A javascript: identifier of a NON-DOI/Handle/URL type prints as inert escaped text (no anchor);
    # a URL-typed javascript: value routes through escUrl and its href collapses to "#".
    extra = {"related_identifiers": [
        {"identifier": "javascript:alert(1)", "identifier_type": "Frobnicate", "relation": "Cites"},
        {"identifier": "javascript:alert(2)", "identifier_type": "URL", "relation": "IsSupplementTo"}]}
    _station, story, _card = _render(tmp_path, extra)
    assert 'href="javascript:' not in story, "a hostile identifier became an executable anchor:\n" + story
    # the out-of-type value is escaped plain text, not linked at all
    assert "javascript:alert(1)" in story or "javascript:alert(1)".replace(":", "") in story
    # the URL-typed hostile value linked, but through escUrl -> href "#"
    assert 'href="#"' in story, "the URL-typed hostile value did not collapse to href '#':\n" + story


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_no_identifier_survey_no_block_no_doi(tmp_path):
    station, story, card = _render(tmp_path, {})   # no dataset_doi, no related_identifiers
    assert "Related identifiers:" not in story, "the block rendered for a survey with no typed relations:\n" + story
    assert "Platform/instrument PID:" not in story, "the instrument PID line rendered when absent:\n" + story
    # R8: no station DOI badge at all; the survey-card DOI badge still reads "no" for a DOI-less survey.
    assert "✗ DOI" in card, "survey-card DOI badge is not 'no' for a survey with no DOI anywhere:\n" + card
    assert "✓ DOI" not in station and "✗ DOI" not in station, \
        "R8: the station Format availability block must no longer carry a DOI badge:\n" + station
