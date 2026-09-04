"use strict";
// Shared station filter (drives both Map and Surveys) + the hierarchy tree. buildTree() is data-dependent
// and called by main after ST is built. See docs: portal internals, filters.js.
const tree=document.getElementById("tree");
// The empty-state selection hint is OWNED by the markup (#selHint's default text in index.html);
// read once at load so the copy lives in one place. updateSel restores it when a selection clears.
const SEL_HINT_EMPTY=(document.getElementById("selHint")||{textContent:""}).textContent;
let findActive=-1;   // index of the keyboard-highlighted Find option (-1 = none). Declared
                     // up here so renderFind() (which resets it) is never in its temporal dead zone. See
                     // docs: portal internals, filters.js.
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
  // Two-phase boot: s.q comes from sci.json, a PHASE 2 product. See docs: portal internals, filters.js.
  if(qMin>0&&hydrUsable("sci")&&!(s.q>=qMin))return false;
  if(!passesYearRange(s))return false;
  // "Downloadable here" is the s.ediAvail licence predicate: the flag behind the Data available
  // dropdown's "tf" option and the one the selection exports read for their not-included honesty.
  // See docs: portal internals, filters.js.
  if(typeof surveyFacetOn==="function"&&surveyFacetOn("dl")&&!s.ediAvail)return false;
  // Data available: the single-select TIME-SERIES level chooser in Browse. See docs: portal internals,
  // filters.js.
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
// Surveys-view search: a case-insensitive substring across the survey name, org, region and blurb. See
// docs: portal internals, filters.js.
function surveyMatchesSearch(sv){
  const el=document.getElementById("surveySearch");
  const q=el&&el.value?el.value.trim().toLowerCase():"";
  if(!q)return true;
  const m=(typeof SMETA!=="undefined"&&SMETA[sv])||{};
  return [sv,m.org,m.region,m.blurb].some(x=>String(x||"").toLowerCase().includes(q));}
// Stage B (selection-state isolation): the Surveys CATALOGUE is filtered ONLY by its own discovery
// controls, the #surveySearch box (surveyMatchesSearch) plus the discovery facets (surveyPassesFacets,
// applied by renderCards / updateCounts). See docs: portal internals, filters.js.
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
  // Make the live results keyboard-usable. The container is role="listbox" (index.html); tag each REAL
  // result (a data-find row, not the "no matches" filler) as an option with a stable id so the input can
  // point aria-activedescendant at the highlighted one. See docs: portal internals, filters.js.
  findOptions().forEach((el,i)=>{el.setAttribute("role","option");el.id="find-opt-"+i;el.setAttribute("aria-selected","false");});
  const find=document.getElementById("find");
  find.setAttribute("aria-expanded","true");
  findActive=-1;find.removeAttribute("aria-activedescendant");}
function hasShapes(){let a=false;drawn.eachLayer(()=>a=true);return a;}
// Coordinate access: a custodian-withheld station has null lat/lon (no position). It must NOT be spatially
// selectable - without this guard null coerces to 0 and a polygon over (0,0) would phantom-select it. See
// docs: portal internals, filters.js.
function inShapes(s){if(!hasPosition(s))return false;
  let inside=false;drawn.eachLayer(layer=>{if(inside)return;
  const rings=layer.getLatLngs();const ring=Array.isArray(rings[0])?rings[0]:rings;let inn=false;
  for(let a=0,b=ring.length-1;a<ring.length;b=a++){const yi=ring[a].lat,xi=ring[a].lng,yj=ring[b].lat,xj=ring[b].lng;
    if(((yi>s.lat)!==(yj>s.lat))&&(s.lon<(xj-xi)*(s.lat-yi)/(yj-yi)+xi))inn=!inn;}if(inn)inside=true;});return inside;}
// The header counter is ONE shell with a CONTEXTUAL slot. See docs: portal internals, filters.js.
function _countN(x){return Number(x).toLocaleString("en-AU");}
function updateCounts(){
  const slot=document.getElementById("countSlot");
  if(!slot)return;
  if(curView==="collections"||curView==="collection"){slot.removeAttribute("title");slot.innerHTML="";return;}
  if(curView==="surveys"){
    // The WORKSPACE LINE. Its first number mirrors the discovery-filtered catalogue (#surveyCount) - the
    // search box AND the discovery facets - never the map rail's tree / type / period / year. See docs:
    // portal internals, filters.js.
    const _fac=(typeof surveyPassesFacets==="function")?surveyPassesFacets:(()=>true);
    const shown=surveys.filter(surveyVisible).filter(_fac).length,sel=selected.size;
    slot.title="surveys passing the current search and filters · stations selected for download";
    slot.innerHTML=`<b>${_countN(shown)}</b> of ${_countN(surveys.length)} survey${surveys.length===1?"":"s"} shown`+
      (sel?` · <b>${_countN(sel)}</b> station${sel===1?"":"s"} selected`:"");
    return;}
  // MAP: the three station counts, rebuilt into the form index.html ships (ids included, since other
  // surfaces paint them by id). See docs: portal internals, filters.js.
  slot.title="stations passing the current filters · stations selected · total stations in the catalogue";
  slot.innerHTML=`<b id="nVis">${visible.length}</b> shown · <b id="nSel">${selected.size}</b> selected · <span id="nTot">${ST.length}</span> total`;}
