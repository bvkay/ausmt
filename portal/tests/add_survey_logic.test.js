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

// publications[] built from the related-publication fields (title / DOI).
const yPub = M.buildSurveyYaml({ ...base, license_declaration: false, pub: "Smith et al. 2024", pub_doi: "10.1093/gji/xyz" });
ok(/publications:\s*\n\s*- title: "Smith et al\. 2024"\s*\n\s*doi: "10\.1093\/gji\/xyz"/.test(yPub),
   "publications[] carries {title, doi} from the related-publication fields");
ok(/schema_version: "0.3"/.test(yPub), "a publications[] entry declares schema_version 0.3");
ok(/- doi: "10\.5/.test(M.buildSurveyYaml({ ...base, license_declaration: false, pub: "", pub_doi: "10.5281/zenodo.1" })),
   "a DOI-only publication emits a bare {doi} entry");

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
const ALLOWED_CONN = u => /^\//.test(u) || /^https:\/\/api\.ror\.org\//.test(u);
const badConns = conns.filter(u => !ALLOWED_CONN(u) && /^https?:/.test(u));
ok(badConns.length === 0, "every fetch()/XHR target is same-origin or the allow-listed ROR API; new origins: " + JSON.stringify(badConns));
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
ok(/attribution:\s*\n\s*declared_by: "Ada L"\s*\n\s*declared_date: 2026-07-13/.test(yAttr),
   "buildSurveyYaml persists attribution.declared_by + declared_date");
ok(/schema_version: "0.3"/.test(yAttr), "a package carrying attribution declares schema_version 0.3");
ok(!/attribution:/.test(M.buildSurveyYaml({ ...base, license_declaration: false })),
   "no attribution block when the licence declaration is not made");

console.log(fail ? `\n${fail} FAILED` : "\nALL PASSED (add-survey logic)");
process.exit(fail ? 1 : 0);
