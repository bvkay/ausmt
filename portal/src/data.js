"use strict";
// The portal computes nothing. It loads generated JSON products. See docs: portal internals, data.js.
function dataUrl(name){
  // Absolute URLs pass through unchanged — manifest artifact urls built with the producer's --base-url
  // (e.g. an NCI/THREDDS host) are already absolute, so prefixing data_base_url would corrupt them
  // ("data/https://…"). This is what makes a tier migration a manifest-only change.
  if(/^[a-z][a-z0-9+.\-]*:\/\//i.test(String(name))) return name;
  var base=(window.AUSMT_CONFIG&&window.AUSMT_CONFIG.data_base_url)||"data";
  return String(base).replace(/\/+$/,"")+"/"+name;
}
// One JSON product. REQUIRED semantics: a not-ok response or unparseable body rejects, so the caller can
// decide whether that is fatal (phase 1) or a hydration failure to be reported honestly (phase 2).
function fetchJson(name,opts){return fetch(dataUrl(name),opts).then(r=>{if(!r.ok)throw new Error("load "+name);return r.json();});}
// Hydration fetches carry the low priority hint: they share the connection with anything the user does next
// (a drawer open, a tile fetch), and none of them is awaited on the first-paint path. See docs: portal
// internals, data.js.
var FETCH_LOW={priority:"low"};
// One OPTIONAL product: absence (404 / network / bad JSON) resolves to `fallback` and never rejects. This is
// the tolerant-of-absence contract build_provenance / collections / build / coord_policy / manifest have
// always had; it is factored out here only so the five of them can run CONCURRENTLY.
function fetchOptional(name,fallback,opts){return fetchJson(name,opts).then(v=>v,()=>fallback);}

// ---- PHASE 1: the first-paint set ---------------------------------------------------------------
// Everything the map dots, the filter rail and the survey/collection views need, and nothing else:
// catalogue.json (~320KB) is REQUIRED. See docs: portal internals, data.js.
async function loadPhase1(){
  const [c,sv,prov,coll,build,cpol]=await Promise.all([
    fetchJson("catalogue.json"),
    fetchJson("surveys.json"),
    fetchOptional("build_provenance.json",null),
    fetchOptional("collections.json",{}),
    // Build.json (build_id/engine_commit/source_commit/generated), optional and tolerant of absence (older
    // builds predate it); the footer only renders the "data build …" line when this resolves. See docs:
    // portal internals, data.js.
    fetchOptional("build.json",null),
    // Optional coordinate-policy markers (ausmt_id -> 'generalised'|'withheld'), emitted by the engine ONLY
    // when a survey has a non-exact station. See docs: portal internals, data.js.
    fetchOptional("coord_policy.json",{}),
  ]);
  return [c,sv,prov,coll,build,cpol];
}

// ---- PHASE 2: background hydration -------------------------------------------------------------- The
// heavy products. See docs: portal internals, data.js.
function startHydration(){
  HYDR.tf="pending";HYDR.sci="pending";HYDR.manifest="pending";HYDR.tsaccess="pending";
  // A tf/sci FAILURE is not absence. See docs: portal internals, data.js.
  TF_READY=fetchJson("tf.json",FETCH_LOW).then(v=>{TFD=v;HYDR.tf="ready";},()=>{TFD=[];HYDR.tf="failed";});
  SCI_READY=fetchJson("sci.json",FETCH_LOW).then(v=>{SCI=v;HYDR.sci="ready";},()=>{SCI=[];HYDR.sci="failed";});
  // manifest.json is OPTIONAL by contract (older data sets / empty builds ship none), so its 404 IS the
  // honest absence (MANIFEST=null, the exact value every consumer already tolerates), not a failure state.
  MANIFEST_READY=fetchOptional("manifest.json",null,FETCH_LOW).then(v=>{MANIFEST=v;HYDR.manifest="ready";});
  // ts_access.json is OPTIONAL by contract - the engine writes it only when the register projects at least
  // one open, verified route, so a 404 IS the honest absence and there is no "failed" state to report. See
  // docs: portal internals, data.js.
  TSACC_READY=fetchOptional("ts_access.json",{},FETCH_LOW).then(v=>{TSACC=v||{};HYDR.tsaccess="ready";});
  return [TF_READY,SCI_READY,MANIFEST_READY,TSACC_READY];
}

// ---- download manifest resolver: the distribution backbone -----------------------------------
// manifest.json indexes every downloadable artifact. See docs: portal internals, data.js.
function mfRows(kind){return (MANIFEST&&Array.isArray(MANIFEST[kind]))?MANIFEST[kind]:[];}
// ONE ausmt_id -> served-rows index over files[], built once per manifest and shared by every consumer. See
// docs: portal internals, data.js.
let _MF_IDX=null,_MF_IDX_SRC;
function mfFileIndex(){
  if(_MF_IDX&&_MF_IDX_SRC===MANIFEST)return _MF_IDX;
  const ix=new Map();
  mfRows("files").forEach(r=>{if(!r||!r.url)return;
    const cur=ix.get(r.ausmt_id);if(cur)cur.push(r);else ix.set(r.ausmt_id,[r]);});
  _MF_IDX=ix;_MF_IDX_SRC=MANIFEST;return ix;}
function artifactsFor(ausmt_id){return mfFileIndex().get(ausmt_id)||[];}
function bundlesForSlug(slug){return slug?mfRows("bundles").filter(r=>r.slug===slug&&r.url):[];}
// ---- the time-series hand-off index ---------------------------------------------------------------
// ts_access.json indexes the archive routes this deployment may hand a reader off to: {ausmt_id: {level
// token: {bytes, url_path}}}. See docs: portal internals, data.js.
function tsAccessKnown(){return TSACC!==null;}
function tsRoutesFor(ausmt_id){return (TSACC&&TSACC[ausmt_id])||null;}
// The route the reader is handed: the one string carrying survey/station/level into the front-door
// log, so measurement needs no beacon and no track call. The edge 302s what its table holds and
// 404s the rest, so a gated station cannot be reached by constructing a path; no slug, no route.
function tsGoRoute(s,level){
  if(!s||!s.slug||!s.id||!level)return null;
  return location.origin+"/go/ts/"+encodeURIComponent(s.slug)+"/"+encodeURIComponent(s.id)+"/"+encodeURIComponent(level);}
// The archive's own address for one register url_path (the reference field beside the route). See docs:
// portal internals, data.js.
const TS_FILESERVER="https://thredds.nci.org.au/thredds/fileServer/";
// The `u` flag is load-bearing, not tidiness: without it the class matches per UTF-16 CODE UNIT, so a code
// point above the BMP arrives as a lone surrogate and encodeURIComponent throws URIError - which, from
// #dlTs. See docs: portal internals, data.js.
function tsArchiveUrl(p){return TS_FILESERVER+String(p==null?"":p).trim().replace(/^\/+/,"")
  .replace(/[^A-Za-z0-9_.~/-]/gu,c=>{const e=encodeURIComponent(c);
    return e===c?"%"+c.charCodeAt(0).toString(16).toUpperCase():e;});}
// Archive-scale sizes: fmtBytes stops at MB (right for served files, wrong for a 9.87 GB hand-off
// reading "9411.6 MB"). Identical rounding at every shared step, three more units above.
function fmtBigBytes(n){if(n==null)return"";
  const u=["B","KB","MB","GB","TB"];let i=0,v=Number(n);
  while(v>=1024&&i<u.length-1){v/=1024;i++;}
  return (i===0?String(v):(i===1?v.toFixed(0):v.toFixed(1)))+" "+u[i];}
function fmtBytes(n){if(n==null)return"";if(n<1024)return n+" B";if(n<1048576)return(n/1024).toFixed(0)+" KB";return(n/1048576).toFixed(1)+" MB";}
