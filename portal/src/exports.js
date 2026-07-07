"use strict";
// Selection-scoped exports + toast. sel() reads shared ST/selected. Citation/EDI helpers are
// referenced at click time only. The strike rose is an export-style action over the selection.
// CSV/GeoJSON columns are built from the station object + the positional sci row sc[] (sc[SC.q]=q,
// sc[SC.qb]=qb, sc[SC.rr]=rr, sc[SC.sw]=sw, sc[SC.dim]=dim) — see the legend in data.js / data-files.md before
// reordering export columns.
const sel=()=>ST.filter(s=>selected.has(s.i));
function csvCell(v){v=(v==null?"":String(v));
  if(/^[=+\-@\t\r]/.test(v))v="'"+v;            // neutralise spreadsheet formula injection (=,+,-,@,tab,CR)
  return /[",\n\r]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v;}
function csvRow(arr){return arr.map(csvCell).join(",");}
function tsUTC(){return new Date().toISOString().replace(/[-:]/g,"").replace(/\.\d{3}Z$/,"Z");} // YYYYMMDDTHHMMSSZ
function save(n,t,m){const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([t],{type:m||"text/plain"}));a.download=n;a.click();URL.revokeObjectURL(a.href);}
function toast(m){const t=document.getElementById("toast");t.textContent=m;t.style.display="block";clearTimeout(toast._h);toast._h=setTimeout(()=>t.style.display="none",7000);}

// CSV rows (header + one per station). Derefs the positional sci row sc[SC.q/qb/rr/dim/sw] at THE export
// call site — extracted from the click handler so it is unit-testable: tests/test_populated_portal_smoke.py
// value-binds these columns, which is the ONLY coverage of the qb/rr/sw call sites (buildState/drawer
// don't expose them). Output is unchanged from the inline version.
function csvRows(stations){
  // C6: `license` rides with the exported rows (sourced from SMETA[survey].lic) so the rights don't get
  // stripped when a CSV of the selection is shared. Appended at the END to keep the existing positional
  // column indices (the populated-smoke value-binding test asserts ex[12..16]) stable.
  const rows=[["ausmt_id","station","country","organisation","survey","lat","lon","type","components","n_periods","period_min_s","period_max_s","quality","quality_basis","remote_ref","dimensionality","software","file","source_doi","timeseries_collection_doi","survey_version","collection","license"]];
  stations.forEach(s=>{const sc=SCI[s.i]||[];rows.push([s.ausmt_id,s.id,s.country,s.org,s.survey,s.lat,s.lon,s.type,s.comps,s.nper,s.pmin,s.pmax,sc[SC.q]??"",sc[SC.qb]==="e"?"error":"shape",sc[SC.rr]?"yes":"unknown",sc[SC.dim]||"",sc[SC.sw]||"",s.file,(SMETA[s.survey]||{}).doi||"",TS_COLLECTION.doi,(SMETA[s.survey]||{}).version||"",((SMETA[s.survey]||{}).collection||{}).id||"",(SMETA[s.survey]||{}).lic||""]);});
  return rows;
}
// C6: the LICENSE.txt content that travels inside the client-side bulk-download zip, mirroring the engine's
// build_portal.license_instrument_text — data is already client-side via SMETA, so no fetch is needed. The
// deed URL comes from the generated LICENSES.urls table (contract/licenses.json), keyed by the canonical id.
function licenseInstrumentText(m){
  const lic=(m.lic||"").trim(), canon=(LICENSES.aliases[lic.toUpperCase()]||lic).toUpperCase();
  const url=(LICENSES.urls||{})[canon]||"";
  const who=((m.cite&&m.cite.au)||m.org||"the survey custodian").trim();
  const yr=(m.dates?(m.dates.match(/\d{4}/g)||[]).slice(-1)[0]:"")||"";
  const attn=[who,yr?"("+yr+")":"",(m.cite&&m.cite.ti)||""].filter(Boolean).join(" ").trim()||who;
  const L=["AusMT survey data — licence and attribution","============================================","",
    "Licence:     "+(canon||"not stated")];
  if(url)L.push("Licence URL: "+url);
  L.push("Licensor:    "+who,"Year:        "+(yr||"not stated"),"","Attribution (cite as):","  "+attn,"",
    "This LICENSE.txt travels with the data files in this archive. The transfer functions were",
    "distributed via the AusMT portal, which serves only openly licensed Australian magnetotelluric",
    "releases; the licence above is the custodian's, set in the survey's survey.yaml. Reuse under the",
    "terms of that licence"+(url?" ("+url+").":"."),"");
  return L.join("\n");
}
document.getElementById("dlCsv").onclick=()=>{track("DownloadGenerated",{format:"csv",n:sel().length});
  save("ausmt-stations-"+tsUTC()+".csv",csvRows(sel()).map(csvRow).join("\r\n"),"text/csv");};
document.getElementById("dlGeo").onclick=()=>{track("DownloadGenerated",{format:"geojson",n:sel().length});const fc={type:"FeatureCollection",features:sel().map(s=>{const sc=SCI[s.i]||[];return{type:"Feature",geometry:{type:"Point",coordinates:[s.lon,s.lat]},
  properties:{id:s.id,ausmt_id:s.ausmt_id,country:s.country,organisation:s.org,survey:s.survey,type:s.type,components:s.comps,period_min_s:s.pmin,period_max_s:s.pmax,quality:sc[SC.q],dimensionality:sc[SC.dim],remote_ref:!!sc[SC.rr],source_doi:(SMETA[s.survey]||{}).doi||null,survey_version:(SMETA[s.survey]||{}).version||null,collection_id:((SMETA[s.survey]||{}).collection||{}).id||null,license:(SMETA[s.survey]||{}).lic||null,file:s.file}};})};  // C6: licence rides each GeoJSON feature
  save("ausmt-selection-"+tsUTC()+".geojson",JSON.stringify(fc,null,1),"application/geo+json");};
document.getElementById("dlSh").onclick=()=>{track("DownloadGenerated",{format:"geojson",n:sel().length});
  const byColl={};sel().forEach(s=>{const doi=(SMETA[s.survey]||{}).doi||TS_COLLECTION.doi;(byColl[doi]=byColl[doi]||[]).push(s);});
  const doc={
    note:"AusMT does not host raw time series. Request the levels you need from the archive(s) below; the station list lets you locate each occupation in their catalogue.",
    generated:new Date().toISOString(),
    time_series_collection:{name:TS_COLLECTION.name,doi:TS_COLLECTION.doi,landing:"https://doi.org/"+TS_COLLECTION.doi},
    archives:Object.entries(byColl).map(([doi,arr])=>({source_doi:doi,landing:"https://doi.org/"+doi,
      stations:arr.map(s=>({ausmt_id:s.ausmt_id,station:s.id,survey:s.survey,survey_version:(SMETA[s.survey]||{}).version||null,lat:s.lat,lon:s.lon}))}))
  };
  save("ausmt-archive-pointers-"+tsUTC()+".json",JSON.stringify(doc,null,2),"application/json");
  toast("Wrote pointers to where the raw time series live — AusMT does not host or fetch them itself.");};
// C22 (2026-07-07): the human-readable CITATIONS.txt line for ONE entry. When the entry has NO DOI the
// pack SAYS SO explicitly — "[no DOI assigned]" — rather than silently omitting the field (chief-architect
// ruling: a reference pack should state the absence). The .bib/.ris twins simply OMIT their doi=/DO/UR
// fields (drawer.js apa/bibtex/ris already guard on a falsy doi, d2bc616); emitting placeholder text there
// would be ingested by reference managers as real bibliographic data — the pre-C22 defect, where
// AUSMT_SELF.pb carried "(DOI to be minted per release via Zenodo)" into every no-DOI publisher field.
function citeLine(c,doi){return "  "+apa(c,doi)+(doi?"":"  [no DOI assigned]");}
document.getElementById("dlCite").onclick=async()=>{track("DownloadGenerated",{format:"ris",n:sel().length});const svs=[...new Set(sel().map(s=>s.survey))].sort();const today=new Date().toISOString().slice(0,10);
  let txt=["AusMT citation pack — generated "+today,"Stations: "+sel().length+" across "+svs.length+" survey release(s).","","== Survey source releases =="];let bib="",risT="";
  svs.forEach(sv=>{const m=SMETA[sv]||{};txt.push(citeLine(m.cite||AUSMT_SELF,m.doi));bib+=bibtex(sv.toLowerCase().replace(/[^a-z0-9]+/g,"_"),m.cite||AUSMT_SELF,m.doi)+"\n\n";risT+=ris(m.cite||AUSMT_SELF,m.doi)+"\n\n";});
  txt.push("","== Time-series collection ==",citeLine(NCI_CITE,TS_COLLECTION.doi));bib+=bibtex("nci_auscope_mt",NCI_CITE,TS_COLLECTION.doi)+"\n\n";risT+=ris(NCI_CITE,TS_COLLECTION.doi)+"\n\n";
  txt.push("","== Curated catalogue metadata (suggested) ==",citeLine(AUSMT_SELF,null));bib+=bibtex("ausmt_catalogue",AUSMT_SELF,null)+"\n";risT+=ris(AUSMT_SELF,null)+"\n";
  // C7: organisation ROR(s) — one line per custodian org that declared one, so the acknowledgement can
  // cite the organisation by its persistent identifier, not just its free-text name.
  const rors=[...new Set(svs.map(sv=>{const m=SMETA[sv]||{};return m.org_ror?`${m.org} (ROR: ${m.org_ror})`:null;}).filter(Boolean))];
  txt.push("","== Custodian organisation identifiers ==",...(rors.length?rors.map(r=>"  "+r):["  none recorded"]));
  txt.push("","== Suggested acknowledgement ==","  Transfer functions were obtained via the AusMT portal, which aggregates openly licensed","  Australian magnetotelluric releases; original custodians are cited above. AusLAMP is a","  collaboration between AuScope, Geoscience Australia, state and territory geological surveys","  and university partners, with instruments supplied through the AuScope NCRIS program.","  Time series were accessed from the NCI-AuScope Magnetotelluric Collection (doi:"+TS_COLLECTION.doi+").");
  const z=new JSZip();z.file("CITATIONS.txt",txt.join("\n"));z.file("citations.bib",bib);z.file("citations.ris",risT);
  const blob=await z.generateAsync({type:"blob"});const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="ausmt-citation-pack-"+tsUTC()+".zip";a.click();URL.revokeObjectURL(a.href);};
document.getElementById("dlZip").onclick=async()=>{track("DownloadGenerated",{format:"zip",n:sel().length});const z=new JSZip(),f=z.folder("ausmt_edis");
  const chosen=sel(),avail=chosen.filter(s=>s.ediAvail),unavail=chosen.filter(s=>!s.ediAvail);
  let ok=0;const included={};toast("Packaging "+avail.length+" redistributable EDI(s)…");   // included: survey -> zip subdir
  for(const s of avail){try{const ea=(typeof artifactsFor==="function"?artifactsFor(s.ausmt_id):[]).find(a=>a.format==="edi");
    const u=ea?dataUrl(ea.url):dataUrl("edi/"+s.file);   // manifest url (slug-namespaced) or legacy flat path
    // Namespace the zip entry by survey slug too: a selection can span surveys that reuse an EDI basename
    // (e.g. two surveys with 01.edi), which would otherwise overwrite each other inside the zip (audit M3).
    const entry=(s.slug?s.slug+"/":"")+s.file;
    const r=await fetch(u);if(!r.ok)throw 0;f.file(entry,await r.blob());ok++;included[s.survey]=s.slug?s.slug+"/":"";}catch(e){}}
  // C6: rights travel with the bytes — one LICENSE.txt per included survey, beside its EDIs (same slug
  // namespace). Built entirely from client-side SMETA (no fetch), mirroring the served-zip instrument.
  Object.keys(included).forEach(sv=>f.file(included[sv]+"LICENSE.txt",licenseInstrumentText(SMETA[sv]||{})));
  if(unavail.length){const lines=["These selected stations are NOT redistributable via AusMT (licence/embargo).",
    "Request them from the source archive:",""].concat(unavail.map(s=>{const m=SMETA[s.survey]||{};
    // C7: m.doi (the survey's OWN dataset DOI) is the honest TF source archive. There is no substitute
    // when it is absent — TS_COLLECTION is the raw time-series collection, not a TF source archive, and
    // citing it here would mislabel a different dataset as "the source archive" (the pre-C7 defect).
    return m.doi?`${s.id}  (${s.survey})  ->  https://doi.org/${m.doi}`
                :`${s.id}  (${s.survey})  ->  no dataset DOI recorded — contact the custodian organisation (${m.org||"unknown"})`;}));
    z.file("NOT_INCLUDED_request_from_archive.txt",lines.join("\n"));}
  if(ok===0&&!unavail.length){toast("Nothing to package.");return;}
  if(ok===0){z.file("README.txt","No EDIs were redistributable in this selection; see the archive pointers file.");}
  const blob=await z.generateAsync({type:"blob"});const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="ausmt-selection-edis-"+tsUTC()+".zip";a.click();URL.revokeObjectURL(a.href);
  toast(`Zipped ${ok} EDI(s)`+(unavail.length?`; ${unavail.length} not redistributable (archive pointers included).`:"."));};
document.getElementById("strike").onclick=()=>{
  const az=[];sel().forEach(s=>{const pt=TFD[s.i];if(!pt||!pt[T.pt_az])return;pt[T.pt_az].forEach((a,k)=>{if(a!=null&&pt[T.pt_beta][k]!=null&&Math.abs(pt[T.pt_beta][k])<5)az.push(((a%180)+180)%180);});});
  if(az.length<5){toast("Not enough low-skew phase-tensor azimuths in the selection for a strike estimate.");return;}
  const bins=18,counts=new Array(bins).fill(0);az.forEach(a=>counts[Math.min(bins-1,Math.floor(a/(180/bins)))]++);
  const mx=Math.max(...counts),R=120,cx=150,cy=150;let wed="";
  for(let k=0;k<bins;k++){for(const off of [0,180]){const a0=(k*(180/bins)+off)*Math.PI/180,a1=((k+1)*(180/bins)+off)*Math.PI/180,r=20+counts[k]/mx*(R-20);
    const x0=cx+r*Math.sin(a0),y0=cy-r*Math.cos(a0),x1=cx+r*Math.sin(a1),y1=cy-r*Math.cos(a1);
    wed+=`<path d="M${cx},${cy} L${x0.toFixed(1)},${y0.toFixed(1)} A${r},${r} 0 0 1 ${x1.toFixed(1)},${y1.toFixed(1)} Z" fill="#E0782F" fill-opacity=".55" stroke="#13202B" stroke-width=".5"/>`;}}
  const svg=`<svg width="300" height="300" xmlns="http://www.w3.org/2000/svg"><circle cx="${cx}" cy="${cy}" r="${R}" fill="none" stroke="#2E4254"/><line x1="${cx}" y1="${cy-R}" x2="${cx}" y2="${cy+R}" stroke="#2E4254"/><line x1="${cx-R}" y1="${cy}" x2="${cx+R}" y2="${cy}" stroke="#2E4254"/><text x="${cx}" y="18" fill="#8FA3B0" font-size="11" text-anchor="middle" font-family="monospace">N</text>${wed}</svg>`;
  drawer.innerHTML=`<div class="dhead"><span class="sid">Strike rose</span><button class="close" aria-label="Close">✕</button></div>`+
   `<div class="dsub">${sel().length} stations · ${az.length} low-skew (|β|&lt;5°) PT azimuths · 180° ambiguous</div><div style="display:flex;justify-content:center;margin-top:14px">${svg}</div>`+
   `<div class="dim" style="margin-top:12px">Geoelectric strike estimated from phase-tensor major-axis azimuths where skew is small. The 90° ambiguity inherent to strike is not resolved here; combine with tipper induction arrows to break it.</div>`;
  drawer.classList.add("open");};
