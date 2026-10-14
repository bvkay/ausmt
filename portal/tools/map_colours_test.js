// Map colours driver: what the SPA map draws outside the stylesheet, run against the shipped
// portal/src/map.js with Leaflet and protomaps stubbed.
//
// The stylesheet colours everything CSS can reach; the basemap and the selection shapes are outside
// it. This boots map.js in a vm with a recording map, a recording protomaps layer factory and the
// token table, and asserts what was drawn:
//
//   BASEMAP   the pmtiles pair is mounted once, in the light flavour, under one credit;
//   SHAPES    the draw tool's shape colour is the --accent token;
//   NO SWITCH map.js listens for no appearance change on document.
//
//   node tools/map_colours_test.js
// Exit 0 = passed, 1 = a real failure.
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm");

const SRC = path.join(path.resolve(__dirname, ".."), "src");
const TOKENS = { "--dot-edge": "#231F20", "--accent": "#282572" };

let fail = 0;
const ok = (cond, msg) => { console.log((cond ? "  ok   " : "  FAIL ") + msg); if (!cond) fail++; };

const stub = () => new Proxy(function () {}, {
  get: (t, p) => { if (p === "then") return undefined; if (p === Symbol.iterator) return function* () {}; return stub(); },
  apply: () => stub(), construct: () => stub(),
});

// The map: records which layers are on it, and answers everything else with a stub.
const onMap = new Set(), removed = [];
const map = new Proxy({}, {
  get: (t, p) => {
    if (p === "removeLayer") return (l) => { removed.push(l); onMap.delete(l); return map; };
    if (p === "addLayer") return (l) => { onMap.add(l); return map; };
    if (p === "fitBounds" || p === "on" || p === "addControl") return () => map;
    if (p === "getContainer") return () => null;
    return stub();
  },
});

// protomaps: each layer records the flavour it was built with and joins the map on addTo.
const built = [];
const protomapsL = {
  leafletLayer: (opts) => {
    const layer = { flavor: opts.flavor, attribution: opts.attribution, addTo: (m) => { m.addLayer(layer); return layer; } };
    built.push(layer);
    return layer;
  },
};

// The draw control records the options it is built with.
const L = new Proxy(function () {}, {
  get: (t, p) => {
    if (p === "map") return () => map;
    if (p === "FeatureGroup") return function () { return { addTo: () => ({}) }; };
    if (p === "Control") return { Draw: function (opts) { this.opts = opts; } };
    if (p === "drawLocal") return { draw: { toolbar: { buttons: {} } }, edit: { toolbar: { buttons: {} } } };
    return stub();
  },
});

const listeners = {};
const ctx = {
  L, window: { AUSMT_CONFIG: { basemap: { provider: "pmtiles" } }, protomapsL, AusmtMapAttrib: { mount() {} } },
  protomapsL,
  document: {
    documentElement: { getAttribute: () => null },
    addEventListener: (type, fn) => { listeners[type] = fn; },
    getElementById: () => null, querySelectorAll: () => [],
  },
  getComputedStyle: () => ({ getPropertyValue: (name) => TOKENS[name] || "" }),
  ST: [],
  console, Math, Object, Array, JSON, Set,
};
ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(SRC, "map.js"), "utf8"), ctx);

ok(built.length === 2 && built.every(l => l.flavor === "light"),
  "the pmtiles pair is mounted in the light flavour, got " + JSON.stringify(built.map(l => l.flavor)));
ok(built.every(l => onMap.has(l)) && removed.length === 0, "both layers are on the map and none is removed");
ok(new Set(built.map(l => l.attribution)).size === 1, "the two layers state one credit, so Leaflet prints it once");
const draw = vm.runInContext("drawControl", ctx);
ok(draw.opts.draw.rectangle.shapeOptions.color === TOKENS["--accent"] &&
   draw.opts.draw.polygon.shapeOptions.color === TOKENS["--accent"],
  "the draw tool's shape colour is the --accent token, got " + draw.opts.draw.rectangle.shapeOptions.color);
ok(Object.keys(listeners).length === 0, "map.js listens for nothing on document, got " + JSON.stringify(Object.keys(listeners)));

if (fail) { console.error("MAP COLOURS FAILED: " + fail + " assertion(s)"); process.exit(1); }
console.log("MAP COLOURS OK");
