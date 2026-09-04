"use strict";
// Shared station filter (drives both Map and Surveys) + the hierarchy tree. buildTree() is
// data-dependent and called by main after ST is built. recolor lives in map.js and is
// referenced only inside event handlers (runtime), never at load time.
const tree=document.getElementById("tree");
// The empty-state selection hint is OWNED by the markup (#selHint's default text in index.html);
// read once at load so the copy lives in one place. updateSel restores it when a selection clears.
const SEL_HINT_EMPTY=(document.getElementById("selHint")||{textContent:""}).textContent;
let findActive=-1;   // index of the keyboard-highlighted Find option (-1 = none). Declared
                     // up here so renderFind() (which resets it) is never in its temporal dead zone.
// The period-window control is retired; the predicate is HEADLESS like qMin below - the
// bounds live in state.js (periodLo/periodHi, full-range by default) and are drivable by harnesses.
// A revival note: the old heading said "cover this period window" while the predicate is an OVERLAP
// test; any returning control must state the overlap semantics.
// Year-range predicate. A station passes when its SURVEY's [year_start,year_end] overlaps the
// typed [from,to] range; either input may be blank (an open end on that side). Unknown years
// (survey declares no dates) PASS when both inputs are empty (no filter in effect) but FAIL as soon
// as either is set — a modeller who typed a year range is asking for DATED data, so silently
// including undated stations would misrepresent the range as covering them.
// The rule itself, over a record's OWN two years. It is read on two surfaces - the map filters stations
// (passesYearRange below) and the survey grid filters surveys (drawer.js _surveyPassesYears) - and it
// lived as two verbatim copies in two files, differing only in the field names each surface spells its
// years with. That is the shape a rule drifts in: one copy gets corrected and the other does not. One
// definition, two callers, and the harness pins the two readings against each other.
function passesYearWindow(yearLo,yearHi){
  const fromEl=document.getElementById("yearFrom"),toEl=document.getElementById("yearTo");
  if(!fromEl||!toEl)return true;                      // filter UI not present (e.g. a bare fixture) -> no-op
  const from=fromEl.value.trim()?+fromEl.value:null,to=toEl.value.trim()?+toEl.value:null;
  if(from==null&&to==null)return true;
  if(yearLo==null&&yearHi==null)return false;         // undated record, but a range WAS requested
  const lo=yearLo??yearHi,hi=yearHi??yearLo;
  if(from!=null&&hi<from)return false;
  if(to!=null&&lo>to)return false;
  return true;}
function passesYearRange(s){return passesYearWindow(s.yearStart,s.yearEnd);}
function passesCore(s){
  if(![...document.querySelectorAll("#typeBoxes input:checked")].map(c=>c.value).includes(s.type))return false;
  const svs=[...tree.querySelectorAll('input[value]:checked')].map(c=>c.value);
  if(!svs.includes(s.survey))return false;
  if(s.pmin>periodHi||s.pmax<periodLo)return false;
  // Two-phase boot: s.q comes from sci.json, a PHASE 2 product. Until that product is USABLE this predicate
  // is INERT: a completeness value that has not arrived is not a FAILING one, and applying it would hide
  // every station on the map (and empty the counts) over data the portal does not have. hydrUsable, not
  // !hydrating: a FAILED sci.json leaves s.q undefined exactly as an in-flight one does, so a pending-only
  // gate would go live on a broken build and report "0 of 5 shown", which reads as a screening outcome.
  // SCI_READY re-runs refresh() the moment the values land, so a filter set early still takes effect.
  // No completeness THRESHOLD control is offered with the Availability group; the predicate
  // is kept because qMin is still drivable (the headless drivers set it) and because deleting a
  // screening rule is a curation decision, not a rail-layout one.
  if(qMin>0&&hydrUsable("sci")&&!(s.q>=qMin))return false;
  if(!passesYearRange(s))return false;
  // "Downloadable here" is the s.ediAvail licence predicate (the retired tickbox's, then the Data
  // available dropdown's "tf" option, the same flag the selection exports read for their not-included
  // honesty). The CONTROL was promoted to the discovery bar and the predicate stayed exactly here, so
  // the map filters on it as it always did; only where a reader sets it has changed.
  if(typeof surveyFacetOn==="function"&&surveyFacetOn("dl")&&!s.ediAvail)return false;
  // Data available: the single-select TIME-SERIES level chooser in Browse. A level token
  // filters on ts_access.json membership and is INERT until the index has landed: a route that has not
  // arrived is not a missing one, and filtering on it would empty the map over data the portal does not
  // have. paintAvailSelect disables the level options across the same window (belt and braces), and
  // TSACC_READY re-runs refresh() so a choice made early still takes effect. Membership in the index IS
  // the access decision: nothing here re-derives availability, and no filter state can surface a
  // station the build gated out.
  const av=document.getElementById("availSel");
  if(av&&av.value&&typeof tsAccessKnown==="function"&&tsAccessKnown()){
    const lv=tsRoutesFor(s.ausmt_id);
    if(!lv||!lv[av.value])return false;}
  return true;}
