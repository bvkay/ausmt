"""End-to-end tests for SURVEY RETIREMENT through the curator HTTP surface (C41 D2 / T3+T4+T6), with
FakeGit at the publish seam. Mirrors test_station_removal_flow.py's structure.

The curator retires a whole survey from the Metadata tab's danger zone: a confirmation page discloses
exactly what the record D2 lists, then the server gates the POST in order — session, CSRF, the
last-survey guard, the TOTP second factor (enrolled? rate-limited? valid? not-replayed?), the typed
slug, the required note — and only then git-rm -r's the package in one commit under PUBLISH_LOCK.

Failure criterion is in each test's docstring (Invariant 10). Async bodies run under conftest.run().
The real-git commit/rollback/revert byte-level guarantees are in test_publish_real_git.py (D1.h); here
FakeGit proves the flow shape, the gate order, and 'nothing staged' on every refusal.
"""
from __future__ import annotations

import re

import pytest

from gateway import totp
from gateway.tests.conftest import (
    CURATOR_NAME, FakeGit, app_client, csrf_for_session, curator_login, inproc_edit_runner, run,
    write_survey_live,
)


def _yaml(slug: str) -> str:
    return (f'schema_version: "0.2"\nslug: {slug}\nproject_name: {slug}\nversion: 1.0.0\n'
            'country: Australia\nregion: South Australia\naccess:\n  level: open\n'
            '  embargo_until: null\n  contact: null\nlicense: CC-BY-4.0\n')


def _live_with_surveys(tmp_path, slugs=("survey-a-2026", "survey-b-2026")):
    """A surveys-live checkout carrying each named survey (survey.yaml + one S01.edi). Two by default
    so the last-survey guard does not fire; pass a single slug to exercise the guard."""
    surveys_live = tmp_path / "surveys-live"
    for slug in slugs:
        write_survey_live(surveys_live, slug=slug, yaml_text=_yaml(slug))
    return surveys_live


def _enrol_totp(gw, name=CURATOR_NAME):
    """Directly enrol + activate a TOTP secret with last_used_step reset LOW (0), so a CURRENT real
    code's step is far greater and is accepted (no 30 s wait, no clock injection through HTTP).
    Returns the secret so the test can compute a live code."""
    secret = totp.generate_secret()
    gw.db.begin_totp_enrolment(name, secret)
    gw.db.activate_totp(name, 0)
    return secret


def _code(secret: str) -> str:
    return totp.code_at(secret, totp.current_step())


def _mutating_git(git: FakeGit) -> list:
    """The git calls that would MUTATE surveys-live (a retirement must issue NONE of these on a refused
    POST). Read-only rev-parse/status from the nav-shell drift chip are excluded."""
    return [c for c in git.calls if c and c[0] in ("rm", "commit", "merge", "push", "add")]


async def _retire(client, slug, *, typed=None, note="retired for test", code, csrf=None):
    return await client.post(
        f"/gateway/curator/survey/{slug}/retire",
        data={"typed_slug": slug if typed is None else typed, "note": note, "code": code,
              "csrf_token": csrf if csrf is not None else csrf_for_session(client)},
        follow_redirects=False)


# --------------------------------------------------------------------------------------------------
# happy path: one commit, git rm -r of exactly the slug, note in body, sibling untouched
# --------------------------------------------------------------------------------------------------
def test_retire_happy_path_one_commit_removes_slug(tmp_path):
    """A valid retirement git-rm -r's EXACTLY the slug's directory in ONE commit whose body carries the
    release note, leaves the sibling survey untouched, and reports success. FAILS IF the wrong path is
    removed, the sibling is touched, more than one commit is issued, or the note is not in the body."""
    async def _body():
        surveys_live = _live_with_surveys(tmp_path)
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, gw, _cfg):
            await curator_login(client)
            secret = _enrol_totp(gw)
            r = await _retire(client, "survey-a-2026", note="superseded by survey-b",
                              code=_code(secret))
            assert r.status_code == 200, r.text
            assert "Retired survey" in r.text
            # exactly one rm, targeting exactly surveys/survey-a-2026 with -r, nothing else.
            rm_calls = [c for c in git.calls if c[:1] == ["rm"]]
            assert len(rm_calls) == 1, rm_calls
            assert rm_calls[0] == ["rm", "-r", "--", "surveys/survey-a-2026"]
            # exactly one commit, and its body carries the note.
            commit_calls = [c for c in git.calls if "commit" in c]
            assert len(commit_calls) == 1
            assert any("superseded by survey-b" in part for part in commit_calls[0])
            assert any("Curated-by: curator:" in part for part in commit_calls[0])
            # on-disk: the target survey is gone, the sibling remains (survey-scope diff-minimality).
            assert not (surveys_live / "surveys" / "survey-a-2026").exists()
            assert (surveys_live / "surveys" / "survey-b-2026" / "survey.yaml").exists()
            # a push to origin happened.
            assert any(c[:2] == ["push", "origin"] for c in git.calls)
    run(_body())


