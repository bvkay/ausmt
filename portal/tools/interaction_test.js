// jsdom-backed INTERACTION test for the portal sidebar + routing.
//
// smoke.js stubs the DOM so querySelectorAll() returns [] -> buildTree() never makes a checkbox and the
// whole interaction layer (tree toggles, Find, #/collection routing) ships untested. That is exactly how
// the value-less-checkbox toggle no-op shipped. This test instead loads the REAL index.html into a jsdom
// DOM, runs the actual src modules in the window's VM context (mirroring the in-order <script> tags), boots
// against a fixture data dir, then DRIVES the UI and asserts the OBSERVABLE result: the filtered station
// set, the visible view, the Find dropdown. It is the regression guard for the hostile-audit must-fix UI
// bugs (country/org toggle, collection route + Back, Find blanking the map).
//
//   node tools/interaction_test.js <dataDir>
//
// Requires jsdom (a dev-only dependency; see package.json — the shipped portal has none). Exit codes:
//   0 = passed   1 = a real interaction failure   2 = jsdom missing (caller should SKIP, not fail)
const fs = require("fs"), path = require("path"), vm = require("vm");
let JSDOM;
try { ({ JSDOM } = require("jsdom")); }
catch (e) { console.error("SKIP: jsdom not installed (run `npm ci` in portal/)"); process.exit(2); }

const TOOLS = __dirname;
const PORTAL = path.resolve(TOOLS, "..");
const SRC = path.join(PORTAL, "src");
const DATA = path.resolve(process.argv[2] || path.join(PORTAL, "data"));

// fixture data served to the app's fetch() (same file set as smoke.js)
const FILES = ["catalogue", "tf", "sci", "surveys", "build_provenance", "collections", "build"];
const DATAMAP = {};
FILES.forEach(k => { try { DATAMAP["data/" + k + ".json"] = JSON.parse(fs.readFileSync(path.join(DATA, k + ".json"))); } catch (e) {} });

// This test is FIXTURE-driven: it asserts against a known 4-station fixture that the pytest wrapper
// (tests/test_interactions.py) builds and passes as argv[2]. The shipped portal/data is empty BY DESIGN
// (demo data is never committed), so a bare `npm run test:interactions` against it has nothing to drive.
// Skip cleanly (exit 0) and point at the real harness rather than reporting a false interaction failure.
const _cat = DATAMAP["data/catalogue.json"];
if (!Array.isArray(_cat) || _cat.length === 0) {
  console.log("SKIP: no stations in " + DATA + " (portal/data ships empty by design). Run the interaction " +
    "test via `pytest -q tests` — tests/test_interactions.py builds a 4-station fixture and passes its path. " +
    "The bare `npm run test:interactions` against empty data drives nothing.");
  process.exit(0);
}

// Leaflet/JSZip stub (the map layer is irrelevant here; the DOM itself is real jsdom).
// mapCalls records every setView()/fitBounds() call the app makes on the `map` object (map.js's
// `L.map(...)` returns this same stub) — general instrumentation for any test that needs to assert
// on map navigation calls actually made, with real arguments, not just "something happened".
const mapCalls = [];
const stub = () => new Proxy(function () {}, {
  get: (t, p) => {
    if (p === "then") return undefined;
    if (p === Symbol.iterator) return function* () {};
    if (p === "setView" || p === "fitBounds") return (...args) => { mapCalls.push({ fn: p, args }); return stub(); };
    return stub();
  },
  apply: () => stub(), construct: () => stub(),
});

// Boot the real page DOM in jsdom with NO page scripts (we run the modules ourselves, in order).
const html = fs.readFileSync(path.join(PORTAL, "index.html"), "utf8");
const dom = new JSDOM(html, { url: "http://localhost/", runScripts: "outside-only", pretendToBeVisual: true });
const win = dom.window;
win.L = stub(); win.JSZip = stub();
// version/schema pinned so version.js produces a DETERMINISTIC ver-chip label the footer-chip assertion
// (item 3) can pin exactly, instead of matching a moving default.
win.AUSMT_CONFIG = { short_name: "AusMT", version: "1.2.3", schema: "MTCAT", schema_version: "1.0" };
win.fetch = url => Promise.resolve(DATAMAP[url] ? { ok: true, json: () => Promise.resolve(DATAMAP[url]) } : { ok: false });

// Concatenate the modules + an api hook; run in the window's global scope so the top-level declarations
// become window globals (same effect as index.html's ordered <script> tags).
const MODULES = ["contract", "security", "state", "data", "plots", "map", "filters", "drawer", "exports", "main", "tour"];
let code = MODULES.map(f => fs.readFileSync(path.join(SRC, f + ".js"), "utf8")).join("\n");
code += "\nwindow.__api={boot,setView,routeFromHash,refresh,openStation,renderFind," +
  "curView:()=>curView,nST:()=>ST.length,visIds:()=>visible.map(s=>s.id)," +
  "visSurveys:()=>[...new Set(visible.map(s=>s.survey))]," +
  // intro-panel + tour hooks (S2 UX-A) — exposed so the driver can assert on internal helpers
  // (e.g. re-reading localStorage) as well as on the rendered DOM.
  "introSeen,tourStep:()=>_tourStep," +
  // S3 hooks: recentlyAdded() for the strip-content assertion; renderRecentlyAdded so the driver
  // can force a re-render after directly poking SMETA (not needed in the current fixture path, but
  // keeps parity with runInit()'s own call sites).
  "recentlyAdded,renderRecentlyAdded," +
  // UX4 (D1-A1/D2/D4): the PURE map helpers, exposed so the AusLAMP partition / colour / tooltip /
  // zoom-scaling are unit-testable without Leaflet (jsdom can't load it). partitionMarkers(list) ->
  // {unclustered, clustered} splits on AusLAMP membership; isAuslampSurvey(slug,set) is the predicate;
  // radiusForZoom/weightForZoom are the D4 step functions; markerColor(s) is membership-blind post-A1;
  // tooltipText(s) carries the A1 type-label swap (member shows "AusLAMP" instead of LPMT). The
  // AUSLAMP_SET getter/setter + buildAuslampSet let the driver exercise both the boot-built set and
  // explicit sets; setColorMode drives the colour-mode assertions. The ST-poke + selectSurvey/selCount
  // hooks verify draw/select flows still COUNT a re-classified station (which may move map containers) —
  // the counting logic reads `visible`/ST, not layer membership, so it stays membership-agnostic.
  "partitionMarkers,isAuslampSurvey,radiusForZoom,weightForZoom,markerColor,tooltipText,buildAuslampSet," +
  "auslampSet:()=>AUSLAMP_SET,setAuslampSet:(arr)=>{AUSLAMP_SET=new Set(arr);}," +
  "setColorMode:(m)=>{colorMode=m;},selectSurvey,renderCards,openSurvey," +
  // UX4 D5 hook: the tree-demo step's resolved survey label (kalkaroo-2022 preferred, first-survey
  // degrade) — a REAL observable for the graceful-degrade assertion, not just "didn't crash".
  "tourTreeTarget:()=>_tourTreeTarget," +
  // UX5 (D7/D8) hooks: the disclosure-caret API (same functions the carets and the tour step call)
  // plus a collapse-set reader, so the invariant and the tour-restore assertions observe real state.
  "treeSetCollapsed,treeIsCollapsed,treeCollapsedKeys:()=>[..._treeCollapsed]," +
  "setType:(id,ty)=>{const s=ST.find(x=>x.id===id);if(s)s.type=ty;}," +
  "setSlug:(id,sl)=>{const s=ST.find(x=>x.id===id);if(s)s.slug=sl;}," +
  // UX3 item 6/7 hooks: poke a survey's blurb (abstract) and read the rendered surveyCard/surveySummary
  // HTML so the driver can assert the card description + XSS-inertness + fallback, and the removal of the
  // dimensionality displays (while skew/strike stay). cardDesc exposed for a direct pure-function check.
  "cardDesc,setBlurb:(sv,b)=>{SMETA[sv]=SMETA[sv]||{};if(b===null)delete SMETA[sv].blurb;else SMETA[sv].blurb=b;}," +
  "cardHtml:(sv)=>surveyCard(sv),summaryHtml:(sv)=>surveySummary(ST.filter(s=>s.survey===sv),SMETA[sv]||{})," +
  // C22 citation-honesty hooks: the citation ASSEMBLY helpers (drawer.js apa/bibtex/ris + exports.js
  // citeLine) and the constants the #dlCite pack feeds them — exposed so section T can assert on the
  // exact strings the pack is built from. citeLine is a LAZY arrow (not a bare reference) so a boot on
  // pre-C22 code still reaches section T and fails THERE with a precise message, instead of dying at
  // this api hook with an unrelated-looking ReferenceError.
  "apa,bibtex,ris,AUSMT_SELF,NCI_CITE,TS_COLLECTION,citeLine:(c,d)=>citeLine(c,d),smeta:(sv)=>SMETA[sv]," +
  "selCount:()=>selected.size,nVisCount:()=>visible.length};";

const doc = win.document;
const fire = (el, type) => el.dispatchEvent(new win.Event(type, { bubbles: true }));
function die(msg) { console.error("INTERACTION FAILED: " + msg); process.exit(1); }
function ok(cond, msg) { if (!cond) die(msg); }

