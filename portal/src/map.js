"use strict";
// Map + layers + markers. Data-dependent work (markers, footprints) is in buildMarkers()/
// buildFootprints(), called by main after ST is built. No direct call into drawer/filters at
// load time; the only cross-module reference is the marker click -> openStation (one-way).
// UX feedback round 1: default to a fixed Australia extent on load (was an arbitrary centre/zoom pair
// that didn't reliably frame the continent on typical viewport sizes). Bounds: [[south,west],[north,east]]
// chosen to cover the AU mainland + Tasmania with a small margin.
// Owner round 2 (2026-07-22): buildMarkers() USED to re-fit to the tight station-marker extent once data
// loaded — but because no station sits north of ~-22.5 lat, that fit dropped the view SOUTH (centre ~-33.6)
// and clipped northern Australia (the "off-centre after load" the owner saw). The owner LIKES this fixed
// Australia framing, so the home view is now ALWAYS this box (below): every station (lon 115.85..148.17,
// lat -43.44..-22.48) falls inside it, so it shows all dots AND frames the whole continent. Defined ONCE
// here as AU_HOME_BOUNDS and shared by the initial fit and buildMarkers()'s HOME_BOUNDS so the two frames
// cannot drift apart.
const AU_HOME_BOUNDS=L.latLngBounds([[-44.5,111.5],[-10,155]]);
const map=L.map("map",{preferCanvas:true}).fitBounds(AU_HOME_BOUNDS);
L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",{attribution:"&copy; OpenStreetMap &copy; CARTO",maxZoom:18}).addTo(map);
// Change 6 (owner, 2026-08-18): SURVEY BADGE icon. Proximity clustering is gone; a compact survey shows as
// ONE badge at its centroid carrying its station count. Visual language is inherited from the retired
// cluster bubbles (same sizes, same palette ramp) so the map does not change dialect, but the MEANING is
// different and the tooltip says so: a bubble was "some stations that happen to be near each other", a
// badge is "this survey". Escaped, because Leaflet sets divIcon html via innerHTML.
function badgeIcon(survey,n){
  const cls=n<10?"svbadge-small":n<100?"svbadge-medium":"svbadge-large";
  const size=n<10?34:n<100?42:52;
  const tip=(survey?survey+" · ":"")+n+" station"+(n===1?"":"s")+" · click to open";
  return L.divIcon({html:`<div title="${escAttr(tip)}"><span>${n}</span></div>`,className:"ausmt-badge "+cls,iconSize:L.point(size,size)});
}
// ---- change 6 (owner, 2026-08-18): MAP DECLUTTER - per-survey badges replace proximity clustering -----
// Leaflet.markercluster is GONE (script, stylesheet and vendored files with it). Proximity clustering
// answered the wrong question: it grouped by "what is near what on screen", so one survey could fragment
// into several bubbles, two surveys could not, and the count on a bubble named a screen accident rather
// than anything in the corpus. A badge names a SURVEY. It is placed at the survey's CENTROID and there is
// exactly one per survey by construction (the router keys a Map by survey name), so a survey can never
// show two badges at any zoom, at any filter state.
//
// THE THREE THRESHOLDS, and why these values:
//
// BADGE_MAX_ZOOM = 7 keeps the owner's earlier UX4-D3 ruling verbatim ("from REGIONAL zoom (z>=7) down
// every site shows individually"). That decision was about clustering but it is really about intent: a
// reader at regional zoom came to look at sites, so nothing may stand in front of them. Reusing the value
// means change 6 does not quietly re-litigate a settled call.
//
// BADGE_SPAN_PX = 64 is the footprint rule the owner asked for, expressed where it is actually decidable:
// not in km (a km threshold means a different thing at every zoom) but in SCREEN PIXELS, so "compact" means
// "too small to read as a shape here". 64px is two badge-widths (the badge itself is 34-52px). Below it a
// survey's dots are an overlapping smudge no larger than the badge that replaces them, so the badge is a
// strict gain: same footprint, adds a name and a count. Above it the dots start to carry shape - a line, an
// L, a grid - and shape is information the badge would destroy. The equivalent km/pixel statement: at
// national zoom (z4, ~2.2 km/px at -30 lat) the cutoff is ~140 km of extent; at z6 it is ~35 km.
//
// BADGE_MIN_STATIONS = 2 because a badge reading "1" is strictly worse than the dot it hides, and because a
// single-station survey has a ZERO-span footprint that would sit under BADGE_SPAN_PX at every zoom and so
// could never expand.
const BADGE_MAX_ZOOM=7;      // at/above this zoom: always dots (UX4-D3's "individual sites from regional zoom down")
const BADGE_SPAN_PX=64;      // a survey badges only while its whole extent spans fewer than this many screen px
const BADGE_MIN_STATIONS=2;  // never badge a lone station
// PER-SURVEY MAP PANES. Introduced by the survey-drawer lane (ruling 2) so the focus dim could reach the
// per-survey cluster bubbles; change 6 retired those bubbles but the pane machinery carries straight over to
// BADGES, which are divIcons for the same reason bubbles were. setStyle cannot dim a divIcon - but a pane is
// a plain DOM element, and one opacity write dims every badge a survey has. Panes are cheap (an empty
// absolutely positioned div), created once per survey, beside the default markerPane in the same z-order.
// Name is keyed by index, never by the survey label, because a pane name reaches a CSS class + querySelector
// and a survey label is custodian-supplied text (spaces, quotes, brackets are all real in the corpus).
const _survPaneName={};let _survPaneN=0;
function _survPaneFor(survey){
  if(!_survPaneName[survey]){
    const nm="ausmt-sv-"+(_survPaneN++);
    _survPaneName[survey]=nm;
    try{const p=map.createPane(nm);if(p&&p.style)p.style.zIndex=600;}catch(e){}   // 600 = Leaflet's markerPane
  }
  return _survPaneName[survey];}
