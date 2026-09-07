// jsdom test: the survey page's "Build a download script" link opens the terminal dialog IN THE PAGE.
//
// A generated survey page (engine/extract/_pages.py survey_page) carries the SPA's #wgetModal markup,
// one anchor per raw-family level card and three external scripts: fetchcmd.js (the composers),
// fetchdialog.js (the dialog controller) and page-fetch.js (the page driver). This test builds a
// page-shaped DOM from the SPA's own dialog block (portal/index.html, held identical to the page's by
// the engine test), stubs fetch() with the shared fixture document (contract/fetch_handoff.json) and
// drives the click: the navigation is prevented, the document is fetched, the clicked level's rows are
// kept, the dialog opens with the composers' own output, Escape closes it and focus returns to the
// link. A fetch failure falls back to the anchor's href, the SPA deep link, through the
// pageFetchFallback seam.
//
//   node tests/page_fetch.test.js       exit 0 passed, 1 failed, 2 jsdom missing (the wrapper skips)
const fs = require("fs"), path = require("path"), vm = require("vm");
let JSDOM;
try { ({ JSDOM } = require("jsdom")); }
catch (e) { console.error("SKIP: jsdom not installed (run `npm ci` in portal/)"); process.exit(2); }

const PORTAL = path.resolve(__dirname, "..");
const SRC = path.join(PORTAL, "src");
const FIX = JSON.parse(fs.readFileSync(path.join(PORTAL, "..", "contract", "fetch_handoff.json"), "utf8"));
const index = fs.readFileSync(path.join(PORTAL, "index.html"), "utf8");
const mStart = index.indexOf('<div id="wgetModal"'), mEnd = index.indexOf('<div id="introWelcome"');
if (mStart < 0 || mEnd < 0) { console.error("FAIL: index.html carries no #wgetModal block"); process.exit(1); }
const dialog = index.slice(mStart, mEnd);

let fail = 0;
const ok = (c, m) => { console.log((c ? "  ok   " : "  FAIL ") + m); if (!c) fail++; };
const read = f => fs.readFileSync(path.join(SRC, f + ".js"), "utf8");
const tick = () => new Promise(r => setTimeout(r, 0));

const DOC_URL = "/data/pages/fetch/" + FIX.survey.slug + ".json";
const anchor = (level) =>
  '<p class="lvlact"><a class="lvlact-fetch" href="/#/survey/' + FIX.survey.slug + "?fetch=" + level + '"' +
  ' data-fetch="' + DOC_URL + '" data-level="' + level + '">Build a download script</a>' +
  ' &#183; <a href="' + DOC_URL + '">Pointers file (JSON)</a></p>';
const html = "<!DOCTYPE html><html><body><main>" + anchor("raw_packed") + anchor("level0") + "</main>" +
  dialog + "</body></html>";

async function drive(fetchImpl) {
  const dom = new JSDOM(html, { url: FIX.base + "/surveys/" + FIX.survey.slug, runScripts: "outside-only",
                                pretendToBeVisual: true });
  const win = dom.window, doc = win.document;
  const fetched = [];
  win.fetch = (u, opts) => { fetched.push(String(u)); return fetchImpl(String(u), opts); };
  const navigated = [];
  // Run as SCRIPTS in the window's own context, as the page's <script src> tags would: a strict-mode
  // eval keeps its function declarations to itself, and the driver's seam must be a window global.
  const ctx = dom.getInternalVMContext();
  ["fetchcmd", "fetchdialog", "page-fetch"].forEach(f => new vm.Script(read(f), { filename: f + ".js" }).runInContext(ctx));
  win.pageFetchFallback = href => navigated.push(href);
  return { win, doc, fetched, navigated };
}

