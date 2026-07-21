"use strict";
// Coordinator: builds derived state, owns view switching + routing + the resizer, and runs the
// data-dependent init in order. Modules don't call each other at load time; main sequences them.
function buildState(){
  ST=CAT.map((r,i)=>({i,id:r[C.id],survey:r[C.survey],lat:r[C.lat],lon:r[C.lon],pmin:r[C.period_min_s],pmax:r[C.period_max_s],nper:r[C.n_periods],comps:r[C.comps],type:r[C.type],region:r[C.region],file:r[C.file],fixed:r[C.coord_flag],
    ediAvail:r[C.edi_available]===1, sha:r[C.sha256]||null,
    org:(SMETA[r[C.survey]]||{}).org||"Unknown",country:(SMETA[r[C.survey]]||{}).country||"Australia",
    slug:(SMETA[r[C.survey]]||{}).slug||null,
    // S3: the survey's declared year range (ints|null), read straight off SMETA (engine-parsed —
    // the portal never re-parses date strings). null when the survey.yaml declares no dates.
    yearStart:(SMETA[r[C.survey]]||{}).year_start??null,yearEnd:(SMETA[r[C.survey]]||{}).year_end??null,
    q:(SCI[i]||[])[SC.q], dim:(SCI[i]||[])[SC.dim],
    // Use the authoritative ausmt_id the engine wrote into catalogue column r[C.ausmt_id]
    // (au.<survey-slug>.<station>). Fall back to the legacy survey-name slugification only for
    // older data that predates r[C.ausmt_id], so the id shown/exported matches the product + MTCAT.
    ausmt_id:r[C.ausmt_id]||((CC[(SMETA[r[C.survey]]||{}).country]||"au").toLowerCase()+"."+r[C.survey].toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/-$/,"")+"."+r[C.id])}));
  // C42 A1: fold the boot-loaded coordinate policy onto each station (generalised | withheld), keyed by
  // the authoritative ausmt_id just derived; null when exact/unmarked. Positions are already masked in the
  // catalogue — this signals POLICY, not position — so the drawer can badge a generalised station honestly
  // without re-deriving precision client-side (forbidden by the record). Tolerant of an absent artifact.
  const _cp=(typeof COORD_POLICY!=="undefined"&&COORD_POLICY)||{};
  ST.forEach(s=>{s.coordPolicy=_cp[s.ausmt_id]||null;});
  surveys=[...new Set(ST.map(s=>s.survey))].sort();
  // slug -> survey label, for the #/survey/<slug> route (the sitemap emits these; ausmt_id is
  // au.<slug>.<station> — mirrors the engine's own slug_of derivation in extract/build_portal.py
  // rather than re-slugifying the label, so it stays correct even if a label's slugification is
  // irregular). Prefer the authoritative SMETA[survey].slug; fall back to deriving it from a
  // station's own ausmt_id (strip "au." and the trailing ".<station>") for older data without it.
  SLUG_TO_SURVEY={};
  surveys.forEach(sv=>{const slug=(SMETA[sv]||{}).slug;if(slug)SLUG_TO_SURVEY[slug]=sv;});
  ST.forEach(s=>{if(!SLUG_TO_SURVEY[s.slug||""]&&s.ausmt_id){
    const rest=s.ausmt_id.replace(/^[a-z]+\./,"");                 // strip "au."/country prefix
    const derived=rest.endsWith("."+s.id)?rest.slice(0,-(s.id.length+1)):null;
    if(derived)SLUG_TO_SURVEY[derived]=s.survey;}});
  buildAuslampSet();
  applyYearRangeHints();
}
// UX4 (D1/D2): build AUSLAMP_SET (survey SLUGS in the `auslamp` collection) from the boot data. The
// collections.json member list (COLL.auslamp.surveys) holds survey LABELS, not slugs (the engine keys
// _group_collections by the survey.yaml name; see build_portal.py); the portal's partition/colour
// predicates key off s.slug, so each label is resolved through SMETA[label].slug here — the SAME
// authoritative slug the engine wrote (no re-derivation). Absent collection / absent slug => empty set
// (graceful degrade). Rebuildable (not a boot-only const) so a test can repopulate COLL and re-run it.
function buildAuslampSet(){
  AUSLAMP_SET=new Set();
  const c=(typeof COLL!=="undefined"&&COLL)?COLL.auslamp:null;
  if(!c||!Array.isArray(c.surveys))return;                         // no auslamp collection -> nothing is AusLAMP
  c.surveys.forEach(label=>{const slug=(SMETA&&SMETA[label]||{}).slug;if(slug)AUSLAMP_SET.add(slug);});
}
// UX feedback round 1 (#2): corpus-wide year hints on the two Year range inputs — placeholder + min/max
// attrs from the min year_start / max year_end across ALL of SMETA (not just ST, so an undated-in-CAT
// survey with declared dates still counts), plus the range appended to the section label, e.g.
// "Year range (2019-2022)". Values themselves stay EMPTY on load — deliberately NOT defaulted to the
// corpus range: passesYearRange() treats a set input as "a range WAS requested" and hides undated
// surveys, so pre-filling the inputs would immediately (and silently) drop every undated survey the
// moment the page loads. These are hints for what values are meaningful, not a default filter.
function applyYearRangeHints(){
  let lo=null,hi=null;
  Object.keys(SMETA||{}).forEach(sv=>{const m=SMETA[sv]||{};
    if(typeof m.year_start==="number")lo=(lo==null?m.year_start:Math.min(lo,m.year_start));
    if(typeof m.year_end==="number")hi=(hi==null?m.year_end:Math.max(hi,m.year_end));});
  const fromEl=document.getElementById("yearFrom"),toEl=document.getElementById("yearTo"),head=document.getElementById("yearRangeHead");
  const dated=lo!=null&&hi!=null;
  if(fromEl){fromEl.placeholder=dated?String(lo):"from";if(dated)fromEl.min=lo,fromEl.max=hi;}
  if(toEl){toEl.placeholder=dated?String(hi):"to";if(dated)toEl.min=lo,toEl.max=hi;}
  if(head)head.textContent="Year range"+(dated?` (${lo}–${hi})`:"");   // suffix hidden when no survey is dated
}
// ---- "Recently added" (S3): same date logic as the engine's feed.xml (build_portal.py
// _survey_latest_date/feed_entries) — latest release_notes[].date, else dates end/start year
// (falls back to Dec 31 of that year so it still sorts correctly against day-precision dates).
// Kept in lockstep with the engine deliberately (comment, not shared code — Python vs JS) so the
// portal strip and the Atom feed can never show a different "latest" survey.
function surveyLatestDate(m){
  const rn=(m&&m.release_notes)||[];
  let best=null;
  if(Array.isArray(rn))rn.forEach(e=>{const d=(e&&e.date)?String(e.date).slice(0,10):"";
    if(/^\d{4}-\d{2}-\d{2}$/.test(d)&&(!best||d>best))best=d;});
  if(best)return best;
  const yr=(m&&(m.year_end||m.year_start))||null;
  return yr?`${yr}-12-31`:null;
}
function recentlyAdded(limit){
  const out=surveys.map(sv=>{const m=SMETA[sv]||{};return {sv,slug:m.slug||null,date:surveyLatestDate(m)};})
    .filter(e=>e.date&&e.slug);
  out.sort((a,b)=>a.date<b.date?1:a.date>b.date?-1:(a.sv<b.sv?1:-1));
  return out.slice(0,limit||5);
}
function recentlyAddedHtml(entries,compact){
  if(!entries.length)return"";
  const items=entries.map(e=>`<li><a href="#/survey/${encodeURIComponent(e.slug)}">${esc(e.sv)}</a>`+
    (compact?"":`<span class="ra-date">${esc(e.date)}</span>`)+`</li>`).join("");
  return `<ul class="recentlist${compact?" compact":""}">${items}</ul>`;
}
function renderRecentlyAdded(){
  const entries=recentlyAdded(5);
  const strip=document.getElementById("recentStrip");
  if(strip){strip.innerHTML=entries.length?`<h2>Recently added</h2>${recentlyAddedHtml(entries,false)}`:"";
    strip.classList.toggle("hidden",!entries.length);}
  const side=document.getElementById("recentSide");
  if(side){const sec=side.closest("section");
    side.innerHTML=recentlyAddedHtml(entries,true);
    if(sec)sec.classList.toggle("hidden",!entries.length);}
}
function setView(v){curView=v;
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
  // UX6 Wave D (D6): the map legend sits over the map, so it belongs to the map view only. (The UX7b
  // first-visit welcome popup is a modal dismissed by user action, not tied to the view — no toggle here.)
  const _leg=document.getElementById("mapLegend");if(_leg)_leg.classList.toggle("hidden",v!=="map");
  if(v==="surveys"){closeDrawer();renderCards();}
  else if(v==="collections"){closeDrawer();renderCollections();}
  else setTimeout(()=>{map.invalidateSize();
    // UX9 item 2: after the size is reclaimed, run the one-shot home-fit corrector (map.js) — it repairs the
    // off-centre-on-load case (a degenerate primary fit) and stands down without fighting a user's own view.
    if(typeof _mapCorrectHomeFit==="function")_mapCorrectHomeFit();},60);
  // re-apply the "hidden when no dated surveys" state — the data-views toggle above just unconditionally
  // unhid #recentSideSection for the map view, which would flash an empty section when there are none.
  if(typeof ST!=="undefined"&&ST.length)renderRecentlyAdded();
  updateCounts();
}
document.getElementById("navMap").onclick=()=>setView("map");
document.getElementById("navSurveys").onclick=()=>setView("surveys");
document.getElementById("navCollections").onclick=()=>setView("collections");

