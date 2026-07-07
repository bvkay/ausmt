// Renders the build/version label into the header chip on every page. The values come from the
// centralised config (config.js, generated from portal.config.yaml) — this file derives the label and
// fills any element carrying the data-ver-chip attribute. To change the version, edit
// portal.config.yaml and regenerate config.js; do not hard-code version strings here or in the HTML.
(function () {
  var c = window.AUSMT_CONFIG || { short_name: "AusMT", version: "0.0.0", schema: "MTCAT", schema_version: "1.0" };
  window.AUSMT_VERSION = {
    version: c.version, schema: c.schema, schema_version: c.schema_version,
    label: c.short_name + " v" + c.version + " \u00b7 " + c.schema + " " + c.schema_version
  };
  function fill() {
    var lbl = window.AUSMT_VERSION.label;
    var nodes = document.querySelectorAll("[data-ver-chip]");
    for (var i = 0; i < nodes.length; i++) { nodes[i].textContent = lbl; }
  }
  if (document.readyState !== "loading") { fill(); }
  else { document.addEventListener("DOMContentLoaded", fill); }
})();

