// AusMT DOI citation-harvest core - the SINGLE SOURCE shared by the public Add Survey form
// (add-survey.html) and the curator metadata editor (served by the gateway at
// /gateway/curator/doi-harvest.js). See docs: portal internals, doi_harvest.js.
(function (root, factory) {
  var api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.AusmtDoiHarvest = api;
})(typeof window !== "undefined" ? window : null, function () {
  "use strict";
  // DOI normalisation: fold a pasted resolver URL down to the bare DOI the validator records. See docs:
  // portal internals, doi_harvest.js.
  function normalizeDoi(s) {
    const v = String(s == null ? "" : s).trim();
    const m = /^https?:\/\/(?:www\.)?(?:dx\.)?doi\.org\/(.+)$/i.exec(v);
    return m ? m[1].trim() : v;
  }
  // looksLikeDoi mirrors the validator's DOI shape (10.NNNN/suffix) AFTER folding a resolver URL, so a
  // pasted https://doi.org/10.x/y still triggers a harvest.
  function looksLikeDoi(s) {
    return /^10\.\d{4,9}\/\S+$/.test(normalizeDoi(String(s == null ? "" : s).trim()));
  }
  // First non-empty string of an array-or-scalar registry field (Crossref wraps title/container-title in
  // arrays; DataCite nests them). Never throws; returns "" when nothing usable.
  function firstRegStr(v) {
    if (Array.isArray(v)) { for (const x of v) { const s = String(x == null ? "" : x).trim(); if (s) return s; } return ""; }
    return String(v == null ? "" : v).trim();
  }
  // Fold a registry author/creator record ([{family|familyName, given|givenName, name}]) into a compact
  // "Family I, Family I" string (family name + given initials). See docs: portal internals, doi_harvest.js.
  function foldRegAuthors(list) {
    return (Array.isArray(list) ? list : []).map(a => {
      a = a || {};
      const fam = String(a.family != null ? a.family : (a.familyName != null ? a.familyName : "")).trim();
      const giv = String(a.given != null ? a.given : (a.givenName != null ? a.givenName : "")).trim();
      if (!fam && !giv) return String(a.name == null ? "" : a.name).trim();   // corporate/organisation author
      const ini = giv.split(/[\s.\-]+/).filter(Boolean).map(w => w[0].toUpperCase()).join("");
      return (fam + (ini ? " " + ini : "")).trim();
    }).filter(Boolean).join(", ");
  }
  // Parse a Crossref /works/<doi> payload ({message:{...}}) to the emission shape {author,year,title,
  // journal,doi}. Best-effort and total: a missing key yields "" for that field, a non-object payload
  // yields null (a miss, not a crash). See docs: portal internals, doi_harvest.js.
  function parseCrossref(data, doi) {
    try {
      const m = data && data.message;
      if (!m || typeof m !== "object") return null;
      const title = firstRegStr(m.title);
      const journal = firstRegStr(m["container-title"]);
      let year = "";
      const dp = m.issued && m.issued["date-parts"];
      if (Array.isArray(dp) && Array.isArray(dp[0]) && dp[0][0] != null) year = String(dp[0][0]).trim();
      const author = foldRegAuthors(m.author);
      const d = normalizeDoi(String(m.DOI != null ? m.DOI : (doi || "")).trim());
      if (!title && !author && !d) return null;   // nothing usable -> treat as a miss
      return { author: author, year: year, title: title, journal: journal, doi: d };
    } catch (e) { return null; }
  }
  // Parse a DataCite /dois/<doi> payload ({data:{attributes:{...}}}) to the same emission shape.
  // titles[].title -> title, creators[] -> author, publicationYear -> year, container.title or publisher ->
  // journal (dataset DOIs carry a publisher, not a journal). See docs: portal internals, doi_harvest.js.
  function parseDatacite(data, doi) {
    try {
      const a = data && data.data && data.data.attributes;
      if (!a || typeof a !== "object") return null;
      const title = firstRegStr((Array.isArray(a.titles) ? a.titles : []).map(t => t && t.title));
      const author = foldRegAuthors(a.creators);
      const year = a.publicationYear != null ? String(a.publicationYear).trim() : "";
      const container = a.container && typeof a.container === "object" ? a.container.title : a.container;
      const publisher = a.publisher && typeof a.publisher === "object" ? a.publisher.name : a.publisher;
      const journal = String(firstRegStr(container) || firstRegStr(publisher) || "").trim();
      const d = normalizeDoi(String(a.doi != null ? a.doi : (doi || "")).trim());
      if (!title && !author && !d) return null;
      return { author: author, year: year, title: title, journal: journal, doi: d };
    } catch (e) { return null; }
  }
  // Compact human citation for a read-only preview line: authors, year, title, journal, with three
  // or more authors collapsed. See docs: portal internals, doi_harvest.js.
  function formatCitation(p) {
    p = p || {};
    const full = String(p.author == null ? "" : p.author).trim();
    let authors = "";
    if (full) {
      const parts = full.split(",").map(s => s.trim()).filter(Boolean);
      authors = parts.length > 2 ? (parts.slice(0, 2).join(", ") + ", et al.") : parts.join(", ");
    }
    const year = String(p.year == null ? "" : p.year).trim();
    const title = String(p.title == null ? "" : p.title).trim();
    const journal = String(p.journal == null ? "" : p.journal).trim();
    let s = "";
    if (authors) s += authors + " ";
    if (year) s += "(" + year + "). ";
    if (title) s += title + (/[.?!]$/.test(title) ? "" : ".") + " ";
    if (journal) s += journal + (/[.?!]$/.test(journal) ? "" : ".");
    s = s.trim();
    return s || String(p.doi == null ? "" : p.doi).trim();
  }
  // Harvest one DOI's metadata: Crossref first (journal papers), DataCite on any Crossref miss/404 (dataset
  // DOIs). Async and PURE of the DOM; the fetch implementation is INJECTED so tests stub it and never touch
  // the real network. See docs: portal internals, doi_harvest.js.
  async function harvestDoi(doi, fetchImpl) {
    const d = normalizeDoi(String(doi == null ? "" : doi).trim());
    if (!looksLikeDoi(d)) return { ok: false, reason: "not-a-doi", doi: d, pub: { author: "", year: "", title: "", journal: "", doi: d } };
    const enc = encodeURIComponent(d);
    const tryJson = async url => { try { const r = await fetchImpl(url); if (!r || !r.ok) return null; return await r.json(); } catch (e) { return null; } };
    let partial = null;
    const cj = await tryJson("https://api.crossref.org/works/" + enc);
    if (cj) { const p = parseCrossref(cj, d); if (p && p.title) return { ok: true, source: "crossref", pub: p }; if (p) partial = partial || p; }
    const dj = await tryJson("https://api.datacite.org/dois/" + enc);
    if (dj) { const p = parseDatacite(dj, d); if (p && p.title) return { ok: true, source: "datacite", pub: p }; if (p) partial = partial || p; }
    return { ok: false, reason: partial ? "thin" : "miss", doi: d, pub: partial || { author: "", year: "", title: "", journal: "", doi: d } };
  }
  return {
    normalizeDoi: normalizeDoi, looksLikeDoi: looksLikeDoi, firstRegStr: firstRegStr,
    foldRegAuthors: foldRegAuthors, parseCrossref: parseCrossref, parseDatacite: parseDatacite,
    formatCitation: formatCitation, harvestDoi: harvestDoi,
  };
});
