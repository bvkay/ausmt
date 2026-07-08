// jsdom-backed INTERACTION + KEY-HYGIENE test for the add-survey page's C13 direct-upload flow.
//
// The pure logic (isOrcidChecksum/gatewayPresent/statusUrlSafe/submitResultMessage/submitFormFields)
// is unit-tested in tests/add_survey_logic.test.js. This driver covers what only a live DOM can: the
// healthz probe gating the submit UI, the in-flight double-submit guard, the escaped 201 status link,
// and — the design §5 CENTREPIECE — that the radioactive submit key travels ONLY in the
// X-AusMT-Submit-Key request header and appears NOWHERE else (not the zip bytes, not any track()
// payload, not the DOM outside the input's own live value, not any URL the mock XHR saw).
//
//   node tools/add_survey_submit_test.js
//
// Requires jsdom (dev-only; the shipped portal has none). Exit codes:
//   0 = passed   1 = a real failure   2 = jsdom missing (caller SKIPs, not fails)
const fs = require("fs"), path = require("path"), vm = require("vm");
let JSDOM;
try { ({ JSDOM } = require("jsdom")); }
catch (e) { console.error("SKIP: jsdom not installed (run `npm ci` in portal/)"); process.exit(2); }

const TOOLS = __dirname;
const PORTAL = path.resolve(TOOLS, "..");
const SRC = path.join(PORTAL, "src");
const html = fs.readFileSync(path.join(PORTAL, "add-survey.html"), "utf8");

function die(msg) { console.error("SUBMIT-TEST FAILED: " + msg); process.exit(1); }
function ok(cond, msg) { if (!cond) die(msg); }

// The distinctive secret we track through the whole flow. If this string surfaces anywhere except the
// X-AusMT-Submit-Key header, the radioactive-key invariant (design §0.3) is broken.
const SECRET_KEY = "SECRET-KEY-do-not-leak-7f3a9c";
// A synthetic minimal-but-valid submission: one clean-decimal EDI + all required metadata, locations
// confirmed, declarations ticked — so validateSurvey() returns zero FAILs and the flow reaches upload.
const EDI_TEXT = '>HEAD\nDATAID="S01"\nLAT=-30.10\nLONG=136.20\n\n>FREQ\n1 10 100\n>ZXYR\n1 2 3\n';

// ---- A programmable fake XMLHttpRequest that records every observable the key could leak into. ----
function makeFakeXHR(record) {
  return class FakeXHR {
    constructor() { this.upload = {}; this.status = 0; this.responseText = ""; this._headers = {}; this.readyState = 0; }
    open(method, url) { this.method = method; this.url = url; record.opens.push({ method, url }); }
    setRequestHeader(k, v) { this._headers[k] = v; record.headers.push({ name: k, value: v }); }
    send(body) {
      record.sends.push(body);
      this._body = body;
      FakeXHR._last = this;
      // Drive a synchronous upload-progress tick so the progress UI path is exercised, then resolve
      // on the next microtask with the scripted response (so in-flight state is observable first).
      if (this.upload && typeof this.upload.onprogress === "function")
        this.upload.onprogress({ lengthComputable: true, loaded: 50, total: 100 });
      Promise.resolve().then(() => {
        this.status = FakeXHR._script.status;
        this.responseText = FakeXHR._script.responseText;
        if (FakeXHR._script.networkError && typeof this.onerror === "function") this.onerror();
        else if (typeof this.onload === "function") this.onload();
      });
    }
    abort() { if (typeof this.onabort === "function") this.onabort(); }
  };
}

