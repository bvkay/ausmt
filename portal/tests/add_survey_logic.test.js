// Node test for the pure logic embedded in add-survey.html. REWRITTEN for the "files first, five minutes,
// enrich later" contribution redesign (2026-07-24): the tiered form, the NEW emission shape (identifiers-
// by-level related_identifiers + publications[] + identifiers.instrument_pid, with the RETIRED flat
// identifier model deleted), and the SOFTENED location + DATAID gates. Self-contained (synthetic EDIs, no
// external data). Run via tests/test_add_survey_logic.py or:  node tests/add_survey_logic.test.js
const fs = require("fs"), path = require("path"), os = require("os");
const html = fs.readFileSync(path.join(__dirname, "..", "add-survey.html"), "utf8");
const block = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1])
  .find(b => b.includes("function buildSurveyYaml"));
if (!block) { console.error("FAIL: pure-logic <script> not found in add-survey.html"); process.exit(1); }
// The inline block aliases the DOI-harvest core from window.AusmtDoiHarvest (the shared src/doi_harvest.js,
// loaded via <script src> in the browser). Provide the same global here before requiring the block so the
// aliased normalizeDoi/looksLikeDoi/parseCrossref/parseDatacite/formatCitation/harvestDoi resolve, exactly
// as they do on the page. This is the SINGLE source both the public form and the curator editor consume.
global.window = global.window || {};
global.window.AusmtDoiHarvest = require(path.join(__dirname, "..", "src", "doi_harvest.js"));

const tmp = path.join(os.tmpdir(), "ausmt_addsurvey_logic.js");
fs.writeFileSync(tmp, block);
const M = require(tmp);

let fail = 0;
const ok = (c, m) => { console.log((c ? "  ok   " : "  FAIL ") + m); if (!c) fail++; };

// HEAD -30:37:57 (=-30.6325) vs INFO -29.3675 -> floored-DMS signature (real Western Gawler case)
const CONFLICT = '>HEAD\nDATAID="WG-1"\nLAT=-30:37:57.165\nLONG=+132:45:12.929\n\n>INFO\nLATITUDE :  -29.3675\nLONGITUDE: 132.7536\n\n>FREQ\n1 10 100\n>ZXYR\n1 2 3\n';
const CLEAN = '>HEAD\nDATAID="SA1"\nLAT=-28.5011\nLONG=131.2\n\n>FREQ\n1 10 100\n>ZXYR\n1 2 3\n';

const p = M.parseEdi(CONFLICT);
ok(Math.abs(p.lat - (-30.6325)) < 1e-3, "HEAD lat parsed (~ -30.6325)");
ok(Math.abs(p.info_lat - (-29.3675)) < 1e-3, "INFO lat parsed (~ -29.3675)");
ok(p.coord_flag === "dms_sign_ambiguous", "DMS HEAD/INFO conflict flagged");
ok(M.parseEdi(CLEAN).coord_flag == null, "clean decimal EDI not flagged");

const base = { name: "X", slug: "x", organisation: "O", country: "Australia", license: "CC-BY-4.0", access: "open",
               uploader_name: "n", uploader_email: "a@b.co", authority_to_submit: true, license_declaration: true };

// ============================ SOFTENED station-location gate (owner ruling 2026-07-24) ============================
// The location-confirm checkbox BLOCKS ONLY when the DMS resolver actually found a HEAD/INFO conflict.
// A survey whose stations carry NO conflict never blocks, regardless of the confirmation state.
const flaggedEdis = [{ name: "WG-1.edi", parsed: p }];
const cleanEdis = [{ name: "SA1.edi", parsed: M.parseEdi(CLEAN) }];
ok(M.validateSurvey({ ...base, locations_confirmed: false }, flaggedEdis, []).items.some(i => i.check === "locations" && i.level === "FAIL"),
   "flagged (conflict) + unconfirmed -> location FAIL (blocking)");
ok(!M.validateSurvey({ ...base, locations_confirmed: true }, flaggedEdis, []).items.some(i => i.check === "locations" && i.level === "FAIL"),
   "flagged (conflict) + confirmed -> no location FAIL");
ok(!M.validateSurvey({ ...base, locations_confirmed: false }, cleanEdis, []).items.some(i => i.check === "locations" && i.level === "FAIL"),
   "NO conflict + unconfirmed -> NO location FAIL (softened: no checkbox wall)");
ok(M.validateSurvey({ ...base, locations_confirmed: false }, cleanEdis, []).items.some(i => i.check === "locations" && i.level === "PASS"),
   "NO conflict -> an informational PASS 'plotted' item (the nudge), never a block");
ok(M.validateSurvey({ ...base, locations_confirmed: false }, flaggedEdis, []).items.some(i => i.check === "coordinates" && /DMS sign bug/.test(i.message)),
   "DMS conflict still surfaced as a coordinates WARNING");

const y = M.buildSurveyYaml({ ...base, data_types: ["BBMT"], region: "South Australia",
                              coord_resolution: { dms_sign: "info", basis: "confirmed on map" } });
ok(/coordinate_resolution:\s*\n\s*dms_sign: info/.test(y), "survey.yaml emits coordinate_resolution dms_sign: info");
ok(/region: "South Australia"/.test(y), "survey.yaml emits region");
ok(!/coordinate_resolution:/.test(M.buildSurveyYaml({ ...base, data_types: ["BBMT"] })),
   "no coordinate_resolution when nothing was resolved");

// ---- access block: embargo_until + contact (audit 5.2) ----
const yEmb = M.buildSurveyYaml({ ...base, access: "embargoed",
                                 embargo_until: "2027-02-01", access_contact: "custodian@agency.gov.au" });
ok(/access:\s*\n\s*level: embargoed\s*\n\s*embargo_until: 2027-02-01/.test(yEmb),
   "survey.yaml emits access.embargo_until when the date is filled");
ok(/contact: "custodian@agency\.gov\.au"/.test(yEmb), "survey.yaml emits access.contact when provided");
const yOpen = M.buildSurveyYaml({ ...base, access: "open" });
ok(/access:\s*\n\s*level: open\s*\n\s*embargo_until: null\s*\n\s*contact: null/.test(yOpen),
   "survey.yaml keeps embargo_until and contact null for an open survey");
ok(/embargo_until: null/.test(M.buildSurveyYaml({ ...base, access: "metadata_only", access_contact: "" })),
   "survey.yaml emits embargo_until: null when the date is left blank");
const yInject = M.buildSurveyYaml({ ...base, access: "embargoed", embargo_until: "2027-02-01\ninjected: true" });
ok(/embargo_until: null/.test(yInject) && !/injected:/.test(yInject),
   "a newline-injection embargo_until emits null and no injected key");

