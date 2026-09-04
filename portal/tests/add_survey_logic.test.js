// Node test for the pure logic embedded in add-survey.html. REWRITTEN for the "files first, five minutes,
// enrich later" contribution redesign: the tiered form, the NEW emission shape (identifiers-
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

// DMS-format INFO block (NSW re-export style): HEAD and INFO genuinely agree to ~4 m. A
// decimal-only INFO regex truncated '-28:31:33.45' to -28, manufacturing a ~0.53 deg (~55 km)
// phantom conflict at every such station.
const NSW_DMS = '>HEAD\nDATAID="A23"\nLAT=-28:31:33.593\nLONG=+152:1:33.241\n\n>INFO\n  LATITUDE    :   -28:31:33.45\n  LONGITUDE   :   152:01:34.43\n\n>FREQ\n1 10 100\n>ZXYR\n1 2 3\n';
const pn = M.parseEdi(NSW_DMS);
ok(Math.abs(pn.info_lat - (-(28 + 31 / 60 + 33.45 / 3600))) < 1e-6, "DMS INFO lat parsed, not truncated at the colon");
ok(Math.abs(pn.info_lon - (152 + 1 / 60 + 34.43 / 3600)) < 1e-6, "DMS INFO lon parsed");
ok(Math.abs(pn.lat - pn.info_lat) < 1e-3, "HEAD and DMS INFO agree to metres");
ok(pn.coord_flag == null, "agreeing DMS blocks not flagged as a conflict");
const base = { name: "X", slug: "x", organisation: "O", country: "Australia", license: "CC-BY-4.0", access: "open",
               uploader_name: "n", uploader_email: "a@b.co", authority_to_submit: true, license_declaration: true };

