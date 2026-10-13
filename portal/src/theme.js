"use strict";
// Applies the remembered appearance before first paint; the CSP allows no inline script. See docs: portal internals, theme.js.
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
    var c = choice();
    var radios = document.querySelectorAll('input[name="appearance"]');
    for (var i = 0; i < radios.length; i++) radios[i].checked = radios[i].value === c;
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
    try { localStorage.setItem(KEY, c); } catch (e) { }
    apply();
  }
  root.setAttribute("data-theme", resolve(choice()));
  if (mq && mq.addEventListener) mq.addEventListener("change", function () { if (choice() === "system") apply(); });
  document.addEventListener("DOMContentLoaded", function () {
    document.addEventListener("change", function (e) {
      var r = e.target;
      if (r && r.name === "appearance" && r.checked) set(r.value);
    });
    reflect();
  });
  window.AusmtTheme = { get: choice, resolved: function () { return resolve(choice()); }, set: set };
})();
