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

function apa(m,doi){return `${esc(m.au)} (${esc(m.yr||"n.d.")}). ${esc(m.ti)}${m.ve?" ("+esc(m.ve)+")":""} [Data set]. ${esc(m.pb)}.`+(doi?` https://doi.org/${esc(doi)}`:"");}
function bibtex(k,m,doi){return `@misc{${k},\n  author    = {${m.au.replace(/;/g," and")}},\n  title     = {${m.ti}},\n  year      = {${m.yr||"n.d."}},\n  publisher = {${m.pb}},\n${doi?`  doi       = {${doi}},\n`:""}  note      = {Accessed via the AusMT portal}\n}`;}
function ris(m,doi){return `TY  - DATA\nAU  - ${m.au.replace(/; /g,"\nAU  - ")}\nTI  - ${m.ti}\nPY  - ${m.yr||""}\nPB  - ${m.pb}\n${doi?`DO  - ${doi}\nUR  - https://doi.org/${doi}\n`:""}ER  -`;}

function badge(l,st,title){const c=st==="ok"?"ok":st==="part"?"part":st==="no"?"no":"";const s=st==="ok"?"✓":st==="part"?"◐":st==="no"?"✗":"?";return `<span class="badge ${c}"${title?` title="${escAttr(title)}"`:""}>${s} ${esc(l)}</span>`;}
// C1b: a survey's access.level is authoritative for whether the portal has its DISPLAY data. "open" (or
// absent/legacy) => served, curves present. Anything else (embargoed | metadata_only | an unknown value)
// => NON-OPEN: the engine emits EMPTY tf series for these stations (the response curves ARE the embargoed
// data), so the drawer must render an ACCESS PANEL in place of the four plots rather than four blank frames.
function accessLevelOf(m){return (m&&m.access)?String(m.access):"open";}
function isOpenAccess(m){return accessLevelOf(m)==="open";}
// The access panel replacing the plots area for a non-open survey. Verbatim copy (esc()'d) per level:
// embargoed(+date) / embargoed(no date) / metadata_only; any other non-open value falls back to the
// no-date embargo wording (fail-closed: an unknown level is treated as withheld, never as open).
function accessPanel(m){
  const lvl=accessLevelOf(m);
  const when=(m&&m.embargo_until)?String(m.embargo_until):"";
  let title,body;
  if(lvl==="metadata_only"){
    title="Metadata only";
    body="This survey is listed metadata-only. Station locations and survey metadata are public; transfer functions are available from the custodian — see the survey's contact and identifiers.";
  }else if(when){
    title="Embargoed until "+when;
    body="This survey is embargoed until "+when+". Station locations and survey metadata are public; transfer functions and downloads are withheld until the embargo lifts.";
  }else{
    title="Embargoed";
    body="This survey is embargoed. Station locations and survey metadata are public; transfer functions and downloads are withheld.";
  }
  return `<div class="plot accesspanel"><div class="badges" style="margin-bottom:8px">${badge(title,"part")}</div>`+
    `<div class="emptynote" style="padding:8px 4px">${esc(body)}</div></div>`;
}
function maturityBar(s){const m=SMETA[s.survey]||{},sc=SCI[s.i]||[];
  const curated=true,fair=!!m.doi,repro=!!(sc[SC.sw]&&m.ts==="ok");
  const lvl=repro?3:fair?2:curated?1:0;const names=["Legacy","Curated","FAIR","Reproducible"];
  return `<div class="maturity">`+names.map((n,k)=>`<div class="step ${k<=lvl?"on":""} ${k===lvl?"cur":""}">${n}</div>`).join("")+`</div>`;}
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
  const ediArt=arts.find(a=>a.format==="edi"), xml=arts.find(a=>a.format==="emtfxml");
  // C1b: a non-open survey has no served TF here (bytes withheld by the C1 gate, curves withheld by C1b),
  // so the TF tile must NOT offer the "via source archive" EDI fetch — it says "embargoed"/"metadata only"
  // (no action) instead, matching the access panel that replaced the plots above.
  const ediTile=ediArt
    ? {n:"Transfer function",sub:"EDI (download)"+(ediArt.size?" · "+fmtBytes(ediArt.size):""),st:"ok",d:{prod:"fetch",url:ediArt.url,name:ediArt.url.split("/").pop()}}
    : !isOpenAccess(m)
    ? {n:"Transfer function",sub:accessLevelOf(m)==="metadata_only"?"metadata only":"embargoed",st:"no",d:null}
    : {n:"Transfer function",sub:s.ediAvail?"EDI (download)":"EDI (via source archive)",st:s.ediAvail?"ok":"unk",d:{prod:"edi",file:s.file,avail:s.ediAvail?"1":"0",survey:s.survey}};
  const xmlTile=xml
    ? {n:"EMTF XML",sub:"download"+(xml.size?" · "+fmtBytes(xml.size):""),st:"ok",d:{prod:"fetch",url:xml.url,name:xml.url.split("/").pop()}}
    : {n:"EMTF XML",sub:"via pipeline",st:"part",d:{prod:"toast",msg:"EMTF XML is produced in the build pipeline (mt_metadata); served on the hosted site for redistributable surveys."}};
  const items=[
   ediTile,
   xmlTile,
   {n:"MTH5",sub:m.mth5==="ok"?"available":m.mth5==="part"?"partial":"not located",st:m.mth5||"unk",d:m.mth5==="no"?null:{prod:"open",url:tsDoi}},
   {n:"Raw time series",sub:m.ts==="ok"?"NCI THREDDS":"not located",st:m.ts||"unk",d:m.ts==="ok"?{prod:"open",url:tsDoi}:null},
   {n:"Phase tensor",sub:"computed",st:"ok",d:{prod:"scroll",sel:"#pt_anchor"}},
   {n:"Publication",sub:m.doi?"DOI":"none recorded",st:m.doi?"ok":"no",d:m.doi?{prod:"open",url:"https://doi.org/"+m.doi}:null}
  ];
  const attrs=d=>d?Object.entries(d).map(([k,v])=>`data-${k}="${escAttr(v)}"`).join(" "):"";
  return `<div class="prodgrid">`+items.map(it=>`<div class="prod ${it.d?"":"dis"}" ${attrs(it.d)}><span class="pdot" style="background:var(--${it.st==="ok"?"ok":it.st==="part"?"part":it.st==="no"?"no":"unk"})"></span><div>${esc(it.n)}<small>${esc(it.sub)}</small></div></div>`).join("")+`</div>`;}
