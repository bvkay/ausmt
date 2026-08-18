// Change 6 map-declutter driver: the PURE badge rule, the router, and the radius curve, run for real
// against the shipped portal/src/map.js.
//
// WHY THIS EXISTS SEPARATELY from tools/interaction_test.js: that harness boots the whole app with a
// stubbed Leaflet, which is right for DOM/routing assertions but makes every map object a Proxy - so a
// station list handed to the router there is not the plain data the router actually reasons about. Here the
// functions under test are extracted and called directly on plain objects, which is what they were written
// to be: no Leaflet, no DOM, no map. Everything asserted below is therefore a real result from shipped
// code, not from a re-implementation.
//
// WHAT THIS DOES NOT PROVE: that a badge renders, is clickable, or lands on screen where the centroid says.
// Those need a browser. See the honest split in tests/test_map_badges.py's docstring.
//
//   node tools/map_badges_test.js
// Exit 0 = passed, 1 = a real failure.
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm");

const SRC = path.join(path.resolve(__dirname, ".."), "src");

// Extract just the pure region of map.js. The file's top level constructs a Leaflet map on load
// (`L.map("map")`), which we neither have nor want here; the badge logic is deliberately Leaflet-free, so
// pull the functions out by name and evaluate them alone. If a listed name ever stops existing, this
// throws loudly rather than silently testing nothing.
const mapSrc = fs.readFileSync(path.join(SRC, "map.js"), "utf8");
const WANT = [
  { kind: "const", names: ["BADGE_MAX_ZOOM", "BADGE_SPAN_PX", "BADGE_MIN_STATIONS",
                           "DOT_R_FLOOR", "DOT_R_CEIL", "DOT_R_SLOPE", "DOT_R_Z0",
                           "DOT_R_BASE_LP", "DOT_R_BASE_STD",
                           "MARKER_FILL_OPACITY", "MARKER_DIM_FILL", "MARKER_DIM_STROKE"] },
  { kind: "fn", names: ["mercatorY", "mercatorPixelSpan", "_badgeBbox", "surveyCentroid",
                        "shouldBadgeSurvey", "partitionForDisplay", "radiusForZoom", "hasPosition",
                        "isAuslampSurvey", "dimStyleFor"] },
];
let code = "";
for (const name of WANT[0].names) {
  // map.js declares some of these singly and some comma-chained on one line, so accept either form.
  const m = new RegExp("(?:const\\s+|,\\s*)" + name + "\\s*=\\s*([^;,]+)\\s*[;,]").exec(mapSrc);
  if (!m) { console.error("MAP BADGES FAILED: const " + name + " not found in map.js"); process.exit(1); }
  code += "const " + name + "=" + m[1].trim() + ";\n";
}
for (const name of WANT[1].names) {
  // Grab `function name(...) { ... }` by brace-matching from the header.
  const start = mapSrc.search(new RegExp("^function\\s+" + name + "\\s*\\(", "m"));
  if (start < 0) { console.error("MAP BADGES FAILED: function " + name + " not found in map.js"); process.exit(1); }
  let i = mapSrc.indexOf("{", start), depth = 0, end = -1, inStr = null;
  for (let j = i; j < mapSrc.length; j++) {
    const c = mapSrc[j], prev = mapSrc[j - 1];
    if (inStr) { if (c === inStr && prev !== "\\") inStr = null; continue; }
    if (c === '"' || c === "'" || c === "`") { inStr = c; continue; }
    if (c === "{") depth++;
    else if (c === "}") { depth--; if (depth === 0) { end = j + 1; break; } }
  }
  if (end < 0) { console.error("MAP BADGES FAILED: could not extract " + name); process.exit(1); }
  code += mapSrc.slice(start, end) + "\n";
}
const ctx = { Math, console, Set, Map, Array, Object, Number, isFinite, JSON };
ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(code + "\nglobalThis.__api={BADGE_MAX_ZOOM,BADGE_SPAN_PX,BADGE_MIN_STATIONS," +
  "DOT_R_FLOOR,DOT_R_CEIL,DOT_R_BASE_LP,DOT_R_BASE_STD," +
  "mercatorPixelSpan,surveyCentroid,shouldBadgeSurvey,partitionForDisplay,radiusForZoom,dimStyleFor};", ctx);
