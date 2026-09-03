"use strict";
// Map + layers + markers. Data-dependent work (markers, footprints) is in buildMarkers()/
// buildFootprints(), called by main after ST is built. No direct call into drawer/filters at
// load time; the only cross-module reference is the marker click -> openStation (one-way).
// UX feedback round 1: default to a fixed Australia extent on load (was an arbitrary centre/zoom pair
// that didn't reliably frame the continent on typical viewport sizes). Bounds: [[south,west],[north,east]]
// chosen to cover the AU mainland + Tasmania with a small margin.
// BuildMarkers() USED to re-fit to the tight station-marker extent once data
// loaded — but because no station sits north of ~-22.5 lat, that fit dropped the view SOUTH (centre ~-33.6)
// And clipped northern Australia. This fixed
// Australia framing, so the home view is now ALWAYS this box (below): every station (lon 115.85..148.17,
// lat -43.44..-22.48) falls inside it, so it shows all dots AND frames the whole continent. Defined ONCE
// here as AU_HOME_BOUNDS and shared by the initial fit and buildMarkers()'s HOME_BOUNDS so the two frames
// cannot drift apart.
const AU_HOME_BOUNDS=L.latLngBounds([[-44.5,111.5],[-10,155]]);
// THE ATTRIBUTION CONTROL IS MOUNTED BELOW, not here. Leaflet's default control is the one that
// carries the flag and the word "Leaflet", which is a courtesy to a library rather than a licence
// term and is what came off the map, so the map is created without one and
// src/mapattrib.js mounts a control with prefix:false in its place, collapsed behind a small (i).
// The CREDIT itself stays on the map: it is a licence obligation, and only the layer that is
// actually drawing knows which provider to name.
const map=L.map("map",{preferCanvas:true,attributionControl:false}).fitBounds(AU_HOME_BOUNDS);
// The basemap is config-driven. provider "pmtiles" serves OUR OWN files through the vendored
// protomaps-leaflet renderer, ending the portal's last runtime third party: the world file
// carries low zooms globally (zoomed out still shows the whole globe) and the region file
// carries full detail for Australia and its surrounds; the z7 crossover is where the region
// bbox has data the world file lacks. "carto" is the hosted fallback while the files roll out
// (or if the renderer failed to load); CARTO watermarks un-keyed raster requests, so the
// deployment's key (config, public by nature) rides the tile URL when set.
// EACH BRANCH STATES ITS OWN CREDIT, and the control prints whichever layer is on the map. This is
// what a single fixed line of prose elsewhere on the page could not do: a deployment running on the
// fallback would have been served CARTO tiles under a Protomaps credit. Both are rendered from
// OpenStreetMap data, so both name OSM; the second name is the provider that built the tiles.
// The links open the way every outbound anchor on this site opens.
const _OSM_CREDIT='\u00a9 <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors';
const _PM_CREDIT=_OSM_CREDIT+', \u00a9 <a href="https://protomaps.com" target="_blank" rel="noopener noreferrer">Protomaps</a>';
const _CARTO_CREDIT=_OSM_CREDIT+', \u00a9 <a href="https://carto.com/attributions" target="_blank" rel="noopener noreferrer">CARTO</a>';
var _bmCfg=(window.AUSMT_CONFIG&&window.AUSMT_CONFIG.basemap)||{};
if(_bmCfg.provider==="pmtiles"&&window.protomapsL){
  // The two pmtiles layers state the SAME credit and Leaflet prints it once: they are one basemap
  // split at the z7 crossover, not two sources.
  protomapsL.leafletLayer({url:_bmCfg.pmtiles_world||"/basemap/world.pmtiles",flavor:"light",lang:"en",maxZoom:7,maxDataZoom:6,attribution:_PM_CREDIT}).addTo(map);
  protomapsL.leafletLayer({url:_bmCfg.pmtiles_region||"/basemap/region.pmtiles",flavor:"light",lang:"en",minZoom:7,maxZoom:18,maxDataZoom:15,attribution:_PM_CREDIT}).addTo(map);
}else{
  var _bmKey=_bmCfg.carto_api_key?("?api_key="+encodeURIComponent(_bmCfg.carto_api_key)):"";
  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"+_bmKey,{maxZoom:18,attribution:_CARTO_CREDIT}).addTo(map);
}
// Mounted after the basemap so the control collects the layer already on the map, which is the
// order Leaflet's own default control is created in. Reached through window, the way every shared
// module on this site is (src/doi_harvest.js sets the precedent): the headless harnesses build a
// context where window is an object of their own rather than the global, and a bare identifier
// would resolve in the browser and nowhere else.
window.AusmtMapAttrib.mount(map,"Map data attribution");
// SITE LOCATIONS ONLY, at every zoom. The per-survey badge bubbles that
// replaced proximity clustering are removed with it - no badge, no leader tail, no decoration pane, no
// zoom threshold. A compact survey now overlaps into a tight group of dots at national zoom and the
// click-to-open-survey affordance the badge carried is gone. The
// drawer's own survey route (#/survey/<slug>) and a dot click are what remain.
// ONE dot container (change 6's own simplification, kept). There used to be two - a never-clustered plain
// layer for AusLAMP members and a markerClusterGroup for everything else - purely because clustering had to
// be withheld from the national LP grid. Nothing collapses now, so every station dot on the map is on the
// map the same way.
const dotLayer=L.layerGroup();
map.addLayer(dotLayer);
// AusLAMP membership is COLLECTION membership, not a data type - a station is AusLAMP iff its
// survey slug is a member of the collection with id `auslamp` in collections.json. AUSLAMP_SET (a Set of
// member SLUGS) is built once at boot from COLL/SMETA (buildAuslampSet, main.js); the pure predicate here
// takes it explicitly so it stays Leaflet-free and unit-testable (jsdom can't load Leaflet).
// NO MAP PATH READS IT now the map is dots-only: its one consumer was the badge rule's
// never-collapse privilege, and nothing collapses now. Kept (with AUSLAMP_SET and buildAuslampSet) because
// it is collection membership rather than map furniture; retiring the three is a separate decision,
// and the boot resolution of labels to slugs is pinned on its own.
function isAuslampSurvey(slug,auslampSet){return !!(slug&&auslampSet&&auslampSet.has(slug));}
// C42 coordinate access: a station whose custodian WITHHELD its coordinates carries null lat/lon in the
// served catalogue — the engine masks the VALUE (there is no separate policy field; withheld => null,
// generalised => a 0.1° cell rendered verbatim). hasPosition is the ONE pure predicate every map path
// uses to skip a position-less station: no marker, no footprint vertex, no fitBounds point, no spatial
// selection. It stays in ST (counted, findable by name); it simply is not ON the map. PURE + Leaflet-free
// so jsdom drives it directly (same idiom as isAuslampSurvey).
function hasPosition(s){return !!(s&&s.lat!=null&&s.lon!=null&&isFinite(s.lat)&&isFinite(s.lon));}
// Paint the currently-visible stations into the ONE dot container. Called by refresh() (a filter changed).
// `visible` (filters.js) is already the filtered set; only POSITIONED stations reach the layer, because a
// coordinate-withheld station has no marker (C42) and no place on the map. Every one of them is a dot: the
// set no longer depends on zoom or on the sidebar mode, so nothing else has to trigger a re-route.
// Returns what this pass painted. The app ignores the value; the jsdom driver calls the pass directly and
// reads it, because under a stubbed Leaflet the layer contents are unreadable Proxies.
function routeVisibleToLayers(){
  const dots=(typeof visible!=="undefined"?visible:[]).filter(hasPosition);
  dotLayer.clearLayers();
  dots.forEach(s=>{if(s.marker)dotLayer.addLayer(s.marker);});
  applySurveyDim();          // a re-render must not drop the change-2 focus dim
  return {dots};
}
const drawn=new L.FeatureGroup().addTo(map);
// Plain-language labels for the draw toolbar buttons. These override the generic
// leaflet.draw defaults ("Draw a polygon" etc.) and MUST be set BEFORE the control is constructed — the
// control reads L.drawLocal at build time to set each button's title (its accessible name).
L.drawLocal.draw.toolbar.buttons.polygon="Draw polygon selection";
L.drawLocal.draw.toolbar.buttons.rectangle="Draw rectangle selection";
L.drawLocal.edit.toolbar.buttons.remove="Clear drawn shapes";
// Kept as a named reference (was an inline `map.addControl(new ...)`) so the SELECTION panel's
// Draw rectangle/polygon buttons can REUSE this control's own mode handlers — see armDraw below.
const drawControl=new L.Control.Draw({draw:{polyline:false,circle:false,circlemarker:false,marker:false,
  polygon:{shapeOptions:{color:"#EF7256",weight:2}},rectangle:{shapeOptions:{color:"#EF7256",weight:2}}},edit:{featureGroup:drawn,edit:false,remove:true}});
