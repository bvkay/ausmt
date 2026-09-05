"use strict";
// tour.js - the guided spotlight tour, a classic script loaded LAST so it may call the app's seams while
// nothing depends on it. Every constraint the deck keeps is stated once in the docs. See docs: portal internals, tour.js.

// The demo survey the copy prefers and the size below which a survey is too small for the demo. Both are
// preferences: the resolver degrades to the largest positioned survey, then to nothing. See docs: portal internals, tour.js.
const TOUR_DEMO_SLUG="vulcan-2022",TOUR_DEMO_MIN=5;
// The station id the drawer steps prefer within the demo survey. A preference, not a requirement: a
// survey without it opens on its first positioned station instead.
const TOUR_DEMO_STATION="A1";

// The deck: `sel` is a static selector so a step spotlights the same element from either direction, and
// `text` is the copy verbatim with {survey} and {n} resolved at render. See docs: portal internals, tour.js.
const TOUR_STEPS=[
  {sel:"#map",
   text:"Every dot is an MT station. Click one to see its transfer function.",
   enter:_tourEnterOpening},
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
   enter:_tourEnterFiles,exit:_tourExitFiles},
  {sel:".selbox",
   text:"Select stations: draw an area, or take everything that passes the filters.",
   enter:_tourEnterSelbox},
  {sel:"#map",
   text:"Selecting in action: zoom to {survey}, draw a rectangle, and every station inside is selected - {n} here.",
   enter:_tourEnterSelectDemo},
  {sel:"#dlLevel2",
   text:"Level 2 transfer functions, served by AusMT: EDI, EMTF XML and MTH5 zips for your selection.",
   enter:_tourEnterSelectDownload},
  {sel:"#dlTimeSeries",
   text:"Time series at NCI: download lists by level, handed off through an AusMT redirect. Metadata and citations follow below.",
   enter:_tourEnterSelectDownload},
  {sel:"#navSurveys",
   text:"Surveys: every survey with its coverage, years, periods, licence and downloads, as cards or a compact list.",
   enter:_tourEnterMapView},
  {sel:"#navCollections",
   text:"Collections: related surveys grouped, such as AusLAMP and the Australia legacy GDS, each with its combined coverage.",
   enter:_tourEnterMapView},
  {sel:"#map",
   text:"That's it: find, screen, select, download, cite. Contribute your own survey from Contribute a survey.",
   enter:_tourEnterFinal}
];

// The SELECT group: the steps that share the select rail mode, the demo rectangle and the demo selection.
// The group owns that state, established on entering any member and cleaned up only when the walk leaves. See docs: portal internals, tour.js.
const _TOUR_SELECT_GROUP=[6,7,8,9];
function _tourInSelectGroup(i){return _TOUR_SELECT_GROUP.indexOf(i)>=0;}

// Overlay dim, applied inline by _tourLayout: a targeted step colours the spot's box-shadow (the backdrop
// stays transparent); a no-target step colours the centred backdrop.
const TOUR_DIM=0.78;

let _tourStep=-1,_tourEls=null;
// What THIS run has itself opened, so the CLOSING STEP undoes only that and not pre-existing visitor
// state. Closing the tour is a different question and is answered by the pre-tour snapshot below.
let _tourOpened={drawer:false,hash:null};
// The demo subjects resolved once per run (the corpus cannot change mid-run) and cleared on stop.
let _tourDemoSv=undefined;

