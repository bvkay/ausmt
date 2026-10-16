// Map zoom driver: the zoom floor, the pan box and the basemap at the floor, run against the shipped
// portal/src/map.js on the REAL vendored Leaflet in jsdom.
//
// WHY REAL LEAFLET. The floor and the box are Leaflet behaviour: a minZoom option is only a claim until
// zoomOut stops at it, and a maxBounds option is only a claim until a pan is held inside it and the
// fitted home view is left where it was. The interaction driver stubs Leaflet, so it can pin the options
// the map is built with but none of what they do. Here map.js is evaluated whole, with leaflet.js and
// leaflet.draw.js loaded first, into a #map container given the sizes the browser measured for the map
// pane (the viewport less the header, the sidebar and the footer).
//
// HONESTY: jsdom has no layout and no canvas. The container sizes are set, not laid out, and no marker
// is drawn; what runs is Leaflet's own zoom, projection and bounds arithmetic, which is what the floor
// and the box are made of.
//
//   node tools/map_zoom_test.js
//
// Requires jsdom (dev-only; the shipped portal has none). Exit codes:
//   0 = passed   1 = a real failure   2 = jsdom missing (caller SKIPs, not fails)
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm");
let JSDOM;
try { ({ JSDOM } = require("jsdom")); }
catch (e) { console.error("SKIP: jsdom not installed (run `npm ci` in portal/)"); process.exit(2); }

const PORTAL = path.resolve(__dirname, "..");
const LEAFLET = fs.readFileSync(path.join(PORTAL, "vendor", "leaflet.js"), "utf8");
const DRAW = fs.readFileSync(path.join(PORTAL, "vendor", "leaflet.draw.js"), "utf8");
const MAP_SRC = fs.readFileSync(path.join(PORTAL, "src", "map.js"), "utf8");

let failed = 0;
function ok(cond, msg) { if (!cond) { console.error("MAP ZOOM FAILED: " + msg); failed++; } }

// The map pane sizes headless Chrome measured (map.getSize()) on the three viewports the portal is
// checked on: a 1280 x 800 and a 1024 x 768 desktop beside the sidebar, and a 375 x 812 phone.
const PANES = { "1280x800": [824, 686], "1024x768": [655, 654], "375x812": [375, 760] };
// The served extent of the full corpus build (15,265 stations), measured from its catalogue.json.
const SERVED = { s: -43.444933, n: -12.377, w: 113.665, e: 166.183 };

// Boot map.js in a fresh window whose #map pane is w x h. `provider` picks the basemap branch; the
// pmtiles branch is given a protomapsL whose layers are real Leaflet GridLayers built from the options
// map.js passes, so their tile range acts as it does under the vendored renderer.
function boot(w, h, provider, stations) {
  const dom = new JSDOM('<!doctype html><html><body><div id="map"></div></body></html>',
    { url: "http://localhost/", runScripts: "outside-only", pretendToBeVisual: true });
  const win = dom.window, el = win.document.getElementById("map");
  Object.defineProperty(el, "clientWidth", { get: () => w });
  Object.defineProperty(el, "clientHeight", { get: () => h });
  const vctx = dom.getInternalVMContext();
  vm.runInContext(LEAFLET, vctx);
  vm.runInContext(DRAW, vctx);
  const pm = [];
  win.AUSMT_CONFIG = { basemap: { provider } };
  win.protomapsL = { leafletLayer: (o) => { pm.push(o); return win.L.gridLayer(o); } };
  win.AusmtMapAttrib = { mount() {} };
  win.ST = stations || [];
  win.TYPE_COL = { LPMT: "#3F88C8" };
  win.esc = (s) => String(s);
  vm.runInContext(MAP_SRC, vctx);
  const get = (expr) => vm.runInContext(expr, vctx);
  return { win, get, pm, map: get("map"), L: win.L };
}
// The tile layers a booted map carries, in the order they were added.
function tileLayers(b) {
  const out = [];
  b.map.eachLayer(l => { if (l instanceof b.L.GridLayer) out.push(l); });
  return out;
}
// Whether a layer would request tile (x, y) at zoom z, by Leaflet's own test.
function tileValid(b, layer, x, y, z) {
  b.map.setZoom(z, { animate: false });
  layer._resetGrid();
  const c = b.L.point(x, y); c.z = z;
  return layer._isValidTile(c);
}

