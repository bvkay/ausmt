// PARITY: the SPA's display grammar against the engine's, helper for helper.
//
// One period, one range and one licence must PRINT the same whether a reader meets them on a static
// entity page or in the workspace. The engine owns the reference implementations in
// engine/extract/_pages.py (_fmt_period, _range, _cc_human/_fmt_licence); portal/src/state.js carries
// the JS twins. This file pins the twins against the SAME worked examples the engine suite pins the
// Python leaf against (engine/tests/test_entity_pages.py, the display-grammar block), written as LITERALS
// on both sides: no cross-runtime import, no generated vector file, so neither suite can be made
// green by editing the other's source of truth.
//
// Run via tests/test_display_grammar.py or: node tests/display_grammar.test.js
const fs = require("fs"), vm = require("vm"), path = require("path");
const SRC = path.resolve(__dirname, "..", "src");
const contract = fs.readFileSync(path.join(SRC, "contract.js"), "utf8");
const state = fs.readFileSync(path.join(SRC, "state.js"), "utf8");

// state.js reads window.AUSMT_CONFIG at load for the self-citation version and touches nothing else,
// so the sandbox is a bare window. Anything it asks for beyond this is a load-time dependency worth
// looking at before the stub is widened.
const ctx = {
  window: { AUSMT_CONFIG: { version: "test" } },
  console, Math, JSON, Date, Promise, Set, Map, Array, Object, String, Number, Boolean, RegExp,
  parseInt, parseFloat, isFinite, isNaN, Infinity, NaN,
};
ctx.globalThis = ctx; ctx.self = ctx;
vm.createContext(ctx);
vm.runInContext(contract + "\n" + state +
  "\n;globalThis.__p = fmtPeriod; globalThis.__r = fmtRange; globalThis.__l = licHuman;", ctx);
const fmtPeriod = ctx.__p, fmtRange = ctx.__r, licHuman = ctx.__l;

let fail = 0;
const ok = (c, m) => { console.log((c ? "  ok   " : "  FAIL ") + m); if (!c) fail++; };
const eq = (got, want, m) =>
  ok(got === want, m + " (want " + JSON.stringify(want) + ", got " + JSON.stringify(got) + ")");

ok(typeof fmtPeriod === "function", "fmtPeriod loaded from state.js");
ok(typeof fmtRange === "function", "fmtRange loaded from state.js");
ok(typeof licHuman === "function", "licHuman loaded from state.js");

// ---- The period display helper, the worked examples VERBATIM -----------------------------------
// The same seven pairs the engine suite asserts on _fmt_period. Under 100 a period reads to two
// significant figures with trailing zeros stripped; at or above 100 it is a thousands-separated
// integer; it is NEVER an exponent, whatever the magnitude.
for (const [value, shown] of [[5.33333, "5.3"], [0.005012, "0.005"], [9.6e-05, "0.000096"],
                              [0.004, "0.004"], [100000, "100,000"], [11651, "11,651"], [5, "5"]])
  eq(fmtPeriod(value), shown, "R1 worked example " + JSON.stringify(value));
ok(fmtPeriod(9.6e-05).indexOf("e") < 0, "exponent notation must never reach a rendered slot");

// TIE VECTORS. Not in the list, and the reason the JS twin cannot simply call toFixed:
// Python rounds an exact .5 tie to the EVEN neighbour and JS rounds it away from zero, so a 1.25 s
// period printed "1.3" in the workspace beside "1.2" on the survey page. These are the values where
// the two runtimes' default tie rules disagree, pinned as literals on both sides of the parity.
for (const [value, shown] of [[1.25, "1.2"], [1.35, "1.4"], [10.5, "10"], [11.5, "12"],
                              [100.5, "100"], [101.5, "102"], [0.125, "0.12"]])
  eq(fmtPeriod(value), shown, "R1 tie vector " + JSON.stringify(value));

