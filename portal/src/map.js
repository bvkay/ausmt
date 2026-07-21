"use strict";
// Map + layers + markers. Data-dependent work (markers, footprints) is in buildMarkers()/
// buildFootprints(), called by main after ST is built. No direct call into drawer/filters at
// load time; the only cross-module reference is the marker click -> openStation (one-way).
// UX feedback round 1: default to a fixed Australia extent on load (was an arbitrary centre/zoom pair
// that didn't reliably frame the continent on typical viewport sizes). Bounds: [[south,west],[north,east]]
// chosen to cover the AU mainland + Tasmania with a small margin. buildMarkers() below fits to the actual
// marker bounds once data loads (>=1 station), superseding this — this fitBounds is the empty/pre-data view.
const map=L.map("map",{preferCanvas:true}).fitBounds([[-44.5,111.5],[-10,155]]);
L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",{attribution:"&copy; OpenStreetMap &copy; CARTO",maxZoom:18}).addTo(map);
// Custom cluster icons (self-contained styling — no dependency on MarkerCluster.Default.css, whose
// absence rendered clusters as bare squares). Sized by child count; national-scale spiderfy is disabled in
// favour of zoom-to-bounds so clusters never explode into huge radial spiders. UX8 (X3): the bubble now
// carries the survey name in its native title tooltip (escaped — Leaflet sets the html via innerHTML).
function clusterIcon(c,survey){
  const n=c.getChildCount();
  const cls=n<10?"cluster-small":n<100?"cluster-medium":"cluster-large";
  const size=n<10?34:n<100?42:52;
  const tip=survey?survey+" · "+n+" stations":n+" stations";
  return L.divIcon({html:`<div title="${escAttr(tip)}"><span>${n}</span></div>`,className:"ausmt-cluster "+cls,iconSize:L.point(size,size)});
}
// UX4 (D3): clustering TIERS — owner extended C32's continental-only rule to ALSO group at STATE zoom.
// Sites aggregate into count bubbles at continental (z<=4) and state (z5-6) zoom; from REGIONAL zoom
// (z>=7) down every site shows individually. So the force-off floor moves 6 -> 7 (at/above z7 clustering
// is disabled). Named constant so the threshold is a single, pinned decision (a test asserts this value
// = 7) rather than a drive-by literal. (Supersedes C32's continental-ONLY 6: the owner now wants state
// zoom grouped too, so the grid/count-bubble view persists one zoom level deeper than before.)
const DISABLE_CLUSTERING_AT_ZOOM=7;   // grouped at continental (z<=4) AND state (z5-6); individual from regional zoom (z>=7) down
// UX8 (X3, owner ruling — supersedes pure-spatial clustering): stations cluster BY SURVEY. Each survey
// gets its OWN L.markerClusterGroup, so a cluster bubble is ALWAYS within one survey — two nearby surveys
// hold SEPARATE bubbles (never one merged spatial fragment) and a compact survey collapses to ONE bubble
// with its count. Only the grouping KEY changed (spatial -> survey); the =7 disable-clustering pin
// (individual sites from regional zoom down), the count-driven icon and the marker radii/tooltips/colour
// modes are unchanged. maxClusterRadius is generous (80): per-survey groups can never cross-merge, so a
// large radius simply collapses one survey to a single bubble at clustered zooms rather than fragmenting it.
function makeSurveyCluster(survey){
  return L.markerClusterGroup({
    maxClusterRadius:80, disableClusteringAtZoom:DISABLE_CLUSTERING_AT_ZOOM, spiderfyOnMaxZoom:false,
    zoomToBoundsOnClick:true, showCoverageOnHover:false, chunkedLoading:true,
    iconCreateFunction:c=>clusterIcon(c,survey)});
}
// PURE partition: bucket a marker list by the _survey stamped on each marker at build time (buildMarkers).
// Side-effect-free so the survey-grouping is unit-testable without Leaflet (jsdom can't load it); the
// facade below is the only Leaflet-touching caller. Two markers of DIFFERENT surveys => two buckets =>
// two separate cluster groups => two separate bubbles (the owner's ruling, falsifiably).
function groupMarkersBySurvey(markers){
  const by={};
  // guard the key TYPE (must be a real string) — under the headless Leaflet stubs a marker is a Proxy
  // whose ._survey is another Proxy, and using that as an object key throws; there, everything falls into
  // the "" bucket (harmless — jsdom renders no bubbles anyway; the grouping is proven on plain-object stubs).
  (markers||[]).forEach(mk=>{const sv=(mk&&typeof mk._survey==="string")?mk._survey:"";(by[sv]=by[sv]||[]).push(mk);});
  return by;
}
// Facade exposing the SAME clearLayers()/addLayers() interface refresh() (filters.js) already calls, so the
// per-survey split needs no change there: addLayers() routes each marker into its survey's cluster group
// (created and added to the map on first use), clearLayers() empties them all. It is intentionally NOT a
// Leaflet layer, so — unlike the old single group — it is not itself added to the map; each per-survey
// sub-group is.
const _survClusters={};   // survey name -> L.markerClusterGroup (lazily added to the map)
const cluster={
  clearLayers(){for(const sv in _survClusters)_survClusters[sv].clearLayers();},
  addLayers(markers){
    const by=groupMarkersBySurvey(markers);
    Object.keys(by).forEach(sv=>{
      let g=_survClusters[sv];
      if(!g){g=_survClusters[sv]=makeSurveyCluster(sv);map.addLayer(g);}
      g.addLayers(by[sv]);
    });
  }
};
// UX4 (D2): the never-cluster privilege moved from the LPMT *type* to the AUSLAMP *programme*. UX3 gave
// every type==="LPMT" station an unclustered plain layer so the AusLAMP national grid reads as a grid;
// but that also un-clustered legacy long-period surveys (e.g. olympic-dam-2004), whose 58 dots then
// masqueraded as national grid coverage — exactly the owner's confusion complaint. Now ONLY AusLAMP-
// collection members (isAuslampSurvey) go into the plain never-clustered layer; everything else — BBMT,
// AMT, GDS AND legacy non-AusLAMP LPMT — rides the markerClusterGroup, so at national zoom the map shows
// THE grid plus ordinary count bubbles. (GDS still clusters, pending a maintainer decision.) refresh()
// (filters.js) clears + repopulates both containers each pass; selection, tooltips, click handlers and
// colour modes all ride on s.marker and are identical across both layers. (Supersedes the UX3 type rule.)
const lpmtLayer=L.layerGroup();     // name kept for continuity; now the AusLAMP (not LPMT-type) unclustered layer
map.addLayer(lpmtLayer);
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
// PURE partition: split a station list into the plain unclustered layer (AusLAMP members) vs. the cluster
// group (everything else). Side-effect-free so it is unit-testable without Leaflet — refresh() below is the
// only Leaflet-touching caller. Reads the module-global AUSLAMP_SET (state.js), which boot fills.
// It splits ONLY on membership (position-agnostic); refresh() feeds it just the positioned stations
// (visible.filter(hasPosition)) so a withheld-coordinate station — which has no marker — never reaches
// addLayers. Keeping position OUT of this function keeps the split cleanly unit-testable with id-only stubs.
function partitionMarkers(stations){
  const unclustered=[],clustered=[];
  (stations||[]).forEach(s=>{(isAuslampSurvey(s&&s.slug,AUSLAMP_SET)?unclustered:clustered).push(s);});
  return {unclustered,clustered};
}
const drawn=new L.FeatureGroup().addTo(map);
// UX6 Wave D (D3, #20): plain-language labels for the draw toolbar buttons. These override the generic
// leaflet.draw defaults ("Draw a polygon" etc.) and MUST be set BEFORE the control is constructed — the
// control reads L.drawLocal at build time to set each button's title (its accessible name).
L.drawLocal.draw.toolbar.buttons.polygon="Draw polygon selection";
L.drawLocal.draw.toolbar.buttons.rectangle="Draw rectangle selection";
L.drawLocal.edit.toolbar.buttons.remove="Clear drawn shapes";
map.addControl(new L.Control.Draw({draw:{polyline:false,circle:false,circlemarker:false,marker:false,
  polygon:{shapeOptions:{color:"#EF7256",weight:2}},rectangle:{shapeOptions:{color:"#EF7256",weight:2}}},edit:{featureGroup:drawn,edit:false,remove:true}}));
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

