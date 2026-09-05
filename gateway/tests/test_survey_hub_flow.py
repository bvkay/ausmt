"""Stage 1 survey-hub + nav-shell flow tests (verification pins), driven through the
real gateway HTTP surface with the in-process edit seam.

Load-bearing pins here:
  * CSP SWEEP (rendered): every surface - the nav shell, the survey hub (both tabs), and the
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


# SIDEBARMERGE: a survey carrying EVERY merged-away section (organisation +
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


def _section_html(body: str, key: str) -> str:
    """The rendered HTML of ONE hub Metadata section block. HUB-SINGLE-SAVE: the sections
    are <section> blocks inside ONE form, so a block ends at </section>, never at </form>.
    Splitting on the wrong terminator would swallow every following section and quietly hollow out the
    per-section assertions built on this helper."""
    assert f'data-hub-section-form="{key}"' in body, f"no section block for {key!r}"
    return body.split(f'data-hub-section-form="{key}"', 1)[1].split("</section>", 1)[0]


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
# CSP SWEEP (rendered) - every surface
# --------------------------------------------------------------------------------------------------
def test_c43_surfaces_are_csp_clean(tmp_path):
    """RENDERED CSP sweep of every Stage-1 surface: the surveys list (nav shell), the survey hub
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
    """The external JS routes redirect an ANONYMOUS request to login (303) - same gate as the
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
# NAV SHELL presence
# --------------------------------------------------------------------------------------------------
def test_nav_shell_rail_and_drift_chip_on_every_page(tmp_path):
    """Every session-gated curator page renders the left rail (the Stage-1 surfaces PLUS the Stage-3a
    Collections entry) and the context bar's drift chip carrying the server-rendered
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
                # Serve state: promoted the panel to a first-class screen, so the rail
                # now points at /gateway/curator/serve (was the queue's #serve-state anchor).
                assert 'href="/gateway/curator/serve"' in r.text           # Serve state
                # Collections joined the rail in Stage 3a - present on every page (not
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
# SURVEY HUB
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
    """SURVEYS-TABLE PIN. The Surveys list is a proper TABLE (not a bare link list): a row
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
    303 to login), like the other external scripts. FAILS IF it 404s, serves HTML, or is
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
    """The Overview & QA tab renders the QA scaffold (browser-populated from /data). Stage 2a: the
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
    """the HUB Metadata tab (the sidebar editor the curator actually uses) renders
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
            form_html = _section_html(body, "identifiers")
            assert 'name="s_identifiers_project_raid"' in form_html
            assert "10.1234/OLDRAID" in form_html                                # existing map value prefilled
            assert 'name="l_related_identifiers_0_identifier"' in form_html
            assert "10.25914/existing-doi" in form_html                          # existing typed row prefilled
            assert 'name="o_identifiers"' in form_html and 'name="o_related_identifiers"' in form_html
            # Plain-language guidance is present in the panel.
            assert "Where does it go?" in form_html
            assert "Derived from (this data was processed from it)" in form_html  # human relation label
            assert 'value="IsDerivedFrom"' in form_html                          # exact vocab still POSTed
            assert ">Related identifiers</h2>" not in body                       # no duplicate list panel
    run(_body())


def test_hub_consolidated_section_round_trips_both_groups(tmp_path):
    """a SINGLE post of the consolidated 'Identifiers & PIDs' hub section round-trips BOTH the
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


