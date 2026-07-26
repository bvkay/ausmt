"""CONTRIBUTOR-CREDIT-SPEC (§6 curator DOI harvest): the curator publications rows reuse the SAME
client-side harvest the public Add Survey form uses. This pins the two guarantees:

  1. NO DUPLICATE-DRIFT: the gateway's bundled copy (gateway/static/doi_harvest.js) is BYTE-IDENTICAL to
     the single source portal/src/doi_harvest.js, and the /gateway/curator/doi-harvest.js route serves
     exactly those bytes. The gateway app image is content-blind (it cannot read portal/ at runtime), so
     the bundled copy is what enables reuse without a runtime cross-service import; this pin is what keeps
     it from drifting.
  2. WIRED: the edit page carries the "Look up DOI" button on publications rows and loads the shared
     harvest script; the route is session-gated and served as raw JS (not HTML-wrapped).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from gateway import curatorpage
from gateway.tests.conftest import (
    FakeGit, app_client, curator_login, inproc_edit_runner, run, write_survey_live,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PORTAL_SRC = _REPO_ROOT / "portal" / "src" / "doi_harvest.js"
_GATEWAY_STATIC = _REPO_ROOT / "gateway" / "static" / "doi_harvest.js"


def test_gateway_bundled_copy_matches_portal_source():
    """PARITY PIN: gateway/static/doi_harvest.js == portal/src/doi_harvest.js, byte-for-byte. FAILS RED if
    either copy is edited without the other - the exact drift the single-source rule exists to prevent."""
    if not _PORTAL_SRC.is_file():
        pytest.skip("portal/src not present (gateway-only checkout)")
    assert _GATEWAY_STATIC.read_bytes() == _PORTAL_SRC.read_bytes(), (
        "gateway/static/doi_harvest.js drifted from portal/src/doi_harvest.js - the shared DOI-harvest "
        "core must stay byte-identical across the two served copies (edit both, or neither)")


def test_served_constant_is_the_bundled_file():
    """The served constant is loaded from the bundled file, so the route cannot serve stale/other bytes."""
    assert curatorpage.DOI_HARVEST_JS == _GATEWAY_STATIC.read_text(encoding="utf-8")
    # sanity: it really is the harvest core (the reused public-form code)
    assert "AusmtDoiHarvest" in curatorpage.DOI_HARVEST_JS
    assert "api.crossref.org" in curatorpage.DOI_HARVEST_JS
    assert "api.datacite.org" in curatorpage.DOI_HARVEST_JS


def test_doi_harvest_js_route_session_gated_and_raw(tmp_path):
    """GET /gateway/curator/doi-harvest.js serves the shared harvest core (session-gated, javascript type,
    RAW not HTML-wrapped) and matches the bundled file byte-for-byte."""
    async def _body():
        surveys_live = tmp_path / "surveys-live"
        write_survey_live(surveys_live)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            # Ungated => redirect to login.
            r_anon = await client.get("/gateway/curator/doi-harvest.js", follow_redirects=False)
            assert r_anon.status_code == 303
            await curator_login(client)
            r = await client.get("/gateway/curator/doi-harvest.js")
            assert r.status_code == 200
            assert "javascript" in r.headers["content-type"]
            assert "<script" not in r.text  # raw JS, not wrapped
            assert r.text == _GATEWAY_STATIC.read_text(encoding="utf-8")
    run(_body())


def test_publications_rows_carry_harvest_button_and_load_shared_script(tmp_path):
    """The edit page renders the "Look up DOI" button on publications rows and loads the shared harvest
    script. FAILS RED if the button is missing (no harvest UI) or the script is not referenced (the button
    would be inert - window.AusmtDoiHarvest never defined)."""
    async def _body():
        surveys_live = tmp_path / "surveys-live"
        write_survey_live(surveys_live)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            body = (await client.get("/gateway/curator/edit/demo-survey-2026")).text
            assert 'src="/gateway/curator/doi-harvest.js"' in body
            # the button + status line ride the publications rows (at least the spare blank rows render it)
            assert "data-editor-harvest-doi" in body
            assert "Look up DOI" in body
            assert "data-harvest-status" in body
    run(_body())