def test_retire_consumes_the_totp_step(tmp_path):
    """A successful retirement CONSUMES the TOTP code (advances last_used_step), so the same code
    cannot retire another survey (replay). FAILS IF the code is not consumed on success."""
    async def _body():
        surveys_live = _live_with_surveys(tmp_path, slugs=("a-2026", "b-2026", "c-2026"))
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, gw, _cfg):
            await curator_login(client)
            secret = _enrol_totp(gw)
            code = _code(secret)
            r1 = await _retire(client, "a-2026", code=code)
            assert r1.status_code == 200
            # The same code on a different surviving survey (b, c remain -> not last) is a REPLAY.
            r2 = await _retire(client, "b-2026", code=code)
            assert r2.status_code == 409
            assert "already used" in r2.text.lower()
            assert (surveys_live / "surveys" / "b-2026").exists(), "replay retirement was not blocked"
    run(_body())


# --------------------------------------------------------------------------------------------------
# refusals: nothing staged
# --------------------------------------------------------------------------------------------------
def test_retire_typed_slug_mismatch_refused_nothing_staged(tmp_path):
    """A wrong typed slug is refused (400) with NO git mutation and the survey intact. FAILS IF a
    mismatched confirmation retires the survey, or any mutating git op runs (clean-checkout pin)."""
    async def _body():
        surveys_live = _live_with_surveys(tmp_path)
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, gw, _cfg):
            await curator_login(client)
            secret = _enrol_totp(gw)
            r = await _retire(client, "survey-a-2026", typed="survey-WRONG", code=_code(secret))
            assert r.status_code == 400
            assert _mutating_git(git) == [], f"a mutating git op ran on a refusal: {_mutating_git(git)}"
            assert (surveys_live / "surveys" / "survey-a-2026" / "survey.yaml").exists()
    run(_body())


def test_retire_missing_note_refused_nothing_staged(tmp_path):
    """A missing release note is refused (400) with nothing staged. FAILS IF a retirement commits with
    no note, or any mutating git op runs."""
    async def _body():
        surveys_live = _live_with_surveys(tmp_path)
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, gw, _cfg):
            await curator_login(client)
            secret = _enrol_totp(gw)
            r = await _retire(client, "survey-a-2026", note="   ", code=_code(secret))
            assert r.status_code == 400
            assert _mutating_git(git) == []
            assert (surveys_live / "surveys" / "survey-a-2026").exists()
    run(_body())


def test_retire_requires_session_and_csrf(tmp_path):
    """The retire GET redirects to login without a session; the POST 401s without a session and 403s
    with a bad CSRF token — with nothing staged. FAILS IF the retire surface is reachable
    unauthenticated or without a valid CSRF token."""
    async def _body():
        surveys_live = _live_with_surveys(tmp_path)
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, gw, _cfg):
            g = await client.get("/gateway/curator/survey/survey-a-2026/retire",
                                 follow_redirects=False)
            assert g.status_code == 303
            p = await client.post("/gateway/curator/survey/survey-a-2026/retire",
                                  data={"typed_slug": "survey-a-2026", "note": "x", "code": "123456"},
                                  follow_redirects=False)
            assert p.status_code == 401
            await curator_login(client)
            _enrol_totp(gw)
            bad = await client.post("/gateway/curator/survey/survey-a-2026/retire",
                                    data={"typed_slug": "survey-a-2026", "note": "x",
                                          "code": "123456", "csrf_token": "wrong"},
                                    follow_redirects=False)
            assert bad.status_code == 403
            assert _mutating_git(git) == []
    run(_body())


