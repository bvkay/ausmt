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


# SIDEBARMERGE (owner ruling 2026-07-24): a survey carrying EVERY merged-away section (organisation +
# instruments under Core fields; lead + principal under Investigators; identifiers + related_identifiers +
# time_series under Identifiers & PIDs), each with intra-section comments and a RETIRED/legacy key
# (instruments[].pid, time_series.collection_pid) so a merged-form edit's diff-minimality and the
# byte-preservation of legacy keys are both observable end-to-end.
MERGE_SURVEY = """\
schema_version: "0.2"
slug: merge-survey-2026
project_name: Merge Survey
version: 1.0.0
region: South Australia
license: CC-BY-4.0

organisation:
  name: University of Example        # the lead org
  ror: null                          # ROR URL when known

instruments:
  - manufacturer: Phoenix            # instrument make
    model: MTU-5C                    # instrument model
    pid: "10.99999/LEGACYPID"        # RETIRED per-row key: must survive an unrelated merged-form edit

lead_investigator:
  name: Ada Lovelace                 # PI of record
  orcid: "0000-0002-1825-0097"

principal_investigators:
  - name: Grace Hopper               # a principal
    orcid: "0000-0001-2345-6789"

identifiers:
  project_raid: https://raid.org/10.1234/OLDRAID   # the project PID

related_identifiers:
  - identifier: "10.25914/existing-doi"            # dataset DOI at NCI
    identifier_type: DOI
    relation: IsVariantFormOf
    custodian: NCI

time_series:
  levels_available:                  # which processing levels EXIST in the archive
    - raw_packed
    - level0
  collection_pid: "10.88888/LEGACYTS"  # RETIRED key: must survive an unrelated merged-form edit
"""


