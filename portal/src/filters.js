"use strict";
// Shared station filter (drives both Map and Surveys) + the hierarchy tree. buildTree() is
// data-dependent and called by main after ST is built. recolor/cluster live in map.js and are
// referenced only inside event handlers (runtime), never at load time.
const tree=document.getElementById("tree");
const pLo=document.getElementById("pLo"),pHi=document.getElementById("pHi");
function sliderRead(){let lo=+pLo.value,hi=+pHi.value;if(lo>hi)[lo,hi]=[hi,lo];return[10**lo,10**hi,lo,hi];}
function paintSlider(){const[plo,phi,lo,hi]=sliderRead();document.getElementById("pLoTxt").textContent=fmtP(plo);document.getElementById("pHiTxt").textContent=fmtP(phi);
  const f=document.getElementById("pfill");f.style.left=((lo+3)/8*100)+"%";f.style.width=((hi-lo)/8*100)+"%";}
// S3: year-range predicate. A station passes when its SURVEY's [year_start,year_end] overlaps the
// typed [from,to] range; either input may be blank (an open end on that side). Unknown years
// (survey declares no dates) PASS when both inputs are empty (no filter in effect) but FAIL as soon
// as either is set — a modeller who typed a year range is asking for DATED data, so silently
// including undated stations would misrepresent the range as covering them.
function passesYearRange(s){
  const fromEl=document.getElementById("yearFrom"),toEl=document.getElementById("yearTo");
  if(!fromEl||!toEl)return true;                      // filter UI not present (e.g. a bare fixture) -> no-op
  const from=fromEl.value.trim()?+fromEl.value:null,to=toEl.value.trim()?+toEl.value:null;
  if(from==null&&to==null)return true;
  if(s.yearStart==null&&s.yearEnd==null)return false;  // undated station, but a range WAS requested
  const lo=s.yearStart??s.yearEnd,hi=s.yearEnd??s.yearStart;
  if(from!=null&&hi<from)return false;
  if(to!=null&&lo>to)return false;
  return true;}
function passesCore(s){
  if(![...document.querySelectorAll("#typeBoxes input:checked")].map(c=>c.value).includes(s.type))return false;
  const svs=[...tree.querySelectorAll('input[value]:checked')].map(c=>c.value);
  if(!svs.includes(s.survey))return false;
  const[plo,phi]=sliderRead();if(s.pmin>phi||s.pmax<plo)return false;
  if(qMin>0&&!(s.q>=qMin))return false;
  if(!passesYearRange(s))return false;
  const dlOnly=document.getElementById("dlOnly");
  if(dlOnly&&dlOnly.checked&&!s.ediAvail)return false;   // "Downloadable here only": predicate s.ediAvail
  return true;}
function passes(s){if(!passesCore(s))return false;
  const q=document.getElementById("find").value.trim().toLowerCase();
  // match station id/file OR survey name, so typing a survey/collection name (which Find invites) keeps that
  // survey's stations on the map instead of blanking it; the dropdown still offers the collection/survey jumps.
  if(q&&!(s.id.toLowerCase().includes(q)||s.file.toLowerCase().includes(q)||s.survey.toLowerCase().includes(q)))return false;
  return true;}
function surveyVisible(sv){const qs=document.getElementById("find").value.trim().toLowerCase();
  if(qs&&!sv.toLowerCase().includes(qs))return false;
  return ST.some(s=>s.survey===sv&&passesCore(s));}
