// C46-W2 Node test: portal/src/exports.js licenseInstrumentText MUST reproduce the shared vector file
// (engine/tests/fixtures/license_instrument_vectors.json) byte-for-byte — the SAME file the engine
// pytest (test_license_instrument_vectors.py) pins the Python leaf against. So the two implementations
// of the licence INSTRUMENT text cannot drift silently: corrupt one vector and exactly that vector reds
// on BOTH sides. Loads contract.js (LICENSES + PROFILES) + exports.js in a vm sandbox, stubbing only the
// DOM those modules touch at load. Run via tests/test_license_text_vectors.py or:
//   node tests/license_text_vectors.test.js
const fs = require("fs"), vm = require("vm"), path = require("path");
const SRC = path.resolve(__dirname, "..", "src");
const contract = fs.readFileSync(path.join(SRC, "contract.js"), "utf8");
const exportsSrc = fs.readFileSync(path.join(SRC, "exports.js"), "utf8");
const VEC = JSON.parse(fs.readFileSync(
  path.join(__dirname, "..", "..", "engine", "tests", "fixtures", "license_instrument_vectors.json"), "utf8"));

// This driver wants the PURE licence/citation text functions, so it gives exports.js the smallest
// document that lets the module finish loading: element stubs for the load-time
// getElementById(...).onclick wiring, plus a document-level addEventListener, because the wget
// dialog's modal contract (Escape) binds one at module top level. Anything the stub does not answer
// is a load-time DOM touch this driver was not expecting: worth a look before widening the stub.
const elStub = () => ({ onclick: null, addEventListener() {} });
const ctx = {
  document: { getElementById: () => elStub(), createElement: () => elStub(), addEventListener() {} },
  console, Math, JSON, Date, Promise, Set, Array, Object, String, Number, Boolean, RegExp,
  parseInt, parseFloat, isFinite, encodeURIComponent, decodeURIComponent,
  setTimeout: () => 0, clearTimeout() {}, URL: { createObjectURL: () => "x", revokeObjectURL() {} },
};
ctx.globalThis = ctx; ctx.self = ctx;
vm.createContext(ctx);
vm.runInContext(contract + "\n" + exportsSrc + "\n;globalThis.__lit = licenseInstrumentText;", ctx);
const lit = ctx.__lit;

let fail = 0;
const ok = (c, m) => { console.log((c ? "  ok   " : "  FAIL ") + m); if (!c) fail++; };

ok(typeof lit === "function", "licenseInstrumentText loaded from exports.js");
ok(Array.isArray(VEC.vectors) && VEC.vectors.length >= 8,
   "shared license_instrument_vectors.json loads (" + VEC.vectors.length + " vectors)");

for (const v of VEC.vectors) {
  const got = lit(v.lic, v.licensor, v.year, v.attribution, v.sources, v.changes);
  if (got === v.expected) { ok(true, "vector [" + v.name + "]"); continue; }
  ok(false, "vector [" + v.name + "] diverged from expected");
  const a = got.split("\n"), b = v.expected.split("\n");
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    if (a[i] !== b[i]) {
      console.log("    first diff at line " + i);
      console.log("      JS : " + JSON.stringify(a[i]));
      console.log("      exp: " + JSON.stringify(b[i]));
      break;
    }
  }
}
console.log(fail ? ("FAILED " + fail) : "ALL PASSED");
process.exit(fail ? 1 : 0);
