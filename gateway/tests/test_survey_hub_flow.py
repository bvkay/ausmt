"""C43 Stage 1 survey-hub + nav-shell flow tests (record D13 verification pins), driven through the
real gateway HTTP surface with the in-process edit seam.

Load-bearing pins here:
  * CSP SWEEP (rendered): every C43 surface — the nav shell, the survey hub (both tabs), and the
    external JS routes — carries NO inline <script> and NO on*= handler (all dead under the
    strictPages CSP, script-src 'self'). Extends the source-level sweep in test_serve_reconcile.py
    with a RENDERED check over the new pages (the non-vacuous form: it inspects served bytes).
  * PER-SECTION PATCH (flow): submitting the hub's organisation section form (its widgets only)
    produces a preview whose diff touches organisation — and NOT a sibling section (lead_investigator)
    the form never carried. The runner-level byte pin lives in test_edit_runner.py; this proves the
    per-section FORM wiring delivers a section-scoped patch end-to-end.
  * SHELL PRESENCE: the rail (Stage-1 surfaces only, no Collections) + context bar (drift chip with
    the server-rendered published HEAD + Request-rebuild) render on every curator page.

Failure criterion is in each test's docstring (Invariant 10). Async bodies run under conftest.run().
"""
from __future__ import annotations

import re

from gateway.tests.conftest import (
    FakeGit, app_client, csrf_for_session, curator_login, inproc_edit_runner, run,
    write_survey_live,
)

# A survey with intra-section comments so a section edit's diff-minimality is observable through the
# hub's per-section form (the same fidelity the runner pin uses, one layer up).
HUB_SURVEY = """\
schema_version: "0.2"
slug: hub-survey-2026
project_name: Hub Survey
version: 1.0.0
region: South Australia

organisation:
  name: University of Example        # the lead org
  ror: null                          # ROR URL when known

lead_investigator:
  name: Ada Lovelace                 # PI of record
  orcid: "0000-0002-1825-0097"

# an unknown custom key the editor form does not model — must survive verbatim
custom_local_note: "keep me byte-for-byte"
"""


