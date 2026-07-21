"""Server-rendered curator pages (design §3/§4). MIRRORS statuspage.py: stdlib string.Template, no
framework, portal palette, minimal JS — and ZERO inline JS: the strictPages CSP (script-src 'self')
blocks inline script blocks and on*-attribute handlers, so all behaviour rides two external
same-origin scripts (CURATOR_UI_JS delegation for confirms/toggles; SERVE_PANEL_JS for the C40
panel). Every interpolated value is html.escaped — reports derive from submitted bytes and MUST NOT
inject markup into the curator's browser.

Two views: the queue (list of actionable submissions) and the detail view (report bundle, live
checklist, submitter block — curator-only PII, design §2 — the sandboxed preview iframe, and the
action forms, EACH carrying a CSRF hidden field). Plus a login form.

Unlike the public status page, the detail view DOES render the submitter block (name/email/orcid) —
that is the whole point of capturing it (design §2) — but ONLY inside authenticated curator HTML,
never on /gateway/status/*.
"""
from __future__ import annotations

import html
import json as _json
import re
from string import Template

from . import checklist as checklist_mod
from . import states
from .curator_auth import CSRF_FIELD

_PALETTE = {
    "bg": "#13202B", "panel": "#1B2C3A", "ink": "#E8EDF1", "muted": "#8FA3B0",
    "accent": "#E0782F", "ok": "#5BAE6A", "warn": "#D9A23B", "bad": "#A85454",
    # C43-HUB: the blue INFO severity (mockup semantics: red fail / amber warn / blue info). The
    # dark palette had no info hue before the survey-hub treatment needed one; steel blue in the
    # same lightness family as ok/warn/bad — an ADDITION for the third severity, not a repaint.
    "info": "#5B84AE",
}

_STATUS_COLOUR = {
    checklist_mod.PASS: _PALETTE["ok"],
    checklist_mod.WARN: _PALETTE["warn"],
    checklist_mod.FAIL: _PALETTE["bad"],
    checklist_mod.NA: _PALETTE["muted"],
}

_STATE_COLOUR = {
    states.VALIDATED: _PALETTE["ok"],
    states.RETURNED: _PALETTE["warn"],
    states.PUBLISH_FAILED: _PALETTE["bad"],
    states.PUBLISHING: _PALETTE["accent"],
    states.PUBLISHED: _PALETTE["ok"],
    states.REJECTED: _PALETTE["bad"],
}

