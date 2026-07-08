// Node test for the pure logic embedded in add-survey.html: parseEdi DMS-sign-bug detection,
// the station-locations confirmation gate, and buildSurveyYaml (coordinate_resolution + region).
// Self-contained (synthetic EDIs, no external data). Run via tests/test_add_survey_logic.py or:
//   node tests/add_survey_logic.test.js
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

const edis = [{ name: "WG-1.edi", parsed: p }];
const base = { name: "X", slug: "x", organisation: "O", country: "Australia", license: "CC-BY-4.0", access: "open",
               uploader_name: "n", uploader_email: "a@b.co", authority_to_submit: true, license_declaration: true };
ok(M.validateSurvey({ ...base, locations_confirmed: false }, edis, []).items.some(i => i.check === "locations" && i.level === "FAIL"),
   "unconfirmed station locations -> FAIL (packaging gated)");
ok(!M.validateSurvey({ ...base, locations_confirmed: true }, edis, []).items.some(i => i.check === "locations" && i.level === "FAIL"),
   "confirmed station locations -> no FAIL");
ok(M.validateSurvey({ ...base, locations_confirmed: false }, edis, []).items.some(i => i.check === "coordinates" && /DMS sign bug/.test(i.message)),
   "DMS conflict surfaced as a coordinates WARNING");

const y = M.buildSurveyYaml({ ...base, data_types: ["BBMT"], region: "South Australia",
                              coord_resolution: { dms_sign: "info", basis: "confirmed on map" } });
ok(/coordinate_resolution:\s*\n\s*dms_sign: info/.test(y), "survey.yaml emits coordinate_resolution dms_sign: info");
ok(/region: "South Australia"/.test(y), "survey.yaml emits region");
ok(!/coordinate_resolution:/.test(M.buildSurveyYaml({ ...base, data_types: ["BBMT"] })),
   "no coordinate_resolution when nothing was resolved");

// ---- access block: embargo_until + contact (audit 5.2) ----
// buildSurveyYaml must emit the submitter's embargo date and access contact into the access block
// when supplied (non-open levels), and leave BOTH null when the fields are blank / level is open.
const yEmb = M.buildSurveyYaml({ ...base, access: "embargoed",
                                 embargo_until: "2027-02-01", access_contact: "custodian@agency.gov.au" });
ok(/access:\s*\n\s*level: embargoed\s*\n\s*embargo_until: 2027-02-01/.test(yEmb),
   "survey.yaml emits access.embargo_until when the date is filled");
ok(/contact: "custodian@agency\.gov\.au"/.test(yEmb),
   "survey.yaml emits access.contact when provided");
const yOpen = M.buildSurveyYaml({ ...base, access: "open" });
ok(/access:\s*\n\s*level: open\s*\n\s*embargo_until: null\s*\n\s*contact: null/.test(yOpen),
   "survey.yaml keeps embargo_until and contact null for an open survey");
const yEmbNoDate = M.buildSurveyYaml({ ...base, access: "metadata_only", access_contact: "" });
ok(/embargo_until: null/.test(yEmbNoDate),
   "survey.yaml emits embargo_until: null when the date is left blank");

// ---- client-side slug mirror (audit minor: validator parity) ----
// slugValid MIRRORS the authoritative rule in gateway/tests/fixtures/vendored_validation/
// validate_survey.py:331  re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", slug). Uppercase, spaces, underscores,
// dots, slashes and leading/trailing hyphens are all rejected; lowercase-hyphenated is accepted.
ok(M.slugValid("example-survey-2026") === true, "slugValid: lowercase-hyphenated slug accepted");
ok(M.slugValid("example") === true, "slugValid: single lowercase token accepted");
ok(M.slugValid("Example-Survey") === false, "slugValid: uppercase rejected");
ok(M.slugValid("example survey") === false, "slugValid: spaces rejected");
ok(M.slugValid("example_survey") === false, "slugValid: underscore rejected");
ok(M.slugValid("example.survey") === false, "slugValid: dot rejected");
ok(M.slugValid("-example") === false && M.slugValid("example-") === false, "slugValid: leading/trailing hyphen rejected");
ok(M.slugValid("") === false, "slugValid: empty rejected");
// wired into validateSurvey as a blocking FAIL under the 'slug' check.
const badSlug = M.validateSurvey({ ...base, slug: "Bad_Slug", locations_confirmed: true },
  [{ name: "ok.edi", parsed: M.parseEdi('>HEAD\nDATAID="OK1"\nLAT=-30\nLONG=136\n\n>FREQ\n1 10 100\n>ZXYR\n1 2 3\n') }], []);
