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
const TOUR_STEPS=[
  {sel:"#map",text:"Every dot is an MT station. Click one to see its transfer function.",
   enter:_tourEnterMapView},
  {sel:"aside.filters",text:"Filter by survey or data type — or draw an area directly on the map. Year, period and quality screening live under “Screening (advanced)”."},
  {sel:"#find",text:"Find anything by name — the map filters live as you type (here: AusLAMP), and the dropdown jumps straight to a matching survey, collection or station.",
   enter:_tourEnterFindDemo,exit:_tourExitFindDemo},
  {sel:"#tree",text:"Or browse the hierarchy — country → organisation → survey. Tick or untick any level to show exactly the surveys you want.",
   enter:_tourEnterTreeDemo,exit:_tourExitTreeDemo},
  {sel:"#drawer",text:"The station drawer shows apparent resistivity, phase, tipper and phase-tensor screening — with full provenance.",
   enter:_tourEnterStation},
  {sel:".selbox",text:"Download single stations, whole surveys, or your current selection — licences and citations travel with the files.",
   enter:_tourEnterSelbox,exit:_tourExitSelbox},
  {sel:"#navSurveys",text:"You're on the Map view. The Surveys button lists every survey as a detailed card — let's head over."},
  {sel:"#cardGrid .scard",text:"Each survey card is the custodian's record — stations, licence, citation and downloads — and links to the full survey story.",
   enter:_tourEnterSurveysView},
  {sel:"#navMap",text:"The Map button brings you back to the stations whenever you're ready."},
  {sel:"#map",text:"That's the loop — find, screen, take, cite. Contribute your own survey any time from Add Survey.",
   enter:_tourEnterMap}
];

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
  const card=document.createElement("div");card.className="tourcard";card.id="tourCard";
  card.setAttribute("role","dialog");card.setAttribute("aria-label","AusMT guided tour");
  card.innerHTML=
    '<div class="tourstep" id="tourStepLabel"></div>'+
    '<div class="tourtext" id="tourText"></div>'+
    '<div class="tourbtns">'+
      '<button type="button" id="tourBack" aria-label="Previous tour step">Back</button>'+
      '<button type="button" id="tourNext" aria-label="Next tour step">Next</button>'+
      '<button type="button" id="tourClose" aria-label="Close tour">Close</button>'+
    '</div>';
  document.body.appendChild(backdrop);document.body.appendChild(spot);document.body.appendChild(card);
  document.getElementById("tourBack").onclick=_tourPrev;
  document.getElementById("tourNext").onclick=_tourNext;
  document.getElementById("tourClose").onclick=stopTour;
  document.addEventListener("keydown",_tourKeydown);
  return{backdrop,spot,card};
}

function _tourKeydown(e){
  if(_tourStep<0)return;
  if(e.key==="Escape"){stopTour();}
  else if(e.key==="ArrowRight"){_tourNext();}
  else if(e.key==="ArrowLeft"){_tourPrev();}
}

function _tourPosition(){
  const step=TOUR_STEPS[_tourStep];
  if(typeof step.enter==="function")step.enter();
  const target=step.sel?document.querySelector(step.sel):null;
  const rect=target?target.getBoundingClientRect():null;
  const hasTarget=!!(rect&&(rect.width>0||rect.height>0));
  const{spot,card,backdrop}=_tourEls;
  backdrop.classList.toggle("centered",!hasTarget);
  card.classList.toggle("static",!hasTarget);
  if(!hasTarget){
    // Target absent (e.g. empty-data state, or an enter action found nothing to open): show centred,
    // no spotlight — same fallback as before, now also covering a no-op enter action.
    spot.style.display="none";
    card.style.top="";card.style.left="";
  }else{
    spot.style.display="block";
    const pad=6;
    spot.style.top=Math.max(0,rect.top-pad)+"px";
    spot.style.left=Math.max(0,rect.left-pad)+"px";
    spot.style.width=(rect.width+pad*2)+"px";
    spot.style.height=(rect.height+pad*2)+"px";
    // Prefer placing the card to the right of the spotlight; fall back to below if it would clip.
    let left=rect.right+16,top=rect.top;
    if(left+340>window.innerWidth)left=Math.max(8,rect.left-16-340);
    if(left<0){left=Math.max(8,rect.left);top=rect.bottom+16;}
    if(top+160>window.innerHeight)top=Math.max(8,window.innerHeight-176);
    card.style.left=left+"px";card.style.top=top+"px";
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
  _tourRestore();                      // Done/Esc/close from ANY step: restore only what the tour itself changed
  if(_tourEls){
    _tourEls.backdrop.remove();_tourEls.spot.remove();_tourEls.card.remove();
    _tourEls=null;
  }
}
