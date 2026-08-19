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
                           "BADGE_TAIL_OPACITY", "BADGE_SIZE_SCALE",
                           "SURV_PANE_Z", "BADGE_TAIL_PANE", "BADGE_TAIL_PANE_Z", "_decorationPanes",
                           "MARKER_FILL_OPACITY", "MARKER_DIM_FILL", "MARKER_DIM_STROKE"] },
  { kind: "fn", names: ["mercatorY", "mercatorPixelSpan", "_badgeBbox", "surveyCentroid",
                        "shouldBadgeSurvey", "partitionForDisplay", "radiusForZoom", "hasPosition",
                        "isAuslampSurvey", "dimStyleFor", "declutterBadges", "badgeSizePx",
                        "tailOpacityFor", "_decorationPaneViolation"] },
];
// NOTE for anyone adding a name here: the brace matcher below treats a quote character as a string
// delimiter WITHOUT skipping comments first, so an apostrophe inside a comment in an extracted function
// swallows the rest of the file and extraction fails (loudly). Keep extracted functions apostrophe-free.
function grabConst(name) {
  // map.js declares some of these singly and some comma-chained on one line, so accept either form.
  const m = new RegExp("(?:const\\s+|,\\s*)" + name + "\\s*=\\s*([^;,]+)\\s*[;,]").exec(mapSrc);
  if (!m) { console.error("MAP BADGES FAILED: const " + name + " not found in map.js"); process.exit(1); }
  return "const " + name + "=" + m[1].trim() + ";\n";
}
function grabFn(name) {
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
  return mapSrc.slice(start, end) + "\n";
}
function buildCode(consts, fns) {
  return consts.map(grabConst).join("") + fns.map(grabFn).join("");
}
const code = buildCode(WANT[0].names, WANT[1].names);
const ctx = { Math, console, Set, Map, Array, Object, Number, isFinite, JSON };
ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(code + "\nglobalThis.__api={BADGE_MAX_ZOOM,BADGE_SPAN_PX,BADGE_MIN_STATIONS," +
  "DOT_R_FLOOR,DOT_R_CEIL,DOT_R_BASE," +
  "BADGE_GAP_PX,BADGE_MAX_SHIFT_PX,BADGE_DECLUTTER_PASSES,BADGE_TAIL_MIN_PX," +
  "BADGE_TAIL_OPACITY,BADGE_SIZE_SCALE,SURV_PANE_Z,BADGE_TAIL_PANE,BADGE_TAIL_PANE_Z,_decorationPanes," +
  "MARKER_DIM_FILL,badgeSizePx,tailOpacityFor,_decorationPaneViolation," +
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

// ---- THE RENDER PATH ITSELF (gate finding, 2026-08-19) ------------------------------------------
// Everything above tests declutterBadges as a PURE function, and the python side scanned map.js for the
// PRESENCE of the call. Neither proved the layout RESULT reaches the badge markers and the leader polyline.
// It did not: neutering _badgeLayout to return true centroids with no tails, and disabling the tail draw
// with `if(false&&at.tail)`, both left the whole suite green. The honesty content of the feature - a
// displaced badge admits it with a leader back to its survey - was unguarded.
//
// So drive the REAL render path. renderBadges and _badgeLayout are extracted from the shipped source and
// run against a recording Leaflet stub whose map.project/unproject are the ACTUAL Web Mercator transforms
// (not stubs that return proxies), so the pixel space the declutter reasons in is the real one. What is
// asserted is what actually landed in the layer: marker positions, polyline vertices, panes and options.
//
// STILL NOT PROVEN HERE (browser facts, unchanged): that Leaflet paints the marker where the LatLng says,
// that a pointer reaches a displaced badge, or that the tail is visible against the basemap.
const RENDER_CONSTS = ["BADGE_GAP_PX", "BADGE_MAX_SHIFT_PX", "BADGE_DECLUTTER_PASSES", "BADGE_TAIL_MIN_PX",
                       "BADGE_TAIL_COLOR", "BADGE_TAIL_OPACITY", "BADGE_SIZE_SCALE", "MARKER_DIM_FILL"];
const RENDER_FNS = ["mercatorY", "declutterBadges", "badgeSizePx", "badgeIcon", "curZoom",
                    "tailOpacityFor", "_badgeLayout", "renderBadges"];
// Real Web Mercator, the transform Leaflet's own project/unproject implement at 256px tiles.
const _merY = (lat) => Math.log(Math.tan(Math.PI / 4 + Math.max(-85.05112878, Math.min(85.05112878, lat)) * Math.PI / 360));
function renderEnv(zoom) {
  const added = [];
  const scale = 256 * Math.pow(2, zoom);
  const env = {
    Math, console, isFinite, Array, Object, Number, JSON, Set, Map,
    added,
    escAttr: (s) => String(s === undefined ? "" : s),
    _survPaneFor: (s) => "pane:" + s,
    // The tail pane is ONE pane for every leader, which is exactly the property the owner change rests on:
    // the stub takes no survey argument, so a per-survey tail pane could not even be expressed here.
    _badgeTailPane: () => A.BADGE_TAIL_PANE,
    _badgeTails: [],            // the registry applySurveyDim walks; renderBadges refills it every pass
    _dimFocusSurvey: null,      // no survey focused (a `let` in map.js, so supplied rather than extracted)
    badgeLayer: { clearLayers() { added.length = 0; }, addLayer(o) { added.push(o); } },
    map: {
      getZoom: () => zoom,
      project(ll, z) {
        const sc = 256 * Math.pow(2, z === undefined ? zoom : z);
        return { x: (ll[1] + 180) / 360 * sc, y: (Math.PI - _merY(ll[0])) / (2 * Math.PI) * sc };
      },
      unproject(p, z) {
        const sc = 256 * Math.pow(2, z === undefined ? zoom : z);
        const lng = p[0] / sc * 360 - 180;
        const m = Math.PI - p[1] / sc * 2 * Math.PI;
        return { lat: (2 * Math.atan(Math.exp(m)) - Math.PI / 2) * 180 / Math.PI, lng };
      },
    },
    L: {
      point: (x, y) => ({ x, y }),
      divIcon: (o) => ({ kind: "divIcon", opts: o }),
      polyline: (latlngs, opts) => ({ kind: "polyline", latlngs, opts }),
      marker: (latlng, opts) => ({ kind: "marker", latlng, opts, on() { return this; } }),
    },
    scale,
  };
  env.globalThis = env;
  vm.createContext(env);
  vm.runInContext(buildCode(RENDER_CONSTS, RENDER_FNS) +
    "\nglobalThis.__r={renderBadges,_badgeLayout,badgeSizePx,declutterBadges,tailOpacityFor};", env);
  return env;
}

// A colliding pile in REAL coordinates: five surveys within ~0.3 deg near the Curnamona, which at z5 is a
// few pixels - the shape of the case the owner reported. Counts deliberately out of order.
const RZ = 5;
const saLL = [
  { survey: "Kalkaroo 2026", slug: "kalk", lat: -32.00, lon: 138.00, count: 312 },
  { survey: "CCMT 2017", slug: "ccmt", lat: -32.05, lon: 138.15, count: 20 },
  { survey: "Jupiter 2021", slug: "jup", lat: -31.95, lon: 137.90, count: 216 },
  { survey: "Burra 2017-18", slug: "burra", lat: -32.10, lon: 138.05, count: 53 },
  { survey: "Tumby Bay 2018-19", slug: "tumby", lat: -31.90, lon: 138.20, count: 83 },
];
const renv = renderEnv(RZ);
renv.__r.renderBadges(saLL);
const rAdded = renv.added;

// The EXPECTATION is computed independently of _badgeLayout: project the true centroids with the same
// Mercator transform, run the pure declutter, and require the layer to carry exactly that. This is what
// makes a neutered _badgeLayout fail - the expectation does not come from the code path under test.
const rProj = saLL.map(b => renv.map.project([b.lat, b.lon], RZ));
const rExpect = renv.__r.declutterBadges(saLL.map((b, i) =>
  ({ x: rProj[i].x, y: rProj[i].y, r: renv.__r.badgeSizePx(b.count) / 2, count: b.count })));
const nDisplaced = rExpect.filter(e => e.displaced).length;
// Non-vacuous by construction: if this fixture stopped colliding there would be nothing to prove.
ok(nDisplaced > 0,
  "RENDER fixture is vacuous: no badge is displaced at z" + RZ + ", so the tail pins would prove nothing");
ok(nDisplaced < saLL.length, "RENDER fixture should leave the anchor badge in place, got all " + nDisplaced + " displaced");

// Walk the layer in order. renderBadges emits, per badge: the leader tail (only when displaced) and then
// the marker. Walking rather than filtering pins THREE things at once - the count, the pairing, and the
// z-order (tail first, so the badge draws over its own leader).
let ri = 0, tails = 0;
saLL.forEach((b, i) => {
  const wantTail = rExpect[i].displaced;
  if (wantTail) {
    const pl = rAdded[ri++];
    ok(pl && pl.kind === "polyline",
      "RENDER: displaced badge " + b.count + " must emit a leader polyline BEFORE its marker, got " +
      JSON.stringify(pl && pl.kind));
    if (pl && pl.kind === "polyline") {
      tails++;
      // the tail ENDS at the true centroid: this is the claim the whole feature exists to keep
      const last = pl.latlngs[pl.latlngs.length - 1];
      ok(near(last[0], b.lat, 1e-9) && near(last[1], b.lon, 1e-9),
        "RENDER: the leader for " + b.survey + " must END at its TRUE centroid " +
        JSON.stringify([b.lat, b.lon]) + ", got " + JSON.stringify(last));
      ok(!(near(pl.latlngs[0][0], b.lat, 1e-9) && near(pl.latlngs[0][1], b.lon, 1e-9)),
        "RENDER: the leader for " + b.survey + " starts at the centroid too - it points at nothing");
      ok(pl.opts && pl.opts.interactive === false,
        "RENDER: the leader polyline must be interactive:false, got " + JSON.stringify(pl.opts));
      // OWNER 2026-08-19: leaders ON TOP. Every leader rides the ONE dedicated tail pane, never its own
      // survey pane - that is what stops a leader being painted under some other survey's badge.
      ok(pl.opts && pl.opts.pane === A.BADGE_TAIL_PANE,
        "RENDER: the leader must ride the dedicated tail pane (" + A.BADGE_TAIL_PANE +
        ") so it paints above EVERY badge, got " + JSON.stringify(pl.opts && pl.opts.pane));
      // The dim the tail lost when it left the survey pane is re-applied per tail, at the undimmed value
      // here because this fixture focuses no survey.
      ok(pl.opts && Math.abs(pl.opts.opacity - renv.__r.tailOpacityFor(b.survey, null)) < 1e-12,
        "RENDER: an unfocused leader must carry the full tail opacity, got " +
        JSON.stringify(pl.opts && pl.opts.opacity));
      // THE RIM TRIM: the leader starts at the badge RIM, not at the badge centre, so a leader that now
      // paints ABOVE its own badge does not lay a spoke across the disc and its number. Measured in pixels
      // against the badge radius the declutter itself separated by.
      const _startPx = renv.map.project([pl.latlngs[0][0], pl.latlngs[0][1]], RZ);
      const _badgePx = rExpect[i], _rBadge = renv.__r.badgeSizePx(b.count) / 2;
      const _gap = Math.hypot(_startPx.x - _badgePx.x, _startPx.y - _badgePx.y);
      const _travel = Math.hypot(_badgePx.x - rProj[i].x, _badgePx.y - rProj[i].y);
      ok(_gap >= Math.min(_rBadge, Math.max(0, _travel - 1)) - 1e-6,
        "RENDER: the leader for " + b.survey + " starts " + _gap.toFixed(2) +
        "px from the badge centre but the badge radius is " + _rBadge.toFixed(2) +
        "px - it would be drawn across its own disc");
      ok(_gap <= _travel + 1e-6,
        "RENDER: the leader for " + b.survey + " was trimmed past its own centroid (start " +
        _gap.toFixed(2) + "px out, centroid is " + _travel.toFixed(2) + "px out)");
    }
  }
  const mk = rAdded[ri++];
  ok(mk && mk.kind === "marker", "RENDER: badge " + b.count + " must emit a marker, got " + JSON.stringify(mk && mk.kind));
  if (mk && mk.kind === "marker") {
    // THE CENTRAL PIN: the marker sits at the DECLUTTERED position, not at the centroid. Re-project what
    // actually reached the layer and compare against the pure function's answer, in pixels.
    const back = renv.map.project([mk.latlng[0], mk.latlng[1]], RZ);
    ok(near(back.x, rExpect[i].x, 1e-6) && near(back.y, rExpect[i].y, 1e-6),
      "RENDER: badge " + b.count + " (" + b.survey + ") was placed at pixel " +
      JSON.stringify([+back.x.toFixed(2), +back.y.toFixed(2)]) + " but the declutter says " +
      JSON.stringify([+rExpect[i].x.toFixed(2), +rExpect[i].y.toFixed(2)]) +
      " (centroid is " + JSON.stringify([+rProj[i].x.toFixed(2), +rProj[i].y.toFixed(2)]) + ")");
    if (wantTail) {
      const off = Math.hypot(back.x - rProj[i].x, back.y - rProj[i].y);
      ok(off > A.BADGE_TAIL_MIN_PX,
        "RENDER: badge " + b.count + " is flagged displaced but landed " + off.toFixed(3) +
        "px from its centroid - the layout result never reached the marker");
    }
    ok(mk.opts && mk.opts.pane === "pane:" + b.survey, "RENDER: a badge marker must ride its survey pane");
    ok(mk.opts && mk.opts.bubblingMouseEvents === false,
      "RENDER: a badge marker must keep bubblingMouseEvents:false through the declutter change");
  }
});
ok(ri === rAdded.length,
  "RENDER: the layer holds " + rAdded.length + " objects but the walk accounted for " + ri +
  " - something extra (or missing) was added");
ok(tails === nDisplaced,
  "RENDER: expected exactly " + nDisplaced + " leader tails (one per displaced badge), got " + tails);
// The anchor: the largest survey must be drawn exactly at its centroid, with no tail.
const rBigIdx = saLL.reduce((a, b, i) => (b.count > saLL[a].count ? i : a), 0);
ok(rExpect[rBigIdx].displaced === false, "RENDER fixture: the largest badge should be the anchor");
const bigMk = rAdded.filter(o => o.kind === "marker")[rBigIdx];
ok(near(bigMk.latlng[0], saLL[rBigIdx].lat, 1e-9) && near(bigMk.latlng[1], saLL[rBigIdx].lon, 1e-9),
  "RENDER: the anchor badge must be drawn at its exact centroid, got " + JSON.stringify(bigMk.latlng));

// A NON-colliding pile must emit NO tails at all: the disclosure only appears when there is something to
// disclose. (This is also what would catch a change that drew leaders unconditionally.)
const spreadLL = [
  { survey: "A", slug: "a", lat: -32.0, lon: 130.0, count: 40 },
  { survey: "B", slug: "b", lat: -25.0, lon: 145.0, count: 300 },
];
const renv2 = renderEnv(RZ);
renv2.__r.renderBadges(spreadLL);
ok(renv2.added.filter(o => o.kind === "polyline").length === 0,
  "RENDER: badges that do not collide must draw NO leader tails");
ok(renv2.added.filter(o => o.kind === "marker").length === 2, "RENDER: both non-colliding badges must still render");
renv2.added.filter(o => o.kind === "marker").forEach((mk, i) =>
  ok(near(mk.latlng[0], spreadLL[i].lat, 1e-9) && near(mk.latlng[1], spreadLL[i].lon, 1e-9),
    "RENDER: a non-colliding badge must sit exactly at its centroid"));

// A SINGLE badge cannot collide, so the layout short-circuits before projecting: still one marker, no tail.
const renv3 = renderEnv(RZ);
renv3.__r.renderBadges([{ survey: "Solo", slug: "s", lat: -30, lon: 140, count: 7 }]);
ok(renv3.added.length === 1 && renv3.added[0].kind === "marker",
  "RENDER: a lone badge must render as exactly one marker with no tail");

// ---- LEADERS ABOVE EVERY BADGE (owner, 2026-08-19) ----------------------------------------------
// The owner complaint was not "a leader is under its own badge" but "a leader is under SOME OTHER cluster".
// The invariant that answers it is a pairwise one: for ANY two badges, a displaced badge's leader paints
// above both. Paint order between panes IS their z-index order, so with ONE tail pane above every badge
// pane the pairwise claim reduces to two facts, and both are asserted against the shipped source: every
// leader is in the tail pane and no badge is, and the tail pane's z sits above the badge panes' z.
// (What a browser adds and this cannot: that the canvas actually rasterises in that order. The z-order is
// the mechanism, and it is what the render harness can honestly observe.)
const _tailPls = rAdded.filter(o => o.kind === "polyline");
const _badgeMks = rAdded.filter(o => o.kind === "marker");
ok(_tailPls.length > 1,
  "leaders-on-top fixture is vacuous: fewer than two leaders, so no PAIR of badges is exercised");
ok(_tailPls.every(p => p.opts.pane === A.BADGE_TAIL_PANE),
  "leaders-on-top: every leader must be in the single tail pane, got " +
  JSON.stringify([...new Set(_tailPls.map(p => p.opts.pane))]));
ok(new Set(_tailPls.map(p => p.opts.pane)).size === 1,
  "leaders-on-top: one tail pane, not one per survey - per-survey tail panes would re-create the " +
  "z-order-by-pane-creation accident the owner is complaining about");
ok(_badgeMks.every(m => m.opts.pane !== A.BADGE_TAIL_PANE),
  "leaders-on-top: a badge must NOT share the tail pane, or the leader/badge order becomes an accident again");
ok(A.BADGE_TAIL_PANE_Z > A.SURV_PANE_Z,
  "leaders-on-top: the tail pane z (" + A.BADGE_TAIL_PANE_Z + ") must sit ABOVE every badge pane z (" +
  A.SURV_PANE_Z + ") - that ordering IS the owner requirement");
// Every badge pane in the fixture carries the SAME z, so "above every badge pane" is one comparison and not
// a per-survey one. Pinned so a future per-survey z ramp cannot slip a badge above the leaders.
ok(new Set(_badgeMks.map(m => m.opts.pane)).size === _badgeMks.length,
  "leaders-on-top setup: each badge should still ride its own survey pane (that is what carries the dim)");
// THE DIM TRADE, pinned as a value rather than as prose: a leader whose survey is not the focused one must
// end up at exactly the opacity the old pane-inherited composition produced (tail alpha times the pane dim).
ok(Math.abs(A.tailOpacityFor("Other", "Focused") - A.BADGE_TAIL_OPACITY * A.MARKER_DIM_FILL) < 1e-12,
  "the per-tail dim must reproduce the pane composition exactly (" + A.BADGE_TAIL_OPACITY + " * " +
  A.MARKER_DIM_FILL + "), got " + A.tailOpacityFor("Other", "Focused"));
ok(A.tailOpacityFor("Focused", "Focused") === A.BADGE_TAIL_OPACITY,
  "the FOCUSED survey's leader must stay at full tail opacity");
ok(A.tailOpacityFor("Anything", null) === A.BADGE_TAIL_OPACITY,
  "with no focus every leader is at full tail opacity");
ok(A.tailOpacityFor("Other", "Focused") > 0,
  "Option A: a dimmed leader must stay VISIBLE, never hidden - a hidden leader would un-disclose a moved badge");
// The tail registry is what lets applySurveyDim reach leaders that no longer inherit a pane dim. If it were
// not refilled, a focus change with no re-render would leave every leader undimmed.
ok(renv._badgeTails.length === _tailPls.length,
  "every leader must be registered for the dim walk, got " + renv._badgeTails.length +
  " registered vs " + _tailPls.length + " drawn");
ok(renv._badgeTails.every(t => typeof t.survey === "string" && t.survey),
  "each registered leader must carry the survey its dim is keyed on");
ok(renv3._badgeTails.length === 0,
  "the registry must be CLEARED by a re-render, or leaders from a previous pass keep being dimmed");

// ---- THE PANE GUARD (production regression, 2026-08-19) -----------------------------------------
// A survey pane held only divIcons until a leader tail - an L.Path - was added to it, at which point
// Leaflet built a full-map-size canvas renderer inside it at z 600, above the station canvas at z 400, and
// no station on the map could be clicked. The guard makes that class of edit fail loudly instead of
// silently. Driven here as the PURE decision (pane name, is-it-a-path, interactive), which is exactly the
// three facts the runtime hook extracts from a layer.
A._decorationPanes.add("ausmt-sv-0");            // a survey pane, as _makeDecorationPane would have registered it
A._decorationPanes.add(A.BADGE_TAIL_PANE);
// (1) THE REGRESSION ITSELF: an interactive path in a survey pane must be refused.
const _viol = A._decorationPaneViolation("ausmt-sv-0", true, true);
ok(_viol && /INTERACTIVE path/.test(_viol),
  "the guard must refuse an interactive path in a survey pane (this is the shipped regression), got " +
  JSON.stringify(_viol));
ok(/ausmt-sv-0/.test(_viol), "the guard message must name the offending pane, got " + JSON.stringify(_viol));
// Leaflet's own default is interactive:true, i.e. OMITTED. The regression shipped with the flag omitted on
// nothing - the tail set it false - but a future edit is far more likely to omit it than to set it true.
ok(A._decorationPaneViolation("ausmt-sv-0", true, undefined),
  "an omitted interactive option is Leaflet's interactive:TRUE default and must be refused too");
// (2) The tail pane is guarded on the same terms: it is also a canvas pane over the stations.
ok(A._decorationPaneViolation(A.BADGE_TAIL_PANE, true, true),
  "the tail pane must be guarded exactly as the survey panes are - it carries a canvas over the stations too");
// (3) WHAT IS ALLOWED, so the guard is a rule and not a blanket refusal.
ok(A._decorationPaneViolation("ausmt-sv-0", true, false) === "",
  "a NON-interactive path is exactly what these panes are for and must pass");
ok(A._decorationPaneViolation("ausmt-sv-0", false, true) === "",
  "a DOM marker icon is interactive by design in these panes (Leaflet gives it pointer-events back) and must pass");
ok(A._decorationPaneViolation("overlayPane", true, true) === "",
  "the guard must not fire outside the decoration panes - station circleMarkers are interactive paths in overlayPane");
ok(A._decorationPaneViolation(undefined, true, true) === "",
  "a layer with no pane goes to Leaflet's defaults and is not this rule's business");
// (4) NON-VACUITY: the panes the guard protects are the ones the shipped code actually creates. Both names
//     come from the source, not from this file, so a rename cannot leave the guard pointing at nothing.
ok(A._decorationPanes.has(A.BADGE_TAIL_PANE),
  "the tail pane must be registered as a decoration pane by the shipped source");

// ---- BADGE CIRCLE SIZE (owner, 2026-08-19: 10% smaller circles, SAME label size) ------------------
// The owner asked for the circle and only the circle. This function sizes the DISC (it feeds iconSize);
// the label size is a CSS font-size on .ausmt-badge.svbadge-*, a separate authority, and the python side
// pins that those font sizes did not move. Here: the scale is real, it is applied to every tier, and the
// tier BOUNDARIES (which pick both the disc size and the CSS class, so the label) are untouched.
ok(A.BADGE_SIZE_SCALE === 0.90,
  "owner 2026-08-19: the badge circles are 10% smaller, so the scale is 0.90, got " + A.BADGE_SIZE_SCALE);
[[5, 34], [9, 34], [10, 42], [99, 42], [100, 52], [312, 52]].forEach(([n, base]) => {
  ok(Math.abs(A.badgeSizePx(n) - base * 0.90) < 1e-9,
    "a " + n + "-station badge must be 10% under its " + base + "px base, got " + A.badgeSizePx(n));
});
// Monotone non-decreasing in count, as it was before the scale (a bigger survey never gets a smaller disc).
ok(A.badgeSizePx(5) < A.badgeSizePx(50) && A.badgeSizePx(50) < A.badgeSizePx(500),
  "the badge size ramp must stay monotone in station count after the scale");
// The three-digit worst case, which is what the owner asked to be checked. Counts of 100+ land in the LARGE
// tier by construction, so the widest label always gets the widest disc - a three-digit count can never fall
// into the small tier. Pinned as an ordering fact rather than as a font measurement (that is the browser's
// business and is reported separately): the label is unchanged, so the only question is which disc it lands
// in, and the answer is the biggest one.
ok(A.badgeSizePx(100) === A.badgeSizePx(999) && A.badgeSizePx(999) > A.badgeSizePx(99),
  "every three-digit count must land in the LARGEST badge tier, so the widest label gets the widest disc");
// The declutter separates by these radii, so a smaller disc must mean a smaller separation requirement -
// this is why the overlap counts move at all, and it is asserted rather than assumed.
ok(A.badgeSizePx(312) / 2 < 52 / 2,
  "the declutter radius must follow the smaller disc, or the badges would still be separated by the old size");

// ---- composition with change 2 ------------------------------------------------------------------
// Badges live in their survey's pane, so the dim decision is the SAME function for both. Pin that the
// decision does not distinguish them (there is one rule, keyed on survey, not on marker kind).
ok(A.dimStyleFor("Compact", "Compact").fillOpacity > A.dimStyleFor("Spread", "Compact").fillOpacity,
  "the focus dim must dim a non-focused survey, for badges exactly as for dots");

if (failed) { console.error(failed + " badge assertion(s) failed"); process.exit(1); }
console.log("MAP BADGES OK");
