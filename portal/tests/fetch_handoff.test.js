// Node test: the per-survey hand-off document and the terminal commands, pinned to the SHARED
// fixture (contract/fetch_handoff.json) the engine pins its emitter against.
//
// Two trees write the same document. The SPA builds it in the browser (exports.js tsHandoffDocument)
// and the engine writes it at build time (pages/fetch/<slug>.json). The composers that turn its rows
// into wget and curl commands now live in fetchcmd.js, a module with no SPA state, so the survey
// page can load them beside the SPA. This test holds all of that to one fixture:
//   * the SPA's own tsHandoffDocument over the fixture's ts_access equals the fixture document;
//   * the composers over the fixture's rows give the fixture's commands (all levels, one level);
//   * state.js TS_COLLECTION and exports.js TS_HANDOFF_NOTE are the fixture's, so the engine, which
//     holds its own copies, is pinned to the same values from its side.
// Run via tests/test_fetch_handoff.py or:  node tests/fetch_handoff.test.js
const fs = require("fs"), vm = require("vm"), path = require("path");
const SRC = path.resolve(__dirname, "..", "src");
const FIX = JSON.parse(fs.readFileSync(
  path.join(__dirname, "..", "..", "contract", "fetch_handoff.json"), "utf8"));

let fail = 0;
const ok = (c, m) => { console.log((c ? "  ok   " : "  FAIL ") + m); if (!c) fail++; };
const read = f => fs.readFileSync(path.join(SRC, f + ".js"), "utf8");

// fetchcmd.js carries no SPA state: it must load in a context with nothing but the language.
const pure = { console, JSON, String, Array, Object, RegExp, navigator: { platform: "Linux" } };
pure.globalThis = pure; pure.window = pure;
vm.createContext(pure);
vm.runInContext(read("fetchcmd") + "\n;globalThis.__c={tsWgetCommand,tsCurlCommand,shq,winSafePath,tsOutPath,detectOs,WGET_OS_NOTES};", pure);
const C = pure.__c;
ok(typeof C.tsWgetCommand === "function" && typeof C.tsCurlCommand === "function",
   "fetchcmd.js loads with no DOM and no SPA globals and defines the two composers");

const rows = FIX.document.stations;
const only = lvl => rows.map(r => Object.assign({}, r, { levels: r.levels.filter(l => l.level === lvl) }))
                        .filter(r => r.levels.length);
ok(C.tsWgetCommand(rows) === FIX.commands.all.unix, "wget over every level equals the fixture");
ok(C.tsCurlCommand(rows, "curl") === FIX.commands.all.mac, "curl over every level equals the fixture");
ok(C.tsCurlCommand(rows, "curl.exe") === FIX.commands.all.win, "curl.exe over every level equals the fixture");
ok(C.tsWgetCommand(only("raw_packed")) === FIX.commands.raw_packed.unix, "wget over raw_packed alone equals the fixture");
ok(C.tsCurlCommand(only("raw_packed"), "curl") === FIX.commands.raw_packed.mac, "curl over raw_packed alone equals the fixture");
ok(C.tsCurlCommand(only("raw_packed"), "curl.exe") === FIX.commands.raw_packed.win, "curl.exe over raw_packed alone equals the fixture");
ok(C.tsWgetCommand([]) === "" && C.tsCurlCommand([], "curl") === "curl -L -C - --create-dirs",
   "no rows compose to no fetch (wget) and to the bare prefix (curl)");
ok(["linux", "mac", "win"].every(k => typeof C.WGET_OS_NOTES[k] === "string" && C.WGET_OS_NOTES[k]),
   "the three OS notes travel with the composers");

// The SPA's own document builder, over the same register and the same survey. The three modules load
// whole in a stub context exactly as the interaction harness loads them; a fixture built any other
// way would pin the fixture to itself.
const ctx = {
  console: { log() {}, error() {}, warn() {} }, JSON, Math, String, Array, Object, Set, Map, Date, Promise,
  Number, Boolean, RegExp, isFinite, parseInt, parseFloat, encodeURIComponent, decodeURIComponent,
  location: { origin: FIX.base, hash: "", search: "", pathname: "/" }, navigator: { platform: "Linux" },
  fetch: () => Promise.reject(new Error("no network in this harness")),
  document: { getElementById: () => null, addEventListener: null, createElement: () => ({}), activeElement: null },
  setTimeout: () => 0, clearTimeout() {}, localStorage: { getItem: () => null, setItem() {} },
};
ctx.globalThis = ctx; ctx.window = ctx; ctx.self = ctx;
vm.createContext(ctx);
vm.runInContext(["state", "data", "fetchcmd", "fetchdialog", "exports"].map(read).join("\n") +
  "\nTSACC=" + JSON.stringify(FIX.ts_access) + ";SMETA=" + JSON.stringify({ [FIX.survey.label]: { version: FIX.survey.version } }) +
  ";globalThis.__s={tsHandoffDocument,TS_HANDOFF_NOTE,TS_COLLECTION};", ctx);
const S = ctx.__s;
const ST = FIX.survey.ausmt_ids.map(aid => ({
  ausmt_id: aid, id: aid.slice(("au." + FIX.survey.slug + ".").length),
  survey: FIX.survey.label, slug: FIX.survey.slug }));
const built = S.tsHandoffDocument(ST, null);
ok(typeof built.doc.generated === "string" && built.doc.generated, "the SPA document carries its own stamp");
delete built.doc.generated;
ok(JSON.stringify(built.doc) === JSON.stringify(FIX.document),
   "the SPA's tsHandoffDocument over the fixture register equals the fixture document" +
   (JSON.stringify(built.doc) === JSON.stringify(FIX.document) ? "" : "\n      got: " + JSON.stringify(built.doc)));
ok(built.files === FIX.files && built.bytes === FIX.bytes,
   "the SPA's file count and byte total equal the fixture's, got " + built.files + " / " + built.bytes);
ok(S.TS_HANDOFF_NOTE === FIX.document.note, "exports.js TS_HANDOFF_NOTE is the fixture note");
ok(S.TS_COLLECTION.doi === FIX.document.time_series_collection.doi &&
   S.TS_COLLECTION.name === FIX.document.time_series_collection.name,
   "state.js TS_COLLECTION is the fixture's time-series collection");

if (fail) { console.log("\n" + fail + " FAILED"); process.exit(1); }
console.log("\nALL PASSED");
