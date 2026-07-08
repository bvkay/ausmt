"""End-to-end tests for the STRUCTURED metadata-editor form (the 2026-07-08 "hostile JSON" rework),
driven through the real gateway HTTP surface with the in-process edit seam.

The load-bearing test here is the ROUND-TRIP: render the edit form from a real, richly-populated
survey.yaml, harvest EXACTLY the fields a browser would submit (unchanged), POST them, and assert the
preview shows NO diff. If the widget <-> section-dict mapping drifts by a single key/null, this fails.

Also covered: the form renders widgets (not the old raw-JSON textareas) for populated sections; empty
optional sections render empty widgets with example placeholders (never a null-skeleton); the advanced
raw-JSON <details> override; per-field validation errors (bad ORCID / bad DOI) rendered on the form;
spare blank rows submitted empty are ignored; the editor.js route + CSP (no inline JS).

Failure criterion is in each test's docstring (Invariant 10). Async bodies run under conftest.run().
"""
from __future__ import annotations

import html as _html
import re

from gateway.tests.conftest import (
    FakeGit, app_client, csrf_for_session, curator_login, inproc_edit_runner, run,
    write_survey_live,
)

# A richly-populated block-style survey.yaml exercising EVERY structured section the widgets model:
# a map with a null (organisation.ror), a lead_investigator, repeatable principal_investigators /
# publications (dict form) / funding / instruments, a full identifiers map, time_series with a
# levels list, access, processing, collection, and a care block (advanced-JSON-only section). An
# unknown key + a comment prove the round-trip fidelity is unbroken by the widget rework.
RICH_SURVEY = """\
schema_version: "0.2"
slug: rich-survey-2026
project_name: Rich Survey            # human-readable name
version: 1.0.0
country: Australia
region: South Australia

organisation:
  name: University of Example
  ror: null

lead_investigator:
  name: Ada Lovelace
  orcid: "0000-0002-1825-0097"

principal_investigators:
  - name: Grace Hopper
    orcid: "0000-0001-6062-4323"
  - name: Katherine Johnson
    orcid: null

identifiers:
  dataset_doi: "10.5281/zenodo.123"
  related_publication: A paper
  related_publication_doi: "10.1000/xyz"
  project: Campaign One
  project_raid: null

publications:
  - author: Hopper G.
    year: "2026"
    title: A study
    journal: J. Geophys.
    doi: "10.1000/pub"

funding:
  - organisation: AuScope
    organisation_ror: null
    grant_id: ARC-123
    grant_title: A grant
    funding_doi: null

instruments:
  - manufacturer: Phoenix
    model: MTU-5C
    pid: null

time_series:
  collection_pid: "10.25914/abc"
  levels_available:
    - raw_packed
    - level0

access:
  level: embargoed
  embargo_until: "2027-01-01"
  contact: release@example.org

processing:
  software: BIRRP
  version: null
  remote_reference: unknown
  notes: null

collection:
  id: auslamp
  title: AusLAMP
  type: programme
  status: completed

care:
  traditional_owner_acknowledgement: null
  land_access: { permission_obtained: unknown, agreement_type: null }
  restrictions_requested: false

# an unknown custom key the editor form does not model — must survive verbatim
custom_local_note: "keep me byte-for-byte"
"""


def _harvest_form_fields(body: str) -> dict:
    """Reconstruct the exact name/value pairs a browser would submit for the FIRST <form> on the
    page, UNCHANGED. Covers <input> (text/date/email/hidden/radio/checkbox), <textarea>, and
    <select>. Radios/checkboxes contribute only when checked; a select contributes its selected
    option; a textarea contributes its (possibly empty) content. Deliberately minimal HTML parsing —
    the rendered markup is our own, escaped, single-quoted-attribute-free where it matters."""
    # Isolate the main edit <form> (there is one form on the edit page).
    form_start = body.index('<form method="post"')
    form_html = body[form_start:body.index("</form>", form_start)]
    fields: dict[str, str] = {}

    # <input ...>
    for tag in re.findall(r"<input\b[^>]*>", form_html):
        name = _attr(tag, "name")
        if not name:
            continue
        itype = (_attr(tag, "type") or "text").lower()
        value = _html.unescape(_attr(tag, "value") or "")
        if itype in ("radio", "checkbox"):
            if " checked" in tag or "checked>" in tag or "checked " in tag:
                fields[name] = value or "1"
        else:
            fields[name] = value

    # <textarea name=...>...</textarea>
    for m in re.finditer(r'<textarea\b[^>]*\bname="([^"]+)"[^>]*>(.*?)</textarea>',
                         form_html, re.S):
        fields[m.group(1)] = _html.unescape(m.group(2))

    # <select name=...>...</select> -> the selected <option> (or the first if none marked)
    for m in re.finditer(r'<select\b[^>]*\bname="([^"]+)"[^>]*>(.*?)</select>', form_html, re.S):
        name, inner = m.group(1), m.group(2)
        sel = re.search(r'<option\b[^>]*\bselected[^>]*value="([^"]*)"', inner) or \
            re.search(r'<option\b[^>]*value="([^"]*)"[^>]*\bselected', inner)
        if sel:
            fields[name] = _html.unescape(sel.group(1))
        else:
            first = re.search(r'<option\b[^>]*value="([^"]*)"', inner)
            if first:
                fields[name] = _html.unescape(first.group(1))
    return fields