ok(badSlug.items.some(i => i.check === "slug" && i.level === "FAIL"),
   "validateSurvey: a malformed slug is a blocking FAIL");
const goodSlug = M.validateSurvey({ ...base, slug: "good-slug", locations_confirmed: true },
  [{ name: "ok.edi", parsed: M.parseEdi('>HEAD\nDATAID="OK1"\nLAT=-30\nLONG=136\n\n>FREQ\n1 10 100\n>ZXYR\n1 2 3\n') }], []);
ok(!goodSlug.items.some(i => i.check === "slug" && i.level === "FAIL"),
   "validateSurvey: a valid slug raises no slug FAIL");

// ---- DATAID-based packaging (task #16) ----
// ediDataId must read the DATAID from the >HEAD block across the real dialect shapes: Geotools/LEMI
// (no indent, quoted), EDL (leading-indented + trailing whitespace, quoted), Phoenix (indented,
// quoted), and an unquoted variant. A realistic olympic-dam header (DATAID="ROX000") is the trigger.
const OLYMPIC = '>HEAD\nDATAID="ROX000"\nACQBY=""\nLAT=-30:37:57.1\nLONG=+136:45:12.9\nELEV=10.0\nUNITS=M\n\n>INFO\n\n>FREQ\n1 10 100\n>ZXYR\n1 2 3\n';
ok(M.ediDataId(OLYMPIC) === "ROX000", "ediDataId reads DATAID from a realistic >HEAD (olympic-dam ROX000)");
ok(M.ediDataId('>HEAD\nDATAID="WG-1"\nLAT=-30\n') === "WG-1", "ediDataId: Geotools/LEMI quoted DATAID with a hyphen");
ok(M.ediDataId(' >HEAD\n\n   DATAID="ST01"                 \n   ACQBY="X"\n') === "ST01", "ediDataId: EDL indented + trailing-whitespace DATAID");
ok(M.ediDataId('>HEAD\n    DATAID="A01"\n') === "A01", "ediDataId: Phoenix indented DATAID");
ok(M.ediDataId('>HEAD\nDATAID=ROX000\n') === "ROX000", "ediDataId: unquoted DATAID tolerated");
ok(M.ediDataId('>HEAD\nLAT=-30\n') === null, "ediDataId: absent DATAID -> null (blocks)");
ok(M.ediDataId('>HEAD\nDATAID=""\n') === null, "ediDataId: empty-quoted DATAID -> null (blocks)");
ok(M.ediDataId("") === null, "ediDataId: empty text -> null");
// Bounded prefix: only the first 64 KB is scanned (the DATAID always lives in the header). A DATAID
// appearing only AFTER 64 KB of padding must NOT be found (proves the read is bounded, not whole-file).
const farId = "x".repeat(70000) + '\nDATAID="LATE"\n';
ok(M.ediDataId(farId) === null, "ediDataId: DATAID beyond the 64 KB prefix is not read (bounded)");

// safeEdiComponent MIRRORS engine build_portal.safe_component: charset [A-Za-z0-9._-], neutralise '..',
// strip leading dots/dashes, never empty. This is the pipeline's own rule for a DATAID -> path, reused.
ok(M.safeEdiComponent("ROX000") === "ROX000", "safeEdiComponent: clean id unchanged");
ok(M.safeEdiComponent("WG-1") === "WG-1", "safeEdiComponent: dash preserved");
ok(M.safeEdiComponent("C6_BxByReplaced") === "C6_BxByReplaced", "safeEdiComponent: underscore preserved");
ok(M.safeEdiComponent("A B") === "A-B", "safeEdiComponent: space -> dash (not in charset)");
ok(M.safeEdiComponent("../../etc/x") === "etc-x", "safeEdiComponent: path traversal neutralised");
ok(M.safeEdiComponent("<img onerror=1>") === "img-onerror-1-", "safeEdiComponent: XSS chars replaced");
ok(M.safeEdiComponent("...ROX") === "ROX", "safeEdiComponent: leading dots stripped");
ok(M.safeEdiComponent("") === "station" && M.safeEdiComponent("///") === "station", "safeEdiComponent: never empty (fallback)");
ok(M.packagedEdiName("ROX000") === "ROX000.edi", "packagedEdiName: <sanitized-DATAID>.edi");

