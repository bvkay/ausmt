"use strict";
// Appearance: the house style (light) by default, today's navy palette as dark. The remembered choice is
// applied here, synchronously in <head>, so the first paint is already in the chosen theme; the deployed
// CSP allows no inline script, which is why this is a file. The stored choice is localStorage
// "ausmt_theme" = "light" | "dark" | "system"; anything else, including nothing, means light. The RESOLVED
// theme is written to <html data-theme="light|dark">, which is the only hook the stylesheets use, and a
// change dispatches "ausmt:theme" on document with detail {theme} for scripts that draw outside CSS (the
// basemap flavour and the dot edges in map.js). Controls need no script of their own: any element with
// data-theme-choice="light|dark|system" sets the choice on click, and radio inputs named welcomeTheme set
// it on change; both are kept in step with the stored choice whenever it is applied.
(function () {
  var KEY = "ausmt_theme";
  var root = document.documentElement;
  var mq = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  function choice() {
    try { var v = localStorage.getItem(KEY); return v === "dark" || v === "system" ? v : "light"; }
    catch (e) { return "light"; }
  }
  function resolve(c) { return c === "dark" || (c === "system" && mq && mq.matches) ? "dark" : "light"; }
  function reflect() {
    var c = choice(), t = resolve(c);
    var buttons = document.querySelectorAll("[data-theme-choice]");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].setAttribute("aria-pressed", buttons[i].getAttribute("data-theme-choice") === t ? "true" : "false");
    }
    var radios = document.querySelectorAll('input[name="welcomeTheme"]');
    for (var j = 0; j < radios.length; j++) radios[j].checked = radios[j].value === c;
  }
  function apply() {
    var t = resolve(choice());
    if (root.getAttribute("data-theme") !== t) {
      root.setAttribute("data-theme", t);
      document.dispatchEvent(new CustomEvent("ausmt:theme", { detail: { theme: t } }));
    }
    reflect();
  }
  function set(c) {
    if (c !== "light" && c !== "dark" && c !== "system") return;
    try { localStorage.setItem(KEY, c); } catch (e) { /* storage unavailable: the choice lasts this page */ }
    apply();
  }
  root.setAttribute("data-theme", resolve(choice()));
  if (mq && mq.addEventListener) mq.addEventListener("change", function () { if (choice() === "system") apply(); });
  document.addEventListener("DOMContentLoaded", function () {
    document.addEventListener("click", function (e) {
      var b = e.target && e.target.closest ? e.target.closest("[data-theme-choice]") : null;
      if (b) set(b.getAttribute("data-theme-choice"));
    });
    document.addEventListener("change", function (e) {
      var r = e.target;
      if (r && r.name === "welcomeTheme" && r.checked) set(r.value);
    });
    reflect();
  });
  window.AusmtTheme = { get: choice, resolved: function () { return resolve(choice()); }, set: set };
})();
