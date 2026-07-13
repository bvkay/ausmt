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
  const t=drawer.querySelector(".close")||drawer;if(t&&t.focus){try{t.focus();}catch(e){}}}
function _restoreDrawerFocus(){const f=_drawerReturnFocus;_drawerReturnFocus=null;if(f&&f.focus){try{f.focus();}catch(e){}}}
// UX6 Wave C: the currently-open station's TF row, stashed so the delegated [data-act="expand"] handler
// can re-render the SAME plotter into the expand modal without re-deriving it from the DOM.
let _curTf=null;
// UX6 Wave C (C2): a small section-role chip using the engine README taxonomy — "Source data",
// "Automated screening", "AusMT-derived". Plain muted text, no colour semantics.
function roleChip(l){return `<span class="rolechip">${esc(l)}</span>`;}
// UX6 Wave C (C1): one tab panel. ALL panels render in the DOM at openStation time; selectDrawerTab
// toggles them via the `hidden` attribute + aria-selected, so the pinned innerHTML/text assertions keep
// matching against the same rendered strings regardless of which tab is active.
function drawerPanel(id,content,selected){
  return `<div class="dpanel" id="dp-${id}" role="tabpanel" data-tab="${id}" aria-labelledby="dt-${id}" tabindex="0"${selected?"":" hidden"}>${content}</div>`;}
// Activate one drawer tab (ARIA roving-tabindex + hidden toggle). Degrades to a no-op under the smoke
// harness (stubbed drawer with querySelectorAll()->[]). Falls back to the first tab for an unknown name.
function selectDrawerTab(name){
  if(!drawer||!drawer.querySelectorAll)return;
  const tabs=[...drawer.querySelectorAll('[role="tab"]')];
  const panels=[...drawer.querySelectorAll('[role="tabpanel"]')];
  if(!tabs.length)return;
  if(!tabs.some(tb=>tb.dataset.tab===name))name=tabs[0].dataset.tab;
  tabs.forEach(tb=>{const on=tb.dataset.tab===name;tb.setAttribute("aria-selected",on?"true":"false");tb.tabIndex=on?0:-1;if(tb.classList)tb.classList.toggle("on",on);});
  panels.forEach(p=>{p.hidden=(p.dataset.tab!==name);});
}
// C1b gate, factored: the served-EDI descriptor for a station — {sub,st,d}. When the access gate REFUSES
// (a non-open survey with no served EDI artifact) d is null, so neither the header Download action, the
// Overview primary-download tile, nor the Files "Transfer function" tile offers a download affordance —
// they say "embargoed"/"metadata only" instead. An OPEN survey keeps today's exact tile text (byte-for-
// byte), including the "EDI (via source archive)" fallback that the C1b pins assert is ABSENT when embargoed.
function ediDescriptor(s,m){
  const arts=(typeof artifactsFor==="function"?artifactsFor(s.ausmt_id):[]);
  const ediArt=arts.find(a=>a.format==="edi");
  if(ediArt) return {sub:"EDI (download)"+(ediArt.size?" · "+fmtBytes(ediArt.size):""),st:"ok",d:{prod:"fetch",url:ediArt.url,name:ediArt.url.split("/").pop()}};
  if(!isOpenAccess(m)) return {sub:accessLevelOf(m)==="metadata_only"?"metadata only":"embargoed",st:"no",d:null};
  return {sub:s.ediAvail?"EDI (download)":"EDI (via source archive)",st:s.ediAvail?"ok":"unk",d:{prod:"edi",file:s.file,avail:s.ediAvail?"1":"0",survey:s.survey}};
}
// C1b: the sticky-header Download EDI action. Renders NOTHING where the gate refuses (no download
// affordance for an embargoed/metadata-only station) — otherwise a primary button routed through the
// same [data-prod] dispatch as the product tiles.
function headerDownloadBtn(s,m){const e=ediDescriptor(s,m);if(!e.d)return"";
  const attrs=Object.entries(e.d).map(([k,v])=>`data-${k}="${escAttr(v)}"`).join(" ");
  return `<button class="primary dl-edi" ${attrs}>Download EDI</button>`;}
// Overview "primary download" tile — the same gated descriptor rendered as a single product tile (disabled
// where the gate refuses, so it states the embargo rather than offering bytes).
function overviewDownload(s,m){const e=ediDescriptor(s,m);
  const attrs=e.d?Object.entries(e.d).map(([k,v])=>`data-${k}="${escAttr(v)}"`).join(" "):"";
  const st=e.st==="ok"?"ok":e.st==="part"?"part":e.st==="no"?"no":"unk";
  return `<div class="prodgrid"><div class="prod ${e.d?"":"dis"}" ${attrs}><span class="pdot" style="background:var(--${st})"></span><div>Transfer function<small>${esc(e.sub)}</small></div></div></div>`;}

