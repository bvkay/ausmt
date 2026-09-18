// jsdom test: the surveys hub's controls search, filter and sort the cards IN THE PAGE.
//
// The engine renders the hub with the controls hidden and every card's facts as data attributes
// (engine/extract/_pages.py surveys_index_page; the engine's page test pins the ids, names and
// attributes this fixture mirrors). This test builds a hub-shaped DOM with three cards, runs
// portal/src/surveys-hub.js in the window as the page's <script src> would, and drives the controls:
// the form is revealed, the default order is the page's own, each sort reorders the cards, each
// filter narrows them and the shown count follows, the URL query carries the view and a page opened
// at that URL restores it, submit stays in the page, and Clear returns to the whole list.
//
//   node tests/surveys_hub.test.js       exit 0 passed, 1 failed, 2 jsdom missing (the wrapper skips)
const fs = require("fs"), path = require("path"), vm = require("vm");
let JSDOM;
try { ({ JSDOM } = require("jsdom")); }
catch (e) { console.error("SKIP: jsdom not installed (run `npm ci` in portal/)"); process.exit(2); }

const SRC = path.join(path.resolve(__dirname, ".."), "src", "surveys-hub.js");
let fail = 0;
const ok = (c, m) => { console.log((c ? "  ok   " : "  FAIL ") + m); if (!c) fail++; };

const card = (f) =>
  '<article class="idxcard" data-slug="' + f.slug + '" data-title="' + f.title + '" data-org="' + f.org +
  '" data-region="' + f.region + '" data-stations="' + f.stations + '" data-y0="' + (f.y0 || "") +
  '" data-y1="' + (f.y1 || "") + '" data-types="' + f.types + '" data-lic="' + f.lic + '" data-doi="' +
  (f.doi ? "1" : "") + '"><div></div><div><h2 class="idxt"><a href="/surveys/' + f.slug + '">' + f.title +
  "</a></h2></div></article>";
const CARDS = [
  {slug: "alpha-2013", title: "Alpha Survey", org: "Org X", region: "South Australia", stations: 10,
   y0: 2013, y1: 2014, types: "MT", lic: "CC BY 4.0", doi: true},
  {slug: "beta-1983", title: "Beta Array", org: "Org Y", region: "Tasmania", stations: 35,
   y0: 1983, y1: 1984, types: "GDS MT", lic: "CC BY 3.0 AU", doi: false},
  {slug: "gamma", title: "Gamma Traverse", org: "Org X", region: "Western Australia", stations: 5,
   y0: null, y1: null, types: "AMT", lic: "CC BY 4.0", doi: false}];
const select = (name, values) =>
  '<label><span>' + name + '</span><select name="' + name + '"><option value="">Any</option>' +
  values.map(v => '<option value="' + v + '">' + v + "</option>").join("") + "</select></label>";
const form =
  '<form class="idxctl" id="idxctl" method="get" action="/surveys" hidden>' +
  '<label class="idxq"><span>Search</span><input type="search" name="q"></label>' +
  select("type", ["AMT", "GDS", "MT"]) + select("org", ["Org X", "Org Y"]) +
  select("region", ["South Australia", "Tasmania", "Western Australia"]) +
  select("lic", ["CC BY 3.0 AU", "CC BY 4.0"]) +
  '<label><span>Sort</span><select name="sort"><option value="title">Title, A to Z</option>' +
  '<option value="stations">Most stations</option><option value="newest">Newest first</option>' +
  '<option value="oldest">Oldest first</option><option value="org">Organisation</option></select></label>' +
  '<p class="idxshown" aria-live="polite"><span id="idxShown">3</span> of 3 surveys shown' +
  ' <a id="idxReset" href="/surveys" hidden>Clear</a></p></form>';
const html = "<!DOCTYPE html><html><body><main>" + form + '<div class="idxlist">' +
  CARDS.map(card).join("") + "</div></main></body></html>";

