"use strict";
// Shared mutable state (assigned during boot) + constants + small colour/format utils.
// No survey metadata is hard-coded here; SMETA is loaded from data/surveys.json at boot.
let CAT,TFD,SCI,SMETA,PROV,COLL,MANIFEST,BUILDID; /*__DATA_BINDING__*/
// ---- two-phase boot: background hydration gates ------------------------------------------------
// The boot paints from the SMALL products (catalogue + surveys, plus the four small optionals). See
// docs: portal internals, state.js.
let TF_READY=Promise.resolve(),SCI_READY=Promise.resolve(),MANIFEST_READY=Promise.resolve();
// ts_access.json rides phase 2 as well. The chooser it feeds is a facet most visitors
// never open, so a phase-1 fetch would add a blocking boot request for it; the Availability controls
// are disabled and aria-busy across the window instead, exactly as the colour modes are.
let TSACC_READY=Promise.resolve();
const HYDR={tf:"ready",sci:"ready",manifest:"ready",tsaccess:"ready"};
function hydrating(k){return HYDR[k]==="pending";}
function hydrFailed(k){return HYDR[k]==="failed";}
// A product is USABLE only when it is loaded. "pending" and "failed" are two different REASONS for one
// fact: the values are not here. See docs: portal internals, state.js.
function hydrUsable(k){return HYDR[k]==="ready";}
// The two positional rows consumers deref by station index. Both tolerate a NOT-YET-ASSIGNED global
// (phase 1 renders before tf/sci land), so a pre-hydration read yields the same empty row an absent product
// yields; the DISPLAY difference is carried by hydrating()/hydrFailed(), never by the data itself.
function sciRow(i){return (SCI&&SCI[i])||[];}
function tfRow(i){return (TFD&&TFD[i])||null;}
let ST=[],surveys=[],visible=[],selected=new Set(),curView="map",qMin=0;
// The period-window predicate is HEADLESS: no slider control drives it, passesCore reads these
// bounds and harnesses set them. Full-range defaults = the filter is off.
let periodLo=0.001,periodHi=100000;
let SLUG_TO_SURVEY={};   // slug -> survey label, built in buildState(); backs the #/survey/<slug> route
// The set of survey SLUGS that belong to the `auslamp` collection, built once at boot (buildAuslampSet,
// main.js) from COLL[auslamp].surveys (which holds survey LABELS) resolved through SMETA[label].slug. See
// docs: portal internals, state.js.
let AUSLAMP_SET=new Set();
// ausmt_id -> coordinate policy ('generalised' | 'withheld') for NON-EXACT stations, loaded at boot from
// the OPTIONAL coord_policy.json (absent for an all-exact corpus => empty => no badges - graceful
// degrade). See docs: portal internals, state.js.
let COORD_POLICY={};
// The hand-off index: ausmt_id -> {level token: {bytes, url_path}} for stations with a VERIFIED, OPEN route into
// the NCI archive, loaded at phase 2 from the OPTIONAL ts_access.json. See docs: portal internals,
// state.js.
let TSACC=null;

// BBMT stays off the copper action hex (#EF7256), and GDS off the ok/status green (#5BAE6A), so a data-type
// marker cannot be mistaken for the selection accent or a "good" status. See docs: portal internals,
// state.js.
const TYPE_COL={LPMT:"#2E8FA3",BBMT:"#3730B8",AMT:"#CDA1EC",GDS:"#C255A0",other:"#999"};
// The INK a type chip needs, which is not one colour for all four: .chip's default near-black sits at
// 2.03:1 on BBMT's deep indigo (below WCAG AA's 4.5 and visibly muddy), where white reaches 9.22:1. See
// docs: portal internals, state.js.
const TYPE_INK={BBMT:"#fff"};
// country drives the hierarchy, so {country:"New Zealand"} surfaces NZ with zero code change.
const CC={"Australia":"AU","New Zealand":"NZ","Antarctica":"AQ","Indonesia":"ID"};
const TS_COLLECTION={doi:"10.25914/mtjg-jp22",name:"NCI-AuScope Magnetotelluric Collection"};
// The time-series level vocabulary, [token, label, gloss], IN THE ORDER IT RENDERS. These tokens ARE
// ts_access.json's keys, so the chooser, the drawer rows and the hand-off pointer file all name a level the
// same way and none of them re-derives the list. See docs: portal internals, state.js.
const TS_LEVELS=[
  ["raw_packed","Packed raw","as recorded, packed by the custodian"],
  ["level0","Level 0","instrument-recorded, full resolution"],
  ["level1_mth5","Level 1 MTH5","calibrated, resampled, filtered"],
  ["level1_netcdf","Level 1 NetCDF","the same Level 1 product, as NetCDF"],
];
// No AU_PLACES quick-zoom list exists here, and no "Go to place" control exists in index.html or
// filters.js. See docs: portal internals, state.js.
const AUSMT_SELF={au:"AusMT contributors",yr:"2026",ti:"AusMT: curated station metadata, quality and provenance for Australian magnetotelluric transfer functions",ve:(window.AUSMT_CONFIG&&window.AUSMT_CONFIG.version)||"",pb:"AusMT"};
const NCI_CITE={au:"AuScope; NCI Australia",yr:"",ti:"NCI-AuScope Magnetotelluric Collection — packed raw, Level 1 and Level 2 time series",ve:"",pb:"NCI Australia"};

// ---- display grammar: one period, one range and one licence, printed one way ------------------
// These three are JS TWINS of the engine's reference implementations (engine/extract/_pages.py:
// _fmt_period, _range, _cc_human/_fmt_licence). See docs: portal internals, state.js.