function refresh(){visible=ST.filter(passes);
  // ONE call paints the visible set into the map's single dot container; map.js owns the layer and this
  // stays the caller it always was. See docs: portal internals, filters.js.
  routeVisibleToLayers();
  if(hasShapes())selected=new Set(visible.filter(inShapes).map(s=>s.i));else selected=new Set([...selected].filter(i=>visible.some(s=>s.i===i)));
  if(curView==="surveys")renderCards();
  updateCounts();updateSel();}
function updateSel(){document.getElementById("selBig").textContent=selected.size;
  // The selection is half the workspace line, so a selection change repaints the header slot. The
  // map form's #nSel is rebuilt by the same call, which is why it is not set directly here.
  updateCounts();
  // Downloads follow the SCOPE (scopeStations), so the metadata buttons enable whenever the scope is
  // non-empty - with nothing selected they act on the filtered corpus, and the scope line says so. See
  // docs: portal internals, filters.js.
  const on=scopeStations().length>0;
  ["dlCsv","dlGeo","dlSh","dlCite"].forEach(id=>{const el=document.getElementById(id);if(el)el.disabled=!on;});
  // The Download block (scope line, the three Level 2 rows, the time-series rows) is owned by exports.js,
  // which owns the packaging the metas must agree with; re-painted here, where the selection is known to
  // have changed. See docs: portal internals, filters.js.
  if(typeof paintDownloadRows==="function")paintDownloadRows();
  document.getElementById("selHint").textContent=selected.size?"Downloads below cover exactly these stations, with provenance pointers.":SEL_HINT_EMPTY;}

// Tree disclosure state. Collapse is IN-MEMORY only (no persistence - polish item), keyed "c:<country>" /
// "o:<country||org>" / "k:<collection id>" (the || separator is the tree's existing org-namespacing
// convention). See docs: portal internals, filters.js.
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
// Caret factory - its OWN click target INSIDE the label-wrapped row. preventDefault stops the label from
// activating its checkbox (the click-target hazard, test-pinned); stopPropagation keeps the click out of
// any delegated handlers. See docs: portal internals, filters.js.
function _caret(key){const c=document.createElement("span");c.className="caret";c.dataset.key=key;c.textContent="▾";
  c.setAttribute("role","button");c.setAttribute("aria-label","Collapse or expand");
  c.addEventListener("click",e=>{e.preventDefault();e.stopPropagation();treeSetCollapsed(key,!treeIsCollapsed(key));});
  return c;}

