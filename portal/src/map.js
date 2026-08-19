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
// PURE: a badge's on-screen diameter in px, by station count. Shared by badgeIcon (which draws it) and the
// declutter pass (which has to know how big the thing it is separating actually is) - two readings of one
// number, so they cannot drift into a layout that separates badges by the wrong distance.
// OWNER (2026-08-19): "make the cluster circles 10% smaller, the text inside can stay the same size". The
// DISC and the LABEL are already separate authorities and that is what makes this a one-constant change:
// this function sizes the disc alone (it feeds iconSize, i.e. the divIcon box the CSS circle fills), while
// the label size is the font-size on .ausmt-badge.svbadge-* in index.html and is deliberately NOT touched.
// Scaling here therefore shrinks the circle and leaves the number exactly as legible as it was. The base
// ramp (34/42/52) is left verbatim beside the scale so the reduction stays readable as a reduction rather
// than being baked into three new magic numbers.
const BADGE_SIZE_SCALE=0.90;    // owner 2026-08-19: circles 10% smaller; the label keeps its own size
function badgeSizePx(n){return (n<10?34:n<100?42:52)*BADGE_SIZE_SCALE;}
function badgeIcon(survey,n){
  const cls=n<10?"svbadge-small":n<100?"svbadge-medium":"svbadge-large";
  const size=badgeSizePx(n);
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
//
// DECORATION PANES AND THE POINTER RULE (production regression, fixed 2026-08-19). A per-survey pane held
// ONLY divIcon badges while it was invented, so it held no <canvas> and nothing about it was in front of
// anything. Then the declutter lane added leader tails as L.polyline - an L.Path - and putting a Path in a
// pane makes Leaflet instantiate a CANVAS RENDERER inside that pane: a full-map-size <canvas> with the
// default pointer-events:auto, at THIS z-index. Station dots are circleMarkers drawn by the default canvas
// in overlayPane at z-index 400. 600 > 400, so twelve full-size survey canvases ended up covering the
// station canvas: every map click was captured by the topmost survey canvas, hit-tested against that
// survey's own (non-interactive) layers, matched nothing, and never reached the stations underneath. NO
// STATION WAS CLICKABLE ANYWHERE, and only the badges in the last-created pane still answered, because a
// badge is a DOM node while the panes below it were covered by the canvases above. MEASURED on the real
// corpus before the fix: 2 of 13 badges hit-reachable, 0 stations.
//
// THE INVARIANT THIS ENCODES: a decoration pane carries DOM badge icons and NON-INTERACTIVE paths, and
// nothing else. Anything that needs a pointer must live in a pane that is not stacked over the station
// layer. It is enforced at pane CREATION rather than by a stylesheet rule keyed on the pane class, because
// the pane name is generated here and a CSS selector written against it is one rename away from silently
// lapsing - and because this is the only place that knows a pane is a decoration pane at all.
//
// WHY pointer-events ON THE PANE DOES NOT COST THE BADGES THEIR CLICKS: Leaflet's own stylesheet carries
//   .leaflet-marker-icon.leaflet-interactive { pointer-events: auto; }
// and an interactive L.Marker's icon element gets both classes. A property set ON the element beats what it
// would inherit, so the badge icons keep their pointer events while everything that merely INHERITS from the
// pane - the canvas renderer above all - loses them. That is Leaflet's published marker contract, not a
// portal class name, so the exemption cannot drift with our markup. VERIFIED IN A REAL BROWSER against the
// live corpus: pane pointer-events none -> survey canvases computed pointer-events none, badge icons still
// computed auto, 13 of 13 badges hit-reachable, and a click on a station dot pixel opened that station.
const SURV_PANE_Z=600;          // 600 = Leaflet's markerPane: a badge is a marker and belongs at marker depth
// Every pane this module creates for decoration, by name. The registry is written by the ONE function that
// creates them, so it cannot fall out of step with the set of panes that actually exist, and the guard below
// reads it rather than pattern-matching a pane name.
const _decorationPanes=new Set();
// Create (once) a pane that may never swallow a pointer event. Registered BEFORE the Leaflet call so the
// headless harnesses - where createPane throws or returns a Proxy - still record the pane as a decoration
// pane and still run the guard.
function _makeDecorationPane(nm,z){
  _decorationPanes.add(nm);
  try{const p=map.createPane(nm);if(p&&p.style){p.style.zIndex=z;p.style.pointerEvents="none";}}catch(e){}
  return nm;}
const _survPaneName={};let _survPaneN=0;
function _survPaneFor(survey){
  if(!_survPaneName[survey]){
    const nm="ausmt-sv-"+(_survPaneN++);
    _survPaneName[survey]=nm;
    _makeDecorationPane(nm,SURV_PANE_Z);
  }
  return _survPaneName[survey];}
// The pane ELEMENT (or null under the headless stubs, where getPane returns a Proxy rather than a node).
function _survPane(survey){
  const nm=_survPaneName[survey];if(!nm)return null;
  let el=null;try{el=map.getPane(nm);}catch(e){return null;}
  return (el&&typeof el==="object"&&el.style&&typeof el.style==="object")?el:null;}
// ---- THE GUARD: nothing interactive may land in a decoration pane ------------------------------------
// The regression was invisible because it was a SIDE EFFECT: nobody added a canvas, somebody added a
// polyline, and Leaflet added the canvas. Any future edit that puts another Path in one of these panes
// brings the same full-map-size canvas back, so the invariant is checked at runtime rather than trusted.
// A decoration pane is pointer-dead by construction now, which means the failure mode of a future edit has
// TWO halves and this catches both: an interactive path there would be silently unclickable AND (before the
// pointer rule, or if it were ever relaxed) would blind the station layer beneath.
//
// PURE, so the decision is testable without Leaflet, a map or a DOM. Returns the operator-facing message,
// or "" when the layer is where it belongs.
function _decorationPaneViolation(paneName,isPath,interactive){
  if(!paneName||!_decorationPanes.has(paneName))return "";      // not our pane: not our rule
  if(!isPath)return "";                                         // a DOM marker icon is exactly what these panes are for
  if(interactive===false)return "";                             // non-interactive decoration is the other allowed content
  return "AusMT map invariant broken: an INTERACTIVE path was added to decoration pane "+paneName+
    ". That pane sits above the station layer and is pointer-dead by design, so the path cannot be clicked "+
    "and its canvas renderer would blind the stations underneath. Put interactive layers in a pane that is "+
    "not stacked over the stations, or set interactive:false.";}
// Every layer that reaches the map passes through Leaflet's layeradd, including layers added through a
// LayerGroup that is itself on the map (LayerGroup.addLayer delegates to Map.addLayer), so this one hook
// sees the badge layer's contents as well as anything added to the map directly.
const _paneGuardViolations=[];
// Path-ness is DUCK-TYPED rather than `instanceof L.Path` so this same code runs under the headless
// harnesses, which stub L entirely. Every L.Path (polyline, polygon, circle, circleMarker) carries both
// setStyle and redraw; L.Marker, L.Tooltip and L.LayerGroup carry neither, and L.GeoJSON has setStyle but
// no redraw - so the pair is what separates "will make a canvas renderer" from "will not".
function _paneGuardInspect(layer){
  const o=(layer&&layer.options)||{};
  const isPath=!!(layer&&typeof layer.setStyle==="function"&&typeof layer.redraw==="function");
  const msg=_decorationPaneViolation(o.pane,isPath,o.interactive);
  if(msg){_paneGuardViolations.push(msg);
    if(typeof console!=="undefined"&&console.error)console.error(msg);}
  return msg;}
map.on("layeradd",e=>_paneGuardInspect(e&&e.layer));
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
// ---- BADGE COLLISION DECLUTTER (owner, 2026-08-19, on the deployed map) -------------------------------
// The SA deposit surveys pile up: 312 / 20 / 216 / 53 / 83 / 78 / 36 badges stacked near Adelaide and the
// Curnamona, overlapping into an unreadable heap at national zoom. Badges are placed at CENTROIDS, and
// several small surveys genuinely share a neighbourhood, so the placement is not wrong - it is just
// unreadable. Standard cartographic label declutter applies: displace the labels, and DRAW THE LEADER.
//
// The leader tail is the whole ethical content of this feature. A badge that moves without one is a badge
// that LIES about where its survey is, and this portal does not make absence claims by omission anywhere
// else either. So: displaced badge -> thin line back to its true centroid, always, above the tail
// threshold. Below that threshold the displacement is sub-pixel-ish and there is nothing to disclose.
//
// TWO RULES SHAPE THE ALGORITHM, both stated rather than tuned:
//   1. COUNT-DESCENDING ANCHORING. Readers navigate by the big badges, so the big ones are the fixed
//      points and the small ones travel. In any colliding pair only the LOWER-count badge moves, which
//      makes "the largest badge in a set never moves" structural rather than emergent.
//   2. A TRAVEL CAP. Past BADGE_MAX_SHIFT_PX we ACCEPT the overlap. A badge 200px from its survey is a
//      worse lie than two badges touching, and a leader tail that long stops reading as an annotation.
// Determinism is a pinned property, not an accident: the ordering tie-break is the original index, the
// coincident-centroid fan-out angle is derived from rank, and nothing reads a clock or a random source.
const BADGE_GAP_PX=4;              // clear air between two badge rims once separated
const BADGE_MAX_SHIFT_PX=88;       // hard cap on how far a badge may travel from its true centroid
// Bounded relaxation. Resolving one pair can disturb an already-resolved one, so this iterates and stops
// early once a whole pass moves nothing. MEASURED on the owner reported SA pile (312/20/216/53/83/78/36):
// converged to machine precision within 8 passes, max travel 55.8px, largest badge anchored. A denser
// synthetic pile needed 16. 24 is that measurement plus headroom, and the cost is trivial - a handful of
// badges, so this is a few hundred distance checks on a zoom notch. A BOUNDED iteration cannot promise
// exactness on adversarial input, which is why the pins assert separation to a stated sub-pixel tolerance
// rather than pretending the fixed point is always reached.
const BADGE_DECLUTTER_PASSES=24;
const BADGE_TAIL_MIN_PX=2;         // under this, a displacement is invisible and draws no leader
// The tail is drawn in the portal's INK, not in the badge's own rim colour (rgba(232,237,241,.4)). The rim
// is a light-on-coloured-disc treatment: it reads because it sits on a saturated badge. A tail crosses the
// CARTO light_all basemap, where a near-white 1px line is simply invisible, so it takes the same ink every
// station dot is already outlined with. Subtle, and actually present.
const BADGE_TAIL_COLOR="#11182D",BADGE_TAIL_OPACITY=.45;
// ---- LEADERS ON TOP (owner, 2026-08-19) --------------------------------------------------------------
// Owner, on the SA pile-up (badges 100/20/63/56/216/58/83/53): "what about the arrow type pointers for the
// clusters? they should really be on top, not underneath some clusters." The complaint is exact. A leader
// used to be created into ITS OWN SURVEY'S pane, so its paint order against OTHER badges was decided by the
// order those surveys happened to get panes - which is the order the router first saw them, i.e. an
// accident. In a pile the low-pane leaders were painted under the high-pane badges and simply vanished, and
// which ones vanished changed with the filter state. That is the inconsistency.
//
// ONE dedicated tail pane, stacked ABOVE every survey pane, makes "a leader paints over every badge"
// structural instead of emergent: there is one pane for all leaders and it is higher than all of the panes
// that hold badges, so no pairing of two badges can order a leader underneath either of them. It is also a
// decoration pane, so its canvas - a Path pane always gets one, which is precisely the regression above -
// is pointer-dead and cannot blind the stations it now sits over.
//
// THE DIMMING TRADE, stated. A tail used to inherit the per-survey focus dim for free, because it rode its
// survey's pane and the dim is one opacity write on that pane element. Leaving the pane gives that up, so
// the dim is re-applied PER TAIL through setStyle (tailOpacityFor below), at the same product the pane
// composition produced: BADGE_TAIL_OPACITY * MARKER_DIM_FILL. The visual result is unchanged; what changed
// is that it is now computed rather than inherited, which is why applySurveyDim has to reach the tails
// explicitly and why the tails are held in a registry for it to walk. The alternative - one tail pane PER
// survey, keeping the free dim - would have reinstated exactly the "z-order by pane creation accident" the
// owner is complaining about, so it loses the point of the change.
const BADGE_TAIL_PANE="ausmt-badge-tails";
const BADGE_TAIL_PANE_Z=610;    // above every survey pane (600), below Leaflet's tooltipPane (650)
let _tailPaneMade=false;
function _badgeTailPane(){
  if(!_tailPaneMade){_tailPaneMade=true;_makeDecorationPane(BADGE_TAIL_PANE,BADGE_TAIL_PANE_Z);}
  return BADGE_TAIL_PANE;}
// PURE: the opacity a leader carries given the focused survey. Reproduces exactly what the pane-inherited
// dim used to compose to, so the focus view looks the same as it did before the tails left the survey panes.
function tailOpacityFor(surveyOfTail,focus){
  return (!focus||surveyOfTail===focus)?BADGE_TAIL_OPACITY:BADGE_TAIL_OPACITY*MARKER_DIM_FILL;}
// PURE: [{x,y,r,count}] (projected pixels) -> [{x,y,displaced}], index-aligned with the input. No Leaflet,
// no DOM, no clock, no randomness - the whole layout decision is unit-testable on plain objects, which is
// the same split shouldBadgeSurvey/partitionForDisplay already use. Never mutates its input: the caller's
// entries carry the TRUE centroid the leader tail is drawn back to, so corrupting them would corrupt the
// honesty mechanism itself.
function declutterBadges(entries){
  const src=(entries||[]).map((e,i)=>({i,
    x:(e&&isFinite(e.x))?+e.x:0, y:(e&&isFinite(e.y))?+e.y:0,
    r:(e&&isFinite(e.r)&&e.r>0)?+e.r:0, count:(e&&isFinite(e.count))?+e.count:0}));
  const pos=src.map(e=>({x:e.x,y:e.y}));
  // Count DESC; original index breaks ties so two equal-count badges resolve identically on every run.
  const order=src.slice().sort((a,b)=>(b.count-a.count)||(a.i-b.i));
  for(let pass=0;pass<BADGE_DECLUTTER_PASSES;pass++){
    let moved=false;
    for(let ai=0;ai<order.length;ai++)for(let bi=ai+1;bi<order.length;bi++){
      const a=order[ai],b=order[bi];                       // a outranks b, so only b may move
      const pa=pos[a.i],pb=pos[b.i],need=a.r+b.r+BADGE_GAP_PX;
      let dx=pb.x-pa.x,dy=pb.y-pa.y,d=Math.hypot(dx,dy);
      if(d>=need-1e-9)continue;                            // already clear
      if(d<1e-9){                                          // exactly coincident: no away-vector exists, so
        const th=2*Math.PI*bi/order.length;                // fan the lower-ranked badges by RANK, not chance
        dx=Math.cos(th);dy=Math.sin(th);d=1;}
      const tx=pa.x+dx/d*need,ty=pa.y+dy/d*need;
      // Clamp the TOTAL travel of b, measured from its own true centroid - not from wherever a previous
      // pass happened to leave it, which would let repeated nudges walk a badge past the cap.
      // (No apostrophes in this function: tools/map_badges_test.js extracts it by brace-matching and
      // treats a quote character as a string delimiter, comments included.)
      const ox=src[b.i].x,oy=src[b.i].y,vx=tx-ox,vy=ty-oy,td=Math.hypot(vx,vy);
      const k=(td>BADGE_MAX_SHIFT_PX)?BADGE_MAX_SHIFT_PX/td:1;
      const nx=ox+vx*k,ny=oy+vy*k;
      if(Math.abs(nx-pb.x)>1e-9||Math.abs(ny-pb.y)>1e-9){pb.x=nx;pb.y=ny;moved=true;}}
    if(!moved)break;}                                      // stable: nothing left to separate
  return src.map((e,i)=>({x:pos[i].x,y:pos[i].y,
    displaced:Math.hypot(pos[i].x-e.x,pos[i].y-e.y)>BADGE_TAIL_MIN_PX}));}
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
// The declutter's Leaflet-touching half: project every badge centroid to pixels at the CURRENT zoom, run
// the pure separation pass in that space, unproject the results. Pixels are the only space this decision
// can be made in - "overlapping" is a screen fact, and it changes with zoom, which is why this re-runs on
// zoomend through reflowForZoom -> routeVisibleToLayers like the badge rule itself.
// PROJECTION IS THE ONE THING THAT CAN FAIL: the headless harnesses stub Leaflet, so map.project returns a
// Proxy whose .x is not a number. Any non-finite projection degrades the WHOLE pass to "every badge at its
// true centroid, no tails" - the exact pre-declutter behaviour, never a half-decluttered layout.
function _badgeLayout(list){
  const plain=(list||[]).map(b=>({lat:b.lat,lon:b.lon,tail:null}));
  if(plain.length<2||!map||typeof map.project!=="function")return plain;
  const z=curZoom(),pts=[];
  for(const b of list){
    let p=null;
    try{p=map.project([b.lat,b.lon],z);}catch(e){p=null;}
    if(!p||!isFinite(p.x)||!isFinite(p.y))return plain;
    pts.push(p);}
  const laid=declutterBadges(list.map((b,i)=>({x:pts[i].x,y:pts[i].y,r:badgeSizePx(b.count)/2,count:b.count})));
  return list.map((b,i)=>{
    if(!laid[i].displaced)return {lat:b.lat,lon:b.lon,tail:null};
    let ll=null;
    try{ll=map.unproject([laid[i].x,laid[i].y],z);}catch(e){ll=null;}
    if(!ll||!isFinite(ll.lat)||!isFinite(ll.lng))return {lat:b.lat,lon:b.lon,tail:null};
    // The tail runs from where the badge NOW SITS back to where its survey ACTUALLY IS, and it now STARTS AT
    // THE BADGE RIM rather than at the badge centre. That trim exists because the leaders moved above every
    // badge (see BADGE_TAIL_PANE): a leader drawn from the centre would lay a dark spoke straight across its
    // own disc and its own number. Trimming by the badge radius keeps the drawn line to exactly the part
    // that was ever visible - the part OUTSIDE the disc - so the owner-visible change is "leaders stop
    // disappearing behind other badges", not "badges grew a spoke". The claim the leader makes is untouched:
    // it still ENDS at the true centroid. The trim is capped at d-1px so a badge sitting almost on top of
    // its own centroid still draws a line rather than one that overshoots and points backwards.
    const dx=pts[i].x-laid[i].x,dy=pts[i].y-laid[i].y,d=Math.hypot(dx,dy);
    let from=[ll.lat,ll.lng];
    if(d>1e-9){
      const cut=Math.min(badgeSizePx(b.count)/2,Math.max(0,d-1));
      let tl=null;
      try{tl=map.unproject([laid[i].x+dx/d*cut,laid[i].y+dy/d*cut],z);}catch(e){tl=null;}
      if(tl&&isFinite(tl.lat)&&isFinite(tl.lng))from=[tl.lat,tl.lng];}
    return {lat:ll.lat,lon:ll.lng,tail:[from,[b.lat,b.lon]]};});}
// The leaders currently on the map, with the survey each belongs to. Held because the focus dim can be
// applied WITHOUT a re-render (setSurveyDim from the drawer), and a tail no longer inherits it from a pane.
const _badgeTails=[];
function renderBadges(list){
  badgeLayer.clearLayers();
  _badgeTails.length=0;
  const layout=_badgeLayout(list||[]);
  (list||[]).forEach((b,i)=>{
    const at=layout[i];
    // The leader is created BEFORE its own marker (the layer walk in tools/map_badges_test.js pins that
    // pairing) but it no longer draws underneath it: leaders live in BADGE_TAIL_PANE, above every badge
    // pane, which is the owner change. interactive:false stays load-bearing for two reasons - a tail must
    // never intercept a click meant for a badge or for the map background (change 5 closes the drawer on
    // those), and an interactive path in a decoration pane is exactly what the pane guard refuses.
    if(at.tail){
      const t=L.polyline(at.tail,{pane:_badgeTailPane(),color:BADGE_TAIL_COLOR,
        weight:1,opacity:tailOpacityFor(b.survey,_dimFocusSurvey),interactive:false});
      _badgeTails.push({survey:b.survey,layer:t});
      badgeLayer.addLayer(t);}
    const m=L.marker([at.lat,at.lon],{pane:_survPaneFor(b.survey),icon:badgeIcon(b.survey,b.count),
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
    if(el&&el.style)el.style.opacity=(!_dimFocusSurvey||sv===_dimFocusSurvey)?"":String(MARKER_DIM_FILL);});
  // The LEADERS are the one thing the pane write no longer covers: they moved to BADGE_TAIL_PANE so they
  // paint above every badge, which also took them out of their survey's pane. tailOpacityFor reproduces the
  // exact product the pane composition used to give, so the focus view is unchanged; this loop is what makes
  // the dim reach them when the focus changes WITHOUT a re-render (drawer "View on map" is that path).
  _badgeTails.forEach(t=>{
    if(t&&t.layer&&typeof t.layer.setStyle==="function")
      t.layer.setStyle({opacity:tailOpacityFor(t.survey,_dimFocusSurvey)});});}
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
// Change 6: CONTINUOUS dot radii, replacing the four-step ladder (2.5 / 3.5 / 4.5 / 5). A step ladder
// jumps: a zoom notch changed every dot's size by a visible 1px in one frame. A linear ramp in zoom is
// continuous across the range and monotone non-decreasing (the pinned property).
// UNIFORM SITE DOT SIZE (owner, 2026-08-19): "the same size as the icons set for the AusLAMP sites". The
// per-type base split change 6 introduced (LP 2.0 / everything else 3.0) is REMOVED. It was solving a
// problem the badge change had already solved from the other end: the LP fabric only competed with surveys
// while a survey WAS a scatter of same-sized dots, and a compact survey is now one BADGE. The size split
// therefore bought nothing and cost the map a second visual variable encoding the same fact as colour.
// Data type is carried by COLOUR; size carries ZOOM. One variable, one meaning. The surviving base is the
// LP one, so BB/AMT/GDS come DOWN to the AusLAMP texture size rather than the fabric coming up; the default
// national zoom is unchanged (owner: "the original zoom level is good for the icon + survey clusters").
// FLOOR and CEILING are both load-bearing and mean different things. The floor stops a dot going sub-pixel
// at far-out zooms, where an invisible dot reads as "no coverage here" - a false claim about the corpus.
// The ceiling stops close zooms growing discs that overlap into one blob and hide the site spacing, which
// at site zoom IS the information. Between them the ramp is 0.5px per zoom level.
const DOT_R_FLOOR=1.8, DOT_R_CEIL=6.5, DOT_R_SLOPE=0.5, DOT_R_Z0=4;
const DOT_R_BASE=2.0;          // at z4 (national): every site dot is ~2px, the AusLAMP LP texture size
// PURE, and a function of ZOOM ALONE. A caller that still passes a data type is harmless: the argument is
// not read, so a call site missed in the removal cannot quietly resurrect the per-type split. That
// inertness is itself pinned (tools/map_badges_test.js) rather than left as an accident of JS arity.
function radiusForZoom(z){
  return Math.min(DOT_R_CEIL,Math.max(DOT_R_FLOOR,DOT_R_BASE+DOT_R_SLOPE*((typeof z==="number"?z:DOT_R_Z0)-DOT_R_Z0)));}
function weightForZoom(z){return z<=4?1.0:1.5;}
// current map zoom as a finite number — the headless smoke/interaction stubs' map.getZoom() returns a
// Proxy (not a number), and even Number(proxy) throws ("cannot convert object to primitive"), so read it
// defensively and default to 4 (national) when it isn't already a finite number.
function curZoom(){const z=map.getZoom();return typeof z==="number"&&Number.isFinite(z)?z:4;}
// One radius for every marker on the map (the per-type split is gone), so this stamps the same zoom-derived
// size across the set. Re-routing rides along, because the badge rule is zoom-dependent (a zoom notch alone
// can collapse a survey into a badge or dissolve one back into dots).
function restyleForZoom(){const z=curZoom(),w=weightForZoom(z),r=radiusForZoom(z);
  ST.forEach(s=>{if(s.marker)s.marker.setStyle({radius:r,weight:w});});}
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
  s.marker=L.circleMarker([s.lat,s.lon],{radius:radiusForZoom(z),weight:w,color:"#11182D",fillColor:markerColor(s),fillOpacity:.92});
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