// The pane ELEMENT (or null under the headless stubs, where getPane returns a Proxy rather than a node).
function _survPane(survey){
  const nm=_survPaneName[survey];if(!nm)return null;
  let el=null;try{el=map.getPane(nm);}catch(e){return null;}
  return (el&&typeof el==="object"&&el.style&&typeof el.style==="object")?el:null;}
// ---- change 6: the PURE badge core (no Leaflet, no DOM - the jsdom driver runs all of it directly) -----
// Web Mercator pixel span of a lat/lon box at a zoom, in the 256px-tile scheme Leaflet uses. Re-derived
// here rather than borrowed from map.project() because the DECISION must be testable without a live map:
//   x px = 256 * 2^z * dLon / 360        (longitude is linear in Mercator x)
//   y px = 256 * 2^z * dMercY / (2*pi)   (latitude is not: it goes through the Mercator y projection)
// Returns the LARGER axis, because a survey is only "too small to read" when BOTH axes are.
function mercatorY(lat){
  const phi=Math.max(-85.05112878,Math.min(85.05112878,lat))*Math.PI/180;
  return Math.log(Math.tan(Math.PI/4+phi/2));}
function mercatorPixelSpan(b,zoom){
  if(!b||!isFinite(b.w)||!isFinite(b.e)||!isFinite(b.so)||!isFinite(b.no))return 0;
  const scale=256*Math.pow(2,zoom);
  const xPx=Math.abs(b.e-b.w)/360*scale;
  const yPx=Math.abs(mercatorY(b.no)-mercatorY(b.so))/(2*Math.PI)*scale;
  return Math.max(xPx,yPx);}
// PURE: the extent of a station list as {w,e,so,no}. Deliberately NOT drawer.js's bbox(): that one serves
// the footprint SCATTER and returns a padded degenerate box for an empty list, which would silently feed a
// non-zero span into the badge rule. This one returns null for "no extent", so the caller must decide.
function _badgeBbox(ss){
  const p=(ss||[]).filter(hasPosition);
  if(!p.length)return null;
  const xs=p.map(s=>s.lon),ys=p.map(s=>s.lat);
  return {w:Math.min(...xs),e:Math.max(...xs),so:Math.min(...ys),no:Math.max(...ys)};}