// Round `v` to `d` decimals the way Python's format does. See docs: portal internals, state.js.
function _fixedHalfEven(v,d){
  const wide=Math.abs(v).toFixed(Math.min(100,d+20));
  if(new RegExp("\\.\\d{"+d+"}50*$").test(wide)){
    const cut=wide.slice(0,wide.indexOf(".")+(d?d+1:0));                 // truncated toward zero
    const mag=((cut.charCodeAt(cut.length-1)-48)%2===0)?Number(cut):Number(cut)+Math.pow(10,-d);
    return (v<0?-mag:mag).toFixed(d);}
  return v.toFixed(d);}
// A period in seconds as a READER sees it; the stored value never changes. Under 100 it is two
// significant figures with trailing zeros stripped, at or above 100 a thousands-separated integer,
// never an exponent. See docs: portal internals, state.js.
function fmtPeriod(v){
  if(v===null||v===undefined||v==="")return "-";
  const n=Number(v);
  if(!isFinite(n))return "-";
  if(n===0)return "0";
  if(Math.abs(n)>=100)return Number(_fixedHalfEven(n,0)).toLocaleString("en-AU");
  // Two significant figures without ever reaching for an exponent: the decimal place count comes
  // from the magnitude, so 0.005012 rounds at the fourth place and 9.6e-05 at the sixth.
  const out=_fixedHalfEven(n,Math.max(0,1-Math.floor(Math.log10(Math.abs(n)))));
  return out.indexOf(".")>=0?out.replace(/0+$/,"").replace(/\.$/,""):out;}
// The range separator, one place: a numeric range in UI chrome reads as a SPACED
// HYPHEN-MINUS rather than an en dash or the word "to". Curator prose is not chrome and keeps its
// own glyph freedoms.
function fmtRange(lo,hi){return lo+" - "+hi;}
// ---- collection member colours: the same ramp the static collection pages lay ------------------
// A collection is drawn twice, as the static page's scatter and as the SPA's collScatter. See docs:
// portal internals, state.js.
const COLL_PAL=["#2E8FA3","#EF7256","#8A5FC0","#5BAE6A","#3F6FC4","#C255A0","#D9A23B","#A85454"];
// Python's colorsys.hls_to_rgb, mirrored constant for constant: the ramp's hex values have to come out
// byte-identical to the engine's, so this cannot be an approximation of the same idea.
const _HLS_T3=1/3,_HLS_S6=1/6,_HLS_T23=2/3;
function _hlsChannel(m1,m2,hue){
  hue=hue-Math.floor(hue);
  if(hue<_HLS_S6)return m1+(m2-m1)*hue*6;
  if(hue<0.5)return m2;
  if(hue<_HLS_T23)return m1+(m2-m1)*(_HLS_T23-hue)*6;
  return m1;}
function _hlsHex(h,l,s){
  const m2=(l<=0.5)?l*(1+s):l+s-(l*s),m1=2*l-m2;
  return "#"+[_hlsChannel(m1,m2,h+_HLS_T3),_hlsChannel(m1,m2,h),_hlsChannel(m1,m2,h-_HLS_T3)]
    .map(v=>Math.round(v*255).toString(16).toUpperCase().padStart(2,"0")).join("");}
// `n` distinct colours, deterministic in MEMBER ORDER and with no randomness anywhere. See docs: portal
// internals, state.js.
function memberColours(n){
  if(n<=COLL_PAL.length)return COLL_PAL.slice(0,n);
  const out=[];
  for(let i=0;i<n;i++)out.push(_hlsHex(i/n,i%2===0?0.62:0.46,0.58));
  return out;}

// The human form of a Creative Commons identifier, DERIVED from the identifier's own grammar rather than
// from a hand-kept map: the prefix, the clause letters (which keep their internal hyphens: BY-NC-SA), the
// version, and a jurisdiction port where one exists. See docs: portal internals, state.js.
const _CC_ID=/^(CC0|CC)(?:-([A-Z]+(?:-[A-Z]+)*))?-(\d+\.\d+)(?:-([A-Z]{2,3}))?$/;
// Read at CALL time, not load time, and memoised only once the table is actually there: state.js is
// loaded on its own by more than one harness, and a module-level read of contract.js's LICENSES turns
// that into a ReferenceError at boot.
let _licKnown=null;
function _licKnownIds(){
  if(_licKnown&&_licKnown.length)return _licKnown;
  const L=(typeof LICENSES!=="undefined"&&LICENSES)||{};
  _licKnown=(L.redistributable||[]).concat(L.recognised_only||[]);
  return _licKnown;}
function licHuman(lic){
  const v=String(lic==null?"":lic).trim();
  if(_licKnownIds().indexOf(v)<0)return v;
  const m=_CC_ID.exec(v);
  return m?m.slice(1).filter(Boolean).join(" "):v;}

function clamp(x){return Math.max(0,Math.min(1,x));}
function lerp(a,b,t){const pa=[1,3,5].map(i=>parseInt(a.substr(i,2),16)),pb=[1,3,5].map(i=>parseInt(b.substr(i,2),16));
  return "#"+pa.map((v,k)=>Math.round(v+(pb[k]-v)*t).toString(16).padStart(2,"0")).join("");}
// The completeness ramp is a CVD-safe SEQUENTIAL dark→light progression (viridis principle)
// - dark slate-blue #2A3B66 → olive #6E7F46 → pale warm yellow #F2E27E - because a red-green pair
// is not distinguishable under a deuteranopia simulation (dE76 about 9.6). See docs: portal internals, state.js.
function qColor(q){if(q==null)return "#5A6E7D";const t=clamp((q-2)/3);return t<.5?lerp("#2A3B66","#6E7F46",t*2):lerp("#6E7F46","#F2E27E",(t-.5)*2);}