// ---- client-side slug mirror + AUTO-DERIVE (redesign: slug derives from the project name) ----
ok(M.slugValid("example-survey-2026") === true, "slugValid: lowercase-hyphenated slug accepted");
ok(M.slugValid("Example-Survey") === false, "slugValid: uppercase rejected");
ok(M.slugValid("example survey") === false, "slugValid: spaces rejected");
ok(M.slugValid("example_survey") === false, "slugValid: underscore rejected");
ok(M.slugValid("-example") === false && M.slugValid("example-") === false, "slugValid: leading/trailing hyphen rejected");
ok(M.slugValid("") === false, "slugValid: empty rejected");
// the derive helper is charset-safe: whatever the project name, the derived slug passes slugValid.
ok(/function deriveSlug/.test(html), "the page carries a deriveSlug() that auto-fills the folder slug from the name");
for (const name of ["Example MT Survey 2026", "AusLAMP: SA (block 4)!", "  spaced  &  odd  "]) {
  const der = html.match(/function deriveSlug\(name\)\{[\s\S]*?\}/)[0];
  const dfn = new Function("name", der.replace(/^function deriveSlug\(name\)\{/, "").replace(/\}$/, ""));
  const slug = dfn(name);
  ok(slug === "" || M.slugValid(slug), "deriveSlug('" + name + "') = '" + slug + "' is slug-valid or empty");
}
const badSlug = M.validateSurvey({ ...base, slug: "Bad_Slug", locations_confirmed: true }, cleanEdis, []);
ok(badSlug.items.some(i => i.check === "slug" && i.level === "FAIL"), "validateSurvey: a malformed slug is a blocking FAIL");
ok(!M.validateSurvey({ ...base, slug: "good-slug", locations_confirmed: true }, cleanEdis, []).items
   .some(i => i.check === "slug" && i.level === "FAIL"), "validateSurvey: a valid slug raises no slug FAIL");

// ---- copy honesty: authoritative validation is the gateway/curator review, not "CI" ----
ok(!/repository workflow<\/b> \(CI\)|authoritative in the AusMT repository/i.test(html),
   "the advisory box no longer claims authoritative validation lives in the repository CI workflow");
ok(/authoritative/i.test(html.slice(html.indexOf('class="advisory"'), html.indexOf('class="advisory"') + 600)),
   "the advisory box still names an authoritative validation stage");
// no em dashes in the redesigned copy (owner ruling: "No em dashes anywhere").
const mainCopy = html.slice(html.indexOf("<main>"), html.indexOf("</main>"));
ok(!/—/.test(mainCopy), "no em dash (U+2014) anywhere in the page's <main> copy");

// ============================ DATAID: ediDataId reader (unchanged shape) ============================
const OLYMPIC = '>HEAD\nDATAID="ROX000"\nACQBY=""\nLAT=-30:37:57.1\nLONG=+136:45:12.9\nELEV=10.0\nUNITS=M\n\n>INFO\n\n>FREQ\n1 10 100\n>ZXYR\n1 2 3\n';
ok(M.ediDataId(OLYMPIC) === "ROX000", "ediDataId reads DATAID from a realistic >HEAD (olympic-dam ROX000)");
ok(M.ediDataId('>HEAD\nDATAID=ROX000\n') === "ROX000", "ediDataId: unquoted DATAID tolerated");
ok(M.ediDataId('>HEAD\nLAT=-30\n') === null, "ediDataId: absent DATAID -> null");
ok(M.ediDataId('>HEAD\nDATAID=""\n') === null, "ediDataId: empty-quoted DATAID -> null");
const farId = "x".repeat(70000) + '\nDATAID="LATE"\n';
ok(M.ediDataId(farId) === null, "ediDataId: DATAID beyond the 64 KB prefix is not read (bounded)");

// safeEdiComponent shared vectors (unchanged contract with the engine)
const VEC = JSON.parse(fs.readFileSync(
  path.join(__dirname, "..", "..", "engine", "tests", "fixtures", "safe_component_vectors.json"), "utf8"));
ok(Array.isArray(VEC.vectors) && VEC.vectors.length >= 20 && typeof VEC.fallback === "string",
   "shared safe_component vectors file loads (" + VEC.vectors.length + " vectors)");
for (const v of VEC.vectors)
  ok(M.safeEdiComponent(v.input, VEC.fallback) === v.expected,
     "safeEdiComponent shared-vector [" + v.kind + "]: " + JSON.stringify(v.input) + " -> " + JSON.stringify(v.expected));
ok(M.packagedEdiName("ROX000") === "ROX000.edi", "packagedEdiName: <sanitized-DATAID>.edi");

// ============================ SOFTENED DATAID gate (owner ruling 2026-07-24) ============================
// deriveDataId: a missing DATAID auto-derives from the FILENAME (extension stripped, then sanitised).
ok(M.deriveDataId("ROX000.edi") === "ROX000", "deriveDataId strips the .edi extension");
ok(M.deriveDataId("Line1__Station7_1.edi") === "Line1__Station7_1", "deriveDataId keeps a safe filename stem");
ok(M.deriveDataId("weird name!.edi") === "weird-name-", "deriveDataId sanitises unsafe filename chars");
ok(M.deriveDataId("A B.mth5") === "A-B", "deriveDataId strips .mth5 too");
// effectiveDataId: real DATAID wins, else the filename-derived fallback.
ok(M.effectiveDataId({ name: "whatever.edi", dataid: "ROX9" }) === "ROX9", "effectiveDataId: real DATAID wins");
ok(M.effectiveDataId({ name: "no-id.edi", dataid: null }) === "no-id", "effectiveDataId: falls back to the filename stem");

// ediNameGate: a MISSING DATAID no longer errors on its own (auto-derived); a distinct set is clean.
ok(M.ediNameGate([{ name: "a.edi", dataid: "ROX000" }, { name: "b.edi", dataid: "ROX001" }]).length === 0,
   "ediNameGate: distinct DATAIDs -> no error");
ok(M.ediNameGate([{ name: "noid.edi", dataid: null }]).length === 0,
   "ediNameGate: a lone missing DATAID does NOT block (auto-derived from filename)");
ok(M.ediNameGate([{ name: "a.edi", dataid: null }, { name: "b.edi", dataid: "ROX1" }]).length === 0,
   "ediNameGate: missing + distinct present -> still no collision");
// the ONE remaining block: a true post-sanitisation collision (two files -> the same packaged name).
const dup = M.ediNameGate([{ name: "line1__1.edi", dataid: "ROX000" }, { name: "line2__1.edi", dataid: "ROX000" }]);
ok(dup.length === 1 && /line1__1\.edi/.test(dup[0]) && /line2__1\.edi/.test(dup[0]),
   "ediNameGate: duplicate DATAID -> one collision error naming BOTH source filenames");
