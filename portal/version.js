// Renders the build/version label into the header chip on every page. The values come from the
// centralised config (config.js, generated from portal.config.yaml) - this file derives the label and
// fills any element carrying the data-ver-chip attribute. To change the version, edit
// portal.config.yaml and regenerate config.js; do not hard-code version strings here or in the HTML.
//
// THE CONFIG-MISSING SENTINEL. If config.js did not load there is no version to render, and this file
// cannot go and read one: the MTCAT schema version lives in engine/schema/mtcat.schema.json, which a
// browser has no way to consult at page-render time, and inventing a build step for a file whose whole
// job is to be a plain <script> tag would trade the stale value for a stale pipeline. So the sentinel
// says NOTHING rather than something wrong: schema_version is null, and the chip renders the schema
// NAME with no number after it, so the label ends at "MTCAT". A missing number is self-evidently a
// missing number; a number is a claim, and the one parked here was false for two schema releases.
(function () {
  var c = window.AUSMT_CONFIG || { short_name: "AusMT", version: "0.0.0", schema: "MTCAT", schema_version: null };
  var sv = c.schema_version;                    // null/absent => render no version rather than a wrong one
  window.AUSMT_VERSION = {
    version: c.version, schema: c.schema, schema_version: sv,
    label: c.short_name + " v" + c.version + " \u00b7 " + c.schema + (sv ? " " + sv : "")
  };
  function fill() {
    var lbl = window.AUSMT_VERSION.label;
    var nodes = document.querySelectorAll("[data-ver-chip]");
    for (var i = 0; i < nodes.length; i++) { nodes[i].textContent = lbl; }
  }
  if (document.readyState !== "loading") { fill(); }
  else { document.addEventListener("DOMContentLoaded", fill); }
})();

