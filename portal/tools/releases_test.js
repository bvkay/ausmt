"use strict";
// Behavioural driver for the Releases page. Loads the REAL releases.html into jsdom, runs the REAL
// releases.js against a stubbed fetch, and asserts what the page states in each of the situations a
// reader can actually land in. Mirrors tools/corpus_stats_test.js (same jsdom + vm idiom).
//
// The page's whole job is to be citable and honest, so the assertions are split accordingly:
//
//   STRUCTURE   a populated index renders one card per release carrying the tag, the cut date, the
//               corpus counts, the build id, the source commit, a citation box, and links built from
//               the release's own files[] block (catalogue documents + every bundle).
//   CITATION    the reference line is exactly the agreed form, and the identifier under it is either a
//               resolvable doi.org LINK or the plain TEXT "DOI: not yet minted" - never an anchor
//               pointing at a DOI that does not resolve.
//   HONESTY     absent-or-empty (no releases published) and unreadable (this request could not find
//               out) are different states with different words. A rejected fetch, a 500 and a
//               malformed document must NOT be reported as "no releases cut yet", and an unreadable
//               per-release document must not produce file links that would 404.
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const { JSDOM } = require("jsdom");

const PORTAL = path.resolve(__dirname, "..");
const SCRIPT = fs.readFileSync(path.join(PORTAL, "releases.js"), "utf8");
const HTML = fs.readFileSync(path.join(PORTAL, "releases.html"), "utf8");

function die(msg) { console.error("RELEASES FAILED: " + msg); process.exit(1); }
function ok(cond, msg) { if (!cond) die(msg); }

// One run: fresh DOM from releases.html, install `fetchImpl`, execute releases.js, drain microtasks,
// then hand back a queryable view of the page.
async function run(fetchImpl, config) {
  const dom = new JSDOM(HTML, { url: "http://localhost/", runScripts: "outside-only" });
  const win = dom.window;
  win.AUSMT_CONFIG = config || { data_base_url: "" };
  win.fetch = fetchImpl;
  vm.runInContext(SCRIPT, dom.getInternalVMContext());
  // The chain is index fetch -> json -> Promise.all(per-release fetch -> json) -> render. Drain
  // generously rather than counting ticks, so adding a link to the chain cannot silently pass.
  for (let i = 0; i < 40; i++) { await Promise.resolve(); }

  const doc = win.document;
  const state = (id) => {
    const n = doc.getElementById(id);
    ok(n !== null, "releases.html is missing #" + id);
    return { hidden: n.hidden, text: n.textContent.replace(/\s+/g, " ").trim() };
  };
  return {
    doc,
    loading: state("relLoading"),
    empty: state("relEmpty"),
    error: state("relError"),
    list: state("relList"),
    emptyMsg: doc.getElementById("relEmptyMsg").textContent.replace(/\s+/g, " ").trim(),
    emptyProbe: { hidden: doc.getElementById("relEmptyProbe").hidden,
      url: doc.getElementById("relEmptyPath").textContent },
    errorProbe: { hidden: doc.getElementById("relErrorProbe").hidden,
      url: doc.getElementById("relErrorPath").textContent },
    cards: Array.from(doc.querySelectorAll("#relList article.rel")),
  };
}

function txt(node, sel) {
  const n = node.querySelector(sel);
  return n === null ? null : n.textContent.replace(/\s+/g, " ").trim();
}
function hrefs(node, sel) {
  return Array.from(node.querySelectorAll(sel)).map((a) => a.getAttribute("href"));
}
function jsonOk(body) { return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) }); }
function status(code) { return Promise.resolve({ ok: false, status: code, json: () => Promise.reject(new Error("no body")) }); }

// --- fixtures: exactly the documents engine/extract/cut_release.py writes -------------------------

const INDEX = {
  schema: "ausmt-releases",
  version: "1.0",
  updated_at: "2026-07-28T14:08:34Z",
  releases: [
    { tag: "2026-Q3", cut: "2026-07-28T14:08:34Z", doi: null, note: null,
      build_id: "20260728T010203Z-ab12cd3", n_surveys: 21, n_stations: 1418, path: "releases/2026-Q3/" },
    { tag: "2026-Q2", cut: "2026-04-14T09:00:00Z", doi: "10.25914/abcd-1234", note: "first citable cut",
      build_id: "20260414T000000Z-99ffaa1", n_surveys: 19, n_stations: 1301, path: "releases/2026-Q2/" },
  ],
};