// two DERIVED names that collide (two files with the same stem, both missing DATAID) also block.
const derdup = M.ediNameGate([{ name: "sub/x.edi", dataid: null }, { name: "y.edi", dataid: null }].map((e, i) => ({ name: ["x.edi", "x.edi"][i], dataid: null })));
ok(derdup.length === 1, "ediNameGate: two files whose derived names collide still block");
// DATAIDs that sanitise to the same name collide.
const sdup = M.ediNameGate([{ name: "a.edi", dataid: "ROX 0" }, { name: "b.edi", dataid: "ROX-0" }]);
ok(sdup.length === 1 && /a\.edi/.test(sdup[0]) && /b\.edi/.test(sdup[0]),
   "ediNameGate: DATAIDs that sanitise to the same name collide (both filenames named)");

// WIRED into validateSurvey: a missing DATAID is a WARNING (auto-derived, curator-flagged), NOT a FAIL.
const missRes = M.validateSurvey({ ...base, locations_confirmed: true },
  [{ name: "no-dataid.edi", parsed: M.parseEdi('>HEAD\nLAT=-30\nLONG=136\n\n>FREQ\n1 10 100\n>ZXYR\n1 2 3\n') }], []);
ok(missRes.items.some(i => i.check === "dataid" && i.level === "WARNING" && /auto-derived/.test(i.message) && /no-dataid/.test(i.message)),
   "validateSurvey: missing DATAID -> WARNING (auto-derived from filename, curator-flagged)");
ok(!missRes.items.some(i => i.check === "dataid" && i.level === "FAIL"),
   "validateSurvey: a lone missing DATAID does NOT FAIL (softened gate)");
// a duplicate DATAID still surfaces a blocking FAIL naming both files.
const dupEdis = [
  { name: "s1.edi", parsed: M.parseEdi('>HEAD\nDATAID="DUP"\nLAT=-30\nLONG=136\n\n>FREQ\n1 10 100\n>ZXYR\n1 2 3\n') },
  { name: "s2.edi", parsed: M.parseEdi('>HEAD\nDATAID="DUP"\nLAT=-31\nLONG=137\n\n>FREQ\n1 10 100\n>ZXYR\n1 2 3\n') },
];
const dupRes = M.validateSurvey({ ...base, locations_confirmed: true }, dupEdis, []);
ok(dupRes.items.some(i => i.check === "dataid" && i.level === "FAIL" && /s1\.edi/.test(i.message) && /s2\.edi/.test(i.message)),
   "validateSurvey: duplicate DATAID surfaces a blocking FAIL naming both files");
ok(dupRes.counts.FAIL > 0, "validateSurvey: the duplicate-DATAID FAIL blocks submission (counts.FAIL>0)");

// ============================ NEW EMISSION SHAPE (redesign) ============================
// The retired flat identifier model is DELETED; the new carrier is identifiers-by-level related_identifiers
// + publications[] + identifiers.instrument_pid. A survey carrying any of these declares schema 0.3.
const yBare = M.buildSurveyYaml({ ...base, license_declaration: false });
ok(/schema_version: "0.2"/.test(yBare), "a bare survey (no 0.3-era field) declares schema_version 0.2");
// RED PROOF: the retired keys must be ABSENT from the emitted survey.yaml.
for (const retired of ["dataset_doi", "related_publication:", "related_publication_doi", "\n  project:", "\nsources:", "collection_pid"]) {
  ok(!yBare.includes(retired), "RETIRED key absent from emission: " + JSON.stringify(retired));
}
// identifiers block = only the two survey/platform PIDs a submitter sets (project_raid + instrument_pid).
ok(/identifiers:\s*\n\s*project_raid: null\s*\n\s*instrument_pid: null/.test(yBare),
   "identifiers block is exactly {project_raid, instrument_pid} (nulls when unset)");
ok(/related_identifiers: \[\]/.test(yBare) && /publications: \[\]/.test(yBare),
   "empty related_identifiers and publications emit as empty lists");
ok(/time_series:\s*\n\s*levels_available: \[\]/.test(yBare) && !/collection_pid/.test(yBare),
   "time_series carries only levels_available (the hard-coded collection_pid null is gone)");

// related_identifiers rows: identifies + identifier + identifier_type + custodian; relation NEVER emitted.
const yRel = M.buildSurveyYaml({ ...base, related_identifiers: [
  { identifies: "raw_packed", identifier: "10.25914/raw", identifier_type: "DOI", custodian: "NCI" },
  { identifies: "entire", identifier: "https://ecat.ga.gov.au/x", identifier_type: "URL", custodian: "GA" },
  { identifies: "collection", identifier: "" }] });   // an empty-identifier row is dropped
ok(/related_identifiers:\s*\n\s*- identifier: "10\.25914\/raw"\s*\n\s*identifies: raw_packed\s*\n\s*identifier_type: DOI\s*\n\s*custodian: "NCI"/.test(yRel),
   "related_identifiers emits identifier + identifies + identifier_type + custodian for a filled row");
ok(!/relation:/.test(yRel), "related_identifiers NEVER emits `relation` (it derives server-side from identifies)");
ok((yRel.match(/- identifier:/g) || []).length === 2, "an empty-identifier related_identifiers row is dropped");
ok(/schema_version: "0.3"/.test(yRel), "a related_identifiers row declares schema_version 0.3");
// vocab guard: an out-of-vocab identifies / identifier_type is dropped (buildSurveyYaml is pure; a scripted
// meta can carry anything). Injection via a newline-bearing level must not smuggle a YAML key.
const yGuard = M.buildSurveyYaml({ ...base, related_identifiers: [
  { identifies: "not-a-level\ninjected: true", identifier: "10.1/x", identifier_type: "EVIL" }] });
ok(!/injected:/.test(yGuard) && !/identifies:/.test(yGuard) && !/identifier_type:/.test(yGuard),
   "out-of-vocab identifies/identifier_type dropped; a newline-injection level emits no key");
ok(/- identifier: "10\.1\/x"/.test(yGuard), "the identifier itself still emits (quoted) even when the level is dropped");

// identifiers.instrument_pid (survey/platform PID) + project_raid from the tier-2 fields.
const yPid = M.buildSurveyYaml({ ...base, instrument_pid: "10.82388/abc", raid: "https://raid.org/1" });
ok(/instrument_pid: "10\.82388\/abc"/.test(yPid) && /project_raid: "https:\/\/raid\.org\/1"/.test(yPid),
   "identifiers.instrument_pid + project_raid emit from the tier-2 fields");
ok(/schema_version: "0.3"/.test(yPid), "a survey/platform instrument_pid declares schema_version 0.3");

// publications[] LEGACY back-compat: the retired single-field {pub, pub_doi} pair still folds into one row.
const yPub = M.buildSurveyYaml({ ...base, license_declaration: false, pub: "Smith et al. 2024", pub_doi: "10.1093/gji/xyz" });
ok(/publications:\s*\n\s*- title: "Smith et al\. 2024"\s*\n\s*doi: "10\.1093\/gji\/xyz"/.test(yPub),
   "publications[] carries {title, doi} from the legacy single publication fields");
