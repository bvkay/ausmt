"use strict";
// tour.js - the guided spotlight tour. Classic script, zero dependencies, loaded LAST so it may call
// setView()/openStation()/setSidebarMode() and the rest of the app's seams; nothing else depends on it,
// so a missing or broken tour.js must never break the app (main.js guards its entry point with typeof).
//
// Constraints this file has to keep:
//   * The tour NEVER auto-starts. It opens from the welcome popup's button or the ?tour=1 entry only.
//   * A step whose target element is absent renders CENTRED with no spotlight rather than crashing or
//     silently skipping, so an empty corpus, a filtered-out demo or a build without an optional control
//     still walks end to end.
//   * Nothing is persisted. The tour is stateless between visits and re-runnable from either entry.
//   * Every step's enter() establishes its COMPLETE state from either direction and is idempotent:
//     entering a step twice is a no-op the second time. Backward navigation is therefore correct by
//     construction rather than by a per-step undo.
//   * Shared state belongs to a GROUP of steps, not to one step: the group's cleanup runs when the walk
//     crosses the group boundary, never on a move inside it. See _TOUR_SELECT_GROUP below.
//   * stopTour() from ANY step restores the visitor's pre-tour snapshot. Nothing the tour did leaks.
//   * The step counter is computed from the deck. No step count is ever written as a literal.

// The demo survey the copy and the demo steps prefer, and the size below which a survey is too small to
// make the selection demo read. Both are preferences, not requirements: _tourDemoSurvey degrades to the
// largest positioned survey and then to nothing, because a corpus without the preferred survey (the test
// fixture, an empty portal, any future corpus) must still walk.
const TOUR_DEMO_SLUG="vulcan-2022",TOUR_DEMO_MIN=5,TOUR_DEMO_COLLECTION="australia-legacy-gds";

// The deck. `sel` is a static selector so it can be pinned; a step may add `el`, a resolver returning the
// live element to spotlight (used where the target is one card among many), which falls back to `sel`.
// `text` is the copy verbatim; {survey}, {n} and {collection} are resolved at render from the loaded
// corpus, never written into the source.
const TOUR_STEPS=[
  {sel:"#map",
   text:"Every dot is an MT station. Click one to see its transfer function.",
   enter:_tourEnterMapView},
  {sel:"aside.filters",
   text:"Filter by data type; Advanced search adds find, data availability by level (time series; transfer function).",
   enter:_tourEnterFilters},
  {sel:"#find",
   text:"Search stations, surveys or collections. Results update as you type.",
   enter:_tourEnterFindDemo,exit:_tourExitFindDemo},
  {sel:"#browseMode",
   text:"Browse by collection, country, organisation or survey. Tick a level to show or hide it.",
   enter:_tourEnterTreeDemo,exit:_tourExitTreeDemo},
  {sel:"#drawer",
   text:"The station drawer: response plots and provenance, in tabs.",
   enter:_tourEnterStation},
  {sel:"#dp-files",
   text:"Files: what you can fetch for this station, by level - the transfer function served by AusMT, and time series handed off to NCI where they exist.",
   enter:_tourEnterStation},
  {sel:".selbox",
   text:"Select stations: draw an area, or take everything that passes the filters.",
   enter:_tourEnterSelbox},
  {sel:"#map",
   text:"Selecting in action: zoom to {survey}, draw a rectangle, and every station inside is selected - {n} here.",
   enter:_tourEnterSelectStep},
  {sel:"#dlLevel2",
   text:"Level 2 transfer functions, served by AusMT: EDI, EMTF XML and MTH5 zips for your selection.",
   enter:_tourEnterSelectStep},
  {sel:"#dlTimeSeries",
   text:"Time series at NCI: download lists by level, handed off through an AusMT redirect. Metadata and citations follow below.",
   enter:_tourEnterSelectStep},
  {sel:"#navSurveys",
   text:"Surveys lists every survey. Let's look.",
   enter:_tourEnterMapView},
  {sel:"#cardGrid .scard",
   text:"Each card is a survey at a glance. Switch to Compact for a denser list.",
   enter:_tourEnterSurveysView},
  {sel:"#drawer",
   text:"Open a survey for its full record: abstract, stations, downloads and citation. View survey leads to its shareable page.",
   enter:_tourEnterSurveysView},
  {sel:"#collectionsGrid .scard",
   text:"Collections gather related surveys: {collection} here. Open one to explore its members on the map."},
  {sel:"#navMap",
   text:"Map brings you back to the stations."},
  {sel:"#map",
   text:"That's it: find, screen, select, download, cite. Contribute your own survey from Contribute a survey.",
   enter:_tourEnterFinal}
];

