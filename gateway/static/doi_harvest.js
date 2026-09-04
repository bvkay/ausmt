// AusMT DOI citation-harvest core - the SINGLE SOURCE shared by the public Add Survey form
// (add-survey.html) and the curator metadata editor (served by the gateway at
// /gateway/curator/doi-harvest.js). CONTRIBUTOR-CREDIT-SPEC (§6, curator DOI harvest): the curator
// publications rows reuse THIS code rather than duplicating it, so a fix to the registry parsing lands
// on both surfaces at once. Both consumers load it as a classic external script tag (it attaches to
// window.AusmtDoiHarvest); node tests require() it (module.exports). It is PURE of the DOM and, for
// harvestDoi, of a live network (the fetch implementation is injected), so the whole module is unit-
// tested with a stubbed fetch and never touches the real registries in CI.
//
// The gateway ships a BYTE-IDENTICAL copy at gateway/static/doi_harvest.js (the gateway app image is
// content-blind - it cannot read portal/ at runtime); a gateway parity test pins the two equal so the
// shared code cannot drift between the two served copies.
(function (root, factory) {
  var api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.AusmtDoiHarvest = api;
})(typeof window !== "undefined" ? window : null, function () {
  "use strict";
  // DOI normalisation: fold a pasted resolver URL down to the bare DOI the validator records. Strips
  // an http/https doi.org or dx.doi.org (optional www.) resolver prefix and returns the bare 10.x/y
  // suffix; a bare DOI (no resolver prefix) and any non-DOI string are returned UNCHANGED. Only doi.org
  // resolver URLs are folded, a URL-typed identifier row keeps its URL.
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
  // "Family I, Family I" string (family name + given initials). An organisation author (no family/given, a
  // bare `name`) rides through verbatim. The FULL author list is kept (no data loss); formatCitation does
  // the "et al." truncation for the compact preview only.
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
  // yields null (a miss, not a crash). Journal is container-title; year is issued.date-parts[0][0].
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
  // titles[].title -> title, creators[] -> author, publicationYear -> year, container.title or publisher
  // -> journal (dataset DOIs carry a publisher, not a journal). Same total/guarded posture as parseCrossref.
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
  // Compact human citation for a read-only preview line: "Kay B, Heinson G, et al. (2023). Title. Journal."
  // Three or more authors collapse to the first two + "et al." (the stored author field keeps the full
  // list). Omits any empty segment cleanly; falls back to the bare DOI when there is nothing else to show.
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
  // Harvest one DOI's metadata: Crossref first (journal papers), DataCite on any Crossref miss/404
  // (dataset DOIs). Async and PURE of the DOM; the fetch implementation is INJECTED so tests stub it and
  // never touch the real network. Returns {ok:true, source, pub} when a registry yields a record WITH A
  // TITLE (the citation's human anchor -> a confident preview). A thin record (no title) or a total miss
  // returns {ok:false, reason, pub}, where pub carries whatever partial data exists (at least the DOI) so
  // the row can expand the manual fields PREFILLED. A non-DOI string never fetches. Every fetch is
  // try/caught so a network error, a non-JSON body, or a blocked request degrades to a graceful miss.
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
