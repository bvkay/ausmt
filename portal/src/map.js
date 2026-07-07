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
// absence rendered clusters as bare squares). Sized/coloured by child count; national-scale spiderfy
// is disabled in favour of zoom-to-bounds so clusters never explode into huge radial spiders.
// UX feedback round 2: clustering loosened — radius 38->24 so markers only aggregate when they'd
// actually overlap (~two dot-diameters), which de-clusters ordinary survey spacing several zoom levels
// sooner. The force-off floor was 12 (UX-2 reasoning: keep dense deposit grids like Vulcan ~0.9 km /
// Kalkaroo ~200 m as count bubbles until legible); C32 SUPERSEDES that with the owner's continental-only
// rule below (DISABLE_CLUSTERING_AT_ZOOM=6), so from state/regional zoom down every site is individual
// even inside a dense grid — the maxClusterRadius:24 still prevents literally-overlapping dots from
// stacking. spiderfyOnMaxZoom stays off so near-coincident re-runs (e.g. WG-8/WG-8r) zoom-to-bounds
// rather than exploding into radial spiders.
function clusterIcon(c){
  const n=c.getChildCount();
  const cls=n<10?"cluster-small":n<100?"cluster-medium":"cluster-large";
  const size=n<10?34:n<100?42:52;
  return L.divIcon({html:`<div><span>${n}</span></div>`,className:"ausmt-cluster "+cls,iconSize:L.point(size,size)});
}
// UX4 (D3): clustering TIERS — owner extended C32's continental-only rule to ALSO group at STATE zoom.
// Sites aggregate into count bubbles at continental (z<=4) and state (z5-6) zoom; from REGIONAL zoom
// (z>=7) down every site shows individually. So the force-off floor moves 6 -> 7 (at/above z7 clustering
// is disabled). Named constant so the threshold is a single, pinned decision (a test asserts this value
// = 7) rather than a drive-by literal. (Supersedes C32's continental-ONLY 6: the owner now wants state
// zoom grouped too, so the grid/count-bubble view persists one zoom level deeper than before.)
const DISABLE_CLUSTERING_AT_ZOOM=7;   // grouped at continental (z<=4) AND state (z5-6); individual from regional zoom (z>=7) down
const cluster=L.markerClusterGroup({
  maxClusterRadius:24, disableClusteringAtZoom:DISABLE_CLUSTERING_AT_ZOOM, spiderfyOnMaxZoom:false,
  zoomToBoundsOnClick:true, showCoverageOnHover:false, chunkedLoading:true,
  iconCreateFunction:clusterIcon});
map.addLayer(cluster);
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
// PURE partition: split a station list into the plain unclustered layer (AusLAMP members) vs. the cluster
// group (everything else). Side-effect-free so it is unit-testable without Leaflet — refresh() below is the
// only Leaflet-touching caller. Reads the module-global AUSLAMP_SET (state.js), which boot fills.
function partitionMarkers(stations){
  const unclustered=[],clustered=[];
  (stations||[]).forEach(s=>{(isAuslampSurvey(s&&s.slug,AUSLAMP_SET)?unclustered:clustered).push(s);});
  return {unclustered,clustered};
}
const drawn=new L.FeatureGroup().addTo(map);
map.addControl(new L.Control.Draw({draw:{polyline:false,circle:false,circlemarker:false,marker:false,
  polygon:{shapeOptions:{color:"#E0782F",weight:2}},rectangle:{shapeOptions:{color:"#E0782F",weight:2}}},edit:{featureGroup:drawn,edit:false,remove:true}}));

