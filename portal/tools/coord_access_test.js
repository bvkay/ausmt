"use strict";
// C42 lane 3 — portal handles masked coordinates (Invariant 10; every pin states its failure
// criterion). Boots the REAL portal modules in jsdom over ENGINE-BUILT artifacts
// (tests/fixtures/c42/, produced by tools/gen_c42_fixtures.py — never hand-typed rows) and drives
// the null-coord (withheld) render/selection/drawer paths plus the honest-counts invariant.
//
// AUDITED GROUND TRUTH (real build, 2026-07-12): the engine emits NO explicit coordinate-access
// policy field on any portal-consumed artifact. The ONLY signals are the masked VALUES:
//   * withheld    -> catalogue lat/lon = null   (DETECTABLE)
//   * generalised -> catalogue lat/lon = the 0.1deg cell, a silently-rounded number (NO marker;
//                    indistinguishable from an exact station that happens to sit on a 0.1deg grid
//                    point). edi_available=0 is shared with embargo/licence gating, so it is NOT a
//                    generalised signal.
// The portal therefore keys off `lat==null || lon==null` for the withheld path. It renders the
// generalised value VERBATIM (the record's rule: no client-side re-rounding / re-derivation of
// precision) — a generalised BADGE is out of reach without an engine policy field (see the lane
// report; that piece is escalated, not implemented).
//
// Pins:
//  1 (null-coords render): buildMarkers/partitionMarkers produce NO marker for a withheld station and
//    never emit a NaN/(null,null) point. RED against pre-fix: a phantom [null,null] circleMarker + a
//    null point in fitBounds.
//  2 (drawer): withheld -> the "coordinates withheld (custodian policy)" line renders, with no
//    "null"/"undefined" and no coordinate value; generalised/exact -> the coordinate value renders.
//  3 (leak): the rendered withheld drawer DOM contains no lat/lon-like decimal pair.
//  4 (selection): inShapes(withheld) is false (excluded from spatial selection — it has no position)
//    yet the withheld station is findable by id/text and stays in ST.
//  5 (counts): the survey station count includes the withheld station.
// Mirrors tools/frame_line_test.js: load modules in order, stub Leaflet, run in the window scope.
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const { JSDOM } = require("jsdom");

const PORTAL = path.resolve(__dirname, "..");
const SRC = path.join(PORTAL, "src");
const FIX = path.join(PORTAL, "tests", "fixtures", "c42");

function readFix(name) { return JSON.parse(fs.readFileSync(path.join(FIX, name), "utf8")); }

// ---- recording Leaflet stub -----------------------------------------------------------------------
// A blanket chainable stub for everything, with two recorders: circleMarker([lat,lon]) and the map's
// fitBounds(points). fgroup() returns an INDEPENDENT layer container per call (so cluster.clearLayers()
// never wipes the drawn selection layer). The map object is chainable-by-default but has real
// fitBounds/getZoom so buildMarkers records its point set and curZoom() reads a finite number.
function chain() {
  return new Proxy(function () {}, {
    get: (t, p) => { if (p === "then") return undefined; if (p === Symbol.iterator) return function* () {}; return chain(); },
    apply: () => chain(), construct: () => chain(),
  });
}
function makeL() {
  const calls = { circleMarker: [], fitBounds: [] };
  function fgroup() {
    const layers = [];
    const g = {
      addTo: () => g, addLayer: (l) => { layers.push(l); return g; },
      addLayers: (ls) => { (ls || []).forEach((l) => layers.push(l)); return g; },
      clearLayers: () => { layers.length = 0; return g; },
      eachLayer: (cb) => { layers.slice().forEach(cb); return g; },
      on: () => g, removeLayer: () => g, getLatLngs: () => [], _layers: layers,
    };
    return g;
  }
  const mapObj = new Proxy({
    fitBounds: (pts) => { calls.fitBounds.push(pts); return mapObj; },
    getZoom: () => 4, addLayer: () => chain(), addControl: () => chain(), on: () => chain(),
    attributionControl: { addAttribution: () => {} },
  }, { get: (o, p) => (p in o ? o[p] : () => chain()) });
  const L = new Proxy(function () {}, {
    get: (t, p) => {
      if (p === "then") return undefined;
      if (p === "map") return () => mapObj;
      if (p === "circleMarker") return (latlng) => { calls.circleMarker.push(latlng); return chain(); };
      // a normal function (NOT an arrow) so `new L.FeatureGroup()` works as well as `L.featureGroup()`.
      if (p === "FeatureGroup" || p === "featureGroup" || p === "layerGroup" || p === "markerClusterGroup") return function () { return fgroup(); };
      return chain();
    },
    apply: () => chain(), construct: () => chain(),
  });
  return { L, calls };
}