// The SELECT group: the steps that share the select rail mode, the demo rectangle and the demo selection.
// The group owns that state, so it is established on entering ANY member and cleaned up only when the
// walk leaves the group in either direction (or the tour stops). A per-step exit hook cannot express this:
// it would tear the shared state down on every move inside the group and rebuild it on the next arrival.
const _TOUR_SELECT_GROUP=[6,7,8,9];
function _tourInSelectGroup(i){return _TOUR_SELECT_GROUP.indexOf(i)>=0;}

// Overlay dim. Single source of truth, applied inline by _tourLayout: on a targeted step it colours the
// spot's box-shadow (the backdrop stays transparent so the cutout shows the element fully); on a
// no-target step it colours the centred backdrop directly.
const TOUR_DIM=0.78;

let _tourStep=-1,_tourEls=null;
// What THIS run has itself opened, so the CLOSING STEP undoes only that and not pre-existing visitor
// state. Closing the tour is a different question and is answered by the pre-tour snapshot below.
let _tourOpened={drawer:false,hash:null};
// The demo subjects resolved once per run (the corpus cannot change mid-run) and cleared on stop.
let _tourDemoSv=undefined;

// ---- demo resolution -------------------------------------------------------------------------------
// Every step that would otherwise name a survey resolves one from the corpus that is actually loaded.
// Preference order: the preferred slug when it has positioned stations, else the first survey large
// enough for the selection demo to read, else the largest positioned survey, else nothing. The last
// case is a real state (an empty portal), and the steps that use it render centred with no demo.
function _tourDemoSurvey(){
  if(_tourDemoSv!==undefined)return _tourDemoSv;
  _tourDemoSv=null;
  if(typeof ST==="undefined"||typeof surveys==="undefined")return _tourDemoSv;
  const pos={};ST.forEach(s=>{if(hasPosition(s))pos[s.survey]=(pos[s.survey]||0)+1;});
  const preferred=(typeof SLUG_TO_SURVEY!=="undefined"&&SLUG_TO_SURVEY[TOUR_DEMO_SLUG])||null;
  if(preferred&&pos[preferred]){_tourDemoSv=preferred;return _tourDemoSv;}
  const big=surveys.find(sv=>(pos[sv]||0)>=TOUR_DEMO_MIN);
  if(big){_tourDemoSv=big;return _tourDemoSv;}
  let best=null;surveys.forEach(sv=>{if((pos[sv]||0)>0&&(best===null||pos[sv]>pos[best]))best=sv;});
  _tourDemoSv=best;return _tourDemoSv;
}
// The collection the collections step names: the preferred id when the corpus carries it, else the first
// collection in the order renderCollections lays the grid out in, so the copy names the card on screen.
function _tourDemoCollection(){
  const coll=(typeof COLL!=="undefined"&&COLL)||null;
  if(!coll)return null;
  if(coll[TOUR_DEMO_COLLECTION])return TOUR_DEMO_COLLECTION;
  const ids=Object.keys(coll).sort();
  return ids.length?ids[0]:null;
}
function _tourCollectionName(cid){
  const c=(typeof COLL!=="undefined"&&COLL&&COLL[cid])||null;
  return (c&&c.title)||cid||"";
}
// The count the selection-demo copy prints: whatever the demo rectangle actually took. Never a literal.
function _tourDemoCount(){return (typeof selected!=="undefined")?selected.size:0;}
// Render a step's copy. The placeholders resolve to the empty-corpus wording when nothing resolved, so
// the sentence stays grammatical rather than showing a token.
function _tourText(step){
  let t=step.text;
  if(t.indexOf("{survey}")>=0)t=t.split("{survey}").join(_tourDemoSurvey()||"a survey");
  if(t.indexOf("{n}")>=0)t=t.split("{n}").join(String(_tourDemoCount()));
  if(t.indexOf("{collection}")>=0)t=t.split("{collection}").join(_tourCollectionName(_tourDemoCollection()));
  return t;
}
// The element a step spotlights: its own resolver when it has one and it finds something, else its
// static selector. Both may come back null, which is the centred no-spotlight state.
function _tourTarget(step){
  if(step&&typeof step.el==="function"){const e=step.el();if(e)return e;}
  return (step&&step.sel)?document.querySelector(step.sel):null;
}