// PURE: the arithmetic-mean position of a survey's POSITIONED stations. Centroid, never a spatial bin, so
// the badge sits inside its own survey rather than at the middle of whatever else happens to be nearby.
// (A survey straddling the antimeridian would need a circular mean; no AusMT survey does, and the corpus is
// Australian, so the plain mean is correct here and this comment is the record that it is a choice.)
function surveyCentroid(stations){
  const p=(stations||[]).filter(hasPosition);
  if(!p.length)return null;
  return {lat:p.reduce((a,s)=>a+s.lat,0)/p.length,lon:p.reduce((a,s)=>a+s.lon,0)/p.length};}
// PURE: does this survey badge at this zoom? Every clause is a stated rule, none is a heuristic:
//   - fewer than BADGE_MIN_STATIONS positioned stations -> no (a "1" badge hides more than it says);
//   - at or past BADGE_MAX_ZOOM -> no (the reader came for sites);
//   - an AusLAMP member -> NEVER (owner: the national LP fabric always reads as a grid; UX4-D2 kept);
//   - otherwise badge iff the footprint spans fewer than BADGE_SPAN_PX screen pixels.
function shouldBadgeSurvey(o){
  o=o||{};
  if(o.badgesEnabled===false)return false;                 // Select & export expands everything (see filters.js)
  if(!(o.count>=BADGE_MIN_STATIONS))return false;
  if(!(o.zoom<BADGE_MAX_ZOOM))return false;
  if(o.isAuslamp)return false;
  return mercatorPixelSpan(o.bbox,o.zoom)<BADGE_SPAN_PX;}
// PURE ROUTER: given the stations that should be on the map, decide what each survey renders as. Returns
// {dots:[station], badges:[{survey,slug,lat,lon,count}]}. The one-badge-per-survey invariant is structural:
// surveys are collected into a Map keyed by survey name and each key yields at most one badge entry.
// Side-effect-free, so the whole declutter decision is unit-testable on plain-object stubs.
function partitionForDisplay(stations,zoom,opts){
  opts=opts||{};
  const bySurvey=new Map();
  (stations||[]).forEach(s=>{
    const sv=(s&&typeof s.survey==="string")?s.survey:"";
    if(!bySurvey.has(sv))bySurvey.set(sv,[]);
    bySurvey.get(sv).push(s);});
  const dots=[],badges=[];
  bySurvey.forEach((ss,sv)=>{
    const positioned=ss.filter(hasPosition);
    const b=_badgeBbox(positioned);
    const badge=shouldBadgeSurvey({count:positioned.length,zoom,bbox:b,
      isAuslamp:isAuslampSurvey(ss[0]&&ss[0].slug,opts.auslampSet),badgesEnabled:opts.badgesEnabled});
    if(!badge){ss.forEach(s=>dots.push(s));return;}
    const c=surveyCentroid(positioned);
    if(!c){ss.forEach(s=>dots.push(s));return;}            // no position to badge at: degrade to dots
    badges.push({survey:sv,slug:(ss[0]&&ss[0].slug)||"",lat:c.lat,lon:c.lon,count:positioned.length});});
  return {dots,badges};}
// ---- change 6: the badge LAYER (the only Leaflet-touching half) ---------------------------------------
// One layer group holding the current badge markers. Each badge marker is created into ITS SURVEY'S PANE
// (_survPaneFor), which is what makes the change-2 focus dim apply to badges exactly as it does to dots:
// applySurveyDim writes one opacity onto the pane and the badge dims with the survey it belongs to.
const badgeLayer=L.layerGroup();
map.addLayer(badgeLayer);
// A badge click OPENS that survey's drawer, through the SAME openSurvey() the #/survey/<slug> route uses,
// so a badge click and a deep link land on identical state (and, since change 5, leave an identical URL).
// bubblingMouseEvents:false is set EXPLICITLY even though L.Marker already defaults to it: change 5's
// background-click handler closes the drawer, and a badge that let its click bubble would open the drawer
// and instantly close it. This is the guarantee, not the default, so it is written down.
function renderBadges(list){
  badgeLayer.clearLayers();
  (list||[]).forEach(b=>{
    const m=L.marker([b.lat,b.lon],{pane:_survPaneFor(b.survey),icon:badgeIcon(b.survey,b.count),
      bubblingMouseEvents:false,keyboard:false});
    m.on("click",()=>{if(typeof openSurvey==="function")openSurvey(b.survey);});
    badgeLayer.addLayer(m);});}
