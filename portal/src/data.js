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
// One JSON product. REQUIRED semantics: a not-ok response or unparseable body rejects, so the caller can
// decide whether that is fatal (phase 1) or a hydration failure to be reported honestly (phase 2).
function fetchJson(name){return fetch(dataUrl(name)).then(r=>{if(!r.ok)throw new Error("load "+name);return r.json();});}
// One OPTIONAL product: absence (404 / network / bad JSON) resolves to `fallback` and never rejects. This is
// the tolerant-of-absence contract build_provenance / collections / build / coord_policy / manifest have
// always had; it is factored out here only so the five of them can run CONCURRENTLY.
function fetchOptional(name,fallback){return fetchJson(name).then(v=>v,()=>fallback);}

// ---- PHASE 1: the first-paint set ---------------------------------------------------------------
// Everything the map dots, the filter rail and the survey/collection views need, and nothing else:
// catalogue.json (~320KB, REQUIRED: it IS the dots) + surveys.json (REQUIRED: the per-survey metadata
// every card and drawer header reads) + the four SMALL optionals. All SIX are issued together.
// Before this split the boot awaited a Promise.all that also carried tf.json (3.2MB raw / ~1MB gzipped,
// ~3.1s measured on a live load) and then ran the five optionals STRICTLY SEQUENTIALLY, so their five
// round trips stacked on top of that wait. Both defects die here: the dots no longer wait on the transfer
// functions, and the optionals no longer wait on each other.
async function loadPhase1(){
  const [c,sv,prov,coll,build,cpol]=await Promise.all([
    fetchJson("catalogue.json"),
    fetchJson("surveys.json"),
    fetchOptional("build_provenance.json",null),
    fetchOptional("collections.json",{}),
    // C12: build.json (build_id/engine_commit/source_commit/generated), optional and tolerant of absence
    // (older builds predate it); the footer only renders the "data build …" line when this resolves.
    // No skew-handshake check here yet (comparing this against a contract hash the portal itself
    // carries); that is C16, once the contract-hash plumbing exists.
    fetchOptional("build.json",null),
    // C42 Amendment A1: optional coordinate-policy markers (ausmt_id -> 'generalised'|'withheld'), emitted
    // by the engine ONLY when a survey has a non-exact station. Absent for an all-exact corpus (the common
    // case) => {} => no badges. Same tolerant-of-absence pattern as collections/build above.
    fetchOptional("coord_policy.json",{}),
  ]);
  return [c,sv,prov,coll,build,cpol];
}

// ---- PHASE 2: background hydration --------------------------------------------------------------
// The heavy products, issued in PARALLEL alongside phase 1 and awaited by NOBODY on the first-paint path.
// Each assigns its global and settles its own gate, so a consumer waits only for the product it actually
// reads (a station drawer's plots need tf; the Files tab needs the manifest; neither needs the other).
// Returns the three gates so a caller (and the headless drivers) can observe hydration.
function startHydration(){
  HYDR.tf="pending";HYDR.sci="pending";HYDR.manifest="pending";
  // A tf/sci FAILURE is not absence: before the phased boot these were part of the required Promise.all and
  // a bad fetch showed the load-error page. First paint no longer depends on them, so the failure is recorded
  // as "failed" and the products fall back to EMPTY arrays; the empty array keeps every positional deref
  // safe, and hydrFailed() is what the consumers render, so a broken build is never mistaken for a station
  // that genuinely has no curves.
  TF_READY=fetchJson("tf.json").then(v=>{TFD=v;HYDR.tf="ready";},()=>{TFD=[];HYDR.tf="failed";});
  SCI_READY=fetchJson("sci.json").then(v=>{SCI=v;HYDR.sci="ready";},()=>{SCI=[];HYDR.sci="failed";});
  // manifest.json is OPTIONAL by contract (older data sets / empty builds ship none), so its 404 IS the
  // honest absence (MANIFEST=null, the exact value every consumer already tolerates), not a failure state.
  MANIFEST_READY=fetchOptional("manifest.json",null).then(v=>{MANIFEST=v;HYDR.manifest="ready";});
  return [TF_READY,SCI_READY,MANIFEST_READY];
}

// ---- download manifest resolver (slice #4 — the distribution backbone) ------------------------
// manifest.json indexes every downloadable artifact: per-station files (EDI/EMTF-XML) and per-survey
// bundles (EDI zip / survey MTH5), each with a portal-RELATIVE url + size + sha256 + tier. The portal
// joins each url onto data_base_url via dataUrl() — so migrating a tier to NCI later is a manifest
// change with zero consumer edits. tier=nci rows carry an ABSOLUTE NCI fileServer url that dataUrl()
// passes through unchanged and renders as a live download link (url is null only if a row is unresolvable).
function mfRows(kind){return (MANIFEST&&Array.isArray(MANIFEST[kind]))?MANIFEST[kind]:[];}
// ONE ausmt_id -> served-rows index over files[], built once per manifest and shared by every consumer.
// artifactsFor used to FILTER the whole files[] array on every call, which is nothing for a drawer opened
// once and quadratic for the selection panel: paintExportSizes asks it per selected station on every
// keystroke, so at corpus scale (3k stations selected, ~9k manifest rows) one repaint walked ~27M rows and
// took 670ms, on the input path. Measured 18ms at 500 stations, 77ms at 1000, 290ms at 2000: the cost grew
// with the SQUARE of the corpus, so it was invisible in every fixture and worst on the full selection.
//
// The cache is keyed on the MANIFEST OBJECT ITSELF, not on a "loaded" flag or a reset call. MANIFEST is
// assigned whole (data.js hydration, and the drivers/harnesses that poke it directly) and never mutated in
// place, so identity is exactly the invalidation signal, and a caller that swaps the manifest cannot forget
// to invalidate a cache it does not know exists. A cache that had to be reset by hand would go stale
// silently, showing one manifest's files under another's, which is worse than the cost it saves.
//
// The returned array is SHARED and must be treated as read-only: every caller reads it with find/some/
// filter. Copying per call would defeat the point on the very path this exists for.
let _MF_IDX=null,_MF_IDX_SRC;
function mfFileIndex(){
  if(_MF_IDX&&_MF_IDX_SRC===MANIFEST)return _MF_IDX;
  const ix=new Map();
  mfRows("files").forEach(r=>{if(!r||!r.url)return;
    const cur=ix.get(r.ausmt_id);if(cur)cur.push(r);else ix.set(r.ausmt_id,[r]);});
  _MF_IDX=ix;_MF_IDX_SRC=MANIFEST;return ix;}
function artifactsFor(ausmt_id){return mfFileIndex().get(ausmt_id)||[];}
function bundlesForSlug(slug){return slug?mfRows("bundles").filter(r=>r.slug===slug&&r.url):[];}
function fmtBytes(n){if(n==null)return"";if(n<1024)return n+" B";if(n<1048576)return(n/1024).toFixed(0)+" KB";return(n/1048576).toFixed(1)+" MB";}
