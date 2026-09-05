// jsdom-backed DRIVEN test for add-survey.html's three maps and the collapsed attribution control
// each of them wears.
//
// WHY A DRIVER AND NOT MORE SOURCE PINS. tests/test_map_attribution.py can read that the page asks
// for a control and that a module builds one; it cannot see whether the control reaches the DOM,
// whether it starts collapsed, whether a click or a keyboard focus opens it, or what it ends up
// printing. Those are the actual ask, so they are driven here: the real page, the real
// module, a real DOM, and the page's own buttons pressed to build each map.
//
// The three maps are the footprint PICKER (a modal, opened by "Pick on map"), the station PREVIEW
// (built inline the moment a file with coordinates lands) and the CONFIRMATION map (a second modal).
// All three are reached the way a contributor reaches them.
//
// HONESTY, stated once: jsdom has no layout and no compositor. "Collapsed" is asserted as the state
// the page is in (the open class absent, aria-expanded false, the credit's element present but
// unrevealed), not as a measured box; the box is a browser measurement recorded with the round's
// screenshots. What IS proven here is that the control exists, that it carries no Leaflet flag or
// prefix, that it names the source the layer declared, and that both a pointer and a keyboard open
// and close it.
//
//   node tools/map_attribution_test.js
//
// Requires jsdom (dev-only; the shipped portal has none). Exit codes:
//   0 = passed   1 = a real failure   2 = jsdom missing (caller SKIPs, not fails)
const fs = require("fs"), path = require("path"), vm = require("vm");
let JSDOM;
try { ({ JSDOM } = require("jsdom")); }
catch (e) { console.error("SKIP: jsdom not installed (run `npm ci` in portal/)"); process.exit(2); }

const TOOLS = __dirname;
const PORTAL = path.resolve(TOOLS, "..");
const SRC = path.join(PORTAL, "src");
const html = fs.readFileSync(path.join(PORTAL, "add-survey.html"), "utf8");

let fail = 0;
const ok = (cond, msg) => { console.log((cond ? "  ok   " : "  FAIL ") + msg); if (!cond) fail++; };
const die = (msg) => { console.error("MAP-ATTRIBUTION TEST FAILED: " + msg); process.exit(1); };

// A clean-decimal EDI, so the page plots it and the station preview map is built.
const EDI_TEXT = '>HEAD\nDATAID="S01"\nLAT=-30.10\nLONG=136.20\n\n>FREQ\n1 10 100\n>ZXYR\n1 2 3\n';

