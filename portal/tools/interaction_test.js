// jsdom-backed INTERACTION test for the portal sidebar + routing.
//
// smoke.js stubs the DOM so querySelectorAll() returns [] -> buildTree() never makes a checkbox and the
// whole interaction layer (tree toggles, Find, #/collection routing) ships untested. That is exactly how
// the value-less-checkbox toggle no-op shipped. This test instead loads the REAL index.html into a jsdom
// DOM, runs the actual src modules in the window's VM context (mirroring the in-order <script> tags), boots
// against a fixture data dir, then DRIVES the UI and asserts the OBSERVABLE result: the filtered station
// set, the visible view, the Find dropdown. It is the regression guard for the hostile-audit must-fix UI
// bugs (country/org toggle, collection route + Back, Find blanking the map).
//
//   node tools/interaction_test.js <dataDir>
//
// Requires jsdom (a dev-only dependency; see package.json — the shipped portal has none). Exit codes:
//   0 = passed   1 = a real interaction failure   2 = jsdom missing (caller should SKIP, not fail)
const fs = require("fs"), path = require("path"), vm = require("vm");
let JSDOM;
try { ({ JSDOM } = require("jsdom")); }
catch (e) { console.error("SKIP: jsdom not installed (run `npm ci` in portal/)"); process.exit(2); }

const TOOLS = __dirname;
const PORTAL = path.resolve(TOOLS, "..");
const SRC = path.join(PORTAL, "src");
const DATA = path.resolve(process.argv[2] || path.join(PORTAL, "data"));

// fixture data served to the app's fetch() (same file set as smoke.js)
const FILES = ["catalogue", "tf", "sci", "surveys", "build_provenance", "collections", "build"];
const DATAMAP = {};
FILES.forEach(k => { try { DATAMAP["data/" + k + ".json"] = JSON.parse(fs.readFileSync(path.join(DATA, k + ".json"))); } catch (e) {} });

// This test is FIXTURE-driven: it asserts against a known 4-station fixture that the pytest wrapper
// (tests/test_interactions.py) builds and passes as argv[2]. The shipped portal/data is empty BY DESIGN
// (demo data is never committed), so a bare `npm run test:interactions` against it has nothing to drive.
// Skip cleanly (exit 0) and point at the real harness rather than reporting a false interaction failure.
const _cat = DATAMAP["data/catalogue.json"];
if (!Array.isArray(_cat) || _cat.length === 0) {
  console.log("SKIP: no stations in " + DATA + " (portal/data ships empty by design). Run the interaction " +
    "test via `pytest -q tests` — tests/test_interactions.py builds a 4-station fixture and passes its path. " +
    "The bare `npm run test:interactions` against empty data drives nothing.");
  process.exit(0);
}

// Leaflet/JSZip stub (the map layer is irrelevant here; the DOM itself is real jsdom).
// mapCalls records every setView()/fitBounds() call the app makes on the `map` object (map.js's
// `L.map(...)` returns this same stub) — general instrumentation for any test that needs to assert
// on map navigation calls actually made, with real arguments, not just "something happened".
const mapCalls = [];
const stub = () => new Proxy(function () {}, {
  get: (t, p) => {
    if (p === "then") return undefined;
    if (p === Symbol.iterator) return function* () {};
    if (p === "setView" || p === "fitBounds" || p === "invalidateSize") return (...args) => { mapCalls.push({ fn: p, args }); return stub(); };
    return stub();
  },
  apply: () => stub(), construct: () => stub(),
});

// ---- RECORDING LEAFLET FACADE (pane/pointer lane, 2026-08-19) ------------------------------------
// The blanket stub above answers every property with another stub, which is right for "the map layer is
// irrelevant here" but makes three things unobservable that a production regression has now proved matter:
// which PANES the app creates and with what style, which LAYERS it puts in them, and what a marker's click
// handler DOES. So the few Leaflet factories the map module actually builds with are recorded, and
// everything else degenerates to the same stub as before - no existing leg changes behaviour.
//
// HONESTY, stated once and repeated at the legs: this records the app's CALLS. jsdom has no layout, no
// compositor and no canvas hit-testing, so nothing here proves that a pointer reaches a layer, that pane
// z-order resolves the way the browser resolves it, or that pointer-events actually stops a canvas
// swallowing a click. Those are browser facts, measured separately by the lane and reported as such.
const recProxy = (own) => {
  const px = new Proxy(function () { }, {
    get: (t, p) => {
      if (p === "then") return undefined;
      if (p === Symbol.iterator) return function* () { };
      if (Object.prototype.hasOwnProperty.call(own, p)) return own[p];
      return stub();
    },
    // A real set trap, so a stamp the app writes onto a layer (map.js writes marker._survey) reads back as
    // itself instead of as a fresh stub.
    set: (t, p, v) => { own[p] = v; return true; },
    apply: () => stub(), construct: () => stub(),
  });
  own.__self = px; own.__rec = own;
  return px;
};
// A layer. `kind` is what the dots-only pin reads: a station dot is a circleMarker, and the two shapes the
// retired badge layer drew (an L.marker divIcon, an L.polyline leader) are recorded too, so their RETURN
// would be caught rather than silently absorbed by the blanket stub. `isPath` models the one Leaflet API
// difference that separates the two families: every L.Path carries setStyle+redraw, L.Marker neither.
const recLayer = (kind, geom, opts, isPath) => {
  const own = Object.create(null);
  own.kind = kind; own.geom = geom; own.options = opts || {}; own.handlers = Object.create(null);
  own.on = (ev, fn) => {
    if (typeof ev === "string") ev.split(/\s+/).forEach(e => (own.handlers[e] = own.handlers[e] || []).push(fn));
    return own.__self;
  };
  own.setStyle = isPath ? (s) => { own.style = Object.assign({}, own.style, s); return own.__self; } : undefined;
  own.redraw = isPath ? () => own.__self : undefined;
  return recProxy(own);
};
// Leaflet's LayerGroup.addLayer delegates to Map.addLayer when the group is on a map, which is what makes
// ONE map-level layeradd hook see everything the app draws. Reproduced here, because that delegation is
// exactly the path the shipped pane guard relies on.
const layersAdded = [];
const mapEvents = Object.create(null);
function mapAddLayer(l) {
  layersAdded.push(l);
  (mapEvents.layeradd || []).forEach(fn => { try { fn({ layer: l }); } catch (e) { /* a guard must not break a render */ } });
}
const recGroup = () => {
  const own = Object.create(null);
  own.kind = "layerGroup"; own.layers = []; own.options = {};
  own.setStyle = undefined; own.redraw = undefined;
  own.addLayer = (l) => { own.layers.push(l); mapAddLayer(l); return own.__self; };
  own.clearLayers = () => { own.layers.length = 0; return own.__self; };
  own.eachLayer = (fn) => { own.layers.forEach(fn); return own.__self; };
  return recProxy(own);
};
// The panes the app creates, by name. It must create NONE (F5): a pane is stacked over the station canvas,
// which is the 2026-08-19 outage. Recorded rather than stubbed away so the absence is assertable.
const panesMade = Object.create(null);
// getZoom is deliberately NOT recorded: curZoom() falls back to 4 (national), which is the zoom the map
// pins are written at. project/unproject are not recorded either - they existed only to make the retired
// badge declutter reachable here, and no shipped map path projects any more.
const mapOwn = Object.create(null);
mapOwn.createPane = (nm) => (panesMade[nm] = panesMade[nm] || { style: {}, name: nm });
mapOwn.getPane = (nm) => panesMade[nm] || null;
mapOwn.on = (ev, fn) => {
  if (typeof ev === "string") ev.split(/\s+/).forEach(e => (mapEvents[e] = mapEvents[e] || []).push(fn));
  return mapOwn.__self;
};
mapOwn.addLayer = (l) => { mapAddLayer(l); return mapOwn.__self; };
["setView", "fitBounds", "invalidateSize"].forEach(fn => {
  mapOwn[fn] = (...args) => { mapCalls.push({ fn, args }); return mapOwn.__self; };
});
const mapFacade = recProxy(mapOwn);
// L.control.scale, recorded. The scale bar is CONSTRUCTED with deliberate options and then
// RE-PARENTED, and both halves are the claim: which options the app asks for, and where the container
// ends up. The blanket stub answers getContainer() with a Proxy, which is not a node, so under it the
// re-parenting cannot happen at all and the pin would be vacuous. Every other L.control member (the
// layer control map.js builds) still degenerates to the old stub.
const scaleControls = [];
const controlFacade = new Proxy(function () { }, {
  get: (t, p) => {
    if (p !== "scale") return stub();
    return (opts) => {
      const own = Object.create(null);
      own.options = opts || {};
      own.container = win.document.createElement("div");
      own.container.className = "leaflet-control-scale";
      own.addTo = () => { own.added = true; return own.__self; };
      own.getContainer = () => own.container;
      scaleControls.push(own);
      return recProxy(own);
    };
  },
  apply: () => stub(), construct: () => stub(),
});

// Boot the real page DOM in jsdom with NO page scripts (we run the modules ourselves, in order).
const html = fs.readFileSync(path.join(PORTAL, "index.html"), "utf8");
const dom = new JSDOM(html, { url: "http://localhost/", runScripts: "outside-only", pretendToBeVisual: true });
const win = dom.window;
// The five factories map.js builds its layers with are recorded; every other L member is the old stub, so
// leaflet.draw, tile layers, icons and bounds behave exactly as they did.
win.L = new Proxy(function () { }, {
  get: (t, p) => {
    if (p === "then") return undefined;
    if (p === Symbol.iterator) return function* () { };
    if (p === "map") return () => mapFacade;
    if (p === "circleMarker") return (ll, o) => recLayer("circleMarker", ll, o, true);
    if (p === "marker") return (ll, o) => recLayer("marker", ll, o, false);
    if (p === "polyline") return (lls, o) => recLayer("polyline", lls, o, true);
    if (p === "layerGroup") return () => recGroup();
    if (p === "control") return controlFacade;
    return stub();
  },
  set: (t, p, v) => { t[p] = v; return true; },
  apply: () => stub(), construct: () => stub(),
});
// JSZip RECORDER. jsdom writes no real archive, but WHICH entries a selection export puts in one is
// exactly the claim the export pins make ("the zip holds a file per station that has this format, and a
// LICENSE.txt beside them"), and the old blanket stub swallowed every z.file() call, so no such claim
// could be asserted at all. This records the entry names (folder prefix included) and degenerates to the
// generic stub for everything else, so generateAsync() still resolves exactly as it did before.
const zipEntries = [];
const zipRec = (prefix) => new Proxy(function () {}, {
  get: (t, p) => {
    if (p === "then") return undefined;
    if (p === Symbol.iterator) return function* () {};
    if (p === "folder") return (n) => zipRec(prefix + String(n) + "/");
    if (p === "file") return (name, body) => { zipEntries.push({ name: prefix + String(name), body }); return zipRec(prefix); };
    return stub();
  },
  apply: () => stub(), construct: () => stub(),
});
win.JSZip = new Proxy(function () {}, { construct: () => zipRec(""), apply: () => zipRec("") });
// jsdom implements no object-URL store, and every export ends by handing a Blob to createObjectURL to
// drive the download anchor. Stubbing the pair lets a pin drive an export CLICK all the way to its end
// (which is where the entry list is complete) instead of stopping short of the code that writes it.
win.URL.createObjectURL = () => "blob:interaction-test";
win.URL.revokeObjectURL = () => {};
// SAVED-FILE RECORDER. save() builds `new Blob([text])`; recording the constructor's parts lets a
// pin read the DOCUMENT an export actually wrote (the Pointers shape), not just that a click ran.
const savedBlobs = [];
const _RealBlob = win.Blob;
win.Blob = function (parts, opts) { savedBlobs.push({ text: (parts || []).join(""), type: (opts || {}).type });
  return new _RealBlob(parts || [], opts || {}); };
// ANALYTICS RECORDER. analytics-shim.js defines window.track() over window.plausible, and it only installs
// its own no-op queue when there is no plausible already (`window.plausible || function(){}`). Defining one
// FIRST therefore records what the real track() emits, through the real shim, rather than replacing track()
// with a re-implementation of it. What an export button reports is a published vocabulary: the fold that
// reads these events cannot see the difference between two buttons that describe themselves differently
// and two buttons that do different things, so the shape is worth pinning at the call site.
const trackCalls = [];
win.plausible = (name, opts) => { trackCalls.push({ name, props: (opts && opts.props) || {} }); };
// HAND-OFF RECORDERS. A /go/ts/ hand-off is a window.open of a route the front door resolves; jsdom
// does not implement window.open, and what is being pinned is exactly WHICH url the app hands the
// browser, so record it. The clipboard is stubbed for the same reason: the copy button's whole job is
// the string it produces, and drawer.js copyTxt reaches navigator.clipboard, which jsdom leaves unset.
const opened = [];
win.open = (...args) => { opened.push(args); return null; };
const clipboard = [];
Object.defineProperty(win.navigator, "clipboard", {
  value: { writeText: t => { clipboard.push(String(t)); return Promise.resolve(); } }, configurable: true });
// version/schema pinned so version.js produces a DETERMINISTIC ver-chip label the footer-chip assertion
// (item 3) can pin exactly, instead of matching a moving default.
win.AUSMT_CONFIG = { short_name: "AusMT", version: "1.2.3", schema: "MTCAT", schema_version: "1.0" };

// ---- two-phase boot instrumentation --------------------------------------------------------------
// The portal boots in TWO phases: phase 1 fetches only what the first paint needs (catalogue + surveys and
// the four small optionals, all in parallel) and renders; phase 2 (tf.json ~3.2MB, sci.json, manifest.json)
// hydrates behind it. To drive that split this fetch (a) LOGS every url in request order, so the driver can
// prove the six phase-1 products and the three heavy ones all went out together rather than one behind
// another, and (b) HOLDS the three heavy responses until releaseHeavy(), so the driver can inspect the app
// in exactly the window the split creates. Every other url resolves immediately, as before.
// ts_access.json joins the held set although it is small: what it gates is a two-phase HONESTY rule
// (nothing may claim a station has no archive route while the index is still in flight), and that
// window is only drivable if the response can be held open here.
const HEAVY = /(^|\/)(tf|sci|manifest|ts_access)\.json$/;
// The served ARTIFACT families (the per-station files the selection exports package). The data dir holds
// only JSON products, so without this every artifact fetch came back !ok and every export packaged
// nothing: a pin could then only observe which URLs were requested, never what the archive ended up
// holding. A matching url resolves as a served file would, so the packaging path runs to completion.
// The query is stripped first, because the bulk label rides there.
const ARTIFACT = /\.(edi|xml|h5)$/i;
// FAILURE INJECTION. Making every artifact fetch succeed (above) is what let the packaging path run to its
// end, and it also made the OTHER end unreachable: an export's transport-failure branch (the fetch throws,
// the station lands in failed[], the archive says which files were served but did not arrive) could not be
// entered by any driver, so the one branch that speaks about the NETWORK rather than about the corpus
// shipped unexercised. Add a path here and its fetch REJECTS, the way a dropped connection does, which is
// the harsher of the two routes into that branch (a not-ok response reaches the same catch). Matched on the
// query-stripped url by SUFFIX, so a leg names the manifest row ("h5/gamma/G1.h5") and not the data-base
// prefix or the bulk label the export appends.
const fetchFail = new Set();
const fetchWouldFail = (url) => {
  const p = String(url).split("?")[0];
  for (const t of fetchFail) if (p === t || p.endsWith("/" + t)) return true;
  return false;
};
const fetchOrder = [];
let heavyPending = [];
let heavyReleased = false;
function heavyHeld() { return heavyPending.length; }
function releaseHeavy() { heavyReleased = true; const q = heavyPending; heavyPending = []; q.forEach(f => f()); }
win.fetch = url => {
  fetchOrder.push(String(url));
  if (fetchWouldFail(url)) return Promise.reject(new Error("injected transport failure: " + url));
  const body = DATAMAP[url] ? { ok: true, json: () => Promise.resolve(DATAMAP[url]) }
    : ARTIFACT.test(String(url).split("?")[0]) ? { ok: true, blob: () => Promise.resolve({ size: 1 }) }
      : { ok: false };
  if (!HEAVY.test(url) || heavyReleased) return Promise.resolve(body);
  return new Promise(res => heavyPending.push(() => res(body)));
};

// Concatenate the modules + an api hook; run in the window's global scope so the top-level declarations
// become window globals (same effect as index.html's ordered <script> tags).
// analytics-shim is FIRST, exactly as index.html loads it: it defines the no-op window.track() every
// export click handler calls on its first line. The harness used to omit it, which is why no pin could
// drive a real export BUTTON (only the pure helpers behind one) without dying on an undefined track.
const MODULES = ["analytics-shim", "contract", "security", "state", "data", "plots", "map", "filters", "drawer", "exports", "main", "tour"];
let code = MODULES.map(f => fs.readFileSync(path.join(SRC, f + ".js"), "utf8")).join("\n");
code += "\nwindow.__api={boot,setView,routeFromHash,refresh,openStation,renderFind," +
  "curView:()=>curView,nST:()=>ST.length,visIds:()=>visible.map(s=>s.id)," +
  "visSurveys:()=>[...new Set(visible.map(s=>s.survey))]," +
  // intro-panel + tour hooks (S2 UX-A) — exposed so the driver can assert on internal helpers
  // (e.g. re-reading localStorage) as well as on the rendered DOM. maybeShowIntro lets the driver
  // simulate a genuine first visit (clear the key, re-run the first-visit show) for the welcome popup.
  "introSeen,maybeShowIntro,tourStep:()=>_tourStep," +
  // Settle-until-stable re-layout (owner 2026-07-22): the drawer step opens a target that keeps reflowing
  // after open (slide, then the async station.json frame-line inject, then a possible map re-fit), so the
  // tour POLLS the target rect each frame and re-runs _tourLayout until it holds stable. tourSettleEl exposes
  // which element the watcher tracks (drawer step -> "drawer"; null when detached) and tourLayoutRuns counts
  // _tourLayout calls, so the pin can drive synthetic rect changes through the parked rAF queue and assert the
  // re-run-until-stable-then-stop behaviour and clean detach without leaking the watcher onto a persistent element.
  "tourSettleEl:()=>_tourSettleEl&&_tourSettleEl.id,tourLayoutRuns:()=>_tourLayoutRuns," +
  "tourSettling:()=>_tourSettleRAF!==0," +   // whether a poll frame is still pending (true=watching, false=stood down/detached)
  // UX7b U7 welcome-popup helpers: showWelcome/closeWelcome drive the first-visit modal directly (the
  // checkbox-persistence matrix pokes #welcomeDismiss then closes each way). UX9 (owner tour redesign): the
  // side-picking _tourPlace is retired for a CENTRED card + a LEADER to the spotlight. _tourCardBox is the
  // PURE centred-card box (with the overlap nudge) and _tourLeader the PURE leader geometry (endpoints +
  // suppression) — both unit-tested with synthetic rects since jsdom has no layout engine. U10 TOUR_DIM is
  // the overlay alpha (the load-bearing 'increased dim' value).
  "showWelcome,closeWelcome,tourCardBox:(cw,ch,vw,vh,t)=>_tourCardBox(cw,ch,vw,vh,t)," +
  "tourLeader:(c,s,sup)=>_tourLeader(c,s,sup),tourDim:()=>TOUR_DIM," +
  // UX6 Wave D hooks: sidebarMode reader + setSidebarMode (D2 Browse/Select toggle); onDrawCreated +
  // drawSelectionMsg (D3 draw-created toast + its pure formatter).
  "sidebarMode:()=>sidebarMode,setSidebarMode,onDrawCreated,drawSelectionMsg," +
  // Discoverability (SELECTION-panel draw buttons): armDraw is the panel's arm entry point (reuses the
  // control's own mode handler); armedDrawMode is the shared active state both the buttons and the map
  // toolbar drive; setArmedDraw is what the DRAWSTART/DRAWSTOP listeners call (icon-arm + cancel paths);
  // drawModeHandler proves the reuse reaches the control's handler, not a duplicated invocation.
  "armDraw,setArmedDraw,drawModeHandler,armedDrawMode:()=>armedDrawMode," +
  // S3 hooks: recentlyAdded() for the strip-content assertion; renderRecentlyAdded so the driver
  // can force a re-render after directly poking SMETA (not needed in the current fixture path, but
  // keeps parity with runInit()'s own call sites); surveyLatestDate so the pinned cross-lane date
  // rule (attribution.declared_date folded into the release_notes candidate set) is asserted
  // directly, without a full re-render.
  "recentlyAdded,renderRecentlyAdded,surveyLatestDate," +
  // UX4 (D1-A1/D2/D4): the PURE map helpers, exposed so the AusLAMP partition / colour / tooltip /
  // zoom-scaling are unit-testable without Leaflet (jsdom can't load it). partitionMarkers(list) ->
  // {unclustered, clustered} splits on AusLAMP membership; isAuslampSurvey(slug,set) is the predicate;
  // radiusForZoom/weightForZoom are the D4 step functions; markerColor(s) is membership-blind post-A1;
  // tooltipText(s) carries the A1 type-label swap (member shows "AusLAMP" instead of LPMT). The
  // AUSLAMP_SET getter/setter + buildAuslampSet let the driver exercise both the boot-built set and
  // explicit sets; setColorMode drives the colour-mode assertions. The ST-poke + selectSurvey/selCount
  // hooks verify draw/select flows still COUNT a re-classified station (which may move map containers) —
  // the counting logic reads `visible`/ST, not layer membership, so it stays membership-agnostic.
  "isAuslampSurvey,radiusForZoom,weightForZoom,markerColor,tooltipText,buildAuslampSet," +
  // The map paint pass. F4 invokes it and reads what it returned, which is the only readable record of
  // what reached the ONE dot container (the stubbed layer group's own contents are Proxies).
  "routeVisibleToLayers," +
  "auslampSet:()=>AUSLAMP_SET,setAuslampSet:(arr)=>{AUSLAMP_SET=new Set(arr);}," +
  // stationMarker reaches a real station's recorded layer, which is how the station-click leg fires the
  // handler the app actually bound rather than a re-implementation of it.
  "stationMarker:(id)=>{const s=ST.find(x=>x.id===id);return s&&s.marker;}," +
  "selectSurvey,renderCards,openSurvey," +
  // Survey-drawer lane hooks. focusSurvey drives the header "View on map" path; drawerFitOptions is the
  // PURE fit padding (asserted against a stubbed drawer width); dimStyleFor is the PURE Option-A dim
  // decision; setSurveyDim/clearSurveyDim + dimFocus expose the focus STATE so a leg can prove the dim
  // lifts on close. _bgClickShouldClose is the pure background-click rule (see the honesty note at its
  // leg: Leaflet is STUBBED here, so the pointer/hit-testing semantics themselves are not exercised).
  "focusSurvey,drawerFitOptions,dimStyleFor,setSurveyDim,clearSurveyDim," +
  "dimFocus:()=>_dimFocusSurvey,bgClickShouldClose:_bgClickShouldClose," +
  "surveyDataLevelsHtml,DATA_LEVEL_SLOTS," +
  // UX4 D5 hook: the tree-demo step's resolved survey label (kalkaroo-2022 preferred, first-survey
  // degrade) — a REAL observable for the graceful-degrade assertion, not just "didn't crash".
  "tourTreeTarget:()=>_tourTreeTarget," +
  // UX5 (D7/D8) hooks: the disclosure-caret API (same functions the carets and the tour step call)
  // plus a collapse-set reader, so the invariant and the tour-restore assertions observe real state.
  "treeSetCollapsed,treeIsCollapsed,treeCollapsedKeys:()=>[..._treeCollapsed]," +
  "setType:(id,ty)=>{const s=ST.find(x=>x.id===id);if(s)s.type=ty;}," +
  "setSlug:(id,sl)=>{const s=ST.find(x=>x.id===id);if(s)s.slug=sl;}," +
  // UX3 item 7 hook: poke a survey's blurb (abstract) and read the rendered surveyCard/surveySummary
  // HTML, so the driver can assert where the abstract renders (C2: the drawer story view, no longer the
  // card) and the removal of the dimensionality displays (while skew/strike stay).
  "setBlurb:(sv,b)=>{SMETA[sv]=SMETA[sv]||{};if(b===null)delete SMETA[sv].blurb;else SMETA[sv].blurb=b;}," +
  "cardHtml:(sv)=>surveyCard(sv),summaryHtml:(sv)=>surveySummary(ST.filter(s=>s.survey===sv),SMETA[sv]||{})," +
  // C22 citation-honesty hooks: the citation ASSEMBLY helpers (drawer.js apa/bibtex/ris + exports.js
  // citeLine) and the constants the #dlCite pack feeds them — exposed so section T can assert on the
  // exact strings the pack is built from. citeLine is a LAZY arrow (not a bare reference) so a boot on
  // pre-C22 code still reaches section T and fails THERE with a precise message, instead of dying at
  // this api hook with an unrelated-looking ReferenceError.
  "apa,bibtex,ris,AUSMT_SELF,NCI_CITE,TS_COLLECTION,citeLine:(c,d)=>citeLine(c,d),smeta:(sv)=>SMETA[sv]," +
  // UX6 Wave E hooks: collScatter (E6 footprint — driven with a stubbed AU_OUTLINE), renderCollections
  // (E5 landing), and openStationById (E7 focus — lets the driver control the invoking element before open).
  "collScatter,memberColours,renderCollections,openStationById:(id)=>{const s=ST.find(x=>x.ausmt_id===id)||ST.find(x=>x.id===id);if(s)openStation(s.i);}," +
  // UX8 (X5/X7) + C46-W3b PURE helpers, exposed so the field->indicator/star mappings are unit-testable
  // (jsdom can't run real geometry): screeningIndicators(d) maps scalar inputs to the five indicator
  // states; maturityModel(m,sc) is the star model; licBadgeState/licIsOpen/attributionText are the W3b
  // licence/attribution helpers; setSMETA patches a survey's metadata so the driver can drive the
  // attribution/sources render paths that the base fixture doesn't carry.
  "screeningIndicators,maturityModel,licBadgeState,licIsOpen,attributionText," +
  "setSMETA:(sv,patch)=>{SMETA[sv]=Object.assign(SMETA[sv]||{},patch);}," +
  // Card-lane polish hooks. processingSoftwareText/pubShortCite are the PURE lineage derivations (the
  // most-specific software string, and a publication reduced to a short cite without fabricating an
  // "et al."); setManifest swaps the download manifest so the distributed-formats node can be driven
  // against real availability (the fixture data dir ships none), mirroring tools/bundle_tiles_test.js.
  // LAZY arrows (not bare references) so a boot on pre-change drawer.js still REACHES section LG and
  // fails there with a precise message, instead of dying at this api hook with a ReferenceError.
  "processingSoftwareText:(m,sc)=>processingSoftwareText(m,sc),pubShortCite:(p)=>pubShortCite(p)," +
  "setManifest:(mf)=>{MANIFEST=mf;}," +
  // THREDDS hooks. setTsAccess swaps the hand-off index the way setManifest swaps the download one
  // (the fixture data dir ships no ts_access.json, which is itself the honest no-download-index
  // case); tsRoutes reads it back through the app's own accessor rather than through a copy of it.
  "setTsAccess:(m)=>{TSACC=(m===null?null:(m||{}));},tsRoutes:(id)=>tsRoutesFor(id)," +
  "tsAccess:()=>TSACC,tsAccessKnown:()=>tsAccessKnown()," +
  // Lineage split hooks (writer vs processor). fileWrittenByText is the PURE writer-cell derivation;
  // setSciRow/restoreSciRows patch one station's sci row BY NAME (projected through SCI_COLUMNS, so a
  // contract append cannot silently mis-place the patch) and put the fixture back, which is how the
  // Method-node omission is driven — that node's inputs live in sci.json, not in SMETA.
  "fileWrittenByText:(f)=>fileWrittenByText(f)," +
  "setSciRow:(id,patch)=>{const s=ST.find(x=>x.ausmt_id===id)||ST.find(x=>x.id===id);if(!s)return;" +
  "  if(!window.__sciBackup)window.__sciBackup=SCI.map(r=>r.slice());" +
  "  const r=SCI[s.i].slice();Object.keys(patch).forEach(k=>{r[SCI_COLUMNS.indexOf(k)]=patch[k];});SCI[s.i]=r;}," +
  "restoreSciRows:()=>{if(window.__sciBackup){SCI=window.__sciBackup;window.__sciBackup=null;}}," +
  // CVD amendment hook: qColor (the completeness ramp) so the sequential-ramp pins drive it directly.
  "qColor," +
  // UX9 item 2 (map off-centre fix) hooks. The off-centre-on-load bug is a fitBounds computed at a
  // degenerate (stale/0x0) container size; the fix invalidates size BEFORE the primary fit and adds a
  // one-shot corrector on the setView('map') timer. mapSizeDegenerate/mapRefitGate are the PURE decisions
  // (unit-tested on synthetic inputs, since jsdom has no layout engine); homeFitDegenerate/mapUserInteracted
  // read the recorded boot state; setMapInteracted flips the user-control flag; mapCorrectHomeFit invokes
  // the corrector so its one-shot re-fit + flag-clear are observable via the map stub's recorded calls.
  "mapSizeDegenerate:(s)=>_mapSizeDegenerate(s),mapRefitGate:(st)=>_mapRefitGate(st)," +
  // Owner round 2: the home frame is now the FIXED Australia box (AU_HOME_BOUNDS), shared by the map-create
  // fit and buildMarkers, NOT the tight positioned-station extent. homeBounds/auHomeBounds expose both so the
  // driver can pin that they are the SAME object (cannot drift) and that HOME_BOUNDS is NOT the old pts array.
  "homeBounds:()=>HOME_BOUNDS,auHomeBounds:()=>AU_HOME_BOUNDS," +
  "homeFitDegenerate:()=>_fitWasDegenerate,mapUserInteracted:()=>_mapUserInteracted," +
  "setMapInteracted:(v)=>{_mapUserInteracted=v;},mapCorrectHomeFit:()=>_mapCorrectHomeFit()," +
  // The DEFERRED unconditional re-fit is the actual off-centre-on-load fix: mapDeferredHomeRefit runs the
  // re-fit body (invalidateSize + fit HOME_BOUNDS, gated ONLY on !userInteracted, NOT on degeneracy);
  // scheduleDeferredHomeRefit is the double-rAF scheduler the driver drives through a controllable rAF queue.
  "mapDeferredHomeRefit:()=>_mapDeferredHomeRefit(),scheduleDeferredHomeRefit:()=>_scheduleDeferredHomeRefit()," +
  // Two-phase boot hooks. hydrationDone settles once tf/sci/manifest have landed AND their late-render work
  // has run, so the driver can say "the app is now in the state a single-phase boot produced" without racing
  // the continuations. hydrState reports the per-product gate ("pending"|"ready"|"failed"), qMin/setQMin drive
  // the completeness PREDICATE directly - the Availability group retired its rail control, so this hook is
  // now the only way to set it, and the two-phase honesty legs below are what it exists for - and
  // markerCount/station/closeDrawer are plain observables for the first-paint assertions.
  "hydrationDone:()=>HYDRATION_DONE,hydrState:(k)=>HYDR[k]," +
  "markerCount:()=>ST.filter(s=>s.marker).length,station:(id)=>ST.find(x=>x.id===id)," +
  "qMin:()=>qMin,setQMin:(v)=>{qMin=v;},closeDrawer," +
  // Availability-chooser hooks (A6). tsLevels/setTsLevels read and drive the chosen level set without
  // going through the buttons (the buttons are disabled across the whole in-flight window, which is
  // exactly the state the inertness pin has to observe); paintTsChooser re-runs the paint after the
  // driver swaps the index, the way runInit and the hydration gate call it.
  "availValue:()=>{const a=document.getElementById(\"availSel\");return a?a.value:null;}," +
  "setAvail:(v)=>{const a=document.getElementById(\"availSel\");if(a)a.value=v||\"\";}," +
  "setPeriodWin:(lo,hi)=>{periodLo=lo;periodHi=hi;}," +
  "paintDownloadRows:()=>paintDownloadRows()," +
  // The hand-off list's PURE builder, exposed for the same reason geoFC is: the file the reader gets
  // is written inside a click handler, and a claim about its contents that no test can reach is a
  // claim that rots. Takes the selection and the chosen levels from the app, not from the driver.
  "tsHandoffDoc:(sts,levels)=>tsHandoffDocument(sts||scopeSel(),levels||null)," +
  // The two terminal-command builders, exposed for the same reason: the strings a reader pastes are
  // built inside showWgetDialog()'s cmds object, so a claim about their shell-safety and their
  // collision-free output paths must observe the real builders, not a re-implementation.
  "tsCurl:(rows,exe)=>tsCurlCommand(rows,exe)," +
  "tsWget:(rows)=>tsWgetCommand(rows)," +
  // geoFC builds the GeoJSON export exactly as #dlGeo does, taking the sci-usable decision FROM THE APP
  // (hydrUsable) rather than from the driver, so the export-honesty pins observe the real branch rather than
  // a re-implementation of it. setSelected drives `selected` by station id without going through
  // selectSurvey (which also enters the select lens and switches views); the strike rose needs a selection
  // and nothing else. Both take/return plain data, so they work identically in a fresh failure window.
  "geoFC:(sts)=>geoFeatureCollection(sts||sel(),hydrUsable('sci'))," +
  "setSelected:(ids)=>{selected=new Set(ids.map(id=>{const s=ST.find(x=>x.id===id);return s?s.i:-1;}).filter(i=>i>=0));updateSel();}," +
  // BULK-EXPORT LABEL hooks. dispatchProd is the drawer's OWN product-download dispatcher (the single
  // station path, drawer.js), exposed so the pin can drive the real unlabelled call site rather than a
  // re-implementation of it; selBulkFlag is the flag string exports.js appends, so the cross-file pin
  // in portal/tests can compare it with the aggregator's constant instead of hard-coding a third copy.
  // LAZY arrows so a boot on pre-lane code still REACHES the section and fails there with a precise
  // message, instead of dying at this api hook with a ReferenceError.
  "dispatchProd:(d)=>dispatchProd(d),selBulkFlag:()=>SEL_BULK_FLAG," +
  "selCount:()=>selected.size,nVisCount:()=>visible.length};";

const doc = win.document;
const fire = (el, type) => el.dispatchEvent(new win.Event(type, { bubbles: true }));
function die(msg) { console.error("INTERACTION FAILED: " + msg); process.exit(1); }
function ok(cond, msg) { if (!cond) die(msg); }

// Boots a SEPARATE fresh jsdom window against the given data map (used for the empty-state intro-panel
// check below — reusing the already-booted populated `win` would double-init the app). Mirrors the setup
// above exactly (same module list/order, same stubs) so it is a faithful re-run of index.html's boot.
// `preBoot` runs on the fresh window BEFORE the modules do, which is the only place a pin can seed
// state the boot itself READS (localStorage: the sidebar-collapse and intro-dismissed keys are
// applied during boot, so setting them afterwards would test nothing).
async function bootFreshWindow(dataMap, url, preBoot) {
  const d = new JSDOM(html, { url: url || "http://localhost/", runScripts: "outside-only", pretendToBeVisual: true });
  const w = d.window;
  w.L = stub(); w.JSZip = stub();
  w.AUSMT_CONFIG = { short_name: "AusMT" };
  w.fetch = url => Promise.resolve(dataMap[url] ? { ok: true, json: () => Promise.resolve(dataMap[url]) } : { ok: false });
  if (typeof preBoot === "function") preBoot(w);
  await new Promise(res => (w.document.readyState === "complete" ? res() : w.addEventListener("load", res, { once: true })));
  vm.runInContext(code, d.getInternalVMContext());
  await w.__api.boot();
  await w.__api.hydrationDone();   // two-phase boot: settle tf/sci/manifest before the caller asserts
  return w;
}

(async () => {
  // Let jsdom finish its document lifecycle BEFORE we run the modules, so main.js's DOMContentLoaded
  // auto-boot can't double-fire alongside our explicit boot() (a second boot re-runs buildTree and
  // appends a duplicate tree). After 'load', the listener main.js registers is too late to fire.
  await new Promise(res => (win.document.readyState === "complete" ? res() : win.addEventListener("load", res, { once: true })));
  vm.runInContext(code, dom.getInternalVMContext());
  const A = win.__api;
  // Controllable requestAnimationFrame: buildMarkers (during boot) schedules the DEFERRED home re-fit via
  // double-rAF. Park those callbacks in a queue instead of letting jsdom's timer fire them, so (1) they never
  // auto-fire mid-assertion and perturb the exact fitBounds counts the corrector block below relies on, and
  // (2) the driver can drain them deterministically to observe the deferred re-fit. Nothing else in the app
  // uses rAF, so this override only intercepts the map fix.
  const rafQ = [];
  win.requestAnimationFrame = (cb) => { rafQ.push(cb); return rafQ.length; };
  // ---- TWO-PHASE BOOT, part 1: boot() must return on the PHASE 1 products alone --------------------
  // tf.json / sci.json / manifest.json are HELD by the instrumented fetch above, so this is exactly the
  // window the split exists for. RED PROOF: before this change boot() awaited a Promise.all that carried
  // tf.json, so with that fetch held it could never resolve: this race would report "blocked" and the whole
  // driver below (2000+ existing assertions included) was unreachable.
  let _bootTimer = 0;
  const _blocked = new Promise(res => { _bootTimer = setTimeout(() => res("blocked"), 5000); });
  const _bootOutcome = await Promise.race([A.boot().then(() => "booted"), _blocked]);
  clearTimeout(_bootTimer);
  ok(_bootOutcome === "booted",
    "phase1: boot() must resolve on the FIRST-PAINT products alone (catalogue + surveys + the small " +
    "optionals); it is still blocked on the held tf/sci/manifest fetches");
  // PARALLELISM. Exactly TEN data fetches have been issued by boot, and all four heavy ones are in flight
  // at the same time. Before this change the five optionals ran STRICTLY ONE AFTER ANOTHER (each awaiting the
  // previous round trip) and none of them was even requested until the tf.json-carrying Promise.all had
  // resolved, so with tf held four of these urls would be missing from the log entirely.
  // ts_access.json rides PHASE 2 (D6): the Availability facet it feeds is one most visitors never open,
  // so it must never be one of the requests first paint waits on.
  const _bootUrls = ["catalogue.json", "surveys.json", "build_provenance.json", "collections.json",
    "build.json", "coord_policy.json", "tf.json", "sci.json", "manifest.json", "ts_access.json"];
  _bootUrls.forEach(n => ok(fetchOrder.some(u => u.endsWith("/" + n)),
    "phase1/2: " + n + " must be requested during boot (the optionals must not queue behind each other); issued: " + JSON.stringify(fetchOrder)));
  ok(fetchOrder.length === _bootUrls.length,
    "boot must issue exactly the ten data fetches, got " + JSON.stringify(fetchOrder));
  ok(heavyHeld() === 4, "phase2: tf/sci/manifest/ts_access must all be in flight CONCURRENTLY, held " + heavyHeld());
  ["tf", "sci", "manifest", "tsaccess"].forEach(k => ok(A.hydrState(k) === "pending",
    "phase2: the " + k + " gate must read 'pending' while its fetch is held, got " + A.hydrState(k)));
  ok(A.tsRoutes("au.alpha.A1") === null,
    "phase2: with ts_access.json in flight the hand-off index must read as UNKNOWN, never as an empty answer");
  ok(A.nST() === 5, "fixture should load 5 stations, got " + A.nST());

  // UX9 ITEM 2: MAP OFF-CENTRE-ON-LOAD FIX. The bug was buildMarkers' fitBounds computing against a
  // degenerate (stale/0x0) container size, so the map framed at zoom 0 / off centre. The fix (a) invalidates
  // size BEFORE the primary fit, and (c) adds a ONE-SHOT corrector on the setView('map') 60ms timer that
  // re-fits HOME_BOUNDS only when the fit was degenerate AND the user has not taken control. These run
  // synchronously at boot (the timer hasn't fired yet), so mapCalls holds the primary invalidateSize+fit here.
  // Owner round 2 (2026-07-22): the home frame is now the FIXED Australia box (AU_HOME_BOUNDS), NOT the tight
  // positioned-station extent (which dropped the view south and clipped northern Australia). buildMarkers no
  // longer assigns the pts array to HOME_BOUNDS and no longer passes a {padding:[24,24]} inset — it fits the
  // shared box directly so the post-load frame is byte-identical to the map-create fit the owner likes.
  // HOME-FRAME IDENTITY: HOME_BOUNDS is the SAME object as the map-create AU_HOME_BOUNDS (cannot drift) and is
  // NOT the old tight-extent pts array. This red-proves against the old `HOME_BOUNDS = pts` (an Array).
  ok(A.homeBounds() === A.auHomeBounds(), "item2: HOME_BOUNDS must be the shared fixed Australia box (=== AU_HOME_BOUNDS), not the tight station extent");
  ok(Array.isArray(A.homeBounds()) === false, "item2: HOME_BOUNDS must NOT be the tight positioned-station extent array (owner round 2: fixed Australia frame)");
  // (a): the PRIMARY (buildMarkers) fit is IMMEDIATELY preceded by an invalidateSize ({animate:false,pan:false})
  //      — the size is reclaimed before the box is measured, not after — and carries NO padding inset (the
  //      home frame is the fixed AU box, whose margins are baked into the coordinates).
  const _fitIdx = mapCalls.findIndex((c, i) => c.fn === "fitBounds" && i > 0
    && mapCalls[i - 1].fn === "invalidateSize"
    && (mapCalls[i - 1].args[0] || {}).animate === false && (mapCalls[i - 1].args[0] || {}).pan === false);
  ok(_fitIdx > 0, "item2: buildMarkers must fit the home bounds immediately after an invalidateSize({animate:false,pan:false}); no such fit recorded");
  ok(_fitIdx > 0 && mapCalls[_fitIdx].args[1] === undefined, "item2: the primary home fit must carry NO padding option (owner round 2: fit the fixed AU box directly), got " + JSON.stringify(mapCalls[_fitIdx].args[1]));
  // (c)-degeneracy: jsdom has no layout engine, so the headless map's size reads degenerate — exactly the
  //                 condition the corrector exists for. Recorded at boot.
  ok(A.homeFitDegenerate() === true, "item2: the boot fit must be recorded as degenerate under the headless (0x0) map");
  // PURE _mapSizeDegenerate: a real box is fine; a zero/partial/absent size is degenerate.
  ok(A.mapSizeDegenerate({ x: 800, y: 600 }) === false, "item2: an 800x600 size must not read degenerate");
  ok(A.mapSizeDegenerate({ x: 0, y: 0 }) === true, "item2: a 0x0 size must read degenerate");
  ok(A.mapSizeDegenerate({ x: 800 }) === true, "item2: a size missing an axis must read degenerate");
  ok(A.mapSizeDegenerate(null) === true, "item2: an absent size must read degenerate");
  // PURE _mapRefitGate: fires ONLY when the user has NOT taken control AND the fit was degenerate.
  ok(A.mapRefitGate({ userInteracted: false, fitDegenerate: true }) === true, "item2: gate must fire for untouched+degenerate");
  ok(A.mapRefitGate({ userInteracted: true, fitDegenerate: true }) === false, "item2: gate must NOT fire once the user has interacted (no fighting a deliberate view)");
  ok(A.mapRefitGate({ userInteracted: false, fitDegenerate: false }) === false, "item2: gate must NOT fire when the primary fit was healthy");
  // The corrector is ONE-SHOT: with the boot state (untouched + degenerate) it re-fits HOME_BOUNDS once and
  // then stands down — a second call (and, by extension, a later return to the map or an E6 programmatic fit)
  // records no further home re-fit.
  ok(A.mapUserInteracted() === false, "item2: the user-control flag must start false at boot");
  const _fbBefore = mapCalls.filter(c => c.fn === "fitBounds").length;
  A.mapCorrectHomeFit();
  ok(mapCalls.filter(c => c.fn === "fitBounds").length === _fbBefore + 1, "item2: the corrector must re-fit HOME_BOUNDS once when untouched+degenerate");
  ok(A.homeFitDegenerate() === false, "item2: the corrector must clear the degenerate flag (one-shot)");
  A.mapCorrectHomeFit();
  ok(mapCalls.filter(c => c.fn === "fitBounds").length === _fbBefore + 1, "item2: the corrector must NOT re-fit a second time (one-shot; must not clobber later/E6 fits)");

  // MAP OFF-CENTRE-ON-LOAD FIX (the DEFERRED re-fit) — the ACTUAL correction. The one-shot corrector above
  // only fires when the primary fit was DEGENERATE (0x0). On a real page load the flex layout hasn't settled
  // at fit time, so the container is NONZERO-BUT-WRONG: the degenerate gate never trips and the bad fit
  // sticks. The deferred re-fit re-fits HOME_BOUNDS UNCONDITIONALLY (gated ONLY on !userInteracted) once
  // layout settles (double-rAF). Regression guard: prove it is scheduled AND fires unconditionally.
  // buildMarkers (at boot) must have SCHEDULED the deferred re-fit into our parked rAF queue (outer frame).
  ok(rafQ.length === 1, "mapfit: buildMarkers must SCHEDULE a deferred re-fit via requestAnimationFrame, queued " + rafQ.length);
  // Precondition: the degenerate flag is already FALSE (the corrector cleared it above) and the user is
  // untouched — so a fit produced by draining the queue PROVES the deferred re-fit is UNCONDITIONAL, i.e.
  // NOT gated on degeneracy (the exact bug: the old corrector would NOT fit in this state).
  A.setMapInteracted(false);
  ok(A.homeFitDegenerate() === false, "mapfit precondition: the degenerate flag is already cleared");
  let _fbD = mapCalls.filter(c => c.fn === "fitBounds").length;
  rafQ.shift()();                              // OUTER frame -> must schedule the INNER frame (double-rAF)
  ok(rafQ.length === 1, "mapfit: the outer frame must schedule a SECOND (inner) frame so the re-fit runs after layout settles (double-rAF)");
  ok(mapCalls.filter(c => c.fn === "fitBounds").length === _fbD, "mapfit: no re-fit must occur until the inner frame runs");
  rafQ.shift()();                              // INNER frame -> invalidateSize + fitBounds(HOME_BOUNDS)
  ok(mapCalls.filter(c => c.fn === "fitBounds").length === _fbD + 1,
    "mapfit: the deferred re-fit must fit HOME_BOUNDS UNCONDITIONALLY once layout settles (regression: it must NOT be gated on the degenerate flag)");
  // it re-claims the true container size FIRST (invalidateSize immediately precedes the deferred fit).
  const _dfIdx = mapCalls.length - 1 - [...mapCalls].reverse().findIndex(c => c.fn === "fitBounds");
  ok(mapCalls[_dfIdx - 1].fn === "invalidateSize", "mapfit: the deferred re-fit must invalidateSize before fitting, got " + mapCalls[_dfIdx - 1].fn);
  // Gated ONLY on user control: once the user has taken over, the deferred re-fit stands down (never fight a
  // deliberate pan/zoom). Drive the body directly so BOTH gate legs are pinned.
  A.setMapInteracted(true);
  _fbD = mapCalls.filter(c => c.fn === "fitBounds").length;
  A.mapDeferredHomeRefit();
  ok(mapCalls.filter(c => c.fn === "fitBounds").length === _fbD, "mapfit: the deferred re-fit must NOT fire once the user has taken control");
  A.setMapInteracted(false);
  A.mapDeferredHomeRefit();
  ok(mapCalls.filter(c => c.fn === "fitBounds").length === _fbD + 1, "mapfit: untouched -> the deferred re-fit fits HOME_BOUNDS");

  // ---- TWO-PHASE BOOT, part 2: what the reader may see DURING hydration ----------------------------
  // Everything above ran with tf/sci/manifest still held. Two things are asserted here. First the POINT of
  // the split: the dots, the counts, the tree and the whole surveys view are already rendered off phase-1
  // data alone (pre-change none of this existed until every product had landed). Second the HONESTY RULE:
  // in that window no surface may render an ABSENCE claim for a product that is merely still in flight.
  ok(A.hydrState("tf") === "pending" && A.hydrState("sci") === "pending" && A.hydrState("manifest") === "pending",
    "phase2 window: the three gates must still read pending here");
  ok(A.nVisCount() === 5, "phase1: all five stations must be filtered and visible before hydration, got " + A.nVisCount());
  ok(A.markerCount() === 5, "phase1: a map marker must exist per positioned station before hydration, got " + A.markerCount());
  ok(doc.getElementById("nTot").textContent === "5", "phase1: the total-station count must be painted before hydration, got " + doc.getElementById("nTot").textContent);
  ok(doc.getElementById("nVis").textContent === "5", "phase1: the shown-station count must be painted before hydration, got " + doc.getElementById("nVis").textContent);
  ok(doc.getElementById("tree").querySelectorAll("input[value]").length === 4,
    "phase1: the survey tree must be built before hydration, got " + doc.getElementById("tree").querySelectorAll("input[value]").length);
  // The SURVEYS view renders entirely from phase-1 data.
  A.setView("surveys");
  ok(A.curView() === "surveys", "phase1: the surveys view must be reachable before hydration");
  const _preCards = doc.getElementById("cardGrid").innerHTML;
  ["Alpha Survey", "Beta Survey", "Gamma Survey", "Delta Survey"].forEach(sv => ok(_preCards.indexOf(sv) >= 0,
    "phase1: the surveys view must render the " + sv + " card before tf/sci/manifest resolve"));
  A.setView("map");

  // The ts_access-driven surfaces are inert-and-disabled, never live over data that has not
  // arrived: a live Download row would price the scope off routes that are not here, and a live
  // level filter would hide every station over them. (Lane B: colour-by is retired; the Data
  // available dropdown and the Download block's time-series rows are the gated surfaces.)
  const _tsBtns = () => [...doc.getElementById("tsSeg").querySelectorAll("button")];
  ok(_tsBtns().length === 4,
    "A6/D8: one Download row per ROUTABLE level token (level2 opens nothing, D19), got " + _tsBtns().length);
  ok(_tsBtns().every(b => b.disabled),
    "honesty: the time-series Download rows must be disabled while ts_access.json is in flight");
  ok(_tsBtns()[0].getAttribute("aria-busy") === "true",
    "honesty: an in-flight hand-off index makes the rows aria-busy, not merely inert");
  const _availLevelOpts = () => [...doc.getElementById("availSel").querySelectorAll("option")].filter(o => o.value && o.value !== "tf");
  ok(_availLevelOpts().length === 4 && _availLevelOpts().every(o => o.disabled),
    "honesty: the Data available level options must be disabled while ts_access.json is in flight");
  A.setAvail("raw_packed");
  A.refresh();
  ok(A.nVisCount() === 5,
    "honesty: the level filter must be INERT while ts_access.json is in flight; emptying the map would read as 'no station publishes this level', got " + A.nVisCount());
  A.setAvail("");
  A.refresh();
  A.setQMin(4.5);                                    // stricter than every fixture station's q (4.0)
  A.refresh();
  ok(A.nVisCount() === 5,
    "honesty: the completeness filter must be INERT while sci.json is in flight; it may never empty the map over values that have not arrived, got " + A.nVisCount());
  A.setQMin(0); A.refresh();

  // B1 (Beta Survey, open access, edi_available=0) reaches the ediDescriptor branches A1 never does: with no
  // served artifact and no embargo, the ungated function falls through to "EDI (via source archive)", a
  // ROUTING claim that needs the manifest to be true, and headerDownloadBtn's d:null makes the sticky header
  // render nothing, which in that function IS the embargo signal. Both are absence claims about a station
  // that may well be downloadable; the manifest just has not arrived.
  A.openStation(2);
  const _b1 = doc.getElementById("drawer").innerHTML;
  ok(_b1.indexOf("EDI (via source archive)") < 0,
    "honesty: the source-archive EDI fallback is a claim about how this deployment serves the file and must not render before the manifest lands");
  ok(_b1.indexOf('class="badges"') < 0,
    "honesty: the format-availability badges must not render before the manifest lands (an 'unk' badge claims a format is not served here)");
  ok(/Loading served files/.test(_b1),
    "honesty: the format-availability block must say it is loading in their place");
  ok(/checking file availability/.test(_b1),
    "honesty: the sticky-header download slot must SAY it is checking; rendering nothing there is how this drawer states an embargo");
  // The lineage Method node reads sc[SC.alg]/sc[SC.rr]: ungated it prints "not stated", a claim about what
  // the source EDI carried.
  const _mIdx = _b1.indexOf('<div class="lt">Method</div>');
  ok(_mIdx >= 0, "the lineage Method node must render");
  ok(_b1.slice(_mIdx, _mIdx + 200).indexOf("loading…") >= 0,
    "honesty: the lineage Method node must read as loading while sci.json is in flight, never 'not stated'");

  // The SURVEY drawer has its own sci/manifest surfaces, and its bundle grid makes its absence claim by
  // OMISSION (no tiles reads as "this survey is not served in bundle form"), which is no more honest for
  // being wordless.
  A.openSurvey("Alpha Survey");
  const _svPre = doc.getElementById("drawer").innerHTML;
  const _rrIdx = _svPre.indexOf("<td>remote reference</td>");
  ok(_rrIdx >= 0, "the survey summary must render its remote-reference row");
  ok(_svPre.slice(_rrIdx, _rrIdx + 160).indexOf("loading…") >= 0,
    "honesty: the survey remote-reference tally must read as loading while sci.json is in flight, never 'not recorded'");
  const _swIdx = _svPre.indexOf("<td>processing software</td>");
  ok(_swIdx >= 0, "the survey summary must render its processing-software row");
  ok(_svPre.slice(_swIdx, _swIdx + 160).indexOf("loading…") >= 0,
    "honesty: the survey processing-software row must read as loading while sci.json is in flight, never 'not recorded'");
  ok(/Survey bundles<small>loading…<\/small>/.test(_svPre),
    "honesty: the survey bundle grid must show a loading tile while the manifest is in flight; rendering no tiles claims the survey is not served in bundle form");

  // A station drawer opened DURING hydration: loading states, and NOT ONE of the honest-absence lines that
  // belong to a product this build genuinely does not serve.
  A.openStation(0);                                  // A1 (Alpha Survey, open access, real curves in the fixture)
  const _preDrawer = doc.getElementById("drawer").innerHTML;
  ok(/Loading response functions/.test(_preDrawer),
    "honesty: the response panel must show a loading state while tf.json is in flight");
  ok(!/data-plot=/.test(_preDrawer),
    "honesty: no response plot may render before tf.json lands (an empty curve set renders as NO plot, i.e. as 'this station has no response functions')");
  ok(!/class="plotexp/.test(_preDrawer),
    "honesty: the expand control must be withheld while there are no curves to expand");
  ok(!/class="matdim /.test(_preDrawer),
    "honesty: the stewardship rows must not render while sci.json is in flight (an unlit star claims a dimension was not achieved)");
  ok(/Loading stewardship details/.test(_preDrawer), "honesty: the stewardship list must say it is loading instead");
  ok(/loading…/.test(_preDrawer), "honesty: the sci/manifest-backed summary cells must read as loading");
  ["not currently available", "none currently served", "not stated in EDI", "EDI (via source archive)"]
    .forEach(copy => ok(_preDrawer.indexOf(copy) < 0,
      "honesty: '" + copy + "' is a claim about what this build serves and must NOT render before hydration"));

  // The re-render on each settling gate rewrites a panel the reader is ALREADY READING. Two things must not
  // ride along with it: an expander they opened may not snap shut (three gates = up to three rewrites across
  // a multi-second window), and the per-station station.json frame-line fetch may not be re-issued each time.
  const _findDetails = (w, label) => [...w.getElementById("drawer").querySelectorAll("details")]
    .find(d => d.querySelector("summary") && d.querySelector("summary").textContent === label);
  const _lineage = _findDetails(doc, "Lineage graph");
  ok(!!_lineage, "the Lineage graph expander must be present in the station drawer");
  _lineage.open = true;
  const _stationJsonBefore = fetchOrder.filter(u => /station\.json$/.test(u)).length;
  ok(_stationJsonBefore >= 1, "opening a station drawer must fetch its station.json for the frame line");

  // ---- TWO-PHASE BOOT, part 3: late hydration must refresh what it made stale ----------------------
  releaseHeavy();
  await A.hydrationDone();
  ["tf", "sci", "manifest", "tsaccess"].forEach(k => ok(A.hydrState(k) === "ready",
    "hydration: the " + k + " gate must settle to 'ready', got " + A.hydrState(k)));
  // The fixture data dir ships NO ts_access.json, which is the deployment case the engine produces
  // for a corpus with no verified routes. That 404 is an ANSWER, not a failure: the gate settles
  // ready on an empty index, and nothing anywhere may report it as a load error.
  ok(A.hydrState("tsaccess") !== "failed",
    "honesty: an absent ts_access.json is a deployment that publishes no download index, never a failure");
  ok(A.tsRoutes("au.alpha.A1") === null && JSON.stringify(A.tsAccess()) === "{}",
    "hydration: an absent ts_access.json must settle to an EMPTY index, not stay unknown, got " + JSON.stringify(A.tsAccess()));
  // ...and the chooser SAYS SO. This is the wording rule: an empty index is a fact about the DEPLOYMENT,
  // and calling it a load error would blame the network for a build that published no routes.
  const _tsSettled = [...doc.getElementById("tsSeg").querySelectorAll("button")];
  ok(_tsSettled.every(b => b.disabled), "the chooser stays disabled when the deployment publishes no routes");
  ok(_tsSettled[0].getAttribute("aria-busy") === "false",
    "honesty: a settled empty index is not busy; aria-busy must not tell a screen reader to keep waiting");
  ok(/publishes no download index/.test(_tsSettled[0].title) && !/could not be loaded/.test(_tsSettled[0].title),
    "honesty: the disabled hint must name the deployment, never a load failure, got " + JSON.stringify(_tsSettled[0].title));
  ok(/publishes no download index/.test(doc.getElementById("tsSegNote").textContent),
    "the group's own note must state the same thing in words, got " + JSON.stringify(doc.getElementById("tsSegNote").textContent));
  const _postDrawer = doc.getElementById("drawer").innerHTML;
  ok(!/Loading response functions/.test(_postDrawer),
    "hydration: a stale loading state may not stand once tf.json has landed; the OPEN drawer must re-render");
  ok(/data-plot="rho"/.test(_postDrawer) && /data-plot="pt"/.test(_postDrawer),
    "hydration: the OPEN drawer must re-render with its response curves");
  ok(/>A1</.test(_postDrawer), "hydration: the re-render must keep the SAME station open");
  ok(/BIRRP/.test(_postDrawer), "hydration: the sci-derived processing software must fill in on the open drawer");
  ok((_postDrawer.match(/class="matdim /g) || []).length === 5,
    "hydration: all five stewardship rows must render once sci.json has landed");
  ok(_postDrawer.indexOf("loading…") < 0, "hydration: no loading cell may survive hydration");
  // The absence copy the fixture DOES earn (it ships no manifest, so no EMTF XML / MTH5 is served) appears
  // only now, which is the whole point: the same words are honest after hydration and dishonest before it.
  ok(_postDrawer.indexOf("not currently available") >= 0,
    "hydration: with the manifest loaded and empty, the genuine not-served copy must render");
  // sci-derived station state and the rail controls come back to life together.
  ok(_postDrawer.indexOf("checking file availability") < 0, "hydration: the header availability check must resolve too");
  // The re-render must not cost the reader their place or the network a repeat round trip.
  const _lineageAfter = _findDetails(doc, "Lineage graph");
  ok(!!_lineageAfter && _lineageAfter.open === true,
    "hydration: an expander the reader opened during the hydration window must still be open after the re-render");
  ok(fetchOrder.filter(u => /station\.json$/.test(u)).length === _stationJsonBefore,
    "hydration: the re-render must not re-issue the station.json frame-line fetch once per settling gate, issued " +
    fetchOrder.filter(u => /station\.json$/.test(u)).length + " vs " + _stationJsonBefore);
  ok(A.station("A1").q === 4.0, "hydration: s.q must be re-folded onto the stations from sci.json, got " + A.station("A1").q);
  A.setQMin(4.5); A.refresh();
  ok(A.nVisCount() === 0,
    "hydration: the completeness filter must be LIVE after sci.json lands (q=4.0 < 4.5 for every fixture station), got " + A.nVisCount());
  A.setQMin(0); A.refresh();
  A.closeDrawer();
  win.location.hash = "";

  // ---- TWO-PHASE BOOT, part 4: a FAILED heavy product is not an absence either ---------------------
  // A fresh window whose tf.json 404s (a broken or partial build). Before the split that was FATAL: tf.json
  // rode in the required Promise.all, so the whole portal fell back to the load-error page. Now first paint
  // survives it, which makes it critical that the response panel SAYS the curves could not be loaded instead
  // of rendering exactly the nothing a station with no curves renders.
  const _noTf = Object.assign({}, DATAMAP); delete _noTf["data/tf.json"];
  const failWin = await bootFreshWindow(_noTf);
  ok(failWin.__api.nST() === 5, "a missing tf.json must no longer blank the portal; the stations must still paint");
  ok(failWin.__api.hydrState("tf") === "failed",
    "a 404 on tf.json must settle its gate to 'failed', got " + failWin.__api.hydrState("tf"));
  ok(failWin.__api.hydrState("sci") === "ready", "the other gates must be unaffected by the tf failure");
  failWin.__api.openStation(0);
  const _failDrawer = failWin.document.getElementById("drawer").innerHTML;
  ok(/Could not load response functions/.test(_failDrawer),
    "honesty: a FAILED tf.json must be STATED, never rendered as a station that has no response functions");
  ok(!/data-plot=/.test(_failDrawer), "a failed tf.json leaves no curves to plot");
  ok(_failDrawer.indexOf("Loading response functions") < 0, "a settled failure must not read as still loading");
  // Lane B (owner D3): the strike rose is retired; its control must be GONE, not disabled.
  ok(!failWin.document.getElementById("strike"), "the strike-rose control is retired and must not render");

  // ---- TWO-PHASE BOOT, part 4b: a FAILED sci.json is not a screening outcome ----------------------
  // The map, the rail and the exports cannot show a per-item loading line, so they gate on whether the
  // product is USABLE, which covers pending AND failed. Testing only "pending" was the defect: SCI_READY
  // settles on failure too, so a 404 on sci.json re-enabled the completeness controls, emptied the map at any
  // qMin, painted every marker the "not evaluated" grey and wrote remote_ref:false into an exported file.
  // Phase 2 is what made a sci.json failure survivable at all (pre-split it rode the required Promise.all and
  // blanked the portal), so this state is this lane's to answer.
  const _noSci = Object.assign({}, DATAMAP); delete _noSci["data/sci.json"];
  const sciFailWin = await bootFreshWindow(_noSci);
  const sfDoc = sciFailWin.document, sfA = sciFailWin.__api;
  ok(sfA.hydrState("sci") === "failed", "a 404 on sci.json must settle its gate to 'failed', got " + sfA.hydrState("sci"));
  ok(sfA.nST() === 5, "a missing sci.json must no longer blank the portal; the stations must still paint");
  sfA.setQMin(4.5); sfA.refresh();
  ok(sfA.nVisCount() === 5,
    "honesty: the completeness filter must be INERT on a FAILED sci.json; emptying the map reads as 'no station meets this threshold', got " + sfA.nVisCount());
  sfA.setQMin(0); sfA.refresh();
  // An export leaves the page. remote_ref:!!undefined is a POSITIVE claim that these stations were not
  // remote-referenced, and quality/dimensionality would vanish as undefined keys with no trace of why.
  const _gjFail = sfA.geoFC([sfA.station("A1")]);
  const _pFail = _gjFail.features[0].properties;
  ok(!("remote_ref" in _pFail),
    "honesty: a FAILED sci.json must not write remote_ref into an exported FILE, got " + JSON.stringify(_pFail.remote_ref));
  ok(!("quality" in _pFail) && !("dimensionality" in _pFail),
    "the other two screening properties must be omitted with it, not silently dropped as undefined");
  ok(typeof _gjFail.note === "string" && /could not be loaded/.test(_gjFail.note),
    "honesty: the FILE must carry the reason those properties are missing; a toast does not travel with a download");
  ok(_pFail.ausmt_id === "au.alpha.A1" && _pFail.license_url !== undefined,
    "the phase-1 properties must be unaffected by the sci failure");
  // And the healthy path is byte-for-byte what it was: the gate must not cost a good build its data.
  const _gjOk = A.geoFC([A.station("A1")]);
  ok(_gjOk.note === undefined, "a healthy sci.json must add NO note to the GeoJSON");
  ok(_gjOk.features[0].properties.quality === 4.0 && _gjOk.features[0].properties.dimensionality === "2-D" &&
     _gjOk.features[0].properties.remote_ref === true,
    "a healthy sci.json must write the three screening properties exactly as before");

  // VER CHIP OFF EVERY SURFACE. The one-footer ruling took Releases and About this build out of the
  // footer, and the version chip rode inside the About-this-build popover; it landed in about.html's
  // #build section, and the owner has now deleted that section too. NO page on this site carries a
  // chip, and no page loads the script either. version.js is a standalone page script (not in
  // MODULES), so run it here against the real DOM as a page that loaded it would, then assert:
  //   (a) this document carries NO [data-ver-chip], in the header, the footer or anywhere else;
  //   (b) version.js still DERIVES a correct label and POPULATES a chip wherever one is supplied,
  //       driven in its own jsdom because no shipped page supplies the node the fill would land in.
  //       The file is kept rather than deleted even though nothing loads it: the label logic and
  //       its config-missing sentinel are the contract a future build page would be held to, and
  //       this is the only place they are exercised. portal/tests/test_about_uniform_chrome.py
  //       holds both zero-everywhere halves, the chips and the loads, across every document.
  vm.runInContext(fs.readFileSync(path.join(PORTAL, "version.js"), "utf8"), dom.getInternalVMContext());
  const spaChips = [...doc.querySelectorAll("[data-ver-chip]")];
  ok(spaChips.length === 0,
    "the SPA carries no version chip: it left with the About-this-build popover, found " + spaChips.length);
  const chipDom = new JSDOM('<section id="build"><span data-ver-chip></span></section>',
    { runScripts: "outside-only" });
  chipDom.window.AUSMT_CONFIG = doc.defaultView.AUSMT_CONFIG;
  vm.runInContext(fs.readFileSync(path.join(PORTAL, "version.js"), "utf8"), chipDom.getInternalVMContext());
  ok(chipDom.window.AUSMT_VERSION.label === "AusMT v1.2.3 · MTCAT 1.0",
    "version.js must still derive the chip label from the loaded config, got: " +
    JSON.stringify(chipDom.window.AUSMT_VERSION.label));

  // THE CONFIG-MISSING SENTINEL must be HONEST. version.js used to fall back to schema_version "1.0",
  // so a page whose config.js failed to load rendered a confident "MTCAT 1.0" chip through the whole of
  // schema 1.1 and 1.2. A JS file cannot read engine/schema/mtcat.schema.json at render time, so the
  // sentinel now carries NO version and the chip stops after the schema name. Driven in its own bare
  // jsdom (no AUSMT_CONFIG at all), because that is the only state that reaches the sentinel.
  const bare = new JSDOM("<footer><span data-ver-chip></span></footer>", { runScripts: "outside-only" });
  vm.runInContext(fs.readFileSync(path.join(PORTAL, "version.js"), "utf8"), bare.getInternalVMContext());
  // Assert the LABEL, not the filled node: a just-constructed jsdom document can still be "loading",
  // in which case version.js correctly defers fill() to DOMContentLoaded. The label is the exact string
  // fill() writes into every chip (the populated-chip case is the assertion directly above), so this
  // pins the rendered text without racing the document's own readiness.
  const bareLabel = bare.window.AUSMT_VERSION.label;
  ok(bareLabel === "AusMT v0.0.0 · MTCAT",
    "with no config loaded the chip must name the schema and state NO version, got: " + JSON.stringify(bareLabel));
  ok(!/MTCAT\s*\d/.test(bareLabel),
    "the config-missing chip must not end in a schema version number, got: " + JSON.stringify(bareLabel));
  ok(bare.window.AUSMT_VERSION.schema_version === null,
    "the config-missing sentinel must expose schema_version null (an explicit 'no version'), got: " +
    JSON.stringify(bare.window.AUSMT_VERSION.schema_version));

  // UX4 (D1) AUSLAMP MEMBERSHIP. Collection membership, resolved once at boot.
  //
  //   AUSLAMP_SET is built at boot from COLL.auslamp.surveys (survey LABELS) resolved through
  //   SMETA[label].slug. The fixture's auslamp collection lists ["Alpha Survey","Beta Survey"] whose slugs
  //   are "alpha"/"beta", so the boot-built set MUST be exactly {alpha, beta} — proving the label->slug
  //   resolution (the collections.json member list is labels, the predicate keys off slug).
  const _bootSet = [...A.auslampSet()].sort();
  ok(_bootSet.length === 2 && _bootSet[0] === "alpha" && _bootSet[1] === "beta",
    "buildAuslampSet must resolve COLL.auslamp.surveys (labels) to SMETA slugs {alpha,beta}, got: " + JSON.stringify(_bootSet));
  // isAuslampSurvey(slug, set): membership true/false/absent-set cases.
  ok(A.isAuslampSurvey("alpha", A.auslampSet()) === true, "isAuslampSurvey must be true for a member slug");
  ok(A.isAuslampSurvey("gamma", A.auslampSet()) === false, "isAuslampSurvey must be false for a non-member slug");
  ok(A.isAuslampSurvey("alpha", new Set()) === false, "isAuslampSurvey must be false against an empty set (absent collection)");
  ok(A.isAuslampSurvey(null, A.auslampSet()) === false, "isAuslampSurvey must be false for a null slug");
  // The never-collapse PRIVILEGE the membership set used to buy is gone with the badges (owner,
  // 2026-08-24): nothing on the map collapses, so no map surface reads AUSLAMP_SET at all. What is pinned
  // here is only what still exists - the boot resolution above and the predicate over it.

  // ZOOM-SCALED RADII. The UX4-D4 four-step ladder (2.5/3.5/4.5/5) became a CONTINUOUS ramp with a floor
  // and a ceiling; the drawer-polish lane (owner, 2026-08-19) then removed the per-TYPE base, so ONE curve
  // serves every data type - "the same size as the icons set for the AusLAMP sites". The pinned PROPERTY is
  // unchanged and still asserted here (monotone non-decreasing in z); the exact curve, its bounds and the
  // type-uniformity are pinned in tools/map_dots_test.js against the named constants.
  for (let z = 0; z < 16; z++) {
    ok(A.radiusForZoom(z + 1) >= A.radiusForZoom(z),
      "radiusForZoom must stay monotone non-decreasing in z (z=" + z + ")");
  }
  ok(A.radiusForZoom(4, "LPMT") === A.radiusForZoom(4, "BBMT"),
    "uniform site dots: LP and BB must render the SAME size (type is carried by colour, never by size), got " +
    A.radiusForZoom(4, "LPMT") + " / " + A.radiusForZoom(4, "BBMT"));
  ok(A.radiusForZoom(4) === A.radiusForZoom(4, "BBMT"),
    "the retired `type` argument must be INERT: passing one may not change the radius");
  ok(A.weightForZoom(4) === 1.0 && A.weightForZoom(0) === 1.0, "weightForZoom(z<=4) must be 1.0");
  ok(A.weightForZoom(5) === 1.5 && A.weightForZoom(9) === 1.5, "weightForZoom(z>=5) must be 1.5");
  for (let z = 0; z < 12; z++) {
    ok(A.radiusForZoom(z + 1) >= A.radiusForZoom(z), "radiusForZoom must be monotone non-decreasing at z=" + z);
    ok(A.weightForZoom(z + 1) >= A.weightForZoom(z), "weightForZoom must be monotone non-decreasing at z=" + z);
  }

  // UX4 Amendment A1 COLOUR (still live) + O4 TOOLTIP (2026-07-12). Colour: EVERY colour mode is
  // membership-blind — type mode gives member and non-member LPMT the IDENTICAL flagship teal. Tooltip:
  // O4 slimmed it to station name + survey name ONLY, so the AusLAMP/legacy distinction is NO LONGER on
  // the tooltip — it survives only in the D2 clustering split. Two synthetic LPMT stations differing ONLY
  // by membership (each given a survey so the O4 tooltip has a survey name).
  A.setAuslampSet(["memb"]);
  const _memberLp = { id: "S1", type: "LPMT", slug: "memb", q: 4.2, dim: "2-D", survey: "Alpha Survey" };
  const _otherLp = { id: "S2", type: "LPMT", slug: "notmemb", q: 4.2, dim: "2-D", survey: "Beta Survey" };
  // Lane B: colour-by is retired; the ONE marker colour is the data-type colour, membership-blind.
  ok(A.markerColor(_memberLp) === A.markerColor(_otherLp),
    "A1: marker colour must be IDENTICAL for AusLAMP vs non-AusLAMP LPMT (no colour split), got: " + A.markerColor(_memberLp) + " / " + A.markerColor(_otherLp));
  ok(A.markerColor(_memberLp) === "#2E8FA3", "A1: all LPMT must render the flagship teal #2E8FA3, got " + A.markerColor(_memberLp));
  // O4 (owner, 2026-07-12): the hover tooltip is station name + survey name ONLY — no diagnostic Q, no
  // type/AusLAMP label. Pre-O4 it swapped the type label to "AusLAMP" for members; that distinction now
  // lives only in the D2 clustering split. Asserting the diagnostic + type/AusLAMP label are GONE is what
  // fails on pre-O4 code (which carried "· Q 4.2" and the AusLAMP/LPMT label).
  const _tMemb = A.tooltipText(_memberLp), _tOther = A.tooltipText(_otherLp);
  ok(_tMemb === "S1 · Alpha Survey", "O4: member tooltip must be 'station · survey' only, got: " + JSON.stringify(_tMemb));
  ok(_tOther === "S2 · Beta Survey", "O4: non-member tooltip must be 'station · survey' only, got: " + JSON.stringify(_tOther));
  ok(_tMemb.indexOf("Q ") < 0 && _tMemb.indexOf("4.2") < 0, "O4: the TF diagnostic (Q) must be gone from the hover tooltip, got: " + JSON.stringify(_tMemb));
  ok(_tMemb.indexOf("AusLAMP") < 0 && _tMemb.indexOf("LPMT") < 0, "O4: the type/AusLAMP label must be gone from the hover tooltip, got: " + JSON.stringify(_tMemb));
  A.buildAuslampSet();   // restore the boot-built set for the rest of the run

  // A. buildTree made REAL checkboxes (the smoke stub never did): 2 countries, 4 orgs, 4 surveys.
  //    (C1b added Delta Survey / OrgW / station D1 — an embargoed survey, still fully discoverable.)
  const countryBoxes = [...doc.querySelectorAll("#tree input[data-country]")].filter(b => !b.hasAttribute("value"));
  const orgBoxes = [...doc.querySelectorAll("#tree input[data-org]")].filter(b => !b.hasAttribute("value"));
  const surveyBoxes = [...doc.querySelectorAll("#tree input[value]")];
  ok(countryBoxes.length === 2, "expected 2 country checkboxes, got " + countryBoxes.length);
  ok(orgBoxes.length === 4, "expected 4 org checkboxes, got " + orgBoxes.length);
  ok(surveyBoxes.length === 4, "expected 4 survey checkboxes, got " + surveyBoxes.length);
  ok(A.visIds().length === 5, "all 5 stations visible at baseline, got " + A.visIds().length);

  // B. COUNTRY toggle: unchecking New Zealand must sync its survey box AND drop its station.
  //    (The value-less-checkbox bug left the listener unbound, so this did nothing.)
  const nz = countryBoxes.find(b => b.getAttribute("data-country") === "New Zealand");
  ok(nz, "no New Zealand country checkbox");
  nz.checked = false; fire(nz, "change");
  ok(surveyBoxes.find(b => b.value === "Gamma Survey").checked === false, "country toggle did NOT sync its survey checkbox");
  ok(!A.visIds().includes("G1"), "country toggle did NOT filter out its station");
  ok(A.visIds().length === 4, "expected 4 visible after hiding New Zealand, got " + A.visIds().length);
  nz.checked = true; fire(nz, "change");
  ok(A.visIds().length === 5, "re-checking the country did not restore its station");

  // C. ORG toggle: unchecking Australia||OrgX must sync Alpha Survey AND drop its 2 stations, leaving the
  //    sibling org (OrgY/Beta) untouched.
  const orgx = orgBoxes.find(b => b.getAttribute("data-org") === "Australia||OrgX");
  ok(orgx, "no Australia||OrgX org checkbox");
  orgx.checked = false; fire(orgx, "change");
  ok(surveyBoxes.find(b => b.value === "Alpha Survey").checked === false, "org toggle did NOT sync its survey checkbox");
  ok(!A.visIds().includes("A1") && !A.visIds().includes("A2"), "org toggle did NOT filter out its stations");
  ok(A.visSurveys().includes("Beta Survey"), "org toggle wrongly hid a sibling org's survey");
  orgx.checked = true; fire(orgx, "change");

  // C2. UX7a (A3) COLLECTIONS GROUP — its OWN block ABOVE the tree (was UX5 (D6) first-WITHIN the tree),
  //     cross-cutting, push-only. The group is now mounted in #collGroup, OUTSIDE #tree.
  const treeEl = doc.getElementById("tree");
  const collGroupEl = doc.getElementById("collGroup");
  ok(collGroupEl, "A3: #collGroup block missing from the rail");
  const collRow = collGroupEl.querySelector("label.coll");
  // (a) the group renders in its own block, with its heading, and NOT inside the tree.
  ok(collRow, "A3: no collection row rendered in the #collGroup block");
  ok(collGroupEl.querySelector(".treegroup"), "A3: Collections group heading missing from #collGroup");
  //     HEADER-ABSENCE (hermetic): #tree must now carry NO collection rows/heading — collections live
  //     strictly OUTSIDE and ABOVE it. Non-vacuous precisely because collRow above proves a collection
  //     row DOES exist (in #collGroup): an empty result here is a real relocation, not a missing feature.
  ok(!treeEl.querySelector(".coll") && !treeEl.querySelector(".treegroup"),
    "A3: #tree must contain NO collection rows/heading (collections render in #collGroup above the tree)");
  //     ORDER: #collGroup precedes #tree in document order (the block sits ABOVE the tree header).
  //     compareDocumentPosition sets DOCUMENT_POSITION_FOLLOWING (4) when treeEl FOLLOWS collGroupEl.
  ok((collGroupEl.compareDocumentPosition(treeEl) & 4) !== 0,
    "A3: the #collGroup block must appear BEFORE #tree in document order (collections above the tree)");
  ok(/AusLAMP: 2 surveys · 3 stations/.test(collRow.textContent),
    "A3: collection row label must read '<name>: <n> surveys · <m> stations' (Alpha 2 + Beta 1 = 3), got: " + collRow.textContent);
  // O1 (owner, 2026-07-12): the collection row carries NO nested member-survey list any more — just the
  // name + survey count + station count. Members stay reachable via the org/country tree + collection page.
  ok(collGroupEl.querySelectorAll(".collmember").length === 0,
    "O1: collection rows must NOT nest a member-survey list, got " + collGroupEl.querySelectorAll(".collmember").length);
  // (b) PUSH-SYNC: unchecking the collection box flips EXACTLY the member surveys (Alpha+Beta) and
  // refreshes; non-members (Gamma, Delta) untouched. Re-check restores. Member surveys still live in #tree.
  const collBox = collRow.querySelector("input[data-coll]");
  ok(collBox, "A3: collection checkbox missing");
  collBox.checked = false; fire(collBox, "change");
  ok(surveyBoxes.find(b => b.value === "Alpha Survey").checked === false, "UX5: collection uncheck did not flip member Alpha Survey");
  ok(surveyBoxes.find(b => b.value === "Beta Survey").checked === false, "UX5: collection uncheck did not flip member Beta Survey");
  ok(surveyBoxes.find(b => b.value === "Gamma Survey").checked === true, "UX5: collection uncheck must NOT touch non-member Gamma");
  ok(surveyBoxes.find(b => b.value === "Delta Survey").checked === true, "UX5: collection uncheck must NOT touch non-member Delta");
  ok(A.visIds().length === 2 && A.visIds().includes("G1") && A.visIds().includes("D1"),
    "UX5: collection uncheck did not refresh the filter (expected exactly G1+D1), got " + JSON.stringify(A.visIds()));
  collBox.checked = true; fire(collBox, "change");
  ok(A.visIds().length === 5, "UX5: re-checking the collection did not restore all 5 stations");

  // C3. UX5 (D7) THE INVARIANT: collapse/expand NEVER changes checkbox state and NEVER changes the
  // filter result — with MIXED checkbox states (Beta unchecked). getAttribute('value') deliberately
  // (a value-less checkbox's .value is 'on' — the classic trap this codebase already documents).
  const betaBox = surveyBoxes.find(b => b.value === "Beta Survey");
  betaBox.checked = false; fire(betaBox, "change");
  const snapshot = () => [...treeEl.querySelectorAll("input")]
    .map(i => (i.getAttribute("value") || i.dataset.coll || i.dataset.org || i.dataset.country) + "=" + i.checked).join(",");
  const before = snapshot(), visBefore = JSON.stringify(A.visIds());
  // O1 (2026-07-12): collection rows no longer disclose member rows, so there is no k: collapse key to
  // exercise here — the invariant is carried by the country/org carets (which still hide survey rows).
  ["c:Australia", "o:Australia||OrgX"].forEach(k => A.treeSetCollapsed(k, true));
  ok(snapshot() === before, "UX5 INVARIANT: collapsing changed a checkbox state.\n  before " + before + "\n  after  " + snapshot());
  ok(JSON.stringify(A.visIds()) === visBefore, "UX5 INVARIANT: collapsing changed the filter result: " + visBefore + " -> " + JSON.stringify(A.visIds()));
  // ...and the collapse REALLY hid rows (the invariant is not vacuously testing a no-op):
  ok(treeEl.querySelectorAll("label.survey.hidden").length > 0, "UX5: collapsing Australia hid no survey rows (visibility not applied)");
  ok(A.visIds().includes("A1"), "UX5 INVARIANT: a checked-but-HIDDEN survey dropped off the map (visibility leaked into filtering)");
  ["c:Australia", "o:Australia||OrgX"].forEach(k => A.treeSetCollapsed(k, false));
  ok(snapshot() === before && JSON.stringify(A.visIds()) === visBefore, "UX5 INVARIANT: expanding changed checkbox state or the filter result");
  ok(treeEl.querySelectorAll("label.survey.hidden").length === 0, "UX5: expanding did not unhide the survey rows");
  betaBox.checked = true; fire(betaBox, "change");
  ok(A.visIds().length === 5, "UX5 cleanup: restoring Beta did not restore 5 visible");

  // C4. UX5 (D7) CARET CLICK-TARGET: a caret click must NOT toggle the row's checkbox (the rows are
  // label-wrapped, so an unguarded child click would activate the label) — and must collapse/expand.
  // "Australia" sorts before "New Zealand"; find its country row directly in #tree (the shared
  // kids/firstCountryIdx indices were dropped when the collections group moved out of the tree in A3).
  const ausRow = [...treeEl.querySelectorAll("label.country")]
    .find(r => { const i = r.querySelector("input[data-country]"); return i && i.getAttribute("data-country") === "Australia"; });
  ok(ausRow, "UX5: no Australia country row found in #tree");
  const caret = ausRow.querySelector(".caret");
  ok(caret, "UX5: country row has no caret");
  const ausBox = ausRow.querySelector("input");
  const wasChecked = ausBox.checked;
  caret.dispatchEvent(new win.MouseEvent("click", { bubbles: true, cancelable: true }));
  ok(ausBox.checked === wasChecked, "UX5: caret click toggled the country checkbox (click-target hazard)");
  ok(A.treeIsCollapsed("c:Australia"), "UX5: caret click did not collapse the country");
  ok(caret.textContent === "▸", "UX5: caret glyph did not flip to collapsed, got " + JSON.stringify(caret.textContent));
  caret.dispatchEvent(new win.MouseEvent("click", { bubbles: true, cancelable: true }));
  ok(!A.treeIsCollapsed("c:Australia") && caret.textContent === "▾", "UX5: caret re-click did not expand");

  // D. COLLECTION route: #/collection/<id> shows the full-width page over the map; Back restores the map.
  win.location.hash = "#/collection/auslamp"; A.routeFromHash();
  ok(A.curView() === "collection", "hash route did not enter the collection view");
  ok(doc.getElementById("collectionview").style.display === "block", "#collectionview not shown");
  ok(doc.getElementById("map").style.display === "none", "#map not hidden behind the collection page");
  ok(/AusLAMP/.test(doc.getElementById("collectionview").innerHTML), "collection page missing its title");
  win.location.hash = ""; A.routeFromHash();
  ok(A.curView() === "map", "Back from the collection page did not restore the map view");

  // E. FIND: typing a survey name lists it AND keeps its stations on the map (the blank-map fix: passes()
  //    must also match s.survey, else a survey-name query — which Find invites — empties the map).
  const find = doc.getElementById("find");
  find.value = "Alpha Survey"; fire(find, "input");
  const items = [...doc.querySelectorAll("#findResults .fitem")];
  ok(items.some(it => it.dataset.find === "survey"), "Find dropdown did not offer the matching survey");
  ok(A.visSurveys().includes("Alpha Survey"), "Find blanked the map for a survey-name query");
  ok(!A.visSurveys().includes("Beta Survey"), "Find query should still exclude non-matching surveys");

  // E2 (UX6 Wave F, F3): the live Find dropdown is keyboard-operable. ArrowDown highlights the first
  // option as an active-descendant; Enter activates it on the SAME path as a click (opens the station);
  // Esc clears the query. Non-vacuous: before F3 there was no keydown handler on #find, so no option ever
  // got aria-selected, the input never carried aria-activedescendant, and Esc left the box untouched.
  find.value = "A1"; fire(find, "input");
  const kbFR = doc.getElementById("findResults");
  ok(kbFR.style.display === "block", "F3: Find dropdown not open for the keyboard test");
  find.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
  const opt0 = kbFR.querySelector(".fitem[data-find]");
  ok(!!opt0 && opt0.getAttribute("aria-selected") === "true", "F3: ArrowDown did not mark the first option aria-selected");
  ok(!!opt0.id && find.getAttribute("aria-activedescendant") === opt0.id,
    "F3: input aria-activedescendant does not point at the highlighted option");
  const drawer = doc.getElementById("drawer");
  find.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  ok(kbFR.style.display === "none", "F3: Enter did not close the Find dropdown");
  ok(drawer.classList.contains("open") && /A1/.test(drawer.innerHTML),
    "F3: Enter did not open station A1 (same activation path as a click)");
  drawer.classList.remove("open");   // reset so a later section can re-open the drawer non-vacuously
  find.value = "Alpha"; fire(find, "input");
  ok(doc.getElementById("findResults").style.display === "block", "F3: dropdown should be open before Esc");
  find.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  ok(find.value === "" && doc.getElementById("findResults").style.display === "none",
    "F3: Esc did not clear the query and close the dropdown");
  // find.value is now "" and refresh() has re-run, so later sections (year/Availability/etc) assume no active Find query

  // F. SURVEY route: #/survey/<slug> (the route the published /surveys/<slug> path URLs 301 into
  //    at the front door - path-URL contract 2026-08-18; the sitemap advertises the path form) must
  //    resolve the slug back to its survey label and open the survey story drawer (openSurvey), same as
  //    clicking a "Survey story" button does. Before this route existed, routeFromHash() silently fell
  //    through for #/survey/... (only #/collection/ and #/station/ were handled) — a sitemap deep-link
  //    landed on a blank/default view instead of the intended survey.
  win.location.hash = "#/survey/alpha"; A.routeFromHash();
  ok(doc.getElementById("drawer").classList.contains("open"), "#/survey/<slug> did not open the drawer");
  ok(/Alpha Survey/.test(doc.getElementById("drawer").innerHTML), "survey route opened the wrong (or no) survey");
  // Unknown slug: must not crash and must not leave a stale drawer open from the previous assertion.
  doc.getElementById("drawer").classList.remove("open");
  win.location.hash = "#/survey/does-not-exist"; A.routeFromHash();
  ok(!doc.getElementById("drawer").classList.contains("open"), "unknown survey slug must not open the drawer");

  // F1b. THE PLURAL ROUTES: #/surveys and #/collections (index-pages lane). Every entity page's
  //      back-navigation and the 404 page's own recovery link pointed at #/surveys, and
  //      routeFromHash matched none of its three branches for it: the hash fell through and the
  //      reader stayed on whatever view was showing, which on a cold load is the Map. Those links
  //      now target the served /surveys and /collections index pages, but the hash form is out in
  //      the wild in published HTML, so the routes must land where their names promise.
  A.setView("map");
  win.location.hash = "#/surveys"; A.routeFromHash();
  ok(A.curView() === "surveys", "#/surveys must land on the Surveys view, got: " + A.curView());
  win.location.hash = "#/collections"; A.routeFromHash();
  ok(A.curView() === "collections", "#/collections must land on the Collections view, got: " + A.curView());
  // The singular entity routes share a prefix with the plural ones, so prove neither swallows the other.
  A.setView("map");
  win.location.hash = "#/survey/alpha"; A.routeFromHash();
  ok(doc.getElementById("drawer").classList.contains("open"),
    "the plural route must not shadow #/survey/<slug>");
  A.closeDrawer();

  // F1c. THE SURVEY ROUTE FRAMES THE MAP. The entity page's button is labelled "View all stations on
  //      the main map" and targets this route, but openSurvey never called setView or fitBounds and
  //      routeFromHash's setView("map") was on the STATION branch only: the reader got a drawer over
  //      whatever view was showing, with the map at its default national extent. The route now
  //      delivers the framing its label promises, through focusSurvey - the same seam the drawer's
  //      own "View on map" control uses, so the Option-A dim comes with it (F3 pins that behaviour).
  A.setView("surveys");
  const _fbBeforeRoute = mapCalls.filter(c => c.fn === "fitBounds").length;
  win.location.hash = "#/survey/alpha"; A.routeFromHash();
  ok(A.curView() === "map", "#/survey/<slug> must frame the MAP, got: " + A.curView());
  ok(doc.getElementById("drawer").classList.contains("open"),
    "#/survey/<slug> must still open the survey drawer");
  ok(mapCalls.filter(c => c.fn === "fitBounds").length === _fbBeforeRoute + 1,
    "#/survey/<slug> must fit the survey's own extent exactly once, got "
      + (mapCalls.filter(c => c.fn === "fitBounds").length - _fbBeforeRoute));
  ok(A.dimFocus() === "Alpha Survey",
    "#/survey/<slug> must apply the Option-A focus dim, got: " + JSON.stringify(A.dimFocus()));
  A.closeDrawer();

  // F2. SURVEY-DRAWER HASH CLEANUP (survey-drawer lane, ruling 5). closeDrawer() cleared ONLY
  //     "#/station..." - a survey opened by the #/survey/<slug> route left that hash in the address bar
  //     after the drawer shut, so the URL claimed a survey was open when nothing was, Back/reload
  //     re-opened a drawer the reader had deliberately closed, and copying the URL shared a state the
  //     page was not in. RED-proven before the fix: this leg failed on the pre-fix closeDrawer.
  //     The STATION behaviour is asserted alongside it so the fix cannot regress the path it mirrors.
  win.location.hash = "#/survey/alpha"; A.routeFromHash();
  ok(doc.getElementById("drawer").classList.contains("open"), "F2 setup: #/survey/alpha did not open the drawer");
  A.closeDrawer();
  ok(win.location.hash === "", "F2: closing the survey drawer must CLEAR the #/survey/<slug> hash back to the plain root, got: " + JSON.stringify(win.location.hash));
  // The station path already cleaned up; it must still.
  win.location.hash = "#/station/au.alpha.A1"; A.routeFromHash();
  ok(doc.getElementById("drawer").classList.contains("open"), "F2 setup: #/station route did not open the drawer");
  A.closeDrawer();
  ok(win.location.hash === "", "F2: the station hash cleanup must be PRESERVED, got: " + JSON.stringify(win.location.hash));

  // F3. SURVEY-DRAWER LANE: "View on map" - FIT PADDING + OPTION-A DIM (ruling 2).
  //     HONESTY NOTE, and it is the important part of this block: Leaflet is STUBBED in this harness
  //     (win.L = stub()), so nothing here exercises Leaflet's real projection, hit-testing or pointer
  //     capture. What IS proven: the ARGUMENTS the app hands the map (mapCalls records fitBounds with its
  //     real options object), and the PURE decision functions. The rendered dim and the real
  //     background-vs-marker pointer semantics are only exercised in a browser.
  // (a) the fit is padded on the RIGHT by the drawer's width, so the extent lands in the map area the
  //     drawer does not cover. Pre-change focusSurvey called fitBounds with NO options at all.
  win.location.hash = "#/survey/alpha"; A.routeFromHash();
  const _fbBeforeFocus = mapCalls.filter(c => c.fn === "fitBounds").length;
  // jsdom lays nothing out, so give the drawer a measurable width the way a real browser would.
  const _focusDrawerEl = doc.getElementById("drawer");
  _focusDrawerEl.getBoundingClientRect = () => ({ width: 420, height: 800, top: 0, left: 860, right: 1280, bottom: 800 });
  ok(A.drawerFitOptions().paddingBottomRight[0] === 420,
    "ruling 2: the fit padding must equal the drawer's MEASURED width (it is user-resizable), got: " + JSON.stringify(A.drawerFitOptions()));
  A.focusSurvey("Alpha Survey");
  const _fits = mapCalls.filter(c => c.fn === "fitBounds");
  ok(_fits.length === _fbBeforeFocus + 1, "ruling 2: View on map must fit the survey extent exactly once");
  const _fitOpts = _fits[_fits.length - 1].args[1];
  ok(_fitOpts && Array.isArray(_fitOpts.paddingBottomRight) && _fitOpts.paddingBottomRight[0] === 420,
    "ruling 2: fitBounds must be padded right by the drawer width, got: " + JSON.stringify(_fitOpts));
  ok(_fitOpts.paddingBottomRight[1] === 0 && _fitOpts.paddingTopLeft[0] === 0,
    "ruling 2: only the RIGHT edge is padded (the drawer covers no other edge), got: " + JSON.stringify(_fitOpts));
  // (b) OPTION A: other surveys stay VISIBLE but dimmed. The rejected behaviour filtered them off the map,
  //     so the strongest pin is that the visible station set is UNCHANGED by focusing one survey.
  ok(A.visIds().length === 5,
    "ruling 2 (Option A): focusing a survey must NOT remove other surveys from the map, got " + A.visIds().length);
  ok(A.dimFocus() === "Alpha Survey", "ruling 2: focusing must record the focused survey, got: " + JSON.stringify(A.dimFocus()));
  // the PURE dim decision: the focused survey full strength, everything else dimmed but non-zero (visible).
  const _onSty = A.dimStyleFor("Alpha Survey", "Alpha Survey"), _offSty = A.dimStyleFor("Beta Survey", "Alpha Survey");
  ok(_onSty.fillOpacity > _offSty.fillOpacity, "ruling 2: a non-focused survey must be DIMMER than the focused one");
  ok(_offSty.fillOpacity > 0, "ruling 2 (Option A): a non-focused survey must stay VISIBLE, not hidden (opacity > 0)");
  const _noFocus = A.dimStyleFor("Beta Survey", null);
  ok(_noFocus.fillOpacity === _onSty.fillOpacity, "ruling 2: with no focus every survey renders at full strength");
  // (c) the dim LIFTS on close, with no layer reload (closeDrawer only restores opacities).
  A.closeDrawer();
  ok(A.dimFocus() === null, "ruling 2: closing the drawer must clear the survey focus dim");
  ok(A.visIds().length === 5, "ruling 2: clearing the dim must not disturb the visible set");
  // (d) the background-click RULE (ruling 5). Only the pure predicate is provable here: whether a click
  //     actually REACHES it is Leaflet hit-testing, which the stub does not implement.
  ok(A.bgClickShouldClose(true, null) === true, "ruling 5: a background click with the drawer open must close it");
  ok(A.bgClickShouldClose(false, null) === false, "ruling 5: a background click with no drawer open is a no-op");
  ok(A.bgClickShouldClose(true, "rectangle") === false,
    "ruling 5: a background click while a draw is ARMED is placing a corner, not dismissing the drawer");

  // F4. DOTS ONLY AT EVERY ZOOM (owner, 2026-08-24). Site locations, never a survey object standing in
  //     front of them. Driven at NATIONAL zoom (curZoom falls back to 4 here) over the compact-survey
  //     fixture with the AusLAMP privilege lifted, which is the state that USED to collapse Alpha into a
  //     badge: without that setup the pin would pass against zero badges and prove nothing.
  A.closeDrawer();
  A.setSidebarMode("browse"); A.setAuslampSet([]); A.refresh();
  // Mark rather than clear: F5 below asserts the no-named-pane invariant over EVERY layer the boot added,
  // so the whole-run record has to survive this leg. The slice is this pass's share of it.
  const _routeMark = layersAdded.length;
  const _dots = A.routeVisibleToLayers();
  const _added = layersAdded.slice(_routeMark).filter(l => l.kind !== "layerGroup");
  ok(!("badges" in _dots),
    "dots only: the paint pass must not carry a badge arm at all, got " + JSON.stringify(Object.keys(_dots)));
  ok(_dots.dots.length === A.visIds().length,
    "dots only: every filtered station must be its own dot at national zoom, got " +
    _dots.dots.length + " of " + A.visIds().length);
  // WHAT REACHED THE MAP, not just what the router decided. A badge is an L.marker (divIcon) and a leader
  // is an L.polyline; a station dot is an L.circleMarker. So the layer kinds ARE the claim.
  ok(_added.every(l => l.kind === "circleMarker"),
    "dots only: nothing but station dots may reach the map on a routing pass, got " +
    JSON.stringify(_added.map(l => l.kind)));
  ok(_added.length === A.visIds().length,
    "dots only: the painted dot count must equal the filtered station count, got " +
    _added.length + " of " + A.visIds().length);
  // The legend must stop advertising an object the map no longer draws.
  const _legDots = doc.getElementById("mapLegend");
  ok(_legDots && !_legDots.querySelector(".legbadge"),
    "dots only: the legend must carry no survey-badge row");
  ok(_legDots && !/zoom to expand/i.test(_legDots.textContent),
    "dots only: the legend must not promise that anything expands on zoom, got " +
    JSON.stringify(_legDots && _legDots.textContent));

  // F5. A STATION CLICK OPENS THAT STATION, AND NOTHING SITS OVER THE STATION LAYER.
  //     (production regression, 2026-08-19: no station on the deployed portal could be opened. CAUSE: the
  //     per-survey badge panes sat at z 600 over the station canvas at z 400, and adding an L.Path to a
  //     pane makes Leaflet build a full-map-size canvas inside it, which swallowed every click.)
  //
  //     The badges, their panes and the pane guard are gone with the 2026-08-24 ruling, so the invariant is
  //     now STRUCTURAL rather than guarded: no pane is created, and no layer is routed into one. Both halves
  //     are asserted, because "the guard was deleted" is only safe while the panes really are absent.
  //     SCOPE, so the wording matches what is actually observed: panesMade holds every map.createPane call
  //     of the run, and layersAdded every layer the recorded factories produced and the app added (map.js's
  //     circleMarkers, markers, polylines and layer groups). Neither is ever cleared, so a leader tail put
  //     into a pane at BOOT is caught here, not just the dots the F4 pass had painted a moment earlier.
  //
  //     WHAT THIS CANNOT PROVE, and what only a real browser can: that a pointer event reaches the station
  //     layer. jsdom has no compositor, no canvas hit-testing and no pane stacking - the click leg below
  //     INVOKES a recorded handler, it does not dispatch a pointer at a pixel.
  ok(Object.keys(panesMade).length === 0,
    "F5: no module may create a Leaflet pane over this whole boot. Any pane is stacked over the station " +
    "canvas and is the exact shape of the 2026-08-19 outage. Got " + JSON.stringify(Object.keys(panesMade)));
  ok(layersAdded.every(l => !(l.options && l.options.pane)),
    "F5: no layer added over this whole boot may be routed into a named pane, got " +
    JSON.stringify(layersAdded.filter(l => l.options && l.options.pane).map(l => l.kind + ":" + l.options.pane)));
  A.closeDrawer();
  win.location.hash = "";
  const _f5dot = _dots.dots.find(s => s.id === "B1") || _dots.dots[0];
  const _f5mk = A.stationMarker(_f5dot.id);
  ok(_f5mk && _f5mk.handlers && (_f5mk.handlers.click || []).length === 1,
    "F5: a station marker must carry exactly one bound click handler, got " +
    ((_f5mk && _f5mk.handlers && (_f5mk.handlers.click || []).length) + ""));
  ok(_f5mk.options && _f5mk.options.pane === undefined,
    "F5: a station marker must stay in Leaflet's DEFAULT overlay pane. The whole outage was decoration " +
    "panes stacked over that layer, so a station that moved INTO one would be unreachable by construction.");
  _f5mk.handlers.click[0]({});
  ok(doc.getElementById("drawer").classList.contains("open"),
    "F5: a station marker click must open the station drawer");
  ok(/#\/station\//.test(win.location.hash),
    "F5: a station marker click must leave the station route in the URL, got " + JSON.stringify(win.location.hash));
  ok(doc.getElementById("drawer").innerHTML.indexOf(_f5dot.id) >= 0,
    "F5: the drawer must show the station that was clicked (" + _f5dot.id + ")");
  A.closeDrawer();

  A.buildAuslampSet(); A.refresh();       // restore the boot-built membership for the rest of the run

  // G. WELCOME POPUP (UX7b U7): on first visit a small CENTRED MODAL (#introWelcome) shows — successor to
  // the Wave D corner strip (which is GONE). role=dialog, focus-managed; "Take the 2-minute tour" starts
  // the tour, "Browse immediately" closes, and a "Don't show this again" checkbox GATES persistence.
  const introWelcome = doc.getElementById("introWelcome");
  ok(introWelcome, "#introWelcome (first-visit welcome popup) missing from index.html");
  ok(!doc.getElementById("introStrip"), "the Wave D corner strip (#introStrip) must be REMOVED — the welcome popup is its successor");
  // U7 dialog semantics: role=dialog + aria-modal, and the three required elements exist.
  ok(introWelcome.getAttribute("role") === "dialog", "the welcome popup must be role=dialog, got: " + JSON.stringify(introWelcome.getAttribute("role")));
  ok(doc.getElementById("welcomeTour") && doc.getElementById("welcomeBrowse") && doc.getElementById("welcomeDismiss"),
    "the welcome popup must offer the tour button, the browse button and the 'Don't show this again' checkbox");
  ok(doc.getElementById("welcomeDismiss").type === "checkbox", "'Don't show this again' must be a checkbox");
  // U7 verbatim copy.
  ok(doc.getElementById("introWelcomeHeading").textContent.trim() === "Welcome to AusMT",
    "welcome heading copy wrong, got: " + JSON.stringify(doc.getElementById("introWelcomeHeading").textContent));
  ok(doc.getElementById("introWelcomeText").textContent.trim() === "Explore Australia's national magnetotelluric data portal",
    "welcome body copy wrong, got: " + JSON.stringify(doc.getElementById("introWelcomeText").textContent));
  // DOCS WAVE STAGE 2: the "How AusMT works" panel (#introOverlay) and its three tiles are RETIRED along
  // with the header item that opened them. Nothing on the page may carry those ids or classes any more:
  // an orphaned panel is dead markup a reader can never reach, and a surviving tile id would mean the
  // header button was removed without its panel. Guards the removal from both ends (markup and styles).
  ["introOverlay", "introPanel", "introClose", "introTakeTour", "tileBrowse", "tileContribute", "tileIntegrate", "howToUse"]
    .forEach(id => ok(!doc.getElementById(id), "docs wave: #" + id + " belongs to the retired 'How AusMT works' panel and must be gone"));
  ["introoverlay", "intropanel", "introtile", "introhero", "introclose", "introtour"]
    .forEach(cls => ok(!doc.querySelector("." + cls), "docs wave: ." + cls + " markup must be gone with the retired panel"));
  // Comments stripped first (HTML and CSS): the stylesheet carries a comment naming the retired classes
  // so the next reader knows what went and why, and a scan that forbids that comment loses the reason.
  const _htmlNoComments = html.replace(/<!--[\s\S]*?-->/g, "").replace(/\/\*[\s\S]*?\*\//g, "");
  ok(!/\.introoverlay|\.intropanel|\.introtile|\.introhero|\.introclose|\.introtour/.test(_htmlNoComments),
    "docs wave: index.html must not keep CSS rules for the retired intro panel");
  // FIRST VISIT: simulate it (clear the key + re-run the first-visit show the way runInit() does).
  win.localStorage.removeItem("ausmt_intro_dismissed");
  A.showWelcome();
  ok(!introWelcome.classList.contains("hidden"), "welcome popup did not show on first visit");
  // FOCUS MANAGEMENT (U7): showing the popup moves focus INTO the dialog.
  ok(introWelcome.contains(doc.activeElement), "showing the welcome popup must move focus into the dialog, active=" + (doc.activeElement && doc.activeElement.id));

  // G1. CHECKBOX PERSISTENCE MATRIX (U7): dismiss ticked/unticked × close-via {tour, browse, Esc, click-out}.
  // Ticked -> the dismissal PERSISTS (localStorage key set) on every close path; unticked -> it does NOT
  // (the popup may return next visit). Load-bearing: on OLD code there is no such popup at all.
  function welcomeCase(ticked, via) {
    win.localStorage.removeItem("ausmt_intro_dismissed");
    A.showWelcome();
    ok(!introWelcome.classList.contains("hidden"), "matrix setup: popup not shown for " + via + "/" + ticked);
    doc.getElementById("welcomeDismiss").checked = ticked;
    if (via === "tour") doc.getElementById("welcomeTour").click();
    else if (via === "browse") doc.getElementById("welcomeBrowse").click();
    else if (via === "esc") win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape" }));
    else if (via === "clickout") introWelcome.dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
    ok(introWelcome.classList.contains("hidden"), "close-via-" + via + " did not close the welcome popup");
    const persisted = win.localStorage.getItem("ausmt_intro_dismissed") === "1";
    ok(persisted === ticked,
      "checkbox matrix FAILED: dismiss=" + ticked + " via " + via + " -> persisted should be " + ticked + ", got " + persisted);
    if (A.tourStep() >= 0) win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape" }));  // close a tour the 'tour' path opened
    doc.getElementById("welcomeDismiss").checked = false;                                                   // reset for the next case
  }
  ["tour", "browse", "esc", "clickout"].forEach(via => { welcomeCase(true, via); welcomeCase(false, via); });

  // G2. TAKING THE TOUR from the popup actually STARTS it and closes the popup.
  win.localStorage.removeItem("ausmt_intro_dismissed");
  A.showWelcome();
  doc.getElementById("welcomeTour").click();
  ok(A.tourStep() === 0, "welcome popup 'Take the tour' did not start the tour, at step " + A.tourStep());
  ok(introWelcome.classList.contains("hidden"), "welcome popup 'Take the tour' did not close the popup");
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape" }));                          // close the tour cleanly
  ok(A.tourStep() === -1, "could not close the tour started from the welcome popup");

  // G3. DOCS WAVE STAGE 2: retiring the header help entry took the on-demand tour button with it, so the
  // replacement pathway is About's link, index.html?tour=1. Boot a window at that URL and assert the tour
  // starts by itself with NO welcome popup. Load-bearing in both directions: the seen flag is SET first,
  // so this also proves the query parameter is not swallowed by a returning visitor's dismissal (the exact
  // person who follows a "start the guided tour" link months later).
  const tourWin = await bootFreshWindow(DATAMAP, "http://localhost/index.html?tour=1");
  ok(tourWin.__api.tourStep() === 0, "?tour=1 must start the tour on load, at step " + tourWin.__api.tourStep());
  ok(tourWin.document.getElementById("introWelcome").classList.contains("hidden"),
    "?tour=1 must go straight to the tour and show no welcome popup");
  ok(!/tour=1/.test(tourWin.location.search),
    "?tour=1 must be dropped from the address bar once the tour is running, so a reload browses instead " +
    "of replaying the tour; search is still " + JSON.stringify(tourWin.location.search));
  tourWin.document.dispatchEvent(new tourWin.KeyboardEvent("keydown", { key: "Escape" }));
  ok(tourWin.__api.tourStep() === -1, "could not close the tour the ?tour=1 boot opened");
  // Same window, now marked as a visitor who ticked "don't show this again": the parameter must still win.
  // The boot above stripped it, so put it back the way a fresh navigation would present it.
  tourWin.localStorage.setItem("ausmt_intro_dismissed", "1");
  tourWin.history.replaceState(null, "", "/index.html?tour=1");
  ok(tourWin.__api.introSeen() === true, "matrix setup: the dismissal flag did not take");
  tourWin.__api.maybeShowIntro();
  ok(tourWin.__api.tourStep() === 0, "?tour=1 must still start the tour for a visitor who dismissed the popup");
  ok(tourWin.document.getElementById("introWelcome").classList.contains("hidden"),
    "?tour=1 must not raise the welcome popup for a returning visitor either");
  tourWin.document.dispatchEvent(new tourWin.KeyboardEvent("keydown", { key: "Escape" }));
  // A plain boot (no query) keeps the first-visit rule: popup, no tour.
  const plainWin = await bootFreshWindow(DATAMAP);
  ok(plainWin.__api.tourStep() === -1, "a plain boot must NOT auto-start the tour, at " + plainWin.__api.tourStep());
  ok(!plainWin.document.getElementById("introWelcome").classList.contains("hidden"),
    "a plain first-visit boot must still show the welcome popup");
  // G3b. THE RAIL MUST BE VISIBLE FOR THE RAIL STEPS (section-4 review, P1). The tour manages rail MODE
  // but used to leave a COLLAPSED rail collapsed, and `.collapsed > *:not(.railcollapse)` is
  // display:none - so exactly the visitor who collapsed the rail months ago and then follows About's
  // ?tour=1 link got steps 3/4/6/7 as empty centred cards, narrating controls that were not on screen.
  // The tour expands it for the run and restores the visitor's own choice on close, the same
  // save-and-restore discipline the rail MODE and the Find/tree demos already follow.
  const collWin = await bootFreshWindow(DATAMAP, "http://localhost/index.html?tour=1", w => {
    w.localStorage.setItem("ausmt_sidebar_collapsed", "1");
  });
  const collRail = collWin.document.querySelector("aside.filters");
  ok(collWin.__api.tourStep() === 0, "matrix setup: ?tour=1 did not start the tour on the collapsed-rail boot");
  ok(!collRail.classList.contains("collapsed"),
    "the tour must expand a collapsed rail: its rail steps spotlight controls that a collapsed rail hides");
  collWin.document.dispatchEvent(new collWin.KeyboardEvent("keydown", { key: "Escape" }));
  ok(collRail.classList.contains("collapsed"),
    "closing the tour must put the visitor's collapsed rail back: the tour restores only what it changed");
  ok(collWin.localStorage.getItem("ausmt_sidebar_collapsed") === "1",
    "the restored collapse state must persist too, so the next visit still opens the way the visitor left it");
  // A visitor whose rail was already EXPANDED must be left expanded (no phantom restore to collapsed).
  const openWin = await bootFreshWindow(DATAMAP, "http://localhost/index.html?tour=1");
  const openRail = openWin.document.querySelector("aside.filters");
  ok(!openRail.classList.contains("collapsed"), "matrix setup: this boot should start with an expanded rail");
  openWin.document.dispatchEvent(new openWin.KeyboardEvent("keydown", { key: "Escape" }));
  ok(!openRail.classList.contains("collapsed"),
    "the tour must not collapse a rail the visitor had open: restore puts back what WAS, not a default");

  win.localStorage.removeItem("ausmt_intro_dismissed");                                                     // clean state for the tour sections

  // G4. TOUR REDESIGN (UX9 owner): CENTRED card + LEADER to the spotlight. The side-picking _tourPlace is
  // retired; the card is centred for EVERY step and a leader line/arrow connects it to the spotlight. The
  // geometry is PURE (_tourCardBox / _tourLeader) because jsdom has NO layout engine (every
  // getBoundingClientRect is zero) — so the centred-always, overlap-nudge, leader-endpoint and map-step
  // suppression coverage runs on SYNTHETIC rects, the same pattern as partitionMarkers()/radiusForZoom().
  // The DOM checks below then pin the leader element, the copper Next class and the applied dim.
  const M = 8, CLEAR = 16, cardW = 340, cardH = 160, vpW = 1200, vpH = 800;
  const cx0 = Math.round((vpW - cardW) / 2), cy0 = Math.round((vpH - cardH) / 2);
  // CENTRED-ALWAYS: no target -> exactly viewport-centred, not nudged.
  let b = A.tourCardBox(cardW, cardH, vpW, vpH, null);
  ok(b.left === cx0 && b.top === cy0, "UX9: the card must be viewport-centred with no target, got " + JSON.stringify(b));
  ok(b.nudged === false, "UX9: a no-target card must not be nudged");
  // A target that does NOT overlap the centred card leaves it centred.
  b = A.tourCardBox(cardW, cardH, vpW, vpH, { left: 20, top: 20, right: 90, bottom: 60 });
  ok(b.left === cx0 && b.top === cy0 && b.nudged === false, "UX9: a non-overlapping target must leave the card centred, got " + JSON.stringify(b));
  // OVERLAP RULE (downward): a target under the centred card nudges it DOWN to target.bottom+16, horizontal
  // stays centred, and it clears the target by >=16 (no residual overlap).
  const tgtMid = { left: 500, top: 300, right: 700, bottom: 420 };
  b = A.tourCardBox(cardW, cardH, vpW, vpH, tgtMid);
  ok(b.nudged === true, "UX9: a target overlapping the centred card must nudge it");
  ok(b.top === tgtMid.bottom + CLEAR, "UX9: overlap nudge must move the card DOWN to target.bottom+16, got " + b.top);
  ok(b.left === cx0, "UX9: the overlap nudge is vertical only — horizontal stays centred, got left=" + b.left);
  ok(b.top >= tgtMid.bottom + CLEAR - 0.001, "UX9: nudged card must clear the target by 16px");
  // OVERLAP RULE (upward fallback): a tall target for which downward would overflow the viewport nudges UP
  // to target.top-16-cardH instead.
  const tgtTall = { left: 500, top: 340, right: 700, bottom: 700 };
  b = A.tourCardBox(cardW, cardH, vpW, vpH, tgtTall);
  ok(b.nudged === true && b.top === tgtTall.top - CLEAR - cardH,
    "UX9: when downward won't fit, nudge UP to target.top-16-cardH, got top=" + b.top);
  ok(b.bottom <= tgtTall.top - CLEAR + 0.001, "UX9: upward-nudged card must clear the target top by 16px");

  // LEADER GEOMETRY: for a centred card and an off-card spotlight, the endpoints lie ON each rect's boundary
  // and on the card-centre<->spot-centre axis (so the line leaves the card edge nearest the target and lands
  // on the spot edge nearest the card).
  const cCard = { left: cx0, top: cy0, right: cx0 + cardW, bottom: cy0 + cardH };
  const cSpot = { left: 900, top: 100, right: 1000, bottom: 200 };
  const ld = A.tourLeader(cCard, cSpot, false);
  ok(ld.visible === true, "UX9: the leader must be visible for a normal targeted step");
  const onEdge = (x, y, r) => (Math.abs(x - r.left) < 1e-6 || Math.abs(x - r.right) < 1e-6 || Math.abs(y - r.top) < 1e-6 || Math.abs(y - r.bottom) < 1e-6)
    && x >= r.left - 1e-6 && x <= r.right + 1e-6 && y >= r.top - 1e-6 && y <= r.bottom + 1e-6;
  ok(onEdge(ld.x1, ld.y1, cCard), "UX9: the leader must start ON the card boundary, got (" + ld.x1 + "," + ld.y1 + ")");
  ok(onEdge(ld.x2, ld.y2, cSpot), "UX9: the leader must end ON the spot boundary, got (" + ld.x2 + "," + ld.y2 + ")");
  const ccx = (cCard.left + cCard.right) / 2, ccy = (cCard.top + cCard.bottom) / 2;
  const scx = (cSpot.left + cSpot.right) / 2, scy = (cSpot.top + cSpot.bottom) / 2, ax = scx - ccx, ay = scy - ccy;
  const colin = (x, y) => Math.abs(ax * (y - ccy) - ay * (x - ccx)) < 1e-6;
  ok(colin(ld.x1, ld.y1) && colin(ld.x2, ld.y2), "UX9: both leader endpoints must lie on the card-centre<->spot-centre axis");
  // MAP-STEP SUPPRESSION: the same rects, but suppressed (as _tourLayout passes for sel '#map' — TOUR_STEPS
  // 0 and 9 — and for the no-target fallback) -> the leader is not drawn.
  ok(A.tourLeader(cCard, cSpot, true).visible === false, "UX9: the leader must be suppressed (visible:false) on map steps / no-target");

  // DOM: open the tour and pin the leader element, the copper Next button and the raised dim. In jsdom every
  // rect is zero, so step 0 takes the no-target branch: the leader hides, the card is centred, and the
  // backdrop carries the dim (0.78, up from the old 0.65).
  doc.getElementById("welcomeTour").click();
  ok(doc.getElementById("tourLeader"), "UX9: the tour must build a leader overlay element (#tourLeader)");
  ok(doc.getElementById("tourLeaderLine"), "UX9: the leader overlay must contain the line element (#tourLeaderLine)");
  ok(!doc.getElementById("tourArrow"), "UX9: the retired caret element (#tourArrow) must be gone");
  const tCard = doc.getElementById("tourCard");
  ok(/px$/.test(tCard.style.left) && /px$/.test(tCard.style.top), "UX9: the centred card must be positioned in px, got left=" + JSON.stringify(tCard.style.left));
  ok(doc.getElementById("tourLeader").style.display === "none", "UX9: the leader must be hidden on the no-target step 0 (jsdom rects are zero)");
  const tNext = doc.getElementById("tourNext");
  ok(tNext.classList.contains("tourprimary"), "U9: the tour Next button must carry the copper .tourprimary class");
  ok(A.tourDim() === 0.78, "U10: overlay dim must be 0.78, got " + A.tourDim());
  ok(A.tourDim() >= 0.65 + 0.10 && A.tourDim() <= 0.65 + 0.15, "U10: overlay dim must be +10..15pp over the old 0.65, got " + A.tourDim());
  const tBack = doc.getElementById("tourBackdrop");
  ok(/0\.78/.test(tBack.style.background) && !/0?\.65/.test(tBack.style.background),
    "U10: the centred (no-target) backdrop must apply the 0.78 dim, got: " + JSON.stringify(tBack.style.background));

  // G4b. OWNER ROUND 2 (2026-07-22): the card must be a CONSTANT SIZE and CONSTANT centred position on EVERY
  // step — steps 1/10 (the map steps) sat differently from 2-9 and steps 7/9 (short copy) rendered a smaller
  // box. FIXED SIZE: .tourcard carries an explicit width (not max-width) + a min-height sized to the tallest
  // step, box-sizing:border-box — so offsetWidth/offsetHeight are constant and short-text steps can no longer
  // shrink. jsdom resolves declared class CSS via getComputedStyle (no layout engine needed), so these pin the
  // CSS contract directly and RED-PROVE against the pre-change max-width/auto-height rule (width would be "").
  const _tcs = win.getComputedStyle(tCard);
  ok(_tcs.width === "340px", "owner2/size: .tourcard must have a FIXED width:340px (not max-width), got width=" + JSON.stringify(_tcs.width));
  ok(/^\d+px$/.test(_tcs.minHeight) && parseInt(_tcs.minHeight, 10) > 0,
    "owner2/size: .tourcard must have a positive min-height (constant box; short steps 7/9 must not shrink), got minHeight=" + JSON.stringify(_tcs.minHeight));
  ok(_tcs.boxSizing === "border-box", "owner2/size: .tourcard must be border-box so the fixed width is the full rendered box, got " + JSON.stringify(_tcs.boxSizing));
  // CONSTANT CENTRED POSITION: step through ALL 10 steps and capture the card's applied left/top. Every step's
  // position must be IDENTICAL (the map steps included) — the overlap-nudge is the ONLY documented exception,
  // and under jsdom's zero rects no target overlaps, so all 10 land on the pure viewport centre. This guards
  // the "same position on every step" contract the owner asked for (map steps 1/10 must match 2-9).
  const _posSeen = [];
  for (let _s = 0; _s < 10; _s++) {
    const _c = doc.getElementById("tourCard");
    _posSeen.push(_c.style.left + "|" + _c.style.top);
    if (_s < 10) win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowRight" }));
  }
  ok(A.tourStep() === 10, "owner2/pos: stepping ArrowRight x10 must reach the last step, at " + A.tourStep());
  ok(_posSeen.every(p => p === _posSeen[0]),
    "owner2/pos: the card's centred position must be IDENTICAL across all 10 steps (map steps included), got " + JSON.stringify(_posSeen));
  ok(/px$/.test(_posSeen[0].split("|")[0]) && /px$/.test(_posSeen[0].split("|")[1]),
    "owner2/pos: the constant position must be applied in px, got " + JSON.stringify(_posSeen[0]));

  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape" }));
  ok(A.tourStep() === -1, "G4: could not close the tour after the positioning checks");

  // H0. NO HELP BUTTON IN THE HEADER. #headerTour went in UX feedback round 3; #howToUse went in the docs
  // wave with the panel it opened. The header is now five items and carries no tour or help control at
  // all. Both ids are pinned absent so neither can quietly return.
  ok(!doc.getElementById("headerTour"), "#headerTour should have been removed from the header (item 2)");
  ok(!doc.getElementById("howToUse"), "#howToUse was retired with the 'How AusMT works' panel (docs wave)");
  ok(doc.getElementById("welcomeTour"), "#welcomeTour (the welcome popup's tour button) is missing");

  // H0b. NO AuScope ORG-MARK IN THE SPA HEADER. The mark closed the right zone on every surface until
  // the owner moved the relationship to the two places that state it in words: the footer, on every
  // page, and About's "Who enables AusMT" section. Asserted against the REAL index.html DOM rather
  // than its source text, so a mark restored under different markup is caught by the slot it lands in
  // and not only by the literal it was written as. The right zone itself must survive: it carries the
  // contextual status slot, and a header with two zones re-floats the centre tab group.
  const _hdr = doc.querySelector("header");
  ok(_hdr, "H0b: index.html must carry the site header");
  ok(_hdr.querySelectorAll(".orgmark").length === 0,
    "H0b: the AuScope org-mark is withdrawn from every header; found " + _hdr.querySelectorAll(".orgmark").length);
  ok([..._hdr.querySelectorAll("img")].every(i => (i.getAttribute("src") || "").indexOf("auscope-icon") < 0),
    "H0b: no header image may name the AuScope icon: " +
    JSON.stringify([..._hdr.querySelectorAll("img")].map(i => i.getAttribute("src"))));
  ok([..._hdr.querySelectorAll("a")].every(a => (a.getAttribute("href") || "").indexOf("auscope.org.au") < 0),
    "H0b: the header carries no outbound AuScope anchor; the footer and About section 2 do");
  ok(_hdr.querySelector(".hright"), "H0b: the right zone stays; the mark left it, the zone did not");

  // H0c. THE MAP WATERMARK. The AuScope colour icon is the one place on the site the symbol survives,
  // and it is there for a reason the chrome could not give: the map is what people screenshot into
  // talks and reports, and a screenshot carries no footer. Driven off the REAL index.html DOM, so a
  // mark that moved out of the map container, grew a link around it or lost its alt text fails here
  // rather than in a source-literal pin that a re-indentation could break.
  const _mapEl = doc.getElementById("map");
  ok(_mapEl, "H0c: index.html must carry the Leaflet map container");
  const _marks = [..._mapEl.querySelectorAll("img.mapmark")];
  ok(_marks.length === 1,
    "H0c: the map must carry exactly one watermark inside its own container, found " + _marks.length);
  ok(_marks[0].getAttribute("src") === "/vendor/auscope-icon-colour.png",
    "H0c: the watermark must be the vendored AuScope colour icon, got " + JSON.stringify(_marks[0].getAttribute("src")));
  ok(_marks[0].getAttribute("alt") === "AuScope",
    "H0c: the watermark is attribution and must name the organisation in its alt text, got " +
    JSON.stringify(_marks[0].getAttribute("alt")));
  ok(!_marks[0].closest("a"),
    "H0c: the watermark must not be a link; the footer carries the link and a link here takes a tab " +
    "stop in the middle of the map");
  // The two properties that make it unable to intercept a zoom, a draw, a popup or the tour. Read
  // from the document's OWN stylesheet text and compared as numbers against Leaflet's, because
  // jsdom does not run a full cascade for these properties.
  const _sheet = [...doc.querySelectorAll("style")].map(s => s.textContent).join("\n");
  const _mapmarkRule = (_sheet.match(/\.mapmark\{[^}]*\}/) || [""])[0];
  ok(/pointer-events:\s*none/.test(_mapmarkRule),
    "H0c: the watermark must be out of hit testing entirely (pointer-events:none), got " + JSON.stringify(_mapmarkRule));
  const _mine = parseInt((_mapmarkRule.match(/z-index:\s*(\d+)/) || [0, "0"])[1], 10);
  const _leaflet = fs.readFileSync(path.join(PORTAL, "vendor", "leaflet.css"), "utf8");
  const _ctlZ = parseInt((_leaflet.match(/\.leaflet-control \{[^}]*?z-index: (\d+)/) || [0, "0"])[1], 10);
  const _popZ = parseInt((_leaflet.match(/\.leaflet-popup-pane\s*\{ z-index: (\d+); \}/) || [0, "0"])[1], 10);
  ok(_ctlZ > 0 && _popZ > 0, "H0c: could not read Leaflet's own control/popup z-indices to compare against");
  ok(_mine > 0 && _mine < _ctlZ && _mine < _popZ,
    "H0c: the watermark's z-index (" + _mine + ") must stay below Leaflet's control (" + _ctlZ +
    ") and popup (" + _popZ + ") layers");

  // H. TOUR v4 (UX rounds 1/2 + UX4 D5): 10 steps now. Opens from the welcome popup's "Take the 2-minute
  // tour" button (#welcomeTour), which is the only tour BUTTON left; index.html?tour=1 is the other entry
  // and is pinned in G3. Step 1 text matches the verbatim design copy, ArrowRight advances to step 2, Esc
  // closes and tears the tour DOM down.
  doc.getElementById("welcomeTour").click();
  ok(A.tourStep() === 0, "tour did not open to step 0 from the welcome popup's tour button");
  let tourText = doc.getElementById("tourText");
  ok(tourText, "#tourText not rendered by the tour");
  ok(tourText.textContent === "Every dot is an MT station. Click one to see its transfer function.",
    "tour step 1 text does not match the verbatim design copy, got: " + tourText.textContent);
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowRight" }));
  ok(A.tourStep() === 1, "ArrowRight did not advance the tour to step 2, at step " + A.tourStep());
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape" }));
  ok(A.tourStep() === -1, "Esc did not close the tour");
  ok(!doc.getElementById("tourCard"), "Esc did not remove the tour DOM");

  // H2. TOUR v4 DEMO STEPS (UX4 D5) + drawer enter action. New step layout: 0 map, 1 filters,
  // 2 FIND DEMO, 3 TREE BROWSE, 4 station drawer, ... Each demo step's EXIT hook must fire on ALL
  // three ways out — Next, Back and mid-tour close — leaving the find box and tree state as found.
  const findBox = doc.getElementById("find"), findRes = doc.getElementById("findResults");
  ok(doc.getElementById("drawer").classList.contains("open") === false, "drawer unexpectedly open before the tour restarts");
  ok(findBox.value === "", "find box not empty before the tour starts");
  doc.getElementById("welcomeTour").click();                           // step 1 (index 0)
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowRight" })); // -> index 1 (filters)
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowRight" })); // -> index 2: FIND DEMO
  ok(A.tourStep() === 2, "ArrowRight x2 did not reach the Find demo step, at step " + A.tourStep());
  // enter typed "AusLAMP" with a REAL input event: the live wiring must have filtered the map AND
  // rendered the dropdown with the actual AusLAMP collection match (fixture collection title "AusLAMP").
  ok(findBox.value === "AusLAMP", "Find demo did not type AusLAMP into the box, got: " + JSON.stringify(findBox.value));
  ok(findRes.style.display === "block", "Find demo did not render the live dropdown");
  ok([...findRes.querySelectorAll(".fitem")].some(it => it.dataset.find === "coll"),
    "Find demo dropdown is missing the real AusLAMP collection match");
  ok(A.nVisCount() === 0, "Find demo should live-filter the fixture map to 0 (no fixture station matches 'AusLAMP'), got " + A.nVisCount());
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowRight" })); // -> index 3: TREE BROWSE (find exit fires)
  ok(A.tourStep() === 3, "ArrowRight did not reach the tree-browse step, at step " + A.tourStep());
  ok(findBox.value === "", "leaving the Find demo FORWARD did not clear the typed query, got: " + JSON.stringify(findBox.value));
  ok(findRes.style.display === "none", "leaving the Find demo FORWARD did not close the dropdown");
  ok(A.nVisCount() === 5, "leaving the Find demo FORWARD did not restore the filtered map, got " + A.nVisCount());
  // graceful degrade (D5): kalkaroo-2022 is NOT in this fixture -> the resolved target must be the
  // FIRST survey present (surveys[] is sorted; "Alpha Survey"), and nothing crashed getting here.
  ok(A.tourTreeTarget() === "Alpha Survey",
    "tree-browse step must degrade to the first survey when kalkaroo-2022 is absent, got: " + JSON.stringify(A.tourTreeTarget()));
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowLeft" }));  // BACK -> index 2 (tree exit fires, find re-enters)
  ok(A.tourStep() === 2, "ArrowLeft did not return to the Find demo step, at step " + A.tourStep());
  ok(findBox.value === "AusLAMP", "re-entering the Find demo backwards did not re-type the query");
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape" }));     // MID-TOUR CLOSE from the demo step
  ok(A.tourStep() === -1, "Esc from the Find demo did not close the tour");
  ok(findBox.value === "", "mid-tour close did not clear the Find demo query, got: " + JSON.stringify(findBox.value));
  ok(findRes.style.display === "none", "mid-tour close did not close the Find dropdown");
  ok(A.nVisCount() === 5, "mid-tour close did not restore the filtered map, got " + A.nVisCount());
  ok(doc.getElementById("tree").scrollTop === 0, "tree scroll not back to its pre-tour position after close");
  // Drawer enter action (was index 2 pre-D5, now index 4): reaching it must open the first visible
  // station's drawer, and Esc from there must close it AND restore the map view.
  doc.getElementById("welcomeTour").click();                           // restart, index 0
  for (let k = 0; k < 4; k++) win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowRight" })); // -> index 4
  ok(A.tourStep() === 4, "ArrowRight x4 did not reach the station-drawer step, at step " + A.tourStep());
  ok(doc.getElementById("drawer").classList.contains("open"), "the station-drawer step did not open the drawer");
  ok(findBox.value === "", "passing THROUGH the Find demo left residue in the find box");

  // H2b. SETTLE-UNTIL-STABLE re-layout (owner 2026-07-22). The drawer step's target keeps reflowing AFTER open
  // — it SLIDES in (transform transition, ~160ms; the box MOVES left), then an ASYNC station.json fetch injects
  // the frame line and grows its HEIGHT, then a deferred map re-fit can nudge it again. A single transitionend
  // re-measure fires after the slide only and leaves the spotlight on a stale early box (the owner-observed
  // "highlight ends where the panel first appeared, now empty"). The tour now POLLS the target rect each frame,
  // re-runs _tourLayout on ANY change (position OR size — a size-only ResizeObserver misses the slide's MOVE),
  // and STOPS once the rect holds stable for a quiet window (or a hard cap). jsdom has no layout engine and its
  // rAF is parked in rafQ, so this pins the WIRING deterministically with a controllable clock + rect: a
  // changing box keeps re-running layout, a stable box stands the watcher down, and stepping away / closing
  // detaches it with no leaked frame or listener. The sub-second visual proof is the instrumented browser run.
  const _drawerEl = doc.getElementById("drawer");
  const _origPerfNow = win.performance.now, _origGBCR = _drawerEl.getBoundingClientRect;
  let _clock = 100000;                                     // controllable monotonic clock (ms); the watcher times via performance.now
  win.performance.now = () => _clock;
  let _dr = { left: 1260, top: 0, width: 420, height: 600, right: 1680, bottom: 600 };  // drawer OFF to the right (mid-slide)
  _drawerEl.getBoundingClientRect = () => ({ ..._dr, x: _dr.left, y: _dr.top });
  // Re-attach the watcher against the stubbed clock/rect: step off the drawer (-> tree) then back (-> drawer).
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowLeft" }));
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowRight" }));
  ok(A.tourStep() === 4, "settle: could not return to the drawer step, at " + A.tourStep());
  ok(A.tourSettleEl() === "drawer", "settle: the watcher must attach to #drawer on the drawer step, got " + JSON.stringify(A.tourSettleEl()));
  ok(A.tourSettling() === true, "settle: a poll frame must be pending right after attach");
  const _tick = rafQ[rafQ.length - 1];                     // the live poll frame (reschedules push the SAME fn to the tail)
  ok(typeof _tick === "function", "settle: attach must schedule a poll frame into the rAF queue");
  // (1) A MOVING/RESIZING box keeps re-running layout. Drive three reflow stages: slide -> final left -> height grow.
  const _drive = (mut, dtMs) => { mut(); _clock += dtMs; const before = A.tourLayoutRuns(); _tick(); return A.tourLayoutRuns() - before; };
  ok(_drive(() => { _dr.left = 840; _dr.right = 1260; }, 20) === 1, "settle: a slide-frame rect MOVE must re-run _tourLayout once");
  ok(_drive(() => { _dr.left = 420; _dr.right = 840; }, 20) === 1, "settle: the box reaching its final left must re-run _tourLayout");
  ok(_drive(() => { _dr.height = 660; _dr.bottom = 660; }, 40) === 1, "settle: the async frame-line HEIGHT growth must re-run _tourLayout (a MOVE-only watcher would miss it)");
  ok(A.tourSettling() === true, "settle: the watcher must still be polling while the box is changing");
  // (2) A STABLE box (no rect change) inside the quiet window keeps polling but does NOT re-run layout...
  ok(_drive(() => {}, 60) === 0, "settle: an unchanged rect must NOT re-run _tourLayout");
  ok(A.tourSettling() === true, "settle: still within the quiet window -> keep polling");
  // ...and once the rect has held stable for the full quiet window, the watcher STANDS DOWN (no re-schedule).
  ok(_drive(() => {}, 200) === 0, "settle: the settling frame must not re-run layout on an unchanged rect");
  ok(A.tourSettling() === false, "settle: after the rect held stable for the quiet window the watcher must STOP polling");
  // (3) Detach on step change: stepping off the drawer must RELEASE #drawer's watcher (no leak on a persistent element).
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowLeft" }));   // -> tree (index 3)
  ok(A.tourSettleEl() !== "drawer", "settle: stepping off the drawer step must release #drawer's watcher, still on " + JSON.stringify(A.tourSettleEl()));
  ok(A.tourSettleEl() === "tree", "settle: the watcher must re-attach to the new step's target (#tree), got " + JSON.stringify(A.tourSettleEl()));
  const _runsAfterDetach = A.tourLayoutRuns();
  _dr.left = 999;                                          // mutate the (now-detached) drawer rect...
  _tick();                                                 // ...and fire the STALE drawer frame: the guard must make it a no-op
  ok(A.tourLayoutRuns() === _runsAfterDetach, "settle: a STALE drawer frame must not re-run _tourLayout after the watcher detached from #drawer");
  win.performance.now = _origPerfNow; _drawerEl.getBoundingClientRect = _origGBCR;   // restore stubs before the close checks
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowRight" }));  // back to the drawer step for the close checks
  ok(A.tourStep() === 4, "settle: could not return to the drawer step for the close checks, at " + A.tourStep());

  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape" }));
  ok(A.tourStep() === -1, "Esc from the drawer step did not close the tour");
  ok(A.tourSettleEl() === null, "settle: closing the tour must detach the drawer's watcher (no leak), got " + JSON.stringify(A.tourSettleEl()));
  ok(A.tourSettling() === false, "settle: closing the tour must leave no poll frame pending");
  ok(!doc.getElementById("drawer").classList.contains("open"), "Esc from the drawer step did not close the drawer it opened");
  ok(A.curView() === "map", "Esc from the drawer step did not restore the map view");

  // H3. UX5 (D8): the tour tree step EXPANDS the target's collapsed ancestors (Alpha Survey ->
  // c:Australia / o:Australia||OrgX) and RESTORES the prior collapse state on ALL THREE exit paths
  // (forward, back, close). The collapse set is real state (treeCollapsedKeys), not a proxy.
  const goToTreeStep = () => { doc.getElementById("welcomeTour").click();
    for (let k = 0; k < 3; k++) win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowRight" })); };
  A.treeSetCollapsed("c:Australia", true); A.treeSetCollapsed("o:Australia||OrgX", true);
  // path 1: FORWARD exit
  goToTreeStep();
  ok(A.tourStep() === 3, "D8: did not reach the tree step, at " + A.tourStep());
  ok(!A.treeIsCollapsed("c:Australia") && !A.treeIsCollapsed("o:Australia||OrgX"),
    "D8: the tree step did not expand the target's collapsed ancestors");
  ok(!surveyBoxes.find(b => b.value === "Alpha Survey").closest("label").classList.contains("hidden"),
    "D8: the target survey row is still hidden on the tree step");
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowRight" }));   // FORWARD exit (-> drawer step)
  ok(A.treeIsCollapsed("c:Australia") && A.treeIsCollapsed("o:Australia||OrgX"),
    "D8: FORWARD exit did not restore the collapse state");
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape" }));       // close the tour cleanly
  // path 2: BACK exit
  goToTreeStep();
  ok(!A.treeIsCollapsed("c:Australia"), "D8: re-entry (path 2) did not expand again");
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowLeft" }));    // BACK exit (-> find demo)
  ok(A.treeIsCollapsed("c:Australia") && A.treeIsCollapsed("o:Australia||OrgX"),
    "D8: BACK exit did not restore the collapse state");
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape" }));
  // path 3: CLOSE (Esc) at the tree step
  goToTreeStep();
  ok(!A.treeIsCollapsed("c:Australia"), "D8: re-entry (path 3) did not expand again");
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape" }));
  ok(A.treeIsCollapsed("c:Australia") && A.treeIsCollapsed("o:Australia||OrgX"),
    "D8: CLOSE exit did not restore the collapse state");
  A.treeSetCollapsed("c:Australia", false); A.treeSetCollapsed("o:Australia||OrgX", false);   // cleanup
  ok(A.treeCollapsedKeys().length === 0, "D8 cleanup: collapse set not empty after the H3 block");

  // H4. UX6 Wave D (D2 follow-up): the .selbox tour step's target lives in the rail's Select & export
  // mode pane — hidden in the default Browse mode, where the step would degrade to the centred
  // no-spotlight card. Reaching the step must switch the rail to Select & export (jsdom has no layout,
  // so the load-bearing observable here is the MODE + the target pane's visibility — in a real browser
  // an unhidden pane is exactly what gives .selbox a nonzero rect and thus its spotlight), and leaving
  // it must restore the visitor's prior mode on ALL exit paths (forward, back, close) — the same
  // three-path restore discipline the Find/tree demo steps pin above.
  A.setSidebarMode("browse");
  doc.getElementById("welcomeTour").click();                              // step index 0
  for (let k = 0; k < 5; k++) win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowRight" })); // -> index 5 (.selbox)
  ok(A.tourStep() === 5, "D2-tour: ArrowRight x5 did not reach the selbox step, at step " + A.tourStep());
  ok(A.sidebarMode() === "select", "D2-tour: the selbox step did not switch the rail to Select & export");
  ok(!doc.getElementById("selectMode").classList.contains("hidden"),
    "D2-tour: the Select pane (the selbox target's mode container) is still hidden on the selbox step");
  ok(!doc.querySelector(".selbox").closest("section").classList.contains("hidden"),
    "D2-tour: the selbox's own section is hidden on the selbox step (map view not forced?)");
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowRight" }));   // FORWARD -> index 6 (.dlbox)
  ok(A.tourStep() === 6, "D2-tour: could not step forward off the selbox step");
  ok(A.sidebarMode() === "select",
    "D2-tour: the Download step lives in the same Select pane and must keep the mode");
  ok(!doc.querySelector(".dlbox").closest("section").classList.contains("hidden"),
    "D2-tour: the Download block's section is hidden on its own step");
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowRight" }));   // FORWARD exit -> index 7
  ok(A.tourStep() === 7, "D2-tour: could not step forward off the Download step");
  ok(A.sidebarMode() === "browse", "D2-tour: leaving the Select-pane steps did not restore the Browse mode");
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowLeft" }));    // BACK -> index 6 again
  ok(A.tourStep() === 6 && A.sidebarMode() === "select",
    "D2-tour: re-entering the Download step backwards did not re-switch the mode");
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape" }));       // CLOSE from the step
  ok(A.tourStep() === -1, "D2-tour: Esc from the Download step did not close the tour");
  ok(A.sidebarMode() === "browse", "D2-tour: mid-tour close did not restore the Browse mode");

  // I. EMPTY-STATE fixture (UX7b U7): the welcome POPUP must still show on first visit (it explains the
  // portal even before any survey exists) and boot must not crash. A fresh window/localStorage so "first
  // visit" is genuine.
  const emptyWin = await bootFreshWindow({
    "data/catalogue.json": [], "data/tf.json": [], "data/sci.json": [], "data/surveys.json": {},
  });
  const emptyDoc = emptyWin.document;
  ok(emptyWin.__api.nST() === 0, "empty-state fixture unexpectedly loaded stations");
  ok(!emptyDoc.getElementById("introStrip"), "the Wave D corner strip (#introStrip) must be gone in the empty-data boot too");
  const emptyWelcome = emptyDoc.getElementById("introWelcome");
  ok(emptyWelcome, "#introWelcome missing in the empty-data boot");
  ok(!emptyWelcome.classList.contains("hidden"), "welcome popup did not show on first visit in the empty-data state");
  ok(!emptyDoc.getElementById("introOverlay"), "the retired 'How AusMT works' panel must be absent in the empty-data boot too");
  ok(/No surveys published yet/.test(emptyDoc.getElementById("map").innerHTML), "empty-state message did not render alongside the welcome popup");

  // I2. UX5 (D6) GATING-OFF: a boot WITHOUT collections.json renders NO Collections group (and the
  // country/org/survey rows + their carets are unaffected) — the graceful pre-collections behaviour.
  const noCollData = {};
  Object.keys(DATAMAP).forEach(k => { if (k !== "data/collections.json") noCollData[k] = DATAMAP[k]; });
  const wNo = await bootFreshWindow(noCollData);
  const tNo = wNo.document.getElementById("tree");
  const cgNo = wNo.document.getElementById("collGroup");
  ok(cgNo && cgNo.children.length === 0 && !cgNo.querySelector("[data-coll]") && !cgNo.querySelector(".treegroup"),
    "A3: the Collections block (#collGroup) must render EMPTY when the data has no collections (#collGroup:empty hides it)");
  ok(!tNo.querySelector("[data-coll]") && !tNo.querySelector(".treegroup"),
    "A3: no collection rows/heading may appear in #tree in the no-collections boot either");
  ok(tNo.querySelectorAll("label.country").length === 2, "UX5: countries missing in the no-collections boot");
  ok(tNo.querySelectorAll(".caret").length > 0, "UX5: disclosure carets missing in the no-collections boot");

  // J. YEAR RANGE filter (S3 + UX feedback round 1 #2): Alpha [2010,2012], Beta [2018,2019], Gamma
  // undated (no year fields at all). The two inputs get corpus-wide HINTS (placeholder + min/max) from
  // buildState()'s applyYearRangeHints() — min year_start / max year_end across SMETA, here 2010/2019 —
  // but must stay EMPTY on load (a value would immediately exclude Gamma under the filter semantics).
  const yearFrom = doc.getElementById("yearFrom"), yearTo = doc.getElementById("yearTo");
  ok(yearFrom && yearTo, "#yearFrom/#yearTo inputs are missing");
  // C6: the year range is a DISCOVERY filter and now lives in the discovery bar, its one home. The
  // predicate below is unchanged, which is the point of moving the control rather than rewriting it
  // (contract section 1, C6: "the rail's year-range and downloadable-only filters are PROMOTED into the
  // discovery bar ... same behaviour, one home; the rail copies are removed").
  ok(doc.getElementById("discoveryControls").contains(yearFrom) && doc.getElementById("discoveryControls").contains(yearTo),
    "C6: the year-range inputs must live in the discovery bar");
  ok(!doc.getElementById("filterPane").contains(yearFrom),
    "C6: the rail copy of the year-range filter must be removed, not duplicated");
  ok(yearFrom.value === "" && yearTo.value === "", "year-range inputs must stay empty on load, got: " + JSON.stringify([yearFrom.value, yearTo.value]));
  ok(yearFrom.placeholder === "2010", "yearFrom placeholder should hint the corpus min (2010), got: " + yearFrom.placeholder);
  ok(yearTo.placeholder === "2019", "yearTo placeholder should hint the corpus max (2019), got: " + yearTo.placeholder);
  ok(yearFrom.min === "2010" && yearFrom.max === "2019", "yearFrom min/max attrs should be the corpus range, got: " + JSON.stringify([yearFrom.min, yearFrom.max]));
  const yearHead = doc.getElementById("yearRangeHead");
  // C1 (owner R2): the corpus-range suffix takes the SPACED HYPHEN, like every other rendered range.
  ok(yearHead && yearHead.textContent === "Year range (2010 - 2019)", "Year range label should append the corpus range with a spaced hyphen, got: " + (yearHead && yearHead.textContent));
  // C6 (fix round): the promotion must not cost the control what the rail copy gave it. A <label> with
  // no `for` and no wrapped control labels NOTHING - it only claims to - and the two inputs carry their
  // own aria-labels, so the honest markup is a plain element.
  const _lblFor = yearHead.tagName === "LABEL" ? yearHead.getAttribute("for") : null;
  ok(yearHead.tagName !== "LABEL" ||
     (_lblFor && doc.getElementById(_lblFor)) || yearHead.contains(yearFrom) || yearHead.contains(yearTo),
    "C6: #yearRangeHead is a <label> with no `for` and no wrapped control, so it labels nothing; " +
    "use a plain element or give it a real association. tagName=" + yearHead.tagName +
    " for=" + JSON.stringify(_lblFor));
  // ...and the rule this filter runs on must be READABLE. A set year hides every undated survey, which
  // is a silent exclusion; the rail said so in visible copy, and the promotion left it only in a title
  // attribute, which is unreachable by keyboard and on touch.
  const yearNote = doc.getElementById("yearRangeNote");
  ok(yearNote && /surveys with no declared date are hidden once a year is set/.test(yearNote.textContent),
    "C6: the undated-survey rule must be visible copy beside the control, not a title attribute; got " +
    JSON.stringify(yearNote && yearNote.textContent));
  ok(yearNote && doc.getElementById("discoveryControls").contains(yearNote),
    "C6: the year-range note belongs in the discovery bar, beside the control it explains");
  yearFrom.value = "2015"; fire(yearFrom, "input");
  ok(A.visSurveys().includes("Beta Survey"), "year filter wrongly excluded Beta Survey (within range)");
  ok(!A.visSurveys().includes("Alpha Survey"), "year filter did not exclude Alpha Survey (ended before 2015)");
  ok(!A.visSurveys().includes("Gamma Survey"), "year filter did not exclude the undated Gamma Survey once a year was set");
  ok(!A.visSurveys().includes("Delta Survey"), "year filter did not exclude the undated Delta Survey once a year was set");
  ok(A.visIds().length === 1, "expected exactly 1 visible station (B1) after the year filter, got " + A.visIds().length);
  // ONE year window, read twice. The map filters STATIONS (filters.js passesYearRange) and the survey
  // grid filters SURVEYS (drawer.js _surveyPassesYears); the two lived as verbatim copies of one rule in
  // two files, which is the shape C1 removed from acqYearText and the reason an en dash could survive in
  // one copy after the other moved. This pin holds the two readings together whatever the rule becomes.
  A.setView("surveys"); A.renderCards();
  const _gridSv = [...new Set([...doc.querySelectorAll("#cardGrid .scard [data-survey]")]
    .map(b => b.dataset.survey))].sort();
  ok(JSON.stringify(_gridSv) === JSON.stringify([...A.visSurveys()].sort()),
    "C6: the survey grid and the map must read one year window the same way; grid " +
    JSON.stringify(_gridSv) + " map " + JSON.stringify([...A.visSurveys()].sort()));
  A.setView("map");
  yearFrom.value = ""; fire(yearFrom, "input");
  ok(A.visIds().length === 5, "clearing the year filter did not restore all 5 stations");

  // K. DOWNLOADABLE HERE (was the standalone tickbox, then the Data available dropdown's "tf" option,
  // now a discovery chip): the capability is KEPT and the s.ediAvail PREDICATE is unchanged, which
  // matters beyond this filter - the selection exports read the same flag for their three-way
  // not-included honesty. Beta's B1 and embargoed Delta's D1 have edi_available=0; the rest =1.
  // C6 (contract section 1) promoted the control into the discovery bar: it is a question about what a
  // reader can take away, which is a DISCOVERY question, and it belongs beside the licence and type
  // chips that ask the same kind of thing. The rail's "tf" option goes with it; the level chooser, which
  // is about the NCI time-series index and not about this predicate, stays where it is.
  ok(!doc.getElementById("dlOnly") && !doc.getElementById("tfAvail"),
    "the standalone tickbox controls are gone");
  const availSel = doc.getElementById("availSel");
  ok(availSel, "#availSel (Data available) missing from the Browse pane");
  ok(doc.getElementById("browseMode").contains(availSel),
    "D1 (Lane B): the time-series level filter is a VIEWING control and lives in Browse, beside data type");
  ok([...availSel.options].every(o => o.value !== "tf"),
    "C6: the rail copy of the downloadable-only filter must be removed from #availSel");
  const dlChip = () => doc.getElementById("facetChips").querySelector('[data-facet="dl"]');
  A.setView("surveys");
  ok(dlChip(), "C6: a 'Downloadable here' chip must render in the discovery bar");
  dlChip().click();
  ok(!A.visIds().includes("B1"), "C6: the Downloadable here chip did not exclude the non-downloadable station B1");
  ok(!A.visIds().includes("D1"), "C6: the Downloadable here chip did not exclude the embargoed (non-downloadable) station D1");
  ok(A.visIds().length === 3, "C6: expected 3 visible stations with Downloadable here on, got " + A.visIds().length);
  // ...and it narrows the CATALOGUE too, which the rail control could never do: the rail is hidden on
  // the Surveys view, so until this moved there was no way to ask the question about survey cards.
  ok(doc.querySelectorAll("#cardGrid .scard").length === 2,
    "C6: the chip must narrow the card grid to the two surveys with downloadable transfer functions, got " +
    doc.querySelectorAll("#cardGrid .scard").length);
  dlChip().click();
  ok(A.visIds().length === 5, "C6: clearing the Downloadable here chip did not restore all 5 stations");
  A.setView("map");

  // K2. AVAILABILITY > TIME SERIES, the per-level chooser (R3/D7/D8), driven over a REAL index. The
  // fixture ships no ts_access.json, so the index is set directly here: A1 and A2 publish routes, B1
  // publishes one level only, and the embargoed D1 publishes none (which is R5 seen from the portal
  // end - a station the build gated out is simply absent from the index, never filtered here).
  A.setTsAccess({
    "au.alpha.A1": { raw_packed: { bytes: 4000000, url_path: "my80/x/A1 [REMOTE].zip" },
                     level1_mth5: { bytes: 1000000, url_path: "my80/x/A1.h5" } },
    "au.alpha.A2": { raw_packed: { bytes: 2000000, url_path: "my80/x/A2.zip" } },
    "au.beta.B1": { level1_mth5: { bytes: 500000, url_path: "my80/x/B1.h5" } },
  });
  A.paintDownloadRows(); A.refresh();
  const tsBtn = tok => doc.getElementById("tsSeg").querySelector('button[data-ts="' + tok + '"]');
  const tsMeta = tok => tsBtn(tok).querySelector(".dlmeta").textContent;
  ok(["raw_packed", "level0", "level1_mth5", "level1_netcdf"].every(t => tsBtn(t)),
    "D8: the Download block must carry a row for each routable level token");
  ok(!tsBtn("level2"), "D19: level_2 holds transfer functions, not time series, and takes no row");
  ok(!tsBtn("raw_packed").disabled && !tsBtn("level1_mth5").disabled,
    "a level the scope can fetch must offer its list once the index has landed");
  ok(tsBtn("level0").disabled && tsBtn("level1_netcdf").disabled,
    "a level with nothing in scope must stay inert rather than offering an empty list");
  ok(/2 stations/.test(tsMeta("raw_packed")),
    "D7: each row states its scope station count, got " + JSON.stringify(tsMeta("raw_packed")));
  ok(/5.7 MB/.test(tsMeta("raw_packed")),
    "D7: each row states its scope summed size, got " + JSON.stringify(tsMeta("raw_packed")));
  ok(/packed by the custodian/.test(tsBtn("raw_packed").title),
    "D7: each row's action carries its one-line gloss, got " + JSON.stringify(tsBtn("raw_packed").title));
  // THE SCOPE RULE (Lane B): with no selection the rows price the filtered corpus; a selection
  // re-prices them to exactly the chosen stations, and the scope line says which state the reader
  // is in. (The owner's founding defect: 2 selected stations still showed corpus-wide totals.)
  ok(/^Across 5 filtered stations:$/.test(doc.getElementById("scopeLine").textContent),
    "the scope line must state the filtered-corpus scope, got " + JSON.stringify(doc.getElementById("scopeLine").textContent));
  A.setSelected(["A1"]);
  ok(/^For the 1 selected station:$/.test(doc.getElementById("scopeLine").textContent),
    "the scope line must state the selection scope, got " + JSON.stringify(doc.getElementById("scopeLine").textContent));
  ok(/1 station/.test(tsMeta("raw_packed")) && /3.8 MB/.test(tsMeta("raw_packed")),
    "a selection re-prices the rows to the SELECTED stations only, got " + JSON.stringify(tsMeta("raw_packed")));
  ok(tsBtn("level0").disabled && /nothing in this scope/.test(tsMeta("level0")),
    "a level the selection cannot fetch says so, got " + JSON.stringify(tsMeta("level0")));
  A.setSelected([]);
  // The DROPDOWN filters (single-select; the rows only download). Union multi-select retired with it.
  A.setAvail("raw_packed"); A.refresh();
  ok(A.visIds().sort().join() === "A1,A2",
    "the level filter must keep exactly the stations the index publishes that level for, got " + JSON.stringify(A.visIds()));
  A.setAvail("level1_mth5"); A.refresh();
  ok(A.visIds().sort().join() === "A1,B1",
    "a single-select change must REPLACE the level filter, got " + JSON.stringify(A.visIds()));
  ok(!A.visIds().includes("D1"),
    "R5: an embargoed station is absent from the index, so no level can bring it back");
  A.setAvail(""); A.refresh();
  ok(A.availValue() === "" && A.visIds().length === 5,
    "clearing Data available must restore the unfiltered map, got " + JSON.stringify(A.visIds()));
  // The size total is the rows' OWN summation over ts_access.json: it never joins the download
  // manifest, whose SEL_ZIP_BUTTONS table would make a fourth zip row out of it.
  A.setManifest({ files: [], bundles: [] });
  A.paintDownloadRows();
  ok(/5.7 MB/.test(tsMeta("raw_packed")),
    "the rows' sizes must come from ts_access.json, not from the download manifest, got " +
    JSON.stringify(tsMeta("raw_packed")));

  // K3. THE HAND-OFF (R7/D3/D5, reshaped in Lane B). AusMT holds none of these bytes, so the offer
  // is a POINTER FILE and never a fourth selection zip. The old #dlTs button is replaced by the
  // per-level "Download list" actions on the time-series rows (each names its own level, so no
  // hidden state can narrow the file) and by the merged Pointers export in the Metadata block.
  ok(!doc.getElementById("dlTs"), "the old #dlTs export is replaced by the per-level row actions");
  ok(doc.getElementById("dlSh") && /Pointers \(JSON\)/.test(doc.getElementById("dlSh").textContent),
    "the Metadata block must carry the merged Pointers (JSON) export");
  A.setSelected(["A1", "A2", "B1", "D1"]);
  const _hd = A.tsHandoffDoc();
  ok(_hd.files === 4 && _hd.doc.stations.length === 3,
    "the list must cover every routable level of every selected station in the index, got " +
    _hd.files + " file(s) across " + _hd.doc.stations.length + " station(s)");
  ok(!_hd.doc.stations.some(r => r.ausmt_id === "au.delta.D1"),
    "R5: the embargoed station is absent from the index, so it cannot appear in a hand-off list");
  const _a1row = _hd.doc.stations.find(r => r.ausmt_id === "au.alpha.A1");
  const _a1raw = _a1row.levels.find(l => l.level === "raw_packed");
  ok(/^https?:\/\/[^/]+\/go\/ts\/alpha\/A1\/raw_packed$/.test(_a1raw.url),
    "D12: the fetched url must be the AusMT /go/ts/<survey>/<station>/<level> route, got " + JSON.stringify(_a1raw.url));
  ok(_a1raw.archive_url_comment === "https://thredds.nci.org.au/thredds/fileServer/my80/x/A1%20%5BREMOTE%5D.zip",
    "D3: the archive address rides alongside as an inert reference, percent-encoded exactly as the " +
    "engine encodes it (the `C5 [REMOTE].zip` case), got " + JSON.stringify(_a1raw.archive_url_comment));
  ok(_a1raw.bytes === 4000000 && _a1raw.filename === "A1 [REMOTE].zip",
    "each row states the size and the archive's own filename, got " + JSON.stringify([_a1raw.bytes, _a1raw.filename]));
  ok(/wget -c/.test(_hd.doc.note) && /curl -L -C -/.test(_hd.doc.note) && /resumes on a re-run/i.test(_hd.doc.note),
    "D3: the file must name the resumable fetch commands for both tools, got " + JSON.stringify(_hd.doc.note));
  ok(/hosts none of these files/i.test(_hd.doc.note),
    "the file must restate that AusMT hosts nothing it routes to, got " + JSON.stringify(_hd.doc.note));
  ok(_hd.doc.scope && _hd.doc.scope.stations === 4 && _hd.doc.scope.levels === "all",
    "the document must record its own scope, got " + JSON.stringify(_hd.doc.scope));
  // A ROW's list is scoped to ITS level - the row names the level, so nothing hidden can narrow it.
  const _hdScoped = A.tsHandoffDoc(null, ["raw_packed"]);
  ok(_hdScoped.files === 2 && _hdScoped.doc.stations.every(r => r.levels.every(l => l.level === "raw_packed")),
    "a per-level list must carry exactly that level, got " + _hdScoped.files + " file(s)");
  ok(_hdScoped.doc.scope && String(_hdScoped.doc.scope.levels) === "raw_packed",
    "a per-level list must record its level in the scope, got " + JSON.stringify(_hdScoped.doc.scope));
  // THE CONFIRMATION (owner rulings 2026-08-23 + 2026-08-25) from the raw_packed row. A small
  // scope gets its FILES: each route handed to the browser through the tsOpenRoute seam (recorded
  // here), nothing saved, and the browser owns the downloads and their progress.
  const _trackBefore = trackCalls.length;
  A.paintDownloadRows();
  ok(/^Download · 2 stations/.test(tsMeta("raw_packed")),
    "a within-cap row states the direct mode, got " + JSON.stringify(tsMeta("raw_packed")));
  const handed = [];
  win.tsOpenRoute = u => handed.push(u);
  const _savedBefore = savedBlobs.length, _zmarkTs = zipEntries.length;
  tsBtn("raw_packed").click();
  await new Promise(r => setTimeout(r, 0));          // the handler is async (the metadata pack awaits SCI_READY)
  ok(handed.length === 2 && handed.every(u => /\/go\/ts\/[^/]+\/[^/]+\/raw_packed$/.test(u)),
    "a within-cap click hands each ROUTE to the browser, got " + JSON.stringify(handed));
  ok(savedBlobs.length === _savedBefore, "the direct path saves no list file");
  // The metadata & citation pack travels with the hand-off (owner, 2026-08-25): citations, the
  // station table, the geometry and the hand-off record itself, zipped beside the data.
  const _tsPack = zipEntries.slice(_zmarkTs).map(e => e.name);
  ["CITATIONS.txt", "citations.bib", "citations.ris", "stations.csv", "selection.geojson", "handoff.json"]
    .forEach(n => ok(_tsPack.indexOf(n) >= 0, "the hand-off metadata pack is missing " + n + ", got " + JSON.stringify(_tsPack)));
  const snackEl = doc.getElementById("snackbar");
  ok(snackEl && !snackEl.classList.contains("hidden"), "the hand-off must confirm itself in the snackbar");
  ok(/Handed 2 files to your browser - /.test(snackEl.textContent) &&
     /Progress appears in your browser's downloads\./.test(snackEl.textContent),
    "the direct confirmation states what was handed and where progress lives, got " + JSON.stringify(snackEl.textContent));
  // Beyond the cap the offer stays a LIST + wget (driven through the cap seam: the fixture's
  // total is megabytes, and the cap's VALUE - 10 GB of TOTAL SIZE, owner-ruled - is a tuning
  // constant, not a contract).
  win.TS_DIRECT_MAX_BYTES = 1;
  A.paintDownloadRows();
  ok(/^Download list · 2 stations/.test(tsMeta("raw_packed")),
    "an over-cap row states the list mode, got " + JSON.stringify(tsMeta("raw_packed")));
  const _zmarkOver = zipEntries.length;
  tsBtn("raw_packed").click();
  await new Promise(r => setTimeout(r, 0));
  // Over the cap the pack is the ONLY save: the standalone list .json was the same document the
  // pack already carries as handoff.json, and it landed at the head of the reader's downloads
  // (owner, 2026-08-26). Exactly one save (the pack), never two.
  // The pack is built through the stubbed JSZip, so it shows up as ZIP ENTRIES rather than a save;
  // what must be GONE is the standalone list .json, which was a real save.
  const _zOver = zipEntries.slice(_zmarkOver).map(e => e.name);
  ok(_zOver.some(n => /handoff\.json$/.test(n)),
    "the over-cap path must still build the metadata pack (its handoff.json IS the list), got " + JSON.stringify(_zOver));
  ok(savedBlobs.length === _savedBefore,
    "the over-cap path must save no standalone list .json - the pack already carries it - got " +
    JSON.stringify(savedBlobs.slice(_savedBefore).map(b => b.name)));
  ok(/Download list ready - 2 files, /.test(snackEl.textContent),
    "the list confirmation must state the ROW-scoped file count and size, got " + JSON.stringify(snackEl.textContent));
  ok(handed.length === 2, "the over-cap path hands nothing directly");
  // The dialog opens BY ITSELF over the cap (owner, 2026-08-26): at this size the terminal command
  // is the only thing that can serve the reader, so putting it behind a snackbar action was a click
  // between them and the answer. The action stays for re-opening after a dismiss.
  const wgetModal = doc.getElementById("wgetModal"), wgetCmd = doc.getElementById("wgetCmd");
  ok(wgetModal && !wgetModal.classList.contains("hidden"),
    "the over-cap path must OPEN the terminal-command dialog itself, not wait for a click");
  doc.getElementById("wgetClose").click();
  win.TS_DIRECT_MAX_BYTES = 5 * 1024 * 1024 * 1024;
  const showBtn = snackEl.querySelector("button");
  ok(showBtn && /terminal command/i.test(showBtn.textContent),
    "the confirmation must still offer the terminal command for a re-open, got " + (showBtn && showBtn.textContent));
  showBtn.click();
  ok(wgetModal && !wgetModal.classList.contains("hidden"), "the wget dialog must re-open from the snackbar action");
  ok(/terminal/i.test(wgetModal.textContent), "the dialog must say the command runs in the reader's own terminal");
  // Platform tabs: three of them, the detected platform pre-selected (jsdom's navigator detects as
  // Linux here). Linux carries per-file `wget ... -P <slug>/<level>` lines (namespaced so same-named
  // files never collide); macOS and Windows carry curl / curl.exe with -o paths namespaced the same
  // way. The Windows command differs genuinely: curl.exe by full name (PowerShell aliases bare curl
  // away) and a safe-charset -o filename (PowerShell and cmd quote incompatibly).
  const osTabs = [...doc.getElementById("wgetOs").querySelectorAll("button")];
  ok(osTabs.length === 3 && osTabs.map(b => b.dataset.os).join() === "linux,mac,win",
    "the dialog must carry Linux/macOS/Windows tabs, got " + osTabs.map(b => b.dataset.os).join());
  ok(osTabs.filter(b => b.classList.contains("on")).length === 1,
    "exactly one tab is pre-selected (the detected platform; jsdom's UA reports the HOST kernel, so which one is host-dependent)");
  osTabs[0].click();
  ok(/^wget -c -q --show-progress --content-disposition -P '/.test(wgetCmd.textContent) &&
     wgetCmd.textContent.indexOf("AUSMT_EOF") < 0,
    "the Linux tab must carry the resumable per-file wget -P form, got " +
    JSON.stringify(wgetCmd.textContent.split("\n")[0]));
  ok(!/^#/.test(wgetCmd.textContent),
    "no leading # header: interactive zsh has no comments by default, so a pasted header line errors");
  // macOS and Windows carry the CURL form: preinstalled on both (no third-party binary, no Homebrew),
  // output names as explicit -o paths namespaced <slug>/<level>/<basename> with --create-dirs, -C - resume.
  osTabs[1].click();
  ok(/^curl -L -C - --create-dirs -o '/.test(wgetCmd.textContent) && wgetCmd.textContent.indexOf("AUSMT_EOF") < 0,
    "the macOS tab must carry the curl namespaced -o form, got " + JSON.stringify(wgetCmd.textContent.slice(0, 60)));
  ok(/preinstalled on macOS/.test(doc.getElementById("wgetOsNote").textContent),
    "the macOS tab must say nothing needs installing");
  osTabs[2].click();
  ok(/^curl\.exe -L -C - --create-dirs -o "/.test(wgetCmd.textContent) &&
     (wgetCmd.textContent.match(/-o "/g) || []).length === 2 &&
     wgetCmd.textContent.indexOf("AUSMT_EOF") < 0,
    "the Windows tab must carry curl.exe with one namespaced -o path per file, got " +
    JSON.stringify(wgetCmd.textContent.slice(0, 80)));
  ok(/preinstalled on Windows 10/.test(doc.getElementById("wgetOsNote").textContent) &&
     !/winget|JernejSimoncic/.test(doc.getElementById("wgetOsNote").textContent),
    "the Windows tab must need no third-party install");
  doc.getElementById("wgetCopy").click();
  ok(clipboard.length === 1 && clipboard[0] === wgetCmd.textContent && /curl\.exe/.test(clipboard[0]),
    "the dialog's copy must put EXACTLY the ACTIVE tab's command on the clipboard");
  osTabs[0].click();
  clipboard.length = 0;
  doc.getElementById("wgetCopy").click();
  ok(clipboard.length === 1 && clipboard[0] === wgetCmd.textContent,
    "switching back to Linux must restore the unix command for the copy");
  ok((clipboard[0].match(/\/go\/ts\//g) || []).length === 2,
    "the copied command must carry exactly the row's routed files, got " + JSON.stringify(clipboard[0]));
  ok(!/thredds\.nci\.org\.au/.test(clipboard[0]),
    "the copied command must fetch the AusMT route, not the archive address it resolves to (the route " +
    "is what the front door counts), got " + JSON.stringify(clipboard[0]));
  // K6. THE DIALOG'S MODAL CONTRACT (section-4 review, P2/P3). It declares aria-modal="true", so it owes
  // the keyboard behaviours the welcome popup (the SAME visual shell) already has: Escape, click-out and
  // focus restore. Esc used to fall through to the drawer's global handler and close the drawer BEHIND
  // the open dialog. The OS switcher is a role="tablist", so its buttons owe role="tab" + aria-selected:
  // before this, the active OS was signalled by a CSS class alone and assistive tech saw nothing.
  const _osBtns = [...doc.getElementById("wgetOs").querySelectorAll("button")];
  ok(_osBtns.every(b => b.getAttribute("role") === "tab"),
    "every OS switcher button must be a role=tab: the container declares role=tablist");
  ok(_osBtns.filter(b => b.getAttribute("aria-selected") === "true").length === 1,
    "exactly one OS tab must carry aria-selected=true, so the active OS is not signalled by colour alone");
  const _pressed = _osBtns.find(b => b.getAttribute("aria-selected") === "true");
  ok(_pressed && _pressed.classList.contains("on"),
    "aria-selected must track the same tab the .on class paints, or the two states can disagree");
  ok(doc.getElementById("wgetCmd").getAttribute("role") === "tabpanel",
    "the command block is the panel the tabs drive, so it must be a role=tabpanel");
  // Escape closes the DIALOG and leaves the drawer alone.
  const _drawerBefore = doc.getElementById("drawer").classList.contains("open");
  doc.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape" }));
  ok(wgetModal.classList.contains("hidden"), "Escape must close the wget dialog");
  ok(doc.getElementById("drawer").classList.contains("open") === _drawerBefore,
    "Escape over the dialog must NOT reach the drawer behind it: the dialog is modal");
  // Re-open and close by clicking the scrim, the welcome popup's own click-out rule.
  snackEl.querySelector("button").click();
  ok(!wgetModal.classList.contains("hidden"), "matrix setup: the dialog did not re-open for the click-out pin");
  wgetModal.click();
  ok(wgetModal.classList.contains("hidden"), "a click on the scrim must close the dialog (click-out)");
  snackEl.querySelector("button").click();
  doc.getElementById("wgetClose").click();
  ok(wgetModal.classList.contains("hidden"), "the dialog's Close must hide it");
  ok(trackCalls.length === _trackBefore,
    "R8: the hand-off adds no track() call site; it is measured at the front door, from the route it uses");
  ok(!/progress|complete|finished|%/i.test(snackEl.textContent),
    "the page claims no progress and no completion; the browser owns both, got " + JSON.stringify(snackEl.textContent));
  // POINTERS (Lane B, D2): the merged document - EVERY scope station appears; routable stations
  // carry levels[]; the embargoed D1 appears WITHOUT levels (identity is public, routes are not).
  clipboard.length = 0;
  doc.getElementById("dlSh").click();
  const _ptrTrack = trackCalls[trackCalls.length - 1];
  ok(_ptrTrack && _ptrTrack.props && _ptrTrack.props.format === "pointers",
    "Pointers must report its own analytics format (the old export was indistinguishable from GeoJSON), got " +
    JSON.stringify(_ptrTrack && _ptrTrack.props));
  const _ptr = JSON.parse(savedBlobs[savedBlobs.length - 1].text);
  ok(_ptr.stations.length === 4, "Pointers must cover EVERY scope station, got " + _ptr.stations.length);
  const _d1 = _ptr.stations.find(r => r.ausmt_id === "au.delta.D1");
  ok(_d1 && !_d1.levels, "an unroutable station appears with no levels[], never invented rows");
  ok(_ptr.stations.filter(r => r.levels).length === 3, "routable stations carry their levels[] rows");
  ok(/Pointers written for 4 stations - 4 fetchable files, /.test(snackEl.textContent),
    "the Pointers confirmation states stations and fetchable files, got " + JSON.stringify(snackEl.textContent));

  // K4. THE SINGLE-STATION HAND-OFF, and THE JOIN RULE that decides whether its action row exists.
  // m.ts_levels is CURATOR-DECLARED and SURVEY-scope; the index is CRAWL-VERIFIED and STATION-scope.
  // Beta declares NO levels at all, so a hasLevel()-gated action would read "not available" for a
  // Level 1 file this deployment can hand B1 straight to. The register wins the station row.
  A.setSMETA("Beta Survey", { ts_levels: [] });
  A.openStationById("au.beta.B1");
  const _files = doc.getElementById("drawer");
  const _hand = [..._files.querySelectorAll('.prod[data-prod="open"][data-tsname]')];
  ok(_hand.length === 1,
    "the JOIN RULE: a verified level must offer its action even where the survey declares no levels, got " + _hand.length);
  ok(/Level 1 MTH5/.test(_hand[0].textContent) && /488 KB/.test(_hand[0].textContent),
    "the action row states the level and the archive's size, got " + JSON.stringify(_hand[0].textContent));
  ok(/not available/.test(_files.querySelector(".filelist").textContent),
    "sensitivity: the survey-scope 'not available' sub-text is UNCHANGED by the action row; the two " +
    "statements answer different questions and this one is still the curator's");
  const _badges = [..._files.querySelectorAll(".badges .badge")].length;
  A.openStationById("au.alpha.A1");
  ok([..._files.querySelectorAll(".badges .badge")].length === _badges,
    "D7: no fourth badge; the drawer gains an ACTION ROW, not another availability claim");
  const _openBefore = opened.length, _trackBefore2 = trackCalls.length;
  const _a1hand = _files.querySelector('.prod[data-prod="open"][data-tsname]');
  ok(_a1hand, "A1 publishes routes, so its Files tab must carry hand-off actions");
  A.dispatchProd(Object.assign({}, _a1hand.dataset));
  ok(opened.length === _openBefore + 1 && /\/go\/ts\/alpha\/A1\//.test(opened[opened.length - 1][0]),
    "the action must open the AusMT route, got " + JSON.stringify(opened[opened.length - 1]));
  ok(trackCalls.length === _trackBefore2,
    "R8: dispatchProd leaves `open` UNTRACKED, and the hand-off must not change that");
  ok(/Handed to NCI THREDDS - your browser is downloading /.test(snackEl.textContent) &&
     /Progress appears in your browser's downloads\./.test(snackEl.textContent),
    "the single-station hand-off states what was handed over and where the progress will appear, got " +
    JSON.stringify(snackEl.textContent));
  ok(!/this may take a while/i.test(snackEl.textContent),
    "a small file gets no large-file line, got " + JSON.stringify(snackEl.textContent));
  A.dispatchProd({ prod: "open", url: "http://localhost/go/ts/alpha/A1/raw_packed",
                   tsname: "BIG.zip", tsbytes: String(9868836788) });
  ok(/9\.2 GB/.test(snackEl.textContent) && /large file - this may take a while/i.test(snackEl.textContent),
    "above 5 GB the hand-off appends the large-file line, got " + JSON.stringify(snackEl.textContent));
  A.setSelected([]);
  A.closeDrawer();

  // K5. HAND-OFF COMMAND SAFETY (fix/gateway-silent-success). Two independent defects in the fetch
  // commands, both proven here against the REAL builders (tsCurlCommand/tsWgetCommand via the bridge):
  //  1. FILENAME COLLISION - the archive basename is NOT unique (a station's level0 and level1_mth5 can
  //     carry the same one, and basenames repeat across surveys), so writing by basename alone lets one
  //     product overwrite another - and with curl -C - the second RESUMES INTO the first, corrupting both.
  //     Each -o path (curl) / -P prefix (wget) must be namespaced by survey slug + level so none collide.
  //  2. SHELL INJECTION - the basename is stored verbatim from third-party registers with no charset gate,
  //     and was interpolated into double quotes where bash/zsh still honour $( ), backticks and ". The
  //     built filename must be shell-safe: POSIX single-quoting on macOS/Linux, a safe-charset restriction
  //     on Windows (curl.exe is pasted into PowerShell or cmd, which quote incompatibly).
  const shq = s => "'" + String(s).replace(/'/g, "'\\''") + "'";      // mirrors exports.js shq()
  const winSafe = s => String(s).replace(/[^A-Za-z0-9._\/-]/g, "_");  // mirrors exports.js winSafePath()
  const INJ = "$(touch pwned) `id` \";x;\" 'sq' [z].zip";             // every metacharacter the field can carry
  A.setTsAccess({
    // A1: ONE station whose level0 and level1_mth5 carry the SAME basename (the live SA295.h5 case).
    "au.alpha.A1": { level0: { bytes: 100, url_path: "arc/SA295.h5" },
                     level1_mth5: { bytes: 200, url_path: "arc/SA295.h5" } },
    // A2: a basename carrying live shell metacharacters (the corpus already ships `C5 [REMOTE].zip`).
    "au.alpha.A2": { raw_packed: { bytes: 300, url_path: "arc/" + INJ } },
  });
  A.setSelected(["A1", "A2"]);
  const _cs = A.tsHandoffDoc().doc.stations;
  const _mac = A.tsCurl(_cs, "curl"), _win = A.tsCurl(_cs, "curl.exe"), _nix = A.tsWget(_cs);
  // DEFECT 1, curl: the two same-basename levels get DISTINCT namespaced -o paths, never a bare basename.
  ok(_mac.indexOf("-o " + shq("alpha/level0/SA295.h5")) >= 0 &&
     _mac.indexOf("-o " + shq("alpha/level1_mth5/SA295.h5")) >= 0,
    "collision: colliding basenames must get distinct <slug>/<level>/ -o paths, got " + JSON.stringify(_mac));
  ok(_mac.indexOf("-o 'SA295.h5'") < 0 && _mac.indexOf('-o "SA295.h5"') < 0,
    "collision: the bare un-namespaced basename must never be an -o target, got " + JSON.stringify(_mac));
  // DEFECT 1, wget: same-named files land in DISTINCT -P prefixes (verified: wget -P builds the tree and
  // --content-disposition writes inside it, so the silent .1 fork cannot happen).
  ok(_nix.indexOf("-P " + shq("alpha/level0")) >= 0 && _nix.indexOf("-P " + shq("alpha/level1_mth5")) >= 0,
    "collision: wget must place same-named files under distinct -P prefixes, got " + JSON.stringify(_nix));
  ok(!/ -i - /.test(_nix) && _nix.indexOf("AUSMT_EOF") < 0,
    "collision: the -i - here-doc cannot namespace per file, so it is retired for per-file -P lines, got " + JSON.stringify(_nix));
  // DEFECT 2, curl macOS/Linux: the -o filename is POSIX single-quoted verbatim ($( ), backtick, ; and "
  // inert), never double-quoted (double quotes still honour them). Verified end-to-end: the quoted form
  // writes the injection string as a literal filename and fires no command.
  ok(_mac.indexOf("-o " + shq("alpha/raw_packed/" + INJ)) >= 0,
    "injection: the POSIX -o filename must be single-quote-escaped verbatim, got " + JSON.stringify(_mac));
  ok(_mac.indexOf('-o "') < 0,
    "injection: the macOS/curl -o filename must never be double-quoted, got " + JSON.stringify(_mac));
  ok(!/\$\(|`/.test(_nix),
    "injection: no command substitution can appear in the wget command (routes, not filenames), got " + JSON.stringify(_nix));
  // DEFECT 2, curl.exe Windows: no single wrap is safe in both PowerShell and cmd, so the built path is
  // restricted to a metacharacter-free charset and double-quoted - inert in either shell.
  ok(_win.indexOf('-o "' + winSafe("alpha/raw_packed/" + INJ) + '"') >= 0,
    "injection: the Windows -o path must be restricted to a safe charset, got " + JSON.stringify(_win));
  const _winO = [..._win.matchAll(/-o "([^"]*)"/g)].map(m => m[1]);
  ok(_winO.length === 3 && _winO.every(t => !/[^A-Za-z0-9._\/-]/.test(t)),
    "injection: every Windows -o filename must be metacharacter-free, got " + JSON.stringify(_winO));
  // The commands still name the AusMT routes (counted at the front door), never the archive addresses.
  ok((_mac.match(/\/go\/ts\//g) || []).length === 3 && !/thredds\.nci\.org\.au/.test(_mac),
    "the fetch commands carry the AusMT routes, not the archive addresses, got " + JSON.stringify(_mac));
  A.setSelected([]);

  // L. GO TO PLACE REMOVED (UX feedback round 1 #1): operator decision, redundant. Assert the input
  // (and its datalist) are gone from the rendered page, not merely unused.
  ok(!doc.getElementById("goPlace"), "#goPlace should have been removed from the filter rail");
  ok(!doc.getElementById("auPlaces"), "#auPlaces datalist should have been removed along with #goPlace");

  // M. SCREENING (advanced) (UX feedback round 1 #4): the specialist controls live inside ONE
  // <details class="advanced"> collapsed by default (no `open` attribute) at the bottom of the filter
  // rail. The Availability group (R2/R3) and the colour-by segmented control are both inside it, and
  // there is exactly ONE Availability group: the standalone "Downloadable here" checkbox and the
  // Min-TF-diagnostic segmented control are gone, replaced by it.
  // Lane B structure (owner polish round): Browse carries every map filter - data type on top, then
  // the Advanced search accordion (Find, Data available, Year range), collapsed by default; Select &
  // download carries selection + Download + Metadata. The retired controls must be absent, not hidden.
  const _adv = doc.getElementById("advSearch");
  ok(_adv && _adv.matches("details.advanced"), "the Advanced search accordion is missing from Browse");
  // The tour's Find step legitimately opened it earlier in this suite, so the collapsed DEFAULT is
  // asserted against the shipped markup, not runtime state.
  ok(!/<details[^>]*id="advSearch"[^>]*\sopen[\s>]/.test(fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8")),
    "Advanced search must ship collapsed (no open attribute in the markup)");
  ok(/Advanced search/.test(_adv.querySelector("summary").textContent),
    "the accordion summary must read Advanced search");
  const _browse = doc.getElementById("browseMode");
  ok(_browse.contains(_adv), "Advanced search lives in the Browse pane");
  // C6: the year range left this accordion for the discovery bar (its rail copy is removed), so what
  // Advanced search still holds is Find and the time-series level chooser.
  ok(["find", "availSel"].every(id => _adv.contains(doc.getElementById(id))),
    "Advanced search must hold Find and Data available");
  ok(!_adv.contains(doc.getElementById("yearFrom")),
    "C6: the year range must no longer be in the rail's Advanced search accordion");
  ok(!doc.getElementById("qSeg"), "the Min-TF-diagnostic group stays retired");
  ok(!doc.getElementById("colorSeg"), "colour-by is retired (owner D4) and must not render");
  ok(!doc.getElementById("pLo") && !doc.getElementById("pHi"),
    "the period slider is retired (headless predicate); its inputs must not render");
  ok(doc.getElementById("selectMode").contains(doc.getElementById("tsSeg")),
    "the Download block's time-series rows live in the Select & download pane");

  // N. RECENTLY ADDED (cleanup wave A): ONE surface (the surveys-view #recentStrip; the map-rail
  // #recentSide is deleted). The strip's DISPLAY rule is a 30-day window ending at the BUILD day
  // (build.json generated=2020-01-15) capped at 3, so of the fixture's dated surveys only Beta
  // (latest 2019-12-31, inside the window) qualifies; Alpha (2012-05-01) is outside it and
  // Gamma/Delta are undated. surveyLatestDate itself stays lockstep with the engine's feed rule.
  const recents = A.recentlyAdded();
  ok(recents.length === 1 && recents[0].sv === "Beta Survey",
    "recentlyAdded() must apply the 30-day build-window: only Beta qualifies, got " + JSON.stringify(recents));
  ok(!recents.some(e => e.sv === "Alpha Survey"), "recentlyAdded() must EXCLUDE Alpha (2012-05-01, outside the 30-day window)");
  ok(!recents.some(e => e.sv === "Gamma Survey" || e.sv === "Delta Survey"), "recentlyAdded() must omit the undated Gamma/Delta surveys");
  const recentStrip = doc.getElementById("recentStrip");
  ok(recentStrip && /Recently added/.test(recentStrip.innerHTML), "#recentStrip did not render a 'Recently added' label");
  // SURVEY LINKS: every survey link in the SPA targets that survey's own published static page, never
  // the right-hand drawer. The strip's link is therefore a path URL, and the fragment form is pinned
  // ABSENT so a revert to the drawer route turns this red rather than passing on a substring.
  const _raLink = recentStrip.querySelector("a");
  ok(_raLink && _raLink.getAttribute("href") === "/surveys/" + recents[0].slug,
    "#recentStrip must link the recent survey by its published /surveys/<slug> page, got href=" +
    JSON.stringify(_raLink && _raLink.getAttribute("href")));
  ok(recentStrip.innerHTML.indexOf("#/survey/") < 0,
    "#recentStrip must NOT link the retired #/survey/<slug> drawer route");
  ok(!recentStrip.classList.contains("hidden"), "#recentStrip must be shown when the window has a survey");
  // C4 (brief 9, Option A): the strip is a CONCISE HORIZONTAL LINE, not a block. It was a heading over a
  // column of rows in a full-width container, which on a wide screen was a large sparse box of mostly
  // empty space sitting between the reader and the catalogue. Option A is one wrapping line:
  // "Recently added: Vulcan 2022 (interpunct) AusLAMP Queensland Phase 3". Pins moved with the markup per
  // contract section 1, C4 ("section N pins move with the markup"); the WINDOW LOGIC above is untouched
  // and its pins are unchanged, which is the point - this commit may only change how the strip reads.
  ok(recentStrip.querySelector("h2") === null,
    "C4: the strip must not open with a block heading; the label is inline (brief 9 Option A)");
  ok(recentStrip.querySelector("ul, li") === null,
    "C4: the strip must not render a vertical list; Option A is one wrapping line");
  ok(/Recently added:/.test(recentStrip.textContent),
    "C4: the inline label reads 'Recently added:', got " + JSON.stringify(recentStrip.textContent));
  ok(recentStrip.querySelectorAll("a").length === recents.length,
    "C4: the strip must link every survey in the window, got " + recentStrip.querySelectorAll("a").length +
    " links for " + recents.length + " entries");
  // The date is what makes an entry "recent", so it may not simply be dropped: it rides the link as its
  // title, reachable without spending a second line on it.
  ok((recentStrip.querySelector("a").getAttribute("title") || "").indexOf(recents[0].date) >= 0,
    "C4: a strip link must carry its date, got title=" +
    JSON.stringify(recentStrip.querySelector("a").getAttribute("title")));
  // POSITION (contract C4): the strip sits directly BELOW the discovery controls, so the controls are
  // the first thing on the view and the strip reads as a shortcut into the grid rather than a preamble.
  const _dc = doc.getElementById("discoveryControls");
  ok(_dc && _dc.nextElementSibling === recentStrip,
    "C4: #recentStrip must sit directly below the discovery controls, got " +
    JSON.stringify(_dc && _dc.nextElementSibling && _dc.nextElementSibling.id));
  // The map-rail recently-added section is GONE (deleted, not merely hidden): the leak was that section
  // un-hiding on every view. Neither the element nor its old wrapper must exist.
  ok(doc.getElementById("recentSide") == null && doc.getElementById("recentSideSection") == null,
    "the map-rail recently-added section (#recentSide/#recentSideSection) must be deleted (single-surface strip only)");

  // N2. PINNED CROSS-LANE DATE RULE (LOCKSTEP with engine build_portal.py _survey_latest_date):
  // attribution.declared_date is a first-class candidate date sharing ONE candidate set with
  // release_notes[].date; the MAX well-formed YYYY-MM-DD wins, and a survey carrying a declared_date
  // but no release_notes dates by that declared_date, NOT the bare-year Dec-31 fallback. These are
  // pure surveyLatestDate() checks (the fixture path above exercises the 30-day window, but never the
  // declared_date candidate), so the shared date rule is pinned directly without a full re-render.
  ok(A.surveyLatestDate({ year_end: 2019, attribution: { declared_date: "2026-07-25" } }) === "2026-07-25",
    "surveyLatestDate must date by attribution.declared_date, not the year_end Dec-31 fallback");
  ok(A.surveyLatestDate({ attribution: { declared_date: "2026-07-25" }, release_notes: [{ date: "2020-01-01" }] }) === "2026-07-25",
    "surveyLatestDate must let a newer declared_date win over an older release note");
  ok(A.surveyLatestDate({ attribution: { declared_date: "2019-01-01" }, release_notes: [{ date: "2023-05-10" }] }) === "2023-05-10",
    "surveyLatestDate must let a newer release note win over an older declared_date");
  ok(A.surveyLatestDate({ year_end: 2020, attribution: { declared_date: "2026-07" } }) === "2020-12-31",
    "surveyLatestDate must skip a malformed (non-YYYY-MM-DD) declared_date and fall back to the year");

  // O. C1b DISPLAY-PRODUCT GATE: opening an EMBARGOED survey's station must replace the four TF plots with
  //    an access panel carrying the verbatim embargo copy, and render NO svg plot paths (the response
  //    curves ARE the embargoed data). An OPEN survey's station must still plot. FAILS pre-fix: the drawer
  //    renders the (now-empty) plots area with no access panel — the verbatim copy is absent.
  const drawerEl = doc.getElementById("drawer");
  // Verbatim no-date embargo copy (embargo_until is null in the fixture) — pinned so a copy edit fails here.
  const EMBARGO_NODATE = "This survey is embargoed. Station locations and survey metadata are public; " +
    "transfer functions and downloads are withheld.";
  win.location.hash = "#/station/au.delta.D1"; A.routeFromHash();
  ok(drawerEl.classList.contains("open"), "#/station route did not open the embargoed station's drawer");
  ok(drawerEl.textContent.indexOf(EMBARGO_NODATE) >= 0,
    "embargoed station drawer is missing the verbatim no-date embargo panel copy; drawer text was: " + drawerEl.textContent.slice(0, 400));
  ok(drawerEl.querySelectorAll("svg path").length === 0,
    "embargoed station drawer must render NO svg plot paths (curves are withheld data), found " + drawerEl.querySelectorAll("svg path").length);
  // The related-products TF tile must say "embargoed", not "EDI (via source archive)".
  ok(drawerEl.innerHTML.indexOf("EDI (via source archive)") < 0,
    "embargoed station must NOT offer the 'EDI (via source archive)' fallback tile");
  // An OPEN survey's station (A1) still plots — the withholding is CONDITIONAL on access, not a blanket wipe.
  drawerEl.classList.remove("open");
  win.location.hash = "#/station/au.alpha.A1"; A.routeFromHash();
  ok(drawerEl.classList.contains("open"), "#/station route did not open the open station's drawer");
  ok(drawerEl.querySelectorAll("svg path").length > 0,
    "an OPEN survey's station must still render TF plot paths, found none");
  ok(drawerEl.textContent.indexOf(EMBARGO_NODATE) < 0,
    "an OPEN survey's station must NOT show the embargo access panel");

  // P. PID LINKS (PID schema + goal-2 proof). Rendered PIDs must be REAL clickable <a href> anchors,
  //    not plain text, and a HOSTILE pid must render INERT (no executable href, no HTML injection).
  //
  //    P1 — SURVEY drawer (openSurvey -> identifiersHtml): each instrument's registry pid from the additive
  //    instruments[] list renders as a REAL clickable <a href>, and the hostile instrument pid
  //    (javascript:alert(1)) must be neutralised by the escUrl guard (rewritten to the safe handle host), so
  //    NO href carries a javascript: scheme. IDCONS D2: the legacy "Survey PID" (m.pid) ROW is RETIRED from
  //    display — never minted, it read "not recorded" on every real survey — so the drawer must NOT render a
  //    "Survey PID" label nor the m.pid handle link (the field is still served; only the row is gone).
  const dpid = doc.getElementById("drawer");
  dpid.classList.remove("open");
  win.location.hash = "#/survey/alpha"; A.routeFromHash();
  ok(dpid.classList.contains("open"), "PID: #/survey/alpha did not open Alpha's drawer");
  let hrefs = [...dpid.querySelectorAll("a[href]")].map(a => a.getAttribute("href"));
  ok(!/Survey PID:/.test(dpid.innerHTML),
    "IDCONS D2: the retired 'Survey PID' row must NOT render in the survey drawer");
  ok(!hrefs.some(h => h === "https://hdl.handle.net/survey/alpha-pid"),
    "IDCONS D2: the retired survey_pid (m.pid) must NOT render as a clickable handle link; hrefs=" + JSON.stringify(hrefs));
  ok(hrefs.some(h => h === "https://instruments.auscope.org.au/system/LEMI-423-007"),
    "PID: a good instruments[].pid did not render as a clickable <a href>; hrefs=" + JSON.stringify(hrefs));
  ok(!hrefs.some(h => /^javascript:/i.test((h || "").trim())),
    "PID: a hostile instrument pid produced an EXECUTABLE javascript: href — XSS guard failed; hrefs=" + JSON.stringify(hrefs));
  ok(hrefs.some(h => h === "https://hdl.handle.net/javascript:alert(1)"),
    "PID: the hostile instrument pid was not neutralised to the safe handle host; hrefs=" + JSON.stringify(hrefs));
  ok(!/onerror\s*=/i.test(dpid.innerHTML), "PID: an onerror= attribute leaked into the survey drawer HTML");
  // The instrument model DISPLAY line (unchanged behaviour) must still be present as text.
  ok(/LEMI 423; Phoenix MTU-5C/.test(dpid.textContent), "PID: the instrument_model display line disappeared");

  //    P2 — STATION drawer (openStation -> provGraph): the time_series collection_pid (m.ts_pid) renders
  //    as a link to https://doi.org/<ts_pid> in the provenance lineage. This proves goal 2 for
  //    collection_pid — it is a clickable link, not plain text — for a survey that declares its own ts_pid.
  dpid.classList.remove("open");
  win.location.hash = "#/station/au.alpha.A1"; A.routeFromHash();
  ok(dpid.classList.contains("open"), "PID: #/station/au.alpha.A1 did not open the station drawer");
  hrefs = [...dpid.querySelectorAll("a[href]")].map(a => a.getAttribute("href"));
  ok(hrefs.some(h => h === "https://doi.org/10.25914/alpha-timeseries"),
    "PID: collection_pid (m.ts_pid) did not render as a clickable <a href> in the station lineage; hrefs=" + JSON.stringify(hrefs));
  dpid.classList.remove("open");

  // Q. UX4 (D2) STILL COUNTED ACROSS CONTAINERS: a station moving BETWEEN the cluster group and the plain
  // AusLAMP layer must NOT drop out of the visible count or the survey selection — the partition is a
  // rendering split, not a filter. Flip Gamma's G1 (a non-member, so currently CLUSTERED) into an AusLAMP
  // member by pointing its slug at a set entry, refresh (real partitionMarkers over the Leaflet-stubbed
  // layers), and assert the visible count is unchanged and select-by-survey still picks it up. Done LAST so
  // it can't perturb earlier fixture assertions. Restores state afterward.
  drawerEl.classList.remove("open");
  A.setAuslampSet([...A.auslampSet(), "gamma"]);   // make Gamma an AusLAMP member -> G1 crosses into the plain layer
  A.setSlug("G1", "gamma");                          // G1's slug already 'gamma' via SMETA, but pin it explicitly
  A.refresh();
  ok(A.nVisCount() === 5, "moving G1 into the AusLAMP layer changed the visible count (the split must not filter), got " + A.nVisCount());
  ok(A.visIds().includes("G1"), "G1 dropped out of the visible set after crossing map containers");
  A.selectSurvey("Gamma Survey");
  ok(A.selCount() === 1, "select-by-survey did not count G1 after it moved to the AusLAMP layer, got " + A.selCount());
  A.buildAuslampSet();   // restore the boot-built set
  // Stage B (selection-state isolation): selectSurvey now ENTERS Select & export mode and scopes the tree
  // as a temporary lens. Return to Browse here so the following sections start from the default mode and an
  // un-scoped tree (the restore hook puts the tree back); mirrors the section-CC tree reset below.
  A.setSidebarMode("browse");

  // R. THE ABSTRACT LIVES IN THE RECORD, NOT ON THE CARD (C2, brief 4/6). The survey.yaml abstract used
  // to render as a 12px muted italic block on every card, which made a grid of cards a wall of prose and
  // pushed the facts a reader scans for below the fold. It is REMOVED from the card and stays where a
  // reader who has chosen a survey meets it: the drawer story view here, and the static survey page,
  // which the engine suite pins separately (engine/tests/test_entity_pages.py, "the survey blurb prose
  // must render"). Pins moved from the card to the drawer per contract section 1, C2: "the abstract
  // remains in the drawer story view and on the survey page (assert both still render it)".
  // (a) the CARD carries no description block at all - not the abstract, not a fallback line.
  A.setBlurb("Alpha Survey", "A regional MT survey across the Gawler Craton.");
  const cardWithBlurb = A.cardHtml("Alpha Survey");
  ok(cardWithBlurb.indexOf('class="desc') < 0,
    "C2: the card must carry no .desc block, got: " +
    JSON.stringify((cardWithBlurb.match(/.{0,40}class="desc.{0,60}/) || [""])[0]));
  ok(cardWithBlurb.indexOf("A regional MT survey across the Gawler Craton.") < 0,
    "C2: the abstract must not render on the card");
  ok(cardWithBlurb.indexOf("No survey description provided") < 0,
    "C2: the card's absent-abstract fallback line goes with the block it belonged to");
  ok(typeof A.cardDesc === "undefined",
    "C2: cardDesc had exactly one call site (the card) and must not be left behind as dead code");
  // (b) the DRAWER STORY VIEW still renders the abstract, which is the surface the card handed it to.
  A.openSurvey("Alpha Survey");
  ok(doc.getElementById("drawer").textContent.indexOf("A regional MT survey across the Gawler Craton.") >= 0,
    "C2: the survey drawer must still render the survey.yaml abstract");
  // (c) HOSTILE-BLURB XSS, moved to the surface that now renders it: an abstract carrying an
  //     <img onerror=...> must be escaped to inert text - no live tag, no live handler, literal text kept.
  const XSS = "<img src=x onerror=\"window.__pwned=1\">pwn";
  A.setBlurb("Alpha Survey", XSS);
  A.openSurvey("Alpha Survey");
  const drwX = doc.getElementById("drawer");
  ok(drwX.querySelector("img[src='x']") === null, "hostile blurb produced a LIVE <img> element (XSS not neutralised)");
  ok(drwX.querySelector("[onerror]") === null, "hostile blurb left a live onerror handler");
  ok(drwX.textContent.indexOf("pwn") >= 0, "escaped hostile blurb should still show its literal text");
  ok(win.__pwned === undefined, "hostile blurb executed script (window.__pwned was set)");
  A.setBlurb("Alpha Survey", null);
  doc.getElementById("drawer").classList.remove("open");

  // S. DIMENSIONALITY HIDDEN FROM SCREENING DISPLAYS (UX feedback round 3, item 7): removed from the
  // station-drawer screening grid (7a), the survey-card stats line (7b) and the survey-story table (7c) —
  // while the phase-tensor/skew and strike lines STAY (dimensionality is inferable from them).
  // (a) station drawer: no "Dimensionality" cell. (OWNER HIDE 2026-07-22: the strike + mean-|β| lines lived
  //     ONLY in the now-hidden Screening panel, so they are ABSENT too — flipped from the prior "KEPT" pins.
  //     Restore the strike/|β| "KEPT" assertions when the Screening surface is re-enabled.)
  win.location.hash = "#/station/au.beta.B1"; A.routeFromHash();
  const drw = doc.getElementById("drawer");
  ok(drw.innerHTML.indexOf(">Dimensionality<") < 0, "station drawer still shows a 'Dimensionality' screening cell (item 7a)");
  ok(drw.textContent.indexOf("phase-tensor strike") < 0,
    "OWNER HIDE: the strike line must be absent while the Screening panel is owner-hidden");
  ok(drw.innerHTML.indexOf("Screening indicators") < 0,
    "OWNER HIDE: the Screening panel prose must be absent while screening is hidden");
  drw.classList.remove("open");
  // (b) survey card stats line: no "N×3-D / N×2-D / N×1-D" fragment.
  ok(A.cardHtml("Beta Survey").indexOf("×3-D") < 0 && A.cardHtml("Beta Survey").indexOf("x3-D") < 0,
    "survey card stats line still shows the N×3-D/2-D/1-D dimensionality fragment (item 7b)");
  // (c) survey-story summary table: no "dimensionality mix" row, but tipper/remote-reference rows remain.
  const sum = A.summaryHtml("Beta Survey");
  ok(sum.indexOf("dimensionality mix") < 0, "survey-story table still shows the 'dimensionality mix' row (item 7c)");
  ok(sum.indexOf("tipper availability") >= 0 && sum.indexOf("remote reference") >= 0,
    "survey-story table lost sibling rows that must be KEPT (tipper/remote reference)");

  // T. C20 TF COMPLETENESS — induction-arrow panel (D3) + error bars (D4), in the station drawer.
  //   A1: tzx_re>0 (only), rho+phase errors present  -> arrow panel with the Parkinson label, a REAL
  //       arrow pointing SOUTH (Parkinson north = -tzx_re < 0), and error-bar whiskers on ρ/φ.
  //   A2: no tipper, no errors                        -> "no tipper" state (no arrow panel) + no bars.
  const drwC = doc.getElementById("drawer");
  drwC.classList.remove("open");
  win.location.hash = "#/station/au.alpha.A1"; A.routeFromHash();
  ok(drwC.classList.contains("open"), "C20: #/station/au.alpha.A1 did not open the drawer");
  // (a) arrow panel EXISTS. C20 Amendment A1 (UX6 Wave C / owner decision D4): the verbatim one-line panel
  // label is superseded by a short heading + an ALWAYS-VISIBLE convention subline. BOTH must be asserted so
  // the convention sentence can never silently vanish later (it moved into the subline, it did not go away).
  ok(drwC.innerHTML.indexOf("Induction arrows (Parkinson)") >= 0,
    "C20 A1: the induction-arrow panel heading 'Induction arrows (Parkinson)' is missing from the drawer");
  ok(drwC.innerHTML.indexOf("Real arrows point toward conductors; imaginary unreversed.") >= 0,
    "C20 A1: the always-visible convention subline ('Real arrows point toward conductors; imaginary unreversed.') is missing");
  ok(drwC.innerHTML.indexOf("tipper magnitude |T|") < 0,
    "C20 D3: the old |T|-magnitude plot title is still present (panel was not replaced)");
  ok(drwC.innerHTML.indexOf("|T|=0.5") >= 0, "C20 D3: the |T|=0.5 unit-scale reference is missing");
  // (b) SIGN MAPPING: parse the REAL arrow <line>s (solid copper #EF7256) inside the drawer. tzx_re>0
  // means real north = -tzx_re < 0, so every real arrow must point DOWN (screen y2 > y1 = SOUTH) with
  // no east deflection (x2 == x1, since tzy_re == 0). This is the D3 falsifiability check.
  // Match ONLY the arrow-panel REAL arrows: solid copper at the arrow stroke-width "1.2" (error bars use
  // "0.8"+opacity and the imaginary arrows use "1.0", so this excludes both).
  const realArrows = [...drwC.innerHTML.matchAll(/<line x1="([\d.]+)" y1="([\d.]+)" x2="([\d.]+)" y2="([\d.]+)" stroke="#EF7256" stroke-width="1\.2"/g)];
  ok(realArrows.length >= 1, "C20 D3: no REAL (copper) induction arrows rendered for a tippered station");
  ok(realArrows.every(m => parseFloat(m[4]) > parseFloat(m[2])),
    "C20 D3 SIGN: a REAL arrow for tzx_re>0 must point SOUTH (y2>y1); got " +
    JSON.stringify(realArrows.map(m => [m[2], m[4]])));
  ok(realArrows.every(m => Math.abs(parseFloat(m[3]) - parseFloat(m[1])) < 0.1),
    "C20 D3 SIGN: a REAL arrow with tzy_re=0 must have no east deflection (x2==x1); got " +
    JSON.stringify(realArrows.map(m => [m[1], m[3]])));
  // (c) ERROR BARS present for A1 (rho copper #EF7256 + teal #2E8FA3 whiskers with the .55 opacity).
  ok(/<line [^>]*stroke="#EF7256" stroke-width=".8" stroke-opacity=".55"/.test(drwC.innerHTML) ||
     /<line [^>]*stroke="#2E8FA3" stroke-width=".8" stroke-opacity=".55"/.test(drwC.innerHTML),
    "C20 D4: error bars did not render for a station WITH errors");
  // (d) A2: no tipper => NO arrow panel; no errors => NO error bars.
  drwC.classList.remove("open");
  win.location.hash = "#/station/au.alpha.A2"; A.routeFromHash();
  ok(drwC.classList.contains("open"), "C20: #/station/au.alpha.A2 did not open the drawer");
  // C20 A1: the no-tipper state renders NO arrow panel — so neither the heading nor the convention subline appears.
  ok(drwC.innerHTML.indexOf("Induction arrows (Parkinson)") < 0 &&
     drwC.innerHTML.indexOf("Real arrows point toward conductors; imaginary unreversed.") < 0,
    "C20 A1: a tipperless station must show the no-tipper state (no arrow panel heading or convention subline)");
  ok(!/stroke-width=".8" stroke-opacity=".55"/.test(drwC.innerHTML),
    "C20 D4: a station WITHOUT errors must render NO error bars");
  // A2 still plots ρ/φ/phase-tensor (the curves themselves), proving (c)/(d) are about bars/arrows only.
  ok(drwC.querySelectorAll("svg path").length > 0, "C20: a no-tipper/no-error open station must still plot ρ/φ curves");
  drwC.classList.remove("open");

  // T2. PT + INDUCTION ARROWS ALWAYS SHOWN (owner requirement). The phase tensor and induction arrows must
  // ALWAYS be shown when the station carries that data — never collapsed by default and with NO
  // collapse/minimise control the user could hide them with. Pre-change both were plotCollapsible() —
  // <details class="plotcollapse"> panels, collapsed by default and user-hideable; now they are plotBlock()
  // always-shown <div class="plot"> blocks. The empty-svg absence guard is preserved: an UNCOLLECTED panel
  // stays ABSENT (no empty box). This section RED-proves the swap: on the old <details> markup the
  // `div.plot[data-plot=...]` selectors below find nothing.
  //   A1 (tipper + pt): both blocks shown, as divs, with no <details>; sublines + expand affordance kept.
  //   A2 (pt, no tipper): pt block shown, arrow block ABSENT (empty-svg guard, no empty box).
  //   D1 (embargoed — neither collected): neither block renders.
  win.location.hash = "#/station/au.alpha.A1"; A.routeFromHash();
  ok(drwC.classList.contains("open"), "PTIA: #/station/au.alpha.A1 did not open the drawer");
  // (a) both panels are always-shown <div class="plot"> blocks, NOT <details>, and no collapse control survives.
  ok(drwC.querySelector('div.plot[data-plot="pt"]'),
    "PTIA a: the phase tensor must render as an always-shown div.plot block, not a collapsible");
  ok(drwC.querySelector('div.plot[data-plot="arrow"]'),
    "PTIA a: the induction arrows must render as an always-shown div.plot block, not a collapsible");
  ok(drwC.querySelectorAll("details.plotcollapse").length === 0,
    "PTIA a: no collapsible <details.plotcollapse> plot may remain (pt/arrow must not be hideable)");
  ok(!drwC.querySelector('details[data-plot="pt"], details[data-plot="arrow"]'),
    "PTIA a: neither the phase tensor nor the induction arrows may sit inside a <details> collapse control");
  // convention sublines survive VISIBLY (they moved from the <summary> into the always-shown .psubline).
  ok(drwC.innerHTML.indexOf("axis = azimuth, fill = skew β") >= 0,
    "PTIA a: the phase-tensor convention subline must survive on the always-shown block");
  ok(drwC.innerHTML.indexOf("Real arrows point toward conductors; imaginary unreversed.") >= 0,
    "PTIA a: the induction-arrow convention subline must survive on the always-shown block");
  // OWNER DIRECTIVE 2026-07-28: the PER-PLOT expand affordance is gone. Every block carried its own ⤢
  // button and all four opened the SAME full-station modal; the response section now carries exactly one
  // control, on its heading row (pinned in section V (h)). RED on stage-1 HEAD, where both blocks have one.
  ok(!drwC.querySelector('div.plot[data-plot="pt"] [data-act="expand"]') &&
     !drwC.querySelector('div.plot[data-plot="arrow"] [data-act="expand"]'),
    "PTIA a: no plot block may carry its own expand control (the response section has ONE, on its heading)");
  // (d) the #pt_anchor scroll target still exists so the related-product quick-link scroll lands.
  ok(drwC.querySelector("#pt_anchor"),
    "PTIA d: the #pt_anchor scroll target must remain in the Response tab");
  // (c) A2: pt present, NO tipper -> pt block shown, arrow block ABSENT (empty-svg guard, no empty box).
  drwC.classList.remove("open");
  win.location.hash = "#/station/au.alpha.A2"; A.routeFromHash();
  ok(drwC.classList.contains("open"), "PTIA: #/station/au.alpha.A2 did not open the drawer");
  ok(drwC.querySelector('div.plot[data-plot="pt"]'),
    "PTIA c: A2 (pt present, no tipper) must still show the always-shown phase-tensor block");
  ok(!drwC.querySelector('[data-plot="arrow"]'),
    "PTIA c: A2 has no tipper -> the induction-arrow block must be ABSENT (empty-svg guard, no empty box)");
  // (b) D1 (embargoed — collected NEITHER): neither block renders (curves are withheld; no empty box).
  drwC.classList.remove("open");
  win.location.hash = "#/station/au.delta.D1"; A.routeFromHash();
  ok(drwC.classList.contains("open"), "PTIA: #/station/au.delta.D1 did not open the drawer");
  ok(!drwC.querySelector('[data-plot="pt"]') && !drwC.querySelector('[data-plot="arrow"]'),
    "PTIA b: a station that collected NEITHER pt nor tipper must render neither block (absent, no empty box)");
  drwC.classList.remove("open");

  // U. C22 CITATION HONESTY (chief-architect ruling 2026-07-07; pre-release hostile-review finding
  // 2026-07-06 — state.js publisher placeholder). A NO-DOI survey's
  // generated .bib/.ris must carry NO placeholder text a reference manager would ingest as real: the
  // pre-C22 AUSMT_SELF.pb publisher read "AusMT (DOI to be minted per release via Zenodo)" and leaked
  // into EVERY no-DOI citation's publisher/PB field (the doi=/DO/UR FIELDS were already guarded by
  // d2bc616's `${doi?...:""}` — the leak was the publisher STRING, not the DOI field). A WITH-DOI
  // survey keeps its real DOI in both formats; the NCI/TS-collection entries are BYTE-pinned to their
  // pre-C22 output; and the human-readable CITATIONS.txt line for a no-DOI entry SAYS
  // "[no DOI assigned]" explicitly (exports.js citeLine — net-new in C22, sanctioned by the ruling).
  //
  // NOTE (Invariant 10): section U asserts the ASSEMBLY HELPERS (apa/bibtex/ris/citeLine) directly —
  // the exact functions the #dlCite click handler feeds into the pack — NOT the zipped file itself:
  // win.JSZip is a STUB in this harness (it swallows z.file() contents), so any "the shipped zip is
  // clean" claim routed through a #dlCite click here would be a vacuous test of the stub.
  const PLACEHOLDER = "DOI to be minted";
  // (a) NO-DOI survey — Beta has neither cite nor doi in the fixture; this is the EXACT call shape of
  //     the per-survey loop in exports.js dlCite (m.cite||AUSMT_SELF, m.doi).
  const mBeta = A.smeta("Beta Survey") || {};
  ok(mBeta.doi === undefined && mBeta.cite === undefined,
    "U: fixture drift — Beta Survey must stay a no-cite/no-DOI survey for the no-DOI leg");
  const bibNo = A.bibtex("beta_survey", mBeta.cite || A.AUSMT_SELF, mBeta.doi);
  const risNo = A.ris(mBeta.cite || A.AUSMT_SELF, mBeta.doi);
  ok(bibNo.indexOf(PLACEHOLDER) < 0, "U: a no-DOI survey's .bib carries the placeholder string ('" + PLACEHOLDER + "'):\n" + bibNo);
  ok(risNo.indexOf(PLACEHOLDER) < 0, "U: a no-DOI survey's .ris carries the placeholder string ('" + PLACEHOLDER + "'):\n" + risNo);
  ok(!/\bdoi\s*=/.test(bibNo), "U: a no-DOI survey's .bib must have NO doi= line:\n" + bibNo);
  ok(!/^DO  - /m.test(risNo) && !/^UR  - /m.test(risNo), "U: a no-DOI survey's .ris must have NO DO/UR lines:\n" + risNo);
  // (b) catalogue-level self-citation (exports.js passes AUSMT_SELF with doi=null).
  const bibSelf = A.bibtex("ausmt_catalogue", A.AUSMT_SELF, null);
  const risSelf = A.ris(A.AUSMT_SELF, null);
  ok(bibSelf.indexOf(PLACEHOLDER) < 0, "U: the catalogue self-citation .bib carries the placeholder:\n" + bibSelf);
  ok(risSelf.indexOf(PLACEHOLDER) < 0, "U: the catalogue self-citation .ris carries the placeholder:\n" + risSelf);
  ok(!/\bdoi\s*=/.test(bibSelf) && !/^DO  - /m.test(risSelf),
    "U: the catalogue self-citation must fabricate no DOI field");
  // (c) WITH-DOI survey keeps its real DOI in BOTH formats (Alpha carries doi+cite in the fixture).
  const mAlpha = A.smeta("Alpha Survey") || {};
  ok(mAlpha.doi === "10.99999/alpha-tf-doi",
    "U: fixture drift — Alpha Survey must carry the with-DOI fixture doi, got " + JSON.stringify(mAlpha.doi));
  const bibW = A.bibtex("alpha_survey", mAlpha.cite || A.AUSMT_SELF, mAlpha.doi);
  const risW = A.ris(mAlpha.cite || A.AUSMT_SELF, mAlpha.doi);
  ok(bibW.indexOf("doi       = {10.99999/alpha-tf-doi},") >= 0, "U: the with-DOI .bib lost its real doi= line:\n" + bibW);
  ok(risW.indexOf("DO  - 10.99999/alpha-tf-doi") >= 0 && risW.indexOf("UR  - https://doi.org/10.99999/alpha-tf-doi") >= 0,
    "U: the with-DOI .ris lost its real DO/UR lines:\n" + risW);
  // (d) NCI/TS-collection entries BYTE-untouched — pinned to the output of the pre-C22 helpers at
  //     cbb7a88 (generated, not hand-typed). A single changed byte in either entry fails here.
  ok(A.TS_COLLECTION.doi === "10.25914/mtjg-jp22", "U: TS_COLLECTION.doi drifted from 10.25914/mtjg-jp22");
  const NCI_BIB_PIN = "@misc{nci_auscope_mt,\n  author    = {AuScope and NCI Australia},\n  title     = {NCI-AuScope Magnetotelluric Collection — packed raw, Level 1 and Level 2 time series},\n  year      = {n.d.},\n  publisher = {NCI Australia},\n  doi       = {10.25914/mtjg-jp22},\n  note      = {Accessed via the AusMT portal}\n}";
  const NCI_RIS_PIN = "TY  - DATA\nAU  - AuScope\nAU  - NCI Australia\nTI  - NCI-AuScope Magnetotelluric Collection — packed raw, Level 1 and Level 2 time series\nPY  - \nPB  - NCI Australia\nDO  - 10.25914/mtjg-jp22\nUR  - https://doi.org/10.25914/mtjg-jp22\nER  -";
  ok(A.bibtex("nci_auscope_mt", A.NCI_CITE, A.TS_COLLECTION.doi) === NCI_BIB_PIN,
    "U: the NCI .bib entry changed byte(s) vs the pre-C22 pin:\n" + A.bibtex("nci_auscope_mt", A.NCI_CITE, A.TS_COLLECTION.doi));
  ok(A.ris(A.NCI_CITE, A.TS_COLLECTION.doi) === NCI_RIS_PIN,
    "U: the NCI .ris entry changed byte(s) vs the pre-C22 pin:\n" + A.ris(A.NCI_CITE, A.TS_COLLECTION.doi));
  // (e) CITATIONS.txt honesty: the no-DOI line SAYS SO explicitly; the with-DOI line carries the real
  //     DOI URL and NO note. On pre-C22 code citeLine does not exist — the lazy api hook throws
  //     ReferenceError right here, which is this leg's RED.
  const lineNo = A.citeLine(A.AUSMT_SELF, null);
  ok(lineNo.indexOf("[no DOI assigned]") >= 0,
    "U: the no-DOI CITATIONS.txt line must say [no DOI assigned], got: " + lineNo);
  ok(lineNo.indexOf(PLACEHOLDER) < 0, "U: the no-DOI CITATIONS.txt line still carries the placeholder: " + lineNo);
  const lineW = A.citeLine(mAlpha.cite, mAlpha.doi);
  ok(lineW.indexOf("https://doi.org/10.99999/alpha-tf-doi") >= 0 && lineW.indexOf("no DOI assigned") < 0,
    "U: the with-DOI CITATIONS.txt line must carry the DOI URL and no note, got: " + lineW);

  // V. UX6 WAVE C — station drawer tabs (C1) + section-role chips (C2) + plot readability/expand (C3).
  //    Every pin states its failure criterion up front.
  const drwV = doc.getElementById("drawer");
  drwV.classList.remove("open");
  win.location.hash = "#/station/au.alpha.A1"; A.routeFromHash();
  ok(drwV.classList.contains("open"), "WaveC: the A1 drawer did not open");

  // (a) UX8 (X4): FOUR tabs, each role=tab, in the mandated order. (OWNER HIDE 2026-07-22: the Screening tab is
  //     reversibly commented out in drawer.js pending design review, so the count is 4, "screening" is absent
  //     from the order AND the DOM. Restore the 5-tab order + the Screening click test below when re-enabled.)
  //     FAILS if a tab is missing, mis-roled, reordered, or if the retired Overview tab reappears.
  const tabsV = [...drwV.querySelectorAll('[role="tab"]')];
  ok(tabsV.length === 4, "C1/X4: expected 4 role=tab buttons (Overview folded away, Screening owner-hidden), got " + tabsV.length);
  const wantTabs = ["response", "files", "provenance", "cite"];
  ok(wantTabs.every((n, k) => tabsV[k] && tabsV[k].dataset.tab === n),
    "C1/X4: tab order/ids drifted from Response/Files/Provenance/Cite, got " +
    JSON.stringify(tabsV.map(t => t.dataset.tab)));
  ok(drwV.querySelector('#dt-screening') == null && drwV.querySelector('#dp-screening') == null,
    "OWNER HIDE: the Screening tab/panel must be ABSENT (owner-hidden pending design review)");
  ok(drwV.querySelector('#dt-overview') == null && drwV.querySelector('#dp-overview') == null,
    "X4: the Overview tab/panel must be GONE (folded into the Response tab's Station summary)");
  ok(drwV.querySelector('[role="tablist"]') != null, "C1: no role=tablist container in the drawer");

  // (b) UX8 (X4): Response is DEFAULT-selected; its panel is visible, the others hidden. FAILS if another
  //     tab wins (e.g. a revert to the Overview-default).
  // (OWNER HIDE 2026-07-22: the Screening tab is hidden, so the "non-Response hidden by default" check now
  // rides the Files tab instead of Screening.)
  const rsTab = drwV.querySelector('#dt-response'), filesTab = drwV.querySelector('#dt-files');
  const rsPanel = drwV.querySelector('#dp-response'), filesPanel = drwV.querySelector('#dp-files');
  ok(rsTab.getAttribute("aria-selected") === "true", "X4: the Response tab must be aria-selected by default");
  ok(rsPanel && rsPanel.hidden === false, "X4: the Response panel must be visible by default");
  ok(filesPanel && filesPanel.hidden === true, "X4: non-Response panels must be hidden by default");

  // (c) UX8 (X4): the Response tab leads with the plots (an OPEN station renders svg plot paths there), and
  //     the former Overview facts live in a collapsible "Station summary" <details> UNDER the plots — not a
  //     leading meta strip. FAILS if the plots aren't first, or the Station summary fold is missing.
  ok(rsPanel.querySelectorAll("svg path").length > 0, "X4: the Response panel must render the plots (svg paths)");
  const ssDetails = [...rsPanel.querySelectorAll("details")].find(d => d.querySelector("summary") && /Station summary/.test(d.querySelector("summary").textContent));
  ok(ssDetails, "X4: the Response tab must carry a collapsible 'Station summary' <details>");
  // the fold sits AFTER the first plot (plots lead), and carries the owner's four group headers.
  const firstPlot = rsPanel.querySelector(".plot");
  ok(firstPlot && (firstPlot.compareDocumentPosition(ssDetails) & win.Node.DOCUMENT_POSITION_FOLLOWING),
    "X4: the Station summary fold must come AFTER the plots (plots are the centerpiece)");
  // R4: the "Data checks" group (the TF error row) is removed; the Station summary now carries three groups.
  ["Station", "Transfer function", "Processing"].forEach(g =>
    ok([...ssDetails.querySelectorAll(".ssg-h")].some(h => h.textContent === g),
      "X4: the Station summary is missing the '" + g + "' group header"));
  ok([...ssDetails.querySelectorAll(".ssg-h")].every(h => h.textContent !== "Data checks"),
    "R4: the Station summary must NOT carry the removed 'Data checks' group");
  ok(ssDetails.innerHTML.indexOf("TF error") < 0, "R4: the removed 'TF error' row must be gone");
  // SURVEY-DRAWER LANE, amendment 2 (owner): the "Transfer function / Download" TILE is removed from the
  // Station summary - it duplicated the Files tab's Level 2 EDI row and blurred the summary-vs-downloads
  // separation. The summary states facts; the Files tab serves bytes. The EDI itself is untouched: it is
  // still offered by the sticky-header action and the Files tab, both asserted below.
  ok(!ssDetails.querySelector(".prodgrid") && !ssDetails.querySelector(".prod"),
    "amendment 2: the Station summary must carry NO download tile:\n" + ssDetails.innerHTML);
  ok(!/Transfer function<small>/.test(ssDetails.innerHTML),
    "amendment 2: the 'Transfer function' download tile must be gone from the Station summary");
  ok(ssDetails.innerHTML.indexOf("data-prod=") < 0 && ssDetails.innerHTML.indexOf("data-avail=") < 0,
    "amendment 2: no download affordance may remain in the Station summary");
  // NOT a regression in disguise: the EDI is still downloadable from the surface that owns the action.
  ok(doc.querySelector("#drawer .dl-edi"),
    "amendment 2: removing the summary tile must NOT remove the sticky-header Download EDI action");
  // R4: the Station group ADDS rows — data type, ausmt_id, and (A1 carries site_name 'A_1' != id 'A1')
  // the "site name" row. The collection row is omitted here (Alpha is in the AusLAMP collection, so it
  // renders); ausmt_id is always present.
  const ssRows = [...ssDetails.querySelectorAll("tr")].map(tr => tr.textContent);
  ok(ssRows.some(t => /site name/.test(t) && /A_1/.test(t)),
    "R4: A1 (site_name 'A_1' != id) must render the 'site name' row, got rows: " + JSON.stringify(ssRows));
  ok(ssRows.some(t => /data type/.test(t) && /BBMT/.test(t)), "R4: the Station summary must carry the 'data type' row");
  ok(ssRows.some(t => /ausmt_id/.test(t) && /au\.alpha\.A1/.test(t)), "R4: the Station summary must carry the 'ausmt_id' row");
  ok(ssRows.some(t => /collection/.test(t) && /AusLAMP/.test(t)), "R4: an in-collection station must carry the 'collection' row");

  // R5: the Files tab is restructured to the NCI data-level standard as a SINGLE COLUMN (.filelist, not the
  // 2-col .prodgrid), ordered raw -> Level 0 -> Level 1 -> Level 2 (EDI/EMTF XML/MTH5 sub-rows) ->
  // Publication (interpretation); the Phase tensor tile is gone; each product row carries an origin tag.
  const filesHtmlV = filesPanel.innerHTML;
  ok(filesPanel.querySelector(".filelist") != null && filesPanel.querySelector(".prodgrid") == null,
    "R5: the Files tab must be a single-column .filelist, not the 2-col .prodgrid");
  ["Raw time series", "Level 0 edited time series", "Level 1 transformed time series",
   "Level 2 derived processed data", "EDI", "EMTF XML", "MTH5", "Publication (interpretation)"].forEach(lbl =>
    ok(filesHtmlV.indexOf(lbl) >= 0, "R5: the Files tab is missing the '" + lbl + "' row"));
  ok(filesHtmlV.indexOf("Phase tensor") < 0, "R5: the Phase tensor tile must be removed from the Files tab");
  ok(filesHtmlV.indexOf("source archive") >= 0 && filesHtmlV.indexOf("AusMT-derived") >= 0,
    "R5: each Files row must carry an origin tag (source archive / AusMT-derived)");

  // R7: no "(no PID)" / "not recorded" noise anywhere in the station drawer.
  ok(drwV.innerHTML.indexOf("(no PID)") < 0, "R7: the station drawer must not render any '(no PID)' suffix");
  // R6: em-dash sweep on the station drawer's rendered text (all panels render at open, so hidden ones are
  // swept too). A full-document textContent sweep runs at the end of this test.
  ok(drwV.textContent.indexOf("—") < 0,
    "R6: an em dash (—) rendered in the station drawer text: " +
    JSON.stringify((drwV.textContent.match(/.{0,24}—.{0,24}/) || [""])[0]));

  // (d) the sticky-header primary action: Download EDI (open station). R1: the redundant header Cite
  //     tab-jump button (.dl-cite) is removed — the Cite TAB reaches the same panel.
  ok(drwV.querySelector(".dtop .dl-edi") != null, "C1: an open station must offer a Download EDI action in the sticky header");
  ok(drwV.querySelector(".dtop .dl-cite") == null, "R1: the redundant header Cite button (.dl-cite) must be removed");

  // (e) clicking a non-default tab activates it (roving tabindex + hidden toggle); switching back restores
  //     Response. (OWNER HIDE 2026-07-22: this rode the Screening tab; it now rides Files while Screening is
  //     hidden — restore the Screening target when the tab is re-enabled.)
  fire(filesTab, "click");
  ok(filesPanel.hidden === false && rsPanel.hidden === true,
    "C1: clicking the Files tab did not activate its panel / hide Response");
  ok(filesTab.getAttribute("aria-selected") === "true" && rsTab.getAttribute("aria-selected") === "false",
    "C1: aria-selected did not move to Files on click");
  fire(rsTab, "click");   // restore Response default for later helpers

  // (f) C2: section-role chips render with the engine taxonomy (muted, plain text). (OWNER HIDE 2026-07-22:
  //     the "Automated screening" role chip lived ONLY on the now-hidden Screening panel, so the drawer now
  //     carries the two surviving labels; assert its ABSENCE and restore the third when the tab returns.)
  ok(drwV.querySelector(".rolechip") != null, "C2: no section-role chips (.rolechip) rendered");
  ok(drwV.innerHTML.indexOf("Source data") >= 0 && drwV.innerHTML.indexOf("AusMT-derived") >= 0,
    "C2: the surviving role-chip taxonomy labels (Source data / AusMT-derived) are not both present");
  ok(drwV.innerHTML.indexOf("Automated screening") < 0,
    "OWNER HIDE: the 'Automated screening' role chip must be absent (it rode the owner-hidden Screening panel)");

  // (g) C3: marker-shape differentiation — the yx series draws <rect> squares, the xy series keeps <circle>.
  //     FAILS if both series share a marker glyph again (colour-only differentiation). Colours stay frozen.
  const rspHtml = drwV.querySelector('#dp-response').innerHTML;
  ok(/<rect [^>]*fill="#2E8FA3"/.test(rspHtml),
    "C3: the yx (teal #2E8FA3) series must render <rect> square markers (shape differentiation)");
  ok(/<circle [^>]*fill="#EF7256"/.test(rspHtml),
    "C3: the xy (copper #EF7256) series must keep <circle> markers");

  // (h) C3 (evolved) + OWNER DIRECTIVE 2026-07-28: ONE EXPAND CONTROL + a CAPPED MODAL.
  //     Pre-change EVERY plot block carried its own ⤢ button (FOUR of them in the response section) and all
  //     four opened the SAME full-station modal, whose panels were rendered at a fixed 2x pixel blow-up
  //     (STATION_MODAL_SCALE: the rho svg went out at width="744"). Now the section carries EXACTLY ONE
  //     control, on the "Response functions" heading row, with ZERO inside the plot blocks; it opens the
  //     same #plotmodal (station-identity header plus ALL response panels: apparent resistivity, phase,
  //     phase tensor and, since A1 carries tipper, the induction arrows); the modal's content column
  //     carries the capped-width class .plotmodal-capw; and the panels are emitted at DESIGN size to be
  //     CSS-stretched to fill that cap. Esc / click-out / the close button close it WITHOUT closing the
  //     drawer, and focus returns to the opener.
  //     Every leg is RED on stage-1 HEAD: the control count is 4 not 1, the heading carries none, the
  //     .plotmodal-capw class does not exist, and the modal rho svg is 744 wide.
  //     NOTE on the cap: jsdom does no layout, so the WIDTH itself cannot be measured here. What is pinned
  //     is the contract that produces it: the class on the box, plus the index.html rules that cap the
  //     column and stretch the svg to fill it (asserted against the stylesheet source, not a computed box).
  ok(doc.getElementById("plotmodal") == null, "C3: no plot modal should be open before the expand click");
  const rspPanelV = drwV.querySelector("#dp-response");
  const rspExpandAll = [...rspPanelV.querySelectorAll('[data-act="expand"]')];
  ok(rspExpandAll.length === 1,
    "C3/ONE-EXPAND: the response section must carry EXACTLY ONE expand control (the four per-plot buttons " +
    "are removed), got " + rspExpandAll.length);
  ok(rspPanelV.querySelectorAll('.plot [data-act="expand"]').length === 0,
    "C3/ONE-EXPAND: no expand control may live INSIDE a plot block");
  const rhoExpand = rspPanelV.querySelector('.sechead [data-act="expand"]');
  ok(rhoExpand != null && rhoExpand === rspExpandAll[0],
    "C3/ONE-EXPAND: the single expand control must sit on the 'Response functions' section heading row");
  ok(rhoExpand.tagName === "BUTTON" &&
     /expand/i.test(rhoExpand.getAttribute("aria-label") || ""),
    "C3/ONE-EXPAND: the section control must be a <button> carrying an accessible expand label (keyboard " +
    "reachable, Enter/Space activated), got " + rhoExpand.tagName + " / " +
    JSON.stringify(rhoExpand.getAttribute("aria-label")));
  if (rhoExpand.focus) rhoExpand.focus();
  fire(rhoExpand, "click");
  const modal = doc.getElementById("plotmodal");
  ok(modal != null, "C3: clicking the section expand control did not open the full-station response modal");
  // ALL FOUR response panels are present as scaled .plot blocks (A1 carries tipper, so the arrow panel too).
  ["rho", "phase", "pt", "arrow"].forEach(k =>
    ok(modal.querySelector('.plot[data-plot="' + k + '"]') != null,
      "C3: the full-station modal is missing the '" + k + "' response panel (was a single-plot popup?)"));
  // ...each with its panel TITLE (the convention text is rendered VISIBLY, not hover-only).
  ["apparent resistivity", "phase φ", "phase tensor", "Induction arrows (Parkinson)"].forEach(title =>
    ok(modal.innerHTML.indexOf(title) >= 0,
      "C3: the full-station modal is missing the '" + title + "' panel title"));
  // CAPPED, RESPONSIVE SIZING. The content column carries .plotmodal-capw, whose index.html rule is the
  // cap (min(<vw>,~760px): centred by the overlay flex, with the overlay's viewport margin), and the panels
  // go out at DESIGN size (372) with the design viewBox, to be stretched to width:100% of that column.
  // A regression to the fixed 2x blow-up (width="744") or a dropped cap fails here.
  const modalBox = modal.querySelector(".plotmodal-box");
  ok(modalBox != null && modalBox.classList.contains("plotmodal-capw"),
    "C3/CAP: the modal content column must carry the capped-width class .plotmodal-capw, got class=" +
    JSON.stringify(modalBox && modalBox.className));
  const capRule = /\.plotmodal-capw\s*\{([^}]*)\}/.exec(html);
  ok(capRule != null, "C3/CAP: index.html declares no .plotmodal-capw rule (nothing caps the modal column)");
  const capPx = capRule && /max-width:\s*min\(\s*\d+vw\s*,\s*(\d+)px\s*\)/.exec(capRule[1]);
  ok(capPx != null && +capPx[1] >= 700 && +capPx[1] <= 800,
    "C3/CAP: .plotmodal-capw must cap the column at a sane px width (700-800) with a vw ceiling for small " +
    "viewports, got: " + (capRule ? capRule[1] : "no rule"));
  const svgRule = /\.plotmodal-svg svg\s*\{([^}]*)\}/.exec(html);
  ok(svgRule != null && /(^|;)\s*width:\s*100%/.test(svgRule[1]),
    "C3/CAP: the modal panels must FILL the capped column (.plotmodal-svg svg{width:100%}), got: " +
    (svgRule ? svgRule[1] : "no rule"));
  ok(svgRule != null && /min-width:\s*372px/.test(svgRule[1]),
    "C3/CAP: the modal svg needs the 372px design-width floor so axis/label text never renders SMALLER " +
    "than in the drawer (the container scrolls instead), got: " + (svgRule ? svgRule[1] : "no rule"));
  const modalSvg = modal.querySelector('.plot[data-plot="rho"] svg');
  ok(modalSvg != null, "C3: the modal rho panel did not re-render an SVG");
  ok(modalSvg.getAttribute("width") === "372",
    "C3/CAP: the modal panels must go out at DESIGN size and be CSS-stretched to the cap, not blown up to a " +
    "fixed 2x pixel size, got width=" + modalSvg.getAttribute("width"));
  ok(modalSvg.getAttribute("viewBox") === "0 0 372 118",
    "C3: the modal rho svg must keep the design viewBox (it is what makes the CSS stretch responsive), got " +
    modalSvg.getAttribute("viewBox"));
  // HEADER FIELDS: station id, its differing site name, survey, organisation, the data-type chip, and the
  // HONEST coordinate line (coordCellHtml). A1 is an EXACT station, so its 6-dp position renders verbatim.
  const modalHead = modal.querySelector(".plotmodal-head");
  ok(modalHead != null, "C3: the full-station modal has no identity header (.plotmodal-head)");
  const sidEl = modalHead.querySelector(".pm-id .sid");
  ok(sidEl != null && sidEl.textContent === "A1",
    "C3: the modal header must carry the station id (A1) in .sid, got: " + JSON.stringify(sidEl && sidEl.textContent));
  const siteEl = modalHead.querySelector(".pm-site");
  ok(siteEl != null && siteEl.textContent === "A_1",
    "C3: the modal header must carry A1's differing site name (A_1) in .pm-site, got: " + JSON.stringify(siteEl && siteEl.textContent));
  ok(modalHead.textContent.indexOf("Alpha Survey") >= 0, "C3: the modal header must carry the survey name");
  ok(modalHead.textContent.indexOf("OrgX") >= 0, "C3: the modal header must carry the organisation");
  ok(modalHead.querySelector(".chip") != null, "C3: the modal header must carry the data-type chip");
  ok(modalHead.textContent.indexOf("-30.000000, 136.000000") >= 0,
    "C3: the modal header must carry the honest coordinate line (A1 exact 6-dp position), got: " + JSON.stringify(modalHead.textContent));
  // Esc closes the modal WITHOUT closing the drawer; focus returns to the opener.
  doc.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  ok(doc.getElementById("plotmodal") == null, "C3: Esc did not close the full-station modal");
  ok(drwV.classList.contains("open"), "C3: Esc on the modal must NOT also close the drawer underneath it");
  ok(doc.activeElement === rhoExpand, "C3: focus did not return to the expand button after closing the modal");
  // Click-out on the overlay backdrop ALSO closes it. Re-open from the SAME (only) control and re-assert
  // that it expands the WHOLE station, not one panel: with the per-plot buttons gone, the section control
  // is the only route to the modal, so re-openability from it is the thing worth pinning.
  fire(rhoExpand, "click");
  const modal2 = doc.getElementById("plotmodal");
  ok(modal2 != null, "C3: the section expand control did not re-open the full-station modal");
  ok(modal2.querySelector('.plot[data-plot="rho"]') != null && modal2.querySelector('.plot[data-plot="pt"]') != null,
    "C3: the section control must expand the WHOLE station (rho + pt panels present), not a single plot");
  fire(modal2, "click");   // the overlay itself is the click target -> close
  ok(doc.getElementById("plotmodal") == null, "C3: clicking the overlay backdrop did not close the modal");
  // NON-TIPPER STATION: A2 has no tipper -> its modal shows rho / phase / pt but NO induction-arrow panel.
  drwV.classList.remove("open");
  win.location.hash = "#/station/au.alpha.A2"; A.routeFromHash();
  ok(drwV.classList.contains("open"), "C3: #/station/au.alpha.A2 did not open the drawer");
  const a2Expand = drwV.querySelector('#dp-response .sechead [data-act="expand"]');
  ok(a2Expand != null, "C3: no section expand control on the A2 response heading");
  ok(drwV.querySelectorAll('#dp-response [data-act="expand"]').length === 1,
    "C3/ONE-EXPAND: A2 must also carry exactly one expand control in its response section");
  fire(a2Expand, "click");
  const a2Modal = doc.getElementById("plotmodal");
  ok(a2Modal != null, "C3: expand did not open the modal for the non-tipper station A2");
  ["rho", "phase", "pt"].forEach(k =>
    ok(a2Modal.querySelector('.plot[data-plot="' + k + '"]') != null,
      "C3: a non-tipper station's modal must still carry the '" + k + "' panel"));
  ok(a2Modal.querySelector('[data-plot="arrow"]') == null &&
     a2Modal.innerHTML.indexOf("Induction arrows (Parkinson)") < 0,
    "C3: a non-tipper station's modal must have NO induction-arrow panel (arrowSvg empty -> panel absent)");
  doc.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  ok(doc.getElementById("plotmodal") == null, "C3: Esc did not close the A2 modal");
  // restore the A1 drawer for the sections that follow (they assume it is the open station).
  drwV.classList.remove("open");
  win.location.hash = "#/station/au.alpha.A1"; A.routeFromHash();
  ok(drwV.classList.contains("open"), "C3: could not restore the A1 drawer after the modal checks");

  // (i) C1b FENCE under tabs: an embargoed station shows the access panel INSIDE the Response tab, renders
  //     no plot paths there, never offers 'EDI (via source archive)' in Files, and gives the sticky header
  //     NO download affordance. FAILS if the gate leaks past the tab split.
  drwV.classList.remove("open");
  win.location.hash = "#/station/au.delta.D1"; A.routeFromHash();
  const dRes = doc.getElementById("dp-response"), dFiles = doc.getElementById("dp-files");
  ok(dRes.textContent.indexOf(EMBARGO_NODATE) >= 0,
    "C1b: the embargoed access panel must render inside the Response tab; got: " + dRes.textContent.slice(0, 200));
  ok(dRes.querySelectorAll("svg path").length === 0, "C1b: the embargoed Response tab must render no plot paths");
  // ...and NO expand control either: with the curves withheld the modal has no panels to open, so an
  // affordance over the access panel would be a dead control. (Section-level control, owner 2026-07-28.)
  ok(dRes.querySelectorAll('[data-act="expand"]').length === 0,
    "C1b: an embargoed station's Response tab must carry no expand control (there is nothing to expand)");
  ok(dFiles.innerHTML.indexOf("EDI (via source archive)") < 0,
    "C1b: the embargoed Files tab must NOT offer 'EDI (via source archive)'");
  ok(doc.querySelector(".dtop .dl-edi") == null,
    "C1b: an embargoed station must show NO Download EDI action in the sticky header");
  // api-docs lane, same C1b fence applied to the API expander: the engine emits a WITHHELD station.json
  // for a non-served survey but returns before writing dimensionality.json at all (a dimensionality
  // classification is interpretation OF the embargoed transfer function). So the endpoint list here must
  // keep the station.json line and drop the dimensionality one, or ~17% of the catalogue is handed a GET
  // that 404s. Asserted on the embargoed fixture in the real DOM, a second harness for the pin in
  // tests/test_drawer_api_endpoints.py.
  const dProvEmb = doc.getElementById("dp-provenance");
  ok(dProvEmb.textContent.indexOf("dimensionality.json") < 0,
    "C1b: an embargoed station has no dimensionality.json emitted, so the API expander must not list one");
  ok(/\/data\/products\/delta\/D1\/station\.json/.test(dProvEmb.textContent),
    "C1b: the embargoed station's station.json line must survive (it is emitted as a withheld stub)");
  drwV.classList.remove("open");

  // W. UX6 Wave D (D2): rail Browse / Select & export mode. Default is Browse; the toggle swaps the two
  // panes with EVERY existing element id intact; drawing a selection or 'Select all filtered' auto-switches
  // to Select & export.
  const modeSeg = doc.getElementById("modeSeg"), browseMode = doc.getElementById("browseMode"), selectMode = doc.getElementById("selectMode");
  ok(modeSeg && browseMode && selectMode, "D2: mode segmented control / panes missing from the rail");
  ok(A.sidebarMode() === "browse", "D2: default rail mode must be Browse, got " + A.sidebarMode());
  ok(!browseMode.classList.contains("hidden") && selectMode.classList.contains("hidden"),
    "D2: Browse must show the browse pane and hide the select pane by default");
  ["find", "typeBoxes", "tree", "selAll", "dlZip", "tsSeg", "availSel", "yearFrom", "dlSh"].forEach(id =>
    ok(doc.getElementById(id), "D2: element id '" + id + "' went missing after the mode split"));
  const selBtn = [...modeSeg.children].find(b => b.dataset.mode === "select");
  selBtn.click();
  ok(A.sidebarMode() === "select", "D2: clicking 'Select & export' did not switch the mode");
  ok(browseMode.classList.contains("hidden") && !selectMode.classList.contains("hidden"),
    "D2: Select & export must hide the browse pane and show the select pane");
  ok(selBtn.classList.contains("on"), "D2: the active mode button did not get the .on state");
  [...modeSeg.children].find(b => b.dataset.mode === "browse").click();
  ok(A.sidebarMode() === "browse", "D2: could not switch back to Browse");
  // W2. TWO LAYOUT REGRESSIONS THIS HARNESS CANNOT SEE BEHAVIOURALLY (found live 2026-08-26).
  // jsdom has no layout engine: every rect is 0, so the mode-switch pins ABOVE stayed green while the
  // live rail was a ONE-WAY DOOR. #filterPane is a column flex, so the taller Select pane made the
  // flex algorithm shrink #modeSeg, and because .seg clips its overflow it collapsed to its 2px
  // borders in silence rather than overflowing where anyone would notice. Measured on the live site:
  // 29px in Browse, 2px in Select, restored to 29px by flex-shrink:0 alone. These are therefore
  // SOURCE pins on the two declarations that carry the constraint - weaker than a behavioural pin,
  // and the honest best this harness can do for a pure-layout class.
  const _segCss = (html.match(/\.seg\{[^}]*\}/) || [""])[0];
  ok(/flex:\s*none|flex-shrink:\s*0/.test(_segCss),
    "the Browse/Select toggle must not be shrinkable: a column-flex parent squashes it to its borders " +
    "in the taller Select pane and the rail becomes a one-way door. Got: " + JSON.stringify(_segCss));
  const _scaleCss = (html.match(/\.leaflet-control-scale-line\{[^}]*\}/) || [""])[0];
  ok(/text-shadow:\s*none/.test(_scaleCss),
    "the scale bar must clear Leaflet's WHITE text-shadow: it is meant for a light basemap and reads " +
    "as a halo around near-white text on the dark legend. Got: " + JSON.stringify(_scaleCss));

  A.setSidebarMode("browse");
  doc.getElementById("selAll").click();
  ok(A.sidebarMode() === "select", "D2: 'Select all filtered' did not auto-switch to Select & export");
  doc.getElementById("clearSel").click();
  A.setSidebarMode("browse");

  // X. UX6 Wave D (D3, #20): the draw-created selection toast + its pure formatter. drawSelectionMsg pins
  // the exact copy (singular/plural, the word 'stations' — never 'sites' — and the shape word).
  // onDrawCreated fires the toast with the freshly computed count and (D2) auto-switches to Select.
  ok(A.drawSelectionMsg(2, "polygon") === "2 stations selected within polygon",
    "D3: polygon toast copy wrong, got: " + JSON.stringify(A.drawSelectionMsg(2, "polygon")));
  ok(A.drawSelectionMsg(1, "rectangle") === "1 station selected within rectangle",
    "D3: singular rectangle toast copy wrong, got: " + JSON.stringify(A.drawSelectionMsg(1, "rectangle")));
  ok(A.drawSelectionMsg(0, "polygon").indexOf("sites") < 0 && A.drawSelectionMsg(3, "polygon").indexOf("stations") >= 0,
    "D3: the toast must say 'stations', never 'sites'");
  A.setSidebarMode("browse");
  const toastEl = doc.getElementById("toast");
  toastEl.textContent = "";
  A.onDrawCreated({ layerType: "rectangle", layer: { options: {} } });
  ok(/^\d+ stations? selected within rectangle$/.test(toastEl.textContent),
    "D3: onDrawCreated did not fire the selection toast with the station count, got: " + JSON.stringify(toastEl.textContent));
  ok(A.sidebarMode() === "select", "D3: onDrawCreated did not auto-switch the rail to Select & export");
  doc.getElementById("clearSel").click();
  A.setSidebarMode("browse");

  // Z. Discoverability (owner, 2026-07-21): the SELECTION panel's "Draw rectangle"/"Draw polygon" buttons
  // ARM the same leaflet.draw handlers as the map's top-left toolbar icons, and armedDrawMode is ONE state
  // shared across both surfaces. Pins: (a) the two buttons exist in the SELECTION panel (below 'Select all
  // filtered') and route through armDraw — the same handler entry point (drawModeHandler), not a duplicated
  // draw invocation; (b) arming from a button sets the shared armedDrawMode that the map toolbar also drives
  // (via DRAWSTART -> setArmedDraw); (c) completing OR cancelling a draw clears it on both surfaces.
  A.setSidebarMode("select");
  const _selbox = doc.querySelector("#selectMode .selbox");
  const drawRect = doc.getElementById("drawRect"), drawPoly = doc.getElementById("drawPoly");
  ok(drawRect && _selbox && _selbox.contains(drawRect), "Draw: 'Draw rectangle' button missing from the SELECTION panel");
  ok(drawPoly && _selbox && _selbox.contains(drawPoly), "Draw: 'Draw polygon' button missing from the SELECTION panel");
  ok(_selbox.contains(doc.getElementById("selAll")), "Draw: the draw buttons must share the box with 'Select all filtered'");
  // (a) the panel button reaches the control's OWN mode handler (the reuse entry point), not a re-impl.
  ok(A.drawModeHandler("rectangle") != null && A.drawModeHandler("polygon") != null,
    "Draw: the control's rectangle/polygon mode handlers must be reachable (the shared arm entry point)");
  ok(A.armedDrawMode() === null, "Draw: nothing must be armed at rest, got " + A.armedDrawMode());
  // (b) arming from the button sets the shared state AND lights only that button.
  drawRect.click();
  ok(A.armedDrawMode() === "rectangle", "Draw: clicking 'Draw rectangle' did not arm rectangle, got " + A.armedDrawMode());
  ok(drawRect.classList.contains("armed"), "Draw: the rectangle button must light while its tool is live");
  ok(!drawPoly.classList.contains("armed"), "Draw: the polygon button must stay inert while rectangle is armed");
  drawPoly.click();
  ok(A.armedDrawMode() === "polygon" && drawPoly.classList.contains("armed") && !drawRect.classList.contains("armed"),
    "Draw: arming polygon must move the single shared state off rectangle (never both lit)");
  // map-icon parity: DRAWSTART from the toolbar icon drives the SAME state the buttons read (setArmedDraw
  // is exactly what the DRAWSTART listener calls) — an icon-armed mode lights the matching panel button.
  A.setArmedDraw("rectangle");
  ok(A.armedDrawMode() === "rectangle" && drawRect.classList.contains("armed") && !drawPoly.classList.contains("armed"),
    "Draw: an icon-armed mode must light the matching panel button (shared state), not the button's own path");
  // (c) completing a draw clears both surfaces (onDrawCreated -> setArmedDraw(null)).
  A.onDrawCreated({ layerType: "rectangle", layer: { options: {} } });
  ok(A.armedDrawMode() === null && !drawRect.classList.contains("armed") && !drawPoly.classList.contains("armed"),
    "Draw: completing a draw must clear the armed state on both surfaces (no button stays lit)");
  // (c) cancelling a draw (DRAWSTOP -> setArmedDraw(null)) clears both.
  drawPoly.click();
  ok(A.armedDrawMode() === "polygon", "Draw: re-arm before the cancel check failed");
  A.setArmedDraw(null);
  ok(A.armedDrawMode() === null && !drawPoly.classList.contains("armed"),
    "Draw: cancelling a draw must clear the armed state (button must not stay lit)");
  doc.getElementById("clearSel").click();
  A.setSidebarMode("browse");

  // Y. Lane B scope rule: downloads are never hidden behind a selection - with nothing selected they
  // act on the FILTERED CORPUS and the scope line says so; a selection re-scopes them. The old
  // hidden-row/empty-hint pair is retired with the behaviour it described.
  const exportBtns = doc.getElementById("exportBtns");
  ok(exportBtns && !doc.getElementById("exportHint"),
    "Lane B: #exportBtns stays; the #exportHint empty-state is retired with the hidden-row behaviour");
  doc.getElementById("clearSel").click();
  ok(!exportBtns.classList.contains("hidden"), "the Metadata row must stay visible with no selection");
  ok(!doc.getElementById("dlCsv").disabled,
    "with no selection the metadata exports act on the filtered corpus and must stay enabled");
  ok(/^Across \d+ filtered stations:$/.test(doc.getElementById("scopeLine").textContent),
    "no selection -> the scope line prices the filtered corpus, got " + JSON.stringify(doc.getElementById("scopeLine").textContent));
  doc.getElementById("selAll").click();
  ok(A.selCount() > 0, "'Select all filtered' did not create a selection");
  ok(/^For the \d+ selected stations?:$/.test(doc.getElementById("scopeLine").textContent),
    "a selection -> the scope line prices the selection, got " + JSON.stringify(doc.getElementById("scopeLine").textContent));
  doc.getElementById("clearSel").click();
  A.setSidebarMode("browse");

  // Z. UX6 Wave D (D5, #24): the sidebar collapse toggle sets the .collapsed class AND calls
  // map.invalidateSize() (recorded by the map stub) so the map reclaims the width; state persists.
  A.setView("map");
  const collapseBtn = doc.getElementById("sidebarCollapse"), aside = doc.getElementById("filterPane");
  ok(collapseBtn, "D5: #sidebarCollapse toggle missing from the rail");
  ok(!aside.classList.contains("collapsed"), "D5: the rail must start expanded");
  const invBefore = mapCalls.filter(c => c.fn === "invalidateSize").length;
  collapseBtn.click();
  ok(aside.classList.contains("collapsed"), "D5: collapse toggle did not add the .collapsed class");
  ok(mapCalls.filter(c => c.fn === "invalidateSize").length > invBefore, "D5: collapsing did not call map.invalidateSize()");
  ok(win.localStorage.getItem("ausmt_sidebar_collapsed") === "1", "D5: collapsed state was not persisted");
  collapseBtn.click();
  ok(!aside.classList.contains("collapsed"), "D5: a second click did not expand the rail");
  ok(win.localStorage.getItem("ausmt_sidebar_collapsed") === "0", "D5: expanded state was not persisted");

  // AA. UX6 Wave D (D6): the static map legend: a coloured dot per data type and nothing else, the dots
  // reading the LIVE --lpmt/--bbmt/--amt/--gds tokens via CSS var() (a hard-coded hex would fail).
  const legend = doc.getElementById("mapLegend");
  ok(legend, "D6: #mapLegend was not built");
  // A legend keys what the map DRAWS. Both retired map objects (the proximity bubble and the survey badge
  // that replaced it) must therefore be absent from its copy, not merely re-worded.
  ok(!/survey \(click to open/.test(legend.textContent) && !/stations \(zoom to expand\)/.test(legend.textContent),
    "dots only: the legend must key no collapsed-survey object, got: " + JSON.stringify(legend.textContent));
  const legDots = [...legend.querySelectorAll(".legrow .dot")];
  ok(legDots.length === 4, "D6: expected 4 data-type legend dots, got " + legDots.length);
  ["--lpmt", "--bbmt", "--amt", "--gds"].forEach(tok =>
    ok(legDots.some(d => (d.getAttribute("style") || "").indexOf("var(" + tok + ")") >= 0),
      "D6: no legend dot reads the live token " + tok + " (a hard-coded hex would fail this)"));
  // A8 (R12). THE SCALE BAR, constructed deliberately (metric only, capped at 120px) and RE-PARENTED
  // into the legend body, where a reader looks for the map's key, rather than left in the Leaflet
  // corner it would otherwise take on top of the dots.
  ok(scaleControls.length === 1, "A8: exactly one scale control must be constructed, got " + scaleControls.length);
  const _sc = scaleControls[0];
  ok(_sc.options.metric === true && _sc.options.imperial === false && _sc.options.maxWidth === 120,
    "A8: the scale bar must be metric-only and capped at 120px, got " + JSON.stringify(_sc.options));
  ok(_sc.added === true, "A8: the control must be added to the map, not merely constructed");
  const _scEl = doc.querySelector("#mapLegend .maplegend-body .maplegend-scale");
  ok(_scEl && _scEl === _sc.getContainer(),
    "A8: the control's OWN container must be re-parented into the legend body, got " + (_scEl && _scEl.className));
  // ...and NEITHER legend pin moves. The scale bar takes its own class precisely so it cannot be
  // counted as a data-type row or change what #mapLegend is a child of.
  ok([...legend.querySelectorAll(".legrow .dot")].length === 4,
    "A8: the scale bar must add no .legrow .dot; the legend still describes exactly four data types");
  ok(legend.parentElement && legend.parentElement.id === "map",
    "A8: the legend stays a child of the map container");
  const legToggle = doc.getElementById("mapLegendToggle");
  ok(legToggle, "D6: the legend collapse toggle is missing");
  const wasExpanded = legend.classList.contains("expanded");
  legToggle.click();
  ok(legend.classList.contains("expanded") !== wasExpanded, "D6: the legend toggle did not flip the expanded state");

  // ===== UX6 WAVE E ==============================================================================
  // BB. THE WORKSPACE CARD. The card field set is reduced; the heavy blocks moved to the survey DETAIL.
  // Each pin states what it fails on. (Alpha's blurb was reset to null in section R.)
  // C2 (contract section 1: "Update the BB card-shape pins to the new field set"): the abstract block
  // leaves the field set. What stays is what a reader SCANS - identity, where, how much, under what
  // licence - plus BOTH actions: the no-buttons rule is a HUB rule, and this is the working view, where
  // Download is the whole point of the grid feeding the download builder.
  doc.getElementById("drawer").classList.remove("open");
  const cardA1 = A.cardHtml("Alpha Survey");
  // present: title, org, collection chip, acquisition year, station count, mixbar, period range, badges, two actions.
  ok(/View survey/.test(cardA1), "E1: slim card must offer a 'View survey' action");
  ok(/>Download</.test(cardA1), "E1: slim card must offer a 'Download' action");
  ok(cardA1.indexOf("mixbar") >= 0, "E1: slim card must keep the data-type mixbar");
  ok(/2<\/b> stations/.test(cardA1), "E1: slim card must show the station count");
  ok(cardA1.indexOf("periods") >= 0, "E1: slim card must show the period range");
  ok(cardA1.indexOf("acquired") >= 0 && /2010\D+2012/.test(cardA1), "E1: slim card must show the acquisition year, 2010 to 2012 (the range joiner is the spaced hyphen; the en dash, U+2013, is purged from portal source)");
  ok(/DOI/.test(cardA1) && cardA1.indexOf("licence ?") >= 0, "E1: slim card must keep the licence + DOI badges");
  // absent (moved to detail): identifiers rollup, APA cite block, spatial extent, coord-QC stats,
  // per-format availability matrix (EDI/time-series/MTH5 badges), the completeness/smoothness check.
  // Both header strings are pinned absent: the station rollup's "Persistent identifiers & instruments"
  // (what the card used to carry) AND the survey grid's "Data at every level" head, which the drawer-polish
  // lane renamed it to. Pinning only the old string would have gone vacuous the moment it was renamed.
  ok(cardA1.indexOf("Persistent identifiers") < 0, "E1: the identifiers block must NOT be on the slim card");
  ok(cardA1.indexOf("Data at every level") < 0, "E1: the data-level grid must NOT be on the slim card");
  ok(cardA1.indexOf('class="cite"') < 0, "E1: the APA citation block must NOT be on the slim card");
  ok(cardA1.indexOf("extent") < 0, "E1: the spatial extent must NOT be on the slim card");
  ok(cardA1.indexOf("coord QC") < 0, "E1: the coordinate-QC flag stat must NOT be on the slim card");
  ok(cardA1.indexOf("time series") < 0 && cardA1.indexOf("MTH5") < 0, "E1: the per-format availability matrix must NOT be on the slim card");
  ok(cardA1.indexOf("completeness/smoothness") < 0, "E1: the completeness/smoothness check must NOT be on the slim card (it stays in the detail)");
  // C2: the abstract block joins that absent list, and BOTH actions stay present (asserted above).
  ok(cardA1.indexOf('class="desc') < 0, "C2: the abstract block must NOT be on the workspace card");
  ok((cardA1.match(/data-act="select"/g) || []).length === 1 && (cardA1.match(/View survey/g) || []).length === 1,
    "C2: the workspace card keeps EXACTLY its two actions, one View survey and one Download");
  // SURVEY LINKS: the card TITLE is a real anchor to the survey's published static page. A heading that
  // a delegated handler turns into a JS navigation cannot be middle-clicked, opened in a new tab, copied,
  // or previewed in the status bar; a real href hands all four back to the browser. Pinned on the ELEMENT
  // rather than on a substring, so a revert to the JS-navigated heading fails here.
  const _cardBox = doc.createElement("div"); _cardBox.innerHTML = cardA1;
  const _cardTitle = _cardBox.querySelector(".scardhead h3 a");
  ok(_cardTitle && _cardTitle.getAttribute("href") === "/surveys/alpha",
    "survey links: the card title must be an anchor to /surveys/alpha, got href=" +
    JSON.stringify(_cardTitle && _cardTitle.getAttribute("href")));
  ok(_cardTitle && _cardTitle.textContent === "Alpha Survey",
    "survey links: the card title anchor must keep the survey name as its visible text, got " +
    JSON.stringify(_cardTitle && _cardTitle.textContent));
  // the removed renderers are NOT deleted from the codebase — they still render in the survey detail
  // (identifiersHtml + apa are exercised by section P above and the E2 rollup below).

  // CC. E3 DISCOVERY CONTROLS. Sort / live count / facets / clear / compact toggle, above the card grid.
  // Reset the tree first — section Q's selectSurvey() left only one survey checked; the discovery view
  // reads the same filter, so restore the full baseline (all 5 stations / 4 surveys) before asserting.
  [...doc.querySelectorAll("#tree input")].forEach(c => { c.checked = true; });
  A.refresh();
  A.setView("surveys");
  ok(A.visIds().length === 5, "E3: expected the clean 5-station baseline entering the discovery tests, got " + A.visIds().length);
  const sortSel = doc.getElementById("sortSel"), surveyCount = doc.getElementById("surveyCount");
  const layoutSeg = doc.getElementById("layoutSeg"), clearFilters = doc.getElementById("clearFilters"), facetChips = doc.getElementById("facetChips");
  ok(sortSel && surveyCount && layoutSeg && clearFilters && facetChips, "E3: a discovery control is missing from #surveysview");
  const surveyOrder = () => [...doc.querySelectorAll("#cardGrid .scard")].map(c => { const b = c.querySelector("[data-survey]"); return b ? b.dataset.survey : null; });
  // (a) live count: 4 distinct surveys visible at baseline.
  ok(surveyCount.textContent === "4 surveys", "E3: the live result count must read '4 surveys', got: " + JSON.stringify(surveyCount.textContent));
  // (b) default sort = Name -> Alpha first.
  ok(surveyOrder()[0] === "Alpha Survey", "E3: default (Name) sort must list Alpha Survey first, got: " + JSON.stringify(surveyOrder()));
  // (c) sort = Year (newest first) -> Beta (2019) ahead of Alpha (2012); undated Gamma/Delta last.
  sortSel.value = "year"; fire(sortSel, "change");
  ok(surveyOrder()[0] === "Beta Survey", "E3: Year sort must put the newest (Beta 2019) first, got: " + JSON.stringify(surveyOrder()));
  sortSel.value = "name"; fire(sortSel, "change");
  ok(surveyOrder()[0] === "Alpha Survey", "E3: switching back to Name sort did not re-order");
  // (d) FORBIDDEN: no completeness/smoothness option in the sort control (the screen must never rank).
  ok([...sortSel.options].every(o => !/completeness|smoothness|quality/i.test(o.value + o.textContent)),
    "E3 FENCE: the sort control must NOT offer a completeness/quality ranking");
  // (e) FACET SWAP (cleanup wave B): the "Has DOI" / "Has tipper" chips are REMOVED; "Open licence" is
  // kept; data-type chips (BBMT/LPMT/AMT/GDS, only corpus-present ones) are added. None is the completeness
  // check. (This is a RED-proof target for the facet swap; old code renders a [data-facet="doi"] chip.)
  ok(facetChips.querySelector('[data-facet="doi"]') == null && facetChips.querySelector('[data-facet="tipper"]') == null,
    "E3: the 'Has DOI' and 'Has tipper' facet chips must be removed");
  ok(facetChips.querySelector('[data-facet="lic"]') != null, "E3: the 'Open licence' facet chip must be kept");
  const facetBtns = [...facetChips.querySelectorAll(".facet")];
  ok(facetBtns.every(b => b.dataset.facet !== "q" && !/completeness|smoothness|quality/i.test(b.textContent)),
    "E3 FENCE: no facet may filter by the completeness/smoothness check");
  // the kept 'Open licence' chip toggles its .on state (re-queried after each click; the chip innerHTML re-renders).
  facetChips.querySelector('[data-facet="lic"]').click();
  ok(facetChips.querySelector('[data-facet="lic"]').classList.contains("on"), "E3: clicking 'Open licence' must set its .on state");
  facetChips.querySelector('[data-facet="lic"]').click();
  ok(!facetChips.querySelector('[data-facet="lic"]').classList.contains("on"), "E3: a second click must clear the 'Open licence' chip");
  // (f) TYPE CHIPS: the all-BBMT baseline renders ONLY the BBMT type chip (only corpus-present types get one).
  ok(facetChips.querySelector('[data-type-facet="BBMT"]') != null, "E3: a BBMT type chip must render (BBMT is present in the corpus)");
  ok(facetChips.querySelector('[data-type-facet="LPMT"]') == null && facetChips.querySelector('[data-type-facet="GDS"]') == null,
    "E3: only corpus-present data types may get a chip (no LPMT/GDS chip in the all-BBMT baseline)");
  // reclassify Gamma's one station to AMT: a second type chip (AMT) now appears, in canonical order after BBMT.
  A.setType("G1", "AMT"); A.renderCards();
  const typeChips = [...facetChips.querySelectorAll("[data-type-facet]")].map(b => b.dataset.typeFacet);
  ok(typeChips.join(",") === "BBMT,AMT", "E3: type chips must render only present types in canonical order (BBMT,AMT), got: " + JSON.stringify(typeChips));
  // selecting AMT narrows to the single AMT survey (Gamma); multi-select adding BBMT restores all four (AMT OR BBMT).
  facetChips.querySelector('[data-type-facet="AMT"]').click();
  ok(surveyCount.textContent === "1 survey" && surveyOrder()[0] === "Gamma Survey",
    "E3: the AMT type chip must narrow to the single AMT survey (Gamma), got: " + JSON.stringify([surveyCount.textContent, surveyOrder()]));
  ok(facetChips.querySelector('[data-type-facet="AMT"]').classList.contains("on"), "E3: an active type chip must get the .on state");
  facetChips.querySelector('[data-type-facet="BBMT"]').click();
  ok(surveyCount.textContent === "4 surveys", "E3: type chips are multi-select (AMT OR BBMT -> all four surveys), got: " + JSON.stringify(surveyCount.textContent));
  // (g) SEARCH (cleanup wave B): reset the type facets first, then case-insensitive substring over
  // name/org/region/blurb, live-updating the grid + count. This REPLACES the rail #find as the Surveys search.
  clearFilters.click();
  const searchInput = doc.getElementById("surveySearch");
  ok(searchInput, "E3: the discovery search input (#surveySearch) is missing from the discovery bar");
  searchInput.value = "beta"; fire(searchInput, "input");
  ok(surveyCount.textContent === "1 survey" && surveyOrder()[0] === "Beta Survey",
    "E3: the search must narrow by survey NAME (beta -> Beta Survey), got: " + JSON.stringify([surveyCount.textContent, surveyOrder()]));
  searchInput.value = "ORGX"; fire(searchInput, "input");   // Alpha's org, matched case-insensitively
  ok(surveyOrder().length === 1 && surveyOrder()[0] === "Alpha Survey",
    "E3: the search must match the ORG field case-insensitively (ORGX -> Alpha/OrgX), got: " + JSON.stringify(surveyOrder()));
  // The header counter stays coherent on the Surveys view; the search handler re-runs updateCounts().
  // C5 moved this pin off #nVis: on the Surveys view the slot is the WORKSPACE LINE, not the map's
  // three station counts (contract section 1, C5).
  ok(doc.getElementById("countSlot").textContent === "1 of 4 surveys shown",
    "E3/C5: the header workspace line must track the search on the Surveys view, got: " + JSON.stringify(doc.getElementById("countSlot").textContent));
  // (h) CLEAR resets the type facets AND clears the search (count back to 4).
  clearFilters.click();
  ok(surveyCount.textContent === "4 surveys" && searchInput.value === "",
    "E3: 'Clear filters' must reset the type facets AND clear the search (count back to 4), got: " + JSON.stringify([surveyCount.textContent, searchInput.value]));
  ok(facetChips.querySelector('[data-type-facet="AMT"]') == null || !facetChips.querySelector('[data-type-facet="AMT"]').classList.contains("on"),
    "E3: 'Clear filters' left a type chip active");
  A.setType("G1", "BBMT"); A.renderCards();   // restore the all-BBMT baseline for the sections that follow
  // (h) COMPACT toggle: single-line rows replace the card grid; toggling back restores cards.
  const cardGridEl = doc.getElementById("cardGrid");
  layoutSeg.querySelector('[data-layout="compact"]').click();
  ok(cardGridEl.className === "cardlist", "E3: compact toggle must switch #cardGrid to the .cardlist layout, got: " + cardGridEl.className);
  ok(cardGridEl.querySelectorAll(".srow").length === 4 && cardGridEl.querySelectorAll(".scard").length === 0,
    "E3: compact layout must render single-line .srow rows (no .scard), got srow=" + cardGridEl.querySelectorAll(".srow").length);
  ok(cardGridEl.querySelector(".srow .srow-lic .badge") != null, "E3: a compact row must carry the licence badge");
  // SURVEY LINKS: the compact row's title is a real anchor to the published static page. The TAG is
  // pinned as well as the href, because a button cannot be middle-clicked, opened in a new tab or copied
  // however its click is wired, which is the whole reason the element changed.
  const _rowTitle = cardGridEl.querySelector(".srow .srow-title");
  ok(_rowTitle && _rowTitle.tagName === "A",
    "survey links: the compact row title must be an anchor, got <" +
    (_rowTitle && _rowTitle.tagName.toLowerCase()) + ">");
  ok(_rowTitle && /^\/surveys\/(alpha|beta|gamma|delta)$/.test(_rowTitle.getAttribute("href") || ""),
    "survey links: the compact row title must link /surveys/<slug>, got href=" +
    JSON.stringify(_rowTitle && _rowTitle.getAttribute("href")));
  ok(cardGridEl.innerHTML.indexOf("#/survey/") < 0 && cardGridEl.innerHTML.indexOf('data-act="story"') < 0,
    "survey links: no compact row may reach the drawer, by hash route or by story action");
  layoutSeg.querySelector('[data-layout="cards"]').click();
  ok(cardGridEl.className === "cardgrid" && cardGridEl.querySelectorAll(".scard").length === 4, "E3: toggling back to Cards did not restore the card grid");

  // C3. FOUR ACROSS, AND THE GRID STOPS WHERE THE BAR STOPS (owner ruling; overturns the five-up note
  // that used to sit at the .cardgrid rule). Two defects in one declaration. The 300px floor let a wide
  // screen pack in five and then six columns of cards too narrow to read; and .cardgrid was the ONLY
  // uncapped grid on the view - .discovery and .collfeature-grid already cap at 1500px - so at 2560px
  // the cards ran a metre wider than the controls that filter them, and the bar no longer looked like it
  // belonged to the grid. A 352px floor under a 1500px cap yields exactly four columns at the cap
  // (4*352 + 3*14 gap = 1450 <= 1500; a fifth would need 1816) and never more, at any width; the
  // floor sits low enough that a 1500px viewport (grid content 1460px after the view's 20px padding)
  // fits four as well, not just the capped ultrawide case. Four-across is the ceiling by ruling: a
  // fifth column on ultrawides would need its own ruling, not a lower floor here.
  // E3 above pins class names only; jsdom resolves declared class CSS through getComputedStyle with no
  // layout engine, so the cap and the floor are pinned as the CSS contract they are.
  const _gridCss = win.getComputedStyle(cardGridEl);
  ok(_gridCss.maxWidth === "1500px",
    "C3: .cardgrid must cap at 1500px so the grid never outruns the discovery bar above it, got maxWidth=" +
    JSON.stringify(_gridCss.maxWidth));
  ok(/minmax\(\s*min\(\s*352px\s*,\s*100%\s*\)\s*,\s*1fr\s*\)/.test(_gridCss.gridTemplateColumns),
    "C3: .cardgrid must lay out on a 352px minimum column so a 1500px viewport and the 1500px cap both " +
    "yield four across, and that floor must be min(352px,100%) - a bare minimum cannot shrink, so a " +
    "375px phone would scroll sideways. Got " +
    JSON.stringify(_gridCss.gridTemplateColumns));
  // The cap is only coherent if it MATCHES the bar's; a grid capped at some other width would still be
  // a grid that does not line up with its controls.
  ok(win.getComputedStyle(doc.getElementById("discoveryControls")).maxWidth === _gridCss.maxWidth,
    "C3: the card grid and the discovery bar must share one cap, got bar=" +
    JSON.stringify(win.getComputedStyle(doc.getElementById("discoveryControls")).maxWidth) +
    " grid=" + JSON.stringify(_gridCss.maxWidth));

  // C5. THE CONTEXTUAL COUNTER (owner R12, the SPA half). The header counter read
  // "N shown / M selected / T total" on EVERY view, and only on the map was that a description of what
  // the reader was looking at. On the Surveys view it counted stations while the screen showed survey
  // cards; on the Collections views it counted something not on screen at all. The SHELL is identical
  // everywhere - same element, same place, same type - and only the SLOT's content changes; where
  // nothing true can be said about what is on screen, it says nothing.
  const slot = doc.getElementById("countSlot");
  ok(slot, "C5: the header counter needs a slot element (#countSlot) whose content is per-view");
  const shell = doc.getElementById("headerCounts");
  ok(shell && shell.classList.contains("counts") && shell.contains(slot),
    "C5: the shell (.counts) must be the same element on every view, with the slot inside it");
  // (a) MAP: unchanged - the three station counts, with the ids the rest of the app paints.
  A.setView("map");
  ok(/^5 shown · 0 selected · 5 total$/.test(slot.textContent.trim()),
    "C5: the map view keeps the three station counts, got " + JSON.stringify(slot.textContent));
  ok(doc.getElementById("nVis") && doc.getElementById("nSel") && doc.getElementById("nTot"),
    "C5: the map form must keep the nVis/nSel/nTot ids");
  // (b) SURVEYS: the workspace line, driven by the LIVE filter and selection state. With nothing
  //     selected the selected clause is HIDDEN rather than reading a truthful-but-noisy "0 selected".
  A.setView("surveys");
  ok(slot.textContent === "4 of 4 surveys shown",
    "C5: the workspace line must read 'N of 4 surveys shown' with no selection, got " + JSON.stringify(slot.textContent));
  ok(doc.getElementById("nVis") == null,
    "C5: the map's station counts must not linger on the Surveys view under a survey-shaped label");
  // ...the FILTER half: narrow the catalogue and the first number follows it.
  const c5search = doc.getElementById("surveySearch");
  c5search.value = "beta"; fire(c5search, "input");
  ok(slot.textContent === "1 of 4 surveys shown",
    "C5: the workspace line's first number is the LIVE filtered count, got " + JSON.stringify(slot.textContent));
  c5search.value = ""; fire(c5search, "input");
  // ...the SELECTION half: it is stations that get selected and downloaded, so the second clause counts
  //    stations, appears when there is a selection, and takes the singular at one.
  A.setSelected(["A1", "A2"]);
  ok(slot.textContent === "4 of 4 surveys shown · 2 stations selected",
    "C5: a live selection must show as a stations-selected clause, got " + JSON.stringify(slot.textContent));
  A.setSelected(["A1"]);
  ok(slot.textContent === "4 of 4 surveys shown · 1 station selected",
    "C5: the selected clause must take the singular at one, got " + JSON.stringify(slot.textContent));
  A.setSelected([]);
  ok(slot.textContent === "4 of 4 surveys shown",
    "C5: clearing the selection must hide the clause, not print a zero, got " + JSON.stringify(slot.textContent));
  // (c) COLLECTIONS and the collection DETAIL: the slot is EMPTY. Neither view is a filtered set of
  //     anything the counter can honestly describe, and a stale station count is worse than none.
  A.setView("collections");
  ok(slot.textContent.trim() === "",
    "C5: the Collections view must leave the counter slot empty, got " + JSON.stringify(slot.textContent));
  ok(shell.classList.contains("counts"),
    "C5: the shell stays in place on Collections - only the slot's content changes");
  win.location.hash = "#/collection/auslamp"; A.routeFromHash();
  ok(slot.textContent.trim() === "",
    "C5: the collection detail must leave the counter slot empty, got " + JSON.stringify(slot.textContent));
  win.location.hash = ""; A.setView("surveys");
  // (d) THE NUMBER FORMAT, at a count the fixture cannot reach. Contract section 1, C5: the counter
  // "renders on the MAP view as today", and today is origin/main's raw `nv.textContent=visible.length`.
  // The workspace line is NEW copy and takes the thousands separator the rest of the workspace uses.
  // With five fixture stations "5" formats identically either way, so BOTH forms were invisible to the
  // suite and the map's could widen without anything noticing. A fresh window carrying 1,200 stations is
  // the smallest thing that can see the difference. Rows are cloned POSITIONALLY (contract/columns.json:
  // id, survey, lat, lon, ..., ausmt_id at 12); tf.json and sci.json are dropped rather than left at
  // five rows, so the synthetic corpus is a clean phase-1-only boot like the two failure windows above.
  const _bigCat = _cat.slice();
  for (let i = _cat.length; i < 1200; i++) {
    const r = _cat[0].slice();
    r[0] = "Z" + i; r[2] = -30 - (i % 40) * 0.1; r[3] = 130 + (i % 40) * 0.1; r[12] = "au.alpha.Z" + i;
    _bigCat.push(r);
  }
  const _bigMap = Object.assign({}, DATAMAP, { "data/catalogue.json": _bigCat });
  delete _bigMap["data/tf.json"]; delete _bigMap["data/sci.json"];
  const bigWin = await bootFreshWindow(_bigMap);
  const bigA = bigWin.__api, bigSlot = bigWin.document.getElementById("countSlot");
  ok(bigA.nST() === 1200, "C5: the 1,200-station window did not build; got " + bigA.nST() + " stations");
  bigA.setView("map");
  ok(/^1200 shown · 0 selected · 1200 total$/.test(bigSlot.textContent.trim()),
    "C5: the map counter renders as today - plain integers, no separator - got " +
    JSON.stringify(bigSlot.textContent.trim()));
  bigA.setView("surveys");
  bigA.setSelected(_bigCat.slice(0, 1018).map(r => r[0]));
  ok(/ · 1,018 stations selected$/.test(bigSlot.textContent),
    "C5: the workspace line's station count takes the en-AU thousands separator, got " +
    JSON.stringify(bigSlot.textContent));

  // C6. THE DISCOVERY BAR AS THE PRIMARY FILTER SURFACE (brief 10). Two gaps, one cause: the year-range
  // and downloadable-only filters lived in the map rail, and the rail is HIDDEN on the Surveys view, so
  // on the view that is entirely about choosing a survey neither question could be asked at all. They
  // are promoted here, beside the licence and type chips that ask the same kind of question, and the
  // rail copies are removed so there is one home and no chance of two controls disagreeing.
  const c6search = doc.getElementById("surveySearch");
  ok(c6search.placeholder === "Search surveys, organisations or locations...",
    "C6: the search placeholder must name what is actually searchable (brief 10), got " +
    JSON.stringify(c6search.placeholder));
  // (a) the promoted YEAR RANGE filters the CATALOGUE, which the rail copy could never do. Alpha
  //     [2010,2012], Beta [2018,2019], Gamma and Delta undated. From 2015: only Beta survives, and the
  //     undated pair drop out because a reader who typed a year is asking for DATED data.
  const c6from = doc.getElementById("yearFrom");
  c6from.value = "2015"; fire(c6from, "input");
  ok(doc.getElementById("surveyCount").textContent === "1 survey",
    "C6: the promoted year range must narrow the card grid, got " + JSON.stringify(doc.getElementById("surveyCount").textContent));
  ok(doc.querySelector("#cardGrid .scard [data-survey]").dataset.survey === "Beta Survey",
    "C6: the surviving card must be Beta (2018-2019), the only survey inside the range");
  // (b) CLEAR FILTERS resets the promoted controls too. Before C6 it reset only the chips and the search
  //     box, so a year typed into the bar survived a "Clear filters" click and silently kept filtering.
  doc.getElementById("clearFilters").click();
  ok(c6from.value === "" && doc.getElementById("yearTo").value === "",
    "C6: Clear filters must reset the promoted year inputs, got " + JSON.stringify([c6from.value, doc.getElementById("yearTo").value]));
  ok(doc.getElementById("surveyCount").textContent === "4 surveys",
    "C6: Clear filters must restore the full catalogue, got " + JSON.stringify(doc.getElementById("surveyCount").textContent));
  const c6dl = doc.getElementById("facetChips").querySelector('[data-facet="dl"]');
  c6dl.click();
  ok(doc.getElementById("surveyCount").textContent === "2 surveys", "C6: setup, the Downloadable here chip must narrow to 2");
  doc.getElementById("clearFilters").click();
  ok(!doc.getElementById("facetChips").querySelector('[data-facet="dl"]').classList.contains("on"),
    "C6: Clear filters must reset the promoted Downloadable here chip");
  ok(doc.getElementById("surveyCount").textContent === "4 surveys",
    "C6: Clear filters must restore the full catalogue after the chip, got " + JSON.stringify(doc.getElementById("surveyCount").textContent));

  // DD/GG. E2 IDENTIFIERS ROLLUP + E4 DETAIL SECTION ORDER (survey detail).
  const drwE = doc.getElementById("drawer");
  drwE.classList.remove("open");
  win.location.hash = "#/survey/alpha"; A.routeFromHash();
  ok(drwE.classList.contains("open"), "E2/E4: #/survey/alpha did not open the survey detail");
  ok(drwE.getAttribute("role") === "dialog", "E7: the drawer must carry role=dialog");
  ok(/Alpha Survey/.test(drwE.getAttribute("aria-label") || ""), "E7: the survey drawer aria-label must name the survey, got: " + JSON.stringify(drwE.getAttribute("aria-label")));
  // E2 SUPERSEDED by the survey-drawer lane (ruling 4): the identifiers block is no longer a collapsed
  // <details> of whatever rows happened to be recorded. It is an always-open DATA-LEVEL tile grid of SIX
  // FIXED slots in the Rees et al. 2019 / NCI scheme, so the deposit chain has the same shape on every
  // survey. Alpha records no related_identifiers at all, which is exactly the case the old surface hid and
  // this one must state: 0 of 6, six MUTED-BUT-VISIBLE tiles, none of them omitted.
  // COPY (drawer-polish lane, owner 2026-08-19): the head reads "Data at every level: N of 6 recorded".
  // The old "Persistent identifiers:" wording is pinned GONE from the survey drawer below, so this rename
  // cannot silently revert; the station drawer's own identifiers block is untouched and keeps its name.
  ok(![...drwE.querySelectorAll("details")].some(d => /Data at every level:/.test(d.querySelector("summary") ? d.querySelector("summary").textContent : "")),
    "ruling 4: the identifiers rollup must NO LONGER be a collapsed <details> - it is an open tile grid");
  const idHead = [...drwE.querySelectorAll(".sechead")].find(h => /Data at every level:/.test(h.textContent));
  ok(idHead, "drawer-polish: the survey detail must carry a 'Data at every level:' section head");
  ok(!/Persistent identifiers:/.test(drwE.innerHTML),
    "drawer-polish: the old 'Persistent identifiers:' head must be GONE from the survey drawer");
  ok(/Data at every level:\s*0 of 6 recorded/.test(idHead.textContent),
    "ruling 4: the header count must read '0 of 6 recorded' for Alpha (no related_identifiers), got: " + JSON.stringify(idHead.textContent));
  const idGrid = idHead.nextElementSibling;
  ok(idGrid && idGrid.classList.contains("prodgrid"), "ruling 4: the identifiers head must be followed by a .prodgrid (the Downloads tile treatment)");
  const idTiles = [...idGrid.querySelectorAll(".prod")];
  ok(idTiles.length === 6, "ruling 4: Alpha must render exactly the SIX fixed slots (no extras), got: " + idTiles.length);
  // The six slot names, in the canonical Table-1 order. Order is part of the ruling: the chain reads
  // collection -> raw -> L0 -> L1 -> L2 -> L3 the same way on every survey.
  const SLOTS = ["Collection", "Packed Raw Data", "Level 0", "Level 1", "Level 2", "Level 3"];
  SLOTS.forEach((nm, i) => ok(idTiles[i].textContent.indexOf(nm) === 0,
    "ruling 4: slot " + (i + 1) + " must be '" + nm + "', got: " + JSON.stringify(idTiles[i].textContent.slice(0, 40))));
  // Owner ruling: an unrecorded level is MUTED BUT VISIBLE (never dropped) - .prod.dis + a hollow dot +
  // the honest state word. This is the assertion that would fail if a future change went back to hiding them.
  idTiles.forEach((t, i) => {
    ok(t.classList.contains("dis"), "ruling 4: unrecorded slot " + (i + 1) + " must render MUTED (.prod.dis), not hidden");
    ok(t.querySelector(".pdot.hollow"), "ruling 4: unrecorded slot " + (i + 1) + " must carry the hollow dot");
    ok(/not yet recorded/.test(t.textContent), "ruling 4: unrecorded slot " + (i + 1) + " must say 'not yet recorded'");
  });
  // The Organisation ROR row leaves the drawer with the old rollup (owner). The org name in the header
  // subline still carries its ROR link, so the identifier itself is not lost to the reader.
  ok(!/Organisation ROR/.test(drwE.innerHTML), "ruling 4: the 'Organisation ROR' row must be gone from the survey drawer");
  // The citation line is the POINT of using a published scheme: the vocabulary has to be checkable.
  const citeLine = drwE.querySelector(".dl-cite");
  ok(citeLine && /Levels per\s+Rees et al\. 2019/.test(citeLine.textContent),
    "ruling 4: the grid must carry the 'Levels per Rees et al. 2019' citation line, got: " + JSON.stringify(citeLine && citeLine.textContent));
  ok(citeLine.querySelector('a[href="https://doi.org/10.1080/22020586.2019.12073015"]'),
    "ruling 4: the citation must link the Rees et al. 2019 DOI");
  // Instruments stay, as ONE compact footer line under the grid (models + platform PID), not as a slot.
  const instrLine = drwE.querySelector(".dl-instr");
  ok(instrLine && /LEMI 423; Phoenix MTU-5C/.test(instrLine.textContent),
    "ruling 4: the instruments footer line must carry the declared models, got: " + JSON.stringify(instrLine && instrLine.textContent));
  // E4: section order. Description before footprint; downloads ahead of funding/publications/identifiers;
  // release notes last. Ruling 3: the trailing "Related surveys" block is REMOVED.
  const H = drwE.innerHTML, at = s => H.indexOf(s);
  const oDesc = at('class="dim"'), oScatter = at("<svg"), oSummary = at("Survey summary"), oDl = at(">Downloads<"),
        oFund = at(">Funding<"), oPubs = at("Related publications"), oIds = at("Data at every level:"),
        oRel = at("Release notes");
  ok(oDesc >= 0 && oScatter > oDesc, "E4: description (1) must come before the geographic footprint (2)");
  ok(oScatter < oSummary, "E4: footprint (2) must come before the station/period stats (3)");
  ok(oSummary < oDl, "E4: stats (3) must come before Downloads (4)");
  ok(oDl < oFund, "E4: Downloads (4) must come before Funding (6)");
  ok(oFund < oPubs, "E4: Funding (6) must come before Publications (7)");
  ok(oPubs < oIds, "E4: Publications (7) must come before the identifiers grid (8)");
  ok(oIds < oRel, "E4: the identifiers grid (8) must come before Release notes (9)");
  ok(at("Related surveys") < 0, "ruling 3: the 'Related surveys' section must be REMOVED from the survey drawer");
  ok(!/data-act="story"/.test(H), "ruling 3: no related-survey links may remain in the survey drawer");

  // ---- SURVEY-DRAWER LANE: HEADER ACTION + DOWNLOADS TRIM (rulings 1 + 2) --------------------------
  // Ruling 2: "View on map" is in the drawer HEADER beside the survey name, not in Downloads. The header
  // is sticky so the control does not scroll away from a long record.
  const svHead = drwE.querySelector(".dhead.svhead");
  ok(svHead, "ruling 2: the survey drawer header must carry the sticky .svhead treatment");
  const mapBtn = svHead.querySelector('[data-act="focus"]');
  ok(mapBtn && mapBtn.textContent === "View on map",
    "ruling 2: the header must carry the 'View on map' action, got: " + JSON.stringify(mapBtn && mapBtn.textContent));
  ok(svHead.querySelector(".close"), "ruling 2: the header must keep its Close control");
  ok(svHead.querySelector(".sid").textContent === "Alpha Survey", "ruling 2: the header must still name the survey");
  // Ruling 1: the Downloads grid is the whole-survey BUNDLES only. Neither of the two removed tiles may
  // survive there: "All EDIs (select & download)" is gone outright, and "View on map" moved to the header.
  const dlHead = [...drwE.querySelectorAll(".sechead")].find(h => h.textContent.trim() === "Downloads");
  ok(dlHead, "ruling 1: the Downloads section head is missing");
  const dlGrid = dlHead.nextElementSibling;
  ok(dlGrid && dlGrid.classList.contains("prodgrid"), "ruling 1: Downloads must render a .prodgrid");
  ok(!dlGrid.querySelector('[data-act="select"]'),
    "ruling 1: the 'All EDIs (select & download)' tile must be REMOVED from Downloads");
  ok(!dlGrid.querySelector('[data-act="focus"]'),
    "ruling 1: the 'View on map' tile must have LEFT Downloads (it lives in the header now)");
  ok(!/All EDIs/.test(H), "ruling 1: the 'All EDIs' copy must not survive anywhere in the survey drawer");
  ok(H.indexOf("View on map") === H.lastIndexOf("View on map"),
    "ruling 2: 'View on map' must appear EXACTLY ONCE in the survey drawer (the header), not also in Downloads");
  drwE.classList.remove("open");

  // DD. E5 COLLECTIONS LANDING (cleanup wave E): the intro paragraph is DELETED; ONE rich card style at
  // any count in the responsive grid; the FULL abstract renders with no 240-char truncation / "Show more".
  A.setView("collections");
  const collGrid = doc.getElementById("collectionsGrid");
  ok(doc.getElementById("collectionsIntro") == null, "E5: the collections landing intro (#collectionsIntro) must be deleted");
  ok(!/Collections group related surveys/.test(doc.getElementById("collectionsview").innerHTML),
    "E5: the deleted landing intro copy must not render anywhere on the collections view");
  ok(collGrid.className === "collfeature-grid", "E5: the collections grid must use the responsive rich-card grid, got: " + collGrid.className);
  const feat = collGrid.querySelector(".scard.collfeature");
  ok(feat, "E5: a rich collection card must render for the single collection");
  ok(/AusLAMP/.test(feat.textContent), "E5: the card must name the collection");
  ok(/Explore collection/.test(feat.textContent), "E5: the card must carry a prominent Explore action");
  ok(/2 surveys/.test(feat.textContent) && /3 stations/.test(feat.textContent), "E5: the card must show the rollup stats (2 surveys · 3 stations)");
  // FULL abstract, no truncation: the whole fixture description (incl. its tail) renders and there is no "Show more".
  ok(/run jointly by state and federal geoscience agencies\./.test(feat.textContent),
    "E5: the card must render the FULL abstract (its tail is present -> not truncated), got: " + JSON.stringify(feat.textContent));
  ok(!/Show more/.test(feat.innerHTML) && feat.innerHTML.indexOf("cf-expand") < 0,
    "E5: the 240-char truncation + 'Show more' expander must be gone");
  // participating organisations derived from member surveys' SMETA (Alpha=OrgX, Beta=OrgY).
  ok(/Participating organisations/.test(feat.textContent) && /OrgX/.test(feat.textContent) && /OrgY/.test(feat.textContent),
    "E5: the card must list participating organisations derived from member SMETA");
  // the footprint scatter is embedded in the card.
  ok(feat.querySelector(".collscatter svg"), "E6: the card must embed the collection footprint scatter");
  // C (leak fix / rail hide): the left rail + its resize handle are HIDDEN on the Collections view. RED-proof
  // target: pre-change the rail stays visible here, and the old map-rail recently-added section leaked
  // visible on every view via renderRecentlyAdded's unconditional un-hide.
  ok(doc.getElementById("filterPane").classList.contains("hidden"), "C: the left rail (#filterPane) must be hidden on the Collections view");
  ok(doc.getElementById("resizer").classList.contains("hidden"), "C: the rail resize handle (#resizer) must be hidden on the Collections view");

  // EE. E6 FOOTPRINT — AU outline present + dots coloured by member survey. collScatter reads the vendored
  // AU_OUTLINE global; the harness doesn't load vendor/au-outline.js, so inject a small stub and assert the
  // outline renders. (Absent-asset degrade is covered implicitly by the feature-card svg above, built while
  // AU_OUTLINE was undefined — it still produced an svg with dots.)
  // Synthetic two-survey member set (top-level `let ST` is a lexical binding, not a window property, so
  // `win.ST` is not reachable from the driver — build the input directly, as the other pure-helper sections do).
  const memberStations = [
    { id: "MA1", survey: "Alpha Survey", lat: -30, lon: 136, type: "LPMT" },
    { id: "MA2", survey: "Alpha Survey", lat: -31, lon: 137, type: "LPMT" },
    { id: "MB1", survey: "Beta Survey", lat: -29, lon: 135, type: "BBMT" },
  ];
  const svgNoOutline = A.collScatter(memberStations);
  ok(svgNoOutline.indexOf("au-outline") < 0, "E6: with no AU_OUTLINE asset the scatter must degrade to dots-only (no outline group)");
  ok(svgNoOutline.indexOf("<circle") >= 0, "E6: the degraded scatter must still plot the station dots");
  win.AU_OUTLINE = { coast: [[[130, -12], [150, -12], [150, -40], [130, -40], [130, -12]]], borders: [[[141, -12], [141, -40]]] };
  const svgOutline = A.collScatter(memberStations);
  ok(/class="au-outline"/.test(svgOutline), "E6: with an AU_OUTLINE asset the scatter must draw the outline group");
  ok((svgOutline.match(/<path /g) || []).length >= 2, "E6: the outline must render coastline + border <path>s");
  ok(/collscatter-legend/.test(svgOutline) && (svgOutline.match(/csl-item/g) || []).length === 2,
    "E6: the footprint must carry a per-survey legend (one item per member survey)");
  // the outline must sit BENEATH the dots (drawn before the <circle>s in document order).
  ok(svgOutline.indexOf("au-outline") >= 0 && svgOutline.indexOf("au-outline") < svgOutline.indexOf("<circle"),
    "E6: the outline group must be drawn before (beneath) the station dots");
  delete win.AU_OUTLINE;
  // C7. THE SCATTER TAKES THE SHARED RAMP. The parity of the colour RULE itself against the engine's
  // _member_colours is held by tests/collection_colours.test.js; this is the half that test cannot see -
  // that collScatter is actually the caller. Nine synthetic members, one station each, is the first
  // count past the eight-entry palette, which is exactly where the old modulo cycling handed the ninth
  // survey the first survey's colour and the legend stopped telling a reader which dots were which.
  const nineMembers = [];
  for (let i = 0; i < 9; i++)
    nineMembers.push({ id: "S" + i, survey: "Survey " + String.fromCharCode(65 + i), lat: -30 - i, lon: 130 + i, type: "LPMT" });
  const svgNine = A.collScatter(nineMembers);
  const nineFills = (svgNine.match(/<circle[^>]*fill="(#[0-9A-F]{6})"/g) || [])
    .map(t => (t.match(/fill="(#[0-9A-F]{6})"/) || [])[1]);
  ok(nineFills.length === 9, "C7: expected 9 member dots in the synthetic scatter, got " + nineFills.length);
  ok(new Set(nineFills).size === 9,
    "C7: nine members must get nine DISTINCT colours (the old palette cycled and repeated), got " +
    new Set(nineFills).size + " distinct: " + JSON.stringify(nineFills));
  // ...and they must be the SAME nine the pages compute, in member order, so one survey is never two
  // colours across the two surfaces.
  ok(JSON.stringify(nineFills) === JSON.stringify(A.memberColours(9)),
    "C7: the scatter must colour from the shared ramp, got " + JSON.stringify(nineFills) +
    " want " + JSON.stringify(A.memberColours(9)));
  // The legend swatches must agree with the dots; a legend keyed off a second colour rule is worse than
  // no legend at all.
  const nineLegend = (svgNine.match(/csl-dot" style="background:(#[0-9A-F]{6})"/g) || [])
    .map(t => (t.match(/background:(#[0-9A-F]{6})/) || [])[1]);
  ok(JSON.stringify(nineLegend) === JSON.stringify(nineFills),
    "C7: the legend swatches must be the dots' own colours, got " + JSON.stringify(nineLegend));
  // ...and a member the PAGE leaves out must not shift the ramp here. _collection_scatter assigns colours
  // over `present` - the members that HAVE positioned stations - so a wholly coordinate-withheld member
  // (C42 is a live corpus state, and hasPosition already keeps such a station off every map surface) is
  // not counted there. Counting it here gave the SPA a different n and moved every later member one step
  // along the ramp, which is the divergence C7 exists to remove.
  const withheldMix = [
    { id: "P1", survey: "Sv A", lat: -30, lon: 136, type: "LPMT" },
    { id: "P2", survey: "Sv B", lat: null, lon: null, type: "LPMT" },
    { id: "P3", survey: "Sv C", lat: -32, lon: 138, type: "LPMT" },
  ];
  const svgMix = A.collScatter(withheldMix);
  const mixFills = (svgMix.match(/<circle[^>]*fill="(#[0-9A-F]{6})"/g) || [])
    .map(t => (t.match(/fill="(#[0-9A-F]{6})"/) || [])[1]);
  ok(JSON.stringify(mixFills) === JSON.stringify(A.memberColours(2)),
    "C7: a position-less member must not enter the colour assignment; the two plotted members take " +
    JSON.stringify(A.memberColours(2)) + ", got " + JSON.stringify(mixFills));
  const mixLegend = (svgMix.match(/csl-dot" style="background:(#[0-9A-F]{6})"/g) || [])
    .map(t => (t.match(/background:(#[0-9A-F]{6})/) || [])[1]);
  ok(JSON.stringify(mixLegend) === JSON.stringify(mixFills),
    "C7: the legend must list the members that plot, in the dots' own colours, got " + JSON.stringify(mixLegend));

  // FF. E6 'View all stations on main map' — from the collection page, switch to map + fitBounds (spy on map).
  win.location.hash = "#/collection/auslamp"; A.routeFromHash();
  ok(A.curView() === "collection", "E6: #/collection/auslamp did not open the collection page");
  const collMapBtn = doc.querySelector('#collectionview [data-act="collmap"]');
  ok(collMapBtn && /View all stations on main map/.test(collMapBtn.textContent), "E6: the collection page must offer 'View all stations on main map'");
  // cleanup wave (E): the detail page uses a two-column HERO (abstract in the main column, fluid scatter in
  // the aside), the .collnote explainer is deleted, and the member table renders (its width cap is lifted).
  const cv = doc.getElementById("collectionview");
  ok(cv.querySelector(".collhero .collhero-main .colldesc") != null,
    "E: the collection detail must render the abstract in the two-column hero's main column");
  ok(cv.querySelector(".collhero .collhero-aside .collscatter svg") != null,
    "E: the hero's aside column must hold the fluid footprint scatter");
  ok(cv.querySelector(".collnote") == null && cv.innerHTML.indexOf("no transfer functions of its own") < 0,
    "E: the detail-page .collnote explainer must be deleted");
  ok(cv.querySelector(".colltable") != null, "E: the member-survey table must still render on the detail page");
  // SURVEY LINKS: a member row's survey link goes to that survey's published static page. href="#" with
  // the navigation done in JS is the worst of both worlds: it looks like a link, but the browser has
  // nothing to preview, copy or open in a tab.
  const _memberLinks = [...cv.querySelectorAll(".colltable td a")];
  ok(_memberLinks.length >= 2, "survey links: the member table must link every member survey, got " + _memberLinks.length);
  ok(_memberLinks.every(a => /^\/surveys\/(alpha|beta)$/.test(a.getAttribute("href") || "")),
    "survey links: every member link must target /surveys/<slug>, got " +
    JSON.stringify(_memberLinks.map(a => a.getAttribute("href"))));
  ok(cv.innerHTML.indexOf('data-act="story"') < 0 && cv.innerHTML.indexOf('href="#"') < 0,
    "survey links: no member link may be a JS-navigated href=\"#\" back into the drawer");
  // C: the rail (+ resize handle) are hidden on the full-width collection detail page too.
  ok(doc.getElementById("filterPane").classList.contains("hidden") && doc.getElementById("resizer").classList.contains("hidden"),
    "C: the rail + resize handle must be hidden on the collection detail page");
  const fbBefore = mapCalls.filter(c => c.fn === "fitBounds").length;
  collMapBtn.click();
  ok(A.curView() === "map", "E6: 'View all on main map' did not switch to the map view (setView)");
  ok(mapCalls.filter(c => c.fn === "fitBounds").length > fbBefore, "E6: 'View all on main map' did not call map.fitBounds to frame the collection");

  // HH. E7 DRAWER DIALOG SEMANTICS — role/aria-label, focus moves in on open, restores to the opener on close.
  A.setView("map");
  const opener = doc.getElementById("navSurveys");
  opener.focus();
  ok(doc.activeElement === opener, "E7: test setup — the opener element did not take focus");
  A.openStationById("au.alpha.A1");
  const drwF = doc.getElementById("drawer");
  ok(drwF.getAttribute("role") === "dialog" && (drwF.getAttribute("aria-label") || "").indexOf("A1") >= 0,
    "E7: the station drawer must be role=dialog with a subject aria-label, got: " + JSON.stringify(drwF.getAttribute("aria-label")));
  ok(drwF.contains(doc.activeElement) && doc.activeElement !== opener, "E7: focus must move INTO the drawer on open");
  drwF.querySelector(".close").click();
  ok(!drwF.classList.contains("open"), "E7: the close button did not close the drawer");
  ok(doc.activeElement === opener, "E7: focus must be RESTORED to the invoking element on close");

  // ===== UX8 (X2/X3/X5/X7) + C46-W3b =============================================================

  // X2. MAP LEGEND OVERLAYS THE MAP CONTAINER (bug fix). #mapLegend must be a child of #map (the Leaflet
  // container), NOT a flex sibling of #map inside #content — so it can never participate in that layout or
  // displace the map at load. FAILS on the pre-fix parenting (parent === "content").
  const legEl = doc.getElementById("mapLegend");
  ok(legEl && legEl.parentElement && legEl.parentElement.id === "map",
    "X2: the map legend must be parented INTO the map container (#map), got parent: " + (legEl && legEl.parentElement && legEl.parentElement.id));

  // X3 IS RETIRED WITH ITS SUBJECT. The UX8-X3 ruling was "a grouped map object never mixes surveys",
  // enforced first by groupMarkersBySurvey for cluster bubbles and then structurally by the badge router.
  // The map groups nothing now, so there is no object left that could mix two surveys.

  // X5. SCREENING INDICATORS — the five-row list is derived ONLY from computed quantities; each field->state
  // mapping is FALSIFIABLE (flip one input, exactly one indicator flips). An all-good baseline, then perturb.
  const baseInd = { q: 4.5, azR: 0.95, azN: 5, beta: 3, betaThr: 6, phaseSplit: 8, decades: 5 };
  const byKey = arr => Object.fromEntries(arr.map(it => [it.key, it]));
  const KEYS = ["smoothness", "strike", "pt", "phasesplit", "coverage"];
  const iBase = byKey(A.screeningIndicators(baseInd));
  ok(KEYS.every(k => iBase[k]), "X5: the five indicators (smoothness/strike/pt/phasesplit/coverage) must all be present");
  ok(KEYS.every(k => iBase[k].state === "green"), "X5: the all-good baseline must render every indicator green, got " + JSON.stringify(KEYS.map(k => k + ":" + iBase[k].state)));
  ok(KEYS.every(k => iBase[k].word && iBase[k].word.length), "X5: every indicator must carry a plain-language state word (never colour alone)");
  // q high->low flips ONLY Smoothness; nothing else changes (independent field mapping).
  const iQ = byKey(A.screeningIndicators({ ...baseInd, q: 2.0 }));
  ok(iQ.smoothness.state === "red", "X5: flipping q must flip Smoothness (green->red), got " + iQ.smoothness.state);
  ok(iQ.strike.state === "green" && iQ.pt.state === "green" && iQ.phasesplit.state === "green" && iQ.coverage.state === "green",
    "X5: flipping q must NOT change any other indicator");
  // strike concentration R high->low flips ONLY Strike stability.
  const iR = byKey(A.screeningIndicators({ ...baseInd, azR: 0.5 }));
  ok(iR.strike.state === "red" && iR.smoothness.state === "green", "X5: flipping the strike resultant length must flip ONLY Strike stability");
  // median |β| far above the PROV threshold flips Phase-tensor consistency; raising the ECHOED skew_3d_deg
  // threshold above the median |β| restores it (the indicator honours the provenance threshold).
  ok(byKey(A.screeningIndicators({ ...baseInd, beta: 20 })).pt.state === "red", "X5: median |β| far above betaThr must flip Phase-tensor consistency to red");
  ok(byKey(A.screeningIndicators({ ...baseInd, beta: 20, betaThr: 30 })).pt.state === "green",
    "X5: raising the ECHOED PROV skew_3d_deg above the median |β| must return the indicator to green (threshold honoured)");
  ok(byKey(A.screeningIndicators({ ...baseInd, phaseSplit: 50 })).phasesplit.state === "red", "X5: a large phase split must flip Phase split to red");
  ok(byKey(A.screeningIndicators({ ...baseInd, decades: 1 })).coverage.state === "red", "X5: narrow period coverage must flip Coverage to red");
  // a not-computable input renders neutral grey 'na' — NEVER a fabricated green.
  const iNA = byKey(A.screeningIndicators({ q: null, azR: null, azN: 0, beta: null, phaseSplit: null, decades: null }));
  ok(KEYS.every(k => iNA[k].state === "na"), "X5: a not-computable input must render 'na' (not evaluated), never a fabricated green, got " + JSON.stringify(KEYS.map(k => k + ":" + iNA[k].state)));
  ok(iNA.smoothness.word === "not evaluated", "X5: an 'na' indicator must say 'not evaluated'");
  // OWNER HIDE (2026-07-22): the Screening tab/panel is reversibly commented out in drawer.js pending design
  // review, so the RENDERED panel is ABSENT. The pure screeningIndicators() model above is UNCHANGED (helpers
  // left intact), so re-enabling the tab is uncommenting only. Restore the rendered-panel pins (five .indrow
  // rows + 'Show details' expander + strike prose) when the Screening surface returns.
  win.location.hash = "#/station/au.alpha.A1"; A.routeFromHash();
  const scP = doc.getElementById("dp-screening");
  ok(scP == null, "OWNER HIDE: the Screening panel (#dp-screening) must be ABSENT (owner-hidden pending design review)");
  ok(doc.getElementById("drawer").innerHTML.indexOf("Screening indicators") < 0,
    "OWNER HIDE: the 'Screening indicators' section must not render while the Screening surface is hidden");
  doc.getElementById("drawer").classList.remove("open");

  // X7. DATASET MATURITY — stars = achieved RECORD-STEWARDSHIP dimensions (NOT scientific quality). PURE
  // model, falsifiable: flip a dimension's input and the star count moves. sc[SC.sw] is index 3.
  const modFull = A.maturityModel({ lic: "CC-BY-4.0", doi: "10.1/x", ts: "ok" }, ["", "", "", "BIRRP"]);
  ok(modFull.total === 5, "X7: the maturity model must have 5 dimensions");
  ok(modFull.stars === 5, "X7: curated+repro+licence+doi+ts all present must give 5 stars, got " + modFull.stars);
  const modNoDoi = A.maturityModel({ lic: "CC-BY-4.0", ts: "ok" }, ["", "", "", "BIRRP"]);
  ok(modNoDoi.stars === modFull.stars - 1, "X7: removing the DOI must drop exactly one star, got " + modNoDoi.stars);
  ok(modNoDoi.dims.find(d => d.key === "doi").note === "not recorded", "X7: a missing DOI reads 'not recorded' (never 'pending')");
  const modNoTs = A.maturityModel({ lic: "CC-BY-4.0", doi: "10.1/x" }, ["", "", "", "BIRRP"]);
  ok(modNoTs.stars === modFull.stars - 2, "X7: removing the time series drops BOTH Reproducible and Time series (2 stars), got " + modNoTs.stars);
  ok(modNoTs.dims.find(d => d.key === "ts").note === "not available", "X7: a missing time series reads 'not available'");
  ok(A.maturityModel({ lic: "Bananas", doi: "10.1/x", ts: "ok" }, ["", "", "", "BIRRP"]).dims.find(d => d.key === "licence").achieved === false,
    "X7: an unrecognised licence must leave the 'Licence verified' dimension unachieved");
  // The RENDERED Provenance tab carries the ITEMISED rows only. OWNER RULING (2026-08-02): the aggregate
  // presentation was removed: the "Dataset maturity" heading, the five-star summary row and the
  // "Record-stewardship maturity ... Not a measure of scientific quality." explainer. The model above is
  // untouched (it still drives the per-row stars), so what is pinned here is the PRESENTATION.
  win.location.hash = "#/station/au.alpha.A1"; A.routeFromHash();
  const matP = doc.getElementById("dp-provenance");
  ok(!/Dataset maturity/.test(matP.textContent), "X7: the Provenance tab must no longer render the 'Dataset maturity' heading");
  ok(!matP.querySelector(".mat-stars"), "X7: the five-star maturity summary row must be gone");
  ok(!/Record-stewardship maturity/.test(matP.textContent), "X7: the maturity explainer sentence must be gone");
  ok(!/Not a measure of scientific quality/.test(matP.textContent), "X7: the not-scientific-quality explainer clause must be gone");
  ok(matP.querySelectorAll(".matdim").length === 5, "X7: the five itemised stewardship rows must survive the header removal");
  ok([...matP.querySelectorAll(".matdim")].every(li => li.querySelector(".matglyph") && /[★☆]/.test(li.querySelector(".matglyph").textContent)),
    "X7: every surviving stewardship row must keep its own star glyph");
  ok(/Curated archive/.test(matP.textContent) && /Licence verified/.test(matP.textContent),
    "X7: the surviving rows must still be labelled");
  // X6: the three always-visible provenance rows are present up top.
  ok(/Processing software/.test(matP.textContent) && /Source archive/.test(matP.textContent), "X6: the Provenance tab must show the software + source-archive summary rows");
  // X8: the Metadata & API box is a single small 'API' expander at the foot.
  ok([...matP.querySelectorAll("details summary")].some(su => su.textContent.trim() === "API"), "X8: the Provenance tab must carry a single 'API' expander");
  // api-docs lane: this used to pin the string "Read API (planned)". That text was retired because its
  // premise was false: the three paths it hedged (station json / survey json / station edi, all under an
  // /api prefix) were never served by any AusMT deployment, so "planned" dressed fiction as a roadmap.
  // The expander now lists the endpoints that DO resolve, templated with this station's own slug + id.
  // The needle below is assembled rather than written literally so this driver does not itself trip
  // tests/test_api_docs_section.py's repo-wide scan for that prefix.
  const _noApiTier = "/" + "api" + "/";
  ok(!/\(planned\)/.test(matP.textContent), "X8: the API expander must not hedge live endpoints as '(planned)'");
  ok(matP.textContent.indexOf(_noApiTier) < 0, "X8: the API expander must advertise no fictional API-tier path");
  ok(/\/data\/products\/alpha\/A1\/station\.json/.test(matP.textContent),
    "X8: the API expander must list this station's own products/<slug>/<id>/station.json endpoint");
  // Public-surface audit (2026-08-22), owner ruling: the only public metadata contracts are mtcat.json and
  // station.json; manifest.json is the download index; everything else under /data is portal-internal.
  // So the expander lists station.json + the download index, and must NOT advertise dimensionality.json
  // (served alongside station.json, not a contract), surveys.json (no contract) or the retired
  // products/manifest.json twin. tests/test_drawer_api_endpoints.py pins the same rows against fixtures.
  ok(!/dimensionality\.json/.test(matP.textContent),
    "X8: the API expander must not advertise dimensionality.json (served alongside station.json; not a contract)");
  ok(/\/data\/manifest\.json/.test(matP.textContent),
    "X8: the API expander must list /data/manifest.json, the download index");
  ok(!/\/data\/surveys\.json/.test(matP.textContent) && !/\/data\/products\/manifest\.json/.test(matP.textContent),
    "X8: the API expander must not advertise surveys.json or the retired products/manifest.json twin");
  // This fixture ships NO manifest (see the distributed-formats block below), so the station has no
  // served EDI artifact row and the expander must therefore render NO EDI endpoint line: the url can
  // only ever be read from a manifest row, never invented.
  ok(matP.textContent.indexOf("/data/edi/") < 0,
    "X8: with no manifest artifact row there is no EDI url to advertise, so no EDI line may be rendered");
  ok(/ausmt\.readthedocs\.io\/en\/latest\/interoperability\/api-reference\//.test(matP.innerHTML),
    "X8: the API expander must point at the docs site's API reference for worked examples (docs wave)");
  ok(!/about\.html#api/.test(matP.innerHTML),
    "X8: the retired About pointer must not survive alongside the docs API reference link");
  doc.getElementById("drawer").classList.remove("open");

  // MM. C46-W3b LICENCE CLASS via the CANON TABLES (not startsWith('CC')) + the attribution line.
  ok(A.licBadgeState("CC-BY-4.0") === "ok", "W3b: CC-BY-4.0 must badge 'ok' (redistributable)");
  ok(A.licBadgeState("cc0") === "ok" && A.licIsOpen("CC0-1.0") === true, "W3b: CC0 (alias) must resolve to redistributable/ok");
  ok(A.licBadgeState("ODbL") === "ok", "W3b: a non-CC OPEN licence (ODbL) must badge 'ok' — the startsWith('CC') guess would have missed it");
  ok(A.licBadgeState("ALL RIGHTS RESERVED") === "part" && A.licIsOpen("ALL RIGHTS RESERVED") === false,
    "W3b: a recognised-but-not-open licence must badge 'part' and NOT count as open");
  ok(A.licBadgeState("Bananas 2.0") === "unk", "W3b: an unrecognised licence must badge 'unk'");
  ok(A.licBadgeState(null) === "unk", "W3b: an absent licence must badge 'unk'");
  ok(A.attributionText({ attribution: { statement: "Cite me verbatim." } }) === "Cite me verbatim.", "W3b: a verbatim attribution.statement must win");
  ok(A.attributionText({ org: "GSSA", dates: "2019-2020" }) === "GSSA (2020)", "W3b: with no statement, synthesise org (last year)");
  ok(A.attributionText({ org: "GSSA" }) === "GSSA", "W3b: no year -> org with no year (no fabrication)");

  // NN. C46-W3b RENDER — attribution statement, source-datasets list, provGraph source node, Cite fallback.
  // Poke Alpha with an attribution statement + a source (the base fixture carries neither). Done LAST so it
  // cannot perturb the earlier Alpha assertions.
  A.setSMETA("Alpha Survey", {
    attribution: { custodian: "GSSA", statement: "GSSA (2020). Alpha survey." },
    sources: [{ title: "Alpha raw archive", custodian: "GSSA", identifier: "10.5555/alpha-src", licence: "CC-BY-3.0-AU", profile: "generic" }],
  });
  const drwN = doc.getElementById("drawer"); drwN.classList.remove("open");
  win.location.hash = "#/station/au.alpha.A1"; A.routeFromHash();
  ok(/GSSA \(2020\)\. Alpha survey\./.test(doc.getElementById("dp-cite").textContent), "W3b: the Cite tab must render the verbatim attribution statement");
  const provN = doc.getElementById("dp-provenance");
  ok(/Source dataset/.test(provN.textContent) && /10\.5555\/alpha-src/.test(provN.innerHTML),
    "W3b: the lineage graph must gain an upstream 'Source dataset' node with the source identifier when sources[] exists");
  drwN.classList.remove("open");
  win.location.hash = "#/survey/alpha"; A.routeFromHash();
  ok(/GSSA \(2020\)\. Alpha survey\./.test(drwN.textContent), "W3b: the survey detail must render the attribution statement");
  // C1/R3 moves the licence half of this pin from the SPDX identifier to the reader's form: the row is
  // chrome. The canonicalisation is unchanged (licCanon still resolves aliases and case); what moved is
  // only how the canonical id is READ. Two assertions where there was one, so the pin is not weakened.
  ok(/Source datasets/.test(drwN.textContent) && /Alpha raw archive/.test(drwN.textContent) && /CC BY 3\.0 AU/.test(drwN.textContent),
    "W3b + C1/R3: the survey detail must render the 'Source datasets' list (title + licence in the reader's form)");
  ok(!/CC-BY-3\.0-AU/.test(drwN.textContent),
    "C1/R3: the Source datasets row must not print the SPDX identifier as chrome");
  // Cite EXPLICIT fallback: Beta has no cite block -> the drawer must SAY so, never silently self-attribute.
  drwN.classList.remove("open");
  win.location.hash = "#/station/au.beta.B1"; A.routeFromHash();
  ok(/custodian citation not recorded/i.test(doc.getElementById("dp-cite").textContent),
    "W3b: a no-cite survey's Cite tab must explicitly say 'custodian citation not recorded, cite the survey package', not a silent AUSMT_SELF masquerade");
  drwN.classList.remove("open");

  // CR. CONTRIBUTOR CREDIT MODEL (CONTRIBUTOR-CREDIT-SPEC §3/§6): the survey drawer renders contributors[]
  // with human role phrases, and the stale lead/principal-investigator display (the survey-summary
  // 'investigators' row served from the retired keys) is gone. Poke Gamma (base fixture carries no credit
  // lists) with the pinned seam shape: a person ProjectLeader with an ORCID, an org DataCollector with no
  // ROR, a person DataCurator with an ORCID, an org Distributor with a real ROR, and a person ContactPerson
  // with no ORCID, using real corpus names/RORs. RED-proven: on pre-change drawer.js none of the role-phrase
  // spans render AND the 'investigators' summary row is still present, so each pin below flips.
  A.setSMETA("Gamma Survey", { contributors: [
    { name: "Stephan Thiel", name_type: "person", role: "ProjectLeader", orcid: "0000-0002-8678-412X" },
    { name: "Zonge Engineering", name_type: "organisation", role: "DataCollector" },
    { name: "Ben Kay", name_type: "person", role: "DataCurator", orcid: "0000-0002-9738-7277" },
    { name: "Geological Survey of South Australia", name_type: "organisation", role: "Distributor", ror: "https://ror.org/028g18b61" },
    { name: "Graham Heinson", name_type: "person", role: "ContactPerson" },
  ] });
  A.openSurvey("Gamma Survey");
  const drwCr = doc.getElementById("drawer"), crH = drwCr.innerHTML;
  // Card-credit rework: contributors are a COLLAPSED <details> grouped by person; the summary reads
  // "Contributors (N)" where N is the distinct people/orgs (here 5 single-role people).
  ok(/>Contributors \(5\)</.test(crH),
    "CREDIT: a Contributors <details> summary reads 'Contributors (N)' (N = distinct people) when contributors[] is present, got: " + (crH.match(/Contributors \([^)]*\)/) || ["<none>"])[0]);
  ok(/<span class="prov">led<\/span>/.test(crH), "CREDIT: a ProjectLeader must render the 'led' role phrase");
  ok(/<span class="prov">collected the data<\/span>/.test(crH), "CREDIT: a DataCollector must render 'collected the data'");
  ok(/<span class="prov">curated<\/span>/.test(crH), "CREDIT: a DataCurator must render 'curated'");
  ok(/<span class="prov">distributed<\/span>/.test(crH), "CREDIT: a Distributor must render 'distributed'");
  ok(/<span class="prov">contact<\/span>/.test(crH), "CREDIT: a ContactPerson must render 'contact'");
  ok(/Stephan Thiel/.test(crH) && /orcid\.org\/0000-0002-8678-412X/.test(crH),
    "CREDIT: a person contributor renders their name plus the ORCID icon-link when an ORCID is present");
  ok(/Geological Survey of South Australia/.test(crH) && /ror\.org\/028g18b61/.test(crH),
    "CREDIT: an organisation contributor's name links to its ROR when present");
  ok(/Zonge Engineering/.test(crH), "CREDIT: an organisation contributor with no ROR renders its plain name (no '(no PID)' suffix)");
  ok(/<details class="prov-d survey-contributors">/.test(crH),
    "CREDIT: contributors render inside a <details class='prov-d ...'> collapsed like the Persistent identifiers rollup");
  ok(!/>investigators</.test(crH),
    "CREDIT retirement: the stale survey-summary 'investigators' row (served from the retired lead/principal-investigator keys) must be gone");
  drwCr.classList.remove("open");
  // Graceful absence: Beta carries no contributors[] and no creators[] -> NO Contributors <details> AND the
  // Attribution block renders exactly as before (no attribution names line, no label, no gloss).
  A.openSurvey("Beta Survey");
  const betaH = doc.getElementById("drawer").innerHTML;
  ok(!/Contributors \(/.test(betaH),
    "CREDIT: a survey with no contributors[] must render NO Contributors <details> (no summary, no placeholder)");
  const betaAttn = [...doc.getElementById("drawer").querySelectorAll(".attn")];
  ok(/>Attribution/.test(betaH) && betaAttn.length === 1 && betaAttn[0].querySelector("a") === null,
    "CREDIT: a survey with no creators[] renders the ONE attribution box as the flat sentence (no names line, no links), got " + betaAttn.length + " boxes");
  ok(!/Cited authors/.test(betaH) && !/credited whenever this dataset is cited/.test(betaH),
    "CREDIT: no 'Cited authors' label and no citation gloss ever render");
  doc.getElementById("drawer").classList.remove("open");

  // PC. PORTAL-CLEANUP WAVE (stage 1). Three cleanups, poked onto Gamma (the base fixture carries none of
  // these, so nothing earlier is perturbed): the survey-card CREATORS section (ordered citation authors with
  // ORCID/ROR links, adjacent to Attribution); the pubCite DOI-URL NORMALISATION + null-field grace; and the
  // Provenance-tab SOURCE ARCHIVE derived from the typed related_identifiers by data level. RED-proven against
  // origin/main drawer.js: no Creators section renders, a URL-form pub DOI double-prefixes the resolver, and
  // the Source archive shows the dataset-DOI / "not recorded" rather than the raw_packed level identifier.
  A.setSMETA("Gamma Survey", {
    creators: [
      { name: "Kate Robertson", name_type: "person", orcid: "0000-0002-1111-2222" },
      { name: "Geological Survey of South Australia", name_type: "organisation", ror: "https://ror.org/028g18b61" },
    ],
    // Faithful to what the engine SERVES: CONTRIBUTOR-CREDIT-SPEC §2.1 builds cite.au from creators[]
    // ("; "-joined, in order), so the attribution sentence and the creator names are the same names.
    // dates gives the sentence its "(year)" tail.
    dates: "2019", cite: { au: "Kate Robertson; Geological Survey of South Australia", yr: "2019",
                           ti: "Gamma Survey magnetotelluric transfer functions", ve: "", pb: "OrgZ" },
    related_identifiers: [
      { identifier: "10.25914/gamma-raw", identifier_type: "DOI", relation: "IsDerivedFrom", custodian: "NCI", identifies: "raw_packed" },
      { identifier: "10.25914/gamma-coll", identifier_type: "DOI", relation: "IsPartOf", custodian: "NCI", identifies: "collection" },
    ],
    funders: [{ name: "Australian Research Council", pid: "https://ror.org/05mmh0f86", grant_id: "ADI RD02-260" }],
    pubs: [
      { a: "Robertson, K.", y: "2023", t: "Deep conductors beneath Gamma", j: "Geophys. J. Int.", doi: "https://doi.org/10.1093/gji/ggad999" },
      { t: "An untitled note on the Gamma survey", doi: "10.5555/gamma-note" },
    ],
  });
  // (1) ONE ATTRIBUTION BOX (owner ruling, card-lane polish). The Attribution section renders EXACTLY ONE
  //     .attn box. When creators[] drive the attribution (§2.1: cite.au IS the "; "-joined creators) that
  //     single box carries the SAME sentence with each name ORCID/ROR-linked in place, keeping the "; "
  //     separators and the "(year)" tail; there is never a second names box. RED on origin/main: TWO
  //     visually identical .attn boxes render (the sentence, then a separate ' · '-joined names line).
  A.openSurvey("Gamma Survey");
  const drwPC = doc.getElementById("drawer"), pcH = drwPC.innerHTML;
  ok(!/>Creators</.test(pcH),
    "PC: no standalone Creators section/heading remains (creators fold into the Attribution block)");
  const attnBoxes = [...drwPC.querySelectorAll(".attn")];
  ok(attnBoxes.length === 1,
    "ONEBOX: the Attribution section must render EXACTLY ONE .attn box (the sentence with the names linked in place), got " + attnBoxes.length);
  ok(!/attribution-authors/.test(pcH),
    "ONEBOX: the separate attribution names box (.attribution-authors) must be gone entirely");
  // The box's TEXT is the plain attribution sentence (the string exports.attributionLine mirrors), so
  // linking the names never changes what the attribution says. The ORCID icon-link is an IMAGE with no
  // text, so extracting textContent leaves the space that separates a name from its icon dangling before
  // the "; " separator (the rendered line is correct); collapse that before comparing.
  const attnText = el => el.textContent.replace(/\s+/g, " ").replace(/\s+([;,.])/g, "$1").trim();
  ok(attnText(attnBoxes[0]) === "Kate Robertson; Geological Survey of South Australia (2019)",
    "ONEBOX: the box must read the attribution sentence with '; ' separators and the '(year)' tail, got: " + JSON.stringify(attnText(attnBoxes[0])));
  ok(attnText(attnBoxes[0]) === A.attributionText(A.smeta("Gamma Survey")),
    "ONEBOX: the rendered box text must equal attributionText(m) exactly (the CSV / citation-pack attribution string)");
  ok(/Kate Robertson/.test(attnBoxes[0].innerHTML) && /orcid\.org\/0000-0002-1111-2222/.test(attnBoxes[0].innerHTML),
    "ONEBOX: a person creator is ORCID-linked INSIDE the one attribution box");
  ok(/Geological Survey of South Australia/.test(attnBoxes[0].innerHTML) && /ror\.org\/028g18b61/.test(attnBoxes[0].innerHTML),
    "ONEBOX: an organisation creator's name links to its ROR INSIDE the one attribution box");
  ok(attnBoxes[0].innerHTML.indexOf("Kate Robertson") < attnBoxes[0].innerHTML.indexOf("Geological Survey of South Australia"),
    "ONEBOX: creators must render in their declared attribution order (person before org here)");
  ok(pcH.indexOf(">Attribution") < pcH.indexOf("Kate Robertson") && pcH.indexOf("Kate Robertson") < pcH.indexOf(">Downloads<"),
    "ONEBOX: the attribution box sits after the Attribution heading and ahead of Downloads");
  ok(!/Cited authors/.test(pcH) && !/credited whenever this dataset is cited/.test(pcH),
    "PC: the attribution box carries NO 'Cited authors' label and NO citation gloss (attribution, not citation)");
  // (1b) CONTRIBUTORS PLACEMENT (owner ruling): the collapsed "Contributors (N)" details moves out from
  //      below Downloads to sit directly beneath the attribution box, inside the Attribution block. RED on
  //      origin/main: the details renders AFTER the Downloads grid.
  ok(/survey-contributors/.test(pcH), "PLACE: setup, Gamma must still carry its contributors <details>");
  ok(pcH.indexOf('class="attn"') < pcH.indexOf("survey-contributors"),
    "PLACE: the Contributors details must sit directly BENEATH the attribution box");
  ok(pcH.indexOf("survey-contributors") < pcH.indexOf(">Downloads<"),
    "PLACE: the Contributors details must sit ABOVE the Downloads section (it used to trail below it)");
  // (2) FUNDING grant id: the funder's grant_id is appended to the Funding section (2 live rows in the corpus).
  const _fundBlock = (pcH.split(">Funding<")[1] || "").split(">Related publications<")[0];
  ok(/Australian Research Council/.test(_fundBlock) && /ADI RD02-260/.test(_fundBlock),
    "PC: a funder's grant_id must be appended in the Funding section, got: " + _fundBlock);
  // (3) pubCite: a URL-form DOI must resolve to a SINGLE doi.org prefix (no double prefix), and a pub missing
  //     author/year/journal must still render its title + link with no empty "(). ." citation skeleton.
  ok(pcH.indexOf('href="https://doi.org/10.1093/gji/ggad999"') >= 0,
    "PC: a URL-form pub DOI must normalise to a single doi.org prefix, got: " + (pcH.match(/href="[^"]*gji[^"]*"/) || [""])[0]);
  ok(pcH.indexOf("doi.org/https") < 0, "PC: a URL-form pub DOI must not double-prefix the resolver");
  ok(/An untitled note on the Gamma survey/.test(pcH) && pcH.indexOf('href="https://doi.org/10.5555/gamma-note"') >= 0,
    "PC: a pub with null author/year/journal must still render its title + DOI link");
  ok((pcH.split(">Related publications<")[1] || "").indexOf("(). ") < 0,
    "PC: a null-field pub must not render the empty '(). .' citation skeleton");
  drwPC.classList.remove("open");
  // (4) SOURCE ARCHIVE (station Provenance tab): derived from related_identifiers by level, raw_packed
  //     preferred over collection, rendered as that level's own DOI link. RED on origin/main (the row shows
  //     the dataset DOI / "not recorded", never the raw_packed identifier).
  win.location.hash = "#/station/nz.gamma.G1"; A.routeFromHash();
  const pcProv = doc.getElementById("dp-provenance");
  const _srcRow = [...pcProv.querySelectorAll("tr")].find(tr => /Source archive/.test(tr.textContent));
  ok(_srcRow, "PC: the Provenance tab must carry a 'Source archive' row");
  ok(/href="https:\/\/doi\.org\/10\.25914\/gamma-raw"/.test(_srcRow.innerHTML),
    "PC: the Source archive must derive from the raw_packed related_identifier (preferred over collection), got: " + _srcRow.innerHTML);
  ok(_srcRow.innerHTML.indexOf("not recorded") < 0,
    "PC: the Source archive must not read 'not recorded' when a level identifier exists");
  doc.getElementById("drawer").classList.remove("open");

  // GC. GROUPED CONTRIBUTORS (card-credit rework). The per-(person, role) list is replaced by a collapsed
  // <details> GROUPED by person: 7 distinct people/orgs across 15 declared (person, role) rows must render as
  // ONE line each with roles comma-joined in the RATIFIED order (ProjectLeader, ProjectMember, DataCollector,
  // ContactPerson, DataCurator, Sponsor, RightsHolder, Distributor), deduping by ORCID (case / URL-form
  // insensitive) else name + name_type, dropping a nameless row and an out-of-vocab role SILENTLY. RED-proven
  // (tools/../scratchpad red-proof + these pins flip on origin/main drawer.js): the pre-change contributorsHtml
  // renders one <br>-joined line PER ROW with no "Contributors (7)" summary, never the grouped "led, curated"
  // phrase, and no survey-contributors <details> at all. Poked onto Delta (embargoed, but the survey drawer
  // renders contributors regardless of access; no earlier/later pin asserts Delta's contributors).
  A.setSMETA("Delta Survey", { contributors: [
    { name: "Alice Anderson",    name_type: "person",       role: "DataCurator",   orcid: "0000-0001-0000-0001" },
    { name: "Alice Anderson",    name_type: "person",       role: "ProjectLeader", orcid: "0000-0001-0000-0001" },
    { name: "Bob Brown",         name_type: "person",       role: "DataCollector", orcid: "0000-0001-0000-0002" },
    { name: "Bob Brown",         name_type: "person",       role: "ProjectMember", orcid: "0000-0001-0000-0002" },
    { name: "Carol Chen",        name_type: "person",       role: "ContactPerson" },
    { name: "Carol Chen",        name_type: "person",       role: "Editor" },                                    // out-of-vocab -> no phrase, no new person
    { name: "Zonge Engineering", name_type: "organisation", role: "DataCollector" },
    { name: "Zonge Engineering", name_type: "organisation", role: "Distributor" },
    { name: "Geological Survey of South Australia", name_type: "organisation", role: "RightsHolder", ror: "https://ror.org/028g18b61" },
    { name: "Geological Survey of South Australia", name_type: "organisation", role: "Distributor",  ror: "https://ror.org/028g18b61" },
    { name: "Geological Survey of South Australia", name_type: "organisation", role: "Sponsor",      ror: "https://ror.org/028g18b61" },
    { name: "David Davies",      name_type: "person",       role: "ProjectMember", orcid: "0000-0003-1234-5678" },
    { name: "D. Davies",         name_type: "person",       role: "ProjectLeader", orcid: "https://orcid.org/0000-0003-1234-5678" }, // SAME ORCID, URL-form -> same person
    { name: "Eve Evans",         name_type: "person",       role: "Sponsor",       orcid: "0000-0005-0000-0005" },
    { name: "",                  name_type: "person",       role: "ProjectMember", orcid: "0000-0009-0000-0009" }, // nameless -> dropped, uncounted
  ] });
  A.openSurvey("Delta Survey");
  const drwGC = doc.getElementById("drawer"), gcH = drwGC.innerHTML;
  const gcBlock = (gcH.split("survey-contributors")[1] || "").split("</details>")[0];   // the contributors <details> only ("" on pre-change)
  // Distinct count = 7 (the two Davies rows collapse by ORCID URL-form; the nameless row is dropped). One number
  // proves BOTH the URL-form ORCID dedup and the nameless-row drop. RED: pre-change renders no "Contributors (N)".
  ok(/>Contributors \(7\)</.test(gcH),
    "GROUP: the Contributors summary counts DISTINCT people/orgs (7 from 15 rows), got: " + (gcH.match(/Contributors \([^)]*\)/) || ["<none>"])[0]);
  // 7 distinct people => 7 lines => 6 <br> separators inside the collapsed <details>. RED: no such block exists.
  ok((gcBlock.match(/<br>/g) || []).length === 6,
    "GROUP: 7 distinct people render as 7 lines (6 <br> separators) inside the collapsed details, got sep count: " + (gcBlock.match(/<br>/g) || []).length);
  ok(/<details class="prov-d survey-contributors">/.test(gcH),
    "GROUP: contributors render inside a <details class='prov-d survey-contributors'> collapsed like the Persistent identifiers rollup");
  // Roles join in the RATIFIED order regardless of declared order: Alice declared DataCurator BEFORE
  // ProjectLeader -> "led, curated"; and she appears exactly once (grouped). RED: pre-change never joins.
  ok(/led, curated/.test(gcH) && (gcH.match(/Alice Anderson/g) || []).length === 1,
    "GROUP: a multi-role person groups to ONE line with roles in the ratified order (led, curated)");
  ok(/project member, collected the data/.test(gcH),
    "GROUP: role phrases sort into the ratified order regardless of declared order (ProjectMember before DataCollector)");
  ok(/sponsored, rights holder, distributed/.test(gcH),
    "GROUP: an org's three roles join in the ratified order (Sponsor, RightsHolder, Distributor)");
  ok(/collected the data, distributed/.test(gcH),
    "GROUP: an org with two roles joins them in ratified order (DataCollector before Distributor)");
  // ORCID URL-form-insensitive dedup: bare "0000-..." and "https://orcid.org/0000-..." collapse to ONE person,
  // first-appearance name ("David Davies") wins, the second-form name ("D. Davies") never renders.
  ok((gcH.match(/David Davies/g) || []).length === 1 && !/D\. Davies/.test(gcH) && /led, project member/.test(gcH),
    "GROUP: two rows sharing an ORCID (bare vs https://orcid.org/ URL form) collapse to ONE person; first-appearance name wins");
  // Out-of-vocab role adds no phrase and is never echoed as a raw token; the person still renders once.
  ok((gcH.match(/Carol Chen/g) || []).length === 1 && gcH.indexOf("Editor") < 0,
    "GROUP: an out-of-vocab role adds no phrase and is never echoed as a raw token; the person still renders once");
  // Nameless row dropped silently: neither its name nor its ORCID render, and it is not counted (7, not 8).
  ok(gcH.indexOf("0000-0009-0000-0009") < 0,
    "GROUP: a nameless contributor row is dropped silently (its ORCID never renders, uncounted)");
  drwGC.classList.remove("open");

  // LG. LINEAGE + PROVENANCE POLISH (owner ruling, from live screenshots). Four fixes in the station
  // drawer's Provenance tab, driven on Gamma's G1 (its survey already carries the pubs[] poked in section
  // PC, and no later section pins Gamma's provenance):
  //   (a) the processing-software node shows the MOST SPECIFIC versioned string available (station-level
  //       first, survey-level fallback, never an invented version) and reads the SAME string as the
  //       Provenance tab's own row;
  //   (b) the collapsed pipeline section is titled "AusMT Provenance" (it is the AusMT pipeline's run, not
  //       the custodian's MT data processing) and the old title is gone;
  //   (c) the distributed-formats node lists ONLY the formats actually served, dot-separated, with no
  //       ticks and no "(pipeline)" qualifier. RED on origin/main: it always claimed "EDI ✓ · EMTF XML
  //       (pipeline)" even where the manifest serves neither;
  //   (d) the publication node reads the survey's pubs[], not the dataset DOI. RED on origin/main: Gamma
  //       has two publications and no dataset DOI, so the node read "none recorded" (the live Newer
  //       Volcanic Province 2019 case: a 2023 paper on the card, "none recorded" in the lineage).
  // The lineage rows are label/value pairs; read the VALUE of one node by its label so a match can never
  // be satisfied by unrelated text elsewhere in the tab (the format-availability badges also say "EMTF XML").
  const lineageValue = (panel, label) => {
    const row = [...panel.querySelectorAll(".lineage .lrow")]
      .find(r => r.querySelector(".lt") && r.querySelector(".lt").textContent.trim() === label);
    return row ? row.querySelector(".lv") : null;
  };
  // (a) PURE derivation: station-level wins, survey-level is the fallback, neither invents a version.
  ok(A.processingSoftwareText({ software: "Geotools" }, ["", "", "", "Geotools 4.0.5.12583"]) === "Geotools 4.0.5.12583",
    "SOFTWARE: the station-level versioned string must win over the bare survey-level software field");
  ok(A.processingSoftwareText({ software: "Geotools 4.0.5.12583" }, []) === "Geotools 4.0.5.12583",
    "SOFTWARE: with no station-level string, the survey-level software field is the fallback");
  ok(A.processingSoftwareText({}, []) === "not stated in EDI",
    "SOFTWARE: with neither, the honest 'not stated in EDI' stands (no version is ever synthesised)");
  // (a, rendered) Gamma declares an UNVERSIONED survey-level software while its stations carry the EDI's
  // own string: both the lineage node and the Provenance row must show the specific one, and agree.
  A.setSMETA("Gamma Survey", { software: "Geotools" });
  A.openStationById("nz.gamma.G1");
  const lgProv = doc.getElementById("dp-provenance");
  const lgSwNode = lineageValue(lgProv, "Processing software");
  const lgSwRow = [...lgProv.querySelectorAll("tr")].find(tr => /Processing software/.test(tr.textContent));
  ok(lgSwNode && lgSwRow, "SOFTWARE: the Provenance tab must carry both a processing-software lineage node and row");
  ok(lgSwNode.textContent.trim() === "BIRRP",
    "SOFTWARE: the lineage node must show the station-level string, got: " + JSON.stringify(lgSwNode.textContent.trim()));
  ok(lgSwNode.textContent.trim() === lgSwRow.cells[1].textContent.trim(),
    "SOFTWARE: the lineage node and the Provenance row must read the SAME string, got: " +
    JSON.stringify([lgSwNode.textContent.trim(), lgSwRow.cells[1].textContent.trim()]));
  // (b) the collapsed pipeline section is retitled; the old title survives nowhere in the tab.
  ok([...lgProv.querySelectorAll("details summary")].some(su => su.textContent.trim() === "AusMT Provenance"),
    "TITLE: the collapsed pipeline section must be titled 'AusMT Provenance', got: " +
    JSON.stringify([...lgProv.querySelectorAll("details summary")].map(su => su.textContent.trim())));
  ok(!/processing provenance/i.test(lgProv.textContent),
    "TITLE: the old 'Processing provenance' title must be gone from the Provenance tab");
  // (c) distributed formats: exactly the served set, dot-separated, no ticks and no "(pipeline)" claim.
  //     The fixture ships NO manifest, so G1 is the served-EDI-only case (edi_available=1, open access):
  //     the unserved XML and MTH5 must simply be ABSENT, never claimed.
  const lgFmtEdi = lineageValue(doc.getElementById("dp-provenance"), "Distributed formats");
  ok(lgFmtEdi && lgFmtEdi.textContent.trim() === "EDI",
    "FORMATS: an unserved format must be ABSENT from the list, not claimed, got: " +
    JSON.stringify(lgFmtEdi && lgFmtEdi.textContent.trim()));
  // All three served: three per-station manifest files[] rows. The MTH5 entry is the STATION's own h5,
  // never the survey's <slug>-tf.h5 bundle: this node sits in a STATION drawer beside a Files tab that
  // reads the station row, and the discriminating case (bundle present, station row absent) is pinned
  // under STATION-H5 below.
  A.setManifest({ files: [
    { ausmt_id: "nz.gamma.G1", format: "edi", url: "files/g1.edi", size: 1000 },
    { ausmt_id: "nz.gamma.G1", format: "emtfxml", url: "files/g1.xml", size: 900 },
    { ausmt_id: "nz.gamma.G1", format: "mth5", url: "files/g1.h5", size: 5000 },
  ], bundles: [] });
  A.openStationById("nz.gamma.G1");
  const lgFmtAll = lineageValue(doc.getElementById("dp-provenance"), "Distributed formats");
  ok(lgFmtAll && lgFmtAll.textContent.trim() === "EDI · EMTF XML · MTH5",
    "FORMATS: all three served must list dot-separated with no ticks and no '(pipeline)', got: " +
    JSON.stringify(lgFmtAll && lgFmtAll.textContent.trim()));
  ok(lgFmtAll.textContent.indexOf("✓") < 0 && lgFmtAll.textContent.indexOf("(pipeline)") < 0,
    "FORMATS: the node must carry neither a tick nor the '(pipeline)' qualifier");
  A.setManifest(null);                                   // restore the fixture's manifest-less state
  // An EMBARGOED station (Delta D1: access embargoed, no served EDI, no bundle) claims NOTHING.
  A.openStationById("au.delta.D1");
  const lgFmtNone = lineageValue(doc.getElementById("dp-provenance"), "Distributed formats");
  ok(lgFmtNone && lgFmtNone.textContent.trim() === "none currently served",
    "FORMATS: an embargoed station must claim no distributed format at all, got: " +
    JSON.stringify(lgFmtNone && lgFmtNone.textContent.trim()));
  // (d) publication node: pubs[]-driven, short cite + "+N more", DOI-linked, and never "none recorded"
  //     for a survey that HAS publications. PURE short-cite rules first (no fabricated co-authors).
  ok(A.pubShortCite({ a: "Robertson, K.", y: "2023" }) === "Robertson, K. (2023)",
    "PUB: a single 'Last, First' author must never gain a fabricated 'et al.', got: " + A.pubShortCite({ a: "Robertson, K.", y: "2023" }));
  ok(A.pubShortCite({ a: "Kay B, Heinson G, Thiel S", y: "2023" }) === "Kay B et al. (2023)",
    "PUB: three or more comma-separated authors collapse to the first author + et al.");
  ok(A.pubShortCite({ a: "Robertson, K.; Thiel, S.", y: "2023" }) === "Robertson, K. et al. (2023)",
    "PUB: a '; '-separated author list collapses on that unambiguous separator");
  ok(A.pubShortCite({ t: "An untitled note", doi: "10.5555/x" }) === "An untitled note",
    "PUB: a row with no author falls back to its title (never an empty cite)");
  A.openStationById("nz.gamma.G1");
  const lgPub = lineageValue(doc.getElementById("dp-provenance"), "Publication (interpretation)");
  ok(lgPub, "PUB: the lineage publication node must be labelled 'Publication (interpretation)'");
  ok(lgPub.textContent.indexOf("none recorded") < 0,
    "PUB: a survey WITH publications must not read 'none recorded' (the live Newer Volcanic Province bug)");
  ok(/Robertson, K\. \(2023\)/.test(lgPub.textContent),
    "PUB: the node must show the first publication as a short cite, got: " + JSON.stringify(lgPub.textContent.trim()));
  ok(/\(\+1 more\)/.test(lgPub.textContent),
    "PUB: a second publication must add a '+N more' tail, got: " + JSON.stringify(lgPub.textContent.trim()));
  ok(lgPub.innerHTML.indexOf('href="https://doi.org/10.1093/gji/ggad999"') >= 0 && lgPub.innerHTML.indexOf("doi.org/https") < 0,
    "PUB: the short cite links to the publication DOI with a single doi.org prefix, got: " + lgPub.innerHTML);
  // A survey with NO publications keeps the honest "none recorded" (Beta declares none).
  A.openStationById("au.beta.B1");
  const lgPubNone = lineageValue(doc.getElementById("dp-provenance"), "Publication (interpretation)");
  ok(lgPubNone && lgPubNone.textContent.trim() === "none recorded",
    "PUB: a survey with no publications must still read 'none recorded', got: " + JSON.stringify(lgPubNone && lgPubNone.textContent.trim()));

  // (e) LINEAGE: the file WRITER is not the PROCESSOR. The graph used to publish the EDI HEAD's program
  //     stamp under "Processing software" — Geotools / WinGLink / MTpy, i.e. whatever SERIALISED the file,
  //     which for most of the corpus estimated nothing. The writer now has its OWN row, read from
  //     station.json (the same fetch as the frame line), and a known exporter is annotated as one.
  //     PURE derivation first, then the rendered row.
  ok(A.fileWrittenByText({ name: "Geotools", version: "4.0.5.12583" }) === "Geotools 4.0.5.12583 (database/file export)",
    "WRITER: a known exporter must render with its version and the export annotation, got: " +
    JSON.stringify(A.fileWrittenByText({ name: "Geotools", version: "4.0.5.12583" })));
  ok(A.fileWrittenByText({ name: "EMpower", version: "v1.54.2.5" }) === "EMpower v1.54.2.5",
    "WRITER: a program that is not a known exporter carries no annotation (it may have done the processing)");
  ok(A.fileWrittenByText({}) === "not stated in EDI",
    "WRITER: a file that names no writer says so; nothing is inferred from the processor");
  A.openStationById("nz.gamma.G1");
  const lgWriter = lineageValue(doc.getElementById("dp-provenance"), "File written by");
  ok(lgWriter, "WRITER: the lineage must carry a 'File written by' node distinct from 'Processing software'");
  // The fixture serves no products/ tree, so the station.json fetch cannot resolve — which must read as a
  // load failure, never as a claim about what the file states.
  ok(/loading…|could not be loaded/.test(lgWriter.textContent),
    "WRITER: with no station.json served the cell must read as loading/unloadable, got: " +
    JSON.stringify(lgWriter.textContent.trim()));
  // An EMBARGOED station serves no station.json science at all, so the row is ABSENT rather than
  // permanently loading — the same absence discipline the withheld download affordance uses.
  A.openStationById("au.delta.D1");
  ok(!lineageValue(doc.getElementById("dp-provenance"), "File written by"),
    "WRITER: an embargoed station must not carry a writer row that can never resolve");
  // (f) METHOD: the row rendered unconditionally and read "not stated" on nearly every station, because
  //     the structured fields behind it are empty for most EDI dialects. It renders only where the source
  //     states an algorithm or remote reference. Gamma's fixture row states both, so it is PRESENT there;
  //     a station whose sci row states neither drops the row instead of printing noise.
  A.openStationById("nz.gamma.G1");
  ok(lineageValue(doc.getElementById("dp-provenance"), "Method"),
    "METHOD: a station whose sci row states an algorithm must keep the Method node");
  A.setSciRow("nz.gamma.G1", { alg: null, rr: 0 });
  A.openStationById("nz.gamma.G1");
  const lgMethodGone = doc.getElementById("dp-provenance");
  ok(!lineageValue(lgMethodGone, "Method"),
    "METHOD: with neither an algorithm nor a stated remote reference the node must be OMITTED, not 'not stated'");
  ok(lgMethodGone.textContent.indexOf("not stated</div>") < 0 && !/>not stated</.test(lgMethodGone.innerHTML),
    "METHOD: the retired 'not stated' cell must survive nowhere in the lineage");
  ok(lineageValue(lgMethodGone, "Processing software"),
    "METHOD: dropping the Method node must not disturb the rows around it");
  A.restoreSciRows();
  doc.getElementById("drawer").classList.remove("open");

  // OO. CVD-SAFE COMPLETENESS RAMP (UX8 amendment). The old red→amber→green ramp's endpoints measured
  // dE76≈9.6 under a deuteranopia simulation — indistinguishable for red-green CVD readers. The ramp is
  // now a SEQUENTIAL dark→light progression whose SIGNAL IS LIGHTNESS (viridis principle): dark slate-blue
  // #2A3B66 → olive #6E7F46 → pale warm yellow #F2E27E (simulated low↔high separation deutan 106.8 /
  // protan 103.1 / tritan 69.1 dE76 — thresholds ≥25/≥25/≥15). Pins:
  //   (a) the EXACT stop hexes at q=2 / 3.5 / 5 (a wrong-endpoint mutation fails here — these hexes are
  //       what the simulation numbers were measured on);
  //   (b) relative luminance is MONOTONE NON-DECREASING across q=2..5 — the structural property that makes
  //       the ramp CVD-safe. The old ramp FAILS this (red→amber rises, amber→green falls), so this pin is
  //       red on a revert even if someone re-shades the endpoints;
  //   (c) null stays the separate "not evaluated" grey #5A6E7D — never the ramp's low end;
  //   (d) the drawer renders the ramp as a .qvdot swatch beside PLAIN text (a dark low end can't be a text
  //       colour on the dark panel), and no completeness VALUE takes qColor as its text colour any more.
  ok(A.qColor(2) === "#2a3b66", "CVD: qColor(2) (low end) must be the dark slate-blue #2a3b66, got " + A.qColor(2));
  ok(A.qColor(3.5) === "#6e7f46", "CVD: qColor(3.5) (mid) must be the olive #6e7f46, got " + A.qColor(3.5));
  ok(A.qColor(5) === "#f2e27e", "CVD: qColor(5) (high end) must be the pale warm yellow #f2e27e, got " + A.qColor(5));
  ok(A.qColor(0) === A.qColor(2) && A.qColor(5.5) === A.qColor(5), "CVD: qColor must clamp to the endpoints outside 2..5");
  ok(A.qColor(null) === "#5A6E7D", "CVD: qColor(null) must stay the separate 'not evaluated' grey #5A6E7D, got " + A.qColor(null));
  const _relLum = hex => {
    const lin = [1, 3, 5].map(i => { const c = parseInt(hex.substr(i, 2), 16) / 255; return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); });
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]; };
  let _prevY = -1, _monotone = true;
  for (let q = 2; q <= 5.001; q += 0.25) { const y = _relLum(A.qColor(q)); if (y < _prevY - 1e-9) _monotone = false; _prevY = y; }
  ok(_monotone, "CVD: relative luminance must rise monotonically along the ramp (lightness IS the signal) — the old red→amber→green ramp fails this");
  ok(_relLum(A.qColor(5)) - _relLum(A.qColor(2)) > 0.5,
    "CVD: the ramp must span a LARGE lightness range (Y gap > 0.5), got " + (_relLum(A.qColor(5)) - _relLum(A.qColor(2))).toFixed(3));
  // (d) drawer render: (OWNER HIDE 2026-07-22: the Station summary "completeness" row — the only .qvdot ramp
  //     swatch in the drawer — is reversibly hidden pending design review, so the swatch is ABSENT. The pure
  //     qColor ramp model above is UNCHANGED (helper intact); restore the .qvdot-present pin when the
  //     completeness row is re-enabled.) The surviving invariant: no element uses a qColor hex as a TEXT
  //     colour (the pre-amendment style="color:<ramp>" anti-pattern).
  win.location.hash = "#/station/au.alpha.A1"; A.routeFromHash();
  const rsPanelQ = doc.getElementById("dp-response");
  ok(rsPanelQ.querySelector(".qvdot") == null,
    "OWNER HIDE: the .qvdot completeness swatch must be absent while the completeness row is owner-hidden");
  const _rampTextColours = [...doc.getElementById("drawer").querySelectorAll('[style*="color:#"]')]
    .filter(el => /color:\s*#(2a3b66|6e7f46|f2e27e)/i.test(el.getAttribute("style") || ""));
  ok(_rampTextColours.length === 0, "CVD: no drawer element may take a ramp hex as its TEXT colour (dark ends are unreadable on the dark panel)");
  doc.getElementById("drawer").classList.remove("open");

  // R6: FINAL em-dash DOM sweep. Render the two rich drawer surfaces (station + survey story) and sweep the
  // whole document's rendered textContent — no em dash (U+2014) may appear in any rendered UI text. (The
  // en dash U+2013 is the house range/placeholder glyph and is intentionally NOT swept.)
  win.location.hash = "#/station/au.alpha.A1"; A.routeFromHash();
  A.openSurvey("Alpha Survey");
  const _emSweep = (doc.body.textContent || "") + doc.getElementById("drawer").textContent;
  ok(_emSweep.indexOf("—") < 0,
    "R6: an em dash (—) rendered somewhere in the app: " +
    JSON.stringify((_emSweep.match(/.{0,30}—.{0,30}/) || [""])[0]));
  doc.getElementById("drawer").classList.remove("open");

  // C1. DISPLAY GRAMMAR: the workspace prints a period, a range and a licence the way the entity pages
  // do (owner rulings R1/R2/R3). The helpers' own parity with the engine's Python leaf is held by
  // tests/display_grammar.test.js; THIS section pins that the rendered slots actually use them, which is
  // the half a pure-function test cannot see. Fixture values: Alpha is 2010-2012 with periods
  // 0.01 - 1000 s, so the pins below are exact strings, not patterns.
  //
  // (a) THE CARD. The old form ran "0.010" and "1,000s" together with an en dash (U+2013, quoted here
  // by name because the glyph itself is purged from portal source): the dash, a trailing zero the
  // two-significant-figure rule strips, and no space before the unit.
  A.setSMETA("Alpha Survey", { lic: "CC-BY-4.0" });
  const c1card = A.cardHtml("Alpha Survey");
  ok(c1card.indexOf("0.01 - 1,000 s") >= 0,
    "C1/R1+R2: the card period range must read '0.01 - 1,000 s', got: " +
    JSON.stringify((c1card.match(/periods[^<]*<b>[^<]*<\/b>/) || [""])[0]));
  ok(c1card.indexOf("0.010") < 0, "C1/R1: the card must not print a trailing zero the significant-figure rule strips");
  ok(c1card.indexOf("2010 - 2012") >= 0,
    "C1/R2: the card acquisition range must take the spaced hyphen, got: " +
    JSON.stringify((c1card.match(/acquired[^<]*<b>[^<]*<\/b>/) || [""])[0]));
  // (b) LICENCE CHROME reads human; the SPDX identifier is the machine's name and is NOT what chrome shows.
  ok(c1card.indexOf("CC BY 4.0") >= 0, "C1/R3: the card licence badge must read the human form 'CC BY 4.0'");
  ok(c1card.indexOf("CC-BY-4.0") < 0, "C1/R3: the SPDX identifier must not appear in card chrome");
  // ...while every MACHINE slot keeps the identifier untouched. This is the pin that stops R3 from being
  // "read nicer" at the cost of an export a reference manager or a GIS reads as a different licence.
  const c1gj = A.geoFC([A.station("A1")]);
  ok(c1gj.features[0].properties.license === "CC-BY-4.0",
    "C1/R3: the GeoJSON export must keep the SPDX identifier, got: " + JSON.stringify(c1gj.features[0].properties.license));
  // (c) THE STATION DRAWER's Transfer-function period row, and (d) the SURVEY drawer's period coverage.
  win.location.hash = "#/station/au.alpha.A1"; A.routeFromHash();
  const c1stn = doc.getElementById("drawer").textContent;
  ok(c1stn.indexOf("0.01 - 1,000 s") >= 0,
    "C1/R2: the station drawer's periods row must read '0.01 - 1,000 s', got: " +
    JSON.stringify((c1stn.match(/periods.{0,40}/) || [""])[0]));
  A.openSurvey("Alpha Survey");
  const c1sv = doc.getElementById("drawer").textContent;
  ok(c1sv.indexOf("0.01 - 1,000 s") >= 0,
    "C1/R2: the survey drawer's period coverage must read '0.01 - 1,000 s', got: " +
    JSON.stringify((c1sv.match(/period coverage.{0,40}/) || [""])[0]));
  ok(c1sv.indexOf("CC BY 4.0") >= 0, "C1/R3: the survey drawer's licence row must read the human form");
  // H6 (owner ruling: U+2013 leaves portal source). An ABSENT table value renders the plain
  // hyphen-minus placeholder, reader-visibly. Alpha's SMETA carries no version, so the survey
  // summary's version row IS the placeholder; and the whole rendered drawer must be free of the
  // en dash (spelt by escape here, since the glyph itself is purged from portal source).
  const c1svHtml = doc.getElementById("drawer").innerHTML;
  ok(c1svHtml.indexOf("<td>version</td><td>-</td>") >= 0,
    "H6: an absent survey-table value must render the plain hyphen-minus placeholder, got: " +
    JSON.stringify((c1svHtml.match(/<td>version<\/td><td>[^<]*<\/td>/) || [""])[0]));
  ok(c1svHtml.indexOf("\u2013") < 0,
    "H6: the rendered survey drawer must not carry an en dash (U+2013) anywhere");
  // (d2) THE SURVEY DRAWER'S "Source datasets" ROWS. A third-party release carries its upstream licence
  // in sources[] (the GSSA and Roxby Downs shape), and that row is READER CHROME sitting on the SAME
  // drawer as the licence/access row pinned above, so a drawer could print both forms of one identifier
  // at once. The fixture declares no sources[], which is why nothing here saw the slot before.
  A.setSMETA("Alpha Survey", { lic: "CC-BY-4.0",
    sources: [{ title: "GSSA legacy release", custodian: "GSSA", licence: "CC-BY-4.0" }] });
  A.openSurvey("Alpha Survey");
  const c1src = (doc.querySelector("#drawer .srcitem .srcm") || { textContent: "" }).textContent;
  ok(c1src.indexOf("CC BY 4.0") >= 0,
    "C1/R3: a source dataset's licence is chrome and must read the human form, got: " + JSON.stringify(c1src));
  ok(c1src.indexOf("CC-BY-4.0") < 0,
    "C1/R3: the SPDX identifier must not appear in the Source datasets row, got: " + JSON.stringify(c1src));
  A.setSMETA("Alpha Survey", { sources: null });
  // (e) THE COLLECTION DETAIL: the rollup stat and the per-member table row.
  win.location.hash = "#/collection/auslamp"; A.routeFromHash();
  const c1coll = doc.getElementById("collectionview").textContent;
  ok(c1coll.indexOf("0.01 - 1,000 s") >= 0,
    "C1/R2: the collection detail's period slots must take the spaced hyphen, got: " +
    JSON.stringify((c1coll.match(/period coverage.{0,40}/) || [""])[0]));
  // (f) THE SWEEP that catches a range slot this list forgot: NO rendered text anywhere may join two
  // digits with an en or em dash. Deliberately narrower than a whole-glyph ban - the SPA keeps its en
  // dash for prose and for absent-value markers (F1 4.7); only a NUMERIC RANGE is converted.
  win.location.hash = ""; A.routeFromHash();
  A.setView("surveys"); A.renderCards();
  A.openSurvey("Alpha Survey");
  const c1sweep = (doc.body.textContent || "") + doc.getElementById("drawer").textContent;
  ok(!/\d\s*[\u2013\u2014]\s*\d/.test(c1sweep),
    "C1/R2: a numeric range still renders with a dash glyph: " +
    JSON.stringify((c1sweep.match(/.{0,30}\d\s*[\u2013\u2014]\s*\d.{0,30}/) || [""])[0]));
  A.setSMETA("Alpha Survey", { lic: null });
  doc.getElementById("drawer").classList.remove("open");
  A.setView("map");

  // QQ. DRAWER SCRIM (cleanup wave D): a dim backdrop behind the drawer on the Surveys / Collections views
  // (NEVER the map view, where the drawer sits side-by-side with the map). Clicking it closes the drawer.
  const scrim = doc.getElementById("drawerScrim");
  ok(scrim, "D: the drawer scrim element (#drawerScrim) is missing");
  // MAP view: NO scrim.
  A.setView("map");
  A.openStationById("au.alpha.A1");
  ok(doc.getElementById("drawer").classList.contains("open"), "D: setup, the station drawer did not open on the map view");
  ok(scrim.classList.contains("hidden"), "D: the scrim must STAY hidden when the drawer opens on the map view (side-by-side)");
  doc.querySelector("#drawer .close").click();
  ok(scrim.classList.contains("hidden"), "D: the scrim stays hidden after closing on the map view");
  // SURVEYS view: the scrim SHOWS behind the drawer, and clicking it closes the drawer.
  A.setView("surveys");
  win.location.hash = "#/survey/alpha"; A.routeFromHash();
  ok(doc.getElementById("drawer").classList.contains("open"), "D: setup, the survey drawer did not open on the surveys view");
  ok(!scrim.classList.contains("hidden"), "D: the scrim must SHOW when the drawer opens on the Surveys view");
  scrim.click();
  ok(!doc.getElementById("drawer").classList.contains("open"), "D: clicking the scrim must close the drawer");
  ok(scrim.classList.contains("hidden"), "D: closing via the scrim must hide the scrim");

  // XX. STAGE B - SELECTION-STATE ISOLATION. Owner bug: the "select & download this survey" control scoped
  // the shared rail tree to its one survey, which (a) emptied the Surveys catalogue with the rail (the only
  // undo) hidden on that view, and (b) left the map tree stuck scoped. Fix: the catalogue is decoupled from
  // the rail tree, and the control's map scoping is a temporary lens restored on exit.
  // SURFACE MOVED (survey-drawer lane, ruling 1): the survey drawer's "All EDIs (select & download)" TILE is
  // removed - Downloads is the three whole-survey bundles, and per-station selection lives on the station
  // drawers. The lens machinery (selectSurvey) is unchanged and still reached from the survey CARD's
  // "Download" button, so this section now drives that surface. The BEHAVIOUR under test is identical; only
  // the control that triggers it moved. A leg below separately pins that the drawer tile is gone.
  // The button only exists on the RICH card (the compact .srow row carries no per-survey actions), so force
  // the cards layout before reading it - earlier sections drive the layout toggle and must not leak in here.
  const selectCtl = () => {
    const cardsBtn = doc.getElementById("layoutSeg") && doc.getElementById("layoutSeg").querySelector('[data-layout="cards"]');
    if (cardsBtn) cardsBtn.click(); else A.renderCards();
    const el = doc.querySelector('#cardGrid [data-act="select"][data-survey="Alpha Survey"]');
    ok(el, "StageB: the survey card's Download (select & download) button is missing for Alpha Survey");
    return el;
  };
  // Clean baseline: drawer closed, all surveys checked, map view, Browse mode.
  doc.getElementById("drawer").classList.remove("open");
  [...doc.querySelectorAll("#tree input")].forEach(c => { c.checked = true; });
  A.setView("map"); A.setSidebarMode("browse"); A.refresh();
  const treeChecked = () => [...doc.querySelectorAll('#tree input[value]')].filter(c => c.checked).map(c => c.value).sort();
  ok(A.visIds().length === 5, "StageB setup: expected the clean 5-station baseline, got " + A.visIds().length);
  ok(treeChecked().length === 4, "StageB setup: all 4 survey boxes must start checked, got " + JSON.stringify(treeChecked()));

  // (1) DECOUPLE (RED-proof). Drive the REAL select-and-download control (the survey card's Download
  // button). It scopes the map tree to its one survey (checks only that box). With the tree scoped, and
  // WITHOUT leaving the map, the Surveys catalogue must STILL render every survey card: it is filtered ONLY
  // by its own discovery controls, never by the rail tree. Pre-change renderCards read passesCore and
  // rendered a single card.
  selectCtl().click();
  ok(treeChecked().length === 1 && treeChecked()[0] === "Alpha Survey",
    "StageB: the All-EDIs tile must scope the map tree to its one survey, got " + JSON.stringify(treeChecked()));
  A.renderCards();
  ok(doc.querySelectorAll("#cardGrid .scard").length === 4,
    "StageB DECOUPLE: the Surveys catalogue must show ALL 4 cards while the rail tree is scoped to one survey, got " + doc.querySelectorAll("#cardGrid .scard").length);

  // (2) LENS RESTORE ON BROWSE (RED-proof). The tile enters Select & export (its exports live in that pane),
  // and returning to Browse restores the scoped tree. Pre-change the tile stayed in Browse and never
  // restored the tree, so the map stayed stuck on the single survey.
  ok(A.sidebarMode() === "select", "StageB: the All-EDIs tile must enter Select & export mode, got " + A.sidebarMode());
  const browseBtn = [...doc.getElementById("modeSeg").children].find(b => b.dataset.mode === "browse");
  browseBtn.click();
  ok(A.sidebarMode() === "browse", "StageB: could not return to Browse mode");
  ok(treeChecked().length === 4, "StageB RESTORE (Browse): returning to Browse must restore the scoped map tree (all 4 checked), got " + JSON.stringify(treeChecked()));
  ok(A.visIds().length === 5, "StageB RESTORE (Browse): the restored tree must put every station back on the map, got " + A.visIds().length);

  // (3) COHERENCE + VIEW-SWITCH EXIT PATH. Re-scope the map via the tile, then navigate to the Surveys view
  // (the exact step in the owner's repro). The catalogue count is coherent - both #surveyCount and #nVis read
  // the discovery-filtered set of 4, never the scoped tree - AND leaving the map releases the lens so the map
  // tree is restored.
  selectCtl().click();
  ok(treeChecked().length === 1, "StageB: re-scope setup failed, got " + JSON.stringify(treeChecked()));
  A.setView("surveys");
  // C5: the header slot is the workspace line on this view, so the coherence pin reads it there.
  ok(doc.getElementById("surveyCount").textContent === "4 surveys" && /^4 of 4 surveys shown/.test(doc.getElementById("countSlot").textContent),
    "StageB COHERENCE: #surveyCount and the header workspace line must both count 4 surveys regardless of tile scoping, got " + JSON.stringify([doc.getElementById("surveyCount").textContent, doc.getElementById("countSlot").textContent]));
  ok(treeChecked().length === 4, "StageB RESTORE (view switch): navigating off the map must restore the scoped tree, got " + JSON.stringify(treeChecked()));
  A.setView("map"); A.setSidebarMode("browse");

  // (4) GUARD. A visitor's OWN Browse-mode tree edit must NOT be clobbered by an unrelated drawer open/close
  // (openSurvey/closeDrawer touch neither the tree nor the lens, and take no snapshot to restore).
  const sbBetaBox = [...doc.querySelectorAll('#tree input[value]')].find(c => c.value === "Beta Survey");
  sbBetaBox.checked = false; fire(sbBetaBox, "change");
  A.openSurvey("Gamma Survey");
  doc.querySelector("#drawer .close").click();
  ok(treeChecked().length === 3 && !treeChecked().includes("Beta Survey"),
    "StageB GUARD: a hand-unchecked Browse-mode tree box must survive an unrelated drawer open/close, got " + JSON.stringify(treeChecked()));
  sbBetaBox.checked = true; A.refresh();   // restore the baseline

  // ===== INTERACTIVE MAP LEGEND (LEG) ============================================================
  // A visitor tried to click the legend's data-type rows to show/hide sites - reasonable, since the rail's
  // DATA TYPE checkboxes use the identical dot+label visual language and ARE toggles. The four TYPE rows
  // are now real toggle BUTTONS that PROXY those rail checkboxes: a legend click flips the SAME checkbox
  // and dispatches its change event, so there is NO second state store and every existing consumer
  // (passesCore, the map redraw, the counts, the surveys decoupling, the select-lens semantics) runs on the
  // one existing path.
  A.setSidebarMode("browse"); A.setView("map");
  const legB = doc.getElementById("mapLegend");
  ok(legB, "LEG: #mapLegend was not built");
  // Rows are resolved BY LABEL TEXT (not by a new class) so the core pin below is meaningful against the
  // PRE-CHANGE markup too: there the row is a plain inert <div> carrying the very same label.
  const legRow = txt => [...legB.querySelectorAll(".legrow")].find(r => r.textContent.trim() === txt);
  const typeBox = k => [...doc.querySelectorAll("#typeBoxes input")].find(c => c.value === k);
  const lpRow = legRow("Long period"), bbRow = legRow("Broadband"),
        amRow = legRow("AMT"), gdRow = legRow("GDS (tipper)");
  ok(lpRow && bbRow && amRow && gdRow, "LEG: the four data-type legend rows are not all present by label");

  // (a) CORE PROXY (the RED-proof pin). The fixture is all-BBMT, so re-type A1 to LPMT first: hiding one
  // type is then FALSIFIABLE against the four stations that must stay. Against pre-change main.js the row
  // is an inert div - the click lands on nothing, the rail checkbox stays checked and this pin fails.
  A.setType("A1", "LPMT"); A.refresh();
  ok(A.visIds().length === 5, "LEG setup: all 5 stations must be visible before toggling, got " + A.visIds().length);
  lpRow.click();
  ok(typeBox("LPMT").checked === false,
    "LEG CORE: clicking the 'Long period' legend row must flip the RAIL #typeBoxes LPMT checkbox (the legend " +
    "PROXIES the one existing state store - pre-change the row was an inert div and this stayed checked)");
  ok(!A.visIds().includes("A1") && A.visIds().length === 4,
    "LEG CORE: hiding a type from the legend must drop exactly that type's stations from the map set, got " + JSON.stringify(A.visIds()));
  ok(A.markerCount() === 5,
    "LEG CORE: hiding a type must not destroy markers - it filters the layer set, got " + A.markerCount());
  ok(doc.getElementById("nVis").textContent === "4",
    "LEG CORE: the header count must follow a legend toggle, got " + doc.getElementById("nVis").textContent);
  ok(lpRow.getAttribute("aria-pressed") === "false" && lpRow.classList.contains("legoff"),
    "LEG: an OFF legend row must report aria-pressed=false AND render dimmed (.legoff)");
  lpRow.click();
  ok(typeBox("LPMT").checked === true && lpRow.getAttribute("aria-pressed") === "true" &&
     !lpRow.classList.contains("legoff") && A.visIds().length === 5,
    "LEG: a second legend click must turn the type back on and restore its stations");

  // (b) SEMANTICS. Real <button type=button> (keyboard reachable), aria-pressed state, and the EXACT rail
  // type keys in rail order - a legend that invented its own keys would silently filter nothing.
  const legBtns = [...legB.querySelectorAll(".legtype")];
  ok(legBtns.length === 4, "LEG: expected 4 legend TYPE toggle buttons (.legtype), got " + legBtns.length);
  ok(legBtns.every(b => b.tagName === "BUTTON" && b.getAttribute("type") === "button"),
    "LEG: a legend type row must be a real <button type=button>, got " + JSON.stringify(legBtns.map(b => b.tagName)));
  ok(JSON.stringify(legBtns.map(b => b.dataset.type)) === JSON.stringify(["LPMT", "BBMT", "AMT", "GDS"]),
    "LEG: the legend rows must carry the EXACT rail type keys, in rail order, got " + JSON.stringify(legBtns.map(b => b.dataset.type)));
  ok(legBtns.every(b => b.getAttribute("aria-pressed") === "true"),
    "LEG: every legend type must read aria-pressed=true while its rail checkbox is checked");
  // Every legend row is now a type toggle: the two retired swatches (.legcluster for the proximity bubble,
  // .legbadge for the survey badge that replaced it) must be gone from the DOM, not just unstyled.
  ok(!legB.querySelector(".legcluster") && !legB.querySelector(".legbadge"),
    "dots only: no retired map-object swatch may survive in the legend");
  ok([...legB.querySelectorAll(".legrow")].every(r => r.classList.contains("legtype")),
    "dots only: every legend row must be a data-type toggle, got " +
    JSON.stringify([...legB.querySelectorAll(".legrow")].map(r => r.className)));
  // Affordance copy, in place of where a 'Legend' title would have gone (the box has no desktop title).
  const legHint = legB.querySelector(".leghint");
  ok(legHint && /click a type to show or hide it/i.test(legHint.textContent),
    "LEG: the legend must carry the muted hint 'Click a type to show or hide it'");
  ok(legB.querySelector(".maplegend-body").firstElementChild === legHint,
    "LEG: the hint belongs at the TOP of the legend body (where a title would have gone)");

  // (c) TWO-WAY SYNC. The rail is the other end of the SAME state - flipping a rail checkbox must dim the
  // legend row through the one sync function on the single #typeBoxes change path.
  const bbBox = typeBox("BBMT");
  bbBox.checked = false; fire(bbBox, "change");
  ok(bbRow.getAttribute("aria-pressed") === "false" && bbRow.classList.contains("legoff"),
    "LEG two-way: flipping the RAIL checkbox must dim the legend row in sync");
  ok(JSON.stringify(A.visIds()) === JSON.stringify(["A1"]),
    "LEG two-way: hiding BBMT from the rail must leave only the LPMT station, got " + JSON.stringify(A.visIds()));
  bbBox.checked = true; fire(bbBox, "change");
  ok(bbRow.getAttribute("aria-pressed") === "true" && !bbRow.classList.contains("legoff") && A.visIds().length === 5,
    "LEG two-way: restoring the rail checkbox must undim the legend row and restore the map set");

  // (d) KEYBOARD. Enter and Space activate the toggle (and the handler cancels the default so a real
  // browser cannot ALSO fire its native button click - one keypress, one flip).
  const key = (el, k) => el.dispatchEvent(new win.KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true }));
  key(amRow, "Enter");
  ok(typeBox("AMT").checked === false && amRow.getAttribute("aria-pressed") === "false" && amRow.classList.contains("legoff"),
    "LEG keyboard: Enter must activate a legend type toggle");
  key(amRow, "Enter");
  ok(typeBox("AMT").checked === true, "LEG keyboard: a second Enter must toggle back");
  key(amRow, " ");
  ok(typeBox("AMT").checked === false && amRow.getAttribute("aria-pressed") === "false",
    "LEG keyboard: Space must activate a legend type toggle");
  key(amRow, " ");
  ok(typeBox("AMT").checked === true && amRow.getAttribute("aria-pressed") === "true", "LEG keyboard: a second Space must toggle back");
  ok(legBtns.every(b => { const e = new win.KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }); b.dispatchEvent(e); b.click(); return e.defaultPrevented; }),
    "LEG keyboard: the keydown handler must preventDefault so a browser's native button activation cannot double-fire");

  // (e) ALL FOUR OFF. An empty map must render with NO error and the header must read 0 shown; toggling
  // back must restore. (A throw anywhere in refresh() would reach the driver's catch and fail the run.)
  legBtns.forEach(b => { if (b.getAttribute("aria-pressed") === "true") b.click(); });
  ok(legBtns.every(b => b.getAttribute("aria-pressed") === "false" && b.classList.contains("legoff")),
    "LEG all-off: every legend row must read aria-pressed=false and render dimmed");
  ok(A.visIds().length === 0, "LEG all-off: no station may pass with every type hidden, got " + JSON.stringify(A.visIds()));
  ok(doc.getElementById("nVis").textContent === "0",
    "LEG all-off: the header must read '0 shown', got " + doc.getElementById("nVis").textContent);
  ok(A.selCount() === 0, "LEG all-off: no station can remain selected when none is visible, got " + A.selCount());
  ok(A.markerCount() === 5, "LEG all-off: the markers themselves survive an empty map, got " + A.markerCount());
  legBtns.forEach(b => b.click());
  ok(legBtns.every(b => b.getAttribute("aria-pressed") === "true") && A.visIds().length === 5,
    "LEG all-off: toggling every type back on must restore the full map set, got " + A.visIds().length);

  // (f) SELECT-AND-EXPORT LENS. enterSelectLens/restoreSelectLens snapshot ONLY the tree's survey
  // checkboxes (`tree.querySelectorAll('input[value]')`, filters.js) - they never read #typeBoxes. So a
  // hand-toggled TYPE (rail or legend: the same checkbox) is a DURABLE Browse filter that the select-and-
  // download flow neither captures nor restores, exactly like the hand-toggled tree box in StageB GUARD.
  // Driven from the survey CARD's Download button since the survey drawer's tile was removed (ruling 1).
  gdRow.click();
  ok(typeBox("GDS").checked === false, "LEG lens setup: GDS must be off before entering the lens");
  selectCtl().click();                                                                    // enters the lens
  ok(typeBox("GDS").checked === false && gdRow.getAttribute("aria-pressed") === "false",
    "LEG lens: entering the select lens must not touch a legend/rail TYPE toggle");
  A.setSidebarMode("browse");                                                             // leaves it -> restoreSelectLens()
  ok(typeBox("GDS").checked === false && gdRow.getAttribute("aria-pressed") === "false",
    "LEG lens: leaving the lens must NOT restore over a legend/rail TYPE toggle (the lens snapshots the tree only)");
  gdRow.click(); A.closeDrawer();
  A.setType("A1", "BBMT"); A.setView("map"); A.refresh();   // restore the all-BBMT baseline

  // ---- STATION MTH5 IS THE STATION'S OWN FILE (owner report 2026-08-04) ---------------------------
  // The Files tab's Level 2 list belongs to ONE STATION. Its EDI and EMTF XML rows have always read that
  // station's own manifest files[] row; the MTH5 row read the SURVEY's bundles[] row instead, because it
  // was written when the survey-aggregated <slug>-tf.h5 was the only MTH5 the build produced. Once the
  // per-station producer landed (h5/<slug>/<station>.h5, one files[] row each) that row started offering
  // the WHOLE SURVEY under a station heading: live, SA026E showed the 1.74 MB survey bundle in place of
  // its own 174,696 B file.
  //
  // The fixture is the shape that makes the confusion possible, and it is the shape the served manifest
  // actually has: the per-station mth5 files[] row AND the survey-level mth5 bundles[] row, together.
  const H5_STATION_URL = "h5/gamma/G1.h5", H5_BUNDLE_URL = "bundles/gamma-tf.h5";
  // The Level 2 rows are `<div class="prod" …>{dot}<div>NAME {chip}<small>sub</small></div></div>`, so the
  // row NAME is the inner div's leading text node, matched exactly, never by a substring of the whole row.
  const prodNamed = (panel, name) => [...panel.querySelectorAll(".prod")].find(d => {
    const body = d.querySelector("div");
    return body && body.firstChild && body.firstChild.nodeType === 3 && body.firstChild.textContent.trim() === name;
  });
  // The OTHER two station-scoped MTH5 surfaces, read the same way a reader reads them. Both live in the
  // Provenance tab: the lineage graph's "Distributed formats" node (drawer.js distributedFormatsText) and
  // the "Format availability" badge row. Panels are rendered whatever tab is selected (drawerPanel hides
  // them with `hidden`), so both are queryable without clicking through.
  const lineageVal = (label) => {
    const lt = [...doc.querySelectorAll("#drawer .lineage .lt")].find(e => e.textContent.trim() === label);
    return lt ? lt.parentNode.querySelector(".lv").textContent.trim() : null;
  };
  // A badge is `<span class="badge {state}">{glyph} {label}</span>`; match on the LABEL (everything after
  // the state glyph) so "MTH5" never matches "EMTF XML", and report the state by its glyph.
  const badgeState = (label) => {
    const b = [...doc.querySelectorAll("#drawer .badges .badge")]
      .find(e => e.textContent.trim().replace(/^\S+\s*/, "") === label);
    if (!b) return null;
    const g = b.textContent.trim().charAt(0);
    return g === "✓" ? "ok" : g === "◐" ? "part" : g === "✗" ? "no" : "unk";
  };
  A.setManifest({
    files: [
      { ausmt_id: "nz.gamma.G1", format: "edi", url: "edi/gamma/x.edi", size: 1000 },
      { ausmt_id: "nz.gamma.G1", format: "emtfxml", url: "xml/gamma/G1.xml", size: 900 },
      { ausmt_id: "nz.gamma.G1", format: "mth5", url: H5_STATION_URL, size: 174696 },
    ],
    bundles: [{ survey: "Gamma Survey", slug: "gamma", format: "mth5", url: H5_BUNDLE_URL, size: 1824522 }],
  });
  A.openStationById("nz.gamma.G1");
  const h5Files = doc.getElementById("dp-files");
  const h5Row = prodNamed(h5Files, "MTH5");
  ok(h5Row, "STATION-H5: the Files tab must carry an MTH5 row when the station has its own served h5");
  ok(h5Row.getAttribute("data-url") === H5_STATION_URL,
    "STATION-H5: the MTH5 row must link the STATION's own files[] row (" + H5_STATION_URL + "), got " +
    JSON.stringify(h5Row.getAttribute("data-url")) + " (the survey bundle is not this station's file)");
  ok(h5Row.getAttribute("data-name") === "G1.h5",
    "STATION-H5: the download name must be the station file's, got " + JSON.stringify(h5Row.getAttribute("data-name")));
  ok(h5Row.getAttribute("data-prod") === "fetch",
    "STATION-H5: the row must download through the same masked front-door fetch the EMTF XML row uses");
  // Size comes from the STATION's manifest row: 174,696 B renders "171 KB". The bundle's 1.7 MB is the
  // live symptom the owner reported and must appear nowhere on the row.
  ok(/171 KB/.test(h5Row.textContent) && h5Row.textContent.indexOf("1.7 MB") < 0,
    "STATION-H5: the size must be the STATION row's (171 KB), not the survey bundle's (1.7 MB), got " +
    JSON.stringify(h5Row.textContent.trim()));
  ok(/AusMT-derived/.test(h5Row.textContent) && /Transfer functions only/.test(h5Row.textContent),
    "STATION-H5: the row keeps its AusMT-derived origin chip and its TF-only wording");
  ok(h5Files.innerHTML.indexOf(H5_BUNDLE_URL) < 0,
    "STATION-H5: the survey-level bundle URL must NEVER render inside a station's Files list, found it in " +
    h5Files.innerHTML.slice(0, 400));
  // A station that HAS its own h5 reads the same in all three station-scoped places. This half of the
  // consistency pin is the one that stays true either way (station row and survey bundle both exist), so
  // it is here to prove the negative half below is measuring the surfaces and not merely their absence.
  ok(/MTH5/.test(lineageVal("Distributed formats") || ""),
    "STATION-H5 consistency: a station with its own served h5 must list MTH5 in the lineage's distributed " +
    "formats, got " + JSON.stringify(lineageVal("Distributed formats")));
  ok(badgeState("MTH5") === "ok",
    "STATION-H5 consistency: a station with its own served h5 must carry an ok MTH5 availability badge, got " +
    JSON.stringify(badgeState("MTH5")));
  // Honest absence: a station with no per-station row of its own (the engine emits none for a
  // coordinate-generalised or withheld station) says so. It must never borrow the survey bundle.
  A.setManifest({
    files: [{ ausmt_id: "nz.gamma.G1", format: "edi", url: "edi/gamma/x.edi", size: 1000 }],
    bundles: [{ survey: "Gamma Survey", slug: "gamma", format: "mth5", url: H5_BUNDLE_URL, size: 1824522 }],
  });
  A.openStationById("nz.gamma.G1");
  const h5FilesNone = doc.getElementById("dp-files");
  const h5RowNone = prodNamed(h5FilesNone, "MTH5");
  ok(h5RowNone && /not currently available/.test(h5RowNone.textContent),
    "STATION-H5: with no per-station h5 the MTH5 row must read the honest not-available line, got " +
    JSON.stringify(h5RowNone && h5RowNone.textContent.trim()));
  ok(h5RowNone.getAttribute("data-url") == null,
    "STATION-H5: the not-available row must carry no download action at all");
  ok(h5FilesNone.innerHTML.indexOf(H5_BUNDLE_URL) < 0,
    "STATION-H5: an absent station h5 must never fall back to the survey bundle");
  // ONE DRAWER, ONE ANSWER. The Files tab reads the station's files[] row; the lineage's distributed-formats
  // node and the format-availability badge read the survey's bundles[] row. This fixture is exactly where
  // those two readings diverge: no station h5, but the survey bundle exists. The reader then sees the same
  // drawer say "not currently available" on the Files tab and "MTH5 is distributed / ✓ MTH5" two tabs over,
  // and there is no way to tell from the screen which one is lying. All three are STATION-scoped surfaces,
  // so all three must answer about the station.
  ok(!/MTH5/.test(lineageVal("Distributed formats") || ""),
    "STATION-H5 consistency: with no station h5 the lineage's distributed formats must NOT claim MTH5 " +
    "(the Files tab in the same drawer says it is not available), got " +
    JSON.stringify(lineageVal("Distributed formats")));
  ok(badgeState("MTH5") === "unk",
    "STATION-H5 consistency: with no station h5 the format-availability badge must read unknown, not ok " +
    "(an ok badge is the survey bundle answering a question about the station), got " +
    JSON.stringify(badgeState("MTH5")));
  ok(/EDI/.test(lineageVal("Distributed formats") || ""),
    "STATION-H5 consistency: the formats line must still list what IS served for the station, got " +
    JSON.stringify(lineageVal("Distributed formats")));
  // ...and the survey bundle keeps the surface it belongs to: the SURVEY drawer's Downloads grid.
  A.openSurvey("Gamma Survey");
  ok(doc.getElementById("drawer").innerHTML.indexOf(H5_BUNDLE_URL) >= 0,
    "STATION-H5: the survey MTH5 bundle must still be offered by the survey drawer's Downloads grid");
  A.setManifest(null); A.closeDrawer();

  // ---- BULK-EXPORT LABEL (owner ruling 2026-08-01) -------------------------------------------------
  // The portal marks the file fetches its multi-file export issues with a query flag, so the server-log
  // aggregator can tell a drag-selected bulk export from a single station download. Two properties, and
  // the second is what makes the first mean anything: the export flow labels EVERY file it fetches, and
  // NOTHING ELSE does. An unlabelled fetch is precisely what "single" means downstream, so a label that
  // leaked onto the drawer's own download would silently reclassify every single download as bulk.
  //
  // Driven through the REAL click handlers against the real fetch, which this harness already records in
  // request order; the fetches are what the label lives on and they are observed here exactly as the
  // browser would issue them.
  ok(typeof A.selBulkFlag === "function" && /^sel=/.test(A.selBulkFlag() || ""),
    "SEL: exports.js must define the bulk-export flag string, got " + JSON.stringify(A.selBulkFlag && A.selBulkFlag()));
  const SELFLAG = A.selBulkFlag();
  const ediFetches = (from) => fetchOrder.slice(from).filter(u => /\/edi\//.test(u));

  A.setSelected(["A1", "A2", "G1"]);              // three EDI-available stations across two surveys
  ok(A.selCount() === 3, "SEL setup: three stations must be selected, got " + A.selCount());
  let mark = fetchOrder.length;
  await doc.getElementById("dlZip").onclick();
  const bulkUrls = ediFetches(mark);
  ok(bulkUrls.length === 3, "SEL: the export must fetch one file per selected station, got " + JSON.stringify(bulkUrls));
  ok(bulkUrls.every(u => u.indexOf(SELFLAG) >= 0),
    "SEL: every file the bulk export fetches must carry " + SELFLAG + ", got " + JSON.stringify(bulkUrls));
  ok(bulkUrls.every(u => u.split("?")[0].endsWith("x.edi")),
    "SEL: the flag rides the QUERY, never the path (the aggregator strips the query to attribute), got " + JSON.stringify(bulkUrls));

  // The drawer's own single-station download goes through drawer.js dispatchProd -> fetchEdi ->
  // downloadUrl, a different call site, and must stay unlabelled.
  mark = fetchOrder.length;
  await A.dispatchProd({ prod: "edi", file: "x.edi", avail: "1", survey: "Alpha Survey" });
  const singleUrls = ediFetches(mark);
  ok(singleUrls.length === 1, "SEL: the drawer download must fetch exactly one file, got " + JSON.stringify(singleUrls));
  ok(singleUrls.every(u => u.indexOf("sel=") < 0),
    "SEL: a single-station download must carry NO selection flag, got " + JSON.stringify(singleUrls));
  A.setSelected([]);

  // ---- SELECTION EXPORTS: EMTF XML AND MTH5 (owner ask 2026-08-04) --------------------------------
  // "EDIs (zip)" packaged the selection in the custodian's format only. AusMT also serves a per-station
  // EMTF XML and a per-station MTH5, and a reader who has just drawn a box around 40 stations had no way
  // to take either without opening 40 drawers. Two more buttons zip those, client-side, through the same
  // flow: the same per-station manifest rows, the same bulk label on every fetch, the same LICENSE.txt
  // beside the bytes, and the same refusal to shrink the answer in silence.
  //
  // The gap is the point of the fixture. Unlike an EDI, a derived file exists only where the build made
  // one: A2 has no MTH5 and G1 no EMTF XML, so each export must skip a DIFFERENT station and say so.
  const SEL_MANIFEST = { files: [
    { ausmt_id: "au.alpha.A1", format: "edi", url: "edi/alpha/A1.edi", size: 1000 },
    { ausmt_id: "au.alpha.A1", format: "emtfxml", url: "xml/alpha/A1.xml", size: 2000000 },
    { ausmt_id: "au.alpha.A1", format: "mth5", url: "h5/alpha/A1.h5", size: 174696 },
    { ausmt_id: "au.alpha.A2", format: "edi", url: "edi/alpha/A2.edi", size: 1100 },
    { ausmt_id: "au.alpha.A2", format: "emtfxml", url: "xml/alpha/A2.xml", size: 200000 },
    { ausmt_id: "nz.gamma.G1", format: "edi", url: "edi/gamma/G1.edi", size: 1200 },
    { ausmt_id: "nz.gamma.G1", format: "mth5", url: "h5/gamma/G1.h5", size: 1000000 },
  ], bundles: [] };
  const xmlBtn = doc.getElementById("dlZipXml"), h5Btn = doc.getElementById("dlZipH5"), ediBtn = doc.getElementById("dlZip");
  const rowName = b => b.querySelector(".pname").textContent;
  const rowMeta = b => b.querySelector("small").textContent;
  ok(xmlBtn, "SELFMT: the Download block must offer an EMTF XML zip row (#dlZipXml)");
  ok(h5Btn, "SELFMT: the Download block must offer an MTH5 zip row (#dlZipH5)");
  ok(typeof xmlBtn.onclick === "function" && typeof h5Btn.onclick === "function",
    "SELFMT: both rows' actions must have a handler bound in exports.js");
  ok(/EMTF XML/.test(rowName(xmlBtn)) && /zip/.test(rowName(xmlBtn)),
    "SELFMT: the XML row must read as an EMTF XML zip export, got " + JSON.stringify(rowName(xmlBtn)));
  ok(/MTH5/.test(rowName(h5Btn)) && /zip/.test(rowName(h5Btn)),
    "SELFMT: the MTH5 row must read as an MTH5 zip export, got " + JSON.stringify(rowName(h5Btn)));
  // Scope gating: with no selection the scope is the filtered corpus, and a derived-format row with
  // nothing of that format in scope (the manifest is empty here) is inert; the EDI row keeps its
  // licence-predicate enablement (a legacy-path EDI can exist with no manifest row).
  A.setSelected([]); A.paintDownloadRows();
  ok(xmlBtn.disabled && h5Btn.disabled,
    "SELFMT: with no file of the format in scope both derived rows must be disabled");
  ok(!ediBtn.disabled, "SELFMT: the EDI row follows the s.ediAvail predicate, not the manifest");

  A.setManifest(SEL_MANIFEST);
  A.setSelected(["A1", "A2", "G1"]);
  ok(!xmlBtn.disabled && !h5Btn.disabled, "SELFMT: a selection must enable both new exports");

  // (a) SIZE HONESTY. The manifest carries per-file sizes client-side, so each of the three zip buttons
  //     states what the current selection would cost before it is clicked. XML: 2,000,000 + 200,000 B
  //     over A1+A2 (G1 has none) = 2.1 MB. MTH5: 174,696 + 1,000,000 over A1+G1 (A2 has none) = 1.1 MB.
  //     EDI: 1000+1100+1200 = 3 KB. Each is an ESTIMATE of what will actually be packaged, so it counts
  //     only the rows the export will fetch, never the whole selection.
  // Packaging outlives the old 7s toast dwell (13-16s measured at 400-700 EDIs), so the packaging
  // message is STICKY: it sets no hide timer and stands until the completion toast replaces it.
  win.toast("packaging probe…", { sticky: true });
  const _toastEl = doc.getElementById("toast");
  ok(_toastEl.style.display === "block" && win.toast._h === null,
    "a sticky toast must stay up with no hide timer until the next toast replaces it");
  win.toast("done");
  ok(_toastEl.textContent === "done" && win.toast._h !== null,
    "a plain toast must replace a sticky one and restore the auto-hide");
  ok(/,\{sticky:true\}/.test(fs.readFileSync(path.join(PORTAL, "src", "exports.js"), "utf8").split("Packaging ")[1] || "") &&
     /,\{sticky:true\}/.test(fs.readFileSync(path.join(PORTAL, "src", "exports.js"), "utf8").split("Packaging ")[2] || ""),
    "both zip flows' packaging toasts must be sticky");
  ok(/2 stations · ~2\.1 MB/.test(rowMeta(xmlBtn)),
    "SELFMT size: the XML row must price the scope (2 stations, ~2.1 MB), got " + JSON.stringify(rowMeta(xmlBtn)));
  ok(/2 stations · ~1\.1 MB/.test(rowMeta(h5Btn)),
    "SELFMT size: the MTH5 row must price the scope (2 stations, ~1.1 MB), got " + JSON.stringify(rowMeta(h5Btn)));
  ok(/3 stations · ~3 KB/.test(rowMeta(ediBtn)),
    "SELFMT size: the EDI row must price the scope (3 stations, ~3 KB), got " + JSON.stringify(rowMeta(ediBtn)));

  const fetchedExt = (from, ext) => fetchOrder.slice(from).filter(u => String(u).split("?")[0].endsWith(ext));
  const zipNames = (from) => zipEntries.slice(from).map(e => e.name);
  const zipBody = (from, re) => (zipEntries.slice(from).find(e => re.test(e.name)) || {}).body;

  // (b) EMTF XML export. Fetches exactly the two stations that HAVE an XML row, every URL bulk-labelled;
  //     packages them under their survey slug; writes the survey's LICENSE.txt beside them; and names
  //     the skipped station in the archive rather than quietly returning two files for three stations.
  let fmark = fetchOrder.length, zmark = zipEntries.length;
  await xmlBtn.onclick();
  const xmlUrls = fetchedExt(fmark, ".xml");
  ok(xmlUrls.length === 2, "SELFMT xml: the export must fetch one file per selected station THAT HAS an " +
    "EMTF XML (A1 and A2, never G1, which has none), got " + JSON.stringify(xmlUrls));
  ok(xmlUrls.every(u => u.indexOf(SELFLAG) >= 0),
    "SELFMT xml: every file the export fetches must carry " + SELFLAG + ", got " + JSON.stringify(xmlUrls));
  ok(xmlUrls.every(u => u.split("?")[0].indexOf("/xml/alpha/") >= 0),
    "SELFMT xml: the export must fetch the stations' own manifest rows, got " + JSON.stringify(xmlUrls));
  ok(fetchedExt(fmark, ".edi").length === 0 && fetchedExt(fmark, ".h5").length === 0,
    "SELFMT xml: an EMTF XML export must fetch nothing but EMTF XML");
  const xmlNames = zipNames(zmark);
  ok(xmlNames.filter(n => /\.xml$/.test(n)).length === 2,
    "SELFMT xml: the zip must hold one entry per fetched file, got " + JSON.stringify(xmlNames));
  ok(xmlNames.some(n => /alpha\/A1\.xml$/.test(n)) && xmlNames.some(n => /alpha\/A2\.xml$/.test(n)),
    "SELFMT xml: entries must be namespaced by survey slug (two surveys can reuse a station basename), got " +
    JSON.stringify(xmlNames));
  ok(xmlNames.some(n => /alpha\/LICENSE\.txt$/.test(n)),
    "SELFMT xml: the rights must travel with the bytes, one LICENSE.txt per included survey, got " +
    JSON.stringify(xmlNames));
  const xmlGap = zipBody(zmark, /NOT_INCLUDED/);
  ok(xmlGap != null, "SELFMT xml: a selected station with no EMTF XML must be reported in the archive, " +
    "never dropped in silence; entries were " + JSON.stringify(xmlNames));
  ok(/\bG1\b/.test(String(xmlGap)),
    "SELFMT xml: the gap note must NAME the skipped station, got " + JSON.stringify(String(xmlGap).slice(0, 300)));
  ok(String(xmlGap).indexOf("A1") < 0 && String(xmlGap).indexOf("A2") < 0,
    "SELFMT xml: the gap note must list only what was skipped, got " + JSON.stringify(String(xmlGap).slice(0, 300)));

  // (c) MTH5 export. The SAME contract over a different gap: A2 is the station with no file this time.
  fmark = fetchOrder.length; zmark = zipEntries.length;
  await h5Btn.onclick();
  const h5Urls = fetchedExt(fmark, ".h5");
  ok(h5Urls.length === 2, "SELFMT h5: the export must fetch one file per selected station THAT HAS an " +
    "MTH5 (A1 and G1, never A2, which has none), got " + JSON.stringify(h5Urls));
  ok(h5Urls.every(u => u.indexOf(SELFLAG) >= 0),
    "SELFMT h5: every file the export fetches must carry " + SELFLAG + ", got " + JSON.stringify(h5Urls));
  ok(h5Urls.every(u => u.split("?")[0].indexOf("/h5/") >= 0),
    "SELFMT h5: the export must fetch the h5/ station files, got " + JSON.stringify(h5Urls));
  ok(fetchedExt(fmark, ".edi").length === 0 && fetchedExt(fmark, ".xml").length === 0,
    "SELFMT h5: an MTH5 export must fetch nothing but MTH5");
  const h5Names = zipNames(zmark);
  ok(h5Names.filter(n => /\.h5$/.test(n)).length === 2,
    "SELFMT h5: the zip must hold one entry per fetched file, got " + JSON.stringify(h5Names));
  ok(h5Names.some(n => /alpha\/A1\.h5$/.test(n)) && h5Names.some(n => /gamma\/G1\.h5$/.test(n)),
    "SELFMT h5: entries must be namespaced by survey slug, got " + JSON.stringify(h5Names));
  ok(h5Names.filter(n => /LICENSE\.txt$/.test(n)).length === 2,
    "SELFMT h5: a selection spanning two surveys must carry BOTH custodians' LICENSE.txt, got " +
    JSON.stringify(h5Names));
  const h5Gap = zipBody(zmark, /NOT_INCLUDED/);
  ok(h5Gap != null && /\bA2\b/.test(String(h5Gap)),
    "SELFMT h5: the gap note must name A2, the selected station with no MTH5, got " +
    JSON.stringify(String(h5Gap).slice(0, 300)));

  // (d) The two new flows are the ONLY thing that changed about the label: the drawer's single-station
  //     download is still unlabelled, so the single-vs-bulk split downstream still means what it says.
  fmark = fetchOrder.length;
  await A.dispatchProd({ prod: "fetch", url: "h5/alpha/A1.h5", name: "A1.h5" });
  ok(fetchedExt(fmark, ".h5").every(u => u.indexOf("sel=") < 0),
    "SELFMT: a single-station MTH5 download must still carry NO selection flag, got " +
    JSON.stringify(fetchedExt(fmark, ".h5")));

  // (e) TRANSPORT FAILURE. A selected station can be absent from the archive for three different reasons,
  //     and the third is not a statement about the corpus at all: the file IS served, and the fetch for it
  //     did not come back. Reporting that station under "no MTH5 is served for these" would tell a reader
  //     their station has no such file, when in fact one exists and the network dropped it, and the second
  //     attempt they would never make is the one that works. The branch has been in the flow since the
  //     export shipped and no driver could enter it: every artifact fetch in this harness resolved ok.
  //     G1 has an h5 row; its fetch is made to fail. A2 still has no row at all, so ONE archive now
  //     carries both kinds of gap and the pin can prove they are told apart rather than pooled.
  fetchFail.add("h5/gamma/G1.h5");
  fmark = fetchOrder.length; zmark = zipEntries.length;
  await h5Btn.onclick();
  ok(fetchedExt(fmark, ".h5").length === 2,
    "SELFMT fail: the export must still ATTEMPT both served files, got " + JSON.stringify(fetchedExt(fmark, ".h5")));
  const failNames = zipNames(zmark);
  ok(failNames.filter(n => /\.h5$/.test(n)).length === 1 && failNames.some(n => /alpha\/A1\.h5$/.test(n)),
    "SELFMT fail: only the file that ARRIVED may be in the archive, got " + JSON.stringify(failNames));
  ok(failNames.filter(n => /LICENSE\.txt$/.test(n)).length === 1,
    "SELFMT fail: the rights instrument must cover the surveys actually INCLUDED, not the ones attempted, got " +
    JSON.stringify(failNames));
  const failGap = String(zipBody(zmark, /NOT_INCLUDED/));
  ok(failGap !== "undefined", "SELFMT fail: a fetch that did not come back must be reported in the archive, " +
    "never dropped in silence; entries were " + JSON.stringify(failNames));
  const iTransport = failGap.indexOf("network or server"), iG1 = failGap.indexOf("G1"), iA2 = failGap.indexOf("A2");
  ok(iTransport >= 0, "SELFMT fail: the archive must carry a TRANSPORT section, got " + JSON.stringify(failGap.slice(0, 400)));
  ok(iG1 > iTransport,
    "SELFMT fail: the station whose fetch failed must be listed under the transport section, not under the " +
    "not-served one (its file exists; saying otherwise is a false claim about the corpus), got " +
    JSON.stringify(failGap.slice(0, 500)));
  ok(iA2 >= 0 && iA2 < iTransport,
    "SELFMT fail: the station with no file at all must stay under the not-served section, so the two kinds " +
    "of gap are not pooled, got " + JSON.stringify(failGap.slice(0, 500)));
  ok(/try the export again/.test(failGap),
    "SELFMT fail: a transport fault must tell the reader the retry is worth making, got " +
    JSON.stringify(failGap.slice(0, 500)));

  // (f) EVERY FETCH FAILS. The floor of the same branch, and the only path that writes README.txt: nothing
  //     arrived, so there is no archive content to explain itself, and a zip holding only a gap note would
  //     otherwise read as an empty download. It must NOT toast "Nothing to package" and return (that is the
  //     genuinely-empty selection, a different fact), and it must carry no LICENSE.txt, because a rights
  //     instrument beside no bytes claims a survey is in an archive it is not in.
  fetchFail.add("h5/alpha/A1.h5");
  fmark = fetchOrder.length; zmark = zipEntries.length;
  await h5Btn.onclick();
  const allFailNames = zipNames(zmark);
  ok(fetchedExt(fmark, ".h5").length === 2 && allFailNames.filter(n => /\.h5$/.test(n)).length === 0,
    "SELFMT allfail: both fetches are attempted and neither lands, so no file entry may exist, got " +
    JSON.stringify(allFailNames));
  const readme = String(zipBody(zmark, /README\.txt$/));
  ok(readme !== "undefined",
    "SELFMT allfail: an archive with nothing in it must say so in a README, not arrive silently empty; " +
    "entries were " + JSON.stringify(allFailNames));
  ok(/MTH5/.test(readme) && /NOT_INCLUDED/.test(readme),
    "SELFMT allfail: the README must name the format and point at the file that lists the stations, got " +
    JSON.stringify(readme));
  ok(allFailNames.filter(n => /LICENSE\.txt$/.test(n)).length === 0,
    "SELFMT allfail: no bytes were included, so no custodian's licence may travel with the archive, got " +
    JSON.stringify(allFailNames));
  const allFailGap = String(zipBody(zmark, /NOT_INCLUDED/));
  ok(/\bA1\b/.test(allFailGap) && /\bG1\b/.test(allFailGap) && /\bA2\b/.test(allFailGap),
    "SELFMT allfail: all three selected stations must be accounted for, each under its own reason, got " +
    JSON.stringify(allFailGap.slice(0, 600)));
  fetchFail.clear();

  // (g) ONE ANALYTICS VOCABULARY ACROSS THE THREE ZIPS. The fold behind these events cannot see the
  //     difference between "two buttons describe themselves differently" and "two buttons do different
  //     things". The EDI zip reported format:"zip" and the two new ones reported format:"emtfxml" /
  //     format:"mth5", so the same action (zip a selection) landed in two different vocabularies and the
  //     three flows could not be summed, compared, or charted as one series. One shape now: format is what
  //     the reader receives (a zip) and `files` is what is inside it.
  const tmark = trackCalls.length;
  await ediBtn.onclick(); await xmlBtn.onclick(); await h5Btn.onclick();
  const dl = trackCalls.slice(tmark).filter(e => e.name === "DownloadGenerated");
  ok(dl.length === 3, "SELFMT event: each of the three zip buttons must report exactly one download event, got " +
    JSON.stringify(trackCalls.slice(tmark)));
  ok(dl.every(e => e.props.format === "zip"),
    "SELFMT event: all three bulk exports deliver a zip, so all three must SAY zip; a per-format `format` " +
    "puts the same action in two vocabularies, got " + JSON.stringify(dl.map(e => e.props)));
  ok(dl.map(e => e.props.files).join(",") === "edi,emtfxml,mth5",
    "SELFMT event: the format actually packaged rides its own field, in button order, got " +
    JSON.stringify(dl.map(e => e.props)));
  ok(dl.every(e => e.props.n === 3),
    "SELFMT event: every export must report the selection size it was given, got " + JSON.stringify(dl.map(e => e.props)));

  // (h) THE MANIFEST INDEX IS PER MANIFEST. artifactsFor() answers from an ausmt_id -> rows index built
  //     once per manifest (data.js mfFileIndex), which is what takes the size repaint off the keystroke
  //     path. A cache is a wrong answer that never goes away unless something invalidates it, and this one
  //     is invalidated by the manifest's own identity precisely so no caller has to remember to. Swap the
  //     manifest for one with different rows and every reader of the index must move with it.
  A.setManifest({ files: [{ ausmt_id: "au.alpha.A1", format: "emtfxml", url: "xml/alpha/A1.xml", size: 1048576 }], bundles: [] });
  A.refresh();
  ok(/~1\.0 MB/.test(rowMeta(xmlBtn)),
    "SELFMT index: a swapped manifest must be read immediately (A1's new 1.0 MB XML row), got " +
    JSON.stringify(rowMeta(xmlBtn)) + " (a stale index would still be showing the previous manifest)");
  ok(rowMeta(h5Btn).indexOf("~") < 0,
    "SELFMT index: rows the new manifest does NOT carry must stop being counted, got " +
    JSON.stringify(rowMeta(h5Btn)));
  // (h2) ARCHIVE-SCALE SIZES. The MTH5 selection zip is the multi-GB case, so the label must use the
  //      archive-scale formatter (like the level chooser and the hand-off snackbar), never
  //      "10108.9 MB". 10,600,000,000 B is ~9.9 GB.
  A.setManifest({ files: [{ ausmt_id: "au.alpha.A1", format: "mth5", url: "mth5/alpha/A1.h5", size: 10600000000 }], bundles: [] });
  A.refresh();
  ok(/~9\.9 GB/.test(rowMeta(h5Btn)),
    "SELFMT size: a multi-GB total must render in GB, got " + JSON.stringify(rowMeta(h5Btn)));
  A.setManifest(SEL_MANIFEST); A.refresh();
  ok(/~2\.1 MB/.test(rowMeta(xmlBtn)) && /~1\.1 MB/.test(rowMeta(h5Btn)),
    "SELFMT index: swapping back must restore the original totals, got " +
    JSON.stringify([xmlBtn.textContent, h5Btn.textContent]));

  // (i) Size honesty has a floor: with no manifest there are no sizes, and a "~0 B" would be a claim
  //     about the corpus rather than about what is known. No estimate at all is the honest state.
  A.setManifest(null); A.refresh(); A.setSelected(["A1", "A2", "G1"]);
  ok(xmlBtn.textContent.indexOf("~") < 0 && h5Btn.textContent.indexOf("~") < 0 && ediBtn.textContent.indexOf("~") < 0,
    "SELFMT size: with no download index there is nothing to estimate, so no size may be shown, got " +
    JSON.stringify([xmlBtn.textContent, h5Btn.textContent, ediBtn.textContent]));
  A.setSelected([]);

  // ---- DP. DRAWER-POLISH LANE (owner feedback 2026-08-19): slot mapping + the grid's link treatment ----
  // Driven on Delta, which every earlier section has finished with, so nothing above is perturbed.
  //
  // (1) `entire` FILLS the Collection slot. `entire` means ONE record covering all levels - the umbrella
  //     record the Collection slot names - so it belongs in that slot, not in the extra-tile bucket it used
  //     to fall into. The fixture is Gawler Phase 2's real shape: a GSSA/SARIG umbrella landing page
  //     (identifies: entire, NO `collection` row) plus its level3 models record. RED on the pre-lane build:
  //     the Collection tile stayed muted, the head read "1 of 6 recorded", and the umbrella record hung
  //     below the grid as an orphan seventh tile.
  A.setSMETA("Delta Survey", { instrument_pid: "10.82388/bt6orvhn", related_identifiers: [
    { identifier: "https://pid.sarig.sa.gov.au/dataset/mesac487", identifier_type: "URL", relation: "IsVariantFormOf", custodian: "GSSA/SARIG", identifies: "entire" },
    { identifier: "https://pid.sarig.sa.gov.au/dataset/mesac525", identifier_type: "URL", relation: "IsSourceOf", custodian: "GSSA/SARIG", identifies: "level3" },
  ] });
  A.openSurvey("Delta Survey");
  const drwDP = doc.getElementById("drawer");
  const dpHead = () => [...drwDP.querySelectorAll(".sechead")].find(h => /Data at every level:/.test(h.textContent));
  const dpTiles = () => [...dpHead().nextElementSibling.querySelectorAll(".prod")];
  ok(dpHead(), "SLOT: the survey drawer must carry the 'Data at every level:' section head");
  ok(/2 of 6 recorded/.test(dpHead().textContent),
    "SLOT: an `entire`-only survey must count 2 of 6 (Collection + Level 3), got: " + JSON.stringify(dpHead().textContent));
  ok(dpTiles().length === 6,
    "SLOT: `entire` must FILL the Collection slot, leaving exactly six tiles and no orphan extra, got " + dpTiles().length);
  ok(!dpTiles()[0].classList.contains("dis") && /mesac487/.test(dpTiles()[0].innerHTML),
    "SLOT: slot 1 (Collection) must be filled by the `entire` umbrella record, got: " + JSON.stringify(dpTiles()[0].textContent.slice(0, 60)));
  ok(/mesac525/.test(dpTiles()[5].innerHTML), "SLOT: slot 6 (Level 3) must still take the level3 row");
  ok(!/Entire dataset/.test(drwDP.innerHTML),
    "SLOT: a row that filled a slot must not ALSO render as an extra tile");

  // (2) COLLISION RULE: a survey carrying BOTH `collection` and `entire` gives the slot to the EXACT key;
  //     the alias renders as an extra tile (nothing is ever silently dropped) and "N of 6" tallies the
  //     SLOT, never the pair. `entire` is declared FIRST here on purpose: an implementation that took the
  //     first row matching either key would hand it the slot and fail this pin visibly.
  A.setSMETA("Delta Survey", { related_identifiers: [
    { identifier: "10.25914/umbrella", identifier_type: "DOI", relation: "IsVariantFormOf", custodian: "GA", identifies: "entire" },
    { identifier: "10.25914/exact", identifier_type: "DOI", relation: "IsPartOf", custodian: "NCI", identifies: "collection" },
  ] });
  A.openSurvey("Delta Survey");
  ok(/1 of 6 recorded/.test(dpHead().textContent),
    "COLLISION: the count must tally the SLOT (1 of 6), not both colliding rows, got: " + JSON.stringify(dpHead().textContent));
  ok(dpTiles().length === 7, "COLLISION: six slots plus the collision-losing extra tile, got " + dpTiles().length);
  // Match on the FULL identifier, not the bare word: the Collection slot's own description ("the umbrella
  // record for everything this survey deposited") carries the word `umbrella` and would false-positive.
  ok(/10\.25914\/exact/.test(dpTiles()[0].innerHTML) && !/10\.25914\/umbrella/.test(dpTiles()[0].innerHTML),
    "COLLISION: the exact `collection` row must win slot 1 over the `entire` alias");
  ok(/Entire dataset/.test(dpTiles()[6].textContent) && /10\.25914\/umbrella/.test(dpTiles()[6].innerHTML),
    "COLLISION: the losing `entire` row must survive as an extra tile, never be dropped");

  // (3) LINK TREATMENT. index.html is the REAL page in this harness, so this asserts the CASCADE rather
  //     than a string: for every anchor the grid renders, some rule in the document's own stylesheet that
  //     sets the accent colour must SELECT that anchor - and the :visited form of the rule must exist too,
  //     so a followed DOI can never fall back to the browser's purple. RED before this lane: NO rule in
  //     the sheet selected these anchors at all, so the DOIs, the Rees citation and the platform PID
  //     rendered in the UA's dark blue on the navy tiles (the owner's screenshot). jsdom resolves no
  //     custom properties, so this proves SELECTION and the declared value, not the painted pixel.
  A.setSMETA("Delta Survey", { instrument_pid: "10.82388/bt6orvhn", related_identifiers: [
    { identifier: "10.25914/link-collection", identifier_type: "DOI", relation: "IsPartOf", custodian: "NCI", identifies: "collection" },
  ] });
  A.openSurvey("Delta Survey");
  const sheetRules = [...doc.styleSheets].flatMap(s => { try { return [...s.cssRules]; } catch (e) { return []; } });
  const accentRules = sheetRules.filter(r => r.style && /var\(--copper\)/.test(r.style.color || ""));
  ok(accentRules.length > 0, "LINKCSS: no rule in index.html sets color:var(--copper) at all - the probe is broken, not the sheet");
  // jsdom (like a real browser) refuses to match :visited from script, so strip the pseudo-class before
  // matching and require it in the SELECTOR TEXT instead - the two halves together are the real claim.
  const selectedBy = (el, wantVisited) => accentRules.some(r => String(r.selectorText).split(",").some(sel => {
    sel = sel.trim();
    if (wantVisited !== (sel.indexOf(":visited") >= 0)) return false;
    try { return el.matches(sel.replace(/:visited/g, "")); } catch (e) { return false; }
  }));
  const gridRoot = dpHead().parentElement;
  const gridAnchors = [...gridRoot.querySelectorAll(".dl-id a, .dl-cite a, .dl-instr a")];
  ok(gridAnchors.length === 3,
    "LINKCSS: expected the three grid link sites (tile identifier, Rees citation, platform PID), got " + gridAnchors.length);
  gridAnchors.forEach(a => {
    const where = a.parentElement.className || a.parentElement.tagName;
    ok(selectedBy(a, false), "LINKCSS: no accent rule selects the grid anchor in '" + where + "' (" + a.getAttribute("href") + ")");
    ok(selectedBy(a, true), "LINKCSS: no accent :visited rule selects the grid anchor in '" + where + "' - it may go browser-purple once followed");
  });
  // The negative: an unrecorded level's state text is a statement, not a link, and no accent rule may take it.
  A.setSMETA("Delta Survey", { instrument_pid: null, related_identifiers: [] });
  A.openSurvey("Delta Survey");
  const stateSpans = [...dpHead().parentElement.querySelectorAll(".dl-state")];
  ok(stateSpans.length === 6, "LINKCSS: expected six muted 'not yet recorded' states, got " + stateSpans.length);
  stateSpans.forEach(s => {
    ok(!s.querySelector("a"), "LINKCSS: the 'not yet recorded' state must never be a link");
    ok(!selectedBy(s, false), "LINKCSS: the muted state text must not be painted the link accent");
  });

  console.log("INTERACTION PASSED (tree country+org toggles, UX5 collections-group-first + push-sync + O1 no-nested-member-list + collapse INVARIANT + caret click-target + gating-off + D8 tour-restore x3 exit paths, collection route+Back, Find (+F3 keyboard nav: ArrowDown active-descendant/Enter-activates/Esc-clears), survey route, intro panel, tour v4 incl. Find-demo real-input+dropdown + tree-browse kalkaroo-degrade + exit hooks on Next/Back/close + drawer-open+restore, empty-state intro, year filter+hints, go-to-place removal, screening(advanced) collapse, recently-added, C1b embargo access panel, PID links survey_pid/collection_pid/instrument pid + hostile-pid inert, ver-chip-off-the-SPA, one-header-help-button, UX4 AusLAMP membership+label→slug + empty-set degrade + O5 radiusForZoom-one-step-smaller/weightForZoom pins+monotone + A1 colour-identical-all-modes + O4 tooltip station+survey-only, dots-only-at-every-zoom(F4 zero badges + painted dots == filtered count + circleMarkers only + no legend badge row) + no-pane structural invariant(F5), still-counted-across-containers, card-desc-from-yaml + hostile-blurb-inert + fallback, dimensionality-hidden-strike/skew-kept, C20 arrow-panel+Parkinson-label+south-sign-mapping + error-bars-present/absent + no-tipper-state, C22 citation-honesty no-DOI-placeholder-free + with-DOI-kept + NCI-byte-pin + txt-no-DOI-note, " +
    "UX6-Wave-C drawer-tabs+ARIA + sticky-header-download/cite + section-role-chips + yx-square/xy-circle-markers + full-station-response-modal(all-panels+identity-header+honest-coords+2x)+Esc/click-out+focus-return+non-tipper-no-arrow-panel + C1b-fence-under-tabs, " +
    "UX7b U6 panel-retitles (Discover-heading/Explore-data/API-access) + U7 welcome-popup first-visit-modal + role=dialog + focus-in + checkbox-persistence-matrix(tour/browse/Esc/click-out × ticked/unticked) + take-tour-starts-tour + help-panel-on-demand-no-persist + empty-state-popup + U8 card-anchor side-pick/no-overlap/caret-aim(4 sides) + U9 copper-Next + U10 dim-0.78, " +
    "UX8 5-tabs+Response-default + Station-summary-fold(4 groups) + Screening-indicators(field-map+mutation+na) + maturity-stars(achieved-count) + prov-collapse+API-expander + legend-in-map-container + W3b lic-canon+attribution+source-node+cite-fallback + CVD-ramp exact-hexes+monotone-luminance+null-grey+qvdot-not-text, " +
    "D2 Browse/Select mode toggle ids-intact + auto-switch-on-select-all + tour-selbox-step mode-switch+3-path-restore, " +
    "D3 draw-toast copy+fires+auto-switch, Draw-buttons in-SELECTION-panel reuse-toolbar-handler + shared-armedDrawMode(button/icon parity) + complete/cancel-clears-both, " +
    "D4 export-empty-state hide/reveal, D5 sidebar-collapse class+invalidateSize+persist, D6 map-legend tokens+collapse, " +
    "LEG interactive-legend (type rows PROXY the rail checkboxes: rail flip + marker-set + header count, exact type keys/order, " +
    "button semantics + aria-pressed, two-way dim from the rail, Enter/Space + preventDefault-no-double-fire, " +
    "all-four-off empty map reads '0 shown' and restores, affordance hint at the top, select-lens never captures a type toggle), " +
    "UX6-Wave-E slim-card field-set+removed-blocks-absent + discovery sort/count/compact + completeness-not-a-ranking fence + E2 identifiers-rollup N-of-M+collapsed-list + E4 detail-section-order + E6 collScatter AU-outline-beneath-dots+per-survey-legend+view-on-map fitBounds + E7 drawer role=dialog+focus-in+focus-restore, " +
    "CLEANUP-WAVE recently-added-single-strip+30day-build-window (rail #recentSide deleted, leak fixed) + facet-swap(Open-licence+data-type chips, DOI/tipper gone)+survey-search(name/org/region/blurb) + rail-hidden-on-surveys/collections/detail + drawer-scrim(non-map click-close) + collections-redesign(one-rich-card+full-abstract+two-column-hero, intro/collnote deleted), " +
    "CARD-POLISH one-attribution-box(single .attn, names ORCID/ROR-linked in place, text == attributionText) + contributors-above-Downloads + lineage software(station-level-wins/survey-fallback/no-invented-version, node == prov row) + AusMT-Provenance-title + formats(served-only, no ticks/(pipeline), embargoed claims nothing) + publication-node-from-pubs(short cite + N-more, no fabricated et al., none-recorded when empty), " +
    "DRAWER-POLISH slot-alias(`entire` fills Collection: 2-of-6 + six tiles + no orphan) + collision-rule(exact `collection` wins the slot, alias survives as an extra, count tallies the slot) + 'Data at every level' head + LINKCSS accent rule SELECTS all three grid link sites incl. :visited, muted state text excluded, " +
    "THREDDS ts_access.json phase-2(ten-fetch boot + held-with-the-heavies + unknown-vs-empty + absence-is-not-failure) + " +
    "ONE Availability group(#dlOnly/#qSeg gone, tfAvail keeps the s.ediAvail predicate, four routable level buttons and no level2, " +
    "in-flight disabled+aria-busy+inert-filter, settled-empty says 'publishes no download index' and never 'could not be loaded', " +
    "per-level count+size+gloss summed from ts_access and NOT from the download manifest, multi-select union filter, embargoed station unreachable by any level) + " +
    "hand-off(#dlTs pointer file in the #dlSh shape: /go/ts/ routes + inert archive address percent-encoded like the engine, " +
    "chooser-scoped, embargoed station absent, wget-follows/curl-needs-L note, no new track() call site, " +
    "'Download list ready' + wget/curl COPY button carrying the routes and not the archive, " +
    "JOIN RULE action row driven by the index alone under an empty ts_levels with the survey sub-text intact, no fourth badge, " +
    "single-station snackbar names file+size+where-progress-lives, >5GB line, untracked open) + " +
    "K5 hand-off command safety(collision: curl -o + wget -P namespaced <slug>/<level>/<basename> so a station's " +
    "same-named levels never overwrite/resume-corrupt; injection: POSIX single-quoted -o on macOS/Linux, " +
    "safe-charset -o on Windows curl.exe, wget carries only encoded routes; --create-dirs builds the tree) + " +
    "scale bar(metric-only maxWidth 120, added, own container re-parented into .maplegend-body, four dots and #map parenting intact))");

  // ---- Two-phase boot, part 3: hydration yields the boot pipe to phase 1 --------------------------
  // Phase-2 products are big (tf.json is ~2.6MB gzipped) and the dots need only the catalogue's
  // ~163KB, so hydration issued alongside phase 1 contends for the same connection and delays the
  // first paint it exists to protect. The pin drives a fresh boot with the CATALOGUE fetch held and
  // asserts no phase-2 product is even REQUESTED while phase 1 is in flight; releasing the catalogue
  // must then let hydration run to completion, so the ordering change can never quietly become
  // "hydration never starts".
  {
    const d2 = new JSDOM(html, { url: "http://localhost/", runScripts: "outside-only", pretendToBeVisual: true });
    const w2 = d2.window;
    w2.L = stub(); w2.JSZip = stub();
    w2.AUSMT_CONFIG = { short_name: "AusMT" };
    const order2 = [];
    let releaseCat = null;
    const HEAVY2 = /tf\.json|sci\.json|manifest\.json|ts_access\.json/;
    w2.fetch = url => {
      order2.push(String(url));
      const body = DATAMAP[url] ? { ok: true, json: () => Promise.resolve(DATAMAP[url]) } : { ok: false };
      if (/catalogue\.json/.test(String(url))) return new Promise(res => { releaseCat = () => res(body); });
      return Promise.resolve(body);
    };
    await new Promise(res => (w2.document.readyState === "complete" ? res() : w2.addEventListener("load", res, { once: true })));
    vm.runInContext(code, d2.getInternalVMContext());
    const bootP = w2.__api.boot();
    for (let i = 0; i < 8; i++) await Promise.resolve();
    ok(releaseCat, "hydration-order: the catalogue fetch must have been issued at boot");
    ok(!order2.some(u => HEAVY2.test(u)),
      "hydration-order: no phase-2 product may be REQUESTED while phase 1 is in flight, got " + order2.join(","));
    releaseCat();
    await bootP;
    await w2.__api.hydrationDone();
    ok(order2.some(u => /tf\.json/.test(u)) && order2.some(u => /ts_access\.json/.test(u)),
      "hydration-order: hydration must still run to completion once phase 1 settles, got " + order2.join(","));
  }

  // ---- Link-preview metadata (Open Graph + Twitter card) ------------------------------------------
  // Pasting the portal URL into Slack/Teams/X produced a bare link: the shipped head carried a
  // <title> and nothing else. These pins hold the preview surface: a real description, the og
  // quartet, the twitter card, and the card image as an actual PNG on disk. The og:image/og:url are
  // ABSOLUTE on the institutional name: preview crawlers resolve nothing relative.
  {
    const _m = sel => { const el = doc.querySelector(sel); return el ? (el.getAttribute("content") || "") : null; };
    ok((_m('meta[name="description"]') || "").length > 60,
      "og: index.html must ship a real meta description, got " + JSON.stringify(_m('meta[name="description"]')));
    ok(_m('meta[property="og:title"]') === "AusMT - Australia's Magnetotelluric Data Portal",
      "og: og:title must carry the portal title, got " + JSON.stringify(_m('meta[property="og:title"]')));
    ok((_m('meta[property="og:description"]') || "").length > 60,
      "og: og:description must be a real sentence, got " + JSON.stringify(_m('meta[property="og:description"]')));
    ok(_m('meta[property="og:url"]') === "https://ausmt.auscope.org.au/",
      "og: og:url must be the absolute institutional URL, got " + JSON.stringify(_m('meta[property="og:url"]')));
    ok(_m('meta[property="og:image"]') === "https://ausmt.auscope.org.au/vendor/social-card.png",
      "og: og:image must be the absolute card URL, got " + JSON.stringify(_m('meta[property="og:image"]')));
    ok(_m('meta[name="twitter:card"]') === "summary_large_image",
      "og: twitter:card must request the large-image preview, got " + JSON.stringify(_m('meta[name="twitter:card"]')));
    const _card = fs.readFileSync(path.join(PORTAL, "vendor", "social-card.png"));
    ok(_card.length > 20000 && _card[0] === 0x89 && _card[1] === 0x50,
      "og: vendor/social-card.png must be a real PNG with content, got " + _card.length + " bytes");
  }

  // ---- Basemap config plumbing (the CARTO key rides config, never code) ---------------------------
  // CARTO watermarks un-keyed raster tile requests. The key is a deployment value, so it lives in
  // portal.config.yaml -> gen_config -> config.js and map.js consults it; a SOURCE pin because the
  // L stub records navigation calls, not tileLayer URLs. Fails if map.js returns to a hardcoded
  // keyless tile URL.
  {
    const _mapSrc = fs.readFileSync(path.join(SRC, "map.js"), "utf8");
    ok(/basemap/.test(_mapSrc) && /carto_api_key/.test(_mapSrc),
      "basemap: map.js must consult AUSMT_CONFIG.basemap.carto_api_key for the tile URL");
    ok(/api_key=/.test(_mapSrc),
      "basemap: map.js must append the api_key query parameter when a key is configured");
  }

  // ---- Self-hosted basemap (pmtiles provider) -----------------------------------------------------
  // The basemap is the portal's LAST runtime third party. provider "pmtiles" serves it from our own
  // /basemap/ files through the vendored protomaps-leaflet renderer: the world file carries low
  // zooms globally (a zoomed-out view still shows the whole globe) and the region file carries full
  // detail for Australia and its surrounds; both paths ride config so a deployment can relocate or
  // date-stamp them without code. carto stays the configured fallback while the files roll out,
  // which is why the switch is data-driven and BOTH branches must keep existing.
  {
    const _mapSrc = fs.readFileSync(path.join(SRC, "map.js"), "utf8");
    ok(/provider/.test(_mapSrc) && /pmtiles/.test(_mapSrc),
      "basemap: map.js must switch on AUSMT_CONFIG.basemap.provider with a pmtiles branch");
    ok(/protomapsL\.leafletLayer/.test(_mapSrc),
      "basemap: the pmtiles branch must render through the vendored protomaps-leaflet");
    ok(/pmtiles_world/.test(_mapSrc) && /pmtiles_region/.test(_mapSrc),
      "basemap: both pmtiles paths must come from config, never hardcoded");
    ok(/OpenStreetMap contributors/.test(_mapSrc) && /Protomaps/.test(_mapSrc),
      "basemap: the pmtiles layers must carry the OSM + Protomaps attribution");
    const _vendored = fs.readFileSync(path.join(PORTAL, "vendor", "protomaps-leaflet.js"), "utf8");
    ok(_vendored.startsWith('"use strict";var protomapsL='),
      "basemap: vendor/protomaps-leaflet.js must be the verbatim upstream UMD (protomapsL global)");
    ok(/vendor\/protomaps-leaflet\.js/.test(html),
      "basemap: index.html must load the vendored renderer");
    const _cfgSrc = fs.readFileSync(path.join(PORTAL, "config.js"), "utf8");
    ok(/pmtiles_world/.test(_cfgSrc) && /pmtiles_region/.test(_cfgSrc) && /provider/.test(_cfgSrc),
      "basemap: generated config.js must carry provider + both pmtiles paths");
  }

  // ---- Discoverability: robots.txt + the root DataCatalog ----------------------------------------
  // The portal ships robots.txt naming the sitemap (the engine emits sitemap.xml + the tier-3
  // pages under the same flag), and the root page carries a schema.org DataCatalog block so the
  // portal itself is a first-class object in dataset search. Both are static shipped surfaces, so
  // both are source pins here.
  {
    const _robots = fs.readFileSync(path.join(PORTAL, "robots.txt"), "utf8");
    ok(/^User-agent: \*/m.test(_robots) && /^Allow: \//m.test(_robots),
      "discoverability: robots.txt must allow crawling");
    ok(/^Sitemap: https:\/\/ausmt\.auscope\.org\.au\/sitemap\.xml$/m.test(_robots),
      "discoverability: robots.txt must name the sitemap at the institutional URL");
    ok(/^Disallow: \/gateway$/m.test(_robots),
      "discoverability: robots.txt must keep crawlers out of the gateway surface");
    // EVERY block, not the first: the page carries two nodes (what it publishes, and what it IS),
    // and a pin that reads only the first would go quiet the moment their order changed.
    const _ldEls = Array.from(doc.querySelectorAll('script[type="application/ld+json"]'));
    ok(_ldEls.length === 2, "discoverability: index.html must carry two JSON-LD blocks, got " + _ldEls.length);
    const _nodes = _ldEls.map(el => {
      try { return JSON.parse(el.textContent); } catch (e) { die("discoverability: every JSON-LD block must parse: " + e); }
    });
    const _byType = {};
    _nodes.forEach(n => { _byType[n["@type"]] = n; });
    const _cat = _byType["DataCatalog"];
    ok(_cat && _cat.name === "AusMT",
      "discoverability: a DataCatalog node named AusMT is required, got " + JSON.stringify(Object.keys(_byType)));
    ok(_cat.url === "https://ausmt.auscope.org.au/",
      "discoverability: the DataCatalog url must be the institutional root");
    // The site's own name. Without it the only site-level name in the markup was the publisher's,
    // and search results labelled the whole portal AuScope.
    const _site = _byType["WebSite"];
    ok(_site, "discoverability: index.html must carry a WebSite node naming the site itself");
    ok(_site.name === "AusMT",
      "discoverability: the WebSite name must be AusMT, got " + JSON.stringify(_site.name));
    ok(_site.alternateName === "Australia's Magnetotelluric Data Portal",
      "discoverability: the WebSite alternateName must be the portal's full name, got " + JSON.stringify(_site.alternateName));
    ok(_site.url === "https://ausmt.auscope.org.au/",
      "discoverability: the WebSite url must be the institutional root");
    ok(_site.publisher && _site.publisher.name === "AuScope",
      "discoverability: the WebSite publisher must stay AuScope");
  }

  // ---- Map chrome: muted basemap + NO attribution control + Search Console ownership --------------
  // The protomaps light flavour renders a stronger sea blue than the portal's palette wants, and the
  // bundle exposes no per-colour flavour override, so the muting is a CSS filter scoped to the tile
  // pane ONLY (station overlays render in other panes and must keep full colour). The google-site-
  // verification meta proves domain ownership to Search Console; the content value is the owner's
  // token, pinned by shape so a token rotation is a one-line index.html edit.
  //
  // THE ATTRIBUTION CONTROL IS GONE FROM THE MAP at the owner's ask, and this is where that is
  // proven against a DRIVEN map rather than against source text: the map is built and rendered in
  // this document, so a control Leaflet still mounted would be in the DOM here. The credit itself
  // did not go: it is a licence obligation (ODbL basemap data, Protomaps tiles) and it now sits in
  // the footer, which is directly beneath the map and always on screen. Both halves are asserted
  // together, because either alone is the defect: the corner line without the footer line is the
  // owner's complaint, and the footer line without the corner removed is the same credit twice.
  {
    ok(/#map \.leaflet-tile-pane\{filter:[^}]*saturate\(/.test(html),
      "map-chrome: index.html must mute the basemap via a saturate filter on the tile pane only");
    ok(!/leaflet-overlay-pane\{[^}]*filter/.test(html) && !/#map\{[^}]*filter/.test(html),
      "map-chrome: the mute filter must never widen to the overlay panes or the whole map");
    ok(!/leaflet-control-attribution/.test(html),
      "map-chrome: index.html must not style an attribution control the map no longer mounts");

    // The map RENDERS: a Leaflet container with its pane stack, and the station dots this fixture
    // supplies drawn into it. Without this the assertion below would pass on a map that failed to
    // build at all, which is the one way "no attribution control" is true and worthless.
    const _mapEl = doc.getElementById("map");
    ok(_mapEl && _mapEl.classList.contains("leaflet-container"),
      "map-chrome: the map must still build a Leaflet container");
    ok(doc.querySelectorAll("#map .leaflet-map-pane").length === 1 &&
       doc.querySelectorAll("#map .leaflet-tile-pane").length === 1 &&
       doc.querySelectorAll("#map .leaflet-overlay-pane").length === 1,
      "map-chrome: the rendered map must carry its pane stack");
    ok(doc.querySelectorAll("#map .leaflet-control-attribution").length === 0,
      "map-chrome: the rendered map must mount NO attribution control, and so print no Leaflet prefix");

    // The credit, in the footer, under the acknowledgement, with both sources linked and both links
    // leaving the tab the way every other outbound anchor on this site does.
    const _credit = doc.querySelector("footer .fcenter .mapcredit");
    ok(_credit, "map-chrome: the SPA footer must carry the basemap credit under the acknowledgement");
    ok(_credit.textContent.replace(/\s+/g, " ").trim() ===
       "Map data \u00a9 OpenStreetMap contributors, tiles \u00a9 Protomaps",
      "map-chrome: the credit wording is the ruling's, got " + JSON.stringify(_credit.textContent));
    const _cl = [..._credit.querySelectorAll("a")];
    ok(_cl.length === 2 &&
       _cl[0].getAttribute("href") === "https://www.openstreetmap.org/copyright" &&
       _cl[1].getAttribute("href") === "https://protomaps.com",
      "map-chrome: the credit links its two sources, OSM's copyright page then Protomaps");
    ok(_cl.every(a => a.getAttribute("target") === "_blank" &&
                      a.getAttribute("rel") === "noopener noreferrer"),
      "map-chrome: a credit link leaves the site, so it opens in a new tab and hands it no opener");

    const _gsv = doc.querySelector('meta[name="google-site-verification"]');
    ok(_gsv && /^[A-Za-z0-9_-]{20,}$/.test(_gsv.getAttribute("content") || ""),
      "map-chrome: index.html must carry the google-site-verification meta with a token-shaped content");
  }

  process.exit(0);
})().catch(e => die((e && e.stack) || String(e)));