const A = ctx.__api;

let failed = 0;
function ok(cond, msg) { if (!cond) { console.error("MAP BADGES FAILED: " + msg); failed++; } }
const near = (a, b, tol) => Math.abs(a - b) <= (tol === undefined ? 1e-6 : tol);

// ---- centroid -----------------------------------------------------------------------------------
// Placement is the CENTROID, never a bin: the badge must sit inside its own survey.
ok(A.surveyCentroid([]) === null, "an empty station list has no centroid (must be null, not 0,0)");
const c1 = A.surveyCentroid([{ lat: -30, lon: 140 }, { lat: -32, lon: 142 }]);
ok(near(c1.lat, -31) && near(c1.lon, 141), "centroid must be the arithmetic mean, got " + JSON.stringify(c1));
// Position-less stations are excluded from the mean, never counted as (0,0) - that would drag an Australian
// survey's badge toward the Gulf of Guinea.
const c2 = A.surveyCentroid([{ lat: -30, lon: 140 }, { lat: null, lon: null }, { lat: -32, lon: 142 }]);
ok(near(c2.lat, -31) && near(c2.lon, 141), "a coordinate-withheld station must not drag the centroid, got " + JSON.stringify(c2));

// ---- pixel span ---------------------------------------------------------------------------------
// One zoom level doubles the pixel span of a fixed box. This is the property the threshold rides on.
const box = { w: 140, e: 141, so: -31, no: -30 };
const s5 = A.mercatorPixelSpan(box, 5), s6 = A.mercatorPixelSpan(box, 6);
ok(near(s6, s5 * 2, 1e-6), "pixel span must double per zoom level, got " + s5 + " -> " + s6);
// 1 degree of longitude at z5 = 256*32/360 = 22.75px. Anchors the absolute scale, not just the ratio.
ok(near(s5, 256 * 32 / 360, 0.5) || s5 > 256 * 32 / 360,
  "1 deg lon at z5 must be ~22.75px (or larger if the lat axis dominates), got " + s5);
ok(A.mercatorPixelSpan(null, 5) === 0, "a null bbox must span 0px, never NaN");

// ---- the badge rule -----------------------------------------------------------------------------
const tiny = { w: 140, e: 140.05, so: -31, no: -30.95 };     // ~5 km across
const wide = { w: 130, e: 145, so: -38, no: -25 };           // a state-scale array
const base = { count: 20, zoom: 4, bbox: tiny, isAuslamp: false, badgesEnabled: true };
ok(A.shouldBadgeSurvey(base) === true, "a compact multi-station survey must badge at national zoom");
ok(A.shouldBadgeSurvey({ ...base, bbox: wide }) === false, "a state-scale footprint must NEVER badge");
ok(A.shouldBadgeSurvey({ ...base, isAuslamp: true }) === false,
  "an AusLAMP member must NEVER badge (the national LP fabric always reads as a grid)");
ok(A.shouldBadgeSurvey({ ...base, count: 1 }) === false, "a lone station must never badge");
ok(A.shouldBadgeSurvey({ ...base, count: A.BADGE_MIN_STATIONS }) === true,
  "exactly BADGE_MIN_STATIONS stations must badge (the boundary is inclusive)");
ok(A.shouldBadgeSurvey({ ...base, badgesEnabled: false }) === false,
  "Select & export (badgesEnabled false) must expand everything");
// zoom ceiling: strictly below BADGE_MAX_ZOOM badges, at it does not.
ok(A.shouldBadgeSurvey({ ...base, zoom: A.BADGE_MAX_ZOOM - 1, bbox: tiny }) === true,
  "just below BADGE_MAX_ZOOM a compact survey still badges");
ok(A.shouldBadgeSurvey({ ...base, zoom: A.BADGE_MAX_ZOOM, bbox: tiny }) === false,
  "at BADGE_MAX_ZOOM every survey must show its stations");

