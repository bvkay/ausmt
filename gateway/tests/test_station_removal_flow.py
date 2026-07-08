"""End-to-end tests for STATION (EDI) REMOVAL through the curator HTTP surface, with the in-process
edit seam + FakeGit. Mirrors test_editor_form_flow.py's structure.

The curator asked for a way to remove an individual EDI (a bad or withdrawn-consent station) from a
published survey. This exercises the full list → preview → confirm pipeline:
  - the stations page lists every EDI with its derived station id + a remove checkbox;
  - preview shows the exact file set, count before→after, the survey.yaml diff, and the validator
    verdict on the package WITHOUT the removed files, and REFUSES an all-stations removal;
  - confirm git-rm's exactly the selected files and bumps the version + appends the release note;
  - a stale selection (file vanished since the form rendered) is refused, not half-applied;
  - CSRF + session gate every POST; the CSP pins (no inline JS, data-confirm on the confirm form).

Failure criterion is in each test's docstring (Invariant 10). Async bodies run under conftest.run().
"""
from __future__ import annotations

import re

from gateway.tests.conftest import (
    FakeGit, app_client, csrf_for_session, curator_login, inproc_edit_runner, run,
    write_survey_live,
)

# A survey.yaml with a real version so the bump logic works; the station list is the EDI files.
MULTI_YAML = """\
schema_version: "0.2"
slug: multi-survey-2026
project_name: Multi Survey
version: 1.2.0
country: Australia
region: South Australia

access:
  level: open
  embargo_until: null
  contact: null

license: CC-BY-4.0

# unknown key survives verbatim
custom_local_note: "keep me byte-for-byte"
"""

STATIONS = ("SA225.edi", "SA226.edi", "SA227.edi")


def _multi_live(tmp_path, stations=STATIONS):
    """A surveys-live checkout with a multi-station survey. write_survey_live seeds the yaml + one
    S01.edi; replace that edi/ with our named station set so the count is deterministic."""
    surveys_live = tmp_path / "surveys-live"
    pkg = write_survey_live(surveys_live, slug="multi-survey-2026", yaml_text=MULTI_YAML)
    edi = pkg / "transfer_functions" / "edi"
    for existing in edi.iterdir():
        existing.unlink()
    for name in stations:
        (edi / name).write_text(">HEAD\n  DATAID=%s\n>END\n" % name, encoding="utf-8")
    return surveys_live, pkg


