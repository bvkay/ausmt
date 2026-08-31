"use strict";
// Shared mutable state (assigned during boot) + constants + small colour/format utils.
// No survey metadata is hard-coded here; SMETA is loaded from data/surveys.json at boot.
let CAT,TFD,SCI,SMETA,PROV,COLL,MANIFEST,BUILDID; /*__DATA_BINDING__*/
// ---- two-phase boot: background hydration gates ------------------------------------------------
// The boot paints from the SMALL products (catalogue + surveys, plus the four small optionals). The heavy
// ones (tf.json ~3.2MB raw, sci.json and the download manifest) stream in AFTERWARDS, so between first
// paint and their arrival TFD/SCI/MANIFEST are simply NOT LOADED YET. That is a THIRD state, distinct both
// from "loaded and empty" and from "this deployment does not serve it", and the honesty rule of this
// codebase forbids collapsing it into either: no consumer may render "not recorded" / "not currently
// available" / "not evaluated" / "none currently served" for a product that is merely still in flight.
//   HYDR[k] === "ready"   -> assigned; render exactly as before
//   HYDR[k] === "pending" -> in flight; render an unobtrusive LOADING state, NEVER absence
//   HYDR[k] === "failed"  -> the fetch resolved not-ok / unparseable; say THAT, never dress it as absence
// TF_READY / SCI_READY / MANIFEST_READY are the awaitable gates for consumers that cannot degrade (the
// exports read TFD/SCI; the bulk EDI zip reads the manifest). The defaults are the SETTLED values so every
// harness that assigns TFD/SCI/MANIFEST directly (the coord-access and bundle-tile drivers do) behaves
// byte-for-byte as it did before phasing: only a boot that actually starts phase 2 flips them to pending.
let TF_READY=Promise.resolve(),SCI_READY=Promise.resolve(),MANIFEST_READY=Promise.resolve();
// THREDDS D6: ts_access.json rides phase 2 as well. The chooser it feeds is a facet most visitors
// never open, so a phase-1 fetch would add a blocking boot request for it; the Availability controls
// are disabled and aria-busy across the window instead, exactly as the colour modes are.
let TSACC_READY=Promise.resolve();
const HYDR={tf:"ready",sci:"ready",manifest:"ready",tsaccess:"ready"};
function hydrating(k){return HYDR[k]==="pending";}
function hydrFailed(k){return HYDR[k]==="failed";}
// A product is USABLE only when it is loaded. "pending" and "failed" are two different REASONS for one
// fact: the values are not here. A surface that can name the reason (the drawer, which renders a loading
// line or a could-not-load line) distinguishes them; a surface that cannot (a filter predicate, a marker
// fill, a property written into an exported file) must gate on THIS, because a failed sci.json leaves s.q
// undefined for every station exactly as a pending one does. Gating those on hydrating() alone would resume
// claiming "fails the threshold" / "not evaluated" / "remote_ref: false" the instant the fetch errored,
// which is the same dishonesty one state later. Phase 2 made a tf/sci failure survivable (before the split
// it was fatal and the portal blanked), so this state is reachable and has to be answered here.
function hydrUsable(k){return HYDR[k]==="ready";}
// The two positional rows consumers deref by station index. Both tolerate a NOT-YET-ASSIGNED global
// (phase 1 renders before tf/sci land), so a pre-hydration read yields the same empty row an absent product
// yields; the DISPLAY difference is carried by hydrating()/hydrFailed(), never by the data itself.
function sciRow(i){return (SCI&&SCI[i])||[];}
function tfRow(i){return (TFD&&TFD[i])||null;}
let ST=[],surveys=[],visible=[],selected=new Set(),curView="map",qMin=0;
// Lane B: the period-window predicate is HEADLESS (the slider control is retired; passesCore reads
// these bounds, harnesses set them). Full-range defaults = the filter is off.
let periodLo=0.001,periodHi=100000;
let SLUG_TO_SURVEY={};   // slug -> survey label, built in buildState(); backs the #/survey/<slug> route
// UX4 (D1/D2): the set of survey SLUGS that belong to the `auslamp` collection, built once at boot
// (buildAuslampSet, main.js) from COLL[auslamp].surveys (which holds survey LABELS) resolved through
// SMETA[label].slug. Empty when collections.json is absent or has no auslamp collection, in which case
// isAuslampSurvey() returns false for everything. NO MAP PATH READS IT since the 2026-08-24 dots-only
// ruling: its one consumer was the badge rule's never-collapse privilege, and nothing collapses now. Kept
// because it is collection membership rather than map furniture; retiring it is an owner call (see map.js).
let AUSLAMP_SET=new Set();
// C42 Amendment A1: ausmt_id -> coordinate policy ('generalised' | 'withheld') for NON-EXACT stations,
// loaded at boot from the OPTIONAL coord_policy.json (absent for an all-exact corpus => empty => no
// badges — graceful degrade, same tolerant-of-absence pattern as collections/manifest). buildState()
// folds it onto each station as s.coordPolicy; the drawer badges from that. It carries POLICY, never a
// coordinate — positions are already masked in the catalogue (generalised => 0.1° cell, withheld => null).
let COORD_POLICY={};
// THREDDS A5: ausmt_id -> {level token: {bytes, url_path}} for stations with a VERIFIED, OPEN route
// into the NCI archive, loaded at phase 2 from the OPTIONAL ts_access.json. `null` means the fetch
// has not settled; `{}` means it settled on absence, which is the honest answer for a deployment
// that publishes no download index (a corpus with no verified routes ships no file). Membership is
// the access rule: a withheld or coordinate-gated station is simply not in it.
let TSACC=null;

