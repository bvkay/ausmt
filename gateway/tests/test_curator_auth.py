"""Curator auth + session + CSRF + rate limit (design §2/§6/§8).

Guards under test, each with a stated failure criterion and proven-failing evidence:
- no session => every curator route 401/redirect (fails if a route served content unauthenticated).
- wrong curator key => 401, rate-limited after N (fails if a wrong key set a session, or if brute
  force was not throttled).
- valid key => session cookie HttpOnly+SameSite (fails if the cookie lacked HttpOnly/SameSite).
- expired session => 401/redirect (fails if a past-expiry session still authenticated).
- CSRF: a state-changing POST without the token => 403, NO transition, NO git call.
- fail-closed config: unset/malformed AUSMT_CURATOR_KEYS => 503 on curator routes.
"""
from __future__ import annotations

import time

import pytest

from gateway import curator_auth, states
from gateway.tests.conftest import (
    CURATOR_NAME, FakeGit, app_client, csrf_for_session, curator_login,
    run, seed_validated,
)

# ---- unit-level guards on the auth primitives -------------------------------------------------


def test_parse_curator_keys_fail_closed_on_unset():
    # Failure criterion: this test fails if an unset/blank key string parses to anything but an error.
    # proven failing 2026-07-06: an early parse returned {} for "" and the caller then treated a
    # gateway with NO curators as "configured but no match" (401) instead of "unconfigured" (503).
    with pytest.raises(curator_auth.CuratorConfigError):
        curator_auth.parse_curator_keys("")
    with pytest.raises(curator_auth.CuratorConfigError):
        curator_auth.parse_curator_keys("   ")


def test_parse_curator_keys_rejects_malformed_and_short():
    with pytest.raises(curator_auth.CuratorConfigError):
        curator_auth.parse_curator_keys("noколон")  # no colon
    with pytest.raises(curator_auth.CuratorConfigError):
        curator_auth.parse_curator_keys("curator1:short")  # key < 16 chars
    with pytest.raises(curator_auth.CuratorConfigError):
        curator_auth.parse_curator_keys("curator1:aaaaaaaaaaaaaaaa,curator1:bbbbbbbbbbbbbbbb")  # dup name
    keys = curator_auth.parse_curator_keys("curator1:this-is-a-long-enough-key-yes")
    assert keys == {"curator1": "this-is-a-long-enough-key-yes"}


def test_match_curator_constant_time_and_correct():
    keys = {"curator1": "k" * 20, "amy": "j" * 20}
    assert curator_auth.match_curator(keys, "k" * 20) == "curator1"
    assert curator_auth.match_curator(keys, "j" * 20) == "amy"
    assert curator_auth.match_curator(keys, "wrong-key-value-0000") is None
    assert curator_auth.match_curator(keys, "") is None


def test_csrf_token_binds_to_session():
    # Failure criterion: fails if the CSRF token is not tied to the session token (i.e. a token from
    # one session validated another) or if a missing token passed.
    a = curator_auth.csrf_token_for("session-a")
    b = curator_auth.csrf_token_for("session-b")
    assert a != b
    assert curator_auth.csrf_ok("session-a", a)
    assert not curator_auth.csrf_ok("session-a", b)
    assert not curator_auth.csrf_ok("session-a", None)
    assert not curator_auth.csrf_ok("session-a", "")


def test_rate_limiter_blocks_after_n_then_clears_on_success():
    lim = curator_auth.LoginRateLimiter(max_attempts=3, window_s=100)
    now = 1000.0
    assert not lim.blocked(now)
    for _ in range(3):
        lim.record_failure(now)
    assert lim.blocked(now)          # blocked after N failures in-window
    assert not lim.blocked(now + 200)  # window rolled off
    for _ in range(3):
        lim.record_failure(now + 300)
    assert lim.blocked(now + 300)
    lim.record_success(now + 300)     # a success clears the counter
    assert not lim.blocked(now + 300)


# ---- route-level guards ------------------------------------------------------------------------