// ---- C38 item 4: safeEdiComponent pinned to the SHARED engine vectors ----
// safeEdiComponent and the engine's build_portal.safe_component are two copies of ONE sanitisation
// rule. Both consume the SAME committed vector file (engine/tests/fixtures/safe_component_vectors.json)
// so they cannot drift apart silently: test_safe_component_vectors.py reds if the engine side diverges;
// this block reds if the JS side does. FAILS IF safeEdiComponent(input, fallback) differs from any
// committed vector — the ad-hoc checks above stay as readable examples; the vectors are the contract.
const VEC = JSON.parse(fs.readFileSync(
  path.join(__dirname, "..", "..", "engine", "tests", "fixtures", "safe_component_vectors.json"), "utf8"));
ok(Array.isArray(VEC.vectors) && VEC.vectors.length >= 20 && typeof VEC.fallback === "string",
   "shared safe_component vectors file loads (" + VEC.vectors.length + " vectors)");
for (const v of VEC.vectors)
  ok(M.safeEdiComponent(v.input, VEC.fallback) === v.expected,
     "safeEdiComponent shared-vector [" + v.kind + "]: " + JSON.stringify(v.input) + " -> " + JSON.stringify(v.expected));

// ediNameGate (submission-time collision guard): clean list -> no errors; duplicate + missing each
// produce a blocking error naming the offending SOURCE filename(s). No silent auto-suffixing.
ok(M.ediNameGate([{ name: "a.edi", dataid: "ROX000" }, { name: "b.edi", dataid: "ROX001" }]).length === 0,
   "ediNameGate: distinct DATAIDs -> no error");
const dup = M.ediNameGate([{ name: "line1__1.edi", dataid: "ROX000" }, { name: "line2__1.edi", dataid: "ROX000" }]);
ok(dup.length === 1 && /line1__1\.edi/.test(dup[0]) && /line2__1\.edi/.test(dup[0]),
   "ediNameGate: duplicate DATAID -> one error naming BOTH source filenames");
const miss = M.ediNameGate([{ name: "noid.edi", dataid: null }]);
ok(miss.length === 1 && /noid\.edi/.test(miss[0]) && /DATAID/.test(miss[0]),
   "ediNameGate: missing DATAID -> error naming the source file");
// two DATAIDs that DIFFER but sanitise to the SAME packaged name still collide (real on-disk clash).
const sdup = M.ediNameGate([{ name: "a.edi", dataid: "ROX 0" }, { name: "b.edi", dataid: "ROX-0" }]);
ok(sdup.length === 1 && /a\.edi/.test(sdup[0]) && /b\.edi/.test(sdup[0]),
   "ediNameGate: DATAIDs that sanitise to the same name collide (both filenames named)");

// The gate is WIRED into validateSurvey as a blocking FAIL (not just a standalone helper). Two EDIs
// with the same DATAID -> a FAIL item under the 'dataid' check whose message names both files.
const dupEdis = [
  { name: "s1.edi", parsed: M.parseEdi('>HEAD\nDATAID="DUP"\nLAT=-30\nLONG=136\n\n>FREQ\n1 10 100\n>ZXYR\n1 2 3\n') },
  { name: "s2.edi", parsed: M.parseEdi('>HEAD\nDATAID="DUP"\nLAT=-31\nLONG=137\n\n>FREQ\n1 10 100\n>ZXYR\n1 2 3\n') },
];
const dupRes = M.validateSurvey({ ...base, locations_confirmed: true }, dupEdis, []);
ok(dupRes.items.some((i) => i.check === "dataid" && i.level === "FAIL" && /s1\.edi/.test(i.message) && /s2\.edi/.test(i.message)),
   "validateSurvey: duplicate DATAID surfaces a blocking FAIL naming both files");