function provGraph(s){const m=SMETA[s.survey]||{},sc=SCI[s.i]||[];
  const nodes=[
   ["Raw time series",m.ts==="ok"?`<a href="${escUrl(tsUrlFor(m))}" target="_blank" rel="noopener noreferrer">${m.ts_pid?"survey collection":"NCI collection"}</a>`:"not located"],
   ["Processing software",sc[SC.sw]?esc(sc[SC.sw]):"not stated in EDI"],
   ["Method",sc[SC.alg]?esc(sc[SC.alg]):(sc[SC.rr]?"remote reference (stated)":"not stated")],
   ["Transfer function",`${s.nper} periods · ${esc(s.comps.split("").join("+"))||"–"}`],
   ["Distributed formats",`EDI ✓ · EMTF XML (pipeline)${m.mth5==="ok"?" · MTH5 ✓":""}`],
   ["Publication",m.doi?`<a href="${escUrl("https://doi.org/"+m.doi)}" target="_blank" rel="noopener noreferrer">doi:${esc(m.doi)}</a>`:"none recorded"]
  ];
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
    ["pipeline", esc((P.pipeline||"ausmt/extract.build_portal")+(P.pipeline_version?" v"+P.pipeline_version:""))],
    ["software", esc(P.software&&P.software.python?("python "+P.software.python):"n/a")],
    ["screening parameters", params],
    ["build date (UTC)", esc(P.generated?P.generated.replace("T"," ").slice(0,19):"n/a")],
    ["git commit", P.git_commit?`<code>${esc(P.git_commit)}</code>`:"<span class='prov'>not recorded</span>"]
  ];
  return `<details class="prov-d"><summary>Processing provenance</summary><table class="meta">`+
    rows.map(([k,v])=>`<tr><td>${esc(k)}</td><td>${v}</td></tr>`).join("")+
    `</table><div class="prov" style="margin-top:6px">Every product traces to its input file, the extractor and version, and the screening parameters above — reproducible offline by <i>AusMT</i>.</div></details>`;
}
function openStation(i){
  const s=ST[i],t=TFD[i]||[[]],m=SMETA[s.survey]||{},sc=SCI[i]||[];
  // UX3 item 7a: sc[SC.dim] (dimensionality) is no longer surfaced in the drawer screening grid — it's
  // inferable from the phase tensor + skew, which stay shown (strike/|β|/3-D-periods line below). The
  // sc.json field itself is unchanged (data products are display-only edits); the map's colour-by-dim
  // mode still reads s.dim. So `dim` is intentionally not destructured here anymore.
  const p3d=sc[SC.p3d],gd=sc[SC.gd],skew=sc[SC.skew],mre=sc[SC.mre],dec=sc[SC.decades];
  location.hash="#/station/"+encodeURIComponent(s.ausmt_id);   // ausmt_id is globally unique; s.id (DATAID) repeats across surveys
  const azs=[];if(t[T.pt_az])t[T.pt_az].forEach((a,k)=>{if(a!=null&&t[T.pt_beta][k]!=null&&Math.abs(t[T.pt_beta][k])<5)azs.push(((a%180)+180)%180);});
  let strikeTxt="insufficient low-skew data";
  if(azs.length>=3){const rad=azs.map(a=>2*a*Math.PI/180);const mean=Math.atan2(rad.reduce((s,x)=>s+Math.sin(x),0),rad.reduce((s,x)=>s+Math.cos(x),0))/2*180/Math.PI;
    const st=((mean%180)+180)%180;strikeTxt=`~N${st.toFixed(0)}°E / N${((st+90)%180).toFixed(0)}°E <span style="color:var(--muted)">(90° ambiguous)</span>`;}
  const diag=`<div class="sci">`+
    `<div class="cell"><div class="lab">Period band</div><div class="val">${fmtP(s.pmin)}–${fmtP(s.pmax)}s</div></div>`+
    `<div class="cell"><div class="lab">Coverage</div><div class="val">${dec!=null?dec+" dec":"–"}</div></div>`+
    `<div class="cell" title="median relative apparent-resistivity error (= 2× the relative impedance error); errors are one standard error (√VAR)"><div class="lab">TF ρ error</div><div class="val">${mre!=null?Math.round(mre*100)+"%":"n/a"}</div></div>`+
    `<div class="cell"><div class="lab">Tipper</div><div class="val">${s.comps.includes("T")?"yes":"no"}</div></div>`+
    `<div class="cell"><div class="lab">Remote ref</div><div class="val">${sc[SC.rr]?"yes":"unk"}</div></div>`+
  `</div>`;
  const keysafe=s.ausmt_id.replace(/[^a-z0-9]/g,"_");
  drawer.innerHTML=
   `<div class="dhead"><span class="sid">${esc(s.id)}</span><span class="chip" style="background:${TYPE_COL[s.type]||"#999"}">${esc(s.type)}</span>`+
   (m.collection&&m.collection.id?`<span class="chip collchip" data-act="collection" data-coll="${escAttr(m.collection.id)}" title="Open collection">${esc(m.collection.title||m.collection.id)}</span>`:"")+
   `<button class="close" aria-label="Close">✕</button></div>`+
   `<div class="dsub">${esc(s.survey)} · ${esc(s.org)} · ${esc(s.country)}</div>`+
   collLine(m)+
   // C1b: for a non-open survey the engine withheld the display curves (empty tf series), so render the
   // access panel here INSTEAD of the four (now-empty) plots — the response curves ARE the withheld data.
   // The #pt_anchor is kept (empty) so the "Phase tensor" related-product scroll target never dangles.
   (isOpenAccess(m)
     ? rhoPlot(t)+phasePlot(t)+`<div id="pt_anchor"></div>`+ptPlot(t)+arrowPlot(t)   // C20: arrow panel BELOW the phase tensor, replacing the |T| plot
     : accessPanel(m)+`<div id="pt_anchor"></div>`)+
   `<div class="sechead">Screening diagnostics <span style="text-transform:none;letter-spacing:0">· not interpretation products</span></div>`+diag+
   `<div class="dim">Geoelectric strike: <b>${strikeTxt}</b>${skew!=null?` · mean |β| <b>${skew}°</b> · 3-D periods <b>${p3d}%</b>`:""}.<br>`+
   `${gd?"⚠ <b>Galvanic/static-shift</b> signature detected (ρ modes offset by a near-constant factor with coincident phases). ":""}`+
   `<span style="color:var(--muted)">TF completeness/smoothness diagnostic: ${sc[SC.q]!=null?`<b style="color:${qColor(sc[SC.q])}">${sc[SC.q].toFixed(1)}/5</b> — ${sc[SC.qb]==="e"?"median error + coverage + smoothness":"shape-based; no error bars in EDI"}; <i>not a quality or geological-value judgement</i>`:"n/a"}.</span></div>`+
   `<div class="sechead">Related products</div>`+relatedProducts(s)+
   `<div class="sechead">Advanced analysis <span style="text-transform:none;letter-spacing:0">· Tier 3, generated offline</span></div>`+
   `<div class="dim">McNeice–Jones / Groom–Bailey decomposition, distortion parameters and Lilley Mohr circles are produced by the <i>AusMT</i> pipeline and surfaced here when available. <span style="color:var(--muted)">Not computed in the browser.</span></div>`+
   `<div class="sechead">Provenance &amp; lineage</div>`+provGraph(s)+provenanceBox(s)+
   identifiersHtml(m)+
   `<div class="sechead">Maturity</div>`+maturityBar(s)+
   `<div class="badges">${badge("EDI","ok")}${badge("time series",m.ts||"unk")}${badge("MTH5",m.mth5||"unk")}${badge("DOI",m.doi?"ok":"no")}${badge(m.lic||"licence ?",m.lic&&m.lic.startsWith("CC")?"ok":"unk")}${s.fixed?badge("coord QC","part","Coordinates were flagged during QC — see this station's provenance and treat with caution."):""}</div>`+
   `<div class="sechead">Cite this station's source</div><div class="citebox">${apa(m.cite||AUSMT_SELF,m.doi)}`+
     `<div class="cb-row"><button data-cite="apa" data-survey="${escAttr(s.survey)}">APA</button>`+
     `<button data-cite="bibtex" data-survey="${escAttr(s.survey)}" data-key="${escAttr(keysafe)}">BibTeX</button>`+
     `<button data-cite="ris" data-survey="${escAttr(s.survey)}">RIS</button></div></div>`+
   `<div class="sechead">Metadata &amp; API</div><table class="meta">`+
     `<tr><td>ausmt_id</td><td>${esc(s.ausmt_id)}</td></tr>`+
     `<tr><td>lat, lon</td><td>${s.lat.toFixed(6)}, ${s.lon.toFixed(6)}</td></tr>`+
     `<tr><td>components</td><td>${esc(s.comps.split("").join(" + "))||"–"}</td></tr>`+
     `<tr><td>source file</td><td>${esc(s.file)}</td></tr></table>`+
   `<div class="api">Planned read API (static JSON on the hosted site):<br>GET <b>/api/station/${esc(s.ausmt_id)}.json</b><br>GET <b>/api/survey/${esc(s.slug||s.survey.toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/-$/,""))}.json</b><br>GET <b>/api/station/${esc(s.ausmt_id)}/edi</b></div>`;
  drawer.classList.add("open");drawer.scrollTop=0;
}
function closeDrawer(){drawer.classList.remove("open");if(location.hash.startsWith("#/station"))history.replaceState(null,"",location.pathname+location.search);}
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
function surveyCard(sv){const ss=ST.filter(s=>s.survey===sv),m=SMETA[sv]||{};
  const mix={};ss.forEach(s=>mix[s.type]=(mix[s.type]||0)+1);
  const pmin=Math.min(...ss.map(s=>s.pmin)),pmax=Math.max(...ss.map(s=>s.pmax));
  const tip=Math.round(100*ss.filter(s=>s.comps.includes("T")).length/ss.length);
  const qs=ss.map(s=>s.q).filter(v=>v!=null);const qavg=qs.length?(qs.reduce((a,b)=>a+b,0)/qs.length).toFixed(1):"–";
  const fixes=ss.filter(s=>s.fixed).length;
  const ext=`${(Math.max(...ss.map(s=>s.lon))-Math.min(...ss.map(s=>s.lon))).toFixed(1)}° × ${(Math.max(...ss.map(s=>s.lat))-Math.min(...ss.map(s=>s.lat))).toFixed(1)}°`;
  const mixbar=Object.entries(mix).map(([ty,n])=>`<div style="width:${100*n/ss.length}%;background:${TYPE_COL[ty]}" title="${esc(ty)}: ${n}"></div>`).join("");
  // UX3 item 7b: the "N×3-D / N×2-D / N×1-D" dimensionality fragment was removed from the stats line
  // (dimensionality is inferable from the phase tensor + skew, which stay shown). The per-station `dim`
  // tally that fed it is gone with it.
  return `<div class="scard"><div class="scardhead"><h3 style="cursor:pointer" data-act="story" data-survey="${escAttr(sv)}" title="Open survey story">${esc(sv)}</h3>`+(m.collection&&m.collection.id?`<span class="chip collchip" data-act="collection" data-coll="${escAttr(m.collection.id)}" title="Open collection">${esc(m.collection.title||m.collection.id)}</span>`:"")+`</div><div class="cust">${esc(m.org||"custodian unknown")} · ${esc(m.country||"")}</div>`+
   `<div class="mixbar">${mixbar}</div>`+
   `<div class="stats"><b>${ss.length}</b> stations · mean TF diagnostic <b>${qavg}/5</b> · tipper <b>${tip}%</b><br>periods <b>${fmtP(pmin)}–${fmtP(pmax)}s</b><br>extent ${ext} · ${fixes} coord QC flag${fixes===1?"":"s"}</div>`+
   `<div class="badges">${badge("EDI",m.edi||"ok")}${badge("time series",m.ts||"unk")}${badge("MTH5",m.mth5||"unk")}${badge("DOI",m.doi?"ok":"no")}${badge(m.lic||"licence ?",m.lic&&m.lic.startsWith("CC")?"ok":"unk")}</div>`+
   cardDesc(m)+
   identifiersHtml(m)+
   `<div class="cite">${apa(m.cite||AUSMT_SELF,m.doi)}</div>`+
   `<div class="cardbtns"><button data-act="story" data-survey="${escAttr(sv)}">Survey story</button><button data-act="focus" data-survey="${escAttr(sv)}">View on map</button><button data-act="select" data-survey="${escAttr(sv)}">Select all & download</button>`+(m.doi?`<button data-act="doi" data-doi="${escAttr(m.doi)}">Open DOI</button>`:"")+`</div></div>`;}
