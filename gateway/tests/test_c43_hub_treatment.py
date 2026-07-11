"""C43-HUB server-side render pins — the survey hub's mockup treatment (contract C43-HUB,
owner rulings 2026-07-11), driven through the real gateway HTTP surface with the in-process edit
seam. The EXECUTABLE JS pins (clusterWarnings & co, producer-truth build_report) live in
test_c43_hub_js_parity.py; this file pins what the SERVER renders and the JS source invariants.

Load-bearing pins:
  * H1 HEADER — every hub tab renders the mockup's header: survey title + mono slug chip +
    orientation line (v<version> · <licence> · <access> · collection <id>) from the metadata
    read-job fields, with a hidden browser-filled counts span; the tab strip carries the hidden
    Stations chip slot + the slug data attribute. The header DEGRADES to the slug when the
    read-job fails on a non-metadata tab (never a bounce, never a 500).
  * H2 SCAFFOLD — the Overview scaffold stamps data-citation-email ONLY when the Q3-ruled
    server-side heuristic fires on the read-job fields (the same helper the Metadata tab uses);
    the four-cards / build-id-card-ABSENT and severity-row invariants are pinned at JS-source
    level here (executable form in the parity file).
  * SEVERITY CSS — .qa.fail/.qa.warn/.qa.info map to the dark palette's bad/warn/info hues
    (red fail / amber warn / blue info — the mockup's severity semantics).

Failure criterion is in each test's docstring (Invariant 10). Async bodies run under conftest.run().
"""
from __future__ import annotations

import re

from gateway import curatorpage, metaedit
from gateway.tests.conftest import (
    FakeGit, app_client, curator_login, inproc_edit_runner, run, write_survey_live,
)

# A survey carrying every orientation-line fact (version/licence/access/collection) + a display
# title, so the H1 header has real fields to render. The citation author is a NAME (the email
# variant is a separate fixture below).
HUB_YAML = """\
schema_version: "0.2"
slug: capr-hub-2026
project_name: Capricorn Hub Fixture
name: "Capricorn Orogen MT (2010)"
version: 1.0.1
region: Western Australia
license: CC-BY-4.0

lead_investigator:
  name: Ada Lovelace
  orcid: "0000-0002-1825-0097"

access:
  level: open
  contact: data@example.org

collection:
  id: capricorn
  title: Capricorn
"""

# The same survey with the mockup's own H4 defect: the citation author is an email address.
HUB_YAML_EMAIL_AUTHOR = HUB_YAML.replace("name: Ada Lovelace",
                                         "name: graham.heinson@adelaide.edu.au")

SLUG = "capr-hub-2026"


def _live(tmp_path, yaml_text=HUB_YAML):
    surveys_live = tmp_path / "surveys-live"
    write_survey_live(surveys_live, slug=SLUG, yaml_text=yaml_text)
    return surveys_live


# --------------------------------------------------------------------------------------------------
# H1 — hub header + tab strip
# --------------------------------------------------------------------------------------------------
def test_hub_header_orientation_line_on_every_tab(tmp_path):
    """H1 HEADER PIN. Every hub tab renders the mockup's header — the survey display TITLE (not the
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
    """H1 NO-INVENTED-FACTS PIN. A survey carrying NO licence/access/collection renders an
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
    """H1 DEGRADATION PIN. When the metadata read-job fails on a NON-metadata tab, the hub still
    renders (200): the title falls back to the slug, the orientation line carries no fact
    segments, and the tab's own content is unaffected. FAILS IF the failure bounces the curator
    off the hub (the pre-C43-HUB metadata-only behaviour) or 500s."""
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
# H2 — overview scaffold + citation-email stamp (Q3 ruling)
# --------------------------------------------------------------------------------------------------
def test_overview_scaffold_stamps_citation_email_only_when_heuristic_fires(tmp_path):
    """Q3 SINGLE-SOURCE PIN (scaffold half). The Overview scaffold carries data-citation-email
    ONLY when the server-side heuristic (citation_author_email — the SAME helper the Metadata tab
    uses) flags the citation author; a normal name stamps nothing. FAILS IF the attribute appears
    for a name, is missing for an email author, or carries a different value than the field."""
    async def _body():
        live_email = _live(tmp_path, yaml_text=HUB_YAML_EMAIL_AUTHOR)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(live_email),
                              surveys_live_dir=live_email) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get(f"/gateway/curator/survey/{SLUG}")
            assert 'data-citation-email="graham.heinson@adelaide.edu.au"' in r.text
    run(_body())

    async def _body_clean(tmp2):
        live_name = _live(tmp2)
        async with app_client(tmp2, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(live_name),
                              surveys_live_dir=live_name) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get(f"/gateway/curator/survey/{SLUG}")
            assert "data-citation-email" not in r.text
    run(_body_clean(tmp_path / "clean"))


