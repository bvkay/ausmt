"""Server-rendered curator pages (design §3/§4). MIRRORS statuspage.py: stdlib string.Template, no
framework, portal palette, minimal JS (plain forms; the only inline script is a submit-confirm on the
destructive actions). Every interpolated value is html.escaped — reports derive from submitted bytes
and MUST NOT inject markup into the curator's browser.

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

_TAIL = "</div></body></html>"


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


def render_queue(*, curator_name: str, rows: list, csrf_token: str) -> str:
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
    )
    return _page("AusMT curator queue", body)


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
            f'<form method="post" action="/gateway/curator/submission/{sid}/reject">{csrf}{note}'
            '<p><button class="b-bad" type="submit" '
            'onclick="return confirm(\'Reject this submission?\')">Reject</button></p>'
            '</form></div>'
        )
    elif state == states.PUBLISHED:
        forms.append(
            '<div class="panel"><h2>Published</h2>'
            '<p class="sub">Committed to surveys-live. Run <code>make rebuild-data</code> on the '
            'server to serve it — the commit is in git history but the live map is not rebuilt '
            'automatically.</p></div>'
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
            f'<p class="sub">Committed to surveys-live — run <code>make rebuild-data</code> on the '
            'server to serve it.</p>'
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
                    f'action="/gateway/curator/uploaders/{_esc(k.id)}/revoke">{csrf}'
                    '<button class="b-bad" type="submit" '
                    'onclick="return confirm(\'Revoke this uploader key? This cannot be undone.\')">'
                    'Revoke</button></form>')
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
            '<p><button type="button" class="b-accent" '
            'onclick="document.getElementById(\'prev\').classList.toggle(\'big\')">'
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
