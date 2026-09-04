"use strict";
// Portal frame-line driver (Invariant 10). Boots the REAL portal modules in jsdom and drives
// the reader-facing frame line the station drawer shows when the engine served impedances AS STORED in
// a declared acquisition frame (the engine never de-rotates under frame policy v3). It asserts:
//   * frameLineText() (PURE, DOM-free) renders the terse honest line for a non-zero declared angle,
// stays SILENT for a zero/absent angle or a null frame, and appends the "mixes declared
//     frames" clause only when the survey carries the mixed-frames note;
//   * frameLineText() NEVER emits markup (it interpolates only a validated number + fixed strings), so
//     even a hostile survey_frame_note cannot inject a tag;
//   * loadStationFrameLine() fetches the per-station station.json, injects the line via textContent,
//     and GUARDS against a stale async write (only writes if #frameline still targets this station);
//   * the resolved line is CACHED per ausmt_id, so a two-phase-boot hydration re-render (which rewrites the
//     drawer and blanks the #frameline placeholder up to three times, once per settling gate) re-injects it
//     without re-issuing the request. Each station.json case below therefore uses its OWN station id: a
//     given station's station.json does not change within a session, and the cache reads it that way.
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
win.__fetches = [];
win.fetch = (url) => {
  win.__fetches.push(String(url));
  return Promise.resolve(
    /station\.json$/.test(String(url)) && win.__fetchDoc
      ? { ok: true, json: () => Promise.resolve(win.__fetchDoc) }
      : { ok: false });
};

// Only the modules the frame line transitively needs (security -> esc/escAttr, state -> SMETA,
// data -> dataUrl, drawer -> frameLineText/loadStationFrameLine). Match bundle_tiles_test's subset.
const MODULES = ["contract", "security", "state", "data", "plots", "mapattrib", "map", "filters", "drawer"];
let code = MODULES.map(f => fs.readFileSync(path.join(SRC, f + ".js"), "utf8")).join("\n");
code += "\nwindow.__api={line:(f)=>frameLineText(f),load:(s)=>loadStationFrameLine(s),setSmeta:(m)=>{SMETA=m;},"
      + "fwb:(f)=>fileWrittenByText(f),knownWriter:(n)=>isKnownWriter(n)};";

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

// --- frameLineText: divergent tipper frame (field present ONLY when divergent) ------------------
const tipOnly = A.line({ declared_azimuth_deg: 0, tipper_declared_azimuth_deg: -60 });
ok(/Tipper served in its own declared -60° frame/.test(tipOnly),
  "case d (TROT=-60, ZROT=0) must show the tipper frame line: " + tipOnly);
ok(/declared-zero reference/.test(tipOnly),
  "the tipper-only line must place the impedances in the declared-zero reference: " + tipOnly);
const tipBoth = A.line({ declared_azimuth_deg: 8, tipper_declared_azimuth_deg: -60 });
ok(/\+8°/.test(tipBoth) && /Tipper served in its own declared -60° frame/.test(tipBoth),
  "divergent tipper beside a nonzero impedance angle must show BOTH: " + tipBoth);
const tipZero = A.line({ declared_azimuth_deg: -60, tipper_declared_azimuth_deg: 0 });
ok(/-60°/.test(tipZero) && /Tipper served in its own declared 0° frame/.test(tipZero),
  "the reverse shape (rotated Z, zero tipper) must show the 0° tipper frame: " + tipZero);
// absent field (engine omits it when equal/undeclared) -> no tipper wording
ok(!/Tipper/.test(A.line({ declared_azimuth_deg: 8 })),
  "no tipper wording without the divergence field");
// a non-numeric hostile value in the tipper field is ignored (validated number only)
ok(!/Tipper/.test(A.line({ declared_azimuth_deg: 8, tipper_declared_azimuth_deg: "<img>" })),
  "a non-numeric tipper field must be ignored, never rendered");

// --- frameLineText: mixed-frames note ---------------------------------------------------------
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

// --- fileWrittenByText: the lineage's file-WRITER cell (PURE) --------------------------------------
// The EDI HEAD's program stamp must NOT be published as "Processing software": Geotools, WinGLink and
// MTpy only WROTE the file, and a reader told otherwise reads them as having processed the data. The
// writer has its own row, and a known exporter is annotated so the distinction is legible.
ok(A.fwb({ name: "Geotools", version: "4.0.5.12583" }) === "Geotools 4.0.5.12583 (database/file export)",
  "a known writer must render with its version and the export annotation: " + A.fwb({ name: "Geotools", version: "4.0.5.12583" }));
ok(A.fwb({ name: "WINGLINK EDI", version: "1.0.22" }).indexOf("(database/file export)") > 0,
  "WinGLink is a known writer and must be annotated as one");
ok(A.fwb({ name: "MTpy" }) === "MTpy (database/file export)",
  "a writer with no version must render bare, with no invented version: " + A.fwb({ name: "MTpy" }));
// a program that is NOT a known exporter carries no annotation (it may well have done the processing)
ok(A.fwb({ name: "EMpower", version: "v1.54.2.5" }) === "EMpower v1.54.2.5",
  "a non-writer program must not be annotated as a database export: " + A.fwb({ name: "EMpower", version: "v1.54.2.5" }));