// ---- enter hooks -----------------------------------------------------------------------------------
// Map-view steps: forward this is a no-op; its real job is BACKWARD navigation from the Surveys and
// Collections steps, where map-only targets would otherwise be display:none and the step would fall back
// to a centred card.
function _tourEnterMapView(){
  if(typeof curView!=="undefined"&&curView!=="map"&&typeof setView==="function")setView("map");
}
// The filter-rail overview: the rail's Advanced search accordion is opened so the controls the copy
// names are on screen. Idempotent (details.open is a set, not a toggle).
function _tourEnterFilters(){
  _tourEnterMapView();
  const adv=document.getElementById("advSearch");if(adv)adv.open=true;
}
function _tourEnterSurveysView(){
  if(typeof curView!=="undefined"&&curView!=="surveys"&&typeof setView==="function")setView("surveys");
}
// The select group's shared state: the rail mode, the demo rectangle and the demo selection. The visitor's
// own mode is captured ONCE on entering the group and restored when the walk leaves it, so a move inside
// the group never touches it. `created` records whether the tour made a selection of its own, so the
// teardown clears the demo and never a selection the visitor brought with them.
let _tourSel={mode:null,created:false,bounds:null};
function _tourEnterSelectMode(){
  if(typeof setSidebarMode!=="function"||typeof sidebarMode==="undefined")return;
  if(_tourSel.mode===null)_tourSel.mode=sidebarMode;
  if(sidebarMode!=="select")setSidebarMode("select");
}
function _tourLeaveSelectGroup(){
  if(_tourSel.created){
    try{if(typeof drawn!=="undefined"&&drawn.clearLayers)drawn.clearLayers();}catch(e){}
    if(typeof selected!=="undefined"){selected.clear();if(typeof updateSel==="function")updateSel();}
    if(typeof clearSurveyDim==="function")clearSurveyDim();
  }
  if(_tourSel.mode!==null&&typeof setSidebarMode==="function")setSidebarMode(_tourSel.mode);
  if(_tourMapMoved&&_tourSnap){_tourFitBounds(_tourSnap.bounds);_tourMapMoved=false;}
  _tourSel={mode:null,created:false,bounds:null};
}
// The selection demo needs an unobstructed map, so the group closes an open drawer on arrival. Whose
// drawer it was does not matter: the pre-tour snapshot puts a visitor's own drawer back on close, and
// stepping BACK re-opens the tour's own through the drawer step's idempotent enter.
function _tourEnterSelbox(){
  _tourEnterMapView();
  const dr=document.getElementById("drawer");
  if(dr&&dr.classList.contains("open")&&typeof closeDrawer==="function")closeDrawer();
  _tourOpened.drawer=false;
  _tourEnterSelectMode();
}
function _tourEnterSelectStep(){
  _tourEnterSelbox();
}
// Find demo. Save the visitor's own query, type the demo query and dispatch a REAL bubbling input event
// so the live wiring in filters.js (refresh() + renderFind()) filters the map and renders the actual
// dropdown: the demo is the real code path, not a mock. Exit restores the saved value the same way and
// hides the dropdown, matching the click-away behaviour.
let _tourFindPrev=null;              // visitor's Find value before the demo; null = nothing to restore
function _tourEnterFindDemo(){
  _tourEnterFilters();
  const f=document.getElementById("find");
  if(!f)return;
  if(_tourFindPrev===null)_tourFindPrev=f.value;
  f.value="AusLAMP";
  f.dispatchEvent(new Event("input",{bubbles:true}));
}
function _tourExitFindDemo(){
  const f=document.getElementById("find");
  if(!f||_tourFindPrev===null)return;
  f.value=_tourFindPrev;_tourFindPrev=null;
  f.dispatchEvent(new Event("input",{bubbles:true}));
  const fr=document.getElementById("findResults");
  if(fr){fr.style.display="none";fr.innerHTML="";}   // dropdown closed even when a query was restored
}
// Tree browse demo. Save the tree scroll AND the expand/collapse state, expand the demo survey's
// ancestors through the same treeSetCollapsed API the disclosure carets use (a collapsed rail must never
// hide the demo), then bring the row into view. No checkbox is touched. Exit puts back the saved
// scrollTop and the saved collapse set on all three ways out.
let _tourTreePrev=null;              // {scrollTop,collapsed[]} before the demo; null = nothing to restore
let _tourTreeTarget=null;            // resolved survey label; null = none resolved
function _tourEnterTreeDemo(){
  _tourEnterMapView();
  const tr=document.getElementById("tree");
  if(!tr)return;
  if(_tourTreePrev===null)_tourTreePrev={scrollTop:tr.scrollTop,
    collapsed:(typeof _treeCollapsed!=="undefined")?[..._treeCollapsed]:null};   // snapshot BEFORE expanding
  _tourTreeTarget=_tourDemoSurvey();
  if(!_tourTreeTarget)return;
  const box=[...tr.querySelectorAll('input[value]')].find(c=>c.value===_tourTreeTarget);
  if(box&&typeof treeSetCollapsed==="function"){
    treeSetCollapsed("c:"+box.dataset.country,false);
    treeSetCollapsed("o:"+box.dataset.org,false);
  }
  const row=box?box.closest("label"):null;
  // Guarded: a headless DOM has no scrollIntoView; in a browser it brings the row to the centre of the
  // scrollable tree. The resolution itself is the load-bearing half and is asserted separately.
  if(row&&typeof row.scrollIntoView==="function"){try{row.scrollIntoView({block:"center"});}catch(e){}}
}
function _tourExitTreeDemo(){
  const tr=document.getElementById("tree");
  if(tr&&_tourTreePrev!==null){
    tr.scrollTop=_tourTreePrev.scrollTop;
    if(_tourTreePrev.collapsed&&typeof _treeCollapsed!=="undefined"&&typeof applyTreeVisibility==="function"){
      _treeCollapsed.clear();_tourTreePrev.collapsed.forEach(k=>_treeCollapsed.add(k));applyTreeVisibility();
    }
  }
  _tourTreePrev=null;
}
// The station-drawer steps open the first visible station's drawer, the same as clicking its marker.
// Idempotent: arriving with that station already open re-selects the tab and opens nothing, so stepping
// back from the Files step does not rewrite the hash or reset the reader's scroll.
function _tourEnterStation(){
  _tourEnterMapView();
  if(typeof visible==="undefined"||!visible.length)return;
  const i=visible[0].i;
  const dr=document.getElementById("drawer");
  const wasOpen=!!(dr&&dr.classList.contains("open"));
  const onSubject=wasOpen&&typeof _drawerSubject!=="undefined"&&_drawerSubject&&
                  _drawerSubject.kind==="station"&&_drawerSubject.i===i;
  if(!onSubject){
    const prevHash=location.hash;
    openStation(i);
    if(!wasOpen)_tourOpened.drawer=true;
    if(_tourOpened.hash===null&&prevHash!==location.hash)_tourOpened.hash=prevHash;
  }
}
// The closing step: land back on the map with the drawer the tour opened closed and a tour-changed hash
// put back. The visitor's collapsed rail is NOT restored here: it belongs to the pre-tour snapshot, so a
// reader who steps BACK off this step still has a rail to read.
function _tourEnterFinal(){
  if(_tourOpened.drawer){closeDrawer();_tourOpened.drawer=false;}
  if(_tourOpened.hash!==null){history.replaceState(null,"",location.pathname+location.search+_tourOpened.hash);_tourOpened.hash=null;}
  _tourEnterMapView();
}
// ---- the pre-tour snapshot -------------------------------------------------------------------------
// The tour navigates, opens drawers, switches rail modes, forces a card layout, draws a shape and makes a
// selection. Undoing "only what the tour opened" cannot express that: it can restore a drawer and a hash,
// but it has nothing to say about a selection a filter change silently dropped, a card layout a step
// forced, or a map frame a fit moved. So the visitor's workspace is snapshotted ONCE at startTour and put
// back whole on stop, from any step. The snapshot is the authority; the group teardowns below exist for
// the boundaries the walk crosses while the tour is still running.
let _tourSnap=null;
let _tourMapMoved=false;             // whether the tour itself moved the map frame