function pidLink(p){if(!p)return "<span class='prov'>not yet wired</span>";if(p.startsWith("TODO"))return `<span class='prov'>${esc(p)}</span>`;
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
    `Dataset DOI: <span class="pidline">${m.doi?pidLink(m.doi):"<span class='prov'>to be wired</span>"}</span><br>`+
    `Organisation ROR: <span class="pidline">${ror||"<span class='prov'>not recorded</span>"}</span><br>`+
    `Project RAiD: <span class="pidline">${raid||"<span class='prov'>not recorded</span>"}</span><br>`+
    `Instrument model: ${m.instrument_model?esc(m.instrument_model):"<span class='prov'>not recorded</span>"}<br>`+
    instrumentPidsHtml(m)+
    `Funders: ${fundLine}</div>`;}
function pubCite(p){return `${esc(p.a)} (${esc(p.y)}). ${esc(p.t)}. <i>${esc(p.j)}</i>.`+(p.doi?` <a href="${escUrl("https://doi.org/"+p.doi)}" target="_blank" rel="noopener noreferrer">doi:${esc(p.doi)}</a>`:"");}
function pubsHtml(m){const ps=(m.pubs||[]);
  if(!ps.length)return `<div class="surveymeta"><span class='prov'>No related publications recorded yet — the science pipeline can auto-suggest these from DOIs that cite the dataset.</span></div>`;
  return `<div class="surveymeta">`+ps.map(p=>"• "+pubCite(p)).join("<br><br>")+`</div>`;}