# --------------------------------------------------------------------------------------------------
# TOTP gate
# --------------------------------------------------------------------------------------------------
def test_retire_unenrolled_curator_refused_with_enrol_pointer(tmp_path):
    """A curator with no active TOTP enrolment is refused (409) with a pointer to Security, nothing
    staged. FAILS IF an un-enrolled curator can retire a survey (fail-closed)."""
    async def _body():
        surveys_live = _live_with_surveys(tmp_path)
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)  # NOT enrolled
            r = await _retire(client, "survey-a-2026", code="123456")
            assert r.status_code == 409
            assert "security" in r.text.lower() or "enrol" in r.text.lower()
            assert _mutating_git(git) == []
            assert (surveys_live / "surveys" / "survey-a-2026").exists()
    run(_body())


def test_retire_pending_enrolment_does_not_satisfy_gate(tmp_path):
    """A curator with a PENDING (begun but not activated) enrolment is refused (409) — an unactivated
    enrolment does NOT satisfy the deletion gate (fail-closed). FAILS IF a pending secret gates a
    retirement. The code used is a valid code FOR the pending secret, proving it is the ACTIVATION
    state (not the code validity) that blocks."""
    async def _body():
        surveys_live = _live_with_surveys(tmp_path)
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, gw, _cfg):
            await curator_login(client)
            # Begin but do NOT activate: a pending row (active False) with a real, correct code.
            secret = totp.generate_secret()
            gw.db.begin_totp_enrolment(CURATOR_NAME, secret)
            assert gw.db.get_totp(CURATOR_NAME).active is False
            r = await _retire(client, "survey-a-2026", code=_code(secret))
            assert r.status_code == 409
            assert "security" in r.text.lower() or "enrol" in r.text.lower()
            assert _mutating_git(git) == []
            assert (surveys_live / "surveys" / "survey-a-2026").exists()
    run(_body())


def test_retire_wrong_code_refused_nothing_staged(tmp_path):
    """A wrong TOTP code is refused (400) with nothing staged. FAILS IF a wrong code retires the
    survey."""
    async def _body():
        surveys_live = _live_with_surveys(tmp_path)
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, gw, _cfg):
            await curator_login(client)
            secret = _enrol_totp(gw)
            good = _code(secret)
            wrong = good[:-1] + str((int(good[-1]) + 1) % 10)
            r = await _retire(client, "survey-a-2026", code=wrong)
            assert r.status_code == 400
            assert _mutating_git(git) == []
            assert (surveys_live / "surveys" / "survey-a-2026").exists()
    run(_body())


def test_retire_replayed_code_rejected(tmp_path):
    """A code whose step was already consumed is rejected (409) with nothing staged. FAILS IF a
    just-used code retires a survey (the last_used_step replay guard)."""
    async def _body():
        surveys_live = _live_with_surveys(tmp_path)
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, gw, _cfg):
            await curator_login(client)
            secret = _enrol_totp(gw)
            step = totp.current_step()
            gw.db.consume_totp_step(CURATOR_NAME, step)   # mark the current step already used
            r = await _retire(client, "survey-a-2026", code=totp.code_at(secret, step))
            assert r.status_code == 409
            assert "already used" in r.text.lower()
            assert _mutating_git(git) == []
            assert (surveys_live / "surveys" / "survey-a-2026").exists()
    run(_body())


def test_retire_rate_limit_trips(tmp_path):
    """After login_max_attempts wrong codes the retire throttle refuses further attempts (429). FAILS
    IF wrong codes on the retire path are unbounded."""
    async def _body():
        surveys_live = _live_with_surveys(tmp_path)
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, gw, cfg):
            await curator_login(client)
            secret = _enrol_totp(gw)
            good = _code(secret)
            wrong = good[:-1] + str((int(good[-1]) + 1) % 10)
            for _ in range(cfg.login_max_attempts):
                r = await _retire(client, "survey-a-2026", code=wrong)
                assert r.status_code == 400
            blocked = await _retire(client, "survey-a-2026", code=wrong)
            assert blocked.status_code == 429
            assert (surveys_live / "surveys" / "survey-a-2026").exists()
    run(_body())


