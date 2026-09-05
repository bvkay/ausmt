"use strict";
// Coordinator: builds derived state, owns view switching + routing + the resizer, and runs the
// data-dependent init in order. Modules don't call each other at load time; main sequences them.
function buildState(){
  ST=CAT.map((r,i)=>({i,id:r[C.id],survey:r[C.survey],lat:r[C.lat],lon:r[C.lon],pmin:r[C.period_min_s],pmax:r[C.period_max_s],nper:r[C.n_periods],comps:r[C.comps],type:r[C.type],region:r[C.region],file:r[C.file],fixed:r[C.coord_flag],
    ediAvail:r[C.edi_available]===1, sha:r[C.sha256]||null,
    // Original pre-sanitisation station/site name (engine emits it only when it differs from id);
    // null for the common clean-id case, so the drawer's Station summary shows the row only when it differs.
    site_name:r[C.site_name]||null,
    org:(SMETA[r[C.survey]]||{}).org||"Unknown",country:(SMETA[r[C.survey]]||{}).country||"Australia",
    slug:(SMETA[r[C.survey]]||{}).slug||null,
    // The survey's declared year range (ints|null), read straight off SMETA (engine-parsed -
    // the portal never re-parses date strings). null when the survey.yaml declares no dates.
    yearStart:(SMETA[r[C.survey]]||{}).year_start??null,yearEnd:(SMETA[r[C.survey]]||{}).year_end??null,
    // Two-phase boot: sci.json is a PHASE 2 product, so at first paint these are undefined and are folded
    // on again by applySciToStations() when SCI_READY settles. sciRow() is the shared not-yet-loaded-safe
    // deref, so this is the same expression at both call sites (one derivation, two moments).
    q:sciRow(i)[SC.q], dim:sciRow(i)[SC.dim],
    // Use the authoritative ausmt_id the engine wrote into catalogue column r[C.ausmt_id]
    // (au.<survey-slug>.<station>). Fall back to the legacy survey-name slugification only for
    // older data that predates r[C.ausmt_id], so the id shown/exported matches the product + MTCAT.
    ausmt_id:r[C.ausmt_id]||((CC[(SMETA[r[C.survey]]||{}).country]||"au").toLowerCase()+"."+r[C.survey].toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/-$/,"")+"."+r[C.id])}));
  // Fold the boot-loaded coordinate policy onto each station (generalised | withheld), keyed by the
  // authoritative ausmt_id just derived; null when exact/unmarked. See docs: portal internals, main.js.
  const _cp=(typeof COORD_POLICY!=="undefined"&&COORD_POLICY)||{};
  ST.forEach(s=>{s.coordPolicy=_cp[s.ausmt_id]||null;});
  surveys=[...new Set(ST.map(s=>s.survey))].sort();
  // slug -> survey label, for the #/survey/<slug> route. The front door emits 301 from the
  // published /surveys/<slug> path URLs into this route. See docs: portal internals, main.js.
  SLUG_TO_SURVEY={};
  surveys.forEach(sv=>{const slug=(SMETA[sv]||{}).slug;if(slug)SLUG_TO_SURVEY[slug]=sv;});
  ST.forEach(s=>{if(!SLUG_TO_SURVEY[s.slug||""]&&s.ausmt_id){
    const rest=s.ausmt_id.replace(/^[a-z]+\./,"");                 // strip "au."/country prefix
    const derived=rest.endsWith("."+s.id)?rest.slice(0,-(s.id.length+1)):null;
    if(derived)SLUG_TO_SURVEY[derived]=s.survey;}});
  buildAuslampSet();
  applyYearRangeHints();
}
// Two-phase boot: the ONLY two station fields that come from sci.json. buildState() runs at first paint,
// before sci.json has landed, so it derives them from an empty row; this re-folds them from the real data
// the moment SCI_READY settles. See docs: portal internals, main.js.
function applySciToStations(){
  if(!Array.isArray(ST))return;
  ST.forEach(s=>{const sc=sciRow(s.i);s.q=sc[SC.q];s.dim=sc[SC.dim];});
}
// Build AUSLAMP_SET (survey SLUGS in the `auslamp` collection) from the boot data. See docs: portal
// internals, main.js.
function buildAuslampSet(){
  AUSLAMP_SET=new Set();
  const c=(typeof COLL!=="undefined"&&COLL)?COLL.auslamp:null;
  if(!c||!Array.isArray(c.surveys))return;                         // no auslamp collection -> nothing is AusLAMP
  c.surveys.forEach(label=>{const slug=(SMETA&&SMETA[label]||{}).slug;if(slug)AUSLAMP_SET.add(slug);});
}
// Corpus-wide year hints on the two Year range inputs: placeholder + min/max
// attrs from the min year_start / max year_end across ALL of SMETA (not just ST, so an undated-in-CAT
// survey with declared dates still counts). See docs: portal internals, main.js.
function applyYearRangeHints(){
  let lo=null,hi=null;
  Object.keys(SMETA||{}).forEach(sv=>{const m=SMETA[sv]||{};
    if(typeof m.year_start==="number")lo=(lo==null?m.year_start:Math.min(lo,m.year_start));
    if(typeof m.year_end==="number")hi=(hi==null?m.year_end:Math.max(hi,m.year_end));});
  const fromEl=document.getElementById("yearFrom"),toEl=document.getElementById("yearTo"),head=document.getElementById("yearRangeHead");
  const dated=lo!=null&&hi!=null;
  if(fromEl){fromEl.placeholder=dated?String(lo):"from";if(dated)fromEl.min=lo,fromEl.max=hi;}
  if(toEl){toEl.placeholder=dated?String(hi):"to";if(dated)toEl.min=lo,toEl.max=hi;}
  if(head)head.textContent="Year range"+(dated?` (${fmtRange(lo,hi)})`:"");   // suffix hidden when no survey is dated
}
// ---- "Recently added" -------------------------------------------------------------------------
// LOCKSTEP RULE, kept identical to the engine's _survey_latest_date in engine/extract/build_portal.py.
// See docs: portal internals, main.js.
function surveyLatestDate(m){
  const cands=[];
  const rn=(m&&m.release_notes);
  if(Array.isArray(rn))rn.forEach(e=>{if(e&&e.date)cands.push(String(e.date).slice(0,10));});
  const dd=m&&m.attribution&&m.attribution.declared_date;   // schema 1.1 attribution.declared_date
  if(dd)cands.push(String(dd).slice(0,10));
  let best=null;
  cands.forEach(d=>{if(/^\d{4}-\d{2}-\d{2}$/.test(d)&&(!best||d>best))best=d;});
  if(best)return best;
  const yr=(m&&(m.year_end||m.year_start))||null;
  return yr?`${yr}-12-31`:null;
}
// The strip's reference "today": the build timestamp (BUILDID.generated) so the strip is
// DETERMINISTIC per build (two loads of the same data show the same three items); falls back to the
// client clock only when no build.json resolved (older/empty builds, browser context only).
function recentBuildDay(){
  const g=(typeof BUILDID!=="undefined"&&BUILDID&&BUILDID.generated)?String(BUILDID.generated).slice(0,10):"";
  if(/^\d{4}-\d{2}-\d{2}$/.test(g))return g;
  return new Date().toISOString().slice(0,10);
}
// The window's lower bound: 30 days before the build day, as YYYY-MM-DD. UTC arithmetic so the
// boundary never drifts by a local timezone offset.
function recentWindowStart(buildDay){
  const d=new Date(buildDay+"T00:00:00Z");d.setUTCDate(d.getUTCDate()-30);
  return d.toISOString().slice(0,10);
}
// The strip surface: dated surveys whose latest date falls within the 30 days ENDING at the build
// day, newest first, capped at 3. Window + cap are the strip's own display rules (see the lockstep
// note above); the feed is unaffected.
function recentlyAdded(limit){
  const build=recentBuildDay(),start=recentWindowStart(build);
  const out=surveys.map(sv=>{const m=SMETA[sv]||{};return {sv,slug:m.slug||null,date:surveyLatestDate(m)};})
    .filter(e=>e.date&&e.slug&&e.date>=start&&e.date<=build);
  out.sort((a,b)=>a.date<b.date?1:a.date>b.date?-1:(a.sv<b.sv?1:-1));
  return out.slice(0,limit||3);
}
// ONE concise horizontal line, wrapping - "Recently added: Vulcan 2022 (interpunct)
// AusLAMP Queensland Phase 3" - not a heading over a column of rows. See docs: portal internals, main.js.
function recentlyAddedHtml(entries){
  if(!entries.length)return"";
  const items=entries.map(e=>`<a href="/surveys/${encodeURIComponent(e.slug)}" title="${escAttr("Latest release "+e.date)}">${esc(e.sv)}</a>`).join(" · ");
  return `<span class="ra-label">Recently added:</span> ${items}`;
}
// ONE surface only (the surveys-view #recentStrip). See docs: portal internals, main.js.
function renderRecentlyAdded(){
  const entries=recentlyAdded(3);
  const strip=document.getElementById("recentStrip");
  if(strip){strip.innerHTML=recentlyAddedHtml(entries);
    strip.classList.toggle("hidden",!entries.length);}
}
function setView(v){
  // Navigating OFF the map ends any All-EDIs selection lens - the lens
  // is a map-scoped view and its rail is hidden on other views, so it must not persist. See docs: portal
  // internals, main.js.
  if(v!=="map"&&typeof restoreSelectLens==="function")restoreSelectLens();
  curView=v;
  document.body.classList.toggle("tree-tall",v==="surveys");   // give the country→org→survey tree more height on the Surveys view
  document.getElementById("navMap").classList.toggle("active",v==="map");
  document.getElementById("navSurveys").classList.toggle("active",v==="surveys");
  const _nc=document.getElementById("navCollections");if(_nc)_nc.classList.toggle("active",v==="collections");
  document.getElementById("map").style.display=v==="map"?"flex":"none";
  document.getElementById("surveysview").style.display=v==="surveys"?"block":"none";
  const _cv=document.getElementById("collectionview");if(_cv)_cv.style.display="none";   // the single-collection detail page
  const _ci=document.getElementById("collectionsview");if(_ci)_ci.style.display=v==="collections"?"block":"none";
  // matches BOTH top-level filter-rail <section>s and, since the "Screening (advanced)" details wrap
  // merged a map-only control (colour-by) into an otherwise both-views section, any data-views element
  // nested inside one (selector kept generic rather than section-only for that one sub-case).
  document.querySelectorAll('#filterPane [data-views]').forEach(sec=>{
    const a=sec.getAttribute("data-views");sec.classList.toggle("hidden",!(a==="both"||a===v));});
  // The map legend sits over the map, so it belongs to the map view only. (The
  // first-visit welcome popup is a modal dismissed by user action, not tied to the view - no toggle here.)
  const _leg=document.getElementById("mapLegend");if(_leg)_leg.classList.toggle("hidden",v!=="map");
  // The left filter rail (+ its resize handle) belong to the MAP view. On Surveys and Collections the
  // rail's controls don't apply (search + facet chips live in the discovery bar there), so hide both and
  // let the content span the width. See docs: portal internals, main.js.
  const _showRail=(v==="map");
  const _fp=document.getElementById("filterPane");if(_fp)_fp.classList.toggle("hidden",!_showRail);
  const _rz=document.getElementById("resizer");if(_rz)_rz.classList.toggle("hidden",!_showRail);
  if(v==="surveys"){closeDrawer();renderCards();}
  else if(v==="collections"){closeDrawer();renderCollections();}
  else setTimeout(()=>{map.invalidateSize();
    // After the size is reclaimed, run the one-shot home-fit corrector (map.js) - it repairs the
    // off-centre-on-load case (a degenerate primary fit) and stands down without fighting a user's own view.
    if(typeof _mapCorrectHomeFit==="function")_mapCorrectHomeFit();},60);
  if(typeof ST!=="undefined"&&ST.length)renderRecentlyAdded();
  updateCounts();
}
// Only Map switches a view in place. See docs: portal internals, main.js.
document.getElementById("navMap").onclick=()=>setView("map");