function renderCards(){const vis=surveys.filter(surveyVisible);
  document.getElementById("cardGrid").innerHTML = vis.length
    ? vis.map(surveyCard).join("")
    : `<div class="emptynote">No surveys match the current filters. Loosen the data-type, period, quality, country/survey or survey-search filters on the left.</div>`;}
function focusSurvey(sv){tree.querySelectorAll('input[value]').forEach(c=>c.checked=(c.value===sv));setView("map");refresh();
  map.fitBounds(L.latLngBounds(ST.filter(s=>s.survey===sv).map(s=>[s.lat,s.lon])).pad(0.15));}
function selectSurvey(sv){tree.querySelectorAll('input[value]').forEach(c=>c.checked=(c.value===sv));setView("map");refresh();
  selected=new Set(ST.filter(s=>s.survey===sv).map(s=>s.i));updateSel();
  map.fitBounds(L.latLngBounds(ST.filter(s=>s.survey===sv).map(s=>[s.lat,s.lon])).pad(0.15));toast(`Selected all ${selected.size} ${sv} stations — use the download buttons in the left panel.`);}

function bbox(ss){return {w:Math.min(...ss.map(s=>s.lon)),e:Math.max(...ss.map(s=>s.lon)),so:Math.min(...ss.map(s=>s.lat)),no:Math.max(...ss.map(s=>s.lat))};}
function miniScatter(ss){const W2=372,H2=200,pad=12;const b=bbox(ss);
  const dx=(b.e-b.w)||1,dy=(b.no-b.so)||1,sc=Math.min((W2-2*pad)/dx,(H2-2*pad)/dy);
  const ox=(W2-dx*sc)/2,oy=(H2-dy*sc)/2;
  const d=ss.map(s=>`<circle cx="${(ox+(s.lon-b.w)*sc).toFixed(1)}" cy="${(H2-oy-(s.lat-b.so)*sc).toFixed(1)}" r="2.6" fill="${TYPE_COL[s.type]||"#999"}" fill-opacity=".85"/>`).join("");
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
    `<tr><td>instrumentation</td><td>${esc(m.instrument_model||"not recorded")}</td></tr>`+
    `<tr><td>processing software</td><td>${esc(software)}</td></tr>`+
    `<tr><td>mean TF diagnostic</td><td>${qavg}/5 <span style="color:var(--muted)">(completeness/smoothness; not a quality verdict)</span></td></tr>`+
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
function openSurvey(sv){const ss=ST.filter(s=>s.survey===sv),m=SMETA[sv]||{};
  const rel=relatedSurveys(sv);
  drawer.innerHTML=
   `<div class="dhead"><span class="sid" style="font-size:18px">${esc(sv)}</span><button class="close" aria-label="Close">✕</button></div>`+
   `<div class="dsub">${esc(m.org||"custodian unknown")} · ${esc(m.country||"")} · ${esc(m.dates||"dates n/a")}</div>`+
   collLine(m)+
   miniScatter(ss)+
   `<div class="dim" style="margin-top:10px">${esc(m.blurb||"Survey description to be provided by the uploader.")}</div>`+
   surveySummary(ss,m)+
   releaseNotesHtml(m)+
   `<div class="sechead">Funding</div><div class="surveymeta">${(m.funders||[]).map(f=>f.pid?`<a href="${escUrl(f.pid)}" target="_blank" rel="noopener noreferrer">${esc(f.name)}</a>`:`${esc(f.name)} <span class='prov'>(no PID)</span>`).join(" · ")||"—"}</div>`+
   `<div class="sechead">Related publications</div>`+pubsHtml(m)+
   `<div class="sechead">Identifiers &amp; instruments</div>`+identifiersHtml(m)+
   `<div class="sechead">Downloads</div><div class="prodgrid">`+
     surveyBundleTiles(m.slug)+
     `<div class="prod" data-act="select" data-survey="${escAttr(sv)}"><span class="pdot" style="background:var(--ok)"></span><div>All EDIs<small>select & download</small></div></div>`+
     `<div class="prod" data-act="focus" data-survey="${escAttr(sv)}"><span class="pdot" style="background:var(--lpmt)"></span><div>View on map<small>zoom to extent</small></div></div>`+
     (m.doi?`<div class="prod" data-act="doi" data-doi="${escAttr(m.doi)}"><span class="pdot" style="background:var(--ok)"></span><div>Dataset DOI<small>source archive</small></div></div>`:"")+
   `</div>`+
   `<div class="sechead">Related surveys</div><div class="surveymeta">`+
     (rel.length?rel.map(o=>`<a href="#" data-act="story" data-survey="${escAttr(o)}">${esc(o)}</a>`).join(" · "):"<span class='prov'>none nearby</span>")+`</div>`;
  drawer.classList.add("open");drawer.scrollTop=0;}

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
  return `<div class="scard"><h3 style="cursor:pointer" data-act="collection" data-coll="${escAttr(cid)}" title="Open collection">${esc(c.title||cid)}</h3>`+
    `<div class="cust">${esc(c.type||"collection")}${c.status?" · "+esc(c.status):""}</div>`+
    `<div class="stats"><b>${c.n_surveys}</b> survey${c.n_surveys===1?"":"s"} · <b>${c.n_stations}</b> site${c.n_stations===1?"":"s"}${c.start_year?" · since <b>"+esc(c.start_year)+"</b>":""}</div>`+
    (c.description?`<div class="desc">${esc(c.description)}</div>`:"")+
    `<div class="stats" style="color:var(--muted);font-size:11px">${(c.surveys||[]).map(esc).join(" · ")||"—"}</div>`+
    `<div class="cardbtns"><button data-act="collection" data-coll="${escAttr(cid)}">Open collection →</button></div></div>`;
}
function renderCollections(){const ids=Object.keys((typeof COLL!=="undefined"&&COLL)||{}).sort();
  document.getElementById("collectionsGrid").innerHTML = ids.length
    ? ids.map(collectionCard).join("")
    : `<div class="emptynote">No collections yet — a collection appears automatically when surveys share a <code>collection.id</code> in their survey.yaml (e.g. AusLAMP).</div>`;
}
function collScatter(ss){
  if(!ss.length) return "";
  const W=900,H=300,pad=18,b=bbox(ss);
  const dx=(b.e-b.w)||1,dy=(b.no-b.so)||1,sc=Math.min((W-2*pad)/dx,(H-2*pad)/dy);
  const ox=(W-dx*sc)/2,oy=(H-dy*sc)/2;
  const dots=ss.map(s=>`<circle cx="${(ox+(s.lon-b.w)*sc).toFixed(1)}" cy="${(H-oy-(s.lat-b.so)*sc).toFixed(1)}" r="3" fill="${TYPE_COL[s.type]||"#999"}" fill-opacity=".82"><title>${esc(s.id)} · ${esc(s.survey)}</title></circle>`).join("");
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:${W}px;background:#16242f;border:1px solid var(--line);border-radius:8px" role="img" aria-label="Member station map">`+
    `<text x="${pad}" y="16" fill="#8FA3B0" font-size="10" font-family="monospace">${b.no.toFixed(1)}°,${b.w.toFixed(1)}° → ${b.so.toFixed(1)}°,${b.e.toFixed(1)}°</text>${dots}</svg>`;
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
   `<button class="collback" data-act="collidx">← All collections</button>`+
   `<h1 class="colltitle">${esc(c.title||cid)}</h1>`+
   `<div class="collsub">${esc(c.type||"collection")}${c.status?" · "+esc(c.status):""} · ${c.n_surveys} survey${c.n_surveys===1?"":"s"} · ${c.n_stations} site${c.n_stations===1?"":"s"}${c.start_year?" · since "+esc(c.start_year):""}${c.last_updated?" · updated "+esc(c.last_updated):""}</div>`+
   (c.description?`<div class="colldesc">${esc(c.description)}</div>`:"")+
   `<div class="collnote">A collection groups related surveys (e.g. a national programme such as AusLAMP). It holds <b>no transfer functions of its own</b> — all data and provenance live with the member surveys below.</div>`+
   `<div class="cstats">`+stat("surveys",c.n_surveys)+stat("sites",c.n_stations)+
     stat("period coverage",isFinite(pmin)?fmtP(pmin)+"–"+fmtP(pmax)+"s":"–")+stat("tipper sites",tip+" / "+ss.length)+stat("extent",ext)+`</div>`+
   (ss.length?`<div class="csechead">Station map</div>`+collScatter(ss):"")+
   `<div class="csechead">Member surveys (${members.length})</div>`+
   `<table class="colltable"><thead><tr><th>Survey</th><th>Sites</th><th>Data&nbsp;types</th><th>Period&nbsp;range</th></tr></thead><tbody>${rows}</tbody></table>`;
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
  else if(d.prod==="scroll"&&d.sel){const el=document.querySelector(d.sel);if(el)el.scrollIntoView({behavior:"smooth"});}
  else if(d.prod==="toast")toast(d.msg);}
document.addEventListener("keydown",e=>{if(e.key==="Escape")closeDrawer();});
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
  if(act==="story"){e.preventDefault();openSurvey(sv);}
  else if(act==="collection"){e.preventDefault();location.hash="#/collection/"+encodeURIComponent(el.dataset.coll);}
  else if(act==="collidx"){e.preventDefault();if(location.hash.indexOf("#/collection/")===0)history.replaceState(null,"",location.pathname+location.search);setView("collections");}
  else if(act==="focus")focusSurvey(sv);
  else if(act==="select")selectSurvey(sv);
  else if(act==="doi"&&doi)window.open(escUrl("https://doi.org/"+doi),"_blank","noopener,noreferrer");   // NOT encodeURIComponent — it %2F-escapes the DOI slash -> doi.org 404; escUrl still blocks scheme injection
});