// hierarchy tree: country -> org -> survey (all names escaped)
function buildTree(){const hier={},svCount={};ST.forEach(s=>{(hier[s.country]=hier[s.country]||{});(hier[s.country][s.org]=hier[s.country][s.org]||{});
  (hier[s.country][s.org][s.survey]=(hier[s.country][s.org][s.survey]||0)+1);svCount[s.survey]=(svCount[s.survey]||0)+1;});
  // Collections toggle group - FIRST, above all countries, only when the boot data has collections (same
  // non-empty gating as the Collections tab). See docs: portal internals, filters.js.
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
      const okey=country+"||"+org;   // org names can repeat across countries - namespace the toggle key
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
  // checkboxes have NO `value` attribute (surveys do), so identify them with hasAttribute("value") - NOT
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

// static control wiring (registrations only; functions resolved at event time) The SINGLE data-type state
// path. See docs: portal internals, filters.js.
document.getElementById("typeBoxes").addEventListener("change",()=>{
  if(typeof syncLegendTypes==="function")syncLegendTypes();
  refresh();});
tree.addEventListener("change",e=>{if(e.target.value!==undefined&&e.target.value!=="")refresh();});
document.getElementById("find").addEventListener("input",()=>{refresh();renderFind();});
document.getElementById("find").addEventListener("focus",renderFind);
// Activation is shared between a mouse click and a keyboard Enter (below), so both take the identical path.
// `it` is a .fitem option element (has data-find). See docs: portal internals, filters.js.
function activateFindItem(it){if(!it||!it.dataset.find)return;
  const kind=it.dataset.find,fb=document.getElementById("find");
  if(kind==="coll"){fb.value="";refresh();location.hash="#/collection/"+encodeURIComponent(it.dataset.id);}
  else if(kind==="survey"){fb.value="";focusSurvey(it.dataset.id);}                       // focusSurvey refreshes + zooms
  else if(kind==="station"){const s=ST[+it.dataset.i];if(s){if(curView!=="map")setView("map");openStation(s.i);}}
  const fr=document.getElementById("findResults");fr.style.display="none";findCloseState();}
document.getElementById("findResults").addEventListener("click",e=>{const it=e.target.closest(".fitem");activateFindItem(it);});
// click-away closes the Find dropdown (the data-act delegated handler in drawer.js ignores .fitem)
document.addEventListener("click",e=>{if(!e.target.closest("#find")&&!e.target.closest("#findResults")){const fr=document.getElementById("findResults");if(fr){fr.style.display="none";findCloseState();}}});

// Keyboard path for the Find dropdown. ArrowUp/Down move an active-descendant highlight, Enter activates
// the highlighted option (same activateFindItem as a click), Esc clears the query. See docs: portal
// internals, filters.js.
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

// ---- Availability > Time series: the per-level chooser ------------------------------------------ The
// access posture, restated where the level filter reads it (passesCore) and where the Download rows price
// it (exports.js paintDownloadRows). See docs: portal internals, filters.js.
const TS_PENDING_HINT="Time-series availability is still loading";
const TS_NONE_HINT="this deployment publishes no download index";
// The current DOWNLOAD SCOPE: the selection when one exists, else the filtered corpus - exactly what
// "Select all filtered" would take. See docs: portal internals, filters.js.
function scopeStations(){return selected.size?ST.filter(s=>selected.has(s.i)):visible;}
// Rail Browse and Select-and-download mode. Browse (default) is every map filter (find, data type, Data
// available, year, tree); Select & download is the map-selection box and the Download/Metadata blocks
// (advanced). See docs: portal internals, filters.js.
let sidebarMode="browse";
// Stage B (selection-state isolation): the All-EDIs / survey "Download" tile (selectSurvey, drawer.js)
// enters Select & download mode and scopes the MAP by checking ONLY its own survey in the tree. See docs:
// portal internals, filters.js.
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
  // Stage B: leaving Select & download for Browse ends any All-EDIs lens - restore the survey checkboxes
  // the tile scoped so the Browse pane shows the visitor's own tree again, never the single-survey scoping
  // the tile applied. See docs: portal internals, filters.js.
  if(mode==="browse"&&sidebarMode==="select")restoreSelectLens();
  sidebarMode=mode;
  // No map re-route on a mode switch: the mode was an input to the badge rule (Select expanded every badge
  // so a lasso could reach the stations) and every station is already its own dot in both modes.
  const bp=document.getElementById("browseMode"),sp=document.getElementById("selectMode"),seg=document.getElementById("modeSeg");
  if(bp)bp.classList.toggle("hidden",mode!=="browse");
  if(sp)sp.classList.toggle("hidden",mode!=="select");
  if(seg)[...seg.children].forEach(b=>b.classList.toggle("on",b.dataset.mode===mode));}
document.getElementById("modeSeg").addEventListener("click",e=>{const b=e.target.closest("button");if(!b||!b.dataset.mode)return;setSidebarMode(b.dataset.mode);});
// "Select all filtered" makes a selection, so auto-switch to Select & download for discoverability of the
// exports it just enabled: the same nudge the draw-created handler in map.js makes. See docs: portal
// internals, filters.js.
document.getElementById("selAll").onclick=()=>{drawn.clearLayers();selected=new Set(visible.map(s=>s.i));updateSel();setSidebarMode("select");};
document.getElementById("clearSel").onclick=()=>{selected.clear();drawn.clearLayers();updateSel();};

// Year range filter - two plain number inputs; either change re-filters (refresh() re-reads
// passesYearRange() each call, so no extra plumbing needed beyond a re-render trigger).
const yearFrom=document.getElementById("yearFrom"),yearTo=document.getElementById("yearTo");
if(yearFrom)yearFrom.addEventListener("input",refresh);
if(yearTo)yearTo.addEventListener("input",refresh);

// Availability > Transfer functions lives in the Browse "Data available" single-select (#availSel,
// its "tf" option) and nowhere else: there is no #tfAvail checkbox. See docs: portal internals,
// filters.js.

// No "Go to place" control exists: no goToPlace(), no #goPlace input and no AU_PLACES list, here or
// in index.html or state.js.