map.addControl(drawControl);
// Explicit aria-labels on the draw + zoom toolbar anchors, set AFTER the controls
// are on the map (their DOM exists by then). leaflet.draw already writes the title from L.drawLocal above;
// the aria-label makes the accessible name unambiguous for AT. No-op where the anchors aren't rendered
// (e.g. the jsdom/smoke harness, which stubs Leaflet) — querySelectorAll simply returns nothing.
function labelToolbar(){
  const set=(sel,label)=>document.querySelectorAll(sel).forEach(a=>a.setAttribute("aria-label",label));
  set(".leaflet-draw-draw-polygon","Draw polygon selection");
  set(".leaflet-draw-draw-rectangle","Draw rectangle selection");
  set(".leaflet-draw-edit-remove","Clear drawn shapes");
  set(".leaflet-control-zoom-in","Zoom in");
  set(".leaflet-control-zoom-out","Zoom out");
}
labelToolbar();

// Discoverability: the SELECTION panel gained "Draw rectangle"/"Draw polygon"
// buttons that ARM the SAME leaflet.draw handlers the map's top-left toolbar icons arm — the panel used
// to point users to a tool at the opposite corner. We REUSE the control's own mode handlers
// (drawControl._toolbars.draw._modes[mode].handler — the exact object each toolbar icon enables), never
// a second draw invocation. Panel button, toolbar icon and armedDrawMode mirror ONE state: enabling a
// handler fires DRAWSTART (whatever the source) and disabling/completing/cancelling fires DRAWSTOP, so
// the armed reflection below stays true no matter which surface armed it.
let armedDrawMode=null;                                   // null | "rectangle" | "polygon" — the shared armed state
// The exact handler object the matching toolbar icon enables (leaflet.draw keys _modes by handler.type).
// Guarded navigation so a missing/stubbed control (the jsdom harness stubs L) is a no-op, never a throw.
function drawModeHandler(mode){const tb=drawControl&&drawControl._toolbars&&drawControl._toolbars.draw;
  const m=tb&&tb._modes&&tb._modes[mode];return m&&m.handler||null;}
