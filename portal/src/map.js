"use strict";
// Map + layers + markers. Data-dependent work (markers, footprints) is in buildMarkers()/
// buildFootprints, called by main after ST is built. See docs: portal internals, map.js.
const AU_HOME_BOUNDS=L.latLngBounds([[-44.5,111.5],[-10,155]]);
// THE ATTRIBUTION CONTROL IS MOUNTED BELOW, not here. See docs: portal internals, map.js.
const map=L.map("map",{preferCanvas:true,attributionControl:false}).fitBounds(AU_HOME_BOUNDS);
// The basemap is config-driven. See docs: portal internals, map.js.
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
// Mounted after the basemap so the control collects the layer already on the map, which is the order
// Leaflet's own default control is created in. See docs: portal internals, map.js.
window.AusmtMapAttrib.mount(map,"Map data attribution");
// SITE LOCATIONS ONLY, at every zoom: no proximity clustering and no per-survey badge bubbles, so
// no badge, no leader tail, no decoration pane and no zoom threshold. See docs: portal internals,
// map.js.
const dotLayer=L.layerGroup();
map.addLayer(dotLayer);
// AusLAMP membership is COLLECTION membership, not a data type - a station is AusLAMP iff its survey slug
// is a member of the collection with id `auslamp` in collections.json. See docs: portal internals, map.js.
function isAuslampSurvey(slug,auslampSet){return !!(slug&&auslampSet&&auslampSet.has(slug));}
// Coordinate access: a station whose custodian WITHHELD its coordinates carries null lat/lon in the served
// catalogue - the engine masks the VALUE (there is no separate policy field; withheld => null, generalised
// => a 0.1° cell rendered verbatim). See docs: portal internals, map.js.
function hasPosition(s){return !!(s&&s.lat!=null&&s.lon!=null&&isFinite(s.lat)&&isFinite(s.lon));}
// Paint the currently-visible stations into the ONE dot container. Called by refresh (a filter changed).
// See docs: portal internals, map.js.
function routeVisibleToLayers(){
  const dots=(typeof visible!=="undefined"?visible:[]).filter(hasPosition);
  dotLayer.clearLayers();
  dots.forEach(s=>{if(s.marker)dotLayer.addLayer(s.marker);});
  applySurveyDim();          // a re-render must not drop the change-2 focus dim
  return {dots};
}
const drawn=new L.FeatureGroup().addTo(map);
// Plain-language labels for the draw toolbar buttons. These override the generic
// leaflet.draw defaults ("Draw a polygon" etc.) and MUST be set BEFORE the control is constructed - the
// control reads L.drawLocal at build time to set each button's title (its accessible name).
L.drawLocal.draw.toolbar.buttons.polygon="Draw polygon selection";
L.drawLocal.draw.toolbar.buttons.rectangle="Draw rectangle selection";
L.drawLocal.edit.toolbar.buttons.remove="Clear drawn shapes";
// Kept as a named reference (was an inline `map.addControl(new ...)`) so the SELECTION panel's
// Draw rectangle/polygon buttons can REUSE this control's own mode handlers - see armDraw below.
const drawControl=new L.Control.Draw({draw:{polyline:false,circle:false,circlemarker:false,marker:false,
  polygon:{shapeOptions:{color:"#EF7256",weight:2}},rectangle:{shapeOptions:{color:"#EF7256",weight:2}}},edit:{featureGroup:drawn,edit:false,remove:true}});
map.addControl(drawControl);
// Explicit aria-labels on the draw + zoom toolbar anchors, set AFTER the controls are on the map (their DOM
// exists by then). See docs: portal internals, map.js.
function labelToolbar(){
  const set=(sel,label)=>document.querySelectorAll(sel).forEach(a=>a.setAttribute("aria-label",label));
  set(".leaflet-draw-draw-polygon","Draw polygon selection");
  set(".leaflet-draw-draw-rectangle","Draw rectangle selection");
  set(".leaflet-draw-edit-remove","Clear drawn shapes");
  set(".leaflet-control-zoom-in","Zoom in");
  set(".leaflet-control-zoom-out","Zoom out");
}
labelToolbar();

// Discoverability: the SELECTION panel's "Draw rectangle"/"Draw polygon" buttons ARM the SAME
// leaflet.draw handlers the map's top-left toolbar icons arm, so the panel need not point a reader at
// a tool in the opposite corner. See docs: portal internals, map.js.
let armedDrawMode=null;                                   // null | "rectangle" | "polygon" - the shared armed state
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
// Arm a mode FROM THE PANEL by enabling the control's own handler - identical to clicking the toolbar icon
// (leaflet.draw binds each icon to _modes[type].handler.enable). See docs: portal internals, map.js.
function armDraw(mode){const h=drawModeHandler(mode);if(h&&typeof h.enable==="function")h.enable();setArmedDraw(mode);}
map.on(L.Draw.Event.DRAWSTART,e=>setArmedDraw(e&&e.layerType));   // icon OR button arms -> both reflect
map.on(L.Draw.Event.DRAWSTOP,()=>setArmedDraw(null));            // complete OR cancel -> both clear
const _drawRect=document.getElementById("drawRect"),_drawPoly=document.getElementById("drawPoly");
if(_drawRect)_drawRect.onclick=()=>armDraw("rectangle");
if(_drawPoly)_drawPoly.onclick=()=>armDraw("polygon");

