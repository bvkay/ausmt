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
  if(v==="surveys"){closeDrawer();renderCards();}
  else if(v==="collections"){closeDrawer();renderCollections();}
  else setTimeout(()=>map.invalidateSize(),60);
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
// --- "three ways in" intro panel (S2 UX-A) ---------------------------------------------------
// Dismissible on first visit (localStorage key below); reachable again later via the header
// "How to use AusMT" link. Renders in BOTH the populated and empty-data states (it explains the
// portal even before any survey exists), so it is shown from runInit(), not boot()/loadData().
const INTRO_KEY="ausmt_intro_dismissed";
function introSeen(){try{return localStorage.getItem(INTRO_KEY)==="1";}catch(e){return false;}}
function markIntroSeen(){try{localStorage.setItem(INTRO_KEY,"1");}catch(e){/* storage unavailable (e.g. privacy mode) — just don't persist */}}
function showIntro(){const ov=document.getElementById("introOverlay");if(ov)ov.classList.remove("hidden");}
function hideIntro(){const ov=document.getElementById("introOverlay");if(ov)ov.classList.add("hidden");}
function dismissIntro(){markIntroSeen();hideIntro();}
function maybeShowIntro(){if(!introSeen())showIntro();}

(function(){
  const closeBtn=document.getElementById("introClose");if(closeBtn)closeBtn.onclick=dismissIntro;
  // Tile 1: "Browse & download" — dismiss the panel and focus the map (the default view).
  const tB=document.getElementById("tileBrowse");if(tB)tB.onclick=()=>{dismissIntro();setView("map");};
  // Tile 2: "Contribute a survey" — off to the guided add-survey flow.
  const tC=document.getElementById("tileContribute");if(tC)tC.onclick=()=>{dismissIntro();window.location.href="add-survey.html";};
  // Tile 3: "Integrate" — machine-readable catalogue docs on the About page.
  const tI=document.getElementById("tileIntegrate");if(tI)tI.onclick=()=>{dismissIntro();window.location.href="about.html#standards";};
  // Header link re-opens the panel on demand; it does NOT reset the dismissed flag (a later visit
  // still starts hidden — only an explicit dismiss/first-visit state controls the localStorage key).
  const howTo=document.getElementById("howToUse");if(howTo)howTo.onclick=showIntro;
  // "Take the tour" button lives inside the panel; startTour is defined in tour.js (loaded after
  // main.js) — guarded so a missing/broken tour.js can't break the panel itself.
  const tourBtn=document.getElementById("introTakeTour");
  if(tourBtn)tourBtn.onclick=()=>{dismissIntro();if(typeof startTour==="function")startTour();};
  // UX3 item 2: the header "Take the tour" button (#headerTour) was removed — the single header help
  // entry point is now "How to use AusMT" (#howToUse, wired above), which opens the intro panel; the
  // panel's own "Take the tour" button (#introTakeTour) starts the tour. So there is one help button in
  // the header, not two.
})();

function runInit(){
  buildState();
  // The Collections tab only appears when the data actually has collections (surveys sharing a collection.id).
  const _nc=document.getElementById("navCollections");
  if(_nc)_nc.style.display=(typeof COLL!=="undefined"&&COLL&&Object.keys(COLL).length)?"":"none";
  if(portalIsEmpty()){buildTree();setView("map");updateCounts();showEmptyState();maybeShowIntro();renderRecentlyAdded();return;}
  buildMarkers();buildFootprints();buildTree();setView("map");refresh();routeFromHash();maybeShowIntro();renderRecentlyAdded();
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