// The card layout is read and written through the layout control itself, so the tour drives the same path
// a visitor's click does and never has to mirror the module's own layout state.
function _tourCardLayout(){
  const seg=document.getElementById("layoutSeg");
  const on=seg&&seg.querySelector?seg.querySelector("button.on"):null;
  return (on&&on.dataset&&on.dataset.layout)||null;
}
function _tourSetCardLayout(mode){
  if(!mode||_tourCardLayout()===mode)return;
  const seg=document.getElementById("layoutSeg");
  const b=seg&&seg.querySelector?seg.querySelector('[data-layout="'+mode+'"]'):null;
  if(b&&b.click)b.click();
}
function _tourMapBounds(){
  try{if(typeof map!=="undefined"&&map.getBounds)return map.getBounds();}catch(e){}
  return null;
}
function _tourFitBounds(b){
  if(!b)return;
  try{if(typeof map!=="undefined"&&map.fitBounds)map.fitBounds(b);}catch(e){}
}
function _tourDrawnLayers(){
  const out=[];
  try{if(typeof drawn!=="undefined"&&drawn.eachLayer)drawn.eachLayer(l=>out.push(l));}catch(e){}
  return out;
}
function _tourTakeSnapshot(){
  const dr=document.getElementById("drawer"),sb=document.querySelector("aside.filters");
  const tr=document.getElementById("tree"),f=document.getElementById("find");
  const adv=document.getElementById("advSearch");
  _tourSnap={
    view:(typeof curView!=="undefined")?curView:null,
    mode:(typeof sidebarMode!=="undefined")?sidebarMode:null,
    collapsed:!!(sb&&sb.classList.contains("collapsed")),
    layout:_tourCardLayout(),
    adv:!!(adv&&adv.open),
    drawerOpen:!!(dr&&dr.classList.contains("open")),
    drawerSubject:(typeof _drawerSubject!=="undefined"&&_drawerSubject)?_drawerSubject:null,
    drawerTab:(typeof _curDrawerTab!=="undefined")?_curDrawerTab:null,
    hash:location.hash,
    shapes:_tourDrawnLayers(),
    selected:(typeof selected!=="undefined")?[...selected]:[],
    bounds:_tourMapBounds(),
    find:f?f.value:null,
    treeScroll:tr?tr.scrollTop:0,
    treeCollapsed:(typeof _treeCollapsed!=="undefined")?[..._treeCollapsed]:null
  };
  _tourMapMoved=false;
}
// Put the visitor's own drawer back. A subject is re-opened through the same seam that opened it first,
// so the drawer's contents are re-rendered rather than restored from stale markup; the active tab is
// re-selected afterwards because opening a station resets it to the default panel.
function _tourRestoreDrawer(s){
  const dr=document.getElementById("drawer");
  const open=!!(dr&&dr.classList.contains("open"));
  if(!s.drawerOpen){if(open&&typeof closeDrawer==="function")closeDrawer();return;}
  const sub=s.drawerSubject;
  if(!sub)return;
  if(sub.kind==="station"&&typeof openStation==="function")openStation(sub.i);
  else if(sub.kind==="survey"&&typeof openSurvey==="function")openSurvey(sub.sv);
  if(s.drawerTab&&typeof selectDrawerTab==="function")selectDrawerTab(s.drawerTab);
}
// Restore order is load bearing: the query first (it drives refresh(), which re-derives the selection),
// then the tree, then the shapes and the selection, then the view (which closes any open drawer), then
// the drawer, and the hash LAST because opening or closing a drawer rewrites it.
function _tourRestoreSnapshot(){
  const s=_tourSnap;
  if(!s)return;
  _tourSnap=null;
  const f=document.getElementById("find");
  if(f&&s.find!==null&&f.value!==s.find){
    f.value=s.find;f.dispatchEvent(new Event("input",{bubbles:true}));
    const fr=document.getElementById("findResults");
    if(fr&&!s.find){fr.style.display="none";fr.innerHTML="";}
  }
  if(s.treeCollapsed&&typeof _treeCollapsed!=="undefined"&&typeof applyTreeVisibility==="function"){
    _treeCollapsed.clear();s.treeCollapsed.forEach(k=>_treeCollapsed.add(k));applyTreeVisibility();
  }
  const tr=document.getElementById("tree");if(tr)tr.scrollTop=s.treeScroll;
  const adv=document.getElementById("advSearch");if(adv)adv.open=s.adv;
  try{if(typeof drawn!=="undefined"&&drawn.clearLayers){drawn.clearLayers();s.shapes.forEach(l=>drawn.addLayer(l));}}catch(e){}
  if(typeof selected!=="undefined"){
    selected=new Set(s.selected);
    if(typeof updateSel==="function")updateSel();
  }
  _tourSetCardLayout(s.layout);
  // "collection" is a full-width detail page, not one of setView's three tab views; a visitor who was
  // reading one is returned to the map rather than to a view name setView cannot take.
  const wantView=(s.view==="map"||s.view==="surveys"||s.view==="collections")?s.view:"map";
  if(typeof setView==="function"&&typeof curView!=="undefined"&&curView!==wantView)setView(wantView);
  if(typeof setSidebarMode==="function"&&typeof sidebarMode!=="undefined"&&sidebarMode!==s.mode&&s.mode)setSidebarMode(s.mode);
  _tourRestoreDrawer(s);
  if(_tourMapMoved){_tourFitBounds(s.bounds);_tourMapMoved=false;}
  const sb=document.querySelector("aside.filters");
  if(sb&&typeof setSidebarCollapsed==="function"&&sb.classList.contains("collapsed")!==s.collapsed)
    setSidebarCollapsed(s.collapsed);
  if(location.hash!==s.hash)history.replaceState(null,"",location.pathname+location.search+s.hash);
  _tourOpened={drawer:false,hash:null};
}