// Unified Find: a live dropdown of matching collections / surveys / stations. Collections + surveys are
// JUMP targets (collection page / focus on the map); stations open, and the text also live-filters the map.
function renderFind(){const box=document.getElementById("findResults");
  const q=document.getElementById("find").value.trim().toLowerCase();
  if(!q){box.style.display="none";box.innerHTML="";return;}
  const COL=(typeof COLL!=="undefined"&&COLL)||{};
  const colls=Object.keys(COL).filter(cid=>(COL[cid].title||cid).toLowerCase().includes(q)||cid.toLowerCase().includes(q)).slice(0,5);
  const svs=surveys.filter(sv=>sv.toLowerCase().includes(q)).slice(0,8);
  const sts=ST.filter(s=>s.id.toLowerCase().includes(q)||(s.file||"").toLowerCase().includes(q)).slice(0,8);
  let h="";
  if(colls.length)h+=`<div class="fgroup">Collections</div>`+colls.map(cid=>`<div class="fitem" data-find="coll" data-id="${escAttr(cid)}">${esc(COL[cid].title||cid)}<span class="fmeta">${COL[cid].n_surveys} surveys · ${COL[cid].n_stations} stations</span></div>`).join("");
  if(svs.length)h+=`<div class="fgroup">Surveys</div>`+svs.map(sv=>`<div class="fitem" data-find="survey" data-id="${escAttr(sv)}">${esc(sv)}</div>`).join("");
  if(sts.length)h+=`<div class="fgroup">Stations${sts.length>=8?" (first 8)":""}</div>`+sts.map(s=>`<div class="fitem" data-find="station" data-i="${s.i}">${esc(s.id)}<span class="fmeta">${esc(s.survey)}</span></div>`).join("");
  if(!h)h=`<div class="fitem fnone">no matches</div>`;
  box.innerHTML=h;box.style.display="block";}
function hasShapes(){let a=false;drawn.eachLayer(()=>a=true);return a;}
// C42 coordinate access: a custodian-withheld station has null lat/lon (no position). It must NOT be
// spatially selectable — without this guard null coerces to 0 and a polygon over (0,0) would phantom-
// select it. It stays in ST/visible (counted, findable by name/text), just never in a bbox/shape hit.
function inShapes(s){if(!hasPosition(s))return false;
  let inside=false;drawn.eachLayer(layer=>{if(inside)return;
  const rings=layer.getLatLngs();const ring=Array.isArray(rings[0])?rings[0]:rings;let inn=false;
  for(let a=0,b=ring.length-1;a<ring.length;b=a++){const yi=ring[a].lat,xi=ring[a].lng,yj=ring[b].lat,xj=ring[b].lng;
    if(((yi>s.lat)!==(yj>s.lat))&&(s.lon<(xj-xi)*(s.lat-yi)/(yj-yi)+xi))inn=!inn;}if(inn)inside=true;});return inside;}
function updateCounts(){const nv=document.getElementById("nVis");
  if(curView==="surveys"){const shown=surveys.filter(surveyVisible).length;nv.textContent=shown+" survey"+(shown===1?"":"s");}
  else nv.textContent=visible.length;
  document.getElementById("nTot").textContent=ST.length;}
function refresh(){paintSlider();visible=ST.filter(passes);
  // UX4 (D2): two map containers — AusLAMP-member markers into the plain (never-clustered) lpmtLayer,
  // everything else (incl. legacy non-AusLAMP LPMT) into the markerClusterGroup. Both are cleared and
  // repopulated every pass; the visible set and all downstream selection/counts logic below are unchanged
  // (they operate on `visible`, not on layer state). (Was UX3's LPMT-type split — see partitionMarkers.)
  // C42: only POSITIONED stations are routed to a layer — a withheld-coordinate station has no marker
  // (buildMarkers skipped it), so feeding it here would push `undefined` into addLayers. It remains in
  // `visible` (counted), just not on the map.
  const _part=partitionMarkers(visible.filter(hasPosition));
  cluster.clearLayers();cluster.addLayers(_part.clustered.map(s=>s.marker));
  lpmtLayer.clearLayers();_part.unclustered.forEach(s=>lpmtLayer.addLayer(s.marker));
  if(hasShapes())selected=new Set(visible.filter(inShapes).map(s=>s.i));else selected=new Set([...selected].filter(i=>visible.some(s=>s.i===i)));
  if(curView==="surveys")renderCards();
  updateCounts();updateSel();}