// ---- demo resolution ----
// Every step that would otherwise name a survey resolves one from the loaded corpus: the preferred slug,
// else the first survey large enough for the demo, else the largest positioned survey, else nothing. See docs: portal internals, tour.js.
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
// The station the drawer steps open, an index into ST resolved from the CORPUS, not the filtered map: the
// preferred station, else the first positioned, else the first visible, else -1. See docs: portal internals, tour.js.
let _tourDemoIdx=undefined;
function _tourDemoStation(){
  if(_tourDemoIdx!==undefined)return _tourDemoIdx;
  _tourDemoIdx=-1;
  if(typeof ST==="undefined")return _tourDemoIdx;
  const sv=_tourDemoSurvey();
  if(sv){
    let i=ST.findIndex(s=>s.survey===sv&&s.id===TOUR_DEMO_STATION&&hasPosition(s));
    if(i<0)i=ST.findIndex(s=>s.survey===sv&&hasPosition(s));
    if(i>=0){_tourDemoIdx=ST[i].i;return _tourDemoIdx;}
  }
  if(typeof visible!=="undefined"&&visible.length)_tourDemoIdx=visible[0].i;
  return _tourDemoIdx;
}
// The count the selection-demo copy prints: whatever the demo rectangle actually took, never a literal.
// Before the demo is applied the rectangle's membership is the same number. See docs: portal internals, tour.js.
function _tourDemoCount(){
  if(!_tourSel.created&&_tourSel.bounds)return _tourRectMembers(_tourSel.bounds).length;
  return (typeof selected!=="undefined")?selected.size:0;
}
// Render a step's copy. The placeholders resolve to the empty-corpus wording when nothing resolved, so
// the sentence stays grammatical rather than showing a token.
function _tourText(step){
  let t=step.text;
  if(t.indexOf("{survey}")>=0)t=t.split("{survey}").join(_tourDemoSurvey()||"a survey");
  if(t.indexOf("{n}")>=0)t=t.split("{n}").join(String(_tourDemoCount()));
  return t;
}
// The element a step spotlights. May be null, which is the centred no-spotlight state.
function _tourTarget(step){
  return (step&&step.sel)?document.querySelector(step.sel):null;
}

// ---- enter hooks ----
// The bare view switch, without the map steps' extra housekeeping below. The drawer steps use this one:
// they are ABOUT the drawer, so they must not close it on arrival.
function _tourMapView(){
  if(typeof curView!=="undefined"&&curView!=="map"&&typeof setView==="function")setView("map");
}
// Close a drawer THIS RUN opened. A visitor's own drawer is left where it is: the pre-tour snapshot puts
// it back on close, and closing it here would be the tour undoing something it never did.
function _tourCloseOwnDrawer(){
  if(!_tourOpened.drawer)return;
  _tourOpened.drawer=false;
  if(typeof closeDrawer==="function")closeDrawer();
}
// Map-view steps: no step leaves the map, so the view switch only serves a visitor who started elsewhere.
// The drawer close keeps the map unobstructed when stepping back. See docs: portal internals, tour.js.
function _tourEnterMapView(){
  _tourMapView();
  _tourCloseOwnDrawer();
}
// The opening step: the map housekeeping above plus Advanced search CLOSED, so it reads the same arriving
// forward or backward. The visitor's own accordion is in the snapshot. See docs: portal internals, tour.js.
function _tourEnterOpening(){
  _tourEnterMapView();
  const adv=document.getElementById("advSearch");if(adv)adv.open=false;
}
// The BROWSE group: the rail steps whose targets live in the rail's Browse pane, hidden when the visitor
// left the rail in Select mode. Their mode is group state on the same terms as the select steps'.
const _TOUR_BROWSE_GROUP=[1,2,3];
function _tourInBrowseGroup(i){return _TOUR_BROWSE_GROUP.indexOf(i)>=0;}
let _tourBrowse={mode:null};
function _tourEnterBrowseMode(){
  if(typeof setSidebarMode!=="function"||typeof sidebarMode==="undefined")return;
  if(_tourBrowse.mode===null)_tourBrowse.mode=sidebarMode;
  if(sidebarMode!=="browse")setSidebarMode("browse");
}
function _tourLeaveBrowseGroup(){
  if(_tourBrowse.mode!==null&&typeof setSidebarMode==="function")setSidebarMode(_tourBrowse.mode);
  _tourBrowse={mode:null};
}
// The filter-rail overview: the rail's Advanced search accordion lives in the Browse pane and is opened so
// the controls the copy names are on screen. Idempotent (details.open is a set, not a toggle).
function _tourEnterFilters(){
  _tourEnterMapView();
  _tourEnterBrowseMode();
  const adv=document.getElementById("advSearch");if(adv)adv.open=true;
}
// The select group's shared state: the rail mode, the demo rectangle and the demo selection. The visitor's
// mode is captured on entering and restored on leaving; `created` marks the tour's own selection. See docs: portal internals, tour.js.
let _tourSel={mode:null,created:false,bounds:null,dimmed:false};
function _tourEnterSelectMode(){
  if(typeof setSidebarMode!=="function"||typeof sidebarMode==="undefined")return;
  if(_tourSel.mode===null)_tourSel.mode=sidebarMode;
  if(sidebarMode!=="select")setSidebarMode("select");
}
function _tourLeaveSelectGroup(){
  if(_tourSel.created){
    try{if(typeof drawn!=="undefined"&&drawn.clearLayers)drawn.clearLayers();}catch(e){}
    if(typeof selected!=="undefined"){selected.clear();if(typeof updateSel==="function")updateSel();}
  }
  if(_tourSel.dimmed&&typeof clearSurveyDim==="function")clearSurveyDim();
  if(_tourSel.mode!==null&&typeof setSidebarMode==="function")setSidebarMode(_tourSel.mode);
  if(_tourMapMoved&&_tourSnap){_tourFitBounds(_tourSnap.bounds);_tourMapMoved=false;}
  _tourSel={mode:null,created:false,bounds:null,dimmed:false};
}
// The selection demo needs an unobstructed map, so the group closes an open drawer on arrival. The
// snapshot puts a visitor's own drawer back on close; stepping BACK re-opens the tour's own.
function _tourEnterSelbox(){
  _tourEnterMapView();
  const dr=document.getElementById("drawer");
  if(dr&&dr.classList.contains("open")&&typeof closeDrawer==="function")closeDrawer();
  _tourOpened.drawer=false;
  _tourEnterSelectMode();
}

