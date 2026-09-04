"""Server-side render pins - the survey hub's mockup styling, driven through the real gateway HTTP surface with the in-process edit
seam. The EXECUTABLE JS pins (clusterWarnings & co, producer-truth build_report) live in
test_c43_hub_js_parity.py; this file pins what the SERVER renders and the JS source invariants.

Load-bearing pins:
  * HEADER - every hub tab renders the mockup's header: survey title + mono slug chip +
    orientation line (v<version> · <licence> · <access> · collection <id>) from the metadata
    read-job fields, with a hidden browser-filled counts span; the tab strip carries the hidden
    Stations chip slot + the slug data attribute. The header DEGRADES to the slug when the
    read-job fails on a non-metadata tab (never a bounce, never a 500).
  * SCAFFOLD: the four-cards / build-id-card-ABSENT and severity-row invariants are pinned at
    JS-source level here (executable form in the parity file). the citation-author
    email heuristic and its three surfaces (the data-citation-email scaffold attribute, the TOC
    issue chip and the Metadata inline field error) are DELETED with the retired flat credit keys
    they read; the pins below assert their absence.
  * SEVERITY CSS - .qa.fail/.qa.warn/.qa.info map to the dark palette's bad/warn/info hues
    (red fail / amber warn / blue info - the mockup's severity semantics).

Failure criterion is in each test's docstring (Invariant 10). Async bodies run under conftest.run.
"""
from __future__ import annotations

import re

from gateway import curatorpage, metaedit
from gateway.tests.conftest import (
    FakeGit, app_client, curator_login, inproc_edit_runner, run,
    write_survey_live,
)

# A survey carrying every orientation-line fact (version/licence/access/collection) + a display
# title, so the header has real fields to render. The citation author is a NAME (the email
# variant is a separate fixture below).
HUB_YAML = """\
schema_version: "0.2"
slug: capr-hub-2026
project_name: Capricorn Hub Fixture
name: "Capricorn Orogen MT (2010)"
version: 1.0.1
region: Western Australia
license: CC-BY-4.0

creators:
  - name: "Lovelace, Ada"
    name_type: person
    orcid: "0000-0002-1825-0097"

access:
  level: open
  contact: data@example.org

collection:
  id: capricorn
  title: Capricorn

publications:
  - author: "Kay, B."
    year: "2026"
    title: "Capricorn MT synthesis"
  - author: "Lovelace, A."
    year: "2025"
    title: "Earlier interpretation"
"""

# The email-author variant is retired with the heuristic that read it. What replaces it
# as the "this survey carries curated MTCAT 2.0 homes" fixture is a survey that actually carries them,
# so the new panels have real values to render.
HUB_YAML_CURATED = HUB_YAML + """
organisations:
  - name: "Geological Survey of South Australia"
    ror: https://ror.org/04y8k6r48
    roles:
      - custodian
    primary_custodian: true
acknowledgements:
  - text: "Data supplied by the Geological Survey of South Australia."
    type: custodian
"""

SLUG = "capr-hub-2026"


def _live(tmp_path, yaml_text=HUB_YAML):
    surveys_live = tmp_path / "surveys-live"
    write_survey_live(surveys_live, slug=SLUG, yaml_text=yaml_text)
    return surveys_live