// ---- The Leaflet stand-in -----------------------------------------------------------------------
// Everything the page's map paths touch degenerates to a chainable stub EXCEPT the three members
// this test is about: L.map (so a map object exists to mount onto), L.tileLayer (so the layer's OWN
// declared credit is observable, which is the property the whole rule turns on) and
// L.control.attribution (which gets a REAL container, because the collapsed control is assembled in
// the DOM and under a blanket stub there would be no node to assemble it on and every assertion
// about it would be vacuous).
function makeLeaflet(win) {
  const stub = () => new Proxy(function () { }, {
    get: (t, p) => {
      if (p === "then") return undefined;
      if (p === Symbol.iterator) return function* () { };
      return stub();
    },
    apply: () => stub(), construct: () => stub(),
  });
  const maps = [];          // { id, opts, layers, control }
  const controls = [];      // the attribution controls, in construction order

  const makeMap = (id, opts) => {
    const m = { id, opts: opts || {}, layers: [], control: null };
    // The map's own methods CHAIN back to the map, the way Leaflet's do: the page writes
    // `L.map(...).setView(...)` and holds what that returns, so a stub that answered setView with a
    // fresh stub would hand every later call a different object and nothing could be recorded.
    const CHAIN = ["setView", "fitBounds", "invalidateSize", "on", "off", "removeLayer",
      "addControl", "removeControl", "eachLayer", "setMaxBounds"];
    m.api = new Proxy(function () { }, {
      get: (t, p) => {
        if (p === "then") return undefined;
        if (p === Symbol.iterator) return function* () { };
        if (p === "__rec") return m;
        if (p === "addLayer") return (l) => { m.layers.push(l); return m.api; };
        if (CHAIN.indexOf(p) >= 0) return () => m.api;
        return stub();
      },
      apply: () => stub(), construct: () => stub(),
    });
    maps.push(m);
    return m.api;
  };

  const makeTile = (url, o) => {
    const own = { url, options: o || {} };
    own.getAttribution = () => own.options.attribution;
    own.api = new Proxy(function () { }, {
      get: (t, p) => {
        if (p === "then") return undefined;
        if (p === Symbol.iterator) return function* () { };
        if (p === "getAttribution") return own.getAttribution;
        if (p === "addTo") return (m) => { if (m && m.__rec) m.__rec.layers.push(own); return own.api; };
        return stub();
      },
      apply: () => stub(), construct: () => stub(),
    });
    return own.api;
  };

  // Leaflet's own Control.Attribution, reduced to the three behaviours this test depends on: it
  // renders into a container of its own, it collects each layer's declared attribution, and it
  // prints the prefix ONLY when options.prefix is truthy. The last one is what makes "no Leaflet
  // flag" a real assertion rather than a restatement of the option.
  const makeAttribution = (opts) => {
    const own = { options: opts || {}, credits: [] };
    own.container = win.document.createElement("div");
    own.container.className = "leaflet-control-attribution leaflet-control";
    own.update = () => {
      const parts = [];
      if (own.options.prefix) parts.push(own.options.prefix);
      if (own.credits.length) parts.push(own.credits.join(", "));
      own.container.innerHTML = parts.join(' <span aria-hidden="true">|</span> ');
    };
    own.addAttribution = (s) => {
      if (typeof s === "string" && s && own.credits.indexOf(s) < 0) own.credits.push(s);
      own.update();
      return own.api;
    };
    own.api = new Proxy(function () { }, {
      get: (t, p) => {
        if (p === "then") return undefined;
        if (p === Symbol.iterator) return function* () { };
        if (p === "options") return own.options;
        if (p === "getContainer") return () => own.container;
        if (p === "addAttribution") return own.addAttribution;
        if (p === "addTo") return (m) => {
          // Leaflet appends the control into the map's own corner and then reads every layer
          // already on the map. jsdom runs no Leaflet, so the map container stands in for the
          // corner; what matters to this test is that the control lands INSIDE the map element,
          // which is where a reader would find it.
          const host = m && m.__rec ? win.document.getElementById(m.__rec.id) : null;
          (host || win.document.body).appendChild(own.container);
          if (m && m.__rec) {
            m.__rec.control = own;
            m.__rec.layers.forEach(l => {
              const a = l && typeof l.getAttribution === "function" ? l.getAttribution() : null;
              own.addAttribution(a);
            });
          }
          own.update();
          return own.api;
        };
        return stub();
      },
      apply: () => stub(), construct: () => stub(),
    });
    controls.push(own);
    return own.api;
  };

  const controlFacade = new Proxy(function () { }, {
    get: (t, p) => (p === "attribution" ? makeAttribution : stub()),
    apply: () => stub(), construct: () => stub(),
  });

  const L = new Proxy(function () { }, {
    get: (t, p) => {
      if (p === "then") return undefined;
      if (p === Symbol.iterator) return function* () { };
      if (p === "map") return makeMap;
      if (p === "tileLayer") return makeTile;
      if (p === "control") return controlFacade;
      if (p === "DomEvent") return { disableClickPropagation: () => { } };
      return stub();
    },
    set: (t, p, v) => { t[p] = v; return true; },
    apply: () => stub(), construct: () => stub(),
  });
  return { L, maps, controls };
}

