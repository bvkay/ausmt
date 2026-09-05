// PARITY: a collection's member colours, the SPA against the static pages.
//
// A collection is drawn twice - as the static collection page's scatter (engine/extract/_pages.py
// _collection_scatter, over _member_colours) and as the SPA's collScatter - and a reader moving between
// them is entitled to find the same survey the same colour. The portal's eight-entry palette leads while
// it can; past eight the engine stops cycling and lays an evenly spaced hue ramp instead, because
// cycling gave two surveys one colour and made the legend useless.
//
// This pins the JS twin (portal/src/state.js memberColours) against the engine's rule, with the expected
// lists as LITERALS on this side and the rule itself asserted structurally, so the two cannot drift
// silently. No cross-runtime import: the engine's own suite pins the Python leaf.
//
// Run via tests/test_collection_colours.py or: node tests/collection_colours.test.js
const fs = require("fs"), vm = require("vm"), path = require("path");
const SRC = path.resolve(__dirname, "..", "src");
const contract = fs.readFileSync(path.join(SRC, "contract.js"), "utf8");
const state = fs.readFileSync(path.join(SRC, "state.js"), "utf8");

const ctx = {
  window: { AUSMT_CONFIG: { version: "test" } },
  console, Math, JSON, Date, Promise, Set, Map, Array, Object, String, Number, Boolean, RegExp,
  parseInt, parseFloat, isFinite, isNaN, Infinity, NaN,
};
ctx.globalThis = ctx; ctx.self = ctx;
vm.createContext(ctx);
vm.runInContext(contract + "\n" + state +
  "\n;globalThis.__mc = memberColours; globalThis.__pal = COLL_PAL;", ctx);
const memberColours = ctx.__mc, COLL_PAL = ctx.__pal;

let fail = 0;
const ok = (c, m) => { console.log((c ? "  ok   " : "  FAIL ") + m); if (!c) fail++; };
const eqList = (got, want, m) =>
  ok(JSON.stringify(got) === JSON.stringify(want),
     m + "\n want " + JSON.stringify(want) + "\n got " + JSON.stringify(got));

ok(typeof memberColours === "function", "memberColours loaded from state.js");

// The three member counts the contract names. 8 is the last count the shared palette covers; 9 is the
// first that must fall through to the ramp; 14 is a real AusLAMP-scale collection.
eqList(memberColours(8),
  ["#2E8FA3", "#EF7256", "#8A5FC0", "#5BAE6A", "#3F6FC4", "#C255A0", "#D9A23B", "#A85454"],
  "C7: 8 members take the shared eight-entry palette, in order");
eqList(memberColours(9),
  ["#D66666", "#B98C31", "#B1D666", "#31B931", "#66D6B1", "#318CB9", "#6666D6", "#8C31B9", "#D666B1"],
  "C7: 9 members fall through to the evenly spaced hue ramp");
eqList(memberColours(14),
  ["#D66666", "#B96C31", "#D6C666", "#92B931", "#86D666", "#31B945", "#66D6A6", "#31B9B9", "#66A6D6",
   "#3145B9", "#8666D6", "#9231B9", "#D666C6", "#B9316C"],
  "C7: 14 members take the ramp for 14");

// THE DEFECT THE RAMP EXISTS TO FIX: cycling an eight-entry palette gave the ninth member the first
// member's colour, so two surveys on one map shared a dot colour and the legend stopped meaning
// anything. Distinctness is the property, asserted well past the palette's length.
for (const n of [9, 12, 14, 20, 33]) {
  const cols = memberColours(n);
  ok(cols.length === n, "memberColours(" + n + ") must return " + n + " colours, got " + cols.length);
  ok(new Set(cols).size === n,
     "every member needs its OWN colour at n=" + n + " (a cycling palette repeats); distinct=" +
     new Set(cols).size);
}

// The palette leads for every count it can cover, so the common case matches the pages exactly.
for (let n = 1; n <= COLL_PAL.length; n++)
  eqList(memberColours(n), COLL_PAL.slice(0, n),
    "C7: at n=" + n + " the shared palette leads, unmodified");

// Deterministic in member order, with no randomness: the same count must give the same list every call,
// which is what lets the static page and the SPA agree without sharing a runtime.
ok(JSON.stringify(memberColours(11)) === JSON.stringify(memberColours(11)),
   "the ramp must be deterministic across calls");
// Every value is a full six-digit uppercase hex triple, the form the engine writes.
ok(memberColours(14).every(c => /^#[0-9A-F]{6}$/.test(c)),
   "colours must be six-digit uppercase hex, got " + JSON.stringify(memberColours(14).slice(0, 3)));

console.log(fail ? ("FAILED " + fail) : "ALL PASSED");
process.exit(fail ? 1 : 0);
