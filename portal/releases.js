// Fills the Releases page from the served index and each release's own document, hard-coding nothing.
// Absent, unreadable and empty are DIFFERENT states, no link is built for an unconfirmed file, and a
// DOI is either resolvable or plain pending text. See docs: portal internals, releases.js.
(function () {
  var loading = document.getElementById("relLoading");
  var empty = document.getElementById("relEmpty");
  var failed = document.getElementById("relError");
  var list = document.getElementById("relList");
  if (!loading || !empty || !failed || !list || typeof fetch !== "function") { return; }

  // Same resolution as src/data.js dataUrl() and corpus-stats.js: a deployment may publish its data
  // elsewhere (AUSMT_CONFIG.data_base_url); blank falls back to the portal's own ./data.
  var cfg = window.AUSMT_CONFIG || {};
  var base = String(cfg.data_base_url || "data").replace(/\/+$/, "");

  // The three catalogue documents a release freezes, in the order cut_release.py copies them.
  var CATALOGUE = ["mtcat.json", "surveys.json", "manifest.json"];

  function show(node) {
    loading.hidden = true;
    empty.hidden = true;
    failed.hidden = true;
    list.hidden = true;
    node.hidden = false;
  }

  // Name the exact document that was requested, on both the empty and the unreadable state, and ship
  // hidden so the line can only ever state a URL that was really requested.
  // See docs: portal internals, releases.js.
  function probe(prefix, url) {
    var code = document.getElementById(prefix + "Path");
    var line = document.getElementById(prefix + "Probe");
    if (!code || !line) { return; }
    code.textContent = url;
    line.hidden = false;
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text !== undefined && text !== null) { n.textContent = String(text); }
    return n;
  }

  // --- tolerant readers ---------------------------------------------------------------------------

  // "<tag>/" relative to the data root. The index writes `path`; a hand-edited row without one still
  // resolves, because the on-disk layout is releases/<tag>/ by construction.
  function relPath(row) {
    var p = String(row.path || ("releases/" + row.tag + "/")).replace(/^\/+/, "");
    return p.replace(/\/*$/, "/");
  }

  function isoDate(v) {
    var m = /^(\d{4}-\d{2}-\d{2})/.exec(String(v == null ? "" : v));
    return m ? m[1] : null;
  }

  function year(v) {
    var m = /^(\d{4})/.exec(String(v == null ? "" : v));
    return m ? m[1] : null;
  }

  function count(v) {
    return (typeof v === "number" && isFinite(v)) ? v.toLocaleString("en-AU") : null;
  }

  function humanSize(b) {
    if (typeof b !== "number" || !isFinite(b) || b < 0) { return null; }
    if (b < 1024) { return b + " B"; }
    if (b < 1024 * 1024) { return (b / 1024).toFixed(1) + " KB"; }
    return (b / (1024 * 1024)).toFixed(1) + " MB";
  }

  // Strip a doi.org resolver prefix so a bare DOI and a resolver URL are handled identically. Mirrors
  // normalise_doi() in engine/extract/cut_release.py (same prefix list, same job).
  var _RESOLVERS = ["https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/",
    "doi.org/", "dx.doi.org/"];

  function bareDoi(v) {
    var s = String(v == null ? "" : v).trim();
    for (var i = 0; i < _RESOLVERS.length; i++) {
      if (s.toLowerCase().indexOf(_RESOLVERS[i]) === 0) { return s.slice(_RESOLVERS[i].length); }
    }
    return s;
  }

  // A DOI is linked only when it LOOKS like one. A stray placeholder ("tbc", "pending", an empty
  // string) must fall through to the pending text rather than become a resolver link that 404s.
  function resolvableDoi(v) {
    var d = bareDoi(v);
    return /^10\.\d{4,9}\/\S+$/.test(d) ? d : null;
  }

  // --- the citation -------------------------------------------------------------------------------

  // The citation names the contributors, the year in brackets, the portal, the release tag and
  // AuScope, and the year is omitted rather than guessed when the cut timestamp cannot be parsed.
  // See docs: portal internals, releases.js.
  function citationText(tag, cut) {
    var y = year(cut);
    return "AusMT contributors" + (y ? " (" + y + ")" : "") +
      ". AusMT Data Portal, Release " + tag + ". AuScope.";
  }

  function citationBox(tag, cut, doi) {
    var box = el("div", "cite");
    box.appendChild(el("div", "cite-label", "Cite this release"));
    box.appendChild(el("div", "cite-text", citationText(tag, cut)));

    var line = el("div", "cite-doi");
    var resolvable = resolvableDoi(doi);
    if (resolvable) {
      var a = el("a", null, "https://doi.org/" + resolvable);
      a.href = "https://doi.org/" + resolvable;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      line.appendChild(el("span", null, "DOI: "));
      line.appendChild(a);
    } else {
      // Reserved-as-text: the release exists and is citable by its frozen path today; the DOI is
      // stamped in later by `cut-release --doi`. Plain text, never an anchor.
      line.appendChild(el("span", "pending", "DOI: not yet minted"));
    }
    box.appendChild(line);
    return box;
  }

  // --- one release --------------------------------------------------------------------------------

  function idLine(parent, key, value, mono) {
    parent.appendChild(el("span", "k", key));
    parent.appendChild(el("span", mono ? "v" : null, value));
    parent.appendChild(document.createElement("br"));
  }

  function fileLink(href, label, title) {
    var a = el("a", null, label);
    a.href = href;
    if (title) { a.title = title; }
    return a;
  }

  function filesBlock(card, prefix, files) {
    var byPath = {};
    var bundles = [];
    var i;
    for (i = 0; i < files.length; i++) {
      var f = files[i];
      if (!f || typeof f.path !== "string" || !f.path) { continue; }
      if (CATALOGUE.indexOf(f.path) >= 0) { byPath[f.path] = f; } else { bundles.push(f); }
    }

    card.appendChild(el("div", "files-label", "Frozen files"));

    var links = el("div", "filelinks");
    for (i = 0; i < CATALOGUE.length; i++) {
      var doc = byPath[CATALOGUE[i]];
      if (!doc) { continue; }            // not in this release's files[]: do not offer the link
      var size = humanSize(doc.size);
      links.appendChild(fileLink(prefix + encodeURI(doc.path), doc.path,
        (size ? size : "") + (doc.sha256 ? (size ? " · " : "") + "sha256 " + doc.sha256 : "")));
    }
    if (links.childNodes.length) { card.appendChild(links); }

    if (!bundles.length) { return; }
    var det = el("details", "bundles");
    det.appendChild(el("summary", null, bundles.length + (bundles.length === 1 ? " bundle file" : " bundle files")));
    var ul = document.createElement("ul");
    for (i = 0; i < bundles.length; i++) {
      var b = bundles[i];
      var li = document.createElement("li");
      li.appendChild(fileLink(prefix + encodeURI(b.path), b.path, b.sha256 ? "sha256 " + b.sha256 : null));
      var hs = humanSize(b.size);
      if (hs) { li.appendChild(el("span", "size", hs)); }
      ul.appendChild(li);
    }
    det.appendChild(ul);
    card.appendChild(det);
  }

  function card(row, detail) {
    var doc = detail || {};
    var tag = String(row.tag);
    var cut = (doc.cut_at && doc.cut_at.cut) || row.cut;
    var c = el("article", "rel");

    var head = el("div", "rel-head");
    head.appendChild(el("div", "rel-tag", tag));
    var date = isoDate(cut);
    if (date) {
      var d = el("div", "rel-cut", "cut " + date);
      d.title = String(cut);
      head.appendChild(d);
    }
    c.appendChild(head);

    var nSv = count(doc.n_surveys !== undefined ? doc.n_surveys : row.n_surveys);
    var nSt = count(doc.n_stations !== undefined ? doc.n_stations : row.n_stations);
    if (nSv !== null || nSt !== null) {
      var corpus = el("div", "rel-corpus");
      if (nSv !== null) {
        corpus.appendChild(el("b", null, nSv));
        corpus.appendChild(el("span", null, " surveys"));
      }
      if (nSv !== null && nSt !== null) { corpus.appendChild(el("span", null, " · ")); }
      if (nSt !== null) {
        corpus.appendChild(el("b", null, nSt));
        corpus.appendChild(el("span", null, " stations"));
      }
      c.appendChild(corpus);
    }

    var note = doc.note || row.note;
    if (note) { c.appendChild(el("div", "rel-note", String(note))); }

    // Build identity. build_id is in the index row; source_commit (the corpus commit the release was
    // built from) is only in release.json, so it appears once that document has been read.
    var ids = el("div", "rel-ids");
    var buildId = doc.build_id || row.build_id;
    if (buildId) { idLine(ids, "build id", String(buildId), true); }
    if (detail) {
      if (doc.source_commit) {
        idLine(ids, "source commit", String(doc.source_commit), true);
      } else {
        idLine(ids, "source commit", "not recorded by this build", false);
      }
    }
    if (ids.childNodes.length) { c.appendChild(ids); }

    c.appendChild(citationBox(tag, cut, doc.doi !== undefined && doc.doi !== null ? doc.doi : row.doi));

    if (detail && Array.isArray(doc.files)) {
      filesBlock(c, base + "/" + relPath(row), doc.files);
    } else {
      c.appendChild(el("div", "detail-warn",
        "The release document at " + relPath(row) + "release.json could not be read from this " +
        "deployment, so this release's file list and source commit are not shown."));
    }
    return c;
  }

  // --- fetching -----------------------------------------------------------------------------------

  var INDEX_URL = base + "/releases/releases.json";

  // Resolves to {state:"ok", doc} / {state:"absent"} / {state:"unreadable"}. It never rejects, so the
  // caller can act on the distinction rather than on an exception it cannot classify.
  function getIndex() {
    return fetch(INDEX_URL).then(function (r) {
      if (r.status === 404) { return { state: "absent" }; }
      if (!r.ok) { return { state: "unreadable" }; }
      return r.json().then(function (doc) { return { state: "ok", doc: doc }; },
        function () { return { state: "unreadable" }; });
    }, function () { return { state: "unreadable" }; });
  }

  // One release's own document, or null when it cannot be read. Never rejects: a single unreadable
  // release must not blank the whole page.
  function getDetail(row) {
    return fetch(base + "/" + relPath(row) + "release.json").then(function (r) {
      if (!r.ok) { return null; }
      return r.json().then(function (d) {
        return (d && typeof d === "object" && !Array.isArray(d)) ? d : null;
      }, function () { return null; });
    }, function () { return null; });
  }

  function showEmpty() { probe("relEmpty", INDEX_URL); show(empty); }
  function showFailed() { probe("relError", INDEX_URL); show(failed); }

  getIndex().then(function (res) {
    if (res.state === "absent") { showEmpty(); return; }
    if (res.state !== "ok") { showFailed(); return; }

    var doc = res.doc;
    if (!doc || typeof doc !== "object" || !Array.isArray(doc.releases)) {
      showFailed();                 // served, but not a releases index: say so, do not say "none"
      return;
    }
    var rows = doc.releases.filter(function (r) {
      return r && typeof r === "object" && typeof r.tag === "string" && r.tag;
    });
    if (!rows.length) { showEmpty(); return; }

    return Promise.all(rows.map(getDetail)).then(function (details) {
      for (var i = 0; i < rows.length; i++) { list.appendChild(card(rows[i], details[i])); }
      show(list);
    });
  }).catch(function () { showFailed(); });
})();
