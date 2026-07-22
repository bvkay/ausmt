"use strict";
// tour.js — 10-step spotlight tour (UX feedback rounds 1 + 2 + UX4 D5). Classic script, zero deps,
// loads LAST (after main.js) so it can call setView()/openStation()/other globals, but nothing in
// main.js depends on it (a missing/broken tour.js must never break the intro panel or the app — see
// the typeof guard in main.js).
//
// Behaviour: never auto-starts (only "Take the tour" in the intro panel or the header link fires
// it); steps whose target element is absent (e.g. empty-data state, or an enter action that found
// nothing to open) render centred with no spotlight instead of crashing or silently skipping; Esc
// closes; ArrowRight/ArrowLeft navigate; all controls are real <button>s with aria-labels; nothing is
// persisted — the tour is stateless and re-runnable from either entry point on every visit.
//
// Round 2 (operator feedback): the tour now NAVIGATES — it spotlights the header view buttons and
// actually switches to the Surveys view, then returns to the map at the end, so a first-timer learns
// the app's two views by watching them happen. Enter actions (run when the tour ARRIVES at a step,
// forward or back) make that work in both directions: map-view steps force the map view back (so
// stepping BACK from the Surveys steps re-shows map-only targets like .selbox). _tourOpened records
// ONLY what the tour itself opened (drawer / hash), so stopTour() from ANY step — including
// mid-Surveys — returns to the map and closes only tour-opened drawers, never state the visitor had
// open before starting.
//
// UX4 D5 (owner, 2026-07-07): two DEMO steps after the filter-rail overview — Find (types "AusLAMP"
// with a real input event so the live dropdown + map filter run) and tree browse (scrolls one survey
// row into view; kalkaroo-2022 preferred, first survey otherwise). Demo steps get an EXIT hook, run
// on ALL three ways of leaving a step (Next, Back, and stopTour for close/Esc/Done), so demo state
// (the typed query, the tree scroll) never leaks past the step — the same restore discipline as
// _tourOpened, extended per-step.
// UX7b U11 (owner, 2026-07-13): shortened step copy — the visible text is the architect-authored deck,
// VERBATIM. Selectors + enter/exit hooks are UNCHANGED (the Find demo still types "AusLAMP", the selbox
// step still switches rail mode, etc. — only the visible copy changed).
const TOUR_STEPS=[
  {sel:"#map",text:"Every dot is an MT station. Click one to see its transfer function.",
   enter:_tourEnterMapView},
  {sel:"aside.filters",text:"Filter by data type, or draw an area on the map. More filters live under Screening (advanced)."},
  {sel:"#find",text:"Search stations, surveys or collections. Results update as you type.",
   enter:_tourEnterFindDemo,exit:_tourExitFindDemo},
  {sel:"#tree",text:"Browse by country, organisation or survey. Tick a level to show or hide it.",
   enter:_tourEnterTreeDemo,exit:_tourExitTreeDemo},
  {sel:"#drawer",text:"The station drawer: response plots and provenance, in tabs.",
   enter:_tourEnterStation},
  {sel:".selbox",text:"Download stations, surveys or selections. Licences and citations come with the files.",
   enter:_tourEnterSelbox,exit:_tourExitSelbox},
  {sel:"#navSurveys",text:"Surveys lists every survey as a card. Let's look."},
  {sel:"#cardGrid .scard",text:"Each card is a survey at a glance. Open it for the full record.",
   enter:_tourEnterSurveysView},
  {sel:"#navMap",text:"Map brings you back to the stations."},
  {sel:"#map",text:"That's it: find, screen, download, cite. Contribute your own survey from Add Survey.",
   enter:_tourEnterMap}
];

// U10: overlay dim, raised from 0.65 to 0.78 (+13pp). Single source of truth, applied inline by
// _tourLayout — on a targeted step it colours the spot's box-shadow (leaving the backdrop transparent so
// the cutout shows the element fully); on a no-target step it colours the centred backdrop directly.
const TOUR_DIM=0.78;