ok(/schema_version: "0.3"/.test(yPub), "a publications[] entry declares schema_version 0.3");
ok(/- doi: "10\.5/.test(M.buildSurveyYaml({ ...base, license_declaration: false, pub: "", pub_doi: "10.5281/zenodo.1" })),
   "a DOI-only publication emits a bare {doi} entry");

// ============================ R3: DOI-first publications + citation harvest (H1/H2/H4) ============================
// The publications block is a repeatable list of rows whose PRIMARY input is one DOI. A valid-looking DOI is
// harvested client-side (Crossref first, DataCite on a miss) into {author,year,title,journal,doi}; harvest
// failure OR a thin record degrades to the manual fields prefilled with whatever partial data exists. The
// EMISSION is identical whether a row was harvested or hand-typed. These tests NEVER hit the network — every
// harvestDoi call is driven by a stubbed fetch (per the standing rule).

// full 5-field emission (author/year/title/journal/doi, in that order, doi last).
const yFull = M.buildSurveyYaml({ ...base, license_declaration: false, publications: [
  { author: "Kay B, Heinson G", year: "2023", title: "MT of the Gawler Craton", journal: "Scientific Reports", doi: "10.1038/s41598-023-32403-z" }] });
ok(/publications:\s*\n\s*- author: "Kay B, Heinson G"\s*\n\s*year: "2023"\s*\n\s*title: "MT of the Gawler Craton"\s*\n\s*journal: "Scientific Reports"\s*\n\s*doi: "10\.1038\/s41598-023-32403-z"/.test(yFull),
   "a full publication row emits author/year/title/journal/doi in order");

// multiple rows + per-row independence in the emission (one DOI-only, one titled).
const yMulti = M.buildSurveyYaml({ ...base, license_declaration: false, publications: [
  { doi: "10.1/aaa" }, { title: "Second paper", journal: "GJI", doi: "10.2/bbb" }] });
const pubBlock = (yMulti.match(/publications:\n([\s\S]*?)\nprocessing:/) || [,""])[1];
ok((pubBlock.match(/^  - /gm) || []).length === 2, "two publication rows emit two independent list entries");
ok(/- doi: "10\.1\/aaa"/.test(yMulti) && /- title: "Second paper"\s*\n\s*journal: "GJI"\s*\n\s*doi: "10\.2\/bbb"/.test(yMulti),
   "each row emits only its own fields (DOI-only stays bare; titled row carries its journal)");

// a resolver URL pasted into the doi slot is folded, and an empty publications[] is still [].
ok(/- doi: "10\.9\/z"/.test(M.buildSurveyYaml({ ...base, license_declaration: false, publications: [{ doi: "https://doi.org/10.9/z" }] })),
   "pubRowsOf normalises a resolver-URL DOI down to the bare DOI");
ok(/publications: \[\]/.test(M.buildSurveyYaml({ ...base, license_declaration: false, publications: [{}, { doi: "" }] })),
   "all-empty publication rows are dropped (publications: [])");

// ---- pure parse + citation formatting ----
const CR_BODY = { message: { DOI: "10.1038/s41598-023-32403-z", title: ["MT of the Gawler Craton"],
  "container-title": ["Scientific Reports"], issued: { "date-parts": [[2023, 4, 1]] },
  author: [{ given: "Ben", family: "Kay" }, { given: "Graham", family: "Heinson" }, { given: "Kate", family: "Robertson" }] } };
const cp = M.parseCrossref(CR_BODY, "10.1038/s41598-023-32403-z");
ok(cp && cp.title === "MT of the Gawler Craton" && cp.journal === "Scientific Reports" && cp.year === "2023",
   "parseCrossref reads title, container-title (journal) and issued year");
ok(cp.author === "Kay B, Heinson G, Robertson K", "parseCrossref folds authors to 'Family Initials'");
ok(M.parseCrossref({}, "x") === null && M.parseCrossref(null, "x") === null, "parseCrossref returns null on a non-payload");
ok(M.formatCitation(cp) === "Kay B, Heinson G, et al. (2023). MT of the Gawler Craton. Scientific Reports.",
   "formatCitation renders the compact 'first two + et al.' citation line");

const DC_BODY = { data: { attributes: { doi: "10.25914/abc", titles: [{ title: "AusLAMP SA MT dataset" }],
  creators: [{ givenName: "Ben", familyName: "Kay" }, { name: "AuScope" }], publisher: "AuScope",
  container: { title: "AuScope Data Repository" }, publicationYear: 2022 } } };
const dp = M.parseDatacite(DC_BODY, "10.25914/abc");
ok(dp && dp.title === "AusLAMP SA MT dataset" && dp.year === "2022", "parseDatacite reads titles[].title and publicationYear");
ok(dp.author === "Kay B, AuScope", "parseDatacite folds creators (personal + organisation) to author string");
ok(dp.journal === "AuScope Data Repository", "parseDatacite prefers container.title for the journal/container slot");
ok(M.parseDatacite({ data: { attributes: { publisher: "NCI", titles: [], creators: [] } } }, "10.1/y").journal === "NCI",
   "parseDatacite falls back to publisher when no container is present");

ok(M.looksLikeDoi("10.1038/s41598-023-32403-z") && M.looksLikeDoi("https://doi.org/10.1234/x"),
   "looksLikeDoi accepts a bare DOI and a resolver-URL DOI");
ok(!M.looksLikeDoi("not a doi") && !M.looksLikeDoi("10.1234") && !M.looksLikeDoi("10.12/x") && !M.looksLikeDoi(""),
   "looksLikeDoi rejects non-DOI text, a suffix-less prefix, a too-short registrant, and empty");

// ---- harvestDoi with a STUBBED fetch (never the network) ----
const CRU = d => "https://api.crossref.org/works/" + encodeURIComponent(d);
const DCU = d => "https://api.datacite.org/dois/" + encodeURIComponent(d);
function stub(table) {   // url -> body (200), "throw" (network error), or absent (404)
  return async (url) => {
    const hit = table[url];
    if (hit === undefined) return { ok: false, status: 404, json: async () => ({}) };
    if (hit === "throw") throw new Error("network down");
    return { ok: true, status: 200, json: async () => hit };
  };
}

