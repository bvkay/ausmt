"use strict";

const HUB_KEYS = ["q", "type", "org", "region", "lic", "sort"];

function hubFacts(el){
  const d = el.dataset || {};
  const year = v => { const n = parseInt(v, 10); return isNaN(n) ? null : n; };
  return {el, title: d.title || "", org: d.org || "", region: d.region || "", slug: d.slug || "",
          stations: year(d.stations) || 0, y0: year(d.y0), y1: year(d.y1),
          types: (d.types || "").split(" ").filter(Boolean), lic: d.lic || "",
          text: [d.title, d.org, d.region, d.slug].join(" ").toLowerCase()};
}

function hubSelect(rows, s){
  const words = (s.q || "").toLowerCase().split(/\s+/).filter(Boolean);
  const keep = rows.filter(r =>
    words.every(w => r.text.indexOf(w) >= 0) &&
    (!s.type || r.types.indexOf(s.type) >= 0) &&
    (!s.org || r.org === s.org) &&
    (!s.region || r.region === s.region) &&
    (!s.lic || r.lic === s.lic));
  const byTitle = (a, b) => a.title.localeCompare(b.title, "en") || a.slug.localeCompare(b.slug, "en");
  const last = v => v === null ? -Infinity : v;
  const first = v => v === null ? Infinity : v;
  const orders = {
    title: byTitle,
    stations: (a, b) => (b.stations - a.stations) || byTitle(a, b),
    newest: (a, b) => (last(b.y1) - last(a.y1)) || (last(b.y0) - last(a.y0)) || byTitle(a, b),
    oldest: (a, b) => (first(a.y0) - first(b.y0)) || (first(a.y1) - first(b.y1)) || byTitle(a, b),
    org: (a, b) => a.org.localeCompare(b.org, "en") || byTitle(a, b)};
  return keep.slice().sort(orders[s.sort] || orders.title);
}

function hubQuery(s){
  const p = [];
  HUB_KEYS.forEach(k => {
    const v = (s[k] || "").trim();
    if (!v || (k === "sort" && v === "title")) return;
    p.push(encodeURIComponent(k) + "=" + encodeURIComponent(v));
  });
  return p.join("&");
}

(function(){
  if (typeof document === "undefined" || !document.getElementById) return;
  const form = document.getElementById("idxctl"), list = document.querySelector(".idxlist");
  if (!form || !list) return;
  const rows = Array.from(list.querySelectorAll("article.idxcard")).map(hubFacts);
  const shown = document.getElementById("idxShown"), reset = document.getElementById("idxReset");
  const field = k => form.elements.namedItem(k);
  const setField = (k, v) => {
    const f = field(k);
    if (!f) return;
    f.value = v || "";
    if (f.tagName === "SELECT" && f.value !== (v || "")) f.value = "";
  };
  const state = () => {
    const s = {};
    HUB_KEYS.forEach(k => { const f = field(k); s[k] = f ? String(f.value || "").trim() : ""; });
    return s;
  };
  function apply(){
    const s = state(), keep = hubSelect(rows, s), kept = new Set(keep);
    rows.forEach(r => { r.el.hidden = !kept.has(r); });
    keep.concat(rows.filter(r => !kept.has(r))).forEach(r => list.appendChild(r.el));
    if (shown) shown.textContent = keep.length.toLocaleString("en");
    const query = hubQuery(s);
    if (reset) reset.hidden = !query;
    if (window.history && window.history.replaceState) {
      window.history.replaceState(null, "", window.location.pathname + (query ? "?" + query : "") + window.location.hash);
    }
  }
  const params = new URLSearchParams(window.location.search);
  HUB_KEYS.forEach(k => { if (params.has(k)) setField(k, params.get(k)); });
  form.hidden = false;
  form.addEventListener("input", apply);
  form.addEventListener("change", apply);
  form.addEventListener("submit", e => { e.preventDefault(); apply(); });
  if (reset) reset.addEventListener("click", e => {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    HUB_KEYS.forEach(k => setField(k, ""));
    apply();
    const q = field("q");
    if (q && q.focus) q.focus();
  });
  apply();
})();