// Reflect armedDrawMode onto the two panel buttons (the toolbar icons carry leaflet.draw's own enabled
// class, so they need no help here). Called on every arm/disarm so a button never looks inert while its
// tool is live, nor stays lit after a draw completes.
function syncDrawButtons(){[["drawRect","rectangle"],["drawPoly","polygon"]].forEach(([id,mode])=>{
  const b=document.getElementById(id);if(b)b.classList.toggle("armed",armedDrawMode===mode);});}
// Single writer for the shared state: set/clear the mode, then reflect it. The DRAWSTART/DRAWSTOP
// listeners below call this (so an icon-armed mode lights the buttons too); armDraw + onDrawCreated
// call it directly.
function setArmedDraw(mode){armedDrawMode=mode||null;syncDrawButtons();}
// Arm a mode FROM THE PANEL by enabling the control's own handler — identical to clicking the toolbar
// icon (leaflet.draw binds each icon to _modes[type].handler.enable). Setting armedDrawMode here gives
// immediate feedback and covers the L-stubbed harness, where the real DRAWSTART event never fires;
// production reconciles via the listeners below.
function armDraw(mode){const h=drawModeHandler(mode);if(h&&typeof h.enable==="function")h.enable();setArmedDraw(mode);}
map.on(L.Draw.Event.DRAWSTART,e=>setArmedDraw(e&&e.layerType));   // icon OR button arms -> both reflect
map.on(L.Draw.Event.DRAWSTOP,()=>setArmedDraw(null));            // complete OR cancel -> both clear
const _drawRect=document.getElementById("drawRect"),_drawPoly=document.getElementById("drawPoly");
if(_drawRect)_drawRect.onclick=()=>armDraw("rectangle");
if(_drawPoly)_drawPoly.onclick=()=>armDraw("polygon");