function passes(s){if(!passesCore(s))return false;
  const q=document.getElementById("find").value.trim().toLowerCase();
  // match station id/file OR survey name, so typing a survey/collection name (which Find invites) keeps that
  // survey's stations on the map instead of blanking it; the dropdown still offers the collection/survey jumps.
  if(q&&!(s.id.toLowerCase().includes(q)||s.file.toLowerCase().includes(q)||s.survey.toLowerCase().includes(q)))return false;
  return true;}
// Surveys-view search: a case-insensitive substring across the survey name, org,
// region and blurb. Reads the discovery-bar #surveySearch input (NOT the rail #find; the rail is
// hidden on the Surveys view, so the discovery search REPLACES #find as that view's search). Empty
// query (or no input present, e.g. a bare fixture) matches everything.
function surveyMatchesSearch(sv){
  const el=document.getElementById("surveySearch");
  const q=el&&el.value?el.value.trim().toLowerCase():"";
  if(!q)return true;
  const m=(typeof SMETA!=="undefined"&&SMETA[sv])||{};
  return [sv,m.org,m.region,m.blurb].some(x=>String(x||"").toLowerCase().includes(q));}
// Stage B (selection-state isolation): the Surveys CATALOGUE is filtered ONLY by its own discovery
// controls, the #surveySearch box (surveyMatchesSearch) plus the discovery facets (surveyPassesFacets,
// applied by renderCards / updateCounts). It must not read passesCore, so the map rail's tree / type /
// period / year / selection state can never hide a card. Coupling passesCore here lets the All-EDIs tile,
// which checks a single tree box to scope the MAP, empty the whole catalogue with the rail (its only undo)
// hidden on this view. The MAP still filters on passesCore via passes() / `visible`; only the catalogue is
// cut loose.
function surveyVisible(sv){return surveyMatchesSearch(sv);}
// Unified Find: a live dropdown of matching collections / surveys / stations. Collections + surveys are
// JUMP targets (collection page / focus on the map); stations open, and the text also live-filters the map.
function renderFind(){const box=document.getElementById("findResults");
  const q=document.getElementById("find").value.trim().toLowerCase();
  if(!q){box.style.display="none";box.innerHTML="";findCloseState();return;}
  const COL=(typeof COLL!=="undefined"&&COLL)||{};
  const colls=Object.keys(COL).filter(cid=>(COL[cid].title||cid).toLowerCase().includes(q)||cid.toLowerCase().includes(q)).slice(0,5);
  const svs=surveys.filter(sv=>sv.toLowerCase().includes(q)).slice(0,8);
  const sts=ST.filter(s=>s.id.toLowerCase().includes(q)||(s.file||"").toLowerCase().includes(q)).slice(0,8);
  let h="";
  if(colls.length)h+=`<div class="fgroup">Collections</div>`+colls.map(cid=>`<div class="fitem" data-find="coll" data-id="${escAttr(cid)}">${esc(COL[cid].title||cid)}<span class="fmeta">${COL[cid].n_surveys} surveys · ${COL[cid].n_stations} stations</span></div>`).join("");
  if(svs.length)h+=`<div class="fgroup">Surveys</div>`+svs.map(sv=>`<div class="fitem" data-find="survey" data-id="${escAttr(sv)}">${esc(sv)}</div>`).join("");
  if(sts.length)h+=`<div class="fgroup">Stations${sts.length>=8?" (first 8)":""}</div>`+sts.map(s=>`<div class="fitem" data-find="station" data-i="${s.i}">${esc(s.id)}<span class="fmeta">${esc(s.survey)}</span></div>`).join("");
  if(!h)h=`<div class="fitem fnone">no matches</div>`;
  box.innerHTML=h;box.style.display="block";
  // Make the live results keyboard-usable. The container is role="listbox" (index.html);
  // tag each REAL result (a data-find row, not the "no matches" filler) as an option with a stable id so
  // the input can point aria-activedescendant at the highlighted one. Matching logic above is untouched.
  findOptions().forEach((el,i)=>{el.setAttribute("role","option");el.id="find-opt-"+i;el.setAttribute("aria-selected","false");});
  const find=document.getElementById("find");
  find.setAttribute("aria-expanded","true");
  findActive=-1;find.removeAttribute("aria-activedescendant");}
