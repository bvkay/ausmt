// Map dot driver: the PURE dot geometry and the focus-dim decision, run for real against the shipped
// portal/src/map.js.
//
// WHY THIS EXISTS SEPARATELY from tools/interaction_test.js: that harness boots the whole app with a
// stubbed Leaflet, which is right for DOM/routing assertions but makes every map object a Proxy. Here the
// functions under test are extracted and called directly on plain numbers, which is what they were written
// to be: no Leaflet, no DOM, no map. Everything asserted below is therefore a real result from shipped
// code, not from a re-implementation.
//
// WHAT IT WAS: the change-6 badge driver (declutter, leader tails, panes, the badge rule and its router).
// That feature was removed and every one of those sections went with it; the removal
// itself is pinned at the SOURCE in tests/test_map_dots.py, because a jsdom run cannot observe the absence
// of a layer it never draws. What survives here is what the map still does: size a dot by zoom, and dim a
// survey that is not in focus.
//
//   node tools/map_dots_test.js
// Exit 0 = passed, 1 = a real failure.
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm");

const SRC = path.join(path.resolve(__dirname, ".."), "src");

// Extract just the pure region of map.js. The file's top level constructs a Leaflet map on load
// (`L.map("map")`), which we neither have nor want here; the geometry is deliberately Leaflet-free, so
// pull the functions out by name and evaluate them alone. If a listed name ever stops existing, this
// throws loudly rather than silently testing nothing.
const mapSrc = fs.readFileSync(path.join(SRC, "map.js"), "utf8");
const WANT = [
  { kind: "const", names: ["DOT_R_FLOOR", "DOT_R_CEIL", "DOT_R_SLOPE", "DOT_R_Z0", "DOT_R_BASE",
                           "MARKER_FILL_OPACITY", "MARKER_DIM_FILL", "MARKER_DIM_STROKE"] },
  { kind: "fn", names: ["radiusForZoom", "weightForZoom", "hasPosition", "dimStyleFor"] },
];
// NOTE for anyone adding a name here: the brace matcher below treats a quote character as a string
// delimiter WITHOUT skipping comments first, so an apostrophe inside a comment in an extracted function
// swallows the rest of the file and extraction fails (loudly). Keep extracted functions apostrophe-free.
function grabConst(name) {
  // map.js declares some of these singly and some comma-chained on one line, so accept either form.
  const m = new RegExp("(?:const\\s+|,\\s*)" + name + "\\s*=\\s*([^;,]+)\\s*[;,]").exec(mapSrc);
  if (!m) { console.error("MAP DOTS FAILED: const " + name + " not found in map.js"); process.exit(1); }
  return "const " + name + "=" + m[1].trim() + ";\n";
}
function grabFn(name) {
  // Grab `function name(...) { ... }` by brace-matching from the header.
  const start = mapSrc.search(new RegExp("^function\\s+" + name + "\\s*\\(", "m"));
  if (start < 0) { console.error("MAP DOTS FAILED: function " + name + " not found in map.js"); process.exit(1); }
  let i = mapSrc.indexOf("{", start), depth = 0, end = -1, inStr = null;
  for (let j = i; j < mapSrc.length; j++) {
    const c = mapSrc[j], prev = mapSrc[j - 1];
    if (inStr) { if (c === inStr && prev !== "\\") inStr = null; continue; }
    if (c === '"' || c === "'" || c === "`") { inStr = c; continue; }
    if (c === "{") depth++;
    else if (c === "}") { depth--; if (depth === 0) { end = j + 1; break; } }
  }
  if (end < 0) { console.error("MAP DOTS FAILED: could not extract " + name); process.exit(1); }
  return mapSrc.slice(start, end) + "\n";
}
function buildCode(consts, fns) {
  return consts.map(grabConst).join("") + fns.map(grabFn).join("");
}
const code = buildCode(WANT[0].names, WANT[1].names);
const ctx = { Math, console, Set, Map, Array, Object, Number, isFinite, JSON };
ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(code + "\nglobalThis.__api={DOT_R_FLOOR,DOT_R_CEIL,DOT_R_BASE," +
  "radiusForZoom,weightForZoom,hasPosition,dimStyleFor};", ctx);
const A = ctx.__api;

let failed = 0;
function ok(cond, msg) { if (!cond) { console.error("MAP DOTS FAILED: " + msg); failed++; } }