function _tourBuild(){
  const backdrop=document.createElement("div");backdrop.className="tourbackdrop";backdrop.id="tourBackdrop";
  const spot=document.createElement("div");spot.className="tourspot";spot.id="tourSpot";
  // The LEADER is an SVG overlay spanning the viewport; a line + arrowhead connect the centred card to
  // the spotlight. Its z-order sits BETWEEN the spot (which carries the dim) and the card, so the line
  // reads over the dim and the card stays on top. The line element is held directly rather than looked
  // up, so it is robust in a DOM that does not render SVG; the arrowhead marker is cosmetics.
  const SVGNS="http://www.w3.org/2000/svg";
  const leader=document.createElementNS(SVGNS,"svg");
  leader.setAttribute("class","tourleader");leader.id="tourLeader";leader.setAttribute("aria-hidden","true");
  leader.innerHTML='<defs><marker id="tourLeaderHead" markerWidth="9" markerHeight="9" refX="7" refY="3" '+
    'orient="auto"><path d="M0,0 L7,3 L0,6 Z"></path></marker></defs>';
  const line=document.createElementNS(SVGNS,"line");line.setAttribute("id","tourLeaderLine");
  line.setAttribute("marker-end","url(#tourLeaderHead)");leader.appendChild(line);
  const card=document.createElement("div");card.className="tourcard";card.id="tourCard";
  card.setAttribute("role","dialog");card.setAttribute("aria-label","AusMT guided tour");
  card.innerHTML=
    '<div class="tourstep" id="tourStepLabel"></div>'+
    '<div class="tourtext" id="tourText"></div>'+
    '<div class="tourbtns">'+
      '<button type="button" id="tourBack" aria-label="Previous tour step">Back</button>'+
      '<button type="button" id="tourNext" class="tourprimary" aria-label="Next tour step">Next</button>'+
      '<button type="button" id="tourClose" aria-label="Close tour">Close</button>'+
    '</div>';
  document.body.appendChild(backdrop);document.body.appendChild(spot);
  document.body.appendChild(leader);document.body.appendChild(card);
  document.getElementById("tourBack").onclick=_tourPrev;
  document.getElementById("tourNext").onclick=_tourNext;
  document.getElementById("tourClose").onclick=stopTour;
  document.addEventListener("keydown",_tourKeydown);
  window.addEventListener("resize",_tourOnResize);
  return{backdrop,spot,leader,line,card};
}
// A viewport change re-runs only the LAYOUT, never the step's enter hook (which would re-run a demo).
function _tourOnResize(){if(_tourStep>=0)_tourLayout();}

