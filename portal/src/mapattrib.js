"use strict";
// The map's attribution, collapsed to one glyph in the corner. Shared by every map this site draws:
// the SPA's, and add-survey's picker, station preview and confirmation maps.
//
// THE CREDIT IS A LICENCE TERM, not a courtesy. The basemap is OpenStreetMap data under ODbL and
// each tile provider asks for credit of its own, so what leaves the corner is the LINE and the
// Leaflet flag and word beside it, which are the courtesy. The control stays, with prefix:false.
//
// IT READS THE LAYERS, and that is why the credit is here rather than in a fixed line elsewhere on
// the page: map.js keeps a fallback to a different tile provider, and only the layer that is
// actually on the map knows which one is drawing. Leaflet's own control collects each layer's
// declared attribution, so the text is always what the reader is looking at.
//
// THE TOGGLE GOES IN A WRAPPER AROUND THE CONTROL, never inside it. Leaflet rewrites the
// attribution container's innerHTML on every attribution update, which is every time a layer is
// added or removed, so anything placed inside it is discarded the next time a layer changes.
//
// No dependency and no asset: the glyph is a text node and the rules live in the document that
// mounts this.
(function (global) {
  var OPEN = "mapattrib-open";
  var LABEL = "Map data attribution";

  // Decorate a mounted control's container. `el` is Leaflet's own container; the wrapper this
  // returns is what the page's rules style. Returns null when there is nothing real to decorate:
  // the headless harnesses stub Leaflet, and a stub's container is not a node.
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
    // THREE WAYS IN and the same three ways out, so the control can never be left open with no way
    // to close it and never left closed with no way to open it without a pointer.
    //
    // A CLICK TOGGLES FROM THE STATE THE POINTER FOUND, not from the state at the moment of the
    // click, and that distinction is the whole of this code rather than a nicety. A mouse click on
    // a hovered control arrives AFTER the hover and the focus have already opened it, so a plain
    // toggle read "open" and closed it; measured in Chrome, clicking the glyph collapsed a control
    // the pointer had just expanded. A tap has the opposite problem: there is no hover, focus lands
    // on the button as part of the tap, and a plain toggle then closed what the tap had opened, so
    // a tap did nothing at all. Reading the state from pointerdown, which precedes both, gets a
    // pointer and a tap right; a keyboard activation fires no pointerdown, so it falls back to the
    // current state, which is the state a reader who tabbed in is looking at.
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

  // Mount the control on `map` and collapse it. No credit is passed in: each tile layer declares
  // its own and the control collects them, which is what keeps the text honest about the provider.
  // The caller creates the map with attributionControl:false, because the control Leaflet mounts by
  // default is the one carrying the flag and the word.
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