function updateSel(){document.getElementById("nSel").textContent=selected.size;document.getElementById("selBig").textContent=selected.size;
  const on=selected.size>0;["dlCsv","dlGeo","dlSh","dlCite","dlZip","strike"].forEach(id=>document.getElementById(id).disabled=!on);
  document.getElementById("selHint").textContent=on?"Exports below cover exactly these stations, with provenance pointers.":"Draw a polygon or rectangle on the map (toolbar, top-left), or take everything that passes the filters.";}

// UX5 (D7): tree disclosure state. Collapse is IN-MEMORY only (no persistence — polish item), keyed
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
  tree.querySelectorAll(".caret").forEach(c=>{c.textContent=treeIsCollapsed(c.dataset.key)?"▸":"▾";});   // ▸ / ▾, single source (O1 2026-07-12: collection carets removed — only country/org carets remain)
}
// UX5 (D7): caret factory — its OWN click target INSIDE the label-wrapped row. preventDefault stops
// the label from activating its checkbox (the click-target hazard, test-pinned); stopPropagation
// keeps the click out of any delegated handlers. Glyph is synced by applyTreeVisibility above.
function _caret(key){const c=document.createElement("span");c.className="caret";c.dataset.key=key;c.textContent="▾";
  c.setAttribute("role","button");c.setAttribute("aria-label","Collapse or expand");
  c.addEventListener("click",e=>{e.preventDefault();e.stopPropagation();treeSetCollapsed(key,!treeIsCollapsed(key));});
  return c;}

