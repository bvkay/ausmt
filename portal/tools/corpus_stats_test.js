"use strict";
// Behavioural driver for the About header's corpus-totals block. Loads the REAL
// about.html into jsdom, runs the REAL corpus-stats.js against a stubbed fetch, and asserts the three
// outcomes the block must have. Mirrors tools/bundle_tiles_test.js (same jsdom + vm idiom).
//
//   1. published corpus  -> the block is revealed and states the catalogue's own totals;
//   2. failed fetch      -> the block stays hidden (file://, an unpublished deployment);
//   3. empty corpus      -> the block stays hidden (an empty build must not read "0 stations").
//
// (2) and (3) are the honesty half: this block sits in the page chrome, so a wrong or placeholder number
// there would be read as fact on every visit.
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const { JSDOM } = require("jsdom");

const PORTAL = path.resolve(__dirname, "..");
const SCRIPT = fs.readFileSync(path.join(PORTAL, "corpus-stats.js"), "utf8");
const HTML = fs.readFileSync(path.join(PORTAL, "about.html"), "utf8");

function die(msg) { console.error("CORPUS STATS FAILED: " + msg); process.exit(1); }
function ok(cond, msg) { if (!cond) die(msg); }

// One run: build a fresh DOM from about.html, install `fetchImpl`, execute corpus-stats.js, and resolve
// once the script's promise chain has settled.
function run(fetchImpl) {
  const dom = new JSDOM(HTML, { url: "http://localhost/", runScripts: "outside-only" });
  const win = dom.window;
  win.AUSMT_CONFIG = { data_base_url: "" };
  win.fetch = fetchImpl;
  vm.runInContext(SCRIPT, dom.getInternalVMContext());
  // Two microtask drains: Promise.all -> .then chain inside the script.
  return Promise.resolve().then(() => Promise.resolve()).then(() => Promise.resolve()).then(() => {
    const el = win.document.getElementById("corpusCounts");
    ok(el !== null, "about.html is missing the #corpusCounts block");
    return { hidden: el.hidden, text: el.textContent.replace(/\s+/g, " ").trim() };
  });
}

function jsonOk(body) { return Promise.resolve({ ok: true, json: () => Promise.resolve(body) }); }

// The live corpus shape: catalogue.json is an ARRAY of positional station rows, surveys.json an OBJECT
// keyed by survey label. 1418 stations / 21 surveys is what the deployed build actually serves.
const stations = new Array(1418).fill(0).map((_, i) => [i]);
const surveys = {};
for (let i = 0; i < 21; i++) { surveys["Survey " + i] = { slug: "s" + i }; }

const served = (u) => (/catalogue\.json$/.test(u) ? jsonOk(stations)
  : /surveys\.json$/.test(u) ? jsonOk(surveys)
    : Promise.resolve({ ok: false, status: 404 }));

(async () => {
  // 1. published corpus -> revealed, with the catalogue's own numbers
  let r = await run(served);
  ok(r.hidden === false, "a published corpus must REVEAL the totals block; it stayed hidden");
  ok(/1,418 stations/.test(r.text), "expected '1,418 stations' (locale-grouped), got: " + r.text);
  ok(/21 surveys/.test(r.text), "expected '21 surveys', got: " + r.text);

  // 2. fetch fails (file:// or unpublished data) -> stays hidden, no partial text
  r = await run(() => Promise.reject(new Error("blocked")));
  ok(r.hidden === true, "a failed fetch must leave the block hidden; it was revealed: " + r.text);
  r = await run(() => Promise.resolve({ ok: false, status: 404 }));
  ok(r.hidden === true, "a 404 must leave the block hidden; it was revealed: " + r.text);

  // 3. empty build -> stays hidden rather than claiming "0 stations · 0 surveys"
  r = await run((u) => (/catalogue\.json$/.test(u) ? jsonOk([]) : jsonOk({})));
  ok(r.hidden === true, "an empty corpus must leave the block hidden; it was revealed: " + r.text);

  console.log("CORPUS STATS OK");
})().catch((e) => die((e && e.stack) || String(e)));