ok(dupRes.counts.FAIL > 0, "validateSurvey: the duplicate-DATAID FAIL blocks submission (counts.FAIL>0)");
// a single, well-named EDI produces NO dataid FAIL (the gate is silent on clean input).
const cleanEdis = [{ name: "ok.edi", parsed: M.parseEdi('>HEAD\nDATAID="OK1"\nLAT=-30\nLONG=136\n\n>FREQ\n1 10 100\n>ZXYR\n1 2 3\n') }];
ok(!M.validateSurvey({ ...base, locations_confirmed: true }, cleanEdis, []).items.some((i) => i.check === "dataid"),
   "validateSurvey: a clean unique DATAID raises no dataid item");

// ---- ROR organisation lookup ----
// The live endpoint MUST be the name-search `query`, NOT the `affiliation` matcher. The affiliation
// matcher is built for parsing full publication affiliation strings and mis-ranks bare names — verified
// live: "University of Adelaide" returns "University of Aden" (chosen, 0.97) and omits Adelaide. This
// source assertion fails if anyone reverts the endpoint.
ok(/api\.ror\.org\/v2\/organizations\?query=/.test(html), "ROR lookup uses the name-search ?query= endpoint");
ok(!/organizations\?affiliation=/.test(html), "ROR lookup does NOT use the ?affiliation= matcher");

// rorMatchesFromResponse must extract {name,id,country,acronym} from BOTH response shapes:
// query -> items are bare v2 orgs; affiliation -> items wrap the org in .organization.
const V2ORG = { id: "https://ror.org/028g18b61",
  names: [{ value: "Adelaide University", types: ["ror_display"] }, { value: "UofA", types: ["acronym"] }],
  locations: [{ geonames_details: { country_name: "Australia" } }] };
const qM = M.rorMatchesFromResponse({ items: [V2ORG] });                               // query shape (bare org)
ok(qM.length === 1 && qM[0].id === "https://ror.org/028g18b61" && qM[0].name === "Adelaide University"
   && qM[0].country === "Australia" && qM[0].acronym === "UofA", "parses a query-shape (bare org) item");
const aM = M.rorMatchesFromResponse({ items: [{ organization: V2ORG, score: 0.9, chosen: true }] }); // affiliation shape
ok(aM.length === 1 && aM[0].id === "https://ror.org/028g18b61" && aM[0].name === "Adelaide University",
   "parses an affiliation-shape (.organization wrapper) item");
ok(M.rorMatchesFromResponse({ items: [{ id: null, names: [] }] }).length === 0,
   "drops un-nameable / un-identifiable items (never shows 'undefined')");

// ---- C3 (PII scrub): the packaged submission .zip must NOT embed submitter email/ORCID -----------
// The zip may be published (public-PR attachment OR the gateway pipeline), so anything written into
// MANIFEST.json/SUBMISSION.md is effectively published. Source-text assertion (same style as the ROR
// endpoint check above) against the SHARED package builder — buildPackage()/buildSubmissionMd(),
// which produce the package CONTENTS for BOTH the download and the C13 direct-upload paths. That
// logic runs in the browser (FileReader/JSZip) and isn't part of the exported pure-logic module M.
// The slice spans from buildPackage to the download click handler, covering both builders. The
// submitter NAME is fine to keep; email/orcid must not reach the package contents.
const pkgBlock = html.slice(html.indexOf("async function buildPackage"), html.indexOf('$("btnPackage").onclick'));
ok(!/submitter:\{[^}]*email:\s*meta\.uploader_email/.test(pkgBlock),
   "MANIFEST.json submitter block does NOT write uploader_email");
ok(!/submitter:\{[^}]*orcid:\s*meta\.uploader_orcid/.test(pkgBlock),
   "MANIFEST.json submitter block does NOT write uploader_orcid");
ok(/submitter:\{[^}]*name:\s*meta\.uploader_name/.test(pkgBlock),
   "MANIFEST.json submitter block still keeps the name");
ok(!/uploader_email/.test(pkgBlock),
   "SUBMISSION.md template does NOT reference uploader_email anywhere in the packager block");
ok(!/uploader_orcid/.test(pkgBlock) || /ORCID/.test(pkgBlock) === false,
   "SUBMISSION.md template does NOT reference uploader_orcid in the packager block");
// Keep the uploader_email FORM FIELD + validation live elsewhere in the page (Stage-2 gateway feed) --
// only the package CONTENTS must be clean, so check it still exists outside the sliced block.
ok(/m_up_email/.test(html), "the uploader email form field itself is still present (feeds Stage-2 gateway)");

