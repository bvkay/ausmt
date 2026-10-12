// Map theme driver: what the SPA map redraws when the appearance changes, run against the shipped
// portal/src/map.js with Leaflet and protomaps stubbed.
//
// The stylesheet themes everything CSS can reach; three things the map draws are outside it, and
// src/theme.js announces a change with "ausmt:theme" on document for exactly those. This boots map.js
// in a vm with a recording map, a recording protomaps layer factory, two theme token tables and one
// station marker, then fires the event and asserts what was redrawn:
//
//   BASEMAP   the pmtiles pair is mounted at start in the resolved theme's flavour, and a change
//             removes both layers and mounts the pair again in the new flavour;
//   DOT EDGE  every station marker's edge is restyled to the new --dot-edge token;
//   SHAPES    the draw tool's shape colour and every drawn shape follow the new --accent token.
//
//   node tools/map_theme_test.js
// Exit 0 = passed, 1 = a real failure.
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm");

const SRC = path.join(path.resolve(__dirname, ".."), "src");
const TOKENS = {
  light: { "--dot-edge": "#231F20", "--accent": "#282572" },
  dark: { "--dot-edge": "#11182D", "--accent": "#EF7256" },
};

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

// The draw control records the drawing options it is given; drawn shapes record their restyle.
const drawingOptions = [];
const drawnShape = { color: null, setStyle(o) { this.color = o.color; } };
const L = new Proxy(function () {}, {
  get: (t, p) => {
    if (p === "map") return () => map;
    if (p === "FeatureGroup") return function () { return { addTo: () => ({ eachLayer: (fn) => fn(drawnShape) }) }; };
    if (p === "Control") return { Draw: function (opts) { this.opts = opts; this.setDrawingOptions = (o) => drawingOptions.push(o); } };
    if (p === "drawLocal") return { draw: { toolbar: { buttons: {} } }, edit: { toolbar: { buttons: {} } } };
    return stub();
  },
});

let theme = "light";
const listeners = {};
const marker = { color: null, setStyle(o) { if (o.color) this.color = o.color; } };
const ctx = {
  L, window: { AUSMT_CONFIG: { basemap: { provider: "pmtiles" } }, protomapsL, AusmtMapAttrib: { mount() {} } },
  protomapsL,
  document: {
    documentElement: { getAttribute: (n) => (n === "data-theme" ? theme : null) },
    addEventListener: (type, fn) => { listeners[type] = fn; },
    getElementById: () => null, querySelectorAll: () => [],
  },
  getComputedStyle: () => ({ getPropertyValue: (name) => TOKENS[theme][name] || "" }),
  ST: [{ marker }],
  console, Math, Object, Array, JSON, Set,
};
ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(SRC, "map.js"), "utf8"), ctx);

ok(built.length === 2 && built.every(l => l.flavor === "light"),
  "the pmtiles pair is mounted at start in the resolved theme's flavour, got " + JSON.stringify(built.map(l => l.flavor)));
ok(built.every(l => onMap.has(l)), "both layers of the starting pair are on the map");
ok(new Set(built.map(l => l.attribution)).size === 1, "the two layers state one credit, so Leaflet prints it once");
const draw = vm.runInContext("drawControl", ctx);
ok(draw.opts.draw.rectangle.shapeOptions.color === TOKENS.light["--accent"],
  "the draw tool's shape colour is the light --accent at start, got " + draw.opts.draw.rectangle.shapeOptions.color);

ok(typeof listeners["ausmt:theme"] === "function", 'map.js listens for "ausmt:theme" on document');
const first = built.slice();
theme = "dark";
listeners["ausmt:theme"]({ detail: { theme: "dark" } });

ok(first.every(l => removed.includes(l) && !onMap.has(l)), "a theme change removes both layers of the old pair");
const second = built.slice(2);
ok(second.length === 2 && second.every(l => l.flavor === "dark" && onMap.has(l)),
  "and mounts the pair again in the dark flavour, got " + JSON.stringify(second.map(l => l.flavor)));
ok(marker.color === TOKENS.dark["--dot-edge"], "every station marker takes the dark --dot-edge, got " + marker.color);
const opts = drawingOptions[drawingOptions.length - 1] || {};
ok(opts.rectangle && opts.rectangle.shapeOptions.color === TOKENS.dark["--accent"] &&
   opts.polygon && opts.polygon.shapeOptions.color === TOKENS.dark["--accent"],
  "the draw tool's shapes take the dark --accent, got " + JSON.stringify(opts));
ok(drawnShape.color === TOKENS.dark["--accent"], "a shape already drawn is restyled too, got " + drawnShape.color);

if (fail) { console.error("MAP THEME FAILED: " + fail + " assertion(s)"); process.exit(1); }
console.log("MAP THEME OK");