// All LPMT renders the flagship teal (TYPE_COL.LPMT) in type mode whatever its AusLAMP membership:
// every colour mode is membership-blind. See docs: portal internals, map.js.
function markerColor(s){return TYPE_COL[s.type]||"#999";}
function recolor(){ST.forEach(s=>{if(s.marker)s.marker.setStyle({fillColor:markerColor(s)});});}   // withheld-coord stations have no marker
// ---- the survey FOCUS DIM -------------------------------------------------------- "View on map" with a
// survey open frames that survey while the rest of the catalogue STAYS ON THE MAP, dimmed. See docs: portal
// internals, map.js.
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
// carries their opacity; it passes ONLY the opacity keys, so it composes with recolor()/restyleForZoom
// (colour and radius) instead of fighting them. See docs: portal internals, map.js.
function applySurveyDim(){
  ST.forEach(s=>{if(s.marker&&s.marker.setStyle)s.marker.setStyle(dimStyleFor(s.survey,_dimFocusSurvey));});}
function setSurveyDim(sv){_dimFocusSurvey=sv||null;applySurveyDim();}
function clearSurveyDim(){if(_dimFocusSurvey===null)return;_dimFocusSurvey=null;applySurveyDim();}
// The station hover tooltip carries station name + survey name ONLY: the TF completeness/smoothness
// diagnostic (Q) and the type/AusLAMP label belong to the click drawer. PURE + Leaflet-free so the
// jsdom driver tests the exact string shipped.
function tooltipText(s){return `${esc(s.id)} · ${esc(s.survey)}`;}
// Zoom-scaled marker geometry. See docs: portal internals, map.js.
const DOT_R_FLOOR=1.8, DOT_R_CEIL=6.5, DOT_R_SLOPE=0.5, DOT_R_Z0=4;
const DOT_R_BASE=2.0;          // at z4 (national): every site dot is ~2px, the AusLAMP LP texture size
// PURE, and a function of ZOOM ALONE. A caller that still passes a data type is harmless: the argument is
// not read, so a call site missed in the removal cannot quietly resurrect the per-type split. See docs:
// portal internals, map.js.
function radiusForZoom(z){
  return Math.min(DOT_R_CEIL,Math.max(DOT_R_FLOOR,DOT_R_BASE+DOT_R_SLOPE*((typeof z==="number"?z:DOT_R_Z0)-DOT_R_Z0)));}
function weightForZoom(z){return z<=4?1.0:1.5;}
// current map zoom as a finite number - the headless smoke/interaction stubs' map.getZoom returns a
// Proxy (not a number), and even Number(proxy) throws ("cannot convert object to primitive"), so read it
// defensively and default to 4 (national) when it isn't already a finite number.
function curZoom(){const z=map.getZoom();return typeof z==="number"&&Number.isFinite(z)?z:4;}
// One radius for every marker on the map, with no per-type split, so this stamps the same
// zoom-derived size across the set. A zoom must not re-route: which stations are on the map is a FILTER answer, and
// dots do not collapse, so a restyle-AND-re-route pass has nothing left to re-route.
function restyleForZoom(){const z=curZoom(),w=weightForZoom(z),r=radiusForZoom(z);
  ST.forEach(s=>{if(s.marker)s.marker.setStyle({radius:r,weight:w});});}