// ---- the zoom floor -------------------------------------------------------------------------------
const fitted = {};
for (const [name, [w, h]] of Object.entries(PANES)) {
  const b = boot(w, h, "carto");
  fitted[name] = b.map.getBoundsZoom(b.get("AU_HOME_BOUNDS"));
  ok(b.map.getZoom() === fitted[name], name + ": the map opens at the zoom that fits the home frame (" +
    fitted[name] + "), got " + b.map.getZoom());
  // Zooming out past the floor stays at the floor, by the button and by a direct request alike.
  for (let i = 0; i < 8; i++) b.map.zoomOut(1, { animate: false });
  ok(b.map.getZoom() === 3, name + ": eight zoom-outs stop at the floor 3, got " + b.map.getZoom());
  b.map.setZoom(0, { animate: false });
  ok(b.map.getZoom() === 3, name + ": a request for zoom 0 stays at the floor 3, got " + b.map.getZoom());
}
ok(JSON.stringify(fitted) === JSON.stringify({ "1280x800": 4, "1024x768": 4, "375x812": 3 }),
  "the home frame fits at 4 / 4 / 3 on the three panes, got " + JSON.stringify(fitted));
{
  const b = boot(824, 686, "carto");
  ok(b.map.options.minZoom === Math.min(...Object.values(fitted)) && b.map.getMinZoom() === 3,
    "the floor is the smallest fitted zoom, so a phone still sees the whole continent, got minZoom " +
    b.map.options.minZoom);
}

// ---- the pan box ----------------------------------------------------------------------------------
{
  const b = boot(824, 686, "carto");
  const mb = b.map.options.maxBounds;
  ok(mb && typeof mb.contains === "function", "the map is built with a maxBounds box");
  ok(b.map.options.maxBoundsViscosity === 1, "a drag is held solid at the box edge, got viscosity " +
    b.map.options.maxBoundsViscosity);
  if (mb && typeof mb.contains === "function") {
    // Generous: every served station with at least 10 degrees to spare on every side.
    ok(mb.contains(b.L.latLngBounds([[SERVED.s - 10, SERVED.w - 10], [SERVED.n + 10, SERVED.e + 10]])),
      "the box holds the served extent padded by 10 degrees, got " + mb.toBBoxString());
    // A request for a view far from the data is pulled back inside the box.
    b.map.setView([10, 30], 5, { animate: false });
    const c = b.map.getCenter();
    ok(mb.contains(c) && c.lng > 80, "a view requested over Africa is held inside the box, got " + c.lng + "," + c.lat);
    b.map.setView([-28, 133], 6, { animate: false });
    b.map.panBy([-100000, 0], { animate: false });
    ok(mb.contains(b.map.getBounds()), "a pan far west comes to rest with the whole view inside the box, got " +
      b.map.getBounds().toBBoxString());
  }
}
// The box never moves the fitted home view: each pane opens on the same centre and zoom as a map with
// no box, because the box is centred on the home frame (longitude linearly, latitude in Mercator).
for (const [name, [w, h]] of Object.entries(PANES)) {
  const b = boot(w, h, "carto");
  const el2 = b.win.document.createElement("div");
  Object.defineProperty(el2, "clientWidth", { get: () => w });
  Object.defineProperty(el2, "clientHeight", { get: () => h });
  b.win.document.body.appendChild(el2);
  const plain = b.L.map(el2, { minZoom: 3 }).fitBounds(b.get("AU_HOME_BOUNDS"));
  b.map.fitBounds(b.get("AU_HOME_BOUNDS"));
  plain.fitBounds(b.get("AU_HOME_BOUNDS"));
  const p1 = b.map.project(b.map.getCenter()), p2 = plain.project(plain.getCenter(), b.map.getZoom());
  ok(b.map.getZoom() === plain.getZoom() && Math.abs(p1.x - p2.x) <= 1 && Math.abs(p1.y - p2.y) <= 1,
    name + ": the box leaves the home view where a map without one puts it, got " +
    JSON.stringify({ zoom: [b.map.getZoom(), plain.getZoom()], dx: p1.x - p2.x, dy: p1.y - p2.y }));
  // At the floor the box is narrower than a desktop pane, and Leaflet centres it: still the home centre.
  b.map.setZoom(3, { animate: false }); plain.setZoom(3, { animate: false });
  const q1 = b.map.project(b.map.getCenter()), q2 = plain.project(plain.getCenter(), 3);
  ok(Math.abs(q1.x - q2.x) <= 1 && Math.abs(q1.y - q2.y) <= 1,
    name + ": at the floor the view stays on the home centre, got " + JSON.stringify({ dx: q1.x - q2.x, dy: q1.y - q2.y }));
}
// A build with a station outside the box drops the box rather than strand that station.
{
  const inside = [{ i: 0, id: "A", survey: "S", type: "LPMT", lat: -30, lon: 136 }];
  const b1 = boot(824, 686, "carto", inside);
  b1.get("buildMarkers()");
  ok(!!b1.map.options.maxBounds, "a build whose stations all lie inside the box keeps it");
  const outside = inside.concat([{ i: 1, id: "B", survey: "S", type: "LPMT", lat: 20, lon: 136 }]);
  const b2 = boot(824, 686, "carto", outside);
  b2.get("buildMarkers()");
  ok(!b2.map.options.maxBounds, "a build with a station outside the box drops the box, got " +
    (b2.map.options.maxBounds && b2.map.options.maxBounds.toBBoxString()));
}