async function r3HarvestTests() {
  const DOI = "10.1038/s41598-023-32403-z";
  // (1) Crossref hit.
  const h1 = await M.harvestDoi(DOI, stub({ [CRU(DOI)]: CR_BODY }));
  ok(h1.ok && h1.source === "crossref" && h1.pub.title === "MT of the Gawler Craton" && h1.pub.doi === DOI,
     "harvestDoi: Crossref hit -> ok, full pub, source crossref");

  // (2) Crossref 404 -> DataCite hit.
  const DOI2 = "10.25914/abc";
  const h2 = await M.harvestDoi(DOI2, stub({ [DCU(DOI2)]: DC_BODY }));   // CRU(DOI2) absent -> 404
  ok(h2.ok && h2.source === "datacite" && h2.pub.title === "AusLAMP SA MT dataset",
     "harvestDoi: Crossref 404 -> DataCite hit -> ok, source datacite");

  // (3) Both miss -> manual expand (ok:false), pub prefilled with at least the DOI.
  const h3 = await M.harvestDoi(DOI, stub({}));
  ok(!h3.ok && h3.reason === "miss" && h3.pub.doi === DOI,
     "harvestDoi: both registries miss -> ok:false (manual), DOI preserved for prefill");

  // (4a) Malformed Crossref (empty title, no authors) then DataCite miss -> graceful ok:false 'thin', no throw.
  const THIN = "10.7777/thin";
  const h4a = await M.harvestDoi(THIN, stub({ [CRU(THIN)]: { message: { DOI: THIN, title: [], author: undefined } } }));
  ok(!h4a.ok && h4a.reason === "thin" && h4a.pub.doi === THIN && h4a.pub.author === "",
     "harvestDoi: a title-less Crossref record degrades gracefully to manual (thin), DOI kept");
  // (4b) Crossref with a title but MISSING authors -> still a confident preview (author empty, title present).
  const TITLED = "10.7777/titled";
  const h4b = await M.harvestDoi(TITLED, stub({ [CRU(TITLED)]: { message: { DOI: TITLED, title: ["Only a title"] } } }));
  ok(h4b.ok && h4b.pub.title === "Only a title" && h4b.pub.author === "",
     "harvestDoi: a Crossref record missing authors still previews (title present, author blank)");

  // (5) Emission identical: the harvested pub and a hand-typed row with the same values emit byte-identically.
  const yH = M.buildSurveyYaml({ ...base, license_declaration: false, publications: [h1.pub] });
  const yM = M.buildSurveyYaml({ ...base, license_declaration: false, publications: [
    { author: h1.pub.author, year: h1.pub.year, title: h1.pub.title, journal: h1.pub.journal, doi: h1.pub.doi }] });
  ok(yH === yM, "emission is byte-identical for a harvested vs a hand-entered publication row");
  ok(/- author: "Kay B, Heinson G, Robertson K"\s*\n\s*year: "2023"\s*\n\s*title: "MT of the Gawler Craton"/.test(yH),
     "the harvested row emits the full 5-field publications[] shape");

  // (6) A non-DOI never fetches; the stub records whether it was called.
  let called = 0;
  const spy = async () => { called++; return { ok: false, status: 404, json: async () => ({}) }; };
  const h6 = await M.harvestDoi("not a doi at all", spy);
  ok(!h6.ok && h6.reason === "not-a-doi" && called === 0, "harvestDoi: a non-DOI input never touches the network");

  // (7) Per-row independence: two DOIs harvested through independent stubs don't cross-contaminate; a network
  // throw on one degrades only that one.
  const A = "10.3333/aaa", B = "10.3333/bbb";
  const hA = await M.harvestDoi(A, stub({ [CRU(A)]: { message: { DOI: A, title: ["Paper A"] } } }));
  const hB = await M.harvestDoi(B, stub({ [CRU(B)]: "throw", [DCU(B)]: "throw" }));
  ok(hA.ok && hA.pub.title === "Paper A", "harvestDoi row A resolves independently");
  ok(!hB.ok && hB.pub.doi === B, "harvestDoi row B (both hosts throw) degrades independently to manual, DOI kept");
}

// dates block (T1) emits only when a date is provided; year + ISO stay bare, free text is quoted.
ok(/dates: \{ start: 2020, end: 2021 \}/.test(M.buildSurveyYaml({ ...base, date_start: "2020", date_end: "2021" })),
   "dates block emits bare year scalars");
ok(!/dates:/.test(M.buildSurveyYaml({ ...base })), "no dates block when neither date is filled");

// ---- provenance-identifier completeness now keys off the NEW carrier (related_identifiers) ----
const provItem = (res) => res.items.find(i => i.check === "provenance" && /no related identifier/.test(i.message));
const provEdis = [{ name: "SA1.edi", parsed: M.parseEdi(CLEAN) }];
ok(!!provItem(M.validateSurvey({ ...base, locations_confirmed: true }, provEdis, [])),
   "no related identifier -> provenance completeness WARNING fires");
ok(!provItem(M.validateSurvey({ ...base, locations_confirmed: true,
     related_identifiers: [{ identifies: "collection", identifier: "10.25914/x", identifier_type: "DOI" }] }, provEdis, [])),
   "a related_identifiers row with an identifier satisfies the provenance hint");
ok(!!provItem(M.validateSurvey({ ...base, locations_confirmed: true,
     related_identifiers: [{ identifies: "collection", identifier: "" }] }, provEdis, [])),
   "a related_identifiers row with NO identifier does not satisfy the hint (the identifier is the signal)");

// ---- relatedIdentifiersEmit (pure filter/guard) ----
const rie = M.relatedIdentifiersEmit([
  { identifies: "level2", identifier: "10.1/a", identifier_type: "DOI", custodian: "NCI" },
  { identifies: "bogus", identifier: "10.1/b", identifier_type: "Handle" },
  { identifier: "" }]);
ok(rie.length === 2, "relatedIdentifiersEmit drops empty-identifier rows");
ok(rie[0].identifies === "level2" && rie[1].identifies === "", "relatedIdentifiersEmit blanks an out-of-vocab identifies");
ok(rie.every(r => !("relation" in r)), "relatedIdentifiersEmit never carries a relation key");

// ---- vocab parity: the tier-2 identifiers-by-level vocab mirrors the gateway/validator ----
const validatorSrc = fs.readFileSync(
  path.join(__dirname, "..", "..", "gateway", "tests", "fixtures", "vendored_validation", "validate_survey.py"), "utf8");
const vLevels = (validatorSrc.match(/IDENTIFIES_LEVELS\s*=\s*\(([^)]*)\)/) || [])[1] || "";
const vLevelList = [...vLevels.matchAll(/"([^"]+)"/g)].map(m => m[1]);
ok(JSON.stringify(M.IDENTIFIES_LEVELS) === JSON.stringify(vLevelList),
   "portal IDENTIFIES_LEVELS matches the vendored validator's tuple: " + JSON.stringify(vLevelList));
const editorSrc = fs.readFileSync(path.join(__dirname, "..", "..", "gateway", "editor_form.py"), "utf8");
const eTypes = (editorSrc.match(/IDENTIFIER_TYPES\s*=\s*\(([^)]*)\)/) || [])[1] || "";
const eTypeList = [...eTypes.matchAll(/"([^"]+)"/g)].map(m => m[1]);
ok(JSON.stringify(M.IDENTIFIER_TYPES) === JSON.stringify(eTypeList),
   "portal IDENTIFIER_TYPES matches gateway editor_form.IDENTIFIER_TYPES: " + JSON.stringify(eTypeList));