// Boots a SEPARATE fresh jsdom window against the given data map (used for the empty-state intro-panel
// check below — reusing the already-booted populated `win` would double-init the app). Mirrors the setup
// above exactly (same module list/order, same stubs) so it is a faithful re-run of index.html's boot.
async function bootFreshWindow(dataMap) {
  const d = new JSDOM(html, { url: "http://localhost/", runScripts: "outside-only", pretendToBeVisual: true });
  const w = d.window;
  w.L = stub(); w.JSZip = stub();
  w.AUSMT_CONFIG = { short_name: "AusMT" };
  w.fetch = url => Promise.resolve(dataMap[url] ? { ok: true, json: () => Promise.resolve(dataMap[url]) } : { ok: false });
  await new Promise(res => (w.document.readyState === "complete" ? res() : w.addEventListener("load", res, { once: true })));
  vm.runInContext(code, d.getInternalVMContext());
  await w.__api.boot();
  return w;
}

(async () => {
  // Let jsdom finish its document lifecycle BEFORE we run the modules, so main.js's DOMContentLoaded
  // auto-boot can't double-fire alongside our explicit boot() (a second boot re-runs buildTree and
  // appends a duplicate tree). After 'load', the listener main.js registers is too late to fire.
  await new Promise(res => (win.document.readyState === "complete" ? res() : win.addEventListener("load", res, { once: true })));
  vm.runInContext(code, dom.getInternalVMContext());
  const A = win.__api;
  await A.boot();
  ok(A.nST() === 5, "fixture should load 5 stations, got " + A.nST());

  // VER CHIP -> FOOTER (UX feedback round 3, item 3): the version chip moved out of the header into the
  // footer. version.js is a standalone page script (not in MODULES), so run it here against the real DOM
  // exactly as index.html's <script src="version.js"> would, then assert:
  //   (a) the ONLY [data-ver-chip] lives inside <footer> (none left in <header>);
  //   (b) it is POPULATED with the config-derived label (not left empty).
  vm.runInContext(fs.readFileSync(path.join(PORTAL, "version.js"), "utf8"), dom.getInternalVMContext());
  const headerChips = [...doc.querySelectorAll("header [data-ver-chip]")];
  const footerChips = [...doc.querySelectorAll("footer [data-ver-chip]")];
  ok(headerChips.length === 0, "the version chip must NOT remain in the header (item 3), found " + headerChips.length);
  ok(footerChips.length === 1, "expected exactly one version chip in the footer, found " + footerChips.length);
  ok(footerChips[0].textContent === "AusMT v1.2.3 · MTCAT 1.0",
    "footer version chip was not populated by version.js, got: " + JSON.stringify(footerChips[0].textContent));

  // UX4 (D1/D2) AUSLAMP PARTITION + MEMBERSHIP. partitionMarkers() is the PURE split behind the two map
  // containers — AusLAMP-COLLECTION members into the never-clustered plain layer, everything else (incl.
  // legacy non-AusLAMP LPMT) into the markerClusterGroup. Tested on synthetic stations (no Leaflet; jsdom
  // can't load it) so it doesn't perturb the shared fixture counts.
  //
  //   AUSLAMP_SET is built at boot from COLL.auslamp.surveys (survey LABELS) resolved through
  //   SMETA[label].slug. The fixture's auslamp collection lists ["Alpha Survey","Beta Survey"] whose slugs
  //   are "alpha"/"beta", so the boot-built set MUST be exactly {alpha, beta} — proving the label->slug
  //   resolution (the collections.json member list is labels, the predicate keys off slug).
  const _bootSet = [...A.auslampSet()].sort();
  ok(_bootSet.length === 2 && _bootSet[0] === "alpha" && _bootSet[1] === "beta",
    "buildAuslampSet must resolve COLL.auslamp.surveys (labels) to SMETA slugs {alpha,beta}, got: " + JSON.stringify(_bootSet));
  // isAuslampSurvey(slug, set): membership true/false/absent-set cases.
  ok(A.isAuslampSurvey("alpha", A.auslampSet()) === true, "isAuslampSurvey must be true for a member slug");
  ok(A.isAuslampSurvey("gamma", A.auslampSet()) === false, "isAuslampSurvey must be false for a non-member slug");
  ok(A.isAuslampSurvey("alpha", new Set()) === false, "isAuslampSurvey must be false against an empty set (absent collection)");
  ok(A.isAuslampSurvey(null, A.auslampSet()) === false, "isAuslampSurvey must be false for a null slug");
  // partitionMarkers with an EXPLICIT set {as1}: only the member (any type) goes unclustered; a NON-member
  // LPMT now CLUSTERS — the UX4 behaviour that FAILS on pre-UX4 code (which un-clustered every LPMT type).
  const _sampleStations = [
    { i: 0, type: "LPMT", slug: "as1", marker: "m0" },  // AusLAMP member  -> unclustered
    { i: 1, type: "LPMT", slug: "legacy-lp", marker: "m1" }, // legacy non-AusLAMP LPMT -> CLUSTERED (new)
    { i: 2, type: "BBMT", slug: "bb", marker: "m2" },   // -> clustered
    { i: 3, type: "GDS", slug: "gds", marker: "m3" },   // -> clustered (GDS deliberately clusters)
    { i: 4, type: "AMT", slug: "am", marker: "m4" },    // -> clustered
    { i: 5, type: "LPMT", slug: "as1b", marker: "m5" }, // second AusLAMP member -> unclustered
  ];
  const _explicit = new Set(["as1", "as1b"]);
  A.setAuslampSet([..._explicit]);
  const _part = A.partitionMarkers(_sampleStations);
  ok(_part.unclustered.length === 2 && _part.unclustered.every(s => _explicit.has(s.slug)),
    "partitionMarkers must route ONLY AusLAMP-member stations to the unclustered layer, got slugs: " +
    JSON.stringify(_part.unclustered.map(s => s.slug)));
  ok(_part.clustered.length === 4 && _part.clustered.every(s => !_explicit.has(s.slug)),
    "partitionMarkers must cluster every non-member — INCLUDING legacy non-AusLAMP LPMT (the UX4 change), got slugs: " +
    JSON.stringify(_part.clustered.map(s => s.slug)));
  // The load-bearing new-only assertion: a NON-member LPMT is in the CLUSTERED bucket (pre-UX4 it was unclustered).
  ok(_part.clustered.some(s => s.slug === "legacy-lp" && s.type === "LPMT"),
    "a legacy (non-AusLAMP) LPMT station must now CLUSTER — this is the UX4 D2 behaviour that fails on base");
  // Empty AUSLAMP_SET => graceful degrade: EVERYTHING clusters (nothing is AusLAMP).
  A.setAuslampSet([]);
  const _degrade = A.partitionMarkers(_sampleStations);
  ok(_degrade.unclustered.length === 0 && _degrade.clustered.length === _sampleStations.length,
    "empty AUSLAMP_SET must degrade to all-clustered, got unclustered=" + _degrade.unclustered.length);
  // No station dropped or duplicated across the two containers.
  ok(_part.unclustered.length + _part.clustered.length === _sampleStations.length,
    "partitionMarkers dropped or duplicated a station across the two containers");
  A.buildAuslampSet();   // restore the boot-built set for the rest of the run

  // UX4 (D4) ZOOM-SCALED RADII. radiusForZoom/weightForZoom are pure step functions: pinned values +
  // monotone non-decreasing in z. If either drifts from the frozen table this fails.
  ok(A.radiusForZoom(3) === 2.5 && A.radiusForZoom(4) === 2.5, "radiusForZoom(z<=4) must be 2.5");   // O5: every tier one step smaller
  ok(A.radiusForZoom(5) === 3.5, "radiusForZoom(5) must be 3.5");
  ok(A.radiusForZoom(6) === 4.5, "radiusForZoom(6) must be 4.5");
  ok(A.radiusForZoom(7) === 5 && A.radiusForZoom(12) === 5, "radiusForZoom(z>=7) must be 5");
  ok(A.weightForZoom(4) === 1.0 && A.weightForZoom(0) === 1.0, "weightForZoom(z<=4) must be 1.0");
  ok(A.weightForZoom(5) === 1.5 && A.weightForZoom(9) === 1.5, "weightForZoom(z>=5) must be 1.5");
  for (let z = 0; z < 12; z++) {
    ok(A.radiusForZoom(z + 1) >= A.radiusForZoom(z), "radiusForZoom must be monotone non-decreasing at z=" + z);
    ok(A.weightForZoom(z + 1) >= A.weightForZoom(z), "weightForZoom must be monotone non-decreasing at z=" + z);
  }

  // UX4 Amendment A1 COLOUR (still live) + O4 TOOLTIP (2026-07-12). Colour: EVERY colour mode is
  // membership-blind — type mode gives member and non-member LPMT the IDENTICAL flagship teal. Tooltip:
  // O4 slimmed it to station name + survey name ONLY, so the AusLAMP/legacy distinction is NO LONGER on
  // the tooltip — it survives only in the D2 clustering split. Two synthetic LPMT stations differing ONLY
  // by membership (each given a survey so the O4 tooltip has a survey name).
  A.setAuslampSet(["memb"]);
  const _memberLp = { id: "S1", type: "LPMT", slug: "memb", q: 4.2, dim: "2-D", survey: "Alpha Survey" };
  const _otherLp = { id: "S2", type: "LPMT", slug: "notmemb", q: 4.2, dim: "2-D", survey: "Beta Survey" };
  A.setColorMode("type");
  ok(A.markerColor(_memberLp) === A.markerColor(_otherLp),
    "A1: TYPE-mode colour must be IDENTICAL for AusLAMP vs non-AusLAMP LPMT (no colour split), got: " + A.markerColor(_memberLp) + " / " + A.markerColor(_otherLp));
  ok(A.markerColor(_memberLp) === "#2E8FA3", "A1: all LPMT must render the flagship teal #2E8FA3, got " + A.markerColor(_memberLp));
  A.setColorMode("quality");
  ok(A.markerColor(_memberLp) === A.markerColor(_otherLp),
    "QUALITY-mode colour must be IDENTICAL regardless of AusLAMP membership, got: " + A.markerColor(_memberLp) + " / " + A.markerColor(_otherLp));
  A.setColorMode("dim");
  ok(A.markerColor(_memberLp) === A.markerColor(_otherLp),
    "DIM-mode colour must be IDENTICAL regardless of AusLAMP membership, got: " + A.markerColor(_memberLp) + " / " + A.markerColor(_otherLp));
  A.setColorMode("type");
  // O4 (owner, 2026-07-12): the hover tooltip is station name + survey name ONLY — no diagnostic Q, no
  // type/AusLAMP label. Pre-O4 it swapped the type label to "AusLAMP" for members; that distinction now
  // lives only in the D2 clustering split. Asserting the diagnostic + type/AusLAMP label are GONE is what
  // fails on pre-O4 code (which carried "· Q 4.2" and the AusLAMP/LPMT label).
  const _tMemb = A.tooltipText(_memberLp), _tOther = A.tooltipText(_otherLp);
  ok(_tMemb === "S1 · Alpha Survey", "O4: member tooltip must be 'station · survey' only, got: " + JSON.stringify(_tMemb));
  ok(_tOther === "S2 · Beta Survey", "O4: non-member tooltip must be 'station · survey' only, got: " + JSON.stringify(_tOther));
  ok(_tMemb.indexOf("Q ") < 0 && _tMemb.indexOf("4.2") < 0, "O4: the TF diagnostic (Q) must be gone from the hover tooltip, got: " + JSON.stringify(_tMemb));
  ok(_tMemb.indexOf("AusLAMP") < 0 && _tMemb.indexOf("LPMT") < 0, "O4: the type/AusLAMP label must be gone from the hover tooltip, got: " + JSON.stringify(_tMemb));
  A.buildAuslampSet();   // restore the boot-built set for the rest of the run

  // A. buildTree made REAL checkboxes (the smoke stub never did): 2 countries, 4 orgs, 4 surveys.
  //    (C1b added Delta Survey / OrgW / station D1 — an embargoed survey, still fully discoverable.)
  const countryBoxes = [...doc.querySelectorAll("#tree input[data-country]")].filter(b => !b.hasAttribute("value"));
  const orgBoxes = [...doc.querySelectorAll("#tree input[data-org]")].filter(b => !b.hasAttribute("value"));
  const surveyBoxes = [...doc.querySelectorAll("#tree input[value]")];
  ok(countryBoxes.length === 2, "expected 2 country checkboxes, got " + countryBoxes.length);
  ok(orgBoxes.length === 4, "expected 4 org checkboxes, got " + orgBoxes.length);
  ok(surveyBoxes.length === 4, "expected 4 survey checkboxes, got " + surveyBoxes.length);
  ok(A.visIds().length === 5, "all 5 stations visible at baseline, got " + A.visIds().length);

  // B. COUNTRY toggle: unchecking New Zealand must sync its survey box AND drop its station.
  //    (The value-less-checkbox bug left the listener unbound, so this did nothing.)
  const nz = countryBoxes.find(b => b.getAttribute("data-country") === "New Zealand");
  ok(nz, "no New Zealand country checkbox");
  nz.checked = false; fire(nz, "change");
  ok(surveyBoxes.find(b => b.value === "Gamma Survey").checked === false, "country toggle did NOT sync its survey checkbox");
  ok(!A.visIds().includes("G1"), "country toggle did NOT filter out its station");
  ok(A.visIds().length === 4, "expected 4 visible after hiding New Zealand, got " + A.visIds().length);
  nz.checked = true; fire(nz, "change");
  ok(A.visIds().length === 5, "re-checking the country did not restore its station");

  // C. ORG toggle: unchecking Australia||OrgX must sync Alpha Survey AND drop its 2 stations, leaving the
  //    sibling org (OrgY/Beta) untouched.
  const orgx = orgBoxes.find(b => b.getAttribute("data-org") === "Australia||OrgX");
  ok(orgx, "no Australia||OrgX org checkbox");
  orgx.checked = false; fire(orgx, "change");
  ok(surveyBoxes.find(b => b.value === "Alpha Survey").checked === false, "org toggle did NOT sync its survey checkbox");
  ok(!A.visIds().includes("A1") && !A.visIds().includes("A2"), "org toggle did NOT filter out its stations");
  ok(A.visSurveys().includes("Beta Survey"), "org toggle wrongly hid a sibling org's survey");
  orgx.checked = true; fire(orgx, "change");

  // C2. UX5 (D6) COLLECTIONS TOGGLE GROUP — first, cross-cutting, push-only.
  const treeEl = doc.getElementById("tree");
  const kids = [...treeEl.children];
  const collRowIdx = kids.findIndex(k => k.classList && k.classList.contains("coll"));
  const firstCountryIdx = kids.findIndex(k => k.classList && k.classList.contains("country"));
  // (a) ordering + gating-on: the group exists and renders FIRST (before any .country row).
  ok(collRowIdx >= 0, "UX5: no collection row rendered in the tree");
  ok(firstCountryIdx > collRowIdx, "UX5: the Collections group must render BEFORE any country row, got coll@" + collRowIdx + " country@" + firstCountryIdx);
  ok(treeEl.querySelector(".treegroup"), "UX5: Collections group heading missing");
  const collRow = kids[collRowIdx];
  ok(/AusLAMP — 2 surveys · 3 stations/.test(collRow.textContent),
    "UX5: collection row label must read '<name> — <n> surveys · <m> stations' (Alpha 2 + Beta 1 = 3), got: " + collRow.textContent);
  // member rows are PASSIVE (indented name + count, NO checkbox — per-survey toggling stays with the orgs)
  const memberRows = [...treeEl.querySelectorAll(".collmember")];
  ok(memberRows.length === 2, "UX5: expected 2 passive member rows, got " + memberRows.length);
  ok(memberRows.every(r => !r.querySelector("input")), "UX5: member rows must be PASSIVE (no checkbox)");
  // (b) PUSH-SYNC: unchecking the collection box flips EXACTLY the member surveys (Alpha+Beta) and
  // refreshes; non-members (Gamma, Delta) untouched. Re-check restores.
  const collBox = collRow.querySelector("input[data-coll]");
  ok(collBox, "UX5: collection checkbox missing");
  collBox.checked = false; fire(collBox, "change");
  ok(surveyBoxes.find(b => b.value === "Alpha Survey").checked === false, "UX5: collection uncheck did not flip member Alpha Survey");
  ok(surveyBoxes.find(b => b.value === "Beta Survey").checked === false, "UX5: collection uncheck did not flip member Beta Survey");
  ok(surveyBoxes.find(b => b.value === "Gamma Survey").checked === true, "UX5: collection uncheck must NOT touch non-member Gamma");
  ok(surveyBoxes.find(b => b.value === "Delta Survey").checked === true, "UX5: collection uncheck must NOT touch non-member Delta");
  ok(A.visIds().length === 2 && A.visIds().includes("G1") && A.visIds().includes("D1"),
    "UX5: collection uncheck did not refresh the filter (expected exactly G1+D1), got " + JSON.stringify(A.visIds()));
  collBox.checked = true; fire(collBox, "change");
  ok(A.visIds().length === 5, "UX5: re-checking the collection did not restore all 5 stations");

  // C3. UX5 (D7) THE INVARIANT: collapse/expand NEVER changes checkbox state and NEVER changes the
  // filter result — with MIXED checkbox states (Beta unchecked). getAttribute('value') deliberately
  // (a value-less checkbox's .value is 'on' — the classic trap this codebase already documents).
  const betaBox = surveyBoxes.find(b => b.value === "Beta Survey");
  betaBox.checked = false; fire(betaBox, "change");
  const snapshot = () => [...treeEl.querySelectorAll("input")]
    .map(i => (i.getAttribute("value") || i.dataset.coll || i.dataset.org || i.dataset.country) + "=" + i.checked).join(",");
  const before = snapshot(), visBefore = JSON.stringify(A.visIds());
  ["c:Australia", "o:Australia||OrgX", "k:auslamp"].forEach(k => A.treeSetCollapsed(k, true));
  ok(snapshot() === before, "UX5 INVARIANT: collapsing changed a checkbox state.\n  before " + before + "\n  after  " + snapshot());
  ok(JSON.stringify(A.visIds()) === visBefore, "UX5 INVARIANT: collapsing changed the filter result: " + visBefore + " -> " + JSON.stringify(A.visIds()));
  // ...and the collapse REALLY hid rows (the invariant is not vacuously testing a no-op):
  ok(treeEl.querySelectorAll("label.survey.hidden").length > 0, "UX5: collapsing Australia hid no survey rows (visibility not applied)");
  ok(memberRows.every(r => r.classList.contains("hidden")), "UX5: collapsing the collection hid no member rows");
  ok(A.visIds().includes("A1"), "UX5 INVARIANT: a checked-but-HIDDEN survey dropped off the map (visibility leaked into filtering)");
  ["c:Australia", "o:Australia||OrgX", "k:auslamp"].forEach(k => A.treeSetCollapsed(k, false));
  ok(snapshot() === before && JSON.stringify(A.visIds()) === visBefore, "UX5 INVARIANT: expanding changed checkbox state or the filter result");
  ok(treeEl.querySelectorAll("label.survey.hidden").length === 0, "UX5: expanding did not unhide the survey rows");
  betaBox.checked = true; fire(betaBox, "change");
  ok(A.visIds().length === 5, "UX5 cleanup: restoring Beta did not restore 5 visible");

  // C4. UX5 (D7) CARET CLICK-TARGET: a caret click must NOT toggle the row's checkbox (the rows are
  // label-wrapped, so an unguarded child click would activate the label) — and must collapse/expand.
  const ausRow = kids[firstCountryIdx];   // "Australia" sorts before "New Zealand"
  const caret = ausRow.querySelector(".caret");
  ok(caret, "UX5: country row has no caret");
  const ausBox = ausRow.querySelector("input");
  const wasChecked = ausBox.checked;
  caret.dispatchEvent(new win.MouseEvent("click", { bubbles: true, cancelable: true }));
  ok(ausBox.checked === wasChecked, "UX5: caret click toggled the country checkbox (click-target hazard)");
  ok(A.treeIsCollapsed("c:Australia"), "UX5: caret click did not collapse the country");
  ok(caret.textContent === "▸", "UX5: caret glyph did not flip to collapsed, got " + JSON.stringify(caret.textContent));
  caret.dispatchEvent(new win.MouseEvent("click", { bubbles: true, cancelable: true }));
  ok(!A.treeIsCollapsed("c:Australia") && caret.textContent === "▾", "UX5: caret re-click did not expand");

  // D. COLLECTION route: #/collection/<id> shows the full-width page over the map; Back restores the map.
  win.location.hash = "#/collection/auslamp"; A.routeFromHash();
  ok(A.curView() === "collection", "hash route did not enter the collection view");
  ok(doc.getElementById("collectionview").style.display === "block", "#collectionview not shown");
  ok(doc.getElementById("map").style.display === "none", "#map not hidden behind the collection page");
  ok(/AusLAMP/.test(doc.getElementById("collectionview").innerHTML), "collection page missing its title");
  win.location.hash = ""; A.routeFromHash();
  ok(A.curView() === "map", "Back from the collection page did not restore the map view");

  // E. FIND: typing a survey name lists it AND keeps its stations on the map (the blank-map fix: passes()
  //    must also match s.survey, else a survey-name query — which Find invites — empties the map).
  const find = doc.getElementById("find");
  find.value = "Alpha Survey"; fire(find, "input");
  const items = [...doc.querySelectorAll("#findResults .fitem")];
  ok(items.some(it => it.dataset.find === "survey"), "Find dropdown did not offer the matching survey");
  ok(A.visSurveys().includes("Alpha Survey"), "Find blanked the map for a survey-name query");
  ok(!A.visSurveys().includes("Beta Survey"), "Find query should still exclude non-matching surveys");
  find.value = ""; fire(find, "input");   // reset: later sections (year/downloadable-only/etc) assume no active Find query

  // F. SURVEY route: #/survey/<slug> (the form the sitemap emits — 1463 links in the real build) must
  //    resolve the slug back to its survey label and open the survey story drawer (openSurvey), same as
  //    clicking a "Survey story" button does. Before this route existed, routeFromHash() silently fell
  //    through for #/survey/... (only #/collection/ and #/station/ were handled) — a sitemap deep-link
  //    landed on a blank/default view instead of the intended survey.
  win.location.hash = "#/survey/alpha"; A.routeFromHash();
  ok(doc.getElementById("drawer").classList.contains("open"), "#/survey/<slug> did not open the drawer");
  ok(/Alpha Survey/.test(doc.getElementById("drawer").innerHTML), "survey route opened the wrong (or no) survey");
  // Unknown slug: must not crash and must not leave a stale drawer open from the previous assertion.
  doc.getElementById("drawer").classList.remove("open");
  win.location.hash = "#/survey/does-not-exist"; A.routeFromHash();
  ok(!doc.getElementById("drawer").classList.contains("open"), "unknown survey slug must not open the drawer");

  // G. INTRO PANEL (S2 UX-A): visible on first load (no localStorage key set yet), dismiss hides it AND
  // sets the localStorage key, and the header "How to use AusMT" link re-opens it on demand.
  win.localStorage.removeItem("ausmt_intro_dismissed");
  const introOverlay = doc.getElementById("introOverlay");
  ok(introOverlay, "#introOverlay missing from index.html");
  // The panel is shown by runInit() at boot, not on-demand; re-run the show logic the way boot() did,
  // since A.boot() already ran once above (test A-F) — simulate "first load" by clearing the key and
  // calling the header link's underlying behaviour via a fresh maybeShowIntro()-equivalent: the header
  // "How to use" button always shows the panel unconditionally, which we reuse for BOTH assertions below.
  win.document.getElementById("howToUse").click();
  ok(!introOverlay.classList.contains("hidden"), "intro panel did not show via the header link");
  doc.getElementById("introClose").click();
  ok(introOverlay.classList.contains("hidden"), "dismissing the intro panel did not hide it");
  ok(win.localStorage.getItem("ausmt_intro_dismissed") === "1", "dismiss did not set the localStorage key");
  ok(A.introSeen() === true, "introSeen() did not observe the persisted dismiss");
  // Header link re-opens it even though the dismissed key is set (re-opening on demand must not be
  // gated by the "seen" flag — only the automatic first-load path is).
  win.document.getElementById("howToUse").click();
  ok(!introOverlay.classList.contains("hidden"), "header link did not re-open a previously-dismissed panel");
  doc.getElementById("introClose").click();

  // H0. ONE HELP BUTTON IN THE HEADER (UX feedback round 3, item 2): the header "Take the tour" button
  // (#headerTour) was removed. The single header help entry point is now "How to use AusMT" (#howToUse),
  // which opens the intro panel; the panel's own "Take the tour" button (#introTakeTour) starts the tour.
  ok(!doc.getElementById("headerTour"), "#headerTour should have been removed from the header (item 2)");
  ok(doc.getElementById("howToUse"), "#howToUse (the single header help button) is missing");
  ok(doc.getElementById("introTakeTour"), "#introTakeTour (the panel's tour button) is missing");

  // H. TOUR v4 (UX rounds 1/2 + UX4 D5): 10 steps now. Opens from the intro panel's "Take the tour"
  // button (#introTakeTour) — the ONLY tour entry point now that #headerTour is gone. Step 1 text matches
  // the verbatim design copy, ArrowRight advances to step 2, Esc closes and tears the tour DOM down.
  doc.getElementById("introTakeTour").click();
  ok(A.tourStep() === 0, "tour did not open to step 0 from the intro-panel button");
  let tourText = doc.getElementById("tourText");
  ok(tourText, "#tourText not rendered by the tour");
  ok(tourText.textContent === "Every dot is an MT station. Click one to see its transfer function.",
    "tour step 1 text does not match the verbatim design copy, got: " + tourText.textContent);
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowRight" }));
  ok(A.tourStep() === 1, "ArrowRight did not advance the tour to step 2, at step " + A.tourStep());
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape" }));
  ok(A.tourStep() === -1, "Esc did not close the tour");
  ok(!doc.getElementById("tourCard"), "Esc did not remove the tour DOM");

  // H2. TOUR v4 DEMO STEPS (UX4 D5) + drawer enter action. New step layout: 0 map, 1 filters,
  // 2 FIND DEMO, 3 TREE BROWSE, 4 station drawer, ... Each demo step's EXIT hook must fire on ALL
  // three ways out — Next, Back and mid-tour close — leaving the find box and tree state as found.
  const findBox = doc.getElementById("find"), findRes = doc.getElementById("findResults");
  ok(doc.getElementById("drawer").classList.contains("open") === false, "drawer unexpectedly open before the tour restarts");
  ok(findBox.value === "", "find box not empty before the tour starts");
  doc.getElementById("introTakeTour").click();                           // step 1 (index 0)
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowRight" })); // -> index 1 (filters)
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowRight" })); // -> index 2: FIND DEMO
  ok(A.tourStep() === 2, "ArrowRight x2 did not reach the Find demo step, at step " + A.tourStep());
  // enter typed "AusLAMP" with a REAL input event: the live wiring must have filtered the map AND
  // rendered the dropdown with the actual AusLAMP collection match (fixture collection title "AusLAMP").
  ok(findBox.value === "AusLAMP", "Find demo did not type AusLAMP into the box, got: " + JSON.stringify(findBox.value));
  ok(findRes.style.display === "block", "Find demo did not render the live dropdown");
  ok([...findRes.querySelectorAll(".fitem")].some(it => it.dataset.find === "coll"),
    "Find demo dropdown is missing the real AusLAMP collection match");
  ok(A.nVisCount() === 0, "Find demo should live-filter the fixture map to 0 (no fixture station matches 'AusLAMP'), got " + A.nVisCount());
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowRight" })); // -> index 3: TREE BROWSE (find exit fires)
  ok(A.tourStep() === 3, "ArrowRight did not reach the tree-browse step, at step " + A.tourStep());
  ok(findBox.value === "", "leaving the Find demo FORWARD did not clear the typed query, got: " + JSON.stringify(findBox.value));
  ok(findRes.style.display === "none", "leaving the Find demo FORWARD did not close the dropdown");
  ok(A.nVisCount() === 5, "leaving the Find demo FORWARD did not restore the filtered map, got " + A.nVisCount());
  // graceful degrade (D5): kalkaroo-2022 is NOT in this fixture -> the resolved target must be the
  // FIRST survey present (surveys[] is sorted; "Alpha Survey"), and nothing crashed getting here.
  ok(A.tourTreeTarget() === "Alpha Survey",
    "tree-browse step must degrade to the first survey when kalkaroo-2022 is absent, got: " + JSON.stringify(A.tourTreeTarget()));
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowLeft" }));  // BACK -> index 2 (tree exit fires, find re-enters)
  ok(A.tourStep() === 2, "ArrowLeft did not return to the Find demo step, at step " + A.tourStep());
  ok(findBox.value === "AusLAMP", "re-entering the Find demo backwards did not re-type the query");
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape" }));     // MID-TOUR CLOSE from the demo step
  ok(A.tourStep() === -1, "Esc from the Find demo did not close the tour");
  ok(findBox.value === "", "mid-tour close did not clear the Find demo query, got: " + JSON.stringify(findBox.value));
  ok(findRes.style.display === "none", "mid-tour close did not close the Find dropdown");
  ok(A.nVisCount() === 5, "mid-tour close did not restore the filtered map, got " + A.nVisCount());
  ok(doc.getElementById("tree").scrollTop === 0, "tree scroll not back to its pre-tour position after close");
  // Drawer enter action (was index 2 pre-D5, now index 4): reaching it must open the first visible
  // station's drawer, and Esc from there must close it AND restore the map view.
  doc.getElementById("introTakeTour").click();                           // restart, index 0
  for (let k = 0; k < 4; k++) win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowRight" })); // -> index 4
  ok(A.tourStep() === 4, "ArrowRight x4 did not reach the station-drawer step, at step " + A.tourStep());
  ok(doc.getElementById("drawer").classList.contains("open"), "the station-drawer step did not open the drawer");
  ok(findBox.value === "", "passing THROUGH the Find demo left residue in the find box");
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape" }));
  ok(A.tourStep() === -1, "Esc from the drawer step did not close the tour");
  ok(!doc.getElementById("drawer").classList.contains("open"), "Esc from the drawer step did not close the drawer it opened");
  ok(A.curView() === "map", "Esc from the drawer step did not restore the map view");

  // H3. UX5 (D8): the tour tree step EXPANDS the target's collapsed ancestors (Alpha Survey ->
  // c:Australia / o:Australia||OrgX) and RESTORES the prior collapse state on ALL THREE exit paths
  // (forward, back, close). The collapse set is real state (treeCollapsedKeys), not a proxy.
  const goToTreeStep = () => { doc.getElementById("introTakeTour").click();
    for (let k = 0; k < 3; k++) win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowRight" })); };
  A.treeSetCollapsed("c:Australia", true); A.treeSetCollapsed("o:Australia||OrgX", true);
  // path 1: FORWARD exit
  goToTreeStep();
  ok(A.tourStep() === 3, "D8: did not reach the tree step, at " + A.tourStep());
  ok(!A.treeIsCollapsed("c:Australia") && !A.treeIsCollapsed("o:Australia||OrgX"),
    "D8: the tree step did not expand the target's collapsed ancestors");
  ok(!surveyBoxes.find(b => b.value === "Alpha Survey").closest("label").classList.contains("hidden"),
    "D8: the target survey row is still hidden on the tree step");
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowRight" }));   // FORWARD exit (-> drawer step)
  ok(A.treeIsCollapsed("c:Australia") && A.treeIsCollapsed("o:Australia||OrgX"),
    "D8: FORWARD exit did not restore the collapse state");
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape" }));       // close the tour cleanly
  // path 2: BACK exit
  goToTreeStep();
  ok(!A.treeIsCollapsed("c:Australia"), "D8: re-entry (path 2) did not expand again");
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowLeft" }));    // BACK exit (-> find demo)
  ok(A.treeIsCollapsed("c:Australia") && A.treeIsCollapsed("o:Australia||OrgX"),
    "D8: BACK exit did not restore the collapse state");
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape" }));
  // path 3: CLOSE (Esc) at the tree step
  goToTreeStep();
  ok(!A.treeIsCollapsed("c:Australia"), "D8: re-entry (path 3) did not expand again");
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape" }));
  ok(A.treeIsCollapsed("c:Australia") && A.treeIsCollapsed("o:Australia||OrgX"),
    "D8: CLOSE exit did not restore the collapse state");
  A.treeSetCollapsed("c:Australia", false); A.treeSetCollapsed("o:Australia||OrgX", false);   // cleanup
  ok(A.treeCollapsedKeys().length === 0, "D8 cleanup: collapse set not empty after the H3 block");

  // I. EMPTY-STATE fixture: the intro panel must still render (it explains the portal even before any
  // survey exists) and boot must not crash. A fresh window/localStorage so "first visit" is genuine.
  const emptyWin = await bootFreshWindow({
    "data/catalogue.json": [], "data/tf.json": [], "data/sci.json": [], "data/surveys.json": {},
  });
  const emptyDoc = emptyWin.document;
  ok(emptyWin.__api.nST() === 0, "empty-state fixture unexpectedly loaded stations");
  const emptyOverlay = emptyDoc.getElementById("introOverlay");
  ok(emptyOverlay, "#introOverlay missing in the empty-data boot");
  ok(!emptyOverlay.classList.contains("hidden"), "intro panel did not show on first visit in the empty-data state");
  ok(/No surveys published yet/.test(emptyDoc.getElementById("map").innerHTML), "empty-state message did not render alongside the intro panel");

  // I2. UX5 (D6) GATING-OFF: a boot WITHOUT collections.json renders NO Collections group (and the
  // country/org/survey rows + their carets are unaffected) — the graceful pre-collections behaviour.
  const noCollData = {};
  Object.keys(DATAMAP).forEach(k => { if (k !== "data/collections.json") noCollData[k] = DATAMAP[k]; });
  const wNo = await bootFreshWindow(noCollData);
  const tNo = wNo.document.getElementById("tree");
  ok(!tNo.querySelector("[data-coll]") && !tNo.querySelector(".treegroup"),
    "UX5: the Collections group must NOT render when the data has no collections");
  ok(tNo.querySelectorAll("label.country").length === 2, "UX5: countries missing in the no-collections boot");
  ok(tNo.querySelectorAll(".caret").length > 0, "UX5: disclosure carets missing in the no-collections boot");

  // J. YEAR RANGE filter (S3 + UX feedback round 1 #2): Alpha [2010,2012], Beta [2018,2019], Gamma
  // undated (no year fields at all). The two inputs get corpus-wide HINTS (placeholder + min/max) from
  // buildState()'s applyYearRangeHints() — min year_start / max year_end across SMETA, here 2010/2019 —
  // but must stay EMPTY on load (a value would immediately exclude Gamma under the filter semantics).
  const yearFrom = doc.getElementById("yearFrom"), yearTo = doc.getElementById("yearTo");
  ok(yearFrom && yearTo, "#yearFrom/#yearTo inputs missing from the filter rail");
  ok(yearFrom.value === "" && yearTo.value === "", "year-range inputs must stay empty on load, got: " + JSON.stringify([yearFrom.value, yearTo.value]));
  ok(yearFrom.placeholder === "2010", "yearFrom placeholder should hint the corpus min (2010), got: " + yearFrom.placeholder);
  ok(yearTo.placeholder === "2019", "yearTo placeholder should hint the corpus max (2019), got: " + yearTo.placeholder);
  ok(yearFrom.min === "2010" && yearFrom.max === "2019", "yearFrom min/max attrs should be the corpus range, got: " + JSON.stringify([yearFrom.min, yearFrom.max]));
  const yearHead = doc.getElementById("yearRangeHead");
  ok(yearHead && yearHead.textContent === "Year range (2010–2019)", "Year range label should append the corpus range, got: " + (yearHead && yearHead.textContent));
  yearFrom.value = "2015"; fire(yearFrom, "input");
  ok(A.visSurveys().includes("Beta Survey"), "year filter wrongly excluded Beta Survey (within range)");
  ok(!A.visSurveys().includes("Alpha Survey"), "year filter did not exclude Alpha Survey (ended before 2015)");
  ok(!A.visSurveys().includes("Gamma Survey"), "year filter did not exclude the undated Gamma Survey once a year was set");
  ok(!A.visSurveys().includes("Delta Survey"), "year filter did not exclude the undated Delta Survey once a year was set");
  ok(A.visIds().length === 1, "expected exactly 1 visible station (B1) after the year filter, got " + A.visIds().length);
  yearFrom.value = ""; fire(yearFrom, "input");
  ok(A.visIds().length === 5, "clearing the year filter did not restore all 5 stations");

  // K. DOWNLOADABLE-HERE-ONLY toggle (S3): Beta's B1 and embargoed Delta's D1 have edi_available=0; the rest =1.
  const dlOnly = doc.getElementById("dlOnly");
  ok(dlOnly, "#dlOnly checkbox missing from the filter rail");
  dlOnly.checked = true; fire(dlOnly, "change");
  ok(!A.visIds().includes("B1"), "downloadable-only did not exclude the non-downloadable station B1");
  ok(!A.visIds().includes("D1"), "downloadable-only did not exclude the embargoed (non-downloadable) station D1");
  ok(A.visIds().length === 3, "expected 3 visible stations with downloadable-only on, got " + A.visIds().length);
  dlOnly.checked = false; fire(dlOnly, "change");
  ok(A.visIds().length === 5, "clearing downloadable-only did not restore all 5 stations");

  // L. GO TO PLACE REMOVED (UX feedback round 1 #1): operator decision, redundant. Assert the input
  // (and its datalist) are gone from the rendered page, not merely unused.
  ok(!doc.getElementById("goPlace"), "#goPlace should have been removed from the filter rail");
  ok(!doc.getElementById("auPlaces"), "#auPlaces datalist should have been removed along with #goPlace");

  // M. SCREENING (advanced) (UX feedback round 1 #4): the Min-TF-diagnostic slider (#qSeg) and the
  // colour-by segmented control (#colorSeg) live inside ONE <details class="advanced"> collapsed by
  // default (no `open` attribute) at the bottom of the filter rail — every element id inside is
  // unchanged from before the relocation, so the wiring above (colorSeg/qSeg handlers) still applies.
  const advDetails = doc.querySelector("details.advanced");
  ok(advDetails, "no <details class=\"advanced\"> found in the filter rail");
  ok(advDetails.hasAttribute("open") === false, "Screening (advanced) details must be collapsed by default");
  ok(advDetails.querySelector("#qSeg"), "#qSeg (Min-TF-diagnostic) is not inside the Screening (advanced) details");
  ok(advDetails.querySelector("#colorSeg"), "#colorSeg (colour-by) is not inside the Screening (advanced) details");

  // N. RECENTLY ADDED (S3): sorted newest-first by the same date logic as the engine's feed.xml
  // (latest release_notes date, else the year_end/year_start fallback). Assert the observed order
  // rather than hard-coding which of Alpha/Beta wins, so this stays correct if fixture dates change.
  const recents = A.recentlyAdded();
  ok(recents.length === 2, "expected 2 dated surveys (Alpha, Beta) in recentlyAdded(), got " + recents.length + ": " + JSON.stringify(recents));
  ok(!recents.some(e => e.sv === "Gamma Survey"), "recentlyAdded() must omit the undated Gamma Survey");
  ok(recents[0].date >= recents[1].date, "recentlyAdded() is not sorted newest-first: " + JSON.stringify(recents));
  const recentStrip = doc.getElementById("recentStrip");
  ok(recentStrip && /Recently added/.test(recentStrip.innerHTML), "#recentStrip did not render a 'Recently added' heading");
  ok(new RegExp(recents[0].slug).test(recentStrip.innerHTML) || recentStrip.innerHTML.indexOf("#/survey/" + recents[0].slug) >= 0,
    "#recentStrip did not link the newest survey by its #/survey/<slug> route");
  const recentSide = doc.getElementById("recentSide");
  ok(recentSide && recentSide.innerHTML.indexOf("#/survey/") >= 0, "the compact map-sidebar recently-added variant (#recentSide) did not render links");

  // O. C1b DISPLAY-PRODUCT GATE: opening an EMBARGOED survey's station must replace the four TF plots with
  //    an access panel carrying the verbatim embargo copy, and render NO svg plot paths (the response
  //    curves ARE the embargoed data). An OPEN survey's station must still plot. FAILS pre-fix: the drawer
  //    renders the (now-empty) plots area with no access panel — the verbatim copy is absent.
  const drawerEl = doc.getElementById("drawer");
  // Verbatim no-date embargo copy (embargo_until is null in the fixture) — pinned so a copy edit fails here.
  const EMBARGO_NODATE = "This survey is embargoed. Station locations and survey metadata are public; " +
    "transfer functions and downloads are withheld.";
  win.location.hash = "#/station/au.delta.D1"; A.routeFromHash();
  ok(drawerEl.classList.contains("open"), "#/station route did not open the embargoed station's drawer");
  ok(drawerEl.textContent.indexOf(EMBARGO_NODATE) >= 0,
    "embargoed station drawer is missing the verbatim no-date embargo panel copy; drawer text was: " + drawerEl.textContent.slice(0, 400));
  ok(drawerEl.querySelectorAll("svg path").length === 0,
    "embargoed station drawer must render NO svg plot paths (curves are withheld data), found " + drawerEl.querySelectorAll("svg path").length);
  // The related-products TF tile must say "embargoed", not "EDI (via source archive)".
  ok(drawerEl.innerHTML.indexOf("EDI (via source archive)") < 0,
    "embargoed station must NOT offer the 'EDI (via source archive)' fallback tile");
  // An OPEN survey's station (A1) still plots — the withholding is CONDITIONAL on access, not a blanket wipe.
  drawerEl.classList.remove("open");
  win.location.hash = "#/station/au.alpha.A1"; A.routeFromHash();
  ok(drawerEl.classList.contains("open"), "#/station route did not open the open station's drawer");
  ok(drawerEl.querySelectorAll("svg path").length > 0,
    "an OPEN survey's station must still render TF plot paths, found none");
  ok(drawerEl.textContent.indexOf(EMBARGO_NODATE) < 0,
    "an OPEN survey's station must NOT show the embargo access panel");

  // P. PID LINKS (PID schema + goal-2 proof). Rendered PIDs must be REAL clickable <a href> anchors,
  //    not plain text, and a HOSTILE pid must render INERT (no executable href, no HTML injection).
  //
  //    P1 — SURVEY drawer (openSurvey -> identifiersHtml): survey_pid (m.pid) and each instrument's
  //    registry pid from the additive instruments[] list. The hostile instrument pid (javascript:alert(1))
  //    must be neutralised by the escUrl guard (rewritten to the safe handle host — the SAME behaviour as
  //    the already-tested survey_pid pidLink), so NO href carries a javascript: scheme.
  const dpid = doc.getElementById("drawer");
  dpid.classList.remove("open");
  win.location.hash = "#/survey/alpha"; A.routeFromHash();
  ok(dpid.classList.contains("open"), "PID: #/survey/alpha did not open Alpha's drawer");
  let hrefs = [...dpid.querySelectorAll("a[href]")].map(a => a.getAttribute("href"));
  ok(hrefs.some(h => h === "https://hdl.handle.net/survey/alpha-pid"),
    "PID: survey_pid (m.pid) did not render as a clickable <a href> to its handle URL; hrefs=" + JSON.stringify(hrefs));
  ok(hrefs.some(h => h === "https://instruments.auscope.org.au/system/LEMI-423-007"),
    "PID: a good instruments[].pid did not render as a clickable <a href>; hrefs=" + JSON.stringify(hrefs));
  ok(!hrefs.some(h => /^javascript:/i.test((h || "").trim())),
    "PID: a hostile instrument pid produced an EXECUTABLE javascript: href — XSS guard failed; hrefs=" + JSON.stringify(hrefs));
  ok(hrefs.some(h => h === "https://hdl.handle.net/javascript:alert(1)"),
    "PID: the hostile instrument pid was not neutralised to the safe handle host; hrefs=" + JSON.stringify(hrefs));
  ok(!/onerror\s*=/i.test(dpid.innerHTML), "PID: an onerror= attribute leaked into the survey drawer HTML");
  // The instrument model DISPLAY line (unchanged behaviour) must still be present as text.
  ok(/LEMI 423; Phoenix MTU-5C/.test(dpid.textContent), "PID: the instrument_model display line disappeared");

  //    P2 — STATION drawer (openStation -> provGraph): the time_series collection_pid (m.ts_pid) renders
  //    as a link to https://doi.org/<ts_pid> in the provenance lineage. This proves goal 2 for
  //    collection_pid — it is a clickable link, not plain text — for a survey that declares its own ts_pid.
  dpid.classList.remove("open");
  win.location.hash = "#/station/au.alpha.A1"; A.routeFromHash();
  ok(dpid.classList.contains("open"), "PID: #/station/au.alpha.A1 did not open the station drawer");
  hrefs = [...dpid.querySelectorAll("a[href]")].map(a => a.getAttribute("href"));
  ok(hrefs.some(h => h === "https://doi.org/10.25914/alpha-timeseries"),
    "PID: collection_pid (m.ts_pid) did not render as a clickable <a href> in the station lineage; hrefs=" + JSON.stringify(hrefs));
  dpid.classList.remove("open");

  // Q. UX4 (D2) STILL COUNTED ACROSS CONTAINERS: a station moving BETWEEN the cluster group and the plain
  // AusLAMP layer must NOT drop out of the visible count or the survey selection — the partition is a
  // rendering split, not a filter. Flip Gamma's G1 (a non-member, so currently CLUSTERED) into an AusLAMP
  // member by pointing its slug at a set entry, refresh (real partitionMarkers over the Leaflet-stubbed
  // layers), and assert the visible count is unchanged and select-by-survey still picks it up. Done LAST so
  // it can't perturb earlier fixture assertions. Restores state afterward.
  drawerEl.classList.remove("open");
  A.setAuslampSet([...A.auslampSet(), "gamma"]);   // make Gamma an AusLAMP member -> G1 crosses into the plain layer
  A.setSlug("G1", "gamma");                          // G1's slug already 'gamma' via SMETA, but pin it explicitly
  A.refresh();
  ok(A.nVisCount() === 5, "moving G1 into the AusLAMP layer changed the visible count (the split must not filter), got " + A.nVisCount());
  ok(A.visIds().includes("G1"), "G1 dropped out of the visible set after crossing map containers");
  A.selectSurvey("Gamma Survey");
  ok(A.selCount() === 1, "select-by-survey did not count G1 after it moved to the AusLAMP layer, got " + A.selCount());
  A.buildAuslampSet();   // restore the boot-built set

  // R. CARD DESCRIPTION FROM survey.yaml (UX feedback round 3, item 6): the survey card's .desc renders
  // the escaped survey.yaml abstract (m.blurb) when present; a hostile abstract must render INERT; and an
  // absent/blank abstract yields the honest muted fallback line — NOT fabricated marketing copy.
  // (a) the OLD hardcoded placeholder is gone from every rendered card.
  A.setBlurb("Alpha Survey", null);                      // ensure a known "absent" starting state
  ok(A.cardHtml("Alpha Survey").indexOf("scraped from the EDIs automatically") < 0,
    "the old hardcoded card-description placeholder must be gone");
  // (b) a normal abstract renders as the description text.
  A.setBlurb("Alpha Survey", "A regional MT survey across the Gawler Craton.");
  let cardA = A.cardHtml("Alpha Survey");
  ok(cardA.indexOf("A regional MT survey across the Gawler Craton.") >= 0,
    "card .desc did not render the survey.yaml abstract (m.blurb)");
  // (c) HOSTILE-BLURB XSS: an abstract carrying an <img onerror=…> must be escaped to inert text — no live
  //     tag, no raw onerror attribute in the rendered HTML. Assert against the actual jsdom-parsed card.
  const XSS = "<img src=x onerror=\"window.__pwned=1\">pwn";
  A.setBlurb("Alpha Survey", XSS);
  const holder = doc.createElement("div");
  holder.innerHTML = A.cardHtml("Alpha Survey");
  const desc = holder.querySelector(".desc");
  ok(desc, "card has no .desc element for the hostile-blurb check");
  ok(desc.querySelector("img") === null, "hostile blurb produced a LIVE <img> element (XSS not neutralised)");
  ok(desc.innerHTML.indexOf("onerror") < 0 || desc.querySelector("[onerror]") === null,
    "hostile blurb left a live onerror handler");
  ok(desc.textContent.indexOf("pwn") >= 0, "escaped hostile blurb should still show its literal text");
  ok(win.__pwned === undefined, "hostile blurb executed script (window.__pwned was set)");
  // (d) absent/blank abstract -> honest muted fallback line (mentions the survey.yaml `abstract` field).
  A.setBlurb("Alpha Survey", "   ");                     // whitespace-only counts as absent (trim())
  ok(A.cardHtml("Alpha Survey").indexOf("No survey description provided") >= 0,
    "blank abstract did not fall back to the honest 'No survey description provided' line");
  A.setBlurb("Alpha Survey", null);
  ok(A.cardDesc({}).indexOf("No survey description provided") >= 0, "cardDesc({}) should return the fallback line");
  ok(A.cardDesc({ blurb: "hi" }).indexOf("hi") >= 0, "cardDesc should render a present blurb");

  // S. DIMENSIONALITY HIDDEN FROM SCREENING DISPLAYS (UX feedback round 3, item 7): removed from the
  // station-drawer screening grid (7a), the survey-card stats line (7b) and the survey-story table (7c) —
  // while the phase-tensor/skew and strike lines STAY (dimensionality is inferable from them).
  // (a) station drawer: no "Dimensionality" cell, but the skew (|β|) + strike line remains.
  win.location.hash = "#/station/au.beta.B1"; A.routeFromHash();
  const drw = doc.getElementById("drawer");
  ok(drw.innerHTML.indexOf(">Dimensionality<") < 0, "station drawer still shows a 'Dimensionality' screening cell (item 7a)");
  ok(drw.textContent.indexOf("phase-tensor strike") >= 0, "station drawer lost the strike line (must be KEPT)");
  ok(drw.innerHTML.indexOf("mean |β|") >= 0 || drw.innerHTML.indexOf("|β|") >= 0,
    "station drawer lost the mean |β| (skew) figure (must be KEPT)");
  drw.classList.remove("open");
  // (b) survey card stats line: no "N×3-D / N×2-D / N×1-D" fragment.
  ok(A.cardHtml("Beta Survey").indexOf("×3-D") < 0 && A.cardHtml("Beta Survey").indexOf("x3-D") < 0,
    "survey card stats line still shows the N×3-D/2-D/1-D dimensionality fragment (item 7b)");
  // (c) survey-story summary table: no "dimensionality mix" row, but tipper/remote-reference rows remain.
  const sum = A.summaryHtml("Beta Survey");
  ok(sum.indexOf("dimensionality mix") < 0, "survey-story table still shows the 'dimensionality mix' row (item 7c)");
  ok(sum.indexOf("tipper availability") >= 0 && sum.indexOf("remote reference") >= 0,
    "survey-story table lost sibling rows that must be KEPT (tipper/remote reference)");

  // T. C20 TF COMPLETENESS — induction-arrow panel (D3) + error bars (D4), in the station drawer.
  //   A1: tzx_re>0 (only), rho+phase errors present  -> arrow panel with the Parkinson label, a REAL
  //       arrow pointing SOUTH (Parkinson north = -tzx_re < 0), and error-bar whiskers on ρ/φ.
  //   A2: no tipper, no errors                        -> "no tipper" state (no arrow panel) + no bars.
  const drwC = doc.getElementById("drawer");
  drwC.classList.remove("open");
  win.location.hash = "#/station/au.alpha.A1"; A.routeFromHash();
  ok(drwC.classList.contains("open"), "C20: #/station/au.alpha.A1 did not open the drawer");
  // (a) arrow panel EXISTS with the verbatim Parkinson label (the |T|-magnitude plot is gone).
  ok(drwC.innerHTML.indexOf("Induction arrows - Parkinson convention (real arrows point toward conductors); imaginary unreversed.") >= 0,
    "C20 D3: the induction-arrow panel + verbatim Parkinson label is missing from the drawer");
  ok(drwC.innerHTML.indexOf("tipper magnitude |T|") < 0,
    "C20 D3: the old |T|-magnitude plot title is still present (panel was not replaced)");
  ok(drwC.innerHTML.indexOf("|T|=0.5") >= 0, "C20 D3: the |T|=0.5 unit-scale reference is missing");
  // (b) SIGN MAPPING: parse the REAL arrow <line>s (solid copper #E0782F) inside the drawer. tzx_re>0
  // means real north = -tzx_re < 0, so every real arrow must point DOWN (screen y2 > y1 = SOUTH) with
  // no east deflection (x2 == x1, since tzy_re == 0). This is the D3 falsifiability check.
  // Match ONLY the arrow-panel REAL arrows: solid copper at the arrow stroke-width "1.2" (error bars use
  // "0.8"+opacity and the imaginary arrows use "1.0", so this excludes both).
  const realArrows = [...drwC.innerHTML.matchAll(/<line x1="([\d.]+)" y1="([\d.]+)" x2="([\d.]+)" y2="([\d.]+)" stroke="#E0782F" stroke-width="1\.2"/g)];
  ok(realArrows.length >= 1, "C20 D3: no REAL (copper) induction arrows rendered for a tippered station");
  ok(realArrows.every(m => parseFloat(m[4]) > parseFloat(m[2])),
    "C20 D3 SIGN: a REAL arrow for tzx_re>0 must point SOUTH (y2>y1); got " +
    JSON.stringify(realArrows.map(m => [m[2], m[4]])));
  ok(realArrows.every(m => Math.abs(parseFloat(m[3]) - parseFloat(m[1])) < 0.1),
    "C20 D3 SIGN: a REAL arrow with tzy_re=0 must have no east deflection (x2==x1); got " +
    JSON.stringify(realArrows.map(m => [m[1], m[3]])));
  // (c) ERROR BARS present for A1 (rho copper #E0782F + teal #2E8FA3 whiskers with the .55 opacity).
  ok(/<line [^>]*stroke="#E0782F" stroke-width=".8" stroke-opacity=".55"/.test(drwC.innerHTML) ||
     /<line [^>]*stroke="#2E8FA3" stroke-width=".8" stroke-opacity=".55"/.test(drwC.innerHTML),
    "C20 D4: error bars did not render for a station WITH errors");
  // (d) A2: no tipper => NO arrow panel; no errors => NO error bars.
  drwC.classList.remove("open");
  win.location.hash = "#/station/au.alpha.A2"; A.routeFromHash();
  ok(drwC.classList.contains("open"), "C20: #/station/au.alpha.A2 did not open the drawer");
  ok(drwC.innerHTML.indexOf("Induction arrows - Parkinson convention") < 0,
    "C20 D3: a tipperless station must show the no-tipper state (no arrow panel)");
  ok(!/stroke-width=".8" stroke-opacity=".55"/.test(drwC.innerHTML),
    "C20 D4: a station WITHOUT errors must render NO error bars");
  // A2 still plots ρ/φ/phase-tensor (the curves themselves), proving (c)/(d) are about bars/arrows only.
  ok(drwC.querySelectorAll("svg path").length > 0, "C20: a no-tipper/no-error open station must still plot ρ/φ curves");
  drwC.classList.remove("open");

  // U. C22 CITATION HONESTY (chief-architect ruling 2026-07-07; pre-release hostile-review finding
  // 2026-07-06 — state.js publisher placeholder). A NO-DOI survey's
  // generated .bib/.ris must carry NO placeholder text a reference manager would ingest as real: the
  // pre-C22 AUSMT_SELF.pb publisher read "AusMT (DOI to be minted per release via Zenodo)" and leaked
  // into EVERY no-DOI citation's publisher/PB field (the doi=/DO/UR FIELDS were already guarded by
  // d2bc616's `${doi?...:""}` — the leak was the publisher STRING, not the DOI field). A WITH-DOI
  // survey keeps its real DOI in both formats; the NCI/TS-collection entries are BYTE-pinned to their
  // pre-C22 output; and the human-readable CITATIONS.txt line for a no-DOI entry SAYS
  // "[no DOI assigned]" explicitly (exports.js citeLine — net-new in C22, sanctioned by the ruling).
  //
  // NOTE (Invariant 10): section U asserts the ASSEMBLY HELPERS (apa/bibtex/ris/citeLine) directly —
  // the exact functions the #dlCite click handler feeds into the pack — NOT the zipped file itself:
  // win.JSZip is a STUB in this harness (it swallows z.file() contents), so any "the shipped zip is
  // clean" claim routed through a #dlCite click here would be a vacuous test of the stub.
  const PLACEHOLDER = "DOI to be minted";
  // (a) NO-DOI survey — Beta has neither cite nor doi in the fixture; this is the EXACT call shape of
  //     the per-survey loop in exports.js dlCite (m.cite||AUSMT_SELF, m.doi).
  const mBeta = A.smeta("Beta Survey") || {};
  ok(mBeta.doi === undefined && mBeta.cite === undefined,
    "U: fixture drift — Beta Survey must stay a no-cite/no-DOI survey for the no-DOI leg");
  const bibNo = A.bibtex("beta_survey", mBeta.cite || A.AUSMT_SELF, mBeta.doi);
  const risNo = A.ris(mBeta.cite || A.AUSMT_SELF, mBeta.doi);
  ok(bibNo.indexOf(PLACEHOLDER) < 0, "U: a no-DOI survey's .bib carries the placeholder string ('" + PLACEHOLDER + "'):\n" + bibNo);
  ok(risNo.indexOf(PLACEHOLDER) < 0, "U: a no-DOI survey's .ris carries the placeholder string ('" + PLACEHOLDER + "'):\n" + risNo);
  ok(!/\bdoi\s*=/.test(bibNo), "U: a no-DOI survey's .bib must have NO doi= line:\n" + bibNo);
  ok(!/^DO  - /m.test(risNo) && !/^UR  - /m.test(risNo), "U: a no-DOI survey's .ris must have NO DO/UR lines:\n" + risNo);
  // (b) catalogue-level self-citation (exports.js passes AUSMT_SELF with doi=null).
  const bibSelf = A.bibtex("ausmt_catalogue", A.AUSMT_SELF, null);
  const risSelf = A.ris(A.AUSMT_SELF, null);
  ok(bibSelf.indexOf(PLACEHOLDER) < 0, "U: the catalogue self-citation .bib carries the placeholder:\n" + bibSelf);
  ok(risSelf.indexOf(PLACEHOLDER) < 0, "U: the catalogue self-citation .ris carries the placeholder:\n" + risSelf);
  ok(!/\bdoi\s*=/.test(bibSelf) && !/^DO  - /m.test(risSelf),
    "U: the catalogue self-citation must fabricate no DOI field");
  // (c) WITH-DOI survey keeps its real DOI in BOTH formats (Alpha carries doi+cite in the fixture).
  const mAlpha = A.smeta("Alpha Survey") || {};
  ok(mAlpha.doi === "10.99999/alpha-tf-doi",
    "U: fixture drift — Alpha Survey must carry the with-DOI fixture doi, got " + JSON.stringify(mAlpha.doi));
  const bibW = A.bibtex("alpha_survey", mAlpha.cite || A.AUSMT_SELF, mAlpha.doi);
  const risW = A.ris(mAlpha.cite || A.AUSMT_SELF, mAlpha.doi);
  ok(bibW.indexOf("doi       = {10.99999/alpha-tf-doi},") >= 0, "U: the with-DOI .bib lost its real doi= line:\n" + bibW);
  ok(risW.indexOf("DO  - 10.99999/alpha-tf-doi") >= 0 && risW.indexOf("UR  - https://doi.org/10.99999/alpha-tf-doi") >= 0,
    "U: the with-DOI .ris lost its real DO/UR lines:\n" + risW);
  // (d) NCI/TS-collection entries BYTE-untouched — pinned to the output of the pre-C22 helpers at
  //     cbb7a88 (generated, not hand-typed). A single changed byte in either entry fails here.
  ok(A.TS_COLLECTION.doi === "10.25914/mtjg-jp22", "U: TS_COLLECTION.doi drifted from 10.25914/mtjg-jp22");
  const NCI_BIB_PIN = "@misc{nci_auscope_mt,\n  author    = {AuScope and NCI Australia},\n  title     = {NCI-AuScope Magnetotelluric Collection — packed raw, Level 1 and Level 2 time series},\n  year      = {n.d.},\n  publisher = {NCI Australia},\n  doi       = {10.25914/mtjg-jp22},\n  note      = {Accessed via the AusMT portal}\n}";
  const NCI_RIS_PIN = "TY  - DATA\nAU  - AuScope\nAU  - NCI Australia\nTI  - NCI-AuScope Magnetotelluric Collection — packed raw, Level 1 and Level 2 time series\nPY  - \nPB  - NCI Australia\nDO  - 10.25914/mtjg-jp22\nUR  - https://doi.org/10.25914/mtjg-jp22\nER  -";
  ok(A.bibtex("nci_auscope_mt", A.NCI_CITE, A.TS_COLLECTION.doi) === NCI_BIB_PIN,
    "U: the NCI .bib entry changed byte(s) vs the pre-C22 pin:\n" + A.bibtex("nci_auscope_mt", A.NCI_CITE, A.TS_COLLECTION.doi));
  ok(A.ris(A.NCI_CITE, A.TS_COLLECTION.doi) === NCI_RIS_PIN,
    "U: the NCI .ris entry changed byte(s) vs the pre-C22 pin:\n" + A.ris(A.NCI_CITE, A.TS_COLLECTION.doi));
  // (e) CITATIONS.txt honesty: the no-DOI line SAYS SO explicitly; the with-DOI line carries the real
  //     DOI URL and NO note. On pre-C22 code citeLine does not exist — the lazy api hook throws
  //     ReferenceError right here, which is this leg's RED.
  const lineNo = A.citeLine(A.AUSMT_SELF, null);
  ok(lineNo.indexOf("[no DOI assigned]") >= 0,
    "U: the no-DOI CITATIONS.txt line must say [no DOI assigned], got: " + lineNo);
  ok(lineNo.indexOf(PLACEHOLDER) < 0, "U: the no-DOI CITATIONS.txt line still carries the placeholder: " + lineNo);
  const lineW = A.citeLine(mAlpha.cite, mAlpha.doi);
  ok(lineW.indexOf("https://doi.org/10.99999/alpha-tf-doi") >= 0 && lineW.indexOf("no DOI assigned") < 0,
    "U: the with-DOI CITATIONS.txt line must carry the DOI URL and no note, got: " + lineW);

  console.log("INTERACTION PASSED (tree country+org toggles, UX5 collections-group-first + push-sync + collapse INVARIANT + caret click-target + gating-off + D8 tour-restore x3 exit paths, collection route+Back, Find, survey route, intro panel, tour v4 incl. Find-demo real-input+dropdown + tree-browse kalkaroo-degrade + exit hooks on Next/Back/close + drawer-open+restore, empty-state intro, year filter+hints, downloadable-only, go-to-place removal, screening(advanced) collapse, recently-added, C1b embargo access panel, PID links survey_pid/collection_pid/instrument pid + hostile-pid inert, ver-chip-in-footer, one-header-help-button, UX4 AusLAMP partition+membership+label→slug + non-member LPMT clusters + empty-set degrade + radiusForZoom/weightForZoom pins+monotone + A1 colour-identical-all-modes + tooltip type-label SWAP, still-counted-across-containers, card-desc-from-yaml + hostile-blurb-inert + fallback, dimensionality-hidden-strike/skew-kept, C20 arrow-panel+Parkinson-label+south-sign-mapping + error-bars-present/absent + no-tipper-state, C22 citation-honesty no-DOI-placeholder-free + with-DOI-kept + NCI-byte-pin + txt-no-DOI-note)");
  process.exit(0);
})().catch(e => die((e && e.stack) || String(e)));