def test_citation_author_email_mirrors_engine_precedence():
    """Q3 HEURISTIC PIN. citation_author_email mirrors build_portal._investigators_of EXACTLY:
    lead_investigator.name, when present, IS the citation author (principal_investigators are
    consulted only when there is no lead). FAILS IF the helper flags a PI email while a lead
    with a clean name exists (the engine would not cite the PI), misses a lead email, or flags
    a plain name."""
    fn = curatorpage.citation_author_email
    assert fn({"lead_investigator": {"name": "a.b@x.org"}}) == ("lead_investigator", "a.b@x.org")
    assert fn({"lead_investigator": {"name": "Ada Lovelace"}}) is None
    # Lead present with a clean name: PI emails are NOT the citation author.
    assert fn({"lead_investigator": {"name": "Ada Lovelace"},
               "principal_investigators": [{"name": "x@y.org"}]}) is None
    # No lead: the PI list is the citation-author list.
    assert fn({"principal_investigators": [{"name": "Grace Hopper"}, {"name": "x@y.zt"}]}) \
        == ("principal_investigators", "x@y.zt")
    assert fn({}) is None


# --------------------------------------------------------------------------------------------------
# H2 — JS-source invariants (executable twins live in test_c43_hub_js_parity.py)
# --------------------------------------------------------------------------------------------------
def test_survey_hub_js_four_cards_and_no_build_id_card():
    """FOUR-CARDS SOURCE PIN incl. the build-id-card-ABSENT assertion. SURVEY_HUB_JS builds
    exactly the mockup's four cards (Serving / published, QA flags, Frame, Last build); the
    Stage-1 'Served build' build-id card is REMOVED (that fact lives in the drift chip + serve
    screen), and /data/build.json is no longer fetched here at all. FAILS IF the build-id card
    or its fetch returns, or a mockup card label disappears."""
    js = curatorpage.SURVEY_HUB_JS
    for label in ("'Serving / published'", "'QA flags'", "'Frame'", "'Last build'"):
        assert label in js, f"missing mockup card {label}"
    assert "Served build" not in js, "the build-id card must stay REMOVED (drift chip owns it)"
    assert "Stations built" not in js, "the Stage-1 card set must not return"
    assert "build.json" not in js, "the overview no longer needs /data/build.json"


def test_survey_hub_js_severity_rows_and_dead_branch_deleted():
    """SEVERITY-ROW + DEAD-BRANCH SOURCE PIN. The needs-attention rows are severity rows
    ('qa ' + kind, with the terse text and the full diagnosis in a title attr), the refusal
    boilerplate is a single REFUSED_NOTE constant appended once by the plan builder, and the old
    string-matching metadata branch (/citation|author|email/…) is DELETED — the info row derives
    only from the server-stamped data-citation-email. FAILS IF the dead regex branch returns, the
    note constant multiplies, or the severity-row classes disappear."""
    js = curatorpage.SURVEY_HUB_JS
    assert "'qa ' + row.kind" in js, "severity rows must carry the qa fail/warn/info classes"
    assert "setAttribute('title', row.title)" in js, "full diagnosis rides the title attr"
    assert js.count("var REFUSED_NOTE") == 1
    assert js.count("REFUSED_NOTE") == 2, "REFUSED_NOTE: one declaration + ONE plan use (once-only)"
    assert "citation|author|email" not in js, "the dead warning-string matcher must stay deleted"
    assert "data-citation-email" in js, "the info row derives from the server-stamped attribute"
    # The CSP/XSS discipline extends to the rewritten constant.
    assert ".innerHTML" not in js and "<script" not in js.lower()
    assert not re.search(r"""\bon[a-z]{3,}\s*=\s*['"]""", js)


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