// The LPMT colour split was REMOVED - all LPMT renders the
// flagship teal (TYPE_COL.LPMT) in type mode regardless of AusLAMP membership, and every colour mode
// Is membership-blind. Now the map is dots-only NO map surface carries the AusLAMP/legacy
// distinction at all: it was last held by the D2 clustering split, which the badge rule inherited and
// Which is now gone.
// The colour-by control is retired; markers carry the data-type colour, a
// phase-1 fact (the legend is the surviving colour surface). qColor lives on for the drawer's
// completeness dot.
function markerColor(s){return TYPE_COL[s.type]||"#999";}
function recolor(){ST.forEach(s=>{if(s.marker)s.marker.setStyle({fillColor:markerColor(s)});});}   // C42: withheld-coord stations have no marker
// ---- the survey FOCUS DIM --------------------------------------------------------
// "View on map" with a survey open frames that survey while the rest of the catalogue STAYS ON THE MAP,
// dimmed. The rejected alternative (what shipped before) filtered every other survey out of the layers, so
// the reader lost the national context that makes a survey's position meaningful, and the map stayed
// filtered after the drawer shut. This is OPACITY ONLY: no layer is added, removed, cleared or rebuilt, so
// there is nothing to reload when the focus lifts - clearSurveyDim just puts the opacities back.
// The focused survey, or null when nothing is focused. Read by applySurveyDim on every re-application.
let _dimFocusSurvey=null;
// Full-strength values are the ones buildMarkers paints with; the dimmed pair keeps a marker legible as a
// PRESENCE (you can still see the coverage) without competing with the focused survey.
const MARKER_FILL_OPACITY=.92,MARKER_DIM_FILL=.16,MARKER_DIM_STROKE=.3;
// PURE: the opacity pair a marker should carry given the focused survey. Leaflet-free and side-effect-free
// so the jsdom driver can pin the DECISION (which survey dims, and by how much) without a real map.
function dimStyleFor(surveyOfMarker,focus){
  return (!focus||surveyOfMarker===focus)
    ? {fillOpacity:MARKER_FILL_OPACITY,opacity:1}
    : {fillOpacity:MARKER_DIM_FILL,opacity:MARKER_DIM_STROKE};}
// Apply the current focus to every marker. Markers are canvas circleMarkers (preferCanvas), so setStyle
// carries their opacity; it passes ONLY the opacity keys, so it composes with recolor()/restyleForZoom()
// (colour and radius) instead of fighting them. Every map object is a station dot now, so this one loop is
// the whole dim: the per-survey panes existed because a badge was a divIcon setStyle could not reach.
function applySurveyDim(){
  ST.forEach(s=>{if(s.marker&&s.marker.setStyle)s.marker.setStyle(dimStyleFor(s.survey,_dimFocusSurvey));});}