def test_no_session_routes_redirect_or_401(tmp_path):
    # Failure criterion: fails if any curator route serves its content without a session.
    # proven failing 2026-07-06: before _require_session gated the queue, GET /queue rendered the
    # list (with submitter names) to an unauthenticated caller.
    async def _body():
        async with app_client(tmp_path) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg)
            queue = await client.get("/gateway/curator/queue", follow_redirects=False)
            assert queue.status_code == 303  # -> login
            detail = await client.get(f"/gateway/curator/submission/{sid}", follow_redirects=False)
            assert detail.status_code == 303
            # NOTE (revised design §7): the preview SUBTREE is authorized by the unguessable submission
            # id in the path, NOT the session (the null-origin iframe cannot send the cookie). So an
            # unauthenticated request with a VALID id serves the (embargo-safe, PII-scrubbed) preview —
            # see test_curator_preview.py::test_preview_authorized_by_id_not_session. The session gate
            # here covers the queue + detail pages, which DO carry PII.
    run(_body())


def test_wrong_key_401_then_rate_limited(tmp_path):
    # Failure criterion: fails if a wrong key set a session, or if repeated wrong keys were not 429'd.
    # proven failing 2026-07-06: without the limiter, the 6th wrong-key POST still returned 401 (no
    # 429), i.e. brute force was unthrottled.
    async def _body():
        async with app_client(tmp_path, login_max_attempts=3, login_window_s=300) as (client, _app, _gw, _cfg):
            for _ in range(3):
                r = await curator_login(client, key="definitely-wrong-key-1234")
                assert r.status_code == 401
                assert curator_auth.SESSION_COOKIE not in r.cookies
            r = await curator_login(client, key="definitely-wrong-key-1234")
            assert r.status_code == 429  # throttled after N failures
            assert "retry-after" in {k.lower() for k in r.headers}
    run(_body())


def test_valid_login_sets_httponly_samesite_cookie(tmp_path):
    # Failure criterion: fails if the session cookie is missing HttpOnly or SameSite=Strict.
    # proven failing 2026-07-06: an early set_cookie omitted httponly, so the token was readable from
    # page JS (defeating the HttpOnly rationale in design §2).
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, _cfg):
            r = await curator_login(client)
            assert r.status_code == 303
            set_cookie = r.headers.get("set-cookie", "")
            assert curator_auth.SESSION_COOKIE in set_cookie
            low = set_cookie.lower()
            assert "httponly" in low
            assert "samesite=strict" in low
            assert "secure" in low
    run(_body())


def test_expired_session_is_rejected(tmp_path):
    # Failure criterion: fails if a session past its absolute expiry still authenticates.
    # proven failing 2026-07-06: without the expiry check in _session_curator, a row with
    # expires_utc in the past still resolved to the curator name and served the queue.
    async def _body():
        async with app_client(tmp_path) as (client, _app, gw, _cfg):
            await curator_login(client)
            assert (await client.get("/gateway/curator/queue", follow_redirects=False)).status_code == 200
            # Backdate the session row's expiry into the past.
            past = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
            gw.db._conn.execute("UPDATE curator_sessions SET expires_utc = ?", (past,))
            gw.db._conn.commit()
            r = await client.get("/gateway/curator/queue", follow_redirects=False)
            assert r.status_code == 303  # expired -> back to login
    run(_body())


def test_logout_requires_csrf(tmp_path):
    async def _body():
        async with app_client(tmp_path) as (client, _app, gw, _cfg):
            await curator_login(client)
            bad = await client.post("/gateway/curator/logout",
                                    data={"csrf_token": "wrong"}, follow_redirects=False)
            assert bad.status_code == 403
            # Session still valid after the rejected logout.
            assert (await client.get("/gateway/curator/queue", follow_redirects=False)).status_code == 200
            good = await client.post("/gateway/curator/logout",
                                     data={"csrf_token": csrf_for_session(client)},
                                     follow_redirects=False)
            assert good.status_code == 303
    run(_body())


def test_approve_without_csrf_403_no_transition_no_git(tmp_path):
    # THE core CSRF guarantee (design §8): a state-changing POST without the token => 403, NO
    # transition, NO git call.
    # Failure criterion: fails if the submission left VALIDATED, or if the fake git recorded ANY call.
    # proven failing 2026-07-06: disabling the csrf_ok gate in handle_curator_action (if False:)
    # made this approve POST return 303 (not 403) and proceed to PUBLISHING — verified by patching
    # the guard off and observing this exact assertion break.
    async def _body():
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg)
            await curator_login(client)
            r = await client.post(f"/gateway/curator/submission/{sid}/approve",
                                  data={"note": "looks good"}, follow_redirects=False)
            assert r.status_code == 403
            assert gw.db.get(sid).state == states.VALIDATED  # unchanged
            assert git.calls == []                            # no git touched
    run(_body())