// UX4 Amendment A1 (owner, 2026-07-07): the D1 colour split was REMOVED — all LPMT renders the
// flagship teal (TYPE_COL.LPMT) in type mode regardless of AusLAMP membership, and every colour mode
// is membership-blind. The AusLAMP/legacy distinction is carried by the D2 clustering split, not by
// colour (and, since O4 2026-07-12, no longer by the hover tooltip either).
function markerColor(s){return colorMode==="quality"?qColor(s.q):colorMode==="dim"?(DIM_COL[s.dim]||"#5A6E7D"):(TYPE_COL[s.type]||"#999");}
function recolor(){ST.forEach(s=>{if(s.marker)s.marker.setStyle({fillColor:markerColor(s)});});}   // C42: withheld-coord stations have no marker
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
function radiusForZoom(z){return z<=4?2.5:z===5?3.5:z===6?4.5:5;}
function weightForZoom(z){return z<=4?1.0:1.5;}
// current map zoom as a finite number — the headless smoke/interaction stubs' map.getZoom() returns a
// Proxy (not a number), and even Number(proxy) throws ("cannot convert object to primitive"), so read it
// defensively and default to 4 (national) when it isn't already a finite number.
function curZoom(){const z=map.getZoom();return typeof z==="number"&&Number.isFinite(z)?z:4;}
function restyleForZoom(){const z=curZoom(),r=radiusForZoom(z),w=weightForZoom(z);
  ST.forEach(s=>{if(s.marker)s.marker.setStyle({radius:r,weight:w});});}