function setSurveyDim(sv){_dimFocusSurvey=sv||null;applySurveyDim();}
function clearSurveyDim(){if(_dimFocusSurvey===null)return;_dimFocusSurvey=null;applySurveyDim();}
// The station hover tooltip is SLIMMED to station name + survey name ONLY -
// the TF completeness/smoothness diagnostic (Q) and the type/AusLAMP label were removed; the diagnostic
// stays in the click drawer. PURE + Leaflet-free so the jsdom driver tests the exact string shipped.
function tooltipText(s){return `${esc(s.id)} · ${esc(s.survey)}`;}
// Zoom-scaled marker geometry. PURE step functions (unit-tested, monotone non-decreasing in z),
// the SINGLE source for both the initial draw (buildMarkers) and the zoomend restyle below — markers read
// too large at national zoom but right when zoomed in, so they grow with zoom. Values are the starting
// points; the final table is recorded in the design doc.
// Every radius tier shifted ONE STEP SMALLER - each tier takes the next-smaller
// tier's old value (z5 4.5->3.5, z6 5->4.5, z>=7 6->5) and the smallest tier drops by the bottom step
// (z<=4 3.5->2.5, the 1.0 gap that separated it from the z5 tier). Still monotone non-decreasing in z.
// weightForZoom left as-is: a 1.0 stroke does not overwhelm a 2.5 fill.
// Change 6: CONTINUOUS dot radii, replacing the four-step ladder (2.5 / 3.5 / 4.5 / 5). A step ladder
// jumps: a zoom notch changed every dot's size by a visible 1px in one frame. A linear ramp in zoom is
// continuous across the range and monotone non-decreasing (the pinned property).
// UNIFORM SITE DOT SIZE: "the same size as the icons set for the AusLAMP sites". The
// per-type base split change 6 introduced (LP 2.0 / everything else 3.0) is REMOVED, because it cost the map
// a second visual variable encoding the same fact as colour. Data type is carried by COLOUR; size carries
// ZOOM. One variable, one meaning. The surviving base is the LP one, so BB/AMT/GDS come DOWN to the AusLAMP
// texture size rather than the fabric coming up.
// FLOOR and CEILING are both load-bearing and mean different things. The floor stops a dot going sub-pixel
// at far-out zooms, where an invisible dot reads as "no coverage here" - a false claim about the corpus.
// The ceiling stops close zooms growing discs that overlap into one blob and hide the site spacing, which
// at site zoom IS the information. Between them the ramp is 0.5px per zoom level.
const DOT_R_FLOOR=1.8, DOT_R_CEIL=6.5, DOT_R_SLOPE=0.5, DOT_R_Z0=4;
const DOT_R_BASE=2.0;          // at z4 (national): every site dot is ~2px, the AusLAMP LP texture size
// PURE, and a function of ZOOM ALONE. A caller that still passes a data type is harmless: the argument is
// not read, so a call site missed in the removal cannot quietly resurrect the per-type split. That
// inertness is itself pinned (tools/map_dots_test.js) rather than left as an accident of JS arity.
function radiusForZoom(z){
  return Math.min(DOT_R_CEIL,Math.max(DOT_R_FLOOR,DOT_R_BASE+DOT_R_SLOPE*((typeof z==="number"?z:DOT_R_Z0)-DOT_R_Z0)));}
function weightForZoom(z){return z<=4?1.0:1.5;}
// current map zoom as a finite number — the headless smoke/interaction stubs' map.getZoom() returns a
// Proxy (not a number), and even Number(proxy) throws ("cannot convert object to primitive"), so read it
// defensively and default to 4 (national) when it isn't already a finite number.
function curZoom(){const z=map.getZoom();return typeof z==="number"&&Number.isFinite(z)?z:4;}
// One radius for every marker on the map (the per-type split is gone), so this stamps the same zoom-derived
// size across the set. A zoom no longer re-routes: which stations are on the map is a FILTER answer, and
// dots do not collapse, so the badge era's reflowForZoom (restyle AND re-route) is gone with the rule that
// needed it.
function restyleForZoom(){const z=curZoom(),w=weightForZoom(z),r=radiusForZoom(z);
  ST.forEach(s=>{if(s.marker)s.marker.setStyle({radius:r,weight:w});});}
