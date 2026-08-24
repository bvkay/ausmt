// Node test: portal/src/data.js tsArchiveUrl MUST reproduce the SHARED vector file
// (engine/tests/fixtures/ts_url_vectors.json) byte-for-byte - the SAME file the engine pytest
// (engine/tests/test_ts_url_vectors.py) pins _stationcheck.ts_access_url against.
//
// WHY A MIRROR EXISTS AT ALL. The engine and the deploy generator now CALL one encoder; JavaScript
// cannot, because it has no quote(url_path, safe="/"). encodeURIComponent is NOT that function on
// its own - it eats `/` and it leaves !'()* alone where Python escapes them - so data.js spells the
// safe set out, and only a shared vector file can say the two agree. Corrupt one vector and exactly
// that vector reds on BOTH sides.
//
// Loads data.js in a vm sandbox with the handful of globals it touches at load. Run via
// tests/test_ts_url_vectors.py or:  node tests/ts_url_vectors.test.js
const fs = require("fs"), vm = require("vm"), path = require("path");
const SRC = path.resolve(__dirname, "..", "src");
const dataSrc = fs.readFileSync(path.join(SRC, "data.js"), "utf8");
const VEC = JSON.parse(fs.readFileSync(
  path.join(__dirname, "..", "..", "engine", "tests", "fixtures", "ts_url_vectors.json"), "utf8"));

// data.js declares module-level state and reads location.origin inside tsGoRoute (never at load).
const ctx = {
  console, Math, JSON, Date, Promise, Set, Map, Array, Object, String, Number, Boolean, RegExp,
  parseInt, parseFloat, isFinite, encodeURIComponent, decodeURIComponent,
  location: { origin: "https://example.invalid" },
  fetch: () => Promise.reject(new Error("no network in this harness")),
  document: { getElementById: () => null },
  setTimeout: () => 0, clearTimeout() {},
};
ctx.globalThis = ctx; ctx.self = ctx; ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(dataSrc + "\n;globalThis.__tsau = tsArchiveUrl;globalThis.__pfx = TS_FILESERVER;", ctx);
const tsArchiveUrl = ctx.__tsau;

let fail = 0;
const ok = (c, m) => { console.log((c ? "  ok   " : "  FAIL ") + m); if (!c) fail++; };

ok(typeof tsArchiveUrl === "function", "tsArchiveUrl loaded from data.js");
ok(Array.isArray(VEC.vectors) && VEC.vectors.length >= 8,
   "shared ts_url_vectors.json loads (" + VEC.vectors.length + " vectors)");
// The host is stated once per side; a mirror that encoded perfectly onto the wrong archive would
// still be wrong, so the prefix is part of the contract rather than a detail either side may hold.
ok(ctx.__pfx === VEC.prefix,
   "data.js TS_FILESERVER must be the vector file's prefix, got " + JSON.stringify(ctx.__pfx));

for (const v of VEC.vectors) {
  const got = tsArchiveUrl(v.url_path);
  if (got === v.expected) { ok(true, "vector [" + v.name + "]"); continue; }
  ok(false, "vector [" + v.name + "] diverged");
  console.log("      JS : " + JSON.stringify(got));
  console.log("      exp: " + JSON.stringify(v.expected));
}

// Absence is not a route: the pointer file must never carry a bare prefix as an address.
ok(tsArchiveUrl(null) === VEC.prefix && tsArchiveUrl(undefined) === VEC.prefix,
   "a null/undefined url_path yields the bare prefix and nothing invented");

console.log(fail ? ("FAILED " + fail) : "ALL PASSED");
process.exit(fail ? 1 : 0);
