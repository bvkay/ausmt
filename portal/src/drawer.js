// drawer.js — station/survey/provenance/citation/download rendering for the detail drawer.
// A station/survey/provenance file split is a tracked deferred refactor:
// feasible (classic scripts, hoisted globals) but low-priority churn for one cohesive concern, and the
// no-build smoke harness can't fully verify drawer rendering, so it's its own task — not a loose marker.
"use strict";
// Station drawer (science first), survey cards, survey story, citations. All event handling is
// delegated (no inline onclick): .close buttons, [data-act] card actions, [data-cite] citation
// copy, [data-prod] product tiles. Cross-module calls (setView/map/refresh) happen at event
// time only. Citations live here because this is the only consumer.
const drawer=document.getElementById("drawer");
// UX6 Wave E (E7): the drawer is a dialog. role + a base aria-label are set here (index.html's #drawer
// element is owned by another lane, so we stamp the ARIA from JS); openStation/openSurvey refine the
// aria-label per subject. tabindex=-1 lets us move focus onto the container as a fallback. This does not
// disturb the Wave C tab keyboard nav (its handler is scoped to [role="tab"] descendants).
if(drawer&&drawer.setAttribute){drawer.setAttribute("role","dialog");drawer.setAttribute("aria-label","Details");drawer.setAttribute("tabindex","-1");}
// UX6 Wave E (E7): focus management, mirroring plots.js's modal pattern — remember the invoking element on
// open, move focus INTO the drawer (its close button, else the container), and RESTORE focus to the opener
// on close. Best-effort/guarded so the headless smoke harness (no real activeElement/focus) never throws.
let _drawerReturnFocus=null;
function _rememberDrawerOpener(){_drawerReturnFocus=(typeof document!=="undefined"&&document)?document.activeElement:null;}
function _focusDrawer(){if(!drawer||!drawer.querySelector)return;
  // preventScroll: on the FIRST open the drawer is still transform:translateX(102%) off-screen mid-slide,
  // so focusing its .close button makes the browser scroll documentElement ~428px left to reveal the
  // off-screen target, then snap back when the .16s slide settles — a visible page-wide bounce. preventScroll
  // keeps focus (accessibility) without that scroll-into-view. Guarded fallback for engines lacking the option.
  const t=drawer.querySelector(".close")||drawer;if(t&&t.focus){try{t.focus({preventScroll:true});}catch(e){}}}
function _restoreDrawerFocus(){const f=_drawerReturnFocus;_drawerReturnFocus=null;if(f&&f.focus){try{f.focus();}catch(e){}}}
// Cleanup wave (D): a dim backdrop shown behind the drawer while it is open on the Surveys /
// Collections / collection-detail views (where the drawer floats over full-width content). NOT on the
// map view: there the drawer sits side-by-side with the map, so no scrim. Clicking the backdrop closes
// the drawer. It lives in #content BENEATH the drawer and the drawer's left-edge resize handle
// (both higher z-index in index.html), so the resizer keeps working. Guarded for the headless harness.
const _drawerScrim=document.getElementById("drawerScrim");
function showDrawerScrim(){if(_drawerScrim)_drawerScrim.classList.toggle("hidden",(typeof curView!=="undefined"&&curView==="map"));}
function hideDrawerScrim(){if(_drawerScrim)_drawerScrim.classList.add("hidden");}
if(_drawerScrim&&_drawerScrim.addEventListener)_drawerScrim.addEventListener("click",()=>closeDrawer());
// UX6 Wave C: the currently-open station's TF row, stashed so the delegated [data-act="expand"] handler
// can re-render the plotters into the full-station response modal without re-deriving them from the DOM.
let _curTf=null;
// UX6 Wave C (evolved): the currently-open station object, stashed alongside _curTf so the expand handler
// can build the response modal's identity header (id / site / survey / org / type / honest coords).
let _curStation=null;
// Two-phase boot: WHAT the drawer is currently showing: {kind:"station",i} | {kind:"survey",sv} | null,
// so a phase-2 product landing can re-render exactly that subject in place (rehydrateOpenDrawer). null means
// "nothing that reads a phase-2 product is on screen": the drawer is shut, or something that builds its own
// markup (the strike rose) owns it.
let _drawerSubject=null;
// UX6 Wave C (C2): a small section-role chip using the engine README taxonomy — "Source data",
// "Automated screening", "AusMT-derived". Plain muted text, no colour semantics.
function roleChip(l){return `<span class="rolechip">${esc(l)}</span>`;}
// ---- two-phase boot: the loading surfaces ------------------------------------------------------
// The drawer is the densest consumer of the PHASE 2 products (tf.json -> the response curves; sci.json ->
// the processing/screening rows; manifest.json -> every served-artifact row, badge and download tile), and
// almost every one of those surfaces has an HONEST-ABSENCE rendering: "not currently available", "not
// recorded", "not stated in EDI", "none currently served", "not evaluated". Each of those is a CLAIM about
// the corpus. None of them may be shown for a product that is merely still in flight, so every such site
// below routes through hydrGate(): pending -> a loading state; failed -> an explicit could-not-load line;
// ready -> the untouched pre-existing rendering. The open drawer re-renders when each gate settles
// (rehydrateOpenDrawer), so nothing that showed a loading state stays showing one.
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
// reader who opened one, up to three times (once per gate) across a multi-second hydration window. Record
// which <details> are open by their summary text (stable across a re-render, and the only key that survives
// an innerHTML rewrite) and put them back. A summary whose text legitimately CHANGES with hydration simply
// fails to match and reverts to its default state, which is the pre-fix behaviour, never worse. Guarded for
// the stubbed-DOM smoke harness (querySelectorAll -> []).
function _openDetailsKeys(){
  if(!(drawer&&drawer.querySelectorAll))return[];
  return [...drawer.querySelectorAll("details")].filter(d=>d.open)
    .map(d=>{const sm=d.querySelector&&d.querySelector("summary");return sm?sm.textContent:"";}).filter(Boolean);}
function _restoreOpenDetails(keys){
  if(!keys||!keys.length||!(drawer&&drawer.querySelectorAll))return;
  [...drawer.querySelectorAll("details")].forEach(d=>{
    const sm=d.querySelector&&d.querySelector("summary");
    if(sm&&keys.indexOf(sm.textContent)>=0)d.open=true;});}
// UX6 Wave C (C1): one tab panel. ALL panels render in the DOM at openStation time; selectDrawerTab
// toggles them via the `hidden` attribute + aria-selected, so the pinned innerHTML/text assertions keep
// matching against the same rendered strings regardless of which tab is active.
function drawerPanel(id,content,selected){
  return `<div class="dpanel" id="dp-${id}" role="tabpanel" data-tab="${id}" aria-labelledby="dt-${id}" tabindex="0"${selected?"":" hidden"}>${content}</div>`;}
// Activate one drawer tab (ARIA roving-tabindex + hidden toggle). Degrades to a no-op under the smoke
// harness (stubbed drawer with querySelectorAll()->[]). Falls back to the first tab for an unknown name.
// Two-phase boot: the active tab is remembered so a hydration re-render (rehydrateOpenDrawer) puts the
// reader back on the panel they were reading, not back on the default Response tab.
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
// C1b gate, factored: the served-EDI descriptor for a station — {sub,st,d}. When the access gate REFUSES
// (a non-open survey with no served EDI artifact) d is null, so neither the header Download action, the
// Overview primary-download tile, nor the Files "Transfer function" tile offers a download affordance —
// they say "embargoed"/"metadata only" instead. An OPEN survey keeps today's exact tile text (byte-for-
// byte), including the "EDI (via source archive)" fallback that the C1b pins assert is ABSENT when embargoed.
function ediDescriptor(s,m){
  // Two-phase boot: the manifest is a PHASE 2 product, so before it lands there is no honest answer here:
  // the served-artifact branch and BOTH fallbacks ("EDI (via source archive)" / the embargo wording) are
  // claims about what this deployment serves. Report the pending state with NO download affordance (d:null,
  // so headerDownloadBtn renders nothing at all rather than a button that might resolve to the wrong route),
  // and let MANIFEST_READY re-render the drawer into the real descriptor.
  if(hydrating("manifest"))return {sub:"loading…",st:"unk",d:null};
  const arts=(typeof artifactsFor==="function"?artifactsFor(s.ausmt_id):[]);
  const ediArt=arts.find(a=>a.format==="edi");
  if(ediArt) return {sub:"Download"+(ediArt.size?" · "+fmtBytes(ediArt.size):""),st:"ok",d:{prod:"fetch",url:ediArt.url,name:ediArt.url.split("/").pop()}};
  if(!isOpenAccess(m)) return {sub:accessLevelOf(m)==="metadata_only"?"metadata only":"embargoed",st:"no",d:null};
  return {sub:s.ediAvail?"Download":"EDI (via source archive)",st:s.ediAvail?"ok":"unk",d:{prod:"edi",file:s.file,avail:s.ediAvail?"1":"0",survey:s.survey}};
}
// C1b: the sticky-header Download EDI action. Renders NOTHING where the gate refuses (no download
// affordance for an embargoed/metadata-only station) — otherwise a primary button routed through the
// same [data-prod] dispatch as the product tiles.
// Two-phase boot: rendering NOTHING is precisely this function's embargo signal, so an in-flight manifest
// must not be allowed to borrow it. ediDescriptor returns d:null while the manifest is pending (correctly:
// it cannot yet know the route), which would silently render an OPEN-access station as embargoed for the
// whole flight: absence by omission, the same defect surveyBundleTiles gets a loading tile for. Say what
// is happening instead, and claim nothing either way about availability.
function headerDownloadBtn(s,m){
  if(hydrating("manifest"))return `<span class="hydrating hydr-inline" role="status">checking file availability…</span>`;
  const e=ediDescriptor(s,m);if(!e.d)return"";
  const attrs=Object.entries(e.d).map(([k,v])=>`data-${k}="${escAttr(v)}"`).join(" ");
  return `<button class="primary dl-edi" ${attrs}>Download EDI</button>`;}
// Overview "primary download" tile — the same gated descriptor rendered as a single product tile (disabled
// where the gate refuses, so it states the embargo rather than offering bytes).
function overviewDownload(s,m){const e=ediDescriptor(s,m);
  const attrs=e.d?Object.entries(e.d).map(([k,v])=>`data-${k}="${escAttr(v)}"`).join(" "):"";
  const st=e.st==="ok"?"ok":e.st==="part"?"part":e.st==="no"?"no":"unk";
  return `<div class="prodgrid"><div class="prod ${e.d?"":"dis"}" ${attrs}><span class="pdot" style="background:var(--${st})"></span><div>Transfer function<small>${esc(e.sub)}</small></div></div></div>`;}

function apa(m,doi){return `${esc(m.au)} (${esc(m.yr||"n.d.")}). ${esc(m.ti)}${m.ve?" ("+esc(m.ve)+")":""} [Data set]. ${esc(m.pb)}.`+(doi?` https://doi.org/${esc(doi)}`:"");}
// R3: the DISPLAY-ONLY APA citation rendered inside the Cite box. Identical to apa() except the trailing
// DOI is a resolution-aware HYPERLINK: ok/unknown/absent (uncached) -> a doi.org anchor; reserved -> plain
// text (never a dead link, honouring the r2 reserved-sweep posture). The COPY/EXPORT path stays apa()
// (plain text) — a citation string that lands on a clipboard must remain text, not markup.
function apaCiteDisplay(m,doi,doiRes){const base=apa(m,null);   // the APA sentence WITHOUT the DOI suffix
  if(!doi)return base;
  const url="https://doi.org/"+doi;
  const doiHtml=doiRes==="reserved"
    ? esc(url)
    : `<a href="${escUrl(url)}" target="_blank" rel="noopener noreferrer">${esc(url)}</a>`;
  return base+" "+doiHtml;}