// Boot the real add-survey DOM with the given fetch() probe behaviour and (optionally) a scripted XHR.
async function boot({ probe, xhrScript }) {
  const dom = new JSDOM(html, { url: "http://localhost/", runScripts: "outside-only", pretendToBeVisual: true });
  const win = dom.window;
  // Stub the map/zip libs the page loads via <script src> (irrelevant here; the DOM is real).
  win.L = undefined;                        // no Leaflet — the map code guards on `typeof L`
  // Real JSZip so the built zip is REAL bytes we can scan for the key (the download path uses it too).
  win.JSZip = require(path.join(PORTAL, "vendor", "jszip.min.js"));
  // crypto.subtle for sha256Hex — jsdom's window.crypto has no `subtle`; bridge to Node's WebCrypto.
  // jsdom exposes `crypto` via a getter, so replace the whole property (configurable) with Node's.
  const { webcrypto } = require("crypto");
  if (!win.crypto || !win.crypto.subtle) {
    try { Object.defineProperty(win, "crypto", { value: webcrypto, configurable: true, writable: true }); }
    catch (e) { win.crypto = webcrypto; }
  }
  // jsdom's window lacks TextEncoder/TextDecoder (the page uses TextEncoder in addFiles); real
  // browsers ship them. Bridge to Node's so the EDI-ingest path runs as it would in a browser.
  const { TextEncoder, TextDecoder } = require("util");
  if (!win.TextEncoder) win.TextEncoder = TextEncoder;
  if (!win.TextDecoder) win.TextDecoder = TextDecoder;
  // Record every blob handed to createObjectURL so the DOWNLOAD path's packaged zip is inspectable
  // too (the SUBMISSION.md numbering regression below reads the real bytes from BOTH transports).
  win.URL.createObjectURL = (b) => { record.blobs.push(b); return "blob:mock"; };
  win.URL.revokeObjectURL = () => {};
  // A recording FormData that matches the browser API the page uses (append/get/getAll/entries) but,
  // unlike jsdom's strict generated FormData, accepts the Node/JSZip Blob the page produces. This lets
  // the REAL page code run unchanged while the test inspects every field, filename, and the file part.
  win.FormData = class RecordingFormData {
    constructor() { this._e = []; }
    append(name, value, filename) { this._e.push([name, value, filename]); }
    get(name) { const r = this._e.find((e) => e[0] === name); return r ? r[1] : null; }
    getAll(name) { return this._e.filter((e) => e[0] === name).map((e) => e[1]); }
    *entries() { for (const [n, v] of this._e) yield [n, v]; }
    [Symbol.iterator]() { return this.entries(); }
  };
  // fetch() → the scripted healthz probe.
  win.fetch = (url) => probe(url);
  // XHR record + fake class (only installed when a script is provided).
  const record = { opens: [], headers: [], sends: [], trackCalls: [], blobs: [] };
  if (xhrScript) {
    const FakeXHR = makeFakeXHR(record);
    FakeXHR._script = xhrScript;
    win.XMLHttpRequest = FakeXHR;
  }
  // Wait for the document to finish loading BEFORE we run the page scripts, so nothing double-fires.
  await new Promise((res) => (win.document.readyState === "complete" ? res() : win.addEventListener("load", res, { once: true })));
  // Run the page's scripts in source order: security.js, analytics-shim.js, then the ONE inline block.
  // We wrap track() to record every event+props so the key-hygiene assertion can scan payloads.
  const security = fs.readFileSync(path.join(SRC, "security.js"), "utf8");
  const shim = fs.readFileSync(path.join(SRC, "analytics-shim.js"), "utf8");
  const inline = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]).find((b) => b.includes("function buildSurveyYaml"));
  ok(!!inline, "could not extract the inline pure-logic+UI script block");
  let code = security + "\n" + shim + "\n" +
    // record every track() call (name + props) so we can prove the key never rides in analytics.
    "(function(){var _t=window.track;window.track=function(n,p){window.__trackCalls.push({name:n,props:p});return _t&&_t(n,p);};})();\n" +
    inline;
  win.__trackCalls = record.trackCalls;
  vm.runInContext(code, dom.getInternalVMContext());
  // Let the probe's promise chain settle (probe → showGatewayUI or stay hidden).
  await new Promise((res) => setTimeout(res, 0));
  return { win, doc: win.document, record, FakeXHR: win.XMLHttpRequest };
}

// Fill in a complete, valid submission on the given window's form.
function fillValidForm(win, { key = SECRET_KEY, orcid = "" } = {}) {
  const doc = win.document, $ = (id) => doc.getElementById(id);
  $("m_name").value = "Example Survey"; $("m_slug").value = "example-survey";
  $("m_org").value = "Test Org"; $("m_country").value = "Australia";
  // license/access are <select>s already defaulting to valid values.
  $("m_up_name").value = "Ada Lovelace"; $("m_up_email").value = "ada@example.org";
  if (orcid) $("m_up_orcid").value = orcid;
  $("m_auth").checked = true; $("m_licdecl").checked = true; $("m_locconf").checked = true;
  if (key != null) $("m_submit_key").value = key;
  // Inject the EDI into the page's internal file list by driving the real drop handler path: the page
  // exposes addFiles() only inside the UI closure, so instead push through the file input's change by
  // faking a File-like object the FileReader path reads. Simpler + faithful: dispatch a drop with a
  // DataTransfer-like payload the page's drop handler accepts.
  return new Promise((res) => {
    const file = new win.File([EDI_TEXT], "S01.edi", { type: "text/plain" });
    const drop = $("drop");
    const ev = new win.Event("drop", { bubbles: true });
    Object.defineProperty(ev, "dataTransfer", { value: { files: [file] } });
    Object.defineProperty(ev, "preventDefault", { value: () => {} });
    drop.dispatchEvent(ev);
    // FileReader is async; wait a tick for readAsText to land the parsed EDI into the file list.
    setTimeout(res, 20);
  });
}

// Fill only the required metadata (no file, no key) so the Package path validates. Mirrors
// fillValidForm's metadata half; used by the file-remove section which supplies its own files.
function fillValidMeta(win) {
  const $ = (id) => win.document.getElementById(id);
  $("m_name").value = "Example Survey"; $("m_slug").value = "example-survey";
  $("m_org").value = "Test Org"; $("m_country").value = "Australia";
  $("m_up_name").value = "Ada Lovelace"; $("m_up_email").value = "ada@example.org";
  $("m_auth").checked = true; $("m_licdecl").checked = true; $("m_locconf").checked = true;
}
// Drop one EDI (name + text) into the page's file list via the real drop handler, then wait for the
// async FileReader to land the parsed entry. Sequential awaits keep list order deterministic.
function addEdi(win, name, text) {
  return new Promise((res) => {
    const file = new win.File([text], name, { type: "text/plain" });
    const ev = new win.Event("drop", { bubbles: true });
    Object.defineProperty(ev, "dataTransfer", { value: { files: [file] } });
    Object.defineProperty(ev, "preventDefault", { value: () => {} });
    win.document.getElementById("drop").dispatchEvent(ev);
    setTimeout(res, 20);
  });
}

