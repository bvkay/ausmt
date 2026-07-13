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
// C42 Amendment A1: ausmt_id -> coordinate policy ('generalised' | 'withheld') for NON-EXACT stations,
// loaded at boot from the OPTIONAL coord_policy.json (absent for an all-exact corpus => empty => no
// badges — graceful degrade, same tolerant-of-absence pattern as collections/manifest). buildState()
// folds it onto each station as s.coordPolicy; the drawer badges from that. It carries POLICY, never a
// coordinate — positions are already masked in the catalogue (generalised => 0.1° cell, withheld => null).
let COORD_POLICY={};

// UX6 Wave B (B2 colour de-collision): BBMT moved off the copper action hex (#E0782F), and GDS off the
// ok/status green (#5BAE6A), so a data-type marker can no longer be mistaken for the selection accent or a
// "good" status. LPMT teal is pinned (interaction test).
// UX8 (X1, owner-delegated): the four data-type hues are pulled further apart. BBMT #3F6FC4 -> #5E5ED6
// (indigo) and AMT #A85CC4 -> #CDA1EC (light violet); LPMT teal and GDS magenta unchanged. The old AMT
// purple sat only ΔE00≈10 from the GDS magenta (confusable); the new pair is ΔE00≈21 with a ~20 L*
// lightness gap, and every data-type pair is now ΔE00≥21 (the four types are the four most mutually
// distinct hues in the palette). These are the map-marker colours; the index.html --lpmt/--bbmt/--amt/
// --gds tokens carry the SAME hexes so the filter legend, the type-filter swatches and the map agree
// byte-for-byte. (plots.js TF-curve colours are independent and unchanged.) DIM_COL is a NON-STATUS
// palette (a cool→warm violet/magenta ramp): dimensionality (1-D/2-D/3-D) is not a quality ranking, so it
// must not borrow the red/amber/green status colours.
const TYPE_COL={LPMT:"#2E8FA3",BBMT:"#5E5ED6",AMT:"#CDA1EC",GDS:"#C255A0",other:"#999"};
const DIM_COL={"1-D":"#4E8FC9","2-D":"#8A5FC0","3-D":"#C44F92",null:"#5A6E7D"};
// country drives the hierarchy, so {country:"New Zealand"} surfaces NZ with zero code change.
const CC={"Australia":"AU","New Zealand":"NZ","Antarctica":"AQ","Indonesia":"ID"};
const TS_COLLECTION={doi:"10.25914/mtjg-jp22",name:"NCI-AuScope Magnetotelluric Collection"};
// UX feedback round 1: "Go to place" (+ its AU_PLACES quick-zoom list) was removed as redundant —
// operator decision from the first live session; see index.html/filters.js for the rest of the removal.
// C22 (2026-07-07): pb is the HONEST plain "AusMT". The pre-C22 value — "AusMT (DOI to be minted per
// release via Zenodo)" — leaked into EVERY no-DOI citation's publisher/PB field of the exported .bib/.ris
// packs (hostile review 2026-07-06: reference managers ingest that placeholder as real bibliographic
// data). Absence of a DOI is expressed by OMISSION in .bib/.ris (drawer.js apa/bibtex/ris guard on a
// falsy doi, since d2bc616) and EXPLICITLY in CITATIONS.txt ("[no DOI assigned]", exports.js citeLine) —
// never by placeholder text in a bibliographic field.
const AUSMT_SELF={au:"AusMT contributors",yr:"2026",ti:"AusMT: curated station metadata, quality and provenance for Australian magnetotelluric transfer functions",ve:(window.AUSMT_CONFIG&&window.AUSMT_CONFIG.version)||"",pb:"AusMT"};
const NCI_CITE={au:"AuScope; NCI Australia",yr:"",ti:"NCI-AuScope Magnetotelluric Collection — packed raw, Level 1 and Level 2 time series",ve:"",pb:"NCI Australia"};

const fmtP=p=>p>=1000?Math.round(p).toLocaleString("en-AU"):p>=1?(+p.toFixed(1)).toString():p.toPrecision(2);
function clamp(x){return Math.max(0,Math.min(1,x));}
function lerp(a,b,t){const pa=[1,3,5].map(i=>parseInt(a.substr(i,2),16)),pb=[1,3,5].map(i=>parseInt(b.substr(i,2),16));
  return "#"+pa.map((v,k)=>Math.round(v+(pb[k]-v)*t).toString(16).padStart(2,"0")).join("");}
// C46-W3b: qColor's low end is the CURRENT status red (#E2938B, the --no token) rather than the retired
// #A85454 (now off-palette). These are graphical dots, so AA contrast is not binding; the point is that the
// low end tracks the status palette instead of a stale hardcoded red. (The dead --q0/--q3/--q5 CSS tokens
// that mirrored the old ramp endpoints were removed with this change.)
function qColor(q){if(q==null)return "#5A6E7D";const t=clamp((q-2)/3);return t<.5?lerp("#E2938B","#D9A23B",t*2):lerp("#D9A23B","#5BAE6A",(t-.5)*2);}