// UX6 Wave B (B2 colour de-collision): BBMT moved off the copper action hex (#EF7256), and GDS off the
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
// LP/BB SEPARABILITY (owner, 2026-08-19, on the deployed map): "Long Period and Broadband icon colours are
// too similar". UX8's pair was ΔE00 26.1 on paper and still unreadable at site-dot size, because it
// separated almost entirely by HUE (teal 222° vs indigo 299°) across only 9 L* - and small marks are
// discriminated by VALUE, not hue. BBMT #5E5ED6 -> #3730B8: deeper and more saturated, which buys a 24.6 L*
// gap and a 55.7 C* gap and lifts the pair to ΔE00 34.2. LPMT is deliberately UNCHANGED - the teal is the
// established fabric colour across this portal and the owner's atlases, so the other one moves.
// The number that actually mattered is the DEUTAN one: simulated deuteranopia collapsed the old pair to
// ΔE00 15.3 (protan 19.2); the new pair holds 25.3 / 30.1. That is the point of separating by lightness
// and along the blue-yellow axis rather than by hue - a red-green deficient reader loses the hue argument
// entirely, so a pair that leans on it is a pair that vanishes for them. The new BB also moves AWAY from
// the AMT light violet (ΔE00 27.2 -> 44.0), so "deeper blue" did not buy LP/BB at AMT's expense.
// All of it is recomputed and gated in tests/test_type_palette_separability.py; the floors are stated
// there, not here, so a future edit cannot re-converge the pair by editing a comment.
const TYPE_COL={LPMT:"#2E8FA3",BBMT:"#3730B8",AMT:"#CDA1EC",GDS:"#C255A0",other:"#999"};
// The INK a type chip needs, which is not one colour for all four: .chip's default near-black sits at
// 2.03:1 on BBMT's deep indigo (below WCAG AA's 4.5 and visibly muddy), where white reaches 9.22:1.
// The other three are the other way round - white on AMT's light violet is 2.12:1 against 8.85:1 for
// the default - so this is a per-type override, never a blanket flip. Measured, not judged by eye.
const TYPE_INK={BBMT:"#fff"};
// country drives the hierarchy, so {country:"New Zealand"} surfaces NZ with zero code change.
const CC={"Australia":"AU","New Zealand":"NZ","Antarctica":"AQ","Indonesia":"ID"};
const TS_COLLECTION={doi:"10.25914/mtjg-jp22",name:"NCI-AuScope Magnetotelluric Collection"};
// THREDDS D8: the time-series level vocabulary, [token, label, gloss], IN THE ORDER IT RENDERS.
// These tokens ARE ts_access.json's keys, so the chooser, the drawer rows and the hand-off pointer
// file all name a level the same way and none of them re-derives the list. `level2` is absent BY
// RULING, not by omission (D19, 2026-08-24): the archive's level_2 tree holds transfer functions,
// not time series, so it opens no route, takes no button and gets no row here.
const TS_LEVELS=[
  ["raw_packed","Packed raw","as recorded, packed by the custodian"],
  ["level0","Level 0","instrument-recorded, full resolution"],
  ["level1_mth5","Level 1 MTH5","calibrated, resampled, filtered"],
  ["level1_netcdf","Level 1 NetCDF","the same Level 1 product, as NetCDF"],
];
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

// ---- display grammar: one period, one range and one licence, printed one way ------------------
// These three are JS TWINS of the engine's reference implementations (engine/extract/_pages.py:
// _fmt_period, _range, _cc_human/_fmt_licence). A reader meets the same values on a static entity
// page and in the workspace, so the two surfaces owe each other the same output; the parity is held
// by tests/display_grammar.test.js against the worked examples the engine suite pins the Python leaf
// against. Change one side and the other must move with it.