function routeFromHash(){
  const mc=location.hash.match(/^#\/collection\/(.+)$/);
  if(mc){openCollectionPage(decodeURIComponent(mc[1]));return;}
  const m=location.hash.match(/^#\/station\/(.+)$/);
  if(m){const id=decodeURIComponent(m[1]);
    // resolve by the globally-unique ausmt_id (DATAID s.id repeats across surveys); fall back to s.id for old links
    const s=ST.find(x=>x.ausmt_id===id)||ST.find(x=>x.id===id);
    if(s){if(curView!=="map")setView("map");openStation(s.i);}return;}
  const msv=location.hash.match(/^#\/survey\/(.+)$/);
  if(msv){const slug=decodeURIComponent(msv[1]),sv=SLUG_TO_SURVEY[slug];
    if(sv)openSurvey(sv);return;}                      // unknown slug: fall through, no crash, no view change
  // hash fell through (e.g. browser Back to ''): if a full-width collection detail is showing, restore a tab view
  if(curView==="collection")setView("map");}
window.addEventListener("hashchange",routeFromHash);

// UX6 Wave E (E6): "View all stations on main map" from a collection page — switch to the map view and
// fit the map to the collection's extent. Prefers the collection's declared bbox; falls back to the
// bounds of its member stations' positions. Uses the same setView/map seams the rest of the app does.
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

// UX6 Wave D (D5, #24): collapse the filter rail to a ~36px icon strip. Class toggle only (CSS forces the
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
  try{localStorage.setItem(SB_COLLAPSE_KEY,collapsed?"1":"0");}catch(e){/* storage unavailable — don't persist */}
  if(curView==="map"&&typeof map!=="undefined"&&map.invalidateSize)map.invalidateSize();
}
(function(){
  const btn=document.getElementById("sidebarCollapse");
  if(btn)btn.onclick=()=>setSidebarCollapsed(!sidebar.classList.contains("collapsed"));
  if(sidebarCollapsed())setSidebarCollapsed(true);   // apply the persisted state on load
})();

// UX6 Wave D (D5, #24): drawer left-edge drag handle. It reuses the resizer pattern but is created HERE
// (never in drawer.js) and parented to .content — NOT #drawer, whose innerHTML drawer.js rewrites on every
// open (which would wipe a child handle). A MutationObserver mirrors the drawer's open state onto the
// handle's visibility + left-edge position, so drawer.js internals stay untouched. min 420px, max 60vw;
// invalidateSize on drag end.
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

// Load-error copy distinguishes the two real causes rather than always blaming file:// (which was
// this message's original, pre-container diagnosis): over HTTP a failed data load almost always
// means the deployment simply has no published data build yet (e.g. site-data/current absent on a
// fresh server) — an operator hint, phrased so a visitor still understands the portal is fine.
function showLoadError(){
  var overFile=(location.protocol==="file:");
  document.getElementById("content").innerHTML = overFile
    ? "<p style=\"padding:24px;color:#E8EDF1\">Could not load data/*.json: pages opened from disk cannot fetch data. Serve over HTTP (e.g. <code>python3 -m http.server</code>).</p>"
    : "<p style=\"padding:24px;color:#E8EDF1\">The catalogue data isn't available yet (data/*.json not found on this server). If you operate this deployment: no data build is published — run the build pipeline (<code>make rebuild-data</code>) to publish one.</p>";
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
// --- First-visit welcome popup (UX7b U7) + "How AusMT works" help panel (S2 UX-A) ----------------
// U7 (owner, 2026-07-13): the first-visit surface is now a small centred MODAL popup (#introWelcome),
// successor to the Wave D corner strip. It offers exactly: "Take the 2-minute tour" (the #introTakeTour
// pathway — starts the tour), "Browse immediately" (close), and a "Don't show this again" checkbox that
// GATES persistence — ticked, every close path (tour / browse / Esc / click-out) persists the dismissal
// via the existing localStorage key; unticked, the popup may return next visit. Esc and click-out behave
// as "Browse immediately". The #introOverlay "How AusMT works" panel stays an on-demand help dialog
// (header #howToUse). First-visit show fires from runInit() (populated AND empty-data paths).
const INTRO_KEY="ausmt_intro_dismissed";
function introSeen(){try{return localStorage.getItem(INTRO_KEY)==="1";}catch(e){return false;}}
function markIntroSeen(){try{localStorage.setItem(INTRO_KEY,"1");}catch(e){/* storage unavailable (e.g. privacy mode) — just don't persist */}}
function showIntro(){const ov=document.getElementById("introOverlay");if(ov)ov.classList.remove("hidden");}   // opens the "How AusMT works" help panel
function hideIntro(){const ov=document.getElementById("introOverlay");if(ov)ov.classList.add("hidden");}
// Welcome popup: focus is moved INTO the box on show and RESTORED to the opener on close — the same
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
function maybeShowIntro(){if(!introSeen())showWelcome();}      // first visit shows the WELCOME POPUP

(function(){
  // "How AusMT works" help panel (#introOverlay) — on-demand only (header "How to use AusMT"). Close and
  // tiles no longer persist anything; the first-visit localStorage key is owned by the welcome popup.
  const closeBtn=document.getElementById("introClose");if(closeBtn)closeBtn.onclick=hideIntro;
  const tB=document.getElementById("tileBrowse");if(tB)tB.onclick=()=>{hideIntro();setView("map");};
  const tC=document.getElementById("tileContribute");if(tC)tC.onclick=()=>{hideIntro();window.location.href="add-survey.html";};
  const tI=document.getElementById("tileIntegrate");if(tI)tI.onclick=()=>{hideIntro();window.location.href="about.html#standards";};
  const howTo=document.getElementById("howToUse");if(howTo)howTo.onclick=showIntro;
  // startTour lives in tour.js (loaded after main.js); guard so a missing/broken tour.js can't break wiring.
  function startTourSafe(){if(typeof startTour==="function")startTour();}
  // #introTakeTour (help panel) — the sole tour entry from the on-demand panel: hide the panel, start.
  const tourBtn=document.getElementById("introTakeTour");if(tourBtn)tourBtn.onclick=()=>{hideIntro();startTourSafe();};
  // Welcome popup wiring. "Take the tour" reuses the #introTakeTour pathway (start the tour) AND closes
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

// UX6 Wave D (D6): static map legend (bottom-left) — one cluster-bubble row + a coloured dot per data
// type. The dots read the LIVE --lpmt/--bbmt/--amt/--gds tokens via CSS var() (no hard-coded hexes here),
// so they track any future colour change automatically. Built once (idempotent). Collapsible on small
// widths (the toggle only shows there via CSS); starts collapsed on a narrow viewport.
// UX8 (X2, bug): the legend is parented INTO the Leaflet map container (#map), not to .content. As a
// child of #content it was a sibling of #map in that flex row — an absolutely-positioned box, but living
// in the same positioned/flex context as the map, so it participated in that layout and could nudge the
// map's framing at load. Inside #map (which Leaflet keeps position:relative) it is an overlay that can
// NEVER affect the map container's own size or centre: #map's box is measured before this child is
// appended and an absolute child adds nothing to it. It also rides #map's display toggle for free.
function buildLegend(){
  if(document.getElementById("mapLegend"))return;                 // idempotent
  const host=document.getElementById("map");if(!host)return;       // the Leaflet container is the overlay's positioning context
  const types=[["--lpmt","Long period"],["--bbmt","Broadband"],["--amt","AMT"],["--gds","GDS (tipper)"]];
  const rows=types.map(([v,label])=>`<div class="legrow"><span class="dot" style="background:var(${v})"></span>${label}</div>`).join("");
  const small=typeof window!=="undefined"&&window.innerWidth<=760;   // body defaults collapsed on small widths
  const el=document.createElement("div");el.id="mapLegend";el.className="maplegend";
  el.innerHTML=`<button type="button" class="maplegend-toggle" id="mapLegendToggle" aria-expanded="${small?"false":"true"}">Legend</button>`+
    `<div class="maplegend-body"><div class="legrow"><span class="legcluster">n</span> stations (zoom to expand)</div>${rows}</div>`;
  host.appendChild(el);
  const toggle=el.querySelector("#mapLegendToggle");
  if(toggle)toggle.addEventListener("click",()=>{const ex=el.classList.toggle("expanded");toggle.setAttribute("aria-expanded",String(ex));});
}
function runInit(){
  buildState();
  // The Collections tab only appears when the data actually has collections (surveys sharing a collection.id).
  const _nc=document.getElementById("navCollections");
  if(_nc)_nc.style.display=(typeof COLL!=="undefined"&&COLL&&Object.keys(COLL).length)?"":"none";
  if(portalIsEmpty()){buildTree();buildLegend();setView("map");updateCounts();showEmptyState();maybeShowIntro();renderRecentlyAdded();return;}
  buildMarkers();buildFootprints();buildTree();buildLegend();setView("map");refresh();routeFromHash();maybeShowIntro();renderRecentlyAdded();
}
// C12: "data build <short id> · <date>" footer text, or "" when build.json didn't resolve (older
// builds predate it — BUILDID is null — so the placeholder must stay empty, not show stale/undefined
// text). Split from the DOM write below so a test can assert the VALUE binding (BUILDID -> text)
// without needing a real DOM (mirrors buildState()'s station0/export0 value-binding pattern).
//
// UX feedback round 1 (#6): the emitter (build_identity() in engine/extract/build_portal.py) is
// already fixed to never fold Python's None into build_id — an unresolved source_commit renders as
// the WORD "unknown" there, never "None". This function still must not display either literal word
// to a visitor: a build_id containing "None" (an older/foreign build predating that fix) or
// "unknown" (the legitimate no-surveys-commit case) is display-DEFENDED here by dropping the short-id
// segment entirely, keeping only the date (when known) — the full raw id still goes in a title attr
// for anyone who needs to trace it, via renderBuildId() below.
function buildIdText(){
  if(!BUILDID||!BUILDID.build_id)return"";
  const raw=String(BUILDID.build_id);
  const date=(BUILDID.generated||"").slice(0,10);
  if(/\b(None|unknown)\b/.test(raw))return date?" · data build "+date:"";
  const short=raw.slice(0,12);
  return " · data build "+short+(date?" · "+date:"");
}
// Uses textContent (not innerHTML+esc()) — never parses markup at all, the strictest available
// guard — even though build_id/generated are engine-generated, not user input. The full raw id (even
// when display-defended above) rides in the title attr so it's still inspectable, not lost.
function renderBuildId(){
  const el=document.getElementById("buildId");
  if(!el)return;
  el.textContent=buildIdText();
  if(BUILDID&&BUILDID.build_id)el.title="build "+String(BUILDID.build_id);
}
async function boot(){
  if(typeof CAT==="undefined"||CAT===null){try{[CAT,TFD,SCI,SMETA,PROV,COLL,MANIFEST,BUILDID,COORD_POLICY]=await loadData();}catch(e){showLoadError();return;}}
  renderBuildId();
  runInit();
}
document.addEventListener("DOMContentLoaded",boot);