# --------------------------------------------------------------------------------------------------
# T6 last-survey guard (evidenced: an empty corpus breaks the production build)
# --------------------------------------------------------------------------------------------------
def test_retire_last_survey_guard_refuses_nothing_staged(tmp_path):
    """With only ONE published survey, retiring it is refused (409) with nothing staged — an empty
    corpus breaks the next rebuild (T6, evidenced). FAILS IF the last survey can be retired."""
    async def _body():
        surveys_live = _live_with_surveys(tmp_path, slugs=("only-survey-2026",))
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, gw, _cfg):
            await curator_login(client)
            secret = _enrol_totp(gw)
            r = await _retire(client, "only-survey-2026", code=_code(secret))
            assert r.status_code == 409
            assert "last remaining survey" in r.text.lower()
            assert _mutating_git(git) == []
            assert (surveys_live / "surveys" / "only-survey-2026").exists()
            # The GET confirmation page also discloses the guard (no form).
            page = (await client.get("/gateway/curator/survey/only-survey-2026/retire")).text
            assert "cannot retire the last survey" in page.lower()
            assert 'name="typed_slug"' not in page, "the retire form must not render for the last survey"
            assert 'name="code"' not in page, "the retire form must not render for the last survey"
    run(_body())


# --------------------------------------------------------------------------------------------------
# confirmation page disclosure (record D2) + CSP
# --------------------------------------------------------------------------------------------------
def test_retire_confirm_page_discloses_record_d2(tmp_path):
    """The confirmation page states the station count, the serving-until-rebuild reality, and the
    git-revert undo, and renders the typed-slug + note + code form. FAILS IF any disclosure is missing
    or the form omits a required field."""
    async def _body():
        surveys_live = _live_with_surveys(tmp_path)
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, gw, _cfg):
            await curator_login(client)
            _enrol_totp(gw)
            page = (await client.get("/gateway/curator/survey/survey-a-2026/retire")).text
            assert "1 station file" in page                       # station count (one S01.edi)
            assert "until the next rebuild" in page.lower()       # serving reality
            assert "git revert" in page.lower()                   # the undo
            assert "collection" in page.lower()                   # collections recompute
            assert "doi" in page.lower()                          # DOI honesty
            assert 'name="typed_slug"' in page and 'name="note"' in page and 'name="code"' in page
    run(_body())


def test_retire_pages_have_no_inline_js(tmp_path):
    """The confirmation page carries ZERO inline scripts / on*= handlers — the strictPages CSP pin.
    FAILS IF the page inlines a script or an event handler."""
    async def _body():
        surveys_live = _live_with_surveys(tmp_path)
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, gw, _cfg):
            await curator_login(client)
            _enrol_totp(gw)
            html = (await client.get("/gateway/curator/survey/survey-a-2026/retire")).text
            for m in re.finditer(r"<script\b[^>]*>", html):
                assert re.search(r"\bsrc\s*=", m.group(0)), f"inline script: {m.group(0)}"
            assert re.findall(r"<[^>]*\son\w+\s*=", html) == [], "inline event handler present"
    run(_body())


# --------------------------------------------------------------------------------------------------
# parametrised git-failure rollback (the test_curator_publish pattern, survey scope)
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("fail_verb", ["rm", "commit", "merge", "push"])
def test_retire_git_failure_rolls_back_fail_closed(tmp_path, fail_verb):
    """An injected git failure at ANY step of the retirement sequence => 409, surveys-live rolled back
    to the captured pre-state (rolled_back), and the sibling survey untouched. FAILS IF a git failure
    is not caught + rolled back (a half-retired publication ledger). Mirrors the test_curator_publish
    parametrised rollback pattern at survey scope."""
    async def _body():
        surveys_live = _live_with_surveys(tmp_path)
        git = FakeGit(fail_on={fail_verb: (1, f"{fail_verb} rejected")})
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, gw, _cfg):
            await curator_login(client)
            secret = _enrol_totp(gw)
            r = await _retire(client, "survey-a-2026", code=_code(secret))
            assert r.status_code == 409, r.text
            assert git.rolled_back, f"a {fail_verb} failure did not roll surveys-live back"
            assert (surveys_live / "surveys" / "survey-b-2026" / "survey.yaml").exists()
    run(_body())