const Q3 = {
  tag: "2026-Q3",
  cut_at: { build_generated: "2026-07-28T01:02:03Z", cut: "2026-07-28T14:08:34Z" },
  build_id: "20260728T010203Z-ab12cd3",
  engine_commit: "0f1e2d3c4b5a69788796a5b4c3d2e1f009182736",
  source_commit: "9a8b7c6d5e4f30211203344556677889900aabbc",
  n_surveys: 21, n_stations: 1418,
  files: [
    { path: "mtcat.json", size: 204800, sha256: "a".repeat(64) },
    { path: "surveys.json", size: 10240, sha256: "b".repeat(64) },
    { path: "manifest.json", size: 2048, sha256: "c".repeat(64) },
    { path: "bundles/musgraves-2016/musgraves-2016.zip", size: 5242880, sha256: "d".repeat(64) },
    { path: "bundles/musgraves-2016/LICENSE.txt", size: 700, sha256: "e".repeat(64) },
  ],
  doi: null, note: null,
};

const Q2 = {
  tag: "2026-Q2",
  cut_at: { build_generated: "2026-04-14T00:00:00Z", cut: "2026-04-14T09:00:00Z" },
  build_id: "20260414T000000Z-99ffaa1",
  engine_commit: "1122334455667788990011223344556677889900",
  source_commit: "aabbccddeeff00112233445566778899aabbccdd",
  n_surveys: 19, n_stations: 1301,
  files: [
    { path: "mtcat.json", size: 190000, sha256: "f".repeat(64) },
    { path: "surveys.json", size: 9000, sha256: "0".repeat(64) },
    { path: "manifest.json", size: 1800, sha256: "1".repeat(64) },
    { path: "bundles/capricorn-2015/capricorn-2015.zip", size: 3145728, sha256: "2".repeat(64) },
  ],
  doi: "10.25914/abcd-1234", note: "first citable cut",
};

// The deployed shape: releases/releases.json for the index, releases/<tag>/release.json per release.
function served(overrides) {
  const docs = Object.assign({
    "releases/releases.json": INDEX,
    "releases/2026-Q3/release.json": Q3,
    "releases/2026-Q2/release.json": Q2,
  }, overrides || {});
  return (url) => {
    for (const key of Object.keys(docs)) {
      if (String(url).endsWith(key)) {
        const v = docs[key];
        return (typeof v === "function") ? v() : jsonOk(v);
      }
    }
    return status(404);
  };
}