async function boot() {
  const dom = new JSDOM(html, { url: "http://localhost/", runScripts: "outside-only", pretendToBeVisual: true });
  const win = dom.window;
  const leaflet = makeLeaflet(win);
  win.L = leaflet.L;
  win.JSZip = function () { return {}; };
  win.fetch = () => Promise.reject(new Error("no gateway in this driver"));
  const { TextEncoder, TextDecoder } = require("util");
  if (!win.TextEncoder) win.TextEncoder = TextEncoder;
  if (!win.TextDecoder) win.TextDecoder = TextDecoder;
  win.URL.createObjectURL = () => "blob:map-attribution";
  win.URL.revokeObjectURL = () => { };
  await new Promise((res) => (win.document.readyState === "complete" ? res() : win.addEventListener("load", res, { once: true })));
  // The page's scripts in source order, the shared module among them exactly as the document loads
  // it: this driver must not become a second, kinder loader than the browser's.
  const parts = ["security.js", "analytics-shim.js", "doi_harvest.js", "mapattrib.js"]
    .map((f) => fs.readFileSync(path.join(SRC, f), "utf8"));
  const inline = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1])
    .find((b) => b.includes("function buildSurveyYaml"));
  if (!inline) die("could not extract the inline UI script block from add-survey.html");
  vm.runInContext(parts.join("\n") + "\n" + inline, dom.getInternalVMContext());
  await new Promise((res) => setTimeout(res, 0));
  return { win, doc: win.document, leaflet };
}

function addEdi(win, name, text) {
  return new Promise((res) => {
    const file = new win.File([text], name, { type: "text/plain" });
    const ev = new win.Event("drop", { bubbles: true });
    Object.defineProperty(ev, "dataTransfer", { value: { files: [file] } });
    Object.defineProperty(ev, "preventDefault", { value: () => { } });
    win.document.getElementById("drop").dispatchEvent(ev);
    setTimeout(res, 30);
  });
}

// The control, as a reader meets it: the wrapper, its glyph and the credit element inside it.
function parts(win, mapId) {
  const host = win.document.getElementById(mapId);
  const wrap = host ? host.querySelector(".mapattrib") : null;
  return {
    host,
    wrap,
    btn: wrap ? wrap.querySelector(".mapattrib-toggle") : null,
    credit: wrap ? wrap.querySelector(".leaflet-control-attribution") : null,
  };
}

function fire(win, el, type) {
  el.dispatchEvent(new win.Event(type, { bubbles: type === "focusin" || type === "focusout" }));
}