// hierarchy tree: country -> org -> survey (all names escaped)
function buildTree(){const hier={},svCount={};ST.forEach(s=>{(hier[s.country]=hier[s.country]||{});(hier[s.country][s.org]=hier[s.country][s.org]||{});
  (hier[s.country][s.org][s.survey]=(hier[s.country][s.org][s.survey]||0)+1);svCount[s.survey]=(svCount[s.survey]||0)+1;});
  // UX5 (D6): Collections toggle group — FIRST, above all countries, only when the boot data has
  // collections (same non-empty gating as the Collections tab). Collections are CROSS-CUTTING (a
  // programme can span orgs) so this is NOT a nesting level: the checkbox is a PUSH-ONLY bulk toggle
  // with the country/org semantics — on change it sets every MEMBER survey's checkbox (matched by
  // LABEL: COLL[cid].surveys holds labels and survey checkboxes use value=<label>) and refreshes. No
  // derived/indeterminate state (country/org don't either — future polish). O1 (2026-07-12): the row is
  // just name + survey count + station count now — no nested member list, no caret (per-survey toggling
  // lives in the org hierarchy). Org rows/counts below are untouched: member surveys still live under their orgs.
  const _coll=(typeof COLL!=="undefined"&&COLL)||{};
  const _cids=Object.keys(_coll).sort();
  if(_cids.length){
    const gh=document.createElement("div");gh.className="treegroup";gh.textContent="Collections";tree.appendChild(gh);
    _cids.forEach(cid=>{const c=_coll[cid],members=c.surveys||[];
      const nSt=members.reduce((a,sv)=>a+(svCount[sv]||0),0);
      // O1 (owner, 2026-07-12): a collection row shows ONLY name + member-survey count + station count —
      // no nested member-survey list and no disclosure caret (nothing left to disclose). Member surveys
      // stay fully reachable via the org/country tree below and the collection page, so nothing is lost.
      const row=document.createElement("label");row.className="coll";
      const inp=document.createElement("input");inp.type="checkbox";inp.checked=true;inp.dataset.coll=cid;
      row.appendChild(inp);
      row.appendChild(document.createTextNode(`${c.title||cid} — ${members.length} survey${members.length===1?"":"s"} · ${nSt} station${nSt===1?"":"s"}`));
      tree.appendChild(row);
      inp.addEventListener("change",()=>{
        tree.querySelectorAll('input[value]').forEach(s=>{if(members.indexOf(s.value)>=0)s.checked=inp.checked;});
        refresh();});});}
  Object.keys(hier).sort().forEach(country=>{
    const cc=document.createElement("label");cc.className="country";
    cc.innerHTML=`<input type="checkbox" data-country="${escAttr(country)}" checked>${esc(country)}<span class="flag">${esc(CC[country]||"")}</span>`;
    cc.insertBefore(_caret("c:"+country),cc.firstChild);   // UX5 (D7): disclosure caret ahead of the checkbox
    tree.appendChild(cc);
    Object.keys(hier[country]).sort().forEach(org=>{
      const okey=country+"||"+org;   // org names can repeat across countries — namespace the toggle key
      const orow=document.createElement("label");orow.className="org";
      const _nsv=Object.keys(hier[country][org]).length;
      orow.innerHTML=`<input type="checkbox" data-org="${escAttr(okey)}" checked>${esc(org)} <span class="osv">(${_nsv} survey${_nsv===1?"":"s"})</span>`;
      orow.insertBefore(_caret("o:"+okey),orow.firstChild);   // UX5 (D7)
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
  applyTreeVisibility();   // UX5 (D7): default = everything expanded; normalises caret glyphs on (re)build
}

// static control wiring (registrations only; functions resolved at event time)
document.getElementById("typeBoxes").addEventListener("change",refresh);
tree.addEventListener("change",e=>{if(e.target.value!==undefined&&e.target.value!=="")refresh();});
document.getElementById("find").addEventListener("input",()=>{refresh();renderFind();});
document.getElementById("find").addEventListener("focus",renderFind);
document.getElementById("findResults").addEventListener("click",e=>{const it=e.target.closest(".fitem");if(!it||!it.dataset.find)return;
  const kind=it.dataset.find,fb=document.getElementById("find");
  if(kind==="coll"){fb.value="";refresh();location.hash="#/collection/"+encodeURIComponent(it.dataset.id);}
  else if(kind==="survey"){fb.value="";focusSurvey(it.dataset.id);}                       // focusSurvey refreshes + zooms
  else if(kind==="station"){const s=ST[+it.dataset.i];if(s){if(curView!=="map")setView("map");openStation(s.i);}}
  document.getElementById("findResults").style.display="none";});
// click-away closes the Find dropdown (the data-act delegated handler in drawer.js ignores .fitem)
document.addEventListener("click",e=>{if(!e.target.closest("#find")&&!e.target.closest("#findResults")){const fr=document.getElementById("findResults");if(fr)fr.style.display="none";}});
pLo.addEventListener("input",refresh);pHi.addEventListener("input",refresh);
document.getElementById("colorSeg").addEventListener("click",e=>{const b=e.target.closest("button");if(!b)return;
  colorMode=b.dataset.c;[...e.currentTarget.children].forEach(x=>x.classList.toggle("on",x===b));recolor();});
document.getElementById("qSeg").addEventListener("click",e=>{const b=e.target.closest("button");if(!b)return;
  qMin=+b.dataset.q;[...e.currentTarget.children].forEach(x=>x.classList.toggle("on",x===b));refresh();});
document.getElementById("selAll").onclick=()=>{selected=new Set(visible.map(s=>s.i));updateSel();};
document.getElementById("clearSel").onclick=()=>{selected.clear();drawn.clearLayers();updateSel();};

// S3: Year range filter — two plain number inputs; either change re-filters (refresh() re-reads
// passesYearRange() each call, so no extra plumbing needed beyond a re-render trigger).
const yearFrom=document.getElementById("yearFrom"),yearTo=document.getElementById("yearTo");
if(yearFrom)yearFrom.addEventListener("input",refresh);
if(yearTo)yearTo.addEventListener("input",refresh);

// S3: "Downloadable here only" — single checkbox, predicate s.ediAvail (read inside passesCore()).
const dlOnly=document.getElementById("dlOnly");
if(dlOnly)dlOnly.addEventListener("change",refresh);

// UX feedback round 1: "Go to place" (goToPlace(), #goPlace, AU_PLACES) removed — operator decision,
// redundant. See index.html (input+datalist removed) and state.js (AU_PLACES removed).
