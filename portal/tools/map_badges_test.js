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
                           "DOT_R_FLOOR", "DOT_R_CEIL", "DOT_R_SLOPE", "DOT_R_Z0", "DOT_R_BASE",
                           "BADGE_GAP_PX", "BADGE_MAX_SHIFT_PX", "BADGE_DECLUTTER_PASSES", "BADGE_TAIL_MIN_PX",
                           "MARKER_FILL_OPACITY", "MARKER_DIM_FILL", "MARKER_DIM_STROKE"] },
  { kind: "fn", names: ["mercatorY", "mercatorPixelSpan", "_badgeBbox", "surveyCentroid",
                        "shouldBadgeSurvey", "partitionForDisplay", "radiusForZoom", "hasPosition",
                        "isAuslampSurvey", "dimStyleFor", "declutterBadges"] },
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
  "DOT_R_FLOOR,DOT_R_CEIL,DOT_R_BASE," +
  "BADGE_GAP_PX,BADGE_MAX_SHIFT_PX,BADGE_DECLUTTER_PASSES,BADGE_TAIL_MIN_PX," +
  "mercatorPixelSpan,surveyCentroid,shouldBadgeSurvey,partitionForDisplay,radiusForZoom,dimStyleFor," +
  "declutterBadges};", ctx);
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
// UNIFORM SITE DOT SIZE (owner, 2026-08-19): "the same size as the icons set for the AusLAMP sites". The
// per-type base split (LP 2.0 / everything else 3.0) is GONE. One curve serves every data type, and it is
// the LP one - BB/AMT/GDS come DOWN to the AusLAMP texture size rather than LP coming up. Data type is
// carried by COLOUR alone now; size carries only zoom. Badges are untouched (count-driven).
for (let z = 0; z < 18; z++) {
  ok(A.radiusForZoom(z + 1) >= A.radiusForZoom(z),
    "radiusForZoom must be monotone non-decreasing in zoom (z=" + z + ")");
}
// Floor and ceiling both hold, at absurd zooms too. The floor is what stops a dot going sub-pixel at
// far-out zoom, where an invisible dot would read as "no coverage here" - a false claim about the corpus.
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

// ---- badge collision declutter (owner, 2026-08-19) ----------------------------------------------
// The SA deposit-survey pile-up (312/20/216/53/83/78/36 badges stacked near Adelaide-Curnamona) made
// overlapping badges unreadable. declutterBadges is a PURE, deterministic separation pass over PROJECTED
// pixel positions: no Leaflet, no wall clock, no randomness. Placement honesty is the constraint that
// shapes it - a badge that moves must SAY it moved (the caller draws a leader tail), and a badge that
// would have to travel absurdly far is left overlapping rather than shot across the map.
const dcEq = (a, b, tol) => Math.abs(a - b) <= (tol === undefined ? 1e-9 : tol);
const dcDist = (p, q) => Math.hypot(p.x - q.x, p.y - q.y);
// A tight pile: five badges within a few px of each other, deliberately NOT in count order.
const pile = [
  { x: 500, y: 400, r: 17, count: 20 },
  { x: 503, y: 402, r: 26, count: 312 },
  { x: 498, y: 397, r: 26, count: 216 },
  { x: 501, y: 405, r: 21, count: 83 },
  { x: 505, y: 399, r: 21, count: 53 },
];
const laid = A.declutterBadges(pile);
ok(Array.isArray(laid) && laid.length === pile.length,
  "declutterBadges must return one entry per input badge, got " + (laid && laid.length));