// ============================ SOFTENED station-location gate ===============================================
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
// deriveSlug is EXPORTED (it moved into the pure-logic section when the SLUG_MAX cap landed), so this
// exercises the real function rather than re-evaluating a copy scraped out of the HTML — the scrape
// broke the moment deriveSlug referenced a module-scope constant.
ok(typeof M.deriveSlug === "function", "the page exports a deriveSlug() that auto-fills the folder slug from the name");
for (const name of ["Example MT Survey 2026", "AusLAMP: SA (block 4)!", "  spaced  &  odd  "]) {
  const slug = M.deriveSlug(name);
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
// no em dashes in the redesigned copy (the rule: "No em dashes anywhere").
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

// ============================ SOFTENED DATAID gate ==================================================
// deriveDataId: a missing DATAID auto-derives from the FILENAME (extension stripped, then sanitised).
ok(M.deriveDataId("ROX000.edi") === "ROX000", "deriveDataId strips the .edi extension");
ok(M.deriveDataId("Line1__Station7_1.edi") === "Line1__Station7_1", "deriveDataId keeps a safe filename stem");
ok(M.deriveDataId("weird name!.edi") === "weird-name-", "deriveDataId sanitises unsafe filename chars");
ok(M.deriveDataId("A B.mth5") === "A-B", "deriveDataId strips .mth5 too");
// effectiveDataId: real DATAID wins, else the filename-derived fallback.
ok(M.effectiveDataId({ name: "whatever.edi", dataid: "ROX9" }) === "ROX9", "effectiveDataId: real DATAID wins");
ok(M.effectiveDataId({ name: "no-id.edi", dataid: null }) === "no-id", "effectiveDataId: falls back to the filename stem");

// ediNameGate: a MISSING DATAID does not error on its own (auto-derived); a distinct set is clean.
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

// ============================ DOI-first publications + citation harvest ============================
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

// dates block emits only when a date is provided; year + ISO stay bare, free text is quoted.
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

// ---- (PII scrub): the packaged submission .zip must NOT embed submitter email/ORCID ----
const pkgBlock = html.slice(html.indexOf("async function buildPackage"), html.indexOf('$("btnPackage").onclick'));
ok(!/submitter:\{[^}]*email:\s*meta\.uploader_email/.test(pkgBlock), "MANIFEST submitter block does NOT write uploader_email");
ok(!/submitter:\{[^}]*orcid:\s*meta\.uploader_orcid/.test(pkgBlock), "MANIFEST submitter block does NOT write uploader_orcid");
ok(/submitter:\{[^}]*name:\s*meta\.uploader_name/.test(pkgBlock), "MANIFEST submitter block still keeps the name");
ok(!/uploader_email/.test(pkgBlock), "the packager block does NOT reference uploader_email");
ok(/m_up_email/.test(html), "the uploader email form field itself is still present (feeds Stage-2 gateway)");

// ============================ direct-upload pure logic (unchanged) ============================
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

// ============================ connection targets + key-request stub ============================
const conns = [...html.matchAll(/(?:fetch|\.open)\(\s*(?:"[^"]*",\s*)?"([^"]+)"/g)].map(m => m[1])
  .filter(u => !/^\$\{/.test(u));
// same-origin, the ROR API, or the citation-harvest registries (Crossref + DataCite). These three
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

// ============================ ROUND 2 =================================================

// ---- slug-collision awareness. servedSlugMap folds surveys.json {name: SMETA} -> {slug: name};
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

// ============================ The retired flat credit keys leave the public form ============
// LANE-CONTRACT-FORM-CREDIT: the form stops writing lead_investigator/principal_investigators (the
// migration deleted them corpus-wide and no reader survives), and the credit questions are rewritten
// in plain language onto the homes.
const yRetired = M.buildSurveyYaml({ ...base, pi: "Ada Lovelace", pi_orcid: "0000-0002-1825-0097",
  principal_investigators: [{ name: "Grace Hopper", orcid: "" }] });
for (const retired of ["lead_investigator", "principal_investigators"]) {
  ok(!yRetired.includes(retired),
     "RETIRED credit key never emitted, even from a scripted meta that still carries it: " + retired);
}
ok(!/id="m_pi"/.test(html) && !/id="m_pi_orcid"/.test(html) && !/id="piRows"/.test(html)
   && !/id="addPi"/.test(html) && !/readPrincipalInvestigators/.test(html),
   "the lead/principal-investigator inputs, rows and reader are gone from the form");
ok(!/When a lead investigator is set the portal credits the lead/.test(html.replace(/\s+/g, " ")),
   "the FALSE served-citation precedence hint is deleted (the engine cites creators, else the org)");
ok(/Leave blank and AusMT cites the organisation and the year/.test(html.replace(/\s+/g, " ")),
   "the creators hint states the TRUE fallback (organisation + year)");
ok(!/or the lead \/ principal investigators above/.test(html.replace(/\s+/g, " ")),
   "the creators hint no longer points at the retired fields");

// ---- tier 3 question set (the plain-language questions, in the order the form asks them) ----
const flat = html.replace(/\s+/g, " ");
for (const q of ["Who should the citation name, in order?", "Who led this survey?", "Who did what?",
                 "Does this dataset already have a citation or DOI?",
                 "Which organisations were involved, and how?",
                 "Is there wording you must include?",
                 "When was this dataset published?"]) {
  ok(flat.includes(q), "tier 3 asks the ratified question: " + q);
}
ok(flat.indexOf("Who should the citation name, in order?") < flat.indexOf("Who led this survey?")
   && flat.indexOf("Who led this survey?") < flat.indexOf("Who did what?"),
   "the credit questions run citation names -> who led -> who did what");
ok(flat.indexOf("Who did what?") < flat.indexOf("5. I know my metadata"),
   "contributors (Who did what?) moved UP out of the advanced tier");

// ---- "Who led this survey?" -> ONE ProjectLeader contributors row ----
const yLead = M.buildSurveyYaml({ ...base, lead_name: "Duan, Jingming",
                                  lead_orcid: "0000-0002-1825-0097" });
ok(/contributors:\s*\n\s*- name: "Duan, Jingming"\s*\n\s*name_type: person\s*\n\s*role: ProjectLeader\s*\n\s*orcid: "0000-0002-1825-0097"/.test(yLead),
   "'Who led this survey?' emits ONE contributors row {name, name_type: person, role: ProjectLeader, orcid}");
ok(!/lead_investigator/.test(yLead), "the lead question never writes a retired key");
const yLeadNoOrcid = M.buildSurveyYaml({ ...base, lead_name: "Duan, Jingming" });
ok(!/orcid:/.test(yLeadNoOrcid.split("contributors:")[1] || ""),
   "an ORCID-less lead emits no orcid key (absent -> absent)");
ok(!/contributors:/.test(M.buildSurveyYaml({ ...base })), "no lead, no contributors key");
const yLeadDup = M.buildSurveyYaml({ ...base, lead_name: "Duan, Jingming",
  contributors: [{ name: "Duan, Jingming", name_type: "person", role: "ProjectLeader" }] });
ok((yLeadDup.match(/role: ProjectLeader/g) || []).length === 1,
   "the lead row is deduped against an identical typed contributors row");
const yLeadPlus = M.buildSurveyYaml({ ...base, lead_name: "Duan, Jingming",
  contributors: [{ name: "Zonge Engineering", name_type: "organisation", role: "DataCollector" }] });
ok(yLeadPlus.indexOf('- name: "Duan, Jingming"') < yLeadPlus.indexOf('- name: "Zonge Engineering"'),
   "the lead row is FIRST in contributors, ahead of the typed rows");

// --- "Does this dataset already have a citation or DOI?" -> citation + ONE related row ----
const yCite = M.buildSurveyYaml({ ...base,
  citation_text: "GSSA (2016). AusLAMP South Australia. [Data set].",
  citation_identifier: "https://doi.org/10.25914/abc" });
ok(/citation:\s*\n\s*preferred_text: "GSSA \(2016\)\. AusLAMP South Australia\. \[Data set\]\."\s*\n\s*text_source: source_provided/.test(yCite),
   "a filled citation question emits preferred_text (quoted verbatim) + a bare text_source");
ok(!/^\s*preferred_identifier:/m.test(yCite),
   "the form NEVER writes citation.preferred_identifier (D18: designation is curation)");
ok(/citation\.preferred_identifier/.test(yCite),
   "...it names it only inside the curator note comment, which no parser ever sees");
ok(/- identifier: "10\.25914\/abc"/.test(yCite),
   "the related-row DOI equals the NORMALISED paste (the resolver URL is folded to the bare DOI)");
ok(/identifier_type: DOI/.test(yCite), "a DOI-shaped paste types the row DOI");
ok(!/identifies:/.test(yCite.split("related_identifiers:")[1] || ""),
   "'curator decides' (the default) omits the identifies key");
ok(/# CONTRIBUTOR: pasted as this dataset's citation identifier; curator: designate via identity_classification\.represents and citation\.preferred_identifier/.test(yCite),
   "the pasted identifier carries the curator note as a YAML COMMENT above its row");
const yCiteUrl = M.buildSurveyYaml({ ...base, citation_identifier: "https://ecat.ga.gov.au/geonetwork/x" });
ok(/- identifier: "https:\/\/ecat\.ga\.gov\.au\/geonetwork\/x"\s*\n\s*identifier_type: URL/.test(yCiteUrl),
   "an http(s) non-DOI paste types the row URL and keeps the URL whole");
ok(!/citation:/.test(yCiteUrl), "an identifier with NO wording emits no citation block");
const yCiteTextOnly = M.buildSurveyYaml({ ...base, citation_text: "Some wording" });
ok(/text_source: source_provided/.test(yCiteTextOnly), "text_source rides a non-empty preferred_text");
ok(!/text_source/.test(M.buildSurveyYaml({ ...base })),
   "text_source is NEVER emitted without a preferred_text (D17)");
const yCiteLevel = M.buildSurveyYaml({ ...base, citation_identifier: "10.25914/abc",
                                       citation_identifies: "entire" });
ok(/identifies: entire/.test(yCiteLevel), "a chosen data level emits the bare vocab token");
const yCiteDedupe = M.buildSurveyYaml({ ...base, citation_identifier: "10.25914/abc",
  related_identifiers: [{ identifier: "10.25914/abc", identifier_type: "DOI", identifies: "entire" }] });
ok((yCiteDedupe.match(/- identifier:/g) || []).length === 1,
   "the citation row is deduped against an existing 'This dataset elsewhere' row");

// ---- "Which organisations were involved, and how?" -> organisations[] (+ the seeded custodian) ----
const yOrg = M.buildSurveyYaml({ ...base, organisation: "Geological Survey of South Australia",
                                 ror: "https://ror.org/04y8k6r48" });
ok(/organisations:\s*\n\s*# INFERRED-REVIEW: custodian seeded from the essential organisation; confirm roles\s*\n\s*- name: "Geological Survey of South Australia"\s*\n\s*ror: "https:\/\/ror\.org\/04y8k6r48"\s*\n\s*roles:\s*\n\s*- custodian\s*\n\s*primary_custodian: true/.test(yOrg),
   "the essential Organisation + ROR seeds a MARKED custodian row with primary_custodian: true");
ok(!/publisher/.test(yOrg), "publisher is NEVER inferred (only ticked)");
const yOrgNoRor = M.buildSurveyYaml({ ...base, organisation: "Org" });
ok(!/ror:\s*null/.test(yOrgNoRor.split("organisations:")[1] || ""),
   "a blank ROR omits the key on the seeded row (never ror: null)");
const yOrgRows = M.buildSurveyYaml({ ...base, organisation: "GSSA", organisations: [
  { name: "Geoscience Australia", ror: "https://ror.org/04ge02x20", roles: ["publisher", "distributor"] },
  { name: "GSSA", roles: ["data_collector"] },
  { name: "", roles: ["publisher"] }] });
ok(/- name: "Geoscience Australia"[\s\S]*?roles:\s*\n\s*- publisher\s*\n\s*- distributor/.test(yOrgRows),
   "a named organisation row emits its ticked roles in vocabulary order");
ok(/- name: "GSSA"\s*\n\s*roles:\s*\n\s*- custodian\s*\n\s*- data_collector\s*\n\s*primary_custodian: true/.test(yOrgRows),
   "naming the essential organisation again MERGES its roles into the seeded custodian row");
ok((yOrgRows.match(/- name: "/g) || []).length === 2, "a nameless organisation row is dropped");
const yOrgNoRole = M.buildSurveyYaml({ ...base, organisation: "GSSA", organisations: [
  { name: "Roleless Org", ror: "https://ror.org/04ge02x20", roles: [] }] });
ok(!/Roleless Org/.test(yOrgNoRole) && (yOrgNoRole.match(/- name: "/g) || []).length === 1,
   "a named organisation row with no role ticked is dropped (it states nothing; the engine would drop it silently)");
const yOrgGuard = M.buildSurveyYaml({ ...base, organisation: "O",
  organisations: [{ name: "X", roles: ["owner\ninjected: true", "publisher"] }] });
ok(!/injected:/.test(yOrgGuard) && !/- owner/.test(yOrgGuard),
   "an out-of-vocab organisation role is dropped; a newline-injection role smuggles no YAML key");

// ---- "Is there wording you must include?" -> acknowledgements[] ----
const yAck = M.buildSurveyYaml({ ...base, acknowledgements: [
  { text: "Data supplied by the GSSA.", type: "custodian", source: "GSSA licence deed" },
  { text: "Plain wording." },
  { text: "", type: "community" }] });
ok(/acknowledgements:\s*\n\s*- text: "Data supplied by the GSSA\."\s*\n\s*type: custodian\s*\n\s*source: "GSSA licence deed"/.test(yAck),
   "acknowledgements emit quoted text, a bare type token and a quoted source");
ok(/- text: "Plain wording\."\s*\n(?!\s*type:)/.test(yAck), "type/source are omitted when blank");
ok((yAck.match(/- text:/g) || []).length === 2, "a textless acknowledgement row is dropped");
ok(!/acknowledgements:/.test(M.buildSurveyYaml({ ...base })), "no key when there is no wording");
const yAckGuard = M.buildSurveyYaml({ ...base,
  acknowledgements: [{ text: "W", type: "mystery\ninjected: true" }] });
ok(!/injected:/.test(yAckGuard) && !/^\s+type:/m.test(yAckGuard),
   "an out-of-vocab acknowledgement type is dropped, never emitted");

// ---- "When was this dataset published?" -> dates.issued (bare ISO date) ----
const yIssued = M.buildSurveyYaml({ ...base, date_issued: "2016-05-01" });
ok(/dates: \{ issued: 2016-05-01 \}/.test(yIssued), "dates.issued emits as a BARE ISO date");
const yIssuedBoth = M.buildSurveyYaml({ ...base, date_start: "2015", date_end: "2016",
                                        date_issued: "2016-05-01" });
ok(/dates: \{ start: 2015, end: 2016, issued: 2016-05-01 \}/.test(yIssuedBoth),
   "issued rides alongside the acquisition window without disturbing it");
ok(!/issued/.test(M.buildSurveyYaml({ ...base, date_issued: "2016" })),
   "a bare YEAR is never emitted as issued (it is a publication DATE, never inferred)");
ok(M.validateSurvey({ ...base, date_issued: "2016" }, cleanEdis, []).items
    .some(i => i.check === "dates" && i.level === "FAIL"),
   "a bare-year issued is a blocking FAIL client-side, the same class the validator uses");
ok(!M.validateSurvey({ ...base, date_issued: "2016-05-01" }, cleanEdis, []).items
    .some(i => i.check === "dates" && i.level === "FAIL"),
   "a proper ISO issued raises no FAIL");

// ---- vocab parity for the new questions, against the vendored validator + the curator editor ----
const vOrgRoles = (validatorSrc.match(/ORG_ROLES_ORDERED\s*=\s*\(([\s\S]*?)\)/) || [])[1] || "";
const vOrgRoleList = [...vOrgRoles.matchAll(/"([^"]+)"/g)].map(m => m[1]);
ok(JSON.stringify(M.ORG_ROLES_ORDERED) === JSON.stringify(vOrgRoleList),
   "portal ORG_ROLES_ORDERED matches the vendored validator's tuple: " + JSON.stringify(vOrgRoleList));
const eOrgRoles = (editorSrc.match(/ORG_ROLES_ORDERED\s*=\s*\(([\s\S]*?)\)/) || [])[1] || "";
ok(JSON.stringify(M.ORG_ROLES_ORDERED) === JSON.stringify([...eOrgRoles.matchAll(/"([^"]+)"/g)].map(m => m[1])),
   "portal ORG_ROLES_ORDERED matches gateway editor_form.ORG_ROLES_ORDERED");
ok(M.ORG_ROLES_OFFERED.indexOf("hosting_institution") < 0 && M.ORG_ROLES_OFFERED.length === M.ORG_ROLES_ORDERED.length - 1,
   "the form offers every organisation role EXCEPT hosting_institution (an AusMT export-side role)");
const vAckTypes = (validatorSrc.match(/ACKNOWLEDGEMENT_TYPES\s*=\s*frozenset\(\{([\s\S]*?)\}\)/) || [])[1] || "";
const vAckList = [...vAckTypes.matchAll(/"([^"]+)"/g)].map(m => m[1]).sort();
ok(JSON.stringify([...M.ACKNOWLEDGEMENT_TYPES].sort()) === JSON.stringify(vAckList),
   "portal ACKNOWLEDGEMENT_TYPES matches the vendored validator's set: " + JSON.stringify(vAckList));
const eAckTypes = (editorSrc.match(/ACKNOWLEDGEMENT_TYPES\s*=\s*\(([\s\S]*?)\)/) || [])[1] || "";
ok(JSON.stringify([...M.ACKNOWLEDGEMENT_TYPES].sort())
   === JSON.stringify([...eAckTypes.matchAll(/"([^"]+)"/g)].map(m => m[1]).sort()),
   "portal ACKNOWLEDGEMENT_TYPES matches gateway editor_form.ACKNOWLEDGEMENT_TYPES");
const vTextSrc = (validatorSrc.match(/CITATION_TEXT_SOURCES\s*=\s*frozenset\(\{([\s\S]*?)\}\)/) || [])[1] || "";
ok([...vTextSrc.matchAll(/"([^"]+)"/g)].map(m => m[1]).indexOf(M.CITATION_TEXT_SOURCE_FORM) >= 0,
   "the fixed text_source the form writes is in the validator's CITATION_TEXT_SOURCES vocab");
ok(M.CITATION_TEXT_SOURCE_FORM === "source_provided",
   "a contributor's wording is ALWAYS source_provided (ausmt_generated is never a contributor value)");

// --- DOI normalisation (resolver URL -> bare DOI; bare + non-DOI + URL-typed left untouched). ----
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
// wiring: folded the single publication DOI into per-row publication rows whose .p-doi input normalises
// on blur (via normalizeDoi directly); the funding DOI still uses wireDoiBlur; a related-identifier row
// normalises ONLY when its type is DOI (a URL-typed row keeps its URL).
ok(/class="p-doi"/.test(html) && /doiInp\.addEventListener\("blur"/.test(html),
   "the per-row publication DOI field normalises on blur");
ok(!/id="m_pubdoi"/.test(html) && !/id="m_pub"/.test(html), "the retired single publication fields (m_pub/m_pubdoi) are gone");
ok(/wireDoiBlur\(wrap\.querySelector\("\.f-doi"\)\)/.test(html), "the funding DOI field is wired for DOI normalisation on blur");
ok(/wireConditionalDoiBlur\(wrap\.querySelector\("\.ri-identifier"\), wrap\.querySelector\("\.ri-type"\)\)/.test(html),
   "a related-identifier row normalises its identifier ONLY when the type is DOI (URL-typed rows untouched)");

// --- The collection block is its own collapsed card (own <details>, exact heading), renumbered. ----
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

// --- The download-zip path is hidden on a live gateway (visibility wiring only; zip code intact). ----
ok(/const bp=\$\("btnPackage"\); if\(bp\) bp\.style\.display="none";/.test(html),
   "showGatewayUI hides the package .zip button when the gateway probe passes");
ok(!/Package \.zip to email \(fallback path\)/.test(html), "the old rewording of the package button is gone (it is hidden, not reworded)");
ok(/async function buildPackage/.test(html) && /function buildSubmissionMd/.test(html),
   "R2 is visibility-only: the zip packager code is kept intact");

// ============================ EMTF XML as a first-class input ==================================================
// The page must ADMIT EMTF XML the way it admits EDI and MTH5: in the file picker's accept list, in the
// drop-zone copy, in the kind classification, and in the validation gate. Pre-fix the accept list was
// ".edi,.h5,.mth5", so a submitter literally could not select their .xml files.
ok(/accept="\.edi,\.xml,\.h5,\.mth5"/.test(html), "the file input accepts .xml alongside .edi and .mth5/.h5");
ok(/Drop <b>\.edi<\/b>, <b>\.xml<\/b>, or <b>\.mth5 \/ \.h5<\/b> files here/.test(html)
   || /Drop <b>\.edi<\/b>, <b>\.xml<\/b> or <b>\.mth5 \/ \.h5<\/b> files here/.test(html),
   "the drop zone names .xml");
ok(/EDI, EMTF XML and MTH5 transfer functions are all accepted/.test(html),
   "the file hint states all three accepted formats");
ok(/kind:"emtfxml"/.test(html), "a dropped .xml is classified as an emtfxml transfer function");
ok(/function xmlFiles\(\)/.test(html), "the page keeps an EMTF XML file list beside ediFiles()/mth5Files()");
ok(/transfer_functions\/emtfxml\//.test(html), "the packager writes EMTF XML into transfer_functions/emtfxml/");

// emtfxmlLooksReal: the browser-side anti-masquerade check, the sibling of the .edi NUL-byte gate.
ok(M.emtfxmlLooksReal('<?xml version="1.0"?>\n<EM_TF><Site/></EM_TF>'), "a real EMTF XML is recognised");
ok(M.emtfxmlLooksReal("<EM_TF>"), "the bare root element is enough");
ok(!M.emtfxmlLooksReal('<?xml version="1.0"?>\n<rss><channel/></rss>'), "an unrelated XML is NOT an EMTF XML");
ok(!M.emtfxmlLooksReal(""), "empty content is not an EMTF XML");
ok(!M.emtfxmlLooksReal(null), "null content does not throw and is not an EMTF XML");

// validateSurvey's structure gate: EMTF XML alone is a complete submission.
const xmlOnly = M.validateSurvey({ ...base, locations_confirmed: true }, [], [],
                                 [{ name: "S01.xml", emtf: true }]);
ok(!xmlOnly.items.some(i => i.check === "structure" && i.level === "FAIL"),
   "an EMTF-XML-only submission raises no 'no transfer-function files' FAIL");
ok(xmlOnly.items.some(i => i.check === "emtfxml" && i.level === "WARNING" && /submission pipeline/.test(i.message)),
   "an accepted EMTF XML carries the honest 'validated in the pipeline, not in this browser' note");
const noneAtAll = M.validateSurvey({ ...base, locations_confirmed: true }, [], [], []);
ok(noneAtAll.items.some(i => i.check === "structure" && i.level === "FAIL" && /EDI, EMTF XML or MTH5/.test(i.message)),
   "a submission with no transfer functions at all still FAILs, naming all three formats");
const badXml = M.validateSurvey({ ...base, locations_confirmed: true }, [], [],
                                [{ name: "notatf.xml", emtf: false }]);
ok(badXml.items.some(i => i.check === "emtfxml" && i.level === "FAIL" && /EM_TF/.test(i.message)),
   "a .xml that is not an EMTF transfer function is a blocking FAIL, not a silent pass");
ok(badXml.counts.FAIL > 0, "the masquerading .xml blocks submission");

// ============================ SLUG LENGTH CAP (the MTH5 truncation) =======================================
// A slug over 45 characters is truncated to slug[:45] as the MTH5 survey group name, and the round-trip
// gate then withholds every station .h5 in the survey — observed live on a real 54-character slug.
// SLUG_MAX caps the DERIVED value and blocks a hand-typed one. These tests fail if either half regresses.
const LONG_NAME = "AusLAMP EFTF Phase 1 - Northern Territory and Queensland (Geoscience Australia)";
const OBSERVED_BAD = "auslamp-eftf-phase-1-northern-territory-and-queensland";  // 54 chars, the live case

ok(M.SLUG_MAX === 40, "SLUG_MAX is 40 (kept under the 45-character MTH5 group-name truncation)");
ok(M.SLUG_MAX < 45, "SLUG_MAX leaves margin under the observed truncation point");

const derived = M.deriveSlug(LONG_NAME);
ok(derived.length <= M.SLUG_MAX, `deriveSlug caps at SLUG_MAX (got ${derived.length}: ${derived})`);
ok(M.slugValid(derived), "the derived slug is always submittable (charset + length)");
ok(!/-$/.test(derived), "no trailing hyphen after the cut");
ok(!/--/.test(derived), "no doubled hyphen after the cut");
ok(derived !== OBSERVED_BAD.slice(0, M.SLUG_MAX) || !derived.endsWith("-"),
   "the cut prefers a hyphen boundary over severing a word");
ok(M.deriveSlug(OBSERVED_BAD).length <= M.SLUG_MAX, "re-deriving from the live bad slug also caps");

// short names are untouched — the cap must not alter the existing corpus's derivations
["auslamp-tas", "ccmt-2017", "vulcan-2022", "auslamp-sa-north-flinders-2013"].forEach(s => {
  ok(M.deriveSlug(s) === s, `short slug '${s}' passes through deriveSlug unchanged`);
});

ok(!M.slugValid(OBSERVED_BAD), "the live 54-character slug is now INVALID (it was accepted before)");
ok(M.slugValid("auslamp-nt-qld-2016-19"), "a sensible short slug stays valid");
ok(!M.slugValid("a".repeat(41)), "41 characters is rejected");
ok(M.slugValid("a".repeat(40)), "40 characters is accepted (boundary)");

// and the blocking gate reports it as a LENGTH problem, not a charset one
const longSlugRes = M.validateSurvey({ ...base, slug: OBSERVED_BAD, locations_confirmed: true },
                                     cleanEdis, []);
const slugItem = longSlugRes.items.find(i => i.check === "slug");
ok(!!slugItem && slugItem.level === "FAIL", "an over-long slug is a blocking FAIL");
ok(!!slugItem && /54 characters/.test(slugItem.message), "the message names the actual length");
ok(!!slugItem && /limit is 40/.test(slugItem.message), "the message names the limit");
ok(!!slugItem && !/lowercase-hyphenated/.test(slugItem.message),
   "a too-long but charset-clean slug is NOT misreported as a charset problem");

// Harvest tests are async (harvestDoi returns a Promise); run them, THEN report + exit.
r3HarvestTests().then(() => {
  console.log(fail ? `\n${fail} FAILED` : "\nALL PASSED (add-survey logic)");
  process.exit(fail ? 1 : 0);
}).catch(e => { console.error("FAIL: async R3 harvest tests threw", e); process.exit(1); });