const html = fs.readFileSync(path.join(PORTAL, "index.html"), "utf8");
const dom = new JSDOM(html, { url: "http://localhost/", runScripts: "outside-only", pretendToBeVisual: true });
const win = dom.window;
const { L, calls } = makeL();
win.L = L; win.JSZip = chain();
win.AUSMT_CONFIG = { short_name: "AusMT" };
// fetch serves the per-station station.json fixtures (loadStationFrameLine); anything else 404s.
win.fetch = (url) => {
  const m = /products\/([^?]+?)\/station\.json/.exec(String(url));
  if (m) {
    const fp = path.join(FIX, "products", ...m[1].split("/"), "station.json");
    if (fs.existsSync(fp)) return Promise.resolve({ ok: true, json: () => Promise.resolve(JSON.parse(fs.readFileSync(fp, "utf8"))) });
  }
  return Promise.resolve({ ok: false });
};

const MODULES = ["contract", "security", "state", "data", "plots", "map", "filters", "drawer", "exports", "main"];
let code = MODULES.map((f) => fs.readFileSync(path.join(SRC, f + ".js"), "utf8")).join("\n");
code += "\nwindow.__api={" +
  "setup:(c,t,s,sv,coll)=>{CAT=c;TFD=t;SCI=s;SMETA=sv;COLL=coll;MANIFEST=null;buildState();buildTree();}," +
  "idxOf:(id)=>ST.findIndex(s=>s.id===id)," +
  "buildMarkersRun:()=>{buildMarkers();return {marker:ST.map(s=>({id:s.id,has:s.marker!==undefined}))};}," +
  // driveRefresh runs the REAL refresh() (which routes partitionMarkers(visible.filter(hasPosition)) into the
  // two Leaflet layers) and reports what actually reached those layers — c+l markers, any undefined (an
  // addLayers(undefined) crash), and the `visible` ids (counts must still include the withheld station).
  "driveRefresh:()=>{buildMarkers();refresh();const c=(cluster._layers||[]),l=(lpmtLayer._layers||[]);" +
  "return {routedCount:c.length+l.length,undef:c.concat(l).filter(m=>m===undefined).length,vis:visible.map(s=>s.id)};}," +
  "footprints:()=>{buildFootprints();return true;}," +
  "recolorRun:()=>{recolor();return true;}," +
  "openDrawer:(i)=>{try{openStation(i);return {ok:true,html:document.getElementById('drawer').innerHTML};}catch(e){return {ok:false,err:String(e&&e.stack||e)};}}," +
  "addWorldShape:()=>{drawn.addLayer({getLatLngs:()=>[[{lat:-89,lng:-179},{lat:-89,lng:179},{lat:89,lng:179},{lat:89,lng:-179}]]});}," +
  "inShapesOf:(i)=>inShapes(ST[i])," +
  "findByText:(q)=>ST.filter(s=>s.id.toLowerCase().includes(q)||(s.file||'').toLowerCase().includes(q)).map(s=>s.id)," +
  "surveyCount:(sv)=>ST.filter(s=>s.survey===sv).length," +
  "total:()=>ST.length" +
  "};";

vm.runInContext(code, dom.getInternalVMContext());

let failures = 0;
function ok(cond, msg) { if (!cond) { console.error("  FAIL: " + msg); failures++; } }

const A = win.__api;
A.setup(readFix("catalogue.json"), readFix("tf.json"), readFix("sci.json"), readFix("surveys.json"), readFix("collections.json"));
const iEx = A.idxOf("EXACTONE"), iGen = A.idxOf("GENFIVE"), iHid = A.idxOf("HIDENINE");
ok(iEx >= 0 && iGen >= 0 && iHid >= 0, "all three fixture stations must load (precondition)");

// --- Pin 1: null-coords render (no phantom marker, no NaN point) ------------------------------------
const bm = A.buildMarkersRun();
const hidMarker = bm.marker.find((m) => m.id === "HIDENINE");
ok(hidMarker && hidMarker.has === false, "PIN1: withheld station must get NO marker (has=" + (hidMarker && hidMarker.has) + ")");
ok(bm.marker.find((m) => m.id === "EXACTONE").has === true, "PIN1: exact station must still get a marker");
ok(bm.marker.find((m) => m.id === "GENFIVE").has === true, "PIN1: generalised station must still get a marker");
const badCM = calls.circleMarker.filter((ll) => !ll || ll[0] == null || ll[1] == null || !isFinite(ll[0]) || !isFinite(ll[1]));
ok(badCM.length === 0, "PIN1: no circleMarker built at a null/NaN position (phantom markers: " + JSON.stringify(badCM) + ")");
const badFit = calls.fitBounds.some((pts) => Array.isArray(pts) && pts.some((p) => Array.isArray(p) && (p[0] == null || p[1] == null || !isFinite(p[0]) || !isFinite(p[1]))));
ok(!badFit, "PIN1: fitBounds must not receive a null/NaN point (NaN bounds)");