// absence is stated as absence, never guessed
["not stated in EDI"].forEach(exp => ok(A.fwb(null) === exp && A.fwb({}) === exp && A.fwb({ name: "" }) === exp,
  "a file that names no writer must say so, got: " + A.fwb({})));
ok(A.knownWriter("geotools 4.0") && !A.knownWriter("LEMIMT") && !A.knownWriter(""),
  "the client-side KNOWN_WRITERS set must mirror the engine's");

// --- loadStationFrameLine: fetch station.json, inject via textContent, guard against stale writes ---
// The SAME fetch resolves the lineage writer cell, so the placeholder rides along in this fixture and the
// caching / staleness rules below are asserted for BOTH cells off ONE request.
function makeFrameline(ausmt) {
  const d = win.document.getElementById("drawer") || win.document.body;
  d.innerHTML = '<div id="frameline" data-ausmt="' + ausmt + '"></div>'
              + '<span id="lineage-fwb" data-ausmt="' + ausmt + '">loading…</span>';
  return win.document.getElementById("frameline");
}
const fwbCell = () => win.document.getElementById("lineage-fwb").textContent;
A.setSmeta({ "Demo Survey": { slug: "demo" } });
const s = { i: 0, id: "A01", survey: "Demo Survey", slug: "demo", ausmt_id: "au.demo.A01" };

win.__fetchDoc = { frame: { declared_azimuth_deg: -60, frame_served: "declared-azimuth" },
                   processing: { software: "Birrp 5.0", file_written_by: { name: "MTpy", version: null } } };
let el = makeFrameline(s.ausmt_id);
A.load(s).then(function () {
  ok(/-60°/.test(el.textContent), "loadStationFrameLine did not inject the -60° line: '" + el.textContent + "'");
  ok(el.querySelector === undefined || win.document.getElementById("frameline").querySelector("img") === null,
    "the injected line must be textContent (no live <img>)");
  ok(fwbCell() === "MTpy (database/file export)",
    "the same fetch must fill the lineage writer cell, got: '" + fwbCell() + "'");

  // staleness guard: the drawer has moved on to another station -> the async write must NOT land
  win.__fetchDoc = { frame: { declared_azimuth_deg: 30 },
                     processing: { file_written_by: { name: "Geotools", version: "9.9" } } };
  const stale = { i: 1, id: "B02", survey: "Demo Survey", slug: "demo", ausmt_id: "au.demo.B02" };
  makeFrameline("au.demo.OTHER");                      // frameline now targets a DIFFERENT station
  A.load(stale).then(function () {
    const fl = win.document.getElementById("frameline");
    ok(fl.textContent === "", "a stale async fetch overwrote the current drawer's frame line: '" + fl.textContent + "'");
    ok(fwbCell() === "loading…",
      "a stale async fetch overwrote another station's writer cell: '" + fwbCell() + "'");

    // a withheld / missing station.json (fetch !ok) yields no line, no throw. Its OWN station id, so it
    // exercises the not-ok path rather than reading back the -60° line cached above.
    win.__fetchDoc = null;
    const missing = { i: 2, id: "C03", survey: "Demo Survey", slug: "demo", ausmt_id: "au.demo.C03" };
    const el3 = makeFrameline(missing.ausmt_id);
    A.load(missing).then(function () {
      ok(el3.textContent === "", "a missing station.json must leave the frame line empty");
      // ...but the writer cell must NOT stay a loading state forever: an unreadable station.json is
      // reported as one. A permanent "loading…" is the same lie the row was added to remove.
      ok(fwbCell() === "could not be loaded",
        "a missing station.json must resolve the writer cell to an honest failure, got: '" + fwbCell() + "'");

      // Two-phase boot: a hydration re-render calls this again for the SAME station after blanking the
      // placeholder. The line must come BACK (the reader must not lose it) with NO second request.
      win.__fetchDoc = { frame: { declared_azimuth_deg: 99 },
                         processing: { file_written_by: { name: "WINGLINK EDI", version: "1.0.22" } } };
      const el4 = makeFrameline(s.ausmt_id);
      const before = win.__fetches.length;
      A.load(s).then(function () {
        ok(/-60°/.test(el4.textContent),
          "a re-render must re-inject the resolved frame line, got: '" + el4.textContent + "'");
        ok(fwbCell() === "MTpy (database/file export)",
          "a re-render must re-inject the CACHED writer cell (not a re-fetch), got: '" + fwbCell() + "'");
        ok(win.__fetches.length === before,
          "a re-render must not re-issue station.json; issued " + (win.__fetches.length - before) + " extra");
        // and a station whose station.json was MISSING is not re-requested either (the no-line outcome is
        // cached too, so three settling gates cannot become three 404s).
        const before2 = win.__fetches.length;
        const el5 = makeFrameline(missing.ausmt_id);
        A.load(missing).then(function () {
          ok(el5.textContent === "", "the cached no-line outcome must stay a no-line outcome");
          ok(win.__fetches.length === before2,
            "a station with no station.json must not be re-requested on a re-render; issued " +
            (win.__fetches.length - before2) + " extra");
          console.log("FRAME LINE OK");
        }).catch(function (e) { die("cached-missing path threw: " + e); });
      }).catch(function (e) { die("re-render path threw: " + e); });
    }).catch(function (e) { die("missing-station.json path threw: " + e); });
  });
}).catch(function (e) { die("loadStationFrameLine threw: " + e); });