function hasShapes(){let a=false;drawn.eachLayer(()=>a=true);return a;}
// Coordinate access: a custodian-withheld station has null lat/lon (no position). It must NOT be
// spatially selectable — without this guard null coerces to 0 and a polygon over (0,0) would phantom-
// select it. It stays in ST/visible (counted, findable by name/text), just never in a bbox/shape hit.
function inShapes(s){if(!hasPosition(s))return false;
  let inside=false;drawn.eachLayer(layer=>{if(inside)return;
  const rings=layer.getLatLngs();const ring=Array.isArray(rings[0])?rings[0]:rings;let inn=false;
  for(let a=0,b=ring.length-1;a<ring.length;b=a++){const yi=ring[a].lat,xi=ring[a].lng,yj=ring[b].lat,xj=ring[b].lng;
    if(((yi>s.lat)!==(yj>s.lat))&&(s.lon<(xj-xi)*(s.lat-yi)/(yj-yi)+xi))inn=!inn;}if(inn)inside=true;});return inside;}
// The header counter is ONE shell with a CONTEXTUAL slot. A fixed
// "N shown / M selected / T total" describes what the reader is looking at only on the map: on the
// Surveys view it counts stations while the screen shows survey cards, and on the Collections views it
// counts something not on screen at all. The shell never moves; only
// this slot's content changes, and where nothing true can be said about what is on screen it says
// nothing rather than leaving a stale number standing.
function _countN(x){return Number(x).toLocaleString("en-AU");}
function updateCounts(){
  const slot=document.getElementById("countSlot");
  if(!slot)return;
  if(curView==="collections"||curView==="collection"){slot.removeAttribute("title");slot.innerHTML="";return;}
  if(curView==="surveys"){
    // The WORKSPACE LINE. Its first number mirrors the discovery-filtered catalogue (#surveyCount) - the
    // search box AND the discovery facets - never the map rail's tree / type / period / year. Its second
    // counts STATIONS, because stations are what a selection holds and what the download builder takes.
    // With nothing selected the clause is hidden: "0 stations selected" is true and is noise.
    const _fac=(typeof surveyPassesFacets==="function")?surveyPassesFacets:(()=>true);
    const shown=surveys.filter(surveyVisible).filter(_fac).length,sel=selected.size;
    slot.title="surveys passing the current search and filters · stations selected for download";
    slot.innerHTML=`<b>${_countN(shown)}</b> of ${_countN(surveys.length)} survey${surveys.length===1?"":"s"} shown`+
      (sel?` · <b>${_countN(sel)}</b> station${sel===1?"":"s"} selected`:"");
    return;}
  // MAP: the three station counts, rebuilt into the form index.html ships (ids included, since other
  // surfaces paint them by id). The three numbers are plain integers; _countN belongs to the workspace
  // line beside them. The counts pin drives a 1,200-station window, because at the fixture's five the
  // two formats are the same string.
  slot.title="stations passing the current filters · stations selected · total stations in the catalogue";
  slot.innerHTML=`<b id="nVis">${visible.length}</b> shown · <b id="nSel">${selected.size}</b> selected · <span id="nTot">${ST.length}</span> total`;}
function refresh(){visible=ST.filter(passes);
  // ONE call paints the visible set into the map's single dot container; map.js owns the layer and this
  // stays the caller it always was. Nothing collapses, so a filter change is the only thing that can alter
  // what is on the map: only POSITIONED stations reach the layer, and a withheld-coordinate station has
  // no marker (buildMarkers skipped it). It remains in `visible` (counted), just not on the map.
  routeVisibleToLayers();
  if(hasShapes())selected=new Set(visible.filter(inShapes).map(s=>s.i));else selected=new Set([...selected].filter(i=>visible.some(s=>s.i===i)));
  if(curView==="surveys")renderCards();
  updateCounts();updateSel();}