function routeFromHash(){
  // The PLURAL routes. Published HTML has pointed at #/surveys since the entity pages shipped (every survey
  // page's back-nav, plus 404.html's recovery link) and no branch matched it, so the hash fell through and
  // the reader stayed on whatever view was showing. See docs: portal internals, main.js.
  if(location.hash==="#/surveys"){setView("surveys");return;}
  if(location.hash==="#/collections"){setView("collections");return;}
  const mc=location.hash.match(/^#\/collection\/(.+)$/);
  if(mc){openCollectionPage(decodeURIComponent(mc[1]));return;}
  const m=location.hash.match(/^#\/station\/(.+)$/);
  if(m){const id=decodeURIComponent(m[1]);
    // resolve by the globally-unique ausmt_id (DATAID s.id repeats across surveys); fall back to s.id for old links
    const s=ST.find(x=>x.ausmt_id===id)||ST.find(x=>x.id===id);
    if(s){if(curView!=="map")setView("map");openStation(s.i);}return;}
  const msv=location.hash.match(/^#\/survey\/(.+)$/);
  if(msv){const slug=decodeURIComponent(msv[1]),sv=SLUG_TO_SURVEY[slug];
    // The entity page's button for this route is labelled "View all stations on the main map", so the route
    // must FRAME the survey: openSurvey rewrites the hash and renders but frames nothing, and the setView
    // above is on the station branch only. See docs: portal internals, main.js.
    if(sv){openSurvey(sv);focusSurvey(sv);}
    return;}                                           // unknown slug: fall through, no crash, no view change
  // hash fell through (e.g. browser Back to ''): if a full-width collection detail is showing, restore a tab view
  if(curView==="collection")setView("map");}
window.addEventListener("hashchange",routeFromHash);

// "View all stations on main map" from a collection page - switch to the map view and fit the map to the
// collection's extent. See docs: portal internals, main.js.
function viewCollectionOnMap(cid){
  const c=(typeof COLL!=="undefined"&&COLL)?COLL[cid]:null;
  setView("map");
  let b=null;
  if(c&&c.bbox&&typeof L!=="undefined"&&L.latLngBounds){
    b=L.latLngBounds([[c.bbox.south,c.bbox.west],[c.bbox.north,c.bbox.east]]);
  }else if(c){
    const members=c.surveys||[],pts=ST.filter(s=>members.indexOf(s.survey)>=0&&hasPosition(s)).map(s=>[s.lat,s.lon]);
    if(pts.length&&typeof L!=="undefined"&&L.latLngBounds)b=L.latLngBounds(pts);
  }
  if(b&&typeof map!=="undefined"&&map.fitBounds)map.fitBounds(b.pad?b.pad(0.15):b);
}

const sidebar=document.getElementById("filterPane"),resizer=document.getElementById("resizer");
function sbLimits(){return {min:248,max:Math.max(300,Math.min(620,Math.round(window.innerWidth*0.5)))};}
function setSidebar(px){const{min,max}=sbLimits();sidebar.style.width=Math.round(Math.max(min,Math.min(max,px)))+"px";}
(function(){let dragging=false;
  const onMove=e=>{if(!dragging)return;const x=(e.touches?e.touches[0].clientX:e.clientX)-sidebar.getBoundingClientRect().left;setSidebar(x);if(curView==="map")map.invalidateSize();};
  const stop=()=>{dragging=false;resizer.classList.remove("drag");document.body.style.userSelect="";};
  const start=e=>{if(window.innerWidth<=760)return;dragging=true;resizer.classList.add("drag");document.body.style.userSelect="none";e.preventDefault();};
  resizer.addEventListener("mousedown",start);resizer.addEventListener("touchstart",start,{passive:false});
  window.addEventListener("mousemove",onMove);window.addEventListener("touchmove",onMove,{passive:false});
  window.addEventListener("mouseup",stop);window.addEventListener("touchend",stop);
  window.addEventListener("resize",()=>{if(window.innerWidth>760)setSidebar(parseInt(sidebar.style.width||"363",10));});
})();

// Collapse the filter rail to a ~36px icon strip. Class toggle only (CSS forces the
// width with !important, beating the resizer's inline width), invalidateSize so the map reclaims the
// space, and the state persists in localStorage.
const SB_COLLAPSE_KEY="ausmt_sidebar_collapsed";
function sidebarCollapsed(){try{return localStorage.getItem(SB_COLLAPSE_KEY)==="1";}catch(e){return false;}}
function setSidebarCollapsed(collapsed){
  sidebar.classList.toggle("collapsed",collapsed);
  const btn=document.getElementById("sidebarCollapse");
  if(btn){btn.setAttribute("aria-expanded",String(!collapsed));
    btn.setAttribute("aria-label",collapsed?"Expand sidebar":"Collapse sidebar");
    btn.title=collapsed?"Expand sidebar":"Collapse sidebar";btn.textContent=collapsed?"›":"‹";}
  try{localStorage.setItem(SB_COLLAPSE_KEY,collapsed?"1":"0");}catch(e){/* storage unavailable - don't persist */}
  if(curView==="map"&&typeof map!=="undefined"&&map.invalidateSize)map.invalidateSize();
}
(function(){
  const btn=document.getElementById("sidebarCollapse");
  if(btn)btn.onclick=()=>setSidebarCollapsed(!sidebar.classList.contains("collapsed"));
  if(sidebarCollapsed())setSidebarCollapsed(true);   // apply the persisted state on load
})();

// Drawer left-edge drag handle. It reuses the resizer pattern but is created HERE (never in drawer.js) and
// parented to .content - NOT #drawer, whose innerHTML drawer.js rewrites on every open (which would wipe a
// child handle). See docs: portal internals, main.js.
(function(){
  const drawer=document.getElementById("drawer"),content=document.getElementById("content");
  if(!drawer||!content)return;
  const handle=document.createElement("div");handle.id="drawerResizer";
  handle.setAttribute("role","separator");handle.setAttribute("aria-orientation","vertical");
  handle.setAttribute("aria-label","Resize station details panel");handle.title="Drag to resize";
  handle.style.display="none";                        // hidden until the drawer opens
  content.appendChild(handle);
  let drawerW=420,dragging=false;
  const limits=()=>({min:420,max:Math.max(420,Math.round(window.innerWidth*0.6))});
  const place=()=>{handle.style.right=drawerW+"px";};
  const onMove=e=>{if(!dragging)return;const x=(e.touches?e.touches[0].clientX:e.clientX);
    const{min,max}=limits();drawerW=Math.round(Math.max(min,Math.min(max,window.innerWidth-x)));
    drawer.style.width=drawerW+"px";place();};
  const stop=()=>{if(!dragging)return;dragging=false;handle.classList.remove("drag");document.body.style.userSelect="";
    if(typeof map!=="undefined"&&map.invalidateSize)map.invalidateSize();};
  const start=e=>{if(window.innerWidth<=760)return;dragging=true;handle.classList.add("drag");document.body.style.userSelect="none";e.preventDefault();};
  handle.addEventListener("mousedown",start);handle.addEventListener("touchstart",start,{passive:false});
  window.addEventListener("mousemove",onMove);window.addEventListener("touchmove",onMove,{passive:false});
  window.addEventListener("mouseup",stop);window.addEventListener("touchend",stop);
  const sync=()=>{const open=drawer.classList.contains("open");handle.style.display=open?"block":"none";if(open)place();};
  if(typeof MutationObserver!=="undefined"){const mo=new MutationObserver(sync);mo.observe(drawer,{attributes:true,attributeFilter:["class"]});}
})();

// Load-error copy distinguishes the two real causes rather than always blaming file:// (which was this
// message's original, pre-container diagnosis). See docs: portal internals, main.js.
function showLoadError(){
  var overFile=(location.protocol==="file:");
  document.getElementById("content").innerHTML = overFile
    ? "<p style=\"padding:24px;color:#E8EDF1\">Could not load data/*.json: pages opened from disk cannot fetch data. Serve over HTTP (e.g. <code>python3 -m http.server</code>).</p>"
    : "<p style=\"padding:24px;color:#E8EDF1\">The catalogue data isn't available yet (data/*.json not found on this server). If you operate this deployment: no data build is published; run the build pipeline (<code>make rebuild-data</code>) to publish one.</p>";
}
function portalIsEmpty(){return !Array.isArray(CAT)||CAT.length===0;}
function showEmptyState(){
  var name=(window.AUSMT_CONFIG&&window.AUSMT_CONFIG.short_name)||"this portal";
  var html='<div class="emptystate" role="status">'+
    '<h2>No surveys published yet</h2>'+
    '<p>No surveys have been published to '+name+' yet. Use <a href="add-survey.html">Add Survey</a> '+
    'to prepare a submission, or add curated surveys to the surveys repository and rebuild the portal.</p>'+
    '</div>';
  var mapEl=document.getElementById("map");
  if(mapEl&&!document.getElementById("emptyOverlay")){
    var ov=document.createElement("div");ov.id="emptyOverlay";ov.className="emptyoverlay";ov.innerHTML=html;
    mapEl.appendChild(ov);
  }
  var sv=document.getElementById("surveysview");if(sv)sv.innerHTML=html;
}
// --- First-visit welcome popup ----------------------------------------------------------- The first-visit
// surface is a small centred MODAL popup (#introWelcome). See docs: portal internals, main.js.
const INTRO_KEY="ausmt_intro_dismissed";
function introSeen(){try{return localStorage.getItem(INTRO_KEY)==="1";}catch(e){return false;}}
function markIntroSeen(){try{localStorage.setItem(INTRO_KEY,"1");}catch(e){/* storage unavailable (e.g. privacy mode) - just don't persist */}}
// startTour lives in tour.js (loaded after main.js); guard so a missing/broken tour.js can't break wiring.
function startTourSafe(){if(typeof startTour==="function")startTour();}
// Welcome popup: focus is moved INTO the box on show and RESTORED to the opener on close - the same
// best-effort/guarded pattern the drawer uses (so the headless harness, with no real focus, never throws).
let _welcomeReturnFocus=null;
function welcomeDismissChecked(){const c=document.getElementById("welcomeDismiss");return !!(c&&c.checked);}
function showWelcome(){
  const w=document.getElementById("introWelcome");if(!w)return;
  _welcomeReturnFocus=(typeof document!=="undefined"&&document)?document.activeElement:null;
  w.classList.remove("hidden");
  const f=document.getElementById("welcomeTour")||w.querySelector(".introwelcome-box");
  if(f&&f.focus){try{f.focus();}catch(e){}}
}
function hideWelcome(){const w=document.getElementById("introWelcome");if(w)w.classList.add("hidden");
  const f=_welcomeReturnFocus;_welcomeReturnFocus=null;if(f&&f.focus){try{f.focus();}catch(e){}}}
// Close via Browse / Esc / click-out: persist ONLY when "Don't show this again" is ticked.
function closeWelcome(){if(welcomeDismissChecked())markIntroSeen();hideWelcome();}
// ?tour=1 (About's "start the guided tour" link) starts the tour outright and shows no popup. Anything else
// falls back to the first-visit rule: show the welcome popup unless the visitor dismissed it. See docs:
// portal internals, main.js.
function tourRequested(){try{return /(^|[?&])tour=1(&|$)/.test(location.search||"");}catch(e){return false;}}
function dropTourParam(){try{
  const q=(location.search||"").replace(/(^\?|&)tour=1(?=&|$)/,"").replace(/^&/,"?");
  history.replaceState(null,"",location.pathname+(q==="?"?"":q)+location.hash);
}catch(e){/* no History API (or a file:// document); leaving the parameter in place is harmless */}}
function maybeShowIntro(){if(tourRequested()){startTourSafe();dropTourParam();return;}if(!introSeen())showWelcome();}

(function(){
  // Welcome popup wiring. "Take the tour" starts the tour AND closes
  // the popup persisting-if-ticked; "Browse immediately" just closes (persist-if-ticked); Esc / click-out
  // behave as Browse immediately.
  const wTour=document.getElementById("welcomeTour");if(wTour)wTour.onclick=()=>{closeWelcome();startTourSafe();};
  const wBrowse=document.getElementById("welcomeBrowse");if(wBrowse)wBrowse.onclick=closeWelcome;
  const welcome=document.getElementById("introWelcome");
  if(welcome){
    welcome.addEventListener("click",e=>{if(e.target===welcome)closeWelcome();});                    // click-out = Browse immediately
    document.addEventListener("keydown",e=>{if(e.key==="Escape"&&!welcome.classList.contains("hidden"))closeWelcome();});
  }
})();

// Static map legend (bottom-left): a coloured dot per data type, and nothing else, since a dot is the only
// thing the map draws. See docs: portal internals, main.js.
function legendTypeBox(key){
  return [...document.querySelectorAll("#typeBoxes input")].find(c=>c.value===key)||null;}
// Legend row activation. Flip the rail checkbox and fire ITS change event - the sole state mutation.
function toggleLegendType(key){
  const box=legendTypeBox(key);if(!box)return;
  box.checked=!box.checked;
  box.dispatchEvent(new Event("change",{bubbles:true}));}
// Two-way sync: repaint the legend FROM the checkboxes. Called from the one #typeBoxes change path, so a
// rail flip and a legend flip both land here. See docs: portal internals, main.js.
function syncLegendTypes(){
  const leg=document.getElementById("mapLegend");if(!leg||!leg.querySelectorAll)return;
  leg.querySelectorAll(".legtype").forEach(btn=>{
    const box=legendTypeBox(btn.dataset.type),on=box?!!box.checked:true;
    btn.setAttribute("aria-pressed",String(on));
    btn.classList.toggle("legoff",!on);});}
// The metric scale bar, RE-PARENTED into the legend body. See docs: portal internals, main.js.
function buildScaleBar(body){
  if(!body||!body.appendChild||body.querySelector(".maplegend-scale"))return null;   // idempotent, like buildLegend
  if(typeof L==="undefined"||!L.control||typeof L.control.scale!=="function")return null;
  const ctl=L.control.scale({metric:true,imperial:false,maxWidth:120});
  if(!ctl||typeof ctl.addTo!=="function")return null;
  ctl.addTo(map);
  const el=(typeof ctl.getContainer==="function")?ctl.getContainer():null;
  // Only a REAL element is moved. The headless harnesses stub Leaflet, so getContainer() there answers
  // with something that is not a node, and appendChild would throw on the boot path.
  if(!el||el.nodeType!==1||!el.classList)return null;
  el.classList.add("maplegend-scale");
  body.appendChild(el);
  return el;}
function buildLegend(){
  if(document.getElementById("mapLegend"))return;                 // idempotent
  const host=document.getElementById("map");if(!host)return;       // the Leaflet container is the overlay's positioning context
  const types=[["--lpmt","Long period","LPMT"],["--bbmt","Broadband","BBMT"],["--amt","AMT","AMT"],["--gds","GDS (tipper)","GDS"]];
  const rows=types.map(([v,label,key])=>`<button type="button" class="legrow legtype" data-type="${key}" aria-pressed="true" `+
    `title="Show or hide ${label} stations on the map"><span class="dot" style="background:var(${v})"></span>${label}</button>`).join("");
  const small=typeof window!=="undefined"&&window.innerWidth<=760;   // body defaults collapsed on small widths
  const el=document.createElement("div");el.id="mapLegend";el.className="maplegend";
  // The hint takes the slot a "Legend" title would take (the box carries no desktop title; the
  // "Legend" button above is the small-width collapse control only), so the affordance is stated
  // once, where the eye lands first, without adding a heading the desktop layout does not have.
  el.innerHTML=`<button type="button" class="maplegend-toggle" id="mapLegendToggle" aria-expanded="${small?"false":"true"}">Legend</button>`+
    `<div class="maplegend-body"><div class="leghint">Click a type to show or hide it</div>${rows}</div>`;
  host.appendChild(el);
  buildScaleBar(el.querySelector(".maplegend-body"));
  const toggle=el.querySelector("#mapLegendToggle");
  if(toggle)toggle.addEventListener("click",()=>{const ex=el.classList.toggle("expanded");toggle.setAttribute("aria-expanded",String(ex));});
  el.querySelectorAll(".legtype").forEach(btn=>{
    btn.addEventListener("click",()=>toggleLegendType(btn.dataset.type));
    // Explicit keyboard activation. A <button> already activates on Enter/Space in a browser, but the
    // default action is CANCELLED here so the browser cannot then synthesise its own click on top of this
    // handler (one keypress must be one flip, not two). See docs: portal internals, main.js.
    btn.addEventListener("keydown",e=>{
      if(e.key==="Enter"||e.key===" "||e.key==="Spacebar"){e.preventDefault();toggleLegendType(btn.dataset.type);}});});
  syncLegendTypes();                                               // paint from the checkboxes, never from an assumption
}
function runInit(){
  buildState();
  // The Collections tab only appears when the data actually has collections (surveys sharing a collection.id).
  const _nc=document.getElementById("navCollections");
  if(_nc)_nc.style.display=(typeof COLL!=="undefined"&&COLL&&Object.keys(COLL).length)?"":"none";
  if(portalIsEmpty()){buildTree();buildLegend();setView("map");updateCounts();showEmptyState();maybeShowIntro();renderRecentlyAdded();return;}
  buildMarkers();buildFootprints();buildTree();buildLegend();setView("map");refresh();routeFromHash();maybeShowIntro();renderRecentlyAdded();
}
// "data build <short id> · <date>" footer text, or "" when build.json didn't resolve (older builds predate
// it - BUILDID is null - so the placeholder must stay empty, not show stale/undefined text). See docs:
// portal internals, main.js.
function buildIdText(){
  if(!BUILDID||!BUILDID.build_id)return"";
  const raw=String(BUILDID.build_id);
  const date=(BUILDID.generated||"").slice(0,10);
  if(/\b(None|unknown)\b/.test(raw))return date?" · data build "+date:"";
  const short=raw.slice(0,12);
  return " · data build "+short+(date?" · "+date:"");
}
// Uses textContent (not innerHTML+esc()) - never parses markup at all, the strictest available
// guard - even though build_id/generated are engine-generated, not user input. The full raw id (even
// when display-defended above) rides in the title attr so it's still inspectable, not lost.
function renderBuildId(){
  const el=document.getElementById("buildId");
  if(!el)return;
  el.textContent=buildIdText();
  if(BUILDID&&BUILDID.build_id)el.title="build "+String(BUILDID.build_id);
}
// ---- two-phase boot ------------------------------------------------------------------------------
// HYDRATION_DONE settles once every phase-2 product has landed AND its late-render work has run. See docs:
// portal internals, main.js.
let HYDRATION_DONE=Promise.resolve();
// Late hydration must never leave a stale render standing. See docs: portal internals, main.js.
function wireHydration(){
  const tf=TF_READY.then(()=>{rehydrateOpenDrawer();});
  const sci=SCI_READY.then(()=>{
    applySciToStations();
    // SCI_READY settles on FAILURE too (phase 2 records the failure rather than rejecting), so
    // consumers gate on hydrUsable, not the bare fact that the promise resolved. The completeness
    // PREDICATE (qMin) is gated on the same hydrUsable inside passesCore, which keeps it inert.
    if(typeof recolor==="function")recolor();
    if(ST.length&&typeof refresh==="function")refresh();
    rehydrateOpenDrawer();
  });
  // The selection card's zip-size estimates are read off the manifest too, and updateSel() last ran
  // before it landed, so they would sit blank until the reader next changed the selection. Repaint them
  // on the same gate that re-renders the drawer.
  const man=MANIFEST_READY.then(()=>{rehydrateOpenDrawer();
    if(typeof paintDownloadRows==="function")paintDownloadRows();});
  // ts_access.json settles the availability facet: until it lands nothing on the page knows which stations
  // this deployment can hand off, so the Download rows and the Data available options are repainted here
  // with counts and sizes. See docs: portal internals, main.js.
  const tsa=TSACC_READY.then(()=>{
    if(typeof paintDownloadRows==="function")paintDownloadRows();
    if(typeof paintAvailSelect==="function")paintAvailSelect();
    if(ST.length&&typeof refresh==="function")refresh();
    rehydrateOpenDrawer();});
  HYDRATION_DONE=Promise.all([tf,sci,man,tsa]);
}
async function boot(){
  if(typeof CAT==="undefined"||CAT===null){
    // Both phases are issued HERE, together: phase 2 does not wait for phase 1 to resolve (the heavy
    // products are independent of the catalogue), and the first paint below does not wait for phase 2.
    const p1=loadPhase1();
    // Phase 1 is the only fatal set: no catalogue or no surveys means there is nothing honest to draw.
    // A phase-2 failure is reported by the consumers that read it, not by blanking the whole portal.
    try{[CAT,SMETA,PROV,COLL,BUILDID,COORD_POLICY]=await p1;}catch(e){showLoadError();return;}
    // Hydration starts only AFTER phase 1 has its bytes: the phase-2 products are large (tf.json alone is
    // most of the page weight) and share one connection with the catalogue the dots need. See docs: portal
    // internals, main.js.
    startHydration();
  }
  // The ts_access-driven surfaces are inert and disabled until the index is known: the Download
  // block's time-series rows and the Data available level options each paint their own in-flight
  // state. Applied BEFORE the first render so neither is ever briefly live over data that has not
  // arrived.
  if(typeof paintDownloadRows==="function")paintDownloadRows();
  if(typeof paintAvailSelect==="function")paintAvailSelect();
  renderBuildId();
  runInit();
  wireHydration();
}
document.addEventListener("DOMContentLoaded",boot);