ok(M.IDENTIFIES_LEVELS.every(lv => typeof M.IDENTIFIES_DISPLAY[lv] === "string" && M.IDENTIFIES_DISPLAY[lv].length),
   "every identifies level carries a human display label (mirrors the curator editor)");

// ---- ROR organisation lookup (unchanged) ----
ok(/api\.ror\.org\/v2\/organizations\?query=/.test(html), "ROR lookup uses the name-search ?query= endpoint");
ok(!/organizations\?affiliation=/.test(html), "ROR lookup does NOT use the ?affiliation= matcher");
const V2ORG = { id: "https://ror.org/028g18b61",
  names: [{ value: "Adelaide University", types: ["ror_display"] }, { value: "UofA", types: ["acronym"] }],
  locations: [{ geonames_details: { country_name: "Australia" } }] };
const qM = M.rorMatchesFromResponse({ items: [V2ORG] });
ok(qM.length === 1 && qM[0].id === "https://ror.org/028g18b61" && qM[0].name === "Adelaide University"
   && qM[0].country === "Australia" && qM[0].acronym === "UofA", "parses a query-shape (bare org) item");
ok(M.rorMatchesFromResponse({ items: [{ id: null, names: [] }] }).length === 0,
   "drops un-nameable / un-identifiable items (never shows 'undefined')");

// ---- C3 (PII scrub): the packaged submission .zip must NOT embed submitter email/ORCID ----
const pkgBlock = html.slice(html.indexOf("async function buildPackage"), html.indexOf('$("btnPackage").onclick'));
ok(!/submitter:\{[^}]*email:\s*meta\.uploader_email/.test(pkgBlock), "MANIFEST submitter block does NOT write uploader_email");
ok(!/submitter:\{[^}]*orcid:\s*meta\.uploader_orcid/.test(pkgBlock), "MANIFEST submitter block does NOT write uploader_orcid");
ok(/submitter:\{[^}]*name:\s*meta\.uploader_name/.test(pkgBlock), "MANIFEST submitter block still keeps the name");
ok(!/uploader_email/.test(pkgBlock), "the packager block does NOT reference uploader_email");
ok(/m_up_email/.test(html), "the uploader email form field itself is still present (feeds Stage-2 gateway)");

// ============================ C13 direct-upload pure logic (unchanged) ============================
const ORCID_VECTORS = JSON.parse(fs.readFileSync(
  path.join(__dirname, "..", "..", "gateway", "tests", "fixtures", "orcid_vectors.json"), "utf8"));
for (const v of ORCID_VECTORS.vectors.filter(v => v.applies_to.includes("portal")))
  ok(M.isOrcidChecksum(v.input) === v.valid, `isOrcidChecksum(${JSON.stringify(v.input)}) === ${v.valid} [${v.note}]`);
ok(M.gatewayPresent(200, '{"ok":true}') === true, "gatewayPresent: 200 + {ok:true} -> present");
ok(M.gatewayPresent(200, '<!doctype html><title>404</title>') === false, "gatewayPresent: 200 + HTML -> absent");
ok(M.gatewayPresent(200, '{"ok":false}') === false, "gatewayPresent: 200 + {ok:false} -> absent");
ok(M.gatewayPresent(404, '{"ok":true}') === false, "gatewayPresent: 404 -> absent");
ok(M.gatewayPresent(0, "") === false, "gatewayPresent: network-error shape -> absent");
ok(M.statusUrlSafe("/gateway/status/AbC-9_xYz01") === true, "statusUrlSafe: same-origin urlsafe-token path accepted");
ok(M.statusUrlSafe("http://evil.example/gateway/status/x") === false, "statusUrlSafe: absolute http URL rejected");
ok(M.statusUrlSafe("javascript:alert(1)") === false, "statusUrlSafe: javascript: scheme rejected");
ok(M.statusUrlSafe("/gateway/status/../../etc/passwd") === false, "statusUrlSafe: path traversal rejected");
ok(M.submitResultMessage(201, {submission_id: "S1"}) === "Submission received.", "submitResultMessage: 201");
ok(/not accepted/i.test(M.submitResultMessage(401, null)), "submitResultMessage: 401 -> key not accepted");
ok(/already in the pipeline/i.test(M.submitResultMessage(409, {submission_id: "abc"})), "submitResultMessage: 409 -> duplicate");
ok(/network/i.test(M.submitResultMessage(0, null)), "submitResultMessage: 0 -> network error");
const hostile = '<img src=x onerror=alert(1)>';
ok(M.submitResultMessage(400, {detail: hostile}) === hostile, "submitResultMessage: 400 -> server detail verbatim (page escapes it)");
const ff1 = M.submitFormFields({uploader_name: "Ada L", uploader_email: "ada@x.co", uploader_orcid: ""});
ok(!("submitter_orcid" in ff1) && ff1.submitter_name === "Ada L" && ff1.submitter_email === "ada@x.co",
   "submitFormFields: empty ORCID is OMITTED entirely");
ok(M.submitFormFields({uploader_name: "A", uploader_email: "a@x.co", uploader_orcid: "0000-0002-1825-0097"}).submitter_orcid
   === "0000-0002-1825-0097", "submitFormFields: non-empty ORCID rides as a field");