// Change 6: ONE dot container. There used to be two (a never-clustered plain layer for AusLAMP members and
// a markerClusterGroup for everything else) purely because clustering had to be withheld from the national
// LP grid. With clustering gone the split has no job: every station dot that is on the map is on the map
// the same way, and "which surveys are collapsed" is now the router's answer (partitionForDisplay), not a
// layer's. AusLAMP's never-collapse privilege survives intact inside shouldBadgeSurvey.
const dotLayer=L.layerGroup();
map.addLayer(dotLayer);
// UX4 (D1): AusLAMP membership is COLLECTION membership, not a data type — a station is AusLAMP iff its
// survey slug is a member of the collection with id `auslamp` in collections.json. AUSLAMP_SET (a Set of
// member SLUGS) is built once at boot from COLL/SMETA (buildAuslampSet, main.js); the pure predicate here
// takes it explicitly so it stays Leaflet-free and unit-testable (jsdom can't load Leaflet). Empty set
// (no collections.json / no auslamp collection) => graceful degrade: nothing is AusLAMP, everything
// clusters exactly as before the split.
function isAuslampSurvey(slug,auslampSet){return !!(slug&&auslampSet&&auslampSet.has(slug));}
// C42 coordinate access: a station whose custodian WITHHELD its coordinates carries null lat/lon in the
// served catalogue — the engine masks the VALUE (there is no separate policy field; withheld => null,
// generalised => a 0.1° cell rendered verbatim). hasPosition is the ONE pure predicate every map path
// uses to skip a position-less station: no marker, no footprint vertex, no fitBounds point, no spatial
// selection. It stays in ST (counted, findable by name); it simply is not ON the map. PURE + Leaflet-free
// so jsdom drives it directly (same idiom as isAuslampSurvey/partitionMarkers).
function hasPosition(s){return !!(s&&s.lat!=null&&s.lon!=null&&isFinite(s.lat)&&isFinite(s.lon));}
// Change 6: route the currently-visible stations into dots + badges and paint both containers. This is the
// ONE place layer membership is decided, called by refresh() (a filter changed) and by zoomend (the badge
// rule is zoom-dependent, so a zoom alone can change what is a badge and what is dots). It re-reads the
// live zoom and the live sidebar mode each pass, so no stale routing can survive either event.
// `visible` (filters.js) is already the filtered set; only POSITIONED stations reach a layer, because a
// coordinate-withheld station has no marker (C42) and no place on the map.
// Routing telemetry: how many routing passes have run, and what the last one decided. Not used by the app
// - it exists so a test can prove that a given ACTION (a mode switch, a zoom) caused a re-route and what
// that re-route produced. Under a stubbed Leaflet the layer contents are unreadable Proxies, so the
// router's own answer is the only honest observable for "the map was repainted, and with what".
let _routePasses=0,_lastRoute={dots:[],badges:[]};
function routeVisibleToLayers(){
  const stations=(typeof visible!=="undefined"?visible:[]).filter(hasPosition);
  const d=partitionForDisplay(stations,curZoom(),{
    auslampSet:(typeof AUSLAMP_SET!=="undefined")?AUSLAMP_SET:null,
    badgesEnabled:(typeof badgesEnabledForMode==="function")?badgesEnabledForMode():true});
  dotLayer.clearLayers();
  d.dots.forEach(s=>{if(s.marker)dotLayer.addLayer(s.marker);});
  renderBadges(d.badges);
  applySurveyDim();          // a re-render must not drop the change-2 focus dim
  _routePasses++;_lastRoute=d;
  return d;
}
const drawn=new L.FeatureGroup().addTo(map);
// UX6 Wave D (D3, #20): plain-language labels for the draw toolbar buttons. These override the generic
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
// UX6 Wave D (D3, #20): explicit aria-labels on the draw + zoom toolbar anchors, set AFTER the controls
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

// Discoverability (owner, 2026-07-21): the SELECTION panel gained "Draw rectangle"/"Draw polygon"
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

