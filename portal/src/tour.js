"use strict";
// Tour.js - 11-step spotlight tour. See docs: portal internals, tour.js.
const TOUR_STEPS=[
  {sel:"#map",text:"Every dot is an MT station. Click one to see its transfer function.",
   enter:_tourEnterMapView},
  {sel:"aside.filters",text:"Filter by data type; Advanced search adds find, data availability and year range."},
  {sel:"#find",text:"Search stations, surveys or collections. Results update as you type.",
   enter:_tourEnterFindDemo,exit:_tourExitFindDemo},
  {sel:"#tree",text:"Browse by country, organisation or survey. Tick a level to show or hide it.",
   enter:_tourEnterTreeDemo,exit:_tourExitTreeDemo},
  {sel:"#drawer",text:"The station drawer: response plots and provenance, in tabs.",
   enter:_tourEnterStation},
  {sel:".selbox",text:"Select stations: draw an area, or take everything that passes the filters.",
   enter:_tourEnterSelbox,exit:_tourExitSelbox},
  {sel:".dlbox",text:"Download prices every product for your selection: zips served by AusMT, time series handed to NCI, metadata and citations below.",
   enter:_tourEnterSelbox,exit:_tourExitSelbox},
  {sel:"#navSurveys",text:"Surveys lists every survey as a card. Let's look."},
  {sel:"#cardGrid .scard",text:"Each card is a survey at a glance. Open it for the full record.",
   enter:_tourEnterSurveysView},
  {sel:"#navMap",text:"Map brings you back to the stations."},
  {sel:"#map",text:"That's it: find, screen, download, cite. Contribute your own survey from Add Survey.",
   enter:_tourEnterMap}
];

// Overlay dim, raised from 0.65 to 0.78 (+13pp). Single source of truth, applied inline by
// _tourLayout — on a targeted step it colours the spot's box-shadow (leaving the backdrop transparent so
// the cutout shows the element fully); on a no-target step it colours the centred backdrop directly.
const TOUR_DIM=0.78;

let _tourStep=-1,_tourEls=null;
// What THIS tour run has itself opened, so stopTour() undoes only that (not pre-existing visitor state).
let _tourOpened={drawer:false,hash:null,view:null,collapsed:false};

