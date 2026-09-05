"use strict";
// The map's attribution, collapsed to one glyph in the corner. Shared by every map this site draws: the
// SPA's, and add-survey's picker, station preview and confirmation maps. See docs: portal internals,
// mapattrib.js.
(function (global) {
  var OPEN = "mapattrib-open";
  var LABEL = "Map data attribution";

  // Decorate a mounted control's container. `el` is Leaflet's own container; the wrapper this returns is
  // what the page's rules style. See docs: portal internals, mapattrib.js.
  function decorate(el, label) {
    if (!el || el.nodeType !== 1 || !el.ownerDocument || !el.parentNode) return null;
    var doc = el.ownerDocument;
    var wrap = doc.createElement("div");
    wrap.className = "mapattrib leaflet-control";
    var btn = doc.createElement("button");
    btn.type = "button";
    btn.className = "mapattrib-toggle";
    // The glyph is one letter and says nothing on its own, so the label is what a screen reader
    // announces, and aria-expanded is what tells a reader whether the credit is showing.
    btn.setAttribute("aria-label", label || LABEL);
    btn.setAttribute("aria-expanded", "false");
    btn.textContent = "i";
    el.parentNode.insertBefore(wrap, el);
    wrap.appendChild(btn);
    wrap.appendChild(el);
    function setOpen(open) {
      if (open) wrap.classList.add(OPEN); else wrap.classList.remove(OPEN);
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    }
    // THREE WAYS IN and the same three ways out, so the control can never be left open with no way to close
    // it and never left closed with no way to open it without a pointer. See docs: portal internals,
    // mapattrib.js.
    var atPointer = null;
    btn.addEventListener("pointerdown", function () { atPointer = wrap.classList.contains(OPEN); });
    btn.addEventListener("click", function (ev) {
      if (ev && ev.preventDefault) ev.preventDefault();
      var was = atPointer === null ? wrap.classList.contains(OPEN) : atPointer;
      atPointer = null;
      setOpen(!was);
    });
    wrap.addEventListener("mouseenter", function () { setOpen(true); });
    wrap.addEventListener("mouseleave", function () { setOpen(false); });
    wrap.addEventListener("focusin", function () { setOpen(true); });
    wrap.addEventListener("focusout", function () { setOpen(false); });
    return wrap;
  }

  // Mount the control on `map` and collapse it. No credit is passed in: each tile layer declares its own
  // and the control collects them, which is what keeps the text honest about the provider. See docs: portal
  // internals, mapattrib.js.
  function mount(map, label) {
    var lib = global.L;
    if (!map || !lib || !lib.control || typeof lib.control.attribution !== "function") return null;
    var ctl = lib.control.attribution({ prefix: false });
    if (!ctl || typeof ctl.addTo !== "function") return null;
    ctl.addTo(map);
    var wrap = decorate(typeof ctl.getContainer === "function" ? ctl.getContainer() : null, label);
    // A control a reader can open must not pan or zoom the map underneath it. Leaflet guards its own
    // container; the wrapper is ours and needs the same guard.
    if (wrap && lib.DomEvent && typeof lib.DomEvent.disableClickPropagation === "function")
      lib.DomEvent.disableClickPropagation(wrap);
    return ctl;
  }

  global.AusmtMapAttrib = { mount: mount, decorate: decorate };
})(typeof window !== "undefined" ? window : globalThis);
