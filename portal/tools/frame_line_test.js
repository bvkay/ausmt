"use strict";
// C25-V3 portal frame-line driver (Invariant 10). Boots the REAL portal modules in jsdom and drives
// the reader-facing frame line the station drawer shows when the engine served impedances AS STORED in
// a declared acquisition frame (the engine never de-rotates under frame policy v3). It asserts:
//   * frameLineText() (PURE, DOM-free) renders the terse honest line for a non-zero declared angle,
//     stays SILENT for a zero/absent angle or a null frame, and appends the V3-B "mixes declared
//     frames" clause only when the survey carries the mixed-frames note;
//   * frameLineText() NEVER emits markup (it interpolates only a validated number + fixed strings), so
//     even a hostile survey_frame_note cannot inject a tag;
//   * loadStationFrameLine() fetches the per-station station.json, injects the line via textContent,
//     and GUARDS against a stale async write (only writes if #frameline still targets this station).
// Mirrors tools/bundle_tiles_test.js: load modules in order, stub Leaflet/JSZip, run in the window scope.
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
// Default fetch: the fixture station.json the loadStationFrameLine() integration expects. A specific
// test overrides win.__fetchDoc to change the served frame; an unresolvable url yields {ok:false}.
win.__fetchDoc = { frame: { declared_azimuth_deg: -60, frame_served: "declared-azimuth" } };
win.fetch = (url) => Promise.resolve(
  /station\.json$/.test(String(url)) && win.__fetchDoc
    ? { ok: true, json: () => Promise.resolve(win.__fetchDoc) }
    : { ok: false });

// Only the modules the frame line transitively needs (security -> esc/escAttr, state -> SMETA,
// data -> dataUrl, drawer -> frameLineText/loadStationFrameLine). Match bundle_tiles_test's subset.
const MODULES = ["contract", "security", "state", "data", "plots", "map", "filters", "drawer"];
let code = MODULES.map(f => fs.readFileSync(path.join(SRC, f + ".js"), "utf8")).join("\n");
code += "\nwindow.__api={line:(f)=>frameLineText(f),load:(s)=>loadStationFrameLine(s),setSmeta:(m)=>{SMETA=m;}};";

const vm = require("vm");
dom.getInternalVMContext();
vm.runInContext(code, dom.getInternalVMContext());

function die(msg) { console.error("FRAME LINE FAILED: " + msg); process.exit(1); }
function ok(cond, msg) { if (!cond) die(msg); }

const A = win.__api;

// --- frameLineText: non-zero declared angle -> the terse honest line -------------------------------
const neg = A.line({ declared_azimuth_deg: -60, frame_served: "declared-azimuth" });
ok(/-60°/.test(neg), "declared -60° must appear in the frame line: " + neg);
ok(/acquisition frame/.test(neg) && /as stored/.test(neg) && /not rotated/.test(neg),
  "the -60° line must say it is served as stored, not rotated: " + neg);
const pos = A.line({ declared_azimuth_deg: 8 });
ok(/\+8°/.test(pos), "declared +8° must render with a leading sign: " + pos);
// a fractional angle rounds to at most 1 dp
ok(/\+8\.1°/.test(A.line({ declared_azimuth_deg: 8.123 })), "angle should render at 1 dp");

// --- frameLineText: zero / absent / null -> SILENT (no line) ---------------------------------------
ok(A.line({ declared_azimuth_deg: 0 }) === "", "a zero declared angle must produce NO line");
ok(A.line({ declared_azimuth_deg: 0.001 }) === "", "a ~0 declared angle must produce NO line");
ok(A.line({}) === "", "a frame with no declared angle and no mixed note must produce NO line");
ok(A.line(null) === "", "a null frame must produce NO line");
ok(A.line({ frame_served: "declared-zero", declared_azimuth_deg: 0 }) === "", "declared-zero => no line");

// --- frameLineText: V3-B mixed-frames note ---------------------------------------------------------
const MIX = "frame: mixed declared frames across stations: 8°…20° — each station is served in its own frame";
const mixed0 = A.line({ declared_azimuth_deg: 0, survey_frame_note: MIX });
ok(/mixes declared acquisition frames across stations/.test(mixed0),
  "a mixed survey with a zero own-angle must still show the mixed-frames line: " + mixed0);
const mixed20 = A.line({ declared_azimuth_deg: 20, survey_frame_note: MIX });
ok(/\+20°/.test(mixed20) && /mixes declared frames across stations/.test(mixed20),
  "a mixed survey with a non-zero own-angle shows BOTH its angle and the mixed clause: " + mixed20);

// --- frameLineText never emits markup (no injection surface; belt-and-braces textContent downstream)
const hostile = 'x"><img src=x onerror=alert(1)>';
for (const f of [{ declared_azimuth_deg: 0, survey_frame_note: hostile },
                 { declared_azimuth_deg: 30, survey_frame_note: hostile }]) {
  const out = A.line(f);
  ok(out.indexOf("<") < 0, "frameLineText leaked markup for a hostile survey_frame_note: " + out);
}

// --- loadStationFrameLine: fetch station.json, inject via textContent, guard against stale writes ---
function makeFrameline(ausmt) {
  const d = win.document.getElementById("drawer") || win.document.body;
  d.innerHTML = '<div id="frameline" data-ausmt="' + ausmt + '"></div>';
  return win.document.getElementById("frameline");
}
A.setSmeta({ "Demo Survey": { slug: "demo" } });
const s = { i: 0, id: "A01", survey: "Demo Survey", slug: "demo", ausmt_id: "au.demo.A01" };

win.__fetchDoc = { frame: { declared_azimuth_deg: -60, frame_served: "declared-azimuth" } };
let el = makeFrameline(s.ausmt_id);
A.load(s).then(function () {
  ok(/-60°/.test(el.textContent), "loadStationFrameLine did not inject the -60° line: '" + el.textContent + "'");
  ok(el.querySelector === undefined || win.document.getElementById("frameline").querySelector("img") === null,
    "the injected line must be textContent (no live <img>)");

  // staleness guard: the drawer has moved on to another station -> the async write must NOT land
  win.__fetchDoc = { frame: { declared_azimuth_deg: 30 } };
  const stale = { i: 1, id: "B02", survey: "Demo Survey", slug: "demo", ausmt_id: "au.demo.B02" };
  makeFrameline("au.demo.OTHER");                      // frameline now targets a DIFFERENT station
  A.load(stale).then(function () {
    const fl = win.document.getElementById("frameline");
    ok(fl.textContent === "", "a stale async fetch overwrote the current drawer's frame line: '" + fl.textContent + "'");

    // a withheld / missing station.json (fetch !ok) yields no line, no throw
    win.__fetchDoc = null;
    const el3 = makeFrameline(s.ausmt_id);
    A.load(s).then(function () {
      ok(el3.textContent === "", "a missing station.json must leave the frame line empty");
      console.log("FRAME LINE OK");
    }).catch(function (e) { die("missing-station.json path threw: " + e); });
  });
}).catch(function (e) { die("loadStationFrameLine threw: " + e); });
