"use strict";
// The portal computes nothing. It loads generated JSON products (incl. survey metadata and
// build provenance). build_provenance.json is optional: older data sets still load without it.
//
// POSITIONAL CONTRACT — these files are arrays read BY INDEX (no field names). The SINGLE SOURCE is
// contract/columns.json, generated into engine/extract/_contract.py + portal/src/contract.js by
// `python contract/generate.py`; the human reference is docs/docs/developer/data-files.md. The portal
// reads columns through contract.js's NAMED index maps — r[C.*], sc[SC.*], t[T.*] — so a reorder in
// columns.json regenerates the indices and no consumer can silently lag. Legend (index -> name):
//   CAT[i]  r[]  = [0 id,1 survey,2 lat,3 lon,4 pmin,5 pmax,6 nper,7 comps,8 type,9 region,
//                   10 file,11 coord_flag,12 ausmt_id,13 edi_available,14 sha256,15 site_name]
//   SCI[i]  sc[] = [0 q,1 qb,2 rr,3 sw,4 alg,5 dim,6 p3d,7 gd,8 ellip,9 skew,10 mre,11 decades]
//   TFD[i]  t[]  = [0 periods,1 rho_xy,2 rho_yx,3 phs_xy,4 phs_yx_adj,5 tip_mag,6 pt_min,7 pt_max,
//                   8 pt_az,9 pt_beta,10 rho_xy_err,11 rho_yx_err,12 phs_xy_err,13 phs_yx_err,
//                   14 tzx_re,15 tzx_im,16 tzy_re,17 tzy_im]   (C20: 10 -> 18; tip_mag kept for compat)
// To change a column: edit contract/columns.json, run `python contract/generate.py`, then data-files.md. APPEND, never reorder.
// Data files are produced by the AusMT engine. By default they are served from the portal's own
// ./data/ directory; a deployment may instead point at a remote base (AUSMT_CONFIG.data_base_url,
// e.g. the engine's gh-pages URL) so the portal and its data can live in separate repos.
function dataUrl(name){
  // Absolute URLs pass through unchanged — manifest artifact urls built with the producer's --base-url
  // (e.g. an NCI/THREDDS host) are already absolute, so prefixing data_base_url would corrupt them
  // ("data/https://…"). This is what makes a tier migration a manifest-only change (audit M11).
  if(/^[a-z][a-z0-9+.\-]*:\/\//i.test(String(name))) return name;
  var base=(window.AUSMT_CONFIG&&window.AUSMT_CONFIG.data_base_url)||"data";
  return String(base).replace(/\/+$/,"")+"/"+name;
}
async function loadData(){const u=["catalogue.json","tf.json","sci.json","surveys.json"].map(dataUrl);
  const [c,t,s,sv]=await Promise.all(u.map(x=>fetch(x).then(r=>{if(!r.ok)throw new Error("load "+x);return r.json();})));
  let prov=null; try{const r=await fetch(dataUrl("build_provenance.json"));if(r.ok)prov=await r.json();}catch(e){}
  let coll={}; try{const r=await fetch(dataUrl("collections.json"));if(r.ok)coll=await r.json();}catch(e){}
  // manifest.json is optional (older data sets / empty builds still load): the download index.
  let man=null; try{const r=await fetch(dataUrl("manifest.json"));if(r.ok)man=await r.json();}catch(e){}
  // C12: build.json (build_id/engine_commit/source_commit/generated) — optional, tolerant of absence
  // (older builds predate it); the footer only renders the "data build …" line when this resolves.
  // No skew-handshake check here yet (comparing this against a contract hash the portal itself
  // carries) — that's C16, once the contract-hash plumbing exists.
  let build=null; try{const r=await fetch(dataUrl("build.json"));if(r.ok)build=await r.json();}catch(e){}
  // C42 Amendment A1: optional coordinate-policy markers (ausmt_id -> 'generalised'|'withheld'), emitted
  // by the engine ONLY when a survey has a non-exact station. Absent for an all-exact corpus (the common
  // case) => {} => no badges. Same tolerant-of-absence pattern as collections/manifest/build above.
  let cpol={}; try{const r=await fetch(dataUrl("coord_policy.json"));if(r.ok)cpol=await r.json();}catch(e){}
  return [c,t,s,sv,prov,coll,man,build,cpol];}

// ---- download manifest resolver (slice #4 — the distribution backbone) ------------------------
// manifest.json indexes every downloadable artifact: per-station files (EDI/EMTF-XML) and per-survey
// bundles (EDI zip / survey MTH5), each with a portal-RELATIVE url + size + sha256 + tier. The portal
// joins each url onto data_base_url via dataUrl() — so migrating a tier to NCI later is a manifest
// change with zero consumer edits. tier=nci rows carry an ABSOLUTE NCI fileServer url that dataUrl()
// passes through unchanged and renders as a live download link (url is null only if a row is unresolvable).
function mfRows(kind){return (MANIFEST&&Array.isArray(MANIFEST[kind]))?MANIFEST[kind]:[];}
function artifactsFor(ausmt_id){return mfRows("files").filter(r=>r.ausmt_id===ausmt_id&&r.url);}
function bundlesForSlug(slug){return slug?mfRows("bundles").filter(r=>r.slug===slug&&r.url):[];}
function fmtBytes(n){if(n==null)return"";if(n<1024)return n+" B";if(n<1048576)return(n/1024).toFixed(0)+" KB";return(n/1048576).toFixed(1)+" MB";}