(async () => {
  // 1. The click opens the dialog with the clicked level's rows composed by the shared composers.
  const good = (u) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(FIX.document) });
  let { win, doc, fetched, navigated } = await drive(good);
  const modal = doc.getElementById("wgetModal"), cmd = doc.getElementById("wgetCmd");
  ok(modal && modal.classList.contains("hidden"), "the dialog starts hidden");
  const links = [...doc.querySelectorAll("a[data-fetch]")];
  ok(links.length === 2, "one fetch anchor per level card, got " + links.length);
  const a = links[0];
  a.focus();
  const ev = new win.MouseEvent("click", { bubbles: true, cancelable: true });
  const notCancelled = a.dispatchEvent(ev);
  ok(notCancelled === false, "the click is prevented: the page answers, not the SPA");
  await tick(); await tick();
  ok(fetched.length === 1 && fetched[0] === DOC_URL,
     "exactly the anchor's data-fetch document is fetched, got " + JSON.stringify(fetched));
  ok(!modal.classList.contains("hidden"), "the dialog opens on the page");
  ok(navigated.length === 0, "no navigation when the fetch succeeds");
  const tabs = [...doc.getElementById("wgetOs").querySelectorAll("button")];
  ok(tabs.filter(b => b.classList.contains("on")).length === 1 &&
     tabs.filter(b => b.getAttribute("aria-selected") === "true").length === 1,
     "one OS tab is selected, in the class and in aria-selected");
  tabs.find(b => b.dataset.os === "linux").click();
  ok(cmd.textContent === FIX.commands.raw_packed.unix,
     "the Linux command is the composers' output for the clicked level alone, got " + JSON.stringify(cmd.textContent));
  tabs.find(b => b.dataset.os === "mac").click();
  ok(cmd.textContent === FIX.commands.raw_packed.mac, "the macOS command follows the tab");
  tabs.find(b => b.dataset.os === "win").click();
  ok(cmd.textContent === FIX.commands.raw_packed.win, "the Windows command follows the tab");
  ok(/preinstalled on Windows 10/.test(doc.getElementById("wgetOsNote").textContent), "the OS note follows the tab");
  // Escape closes and focus returns to the link that opened it.
  doc.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  ok(modal.classList.contains("hidden"), "Escape closes the dialog");
  ok(doc.activeElement === a, "focus returns to the link that opened the dialog");
  // The second card's link fetches the same document and keeps ITS level.
  links[1].dispatchEvent(new win.MouseEvent("click", { bubbles: true, cancelable: true }));
  await tick(); await tick();
  tabs.find(b => b.dataset.os === "linux").click();
  ok(!modal.classList.contains("hidden") && /level0/.test(cmd.textContent) && !/raw_packed/.test(cmd.textContent),
     "the level0 card composes level0 rows only, got " + JSON.stringify(cmd.textContent));
  doc.getElementById("wgetClose").click();
  ok(modal.classList.contains("hidden"), "Close hides the dialog");

  // 2. A failed fetch falls back to the anchor's own href, the SPA deep link.
  ({ win, doc, fetched, navigated } = await drive(() => Promise.reject(new Error("offline"))));
  const a2 = doc.querySelector("a[data-fetch]");
  a2.dispatchEvent(new win.MouseEvent("click", { bubbles: true, cancelable: true }));
  await tick(); await tick();
  ok(doc.getElementById("wgetModal").classList.contains("hidden"), "no dialog opens on a failed fetch");
  ok(navigated.length === 1 && /\/#\/survey\/example-survey\?fetch=raw_packed$/.test(navigated[0]),
     "a failed fetch hands the reader to the SPA deep link, got " + JSON.stringify(navigated));
  // A 404 is a failure too: the document is written only for surveys with a routed row.
  ({ win, doc, fetched, navigated } = await drive(() => Promise.resolve({ ok: false, status: 404, json: () => Promise.reject(new Error("no body")) })));
  doc.querySelector("a[data-fetch]").dispatchEvent(new win.MouseEvent("click", { bubbles: true, cancelable: true }));
  await tick(); await tick();
  ok(navigated.length === 1, "a non-2xx answer falls back to the deep link too");

  if (fail) { console.log("\n" + fail + " FAILED"); process.exit(1); }
  console.log("\nALL PASSED");
})().catch(e => { console.error("FAIL: " + (e && e.stack || e)); process.exit(1); });