function updateSel(){document.getElementById("selBig").textContent=selected.size;
  // The selection is half the workspace line, so a selection change repaints the header slot. The
  // map form's #nSel is rebuilt by the same call, which is why it is not set directly here.
  updateCounts();
  // Downloads follow the SCOPE (scopeStations), so the metadata buttons enable whenever the
  // scope is non-empty - with nothing selected they act on the filtered corpus, and the scope line
  // says so. Guarded per element: a renamed button must not abort every later line of this function
  // on each selection change (the bind-time console.error is the loud signal).
  const on=scopeStations().length>0;
  ["dlCsv","dlGeo","dlSh","dlCite"].forEach(id=>{const el=document.getElementById(id);if(el)el.disabled=!on;});
  // The Download block (scope line, the three Level 2 rows, the time-series rows) is owned by
  // exports.js, which owns the packaging the metas must agree with; re-painted here, where the
  // selection is known to have changed. Guarded like the other cross-module calls: a harness that
  // loads filters.js without exports.js still updates the counts.
  if(typeof paintDownloadRows==="function")paintDownloadRows();
  document.getElementById("selHint").textContent=selected.size?"Downloads below cover exactly these stations, with provenance pointers.":SEL_HINT_EMPTY;}

// Tree disclosure state. Collapse is IN-MEMORY only (no persistence - polish item), keyed
// "c:<country>" / "o:<country||org>" / "k:<collection id>" (the || separator is the tree's existing
// org-namespacing convention). Visibility is applied by WALKING the flat rows: a row hides when ANY
// ancestor key is collapsed, so re-expanding a country keeps a collapsed org's surveys hidden.
// INVARIANT (test-pinned): collapse/expand touches ONLY row visibility — never a checkbox, never the
// filter result (passesCore reads `input[value]:checked`, and a hidden row's checkbox still matches),
// so checked-but-hidden surveys stay on the map.
const _treeCollapsed=new Set();
function treeIsCollapsed(key){return _treeCollapsed.has(key);}
function treeSetCollapsed(key,collapsed){if(collapsed)_treeCollapsed.add(key);else _treeCollapsed.delete(key);applyTreeVisibility();}
function applyTreeVisibility(){
  tree.querySelectorAll("label.org").forEach(row=>{const okey=row.querySelector("input").dataset.org;
    row.classList.toggle("hidden",treeIsCollapsed("c:"+okey.slice(0,okey.indexOf("||"))));});
  tree.querySelectorAll("label.survey").forEach(row=>{const inp=row.querySelector("input");
    row.classList.toggle("hidden",treeIsCollapsed("c:"+inp.dataset.country)||treeIsCollapsed("o:"+inp.dataset.org));});
  tree.querySelectorAll(".caret").forEach(c=>{c.textContent=treeIsCollapsed(c.dataset.key)?"▸":"▾";});   // the one place the caret glyphs are written; only country and org rows carry one
}
// Caret factory - its OWN click target INSIDE the label-wrapped row. preventDefault stops
// the label from activating its checkbox (the click-target hazard, test-pinned); stopPropagation
// keeps the click out of any delegated handlers. Glyph is synced by applyTreeVisibility above.
function _caret(key){const c=document.createElement("span");c.className="caret";c.dataset.key=key;c.textContent="▾";
  c.setAttribute("role","button");c.setAttribute("aria-label","Collapse or expand");
  c.addEventListener("click",e=>{e.preventDefault();e.stopPropagation();treeSetCollapsed(key,!treeIsCollapsed(key));});
  return c;}

