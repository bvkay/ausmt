// drawer.js - station/survey/provenance/citation/download rendering for the detail drawer. See docs: portal
// internals, drawer.js.
"use strict";
// Station drawer (science first), survey cards, survey story, citations. All event handling is delegated
// (no inline onclick): .close buttons, [data-act] card actions, [data-cite] citation copy, [data-prod]
// product tiles. See docs: portal internals, drawer.js.
const drawer=document.getElementById("drawer");
// The drawer is a dialog. role + a base aria-label are set here (index.html's #drawer element is declared
// in index.html, so the ARIA is stamped from JS); openStation/openSurvey refine the aria-label per subject.
// See docs: portal internals, drawer.js.
if(drawer&&drawer.setAttribute){drawer.setAttribute("role","dialog");drawer.setAttribute("aria-label","Details");drawer.setAttribute("tabindex","-1");}
// Focus management, mirroring plots.js's modal pattern - remember the invoking element on
// open, move focus INTO the drawer (its close button, else the container), and RESTORE focus to the opener
// on close. Best-effort/guarded so the headless smoke harness (no real activeElement/focus) never throws.
let _drawerReturnFocus=null;
function _rememberDrawerOpener(){_drawerReturnFocus=(typeof document!=="undefined"&&document)?document.activeElement:null;}
function _focusDrawer(){if(!drawer||!drawer.querySelector)return;
  // preventScroll: on the FIRST open the drawer is still transform:translateX(102%) off-screen mid-slide,
  // so focusing its .close button makes the browser scroll documentElement ~428px left to reveal the
  // off-screen target. See docs: portal internals, drawer.js.
  const t=drawer.querySelector(".close")||drawer;if(t&&t.focus){try{t.focus({preventScroll:true});}catch(e){}}}
function _restoreDrawerFocus(){const f=_drawerReturnFocus;_drawerReturnFocus=null;if(f&&f.focus){try{f.focus();}catch(e){}}}
// A dim backdrop shown behind the drawer while it is open on the Surveys / Collections / collection-detail
// views (where the drawer floats over full-width content). See docs: portal internals, drawer.js.
const _drawerScrim=document.getElementById("drawerScrim");
function showDrawerScrim(){if(_drawerScrim)_drawerScrim.classList.toggle("hidden",(typeof curView!=="undefined"&&curView==="map"));}
function hideDrawerScrim(){if(_drawerScrim)_drawerScrim.classList.add("hidden");}
if(_drawerScrim&&_drawerScrim.addEventListener)_drawerScrim.addEventListener("click",()=>closeDrawer());
// The currently-open station's TF row, stashed so the delegated [data-act="expand"] handler
// can re-render the plotters into the full-station response modal without re-deriving them from the DOM.
let _curTf=null;
// The currently-open station object, stashed alongside _curTf so the expand handler
// can build the response modal's identity header (id / site / survey / org / type / honest coords).
let _curStation=null;
// Two-phase boot: WHAT the drawer is currently showing: {kind:"station",i} | {kind:"survey",sv} | null, so
// a phase-2 product landing can re-render exactly that subject in place (rehydrateOpenDrawer). See docs:
// portal internals, drawer.js.
let _drawerSubject=null;
// A small section-role chip using the engine README taxonomy - "Source data",
// "Automated screening", "AusMT-derived". Plain muted text, no colour semantics.
function roleChip(l){return `<span class="rolechip">${esc(l)}</span>`;}
// ---- two-phase boot: the loading surfaces ------------------------------------------------------ The
// drawer is the densest consumer of the PHASE 2 products (tf.json -> the response curves; sci.json -> the
// processing/screening rows). See docs: portal internals, drawer.js.
function hydrBlock(what){return `<div class="hydrating" role="status">Loading ${esc(what)}…</div>`;}
function hydrFailBlock(what){return `<div class="hydrating hydrfail" role="status">Could not load ${esc(what)}.</div>`;}
function hydrCell(){return `<span class="hydrating hydr-inline">loading…</span>`;}
function hydrFailCell(){return `<span class="hydrating hydr-inline hydrfail">could not be loaded</span>`;}
// Render helper: returns the loading / failed markup for product `k`, or "" when it is ready and the caller
// should render its normal content. `block` picks the block form over the inline-cell form.
function hydrGate(k,what,block){
  if(hydrating(k))return block?hydrBlock(what):hydrCell();
  if(hydrFailed(k))return block?hydrFailBlock(what):hydrFailCell();
  return "";}
// A hydration re-render rewrites the whole drawer, which would otherwise snap every expander shut under a
// reader who opened one, up to three times (once per gate) across a multi-second hydration window. See
// docs: portal internals, drawer.js.
function _openDetailsKeys(){
  if(!(drawer&&drawer.querySelectorAll))return[];
  return [...drawer.querySelectorAll("details")].filter(d=>d.open)
    .map(d=>{const sm=d.querySelector&&d.querySelector("summary");return sm?sm.textContent:"";}).filter(Boolean);}
function _restoreOpenDetails(keys){
  if(!keys||!keys.length||!(drawer&&drawer.querySelectorAll))return;
  [...drawer.querySelectorAll("details")].forEach(d=>{
    const sm=d.querySelector&&d.querySelector("summary");
    if(sm&&keys.indexOf(sm.textContent)>=0)d.open=true;});}
// One tab panel. ALL panels render in the DOM at openStation time; selectDrawerTab
// toggles them via the `hidden` attribute + aria-selected, so the pinned innerHTML/text assertions keep
// matching against the same rendered strings regardless of which tab is active.
function drawerPanel(id,content,selected){
  return `<div class="dpanel" id="dp-${id}" role="tabpanel" data-tab="${id}" aria-labelledby="dt-${id}" tabindex="0"${selected?"":" hidden"}>${content}</div>`;}
// Activate one drawer tab (ARIA roving-tabindex + hidden toggle). Degrades to a no-op under the smoke
// harness (stubbed drawer with querySelectorAll()->[]). See docs: portal internals, drawer.js.
let _curDrawerTab="response";
function selectDrawerTab(name){
  _curDrawerTab=name;
  if(!drawer||!drawer.querySelectorAll)return;
  const tabs=[...drawer.querySelectorAll('[role="tab"]')];
  const panels=[...drawer.querySelectorAll('[role="tabpanel"]')];
  if(!tabs.length)return;
  if(!tabs.some(tb=>tb.dataset.tab===name))name=_curDrawerTab=tabs[0].dataset.tab;
  tabs.forEach(tb=>{const on=tb.dataset.tab===name;tb.setAttribute("aria-selected",on?"true":"false");tb.tabIndex=on?0:-1;if(tb.classList)tb.classList.toggle("on",on);});
  panels.forEach(p=>{p.hidden=(p.dataset.tab!==name);});
}
// The display gate, factored: the served-EDI descriptor for a station, {sub,st,d}. See docs: portal
// internals, drawer.js.
function ediDescriptor(s,m){
  // Two-phase boot: the manifest is a PHASE 2 product, so before it lands there is no honest answer here:
  // the served-artifact branch and BOTH fallbacks ("EDI (via source archive)" / the embargo wording) are
  // claims about what this deployment serves. See docs: portal internals, drawer.js.
  if(hydrating("manifest"))return {sub:"loading…",st:"unk",d:null};
  const arts=(typeof artifactsFor==="function"?artifactsFor(s.ausmt_id):[]);
  const ediArt=arts.find(a=>a.format==="edi");
  if(ediArt) return {sub:"Download"+(ediArt.size?" · "+fmtBytes(ediArt.size):""),st:"ok",d:{prod:"fetch",url:ediArt.url,name:ediArt.url.split("/").pop()}};
  if(!isOpenAccess(m)) return {sub:accessLevelOf(m)==="metadata_only"?"metadata only":"embargoed",st:"no",d:null};
  return {sub:s.ediAvail?"Download":"EDI (via source archive)",st:s.ediAvail?"ok":"unk",d:{prod:"edi",file:s.file,avail:s.ediAvail?"1":"0",survey:s.survey}};
}
// The sticky-header Download EDI action. Renders NOTHING where the gate refuses (no download affordance for
// an embargoed/metadata-only station) - otherwise a primary button routed through the same [data-prod]
// dispatch as the product tiles. See docs: portal internals, drawer.js.
function headerDownloadBtn(s,m){
  if(hydrating("manifest"))return `<span class="hydrating hydr-inline" role="status">checking file availability…</span>`;
  const e=ediDescriptor(s,m);if(!e.d)return"";
  const attrs=Object.entries(e.d).map(([k,v])=>`data-${k}="${escAttr(v)}"`).join(" ");
  return `<button class="primary dl-edi" ${attrs}>Download EDI</button>`;}
// The Station summary carries no "primary download" tile; the Files tab is the one surface that
// offers bytes. See docs: portal internals, drawer.js.

// The PLAIN-TEXT APA sentence: what the citation pack's CITATIONS.txt and the clipboard copy carry.
// A text file must never receive HTML entities (O'Brien is not O&#39;Brien on disk).
function apaPlain(m,doi){return `${m.au} (${m.yr||"n.d."}). ${m.ti}${m.ve?" ("+m.ve+")":""} [Data set]. ${m.pb}.`+(doi?` https://doi.org/${doi}`:"");}
// The HTML rendering of the same sentence. esc() is character-wise, so escaping the assembled string
// equals escaping each field; the two renderers cannot drift because one wraps the other.
function apa(m,doi){return esc(apaPlain(m,doi));}
// The DISPLAY-ONLY APA citation rendered inside the Cite box. See docs: portal internals, drawer.js.
function apaCiteDisplay(m,doi,doiRes){const base=apa(m,null);   // the APA sentence WITHOUT the DOI suffix
  if(!doi)return base;
  const url="https://doi.org/"+doi;
  const doiHtml=doiRes==="reserved"
    ? esc(url)
    : `<a href="${escUrl(url)}" target="_blank" rel="noopener noreferrer">${esc(url)}</a>`;
  return base+" "+doiHtml;}