// Round `v` to `d` decimals the way Python's format() does. The reason this is not a bare toFixed:
// the two runtimes break an EXACT .5 tie differently - Python to the even neighbour, JS away from
// zero - so a 1.25 s period read "1.3" in the workspace and "1.2" on the survey page. A tie is
// exactly a decimal expansion that terminates in a 5 one place past the target, which is detectable
// on the expansion itself; every other value toFixed already rounds correctly.
function _fixedHalfEven(v,d){
  const wide=Math.abs(v).toFixed(Math.min(100,d+20));
  if(new RegExp("\\.\\d{"+d+"}50*$").test(wide)){
    const cut=wide.slice(0,wide.indexOf(".")+(d?d+1:0));                 // truncated toward zero
    const mag=((cut.charCodeAt(cut.length-1)-48)%2===0)?Number(cut):Number(cut)+Math.pow(10,-d);
    return (v<0?-mag:mag).toFixed(d);}
  return v.toFixed(d);}
// A period in seconds as a READER sees it; the stored value never changes. Under 100: two
// significant figures, trailing zeros stripped. At or above 100: a thousands-separated integer.
// Never exponent notation, whatever the magnitude - "9.6e-05 s" is a number a processing log can
// carry and a survey card cannot. The unit belongs to the caller's slot, not to this string.
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
// The range separator, one place. Owner ruling R2: a numeric range in UI chrome reads as a SPACED
// HYPHEN-MINUS rather than an en dash or the word "to". Curator prose is not chrome and keeps its
// own glyph freedoms.
function fmtRange(lo,hi){return lo+" - "+hi;}
// The human form of a Creative Commons identifier, DERIVED from the identifier's own grammar so the
// display cannot fall behind the allow-list: the prefix, the clause letters (which keep their
// internal hyphens: BY-NC-SA), the version, and a jurisdiction port where one exists. A hand-kept
// map covering only today's corpus goes wrong silently - the first third-party release under a 3.0,
// -AU, NC or ND id would print "CC-BY-3.0-AU" on one card beside "CC BY 4.0" on the next.
// Non-CC ids (PUBLIC DOMAIN, ODBL-1.0, ALL RIGHTS RESERVED...) and unrecognised ids have no such
// published reader's form and are printed verbatim, because guessing one would be inventing metadata.
// The SPDX identifier itself stays untouched in exports, data slots and citation output.
const _CC_ID=/^(CC0|CC)(?:-([A-Z]+(?:-[A-Z]+)*))?-(\d+\.\d+)(?:-([A-Z]{2,3}))?$/;
function licHuman(lic){
  const v=String(lic==null?"":lic).trim();
  const m=_CC_ID.exec(v);
  return m?m.slice(1).filter(Boolean).join(" "):v;}

function clamp(x){return Math.max(0,Math.min(1,x));}
function lerp(a,b,t){const pa=[1,3,5].map(i=>parseInt(a.substr(i,2),16)),pb=[1,3,5].map(i=>parseInt(b.substr(i,2),16));
  return "#"+pa.map((v,k)=>Math.round(v+(pb[k]-v)*t).toString(16).padStart(2,"0")).join("");}
// UX8 CVD amendment (supersedes the W3b red→amber→green re-shade): the completeness ramp is a CVD-safe
// SEQUENTIAL dark→light progression (viridis principle) — dark slate-blue #2A3B66 → olive #6E7F46 → pale
// warm yellow #F2E27E — because the old red→green endpoints measured dE76≈9.6 under a deuteranopia
// simulation (indistinguishable for red-green CVD readers). LIGHTNESS carries the signal (relative
// luminance rises monotonically 0.046 → 0.75 along the lerp path), so the ramp survives all three
// dichromacies: simulated low↔high separation deutan 106.8 / protan 103.1 / tritan 69.1 dE76. The olive
// mid keeps the ramp off the lpmt teal and the ok green (every stop ≥17 dE00 from the data-type and
// status colours), and the null/"not evaluated" grey #5A6E7D stays clearly apart from the dark low end
// (dE00 20, L* 45 vs 26). The dark low end is marker-fill/dot material — drawer text no longer takes
// qColor as a text colour (it renders a .qvdot swatch beside plain readable text instead).
function qColor(q){if(q==null)return "#5A6E7D";const t=clamp((q-2)/3);return t<.5?lerp("#2A3B66","#6E7F46",t*2):lerp("#6E7F46","#F2E27E",(t-.5)*2);}