_HEAD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>$title</title>
<style>
 body{margin:0;background:$bg;color:$ink;font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif}
 .wrap{max-width:960px;margin:0 auto;padding:2rem 1.25rem}
 .wrap.wide{max-width:none} /* per-page opt-in (H2: the keys page) — the default measure stands */
 .dt{font-variant-numeric:tabular-nums;white-space:nowrap} /* short datetimes never wrap (H2) */
 a{color:$accent}
 h1{font-size:1.15rem;font-weight:600;margin:0 0 .25rem}
 h2{font-size:1rem;font-weight:600;margin:0 0 .5rem}
 .sub{color:$muted;font-size:.85rem;margin:0 0 1.5rem}
 .badge{display:inline-block;padding:.15rem .55rem;border-radius:999px;font-weight:600;
   font-size:.75rem;color:$bg}
 .panel{background:$panel;border-radius:8px;padding:1rem 1.25rem;margin:1rem 0}
 table{border-collapse:collapse;width:100%;font-size:.85rem}
 th,td{text-align:left;padding:.4rem .5rem;border-bottom:1px solid #2E4254;vertical-align:top}
 th{color:$muted;font-weight:600}
 pre{white-space:pre-wrap;word-break:break-word;background:$bg;padding:.75rem;border-radius:6px;
   font-size:.8rem;color:$muted}
 iframe{width:100%;height:420px;border:1px solid #2E4254;border-radius:6px;background:#fff}
 iframe.big{height:80vh}
 input,textarea{font:inherit;background:$bg;color:$ink;border:1px solid #2E4254;border-radius:6px;
   padding:.5rem;width:100%;box-sizing:border-box}
 textarea{min-height:4rem}
 button{font:inherit;font-weight:600;border:0;border-radius:6px;padding:.5rem 1rem;cursor:pointer;
   color:$bg}
 .b-ok{background:$ok}.b-warn{background:$warn}.b-bad{background:$bad}.b-accent{background:$accent}
 form.act{display:inline-block;margin:.25rem .5rem .25rem 0}
 .k{color:$muted}
 /* C43 Stage 1 nav shell: a persistent left rail + a context bar on every curator page. Pure CSS
    (style-src allows 'unsafe-inline'); no JS needed for the layout — the drift chip's served-build
    half is filled by the external context-bar script, everything else is server-rendered. */
 .shell{display:flex;min-height:100vh;align-items:stretch}
 .rail{flex:0 0 13rem;background:#152430;border-right:1px solid #2E4254;padding:1.25rem 0}
 .rail .brand{font-weight:600;padding:0 1.25rem 1rem;font-size:.95rem}
 .rail .grp{color:$muted;font-size:.7rem;text-transform:uppercase;letter-spacing:.05em;
   padding:.75rem 1.25rem .25rem}
 .rail a{display:block;padding:.35rem 1.25rem;color:$ink;text-decoration:none;font-size:.9rem;
   border-left:3px solid transparent}
 .rail a:hover{background:#1B2C3A}
 .rail a.on{border-left-color:$accent;background:#1B2C3A;font-weight:600}
 .main{flex:1 1 auto;min-width:0}
 .ctxbar{display:flex;flex-wrap:wrap;align-items:center;gap:.5rem 1rem;
   background:#152430;border-bottom:1px solid #2E4254;padding:.6rem 1.25rem}
 .crumb{font-size:.85rem;color:$muted}
 .crumb a{color:$accent}
 .crumb b{color:$ink;font-weight:600}
 .chip{display:inline-flex;align-items:center;gap:.4rem;background:$bg;border:1px solid #2E4254;
   border-radius:999px;padding:.2rem .7rem;font-size:.75rem;color:$muted}
 .chip code{color:$ink}
 .chip .dot{width:.55rem;height:.55rem;border-radius:50%;background:$muted}
 .chip.current .dot{background:$ok}.chip.behind .dot{background:$warn}
 .ctxbar .spacer{flex:1 1 auto}
 /* one-section-at-a-time metadata TOC (S1-2 Metadata tab) */
 .toc{position:sticky;top:.5rem}
 .toc a{display:block;padding:.25rem .5rem;color:$muted;text-decoration:none;font-size:.85rem;
   border-radius:6px}
 .toc a.on{background:#1B2C3A;color:$ink;font-weight:600}
 .tabs{display:flex;gap:.25rem;border-bottom:1px solid #2E4254;margin:0 0 1rem}
 .tabs a{padding:.5rem .9rem;color:$muted;text-decoration:none;font-size:.9rem;
   border-bottom:2px solid transparent}
 .tabs a.on{color:$ink;border-bottom-color:$accent;font-weight:600}
 .cards{display:flex;flex-wrap:wrap;gap:.75rem;margin:1rem 0}
 .card{flex:1 1 8rem;background:$panel;border-radius:8px;padding:.75rem 1rem}
 .card .n{font-size:1.4rem;font-weight:700}
 .card .l{color:$muted;font-size:.75rem;text-transform:uppercase;letter-spacing:.04em}
 /* C43 S2b-i operations floor (serve-state screen). Server-rendered cards — no JS (the facts come
    from ops-status.json read server-side, the reconcile-status.json seam), so nothing here touches
    the strictPages script-src 'self' CSP. */
 .ops{display:grid;grid-template-columns:repeat(auto-fit,minmax(15rem,1fr));gap:.75rem;margin:.75rem 0}
 .ops .opscard{background:$panel;border-radius:8px;padding:.75rem 1rem}
 .ops h3{font-size:.9rem;font-weight:600;margin:0 0 .5rem;display:flex;align-items:center;
   justify-content:space-between;gap:.5rem}
 .pill{display:inline-block;padding:.05rem .55rem;border-radius:999px;font-size:.7rem;font-weight:700;
   color:$bg;white-space:nowrap}
 .fact{display:flex;justify-content:space-between;gap:1rem;font-size:.83rem;padding:.2rem 0;
   border-bottom:1px solid #22323f}
 .fact:last-child{border-bottom:0}
 .fact .fk{color:$muted}
 .fact .fv{text-align:right;word-break:break-word}
 .opsband{border-radius:6px;padding:.6rem .9rem;margin:.75rem 0;font-size:.88rem}
 .opsnote{color:$muted;font-size:.78rem;margin:.4rem 0 0}
 .stale{color:$warn;font-weight:600}
 /* C43 S2b-ii: the read-only action-audit tail on the serve screen — a bounded, scrollable log. */
 .audittail{max-height:16rem;overflow:auto;font-size:.78rem;line-height:1.5}
 /* C43 FR2-2: Stations tab THREE thirds (owner ruling round 2, 2026-07-11). WIDE = site table
    (col 1) | station facts (col 2) | plots (col 3), all grid-ROW 1, top-aligned. DOM order is
    facts-first then plots then table (the panel-first stacking rule preserved: on a narrow single
    column the facts stack ABOVE the plots ABOVE the table). grid-row:1 on ALL THREE is load-bearing
    (usability incident 2026-07-11): with only grid-COLUMN set, auto-placement cannot move the cursor
    backwards within a row — a DOM-later item wanting an earlier column drops to ROW 2 silently. The
    table column is a minmax so it never truncates its columns (may be slightly narrower than a strict
    third); facts + plots split the rest, and the plots column scrolls its fixed-width SVGs internally
    rather than overflowing the page. Chosen template: minmax(21rem,25rem) | minmax(0,1fr) |
    minmax(0,1fr). The three-thirds needs a wide desktop; below the 1120px stack breakpoint the three
    items collapse to one column (facts, plots, table — DOM order). */
 .stations-split{display:grid;
   grid-template-columns:minmax(21rem,25rem) minmax(0,1fr) minmax(0,1fr);
   gap:1.25rem;align-items:start;margin-top:.5rem}
 .stations-split .st-list{grid-column:1;grid-row:1}   /* site table: left column (DOM-last) */
 .stations-split .st-facts{grid-column:2;grid-row:1}  /* station facts: middle column (DOM-first) */
 .stations-split .st-plots{grid-column:3;grid-row:1;min-width:0;overflow-x:auto} /* plots: right */
 /* C43 FR2-1: submission-detail two-column arrangement (review context left, sandboxed preview
    right). grid-row:1 on both explicitly-placed columns (the auto-placement incident). Collapses to
    one column below 1024px (DOM order: context, then preview). */
 .detail-split{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);
   gap:1.25rem;align-items:start}
 .detail-split .dcol{min-width:0}
 .detail-split .dcol.left{grid-column:1;grid-row:1}
 .detail-split .dcol.right{grid-column:2;grid-row:1}
 /* The list is its OWN scroll region — a fixed-height container with its own scrollbar, NEVER a
    full-page-length table (a >300-station survey must not push the panel off-screen). The filter box
    sits ABOVE the scroll region (outside .st-scroll) so it stays put while the rows scroll. */
 .st-scroll{max-height:70vh;overflow-y:auto;border:1px solid #2E4254;border-radius:6px}
 .st-scroll table{margin:0}
 .st-scroll th{position:sticky;top:0;background:$panel;z-index:1}
 .st-list .st-filter{margin:0 0 .5rem}
 tr.st-row{cursor:pointer}
 tr.st-row:hover{background:#1B2C3A}
 tr.st-row.on{background:#243747}          /* selected row stays visibly highlighted */
 tr.st-row.on td:first-child{box-shadow:inset 3px 0 0 $accent}
 details summary{cursor:pointer;color:$muted;font-size:.8rem;margin:.5rem 0 .25rem}
 /* ---- C43-HUB survey-hub treatment (mockup v4 structure in the dark palette) ---- */
 .slugchip{display:inline-block;background:$panel;border:1px solid #2E4254;border-radius:6px;
   padding:.05rem .5rem;font-size:.72rem;color:$muted;font-weight:600;vertical-align:.15rem;
   font-family:ui-monospace,Consolas,monospace}
 .card .d{color:$muted;font-size:.75rem;margin-top:.15rem}
 .card .n small{font-size:.85rem;color:$muted;font-weight:600}
 .card .n.warn{color:$warn}
 /* Needs-attention severity ROWS: the coloured LEFT BORDER carries the severity hue —
    red fail / amber warn / blue info (the mockup's semantics, dark-palette values). */
 .qa{border-left:3px solid #2E4254;background:$panel;border-radius:0 6px 6px 0;
   padding:.5rem .75rem;margin:.5rem 0;font-size:.85rem;display:flex;gap:.6rem;
   align-items:baseline;flex-wrap:wrap}
 .qa.fail{border-left-color:$bad}
 .qa.warn{border-left-color:$warn}
 .qa.info{border-left-color:$info}
 .qa .sid{font-family:ui-monospace,Consolas,monospace;font-weight:600;white-space:nowrap}
 .qa .why{color:$muted;min-width:0}
 .qa .go{margin-left:auto;white-space:nowrap}
 .note{background:$bg;border:1px solid #2E4254;border-radius:6px;padding:.45rem .7rem;
   font-size:.8rem;color:$muted;margin:.4rem 0 .9rem}
 /* Station drill-down facts (mockup dl.facts) + panel header row */
 dl.facts{display:grid;grid-template-columns:10rem 1fr;gap:.3rem .8rem;margin:0;font-size:.85rem}
 dl.facts dt{color:$muted}
 dl.facts dd{margin:0;min-width:0;word-break:break-word}
 .ph{display:flex;align-items:center;gap:.6rem;flex-wrap:wrap;border-bottom:1px solid #2E4254;
   padding-bottom:.5rem;margin-bottom:.6rem}
 .ph .phid{font-family:ui-monospace,Consolas,monospace;font-weight:700;font-size:1rem}
 .ph .go{margin-left:auto;white-space:nowrap}
 /* Metadata TOC state hints + the display-layer inline field error */
 .toc .state{float:right;color:$muted;font-size:.72rem;margin-left:.5rem}
 .toc .state.issue{color:$bad;font-weight:600}
 .badinput{border-color:$bad !important;background:rgba(168,84,84,.15) !important}
 .fielderr{color:$bad;font-size:.8rem;margin:.25rem 0 0}
 /* ---- C43 Stage 3a collections console (record D5-A; owner-approved preview 2026-07-12). Fully
    server-rendered, READ-ONLY — ZERO JS (the strictPages CSP is script-src 'self'). The bands derive
    from the shipped .opsband warn token; the status chips + member/Declares table are new classes
    that reuse the panel/table idiom. ---- */
 .mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
 .num{font-variant-numeric:tabular-nums;white-space:nowrap}
 tr.rowlink{cursor:pointer}
 tr.rowlink:hover{background:#1B2C3A}
 .statuschip{display:inline-flex;align-items:center;gap:.4rem;border-radius:999px;padding:.1rem .6rem;
   font-size:.72rem;font-weight:600}
 .statuschip .d{width:.5rem;height:.5rem;border-radius:50%}
 .s-active{background:rgba(91,174,106,.15);color:$ok} .s-active .d{background:$ok}
 .s-completed{background:rgba(143,163,176,.15);color:$muted} .s-completed .d{background:$muted}
 .s-archived{background:rgba(143,163,176,.12);color:$muted} .s-archived .d{background:$muted}
 .s-unknown{background:rgba(143,163,176,.1);color:$muted} .s-unknown .d{background:$muted}
 .mixed{color:$warn;font-size:.72rem;white-space:nowrap}
 /* Inconsistency bands: the amber warn seam from the preview (derived from .opsband). */
 .cband{border-radius:8px;padding:.7rem 1rem;margin:.75rem 0;font-size:.85rem;
   background:#3a2f1c;border:1px solid #5a4a24}
 .cband b{color:$warn}
 .cband .why{color:$muted;display:block;margin-top:.25rem}
 .cband .fix{color:$muted;font-size:.8rem;margin-top:.4rem}
 /* Read-only detail: rollup facts as a definition grid + the member/Declares table markers. */
 dl.crollup{display:grid;grid-template-columns:10rem 1fr;gap:.3rem .8rem;margin:0;font-size:.88rem}
 dl.crollup dt{color:$muted}
 dl.crollup dd{margin:0;min-width:0;word-break:break-word}
 .badge-move{color:$warn;font-size:.72rem;white-space:nowrap}
 .badge-ok{color:$muted;font-size:.72rem}
 .divergerow{color:$warn;font-size:.8rem;margin:.3rem 0 0;display:flex;gap:.4rem}
 .divergerow b{color:$warn}
 /* A dashed, muted "next stage" note (the editor lands in 3b) — the preview's .dnote. */
 .dnote{background:$bg;border:1px dashed #2E4254;border-radius:8px;padding:.7rem 1rem;
   margin:1.25rem 0 0;font-size:.82rem;color:$muted}
 .dnote b{color:$ink}
 /* ---- C43 Stage 3b collections EDITOR (record D5-A A3/A5/A6; owner-approved preview views 2/3).
    The fan-out edit form + the two-column membership manager + the batch-diff confirm. The ONLY JS on
    these pages is the candidate-picker filter (external route constant collections.js, CSP-safe —
    textContent DOM, no inline on*). Verbatim class idiom from the approved preview. ---- */
 .formrow{display:grid;grid-template-columns:9rem minmax(0,1fr);gap:.6rem 1rem;align-items:start;
   padding:.5rem 0;border-bottom:1px solid #22323f}
 .formrow:last-of-type{border-bottom:0}
 .formrow>label{color:$muted;font-size:.85rem;padding-top:.5rem}
 .formrow select{font:inherit;background:$bg;color:$ink;border:1px solid #2E4254;border-radius:6px;
   padding:.5rem;width:100%;max-width:40rem}
 .hint{color:$muted;font-size:.78rem;margin-top:.25rem}
 .diverge{color:$warn;font-size:.78rem;margin-top:.3rem;display:flex;gap:.4rem}
 .diverge b{color:$warn}
 .fnote{background:$bg;border-left:3px solid $accent;border-radius:0 6px 6px 0;padding:.6rem .85rem;
   margin:1rem 0 0;font-size:.83rem;color:$ink}
 .fnote b{color:$ink}
 .btnrow{display:flex;gap:.5rem;margin-top:1rem;flex-wrap:wrap}
 button.ghost{background:transparent;color:$ink;border:1px solid #2E4254}
 /* two-column membership manager (A3) */
 .memberwrap{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-top:.5rem}
 .mcol{background:$panel;border-radius:8px;overflow:hidden}
 .ph2{padding:.6rem 1rem;border-bottom:1px solid #2E4254;font-weight:600;font-size:.85rem;
   display:flex;align-items:center;gap:.5rem}
 .ph2 .c{color:$muted;font-weight:400}
 .mfilter{display:block;margin:.6rem 1rem;width:auto}
 .mscroll{max-height:22rem;overflow-y:auto}
 .mscroll table{margin:0} .mscroll td,.mscroll th{padding:.4rem .75rem}
 .mscroll th{position:sticky;top:0;background:$panel;z-index:1}
 .memrow input[type=checkbox]{width:auto;max-width:none}
 .memrow.hide{display:none}
 .badge-none{color:$muted;font-size:.72rem}
 /* per-survey diff + validator rows on the batch-diff confirm (view 3) */
 .commitrow{display:flex;align-items:center;gap:.6rem;padding:.4rem .6rem;
   border-bottom:1px solid #22323f;font-size:.82rem}
 .commitrow:last-child{border-bottom:0}
 .tick{color:$ok;font-weight:700}
 .cross{color:$bad;font-weight:700}
 .verdlist{background:$bg;border:1px solid #2E4254;border-radius:6px;margin-top:.4rem}
 @media (max-width:860px){.memberwrap{grid-template-columns:1fr}}
 /* The three-thirds Stations layout needs a wide desktop (site table + facts + a fixed-width plots
    column). Below 1120px collapse it to ONE column: DOM order is facts-first then plots then table,
    so they stack facts / plots / table with no `order` needed; grid-row returns to auto so the three
    stack (the wide grid-row:1 pins would otherwise force all three into one squeezed row). The
    detail-split collapses at the same 1024px reading-width threshold. */
 @media (max-width:1120px){
   .stations-split{grid-template-columns:1fr}
   .stations-split .st-list,.stations-split .st-facts,.stations-split .st-plots{
     grid-column:1;grid-row:auto}
   .st-scroll{max-height:24rem}}
 @media (max-width:1024px){.detail-split{grid-template-columns:1fr}
   .detail-split .dcol.left,.detail-split .dcol.right{grid-column:1;grid-row:auto}}
 @media (max-width:720px){.shell{display:block}.rail{flex-basis:auto;border-right:0;
   border-bottom:1px solid #2E4254}}
</style></head>
<body>
"""

# Every curator page loads the shared UI script (delegated data-confirm / data-toggle-big handlers)
# as an EXTERNAL same-origin script — the strictPages CSP (script-src 'self') silently blocks inline
# script blocks AND on*-attribute handlers on every /gateway/* page, so inline handlers are dead code
# that only fails in production (three shipped that way and never ran; found 2026-07-08).
_TAIL = '<script src="/gateway/curator/ui.js" defer></script></body></html>'


# Shared curator-page behaviours, DELEGATED so per-element handlers never need inlining again:
#   * a <form data-confirm="message"> gets an accidental-click confirm on submit;
#   * a <button data-toggle-big="elementId"> toggles the .big class on that element.
# Served by GET /gateway/curator/ui.js — deliberately UNGATED, the login page loads it pre-session
# (see app.handle_curator_ui_js).
CURATOR_UI_JS = """
(function () {
  document.addEventListener('submit', function (ev) {
    var f = ev.target;
    if (f && f.getAttribute && f.getAttribute('data-confirm')) {
      if (!window.confirm(f.getAttribute('data-confirm'))) ev.preventDefault();
    }
  });
  document.addEventListener('click', function (ev) {
    // closest(), not ev.target directly: a click on a CHILD of the button (a future <span>/icon)
    // reports the child as target and would silently miss the attribute (review C1).
    var t = ev.target && ev.target.closest && ev.target.closest('[data-toggle-big]');
    if (t) {
      var el = document.getElementById(t.getAttribute('data-toggle-big'));
      if (el) el.classList.toggle('big');
    }
  });
})();
"""


# The metadata-editor's repeatable-row behaviour, DELEGATED (no inline handlers — the strictPages
# CSP kills them). Served external at GET /gateway/curator/editor.js. Add-row clones the section's
# <template> (its field names carry a ___N___ index placeholder) with a fresh unique index and
# appends it; remove-row drops the nearest row. DEGRADES: without this script the server already
# renders existing rows + spare blank rows, so a curator can still add entries. Every value the JS
# touches is set via name/textContent, never innerHTML from user data.
EDITOR_UI_JS = """
(function () {
  var counters = {};
  function nextIndex(section, rowsHost) {
    // Start above the highest server-rendered index so a new row never collides with an existing one.
    if (counters[section] == null) {
      var max = -1;
      var pfx = 'l_' + section + '_';
      rowsHost.querySelectorAll('[name^="' + pfx + '"]').forEach(function (el) {
        var n = parseInt(el.getAttribute('name').slice(pfx.length).split('_')[0], 10);
        if (!isNaN(n) && n > max) max = n;
      });
      counters[section] = max + 1;
    }
    return counters[section]++;
  }
  document.addEventListener('click', function (ev) {
    var add = ev.target && ev.target.closest && ev.target.closest('[data-editor-add-row]');
    if (add) {
      var section = add.getAttribute('data-editor-add-row');
      var tpl = document.querySelector('[data-editor-template="' + section + '"]');
      var rowsHost = document.querySelector('[data-editor-rows="' + section + '"]');
      if (!tpl || !rowsHost) return;
      var idx = nextIndex(section, rowsHost);
      var frag = tpl.innerHTML.split('ROWIDX').join(String(idx));
      var wrap = document.createElement('div');
      wrap.innerHTML = frag;
      var row = wrap.firstElementChild;
      if (row) rowsHost.appendChild(row);
      return;
    }
    var rem = ev.target && ev.target.closest && ev.target.closest('[data-editor-remove-row]');
    if (rem) {
      var r = rem.closest('[data-editor-row]');
      if (r) r.parentNode.removeChild(r);
    }
  });
})();
"""


# The context-bar drift chip's served-build half: fetch /data/build.json SAME-ORIGIN (Caddy serves
# /data/* from the built current/) and fill the served build id, then compare its source_commit
# against the server-rendered published HEAD to flip the chip current|behind. RAW JS served by
# GET /gateway/curator/context-bar.js — inline delivery is dead under the strictPages script-src
# 'self' policy (same reason as serve-state.js/ui.js). Every value goes in via textContent (never
# innerHTML), so a build-report-derived string cannot inject markup. Prefix-tolerant commit compare
# (7-char short vs 8-char HEAD of the same commit is NOT a mismatch), matching SERVE_PANEL_JS.
CONTEXT_BAR_JS = """
(function () {
  var chip = document.getElementById('drift-chip');
  if (!chip) return;
  var publishedHead = chip.getAttribute('data-published-head') || '';
  var buildEl = document.getElementById('drift-build');
  var servingEl = document.getElementById('drift-serving');
  // S2a-5 DISPLAY shortener (mirrors gateway/builddisplay.py — the authoritative, pinned spec):
  // "<engine>-<source>-<iso>" -> "<source short> · HH:MM UTC"; a shape this does not recognise falls
  // back to the id VERBATIM (never hide information). The FULL id rides the title attribute (hover).
  function shortBuildId(id) {
    if (!id) return '';
    var s = String(id);
    var m = s.match(/^([0-9a-fA-F]+|unknown)-([0-9a-fA-F]+|unknown)-(\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}[0-9.]*(?:Z|[+-]\\d{2}:?\\d{2})?)$/);
    if (!m) return s;
    var source = m[2];
    var short = (source === 'unknown') ? 'unknown' : source.slice(0, 7);
    var hhmm = m[3].slice(11, 16);
    return short + ' \\u00b7 ' + hhmm + ' UTC';
  }
  fetch('/data/build.json', {credentials: 'omit', cache: 'no-store'}).then(function (r) {
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }).then(function (b) {
    if (buildEl) {
      var full = b.build_id || '';
      buildEl.textContent = full ? shortBuildId(full) : '(unknown)';
      if (full) buildEl.setAttribute('title', full);   // full id on hover (DOM property, not markup)
    }
    var served = b.source_commit || '';
    if (!publishedHead || !served) return;  // can't judge currency without both sides
    var current = (publishedHead.indexOf(served) === 0 || served.indexOf(publishedHead) === 0);
    chip.classList.add(current ? 'current' : 'behind');
    var verdict = document.createElement('span');
    verdict.textContent = current ? '· current' : '· behind';
    verdict.className = 'k';
    if (servingEl) servingEl.appendChild(verdict);
  }).catch(function () {
    if (buildEl) buildEl.textContent = '(no served build)';
  });
})();
"""


# The survey hub's browser-side script (C43 Stage 1 S1-2; REBUILT by C43-HUB to the approved mockup's
# information design). Jobs, all degradable:
#   1. HUB HEADER + TAB STRIP (every tab) — fill the orientation line's station counts
#      ([data-hub-counts]: 'N stations published, M serving') and the Stations tab chip
#      ([data-stations-chip]: 'd dropped · f flagged', hidden at 0/0) from /data/build_report.json.
#   2. OVERVIEW & QA tab — fetch /data/build_report.json SAME-ORIGIN, filter to this survey
#      (#survey-qa[data-survey-slug]), and render the mockup's four health cards (Serving/published,
#      QA flags, Frame, Last build — the build-id card is REMOVED: that fact lives in the drift chip
#      and the serve screen), the "Needs attention" SEVERITY ROWS (red fail / amber warn / blue info;
#      terse diagnosis with the full gate text in a title attr; same-class prefix runs >=3 CLUSTERED
#      onto one row), the refused-package note ONCE, and the conditioning summary table.
#   3. METADATA tab — enhance the sticky TOC to show ONE section at a time (#hub-toc / .hub-section).
#      Without this script the server renders every section stacked and fully functional (graceful).
#
# DATA HONESTY (owner rulings 2026-07-11, contract C43-HUB):
#   * QA flags = the sum of counts over the survey.frame CONVENTION-WARN entries ("served with note"
#     stations) — ONE definition (qaFlagCount) shared by the H2 card and the H1 tab chip.
#   * The Frame card headline derives from the frame notes' DE-ROTATION entries ONLY (convention/
#     quadrant warns are QA flags, not frame state); the sub-line uses the record's own vocabulary
#     ("declared-zero reference" — never "geomagnetic", which the engine deliberately never asserts).
#   * The citation-author info row renders ONLY when the server stamped data-citation-email on the
#     scaffold (derived server-side from the SAME helper the Metadata tab's inline error uses) —
#     never inferred by matching warning strings (the old /citation|author|email/ branch is deleted).
#   * Warnings strings that MIRROR structured sources (the per-drop 'station X SKIPPED …' echo and
#     the 'convention: …' aggregation echo) are filtered — the structured rows render them properly.
#
# ANY logic beyond DOM wiring lives in NAMED, DOM-FREE functions (clusterWarnings, attentionItems,
# attentionPlan, cardsPlan, hubCounts, qaFlagCount, frameCardFacts, terseDrop, terseWarn,
# stationsChipText, attentionHref, conditioningScope, …) driven executable by the Node harness
# (gateway/tests/test_c43_hub_js_parity.py) with a build_report the REAL ENGINE produced.
# RAW JS served by GET /gateway/curator/survey-hub.js — inline is dead under script-src 'self'. Every
# value goes in via textContent (never innerHTML) so a build-report string cannot inject markup.
SURVEY_HUB_JS = r"""
(function () {
  // ---- Metadata TOC: one section visible at a time (progressive enhancement) ----
  var toc = document.getElementById('hub-toc');
  var host = document.getElementById('hub-sections');
  if (toc && host) {
    var forms = host.querySelectorAll('.hub-section');
    var links = toc.querySelectorAll('[data-hub-section]');
    function show(key) {
      forms.forEach(function (f) {
        f.style.display = (f.getAttribute('data-hub-section-form') === key) ? '' : 'none';
      });
      links.forEach(function (a) {
        if (a.getAttribute('data-hub-section') === key) a.classList.add('on');
        else a.classList.remove('on');
      });
    }
    links.forEach(function (a) {
      a.addEventListener('click', function (ev) {
        ev.preventDefault();
        show(a.getAttribute('data-hub-section'));
      });
    });
    var first = links[0] && links[0].getAttribute('data-hub-section');
    var onlink = toc.querySelector('[data-hub-section].on');
    show(onlink ? onlink.getAttribute('data-hub-section') : first);
  }

  // ================================================================================================
  // C43-HUB pure helpers — DOM-FREE by design: the Node harness (test_c43_hub_js_parity.py) drives
  // these exact functions with a build_report the REAL ENGINE produced. No DOM, no fetch, no state.
  // ================================================================================================

  // A convention-WARN frame note (build_portal Gate 2 WARN class): 'convention: arg(Zxy|Zyx)
  // mid-band median X deg is outside its expected quadrant while the other off-diagonal is
  // in-quadrant — …'. THE one QA-flag definition (owner ruling Q2).
  function isQuadrantWarnNote(note) {
    return typeof note === 'string' && note.indexOf('convention: ') === 0 &&
           note.indexOf('outside its expected quadrant') >= 0;
  }

  // QA flags = sum of carrier counts over convention-warn frame entries ("served with note").
  // Shared by the H2 QA-flags card AND the H1 Stations-chip flagged number (pinned equal).
  function qaFlagCount(frameEntries) {
    var n = 0;
    (frameEntries || []).forEach(function (e) {
      if (e && isQuadrantWarnNote(e.note)) n += (e.count || 0);
    });
    return n;
  }

  // published = built + dropped (the refused stations stay in the package); serving = built.
  function hubCounts(survey) {
    var built = (survey && survey.stations_built != null) ? survey.stations_built : null;
    var dropped = (survey && survey.stations_dropped) ? survey.stations_dropped.length : 0;
    return {
      serving: built,
      published: built == null ? null : built + dropped,
      dropped: dropped,
      flagged: qaFlagCount(survey && survey.frame)
    };
  }

  // The Stations tab chip: 'd dropped · f flagged' — null (chip stays hidden) at 0/0.
  function stationsChipText(counts) {
    if (!counts || (!counts.dropped && !counts.flagged)) return null;
    return counts.dropped + ' dropped · ' + counts.flagged + ' flagged';
  }

  // Frame card (owner ruling Q1): headline from DE-ROTATION notes ONLY — no de-rotation notes =>
  // 'as-stored', otherwise 'N de-rotated' (N = union of enumerated carriers; count lower bound when
  // a note's carriers are not enumerated). Convention/insufficient notes count as NEITHER. Sub-line
  // in the record's own vocabulary: R3 'declared acquisition frame' notes when present, else
  // 'declared-zero reference'. The word 'geomagnetic' appears NOWHERE (C25's deliberate refusal).
  function frameCardFacts(frameEntries) {
    var ids = {}, exact = true, floor = 0, declared = false;
    (frameEntries || []).forEach(function (e) {
      if (!e || typeof e.note !== 'string' || e.note.indexOf('frame: ') !== 0) return;
      if (e.note.indexOf('de-rotated') >= 0) {
        if (e.stations && e.stations.length) {
          e.stations.forEach(function (s) { ids[String(s)] = true; });
        } else {
          exact = false;
          if ((e.count || 0) > floor) floor = e.count;
        }
      }
      if (e.note.indexOf('declared acquisition frame') >= 0) declared = true;
    });
    var uniq = Object.keys(ids).length;
    var derot = exact ? uniq : Math.max(uniq, floor);
    return {
      headline: derot ? (derot + ' de-rotated') : 'as-stored',
      sub: declared ? 'declared acquisition frame recorded' : 'declared-zero reference'
    };
  }

  function signedDegStr(v) {
    // '+43.6°' / '-73.5°' from a NUMERIC STRING as the engine printed it (no re-rounding).
    return (parseFloat(v) >= 0 ? '+' : '') + v + '°';
  }

  // Terse diagnosis for a REFUSAL ({station, reason} from stations_dropped; reason is
  // '[<gate>] <detail>'). Returns {cls, terse}; the FULL reason always rides the row title attr,
  // and an unrecognised shape falls back VERBATIM (never hide information — builddisplay posture).
  function terseDrop(reason) {
    var s = String(reason || '');
    var m = /^\[([^\]]+)\]\s*([\s\S]*)$/.exec(s);
    var gate = m ? m[1] : 'gate';
    var detail = m ? m[2] : s;
    if (/^BOTH off-diagonal/.test(detail)) {
      var dash = detail.indexOf(' — ');
      var tail = dash >= 0 ? detail.slice(dash + 3) : '';
      var sigm = /^(.*?signature)/.exec(tail);
      var sig = sigm ? sigm[1] : 'coherent out-of-quadrant phases';
      var xy = /arg Zxy=(-?\d+(?:\.\d+)?) deg/.exec(detail);
      var yx = /arg Zyx=(-?\d+(?:\.\d+)?) deg/.exec(detail);
      return { cls: gate + ':' + sig,
               terse: 'refused — both off-diagonals out of quadrant; ' + sig
                    + (xy && yx ? ' (Zxy ' + signedDegStr(xy[1]) + ', Zyx ' + signedDegStr(yx[1]) + ')' : '') };
    }
    var first = detail.split(/;|\. /)[0];
    return { cls: gate, terse: 'refused — ' + (first || detail) };
  }

  // Terse diagnosis + class for a convention-WARN frame note. cls carries the component so
  // clustering groups SAME-CLASS warns only.
  function terseWarn(note) {
    var m = /^convention: arg\(Z(xy|yx)\) mid-band median (-?\d+(?:\.\d+)?) deg/.exec(String(note || ''));
    if (!m) return { cls: 'frame-note', terse: String(note || '') };
    var comp = 'Z' + m[1];
    var other = m[1] === 'xy' ? 'Zyx' : 'Zxy';
    return { cls: 'quadrant:' + comp,
             terse: 'arg(' + comp + ') median ' + signedDegStr(m[2]) + ' out of expected quadrant; '
                  + other + ' in-quadrant — served with note' };
  }

  // The flat item list feeding clusterWarnings: refusals (fail) from stations_dropped, quadrant
  // warns (warn) EXPANDED per enumerated carrier station from survey.frame, and residual survey
  // warnings (warn, unclustered). Warnings strings that MIRROR structured sources are filtered:
  // the per-drop echo ('station X SKIPPED by convention gate: …') and the aggregated convention
  // echo ('convention: …') — the structured rows above render those facts properly.
  function attentionItems(survey) {
    var items = [];
    ((survey && survey.stations_dropped) || []).forEach(function (d) {
      var t = terseDrop(d && d.reason);
      items.push({ kind: 'fail', station: String((d && d.station) || ''), cls: t.cls,
                   terse: t.terse, full: String((d && d.reason) || ''), link: 'removal' });
    });
    ((survey && survey.frame) || []).forEach(function (e) {
      if (!e || !isQuadrantWarnNote(e.note)) return;
      var t = terseWarn(e.note);
      if (e.stations && e.stations.length) {
        e.stations.forEach(function (sid) {
          items.push({ kind: 'warn', station: String(sid), cls: t.cls, terse: t.terse,
                       full: String(e.note), link: 'stations' });
        });
      } else {
        // Carriers not enumerated (large set): one aggregate row, never per-station rows.
        items.push({ kind: 'warn', station: (e.count || 0) + ' stations', cls: t.cls,
                     terse: t.terse, full: String(e.note), link: 'stations', noCluster: true });
      }
    });
    ((survey && survey.warnings) || []).forEach(function (w) {
      var s = String(w);
      if (/^station .* SKIPPED by convention gate: /.test(s)) return;  // mirrors stations_dropped
      if (/^convention: /.test(s)) return;                             // mirrors frame entries
      items.push({ kind: 'warn', station: 'survey', cls: 'survey-warning', terse: s, full: s,
                   link: null, noCluster: true });
    });
    return items;
  }

  // The alphabetic prefix of a station id (trailing digit run stripped): 'CP1L02' -> 'CP1L'.
  // null when there is nothing to cluster on (no trailing digits, or an all-digit id).
  function idPrefix(id) {
    var m = /^(.*[^0-9])(\d+)$/.exec(String(id || ''));
    return m ? m[1] : null;
  }

  // Numeric-aware id ordering (gate F3): a lexicographic sort renders an UNPADDED run's range
  // label backwards ('L10 … L3'). Ids sharing a prefix compare by the trailing digit run AS AN
  // INTEGER; anything else falls back to plain string order. Zero-padded corpora order
  // identically either way.
  function idOrder(a, b) {
    var sa = String(a), sb = String(b);
    var ma = /^(.*?)(\d+)$/.exec(sa);
    var mb = /^(.*?)(\d+)$/.exec(sb);
    if (ma && mb && ma[1] === mb[1]) return Number(ma[2]) - Number(mb[2]);
    return sa < sb ? -1 : (sa > sb ? 1 : 0);
  }

  // One-line class summary for a clustered row, derived from the item's CLASS (never a guess).
  function classSummary(it) {
    if (it.kind === 'fail') {
      var i = it.cls.indexOf(':');
      var sig = i >= 0 ? it.cls.slice(i + 1) : 'coherent convention violations';
      return 'refused — ' + sig + ' (details per station)';
    }
    var m = /^quadrant:(Zxy|Zyx)$/.exec(it.cls);
    if (m) return 'one off-diagonal (' + m[1] + ') out of expected quadrant — served with note';
    return it.terse;
  }

  // CLUSTERING (contract H2): items of the SAME class whose station ids share an alphabetic prefix
  // run, >=3 members, collapse to ONE row — 'CP1L02 … CP1L13' (or 'A · B · C' at exactly 3) +
  // '<n> stations — <class summary>; clustered on one line', full notes in the title. Groups of <3
  // and unclusterable items render individually. Row order follows first appearance.
  function clusterWarnings(items) {
    var seq = [], groups = {};
    (items || []).forEach(function (it) {
      var pfx = it.noCluster ? null : idPrefix(it.station);
      var key = pfx ? (it.kind + '|' + it.cls + '|' + pfx) : null;
      if (!key) { seq.push({ single: it }); return; }
      if (!groups[key]) { groups[key] = []; seq.push({ groupKey: key }); }
      groups[key].push(it);
    });
    var out = [];
    seq.forEach(function (s) {
      if (s.single) {
        out.push({ kind: s.single.kind, sid: s.single.station, text: s.single.terse,
                   title: s.single.full, link: s.single.link, n: 1, ids: [s.single.station] });
        return;
      }
      var g = groups[s.groupKey];
      if (!g) return;
      delete groups[s.groupKey];
      if (g.length < 3) {
        g.forEach(function (it) {
          out.push({ kind: it.kind, sid: it.station, text: it.terse, title: it.full,
                     link: it.link, n: 1, ids: [it.station] });
        });
        return;
      }
      var ids = g.map(function (it) { return it.station; }).sort(idOrder);   // F3: numeric-aware
      var sid = g.length === 3 ? ids.join(' · ')
                               : ids[0] + ' … ' + ids[ids.length - 1];
      out.push({ kind: g[0].kind, sid: sid,
                 text: g.length + ' stations — ' + classSummary(g[0]) + '; clustered on one line',
                 title: g.map(function (it) { return it.station + ': ' + it.full; }).join('\n'),
                 link: g[0].link, n: g.length, ids: ids });
    });
    return out;
  }

  // The refused-package boilerplate — rendered ONCE under the refusal rows (contract H2), never
  // repeated per row (the pin fails if this marker enters a per-row loop).
  var REFUSED_NOTE = 'Refused stations stay in the published package — they are withheld from '
                   + 'serving only. Fix is custodian-side re-export; each row carries the diagnosis.';

  function truncEmail(v) {
    var s = String(v || '');
    var at = s.indexOf('@');
    return at > 0 ? s.slice(0, at + 1) + '…' : s;
  }
  function metaInfoText(email, built) {
    return 'citation author is an email address (' + truncEmail(email) + ') — baked into '
         + (built != null ? 'all ' + built + ' served' : 'every served') + ' station XML';
  }

  // The FULL render plan for Needs attention: fail rows, the package note ONCE (only when there
  // are refusals), then warn rows, then the metadata info row (only when the server stamped the
  // citation-email attribute). Pure: [{row}| {note}] entries, in render order.
  function attentionPlan(survey, citationEmail) {
    var rows = clusterWarnings(attentionItems(survey));
    var plan = [];
    rows.forEach(function (r) { if (r.kind === 'fail') plan.push({ row: r }); });
    if (plan.length) plan.push({ note: REFUSED_NOTE });
    rows.forEach(function (r) { if (r.kind !== 'fail') plan.push({ row: r }); });
    if (citationEmail) {
      plan.push({ row: { kind: 'info', sid: 'metadata',
                         text: metaInfoText(citationEmail, survey && survey.stations_built),
                         title: null, link: 'metadata', n: 1, ids: [] } });
    }
    return plan;
  }

  // Row action-link targets (contract H2): refusals -> the station-removal list; quadrant warns ->
  // the Stations tab; metadata-class issues -> the owning Metadata section.
  function attentionHref(link, slug2) {
    if (link === 'removal') return '/gateway/curator/edit/' + encodeURIComponent(slug2) + '/stations';
    if (link === 'stations') return '/gateway/curator/survey/' + encodeURIComponent(slug2) + '?tab=stations';
    if (link === 'metadata') return '/gateway/curator/survey/' + encodeURIComponent(slug2) + '?tab=metadata';
    return null;
  }
  function attentionLinkText(row) {
    if (row.link === 'removal') return 'inspect';
    if (row.link === 'metadata') return 'fix in Metadata';
    if (row.link === 'stations') return row.n > 1 ? 'review stations' : 'review station';
    return null;
  }

  function durationText(d) {
    if (d == null) return '-';
    var n = Number(d);
    if (!isFinite(n)) return '-';
    return (n >= 10 ? String(Math.round(n)) : n.toFixed(1)) + ' s';
  }
  function cacheWord(cache) {
    var h = (cache && cache.hits) || 0, m = (cache && cache.misses) || 0;
    if (m > 0 && h === 0) return 'cold';
    if (h > 0 && m === 0) return 'warm';
    if (h > 0 && m > 0) return 'mixed';
    return '';
  }

  // The mockup's FOUR cards — Serving/published, QA flags, Frame, Last build. The build-id card is
  // deliberately ABSENT (that fact lives in the drift chip + the serve screen); the pin asserts it.
  function cardsPlan(survey, rep) {
    var counts = hubCounts(survey);
    var fc = frameCardFacts(survey && survey.frame);
    var cache = (survey && survey.cache) || {};
    var buildSub = [cacheWord(cache),
                    (rep && rep.engine_commit) ? 'engine ' + rep.engine_commit : '']
                   .filter(function (x) { return !!x; }).join(' · ');
    return [
      { label: 'Serving / published',
        value: counts.serving == null ? '-' : String(counts.serving),
        small: counts.published == null ? '' : ' / ' + counts.published,
        sub: counts.dropped ? counts.dropped + ' refused by convention gate'
                            : 'all published stations serving',
        tone: '' },
      { label: 'QA flags', value: String(counts.flagged), small: '',
        sub: counts.flagged ? 'served with note — one off-diagonal out of quadrant'
                            : 'no quadrant warnings in this build',
        tone: counts.flagged ? 'warn' : '' },
      { label: 'Frame', value: fc.headline, small: '', sub: fc.sub, tone: '' },
      { label: 'Last build', value: durationText(survey && survey.duration_seconds), small: '',
        sub: buildSub, tone: '' }
    ];
  }

  // Conditioning scope cell: 'all 147' when every served station carries the note; the enumerated
  // carrier set when short; 'N (all except …)' for the complement form; the bare count otherwise.
  function conditioningScope(entry, built) {
    if (!entry) return '';
    if (built != null && entry.count === built) return 'all ' + built;
    if (entry.stations && entry.stations.length) return entry.stations.join(', ');
    if (entry.except && entry.except.length) {
      return entry.count + ' (all except ' + entry.except.join(', ') + ')';
    }
    return String(entry.count);
  }

  // ================================================================================================
  // DOM wiring (everything below is presentation over the pure plan builders above)
  // ================================================================================================
  function el(tag, text, cls) {
    var e = document.createElement(tag);
    if (text != null) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  }
  function fetchJson(url) {
    return fetch(url, {credentials: 'omit', cache: 'no-store'}).then(function (r) {
      if (r.status === 404) return {__missing: true};
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }

  // ONE build_report fetch shared by the header counts, the tab chip, and the overview render.
  var _repPromise = null;
  function buildReport() {
    if (!_repPromise) {
      _repPromise = fetchJson('/data/build_report.json').catch(function () { return {__err: true}; });
    }
    return _repPromise;
  }
  function surveyFromReport(rep, slug2) {
    if (!rep || rep.__missing || rep.__err) return null;
    return (rep.surveys || {})[slug2] || null;
  }

  // ---- header counts + Stations tab chip (every hub tab) ----
  var tabsEl = document.querySelector('[data-hub-tabs]');
  var hubSlug = tabsEl ? (tabsEl.getAttribute('data-survey-slug') || '') : '';
  var chipEl = document.querySelector('[data-stations-chip]');
  var countsEl = document.querySelector('[data-hub-counts]');
  if (hubSlug && (chipEl || countsEl)) {
    buildReport().then(function (rep) {
      var survey = surveyFromReport(rep, hubSlug);
      if (!survey) return;
      var counts = hubCounts(survey);
      if (chipEl) {
        var t = stationsChipText(counts);
        if (t) { chipEl.textContent = t; chipEl.hidden = false; }
      }
      if (countsEl && counts.published != null) {
        countsEl.textContent = '';
        countsEl.appendChild(document.createTextNode(
          ' · ' + counts.published + ' stations published, '));
        countsEl.appendChild(el('b', counts.serving + ' serving'));
        countsEl.hidden = false;
      }
    });
  }

  // ---- Overview & QA: browser-side from the served /data corpus ----
  var qa = document.getElementById('survey-qa');
  if (!qa) return;
  var slug = qa.getAttribute('data-survey-slug') || '';
  var citationEmail = qa.getAttribute('data-citation-email') || '';

  function attentionRowEl(row) {
    var div = el('div', null, 'qa ' + row.kind);
    div.appendChild(el('span', row.sid, 'sid'));
    var why = el('span', row.text, 'why');
    if (row.title && row.title !== row.text) why.setAttribute('title', row.title);
    div.appendChild(why);
    var href = attentionHref(row.link, slug);
    if (href) {
      var go = el('span', null, 'go');
      var a = el('a', attentionLinkText(row));
      a.href = href;
      go.appendChild(a);
      div.appendChild(go);
    }
    return div;
  }

  buildReport().then(function (rep) {
    var cards = document.getElementById('qa-cards');
    var attention = document.getElementById('qa-attention');
    var cond = document.getElementById('qa-conditioning');
    cards.textContent = ''; attention.textContent = ''; cond.textContent = '';

    if (!rep || rep.__missing || rep.__err) {
      cards.appendChild(el('p', 'No build report available yet (/data/build_report.json).', 'sub'));
      return;
    }
    var survey = surveyFromReport(rep, slug);
    if (!survey) {
      cards.appendChild(el('p', 'This survey is not in the current build report — it may not '
        + 'have been built into the served corpus yet.', 'sub'));
      return;
    }

    // The four cards (label / value+small / sub — the mockup's card anatomy).
    cardsPlan(survey, rep).forEach(function (c) {
      var box = el('div', null, 'card');
      box.appendChild(el('div', c.label, 'l'));
      var v = el('div', c.value, c.tone ? 'n ' + c.tone : 'n');
      if (c.small) v.appendChild(el('small', c.small));
      box.appendChild(v);
      if (c.sub) box.appendChild(el('div', c.sub, 'd'));
      cards.appendChild(box);
    });

    // Needs attention: severity rows from the pure plan (fail rows, ONE package note, warn rows,
    // the metadata info row when stamped).
    var plan = attentionPlan(survey, citationEmail);
    if (!plan.length) {
      attention.appendChild(el('p', 'Nothing needs attention — no refused stations or QA '
        + 'warnings in the current build.', 'sub'));
    } else {
      plan.forEach(function (step) {
        if (step.note) attention.appendChild(el('div', step.note, 'note'));
        else attention.appendChild(attentionRowEl(step.row));
      });
    }

    // Conditioning summary (the mockup's tight two-column table).
    var conditioning = survey.conditioning || [];
    if (!conditioning.length) {
      cond.appendChild(el('p', 'No conditioning notes recorded for this survey.', 'sub'));
    } else {
      var tbl = el('table');
      var head = el('tr');
      ['Note', 'Stations'].forEach(function (h) { head.appendChild(el('th', h)); });
      tbl.appendChild(head);
      conditioning.forEach(function (c) {
        var tr = el('tr');
        tr.appendChild(el('td', c.note));
        tr.appendChild(el('td', conditioningScope(c, survey.stations_built)));
        tbl.appendChild(tr);
      });
      cond.appendChild(tbl);
    }
  });
})();
"""


# The C43 Stage-2a Stations tab browser-side script. ALL data is fetched SAME-ORIGIN from the served
# /data corpus (catalogue.json / sci.json / tf.json / surveys.json + build.json) — the serve-panel
# pattern, ZERO new gateway privileges (the gateway has no site-data mount). The catalogue/sci/tf
# arrays are INDEX-ALIGNED (station i is catalogue[i]/sci[i]/tf[i] — the engine appends them in one
# pass); we filter to this survey's rows by ausmt_id prefix ('au.<slug>.', surveyRows below) — the
# catalogue `survey` column carries the display LABEL, never the slug (hotfix H1, 2026-07-11).
#
# CSP + XSS discipline (the same rules SURVEY_HUB_JS follows, extended to SVG): served external under
# script-src 'self'; EVERY value goes in via textContent or a DOM property, NEVER innerHTML with data;
# every SVG node is built with createElementNS (never an innerHTML string), so a build-report/catalogue
# string can never inject markup — coordinates are computed numbers, but the discipline is uniform so a
# source sweep can assert no innerHTML-with-data path exists.
#
# THE PHASE FACT (mirrors gateway/phaseqc.py — the authoritative, pinned server-side spec; the
# EXECUTABLE Node parity pin runs these very functions against phaseqc, fix-round F3):
#   tf.json t[4] = phs_yx_adj is stored with a +180 presentation shift (engine _edi_tf.norm_phase). The
#   workbench SUBTRACTS 180 and re-wraps (FLOORED modulo — JS's truncated % diverges on negatives,
#   fix-round F1) to recover TRUE φyx, plots it on a FULL ±180 axis with the Q3 (−180…−90) band shaded.
#   φxy (t[3]) is stored true, plotted 0…90 with the Q1 band shaded. ENGINE-GATE ALIGNED (fix-round F4,
#   _conventions.py Gate 2): a point draws RED only when outside its band by MORE than
#   QUADRANT_SLACK_DEG (10°, cross-import-pinned equal to the engine constant); the verdict strip
#   beneath each phase plot is the MEDIAN of classified points vs band+slack (yx median on the
#   seam-mapped (−360,0] axis) and carries the median value.
STATIONS_JS = r"""
(function () {
  var host = document.getElementById('survey-stations');
  if (!host) return;
  var slug = host.getAttribute('data-survey-slug') || '';
  var publishedHead = host.getAttribute('data-published-head') || '';
  // C42/C43 Stage-4: the boot-loaded coordinate-access policy map (ausmt_id -> 'generalised' |
  // 'withheld'), read same-origin from the OPTIONAL /data/coord_policy.json — the SAME boot artifact
  // the portal drawer reads (A1). It lists ONLY non-exact stations and carries the ENGINE-RESOLVED
  // effective policy (override-or-default already applied at the mask seam), never a coordinate, so
  // 'absent => exact' is the honest effective policy with NO client-side precision re-derivation
  // (forbidden by the record). Absent file (all-exact corpus) => empty => every station reads 'exact'.
  var COORD_POLICY = {};
  var SVGNS = 'http://www.w3.org/2000/svg';

  // ---- column maps (single-sourced positional contract; mirror portal/src/contract.js) ----
  var C = { id: 0, survey: 1, lat: 2, lon: 3, pmin: 4, pmax: 5, nper: 6, comps: 7, type: 8,
            region: 9, file: 10, coord_flag: 11, ausmt_id: 12, edi_available: 13, sha256: 14 };
  var SC = { q: 0, qb: 1, rr: 2, sw: 3, alg: 4, dim: 5, p3d: 6, gd: 7, ellip: 8, skew: 9, mre: 10 };
  var T = { periods: 0, rho_xy: 1, rho_yx: 2, phs_xy: 3, phs_yx_adj: 4, tip_mag: 5, pt_min: 6,
            pt_max: 7, pt_az: 8, pt_beta: 9, rho_xy_err: 10, rho_yx_err: 11, phs_xy_err: 12,
            phs_yx_err: 13, tzx_re: 14, tzx_im: 15, tzy_re: 16, tzy_im: 17 };

  // ---- phase-quadrant classification (mirrors gateway/phaseqc.py EXACTLY — the pinned spec; the
  // executable Node parity pin runs THESE functions against phaseqc over a boundary sweep) ----
  var YX_SHIFT = 180.0, Q1_LO = 0.0, Q1_HI = 90.0, Q3_LO = -180.0, Q3_HI = -90.0, SLACK = 10.0;
  // FLOORED modulo (fix-round F1): JS % is TRUNCATED (keeps the dividend's sign) and does NOT match
  // Python's floored % on negatives — the truncated version sent every negative stored t[4] (exactly
  // the wrong-convention stations this feature exists to catch) off-canvas and flipped verdicts (735
  // sweep mismatches, F3 red). floormod below is CPython's float-% algorithm EXACTLY (fmod + ONE
  // conditional add), which the executable parity pin requires BIT-identical: the review's
  // ((x%360)+360)%360 idiom is floored in semantics but its unconditional +360 introduces a 1-ulp
  // drift on negative remainders that flips 1dp rounding at the slack edges (stored=100.05 ->
  // inQ3 false vs true — caught by the F3 pin itself, see the fix-round report).
  function floormod(x, y) { var r = x % y; if (r !== 0 && r < 0) r += y; return r; }
  function wrap180(p) { return floormod(p + 180.0, 360.0) - 180.0; }
  // toFixed(1) — NOT Math.round(x*10)/10 — mirrors CPython round(x, 1): both round the EXACT decimal
  // value of the double (multiplying by 10 first manufactures .5 halves that do not exist in the true
  // value and rounds them half-up). On a genuine exact tie toFixed is half-up vs Python's half-even,
  // but 1dp tf.json values (norm_phase rounds t[4] to 1dp) can never produce an exact x.x5 double.
  function trueYx(stored) { return stored == null ? null : parseFloat(wrap180(stored - YX_SHIFT).toFixed(1)); }
  // mapYx: the engine gate's wrap-safe yx axis — TRUE phase mapped to (-360, 0] so Q3 ± slack is one
  // contiguous window and a value near ±180 cannot straddle the seam (phaseqc._map_yx mirror).
  function mapYx(t) { return t <= 0 ? t : t - 360.0; }
  // Per-point flags = band ± SLACK (fix-round F4b: a red dot means outside the band by MORE than the
  // slack), matching the engine gate's bands (phaseqc.in_quadrant_xy / in_quadrant_yx mirrors).
  function inQ1(pxy) { return pxy == null ? null : (pxy >= Q1_LO - SLACK && pxy <= Q1_HI + SLACK); }
  function inQ3(stored) {
    var v = trueYx(stored);
    if (v == null) return null;
    var m = mapYx(v);
    return (m >= Q3_LO - SLACK && m <= Q3_HI + SLACK);
  }
  // The engine gate's median (phaseqc._median mirror): sorted; middle, or the mean of the two middles.
  function medianOf(vals) {
    var s = vals.slice().sort(function (a, b) { return a - b; });
    var m = Math.floor(s.length / 2);
    return (s.length % 2) ? s[m] : 0.5 * (s[m - 1] + s[m]);
  }

  // ---- data URLs (fix-round F2): ABSOLUTE, never page-relative — from the hub page URL
  // /gateway/curator/survey/<slug> a relative 'data/...' resolves under /gateway/curator/survey/
  // and 404s, killing the whole tab. Matches the Overview/context-bar JS. Single-sourced here so the
  // executable URL parity pin can drive these exact functions.
  function dataUrl(name) { return '/data/' + name; }
  function stationJsonUrl(slug2, id) {
    return '/data/products/' + encodeURIComponent(slug2) + '/' + encodeURIComponent(id) + '/station.json';
  }

  // ---- survey row selection (hotfix H1, 2026-07-11) ----
  // ENGINE TRUTH: the catalogue `survey` column (C.survey) carries the survey's display LABEL
  // (build_portal: r["survey"] = survey_label, e.g. "Burra 2017-18"), NEVER the slug — the merged
  // Stage-2a filter compared it to the hub's slug and matched NOTHING, blanking the Stations tab on
  // every production survey (owner-reported). Join on ausmt_id (C.ausmt_id) instead: the engine
  // constructs it as au.<safe_component(slug)>.<station id>, and every slug the engine produces is
  // a safe_component FIXED POINT, so 'au.' + slug + '.' selects exactly this survey's rows. The
  // trailing dot is the survey boundary — 'au.burra-2017.' cannot prefix-match
  // 'au.burra-2017-18.A1'. A hypothetical slug that is NOT a fixed point (e.g. one containing '..',
  // which the engine never emits and no on-disk package carries) fails EMPTY (zero rows — the
  // honest no-stations message), never WRONG (another survey's rows). DOM-free BY DESIGN: the
  // executable Node pin drives THIS function with an engine-produced catalogue
  // (test_c43_stage2a_js_parity.py) — the shipped defect was an inline, undrivable filter loop.
  function surveyRows(cat, sci, tf, slug2) {
    var prefix = 'au.' + slug2 + '.';
    var rows = [];
    for (var i = 0; i < cat.length; i++) {
      if (String(cat[i][C.ausmt_id]).indexOf(prefix) !== 0) continue;
      rows.push({
        cat: cat[i],
        sc: (Array.isArray(sci) && sci[i]) ? sci[i] : null,
        tf: (Array.isArray(tf) && tf[i]) ? tf[i] : null
      });
    }
    return rows;
  }

  // ---- tiny DOM helpers (no innerHTML with data) ----
  function el(tag, text, cls) {
    var e = document.createElement(tag);
    if (text != null) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  }
  function svg(tag, attrs) {
    var e = document.createElementNS(SVGNS, tag);
    if (attrs) { for (var k in attrs) { if (attrs.hasOwnProperty(k)) e.setAttribute(k, attrs[k]); } }
    return e;
  }
  function svgText(x, y, str, opts) {
    var t = svg('text', { x: x, y: y, 'font-size': (opts && opts.size) || 8.5,
      'text-anchor': (opts && opts.anchor) || 'start', fill: (opts && opts.fill) || '#8FA3B0',
      'font-family': 'monospace' });
    t.textContent = str;   // textContent, never innerHTML
    return t;
  }
  function fetchJson(url) {
    return fetch(url, { credentials: 'omit', cache: 'no-store' }).then(function (r) {
      if (r.status === 404) return { __missing: true };
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }
  function num(v, dp) { return (v == null) ? '-' : (dp != null ? Number(v).toFixed(dp) : String(v)); }

  var W = 372, PADL = 40, PADR = 10;

  // A log-x scale over the period axis (periods are ascending, thinned to <=32).
  function xScale(per) {
    var lo = Math.log10(per[0]), hi = Math.log10(per[per.length - 1]);
    var span = (hi - lo) || 1;
    return function (v) { return PADL + (Math.log10(v) - lo) / span * (W - PADL - PADR); };
  }
  function supTen(d) {
    var m = {'-':'⁻','0':'⁰','1':'¹','2':'²','3':'³','4':'⁴',
             '5':'⁵','6':'⁶','7':'⁷','8':'⁸','9':'⁹'};
    return '10' + String(d).split('').map(function (c) { return m[c] || c; }).join('');
  }
  // The x-axis decade gridlines + labels, appended to an <svg> group.
  function xFrame(g, per, x, H) {
    g.appendChild(svg('rect', { x: PADL, y: 4, width: (W - PADL - PADR), height: (H - 22),
      fill: 'none', stroke: '#2E4254' }));
    var lo = Math.ceil(Math.log10(per[0])), hi = Math.floor(Math.log10(per[per.length - 1]));
    for (var d = lo; d <= hi; d++) {
      var xx = x(Math.pow(10, d));
      g.appendChild(svg('line', { x1: xx, y1: 4, x2: xx, y2: (H - 18), stroke: '#2E4254',
        'stroke-dasharray': '2,3' }));
      g.appendChild(svgText(xx, H - 6, supTen(d), { anchor: 'middle' }));
    }
  }
  // A polyline path over (period, value) pairs, skipping null/non-finite y — built as an SVG <path>
  // with a computed `d` string (numbers only, no data). Colour c.
  function linePath(g, per, vals, x, y, c) {
    var d = '', pen = false;
    for (var i = 0; i < per.length; i++) {
      var v = vals[i];
      if (v == null || !isFinite(y(v))) { pen = false; continue; }
      d += (pen ? 'L' : 'M') + x(per[i]).toFixed(1) + ',' + y(v).toFixed(1);
      pen = true;
    }
    if (d) g.appendChild(svg('path', { d: d, fill: 'none', stroke: c, 'stroke-width': 1.1 }));
  }
  // Per-point dots; when `flags` is supplied, an out-of-quadrant point (flag === false) is drawn RED.
  function dots(g, per, vals, x, y, c, flags) {
    for (var i = 0; i < per.length; i++) {
      var v = vals[i];
      if (v == null || !isFinite(y(v))) continue;
      var col = c;
      if (flags && flags[i] === false) col = '#D9534F';   // out-of-quadrant => red
      g.appendChild(svg('circle', { cx: x(per[i]).toFixed(1), cy: y(v).toFixed(1), r: 2.1, fill: col }));
    }
  }

  // ---- ρa plot (log-log) ----
  function rhoPlot(t) {
    var per = t[T.periods];
    if (!per || !per.length) return null;
    var all = t[T.rho_xy].concat(t[T.rho_yx]).filter(function (v) { return v != null && v > 0; });
    if (!all.length) return null;
    var H = 120, x = xScale(per);
    var lo = Math.floor(Math.log10(Math.min.apply(null, all)));
    var hi = Math.ceil(Math.log10(Math.max.apply(null, all)));
    if (hi <= lo) hi = lo + 1;
    var y = function (v) { return 4 + (hi - Math.log10(v)) / (hi - lo) * (H - 26); };
    var s = svg('svg', { width: W, height: H, role: 'img' });
    xFrame(s, per, x, H);
    for (var d = lo; d <= hi; d++) s.appendChild(svgText(PADL - 4, y(Math.pow(10, d)) + 3, supTen(d), { anchor: 'end' }));
    linePath(s, per, t[T.rho_xy], x, y, '#E0782F'); dots(s, per, t[T.rho_xy], x, y, '#E0782F');
    linePath(s, per, t[T.rho_yx], x, y, '#2E8FA3'); dots(s, per, t[T.rho_yx], x, y, '#2E8FA3');
    s.appendChild(svgText(W - 10, 14, 'xy', { anchor: 'end', size: 9, fill: '#E0782F' }));
    s.appendChild(svgText(W - 10, 25, 'yx', { anchor: 'end', size: 9, fill: '#2E8FA3' }));
    return wrapPlot('apparent resistivity ρ (Ω·m), log–log', s);
  }

  // ---- combined phase plan (C43 FR2-3): the pure, DOM-FREE data mapper for the ONE ±180 phase plot
  // (owner ruling 2026-07-11 — φxy and φyx share a single axis). It carries the two SERIES (true φxy =
  // stored t[3], which has no shift; true φyx = stored t[4] UNWRAPPED via trueYx), their per-point
  // band±slack flags + median verdicts (from the parity-tested classify — NO recompute), and the band
  // OWNERS: Q1 belongs to xy, Q3 (+ its ±180 seam continuation) belongs to yx. The Node harness
  // (test_c43_hub_js_parity / stage2a_js_parity) drives THIS function against classify(); the
  // mutation-proofs live here — reading the yx series raw (dropping trueYx) reds the series pin, and a
  // band that crossed 0 (a merged Q1+Q3 band) reds the band-ownership pin. Returns null when the
  // station carries no phase data at all.
  function combinedPhasePlan(t) {
    if (!t) return null;
    var per = t[T.periods];
    if (!per || !per.length) return null;
    var xyStored = t[T.phs_xy] || [];
    var yxStored = t[T.phs_yx_adj] || [];
    var hasXy = xyStored.some(function (v) { return v != null; });
    var hasYx = yxStored.some(function (v) { return v != null; });
    if (!hasXy && !hasYx) return null;
    var cxy = classify(xyStored, 'xy');   // stored φxy IS true
    var cyx = classify(yxStored, 'yx');   // classify unwraps the +180 shift internally
    return {
      xy: { series: xyStored.slice(),
            points: cxy.points, median: cxy.median, medianIn: cxy.medianIn, n: cxy.n },
      yx: { series: yxStored.map(trueYx),         // UNWRAP the +180 presentation shift to true φyx
            points: cyx.points, median: cyx.median, medianIn: cyx.medianIn, n: cyx.n },
      // Band owners on the ±180 display axis: Q1 -> xy; Q3 -> yx, plus the seam continuation
      // +170..+180 (φyx near +180 classifies IN Q3 via the wrap-safe (-360,0] axis — phaseqc._map_yx).
      // NO band crosses 0: Q1 and Q3 stay SEPARATELY owned (the band-ownership invariant the pin guards).
      bands: [ { comp: 'xy', lo: Q1_LO, hi: Q1_HI },
               { comp: 'yx', lo: Q3_LO, hi: Q3_HI },
               { comp: 'yx', lo: 170.0, hi: 180.0, seam: true } ]
    };
  }

  // ---- combined φ plot: ONE +180…−180 axis carrying BOTH φxy and φyx (owner ruling 2026-07-11) ----
  function phasePlot(t) {
    var plan = combinedPhasePlan(t);
    if (!plan) return null;
    var per = t[T.periods];
    var H = 150, x = xScale(per);
    var lo = -180, hi = 180;                    // FULL ±180 axis, shared by both components
    var y = function (v) { return 4 + (hi - v) / (hi - lo) * (H - 26); };
    var s = svg('svg', { width: W, height: H, role: 'img' });
    // BOTH expected bands shaded (the ok tone at TWO opacities — Q1 lighter, Q3 darker — so the two
    // are subtly distinguishable), owners taken from the plan. The seam band shows that φyx near +180
    // is still Q3 (the wrap); the caption names the wrap too.
    plan.bands.forEach(function (b) {
      s.appendChild(svg('rect', { x: PADL, y: y(b.hi), width: (W - PADL - PADR),
        height: (y(b.lo) - y(b.hi)), fill: '#5BAE6A',
        'fill-opacity': b.comp === 'xy' ? 0.09 : 0.17 }));
    });
    xFrame(s, per, x, H);
    [-180, -90, 0, 90, 180].forEach(function (v) {
      s.appendChild(svgText(PADL - 4, y(v) + 3, String(v), { anchor: 'end' })); });
    // φxy (stored = true) in the ρa-xy colour, φyx (unwrapped true) in the ρa-yx colour — each phase
    // component matches its ρa curve for cross-plot reading. Out-of-band(+slack) points draw RED per
    // component (classify().points), so a wrong-quadrant point is red on either series.
    linePath(s, per, plan.xy.series, x, y, '#E0782F');
    dots(s, per, plan.xy.series, x, y, '#E0782F', plan.xy.points);
    linePath(s, per, plan.yx.series, x, y, '#2E8FA3');
    dots(s, per, plan.yx.series, x, y, '#2E8FA3', plan.yx.points);
    // Tiny in-plot legend naming which series + band is whose.
    s.appendChild(svgText(W - 10, 14, 'φxy · Q1 band', { anchor: 'end', size: 9, fill: '#E0782F' }));
    s.appendChild(svgText(W - 10, 25, 'φyx · Q3 band', { anchor: 'end', size: 9, fill: '#2E8FA3' }));
    return { node: wrapPlot('phase φ (°) — φxy expect Q1 (0…90°) · φyx expect Q3 (−180…−90°, '
                          + 'wraps ±180)', s), plan: plan };
  }

  // ---- tipper: |T| (t[5]) plus Re Tzx (t[14]) and Re Tzy (t[16]) as read (no sign games) ----
  function tipperPlot(t) {
    var per = t[T.periods];
    if (!per || !per.length) return null;
    var mag = t[T.tip_mag], rzx = t[T.tzx_re], rzy = t[T.tzy_re];
    var present = mag.some(function (v) { return v != null; }) ||
                  rzx.some(function (v) { return v != null; }) ||
                  rzy.some(function (v) { return v != null; });
    if (!present) return null;
    var H = 108, x = xScale(per);
    var comps = mag.concat(rzx).concat(rzy).filter(function (v) { return v != null && isFinite(v); });
    var mx = Math.max(1, Math.ceil(Math.max.apply(null, comps.map(Math.abs)) * 10) / 10);
    var lo = -mx, hi = mx;
    var y = function (v) { return 4 + (hi - v) / (hi - lo) * (H - 26); };
    var s = svg('svg', { width: W, height: H, role: 'img' });
    xFrame(s, per, x, H);
    [-mx, 0, mx].forEach(function (v) { s.appendChild(svgText(PADL - 4, y(v) + 3, v.toFixed(1), { anchor: 'end' })); });
    s.appendChild(svg('line', { x1: PADL, y1: y(0), x2: (W - PADR), y2: y(0), stroke: '#2E4254', 'stroke-dasharray': '2,3' }));
    linePath(s, per, mag, x, y, '#E8EDF1'); dots(s, per, mag, x, y, '#E8EDF1');
    linePath(s, per, rzx, x, y, '#E0782F'); dots(s, per, rzx, x, y, '#E0782F');
    linePath(s, per, rzy, x, y, '#2E8FA3'); dots(s, per, rzy, x, y, '#2E8FA3');
    s.appendChild(svgText(W - 10, 14, '|T|', { anchor: 'end', size: 9, fill: '#E8EDF1' }));
    s.appendChild(svgText(W - 10, 25, 'Re Tzx', { anchor: 'end', size: 9, fill: '#E0782F' }));
    s.appendChild(svgText(W - 10, 36, 'Re Tzy', { anchor: 'end', size: 9, fill: '#2E8FA3' }));
    return wrapPlot('tipper |T| and Re Tzx / Re Tzy (as read)', s);
  }

  // Series classification (phaseqc.classify_series mirror, fix-round F4c): per-point band±slack
  // flags (the red dots) + the MEDIAN verdict, engine-rule aligned — for yx the median is computed on
  // the seam-mapped (-360, 0] axis and reported back in (-180, 180] (the engine's med_yx_report rule).
  function classify(vals, mode) {
    var points, trues, median = null, medianIn = null;
    if (mode === 'xy') {
      points = (vals || []).map(inQ1);
      trues = (vals || []).filter(function (v) { return v != null; });
      if (trues.length) {
        median = medianOf(trues);
        medianIn = (median >= Q1_LO - SLACK && median <= Q1_HI + SLACK);
      }
    } else {
      points = (vals || []).map(inQ3);
      trues = (vals || []).map(trueYx).filter(function (v) { return v != null; });
      if (trues.length) {
        var medMapped = medianOf(trues.map(mapYx));
        medianIn = (medMapped >= Q3_LO - SLACK && medMapped <= Q3_HI + SLACK);
        median = medMapped < -180.0 ? medMapped + 360.0 : medMapped;
      }
    }
    var classified = points.filter(function (p) { return p !== null; });
    var anyOut = classified.some(function (p) { return p === false; });
    return { points: points, any_out: anyOut, n: classified.length,
             median: median, medianIn: medianIn };
  }

  // ---- C43-HUB H3 pure formatters (DOM-free; the Node harness drives these exact functions —
  // test_c43_hub_js_parity.py — with REAL engine corpus rows/frames) -----------------------------
  // Truncated sha for inline display: 'CP1L04.edi · sha256 9c41…e2' with the FULL hash in the
  // title attr. Odd shapes (non-hex, short) render VERBATIM — never hide information (the
  // builddisplay.py posture).
  function shortSha(h) {
    var s = String(h == null ? '' : h);
    if (/^[0-9a-f]{12,}$/i.test(s)) return s.slice(0, 4) + '…' + s.slice(-2);
    return s;
  }
  // The portal's station deep-link: portal/src/main.js routes '#/station/<ausmt_id>' (drawer.js
  // writes the same hash), and the portal is served at this origin's root — so the link is a
  // same-origin fragment URL, no new privilege.
  function portalStationUrl(ausmtId) {
    return '/#/station/' + encodeURIComponent(String(ausmtId == null ? '' : ausmtId));
  }
  function latLonText(lat, lon) { return num(lat, 3) + ' / ' + num(lon, 3); }
  // The station's EFFECTIVE coordinate policy: its coord_policy.json override if present, else
  // 'exact'. The engine stamps the RESOLVED policy (override-or-survey-default) on that boot artifact
  // for non-exact stations only, so 'absent => exact' is honest for BOTH a default-exact station and
  // an explicit exact override. Pure (map + id in) so the executable JS pin exercises it.
  function effectivePolicy(policyMap, ausmtId) {
    return (policyMap && policyMap[ausmtId]) || 'exact';
  }
  // Position + the C42 EFFECTIVE-policy marker (Stage-4): '(exact)' / '(generalised)' / '(withheld)'
  // from effectivePolicy — the honest served state, not a static label. A withheld station's masked
  // lat/lon are null (num renders '-'), a generalised station carries the 0.1deg cell VERBATIM (no
  // client re-rounding). The coordinate-PARSE QC flag (catalogue coord_flag) is a DIFFERENT fact and
  // stays appended when set — the boolean form keeps the established 'coordinate flag set' wording (a
  // bare 'true' says nothing), a string value renders verbatim.
  function positionText(lat, lon, coordFlag, policy) {
    var t = num(lat, 4) + ', ' + num(lon, 4) + ' (' + (policy || 'exact') + ')';
    if (coordFlag === true) return t + ' · coordinate flag set';
    return coordFlag ? t + ' · coord QC: ' + String(coordFlag) : t;
  }
  function bandText(pmin, pmax, nper) {
    return num(pmin) + ' – ' + num(pmax) + ' s · ' + num(nper) + ' periods';
  }
  function dimText(dim, skew) {
    var d = (dim == null || dim === '') ? '-' : String(dim);
    return (skew == null) ? d : d + ' (skew β median ' + String(skew) + '°)';
  }
  // Median relative apparent-resistivity error as a percentage — the same *100 presentation the
  // portal's own drawer uses for this sci field (drawer.js), 1 dp.
  function mreText(mre) {
    if (mre == null || !isFinite(Number(mre))) return '-';
    return (Number(mre) * 100).toFixed(1) + ' %';
  }
  function tipperText(comps) {
    return (String(comps == null ? '' : comps).indexOf('T') >= 0) ? 'present' : 'absent';
  }
  function signedMedian(m) { return (m >= 0 ? '+' : '') + m.toFixed(1) + '°'; }
  function sentencePart(comp, q, c) {
    if (!c || c.n === 0 || c.median == null) {
      return { t: comp + ' — no verdict (insufficient phase data)', out: false };
    }
    if (c.medianIn) {
      return { t: comp + ' in-quadrant (median ' + signedMedian(c.median) + ')', out: false };
    }
    return { t: 'arg(' + comp + ') median ' + signedMedian(c.median) + ' out of ' + q, out: true };
  }
  // The convention fact AS A SENTENCE with the medians (contract H3; the medians are the SAME
  // classify() output the plots/verdict strips use — the parity-tested seam, no recompute):
  // 'arg(Zyx) median +51.9° out of Q3; Zxy in-quadrant (median +45.2°)'. The out-of-quadrant
  // component leads (the mockup's shape); .out drives the warn colour.
  function conventionSentence(cXy, cYx) {
    var px = sentencePart('Zxy', 'Q1', cXy);
    var py = sentencePart('Zyx', 'Q3', cYx);
    var parts = (py.out && !px.out) ? [py, px] : [px, py];
    return { text: parts[0].t + '; ' + parts[1].t, out: px.out || py.out };
  }
  // The frame declaration IN WORDS (contract H3: 'declared-zero · no rotation declared'), built
  // from VERBATIM station.json frame fields — no reinterpretation: frame_served as stored, then
  // de-rotation / declared-azimuth / no-rotation from the derotated + declared_azimuth_deg
  // fields. C25-V3 F2: tipper_declared_azimuth_deg (present ONLY when the tipper's uniform declared
  // frame diverges from the impedance's declared azimuth — the engine omits it otherwise) appends a
  // 'tipper declared azimuth N°' part, same verbatim String() coercion. Extra frame fields stay in
  // the collapsed raw-JSON details.
  function frameWords(frame) {
    if (!frame || typeof frame !== 'object') return null;
    var parts = [String(frame.frame_served == null ? '-' : frame.frame_served)];
    if (frame.derotated) {
      parts.push('de-rotated to the declared zero-azimuth reference');
    } else if (frame.declared_azimuth_deg != null && Number(frame.declared_azimuth_deg) !== 0) {
      parts.push('declared azimuth ' + String(frame.declared_azimuth_deg) + '°');
    } else {
      parts.push('no rotation declared');
    }
    if (frame.tipper_declared_azimuth_deg != null) {
      parts.push('tipper declared azimuth ' + String(frame.tipper_declared_azimuth_deg) + '°');
    }
    return parts.join(' · ');
  }
  // Panel status chip + list quality chip — BOTH derived from the same classify() results
  // (contract H3: 'derive from the same QA data as the list chips'). A station whose median is
  // out of its expected quadrant is 'served with note' (it IS served — Gate 2 WARNs never drop).
  function stationStatus(cXy, cYx) {
    var xyOut = !!(cXy && cXy.n > 0 && cXy.median != null && !cXy.medianIn);
    var yxOut = !!(cYx && cYx.n > 0 && cYx.median != null && !cYx.medianIn);
    if (xyOut || yxOut) return { label: 'served with note', kind: 'warn' };
    return { label: 'served', kind: 'ok' };
  }
  function qualityChip(cXy, cYx, dim) {
    var xyOut = !!(cXy && cXy.n > 0 && cXy.median != null && !cXy.medianIn);
    var yxOut = !!(cYx && cYx.n > 0 && cYx.median != null && !cYx.medianIn);
    if (xyOut && yxOut) return { label: 'Zxy+Zyx quadrant', kind: 'warn' };
    if (xyOut) return { label: 'Zxy quadrant', kind: 'warn' };
    if (yxOut) return { label: 'Zyx quadrant', kind: 'warn' };
    return { label: (dim == null || dim === '') ? '?' : String(dim), kind: 'neutral' };
  }
  // One classification per station, shared by the panel chip, the convention sentence, and the
  // list quality chip (and consistent with the plot verdict strips, which classify the same
  // series).
  function classifyStation(t) {
    if (!t) return { xy: classify([], 'xy'), yx: classify([], 'yx') };
    return { xy: classify(t[T.phs_xy] || [], 'xy'), yx: classify(t[T.phs_yx_adj] || [], 'yx') };
  }
  // Terse conditioning fragment (gate F1): each canonical_conditioning note string terses to a
  // PREFIX of itself — the text before the engine's own ' — ' explanation separator — and a
  // fragment is never allowed to strand an open parenthesis (the channel-orientations note has
  // its em-dash INSIDE parens; a mid-paren cut would garble). Prefix-derivation means the line
  // can never say something the note does not; the FULL notes ride the title attr and the raw
  // JSON stays in the collapsed details.
  function terseConditioningNote(note) {
    var s = String(note == null ? '' : note);
    var cut = s.indexOf(' — ');
    var frag = cut >= 0 ? s.slice(0, cut) : s;
    var open = (frag.match(/\(/g) || []).length;
    var close = (frag.match(/\)/g) || []).length;
    if (open > close) frag = frag.slice(0, frag.indexOf('(')).replace(/\s+$/, '');
    return frag;
  }
  // The mockup's ONE conditioning line: terse fragments joined ' · '.
  function conditioningLine(notes) {
    var frags = (notes || []).map(terseConditioningNote).filter(function (f) { return !!f; });
    return frags.length ? frags.join(' · ') : null;
  }
  // Terse coordinate-QC line (gate F2): the station.json coordinate_qc fields on one line —
  // flag verbatim, the HEAD/INFO conflict when recorded, the resolution when recorded. A null
  // field is OMITTED, never asserted (no invented 'unresolved'). Warn-toned by the caller when
  // flagged; the Position row's catalogue-flag marker stays the primary signal.
  function coordQcLine(qc) {
    if (!qc || typeof qc !== 'object') return null;
    var parts = [];
    if (qc.flag) parts.push(String(qc.flag));
    if (qc.head_info_conflict_deg != null) {
      parts.push('HEAD/INFO conflict ' + String(qc.head_info_conflict_deg) + '°');
    }
    if (qc.resolution) parts.push('resolution: ' + String(qc.resolution));
    return parts.length ? parts.join(' · ') : null;
  }

  // A plot card: a caption div + the svg. The verdict strip is appended SEPARATELY, beneath.
  function wrapPlot(caption, svgNode) {
    var box = el('div', null, 'plot');
    box.style.margin = '.5rem 0';
    box.appendChild(el('div', caption, 'k'));
    box.appendChild(svgNode);
    return box;
  }
  // The combined verdict-strip PARTS (C43 FR2-3): ONE strip beneath the single phase plot carries
  // BOTH component verdicts. Pure + DOM-free so the Node harness pins that BOTH components are present
  // (a strip missing a component reds the mutation-proof). Each part is {comp, expect, text, out};
  // the VERDICT is the MEDIAN vs band+slack (fix-round F4c — the engine gate's rule) using the SAME
  // classify() output the plot dots use (no recompute). Red dots (per-point beyond-slack flags) can
  // coexist with a green median verdict — scattered outliers do not flip a station verdict, a coherent
  // median does. `out` drives the warn colour on that component's lead.
  function phaseVerdictParts(plan) {
    function part(comp, expect, c) {
      if (!c || c.n === 0 || c.median == null) {
        return { comp: comp, expect: expect, text: 'expect ' + expect + ' — no phase data',
                 out: false };
      }
      var med = 'median ' + comp + ' ' + c.median.toFixed(1) + '°';
      if (c.medianIn) {
        return { comp: comp, expect: expect,
                 text: 'expect ' + expect + ' — ' + med + ' — in quadrant ✓', out: false };
      }
      return { comp: comp, expect: expect,
               text: 'expect ' + expect + ' — ' + med + ' — out of quadrant ⚠', out: true };
    }
    return [ part('φxy', 'Q1', plan && plan.xy),
             part('φyx', 'Q3', plan && plan.yx) ];
  }

  // ONE verdict strip beneath the combined phase plot, carrying BOTH component verdicts joined ' · ';
  // an out-of-quadrant component leads in the warn colour, the in-quadrant one stays green.
  function combinedVerdictStrip(plan) {
    var strip = el('div', null, 'sub');
    strip.style.margin = '.15rem 0 .5rem';
    phaseVerdictParts(plan).forEach(function (p, i) {
      if (i) strip.appendChild(document.createTextNode(' · '));
      var span = el('span', p.text);
      span.style.color = p.out ? '#D9534F' : '#5BAE6A';
      strip.appendChild(span);
    });
    return strip;
  }

  // ---- facts panel (C43-HUB H3: the mockup's information design — science before plumbing) ----
  // Panel header row: mono station id + status chip (derived from the SAME classify() results the
  // list chips use) + the portal deep-link (portal route '#/station/<ausmt_id>'). Facts as a
  // dl.facts in EXACTLY the mockup's order: Position (+ the EFFECTIVE C42 policy marker — override
  // or survey default, from coord_policy.json), Band on one line, Frame in words, Convention as a sentence with the
  // medians (warn-coloured when out), Dimensionality (+ skew β when sci carries it), Median rel.
  // error, Tipper, Source file + TRUNCATED sha (full hash in the title attr). The panel-only
  // catalogue plumbing rows the mockup dropped (Components/Type/Remote reference) are dropped
  // here too — the approved information design; the raw station.json details keep the depth.
  // `cls` is classifyStation(tf); `station` is null while station.json is in flight, __missing
  // when the products tree is not served (the Frame row says so honestly).
  function factsPanel(cat, sc, station, buildId, lagPending, cls) {
    var panel = el('div', null, 'panel');
    // [FC-2] lag label ON THE PANEL when served != published (not only the drift chip).
    if (lagPending) {
      var lag = el('p', 'facts from build ' + (buildId || '(unknown)') + ' — publish pending', 'sub');
      lag.style.color = '#D9A23B'; lag.style.fontWeight = '600';
      panel.appendChild(lag);
    }
    var ph = el('div', null, 'ph');
    ph.appendChild(el('span', String(cat[C.id]), 'phid'));
    var st = stationStatus(cls.xy, cls.yx);
    var badge = el('span', st.label, 'badge');
    badge.style.background = (st.kind === 'warn') ? '#D9A23B' : '#5BAE6A';
    ph.appendChild(badge);
    if (cat[C.ausmt_id]) {
      var go = el('span', null, 'go');
      var pa = el('a', 'open in portal ↗');
      pa.href = portalStationUrl(cat[C.ausmt_id]);
      pa.target = '_blank'; pa.rel = 'noopener';
      go.appendChild(pa);
      ph.appendChild(go);
    }
    panel.appendChild(ph);

    var dl = el('dl', null, 'facts');
    function fact(k, v, opts) {
      dl.appendChild(el('dt', k));
      var dd = el('dd', v);
      if (opts && opts.mono) dd.style.fontFamily = 'ui-monospace,Consolas,monospace';
      if (opts && opts.warn) dd.style.color = '#D9A23B';
      if (opts && opts.title) dd.setAttribute('title', opts.title);
      dl.appendChild(dd);
    }
    fact('Position', positionText(cat[C.lat], cat[C.lon], cat[C.coord_flag],
                                  effectivePolicy(COORD_POLICY, cat[C.ausmt_id])), { mono: true });
    // Gate F2: the coordinate-QC detail as ONE terse line right under Position (warn-toned when
    // flagged) — the raw JSON lives only in the collapsed details below.
    if (station && !station.__missing && station.coordinate_qc) {
      var cq = coordQcLine(station.coordinate_qc);
      if (cq) fact('Coordinate QC', cq, { warn: !!station.coordinate_qc.flag });
    }
    fact('Band', bandText(cat[C.pmin], cat[C.pmax], cat[C.nper]));
    if (station == null) {
      fact('Frame', '…');                       // station.json in flight
    } else if (station.__missing || !station.frame) {
      fact('Frame', 'not served (no station.json for this build)');
    } else {
      fact('Frame', frameWords(station.frame) || '-');
    }
    var conv = conventionSentence(cls.xy, cls.yx);
    fact('Convention', conv.text, { warn: conv.out });
    if (sc) {
      fact('Dimensionality', dimText(sc[SC.dim], sc[SC.skew]));
      fact('Median rel. error', mreText(sc[SC.mre]));
    }
    fact('Tipper', tipperText(cat[C.comps]));
    // Gate F1: conditioning as ONE terse line (the mockup's 'Conditioning: sign_convention
    // library default · …' shape) — prefix-derived fragments, FULL notes on the title attr.
    if (station && !station.__missing && station.canonical_conditioning) {
      var cl2 = conditioningLine(station.canonical_conditioning);
      if (cl2) fact('Conditioning', cl2,
                    { title: (station.canonical_conditioning || []).join('\n') });
    }
    var shaFull = String(cat[C.sha256] || '');
    fact('Source file', (cat[C.file] || '-') + ' · sha256 ' + shortSha(shaFull),
         { mono: true, title: shaFull ? 'sha256 ' + shaFull : null });
    panel.appendChild(dl);

    if (station && !station.__missing) {
      // Gate F1/F2: NO raw JSON visible outside a collapsed details. ONE details carries the
      // ENTIRE fetched station.json verbatim (frame + conditioning + coordinate QC + every
      // extra field) — superseding the frame-only 'raw frame declaration' block; all values via
      // textContent, never innerHTML.
      var det = el('details');
      var sum = el('summary', 'raw station.json'); det.appendChild(sum);
      var fp = el('pre'); fp.textContent = JSON.stringify(station, null, 1); det.appendChild(fp);
      panel.appendChild(det);
    }
    return panel;
  }

  // ---- drill-down: facts (col 2) + plots (col 3) + remove link ----
  function openStation(idx, rows, buildId, lagPending) {
    var factsHost = document.getElementById('station-facts');
    var plotsHost = document.getElementById('station-plots-col');
    factsHost.textContent = ''; plotsHost.textContent = '';
    var r = rows[idx];
    var cat = r.cat, sc = r.sc, t = r.tf;
    var cls = classifyStation(t);   // ONE classification: panel chip + sentence + (list chips)
    // Facts render immediately from catalogue/sci into the MIDDLE column; station.json enriches them
    // when it loads. Plots depend only on t (tf) so they render once into the RIGHT column.
    var panel = factsPanel(cat, sc, null, buildId, lagPending, cls);
    factsHost.appendChild(panel);
    renderPlots(plotsHost, t);
    appendRemove(factsHost, cat);
    // Enrich the facts with the per-station station.json (frame/conditioning/QA) if the products tree
    // is served. ABSOLUTE url via the single-sourced helper (fix-round F2 — a page-relative fetch 404s).
    fetchJson(stationJsonUrl(slug, cat[C.id])).then(function (station) {
      var enriched = factsPanel(cat, sc, station || { __missing: true }, buildId, lagPending, cls);
      factsHost.replaceChild(enriched, panel);
      panel = enriched;
      appendRemove(factsHost, cat);
    }).catch(function () {
      // Products not served for this build: re-render with the honest Frame placeholder.
      var fallback = factsPanel(cat, sc, { __missing: true }, buildId, lagPending, cls);
      factsHost.replaceChild(fallback, panel);
      panel = fallback;
      appendRemove(factsHost, cat);
    });
  }
  // Build the plots column (col 3): ρa, the NEW combined ±180 phase plot (+ its two-component verdict
  // strip), then tipper — in that vertical order (owner ruling round 2). Idempotent: clears first.
  function renderPlots(host, t) {
    host.textContent = '';
    if (!t) {
      host.appendChild(el('p', 'No response-curve data served for this station.', 'sub'));
      return;
    }
    var rp = rhoPlot(t); if (rp) host.appendChild(rp);
    var ph = phasePlot(t);
    if (ph) { host.appendChild(ph.node); host.appendChild(combinedVerdictStrip(ph.plan)); }
    var tp = tipperPlot(t); if (tp) host.appendChild(tp);
  }
  function appendRemove(detail, cat) {
    if (document.getElementById('station-remove')) return;
    var p = el('p'); p.id = 'station-remove';
    var a = el('a', 'Remove this station (opens the removal flow)');
    // ABSOLUTE href (fix-round F2 class): a page-relative 'edit/...' from /gateway/curator/survey/<slug>
    // resolves under /survey/ and 404s — same defect class as the relative data fetches.
    a.href = '/gateway/curator/edit/' + encodeURIComponent(slug) + '/stations';
    p.appendChild(a);
    detail.appendChild(p);
  }

  // ---- list + filter (C43 FR2-2: the site table is the LEFT column; the FACTS panel #station-facts
  // and the PLOTS column #station-plots-col are pre-rendered siblings in the middle/right columns).
  // The table lives inside a FIXED-HEIGHT scroll region (.st-scroll) with the filter box ABOVE it, so
  // a >300-station survey scrolls WITHIN the list and never pushes the facts/plots off-screen. Row
  // click populates the facts + plots WITHOUT the page scrolling (no location hash, no scrollIntoView)
  // and highlights the selected row. ----
  function render(rows, buildId, lagPending) {
    var list = document.getElementById('stations-list');
    list.textContent = '';
    if (lagPending) {
      var lag = el('p', 'Facts from build ' + (buildId || '(unknown)') + ' — publish pending', 'sub');
      lag.style.color = '#D9A23B'; lag.style.fontWeight = '600';
      list.appendChild(lag);
    }
    if (!rows.length) {
      list.appendChild(el('p', 'No stations for this survey in the served corpus (' + slug + ').', 'sub'));
      return;
    }
    var filterWrap = el('p', null, 'st-filter');
    var filter = document.createElement('input');
    filter.type = 'search'; filter.placeholder = 'filter stations by id…';
    filter.style.maxWidth = '18rem';
    filterWrap.appendChild(filter);
    list.appendChild(filterWrap);

    var scroll = el('div', null, 'st-scroll');
    var tbl = el('table');
    var head = el('tr');
    // C43-HUB H3: Lat/Lon MERGED into one column (the mockup's list shape).
    ['Station', 'Lat / Lon', 'Periods', 'Quality'].forEach(function (h) { head.appendChild(el('th', h)); });
    tbl.appendChild(head);
    var selected = null;
    rows.forEach(function (r, i) {
      var cat = r.cat, sc = r.sc;
      var tr = el('tr', null, 'st-row');
      tr.setAttribute('data-station-id', String(cat[C.id]).toLowerCase());
      tr.setAttribute('tabindex', '0');   // keyboard-focusable row (whole-row selection target)
      function select(ev) {
        if (ev) ev.preventDefault();
        if (selected) selected.classList.remove('on');
        tr.classList.add('on');
        selected = tr;
        // openStation clears + repopulates the facts (col 2) and plots (col 3) columns in place.
        openStation(i, rows, buildId, lagPending);
      }
      tr.addEventListener('click', select);
      tr.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter' || ev.key === ' ') select(ev);   // Space/Enter activate the focused row
      });
      tr.appendChild(el('td', String(cat[C.id])));
      tr.appendChild(el('td', latLonText(cat[C.lat], cat[C.lon])));
      tr.appendChild(el('td', num(cat[C.nper])));
      // Quality chip (C43-HUB H3): the SAME QA data the panel status chip derives from — a
      // quadrant-warn component names itself ('Zyx quadrant', amber); a clean station shows its
      // dimensionality class as the neutral diagnostic (NOT a value judgement).
      var chip = el('td');
      var clsRow = classifyStation(r.tf);
      var qc = qualityChip(clsRow.xy, clsRow.yx, sc ? sc[SC.dim] : null);
      var badge = el('span', qc.label, 'badge');
      if (qc.kind === 'warn') { badge.style.background = '#D9A23B'; }
      else { badge.style.background = '#2E4254'; badge.style.color = '#E8EDF1'; }
      chip.appendChild(badge);
      tr.appendChild(chip);
      tbl.appendChild(tr);
    });
    scroll.appendChild(tbl);
    list.appendChild(scroll);

    filter.addEventListener('input', function () {
      var q = filter.value.trim().toLowerCase();
      tbl.querySelectorAll('tr[data-station-id]').forEach(function (tr) {
        var hit = !q || tr.getAttribute('data-station-id').indexOf(q) >= 0;
        tr.style.display = hit ? '' : 'none';
      });
    });
  }

  // ---- load + join (ABSOLUTE urls via dataUrl — fix-round F2) ----
  Promise.all([
    fetchJson(dataUrl('catalogue.json')).catch(function () { return { __err: true }; }),
    fetchJson(dataUrl('sci.json')).catch(function () { return { __err: true }; }),
    fetchJson(dataUrl('tf.json')).catch(function () { return { __err: true }; }),
    fetchJson(dataUrl('build.json')).catch(function () { return { __err: true }; }),
    // coord_policy.json is OPTIONAL (absent for an all-exact corpus) — tolerate absence, same
    // graceful-degrade posture as the portal (empty => every station reads 'exact').
    fetchJson(dataUrl('coord_policy.json')).catch(function () { return {}; })
  ]).then(function (res) {
    var cat = res[0], sci = res[1], tf = res[2], build = res[3], cpol = res[4];
    if (cpol && !cpol.__err && !cpol.__missing && typeof cpol === 'object' && !Array.isArray(cpol)) {
      COORD_POLICY = cpol;
    }
    if (!cat || cat.__err || cat.__missing || !Array.isArray(cat)) {
      host.textContent = '';
      host.appendChild(el('p', 'No served catalogue yet (data/catalogue.json). Stations appear once '
        + 'this survey is built into the served corpus.', 'sub'));
      return;
    }
    var buildId = (build && !build.__err && !build.__missing) ? (build.build_id || null) : null;
    var served = (build && !build.__err && !build.__missing) ? (build.source_commit || '') : '';
    // [FC-2]: lag is pending when the served source_commit differs from the published HEAD (prefix-
    // tolerant, matching the drift chip). Only judgeable with both sides present.
    var lagPending = false;
    if (publishedHead && served) {
      lagPending = !(publishedHead.indexOf(served) === 0 || served.indexOf(publishedHead) === 0);
    }
    // Join catalogue/sci/tf BY INDEX, filtered to this survey's rows by ausmt_id prefix (H1 —
    // the survey column is the display label, never the slug; see surveyRows).
    render(surveyRows(cat, sci, tf, slug), buildId, lagPending);
  }).catch(function (e) {
    host.textContent = '';
    host.appendChild(el('p', 'Could not load the served corpus: ' + e.message, 'sub'));
  });
})();
"""


# The Surveys-list browser script (C43 FR2-1): fill the display name / version / licence / served
# station-count columns from the served /data corpus SAME-ORIGIN (surveys.json + build_report.json —
# the serve-panel pattern, ZERO new gateway privileges; the gateway has no site-data mount). surveys.json
# is keyed by the display LABEL, so we join by each entry's own `slug` field (mirrors the Stations tab's
# ausmt_id join — the label is not the slug). ABSENT facts render absent ('—'), never invented. RAW JS
# served by GET /gateway/curator/surveys-list.js — inline is dead under script-src 'self'; every value
# goes in via textContent (never innerHTML) so a served-metadata string cannot inject markup. DEGRADES:
# without the script every row still shows its slug + the hub link.
SURVEYS_LIST_JS = r"""
(function () {
  var table = document.getElementById('surveys-table');
  if (!table) return;
  function fetchJson(url) {
    return fetch(url, { credentials: 'omit', cache: 'no-store' }).then(function (r) {
      if (r.status === 404) return { __missing: true };
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }
  // surveys.json is keyed by the survey display LABEL (its NAME — the portal reads the same key as the
  // survey title); each entry carries its own `slug` (the engine stamps it —
  // build_portal.survey_meta_from_yaml; the entry has NO separate `name` field). Build a slug ->
  // {label, entry} map from the values (the label IS the display name), the same way the Stations tab
  // joins the catalogue by ausmt_id rather than the label column.
  function bySlug(surveys) {
    var out = {};
    if (!surveys || surveys.__missing || surveys.__err || typeof surveys !== 'object') return out;
    Object.keys(surveys).forEach(function (label) {
      var e = surveys[label];
      if (e && e.slug != null) out[String(e.slug)] = { label: label, entry: e };
    });
    return out;
  }
  // ABSENT => leave the server-rendered '—' placeholder (never invent a value).
  function setCell(tr, key, value) {
    var span = tr.querySelector('[data-cell="' + key + '"]');
    if (!span) return;
    if (value != null && value !== '') span.textContent = String(value);
  }
  Promise.all([
    fetchJson('/data/surveys.json').catch(function () { return { __err: true }; }),
    fetchJson('/data/build_report.json').catch(function () { return { __err: true }; })
  ]).then(function (res) {
    var surveys = bySlug(res[0]);
    var rep = res[1];
    var repSurveys = (rep && !rep.__err && !rep.__missing) ? (rep.surveys || {}) : {};
    table.querySelectorAll('tr[data-survey-slug]').forEach(function (tr) {
      var slug = tr.getAttribute('data-survey-slug');
      var rec = surveys[slug];
      if (rec) {
        setCell(tr, 'name', rec.label);         // the display name is the surveys.json key (label)
        setCell(tr, 'version', rec.entry.version);
        setCell(tr, 'licence', rec.entry.lic);
      }
      var rs = repSurveys[slug];
      if (rs && rs.stations_built != null) setCell(tr, 'stations', rs.stations_built);
    });
  });
})();
"""


def _esc(value) -> str:
    return html.escape(str(value), quote=True)


def _url_quote(value) -> str:
    """URL-encode a single path SEGMENT for an href (safe='' so `/` is encoded too — the caller joins
    already-split segments). Used for the quarantine file links, whose relative paths are
    server-enumerated (never curator-typed) but may carry spaces/odd chars a bare href would break."""
    from urllib.parse import quote
    return quote(str(value), safe="")


# The canonical stored-UTC shape (db._utc_now: time.strftime("%Y-%m-%dT%H:%M:%SZ")).
_UTC_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}):\d{2}Z$")


def short_utc(ts: str) -> str:
    """The display form of a stored UTC timestamp (H2): the canonical db shape renders as
    '2026-07-08 07:49' (date + minutes — operator resolution; the full ISO rides in the cell's
    title attribute at the call site). VERBATIM fallback: any other shape is returned unchanged,
    never mangled or emptied — the S2a-5 build-id shortener posture (audit data is sacred)."""
    m = _UTC_TS_RE.match(ts or "")
    return f"{m.group(1)} {m.group(2)}" if m else (ts or "")


def _dt_html(ts: str) -> str:
    """A datetime table cell fragment: the short form as visible text, the full stored ISO in a
    title attribute (hover keeps the audit precision), tabular-nums + nowrap via .dt."""
    return f'<span class="dt" title="{_esc(ts)}">{_esc(short_utc(ts))}</span>'


def _head(title: str) -> str:
    return Template(_HEAD).substitute(
        title=_esc(title), bg=_PALETTE["bg"], ink=_PALETTE["ink"], muted=_PALETTE["muted"],
        accent=_PALETTE["accent"], panel=_PALETTE["panel"], ok=_PALETTE["ok"],
        warn=_PALETTE["warn"], bad=_PALETTE["bad"], info=_PALETTE["info"],
    )


def _page(title: str, body: str) -> str:
    """A CHROME-LESS page: no left rail, no context bar. Used only where there is no curator session
    to hang chrome on (the login page) or where a bare terminal confirmation reads cleanest (the
    edit/removal "committed" pages). Every session-gated working page goes through _shell instead."""
    return _head(title) + '<div class="wrap">' + body + "</div>" + _TAIL


# ---- C43 Stage 1 nav shell (S1-1) ----------------------------------------------------------------
# The persistent left rail + context bar every curator working page renders. Server-rendered chrome
# (string.Template, no framework, no templates dir — the house architecture); the ONLY browser-side
# piece is the drift chip's served-build half, filled by an external context-bar script (the
# precedented serve-state pattern) — ALL JS stays in external route constants (the strictPages CSP is
# script-src 'self'). Published HEAD is server-rendered here from serve_state.read_published_head.

# The rail sections and their entries, as (group, [(key, label, href)]). Collections joined the
# Surveys group in Stage 3a (record D5-A) — the read-only projection at /gateway/curator/collections;
# it sits beside Surveys because a collection is a programme grouping OF surveys.
_RAIL = (
    ("Surveys", (("surveys", "Surveys", "/gateway/curator/edit"),
                 ("collections", "Collections", "/gateway/curator/collections"))),
    ("Intake", (("queue", "Submission queue", "/gateway/curator/queue"),
                ("uploaders", "Uploader keys", "/gateway/curator/uploaders"))),
    # Security sits under Operations beside Serve state (C41 T2): it is an operator-facing account
    # concern — enrolling the authenticator that gates the destructive workbench actions — not a
    # per-survey editing surface, so Operations is its home rather than Surveys/Intake.
    # Analytics (C45) sits under Operations beside Serve state: it is a read-only, operator/reporting
    # surface over the box's own usage aggregates (downloads/visits/countries), the same trust class as
    # the ops floor — not a per-survey editing surface.
    ("Operations", (("serve", "Serve state", "/gateway/curator/serve"),
                    ("analytics", "Analytics", "/gateway/curator/analytics"),
                    ("security", "Security", "/gateway/curator/security"))),
)


class NavContext:
    """The server-side chrome inputs a curator page passes to _shell. `active` is the rail key to
    highlight; `crumb` is the ready-made breadcrumb HTML (already escaped by the caller);
    `published_head`/`published_available` feed the drift chip's server-rendered half (the served
    build id half is browser-populated); `csrf` arms the ever-present Request-rebuild button.
    `show_rebuild` False drops the button on pages where it would be noise (none in Stage 1 — kept as
    a seam)."""

    def __init__(self, *, active: str, crumb: str, published_head: str | None,
                 published_available: bool, csrf: str, show_rebuild: bool = True):
        self.active = active
        self.crumb = crumb
        self.published_head = published_head
        self.published_available = published_available
        self.csrf = csrf
        self.show_rebuild = show_rebuild


def _rail_html(active: str) -> str:
    parts = ['<nav class="rail"><div class="brand">AusMT curator</div>']
    for group, entries in _RAIL:
        parts.append(f'<div class="grp">{_esc(group)}</div>')
        for key, label, href in entries:
            on = " on" if key == active else ""
            parts.append(f'<a class="railitem{on}" href="{_esc(href)}">{_esc(label)}</a>')
    parts.append("</nav>")
    return "".join(parts)


def _context_bar(nav: "NavContext") -> str:
    """Breadcrumb + drift chip + Request-rebuild button. The chip carries the SERVER-rendered published
    HEAD; its served-build id + current|behind verdict are filled browser-side by the context-bar
    script (same-origin /data/build.json fetch — the serve-panel pattern, zero new gateway privileges).
    data-published-head lets that script compare and flip the chip current/behind."""
    if nav.published_available and nav.published_head:
        head_code = f'<code>{_esc(nav.published_head)}</code>'
        pub_attr = _esc(nav.published_head)
    else:
        head_code = '<code>unavailable</code>'
        pub_attr = ""
    # The chip starts neutral; the external script adds .current/.behind + the served build id once
    # /data/build.json loads. It DEGRADES to "serving …" (server can't read site-data — no mount).
    chip = (
        f'<span class="chip" id="drift-chip" data-published-head="{pub_attr}">'
        '<span class="dot"></span>'
        '<span id="drift-serving">serving <code id="drift-build">…</code></span>'
        '<span class="k">·</span>'
        f'<span>published HEAD {head_code}</span>'
        '</span>'
    )
    rebuild = ""
    if nav.show_rebuild:
        rebuild = (
            '<form class="act" method="post" action="/gateway/curator/rebuild" '
            'data-confirm="Request a rebuild on the next reconcile tick?" style="margin:0">'
            f'<input type="hidden" name="{CSRF_FIELD}" value="{_esc(nav.csrf)}">'
            '<button class="b-accent" type="submit" style="padding:.3rem .8rem;font-size:.8rem">'
            'Request rebuild</button></form>'
        )
    return (
        '<div class="ctxbar">'
        f'<div class="crumb">{nav.crumb}</div>'
        '<div class="spacer"></div>'
        f'{chip}{rebuild}'
        '</div>'
    )


def _shell(title: str, body: str, *, nav: "NavContext", wide: bool = True) -> str:
    """Wrap a page body in the Stage-1 nav shell: left rail + context bar + main content. The external
    context-bar script (drift chip served-build half) loads at the tail, joining ui.js. Chrome-less
    pages (login, terminal confirms) use _page instead.

    `wide` is WIDE-BY-DEFAULT (C43 FR2-1 owner ruling, 2026-07-11: "all the curator pages should be
    like the surveys-stations page — full width, intuitive"). Every shelled working page fills the
    viewport; a page that wants the centred reading measure passes wide=False (none do today — the
    only narrow survivors are the login page and the terminal confirm pages, which are chrome-less
    _page users). Pages that want a comfortable FORM measure inside the wide page cap the field column
    locally (e.g. the Metadata TOC form, the uploader create form) rather than narrowing the shell."""
    return (
        _head(title)
        + '<div class="shell">'
        + _rail_html(nav.active)
        + '<div class="main">'
        + _context_bar(nav)
        + ('<div class="wrap wide">' if wide else '<div class="wrap">') + body + '</div>'
        + '</div></div>'
        + '<script src="/gateway/curator/context-bar.js" defer></script>'
        + _TAIL
    )


def render_login(*, error: str = "") -> str:
    err = f'<p class="sub" style="color:{_PALETTE["bad"]}">{_esc(error)}</p>' if error else ""
    body = (
        '<h1>Curator sign in</h1>'
        '<p class="sub">Enter your curator key. This is separate from the submission key.</p>'
        f'{err}'
        '<div class="panel"><form method="post" action="/gateway/curator/login">'
        '<p><input type="password" name="curator_key" placeholder="curator key" autofocus '
        'autocomplete="off"></p>'
        '<p><button class="b-accent" type="submit">Sign in</button></p>'
        '</form></div>'
    )
    return _page("AusMT curator sign in", body)


def _state_badge(state: str) -> str:
    colour = _STATE_COLOUR.get(state, _PALETTE["muted"])
    return f'<span class="badge" style="background:{colour}">{_esc(state)}</span>'


def render_queue(*, curator_name: str, rows: list, csrf_token: str,
                 nav: "NavContext | None" = None) -> str:
    """The review queue (C43 FR2-1: purely the queue). The inline serve-state panel was REMOVED here
    by owner ruling (2026-07-11, ratified): the dedicated /gateway/curator/serve screen + the
    ever-present drift chip in the context bar own the served-vs-published job now — a second copy on
    the queue page was redundant. Full width via the wide-by-default shell; the table breathes."""
    if rows:
        trs = []
        for r in rows:
            warn_count = r.get("warn_count", 0)
            trs.append(
                "<tr>"
                f'<td><a href="/gateway/curator/submission/{_esc(r["id"])}">{_esc(r["id"][:12])}</a></td>'
                f'<td>{_esc(r.get("slug") or "-")}</td>'
                f'<td>{_esc(r.get("submitter_name") or "-")}</td>'
                f'<td>{_esc(warn_count)}</td>'
                f'<td>{_state_badge(r["state"])}</td>'
                f'<td class="k">{_esc(r.get("updated_utc") or "")}</td>'
                "</tr>"
            )
        table = ("<table><tr><th>ID</th><th>Slug</th><th>Submitter</th><th>Warnings</th>"
                 "<th>State</th><th>Updated</th></tr>" + "".join(trs) + "</table>")
    else:
        table = '<p class="sub">Nothing awaiting review.</p>'
    logout = (
        '<form class="act" method="post" action="/gateway/curator/logout">'
        f'<input type="hidden" name="{CSRF_FIELD}" value="{_esc(csrf_token)}">'
        '<button class="b-bad" type="submit">Sign out</button></form>'
    )
    body = (
        f'<h1>Review queue</h1>'
        f'<p class="sub">Signed in as curator:{_esc(curator_name)} · '
        '<a href="/gateway/curator/quarantine">quarantined submissions</a> '
        f'{logout}</p>'
        f'<div class="panel">{table}</div>'
    )
    if nav is not None:
        return _shell("AusMT curator queue", body, nav=nav)
    return _page("AusMT curator queue", body)


# ---- C40 serve-state panel -------------------------------------------------------------------
# The published-vs-served view + the zero-argument "request rebuild" button. Two data sources:
#   SERVER-SIDE (passed in): surveys-live HEAD (via the publish git seam), the reconcile-status.json
#     contents, and whether a rebuild.request is pending — all from mounts the gateway already has.
#   BROWSER-SIDE (fetched by the inline JS below): /data/build.json + /data/build_report.json,
#     same-origin from Caddy (the gateway server has NO site-data mount — design §3). The JS renders
#     the served build id + source_commit (highlighted when it differs from the published HEAD the
#     server passed in) and the per-survey build_report table with an expandable detail row.
# Dependency-free vanilla JS, matching the rest of the curator UI (no framework, no CDN).

_ACTION_COLOUR = {
    "rebuilt": _PALETTE["ok"], "noop": _PALETTE["muted"], "failed": _PALETTE["bad"],
    "sync_failed": _PALETTE["bad"],
    # C43 S2b-i ops-guards render gap (incident-backed): untracked_blocked is a REFUSED rebuild that
    # needs an operator — render it RED, not defaulted to muted, and surface its log_tail (the
    # offending-dir list reconcile wrote as the detail). S2b-ii adds the pause/pinned states.
    "untracked_blocked": _PALETTE["bad"],
    "paused": _PALETTE["warn"], "pinned": _PALETTE["warn"],
}

# Actions whose log_tail/detail carries an operator-actionable explanation the status block must show.
_ACTION_SHOW_TAIL = ("failed", "sync_failed", "untracked_blocked", "paused", "pinned")


def _reconcile_status_block(status: dict | None) -> str:
    """Render the last reconcile outcome from reconcile-status.json. None => the agent is not
    installed yet (a hint, not an error). A `failed`/`sync_failed` shows the log tail so a shell-less
    curator sees WHY without console access (design §2 — the NCI no-console requirement)."""
    if status is None:
        return ('<p class="sub">No reconcile status yet — the host reconcile agent is not installed, '
                'its status file is unreadable by the gateway (permissions on gateway/state — see the '
                'deploy README ownership prep), '
                'or has not run a pass. See the deploy README "Serve reconcile".</p>')
    action = str(status.get("action") or "unknown")
    colour = _ACTION_COLOUR.get(action, _PALETTE["muted"])
    rows = [
        f'<tr><td class="k">Last reconcile</td><td>{_esc(status.get("last_run") or "-")}</td></tr>',
        f'<tr><td class="k">Outcome</td>'
        f'<td><span class="badge" style="background:{colour}">{_esc(action)}</span></td></tr>',
        f'<tr><td class="k">surveys-live HEAD (at that run)</td><td>{_esc(status.get("head") or "-")}</td></tr>',
        f'<tr><td class="k">Built source_commit</td><td>{_esc(status.get("built") or "-")}</td></tr>',
        f'<tr><td class="k">Build id</td><td>{_esc(status.get("build_id") or "-")}</td></tr>',
    ]
    if status.get("log_file"):
        rows.append(f'<tr><td class="k">Log file</td><td>{_esc(status.get("log_file"))}</td></tr>')
    table = "<table>" + "".join(rows) + "</table>"
    tail = ""
    if action in _ACTION_SHOW_TAIL and status.get("log_tail"):
        # untracked_blocked/failed/sync_failed are hard states (red); paused/pinned are intentional
        # (amber) — either way the detail is operator-actionable and must be shown, not buried.
        hard = action in ("failed", "sync_failed", "untracked_blocked")
        colour = _PALETTE["bad"] if hard else _PALETTE["warn"]
        lead = ("Last build did not serve — old data still live. Detail:" if hard
                else "Auto-rebuild is being held. Detail:")
        tail = (f'<p class="sub" style="color:{colour};font-weight:600">{lead}</p>'
                f'<pre>{_esc(status.get("log_tail"))}</pre>')
    return table + tail


def render_serve_panel(*, published_head, published_available: bool, status: dict | None,
                       pending: bool, csrf_token: str) -> str:
    """The full serve-state panel for the queue page. `published_head` is the surveys-live short HEAD
    the server read (or None); `published_available` is False when git could not be run (show
    "unavailable", never error). `status` is the parsed reconcile-status.json (or None). `pending`
    is True when a rebuild.request is waiting. The served-build half is filled in by the browser JS."""
    if published_available and published_head:
        head_html = f'<code id="published-head">{_esc(published_head)}</code>'
    else:
        head_html = '<code id="published-head" data-unavailable="1">unavailable</code>'
    pending_html = ""
    if pending:
        pending_html = (f'<p class="sub" style="color:{_PALETTE["warn"]};font-weight:600">'
                        'Rebuild requested — pending the next reconcile tick.</p>')
    csrf = f'<input type="hidden" name="{CSRF_FIELD}" value="{_esc(csrf_token)}">'
    # The button posts to the zero-argument rebuild route. The accidental-click confirm rides the
    # shared data-confirm delegation in CURATOR_UI_JS — never an inline handler: the Caddyfile's
    # strictPages CSP (script-src 'self') blocks inline handlers, so one here silently never runs
    # (the 2026-07-08 first-install symptom — the form submitted with no confirm). The server is
    # idempotent regardless, so a blocked confirm was never a safety hole, only a missing courtesy.
    button = (
        f'<form class="act" method="post" action="/gateway/curator/rebuild" '
        'data-confirm="Request a rebuild on the next reconcile tick?">'
        f'{csrf}'
        '<button class="b-accent" type="submit">'
        'Request rebuild</button></form>'
    )
    # data-published-head lets the JS compare the served source_commit against the published HEAD and
    # highlight a mismatch (published but not yet served).
    published_attr = _esc(published_head) if (published_available and published_head) else ""
    body = (
        '<div class="panel" id="serve-state" '
        f'data-published-head="{published_attr}">'
        '<h2>Serve state</h2>'
        f'<p class="sub">Published (surveys-live HEAD): {head_html}. The served build below is fetched '
        'from the live site; if its source commit differs from the published HEAD, a publish has not '
        'yet been rebuilt into the served corpus.</p>'
        f'{pending_html}'
        '<h2>Served build</h2>'
        '<div id="served-build"><p class="sub">Loading served build…</p></div>'
        '<h2>Per-survey build report</h2>'
        '<div id="build-report"><p class="sub">Loading build report…</p></div>'
        '<h2>Last reconcile</h2>'
        f'{_reconcile_status_block(status)}'
        f'<p style="margin-top:1rem">{button}</p>'
        '</div>'
        # EXTERNAL script, same-origin — NOT an inline script block. The Caddyfile serves every
        # /gateway/* page under the strictPages CSP (script-src 'self', no 'unsafe-inline'), which
        # BLOCKS inline scripts entirely: the first install (2026-07-08) shipped this panel's JS
        # inline and the browser never ran it ("Loading…" forever). 'self' allows a same-origin
        # script URL, so the JS is served by the session-gated /gateway/curator/serve-state.js route.
        '<script src="/gateway/curator/serve-state.js" defer></script>'
    )
    return body


# Vanilla JS: fetch the served build metadata SAME-ORIGIN (Caddy serves /data/* from the built
# current/) and render it. Graceful on a 404 (no build yet) and on a fetch/parse error. Dependency-
# free; every value is inserted via textContent (never innerHTML) so submitter-derived report strings
# cannot inject markup into the curator page.
#
# DELIVERY (CSP): this constant is RAW JS (no script-tag wrapper), served as its own same-origin
# document by GET /gateway/curator/serve-state.js — inline delivery is dead under the strictPages
# script-src 'self' policy (see render note above). Keep ALL panel behaviour in here (including the
# button confirm): no inline scripts, no on*= attributes anywhere on the curator pages — a rendered-
# page test pins that invariant.
SERVE_PANEL_JS = """
(function () {
  var panel = document.getElementById('serve-state');
  if (!panel) return;
  var publishedHead = panel.getAttribute('data-published-head') || '';
  // (The rebuild button's confirm rides the shared data-confirm delegation in ui.js.)

  // S2a-5 DISPLAY shortener (mirrors gateway/builddisplay.py — the authoritative, pinned spec):
  // "<engine>-<source>-<iso>" -> "<source short> · HH:MM UTC"; an unrecognised shape falls back to
  // the id VERBATIM (never hide information). The full id rides the <code> title attribute (hover).
  function shortBuildId(id) {
    if (!id) return '';
    var s = String(id);
    var m = s.match(/^([0-9a-fA-F]+|unknown)-([0-9a-fA-F]+|unknown)-(\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}[0-9.]*(?:Z|[+-]\\d{2}:?\\d{2})?)$/);
    if (!m) return s;
    var source = m[2];
    var short = (source === 'unknown') ? 'unknown' : source.slice(0, 7);
    var hhmm = m[3].slice(11, 16);
    return short + ' \\u00b7 ' + hhmm + ' UTC';
  }

  function el(tag, text, cls) {
    var e = document.createElement(tag);
    if (text != null) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  }
  function fetchJson(url) {
    return fetch(url, {credentials: 'omit', cache: 'no-store'}).then(function (r) {
      if (r.status === 404) return {__missing: true};
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }

  // ---- served build.json ----
  fetchJson('/data/build.json').then(function (b) {
    var box = document.getElementById('served-build');
    box.textContent = '';
    if (b.__missing) {
      box.appendChild(el('p', 'No build has been served yet (/data/build.json is 404).', 'sub'));
      return;
    }
    var tbl = el('table');
    function row(k, v, highlight, title) {
      var tr = el('tr');
      var tdk = el('td', k, 'k');
      var tdv = el('td');
      var code = el('code', v == null ? '-' : String(v));
      if (highlight) { code.style.background = 'rgba(217,162,59,.25)'; code.style.padding = '0 .3rem'; }
      if (title) code.setAttribute('title', title);   // full value on hover (DOM property, not markup)
      tdv.appendChild(code);
      tr.appendChild(tdk); tr.appendChild(tdv); return tr;
    }
    var served = b.source_commit;
    // Highlight when the served source_commit differs from the published HEAD (prefix-tolerant: a
    // 7-char stored short vs an 8-char HEAD of the same commit is NOT a mismatch).
    var mismatch = false;
    if (publishedHead && served) {
      mismatch = !(publishedHead.indexOf(served) === 0 || served.indexOf(publishedHead) === 0);
    }
    // S2a-5: the Served-build card shows the SHORT display id with the full id on hover (title).
    tbl.appendChild(row('Build id', b.build_id ? shortBuildId(b.build_id) : null, false, b.build_id));
    tbl.appendChild(row('Engine commit', b.engine_commit));
    tbl.appendChild(row('Served source_commit', served, mismatch));
    box.appendChild(tbl);
    if (mismatch) {
      box.appendChild(el('p',
        'The served corpus was built from ' + served + ' but the published HEAD is ' + publishedHead +
        ' — a publish is committed but not yet rebuilt into the live site.', 'sub'));
    }
  }).catch(function (e) {
    var box = document.getElementById('served-build');
    box.textContent = '';
    box.appendChild(el('p', 'Could not load /data/build.json: ' + e.message, 'sub'));
  });

  // ---- per-survey build_report.json ----
  fetchJson('/data/build_report.json').then(function (rep) {
    var box = document.getElementById('build-report');
    box.textContent = '';
    if (rep.__missing) {
      box.appendChild(el('p', 'No build report yet (/data/build_report.json is 404).', 'sub'));
      return;
    }
    var surveys = rep.surveys || {};
    var slugs = Object.keys(surveys).sort();
    if (!slugs.length) {
      box.appendChild(el('p', 'The build report lists no surveys.', 'sub'));
      return;
    }
    var tbl = el('table');
    var head = el('tr');
    ['Survey', 'Stations', 'Warnings', 'Conditioning', 'Cache hit/miss', 'Duration (s)', ''].forEach(
      function (h) { head.appendChild(el('th', h)); });
    tbl.appendChild(head);
    slugs.forEach(function (slug, i) {
      var s = surveys[slug] || {};
      var cache = s.cache || {};
      var warnCount = (s.warnings || []).length;
      var condCount = (s.conditioning || []).length;
      var tr = el('tr');
      tr.appendChild(el('td', slug));
      tr.appendChild(el('td', String(s.stations_built != null ? s.stations_built : '-')));
      tr.appendChild(el('td', String(warnCount)));
      tr.appendChild(el('td', String(condCount)));
      tr.appendChild(el('td', (cache.hits != null ? cache.hits : '-') + ' / ' +
        (cache.misses != null ? cache.misses : '-')));
      tr.appendChild(el('td', String(s.duration_seconds != null ? s.duration_seconds : '-')));
      var tdBtn = el('td');
      var hasDetail = warnCount || condCount || (s.stations_dropped || []).length;
      if (hasDetail) {
        var btn = el('button', 'details');
        btn.type = 'button';
        btn.className = 'b-accent';
        btn.style.padding = '.15rem .55rem';
        btn.style.fontSize = '.75rem';
        var detailId = 'detail-' + i;
        btn.setAttribute('data-target', detailId);
        btn.addEventListener('click', function () {
          var d = document.getElementById(detailId);
          if (d) d.style.display = (d.style.display === 'none' ? '' : 'none');
        });
        tdBtn.appendChild(btn);
      }
      tr.appendChild(tdBtn);
      tbl.appendChild(tr);

      if (hasDetail) {
        var dtr = el('tr');
        dtr.id = 'detail-' + i;
        dtr.style.display = 'none';
        var dtd = el('td');
        dtd.colSpan = 7;
        (s.stations_dropped || []).forEach(function (sd) {
          dtd.appendChild(el('p', 'dropped: ' + sd.station + ' — ' + sd.reason, 'sub'));
        });
        (s.warnings || []).forEach(function (w) {
          dtd.appendChild(el('p', 'warning: ' + w, 'sub'));
        });
        (s.conditioning || []).forEach(function (c) {
          var line = 'conditioning (' + c.count + '): ' + c.note;
          // .length guards: an EMPTY array is truthy in JS — a report from an older engine (or a
          // future regression) shipping stations/except as [] must render nothing, not "[all except: ]".
          if (c.stations && c.stations.length) line += '  [stations: ' + c.stations.join(', ') + ']';
          else if (c.except && c.except.length) line += '  [all except: ' + c.except.join(', ') + ']';
          dtd.appendChild(el('p', line, 'sub'));
        });
        dtr.appendChild(dtd);
        tbl.appendChild(dtr);
      }
    });
    box.appendChild(tbl);
  }).catch(function (e) {
    var box = document.getElementById('build-report');
    box.textContent = '';
    box.appendChild(el('p', 'Could not load /data/build_report.json: ' + e.message, 'sub'));
  });
})();
"""


# ---- C43 S2b-i: serve-state screen + operations floor ------------------------------------------
# The serve panel promoted to a first-class screen (record D8/D15): the existing published/served
# blocks (render_serve_panel) + a loud reconcile SYNC strip + a four-card operations FLOOR + the
# retained-builds and backup-snapshots tables + a build-detail view. Everything here is READ-ONLY —
# NO privileged action is rendered (rollback/restore/update/backup/pause are Stage 2b-ii; omitted,
# never disabled placeholders). The floor facts come from ops-status.json read SERVER-side
# (serve_state.read_ops_status), so the floor is pure server-rendered HTML: no new JS, nothing for the
# strictPages CSP (script-src 'self') to block. Missing/stale ops-status.json => every dependent card
# renders an explicit STALE state (never last-known-good silently).

_OPS_KIND_COLOUR = {"ok": _PALETTE["ok"], "warn": _PALETTE["warn"], "bad": _PALETTE["bad"],
                    "muted": _PALETTE["muted"]}


def _pill(label: str, kind: str) -> str:
    colour = _OPS_KIND_COLOUR.get(kind, _PALETTE["muted"])
    return f'<span class="pill" style="background:{colour}">{_esc(label)}</span>'


def _fact(k: str, v: str) -> str:
    """One fact row — the KEY is escaped; the VALUE is trusted HTML the caller has already escaped
    (values may carry a <code>/<span> wrapper). Callers must _esc any data before it reaches here."""
    return f'<div class="fact"><span class="fk">{_esc(k)}</span><span class="fv">{v}</span></div>'


def _ops_card(title: str, pill_html: str, body: str) -> str:
    return f'<div class="opscard"><h3>{_esc(title)}{pill_html}</h3>{body}</div>'


def _stale_card(title: str, generated_at, note: str) -> str:
    gen = _esc(generated_at) if generated_at else "never"
    body = (f'<p class="stale">STALE — no fresh data</p>'
            f'<p class="opsnote">{_esc(note)} Last ops-status.json: {gen}.</p>')
    return _ops_card(title, _pill("stale", "warn"), body)


def _stale_note(what: str, generated_at) -> str:
    gen = _esc(generated_at) if generated_at else "never"
    return (f'<p class="stale">STALE — {_esc(what)} unavailable.</p>'
            f'<p class="opsnote">ops-status.json is missing or older than ~2 timer periods '
            f'(last: {gen}). Not showing last-known-good.</p>')


def _backups_card(ops: dict) -> str:
    b = ops.get("backups") or {}
    newest = b.get("newest")
    age = b.get("age_hours")
    maxh = b.get("max_hours") or 26
    count = b.get("count")
    systemd_failed = bool(b.get("systemd_failed"))
    drill = b.get("drill") if isinstance(b.get("drill"), dict) else None
    over = isinstance(age, (int, float)) and age > maxh
    kind = "bad" if systemd_failed else ("warn" if (over or not newest) else "ok")
    label = "FAILED" if systemd_failed else ("overdue" if over else ("none" if not newest else "ok"))
    facts = [
        _fact("Newest snapshot", f'<span class="dt">{_esc(newest)}</span>' if newest else "— none yet"),
        _fact("Age", f"{_esc(age)} h (threshold {_esc(maxh)} h)" if age is not None else "—"),
        _fact("Retained", _esc(count) if count is not None else "—"),
        _fact("Last drill", (f'{_esc(drill.get("verdict"))} ({_esc(drill.get("at"))})' if drill
                             else "no drill recorded")),
        _fact("Backup unit", "FAILED" if systemd_failed else "ok"),
    ]
    return _ops_card("Backups", _pill(label, kind), "".join(facts))


def _alerts_card(ops: dict) -> str:
    a = ops.get("alerts") or {}
    installed = bool(a.get("installed"))
    checks_ok = bool(a.get("checks_ok"))
    if not installed:
        body = (_fact("Dead-man ping", "not installed")
                + '<p class="opsnote">The external dead-man monitor is not wired yet — install it so a '
                  'silent stall (crash-loop, full disk, stale backup) reaches the curator. See deploy '
                  'README "Alerting".</p>')
        return _ops_card("Alerts", _pill("not installed", "muted"), body)
    kind = "ok" if checks_ok else "warn"
    body = (_fact("Dead-man ping", "installed")
            + _fact("Box self-checks", "passing" if checks_ok else "FAILING")
            + '<p class="opsnote">The beat lands at the external monitor (it routes the alert email); '
              "this shows whether it is wired and whether the box's own checks pass right now.</p>")
    return _ops_card("Alerts", _pill("ok" if checks_ok else "check", kind), body)


def _box_card(ops: dict) -> str:
    box = ops.get("box") or {}
    uptime = box.get("uptime")
    disk = box.get("disk_pct")
    disk_max = box.get("disk_max_pct") or 85
    services = box.get("services") or []
    clam = box.get("clamav_sig_age_days")
    disk_over = isinstance(disk, (int, float)) and disk > disk_max
    bad_services = [s for s in services if isinstance(s, dict)
                    and (s.get("state") != "running"
                         or (s.get("health") and s.get("health") not in ("healthy", "starting")))]
    kind = "warn" if (disk_over or bad_services) else "ok"
    if services:
        parts = []
        for s in services:
            if not isinstance(s, dict):
                continue
            st = s.get("state") or "?"
            h = s.get("health")
            ok = st == "running" and (not h or h in ("healthy", "starting"))
            txt = _esc(s.get("name")) + ": " + _esc(st) + (f"/{_esc(h)}" if h else "")
            parts.append(txt if ok else f'<span style="color:{_PALETTE["warn"]};font-weight:600">{txt}</span>')
        svc_html = "<br>".join(parts)
    else:
        svc_html = "—"
    if disk is None:
        disk_v = "—"
    else:
        disk_txt = f"{_esc(disk)}% of {_esc(disk_max)}%"
        disk_v = f'<span style="color:{_PALETTE["warn"]};font-weight:600">{disk_txt}</span>' if disk_over else disk_txt
    facts = [
        _fact("Uptime", _esc(uptime) if uptime else "—"),
        _fact("Disk", disk_v),
        _fact("Services", svc_html),
        _fact("ClamAV signatures", f"{_esc(clam)} days old" if clam is not None else "unknown"),
    ]
    return _ops_card("Box", _pill("degraded" if kind == "warn" else "ok", kind), "".join(facts))


def _freshness_row(label: str, repo: dict) -> str:
    repo = repo or {}
    sha = repo.get("sha")
    origin = repo.get("origin")
    behind = bool(repo.get("behind"))
    comparable = bool(repo.get("comparable"))
    if not sha:
        v = "unavailable (not a checkout / no HEAD)"
    elif not comparable:
        v = f'<code>{_esc(sha)}</code> — origin unknown (no fetch since last sync)'
    elif behind:
        v = (f'<code>{_esc(sha)}</code> vs origin <code>{_esc(origin)}</code> — '
             f'<span style="color:{_PALETTE["warn"]};font-weight:600">behind</span>')
    else:
        v = f'<code>{_esc(sha)}</code> — current'
    return _fact(label, v)


def _freshness_card(ops: dict) -> str:
    f = ops.get("freshness") or {}
    code = f.get("code") or {}
    sl = f.get("surveys_live") or {}
    behind = bool(code.get("behind")) or bool(sl.get("behind"))
    # "current" is EARNED, never defaulted (the 2026-07-11 incident was a lying "current" chip):
    # it requires BOTH repos to carry a comparable sha. Unavailable/unparseable freshness — a
    # broken checkout, or alert.sh/gateway schema skew — pills "unknown" in warn colour, because
    # a floor that cannot see the repos must never claim they are current.
    known = all(bool(r.get("sha")) and bool(r.get("comparable")) for r in (code, sl))
    if behind:
        pill, kind = "behind", "warn"
    elif known:
        pill, kind = "current", "ok"
    else:
        pill, kind = "unknown", "warn"
    body = (_freshness_row("Code checkout", code) + _freshness_row("surveys-live", sl)
            + '<p class="opsnote">Local HEAD vs the last successfully-fetched origin; a fetch that '
              'cannot reach origin surfaces in the reconcile sync state above, not here (record D15).</p>')
    return _ops_card("Freshness (vs origin)", _pill(pill, kind), body)


def _sync_strip(status, ops, ops_stale: bool) -> str:
    """The reconcile SYNC state, surfaced LOUDLY (record D8/D15). Driven by the FRESH
    reconcile-status.json `action` (NOT gated behind ops-status staleness — the incident was a
    sync_failed that hid for 4 h), enriched with the sync_failed streak from ops-status when it is
    fresh. A sync_failed is a first-class red band; a build `failed` is amber; noop/rebuilt are calm."""
    action = status.get("action") if isinstance(status, dict) else None
    last_run = status.get("last_run") if isinstance(status, dict) else None
    lr = _esc(last_run) if last_run else "?"
    streak_txt = ""
    if not ops_stale and isinstance(ops, dict):
        rec = ops.get("reconcile") or {}
        if rec.get("sync_failed"):
            n = rec.get("sync_failed_streak")
            since = rec.get("sync_failed_since")
            bits = []
            if since:
                bits.append(f"failing since {_esc(since)}")
            if isinstance(n, int) and n > 1:
                bits.append(f"{n} consecutive ticks")
            if bits:
                streak_txt = " — " + ", ".join(bits)
    if action == "sync_failed":
        return (f'<div class="opsband" style="background:{_PALETTE["bad"]};color:{_PALETTE["bg"]};font-weight:600">'
                f'surveys-live SYNC FAILED — the box could not fast-forward from origin; the served and '
                f'published data may be behind GitHub{streak_txt}. (last reconcile {lr})</div>')
    if action == "failed":
        return (f'<div class="opsband" style="background:{_PALETTE["warn"]};color:{_PALETTE["bg"]};font-weight:600">'
                f'Last rebuild FAILED — the previous build is still serving (fail-closed). See "Last '
                f'reconcile" above for the log tail. (last reconcile {lr})</div>')
    if action in ("noop", "rebuilt"):
        return (f'<div class="opsband" style="background:{_PALETTE["panel"]}">Reconcile sync: '
                f'<b>{_esc(action)}</b> at {lr} — surveys-live in sync with origin as of the last tick.</div>')
    if action:
        return (f'<div class="opsband" style="background:{_PALETTE["panel"]}">Last reconcile: '
                f'{_esc(action)} at {lr}.</div>')
    return (f'<div class="opsband" style="background:{_PALETTE["panel"]}">No reconcile status yet — '
            'the reconcile timer is not installed or has not run a pass.</div>')


def _builds_table(ops, ops_stale: bool, generated_at, *, csrf_token: str = "",
                  actions: bool = False) -> str:
    if ops is None or ops_stale:
        return _stale_note("build inventory", generated_at)
    builds = ops.get("builds") or []
    if not builds:
        return '<p class="sub">No retained builds reported by the box.</p>'
    rows = []
    for b in builds:
        if not isinstance(b, dict):
            continue
        d = b.get("dir") or ""
        bid = b.get("build_id")
        # The build dir name (a sortable UTC timestamp) is the row label; the full opaque build_id
        # rides the title (hover). The detail route matches this dir against the SAME ops-status
        # inventory server-side — it never opens a file by this name, so an unknown ref just 404s.
        href = "/gateway/curator/serve/build/" + _esc(d)
        is_serving = bool(b.get("serving"))
        serving = f'<span class="pill" style="background:{_PALETTE["ok"]}">serving</span>' if is_serving else ""
        # C43 S2b-ii: "serve this build…" = rollback (a link to the typed-id confirm page). The
        # currently-serving build offers no rollback-to-itself. rollback is a repoint, never a rebuild.
        act = ""
        if actions and d and not is_serving:
            act = f' · <a href="/gateway/curator/serve/rollback/{_esc(d)}">serve this build…</a>'
        rows.append(
            "<tr>"
            f'<td><a href="{href}"><code title="{_esc(bid) if bid else ""}">{_esc(d)}</code></a> {serving}</td>'
            f'<td>{_esc(b.get("engine_commit") or "-")}</td>'
            f'<td>{_esc(b.get("source_commit") or "-")}</td>'
            f'<td>{_esc(b.get("stations")) if b.get("stations") is not None else "-"}</td>'
            f'<td><a href="{href}">detail</a>{act}</td>'
            "</tr>")
    return ('<table><tr><th>Build (dir)</th><th>Engine</th><th>Source</th><th>Stations</th><th></th></tr>'
            + "".join(rows) + "</table>")


def _backups_table(ops, ops_stale: bool, generated_at, *, actions: bool = False) -> str:
    if ops is None or ops_stale:
        return _stale_note("backup snapshots", generated_at)
    b = ops.get("backups") or {}
    snaps = b.get("snapshots") or []
    if not snaps and b.get("newest"):   # tolerate an older writer that carried only the newest
        snaps = [{"name": b.get("newest"), "age_hours": b.get("age_hours")}]
    if not snaps:
        return '<p class="sub">No backup snapshots reported by the box.</p>'
    rows = []
    for s in snaps:
        if not isinstance(s, dict):
            continue
        age = s.get("age_hours")
        name = s.get("name") or ""
        # C43 S2b-ii: guarded restore (a link to the typed-id + TOTP confirm page). Drill-first,
        # destructive — the confirm page carries the disclosure + the second factor.
        act = ""
        if actions and name:
            act = f'<td><a href="/gateway/curator/serve/restore/{_esc(name)}">restore…</a></td>'
        else:
            act = "<td></td>" if actions else ""
        rows.append(f'<tr><td><span class="dt">{_esc(name)}</span></td>'
                    f'<td>{(_esc(age) + " h") if age is not None else "-"}</td>{act}</tr>')
    head = ('<table><tr><th>Snapshot</th><th>Age</th>'
            + ("<th></th>" if actions else "") + "</tr>")
    return head + "".join(rows) + "</table>"


# ---- C43 S2b-ii: privileged ACTION controls on the serve screen (record D8/D9) ----------------
# The D8 buttons. All post to session+CSRF-gated routes that write an INTENT the host actions agent
# executes (the gateway gains no shell — C40). Single-flight (D9.3): a pending intent of a kind
# disables its button and shows the pending state. The destructive/id-carrying ones (rollback,
# restore) are their own confirmation PAGES (typed id; restore also a TOTP code). Everything here
# rides the shared data-confirm delegation in CURATOR_UI_JS — NO inline handler (strictPages CSP).

def _act_form(route: str, label: str, csrf: str, *, cls: str = "b-accent", confirm: str = "",
              disabled: bool = False, title: str = "") -> str:
    """One action <form> posting to `route`. When disabled (single-flight pending), the button is
    inert and titled with why. The confirm rides data-confirm (delegated in ui.js) — never inline JS."""
    dc = f' data-confirm="{_esc(confirm)}"' if (confirm and not disabled) else ""
    dis = " disabled" if disabled else ""
    ttl = f' title="{_esc(title)}"' if title else ""
    return (f'<form class="act" method="post" action="{route}"{dc} '
            'style="display:inline-block;margin:.2rem .4rem .2rem 0">'
            f'{csrf}<button class="{cls}" type="submit"{dis}{ttl}>{_esc(label)}</button></form>')


def _serve_actions_panel(*, csrf_token: str, pending_intents: dict, paused: bool,
                         rollback_pin: dict | None, audit_tail: list) -> str:
    """The D8 actions box: Update / Snapshot / Force-full-rebuild / Pause-or-Resume, plus the pending
    intents banner and the read-only audit tail. Per-build rollback + per-snapshot restore live on
    their rows (below) as links to their own confirm pages."""
    csrf = f'<input type="hidden" name="{CSRF_FIELD}" value="{_esc(csrf_token)}">'
    pi = pending_intents or {}

    def _btn(kind, route, label, confirm, cls="b-accent"):
        p = pi.get(kind)
        if p:
            by = p.get("requested_by") or "?"
            return _act_form(route, f"{label} (pending)", csrf, cls=cls, disabled=True,
                             title=f"already requested by {by} — waiting for the host agent")
        return _act_form(route, label, csrf, cls=cls, confirm=confirm)

    update_btn = _btn("update", "/gateway/curator/serve/update", "Update box…",
                      "Update the box now? Runs git pull --ff-only + docker compose pull + up -d "
                      "(deploys what main already published). This is the bounded C40 exception.")
    snapshot_btn = _btn("backup", "/gateway/curator/serve/snapshot", "Snapshot now",
                        "Take an on-box DB snapshot now?", cls="b-ok")
    # Force full rebuild rides rebuild.request (full flag), not the single-flight intent set — it is
    # idempotent like the plain rebuild, so it is never disabled.
    fullrebuild_btn = _act_form(
        "/gateway/curator/serve/rebuild-full", "Force full rebuild…", csrf, cls="b-warn",
        confirm="Force a FULL rebuild (ignore the build cache, recompute everything) on the next "
                "reconcile tick? Slower, but bypasses a suspect cache.")
    if paused:
        pause_btn = _act_form("/gateway/curator/serve/resume", "Resume auto-rebuild", csrf, cls="b-ok",
                              confirm="Resume automatic rebuilds now?")
    else:
        pause_btn = _act_form("/gateway/curator/serve/pause", "Pause auto-rebuild", csrf, cls="b-warn",
                              confirm="Pause automatic rebuilds during a multi-edit session? It "
                                      "auto-expires after 6 h; Resume to lift it sooner.")

    # Pending banner (single-flight visibility).
    banner = ""
    if pi:
        items = ", ".join(f'{_esc(k)} (by {_esc(v.get("requested_by") or "?")})' for k, v in pi.items())
        banner = (f'<p class="opsnote" style="color:{_PALETTE["warn"]};font-weight:600">'
                  f'Pending host action(s): {items} — waiting for the actions agent (runs every ~2 min). '
                  f'The matching button is disabled until it lands.</p>')
    pause_note = ""
    if paused:
        pause_note = ('<p class="opsnote">Auto-rebuild is PAUSED — drift is not being rebuilt. It '
                      'auto-expires after 6 h; a pause that persists past 24 h raises an alert.</p>')
    pin_note = ""
    if rollback_pin:
        pb = rollback_pin.get("pinned_build") or "?"
        pin_note = (f'<p class="opsnote" style="color:{_PALETTE["warn"]};font-weight:600">'
                    f'A rollback pin is standing — serving builds/{_esc(pb)}; reconcile will NOT '
                    f'auto-rebuild until you Force/Request a rebuild to move forward.</p>')

    audit_html = _audit_tail_block(audit_tail)
    return (
        '<div class="panel">'
        '<h2>Actions</h2>'
        '<p class="sub">Privileged host actions — each writes an intent the on-box actions agent '
        'executes (the gateway itself has no shell; every action is audited below).</p>'
        f'{banner}{pause_note}{pin_note}'
        f'<div style="margin:.5rem 0">{update_btn}{snapshot_btn}{fullrebuild_btn}{pause_btn}</div>'
        f'{audit_html}'
        '</div>'
    )


def _audit_tail_block(audit_tail: list) -> str:
    """Read-only render of the host actions-audit.log tail (who/what/when/outcome). Every line is
    host-generated in a fixed shape but still _esc'd — the audit log is display data, not markup."""
    lines = [ln for ln in (audit_tail or []) if isinstance(ln, str) and ln.strip()]
    if not lines:
        return ('<h3>Action audit</h3><p class="sub">No privileged actions recorded yet '
                '(actions-audit.log is empty or the actions agent has not run).</p>')
    # Newest last in the file; show newest FIRST for the reader.
    body = "\n".join(_esc(ln) for ln in reversed(lines))
    return (f'<h3>Action audit <span class="sub">(newest first)</span></h3>'
            f'<pre class="audittail">{body}</pre>')


def render_serve_page(*, published_head, published_available: bool, status, pending: bool,
                      csrf_token: str, ops, ops_stale: bool, nav: "NavContext",
                      pending_intents: dict | None = None, paused: bool = False,
                      rollback_pin: dict | None = None, audit_tail: list | None = None) -> str:
    """The first-class serve-state screen (record D8/D15). The existing serve panel (published HEAD,
    served build + currency, per-survey build report, last reconcile — render_serve_panel) plus the
    reconcile SYNC strip, the four-card operations FLOOR, and the retained-builds + backup-snapshots
    tables. Read-only: no privileged action control is rendered. `ops` is the parsed ops-status.json
    (or None); `ops_stale` is True when it is missing OR older than ~2 timer periods — either flips
    every dependent surface to an explicit STALE state."""
    panel = render_serve_panel(published_head=published_head, published_available=published_available,
                               status=status, pending=pending, csrf_token=csrf_token)
    generated_at = ops.get("generated_at") if isinstance(ops, dict) else None
    sync = _sync_strip(status, ops, ops_stale)
    stale = ops is None or ops_stale
    if stale:
        floor = ('<div class="ops">'
                 + _stale_card("Backups", generated_at, "Backup state unavailable.")
                 + _stale_card("Alerts", generated_at, "Alert state unavailable.")
                 + _stale_card("Box", generated_at, "Box state unavailable.")
                 + _stale_card("Freshness (vs origin)", generated_at, "Repo freshness unavailable.")
                 + "</div>")
        stale_banner = (f'<div class="opsband" style="background:{_PALETTE["warn"]};color:{_PALETTE["bg"]};font-weight:600">'
                        f'Operations floor is STALE — ops-status.json is missing or older than ~2 timer '
                        f'periods (last: {_esc(generated_at) if generated_at else "never"}). The alert '
                        f'timer (deploy/scripts/alert.sh) may not be installed or running. Cards below '
                        f'show STALE, not last-known-good.</div>')
    else:
        floor = ('<div class="ops">'
                 + _backups_card(ops) + _alerts_card(ops) + _box_card(ops) + _freshness_card(ops)
                 + "</div>")
        stale_banner = ""
    actions = _serve_actions_panel(csrf_token=csrf_token, pending_intents=pending_intents or {},
                                   paused=paused, rollback_pin=rollback_pin, audit_tail=audit_tail or [])
    body = (
        '<h1>Serve state</h1>'
        '<p class="sub">Published vs served, the box operations floor, and the privileged host '
        'actions. Every action writes an intent the on-box agent executes (the gateway has no '
        'shell); the destructive ones (rollback, restore) require a typed confirmation.</p>'
        f'{panel}'
        '<h2>Reconcile sync</h2>'
        f'{sync}'
        f'{actions}'
        '<h2>Operations floor</h2>'
        f'{stale_banner}'
        f'{floor}'
        '<h2>Retained builds</h2>'
        f'{_builds_table(ops, ops_stale, generated_at, csrf_token=csrf_token, actions=True)}'
        '<h2>Backup snapshots</h2>'
        f'{_backups_table(ops, ops_stale, generated_at, actions=True)}'
    )
    return _shell("AusMT serve state", body, nav=nav)


def find_build(ops, build_ref: str):
    """Return the ops-status.json builds[] entry whose `dir` matches build_ref, or None. Pure lookup
    over the SERVER-read inventory — never a filesystem path build (a hostile ref just does not match
    and yields None => a 'no such build' page, never a traversal)."""
    if not isinstance(ops, dict):
        return None
    for b in ops.get("builds") or []:
        if isinstance(b, dict) and b.get("dir") == build_ref:
            return b
    return None


def render_build_detail(*, build, generated_at, log_tail, ops_stale: bool, nav: "NavContext") -> str:
    """Read-only forensics for one retained build (record D8/D15 B4): identity + the C18-A4 cache
    counters (salt_fp / write_errors / read_errors, from build_provenance.json via ops-status.json) +
    the build log tail (the newest build log the box copied into the state dir). NO 'serve this build'
    action — rollback is Stage 2b-ii."""
    back = '<p style="margin-top:1rem"><a href="/gateway/curator/serve">back to serve state</a></p>'
    if ops_stale:
        body = ('<h1>Build detail</h1>'
                f'<p class="stale">STALE — ops-status.json is missing or older than ~2 timer periods '
                f'(last: {_esc(generated_at) if generated_at else "never"}). Build forensics unavailable.</p>'
                + back)
        return _shell("AusMT build detail", body, nav=nav)
    if build is None:
        body = ('<h1>Build detail</h1>'
                '<p class="sub">No such retained build in the current inventory.</p>' + back)
        return _shell("AusMT build detail", body, nav=nav)
    cache = build.get("cache") or {}

    def cv(k):
        v = cache.get(k)
        return _esc(v) if v is not None else "—"

    idrows = [
        _fact("Build id", f'<code>{_esc(build.get("build_id") or "-")}</code>'),
        _fact("Build dir", f'<code>{_esc(build.get("dir") or "-")}</code>'),
        _fact("Engine commit", _esc(build.get("engine_commit") or "-")),
        _fact("Source commit", _esc(build.get("source_commit") or "-")),
        _fact("Stations", _esc(build.get("stations")) if build.get("stations") is not None else "-"),
        _fact("Serving", "yes" if build.get("serving") else "no"),
    ]
    cacherows = [
        _fact("Cache enabled", cv("enabled")),
        _fact("Cache mode", cv("mode")),
        _fact("Salt fingerprint (salt_fp)", f'<code>{cv("salt_fp")}</code>'),
        _fact("Write errors", cv("write_errors")),
        _fact("Read errors", cv("read_errors")),
        _fact("Hits / misses", f'{cv("hits")} / {cv("misses")}'),
    ]
    if cache.get("degenerate"):
        cacherows.append(_fact("Degenerate", f'{cv("degenerate")} ({cv("reason")})'))
    log_block = (f'<pre>{_esc(log_tail)}</pre>') if log_tail else '<p class="sub">No build log tail available.</p>'
    body = (
        '<h1>Build detail</h1>'
        '<p class="sub">Read-only forensics for a retained build. The C18-A4 cache counters come from '
        "build_provenance.json (via ops-status.json); the log tail is the most recent build log the box "
        'copied into the state dir.</p>'
        '<h2>Identity</h2>'
        f'<div class="opscard">{"".join(idrows)}</div>'
        '<h2>Cache forensics (C18-A4)</h2>'
        f'<div class="opscard">{"".join(cacherows)}</div>'
        '<h2>Build log tail</h2>'
        f'{log_block}'
        + back
    )
    return _shell("AusMT build detail", body, nav=nav)


# ---- C45 usage-analytics screen (record D4/D5) -------------------------------------------------
# A READ-ONLY Operations page rendering the host aggregator's stats.json (downloads/visits/countries +
# a daily series). SAME trust class as the ops floor: the facts come from stats.json read SERVER-side
# (serve_state.read_stats — the ops-status.json seam, no new mount, C40 intact). ZERO JS: the daily
# series is a SERVER-RENDERED inline SVG sparkline, so nothing here touches the strictPages CSP
# (script-src 'self'). Fail-closed: a missing stats.json shows an honest empty state; a stale one (old
# generated_at, the serve_state band) shows a prominent STALE banner — never a 500, never a silent
# last-known-good masquerading as live.

def _human_bytes(n) -> str:
    """A compact human size for a byte count (aggregate download volume). Non-numeric -> '—'."""
    try:
        v = float(n)
    except (TypeError, ValueError):
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if v < 1024 or unit == "TB":
            return (f"{int(v)} {unit}" if unit == "B" else f"{v:.1f} {unit}")
        v /= 1024.0
    return f"{v:.1f} TB"


def _num_card(value, label) -> str:
    return f'<div class="card"><div class="n">{_esc(value)}</div><div class="l">{_esc(label)}</div></div>'


def _analytics_cards(stats: dict) -> str:
    totals = stats.get("totals") or {}
    downloads = totals.get("downloads") or 0
    visits = totals.get("visits") or 0
    unattributed = totals.get("unattributed") or 0
    volume = _human_bytes(totals.get("download_bytes"))
    countries = stats.get("countries") or {}
    n_countries = len([c for c in countries if c and c != "unknown"])
    by_dataset = (stats.get("downloads") or {}).get("by_dataset") or {}
    cards = (
        _num_card(downloads, "Downloads")
        + _num_card(visits, "Portal visits")
        + _num_card(n_countries, "Countries")
        + _num_card(len(by_dataset), "Datasets downloaded")
        + _num_card(volume, "Download volume")
        + _num_card(unattributed, "Unattributed")
    )
    return f'<div class="cards">{cards}</div>'


def _format_breakdown(stats: dict) -> str:
    by_format = (stats.get("downloads") or {}).get("by_format") or {}
    if not by_format:
        return ""
    parts = ", ".join(f"{_esc(k)}: <b>{_esc(v)}</b>"
                      for k, v in sorted(by_format.items(), key=lambda kv: (-kv[1], kv[0])))
    return f'<p class="opsnote">Downloads by format — {parts}.</p>'


def _dataset_label(row: dict) -> str:
    """The station id (a per-station file) or the survey-package slug + '(bundle)' (a per-survey
    bundle) — the finest attribution the manifest reverse map yields."""
    if row.get("station"):
        return _esc(row.get("station"))
    if row.get("slug"):
        return f'{_esc(row.get("slug"))} <span class="k">(bundle)</span>'
    return "—"


def _top_datasets_table(stats: dict, *, n: int = 20) -> str:
    by_dataset = (stats.get("downloads") or {}).get("by_dataset") or {}
    if not by_dataset:
        return '<p class="sub">No attributed downloads yet.</p>'
    rows = sorted(by_dataset.values(), key=lambda r: (-int(r.get("downloads") or 0),
                                                      str(r.get("survey") or "")))
    trs = []
    for r in rows[:n]:
        trs.append(
            "<tr>"
            f'<td>{_esc(r.get("survey") or "—")}</td>'
            f'<td>{_dataset_label(r)}</td>'
            f'<td>{_esc(r.get("format") or "—")}</td>'
            f'<td class="num">{_esc(r.get("downloads") or 0)}</td>'
            "</tr>")
    more = ("" if len(rows) <= n else
            f'<p class="opsnote">Showing the top {n} of {len(rows)} datasets by downloads.</p>')
    return ('<table><thead><tr><th>Survey</th><th>Station / package</th><th>Format</th>'
            '<th class="num">Downloads</th></tr></thead><tbody>'
            + "".join(trs) + "</tbody></table>" + more)


def _country_table(stats: dict) -> str:
    countries = stats.get("countries") or {}
    if not countries:
        return '<p class="sub">No country data yet.</p>'
    rows = sorted(countries.items(), key=lambda kv: (-int(kv[1] or 0), str(kv[0])))
    trs = []
    for cc, count in rows:
        label = "unknown" if (not cc or cc == "unknown") else cc
        trs.append(f'<tr><td>{_esc(label)}</td><td class="num">{_esc(count)}</td></tr>')
    return ('<table><thead><tr><th>Country</th><th class="num">Requests (downloads + visits)</th>'
            '</tr></thead><tbody>' + "".join(trs) + "</tbody></table>")


def _daily_sparkline(daily: list) -> str:
    """A SERVER-RENDERED inline SVG sparkline of the daily downloads (accent) and visits (info) series.
    NO JS — pure SVG, so it is inert under the strictPages CSP. Empty/one-point series degrade to a
    note / a single marker. Every interpolated value is numeric or _esc'd."""
    pts = [d for d in (daily or []) if isinstance(d, dict) and isinstance(d.get("date"), str)]
    if not pts:
        return '<p class="sub">No daily series yet.</p>'
    pts = sorted(pts, key=lambda d: d["date"])
    downloads = [max(int(d.get("downloads") or 0), 0) for d in pts]
    visits = [max(int(d.get("visits") or 0), 0) for d in pts]
    peak = max(downloads + visits + [1])
    w, h, pad = 720, 120, 10
    plot_h = h - 2 * pad
    n = len(pts)

    def _coords(series):
        out = []
        for i, v in enumerate(series):
            x = pad + (0 if n == 1 else (w - 2 * pad) * i / (n - 1))
            y = pad + plot_h - (v / peak) * plot_h
            out.append(f"{x:.1f},{y:.1f}")
        return " ".join(out)

    dl_accent = _PALETTE["accent"]
    vis_info = _PALETTE["info"]
    grid = "#2E4254"
    baseline_y = pad + plot_h
    if n == 1:
        # A single day: draw two markers rather than a degenerate line.
        dx = pad
        marks = (f'<circle cx="{dx}" cy="{pad + plot_h - (downloads[0] / peak) * plot_h:.1f}" r="3" '
                 f'fill="{dl_accent}"/>'
                 f'<circle cx="{dx}" cy="{pad + plot_h - (visits[0] / peak) * plot_h:.1f}" r="3" '
                 f'fill="{vis_info}"/>')
        series_svg = marks
    else:
        series_svg = (
            f'<polyline fill="none" stroke="{dl_accent}" stroke-width="2" points="{_coords(downloads)}"/>'
            f'<polyline fill="none" stroke="{vis_info}" stroke-width="2" stroke-dasharray="4 3" '
            f'points="{_coords(visits)}"/>')
    first_date, last_date = _esc(pts[0]["date"]), _esc(pts[-1]["date"])
    svg = (
        f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img" '
        f'aria-label="Daily downloads and visits" style="width:100%;height:auto;max-width:100%">'
        f'<line x1="{pad}" y1="{baseline_y}" x2="{w - pad}" y2="{baseline_y}" stroke="{grid}" '
        f'stroke-width="1"/>'
        f'{series_svg}'
        f'<text x="{pad}" y="{h - 1}" fill="{_PALETTE["muted"]}" font-size="11">{first_date}</text>'
        f'<text x="{w - pad}" y="{h - 1}" fill="{_PALETTE["muted"]}" font-size="11" '
        f'text-anchor="end">{last_date}</text>'
        f'<text x="{pad}" y="{pad + 8}" fill="{_PALETTE["muted"]}" font-size="11">peak {peak}</text>'
        "</svg>")
    legend = (f'<p class="opsnote"><span style="color:{dl_accent}">&#9644;</span> downloads &nbsp; '
              f'<span style="color:{vis_info}">&#9644;</span> visits &nbsp;·&nbsp; {n} day(s)</p>')
    return f'<div style="overflow-x:auto">{svg}</div>{legend}'


def render_analytics_page(*, stats, stats_stale: bool, nav: "NavContext") -> str:
    """The C45 usage-analytics screen (record D4/D5): summary cards, a top-datasets table, a country
    table, and a server-rendered daily sparkline over the aggregator's stats.json. `stats` is the parsed
    stats.json (or None); `stats_stale` is True when it is missing OR older than ~2 timer periods (the
    serve_state band). Read-only, ZERO JS. A None stats renders the honest EMPTY state; a present-but-
    stale one renders the data under a prominent STALE banner (never last-known-good silently as live)."""
    generated_at = stats.get("generated_at") if isinstance(stats, dict) else None
    intro = ('<h1>Usage analytics</h1>'
             '<p class="sub">Downloads and portal visits from the server access log, aggregated daily '
             '(masked-at-edge IPs, aggregates only — no addresses or user-agents are stored). '
             'Per-station and per-survey <em>views</em> are not server-countable — the portal renders '
             'them client-side with no per-navigation request (record D3), so this screen reports '
             'downloads and whole-portal visits, honestly, not page views.</p>')
    if not isinstance(stats, dict):
        body = (intro
                + '<div class="opsband" style="background:' + _PALETTE["panel"] + '">'
                + '<p style="margin:0"><b>No usage analytics yet.</b> The aggregator has not written a '
                + 'stats.json. Install the <code>ausmt-stats</code> timer and place the db-ip CSV '
                + '(deploy/README.md &rarr; "Usage analytics"); the first daily fold populates this '
                + 'screen.</p></div>')
        return _shell("AusMT usage analytics", body, nav=nav)

    if stats_stale:
        chip = (f'<div class="opsband" style="background:{_PALETTE["warn"]};color:{_PALETTE["bg"]};'
                f'font-weight:600">Usage analytics are STALE — stats.json is missing recent updates or '
                f'is older than ~2 aggregation periods (last generated: '
                f'{_esc(generated_at) if generated_at else "never"}). The ausmt-stats timer may not be '
                f'running. The figures below are as of that time, not live.</div>')
    else:
        chip = (f'<p class="sub" style="margin-top:-.5rem">Updated '
                f'<span class="dt" title="{_esc(generated_at)}">{_esc(short_utc(generated_at or ""))}</span>'
                f' · aggregated daily.</p>')
    body = (
        intro
        + chip
        + _analytics_cards(stats)
        + _format_breakdown(stats)
        + '<h2>Daily downloads &amp; visits</h2>'
        + _daily_sparkline(stats.get("daily") or [])
        + '<h2>Top datasets</h2>'
        + _top_datasets_table(stats)
        + '<h2>By country</h2>'
        + _country_table(stats)
    )
    return _shell("AusMT usage analytics", body, nav=nav)


# ---- C43 S2b-ii: rollback + restore CONFIRMATION pages (typed id; restore also a TOTP code) ------

def render_rollback_confirm(*, build_ref: str, build, serving: bool, csrf_token: str,
                            error: str = "", nav: "NavContext") -> str:
    """The "serve this build" (rollback) confirmation page. Rollback is a REPOINT of `current`, never
    a rebuild — it serves an already-verified retained build immediately, and pins reconcile off an
    auto-revert until an explicit rebuild moves forward. Confirmation requires typing the build id. If
    the id is not in the retained inventory (or is the currently-serving build) the form is replaced by
    the honest refusal — the host re-validates against the real inventory regardless (D9.2)."""
    csrf = f'<input type="hidden" name="{CSRF_FIELD}" value="{_esc(csrf_token)}">'
    err = f'<p class="sub" style="color:{_PALETTE["bad"]}">{_esc(error)}</p>' if error else ""
    back = '<p><a href="/gateway/curator/serve">back to serve state</a></p>'
    if build is None:
        body = (f'<h1>Serve build — {_esc(build_ref)}</h1>{err}'
                '<div class="panel"><h2>No such retained build</h2>'
                '<p class="sub">That build is not in the current retained inventory, so it cannot be '
                'served. Pick a build from the retained-builds table.</p>' + back + '</div>')
        return _shell("AusMT rollback", body, nav=nav)
    if serving:
        body = (f'<h1>Serve build — {_esc(build_ref)}</h1>{err}'
                '<div class="panel"><h2>Already serving</h2>'
                '<p class="sub">This build is the one currently being served — there is nothing to roll '
                'back to.</p>' + back + '</div>')
        return _shell("AusMT rollback", body, nav=nav)
    src = build.get("source_commit") or "?"
    disclosure = (
        '<div class="panel"><h2>What "serve this build" does</h2><ul>'
        f'<li><strong>Repoints <code>current</code></strong> to <code>builds/{_esc(build_ref)}</code> '
        '(source ' + f'<code>{_esc(src)}</code>) with an atomic symlink swap — it serves an '
        'already-verified retained build IMMEDIATELY. It NEVER rebuilds.</li>'
        '<li><strong>Pins the reconcile agent</strong> — while the pin stands, automatic rebuilds are '
        'held so the box does not silently revert your rollback. The drift chip shows the lag honestly.'
        '</li>'
        '<li><strong>To move forward again</strong> — press Force/Request rebuild on the serve screen; '
        'that clears the pin and rebuilds to the published HEAD.</li>'
        '</ul></div>')
    confirm_msg = f"Serve builds/{build_ref}? Repoints current (no rebuild) and pins reconcile."
    form = (
        '<div class="panel"><h2>Confirm — serve this build</h2>'
        f'{err}'
        f'<form method="post" action="/gateway/curator/serve/rollback/{_esc(build_ref)}" '
        f'data-confirm="{_esc(confirm_msg)}">'
        f'{csrf}'
        '<p><label class="k">Type the build id to confirm</label>'
        f'<input type="text" name="typed_build" autocomplete="off" placeholder="{_esc(build_ref)}"></p>'
        '<p><button class="b-warn" type="submit">Serve this build</button></p>'
        '</form></div>')
    body = (f'<h1>Serve build — {_esc(build_ref)}</h1>'
            '<p class="sub">Roll the served corpus back to an already-verified retained build. Typed '
            'confirmation required.</p>' + disclosure + form + back)
    return _shell("AusMT rollback", body, nav=nav)


def render_restore_confirm(*, snapshot_ref: str, snapshot_exists: bool, csrf_token: str,
                           enrolled: bool, error: str = "", nav: "NavContext") -> str:
    """The guarded DB-restore confirmation page (record D8, drill-first destructive op). Confirmation
    requires typing the snapshot id AND a valid TOTP code (the C41 shared destructive-op second
    factor). When the snapshot is not in the inventory, or the curator is not enrolled in the second
    factor, the form is replaced by the honest refusal (the host re-validates + the route re-gates
    regardless). The disclosure states exactly what a restore erases."""
    csrf = f'<input type="hidden" name="{CSRF_FIELD}" value="{_esc(csrf_token)}">'
    err = f'<p class="sub" style="color:{_PALETTE["bad"]}">{_esc(error)}</p>' if error else ""
    back = '<p><a href="/gateway/curator/serve">back to serve state</a></p>'
    disclosure = (
        '<div class="panel"><h2>What restoring this snapshot does</h2><ul>'
        f'<li><strong>Replaces the live gateway DB</strong> with the snapshot '
        f'<code>{_esc(snapshot_ref)}</code> — the on-box agent stops the gateway, DRILLS the snapshot '
        'first (integrity + schema; a failing drill ABORTS with the live DB untouched), swaps the DB, '
        'and restarts the gateway.</li>'
        '<li><strong>Submissions received AFTER the snapshot are ERASED</strong> — the DB is the '
        'submission + audit record; anything since the snapshot was taken is not in it and is lost.</li>'
        '<li><strong>Uploader keys + curator enrolments</strong> revert to their state at the snapshot '
        'too.</li>'
        '<li><strong>Drill-first is the safety net</strong> — a corrupt/incompatible snapshot is '
        'refused before the live DB is touched.</li>'
        '</ul></div>')
    if not snapshot_exists:
        body = (f'<h1>Restore DB — {_esc(snapshot_ref)}</h1>{err}'
                '<div class="panel"><h2>No such snapshot</h2>'
                '<p class="sub">That snapshot is not in the reported backup inventory, so it cannot be '
                'restored. Pick a snapshot from the backup-snapshots table.</p>' + back + '</div>')
        return _shell("AusMT restore", body, nav=nav)
    if not enrolled:
        body = (f'<h1>Restore DB — {_esc(snapshot_ref)}</h1>'
                '<p class="sub">A DB restore is destructive and protected by your authenticator.</p>'
                + disclosure +
                '<div class="panel"><h2>Enrol your authenticator first</h2>'
                f'{err}'
                '<p class="sub">Restoring the DB requires a time-based one-time code (the second '
                'factor). You are not enrolled. Set it up on the '
                '<a href="/gateway/curator/security">Security</a> page, then return here.</p>'
                + back + '</div>')
        return _shell("AusMT restore", body, nav=nav)
    confirm_msg = (f"Restore the gateway DB from {snapshot_ref}? Submissions since the snapshot are "
                   "ERASED (drill-first; a failing drill aborts untouched).")
    form = (
        '<div class="panel"><h2>Confirm — restore the DB</h2>'
        f'{err}'
        f'<form method="post" action="/gateway/curator/serve/restore/{_esc(snapshot_ref)}" '
        f'data-confirm="{_esc(confirm_msg)}">'
        f'{csrf}'
        '<p><label class="k">Type the snapshot id to confirm</label>'
        f'<input type="text" name="typed_snapshot" autocomplete="off" placeholder="{_esc(snapshot_ref)}"></p>'
        '<p><label class="k">Authenticator code (required — the second factor)</label>'
        '<input type="text" name="code" inputmode="numeric" autocomplete="off" '
        'placeholder="123456" style="max-width:12rem"></p>'
        '<p><button class="b-bad" type="submit">Restore DB from snapshot</button></p>'
        '</form></div>')
    body = (f'<h1>Restore DB — {_esc(snapshot_ref)}</h1>'
            '<p class="sub">Restore the gateway database from an on-box snapshot. This is destructive '
            'and protected by a typed confirmation and your authenticator. Read what it erases.</p>'
            + disclosure + form + back)
    return _shell("AusMT restore", body, nav=nav)


def _checklist_panel(cl: "checklist_mod.Checklist") -> str:
    trs = []
    for c in cl.checks:
        colour = _STATUS_COLOUR.get(c.status, _PALETTE["muted"])
        block = " (blocking)" if c.blocking else ""
        trs.append(
            "<tr>"
            f'<td><span class="badge" style="background:{colour}">{_esc(c.status)}</span></td>'
            f'<td>{_esc(c.label)}{_esc(block)}</td>'
            f'<td>{_esc(c.detail)}</td>'
            "</tr>"
        )
    warning = ""
    if cl.has_unacknowledgeable_blocking_fail:
        warning = (f'<p style="color:{_PALETTE["bad"]};font-weight:600">'
                   'A blocking check FAILED — approve is refused until it is resolved.</p>')
    elif cl.has_acknowledgeable_blocking_fail:
        # C11b §3: an acknowledgeable-only block. Approve is available via the acknowledgement
        # checkbox (a deliberate curator decision), NOT hard-refused. The submitter's own email would
        # be unacknowledgeable and hit the branch above instead.
        warning = (f'<p style="color:{_PALETTE["warn"]};font-weight:600">'
                   'A blocking PII check FAILED on non-submitter addresses — approve requires the '
                   'acknowledgement below.</p>')
    return ('<div class="panel"><h2>Checklist</h2>' + warning
            + "<table><tr><th>Status</th><th>Check</th><th>Detail</th></tr>"
            + "".join(trs) + "</table></div>")


def _submitter_panel(*, name: str, email: str, orcid: str | None) -> str:
    # Curator-only PII (design §2). This block appears ONLY here, never on the public status page.
    orcid_row = f'<tr><td class="k">ORCID</td><td>{_esc(orcid)}</td></tr>' if orcid else ""
    return (
        '<div class="panel"><h2>Submitter (curator-only)</h2>'
        '<table>'
        f'<tr><td class="k">Name</td><td>{_esc(name)}</td></tr>'
        f'<tr><td class="k">Email</td><td>{_esc(email)}</td></tr>'
        f'{orcid_row}'
        '</table></div>'
    )


def _reports_panel(*, validate_report: dict | None, preview_summary: dict | None) -> str:
    parts = ['<div class="panel"><h2>Report bundle</h2>']
    items = (validate_report or {}).get("items") if isinstance(validate_report, dict) else None
    if isinstance(items, list) and items:
        rows = []
        for it in items:
            if not isinstance(it, dict):
                continue
            level = _esc(it.get("level") or it.get("status") or "")
            name = _esc(it.get("name") or it.get("check") or it.get("id") or "")
            msg = _esc(it.get("message") or it.get("detail") or it.get("msg") or "")
            rows.append(f"<tr><td>{level}</td><td>{name}</td><td>{msg}</td></tr>")
        parts.append("<h2>Validator</h2><table><tr><th>Level</th><th>Check</th><th>Message</th></tr>"
                     + "".join(rows) + "</table>")
    if isinstance(preview_summary, dict) and preview_summary:
        rows = []
        for key in ("station_count", "types", "coord_flags", "warnings"):
            if key in preview_summary:
                rows.append(f'<tr><td class="k">{_esc(key)}</td><td>{_esc(preview_summary[key])}</td></tr>')
        if rows:
            parts.append("<h2>Preview summary</h2><table>" + "".join(rows) + "</table>")
    parts.append("</div>")
    return "".join(parts)


# C11b §3: the acknowledgement checkbox label. Rendered ONLY when the PII block is acknowledgeable
# (non-submitter addresses) and there are NO submitter hits. When a submitter hit exists the checkbox
# is NOT rendered and the button is hard-disabled — the server-side 409 is the guarantee either way.
_ACK_PII_LABEL = (
    "I have opened each listed file and confirm every address is part of the original submitted "
    "records (e.g. an EDI &gt;INFO contact line) and none is the submitter's private contact — "
    "publishing them is a deliberate curator decision."
)


def _ack_pii_checkbox() -> str:
    return ('<p><label><input type="checkbox" name="ack_pii" value="1" style="width:auto"> '
            f'{_ACK_PII_LABEL}</label></p>')


def _action_forms(*, submission_id: str, state: str, csrf_token: str,
                  cl: "checklist_mod.Checklist") -> str:
    sid = _esc(submission_id)
    csrf = f'<input type="hidden" name="{CSRF_FIELD}" value="{_esc(csrf_token)}">'
    note = ('<p><textarea name="note" placeholder="Decision note (required)" '
            'required></textarea></p>')
    # A hard block (submitter PII or any non-PII FAIL) disables approve. An acknowledgeable-only PII
    # block does NOT disable it — instead the ack checkbox appears (§3). The 409 remains the guarantee.
    hard_blocked = cl.has_unacknowledgeable_blocking_fail
    ack_box = _ack_pii_checkbox() if cl.has_acknowledgeable_blocking_fail else ""
    forms = []
    if state in (states.VALIDATED,):
        approve_attr = "disabled" if hard_blocked else ""
        approve_title = ' title="Blocked by a failing check"' if hard_blocked else ""
        forms.append(
            f'<div class="panel"><h2>Approve &amp; publish</h2>'
            f'<form method="post" action="/gateway/curator/submission/{sid}/approve">{csrf}{note}'
            '<p><label><input type="checkbox" name="confirm_overwrite" value="1" '
            'style="width:auto"> This updates an existing survey (replace it)</label></p>'
            f'{ack_box}'
            f'<p><button class="b-ok" type="submit" {approve_attr}{approve_title}>Approve</button></p>'
            '</form></div>'
        )
        forms.append(
            f'<div class="panel"><h2>Return to submitter</h2>'
            f'<form method="post" action="/gateway/curator/submission/{sid}/return">'
            f'{csrf}{note}<p><button class="b-warn" type="submit">Return to submitter</button></p>'
            '</form></div>'
        )
        # Reject now REQUIRES a real note too (design §3 — no exemption). Its own note field.
        forms.append(
            f'<div class="panel"><h2>Reject</h2>'
            f'<form method="post" action="/gateway/curator/submission/{sid}/reject" '
            'data-confirm="Reject this submission?">'
            f'{csrf}{note}'
            '<p><button class="b-bad" type="submit">Reject</button></p>'
            '</form></div>'
        )
    elif state == states.PUBLISHED:
        forms.append(
            '<div class="panel"><h2>Published</h2>'
            '<p class="sub">Committed to surveys-live. The serve-reconcile agent rebuilds and '
            'serves it automatically on its next tick (typically within 15 minutes) — watch the '
            'serve-state panel on the queue page. Manual <code>make rebuild-data</code> still '
            'works if the reconcile timer is not installed.</p></div>'
        )
    elif state == states.PUBLISH_FAILED:
        # Retry re-evaluates the checklist and acknowledgement is PER-ACTION (C11b §2), so a
        # still-acknowledgeable block needs the checkbox again here; a hard block disables retry.
        retry_attr = "disabled" if hard_blocked else ""
        retry_title = ' title="Blocked by a failing check"' if hard_blocked else ""
        forms.append(
            f'<div class="panel"><h2>Publish failed — retry</h2>'
            f'<form method="post" action="/gateway/curator/submission/{sid}/retry">{csrf}{note}'
            '<p><label><input type="checkbox" name="confirm_overwrite" value="1" '
            'style="width:auto"> This updates an existing survey (replace it)</label></p>'
            f'{ack_box}'
            f'<p><button class="b-accent" type="submit" {retry_attr}{retry_title}>Retry publish</button></p>'
            '</form></div>'
        )
    elif state == states.PUBLISHING:
        forms.append('<div class="panel"><p class="sub">Publishing in progress — refresh to see the '
                     'outcome.</p></div>')
    return "".join(forms)


# ---- C31 metadata editor ---------------------------------------------------------------------

# The editable fields, grouped like the add-survey page (C31 §2). Top-level scalars render as an
# input/textarea; the STRUCTURED sections (maps + lists) now render as per-section WIDGETS
# (labelled inputs, selects, checkboxes, repeatable rows) instead of the raw-JSON textareas a 2026-
# 07-08 production use judged hostile for a geophysicist. Every section still keeps an "advanced"
# collapsed raw-JSON <details> fallback that OVERRIDES its widgets when non-empty (deliberate escape
# hatch, documented in the copy). The section shapes/labels live in gateway.editor_form (the server-
# side assembly half) so rendering and assembly cannot drift. ORCID/ROR hints are text + a plain
# link only (C31 §2 / the strictPages CSP has no api.ror.org connect-src — a fetch would be blocked).
_EDIT_SCALARS = (
    ("project_name", "Project name"),
    ("name", "Name (backward-compatible alias)"),
    ("region", "Region"),
    ("license", "Licence (e.g. CC-BY-4.0)"),
)
_EDIT_TEXTAREAS = (
    ("abstract", "Abstract"),
)

# Sections with NO structured widget (schema too open-ended / nested to model as flat labelled
# inputs) — rendered as advanced-JSON ONLY, and the form says so honestly. `care` carries a nested
# land_access map + a boolean, which flat inputs cannot round-trip cleanly.
_EDIT_JSON_ONLY = (
    ("care", "CARE governance",
     "traditional_owner_acknowledgement, land_access {permission_obtained, agreement_type}, "
     "restrictions_requested"),
)

# The structured-section titles + document order (matches survey-yaml.md), shared by the single-form
# edit page and the C43 survey-hub Metadata tab (which splits each into its own per-section form) so
# rendering order never drifts between them.
_SECTION_TITLES = {
    "organisation": "Organisation", "lead_investigator": "Lead investigator",
    "principal_investigators": "Principal investigators", "identifiers": "Identifiers",
    "publications": "Publications", "funding": "Funding", "instruments": "Instruments",
    "time_series": "Time series", "access": "Access", "attribution": "Attribution & rights",
    "sources": "Source datasets", "processing": "Processing", "collection": "Collection",
}
_SECTION_ORDER = ("organisation", "lead_investigator", "principal_investigators", "identifiers",
                  "publications", "funding", "instruments", "time_series", "access", "attribution",
                  "sources", "processing", "collection")


def _json_text(value) -> str:
    import json as _json
    return _json.dumps(value, indent=2, ensure_ascii=False)


def _canon_json(value) -> str:
    """Canonical (compact, key-sorted) JSON for the hidden o_<section> snapshot — the round-trip
    anchor editor_form.assemble_section compares an unchanged submit against. sort_keys makes the
    snapshot stable regardless of the read-job's key order."""
    import json as _json
    return _json.dumps(value, sort_keys=True, ensure_ascii=False)


def _suggest_bump(current: str, kind: str) -> str:
    """Display-only bump suggestion for the form (patch is the C31 §0.3 default). The AUTHORITATIVE
    semver comparison + enforcement lives in the runner (gateway.runner.edit.semver_greater); this is
    a pure-stdlib suggestion so the page needs no yaml/runner import. A non-semver current version
    falls back to 1.0.x so the form always shows a valid suggestion."""
    parts = str(current or "").split(".")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        major, minor, patch = (int(p) for p in parts)
    else:
        major, minor, patch = 1, 0, 0
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


# ---- editor widget helpers (deliverable of the 2026-07-08 form rework) --------------------------
# Every value is _esc'd. NO inline JS / on*= handlers anywhere (the strictPages CSP kills them, and
# two pin tests enforce it) — the repeatable-row add/remove behaviour rides EDITOR_UI_JS's delegated
# data-attribute handlers, served external at /gateway/curator/editor.js, and DEGRADES without JS
# (the server renders existing rows + spare blank rows so adding a row needs no script).

# ROR/DOI/date hint copy — a plain link only (no api.ror.org fetch: the curator CSP has no
# connect-src for it, unlike add-survey.html).
_ROR_HINT = ('<span class="sub">ROR id — <a href="https://ror.org" target="_blank" '
             'rel="noopener">find your organisation\'s ROR</a></span>')


def _field_error_map(field_errors) -> dict:
    """Group SectionError objects by section so a widget block can show its own error line(s)."""
    out: dict[str, list[str]] = {}
    for e in field_errors or []:
        out.setdefault(getattr(e, "section", ""), []).append(getattr(e, "message", str(e)))
    return out


def _section_error_html(errors_for_section) -> str:
    if not errors_for_section:
        return ""
    items = "".join(f"<li>{_esc(m)}</li>" for m in errors_for_section)
    return (f'<ul class="sub" style="color:{_PALETTE["bad"]};margin:.25rem 0 .5rem;'
            f'padding-left:1.2rem">{items}</ul>')


def _text_input(name: str, value, placeholder: str = "", input_type: str = "text",
                extra_hint: str = "", css_class: str = "") -> str:
    val = "" if value is None else value
    ph = f' placeholder="{_esc(placeholder)}"' if placeholder else ""
    hint = f' {extra_hint}' if extra_hint else ""
    cls = f' class="{_esc(css_class)}"' if css_class else ""
    return (f'<input type="{_esc(input_type)}" name="{_esc(name)}"{cls} '
            f'value="{_esc(val)}"{ph}>{hint}')


def _snapshot_hidden(section: str, fields: dict) -> str:
    """The hidden o_<section> round-trip anchor: canonical JSON of the ORIGINAL section value, or
    absent when the survey did not carry the section (so a left-empty section stays absent)."""
    if section not in fields:
        return ""
    return (f'<input type="hidden" name="o_{section}" '
            f'value="{_esc(_canon_json(fields[section]))}">')


def _sub_value(section: str, subkey: str, fields: dict, submitted: dict | None):
    """The value to prefill a map sub-field: the resubmitted form value (after a validation error) if
    present, else the original from the read-job fields, else empty."""
    if submitted is not None and f"s_{section}_{subkey}" in submitted:
        return submitted.get(f"s_{section}_{subkey}")
    section_val = fields.get(section)
    if isinstance(section_val, dict):
        return section_val.get(subkey)
    if isinstance(section_val, str) and subkey == "name":
        return section_val  # organisation-as-bare-string: the string prefills the Name field
    return None


def _map_section_panel(section: str, title: str, fields: dict, submitted: dict | None,
                       err_map: dict, display_errs: dict | None = None) -> str:
    """`display_errs` (C43-HUB H4): {subkey: message} DISPLAY-LAYER inline errors — the red input
    + explanatory line under it (the mockup's citation-author-email example). Rendering only:
    the runner-side validator and the preview/confirm POST path are untouched (pinned)."""
    from . import editor_form
    subfields = editor_form.MAP_SECTIONS[section]
    rows = [f'<h2>{_esc(title)}</h2>', _section_error_html(err_map.get(section))]
    for subkey, label, placeholder, kind in subfields:
        name = f"s_{section}_{subkey}"
        val = _sub_value(section, subkey, fields, submitted)
        derr = (display_errs or {}).get(subkey)
        derr_html = f'<span class="fielderr">{_esc(derr)}</span>' if derr else ""
        bad = "badinput" if derr else ""
        if kind == "select" and section == "access" and subkey == "coordinates":
            rows.append(_coordinate_access_widget(name, val))
        elif kind == "select" and section == "access":
            rows.append(_access_level_widget(name, val))
        elif kind == "license":
            rows.append(_license_select_widget(name, label, val))
        elif kind == "profile":
            rows.append(_profile_select_widget(name, label, val))
        elif kind == "bool":
            rows.append(_bool_widget(name, label, val, submitted))
        elif kind == "date":
            rows.append(f'<p><label class="k">{_esc(label)}</label>'
                        f'{_text_input(name, val, placeholder, input_type="date", css_class=bad)}'
                        f'{derr_html}</p>')
        elif kind == "email":
            rows.append(f'<p><label class="k">{_esc(label)}</label>'
                        f'{_text_input(name, val, placeholder, input_type="email", css_class=bad)}'
                        f'{derr_html}</p>')
        elif kind == "levels" and section == "time_series":
            rows.append(_levels_widget(section, subkey, fields, submitted))
        elif kind == "ror":
            rows.append(f'<p><label class="k">{_esc(label)}</label>'
                        f'{_text_input(name, val, placeholder, extra_hint=_ROR_HINT, css_class=bad)}'
                        f'{derr_html}</p>')
        else:
            rows.append(f'<p><label class="k">{_esc(label)}</label>'
                        f'{_text_input(name, val, placeholder, css_class=bad)}'
                        f'{derr_html}</p>')
    rows.append(_snapshot_hidden(section, fields))
    rows.append(_advanced_json_details(section, fields))
    return f'<div class="panel">{"".join(rows)}</div>'


def _access_level_widget(name: str, value) -> str:
    from . import editor_form
    current = value if value in editor_form.ACCESS_LEVELS else "open"
    opts = "".join(
        f'<option value="{_esc(lv)}"{" selected" if lv == current else ""}>{_esc(lv)}</option>'
        for lv in editor_form.ACCESS_LEVELS)
    return (f'<p><label class="k">Access level</label>'
            f'<select name="{_esc(name)}">{opts}</select></p>')


def _coordinate_access_widget(name: str, value) -> str:
    """The C42 survey-level coordinate-access policy <select>: exact / generalised / withheld, with a
    leading blank '(default: exact)' option. Mirrors _access_level_widget but — unlike level — an UNSET
    policy stays blank (submits ""), so the assembler never writes access.coordinates for a survey that
    never set it (the record's byte-unchanged promise; absent => exact). An out-of-vocab STORED value is
    SHOWN as its own selected option rather than silently coerced, so the curator sees and can fix it —
    the render degrades safely, it does not crash. Server-rendered <select>, no JS (CSP unaffected)."""
    from . import editor_form
    cur = str(value) if value not in (None, "") else ""
    opts = [f'<option value=""{" selected" if cur == "" else ""}>(default: exact)</option>']
    for pol in editor_form.COORDINATE_POLICIES:
        opts.append(
            f'<option value="{_esc(pol)}"{" selected" if pol == cur else ""}>{_esc(pol)}</option>')
    if cur and cur not in editor_form.COORDINATE_POLICIES:
        # A stored value outside the vocab (e.g. a hand-edited survey.yaml): show it selected so the
        # curator sees and can correct it — never crash, never silently drop it (the render pin).
        opts.append(f'<option value="{_esc(cur)}" selected>{_esc(cur)} (stored value)</option>')
    return (f'<p><label class="k">Coordinate access</label>'
            f'<select name="{_esc(name)}">{"".join(opts)}</select>'
            f'<br><span class="sub">Survey default for served station coordinates: exact as recorded, '
            f'generalised to 0.1&deg; (~11 km), or withheld. Leave as default to serve them exactly.'
            f'</span></p>')


def _license_option_html(current: str) -> str:
    """The <option>s for a licence <select>: the full contract vocab (editor_form.LICENSE_IDS),
    grouped redistributable vs recognised metadata-only, `current` selected. An out-of-vocab STORED
    value (a hand-edited / legacy licence) is shown as its own selected option so the curator sees and
    can fix it rather than it being silently coerced — the same render-degrade discipline as
    _coordinate_access_widget. Every value escaped. Shared by the top-level and sources[] selects."""
    from . import editor_form
    cur = str(current) if current not in (None, "") else ""

    def opt(v):
        return f'<option value="{_esc(v)}"{" selected" if v == cur else ""}>{_esc(v)}</option>'
    redist = editor_form.LICENSE_REDISTRIBUTABLE
    recog = [x for x in editor_form.LICENSE_IDS if x not in redist]
    html = ('<optgroup label="Redistributable (AusMT serves the bytes)">'
            + "".join(opt(v) for v in redist) + "</optgroup>"
            + '<optgroup label="Recognised (metadata-only display)">'
            + "".join(opt(v) for v in recog) + "</optgroup>")
    if cur and cur not in editor_form.LICENSE_IDS:
        html += f'<option value="{_esc(cur)}" selected>{_esc(cur)} (stored value — not a recognised id)</option>'
    return html


def _license_select_widget(name: str, label: str, value) -> str:
    """A vocab-validated licence <select> for a sources[].licence field (C46). Kills the free-text seam:
    the curator picks a recognised id, never types one. Server-rendered, no JS (CSP unaffected)."""
    return (f'<p><label class="k">{_esc(label)}</label>'
            f'<select name="{_esc(name)}"><option value="">(none)</option>'
            f'{_license_option_html(value)}</select></p>')


def _license_scalar_widget(value) -> str:
    """The top-level `license` <select> (f_license) — the C46 free-text-seam killer for the ONE
    package-level licence. Full contract vocab, current value selected; an out-of-vocab stored value is
    shown as its own option (never silently coerced). Required field, so no '(none)'; a leading blank
    appears only when nothing is stored yet. Assembled server-side in app._build_patch as before (the
    select just constrains what f_license can carry) — no JS, CSP unaffected."""
    cur = str(value) if value not in (None, "") else ""
    blank = (f'<option value=""{" selected" if cur == "" else ""}>(select a licence)</option>'
             if cur == "" else "")
    return f'<select name="f_license">{blank}{_license_option_html(cur)}</select>'


def _profile_select_widget(name: str, label: str, value) -> str:
    """The C46 attribution-profile <select> (ga | generic) for a sources[].profile field. A leading
    blank leaves it unset (default: generic at render time). An out-of-vocab stored value is shown so
    the curator can correct it. Every value escaped."""
    from . import editor_form
    cur = str(value) if value not in (None, "") else ""
    opts = [f'<option value=""{" selected" if cur == "" else ""}>(default: generic)</option>']
    for prof in editor_form.SOURCE_PROFILES:
        opts.append(f'<option value="{_esc(prof)}"{" selected" if prof == cur else ""}>{_esc(prof)}</option>')
    if cur and cur not in editor_form.SOURCE_PROFILES:
        opts.append(f'<option value="{_esc(cur)}" selected>{_esc(cur)} (stored value)</option>')
    return (f'<p><label class="k">{_esc(label)}</label>'
            f'<select name="{_esc(name)}">{"".join(opts)}</select></p>')


def _bool_widget(name: str, label: str, value, submitted: dict | None) -> str:
    """A single checkbox for a boolean sub-field (C46 attribution.changes_made). After a validation
    error the CHECKED state comes from `submitted` (the name is present iff it was ticked) so an
    un-tick survives the round-trip; otherwise it reflects the stored value. No JS (CSP unaffected)."""
    if submitted is not None:
        checked = name in submitted
    else:
        checked = value is True or (isinstance(value, str) and value.strip().lower() in ("true", "1", "yes"))
    mark = " checked" if checked else ""
    return (f'<p><label class="k">{_esc(label)}</label><br>'
            f'<label style="display:inline-block"><input type="checkbox" name="{_esc(name)}" '
            f'value="1" style="width:auto"{mark}> yes</label></p>')


def _levels_widget(section: str, subkey: str, fields: dict, submitted: dict | None) -> str:
    from . import editor_form
    # Determine which levels are checked: resubmitted checkboxes win, else the original list.
    checked: set[str] = set()
    if submitted is not None and any(
            k.startswith(f"c_{section}_{subkey}_") for k in submitted):
        for lv in editor_form.TIME_SERIES_LEVELS:
            if f"c_{section}_{subkey}_{lv}" in submitted:
                checked.add(lv)
    else:
        sec = fields.get(section)
        cur = sec.get(subkey) if isinstance(sec, dict) else None
        if isinstance(cur, list):
            checked = {str(x) for x in cur}
    boxes = []
    for lv in editor_form.TIME_SERIES_LEVELS:
        mark = " checked" if lv in checked else ""
        boxes.append(
            f'<label style="display:inline-block;margin-right:1rem"><input type="checkbox" '
            f'name="c_{section}_{subkey}_{_esc(lv)}" value="1" style="width:auto"{mark}> '
            f'{_esc(lv)}</label>')
    return ('<p><label class="k">Levels available</label><br>' + "".join(boxes) +
            '<br><span class="sub">Tick each processing level the collection provides. For a level '
            'outside this list, use the advanced JSON below.</span></p>')


def _list_row_html(section: str, index: int, subfields, values: dict | None) -> str:
    """One repeatable row: the per-subkey inputs + a remove button (data-attribute delegated; a no-JS
    submit just leaves an empty row, which the server drops). `values` prefills an existing row."""
    cells = []
    for subkey, label, placeholder, kind in subfields:
        name = f"l_{section}_{index}_{subkey}"
        val = (values or {}).get(subkey)
        if kind == "license":                       # C46 sources[].licence — vocab <select>
            cells.append(_license_select_widget(name, label, val))
            continue
        if kind == "profile":                       # C46 sources[].profile — ga|generic <select>
            cells.append(_profile_select_widget(name, label, val))
            continue
        itype = "email" if kind == "email" else "text"
        extra = _ROR_HINT if kind == "ror" else ""
        cells.append(f'<p style="margin:.15rem 0"><label class="k">{_esc(label)}</label>'
                     f'{_text_input(name, val, placeholder, input_type=itype, extra_hint=extra)}</p>')
    remove = ('<p style="margin:.15rem 0"><button type="button" class="b-bad" '
              'style="padding:.2rem .6rem;font-size:.75rem" data-editor-remove-row>'
              'Remove row</button></p>')
    return (f'<div class="editor-row" data-editor-row style="border:1px solid #2E4254;'
            f'border-radius:6px;padding:.5rem;margin:.4rem 0">{"".join(cells)}{remove}</div>')


# Spare blank rows rendered when JS is unavailable so a curator can still add entries (deliverable 3).
_SPARE_BLANK_ROWS = 2

# The literal index placeholder inside a section's <template> row. editor.js substitutes a fresh
# unique index for it. It sits BETWEEN underscores in the field name (l_<section>_<TOKEN>_<subkey>)
# so no real index or field text can collide with it, and the surrounding underscores survive.
ROW_INDEX_TOKEN = "ROWIDX"


def _list_section_panel(section: str, title: str, fields: dict, submitted: dict | None,
                        err_map: dict, display_error: str | None = None) -> str:
    """`display_error` (C43-HUB H4): a DISPLAY-LAYER section-level error line (list rows have no
    single offending input to redden, so the message renders under the heading). Rendering only —
    the server validator and POST path are untouched."""
    from . import editor_form
    subfields = editor_form.LIST_SECTIONS[section]
    # Prefill existing rows: resubmitted rows win (preserve typed values on a validation error),
    # else the original list from the read-job.
    existing: list[dict] = []
    if submitted is not None and any(k.startswith(f"l_{section}_") for k in submitted):
        for i in _submitted_row_indices(submitted, section):
            existing.append({sk: submitted.get(f"l_{section}_{i}_{sk}") for sk, *_ in subfields})
    else:
        orig = fields.get(section)
        if isinstance(orig, list):
            for item in orig:
                if isinstance(item, dict):
                    existing.append({sk: item.get(sk) for sk, *_ in subfields})
                else:
                    # A non-dict list item (e.g. a bare-DOI publication string) can't map to the row
                    # widgets — leave it to the advanced JSON, and note it. Render no widget row for it.
                    existing.append(None)  # placeholder marker; skipped below
    rendered = []
    idx = 0
    for row in existing:
        if row is None:
            continue  # non-dict item handled via advanced JSON
        rendered.append(_list_row_html(section, idx, subfields, row))
        idx += 1
    # Spare blank rows so add-without-JS works.
    for _ in range(_SPARE_BLANK_ROWS):
        rendered.append(_list_row_html(section, idx, subfields, None))
        idx += 1
    add_btn = ('<p><button type="button" class="b-accent" style="padding:.3rem .8rem" '
               f'data-editor-add-row="{_esc(section)}">+ Add row</button></p>')
    # A template row whose index is the literal placeholder ROW_INDEX_TOKEN (with its underscores
    # preserved: the field name becomes l_<section>_<TOKEN>_<subkey>). editor.js clones this and
    # substitutes a fresh unique index for the token. Hidden from no-JS users (the spare rows cover
    # them). Rendering with the token as the index — NOT string-replacing a rendered "_0_" — keeps
    # the surrounding underscores intact (a "_0_"->placeholder replace ate them, giving malformed
    # names like l_instruments3manufacturer; caught by the jsdom harness).
    template = (f'<template data-editor-template="{_esc(section)}">'
                f'{_list_row_html(section, ROW_INDEX_TOKEN, subfields, None)}'
                '</template>')
    heading = [f'<h2>{_esc(title)}</h2>', _section_error_html(err_map.get(section))]
    if display_error:
        heading.append(f'<p class="fielderr">{_esc(display_error)}</p>')
    return (f'<div class="panel" data-editor-section="{_esc(section)}">'
            + "".join(heading)
            + f'<div data-editor-rows="{_esc(section)}">{"".join(rendered)}</div>'
            + add_btn + template
            + _snapshot_hidden(section, fields)
            + _advanced_json_details(section, fields)
            + '</div>')


def _submitted_row_indices(submitted: dict, section: str) -> list[int]:
    prefix = f"l_{section}_"
    idx: set[int] = set()
    for key in submitted:
        if key.startswith(prefix):
            num, _, _sub = key[len(prefix):].partition("_")
            if num.isdigit():
                idx.add(int(num))
    return sorted(idx)


def _advanced_json_details(section: str, fields: dict) -> str:
    """The per-section collapsed-by-default advanced raw-JSON escape hatch (a <details> — no JS
    needed). When NON-EMPTY it OVERRIDES this section's widgets server-side (editor_form precedence).
    Prefilled empty by default so an unchanged submit uses the widgets, not a pre-baked JSON skeleton
    (deliverable 11): the read-job value is shown only as a collapsed reference, never as the input."""
    ref = _json_text(fields[section]) if section in fields else ""
    ref_block = (f'<p class="sub">current value (reference): '
                 f'<code>{_esc(ref)}</code></p>' if ref else "")
    return (
        '<details style="margin-top:.5rem"><summary class="sub">Advanced: edit this section as raw '
        'JSON (overrides the fields above when filled)</summary>'
        f'{ref_block}'
        f'<textarea name="j_{_esc(section)}" rows="4" placeholder="leave blank to use the fields '
        'above"></textarea></details>')


def _json_only_panel(section: str, title: str, hint: str, fields: dict, err_map: dict) -> str:
    """A section with no structured widget (schema too nested/open-ended): advanced-JSON only, stated
    honestly. Prefilled with the current value so the curator edits from it (there is no widget to
    fall back to)."""
    present = section in fields
    val = _json_text(fields[section]) if present else ""
    return (
        f'<div class="panel"><h2>{_esc(title)}</h2>'
        f'{_section_error_html(err_map.get(section))}'
        f'<p class="sub">This section has no structured form yet ({_esc(hint)}). Edit it as raw JSON '
        '(leave blank to leave unchanged).</p>'
        f'<textarea name="j_{_esc(section)}" rows="4">{_esc(val)}</textarea></div>')


def render_edit_form(*, slug: str, version: str | None, fields: dict, csrf_token: str,
                     error: str = "", field_errors=None, submitted: dict | None = None,
                     nav: "NavContext | None" = None) -> str:
    """The seed form (C31 §1.2): server-rendered, escaped, prefilled from the runner's editable
    subset. Top-level scalars are inputs/textarea; the structured sections are per-section WIDGETS
    (labelled inputs, an access-level <select>, levels checkboxes, repeatable rows) with a collapsed
    advanced-JSON <details> override each; `care` is advanced-JSON only (nested shape). A version-bump
    radio group (patch default) + a required release-note box carry the C31 §0.3 discipline.
    `field_errors` annotates the section(s) that failed validation; `submitted` re-prefills the
    widgets with the curator's typed values after such a failure so nothing is discarded."""
    from . import editor_form
    err = f'<p class="sub" style="color:{_PALETTE["bad"]}">{_esc(error)}</p>' if error else ""
    err_map = _field_error_map(field_errors)
    if err_map and not err:
        err = (f'<p class="sub" style="color:{_PALETTE["bad"]}">Some fields need attention — see the '
               'highlighted sections below.</p>')
    cur = version or "0.0.0"
    patch_v = _suggest_bump(cur, "patch")
    minor_v = _suggest_bump(cur, "minor")
    major_v = _suggest_bump(cur, "major")

    def _scalar_val(key):
        if submitted is not None and f"f_{key}" in submitted:
            return submitted.get(f"f_{key}")
        v = fields.get(key, "")
        return "" if v is None else v

    scalar_rows = []
    for key, label in _EDIT_SCALARS:
        widget = (_license_scalar_widget(_scalar_val(key)) if key == "license"
                  else _text_input(f"f_{key}", _scalar_val(key)))
        scalar_rows.append(f'<p><label class="k">{_esc(label)}</label>{widget}</p>')
    for key, label in _EDIT_TEXTAREAS:
        scalar_rows.append(f'<p><label class="k">{_esc(label)}</label>'
                           f'<textarea name="f_{key}">{_esc(_scalar_val(key))}</textarea></p>')
    scalar_panel = f'<div class="panel">{"".join(scalar_rows)}</div>'

    panels = []
    for section in _SECTION_ORDER:
        if section in editor_form.MAP_SECTIONS:
            panels.append(_map_section_panel(section, _SECTION_TITLES[section], fields, submitted, err_map))
        elif section in editor_form.LIST_SECTIONS:
            panels.append(_list_section_panel(section, _SECTION_TITLES[section], fields, submitted, err_map))
    for section, title, hint in _EDIT_JSON_ONLY:
        panels.append(_json_only_panel(section, title, hint, fields, err_map))

    csrf = f'<input type="hidden" name="{CSRF_FIELD}" value="{_esc(csrf_token)}">'
    bump = (
        '<p><label class="k">Version bump (a content edit requires a semver-greater version)</label>'
        f'<label><input type="radio" name="bump" value="patch" checked style="width:auto"> patch '
        f'&rarr; {_esc(patch_v)}</label><br>'
        f'<label><input type="radio" name="bump" value="minor" style="width:auto"> minor '
        f'&rarr; {_esc(minor_v)}</label><br>'
        f'<label><input type="radio" name="bump" value="major" style="width:auto"> major '
        f'&rarr; {_esc(major_v)}</label></p>'
    )
    body = (
        f'<h1>Edit metadata — {_esc(slug)}</h1>'
        f'<p class="sub">current version {_esc(cur)} · '
        f'<a href="/gateway/curator/edit/{_esc(slug)}/stations">manage stations (remove EDIs)</a> · '
        f'<a href="/gateway/curator/queue">back to queue</a></p>'
        '<p class="sub">Fill the fields for each section. An empty field is left unchanged; each '
        'section also has an <em>Advanced</em> raw-JSON box that overrides its fields when filled.</p>'
        f'{err}'
        f'<form method="post" action="/gateway/curator/edit/{_esc(slug)}/preview">'
        f'{scalar_panel}'
        f'{"".join(panels)}'
        f'<div class="panel">{bump}'
        '<p><label class="k">Release note (required)</label>'
        '<textarea name="note" placeholder="What changed and why" required></textarea></p>'
        f'{csrf}'
        '<p><button class="b-accent" type="submit">Preview change</button></p>'
        '</div></form>'
        # EXTERNAL same-origin script for the repeatable-row add/remove (strictPages CSP blocks
        # inline JS; the behaviour degrades to the server-rendered spare rows without it).
        '<script src="/gateway/curator/editor.js" defer></script>'
    )
    if nav is not None:
        return _shell(f"AusMT edit {slug}", body, nav=nav)
    return _page(f"AusMT edit {slug}", body)


# ---- C43 Stage 1: survey hub (S1-2) --------------------------------------------------------------
# One hub per survey, two tabs: Overview & QA (landing) and Metadata. A Stations entry in the tab
# strip LINKS to the existing removal page (labelled). NO History tab (Stage 2). The Overview tab is
# populated BROWSER-side from same-origin /data/build_report.json + /data/build.json filtered to this
# survey (the serve-panel pattern — zero new gateway privileges). The Metadata tab splits the editor
# into a sticky section TOC + per-section forms, each POSTing ONLY its own section's widgets to the
# unchanged /edit/{slug}/preview route (the merge seam already scopes the patch to the widgets present
# — verified: a form carrying one section's s_/l_/c_ inputs + its o_<section> snapshot assembles to a
# single-section patch, so no runner-side section-scoped mode is needed).

# C43 Stage 2a: Stations and History are now REAL in-hub tabs (Stage 1 shipped them as a link-out and
# nothing). The tab ORDER matches record D4: Overview & QA (landing) / Stations / Metadata / History.
_HUB_TABS = (("overview", "Overview & QA"), ("stations", "Stations"),
             ("metadata", "Metadata"), ("history", "History"))
_HUB_TAB_KEYS = frozenset(k for k, _ in _HUB_TABS)


# C43-HUB (Q3 ruling, 2026-07-11): the ONE display-layer email heuristic behind all three
# citation-author surfaces — the Overview info row (data-citation-email scaffold attribute), the
# Metadata TOC issue hint, and the Metadata inline field error — so they can never disagree.
# DISPLAY-LAYER ONLY: the server validator and the preview/confirm POST path are untouched (pinned).
_EMAIL_DISPLAY_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# The contract's inline-error copy (H4), rendered verbatim wherever the heuristic fires.
_CITATION_EMAIL_ERROR = ("This looks like an email address — citation authors are published "
                         "verbatim in every station's XML. Use a name; keep the email in Contact.")


def citation_author_email(fields: dict) -> tuple[str, str] | None:
    """(owning_section, offending_value) when the survey's CITATION AUTHOR looks like an email
    address, else None. Mirrors the engine's _investigators_of precedence EXACTLY (build_portal.py):
    lead_investigator.name, when present, IS the citation author baked into every served station
    XML — principal_investigators names are used only when there is no lead. A display heuristic,
    never a validator: the runner-side validation rules are unchanged."""
    li = fields.get("lead_investigator")
    if isinstance(li, dict) and li.get("name"):
        name = str(li["name"]).strip()
        return ("lead_investigator", name) if _EMAIL_DISPLAY_RE.match(name) else None
    for pi in (fields.get("principal_investigators") or []):
        if isinstance(pi, dict) and pi.get("name"):
            name = str(pi["name"]).strip()
            if _EMAIL_DISPLAY_RE.match(name):
                return ("principal_investigators", name)
    return None


def _hub_header(slug: str, *, fields: dict, version: str | None) -> str:
    """The hub header (C43-HUB H1, every tab): the survey TITLE (survey.yaml name/project_name,
    falling back to the slug when the read-job degraded) + a mono slug chip, then the mockup's
    orientation line — 'v<version> · <licence> · <access> · collection <id>' from the metadata
    read-job fields, each segment rendered ONLY when the survey carries the fact (never invented),
    plus a hidden counts span survey-hub.js fills browser-side from build_report
    ('N stations published, M serving' — published = built + dropped, serving = built)."""
    title = slug
    for key in ("name", "project_name"):
        v = fields.get(key)
        if isinstance(v, str) and v.strip():
            title = v.strip()
            break
    h1 = f'<h1>{_esc(title)} <span class="slugchip">{_esc(slug)}</span></h1>'
    segs: list[str] = []
    if version:
        segs.append(f"v{_esc(str(version))}")
    lic = fields.get("license")
    if isinstance(lic, str) and lic.strip():
        segs.append(_esc(lic.strip()))
    acc = fields.get("access")
    if isinstance(acc, dict) and isinstance(acc.get("level"), str) and acc["level"].strip():
        segs.append(_esc(acc["level"].strip()))
    coll = fields.get("collection")
    if isinstance(coll, dict) and isinstance(coll.get("id"), str) and coll["id"].strip():
        segs.append(f'collection <span class="dt">{_esc(coll["id"].strip())}</span>')
    counts = '<span data-hub-counts hidden></span>'
    return (h1 + f'<p class="sub" id="hub-orientation">{" · ".join(segs)}{counts}</p>')


def _hub_tab_strip(slug: str, active: str) -> str:
    """The hub tab strip (C43 Stage 2a; C43-HUB H1 adds the browser-populated Stations chip):
    Overview & QA / Stations / Metadata / History, all in-hub tabs. The Stations entry carries a
    hidden chip slot ([data-stations-chip]) survey-hub.js fills with '<d> dropped · <f> flagged'
    from build_report — hidden at 0/0, so a healthy survey shows no chip. The strip carries the
    slug (data-survey-slug) so the chip/header script works on EVERY tab, not just Overview."""
    parts = [f'<div class="tabs" data-hub-tabs data-survey-slug="{_esc(slug)}">']
    for key, label in _HUB_TABS:
        on = " on" if key == active else ""
        chip = ""
        if key == "stations":
            chip = (f' <span class="badge" data-stations-chip hidden '
                    f'style="background:{_PALETTE["warn"]}"></span>')
        parts.append(
            f'<a class="hubtab{on}" href="/gateway/curator/survey/{_esc(slug)}?tab={key}">'
            f'{_esc(label)}{chip}</a>')
    parts.append("</div>")
    return "".join(parts)


def _hub_overview_body(slug: str, *, citation_email: str | None = None) -> str:
    """The Overview & QA tab body (C43-HUB H2 scaffold). Every value is populated BROWSER-side by
    survey-hub.js from /data/build_report.json filtered to THIS survey (data-survey-slug). The
    server renders only the scaffold + loading placeholders — it has no site-data mount, so it
    cannot read the served corpus (the serve-panel constraint). `citation_email` (the Q3-ruled
    server-side heuristic over the metadata read-job fields) is stamped as data-citation-email so
    the JS can render the mockup's metadata info row from a SERVED fact, never a string-match
    guess. The section sub-lines carry the mockup's framing copy."""
    email_attr = f' data-citation-email="{_esc(citation_email)}"' if citation_email else ""
    return (
        f'<div id="survey-qa" data-survey-slug="{_esc(slug)}"{email_attr}>'
        '<div class="cards" id="qa-cards"><p class="sub">Loading survey health…</p></div>'
        '<div class="panel"><h2>Needs attention</h2>'
        '<p class="sub" style="margin:0 0 .5rem">from build_report, newest build</p>'
        '<div id="qa-attention"><p class="sub">Loading build report…</p></div></div>'
        '<div class="panel"><h2>Conditioning summary</h2>'
        '<p class="sub" style="margin:0 0 .5rem">honesty notes on all served stations</p>'
        '<div id="qa-conditioning"><p class="sub">Loading conditioning notes…</p></div></div>'
        '</div>'
    )


def _hub_stations_body(slug: str, *, build_lag: dict | None = None) -> str:
    """The Stations tab body (C43 S2a-1). Server renders ONLY the scaffold + loading placeholder; the
    filterable station table, drill-down facts panel, hand-built SVG plots, and quadrant verdicts are
    all populated BROWSER-side by stations.js from the served /data corpus (catalogue/sci/tf/build) —
    the serve-panel pattern, zero new gateway privileges. `build_lag` carries the server-rendered
    published HEAD for the [FC-2] lag label (data-published-head): the JS compares it against the
    served build's source_commit and, on drift, renders 'facts from build <id> — publish pending' on
    the panel itself. Degrades: without JS the placeholder stays, the page never breaks."""
    published = (build_lag or {}).get("published_head") or ""
    # C43 FR2-2 scaffold: THREE thirds (owner ruling round 2). The split container carries THREE slots
    # the JS fills: station FACTS (#station-facts, col 2), the PLOTS column (#station-plots-col, col 3),
    # and the site TABLE (#stations-list, col 1). DOM ORDER is FACTS then PLOTS then TABLE — so on a
    # narrow single column they stack facts / plots / table (the panel-first stacking rule preserved);
    # on wide screens .stations-split places each into its grid COLUMN (table left, facts middle, plots
    # right) all on grid-ROW 1 (see shell CSS). The list slot holds the filter box + the fixed-height
    # .st-scroll region the JS builds the table into. Server renders only the scaffold + loading
    # placeholders; stations.js fills them from the served /data corpus (catalogue/sci/tf/build).
    # Degrades: without JS the placeholders stay, the page never breaks.
    return (
        f'<div id="survey-stations" data-survey-slug="{_esc(slug)}" '
        f'data-published-head="{_esc(published)}">'
        '<div class="stations-split">'
        '<div id="station-facts" class="st-facts">'
        '<p class="sub">Select a station from the table to view its facts.</p>'
        '</div>'
        '<div id="station-plots-col" class="st-plots">'
        '<p class="sub">Response curves appear here once a station is selected.</p>'
        '</div>'
        '<div id="stations-list" class="st-list">'
        '<p class="sub">Loading stations from the served corpus…</p>'
        '</div>'
        '</div>'
        '</div>'
        # EXTERNAL same-origin script (strictPages CSP blocks inline JS). Degrades gracefully.
        '<script src="/gateway/curator/stations.js" defer></script>'
    )


def _hub_history_body(*, slug: str, commits: list, error: str = "") -> str:
    """The History tab body (C43 S2a-2): a READ-ONLY table of the survey package's git log — version
    tag/subject, release-note body, when, author. Fully SERVER-RENDERED (the runner already returned
    the parsed commits via the history read-job; no browser JS, so nothing to fetch and nothing to
    inline under the CSP). NO rename/retire actions — those are Stage 4. Every value is _esc'd (a
    commit subject/body is git content rendered into the curator's browser)."""
    if error:
        return (f'<p class="sub" style="color:{_PALETTE["bad"]}">{_esc(error)}</p>'
                '<p class="sub">The read-only audit trail could not be read for this survey.</p>')
    if not commits:
        return ('<p class="sub">No git history for this survey package yet (it may not be under '
                'version control in this checkout).</p>')
    rows = []
    for c in commits:
        body = c.get("body") or ""
        note_html = f'<div class="k" style="white-space:pre-wrap">{_esc(body)}</div>' if body else ""
        # C43-HUB H5 (density polish to the mockup's table): When and Author MERGED into the
        # mockup's single 'When · by' column ('2026-07-10 · ben') — values verbatim from the
        # history read-job, no reformatting. No behaviour change.
        when_by = " · ".join(x for x in (c.get("date") or "", c.get("author") or "") if x)
        rows.append(
            "<tr>"
            f'<td><code>{_esc(c.get("short") or "")}</code></td>'
            f'<td>{_esc(c.get("subject") or "")}{note_html}</td>'
            f'<td class="k dt">{_esc(when_by)}</td>'
            "</tr>")
    table = ('<table><tr><th>Commit</th><th>Change / release note</th><th>When · by</th></tr>'
             + "".join(rows) + "</table>")
    return (
        '<p class="sub">Read-only audit trail — every published change to this survey package '
        '(version bumps, release notes, station removals), newest first. Rename and retirement '
        'actions are not offered here.</p>'
        f'<div class="panel">{table}</div>')


def _toc_state_hint(section: str, fields: dict, flagged_section: str | None) -> str:
    """The TOC state hint (C43-HUB H4): render-time facts only — the issue chip on the section the
    citation-email heuristic flagged, entry COUNTS for list sections, and the access level /
    collection id values. A section with nothing derivable gets no hint (never a placeholder)."""
    from . import editor_form
    if section == flagged_section:
        return '<span class="state issue">1 issue</span>'
    val = fields.get(section)
    if section in editor_form.LIST_SECTIONS and isinstance(val, list) and val:
        return f'<span class="state">{len(val)}</span>'
    if section == "access" and isinstance(val, dict) \
            and isinstance(val.get("level"), str) and val["level"].strip():
        return f'<span class="state">{_esc(val["level"].strip())}</span>'
    if section == "collection" and isinstance(val, dict) \
            and isinstance(val.get("id"), str) and val["id"].strip():
        return f'<span class="state">{_esc(val["id"].strip())}</span>'
    return ""


def _hub_metadata_body(*, slug: str, version: str | None, fields: dict, csrf_token: str,
                       field_errors=None, submitted: dict | None = None,
                       active_section: str | None = None) -> str:
    """The Metadata tab body: a sticky section TOC + one per-section form per section, each with its
    OWN commit tray (bump + required note + Preview) so "only this section is submitted" is literally
    true — the form carries only that section's widgets, and the merge seam scopes the patch to them.
    Every section keeps its advanced-JSON override (inside its panel). Server renders ALL sections
    (fully functional without JS); survey-hub.js enhances the TOC to show one section at a time.
    C43-HUB H4: TOC entries carry render-time state hints (_toc_state_hint), and the section the
    citation-email heuristic flags renders the mockup's inline field error — DISPLAY-LAYER only,
    the same citation_author_email helper the Overview info row uses (they can never disagree)."""
    from . import editor_form
    err_map = _field_error_map(field_errors)
    flag = citation_author_email(fields)
    flagged_section = flag[0] if flag else None
    cur = version or "0.0.0"

    # The scalar panel is its own "section" (id: _scalars) so editing a top-level scalar submits only
    # the f_* fields — the per-section discipline extends to the scalars.
    def _scalar_val(key):
        if submitted is not None and f"f_{key}" in submitted:
            return submitted.get(f"f_{key}")
        v = fields.get(key, "")
        return "" if v is None else v

    scalar_rows = ['<h2>Core fields</h2>']
    for key, label in _EDIT_SCALARS:
        widget = (_license_scalar_widget(_scalar_val(key)) if key == "license"
                  else _text_input(f"f_{key}", _scalar_val(key)))
        scalar_rows.append(f'<p><label class="k">{_esc(label)}</label>{widget}</p>')
    for key, label in _EDIT_TEXTAREAS:
        scalar_rows.append(f'<p><label class="k">{_esc(label)}</label>'
                           f'<textarea name="f_{key}">{_esc(_scalar_val(key))}</textarea></p>')
    scalar_panel_inner = "".join(scalar_rows)

    # (toc key, title, panel-inner-html)
    sections: list[tuple[str, str, str]] = [("_scalars", "Core fields", scalar_panel_inner)]
    for section in _SECTION_ORDER:
        if section in editor_form.MAP_SECTIONS:
            # H4 inline error: the flagged map section's name input goes red with the contract's
            # explanatory copy (the mockup's own example).
            derrs = ({"name": _CITATION_EMAIL_ERROR}
                     if flagged_section == section else None)
            inner = _map_section_panel(section, _SECTION_TITLES[section], fields, submitted,
                                       err_map, display_errs=derrs)
        elif section in editor_form.LIST_SECTIONS:
            derr = _CITATION_EMAIL_ERROR if flagged_section == section else None
            inner = _list_section_panel(section, _SECTION_TITLES[section], fields, submitted,
                                        err_map, display_error=derr)
        else:
            continue
        sections.append((section, _SECTION_TITLES[section], inner))
    for section, title, hint in _EDIT_JSON_ONLY:
        sections.append((section, title, _json_only_panel(section, title, hint, fields, err_map)))

    # The commit tray reused inside EVERY section form (bump + required note + Preview). Its own note
    # + bump per section keeps the submit self-contained ("only this section is submitted").
    patch_v, minor_v, major_v = (_suggest_bump(cur, k) for k in ("patch", "minor", "major"))

    def _tray() -> str:
        return (
            '<div style="border-top:1px solid #2E4254;margin-top:.75rem;padding-top:.75rem">'
            '<p><label class="k">Version bump (a content edit requires a semver-greater version)</label>'
            f'<label><input type="radio" name="bump" value="patch" checked style="width:auto"> patch '
            f'&rarr; {_esc(patch_v)}</label> '
            f'<label><input type="radio" name="bump" value="minor" style="width:auto"> minor '
            f'&rarr; {_esc(minor_v)}</label> '
            f'<label><input type="radio" name="bump" value="major" style="width:auto"> major '
            f'&rarr; {_esc(major_v)}</label></p>'
            '<p><label class="k">Release note (required)</label>'
            '<textarea name="note" placeholder="What changed and why" required></textarea></p>'
            '<p class="sub">Only this section is submitted — Preview shows the exact YAML diff and the '
            'validator verdict before anything commits.</p>'
            '<p><button class="b-accent" type="submit">Preview diff &amp; validate</button></p>'
            '</div>')

    csrf = f'<input type="hidden" name="{CSRF_FIELD}" value="{_esc(csrf_token)}">'
    default_key = active_section or sections[0][0]

    toc_links = []
    forms = []
    for key, title, inner in sections:
        sec_id = f"sec-{_esc(key)}"
        on = " on" if key == default_key else ""
        hint = _toc_state_hint(key, fields, flagged_section)
        toc_links.append(f'<a class="tocitem{on}" href="#{sec_id}" data-hub-section="{_esc(key)}">'
                         f'{_esc(title)}{hint}</a>')
        forms.append(
            f'<form class="hub-section" id="{sec_id}" data-hub-section-form="{_esc(key)}" '
            f'method="post" action="/gateway/curator/edit/{_esc(slug)}/preview">'
            f'<div class="panel">{inner}{_tray()}{csrf}</div>'
            '</form>')

    err = ""
    if err_map:
        err = (f'<p class="sub" style="color:{_PALETTE["bad"]}">Some fields need attention — see the '
               'highlighted section(s).</p>')
    return (
        f'{err}'
        # C43 FR2-1: the Metadata tab rides the wide page, but a form input must NOT stretch to
        # 1600px — the field column is CAPPED to a comfortable form measure (~52rem) while the TOC
        # keeps its 12rem rail; the space to the right of the capped column is left for the TOC and
        # future preview real estate. The wide page is for tables/plots, not for stretching a text
        # input across the whole viewport.
        '<div style="display:flex;gap:1.25rem;align-items:flex-start">'
        f'<nav class="toc" id="hub-toc" style="flex:0 0 12rem">{"".join(toc_links)}</nav>'
        f'<div style="flex:1 1 auto;min-width:0;max-width:52rem" id="hub-sections">'
        f'{"".join(forms)}</div>'
        '</div>'
        # C41 D2: the danger zone lives at the BOTTOM of the Metadata tab (destructive ops beside the
        # editing surface; History stays read-only), collapsed + visually separated.
        + _hub_danger_zone(slug)
        # editor.js only — survey-hub.js is included ONCE by render_survey_hub for every tab
        # (C43-HUB: the header counts + Stations chip need it hub-wide).
        + '<script src="/gateway/curator/editor.js" defer></script>'
    )


def _hub_danger_zone(slug: str) -> str:
    """The Metadata tab's danger zone (C41 D2): a collapsed, visually-separated <details> whose only
    affordance is a link to the retirement confirmation page (which carries the typed-slug + note +
    TOTP gate). No form or destructive control here — a single click only OPENS the confirmation
    page. The link is inline-styled (the button classes rely on the `button{}` base rules an <a> does
    not inherit)."""
    bad = _PALETTE["bad"]
    return (
        f'<details style="margin-top:2rem;border:1px solid {bad};border-radius:8px;padding:1rem;'
        'background:rgba(168,84,84,.08)">'
        f'<summary style="cursor:pointer;color:{bad};font-weight:600">Danger zone</summary>'
        '<p class="sub" style="margin:.75rem 0 .5rem">Retiring a survey removes its ENTIRE package '
        'from the repository in one commit (reversible by <code>git revert</code>). It requires a '
        'typed confirmation, a release note, and your authenticator code.</p>'
        f'<p><a href="/gateway/curator/survey/{_esc(slug)}/retire" '
        f'style="display:inline-block;background:{bad};color:#fff;padding:.5rem 1rem;'
        'border-radius:6px;font-weight:600;text-decoration:none">Remove survey…</a></p>'
        '</details>')


def render_survey_hub(*, slug: str, tab: str, version: str | None, fields: dict, csrf_token: str,
                      nav: "NavContext", field_errors=None, submitted: dict | None = None,
                      active_section: str | None = None, commits: list | None = None,
                      history_error: str = "", build_lag: dict | None = None) -> str:
    """The per-survey hub (C43 Stage 1 S1-2 + Stage 2a + the C43-HUB mockup treatment). `tab`
    selects Overview & QA (default) / Stations / Metadata / History. Rendered inside the nav shell
    under ONE mockup-shaped header for every tab — the survey title + slug chip + orientation line
    (_hub_header, from the metadata read-job `fields`/`version`; the header DEGRADES to the slug
    when the read-job failed on a non-metadata tab). The Overview + Stations tabs are browser-
    populated from the served /data corpus (the serve-panel pattern, zero new gateway privileges);
    the Metadata tab is the per-section editor; the History tab is server-rendered from the runner
    history read-job (`commits`). `build_lag` (S2a-1 [FC-2]) carries the served-vs-published label
    state the Stations JS renders when served ≠ published. survey-hub.js loads ONCE for every tab
    (header counts + Stations chip are hub-wide); it degrades to the server-rendered scaffold."""
    tab = tab if tab in _HUB_TAB_KEYS else "overview"
    fields = fields or {}
    head = _hub_header(slug, fields=fields, version=version)
    strip = _hub_tab_strip(slug, tab)
    citation = citation_author_email(fields)
    if tab == "metadata":
        inner = _hub_metadata_body(slug=slug, version=version, fields=fields, csrf_token=csrf_token,
                                   field_errors=field_errors, submitted=submitted,
                                   active_section=active_section)
    elif tab == "stations":
        inner = _hub_stations_body(slug, build_lag=build_lag)
    elif tab == "history":
        inner = _hub_history_body(slug=slug, commits=commits or [], error=history_error)
    else:
        inner = _hub_overview_body(slug, citation_email=citation[1] if citation else None)
    # EXTERNAL same-origin script, ONCE per page (strictPages CSP blocks inline JS). Degrades:
    # placeholders/scaffolds remain, the page never breaks.
    body = f'{head}{strip}{inner}<script src="/gateway/curator/survey-hub.js" defer></script>'
    # C43 FR2-1: EVERY hub tab fills the viewport (wide-by-default via _shell). The Metadata tab keeps
    # a comfortable FORM measure INSIDE the wide page (the TOC form caps its own field column — see
    # _hub_metadata_body), so a form input never stretches to 1600px while the Stations/Overview/
    # History tabs use the full width for their tables and the three-thirds split.
    return _shell(f"AusMT survey {slug}", body, nav=nav)


def render_edit_preview(*, slug: str, version: str, diff: str, validate_report: dict | None,
                        has_fail: bool, new_sha256: str, note: str, patch_json: str,
                        bump: str, csrf_token: str, nav: "NavContext | None" = None) -> str:
    """The preview (C31 §1.4): the unified diff (escaped, no truncation), the validator verdict, and
    — only when the validator did NOT FAIL — a confirm form carrying the §0.6 content hash + the
    patch/bump/note needed to reproduce the exact bytes at commit. A FAIL shows the report and NO
    confirm button (and the server 409s regardless — the button absence is UX)."""
    csrf = f'<input type="hidden" name="{CSRF_FIELD}" value="{_esc(csrf_token)}">'
    diff_panel = (f'<div class="panel"><h2>Changes to survey.yaml</h2>'
                  f'<pre>{_esc(diff)}</pre></div>')
    verdict = _reports_panel(validate_report=validate_report, preview_summary=None)
    if has_fail:
        banner = (f'<p style="color:{_PALETTE["bad"]};font-weight:600">'
                  'The validator FAILED on the edited survey — this change cannot be published. '
                  'Go back and fix the values.</p>')
        confirm = ""
    else:
        banner = (f'<p style="color:{_PALETTE["ok"]};font-weight:600">'
                  'Validator passed (WARNINGs, if any, do not block). Confirm to commit.</p>')
        confirm = (
            f'<div class="panel"><h2>Commit &amp; push</h2>'
            f'<p class="sub">Committed to surveys-live — the serve-reconcile agent serves it on its '
            'next tick (or run <code>make rebuild-data</code> by hand).</p>'
            f'<form method="post" action="/gateway/curator/edit/{_esc(slug)}/confirm">'
            f'{csrf}'
            f'<input type="hidden" name="new_sha256" value="{_esc(new_sha256)}">'
            f'<input type="hidden" name="bump" value="{_esc(bump)}">'
            f'<input type="hidden" name="patch_json" value="{_esc(patch_json)}">'
            f'<input type="hidden" name="note" value="{_esc(note)}">'
            '<p><button class="b-ok" type="submit">Confirm &amp; commit</button></p>'
            '</form></div>'
        )
    body = (
        f'<h1>Preview edit — {_esc(slug)}</h1>'
        f'<p class="sub">new version {_esc(version)} · '
        f'<a href="/gateway/curator/edit/{_esc(slug)}">back to edit form</a> · '
        f'<a href="/gateway/curator/queue">queue</a></p>'
        f'{banner}{diff_panel}{verdict}{confirm}'
    )
    if nav is not None:
        return _shell(f"AusMT preview {slug}", body, nav=nav)
    return _page(f"AusMT preview {slug}", body)


def render_edit_list(*, curator_name: str, slugs: list, csrf_token: str,
                     nav: "NavContext | None" = None) -> str:
    """The Surveys list (C43 Stage 1 S1-1; C43 FR2-1 makes it a proper TABLE). Server-rendered from a
    DIRECTORY LISTING of surveys-live (never content parsing — the survey.yaml presence is a stat, not
    a load), so the server knows only the slugs. The richer columns — display name, version, licence,
    and served station count — are filled BROWSER-side by surveys-list.js from the served /data corpus
    (surveys.json + build_report.json; the serve-panel pattern, zero new gateway privileges). ABSENT
    facts render absent ('—'), never invented: a survey not yet in the served corpus shows only its
    slug. Every row links to the per-survey HUB (the task home), NOT the edit form."""
    if slugs:
        rows = []
        for s in slugs:
            slug = _esc(s)
            rows.append(
                f'<tr data-survey-slug="{slug}">'
                f'<td><a href="/gateway/curator/survey/{slug}">'
                f'<span data-cell="name">{slug}</span></a></td>'
                f'<td><span class="slugchip">{slug}</span></td>'
                f'<td><span data-cell="version">&mdash;</span></td>'
                f'<td><span data-cell="licence">&mdash;</span></td>'
                f'<td><span data-cell="stations">&mdash;</span></td>'
                "</tr>")
        listing = (
            '<table id="surveys-table"><tr><th>Survey</th><th>Slug</th><th>Version</th>'
            '<th>Licence</th><th>Stations</th></tr>'
            + "".join(rows) + "</table>"
            '<p class="sub" style="margin:.6rem 0 0">Name, version, licence and served station count '
            'are read from the live served corpus; a survey not yet built into the corpus shows only '
            'its slug.</p>')
    else:
        listing = '<p class="sub">No published surveys in surveys-live.</p>'
    body = (
        '<h1>Surveys</h1>'
        f'<p class="sub">Signed in as curator:{_esc(curator_name)}</p>'
        f'<div class="panel">{listing}</div>'
        # EXTERNAL same-origin script (strictPages CSP blocks inline JS). Degrades: without it every
        # row still shows its slug + the hub link, the page never breaks.
        '<script src="/gateway/curator/surveys-list.js" defer></script>'
    )
    if nav is not None:
        return _shell("AusMT surveys", body, nav=nav)
    return _page("AusMT surveys", body)


# ---- C43 Stage 3a collections console (record D5-A) -----------------------------------------------
# Two READ-ONLY server-rendered views over the runner's collections projection: the index (summary
# cards + list table + inconsistency bands) and the per-id detail (rollup facts + member/Declares
# table + callouts). NO write controls in 3a — creation/edit/merge/normalise are Stage 3b. ZERO JS:
# the whole surface is server-rendered (the strictPages CSP is script-src 'self').
# The projection has no collection OBJECT: the id lives in each member's survey.yaml, so a "collection"
# here is a rollup keyed by exact collection.id. Membership is by SLUG (read live from surveys-live),
# never the rollup's display labels (the labels-vs-slugs trap that broke the stations tab, hotfix #33).

# The programme fields whose per-member divergence the console marks with a ◆ (record D5-A A4). Kept in
# sync with the runner's _COLLECTION_DIVERGENCE_FIELDS. F2 (D5-C): `last_updated` is EXCLUDED — it is a
# gateway-managed per-member timestamp, not a curator-reconcilable programme field (a Normalise on it
# would have no form field to fix); it is never a divergence the console reports.
_COLLECTION_FIELDS = ("title", "type", "status", "start_year", "description")
_COLLECTION_FIELD_LABELS = {"title": "title", "type": "type", "status": "status",
                            "start_year": "start year", "description": "description"}


def _collection_status_chip(status) -> str:
    """The rollup status as a coloured chip (active/completed/archived); a missing/out-of-vocab status
    (the engine drops those from the rollup) renders a muted 'no status' chip rather than an empty
    cell, so the read is never ambiguous."""
    s = str(status) if status not in (None, "") else ""
    cls = {"active": "s-active", "completed": "s-completed",
           "archived": "s-archived"}.get(s, "s-unknown")
    label = s if s else "no status"
    return f'<span class="statuschip {cls}"><span class="d"></span>{_esc(label)}</span>'


def _collection_href(cid: str) -> str:
    return f"/gateway/curator/collections/{_url_quote(cid)}"


def _divergence_summary(divergence: dict) -> str:
    """A human phrase for a collection's per-field divergence: e.g.
    '2 titles (AusLAMP ×1, AusLAMP Project ×1) · 2 statuses (active ×1, completed ×1)'. Every value is
    escaped. Empty divergence yields '' (caller renders no band)."""
    parts = []
    for fld in _COLLECTION_FIELDS:
        buckets = divergence.get(fld)
        if not buckets:
            continue
        label = _COLLECTION_FIELD_LABELS.get(fld, fld)
        breakdown = ", ".join(
            f'<span class="mono">{_esc(b.get("value"))}</span> &times;{len(b.get("members") or [])}'
            for b in buckets)
        parts.append(f'{len(buckets)} <b>{_esc(label)}</b> values ({breakdown})')
    return " &middot; ".join(parts)


def _near_dup_group_for(cid: str, near_duplicates: list) -> list | None:
    for group in near_duplicates or []:
        if cid in group:
            return group
    return None


def _merge_link_html(group: list, collections: dict) -> str:
    """The 'Merge into <majority>' entry point (record E) for one near-duplicate id group: a link into
    the MINORITY collection's editor with the majority id pre-filled in the id field — a rename that
    rewrites the minority members onto the canonical id (same preview -> publish flow). Majority = the
    group id with the most members; ties break on sort order (deterministic)."""
    def _n(gid):
        return int((collections.get(gid) or {}).get("n_surveys") or 0)
    majority = max(sorted(group), key=_n)
    links = []
    for minority in group:
        if minority == majority:
            continue
        href = f"{_collection_href(minority)}?id={_url_quote(majority)}"
        links.append(f'<a href="{_esc(href)}">Merge <span class="mono">{_esc(minority)}</span> into '
                     f'<span class="mono">{_esc(majority)}</span>&hellip;</a>')
    return " &middot; ".join(links)


def render_collections_index(*, collections: dict, near_duplicates: list,
                             nav: "NavContext") -> str:
    """The collections index (record D5-A A1). Summary cards, the two inconsistency bands (id
    near-duplicates + per-field divergence, each with its one-click remedy — record E: Merge /
    Normalise link into the editor with the canonical value pre-filled), the list table, and the
    'New collection…' entry (record A5). An empty corpus renders a clean 'No collections yet' state,
    never an error (matches the engine's collections.json == {})."""
    collections = collections or {}
    near_duplicates = near_duplicates or []
    # Summary tallies.
    n_coll = len(collections)
    n_members = sum(int(c.get("n_surveys") or 0) for c in collections.values())
    n_stations = sum(int(c.get("n_stations") or 0) for c in collections.values())
    attention = {cid for cid, c in collections.items() if c.get("divergence")}
    for group in near_duplicates:
        attention.update(group)
    n_attention = len(attention)
    att_cls = ' class="n warn"' if n_attention else ' class="n"'
    cards = (
        '<div class="cards">'
        f'<div class="card"><div class="n">{n_coll}</div><div class="l">Collections</div></div>'
        f'<div class="card"><div class="n">{n_members}</div><div class="l">Member surveys</div></div>'
        f'<div class="card"><div class="n">{n_stations}</div><div class="l">Published stations</div></div>'
        f'<div class="card"><div{att_cls}>{n_attention}</div><div class="l">Need attention</div></div>'
        '</div>'
    )

    if not collections:
        body = (
            '<h1>Collections</h1>'
            '<p class="sub">Programme groupings, rolled up from every published '
            '<span class="mono">survey.yaml</span> at the current published HEAD.</p>'
            + cards +
            '<div style="margin:1rem 0">'
            '<a class="b-accent" style="display:inline-block;padding:.5rem 1rem;border-radius:6px;'
            f'color:{_PALETTE["bg"]};font-weight:600" href="/gateway/curator/collections/new">'
            'New collection&hellip;</a></div>'
            '<div class="panel"><p class="sub" style="margin:0">No collections yet. A survey joins a '
            'collection by declaring a <span class="mono">collection</span> block in its '
            '<span class="mono">survey.yaml</span> — start one with <b>New collection…</b> above (it '
            'assigns the block to the surveys you pick), or a survey declares it directly.</p></div>'
        )
        return _shell("AusMT collections", body, nav=nav)

    # Inconsistency bands. (a) id near-duplicates.
    bands = []
    for group in near_duplicates:
        named = " and ".join(
            f'<span class="mono">{_esc(gid)}</span> ({int((collections.get(gid) or {}).get("n_surveys") or 0)} '
            f'survey{"s" if int((collections.get(gid) or {}).get("n_surveys") or 0) != 1 else ""})'
            for gid in group)
        bands.append(
            '<div class="cband">'
            f'<b>&#9888; Near-duplicate ids</b> &mdash; {named} differ only by case or whitespace. '
            'The portal groups by exact id, so this splits one programme into separate collections.'
            '<span class="why">A reader browsing programmes sees the same name more than once, each '
            'with a partial member list.</span>'
            f'<span class="fix">{_merge_link_html(group, collections)}</span>'
            '</div>')
    # (b) per-field divergence, one band per collection that disagrees.
    for cid, c in collections.items():
        summary = _divergence_summary(c.get("divergence") or {})
        if not summary:
            continue
        title = c.get("title") or cid
        bands.append(
            '<div class="cband">'
            f'<b>&#9888; Members disagree within &ldquo;{_esc(title)}&rdquo;</b> &mdash; {summary}.'
            '<span class="why">The rollup takes whichever member builds first — readers may see '
            'either. This is silent on the portal today.</span>'
            f'<span class="fix"><a href="{_esc(_collection_href(cid))}">Review &amp; '
            'normalise&hellip;</a></span>'
            '</div>')
    bands_html = "".join(bands)

    # List table.
    rows = []
    for cid in collections:
        c = collections[cid]
        title = c.get("title") or cid
        n_surv = int(c.get("n_surveys") or 0)
        mixed = ' <span class="mixed">&middot; mixed</span>' if c.get("divergence") else ""
        rows.append(
            '<tr class="rowlink">'
            f'<td><a href="{_esc(_collection_href(cid))}"><b>{_esc(title)}</b></a> '
            f'<span class="mono" style="color:{_PALETTE["muted"]}">{_esc(cid)}</span></td>'
            f'<td>{_esc(c.get("type")) if c.get("type") else "&mdash;"}</td>'
            f'<td class="num">{n_surv} survey{"s" if n_surv != 1 else ""}</td>'
            f'<td class="num">{int(c.get("n_stations") or 0)}</td>'
            f'<td>{_collection_status_chip(c.get("status"))}{mixed}</td>'
            '</tr>')
    table = (
        '<div class="panel"><table>'
        '<tr><th>Collection</th><th>Type</th><th>Members</th><th>Stations</th><th>Status</th></tr>'
        + "".join(rows) + '</table></div>'
        '<p class="sub" style="margin:.6rem 0 0">Membership is resolved by survey <b>slug</b>, read '
        'live from surveys-live via a runner read-job — never the rollup\'s display labels.</p>'
    )

    body = (
        '<h1>Collections</h1>'
        '<p class="sub">Rolled up from every published <span class="mono">survey.yaml</span> at the '
        'current published HEAD — the edit truth. There is no collection object in the data model: the '
        'id lives in each member\'s <span class="mono">survey.yaml</span>, so a collection is a '
        'projection over its members. Station counts are the <b>published</b> EDI-file counts; the '
        'served portal may differ until the next rebuild.</p>'
        + cards
        + '<div style="margin:1rem 0">'
          '<a class="b-accent" style="display:inline-block;padding:.5rem 1rem;border-radius:6px;'
          f'color:{_PALETTE["bg"]};font-weight:600" href="/gateway/curator/collections/new">'
          'New collection&hellip;</a></div>'
        + bands_html + table
    )
    return _shell("AusMT collections", body, nav=nav)


_COLLECTION_TYPE_VOCAB = ("programme", "release", "institutional", "other")
_COLLECTION_STATUS_VOCAB = ("active", "completed", "archived")


def _select_html(name: str, options, selected, *, blank_label: str) -> str:
    """A <select> with a leading '(unset)' blank option — used for type/status where the rollup value
    may be absent. `selected` is the currently-selected value (or None/''). Every value escaped."""
    sel = str(selected) if selected not in (None, "") else ""
    opts = [f'<option value=""{" selected" if sel == "" else ""}>{_esc(blank_label)}</option>']
    for o in options:
        mark = " selected" if o == sel else ""
        opts.append(f'<option value="{_esc(o)}"{mark}>{_esc(o)}</option>')
    return f'<select name="{_esc(name)}">' + "".join(opts) + "</select>"


def _diverge_line(divergence: dict, canonical, fld: str) -> str:
    """The ◆ 'N members differ' hint under an editable field (view 2). Names the outlier value(s) that
    disagree with the canonical (form) value; empty when the field agrees across members. Every value
    escaped."""
    buckets = (divergence or {}).get(fld)
    if not buckets:
        return ""
    parts = []
    for b in buckets:
        val = b.get("value")
        if val == canonical:
            continue  # the canonical value is not an outlier
        members = b.get("members") or []
        who = ", ".join(_esc(m) for m in members)
        parts.append(f'&ldquo;{_esc(val)}&rdquo; &mdash; {who}')
    if not parts:
        return ""
    return ('<div class="diverge"><span>&#9670;</span><div><b>Members differ:</b> '
            + " &middot; ".join(parts)
            + '. Saving sets every member to the value above.</div></div>')


def _collection_form_fields(*, collection: dict, prefill_id: str | None, divergence: dict,
                            n_surv: int, is_new: bool) -> str:
    """The fan-out edit form fields (view 2): title / id (lowercase-hyphenated + fan-out disclosure) /
    type / status / start year / description, seeded with the rollup (canonical) values and marked with
    ◆ divergence hints. `prefill_id` overrides the id field (the Merge entry point pre-fills the
    canonical id). Shared by the editor and the create form (create passes an empty collection)."""
    c = collection or {}
    title_v = _esc(c.get("title") or "")
    id_v = _esc(prefill_id if prefill_id else (c.get("id") or ""))
    start_v = _esc(c.get("start_year") or "")
    desc_v = _esc(c.get("description") or "")
    fanout = ("" if is_new else
              f'Changing the id rewrites {n_surv} member <span class="mono">survey.yaml</span>'
              f'{"s" if n_surv != 1 else ""} — shown as one batched confirm. ')
    return (
        '<div class="formrow"><label>Title</label><div>'
        f'<input name="f_title" value="{title_v}">'
        + _diverge_line(divergence, c.get("title"), "title") +
        '</div></div>'
        '<div class="formrow"><label>Id (slug)</label><div>'
        f'<input class="mono" name="f_id" value="{id_v}">'
        f'<div class="hint">{fanout}Must be lowercase-hyphenated '
        '(<span class="mono">a&ndash;z 0&ndash;9 -</span>).</div>'
        '</div></div>'
        '<div class="formrow"><label>Type</label><div>'
        + _select_html("f_type", _COLLECTION_TYPE_VOCAB, c.get("type"), blank_label="(unset)")
        + _diverge_line(divergence, c.get("type"), "type") +
        '</div></div>'
        '<div class="formrow"><label>Status</label><div>'
        + _select_html("f_status", _COLLECTION_STATUS_VOCAB, c.get("status"), blank_label="(unset)")
        + _diverge_line(divergence, c.get("status"), "status") +
        '</div></div>'
        '<div class="formrow"><label>Start year</label><div>'
        f'<input class="num" name="f_start_year" value="{start_v}" style="max-width:8rem">'
        + _diverge_line(divergence, c.get("start_year"), "start_year") +
        '</div></div>'
        '<div class="formrow"><label>Description</label><div>'
        f'<textarea name="f_description" style="min-height:6rem">{desc_v}</textarea>'
        '<div class="hint">The reader-facing programme summary shown on the portal\'s collection '
        'page. Fans out to every member like the other fields.</div>'
        + _diverge_line(divergence, c.get("description"), "description") +
        '</div></div>'
    )


def _membership_manager(*, members: list, candidates: list, cid: str, is_new: bool) -> str:
    """The two-column membership manager (record A3): current members (each a keep checkbox, checked;
    unchecking stages a removal) beside a SEARCHABLE candidate picker (add checkboxes) over surveys NOT
    already in this collection, each showing `no collection` vs `in "<id>" -> moves`. The filter is the
    ONLY JS (external collections.js). `members` is the collection's current member list (by SLUG);
    `candidates` is every published survey with its current_collection_id."""
    # Current-members column (omitted for a brand-new collection).
    cur_col = ""
    if not is_new:
        mrows = []
        for m in members:
            slug = m.get("slug")
            n_stn = int(m.get("n_stations") or 0)
            mrows.append(
                '<tr class="memrow">'
                f'<td><input type="checkbox" name="keep" value="{_esc(slug)}" checked '
                'title="untick to remove from this collection"></td>'
                f'<td class="mono">{_esc(slug)}</td>'
                f'<td class="num">{n_stn}</td></tr>')
        cur_col = (
            '<div class="mcol">'
            f'<div class="ph2">In this collection <span class="c">&middot; {len(members)} '
            f'survey{"s" if len(members) != 1 else ""}</span></div>'
            '<div class="mscroll"><table>'
            '<tr><th>keep</th><th>Survey</th><th>Stations</th></tr>'
            + "".join(mrows) + '</table></div></div>')

    # Candidate picker: every published survey NOT already a member of THIS collection.
    member_slugs = {m.get("slug") for m in (members or [])}
    prows = []
    for s in candidates or []:
        slug = s.get("slug")
        if slug in member_slugs:
            continue
        cur = s.get("current_collection_id")
        if cur:
            currently = (f'<span class="badge-move">in &ldquo;{_esc(cur)}&rdquo; &rarr; moves</span>')
        else:
            currently = '<span class="badge-none">no collection</span>'
        n_stn = int(s.get("n_stations") or 0)
        # data-slug + data-cur feed the filter (textContent match on slug + current id).
        prows.append(
            f'<tr class="memrow" data-filter="{_esc(str(slug) + " " + str(cur or ""))}">'
            f'<td><input type="checkbox" name="add" value="{_esc(slug)}"></td>'
            f'<td class="mono">{_esc(slug)}</td>'
            f'<td class="num">{n_stn}</td>'
            f'<td>{currently}</td></tr>')
    pick_col = (
        '<div class="mcol">'
        '<div class="ph2">Add surveys <span class="c">&middot; search, then check</span></div>'
        '<input class="mfilter" id="cand-filter" placeholder="filter surveys by name or slug&hellip;" '
        'autocomplete="off">'
        '<div class="mscroll"><table id="cand-table">'
        '<tr><th>add</th><th>Survey</th><th>Stations</th><th>Currently</th></tr>'
        + ("".join(prows) if prows else
           '<tr><td colspan="4" class="badge-none" style="padding:.6rem .75rem">'
           'no other published surveys to add</td></tr>')
        + '</table></div></div>')
    return (
        f'<h2 style="margin-top:1.5rem">Members <span style="color:{_PALETTE["muted"]};'
        'font-weight:400">&middot; manage which surveys belong</span></h2>'
        '<div class="memberwrap">' + cur_col + pick_col + '</div>'
        '<p class="sub" style="margin:.6rem 0 0">Adding a survey that already belongs to another '
        'collection <b>moves</b> it (its <span class="mono">collection.id</span> changes) — the picker '
        'says so before you commit. Everything here stages into ONE atomic batch: nothing is written '
        'until you Preview and Publish.</p>')


def render_collection_detail(*, cid: str, collection: dict, candidates: list, near_duplicates: list,
                             csrf_token: str, prefill_id: str | None = None, error: str = "",
                             nav: "NavContext") -> str:
    """The collection EDITOR (record D5-A A3/A6, owner-approved preview view 2). Turns the Stage-3a
    read-only detail into ONE desired-end-state form: the fan-out field inputs (seeded with the rollup
    values, ◆ divergence hints), the two-column membership manager (keep/remove + a searchable add
    picker), and the required release note. Preview POSTs the whole form; the server computes the delta
    and renders the batch-diff confirm. The form state IS the staged state (no client-side staging) —
    the ONLY JS is the candidate-picker filter. `prefill_id` pre-fills the id field (the Merge entry
    point). The handler 404s an unknown id before this renderer is reached."""
    near_duplicates = near_duplicates or []
    title = collection.get("title") or cid
    n_surv = int(collection.get("n_surveys") or 0)
    n_stn = int(collection.get("n_stations") or 0)
    divergence = collection.get("divergence") or {}
    header = (
        f'<h1>{_esc(title)} '
        f'<span style="color:{_PALETTE["muted"]};font-weight:400">&middot; {n_surv} '
        f'member{"s" if n_surv != 1 else ""} &middot; {n_stn} stations</span> '
        f'{_collection_status_chip(collection.get("status"))}</h1>'
        '<p class="sub">Edit fields and membership below, then preview. Every change fans out across '
        'the member <span class="mono">survey.yaml</span>s as ONE atomic, validator-checked batch — '
        'any member failing validation blocks the whole batch. Published-source: rolled up from every '
        'member at the current published HEAD; the served portal may differ until the next rebuild.</p>'
    )
    err_html = (f'<div class="cband"><b>&#9888; {_esc(error)}</b></div>') if error else ""

    # Per-collection inconsistency callouts (now actionable IN this editor).
    callouts = []
    group = _near_dup_group_for(cid, near_duplicates)
    if group:
        others = " and ".join(f'<span class="mono">{_esc(g)}</span>' for g in group if g != cid)
        callouts.append(
            '<div class="cband">'
            f'<b>&#9888; Near-duplicate id</b> &mdash; this id collides with {others} '
            '(differs only by case or whitespace). To merge, change the <b>Id</b> field below to the '
            'canonical id and preview — that rewrites this collection\'s members onto it.</div>')
    summary = _divergence_summary(divergence)
    if summary:
        callouts.append(
            '<div class="cband">'
            f'<b>&#9888; Members disagree</b> &mdash; {summary}. The fields below hold the canonical '
            '(first-declarer) value; previewing normalises every &#9670; member to it.</div>')
    callouts_html = "".join(callouts)

    csrf = f'<input type="hidden" name="{CSRF_FIELD}" value="{_esc(csrf_token)}">'
    members = collection.get("members") or []
    rendered_members = _json.dumps([m.get("slug") for m in members])
    form = (
        f'<form method="post" action="/gateway/curator/collections/{_url_quote(cid)}/preview">'
        f'{csrf}'
        f'<input type="hidden" name="rendered_members" value="{_esc(rendered_members)}">'
        '<div class="panel"><div class="ph">Edit collection '
        f'<span class="go" style="color:{_PALETTE["muted"]};font-size:.78rem;font-weight:400;'
        'margin-left:auto">changes fan out to every member survey</span></div>'
        '<div class="pb">'
        + _collection_form_fields(collection=collection, prefill_id=prefill_id,
                                  divergence=divergence, n_surv=n_surv, is_new=False)
        + _membership_manager(members=members, candidates=candidates, cid=cid, is_new=False)
        + '<div class="formrow" style="margin-top:1rem;border:0"><label>Release note</label><div>'
        '<input name="note" placeholder="Why (required) — written to every commit in the batch" '
        'style="max-width:52rem" required>'
        '<div class="hint">Required. One shared note is written to every commit in the batch.</div>'
        '</div></div>'
        '<div class="fnote"><b>Preview shows one combined diff across every affected member</b> '
        '(N commits, one shared release note), validator-checked per survey. The batch is '
        '<b>atomic</b>: any member failing validation blocks it — nothing commits. Unchanged members '
        'get no commit.</div>'
        '<div class="btnrow">'
        '<button class="b-accent" type="submit">Preview batch diff&hellip;</button>'
        '<a class="ghost" style="display:inline-block;padding:.5rem 1rem;border-radius:6px" '
        'href="/gateway/curator/collections">Cancel</a>'
        '</div>'
        '</div></div></form>'
    )

    body = (header + err_html + callouts_html + form
            + '<script src="/gateway/curator/collections.js" defer></script>')
    return _shell(f"AusMT collection · {cid}", body, nav=nav)


def render_collection_create(*, candidates: list, csrf_token: str, error: str = "",
                             nav: "NavContext") -> str:
    """The create form (record A5): a collection with no members cannot exist, so this collects the
    details AND an initial member set (≥1) — the same fan-out form + candidate picker as the editor,
    minus a current-members column. Preview POSTs to /collections/new/preview; the server refuses zero
    members (400). The ONLY JS is the candidate-picker filter."""
    csrf = f'<input type="hidden" name="{CSRF_FIELD}" value="{_esc(csrf_token)}">'
    err_html = (f'<div class="cband"><b>&#9888; {_esc(error)}</b></div>') if error else ""
    header = (
        '<h1>New collection</h1>'
        '<p class="sub">There is no collection object in the data model — a collection exists only '
        'because its members declare it. So this sets the <span class="mono">collection</span> block '
        'on the survey(s) you pick (at least one), as ONE atomic, validator-checked batch.</p>'
    )
    form = (
        '<form method="post" action="/gateway/curator/collections/new/preview">'
        f'{csrf}'
        '<input type="hidden" name="rendered_members" value="[]">'
        '<div class="panel"><div class="ph">New collection details</div><div class="pb">'
        + _collection_form_fields(collection={}, prefill_id=None, divergence={}, n_surv=0, is_new=True)
        + _membership_manager(members=[], candidates=candidates, cid="", is_new=True)
        + '<div class="formrow" style="margin-top:1rem;border:0"><label>Release note</label><div>'
        '<input name="note" placeholder="Why (required) — written to every commit in the batch" '
        'style="max-width:52rem" required>'
        '<div class="hint">Required. One shared note is written to every member\'s commit.</div>'
        '</div></div>'
        '<div class="fnote"><b>Pick at least one member.</b> Preview shows the combined diff across '
        'the chosen surveys (one commit each, one shared release note), validator-checked per survey — '
        'the batch is atomic.</div>'
        '<div class="btnrow">'
        '<button class="b-accent" type="submit">Preview batch diff&hellip;</button>'
        '<a class="ghost" style="display:inline-block;padding:.5rem 1rem;border-radius:6px" '
        'href="/gateway/curator/collections">Cancel</a>'
        '</div>'
        '</div></div></form>'
        '<script src="/gateway/curator/collections.js" defer></script>'
    )
    body = header + err_html + form
    return _shell("AusMT new collection", body, nav=nav)


def render_collection_batch_preview(*, cid: str, is_new: bool, results: list, note: str,
                                    spec_json: str, expected_shas_json: str, has_fail: bool,
                                    csrf_token: str, nav: "NavContext") -> str:
    """The batch-diff confirm (record D5-A A6, owner-approved preview view 3): the combined per-survey
    diff, a per-survey validator verdict (PASS/FAIL), the N-commits / one-shared-note disclosure, the
    release note, and — only when EVERY affected survey passed — a Publish button. A FAIL shows the
    verdict and NO publish button (and the server 409s regardless — the button absence is UX). `results`
    are the CHANGED surveys only; `spec_json`/`expected_shas_json` are carried to the publish POST so it
    re-applies + re-validates under the lock (TOCTOU guard — it does NOT trust this preview)."""
    changed = [r for r in results if r.get("changed")]
    n = len(changed)
    action = ("/gateway/curator/collections/new/publish" if is_new
              else f"/gateway/curator/collections/{_url_quote(cid)}/publish")
    back = ("/gateway/curator/collections/new" if is_new
            else f"/gateway/curator/collections/{_url_quote(cid)}")

    # Combined diff — one block per changed survey (escaped, no truncation).
    diff_blocks = []
    for r in changed:
        eff = r.get("effect") or "edit"
        diff_blocks.append(
            f'<div style="font-weight:600;font-size:.82rem;margin:.6rem 0 .2rem">'
            f'<span class="mono">{_esc(r.get("slug"))}</span> '
            f'<span style="color:{_PALETTE["muted"]};font-weight:400">&middot; {_esc(eff)} &middot; '
            f'&rarr; {_esc(r.get("new_version") or "")}</span></div>'
            f'<pre>{_esc(r.get("diff") or "")}</pre>')
    diff_panel = (
        '<div class="panel"><div class="ph">Combined diff '
        f'<span class="go" style="color:{_PALETTE["muted"]};font-size:.78rem;font-weight:400;'
        f'margin-left:auto">{n} survey.yaml{"s" if n != 1 else ""} &middot; {n} '
        f'commit{"s" if n != 1 else ""} &middot; 1 shared release note</span></div>'
        '<div class="pb">' + "".join(diff_blocks) + '</div></div>')

    # Per-survey validator verdicts.
    vrows = []
    for r in changed:
        if r.get("has_fail"):
            mark = '<span class="cross">&#10007;</span>'
            verdict = f'<span style="margin-left:auto;color:{_PALETTE["bad"]}">FAIL</span>'
        else:
            mark = '<span class="tick">&#10003;</span>'
            verdict = f'<span style="margin-left:auto;color:{_PALETTE["ok"]}">PASS</span>'
        vrows.append(
            f'<div class="commitrow">{mark} <span class="mono">{_esc(r.get("slug"))}</span> '
            f'<span style="color:{_PALETTE["muted"]}">{_esc(r.get("effect") or "edit")} &rarr; '
            f'{_esc(r.get("new_version") or "")}</span>{verdict}</div>')
    verdict_panel = (
        '<div class="panel"><div class="ph">Per-survey validation</div><div class="pb">'
        '<div class="verdlist">' + "".join(vrows) + '</div></div></div>')

    if has_fail:
        banner = (f'<p style="color:{_PALETTE["bad"]};font-weight:600">The validator FAILED on at '
                  'least one member — this batch cannot be published. Fix the offending survey and '
                  're-preview. Nothing has been committed.</p>')
        confirm = ""
    else:
        banner = (f'<p style="color:{_PALETTE["ok"]};font-weight:600">Every affected member passed '
                  '(WARNINGs do not block). Confirm to commit the whole batch atomically.</p>')
        csrf = f'<input type="hidden" name="{CSRF_FIELD}" value="{_esc(csrf_token)}">'
        confirm = (
            '<div class="panel"><div class="ph">Publish batch</div><div class="pb">'
            '<div class="fnote">Reversible: each commit is an ordinary published edit. The batch '
            're-applies and re-validates under the publish lock at commit time — a stale preview or a '
            'concurrent edit is refused, nothing partial ever lands.</div>'
            f'<form method="post" action="{_esc(action)}" data-confirm="Publish this '
            f'{n}-commit batch?">'
            f'{csrf}'
            f'<input type="hidden" name="spec_json" value="{_esc(spec_json)}">'
            f'<input type="hidden" name="expected_shas_json" value="{_esc(expected_shas_json)}">'
            f'<input type="hidden" name="note" value="{_esc(note)}">'
            f'<p class="btnrow"><button class="b-ok" type="submit">Publish batch &mdash; {n} '
            f'commit{"s" if n != 1 else ""}</button></p>'
            '</form></div></div>')

    body = (
        f'<h1>Preview batch &mdash; {_esc(cid) if not is_new else "new collection"}</h1>'
        f'<p class="sub">One combined preview before anything is written. {n} affected '
        f'survey{"s" if n != 1 else ""}; every one is validated; the batch commits only if all pass. '
        f'&middot; <a href="{_esc(back)}">back to editor</a></p>'
        f'{banner}'
        f'<div class="fnote"><b>Release note (all commits):</b> {_esc(note)}</div>'
        f'{diff_panel}{verdict_panel}{confirm}'
    )
    return _shell(f"AusMT preview batch · {cid or 'new'}", body, nav=nav)


# ---- C43 Stage 3b candidate-picker filter (the ONLY JS on the editor/create pages) ---------------
# Served by GET /gateway/curator/collections.js as an EXTERNAL same-origin script (the strictPages CSP
# is script-src 'self' — inline blocks/on* are dead). Mirrors the shipped stations-filter pattern:
# textContent read, className toggle only; NO innerHTML-with-data, no eval, no fetch. DOM-free logic
# (matchRow) is factored out so the executable Node parity pin can drive it (F: string pins are banned).
COLLECTIONS_JS = r"""
'use strict';
(function () {
  // Pure, DOM-free: does a candidate row (its filter text) match the query? Case-insensitive
  // substring over the whitespace-joined "slug currentCollectionId". Empty query matches everything.
  // Extracted + driven by the Node parity pin (test_c43_stage3b_js_parity.py).
  function matchRow(filterText, query) {
    var q = String(query == null ? '' : query).trim().toLowerCase();
    if (q === '') return true;
    return String(filterText == null ? '' : filterText).toLowerCase().indexOf(q) !== -1;
  }

  function apply(input, rows) {
    var q = input.value;
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      var ft = row.getAttribute('data-filter') || '';
      // className toggle only — never innerHTML.
      if (matchRow(ft, q)) { row.classList.remove('hide'); }
      else { row.classList.add('hide'); }
    }
  }

  function wire() {
    var input = document.getElementById('cand-filter');
    var table = document.getElementById('cand-table');
    if (!input || !table) return;
    var rows = table.querySelectorAll('tr.memrow');
    input.addEventListener('input', function () { apply(input, rows); });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wire);
  } else {
    wire();
  }
})();
"""


# ---- station (EDI) removal ------------------------------------------------------------------------
# A station is one .edi file under <slug>/transfer_functions/edi/. survey.yaml carries NO station-list
# field, so the listing is the EDI files themselves and a removal is a git rm + version bump + release
# note. NO inline JS: the final confirm form rides the shared CURATOR_UI_JS data-confirm delegation.


def render_stations_list(*, slug: str, version: str | None, stations: list, csrf_token: str,
                         error: str = "", nav: "NavContext | None" = None) -> str:
    """The stations page (removal deliverable 1): one row per EDI — filename, derived station id, and a
    remove checkbox — plus the version-bump picker (a removal is a content change: minor by default)
    and the required release note. Submitting selects one or more files for a removal PREVIEW. A
    refused preview re-renders this page freshly (with an error banner) rather than trying to restore
    checkbox state — the curator re-ticks, which is a two-click cost on the rare refusal path and keeps
    the renderer stateless (no submitted-form threading)."""
    err = f'<p class="sub" style="color:{_PALETTE["bad"]}">{_esc(error)}</p>' if error else ""
    cur = version or "0.0.0"
    # A removal is at least a MINOR change by default (content changed); patch/major still offered.
    minor_v = _suggest_bump(cur, "minor")
    patch_v = _suggest_bump(cur, "patch")
    major_v = _suggest_bump(cur, "major")
    csrf = f'<input type="hidden" name="{CSRF_FIELD}" value="{_esc(csrf_token)}">'
    if stations:
        rows = []
        for s in stations:
            filename = s.get("filename", "") if isinstance(s, dict) else ""
            station_id = s.get("station_id", "") if isinstance(s, dict) else ""
            rows.append(
                "<tr>"
                f'<td><input type="checkbox" name="remove" value="{_esc(filename)}" '
                f'style="width:auto"></td>'
                f"<td>{_esc(filename)}</td><td>{_esc(station_id)}</td></tr>")
        table = ('<table><tr><th>Remove</th><th>File</th><th>Station id</th></tr>'
                 + "".join(rows) + "</table>")
        count_line = f'<p class="sub">{len(stations)} station(s) in this survey.</p>'
    else:
        table = '<p class="sub">This survey has no EDI files.</p>'
        count_line = ""

    # A removal defaults to a MINOR bump (content changed); patch/major still offered.
    bump = (
        '<p><label class="k">Version bump (removing a station is a content change)</label>'
        f'<label><input type="radio" name="bump" value="patch" style="width:auto"> patch '
        f'&rarr; {_esc(patch_v)}</label><br>'
        f'<label><input type="radio" name="bump" value="minor" checked style="width:auto"> minor '
        f'&rarr; {_esc(minor_v)}</label><br>'
        f'<label><input type="radio" name="bump" value="major" style="width:auto"> major '
        f'&rarr; {_esc(major_v)}</label></p>'
    )
    body = (
        f'<h1>Manage stations — {_esc(slug)}</h1>'
        f'<p class="sub">current version {_esc(cur)} · '
        f'<a href="/gateway/curator/edit/{_esc(slug)}">back to edit form</a> · '
        f'<a href="/gateway/curator/queue">queue</a></p>'
        '<p class="sub">Tick the station(s) to remove, then preview. A removal deletes the EDI '
        'file(s) from the survey repository — at least one station must remain.</p>'
        f'{err}'
        f'<form method="post" action="/gateway/curator/edit/{_esc(slug)}/stations/preview">'
        f'<div class="panel">{count_line}{table}</div>'
        f'<div class="panel">{bump}'
        '<p><label class="k">Release note (required — records why the station(s) were removed)</label>'
        '<textarea name="note" placeholder="e.g. withdrawn consent for SA226" required></textarea></p>'
        f'{csrf}'
        '<p><button class="b-accent" type="submit">Preview removal</button></p>'
        '</div></form>'
    )
    if nav is not None:
        return _shell(f"AusMT stations {slug}", body, nav=nav)
    return _page(f"AusMT stations {slug}", body)


def render_removal_preview(*, slug: str, version: str, removed: list, station_count_before: int,
                           station_count_after: int, diff: str, validate_report: dict | None,
                           has_fail: bool, new_sha256: str, note: str, bump: str,
                           filenames_json: str, csrf_token: str,
                           nav: "NavContext | None" = None) -> str:
    """The removal preview (deliverable 2): exactly which files will be deleted, station count before
    → after, the survey.yaml diff (version + release_notes), and the validator's verdict on the package
    WITHOUT the removed files. Only when the validator did NOT FAIL is a confirm form shown — carrying
    the §0.6 content hash + the filenames/bump/note to reproduce the exact bytes at commit. The confirm
    form has a data-confirm guard (rides CURATOR_UI_JS; no inline JS)."""
    csrf = f'<input type="hidden" name="{CSRF_FIELD}" value="{_esc(csrf_token)}">'
    files_items = "".join(f"<li>{_esc(name)}</li>" for name in removed)
    n = len(removed)
    files_panel = (
        '<div class="panel"><h2>Files to delete</h2>'
        f'<ul>{files_items}</ul>'
        f'<p class="sub">Stations: {station_count_before} &rarr; {station_count_after}</p></div>')
    diff_panel = (f'<div class="panel"><h2>Changes to survey.yaml</h2>'
                  f'<pre>{_esc(diff)}</pre></div>')
    verdict = _reports_panel(validate_report=validate_report, preview_summary=None)
    if has_fail:
        banner = (f'<p style="color:{_PALETTE["bad"]};font-weight:600">'
                  'The validator FAILED on the survey WITHOUT these stations — this removal cannot be '
                  'published. Go back and reconsider the selection.</p>')
        confirm = ""
    else:
        banner = (f'<p style="color:{_PALETTE["ok"]};font-weight:600">'
                  'Validator passed on the survey without the selected station(s) (WARNINGs, if any, '
                  'do not block). Confirm to delete and commit.</p>')
        # data-confirm carries the exact house copy the brief mandates (rides the delegated handler).
        confirm_msg = (f"Remove {n} station(s) from {slug}? This deletes the EDI files from the "
                       "survey repository.")
        confirm = (
            f'<div class="panel"><h2>Delete &amp; commit</h2>'
            '<p class="sub">The EDI file(s) are git-rm\'d and survey.yaml updated in one commit, then '
            'pushed — the serve-reconcile agent serves the result on its next tick (or run '
            '<code>make rebuild-data</code> by hand).</p>'
            f'<form method="post" action="/gateway/curator/edit/{_esc(slug)}/stations/confirm" '
            f'data-confirm="{_esc(confirm_msg)}">'
            f'{csrf}'
            f'<input type="hidden" name="new_sha256" value="{_esc(new_sha256)}">'
            f'<input type="hidden" name="bump" value="{_esc(bump)}">'
            f'<input type="hidden" name="filenames_json" value="{_esc(filenames_json)}">'
            f'<input type="hidden" name="note" value="{_esc(note)}">'
            f'<p><button class="b-bad" type="submit">Remove {n} station(s) &amp; commit</button></p>'
            '</form></div>'
        )
    body = (
        f'<h1>Preview removal — {_esc(slug)}</h1>'
        f'<p class="sub">new version {_esc(version)} · '
        f'<a href="/gateway/curator/edit/{_esc(slug)}/stations">back to stations</a> · '
        f'<a href="/gateway/curator/queue">queue</a></p>'
        f'{banner}{files_panel}{diff_panel}{verdict}{confirm}'
    )
    if nav is not None:
        return _shell(f"AusMT remove stations {slug}", body, nav=nav)
    return _page(f"AusMT remove stations {slug}", body)


# ---- survey retirement (C41 D2) — the danger-zone confirmation + terminal page --------------------
# Whole-survey removal: a git rm -r of the survey package, gated by a typed slug + a required release
# note + a valid TOTP second factor. The confirmation page DISCLOSES exactly what the record D2 lists
# (package contents + N stations, serving-until-rebuild, collections recompute, bookmark/DOI honesty,
# the git-revert undo). No inline JS: the submit rides the shared CURATOR_UI_JS data-confirm.


def render_survey_retire_confirm(*, slug: str, station_count: int | None, csrf_token: str,
                                 enrolled: bool, is_last_survey: bool, error: str = "",
                                 nav: "NavContext | None" = None) -> str:
    """The retirement confirmation page (C41 D2): the full disclosure + the typed-slug / release-note /
    TOTP-code form. When the last-survey guard fires (retiring would empty the corpus and break the
    build) or the curator is not enrolled in the second factor, the form is replaced by the honest
    refusal in its place — the disclosure still renders so the curator understands the action either
    way."""
    csrf = f'<input type="hidden" name="{CSRF_FIELD}" value="{_esc(csrf_token)}">'
    err = f'<p class="sub" style="color:{_PALETTE["bad"]}">{_esc(error)}</p>' if error else ""
    n_txt = (f"{station_count} station file(s)" if isinstance(station_count, int)
             else "all its station files")
    disclosure = (
        '<div class="panel"><h2>What retiring this survey does</h2><ul>'
        f'<li><strong>Deletes the survey package</strong> — <code>{_esc(slug)}/survey.yaml</code> and '
        f'{_esc(n_txt)} (the whole <code>surveys/{_esc(slug)}</code> directory) are removed with '
        '<code>git rm -r</code> in ONE commit.</li>'
        '<li><strong>Serving is unchanged until the next rebuild</strong> — the survey keeps serving '
        'off the current build; the drift chip and serve panel show the lag honestly. Request a '
        'rebuild from the serve-state screen to serve the removal.</li>'
        '<li><strong>Collections recompute</strong> — any collection this survey belonged to drops it '
        'on the next rebuild (the member simply disappears).</li>'
        '<li><strong>Reader links break at the next rebuild</strong> — bookmarks to this survey 404; '
        'a minted DOI keeps resolving to a dead entry until the custodian updates its DOI metadata '
        '(DOI hygiene is the custodian&rsquo;s — this discloses it, it does not solve it).</li>'
        '<li><strong>Reversible</strong> — this is one commit; <code>git revert</code> of it restores '
        'the package byte-for-byte (ask the operator). git IS the soft delete; nothing is lost.</li>'
        '</ul></div>')
    if is_last_survey:
        action = (
            '<div class="panel"><h2>Cannot retire the last survey</h2>'
            f'{err}'
            '<p class="sub">This is the only published survey. An empty corpus breaks the next rebuild '
            '(the production build does not permit an empty result), so the retired survey would keep '
            'serving off the last good build indefinitely. Publish another survey before retiring this '
            'one.</p>'
            '<p><a href="/gateway/curator/survey/'
            f'{_esc(slug)}">back to the survey</a></p></div>')
    elif not enrolled:
        action = (
            '<div class="panel"><h2>Enrol your authenticator first</h2>'
            f'{err}'
            '<p class="sub">Retiring a survey requires a time-based one-time code (the second factor). '
            'You are not enrolled. Set up your authenticator on the '
            '<a href="/gateway/curator/security">Security</a> page, then return here.</p>'
            '<p><a href="/gateway/curator/survey/'
            f'{_esc(slug)}">back to the survey</a></p></div>')
    else:
        confirm_msg = (f"Retire {slug}? This git-rm's the whole survey package "
                       "(reversible by git revert).")
        action = (
            '<div class="panel"><h2>Confirm retirement</h2>'
            f'{err}'
            f'<form method="post" action="/gateway/curator/survey/{_esc(slug)}/retire" '
            f'data-confirm="{_esc(confirm_msg)}">'
            f'{csrf}'
            '<p><label class="k">Type the survey slug to confirm</label>'
            f'<input type="text" name="typed_slug" autocomplete="off" placeholder="{_esc(slug)}"></p>'
            '<p><label class="k">Release note (required — why retired; becomes the commit message)'
            '</label>'
            '<textarea name="note" placeholder="e.g. superseded by …, withdrawn by the custodian" '
            'required></textarea></p>'
            '<p><label class="k">Authenticator code (required — the second factor)</label>'
            '<input type="text" name="code" inputmode="numeric" autocomplete="off" '
            'placeholder="123456" style="max-width:12rem"></p>'
            '<p><button class="b-bad" type="submit">Retire survey</button></p>'
            '</form></div>')
    body = (
        f'<h1>Retire survey — {_esc(slug)}</h1>'
        '<p class="sub">This is a destructive action, protected by a typed confirmation and your '
        'authenticator. Read what it does before confirming.</p>'
        f'{disclosure}{action}'
    )
    if nav is not None:
        return _shell(f"AusMT retire {slug}", body, nav=nav)
    return _page(f"AusMT retire {slug}", body)


def render_survey_retired(*, slug: str, curator: str) -> str:
    """The terminal page after a successful retirement: confirmation + the serve-until-rebuild reality +
    the git-revert undo (record D2). A chrome-less _page like the station-removal terminal confirm."""
    body = (
        f'<h1>Retired survey — {_esc(slug)}</h1>'
        '<p class="sub">The survey package was removed from surveys-live and pushed in one commit '
        f'(curator:{_esc(curator)}). The serve-reconcile agent rebuilds and serves the result on its '
        'next tick (typically within 15 minutes) — see the serve-state panel, or run '
        '<code>make rebuild-data</code> by hand. Until then the survey keeps serving off the current '
        'build; the drift chip shows the lag.</p>'
        '<p class="sub"><strong>Undo:</strong> this is reversible — <code>git revert</code> of the '
        'retirement commit restores the package byte-for-byte. Ask the operator.</p>'
        '<p><a href="/gateway/curator/edit">back to surveys</a> · '
        '<a href="/gateway/curator/serve">serve state</a></p>'
    )
    return _page(f"AusMT retired {slug}", body)


# ---- uploader keys (schema v2 — curator-managed submit keys) ---------------------------------

# The rotation runbook the keys page links to (D7). A repo-relative doc path, not an external URL —
# the strictPages CSP would not block a link, but a same-repo runbook is the honest target (there is
# no external rotation service). Rendered as plain text + the path so it is useful even where the doc
# is browsed on the git host rather than fetched.
_KEY_ROTATION_RUNBOOK = "docs/docs/operator/uploader-key-rotation.md"


def render_uploaders(*, curator_name: str, keys: list, csrf_token: str, error: str = "",
                     submission_counts: dict | None = None,
                     nav: "NavContext | None" = None) -> str:
    """The uploader-key management page (feat/uploader-key-management + C43 D7 deltas): a create form +
    the list of issued keys. The list shows name, email (curator-only PII, never on a public page),
    created (by/when), last used, submission count, a free-text NOTE (D7 — sqlite only, never git), and
    status (active/revoked with when/by). A revoked row STAYS listed for the audit trail — there is no
    delete — and its note becomes read-only (audit context, not an editable field). The plaintext key
    is NEVER shown here (displayed exactly once at creation). D7 deltas over the v2 page:
      * per-key free-text note (who it's for / expiry intent), edited inline via a tiny POST form;
      * submission count per key from the audit trail (`submission_counts` name->count);
      * an explicit UNUSED-KEY NUDGE — an active key that has never been used is badged 'never used'
        so a stale key stands out at a glance;
      * revoked keys retained as read-only audit rows (unchanged from v2, restated for D7);
      * a rotation-runbook link on the page.
    Every interpolated value is html.escaped (a note is curator free text — it MUST NOT inject markup)."""
    csrf = f'<input type="hidden" name="{CSRF_FIELD}" value="{_esc(csrf_token)}">'
    err = f'<p class="sub" style="color:{_PALETTE["bad"]}">{_esc(error)}</p>' if error else ""
    counts = submission_counts or {}
    create = (
        '<div class="panel"><h2>Issue a new uploader key</h2>'
        '<p class="sub">The key is shown ONCE on the next page — it cannot be retrieved again '
        '(revoke and create a new one if lost). The email is a curator-only contact for the uploader '
        'and never appears on any public page.</p>'
        f'{err}'
        # The create form keeps a comfortable reading measure on the (wide, H2) page — a
        # name/email input stretched across the whole viewport helps nobody.
        '<form method="post" action="/gateway/curator/uploaders/create" style="max-width:40rem">'
        f'{csrf}'
        # maxlength attrs = client courtesy; the SERVER caps are the gate (app._KEY_*_MAX_CHARS, F5).
        '<p><label class="k">Name (required, unique)</label>'
        '<input type="text" name="name" placeholder="e.g. field-team-1" required autocomplete="off" '
        'maxlength="120"></p>'
        '<p><label class="k">Email (optional, curator-only)</label>'
        '<input type="text" name="email" placeholder="contact@example.org" autocomplete="off" '
        'maxlength="254"></p>'
        '<p><button class="b-accent" type="submit">Create key</button></p>'
        '</form></div>'
    )
    runbook = (
        '<p class="sub">Key rotation is mint &rarr; use &rarr; revoke, then re-mint (key material is '
        'hashes-only and deliberately uneditable). Runbook: '
        f'<code>{_esc(_KEY_ROTATION_RUNBOOK)}</code></p>'
    )
    if keys:
        trs = []
        for k in keys:
            n_sub = counts.get(k.name, 0)
            if k.revoked_utc:
                status = (f'<span class="badge" style="background:{_PALETTE["bad"]}">revoked</span> '
                          f'<span class="k">{_dt_html(k.revoked_utc)} '
                          f'by curator:{_esc(k.revoked_by or "")}</span>')
                action = ""
                # A revoked key's note is read-only audit context — rendered, never an editable form.
                note_cell = (f'<span class="k">{_esc(k.note)}</span>' if k.note
                             else '<span class="k">—</span>')
            else:
                # The unused-key nudge (D7): an active key that has NEVER been used stands out.
                if k.last_used_utc:
                    status = f'<span class="badge" style="background:{_PALETTE["ok"]}">active</span>'
                else:
                    status = (f'<span class="badge" style="background:{_PALETTE["ok"]}">active</span> '
                              f'<span class="badge" style="background:{_PALETTE["warn"]}">'
                              'never used</span>')
                action = (
                    f'<form class="act" method="post" '
                    f'action="/gateway/curator/uploaders/{_esc(k.id)}/revoke" '
                    'data-confirm="Revoke this uploader key? This cannot be undone.">'
                    f'{csrf}'
                    '<button class="b-bad" type="submit">Revoke</button></form>')
                # An inline note editor: a tiny same-row POST form (no inline JS — a plain submit).
                note_cell = (
                    f'<form method="post" action="/gateway/curator/uploaders/{_esc(k.id)}/note" '
                    'style="margin:0;display:flex;gap:.3rem;align-items:flex-start">'
                    f'{csrf}'
                    # H2: a USABLE editor width (34ch, capped to the cell) — the global 100% width
                    # inside a cramped cell rendered a few characters wide. The 2000 cap stays.
                    f'<textarea name="note" rows="2" placeholder="who it\'s for / expiry intent" '
                    f'maxlength="2000" style="min-height:2.4rem;width:34ch;max-width:100%">'
                    f'{_esc(k.note or "")}</textarea>'
                    '<button class="b-accent" type="submit" '
                    'style="padding:.3rem .6rem;font-size:.75rem">Save</button></form>')
            trs.append(
                "<tr>"
                f'<td>{_esc(k.name)}</td>'
                f'<td>{_esc(k.email or "-")}</td>'
                # H2: short datetime as visible text, full stored ISO on hover (title) — the raw
                # ISO wrapped over three lines in the cramped cells.
                f'<td class="k">{_dt_html(k.created_utc)}<br>by curator:{_esc(k.created_by)}</td>'
                f'<td class="k">{_dt_html(k.last_used_utc) if k.last_used_utc else "never"}</td>'
                f'<td class="k">{_esc(n_sub)}</td>'
                f'<td>{note_cell}</td>'
                f'<td>{status}</td>'
                f'<td>{action}</td>'
                "</tr>"
            )
        table = ("<table><tr><th>Name</th><th>Email</th><th>Created</th><th>Last used</th>"
                 "<th>Submissions</th><th>Note</th><th>Status</th><th></th></tr>"
                 + "".join(trs) + "</table>")
    else:
        table = '<p class="sub">No uploader keys issued yet.</p>'
    body = (
        '<h1>Uploader keys</h1>'
        f'<p class="sub">Signed in as curator:{_esc(curator_name)}</p>'
        f'{create}'
        f'<div class="panel"><h2>Issued keys</h2>{runbook}{table}</div>'
    )
    if nav is not None:
        # H2 (owner feedback): the keys page uses the FULL page width so the issued-keys table
        # spreads out — a per-page variant; every other page keeps the default measure.
        return _shell("AusMT uploader keys", body, nav=nav, wide=True)
    return _page("AusMT uploader keys", body)


# ---- C43 D6 quarantine view (read-only) ----------------------------------------------------------
# A read-only inspection surface for a QUARANTINED submission: the file listing under its extracted
# package + the refusal reason (the terminal-transition reason). NO action forms — the review flow
# (approve/return/reject) is deliberately untouched (D6); a quarantined submission is terminal and the
# only affordance here is looking at what arrived and why it was refused. The per-file view rides a
# path-contained route (app.py handle_quarantine_file) mirroring the preview-sandbox containment.


def render_quarantine_list(*, curator_name: str, rows: list, nav: "NavContext") -> str:
    """The quarantine list: every QUARANTINED submission with its slug, when, and refusal reason, each
    linking to its read-only inspection view. Quarantined submissions are terminal and NOT in the
    actionable queue (states.QUEUE_STATES) — this surface is the only place they are visible, so a
    curator can see WHAT was refused and WHY without console access (the NCI sole-entry framing)."""
    if rows:
        trs = []
        for r in rows:
            sid = _esc(r["id"])
            trs.append(
                "<tr>"
                f'<td><a href="/gateway/curator/quarantine/{sid}">{_esc(r["id"][:12])}</a></td>'
                f'<td>{_esc(r.get("slug") or "-")}</td>'
                f'<td class="k">{_esc(r.get("updated_utc") or "")}</td>'
                f'<td>{_esc(r.get("reason") or "-")}</td>'
                "</tr>")
        table = ('<table><tr><th>ID</th><th>Slug</th><th>Quarantined</th><th>Refusal reason</th></tr>'
                 + "".join(trs) + "</table>")
    else:
        table = '<p class="sub">No quarantined submissions.</p>'
    body = (
        '<h1>Quarantined submissions</h1>'
        '<p class="sub">Read-only inspection of submissions the pipeline refused (unsafe archive, '
        'validator FAIL, or a failed preview build). The review flow is not offered here — a '
        'quarantined submission is terminal; a corrected package is a fresh upload.</p>'
        f'<div class="panel">{table}</div>'
    )
    return _shell("AusMT quarantine", body, nav=nav)


def render_quarantine_detail(*, submission_id: str, slug: str | None, reason: str,
                             files: list, nav: "NavContext") -> str:
    """A single quarantined submission's read-only view: the refusal reason + the file listing of the
    extracted package, each file linking to its path-contained inspection route. `files` is a list of
    {rel, size} for every file under quarantine/<id>/package (relative POSIX paths, server-enumerated —
    the curator never supplies a path that reaches the filesystem un-contained). NO action forms."""
    sid = _esc(submission_id)
    reason_block = (
        '<div class="panel"><h2>Refusal reason</h2>'
        f'<pre>{_esc(reason or "(no recorded reason)")}</pre></div>')
    if files:
        rows = []
        for f in files:
            rel = f.get("rel", "")
            size = f.get("size")
            size_txt = f"{size:,} B" if isinstance(size, int) else "-"
            # The link is to the containment route; the curator NEVER types a path — this is a
            # server-enumerated relative path, url-encoded per segment so a legitimate odd filename
            # (spaces etc) still resolves, and the route re-contains regardless.
            enc = "/".join(_url_quote(part) for part in rel.split("/"))
            rows.append(
                "<tr>"
                f'<td><a href="/gateway/curator/quarantine/{sid}/file/{enc}">{_esc(rel)}</a></td>'
                f'<td class="k">{_esc(size_txt)}</td>'
                "</tr>")
        listing = ('<table><tr><th>File</th><th>Size</th></tr>' + "".join(rows) + "</table>")
    else:
        listing = ('<p class="sub">No extracted package files present — the submission was refused '
                   'before or during unpacking (see the reason above).</p>')
    body = (
        f'<h1>Quarantined submission {_esc(submission_id[:12])}</h1>'
        f'<p class="sub">slug: {_esc(slug or "-")} · '
        '<a href="/gateway/curator/quarantine">back to quarantine</a></p>'
        f'{reason_block}'
        f'<div class="panel"><h2>Package contents (read-only)</h2>{listing}</div>'
    )
    return _shell(f"AusMT quarantine {submission_id[:12]}", body, nav=nav)


def render_uploader_created(*, curator_name: str, name: str, key: str) -> str:
    """The show-ONCE page after a create: the plaintext key with copy-me wording and an explicit
    reminder that it cannot be retrieved again. This is the ONLY place the plaintext is ever rendered;
    the list page shows only its name/status. The key is escaped (defence in depth — the charset is
    urlsafe-base64 so it cannot contain markup, but the page still escapes it)."""
    body = (
        f'<h1>Uploader key created — {_esc(name)}</h1>'
        '<p class="sub">Copy this key now and give it to the uploader out-of-band (they send it as '
        'the <code>X-AusMT-Submit-Key</code> header). It is shown ONCE and cannot be retrieved again '
        '— if it is lost, revoke it and create a new one.</p>'
        f'<div class="panel"><h2>The key (copy me)</h2>'
        f'<pre style="user-select:all">{_esc(key)}</pre></div>'
        '<p><a href="/gateway/curator/uploaders">back to uploader keys</a> · '
        '<a href="/gateway/curator/queue">queue</a></p>'
    )
    return _page("AusMT uploader key created", body)


# ---- curator security: TOTP second factor (schema v4 — C41 D2) -----------------------------------
# The Security page enrols the per-curator TOTP authenticator that gates the destructive workbench
# actions (survey retirement first). Three states, no inline JS (every form is a plain POST):
#   * none    — not enrolled; offer "Begin enrolment" (generates a secret).
#   * pending — a secret was generated but not activated; the secret was shown ONCE and is not
#               re-rendered on a reload, so offer "activate with a code" AND "begin again".
#   * active  — enrolled; offer "rotate" (which requires a CURRENT code — a session alone must never
#               rotate the secret, else the second factor collapses into the first, D2).
# The secret + otpauth URI are rendered ONLY as the immediate response to begin/rotate (the show-once
# view), never on a GET — the DB stores the secret but the page never re-displays it.


def _totp_begin_form(csrf: str, *, label: str) -> str:
    return ('<form method="post" action="/gateway/curator/security/enrol">'
            f'{csrf}'
            f'<p><button class="b-accent" type="submit">{_esc(label)}</button></p>'
            '</form>')


def _totp_code_form(csrf: str, *, action: str, label: str, button: str, button_class: str) -> str:
    return (f'<form method="post" action="{_esc(action)}">'
            f'{csrf}'
            f'<p><label class="k">{_esc(label)}</label>'
            '<input type="text" name="code" inputmode="numeric" autocomplete="off" '
            'placeholder="123456" style="max-width:12rem"></p>'
            f'<p><button class="{_esc(button_class)}" type="submit">{_esc(button)}</button></p>'
            '</form>')


def _totp_secret_panel(secret: str, otpauth_uri: str, csrf: str) -> str:
    """The SHOW-ONCE view rendered as the direct response to enrol/rotate: the base32 secret + the
    otpauth:// URI for manual authenticator entry (no QR image dependency, D2), then the activate form.
    The secret is never rendered again — a reload of the security page shows the pending state without
    it."""
    return (
        '<div class="panel"><h2>Add this secret to your authenticator (shown once)</h2>'
        '<p class="sub">Enter this secret into your authenticator app (Google Authenticator, Aegis, '
        '1Password, …) by manual entry, or paste the otpauth URI. It is shown ONCE and cannot be '
        'retrieved again — if you lose it before activating, begin again for a fresh secret.</p>'
        '<p><label class="k">Secret (base32, manual entry)</label>'
        f'<pre style="user-select:all">{_esc(secret)}</pre></p>'
        '<p><label class="k">otpauth URI</label>'
        f'<pre style="user-select:all">{_esc(otpauth_uri)}</pre></p>'
        '<h3>Activate</h3>'
        '<p class="sub">Enter a current code from your authenticator to prove it works — the factor '
        'is NOT active (and will not gate anything) until you do.</p>'
        + _totp_code_form(csrf, action="/gateway/curator/security/activate",
                          label="Code from your authenticator", button="Activate",
                          button_class="b-ok")
        + '</div>')


def render_security(*, curator_name: str, csrf_token: str, state: str, secret: str | None = None,
                    otpauth_uri: str | None = None, enrolled_utc: str | None = None,
                    error: str = "", nav: "NavContext | None" = None) -> str:
    """The Security page (C41 T2): enrol / activate / rotate the per-curator TOTP second factor. `state`
    is 'none' | 'pending' | 'active'. When `secret` is supplied (the immediate response to a begin or
    rotate) the show-once secret panel is rendered regardless of state; otherwise the page renders the
    stored state with NO secret. Every form is a plain POST (no inline JS — strictPages CSP)."""
    csrf = f'<input type="hidden" name="{CSRF_FIELD}" value="{_esc(csrf_token)}">'
    err = f'<p class="sub" style="color:{_PALETTE["bad"]}">{_esc(error)}</p>' if error else ""
    intro = (
        '<h1>Security — two-factor for destructive actions</h1>'
        f'<p class="sub">Signed in as curator:{_esc(curator_name)}</p>'
        '<p class="sub">Retiring a survey (and other destructive workbench actions) requires a '
        'time-based one-time code (TOTP) from your authenticator app in addition to your session, so '
        'a stolen session alone cannot delete a survey. The secret is stored only in the gateway '
        'database (never in git). If you lose your authenticator, recovery is a console action by the '
        'operator — there is deliberately no self-service reset or unenrol here.</p>'
    )
    if secret is not None:
        panel = _totp_secret_panel(secret, otpauth_uri or "", csrf)
    elif state == "pending":
        panel = (
            '<div class="panel"><h2>Enrolment pending activation</h2>'
            f'{err}'
            '<p class="sub">You began an enrolment but have not activated it. The secret is shown '
            'ONCE at generation and is not stored in a retrievable form. If you saved it in your '
            'authenticator, enter a current code to activate. Otherwise, begin again for a fresh '
            'secret.</p>'
            + _totp_code_form(csrf, action="/gateway/curator/security/activate",
                              label="Code from your authenticator", button="Activate",
                              button_class="b-ok")
            + '<h3>Or start over</h3>'
            + _totp_begin_form(csrf, label="Begin again (new secret)")
            + '</div>')
    elif state == "active":
        panel = (
            '<div class="panel"><h2>Two-factor is enrolled</h2>'
            f'<p class="sub">Active since {_dt_html(enrolled_utc or "")}. Your authenticator is '
            'required for destructive actions such as survey retirement.</p>'
            f'{err}'
            '<h3>Rotate the secret</h3>'
            '<p class="sub">Rotating requires a CURRENT code from your existing authenticator — a '
            'session alone cannot rotate the secret. You will be shown a new secret once and must '
            'activate it (deletion is refused while a rotation is pending activation). To disable or '
            'reset a lost authenticator, ask the operator (a console action).</p>'
            + _totp_code_form(csrf, action="/gateway/curator/security/rotate",
                              label="Current code", button="Rotate secret",
                              button_class="b-accent")
            + '</div>')
    else:  # none
        panel = (
            '<div class="panel"><h2>Not enrolled</h2>'
            f'{err}'
            '<p class="sub">You have not enrolled an authenticator. Begin enrolment to generate a '
            'secret; you will add it to your authenticator app and confirm a code before it becomes '
            'active.</p>'
            + _totp_begin_form(csrf, label="Begin enrolment")
            + '</div>')
    body = intro + panel
    if nav is not None:
        return _shell("AusMT security", body, nav=nav)
    return _page("AusMT security", body)


def render_detail(*, submission_id: str, state: str, updated_utc: str,
                  submitter_name: str, submitter_email: str, submitter_orcid: str | None,
                  validate_report: dict | None, preview_summary: dict | None,
                  cl: "checklist_mod.Checklist", csrf_token: str, note: str = "",
                  has_preview: bool, nav: "NavContext | None" = None) -> str:
    """The submission review page. C43 FR2-1: full width inside the nav shell (wide-by-default) with a
    two-column arrangement when a preview exists — the review CONTEXT (submitter PII, checklist, report
    bundle, last note) on the LEFT, the sandboxed PREVIEW on the RIGHT — and the review ACTION forms
    (approve / return / reject) beneath, full width. LAYOUT ONLY: the action logic, the CSRF fields,
    the null-origin sandbox, and the PII split are all unchanged. Without `nav` it renders chrome-less
    (the source-literal render-pin path); the two-column split still applies and collapses on narrow."""
    preview = ""
    if has_preview:
        # NULL-ORIGIN SANDBOX (design §7): sandbox="allow-scripts" WITHOUT allow-same-origin — the
        # portal JS renders the map/drawer, but the framed document has an OPAQUE origin and cannot
        # read the curator cookie/session, the parent DOM, or make credentialed same-origin requests.
        # A portal-XSS in this UN-curated submitter data therefore cannot steal the curator session or
        # forge an approve. There is NO "open in a new tab" link — a top-level same-origin navigation
        # would run the submitter's portal JS in the curator origin, defeating the frame. "Full size"
        # is a CSS expansion of the SAME sandboxed iframe (a class toggle), never a navigation.
        sid = _esc(submission_id)
        preview = (
            '<div class="panel"><h2>Preview</h2>'
            '<p class="sub">Sandboxed, null-origin. Renders un-curated submitter data in isolation '
            'from your session.</p>'
            f'<iframe id="prev" src="/gateway/curator/preview/{sid}/index.html" '
            'sandbox="allow-scripts" referrerpolicy="no-referrer" '
            'title="submission preview"></iframe>'
            '<p><button type="button" class="b-accent" data-toggle-big="prev">'
            'Toggle full size</button></p></div>'
        )
    note_panel = f'<div class="panel"><h2>Last note</h2><pre>{_esc(note)}</pre></div>' if note else ""
    context = (
        _submitter_panel(name=submitter_name, email=submitter_email, orcid=submitter_orcid)
        + _checklist_panel(cl)
        + _reports_panel(validate_report=validate_report, preview_summary=preview_summary)
        + note_panel
    )
    actions = _action_forms(submission_id=submission_id, state=state, csrf_token=csrf_token, cl=cl)
    header = (
        f'<h1>Submission {_esc(submission_id[:12])} {_state_badge(state)}</h1>'
        f'<p class="sub">updated {_esc(updated_utc)} · '
        '<a href="/gateway/curator/queue">back to queue</a></p>')
    if has_preview:
        # Two columns: review context (PII/checklist/reports/note) LEFT, sandboxed preview RIGHT;
        # the action forms sit beneath, full width. grid-row pinned on both dcols (auto-placement
        # incident). Collapses to one column on narrow (context, then preview).
        middle = (
            '<div class="detail-split">'
            f'<div class="dcol left">{context}</div>'
            f'<div class="dcol right">{preview}</div>'
            '</div>')
    else:
        middle = context
    body = header + middle + actions
    if nav is not None:
        return _shell(f"AusMT submission {submission_id[:12]}", body, nav=nav)
    return _page(f"AusMT submission {submission_id[:12]}", body)