function bibtex(k,m,doi){return `@misc{${k},\n  author    = {${m.au.replace(/;/g," and")}},\n  title     = {${m.ti}},\n  year      = {${m.yr||"n.d."}},\n  publisher = {${m.pb}},\n${doi?`  doi       = {${doi}},\n`:""}  note      = {Accessed via the AusMT portal}\n}`;}
function ris(m,doi){return `TY  - DATA\nAU  - ${m.au.replace(/; /g,"\nAU  - ")}\nTI  - ${m.ti}\nPY  - ${m.yr||""}\nPB  - ${m.pb}\n${doi?`DO  - ${doi}\nUR  - https://doi.org/${doi}\n`:""}ER  -`;}

function badge(l,st,title){const c=st==="ok"?"ok":st==="part"?"part":st==="no"?"no":"";const s=st==="ok"?"✓":st==="part"?"◐":st==="no"?"✗":"?";return `<span class="badge ${c}"${title?` title="${escAttr(title)}"`:""}>${s} ${esc(l)}</span>`;}
// C46-W3b: licence class/badge routed through the CANONICAL contract tables (contract.js LICENSES) — never
// a `startsWith('CC')` guess (which mis-classed CC0/ODbL/ODC-BY and every non-CC open licence, and would
// have passed a hostile "CCwhatever"). licCanon normalises aliases + case exactly like exports.canonLic.
// licIsOpen = "redistributable" (openly licensed — the 'Open licence' facet + the 'Licence verified' star).
// licBadgeState maps the canonical id: redistributable -> ok, recognised-but-not-open -> part, else unk.
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
// C46-W3b: the survey-level attribution line — the custodian's verbatim attribution.statement when
// declared, else the org(year) synthesis. MIRRORS exports.attributionLine byte-for-byte so the drawer, the
// station Cite tab, the exported CSV and the citation pack all render the SAME attribution string.
function attributionText(m){m=m||{};
  const st=((m.attribution||{}).statement||"").toString().trim();
  if(st)return st;
  const who=((m.cite&&m.cite.au)||m.org||"").toString().trim();
  const yr=attributionYear(m);
  return [who,yr?"("+yr+")":""].filter(Boolean).join(" ").trim();}
// C46-W3b: a source's required attribution when it carries no verbatim statement — the profile-rendered
// form via the generated PROFILES table (exports.renderProfile, present at render time), else custodian(year).
function sourceAttr(s){s=s||{};
  const cust=(s.custodian||"").toString().trim();
  const yr=(s.retrieved?(String(s.retrieved).match(/\d{4}/)||[])[0]:"")||"";
  if(typeof renderProfile==="function")return renderProfile((s.profile||"generic").toString().trim()||"generic",cust,yr,(s.title||"").toString().trim(),false);
  return [cust,yr?"("+yr+")":""].filter(Boolean).join(" ").trim();}
// C46-W3b: the upstream "Source datasets" list for the survey detail — one row per sources[] entry (title,
// custodian + identifier link + canonical licence, then the required attribution). "" when none declared.
function sourcesListHtml(m){const srcs=(m&&m.sources)||[];
  if(!srcs.length)return"";
  const rows=srcs.map(s0=>{const s=s0||{};
    const title=esc((s.title||"untitled source dataset").toString().trim());
    const cust=esc((s.custodian||"unknown custodian").toString().trim());
    const idv=(s.identifier||"").toString().trim();
    const ident=idv?" · "+pidLink(idv):"";
    const slic=esc(licCanon(s.licence)||"licence not stated");
    const stmt=(s.statement||"").toString().trim();
    const attr=stmt?esc(stmt):esc(sourceAttr(s));
    return `<div class="srcitem"><div class="srct">${title}</div><div class="srcm">${cust}${ident} · <span class="prov">${slic}</span></div>${attr?`<div class="srca">${attr}</div>`:""}</div>`;
  }).join("");
  return `<div class="sechead">Source datasets ${roleChip("Source data")}</div><div class="srclist">${rows}</div>`;}
// C1b: a survey's access.level is authoritative for whether the portal has its DISPLAY data. "open" (or
// absent, which this reader defaults to open) => served, curves present. The producer emits only the three
// ACCESS_LEVELS values. Anything else (embargoed | metadata_only | an unknown value)
// => NON-OPEN: the engine emits EMPTY tf series for these stations (the response curves ARE the embargoed
// data), so the drawer must render an ACCESS PANEL in place of the four plots rather than four blank frames.
function accessLevelOf(m){return (m&&m.access)?String(m.access):"open";}
function isOpenAccess(m){return accessLevelOf(m)==="open";}
// Withheld-download copy: the TRUTHFUL access reason for a survey with NO dataset DOI (so no honest
// source-archive pointer exists). Embargo and licence are DISTINCT access states: a licence-restricted
// station must never be blanket-labelled as embargoed (same access-integrity discipline as the Kalkaroo
// fix). No em/en dashes in this copy (owner request); plain punctuation only.
function withheldReason(m){
  const org=(m&&m.org)||"unknown";
  const reason=accessLevelOf(m)==="embargoed"
    ? "dataset currently under embargo"+((m&&m.embargo_until)?" until "+String(m.embargo_until):"")
    : "not redistributable under its licence";
  return reason+", contact the custodian organisation ("+org+")";
}
// C42 Amendment A1: the boot-loaded coordinate policy for a station ('generalised' | 'withheld' | null),
// folded onto s by buildState() from coord_policy.json. The engine masks the VALUE (generalised => 0.1°
// cell rendered verbatim, withheld => null lat/lon) AND — for a non-exact station — emits this policy
// marker so the portal can badge honestly WITHOUT re-deriving precision client-side (forbidden by the
// record). Pure (no DOM/Leaflet) so the jsdom driver exercises it.
function coordPolicyOf(s){return (s&&s.coordPolicy)||null;}
// True when a station's SERVED position is masked. A withheld station is detectable from its null coords
// alone (belt-and-braces if the marker artifact never loaded); a generalised station needs the marker
// (its 0.1° cell is a valid-looking position, indistinguishable from an exact grid-point without it).
function coordsMasked(s){return !hasPosition(s)||coordPolicyOf(s)==="generalised"||coordPolicyOf(s)==="withheld";}
// Survey-level honesty predicate: are ALL of a survey's station locations served EXACT? Backs the access-
// panel stance text — "Station locations are public" is asserted only when this is true (D2/A1).
function surveyLocationsPublic(sv){return !ST.some(s=>s.survey===sv&&coordsMasked(s));}
// The drawer's lat/lon cell. Withheld => the honest withheld line (no coords). Generalised => the masked
// 0.1° cell rendered VERBATIM (never re-rounded — the record forbids client-side re-derivation) PLUS the
// "position generalised" badge, so a reader knows the ~0.1° number is a custodian generalisation, not a
// precise fix. Exact => the verbatim 6-dp position.
function coordCellHtml(s){
  if(!hasPosition(s)) return `<span style="color:var(--muted)">coordinates withheld (custodian policy)</span>`;
  const coords=`${s.lat.toFixed(6)}, ${s.lon.toFixed(6)}`;
  return coordPolicyOf(s)==="generalised"
    ? `${coords}<br><span style="color:var(--muted)">position generalised to ~0.1° (custodian policy)</span>`
    : coords;
}
// UX6 Wave C (evolved): the identity header for the full-station RESPONSE modal (the expand affordance).
// Station id, the source site name when it differs from the displayed id, and the data-type chip on the
// first line; survey · organisation on the second; the honest coordinate line on the third. Reuses
// coordCellHtml VERBATIM so a masked position is never printed raw here (custodian policy holds inside the
// modal exactly as in the drawer), and orgNameLink so the ROR link treatment matches the drawer header.
function stationModalHeader(s,m){
  const site=(s.site_name&&s.site_name!==s.id)?`<span class="pm-site">${esc(s.site_name)}</span>`:"";
  const typeChip=`<span class="chip" style="background:${TYPE_COL[s.type]||"#999"}">${esc(s.type)}</span>`;
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
  // C42 A1: the location-publicity clause is only asserted when EVERY station's position is served exact.
  // When a custodian has generalised/withheld any station, "locations are public" is FALSE — say so.
  // (Disclosing that a location is generalised/withheld reveals POLICY, not POSITION.)
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
// UX8 (X7): dataset-maturity model. Five RECORD-STEWARDSHIP dimensions — how completely a record is
// archived, licensed and reproducible, NOT its scientific quality (said in the block's subline). Stars =
// achieved count. PURE so the star count is unit-testable: flip m.doi / m.ts and the count changes.
// "not recorded" / "not available" phrasing per the honesty rules (never "pending").
// IDCONS D4 (SPEC §5): the resolution state of the survey's dataset DOI, across BOTH the flat dataset_doi
// (engine fallback, m.doi_resolution) and the typed related_identifiers DOI rows. Returns "ok" when at
// least one DOI-typed identifier is live-or-uncached (ok / unknown / absent — anything not "reserved");
// "reserved" ONLY when a DOI-typed identifier exists and EVERY one is reserved (doi.org's own 404); null
// when none is recorded. A reserved DOI is not a working identifier, so it must NOT light the DOI star.
function datasetDoiResolution(m){m=m||{};
  const res=[];
  if(m.doi)res.push(m.doi_resolution);
  for(const r of (m.related_identifiers||[]))if(r&&r.identifier_type==="DOI")res.push(r.resolution);
  if(!res.length)return null;
  return res.some(x=>x!=="reserved")?"ok":"reserved";}
// IDCONS D1: "the raw time series is linked" now reads off a typed IsDerivedFrom relation (the new home of
// the collection PID) OR the still-readable flat ts_pid (engine fallback) OR the pipeline availability flag.
function tsLinked(m){m=m||{};
  return (m.related_identifiers||[]).some(r=>r&&r.relation==="IsDerivedFrom")||!!m.ts_pid||m.ts==="ok";}
function maturityModel(m,sc){m=m||{};sc=sc||[];
  const doiRes=datasetDoiResolution(m),tsOn=tsLinked(m);
  const dims=[
    {key:"curated",label:"Curated archive",achieved:true,note:""},
    {key:"repro",label:"Reproducible",achieved:!!(sc[SC.sw]&&m.ts==="ok"),note:""},
    {key:"licence",label:"Licence verified",achieved:licBadgeState(m.lic)!=="unk",note:""},
    // IDCONS D4: the DOI star lights only for a RESOLVED (ok/unknown) dataset DOI. A reserved DOI shows a
    // hollow star with honest wording — never a green "minted" off a DOI that 404s at doi.org today.
    {key:"doi",label:"DOI",achieved:doiRes==="ok",note:doiRes==="ok"?"minted":doiRes==="reserved"?"reserved (not yet active)":"not recorded"},
    {key:"ts",label:"Time series",achieved:tsOn,note:tsOn?"linked":"not available"},
  ];
  return {dims,stars:dims.filter(d=>d.achieved).length,total:dims.length};}
function maturityBlock(s){const m=SMETA[s.survey]||{},sc=sciRow(s.i);
  // Two-phase boot: the "Reproducible" dimension reads sc[SC.sw] (sci.json, PHASE 2). An unlit star is a
  // statement that the dimension was NOT achieved, so the whole block waits rather than under-counting the
  // stars for a moment and then silently gaining one.
  const gate=hydrGate("sci","dataset maturity",true);
  if(gate)return `<div class="matblock"><div class="mat-h">Dataset maturity</div>${gate}</div>`;
  const mod=maturityModel(m,sc);
  const stars="★".repeat(mod.stars)+"☆".repeat(mod.total-mod.stars);
  const rows=mod.dims.map(d=>`<li class="matdim ${d.achieved?"on":"off"}"><span class="matglyph">${d.achieved?"★":"☆"}</span><span>${esc(d.label)}${d.note?": "+esc(d.note):""}</span></li>`).join("");
  return `<div class="matblock"><div class="mat-h">Dataset maturity <span class="mat-stars" title="${mod.stars} of ${mod.total} stewardship dimensions achieved">${stars}</span></div>`+
    `<div class="mat-sub">Record-stewardship maturity: how completely this record is archived, licensed and reproducible. Not a measure of scientific quality.</div>`+
    `<ul class="matdims">${rows}</ul></div>`;}
// C7: the raw-TS pointer. A survey's OWN time_series.collection_pid (SMETA.ts_pid) is authoritative
// when declared; TS_COLLECTION (the AusLAMP/NCI collection DOI) is only the DEPLOYMENT-WIDE default for
// surveys that genuinely belong to that shared collection and declare no PID of their own — never a
// stand-in for a survey's dataset DOI (see tsUrlFor's caller sites vs. fetchEdi/exports.js source-citation).
function tsPidRaw(m){return (m&&m.ts_pid)||TS_COLLECTION.doi;}
function tsUrlFor(m){return "https://doi.org/"+tsPidRaw(m);}
// The served MTH5 bundle for a survey (the per-survey <slug>-tf.h5 the Downloads grid + Files tab use).
// SINGLE SOURCE of MTH5 presence: the format-availability badge and the provenance lineage line derive
// MTH5 from THIS (not the stale SMETA.mth5, which the engine always emits as "unk"), so all three agree
// with the Downloads tile (19/21 surveys live). Guarded like the other bundlesForSlug callers.
function mth5BundleFor(m){return (typeof bundlesForSlug==="function"?bundlesForSlug(m&&m.slug):[]).find(r=>r&&r.format==="mth5");}
// api-docs lane: a manifest artifact url rendered as the ENDPOINT a reader can GET. A tier=repo row
// carries a portal-relative path ("edi/<slug>/<file>.edi") which the hosted site serves under /data/;
// a tier=nci row already carries the ABSOLUTE fileServer url, so it is shown verbatim; prefixing /data/
// there would print a path that does not exist. Display only; the download path still goes through
// dataUrl() (which honours a deployment's data_base_url).
function apiArtifactPath(u){const v=String(u==null?"":u);
  return /^[a-z][a-z0-9+.\-]*:\/\//i.test(v)?v:"/data/"+v.replace(/^\/+/,"");}
// R5: the Files tab, structured to the NCI data-level standard as a SINGLE COLUMN of full-width rows
// (Packed raw / Level 0 / Level 1 time series -> Level 2 derived processed data with EDI/EMTF-XML/MTH5
// sub-rows -> Level 3 models, when ever served -> Publication). Each row carries an explicit ORIGIN tag
// ("AusMT-derived" vs "source archive") so there is zero ambiguity about what AusMT computed vs what came
// from the source. The Phase tensor tile is gone (it is a visual product; it lives in the Response tab).
function relatedProducts(s){const m=SMETA[s.survey]||{};
  const tsDoi=tsUrlFor(m);
  // IDCONS D4 / r2 posture: a reserved collection PID / dataset DOI must not open a dead doi.org link.
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
  // D-L4 (SPEC §9.6): the related_identifiers row whose `identifies` matches this level (its own DOI), so
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
      // window.open). A URL-typed identifier is relatedIdHref's raw value, so a javascript:/data: value
      // would otherwise route straight into window.open — gate it here and fall through to the reserved /
      // tsOpen branches (escUrl still guards the block anchor edge).
      const href=relatedIdHref(idRow.identifier,idRow.identifier_type);
      if(href&&/^https?:/i.test(href))return {n:label,sub:gloss+" · "+(idRow.custodian||"source collection"),origin:"source archive",st:"ok",d:{prod:"open",url:href}};
    }
    if(tsReserved)return {n:label,sub:gloss+" · reserved, not yet active",origin:"source archive",st:"part",d:null};
    return {n:label,sub:gloss+" · "+(m.ts_pid?"survey collection":"NCI collection"),origin:"source archive",st:"ok",d:tsOpen};
  };
  // Level 2 sub-rows (the impedance tensors): the source EDI (the custodian's processed transfer function,
  // gated by C1b for non-open surveys — it says "embargoed"/"metadata only", never "via source archive"),
  // then the AusMT-derived EMTF XML (build pipeline, mt_metadata) and MTH5.
  const ediSub={n:"EDI",...ediDescriptor(s,m),origin:"source archive"};
  const xmlSub=xml
    ? {n:"EMTF XML",sub:"Download"+(xml.size?" · "+fmtBytes(xml.size):""),origin:"AusMT-derived",st:"ok",d:{prod:"fetch",url:xml.url,name:xml.url.split("/").pop()}}
    // Honesty fix: the 8 surveys with zero served XML ARE redistributable (the build pipeline failed on
    // them), so the old "via pipeline / served for redistributable surveys" toast was FALSE. Show the same
    // honest inert not-available sub-line the MTH5 row uses, with no toast overclaim.
    : {n:"EMTF XML",sub:"not currently available",origin:"AusMT-derived",st:"unk",d:null};
  // C32 tier 2: the Level 2 MTH5 sub-row LIGHTS from the actual per-survey <slug>-tf.h5 bundle in the
  // manifest (the same rows the Downloads grid uses), NOT a static SMETA flag — so it is true to what the
  // build served. An embargoed/withheld survey produces NO bundle (the h5 is suppressed byte-for-byte like
  // the EDI), so the row falls back to the honest not-available state. Download is wired exactly like the
  // EMTF XML row ({prod:"fetch"}), so the pull is counted by the same masked front-door analytics. The
  // label stays TF-only honest ("transfer functions").
  const mth5Bundle=mth5BundleFor(m);
  const mth5Sub=mth5Bundle
    ? {n:"MTH5",sub:"Transfer functions only · Download"+(mth5Bundle.size?" · "+fmtBytes(mth5Bundle.size):""),origin:"AusMT-derived",st:"ok",d:{prod:"fetch",url:mth5Bundle.url,name:mth5Bundle.url.split("/").pop()}}
    : {n:"MTH5",sub:"Transfer functions only · not currently available",origin:"AusMT-derived",st:"unk",d:null};
  const level2Subs=[ediSub,xmlSub,mth5Sub];
  // Publication (interpretation) — the parenthetical separates the dataset citation from an interpretation
  // publication. Reserved-DOI honesty applies (inert + note).
  const pubRow={n:"Publication (interpretation)",sub:m.doi?(doiReserved?"reserved, not yet active":"DOI"):"none recorded",origin:"source archive",st:m.doi?(doiReserved?"part":"ok"):"no",d:(m.doi&&!doiReserved)?{prod:"open",url:"https://doi.org/"+m.doi}:null};
  const attrs=d=>d?Object.entries(d).map(([k,v])=>`data-${k}="${escAttr(v)}"`).join(" "):"";
  const dot=st=>`<span class="pdot" style="background:var(--${st==="ok"?"ok":st==="part"?"part":st==="no"?"no":"unk"})"></span>`;
  const row=it=>`<div class="prod ${it.d?"":"dis"}" ${attrs(it.d)}>${dot(it.st)}<div>${esc(it.n)} ${it.origin?roleChip(it.origin):""}<small>${esc(it.sub)}</small></div></div>`;
  const tsRows=[
    tsLevelRow("Raw time series","packed raw time series","raw_packed"),
    tsLevelRow("Level 0 edited time series","instrument-recorded, full resolution","level0"),
    tsLevelRow("Level 1 transformed time series","calibrated, resampled, filtered","level1"),
  ].map(row).join("");
  // Two-phase boot: all three Level 2 sub-rows resolve against the download manifest (PHASE 2), and each of
  // them degrades to a "not currently available" / "via source archive" line, i.e. statements about what the
  // build actually served. Render the loading state in place of the three rows until the manifest lands
  // (the time-series rows above and the publication row below read survey metadata from phase 1, so they
  // are honest immediately and are left alone).
  const level2Body=hydrating("manifest")?hydrBlock("served files"):level2Subs.map(row).join("");
  const level2=`<div class="fl-group"><div class="fl-ghead">Level 2 derived processed data <small>transfer functions</small></div>`+
    `<div class="fl-sub">${level2Body}</div></div>`;
  // R5: Level 3 models render ONLY when a model DOI is served in the survey metadata. No such field exists
  // today, so the slot stays here as a comment and simply does not render yet. When one lands, e.g.:
  //   if(m.model_doi) level3 = row({n:"Level 3 models",sub:...,origin:"source archive",st:"ok",d:{prod:"open",url:"https://doi.org/"+m.model_doi}});
  return `<div class="filelist">${tsRows}${level2}${row(pubRow)}</div>`;}
// Card-lane polish (owner): the MOST SPECIFIC processing-software string available for a station. The
// station-level string the source EDI carried (sc[SC.sw], e.g. "Geotools 4.0.5.12583") wins because it
// is the one that names a VERSION; the survey-level declared software field (m.software, often the bare
// product name) is the fallback; with neither, the honest "not stated in EDI" stands. No version is ever
// synthesised. SINGLE SOURCE for the Provenance tab's own row AND the lineage graph node, so the two
// surfaces in one tab cannot disagree about what processed this station.
// Two-phase boot: the station-level string lives in sci.json (PHASE 2). The fallbacks are honest ONLY once
// that row is known: "not stated in EDI" asserts the EDI carried no software field, and the survey-level
// m.software would silently win over a station string that simply had not arrived. So while sci is
// unresolved this says so instead. PURE (no DOM) as before; the caller escapes it.
function processingSoftwareText(m,sc){
  if(hydrating("sci"))return "loading…";
  if(hydrFailed("sci"))return "could not be loaded";
  const st=(((sc||[])[SC.sw])||"").toString().trim();
  if(st)return st;
  const sv=((m&&m.software)||"").toString().trim();
  return sv||"not stated in EDI";}
// Card-lane polish (owner): the formats AusMT actually distributes for this station/survey, dot-separated
// with no ticks and no "(pipeline)" qualifier. Availability comes from the SAME sources the Files tab
// reads: ediDescriptor for the EDI (its manifest artifact first, then the served-here fallback, and "no"
// for an embargoed/metadata-only station, so a withheld EDI is never listed), the manifest artifact row
// for the EMTF XML, and the per-survey bundle helper for MTH5. A format that is not served is simply
// ABSENT from the list; the old line asserted "EDI ✓ · EMTF XML (pipeline)" unconditionally, claiming an
// XML for the 8 surveys the build pipeline never produced one for and an EDI for embargoed stations.
function distributedFormatsText(s,m){
  // Two-phase boot: every input here is a manifest row (PHASE 2). Pre-hydration the list would come back
  // empty and print "none currently served", a false claim about the corpus and exactly the overclaim in
  // the other direction that this function was written to remove. Say it is loading instead.
  if(hydrating("manifest"))return "loading…";
  const arts=(typeof artifactsFor==="function"?artifactsFor(s&&s.ausmt_id):[]);
  const out=[];
  if(ediDescriptor(s,m).st==="ok")out.push("EDI");
  if(arts.some(a=>a&&a.format==="emtfxml"))out.push("EMTF XML");
  if(mth5BundleFor(m))out.push("MTH5");
  return out.length?out.join(" · "):"none currently served";}
// Card-lane polish (owner): a publication reduced to a short lineage cite, "FirstAuthor et al. (Year)".
// Never fabricates a co-author: names split on "; " when the row uses that separator, else on "," where
// THREE or more parts prove a real list (a single "Last, First" name splits into exactly two, so it is
// kept verbatim, as does a two-name comma list). Falls back to the title, then the bare DOI, so a row
// with no author still says something true. Mirrors doi_harvest.formatCitation's ">2 parts" convention.
function pubShortCite(p){p=p||{};
  const a=String(p.a==null?"":p.a).trim(),y=String(p.y==null?"":p.y).trim(),t=String(p.t==null?"":p.t).trim();
  const doi=String(p.doi==null?"":p.doi).trim().replace(/^https?:\/\/(?:dx\.)?doi\.org\//i,"");
  let who="";
  if(a){const sep=a.indexOf(";")>=0?";":",";
    const parts=a.split(sep).map(x=>x.trim()).filter(Boolean);
    who=(sep===";"?parts.length>1:parts.length>2)?parts[0]+" et al.":a;}
  const head=[who||t,y?"("+y+")":""].filter(Boolean).join(" ").trim();
  return head||(doi?"doi:"+doi:"");}
// Card-lane polish (owner): the lineage PUBLICATION cell, read from the survey's related publications
// (pubs[], the same list the survey card renders). It used to read the dataset DOI (m.doi), which is the
// identifier of the DATA, not an interpretation publication, so a survey with a real paper in pubs[] and
// no dataset DOI still read "none recorded" (live: Newer Volcanic Province 2019 and its 2023 paper). The
// first publication renders as a short cite, DOI-linked when it carries one, with a "+N more" tail.
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
  // C46-W3b: an upstream "source dataset" node when the survey declares sources[] — the lineage's origin,
  // above the raw time series. Shows the first source's title + identifier link (with a "+N more" tail).
  const srcs=(m.sources||[]);
  if(srcs.length){const s0=srcs[0]||{};const idv=(s0.identifier||"").toString().trim();
    const lbl=esc((s0.title||"source dataset").toString().trim())+(srcs.length>1?` <span class="prov">(+${srcs.length-1} more)</span>`:"");
    nodes.push(["Source dataset",idv?`${lbl} · ${pidLink(idv)}`:lbl]);}
  nodes.push(
   ["Raw time series",m.ts==="ok"?tsCollectionCell(m):"not located in source archives"],
   ["Processing software",esc(processingSoftwareText(m,sc))],
   ["Method",methodGate||(sc[SC.alg]?esc(sc[SC.alg]):(sc[SC.rr]?"remote reference (stated)":"not stated"))],
   ["Transfer function",`${s.nper} periods · ${esc(s.comps.split("").join("+"))||"–"}`],
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
    // HIDDEN pending design review (owner 2026-07-22): screening surface not public-ready — restore by uncommenting the "screening parameters" row below. The `params` string is left computed above so re-enabling is uncommenting only.
    /* ["screening parameters", params], */
    ["build date (UTC)", esc(P.generated?P.generated.replace("T"," ").slice(0,19):"n/a")],
    ["Build commit", P.git_commit?`<code>${esc(P.git_commit)}</code>`:"<span class='prov'>unavailable</span>"]
  ];
  // Owner ruling: titled "AusMT Provenance", not "Processing provenance". Every row below is about the
  // AUSMT PIPELINE's own run (extractor, pipeline version, build date, build commit), not the custodian's
  // MT data processing, and readers took the old title to mean the latter. The MT processing software the
  // custodian used has its own row at the top of this tab (and its own lineage node).
  return `<details class="prov-d"><summary>AusMT Provenance</summary><table class="meta">`+
    rows.map(([k,v])=>`<tr><td>${esc(k)}</td><td>${v}</td></tr>`).join("")+
    // HIDDEN pending design review (owner 2026-07-22): the ", and the screening parameters above" clause is
    // dropped alongside the hidden screening-parameters row above — restore the commented clause when the row returns.
    `</table><div class="prov" style="margin-top:6px">Every product traces to its input file, the extractor and version`+
    /* ", and the screening parameters above" */
    `. Reproducible offline by <i>AusMT</i>.</div></details>`;
}
// C25-V3 (frame policy v3, owner ruling 2026-07-11): the engine serves impedances AS STORED in the
// source's declared acquisition frame and NEVER de-rotates. When that frame is non-trivial we report
// it to the READER — terse, honest, no interpretation. frameLineText is PURE (DOM-free) so a Node pin
// (tools/frame_line_test.js) can drive it. Inputs are the VERBATIM station.json `frame` block values:
//   declared_azimuth_deg        — the recorded acquisition-frame angle (0 => served in the
//                                 declared-zero / geographic reference; no line by itself).
//   tipper_declared_azimuth_deg — F2: present ONLY when the tipper's uniform declared frame DIVERGES
//                                 from the impedance's declared azimuth (the engine omits it when
//                                 equal or undeclared), so presence itself is the trigger.
//   survey_frame_note           — the V3-B "mixed declared frames across stations" note (present only
//                                 for an inconsistent survey).
// Trigger: a non-zero declared angle, a divergent tipper frame, or a survey mixed-frames note.
function frameLineText(frame){
  if(!frame||typeof frame!=="object") return "";
  const az=frame.declared_azimuth_deg;
  const hasAngle=(typeof az==="number"&&isFinite(az)&&Math.abs(az)>0.01);
  const taz=frame.tipper_declared_azimuth_deg;
  const hasTip=(typeof taz==="number"&&isFinite(taz));    // engine emits it ONLY when divergent (F2)
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
// Per-station frame facts live ONLY in the per-station station.json (the positional catalogue has no
// frame column, and adding one would need a contract change). So fetch it lazily at drawer-open — the
// SAME product the curator workbench reads — and inject the line if the drawer still shows this station.
// Best-effort: an absent/withheld station.json (older builds, no --products, or a file:// portal) just
// yields no line, never an error. Only called for OPEN-access surveys (a withheld survey serves no
// impedances, so a "served in frame X" line would be false).
// Two-phase boot: a hydration re-render calls this again for the SAME station (the innerHTML rewrite blanks
// the #frameline placeholder, so it does have to be re-injected), and with three gates that is up to four
// identical station.json requests per drawer open. Cache the RESOLVED LINE per station instead: "" covers
// every no-line outcome (absent station.json, no frame block, nothing worth saying, an offline/file:// error)
// so a station that produced no line is not re-requested either.
const _frameLineCache=new Map();                          // ausmt_id -> the resolved line ("" = no line)
function _injectFrameLine(s,txt){
  if(!txt) return;
  const el=document.getElementById("frameline");
  if(el&&el.dataset.ausmt===s.ausmt_id){                  // guard: drawer may have moved on (async)
    el.textContent=txt;
    el.style.cssText="font-size:12px;color:var(--muted);margin:2px 0 10px;line-height:1.4";
  }
}
function loadStationFrameLine(s){
  const slug=s.slug||((SMETA[s.survey]||{}).slug);
  if(!slug||!s.id) return Promise.resolve();              // cannot locate station.json — skip
  if(_frameLineCache.has(s.ausmt_id)){_injectFrameLine(s,_frameLineCache.get(s.ausmt_id));return Promise.resolve();}
  const url=dataUrl("products/"+encodeURIComponent(slug)+"/"+encodeURIComponent(s.id)+"/station.json");
  // The catch sits on the FETCH, not on the whole chain, so a withheld/offline/file:// station caches its
  // no-line outcome (and is not re-requested) while a throw in the render step below caches nothing and is
  // simply retried, exactly as before.
  return fetch(url).then(r=>r.ok?r.json():null).catch(()=>null).then(doc=>{   // withheld / offline / file:// => no line
    const txt=(doc&&doc.frame)?(frameLineText(doc.frame)||""):"";
    _frameLineCache.set(s.ausmt_id,txt);
    _injectFrameLine(s,txt);
  }).catch(()=>{});
}
// UX8 (X5): the five Screening indicators, each derived ONLY from a quantity the pipeline already computes.
// PURE (no DOM) so the field->indicator->threshold mapping is falsifiable: flip one input and exactly one
// indicator flips state. Each row is {key,label,state,word}; state ∈ green|amber|red|na and `word` is the
// plain-language state so meaning never rides on colour alone. A NOT-computable input renders the neutral
// grey 'not evaluated' — never a fabricated green. Thresholds echo PROV.parameters where the pipeline
// records one (phase-tensor consistency uses PROV pct_periods_3d_threshold, passed in as pctThr); the
// others use the documented screen thresholds below.
//   d.q          completeness/smoothness check (0..5)      -> Smoothness            green>=4  amber>=3
//   d.azR/azN    circular resultant length + count of low-skew PT azimuths -> Strike stability  green>=.9 amber>=.75 (need >=3)
//   d.beta,betaThr median |β| (deg) vs its PROV threshold skew_3d_deg      -> Phase tensor consistency  green<=thr amber<=2*thr
//   d.phaseSplit median |φxy − φyx| separation (deg)       -> Phase split           green<=15 amber<=35
//   d.decades    period band width in decades              -> Coverage              green>=4  amber>=2
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
function _indWord(st){return st==="green"?"Green":st==="amber"?"Amber":st==="red"?"Red":"–";}
function screeningIndicatorList(inds){
  return `<ul class="indlist">`+inds.map(it=>{
    const cls=it.state==="green"?"ok":it.state==="amber"?"part":it.state==="red"?"no":"na";
    const stateTxt=it.state==="na"?"not evaluated":_indWord(it.state)+" · "+esc(it.word);
    return `<li class="indrow ind-${cls}"><span class="indglyph">${_indGlyph(it.state)}</span>`+
      `<span class="indlabel">${esc(it.label)}</span><span class="indstate">${stateTxt}</span></li>`;
  }).join("")+`</ul>`;}
// UX8 (X4): the "Station summary" collapsible under the Response plots — the owner's exact four-group
// layout. DATA_CHECKS_LABEL is a ONE-STRING seam (owner sketched "Quality"; architect amended to "Data
// checks") — change the one constant to re-label that group.
const DATA_CHECKS_LABEL="Data checks";
function _ssGroup(title,rows,extra){
  return `<div class="ssgroup"><div class="ssg-h">${esc(title)}</div><table class="meta">`+
    rows.map(([k,v])=>`<tr><td>${esc(k)}</td><td>${v}</td></tr>`).join("")+`</table>${extra||""}</div>`;}
function stationSummaryDetails(s,m,sc){
  // R4: the Station group. Rows APPEND after coordinates (never reorder): the source station/site name
  // (only when it differs from the displayed, sanitised id — the SA28_2B -> SA282B case), the data type,
  // the ausmt_id, and the collection title (row omitted entirely when the survey is in no collection).
  const stationRows=[["coordinates",coordCellHtml(s)]];
  if(s.site_name&&s.site_name!==s.id)stationRows.push(["site name",esc(s.site_name)]);
  stationRows.push(["data type",esc(s.type||"–")]);   // no long-form gloss exists in the corpus yet; show the code
  stationRows.push(["ausmt_id",esc(s.ausmt_id)]);
  if(m.collection&&m.collection.id)stationRows.push(["collection",esc(m.collection.title||m.collection.id)]);
  const station=_ssGroup("Station",stationRows,overviewDownload(s,m));
  // Two-phase boot: periods/components/tipper are catalogue columns (phase 1, honest at first paint);
  // "remote reference" and the Processing group read the sci row (PHASE 2), whose absent-value renderings
  // ("not recorded", "not stated in EDI") are claims about the source EDI. Those two wait.
  const sciGate=hydrGate("sci","processing details");
  const tf=_ssGroup("Transfer function",[
    ["periods",`${fmtP(s.pmin)}–${fmtP(s.pmax)} s`],
    ["components",(esc(s.comps.split("").join(" + "))||"–")],
    ["tipper",s.comps.includes("T")?"yes":"no"],
    ["remote reference",sciGate||(sc[SC.rr]?"yes":"not recorded")]]);
  // R4: the "Data checks" group (the TF error row) is REMOVED per owner ruling — reversibly commented per
  // house style for hidden-not-deleted surfaces. mre / DATA_CHECKS_LABEL / _ssGroup are left intact so
  // re-enabling is uncommenting only.
  /* const mre=sc[SC.mre];
  const checks=_ssGroup(DATA_CHECKS_LABEL,[
    ["TF error",mre!=null?Math.round(mre*100)+"%":"n/a"]]); */
  const proc=_ssGroup("Processing",[
    ["software",sciGate||(sc[SC.sw]?esc(sc[SC.sw]):"not stated in EDI")],
    ["source",esc(s.file)]]);
  return `<details class="prov-d ssdetails"><summary>Station summary</summary><div class="prov-dbody ssbody">${station}${tf}${proc}</div></details>`;
}
// Two-phase boot: `opts.rehydrate` marks a re-render driven by a phase-2 product LANDING (main.js
// wireHydration -> rehydrateOpenDrawer), not by a reader opening the drawer. Such a re-render must not
// re-capture the opener, must not pull focus back into the dialog, must not rewrite the hash, and must leave
// the reader exactly where they were (same scroll offset, same tab), so the only visible change is the
// section that was showing a loading state filling in.
function openStation(i,opts){
  const rehydrate=!!(opts&&opts.rehydrate);
  const keepScroll=rehydrate?(drawer.scrollTop||0):0;
  const keepTab=rehydrate?_curDrawerTab:"response";
  const keepOpen=rehydrate?_openDetailsKeys():[];     // expanders the reader opened mid-hydration stay open
  if(!rehydrate)_rememberDrawerOpener();              // E7: capture the invoking element before the rewrite
  _drawerSubject={kind:"station",i};                  // what rehydrateOpenDrawer re-renders when a gate settles
  const s=ST[i],t=tfRow(i)||[[]],m=SMETA[s.survey]||{},sc=sciRow(i);
  // UX3 item 7a: sc[SC.dim] (dimensionality) is no longer surfaced in the drawer screening grid — it's
  // inferable from the phase tensor + skew, which stay shown (strike/|β|/3-D-periods line below). The
  // sc.json field itself is unchanged (data products are display-only edits); the map's colour-by-dim
  // mode still reads s.dim. So `dim` is intentionally not destructured here anymore.
  const p3d=sc[SC.p3d],gd=sc[SC.gd],skew=sc[SC.skew],dec=sc[SC.decades];
  if(!rehydrate)location.hash="#/station/"+encodeURIComponent(s.ausmt_id);   // ausmt_id is globally unique; s.id (DATAID) repeats across surveys
  const azs=[],azPers=[];if(t[T.pt_az])t[T.pt_az].forEach((a,k)=>{if(a!=null&&t[T.pt_beta][k]!=null&&Math.abs(t[T.pt_beta][k])<5){azs.push(((a%180)+180)%180);const _pk=t[T.periods]&&t[T.periods][k];if(_pk!=null)azPers.push(_pk);}});
  const _perTxt=azPers.length?` over ${fmtP(Math.min(...azPers))}–${fmtP(Math.max(...azPers))}s`:"";
  // Per-period 3-D screening threshold echoed from the build's own provenance (never hard-coded); when
  // build_provenance.json isn't loaded the degree figure is simply omitted rather than fabricated.
  const _bp=(typeof PROV!=="undefined"&&PROV&&PROV.parameters&&PROV.parameters.dimensionality)||{};const _betaThr=_bp.beta_per_period_deg;
  // Strike circular concentration (mean resultant length R on the doubled axial angles) — the Strike-
  // stability indicator's input, and the same doubled-angle mean feeds the strike clause below.
  let strikeClause=`median phase-tensor strike <b>not estimated</b> <span style="color:var(--muted)">(insufficient low-skew data)</span>`;
  let _azR=null;
  if(azs.length>=1){const rad=azs.map(a=>2*a*Math.PI/180);
    const _S=rad.reduce((s,x)=>s+Math.sin(x),0),_C=rad.reduce((s,x)=>s+Math.cos(x),0);
    _azR=Math.hypot(_S,_C)/azs.length;
    if(azs.length>=3){const mean=Math.atan2(_S,_C)/2*180/Math.PI;const st=((mean%180)+180)%180;
      strikeClause=`median phase-tensor strike <b>~N${st.toFixed(0)}°E / N${((st+90)%180).toFixed(0)}°E</b> <span style="color:var(--muted)">(90° ambiguous)</span>${_perTxt}`;}}
  // Median xy/yx phase split (deg) — the Phase-split indicator's input (φyx already +180°-adjusted).
  let _phaseSplit=null;
  if(t[T.phs_xy]&&t[T.phs_yx_adj]){const _sp=[];t[T.phs_xy].forEach((v,k)=>{const w=t[T.phs_yx_adj][k];if(v!=null&&w!=null)_sp.push(Math.abs(v-w));});
    if(_sp.length){_sp.sort((a,b)=>a-b);_phaseSplit=_sp[Math.floor(_sp.length/2)];}}
  const _inds=screeningIndicators({q:sc[SC.q],azR:_azR,azN:azs.length,beta:skew,betaThr:_bp.skew_3d_deg,phaseSplit:_phaseSplit,decades:dec});
  const keysafe=s.ausmt_id.replace(/[^a-z0-9]/g,"_");
  // ---- UX6 Wave C: sticky header (identity + chips + primary actions) + tab strip -------------------
  const typeChip=`<span class="chip" style="background:${TYPE_COL[s.type]||"#999"}">${esc(s.type)}</span>`;
  const collChip=(m.collection&&m.collection.id)?`<span class="chip collchip" data-act="collection" data-coll="${escAttr(m.collection.id)}" title="Explore collection">${esc(m.collection.title||m.collection.id)}</span>`:"";
  // Acquisition year: the survey's declared dates string, else its year_start(-end) range; omitted if neither.
  const yearTxt=m.dates?esc(m.dates):(m.year_start?esc(String(m.year_start))+(m.year_end&&m.year_end!==m.year_start?"–"+esc(String(m.year_end)):""):"");
  const yearChip=yearTxt?`<span class="hchip">${yearTxt}</span>`:"";
  const licBadge=badge(m.lic||"licence ?",licBadgeState(m.lic));
  // UX8 (X4, owner ruling): Response is the default tab and Overview is gone (its facts fold into the
  // Response tab's "Station summary" collapsible). Five tabs; Response first (default-selected).
  // HIDDEN pending design review (owner 2026-07-22): screening surface not public-ready — restore by uncommenting the ["screening","Screening"] entry.
  const TABS=[["response","Response"],/*["screening","Screening"],*/["files","Files"],["provenance","Provenance"],["cite","Cite"]];
  const tabStrip=`<div class="seg dtabs" role="tablist" aria-label="Station detail sections">`+
    TABS.map(([id,label],k)=>`<button role="tab" id="dt-${id}" data-act="tab" data-tab="${id}" aria-controls="dp-${id}" aria-selected="${k===0}" tabindex="${k===0?0:-1}"${k===0?' class="on"':""}>${esc(label)}</button>`).join("")+`</div>`;
  const header=`<div class="dtop">`+
    `<div class="dhead"><span class="sid">${esc(s.id)}</span>${typeChip}${collChip}<button class="close" aria-label="Close">✕</button></div>`+
    `<div class="dsub">${esc(s.survey)} · ${orgNameLink(s.org,m.org_ror)} · ${esc(s.country)}</div>`+
    collLine(m)+
    `<div class="dchips">${yearChip}${licBadge}</div>`+
    // R1: the header "Cite" tab-jump button (.dl-cite) is removed as redundant — the Cite TAB already
    // reaches the same panel; the header keeps only the Download EDI primary action.
    `<div class="dactions">${headerDownloadBtn(s,m)}</div>`+
    tabStrip+`</div>`;
  // ---- Panel content -------------------------------------------------------------------------------
  // Response (default) — the four plots FIRST (the centerpiece; all four always shown — phase tensor +
  // induction arrows are never collapsed and carry no minimise control), then the collapsible "Station
  // summary" (the owner's four-group layout, stationSummaryDetails) which absorbs the former Overview
  // facts. C1b: a non-open station shows the
  // access panel here INSTEAD of the plots (curves ARE the withheld data). #pt_anchor is kept so the
  // "Phase tensor" related-product scroll target never dangles; the frame line is populated lazily.
  // Owner directive (2026-07-28): the response section carries exactly ONE expand control, on this heading
  // row, instead of a ⤢ button per plot block (all four opened the same full-station modal). It is rendered
  // only for an open-access station: without curves openStationModal has no panels to show and would open
  // nothing, so a control there would be a dead affordance over the access panel.
  const _rspOpen=isOpenAccess(m);
  // Two-phase boot: the curves live in tf.json (PHASE 2). An empty TF row renders NO plot at all (plotBlock
  // guards on an empty series), so painting the plots pre-hydration would show an open-access station as
  // having no response functions, the loudest absence claim in the drawer. While tf is in flight the panel
  // carries a loading state instead, and the expand control is withheld with it (openStationModal would find
  // no panels and open an empty overlay). TF_READY re-renders this section with the curves in place.
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
  // HIDDEN pending design review (owner 2026-07-22): screening surface not public-ready — restore by uncommenting the screeningHtml block below (and its drawerPanel("screening",…) render + the ["screening","Screening"] TABS entry above). Underlying data/helpers (screeningIndicators, _inds, strikeClause…) are left intact so re-enabling is uncommenting only.
  // Screening (X5) — a five-row indicator list (glyph + label + Green/Amber/Red state word + descriptive
  // word; never colour alone; a not-computable check is neutral grey "not evaluated"), then a "Show
  // details" expander preserving the full automated screening prose (strike + median |β| lines, the
  // galvanic flag, and the completeness/smoothness check with its not-a-verdict framing — UX3-7a fence).
  /* const screeningHtml=`<div class="sechead">Screening indicators ${roleChip("Automated screening")} <span style="text-transform:none;letter-spacing:0">· not interpretation products</span></div>`+
    screeningIndicatorList(_inds)+
    `<details class="prov-d"><summary>Show details</summary><div class="prov-dbody">`+
    `<div class="dim">Automated screening estimate — ${strikeClause}${skew!=null?` · median |β| <b>${skew}°</b> · <b>${p3d}%</b> of evaluated periods exceeded the |β|${_betaThr!=null?` &gt; ${esc(String(_betaThr))}°`:""} screening threshold`:""}. Not a structural interpretation.<br>`+
    `${gd?"⚠ <b>Galvanic/static-shift</b> signature detected (ρ modes offset by a near-constant factor with coincident phases). ":""}`+
    `<span style="color:var(--muted)">Automated completeness/smoothness check: ${sc[SC.q]!=null?`<span class="qvdot" style="background:${qColor(sc[SC.q])}"></span><b>${sc[SC.q].toFixed(1)}/5</b> — ${sc[SC.qb]==="e"?"median error + coverage + smoothness":"shape-based; no error bars in EDI"}; <i>not a quality or geological-value judgement</i>`:"n/a"}.</span></div>`+
    `</div></details>`; */
  // Files — the NCI data-level product list. R5: the section-level role chip is dropped; each product row
  // now carries its OWN origin tag (AusMT-derived vs source archive), so a single section chip would be
  // wrong (the list spans both source-archive time series and AusMT-derived deliverables).
  const filesHtml=`<div class="sechead">Related products</div>`+relatedProducts(s);
  // Provenance (X6/X7/X8) — three source-data rows visible (processing software · transfer function
  // source file+sha · source archive), then the Dataset-maturity block (X7 stars), then EVERYTHING ELSE
  // (lineage graph, full provenance table, identifiers, format availability, record metadata, API)
  // behind collapsed <details>. Nothing deleted — only demoted. The API box (X8) is the last, small expander.
  const _srcArchive=sourceArchiveCell(m);
  // This station's served artifact rows (manifest `files`), read once and reused by the format-availability
  // badge and the API section below. Empty for a withheld/embargoed survey: the engine emits no manifest
  // rows for one, so absence here IS the embargo, never a "row we failed to find".
  // Two-phase boot: that reading of an empty list only holds once the manifest has LANDED, so both consumers
  // below gate on _manGate first: pre-hydration an empty list means "not received yet", not "not served".
  const _manGate=hydrGate("manifest","served files",true);
  const _arts=(typeof artifactsFor==="function"?artifactsFor(s.ausmt_id):[]);
  // R8: whether a served EMTF-XML artifact exists for this station (drives the format-availability badge:
  // ok when served, else part — produced via the build pipeline for redistributable surveys).
  const _fmtXmlArt=_arts.some(a=>a.format==="emtfxml");
  const provTop=`<table class="meta prov-top">`+
    `<tr><td>Processing software</td><td>${esc(processingSoftwareText(m,sc))}</td></tr>`+
    `<tr><td>Transfer function</td><td>${esc(s.file)}${s.sha?` · <code title="${escAttr(s.sha)}">${esc(s.sha.slice(0,16))}…</code>`:" · <span class='prov'>no checksum</span>"}</td></tr>`+
    `<tr><td>Source archive</td><td>${_srcArchive}</td></tr></table>`;
  const metaTable=`<table class="meta">`+
    `<tr><td>ausmt_id</td><td>${esc(s.ausmt_id)}</td></tr>`+
    // C42 coordinate access: a custodian-withheld station carries null lat/lon (masked VALUE) — show the
    // honest withheld line instead of null-derefing .toFixed. A generalised station carries the 0.1° cell,
    // rendered VERBATIM (no client-side re-rounding) with a "position generalised" badge driven by the
    // engine's coord_policy marker (A1). coordCellHtml encapsulates all three; hasPosition is the shared predicate.
    `<tr><td>lat, lon</td><td>${coordCellHtml(s)}</td></tr>`+
    `<tr><td>components</td><td>${esc(s.comps.split("").join(" + "))||"–"}</td></tr>`+
    `<tr><td>source file</td><td>${esc(s.file)}</td></tr></table>`;
  // X8: the Metadata & API box collapses to a single small "API" expander at the tab's foot.
  // api-docs lane: the section used to advertise a "Read API (planned)" over three paths under an /api
  // prefix (station json, survey json, station edi). No such tier has ever existed on any AusMT
  // deployment; those three lines were fiction. What the site actually serves is read-only static JSON
  // under /data/, so the section now lists the LIVE endpoints for the station in front of the reader:
  //   * the per-station products, keyed by the survey slug + the station id (the same path
  //     loadStationFrameLine() already fetches, so it is provably the real product location).
  //     station.json is emitted for EVERY station: a non-served one gets a withheld stub that states
  //     the access level, so the line resolves and is worth pointing at. dimensionality.json is NOT:
  //     it is a pure interpretation of the withheld transfer function, so the engine returns before
  //     writing it for a non-served survey (build_portal._write_station_products) and the live site
  //     404s that path for every embargoed / metadata_only station. It is therefore gated on the SAME
  //     predicate the engine gates emission on, access.level == "open" (isOpenAccess). Advertising it
  //     unconditionally would reintroduce, at ~17% of the catalogue, exactly the dead-endpoint defect
  //     this section was rewritten to remove;
  //   * this station's OWN served EDI, taken from its manifest artifact row. The url is READ, never
  //     templated: the served filename is genuinely not derivable from the station id (live corpus:
  //     station A1 of vulcan-2022 is served as edi/vulcan-2022/Vulcan_A1.edi). No row => no line,
  //     which is exactly the embargo case (withheld by construction, so there is nothing to link).
  //   * the two survey-level documents every consumer starts from.
  // Docs wave, stage 2 (owner ruling 3): the trailing pointer used to send readers to About's
  // "Fetching data via API". About is now a front door carrying a quickstart, and the worked
  // patterns (per-station manifest fetch, bounding box, checksum verification) live on the docs site's
  // API reference. The pointer goes there, to the same stable RTD path About links, so the two surfaces
  // agree on where depth lives. tests/test_drawer_api_endpoints.py pins the URL string against About's.
  const _apiSlug=s.slug||((SMETA[s.survey]||{}).slug)||"";
  const _apiEdi=_arts.find(a=>a.format==="edi");
  const _apiRows=[];
  if(_apiSlug&&s.id){const _pp="/data/products/"+encodeURIComponent(_apiSlug)+"/"+encodeURIComponent(s.id)+"/";
    _apiRows.push(_pp+"station.json");
    if(isOpenAccess(m))_apiRows.push(_pp+"dimensionality.json");}
  if(_apiEdi&&_apiEdi.url)_apiRows.push(apiArtifactPath(_apiEdi.url));
  _apiRows.push("/data/surveys.json","/data/products/manifest.json");
  // Two-phase boot: the per-station EDI line is READ from a manifest row, and "no row => no line" is a
  // deliberate embargo signal. Before the manifest lands there is no row for ANY station, so the list would
  // silently under-state itself; the loading line says which line is still to come rather than omitting it
  // in silence. The four survey/product paths above are static and stay listed immediately.
  const apiBlock=`<div class="api">Read-only static JSON on the hosted site, no key required:<br>`+
    _apiRows.map(u=>`GET <b>${esc(u)}</b>`).join("<br>")+
    (_manGate?`<br>${_manGate}`:"")+
    `<br><a href="https://ausmt.readthedocs.io/en/latest/interoperability/api-reference/">worked examples in the API reference</a></div>`;
  const provenanceHtml=`<div class="sechead">Provenance ${roleChip("Source data")}</div>`+provTop+maturityBlock(s)+
    `<details class="prov-d"><summary>Lineage graph</summary><div class="prov-dbody">${provGraph(s)}</div></details>`+
    provenanceBox(s)+
    // Card-lane polish: OMIT the Identifiers & instruments expander entirely when there is nothing to show
    // (a zero-identifier survey), rather than rendering an empty disclosure.
    (identifiersHtml(m)?`<details class="prov-d"><summary>Identifiers &amp; instruments</summary><div class="prov-dbody">${identifiersHtml(m)}</div></details>`:"")+
    // R8: the badge set tells the DISTRIBUTED-FORMATS story — EDI, EMTF XML (via pipeline), MTH5, time
    // series (from the levels metadata) and the licence badge. The bare "DOI" badge is dropped (it failed
    // as communication; dataset-DOI presence is already conveyed by the maturity star and the identifiers
    // block). States stay honest (ok/unknown/no). EMTF XML is ok when a served artifact exists, else part.
    // Two-phase boot: the EMTF XML and MTH5 badge STATES are manifest-derived, so the whole badge row waits
    // rather than briefly showing "part"/"unknown" for formats that are in fact served.
    `<details class="prov-d"><summary>Format availability</summary><div class="prov-dbody">${_manGate||`<div class="badges">${badge("EDI","ok")}${badge("EMTF XML",_fmtXmlArt?"ok":"part","EMTF XML is produced in the build pipeline (mt_metadata); served for redistributable surveys.")}${badge("MTH5",mth5BundleFor(m)?"ok":"unk")}${badge("time series",(m.ts_levels&&m.ts_levels.length)?"ok":(m.ts||"unk"))}${licBadge}${s.fixed?badge("coord QC","part","Coordinates were flagged during QC; see this station's provenance and treat with caution."):""}</div>`}</div></details>`+
    `<details class="prov-d"><summary>Record metadata</summary><div class="prov-dbody">${metaTable}</div></details>`+
    `<details class="prov-d"><summary>API</summary><div class="prov-dbody">${apiBlock}</div></details>`;
  // Cite — the citation box. C46-W3b: a no-cite survey is EXPLICIT ("custodian citation not recorded — cite
  // the survey package") rather than a silent AUSMT_SELF masquerade, and the captured attribution statement
  // (verbatim, else org(year) synthesis) renders alongside. The copy buttons keep their assembly helpers.
  const _attn=attributionText(m);
  // R3: the citation box renders the DOI as a resolution-aware hyperlink (apaCiteDisplay); the copy buttons
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
    // HIDDEN pending design review (owner 2026-07-22): screening surface not public-ready — restore by uncommenting.
    /* drawerPanel("screening",screeningHtml,false)+ */
    drawerPanel("files",filesHtml,false)+
    drawerPanel("provenance",provenanceHtml,false)+
    drawerPanel("cite",citeHtml,false);
  _curTf=t;                                        // stash for the expand-modal handler
  _curStation=s;                                   // stash the station for the response modal's identity header
  drawer.setAttribute("aria-label","Station "+s.id+" details");   // E7: refine the dialog label per subject
  drawer.classList.add("open");drawer.scrollTop=keepScroll;showDrawerScrim();   // D: dim backdrop on non-map views
  selectDrawerTab(keepTab);                        // UX8 (X4): Response default-selected (a rehydrate keeps the reader's tab)
  _restoreOpenDetails(keepOpen);                   // and the expanders they had open (empty on a real open)
  if(!rehydrate)_focusDrawer();                    // E7: move focus into the dialog (never on a hydration re-render)
  if(isOpenAccess(m)) loadStationFrameLine(s);     // C25-V3: inject the frame line if this station declares one
}
// Two-phase boot: re-render whatever the drawer is currently showing, IN PLACE, because a phase-2 product
// just landed and one of its sections was rendering a loading state. A no-op when the drawer is closed, or
// when it is showing something that reads no phase-2 product (the strike rose writes its own markup and
// clears the subject). Scroll offset and the active tab are preserved, so nothing jumps under the reader.
function rehydrateOpenDrawer(){
  if(!_drawerSubject)return;
  if(!(drawer&&drawer.classList&&drawer.classList.contains&&drawer.classList.contains("open")))return;
  if(_drawerSubject.kind==="station"&&ST[_drawerSubject.i])openStation(_drawerSubject.i,{rehydrate:true});
  else if(_drawerSubject.kind==="survey")openSurvey(_drawerSubject.sv,{rehydrate:true});
}
function closeDrawer(){const wasOpen=drawer.classList.contains&&drawer.classList.contains("open");
  _drawerSubject=null;                                 // nothing to rehydrate once it is shut
  drawer.classList.remove("open");hideDrawerScrim();   // D: drop the dim backdrop
  if(location.hash.startsWith("#/station"))history.replaceState(null,"",location.pathname+location.search);
  if(wasOpen)_restoreDrawerFocus();}               // E7: return focus to the invoking element (only if it was open)
async function fetchEdi(file,avail,survey){
  // C7: this EDI isn't redistributable here. Its dataset DOI (m.doi), when the survey has one, is the
  // TF source archive and is safe to open. There is NO honest substitute when no dataset DOI is
  // recorded — TS_COLLECTION is the raw TIME-SERIES collection, not a transfer-function source archive,
  // and silently opening it mislabels a different dataset as "the source archive" (the pre-C7 defect).
  if(!avail){const m=SMETA[survey]||{};
    if(m.doi){toast("This EDI isn't redistributable here; opening the source archive.");
      window.open("https://doi.org/"+m.doi,"_blank","noopener,noreferrer");}
    else toast("This EDI isn't redistributable here: "+withheldReason(m)+".");
    return;}
  // Route through dataUrl() (honours data_base_url) — NOT a hardcoded "data/edi/" path, so the
  // portal and its data can live in separate repos / on NCI.
  return downloadUrl(dataUrl("edi/"+file),file);}
// Generic blob download for a resolved manifest URL (EMTF XML, per-survey bundles, EDI fallback).
async function downloadUrl(url,filename){
  try{const r=await fetch(url);if(!r.ok)throw 0;const b=await r.blob();
    const a=document.createElement("a");a.href=URL.createObjectURL(b);a.download=filename||url.split("/").pop();a.click();URL.revokeObjectURL(a.href);}
  catch(e){toast("Download works when served over HTTP next to the data files; can't fetch over file://.");}}
function copyTxt(t){navigator.clipboard?.writeText(t).then(()=>toast("Copied.")).catch(()=>toast("Copy failed; select manually."));}

// UX3 item 6: the survey card description comes from the survey.yaml abstract, which the engine already
// carries into SMETA as m.blurb (build_portal.py). Render the escaped abstract when present and non-empty;
// otherwise an HONEST muted single line — no fabricated marketing copy (the old hardcoded placeholder
// implied content that wasn't there). esc() makes a hostile abstract (e.g. <img onerror=…>) render inert.
function cardDesc(m){
  const blurb=(m&&typeof m.blurb==="string")?m.blurb.trim():"";
  return blurb
    ? `<div class="desc">${esc(blurb)}</div>`
    : `<div class="desc desc-empty">No survey description provided; add an <code>abstract</code> to survey.yaml.</div>`;
}
// UX6 Wave E: a survey's declared acquisition window as display text — the dates string when present,
// else the year_start(-end) range; "" when neither is declared (caller omits the field). Shared by the
// slim survey card and the compact list row so both read the same value.
function acqYearText(m){return m.dates?esc(m.dates):(m.year_start?esc(String(m.year_start))+(m.year_end&&m.year_end!==m.year_start?"–"+esc(String(m.year_end)):""):"");}
// UX6 Wave E (E1): SLIM survey card. Field set is deliberately reduced to: title · organisation ·
// collection chip · acquisition year · station count · data-type mixbar · period range · licence + DOI
// badges · short description · two actions (View survey, Download). The heavier blocks that used to live
// on the card — the persistent-identifiers rollup (identifiersHtml), the APA citation (.cite), the
// spatial extent, the coordinate-QC flag tally, and the per-format availability matrix (EDI/time-series/
// MTH5 badges) — are NOT deleted from the codebase; they still render in the survey DETAIL (openSurvey)
// and the station drawer. The automated completeness/smoothness check is intentionally OMITTED from the
// card (it must never read as a card-level verdict) and stays in the detail + drawer with its framing.
function surveyCard(sv){const ss=ST.filter(s=>s.survey===sv),m=SMETA[sv]||{};
  const mix={};ss.forEach(s=>mix[s.type]=(mix[s.type]||0)+1);
  const pmin=Math.min(...ss.map(s=>s.pmin)),pmax=Math.max(...ss.map(s=>s.pmax));
  const mixbar=Object.entries(mix).map(([ty,n])=>`<div style="width:${100*n/ss.length}%;background:${TYPE_COL[ty]}" title="${esc(ty)}: ${n}"></div>`).join("");
  const yearTxt=acqYearText(m);
  return `<div class="scard"><div class="scardhead"><h3 style="cursor:pointer" data-act="story" data-survey="${escAttr(sv)}" title="Open survey">${esc(sv)}</h3>`+(m.collection&&m.collection.id?`<span class="chip collchip" data-act="collection" data-coll="${escAttr(m.collection.id)}" title="Explore collection">${esc(m.collection.title||m.collection.id)}</span>`:"")+`</div><div class="cust">${orgNameLink(m.org||"custodian unknown",m.org_ror)} · ${esc(m.country||"")}</div>`+
   `<div class="mixbar">${mixbar}</div>`+
   `<div class="stats"><b>${ss.length}</b> station${ss.length===1?"":"s"}${yearTxt?` · acquired <b>${yearTxt}</b>`:""}<br>periods <b>${fmtP(pmin)}–${fmtP(pmax)}s</b></div>`+
   `<div class="badges">${badge(m.lic||"licence ?",licBadgeState(m.lic))}${badge("DOI",hasDatasetDoi(m)?"ok":"no")}</div>`+
   cardDesc(m)+
   `<div class="cardbtns"><button data-act="story" data-survey="${escAttr(sv)}">View survey</button><button data-act="select" data-survey="${escAttr(sv)}">Download</button></div></div>`;}
function pidLink(p){if(!p)return "<span class='prov'>not recorded</span>";if(p.startsWith("TODO"))return "<span class='prov'>not recorded</span>";
  const href=p.startsWith("http")?p:(p.startsWith("10.")?"https://doi.org/"+p:"https://hdl.handle.net/"+p);return `<a href="${escUrl(href)}" target="_blank" rel="noopener noreferrer">${esc(p)}</a>`;}
// A person's ORCID as a small icon-link (self-hosted vendor logo, CSP-safe same-origin); "" when absent,
// so callers append it directly after the escaped name.
function orcidLink(o){if(!o)return "";const href="https://orcid.org/"+o;
  return ` <a href="${escUrl(href)}" target="_blank" rel="noopener noreferrer" title="ORCID: ${escAttr(o)}" class="orcid-ico"><img src="vendor/ORCID_iD.png" alt="ORCID" class="idlogo orcid-logo"></a>`;}
// Credit model (SPEC §3.1): the DataCite contributorType subset -> a human role phrase. Fail-closed vocab;
// an absent or out-of-vocab role adds no phrase (the validator blocks a bad token upstream, so this never
// echoes a raw token).
const CONTRIBUTOR_ROLE_LABELS={ProjectLeader:"led",ProjectMember:"project member",DataCollector:"collected the data",
  ContactPerson:"contact",DataCurator:"curated",Sponsor:"sponsored",RightsHolder:"rights holder",Distributor:"distributed"};
// The RATIFIED display order for a person's role phrases when they hold several (SPEC §3.1). Pinned
// explicitly (not left to object-key order) so a grouped person's phrases read in ONE stable sequence
// regardless of the order their contributor rows were declared in. Keyed against CONTRIBUTOR_ROLE_LABELS.
const CONTRIBUTOR_ROLE_ORDER=["ProjectLeader","ProjectMember","DataCollector","ContactPerson","DataCurator","Sponsor","RightsHolder","Distributor"];
// An ORCID grouping key: lower-cased, resolver-prefix stripped, trailing slashes dropped, so the bare id
// and the full https://orcid.org/<id> URL form collapse to the SAME person. "" when no ORCID (the caller
// then dedupes on name + name_type instead).
function orcidKey(o){return o?String(o).trim().toLowerCase().replace(/^https?:\/\/orcid\.org\//,"").replace(/\/+$/,""):"";}
// One contributor's NAME cell (no role phrase): an organisation links to its ROR, a person carries the
// ORCID icon-link. Shared by the grouped Contributors list. "" for a nameless row (blank-over-placeholder,
// so the caller drops it silently rather than printing an empty placeholder).
function contributorName(c){
  const name=((c&&c.name)||"").toString().trim();
  if(!name)return "";
  return c.name_type==="organisation"?orgNameLink(name,c.ror):esc(name)+orcidLink(c.orcid);}
// Credit model (SPEC §3/§6): the survey's contributors[] as a COLLAPSED <details> (styled like the
// Persistent-identifiers rollup), GROUPED by person. The old surface printed one line per (person, role)
// row; a survey with 7 people across 15 role rows printed 15 lines. Now rows dedupe by ORCID (case /
// URL-form-insensitive) else by exact name + name_type, preserving first-appearance order, and each distinct
// person renders ONE line: the name (ORCID/ROR link as before) then their role phrases comma-joined in the
// RATIFIED role order. An unknown/absent role adds no phrase (never a raw token); a nameless row is dropped
// silently and never counted. The summary counts the DISTINCT people/orgs. Returns "" (no section, no
// placeholder) when the list is absent or empty, matching sourcesListHtml/instrumentPidsHtml.
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
// Credit model (SPEC §2.1): the survey's ORDERED creators[], the attribution-author list. Order IS the
// attribution order; a person carries the ORCID icon-link, an organisation's name links to its ROR. No role
// phrase (that is the contributors[] surface). Reads the pinned seam field verbatim; a creator row is the
// same {name, name_type, orcid, ror} shape as a contributor minus the role. "" for a nameless row.
function creatorRow(c){
  const name=((c&&c.name)||"").toString().trim();
  if(!name)return "";
  return c&&c.name_type==="organisation"?orgNameLink(name,c.ror):esc(name)+orcidLink(c.orcid);}
// Card-lane polish (owner ruling): ONE attribution box, never two. The Attribution section used to render
// the sentence and the creator names as two separate, visually identical .attn boxes, and because the
// engine builds cite.au from creators[] (CONTRIBUTOR-CREDIT-SPEC §2.1, names joined "; "), those two boxes
// carried the SAME names twice. They merge here: the single box renders the ONE attribution sentence with
// each creator name ORCID/ROR-linked IN PLACE (creatorRow, the same per-name link rendering as before),
// keeping the "; " separators and the "(year)" tail of the plain sentence.
// The links are substituted ONLY when the creators reconstruct the sentence's own name string (the §2.1
// guarantee: cite.au IS the "; "-joined creators). A verbatim custodian attribution.statement is never
// rewritten, and a survey whose recorded citation names someone else keeps that recorded string: in both
// cases the flat escaped sentence renders exactly as today, in the SAME single box. That keeps the drawer
// byte-identical in TEXT to exports.attributionLine (the CSV / citation-pack / Cite-tab attribution).
// Returns "" when the survey has no attribution sentence at all, so the caller omits the whole section.
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
// name). The Funding section owns this display; the identifiers rollup no longer duplicates the funders line.
function funderHtml(f){f=f||{};
  const name=esc(f.name||"");
  const nm=f.pid?`<a href="${escUrl(f.pid)}" target="_blank" rel="noopener noreferrer">${name}</a>`:name;
  return nm+(f.grant_id?` <span class="prov">(${esc(f.grant_id)})</span>`:"");}
// C7: a ROR value may be a bare id (00892tw58) or a full https://ror.org/... URL — resolve either to
// the canonical ror.org landing page link.
function rorLink(r){if(!r)return null;const href=r.startsWith("http")?r:"https://ror.org/"+r;return `<a href="${escUrl(href)}" target="_blank" rel="noopener noreferrer">${esc(r)}</a>`;}
// owner 2026-07-22: when the organisation carries a ROR, its NAME is the link to the ror.org landing page
// (replacing the separate ROR logo badge). No ROR -> plain escaped name. esc/escUrl keep a hostile org/ror value inert.
function orgNameLink(name,r){const t=esc(name); if(!r) return t;
  const href=r.startsWith("http")?r:"https://ror.org/"+r;
  return `<a class="orglink" href="${escUrl(href)}" target="_blank" rel="noopener noreferrer" title="ROR: ${escAttr(r)}">${t}</a>`;}
// C7: a RAiD identifier is already a resolvable https://raid.org/... URL (per the survey.yaml comment
// and the validator's format check); a bare id falls back to that same host.
function raidLink(r){if(!r)return null;const href=r.startsWith("http")?r:"https://raid.org/"+r;return `<a href="${escUrl(href)}" target="_blank" rel="noopener noreferrer">${esc(r)}</a>`;}
// PID-schema: an instrument's `pid` is a persistent identifier for an instrument SYSTEM (the AuScope
// Instrument Registry URL/handle). It is curator-asserted free text — render it as a link ONLY through
// the same escUrl guard the other PID links use (a non-http(s)/mailto/relative value -> href "#", inert),
// so a hostile `javascript:...` / `<img onerror=...>` value can never become an executable/anchor. A bare
// handle falls back to the handle-resolver host, mirroring pidLink. Absent pid -> no link (caller omits it).
function instrumentPidLink(p){if(!p)return null;const s=String(p);
  const href=s.startsWith("http")?s:(s.startsWith("10.")?"https://doi.org/"+s:"https://hdl.handle.net/"+s);
  return `<a href="${escUrl(href)}" target="_blank" rel="noopener noreferrer">${esc(s)}</a>`;}
// PID-schema: the per-instrument PID line, shown only when SMETA carries the structured `instruments`
// list (the engine attaches it ONLY when at least one instrument declares a pid — see _instruments_of).
// Each instrument prints its manufacturer/model label with its registry PID as a trailing link; an
// instrument WITHOUT a pid in that list prints just the (escaped) label. Returns "" when no list -> the
// existing "Instrument model:" line above remains the sole instrument row (byte-identical old surveys).
function instrumentPidsHtml(m){
  const list=(m.instruments||[]);
  if(!list.length)return "";
  // R7: an instrument with a model but no PID shows JUST the model (no "(no PID)" suffix).
  const rows=list.map(i=>{const label=[i.manufacturer,i.model].filter(Boolean).map(esc).join(" ")||"instrument";
    const link=instrumentPidLink(i.pid);
    return link?`${label}: ${link}`:label;}).join("<br>");
  return `Instrument PIDs:<br><span class="pidline">${rows}</span>`;}
// §2a (identifiers design — the related-identifiers model): DataCite relation -> a human label. An
// out-of-vocab relation (should never publish — the validator FAILs it) falls back to the escaped raw
// value; a blank relation to a neutral "Related".
const RELATION_LABELS={IsDerivedFrom:"Derived from",IsVariantFormOf:"Variant form of",
  IsSupplementTo:"Supplement to",Cites:"Cites",IsPartOf:"Part of",IsSourceOf:"Source of"};
// D-L1/D-L4 (SPEC §9): `identifies` states WHAT the identifier points at, in NCI Table 1 data-level terms.
// When present it labels the row by LEVEL (e.g. "Raw time series", "Collection", "Entire dataset"),
// falling back to the DataCite relation label for a legacy row that carries no identifies. Table 1 order.
const IDENTIFIES_LABELS={collection:"Collection",raw_packed:"Raw time series",level0:"Level 0, edited time series",
  level1:"Level 1, transformed time series",level2:"Level 2, processed data",level3:"Level 3, models",
  entire:"Entire dataset"};
// §2a: a typed provenance identifier -> a link whose resolver host is chosen by identifier_type, ALWAYS
// through the escUrl guard (a hostile identifier value can never become an executable/relative anchor —
// same posture as pidLink/instrumentPidLink). DOI -> doi.org (unless already a URL); Handle ->
// hdl.handle.net; URL -> itself. ANY OTHER type (RAiD, an unknown, or none) -> escaped PLAIN TEXT with NO
// anchor: we will not invent a resolver for a type we do not model, and an unlinked value stays inert.
// §2a: the resolver URL for a typed identifier, chosen by identifier_type. DOI -> doi.org (unless already
// a URL); Handle -> hdl.handle.net; URL -> itself. ANY OTHER type (RAiD, unknown, none) -> null: we do not
// invent a resolver for a type we do not model. Shared by relatedIdLink (the block anchor) and the files
// tab (which needs the raw URL for a product tile's data-url). escUrl still guards at the anchor/attr edge.
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
// IDCONS D4 (SPEC §5.4): render an identifier HONESTLY given its resolution facet from the pid_status
// cache (attached by build_portal.apply_pid_resolution). "reserved" = doi.org's OWN 404, a reserved-but-
// not-yet-active DOI (e.g. a freshly-minted NCI PID whose handle mapping is not live) -> plain escaped
// text + a muted "(reserved — not yet active)" note, NEVER an anchor: we do not ship a dead link. "ok" /
// "unknown" / absent (no cache) -> the caller's normal link, byte-for-byte as today (unknown = today).
function reservedText(text){return `${esc(text)} <span class="prov reserved-note">(reserved, not yet active)</span>`;}
function resolvedOr(resolution,text,linkHtml){return resolution==="reserved"?reservedText(text):linkHtml;}
// IDCONS D4: the raw-TS collection cell — a link to the survey's OWN collection PID (or the NCI default),
// rendered as plain text + reserved note when the survey's own ts_pid is reserved. The NCI default
// collection is a known-live handle, so it is never gated (only the survey's own ts_pid carries a facet).
function tsCollectionCell(m){
  const label=m.ts_pid?"survey collection":"NCI collection";
  if(m.ts_pid&&m.ts_pid_resolution==="reserved")return reservedText(tsPidRaw(m));
  return `<a href="${escUrl(tsUrlFor(m))}" target="_blank" rel="noopener noreferrer">${label}</a>`;}
// The Provenance-tab "Source archive" cell. Preference: the related_identifier that IDENTIFIES the source
// data by NCI data level (raw_packed, then collection, then entire), rendered with the SAME resolution
// honesty the Files tab / identifiers block use (reserved -> plain text + note, else a typed link); then
// the flat dataset DOI; then the raw-TS collection cell; else the honest "not recorded". Derives from the
// same typed provenance the Files tab keys off, so an identifier-bearing survey shows its real archive
// instead of "not recorded". Pure (reads m only) so the derivation is unit-testable.
function sourceArchiveCell(m){m=m||{};
  const rels=(m.related_identifiers||[]).filter(r=>r&&typeof r==="object");
  for(const lvl of ["raw_packed","collection","entire"]){
    const r=rels.find(x=>x.identifies===lvl&&x.identifier);
    if(r)return r.resolution==="reserved"?reservedText(r.identifier):relatedIdLink(r.identifier,r.identifier_type);
  }
  if(m.doi)return resolvedOr(m.doi_resolution,"doi:"+m.doi,`<a href="${escUrl("https://doi.org/"+m.doi)}" target="_blank" rel="noopener noreferrer">doi:${esc(m.doi)}</a>`);
  return m.ts==="ok"?tsCollectionCell(m):"<span class='prov'>not recorded</span>";}
// §2a: the related-identifiers block — one line per typed relation (SMETA.related_identifiers, served by
// the engine mapper as always-a-list). The relation prints as a human label, the identifier as a
// type-linked value, the custodian (when present) in muted text. Empty list -> "" (the section simply
// does not render, mirroring instrumentPidsHtml). Non-mapping entries are skipped defensively.
function relatedIdentifiersHtml(m){
  const list=(m.related_identifiers||[]).filter(r=>r&&typeof r==="object");
  if(!list.length)return "";
  const rows=list.map(r=>{
    // D-L1: label by the data LEVEL when identifies is present; else fall back to the relation label.
    const label=(r.identifies&&IDENTIFIES_LABELS[r.identifies])||RELATION_LABELS[r.relation]||(r.relation?esc(r.relation):"Related");
    const cust=r.custodian?` <span class='prov'>(${esc(r.custodian)})</span>`:"";
    // IDCONS D4: a reserved identifier renders as plain text + note, not an anchor (never a dead link).
    const idCell=r.resolution==="reserved"?reservedText(r.identifier):relatedIdLink(r.identifier,r.identifier_type);
    return `${label}: ${idCell}${cust}`;}).join("<br>");
  return `Related identifiers:<br><span class="pidline">${rows}</span>`;}
// §2a: "a persistent dataset identifier exists in this survey's provenance chain" — the ratified reading
// of the DOI maturity badge. TRUE when a minted dataset DOI is set OR any typed related_identifier is a
// DOI, so a curator survey (dataset_doi null, the DOI living in the typed provenance list) still lights
// the badge. Shared by BOTH badge sites (station format-availability + survey card) via this one predicate.
function hasDatasetDoi(m){return !!(m&&(m.doi||(m.related_identifiers||[]).some(r=>r&&r.identifier_type==="DOI")));}
// R7 (owner ruling — reverses the earlier explicit-absence posture): the rollup renders ONLY the rows that
// carry a value. No "not recorded", no "(no PID)", no "not recorded in source metadata" noise; an instrument
// with a model but no PID shows just the model; a group with no content is omitted (heading included). The
// underlying keys are still SERVED — only the empty ROWS are dropped. IDCONS D2's retired Survey-PID row
// stays gone.
function identifiersHtml(m){
  const rows=[];
  if(m.doi)rows.push(`Dataset DOI: <span class="pidline">${resolvedOr(m.doi_resolution,m.doi,pidLink(m.doi))}</span>`);
  const ror=rorLink(m.org_ror); if(ror)rows.push(`Organisation ROR: <span class="pidline">${ror}</span>`);
  const raid=raidLink(m.raid); if(raid)rows.push(`Project RAiD: <span class="pidline">${raid}</span>`);
  const rel=relatedIdentifiersHtml(m); if(rel)rows.push(rel);
  if(m.instrument_model)rows.push(`Instrument model: ${esc(m.instrument_model)}`);
  if(m.instrument_pid)rows.push(`Platform/instrument PID: <span class="pidline">${instrumentPidLink(m.instrument_pid)}</span>`);
  const instr=instrumentPidsHtml(m); if(instr)rows.push(instr);
  // Funders are shown (with grant ids) by the survey card's own Funding section; the identifiers rollup no
  // longer duplicates them here.
  if(!rows.length)return "";
  return `<div class="surveymeta"><b>Persistent identifiers &amp; instruments</b><br>${rows.join("<br>")}</div>`;}
// One related-publication citation. Robust to two real-corpus shapes: (1) a DOI value that is already a
// full https://doi.org/ URL (the NVP harvester emits URL-form DOIs); the prefix is stripped before the
// href/label so the resolver gets a single prefix (no doi.org/https://doi.org/ double-prefix) and the
// label reads doi:<id>; (2) a row missing author/year/journal, the empty "(). ." skeleton is skipped and
// only the present pieces (title + link) render.
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
// UX6 Wave E (E3): discovery controls for the Surveys view. State lives in this module (the controls are
// static in index.html; the coordinator/rail filters are untouched). FORBIDDEN by contract: sorting or
// faceting by the automated completeness/smoothness check — the screen must never become a ranking, so
// none of the sort modes or facets below reference s.q / the check.
let _sortMode="name",_cardLayout="cards";
const _facets={lic:false};                          // presence facets (currently just "Open licence")
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
  if(_typeFacets.size){                             // type chips: a survey passes if ANY of its stations' type is selected
    const types=_surveyTypeSet(sv);let any=false;
    _typeFacets.forEach(t=>{if(types.has(t))any=true;});
    if(!any)return false;}
  return true;}
function sortSurveys(list){const arr=[...list],m=sv=>SMETA[sv]||{};
  if(_sortMode==="stations")arr.sort((a,b)=>_stationCount(b)-_stationCount(a)||a.localeCompare(b));
  else if(_sortMode==="year")arr.sort((a,b)=>_yearKey(m(b))-_yearKey(m(a))||a.localeCompare(b));       // newest first
  else if(_sortMode==="recent")arr.sort((a,b)=>{                                                       // same "latest date" rule as the feed / recently-added strip
    const da=(typeof surveyLatestDate==="function"?surveyLatestDate(m(a)):null)||"",
          db=(typeof surveyLatestDate==="function"?surveyLatestDate(m(b)):null)||"";
    return da<db?1:da>db?-1:a.localeCompare(b);});
  else arr.sort((a,b)=>a.localeCompare(b));                                                            // "name" (default)
  return arr;}
// Compact/list layout row (E3): a single line — title, org, acquisition year, station count, licence badge.
function surveyRow(sv){const ss=ST.filter(s=>s.survey===sv),m=SMETA[sv]||{};const yearTxt=acqYearText(m);
  return `<div class="srow"><button class="srow-title" data-act="story" data-survey="${escAttr(sv)}" title="Open survey">${esc(sv)}</button>`+
    `<span class="srow-org">${esc(m.org||"–")}</span>`+
    `<span class="srow-year">${yearTxt||"–"}</span>`+
    `<span class="srow-stn">${ss.length} station${ss.length===1?"":"s"}</span>`+
    `<span class="srow-lic">${badge(m.lic||"licence ?",licBadgeState(m.lic))}</span></div>`;}
function renderDiscovery(n){
  const cnt=document.getElementById("surveyCount");
  if(cnt)cnt.textContent=n+" survey"+(n===1?"":"s");
  const fc=document.getElementById("facetChips");
  if(!fc)return;
  // "Open licence" (presence) + one chip per corpus-present data type (BBMT/LPMT/AMT/GDS), multi-select.
  const chips=[`<button type="button" class="facet${_facets.lic?" on":""}" data-facet="lic" aria-pressed="${_facets.lic?"true":"false"}">Open licence</button>`];
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
// "Clear filters" (cleanup wave B): drop the discovery facets (licence + data-type chips) and the
// discovery search query, the view-level narrowings this bar owns, then re-render the grid and the
// header count. The map's own rail search (#find) and structural filters are a separate surface; this
// never reaches across into them.
function clearDiscoveryFilters(){
  Object.keys(_facets).forEach(k=>_facets[k]=false);
  _typeFacets.clear();
  const s=document.getElementById("surveySearch");
  if(s&&s.value)s.value="";
  renderCards();
  if(typeof updateCounts==="function")updateCounts();}
function focusSurvey(sv){tree.querySelectorAll('input[value]').forEach(c=>c.checked=(c.value===sv));setView("map");refresh();
  // C42: fit only POSITIONED stations — a withheld-coord station has no [lat,lon] to bound (avoids NaN bounds).
  const _fb=ST.filter(s=>s.survey===sv&&hasPosition(s)).map(s=>[s.lat,s.lon]);if(_fb.length)map.fitBounds(L.latLngBounds(_fb).pad(0.15));}
function selectSurvey(sv){
  // Stage B (selection-state isolation): scoping the map to one survey is a TEMPORARY LENS. Snapshot the
  // tree BEFORE mutating it (enterSelectLens, filters.js) and enter Select & export so the exports this
  // selection enables are visible (they live in the Select pane). The lens is restored when the visitor
  // returns to Browse or leaves the map. The Surveys catalogue no longer reads this tree state at all
  // (surveyVisible), so the scoping can never empty it; the snapshot keeps the MAP tree honest too.
  if(typeof enterSelectLens==="function")enterSelectLens();
  tree.querySelectorAll('input[value]').forEach(c=>c.checked=(c.value===sv));setView("map");
  if(typeof setSidebarMode==="function")setSidebarMode("select");
  refresh();
  selected=new Set(ST.filter(s=>s.survey===sv).map(s=>s.i));updateSel();
  const _sb=ST.filter(s=>s.survey===sv&&hasPosition(s)).map(s=>[s.lat,s.lon]);if(_sb.length)map.fitBounds(L.latLngBounds(_sb).pad(0.15));toast(`Selected all ${selected.size} ${sv} stations; use the download buttons in the left panel.`);}

// C42: bbox over POSITIONED stations only — a withheld-coord station (null lat/lon) would poison Math.min/max
// with NaN. Empty (all-withheld survey) => a degenerate 0° box so callers never crash on b.e/b.w.
function bbox(ss){const p=(ss||[]).filter(hasPosition),xs=p.map(s=>s.lon),ys=p.map(s=>s.lat);
  return xs.length?{w:Math.min(...xs),e:Math.max(...xs),so:Math.min(...ys),no:Math.max(...ys)}:{w:0,e:0,so:0,no:0};}
// Survey footprint mini-scatter. The in-plot corner label is gone; instead the plot box carries OUTSIDE
// axis ticks: 3 latitude labels down the left margin, 3 longitude labels along the bottom (1 dp, degree
// suffix, monospace 9px), with a small tick mark on the box edge at each. The SVG is responsive (viewBox +
// width:100%) so it scales inside the resizable drawer. A degenerate/withheld-coords bbox (0° box) draws
// no dots and repeated 0.0° labels but never crashes (dx/dy carry the ||1 guard; bbox is empty-safe).
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
function relatedSurveys(sv){const m=SMETA[sv]||{},b=bbox(ST.filter(s=>s.survey===sv));
  return surveys.filter(o=>o!==sv).map(o=>{const os=ST.filter(s=>s.survey===o),ob=bbox(os);
    const sameOrg=(SMETA[o]||{}).org===m.org;
    const overlap=!(ob.w>b.e||ob.e<b.w||ob.so>b.no||ob.no<b.so);
    const sameCountry=(SMETA[o]||{}).country===m.country;
    return {o,score:(sameOrg?2:0)+(overlap?2:0)+(sameCountry?1:0)};}).filter(x=>x.score>0).sort((a,b)=>b.score-a.score).slice(0,4).map(x=>x.o);}
// Survey-level summary (10-second view): aggregates of already-computed per-station values + survey metadata only 
function surveySummary(ss,m){
  // UX3 item 7c: the "dimensionality mix (screening only)" row was removed from this table (dimensionality
  // is inferable from the phase tensor + skew). The per-station dim tally that fed it (dimCount/nClass/
  // dimPct) is gone with it; sc[SC.dim] itself is untouched (data products unchanged — display only).
  // Two-phase boot: the remote-reference tally and the derived processing-software mode come from sci.json
  // (PHASE 2). "not recorded" and the m.software fallback are claims about the source EDIs, so those two
  // rows wait for SCI_READY; every other row here is catalogue/survey metadata and is honest immediately.
  const sciGate=hydrGate("sci","processing details");
  const typeCount={}, swCount={}; let tipper=0, rr=0, rrKnown=0, pmin=Infinity, pmax=-Infinity;
  ss.forEach(s=>{ const sc=sciRow(s.i);
    if(s.type) typeCount[s.type]=(typeCount[s.type]||0)+1;
    if(sc[SC.sw]) swCount[sc[SC.sw]]=(swCount[sc[SC.sw]]||0)+1;
    if((s.comps||"").indexOf("T")>=0) tipper++;
    if(sc[SC.rr]!=null){ rrKnown++; if(sc[SC.rr]) rr++; }
    if(s.pmin!=null) pmin=Math.min(pmin,s.pmin);
    if(s.pmax!=null) pmax=Math.max(pmax,s.pmax); });
  const types=Object.keys(typeCount).sort().map(t=>`${t} ${typeCount[t]}`).join(" · ")||"–";
  const software=m.software||Object.keys(swCount).sort((a,b)=>swCount[b]-swCount[a])[0]||"not recorded";
  const coll=m.collection&&m.collection.id?`<a href="#" data-act="collection" data-coll="${escAttr(m.collection.id)}">${esc(m.collection.title||m.collection.id)}</a>`:"–";
  // Embargoed surveys append the embargo date to the access cell ("embargoed until 2027-02-01"); any other
  // access state (or an embargo with no date) renders the bare level as before.
  const _acc=m.access||"open";
  const _accTxt=(_acc==="embargoed"&&m.embargo_until)?"embargoed until "+esc(String(m.embargo_until)):esc(_acc);
  return `<div class="sechead">Survey summary <span style="font-weight:400;color:var(--muted);text-transform:none;letter-spacing:0">(10-second view)</span></div><table class="meta">`+
    `<tr><td>stations</td><td>${ss.length}</td></tr>`+
    `<tr><td>data types</td><td>${esc(types)}</td></tr>`+
    `<tr><td>period coverage</td><td>${isFinite(pmin)?fmtP(pmin)+" – "+fmtP(pmax)+" s":"–"}</td></tr>`+
    `<tr><td>tipper availability</td><td>${tipper} / ${ss.length} stations</td></tr>`+
    `<tr><td>remote reference</td><td>${sciGate||(rrKnown?`${rr} / ${rrKnown} stations`:"not recorded")}</td></tr>`+
    `<tr><td>instrumentation</td><td>${esc(m.instrument_model||"not recorded in source metadata")}</td></tr>`+
    `<tr><td>processing software</td><td>${sciGate||esc(software)}</td></tr>`+
    `<tr><td>acquisition</td><td>${esc(m.dates||"–")}</td></tr>`+
    `<tr><td>collection</td><td>${coll}</td></tr>`+
    `<tr><td>licence / access</td><td>${esc(m.lic||"?")} · ${_accTxt}</td></tr>`+
    `<tr><td>version</td><td>${esc(m.version||"–")}</td></tr>`+
    `</table>`;
}
// Release notes: shown only when a survey provides them (optional; no requirement for existing surveys).
function releaseNotesHtml(m){
  const rn=m.release_notes;
  if(!Array.isArray(rn)||!rn.length) return "";
  const rows=rn.map(e=>`<tr><td>${esc(e.version||"–")}</td><td>${esc(e.date||"")}${e.date&&e.note?": ":""}${esc(e.note||"")}</td></tr>`).join("");
  return `<div class="sechead">Release notes</div><table class="meta">${rows}</table>`;
}
// Pre-built per-survey download bundles from the manifest (EDI zip + EMTF-XML zip always when served;
// survey MTH5 only when the survey_h5_enabled flag produced one). Empty string when the survey isn't
// served. C32: the MTH5 bundle holds TRANSFER FUNCTIONS ONLY (never time series) — the label says so,
// matching the engine's <slug>-tf.h5 filename.
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
// UX6 Wave E (E2): persistent-identifier rollup count for the survey detail. IDCONS D2: the retired "Survey
// PID" (m.pid) slot is dropped — it is no longer a displayed row, so counting it would tally a slot the
// curator cannot see. The count now tracks the three single-value slots identifiersHtml still renders
// (dataset DOI, organisation ROR, project RAiD); a slot counts as recorded when it is truthy and not a
// "TODO…" placeholder (the same convention pidLink uses). The typed Related identifiers rows have their own
// visible block below. Drives the "Persistent identifiers: N of M recorded" summary.
function pidRollup(m){const has=v=>!!(v&&!String(v).startsWith("TODO"));
  const fields=[(m||{}).doi,(m||{}).org_ror,(m||{}).raid];
  return {have:fields.filter(has).length,total:fields.length};}
// Two-phase boot: `opts.rehydrate` has the same meaning as in openStation: a re-render driven by a phase-2
// product landing, which keeps the reader's scroll position and does not touch focus.
function openSurvey(sv,opts){const ss=ST.filter(s=>s.survey===sv),m=SMETA[sv]||{};
  const rehydrate=!!(opts&&opts.rehydrate);
  const keepScroll=rehydrate?(drawer.scrollTop||0):0;
  const keepOpen=rehydrate?_openDetailsKeys():[];     // expanders the reader opened mid-hydration stay open
  const rel=relatedSurveys(sv),pr=pidRollup(m);
  if(!rehydrate)_rememberDrawerOpener();              // E7: capture the invoking element before the rewrite
  _drawerSubject={kind:"survey",sv};                  // what rehydrateOpenDrawer re-renders when a gate settles
  // UX6 Wave E (E4): section order — (1) title+description, (2) geographic footprint, (3) station count +
  // period-range stats, (4) licence + downloads, (5) acquisition + processing, (6) contributors + funding,
  // (7) publications, (8) identifiers (E2 rollup), (9) release history. Content is unchanged from before —
  // only the order. Acquisition/processing are carried inside the survey-summary table (sections 3/5 share
  // that atomic block). Card-lane polish (owner): contributors (credit model, SPEC §3) no longer trail
  // below Downloads, they sit inside the ATTRIBUTION block directly beneath the attribution box.
  // Downloads move up ahead of funding/publications/identifiers; release history moves last.
  drawer.innerHTML=
   `<div class="dhead"><span class="sid" style="font-size:18px">${esc(sv)}</span><button class="close" aria-label="Close">✕</button></div>`+
   `<div class="dsub">${orgNameLink(m.org||"custodian unknown",m.org_ror)} · ${esc(m.country||"")}${m.region?" · "+esc(m.region):""} · ${esc(m.dates||"dates n/a")}</div>`+
   collLine(m)+
   `<div class="dim" style="margin-top:10px">${esc(m.blurb||"Survey description to be provided by the uploader.")}</div>`+
   miniScatter(ss)+
   surveySummary(ss,m)+
   // C46-W3b: the captured attribution statement rendered where the survey's attribution lives (verbatim
   // custodian statement, else the org(year) synthesis). Card-lane polish: that sentence is now ONE box
   // (attributionBoxHtml) carrying the creator names ORCID/ROR-linked in place, never a second names box,
   // and the collapsed "Contributors (N)" details moves UP to sit directly beneath it (credit reads as one
   // block: who to attribute, then who did what) instead of trailing below Downloads. The upstream
   // "Source datasets" list follows.
   (attributionText(m)?`<div class="sechead">Attribution ${roleChip("Source data")}</div>`+attributionBoxHtml(m):"")+
   contributorsHtml(m)+
   sourcesListHtml(m)+
   `<div class="sechead">Downloads</div><div class="prodgrid">`+
     surveyBundleTiles(m.slug)+
     `<div class="prod" data-act="select" data-survey="${escAttr(sv)}"><span class="pdot" style="background:var(--ok)"></span><div>All EDIs<small>select & download</small></div></div>`+
     `<div class="prod" data-act="focus" data-survey="${escAttr(sv)}"><span class="pdot" style="background:var(--lpmt)"></span><div>View on map<small>zoom to extent</small></div></div>`+
     // IDCONS D4: a reserved dataset DOI is shown as an inert, honestly-labelled chip — never a green
     // "source archive" tile that opens a doi.org 404.
     (m.doi?(m.doi_resolution==="reserved"
       ?`<div class="prod dis"><span class="pdot" style="background:var(--part)"></span><div>Dataset DOI<small>reserved (not yet active)</small></div></div>`
       :`<div class="prod" data-act="doi" data-doi="${escAttr(m.doi)}"><span class="pdot" style="background:var(--ok)"></span><div>Dataset DOI<small>source archive</small></div></div>`):"")+
   `</div>`+
   `<div class="sechead">Funding</div><div class="surveymeta">${(m.funders||[]).map(funderHtml).join(" · ")||"–"}</div>`+
   `<div class="sechead">Related publications</div>`+pubsHtml(m)+
   `<details class="prov-d survey-ids"><summary>Persistent identifiers: ${pr.have} of ${pr.total} recorded</summary><div class="prov-dbody">`+identifiersHtml(m)+`</div></details>`+
   releaseNotesHtml(m)+
   `<div class="sechead">Related surveys</div><div class="surveymeta">`+
     (rel.length?rel.map(o=>`<a href="#" data-act="story" data-survey="${escAttr(o)}">${esc(o)}</a>`).join(" · "):"<span class='prov'>none nearby</span>")+`</div>`;
  drawer.setAttribute("aria-label",sv+", survey details");
  drawer.classList.add("open");drawer.scrollTop=keepScroll;showDrawerScrim();   // D: dim backdrop on non-map views
  _restoreOpenDetails(keepOpen);                      // and the expanders they had open (empty on a real open)
  if(!rehydrate)_focusDrawer();}                      // E7: move focus into the dialog (never on a hydration re-render)

// ---- single delegated click handler (no inline onclick anywhere) ----
function collLine(m){
  const parts=[];
  if(m.version) parts.push(`Version ${esc(m.version)}`);
  if(m.collection&&m.collection.id) parts.push(`Part of: <a href="#" data-act="collection" data-coll="${escAttr(m.collection.id)}">${esc(m.collection.title||m.collection.id)}</a>`);
  return parts.length?`<div class="dsub" style="margin-top:3px">${parts.join(" · ")}</div>`:"";
}
// Collections INDEX (the "Collections" tab): one rich card per collection in COLL, opening the
// full-width collection page. A collection appears automatically when surveys share a collection.id.
// E5: the participating organisations of a collection, derived from its member surveys' SMETA (deduped, sorted).
function collOrgs(c){const set=new Set();((c&&c.surveys)||[]).forEach(sv=>{const o=(SMETA[sv]||{}).org;if(o)set.add(o);});return [...set].sort();}
// Cleanup wave (E): ONE rich collection card at ANY count; the earlier feature/compact two-branch split
// is gone. Title + type/status, the FULL abstract (no 240-char truncation, no Show more), the footprint
// scatter, rollup stats, participating organisations, and a prominent Explore action. Rendered into a
// responsive auto-fit grid (index.html .collfeature-grid) so it reads from one collection today to
// several (WA-MT, Vulcan) soon. Keeps the .scard.collfeature class the styling + tests key off.
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
// UX6 Wave E (E6): collection footprint. Fixed-Australia extent with a simplified coastline + state-
// boundary outline (vendor/au-outline.js — public-domain Natural Earth, see that file's header) drawn
// BENEATH the station dots; dots are COLOURED BY MEMBER SURVEY with a small legend. Degrades cleanly when
// AU_OUTLINE is absent (e.g. the headless harness doesn't load the vendor asset) — dots + legend still
// render. The projection is a plain equirectangular fit of the fixed AU box, so the outline and the dots
// stay registered; the canvas aspect matches the box to avoid squashing.
const AU_EXTENT={w:112,e:154,so:-44,no:-9};
const COLL_PAL=["#2E8FA3","#EF7256","#8A5FC0","#5BAE6A","#3F6FC4","#C255A0","#D9A23B","#A85454"];
// Fluid (viewBox + width:100%) so it scales inside its container; `maxW` optionally raises the max-width
// cap (the detail-page hero gives it more room than a list card). W stays the viewBox coordinate space so
// the geometry is identical regardless of rendered size. Both call sites pass just `ss` or `(ss,maxW)`.
function collScatter(ss,maxW){
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
  const members=[...new Set(ss.map(s=>s.survey))].sort();
  const col=sv=>COLL_PAL[members.indexOf(sv)%COLL_PAL.length];
  const dots=ss.filter(hasPosition).map(s=>{const p=proj(s.lon,s.lat);
    return `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="3" fill="${col(s.survey)}" fill-opacity=".9"><title>${esc(s.id)} · ${esc(s.survey)}</title></circle>`;}).join("");
  const svg=`<svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:${cap}px;background:#16242f;border:1px solid var(--line);border-radius:8px" role="img" aria-label="Member stations over Australia">${outline}${dots}</svg>`;
  const legend=`<div class="collscatter-legend">`+members.map(sv=>`<span class="csl-item"><span class="csl-dot" style="background:${col(sv)}"></span>${esc(sv)}</span>`).join("")+`</div>`;
  return `<div class="collscatter">${svg}${legend}</div>`;
}
function openCollectionPage(cid){
  const c=(typeof COLL!=="undefined"&&COLL?COLL[cid]:null);
  if(!c){toast("Collection details not available");return;}
  const members=c.surveys||[];
  const ss=ST.filter(s=>members.indexOf(s.survey)>=0);
  let pmin=Infinity,pmax=-Infinity,tip=0;
  ss.forEach(s=>{ if(s.pmin!=null)pmin=Math.min(pmin,s.pmin); if(s.pmax!=null)pmax=Math.max(pmax,s.pmax);
    if((s.comps||"").indexOf("T")>=0)tip++; });
  const ext=c.bbox?`${(c.bbox.east-c.bbox.west).toFixed(1)}° × ${(c.bbox.north-c.bbox.south).toFixed(1)}°`:"–";
  const stat=(lab,val)=>`<div class="cstat"><div class="cnum">${val}</div><div class="clab">${esc(lab)}</div></div>`;
  const rows=members.map(sv=>{const sub=ST.filter(s=>s.survey===sv),m=SMETA[sv]||{};
    const tc={};sub.forEach(s=>{if(s.type)tc[s.type]=(tc[s.type]||0)+1;});
    const pmn=Math.min(...sub.map(s=>s.pmin).filter(v=>v!=null)),pmx=Math.max(...sub.map(s=>s.pmax).filter(v=>v!=null));
    const types=Object.keys(tc).sort().map(t=>`${esc(t)} ${tc[t]}`).join(" · ")||"–";
    return `<tr><td><a href="#" data-act="story" data-survey="${escAttr(sv)}">${esc(sv)}</a><div class="csub">${esc(m.org||"–")}</div></td>`+
      `<td>${sub.length}</td><td>${types}</td><td>${isFinite(pmn)?fmtP(pmn)+"–"+fmtP(pmx)+"s":"–"}</td></tr>`;
  }).join("");
  const v=document.getElementById("collectionview");
  // Cleanup wave (E): a two-column HERO on wide screens; the abstract (+ the type/status/counts subline)
  // on the left, the fluid footprint scatter on the right; the stat tiles span full-width below; the member
  // table breathes to full width. The .collnote explainer is deleted (it duplicated the list-page intro,
  // itself deleted). Single column on narrow screens (index.html .collhero).
  v.innerHTML=
   `<div class="collpagenav"><button class="collback" data-act="collidx">← All collections</button>`+
   `<button class="collback collmapbtn" data-act="collmap" data-coll="${escAttr(cid)}">View all stations on main map</button></div>`+
   `<h1 class="colltitle">${esc(c.title||cid)}</h1>`+
   `<div class="collhero">`+
     `<div class="collhero-main">`+
       `<div class="collsub">${esc(c.type||"collection")}${c.status?" · "+esc(c.status):""} · ${c.n_surveys} survey${c.n_surveys===1?"":"s"} · ${c.n_stations} station${c.n_stations===1?"":"s"}${c.start_year?" · since "+esc(c.start_year):""}${c.last_updated?" · updated "+esc(c.last_updated):""}</div>`+
       (c.description?`<div class="colldesc">${esc(c.description)}</div>`:"")+
     `</div>`+
     (ss.length?`<div class="collhero-aside">${collScatter(ss,720)}</div>`:"")+
   `</div>`+
   `<div class="cstats">`+stat("surveys",c.n_surveys)+stat("stations",c.n_stations)+
     stat("period coverage",isFinite(pmin)?fmtP(pmin)+"–"+fmtP(pmax)+"s":"–")+stat("tipper stations",tip+" / "+ss.length)+stat("extent",ext)+`</div>`+
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
}
function dispatchProd(d){
  if(d.prod==="edi")fetchEdi(d.file,d.avail==="1",d.survey);
  else if(d.prod==="fetch"&&d.url){track("DownloadGenerated",{format:(d.name||"").split(".").pop()});downloadUrl(dataUrl(d.url),d.name);}
  else if(d.prod==="open"&&d.url)window.open(d.url,"_blank","noopener,noreferrer");
  else if(d.prod==="scroll"&&d.sel){const el=document.querySelector(d.sel);if(el){
    // UX6 Wave C: the scroll target (#pt_anchor) lives in the Response tab, with the phase tensor + induction
    // arrows now always-shown blocks — activate its tab so the scroll actually reveals it.
    const panel=el.closest?el.closest('[role="tabpanel"]'):null;
    if(panel&&panel.dataset&&panel.dataset.tab)selectDrawerTab(panel.dataset.tab);
    if(el.scrollIntoView)el.scrollIntoView({behavior:"smooth"});}}
  else if(d.prod==="toast")toast(d.msg);}
// UX6 Wave C: yield to an open plot-expand modal — its own Esc handler (plots.js) closes it, so the drawer
// must NOT also close underneath it. Otherwise Escape closes the drawer as before.
document.addEventListener("keydown",e=>{if(e.key==="Escape"){if(typeof document!=="undefined"&&document.getElementById&&document.getElementById("plotmodal"))return;closeDrawer();}});
// UX6 Wave C: ARIA tabs keyboard navigation (arrow keys / Home / End) with roving tabindex. Delegated on
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
  else if(act==="story"){e.preventDefault();openSurvey(sv);}
  else if(act==="collection"){e.preventDefault();location.hash="#/collection/"+encodeURIComponent(el.dataset.coll);}
  else if(act==="collidx"){e.preventDefault();if(location.hash.indexOf("#/collection/")===0)history.replaceState(null,"",location.pathname+location.search);setView("collections");}
  else if(act==="collmap"){e.preventDefault();if(typeof viewCollectionOnMap==="function")viewCollectionOnMap(el.dataset.coll);}   // E6: switch to map + fitBounds to the collection
  else if(act==="focus")focusSurvey(sv);
  else if(act==="select")selectSurvey(sv);
  else if(act==="doi"&&doi)window.open(escUrl("https://doi.org/"+doi),"_blank","noopener,noreferrer");   // NOT encodeURIComponent — it %2F-escapes the DOI slash -> doi.org 404; escUrl still blocks scheme injection
});

// UX6 Wave E (E3): discovery-controls wiring for the Surveys view. Static registrations — the controls
// live in index.html's #surveysview and exist at parse time (drawer.js loads after them). Each handler
// mutates this module's discovery state then re-renders the cards; the container listener on #facetChips
// survives its own innerHTML re-render (the container element is stable, only its children change).
(function(){
  const sortSel=document.getElementById("sortSel");
  if(sortSel&&sortSel.addEventListener)sortSel.addEventListener("change",()=>{_sortMode=sortSel.value||"name";renderCards();});
  const layoutSeg=document.getElementById("layoutSeg");
  if(layoutSeg&&layoutSeg.addEventListener)layoutSeg.addEventListener("click",e=>{const b=e.target.closest&&e.target.closest("button");if(!b||!b.dataset.layout)return;
    _cardLayout=b.dataset.layout;[...(layoutSeg.children||[])].forEach(x=>x.classList&&x.classList.toggle("on",x===b));renderCards();});
  const clearBtn=document.getElementById("clearFilters");
  if(clearBtn&&clearBtn.addEventListener)clearBtn.addEventListener("click",clearDiscoveryFilters);
  // Live surveys-view search (cleanup wave B): case-insensitive substring over name/org/region/blurb
  // (surveyMatchesSearch in filters.js reads this input). Live-updates the grid + #surveyCount and the
  // header #nVis count.
  const search=document.getElementById("surveySearch");
  if(search&&search.addEventListener)search.addEventListener("input",()=>{renderCards();if(typeof updateCounts==="function")updateCounts();});
  const fc=document.getElementById("facetChips");
  if(fc&&fc.addEventListener)fc.addEventListener("click",e=>{
    const lf=e.target.closest&&e.target.closest("[data-facet]");
    if(lf){const k=lf.dataset.facet;if(k in _facets){_facets[k]=!_facets[k];renderCards();}return;}
    const tf=e.target.closest&&e.target.closest("[data-type-facet]");
    if(tf){const t=tf.dataset.typeFacet;if(_typeFacets.has(t))_typeFacets.delete(t);else _typeFacets.add(t);renderCards();}});
})();