// The home frame buildMarkers fits to, remembered module-level so the setView("map") 60ms
// corrector can re-fit to it (null until data is in). This is the FIXED Australia frame
// (AU_HOME_BOUNDS), NOT the tight station extent — see buildMarkers. _fitWasDegenerate records whether that
// primary fit landed at a degenerate container size (see buildMarkers).
let HOME_BOUNDS=null,_fitWasDegenerate=false;
// PURE: a Leaflet map size is degenerate when it is missing or zero on either axis — the state that makes
// fitBounds compute against a 0x0/stale box and land at zoom 0 / the wrong centre. Leaflet-free so the
// jsdom driver pins it on synthetic sizes (the headless map's getSize() is a Proxy, so it reads degenerate).
function _mapSizeDegenerate(size){return !(size&&typeof size.x==="number"&&typeof size.y==="number"&&size.x>0&&size.y>0);}
// PURE: the corrector fires ONLY when the user has not taken control (never fight a deliberate view) AND the
// primary fit was degenerate (so a healthy fit — and any later programmatic fit, e.g. E6's collection
// framing — is left untouched). Split out so the no-fight-with-user decision is unit-testable.
function _mapRefitGate(st){return !!st&&!st.userInteracted&&!!st.fitDegenerate;}
function buildMarkers(){const z=curZoom(),w=weightForZoom(z);ST.forEach(s=>{
  if(!hasPosition(s))return;   // C42: a withheld-coordinate station has no position — no (0,0) phantom marker, no crash
  s.marker=L.circleMarker([s.lat,s.lon],{radius:radiusForZoom(z),weight:w,color:"#11182D",fillColor:markerColor(s),fillOpacity:.92});
  s.marker._survey=s.survey;   // UX8 (X3): the per-survey cluster facade buckets markers by this stamp
  // A marker click OPENS that station and must never ALSO read as a
  // background click that closes the drawer. L.Path defaults bubblingMouseEvents to TRUE, so without this
  // a marker click would fire the marker handler and then bubble to the map's click handler below - the
  // drawer would open and immediately close. DOM-target discrimination cannot do this job here: the map is
  // preferCanvas, so every marker and the background share ONE canvas element as e.target. Leaflet's own
  // layer hit-testing is the discriminator, and this flag is how it is expressed.
  s.marker.options.bubblingMouseEvents=false;
  s.marker.bindTooltip(tooltipText(s),{className:"qtip",direction:"top",offset:[0,-4]});   // O4: hover shows station + survey only
  s.marker.on("click",()=>openStation(s.i));});
  // Home frame once data is in: re-fit to the FIXED Australia box
  // (AU_HOME_BOUNDS), NOT the tight positioned-station extent. The tight extent dropped the view south and
  // clipped northern Australia; every station falls inside AU_HOME_BOUNDS, so this frames the continent AND
  // shows every dot. Guarded on there being at least one positioned station so an all-withheld catalogue
  // simply keeps the map-create fit (identical box) rather than re-running the size/timing repair for nothing.
  const pts=ST.filter(hasPosition).map(s=>[s.lat,s.lon]);
  if(pts.length){
    // Reclaim the true container size BEFORE fitting: on first load the map's cached size can be stale/0x0
    // (its container was unlaid-out at map-create), which makes fitBounds compute against a degenerate box
    // and land at zoom 0 / the wrong centre. invalidateSize repairs the cached size first; the fit is the
    // PRIMARY attempt (the 60ms timer is only the corrector). We record whether the size was still degenerate
    // at fit time so the corrector runs exactly when it is needed.
    map.invalidateSize({animate:false,pan:false});
    HOME_BOUNDS=AU_HOME_BOUNDS;
    _fitWasDegenerate=_mapSizeDegenerate(typeof map.getSize==="function"?map.getSize():null);
    map.fitBounds(HOME_BOUNDS);
    // The primary fit above runs BEFORE the flex layout has settled, so it fits a wrong-but-nonzero box.
    // Schedule an unconditional re-fit once layout settles — the real correction (see _mapDeferredHomeRefit).
    _scheduleDeferredHomeRefit();
  }
}
// One-shot corrector, called from the setView("map") 60ms timer AFTER invalidateSize has
// repaired the container size. Re-fits HOME_BOUNDS when the gate allows (user hasn't taken control and the
// primary fit was degenerate), then clears the flag so it runs at most once — a later return to the map, or
// a programmatic fit like E6, is never clobbered.
function _mapCorrectHomeFit(){
  if(!_mapRefitGate({userInteracted:_mapUserInteracted,fitDegenerate:_fitWasDegenerate}))return;
  if(HOME_BOUNDS)map.fitBounds(HOME_BOUNDS);
  _fitWasDegenerate=false;   // one-shot: the boot repair fires once, then stands down
}
// The ACTUAL off-centre-on-load fix. The one-shot corrector above only re-fits when the primary fit was
// DEGENERATE (0x0). But on a real page load the flex layout has not settled at fit time, so the container
// size is NONZERO-BUT-WRONG: the fit lands off-centre yet the degenerate gate never trips, and the bad fit
// STICKS. (Dispatching a window 'resize' — which triggers the app's unconditional invalidateSize + re-layout
// — snaps it to correct framing every time; this is that same correction, done once, automatically.) This
// deferred re-fit re-claims the true size and re-fits HOME_BOUNDS UNCONDITIONALLY — it is NOT gated on the
// degenerate flag (that gate is the bug). It is gated ONLY on the user not having taken control, so it never
// fights a deliberate pan/zoom. Because HOME_BOUNDS is remembered, the re-fit is idempotent when the fit was
// already correct and corrective when it was wrong.
function _mapDeferredHomeRefit(){
  map.invalidateSize({animate:false,pan:false});
  if(HOME_BOUNDS&&!_mapUserInteracted)map.fitBounds(HOME_BOUNDS);
}
// Schedule the deferred re-fit AFTER layout settles. Double requestAnimationFrame: a single rAF can still
// run before the browser has performed the final layout+paint, so we wait one more frame — by the second
// frame the container is at its settled flex size and the re-fit measures the RIGHT box. Falls back to a
// small timeout where rAF is absent (e.g. a non-visual headless host).
function _scheduleDeferredHomeRefit(){
  const raf=(typeof requestAnimationFrame==="function")?requestAnimationFrame:(cb=>setTimeout(cb,0));
  raf(()=>raf(()=>_mapDeferredHomeRefit()));
}
// Mark that the USER has taken control of the map, so the corrector never fights a deliberate pan/zoom.
// Gated on genuine user gestures ONLY: Leaflet's dragstart is user-initiated (a programmatic setView/
// fitBounds does NOT fire it), and the container wheel/touch listeners catch scroll- and pinch-zoom.
// movestart is deliberately NOT used — it also fires on the app's own programmatic moves.
let _mapUserInteracted=false;
function _mapMarkInteracted(){_mapUserInteracted=true;}
// A click on the MAP BACKGROUND closes an open drawer (survey OR station).
// Leaflet only routes a click here when its hit-testing found no interactive layer under the pointer:
// station markers set bubblingMouseEvents:false (buildMarkers) and a drawn shape is an L.Path target that
// consumes its own click, so "reached this handler" IS "landed on the background". PURE decision split
// out as _bgClickShouldClose so the jsdom driver can pin the RULE; note that the pointer/capture semantics
// themselves are Leaflet's and are only exercised in a real browser.
// An ARMED DRAW is excluded: mid-rectangle the click is placing a corner, not dismissing a panel.
function _bgClickShouldClose(drawerOpen,armedMode){return !!drawerOpen&&!armedMode;}
map.on("click",()=>{
  const d=document.getElementById("drawer");
  const open=!!(d&&d.classList&&d.classList.contains("open"));
  if(_bgClickShouldClose(open,armedDrawMode)&&typeof closeDrawer==="function")closeDrawer();
});
map.on("dragstart",_mapMarkInteracted);
const _mapCont=(typeof map.getContainer==="function")?map.getContainer():null;
if(_mapCont&&_mapCont.addEventListener){
  _mapCont.addEventListener("wheel",_mapMarkInteracted,{passive:true});
  _mapCont.addEventListener("touchstart",_mapMarkInteracted,{passive:true});
}
// Restyle every marker on each zoom step so radius/weight track the tier. preferCanvas is on
// (map creation) so a full restyle of ~1200 circleMarkers per step is acceptable; registered once here.
map.on("zoomend",restyleForZoom);