// SETTLE-UNTIL-STABLE re-layout. Some steps' enter hooks trigger layout changes on their OWN target that
// keep going after _tourLayout first measures it. The station-drawer step is the worst case: openStation
// renders synchronously, then adds .open, which SLIDES the drawer in over a CSS transform transition so
// its left travels; then an async station.json fetch injects the frame line and reflows its HEIGHT; then
// a deferred map re-fit can reflow the map column under it. A single transitionend re-measure fires after
// the slide only and leaves the spotlight on a stale early box. So after entering a step, POLL the target
// rect each animation frame; on ANY change, position OR size (a size-only observer misses the slide,
// which MOVES the box), re-run _tourLayout; stop once the rect has held stable for _TOUR_SETTLE_STABLE_MS
// or after a hard _TOUR_SETTLE_CAP_MS. General, not a per-step special case: a static target reads stable
// on the first frame and the watcher stands down immediately. The transitionend hook is kept as a cheap
// extra nudge but is not relied on alone. The watcher is ATTACHED on arrival and DETACHED on EVERY
// departure, so no poll loop or listener leaks past the step or the tour. _tourLayoutRuns is bumped by
// _tourLayout purely so a driver can observe re-runs.
const _TOUR_SETTLE_STABLE_MS=200,_TOUR_SETTLE_CAP_MS=2000;   // quiet window the rect must hold; hard cap
let _tourSettleEl=null;                 // element the current step's watcher tracks; null = none attached
let _tourSettleRAF=0;                   // pending frame handle for the poll; 0 = none scheduled
let _tourLayoutRuns=0;                  // observability: total _tourLayout calls this session
function _tourNow(){return (typeof performance!=="undefined"&&performance.now)?performance.now():Date.now();}
// Compact position+size signature of an element's box; null when the element is gone. Captures BOTH a
// slide's travel and an async inject's height growth, so any reflow that moves OR resizes shows up.
function _tourRectKey(el){
  if(!el)return null;
  const r=el.getBoundingClientRect();
  return r.left+"|"+r.top+"|"+r.width+"|"+r.height;
}
function _tourOnSettle(){if(_tourStep>=0)_tourLayout();}   // re-measure the instant a transition ends
function _tourAttachSettle(){
  _tourDetachSettle();                  // never stack a watcher or listener across steps
  const target=_tourTarget(TOUR_STEPS[_tourStep]);
  if(!target)return;                    // no-target step: nothing to track
  _tourSettleEl=target;
  target.addEventListener("transitionend",_tourOnSettle);
  const start=_tourNow();
  let lastKey=_tourRectKey(target),stableSince=start;
  const tick=()=>{
    if(_tourStep<0||_tourSettleEl!==target)return;   // stepped away since this frame was queued
    _tourSettleRAF=0;
    const now=_tourNow();
    const key=_tourRectKey(target);
    if(key!==lastKey){                  // the box MOVED or RESIZED: re-measure against the new box
      lastKey=key;stableSince=now;
      _tourLayout();
    }
    if(now-stableSince>=_TOUR_SETTLE_STABLE_MS)return;   // settled: stop watching
    if(now-start>=_TOUR_SETTLE_CAP_MS)return;            // hard cap: never loop forever
    _tourSettleRAF=requestAnimationFrame(tick);
  };
  _tourSettleRAF=requestAnimationFrame(tick);
}
function _tourDetachSettle(){
  if(_tourSettleRAF){cancelAnimationFrame(_tourSettleRAF);_tourSettleRAF=0;}
  if(_tourSettleEl){_tourSettleEl.removeEventListener("transitionend",_tourOnSettle);_tourSettleEl=null;}
}