// ============================ C13 direct-upload pure logic (design §4/§5) ============================
// -- isOrcidChecksum: ISO 7064 MOD 11-2, must mirror gateway/orcid.py EXACTLY. M2 (code-health review
//    §6): the reference verdicts now come from the SHARED vector file gateway/tests/fixtures/
//    orcid_vectors.json — the SAME file gateway/tests/test_orcid.py and the vendored-validator test
//    consume. A divergence between this portal isOrcidChecksum and the shared oracle reds exactly the
//    offending vector, so the three ISO-7064 copies cannot drift apart silently. We drive every vector
//    whose `applies_to` lists "portal" (the portal's FORMAT contract: bare 16-char form accepted).
const ORCID_VECTORS = JSON.parse(fs.readFileSync(
  path.join(__dirname, "..", "..", "gateway", "tests", "fixtures", "orcid_vectors.json"), "utf8"));
const portalOrcidVectors = ORCID_VECTORS.vectors.filter(v => v.applies_to.includes("portal"));
ok(portalOrcidVectors.length > 0, "shared orcid_vectors.json has portal-scoped vectors");
for (const v of portalOrcidVectors) {
  ok(M.isOrcidChecksum(v.input) === v.valid,
     `isOrcidChecksum(${JSON.stringify(v.input)}) === ${v.valid} [shared vector: ${v.note}]`);
}

// -- gatewayPresent (§1 strict shape check): PRESENT iff 200 AND JSON AND ok===true.
ok(M.gatewayPresent(200, '{"ok":true}') === true, "gatewayPresent: 200 + {ok:true} -> present");
ok(M.gatewayPresent(200, '<!doctype html><title>404</title>') === false, "gatewayPresent: 200 + HTML body (SPA/404 fallback) -> absent");
ok(M.gatewayPresent(200, '{"ok":false}') === false, "gatewayPresent: 200 + {ok:false} -> absent");
ok(M.gatewayPresent(200, '{"status":"up"}') === false, "gatewayPresent: 200 + JSON without ok===true -> absent");
ok(M.gatewayPresent(404, '{"ok":true}') === false, "gatewayPresent: 404 (even with a truthy body) -> absent");
ok(M.gatewayPresent(500, '{"ok":true}') === false, "gatewayPresent: 500 -> absent");
ok(M.gatewayPresent(0, "") === false, "gatewayPresent: network-error shape (status 0) -> absent");

// -- statusUrlSafe (§2 anchor guard): accept only a same-origin /gateway/status/<urlsafe-token>.
ok(M.statusUrlSafe("/gateway/status/AbC-9_xYz01") === true, "statusUrlSafe: same-origin urlsafe-token path accepted");
ok(M.statusUrlSafe("http://evil.example/gateway/status/x") === false, "statusUrlSafe: absolute http URL rejected");
ok(M.statusUrlSafe("//evil.example/gateway/status/x") === false, "statusUrlSafe: protocol-relative //host rejected");
ok(M.statusUrlSafe("javascript:alert(1)") === false, "statusUrlSafe: javascript: scheme rejected");
ok(M.statusUrlSafe("/gateway/status/../../etc/passwd") === false, "statusUrlSafe: path traversal rejected");
ok(M.statusUrlSafe("/gateway/statusx/token") === false, "statusUrlSafe: tampered prefix rejected");
ok(M.statusUrlSafe("/gateway/status/") === false, "statusUrlSafe: empty token rejected");

// -- submitResultMessage (§2 code map): returns plain text (never HTML). Assert each documented code.
ok(M.submitResultMessage(201, {submission_id: "S1"}) === "Submission received.", "submitResultMessage: 201");
ok(/not accepted/i.test(M.submitResultMessage(401, null)), "submitResultMessage: 401 -> key not accepted");
ok(/already in the pipeline/i.test(M.submitResultMessage(409, {submission_id: "abc"})) && /abc/.test(M.submitResultMessage(409, {submission_id: "abc"})),
   "submitResultMessage: 409 -> duplicate, mentions the id");