function apa(m,doi){return `${esc(m.au)} (${esc(m.yr||"n.d.")}). ${esc(m.ti)}${m.ve?" ("+esc(m.ve)+")":""} [Data set]. ${esc(m.pb)}.`+(doi?` https://doi.org/${esc(doi)}`:"");}
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
// C46-W3b: the survey-level attribution line — the custodian's verbatim attribution.statement when
// declared, else the org(year) synthesis. MIRRORS exports.attributionLine byte-for-byte so the drawer, the
// station Cite tab, the exported CSV and the citation pack all render the SAME attribution string.
function attributionText(m){m=m||{};
  const st=((m.attribution||{}).statement||"").toString().trim();
  if(st)return st;
  const who=((m.cite&&m.cite.au)||m.org||"").toString().trim();
  const yr=(m.dates?(String(m.dates).match(/\d{4}/g)||[]).slice(-1)[0]:"")||"";
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
// absent/legacy) => served, curves present. Anything else (embargoed | metadata_only | an unknown value)
// => NON-OPEN: the engine emits EMPTY tf series for these stations (the response curves ARE the embargoed
// data), so the drawer must render an ACCESS PANEL in place of the four plots rather than four blank frames.
function accessLevelOf(m){return (m&&m.access)?String(m.access):"open";}
function isOpenAccess(m){return accessLevelOf(m)==="open";}
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
    body="This survey is listed metadata-only. "+stance+"; transfer functions are available from the custodian — see the survey's contact and identifiers.";
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
function maturityModel(m,sc){m=m||{};sc=sc||[];
  const dims=[
    {key:"curated",label:"Curated archive",achieved:true,note:""},
    {key:"repro",label:"Reproducible",achieved:!!(sc[SC.sw]&&m.ts==="ok"),note:""},
    {key:"licence",label:"Licence verified",achieved:licBadgeState(m.lic)!=="unk",note:""},
    {key:"doi",label:"DOI",achieved:!!m.doi,note:m.doi?"minted":"not recorded"},
    {key:"ts",label:"Time series",achieved:m.ts==="ok",note:m.ts==="ok"?"linked":"not available"},
  ];
  return {dims,stars:dims.filter(d=>d.achieved).length,total:dims.length};}
function maturityBlock(s){const m=SMETA[s.survey]||{},sc=SCI[s.i]||[];const mod=maturityModel(m,sc);
  const stars="★".repeat(mod.stars)+"☆".repeat(mod.total-mod.stars);
  const rows=mod.dims.map(d=>`<li class="matdim ${d.achieved?"on":"off"}"><span class="matglyph">${d.achieved?"★":"☆"}</span><span>${esc(d.label)}${d.note?": "+esc(d.note):""}</span></li>`).join("");
  return `<div class="matblock"><div class="mat-h">Dataset maturity <span class="mat-stars" title="${mod.stars} of ${mod.total} stewardship dimensions achieved">${stars}</span></div>`+
    `<div class="mat-sub">Record-stewardship maturity — how completely this record is archived, licensed and reproducible. Not a measure of scientific quality.</div>`+
    `<ul class="matdims">${rows}</ul></div>`;}
// C7: the raw-TS pointer. A survey's OWN time_series.collection_pid (SMETA.ts_pid) is authoritative
// when declared; TS_COLLECTION (the AusLAMP/NCI collection DOI) is only the DEPLOYMENT-WIDE default for
// surveys that genuinely belong to that shared collection and declare no PID of their own — never a
// stand-in for a survey's dataset DOI (see tsUrlFor's caller sites vs. fetchEdi/exports.js source-citation).
function tsPidRaw(m){return (m&&m.ts_pid)||TS_COLLECTION.doi;}
function tsUrlFor(m){return "https://doi.org/"+tsPidRaw(m);}
function relatedProducts(s){const m=SMETA[s.survey]||{};
  const tsDoi=tsUrlFor(m);
  // EDI + EMTF XML: real downloads driven by the manifest (which carries the authoritative, slug-
  // namespaced url + size). Fall back to the legacy flat-path EDI fetch / pipeline note for data sets
  // built before the manifest (or non-redistributable surveys, which aren't served).
  const arts=(typeof artifactsFor==="function"?artifactsFor(s.ausmt_id):[]);
  const xml=arts.find(a=>a.format==="emtfxml");
  // C1b: a non-open survey has no served TF here (bytes withheld by the C1 gate, curves withheld by C1b),
  // so the TF tile must NOT offer the "via source archive" EDI fetch — it says "embargoed"/"metadata only"
  // (no action) instead, matching the access panel that replaced the plots above. Shared gate logic lives
  // in ediDescriptor (also feeds the sticky-header Download action + the Overview primary-download tile).
  const ediTile={n:"Transfer function",...ediDescriptor(s,m)};
  const xmlTile=xml
    ? {n:"EMTF XML",sub:"download"+(xml.size?" · "+fmtBytes(xml.size):""),st:"ok",d:{prod:"fetch",url:xml.url,name:xml.url.split("/").pop()}}
    : {n:"EMTF XML",sub:"via pipeline",st:"part",d:{prod:"toast",msg:"EMTF XML is produced in the build pipeline (mt_metadata); served on the hosted site for redistributable surveys."}};
  const items=[
   ediTile,
   xmlTile,
   {n:"MTH5",sub:m.mth5==="ok"?"available":m.mth5==="part"?"partial":"product not currently available (not located in source archives)",st:m.mth5||"unk",d:m.mth5==="no"?null:{prod:"open",url:tsDoi}},
   {n:"Raw time series",sub:m.ts==="ok"?"NCI THREDDS":"not located in source archives",st:m.ts||"unk",d:m.ts==="ok"?{prod:"open",url:tsDoi}:null},
   {n:"Phase tensor",sub:"computed",st:"ok",d:{prod:"scroll",sel:"#pt_anchor"}},
   {n:"Publication",sub:m.doi?"DOI":"none recorded",st:m.doi?"ok":"no",d:m.doi?{prod:"open",url:"https://doi.org/"+m.doi}:null}
  ];
  const attrs=d=>d?Object.entries(d).map(([k,v])=>`data-${k}="${escAttr(v)}"`).join(" "):"";
  return `<div class="prodgrid">`+items.map(it=>`<div class="prod ${it.d?"":"dis"}" ${attrs(it.d)}><span class="pdot" style="background:var(--${it.st==="ok"?"ok":it.st==="part"?"part":it.st==="no"?"no":"unk"})"></span><div>${esc(it.n)}<small>${esc(it.sub)}</small></div></div>`).join("")+`</div>`;}
function provGraph(s){const m=SMETA[s.survey]||{},sc=SCI[s.i]||[];
  const nodes=[];
  // C46-W3b: an upstream "source dataset" node when the survey declares sources[] — the lineage's origin,
  // above the raw time series. Shows the first source's title + identifier link (with a "+N more" tail).
  const srcs=(m.sources||[]);
  if(srcs.length){const s0=srcs[0]||{};const idv=(s0.identifier||"").toString().trim();
    const lbl=esc((s0.title||"source dataset").toString().trim())+(srcs.length>1?` <span class="prov">(+${srcs.length-1} more)</span>`:"");
    nodes.push(["Source dataset",idv?`${lbl} · ${pidLink(idv)}`:lbl]);}
  nodes.push(
   ["Raw time series",m.ts==="ok"?`<a href="${escUrl(tsUrlFor(m))}" target="_blank" rel="noopener noreferrer">${m.ts_pid?"survey collection":"NCI collection"}</a>`:"not located in source archives"],
   ["Processing software",sc[SC.sw]?esc(sc[SC.sw]):"not stated in EDI"],
   ["Method",sc[SC.alg]?esc(sc[SC.alg]):(sc[SC.rr]?"remote reference (stated)":"not stated")],
   ["Transfer function",`${s.nper} periods · ${esc(s.comps.split("").join("+"))||"–"}`],
   ["Distributed formats",`EDI ✓ · EMTF XML (pipeline)${m.mth5==="ok"?" · MTH5 ✓":""}`],
   ["Publication",m.doi?`<a href="${escUrl("https://doi.org/"+m.doi)}" target="_blank" rel="noopener noreferrer">doi:${esc(m.doi)}</a>`:"none recorded"]
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
    ["screening parameters", params],
    ["build date (UTC)", esc(P.generated?P.generated.replace("T"," ").slice(0,19):"n/a")],
    ["Build commit", P.git_commit?`<code>${esc(P.git_commit)}</code>`:"<span class='prov'>unavailable</span>"]
  ];
  return `<details class="prov-d"><summary>Processing provenance</summary><table class="meta">`+
    rows.map(([k,v])=>`<tr><td>${esc(k)}</td><td>${v}</td></tr>`).join("")+
    `</table><div class="prov" style="margin-top:6px">Every product traces to its input file, the extractor and version, and the screening parameters above — reproducible offline by <i>AusMT</i>.</div></details>`;
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
  if(hasAngle) parts.push("Impedances served in the source's declared "+fmt(az)+" acquisition frame (as stored — not rotated to geographic north).");
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
function loadStationFrameLine(s){
  const slug=s.slug||((SMETA[s.survey]||{}).slug);
  if(!slug||!s.id) return Promise.resolve();              // cannot locate station.json — skip
  const url=dataUrl("products/"+encodeURIComponent(slug)+"/"+encodeURIComponent(s.id)+"/station.json");
  return fetch(url).then(r=>r.ok?r.json():null).then(doc=>{
    if(!doc||!doc.frame) return;
    const txt=frameLineText(doc.frame);
    if(!txt) return;
    const el=document.getElementById("frameline");
    if(el&&el.dataset.ausmt===s.ausmt_id){                // guard: drawer may have moved on (async)
      el.textContent=txt;
      el.style.cssText="font-size:12px;color:var(--muted);margin:2px 0 10px;line-height:1.4";
    }
  }).catch(()=>{});                                       // withheld / offline / file:// => no line
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
//   d.p3d,pctThr % periods breaching the 3-D |β| screen vs PROV threshold  -> Phase tensor consistency  green<=thr amber<=2*thr
//   d.phaseSplit median |φxy − φyx| separation (deg)       -> Phase split           green<=15 amber<=35
//   d.decades    period band width in decades              -> Coverage              green>=4  amber>=2
function screeningIndicators(d){
  d=d||{};
  const na={state:"na",word:"not evaluated"};
  const band=(v,g,a,gw,aw,rw)=>v==null?na:(v>=g?{state:"green",word:gw}:v>=a?{state:"amber",word:aw}:{state:"red",word:rw});
  const smooth=band(d.q,4,3,"Clean","Fair","Rough");
  const strike=(d.azN==null||d.azN<3||d.azR==null)?na:band(d.azR,0.9,0.75,"Stable","Variable","Unstable");
  let pt;
  if(d.p3d==null)pt=na;
  else{const thr=(d.pctThr!=null&&isFinite(d.pctThr))?d.pctThr:30;
    pt=d.p3d<=thr?{state:"green",word:"Consistent"}:d.p3d<=2*thr?{state:"amber",word:"Mixed"}:{state:"red",word:"Complex"};}
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
function _indWord(st){return st==="green"?"Green":st==="amber"?"Amber":st==="red"?"Red":"—";}
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
  const mre=sc[SC.mre];
  const station=_ssGroup("Station",[["coordinates",coordCellHtml(s)]],overviewDownload(s,m));
  const tf=_ssGroup("Transfer function",[
    ["periods",`${fmtP(s.pmin)}–${fmtP(s.pmax)} s`],
    ["components",(esc(s.comps.split("").join(" + "))||"–")],
    ["tipper",s.comps.includes("T")?"yes":"no"],
    ["remote reference",sc[SC.rr]?"yes":"not recorded"]]);
  const checks=_ssGroup(DATA_CHECKS_LABEL,[
    ["completeness",sc[SC.q]!=null?`<b style="color:${qColor(sc[SC.q])}">${sc[SC.q].toFixed(1)}/5</b> <span class="prov">(shape/coverage screen — not a verdict)</span>`:"n/a"],
    ["TF error",mre!=null?Math.round(mre*100)+"%":"n/a"]]);
  const proc=_ssGroup("Processing",[
    ["software",sc[SC.sw]?esc(sc[SC.sw]):"not stated in EDI"],
    ["source",esc(s.file)]]);
  return `<details class="prov-d ssdetails"><summary>Station summary</summary><div class="prov-dbody ssbody">${station}${tf}${checks}${proc}</div></details>`;
}
function openStation(i){
  _rememberDrawerOpener();                            // E7: capture the invoking element before the rewrite
  const s=ST[i],t=TFD[i]||[[]],m=SMETA[s.survey]||{},sc=SCI[i]||[];
  // UX3 item 7a: sc[SC.dim] (dimensionality) is no longer surfaced in the drawer screening grid — it's
  // inferable from the phase tensor + skew, which stay shown (strike/|β|/3-D-periods line below). The
  // sc.json field itself is unchanged (data products are display-only edits); the map's colour-by-dim
  // mode still reads s.dim. So `dim` is intentionally not destructured here anymore.
  const p3d=sc[SC.p3d],gd=sc[SC.gd],skew=sc[SC.skew],dec=sc[SC.decades];
  location.hash="#/station/"+encodeURIComponent(s.ausmt_id);   // ausmt_id is globally unique; s.id (DATAID) repeats across surveys
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
  const _inds=screeningIndicators({q:sc[SC.q],azR:_azR,azN:azs.length,p3d,pctThr:_bp.pct_periods_3d_threshold,phaseSplit:_phaseSplit,decades:dec});
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
  const TABS=[["response","Response"],["screening","Screening"],["files","Files"],["provenance","Provenance"],["cite","Cite"]];
  const tabStrip=`<div class="seg dtabs" role="tablist" aria-label="Station detail sections">`+
    TABS.map(([id,label],k)=>`<button role="tab" id="dt-${id}" data-act="tab" data-tab="${id}" aria-controls="dp-${id}" aria-selected="${k===0}" tabindex="${k===0?0:-1}"${k===0?' class="on"':""}>${esc(label)}</button>`).join("")+`</div>`;
  const header=`<div class="dtop">`+
    `<div class="dhead"><span class="sid">${esc(s.id)}</span>${typeChip}${collChip}<button class="close" aria-label="Close">✕</button></div>`+
    `<div class="dsub">${esc(s.survey)} · ${esc(s.org)} · ${esc(s.country)}</div>`+
    collLine(m)+
    `<div class="dchips">${yearChip}${licBadge}</div>`+
    `<div class="dactions">${headerDownloadBtn(s,m)}<button class="dl-cite" data-act="tab" data-tab="cite">Cite</button></div>`+
    tabStrip+`</div>`;
  // ---- Panel content -------------------------------------------------------------------------------
  // Response (default) — the four plots FIRST (the centerpiece; rho + phase expanded, phase tensor +
  // induction arrows collapsed), then the collapsible "Station summary" (the owner's four-group layout,
  // stationSummaryDetails) which absorbs the former Overview facts. C1b: a non-open station shows the
  // access panel here INSTEAD of the plots (curves ARE the withheld data). #pt_anchor is kept so the
  // "Phase tensor" related-product scroll target never dangles; the frame line is populated lazily.
  const responseHtml=`<div class="sechead">Response functions ${roleChip("AusMT-derived")}</div>`+
    (isOpenAccess(m)
      ? plotBlock("rho",t)+plotBlock("phase",t)+`<div id="pt_anchor"></div>`+plotCollapsible("pt",t,false)+plotCollapsible("arrow",t,false)
      : accessPanel(m,s.survey)+`<div id="pt_anchor"></div>`)+
    `<div id="frameline" data-ausmt="${escAttr(s.ausmt_id)}"></div>`+
    stationSummaryDetails(s,m,sc);
  // Screening (X5) — a five-row indicator list (glyph + label + Green/Amber/Red state word + descriptive
  // word; never colour alone; a not-computable check is neutral grey "not evaluated"), then a "Show
  // details" expander preserving the full automated screening prose (strike + median |β| lines, the
  // galvanic flag, and the completeness/smoothness check with its not-a-verdict framing — UX3-7a fence).
  const screeningHtml=`<div class="sechead">Screening indicators ${roleChip("Automated screening")} <span style="text-transform:none;letter-spacing:0">· not interpretation products</span></div>`+
    screeningIndicatorList(_inds)+
    `<details class="prov-d"><summary>Show details</summary><div class="prov-dbody">`+
    `<div class="dim">Automated screening estimate — ${strikeClause}${skew!=null?` · median |β| <b>${skew}°</b> · <b>${p3d}%</b> of evaluated periods exceeded the |β|${_betaThr!=null?` &gt; ${esc(String(_betaThr))}°`:""} screening threshold`:""}. Not a structural interpretation.<br>`+
    `${gd?"⚠ <b>Galvanic/static-shift</b> signature detected (ρ modes offset by a near-constant factor with coincident phases). ":""}`+
    `<span style="color:var(--muted)">Automated completeness/smoothness check: ${sc[SC.q]!=null?`<b style="color:${qColor(sc[SC.q])}">${sc[SC.q].toFixed(1)}/5</b> — ${sc[SC.qb]==="e"?"median error + coverage + smoothness":"shape-based; no error bars in EDI"}; <i>not a quality or geological-value judgement</i>`:"n/a"}.</span></div>`+
    `</div></details>`;
  // Files — related products (incl. advanced-analysis placeholder), the AusMT-derived deliverables.
  const filesHtml=`<div class="sechead">Related products ${roleChip("AusMT-derived")}</div>`+relatedProducts(s)+
    `<div class="sechead">Advanced analysis <span style="text-transform:none;letter-spacing:0">· Tier 3, generated offline</span></div>`+
    `<div class="dim">McNeice–Jones / Groom–Bailey decomposition, distortion parameters and Lilley Mohr circles are planned <i>AusMT</i> pipeline products; they will appear here once produced. <span style="color:var(--muted)">Not computed in the browser.</span></div>`;
  // Provenance (X6/X7/X8) — three source-data rows visible (processing software · transfer function
  // source file+sha · source archive), then the Dataset-maturity block (X7 stars), then EVERYTHING ELSE
  // (lineage graph, full provenance table, identifiers, format availability, record metadata, API)
  // behind collapsed <details>. Nothing deleted — only demoted. The API box (X8) is the last, small expander.
  const _srcArchive=m.doi
    ? `<a href="${escUrl("https://doi.org/"+m.doi)}" target="_blank" rel="noopener noreferrer">doi:${esc(m.doi)}</a>`
    : (m.ts==="ok"?`<a href="${escUrl(tsUrlFor(m))}" target="_blank" rel="noopener noreferrer">${m.ts_pid?"survey collection":"NCI collection"}</a>`:"<span class='prov'>not recorded</span>");
  const provTop=`<table class="meta prov-top">`+
    `<tr><td>Processing software</td><td>${sc[SC.sw]?esc(sc[SC.sw]):"not stated in EDI"}</td></tr>`+
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
  // X8: the Metadata & API box collapses to a single small "API" expander at the tab's foot (Wave A's
  // honest "planned" link text kept inside).
  const apiBlock=`<div class="api">Read API (planned) — static JSON on the hosted site:<br>GET <b>/api/station/${esc(s.ausmt_id)}.json</b><br>GET <b>/api/survey/${esc(s.slug||s.survey.toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/-$/,""))}.json</b><br>GET <b>/api/station/${esc(s.ausmt_id)}/edi</b></div>`;
  const provenanceHtml=`<div class="sechead">Provenance ${roleChip("Source data")}</div>`+provTop+maturityBlock(s)+
    `<details class="prov-d"><summary>Lineage graph</summary><div class="prov-dbody">${provGraph(s)}</div></details>`+
    provenanceBox(s)+
    `<details class="prov-d"><summary>Identifiers &amp; instruments</summary><div class="prov-dbody">${identifiersHtml(m)}</div></details>`+
    `<details class="prov-d"><summary>Format availability</summary><div class="prov-dbody"><div class="badges">${badge("EDI","ok")}${badge("time series",m.ts||"unk")}${badge("MTH5",m.mth5||"unk")}${badge("DOI",m.doi?"ok":"no")}${licBadge}${s.fixed?badge("coord QC","part","Coordinates were flagged during QC — see this station's provenance and treat with caution."):""}</div></div></details>`+
    `<details class="prov-d"><summary>Record metadata</summary><div class="prov-dbody">${metaTable}</div></details>`+
    `<details class="prov-d"><summary>API</summary><div class="prov-dbody">${apiBlock}</div></details>`;
  // Cite — the citation box. C46-W3b: a no-cite survey is EXPLICIT ("custodian citation not recorded — cite
  // the survey package") rather than a silent AUSMT_SELF masquerade, and the captured attribution statement
  // (verbatim, else org(year) synthesis) renders alongside. The copy buttons keep their assembly helpers.
  const _attn=attributionText(m);
  const citeBody=m.cite
    ? apa(m.cite,m.doi)
    : `<div class="prov" style="margin-bottom:6px">Custodian citation not recorded — cite the survey package:</div>${apa(AUSMT_SELF,m.doi)}`;
  const citeHtml=`<div class="sechead">Cite this station's source</div><div class="citebox">${citeBody}`+
    (_attn?`<div class="attn"><b>Attribution:</b> ${esc(_attn)}</div>`:"")+
    `<div class="cb-row"><button data-cite="apa" data-survey="${escAttr(s.survey)}">APA</button>`+
    `<button data-cite="bibtex" data-survey="${escAttr(s.survey)}" data-key="${escAttr(keysafe)}">BibTeX</button>`+
    `<button data-cite="ris" data-survey="${escAttr(s.survey)}">RIS</button></div></div>`;
  drawer.innerHTML=header+
    drawerPanel("response",responseHtml,true)+
    drawerPanel("screening",screeningHtml,false)+
    drawerPanel("files",filesHtml,false)+
    drawerPanel("provenance",provenanceHtml,false)+
    drawerPanel("cite",citeHtml,false);
  _curTf=t;                                        // stash for the expand-modal handler
  drawer.setAttribute("aria-label","Station "+s.id+" details");   // E7: refine the dialog label per subject
  drawer.classList.add("open");drawer.scrollTop=0;
  selectDrawerTab("response");                     // UX8 (X4): Response default-selected
  _focusDrawer();                                  // E7: move focus into the dialog
  if(isOpenAccess(m)) loadStationFrameLine(s);     // C25-V3: inject the frame line if this station declares one
}
function closeDrawer(){const wasOpen=drawer.classList.contains&&drawer.classList.contains("open");
  drawer.classList.remove("open");if(location.hash.startsWith("#/station"))history.replaceState(null,"",location.pathname+location.search);
  if(wasOpen)_restoreDrawerFocus();}               // E7: return focus to the invoking element (only if it was open)
async function fetchEdi(file,avail,survey){
  // C7: this EDI isn't redistributable here. Its dataset DOI (m.doi), when the survey has one, is the
  // TF source archive and is safe to open. There is NO honest substitute when no dataset DOI is
  // recorded — TS_COLLECTION is the raw TIME-SERIES collection, not a transfer-function source archive,
  // and silently opening it mislabels a different dataset as "the source archive" (the pre-C7 defect).
  if(!avail){const m=SMETA[survey]||{};
    if(m.doi){toast("This EDI isn't redistributable here — opening the source archive.");
      window.open("https://doi.org/"+m.doi,"_blank","noopener,noreferrer");}
    else toast("This EDI isn't redistributable here, and no dataset DOI is recorded — contact the custodian organisation ("+(m.org||"unknown")+").");
    return;}
  // Route through dataUrl() (honours data_base_url) — NOT a hardcoded "data/edi/" path, so the
  // portal and its data can live in separate repos / on NCI.
  return downloadUrl(dataUrl("edi/"+file),file);}
// Generic blob download for a resolved manifest URL (EMTF XML, per-survey bundles, EDI fallback).
async function downloadUrl(url,filename){
  try{const r=await fetch(url);if(!r.ok)throw 0;const b=await r.blob();
    const a=document.createElement("a");a.href=URL.createObjectURL(b);a.download=filename||url.split("/").pop();a.click();URL.revokeObjectURL(a.href);}
  catch(e){toast("Download works when served over HTTP next to the data files; can't fetch over file://.");}}
function copyTxt(t){navigator.clipboard?.writeText(t).then(()=>toast("Copied.")).catch(()=>toast("Copy failed — select manually."));}

// UX3 item 6: the survey card description comes from the survey.yaml abstract, which the engine already
// carries into SMETA as m.blurb (build_portal.py). Render the escaped abstract when present and non-empty;
// otherwise an HONEST muted single line — no fabricated marketing copy (the old hardcoded placeholder
// implied content that wasn't there). esc() makes a hostile abstract (e.g. <img onerror=…>) render inert.
function cardDesc(m){
  const blurb=(m&&typeof m.blurb==="string")?m.blurb.trim():"";
  return blurb
    ? `<div class="desc">${esc(blurb)}</div>`
    : `<div class="desc desc-empty">No survey description provided — add an <code>abstract</code> to survey.yaml.</div>`;
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
  return `<div class="scard"><div class="scardhead"><h3 style="cursor:pointer" data-act="story" data-survey="${escAttr(sv)}" title="Open survey">${esc(sv)}</h3>`+(m.collection&&m.collection.id?`<span class="chip collchip" data-act="collection" data-coll="${escAttr(m.collection.id)}" title="Explore collection">${esc(m.collection.title||m.collection.id)}</span>`:"")+`</div><div class="cust">${esc(m.org||"custodian unknown")} · ${esc(m.country||"")}</div>`+
   `<div class="mixbar">${mixbar}</div>`+
   `<div class="stats"><b>${ss.length}</b> station${ss.length===1?"":"s"}${yearTxt?` · acquired <b>${yearTxt}</b>`:""}<br>periods <b>${fmtP(pmin)}–${fmtP(pmax)}s</b></div>`+
   `<div class="badges">${badge(m.lic||"licence ?",licBadgeState(m.lic))}${badge("DOI",m.doi?"ok":"no")}</div>`+
   cardDesc(m)+
   `<div class="cardbtns"><button data-act="story" data-survey="${escAttr(sv)}">View survey</button><button data-act="select" data-survey="${escAttr(sv)}">Download</button></div></div>`;}
function pidLink(p){if(!p)return "<span class='prov'>not recorded</span>";if(p.startsWith("TODO"))return "<span class='prov'>not recorded</span>";
  const href=p.startsWith("http")?p:(p.startsWith("10.")?"https://doi.org/"+p:"https://hdl.handle.net/"+p);return `<a href="${escUrl(href)}" target="_blank" rel="noopener noreferrer">${esc(p)}</a>`;}
// C7: SMETA.investigators is [{name, orcid}, ...] (ORCID solicited by the schema, previously discarded).
// Each name renders with a small ORCID icon-link when present; tolerates the legacy bare-string shape
// (a plain name, no ORCID) so old/hand-built surveys.json still renders instead of crashing.
function orcidLink(o){if(!o)return "";const href="https://orcid.org/"+o;
  return ` <a href="${escUrl(href)}" target="_blank" rel="noopener noreferrer" title="ORCID: ${escAttr(o)}" class="orcid-ico">◉</a>`;}
function investigatorsHtml(invs){
  const list=(invs||[]);
  if(!list.length)return "–";
  return list.map(i=>typeof i==="string"?esc(i):esc(i.name||"–")+orcidLink(i.orcid)).join(", ");}
// C7: a ROR value may be a bare id (00892tw58) or a full https://ror.org/... URL — resolve either to
// the canonical ror.org landing page link.
function rorLink(r){if(!r)return null;const href=r.startsWith("http")?r:"https://ror.org/"+r;return `<a href="${escUrl(href)}" target="_blank" rel="noopener noreferrer">${esc(r)}</a>`;}
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
  const rows=list.map(i=>{const label=[i.manufacturer,i.model].filter(Boolean).map(esc).join(" ")||"instrument";
    const link=instrumentPidLink(i.pid);
    return link?`${label} — ${link}`:`${label} <span class='prov'>(no PID)</span>`;}).join("<br>");
  return `Instrument PIDs:<br><span class="pidline">${rows}</span><br>`;}
function identifiersHtml(m){
  const fund=(m.funders||[]);
  const fundLine=fund.length?fund.map(f=>f.pid?`<a href="${escUrl(f.pid)}" target="_blank" rel="noopener noreferrer">${esc(f.name)}</a>`:`${esc(f.name)} <span class='prov'>(no PID)</span>`).join(" · "):"<span class='prov'>none recorded</span>";
  const ror=rorLink(m.org_ror);
  const raid=raidLink(m.raid);
  return `<div class="surveymeta"><b>Persistent identifiers &amp; instruments</b><br>`+
    `Survey PID: <span class="pidline">${pidLink(m.pid)}</span><br>`+
    `Dataset DOI: <span class="pidline">${m.doi?pidLink(m.doi):"<span class='prov'>not recorded</span>"}</span><br>`+
    `Organisation ROR: <span class="pidline">${ror||"<span class='prov'>not recorded</span>"}</span><br>`+
    `Project RAiD: <span class="pidline">${raid||"<span class='prov'>not recorded</span>"}</span><br>`+
    `Instrument model: ${m.instrument_model?esc(m.instrument_model):"<span class='prov'>not recorded in source metadata</span>"}<br>`+
    instrumentPidsHtml(m)+
    `Funders: ${fundLine}</div>`;}
function pubCite(p){return `${esc(p.a)} (${esc(p.y)}). ${esc(p.t)}. <i>${esc(p.j)}</i>.`+(p.doi?` <a href="${escUrl("https://doi.org/"+p.doi)}" target="_blank" rel="noopener noreferrer">doi:${esc(p.doi)}</a>`:"");}
function pubsHtml(m){const ps=(m.pubs||[]);
  if(!ps.length)return `<div class="surveymeta"><span class='prov'>No related publications recorded yet — the science pipeline can auto-suggest these from DOIs that cite the dataset.</span></div>`;
  return `<div class="surveymeta">`+ps.map(p=>"• "+pubCite(p)).join("<br><br>")+`</div>`;}
// UX6 Wave E (E3): discovery controls for the Surveys view. State lives in this module (the controls are
// static in index.html; the coordinator/rail filters are untouched). FORBIDDEN by contract: sorting or
// faceting by the automated completeness/smoothness check — the screen must never become a ranking, so
// none of the sort modes or facets below reference s.q / the check.
let _sortMode="name",_cardLayout="cards";
const _facets={lic:false,doi:false,tipper:false};   // boolean presence facets, AND-combined when active
function _stationCount(sv){return ST.filter(s=>s.survey===sv).length;}
function _surveyHasTipper(sv){return ST.some(s=>s.survey===sv&&(s.comps||"").includes("T"));}
function _yearKey(m){return m.year_start!=null?m.year_start:(m.year_end!=null?m.year_end:-Infinity);}
function surveyPassesFacets(sv){const m=SMETA[sv]||{};
  if(_facets.lic&&!licIsOpen(m.lic))return false;   // "Open licence": an openly-licensed (redistributable) id per the canon tables
  if(_facets.doi&&!m.doi)return false;
  if(_facets.tipper&&!_surveyHasTipper(sv))return false;
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
    `<span class="srow-org">${esc(m.org||"—")}</span>`+
    `<span class="srow-year">${yearTxt||"—"}</span>`+
    `<span class="srow-stn">${ss.length} station${ss.length===1?"":"s"}</span>`+
    `<span class="srow-lic">${badge(m.lic||"licence ?",licBadgeState(m.lic))}</span></div>`;}
function renderDiscovery(n){
  const cnt=document.getElementById("surveyCount");
  if(cnt)cnt.textContent=n+" survey"+(n===1?"":"s");
  const fc=document.getElementById("facetChips");
  if(fc)fc.innerHTML=[["lic","Open licence"],["doi","Has DOI"],["tipper","Has tipper"]]
    .map(([k,l])=>`<button type="button" class="facet${_facets[k]?" on":""}" data-facet="${k}" aria-pressed="${_facets[k]?"true":"false"}">${l}</button>`).join("");}
function renderCards(){
  const vis=sortSurveys(surveys.filter(surveyVisible).filter(surveyPassesFacets));
  const grid=document.getElementById("cardGrid");
  if(grid)grid.className=_cardLayout==="compact"?"cardlist":"cardgrid";
  if(grid)grid.innerHTML = vis.length
    ? (_cardLayout==="compact"?vis.map(surveyRow).join(""):vis.map(surveyCard).join(""))
    : `<div class="emptynote">No surveys match the current filters. Loosen the data-type, period, quality, country/survey or survey-search filters on the left, or clear the discovery facets above.</div>`;
  renderDiscovery(vis.length);}
// "Clear filters" (E3): drop the discovery facets and the Find text query (the two view-level narrowings
// this bar owns), then re-render. The left-rail structural filters (data type, tree, year, period) keep
// their own controls — this action never silently reaches across into them.
function clearDiscoveryFilters(){
  Object.keys(_facets).forEach(k=>_facets[k]=false);
  const f=document.getElementById("find");
  if(f&&f.value){f.value="";if(typeof renderFind==="function")renderFind();
    if(typeof refresh==="function")refresh();else renderCards();}   // refresh() re-renders cards for the surveys view
  else renderCards();}
function focusSurvey(sv){tree.querySelectorAll('input[value]').forEach(c=>c.checked=(c.value===sv));setView("map");refresh();
  // C42: fit only POSITIONED stations — a withheld-coord station has no [lat,lon] to bound (avoids NaN bounds).
  const _fb=ST.filter(s=>s.survey===sv&&hasPosition(s)).map(s=>[s.lat,s.lon]);if(_fb.length)map.fitBounds(L.latLngBounds(_fb).pad(0.15));}
function selectSurvey(sv){tree.querySelectorAll('input[value]').forEach(c=>c.checked=(c.value===sv));setView("map");refresh();
  selected=new Set(ST.filter(s=>s.survey===sv).map(s=>s.i));updateSel();
  const _sb=ST.filter(s=>s.survey===sv&&hasPosition(s)).map(s=>[s.lat,s.lon]);if(_sb.length)map.fitBounds(L.latLngBounds(_sb).pad(0.15));toast(`Selected all ${selected.size} ${sv} stations — use the download buttons in the left panel.`);}

// C42: bbox over POSITIONED stations only — a withheld-coord station (null lat/lon) would poison Math.min/max
// with NaN. Empty (all-withheld survey) => a degenerate 0° box so callers never crash on b.e/b.w.
function bbox(ss){const p=(ss||[]).filter(hasPosition),xs=p.map(s=>s.lon),ys=p.map(s=>s.lat);
  return xs.length?{w:Math.min(...xs),e:Math.max(...xs),so:Math.min(...ys),no:Math.max(...ys)}:{w:0,e:0,so:0,no:0};}
function miniScatter(ss){const W2=372,H2=200,pad=12;const pp=(ss||[]).filter(hasPosition);const b=bbox(pp);
  const dx=(b.e-b.w)||1,dy=(b.no-b.so)||1,sc=Math.min((W2-2*pad)/dx,(H2-2*pad)/dy);
  const ox=(W2-dx*sc)/2,oy=(H2-dy*sc)/2;
  const d=pp.map(s=>`<circle cx="${(ox+(s.lon-b.w)*sc).toFixed(1)}" cy="${(H2-oy-(s.lat-b.so)*sc).toFixed(1)}" r="2.6" fill="${TYPE_COL[s.type]||"#999"}" fill-opacity=".85"/>`).join("");
  return `<svg width="${W2}" height="${H2}" role="img" style="background:#16242f;border:1px solid var(--line);border-radius:6px">`+
    `<text x="${pad}" y="14" fill="#8FA3B0" font-size="9" font-family="monospace">${b.no.toFixed(1)}°,${b.w.toFixed(1)}° → ${b.so.toFixed(1)}°,${b.e.toFixed(1)}°</text>${d}</svg>`;}
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
  const typeCount={}, swCount={}; let tipper=0, rr=0, rrKnown=0, pmin=Infinity, pmax=-Infinity;
  const qs=[];
  ss.forEach(s=>{ const sc=SCI[s.i]||[];
    if(s.type) typeCount[s.type]=(typeCount[s.type]||0)+1;
    if(sc[SC.sw]) swCount[sc[SC.sw]]=(swCount[sc[SC.sw]]||0)+1;
    if((s.comps||"").indexOf("T")>=0) tipper++;
    if(sc[SC.rr]!=null){ rrKnown++; if(sc[SC.rr]) rr++; }
    if(s.pmin!=null) pmin=Math.min(pmin,s.pmin);
    if(s.pmax!=null) pmax=Math.max(pmax,s.pmax);
    if(s.q!=null) qs.push(s.q); });
  const types=Object.keys(typeCount).sort().map(t=>`${t} ${typeCount[t]}`).join(" · ")||"–";
  const software=m.software||Object.keys(swCount).sort((a,b)=>swCount[b]-swCount[a])[0]||"not recorded";
  const qavg=qs.length?(qs.reduce((a,b)=>a+b,0)/qs.length).toFixed(1):"–";
  const coll=m.collection&&m.collection.id?`<a href="#" data-act="collection" data-coll="${escAttr(m.collection.id)}">${esc(m.collection.title||m.collection.id)}</a>`:"—";
  return `<div class="sechead">Survey summary <span style="font-weight:400;color:var(--muted);text-transform:none;letter-spacing:0">(10-second view)</span></div><table class="meta">`+
    `<tr><td>stations</td><td>${ss.length}</td></tr>`+
    `<tr><td>data types</td><td>${esc(types)}</td></tr>`+
    `<tr><td>period coverage</td><td>${isFinite(pmin)?fmtP(pmin)+" – "+fmtP(pmax)+" s":"–"}</td></tr>`+
    `<tr><td>tipper availability</td><td>${tipper} / ${ss.length} stations</td></tr>`+
    `<tr><td>remote reference</td><td>${rrKnown?`${rr} / ${rrKnown} stations`:"not recorded"}</td></tr>`+
    `<tr><td>instrumentation</td><td>${esc(m.instrument_model||"not recorded in source metadata")}</td></tr>`+
    `<tr><td>processing software</td><td>${esc(software)}</td></tr>`+
    `<tr><td>Automated completeness/smoothness check</td><td>${qavg}/5 <span style="color:var(--muted)">(not a quality verdict)</span></td></tr>`+
    `<tr><td>acquisition</td><td>${esc(m.dates||"–")}</td></tr>`+
    `<tr><td>investigators</td><td>${investigatorsHtml(m.investigators)}</td></tr>`+
    `<tr><td>collection</td><td>${coll}</td></tr>`+
    `<tr><td>licence / access</td><td>${esc(m.lic||"?")} · ${esc(m.access||"open")}</td></tr>`+
    `<tr><td>version</td><td>${esc(m.version||"–")}</td></tr>`+
    `</table>`;
}
// Release notes: shown only when a survey provides them (optional; no requirement for existing surveys).
function releaseNotesHtml(m){
  const rn=m.release_notes;
  if(!Array.isArray(rn)||!rn.length) return "";
  const rows=rn.map(e=>`<tr><td>${esc(e.version||"–")}</td><td>${esc(e.date||"")}${e.date&&e.note?" — ":""}${esc(e.note||"")}</td></tr>`).join("");
  return `<div class="sechead">Release notes</div><table class="meta">${rows}</table>`;
}
// Pre-built per-survey download bundles from the manifest (EDI zip + EMTF-XML zip always when served;
// survey MTH5 only when the survey_h5_enabled flag produced one). Empty string when the survey isn't
// served. C32: the MTH5 bundle holds TRANSFER FUNCTIONS ONLY (never time series) — the label says so,
// matching the engine's <slug>-tf.h5 filename.
function surveyBundleTiles(slug){
  const b=(typeof bundlesForSlug==="function")?bundlesForSlug(slug):[];
  if(!b.length)return"";
  const label={"edi-zip":["EDI bundle (.zip)","whole survey"],
               "xml-zip":["EMTF-XML bundle (.zip)","whole survey"],
               "mth5":["Survey MTH5 (transfer functions)","TFs only · mtpy-v2 / ModEM"]};
  return b.map(r=>{const L=label[r.format]||[r.format,""];
    return `<div class="prod" data-prod="fetch" data-url="${escAttr(r.url)}" data-name="${escAttr(r.url.split("/").pop())}">`+
      `<span class="pdot" style="background:var(--ok)"></span><div>${esc(L[0])}<small>${esc(L[1])}${r.size?" · "+esc(fmtBytes(r.size)):""}</small></div></div>`;
  }).join("");
}
// UX6 Wave E (E2): persistent-identifier rollup count for the survey detail. Counts the four canonical
// PID slots that identifiersHtml renders (Survey PID, Dataset DOI, Organisation ROR, Project RAiD); a slot
// counts as recorded when it is truthy and not a "TODO…" placeholder (the same not-recorded convention
// pidLink uses). Drives the "Persistent identifiers: N of M recorded" summary; the explicit per-row list
// (with its honest "not recorded" rows) is collapsed inside the <details>, never deleted.
function pidRollup(m){const has=v=>!!(v&&!String(v).startsWith("TODO"));
  const fields=[(m||{}).pid,(m||{}).doi,(m||{}).org_ror,(m||{}).raid];
  return {have:fields.filter(has).length,total:fields.length};}
function openSurvey(sv){const ss=ST.filter(s=>s.survey===sv),m=SMETA[sv]||{};
  const rel=relatedSurveys(sv),pr=pidRollup(m);
  _rememberDrawerOpener();                            // E7: capture the invoking element before the rewrite
  // UX6 Wave E (E4): section order — (1) title+description, (2) geographic footprint, (3) station count +
  // period-range stats, (4) licence + downloads, (5) acquisition + processing, (6) investigators + funding,
  // (7) publications, (8) identifiers (E2 rollup), (9) release history. Content is unchanged from before —
  // only the order. Acquisition/processing/investigators are carried inside the survey-summary table
  // (sections 3/5/6 share that one atomic block); the mean-check row keeps its "(not a quality verdict)"
  // framing there. Downloads move up ahead of funding/publications/identifiers; release history moves last.
  drawer.innerHTML=
   `<div class="dhead"><span class="sid" style="font-size:18px">${esc(sv)}</span><button class="close" aria-label="Close">✕</button></div>`+
   `<div class="dsub">${esc(m.org||"custodian unknown")} · ${esc(m.country||"")} · ${esc(m.dates||"dates n/a")}</div>`+
   collLine(m)+
   `<div class="dim" style="margin-top:10px">${esc(m.blurb||"Survey description to be provided by the uploader.")}</div>`+
   miniScatter(ss)+
   surveySummary(ss,m)+
   // C46-W3b: the captured attribution statement rendered where the survey's citation lives (verbatim
   // custodian statement, else the org(year) synthesis), and the upstream "Source datasets" list.
   (attributionText(m)?`<div class="sechead">Attribution ${roleChip("Source data")}</div><div class="attn">${esc(attributionText(m))}</div>`:"")+
   sourcesListHtml(m)+
   `<div class="sechead">Downloads</div><div class="prodgrid">`+
     surveyBundleTiles(m.slug)+
     `<div class="prod" data-act="select" data-survey="${escAttr(sv)}"><span class="pdot" style="background:var(--ok)"></span><div>All EDIs<small>select & download</small></div></div>`+
     `<div class="prod" data-act="focus" data-survey="${escAttr(sv)}"><span class="pdot" style="background:var(--lpmt)"></span><div>View on map<small>zoom to extent</small></div></div>`+
     (m.doi?`<div class="prod" data-act="doi" data-doi="${escAttr(m.doi)}"><span class="pdot" style="background:var(--ok)"></span><div>Dataset DOI<small>source archive</small></div></div>`:"")+
   `</div>`+
   `<div class="sechead">Funding</div><div class="surveymeta">${(m.funders||[]).map(f=>f.pid?`<a href="${escUrl(f.pid)}" target="_blank" rel="noopener noreferrer">${esc(f.name)}</a>`:`${esc(f.name)} <span class='prov'>(no PID)</span>`).join(" · ")||"—"}</div>`+
   `<div class="sechead">Related publications</div>`+pubsHtml(m)+
   `<details class="prov-d survey-ids"><summary>Persistent identifiers: ${pr.have} of ${pr.total} recorded</summary><div class="prov-dbody">`+identifiersHtml(m)+`</div></details>`+
   releaseNotesHtml(m)+
   `<div class="sechead">Related surveys</div><div class="surveymeta">`+
     (rel.length?rel.map(o=>`<a href="#" data-act="story" data-survey="${escAttr(o)}">${esc(o)}</a>`).join(" · "):"<span class='prov'>none nearby</span>")+`</div>`;
  drawer.setAttribute("aria-label",sv+" — survey details");
  drawer.classList.add("open");drawer.scrollTop=0;
  _focusDrawer();}                                    // E7: move focus into the dialog

// ---- single delegated click handler (no inline onclick anywhere) ----
function collLine(m){
  const parts=[];
  if(m.version) parts.push(`Version ${esc(m.version)}`);
  if(m.collection&&m.collection.id) parts.push(`Part of: <a href="#" data-act="collection" data-coll="${escAttr(m.collection.id)}">${esc(m.collection.title||m.collection.id)}</a>`);
  return parts.length?`<div class="dsub" style="margin-top:3px">${parts.join(" · ")}</div>`:"";
}
// Full-width collection page (#collectionview). A collection aggregates MANY surveys, so it gets the
// whole content area, not the narrow drawer: member-survey rollup (total sites, period coverage,
// type/dimensionality mix), an all-stations scatter, and a per-survey table. Reached via #/collection/<id>
// (main.js routeFromHash); collections hold no TFs of their own — everything rolls up from member surveys.
// Collections INDEX (the "Collections" tab): one card per collection in COLL, each opening the
// full-width collection page. A collection appears automatically when surveys share a collection.id.
function collectionCard(cid){const c=COLL[cid];
  return `<div class="scard"><h3 style="cursor:pointer" data-act="collection" data-coll="${escAttr(cid)}" title="Explore collection">${esc(c.title||cid)}</h3>`+
    `<div class="cust">${esc(c.type||"collection")}${c.status?" · "+esc(c.status):""}</div>`+
    `<div class="stats"><b>${c.n_surveys}</b> survey${c.n_surveys===1?"":"s"} · <b>${c.n_stations}</b> station${c.n_stations===1?"":"s"}${c.start_year?" · since <b>"+esc(c.start_year)+"</b>":""}</div>`+
    (c.description?`<div class="desc">${esc(c.description)}</div>`:"")+
    `<div class="stats" style="color:var(--muted);font-size:11px">${(c.surveys||[]).map(esc).join(" · ")||"—"}</div>`+
    `<div class="cardbtns"><button data-act="collection" data-coll="${escAttr(cid)}">Explore collection →</button></div></div>`;
}
// UX6 Wave E (E5): the plain, truthful landing intro above the collections grid.
function collectionsIntroHtml(){return `<p class="coll-intro">Collections group related surveys acquired under one programme — such as the national <b>AusLAMP</b> long-period array. A collection holds no transfer functions of its own; every dataset and its provenance stay with the member surveys it links to. A collection appears here automatically once surveys share a <code>collection.id</code>.</p>`;}
// E5: the participating organisations of a collection, derived from its member surveys' SMETA (deduped, sorted).
function collOrgs(c){const set=new Set();((c&&c.surveys)||[]).forEach(sv=>{const o=(SMETA[sv]||{}).org;if(o)set.add(o);});return [...set].sort();}
// E5: full-width FEATURE card, shown when there are ≤2 collections (grid layout takes over above 2). Name,
// description (truncated with an expand), footprint scatter, the existing rollup stats, participating
// organisations, and a prominent Explore action.
function collFeatureCard(cid){const c=COLL[cid];const members=(c.surveys||[]);const ss=ST.filter(s=>members.indexOf(s.survey)>=0);
  const orgs=collOrgs(c);const desc=c.description||"";const cut=desc.length>240;
  const descHtml=desc
    ? `<div class="desc collfeat-desc">`+(cut
        ? `<span class="cf-short">${esc(desc.slice(0,240))}… <button type="button" class="cf-expand" data-act="cf-expand">Show more</button></span><span class="cf-full" hidden>${esc(desc)}</span>`
        : esc(desc))+`</div>`
    : "";
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
  const intro=document.getElementById("collectionsIntro"),grid=document.getElementById("collectionsGrid");
  if(intro)intro.innerHTML=ids.length?collectionsIntroHtml():"";
  if(!ids.length){if(grid){grid.className="cardgrid";grid.innerHTML=`<div class="emptynote">No collections yet — a collection appears automatically when surveys share a <code>collection.id</code> in their survey.yaml (e.g. AusLAMP).</div>`;}return;}
  const feature=ids.length<=2;                                    // ≤2 => full-width feature cards; grid above 2
  if(grid){grid.className=feature?"collfeature-grid":"cardgrid";
    grid.innerHTML=(feature?ids.map(collFeatureCard):ids.map(collectionCard)).join("");}
}
// UX6 Wave E (E6): collection footprint. Fixed-Australia extent with a simplified coastline + state-
// boundary outline (vendor/au-outline.js — public-domain Natural Earth, see that file's header) drawn
// BENEATH the station dots; dots are COLOURED BY MEMBER SURVEY with a small legend. Degrades cleanly when
// AU_OUTLINE is absent (e.g. the headless harness doesn't load the vendor asset) — dots + legend still
// render. The projection is a plain equirectangular fit of the fixed AU box, so the outline and the dots
// stay registered; the canvas aspect matches the box to avoid squashing.
const AU_EXTENT={w:112,e:154,so:-44,no:-9};
const COLL_PAL=["#2E8FA3","#E0782F","#8A5FC0","#5BAE6A","#3F6FC4","#C255A0","#D9A23B","#A85454"];
function collScatter(ss){
  if(!ss.length) return "";
  const W=560,H=Math.round(W*(AU_EXTENT.no-AU_EXTENT.so)/(AU_EXTENT.e-AU_EXTENT.w)),pad=22;
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
  const svg=`<svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:${W}px;background:#16242f;border:1px solid var(--line);border-radius:8px" role="img" aria-label="Member stations over Australia">${outline}${dots}</svg>`;
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
    return `<tr><td><a href="#" data-act="story" data-survey="${escAttr(sv)}">${esc(sv)}</a><div class="csub">${esc(m.org||"—")}</div></td>`+
      `<td>${sub.length}</td><td>${types}</td><td>${isFinite(pmn)?fmtP(pmn)+"–"+fmtP(pmx)+"s":"–"}</td></tr>`;
  }).join("");
  const v=document.getElementById("collectionview");
  v.innerHTML=
   `<div class="collpagenav"><button class="collback" data-act="collidx">← All collections</button>`+
   `<button class="collback collmapbtn" data-act="collmap" data-coll="${escAttr(cid)}">View all stations on main map</button></div>`+
   `<h1 class="colltitle">${esc(c.title||cid)}</h1>`+
   `<div class="collsub">${esc(c.type||"collection")}${c.status?" · "+esc(c.status):""} · ${c.n_surveys} survey${c.n_surveys===1?"":"s"} · ${c.n_stations} station${c.n_stations===1?"":"s"}${c.start_year?" · since "+esc(c.start_year):""}${c.last_updated?" · updated "+esc(c.last_updated):""}</div>`+
   (c.description?`<div class="colldesc">${esc(c.description)}</div>`:"")+
   `<div class="collnote">A collection groups related surveys (e.g. a national programme such as AusLAMP). It holds <b>no transfer functions of its own</b> — all data and provenance live with the member surveys below.</div>`+
   `<div class="cstats">`+stat("surveys",c.n_surveys)+stat("stations",c.n_stations)+
     stat("period coverage",isFinite(pmin)?fmtP(pmin)+"–"+fmtP(pmax)+"s":"–")+stat("tipper stations",tip+" / "+ss.length)+stat("extent",ext)+`</div>`+
   (ss.length?`<div class="csechead">Station map</div>`+collScatter(ss):"")+
   `<div class="csechead">Member surveys (${members.length})</div>`+
   `<table class="colltable"><thead><tr><th>Survey</th><th>Stations</th><th>Data&nbsp;types</th><th>Period&nbsp;range</th></tr></thead><tbody>${rows}</tbody></table>`;
  document.getElementById("map").style.display="none";
  document.getElementById("surveysview").style.display="none";
  const _ci=document.getElementById("collectionsview");if(_ci)_ci.style.display="none";
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
    // UX6 Wave C: the scroll target (#pt_anchor) now lives in the Response tab with the phase tensor in a
    // collapsed <details> — activate its tab and open the plot collapsibles so the scroll actually reveals it.
    const panel=el.closest?el.closest('[role="tabpanel"]'):null;
    if(panel&&panel.dataset&&panel.dataset.tab)selectDrawerTab(panel.dataset.tab);
    if(panel&&panel.querySelectorAll)panel.querySelectorAll("details.plotcollapse").forEach(dt=>{dt.open=true;});
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
  else if(act==="expand"){e.preventDefault();const kind=el.dataset.plot;if(kind&&typeof openPlotModal==="function"&&_curTf)openPlotModal(kind,_curTf);}
  else if(act==="story"){e.preventDefault();openSurvey(sv);}
  else if(act==="collection"){e.preventDefault();location.hash="#/collection/"+encodeURIComponent(el.dataset.coll);}
  else if(act==="collidx"){e.preventDefault();if(location.hash.indexOf("#/collection/")===0)history.replaceState(null,"",location.pathname+location.search);setView("collections");}
  else if(act==="collmap"){e.preventDefault();if(typeof viewCollectionOnMap==="function")viewCollectionOnMap(el.dataset.coll);}   // E6: switch to map + fitBounds to the collection
  else if(act==="cf-expand"){e.preventDefault();const box=el.closest(".collfeat-desc");if(box){const sh=box.querySelector(".cf-short"),fu=box.querySelector(".cf-full");if(sh)sh.hidden=true;if(fu)fu.hidden=false;}}   // E5: expand a truncated feature description
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
  const fc=document.getElementById("facetChips");
  if(fc&&fc.addEventListener)fc.addEventListener("click",e=>{const b=e.target.closest&&e.target.closest("[data-facet]");if(!b)return;
    const k=b.dataset.facet;if(k in _facets){_facets[k]=!_facets[k];renderCards();}});
})();