function _tourKeydown(e){
  if(_tourStep<0)return;
  if(e.key==="Escape"){stopTour();}
  else if(e.key==="ArrowRight"){_tourNext();}
  else if(e.key==="ArrowLeft"){_tourPrev();}
}

// The tour card is CENTRED for EVERY step. This PURE fn returns the card's fixed-position box. Base = the
// viewport centre. OVERLAP RULE: when a target rect would sit under the centred card, nudge the card by
// the MINIMAL vertical offset so it clears the target by _TOUR_CLEAR, deterministically DOWNWARD when
// that still fits the viewport (bottom margin _TOUR_M), else UPWARD. No DOM, so the geometry is testable
// on synthetic rects in a DOM with no layout engine.
const _TOUR_M=8,_TOUR_CLEAR=16;   // viewport margin; target->card clearance on an overlap nudge
function _tourCardBox(cardW,cardH,vpW,vpH,targetRect){
  const M=_TOUR_M,CLEAR=_TOUR_CLEAR;
  const left=Math.round((vpW-cardW)/2),baseTop=Math.round((vpH-cardH)/2);
  let top=baseTop;
  if(targetRect){
    const overlaps=!(left+cardW<=targetRect.left||left>=targetRect.right||
                     baseTop+cardH<=targetRect.top||baseTop>=targetRect.bottom);
    if(overlaps){
      const down=Math.round(targetRect.bottom+CLEAR),up=Math.round(targetRect.top-CLEAR-cardH);
      // Prefer downward; upward only when downward will not fit; when NEITHER fits (a target too tall to
      // clear vertically) stay centred, because an on-screen card over the target beats one off screen.
      top=(down+cardH<=vpH-M)?down:(up>=M?up:baseTop);
    }
  }
  return{left,top,right:left+cardW,bottom:top+cardH,nudged:top!==baseTop};
}
// Geometry of the LEADER from the centred card to the spotlight. PURE: the endpoints are the boundary
// points where the card-centre to spot-centre axis crosses each rect, so the line leaves the card edge
// nearest the target and lands on the spot edge nearest the card. visible is false when suppressed: the
// map steps (where the spotlight over the map IS the cue) and the no-target fallback.
function _tourLeader(cardBox,spotBox,suppressed){
  if(suppressed)return{x1:0,y1:0,x2:0,y2:0,visible:false};
  const ccx=(cardBox.left+cardBox.right)/2,ccy=(cardBox.top+cardBox.bottom)/2;
  const scx=(spotBox.left+spotBox.right)/2,scy=(spotBox.top+spotBox.bottom)/2;
  const dx=scx-ccx,dy=scy-ccy;
  if(dx===0&&dy===0)return{x1:ccx,y1:ccy,x2:scx,y2:scy,visible:false};   // concentric: impossible once nudged clear
  const edge=(cx,cy,hw,hh,vx,vy)=>{                                      // boundary point from a centre along (vx,vy)
    const t=Math.min(vx!==0?hw/Math.abs(vx):Infinity,vy!==0?hh/Math.abs(vy):Infinity);
    return[cx+vx*t,cy+vy*t];
  };
  const[x1,y1]=edge(ccx,ccy,(cardBox.right-cardBox.left)/2,(cardBox.bottom-cardBox.top)/2,dx,dy);
  const[x2,y2]=edge(scx,scy,(spotBox.right-spotBox.left)/2,(spotBox.bottom-spotBox.top)/2,-dx,-dy);
  return{x1,y1,x2,y2,visible:true};
}
// Arrival at a step: run its enter hook (which may switch view / open a drawer and so change the target
// rect), THEN lay the spotlight + card out. Split from _tourLayout so a resize re-lays-out WITHOUT
// re-firing the enter hook.
function _tourPosition(){
  const step=TOUR_STEPS[_tourStep];
  if(typeof step.enter==="function")step.enter();
  _tourLayout();
  _tourAttachSettle();   // then WATCH the target's box until it settles
}
function _tourLayout(){
  _tourLayoutRuns++;
  const step=TOUR_STEPS[_tourStep];
  const target=_tourTarget(step);
  const rect=target?target.getBoundingClientRect():null;
  const hasTarget=!!(rect&&(rect.width>0||rect.height>0));
  const isMapStep=step.sel==="#map";                       // the map is the backdrop: the spotlight alone is the cue
  const{spot,card,backdrop,leader,line}=_tourEls;
  const cardW=card.offsetWidth||340,cardH=card.offsetHeight||160;   // fall back where there is no layout engine
  // The overlap nudge applies to DISCRETE targets only. A map step's target is the whole map, so it never
  // nudges: the card centres over the map spotlight, and the leader is suppressed there anyway.
  const box=_tourCardBox(cardW,cardH,window.innerWidth,window.innerHeight,(hasTarget&&!isMapStep)?rect:null);
  card.style.left=box.left+"px";card.style.top=box.top+"px";
  if(!hasTarget){
    // Target absent: centred card, no spotlight, no leader; the backdrop carries the dim itself.
    spot.style.display="none";
    if(leader)leader.style.display="none";
    backdrop.style.background="rgba(11,15,18,"+TOUR_DIM+")";
  }else{
    // Targeted step: the spot's box-shadow supplies the dim and the backdrop stays transparent, so the
    // spotlighted element shows fully through the cutout.
    backdrop.style.background="transparent";
    spot.style.display="block";
    const pad=6;
    spot.style.top=Math.max(0,rect.top-pad)+"px";
    spot.style.left=Math.max(0,rect.left-pad)+"px";
    spot.style.width=(rect.width+pad*2)+"px";
    spot.style.height=(rect.height+pad*2)+"px";
    spot.style.boxShadow="0 0 0 4000px rgba(11,15,18,"+TOUR_DIM+")";
    const spotBox={left:rect.left-pad,top:rect.top-pad,right:rect.right+pad,bottom:rect.bottom+pad};
    const ld=_tourLeader(box,spotBox,isMapStep);
    if(leader&&line){
      if(ld.visible){
        leader.style.display="block";
        line.setAttribute("x1",ld.x1);line.setAttribute("y1",ld.y1);
        line.setAttribute("x2",ld.x2);line.setAttribute("y2",ld.y2);
      }else leader.style.display="none";
    }
  }
  document.getElementById("tourStepLabel").textContent="Step "+(_tourStep+1)+" of "+TOUR_STEPS.length;
  document.getElementById("tourText").textContent=_tourText(step);
  document.getElementById("tourBack").disabled=(_tourStep===0);
  document.getElementById("tourNext").textContent=(_tourStep===TOUR_STEPS.length-1)?"Done":"Next";
}