def _hub_client(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    write_survey_live(surveys_live, slug="hub-survey-2026", yaml_text=HUB_SURVEY)
    return surveys_live


def _assert_csp_clean(name: str, html: str) -> None:
    """No inline <script> without src=; no on*= handlers — all dead under the strictPages CSP."""
    for m in re.finditer(r"<script\b[^>]*>", html):
        assert re.search(r"\bsrc\s*=", m.group(0)), f"{name}: inline <script> is dead under CSP: {m.group(0)}"
    handlers = re.findall(r"<[^>]*\son[a-z]{2,}\s*=", html)
    assert handlers == [], f"{name}: inline event handlers are dead under CSP: {handlers}"


# --------------------------------------------------------------------------------------------------
# CSP SWEEP (rendered) — every C43 surface
# --------------------------------------------------------------------------------------------------
def test_c43_surfaces_are_csp_clean(tmp_path):
    """RENDERED CSP sweep of every C43 Stage-1 surface: the surveys list (nav shell), the survey hub
    Overview tab, the hub Metadata tab, the queue (shell), the uploader keys page (shell), and the two
    new external JS routes (raw JS, not <script>-wrapped, session-gated). FAILS IF any surface ships an
    inline <script> or an on*= handler, or a JS route serves HTML-wrapped script."""
    async def _body():
        surveys_live = _hub_client(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            for path, name in (
                ("/gateway/curator/edit", "surveys-list"),
                ("/gateway/curator/survey/hub-survey-2026", "hub-overview"),
                ("/gateway/curator/survey/hub-survey-2026?tab=metadata", "hub-metadata"),
                ("/gateway/curator/queue", "queue"),
                ("/gateway/curator/uploaders", "uploaders"),
                ("/gateway/curator/edit/hub-survey-2026", "edit-form"),
            ):
                r = await client.get(path)
                assert r.status_code == 200, (path, r.status_code)
                _assert_csp_clean(name, r.text)
            # The two new JS routes serve RAW JS (not <script>-wrapped), session-gated.
            for route in ("context-bar.js", "survey-hub.js"):
                r = await client.get(f"/gateway/curator/{route}")
                assert r.status_code == 200, route
                assert "javascript" in r.headers["content-type"], route
                assert "<script" not in r.text, f"{route} must be raw JS, not HTML-wrapped"
    run(_body())


def test_c43_js_routes_are_session_gated(tmp_path):
    """The C43 external JS routes redirect an ANONYMOUS request to login (303) — same gate as the
    pages that reference them. FAILS IF a route serves ungated or 404s (the page would load with a
    broken chrome)."""
    async def _body():
        surveys_live = _hub_client(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            for route in ("context-bar.js", "survey-hub.js"):
                r = await client.get(f"/gateway/curator/{route}", follow_redirects=False)
                assert r.status_code == 303, (route, r.status_code)
    run(_body())


# --------------------------------------------------------------------------------------------------
# NAV SHELL presence (S1-1)
# --------------------------------------------------------------------------------------------------
def test_nav_shell_rail_and_drift_chip_on_every_page(tmp_path):
    """Every session-gated curator page renders the left rail (with the Stage-1 surfaces and NOT
    Collections) and the context bar's drift chip carrying the server-rendered published HEAD +
    Request-rebuild button. FAILS IF a page loses the shell or the rail gains a Collections entry
    (Stage 3) before its stage."""
    async def _body():
        surveys_live = _hub_client(tmp_path)
        git = FakeGit()  # its rev-parse returns a stable short HEAD -> the chip shows it server-side
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            for path in ("/gateway/curator/queue", "/gateway/curator/edit",
                         "/gateway/curator/survey/hub-survey-2026",
                         "/gateway/curator/uploaders"):
                r = await client.get(path)
                assert r.status_code == 200, path
                assert 'class="rail"' in r.text, f"{path}: no left rail"
                # Rail carries the Stage-1 surfaces.
                assert 'href="/gateway/curator/edit"' in r.text          # Surveys
                assert 'href="/gateway/curator/queue"' in r.text          # Submission queue
                assert 'href="/gateway/curator/uploaders"' in r.text      # Uploader keys
                # Serve state: C43 S2b-i promoted the panel to a first-class screen, so the rail
                # now points at /gateway/curator/serve (was the queue's #serve-state anchor).
                assert 'href="/gateway/curator/serve"' in r.text           # Serve state
                # Collections is Stage 3 — NOT in the rail (not even as a disabled placeholder).
                assert ">Collections<" not in r.text, f"{path}: Collections leaked into the rail"
                # Drift chip + published HEAD + Request-rebuild button.
                assert 'id="drift-chip"' in r.text, f"{path}: no drift chip"
                assert "published HEAD" in r.text
                assert 'action="/gateway/curator/rebuild"' in r.text
                assert 'src="/gateway/curator/context-bar.js"' in r.text
    run(_body())


# --------------------------------------------------------------------------------------------------
# SURVEY HUB (S1-2)
# --------------------------------------------------------------------------------------------------
def test_survey_list_links_to_hub_not_edit_form(tmp_path):
    """The Surveys list rows link to the per-survey HUB (the task home), not straight to the edit
    form. FAILS IF a row reverts to linking the edit form (the hub is the Stage-1 entry point)."""
    async def _body():
        surveys_live = _hub_client(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get("/gateway/curator/edit")
            assert 'href="/gateway/curator/survey/hub-survey-2026"' in r.text
    run(_body())


def test_surveys_list_is_a_table_filled_browser_side(tmp_path):
    """C43 FR2-1 SURVEYS-TABLE PIN. The Surveys list is a proper TABLE (not a bare link list): a row
    per slug with Survey / Slug / Version / Licence / Stations columns, the slug rendered as a mono
    chip, the Survey cell linking to the hub, and data-cell placeholders the external surveys-list.js
    fills from the served corpus (surveys.json + build_report.json). The server renders only slugs (a
    directory listing, never content parsing); absent facts render '—'. FAILS IF the table/columns are
    absent, a row loses its data-survey-slug hook or hub link, or the enrichment script is not
    referenced."""
    async def _body():
        surveys_live = _hub_client(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get("/gateway/curator/edit")
            assert r.status_code == 200
            html = r.text
            assert 'id="surveys-table"' in html, "the surveys list must be a table"
            for col in ("<th>Survey</th>", "<th>Slug</th>", "<th>Version</th>",
                        "<th>Licence</th>", "<th>Stations</th>"):
                assert col in html, col
            assert 'data-survey-slug="hub-survey-2026"' in html, "each row carries its slug hook"
            assert 'href="/gateway/curator/survey/hub-survey-2026"' in html, "the row links to the hub"
            assert '<span class="slugchip">hub-survey-2026</span>' in html, "slug as a mono chip"
            assert 'data-cell="version"' in html and 'data-cell="stations"' in html
            assert 'src="/gateway/curator/surveys-list.js"' in html, "the enrichment script is referenced"
    run(_body())


def test_surveys_list_js_route_raw_and_session_gated(tmp_path):
    """The surveys-list.js route serves RAW JS (not <script>-wrapped) and is session-gated (anon =>
    303 to login), like the other C43 external scripts. FAILS IF it 404s, serves HTML, or is
    ungated."""
    async def _body():
        surveys_live = _hub_client(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            r_anon = await client.get("/gateway/curator/surveys-list.js", follow_redirects=False)
            assert r_anon.status_code == 303, "anonymous must redirect to login"
            await curator_login(client)
            r = await client.get("/gateway/curator/surveys-list.js")
            assert r.status_code == 200
            assert "javascript" in r.headers["content-type"]
            assert "<script" not in r.text.lower(), "raw JS, not HTML-wrapped"
            assert "surveys-table" in r.text and "build_report.json" in r.text
    run(_body())


def test_hub_overview_tab_scaffold_and_real_stations_history_tabs(tmp_path):
    """The Overview & QA tab renders the QA scaffold (browser-populated from /data). C43 Stage 2a: the
    Stations and History tab-strip entries are now REAL in-hub tabs (?tab=stations / ?tab=history),
    NOT the Stage-1 link-out/absence. FAILS IF the QA data-hook is missing, or the Stations/History
    tabs regress to the Stage-1 link-out / are absent."""
    async def _body():
        surveys_live = _hub_client(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get("/gateway/curator/survey/hub-survey-2026")
            assert r.status_code == 200
            # QA scaffold hooks (the JS fills them from /data/build_report.json + /data/build.json).
            assert 'data-survey-slug="hub-survey-2026"' in r.text
            assert 'id="qa-cards"' in r.text and 'id="qa-attention"' in r.text
            assert 'src="/gateway/curator/survey-hub.js"' in r.text
            # Stage 2a: Stations + History are real in-hub tabs (the tab strip points at ?tab=...).
            assert '?tab=stations">Stations' in r.text
            assert '?tab=history">History' in r.text
            # The Stage-1 Stations link-out to the removal page is GONE from the tab strip.
            assert 'stations">Stations (remove EDIs)' not in r.text
    run(_body())


def test_hub_metadata_tab_per_section_forms(tmp_path):
    """The Metadata tab renders a section TOC + one FORM per section (each posting only its own
    widgets to the preview route) + a per-section commit tray. FAILS IF the tab reverts to one giant
    form (per-section submit is the point) or drops the TOC / commit tray."""
    async def _body():
        surveys_live = _hub_client(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get("/gateway/curator/survey/hub-survey-2026?tab=metadata")
            assert r.status_code == 200
            forms = re.findall(r'data-hub-section-form="([^"]+)"', r.text)
            # Scalars + each structured section is its own form.
            assert "_scalars" in forms and "organisation" in forms and "lead_investigator" in forms
            assert len(forms) >= 6, forms
            assert 'class="toc"' in r.text                       # sticky section TOC
            assert "Only this section is submitted" in r.text     # commit-tray copy
            assert r.text.count(
                'action="/gateway/curator/edit/hub-survey-2026/preview"') == len(forms)
    run(_body())


def test_hub_per_section_submit_is_section_scoped(tmp_path):
    """PER-SECTION PATCH PIN (flow). Submit ONLY the organisation section's widgets (name unchanged,
    ror set) — the exact fields that section's form carries — and the preview diff changes organisation
    WITHOUT rewriting the untouched lead_investigator section. FAILS IF a per-section submit leaks a
    sibling section into the patch/diff (the wiring must deliver a section-scoped patch)."""
    async def _body():
        surveys_live = _hub_client(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            # Exactly the organisation section form's payload: its two widgets + its snapshot + the
            # commit tray fields. NO other section's widgets — that is what "per-section submit" means.
            data = {
                "s_organisation_name": "University of Example",
                "s_organisation_ror": "https://ror.org/03yghzc09",
                "o_organisation": '{"name": "University of Example", "ror": null}',
                "note": "add ROR", "bump": "patch", "csrf_token": csrf,
            }
            r = await client.post("/gateway/curator/edit/hub-survey-2026/preview",
                                  data=data, follow_redirects=False)
            assert r.status_code == 200
            assert "03yghzc09" in r.text                    # the ROR change is previewed
            assert "new version 1.0.1" in r.text
            # The diff must NOT rewrite lead_investigator — a section the form never carried.
            pre = re.search(r"<pre>(.*?)</pre>", r.text, re.S)
            assert pre, "no diff panel rendered"
            import html as _html
            changed = [ln for ln in _html.unescape(pre.group(1)).splitlines()
                       if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
            for needle in ("Ada Lovelace", "PI of record", "lead_investigator"):
                assert not any(needle in ln for ln in changed), \
                    f"per-section submit leaked section B ({needle!r}) into the diff:\n{changed}"
    run(_body())