def _merge_client(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    write_survey_live(surveys_live, slug="merge-survey-2026", yaml_text=MERGE_SURVEY)
    return surveys_live


def _diff_changed(text: str) -> list[str]:
    """The +/- content lines of the preview diff (excluding the ---/+++ file headers)."""
    import html as _html
    pre = re.search(r"<pre>(.*?)</pre>", text, re.S)
    assert pre, "no diff panel rendered:\n" + text
    return [ln for ln in _html.unescape(pre.group(1)).splitlines()
            if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]


def _canon(value) -> str:
    """A hidden o_<section> snapshot value (any valid JSON of the original; the round-trip compare is
    order-independent). Mirrors what the rendered form embeds."""
    import json
    return json.dumps(value, sort_keys=True)


def _hub_client(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    write_survey_live(surveys_live, slug="hub-survey-2026", yaml_text=HUB_SURVEY)
    return surveys_live


# IDCONS: a survey that already carries an identifiers map (project_raid) AND a typed related_identifiers
# row, so the consolidated hub section renders BOTH groups' o_<section> snapshots and prefills the existing
# values — the shape a curator round-trips through the folded section.
HUB_SURVEY_IDS = """\
schema_version: "0.2"
slug: hub-ids-2026
project_name: Hub IDs Survey
version: 1.0.0
region: South Australia

identifiers:
  project_raid: https://raid.org/10.1234/OLDRAID   # the one project PID a curator sets here

related_identifiers:
  - identifier: "10.25914/existing-doi"            # the dataset's DOI at NCI (typed provenance)
    identifier_type: DOI
    relation: IsVariantFormOf
    custodian: NCI

organisation:
  name: University of Example

lead_investigator:
  name: Ada Lovelace
  orcid: "0000-0002-1825-0097"
"""


def _hub_ids_client(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    write_survey_live(surveys_live, slug="hub-ids-2026", yaml_text=HUB_SURVEY_IDS)
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
    """Every session-gated curator page renders the left rail (the Stage-1 surfaces PLUS the Stage-3a
    Collections entry, record D5-A) and the context bar's drift chip carrying the server-rendered
    published HEAD + Request-rebuild button. FAILS IF a page loses the shell or the rail drops a
    surface."""
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
                # Collections joined the rail in Stage 3a (record D5-A) — present on every page (not
                # the active item on these non-collections pages).
                assert 'href="/gateway/curator/collections">Collections</a>' in r.text, \
                    f"{path}: Collections missing from the rail"
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


def test_hub_metadata_identifiers_consolidated_one_section(tmp_path):
    """IDCONS D1 (SPEC §2) — the HUB Metadata tab (the sidebar editor the curator actually uses) renders
    the identifier surface as ONE consolidated 'Identifiers & PIDs' section, exactly like the full form.
    The sidebar/TOC shows a SINGLE entry (no standalone 'Related identifiers' section), the consolidated
    form carries BOTH the identifiers map widgets (project_raid) AND the typed related_identifiers list
    rows, and the plain-language guidance copy is present. FAILS RED against the pre-fix hub, which
    rendered the plain 'Identifiers' map panel AND a separate 'Related identifiers' list panel."""
    async def _body():
        surveys_live = _hub_ids_client(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get("/gateway/curator/survey/hub-ids-2026?tab=metadata")
            assert r.status_code == 200
            body = r.text
            forms = re.findall(r'data-hub-section-form="([^"]+)"', body)
            # ONE consolidated identifiers section; the standalone related_identifiers section is GONE.
            assert "identifiers" in forms, forms
            assert "related_identifiers" not in forms, \
                "the hub still renders a standalone 'related_identifiers' section form: " + repr(forms)
            # The sidebar/TOC has ONE 'Identifiers & PIDs' entry and NO 'Related identifiers' entry.
            toc = re.findall(r'data-hub-section="([^"]+)"', body)
            assert toc.count("identifiers") == 1 and "related_identifiers" not in toc, toc
            assert body.count('data-hub-section="identifiers">Identifiers &amp; PIDs') == 1
            # The consolidated FORM carries BOTH groups' widgets + BOTH round-trip snapshots — the identifiers
            # map (project_raid) and the typed related_identifiers list rows — so one section post round-trips
            # both. The existing stored values are prefilled.
            form_html = body.split('data-hub-section-form="identifiers"', 1)[1].split("</form>", 1)[0]
            assert 'name="s_identifiers_project_raid"' in form_html
            assert "10.1234/OLDRAID" in form_html                                # existing map value prefilled
            assert 'name="l_related_identifiers_0_identifier"' in form_html
            assert "10.25914/existing-doi" in form_html                          # existing typed row prefilled
            assert 'name="o_identifiers"' in form_html and 'name="o_related_identifiers"' in form_html
            # Plain-language guidance (the heart of the owner complaint) is present in the panel.
            assert "Where does it go?" in form_html
            assert "Derived from (this data was processed from it)" in form_html  # human relation label
            assert 'value="IsDerivedFrom"' in form_html                          # exact vocab still POSTed
            assert ">Related identifiers</h2>" not in body                       # no duplicate list panel
    run(_body())


def test_hub_consolidated_section_round_trips_both_groups(tmp_path):
    """IDCONS D1 — a SINGLE post of the consolidated 'Identifiers & PIDs' hub section round-trips BOTH the
    identifiers MAP fields (project_raid) AND the related_identifiers LIST rows: build_section_patch
    iterates every widget section and assembles whichever widgets are present, so one form carrying both
    groups produces a patch touching both keys. FAILS IF the combined section post drops either group."""
    async def _body():
        surveys_live = _hub_client(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            # The consolidated section form's payload: an identifiers MAP widget (project_raid) AND a typed
            # related_identifiers LIST row — the exact widgets the one folded section carries. No o_ snapshots
            # (the fixture has neither key) so both assemble as fresh additions from ONE post.
            data = {
                "s_identifiers_project_raid": "https://raid.org/10.5555/HUBRAID",
                "l_related_identifiers_0_identifier": "10.25914/hub-newrow",
                "l_related_identifiers_0_identifier_type": "DOI",
                "l_related_identifiers_0_relation": "IsDerivedFrom",
                "l_related_identifiers_0_custodian": "NCI",
                "note": "record dataset provenance", "bump": "patch", "csrf_token": csrf,
            }
            r = await client.post("/gateway/curator/edit/hub-survey-2026/preview",
                                  data=data, follow_redirects=False)
            assert r.status_code == 200
            pre = re.search(r"<pre>(.*?)</pre>", r.text, re.S)
            assert pre, "no diff panel rendered:\n" + r.text
            import html as _html
            added = [ln for ln in _html.unescape(pre.group(1)).splitlines()
                     if ln.startswith("+") and not ln.startswith("+++")]
            blob = "\n".join(added)
            assert "10.5555/HUBRAID" in blob, \
                "the identifiers MAP field (project_raid) did not round-trip through the combined post:\n" + blob
            assert "10.25914/hub-newrow" in blob, \
                "the related_identifiers LIST row did not round-trip through the combined post:\n" + blob
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
            # Scalars + each (possibly merged) sidebar section is its own form. SIDEBARMERGE: organisation
            # and instruments are folded into the "Core fields" (_scalars) form and are NOT standalone;
            # the merged "Investigators" form keeps the lead_investigator key.
            assert "_scalars" in forms and "lead_investigator" in forms
            assert "organisation" not in forms, \
                "organisation must be folded into the merged Core fields form, not a standalone form"
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


# --------------------------------------------------------------------------------------------------
# SIDEBARMERGE (owner ruling 2026-07-24) — M1/M2/M3 merged sidebar entries
# --------------------------------------------------------------------------------------------------
def test_hub_sidebar_merges_one_entry_per_group(tmp_path):
    """SIDEBARMERGE IA PIN (M1/M2/M3). The Metadata sidebar collapses to ONE entry per merged group in
    the owner-ruled order: Core fields (scalars + Organisation + Instruments) / Investigators (Lead +
    Principal) / Identifiers & PIDs (now incl. Time series levels) / Publications / Funding / Access /
    Attribution & rights / Processing / Collection / CARE governance. The retired standalone entries
    (Organisation, Instruments, Lead investigator, Principal investigators, Time series) are GONE as
    their own sidebar/forms; each merged FORM carries every constituent's widgets + o_ snapshots (so one
    submit round-trips them) and the honest serving/levels hints. FAILS RED against the pre-merge hub,
    which showed those as separate sidebar entries and forms."""
    async def _body():
        surveys_live = _merge_client(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get("/gateway/curator/survey/merge-survey-2026?tab=metadata")
            assert r.status_code == 200
            body = r.text
            # The sidebar/TOC is exactly the merged order, one entry per merged group.
            toc = re.findall(r'data-hub-section="[^"]+">([^<]+)', body)
            assert toc == ["Core fields", "Investigators", "Identifiers &amp; PIDs", "Publications",
                           "Funding", "Access", "Attribution &amp; rights", "Processing",
                           "Collection", "CARE governance"], toc
            # No standalone entry/form for a merged-away section.
            forms = re.findall(r'data-hub-section-form="([^"]+)"', body)
            for gone in ("organisation", "instruments", "principal_investigators",
                         "time_series", "related_identifiers"):
                assert gone not in forms, f"{gone} must be folded into a merged form, not standalone"
            # ONE Core fields, ONE Investigators, ONE Identifiers & PIDs sidebar entry.
            assert forms.count("_scalars") == 1 and forms.count("lead_investigator") == 1
            assert forms.count("identifiers") == 1

            def _form(key):
                return body.split(f'data-hub-section-form="{key}"', 1)[1].split("</form>", 1)[0]

            # M3 Core fields: three grouped headings + all three constituents' widgets + o_ snapshots.
            core = _form("_scalars")
            for needle in ("<h2>Core fields</h2>", "<h2>Organisation</h2>", "<h2>Instruments</h2>",
                           'name="f_project_name"', 'name="s_organisation_name"', 'name="o_organisation"',
                           'name="l_instruments_0_manufacturer"', 'name="o_instruments"'):
                assert needle in core, f"Core fields form missing {needle}"

            # M2 Investigators: lead first then principals, both groups' widgets + snapshots + honest hint.
            inv = _form("lead_investigator")
            for needle in ("<h2>Lead investigator</h2>", "<h2>Principal investigators</h2>",
                           'name="s_lead_investigator_name"', 'name="o_lead_investigator"',
                           'name="l_principal_investigators_0_name"', 'name="o_principal_investigators"'):
                assert needle in inv, f"Investigators form missing {needle}"
            assert inv.index("<h2>Lead investigator</h2>") < inv.index("<h2>Principal investigators</h2>")
            assert ("When a lead investigator is set the portal credits the lead; otherwise the "
                    "principal investigators list is credited") in inv

            # M1 Identifiers & PIDs: the folded Time series levels group (d) + its widgets/snapshot/hint.
            ids = _form("identifiers")
            for needle in ("Time series levels available",
                           'name="c_time_series_levels_available_raw_packed"', 'name="o_time_series"',
                           'name="l_related_identifiers_0_identifier"'):
                assert needle in ids, f"Identifiers form missing {needle}"
            assert "Tick which processing levels EXIST in the archives" in ids
            # The folded checkboxes reflect the survey's stored levels.
            assert ('name="c_time_series_levels_available_raw_packed" value="1" style="width:auto" '
                    "checked") in ids
    run(_body())


def test_hub_core_fields_merge_round_trips_scalars_org_instruments(tmp_path):
    """SIDEBARMERGE M3 COMBINED-POST PIN. ONE post of the merged Core fields form round-trips ALL THREE
    constituents — a top-level scalar (project_name), the Organisation map (ror), and a fresh Instruments
    row — because build_section_patch assembles whichever widgets the one form carries. FAILS IF the
    combined post drops any constituent."""
    async def _body():
        surveys_live = _hub_client(tmp_path)  # has organisation + lead; lacks instruments
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            data = {
                "f_project_name": "Hub Survey Renamed",                       # scalar change
                "s_organisation_name": "University of Example",
                "s_organisation_ror": "https://ror.org/03yghzc09",            # organisation map change
                "o_organisation": _canon({"name": "University of Example", "ror": None}),
                "l_instruments_0_manufacturer": "Metronix",                   # fresh instruments row
                "l_instruments_0_model": "ADU-08e",
                "note": "rename + org ror + instrument", "bump": "patch", "csrf_token": csrf,
            }
            r = await client.post("/gateway/curator/edit/hub-survey-2026/preview",
                                  data=data, follow_redirects=False)
            assert r.status_code == 200
            blob = "\n".join(ln for ln in _diff_changed(r.text) if ln.startswith("+"))
            assert "Hub Survey Renamed" in blob, "scalar did not round-trip through the merged post:\n" + blob
            assert "03yghzc09" in blob, "organisation did not round-trip through the merged post:\n" + blob
            assert "Metronix" in blob, "instruments did not round-trip through the merged post:\n" + blob
    run(_body())


def test_hub_investigators_merge_round_trips_lead_and_principals(tmp_path):
    """SIDEBARMERGE M2 COMBINED-POST PIN. ONE post of the merged Investigators form round-trips BOTH the
    Lead investigator map (name) AND a fresh Principal investigators row. FAILS IF the combined post
    drops either group."""
    async def _body():
        surveys_live = _hub_client(tmp_path)  # has lead (Ada); lacks principals
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            data = {
                "s_lead_investigator_name": "Charles Babbage",               # lead map change
                "s_lead_investigator_orcid": "0000-0002-1825-0097",
                "o_lead_investigator": _canon({"name": "Ada Lovelace", "orcid": "0000-0002-1825-0097"}),
                "l_principal_investigators_0_name": "Grace Hopper",           # fresh principal row
                "l_principal_investigators_0_orcid": "0000-0001-2345-6789",
                "note": "swap lead + add principal", "bump": "patch", "csrf_token": csrf,
            }
            r = await client.post("/gateway/curator/edit/hub-survey-2026/preview",
                                  data=data, follow_redirects=False)
            assert r.status_code == 200
            blob = "\n".join(ln for ln in _diff_changed(r.text) if ln.startswith("+"))
            assert "Charles Babbage" in blob, "lead did not round-trip through the merged post:\n" + blob
            assert "Grace Hopper" in blob, "principals did not round-trip through the merged post:\n" + blob
    run(_body())


def test_hub_identifiers_merge_round_trips_time_series(tmp_path):
    """SIDEBARMERGE M1 COMBINED-POST PIN. ONE post of the Identifiers & PIDs form round-trips the
    identifiers map (project_raid), a related_identifiers row, AND the folded time_series levels — three
    sections in one submit. FAILS IF the folded time_series group drops out of the combined post."""
    async def _body():
        surveys_live = _hub_client(tmp_path)  # lacks identifiers/related/time_series
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            data = {
                "s_identifiers_project_raid": "https://raid.org/10.5555/HUBRAID",   # identifiers map
                "l_related_identifiers_0_identifier": "10.25914/hub-newrow",        # related row
                "l_related_identifiers_0_identifier_type": "DOI",
                "l_related_identifiers_0_relation": "IsDerivedFrom",
                "l_related_identifiers_0_custodian": "NCI",
                "c_time_series_levels_available_raw_packed": "1",                   # folded time_series
                "c_time_series_levels_available_level0": "1",
                "note": "record ids + levels", "bump": "patch", "csrf_token": csrf,
            }
            r = await client.post("/gateway/curator/edit/hub-survey-2026/preview",
                                  data=data, follow_redirects=False)
            assert r.status_code == 200
            blob = "\n".join(ln for ln in _diff_changed(r.text) if ln.startswith("+"))
            assert "10.5555/HUBRAID" in blob, "identifiers map dropped from the combined post:\n" + blob
            assert "10.25914/hub-newrow" in blob, "related_identifiers dropped from the combined post:\n" + blob
            assert "raw_packed" in blob and "level0" in blob, \
                "the folded time_series levels dropped from the combined post:\n" + blob
    run(_body())


def test_hub_merged_form_no_clobber_and_legacy_preserved(tmp_path):
    """SIDEBARMERGE NO-CLOBBER + LEGACY-BYTE PIN. Editing ONE constituent of a merged form (Organisation's
    ror) while carrying the OTHER constituent unchanged (the Instruments row, with its o_instruments
    snapshot) touches ONLY organisation: the Instruments row is NOT rewritten, its RETIRED legacy pid is
    byte-preserved (never in the diff), and sibling sections the form does not carry (lead_investigator,
    identifiers, time_series) are untouched. FAILS IF a merged-form edit clobbers a co-constituent or a
    legacy key, or leaks a section the form never carried."""
    async def _body():
        surveys_live = _merge_client(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            # The merged Core fields form carries the Organisation widgets (ror changed) AND the
            # Instruments row UNCHANGED with its snapshot — the retired pid is not a widget; the assembler
            # carries it forward so the row round-trips to a no-op.
            data = {
                "s_organisation_name": "University of Example",
                "s_organisation_ror": "https://ror.org/03yghzc09",           # the ONE change
                "o_organisation": _canon({"name": "University of Example", "ror": None}),
                "l_instruments_0_manufacturer": "Phoenix",                   # instruments unchanged
                "l_instruments_0_model": "MTU-5C",
                "o_instruments": _canon([{"manufacturer": "Phoenix", "model": "MTU-5C",
                                          "pid": "10.99999/LEGACYPID"}]),
                "note": "add org ror only", "bump": "patch", "csrf_token": csrf,
            }
            r = await client.post("/gateway/curator/edit/merge-survey-2026/preview",
                                  data=data, follow_redirects=False)
            assert r.status_code == 200
            assert "03yghzc09" in r.text                                     # the ror change previews
            changed = _diff_changed(r.text)
            # The co-constituent Instruments row (incl. its retired legacy pid) is NOT rewritten.
            for needle in ("LEGACYPID", "Metronix", "MTU-5C", "manufacturer"):
                assert not any(needle in ln for ln in changed), \
                    f"merged-form edit clobbered the co-constituent Instruments ({needle!r}):\n{changed}"
            # Sibling sections the Core fields form never carried stay untouched.
            for needle in ("lead_investigator", "Ada Lovelace", "project_raid", "LEGACYTS",
                           "levels_available", "related_identifiers"):
                assert not any(needle in ln for ln in changed), \
                    f"merged-form edit leaked an uncarried section ({needle!r}):\n{changed}"
    run(_body())


def test_hub_identifiers_edit_preserves_time_series_legacy_key(tmp_path):
    """SIDEBARMERGE M1 LEGACY-BYTE PIN. Editing the identifiers project_raid through the merged
    Identifiers & PIDs form, while the folded time_series levels ride along UNCHANGED (o_time_series
    snapshot carries the retired collection_pid), preserves time_series byte-for-byte: the retired
    collection_pid never appears in the diff. FAILS IF folding time_series into the identifiers form
    rewrites or drops its legacy key on an unrelated identifiers edit."""
    async def _body():
        surveys_live = _merge_client(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            data = {
                "s_identifiers_project_raid": "https://raid.org/10.1234/NEWRAID",   # the ONE change
                "o_identifiers": _canon({"project_raid": "https://raid.org/10.1234/OLDRAID"}),
                # the folded time_series levels ride along UNCHANGED (retired collection_pid carried).
                "c_time_series_levels_available_raw_packed": "1",
                "c_time_series_levels_available_level0": "1",
                "o_time_series": _canon({"levels_available": ["raw_packed", "level0"],
                                         "collection_pid": "10.88888/LEGACYTS"}),
                # the related_identifiers row rides along UNCHANGED.
                "l_related_identifiers_0_identifier": "10.25914/existing-doi",
                "l_related_identifiers_0_identifier_type": "DOI",
                "l_related_identifiers_0_relation": "IsVariantFormOf",
                "l_related_identifiers_0_custodian": "NCI",
                "o_related_identifiers": _canon([{"identifier": "10.25914/existing-doi",
                                                  "identifier_type": "DOI",
                                                  "relation": "IsVariantFormOf", "custodian": "NCI"}]),
                "note": "new raid only", "bump": "patch", "csrf_token": csrf,
            }
            r = await client.post("/gateway/curator/edit/merge-survey-2026/preview",
                                  data=data, follow_redirects=False)
            assert r.status_code == 200
            assert "10.1234/NEWRAID" in r.text                               # the raid change previews
            changed = _diff_changed(r.text)
            for needle in ("LEGACYTS", "collection_pid", "levels_available", "existing-doi"):
                assert not any(needle in ln for ln in changed), \
                    f"identifiers edit clobbered the folded time_series/related legacy data ({needle!r}):\n{changed}"
    run(_body())
