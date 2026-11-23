/* Hover read-out for the Usage page's day-by-day charts.
   The page is complete without this script: every value is already printed in a title and in the
   table twin. It reads only the data attributes the server wrote on the charts, changes only the
   crosshairs, the u-dim class on columns and the #u-tip box, writes text only through textContent,
   makes no request and stores nothing. A missing element makes it do nothing. */
(function () {
  "use strict";

  var ORDER = ["visits", "bundles", "files"];

  /* The read-out lines: the day label, then "name: value" for each readable entry in the order
     given. Values are copied as given and never computed, so the tip cannot disagree with the
     table twin. */
  function formatReadout(label, entries) {
    var lines = [String(label)];
    var list = Array.isArray(entries) ? entries : [];
    for (var k = 0; k < list.length; k++) {
      var e = list[k];
      if (!Array.isArray(e) || typeof e[0] !== "string" || typeof e[1] !== "string") {
        continue;
      }
      lines.push(e[0] + ": " + e[1]);
    }
    return lines;
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { formatReadout: formatReadout };
  }
  if (typeof document === "undefined") {
    return;
  }

  function charts() {
    var found = document.querySelectorAll("svg[data-u-chart]");
    var byKey = {};
    for (var k = 0; k < found.length; k++) {
      byKey[found[k].getAttribute("data-u-chart")] = found[k];
    }
    var out = [];
    for (var j = 0; j < ORDER.length; j++) {
      if (byKey[ORDER[j]]) {
        out.push(byKey[ORDER[j]]);
      }
    }
    return out;
  }

  function hitAt(svg, i) {
    var hits = svg.querySelectorAll(".u-hit");
    for (var k = 0; k < hits.length; k++) {
      if (hits[k].getAttribute("data-i") === i) {
        return hits[k];
      }
    }
    return null;
  }

  function setDim(svg, i) {
    var bars = svg.querySelectorAll(".u-bar");
    for (var k = 0; k < bars.length; k++) {
      if (i !== null && bars[k].getAttribute("data-i") !== i) {
        bars[k].classList.add("u-dim");
      } else {
        bars[k].classList.remove("u-dim");
      }
    }
  }

  function clear(all, tip) {
    for (var k = 0; k < all.length; k++) {
      var cross = all[k].querySelector(".u-cross");
      if (cross) {
        cross.setAttribute("visibility", "hidden");
      }
      setDim(all[k], null);
    }
    tip.hidden = true;
  }

  function fill(tip, lines) {
    while (tip.firstChild) {
      tip.removeChild(tip.firstChild);
    }
    for (var k = 0; k < lines.length; k++) {
      var div = document.createElement("div");
      if (k === 0) {
        var b = document.createElement("b");
        b.textContent = lines[k];
        div.appendChild(b);
      } else {
        div.textContent = lines[k];
      }
      tip.appendChild(div);
    }
  }

  /* The tip sits 14 px from the pointer and flips to stay 8 px inside the viewport. */
  function place(tip, x, y) {
    var w = tip.offsetWidth;
    var h = tip.offsetHeight;
    var left = x + 14;
    var top = y + 14;
    if (left + w > window.innerWidth - 8) {
      left = x - 14 - w;
    }
    if (top + h > window.innerHeight - 8) {
      top = y - 14 - h;
    }
    tip.style.left = Math.max(8, left) + "px";
    tip.style.top = Math.max(8, top) + "px";
  }

  function start() {
    var tip = document.getElementById("u-tip");
    var all = charts();
    if (!tip || !all.length) {
      return;
    }
    function move(ev) {
      var t = ev.target;
      var hit = t && t.closest ? t.closest(".u-hit") : null;
      if (!hit) {
        return;
      }
      var i = hit.getAttribute("data-i");
      var label = hit.getAttribute("data-label");
      if (i === null || label === null) {
        return;
      }
      var entries = [];
      for (var k = 0; k < all.length; k++) {
        var own = hitAt(all[k], i);
        var cross = all[k].querySelector(".u-cross");
        if (own && cross) {
          var cx = own.getAttribute("data-cx");
          if (cx !== null) {
            cross.setAttribute("x1", cx);
            cross.setAttribute("x2", cx);
            cross.setAttribute("visibility", "visible");
          }
        }
        setDim(all[k], i);
        if (own) {
          entries.push([all[k].getAttribute("data-u-name"), own.getAttribute("data-v")]);
        }
      }
      fill(tip, formatReadout(label, entries));
      tip.hidden = false;
      place(tip, ev.clientX, ev.clientY);
    }
    for (var k = 0; k < all.length; k++) {
      all[k].addEventListener("pointermove", move);
      all[k].addEventListener("pointerleave", function () { clear(all, tip); });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
