"use strict";
// Shared mutable state (assigned during boot) + constants + small colour/format utils.
// No survey metadata is hard-coded here; SMETA is loaded from data/surveys.json at boot.
let CAT,TFD,SCI,SMETA,PROV,COLL,MANIFEST,BUILDID; /*__DATA_BINDING__*/
let ST=[],surveys=[],visible=[],selected=new Set(),curView="map",colorMode="type",qMin=0;
let SLUG_TO_SURVEY={};   // slug -> survey label, built in buildState(); backs the #/survey/<slug> route
// UX4 (D1/D2): the set of survey SLUGS that belong to the `auslamp` collection, built once at boot
// (buildAuslampSet, main.js) from COLL[auslamp].surveys (which holds survey LABELS) resolved through
// SMETA[label].slug. Empty when collections.json is absent or has no auslamp collection — graceful
// degrade: isAuslampSurvey() then returns false for everything and the map behaves as before UX4.
let AUSLAMP_SET=new Set();

const TYPE_COL={LPMT:"#2E8FA3",BBMT:"#E0782F",AMT:"#A85CC4",GDS:"#5BAE6A",other:"#999"};
const DIM_COL={"1-D":"#2E8FA3","2-D":"#D9A23B","3-D":"#A85454",null:"#5A6E7D"};
// country drives the hierarchy, so {country:"New Zealand"} surfaces NZ with zero code change.
const CC={"Australia":"AU","New Zealand":"NZ","Antarctica":"AQ","Indonesia":"ID"};
const TS_COLLECTION={doi:"10.25914/mtjg-jp22",name:"NCI-AuScope Magnetotelluric Collection"};
// UX feedback round 1: "Go to place" (+ its AU_PLACES quick-zoom list) was removed as redundant —
// operator decision from the first live session; see index.html/filters.js for the rest of the removal.
const AUSMT_SELF={au:"AusMT contributors",yr:"2026",ti:"AusMT: curated station metadata, quality and provenance for Australian magnetotelluric transfer functions",ve:(window.AUSMT_CONFIG&&window.AUSMT_CONFIG.version)||"",pb:"AusMT (DOI to be minted per release via Zenodo)"};
const NCI_CITE={au:"AuScope; NCI Australia",yr:"",ti:"NCI-AuScope Magnetotelluric Collection — packed raw, Level 1 and Level 2 time series",ve:"",pb:"NCI Australia"};

const fmtP=p=>p>=1000?Math.round(p).toLocaleString("en-AU"):p>=1?(+p.toFixed(1)).toString():p.toPrecision(2);
function clamp(x){return Math.max(0,Math.min(1,x));}
function lerp(a,b,t){const pa=[1,3,5].map(i=>parseInt(a.substr(i,2),16)),pb=[1,3,5].map(i=>parseInt(b.substr(i,2),16));
  return "#"+pa.map((v,k)=>Math.round(v+(pb[k]-v)*t).toString(16).padStart(2,"0")).join("");}
function qColor(q){if(q==null)return "#5A6E7D";const t=clamp((q-2)/3);return t<.5?lerp("#A85454","#D9A23B",t*2):lerp("#D9A23B","#5BAE6A",(t-.5)*2);}