// (1) SEPARATION FLOOR: no output pair may sit closer than r1+r2+GAP. SEP_TOL is a stated sub-pixel
//     tolerance, not a fudge to make a red test pass: the pass count is BOUNDED, so the relaxation is not
//     promised to land exactly on its fixed point for arbitrary input. 0.01px is invisible, and a real
//     failure (badges still tens of px into each other) blows straight through it.
const SEP_TOL = 0.01;
for (let i = 0; i < laid.length; i++) {
  for (let j = i + 1; j < laid.length; j++) {
    const need = pile[i].r + pile[j].r + A.BADGE_GAP_PX;
    const got = dcDist(laid[i], laid[j]);
    ok(got >= need - SEP_TOL,
      "declutter left badges overlapping: pair " + i + "/" + j + " at " + got.toFixed(3) +
      "px, needs " + need + "px");
  }
}
// (2) ANCHOR STABILITY: the biggest survey in a colliding set does not move. Readers navigate by the big
//     badges, so they are the fixed points and the small ones do the travelling.
const biggest = pile.reduce((a, b, i) => (b.count > pile[a].count ? i : a), 0);
ok(laid[biggest].displaced === false,
  "the largest badge (count " + pile[biggest].count + ") must stay anchored, not be displaced");
ok(dcEq(laid[biggest].x, pile[biggest].x) && dcEq(laid[biggest].y, pile[biggest].y),
  "the anchored badge's position must be byte-identical to its centroid projection");
// (3) DISPLACEMENT BOUND: no badge travels further than the stated cap. Beyond it we ACCEPT overlap - a
//     badge 200px from its survey is a worse lie than two badges touching.
laid.forEach((p, i) => {
  const moved = dcDist(p, pile[i]);
  ok(moved <= A.BADGE_MAX_SHIFT_PX + 1e-6,
    "badge " + i + " travelled " + moved.toFixed(2) + "px, over the " + A.BADGE_MAX_SHIFT_PX + "px cap");
  ok(p.displaced === (moved > A.BADGE_TAIL_MIN_PX),
    "badge " + i + " displaced flag (" + p.displaced + ") must mean 'moved more than BADGE_TAIL_MIN_PX' " +
    "(moved " + moved.toFixed(2) + "px) - the flag is exactly what gates the leader tail");
});
// (4) DETERMINISM: same input, same layout. No randomness, no wall clock, no dependence on object identity.
const again = A.declutterBadges(pile.map(p => ({ ...p })));
ok(JSON.stringify(again) === JSON.stringify(laid),
  "declutterBadges must be deterministic: two runs on equal input gave different layouts");
// (5) NO-COLLISION PASS-THROUGH: badges that already clear each other are left EXACTLY where they were.
//     At most zooms the pile-up resolves naturally and the declutter must then be a no-op, not a nudge.
const spread = [{ x: 100, y: 100, r: 17, count: 5 }, { x: 400, y: 380, r: 26, count: 300 }];
const spreadOut = A.declutterBadges(spread);
ok(spreadOut.every((p, i) => dcEq(p.x, spread[i].x) && dcEq(p.y, spread[i].y) && p.displaced === false),
  "non-overlapping badges must pass through untouched, got " + JSON.stringify(spreadOut));
// (6) DEGENERATE INPUTS: empty, single, and exactly-coincident centroids (two surveys with the same mean
//     position is not impossible) must not divide by zero, NaN, or hang.
ok(JSON.stringify(A.declutterBadges([])) === "[]", "an empty badge list must return an empty layout");
const one = A.declutterBadges([{ x: 10, y: 20, r: 17, count: 3 }]);
ok(one.length === 1 && one[0].displaced === false && dcEq(one[0].x, 10) && dcEq(one[0].y, 20),
  "a single badge can collide with nothing and must never move");
const coincident = A.declutterBadges([{ x: 50, y: 50, r: 17, count: 9 }, { x: 50, y: 50, r: 17, count: 4 }]);
ok(coincident.every(p => isFinite(p.x) && isFinite(p.y)),
  "exactly coincident centroids must not produce NaN (the away-vector is undefined there and needs a rule)");
ok(dcDist(coincident[0], coincident[1]) > 0,
  "exactly coincident badges must still be pushed apart, not left stacked at one point");