function hull(points){const pts=[...points].sort((a,b)=>a[0]-b[0]||a[1]-b[1]);if(pts.length<3)return pts;
  const cr=(o,a,b)=>(a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0]);const lo=[],hi=[];
  for(const p of pts){while(lo.length>=2&&cr(lo[lo.length-2],lo[lo.length-1],p)<=0)lo.pop();lo.push(p);}
  for(const p of pts.reverse()){while(hi.length>=2&&cr(hi[hi.length-2],hi[hi.length-1],p)<=0)hi.pop();hi.push(p);}
  return lo.slice(0,-1).concat(hi.slice(0,-1));}
const footprints=L.featureGroup();
function buildFootprints(){const by={};ST.forEach(s=>{if(!hasPosition(s))return;(by[s.survey]=by[s.survey]||[]).push([s.lon,s.lat]);});   // C42: skip withheld-coord stations (no hull vertex)
 Object.entries(by).forEach(([sv,pts],k)=>{const h=hull(pts);if(h.length<3)return;
   L.polygon(h.map(p=>[p[1],p[0]]),{color:Object.values(TYPE_COL)[k%4],weight:1.4,fillOpacity:.04,interactive:false}).bindTooltip(esc(sv)).addTo(footprints);});}
const userLayers={};
// Leaflet renders an attribution as HTML, and the source half of this line is FILE CONTENT (a fetched
// layers/*.geojson), so both halves are escaped. The guard is here while the path is DORMANT (the layer
// control below is not mounted, so the fetch never runs) precisely so re-enabling the control cannot
// re-open the sink by omission: a later change must not have to rediscover this.
// The guard on the control existing stays: a document that failed to load src/mapattrib.js draws a
// map with no control at all, and a layer added there must toast rather than throw.
function _layerAttribution(name,src){return esc(name)+": "+esc(src);}
function userLayer(name,file,color){const grp=L.featureGroup();grp._loaded=false;
  grp.on("add",async()=>{if(grp._loaded)return;
    try{const r=await fetch("layers/"+file);if(!r.ok)throw 0;const gj=await r.json();
      L.geoJSON(gj,{style:{color,weight:1.3,fillOpacity:.03},interactive:false}).addTo(grp);
      const src=gj.source||(gj.features&&gj.features[0]&&gj.features[0].properties&&gj.features[0].properties.source);
      if(src&&map.attributionControl)map.attributionControl.addAttribution(_layerAttribution(name,src));grp._loaded=true;}
    catch(e){toast(`Layer "${name}" not found; place GeoJSON at layers/${file} (ogr2ogr -f GeoJSON -t_srs EPSG:4326), with a top-level "source" field.`);}});
  userLayers[name]=grp;return grp;}
