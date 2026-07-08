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
</style></head>
<body><div class="wrap">
"""

# Every curator page loads the shared UI script (delegated data-confirm / data-toggle-big handlers)
# as an EXTERNAL same-origin script — the strictPages CSP (script-src 'self') silently blocks inline
# script blocks AND on*-attribute handlers on every /gateway/* page, so inline handlers are dead code
# that only fails in production (three shipped that way and never ran; found 2026-07-08).
_TAIL = '<script src="/gateway/curator/ui.js" defer></script></div></body></html>'


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


def _esc(value) -> str:
    return html.escape(str(value), quote=True)


def _page(title: str, body: str) -> str:
    head = Template(_HEAD).substitute(
        title=_esc(title), bg=_PALETTE["bg"], ink=_PALETTE["ink"], muted=_PALETTE["muted"],
        accent=_PALETTE["accent"], panel=_PALETTE["panel"], ok=_PALETTE["ok"],
        warn=_PALETTE["warn"], bad=_PALETTE["bad"],
    )
    return head + body + _TAIL


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
                 serve_panel: str = "") -> str:
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
        f'<p class="sub">Signed in as curator:{_esc(curator_name)} '
        '· <a href="/gateway/curator/edit">Edit published metadata</a> '
        '· <a href="/gateway/curator/uploaders">Uploader keys</a> '
        f'{logout}</p>'
        f'<div class="panel">{table}</div>'
        f'{serve_panel}'
    )
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
          if (c.stations) line += '  [stations: ' + c.stations.join(', ') + ']';
          else if (c.except) line += '  [all except: ' + c.except.join(', ') + ']';
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

# The editable fields, grouped like the add-survey page (C31 §2). Scalars render as an input/
# textarea; structured fields (maps + lists) render as a JSON textarea — the curator edits the
# structure directly, escaped, and the gateway parses it back to a patch WITHOUT importing yaml
# (json is stdlib, not survey content — the §0.1 rule is about YAML/EDI parsing). ORCID/ROR hints
# are text-only (C31 §2 — no live API calls from the curator page).
_EDIT_SCALARS = (
    ("project_name", "Project name"),
    ("name", "Name (backward-compatible alias)"),
    ("region", "Region"),
    ("license", "Licence (e.g. CC-BY-4.0)"),
)
_EDIT_TEXTAREAS = (
    ("abstract", "Abstract"),
)
_EDIT_JSON = (
    ("organisation", "Organisation {name, ror}"),
    ("lead_investigator", "Lead investigator {name, orcid}"),
    ("principal_investigators", "Principal investigators [ {name, orcid}, … ]"),
    ("identifiers", "Identifiers {dataset_doi, survey_pid, …}"),
    ("publications", "Publications [ … ]"),
    ("funding", "Funding [ … ]"),
    ("instruments", "Instruments [ {manufacturer, model, pid}, … ]"),
    ("time_series", "Time series {collection_pid, levels_available}"),
    ("access", "Access {level, embargo_until, contact}"),
    ("collection", "Collection {id, title, type, status}"),
    ("processing", "Processing {software, version, remote_reference, notes}"),
    ("care", "CARE governance {…}"),
)


def _json_text(value) -> str:
    import json as _json
    return _json.dumps(value, indent=2, ensure_ascii=False)


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


def render_edit_form(*, slug: str, version: str | None, fields: dict, csrf_token: str,
                     error: str = "") -> str:
    """The seed form (C31 §1.2): server-rendered, escaped, prefilled from the runner's editable
    subset. Scalars are inputs, abstract a textarea, structured fields JSON textareas. A version-bump
    radio group (patch default) + a required release-note box carry the C31 §0.3 discipline."""
    err = f'<p class="sub" style="color:{_PALETTE["bad"]}">{_esc(error)}</p>' if error else ""
    cur = version or "0.0.0"
    patch_v = _suggest_bump(cur, "patch")
    minor_v = _suggest_bump(cur, "minor")
    major_v = _suggest_bump(cur, "major")
    rows = []
    for key, label in _EDIT_SCALARS:
        val = fields.get(key, "")
        val = "" if val is None else val
        rows.append(f'<p><label class="k">{_esc(label)}</label>'
                    f'<input type="text" name="f_{key}" value="{_esc(val)}"></p>')
    for key, label in _EDIT_TEXTAREAS:
        val = fields.get(key, "")
        val = "" if val is None else val
        rows.append(f'<p><label class="k">{_esc(label)}</label>'
                    f'<textarea name="f_{key}">{_esc(val)}</textarea></p>')
    for key, label in _EDIT_JSON:
        present = key in fields
        val = _json_text(fields[key]) if present else ""
        rows.append(f'<p><label class="k">{_esc(label)} <span class="sub">(JSON; leave blank to '
                    f'leave unchanged)</span></label>'
                    f'<textarea name="j_{key}" rows="4">{_esc(val)}</textarea></p>')
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
        f'<a href="/gateway/curator/queue">back to queue</a></p>'
        f'{err}'
        f'<form method="post" action="/gateway/curator/edit/{_esc(slug)}/preview">'
        f'<div class="panel">{"".join(rows)}</div>'
        f'<div class="panel">{bump}'
        '<p><label class="k">Release note (required)</label>'
        '<textarea name="note" placeholder="What changed and why" required></textarea></p>'
        f'{csrf}'
        '<p><button class="b-accent" type="submit">Preview change</button></p>'
        '</div></form>'
    )
    return _page(f"AusMT edit {slug}", body)


def render_edit_preview(*, slug: str, version: str, diff: str, validate_report: dict | None,
                        has_fail: bool, new_sha256: str, note: str, patch_json: str,
                        bump: str, csrf_token: str) -> str:
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
    return _page(f"AusMT preview {slug}", body)


def render_edit_list(*, curator_name: str, slugs: list, csrf_token: str) -> str:
    """A small index of PUBLISHED surveys that can be edited (C31 §1.1)."""
    if slugs:
        items = "".join(
            f'<li><a href="/gateway/curator/edit/{_esc(s)}">{_esc(s)}</a></li>' for s in slugs)
        listing = f"<ul>{items}</ul>"
    else:
        listing = '<p class="sub">No published surveys in surveys-live.</p>'
    body = (
        '<h1>Edit published metadata</h1>'
        f'<p class="sub">Signed in as curator:{_esc(curator_name)} · '
        '<a href="/gateway/curator/queue">back to queue</a></p>'
        f'<div class="panel">{listing}</div>'
    )
    return _page("AusMT edit metadata", body)


# ---- uploader keys (schema v2 — curator-managed submit keys) ---------------------------------

def render_uploaders(*, curator_name: str, keys: list, csrf_token: str, error: str = "") -> str:
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
        f'<p class="sub">Signed in as curator:{_esc(curator_name)} · '
        '<a href="/gateway/curator/queue">back to queue</a></p>'
        f'{create}'
        f'<div class="panel"><h2>Issued keys</h2>{table}</div>'
    )
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