// The home frame buildMarkers fits to, remembered module-level so the setView("map") 60ms corrector can
// re-fit to it (null until data is in). See docs: portal internals, map.js.
let HOME_BOUNDS=null,_fitWasDegenerate=false;
// PURE: a Leaflet map size is degenerate when it is missing or zero on either axis, which is what makes
// fitBounds compute against a 0x0 box and land at zoom 0. Leaflet-free so the jsdom driver pins it on
// synthetic sizes (the headless map's getSize is a Proxy, so it reads degenerate).
function _mapSizeDegenerate(size){return !(size&&typeof size.x==="number"&&typeof size.y==="number"&&size.x>0&&size.y>0);}
// PURE: the corrector fires ONLY when the user has not taken control (never fight a deliberate view) AND the
// primary fit was degenerate (so a healthy fit, and any later programmatic fit such as a collection
// framing - is left untouched). Split out so the no-fight-with-user decision is unit-testable.
function _mapRefitGate(st){return !!st&&!st.userInteracted&&!!st.fitDegenerate;}
function buildMarkers(){const z=curZoom(),w=weightForZoom(z);ST.forEach(s=>{
  if(!hasPosition(s))return;   // a withheld-coordinate station has no position - no (0,0) phantom marker, no crash
  s.marker=L.circleMarker([s.lat,s.lon],{radius:radiusForZoom(z),weight:w,color:"#11182D",fillColor:markerColor(s),fillOpacity:.92});
  s.marker._survey=s.survey;   // the per-survey cluster facade buckets markers by this stamp
  // A marker click OPENS that station and must never ALSO read as a background click that closes the
  // drawer. See docs: portal internals, map.js.
  s.marker.options.bubblingMouseEvents=false;
  s.marker.bindTooltip(tooltipText(s),{className:"qtip",direction:"top",offset:[0,-4]});   // hover shows station + survey only
  s.marker.on("click",()=>openStation(s.i));});
  // Home frame once data is in: re-fit to the FIXED Australia box (AU_HOME_BOUNDS), NOT the tight
  // positioned-station extent. See docs: portal internals, map.js.
  const pts=ST.filter(hasPosition).map(s=>[s.lat,s.lon]);
  if(pts.length){
    // Reclaim the true container size BEFORE fitting: on first load the map's cached size can be stale/0x0
    // (its container was unlaid-out at map-create), which makes fitBounds compute against a degenerate box
    // and land at zoom 0 / the wrong centre. See docs: portal internals, map.js.
    map.invalidateSize({animate:false,pan:false});
    HOME_BOUNDS=AU_HOME_BOUNDS;
    _fitWasDegenerate=_mapSizeDegenerate(typeof map.getSize==="function"?map.getSize():null);
    map.fitBounds(HOME_BOUNDS);
    // The primary fit above runs BEFORE the flex layout has settled, so it fits a wrong-but-nonzero box.
    // Schedule an unconditional re-fit once layout settles - the real correction (see _mapDeferredHomeRefit).
    _scheduleDeferredHomeRefit();
  }
}
// One-shot corrector, called from the setView("map") 60ms timer AFTER invalidateSize has repaired the
// container size. See docs: portal internals, map.js.
function _mapCorrectHomeFit(){
  if(!_mapRefitGate({userInteracted:_mapUserInteracted,fitDegenerate:_fitWasDegenerate}))return;
  if(HOME_BOUNDS)map.fitBounds(HOME_BOUNDS);
  _fitWasDegenerate=false;   // one-shot: the boot repair fires once, then stands down
}
// The ACTUAL off-centre-on-load fix. The one-shot corrector above only re-fits when the primary fit was
// DEGENERATE (0x0). See docs: portal internals, map.js.
function _mapDeferredHomeRefit(){
  map.invalidateSize({animate:false,pan:false});
  if(HOME_BOUNDS&&!_mapUserInteracted)map.fitBounds(HOME_BOUNDS);
}
// Schedule the deferred re-fit AFTER layout settles. See docs: portal internals, map.js.
function _scheduleDeferredHomeRefit(){
  const raf=(typeof requestAnimationFrame==="function")?requestAnimationFrame:(cb=>setTimeout(cb,0));
  raf(()=>raf(()=>_mapDeferredHomeRefit()));
}
// Mark that the USER has taken control of the map, so the corrector never fights a deliberate pan/zoom. See
// docs: portal internals, map.js.
let _mapUserInteracted=false;
function _mapMarkInteracted(){_mapUserInteracted=true;}
// A click on the MAP BACKGROUND closes an open drawer (survey OR station). See docs: portal internals,
// map.js.
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
function buildFootprints(){const by={};ST.forEach(s=>{if(!hasPosition(s))return;(by[s.survey]=by[s.survey]||[]).push([s.lon,s.lat]);});   // skip withheld-coord stations (no hull vertex)
 Object.entries(by).forEach(([sv,pts],k)=>{const h=hull(pts);if(h.length<3)return;
   L.polygon(h.map(p=>[p[1],p[0]]),{color:Object.values(TYPE_COL)[k%4],weight:1.4,fillOpacity:.04,interactive:false}).bindTooltip(esc(sv)).addTo(footprints);});}
const userLayers={};
// Leaflet renders an attribution as HTML, and the source half of this line is FILE CONTENT (a fetched
// layers/*.geojson), so both halves are escaped. See docs: portal internals, map.js.
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

// The selection-feedback toast copy. PURE (unit-tested) so the exact string - proper singular/plural, the
// word "stations" (never "sites"), and the shape word - is pinned. See docs: portal internals, map.js.
function drawSelectionMsg(n,layerType){const shape=layerType==="rectangle"?"rectangle":"polygon";
  return n+" station"+(n===1?"":"s")+" selected within "+shape;}
// One active selection shape: a new box replaces the previous one rather than stacking. refresh
// recomputes `selected` from the new shape, THEN we toast the fresh count and surface the exports by
// auto-switching the rail to Select & download. See docs: portal internals, map.js.
function onDrawCreated(e){e.layer.options.interactive=false;drawn.clearLayers();drawn.addLayer(e.layer);refresh();
  setArmedDraw(null);   // a completed draw disarms the mode - the panel button must not stay lit
  if(typeof toast==="function")toast(drawSelectionMsg(selected.size,e&&e.layerType));
  if(typeof setSidebarMode==="function")setSidebarMode("select");}
map.on(L.Draw.Event.CREATED,onDrawCreated);
map.on(L.Draw.Event.DELETED,()=>refresh());