// (7) INPUT PURITY: the caller's array and entries must come back unmutated - the true centroid is what
//     the leader tail is drawn back TO, so corrupting it would corrupt the honesty mechanism itself.
const beforeJson = JSON.stringify(pile);
A.declutterBadges(pile);
ok(JSON.stringify(pile) === beforeJson, "declutterBadges must not mutate its input (the true centroids)");
// (8) THE REPORTED CASE. The owner screenshot pile-up: 312 / 20 / 216 / 53 / 83 / 78 / 36 stacked within a
//     few px near Adelaide-Curnamona. This is the fixture the feature exists for, so it is asserted as
//     itself rather than only as a synthetic: every pair separates, the 312 stays put, and nothing has to
//     reach the travel cap to get there (measured max travel ~56px against an 88px cap).
const sa = [
  { x: 700, y: 520, r: 26, count: 312 }, { x: 706, y: 517, r: 21, count: 20 },
  { x: 697, y: 524, r: 26, count: 216 }, { x: 703, y: 527, r: 21, count: 53 },
  { x: 709, y: 522, r: 21, count: 83 }, { x: 694, y: 519, r: 21, count: 78 },
  { x: 701, y: 514, r: 21, count: 36 },
];
const saOut = A.declutterBadges(sa);
for (let i = 0; i < saOut.length; i++) {
  for (let j = i + 1; j < saOut.length; j++) {
    const need = sa[i].r + sa[j].r + A.BADGE_GAP_PX;
    ok(dcDist(saOut[i], saOut[j]) >= need - SEP_TOL,
      "SA pile-up: badges " + sa[i].count + "/" + sa[j].count + " still overlap (" +
      dcDist(saOut[i], saOut[j]).toFixed(2) + "px, needs " + need + "px)");
  }
}
ok(saOut[0].displaced === false && dcEq(saOut[0].x, sa[0].x) && dcEq(saOut[0].y, sa[0].y),
  "SA pile-up: the 312-station badge is the landmark and must not move");
const saMax = Math.max(...saOut.map((p, i) => dcDist(p, sa[i])));
ok(saMax < A.BADGE_MAX_SHIFT_PX,
  "SA pile-up: the real case must resolve WITHOUT any badge reaching the travel cap, max travel was " +
  saMax.toFixed(1) + "px against a " + A.BADGE_MAX_SHIFT_PX + "px cap");
// (9) THE CAP ACTUALLY BINDS, and overlap is the accepted outcome when it does. A dozen large badges on
//     one point cannot all be separated inside the cap; the rule is that they stay put and overlap rather
//     than being flung across the map, so this pins the cap as a REAL limit, not a decorative constant.
const impossible = [];
for (let k = 0; k < 12; k++) impossible.push({ x: 300, y: 300, r: 26, count: 100 - k });
const impOut = A.declutterBadges(impossible);
impOut.forEach((p, i) => ok(dcDist(p, impossible[i]) <= A.BADGE_MAX_SHIFT_PX + 1e-6,
  "an unresolvable pile must still respect the travel cap; badge " + i + " went " +
  dcDist(p, impossible[i]).toFixed(1) + "px"));
ok(impOut.some((p, i) => {
  for (let j = 0; j < impOut.length; j++) {
    if (j === i) continue;
    if (dcDist(p, impOut[j]) < impossible[i].r + impossible[j].r + A.BADGE_GAP_PX - SEP_TOL) return true;
  }
  return false;
}), "the cap must be a REAL limit: an unresolvable pile is expected to end up still overlapping, " +
    "which is the stated trade (accepted overlap beats a badge far from its survey)");
ok(impOut.every(p => isFinite(p.x) && isFinite(p.y)), "an unresolvable pile must not produce NaN positions");

// ---- composition with change 2 ------------------------------------------------------------------
// Badges live in their survey's pane, so the dim decision is the SAME function for both. Pin that the
// decision does not distinguish them (there is one rule, keyed on survey, not on marker kind).
ok(A.dimStyleFor("Compact", "Compact").fillOpacity > A.dimStyleFor("Spread", "Compact").fillOpacity,
  "the focus dim must dim a non-focused survey, for badges exactly as for dots");

if (failed) { console.error(failed + " badge assertion(s) failed"); process.exit(1); }
console.log("MAP BADGES OK");
