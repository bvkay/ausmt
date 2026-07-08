"""C40 serve-reconcile gateway half: the curator "request rebuild" button + the serve-state panel.

The button writes the zero-argument rebuild.request the host reconcile agent consumes; the panel
shows published HEAD vs served build, the last reconcile outcome, and a pending indicator. This file
proves the gateway half against INDEPENDENT OBSERVABLES (the request file on disk + its parsed JSON,
the response status, the rendered HTML), mirroring test_uploader_keys.py's structure.

Failure criterion is in each test's docstring (Invariant 10). Async bodies run under conftest.run()
(no pytest-asyncio), the established gateway pattern.
"""
from __future__ import annotations

import json

from gateway import serve_state
from gateway.publish import GitResult
from gateway.tests.conftest import (
    CURATOR_NAME, app_client, csrf_for_session, curator_login, run,
)


# ---- unit: serve_state helpers -----------------------------------------------------------------

def test_write_rebuild_request_atomic_and_audited(tmp_path):
    """write_rebuild_request lands a valid {requested_at, requested_by} JSON file and leaves NO .tmp
    behind (atomic replace). FAILS IF: the content is malformed, requested_by is not recorded, or a
    temp file is orphaned."""
    state = tmp_path / "state"
    state.mkdir()
    path = serve_state.write_rebuild_request(state, requested_by="curator-x")
    assert path.name == serve_state.REQUEST_FILENAME
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["requested_by"] == "curator-x"
    assert doc["requested_at"].endswith("Z")
    assert list(state.glob("*.tmp*")) == [], "no temp file may survive the atomic write"


def test_write_rebuild_request_overwrites_idempotent(tmp_path):
    """A second write overwrites the same single file (design: pressing twice = one file). FAILS IF:
    repeated requests accumulate multiple files."""
    state = tmp_path / "state"
    state.mkdir()
    serve_state.write_rebuild_request(state, requested_by="a")
    serve_state.write_rebuild_request(state, requested_by="b")
    files = list(state.glob("rebuild.request*"))
    assert len(files) == 1
    assert json.loads(files[0].read_text(encoding="utf-8"))["requested_by"] == "b"


def test_write_rebuild_request_missing_dir_fails_closed(tmp_path):
    """Writing under a non-existent state dir raises StateDirUnwritable (=> the route 503s). FAILS IF:
    a missing dir is silently created or swallowed, so a button press reports success but queues
    nothing."""
    import pytest
    missing = tmp_path / "nope"
    with pytest.raises(serve_state.StateDirUnwritable):
        serve_state.write_rebuild_request(missing, requested_by="x")


def test_read_reconcile_status_absent_and_malformed(tmp_path):
    """read_reconcile_status returns None for an absent OR malformed status file — never raises.
    FAILS IF: a broken status file propagates an exception (which would 500 the curator page)."""
    state = tmp_path / "state"
    state.mkdir()
    assert serve_state.read_reconcile_status(state) is None
    (state / serve_state.STATUS_FILENAME).write_text("{not json", encoding="utf-8")
    assert serve_state.read_reconcile_status(state) is None
    (state / serve_state.STATUS_FILENAME).write_text('{"action": "noop"}', encoding="utf-8")
    assert serve_state.read_reconcile_status(state)["action"] == "noop"


def test_read_published_head_unavailable_on_git_error(tmp_path):
    """read_published_head degrades to available=False on a git failure and on a None surveys_live —
    never raises. FAILS IF: a git error surfaces as an exception (500 on the page) instead of an
    'unavailable' state."""
    def boom(_args, *, cwd, env=None):
        raise RuntimeError("git not here")
    assert serve_state.read_published_head(boom, tmp_path).available is False
    assert serve_state.read_published_head(boom, None).available is False

    def bad_rc(_args, *, cwd, env=None):
        return GitResult(returncode=128, stdout="", stderr="not a git repo")
    assert serve_state.read_published_head(bad_rc, tmp_path).available is False

    def ok(_args, *, cwd, env=None):
        return GitResult(returncode=0, stdout="abc1234\n", stderr="")
    got = serve_state.read_published_head(ok, tmp_path)
    assert got.available is True and got.short == "abc1234"


# ---- route: POST /gateway/curator/rebuild ------------------------------------------------------

def test_rebuild_requires_session(tmp_path):
    """POST /gateway/curator/rebuild without a curator session is 401 and writes nothing. FAILS IF:
    an unauthenticated request can queue a rebuild."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            r = await client.post("/gateway/curator/rebuild",
                                  data={"csrf_token": "whatever"}, follow_redirects=False)
            assert r.status_code == 401
            assert not (cfg.state_dir / serve_state.REQUEST_FILENAME).exists()
    run(_body())


def test_rebuild_requires_csrf(tmp_path):
    """POST with a session but a bad CSRF token is 403 and writes nothing. FAILS IF: a cross-site
    form can trigger a rebuild."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            r = await client.post("/gateway/curator/rebuild",
                                  data={"csrf_token": "wrong"}, follow_redirects=False)
            assert r.status_code == 403
            assert not (cfg.state_dir / serve_state.REQUEST_FILENAME).exists()
    run(_body())