// hierarchy tree: country -> org -> survey (all names escaped)
function buildTree(){const hier={},svCount={};ST.forEach(s=>{(hier[s.country]=hier[s.country]||{});(hier[s.country][s.org]=hier[s.country][s.org]||{});
  (hier[s.country][s.org][s.survey]=(hier[s.country][s.org][s.survey]||0)+1);svCount[s.survey]=(svCount[s.survey]||0)+1;});
  // Collections toggle group - FIRST, above all countries, only when the boot data has
  // collections (same non-empty gating as the Collections tab). Collections are CROSS-CUTTING (a
  // programme can span orgs) so this is NOT a nesting level: the checkbox is a PUSH-ONLY bulk toggle
  // with the country/org semantics — on change it sets every MEMBER survey's checkbox (matched by
  // LABEL: COLL[cid].surveys holds labels and survey checkboxes use value=<label>) and refreshes. No
  // Derived/indeterminate state (country/org don't either). The row is
  // just name + survey count + station count: no nested member list, no caret (per-survey toggling
  // lives in the org hierarchy). Org rows/counts below are untouched: member surveys still live under their orgs.
  // The Collections group is mounted in its OWN block (#collGroup) ABOVE the country/org/survey
  // tree, not first-within #tree. Only the mount point changed — the heading, the row label, the push-only
  // bulk-toggle semantics and the member-survey sync (still matched against #tree's value checkboxes) are
  // unchanged. Fallback to `tree` keeps any harness without the #collGroup element working as before.
  const _coll=(typeof COLL!=="undefined"&&COLL)||{};
  const _cids=Object.keys(_coll).sort();
  const collGroup=document.getElementById("collGroup")||tree;
  if(_cids.length){
    if(collGroup!==tree)collGroup.innerHTML="";   // re-render safety for the dedicated block
    const gh=document.createElement("div");gh.className="treegroup";gh.textContent="Collections";collGroup.appendChild(gh);
    _cids.forEach(cid=>{const c=_coll[cid],members=c.surveys||[];
      const nSt=members.reduce((a,sv)=>a+(svCount[sv]||0),0);
      // A collection row shows ONLY name + member-survey count + station count -
      // no nested member-survey list and no disclosure caret (nothing left to disclose). Member surveys
      // stay fully reachable via the org/country tree below and the collection page, so nothing is lost.
      const row=document.createElement("label");row.className="coll";
      const inp=document.createElement("input");inp.type="checkbox";inp.checked=true;inp.dataset.coll=cid;
      row.appendChild(inp);
      row.appendChild(document.createTextNode(`${c.title||cid}: ${members.length} survey${members.length===1?"":"s"} · ${nSt} station${nSt===1?"":"s"}`));
      collGroup.appendChild(row);
      inp.addEventListener("change",()=>{
        tree.querySelectorAll('input[value]').forEach(s=>{if(members.indexOf(s.value)>=0)s.checked=inp.checked;});
        refresh();});});}
  Object.keys(hier).sort().forEach(country=>{
    const cc=document.createElement("label");cc.className="country";
    cc.innerHTML=`<input type="checkbox" data-country="${escAttr(country)}" checked>${esc(country)}<span class="flag">${esc(CC[country]||"")}</span>`;
    cc.insertBefore(_caret("c:"+country),cc.firstChild);   // disclosure caret ahead of the checkbox
    tree.appendChild(cc);
    Object.keys(hier[country]).sort().forEach(org=>{
      const okey=country+"||"+org;   // org names can repeat across countries — namespace the toggle key
      const orow=document.createElement("label");orow.className="org";
      const _nsv=Object.keys(hier[country][org]).length;
      orow.innerHTML=`<input type="checkbox" data-org="${escAttr(okey)}" checked>${esc(org)} <span class="osv">(${_nsv} survey${_nsv===1?"":"s"})</span>`;
      orow.insertBefore(_caret("o:"+okey),orow.firstChild);   // the org row's disclosure caret
      tree.appendChild(orow);
      Object.keys(hier[country][org]).sort().forEach(sv=>{
        const l=document.createElement("label");l.className="survey";
        l.innerHTML=`<input type="checkbox" value="${escAttr(sv)}" data-country="${escAttr(country)}" data-org="${escAttr(okey)}" checked>${esc(sv.replace(/^AusLAMP /,""))}<span class="n">${hier[country][org][sv]|0}</span>`;
        tree.appendChild(l);});});});
  // Country checkbox toggles all its orgs + surveys; org checkbox toggles its surveys. The PARENT
  // checkboxes have NO `value` attribute (surveys do), so identify them with hasAttribute("value") — NOT
  // .value, which is "on" for a value-less checkbox (the bug that made the country/org toggles no-ops).
  tree.querySelectorAll('input[data-country]').forEach(inp=>{if(inp.hasAttribute("value"))return;
    inp.addEventListener("change",()=>{
      tree.querySelectorAll('input[data-country]').forEach(c=>{if(c.hasAttribute("value")&&c.dataset.country===inp.dataset.country)c.checked=inp.checked;});
      tree.querySelectorAll('input[data-org]').forEach(c=>{if(!c.hasAttribute("value")&&(c.dataset.org||"").indexOf(inp.dataset.country+"||")===0)c.checked=inp.checked;});  // keep org boxes in sync
      refresh();});});
  tree.querySelectorAll('input[data-org]').forEach(inp=>{if(inp.hasAttribute("value"))return;
    inp.addEventListener("change",()=>{tree.querySelectorAll('input[data-org]').forEach(c=>{if(c.hasAttribute("value")&&c.dataset.org===inp.dataset.org)c.checked=inp.checked;});refresh();});});
  applyTreeVisibility();   // default = everything expanded; normalises caret glyphs on (re)build
}