let _tourStep=-1,_tourEls=null;
// What THIS tour run has itself opened, so stopTour() undoes only that (not pre-existing visitor state).
let _tourOpened={drawer:false,hash:null,view:null};

// Steps 1/4 enter action: make sure the MAP view is showing. Forward this is a no-op; its real job
// is BACKWARD navigation from the Surveys steps (6-7), where map-only targets (.selbox, the map
// itself) would otherwise be display:none and every earlier step would fall back to a centred card.
function _tourEnterMapView(){
  if(typeof curView!=="undefined"&&curView!=="map"&&typeof setView==="function")setView("map");
}
// Step 6 enter action: actually switch to the Surveys view — the navigation IS the lesson. setView
// closes any open drawer itself; _tourOpened.drawer is left as-is because closeDrawer() is a safe
// no-op double-close at restore time.
function _tourEnterSurveysView(){
  if(typeof curView!=="undefined"&&curView!=="surveys"&&typeof setView==="function")setView("surveys");
}
// UX6 Wave D (D2 follow-up): the .selbox step's target lives in the rail's Select & export mode pane,
// which is hidden in the default Browse mode (zero rect => the step would fall back to the centred
// no-spotlight card). Enter: force the map view, save the visitor's rail mode, and switch to
// Select & export so the target is visible and spotlit. Exit (Next/Back/close — the same three-path
// discipline as the Find/tree demos): put the saved mode back, so the tour never leaks a mode change.
// Guarded so a build without the D2 mode split degrades to the old centred-card behaviour, no crash.
let _tourSelPrevMode=null;           // rail mode before the selbox step; null = nothing to restore
function _tourEnterSelbox(){
  _tourEnterMapView();
  if(typeof setSidebarMode!=="function"||typeof sidebarMode==="undefined")return;
  if(_tourSelPrevMode===null)_tourSelPrevMode=sidebarMode;
  setSidebarMode("select");
}
function _tourExitSelbox(){
  if(_tourSelPrevMode===null)return;
  if(typeof setSidebarMode==="function")setSidebarMode(_tourSelPrevMode);
  _tourSelPrevMode=null;
}
// UX4 D5 Find demo. Enter: save the visitor's own query (restore discipline — only undo what the
// tour did), type "AusLAMP" and dispatch a REAL bubbling input event so the live wiring in filters.js
// (refresh() + renderFind()) filters the map and renders the actual dropdown — the demo is the real
// code path, not a mock. Exit: restore the saved value with another input event (so the filter state
// is genuinely restored) and hide the dropdown, matching the click-away behaviour in filters.js.
let _tourFindPrev=null;              // visitor's Find value before the demo; null = nothing to restore
function _tourEnterFindDemo(){
  _tourEnterMapView();
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
  if(fr){fr.style.display="none";fr.innerHTML="";}   // dropdown closed on exit even if a query was restored (click-away state)
}
// UX4 D5 tree browse demo (+ UX5 D8: rides the disclosure carets). Enter: save the tree scroll AND
// the expand/collapse state, EXPAND the target row's ancestors (country + org, via the same
// treeSetCollapsed API the carets use — a collapsed rail must never hide the demo), then bring the
// row into view — kalkaroo-2022 preferred (via SLUG_TO_SURVEY, the authoritative slug->label map),
// degrading to the FIRST survey present so a data-dependent id can never crash the tour (empty
// portal: no-op, step renders centred per the absent-target pattern). No checkbox is touched. Exit:
// put back the saved scrollTop and the saved collapse set — on all three exit paths (Next/Back/close).
let _tourTreePrev=null;              // {scrollTop,collapsed[]} before the demo; null = nothing to restore
let _tourTreeTarget=null;            // resolved survey label (exposed to the jsdom driver; null = none)
function _tourEnterTreeDemo(){
  _tourEnterMapView();
  const tr=document.getElementById("tree");
  if(!tr)return;
  if(_tourTreePrev===null)_tourTreePrev={scrollTop:tr.scrollTop,
    collapsed:(typeof _treeCollapsed!=="undefined")?[..._treeCollapsed]:null};   // snapshot BEFORE expanding
  _tourTreeTarget=(typeof SLUG_TO_SURVEY!=="undefined"&&SLUG_TO_SURVEY["kalkaroo-2022"])||
                  (typeof surveys!=="undefined"&&surveys.length?surveys[0]:null);
  if(!_tourTreeTarget)return;
  const box=[...tr.querySelectorAll('input[value]')].find(c=>c.value===_tourTreeTarget);
  if(box&&typeof treeSetCollapsed==="function"){                                 // UX5 D8: ancestors expanded
    treeSetCollapsed("c:"+box.dataset.country,false);
    treeSetCollapsed("o:"+box.dataset.org,false);
  }
  const row=box?box.closest("label"):null;
  // scrollIntoView is guarded: jsdom doesn't implement it (the driver still asserts the RESOLUTION);
  // in the real browser it brings the row to the centre of the scrollable tree.
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
// Station-drawer step enter action: open the first VISIBLE station's drawer (reuse openStation), same
// as clicking its marker — forcing the map view first so it also works stepping back from the Surveys
// steps. No-op (step renders centred, no spotlight) when nothing is visible — e.g. the empty-data
// state or every station filtered out — matching the existing "absent target" pattern below.
function _tourEnterStation(){
  _tourEnterMapView();
  if(typeof visible==="undefined"||!visible.length)return;
  const wasOpen=document.getElementById("drawer").classList.contains("open");
  const prevHash=location.hash;
  openStation(visible[0].i);
  if(!wasOpen)_tourOpened.drawer=true;
  if(prevHash!==location.hash)_tourOpened.hash=prevHash;   // remember what to restore, not just "changed"
}
// Step 8 enter action: close whatever drawer the tour opened and land back on the map — the loop's
// closing beat. Uses the same restore path as stopTour() so behaviour is identical whether a visitor
// reaches step 8 by stepping through or jumps back to it.
function _tourEnterMap(){
  _tourRestore();
}
// Shared restore: closes a tour-opened drawer, puts back a tour-changed hash, and returns to the map
// view — but ONLY undoes state _tourOpened recorded as the tour's own doing.
function _tourRestore(){
  if(_tourOpened.drawer){closeDrawer();_tourOpened.drawer=false;}
  if(_tourOpened.hash!==null){history.replaceState(null,"",location.pathname+location.search+_tourOpened.hash);_tourOpened.hash=null;}
  if(typeof curView!=="undefined"&&curView!=="map"&&typeof setView==="function")setView("map");
}

function _tourBuild(){
  const backdrop=document.createElement("div");backdrop.className="tourbackdrop";backdrop.id="tourBackdrop";
  const spot=document.createElement("div");spot.className="tourspot";spot.id="tourSpot";
  // UX9 (owner): the LEADER is an SVG overlay spanning the viewport; a line + arrowhead connect the centred
  // card to the spotlight. Its z-order sits BETWEEN the spot (which carries the dim) and the card (see CSS),
  // so the line reads over the dim and the card stays on top. The line element is held directly (not looked
  // up) so it is robust in jsdom, which does not render SVG; the arrowhead marker is browser-only cosmetics.
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
      // U9: the primary advance button carries .tourprimary (copper fill, dark text).
      '<button type="button" id="tourNext" class="tourprimary" aria-label="Next tour step">Next</button>'+
      '<button type="button" id="tourClose" aria-label="Close tour">Close</button>'+
    '</div>';
  document.body.appendChild(backdrop);document.body.appendChild(spot);
  document.body.appendChild(leader);document.body.appendChild(card);
  document.getElementById("tourBack").onclick=_tourPrev;
  document.getElementById("tourNext").onclick=_tourNext;
  document.getElementById("tourClose").onclick=stopTour;
  document.addEventListener("keydown",_tourKeydown);
  window.addEventListener("resize",_tourOnResize);                     // UX9: re-centre + redraw the leader on resize
  return{backdrop,spot,leader,line,card};
}
// UX9: re-run only the LAYOUT (not the step's enter hook) when the viewport changes while the tour is open —
// the card re-centres and the leader is recomputed; the card never re-anchors (it is always centred).
function _tourOnResize(){if(_tourStep>=0)_tourLayout();}

// SETTLE-UNTIL-STABLE re-layout (owner, 2026-07-22). Some steps' enter hooks trigger layout changes on their
// OWN target that keep going AFTER _tourLayout first measures it. The station-drawer step (index 4) is the
// worst case: openStation (a) renders the facts panel synchronously, then adds .open, which (b) SLIDES the
// drawer in via a CSS transform transition (index.html: transform translateX(102%) -> none, .16s ease) so its
// getBoundingClientRect().left travels leftward over ~160ms; then (c) an ASYNC station.json fetch injects the
// frame line (drawer.js loadStationFrameLine) and reflows the drawer's HEIGHT; and (d) the deferred map home
// re-fit can reflow the map column under it. The drawer box therefore MOVES and RESIZES several times across
// ~1s. A single transitionend re-measure fires after the SLIDE only (stage b) and leaves the spotlight on a
// stale early box (the owner-observed "highlight lands where the panel first appeared, now empty"). The robust
// fix: after entering a step, POLL the target rect each animation frame; on ANY change — position OR size (a
// size-only ResizeObserver misses the slide, which MOVES the box) — re-run _tourLayout so the spotlight tracks
// the box; stop once the rect has held STABLE for _TOUR_SETTLE_STABLE_MS, or after a hard _TOUR_SETTLE_CAP_MS.
// General, not a step-5 special case: a static target reads stable on the first frame and the watcher stands
// down immediately; the map steps re-measure an unchanging box harmlessly. The transitionend hook is KEPT as
// a cheap extra nudge (it re-lays-out the instant a transition ends) but is no longer relied on alone. The
// watcher is ATTACHED on arrival and DETACHED on EVERY departure (Next/Back/close/teardown) — the rAF handle
// is cancelled and the listener removed — so no poll loop or listener leaks past the step or the tour.
// jsdom has no layout engine and its rAF is driver-controllable, so the pin drives synthetic rect changes +
// a stubbed clock through the queue to prove the re-run/stop/detach wiring; the sub-second proof is a browser
// run. _tourLayoutRuns is bumped by _tourLayout purely so the pin (and the browser probe) can observe re-runs.
const _TOUR_SETTLE_STABLE_MS=200,_TOUR_SETTLE_CAP_MS=2000;   // quiet window the rect must hold; hard time cap
let _tourSettleEl=null;                 // element the current step's settle watcher tracks; null = none attached
let _tourSettleRAF=0;                   // pending animation-frame handle for the poll; 0 = none scheduled
let _tourLayoutRuns=0;                  // observability: total _tourLayout calls this session (settle-pin observable)
function _tourNow(){return (typeof performance!=="undefined"&&performance.now)?performance.now():Date.now();}
// Compact position+size signature of an element's box; null when the element is gone. Captures BOTH the
// slide's left travel and the frame-line inject's height growth, so any reflow that moves OR resizes shows up.
function _tourRectKey(el){
  if(!el)return null;
  const r=el.getBoundingClientRect();
  return r.left+"|"+r.top+"|"+r.width+"|"+r.height;
}
function _tourOnSettle(){if(_tourStep>=0)_tourLayout();}   // transitionend nudge — re-measure the instant a transition ends
function _tourAttachSettle(){
  _tourDetachSettle();                  // never stack a watcher or listener across steps
  const step=TOUR_STEPS[_tourStep];
  const target=step&&step.sel?document.querySelector(step.sel):null;
  if(!target)return;                    // no-target step (absent element / centred fallback): nothing to track
  _tourSettleEl=target;
  target.addEventListener("transitionend",_tourOnSettle);
  const start=_tourNow();
  let lastKey=_tourRectKey(target),stableSince=start;
  const tick=()=>{
    if(_tourStep<0||_tourSettleEl!==target)return;   // stepped away / closed since this frame was queued — stand down, touch nothing
    _tourSettleRAF=0;
    const now=_tourNow();
    const key=_tourRectKey(target);
    if(key!==lastKey){                  // the box MOVED or RESIZED — re-measure the spotlight against the new box
      lastKey=key;stableSince=now;
      _tourLayout();
    }
    if(now-stableSince>=_TOUR_SETTLE_STABLE_MS)return;   // settled: the rect held for the quiet window -> stop watching
    if(now-start>=_TOUR_SETTLE_CAP_MS)return;            // hard cap -> stop even if it is still twitching (never loop forever)
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

// UX9 (owner): the tour card is CENTRED for EVERY step (the pattern formerly used only as the no-target
// fallback, now generalised). This PURE fn returns the card's fixed-position box. Base = the viewport
// centre. OVERLAP RULE: when a target rect would sit under the centred card, nudge the card by the MINIMAL
// vertical offset so it clears the target by _TOUR_CLEAR — deterministically DOWNWARD when that still fits
// the viewport (bottom margin _TOUR_M), else UPWARD. No-DOM so the driver pins centred-always + the nudge on
// synthetic rects (jsdom has no layout engine), exactly as the retired _tourPlace was.
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
      // prefer downward; upward only when downward won't fit; if NEITHER fits (a target too tall to clear
      // vertically) stay centred — an on-screen card over the target beats one nudged off the viewport.
      top=(down+cardH<=vpH-M)?down:(up>=M?up:baseTop);
    }
  }
  return{left,top,right:left+cardW,bottom:top+cardH,nudged:top!==baseTop};
}
// UX9 (owner): geometry of the LEADER from the centred card to the spotlight. PURE — the endpoints are the
// boundary points where the card-centre<->spot-centre axis crosses each rect, so the line leaves the card
// edge nearest the target and lands on the spot edge nearest the card (arrowhead at the spot end). visible
// is false when suppressed — the map steps (the spotlight over the map IS the cue) and the no-target
// fallback. No-DOM so the driver pins the endpoints + suppression on synthetic rects.
function _tourLeader(cardBox,spotBox,suppressed){
  if(suppressed)return{x1:0,y1:0,x2:0,y2:0,visible:false};
  const ccx=(cardBox.left+cardBox.right)/2,ccy=(cardBox.top+cardBox.bottom)/2;
  const scx=(spotBox.left+spotBox.right)/2,scy=(spotBox.top+spotBox.bottom)/2;
  const dx=scx-ccx,dy=scy-ccy;
  if(dx===0&&dy===0)return{x1:ccx,y1:ccy,x2:scx,y2:scy,visible:false};   // concentric — impossible once nudged clear
  const edge=(cx,cy,hw,hh,vx,vy)=>{                                      // boundary point from a centre along (vx,vy)
    const t=Math.min(vx!==0?hw/Math.abs(vx):Infinity,vy!==0?hh/Math.abs(vy):Infinity);
    return[cx+vx*t,cy+vy*t];
  };
  const[x1,y1]=edge(ccx,ccy,(cardBox.right-cardBox.left)/2,(cardBox.bottom-cardBox.top)/2,dx,dy);
  const[x2,y2]=edge(scx,scy,(spotBox.right-spotBox.left)/2,(spotBox.bottom-spotBox.top)/2,-dx,-dy);
  return{x1,y1,x2,y2,visible:true};
}
// Arrival at a step: run its enter hook (which may switch view / open a drawer and so change the target
// rect), THEN lay the spotlight + card + caret out. Split from _tourLayout so a resize re-lays-out WITHOUT
// re-firing the enter hook (which would re-run a demo action).
function _tourPosition(){
  const step=TOUR_STEPS[_tourStep];
  if(typeof step.enter==="function")step.enter();
  _tourLayout();
  _tourAttachSettle();   // then WATCH the target's box: re-measure through the slide + async re-renders until it settles
}
function _tourLayout(){
  _tourLayoutRuns++;
  const step=TOUR_STEPS[_tourStep];
  const target=step.sel?document.querySelector(step.sel):null;
  const rect=target?target.getBoundingClientRect():null;
  const hasTarget=!!(rect&&(rect.width>0||rect.height>0));
  const isMapStep=step.sel==="#map";                       // the map is the backdrop — the spotlight alone is the cue, no leader
  const{spot,card,backdrop,leader,line}=_tourEls;
  // The card is CENTRED for EVERY step (fixed-position, computed by _tourCardBox), nudged clear of the
  // target if it would sit under it. It never re-anchors to a side; a resize only re-centres + redraws.
  const cardW=card.offsetWidth||340,cardH=card.offsetHeight||160;   // fall back when there's no layout engine (jsdom)
  // The overlap nudge applies to DISCRETE targets only. A map step's target is the whole map (the backdrop),
  // so it never nudges — the card centres over the map spotlight; the leader is suppressed there anyway.
  const box=_tourCardBox(cardW,cardH,window.innerWidth,window.innerHeight,(hasTarget&&!isMapStep)?rect:null);
  card.style.left=box.left+"px";card.style.top=box.top+"px";
  if(!hasTarget){
    // Target absent (empty-data state, or an enter action found nothing to open): centred card, no
    // spotlight, no leader — the backdrop carries the dim itself (U10).
    spot.style.display="none";
    if(leader)leader.style.display="none";
    backdrop.style.background="rgba(11,15,18,"+TOUR_DIM+")";
  }else{
    // Targeted step: the spot's box-shadow supplies the dim (U10) and the backdrop stays transparent, so
    // the spotlighted element shows fully through the cutout.
    backdrop.style.background="transparent";
    spot.style.display="block";
    const pad=6;
    spot.style.top=Math.max(0,rect.top-pad)+"px";
    spot.style.left=Math.max(0,rect.left-pad)+"px";
    spot.style.width=(rect.width+pad*2)+"px";
    spot.style.height=(rect.height+pad*2)+"px";
    spot.style.boxShadow="0 0 0 4000px rgba(11,15,18,"+TOUR_DIM+")";
    // Leader from the centred card to the spotlight — suppressed on the map steps (TOUR_STEPS 0 and 9).
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
  document.getElementById("tourText").textContent=step.text;
  document.getElementById("tourBack").disabled=(_tourStep===0);
  document.getElementById("tourNext").textContent=(_tourStep===TOUR_STEPS.length-1)?"Done":"Next";
}

// UX4 D5: run the CURRENT step's exit hook (if any) before leaving it — called on Next, Back and
// stopTour, so a demo step's cleanup runs on every possible way out (forward, backward, close/Esc).
function _tourExitCurrent(){
  const s=TOUR_STEPS[_tourStep];
  if(s&&typeof s.exit==="function")s.exit();
  _tourDetachSettle();   // drop this step's settle watcher + listener on every way out (Next/Back/close) — symmetric with attach
}
function _tourNext(){
  if(_tourStep>=TOUR_STEPS.length-1){stopTour();return;}   // stopTour runs the exit hook itself
  _tourExitCurrent();
  _tourStep++;_tourPosition();
}
function _tourPrev(){
  if(_tourStep<=0)return;
  _tourExitCurrent();
  _tourStep--;_tourPosition();
}

function startTour(){
  if(_tourStep>=0)return;              // already running
  if(!TOUR_STEPS.length)return;
  _tourOpened={drawer:false,hash:null,view:null};
  _tourFindPrev=null;_tourTreePrev=null;_tourTreeTarget=null;_tourSelPrevMode=null;   // D5/D2 demo state: fresh every run
  _tourEls=_tourBuild();
  _tourStep=0;_tourPosition();
}
function stopTour(){
  if(_tourStep<0)return;
  _tourExitCurrent();                  // D5: a demo step's cleanup runs on mid-tour close too
  _tourStep=-1;
  document.removeEventListener("keydown",_tourKeydown);
  window.removeEventListener("resize",_tourOnResize);   // U8: stop tracking the viewport once the tour closes
  _tourRestore();                      // Done/Esc/close from ANY step: restore only what the tour itself changed
  if(_tourEls){
    _tourEls.backdrop.remove();_tourEls.spot.remove();_tourEls.leader.remove();_tourEls.card.remove();
    _tourEls=null;
  }
}