def test_rebuild_success_writes_valid_request_and_redirects(tmp_path):
    """A valid session + CSRF writes a well-formed rebuild.request attributed to the curator and
    redirects (303) back to the queue's serve-state section. FAILS IF: the file is absent/malformed,
    the curator is not recorded, or the response is not a redirect."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            r = await client.post("/gateway/curator/rebuild",
                                  data={"csrf_token": csrf_for_session(client)},
                                  follow_redirects=False)
            assert r.status_code == 303
            assert "/gateway/curator/queue" in r.headers.get("location", "")
            req = cfg.state_dir / serve_state.REQUEST_FILENAME
            assert req.exists()
            doc = json.loads(req.read_text(encoding="utf-8"))
            assert doc["requested_by"] == CURATOR_NAME
            assert doc["requested_at"].endswith("Z")
    run(_body())


def test_rebuild_repeat_post_overwrites_single_file(tmp_path):
    """Two presses leave exactly ONE request file (idempotent). FAILS IF: repeated posts accumulate
    multiple request files (a storm the host agent would then process one-per-tick, but the contract
    is one file)."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            await client.post("/gateway/curator/rebuild", data={"csrf_token": csrf},
                              follow_redirects=False)
            await client.post("/gateway/curator/rebuild", data={"csrf_token": csrf},
                              follow_redirects=False)
            assert len(list(cfg.state_dir.glob("rebuild.request*"))) == 1
    run(_body())


def test_rebuild_unwritable_state_dir_503(tmp_path):
    """If the state dir cannot be written, the route fails CLOSED with a 503 rather than pretending
    the rebuild was queued. FAILS IF: an unwritable state dir yields a success/redirect (a silent
    dropped request the curator believes succeeded)."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, gw, _cfg):
            await curator_login(client)
            # Force the write to fail closed by pointing the helper at a missing dir via monkeypatch
            # of the write path — the cleanest deterministic unwritable condition cross-platform (a
            # chmod-based read-only dir is unreliable on Windows).
            import gateway.serve_state as ss
            orig = ss.write_rebuild_request
            def _boom(state_dir, *, requested_by):
                raise ss.StateDirUnwritable("simulated unwritable state dir")
            ss.write_rebuild_request = _boom
            try:
                r = await client.post("/gateway/curator/rebuild",
                                      data={"csrf_token": csrf_for_session(client)},
                                      follow_redirects=False)
            finally:
                ss.write_rebuild_request = orig
            assert r.status_code == 503
    run(_body())


# ---- panel rendering on the queue page ---------------------------------------------------------

def test_queue_panel_renders_without_status(tmp_path):
    """With no reconcile-status.json the queue page still renders the serve-state panel and shows the
    "agent not installed" hint + the browser-fetch placeholders + the rebuild button. FAILS IF: the
    panel is missing, or a missing status file breaks the page."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get("/gateway/curator/queue")
            assert r.status_code == 200
            assert 'id="serve-state"' in r.text
            assert "reconcile agent is not installed" in r.text or "not installed" in r.text
            assert "/data/build.json" in r.text and "/data/build_report.json" in r.text
            assert "Request rebuild" in r.text
    run(_body())


def test_queue_panel_renders_status_and_pending(tmp_path):
    """With a status file present AND a pending rebuild.request, the panel shows the last outcome and
    the pending indicator. FAILS IF: the panel does not surface the reconcile action, or the pending
    flag is not shown when a request file exists (the curator would not know a rebuild is queued)."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            cfg.state_dir.mkdir(parents=True, exist_ok=True)
            (cfg.state_dir / serve_state.STATUS_FILENAME).write_text(json.dumps({
                "last_run": "2026-07-08T00:00:00Z", "action": "rebuilt",
                "head": "abc1234", "built": "abc1234", "build_id": "bid-9",
                "log_file": "/x/y.build.log", "log_tail": None}), encoding="utf-8")
            (cfg.state_dir / serve_state.REQUEST_FILENAME).write_text("{}", encoding="utf-8")
            await curator_login(client)
            r = await client.get("/gateway/curator/queue")
            assert r.status_code == 200
            assert "rebuilt" in r.text
            assert "2026-07-08T00:00:00Z" in r.text
            assert "pending the next reconcile tick" in r.text.lower()
    run(_body())


def test_queue_panel_failed_shows_log_tail(tmp_path):
    """A failed reconcile shows the log tail so a shell-less curator sees WHY the last build did not
    serve. FAILS IF: a failed status hides the log tail (the NCI no-console requirement)."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            cfg.state_dir.mkdir(parents=True, exist_ok=True)
            (cfg.state_dir / serve_state.STATUS_FILENAME).write_text(json.dumps({
                "last_run": "2026-07-08T00:00:00Z", "action": "failed",
                "head": "abc1234", "built": "def5678", "build_id": None,
                "log_file": "/x/y.build.log",
                "log_tail": "VERIFY FAILED -- current left untouched"}), encoding="utf-8")
            await curator_login(client)
            r = await client.get("/gateway/curator/queue")
            assert r.status_code == 200
            assert "failed" in r.text
            assert "VERIFY FAILED" in r.text, "a failed reconcile must surface its log tail"
    run(_body())


def test_queue_panel_published_head_via_git_seam(tmp_path):
    """The panel's server-side published HEAD comes from the injected git seam (the publish flow's
    runner). With a seam returning a known short sha, the page shows it; with a failing seam it shows
    'unavailable' and does NOT 500. FAILS IF: the git seam result is not reflected, or a git error
    500s the queue page."""
    async def _body():
        # Seam that returns a fixed HEAD for rev-parse.
        def good_git(args, *, cwd, env=None):
            if args[:1] == ["rev-parse"]:
                return GitResult(returncode=0, stdout="feed123\n", stderr="")
            return GitResult(returncode=0, stdout="", stderr="")
        async with app_client(tmp_path, git_runner=good_git) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get("/gateway/curator/queue")
            assert r.status_code == 200
            assert "feed123" in r.text

        def bad_git(args, *, cwd, env=None):
            return GitResult(returncode=128, stdout="", stderr="dubious ownership")
        async with app_client(tmp_path, git_runner=bad_git) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get("/gateway/curator/queue")
            assert r.status_code == 200  # never 500
            assert "unavailable" in r.text
    run(_body())
