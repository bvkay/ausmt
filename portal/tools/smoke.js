// Headless smoke test for the static portal: concatenates the ES modules, stubs the DOM / Leaflet /
// JSZip / fetch, boots the app against a data directory, and exercises the main code paths. Works for
// BOTH an empty portal (asserts the empty-state path runs cleanly) and a populated one (asserts
// station/survey/collection paths, data-agnostically). Exits non-zero on any runtime error.
//
//   node tools/smoke.js [dataDir]      # dataDir defaults to ../data relative to this file
//
// Used by tests/test_empty_portal_smoke.py and handy for manual checks.
const fs = require("fs"), vm = require("vm"), path = require("path");

const TOOLS = __dirname;
const SRC = path.resolve(TOOLS, "..", "src");
const DATA = path.resolve(process.argv[2] || path.join(TOOLS, "..", "data"));

const MODULES = ["contract", "security", "state", "data", "plots", "map", "filters", "drawer", "exports", "main", "tour"];
let code = MODULES.map(f => fs.readFileSync(path.join(SRC, f + ".js"), "utf8")).join("\n");
code += "\nglobalThis.__api={boot,openStation,openSurvey,setView,refresh,routeFromHash," +
  "showEmptyState,portalIsEmpty,nST:()=>ST.length,firstSurvey:()=>surveys[0],firstId:()=>ST[0]&&ST[0].id," +
  // station0 exposes the buildState() fields derived THROUGH the contract maps (r[C.*], sc[SC.*]) so a test
  // can assert their VALUES against the source data — catching a wrong call-site index, not just a crash.
  "station0:()=>ST[0]&&{id:ST[0].id,lat:ST[0].lat,lon:ST[0].lon,type:ST[0].type,ausmt_id:ST[0].ausmt_id,q:ST[0].q,dim:ST[0].dim}," +
  // export0 = the CSV row exports.js builds for ST[0], so the test can value-bind the export call site's
  // sc[SC.qb/rr/sw] derefs (qb/rr/sw are covered by NOTHING else).
  "export0:()=>ST[0]?csvRows([ST[0]])[1]:null," +
  // C12: buildIdText() is a pure function of BUILDID (set by boot() from build.json) — exposing it
  // lets a test assert the footer VALUE binding without a real DOM (getElementById stubs below return
  // a fresh throwaway object per call, so nothing written to el.textContent would be observable).
  "buildIdText:()=>buildIdText()};";

const stub = () => new Proxy(function () {}, {
  get: (t, p) => { if (p === "then") return undefined; if (p === Symbol.iterator) return function* () {}; return stub(); },
  apply: () => stub(), construct: () => stub(),
});
function elStub() {
  const t = {
    value: "", checked: true, textContent: "", innerHTML: "", scrollTop: 0, disabled: false,
    style: {}, dataset: {}, children: [],
    classList: { toggle() {}, add() {}, remove() {}, contains() { return false; } },
    appendChild() {}, addEventListener() {}, querySelectorAll() { return []; },
    querySelector() { return null; }, closest() { return null; },
    getAttribute() { return null; }, getBoundingClientRect() { return { left: 0 }; },
    scrollIntoView() {}, click() {}, onclick: null,
  };
  return new Proxy(t, { get: (o, p) => (p in o ? o[p] : stub()), set: (o, p, v) => { o[p] = v; return true; } });
}

const files = ["catalogue", "tf", "sci", "surveys", "build_provenance", "collections", "build"];
const data = {};
files.forEach(k => { try { data["data/" + k + ".json"] = JSON.parse(fs.readFileSync(path.join(DATA, k + ".json"))); } catch (e) {} });

// Minimal localStorage stub — main.js's intro-panel dismiss state (ausmt_intro_dismissed) reads/writes
// it; without this it still degrades safely (try/catch around every call) but a stub lets the smoke
// path actually exercise the get/set round-trip instead of only the catch branch.
function localStorageStub() {
  const store = {};
  return { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; }, clear: () => { Object.keys(store).forEach(k => delete store[k]); } };
}
const ctx = {
  document: {
    getElementById: () => elStub(), createElement: () => elStub(), addEventListener() {},
    body: elStub(), querySelector: () => null,
    querySelectorAll: sel => (/typeBoxes/.test(sel) ? [{ value: "LPMT" }, { value: "BBMT" }, { value: "AMT" }, { value: "GDS" }, { value: "other" }] : []),
  },
  window: { addEventListener() {}, open() {}, innerWidth: 1200, AUSMT_CONFIG: { short_name: "AusMT" } },
  location: { hash: "", pathname: "/", search: "" }, history: { replaceState() {} },
  navigator: { clipboard: { writeText: () => Promise.resolve() } },
  localStorage: localStorageStub(),
  L: stub(), JSZip: stub(),
  fetch: url => Promise.resolve(data[url] ? { ok: true, json: () => Promise.resolve(data[url]) } : { ok: false }),
  URL: { createObjectURL: () => "x", revokeObjectURL() {} }, Blob: function () {},
  setTimeout: f => { try { f(); } catch (e) {} return 0; }, clearTimeout() {},
  console, Math, JSON, Date, Promise, encodeURIComponent, decodeURIComponent,
  parseInt, parseFloat, isFinite, Set, Array, Object, String, Number,
};
ctx.globalThis = ctx; ctx.self = ctx; vm.createContext(ctx); vm.runInContext(code, ctx);

(async () => {
  const A = ctx.__api;
  try {
    await A.boot();
    // C12: printed regardless of empty/populated (build.json is independent of station count) so a
    // wrapper test can assert the footer's build-id VALUE binding either way.
    console.log("BUILDID_TEXT " + JSON.stringify(A.buildIdText()));
    if (A.nST() === 0) {
      if (!A.portalIsEmpty()) throw new Error("portalIsEmpty() false on empty data");
      A.showEmptyState(); A.setView("surveys"); A.setView("map");
      console.log("EMPTY portal: ST=0, empty-state rendered, views toggle, no NaN/crash");
    } else {
      A.openStation(0); A.openStation(A.nST() - 1);
      A.openSurvey(A.firstSurvey()); A.setView("surveys"); A.setView("map"); A.refresh();
      ctx.location.hash = "#/station/" + A.firstId(); A.routeFromHash();
      console.log("POPULATED portal: ST=" + A.nST() + ", station/survey/route paths OK");
      console.log("STATION0 " + JSON.stringify(A.station0()));
      console.log("EXPORT0 " + JSON.stringify(A.export0()));
    }
  } catch (e) { console.error("RUNTIME ERROR:", (e && e.stack) || e); process.exit(1); }
  console.log("SMOKE PASSED");
})();
