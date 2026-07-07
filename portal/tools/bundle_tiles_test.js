"use strict";
// C32 portal bundle-tile driver. Boots the REAL portal modules in jsdom against a synthetic MANIFEST
// and asserts surveyBundleTiles() renders/gates the three per-survey bundle tiles correctly:
//   * a served survey shows EDI-zip, EMTF-XML-zip and (flag-on) the TF MTH5 tile, the MTH5 labelled
//     "transfer functions only" (never implying time series) — the C32 labelling requirement;
//   * a survey with no bundle rows (embargoed / withheld) renders the empty withheld state ("");
//   * a hostile slug that reached a bundle url is HTML-escaped in the emitted markup (no raw < or ">
//     and no live attribute break-out) — paths are built from the sanitized slug, and escAttr is the
//     belt-and-braces at render time.
// Mirrors tools/interaction_test.js: load modules in order, stub Leaflet/JSZip, run in the window scope.
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const PORTAL = path.resolve(__dirname, "..");
const SRC = path.join(PORTAL, "src");

const stub = () => new Proxy(function () {}, {
  get: (t, p) => { if (p === "then") return undefined; if (p === Symbol.iterator) return function* () {}; return stub(); },
  apply: () => stub(), construct: () => stub(),
});

const html = fs.readFileSync(path.join(PORTAL, "index.html"), "utf8");
const dom = new JSDOM(html, { url: "http://localhost/", runScripts: "outside-only", pretendToBeVisual: true });
const win = dom.window;
win.L = stub(); win.JSZip = stub();
win.AUSMT_CONFIG = { short_name: "AusMT" };
win.fetch = () => Promise.resolve({ ok: false });

// Only the modules surveyBundleTiles() transitively needs (security -> esc/escAttr, state -> MANIFEST,
// data -> bundlesForSlug/fmtBytes, drawer -> surveyBundleTiles). Loading the full chain would also boot
// map/main which want more DOM; this focused subset is enough and faster.
const MODULES = ["contract", "security", "state", "data", "plots", "map", "filters", "drawer"];
let code = MODULES.map(f => fs.readFileSync(path.join(SRC, f + ".js"), "utf8")).join("\n");
code += "\nwindow.__api={setManifest:(m)=>{MANIFEST=m;},tiles:(slug)=>surveyBundleTiles(slug)};";

const vm = require("vm");
dom.getInternalVMContext();
vm.runInContext(code, dom.getInternalVMContext());

function die(msg) { console.error("BUNDLE TILES FAILED: " + msg); process.exit(1); }
function ok(cond, msg) { if (!cond) die(msg); }

const A = win.__api;

// --- served survey: all three bundle kinds present in the manifest ---------------------------------
A.setManifest({
  files: [], bundles: [
    { survey: "Demo", slug: "demo", format: "edi-zip", url: "bundles/demo-edi.zip", size: 20500, license: "CC-BY-4.0", n_stations: 2 },
    { survey: "Demo", slug: "demo", format: "xml-zip", url: "bundles/demo-xml.zip", size: 16489, license: "CC-BY-4.0", n_stations: 2 },
    { survey: "Demo", slug: "demo", format: "mth5", url: "bundles/demo-tf.h5", size: 276506, license: "CC-BY-4.0", n_stations: 2 },
  ],
});
const t = A.tiles("demo");
ok(t.indexOf("bundles/demo-edi.zip") >= 0, "EDI-zip tile url missing");
ok(t.indexOf("bundles/demo-xml.zip") >= 0, "EMTF-XML-zip tile url missing");
ok(t.indexOf("bundles/demo-tf.h5") >= 0, "TF MTH5 tile url missing");
ok(/EDI bundle/.test(t), "EDI-zip tile label missing");
ok(/EMTF-XML bundle/.test(t), "EMTF-XML-zip tile label missing");
// C32 core labelling requirement: the MTH5 tile must say transfer functions, never imply time series
ok(/transfer functions/i.test(t), "MTH5 tile must be labelled 'transfer functions' (C32)");
ok(t.toLowerCase().indexOf("time series") < 0, "MTH5 tile must NOT imply time series");
// size formatting rides through (fmtBytes) so the tiles show a human size
ok(/KB|MB|B/.test(t), "bundle tiles should show a formatted size");

// --- withheld survey: no bundle rows -> empty withheld state ---------------------------------------
A.setManifest({ files: [], bundles: [] });
ok(A.tiles("demo") === "", "a survey with no bundle rows must render the empty withheld state");
// a slug that simply isn't in the manifest also yields nothing
A.setManifest({ files: [], bundles: [{ survey: "Other", slug: "other", format: "edi-zip", url: "bundles/other-edi.zip", size: 1, license: "CC-BY-4.0", n_stations: 1 }] });
ok(A.tiles("demo") === "", "surveyBundleTiles must gate strictly on the matching slug");

// --- hostile slug in a bundle url must be escaped in the markup -------------------------------------
const hostile = 'x"><img src=x onerror=alert(1)>';
A.setManifest({ files: [], bundles: [
  { survey: "Evil", slug: hostile, format: "edi-zip", url: "bundles/" + hostile + "-edi.zip", size: 1, license: "CC-BY-4.0", n_stations: 1 },
] });
const ht = A.tiles(hostile);
ok(ht.length > 0, "expected a tile for the hostile-slug row (it has a url)");
// render the emitted markup into a detached node and confirm NO live <img> and NO attribute break-out
const holder = win.document.createElement("div");
holder.innerHTML = ht;
ok(holder.querySelector("img") === null, "hostile slug produced a LIVE <img> (escaping failed)");
ok(holder.querySelector("[onerror]") === null, "hostile slug produced a live onerror handler");
ok(ht.indexOf("<img") < 0, "raw <img markup leaked into the tile string (must be entity-escaped)");

console.log("BUNDLE TILES OK");