function assertControl(win, mapId, expectedCredit) {
  const p = parts(win, mapId);
  ok(!!p.host, `#${mapId}: the map container must exist in the document`);
  ok(!!p.wrap, `#${mapId}: the attribution control must be mounted inside the map`);
  if (!p.wrap) return;
  ok(!!p.credit, `#${mapId}: the control must carry Leaflet's own .leaflet-control-attribution element`);
  ok(!!p.btn && p.btn.tagName === "BUTTON",
    `#${mapId}: the glyph must be a real button a keyboard can reach, got ` +
    (p.btn ? p.btn.tagName : "nothing"));

  // COLLAPSED BY DEFAULT. jsdom measures no box, so the state is read where the page holds it: the
  // open class is absent and the button says so.
  ok(!p.wrap.classList.contains("mapattrib-open"),
    `#${mapId}: the control must start collapsed`);
  ok(p.btn.getAttribute("aria-expanded") === "false",
    `#${mapId}: a collapsed control says so, got aria-expanded=` +
    JSON.stringify(p.btn.getAttribute("aria-expanded")));
  ok((p.btn.getAttribute("aria-label") || "").length > 3,
    `#${mapId}: the glyph is one letter, so it carries a label that says what it opens`);

  // NO LEAFLET FLAG AND NO PREFIX. The credit is a licence term; the library's name beside it is a
  // courtesy the portal does not carry.
  const text = p.credit.textContent || "";
  ok(!/Leaflet/.test(text), `#${mapId}: the control must print no Leaflet prefix, got ` + JSON.stringify(text));
  ok(!p.credit.querySelector(".leaflet-attribution-flag"),
    `#${mapId}: the Leaflet flag goes with the prefix`);
  ok(text.indexOf(expectedCredit) >= 0,
    `#${mapId}: the control prints the credit the LAYER declared, expected ` +
    JSON.stringify(expectedCredit) + " in " + JSON.stringify(text));

  // OPENS ON CLICK, and closes on a second one.
  p.btn.dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
  ok(p.wrap.classList.contains("mapattrib-open") && p.btn.getAttribute("aria-expanded") === "true",
    `#${mapId}: a click must expand the control`);
  p.btn.dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
  ok(!p.wrap.classList.contains("mapattrib-open") && p.btn.getAttribute("aria-expanded") === "false",
    `#${mapId}: a second click must collapse it again`);

  // OPENS ON KEYBOARD FOCUS, and closes when focus leaves. This is the leg that makes the control
  // reachable without a pointer at all.
  fire(win, p.btn, "focusin");
  ok(p.wrap.classList.contains("mapattrib-open") && p.btn.getAttribute("aria-expanded") === "true",
    `#${mapId}: focusing the glyph must expand the control`);
  fire(win, p.btn, "focusout");
  ok(!p.wrap.classList.contains("mapattrib-open"),
    `#${mapId}: the control must collapse again when focus leaves`);

  // AND ON HOVER, the third way in, closing when the pointer leaves.
  fire(win, p.wrap, "mouseenter");
  ok(p.wrap.classList.contains("mapattrib-open"), `#${mapId}: hovering must expand the control`);
  fire(win, p.wrap, "mouseleave");
  ok(!p.wrap.classList.contains("mapattrib-open"), `#${mapId}: leaving must collapse it again`);

  // THE POINTER PATH, in the order a real mouse produces it: hover, then pointerdown, then focus,
  // then click. Measured in Chrome, a toggle reading the state at CLICK time collapsed a control the
  // hover had just opened, so the click read as doing nothing.
  fire(win, p.wrap, "mouseenter");
  fire(win, p.btn, "pointerdown");
  fire(win, p.btn, "focusin");
  p.btn.dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
  ok(!p.wrap.classList.contains("mapattrib-open"),
    `#${mapId}: clicking a control the pointer already opened must collapse it`);
  // AND THE TAP PATH, which has no hover at all: pointerdown, focus, click, and the control must be
  // OPEN at the end of it. A toggle that read the state at click time left a tap doing nothing.
  fire(win, p.wrap, "mouseleave");
  fire(win, p.btn, "focusout");
  fire(win, p.btn, "pointerdown");
  fire(win, p.btn, "focusin");
  p.btn.dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
  ok(p.wrap.classList.contains("mapattrib-open"),
    `#${mapId}: a tap, which brings no hover, must leave the control open`);
  fire(win, p.btn, "focusout");
}

(async () => {
  const { win, doc, leaflet } = await boot();
  const OSM = "OpenStreetMap contributors";

  // The station PREVIEW map is built by the page itself the moment a file with coordinates lands.
  await addEdi(win, "S01.edi", EDI_TEXT);
  // The PICKER and the CONFIRMATION map are behind the two buttons a contributor presses.
  doc.getElementById("btnPick").dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
  doc.getElementById("btnConfirmMap").dispatchEvent(new win.MouseEvent("click", { bubbles: true }));

  ok(leaflet.maps.length === 3,
    "add-survey must build three maps (preview, picker, confirmation), built " +
    JSON.stringify(leaflet.maps.map(m => m.id)));
  leaflet.maps.forEach(m => {
    ok(m.opts.attributionControl === false,
      `#${m.id}: the map is built without Leaflet's default control, which carries the flag and ` +
      "the word; got " + JSON.stringify(m.opts));
  });
  ok(leaflet.controls.length === 3,
    "one collapsed control per map, constructed " + leaflet.controls.length + " time(s)");
  leaflet.controls.forEach((c, i) => {
    ok(c.options.prefix === false,
      "control " + i + " must be constructed with prefix:false, got " + JSON.stringify(c.options));
  });

  ["t0map", "pickmap", "confirmmap"].forEach(id => assertControl(win, id, OSM));

  if (fail) die(fail + " assertion(s) failed");
  console.log("ALL PASSED (add-survey: three maps, three collapsed attribution controls, " +
    "no Leaflet prefix, click + keyboard + hover open and close, credit read from the layer)");
  process.exit(0);
})().catch(e => die((e && e.stack) || String(e)));