// Run the CURRENT step's exit hook (if any) before leaving it, on Next, Back and stopTour, so a demo
// step's own cleanup runs on every possible way out.
function _tourExitCurrent(){
  const s=TOUR_STEPS[_tourStep];
  if(s&&typeof s.exit==="function")s.exit();
  _tourDetachSettle();   // drop this step's settle watcher on every way out, symmetric with attach
}
// Group cleanup: run the owning group's teardown when, and only when, the move crosses its boundary.
// `to` is -1 for stopTour, which leaves every group.
function _tourCrossGroups(from,to){
  if(_tourInSelectGroup(from)&&!_tourInSelectGroup(to))_tourLeaveSelectGroup();
}
function _tourGo(to){
  const from=_tourStep;
  _tourExitCurrent();
  _tourCrossGroups(from,to);
  _tourStep=to;_tourPosition();
}
function _tourNext(){
  if(_tourStep>=TOUR_STEPS.length-1){stopTour();return;}   // stopTour runs the exit hook itself
  _tourGo(_tourStep+1);
}
function _tourPrev(){
  if(_tourStep<=0)return;
  _tourGo(_tourStep-1);
}

function startTour(){
  if(_tourStep>=0)return;              // already running
  if(!TOUR_STEPS.length)return;
  _tourOpened={drawer:false,hash:null};
  _tourFindPrev=null;_tourTreePrev=null;_tourTreeTarget=null;
  _tourSel={mode:null,created:false,bounds:null};
  _tourDemoSv=undefined;               // resolve the demo subjects afresh against the loaded corpus
  _tourTakeSnapshot();                 // the workspace the visitor is handed back on close, from any step
  // A COLLAPSED rail hides every child but the collapse button, so the rail steps would spotlight nothing
  // and narrate controls that are not on screen. Expand it for the run; the snapshot above already holds
  // the visitor's own choice, so the restore puts it back.
  const _sb=document.querySelector("aside.filters");
  if(_sb&&_sb.classList.contains("collapsed")&&typeof setSidebarCollapsed==="function")setSidebarCollapsed(false);
  _tourEls=_tourBuild();
  _tourStep=0;_tourPosition();
}
function stopTour(){
  if(_tourStep<0)return;
  const from=_tourStep;
  _tourExitCurrent();                  // a demo step's cleanup runs on mid-tour close too
  _tourCrossGroups(from,-1);           // every group's teardown, from any step
  _tourStep=-1;
  document.removeEventListener("keydown",_tourKeydown);
  window.removeEventListener("resize",_tourOnResize);
  _tourRestoreSnapshot();              // the visitor's whole pre-tour workspace, field for field
  if(_tourEls){
    _tourEls.backdrop.remove();_tourEls.spot.remove();_tourEls.leader.remove();_tourEls.card.remove();
    _tourEls=null;
  }
}
