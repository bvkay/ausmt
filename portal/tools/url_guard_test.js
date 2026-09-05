// URL/HTML guard driver: the two allowlist edges the client owns, run for real against the shipped
// portal/src/security.js and portal/src/map.js.
//
// WHY THIS EXISTS SEPARATELY from tools/interaction_test.js: both surfaces here are decisions, not
// renders. escUrl is a pure allowlist and the layer attribution is a pure string build, so they are
// driven directly over a VECTOR TABLE rather than fished out of assembled DOM. A vector that flips
// reds by name, which is what a security allowlist needs from its pin.
//
// SECTION A (escUrl, security.js). Every href the portal emits passes this allowlist, and a
// related-identifier of identifier_type URL reaches it as a RAW third-party field (drawer.js:1249).
// The table below is the whole contract: what may become an anchor, and what must collapse to "#".
//
// SECTION B (userLayer, map.js). Leaflet's addAttribution renders its argument as HTML. The layer
// control is not mounted today, so the fetch never runs; the pin drives the REAL userLayer handler
// with hostile GeoJSON anyway, so the guard is proven before a revisit re-enables the control.
//
//   node tools/url_guard_test.js
// Exit 0 = passed, 1 = a real failure.
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm");

const SRC = path.join(path.resolve(__dirname, ".."), "src");
const securitySrc = fs.readFileSync(path.join(SRC, "security.js"), "utf8");
const mapSrc = fs.readFileSync(path.join(SRC, "map.js"), "utf8");

let failed = 0;
function ok(cond, msg) { if (!cond) { console.error("URL GUARD FAILED: " + msg); failed++; } }

// ---- Section A: escUrl over the vector table -------------------------------------------------------
const actx = { console, String, RegExp, JSON };
actx.globalThis = actx;
vm.createContext(actx);
vm.runInContext(securitySrc + "\nglobalThis.__api={esc,escUrl};", actx);
const esc = actx.__api.esc, escUrl = actx.__api.escUrl;
ok(typeof escUrl === "function", "escUrl must load from security.js");

// ACCEPTED: a same-origin path or an explicit http(s)/mailto/fragment target. The value survives as
// itself, entity-escaped for the attribute it is about to sit in.
const ACCEPT = [
  ["absolute https", "https://doi.org/10.25914/sv5r-zw68"],
  ["absolute http", "http://example.test/x"],
  ["scheme case is ignored", "HTTPS://EXAMPLE.TEST/x"],
  ["mailto", "mailto:ben@example.test"],
  ["fragment", "#frag"],
  ["site root", "/"],
  ["one-segment path", "/x"],
  ["boot artifact", "/data/catalogue.json"],
  ["hand-off route", "/go/ts/demo/ST1/level0"],
  ["query string is escaped, not rejected", "/x?a=1&b=2"],
];
// REJECTED: everything else collapses to "#". The scheme rows were already true and must stay true;
// the slash rows are the protocol-relative gap (a leading // is an OFF-SITE authority, not a path).
const REJECT = [
  ["javascript scheme", "javascript:alert(1)"],
  ["javascript behind leading whitespace", "\tjavascript:alert(1)"],
  ["javascript in upper case", "JAVASCRIPT:alert(1)"],
  ["data document", "data:text/html,<script>alert(1)</script>"],
  ["vbscript scheme", "vbscript:msgbox(1)"],
  ["protocol-relative host", "//evil.example.com"],
  ["protocol-relative host with a path", "//evil.example.com/logo.png"],
  ["bare double slash", "//"],
  ["triple slash", "///x"],
  // Browsers fold a backslash to a forward slash while parsing an http(s) URL, so /\host resolves to
  // the same off-site authority as //host and must be refused on the same ground.
  ["backslash authority", "/\\evil.example.com"],
  ["backslash authority, doubled", "/\\\\evil.example.com"],
  ["leading backslashes", "\\\\evil.example.com"],
  ["backslash then slash", "\\/evil.example.com"],
  ["relative path behind leading whitespace", " /x"],
  ["bare relative path", "x/y"],
  ["empty", ""],
];

for (const [name, v] of ACCEPT) {
  const want = esc(v);
  ok(escUrl(v) === want,
    "ACCEPT [" + name + "] " + JSON.stringify(v) + " -> " + JSON.stringify(escUrl(v)) +
    ", want " + JSON.stringify(want));
  // An accepted vector whose escaped form IS "#" could not tell acceptance from rejection apart.
  ok(want !== "#", "ACCEPT [" + name + "] is a vacuous vector (its escaped form is the reject value)");
}
for (const [name, v] of REJECT) {
  ok(escUrl(v) === "#",
    "REJECT [" + name + "] " + JSON.stringify(v) + " -> " + JSON.stringify(escUrl(v)) + ", want \"#\"");
}
// A missing value is an absent link, never an inherited one.
ok(escUrl(null) === "#" && escUrl(undefined) === "#", "a null/undefined href must collapse to \"#\"");