// UX4 Amendment A1 (owner, 2026-07-07): the D1 colour split was REMOVED — all LPMT renders the
// flagship teal (TYPE_COL.LPMT) in type mode regardless of AusLAMP membership, and every colour mode
// is membership-blind. The AusLAMP/legacy distinction is carried by the D2 clustering split, not by
// colour (and, since O4 2026-07-12, no longer by the hover tooltip either).
// Two-phase boot: s.q / s.dim come from sci.json (PHASE 2). Both sci-driven modes have a NEUTRAL GREY that
// MEANS "not evaluated" (qColor's null branch, DIM_COL's null key), so painting it over values the portal
// does not have would state a screening outcome it never received. Gate on hydrUsable, not on !hydrating:
// a FAILED sci.json leaves s.q/s.dim undefined exactly as an in-flight one does, and painting the whole map
// "not evaluated" off a 404 is a screening claim standing in for a load failure. Until the product is usable
// the marker keeps its data-type colour (a phase-1 fact). The two mode buttons are disabled across the same
// window (setSciControlsEnabled), so this guard is unreachable in normal use and exists to make the
// dishonest paint impossible rather than merely unlikely; SCI_READY recolours.
function markerColor(s){
  if(!hydrUsable("sci")&&(colorMode==="quality"||colorMode==="dim"))return TYPE_COL[s.type]||"#999";
  return colorMode==="quality"?qColor(s.q):colorMode==="dim"?(DIM_COL[s.dim]||"#5A6E7D"):(TYPE_COL[s.type]||"#999");}
function recolor(){ST.forEach(s=>{if(s.marker)s.marker.setStyle({fillColor:markerColor(s)});});}   // C42: withheld-coord stations have no marker
// ---- survey-drawer lane (ruling 2, Option A): the survey FOCUS DIM ------------------------------------
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
// Apply the current focus to every marker AND to each per-survey cluster group's pane. Markers are canvas
// circleMarkers (preferCanvas), so setStyle carries their opacity; a CLUSTER BUBBLE is a divIcon, which
// setStyle cannot reach, so each survey's cluster group renders into its OWN pane (makeSurveyCluster) and
// the pane element's opacity dims the bubble with its markers. setStyle here passes ONLY the opacity keys,
// so it composes with recolor()/restyleForZoom() (colour and radius) instead of fighting them.
function applySurveyDim(){
  ST.forEach(s=>{if(s.marker&&s.marker.setStyle)s.marker.setStyle(dimStyleFor(s.survey,_dimFocusSurvey));});
  // Change 6 (composition): the panes now carry BADGES rather than cluster bubbles, and a badge is a divIcon
  // for the same reason a bubble was, so the same one-write-per-pane dim covers it. Iterating the pane
  // REGISTRY (not a layer registry) is what makes that true: a survey has a pane as soon as it has ever had
  // a badge, so a badge can never render outside the surface the dim reaches.
  Object.keys(_survPaneName).forEach(sv=>{
    const el=_survPane(sv);
    if(el&&el.style)el.style.opacity=(!_dimFocusSurvey||sv===_dimFocusSurvey)?"":String(MARKER_DIM_FILL);});}
