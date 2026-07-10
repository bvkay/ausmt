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
from string import Template

from . import checklist as checklist_mod
from . import states
from .curator_auth import CSRF_FIELD

_PALETTE = {
    "bg": "#13202B", "panel": "#1B2C3A", "ink": "#E8EDF1", "muted": "#8FA3B0",
    "accent": "#E0782F", "ok": "#5BAE6A", "warn": "#D9A23B", "bad": "#A85454",
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
  fetch('/data/build.json', {credentials: 'omit', cache: 'no-store'}).then(function (r) {
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }).then(function (b) {
    if (buildEl) buildEl.textContent = b.build_id || '(unknown)';
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


# The survey hub's browser-side script (C43 Stage 1 S1-2). TWO jobs, both degradable:
#   1. OVERVIEW & QA tab — fetch /data/build_report.json + /data/build.json SAME-ORIGIN, filter to
#      this survey (#survey-qa[data-survey-slug]), and render the health cards, the "Needs attention"
#      rows (each build-report warning/refusal as an actionable row with its inline diagnosis), and
#      the conditioning summary. Refused stations link ONLY to the existing station-removal list (the
#      drill-down is Stage 2 — no dangling links); metadata-class issues link to the Metadata tab's
#      owning section. The gateway has NO site-data mount, so this MUST be browser-side (the serve-
#      panel precedent).
#   2. METADATA tab — enhance the sticky TOC to show ONE section at a time (#hub-toc / .hub-section).
#      Without this script the server renders every section stacked and fully functional (graceful).
# RAW JS served by GET /gateway/curator/survey-hub.js — inline is dead under script-src 'self'. Every
# value goes in via textContent (never innerHTML) so a build-report string cannot inject markup.
SURVEY_HUB_JS = """
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

  // ---- Overview & QA: browser-side from the served /data corpus ----
  var qa = document.getElementById('survey-qa');
  if (!qa) return;
  var slug = qa.getAttribute('data-survey-slug') || '';

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
  function card(host, n, label) {
    var c = el('div', null, 'card');
    c.appendChild(el('div', String(n), 'n'));
    c.appendChild(el('div', label, 'l'));
    host.appendChild(c);
  }

  Promise.all([
    fetchJson('/data/build_report.json').catch(function () { return {__err: true}; }),
    fetchJson('/data/build.json').catch(function () { return {__err: true}; })
  ]).then(function (res) {
    var rep = res[0], build = res[1];
    var cards = document.getElementById('qa-cards');
    var attention = document.getElementById('qa-attention');
    var cond = document.getElementById('qa-conditioning');
    cards.textContent = ''; attention.textContent = ''; cond.textContent = '';

    if (!rep || rep.__missing || rep.__err) {
      cards.appendChild(el('p', 'No build report available yet (/data/build_report.json).', 'sub'));
      return;
    }
    var survey = (rep.surveys || {})[slug];
    if (!survey) {
      cards.appendChild(el('p', 'This survey is not in the current build report — it may not have '
        + 'been built into the served corpus yet.', 'sub'));
      return;
    }
    var dropped = survey.stations_dropped || [];
    var warnings = survey.warnings || [];
    var conditioning = survey.conditioning || [];

    // Health cards.
    card(cards, survey.stations_built != null ? survey.stations_built : '-', 'Stations built');
    card(cards, dropped.length, 'Refused stations');
    card(cards, warnings.length, 'QA warnings');
    var buildId = (build && !build.__missing && !build.__err) ? (build.build_id || '-') : '-';
    card(cards, buildId, 'Served build');

    // Needs attention: refusals then warnings, each an actionable row with inline diagnosis.
    if (!dropped.length && !warnings.length) {
      attention.appendChild(el('p', 'Nothing needs attention — no refused stations or QA warnings '
        + 'in the current build.', 'sub'));
    } else {
      dropped.forEach(function (d) {
        var row = el('div', null, 'panel');
        row.style.margin = '.5rem 0';
        row.appendChild(el('div', 'Refused: ' + d.station));
        row.appendChild(el('div', d.reason, 'sub'));
        var note = el('p', 'Refused stations stay in the published package but are withheld from '
          + 'serving — the fix is a custodian-side re-export. To remove it here instead:', 'sub');
        row.appendChild(note);
        var a = el('a', 'manage stations (remove EDIs)');
        a.href = '/gateway/curator/edit/' + encodeURIComponent(slug) + '/stations';
        row.appendChild(a);
        attention.appendChild(row);
      });
      warnings.forEach(function (w) {
        var row = el('div', null, 'panel');
        row.style.margin = '.5rem 0';
        row.appendChild(el('div', 'Warning', 'k'));
        row.appendChild(el('div', String(w)));
        // Metadata-class warnings (e.g. an email as citation author) link to the Metadata tab.
        if (/citation|author|email|doi|orcid|license|licence|metadata/i.test(String(w))) {
          var a = el('a', 'open the Metadata tab');
          a.href = '/gateway/curator/survey/' + encodeURIComponent(slug) + '?tab=metadata';
          row.appendChild(a);
        }
        attention.appendChild(row);
      });
    }

    // Conditioning summary.
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
        var scope = String(c.count);
        if (c.stations && c.stations.length) scope += ' (' + c.stations.join(', ') + ')';
        else if (c.except && c.except.length) scope += ' (all except ' + c.except.join(', ') + ')';
        tr.appendChild(el('td', scope));
        tbl.appendChild(tr);
      });
      cond.appendChild(tbl);
    }
  });
})();
"""


def _esc(value) -> str:
    return html.escape(str(value), quote=True)


def _head(title: str) -> str:
    return Template(_HEAD).substitute(
        title=_esc(title), bg=_PALETTE["bg"], ink=_PALETTE["ink"], muted=_PALETTE["muted"],
        accent=_PALETTE["accent"], panel=_PALETTE["panel"], ok=_PALETTE["ok"],
        warn=_PALETTE["warn"], bad=_PALETTE["bad"],
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

# The rail sections and their entries, as (group, [(key, label, href)]). Stage-1 ONLY surfaces that
# EXIST ship — Collections is Stage 3 and is DELIBERATELY absent (not a disabled placeholder, per the
# contract). "Serve state" links to the queue page's serve panel anchor (the panel lives there today).
_RAIL = (
    ("Surveys", (("surveys", "Surveys", "/gateway/curator/edit"),)),
    ("Intake", (("queue", "Submission queue", "/gateway/curator/queue"),
                ("uploaders", "Uploader keys", "/gateway/curator/uploaders"))),
    ("Operations", (("serve", "Serve state", "/gateway/curator/queue#serve-state"),)),
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


def _shell(title: str, body: str, *, nav: "NavContext") -> str:
    """Wrap a page body in the Stage-1 nav shell: left rail + context bar + main content. The external
    context-bar script (drift chip served-build half) loads at the tail, joining ui.js. Chrome-less
    pages (login, terminal confirms) use _page instead."""
    return (
        _head(title)
        + '<div class="shell">'
        + _rail_html(nav.active)
        + '<div class="main">'
        + _context_bar(nav)
        + '<div class="wrap">' + body + '</div>'
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
                 serve_panel: str = "", nav: "NavContext | None" = None) -> str:
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
        f'<p class="sub">Signed in as curator:{_esc(curator_name)} {logout}</p>'
        f'<div class="panel">{table}</div>'
        f'{serve_panel}'
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
}


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
    if action in ("failed", "sync_failed") and status.get("log_tail"):
        tail = (f'<p class="sub" style="color:{_PALETTE["bad"]};font-weight:600">'
                f'Last build did not serve — old data still live. Log tail:</p>'
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
    function row(k, v, highlight) {
      var tr = el('tr');
      var tdk = el('td', k, 'k');
      var tdv = el('td');
      var code = el('code', v == null ? '-' : String(v));
      if (highlight) { code.style.background = 'rgba(217,162,59,.25)'; code.style.padding = '0 .3rem'; }
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
    tbl.appendChild(row('Build id', b.build_id));
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
    "time_series": "Time series", "access": "Access", "processing": "Processing",
    "collection": "Collection",
}
_SECTION_ORDER = ("organisation", "lead_investigator", "principal_investigators", "identifiers",
                  "publications", "funding", "instruments", "time_series", "access", "processing",
                  "collection")


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
                extra_hint: str = "") -> str:
    val = "" if value is None else value
    ph = f' placeholder="{_esc(placeholder)}"' if placeholder else ""
    hint = f' {extra_hint}' if extra_hint else ""
    return (f'<input type="{_esc(input_type)}" name="{_esc(name)}" '
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
                       err_map: dict) -> str:
    from . import editor_form
    subfields = editor_form.MAP_SECTIONS[section]
    rows = [f'<h2>{_esc(title)}</h2>', _section_error_html(err_map.get(section))]
    for subkey, label, placeholder, kind in subfields:
        name = f"s_{section}_{subkey}"
        val = _sub_value(section, subkey, fields, submitted)
        if kind == "select" and section == "access":
            rows.append(_access_level_widget(name, val))
        elif kind == "date":
            rows.append(f'<p><label class="k">{_esc(label)}</label>'
                        f'{_text_input(name, val, placeholder, input_type="date")}</p>')
        elif kind == "email":
            rows.append(f'<p><label class="k">{_esc(label)}</label>'
                        f'{_text_input(name, val, placeholder, input_type="email")}</p>')
        elif kind == "levels" and section == "time_series":
            rows.append(_levels_widget(section, subkey, fields, submitted))
        elif kind == "ror":
            rows.append(f'<p><label class="k">{_esc(label)}</label>'
                        f'{_text_input(name, val, placeholder, extra_hint=_ROR_HINT)}</p>')
        else:
            rows.append(f'<p><label class="k">{_esc(label)}</label>'
                        f'{_text_input(name, val, placeholder)}</p>')
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
                        err_map: dict) -> str:
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
        scalar_rows.append(f'<p><label class="k">{_esc(label)}</label>'
                           f'{_text_input(f"f_{key}", _scalar_val(key))}</p>')
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

_HUB_TABS = (("overview", "Overview & QA"), ("metadata", "Metadata"))


def _hub_tab_strip(slug: str, active: str) -> str:
    """The hub tab strip: Overview & QA / Metadata as in-hub tabs, plus a Stations entry LINKING OUT
    to the existing removal page (labelled as such — Stage 1 rehomes it, does not rebuild it). No
    History tab (Stage 2)."""
    parts = ['<div class="tabs">']
    for key, label in _HUB_TABS:
        on = " on" if key == active else ""
        parts.append(
            f'<a class="hubtab{on}" href="/gateway/curator/survey/{_esc(slug)}?tab={key}">'
            f'{_esc(label)}</a>')
    # Stations links to the existing removal flow (not a hub tab — Stage 1 has no station drill-down).
    parts.append(
        f'<a class="hubtab" href="/gateway/curator/edit/{_esc(slug)}/stations">Stations (remove EDIs)</a>')
    parts.append("</div>")
    return "".join(parts)


def _hub_overview_body(slug: str) -> str:
    """The Overview & QA tab body. Every value is populated BROWSER-side by survey-hub.js from
    /data/build_report.json + /data/build.json filtered to THIS survey (data-survey-slug). The server
    renders only the scaffold + loading placeholders — it has no site-data mount, so it cannot read
    the served corpus (the same constraint the serve panel lives under). Refused/warning rows render
    their gate diagnosis inline; the only links out are to the existing station-removal list (the
    drill-down is Stage 2 — no dangling links). Metadata-class issues link to the Metadata tab."""
    return (
        f'<div id="survey-qa" data-survey-slug="{_esc(slug)}">'
        '<div class="cards" id="qa-cards"><p class="sub">Loading survey health…</p></div>'
        '<div class="panel"><h2>Needs attention</h2>'
        '<div id="qa-attention"><p class="sub">Loading build report…</p></div></div>'
        '<div class="panel"><h2>Conditioning summary</h2>'
        '<div id="qa-conditioning"><p class="sub">Loading conditioning notes…</p></div></div>'
        '</div>'
        # EXTERNAL same-origin script (strictPages CSP blocks inline JS). Degrades: without it the
        # placeholders remain, the page never breaks.
        '<script src="/gateway/curator/survey-hub.js" defer></script>'
    )


def _hub_metadata_body(*, slug: str, version: str | None, fields: dict, csrf_token: str,
                       field_errors=None, submitted: dict | None = None,
                       active_section: str | None = None) -> str:
    """The Metadata tab body: a sticky section TOC + one per-section form per section, each with its
    OWN commit tray (bump + required note + Preview) so "only this section is submitted" is literally
    true — the form carries only that section's widgets, and the merge seam scopes the patch to them.
    Every section keeps its advanced-JSON override (inside its panel). Server renders ALL sections
    (fully functional without JS); survey-hub.js enhances the TOC to show one section at a time."""
    from . import editor_form
    err_map = _field_error_map(field_errors)
    cur = version or "0.0.0"

    # The scalar panel is its own "section" (id: _scalars) so editing a top-level scalar submits only
    # the f_* fields — the per-section discipline extends to the scalars.
    def _scalar_val(key):
        if submitted is not None and f"f_{key}" in submitted:
            return submitted.get(f"f_{key}")
        v = fields.get(key, "")
        return "" if v is None else v

    scalar_rows = [f'<h2>Core fields</h2>']
    for key, label in _EDIT_SCALARS:
        scalar_rows.append(f'<p><label class="k">{_esc(label)}</label>'
                           f'{_text_input(f"f_{key}", _scalar_val(key))}</p>')
    for key, label in _EDIT_TEXTAREAS:
        scalar_rows.append(f'<p><label class="k">{_esc(label)}</label>'
                           f'<textarea name="f_{key}">{_esc(_scalar_val(key))}</textarea></p>')
    scalar_panel_inner = "".join(scalar_rows)

    # (toc key, title, panel-inner-html)
    sections: list[tuple[str, str, str]] = [("_scalars", "Core fields", scalar_panel_inner)]
    for section in _SECTION_ORDER:
        if section in editor_form.MAP_SECTIONS:
            inner = _map_section_panel(section, _SECTION_TITLES[section], fields, submitted, err_map)
        elif section in editor_form.LIST_SECTIONS:
            inner = _list_section_panel(section, _SECTION_TITLES[section], fields, submitted, err_map)
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
        toc_links.append(f'<a class="tocitem{on}" href="#{sec_id}" data-hub-section="{_esc(key)}">'
                         f'{_esc(title)}</a>')
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
        '<div style="display:flex;gap:1.25rem;align-items:flex-start">'
        f'<nav class="toc" id="hub-toc" style="flex:0 0 12rem">{"".join(toc_links)}</nav>'
        f'<div style="flex:1 1 auto;min-width:0" id="hub-sections">{"".join(forms)}</div>'
        '</div>'
        '<script src="/gateway/curator/editor.js" defer></script>'
        '<script src="/gateway/curator/survey-hub.js" defer></script>'
    )


def render_survey_hub(*, slug: str, tab: str, version: str | None, fields: dict, csrf_token: str,
                      nav: "NavContext", field_errors=None, submitted: dict | None = None,
                      active_section: str | None = None) -> str:
    """The per-survey hub (C43 Stage 1 S1-2). `tab` selects Overview & QA (default) or Metadata.
    Rendered inside the nav shell (rail + context bar). The Overview tab is browser-populated; the
    Metadata tab is the per-section editor. `fields`/`version` come from the runner read-job (only
    needed for the Metadata tab; the Overview tab needs no server-side survey content)."""
    tab = tab if tab in ("overview", "metadata") else "overview"
    crumb = (f'<a href="/gateway/curator/edit">Surveys</a> › <b>{_esc(slug)}</b>')
    strip = _hub_tab_strip(slug, tab)
    if tab == "metadata":
        cur = version or "0.0.0"
        head = (f'<h1>{_esc(slug)} — metadata</h1>'
                f'<p class="sub">current version {_esc(cur)}</p>')
        inner = _hub_metadata_body(slug=slug, version=version, fields=fields, csrf_token=csrf_token,
                                   field_errors=field_errors, submitted=submitted,
                                   active_section=active_section)
    else:
        head = (f'<h1>{_esc(slug)}</h1>'
                '<p class="sub">Survey health at a glance — served vs published counts, QA flags, '
                'and every build-report warning as an actionable row.</p>')
        inner = _hub_overview_body(slug)
    body = f'{head}{strip}{inner}'
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
    """The Surveys list (C43 Stage 1 S1-1: the former edit-list page, now the rail's Surveys surface).
    Each row links to the per-survey HUB (Overview & QA landing tab), NOT straight to the edit form —
    the hub is the task home. A directory listing of surveys-live, never content parsing."""
    if slugs:
        items = "".join(
            f'<li><a href="/gateway/curator/survey/{_esc(s)}">{_esc(s)}</a></li>' for s in slugs)
        listing = f"<ul>{items}</ul>"
    else:
        listing = '<p class="sub">No published surveys in surveys-live.</p>'
    body = (
        '<h1>Surveys</h1>'
        f'<p class="sub">Signed in as curator:{_esc(curator_name)}</p>'
        f'<div class="panel">{listing}</div>'
    )
    if nav is not None:
        return _shell("AusMT surveys", body, nav=nav)
    return _page("AusMT surveys", body)


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


# ---- uploader keys (schema v2 — curator-managed submit keys) ---------------------------------

def render_uploaders(*, curator_name: str, keys: list, csrf_token: str, error: str = "",
                     nav: "NavContext | None" = None) -> str:
    """The uploader-key management page (feat/uploader-key-management): a create form + the list of
    issued keys. The list shows name, email (curator-only PII, never on a public page), created
    (by/when), last used, and status (active/revoked with when/by). A revoked row STAYS listed for the
    audit trail — there is no delete. The plaintext key is NEVER shown here (it is displayed exactly
    once at creation); only the name/status is rendered. Every interpolated value is html.escaped."""
    csrf = f'<input type="hidden" name="{CSRF_FIELD}" value="{_esc(csrf_token)}">'
    err = f'<p class="sub" style="color:{_PALETTE["bad"]}">{_esc(error)}</p>' if error else ""
    create = (
        '<div class="panel"><h2>Issue a new uploader key</h2>'
        '<p class="sub">The key is shown ONCE on the next page — it cannot be retrieved again '
        '(revoke and create a new one if lost). The email is a curator-only contact for the uploader '
        'and never appears on any public page.</p>'
        f'{err}'
        '<form method="post" action="/gateway/curator/uploaders/create">'
        f'{csrf}'
        '<p><label class="k">Name (required, unique)</label>'
        '<input type="text" name="name" placeholder="e.g. field-team-1" required autocomplete="off"></p>'
        '<p><label class="k">Email (optional, curator-only)</label>'
        '<input type="text" name="email" placeholder="contact@example.org" autocomplete="off"></p>'
        '<p><button class="b-accent" type="submit">Create key</button></p>'
        '</form></div>'
    )
    if keys:
        trs = []
        for k in keys:
            if k.revoked_utc:
                status = (f'<span class="badge" style="background:{_PALETTE["bad"]}">revoked</span> '
                          f'<span class="k">{_esc(k.revoked_utc)} by curator:{_esc(k.revoked_by or "")}</span>')
                action = ""
            else:
                status = f'<span class="badge" style="background:{_PALETTE["ok"]}">active</span>'
                action = (
                    f'<form class="act" method="post" '
                    f'action="/gateway/curator/uploaders/{_esc(k.id)}/revoke" '
                    'data-confirm="Revoke this uploader key? This cannot be undone.">'
                    f'{csrf}'
                    '<button class="b-bad" type="submit">Revoke</button></form>')
            trs.append(
                "<tr>"
                f'<td>{_esc(k.name)}</td>'
                f'<td>{_esc(k.email or "-")}</td>'
                f'<td class="k">{_esc(k.created_utc)}<br>by curator:{_esc(k.created_by)}</td>'
                f'<td class="k">{_esc(k.last_used_utc or "never")}</td>'
                f'<td>{status}</td>'
                f'<td>{action}</td>'
                "</tr>"
            )
        table = ("<table><tr><th>Name</th><th>Email</th><th>Created</th><th>Last used</th>"
                 "<th>Status</th><th></th></tr>" + "".join(trs) + "</table>")
    else:
        table = '<p class="sub">No uploader keys issued yet.</p>'
    body = (
        '<h1>Uploader keys</h1>'
        f'<p class="sub">Signed in as curator:{_esc(curator_name)}</p>'
        f'{create}'
        f'<div class="panel"><h2>Issued keys</h2>{table}</div>'
    )
    if nav is not None:
        return _shell("AusMT uploader keys", body, nav=nav)
    return _page("AusMT uploader keys", body)


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


def render_detail(*, submission_id: str, state: str, updated_utc: str,
                  submitter_name: str, submitter_email: str, submitter_orcid: str | None,
                  validate_report: dict | None, preview_summary: dict | None,
                  cl: "checklist_mod.Checklist", csrf_token: str, note: str = "",
                  has_preview: bool) -> str:
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
    body = (
        f'<h1>Submission {_esc(submission_id[:12])} {_state_badge(state)}</h1>'
        f'<p class="sub">updated {_esc(updated_utc)} · <a href="/gateway/curator/queue">back to queue</a></p>'
        + _submitter_panel(name=submitter_name, email=submitter_email, orcid=submitter_orcid)
        + _checklist_panel(cl)
        + _reports_panel(validate_report=validate_report, preview_summary=preview_summary)
        + preview
        + note_panel
        + _action_forms(submission_id=submission_id, state=state, csrf_token=csrf_token, cl=cl)
    )
    return _page(f"AusMT submission {submission_id[:12]}", body)