// ---- the selection demo ----
// The demo frames the demo survey, grows a rectangle over it and leaves the stations inside selected. It
// never arms the real draw handler; every frame and timer is registered. See docs: portal internals, tour.js.
const TOUR_RECT_PAD=0.1,TOUR_RECT_MIN_PAD=0.01;      // rectangle padding: 10 percent of span, with a floor
// How far inside the margin that would first admit a neighbour the chosen margin sits. Containment is
// inclusive, so the admitting margin is itself unusable and a fraction of a hair below it is the answer.
const TOUR_RECT_GAP=0.99;
// Phase durations: the whole demo is about two seconds, long enough to read as an action and short enough
// not to invite Next. The fit wait resolves on the map's own moveend. See docs: portal internals, tour.js.
const TOUR_ANIM={fit:450,glide:420,press:110,grow:780,fade:120};
const TOUR_RECT_STYLE={color:"#EF7256",weight:2};                                  // matches a hand-drawn shape
const TOUR_PREVIEW_STYLE={color:"#EF7256",weight:2,dashArray:"6 5",fill:false};    // the growing outline

let _tourAnim={raf:0,timers:[],cursor:null,layer:null,rect:null,seq:0};
function _tourAnimPending(){
  return{raf:_tourAnim.raf!==0,timers:_tourAnim.timers.length,cursor:!!_tourAnim.cursor,
    layer:!!_tourAnim.layer,running:_tourAnim.raf!==0||_tourAnim.timers.length>0};
}
function _tourAnimTimer(fn,ms){
  const id=setTimeout(()=>{
    const k=_tourAnim.timers.indexOf(id);if(k>=0)_tourAnim.timers.splice(k,1);
    fn();
  },ms);
  _tourAnim.timers.push(id);
  return id;
}
// Cancel everything the demo has in flight. Bumping the sequence invalidates any callback already queued,
// so a frame or timer that fires between the clear and its own removal stands down instead of acting on a
// step that has been left.
function _tourAnimCancel(){
  _tourAnim.seq++;
  _tourAnim.timers.forEach(clearTimeout);_tourAnim.timers=[];
  if(_tourAnim.raf){cancelAnimationFrame(_tourAnim.raf);_tourAnim.raf=0;}
  if(_tourAnim.cursor){_tourAnim.cursor.remove();_tourAnim.cursor=null;}
  if(_tourAnim.layer){try{if(typeof map!=="undefined"&&map.removeLayer)map.removeLayer(_tourAnim.layer);}catch(e){}_tourAnim.layer=null;}
  _tourAnim.rect=null;
  const btn=document.getElementById("drawRect");
  if(btn&&btn.classList)btn.classList.remove("armed");
}
function _tourInstant(){
  if(typeof window!=="undefined"&&window.AUSMT_TOUR_INSTANT===true)return true;
  try{return !!(window.matchMedia&&window.matchMedia("(prefers-reduced-motion: reduce)").matches);}catch(e){return false;}
}
// The rectangle's margin, as a fraction of the demo survey's extent: the largest fraction up to
// TOUR_RECT_PAD that admits no station of any other survey, never below the floor. See docs: portal internals, tour.js.
function _tourRectMargin(sv,south,north,west,east){
  if(typeof visible==="undefined")return TOUR_RECT_PAD;
  const h=north-south,w=east-west;
  let first=Infinity;
  visible.forEach(s=>{
    if(s.survey===sv||!hasPosition(s))return;
    const dLat=Math.max(0,south-s.lat,s.lat-north),dLon=Math.max(0,west-s.lon,s.lon-east);
    const fLat=(TOUR_RECT_MIN_PAD>=dLat)?0:(h>0?dLat/h:Infinity);
    const fLon=(TOUR_RECT_MIN_PAD>=dLon)?0:(w>0?dLon/w:Infinity);
    const f=Math.max(fLat,fLon);
    if(f<first)first=f;
  });
  return Math.min(TOUR_RECT_PAD,first*TOUR_RECT_GAP);
}
// The demo rectangle: the demo survey's positioned extent, padded so every station is inside rather than
// on the edge. The floor keeps a one-station or one-line survey from producing a degenerate box.
function _tourDemoBounds(){
  const sv=_tourDemoSurvey();
  if(!sv||typeof ST==="undefined")return null;
  const pts=ST.filter(s=>s.survey===sv&&hasPosition(s));
  if(!pts.length)return null;
  const lats=pts.map(s=>s.lat),lons=pts.map(s=>s.lon);
  const south=Math.min(...lats),north=Math.max(...lats),west=Math.min(...lons),east=Math.max(...lons);
  const m=_tourRectMargin(sv,south,north,west,east);
  const padLat=Math.max((north-south)*m,TOUR_RECT_MIN_PAD);
  const padLon=Math.max((east-west)*m,TOUR_RECT_MIN_PAD);
  return{south:south-padLat,north:north+padLat,west:west-padLon,east:east+padLon};
}
// The rectangle's membership over the CURRENTLY VISIBLE stations, which is what a drawn shape selects.
// Axis-aligned, so this is the same answer the shape layer's point-in-polygon test gives for this box.
function _tourRectMembers(b){
  if(!b||typeof visible==="undefined")return[];
  return visible.filter(s=>hasPosition(s)&&s.lat>=b.south&&s.lat<=b.north&&s.lon>=b.west&&s.lon<=b.east)
                .map(s=>s.i);
}
function _tourFocusDemo(){
  const sv=_tourDemoSurvey();
  if(!sv||typeof focusSurvey!=="function")return;
  focusSurvey(sv);
  _tourMapMoved=true;_tourSel.dimmed=true;
}
// The end state, applied the way a completed draw applies one. The demo's selection IS the rectangle's
// membership, applied directly where no shape layer carried it. See docs: portal internals, tour.js.
function _tourApplyDemo(b){
  if(!b)return;
  try{
    if(typeof drawn!=="undefined"&&drawn.clearLayers)drawn.clearLayers();
    if(typeof L!=="undefined"&&L.rectangle&&typeof drawn!=="undefined"&&drawn.addLayer){
      const rect=L.rectangle([[b.south,b.west],[b.north,b.east]],TOUR_RECT_STYLE);
      if(rect&&rect.options)rect.options.interactive=false;
      drawn.addLayer(rect);
    }
  }catch(e){}
  if(typeof refresh==="function")refresh();
  if(typeof hasShapes!=="function"||!hasShapes()){
    if(typeof selected!=="undefined"){
      selected=new Set(_tourRectMembers(b));
      if(typeof updateSel==="function")updateSel();
    }
  }
  if(typeof setSidebarMode==="function")setSidebarMode("select");
  _tourSel.created=true;_tourSel.bounds=b;
  if(typeof toast==="function"&&typeof drawSelectionMsg==="function")
    toast(drawSelectionMsg(_tourDemoCount(),"rectangle"));
}
// ---- the animation ----
function _tourFrames(ms,onFrame,onDone){
  const start=_tourNow(),seq=_tourAnim.seq;
  const tick=()=>{
    _tourAnim.raf=0;
    if(_tourStep<0||_tourAnim.seq!==seq)return;
    const t=ms>0?Math.min(1,(_tourNow()-start)/ms):1;
    onFrame(t);
    if(t<1){_tourAnim.raf=requestAnimationFrame(tick);return;}
    if(onDone)onDone();
  };
  _tourAnim.raf=requestAnimationFrame(tick);
}
function _tourCursorMake(){
  const c=document.createElement("div");
  c.className="tourcursor";c.id="tourCursor";c.setAttribute("aria-hidden","true");
  c.innerHTML='<svg viewBox="0 0 16 20" width="16" height="20"><path d="M1 1 L1 16 L5 12 L8 19 L11 18 L8 11 L14 11 Z"></path></svg>';
  document.body.appendChild(c);
  _tourAnim.cursor=c;
  return c;
}
function _tourCursorAt(c,p){if(c&&p){c.style.left=Math.round(p.x)+"px";c.style.top=Math.round(p.y)+"px";}}
function _tourPointOf(el){
  if(!el||!el.getBoundingClientRect)return null;
  const r=el.getBoundingClientRect();
  return{x:r.left+r.width/2,y:r.top+r.height/2};
}
// A latitude/longitude as a viewport point. Falls back to the map's centre wherever the projection is
// unavailable, so the glyph always has somewhere real to be and the demo never fails on the geometry.
function _tourMapPoint(lat,lng){
  const el=document.getElementById("map");
  const r=el&&el.getBoundingClientRect?el.getBoundingClientRect():null;
  try{
    if(typeof map!=="undefined"&&map.latLngToContainerPoint&&typeof L!=="undefined"&&L.latLng&&r){
      const p=map.latLngToContainerPoint(L.latLng(lat,lng));
      const x=Number(p&&p.x),y=Number(p&&p.y);
      if(isFinite(x)&&isFinite(y))return{x:r.left+x,y:r.top+y};
    }
  }catch(e){}
  return r?{x:r.left+r.width/2,y:r.top+r.height/2}:{x:0,y:0};
}
function _tourGlide(c,from,to,ms,done){
  if(!from||!to){if(done)done();return;}
  _tourFrames(ms,t=>{
    const e=t<0.5?2*t*t:1-Math.pow(-2*t+2,2)/2;                     // ease in and out, so the move reads
    _tourCursorAt(c,{x:from.x+(to.x-from.x)*e,y:from.y+(to.y-from.y)*e});
  },done);
}
function _tourPreviewMake(){
  try{
    if(typeof L==="undefined"||!L.layerGroup||typeof map==="undefined")return null;
    const g=L.layerGroup();
    if(g&&g.addTo)g.addTo(map);
    _tourAnim.layer=g;return g;
  }catch(e){return null;}
}
// One rectangle, RESHAPED each frame. Rebuilding the shape per frame re-adds a layer to the map on every
// tick, which on a large corpus costs a full re-draw of the canvas the station dots share.
function _tourPreviewDraw(g,bb){
  try{
    if(!g)return;
    const ll=[[bb.south,bb.west],[bb.north,bb.east]];
    if(_tourAnim.rect&&_tourAnim.rect.setBounds){_tourAnim.rect.setBounds(ll);return;}
    const r=L.rectangle(ll,TOUR_PREVIEW_STYLE);
    if(r&&r.options)r.options.interactive=false;
    if(g.addLayer)g.addLayer(r);
    _tourAnim.rect=r;
  }catch(e){}
}
// The map's own fit animates, so the demo waits for it before moving the cursor. Bounded: a map that
// never reports the move (a stubbed or already-settled map) still proceeds on the timer.
function _tourWaitFit(cb){
  let done=false;
  const finish=()=>{
    if(done)return;done=true;
    try{if(typeof map!=="undefined"&&map.off)map.off("moveend",finish);}catch(e){}
    cb();
  };
  try{if(typeof map!=="undefined"&&map.once)map.once("moveend",finish);}catch(e){}
  _tourAnimTimer(finish,TOUR_ANIM.fit);
}
function _tourRunDemo(b){
  _tourAnimCancel();
  _tourSel.bounds=b;                 // the copy states the rectangle's count from the first frame
  const seq=_tourAnim.seq;
  const alive=()=>_tourStep>=0&&_tourAnim.seq===seq;
  _tourFocusDemo();
  const c=_tourCursorMake();
  _tourCursorAt(c,_tourMapPoint((b.south+b.north)/2,(b.west+b.east)/2));
  const btn=document.getElementById("drawRect");
  _tourWaitFit(()=>{
    if(!alive())return;
    const btnPt=_tourPointOf(btn)||_tourMapPoint(b.north,b.west);
    _tourGlide(c,_tourPointOf(document.getElementById("map"))||btnPt,btnPt,TOUR_ANIM.glide,()=>{
      if(!alive())return;
      if(c.classList)c.classList.add("press");
      if(btn&&btn.classList)btn.classList.add("armed");
      _tourAnimTimer(()=>{
        if(!alive())return;
        if(c.classList)c.classList.remove("press");
        const nw=_tourMapPoint(b.north,b.west);
        _tourGlide(c,btnPt,nw,TOUR_ANIM.glide,()=>{
          if(!alive())return;
          const g=_tourPreviewMake();
          _tourFrames(TOUR_ANIM.grow,t=>{
            const bb={north:b.north,west:b.west,
                      south:b.north+(b.south-b.north)*t,east:b.west+(b.east-b.west)*t};
            _tourPreviewDraw(g,bb);
            _tourCursorAt(c,_tourMapPoint(bb.south,bb.east));   // the glyph rides the moving corner
          },()=>{
            if(!alive())return;
            _tourFinishDemo(b,c);
          });
        });
      },TOUR_ANIM.press);
    });
  });
}
function _tourFinishDemo(b,c){
  if(_tourAnim.layer){
    try{if(typeof map!=="undefined"&&map.removeLayer)map.removeLayer(_tourAnim.layer);}catch(e){}
    _tourAnim.layer=null;
  }
  _tourAnim.rect=null;
  const btn=document.getElementById("drawRect");
  if(btn&&btn.classList)btn.classList.remove("armed");
  _tourApplyDemo(b);
  if(c){
    if(c.classList)c.classList.add("out");
    _tourAnimTimer(()=>{if(_tourAnim.cursor===c){c.remove();_tourAnim.cursor=null;}},TOUR_ANIM.fade);
  }
  if(_tourStep>=0&&_tourEls)_tourLayout();   // the copy prints the count the selection actually has
}
// The demo step. Idempotent: arriving with the demo already established changes nothing, so stepping
// back into it neither replays the animation nor re-derives the selection.
function _tourEnterSelectDemo(){
  _tourEnterSelbox();
  if(_tourSel.created)return;
  const b=_tourDemoBounds();
  if(!b)return;                              // no positioned survey: the step renders its copy, no demo
  if(_tourInstant()){_tourFocusDemo();_tourApplyDemo(b);return;}
  _tourRunDemo(b);
}
// The download steps live inside the same group and need the same selection, but they never animate:
// arriving at one backwards from outside the group re-creates the end state directly.
function _tourEnterSelectDownload(){
  _tourEnterSelbox();
  if(_tourSel.created)return;
  const b=_tourDemoBounds();
  if(!b)return;
  _tourFocusDemo();
  _tourApplyDemo(b);
}
// Find demo: save the visitor's query, type the demo query and dispatch a real input event so the live
// wiring filters the map. Exit restores the saved value and hides the dropdown. See docs: portal internals, tour.js.
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
// Tree browse demo: save the tree scroll and collapse state, expand the demo survey's ancestors and bring
// the row into view. Exit restores both on every way out; no checkbox is touched. See docs: portal internals, tour.js.
let _tourTreePrev=null;              // {scrollTop,collapsed[]} before the demo; null = nothing to restore
let _tourTreeTarget=null;            // resolved survey label; null = none resolved
function _tourEnterTreeDemo(){
  _tourEnterMapView();
  _tourEnterBrowseMode();
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
// The station-drawer steps open the demo station's drawer idempotently: arriving with it open opens nothing.
// The tab is re-selected in both cases, so this step establishes the Response tab. See docs: portal internals, tour.js.
function _tourEnterStation(){
  _tourMapView();
  const i=_tourDemoStation();
  if(i<0)return;
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
  _tourSelectTab("response");
}
// Drive the drawer's own tab control where one is rendered, so the tour takes the path a reader's click
// takes; fall back to the module seam when the drawer is shut and there is only tab STATE to set.
function _tourSelectTab(name){
  const b=document.getElementById("dt-"+name);
  if(b&&b.click&&typeof _curDrawerTab!=="undefined"&&_curDrawerTab!==name){b.click();return;}
  if(typeof selectDrawerTab==="function"&&typeof _curDrawerTab!=="undefined"&&_curDrawerTab!==name)selectDrawerTab(name);
}
// The Files step: the same station, its Files pane showing. Leaving it in EITHER direction returns the
// drawer to the Response tab, so the drawer step is never re-entered on a panel it did not establish.
function _tourEnterFiles(){
  _tourEnterStation();
  _tourSelectTab("files");
}
function _tourExitFiles(){
  _tourSelectTab("response");
}
// The closing step: back on the map, the tour's drawer closed and a tour-changed hash put back. The
// visitor's collapsed rail belongs to the snapshot, so a reader who steps BACK still has a rail to read.
function _tourEnterFinal(){
  _tourCloseOwnDrawer();
  if(_tourOpened.hash!==null){history.replaceState(null,"",location.pathname+location.search+_tourOpened.hash);_tourOpened.hash=null;}
  _tourMapView();
}
// ---- the pre-tour snapshot ----
// The visitor's workspace is snapshotted ONCE at startTour and put back whole on stop, from any step. The
// group teardowns cover only the boundaries crossed while the tour runs. See docs: portal internals, tour.js.
let _tourSnap=null;
let _tourMapMoved=false;             // whether the tour itself moved the map frame

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
// Put the visitor's own drawer back through the seam that opened it first, so its contents are
// re-rendered rather than restored from stale markup; the tab is re-selected afterwards.
function _tourRestoreDrawer(s){
  const dr=document.getElementById("drawer");
  const open=!!(dr&&dr.classList.contains("open"));
  if(!s.drawerOpen){
    if(open&&typeof closeDrawer==="function")closeDrawer();
    // The active tab is state even with nothing open: the Files step sets it, so it is put back here too.
    if(s.drawerTab&&typeof selectDrawerTab==="function")selectDrawerTab(s.drawerTab);
    return;
  }
  const sub=s.drawerSubject;
  if(!sub)return;
  if(sub.kind==="station"&&typeof openStation==="function")openStation(sub.i);
  else if(sub.kind==="survey"&&typeof openSurvey==="function")openSurvey(sub.sv);
  if(s.drawerTab&&typeof selectDrawerTab==="function")selectDrawerTab(s.drawerTab);
}
// Restore order is load bearing: the query first (it drives refresh()), then the tree, the shapes and
// the selection, the view (which closes any drawer), the drawer, and the hash LAST.
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
  // The LEADER is an SVG overlay spanning the viewport: a line and arrowhead connect the centred card to the
  // spotlight, layered between the spot and the card. The line element is held directly, so a DOM that does
  // not render SVG cannot break it. See docs: portal internals, tour.js.
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

// SETTLE-UNTIL-STABLE re-layout: the target rect is polled each frame and _tourLayout re-run on any change
// until it holds stable or the cap passes. Detached on every departure. See docs: portal internals, tour.js.
const _TOUR_SETTLE_STABLE_MS=200,_TOUR_SETTLE_CAP_MS=2000;   // quiet window the rect must hold; hard cap
let _tourSettleEl=null;                 // element the current step's watcher tracks; null = none attached
let _tourSettleRAF=0;                   // pending frame handle for the poll; 0 = none scheduled
let _tourLayoutRuns=0;                  // observability: total _tourLayout calls this session
function _tourNow(){return (typeof performance!=="undefined"&&performance.now)?performance.now():Date.now();}
// Compact position+size signature of an element's box; null when the element is absent. Captures BOTH a
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

// The tour card is CENTRED for EVERY step; this PURE fn returns its box. A card that would cover its target
// is nudged by the minimal vertical offset, downward when that fits, else upward. See docs: portal internals, tour.js.
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
// Geometry of the LEADER from the centred card to the spotlight, PURE: the endpoints are where the
// centre-to-centre axis crosses each rect. visible is false on the map steps and the no-target fallback. See docs: portal internals, tour.js.
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
// The containers whose content SCROLLS: a target inside one can sit outside its visible part, and a spotlight
// measured there lands on empty space. The containers themselves are not in this class. See docs: portal internals, tour.js.
const TOUR_SCROLLERS="aside.filters,#drawer,.tree";
// Bring a target inside a scroller into view before the layout measures it; "nearest" is the smallest scroll
// that makes it visible. Guarded, since a headless DOM has no scrollIntoView. See docs: portal internals, tour.js.
function _tourScrollIntoView(el){
  if(!el||!el.parentElement||typeof el.parentElement.closest!=="function")return;
  if(!el.parentElement.closest(TOUR_SCROLLERS))return;
  if(typeof el.scrollIntoView!=="function")return;
  try{el.scrollIntoView({block:"nearest"});}catch(e){}
}
// Arrival at a step: run its enter hook, bring the target into view where it lives in a scroller, THEN
// lay the spotlight and card out. Split from _tourLayout so a resize never re-fires the enter hook.
function _tourPosition(){
  const step=TOUR_STEPS[_tourStep];
  if(typeof step.enter==="function")step.enter();
  _tourScrollIntoView(_tourTarget(step));
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
  _tourAnimCancel();     // no frame or timer of the selection demo outlives the step that started it
  _tourDetachSettle();   // drop this step's settle watcher on every way out, symmetric with attach
}
// Group cleanup: run the owning group's teardown when, and only when, the move crosses its boundary.
// `to` is -1 for stopTour, which leaves every group.
function _tourCrossGroups(from,to){
  if(_tourInBrowseGroup(from)&&!_tourInBrowseGroup(to))_tourLeaveBrowseGroup();
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
  _tourSel={mode:null,created:false,bounds:null,dimmed:false};
  _tourBrowse={mode:null};
  _tourDemoSv=undefined;_tourDemoIdx=undefined;   // resolve the demo subjects afresh against the loaded corpus
  _tourTakeSnapshot();                 // the workspace the visitor is handed back on close, from any step
  // A COLLAPSED rail hides every child but the collapse button, so the rail steps would spotlight nothing.
  // Expand it for the run; the snapshot holds the visitor's own choice and the restore puts it back.
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
