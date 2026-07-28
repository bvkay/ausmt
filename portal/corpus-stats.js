// Fills the About page header's corpus-totals block ("N stations · N surveys") from the SAME static data
// products the portal app reads: catalogue.json (one row per station) and surveys.json (one entry per
// survey). About does not load the app bundle, so this is a self-contained script rather than a call into
// src/data.js; it duplicates only the base-url resolution, which it must match exactly.
//
// Honest by construction. The block ships hidden and is revealed ONLY once both documents resolve to a
// non-empty corpus, so a file:// page (fetch blocked or cross-origin), a deployment whose data is not
// published yet, and an empty build all show nothing at all rather than a fabricated or "0 stations"
// total. Nothing is hard-coded: the numbers can only ever be what the served catalogue says.
//
// build.json is deliberately NOT a source here. It carries build IDENTITY (build_id, engine_commit,
// source_commit, generated) and no counts, so it cannot answer this question.
(function () {
  var el = document.getElementById("corpusCounts");
  var nSt = document.getElementById("corpusStations");
  var nSv = document.getElementById("corpusSurveys");
  if (!el || !nSt || !nSv || typeof fetch !== "function") { return; }
  // Same resolution as src/data.js dataUrl(): a deployment may publish its data elsewhere
  // (AUSMT_CONFIG.data_base_url); blank falls back to the portal's own ./data.
  var cfg = window.AUSMT_CONFIG || {};
  var base = String(cfg.data_base_url || "data").replace(/\/+$/, "");
  function get(name) {
    return fetch(base + "/" + name).then(function (r) {
      if (!r.ok) { throw new Error(name + " " + r.status); }
      return r.json();
    });
  }
  Promise.all([get("catalogue.json"), get("surveys.json")]).then(function (docs) {
    var stations = Array.isArray(docs[0]) ? docs[0].length : 0;
    var surveys = (docs[1] && typeof docs[1] === "object") ? Object.keys(docs[1]).length : 0;
    if (!stations || !surveys) { return; }        // empty build: say nothing rather than "0 · 0"
    nSt.textContent = stations.toLocaleString("en-AU");
    nSv.textContent = surveys.toLocaleString("en-AU");
    el.hidden = false;
  }).catch(function () { /* unpublished data / file:// : the block stays hidden */ });
})();