// ---- Section B: the map attribution sink ------------------------------------------------------------
// map.js builds a Leaflet map at load, so pull userLayer out by name and run it alone (the
// tools/map_dots_test.js idiom). If the name ever stops existing this throws loudly rather than
// silently testing nothing.
function grabFn(name, required) {
  const start = mapSrc.search(new RegExp("^function\\s+" + name + "\\s*\\(", "m"));
  if (start < 0) {
    if (!required) return "";
    console.error("URL GUARD FAILED: function " + name + " not found in map.js");
    process.exit(1);
  }
  let i = mapSrc.indexOf("{", start), depth = 0, end = -1, inStr = null;
  for (let j = i; j < mapSrc.length; j++) {
    const c = mapSrc[j], prev = mapSrc[j - 1];
    if (inStr) { if (c === inStr && prev !== "\\") inStr = null; continue; }
    if (c === '"' || c === "'" || c === "`") { inStr = c; continue; }
    if (c === "{") depth++;
    else if (c === "}") { depth--; if (depth === 0) { end = j + 1; break; } }
  }
  if (end < 0) { console.error("URL GUARD FAILED: could not extract " + name); process.exit(1); }
  return mapSrc.slice(start, end) + "\n";
}

const HOSTILE_SRC = '<img src=x onerror=alert(1)>Survey source';
const HOSTILE_NAME = '<b onmouseover=alert(2)>States</b>';

function runLayer(name, geojson) {
  const attributions = [], toasts = [];
  let handler = null;
  const grp = { _loaded: false, on: (ev, fn) => { if (ev === "add") handler = fn; return grp; } };
  const bctx = {
    console, String, RegExp, JSON, Promise,
    L: { featureGroup: () => grp, geoJSON: () => ({ addTo: () => ({}) }) },
    map: { attributionControl: { addAttribution: (s) => attributions.push(s) } },
    toast: (m) => toasts.push(m),
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve(geojson) }),
  };
  bctx.globalThis = bctx;
  vm.createContext(bctx);
  vm.runInContext(securitySrc + "\nconst userLayers={};\n" +
    grabFn("_layerAttribution", false) + grabFn("userLayer", true) +
    "\nglobalThis.__mk=userLayer;", bctx);
  bctx.__mk(name, "states.geojson", "#8FA3B0");
  if (!handler) { console.error("URL GUARD FAILED: userLayer registered no 'add' handler"); process.exit(1); }
  return Promise.resolve(handler()).then(() => ({ attributions, toasts }));
}

// The GeoJSON files are operator-placed, but they are FILE CONTENT reaching an HTML sink, so the
// attribution is escaped on the same terms as any survey field.
runLayer(HOSTILE_NAME, { type: "FeatureCollection", features: [], source: HOSTILE_SRC })
  .then((r) => {
    ok(r.attributions.length === 1,
      "the layer must publish exactly one attribution, got " + r.attributions.length +
      " (toasts: " + JSON.stringify(r.toasts) + ")");
    const a = r.attributions[0] || "";
    ok(a.indexOf("<img") < 0 && a.indexOf("<b ") < 0,
      "a top-level GeoJSON source must reach addAttribution ESCAPED, got " + JSON.stringify(a));
    ok(a.indexOf("&lt;img") >= 0, "the escaped source text must survive, got " + JSON.stringify(a));
    ok(a.indexOf("&lt;b") >= 0, "the layer NAME must be escaped on the same terms, got " + JSON.stringify(a));
    // The fallback reads the same field off the first feature and lands in the same sink.
    return runLayer("States", {
      type: "FeatureCollection",
      features: [{ type: "Feature", properties: { source: HOSTILE_SRC }, geometry: null }],
    });
  })
  .then((r) => {
    const a = r.attributions[0] || "";
    ok(r.attributions.length === 1, "the per-feature source fallback must publish one attribution");
    ok(a.indexOf("<img") < 0, "a per-feature GeoJSON source must reach addAttribution ESCAPED, got " + JSON.stringify(a));
    // A benign source must arrive intact, or the guard would be paid for by garbled attributions.
    return runLayer("Cratons", { type: "FeatureCollection", features: [], source: "Geoscience Australia 2024" });
  })
  .then((r) => {
    ok(r.attributions[0] === "Cratons: Geoscience Australia 2024",
      "a benign attribution must render verbatim, got " + JSON.stringify(r.attributions[0]));
    // No source field is no attribution, not an empty one.
    return runLayer("Cratons", { type: "FeatureCollection", features: [] });
  })
  .then((r) => {
    ok(r.attributions.length === 0,
      "a layer with no source field must publish no attribution, got " + JSON.stringify(r.attributions));
    if (failed) { console.error("URL GUARD FAILED: " + failed + " pin(s)"); process.exit(1); }
    console.log("URL GUARD OK");
  })
  .catch((e) => { console.error("URL GUARD FAILED: " + ((e && e.stack) || e)); process.exit(1); });