// static control wiring (registrations only; functions resolved at event time)
// The SINGLE data-type state path. Both ends of the type filter reach it: the rail's own checkboxes, and
// the map legend's type rows (which proxy those checkboxes and dispatch this very event - see
// toggleLegendType/syncLegendTypes in main.js). syncLegendTypes repaints the legend FROM the checkbox
// state, so a rail flip dims the legend row and a legend flip confirms itself, off one function. Guarded
// on typeof for the same reason every other handler here resolves late: main.js loads after this file.
document.getElementById("typeBoxes").addEventListener("change",()=>{
  if(typeof syncLegendTypes==="function")syncLegendTypes();
  refresh();});
tree.addEventListener("change",e=>{if(e.target.value!==undefined&&e.target.value!=="")refresh();});
document.getElementById("find").addEventListener("input",()=>{refresh();renderFind();});
document.getElementById("find").addEventListener("focus",renderFind);
// Activation is shared between a mouse click and a keyboard Enter (below), so both take
// the identical path. `it` is a .fitem option element (has data-find). Kept verbatim from the old click
// handler body — no routing change, only extracted so Enter can reuse it.
function activateFindItem(it){if(!it||!it.dataset.find)return;
  const kind=it.dataset.find,fb=document.getElementById("find");
  if(kind==="coll"){fb.value="";refresh();location.hash="#/collection/"+encodeURIComponent(it.dataset.id);}
  else if(kind==="survey"){fb.value="";focusSurvey(it.dataset.id);}                       // focusSurvey refreshes + zooms
  else if(kind==="station"){const s=ST[+it.dataset.i];if(s){if(curView!=="map")setView("map");openStation(s.i);}}
  const fr=document.getElementById("findResults");fr.style.display="none";findCloseState();}
document.getElementById("findResults").addEventListener("click",e=>{const it=e.target.closest(".fitem");activateFindItem(it);});
// click-away closes the Find dropdown (the data-act delegated handler in drawer.js ignores .fitem)
document.addEventListener("click",e=>{if(!e.target.closest("#find")&&!e.target.closest("#findResults")){const fr=document.getElementById("findResults");if(fr){fr.style.display="none";findCloseState();}}});

// Keyboard path for the Find dropdown. ArrowUp/Down move an active-descendant highlight,
// Enter activates the highlighted option (same activateFindItem as a click), Esc clears the query. No CSS
// Rule is added to index.html for the highlight - the active option is
// styled inline to match the existing :hover look (copper fill, dark ink), and un-styled on move-off.
// (findActive is declared at the top of this file to avoid a temporal-dead-zone hazard in renderFind.)
function findOptions(){return [...document.getElementById("findResults").querySelectorAll(".fitem[data-find]")];}
function findIsOpen(){const fr=document.getElementById("findResults");return fr&&fr.style.display==="block";}
function findPaint(el,on){if(!el)return;const meta=el.querySelector(".fmeta");
  if(on){el.style.background="var(--copper)";el.style.color="#16110b";if(meta)meta.style.color="#16110b";el.setAttribute("aria-selected","true");}
  else{el.style.background="";el.style.color="";if(meta)meta.style.color="";el.setAttribute("aria-selected","false");}}