// ============================ connection targets (§5) + key-request stub ============================
const conns = [...html.matchAll(/(?:fetch|\.open)\(\s*(?:"[^"]*",\s*)?"([^"]+)"/g)].map(m => m[1])
  .filter(u => !/^\$\{/.test(u));
// same-origin, the ROR API, or the R3 citation-harvest registries (Crossref + DataCite). These three
// external hosts are the ONLY connect-src additions the add-survey CSP allows; a NEW origin fails here.
const ALLOWED_CONN = u => /^\//.test(u) || /^https:\/\/api\.ror\.org\//.test(u)
  || /^https:\/\/api\.crossref\.org\//.test(u) || /^https:\/\/api\.datacite\.org\//.test(u);
const badConns = conns.filter(u => !ALLOWED_CONN(u) && /^https?:/.test(u));
ok(badConns.length === 0, "every fetch()/XHR target is same-origin or an allow-listed API (ROR / Crossref / DataCite); new origins: " + JSON.stringify(badConns));
ok(!/cdnjs\.cloudflare\.com|basemaps\.cartocdn\.com/.test(html), "no CDN/basemap origin on the add-survey page");
ok(/fetch\("\/gateway\/healthz"/.test(html), "healthz probe uses the literal same-origin /gateway/healthz path");
ok(/\.open\("POST",\s*"\/gateway\/submit"\)/.test(html), "submit POSTs to the literal same-origin /gateway/submit path");
ok(!/https?:\/\/[^"'`]*\/gateway\//.test(html), "no absolute-URL /gateway/ reference (same-origin only)");
ok(/setRequestHeader\("X-AusMT-Submit-Key"/.test(html), "the submit key is sent via the X-AusMT-Submit-Key header");
ok(!/localStorage[^;\n]*submit_key/i.test(html) && !/sessionStorage[^;\n]*submit_key/i.test(html),
   "the submit key is never written to localStorage/sessionStorage");
// KEY REQUEST stub: POSTs {email} to the same-origin /gateway/request-key, always the SAME neutral message.
ok(/fetch\("\/gateway\/request-key"/.test(html), "the key-request stub POSTs to the same-origin /gateway/request-key path");
ok(/btnRequestKey/.test(html) && /m_keyreq_email/.test(html), "the key-request UI (button + email input) is present");
ok(/Need a key\?/.test(html), "the key-request prompt copy is present in the submit section");
ok(/if this address is eligible/i.test(html), "the key-request message is neutral (no account enumeration)");

// ---- licence select vocab = the generated contract (unchanged), no hand-copied source-licence select ----
const CONTRACT_SRC = fs.readFileSync(path.join(__dirname, "..", "src", "contract.js"), "utf8");
const LICENSES = new Function(CONTRACT_SRC + "; return LICENSES;")();
ok(JSON.stringify(M.licenseSelectIds(LICENSES)) === JSON.stringify([...LICENSES.redistributable, ...LICENSES.recognised_only]),
   "licenseSelectIds derives the select vocab from the contract");
ok(/\bLICENSES\b/.test(html) && /\.redistributable\b/.test(html) && /\.recognised_only\b/.test(html),
   "the licence select reads the contract LICENSES at runtime, not a hand-copied option list");
ok(!/id="m_src_license"/.test(html), "the retired source-licence <select> is gone (the sources[] block was deleted)");
ok(/<script src="src\/contract\.js">/.test(html), "the page loads the generated contract (src/contract.js) for the licence vocab");

// ---- attribution persistence (unchanged carrier) ----
const yAttr = M.buildSurveyYaml({ ...base, license_declaration: true, uploader_name: "Ada L", declared_date: "2026-07-13" });
// declared_date is emitted as a QUOTED string so PyYAML safe_load keeps it a str (not a datetime.date the
// engine's json.dumps then chokes on at the surveys.json/mtcat emit). Round-trips as a string everywhere.
ok(/attribution:\s*\n\s*declared_by: "Ada L"\s*\n\s*declared_date: "2026-07-13"/.test(yAttr),
   "buildSurveyYaml persists attribution.declared_by + a QUOTED declared_date");
ok(!/declared_date: \d{4}-\d{2}-\d{2}\b/.test(yAttr),
   "declared_date is never emitted as a BARE ISO scalar (that implicit-typed to date and crashed the engine)");
ok(/schema_version: "0.3"/.test(yAttr), "a package carrying attribution declares schema_version 0.3");
ok(!/attribution:/.test(M.buildSurveyYaml({ ...base, license_declaration: false })),
   "no attribution block when the licence declaration is not made");

// ============================ ROUND 2 (owner-ruled 2026-07-24) ============================

// ---- R1: slug-collision awareness. servedSlugMap folds surveys.json {name: SMETA} -> {slug: name};
//      stationCountsByName counts catalogue.json rows (index 1 = survey name) per survey. The chip warns
//      (never blocks) when a charset-valid slug matches a served slug.
const SURVEYS_FIXTURE = { "Vulcan 2022": { slug: "vulcan-2022", org: "GA" },
                          "Otway 2019": { slug: "otway-2019", org: "UniMelb" },
                          "No Slug Survey": { org: "X" } };   // a malformed/absent slug is skipped
const smap = M.servedSlugMap(SURVEYS_FIXTURE);
ok(smap["vulcan-2022"] === "Vulcan 2022" && smap["otway-2019"] === "Otway 2019",
   "servedSlugMap maps each published slug to its survey name");
ok(!("undefined" in smap) && Object.keys(smap).length === 2, "servedSlugMap skips an entry with no slug");
ok(Object.keys(M.servedSlugMap({})).length === 0, "servedSlugMap on the empty portal ({}) is empty (degrade)");
ok(Object.keys(M.servedSlugMap(null)).length === 0 && Object.keys(M.servedSlugMap([1, 2])).length === 0,
   "servedSlugMap tolerates null / a non-object (fetch-failure degrade)");
ok(M.servedSlugMap(SURVEYS_FIXTURE)["glenelg-2025"] === undefined, "a brand-new slug is NOT in the served set (no false collision)");
const CATALOGUE_FIXTURE = [
  ["ST1", "Vulcan 2022", -30, 135, 0.005, 6000, 62, "Z", "BBMT", "AU", "ST1.edi", false, "au.vulcan-2022.ST1", 1, "h"],
  ["ST2", "Vulcan 2022", -31, 136, 0.005, 6000, 62, "Z", "BBMT", "AU", "ST2.edi", false, "au.vulcan-2022.ST2", 0, "h"],
  ["ST3", "Otway 2019", -38, 143, 0.005, 6000, 62, "Z", "BBMT", "AU", "ST3.edi", false, "au.otway-2019.ST3", 0, "h"]];
const counts = M.stationCountsByName(CATALOGUE_FIXTURE);
ok(counts["Vulcan 2022"] === 2 && counts["Otway 2019"] === 1, "stationCountsByName counts catalogue rows per survey name");
ok(Object.keys(M.stationCountsByName(null)).length === 0 && Object.keys(M.stationCountsByName({})).length === 0,
   "stationCountsByName tolerates null / a non-array (fetch-failure degrade)");
// the render logic lives in the DOM closure; assert the page carries the collision loader + the non-blocking copy.
ok(/servedSlugMap\(/.test(html) && /stationCountsByName\(/.test(html), "the page uses servedSlugMap + stationCountsByName for collision awareness");
ok(/fetch\("data\/surveys\.json"\)/.test(html), "the collision check fetches the same-origin data/surveys.json");
ok(/matches the existing survey /.test(html) && /Continue if you are updating that survey/.test(html),
   "the collision warning copy informs (non-blocking), it does not wall");
ok(/orcidok warn/.test(html), "the collision state uses a distinct 'warn' chip class (not the valid/invalid states)");

// ---- R4: principal_investigators[] emission (schema shape {name, orcid}, mirrors the validator/editor). ----
const yPI = M.buildSurveyYaml({ ...base, principal_investigators: [
  { name: "Ada Lovelace", orcid: "0000-0002-1825-0097" },
  { name: "Grace Hopper", orcid: "" },
  { name: "", orcid: "0000-0001-0000-0000" }] });   // a nameless row is dropped
ok(/principal_investigators:\s*\n\s*- name: "Ada Lovelace"\s*\n\s*orcid: "0000-0002-1825-0097"\s*\n\s*- name: "Grace Hopper"\s*\n\s*orcid: null/.test(yPI),
   "principal_investigators emits {name, orcid} rows; a blank ORCID -> null");
ok((yPI.match(/- name:/g) || []).length === 2, "a nameless principal_investigators row is dropped (name is the signal)");
ok(!/principal_investigators:/.test(M.buildSurveyYaml({ ...base })), "no principal_investigators key when the list is empty (absent -> absent)");
ok(!/principal_investigators:/.test(M.buildSurveyYaml({ ...base, principal_investigators: [{ name: "" }] })),
   "an all-nameless principal_investigators list emits no key");
// the lead-investigator block still precedes it (served-citation precedence: lead first, else this list).
ok(yPI.indexOf("lead_investigator:") >= 0 && yPI.indexOf("lead_investigator:") < yPI.indexOf("principal_investigators:"),
   "lead_investigator is emitted before principal_investigators");
// the form carries the repeatable UI + the honest serving-precedence hint (mirrors the curator hub copy).
ok(/id="piRows"/.test(html) && /id="addPi"/.test(html) && /readPrincipalInvestigators\(/.test(html),
   "the form carries the repeatable principal-investigators UI (piRows + addPi) wired into readMeta");
ok(/When a lead investigator is set the portal credits the lead; otherwise the principal investigators list is credited/
   .test(html.replace(/\s+/g, " ")), "the serving-precedence hint mirrors the curator hub copy");
// parity: the emitted PI keys match the vendored editor's principal_investigators row spec (name, orcid).
ok(/"principal_investigators":\s*\[\s*\n\s*\("name"[\s\S]*?\("orcid"/.test(editorSrc),
   "the editor's principal_investigators row spec is (name, orcid) - the emission shape mirrors it");

// ---- R5: DOI normalisation (resolver URL -> bare DOI; bare + non-DOI + URL-typed left untouched). ----
ok(M.normalizeDoi("https://doi.org/10.1093/gji/xyz") === "10.1093/gji/xyz", "normalizeDoi folds an https://doi.org/ URL to the bare DOI");
ok(M.normalizeDoi("http://doi.org/10.1093/gji/xyz") === "10.1093/gji/xyz", "normalizeDoi folds an http:// resolver URL");
ok(M.normalizeDoi("https://dx.doi.org/10.5281/zenodo.1") === "10.5281/zenodo.1", "normalizeDoi folds a dx.doi.org URL");
ok(M.normalizeDoi("https://www.doi.org/10.1/x") === "10.1/x", "normalizeDoi tolerates a www. resolver host");
ok(M.normalizeDoi("HTTPS://DOI.ORG/10.1/X") === "10.1/X", "normalizeDoi is case-insensitive on the resolver prefix (suffix preserved)");
ok(M.normalizeDoi("  https://doi.org/10.1/y  ") === "10.1/y", "normalizeDoi trims surrounding whitespace");
ok(M.normalizeDoi("10.1093/gji/xyz") === "10.1093/gji/xyz", "normalizeDoi leaves a BARE DOI untouched");
ok(M.normalizeDoi("not a doi at all") === "not a doi at all", "normalizeDoi leaves a non-DOI string untouched");
ok(M.normalizeDoi("https://example.org/paper") === "https://example.org/paper", "normalizeDoi leaves a NON-doi.org URL untouched (it is not a DOI resolver)");
ok(M.normalizeDoi("") === "" && M.normalizeDoi(null) === "", "normalizeDoi handles empty / null");
// wiring: R3 folded the single publication DOI into per-row publication rows whose .p-doi input normalises
// on blur (via normalizeDoi directly); the funding DOI still uses wireDoiBlur; a related-identifier row
// normalises ONLY when its type is DOI (a URL-typed row keeps its URL).
ok(/class="p-doi"/.test(html) && /doiInp\.addEventListener\("blur"/.test(html),
   "the per-row publication DOI field normalises on blur");
ok(!/id="m_pubdoi"/.test(html) && !/id="m_pub"/.test(html), "the retired single publication fields (m_pub/m_pubdoi) are gone");
ok(/wireDoiBlur\(wrap\.querySelector\("\.f-doi"\)\)/.test(html), "the funding DOI field is wired for DOI normalisation on blur");
ok(/wireConditionalDoiBlur\(wrap\.querySelector\("\.ri-identifier"\), wrap\.querySelector\("\.ri-type"\)\)/.test(html),
   "a related-identifier row normalises its identifier ONLY when the type is DOI (URL-typed rows untouched)");

// ---- R3: the collection block is its own collapsed card (own <details>, exact heading), renumbered. ----
ok(/<details class="tier" id="tierCollection">/.test(html), "the collection block is its own tier-style <details> card");
ok(/<h2>4\. Was this survey part of a collection \/ program \(eg AusLAMP\)\?<\/h2>/.test(html),
   "the collection card carries the exact owner-ruled heading (numbered 4)");
ok(/<h2>5\. I know my metadata<\/h2>/.test(html) && /<h2>6\. Check and package<\/h2>/.test(html),
   "the following sections are renumbered consistently (5. metadata, 6. check and package)");
// the collection FIELDS (and the collections.json autofill IDs) are intact inside the new card, so emission is unchanged.
for (const id of ["m_coll_id", "m_coll_title", "m_coll_type", "m_coll_status", "m_coll_year", "m_coll_desc", "collDatalist", "collHint"])
  ok(new RegExp('id="' + id + '"').test(html), "collection field/autofill id preserved in the new card: " + id);
const yColl = M.buildSurveyYaml({ ...base, collection_id: "auslamp", collection_title: "AusLAMP", collection_type: "programme" });
ok(/collection:\s*\n\s*id: "auslamp"\s*\n\s*title: "AusLAMP"\s*\n\s*type: "programme"/.test(yColl),
   "collection emission is unchanged by the card move (id/title/type still emitted)");

// ---- R2: the download-zip path is hidden on a live gateway (visibility wiring only; zip code intact). ----
ok(/const bp=\$\("btnPackage"\); if\(bp\) bp\.style\.display="none";/.test(html),
   "showGatewayUI hides the package .zip button when the gateway probe passes");
ok(!/Package \.zip to email \(fallback path\)/.test(html), "the old rewording of the package button is gone (it is hidden, not reworded)");
ok(/async function buildPackage/.test(html) && /function buildSubmissionMd/.test(html),
   "R2 is visibility-only: the zip packager code is kept intact");

// R3 harvest tests are async (harvestDoi returns a Promise); run them, THEN report + exit.
r3HarvestTests().then(() => {
  console.log(fail ? `\n${fail} FAILED` : "\nALL PASSED (add-survey logic)");
  process.exit(fail ? 1 : 0);
}).catch(e => { console.error("FAIL: async R3 harvest tests threw", e); process.exit(1); });