function page(query) {
  const dom = new JSDOM(html, { url: "https://ausmt.auscope.org.au/surveys" + (query || ""),
                                runScripts: "outside-only", pretendToBeVisual: true });
  const win = dom.window, doc = win.document;
  new vm.Script(fs.readFileSync(SRC, "utf8"), { filename: "surveys-hub.js" }).runInContext(dom.getInternalVMContext());
  const f = doc.getElementById("idxctl");
  const set = (name, value) => {
    const el = f.elements.namedItem(name);
    el.value = value;
    el.dispatchEvent(new win.Event(el.tagName === "SELECT" ? "change" : "input", { bubbles: true }));
  };
  const visible = () => Array.from(doc.querySelectorAll("article.idxcard")).filter(a => !a.hidden).map(a => a.dataset.slug);
  const shown = () => doc.getElementById("idxShown").textContent;
  return { win, doc, f, set, visible, shown };
}

// 1. Reveal and the page's own order.
let p = page("");
ok(!p.f.hidden, "the script reveals the hidden form");
ok(p.visible().join() === "alpha-2013,beta-1983,gamma", "the default order is the page's own, by title: " + p.visible());
ok(p.shown() === "3", "every card counts as shown at the start");
ok(p.doc.getElementById("idxReset").hidden, "Clear stays hidden while nothing is set");

// 2. Sorts.
p.set("sort", "stations");
ok(p.visible().join() === "beta-1983,alpha-2013,gamma", "most stations first: " + p.visible());
p.set("sort", "newest");
ok(p.visible().join() === "alpha-2013,beta-1983,gamma", "newest first, a survey with no year last: " + p.visible());
p.set("sort", "oldest");
ok(p.visible().join() === "beta-1983,alpha-2013,gamma", "oldest first, a survey with no year still last: " + p.visible());
p.set("sort", "org");
ok(p.visible().join() === "alpha-2013,gamma,beta-1983", "by organisation, then title: " + p.visible());
ok(p.win.location.search === "?sort=org", "the sort rides the URL: " + p.win.location.search);
p.set("sort", "title");
ok(p.win.location.search === "", "the default sort writes no query");

// 3. Filters and the count.
p.set("type", "GDS");
ok(p.visible().join() === "beta-1983" && p.shown() === "1", "a data type keeps the surveys carrying it: " + p.visible());
ok(!p.doc.getElementById("idxReset").hidden, "Clear appears once a filter is set");
p.set("type", "");
p.set("org", "Org X");
ok(p.visible().join() === "alpha-2013,gamma" && p.shown() === "2", "an organisation narrows to its surveys: " + p.visible());
p.set("region", "Western Australia");
ok(p.visible().join() === "gamma", "filters combine: " + p.visible());
p.set("region", "");
p.set("lic", "CC BY 3.0 AU");
ok(p.visible().length === 0 && p.shown() === "0", "a licence no kept survey carries shows none");
p.set("lic", "");
p.set("org", "");
p.set("q", "  Tasmania ");
ok(p.visible().join() === "beta-1983", "search reads the region: " + p.visible());
p.set("q", "org x gamma");
ok(p.visible().join() === "gamma", "every search word must match: " + p.visible());
ok(p.win.location.search === "?q=org%20x%20gamma", "the search rides the URL encoded: " + p.win.location.search);

// 4. Submit stays in the page.
const submit = new p.win.Event("submit", { bubbles: true, cancelable: true });
p.f.dispatchEvent(submit);
ok(submit.defaultPrevented, "submit is answered in the page, not by a reload");

// 5. Clear.
const click = new p.win.MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
p.doc.getElementById("idxReset").dispatchEvent(click);
ok(click.defaultPrevented && p.visible().length === 3 && p.shown() === "3" && p.win.location.search === "",
   "Clear returns the whole list and empties the query");

// 6. A page opened at a shared URL restores the view; a value no option offers reads as any.
p = page("?q=alpha&sort=stations&type=MT&org=Nobody");
ok(p.f.elements.namedItem("q").value === "alpha" && p.f.elements.namedItem("sort").value === "stations",
   "the query fills the controls");
ok(p.f.elements.namedItem("org").value === "", "an organisation the page does not offer is not selected");
ok(p.visible().join() === "alpha-2013" && p.shown() === "1", "the restored view is applied: " + p.visible());

console.log(fail ? "FAILED " + fail : "ALL PASSED");
process.exit(fail ? 1 : 0);