// ---- one world, never repeated, never cut short ---------------------------------------------------

// At the floor the world is wider than every measured pane, so its copies can never sit side by side.
// The view may still cross the antimeridian (zoom 3 on a desktop pane reaches past 180 E), and every
// tile it covers there must be drawn, not left as a blank band.
for (const [name, [w, h]] of Object.entries(PANES)) {
  const b = boot(w, h, "carto");
  ok(256 * Math.pow(2, b.get("MAP_MIN_ZOOM")) > w,
    name + ": at the floor the world is wider than the pane, got " + 256 * Math.pow(2, b.get("MAP_MIN_ZOOM")) + " <= " + w);
}
for (const provider of ["pmtiles", "carto"]) {
  for (const [name, [w, h]] of Object.entries(PANES)) {
    const b = boot(w, h, provider);
    const layers = tileLayers(b);
    ok(layers.length === (provider === "pmtiles" ? 2 : 1), provider + ": the basemap layer count, got " + layers.length);
    b.map.setZoom(3, { animate: false });
    const pb = b.map.getPixelBounds();
    const x0 = Math.floor(pb.min.x / 256), x1 = Math.floor((pb.max.x - 1) / 256);
    const y0 = Math.max(0, Math.floor(pb.min.y / 256)), y1 = Math.min(7, Math.floor((pb.max.y - 1) / 256));
    // The z3 world layer is the one that draws here (the pmtiles region layer starts at z7).
    const l = layers[0], missing = [];
    for (let x = x0; x <= x1; x++) for (let y = y0; y <= y1; y++) if (!tileValid(b, l, x, y, 3)) missing.push([x, y]);
    ok(missing.length === 0, provider + " " + name + ": every tile in the floor view is drawn (x " + x0 + " to " + x1 +
      "), missing " + JSON.stringify(missing));
  }
}

if (failed) { console.error(failed + " map-zoom assertion(s) failed"); process.exit(1); }
console.log("MAP ZOOM OK");