// THRESHOLD CROSSING, the headline behaviour: hold the survey still and zoom in; it must badge, then stop,
// and never flip back. Find the crossing and assert monotonicity either side of it.
const cross = { w: 140, e: 140.4, so: -31, no: -30.6 };
let lastBadged = true, flips = 0, crossZoom = null;
for (let z = 1; z <= 12; z++) {
  const b = A.shouldBadgeSurvey({ count: 30, zoom: z, bbox: cross, isAuslamp: false, badgesEnabled: true });
  if (b !== lastBadged) { flips++; if (!b) crossZoom = z; }
  lastBadged = b;
}
ok(flips === 1, "badging must flip exactly ONCE across the zoom range (no oscillation), got " + flips + " flips");
ok(crossZoom !== null && crossZoom <= A.BADGE_MAX_ZOOM,
  "the survey must EXPAND as you zoom in, at or before BADGE_MAX_ZOOM; crossed at z=" + crossZoom);
ok(A.mercatorPixelSpan(cross, crossZoom) >= A.BADGE_SPAN_PX || crossZoom === A.BADGE_MAX_ZOOM,
  "the crossing must be explained by the span threshold or the zoom ceiling, not by accident");

// ---- the router ---------------------------------------------------------------------------------
// ONE BADGE PER SURVEY, the structural invariant. Two clumps of the SAME survey, far apart, must still
// yield exactly one badge - the failure mode proximity clustering had by construction.
const split = [
  { survey: "Split", slug: "split", lat: -30.0, lon: 140.0 },
  { survey: "Split", slug: "split", lat: -30.01, lon: 140.01 },
  { survey: "Split", slug: "split", lat: -34.0, lon: 148.0 },
  { survey: "Split", slug: "split", lat: -34.01, lon: 148.01 },
];
let r = A.partitionForDisplay(split, 4, { auslampSet: null, badgesEnabled: true });
ok(r.badges.filter(b => b.survey === "Split").length <= 1,
  "a survey may NEVER produce two badges, got " + r.badges.length);
// (this one is spread, so it renders as dots - the point is that it is never TWO badges)
ok(r.badges.length === 0 && r.dots.length === 4, "a spread survey renders as dots, got " + JSON.stringify(r.badges));

// A mixed map: one compact survey (badges), one spread survey (dots), one AusLAMP member (dots).
const mixed = [
  { survey: "Compact", slug: "compact", lat: -30.00, lon: 140.00 },
  { survey: "Compact", slug: "compact", lat: -30.02, lon: 140.02 },
  { survey: "Compact", slug: "compact", lat: -30.01, lon: 140.03 },
  { survey: "Spread", slug: "spread", lat: -25.0, lon: 130.0 },
  { survey: "Spread", slug: "spread", lat: -38.0, lon: 148.0 },
  { survey: "Grid", slug: "auslamp-x", lat: -30.0, lon: 141.0 },
  { survey: "Grid", slug: "auslamp-x", lat: -30.1, lon: 141.1 },
];
const auslamp = new Set(["auslamp-x"]);
r = A.partitionForDisplay(mixed, 4, { auslampSet: auslamp, badgesEnabled: true });
ok(r.badges.length === 1 && r.badges[0].survey === "Compact",
  "only the compact non-AusLAMP survey may badge, got " + JSON.stringify(r.badges.map(b => b.survey)));
ok(r.badges[0].count === 3, "the badge must carry its survey's station COUNT, got " + r.badges[0].count);
ok(near(r.badges[0].lat, (-30.00 + -30.02 + -30.01) / 3) && near(r.badges[0].lon, (140.00 + 140.02 + 140.03) / 3),
  "the badge must sit at its survey's centroid, got " + JSON.stringify(r.badges[0]));