ok(/size limit/i.test(M.submitResultMessage(413, null)), "submitResultMessage: 413 -> size limit");
ok(/capacity/i.test(M.submitResultMessage(429, null)), "submitResultMessage: 429 -> capacity");
ok(/starting|paused/i.test(M.submitResultMessage(503, null)), "submitResultMessage: 503 -> starting/paused");
ok(/network/i.test(M.submitResultMessage(0, null)), "submitResultMessage: 0 -> network error");
// 400 passes the server `detail` through VERBATIM as text (the page escapes it at render). A hostile
// detail must come back as inert text, NOT get sanitised/dropped here (the escaping is the page's job).
const hostile = '<img src=x onerror=alert(1)>';
ok(M.submitResultMessage(400, {detail: hostile}) === hostile,
   "submitResultMessage: 400 -> server detail passed through verbatim (as text, page escapes it)");
ok(!/</.test(M.submitResultMessage(413, null)) && !/</.test(M.submitResultMessage(401, null)),
   "submitResultMessage: canned messages contain no HTML");

// -- submitFormFields (§3): name+email always; orcid ONLY when non-empty (field omitted otherwise).
const ff1 = M.submitFormFields({uploader_name: "Ada L", uploader_email: "ada@x.co", uploader_orcid: ""});
ok(!("submitter_orcid" in ff1) && ff1.submitter_name === "Ada L" && ff1.submitter_email === "ada@x.co",
   "submitFormFields: empty ORCID is OMITTED entirely");
const ff2 = M.submitFormFields({uploader_name: "Ada L", uploader_email: "ada@x.co", uploader_orcid: "0000-0002-1825-0097"});
ok(ff2.submitter_orcid === "0000-0002-1825-0097", "submitFormFields: non-empty ORCID rides as a field");

// ============================ C13 source assertions (grep-style, §5) ================================
// No NEW external origin is CONTACTED by C13. The only network destinations the page opens are its
// fetch()/XHR .open() calls: the pre-existing api.ror.org lookup, and the two new same-origin gateway
// calls. Every fetch()/.open() target must therefore be either a same-origin relative "/..." path or
// the one allow-listed https://api.ror.org — anything else is a new external origin C13 must not add.
// (Scanning only the actual connection points avoids false hits on placeholder/comment URLs like the
// commented-out Plausible host or an input's https://ror.org placeholder — those open no connection.)
const conns = [...html.matchAll(/(?:fetch|\.open)\(\s*(?:"[^"]*",\s*)?"([^"]+)"/g)].map(m => m[1])
  .filter(u => !/^\$\{/.test(u));
const ALLOWED_CONN = u => /^\//.test(u) || /^https:\/\/api\.ror\.org\//.test(u);
const badConns = conns.filter(u => !ALLOWED_CONN(u) && /^https?:/.test(u));
ok(badConns.length === 0, "every fetch()/XHR target is same-origin or the allow-listed ROR API; new origins: " + JSON.stringify(badConns));
// Belt-and-braces: no CDN/basemap host string appears anywhere on this contributor page.
ok(!/cdnjs\.cloudflare\.com|basemaps\.cartocdn\.com/.test(html), "no CDN/basemap origin on the add-survey page");

// The gateway is consumed at the LITERAL same-origin relative paths (design §0.2) — never an absolute
// URL, never a configurable base. These exact strings must be present and un-prefixed.
ok(/fetch\("\/gateway\/healthz"/.test(html), "healthz probe uses the literal same-origin /gateway/healthz path");
ok(/\.open\("POST",\s*"\/gateway\/submit"\)/.test(html), "submit POSTs to the literal same-origin /gateway/submit path");
ok(!/https?:\/\/[^"'`]*\/gateway\//.test(html), "no absolute-URL /gateway/ reference (same-origin only, no config knob)");
ok(!/gateway_base_url/.test(html), "no gateway_base_url config knob (design §0.2)");
// The submit key header is the ONLY place the key is put on the wire (design §0.3). Assert the header
// name is present and that the key is never persisted anywhere.
ok(/setRequestHeader\("X-AusMT-Submit-Key"/.test(html), "the submit key is sent via the X-AusMT-Submit-Key header");
ok(!/localStorage[^;\n]*submit_key/i.test(html) && !/sessionStorage[^;\n]*submit_key/i.test(html)
   && !/m_submit_key[^;\n]*(localStorage|sessionStorage|cookie)/i.test(html),
   "the submit key is never written to localStorage/sessionStorage/cookies (design §0.3)");

console.log(fail ? `\n${fail} FAILED` : "\nALL PASSED (add-survey logic)");
process.exit(fail ? 1 : 0);