// Enter action for the map-view steps: make sure the MAP view is showing. Forward this is a no-op; its
// real job is BACKWARD navigation from the Surveys steps, where map-only targets (.selbox, the map
// itself) would otherwise be display:none and every earlier step would fall back to a centred card.
function _tourEnterMapView(){
  if(typeof curView!=="undefined"&&curView!=="map"&&typeof setView==="function")setView("map");
}
// Surveys-view step enter action. Named by SELECTOR, not by index: a step inserted mid-deck left every
// numbered comment in this file one behind, so the numbers are gone. See docs: portal internals, tour.js.
function _tourEnterSurveysView(){
  if(typeof curView!=="undefined"&&curView!=="surveys"&&typeof setView==="function")setView("surveys");
}
// The .selbox step's target lives in the rail's Select & download mode pane, which is hidden in the default
// Browse mode (zero rect => the step would fall back to the centred no-spotlight card). See docs: portal
// internals, tour.js.
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
// Find demo. See docs: portal internals, tour.js.
let _tourFindPrev=null;              // visitor's Find value before the demo; null = nothing to restore
function _tourEnterFindDemo(){
  _tourEnterMapView();
  // Find lives inside the Advanced search accordion; the tour opens it so the spotlit target is
  // visible (the exit hook leaves it open - closing would yank the panel out from under the reader).
  const adv=document.getElementById("advSearch");if(adv)adv.open=true;
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
// Tree browse demo. See docs: portal internals, tour.js.
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
  if(box&&typeof treeSetCollapsed==="function"){                                 // the ancestors must be expanded
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
// Station-drawer step enter action: open the first VISIBLE station's drawer (reuse openStation), same as
// clicking its marker - forcing the map view first so it also works stepping back from the Surveys steps.
// See docs: portal internals, tour.js.
function _tourEnterStation(){
  _tourEnterMapView();
  if(typeof visible==="undefined"||!visible.length)return;
  const wasOpen=document.getElementById("drawer").classList.contains("open");
  const prevHash=location.hash;
  openStation(visible[0].i);
  if(!wasOpen)_tourOpened.drawer=true;
  if(prevHash!==location.hash)_tourOpened.hash=prevHash;   // remember what to restore, not just "changed"
}
// Final map step enter action (by selector, not index): close whatever drawer the tour opened and land back
// on the map. The loop's closing beat. See docs: portal internals, tour.js.
function _tourEnterMap(){
  _tourRestore();
}
// Shared restore: closes a tour-opened drawer, puts back a tour-changed hash, and returns to the map
// view — but ONLY undoes state _tourOpened recorded as the tour's own doing.
function _tourRestore(){
  if(_tourOpened.collapsed){                     // put the visitor's own collapsed rail back (see startTour)
    if(typeof setSidebarCollapsed==="function")setSidebarCollapsed(true);
    _tourOpened.collapsed=false;
  }
  if(_tourOpened.drawer){closeDrawer();_tourOpened.drawer=false;}
  if(_tourOpened.hash!==null){history.replaceState(null,"",location.pathname+location.search+_tourOpened.hash);_tourOpened.hash=null;}
  if(typeof curView!=="undefined"&&curView!=="map"&&typeof setView==="function")setView("map");
}

function _tourBuild(){
  const backdrop=document.createElement("div");backdrop.className="tourbackdrop";backdrop.id="tourBackdrop";
  const spot=document.createElement("div");spot.className="tourspot";spot.id="tourSpot";
  // The LEADER is an SVG overlay spanning the viewport; a line + arrowhead connect the centred card to the
  // spotlight. Its z-order sits BETWEEN the spot (which carries the dim) and the card (see CSS), so the
  // line reads over the dim and the card stays on top. See docs: portal internals, tour.js.
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
      // The primary advance button carries .tourprimary (copper fill, dark text).
      '<button type="button" id="tourNext" class="tourprimary" aria-label="Next tour step">Next</button>'+
      '<button type="button" id="tourClose" aria-label="Close tour">Close</button>'+
    '</div>';
  document.body.appendChild(backdrop);document.body.appendChild(spot);
  document.body.appendChild(leader);document.body.appendChild(card);
  document.getElementById("tourBack").onclick=_tourPrev;
  document.getElementById("tourNext").onclick=_tourNext;
  document.getElementById("tourClose").onclick=stopTour;
  document.addEventListener("keydown",_tourKeydown);
  window.addEventListener("resize",_tourOnResize);                     // re-centre + redraw the leader on resize
  return{backdrop,spot,leader,line,card};
}
// Re-run only the LAYOUT (not the step's enter hook) when the viewport changes while the tour is open -
// the card re-centres and the leader is recomputed; the card never re-anchors (it is always centred).
function _tourOnResize(){if(_tourStep>=0)_tourLayout();}

// SETTLE-UNTIL-STABLE re-layout. Some steps' enter hooks trigger layout changes on their OWN target that
// keep going AFTER _tourLayout first measures it. See docs: portal internals, tour.js.
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

// The tour card is CENTRED for EVERY step (the pattern formerly used only as the no-target fallback, now
// generalised). This PURE fn returns the card's fixed-position box. See docs: portal internals, tour.js.
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
// Geometry of the LEADER from the centred card to the spotlight. See docs: portal internals, tour.js.
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
    // spotlight, no leader: the backdrop carries the dim itself.
    spot.style.display="none";
    if(leader)leader.style.display="none";
    backdrop.style.background="rgba(11,15,18,"+TOUR_DIM+")";
  }else{
    // Targeted step: the spot's box-shadow supplies the dim and the backdrop stays transparent, so
    // the spotlighted element shows fully through the cutout.
    backdrop.style.background="transparent";
    spot.style.display="block";
    const pad=6;
    spot.style.top=Math.max(0,rect.top-pad)+"px";
    spot.style.left=Math.max(0,rect.left-pad)+"px";
    spot.style.width=(rect.width+pad*2)+"px";
    spot.style.height=(rect.height+pad*2)+"px";
    spot.style.boxShadow="0 0 0 4000px rgba(11,15,18,"+TOUR_DIM+")";
    // Leader from the centred card to the spotlight, suppressed on the two map steps (the sel==='#map'
    // entries, which isMapStep keys off by SELECTOR rather than by a number that rots).
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

// Run the CURRENT step's exit hook (if any) before leaving it - called on Next, Back and
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
  _tourOpened={drawer:false,hash:null,view:null,collapsed:false};
  _tourFindPrev=null;_tourTreePrev=null;_tourTreeTarget=null;_tourSelPrevMode=null;   // demo state: fresh every run
  // A COLLAPSED rail hides every child but the collapse button, so the rail steps (Find, the tree. Expand
  // it for the run and record that WE did, so _tourRestore puts the visitor's own choice back. See docs:
  // portal internals, tour.js.
  const _sb=document.querySelector("aside.filters");
  if(_sb&&_sb.classList.contains("collapsed")&&typeof setSidebarCollapsed==="function"){
    setSidebarCollapsed(false);_tourOpened.collapsed=true;
  }
  _tourEls=_tourBuild();
  _tourStep=0;_tourPosition();
}
function stopTour(){
  if(_tourStep<0)return;
  _tourExitCurrent();                  // a demo step's cleanup runs on mid-tour close too
  _tourStep=-1;
  document.removeEventListener("keydown",_tourKeydown);
  window.removeEventListener("resize",_tourOnResize);   // stop tracking the viewport once the tour closes
  _tourRestore();                      // Done/Esc/close from ANY step: restore only what the tour itself changed
  if(_tourEls){
    _tourEls.backdrop.remove();_tourEls.spot.remove();_tourEls.leader.remove();_tourEls.card.remove();
    _tourEls=null;
  }
}