// UX9 item 2: the positioned-station extent buildMarkers fits to, remembered module-level so the
// setView("map") 60ms corrector can re-fit to it (null until data with positions is in). _fitWasDegenerate
// records whether that primary fit landed at a degenerate container size (see buildMarkers).
let HOME_BOUNDS=null,_fitWasDegenerate=false;
// PURE: a Leaflet map size is degenerate when it is missing or zero on either axis — the state that makes
// fitBounds compute against a 0x0/stale box and land at zoom 0 / the wrong centre. Leaflet-free so the
// jsdom driver pins it on synthetic sizes (the headless map's getSize() is a Proxy, so it reads degenerate).
function _mapSizeDegenerate(size){return !(size&&typeof size.x==="number"&&typeof size.y==="number"&&size.x>0&&size.y>0);}
// PURE: the corrector fires ONLY when the user has not taken control (never fight a deliberate view) AND the
// primary fit was degenerate (so a healthy fit — and any later programmatic fit, e.g. E6's collection
// framing — is left untouched). Split out so the no-fight-with-user decision is unit-testable.
function _mapRefitGate(st){return !!st&&!st.userInteracted&&!!st.fitDegenerate;}
function buildMarkers(){const z=curZoom(),r=radiusForZoom(z),w=weightForZoom(z);ST.forEach(s=>{
  if(!hasPosition(s))return;   // C42: a withheld-coordinate station has no position — no (0,0) phantom marker, no crash
  s.marker=L.circleMarker([s.lat,s.lon],{radius:r,weight:w,color:"#11182D",fillColor:markerColor(s),fillOpacity:.92});
  s.marker._survey=s.survey;   // UX8 (X3): the per-survey cluster facade buckets markers by this stamp
  s.marker.bindTooltip(tooltipText(s),{className:"qtip",direction:"top",offset:[0,-4]});   // O4: hover shows station + survey only
  s.marker.on("click",()=>openStation(s.i));});
  // fit to the actual POSITIONED-station extent once data is in — supersedes the AU-bounds default set at
  // map creation above. C42: null-coord (withheld) stations are excluded so the bounds never go NaN.
  const pts=ST.filter(hasPosition).map(s=>[s.lat,s.lon]);
  if(pts.length){
    // Reclaim the true container size BEFORE fitting: on first load the map's cached size can be stale/0x0
    // (its container was unlaid-out at map-create), which makes fitBounds compute against a degenerate box
    // and land at zoom 0 / the wrong centre. invalidateSize repairs the cached size first; the fit is the
    // PRIMARY attempt (the 60ms timer is only the corrector). We record whether the size was still degenerate
    // at fit time so the corrector runs exactly when it is needed.
    map.invalidateSize({animate:false,pan:false});
    HOME_BOUNDS=pts;
    _fitWasDegenerate=_mapSizeDegenerate(typeof map.getSize==="function"?map.getSize():null);
    map.fitBounds(HOME_BOUNDS,{padding:[24,24]});
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
  if(HOME_BOUNDS)map.fitBounds(HOME_BOUNDS,{padding:[24,24]});
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
  if(HOME_BOUNDS&&!_mapUserInteracted)map.fitBounds(HOME_BOUNDS,{padding:[24,24]});
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
map.on("dragstart",_mapMarkInteracted);
const _mapCont=(typeof map.getContainer==="function")?map.getContainer():null;
if(_mapCont&&_mapCont.addEventListener){
  _mapCont.addEventListener("wheel",_mapMarkInteracted,{passive:true});
  _mapCont.addEventListener("touchstart",_mapMarkInteracted,{passive:true});
}
// UX4 (D4): restyle every marker on each zoom step so radius/weight track the tier. preferCanvas is on
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
function userLayer(name,file,color){const grp=L.featureGroup();grp._loaded=false;
  grp.on("add",async()=>{if(grp._loaded)return;
    try{const r=await fetch("layers/"+file);if(!r.ok)throw 0;const gj=await r.json();
      L.geoJSON(gj,{style:{color,weight:1.3,fillOpacity:.03},interactive:false}).addTo(grp);
      const src=gj.source||(gj.features&&gj.features[0]&&gj.features[0].properties&&gj.features[0].properties.source);
      if(src)map.attributionControl.addAttribution(name+": "+src);grp._loaded=true;}
    catch(e){toast(`Layer "${name}" not found — place GeoJSON at layers/${file} (ogr2ogr -f GeoJSON -t_srs EPSG:4326), with a top-level "source" field.`);}});
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
  if(typeof toast==="function")toast(drawSelectionMsg(selected.size,e&&e.layerType));
  if(typeof setSidebarMode==="function")setSidebarMode("select");}
map.on(L.Draw.Event.CREATED,onDrawCreated);
map.on(L.Draw.Event.DELETED,()=>refresh());