// --- Pin 1b: the REAL refresh() routes only positioned stations; withheld stays counted, off the map --
const dr = A.driveRefresh();
ok(dr.undef === 0, "PIN1b: refresh must not route an undefined marker into addLayers (crash), got " + dr.undef);
ok(dr.routedCount === 2, "PIN1b: refresh routes ONLY the 2 positioned stations to the map (withheld excluded), got " + dr.routedCount + " (visible: " + JSON.stringify(dr.vis) + ")");
ok(dr.vis.indexOf("HIDENINE") >= 0 && dr.vis.length === 3, "PIN1b: the withheld station stays in `visible` (counted), just not on the map: " + JSON.stringify(dr.vis));

// footprints/recolor must not throw over a null-coord corpus
ok((() => { try { A.footprints(); A.recolorRun(); return true; } catch (e) { console.error("  (footprints/recolor threw) " + e); return false; } })(),
  "PIN1c: buildFootprints/recolor must not throw over a withheld station");

// --- Pin 2 + 3: drawer render + leak -----------------------------------------------------------------
const dHid = A.openDrawer(iHid);
ok(dHid.ok, "PIN2/3: opening the withheld drawer must not throw: " + dHid.err);
if (dHid.ok) {
  ok(/coordinates withheld \(custodian policy\)/i.test(dHid.html),
    "PIN2: withheld drawer must show the 'coordinates withheld (custodian policy)' line");
  // no fabricated null/undefined in the coordinate context
  ok(!/null,\s*null/i.test(dHid.html) && !/undefined/.test(dHid.html),
    "PIN2: withheld drawer must not print null/undefined coordinates");
  // LEAK: no lat/lon-like decimal pair "-dd.dddddd, ddd.dddddd" and no true coord substrings
  ok(!/-?\d{1,3}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,}/.test(dHid.html),
    "PIN3: withheld drawer must contain no lat/lon-like decimal pair");
  ok(dHid.html.indexOf("33.5555") < 0 && dHid.html.indexOf("137.5555") < 0,
    "PIN3: the withheld station's TRUE coordinates must appear nowhere in the DOM");
}
const dGen = A.openDrawer(iGen);
ok(dGen.ok, "PIN2: opening the generalised drawer must not throw: " + dGen.err);
if (dGen.ok) {
  // the generalised value is rendered VERBATIM (0.1deg cell), never re-rounded or badged-as-exact
  ok(/-32\.9(0*)?\s*,\s*136\.9/.test(dGen.html), "PIN2: generalised drawer must render the masked 0.1deg value verbatim");
  ok(!/coordinates withheld/i.test(dGen.html), "PIN2: a generalised station must not show the withheld line");
}
const dEx = A.openDrawer(iEx);
ok(dEx.ok, "PIN2: opening the exact drawer must not throw: " + dEx.err);
if (dEx.ok) ok(/-31\.234567\s*,\s*135\.234567/.test(dEx.html), "PIN2: exact drawer must render the verbatim coordinates");

// --- Pin 4: spatial selection excludes withheld, text search still finds it -------------------------
A.addWorldShape();  // a polygon covering the whole globe (incl. the (0,0) phantom point)
ok(A.inShapesOf(iEx) === true, "PIN4: exact station inside a world polygon must be selected (else vacuous)");
ok(A.inShapesOf(iGen) === true, "PIN4: generalised station inside a world polygon must be selected");
ok(A.inShapesOf(iHid) === false, "PIN4: withheld station must be EXCLUDED from spatial selection (no position)");
ok(A.findByText("hidenine").includes("HIDENINE"), "PIN4: withheld station must remain findable by id/text");

// --- Pin 5: counts stay honest -----------------------------------------------------------------------
ok(A.surveyCount("Coord Access Sweep Survey") === 3, "PIN5: survey station count must include the withheld station (=3)");
ok(A.total() === 3, "PIN5: total station count must include the withheld station");

if (failures) { console.error("COORD ACCESS FAILED: " + failures + " pin(s)"); process.exit(1); }
console.log("COORD ACCESS OK");
