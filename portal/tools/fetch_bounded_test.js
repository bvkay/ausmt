// fetchBounded: the bulk-zip fetcher. Pins: real parallelism under the cap, input-order results,
// a failed fetch is null in its slot, and a short list never spawns idle workers.
// Extracted from exports.js by construct name (the map_dots_test.js pattern) and run in a vm with
// an instrumented fetch.
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SRC = fs.readFileSync(path.join(__dirname, "..", "src", "exports.js"), "utf8");
const m = SRC.match(/async function fetchBounded[\s\S]*?\n  return out;\}/);
if (!m) { console.error("FAIL: fetchBounded not found in exports.js"); process.exit(1); }

let inFlight = 0, maxInFlight = 0, calls = [];
const ctx = {
  fetch: (url) => {
    inFlight++; maxInFlight = Math.max(maxInFlight, inFlight); calls.push(url);
    return new Promise((resolve) => setTimeout(() => {
      inFlight--;
      if (url === "u3") resolve({ ok: false });
      else resolve({ ok: true, blob: async () => "blob:" + url });
    }, 5));
  },
  Promise, Array, Math, setTimeout,
};
vm.createContext(ctx);
vm.runInContext(m[0] + "; this.fetchBounded = fetchBounded;", ctx);

const items = Array.from({ length: 12 }, (_, i) => "u" + i);
ctx.fetchBounded(items, 6, (u) => u).then((out) => {
  const fails = [];
  const ok = (cond, msg) => { if (!cond) fails.push(msg); };
  ok(maxInFlight > 1, "requests must overlap (sequential = the 300-file slowdown), got max " + maxInFlight);
  ok(maxInFlight <= 6, "the cap must hold, got max " + maxInFlight);
  ok(out.length === 12 && out[0] === "blob:u0" && out[11] === "blob:u11",
     "results must keep input order");
  ok(out[3] === null, "a non-ok response must land as null in its own slot");
  ok(calls.length === 12, "every item fetched exactly once, got " + calls.length);
  return ctx.fetchBounded(["a"], 6, (u) => u).then((one) => {
    ok(one.length === 1 && one[0] === "blob:a", "a single item still works under the worker pool");
    if (fails.length) { fails.forEach((f) => console.error("FAIL: " + f)); process.exit(1); }
    console.log("FETCH-BOUNDED PASSED (" + calls.length + " fetches, max in flight " + maxInFlight + ")");
  });
}).catch((e) => { console.error("FAIL: " + e); process.exit(1); });