// Layer control hidden pending a decision - overlay definitions (footprints + the user
// GeoJSON layers) are kept and still constructed; the control is simply NOT added to the map.
L.control.layers(null,{"Survey footprints":footprints,
  "States / territories":userLayer("States","states.geojson","#8FA3B0"),
  "Geological provinces":userLayer("Geological provinces","provinces.geojson","#5BAE6A"),
  "Cratons":userLayer("Cratons","cratons.geojson","#D9A23B"),
  "Major crustal boundaries":userLayer("Crustal boundaries","crustal_boundaries.geojson","#A85CC4")},{collapsed:true});

// The selection-feedback toast copy. PURE (unit-tested) so the exact string -
// proper singular/plural, the word "stations" (never "sites"), and the shape word — is pinned. Any
// layerType other than "rectangle" reads as "polygon" (the only two draw modes enabled above).
function drawSelectionMsg(n,layerType){const shape=layerType==="rectangle"?"rectangle":"polygon";
  return n+" station"+(n===1?"":"s")+" selected within "+shape;}
// One active selection shape: a new box replaces the previous one rather than stacking. refresh()
// recomputes `selected` from the new shape, THEN we toast the fresh count and (D2) surface the exports by
// auto-switching the rail to Select & download. Named (not inline) so the jsdom driver can invoke it.
function onDrawCreated(e){e.layer.options.interactive=false;drawn.clearLayers();drawn.addLayer(e.layer);refresh();
  setArmedDraw(null);   // a completed draw disarms the mode — the panel button must not stay lit
  if(typeof toast==="function")toast(drawSelectionMsg(selected.size,e&&e.layerType));
  if(typeof setSidebarMode==="function")setSidebarMode("select");}
map.on(L.Draw.Event.CREATED,onDrawCreated);
map.on(L.Draw.Event.DELETED,()=>refresh());