// ---- radius curve -------------------------------------------------------------------------------
// UNIFORM SITE DOT SIZE: "the same size as the icons set for the AusLAMP sites". The
// per-type base split (LP 2.0 / everything else 3.0) is GONE. One curve serves every data type, and it is
// the LP one - BB/AMT/GDS come DOWN to the AusLAMP texture size rather than LP coming up. Data type is
// carried by COLOUR alone; size carries only zoom.
for (let z = 0; z < 18; z++) {
  ok(A.radiusForZoom(z + 1) >= A.radiusForZoom(z),
    "radiusForZoom must be monotone non-decreasing in zoom (z=" + z + ")");
}
// Floor and ceiling both hold, at absurd zooms too. The floor is what stops a dot going sub-pixel at
// far-out zoom, where an invisible dot would read as "no coverage here" - a false claim about the corpus.
// It matters more since the dots-only rule: at national zoom a dot is now the ONLY thing that
// says a survey is there, with no badge standing in for it.
for (const z of [-5, 0, 4, 8, 22, 99]) {
  const rr = A.radiusForZoom(z);
  ok(rr >= A.DOT_R_FLOOR - 1e-9, "radius must never fall below the floor (z" + z + ") got " + rr);
  ok(rr <= A.DOT_R_CEIL + 1e-9, "radius must never exceed the ceiling (z" + z + ") got " + rr);
}
// The floor is REACHED (not a decorative clamp that never fires): far enough out, the ramp bottoms out.
ok(A.radiusForZoom(-5) === A.DOT_R_FLOOR, "the floor must actually bind at far-out zoom");
ok(A.radiusForZoom(99) === A.DOT_R_CEIL, "the ceiling must actually bind at close zoom");
// THE CHANGE ITSELF: no data type may render larger or smaller than any other, at any zoom. The retired
// `type` argument's CALL FORM must be inert - a stray second argument is ignored, never honoured, so a
// caller that was not updated cannot quietly resurrect the per-type split.
for (let z = 0; z <= 12; z++) {
  const uniform = A.radiusForZoom(z);
  for (const ty of ["LPMT", "BBMT", "AMT", "GDS", "NEWTYPE", undefined, null]) {
    ok(A.radiusForZoom(z, ty) === uniform,
      "every data type must render at the SAME radius (type " + ty + " at z=" + z + "): got " +
      A.radiusForZoom(z, ty) + " vs " + uniform);
  }
}
// ...and the size they all take is the AusLAMP LP one. Pinned against the named constant AND its value,
// because "they all match" would still pass if every dot had jumped to the retired 3.0 standard base.
ok(A.DOT_R_BASE === 2.0,
  "the surviving curve must be the AusLAMP/LP one (base 2.0), got " + A.DOT_R_BASE);
ok(A.radiusForZoom(4) === A.DOT_R_BASE,
  "at national zoom every dot must sit at DOT_R_BASE, got " + A.radiusForZoom(4));
ok(A.radiusForZoom(4) >= A.DOT_R_FLOOR && A.radiusForZoom(4) <= 3.0,
  "at national zoom every dot must be small texture (~2-3px), got " + A.radiusForZoom(4));
ok(A.weightForZoom(4) === 1.0 && A.weightForZoom(5) === 1.5,
  "the stroke weight must still step at z5, got " + A.weightForZoom(4) + " / " + A.weightForZoom(5));

// ---- positioned stations only -------------------------------------------------------------------
// A coordinate-withheld station carries null lat/lon and has no place on the map. Every map path
// funnels through this one predicate, which is why it is pinned here rather than at each call site.
ok(A.hasPosition({ lat: -30, lon: 140 }) === true, "an exact position must reach the map");
ok(A.hasPosition({ lat: null, lon: null }) === false, "a withheld position must never reach the map");
ok(A.hasPosition({ lat: 0, lon: 0 }) === true, "a real (0,0) is a position, not a sentinel");
ok(A.hasPosition({ lat: NaN, lon: 140 }) === false, "a NaN coordinate must never reach the map");
ok(A.hasPosition(null) === false, "a missing station must not crash the predicate");

// ---- composition with change 2 ------------------------------------------------------------------
// Every map object is a station dot now, so the focus dim is one rule over one kind of thing, keyed on the
// survey. Non-focused must be dimmer, and still VISIBLE (Option A keeps the national context on the map).
ok(A.dimStyleFor("Compact", "Compact").fillOpacity > A.dimStyleFor("Spread", "Compact").fillOpacity,
  "the focus dim must dim a non-focused survey");
ok(A.dimStyleFor("Spread", "Compact").fillOpacity > 0,
  "a non-focused survey must stay visible, not hidden");
ok(A.dimStyleFor("Spread", null).fillOpacity === A.dimStyleFor("Compact", "Compact").fillOpacity,
  "with no focus every survey renders at full strength");

if (failed) { console.error(failed + " map-dot assertion(s) failed"); process.exit(1); }
console.log("MAP DOTS OK");