function setSurveyDim(sv){_dimFocusSurvey=sv||null;applySurveyDim();}
function clearSurveyDim(){if(_dimFocusSurvey===null)return;_dimFocusSurvey=null;applySurveyDim();}
// O4 (owner, 2026-07-12): the station hover tooltip is SLIMMED to station name + survey name ONLY —
// the TF completeness/smoothness diagnostic (Q) and the type/AusLAMP label were removed. The
// AusLAMP/legacy distinction stays in the D2 clustering split; the diagnostic stays in the click
// drawer. PURE + Leaflet-free so the jsdom driver tests the exact string shipped.
function tooltipText(s){return `${esc(s.id)} · ${esc(s.survey)}`;}
// UX4 (D4): zoom-scaled marker geometry. PURE step functions (unit-tested, monotone non-decreasing in z),
// the SINGLE source for both the initial draw (buildMarkers) and the zoomend restyle below — markers read
// too large at national zoom but right when zoomed in, so they grow with zoom. Cluster bubbles are
// untouched (count-driven). Values are UX4 starting points; the final table is recorded in the design doc.
// O5 (owner, 2026-07-12): every radius tier shifted ONE STEP SMALLER — each tier takes the next-smaller
// tier's old value (z5 4.5->3.5, z6 5->4.5, z>=7 6->5) and the smallest tier drops by the bottom step
// (z<=4 3.5->2.5, the 1.0 gap that separated it from the z5 tier). Still monotone non-decreasing in z.
// Cluster bubbles untouched (count-driven); weightForZoom left as-is — a 1.0 stroke does not overwhelm a 2.5 fill.
// Change 6: CONTINUOUS, TYPE-AWARE dot radii, replacing the four-step ladder (2.5 / 3.5 / 4.5 / 5).
// Two things the ladder could not do:
//   1. The LP fabric and a BB survey rendered at the SAME size, so at national zoom the AusLAMP grid - which
//      is background texture, the thing you read the country's coverage from - competed with the surveys a
//      reader is actually looking for. LPMT now starts a full pixel smaller and stays proportionally under.
//   2. A step ladder jumps: a zoom notch changed every dot's size by a visible 1px in one frame. A linear
//      ramp in zoom is continuous across the range and monotone non-decreasing (the pinned property).
// FLOOR and CEILING are both load-bearing and mean different things. The floor stops a dot going sub-pixel
// at far-out zooms, where an invisible dot reads as "no coverage here" - a false claim about the corpus.
// The ceiling stops close zooms growing discs that overlap into one blob and hide the site spacing, which
// at site zoom IS the information. Between them the ramp is 0.5px per zoom level.
const DOT_R_FLOOR=1.8, DOT_R_CEIL=6.5, DOT_R_SLOPE=0.5, DOT_R_Z0=4;
const DOT_R_BASE_LP=2.0, DOT_R_BASE_STD=3.0;   // at z4 (national): LP ~2px texture, BB/AMT/GDS ~3px above it
// PURE. `type` is optional: an unknown/absent type takes the standard (non-fabric) ramp, so a corpus that
// grows a new data type renders prominently rather than silently joining the background.
function radiusForZoom(z,type){
  const base=(type==="LPMT")?DOT_R_BASE_LP:DOT_R_BASE_STD;
  return Math.min(DOT_R_CEIL,Math.max(DOT_R_FLOOR,base+DOT_R_SLOPE*((typeof z==="number"?z:DOT_R_Z0)-DOT_R_Z0)));}
function weightForZoom(z){return z<=4?1.0:1.5;}
// current map zoom as a finite number — the headless smoke/interaction stubs' map.getZoom() returns a
// Proxy (not a number), and even Number(proxy) throws ("cannot convert object to primitive"), so read it
// defensively and default to 4 (national) when it isn't already a finite number.
function curZoom(){const z=map.getZoom();return typeof z==="number"&&Number.isFinite(z)?z:4;}
// Change 6: radius is per-TYPE now, so this restyles each marker against its own station's type rather
// than stamping one radius across the map. Re-routing rides along, because the badge rule is zoom-dependent
// (a zoom notch alone can collapse a survey into a badge or dissolve one back into dots).
function restyleForZoom(){const z=curZoom(),w=weightForZoom(z);
  ST.forEach(s=>{if(s.marker)s.marker.setStyle({radius:radiusForZoom(z,s.type),weight:w});});}