const JSON_OK = { status: 200, text: () => Promise.resolve('{"ok":true}') };
const probePresent = () => Promise.resolve(JSON_OK);
const probeAbsent = () => Promise.reject(new Error("network"));                 // no gateway
const probeHtml200 = () => Promise.resolve({ status: 200, text: () => Promise.resolve("<!doctype html><title>404</title>") });

(async () => {
  // --------------------------------------------------------------------------------------------------
  // 1. PROBE GATES THE UI: absent (network error) and a 200-but-HTML body both leave it HIDDEN; only a
  //    strict 200+{ok:true} reveals it. (gatewayPresent's strictness is unit-tested; here we prove the
  //    DOM wiring honours it.)
  {
    const { doc } = await boot({ probe: probeAbsent });
    ok(!doc.getElementById("gatewayBlock").classList.contains("show"),
      "gateway UI must stay hidden when the probe errors (no gateway)");
  }
  {
    const { doc } = await boot({ probe: probeHtml200 });
    ok(!doc.getElementById("gatewayBlock").classList.contains("show"),
      "gateway UI must stay hidden on a 200 with an HTML body (SPA/404 fallback)");
  }
  const shown = await boot({ probe: probePresent });
  ok(shown.doc.getElementById("gatewayBlock").classList.contains("show"),
    "gateway UI must show when the probe returns 200 + {ok:true}");
  ok(shown.record.trackCalls.some((t) => t.name === "GatewayDetected"),
    "a passing probe fires GatewayDetected");

  // --------------------------------------------------------------------------------------------------
  // 2. THE KEY-HYGIENE CENTREPIECE (design §5). Boot with the gateway present + a scripted 201, fill a
  //    valid form with the SECRET key, submit, and prove the key appears ONLY in the header.
  const script201 = { status: 201, responseText: JSON.stringify({ submission_id: "SUB123", status_url: "/gateway/status/tok-EN_abc123" }) };
  const env = await boot({ probe: probePresent, xhrScript: script201 });
  const { win, doc, record } = env;
  await fillValidForm(win, { key: SECRET_KEY });

  // Double-submit guard: the button is enabled before submit, disabled the instant it is in flight.
  const btn = doc.getElementById("btnSubmitGateway");
  ok(btn.disabled === false, "submit button starts enabled");
  const clickP = btn.onclick();                        // async handler; returns a promise
  // Synchronously after the click kicks off, the button must be disabled and Cancel visible.
  ok(btn.disabled === true, "submit button is disabled while in flight (double-submit guard)");
  ok(doc.getElementById("btnCancelSubmit").style.display !== "none", "Cancel button is shown while in flight");
  await clickP;
  await new Promise((res) => setTimeout(res, 0));       // let the XHR onload microtask + render run

  // (a) exactly one submit happened, to the literal same-origin path.
  ok(record.opens.length === 1 && record.opens[0].url === "/gateway/submit" && record.opens[0].method === "POST",
    "exactly one POST to /gateway/submit; saw " + JSON.stringify(record.opens));
  // (b) the key IS present, in the X-AusMT-Submit-Key header, and only there among headers.
  const keyHeaders = record.headers.filter((h) => h.value === SECRET_KEY);
  ok(keyHeaders.length === 1 && keyHeaders[0].name === "X-AusMT-Submit-Key",
    "the key rides in exactly one header, X-AusMT-Submit-Key; headers: " + JSON.stringify(record.headers));
  // (c) the key is NOT in any URL the XHR opened.
  ok(!record.opens.some((o) => o.url.indexOf(SECRET_KEY) >= 0), "the key is absent from every XHR URL");
  // (d) the key is NOT in the multipart body: read every FormData entry (file + fields).
  const fd = record.sends[0];
  ok(fd && typeof fd.getAll === "function", "the request body is a FormData");
  const fdText = [];
  for (const [k, v] of fd.entries()) { fdText.push(k); fdText.push(typeof v === "string" ? v : (v && v.name) || ""); }
  ok(!fdText.some((s) => String(s).indexOf(SECRET_KEY) >= 0), "the key is absent from every FormData field/filename");
  // (e) the key is NOT in the built ZIP BYTES. Pull the File part out of the FormData and scan it.
  const filePart = fd.get("file");
  ok(filePart, "the FormData carries a `file` part");
  const zipBuf = Buffer.from(await filePart.arrayBuffer());
  ok(zipBuf.indexOf(Buffer.from(SECRET_KEY)) < 0, "the key is absent from the built zip bytes");
  // Also prove email/ORCID (C3) never entered the zip bytes even though they ride as form fields.
  ok(zipBuf.indexOf(Buffer.from("ada@example.org")) < 0, "the submitter email is absent from the zip bytes (C3)");
  // (f) the key is NOT in any track() payload (name or props).
  ok(!record.trackCalls.some((t) => JSON.stringify(t).indexOf(SECRET_KEY) >= 0), "the key is absent from every track() payload");
  ok(record.trackCalls.some((t) => t.name === "GatewaySubmitAttempted"), "GatewaySubmitAttempted fired");
  ok(record.trackCalls.some((t) => t.name === "GatewaySubmitResult" && t.props && t.props.code === 201),
    "GatewaySubmitResult{code:201} fired");
  // track() must never carry the submission id either (capability-adjacent, design §0.4).
  ok(!record.trackCalls.some((t) => JSON.stringify(t.props || {}).indexOf("SUB123") >= 0),
    "the submission id never enters a track() payload (design §0.4)");
  // (g) the key is NOT anywhere in the rendered DOM (outside the input's own live .value, which is not
  //     serialised into innerHTML). This is the "never echoed into the DOM" assertion.
  ok(doc.body.innerHTML.indexOf(SECRET_KEY) < 0, "the key never appears in document.body.innerHTML");
  ok(doc.getElementById("m_submit_key").value === SECRET_KEY, "sanity: the key is still the input's live value (only there)");

  // 201 success panel: id shown, status link is an ESCAPED anchor with the safe URL, and the
  // save-this-link warning is present.
  const body = doc.getElementById("submitBody");
  ok(/SUB123/.test(body.textContent), "success panel shows the submission id");
  const anchor = body.querySelector('a[href="/gateway/status/tok-EN_abc123"]');
  ok(anchor, "success panel renders the status link as an anchor to the safe URL");
  ok(/Save this link/i.test(body.textContent), "success panel carries the save-this-link warning");

  // --------------------------------------------------------------------------------------------------
  // 3. XSS REGRESSION (design §5): a hostile 400 `detail` and a hostile status_url must render as inert
  //    TEXT — no element injection. This assertion FAILS if someone removes the esc()/escAttr()/
  //    statusUrlSafe() guards (non-vacuous).
  // (3a) hostile 400 detail.
  {
    const evil = '<img src=x onerror="window.__pwned=1">';
    const script400 = { status: 400, responseText: JSON.stringify({ detail: evil }) };
    const e = await boot({ probe: probePresent, xhrScript: script400 });
    await fillValidForm(e.win, { key: SECRET_KEY });
    await e.doc.getElementById("btnSubmitGateway").onclick();
    await new Promise((res) => setTimeout(res, 0));
    const panel = e.doc.getElementById("submitBody");
    ok(e.win.__pwned === undefined, "a hostile 400 detail must NOT execute (no onerror fired)");
    ok(panel.querySelector("img") === null, "a hostile 400 detail must NOT inject an <img> element");
    ok(panel.textContent.indexOf("<img") >= 0, "the hostile detail is shown as inert escaped text");
  }
  // (3b) hostile status_url on a 201: statusUrlSafe rejects it, so NO anchor is rendered (id shown).
  {
    const script201x = { status: 201, responseText: JSON.stringify({ submission_id: "S9", status_url: "javascript:alert(1)" }) };
    const e = await boot({ probe: probePresent, xhrScript: script201x });
    await fillValidForm(e.win, { key: SECRET_KEY });
    await e.doc.getElementById("btnSubmitGateway").onclick();
    await new Promise((res) => setTimeout(res, 0));
    const panel = e.doc.getElementById("submitBody");
    ok(panel.querySelector('a[href^="javascript:"]') === null, "an unsafe status_url must NOT become a javascript: anchor");
    ok(panel.querySelectorAll("a").length === 0, "an unsafe status_url renders no anchor at all");
    ok(/S9/.test(panel.textContent), "the id is still shown even when the status link is unsafe");
  }

  // --------------------------------------------------------------------------------------------------
  // 4. FAIL-FAST GATES before any upload: empty key blocks; a bad-checksum ORCID blocks. Neither opens
  //    an XHR (the record stays empty).
  {
    const e = await boot({ probe: probePresent, xhrScript: script201 });
    await fillValidForm(e.win, { key: "" });                        // empty key
    await e.doc.getElementById("btnSubmitGateway").onclick();
    await new Promise((res) => setTimeout(res, 0));
    ok(e.record.opens.length === 0, "an empty submit key blocks before any upload");
    ok(/submit key/i.test(e.doc.getElementById("submitBody").textContent), "empty-key message shown");
  }
  {
    const e = await boot({ probe: probePresent, xhrScript: script201 });
    await fillValidForm(e.win, { key: SECRET_KEY, orcid: "0000-0002-1825-0098" }); // wrong checksum
    await e.doc.getElementById("btnSubmitGateway").onclick();
    await new Promise((res) => setTimeout(res, 0));
    ok(e.record.opens.length === 0, "a bad-checksum submitter ORCID blocks before any upload (fail fast, design §2.2)");
    ok(/checksum/i.test(e.doc.getElementById("submitBody").textContent), "ORCID-checksum message shown");
  }

  // --------------------------------------------------------------------------------------------------
  // 4b. EMBARGO DATE + ACCESS CONTACT REVEAL AND EMIT (audit 5.2). The embargo/contact inputs are hidden
  //     for an 'open' level and revealed for any non-open level; a filled date reaches survey.yaml as a
  //     bare ISO scalar. Reads the REAL packaged survey.yaml via the download path (createObjectURL).
  async function packagedSurveyYaml(win, record) {
    ok(record.blobs.length === 1, "packaging produced exactly one zip blob");
    const buf = Buffer.from(await record.blobs[record.blobs.length - 1].arrayBuffer());
    const JSZipNode = require(path.join(PORTAL, "vendor", "jszip.min.js"));
    const z = await JSZipNode.loadAsync(buf);
    const entries = z.file(/survey\.yaml$/);
    ok(entries.length === 1, "the zip contains exactly one survey.yaml");
    return entries[0].async("string");
  }
  {
    // (4b-i) default level 'open' -> the embargo block is hidden and both fields serialise as null.
    const e = await boot({ probe: probeAbsent });
    fillValidMeta(e.win);
    await addEdi(e.win, "S01.edi", EDI_TEXT);
    ok(e.doc.getElementById("embargoBlock").style.display === "none",
      "the embargo/contact block is hidden while access level is 'open'");
    await e.doc.getElementById("btnPackage").onclick();
    await new Promise((res) => setTimeout(res, 0));
    const yOpen = await packagedSurveyYaml(e.win, e.record);
    ok(/access:\s*\n\s*level: open\s*\n\s*embargo_until: null\s*\n\s*contact: null/.test(yOpen),
      "open survey.yaml keeps embargo_until and contact null");
  }
  {
    // (4b-ii) level 'embargoed' -> the block reveals; a filled date + contact reach survey.yaml.
    const e = await boot({ probe: probeAbsent });
    fillValidMeta(e.win);
    await addEdi(e.win, "S01.edi", EDI_TEXT);
    const acc = e.doc.getElementById("m_access");
    acc.value = "embargoed";
    acc.dispatchEvent(new e.win.Event("change", { bubbles: true }));
    ok(e.doc.getElementById("embargoBlock").style.display === "block",
      "selecting a non-open access level reveals the embargo/contact block");
    e.doc.getElementById("m_embargo_until").value = "2027-02-01";
    e.doc.getElementById("m_access_contact").value = "custodian@agency.gov.au";
    await e.doc.getElementById("btnPackage").onclick();
    await new Promise((res) => setTimeout(res, 0));
    const yEmb = await packagedSurveyYaml(e.win, e.record);
    ok(/access:\s*\n\s*level: embargoed\s*\n\s*embargo_until: 2027-02-01/.test(yEmb),
      "embargoed survey.yaml emits the filled embargo_until date; got: " +
      (yEmb.match(/access:[\s\S]*?contact:.*$/m) || [""])[0]);
    ok(/contact: "custodian@agency\.gov\.au"/.test(yEmb),
      "embargoed survey.yaml emits the access contact");
  }
  {
    // (4b-iii) always-visible disclosure hint states, truthfully, that every level publishes coordinates.
    const e = await boot({ probe: probeAbsent });
    const disc = e.doc.getElementById("accessDisclosure");
    ok(disc && disc.textContent.trim().length > 0, "the access disclosure hint is present");
    const discText = disc.textContent.replace(/\s+/g, " ");   // collapse source-wrap whitespace
    ok(/lists this survey publicly/i.test(discText) && /coordinates/i.test(discText)
      && /withhold/i.test(discText),
      "the disclosure states public listing, coordinate visibility, and byte withholding");
  }

  // --------------------------------------------------------------------------------------------------
  // 5. SUBMISSION.md "How to submit" LIST NUMBERING (adversarial-review finding, LOW): the packaged
  //    instructions are an ordered list and must number strictly sequentially (1., 2., ...) in BOTH
  //    branches. The gateway-ABSENT branch (the PRIMARY path on static-only/file:// deploys) regressed
  //    to "1." then "3." with no "2." — this section reads the REAL packaged bytes from both transports
  //    and fails on any gap. Present-path zip = the one captured in section 2; absent-path zip = the
  //    DOWNLOAD path's blob (captured via the createObjectURL recorder).
  async function howToSubmitNumbers(zipBytes) {
    const JSZipNode = require(path.join(PORTAL, "vendor", "jszip.min.js"));
    const z = await JSZipNode.loadAsync(zipBytes);
    const entries = z.file(/SUBMISSION\.md$/);
    ok(entries.length === 1, "the zip contains exactly one SUBMISSION.md");
    const md = await entries[0].async("string");
    const at = md.indexOf("## How to submit");
    ok(at >= 0, "SUBMISSION.md carries the '## How to submit' section");
    return [...md.slice(at).matchAll(/^(\d+)\.\s/gm)].map((m) => +m[1]);
  }
  const sequential = (nums) => nums.length > 0 && nums.every((n, i) => n === i + 1);
  // (5a) gateway-PRESENT package (zip already captured in section 2 from the upload's FormData).
  {
    const nums = await howToSubmitNumbers(zipBuf);
    ok(sequential(nums),
      "gateway-PRESENT SUBMISSION.md list numbering must be strictly sequential; got: " + JSON.stringify(nums));
  }
  // (5b) gateway-ABSENT package via the DOWNLOAD path (the pre-C13 primary flow on static deploys).
  {
    const e = await boot({ probe: probeAbsent });
    await fillValidForm(e.win, { key: null });          // no key needed to package
    await e.doc.getElementById("btnPackage").onclick();
    await new Promise((res) => setTimeout(res, 0));
    ok(e.record.blobs.length === 1, "the download path produced exactly one zip blob");
    const buf = Buffer.from(await e.record.blobs[0].arrayBuffer());
    const nums = await howToSubmitNumbers(buf);
    ok(sequential(nums),
      "gateway-ABSENT SUBMISSION.md list numbering must be strictly sequential; got: " + JSON.stringify(nums));
  }

  // --------------------------------------------------------------------------------------------------
  // 5c. NO PR FICTION IN SUBMISSION.md (audit 5.1). The ausmt-surveys repo is private forever, so a
  //     "pull request (always available)" instruction is impossible to follow. The packaged SUBMISSION.md
  //     must NOT instruct opening a PR against that repo, and MUST carry the honest email-the-operator
  //     fallback. Checked on BOTH transports (the file travels inside the zip either way).
  async function packagedSubmissionMd(zipBytes) {
    const JSZipNode = require(path.join(PORTAL, "vendor", "jszip.min.js"));
    const z = await JSZipNode.loadAsync(zipBytes);
    const entries = z.file(/SUBMISSION\.md$/);
    ok(entries.length === 1, "the zip contains exactly one SUBMISSION.md");
    return entries[0].async("string");
  }
  for (const branch of ["present", "absent"]) {
    const e = await boot({ probe: branch === "present" ? probePresent : probeAbsent });
    await fillValidForm(e.win, { key: branch === "present" ? SECRET_KEY : null });
    // Package via download (gives us a blob on both branches without needing an XHR script).
    await e.doc.getElementById("btnPackage").onclick();
    await new Promise((res) => setTimeout(res, 0));
    ok(e.record.blobs.length >= 1, "packaging produced a zip blob (" + branch + ")");
    const md = await packagedSubmissionMd(Buffer.from(await e.record.blobs[e.record.blobs.length - 1].arrayBuffer()));
    ok(!/always available/i.test(md),
      "SUBMISSION.md must not claim a PR path is 'always available' (" + branch + ")");
    ok(!/pull request|open a pr|ausmt-surveys/i.test(md),
      "SUBMISSION.md must not instruct a PR against the private ausmt-surveys repo (" + branch + ")");
    ok(/email[\s\S]*zip[\s\S]*operator|email[\s\S]*operator[\s\S]*zip/i.test(md),
      "SUBMISSION.md must carry the honest email-the-operator fallback (" + branch + ")");
    ok(/About page/i.test(md),
      "SUBMISSION.md points to the operator contact on the About page (" + branch + ")");
  }

  // --------------------------------------------------------------------------------------------------
  // 6. PER-ROW FILE REMOVE (fix/add-survey-file-remove): the ✕ button removes a file from `files`, the
  //    list re-renders, updateConf() re-runs, and — the LOAD-BEARING invariant — a removed file must
  //    NEVER ship in the packaged zip. Two EDIs are added; the FIRST (a dms_sign_ambiguous-flagged
  //    station, so it also drives the conflict count) is removed; then we assert the list, the DMS
  //    conflict count, and the REAL packaged zip bytes.
  {
    // KEEPER = a clean-decimal station. GONE = HEAD/INFO DMS-sign conflict (flagged) — this is removed.
    const KEEPER_EDI = '>HEAD\nDATAID="KEEP"\nLAT=-28.20\nLONG=141.00\n\n>FREQ\n1 10 100\n>ZXYR\n1 2 3\n';
    const GONE_EDI = '>HEAD\nDATAID="GONE"\nLAT=-31.5\nLONG=140.10\n\n>INFO\nLATITUDE: -30.5\nLONGITUDE: 140.10\n\n>FREQ\n1 10 100\n>ZXYR\n1 2 3\n';
    const e = await boot({ probe: probeAbsent });
    fillValidMeta(e.win);
    await addEdi(e.win, "gone.edi", GONE_EDI);      // row 0 (flagged, to be removed)
    await addEdi(e.win, "keep.edi", KEEPER_EDI);    // row 1 (clean, survives)
    const doc = e.doc, filelist = doc.getElementById("filelist");

    // Precondition sanity: two rows present, and the flagged station shows a conflict count of 1.
    ok(filelist.querySelectorAll(".f").length === 2, "two file rows present before removal");
    ok(filelist.textContent.indexOf("gone.edi") >= 0 && filelist.textContent.indexOf("keep.edi") >= 0,
      "both filenames listed before removal");
    ok(doc.getElementById("dmsCount").textContent === "1",
      "updateConf reports 1 HEAD/INFO conflict before removal; got: " + doc.getElementById("dmsCount").textContent);
    ok(doc.getElementById("dmsChoice").style.display === "block",
      "the DMS resolver is shown while a flagged file is present");

    // Click the FIRST row's ✕ remove button (the flagged gone.edi). Its data-i is 0.
    const rmBtn = filelist.querySelector('.f button.rm[data-i="0"]');
    ok(rmBtn, "the first file row has a ✕ remove button");
    ok(/gone\.edi/.test(rmBtn.getAttribute("title")) && /gone\.edi/.test(rmBtn.getAttribute("aria-label")),
      "the remove button's title/aria-label name the file (escAttr path)");
    rmBtn.dispatchEvent(new e.win.Event("click", { bubbles: true }));

    // (a) THE LIST now shows ONLY the remaining file.
    ok(filelist.querySelectorAll(".f").length === 1, "exactly one row remains after removal");
    ok(filelist.textContent.indexOf("keep.edi") >= 0, "the kept file is still listed");
    ok(filelist.textContent.indexOf("gone.edi") < 0, "the removed file is gone from the list");

    // (c) updateConf ran on re-render: the flagged file left with its file, so the conflict count clears.
    ok(doc.getElementById("dmsCount").textContent === "0",
      "removing the flagged file clears the conflict count (updateConf); got: " + doc.getElementById("dmsCount").textContent);
    ok(doc.getElementById("dmsChoice").style.display === "none",
      "the DMS resolver hides once no flagged file remains");

    // (b) THE LOAD-BEARING ASSERTION: package now, and prove the zip carries ONLY the kept EDI. A
    //     removed file shipping here would be the exact regression this feature must prevent.
    await doc.getElementById("btnPackage").onclick();
    await new Promise((res) => setTimeout(res, 0));
    ok(e.record.blobs.length === 1, "the package path produced exactly one zip blob after removal");
    const zip = Buffer.from(await e.record.blobs[0].arrayBuffer());
    const JSZipNode = require(path.join(PORTAL, "vendor", "jszip.min.js"));
    const z = await JSZipNode.loadAsync(zip);
    const ediPaths = Object.keys(z.files).filter((p) => /transfer_functions\/edi\/.+\.edi$/.test(p));
    // task #16: entries are named by DATAID (KEEP -> KEEP.edi), NOT by the on-disk filename (keep.edi).
    // The remove feature must compose with the rename: only the KEPT station's DATAID-named entry ships.
    ok(ediPaths.length === 1 && /\/KEEP\.edi$/.test(ediPaths[0]),
      "the zip carries exactly one EDI, the kept one named by its DATAID (KEEP.edi); entries: " + JSON.stringify(ediPaths));
    ok(!ediPaths.some((p) => /\/GONE\.edi$/.test(p)), "the removed EDI's DATAID-named path is absent from the zip");
    // The DATAID-named entry present; the ORIGINAL on-disk filename must NOT survive as an entry PATH
    // (it may still appear inside MANIFEST.json as source_filename provenance — that's an entry VALUE,
    // asserted below — so we check the entry-name list, not the raw bytes, for the kept file).
    ok(!Object.keys(z.files).some((p) => /transfer_functions\/edi\/keep\.edi$/.test(p)),
      "the kept EDI is NOT a zip entry under its original lowercase filename (renamed to KEEP.edi)");
    // Scan the raw bytes for the REMOVED file: neither its name nor its unique DATAID may appear anywhere
    // (it was removed before packaging, so it must be wholly absent — no entry, no provenance, no bytes).
    ok(zip.indexOf(Buffer.from("gone.edi")) < 0, "the removed filename is absent from the zip bytes");
    ok(zip.indexOf(Buffer.from('DATAID="GONE"')) < 0, "the removed EDI's content is absent from the zip bytes");
    ok(zip.indexOf(Buffer.from('DATAID="KEEP"')) >= 0, "sanity: the kept EDI's content IS in the zip bytes");
    // MANIFEST.json records the ORIGINAL filename as additive provenance while `file` uses the DATAID name.
    const manEntry = z.file(/MANIFEST\.json$/);
    ok(manEntry.length === 1, "the zip contains exactly one MANIFEST.json");
    const man = JSON.parse(await manEntry[0].async("string"));
    ok(Array.isArray(man.transfer_functions) && man.transfer_functions.length === 1, "MANIFEST lists the one kept tf");
    ok(man.transfer_functions[0].file === "transfer_functions/edi/KEEP.edi",
      "MANIFEST `file` is the DATAID-based path; got: " + man.transfer_functions[0].file);
    ok(man.transfer_functions[0].source_filename === "keep.edi",
      "MANIFEST `source_filename` records the original selected name; got: " + man.transfer_functions[0].source_filename);
  }

  // --------------------------------------------------------------------------------------------------
  // 7. DATAID-BASED PACKAGING (task #16): files package under <sanitized-DATAID>.edi (matching the
  //    station identity the engine keys off), the file list shows the rename BEFORE upload, and a
  //    duplicate/unreadable DATAID BLOCKS submission naming both source filenames (fail loud, no silent
  //    auto-suffixing). The motivating case: olympic-dam-2004 ships LineNo__StationNo_1.edi whose
  //    DATAIDs are ROX000 etc — the packaged names must be ROX000.edi, not the line/station filename.
  {
    // Realistic olympic-dam shape: on-disk name LineNo__StationNo_1.edi, DATAID="ROX000" in >HEAD.
    const ROX0 = '\x3eHEAD\nDATAID="ROX000"\nLAT=-30.10\nLONG=136.60\n\n\x3eFREQ\n1 10 100\n\x3eZXYR\n1 2 3\n';
    const ROX1 = '\x3eHEAD\nDATAID="ROX001"\nLAT=-30.20\nLONG=136.70\n\n\x3eFREQ\n1 10 100\n\x3eZXYR\n1 2 3\n';

    // (7a) rename PREVIEW in the file list: "1__1_1.edi → ROX000.edi" is shown before any upload.
    {
      const e = await boot({ probe: probeAbsent });
      fillValidMeta(e.win);
      await addEdi(e.win, "1__1_1.edi", ROX0);
      const fl = e.doc.getElementById("filelist");
      ok(/1__1_1\.edi/.test(fl.textContent), "the file list shows the original selected filename");
      ok(/→\s*ROX000\.edi/.test(fl.textContent),
        "the file list shows the DATAID rename preview (→ ROX000.edi); got: " + fl.textContent.replace(/\s+/g, " ").trim());
    }

    // (7b) the packaged zip names the EDI by DATAID (ROX000.edi), not by the LineNo__StationNo filename.
    {
      const e = await boot({ probe: probeAbsent });
      fillValidMeta(e.win);
      await addEdi(e.win, "1__1_1.edi", ROX0);
      await e.doc.getElementById("btnPackage").onclick();
      await new Promise((res) => setTimeout(res, 0));
      ok(e.record.blobs.length === 1, "packaging the DATAID case produced one zip blob");
      const zip = Buffer.from(await e.record.blobs[0].arrayBuffer());
      const JSZipNode = require(path.join(PORTAL, "vendor", "jszip.min.js"));
      const z = await JSZipNode.loadAsync(zip);
      const ediPaths = Object.keys(z.files).filter((p) => /transfer_functions\/edi\/.+\.edi$/.test(p));
      ok(ediPaths.length === 1 && /\/ROX000\.edi$/.test(ediPaths[0]),
        "the zip entry is named by DATAID (ROX000.edi), not the on-disk filename; entries: " + JSON.stringify(ediPaths));
      ok(!Object.keys(z.files).some((p) => /1__1_1\.edi$/.test(p)),
        "the on-disk filename is NOT a zip entry PATH (renamed); the original name survives only as MANIFEST source_filename");
      // and it IS preserved as additive provenance inside MANIFEST.json.
      const man2 = JSON.parse(await z.file(/MANIFEST\.json$/)[0].async("string"));
      ok(man2.transfer_functions[0].file === "transfer_functions/edi/ROX000.edi"
        && man2.transfer_functions[0].source_filename === "1__1_1.edi",
        "MANIFEST: file=ROX000.edi (DATAID) + source_filename=1__1_1.edi (original)");
    }

    // (7c) DUPLICATE DATAID blocks submission, and the message names BOTH source filenames. Two files
    //      with the same DATAID (copy-paste mistake) is a FAIL — no silent auto-suffix.
    {
      const e = await boot({ probe: probeAbsent });
      fillValidMeta(e.win);
      await addEdi(e.win, "line1__station1_1.edi", ROX0);
      await addEdi(e.win, "line2__station7_1.edi", ROX0);          // SAME DATAID="ROX000"
      e.doc.getElementById("btnValidate").onclick();
      const vtext = e.doc.getElementById("vList").textContent;
      ok(/FAIL/.test(e.doc.getElementById("vSummary").textContent), "a duplicate DATAID makes validation FAIL");
      ok(/line1__station1_1\.edi/.test(vtext) && /line2__station7_1\.edi/.test(vtext),
        "the duplicate-DATAID error names BOTH source filenames; got: " + vtext.replace(/\s+/g, " ").trim());
      // and it BLOCKS packaging (buildPackage returns blocked on any FAIL).
      await e.doc.getElementById("btnPackage").onclick();
      await new Promise((res) => setTimeout(res, 0));
      ok(e.record.blobs.length === 0, "a duplicate DATAID blocks packaging (no zip produced)");
      ok(/validation FAIL/i.test(e.doc.getElementById("pkBody").textContent), "packaging is blocked with a FAIL message");
    }

    // (7d) UNREADABLE / ABSENT DATAID blocks submission: an EDI with no DATAID line cannot be named.
    {
      const NOID = '\x3eHEAD\nLAT=-30.10\nLONG=136.60\n\n\x3eFREQ\n1 10 100\n\x3eZXYR\n1 2 3\n';
      const e = await boot({ probe: probeAbsent });
      fillValidMeta(e.win);
      await addEdi(e.win, "no-dataid.edi", NOID);
      // the file list flags it (red "no DATAID") before any submit attempt.
      ok(/no DATAID/i.test(e.doc.getElementById("filelist").textContent),
        "the file list flags a missing DATAID before submission");
      e.doc.getElementById("btnValidate").onclick();
      const vtext = e.doc.getElementById("vList").textContent;
      ok(/FAIL/.test(e.doc.getElementById("vSummary").textContent), "a missing DATAID makes validation FAIL");
      ok(/no-dataid\.edi/.test(vtext) && /DATAID/.test(vtext),
        "the missing-DATAID error names the source file; got: " + vtext.replace(/\s+/g, " ").trim());
      await e.doc.getElementById("btnPackage").onclick();
      await new Promise((res) => setTimeout(res, 0));
      ok(e.record.blobs.length === 0, "a missing DATAID blocks packaging (no zip produced)");
    }
  }

  console.log("SUBMIT-TEST PASSED (probe gating, double-submit guard, key-hygiene: header-only, " +
    "escaped 201 link, XSS-inert hostile detail/status_url, fail-fast empty-key + bad-ORCID gates, " +
    "SUBMISSION.md sequential numbering both branches, per-row file remove: list + DMS conflict count + " +
    "removed file absent from packaged zip bytes, DATAID packaging: rename preview + DATAID-named zip entry + " +
    "MANIFEST source_filename + duplicate/missing DATAID blocks naming both filenames)");
  process.exit(0);
})().catch((e) => die((e && e.stack) || String(e)));