// Absence is a plain hyphen, and zero is zero (never "0.0", never an exponent).
eq(fmtPeriod(null), "-", "R1: an absent period is a plain hyphen");
eq(fmtPeriod(undefined), "-", "R1: an undefined period is a plain hyphen");
eq(fmtPeriod("not a number"), "-", "R1: an unparseable period is a plain hyphen");
eq(fmtPeriod(0), "0", "R1: zero prints as zero");

// ---- The range separator ----------------------------------------------------------------------
// The revised rule: a numeric range in UI chrome reads as a SPACED HYPHEN-MINUS. Not an
// en dash, not an em dash, not the word "to".
eq(fmtRange(2016, 2021), "2016 - 2021", "R2: a year range takes the spaced hyphen");
eq(fmtRange(fmtPeriod(5), fmtPeriod(100000)), "5 - 100,000", "R2: a period range takes the spaced hyphen");
ok(fmtRange(1, 2).indexOf("\u2013") < 0 && fmtRange(1, 2).indexOf("\u2014") < 0,
   "the range separator carries no dash glyph");

// ---- The licence in human form ----------------------------------------------------------------
// The SPDX identifier is the machine's name for a licence; what a reader sees in chrome is the form
// the licence is published under. The form is derived from the identifier's own grammar (prefix,
// clause letters keeping their internal hyphens, version, jurisdiction port) over the identifiers
// the INSTRUMENT recognises - contract/licenses.json's redistributable + recognised_only, the same
// two tables _pages.py builds _LICENCE_DISPLAY from. A non-CC id has no such published reader's form
// and is printed verbatim rather than guessed at.
for (const [id, shown] of [["CC-BY-4.0", "CC BY 4.0"], ["CC0-1.0", "CC0 1.0"],
                           ["CC-BY-NC-SA-4.0", "CC BY-NC-SA 4.0"], ["CC-BY-3.0-AU", "CC BY 3.0 AU"],
                           ["CC-BY-SA-4.0", "CC BY-SA 4.0"], ["ODBL-1.0", "ODBL-1.0"],
                           ["PUBLIC DOMAIN", "PUBLIC DOMAIN"]])
  eq(licHuman(id), shown, "R3 licence display " + JSON.stringify(id));
// THE DOMAIN, which is half of the parity and was the half nothing pinned. A CC-GRAMMAR id that the
// instrument does not carry is echoed verbatim, because that is what _fmt_licence does: its lookup
// table has a key only for an allow-listed id. A wider JS domain meant the survey page printed
// "CC-BY-2.0" while the workspace printed "CC BY 2.0" for the same survey - two surfaces, one
// identifier, two readings, which is exactly what the licence rule exists to stop.
for (const id of ["CC-BY-2.0", "CC0-2.0", "CC-BY-ND-2.5", "CC-BY-NC-SA-2.0", "CC-BY-4.0-NZ"])
  eq(licHuman(id), id, "R3: a CC id the instrument does not recognise is echoed, as the pages echo it");
// An identifier the instrument does not recognise is echoed, never invented into a human form.
eq(licHuman("NOT-A-LICENCE-9.9"), "NOT-A-LICENCE-9.9", "R3: an unrecognised id is printed verbatim");
eq(licHuman(""), "", "R3: no licence, no text");

// EVERY CC id the instrument recognises must have a reader's form, so the map cannot fall behind
// the allow-list: this is the check that catches a licence added to contract/licenses.json without
// a display form, which is how one card came to read "CC-BY-3.0-AU" beside another's "CC BY 4.0".
const allCc = ctx.LICENSES.redistributable.concat(ctx.LICENSES.recognised_only)
  .filter(id => /^CC/.test(id));
ok(allCc.length >= 14, "the instrument's CC ids are readable from contract.js (" + allCc.length + ")");
for (const id of allCc)
  ok(licHuman(id) !== id && licHuman(id).indexOf(" ") > 0,
     "every recognised CC id needs a reader's form, " + JSON.stringify(id) +
     " printed " + JSON.stringify(licHuman(id)));

console.log(fail ? ("FAILED " + fail) : "ALL PASSED");
process.exit(fail ? 1 : 0);
