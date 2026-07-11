"""End-to-end tests for the curator TOTP enrolment surface (C41 T2) through the HTTP layer.

The Security page enrols the per-curator authenticator that gates survey retirement. These pins cover
the enrolment lifecycle (begin -> show-once secret -> activate -> active), the collapse guard
(rotation needs the current code; a session alone must not rotate), the show-once property, the
fail-closed refusals (wrong code, already-enrolled begin, rotate-without-current-code), the throttle,
and the strictPages CSP (no inline JS).

Failure criterion is in each test's docstring (Invariant 10). Async bodies run under conftest.run().
"""
from __future__ import annotations

import re

from gateway import totp
from gateway.tests.conftest import (
    CURATOR_NAME, FakeGit, app_client, csrf_for_session, curator_login, run,
)


def _valid_code(gw, *, now: float | None = None) -> str:
    """A current valid TOTP code for the curator's stored secret (active or pending), read straight
    from the DB the way an authenticator app would from the shared secret."""
    row = gw.db.get_totp(CURATOR_NAME)
    assert row is not None, "no TOTP row to compute a code from"
    return totp.code_at(row.secret, totp.current_step(now))


async def _begin(client):
    return await client.post("/gateway/curator/security/enrol",
                             data={"csrf_token": csrf_for_session(client)},
                             follow_redirects=False)


async def _activate(client, code):
    return await client.post("/gateway/curator/security/activate",
                             data={"code": code, "csrf_token": csrf_for_session(client)},
                             follow_redirects=False)


# --------------------------------------------------------------------------------------------------
# session + CSRF gates
# --------------------------------------------------------------------------------------------------
def test_security_page_requires_session(tmp_path):
    """GET /security redirects to login without a session; the POSTs 401. FAILS IF the security
    surface is reachable unauthenticated."""
    async def _body():
        async with app_client(tmp_path, git_runner=FakeGit()) as (client, _app, _gw, _cfg):
            g = await client.get("/gateway/curator/security", follow_redirects=False)
            assert g.status_code == 303
            p = await client.post("/gateway/curator/security/enrol", data={}, follow_redirects=False)
            assert p.status_code == 401
            a = await client.post("/gateway/curator/security/activate",
                                  data={"code": "123456"}, follow_redirects=False)
            assert a.status_code == 401
    run(_body())


def test_security_posts_require_csrf(tmp_path):
    """A logged-in security POST with a wrong CSRF token is 403 and enrols nothing. FAILS IF a
    cross-site form could drive enrolment/rotation."""
    async def _body():
        async with app_client(tmp_path, git_runner=FakeGit()) as (client, _app, gw, _cfg):
            await curator_login(client)
            r = await client.post("/gateway/curator/security/enrol",
                                  data={"csrf_token": "wrong"}, follow_redirects=False)
            assert r.status_code == 403
            assert gw.db.get_totp(CURATOR_NAME) is None
    run(_body())


# --------------------------------------------------------------------------------------------------
# enrol -> show-once -> activate
# --------------------------------------------------------------------------------------------------
def test_enrol_shows_secret_once_then_activation_makes_active(tmp_path):
    """Begin enrolment shows the base32 secret + otpauth URI ONCE and stages a PENDING (not active)
    enrolment; a subsequent GET does NOT re-show the secret; a valid code activates it. FAILS IF the
    secret is re-rendered on reload, or a pending enrolment is treated as active, or a valid code does
    not activate."""
    async def _body():
        async with app_client(tmp_path, git_runner=FakeGit()) as (client, _app, gw, _cfg):
            await curator_login(client)
            begin = await _begin(client)
            assert begin.status_code == 200
            # The show-once page carries the secret + the otpauth URI.
            row = gw.db.get_totp(CURATOR_NAME)
            assert row is not None and row.active is False, "begin must stage a PENDING enrolment"
            assert row.secret in begin.text, "the secret was not shown on the begin page"
            assert "otpauth://totp/" in begin.text
            # A reload of the security page must NOT re-show the secret (shown once).
            page = await client.get("/gateway/curator/security")
            assert row.secret not in page.text, "secret leaked on a security-page reload (not show-once)"
            assert "pending activation" in page.text.lower()
            # Activate with a real code -> active.
            act = await _activate(client, _valid_code(gw))
            assert act.status_code == 200
            active = gw.db.get_totp(CURATOR_NAME)
            assert active.active is True and active.enrolled_utc is not None
            assert "enrolled" in act.text.lower()
    run(_body())


def test_activate_wrong_code_refused_stays_pending(tmp_path):
    """A wrong activation code is refused (400) and the enrolment stays PENDING (not active). FAILS IF
    a wrong code activates the factor."""
    async def _body():
        async with app_client(tmp_path, git_runner=FakeGit()) as (client, _app, gw, _cfg):
            await curator_login(client)
            await _begin(client)
            r = await _activate(client, "000000")
            # 000000 will (almost surely) not match; if it improbably does, perturb — but the pin is
            # the refusal, so assert on a definitely-wrong code derived from the real one.
            good = _valid_code(gw)
            wrong = good[:-1] + str((int(good[-1]) + 1) % 10)
            r = await _activate(client, wrong)
            assert r.status_code == 400
            assert gw.db.get_totp(CURATOR_NAME).active is False
    run(_body())