// UX4 Amendment A1 (owner, 2026-07-07): the D1 colour split was REMOVED — all LPMT renders the
// flagship teal (TYPE_COL.LPMT) in type mode regardless of AusLAMP membership, and every colour mode
// is membership-blind. The AusLAMP/legacy distinction is carried by the TOOLTIP type-label swap
// (tooltipText below) and the D2 clustering split, not by colour.
function markerColor(s){return colorMode==="quality"?qColor(s.q):colorMode==="dim"?(DIM_COL[s.dim]||"#5A6E7D"):(TYPE_COL[s.type]||"#999");}
function recolor(){ST.forEach(s=>s.marker.setStyle({fillColor:markerColor(s)}));}
// UX4 Amendment A1: the tooltip's TYPE SLOT shows "AusLAMP" INSTEAD OF the raw LPMT type label for
// collection members (a swap, not an append — supersedes the D1 append) — the sole AusLAMP/legacy
// visual distinction on hover. Non-members keep their type label unchanged. PURE + Leaflet-free so
// the jsdom driver tests the exact string shipped (same pattern as partitionMarkers).
function tooltipText(s){return `${esc(s.id)} · ${isAuslampSurvey(s.slug,AUSLAMP_SET)?"AusLAMP":esc(s.type)} · Q ${s.q??"–"}`;}
// UX4 (D4): zoom-scaled marker geometry. PURE step functions (unit-tested, monotone non-decreasing in z),
// the SINGLE source for both the initial draw (buildMarkers) and the zoomend restyle below — markers read
// too large at national zoom but right when zoomed in, so they grow with zoom. Cluster bubbles are
// untouched (count-driven). Values are UX4 starting points; the final table is recorded in the design doc.
function radiusForZoom(z){return z<=4?3.5:z===5?4.5:z===6?5:6;}
function weightForZoom(z){return z<=4?1.0:1.5;}
// current map zoom as a finite number — the headless smoke/interaction stubs' map.getZoom() returns a
// Proxy (not a number), and even Number(proxy) throws ("cannot convert object to primitive"), so read it
// defensively and default to 4 (national) when it isn't already a finite number.
function curZoom(){const z=map.getZoom();return typeof z==="number"&&Number.isFinite(z)?z:4;}
function restyleForZoom(){const z=curZoom(),r=radiusForZoom(z),w=weightForZoom(z);
  ST.forEach(s=>{if(s.marker)s.marker.setStyle({radius:r,weight:w});});}
function buildMarkers(){const z=curZoom(),r=radiusForZoom(z),w=weightForZoom(z);ST.forEach(s=>{
  s.marker=L.circleMarker([s.lat,s.lon],{radius:r,weight:w,color:"#13202B",fillColor:markerColor(s),fillOpacity:.92});
  s.marker.bindTooltip(tooltipText(s),{className:"qtip",direction:"top",offset:[0,-4]});   // A1: type-label swap for AusLAMP members
  s.marker.on("click",()=>openStation(s.i));});
  // fit to the actual station extent once data is in (>=1 station) — supersedes the AU-bounds default
  // set at map creation above, which only serves the pre-data/empty state.
  if(ST.length>=1)map.fitBounds(ST.map(s=>[s.lat,s.lon]));}
// UX4 (D4): restyle every marker on each zoom step so radius/weight track the tier. preferCanvas is on
// (map creation) so a full restyle of ~1200 circleMarkers per step is acceptable; registered once here.
map.on("zoomend",restyleForZoom);

function hull(points){const pts=[...points].sort((a,b)=>a[0]-b[0]||a[1]-b[1]);if(pts.length<3)return pts;
  const cr=(o,a,b)=>(a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0]);const lo=[],hi=[];
  for(const p of pts){while(lo.length>=2&&cr(lo[lo.length-2],lo[lo.length-1],p)<=0)lo.pop();lo.push(p);}
  for(const p of pts.reverse()){while(hi.length>=2&&cr(hi[hi.length-2],hi[hi.length-1],p)<=0)hi.pop();hi.push(p);}
  return lo.slice(0,-1).concat(hi.slice(0,-1));}
const footprints=L.featureGroup();
function buildFootprints(){const by={};ST.forEach(s=>(by[s.survey]=by[s.survey]||[]).push([s.lon,s.lat]));
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
L.control.layers(null,{"Survey footprints":footprints,
  "States / territories":userLayer("States","states.geojson","#8FA3B0"),
  "Geological provinces":userLayer("Geological provinces","provinces.geojson","#5BAE6A"),
  "Cratons":userLayer("Cratons","cratons.geojson","#D9A23B"),
  "Major crustal boundaries":userLayer("Crustal boundaries","crustal_boundaries.geojson","#A85CC4")},{collapsed:true}).addTo(map);

map.on(L.Draw.Event.CREATED,e=>{e.layer.options.interactive=false;drawn.clearLayers();drawn.addLayer(e.layer);refresh();});  // one active selection shape: a new box replaces the previous one rather than stacking
map.on(L.Draw.Event.DELETED,()=>refresh());