function setFindActive(idx){const opts=findOptions(),find=document.getElementById("find");
  if(findActive>=0&&findActive<opts.length)findPaint(opts[findActive],false);
  findActive=opts.length?(((idx%opts.length)+opts.length)%opts.length):-1;   // wrap both directions
  if(findActive>=0){const el=opts[findActive];findPaint(el,true);if(el.scrollIntoView)el.scrollIntoView({block:"nearest"});find.setAttribute("aria-activedescendant",el.id);}
  else find.removeAttribute("aria-activedescendant");}
function findCloseState(){findActive=-1;const find=document.getElementById("find");
  find.setAttribute("aria-expanded","false");find.removeAttribute("aria-activedescendant");}
document.getElementById("find").addEventListener("keydown",e=>{
  if(e.key==="Escape"){const fb=document.getElementById("find");if(fb.value){fb.value="";refresh();}renderFind();return;}
  if(!findIsOpen()||!findOptions().length)return;
  // From the neutral state (findActive<0) ArrowDown lands on the first option and ArrowUp on the last;
  // thereafter each wraps around the ends (setFindActive normalises the index).
  if(e.key==="ArrowDown"){e.preventDefault();setFindActive(findActive<0?0:findActive+1);}
  else if(e.key==="ArrowUp"){e.preventDefault();setFindActive(findActive<0?findOptions().length-1:findActive-1);}
  else if(e.key==="Enter"){if(findActive>=0){e.preventDefault();activateFindItem(findOptions()[findActive]);}}});
// One-time ARIA wiring so the input advertises the listbox it drives (combobox pattern). Attributes are
// set here rather than in index.html, so this behaviour stays inside filters.js.
(function(){const find=document.getElementById("find");if(!find)return;
  find.setAttribute("role","combobox");find.setAttribute("aria-autocomplete","list");
  find.setAttribute("aria-controls","findResults");find.setAttribute("aria-expanded","false");})();
// Data available (Browse): a change re-filters; paintAvailSelect owns the level options' two-phase
// state (disabled + a reason while ts_access.json is in flight or absent; Any/TF ride the catalogue
// and are live from first paint).
const _availSel=document.getElementById("availSel");
if(_availSel&&_availSel.addEventListener)_availSel.addEventListener("change",refresh);
function paintAvailSelect(){
  const av=document.getElementById("availSel");if(!av||!av.querySelectorAll)return;
  const known=(typeof tsAccessKnown==="function")&&tsAccessKnown();
  const ix=(typeof TSACC!=="undefined"&&TSACC)||{};
  const empty=known&&!Object.keys(ix).length;
  [...av.querySelectorAll("option")].forEach(o=>{
    // "" is the Any option, which rides the catalogue and is live from first paint. There is no "tf"
    // option in #availSel (the capability is a discovery chip), so no option reaches that branch; the
    // harness pin asserts #availSel carries no "tf" value.
    if(o.value==="")return;
    o.disabled=!known||empty;
    o.title=known?(empty?"Availability by level: "+TS_NONE_HINT:""):TS_PENDING_HINT;});
}