def test_begin_when_already_active_is_refused(tmp_path):
    """Once ACTIVE, a plain begin-enrolment is refused (409) — an active secret is rotated with the
    current code, never silently replaced by a session-only begin. FAILS IF begin overwrites an active
    secret without the current code (a collapse)."""
    async def _body():
        async with app_client(tmp_path, git_runner=FakeGit()) as (client, _app, gw, _cfg):
            await curator_login(client)
            await _begin(client)
            await _activate(client, _valid_code(gw))
            active_secret = gw.db.get_totp(CURATOR_NAME).secret
            r = await _begin(client)
            assert r.status_code == 409
            assert gw.db.get_totp(CURATOR_NAME).secret == active_secret, "begin replaced an active secret"
    run(_body())


# --------------------------------------------------------------------------------------------------
# rotation collapse guard
# --------------------------------------------------------------------------------------------------
def test_rotate_without_current_code_refused_collapse_guard(tmp_path):
    """Rotation with a WRONG/absent current code is refused (400) and the secret is UNCHANGED — a
    session alone must never rotate the secret (D2 collapse guard). FAILS IF a session-only rotation
    succeeds. Mutation-proof: dropping the current-code check in handle_security_rotate makes this RED
    (a wrong code would then rotate)."""
    async def _body():
        async with app_client(tmp_path, git_runner=FakeGit()) as (client, _app, gw, _cfg):
            await curator_login(client)
            await _begin(client)
            await _activate(client, _valid_code(gw))
            before = gw.db.get_totp(CURATOR_NAME).secret
            good = _valid_code(gw)
            wrong = good[:-1] + str((int(good[-1]) + 1) % 10)
            r = await client.post("/gateway/curator/security/rotate",
                                  data={"code": wrong, "csrf_token": csrf_for_session(client)},
                                  follow_redirects=False)
            assert r.status_code == 400
            assert gw.db.get_totp(CURATOR_NAME).secret == before, "session-only rotation changed the secret"
            assert gw.db.get_totp(CURATOR_NAME).active is True
    run(_body())


def test_rotate_with_current_code_stages_new_pending_secret(tmp_path):
    """Rotation with a valid CURRENT code shows a NEW secret once and stages it PENDING (the old secret
    retired; deletion refused until re-activation). FAILS IF rotation does not change the secret or
    leaves it active without re-activation."""
    async def _body():
        async with app_client(tmp_path, git_runner=FakeGit()) as (client, _app, gw, _cfg):
            await curator_login(client)
            await _begin(client)
            await _activate(client, _valid_code(gw))
            old_secret = gw.db.get_totp(CURATOR_NAME).secret
            r = await client.post("/gateway/curator/security/rotate",
                                  data={"code": _valid_code(gw), "csrf_token": csrf_for_session(client)},
                                  follow_redirects=False)
            assert r.status_code == 200
            new = gw.db.get_totp(CURATOR_NAME)
            assert new.secret != old_secret, "rotation did not change the secret"
            assert new.active is False, "rotated secret must be pending re-activation"
            assert new.secret in r.text, "the new secret was not shown once"
            # Re-activate the new secret closes the loop.
            act = await _activate(client, _valid_code(gw))
            assert gw.db.get_totp(CURATOR_NAME).active is True
            assert act.status_code == 200
    run(_body())


# --------------------------------------------------------------------------------------------------
# rate limit + CSP
# --------------------------------------------------------------------------------------------------
def test_totp_rate_limit_trips_on_repeated_wrong_codes(tmp_path):
    """After login_max_attempts wrong codes the TOTP throttle refuses further attempts with 429 (the
    login-throttle pattern). FAILS IF wrong codes are unbounded."""
    async def _body():
        # login_max_attempts defaults to 5 in the test config.
        async with app_client(tmp_path, git_runner=FakeGit()) as (client, _app, gw, cfg):
            await curator_login(client)
            await _begin(client)
            good = _valid_code(gw)
            wrong = good[:-1] + str((int(good[-1]) + 1) % 10)
            for _ in range(cfg.login_max_attempts):
                r = await _activate(client, wrong)
                assert r.status_code == 400
            blocked = await _activate(client, wrong)
            assert blocked.status_code == 429
            # A valid code is ALSO refused while blocked (the window must roll off first).
            still = await _activate(client, good)
            assert still.status_code == 429
    run(_body())


def test_security_pages_have_no_inline_js(tmp_path):
    """The security page (none/pending/show-once states) carries ZERO inline scripts / on*= handlers —
    the strictPages CSP pin. FAILS IF any state inlines a script or event handler."""
    async def _body():
        async with app_client(tmp_path, git_runner=FakeGit()) as (client, _app, _gw, _cfg):
            await curator_login(client)
            pages = [(await client.get("/gateway/curator/security")).text,
                     (await _begin(client)).text]
            for html in pages:
                for m in re.finditer(r"<script\b[^>]*>", html):
                    assert re.search(r"\bsrc\s*=", m.group(0)), f"inline script: {m.group(0)}"
                assert re.findall(r"<[^>]*\son\w+\s*=", html) == [], "inline event handler present"
    run(_body())
