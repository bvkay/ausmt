// Dump the survey.yaml the REAL add-survey page packages, for each of a
// set of credit/citation scenarios, so the REAL surveys validator can be run over them.
//
// This driver asserts nothing itself. It boots the page in jsdom exactly as tools/add_survey_submit_test.js
// does (same script order, same JSZip, same download-path capture), drives the live DOM for each scenario,
// and unpacks the packaged zip into
//
//     $AUSMT_PACKAGED_YAML_DIR/<slug>/
//
// as a validator-shaped package (survey.yaml + transfer_functions/edi/*.edi, folder named for the slug).
// tests/test_add_survey_packaged_yaml.py then runs the real validator over every one of them and asserts
// zero FAILs: the form's own output, checked by the oracle that gates the pipeline, not by a same-author
// expectation of what the YAML should look like.
//
//   AUSMT_PACKAGED_YAML_DIR=/tmp/x node tools/packaged_yaml_dump.js
//
// Exit codes:  0 = wrote every scenario   1 = a real failure   2 = jsdom missing (caller SKIPs)
const fs = require("fs"), path = require("path"), vm = require("vm");
let JSDOM;
try { ({ JSDOM } = require("jsdom")); }
catch (e) { console.error("SKIP: jsdom not installed (run `npm ci` in portal/)"); process.exit(2); }

const TOOLS = __dirname;
const PORTAL = path.resolve(TOOLS, "..");
const SRC = path.join(PORTAL, "src");
const html = fs.readFileSync(path.join(PORTAL, "add-survey.html"), "utf8");
const OUT = process.env.AUSMT_PACKAGED_YAML_DIR;
if (!OUT) { console.error("DUMP FAILED: AUSMT_PACKAGED_YAML_DIR is not set"); process.exit(1); }

function die(msg) { console.error("DUMP FAILED: " + msg); process.exit(1); }
const EDI_TEXT = '>HEAD\nDATAID="S01"\nLAT=-30.10\nLONG=136.20\n\n>FREQ\n1 10 100\n>ZXYR\n1 2 3\n';

async function boot() {
  const dom = new JSDOM(html, { url: "http://localhost/", runScripts: "outside-only", pretendToBeVisual: true });
  const win = dom.window;
  win.L = undefined;
  win.JSZip = require(path.join(PORTAL, "vendor", "jszip.min.js"));
  const { webcrypto } = require("crypto");
  if (!win.crypto || !win.crypto.subtle) {
    try { Object.defineProperty(win, "crypto", { value: webcrypto, configurable: true, writable: true }); }
    catch (e) { win.crypto = webcrypto; }
  }
  const { TextEncoder, TextDecoder } = require("util");
  if (!win.TextEncoder) win.TextEncoder = TextEncoder;
  if (!win.TextDecoder) win.TextDecoder = TextDecoder;
  const record = { blobs: [] };
  win.URL.createObjectURL = (b) => { record.blobs.push(b); return "blob:mock"; };
  win.URL.revokeObjectURL = () => {};
  win.fetch = () => Promise.reject(new Error("no gateway"));   // probe absent: the download path is used
  await new Promise((res) => (win.document.readyState === "complete" ? res() : win.addEventListener("load", res, { once: true })));
  const security = fs.readFileSync(path.join(SRC, "security.js"), "utf8");
  const shim = fs.readFileSync(path.join(SRC, "analytics-shim.js"), "utf8");
  const doiHarvest = fs.readFileSync(path.join(SRC, "doi_harvest.js"), "utf8");
  const inline = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]).find((b) => b.includes("function buildSurveyYaml"));
  if (!inline) die("could not extract the inline pure-logic+UI script block");
  vm.runInContext(security + "\n" + shim + "\n" + doiHarvest + "\n" + inline, dom.getInternalVMContext());
  await new Promise((res) => setTimeout(res, 0));
  return { win, doc: win.document, record };
}

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

function fillRequired(win, slug) {
  const $ = (id) => win.document.getElementById(id);
  $("m_name").value = "Packaged " + slug;
  $("m_slug").value = slug;
  $("m_org").value = "Geological Survey of South Australia";
  $("m_ror").value = "https://ror.org/04y8k6r48";
  $("m_country").value = "Australia";
  // The licence <select> is populated at runtime from the generated contract; in jsdom the option list
  // may be empty, so add the one we want rather than leaving the package at the "TBD" default.
  const lic = $("m_license");
  if (!Array.from(lic.options).some((o) => o.value === "CC-BY-4.0")) {
    const o = win.document.createElement("option"); o.value = "CC-BY-4.0"; o.textContent = "CC-BY-4.0";
    lic.appendChild(o);
  }
  lic.value = "CC-BY-4.0";
  $("m_up_name").value = "Ada Lovelace"; $("m_up_email").value = "ada@example.org";
  $("m_auth").checked = true; $("m_licdecl").checked = true; $("m_locconf").checked = true;
}

