"use strict";
// Scope-following downloads + toast/snackbar. Every download acts on scopeSel() (the selection,
// else the filtered corpus); paintDownloadRows() owns the Download block's scope line, priced rows
// and disabled states. Citation/EDI helpers are referenced at click time only.
// CSV/GeoJSON columns are built from the station object + the positional sci row sc[] (sc[SC.q]=q,
// sc[SC.qb]=qb, sc[SC.rr]=rr, sc[SC.sw]=sw, sc[SC.dim]=dim) — see the legend in data.js / data-files.md before
// reordering export columns.
const sel=()=>ST.filter(s=>selected.has(s.i));
// Lane B: every download acts on the SCOPE - the selection when one exists, else the filtered
// corpus (filters.js scopeStations; the scope line in the Download block states which). sel() stays
// for callers that mean the literal selection.
function scopeSel(){return (typeof scopeStations==="function")?scopeStations():sel();}
// Bind one control's click handler, tolerating an absent element: an unguarded miss threw at parse
// time and silently dropped every LATER binding and top-level assignment in this file. A missing id
// announces itself in the console instead.
function bindClick(id,fn){const el=document.getElementById(id);
  if(el)el.onclick=fn;else console.error("export control #"+id+" is missing; handler not bound");}
function csvCell(v){
  if(typeof v==="number"&&isFinite(v))return String(v);   // numeric data is never a formula
  v=(v==null?"":String(v));
  // Neutralise spreadsheet formula injection (=,+,-,@,tab,CR) - except a value that parses as a
  // finite number: a southern latitude starts with "-" and quoting it turns the whole lat column
  // into text for Excel/pandas/QGIS.
  if(/^[=+\-@\t\r]/.test(v)&&!isFinite(Number(v)))v="'"+v;
  return /[",\n\r]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v;}
function csvRow(arr){return arr.map(csvCell).join(",");}
function tsUTC(){return new Date().toISOString().replace(/[-:]/g,"").replace(/\.\d{3}Z$/,"Z");} // YYYYMMDDTHHMMSSZ
function save(n,t,m){const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([t],{type:m||"text/plain"}));a.download=n;a.click();URL.revokeObjectURL(a.href);}
function toast(m){const t=document.getElementById("toast");t.textContent=m;t.style.display="block";clearTimeout(toast._h);toast._h=setTimeout(()=>t.style.display="none",7000);}
// ---- the hand-off snackbar (owner UX ruling 2026-08-23) ------------------------------------------
// PROGRESS BELONGS TO THE BROWSER: a hand-off is a 302, the bytes travel browser-to-archive, and
// CORS forbids fetching the payload in-page. No progress bar, no download panel, no completion
// claim - the page says only what it handed over. It differs from toast() in exactly one way, which is why it is a second element and not a
// second use of the first: it can carry ONE action, the wget command for a whole list.
function snack(msg,note,action){
  const el=document.getElementById("snackbar");if(!el)return;
  el.textContent="";
  const body=document.createElement("span");
  body.appendChild(document.createTextNode(msg));
  if(note){const n=document.createElement("span");n.className="snack-note";n.textContent=note;body.appendChild(n);}
  el.appendChild(body);
  if(action){const b=document.createElement("button");b.type="button";b.className="snack-act";
    b.textContent=action.label;b.addEventListener("click",action.onClick);el.appendChild(b);}
  el.classList.remove("hidden");
  clearTimeout(snack._h);
  // An offer with an action gets long enough to reach for it; a plain hand-off note is transient.
  snack._h=setTimeout(()=>{el.classList.add("hidden");el.textContent="";},action?25000:9000);}
// Above this the wait is worth naming. 5 GB is the owner's threshold; the corpus has single archives
// of 9.87 GB, and a reader who clicked expecting a file is owed the warning before the browser goes
// quiet for a quarter of an hour.
var HANDOFF_LARGE_BYTES=5*1024*1024*1024;
function handoffSnack(filename,bytes){
  snack("Handed to NCI THREDDS - your browser is downloading "+filename+
        " ("+(bytes?fmtBigBytes(bytes):"size not stated")+"). Progress appears in your browser's downloads.",
        bytes>=HANDOFF_LARGE_BYTES?"Large file - this may take a while.":null);}

// CSV rows (header + one per station). Derefs the positional sci row sc[SC.q/qb/rr/dim/sw] at THE export
// call site — extracted from the click handler so it is unit-testable: tests/test_populated_portal_smoke.py
// value-binds these columns, which is the ONLY coverage of the qb/rr/sw call sites (buildState/drawer
// don't expose them). Output is unchanged from the inline version.
function csvRows(stations){
  // C6/C46: `license`, `license_url` (the deed URL keyed off the canonical id) and `attribution` (the
  // rendered attribution line — the custodian's verbatim statement when declared, else the org(year)
  // synthesis) travel with the exported rows so the rights don't get stripped when a CSV of the selection
  // is shared.
  // UX8 (W3b, owner directive): the station CSV DROPS six columns — quality, quality_basis, remote_ref,
  // dimensionality, software and file — leaving a lean identity/geometry/rights row. (These derived-screen
  // and per-station-file fields stay in the GeoJSON export; the smoke test's column value-binds moved to
  // the reduced set.) The rights columns license/license_url/attribution stay.
  const rows=[["ausmt_id","station","country","organisation","survey","lat","lon","type","components","n_periods","period_min_s","period_max_s","source_doi","timeseries_collection_doi","survey_version","collection","license","license_url","attribution"]];
  stations.forEach(s=>{const m=SMETA[s.survey]||{};rows.push([s.ausmt_id,s.id,s.country,s.org,s.survey,s.lat,s.lon,s.type,s.comps,s.nper,s.pmin,s.pmax,m.doi||"",TS_COLLECTION.doi,m.version||"",(m.collection||{}).id||"",m.lic||"",licenseUrl(m.lic),attributionLine(m)]);});
  return rows;
}
// C46: the licence deed URL for a raw licence string, via the canonical PROFILES/LICENSES tables (never a
// startsWith guess); "" when the id has no single canonical URL (e.g. PUBLIC DOMAIN) or is unrecognised.
function licenseUrl(lic){return (LICENSES.urls||{})[canonLic(lic)]||"";}
// C46: the rendered attribution line for a survey — the custodian's verbatim attribution.statement when
// declared, else the org(year) synthesis (the same default the LICENSE instrument uses when no statement).
function attributionLine(m){m=m||{};
  const st=((m.attribution||{}).statement||"").toString().trim();
  if(st)return st;
  const who=((m.cite&&m.cite.au)||m.org||"").toString().trim();
  const yr=(m.dates?(String(m.dates).match(/\d{4}/g)||[]).slice(-1)[0]:"")||"";
  return [who,yr?"("+yr+")":""].filter(Boolean).join(" ").trim();}
// C6/C46: the LICENSE.txt content that travels inside the client-side bulk-download zip, mirroring the
// engine's _license_text.license_instrument_text EXACTLY — the two implementations are pinned to a shared
// vector file (engine/tests/fixtures/license_instrument_vectors.json), consumed by both an engine pytest
// AND portal/tests/license_text_vectors.test.js, so they cannot drift silently. Deed URLs + attribution
// PROFILES come from the generated LICENSES/PROFILES tables (contract/*.json), keyed by the canonical id.
// Signature MIRRORS the Python leaf (lic, licensor, year, attribution, sources, changes) so the shared
// vectors drive both sides with identical inputs; the m -> (who, yr, attn) derivation lives at the call
// site below (as it does in build_portal), not inside the renderer.
var DEFAULT_CHANGES_SUMMARY = "the deposited transfer functions were regenerated into AusMT's canonical distribution formats, and station coordinates, identifiers and metadata were conditioned for release";
function canonLic(s){const u=String(s==null?"":s).trim().replace(/\s+/g," ").toUpperCase();
  return ((LICENSES.aliases||{})[u]||u).toUpperCase();}
function year4(s){const m=String(s==null?"":s).match(/\d{4}/);return m?m[0]:"";}   // source `retrieved` -> its year
function renderProfile(key,licensor,year,sourceTitle,derivative){
  const prof=(PROFILES[key]||PROFILES.generic||{});
  const tmpl=(derivative&&prof.derivative)?prof.derivative:(prof.attribution||"{licensor} ({year})");
  // ONE left-to-right pass (like Python str.format): a value carrying a {token} is inserted literally, never re-scanned.
  return tmpl.replace(/\{(licensor|year|source_title)\}/g,(_,k)=>k==="licensor"?licensor:(k==="year"?year:sourceTitle));
}
function licenseInstrumentText(lic,licensor,year,attribution,sources,changes){
  const cid=canonLic(lic);
  const url=(LICENSES.urls||{})[cid]||"";
  const who=(licensor||"the survey custodian").toString().trim();
  const yr=(year==null?"":String(year)).trim();
  const attn=(attribution||(who+(yr?" ("+yr+")":""))).toString().trim();
  const L=["AusMT survey data — licence and attribution","============================================","",
    "Licence:     "+cid];
  if(url)L.push("Licence URL: "+url);
  L.push("Licensor:    "+who,"Year:        "+(yr||"not stated"),"","Attribution (cite as):","  "+attn,"",
    "This LICENSE.txt travels with the data files in this archive. The transfer functions were",
    "distributed via the AusMT portal, which serves only openly licensed Australian magnetotelluric",
    "releases; the licence above is the custodian's, set in the survey's survey.yaml. Reuse under the",
    "terms of that licence"+(url?" ("+url+").":"."),"");
  // C46 additions (byte-inert when sources + changes are both absent): per-source attribution paragraphs,
  // supersession line(s), then the CC-BY §3(a) changes clause. Order + wording pinned to the Python leaf.
  const srcs=sources||[];
  if(srcs.length){
    const made=!!(changes&&changes.made);
    L.push("Source datasets","---------------","");
    for(const s0 of srcs){const s=s0||{};
      const title=(s.title==null?"":String(s.title)).trim()||"untitled source dataset";
      const cust=(s.custodian==null?"":String(s.custodian)).trim()||"unknown custodian";
      const ident=(s.identifier==null?"":String(s.identifier)).trim();
      const slic=canonLic(s.licence);
      const head=title+" — "+cust+(ident?" ("+ident+")":"")+", licensed "+slic+".";
      const statement=(s.statement==null?"":String(s.statement)).trim();
      let attr;
      if(statement){attr=statement;}
      else{const pk=(s.profile==null?"":String(s.profile)).trim()||"generic";
        const syr=year4(s.retrieved)||yr;
        attr=renderProfile(pk,cust,syr,title,made&&pk==="ga");}
      L.push(head,"  "+attr,"");
    }
    for(const s0 of srcs){const slic=canonLic((s0||{}).licence);
      if(slic&&slic!==cid)L.push("The upstream dataset was obtained under "+slic+"; this AusMT release is published by the custodian under "+cid+".","");}
    // C46-W3a: each custodian profile's s.5 disclaimer once (dedup, first-seen), the final paragraph(s)
    // of the Source-datasets block — a profile-level legal notice, so it renders even under a verbatim
    // statement. Byte-inert when no source's profile carries a disclaimer. Pinned to the Python leaf.
    const seenDisc=[];
    for(const s0 of srcs){const pk=((s0||{}).profile==null?"":String((s0||{}).profile)).trim()||"generic";
      const disc=((PROFILES[pk]||{}).disclaimer==null?"":String((PROFILES[pk]||{}).disclaimer)).trim();
      if(disc&&seenDisc.indexOf(disc)<0){seenDisc.push(disc);L.push(disc,"");}}
  }
  if(changes&&changes.made){
    const summary=(changes.summary==null?"":String(changes.summary)).trim()||DEFAULT_CHANGES_SUMMARY;
    L.push("Changes were made: "+summary+". AusMT serves derived renditions (canonical EMTF XML; MTH5 where available) generated from the deposited files; per-station conditioning notes are recorded in the machine-readable products.","");
  }
  return L.join("\n");
}
bindClick("dlCsv",()=>{track("DownloadGenerated",{format:"csv",n:scopeSel().length});
  save("ausmt-stations-"+tsUTC()+".csv",csvRows(scopeSel()).map(csvRow).join("\r\n"),"text/csv");});
// Two-phase boot: quality/dimensionality/remote_ref ride each GeoJSON feature and come from sci.json, a
// PHASE 2 product. An export is a FILE that outlives the page, so it must never carry a value the portal
// simply had not received yet. AWAIT the gate (already-resolved in the normal case, so the click is
// unchanged once hydration is done) rather than degrade.
// If sci.json FAILED, awaiting settles on nothing: sciRow returns [] for every station, and the
// quality/dimensionality/remote_ref keys would vanish as undefined (JSON.stringify drops them) with no
// trace of why. remote_ref carries its own per-row guard besides: a station with no usable sci row
// omits the key rather than claiming false, matching its two siblings. So when the product is not usable the
// three screening properties are omitted DELIBERATELY and the FILE ITSELF carries the reason: a toast does
// not travel with the download, and whoever opens this file next has no other way to learn the difference
// between "not screened" and "the screening data never loaded".
const GEO_SCI_UNAVAILABLE="quality, dimensionality and remote_ref are OMITTED from every feature in this file: the screening product (sci.json) could not be loaded in the session that generated it. Their absence records a load failure, NOT a screening outcome.";
// Extracted from the click handler for the same reason csvRows was (see above): the honesty rule now has a
// branch here, and a branch that only exists inside an onclick is a branch no test can reach.
function geoFeatureCollection(stations,sciOk){
  return {type:"FeatureCollection",...(sciOk?{}:{note:GEO_SCI_UNAVAILABLE}),features:stations.map(s=>{const sc=sciRow(s.i);return{type:"Feature",geometry:hasPosition(s)?{type:"Point",coordinates:[s.lon,s.lat]}:null,   // C42: a withheld-coord station is an unlocated feature (spec-legal null geometry), never a (0,0)/[null,null] phantom point
  properties:{id:s.id,ausmt_id:s.ausmt_id,country:s.country,organisation:s.org,survey:s.survey,type:s.type,components:s.comps,period_min_s:s.pmin,period_max_s:s.pmax,...(sciOk?{quality:sc[SC.q],dimensionality:sc[SC.dim],remote_ref:sc[SC.rr]==null?undefined:!!sc[SC.rr]}:{}),source_doi:(SMETA[s.survey]||{}).doi||null,survey_version:(SMETA[s.survey]||{}).version||null,collection_id:((SMETA[s.survey]||{}).collection||{}).id||null,license:(SMETA[s.survey]||{}).lic||null,license_url:licenseUrl((SMETA[s.survey]||{}).lic)||null,attribution:attributionLine(SMETA[s.survey]||{})||null,file:s.file}};})};  // C6/C46: licence + deed URL + attribution ride each GeoJSON feature
}
bindClick("dlGeo",async()=>{track("DownloadGenerated",{format:"geojson",n:scopeSel().length});
  if(hydrating("sci")){toast("Waiting for the screening data before writing the GeoJSON…");}
  await SCI_READY;
  const sciOk=hydrUsable("sci");
  if(!sciOk)toast("The screening data could not be loaded, so quality, dimensionality and remote reference are left out of this GeoJSON; the file says so.");
  save("ausmt-selection-"+tsUTC()+".geojson",JSON.stringify(geoFeatureCollection(scopeSel(),sciOk),null,1),"application/geo+json");});
// POINTERS (Lane B, D2): the merged provenance-and-hand-off document, one per scope station. It is
// the union of the two files it replaces: EVERY station in scope appears (the archive-pointers
// rule), and stations with verified open files carry actionable levels[] rows (the fetch-list
// rule), including explicit gap rows where a route could not be built. source_doi is the survey's
// OWN dataset DOI or null with the reason - never the time-series collection DOI standing in for a
// TF source archive (the pre-C7 mislabel the EDI zip's gap file already refuses).
var POINTERS_NOTE="AusMT hosts no raw time series and fetches none of them. Each stations[].levels[].url is an AusMT route that answers 302 with the address of the archive holding the file; archive_url_comment records where that route currently points and is for reference only (wget follows the redirect on its own; curl needs -L). A station without levels[] has no file this deployment can route to: request those from the source archive via source_doi/landing, or contact the custodian where none is recorded.";
bindClick("dlSh",()=>{const st=scopeSel();track("DownloadGenerated",{format:"pointers",n:st.length});
  if(hydrating("tsaccess")){snack("Waiting for the archive hand-off index…");return;}
  let files=0,bytes=0;
  const rows=st.map(s=>{const m=SMETA[s.survey]||{};
    const ls=tsHandoffLevels(s,null,true);
    const row={ausmt_id:s.ausmt_id,station:s.id,survey:s.survey,
               survey_version:m.version||null,lat:s.lat,lon:s.lon,
               source_doi:m.doi||null,landing:m.doi?"https://doi.org/"+m.doi:null};
    // No dataset DOI: say why the pointer is thin. A served survey simply has none recorded; a
    // withheld one states its actual access reason (embargo vs licence), as the zip gap files do.
    if(!m.doi)row.source_note=s.ediAvail?"no dataset DOI recorded for this survey"
                                        :(typeof withheldReason==="function"?withheldReason(m):"withheld");
    if(ls.length){row.levels=ls;ls.forEach(l=>{if(l.url){files++;bytes+=(l.bytes||0);}});}
    return row;});
  const doc={note:POINTERS_NOTE,generated:new Date().toISOString(),
    scope:{stations:rows.length,levels:"all"},
    time_series_collection:{name:TS_COLLECTION.name,doi:TS_COLLECTION.doi,
                            landing:"https://doi.org/"+TS_COLLECTION.doi},
    stations:rows};
  save("ausmt-pointers-"+tsUTC()+".json",JSON.stringify(doc,null,2),"application/json");
  if(files){
    const cmd=tsWgetCommand(rows.filter(r=>r.levels));
    snack("Pointers written for "+rows.length+" station"+(rows.length===1?"":"s")+" - "+files+" fetchable file"+(files===1?"":"s")+", "+fmtBigBytes(bytes)+".",
          "Your browser downloads them; AusMT only points the way.",
          {label:"Copy wget command",onClick:()=>{if(typeof copyTxt==="function")copyTxt(cmd);}});}
  else snack("Pointers written for "+rows.length+" station"+(rows.length===1?"":"s")+". None has a time-series file this deployment can route to.");});

// ---- the time-series HAND-OFF list (R7 / D3 / D5) ------------------------------------------------
// The offer is a POINTER FILE, never a server-built zip or a fourth exportSelectionFormat:
// AusMT holds none of these bytes, and packaging them would make
// this portal a proxy for an archive that already serves them properly.
//
// PORTAL-GENERATED, not gateway-generated (D5). A fifth public gateway route would touch two
// independent allowlists, their parity test, both deny-by-default blocks and the route table; the
// /go/ts/ path shape already carries survey, station and level, which is the whole of what the
// measurement needs. That is also why nothing here calls track(): the request the reader actually
// makes is counted at the front door, from the route it names.
//
// Each row states the ROUTE, because that is the string to fetch, and the archive's own address
// alongside as an inert reference (D3) - so the file still names its bytes if AusMT is down, without
// pretending that address is what you were asked to fetch.
var TS_HANDOFF_NOTE="AusMT hosts none of these files and fetches none of them. Each `url` is an AusMT route that answers 302 with the address of the archive holding the file; `archive_url_comment` records where that route currently points and is for reference only. wget follows the redirect on its own; curl needs -L.";
// One station's routable levels, in the vocabulary's own order so two readers' files sort alike.
// `levels` names the level tokens on the table; empty/null means every level this station has.
function tsHandoffLevels(s,levels,includeGaps){
  const lv=(typeof tsRoutesFor==="function")?tsRoutesFor(s&&s.ausmt_id):null;
  if(!lv)return [];
  return TS_LEVELS.map(([tok])=>tok)
    .filter(tok=>lv[tok]&&(!levels||!levels.length||levels.indexOf(tok)>=0))
    .map(tok=>{const url=tsGoRoute(s,tok),okUrl=!!(url&&/^https?:/i.test(url));
      const row={level:tok,url:okUrl?url:null,bytes:lv[tok].bytes||null,
                 filename:String(lv[tok].url_path||"").split("/").pop(),
                 archive_url_comment:tsArchiveUrl(lv[tok].url_path)};
      // A verified file whose portal route cannot be built (no survey slug) is a GAP, not a
      // silence: the fetch lists drop the row, the Pointers document keeps it and says why.
      if(!okUrl)row.note="no portal route could be built for this level";
      return row;})
    .filter(r=>includeGaps?true:!!r.url);}
// The whole document, plus the two figures the confirmation states. Pure, and extracted for the
// reason csvRows and geoFeatureCollection were: a claim about what a downloaded file contains is a
// claim no test can reach while it lives inside an onclick.
function tsHandoffDocument(stations,levels){
  const rows=[];let files=0,bytes=0;
  (stations||[]).forEach(s=>{const ls=tsHandoffLevels(s,levels);
    if(!ls.length)return;
    files+=ls.length;ls.forEach(l=>{bytes+=(l.bytes||0);});
    rows.push({ausmt_id:s.ausmt_id,station:s.id,survey:s.survey,
               survey_version:(SMETA[s.survey]||{}).version||null,levels:ls});});
  // The document records its own scope, so a list narrowed to one level cannot read as "all this
  // scope has": how many stations were asked, and which levels were on the table.
  return {files:files,bytes:bytes,doc:{note:TS_HANDOFF_NOTE,generated:new Date().toISOString(),
    scope:{stations:(stations||[]).length,levels:(levels&&levels.length)?levels.slice():"all"},
    time_series_collection:{name:TS_COLLECTION.name,doi:TS_COLLECTION.doi,
                            landing:"https://doi.org/"+TS_COLLECTION.doi},
    stations:rows}};}
// The command the COPY button offers. A heredoc rather than "wget -i <the file you just saved>": the
// saved file is JSON (the #dlSh shape, so one habit reads both), and `wget -i` wants bare urls, so
// naming the file would hand over a command that does not run. It fetches the ROUTES, never the
// archive addresses beside them, because the route is what the front door counts.
function tsWgetCommand(rows){
  const urls=[];(rows||[]).forEach(r=>r.levels.forEach(l=>{if(l.url)urls.push(l.url);}));
  return ["# AusMT time-series hand-off: "+urls.length+" file(s). wget follows the 302 to the archive.",
          "wget --content-disposition -i - <<'AUSMT_EOF'"].concat(urls,["AUSMT_EOF"]).join("\n");}
// One level's fetch list for the current scope, from the Download block's time-series rows. The
// row names its own level, so no hidden chooser state can narrow this file (the pre-Lane-B defect:
// a collapsed accordion's level toggles silently scoped the old Time-series list export).
function tsLevelList(tok){
  // Two-phase boot: the index IS the availability answer here, so writing a list before it lands
  // would report every station as having nothing to fetch. Say which wait this is and stop.
  if(hydrating("tsaccess")){snack("Waiting for the archive hand-off index…");return;}
  const built=tsHandoffDocument(scopeSel(),[tok]);
  if(!built.files){snack("Nothing in the current scope has a time-series file this deployment can route to at this level.");return;}
  save("ausmt-timeseries-"+tok+"-"+tsUTC()+".json",JSON.stringify(built.doc,null,2),"application/json");
  const cmd=tsWgetCommand(built.doc.stations);
  snack("Download list ready - "+built.files+" file"+(built.files===1?"":"s")+", "+fmtBigBytes(built.bytes)+".",
        "Your browser downloads them; AusMT only points the way.",
        {label:"Copy wget command",onClick:()=>{if(typeof copyTxt==="function")copyTxt(cmd);}});}
// C22 (2026-07-07): the human-readable CITATIONS.txt line for ONE entry. When the entry has NO DOI the
// pack SAYS SO explicitly — "[no DOI assigned]" — rather than silently omitting the field (chief-architect
// ruling: a reference pack should state the absence). The .bib/.ris twins simply OMIT their doi=/DO/UR
// fields (drawer.js apa/bibtex/ris already guard on a falsy doi, d2bc616); emitting placeholder text there
// would be ingested by reference managers as real bibliographic data — the pre-C22 defect, where
// AUSMT_SELF.pb carried "(DOI to be minted per release via Zenodo)" into every no-DOI publisher field.
function citeLine(c,doi){return "  "+apaPlain(c,doi)+(doi?"":"  [no DOI assigned]");}
bindClick("dlCite",async()=>{const _scope=scopeSel();track("DownloadGenerated",{format:"ris",n:_scope.length});const svs=[...new Set(_scope.map(s=>s.survey))].sort();const today=new Date().toISOString().slice(0,10);
  let txt=["AusMT citation pack — generated "+today,"Stations: "+_scope.length+" across "+svs.length+" survey release(s).","","== Survey source releases =="];let bib="",risT="";
  svs.forEach(sv=>{const m=SMETA[sv]||{};const c=m.cite||AUSMT_SELF;
    // C46: an EXPLICIT fallback — a survey with no custodian cite block is no longer SILENTLY rendered as
    // the AusMT brand (the pre-C46 `m.cite||AUSMT_SELF` masquerade). The human line SAYS the custodian
    // citation is unrecorded and points at the AusMT package citation instead; the .bib/.ris twins keep
    // the package fallback but under a survey-slug key, never claiming to BE the custodian's own citation.
    if(m.cite){txt.push(citeLine(c,m.doi));}
    else{txt.push("  "+sv+": custodian citation not recorded — cite the survey package:",citeLine(AUSMT_SELF,m.doi));}
    bib+=bibtex(sv.toLowerCase().replace(/[^a-z0-9]+/g,"_"),c,m.doi)+"\n\n";risT+=ris(c,m.doi)+"\n\n";});
  txt.push("","== Time-series collection ==",citeLine(NCI_CITE,TS_COLLECTION.doi));bib+=bibtex("nci_auscope_mt",NCI_CITE,TS_COLLECTION.doi)+"\n\n";risT+=ris(NCI_CITE,TS_COLLECTION.doi)+"\n\n";
  txt.push("","== Curated catalogue metadata (suggested) ==",citeLine(AUSMT_SELF,null));bib+=bibtex("ausmt_catalogue",AUSMT_SELF,null)+"\n";risT+=ris(AUSMT_SELF,null)+"\n";
  // C46: source-dataset citations chained — one line per UNIQUE upstream source across the selection
  // (identifier + custodian + licence + title), so a derived release credits the dataset it was built from.
  const srcSeen={},srcLines=[];
  svs.forEach(sv=>{((SMETA[sv]||{}).sources||[]).forEach(s=>{if(!s)return;
    const key=((s.identifier||s.title||"")+"|"+(s.custodian||"")).toLowerCase();if(srcSeen[key])return;srcSeen[key]=1;
    const ident=(s.identifier||"").toString().trim(),cust=(s.custodian||"").toString().trim(),slic=canonLic(s.licence),title=(s.title||"").toString().trim();
    srcLines.push("  "+[ident||"[no identifier]",cust?"— "+cust:"",slic?"("+slic+")":"",title?"["+title+"]":""].filter(Boolean).join(" "));});});
  if(srcLines.length)txt.push("","== Source datasets ==",...srcLines);
  // C7: organisation ROR(s) — one line per custodian org that declared one, so the acknowledgement can
  // cite the organisation by its persistent identifier, not just its free-text name.
  const rors=[...new Set(svs.map(sv=>{const m=SMETA[sv]||{};return m.org_ror?`${m.org} (ROR: ${m.org_ror})`:null;}).filter(Boolean))];
  txt.push("","== Custodian organisation identifiers ==",...(rors.length?rors.map(r=>"  "+r):["  none recorded"]));
  // C46: the acknowledgement is DATA-DRIVEN, assembled from the ACTUAL selection — the custodians of
  // record (attribution.custodian, else the organisation) plus each unique source-dataset attribution
  // (verbatim statement, else the profile-rendered form). The AusLAMP/AuScope/NCI sentence is included
  // ONLY when the selection references that archive (a survey's ts_pid or a source pointing at NCI/AuScope
  // / the collection DOI) — no longer a hardcoded paragraph on every pack.
  const custodians=[...new Set(svs.map(sv=>{const m=SMETA[sv]||{};return ((m.attribution||{}).custodian||m.org||"").toString().trim();}).filter(Boolean))];
  const saSeen={},srcAttrs=[];
  svs.forEach(sv=>{const m=SMETA[sv]||{};const yr=(m.dates?(String(m.dates).match(/\d{4}/g)||[]).slice(-1)[0]:"")||"";
    (m.sources||[]).forEach(s=>{if(!s)return;const stmt=(s.statement||"").toString().trim();
      const a=stmt||renderProfile((s.profile||"generic").toString().trim()||"generic",(s.custodian||"").toString().trim(),year4(s.retrieved)||yr,(s.title||"").toString().trim(),false);
      if(a&&!saSeen[a]){saSeen[a]=1;srcAttrs.push(a);}});});
  const usesNci=svs.some(sv=>{const m=SMETA[sv]||{};const pid=String(m.ts_pid||"");
    const inSrc=(m.sources||[]).some(s=>{const blob=(s?((s.custodian||"")+" "+(s.identifier||"")):"").toString();return /auscope|nci/i.test(blob)||(TS_COLLECTION.doi&&blob.indexOf(TS_COLLECTION.doi)>=0);});
    return (pid&&(/auscope|nci/i.test(pid)||(TS_COLLECTION.doi&&pid.indexOf(TS_COLLECTION.doi)>=0)))||inSrc;});
  const ack=["","== Suggested acknowledgement ==",
    "  Transfer functions were obtained via the AusMT portal, which aggregates openly licensed",
    "  Australian magnetotelluric releases. Please attribute the data to its custodian(s):"];
  (custodians.length?custodians:["(no custodian recorded — see the survey releases above)"]).forEach(cn=>ack.push("    "+cn));
  if(srcAttrs.length){ack.push("  Source dataset attribution:");srcAttrs.forEach(a=>ack.push("    "+a));}
  if(usesNci)ack.push("  AusLAMP is a collaboration between AuScope, Geoscience Australia, state and territory","  geological surveys and university partners, with instruments supplied through the AuScope","  NCRIS program. Time series were accessed from the NCI-AuScope Magnetotelluric Collection","  (doi:"+TS_COLLECTION.doi+").");
  txt.push(...ack);
  const z=new JSZip();z.file("CITATIONS.txt",txt.join("\n"));z.file("citations.bib",bib);z.file("citations.ris",risT);
  const blob=await z.generateAsync({type:"blob"});const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="ausmt-citation-pack-"+tsUTC()+".zip";a.click();URL.revokeObjectURL(a.href);});
// The BULK-EXPORT LABEL (owner ruling 2026-08-01). The multi-file export below marks each file fetch it
// issues with this query flag, so the server-log aggregator can tell a drag-selected bulk export from a
// single station download. It is a LABEL on a request that already happens: no extra request, no beacon,
// nothing about who is asking. The flag rides the QUERY and never the path, because the aggregator strips
// the query before attributing a download, so a flagged and an unflagged fetch of the same file are still
// one file (see deploy/scripts/aggregate_stats.py: the dedupe key is the query-stripped path).
//
// ONLY this flow labels anything. The drawer's own single-station downloads go through drawer.js
// downloadUrl() and stay unlabelled, which is the whole point: an unlabelled fetch is exactly what
// "single" means downstream, so leaking the flag onto that path would reclassify every single download
// as a bulk one. The gate is therefore the CALL SITE, not the shared dataUrl() helper both use.
var SEL_BULK_FLAG="sel=bulk";
function bulkUrl(u){u=String(u);return u+(u.indexOf("?")>=0?"&":"?")+SEL_BULK_FLAG;}
// C6/C46: rights travel with the bytes: one LICENSE.txt per included survey, beside that survey's files
// (same slug namespace). Built entirely from client-side SMETA (no fetch), mirroring the served-zip
// instrument. The m -> (who, yr, attn) derivation mirrors build_portal's LICENSE.txt call site;
// sources/changes ride on SMETA when present (dormant until a survey carries an attribution/sources
// block). Extracted from the EDI flow, byte for byte, when the EMTF XML and MTH5 selection zips arrived:
// three archives of the same custodian's files must carry the same instrument, and a second copy of this
// derivation is exactly how they would come to differ. `included` maps survey name -> zip subdirectory.
function writeLicenseFiles(folder,included){
  Object.keys(included).forEach(sv=>{const m=SMETA[sv]||{};
    const who=((m.cite&&m.cite.au)||m.org||"the survey custodian").trim();
    const yr=(m.dates?(m.dates.match(/\d{4}/g)||[]).slice(-1)[0]:"")||"";
    const attn=[who,yr?"("+yr+")":"",(m.cite&&m.cite.ti)||""].filter(Boolean).join(" ").trim()||who;
    folder.file(included[sv]+"LICENSE.txt",licenseInstrumentText(m.lic,who,yr,attn,m.sources||null,m.changes||null));});
}
// The SELECTION-ZIP EVENT SHAPE, shared by all three bulk buttons. `format` is what the reader receives
// and `files` is what is inside it, so the three flows are one comparable series: an operator can ask "how
// often is a selection taken as an archive" and "which format is asked for" separately, and the answers
// still add up. They used to disagree: the EDI zip reported format:"zip" while the two derived-format
// zips reported format:"emtfxml"/"mth5", which put ONE action in two vocabularies. Nothing downstream can
// tell a naming difference from a behaviour difference, so a chart of "zip exports" silently excluded two
// of the three buttons and a chart by format double-counted the third against the single-file downloads,
// which report their own extension through the drawer's dispatchProd.
// Bounded-concurrency fetch for the bulk zips. Results keep the INPUT order (zip entries stay
// deterministic across runs) and a failure lands as null in its slot, so per-file accounting is
// the caller's, unchanged. Six in flight matches a browser's per-host default; the sequential
// loop this replaces serialised ~300 round trips behind one another.
async function fetchBounded(items,limit,getUrl){
  const out=new Array(items.length);let next=0;
  async function worker(){
    for(;;){const i=next++;if(i>=items.length)return;
      try{const r=await fetch(getUrl(items[i]));out[i]=r&&r.ok?await r.blob():null;}
      catch(e){out[i]=null;}}}
  await Promise.all(Array.from({length:Math.max(1,Math.min(limit,items.length))},worker));
  return out;}
function trackSelectionZip(files){track("DownloadGenerated",{format:"zip",files:files,n:scopeSel().length});}
bindClick("dlZip",async()=>{trackSelectionZip("edi");
  // Two-phase boot: each EDI is fetched at its MANIFEST url when there is one (the legacy flat path is only
  // the fallback), so packaging before the manifest lands would silently take the fallback route for every
  // station and could write a zip missing files that are in fact served. Await the gate.
  if(hydrating("manifest")){toast("Waiting for the download index…");}
  await MANIFEST_READY;
  const z=new JSZip(),f=z.folder("ausmt_edis");
  const chosen=scopeSel(),avail=chosen.filter(s=>s.ediAvail),unavail=chosen.filter(s=>!s.ediAvail);
  let ok=0;const included={};toast("Packaging "+avail.length+" redistributable EDI(s)…");   // included: survey -> zip subdir
  const ediItems=avail.map(s=>{try{const ea=(typeof artifactsFor==="function"?artifactsFor(s.ausmt_id):[]).find(a=>a.format==="edi");
    // Namespace the zip entry by survey slug too: a selection can span surveys that reuse an EDI basename
    // (e.g. two surveys with 01.edi), which would otherwise overwrite each other inside the zip (audit M3).
    return {s,url:bulkUrl(ea?dataUrl(ea.url):dataUrl("edi/"+s.file)),entry:(s.slug?s.slug+"/":"")+s.file};}
    catch(e){return null;}}).filter(Boolean);
  const ediBlobs=await fetchBounded(ediItems,6,it=>it.url);
  ediItems.forEach((it,i)=>{if(ediBlobs[i]){f.file(it.entry,ediBlobs[i]);ok++;included[it.s.survey]=it.s.slug?it.s.slug+"/":"";}});
  writeLicenseFiles(f,included);
  if(unavail.length){const lines=["These selected stations are NOT redistributable via AusMT (licence/embargo).",
    "Request them from the source archive, or contact the custodian where no DOI is recorded:",""].concat(unavail.map(s=>{const m=SMETA[s.survey]||{};
    // C7: m.doi (the survey's OWN dataset DOI) is the honest TF source archive. There is no substitute
    // when it is absent (TS_COLLECTION is the raw time-series collection, not a TF source archive, and
    // citing it here would mislabel a different dataset as "the source archive", the pre-C7 defect); so
    // when no DOI is recorded we state the ACTUAL access reason (embargo vs licence) via withheldReason().
    return m.doi?`${s.id}  (${s.survey})  ->  https://doi.org/${m.doi}`
                :`${s.id}  (${s.survey})  ->  ${withheldReason(m)}`;}));
    z.file("NOT_INCLUDED_request_from_archive.txt",lines.join("\n"));}
  if(ok===0&&!unavail.length){toast("Nothing to package.");return;}
  if(ok===0){z.file("README.txt","No EDIs were redistributable in this selection; see the archive pointers file.");}
  const blob=await z.generateAsync({type:"blob"});const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="ausmt-selection-edis-"+tsUTC()+".zip";a.click();URL.revokeObjectURL(a.href);
  toast(`Zipped ${ok} EDI(s)`+(unavail.length?`; ${unavail.length} not redistributable (archive pointers included).`:"."));});

// ---- selection exports for the two AusMT-derived formats (owner ask 2026-08-04) ------------------
// A reader who has drawn a box around forty stations can take their EDIs in one click. AusMT also serves
// a per-station EMTF XML and a per-station MTH5, and until now the only way to collect those over a
// selection was forty visits to forty drawers. These two flows are the EDI flow over a different format:
// same per-station manifest rows, same bulk label on every fetch, same LICENSE.txt beside the bytes.
//
// One thing genuinely differs, and it drives the honesty rules below. An EDI is the custodian's own file,
// so "is it served here?" is a LICENCE question (s.ediAvail) with a legacy flat path to fall back on. A
// derived file exists only where the build produced one: eight surveys have no served XML at all, and a
// coordinate-generalised or withheld station gets neither format. So availability here is simply "does
// this station have a manifest row of this format", there is no fallback path to guess at, and a
// selection will routinely contain stations that must be skipped. Skipping them quietly would hand back
// an archive of 31 files for 40 stations with nothing to say which nine went missing or why.
var SEL_FORMATS={
  emtfxml:{label:"EMTF XML",folder:"ausmt_emtf_xml",stem:"ausmt-selection-emtf-xml-",
           note:"No EMTF XML is served for these selected stations."},
  mth5:{label:"MTH5",folder:"ausmt_mth5",stem:"ausmt-selection-mth5-",
        note:"No per-station MTH5 is served for these selected stations."},
};
// This station's served manifest row of one format, or null. The SAME rows the station drawer's Files tab
// links, so what a selection export packages and what a drawer offers cannot disagree.
function selArtifact(s,fmt){
  return (typeof artifactsFor==="function"?artifactsFor(s&&s.ausmt_id):[]).find(a=>a&&a.format===fmt)||null;}
// The three selection zips, in the order the panel renders them: element id, button base label, and the
// manifest `format` each one packages.
var SEL_ZIP_BUTTONS=[["dlZip","EDI (zip)","edi","dlZipMeta"],["dlZipXml","EMTF XML (zip)","emtfxml","dlZipXmlMeta"],["dlZipH5","MTH5 (zip)","mth5","dlZipH5Meta"]];
// Size honesty (owner, 2026-08-04): each zip button states what THIS selection would cost before it is
// clicked, so nobody starts a multi-hundred-megabyte MTH5 pull to find out. It counts only the rows the
// export will actually fetch, so it is the estimate for the archive that will arrive, not for the
// selection: an EDI whose station has no manifest row (the legacy flat path) contributes no size, which
// is why every figure is prefixed "~". No manifest, no figure: a total of 0 would render "~0 B", a claim
// that the selection costs nothing, when the truth is that nothing is known yet.
//
// This runs on EVERY KEYSTROKE (filters.js refresh() calls it after re-filtering), so it is a hot path and
// is written as ONE pass over the selection that sums all three formats at once, reading each station's
// rows through the manifest index (data.js mfFileIndex) rather than rescanning files[] per station per
// format. It used to be three passes, each doing a linear scan of the whole manifest per station: 670ms
// per repaint at 3000 selected stations against a 9000-row manifest, on the input path. It is now ~0.3ms
// there, and flat in the manifest size.
function paintL2Rows(st){
  const known=(typeof MANIFEST!=="undefined"&&!!MANIFEST);
  // Object.create(null), so a manifest row whose `format` happens to name an Object.prototype member
  // ("constructor") cannot resolve to an inherited property and be treated as a live total.
  const total=Object.create(null),count=Object.create(null);
  SEL_ZIP_BUTTONS.forEach(([,,fmt])=>{total[fmt]=0;count[fmt]=0;});
  if(known)for(const s of st){
    const rows=(typeof artifactsFor==="function"?artifactsFor(s.ausmt_id):[]);
    // First row of each format only: the export fetches .find(format), so the estimate counts
    // exactly what the archive will contain even under mirror rows.
    const seen=Object.create(null);
    for(const a of rows){if(a&&a.size&&total[a.format]!==undefined&&!seen[a.format]){seen[a.format]=1;total[a.format]+=a.size;count[a.format]++;}}}
  const nEdi=st.filter(s=>s.ediAvail).length;
  SEL_ZIP_BUTTONS.forEach(([id,base,fmt,metaId])=>{
    const b=document.getElementById(id),meta=document.getElementById(metaId);
    // Enablement is what the flow can PACKAGE: the EDI zip has the licence predicate (plus a legacy
    // flat path a station may resolve through with no manifest row); the derived formats exist only
    // as manifest rows. Sizes claim nothing without a manifest ("~0 B" would price the scope at
    // free when the truth is unknown).
    const can=fmt==="edi"?nEdi>0:(known&&count[fmt]>0);
    const c=fmt==="edi"?nEdi:count[fmt];
    const n=(known&&st.length)?total[fmt]:null;
    _tileState(b,can?"ok":"none");
    if(!meta)return;
    meta.textContent=!st.length?"":(c?"Download · "+c+" station"+(c===1?"":"s")+(n?" · ~"+fmtBigBytes(n):""):"nothing in this scope");
    meta.title=n?base+": about "+fmtBigBytes(n)+" across "+c+" station"+(c===1?"":"s")+", estimated from the download index.":"";});
}
// One tile's visual state, in the drawer's Related-products language: ok = live (green dot),
// none = present but priced at nothing (dis + hollow dot), wait = index in flight (dis + unknown dot).
function _tileState(b,state){
  if(!b)return;
  b.disabled=state!=="ok";
  if(b.classList)b.classList.toggle("dis",state!=="ok");
  const d=b.querySelector?b.querySelector(".pdot"):null;
  if(d){d.classList.toggle("hollow",state==="none");
    d.style.background=state==="ok"?"var(--ok)":(state==="wait"?"var(--unk)":"transparent");}
}
// The time-series rows: one per level token, priced over the scope, action = that level's fetch
// list. Two-phase honesty carries over from the retired chooser: in flight is busy-and-disabled
// with the pending hint; a settled-empty deployment says so in the note (a curation state, never a
// load error); membership in ts_access.json is the access decision (R5).
function paintTsRows(st){
  const seg=document.getElementById("tsSeg");if(!seg||!seg.querySelectorAll)return;
  if(!seg.children.length&&typeof TS_LEVELS!=="undefined")TS_LEVELS.forEach(([tok,label,gloss])=>{
    const b=document.createElement("button");b.type="button";b.className="prod";
    b.dataset.ts=tok;b.dataset.gloss=gloss;b.disabled=true;
    // Template markup, drawer-style; TS_LEVELS labels are the module's own constants, not data.
    b.innerHTML='<span class="pdot"></span><div><span class="pname"></span> <span class="rolechip">source archive</span><small class="dlmeta"></small></div>';
    const name=b.querySelector?b.querySelector(".pname"):null;
    if(name)name.textContent=label;
    seg.appendChild(b);});
  const known=(typeof tsAccessKnown==="function")&&tsAccessKnown();
  const ix=(typeof TSACC!=="undefined"&&TSACC)||{};
  const anyPublished=known&&Object.keys(ix).length>0;
  [...seg.querySelectorAll("button")].forEach(b=>{
    const tok=b.dataset.ts;let n=0,bytes=0;
    if(known)st.forEach(s=>{const lv=tsRoutesFor(s.ausmt_id);const e=lv&&lv[tok];if(e){n++;bytes+=(e.bytes||0);}});
    const meta=b.querySelector?b.querySelector(".dlmeta"):null;
    if(meta)meta.textContent=!known?"":(n?"Download list · "+n+" station"+(n===1?"":"s")+(bytes?" · "+fmtBigBytes(bytes):"")+" · via an AusMT redirect to NCI":"nothing in this scope");
    _tileState(b,known?(n?"ok":"none"):"wait");
    b.setAttribute("aria-busy",known?"false":"true");
    b.title=known?(n?b.dataset.gloss+" · "+n+" station"+(n===1?"":"s")+" this deployment can hand off"
                    :(anyPublished?b.dataset.gloss:b.dataset.gloss+" · "+TS_NONE_HINT))
                 :TS_PENDING_HINT;});
  const note=document.getElementById("tsSegNote");
  if(note)note.textContent=!known?TS_PENDING_HINT+"."
    :(anyPublished?"AusMT hands these off to the archive that holds them."
                  :"Availability by level: "+TS_NONE_HINT+".");
}
// The Download block's one public painter: scope line + Level 2 rows + time-series rows. Called
// from updateSel (every selection/filter change) and the MANIFEST/TSACC hydration continuations.
function paintDownloadRows(){
  const st=scopeSel(),n=st.length;
  const line=document.getElementById("scopeLine");
  if(line)line.textContent=(typeof selected!=="undefined"&&selected.size)
    ?"For the "+n+" selected station"+(n===1?"":"s")+":"
    :"Across "+n+" filtered station"+(n===1?"":"s")+":";
  paintL2Rows(st);
  paintTsRows(st);
}
const _tsRowsSeg=document.getElementById("tsSeg");
if(_tsRowsSeg&&_tsRowsSeg.addEventListener)_tsRowsSeg.addEventListener("click",e=>{
  const b=e.target.closest?e.target.closest("button"):null;
  if(!b||b.disabled||!b.dataset.ts)return;
  tsLevelList(b.dataset.ts);});
// One selection export, for one AusMT-derived format. Mirrors the EDI flow above step for step.
async function exportSelectionFormat(fmt){
  const C=SEL_FORMATS[fmt];
  trackSelectionZip(fmt);
  // Two-phase boot: availability IS the manifest row here, so packaging before the manifest lands would
  // report every station as having no file of this format. Await the gate.
  if(hydrating("manifest")){toast("Waiting for the download index…");}
  await MANIFEST_READY;
  const z=new JSZip(),f=z.folder(C.folder);
  const chosen=scopeSel(),have=chosen.filter(s=>selArtifact(s,fmt)),missing=chosen.filter(s=>!selArtifact(s,fmt));
  let ok=0;const included={},failed=[];toast("Packaging "+have.length+" "+C.label+" file(s)…");
  const fmtItems=have.map(s=>{const a=selArtifact(s,fmt);
    // Namespace the zip entry by survey slug, exactly as the EDI zip does: a selection can span surveys
    // that reuse a station id, which would otherwise overwrite each other inside the archive (audit M3).
    return {s,url:bulkUrl(dataUrl(a.url)),entry:(s.slug?s.slug+"/":"")+a.url.split("/").pop()};});
  const fmtBlobs=await fetchBounded(fmtItems,6,it=>it.url);
  fmtItems.forEach((it,i)=>{if(fmtBlobs[i]){f.file(it.entry,fmtBlobs[i]);ok++;included[it.s.survey]=it.s.slug?it.s.slug+"/":"";}
    else{failed.push(it.s);}});
  writeLicenseFiles(f,included);
  // The gap file. A station can be absent from this archive for two DIFFERENT reasons and they are not
  // interchangeable: its survey is not redistributable here at all (licence/embargo, the same wording and
  // the same archive pointers the EDI zip writes), or the survey IS served but this format was never
  // produced for that station. A third list records files that were served but did not come back, which
  // is a transport failure and not a statement about the corpus at all.
  const notServed=missing.filter(s=>!s.ediAvail),noFile=missing.filter(s=>s.ediAvail);
  if(missing.length||failed.length){
    const lines=[`${C.label} selection export: stations NOT included`,""];
    if(notServed.length){
      lines.push("Not redistributable via AusMT (licence/embargo). Request them from the source archive,",
        "or contact the custodian where no DOI is recorded:","");
      notServed.forEach(s=>{const m=SMETA[s.survey]||{};
        lines.push(m.doi?`  ${s.id}  (${s.survey})  ->  https://doi.org/${m.doi}`
                        :`  ${s.id}  (${s.survey})  ->  ${withheldReason(m)}`);});
      lines.push("");}
    if(noFile.length){
      lines.push(C.note+" Each of them is served in at least its source EDI; the",
        "station's Files tab in the portal lists exactly what this deployment holds for it:","");
      noFile.forEach(s=>lines.push(`  ${s.id}  (${s.survey})`));
      lines.push("");}
    if(failed.length){
      lines.push("These files ARE served but could not be fetched for this archive (network or server",
        "error). Nothing is wrong with the data; try the export again:","");
      failed.forEach(s=>lines.push(`  ${s.id}  (${s.survey})`));
      lines.push("");}
    z.file("NOT_INCLUDED_read_me.txt",lines.join("\n"));}
  if(ok===0&&!missing.length&&!failed.length){toast("Nothing to package.");return;}
  if(ok===0){z.file("README.txt",`No ${C.label} file was available for this selection; see NOT_INCLUDED_read_me.txt.`);}
  const blob=await z.generateAsync({type:"blob"});const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download=C.stem+tsUTC()+".zip";a.click();URL.revokeObjectURL(a.href);
  const skipped=missing.length+failed.length;
  toast(`Zipped ${ok} ${C.label} file(s)`+(skipped?`; ${skipped} selected station(s) not included (the zip says which and why).`:"."));}
bindClick("dlZipXml",()=>exportSelectionFormat("emtfxml"));
bindClick("dlZipH5",()=>exportSelectionFormat("mth5"));