(async () => {
  // ---- 1. STRUCTURE: a populated index renders one card per release, newest first ----------------
  let r = await run(served());
  ok(r.list.hidden === false, "a populated index must reveal the release list; it stayed hidden");
  ok(r.empty.hidden === true, "the empty state must be hidden when releases exist");
  ok(r.error.hidden === true, "the error state must be hidden when the index was read fine");
  ok(r.loading.hidden === true, "the loading state must be replaced once the index resolves");
  ok(r.cards.length === 2, "expected 2 release cards, got " + r.cards.length);

  const q3 = r.cards[0];
  ok(txt(q3, ".rel-tag") === "2026-Q3", "first card must be the newest release tag; got " + txt(q3, ".rel-tag"));
  ok(txt(q3, ".rel-cut") === "cut 2026-07-28", "expected the ISO cut date; got " + txt(q3, ".rel-cut"));
  ok(/21 surveys/.test(txt(q3, ".rel-corpus")), "expected '21 surveys'; got " + txt(q3, ".rel-corpus"));
  ok(/1,418 stations/.test(txt(q3, ".rel-corpus")),
    "expected the locale-grouped '1,418 stations'; got " + txt(q3, ".rel-corpus"));

  // build id + source commit, both in the mono identity block
  const ids = txt(q3, ".rel-ids");
  ok(/build id/.test(ids) && ids.indexOf(Q3.build_id) >= 0, "the card must state the build id; got " + ids);
  ok(/source commit/.test(ids) && ids.indexOf(Q3.source_commit) >= 0,
    "the card must state the source commit (only release.json carries it); got " + ids);
  const monos = Array.from(q3.querySelectorAll(".rel-ids span.v")).map((n) => n.textContent);
  ok(monos.indexOf(Q3.build_id) >= 0 && monos.indexOf(Q3.source_commit) >= 0,
    "build id and source commit must both be rendered in the mono value style; got " + JSON.stringify(monos));

  // ---- 2. LINKS: built from the release's own files[], catalogue documents + every bundle ---------
  const cat = hrefs(q3, ".filelinks a");
  ok(JSON.stringify(cat) === JSON.stringify([
    "data/releases/2026-Q3/mtcat.json",
    "data/releases/2026-Q3/surveys.json",
    "data/releases/2026-Q3/manifest.json",
  ]), "catalogue links must point into the release directory, in copy order; got " + JSON.stringify(cat));

  const bundleLinks = hrefs(q3, "details.bundles a");
  ok(JSON.stringify(bundleLinks) === JSON.stringify([
    "data/releases/2026-Q3/bundles/musgraves-2016/musgraves-2016.zip",
    "data/releases/2026-Q3/bundles/musgraves-2016/LICENSE.txt",
  ]), "every bundle in files[] must be linked; got " + JSON.stringify(bundleLinks));
  ok(/2 bundle files/.test(txt(q3, "details.bundles summary")),
    "the bundle disclosure must count the files; got " + txt(q3, "details.bundles summary"));
  ok(/5\.0 MB/.test(txt(q3, "details.bundles")), "bundle sizes must be shown; got " + txt(q3, "details.bundles"));
  ok(q3.querySelector(".detail-warn") === null,
    "a release whose release.json was read must NOT carry the could-not-be-read warning");

  // ---- 3. CITATION: exact reference line, and the two identifier outcomes ------------------------
  ok(txt(q3, ".cite-text") === "AusMT contributors (2026). AusMT Data Portal, Release 2026-Q3. AuScope.",
    "citation line is wrong: " + txt(q3, ".cite-text"));
  ok(txt(q3, ".cite-doi") === "DOI: not yet minted",
    "an unminted release must show the plain pending text; got " + txt(q3, ".cite-doi"));
  ok(q3.querySelector(".cite-doi a") === null,
    "the pending DOI marker must be TEXT, never an anchor (a dead resolver link is the thing this avoids)");

  const q2 = r.cards[1];
  ok(txt(q2, ".cite-text") === "AusMT contributors (2026). AusMT Data Portal, Release 2026-Q2. AuScope.",
    "citation line is wrong: " + txt(q2, ".cite-text"));
  const doiA = q2.querySelector(".cite-doi a");
  ok(doiA !== null, "a minted release must link its DOI at the resolver");
  ok(doiA.getAttribute("href") === "https://doi.org/10.25914/abcd-1234",
    "DOI link must resolve through doi.org; got " + doiA.getAttribute("href"));
  ok(doiA.getAttribute("rel") === "noopener noreferrer" && doiA.getAttribute("target") === "_blank",
    "the external DOI link must carry target=_blank rel='noopener noreferrer' (reverse-tabnabbing guard)");
  ok(/first citable cut/.test(txt(q2, ".rel-note")), "the release note must be shown; got " + txt(q2, ".rel-note"));

  // A DOI-shaped placeholder must fall through to the pending text rather than become a dead link.
  r = await run(served({
    "releases/2026-Q2/release.json": Object.assign({}, Q2, { doi: "pending" }),
    "releases/releases.json": {
      schema: "ausmt-releases", version: "1.0",
      releases: [Object.assign({}, INDEX.releases[1], { doi: "pending" })],
    },
  }));
  ok(txt(r.cards[0], ".cite-doi") === "DOI: not yet minted",
    "a non-DOI placeholder must render as pending, not as a resolver link; got " + txt(r.cards[0], ".cite-doi"));
  ok(r.cards[0].querySelector(".cite-doi a") === null, "a placeholder DOI must not become an anchor");

  // A resolver-prefixed DOI is normalised to one canonical link (matches cut_release.normalise_doi).
  r = await run(served({
    "releases/2026-Q2/release.json": Object.assign({}, Q2, { doi: "https://doi.org/10.25914/abcd-1234" }),
    "releases/releases.json": { schema: "ausmt-releases", version: "1.0", releases: [INDEX.releases[1]] },
  }));
  ok(r.cards[0].querySelector(".cite-doi a").getAttribute("href") === "https://doi.org/10.25914/abcd-1234",
    "a resolver-prefixed DOI must not double up the prefix");

  // ---- 4. HONESTY: empty and absent say "none cut"; unreadable says it could not find out --------
  const EMPTY_TEXT = "No releases cut yet; releases are quarterly snapshots of the corpus.";

  r = await run(served({ "releases/releases.json": { schema: "ausmt-releases", version: "1.0", releases: [] } }));
  ok(r.empty.hidden === false, "an empty index must show the empty state; it stayed hidden");
  ok(r.emptyMsg === EMPTY_TEXT, "empty-state wording drifted: " + r.emptyMsg);
  ok(r.list.hidden === true && r.error.hidden === true, "only the empty state may be visible on an empty index");
  ok(r.cards.length === 0, "an empty index must render no cards");

  r = await run(() => status(404));
  ok(r.empty.hidden === false, "an absent index (404) must show the empty state; it stayed hidden");
  ok(r.error.hidden === true, "a 404 index is 'nothing published', not 'could not be read'");
  // The probe: "no release has been cut" and "the release tier is not published at this path" both
  // arrive as a 404, so the state has to name the document it asked for or an operator cannot tell
  // which one they are looking at.
  ok(r.emptyProbe.hidden === false, "the empty state must reveal the probe line naming what it looked for");
  ok(r.emptyProbe.url === "data/releases/releases.json",
    "the probe must state the URL actually requested; got " + r.emptyProbe.url);

  r = await run(() => Promise.reject(new Error("blocked")));
  ok(r.error.hidden === false, "a rejected fetch must show the could-not-be-read state; it stayed hidden");
  ok(r.empty.hidden === true,
    "a rejected fetch must NOT be reported as 'no releases cut yet' - the page does not know that");
  ok(/could not be read/.test(r.error.text), "the error state must say the index could not be read");
  ok(r.errorProbe.hidden === false && r.errorProbe.url === "data/releases/releases.json",
    "the unreadable state must also name the document it tried; got " + JSON.stringify(r.errorProbe));

  r = await run(() => status(500));
  ok(r.error.hidden === false, "a 500 must show the could-not-be-read state");
  ok(r.empty.hidden === true, "a 500 must not be reported as 'no releases cut yet'");

  r = await run(served({ "releases/releases.json": { not: "an index" } }));
  ok(r.error.hidden === false, "a served document that is not a releases index must show the error state");
  ok(r.empty.hidden === true, "a malformed index must not be reported as 'no releases cut yet'");

  // ---- 5. HONESTY: an unreadable per-release document degrades, it does not fabricate links ------
  r = await run(served({ "releases/2026-Q3/release.json": () => status(404) }));
  ok(r.cards.length === 2, "one unreadable release document must not blank the whole page");
  const degraded = r.cards[0];
  ok(txt(degraded, ".rel-tag") === "2026-Q3", "the degraded card is still the release it claims to be");
  ok(txt(degraded, ".cite-text") === "AusMT contributors (2026). AusMT Data Portal, Release 2026-Q3. AuScope.",
    "the citation still comes from the index row when the release document is unreadable");
  ok(degraded.querySelectorAll(".filelinks a").length === 0,
    "no file may be linked when its release document could not be read (the links would 404)");
  ok(degraded.querySelector("details.bundles") === null, "no bundle list without a files[] block to build it from");
  ok(/could not be read/.test(txt(degraded, ".detail-warn")),
    "the degraded card must SAY the release document could not be read; got " + txt(degraded, ".detail-warn"));
  ok(!/source commit/.test(txt(degraded, ".rel-ids") || ""),
    "source commit must be omitted, not guessed, when release.json is unreadable");
  ok(r.cards[1].querySelectorAll(".filelinks a").length === 3,
    "the release whose document WAS readable must still get its links");

  // ---- 6. a deployment that publishes its data elsewhere ----------------------------------------
  r = await run(served(), { data_base_url: "https://data.example.org/ausmt" });
  ok(r.cards.length === 2, "data_base_url deployments must still render");
  ok(hrefs(r.cards[0], ".filelinks a")[0] === "https://data.example.org/ausmt/releases/2026-Q3/mtcat.json",
    "links must honour AUSMT_CONFIG.data_base_url; got " + hrefs(r.cards[0], ".filelinks a")[0]);

  r = await run(() => status(404), { data_base_url: "https://data.example.org/ausmt" });
  ok(r.emptyProbe.url === "https://data.example.org/ausmt/releases/releases.json",
    "the probe must report the URL this deployment really asked for, not a hard-coded one; got " +
    r.emptyProbe.url);

  // ---- 7. tolerance: rows the index should not have, and a release with no cut timestamp ---------
  r = await run(served({
    "releases/releases.json": {
      schema: "ausmt-releases", version: "1.0",
      releases: [null, "junk", { cut: "2026-01-01T00:00:00Z" }, { tag: "2026-Q1", path: "releases/2026-Q1/" }],
    },
    "releases/2026-Q1/release.json": () => status(404),
  }));
  ok(r.cards.length === 1, "rows without a usable tag must be skipped, not rendered; got " + r.cards.length);
  ok(txt(r.cards[0], ".cite-text") === "AusMT contributors. AusMT Data Portal, Release 2026-Q1. AuScope.",
    "with no cut date the citation must DROP the year rather than invent one; got " + txt(r.cards[0], ".cite-text"));
  ok(r.cards[0].querySelector(".rel-cut") === null, "no cut date means no cut-date line");

  console.log("RELEASES OK");
})().catch((e) => die((e && e.stack) || String(e)));