// ---- Availability > Time series: the per-level chooser ------------------------------------------
// The access posture, restated where the level filter reads it (passesCore) and where the Download
// rows price it (exports.js paintDownloadRows): which stations appear in ts_access.json was decided
// in the build - open access, a verified register row, never level_2 - so nothing in the portal
// re-derives availability from survey metadata, and no control state can bring back a station the
// build gated out. The two-phase hints are shared by the Data available options and the Download
// rows; in flight and settled-empty are NOT the same fact (one resolves itself, one is a statement
// about the build), so each surface names which it is in.
const TS_PENDING_HINT="Time-series availability is still loading";
const TS_NONE_HINT="this deployment publishes no download index";
// The current DOWNLOAD SCOPE: the selection when one exists, else the filtered corpus -
// exactly what "Select all filtered" would take. One rule, no modes; the scope line in the Download
// block states which. exports.js reads this for every download and every priced row.
function scopeStations(){return selected.size?ST.filter(s=>selected.has(s.i)):visible;}
// Rail Browse and Select-and-download mode. Browse (default) is
// every map filter (find, data type, Data available, year, tree); Select & download is the
// map-selection box and the Download/Metadata blocks
// (advanced). It is a pure show/hide of the two mode panes — it never touches data-views (view/mode are
// orthogonal: a section is visible iff its mode pane is shown AND its own data-views allows the view).
let sidebarMode="browse";
// Stage B (selection-state isolation): the All-EDIs / survey "Download" tile (selectSurvey, drawer.js)
// enters Select & download mode and scopes the MAP by checking ONLY its own survey in the tree. That map
// scoping is a TEMPORARY LENS, not a durable filter: snapshot the survey checkboxes it is about to mutate
// on entry (enterSelectLens) and put them back when the visitor leaves the lens - returns to Browse
// (setSidebarMode below) or navigates off the map (setView, main.js). The snapshot is taken ONLY by the
// tile flow, so a visitor hand-toggling tree boxes in Browse mode is NEVER captured or restored (their
// state stands). Scope is tight: only the `input[value]` survey checkboxes selectSurvey touches are
// captured / restored; country / org parents and every other control are left exactly as they are.
let _selLens=null;                 // Array<[surveyValue, wasChecked]> awaiting restore; null = no lens live
function enterSelectLens(){
  if(_selLens!==null)return;        // re-entrant tile click while a lens is live: keep the ORIGINAL snapshot
  _selLens=[...tree.querySelectorAll('input[value]')].map(c=>[c.value,c.checked]);}
function restoreSelectLens(){
  if(_selLens===null)return;
  const snap=_selLens;_selLens=null;
  const want={};snap.forEach(([v,ch])=>{want[v]=ch;});
  tree.querySelectorAll('input[value]').forEach(c=>{if(c.value in want)c.checked=want[c.value];});
  refresh();}
function setSidebarMode(mode){
  // Stage B: leaving Select & download for Browse ends any All-EDIs lens - restore the survey checkboxes the
  // tile scoped so the Browse pane shows the visitor's own tree again, never the single-survey scoping the
  // tile applied. Guarded on the select->browse transition so repeated setSidebarMode("browse") calls and a
  // visitor's plain Browse use are untouched.
  if(mode==="browse"&&sidebarMode==="select")restoreSelectLens();
  sidebarMode=mode;
  // No map re-route on a mode switch: the mode was an input to the badge rule (Select expanded every badge
  // so a lasso could reach the stations) and every station is already its own dot in both modes.
  const bp=document.getElementById("browseMode"),sp=document.getElementById("selectMode"),seg=document.getElementById("modeSeg");
  if(bp)bp.classList.toggle("hidden",mode!=="browse");
  if(sp)sp.classList.toggle("hidden",mode!=="select");
  if(seg)[...seg.children].forEach(b=>b.classList.toggle("on",b.dataset.mode===mode));}
document.getElementById("modeSeg").addEventListener("click",e=>{const b=e.target.closest("button");if(!b||!b.dataset.mode)return;setSidebarMode(b.dataset.mode);});
// "Select all filtered" makes a selection, so auto-switch to Select & download for discoverability of
// the exports it just enabled: the same nudge the draw-created handler in map.js makes.
// It also CLEARS any drawn shape: refresh() re-derives the selection from shapes, so a stale shape
// would silently discard the select-all on the next filter change.
document.getElementById("selAll").onclick=()=>{drawn.clearLayers();selected=new Set(visible.map(s=>s.i));updateSel();setSidebarMode("select");};
document.getElementById("clearSel").onclick=()=>{selected.clear();drawn.clearLayers();updateSel();};

// Year range filter - two plain number inputs; either change re-filters (refresh() re-reads
// passesYearRange() each call, so no extra plumbing needed beyond a re-render trigger).
const yearFrom=document.getElementById("yearFrom"),yearTo=document.getElementById("yearTo");
if(yearFrom)yearFrom.addEventListener("input",refresh);
if(yearTo)yearTo.addEventListener("input",refresh);

// Availability > Transfer functions: the #tfAvail CHECKBOX is gone, folded into the Browse
// "Data available" single-select (#availSel, its "tf" option).
// The PREDICATE s.ediAvail outlived the control exactly as this comment always said it would: it is
// read in passesCore() above and by the selection exports' three-way not-included honesty.

// UX feedback round 1: "Go to place" (goToPlace(), #goPlace, AU_PLACES) removed — operator decision,
// redundant. See index.html (input+datalist removed) and state.js (AU_PLACES removed).