def _attr(tag: str, name: str) -> str | None:
    m = re.search(rf'\b{name}="([^"]*)"', tag)
    return m.group(1) if m else None


def _rich_client(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    pkg = write_survey_live(surveys_live, slug="rich-survey-2026", yaml_text=RICH_SURVEY)
    return surveys_live, pkg


# --------------------------------------------------------------------------------------------------
# CRITICAL: render the form from a real survey.yaml, submit it UNCHANGED, expect NO diff.
# --------------------------------------------------------------------------------------------------
def test_unchanged_form_submit_produces_no_diff(tmp_path):
    """Render the edit form from a richly-populated survey.yaml, harvest exactly the fields a browser
    would submit, POST them unchanged, and the merge must refuse as a NO-OP (no changes) — proving
    the widget<->section mapping round-trips byte-for-byte. FAILS IF any section reassembles to a
    value differing from the original (a spurious diff / a real edit the curator never made)."""
    async def _body():
        surveys_live, _pkg = _rich_client(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            form_html = (await client.get("/gateway/curator/edit/rich-survey-2026")).text
            fields = _harvest_form_fields(form_html)
            # Fill the required release note + bump so the POST is well-formed; everything else is the
            # harvested, unchanged form.
            fields["note"] = "no-op test"
            fields["bump"] = "patch"
            fields["csrf_token"] = csrf
            r = await client.post("/gateway/curator/edit/rich-survey-2026/preview",
                                  data=fields, follow_redirects=False)
            assert r.status_code == 200
            # A true no-op: the runner refuses with "no changes" (nothing reassembled to a diff).
            assert "no changes" in r.text.lower(), (
                "an unchanged structured-form submit must be a no-op — a diff here means a section "
                "widget did not round-trip")
    run(_body())


def test_single_widget_edit_produces_targeted_diff(tmp_path):
    """Change ONE widget (organisation ROR from null to a URL) and submit; the preview shows that one
    change and nothing else spurious. FAILS IF editing one field silently rewrites other sections."""
    async def _body():
        surveys_live, _pkg = _rich_client(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            form_html = (await client.get("/gateway/curator/edit/rich-survey-2026")).text
            fields = _harvest_form_fields(form_html)
            fields["s_organisation_ror"] = "https://ror.org/03yghzc09"
            fields["note"] = "add ROR"
            fields["bump"] = "patch"
            fields["csrf_token"] = csrf
            r = await client.post("/gateway/curator/edit/rich-survey-2026/preview",
                                  data=fields, follow_redirects=False)
            assert r.status_code == 200
            assert "03yghzc09" in r.text            # the ROR change shows in the diff
            assert "new version 1.0.1" in r.text
            # No other section leaked into the diff: the access contact / PI names are unchanged, so
            # they must NOT appear as +/- diff lines (they appear only if rewritten).
            diff = r.text[r.text.index("Changes to survey.yaml"):]
            assert "release@example.org" not in _added_removed_lines(diff)
            assert "Grace Hopper" not in _added_removed_lines(diff)
    run(_body())


def _added_removed_lines(diff_html: str) -> str:
    """The +/- body lines of the rendered unified diff (rough: lines starting with + or - inside the
    <pre>), so a test can assert an unchanged value did NOT move."""
    pre = re.search(r"<pre>(.*?)</pre>", diff_html, re.S)
    if not pre:
        return ""
    out = []
    for line in _html.unescape(pre.group(1)).splitlines():
        if line[:1] in "+-" and not line.startswith(("+++", "---")):
            out.append(line)
    return "\n".join(out)


# --------------------------------------------------------------------------------------------------
# widgets, not JSON textareas
# --------------------------------------------------------------------------------------------------
def test_form_renders_widgets_not_json_textareas(tmp_path):
    """A populated survey renders structured widgets (named s_/l_/c_ inputs, an access <select>) and
    NOT the old raw-JSON textareas (j_organisation etc. as the PRIMARY input). FAILS IF the sections
    revert to bare JSON textareas — the whole point of the 2026-07-08 rework."""
    async def _body():
        surveys_live, _pkg = _rich_client(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            body = (await client.get("/gateway/curator/edit/rich-survey-2026")).text
            # Structured widgets present:
            assert 'name="s_organisation_name"' in body
            assert 'name="s_organisation_ror"' in body
            assert 'name="s_lead_investigator_orcid"' in body
            assert 'name="s_access_level"' in body and "<select" in body
            assert 'name="s_access_embargo_until"' in body and 'type="date"' in body
            assert 'name="l_principal_investigators_0_name"' in body      # repeatable row
            assert 'name="c_time_series_levels_available_raw_packed"' in body  # checkbox
            # The prefilled values landed in the widgets:
            assert 'value="University of Example"' in body
            assert 'value="Ada Lovelace"' in body
            assert 'value="Grace Hopper"' in body
            # The advanced <details> JSON box exists but is the FALLBACK, not the primary input:
            assert "<details" in body and 'name="j_organisation"' in body
            # The ROR hint links to ror.org (no api.ror.org fetch — CSP has no connect-src for it):
            assert 'href="https://ror.org"' in body
            assert "api.ror.org" not in body
    run(_body())


def test_empty_optional_sections_render_empty_widgets_with_placeholders(tmp_path):
    """A survey with NO optional sections renders the widgets empty with example placeholders — never
    a bare void, never a pre-filled JSON null-skeleton. FAILS IF an empty section shows a raw JSON of
    nulls as the input, or omits the widget entirely."""
    async def _body():
        # The minimal EDIT_EXEMPLAR fixture (default) has organisation + access only; identifiers,
        # instruments, publications, funding, PIs, collection, processing, time_series are ABSENT.
        surveys_live = tmp_path / "surveys-live"
        write_survey_live(surveys_live)  # default demo-survey-2026 (sparse)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            body = (await client.get("/gateway/curator/edit/demo-survey-2026")).text
            # Absent sections still render their widgets (empty), with example placeholders:
            assert 'name="s_identifiers_dataset_doi"' in body
            assert 'placeholder="10.xxxx/xxxxx"' in body           # DOI example
            assert 'name="l_instruments_0_manufacturer"' in body   # a spare blank row exists
            assert 'placeholder="Phoenix"' in body                 # instrument example
            # An absent section carries NO o_<section> snapshot (so it stays absent on submit):
            assert 'name="o_identifiers"' not in body
            # And it is NOT a pre-filled JSON skeleton of nulls in the primary textarea:
            assert '"dataset_doi": null' not in body.split("<details")[0]
    run(_body())


# --------------------------------------------------------------------------------------------------
# per-field validation errors render on the form
# --------------------------------------------------------------------------------------------------
def test_bad_orcid_renders_field_error_on_form(tmp_path):
    """A bad lead-investigator ORCID re-renders the FORM with a per-field error (not a blanket
    failure, not a commit). FAILS IF a malformed ORCID is accepted or produces only a generic error."""
    async def _body():
        surveys_live, _pkg = _rich_client(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            form_html = (await client.get("/gateway/curator/edit/rich-survey-2026")).text
            fields = _harvest_form_fields(form_html)
            fields["s_lead_investigator_orcid"] = "0000-0000-0000-0000"  # bad checksum
            fields["note"] = "x"
            fields["bump"] = "patch"
            fields["csrf_token"] = csrf
            r = await client.post("/gateway/curator/edit/rich-survey-2026/preview",
                                  data=fields, follow_redirects=False)
            assert r.status_code == 200
            # Back on the FORM (not the preview), with an ORCID error, and the typed value preserved.
            assert 'action="/gateway/curator/edit/rich-survey-2026/preview"' in r.text
            assert "ORCID" in r.text and "checksum" in r.text.lower()
            assert 'value="0000-0000-0000-0000"' in r.text  # not discarded
    run(_body())


def test_bad_doi_renders_field_error_on_form(tmp_path):
    """A dataset DOI without a '10.' prefix re-renders the form with a per-field error. FAILS IF a
    non-DOI is accepted into a DOI field."""
    async def _body():
        surveys_live, _pkg = _rich_client(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            form_html = (await client.get("/gateway/curator/edit/rich-survey-2026")).text
            fields = _harvest_form_fields(form_html)
            fields["s_identifiers_dataset_doi"] = "not-a-doi"
            fields["note"] = "x"
            fields["bump"] = "patch"
            fields["csrf_token"] = csrf
            r = await client.post("/gateway/curator/edit/rich-survey-2026/preview",
                                  data=fields, follow_redirects=False)
            assert r.status_code == 200
            assert "DOI" in r.text and "10." in r.text
            assert 'value="not-a-doi"' in r.text
    run(_body())


# --------------------------------------------------------------------------------------------------
# advanced-JSON override precedence, end-to-end
# --------------------------------------------------------------------------------------------------
def test_advanced_json_override_end_to_end(tmp_path):
    """Filling a section's advanced <details> JSON box OVERRIDES its widgets end-to-end. FAILS IF the
    widgets win over the raw-JSON fallback through the real merge."""
    async def _body():
        surveys_live, _pkg = _rich_client(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            form_html = (await client.get("/gateway/curator/edit/rich-survey-2026")).text
            fields = _harvest_form_fields(form_html)
            # Widget says level stays embargoed; advanced JSON flips it to metadata_only + clears the
            # contact — the JSON must win.
            fields["j_access"] = '{"level": "metadata_only", "embargo_until": null, "contact": null}'
            fields["note"] = "override via json"
            fields["bump"] = "patch"
            fields["csrf_token"] = csrf
            r = await client.post("/gateway/curator/edit/rich-survey-2026/preview",
                                  data=fields, follow_redirects=False)
            assert r.status_code == 200
            assert "metadata_only" in r.text
    run(_body())


# --------------------------------------------------------------------------------------------------
# spare blank rows are ignored; the editor.js route + CSP
# --------------------------------------------------------------------------------------------------
def test_spare_blank_rows_ignored(tmp_path):
    """The server-rendered SPARE blank rows (the no-JS add path) submitted empty are dropped — an
    unchanged submit stays a no-op even though the form carried blank instrument/PI/etc. rows. FAILS
    IF a blank spare row lands in the yaml as a row of nulls."""
    async def _body():
        surveys_live, _pkg = _rich_client(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            form_html = (await client.get("/gateway/curator/edit/rich-survey-2026")).text
            # The rendered form has spare blank rows (indices beyond the populated ones).
            assert 'name="l_instruments_1_manufacturer"' in form_html  # a spare row exists
            fields = _harvest_form_fields(form_html)
            fields["note"] = "noop"
            fields["bump"] = "patch"
            fields["csrf_token"] = csrf
            r = await client.post("/gateway/curator/edit/rich-survey-2026/preview",
                                  data=fields, follow_redirects=False)
            assert r.status_code == 200
            assert "no changes" in r.text.lower()  # spare rows dropped -> still a no-op
    run(_body())


def test_js_added_row_at_arbitrary_index_lands_in_yaml(tmp_path):
    """A row the client-side JS appends carries a fresh, possibly NON-CONTIGUOUS index (e.g.
    l_instruments_7_*); the server discovers rows by name, not a fixed count, so it must be picked
    up. FAILS IF row assembly assumes contiguous 0..N indices (the JS-added row would be silently
    dropped — the exact symptom the jsdom harness guards against on the client side)."""
    async def _body():
        surveys_live, _pkg = _rich_client(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            form_html = (await client.get("/gateway/curator/edit/rich-survey-2026")).text
            fields = _harvest_form_fields(form_html)
            # Simulate a JS-added instrument row at a high, non-contiguous index.
            fields["l_instruments_7_manufacturer"] = "Metronix"
            fields["l_instruments_7_model"] = "ADU-08e"
            fields["note"] = "add instrument"
            fields["bump"] = "patch"
            fields["csrf_token"] = csrf
            r = await client.post("/gateway/curator/edit/rich-survey-2026/preview",
                                  data=fields, follow_redirects=False)
            assert r.status_code == 200
            assert "Metronix" in r.text and "ADU-08e" in r.text  # the JS-added row reached the diff
    run(_body())


def test_editor_js_route_and_no_inline_js(tmp_path):
    """GET /gateway/curator/editor.js serves the row JS (session-gated, javascript type, RAW not
    HTML-wrapped); the edit page references it externally and carries ZERO inline scripts / on*=
    handlers (the strictPages CSP pin). FAILS IF the row JS is inlined (dead under Caddy) or the route
    is missing/ungated."""
    import re as _re
    async def _body():
        surveys_live, _pkg = _rich_client(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            # Ungated => redirect to login.
            r_anon = await client.get("/gateway/curator/editor.js", follow_redirects=False)
            assert r_anon.status_code == 303
            await curator_login(client)
            r = await client.get("/gateway/curator/editor.js")
            assert r.status_code == 200
            assert "javascript" in r.headers["content-type"]
            assert "<script" not in r.text  # raw JS, not wrapped
            assert "data-editor-add-row" in r.text
            # The edit page: external script reference, no inline JS, no on*= handlers.
            body = (await client.get("/gateway/curator/edit/rich-survey-2026")).text
            assert 'src="/gateway/curator/editor.js"' in body
            for m in _re.finditer(r"<script\b[^>]*>", body):
                assert _re.search(r"\bsrc\s*=", m.group(0)), f"inline script on edit page: {m.group(0)}"
            assert _re.findall(r"<[^>]*\son\w+\s*=", body) == []
    run(_body())