ok(r.dots.length === 4, "every non-badged station must still be a dot (nothing may vanish), got " + r.dots.length);
// CONSERVATION: no station may be lost or double-counted between the two containers.
const badgedCount = r.badges.reduce((a, b) => a + b.count, 0);
ok(badgedCount + r.dots.length === mixed.length,
  "dots + badged stations must account for EVERY station exactly once, got " +
  badgedCount + "+" + r.dots.length + " vs " + mixed.length);

// SELECT & EXPORT: everything expands, nothing badges.
r = A.partitionForDisplay(mixed, 4, { auslampSet: auslamp, badgesEnabled: false });
ok(r.badges.length === 0 && r.dots.length === mixed.length,
  "Select & export must expand EVERY badge to dots so a lasso can reach the stations, got " +
  r.badges.length + " badges");

// A survey whose stations are all coordinate-withheld must not badge at (0,0) or crash.
r = A.partitionForDisplay([{ survey: "Hidden", slug: "h", lat: null, lon: null }], 4,
  { auslampSet: null, badgesEnabled: true });
ok(r.badges.length === 0, "a survey with no positioned station must produce no badge");

// ---- radius curve -------------------------------------------------------------------------------
// Monotone non-decreasing in zoom (the pinned property the old step ladder had), for both ramps.
for (const ty of ["LPMT", "BBMT"]) {
  for (let z = 0; z < 18; z++) {
    ok(A.radiusForZoom(z + 1, ty) >= A.radiusForZoom(z, ty),
      "radiusForZoom must be monotone non-decreasing in zoom (" + ty + " at z=" + z + ")");
  }
}
// Floor and ceiling both hold, at absurd zooms too. The floor is what stops a dot going sub-pixel at
// far-out zoom, where an invisible dot would read as "no coverage here" - a false claim about the corpus.
for (const ty of ["LPMT", "BBMT", undefined]) {
  for (const z of [-5, 0, 4, 8, 22, 99]) {
    const rr = A.radiusForZoom(z, ty);
    ok(rr >= A.DOT_R_FLOOR - 1e-9, "radius must never fall below the floor (" + ty + " z" + z + ") got " + rr);
    ok(rr <= A.DOT_R_CEIL + 1e-9, "radius must never exceed the ceiling (" + ty + " z" + z + ") got " + rr);
  }
}
// The floor is REACHED (not a decorative clamp that never fires): far enough out, both ramps bottom out.
ok(A.radiusForZoom(-5, "LPMT") === A.DOT_R_FLOOR, "the floor must actually bind at far-out zoom");
ok(A.radiusForZoom(99, "BBMT") === A.DOT_R_CEIL, "the ceiling must actually bind at close zoom");
// The LP fabric stays UNDER the standard dots wherever both are ramping - the whole point of the split.
for (let z = 4; z <= 9; z++) {
  ok(A.radiusForZoom(z, "LPMT") < A.radiusForZoom(z, "BBMT"),
    "the LP fabric must read smaller than BB/AMT at z=" + z + " (texture beneath, surveys above)");
}
// At national zoom LP is the small texture the owner asked for (~2-3px).
ok(A.radiusForZoom(4, "LPMT") >= A.DOT_R_FLOOR && A.radiusForZoom(4, "LPMT") <= 3.0,
  "at national zoom the LP dot must be small texture (~2-3px), got " + A.radiusForZoom(4, "LPMT"));
// An unknown type takes the standard (prominent) ramp, never the fabric ramp.
ok(A.radiusForZoom(6, "NEWTYPE") === A.radiusForZoom(6, "BBMT"),
  "an unknown data type must render on the standard ramp, not silently join the background fabric");

// ---- composition with change 2 ------------------------------------------------------------------
// Badges live in their survey's pane, so the dim decision is the SAME function for both. Pin that the
// decision does not distinguish them (there is one rule, keyed on survey, not on marker kind).
ok(A.dimStyleFor("Compact", "Compact").fillOpacity > A.dimStyleFor("Spread", "Compact").fillOpacity,
  "the focus dim must dim a non-focused survey, for badges exactly as for dots");

if (failed) { console.error(failed + " badge assertion(s) failed"); process.exit(1); }
console.log("MAP BADGES OK");