# --------------------------------------------------------------------------------------------------
# Hub header + tab strip
# --------------------------------------------------------------------------------------------------
def test_hub_header_orientation_line_on_every_tab(tmp_path):
    """HEADER PIN. Every hub tab renders the mockup's header - the survey display TITLE (not the
    slug) + a mono slug chip + the orientation line 'v1.0.1 · CC-BY-4.0 · open · collection
    capricorn' (each fact from the metadata read-job fields, in the mockup's order) + the hidden
    counts span survey-hub.js fills from build_report. The tab strip carries data-survey-slug and
    the hidden Stations chip slot on every tab. FAILS IF a tab loses the header, a served fact is
    missing/reordered, the counts span or chip slot is absent, or the header shows an INVENTED
    fact (a segment whose field the survey does not carry)."""
    async def _body():
        surveys_live = _live(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            for tab in ("", "?tab=stations", "?tab=metadata", "?tab=history"):
                r = await client.get(f"/gateway/curator/survey/{SLUG}{tab}")
                assert r.status_code == 200, (tab, r.status_code)
                # Title + slug chip (the mockup's h1 anatomy).
                assert ("<h1>Capricorn Orogen MT (2010) "
                        f'<span class="slugchip">{SLUG}</span></h1>') in r.text, tab
                # Orientation line: the four facts, in the mockup's order, then the counts span.
                m = re.search(r'<p class="sub" id="hub-orientation">(.*?)</p>', r.text, re.DOTALL)
                assert m, f"{tab}: no orientation line"
                line = m.group(1)
                assert line.index("v1.0.1") < line.index("CC-BY-4.0") < line.index("open") \
                    < line.index("collection"), (tab, line)
                assert "capricorn" in line, (tab, line)
                assert '<span data-hub-counts hidden></span>' in line, (tab, line)
                # Tab strip: slug attribute + the hidden Stations chip slot.
                assert f'data-hub-tabs data-survey-slug="{SLUG}"' in r.text, tab
                assert "data-stations-chip hidden" in r.text, tab
                # survey-hub.js loads ONCE on every tab (header counts + chip are hub-wide).
                assert r.text.count('src="/gateway/curator/survey-hub.js"') == 1, tab
    run(_body())


def test_hub_header_never_invents_missing_facts(tmp_path):
    """NO-INVENTED-FACTS PIN. A survey carrying NO licence/access/collection renders an
    orientation line with only the version — no empty separators, no defaulted 'open', no
    fabricated collection. FAILS IF a missing survey.yaml fact still produces a segment (the
    display layer must never assert what the record does not carry)."""
    async def _body():
        surveys_live = tmp_path / "surveys-live"
        write_survey_live(surveys_live, slug="bare-2026",
                          yaml_text="schema_version: \"0.2\"\nslug: bare-2026\n"
                                    "project_name: Bare\nversion: 2.0.0\n")
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get("/gateway/curator/survey/bare-2026")
            assert r.status_code == 200
            m = re.search(r'<p class="sub" id="hub-orientation">(.*?)</p>', r.text, re.DOTALL)
            assert m
            line = m.group(1)
            assert "v2.0.0" in line
            for invented in ("open", "collection", "CC-BY", " · <span data-hub-counts"):
                assert invented not in line.replace(
                    '<span data-hub-counts hidden></span>', ''), (invented, line)
            # No dangling separators around the (single) segment.
            assert " ·  · " not in line and not line.strip().startswith("·"), line
    run(_body())


def test_hub_header_degrades_when_read_job_fails(tmp_path):
    """DEGRADATION PIN. When the metadata read-job fails on a NON-metadata tab, the hub still
    renders (200): the title falls back to the slug, the orientation line carries no fact
    segments, and the tab's own content is unaffected. FAILS IF the failure bounces the curator
    off the hub (the -HUB metadata-only behaviour) or 500s."""
    async def _body():
        surveys_live = _live(tmp_path)

        def _boom(job):
            raise metaedit.EditRunnerError("runner down")

        async with app_client(tmp_path, git_runner=FakeGit(), edit_runner=_boom,
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get(f"/gateway/curator/survey/{SLUG}")
            assert r.status_code == 200
            assert f'<h1>{SLUG} <span class="slugchip">{SLUG}</span></h1>' in r.text
            assert "v1.0.1" not in r.text          # no facts without the read-job
            assert 'id="qa-cards"' in r.text        # the tab's own scaffold is intact
    run(_body())


# --------------------------------------------------------------------------------------------------
# Overview scaffold + citation-email stamp
# --------------------------------------------------------------------------------------------------
def test_overview_scaffold_never_stamps_a_citation_email(tmp_path):
    """ SCAFFOLD PIN, inverted. The citation-author email heuristic read ONLY the two
    retired flat credit keys, so with those migrated away it could never fire again; it and its
    scaffold attribute are deleted outright. FAILS IF the attribute or the helper comes back."""
    assert not hasattr(curatorpage, "citation_author_email")
    assert not hasattr(curatorpage, "_CITATION_EMAIL_ERROR")

    async def _body():
        surveys_live = _live(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get(f"/gateway/curator/survey/{SLUG}")
            assert "data-citation-email" not in r.text
            assert 'id="qa-cards"' in r.text        # the rest of the scaffold is untouched
    run(_body())


# --------------------------------------------------------------------------------------------------
# JS-source invariants (executable twins live in test_c43_hub_js_parity.py)
# --------------------------------------------------------------------------------------------------
def test_survey_hub_js_four_cards_and_no_build_id_card():
    """FOUR-CARDS SOURCE PIN incl. the build-id-card-ABSENT assertion. SURVEY_HUB_JS builds
    exactly the mockup's four cards (Serving / published, QA flags, Frame, Last build); the
    Stage-1 'Served build' build-id card is REMOVED (that fact lives in the drift chip + serve
    screen), and /data/build.json is not fetched here at all. FAILS IF the build-id card
    or its fetch returns, or a mockup card label disappears."""
    js = curatorpage.SURVEY_HUB_JS
    for label in ("'Serving / published'", "'QA flags'", "'Frame'", "'Last build'"):
        assert label in js, f"missing mockup card {label}"
    assert "Served build" not in js, "the build-id card must stay REMOVED (drift chip owns it)"
    assert "Stations built" not in js, "the Stage-1 card set must not return"
    assert "build.json" not in js, "the overview no longer needs /data/build.json"


def test_survey_hub_js_severity_rows_and_dead_branch_deleted():
    """SEVERITY-ROW + DEAD-BRANCH SOURCE PIN. The needs-attention rows are severity rows
    ('qa ' + kind, with the terse text and the full diagnosis in a title attr) and the refusal
    boilerplate is a single REFUSED_NOTE constant appended once by the plan builder. Both the old
    string-matching metadata branch (citation|author|email/…) and the server-stamped
    data-citation-email info row that replaced it are now DELETED. FAILS IF either
    citation-author branch returns, the note constant multiplies, or the severity-row classes
    disappear."""
    js = curatorpage.SURVEY_HUB_JS
    assert "'qa ' + row.kind" in js, "severity rows must carry the qa fail/warn/info classes"
    assert "setAttribute('title', row.title)" in js, "full diagnosis rides the title attr"
    assert js.count("var REFUSED_NOTE") == 1
    assert js.count("REFUSED_NOTE") == 2, "REFUSED_NOTE: one declaration + ONE plan use (once-only)"
    assert "citation|author|email" not in js, "the dead warning-string matcher must stay deleted"
    assert "data-citation-email" not in js, "the citation-email info row stays out"
    assert "metaInfoText" not in js and "truncEmail" not in js
    # The CSP/XSS discipline extends to the rewritten constant.
    assert ".innerHTML" not in js and "<script" not in js.lower()
    assert not re.search(r"""\bon[a-z]{3,}\s*=\s*['"]""", js)


def test_station_panel_no_raw_json_outside_collapsed_details():
    """GATE SOURCE PIN. The stations panel renders NO raw JSON
    outside a collapsed <details>: the ONLY <pre> in STATIONS_JS is the collapsed 'raw
    station.json' dump; the old visible 'Conditioning / QA notes' and 'Coordinate QC' pre blocks
    are gone; conditioning and coordinate QC render as ONE terse dl line each
    (conditioningLine / coordQcLine over served station.json values). FAILS IF a visible pre
    returns, the terse lines unwire, or the collapsed dump disappears."""
    js = curatorpage.STATIONS_JS
    assert js.count("el('pre')") == 1, (
        "exactly ONE pre - the collapsed raw station.json dump - is allowed in the panel")
    assert "el('summary', 'raw station.json')" in js
    assert "'Conditioning / QA notes'" not in js, "the visible conditioning JSON block must stay gone"
    assert "el('h2', 'Coordinate QC')" not in js, "the visible coordinate-QC JSON block must stay gone"
    assert "function conditioningLine(" in js
    assert "conditioningLine(station.canonical_conditioning)" in js, "terse conditioning line wired"
    assert "function coordQcLine(" in js
    assert "coordQcLine(station.coordinate_qc)" in js, "terse coordinate-QC line wired"


# --------------------------------------------------------------------------------------------------
# Metadata TOC state hints + the inline citation-email field error (display-layer only)
# --------------------------------------------------------------------------------------------------
def test_metadata_toc_state_hints(tmp_path):
    """TOC-HINT PIN. The Metadata TOC entries carry render-time state hints: entry COUNTS on
    non-empty list sections (publications: 2, organisations: 1, acknowledgements: 1) and the access
    level / collection id values. There is no '1 issue' chip, because the only
    thing that ever produced one was the deleted citation-email heuristic. FAILS IF a hint is
    invented for an empty section, a count drifts from the survey's own entries, or the retired
    issue chip returns."""
    async def _body():
        surveys_live = _live(tmp_path, yaml_text=HUB_YAML_CURATED)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get(f"/gateway/curator/survey/{SLUG}?tab=metadata")
            assert r.status_code == 200
            toc = re.search(r'<nav class="toc"[^>]*>(.*?)</nav>', r.text, re.DOTALL).group(1)
            assert '<span class="state issue">' not in toc, "the citation-email issue chip is retired"
            assert ('data-hub-section="publications">Publications'
                    '<span class="state">2</span>') in toc
            assert ('data-hub-section="organisations">Organisations &amp; roles'
                    '<span class="state">1</span>') in toc
            assert ('data-hub-section="acknowledgements">Required acknowledgements'
                    '<span class="state">1</span>') in toc
            assert ('data-hub-section="access">Access'
                    '<span class="state">open</span>') in toc
            assert ('data-hub-section="collection">Collection'
                    '<span class="state">capricorn</span>') in toc
            # Empty list sections carry NO hint (never a 0 placeholder).
            assert re.search(r'data-hub-section="funding">Funding</a>', toc), toc
    run(_body())


def test_metadata_tab_renders_the_curated_home_panels(tmp_path):
    """PANEL PIN. The Metadata tab renders the three curated homes plus the designation
    mapping, prefilled from the survey's own values: the organisations role checkbox group with the
    stored custodian ticked and its primary-custodian radio selected, the citation preferred-text and
    nested preferred-identifier inputs, the acknowledgement wording, and the identity_classification
    case select with both designation row groups. FAILS IF a curator cannot edit a key the public
    form and the migration can write (the no-raw-JSON-escape rule)."""
    async def _body():
        surveys_live = _live(tmp_path, yaml_text=HUB_YAML_CURATED)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get(f"/gateway/curator/survey/{SLUG}?tab=metadata")
            body = r.text
            orgs = body.split('data-hub-section-form="organisations"', 1)[1].split("</section>", 1)[0]
            assert 'value="Geological Survey of South Australia"' in orgs
            assert 'name="c_organisations_0_custodian" value="1" style="width:auto" checked' in orgs
            assert 'name="c_organisations_primary" value="0" style="width:auto" checked' in orgs
            cit = body.split('data-hub-section-form="citation"', 1)[1].split("</section>", 1)[0]
            assert 'name="s_citation_preferred_text"' in cit
            assert 'name="s_citation_text_source"' in cit
            assert 'name="s_citation_preferred_identifier_scheme"' in cit
            assert 'name="s_citation_preferred_identifier_identifier"' in cit
            idc = body.split('data-hub-section-form="identity_classification"', 1)[1] \
                      .split("</section>", 1)[0]
            assert 'name="s_identity_classification_case"' in idc
            assert 'name="l_identity_classification_represents_0_scheme"' in idc
            assert 'name="l_identity_classification_own_identifiers_0_identifier"' in idc
            acks = body.split('data-hub-section-form="acknowledgements"', 1)[1] \
                       .split("</section>", 1)[0]
            assert 'value="Data supplied by the Geological Survey of South Australia."' in acks
            assert 'name="l_acknowledgements_0_type"' in acks
    run(_body())


# --------------------------------------------------------------------------------------------------
# History density polish (the mockup's merged 'When · by' column)
# --------------------------------------------------------------------------------------------------
def test_history_when_by_merged_column(tmp_path):
    """DENSITY PIN. The History table merges When and Author into the mockup's single
    'When · by' column ('<date> · <author>', values verbatim from the history read-job); the
    separate Author column is gone; behaviour (read-only real git log) is unchanged. FAILS IF
    the columns split again or the author drops out of the merged cell."""
    import subprocess

    async def _body():
        surveys_live = _live(tmp_path)

        def git(*a):
            subprocess.run(["git", "-C", str(surveys_live), *a], check=True,
                           capture_output=True, text=True)

        git("init", "-q")
        git("config", "user.email", "curator@ausmt.local")
        git("config", "user.name", "AusMT Gateway")
        git("add", "-A")
        git("commit", "-qm", "initial import of capr-hub-2026")
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get(f"/gateway/curator/survey/{SLUG}?tab=history")
            assert r.status_code == 200
            assert "<th>When · by</th>" in r.text
            assert "<th>Author</th>" not in r.text and "<th>When</th>" not in r.text
            assert re.search(r'<td class="k dt">[^<]+ · AusMT Gateway</td>', r.text), \
                "the merged cell must carry '<date> · <author>'"
    run(_body())


def test_severity_css_maps_to_dark_palette_hues(tmp_path):
    """SEVERITY-COLOUR PIN (render half). The rendered hub page's CSS maps the severity classes to
    the dark palette's hues — .qa.fail -> bad (red), .qa.warn -> warn (amber), .qa.info -> info
    (blue) — the mockup's severity semantics without repainting the theme. FAILS IF a severity
    class loses its hue or the info hue is dropped from the palette."""
    async def _body():
        surveys_live = _live(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get(f"/gateway/curator/survey/{SLUG}")
            css = r.text
            p = curatorpage._PALETTE  # noqa: SLF001
            assert f'.qa.fail{{border-left-color:{p["bad"]}}}' in css
            assert f'.qa.warn{{border-left-color:{p["warn"]}}}' in css
            assert f'.qa.info{{border-left-color:{p["info"]}}}' in css
    run(_body())
