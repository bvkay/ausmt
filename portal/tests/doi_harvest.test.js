// Node test for the SHARED DOI citation-harvest core (src/doi_harvest.js) - the single source the public
// Add Survey form AND the curator metadata editor both consume (the contributor-credit model). Exercises the
// module directly: the export surface, the window-global attachment the curator page relies on, the
// registry parsers, and harvestDoi's Crossref-then-DataCite fallback with a STUBBED fetch (never the
// network). Run via tests/test_doi_harvest.py or:  node tests/doi_harvest.test.js
const path = require("path");
const H = require(path.join(__dirname, "..", "src", "doi_harvest.js"));

let fail = 0;
const ok = (c, m) => { console.log((c ? "  ok   " : "  FAIL ") + m); if (!c) fail++; };

// ---- export surface + window-global attachment ----
const EXPECTED = ["normalizeDoi", "looksLikeDoi", "firstRegStr", "foldRegAuthors",
                  "parseCrossref", "parseDatacite", "formatCitation", "harvestDoi"];
ok(EXPECTED.every(k => typeof H[k] === "function"), "exports all eight harvest functions");

// The curator editor loads it as a classic script and reads window.AusmtDoiHarvest - prove the module
// attaches to a provided global (simulating the browser load the gateway serves).
delete global.window;
global.window = {};
delete require.cache[require.resolve(path.join(__dirname, "..", "src", "doi_harvest.js"))];
require(path.join(__dirname, "..", "src", "doi_harvest.js"));
ok(global.window.AusmtDoiHarvest && typeof global.window.AusmtDoiHarvest.harvestDoi === "function",
   "attaches to window.AusmtDoiHarvest when loaded as a browser script");

// ---- pure parsing ----
ok(H.normalizeDoi("https://doi.org/10.1/x") === "10.1/x", "normalizeDoi folds a resolver URL to the bare DOI");
ok(H.normalizeDoi("10.1/x") === "10.1/x", "normalizeDoi leaves a bare DOI unchanged");
ok(H.looksLikeDoi("10.1038/s41598-023-32403-z") === true, "looksLikeDoi accepts a well-formed DOI");
ok(H.looksLikeDoi("not a doi") === false, "looksLikeDoi rejects a non-DOI");

const CR = { message: { DOI: "10.1038/x", title: ["A Title"], "container-title": ["Nature"],
             issued: { "date-parts": [[2023]] }, author: [{ family: "Kay", given: "Ben" },
             { family: "Heinson", given: "Graham" }] } };
const cp = H.parseCrossref(CR, "10.1038/x");
ok(cp.title === "A Title" && cp.journal === "Nature" && cp.year === "2023",
   "parseCrossref reads title, journal (container-title) and year");
ok(cp.author === "Kay B, Heinson G", "parseCrossref folds authors to 'Family Initials'");
ok(H.parseCrossref({}, "x") === null && H.parseCrossref(null, "x") === null,
   "parseCrossref returns null on a non-payload");

const DC = { data: { attributes: { titles: [{ title: "Dataset" }], creators: [{ name: "GSSA" }],
             publicationYear: 2016, publisher: "NCI", doi: "10.25914/y" } } };
const dp = H.parseDatacite(DC, "10.25914/y");
ok(dp.title === "Dataset" && dp.author === "GSSA" && dp.year === "2016" && dp.journal === "NCI",
   "parseDatacite reads title, org creator, year and publisher-as-journal");

// ---- harvestDoi with a STUBBED fetch (never the network) ----
function stub(map) { return async (u) => (u in map ? { ok: true, json: async () => map[u] } : { ok: false }); }
const CRU = d => "https://api.crossref.org/works/" + encodeURIComponent(d);
const DCU = d => "https://api.datacite.org/dois/" + encodeURIComponent(d);

(async () => {
  const D1 = "10.1038/x";
  const m1 = {}; m1[CRU(D1)] = CR;
  const h1 = await H.harvestDoi(D1, stub(m1));
  ok(h1.ok && h1.source === "crossref" && h1.pub.title === "A Title", "harvestDoi: Crossref hit -> ok");

  const D2 = "10.25914/y";
  const m2 = {}; m2[DCU(D2)] = DC;   // no Crossref record for this DOI -> a 'miss' that falls through to DataCite
  const h2 = await H.harvestDoi(D2, stub(m2));
  ok(h2.ok && h2.source === "datacite", "harvestDoi: Crossref miss -> DataCite hit");

  const h3 = await H.harvestDoi(D1, stub({}));
  ok(!h3.ok && h3.pub.doi === D1, "harvestDoi: both registries miss -> manual, DOI preserved for prefill");

  let called = 0;
  const h4 = await H.harvestDoi("not a doi", async () => { called++; return { ok: false }; });
  ok(!h4.ok && h4.reason === "not-a-doi" && called === 0, "harvestDoi: a non-DOI never touches the network");

  if (fail) { console.error("\n" + fail + " CHECK(S) FAILED"); process.exit(1); }
  console.log("\nALL PASSED (doi_harvest)");
})();