function reflowForZoom(){restyleForZoom();routeVisibleToLayers();}
// UX9 item 2: the home frame buildMarkers fits to, remembered module-level so the setView("map") 60ms
// corrector can re-fit to it (null until data is in). Owner round 2: this is now the FIXED Australia frame
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
  s.marker=L.circleMarker([s.lat,s.lon],{radius:radiusForZoom(z,s.type),weight:w,color:"#11182D",fillColor:markerColor(s),fillOpacity:.92});
  s.marker._survey=s.survey;   // UX8 (X3): the per-survey cluster facade buckets markers by this stamp
  // Survey-drawer lane (ruling 5): a marker click OPENS that station and must never ALSO read as a
  // background click that closes the drawer. L.Path defaults bubblingMouseEvents to TRUE, so without this
  // a marker click would fire the marker handler and then bubble to the map's click handler below - the
  // drawer would open and immediately close. DOM-target discrimination cannot do this job here: the map is
  // preferCanvas, so every marker and the background share ONE canvas element as e.target. Leaflet's own
  // layer hit-testing is the discriminator, and this flag is how it is expressed.
  s.marker.options.bubblingMouseEvents=false;
  s.marker.bindTooltip(tooltipText(s),{className:"qtip",direction:"top",offset:[0,-4]});   // O4: hover shows station + survey only
  s.marker.on("click",()=>openStation(s.i));});
  // Home frame once data is in. Owner round 2 (2026-07-22): re-fit to the FIXED Australia box
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
// UX9 item 2: one-shot corrector, called from the setView("map") 60ms timer AFTER invalidateSize has
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
// Survey-drawer lane (ruling 5): a click on the MAP BACKGROUND closes an open drawer (survey OR station).
// Leaflet only routes a click here when its hit-testing found no interactive layer under the pointer:
// station markers set bubblingMouseEvents:false (buildMarkers) and cluster bubbles / drawn shapes are
// L.Marker / L.Path targets that consume their own click, so "reached this handler" IS "landed on the
// background". PURE decision split out as _bgClickShouldClose so the jsdom driver can pin the RULE; note
// that the pointer/capture semantics themselves are Leaflet's and are only exercised in a real browser.
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
// UX4 (D4): restyle every marker on each zoom step so radius/weight track the tier. preferCanvas is on
// (map creation) so a full restyle of ~1200 circleMarkers per step is acceptable; registered once here.
map.on("zoomend",reflowForZoom);   // change 6: restyle AND re-route (badging is zoom-dependent)

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
function userLayer(name,file,color){const grp=L.featureGroup();grp._loaded=false;
  grp.on("add",async()=>{if(grp._loaded)return;
    try{const r=await fetch("layers/"+file);if(!r.ok)throw 0;const gj=await r.json();
      L.geoJSON(gj,{style:{color,weight:1.3,fillOpacity:.03},interactive:false}).addTo(grp);
      const src=gj.source||(gj.features&&gj.features[0]&&gj.features[0].properties&&gj.features[0].properties.source);
      if(src)map.attributionControl.addAttribution(name+": "+src);grp._loaded=true;}
    catch(e){toast(`Layer "${name}" not found; place GeoJSON at layers/${file} (ogr2ogr -f GeoJSON -t_srs EPSG:4326), with a top-level "source" field.`);}});
  userLayers[name]=grp;return grp;}
// layer control hidden pending owner revisit (2026-07-12) — overlay definitions (footprints + the user
// GeoJSON layers) are kept and still constructed; the control is simply NOT added to the map.
L.control.layers(null,{"Survey footprints":footprints,
  "States / territories":userLayer("States","states.geojson","#8FA3B0"),
  "Geological provinces":userLayer("Geological provinces","provinces.geojson","#5BAE6A"),
  "Cratons":userLayer("Cratons","cratons.geojson","#D9A23B"),
  "Major crustal boundaries":userLayer("Crustal boundaries","crustal_boundaries.geojson","#A85CC4")},{collapsed:true});

// UX6 Wave D (D3, #20): the selection-feedback toast copy. PURE (unit-tested) so the exact string —
// proper singular/plural, the word "stations" (never "sites"), and the shape word — is pinned. Any
// layerType other than "rectangle" reads as "polygon" (the only two draw modes enabled above).
function drawSelectionMsg(n,layerType){const shape=layerType==="rectangle"?"rectangle":"polygon";
  return n+" station"+(n===1?"":"s")+" selected within "+shape;}
// One active selection shape: a new box replaces the previous one rather than stacking. refresh()
// recomputes `selected` from the new shape, THEN we toast the fresh count and (D2) surface the exports by
// auto-switching the rail to Select & export. Named (not inline) so the jsdom driver can invoke it.
function onDrawCreated(e){e.layer.options.interactive=false;drawn.clearLayers();drawn.addLayer(e.layer);refresh();
  setArmedDraw(null);   // a completed draw disarms the mode — the panel button must not stay lit
  if(typeof toast==="function")toast(drawSelectionMsg(selected.size,e&&e.layerType));
  if(typeof setSidebarMode==="function")setSidebarMode("select");}
map.on(L.Draw.Event.CREATED,onDrawCreated);
map.on(L.Draw.Event.DELETED,()=>refresh());
