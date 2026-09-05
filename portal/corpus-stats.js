// Fills the About page header's corpus totals from catalogue.json and surveys.json. The block ships
// hidden and is revealed only once both resolve to a non-empty corpus, so a blocked fetch or an
// unpublished data set shows nothing rather than a zero.
// See docs: portal internals, corpus-stats.js.
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