// & is a LaTeX special: an unescaped ampersand in a field value fails the BibTeX compile.
function bibAmp(s){return String(s==null?"":s).replace(/&/g,"\\&");}
function bibtex(k,m,doi){return `@misc{${k},\n  author    = {${bibAmp(m.au).replace(/;/g," and")}},\n  title     = {${bibAmp(m.ti)}},\n  year      = {${m.yr||"n.d."}},\n  publisher = {${bibAmp(m.pb)}},\n${doi?`  doi       = {${doi}},\n`:""}  note      = {Accessed via the AusMT portal}\n}`;}
function ris(m,doi){return `TY  - DATA\nAU  - ${m.au.replace(/; /g,"\nAU  - ")}\nTI  - ${m.ti}\nPY  - ${m.yr||""}\nPB  - ${m.pb}\n${doi?`DO  - ${doi}\nUR  - https://doi.org/${doi}\n`:""}ER  -`;}

// The glyph carries the state for a colour-blind READER (✓/◐/✗/?, not colour alone), but a glyph has no
// reliable spoken name and `title` is not dependably announced, so the state also rides in an aria-label:
// assistive tech gets "EMTF XML: partial" rather than a bare format name in an unreadable colour.
const _BADGE_STATE={ok:"available",part:"partial",no:"not available"};
function badge(l,st,title){const c=st==="ok"?"ok":st==="part"?"part":st==="no"?"no":"";const s=st==="ok"?"✓":st==="part"?"◐":st==="no"?"✗":"?";return `<span class="badge ${c}" aria-label="${escAttr(l+": "+(_BADGE_STATE[st]||"unknown"))}"${title?` title="${escAttr(title)}"`:""}>${s} ${esc(l)}</span>`;}
// Licence class/badge routed through the CANONICAL contract tables (contract.js LICENSES), never a
// `startsWith('CC')` guess: that guess mis-classes CC0, ODbL and ODC-BY along with every non-CC open
// licence, and passes a hostile "CCwhatever". See docs: portal internals, drawer.js.
function licCanon(x){const u=String(x==null?"":x).trim().replace(/\s+/g," ").toUpperCase();
  return ((LICENSES.aliases||{})[u]||u);}
function licIsOpen(lic){return !!lic&&(LICENSES.redistributable||[]).indexOf(licCanon(lic))>=0;}
function licBadgeState(lic){if(!lic)return "unk";const c=licCanon(lic);
  if((LICENSES.redistributable||[]).indexOf(c)>=0)return "ok";
  if((LICENSES.recognised_only||[]).indexOf(c)>=0)return "part";
  return "unk";}
// The attribution synthesis year: the LAST 4-digit year in the survey's declared dates string, "" when
// undeclared. Factored out (behaviour unchanged) so the ONE attribution box (attributionBoxHtml) rebuilds
// the same "(year)" tail around linked creator names without re-deriving it, and so the two cannot drift.
function attributionYear(m){return ((m&&m.dates)?(String(m.dates).match(/\d{4}/g)||[]).slice(-1)[0]:"")||"";}
// The survey-level attribution line - the custodian's verbatim attribution.statement when
// declared, else the org(year) synthesis. MIRRORS exports.attributionLine byte-for-byte so the drawer, the
// station Cite tab, the exported CSV and the citation pack all render the SAME attribution string.
function attributionText(m){m=m||{};
  const st=((m.attribution||{}).statement||"").toString().trim();
  if(st)return st;
  const who=((m.cite&&m.cite.au)||m.org||"").toString().trim();
  const yr=attributionYear(m);
  return [who,yr?"("+yr+")":""].filter(Boolean).join(" ").trim();}
// A source's required attribution when it carries no verbatim statement - the profile-rendered
// form via the generated PROFILES table (exports.renderProfile, present at render time), else custodian(year).
function sourceAttr(s){s=s||{};
  const cust=(s.custodian||"").toString().trim();
  const yr=(s.retrieved?(String(s.retrieved).match(/\d{4}/)||[])[0]:"")||"";
  if(typeof renderProfile==="function")return renderProfile((s.profile||"generic").toString().trim()||"generic",cust,yr,(s.title||"").toString().trim(),false);
  return [cust,yr?"("+yr+")":""].filter(Boolean).join(" ").trim();}
// The upstream "Source datasets" list for the survey detail - one row per sources[] entry (title,
// custodian + identifier link + canonical licence, then the required attribution). "" when none declared.
function sourcesListHtml(m){const srcs=(m&&m.sources)||[];
  if(!srcs.length)return"";
  const rows=srcs.map(s0=>{const s=s0||{};
    const title=esc((s.title||"untitled source dataset").toString().trim());
    const cust=esc((s.custodian||"unknown custodian").toString().trim());
    const idv=(s.identifier||"").toString().trim();
    const ident=idv?" · "+pidLink(idv):"";
    // This row is CHROME, not a data slot, and it sits on the same drawer as the licence / access row, so
    // it takes the human form. See docs: portal internals, drawer.js.
    const slic=esc(licHuman(licCanon(s.licence))||"licence not stated");
    const stmt=(s.statement||"").toString().trim();
    const attr=stmt?esc(stmt):esc(sourceAttr(s));
    return `<div class="srcitem"><div class="srct">${title}</div><div class="srcm">${cust}${ident} · <span class="prov">${slic}</span></div>${attr?`<div class="srca">${attr}</div>`:""}</div>`;
  }).join("");
  return `<div class="sechead">Source datasets ${roleChip("Source data")}</div><div class="srclist">${rows}</div>`;}
// A survey's access.level is authoritative for whether the portal has its DISPLAY data. "open" (or absent,
// which this reader defaults to open) => served, curves present. See docs: portal internals, drawer.js.
function accessLevelOf(m){return (m&&m.access)?String(m.access):"open";}
function isOpenAccess(m){return accessLevelOf(m)==="open";}
// Withheld-download copy: the TRUTHFUL access reason for a survey with NO dataset DOI (so no honest
// source-archive pointer exists). See docs: portal internals, drawer.js.
function withheldReason(m){
  const org=(m&&m.org)||"unknown";
  const reason=accessLevelOf(m)==="embargoed"
    ? "dataset currently under embargo"+((m&&m.embargo_until)?" until "+String(m.embargo_until):"")
    : "not redistributable under its licence";
  return reason+", contact the custodian organisation ("+org+")";
}
// The boot-loaded coordinate policy for a station ('generalised' | 'withheld' | null), folded onto s by
// buildState() from coord_policy.json. See docs: portal internals, drawer.js.
function coordPolicyOf(s){return (s&&s.coordPolicy)||null;}
// True when a station's SERVED position is masked. A withheld station is detectable from its null coords
// alone (belt-and-braces if the marker artifact never loaded); a generalised station needs the marker
// (its 0.1° cell is a valid-looking position, indistinguishable from an exact grid-point without it).
function coordsMasked(s){return !hasPosition(s)||coordPolicyOf(s)==="generalised"||coordPolicyOf(s)==="withheld";}
// Survey-level honesty predicate: are ALL of a survey's station locations served EXACT? Backs the access-
// panel stance text: "Station locations are public" is asserted only when this is true.
function surveyLocationsPublic(sv){return !ST.some(s=>s.survey===sv&&coordsMasked(s));}
// The drawer's lat/lon cell. Withheld => the honest withheld line (no coords). See docs: portal internals,
// drawer.js.
function coordCellHtml(s){
  if(!hasPosition(s)) return `<span style="color:var(--muted)">coordinates withheld (custodian policy)</span>`;
  const coords=`${s.lat.toFixed(6)}, ${s.lon.toFixed(6)}`;
  return coordPolicyOf(s)==="generalised"
    ? `${coords}<br><span style="color:var(--muted)">position generalised to ~0.1° (custodian policy)</span>`
    : coords;
}
// The identity header for the full-station RESPONSE modal (the expand affordance). See docs: portal
// internals, drawer.js.
function stationModalHeader(s,m){
  const site=(s.site_name&&s.site_name!==s.id)?`<span class="pm-site">${esc(s.site_name)}</span>`:"";
  const typeChip=`<span class="chip" style="background:${TYPE_COL[s.type]||"#999"}${TYPE_INK[s.type]?";color:"+TYPE_INK[s.type]:""}">${esc(s.type)}</span>`;
  return `<div class="pm-id"><span class="sid">${esc(s.id)}</span>${site}${typeChip}</div>`+
    `<div class="pm-sub">${esc(s.survey)} · ${orgNameLink(s.org,(m||{}).org_ror)}</div>`+
    `<div class="pm-coord">${coordCellHtml(s)}</div>`;
}
// The access panel replacing the plots area for a non-open survey. Verbatim copy (esc()'d) per level:
// embargoed(+date) / embargoed(no date) / metadata_only; any other non-open value falls back to the
// no-date embargo wording (fail-closed: an unknown level is treated as withheld, never as open).
function accessPanel(m,sv){
  const lvl=accessLevelOf(m);
  const when=(m&&m.embargo_until)?String(m.embargo_until):"";
  // The location-publicity clause is only asserted when EVERY station's position is served exact. When a
  // custodian has generalised/withheld any station, "locations are public" is FALSE - say so. See docs:
  // portal internals, drawer.js.
  const stance=surveyLocationsPublic(sv)
    ? "Station locations and survey metadata are public"
    : "Survey metadata is public; some station locations are generalised or withheld at the custodian's request";
  let title,body;
  if(lvl==="metadata_only"){
    title="Metadata only";
    body="This survey is listed metadata-only. "+stance+"; transfer functions are available from the custodian; see the survey's contact and identifiers.";
  }else if(when){
    title="Embargoed until "+when;
    body="This survey is embargoed until "+when+". "+stance+"; transfer functions and downloads are withheld until the embargo lifts.";
  }else{
    title="Embargoed";
    body="This survey is embargoed. "+stance+"; transfer functions and downloads are withheld.";
  }
  return `<div class="plot accesspanel"><div class="badges" style="margin-bottom:8px">${badge(title,"part")}</div>`+
    `<div class="emptynote" style="padding:8px 4px">${esc(body)}</div></div>`;
}
// Dataset-maturity model. Five RECORD-STEWARDSHIP dimensions - how completely a record is archived,
// licensed and reproducible, NOT its scientific quality (said in the block's subline). See docs: portal
// internals, drawer.js.
function datasetDoiResolution(m){m=m||{};
  const res=[];
  if(m.doi)res.push(m.doi_resolution);
  for(const r of (m.related_identifiers||[]))if(r&&r.identifier_type==="DOI")res.push(r.resolution);
  if(!res.length)return null;
  return res.some(x=>x!=="reserved")?"ok":"reserved";}
// "the raw time series is linked" reads off a typed IsDerivedFrom relation (which carries the collection
// PID) OR the flat ts_pid (engine fallback) OR the pipeline availability flag.
function tsLinked(m){m=m||{};
  return (m.related_identifiers||[]).some(r=>r&&r.relation==="IsDerivedFrom")||!!m.ts_pid||m.ts==="ok";}
function maturityModel(m,sc){m=m||{};sc=sc||[];
  const doiRes=datasetDoiResolution(m),tsOn=tsLinked(m);
  const dims=[
    {key:"curated",label:"Curated archive",achieved:true,note:""},
    {key:"repro",label:"Reproducible",achieved:!!(sc[SC.sw]&&m.ts==="ok"),note:""},
    {key:"licence",label:"Licence verified",achieved:licBadgeState(m.lic)!=="unk",note:""},
    // The DOI star lights only for a RESOLVED (ok/unknown) dataset DOI. A reserved DOI shows a
    // hollow star with honest wording - never a green "minted" off a DOI that 404s at doi.org today.
    {key:"doi",label:"DOI",achieved:doiRes==="ok",note:doiRes==="ok"?"minted":doiRes==="reserved"?"reserved (not yet active)":"not recorded"},
    {key:"ts",label:"Time series",achieved:tsOn,note:tsOn?"linked":"not available"},
  ];
  return {dims,stars:dims.filter(d=>d.achieved).length,total:dims.length};}
// The dimensions are listed one by one and never aggregated: no "Dataset maturity" heading, no
// five-star summary row. See docs: portal internals, drawer.js.
function maturityBlock(s){const m=SMETA[s.survey]||{},sc=sciRow(s.i);
  // Two-phase boot: the "Reproducible" dimension reads sc[SC.sw] (sci.json, PHASE 2). An unlit star is a
  // statement that the dimension was NOT achieved, so the whole LIST waits rather than under-stating a
  // dimension for a moment and then silently lighting it. See docs: portal internals, drawer.js.
  const gate=hydrGate("sci","stewardship details",true);
  if(gate)return `<div class="matblock">${gate}</div>`;
  const mod=maturityModel(m,sc);
  const rows=mod.dims.map(d=>`<li class="matdim ${d.achieved?"on":"off"}"><span class="matglyph">${d.achieved?"★":"☆"}</span><span>${esc(d.label)}${d.note?": "+esc(d.note):""}</span></li>`).join("");
  return `<div class="matblock"><ul class="matdims">${rows}</ul></div>`;}
// The raw-TS pointer. See docs: portal internals, drawer.js.
function tsPidRaw(m){return (m&&m.ts_pid)||TS_COLLECTION.doi;}
function tsUrlFor(m){return "https://doi.org/"+tsPidRaw(m);}
// There is no survey-scoped MTH5 lookup here: the <slug>-tf.h5 bundles[] row is survey-scoped and
// every surface on this side is STATION-scoped. See docs: portal internals, drawer.js.
function apiArtifactPath(u){const v=String(u==null?"":u);
  return /^[a-z][a-z0-9+.\-]*:\/\//i.test(v)?v:"/data/"+v.replace(/^\/+/,"");}
// The Files tab, structured to the NCI data-level standard as a SINGLE COLUMN of full-width rows (Packed
// raw / Level 0 / Level 1 time series -> Level 2 derived processed data with EDI/EMTF-XML/MTH5 sub-rows ->
// Level 3 models, when ever served -> Publication). See docs: portal internals, drawer.js.
function relatedProducts(s){const m=SMETA[s.survey]||{};
  const tsDoi=tsUrlFor(m);
  // The reserved-identifier posture: a reserved collection PID or dataset DOI must not open a dead link.
  // When reserved, the row is left inert (no action) with an honest note rather than routing to a 404.
  const tsReserved=!!(m.ts_pid&&m.ts_pid_resolution==="reserved"),tsOpen=tsReserved?null:{prod:"open",url:tsDoi};
  const doiReserved=!!(m.doi&&m.doi_resolution==="reserved");
  const arts=(typeof artifactsFor==="function"?artifactsFor(s.ausmt_id):[]);
  const xml=arts.find(a=>a.format==="emtfxml");
  // Time-series level availability comes from the survey time_series levels metadata (m.ts_levels; vocab
  // raw_packed / level0 / level1). A present level links to the source time-series collection (reserved
  // honesty); an absent level shows the honest muted not-available state (levels 0-2 are never omitted).
  const levels=(m.ts_levels||[]);
  const hasLevel=v=>levels.indexOf(v)>=0;
  // The related_identifiers row whose `identifies` matches this level (its own DOI), so
  // a user on the files tab jumps straight to the DOI for the data level they are looking at.
  const idRowFor=lvl=>(m.related_identifiers||[]).find(r=>r&&r.identifies===lvl);
  const tsLevelRow=(label,gloss,vocab)=>{
    if(!hasLevel(vocab))return {n:label,sub:gloss+" · not available",origin:"source archive",st:"unk",d:null};
    // Prefer the level's OWN identifier when a matching identifies row exists (reserved honesty applies:
    // a reserved level DOI is left inert with an honest note, never a dead link).
    const idRow=idRowFor(vocab);
    if(idRow&&idRow.identifier){
      if(idRow.resolution==="reserved")return {n:label,sub:gloss+" · reserved, not yet active",origin:"source archive",st:"part",d:null};
      // Scheme guard: only an http(s) href becomes a product-tile open action (its data-url reaches
      // window.open). See docs: portal internals, drawer.js.
      const href=relatedIdHref(idRow.identifier,idRow.identifier_type);
      if(href&&/^https?:/i.test(href))return {n:label,sub:gloss+" · "+(idRow.custodian||"source collection"),origin:"source archive",st:"ok",d:{prod:"open",url:href}};
    }
    if(tsReserved)return {n:label,sub:gloss+" · reserved, not yet active",origin:"source archive",st:"part",d:null};
    return {n:label,sub:gloss+" · "+(m.ts_pid?"survey collection":"NCI collection"),origin:"source archive",st:"ok",d:tsOpen};
  };
  // THE JOIN RULE, binding. `m.ts_levels` above is CURATOR-DECLARED and SURVEY-scope; ts_access.json is
  // CRAWL-VERIFIED and STATION-scope, and the two answer different questions. See docs: portal internals,
  // drawer.js.
  const tsIndexKnown=(typeof tsAccessKnown==="function")&&tsAccessKnown();
  const tsHandoff=(typeof tsRoutesFor==="function")?(tsRoutesFor(s.ausmt_id)||{}):{};
  const tsActionRows=toks=>toks.filter(t=>tsHandoff[t]).map(t=>{
    const e=tsHandoff[t],route=(typeof tsGoRoute==="function")?tsGoRoute(s,t):null;
    const label=((typeof TS_LEVELS!=="undefined"&&TS_LEVELS.find(l=>l[0]===t))||[])[1]||t;
    const name=String(e.url_path||"").split("/").pop();
    // The SAME scheme guard the identifier branch above uses: only an http(s) url becomes an open
    // action, because a data-url on a .prod tile reaches window.open.
    const ok=route&&/^https?:/i.test(route);
    return {n:"Fetch from the archive",
            sub:label+" · "+(e.bytes?fmtBigBytes(e.bytes):"size not stated")+" · via an AusMT redirect to NCI",
            origin:"source archive",st:ok?"ok":"unk",
            d:ok?{prod:"open",url:route,tsname:name,tsbytes:String(e.bytes||0)}:null};});
  // Level 2 sub-rows (the impedance tensors): the source EDI (the custodian's processed transfer function,
  // gated for non-open surveys - it says "embargoed"/"metadata only", never "via source archive"),
  // then the AusMT-derived EMTF XML (build pipeline, mt_metadata) and MTH5.
  const ediSub={n:"EDI",...ediDescriptor(s,m),origin:"source archive"};
  const xmlSub=xml
    ? {n:"EMTF XML",sub:"Download"+(xml.size?" · "+fmtBytes(xml.size):""),origin:"AusMT-derived",st:"ok",d:{prod:"fetch",url:xml.url,name:xml.url.split("/").pop()}}
    // Honesty fix: the 8 surveys with zero served XML ARE redistributable (the build pipeline failed on
    // them), so the old "via pipeline / served for redistributable surveys" toast was FALSE. Show the same
    // honest inert not-available sub-line the MTH5 row uses, with no toast overclaim.
    : {n:"EMTF XML",sub:"not currently available",origin:"AusMT-derived",st:"unk",d:null};
  // The Level 2 MTH5 sub-row is THIS STATION's own transfer-function h5: the manifest files[] row with
  // format mth5 (the h5/<slug>/<station>.h5 family), read from the very same `arts` rows the EDI and EMTF
  // XML sub-rows beside it read. See docs: portal internals, drawer.js.
  const mth5=arts.find(a=>a.format==="mth5");
  const mth5Sub=mth5
    ? {n:"MTH5",sub:"Transfer functions only · Download"+(mth5.size?" · "+fmtBytes(mth5.size):""),origin:"AusMT-derived",st:"ok",d:{prod:"fetch",url:mth5.url,name:mth5.url.split("/").pop()}}
    : {n:"MTH5",sub:"Transfer functions only · not currently available",origin:"AusMT-derived",st:"unk",d:null};
  const level2Subs=[ediSub,xmlSub,mth5Sub];
  // Publication (interpretation) - the parenthetical separates the dataset citation from an interpretation
  // publication. Reserved-DOI honesty applies (inert + note).
  const pubRow={n:"Publication (interpretation)",sub:m.doi?(doiReserved?"reserved, not yet active":"DOI"):"none recorded",origin:"source archive",st:m.doi?(doiReserved?"part":"ok"):"no",d:(m.doi&&!doiReserved)?{prod:"open",url:"https://doi.org/"+m.doi}:null};
  const attrs=d=>d?Object.entries(d).map(([k,v])=>`data-${k}="${escAttr(v)}"`).join(" "):"";
  const dot=st=>`<span class="pdot" style="background:var(--${st==="ok"?"ok":st==="part"?"part":st==="no"?"no":"unk"})"></span>`;
  const row=it=>`<div class="prod ${it.d?"":"dis"}" ${attrs(it.d)}>${dot(it.st)}<div>${esc(it.n)} ${it.origin?roleChip(it.origin):""}<small>${esc(it.sub)}</small></div></div>`;
  const tsRows=[
    [tsLevelRow("Raw time series","packed raw time series","raw_packed"),tsActionRows(["raw_packed"])],
    [tsLevelRow("Level 0 edited time series","instrument-recorded, full resolution","level0"),tsActionRows(["level0"])],
    [tsLevelRow("Level 1 transformed time series","calibrated, resampled, filtered","level1"),
     tsActionRows(["level1_mth5","level1_netcdf"])],
  ].map(([lvl,acts])=>row(lvl)+acts.map(row).join("")).join("")+
    // Two-phase boot: the hand-off index is a PHASE 2 product, so before it lands the absence of an
    // action row states nothing. Say which wait it is rather than letting silence read as "no file".
    (tsIndexKnown?"":hydrBlock("archive hand-off routes"));
  // Two-phase boot: all three Level 2 sub-rows resolve against the download manifest (PHASE 2), and each of
  // them degrades to a "not currently available" / "via source archive" line, i.e. statements about what
  // the build actually served. See docs: portal internals, drawer.js.
  const level2Body=hydrating("manifest")?hydrBlock("served files"):level2Subs.map(row).join("");
  const level2=`<div class="fl-group"><div class="fl-ghead">Level 2 derived processed data <small>transfer functions</small></div>`+
    `<div class="fl-sub">${level2Body}</div></div>`;
  // Level 3 models render ONLY when a model DOI is served in the survey metadata. No such field exists,
  // so the slot renders nothing: a survey record carrying m.model_doi is what would fill it, as a row
  // whose origin is the source archive and whose link is the doi.org resolver.
  return `<div class="filelist">${tsRows}${level2}${row(pubRow)}</div>`;}
// The MOST SPECIFIC processing-software string available for a station. See docs: portal internals,
// drawer.js.
function processingSoftwareText(m,sc){
  if(hydrating("sci"))return "loading…";
  if(hydrFailed("sci"))return "could not be loaded";
  const st=(((sc||[])[SC.sw])||"").toString().trim();
  if(st)return st;
  const sv=((m&&m.software)||"").toString().trim();
  return sv||"not stated in EDI";}
// LINEAGE: programs that WRITE transfer-function files they did not process. MIRRORED from the engine's
// _edi_catalog.KNOWN_WRITERS - keep the two in step. See docs: portal internals, drawer.js.
const KNOWN_WRITERS=["geotools","winglink","mtpy"];
function isKnownWriter(name){const n=String(name==null?"":name).trim().toLowerCase();
  return !!n&&KNOWN_WRITERS.some(w=>n.indexOf(w)>=0);}
// The lineage's "File written by" cell: the program that SERIALISED this station's file, from
// station.json's processing.file_written_by. See docs: portal internals, drawer.js.
function fileWrittenByText(fwb){
  const name=String((fwb&&fwb.name)==null?"":fwb.name).trim();
  if(!name)return "not stated in EDI";
  const ver=String((fwb&&fwb.version)==null?"":fwb.version).trim();
  return name+(ver?" "+ver:"")+(isKnownWriter(name)?" (database/file export)":"");}
// The formats AusMT actually distributes for THIS STATION, dot-separated with no ticks and no "(pipeline)"
// qualifier. It renders inside the station drawer's lineage graph, so every input must be station-scoped.
// See docs: portal internals, drawer.js.
function distributedFormatsText(s,m){
  // Two-phase boot: every input here is a manifest row (PHASE 2). See docs: portal internals, drawer.js.
  if(hydrating("manifest"))return "loading…";
  const arts=(typeof artifactsFor==="function"?artifactsFor(s&&s.ausmt_id):[]);
  const out=[];
  if(ediDescriptor(s,m).st==="ok")out.push("EDI");
  if(arts.some(a=>a&&a.format==="emtfxml"))out.push("EMTF XML");
  // MTH5 reads the STATION's own files[] row, like its two neighbours. See docs: portal internals,
  // drawer.js.
  if(arts.some(a=>a&&a.format==="mth5"))out.push("MTH5");
  return out.length?out.join(" · "):"none currently served";}
// A publication reduced to a short lineage cite, "FirstAuthor et al. (Year)". See docs: portal internals,
// drawer.js.
function pubShortCite(p){p=p||{};
  const a=String(p.a==null?"":p.a).trim(),y=String(p.y==null?"":p.y).trim(),t=String(p.t==null?"":p.t).trim();
  const doi=String(p.doi==null?"":p.doi).trim().replace(/^https?:\/\/(?:dx\.)?doi\.org\//i,"");
  let who="";
  if(a){const sep=a.indexOf(";")>=0?";":",";
    const parts=a.split(sep).map(x=>x.trim()).filter(Boolean);
    who=(sep===";"?parts.length>1:parts.length>2)?parts[0]+" et al.":a;}
  const head=[who||t,y?"("+y+")":""].filter(Boolean).join(" ").trim();
  return head||(doi?"doi:"+doi:"");}
// The lineage PUBLICATION cell, read from the survey's related publications (pubs[], the same list the
// survey card renders). See docs: portal internals, drawer.js.
function publicationCell(m){
  const ps=(((m||{}).pubs)||[]).filter(p=>p&&typeof p==="object");
  if(!ps.length)return "none recorded";
  const p0=ps[0];
  const cite=pubShortCite(p0);
  if(!cite)return "none recorded";
  const doi=String(p0.doi==null?"":p0.doi).trim().replace(/^https?:\/\/(?:dx\.)?doi\.org\//i,"");
  const cell=doi?`<a href="${escUrl("https://doi.org/"+doi)}" target="_blank" rel="noopener noreferrer">${esc(cite)}</a>`:esc(cite);
  return cell+(ps.length>1?` <span class="prov">(+${ps.length-1} more)</span>`:"");}
function provGraph(s){const m=SMETA[s.survey]||{},sc=sciRow(s.i);
  // Two-phase boot: the Method node reads sc[SC.alg]/sc[SC.rr] (sci.json) and would otherwise fall to
  // "not stated", a claim about the source EDI, before the row exists.
  const methodGate=hydrGate("sci","processing method");
  const nodes=[];
  // An upstream "source dataset" node when the survey declares sources[] - the lineage's origin,
  // above the raw time series. Shows the first source's title + identifier link (with a "+N more" tail).
  const srcs=(m.sources||[]);
  if(srcs.length){const s0=srcs[0]||{};const idv=(s0.identifier||"").toString().trim();
    const lbl=esc((s0.title||"source dataset").toString().trim())+(srcs.length>1?` <span class="prov">(+${srcs.length-1} more)</span>`:"");
    nodes.push(["Source dataset",idv?`${lbl} · ${pidLink(idv)}`:lbl]);}
  nodes.push(
   ["Raw time series",m.ts==="ok"?tsCollectionCell(m):"not located in source archives"],
   ["Processing software",esc(processingSoftwareText(m,sc))]);
  // "Method" renders only where the source file actually states an algorithm or a remote reference, or
  // while sci.json is still in flight, where the honest answer is that the answer is not known yet. See
  // docs: portal internals, drawer.js.
  if(methodGate||sc[SC.alg]||sc[SC.rr])
    nodes.push(["Method",methodGate||(sc[SC.alg]?esc(sc[SC.alg]):"remote reference (stated)")]);
  // The file-WRITER, under its own heading, next to the processor it is not. Read from station.json
  // (loadStationFrameLine's fetch), so the cell is a placeholder the async resolve fills in; on a re-render
  // the cache answers synchronously. See docs: portal internals, drawer.js.
  if(isOpenAccess(m)){
    const _fw=stationFactsOf(s);
    nodes.push(["File written by",
      `<span id="lineage-fwb" data-ausmt="${escAttr(s.ausmt_id)}">${_fw?esc(_fw.writer):"loading…"}</span>`]);
  }
  nodes.push(
   ["Transfer function",`${s.nper} periods · ${esc(s.comps.split("").join("+"))||"-"}`],
   ["Distributed formats",esc(distributedFormatsText(s,m))],
   ["Publication (interpretation)",publicationCell(m)]
  );
  return `<div class="lineage">`+nodes.map((n,k)=>`<div class="lrow"><span class="ldot"></span><div><div class="lt">${esc(n[0])}</div><div class="lv">${n[1]}</div></div></div>`+(k<nodes.length-1?`<div class="lconn"></div>`:"")).join("")+`</div>`;}

function provenanceBox(s){
  // Surfaces the provenance the pipeline already emits: per-station source file + checksum,
  // and build-level extractor/version/parameters/date/commit (from build_provenance.json).
  const P=PROV||{};
  const sha=s.sha?`<code title="${escAttr(s.sha)}">${esc(s.sha.slice(0,16))}…</code>`:"<span class='prov'>not recorded</span>";
  const D=P.parameters&&P.parameters.dimensionality;
  const params=D
    ? `median|β|&gt;${esc(D.skew_3d_deg)}° or &gt;${esc(D.pct_periods_3d_threshold)}% periods |β|&gt;${esc(D.beta_per_period_deg)}° → 3-D · ellipticity&gt;${esc(D.ellip_2d_deg)} → 2-D · &lt;${esc(Math.round((D.min_usable_period_frac||0.5)*100))}% usable → indeterminate`
    : "<span class='prov'>n/a</span>";
  const rows=[
    ["source file", esc(s.file)],
    ["SHA-256", sha],
    ["extractor", esc(P.extractor||"mt_metadata (community canonical)")],
    ["Generated by", "AusMT build pipeline ("+esc((P.pipeline||"ausmt/extract.build_portal")+(P.pipeline_version?" v"+P.pipeline_version:""))+")"],
    ["software", esc(P.software&&P.software.python?("python "+P.software.python):"n/a")],
    // No screening-parameters row renders here; `params` above is computed for the model alone.
    ["build date (UTC)", esc(P.generated?P.generated.replace("T"," ").slice(0,19):"n/a")],
    ["Build commit", P.git_commit?`<code>${esc(P.git_commit)}</code>`:"<span class='prov'>unavailable</span>"]
  ];
  // Titled "AusMT Provenance", not "Processing provenance". Every row below is about the AUSMT PIPELINE's
  // own run (extractor, pipeline version, build date, build commit), not the custodian's MT data
  // processing, and readers took the old title to mean the latter. See docs: portal internals, drawer.js.
  return `<details class="prov-d"><summary>AusMT Provenance</summary><table class="meta">`+
    rows.map(([k,v])=>`<tr><td>${esc(k)}</td><td>${v}</td></tr>`).join("")+
    `</table><div class="prov" style="margin-top:6px">Every product traces to its input file, the extractor and version`+
    `. Reproducible offline by <i>AusMT</i>.</div></details>`;
}
// The engine serves impedances AS STORED in the source's declared acquisition frame and NEVER de-rotates.
// When that frame is non-trivial we report it to the READER - terse, honest, no interpretation. See docs:
// portal internals, drawer.js.
function frameLineText(frame){
  if(!frame||typeof frame!=="object") return "";
  const az=frame.declared_azimuth_deg;
  const hasAngle=(typeof az==="number"&&isFinite(az)&&Math.abs(az)>0.01);
  const taz=frame.tipper_declared_azimuth_deg;
  const hasTip=(typeof taz==="number"&&isFinite(taz));    // the engine emits it ONLY when divergent
  const mixed=(typeof frame.survey_frame_note==="string"&&frame.survey_frame_note.trim())?frame.survey_frame_note.trim():"";
  if(!hasAngle&&!hasTip&&!mixed) return "";
  const fmt=v=>{const a=Math.round(v*10)/10;return (a>0?"+":"")+a+"°";};   // at most 1 dp, terse
  const parts=[];
  if(hasAngle) parts.push("Impedances served in the source's declared "+fmt(az)+" acquisition frame (as stored, not rotated to geographic north).");
  if(hasTip) parts.push("Tipper served in its own declared "+fmt(taz)+" frame"+(hasAngle?"":" while impedances are in the declared-zero reference")+" (as stored).");
  if(mixed) parts.push(parts.length
    ? "This survey mixes declared frames across stations."
    : "This survey mixes declared acquisition frames across stations; each station is served as stored.");
  return parts.join(" ");
}
// Per-station frame facts live ONLY in the per-station station.json (the positional catalogue has no frame
// column, and adding one would need a contract change). See docs: portal internals, drawer.js.
const _frameLineCache=new Map();                          // ausmt_id -> {line, writer} ("" line = no line)
function _injectStationFacts(s,facts){
  if(!facts) return;
  const el=document.getElementById("frameline");
  if(facts.line&&el&&el.dataset.ausmt===s.ausmt_id){       // guard: drawer may have moved on (async)
    el.textContent=facts.line;
    el.style.cssText="font-size:12px;color:var(--muted);margin:2px 0 10px;line-height:1.4";
  }
  ["lineage-fwb","provtop-fwb"].forEach(id=>{           // two cells in one tab, one fetch, same guard
    const w=document.getElementById(id);
    if(w&&w.dataset.ausmt===s.ausmt_id) w.textContent=facts.writer;
  });
}
function stationFactsOf(s){return _frameLineCache.get(s&&s.ausmt_id);}
function loadStationFrameLine(s){
  const slug=s.slug||((SMETA[s.survey]||{}).slug);
  if(!slug||!s.id) return Promise.resolve();              // cannot locate station.json - skip
  if(_frameLineCache.has(s.ausmt_id)){_injectStationFacts(s,_frameLineCache.get(s.ausmt_id));return Promise.resolve();}
  const url=dataUrl("products/"+encodeURIComponent(slug)+"/"+encodeURIComponent(s.id)+"/station.json");
  // The catch sits on the FETCH, not on the whole chain, so a withheld/offline/file:// station caches its
  // no-line outcome (and is not re-requested) while a throw in the render step below caches nothing and is
  // simply retried, exactly as before.
  return fetch(url).then(r=>r.ok?r.json():null).catch(()=>null).then(doc=>{   // withheld / offline / file:// => no line
    const facts={line:(doc&&doc.frame)?(frameLineText(doc.frame)||""):"",
                 writer:doc?fileWrittenByText((doc.processing||{}).file_written_by)
                           :"could not be loaded"};
    _frameLineCache.set(s.ausmt_id,facts);
    _injectStationFacts(s,facts);
  }).catch(()=>{});
}
// The five Screening indicators, each derived ONLY from a quantity the pipeline already computes. PURE (no
// DOM) so the field->indicator->threshold mapping is falsifiable: flip one input and exactly one indicator
// flips state. See docs: portal internals, drawer.js.
function screeningIndicators(d){
  d=d||{};
  const na={state:"na",word:"not evaluated"};
  const band=(v,g,a,gw,aw,rw)=>v==null?na:(v>=g?{state:"green",word:gw}:v>=a?{state:"amber",word:aw}:{state:"red",word:rw});
  const smooth=band(d.q,4,3,"Clean","Fair","Rough");
  const strike=(d.azN==null||d.azN<3||d.azR==null)?na:band(d.azR,0.9,0.75,"Stable","Variable","Unstable");
  let pt;
  if(d.beta==null)pt=na;
  else{const thr=(d.betaThr!=null&&isFinite(d.betaThr))?d.betaThr:5;   // PROV skew_3d_deg, else a 5° default
    pt=d.beta<=thr?{state:"green",word:"Consistent"}:d.beta<=2*thr?{state:"amber",word:"Mixed"}:{state:"red",word:"Complex"};}
  const psplit=(d.phaseSplit==null)?na:(d.phaseSplit<=15?{state:"green",word:"Aligned"}:d.phaseSplit<=35?{state:"amber",word:"Moderate"}:{state:"red",word:"Split"});
  const cov=band(d.decades,4,2,"Broad","Moderate","Narrow");
  return [
    {key:"smoothness",label:"Smoothness",state:smooth.state,word:smooth.word},
    {key:"strike",label:"Strike stability",state:strike.state,word:strike.word},
    {key:"pt",label:"Phase tensor consistency",state:pt.state,word:pt.word},
    {key:"phasesplit",label:"Phase split",state:psplit.state,word:psplit.word},
    {key:"coverage",label:"Coverage",state:cov.state,word:cov.word},
  ];
}
function _indGlyph(st){return st==="green"?"✔":st==="amber"?"◐":st==="red"?"✗":"◌";}
function _indWord(st){return st==="green"?"Green":st==="amber"?"Amber":st==="red"?"Red":"-";}
function screeningIndicatorList(inds){
  return `<ul class="indlist">`+inds.map(it=>{
    const cls=it.state==="green"?"ok":it.state==="amber"?"part":it.state==="red"?"no":"na";
    const stateTxt=it.state==="na"?"not evaluated":_indWord(it.state)+" · "+esc(it.word);
    return `<li class="indrow ind-${cls}"><span class="indglyph">${_indGlyph(it.state)}</span>`+
      `<span class="indlabel">${esc(it.label)}</span><span class="indstate">${stateTxt}</span></li>`;
  }).join("")+`</ul>`;}
// The "Station summary" collapsible under the Response plots, in four fixed groups.
// DATA_CHECKS_LABEL is a ONE-STRING seam: change the one constant to re-label that group.
const DATA_CHECKS_LABEL="Data checks";
function _ssGroup(title,rows,extra){
  return `<div class="ssgroup"><div class="ssg-h">${esc(title)}</div><table class="meta">`+
    rows.map(([k,v])=>`<tr><td>${esc(k)}</td><td>${v}</td></tr>`).join("")+`</table>${extra||""}</div>`;}
function stationSummaryDetails(s,m,sc){
  // The Station group. Rows APPEND after coordinates (never reorder): the source station/site name
  // (only when it differs from the displayed, sanitised id - the SA28_2B -> SA282B case), the data type,
  // the ausmt_id, and the collection title (row omitted entirely when the survey is in no collection).
  const stationRows=[["coordinates",coordCellHtml(s)]];
  if(s.site_name&&s.site_name!==s.id)stationRows.push(["site name",esc(s.site_name)]);
  stationRows.push(["data type",esc(s.type||"-")]);   // no long-form gloss exists in the corpus yet; show the code
  stationRows.push(["ausmt_id",esc(s.ausmt_id)]);
  if(m.collection&&m.collection.id)stationRows.push(["collection",esc(m.collection.title||m.collection.id)]);
  // This summary group offers no download tile: a summary states facts and the Files tab serves
  // bytes, which is the separation the tabs exist to draw. See docs: portal internals, drawer.js.
  const station=_ssGroup("Station",stationRows);
  // Two-phase boot: periods/components/tipper are catalogue columns (phase 1, honest at first paint);
  // "remote reference" and the Processing group read the sci row (PHASE 2), whose absent-value renderings
  // ("not recorded", "not stated in EDI") are claims about the source EDI. Those two wait.
  const sciGate=hydrGate("sci","processing details");
  const tf=_ssGroup("Transfer function",[
    ["periods",`${fmtRange(fmtPeriod(s.pmin),fmtPeriod(s.pmax))} s`],
    ["components",(esc(s.comps.split("").join(" + "))||"-")],
    ["tipper",s.comps.includes("T")?"yes":"no"],
    ["remote reference",sciGate||(sc[SC.rr]?"yes":"not recorded")]]);
  // No "Data checks" group renders here: the TF error is not shown to readers. SC.mre and
  // DATA_CHECKS_LABEL stay defined because the column index and the label are part of the sc.json
  // vocabulary, which the products keep whether or not this surface renders.
  const proc=_ssGroup("Processing",[
    ["software",sciGate||(sc[SC.sw]?esc(sc[SC.sw]):"not stated in EDI")],
    ["source",esc(s.file)]]);
  return `<details class="prov-d ssdetails"><summary>Station summary</summary><div class="prov-dbody ssbody">${station}${tf}${proc}</div></details>`;
}
// Two-phase boot: `opts.rehydrate` marks a re-render driven by a phase-2 product LANDING (main.js
// wireHydration -> rehydrateOpenDrawer), not by a reader opening the drawer. See docs: portal internals,
// drawer.js.
function openStation(i,opts){
  const rehydrate=!!(opts&&opts.rehydrate);
  const keepScroll=rehydrate?(drawer.scrollTop||0):0;
  const keepTab=rehydrate?_curDrawerTab:"response";
  const keepOpen=rehydrate?_openDetailsKeys():[];     // expanders the reader opened mid-hydration stay open
  if(!rehydrate)_rememberDrawerOpener();              // capture the invoking element before the rewrite
  _drawerSubject={kind:"station",i};                  // what rehydrateOpenDrawer re-renders when a gate settles
  const s=ST[i],t=tfRow(i)||[[]],m=SMETA[s.survey]||{},sc=sciRow(i);
  // sc[SC.dim] (dimensionality) is not surfaced in the drawer screening grid: it is inferable from the
  // phase tensor + skew, which are shown (strike/|β|/3-D-periods line below). See docs: portal internals,
  // drawer.js.
  const p3d=sc[SC.p3d],gd=sc[SC.gd],skew=sc[SC.skew],dec=sc[SC.decades];
  if(!rehydrate)location.hash="#/station/"+encodeURIComponent(s.ausmt_id);   // ausmt_id is globally unique; s.id (DATAID) repeats across surveys
  const azs=[],azPers=[];if(t[T.pt_az])t[T.pt_az].forEach((a,k)=>{if(a!=null&&t[T.pt_beta][k]!=null&&Math.abs(t[T.pt_beta][k])<5){azs.push(((a%180)+180)%180);const _pk=t[T.periods]&&t[T.periods][k];if(_pk!=null)azPers.push(_pk);}});
  const _perTxt=azPers.length?` over ${fmtRange(fmtPeriod(Math.min(...azPers)),fmtPeriod(Math.max(...azPers)))} s`:"";
  // Per-period 3-D screening threshold echoed from the build's own provenance (never hard-coded); when
  // build_provenance.json isn't loaded the degree figure is simply omitted rather than fabricated.
  const _bp=(typeof PROV!=="undefined"&&PROV&&PROV.parameters&&PROV.parameters.dimensionality)||{};const _betaThr=_bp.beta_per_period_deg;
  // Strike circular concentration (mean resultant length R on the doubled axial angles) - the Strike-
  // stability indicator's input, and the same doubled-angle mean feeds the strike clause below.
  let strikeClause=`median phase-tensor strike <b>not estimated</b> <span style="color:var(--muted)">(insufficient low-skew data)</span>`;
  let _azR=null;
  if(azs.length>=1){const rad=azs.map(a=>2*a*Math.PI/180);
    const _S=rad.reduce((s,x)=>s+Math.sin(x),0),_C=rad.reduce((s,x)=>s+Math.cos(x),0);
    _azR=Math.hypot(_S,_C)/azs.length;
    if(azs.length>=3){const mean=Math.atan2(_S,_C)/2*180/Math.PI;const st=((mean%180)+180)%180;
      strikeClause=`median phase-tensor strike <b>~N${st.toFixed(0)}°E / N${((st+90)%180).toFixed(0)}°E</b> <span style="color:var(--muted)">(90° ambiguous)</span>${_perTxt}`;}}
  // Median xy/yx phase split (deg) - the Phase-split indicator's input (φyx already +180°-adjusted).
  let _phaseSplit=null;
  if(t[T.phs_xy]&&t[T.phs_yx_adj]){const _sp=[];t[T.phs_xy].forEach((v,k)=>{const w=t[T.phs_yx_adj][k];if(v!=null&&w!=null)_sp.push(Math.abs(v-w));});
    if(_sp.length){_sp.sort((a,b)=>a-b);_phaseSplit=_sp[Math.floor(_sp.length/2)];}}
  const _inds=screeningIndicators({q:sc[SC.q],azR:_azR,azN:azs.length,beta:skew,betaThr:_bp.skew_3d_deg,phaseSplit:_phaseSplit,decades:dec});
  const keysafe=s.ausmt_id.replace(/[^a-z0-9]/g,"_");
  // ---- Sticky header (identity + chips + primary actions) + tab strip -------------------
  const typeChip=`<span class="chip" style="background:${TYPE_COL[s.type]||"#999"}${TYPE_INK[s.type]?";color:"+TYPE_INK[s.type]:""}">${esc(s.type)}</span>`;
  const collChip=(m.collection&&m.collection.id)?`<span class="chip collchip" data-act="collection" data-coll="${escAttr(m.collection.id)}" title="Explore collection">${esc(m.collection.title||m.collection.id)}</span>`:"";
  // Acquisition year: the survey's declared dates string, else its year_start(-end) range; omitted if
  // neither. This was a verbatim second copy of acqYearText, which is how the station chip could have
  // kept an en-dash range while the card moved to the spaced hyphen; it now calls the one helper.
  const yearTxt=acqYearText(m);
  const yearChip=yearTxt?`<span class="hchip">${yearTxt}</span>`:"";
  const licBadge=badge(licHuman(m.lic)||"licence ?",licBadgeState(m.lic));
  // Four tabs, Response first and selected. Its "Station summary" collapsible carries the station
  // facts, and no Screening tab renders.
  const TABS=[["response","Response"],["files","Files"],["provenance","Provenance"],["cite","Cite"]];
  const tabStrip=`<div class="seg dtabs" role="tablist" aria-label="Station detail sections">`+
    TABS.map(([id,label],k)=>`<button role="tab" id="dt-${id}" data-act="tab" data-tab="${id}" aria-controls="dp-${id}" aria-selected="${k===0}" tabindex="${k===0?0:-1}"${k===0?' class="on"':""}>${esc(label)}</button>`).join("")+`</div>`;
  const header=`<div class="dtop">`+
    `<div class="dhead"><span class="sid">${esc(s.id)}</span>${typeChip}${collChip}<button class="close" aria-label="Close">✕</button></div>`+
    `<div class="dsub">${esc(s.survey)} · ${orgNameLink(s.org,m.org_ror)} · ${esc(s.country)}</div>`+
    collLine(m)+
    `<div class="dchips">${yearChip}${licBadge}</div>`+
    // The header carries no "Cite" tab-jump button: the Cite TAB already reaches that panel, so
    // the header keeps only the Download EDI primary action.
    `<div class="dactions">${headerDownloadBtn(s,m)}</div>`+
    tabStrip+`</div>`;
  // ---- Panel content -------------------------------------------------------------------------------
  // Response (default) - the four plots FIRST, the centerpiece. See docs: portal internals, drawer.js.
  const _rspOpen=isOpenAccess(m);
  // Two-phase boot: the curves live in tf.json (PHASE 2). See docs: portal internals, drawer.js.
  const _tfGate=_rspOpen?hydrGate("tf","response functions",true):"";
  const responseHtml=`<div class="sechead rsphead">Response functions ${roleChip("AusMT-derived")}`+
    (_rspOpen&&!_tfGate&&typeof responseExpandBtn==="function"?responseExpandBtn():"")+`</div>`+
    (_tfGate
      ? _tfGate+`<div id="pt_anchor"></div>`
      : _rspOpen
      ? plotBlock("rho",t)+plotBlock("phase",t)+`<div id="pt_anchor"></div>`+plotBlock("pt",t)+plotBlock("arrow",t)
      : accessPanel(m,s.survey)+`<div id="pt_anchor"></div>`)+
    `<div id="frameline" data-ausmt="${escAttr(s.ausmt_id)}"></div>`+
    stationSummaryDetails(s,m,sc);
  // NO SCREENING SURFACE RENDERS in the drawer: the automated indicators are not public, so there is no
  // "screening" panel and no ["screening","Screening"] TABS entry. See docs: portal internals, drawer.js.
  const filesHtml=`<div class="sechead">Related products</div>`+relatedProducts(s);
  // Provenance: three source-data rows visible (processing software, transfer function source file+sha ·
  // source archive), then the Dataset-maturity stars, then EVERYTHING ELSE (lineage graph, full provenance
  // table, identifiers, format availability). See docs: portal internals, drawer.js.
  const _srcArchive=sourceArchiveCell(m);
  // This station's served artifact rows (manifest `files`), read once and reused by the format-availability
  // badge and the API section below. See docs: portal internals, drawer.js.
  const _manGate=hydrGate("manifest","served files",true);
  const _arts=(typeof artifactsFor==="function"?artifactsFor(s.ausmt_id):[]);
  // Whether a served EMTF-XML artifact exists for this station (drives the format-availability badge:
  // ok when served, else part - produced via the build pipeline for redistributable surveys).
  const _fmtXmlArt=_arts.some(a=>a.format==="emtfxml");
  // The same question for MTH5, off the same station rows. See docs: portal internals, drawer.js.
  const _fmtH5Art=_arts.some(a=>a.format==="mth5");
  // The writer row rides alongside the processing-software row for the same reason it does in the lineage
  // graph. Same cache, same async fill, own element id (two injection targets, one fetch). See docs: portal
  // internals, drawer.js.
  const _fwTop=stationFactsOf(s);
  const provTop=`<table class="meta prov-top">`+
    `<tr><td>Processing software</td><td>${esc(processingSoftwareText(m,sc))}</td></tr>`+
    (isOpenAccess(m)?`<tr><td>File written by</td><td><span id="provtop-fwb" data-ausmt="${escAttr(s.ausmt_id)}">${_fwTop?esc(_fwTop.writer):"loading…"}</span></td></tr>`:"")+
    `<tr><td>Transfer function</td><td>${esc(s.file)}${s.sha?` · <code title="${escAttr(s.sha)}">${esc(s.sha.slice(0,16))}…</code>`:" · <span class='prov'>no checksum</span>"}</td></tr>`+
    `<tr><td>Source archive</td><td>${_srcArchive}</td></tr></table>`;
  const metaTable=`<table class="meta">`+
    `<tr><td>ausmt_id</td><td>${esc(s.ausmt_id)}</td></tr>`+
    // Coordinate access: a custodian-withheld station carries null lat/lon (masked VALUE), so show the
    // honest withheld line instead of null-derefing .toFixed. See docs: portal internals, drawer.js.
    `<tr><td>lat, lon</td><td>${coordCellHtml(s)}</td></tr>`+
    `<tr><td>components</td><td>${esc(s.comps.split("").join(" + "))||"-"}</td></tr>`+
    `<tr><td>source file</td><td>${esc(s.file)}</td></tr></table>`;
  // The Metadata & API box collapses to a single small "API" expander at the tab's foot. No /api tier has
  // ever existed on any AusMT deployment, so the section must never advertise one. See docs: portal
  // internals, drawer.js.
  const _apiSlug=s.slug||((SMETA[s.survey]||{}).slug)||"";
  const _apiEdi=_arts.find(a=>a.format==="edi");
  const _apiRows=[];
  if(_apiSlug&&s.id)_apiRows.push("/data/products/"+encodeURIComponent(_apiSlug)+"/"+encodeURIComponent(s.id)+"/station.json");
  if(_apiEdi&&_apiEdi.url)_apiRows.push(apiArtifactPath(_apiEdi.url));
  _apiRows.push("/data/manifest.json");
  // Two-phase boot: the per-station EDI line is READ from a manifest row, and "no row => no line" is a
  // deliberate embargo signal. See docs: portal internals, drawer.js.
  const apiBlock=`<div class="api">Read-only static JSON on the hosted site, no key required:<br>`+
    _apiRows.map(u=>`GET <b>${esc(u)}</b>`).join("<br>")+
    (_manGate?`<br>${_manGate}`:"")+
    `<br><a href="https://ausmt.readthedocs.io/en/latest/interoperability/api-reference/">worked examples in the API reference</a></div>`;
  const provenanceHtml=`<div class="sechead">Provenance ${roleChip("Source data")}</div>`+provTop+maturityBlock(s)+
    `<details class="prov-d"><summary>Lineage graph</summary><div class="prov-dbody">${provGraph(s)}</div></details>`+
    provenanceBox(s)+
    // OMIT the Identifiers & instruments expander entirely when there is nothing to show
    // (a zero-identifier survey), rather than rendering an empty disclosure.
    (identifiersHtml(m)?`<details class="prov-d"><summary>Identifiers &amp; instruments</summary><div class="prov-dbody">${identifiersHtml(m)}</div></details>`:"")+
    // The badge set tells the DISTRIBUTED-FORMATS story - EDI, EMTF XML (via pipeline), MTH5, time series
    // (from the levels metadata) and the licence badge. See docs: portal internals, drawer.js.
    `<details class="prov-d"><summary>Format availability</summary><div class="prov-dbody">${_manGate||`<div class="badges">${badge("EDI","ok")}${badge("EMTF XML",_fmtXmlArt?"ok":"part","EMTF XML is produced in the build pipeline (mt_metadata); served for redistributable surveys.")}${badge("MTH5",_fmtH5Art?"ok":"unk","Per-station MTH5 (transfer functions only) is written where the build produced one; the survey's whole-survey bundle, when there is one, is offered on the survey page.")}${badge("time series",(m.ts_levels&&m.ts_levels.length)?"ok":(m.ts||"unk"))}${licBadge}${s.fixed?badge("coord QC","part","Coordinates were flagged during QC; see this station's provenance and treat with caution."):""}</div>`}</div></details>`+
    `<details class="prov-d"><summary>Record metadata</summary><div class="prov-dbody">${metaTable}</div></details>`+
    `<details class="prov-d"><summary>API</summary><div class="prov-dbody">${apiBlock}</div></details>`;
  // Cite - the citation box. A no-cite survey is EXPLICIT ("custodian citation not recorded - cite the
  // survey package") rather than a silent AUSMT_SELF masquerade, and the captured attribution statement
  // (verbatim, else org(year) synthesis) renders alongside. See docs: portal internals, drawer.js.
  const _attn=attributionText(m);
  // The citation box renders the DOI as a resolution-aware hyperlink (apaCiteDisplay); the copy buttons
  // below still assemble plain-text apa()/bibtex()/ris() strings via the [data-cite] handler.
  const citeBody=m.cite
    ? apaCiteDisplay(m.cite,m.doi,m.doi_resolution)
    : `<div class="prov" style="margin-bottom:6px">Custodian citation not recorded, cite the survey package:</div>${apaCiteDisplay(AUSMT_SELF,m.doi,m.doi_resolution)}`;
  const citeHtml=`<div class="sechead">Cite this station's source</div><div class="citebox">${citeBody}`+
    (_attn?`<div class="attn"><b>Attribution:</b> ${esc(_attn)}</div>`:"")+
    `<div class="cb-row"><button data-cite="apa" data-survey="${escAttr(s.survey)}">APA</button>`+
    `<button data-cite="bibtex" data-survey="${escAttr(s.survey)}" data-key="${escAttr(keysafe)}">BibTeX</button>`+
    `<button data-cite="ris" data-survey="${escAttr(s.survey)}">RIS</button></div></div>`;
  drawer.innerHTML=header+
    drawerPanel("response",responseHtml,true)+
    // No Screening panel is concatenated here: the automated indicators are not a public surface.
    drawerPanel("files",filesHtml,false)+
    drawerPanel("provenance",provenanceHtml,false)+
    drawerPanel("cite",citeHtml,false);
  _curTf=t;                                        // stash for the expand-modal handler
  _curStation=s;                                   // stash the station for the response modal's identity header
  drawer.setAttribute("aria-label","Station "+s.id+" details");   // the dialog label names its subject
  drawer.classList.add("open");drawer.scrollTop=keepScroll;showDrawerScrim();   // D: dim backdrop on non-map views
  selectDrawerTab(keepTab);                        // Response is the default tab (a rehydrate keeps the reader's tab)
  _restoreOpenDetails(keepOpen);                   // and the expanders they had open (empty on a real open)
  if(!rehydrate)_focusDrawer();                    // move focus into the dialog (never on a hydration re-render)
  if(isOpenAccess(m)) loadStationFrameLine(s);     // inject the frame line if this station declares one
}
// The hash prefixes that describe SOMETHING OPEN IN THE DRAWER, and which a close must therefore hand back
// to the plain root. See docs: portal internals, drawer.js.
const HASH_ROUTES_CLEARED_ON_CLOSE=["#/station","#/survey"];
// Two-phase boot: re-render whatever the drawer is currently showing, IN PLACE, because a phase-2 product
// just landed and one of its sections was rendering a loading state. See docs: portal internals, drawer.js.
function rehydrateOpenDrawer(){
  if(!_drawerSubject)return;
  if(!(drawer&&drawer.classList&&drawer.classList.contains&&drawer.classList.contains("open")))return;
  if(_drawerSubject.kind==="station"&&ST[_drawerSubject.i])openStation(_drawerSubject.i,{rehydrate:true});
  else if(_drawerSubject.kind==="survey")openSurvey(_drawerSubject.sv,{rehydrate:true});
}
function closeDrawer(){const wasOpen=drawer.classList.contains&&drawer.classList.contains("open");
  _drawerSubject=null;                                 // nothing to rehydrate once it is shut
  drawer.classList.remove("open");hideDrawerScrim();   // D: drop the dim backdrop
  // The SURVEY hash is cleaned up on exactly the same terms the station hash always was. See docs: portal
  // internals, drawer.js.
  if(HASH_ROUTES_CLEARED_ON_CLOSE.some(p=>location.hash.startsWith(p)))history.replaceState(null,"",location.pathname+location.search);
  // The survey focus dim is a VIEW state owned by the open drawer, so it lifts with it.
  // Opacity only, never a layer rebuild, so nothing reloads on close.
  if(typeof clearSurveyDim==="function")clearSurveyDim();
  if(wasOpen)_restoreDrawerFocus();}               // return focus to the invoking element (only if it was open)
async function fetchEdi(file,avail,survey){
  // This EDI isn't redistributable here. Its dataset DOI (m.doi), when the survey has one, is the TF source
  // archive and is safe to open. See docs: portal internals, drawer.js.
  if(!avail){const m=SMETA[survey]||{};
    if(m.doi){toast("This EDI isn't redistributable here; opening the source archive.");
      window.open("https://doi.org/"+m.doi,"_blank","noopener,noreferrer");}
    else toast("This EDI isn't redistributable here: "+withheldReason(m)+".");
    return;}
  // Route through dataUrl() (honours data_base_url) - NOT a hardcoded "data/edi/" path, so the
  // portal and its data can live in separate repos / on NCI.
  return downloadUrl(dataUrl("edi/"+file),file);}
// Generic blob download for a resolved manifest URL (EMTF XML, per-survey bundles, EDI fallback).
async function downloadUrl(url,filename){
  try{const r=await fetch(url);if(!r.ok)throw 0;const b=await r.blob();
    const a=document.createElement("a");a.href=URL.createObjectURL(b);a.download=filename||url.split("/").pop();a.click();URL.revokeObjectURL(a.href);}
  catch(e){toast("Download works when served over HTTP next to the data files; can't fetch over file://.");}}
function copyTxt(t){navigator.clipboard?.writeText(t).then(()=>toast("Copied.")).catch(()=>toast("Copy failed; select manually."));}

// A survey's declared acquisition window as display text - the dates string when present,
// else the year_start(-end) range; "" when neither is declared (caller omits the field). Shared by the
// slim survey card and the compact list row so both read the same value.
function acqYearText(m){return m.dates?esc(m.dates):(m.year_start?(m.year_end&&m.year_end!==m.year_start?fmtRange(esc(String(m.year_start)),esc(String(m.year_end))):esc(String(m.year_start))):"");}
// SLIM survey card. Field set is deliberately reduced to: title · organisation · collection chip ·
// acquisition year · station count · data-type mixbar · period range · licence + DOI badges · short
// description · two actions (View survey, Download). See docs: portal internals, drawer.js.
function surveyCard(sv){const ss=ST.filter(s=>s.survey===sv),m=SMETA[sv]||{};
  const mix={};ss.forEach(s=>mix[s.type]=(mix[s.type]||0)+1);
  const pmin=Math.min(...ss.map(s=>s.pmin)),pmax=Math.max(...ss.map(s=>s.pmax));
  const mixbar=Object.entries(mix).map(([ty,n])=>`<div style="width:${100*n/ss.length}%;background:${TYPE_COL[ty]}" title="${esc(ty)}: ${n}"></div>`).join("");
  const yearTxt=acqYearText(m);
  return `<div class="scard"><div class="scardhead"><h3><a href="/surveys/${escAttr(m.slug||sv)}" title="Open survey">${esc(sv)}</a></h3>`+(m.collection&&m.collection.id?`<span class="chip collchip" data-act="collection" data-coll="${escAttr(m.collection.id)}" title="Explore collection">${esc(m.collection.title||m.collection.id)}</span>`:"")+`</div><div class="cust">${orgNameLink(m.org||"custodian unknown",m.org_ror)} · ${esc(m.country||"")}</div>`+
   surveyLocator(ss)+
   `<div class="mixbar">${mixbar}</div>`+
   `<div class="stats"><b>${ss.length}</b> station${ss.length===1?"":"s"}${yearTxt?` · acquired <b>${yearTxt}</b>`:""}<br>periods <b>${fmtRange(fmtPeriod(pmin),fmtPeriod(pmax))} s</b></div>`+
   `<div class="badges">${badge(licHuman(m.lic)||"licence ?",licBadgeState(m.lic))}${badge("DOI",hasDatasetDoi(m)?"ok":"no")}</div>`+
   `<div class="cardbtns"><a class="primary" href="/surveys/${escAttr(m.slug||sv)}">View survey →</a><button data-act="select" data-survey="${escAttr(sv)}">Download</button></div></div>`;}
// Per-survey card locator: the SAME fixed-Australia frame as the
// collection scatter, one survey's stations only, dots coloured by DATA TYPE with the portal's own
// palette (the card's mixbar is the legend). Degrades like collScatter when AU_OUTLINE is absent.
function surveyLocator(ss){
  if(!ss.length) return "";
  const W=300,H=Math.round(W*(AU_EXTENT.no-AU_EXTENT.so)/(AU_EXTENT.e-AU_EXTENT.w)),pad=10;
  const proj=(lon,lat)=>[pad+(lon-AU_EXTENT.w)/(AU_EXTENT.e-AU_EXTENT.w)*(W-2*pad),
                         pad+(AU_EXTENT.no-lat)/(AU_EXTENT.no-AU_EXTENT.so)*(H-2*pad)];
  let outline="";
  if(typeof AU_OUTLINE!=="undefined"&&AU_OUTLINE){
    const pts=r=>r.map(([lo,la])=>{const p=proj(lo,la);return p[0].toFixed(1)+","+p[1].toFixed(1);}).join("L");
    const coast=(AU_OUTLINE.coast||[]).map(r=>`<path d="M${pts(r)}Z" fill="#1d3140" stroke="#3a5266" stroke-width="1"/>`).join("");
    outline=`<g>${coast}</g>`;
  }
  const withPos=ss.filter(hasPosition);
  const r=withPos.length>200?1.6:2.2;
  const dots=withPos.map(s=>{const p=proj(s.lon,s.lat);
    return `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="${r}" fill="${TYPE_COL[s.type]||"#4FC3D9"}" fill-opacity=".9"/>`;}).join("");
  // Compact-footprint marker: a deposit-scale survey is a lone
  // sub-pixel dot on a continent, so it gains a ring + a station-count pill at the centroid -
  // where AND how much, at a glance. State-scale footprints read on their own and get neither.
  let marker="";
  if(withPos.length){
    const lons=withPos.map(s=>s.lon),lats=withPos.map(s=>s.lat);
    const ext=Math.max(Math.max(...lons)-Math.min(...lons),Math.max(...lats)-Math.min(...lats));
    if(ext<2){
      const c=proj(lons.reduce((a,b)=>a+b)/lons.length,lats.reduce((a,b)=>a+b)/lats.length);
      const label=String(withPos.length);
      const pw=label.length*7+14;
      const px=Math.min(Math.max(c[0]-pw/2,4),W-pw-4),py=c[1]>36?c[1]-30:c[1]+16;
      marker=`<circle cx="${c[0].toFixed(1)}" cy="${c[1].toFixed(1)}" r="8" fill="none" stroke="#EF7256" stroke-width="1.6" opacity=".85"/>`+
        `<rect x="${px.toFixed(1)}" y="${py.toFixed(1)}" width="${pw}" height="16" rx="8" fill="#18213D" stroke="#EF7256" stroke-width="1"/>`+
        `<text x="${(px+pw/2).toFixed(1)}" y="${(py+11.5).toFixed(1)}" text-anchor="middle" fill="#EF7256" font-size="10" font-weight="600" font-family="ui-monospace,Menlo,monospace">${label}</text>`;
    }
  }
  return `<div class="card-locator"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Survey location in Australia">${outline}${dots}${marker}</svg></div>`;
}
function pidLink(p){if(!p)return "<span class='prov'>not recorded</span>";if(p.startsWith("TODO"))return "<span class='prov'>not recorded</span>";
  const href=p.startsWith("http")?p:(p.startsWith("10.")?"https://doi.org/"+p:"https://hdl.handle.net/"+p);return `<a href="${escUrl(href)}" target="_blank" rel="noopener noreferrer">${esc(p)}</a>`;}
// A person's ORCID as a small icon-link (self-hosted vendor logo, CSP-safe same-origin); "" when absent,
// so callers append it directly after the escaped name.
function orcidLink(o){if(!o)return "";const href="https://orcid.org/"+o;
  return ` <a href="${escUrl(href)}" target="_blank" rel="noopener noreferrer" title="ORCID: ${escAttr(o)}" class="orcid-ico"><img src="vendor/ORCID_iD.png" alt="ORCID" class="idlogo orcid-logo"></a>`;}
// Credit model: the DataCite contributorType subset -> a human role phrase. Fail-closed vocab;
// an absent or out-of-vocab role adds no phrase (the validator blocks a bad token upstream, so this never
// echoes a raw token).
const CONTRIBUTOR_ROLE_LABELS={ProjectLeader:"led",ProjectMember:"project member",DataCollector:"collected the data",
  ContactPerson:"contact",DataCurator:"curated",Sponsor:"sponsored",RightsHolder:"rights holder",Distributor:"distributed"};
// The display order for a person's role phrases when they hold several. See docs:
// portal internals, drawer.js.
const CONTRIBUTOR_ROLE_ORDER=["ProjectLeader","ProjectMember","DataCollector","ContactPerson","DataCurator","Sponsor","RightsHolder","Distributor"];
// An ORCID grouping key: lower-cased, resolver-prefix stripped, trailing slashes dropped, so the bare id
// and the full https://orcid.org/<id> URL form collapse to the SAME person. "" when no ORCID (the caller
// then dedupes on name + name_type instead).
function orcidKey(o){return o?String(o).trim().toLowerCase().replace(/^https?:\/\/orcid\.org\//,"").replace(/\/+$/,""):"";}
// One contributor's NAME cell (no role phrase): an organisation links to its ROR, a person carries the
// ORCID icon-link. Shared by the grouped Contributors list. See docs: portal internals, drawer.js.
function contributorName(c){
  const name=((c&&c.name)||"").toString().trim();
  if(!name)return "";
  return c.name_type==="organisation"?orgNameLink(name,c.ror):esc(name)+orcidLink(c.orcid);}
// Credit model: the survey's contributors[] as a COLLAPSED <details> (styled like the
// Persistent-identifiers rollup), GROUPED by person. See docs: portal internals, drawer.js.
function contributorsHtml(m){
  const list=((m&&m.contributors)||[]).filter(c=>c&&typeof c==="object");
  const groups=[],byKey=Object.create(null);
  list.forEach(c=>{
    const name=((c&&c.name)||"").toString().trim();
    if(!name)return;                                             // nameless row: dropped, uncounted
    const key=c.orcid?"o:"+orcidKey(c.orcid):"n:"+(c.name_type||"")+":"+name;
    let g=byKey[key];
    if(!g){g={c:c,roles:[]};byKey[key]=g;groups.push(g);}        // first appearance owns the name/link
    if(c.role&&CONTRIBUTOR_ROLE_LABELS[c.role]&&g.roles.indexOf(c.role)<0)g.roles.push(c.role);});
  if(!groups.length)return "";
  const rows=groups.map(g=>{
    const phrases=CONTRIBUTOR_ROLE_ORDER.filter(r=>g.roles.indexOf(r)>=0).map(r=>CONTRIBUTOR_ROLE_LABELS[r]);
    return phrases.length?`${contributorName(g.c)} <span class="prov">${phrases.map(esc).join(", ")}</span>`:contributorName(g.c);});
  return `<details class="prov-d survey-contributors"><summary>Contributors (${groups.length})</summary>`+
    `<div class="prov-dbody"><div class="surveymeta">${rows.join("<br>")}</div></div></details>`;}
// Credit model: the survey's ORDERED creators[], the attribution-author list. Order IS the
// attribution order; a person carries the ORCID icon-link, an organisation's name links to its ROR. See
// docs: portal internals, drawer.js.
function creatorRow(c){
  const name=((c&&c.name)||"").toString().trim();
  if(!name)return "";
  return c&&c.name_type==="organisation"?orgNameLink(name,c.ror):esc(name)+orcidLink(c.orcid);}
// ONE attribution box, never two. The engine builds cite.au from creators[] (the same ordered list,
// names joined "; "), so a second .attn box for the creator names would carry the SAME names twice. See
// docs: portal internals, drawer.js.
function attributionBoxHtml(m){m=m||{};
  const text=attributionText(m);
  if(!text)return "";
  const norm=v=>String(v==null?"":v).replace(/\s+/g," ").trim();
  const rows=((m.creators)||[]).filter(c=>c&&typeof c==="object");
  const names=rows.map(c=>norm(c.name)).filter(Boolean);
  const stmt=((m.attribution||{}).statement||"").toString().trim();
  const who=norm((m.cite&&m.cite.au)||m.org||"");
  if(stmt||!names.length||names.join("; ")!==who)return `<div class="attn">${esc(text)}</div>`;
  const linked=rows.map(creatorRow).filter(Boolean);
  const yr=attributionYear(m);
  return `<div class="attn">${linked.join("; ")}${yr?" ("+esc(yr)+")":""}</div>`;}
// One funder rendered as its (ROR/pid-linked) name with the grant id appended in muted text when the
// funding row carries one (the engine emits grant_id only for a real declared grant; absent -> just the
// name). The Funding section owns this display; the identifiers rollup must not duplicate the funders line.
function funderHtml(f){f=f||{};
  const name=esc(f.name||"");
  const nm=f.pid?`<a href="${escUrl(f.pid)}" target="_blank" rel="noopener noreferrer">${name}</a>`:name;
  return nm+(f.grant_id?` <span class="prov">(${esc(f.grant_id)})</span>`:"");}
// A ROR value may be a bare id (00892tw58) or a full https://ror.org/... URL - resolve either to
// the canonical ror.org landing page link.
function rorLink(r){if(!r)return null;const href=r.startsWith("http")?r:"https://ror.org/"+r;return `<a href="${escUrl(href)}" target="_blank" rel="noopener noreferrer">${esc(r)}</a>`;}
// When the organisation carries a ROR, its NAME is the link to the ror.org landing page (replacing the
// separate ROR logo badge). No ROR -> plain escaped name. See docs: portal internals, drawer.js.
function orgNameLink(name,r){const t=esc(name); if(!r) return t;
  const href=r.startsWith("http")?r:"https://ror.org/"+r;
  return `<a class="orglink" href="${escUrl(href)}" target="_blank" rel="noopener noreferrer" title="ROR: ${escAttr(r)}">${t}</a>`;}
// A RAiD identifier is already a resolvable https://raid.org/... URL (per the survey.yaml comment
// and the validator's format check); a bare id falls back to that same host.
function raidLink(r){if(!r)return null;const href=r.startsWith("http")?r:"https://raid.org/"+r;return `<a href="${escUrl(href)}" target="_blank" rel="noopener noreferrer">${esc(r)}</a>`;}
// PID-schema: an instrument's `pid` is a persistent identifier for an instrument SYSTEM (the AuScope
// Instrument Registry URL/handle). See docs: portal internals, drawer.js.
function instrumentPidLink(p){if(!p)return null;const s=String(p);
  const href=s.startsWith("http")?s:(s.startsWith("10.")?"https://doi.org/"+s:"https://hdl.handle.net/"+s);
  return `<a href="${escUrl(href)}" target="_blank" rel="noopener noreferrer">${esc(s)}</a>`;}
// PID-schema: the per-instrument PID line, shown only when SMETA carries the structured `instruments` list
// (the engine attaches it ONLY when at least one instrument declares a pid - see _instruments_of). See
// docs: portal internals, drawer.js.
function instrumentPidsHtml(m){
  const list=(m.instruments||[]);
  if(!list.length)return "";
  // An instrument with a model but no PID shows JUST the model (no "(no PID)" suffix).
  const rows=list.map(i=>{const label=[i.manufacturer,i.model].filter(Boolean).map(esc).join(" ")||"instrument";
    const link=instrumentPidLink(i.pid);
    return link?`${label}: ${link}`:label;}).join("<br>");
  return `Instrument PIDs:<br><span class="pidline">${rows}</span>`;}
// The related-identifiers model: a DataCite relation maps to a human label. An
// out-of-vocab relation (should never publish - the validator FAILs it) falls back to the escaped raw
// value; a blank relation to a neutral "Related".
const RELATION_LABELS={IsDerivedFrom:"Derived from",IsVariantFormOf:"Variant form of",
  IsSupplementTo:"Supplement to",Cites:"Cites",IsPartOf:"Part of",IsSourceOf:"Source of"};
// `identifies` states WHAT the identifier points at, in NCI Table 1 data-level terms.
// See docs: portal internals, drawer.js.
const IDENTIFIES_LABELS={collection:"Collection",raw_packed:"Raw time series",level0:"Level 0, edited time series",
  level1:"Level 1, transformed time series",level2:"Level 2, processed data",level3:"Level 3, models",
  entire:"Entire dataset"};
// A typed provenance identifier resolves to a link whose host is chosen by identifier_type, ALWAYS
// through the escUrl guard (a hostile identifier value can never become an executable/relative anchor -
// same posture as pidLink/instrumentPidLink). See docs: portal internals, drawer.js.
function relatedIdHref(id,type){
  const s=String(id==null?"":id).trim(); if(!s)return null;
  const t=String(type==null?"":type);
  if(t==="DOI")return s.startsWith("http")?s:"https://doi.org/"+s;
  if(t==="Handle")return s.startsWith("http")?s:"https://hdl.handle.net/"+s;
  if(t==="URL")return s;
  return null;}
function relatedIdLink(id,type){
  const s=String(id==null?"":id); if(!s.trim())return "<span class='prov'>not recorded</span>";
  const href=relatedIdHref(id,type);
  return href?`<a href="${escUrl(href)}" target="_blank" rel="noopener noreferrer">${esc(s.trim())}</a>`:esc(s);}
// Render an identifier HONESTLY given its resolution facet from the pid_status cache (attached by
// build_portal.apply_pid_resolution). See docs: portal internals, drawer.js.
function reservedText(text){return `${esc(text)} <span class="prov reserved-note">(reserved, not yet active)</span>`;}
function resolvedOr(resolution,text,linkHtml){return resolution==="reserved"?reservedText(text):linkHtml;}
// The raw-TS collection cell: a link to the survey's OWN collection PID (or the NCI default),
// rendered as plain text + reserved note when the survey's own ts_pid is reserved. The NCI default
// collection is a known-live handle, so it is never gated (only the survey's own ts_pid carries a facet).
function tsCollectionCell(m){
  const label=m.ts_pid?"survey collection":"NCI collection";
  if(m.ts_pid&&m.ts_pid_resolution==="reserved")return reservedText(tsPidRaw(m));
  return `<a href="${escUrl(tsUrlFor(m))}" target="_blank" rel="noopener noreferrer">${label}</a>`;}
// The Provenance-tab "Source archive" cell. See docs: portal internals, drawer.js.
function sourceArchiveCell(m){m=m||{};
  const rels=(m.related_identifiers||[]).filter(r=>r&&typeof r==="object");
  for(const lvl of ["raw_packed","collection","entire"]){
    const r=rels.find(x=>x.identifies===lvl&&x.identifier);
    if(r)return r.resolution==="reserved"?reservedText(r.identifier):relatedIdLink(r.identifier,r.identifier_type);
  }
  if(m.doi)return resolvedOr(m.doi_resolution,"doi:"+m.doi,`<a href="${escUrl("https://doi.org/"+m.doi)}" target="_blank" rel="noopener noreferrer">doi:${esc(m.doi)}</a>`);
  return m.ts==="ok"?tsCollectionCell(m):"<span class='prov'>not recorded</span>";}
// The related-identifiers block: one line per typed relation (SMETA.related_identifiers, served by
// the engine mapper as always-a-list). See docs: portal internals, drawer.js.
function relatedIdentifiersHtml(m){
  const list=(m.related_identifiers||[]).filter(r=>r&&typeof r==="object");
  if(!list.length)return "";
  const rows=list.map(r=>{
    // A related_identifiers row's "identifies" field is what labels it; the relation label is the
    // fallback when the field is absent.
    const label=(r.identifies&&IDENTIFIES_LABELS[r.identifies])||RELATION_LABELS[r.relation]||(r.relation?esc(r.relation):"Related");
    const cust=r.custodian?` <span class='prov'>(${esc(r.custodian)})</span>`:"";
    // A reserved identifier renders as plain text + note, not an anchor (never a dead link).
    const idCell=r.resolution==="reserved"?reservedText(r.identifier):relatedIdLink(r.identifier,r.identifier_type);
    return `${label}: ${idCell}${cust}`;}).join("<br>");
  return `Related identifiers:<br><span class="pidline">${rows}</span>`;}
// "A persistent dataset identifier exists in this survey's provenance chain" is the reading of
// the DOI maturity badge. See docs: portal internals, drawer.js.
function hasDatasetDoi(m){return !!(m&&(m.doi||(m.related_identifiers||[]).some(r=>r&&r.identifier_type==="DOI")));}
// The rollup renders ONLY the rows that carry a value. No "not recorded", no "(no PID)", no "not recorded
// in source metadata" noise; an instrument with a model but no PID shows just the model; a group with no
// content is omitted (heading included). See docs: portal internals, drawer.js.
function identifiersHtml(m){
  const rows=[];
  if(m.doi)rows.push(`Dataset DOI: <span class="pidline">${resolvedOr(m.doi_resolution,m.doi,pidLink(m.doi))}</span>`);
  const ror=rorLink(m.org_ror); if(ror)rows.push(`Organisation ROR: <span class="pidline">${ror}</span>`);
  const raid=raidLink(m.raid); if(raid)rows.push(`Project RAiD: <span class="pidline">${raid}</span>`);
  const rel=relatedIdentifiersHtml(m); if(rel)rows.push(rel);
  if(m.instrument_model)rows.push(`Instrument model: ${esc(m.instrument_model)}`);
  if(m.instrument_pid)rows.push(`Platform/instrument PID: <span class="pidline">${instrumentPidLink(m.instrument_pid)}</span>`);
  const instr=instrumentPidsHtml(m); if(instr)rows.push(instr);
  // Funders are shown (with grant ids) by the survey card's own Funding section, and by that
  // section alone: the identifiers rollup does not repeat them here.
  if(!rows.length)return "";
  return `<div class="surveymeta"><b>Persistent identifiers &amp; instruments</b><br>${rows.join("<br>")}</div>`;}
// One related-publication citation. See docs: portal internals, drawer.js.
function pubCite(p){p=p||{};
  const doi=String(p.doi==null?"":p.doi).trim().replace(/^https?:\/\/(?:dx\.)?doi\.org\//i,"");
  const a=String(p.a==null?"":p.a).trim(),y=String(p.y==null?"":p.y).trim(),
        t=String(p.t==null?"":p.t).trim(),j=String(p.j==null?"":p.j).trim();
  const head=[a?esc(a):"",y?"("+esc(y)+")":""].filter(Boolean).join(" ");
  const seg=[head?head+".":"",t?esc(t)+".":"",j?"<i>"+esc(j)+"</i>.":""].filter(Boolean).join(" ");
  const link=doi?` <a href="${escUrl("https://doi.org/"+doi)}" target="_blank" rel="noopener noreferrer">doi:${esc(doi)}</a>`:"";
  return seg+link;}
function pubsHtml(m){const ps=(m.pubs||[]);
  if(!ps.length)return `<div class="surveymeta"><span class='prov'>No related publications recorded yet; the science pipeline can auto-suggest these from DOIs that cite the dataset.</span></div>`;
  return `<div class="surveymeta">`+ps.map(p=>"• "+pubCite(p)).join("<br><br>")+`</div>`;}
// Discovery controls for the Surveys view. State lives in this module (the controls are static in
// index.html; the coordinator/rail filters are untouched). See docs: portal internals, drawer.js.
let _sortMode="name",_cardLayout="cards";
// Presence facets. "dl" (Downloadable here) was promoted out of the map rail, where it lived as
// the Data available dropdown's "tf" option and so could not be asked at all on the Surveys view.
const _facets={lic:false,dl:false};
const _typeFacets=new Set();                        // selected data-type chips, OR-combined within the group
const _TYPE_ORDER=["BBMT","LPMT","AMT","GDS"];      // canonical chip order; only corpus-present types render
function _stationCount(sv){return ST.filter(s=>s.survey===sv).length;}
// The survey's catalogue data-type set, derived the way the card mixbar does (per-station s.type).
function _surveyTypeSet(sv){const t=new Set();ST.forEach(s=>{if(s.survey===sv&&s.type)t.add(s.type);});return t;}
// The data types actually present in the corpus, in canonical order, the type chips to render.
function _presentTypes(){const have=new Set(ST.map(s=>s.type));return _TYPE_ORDER.filter(t=>have.has(t));}
function _yearKey(m){return m.year_start!=null?m.year_start:(m.year_end!=null?m.year_end:-Infinity);}
function surveyPassesFacets(sv){const m=SMETA[sv]||{};
  if(_facets.lic&&!licIsOpen(m.lic))return false;   // "Open licence": an openly-licensed (redistributable) id per the canon tables
  // "Downloadable here": the SAME s.ediAvail predicate the map applies per station, asked of a survey
  // - it passes when ANY of its stations carries a transfer function this portal may serve.
  if(_facets.dl&&!ST.some(s=>s.survey===sv&&s.ediAvail))return false;
  // The survey-level reading of passesYearRange's semantics. An undated survey passes
  // while both inputs are empty and fails as soon as either is set, because a reader who typed a year is
  // asking for DATED data and including undated surveys would misrepresent the range as covering them.
  if(!_surveyPassesYears(m))return false;
  if(_typeFacets.size){                             // type chips: a survey passes if ANY of its stations' type is selected
    const types=_surveyTypeSet(sv);let any=false;
    _typeFacets.forEach(t=>{if(types.has(t))any=true;});
    if(!any)return false;}
  return true;}
// The promoted facets gate the MAP's own predicates too (filters.js passesCore), and _facets is
// this module's state, so it is read through one named accessor rather than reached into.
function surveyFacetOn(k){return !!_facets[k];}
// The survey-level reading of ONE rule, which lives in filters.js (passesYearWindow); this is not a second
// verbatim copy of it. See docs: portal internals, drawer.js.
function _surveyPassesYears(m){
  return (typeof passesYearWindow==="function")?passesYearWindow(m.year_start,m.year_end):true;}
function sortSurveys(list){const arr=[...list],m=sv=>SMETA[sv]||{};
  if(_sortMode==="stations")arr.sort((a,b)=>_stationCount(b)-_stationCount(a)||a.localeCompare(b));
  else if(_sortMode==="year")arr.sort((a,b)=>_yearKey(m(b))-_yearKey(m(a))||a.localeCompare(b));       // newest first
  else if(_sortMode==="recent")arr.sort((a,b)=>{                                                       // same "latest date" rule as the feed / recently-added strip
    const da=(typeof surveyLatestDate==="function"?surveyLatestDate(m(a)):null)||"",
          db=(typeof surveyLatestDate==="function"?surveyLatestDate(m(b)):null)||"";
    return da<db?1:da>db?-1:a.localeCompare(b);});
  else arr.sort((a,b)=>a.localeCompare(b));                                                            // "name" (default)
  return arr;}
// Compact/list layout row: a single line of title, org, acquisition year, station count, licence badge.
function surveyRow(sv){const ss=ST.filter(s=>s.survey===sv),m=SMETA[sv]||{};const yearTxt=acqYearText(m);
  return `<div class="srow"><a class="srow-title" href="/surveys/${escAttr(m.slug||sv)}" title="Open survey">${esc(sv)}</a>`+
    `<span class="srow-org">${esc(m.org||"-")}</span>`+
    `<span class="srow-year">${yearTxt||"-"}</span>`+
    `<span class="srow-stn">${ss.length} station${ss.length===1?"":"s"}</span>`+
    `<span class="srow-lic">${badge(licHuman(m.lic)||"licence ?",licBadgeState(m.lic))}</span></div>`;}
function renderDiscovery(n){
  const cnt=document.getElementById("surveyCount");
  if(cnt)cnt.textContent=n+" survey"+(n===1?"":"s");
  const fc=document.getElementById("facetChips");
  if(!fc)return;
  // "Open licence" (presence) + one chip per corpus-present data type (BBMT/LPMT/AMT/GDS), multi-select.
  const chips=[`<button type="button" class="facet${_facets.lic?" on":""}" data-facet="lic" aria-pressed="${_facets.lic?"true":"false"}">Open licence</button>`,
    `<button type="button" class="facet${_facets.dl?" on":""}" data-facet="dl" aria-pressed="${_facets.dl?"true":"false"}" title="Surveys whose transfer functions this portal may serve directly">Downloadable here</button>`];
  _presentTypes().forEach(t=>{const on=_typeFacets.has(t);
    chips.push(`<button type="button" class="facet${on?" on":""}" data-type-facet="${escAttr(t)}" aria-pressed="${on?"true":"false"}">${esc(t)}</button>`);});
  fc.innerHTML=chips.join("");}
function renderCards(){
  const vis=sortSurveys(surveys.filter(surveyVisible).filter(surveyPassesFacets));
  const grid=document.getElementById("cardGrid");
  if(grid)grid.className=_cardLayout==="compact"?"cardlist":"cardgrid";
  if(grid)grid.innerHTML = vis.length
    ? (_cardLayout==="compact"?vis.map(surveyRow).join(""):vis.map(surveyCard).join(""))
    : `<div class="emptynote">No surveys match the current search and filters. Clear the search box or the licence/type chips above to widen the results.</div>`;
  renderDiscovery(vis.length);
  // Stage B: keep the header #nVis coherent with #surveyCount (both the discovery-filtered set) on every
  // grid re-render - e.g. a facet toggle, which re-renders here but has no other updateCounts path.
  if(curView==="surveys"&&typeof updateCounts==="function")updateCounts();}
// "Clear filters": drop the discovery facets (licence + data-type chips) and the
// discovery search query, the view-level narrowings this bar owns, then re-render the grid and the
// header count. The map's own rail search (#find) and structural filters are a separate surface; this
// never reaches across into them.
function clearDiscoveryFilters(){
  Object.keys(_facets).forEach(k=>_facets[k]=false);
  _typeFacets.clear();
  const s=document.getElementById("surveySearch");
  if(s&&s.value)s.value="";
  // The promoted year inputs are this bar's filters now, so Clear filters owes them a reset. Before
  // the promotion they were the rail's, and a year left in them survived every "Clear filters" click.
  ["yearFrom","yearTo"].forEach(id=>{const el=document.getElementById(id);if(el)el.value="";});
  // refresh() re-runs the map predicates (the promoted filters gate those too) and re-renders the grid.
  if(typeof refresh==="function")refresh();else renderCards();
  if(typeof updateCounts==="function")updateCounts();}
// "View on map" from the survey drawer header. See docs: portal internals, drawer.js.
function focusSurvey(sv){
  setView("map");
  if(typeof setSurveyDim==="function")setSurveyDim(sv);
  // Fit only POSITIONED stations - a withheld-coord station has no [lat,lon] to bound (avoids NaN bounds).
  const _fb=ST.filter(s=>s.survey===sv&&hasPosition(s)).map(s=>[s.lat,s.lon]);
  if(_fb.length)map.fitBounds(L.latLngBounds(_fb).pad(0.15),drawerFitOptions());}
// The drawer is position:absolute over the RIGHT of the map (index.html #drawer, z-index 1100), so a plain
// fitBounds centres the survey in the full container and lands half of it under the panel. See docs: portal
// internals, drawer.js.
function drawerFitOptions(){
  let w=0;
  try{ if(drawer&&drawer.classList&&drawer.classList.contains("open")&&drawer.getBoundingClientRect)
        w=Math.round(drawer.getBoundingClientRect().width)||0; }catch(e){w=0;}
  if(!(w>0&&isFinite(w)))w=0;
  return {paddingTopLeft:[0,0],paddingBottomRight:[w,0]};}
function selectSurvey(sv){
  // Stage B (selection-state isolation): scoping the map to one survey is a TEMPORARY LENS. See docs:
  // portal internals, drawer.js.
  if(typeof enterSelectLens==="function")enterSelectLens();
  tree.querySelectorAll('input[value]').forEach(c=>c.checked=(c.value===sv));setView("map");
  if(typeof setSidebarMode==="function")setSidebarMode("select");
  refresh();
  selected=new Set(ST.filter(s=>s.survey===sv).map(s=>s.i));updateSel();
  const _sb=ST.filter(s=>s.survey===sv&&hasPosition(s)).map(s=>[s.lat,s.lon]);if(_sb.length)map.fitBounds(L.latLngBounds(_sb).pad(0.15));toast(`Selected all ${selected.size} ${sv} stations; use the download buttons in the left panel.`);}

// Bbox over POSITIONED stations only - a withheld-coord station (null lat/lon) would poison Math.min/max
// with NaN. Empty (all-withheld survey) => a degenerate 0° box so callers never crash on b.e/b.w.
function bbox(ss){const p=(ss||[]).filter(hasPosition),xs=p.map(s=>s.lon),ys=p.map(s=>s.lat);
  return xs.length?{w:Math.min(...xs),e:Math.max(...xs),so:Math.min(...ys),no:Math.max(...ys)}:{w:0,e:0,so:0,no:0};}
// Survey footprint mini-scatter. See docs: portal internals, drawer.js.
function miniScatter(ss){
  const W2=372,H2=210,mL=38,mR=10,mT=10,mB=20;
  const bx0=mL,bx1=W2-mR,by0=mT,by1=H2-mB,bw=bx1-bx0,bh=by1-by0;
  const pp=(ss||[]).filter(hasPosition),b=bbox(pp);
  const dx=(b.e-b.w)||1,dy=(b.no-b.so)||1,sc=Math.min(bw/dx,bh/dy);
  const ox=(bw-dx*sc)/2,oy=(bh-dy*sc)/2;                 // letterbox offset inside the plot box
  const px=lon=>bx0+ox+(lon-b.w)*sc,py=lat=>by1-oy-(lat-b.so)*sc;
  const dots=pp.map(s=>`<circle cx="${px(s.lon).toFixed(1)}" cy="${py(s.lat).toFixed(1)}" r="2.6" fill="${TYPE_COL[s.type]||"#999"}" fill-opacity=".85"/>`).join("");
  const fmtd=v=>v.toFixed(1)+"°";
  const latTicks=[b.no,(b.no+b.so)/2,b.so].map(v=>{const y=py(v).toFixed(1);
    return `<line x1="${bx0-3}" y1="${y}" x2="${bx0}" y2="${y}" stroke="#8FA3B0" stroke-width="1"/>`+
      `<text x="${bx0-5}" y="${(py(v)+3).toFixed(1)}" fill="#8FA3B0" font-size="9" font-family="monospace" text-anchor="end">${fmtd(v)}</text>`;}).join("");
  const lonTicks=[b.w,(b.w+b.e)/2,b.e].map(v=>{const x=px(v).toFixed(1);
    return `<line x1="${x}" y1="${by1}" x2="${x}" y2="${by1+3}" stroke="#8FA3B0" stroke-width="1"/>`+
      `<text x="${x}" y="${by1+13}" fill="#8FA3B0" font-size="9" font-family="monospace" text-anchor="middle">${fmtd(v)}</text>`;}).join("");
  const box=`<rect x="${bx0}" y="${by0}" width="${bw}" height="${bh}" fill="none" stroke="var(--line)"/>`;
  return `<svg viewBox="0 0 ${W2} ${H2}" width="100%" role="img" style="max-width:${W2}px;background:#16242f;border:1px solid var(--line);border-radius:6px">`+
    box+latTicks+lonTicks+dots+`</svg>`;}
// There is no "Related surveys" section and no relatedSurveys() scorer. See docs: portal internals,
// drawer.js.
function surveySummary(ss,m){
  // This table carries no "dimensionality mix" row: dimensionality is inferable from the phase
  // tensor and skew. See docs: portal internals, drawer.js.
  const sciGate=hydrGate("sci","processing details");
  const typeCount={}, swCount={}; let tipper=0, rr=0, rrKnown=0, pmin=Infinity, pmax=-Infinity;
  ss.forEach(s=>{ const sc=sciRow(s.i);
    if(s.type) typeCount[s.type]=(typeCount[s.type]||0)+1;
    if(sc[SC.sw]) swCount[sc[SC.sw]]=(swCount[sc[SC.sw]]||0)+1;
    if((s.comps||"").indexOf("T")>=0) tipper++;
    if(sc[SC.rr]!=null){ rrKnown++; if(sc[SC.rr]) rr++; }
    if(s.pmin!=null) pmin=Math.min(pmin,s.pmin);
    if(s.pmax!=null) pmax=Math.max(pmax,s.pmax); });
  const types=Object.keys(typeCount).sort().map(t=>`${t} ${typeCount[t]}`).join(" · ")||"-";
  const software=m.software||Object.keys(swCount).sort((a,b)=>swCount[b]-swCount[a])[0]||"not recorded";
  const coll=m.collection&&m.collection.id?`<a href="#" data-act="collection" data-coll="${escAttr(m.collection.id)}">${esc(m.collection.title||m.collection.id)}</a>`:"-";
  // Embargoed surveys append the embargo date to the access cell; any other
  // access state (or an embargo with no date) renders the bare level as before.
  const _acc=m.access||"open";
  const _accTxt=(_acc==="embargoed"&&m.embargo_until)?"embargoed until "+esc(String(m.embargo_until)):esc(_acc);
  return `<div class="sechead">Survey summary <span style="font-weight:400;color:var(--muted);text-transform:none;letter-spacing:0">(10-second view)</span></div><table class="meta">`+
    `<tr><td>stations</td><td>${ss.length}</td></tr>`+
    `<tr><td>data types</td><td>${esc(types)}</td></tr>`+
    `<tr><td>period coverage</td><td>${isFinite(pmin)?fmtRange(fmtPeriod(pmin),fmtPeriod(pmax))+" s":"-"}</td></tr>`+
    `<tr><td>tipper availability</td><td>${tipper} / ${ss.length} stations</td></tr>`+
    `<tr><td>remote reference</td><td>${sciGate||(rrKnown?`${rr} / ${rrKnown} stations`:"not recorded")}</td></tr>`+
    `<tr><td>instrumentation</td><td>${esc(m.instrument_model||"not recorded in source metadata")}</td></tr>`+
    `<tr><td>processing software</td><td>${sciGate||esc(software)}</td></tr>`+
    `<tr><td>acquisition</td><td>${esc(m.dates||"-")}</td></tr>`+
    `<tr><td>collection</td><td>${coll}</td></tr>`+
    `<tr><td>licence / access</td><td>${esc(licHuman(m.lic)||"?")} · ${_accTxt}</td></tr>`+
    `<tr><td>version</td><td>${esc(m.version||"-")}</td></tr>`+
    `</table>`;
}
// Release notes: shown only when a survey provides them (optional; no requirement for existing surveys).
function releaseNotesHtml(m){
  const rn=m.release_notes;
  if(!Array.isArray(rn)||!rn.length) return "";
  const rows=rn.map(e=>`<tr><td>${esc(e.version||"-")}</td><td>${esc(e.date||"")}${e.date&&e.note?": ":""}${esc(e.note||"")}</td></tr>`).join("");
  return `<div class="sechead">Release notes</div><table class="meta">${rows}</table>`;
}
// Pre-built per-survey download bundles from the manifest (EDI zip + EMTF-XML zip always when served;
// survey MTH5 only when the survey_h5_enabled flag produced one). See docs: portal internals, drawer.js.
function surveyBundleTiles(slug){
  // Two-phase boot: the bundle rows live in the manifest (PHASE 2). "" (no tiles) reads as "this survey is
  // not served in bundle form", an absence claim made by OMISSION, which is no more honest than making it
  // in words, so pre-hydration the grid shows a loading tile that MANIFEST_READY replaces with the real one.
  if(hydrating("manifest"))return `<div class="prod dis"><span class="pdot" style="background:var(--unk)"></span><div>Survey bundles<small>loading…</small></div></div>`;
  const b=(typeof bundlesForSlug==="function")?bundlesForSlug(slug):[];
  if(!b.length)return"";
  const label={"edi-zip":["EDI bundle (.zip)","whole survey"],
               "xml-zip":["EMTF-XML bundle (.zip)","whole survey"],
               "mth5":["Survey MTH5 (transfer functions)","TFs only · whole survey"]};
  return b.map(r=>{const L=label[r.format]||[r.format,""];
    return `<div class="prod" data-prod="fetch" data-url="${escAttr(r.url)}" data-name="${escAttr(r.url.split("/").pop())}">`+
      `<span class="pdot" style="background:var(--ok)"></span><div>${esc(L[0])}<small>${esc(L[1])}${r.size?" · "+esc(fmtBytes(r.size)):""}</small></div></div>`;
  }).join("");
}
// ---- the survey DATA AT EVERY LEVEL tile grid --------------------------- The block is a DATA-LEVEL grid:
// six fixed slots, always all six, rendered in the Downloads tile styling. See docs: portal internals,
// drawer.js.
const REES_LEVELS_DOI="https://doi.org/10.1080/22020586.2019.12073015";
// [identifies key, tile name, one-line description]. See docs: portal internals, drawer.js.
const DATA_LEVEL_SLOTS=[
  ["collection","Collection","the umbrella record for everything this survey deposited"],
  ["raw_packed","Packed Raw Data","raw time series: telemetry data streamed from site loggers"],
  ["level0","Level 0","edited time series: instrument-recorded, full resolution"],
  ["level1","Level 1","transformed time series (MTH5): calibrated, resampled, filtered"],
  ["level2","Level 2","derived frequency-domain processed data: transfer functions"],
  ["level3","Level 3","derived modelling inputs and outputs"],
];
// SLOT ALIASES. `entire` - ONE record covering all levels, the shape the survey template gives a
// state-survey landing page - IS the umbrella record the Collection slot names, so it FILLS that slot
// instead of falling through to the extra-tile bucket. See docs: portal internals, drawer.js.
const SLOT_ALIASES={collection:["entire"]};
// One tile. UNRECORDED is explicit: muted BUT VISIBLE (.prod.dis + a hollow dot + "not yet recorded"),
// never omitted, so the deposit chain has the same shape on every survey and a gap is legible as a gap. See
// docs: portal internals, drawer.js.
function dataLevelTile(name,desc,row){
  const head=`${esc(name)}<small>${esc(desc)}</small>`;
  if(!row||!row.identifier)
    return `<div class="prod dis dl-tile"><span class="pdot hollow"></span><div>${head}<small class="dl-state">not yet recorded</small></div></div>`;
  const tag=row.custodian?` <span class="prov">${esc(row.custodian)}</span>`:"";
  if(row.resolution==="reserved")
    return `<div class="prod dis dl-tile"><span class="pdot" style="background:var(--part)"></span><div>${head}<small class="dl-id">${reservedText(row.identifier)}${tag}</small></div></div>`;
  const href=relatedIdHref(row.identifier,row.identifier_type);
  const act=(href&&/^https?:/i.test(href))?{prod:"open",url:href}:null;
  const attrs=act?Object.entries(act).map(([k,v])=>`data-${k}="${escAttr(v)}"`).join(" "):"";
  return `<div class="prod dl-tile" ${attrs}><span class="pdot" style="background:var(--ok)"></span>`+
    `<div>${head}<small class="dl-id">${relatedIdLink(row.identifier,row.identifier_type)}${tag}</small></div></div>`;}
// The whole section: the six fixed slots, then any identifier NO slot claimed (directly or through
// SLOT_ALIASES) as an EXTRA tile below them. See docs: portal internals, drawer.js.
function surveyDataLevelsHtml(m){
  m=m||{};
  const rels=(m.related_identifiers||[]).filter(r=>r&&typeof r==="object"&&r.identifier);
  // Resolve the six slots ONCE, recording which rows they consumed. See docs: portal internals, drawer.js.
  const taken=[],slotRows=[];
  DATA_LEVEL_SLOTS.forEach(([k])=>{
    const pick=key=>rels.find(r=>r.identifies===key&&taken.indexOf(r)<0);
    const row=pick(k)||(SLOT_ALIASES[k]||[]).map(pick).find(Boolean)||null;   // exact key first, then aliases
    if(row)taken.push(row);
    slotRows.push(row);});
  const have=slotRows.filter(Boolean).length;
  const tiles=DATA_LEVEL_SLOTS.map(([,name,desc],i)=>dataLevelTile(name,desc,slotRows[i])).join("");
  // Unclaimed rows: an out-of-slot `identifies`, the alias that LOST a collision (a survey declaring both
  // `collection` and `entire`), or a legacy row that predates the level model and carries only a DataCite
  // relation. See docs: portal internals, drawer.js.
  const extras=rels.filter(r=>taken.indexOf(r)<0).map(r=>{
    const label=(r.identifies&&IDENTIFIES_LABELS[r.identifies])||RELATION_LABELS[r.relation]||(r.relation?String(r.relation):"Related identifier");
    return dataLevelTile(label,"recorded identifier outside the six data levels",r);}).join("");
  // The project RAiD is a PROJECT identifier, not a data level, so it has no slot - but it was visible in
  // the block this grid replaces, and dropping it silently would lose a recorded identifier. It rides the
  // same extra-tile mechanism, which is the section's one rule for "recorded, but not one of the six".
  const raidRow=(m.raid&&!String(m.raid).startsWith("TODO"))?{identifier:String(m.raid),identifier_type:"URL"}:null;
  const raid=raidRow?dataLevelTile("Project RAiD","the research activity this survey was acquired under",raidRow):"";
  // The head names what the grid is FOR - the
  // deposit chain, level by level - rather than the identifier machinery it happens to be made of. The
  // STATION drawer's own "Persistent identifiers & instruments" block (identifiersHtml) keeps its name.
  return `<div class="sechead">Data at every level: <span class="dl-count">${have} of 6 recorded</span></div>`+
    `<div class="prodgrid">${tiles}${extras}${raid}</div>`+
    // The citability IS the point of using a published scheme, so the grid says which one, in print.
    `<div class="dl-cite">Levels per <a href="${escUrl(REES_LEVELS_DOI)}" target="_blank" rel="noopener noreferrer">Rees et al. 2019</a></div>`+
    surveyInstrumentsLine(m);}
// The instruments stay, as ONE compact footer line under the grid (models + platform PID) -
// not a slot, because an instrument is not a data level. "" when the survey declares neither.
function surveyInstrumentsLine(m){
  m=m||{};
  const parts=[];
  if(m.instrument_model)parts.push(esc(m.instrument_model));
  if(m.instrument_pid)parts.push(instrumentPidLink(m.instrument_pid));
  const perInstrument=((m.instruments||[]).filter(i=>i&&i.pid).map(i=>{
    const label=[i.manufacturer,i.model].filter(Boolean).map(esc).join(" ")||"instrument";
    return `${label}: ${instrumentPidLink(i.pid)}`;}));
  const all=parts.concat(perInstrument);
  if(!all.length)return "";
  return `<div class="dl-instr">Instruments: ${all.join(" · ")}</div>`;}
// Two-phase boot: `opts.rehydrate` has the same meaning as in openStation: a re-render driven by a phase-2
// product landing, which keeps the reader's scroll position and does not touch focus.
function openSurvey(sv,opts){const ss=ST.filter(s=>s.survey===sv),m=SMETA[sv]||{};
  const rehydrate=!!(opts&&opts.rehydrate);
  const keepScroll=rehydrate?(drawer.scrollTop||0):0;
  const keepOpen=rehydrate?_openDetailsKeys():[];     // expanders the reader opened mid-hydration stay open
  if(!rehydrate)_rememberDrawerOpener();              // capture the invoking element before the rewrite
  // The survey drawer OWNS its route the way openStation always has. Without this, opening survey B over
  // survey A left #/survey/<A> in the address bar - the same stale-URL defect the close path had, one step
  // further along. See docs: portal internals, drawer.js.
  if(!rehydrate&&m.slug)location.hash="#/survey/"+encodeURIComponent(m.slug);
  _drawerSubject={kind:"survey",sv};                  // what rehydrateOpenDrawer re-renders when a gate settles
  // Section order - (1) title+description, (2) geographic footprint, (3) station count + period-range
  // stats, (4) licence + downloads, (5) acquisition + processing, (6) contributors + funding, (7)
  // publications, (8) identifiers (the rollup), (9) release history. See docs: portal internals, drawer.js.
  drawer.innerHTML=
   // "View on map" is a NAVIGATION action, not a download, so it leaves the Downloads grid and
   // sits in the header beside the survey name. The header is sticky (.svhead), so the control stays
   // reachable from anywhere in a long survey record instead of scrolling away with the tiles.
   `<div class="dhead svhead"><span class="sid" style="font-size:18px">${esc(sv)}</span>`+
     `<button class="dhead-act" data-act="focus" data-survey="${escAttr(sv)}">View on map</button>`+
     `<button class="close" aria-label="Close">✕</button></div>`+
   `<div class="dsub">${orgNameLink(m.org||"custodian unknown",m.org_ror)} · ${esc(m.country||"")}${m.region?" · "+esc(m.region):""} · ${esc(m.dates||"dates n/a")}</div>`+
   collLine(m)+
   `<div class="dim" style="margin-top:10px">${esc(m.blurb||"Survey description to be provided by the uploader.")}</div>`+
   miniScatter(ss)+
   surveySummary(ss,m)+
   // The captured attribution statement rendered where the survey's attribution lives (verbatim custodian
   // statement, else the org(year) synthesis). See docs: portal internals, drawer.js.
   (attributionText(m)?`<div class="sechead">Attribution ${roleChip("Source data")}</div>`+attributionBoxHtml(m):"")+
   contributorsHtml(m)+
   sourcesListHtml(m)+
   // Downloads is the THREE whole-survey bundles (surveyBundleTiles) and nothing else that competes
   // with them: the EDI bundle already covers the whole survey, per-station selection belongs to
   // the station drawers, and "View on map" belongs to the header.
   `<div class="sechead">Downloads</div><div class="prodgrid">`+
     surveyBundleTiles(m.slug)+
     // A reserved dataset DOI is shown as an inert, honestly-labelled chip, never a green
     // "source archive" tile that opens a doi.org 404.
     (m.doi?(m.doi_resolution==="reserved"
       ?`<div class="prod dis"><span class="pdot" style="background:var(--part)"></span><div>Dataset DOI<small>reserved (not yet active)</small></div></div>`
       :`<div class="prod" data-act="doi" data-doi="${escAttr(m.doi)}"><span class="pdot" style="background:var(--ok)"></span><div>Dataset DOI<small>source archive</small></div></div>`):"")+
   `</div>`+
   `<div class="sechead">Funding</div><div class="surveymeta">${(m.funders||[]).map(funderHtml).join(" · ")||"-"}</div>`+
   `<div class="sechead">Related publications</div>`+pubsHtml(m)+
   // The identifiers rollup is the always-open DATA-LEVEL tile grid and carries no Organisation ROR
   // row: the custodian's ROR reaches the reader as the link on the organisation name in the header
   // subline above (orgNameLink) and on the About page. See docs: portal internals, drawer.js.
   surveyDataLevelsHtml(m)+
   releaseNotesHtml(m);   // no "Related surveys" section; release notes are last
  drawer.setAttribute("aria-label",sv+", survey details");
  drawer.classList.add("open");drawer.scrollTop=keepScroll;showDrawerScrim();   // D: dim backdrop on non-map views
  _restoreOpenDetails(keepOpen);                      // and the expanders they had open (empty on a real open)
  if(!rehydrate)_focusDrawer();}                      // move focus into the dialog (never on a hydration re-render)

// ---- single delegated click handler (no inline onclick anywhere) ----
function collLine(m){
  const parts=[];
  if(m.version) parts.push(`Version ${esc(m.version)}`);
  if(m.collection&&m.collection.id) parts.push(`Part of: <a href="#" data-act="collection" data-coll="${escAttr(m.collection.id)}">${esc(m.collection.title||m.collection.id)}</a>`);
  return parts.length?`<div class="dsub" style="margin-top:3px">${parts.join(" · ")}</div>`:"";
}
// Collections INDEX (the "Collections" tab): one rich card per collection in COLL, opening the full-width
// collection page. A collection appears automatically when surveys share a collection.id. See docs: portal
// internals, drawer.js.
function collOrgs(c){const set=new Set();((c&&c.surveys)||[]).forEach(sv=>{const o=(SMETA[sv]||{}).org;if(o)set.add(o);});return [...set].sort();}
// ONE rich collection card at ANY count, with no compact variant beside it. Title + type/status, the FULL
// abstract (no 240-char truncation, no Show more), the footprint scatter, rollup stats, participating
// organisations, and a prominent Explore action. See docs: portal internals, drawer.js.
function collectionCard(cid){const c=COLL[cid];const members=(c.surveys||[]);const ss=ST.filter(s=>members.indexOf(s.survey)>=0);
  const orgs=collOrgs(c);const desc=c.description||"";
  const descHtml=desc?`<div class="desc collfeat-desc">${esc(desc)}</div>`:"";
  return `<div class="scard collfeature">`+
    `<div class="scardhead"><h3 style="cursor:pointer" data-act="collection" data-coll="${escAttr(cid)}" title="Explore collection">${esc(c.title||cid)}</h3></div>`+
    `<div class="cust">${esc(c.type||"collection")}${c.status?" · "+esc(c.status):""}</div>`+
    descHtml+
    (ss.length?collScatter(ss):"")+
    `<div class="stats"><b>${c.n_surveys}</b> survey${c.n_surveys===1?"":"s"} · <b>${c.n_stations}</b> station${c.n_stations===1?"":"s"}${c.start_year?" · since <b>"+esc(c.start_year)+"</b>":""}</div>`+
    (orgs.length?`<div class="coll-orgs">Participating organisations: ${orgs.map(esc).join(" · ")}</div>`:"")+
    `<div class="cardbtns"><button class="primary" data-act="collection" data-coll="${escAttr(cid)}">Explore collection →</button></div>`+
  `</div>`;}
function renderCollections(){const ids=Object.keys((typeof COLL!=="undefined"&&COLL)||{}).sort();
  const grid=document.getElementById("collectionsGrid");
  if(!grid)return;
  if(!ids.length){grid.className="cardgrid";grid.innerHTML=`<div class="emptynote">No collections yet; a collection appears automatically when surveys share a <code>collection.id</code> in their survey.yaml (e.g. AusLAMP).</div>`;return;}
  grid.className="collfeature-grid";                              // ONE responsive grid at any count (index.html)
  grid.innerHTML=ids.map(collectionCard).join("");
}
// Collection footprint. See docs: portal internals, drawer.js.
const AU_EXTENT={w:112,e:154,so:-44,no:-9};
// Fluid (viewBox + width:100%) so it scales inside its container; `maxW` optionally raises the max-width
// cap (the detail-page hero gives it more room than a list card). See docs: portal internals, drawer.js.
function collScatter(ss,maxW,mark){
  if(!ss.length) return "";
  const W=560,H=Math.round(W*(AU_EXTENT.no-AU_EXTENT.so)/(AU_EXTENT.e-AU_EXTENT.w)),pad=22;
  const cap=(typeof maxW==="number"&&maxW>0)?maxW:W;
  const proj=(lon,lat)=>[pad+(lon-AU_EXTENT.w)/(AU_EXTENT.e-AU_EXTENT.w)*(W-2*pad),
                         pad+(AU_EXTENT.no-lat)/(AU_EXTENT.no-AU_EXTENT.so)*(H-2*pad)];
  // Outline beneath the dots (guarded; absent asset => no backdrop, dots still plot).
  let outline="";
  if(typeof AU_OUTLINE!=="undefined"&&AU_OUTLINE){
    const pts=r=>r.map(([lo,la])=>{const p=proj(lo,la);return p[0].toFixed(1)+","+p[1].toFixed(1);}).join("L");
    const coast=(AU_OUTLINE.coast||[]).map(r=>`<path d="M${pts(r)}Z" fill="#1d3140" stroke="#3a5266" stroke-width="1"/>`).join("");
    const borders=(AU_OUTLINE.borders||[]).map(r=>`<path d="M${pts(r)}" fill="none" stroke="#3a5266" stroke-width=".8" stroke-dasharray="3 3"/>`).join("");
    outline=`<g class="au-outline">${coast}${borders}</g>`;
  }
  // The members that PLOT, which is the engine's `present` list (_pages.py _collection_scatter assigns
  // colours over the members that have positioned stations) expressed with the SPA's own predicate. See
  // docs: portal internals, drawer.js.
  const members=[...new Set(ss.filter(hasPosition).map(s=>s.survey))].sort();
  // The SAME ramp the static collection page lays (state.js memberColours, twin of the engine's
  // _member_colours). The old modulo handed the ninth member the first member's colour, so a
  // ten-survey collection drew two surveys in one colour and its legend stopped meaning anything.
  const _memberCols=memberColours(members.length);
  const col=sv=>_memberCols[members.indexOf(sv)];
  const dots=ss.filter(hasPosition).map(s=>{const p=proj(s.lon,s.lat);
    return `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="3" fill="${col(s.survey)}" fill-opacity=".9"><title>${esc(s.id)} · ${esc(s.survey)}</title></circle>`;}).join("");
  const svg=`<svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:${cap}px;background:#16242f;border:1px solid var(--line);border-radius:8px" role="img" aria-label="Member stations over Australia">${outline}${dots}</svg>`;
  const legend=`<div class="collscatter-legend">`+members.map(sv=>`<span class="csl-item"><span class="csl-dot" style="background:${col(sv)}"></span>${esc(sv)}</span>`).join("")+`</div>`;
  const panel=mark?`<div class="collscatter-panel" style="max-width:${cap}px">${svg}<img class="collmark" src="/vendor/auscope-icon-white.png" alt="AuScope" width="27" height="28"></div>`:svg;
  return `<div class="collscatter">${panel}${legend}</div>`;
}
function openCollectionPage(cid){
  const c=(typeof COLL!=="undefined"&&COLL?COLL[cid]:null);
  if(!c){toast("Collection details not available");return;}
  const members=c.surveys||[];
  const ss=ST.filter(s=>members.indexOf(s.survey)>=0);
  let pmin=Infinity,pmax=-Infinity,tip=0;
  ss.forEach(s=>{ if(s.pmin!=null)pmin=Math.min(pmin,s.pmin); if(s.pmax!=null)pmax=Math.max(pmax,s.pmax);
    if((s.comps||"").indexOf("T")>=0)tip++; });
  const ext=c.bbox?`${(c.bbox.east-c.bbox.west).toFixed(1)}° × ${(c.bbox.north-c.bbox.south).toFixed(1)}°`:"-";
  const stat=(lab,val)=>`<div class="cstat"><div class="cnum">${val}</div><div class="clab">${esc(lab)}</div></div>`;
  const rows=members.map(sv=>{const sub=ST.filter(s=>s.survey===sv),m=SMETA[sv]||{};
    const tc={};sub.forEach(s=>{if(s.type)tc[s.type]=(tc[s.type]||0)+1;});
    const pmn=Math.min(...sub.map(s=>s.pmin).filter(v=>v!=null)),pmx=Math.max(...sub.map(s=>s.pmax).filter(v=>v!=null));
    const types=Object.keys(tc).sort().map(t=>`${esc(t)} ${tc[t]}`).join(" · ")||"-";
    return `<tr><td><a href="/surveys/${escAttr(m.slug||sv)}">${esc(sv)}</a><div class="csub">${esc(m.org||"-")}</div></td>`+
      `<td>${sub.length}</td><td>${types}</td><td>${isFinite(pmn)?fmtRange(fmtPeriod(pmn),fmtPeriod(pmx))+" s":"-"}</td></tr>`;
  }).join("");
  const v=document.getElementById("collectionview");
  // A two-column HERO on wide screens: the abstract (+ the type/status/counts subline) on the left, the
  // fluid footprint scatter on the right; the stat tiles span full-width below and the member table
  // breathes to full width. See docs: portal internals, drawer.js.
  v.innerHTML=
   `<div class="collpagenav"><button class="collback" data-act="collidx">← All collections</button>`+
   `<button class="collback collmapbtn" data-act="collmap" data-coll="${escAttr(cid)}">View all stations on main map</button></div>`+
   `<h1 class="colltitle">${esc(c.title||cid)}</h1>`+
   `<div class="collhero">`+
     `<div class="collhero-main">`+
       `<div class="collsub">${esc(c.type||"collection")}${c.status?" · "+esc(c.status):""} · ${c.n_surveys} survey${c.n_surveys===1?"":"s"} · ${c.n_stations} station${c.n_stations===1?"":"s"}${c.start_year?" · since "+esc(c.start_year):""}${c.last_updated?" · updated "+esc(c.last_updated):""}</div>`+
       (c.description?`<div class="colldesc">${esc(c.description)}</div>`:"")+
     `</div>`+
     (ss.length?`<div class="collhero-aside">${collScatter(ss,720,true)}</div>`:"")+
   `</div>`+
   `<div class="cstats">`+stat("surveys",c.n_surveys)+stat("stations",c.n_stations)+
     stat("period coverage",isFinite(pmin)?fmtRange(fmtPeriod(pmin),fmtPeriod(pmax))+" s":"-")+stat("tipper stations",tip+" / "+ss.length)+stat("extent",ext)+`</div>`+
   `<div class="csechead">Member surveys (${members.length})</div>`+
   `<table class="colltable"><thead><tr><th>Survey</th><th>Stations</th><th>Data&nbsp;types</th><th>Period&nbsp;range</th></tr></thead><tbody>${rows}</tbody></table>`;
  document.getElementById("map").style.display="none";
  document.getElementById("surveysview").style.display="none";
  const _ci=document.getElementById("collectionsview");if(_ci)_ci.style.display="none";
  // C: the collection-detail page also spans full width, so hide the rail + resize handle (setView's map
  // path restores them). This is the manual view switch openCollectionPage owns instead of setView.
  const _fp=document.getElementById("filterPane");if(_fp)_fp.classList.add("hidden");
  const _rz=document.getElementById("resizer");if(_rz)_rz.classList.add("hidden");
  document.getElementById("navMap").classList.remove("active");
  document.getElementById("navSurveys").classList.remove("active");
  const _nc=document.getElementById("navCollections");if(_nc)_nc.classList.add("active");
  closeDrawer();
  v.style.display="block";v.scrollTop=0;curView="collection";
  // This is the one view switch that does NOT go through setView, so it owes the header counter the
  // repaint setView gives it - otherwise the slot keeps whatever the previous view left there.
  if(typeof updateCounts==="function")updateCounts();
}
function dispatchProd(d){
  if(d.prod==="edi")fetchEdi(d.file,d.avail==="1",d.survey);
  else if(d.prod==="fetch"&&d.url){track("DownloadGenerated",{format:(d.name||"").split(".").pop()});downloadUrl(dataUrl(d.url),d.name);}
  else if(d.prod==="open"&&d.url){window.open(d.url,"_blank","noopener,noreferrer");
    // A time-series hand-off carries the archive's filename and size, so it can say what it just
    // handed over. Still UNTRACKED, as required: the request is counted at the front door,
    // from the /go/ts/ route it names, and a second count here would be a different number.
    if(d.tsname&&typeof handoffSnack==="function")handoffSnack(d.tsname,+d.tsbytes||0);}
  else if(d.prod==="scroll"&&d.sel){const el=document.querySelector(d.sel);if(el){
    // The scroll target (#pt_anchor) lives in the Response tab, with the phase tensor + induction
    // arrows now always-shown blocks - activate its tab so the scroll actually reveals it.
    const panel=el.closest?el.closest('[role="tabpanel"]'):null;
    if(panel&&panel.dataset&&panel.dataset.tab)selectDrawerTab(panel.dataset.tab);
    if(el.scrollIntoView)el.scrollIntoView({behavior:"smooth"});}}
  else if(d.prod==="toast")toast(d.msg);}
// Yield to an open plot-expand modal - its own Esc handler (plots.js) closes it, so the drawer must NOT
// also close underneath it. Otherwise Escape closes the drawer as before. See docs: portal internals,
// drawer.js.
document.addEventListener("keydown",e=>{if(e.key==="Escape"){
  if(typeof document==="undefined"||!document.getElementById)return void closeDrawer();
  if(document.getElementById("plotmodal"))return;
  const wm=document.getElementById("wgetModal");
  if(wm&&wm.classList&&!wm.classList.contains("hidden"))return;
  closeDrawer();}});
// ARIA tabs keyboard navigation (arrow keys / Home / End) with roving tabindex. Delegated on
// the persistent drawer element so it survives every innerHTML re-render.
if(drawer&&drawer.addEventListener)drawer.addEventListener("keydown",e=>{
  const tab=(e.target&&e.target.closest)?e.target.closest('[role="tab"]'):null;if(!tab)return;
  const tabs=[...drawer.querySelectorAll('[role="tab"]')];const idx=tabs.indexOf(tab);if(idx<0)return;
  let ni=-1;
  if(e.key==="ArrowRight"||e.key==="ArrowDown")ni=(idx+1)%tabs.length;
  else if(e.key==="ArrowLeft"||e.key==="ArrowUp")ni=(idx-1+tabs.length)%tabs.length;
  else if(e.key==="Home")ni=0;else if(e.key==="End")ni=tabs.length-1;else return;
  e.preventDefault();const nt=tabs[ni];selectDrawerTab(nt.dataset.tab);if(nt.focus)nt.focus();
});
document.addEventListener("click",e=>{
  if(e.target.closest(".close")){closeDrawer();return;}
  const cite=e.target.closest("[data-cite]");
  if(cite){const m=SMETA[cite.dataset.survey]||{},c=m.cite||AUSMT_SELF;
    const out=cite.dataset.cite==="apa"?apa(c,m.doi):cite.dataset.cite==="ris"?ris(c,m.doi):bibtex(cite.dataset.key,c,m.doi);
    copyTxt(out);return;}
  const prod=e.target.closest("[data-prod]");
  if(prod){dispatchProd(prod.dataset);return;}
  const el=e.target.closest("[data-act]");if(!el)return;
  const act=el.dataset.act,sv=el.dataset.survey,doi=el.dataset.doi;
  if(act==="tab"){e.preventDefault();selectDrawerTab(el.dataset.tab);}
  else if(act==="expand"){e.preventDefault();if(typeof openStationModal==="function"&&_curTf&&_curStation)openStationModal(stationModalHeader(_curStation,SMETA[_curStation.survey]||{}),_curTf);}
  else if(act==="collection"){e.preventDefault();location.hash="#/collection/"+encodeURIComponent(el.dataset.coll);}
  else if(act==="collidx"){e.preventDefault();if(location.hash.indexOf("#/collection/")===0)history.replaceState(null,"",location.pathname+location.search);setView("collections");}
  else if(act==="collmap"){e.preventDefault();if(typeof viewCollectionOnMap==="function")viewCollectionOnMap(el.dataset.coll);}   // switch to map + fitBounds to the collection
  else if(act==="focus")focusSurvey(sv);
  else if(act==="select")selectSurvey(sv);
  else if(act==="doi"&&doi)window.open(escUrl("https://doi.org/"+doi),"_blank","noopener,noreferrer");   // NOT encodeURIComponent - it %2F-escapes the DOI slash -> doi.org 404; escUrl still blocks scheme injection
});

// Discovery-controls wiring for the Surveys view. Static registrations - the controls live in index.html's
// #surveysview and exist at parse time (drawer.js loads after them). See docs: portal internals, drawer.js.
(function(){
  const sortSel=document.getElementById("sortSel");
  if(sortSel&&sortSel.addEventListener)sortSel.addEventListener("change",()=>{_sortMode=sortSel.value||"name";renderCards();});
  const layoutSeg=document.getElementById("layoutSeg");
  if(layoutSeg&&layoutSeg.addEventListener)layoutSeg.addEventListener("click",e=>{const b=e.target.closest&&e.target.closest("button");if(!b||!b.dataset.layout)return;
    _cardLayout=b.dataset.layout;[...(layoutSeg.children||[])].forEach(x=>x.classList&&x.classList.toggle("on",x===b));renderCards();});
  const clearBtn=document.getElementById("clearFilters");
  if(clearBtn&&clearBtn.addEventListener)clearBtn.addEventListener("click",clearDiscoveryFilters);
  // Live surveys-view search: case-insensitive substring over name/org/region/blurb
  // (surveyMatchesSearch in filters.js reads this input). Live-updates the grid + #surveyCount and the
  // header #nVis count.
  const search=document.getElementById("surveySearch");
  if(search&&search.addEventListener)search.addEventListener("input",()=>{renderCards();if(typeof updateCounts==="function")updateCounts();});
  const fc=document.getElementById("facetChips");
  if(fc&&fc.addEventListener)fc.addEventListener("click",e=>{
    const lf=e.target.closest&&e.target.closest("[data-facet]");
    // "dl" gates passesCore as well as the catalogue, so a full refresh - the map has to follow it.
    if(lf){const k=lf.dataset.facet;if(k in _facets){_facets[k]=!_facets[k];
      if(k==="dl"&&typeof refresh==="function")refresh();else renderCards();}return;}
    const tf=e.target.closest&&e.target.closest("[data-type-facet]");
    if(tf){const t=tf.dataset.typeFacet;if(_typeFacets.has(t))_typeFacets.delete(t);else _typeFacets.add(t);renderCards();}});
})();