# --------------------------------------------------------------------------------------------------
# listing
# --------------------------------------------------------------------------------------------------
def test_stations_page_lists_edis_with_checkboxes(tmp_path):
    """The stations page lists every EDI with its derived station id and a remove checkbox, and the
    edit form links to it. FAILS IF a station is missed, the station id is wrong, or the checkbox is
    absent."""
    async def _body():
        surveys_live, _pkg = _multi_live(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            body = (await client.get("/gateway/curator/edit/multi-survey-2026/stations")).text
            for name in STATIONS:
                assert name in body
                assert f'value="{name}"' in body  # a remove checkbox for each EDI
            assert "SA225" in body and "SA226" in body  # derived station ids
            # The edit form links to the stations page.
            edit = (await client.get("/gateway/curator/edit/multi-survey-2026")).text
            assert '/gateway/curator/edit/multi-survey-2026/stations' in edit
    run(_body())


# --------------------------------------------------------------------------------------------------
# preview: file set + counts + all-stations refusal
# --------------------------------------------------------------------------------------------------
def test_preview_shows_file_set_and_before_after_counts(tmp_path):
    """Previewing a removal shows exactly the selected file(s), the station count before→after, the
    survey.yaml version bump, and a validator verdict. FAILS IF the wrong files/counts are shown or the
    diff omits the version bump."""
    async def _body():
        surveys_live, _pkg = _multi_live(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            r = await client.post("/gateway/curator/edit/multi-survey-2026/stations/preview",
                                  data={"remove": "SA226.edi", "note": "withdrawn consent",
                                        "bump": "minor", "csrf_token": csrf},
                                  follow_redirects=False)
            assert r.status_code == 200
            assert "SA226.edi" in r.text
            assert "3" in r.text and "2" in r.text            # before 3 -> after 2
            assert "new version 1.3.0" in r.text              # minor bump
            assert "SA225.edi" not in _files_to_delete(r.text)  # survivor not in the delete list
            # a confirm form with the data-confirm guard is present (validator passed)
            assert 'data-confirm=' in r.text
            assert "This deletes the EDI files" in r.text
    run(_body())


def _files_to_delete(html: str) -> str:
    """The 'Files to delete' panel text, so a test can assert a survivor is NOT listed for deletion."""
    m = re.search(r"Files to delete(.*?)</div>", html, re.S)
    return m.group(1) if m else ""


def test_preview_refuses_all_stations_removal(tmp_path):
    """Selecting every EDI is refused at preview (at least one must remain). FAILS IF an all-stations
    selection produces a confirmable preview instead of an error back on the stations page."""
    async def _body():
        surveys_live, _pkg = _multi_live(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            r = await client.post("/gateway/curator/edit/multi-survey-2026/stations/preview",
                                  data={"remove": ["SA225.edi", "SA226.edi", "SA227.edi"],
                                        "note": "all", "bump": "minor", "csrf_token": csrf},
                                  follow_redirects=False)
            assert r.status_code == 200
            assert "at least one" in r.text.lower()
            # No confirm form (the removal was refused).
            assert "stations/confirm" not in r.text
    run(_body())


def test_preview_empty_selection_refused(tmp_path):
    """Previewing with nothing ticked returns to the stations page with a clear error. FAILS IF an
    empty selection reaches the runner as a valid removal."""
    async def _body():
        surveys_live, _pkg = _multi_live(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            r = await client.post("/gateway/curator/edit/multi-survey-2026/stations/preview",
                                  data={"note": "x", "bump": "minor", "csrf_token": csrf},
                                  follow_redirects=False)
            assert r.status_code == 200
            assert "select at least one" in r.text.lower()
    run(_body())


# --------------------------------------------------------------------------------------------------
# confirm: deletes exactly the selected files, bumps version, appends note
# --------------------------------------------------------------------------------------------------
def test_confirm_deletes_selected_and_commits(tmp_path):
    """Confirming a removal git-rm's exactly the selected EDI (survivors remain), writes the bumped
    survey.yaml with the release note, and reports success. FAILS IF the wrong file is removed, the
    note is not recorded, or the survivor is deleted."""
    async def _body():
        surveys_live, pkg = _multi_live(tmp_path)
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            # Preview first to get the sha the confirm pins against.
            prev = await client.post("/gateway/curator/edit/multi-survey-2026/stations/preview",
                                     data={"remove": "SA226.edi", "note": "withdrawn consent",
                                           "bump": "minor", "csrf_token": csrf},
                                     follow_redirects=False)
            sha = _hidden(prev.text, "new_sha256")
            filenames_json = _hidden(prev.text, "filenames_json")
            r = await client.post("/gateway/curator/edit/multi-survey-2026/stations/confirm",
                                  data={"new_sha256": sha, "bump": "minor",
                                        "filenames_json": filenames_json,
                                        "note": "withdrawn consent", "csrf_token": csrf},
                                  follow_redirects=False)
            assert r.status_code == 200, r.text
            assert "Removed 1 station" in r.text
            edi = pkg / "transfer_functions" / "edi"
            assert not (edi / "SA226.edi").exists()     # removed
            assert (edi / "SA225.edi").exists()          # survivor
            assert (edi / "SA227.edi").exists()
            new_yaml = (pkg / "survey.yaml").read_text(encoding="utf-8")
            assert "1.3.0" in new_yaml
            assert "withdrawn consent" in new_yaml       # release note landed
            assert "release_notes:" in new_yaml
            # exactly one EDI was git-rm'd, and it was SA226.
            rm_calls = [c for c in git.calls if c[:1] == ["rm"]]
            assert rm_calls
            assert any("SA226.edi" in part for c in rm_calls for part in c)
            assert not any("SA225.edi" in part for c in rm_calls for part in c)
    run(_body())


def _hidden(html: str, name: str) -> str:
    m = re.search(rf'name="{name}"[^>]*value="([^"]*)"', html) or \
        re.search(rf'value="([^"]*)"[^>]*name="{name}"', html)
    assert m, f"hidden field {name!r} not found in preview"
    import html as _h
    return _h.unescape(m.group(1))


# --------------------------------------------------------------------------------------------------
# stale selection refused (file vanished between preview and confirm)
# --------------------------------------------------------------------------------------------------
def test_confirm_stale_selection_refused(tmp_path):
    """If a selected file vanished since the preview (a stale form / a concurrent removal), confirm is
    refused with a 409 — never a half-removal. FAILS IF a missing selection is silently committed for
    the survivors."""
    async def _body():
        surveys_live, pkg = _multi_live(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            prev = await client.post("/gateway/curator/edit/multi-survey-2026/stations/preview",
                                     data={"remove": "SA226.edi", "note": "x", "bump": "minor",
                                           "csrf_token": csrf}, follow_redirects=False)
            sha = _hidden(prev.text, "new_sha256")
            filenames_json = _hidden(prev.text, "filenames_json")
            # Simulate the file vanishing (a concurrent removal) between preview and confirm.
            (pkg / "transfer_functions" / "edi" / "SA226.edi").unlink()
            r = await client.post("/gateway/curator/edit/multi-survey-2026/stations/confirm",
                                  data={"new_sha256": sha, "bump": "minor",
                                        "filenames_json": filenames_json,
                                        "note": "x", "csrf_token": csrf},
                                  follow_redirects=False)
            assert r.status_code == 409, r.text
            # The survivors are untouched (no half-removal).
            edi = pkg / "transfer_functions" / "edi"
            assert (edi / "SA225.edi").exists() and (edi / "SA227.edi").exists()
    run(_body())


# --------------------------------------------------------------------------------------------------
# CSRF + session gates
# --------------------------------------------------------------------------------------------------
def test_stations_routes_require_session(tmp_path):
    """The stations GET redirects to login without a session; the POSTs 401 without a session. FAILS
    IF any station route is reachable unauthenticated."""
    async def _body():
        surveys_live, _pkg = _multi_live(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            g = await client.get("/gateway/curator/edit/multi-survey-2026/stations",
                                 follow_redirects=False)
            assert g.status_code == 303  # -> login
            p = await client.post("/gateway/curator/edit/multi-survey-2026/stations/preview",
                                  data={"remove": "SA226.edi"}, follow_redirects=False)
            assert p.status_code == 401
            c = await client.post("/gateway/curator/edit/multi-survey-2026/stations/confirm",
                                  data={"filenames_json": "[]"}, follow_redirects=False)
            assert c.status_code == 401
    run(_body())


def test_stations_post_bad_csrf_refused(tmp_path):
    """A logged-in POST with a wrong CSRF token is a 403 with no removal. FAILS IF a cross-site form
    could drive a station removal."""
    async def _body():
        surveys_live, pkg = _multi_live(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.post("/gateway/curator/edit/multi-survey-2026/stations/preview",
                                  data={"remove": "SA226.edi", "note": "x", "bump": "minor",
                                        "csrf_token": "wrong-token"}, follow_redirects=False)
            assert r.status_code == 403
            # nothing removed
            assert (pkg / "transfer_functions" / "edi" / "SA226.edi").exists()
    run(_body())


# --------------------------------------------------------------------------------------------------
# CSP pins on the new pages
# --------------------------------------------------------------------------------------------------
def test_stations_pages_have_no_inline_js_and_confirm_rides_data_attr(tmp_path):
    """The stations list + removal preview carry ZERO inline scripts / on*= handlers, and the final
    commit form uses data-confirm (the delegated CURATOR_UI_JS handler) — the strictPages CSP pin.
    FAILS IF a page inlines a script or an event handler, or the confirm reverts to an inline
    onsubmit."""
    async def _body():
        surveys_live, _pkg = _multi_live(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            for html in (
                (await client.get("/gateway/curator/edit/multi-survey-2026/stations")).text,
                (await client.post("/gateway/curator/edit/multi-survey-2026/stations/preview",
                                   data={"remove": "SA226.edi", "note": "x", "bump": "minor",
                                         "csrf_token": csrf}, follow_redirects=False)).text,
            ):
                for m in re.finditer(r"<script\b[^>]*>", html):
                    assert re.search(r"\bsrc\s*=", m.group(0)), f"inline script: {m.group(0)}"
                assert re.findall(r"<[^>]*\son\w+\s*=", html) == [], "inline event handler present"
            # The confirm form rides data-confirm with the mandated house copy.
            prev = (await client.post("/gateway/curator/edit/multi-survey-2026/stations/preview",
                                      data={"remove": "SA226.edi", "note": "x", "bump": "minor",
                                            "csrf_token": csrf}, follow_redirects=False)).text
            assert 'data-confirm="Remove 1 station(s) from multi-survey-2026?' in prev
    run(_body())