// Every scenario the form's new credit questions can produce, driven through the LIVE DOM.
const SCENARIOS = {
  // The bare case: only the essentials. Proves the seeded custodian row alone validates.
  "packaged-bare": () => {},
  // Every new question filled at once: the lead row, the citation wording + a pasted DOI, extra
  // organisation roles, required wording, and a publication date.
  "packaged-full": (doc) => {
    doc.getElementById("m_date_issued").value = "2016-05-01";
    doc.getElementById("m_lead_name").value = "Duan, Jingming";
    doc.getElementById("m_lead_orcid").value = "0000-0002-1825-0097";
    doc.getElementById("m_cite_text").value = "GSSA (2016). AusLAMP South Australia. [Data set].";
    doc.getElementById("m_cite_identifier").value = "https://doi.org/10.25914/abc";
    doc.getElementById("addOrg").onclick();
    const org = doc.querySelector("#orgRows .orgrow");
    org.querySelector(".og-name").value = "Geoscience Australia";
    org.querySelector(".og-ror").value = "https://ror.org/04ge02x20";
    org.querySelector('.og-role[value="publisher"]').checked = true;
    org.querySelector('.og-role[value="distributor"]').checked = true;
    doc.getElementById("addAck").onclick();
    const ack = doc.querySelector("#ackRows .ackrow");
    ack.querySelector(".ak-text").value = "Data supplied by the Geological Survey of South Australia.";
    ack.querySelector(".ak-type").value = "custodian";
    ack.querySelector(".ak-source").value = "GSSA licence deed";
    const cr = doc.querySelector("#creatorRows .creatorrow");
    cr.querySelector(".cr-name").value = "Thiel, Stephan";
    cr.querySelector(".cr-id").value = "0000-0002-1825-0097";
  },
  // A URL-typed citation identifier plus a chosen data level, and the essential organisation named
  // AGAIN with extra roles (the merge branch).
  "packaged-url-citation": (doc) => {
    doc.getElementById("m_cite_identifier").value = "https://ecat.ga.gov.au/geonetwork/record/1";
    doc.getElementById("m_cite_identifies").value = "entire";
    doc.getElementById("addOrg").onclick();
    const org = doc.querySelector("#orgRows .orgrow");
    org.querySelector(".og-name").value = "Geological Survey of South Australia";
    org.querySelector('.og-role[value="data_collector"]').checked = true;
  },
};

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  for (const [slug, fill] of Object.entries(SCENARIOS)) {
    const e = await boot();
    fillRequired(e.win, slug);
    await addEdi(e.win, "S01.edi", EDI_TEXT);
    fill(e.doc);
    await e.doc.getElementById("btnPackage").onclick();
    await new Promise((res) => setTimeout(res, 0));
    if (e.record.blobs.length !== 1) die(slug + ": packaging produced " + e.record.blobs.length + " zip blob(s)");
    const buf = Buffer.from(await e.record.blobs[0].arrayBuffer());
    const JSZipNode = require(path.join(PORTAL, "vendor", "jszip.min.js"));
    const z = await JSZipNode.loadAsync(buf);
    // The validator wants the package folder NAMED for the slug, so strip the zip's own root prefix.
    const dest = path.join(OUT, slug);
    let wroteYaml = false, wroteEdi = 0;
    for (const name of Object.keys(z.files)) {
      const entry = z.files[name];
      if (entry.dir) continue;
      const rel = name.split("/").slice(1).join("/");     // drop the zip's root folder
      if (!rel) continue;
      const target = path.join(dest, rel);
      fs.mkdirSync(path.dirname(target), { recursive: true });
      fs.writeFileSync(target, Buffer.from(await entry.async("nodebuffer")));
      if (rel === "survey.yaml") wroteYaml = true;
      if (/^transfer_functions\/edi\/.+\.edi$/.test(rel)) wroteEdi++;
    }
    if (!wroteYaml) die(slug + ": the packaged zip carried no survey.yaml");
    if (!wroteEdi) die(slug + ": the packaged zip carried no EDI");
    console.log("wrote " + dest);
  }
  console.log("PACKAGED-YAML DUMP OK (" + Object.keys(SCENARIOS).length + " scenarios)");
})().catch((err) => die(String((err && err.stack) || err)));