def test_hub_metadata_tab_single_form_all_sections(tmp_path):
    """HUB-SINGLE-SAVE STRUCTURE PIN. The Metadata tab renders a section TOC + ONE form
    carrying EVERY section as a <section> block + ONE commit tray. FAILS IF the tab reverts to a form
    per section (that is exactly what cost the curator a merge job / version bump / preview / confirm
    per section), or drops the TOC / the single tray. RED against the pre-change hub, which rendered
    N forms and N trays."""
    async def _body():
        surveys_live = _hub_client(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get("/gateway/curator/survey/hub-survey-2026?tab=metadata")
            assert r.status_code == 200
            sections = re.findall(r'data-hub-section-form="([^"]+)"', r.text)
            # Scalars + each (possibly merged) sidebar section is its own BLOCK. SIDEBARMERGE:
            # organisation and instruments are folded into the "Core fields" (_scalars) block and are
            # NOT standalone; the contributor-credit model: the unified People & credit block is "people".
            assert "_scalars" in sections and "people" in sections
            assert "organisation" not in sections, \
                "organisation must be folded into the merged Core fields block, not a standalone one"
            assert "lead_investigator" not in sections and "creators" not in sections, \
                "the retired investigator/creator panels must be folded into the People & credit block"
            assert len(sections) >= 6, sections
            assert 'class="toc"' in r.text                       # sticky section TOC
            # ONE form, ONE action, ONE tray, ONE required release note, ONE bump radio group — the
            # whole point: every section is saved together as a single edit.
            assert r.text.count('action="/gateway/curator/edit/hub-survey-2026/preview"') == 1, \
                "the Metadata tab must post every section through ONE form"
            assert r.text.count('id="hub-metadata-form"') == 1
            assert r.text.count('id="hub-commit-tray"') == 1
            assert r.text.count('name="note"') == 1 and r.text.count('value="patch"') == 1
            assert "Every section is saved together as ONE edit" in r.text   # commit-tray copy
            assert "Only this section is submitted" not in r.text            # the retired promise
            # Each section block is a <section>, not a <form> — no nested/sibling form can smuggle a
            # second save button back in.
            for key in sections:
                assert f'<section class="hub-section" id="sec-{key}"' in r.text, key
            # The TOC entries are ordinary in-page anchors (they work with no JS at all).
            for key in sections:
                assert f'href="#sec-{key}" data-hub-section="{key}"' in r.text, key
    run(_body())


def test_hub_enter_key_defaults_to_an_unnamed_save(tmp_path):
    """IMPLICIT-SUBMISSION PIN. A form's default button - the one Enter in a text field
    activates, is the FIRST submit button in tree order. With every section folded into ONE form, any
    NAMED submit anywhere on the tab would become that default and Enter in a text field would post an
    extra field nobody asked for. (The retired legacy Convert action was exactly such a button; it was
    deleted, and this guard stays because the hazard is structural.) An unnamed submit must come
    first, so Enter is a plain Save. FAILS IF the first submit inside the metadata form carries a name,
    or if the guard is missing / focusable."""
    async def _body():
        surveys_live = _hub_client(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            body = (await client.get("/gateway/curator/survey/hub-survey-2026?tab=metadata")).text
            # No named submit is rendered anywhere on the tab any more.
            assert "people_convert" not in body
            form = _one_form_html(body)
            first = re.search(r'<button[^>]*type="submit"[^>]*>', form)
            assert first, "no submit button in the metadata form"
            assert "name=" not in first.group(0), \
                f"the form's default button is a NAMED action: {first.group(0)}"
            assert 'tabindex="-1"' in first.group(0) and 'aria-hidden="true"' in first.group(0), \
                "the default-submit guard must stay out of the tab order and the a11y tree"
            # It is off-screen, NOT display:none (display:none is skipped for implicit submission in
            # some engines, which would hand the default straight back to Convert).
            assert "display:none" not in first.group(0), first.group(0)
    run(_body())


def test_hub_per_section_submit_is_section_scoped(tmp_path):
    """SECTION-SCOPED PATCH PIN (flow). Submit ONLY the organisation section's widgets (name unchanged,
    ror set) and the preview diff changes organisation WITHOUT rewriting the untouched
    lead_investigator section. HUB-SINGLE-SAVE: still the load-bearing pin under the one
    combined form — a save now carries every section, and the no-clobber promise rests entirely on
    assemble_section returning _OMIT for a section that round-trips to its o_<section> snapshot.
    FAILS IF a submit leaks a section the curator did not touch into the patch/diff."""
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
# SIDEBARMERGE - merged sidebar entries
# --------------------------------------------------------------------------------------------------
def test_hub_sidebar_merges_one_entry_per_group(tmp_path):
    """SIDEBARMERGE IA PIN. The Metadata sidebar collapses to ONE entry per merged group in
    the settled order: Core fields (scalars + Organisation + Instruments) / Investigators (Lead +
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
            # The sidebar/TOC is exactly the merged order, one entry per merged group: the four
            # investigator/creator/contributor panels collapse to ONE "People & credit" entry.
            toc = re.findall(r'data-hub-section="[^"]+">([^<]+)', body)
            assert toc == ["Core fields", "People &amp; credit", "Organisations &amp; roles",
                           "Identifiers &amp; PIDs", "Citation", "Identity &amp; designation",
                           "Required acknowledgements",
                           "Publications", "Funding", "Access", "Attribution &amp; rights",
                           "Processing", "Collection", "CARE governance"], toc
            # No standalone entry/form for a merged-away or retired section.
            forms = re.findall(r'data-hub-section-form="([^"]+)"', body)
            for gone in ("organisation", "instruments", "lead_investigator", "principal_investigators",
                         "creators", "contributors", "time_series", "related_identifiers"):
                assert gone not in forms, f"{gone} must be folded into a merged form, not standalone"
            # ONE Core fields, ONE People & credit, ONE Identifiers & PIDs sidebar entry.
            assert forms.count("_scalars") == 1 and forms.count("people") == 1
            assert forms.count("identifiers") == 1

            def _form(key):
                return _section_html(body, key)

            # Core fields: three grouped headings + all three constituents' widgets + o_ snapshots.
            core = _form("_scalars")
            for needle in ("<h2>Core fields</h2>", "<h2>Organisation</h2>", "<h2>Instruments</h2>",
                           'name="f_project_name"', 'name="s_organisation_name"', 'name="o_organisation"',
                           'name="l_instruments_0_manufacturer"', 'name="o_instruments"'):
                assert needle in core, f"Core fields form missing {needle}"

            # People & credit: ONE panel of unified rows + the widgets and the short
            # credit explainer (NOT the retired precedence sentence). (The o_creators/o_contributors
            # round-trip anchors render only when the survey CARRIES those lists; this survey has
            # neither, so their absence is correct - it keeps an empty panel absent -> _OMIT.)
            people = _form("people")
            for needle in ('<h2>People &amp; credit</h2>', 'data-editor-rows="people"',
                           'name="l_people_0_name"', "data-people-nametype", 'name="l_people_0_cited"',
                           'name="l_people_0_role_ProjectLeader"', "Cited authors form the citation"):
                assert needle in people, f"People & credit form missing {needle}"
            assert ("When a lead investigator is set the portal credits the lead") not in people
            # The legacy Convert notices are GONE. The survey still carries both retired flat
            # keys on disk; the editor models them with NOTHING, so they are never shown and never
            # patched (byte-preserved as unmodelled keys).
            assert "people_convert" not in people
            assert "Ada Lovelace" not in people and "Grace Hopper" not in people
            # ONE advanced-JSON escape per underlying list.
            assert 'name="j_creators"' in people and 'name="j_contributors"' in people

            # Identifiers & PIDs: the folded Time series levels group (d) + its widgets/snapshot/hint.
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
    """SIDEBARMERGE COMBINED-POST PIN. ONE post of the merged Core fields form round-trips ALL THREE
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


def test_hub_curated_homes_merge_round_trips_in_one_post(tmp_path):
    """COMBINED-POST PIN, replacing the retired Investigators pin. ONE post of the metadata form
    round-trips the citation map (preferred text + the nested preferred-identifier pair), the
    identity_classification designation mapping, an organisations row with its role checkbox group and
    its primary-custodian radio, AND an acknowledgements row. FAILS IF any of the four new panels drops
    out of the combined post, or the non-scalar organisations controls do not assemble."""
    async def _body():
        surveys_live = _hub_client(tmp_path)  # carries none of the curated homes
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            data = {
                "s_citation_preferred_text": "GSSA (2016). AusLAMP South Australia.",
                "s_citation_text_source": "source_provided",
                "s_citation_preferred_identifier_scheme": "DOI",
                "s_citation_preferred_identifier_identifier": "10.25914/hubdoi",
                "s_identity_classification_case": "case_b",
                "l_identity_classification_own_identifiers_0_scheme": "DOI",
                "l_identity_classification_own_identifiers_0_identifier": "10.25914/hubdoi",
                "l_organisations_0_name": "Geological Survey of South Australia",
                "l_organisations_0_ror": "https://ror.org/04y8k6r48",
                "c_organisations_0_custodian": "1",
                "c_organisations_0_publisher": "1",
                "c_organisations_primary": "0",
                "l_acknowledgements_0_text": "Data supplied by the GSSA.",
                "l_acknowledgements_0_type": "custodian",
                "note": "curate the citation homes", "bump": "patch", "csrf_token": csrf,
            }
            r = await client.post("/gateway/curator/edit/hub-survey-2026/preview",
                                  data=data, follow_redirects=False)
            assert r.status_code == 200
            blob = "\n".join(ln for ln in _diff_changed(r.text) if ln.startswith("+"))
            for needle in ("GSSA (2016). AusLAMP South Australia.", "text_source: source_provided",
                           "preferred_identifier:", "10.25914/hubdoi", "case: case_b",
                           "own_identifiers:", "Geological Survey of South Australia",
                           "publisher", "custodian", "primary_custodian: true",
                           "Data supplied by the GSSA."):
                assert needle in blob, f"{needle!r} did not round-trip through the merged post:\n{blob}"
            # The retired flat credit key the fixture still carries is untouched by the save.
            assert "lead_investigator" not in blob, blob
    run(_body())


def test_hub_identifiers_merge_round_trips_time_series(tmp_path):
    """SIDEBARMERGE COMBINED-POST PIN. ONE post of the Identifiers & PIDs form round-trips the
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
    """SIDEBARMERGE LEGACY-BYTE PIN. Editing the identifiers project_raid through the merged
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


# --------------------------------------------------------------------------------------------------
# HUB-SINGLE-SAVE - one save across every section; the JS-hidden spare rows
# --------------------------------------------------------------------------------------------------
def _hub_form_fields(body: str) -> dict:
    """The exact name/value pairs a browser would submit for the hub's ONE metadata form. Isolated by
    id="hub-metadata-form" (NOT "the first form on the page" — the nav shell's context bar renders a
    Request-rebuild form above it). Reuses the full-form harvester's parsing on the isolated slice."""
    from gateway.tests.test_editor_form_flow import _harvest_form_fields
    start = body.index('<form id="hub-metadata-form"')
    end = body.index("</form>", start)
    # _harvest_form_fields isolates on '<form method="post"' — hand it a slice already shaped that way.
    return _harvest_form_fields('<form method="post"' + body[start:end] + "</form>")


def _one_form_html(body: str) -> str:
    start = body.index('<form id="hub-metadata-form"')
    return body[start:body.index("</form>", start)]


def test_hub_single_save_spans_two_sections_in_one_merge_job(tmp_path):
    """HUB-SINGLE-SAVE COMBINED-SAVE PIN. The curator edits TWO sidebar sections - Core
    fields (a top-level scalar) and Access (the access map) — and clicks Save ONCE. The whole hub form
    is submitted as a browser would submit it, producing exactly ONE merge job whose patch carries BOTH
    sections and exactly ONE version bump (1.0.0 -> 1.0.1).

    NON-VACUITY — what the OLD per-section hub could not satisfy:
      * the page must contain exactly ONE form posting to the preview route (the old hub rendered one
        form per section, ten of them, each with its own action);
      * BOTH sections' widgets must live inside that ONE form (in the old hub the scalar and access
        widgets were in DIFFERENT forms — no browser submit could ever have carried both);
      * exactly ONE merge job for the whole edit (the old flow needed two saves = two merge jobs = two
        bumps, 1.0.1 then 1.0.2 = two release notes, two previews, two confirms).
    FAILS IF the tab regresses to per-section forms, if either section drops out of the combined patch,
    or if one save produces more than one merge job / more than one version bump."""
    async def _body():
        surveys_live = _hub_client(tmp_path)
        seam = inproc_edit_runner(surveys_live)
        merge_jobs: list[dict] = []

        def counting_seam(job: dict) -> dict:
            if job.get("kind") == "merge":
                merge_jobs.append(job)
            return seam(job)

        async with app_client(tmp_path, git_runner=FakeGit(), edit_runner=counting_seam,
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            body = (await client.get("/gateway/curator/survey/hub-survey-2026?tab=metadata")).text

            # (1) ONE form for the whole tab.
            assert body.count('action="/gateway/curator/edit/hub-survey-2026/preview"') == 1, \
                "the Metadata tab must render exactly ONE form posting to the preview route"

            # (2) BOTH sections' widgets are inside that ONE form — the structural fact the per-section
            #     hub could not provide.
            one_form = _one_form_html(body)
            assert 'name="f_project_name"' in one_form, "Core fields widgets are not in the one form"
            assert 'name="s_access_level"' in one_form, "Access widgets are not in the one form"

            # (3) submit the WHOLE form, as the browser does, with a change in EACH section.
            fields = _hub_form_fields(body)
            assert "f_project_name" in fields and "s_access_level" in fields, sorted(fields)
            fields["f_project_name"] = "Hub Survey Renamed"        # section A: Core fields
            fields["s_access_level"] = "embargoed"                 # section B: Access
            fields["note"] = "rename + embargo in one edit"
            fields["bump"] = "patch"
            fields["csrf_token"] = csrf
            r = await client.post("/gateway/curator/edit/hub-survey-2026/preview",
                                  data=fields, follow_redirects=False)
            assert r.status_code == 200, r.text[:800]

            # ONE merge job for the whole two-section edit.
            assert len(merge_jobs) == 1, \
                f"one Save must enqueue ONE merge job, got {len(merge_jobs)}"
            patch = merge_jobs[0].get("patch") or {}
            assert "access" in patch, f"section B (access) missing from the combined patch: {patch}"
            assert patch["access"].get("level") == "embargoed", patch["access"]
            assert patch.get("project_name") == "Hub Survey Renamed", \
                f"section A (project_name) missing from the combined patch: {patch}"

            # ONE version bump for the whole edit (not one per section).
            assert "new version 1.0.1" in r.text, r.text[:800]
            assert "1.0.2" not in r.text
            blob = "\n".join(ln for ln in _diff_changed(r.text) if ln.startswith("+"))
            assert "Hub Survey Renamed" in blob, "section A missing from the one diff:\n" + blob
            assert "embargoed" in blob, "section B missing from the one diff:\n" + blob
    run(_body())


def test_hub_spare_rows_carry_the_marker_and_editor_js_hides_them(tmp_path):
    """SPARE-ROW MARKER PIN. The server still renders the no-JS spare blank rows (a
    deliberate degradation invariant) but stamps them data-spare-row="1", and editor.js hides exactly
    those on init. The rows a curator actually has — and the template editor.js clones for +Add — must
    NOT carry the marker, or a real row (or every JS-added row) would render invisible.

    NON-VACUITY: the pre-change renderer emitted NO data-spare-row attribute anywhere and editor.js had
    no hide step, so every assertion below is red against it. FAILS IF the marker is dropped (the blank
    panels come back), stamped on a populated or template row, or if editor.js stops hiding them."""
    from gateway import curatorpage as _cp

    async def _body():
        surveys_live = _merge_client(tmp_path)   # carries a populated instruments row
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            body = (await client.get("/gateway/curator/survey/merge-survey-2026?tab=metadata")).text
            core = _section_html(body, "_scalars")
            # Count the LIVE rows only — the <template> row editor.js clones for +Add lives in the same
            # block and is asserted separately below.
            live = re.sub(r"<template\b.*?</template>", "", core, flags=re.S)
            rows = re.findall(r'<div class="editor-row" data-editor-row([^>]*)>', live)
            # instruments: 1 populated row + _SPARE_BLANK_ROWS spare ones.
            marked = [a for a in rows if 'data-spare-row="1"' in a]
            assert len(marked) == _cp._SPARE_BLANK_ROWS, \
                f"expected {_cp._SPARE_BLANK_ROWS} marked spare rows, got {len(marked)} of {rows}"
            assert len(rows) - len(marked) == 1, \
                "the survey's ONE populated instruments row must NOT be marked spare"
            # The populated row (the one carrying the stored value) is unmarked.
            populated = core.split("Phoenix", 1)[0].rsplit('<div class="editor-row"', 1)[-1]
            assert "data-spare-row" not in populated, populated[:200]
            # The template editor.js clones for +Add is never marked — a cloned row must be visible.
            tpl = body.split('<template data-editor-template="instruments">', 1)[1].split(
                "</template>", 1)[0]
            assert "data-spare-row" not in tpl, "the +Add template row must not be marked spare"
            # Every repeatable section renders marked spares (five sections x two blank panels was the
            # complaint), including the People & credit and related_identifiers custom row builders.
            for key, needle in (("people", 'name="l_people_'),
                                ("identifiers", 'name="l_related_identifiers_'),
                                ("publications", 'name="l_publications_'),
                                ("funding", 'name="l_funding_')):
                block = _section_html(body, key)
                assert 'data-spare-row="1"' in block, f"{key} lost its spare-row markers"
                assert needle in block, key
            # editor.js hides exactly the marked rows on init.
            js = (await client.get("/gateway/curator/editor.js")).text
            assert "[data-editor-row][data-spare-row]" in js, \
                "editor.js must hide the marked spare rows on init"
            assert "row.style.display = 'none'" in js
    run(_body())


def test_hub_combined_save_field_error_keeps_other_sections_values(tmp_path):
    """COMBINED-SAVE ERROR PIN. A per-field parse failure in section B (a malformed ORCID
    in People & credit) re-renders the HUB Metadata tab with the error beside its owning section AND
    section A's typed-but-unsaved values intact — nothing the curator entered anywhere in the one form
    is discarded, and they stay on the tab they were editing.

    NON-VACUITY: the pre-change handler bounced EVERY failed save to the standalone full form
    (render_edit_form) — a different page with no hub tab strip and no section blocks — so the
    'lands back on the hub' assertions are red against it; and with a form per section there was no
    such thing as 'section A's values' surviving a section B failure, because the two could not be
    submitted together. FAILS IF the error re-render leaves the hub, loses a typed value from a
    section other than the failing one, or drops the per-section error annotation."""
    async def _body():
        surveys_live = _hub_client(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            body = (await client.get("/gateway/curator/survey/hub-survey-2026?tab=metadata")).text
            fields = _hub_form_fields(body)
            fields["f_project_name"] = "Kept Across The Failure"      # section A: a good edit
            fields["s_access_level"] = "embargoed"                    # section A': another good edit
            fields["l_people_0_name"] = "Ada Lovelace"                # section B: the failing row
            fields["l_people_0_name_type"] = "person"
            fields["l_people_0_orcid"] = "not-an-orcid"               # the parse failure
            fields["note"] = "should not commit"
            fields["bump"] = "patch"
            fields["csrf_token"] = csrf
            r = await client.post("/gateway/curator/edit/hub-survey-2026/preview",
                                  data=fields, follow_redirects=False)
            assert r.status_code == 200
            out = r.text
            # Nothing previewed/committed.
            assert "new version" not in out, "a failed parse must not reach the preview"
            # We are back on the HUB Metadata tab (not the standalone full form).
            assert 'id="hub-metadata-form"' in out and 'data-hub-section-form="people"' in out
            assert "?tab=history" in out, "the hub tab strip is missing - this is not the hub"
            assert "<h1>Edit metadata" not in out, "bounced to the standalone full form"
            # The error is annotated on its OWNING section (the _section_error_html list), and the
            # offending value is preserved there so the curator can see and fix what they typed.
            people = _section_html(out, "people")
            assert "not-an-orcid" in people, "the curator's own bad value was discarded"
            assert "is not a valid ORCID" in people, \
                "the per-field ORCID error is not rendered on its owning section"
            # ...and NOT smeared over a section that did not fail.
            assert "is not a valid ORCID" not in _section_html(out, "_scalars")
            # Section A's typed values survived the section-B failure.
            core = _section_html(out, "_scalars")
            assert 'value="Kept Across The Failure"' in core, \
                "section A's typed value was discarded by a section B failure"
            access = _section_html(out, "access")
            assert re.search(r'<option value="embargoed"[^>]*\bselected', access) or \
                re.search(r'\bselected[^>]*value="embargoed"', access), \
                "section A's access edit was discarded by a section B failure"
            # The error round-trip must NOT convert the hidden spare rows into visible empty ones (and
            # then append two more behind them) — the panels would fill with blanks on every retry.
            # Every rebuilt row that carries nothing is re-marked spare, so only the row the curator
            # actually typed into stays unmarked.
            live = re.sub(r"<template\b.*?</template>", "", people, flags=re.S)
            rows = re.findall(r'<div class="editor-row" data-editor-row([^>]*)>', live)
            unmarked = [a for a in rows if "data-spare-row" not in a]
            assert len(unmarked) == 1, \
                f"expected only the typed people row to be visible, got {len(unmarked)} of {len(rows)}"
    run(_body())