def test_fail_closed_when_curator_keys_unset(tmp_path):
    # Failure criterion: fails if a curator route serves anything but 503 when AUSMT_CURATOR_KEYS is
    # unset — you must not be able to reach the queue without a configured curator identity (§2).
    async def _body():
        async with app_client(tmp_path, curator_keys="") as (client, _app, _gw, _cfg):
            root = await client.get("/gateway/curator/", follow_redirects=False)
            assert root.status_code == 503
            login = await curator_login(client)
            assert login.status_code == 503
    run(_body())


def test_login_actor_is_named_in_audit(tmp_path):
    # A successful approve records actor curator:<name> (design §1/§8 audit completeness).
    from gateway.tests.conftest import settle_publish

    async def _body():
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg)
            await curator_login(client)
            await client.post(f"/gateway/curator/submission/{sid}/approve",
                              data={"note": "ok", "csrf_token": csrf_for_session(client)},
                              follow_redirects=False)
            await settle_publish(gw, sid)  # let the background publish settle
            actors = [t["actor"] for t in gw.db.transitions_for(sid)]
            assert f"curator:{CURATOR_NAME}" in actors
    run(_body())


def test_duplicate_key_value_rejected():
    # review #10: two curators sharing a KEY VALUE mis-attribute actions (match returns the last name).
    # Failure criterion: fails if two identical keys parse without error.
    # proven failing 2026-07-06: parse only rejected duplicate NAMES; two names with the same key
    # parsed fine, so an action by 'amy' would be logged as 'curator1' (whichever was configured last).
    import pytest
    with pytest.raises(curator_auth.CuratorConfigError):
        curator_auth.parse_curator_keys("curator1:shared-key-abcdefghij,amy:shared-key-abcdefghij")


def test_rate_limiter_evaluate_is_thread_safe():
    # review #9: the login route is sync `def` (threadpool), so evaluate() must serialize the
    # blocked-check + key-match + record so a burst cannot slip past the cap. Failure criterion: fails
    # if MORE than max_attempts wrong-key evaluations return 'denied' (i.e. reached the key check)
    # within a window when hammered concurrently.
    # proven failing 2026-07-06: with the pre-fix separate blocked()/record_failure() and no lock, a
    # threaded burst of wrong keys nearly all read 'not blocked' and reached the key check before any
    # failure recorded — far more than max_attempts got through.
    import threading

    keys = {"curator1": "k" * 20}
    lim = curator_auth.LoginRateLimiter(max_attempts=5, window_s=1000)
    denied = []
    blocked = []
    barrier = threading.Barrier(40)

    def worker():
        barrier.wait()  # release all 40 threads at once to maximise the race window
        outcome, _ = lim.evaluate(keys, "wrong-key-value-000")
        (denied if outcome == "denied" else blocked).append(1)

    threads = [threading.Thread(target=worker) for _ in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # At most max_attempts wrong keys reached the key check; the rest were refused as blocked.
    assert len(denied) <= 5, f"{len(denied)} attempts slipped past the cap of 5"
    assert len(denied) + len(blocked) == 40


def test_correct_key_blocked_during_window():
    # A blocked window refuses even a CORRECT key (design §6): brute force can't outrun the limiter by
    # occasionally guessing right during the lockout.
    keys = {"curator1": "k" * 20}
    lim = curator_auth.LoginRateLimiter(max_attempts=2, window_s=1000)
    now = 1000.0
    assert lim.evaluate(keys, "bad-key-000000000000", now)[0] == "denied"
    assert lim.evaluate(keys, "bad-key-000000000000", now)[0] == "denied"
    # Now blocked: even the right key is refused.
    assert lim.evaluate(keys, "k" * 20, now)[0] == "blocked"
    # After the window, the right key works.
    assert lim.evaluate(keys, "k" * 20, now + 2000)[0] == "ok"
