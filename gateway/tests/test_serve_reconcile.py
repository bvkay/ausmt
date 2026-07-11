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
    redirects (303) to the SERVE-STATE screen's panel. C43 FR2-1 (owner ruling, ratified 2026-07-11)
    moved the serve panel off the queue page to /gateway/curator/serve, so the redirect follows it
    there — that is where the curator now sees the 'rebuild requested — pending' state. FAILS IF: the
    file is absent/malformed, the curator is not recorded, or the response is not a redirect to the
    serve screen."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            r = await client.post("/gateway/curator/rebuild",
                                  data={"csrf_token": csrf_for_session(client)},
                                  follow_redirects=False)
            assert r.status_code == 303
            assert "/gateway/curator/serve" in r.headers.get("location", "")
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


# ---- panel rendering on the SERVE-STATE screen -------------------------------------------------
# C43 FR2-1 (owner ruling, ratified 2026-07-11): the serve-state panel was REMOVED from the queue page
# — the dedicated /gateway/curator/serve screen (which embeds render_serve_panel) + the ever-present
# drift chip own the served-vs-published job now. These panel-render pins MOVE with the panel to its
# new home /serve (checked against test_c43_stage2b_ops.py: that file pins the ops floor / sync strip
# / build detail but NOT the panel's serve-state id, the not-installed hint, serve-state.js, the
# pending indicator, or the reconcile log tail — so these are not duplicated and are retargeted, not
# deleted). The queue page is proven pure-queue by test_queue_page_is_pure_queue below.

def test_serve_panel_renders_without_status(tmp_path):
    """With no reconcile-status.json the SERVE screen still renders the serve-state panel and shows the
    "agent not installed" hint + the browser-fetch placeholders + the rebuild button. FAILS IF: the
    panel is missing, or a missing status file breaks the page."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get("/gateway/curator/serve")
            assert r.status_code == 200
            assert 'id="serve-state"' in r.text
            assert "reconcile agent is not installed" in r.text or "not installed" in r.text
            # The /data/build*.json fetches live in the EXTERNAL panel script now (CSP: inline JS is
            # dead under script-src 'self'); the page must reference that script, and the script
            # route itself is covered by test_serve_state_js_route_serves_the_panel_script.
            assert 'src="/gateway/curator/serve-state.js"' in r.text
            assert "Request rebuild" in r.text
    run(_body())


def test_serve_panel_renders_status_and_pending(tmp_path):
    """With a status file present AND a pending rebuild.request, the SERVE screen's panel shows the
    last outcome and the pending indicator. FAILS IF: the panel does not surface the reconcile action,
    or the pending flag is not shown when a request file exists (the curator would not know a rebuild
    is queued)."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            cfg.state_dir.mkdir(parents=True, exist_ok=True)
            (cfg.state_dir / serve_state.STATUS_FILENAME).write_text(json.dumps({
                "last_run": "2026-07-08T00:00:00Z", "action": "rebuilt",
                "head": "abc1234", "built": "abc1234", "build_id": "bid-9",
                "log_file": "/x/y.build.log", "log_tail": None}), encoding="utf-8")
            (cfg.state_dir / serve_state.REQUEST_FILENAME).write_text("{}", encoding="utf-8")
            await curator_login(client)
            r = await client.get("/gateway/curator/serve")
            assert r.status_code == 200
            assert "rebuilt" in r.text
            assert "2026-07-08T00:00:00Z" in r.text
            assert "pending the next reconcile tick" in r.text.lower()
    run(_body())


def test_serve_panel_failed_shows_log_tail(tmp_path):
    """A failed reconcile shows the log tail on the SERVE screen so a shell-less curator sees WHY the
    last build did not serve. FAILS IF: a failed status hides the log tail (the NCI no-console
    requirement)."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            cfg.state_dir.mkdir(parents=True, exist_ok=True)
            (cfg.state_dir / serve_state.STATUS_FILENAME).write_text(json.dumps({
                "last_run": "2026-07-08T00:00:00Z", "action": "failed",
                "head": "abc1234", "built": "def5678", "build_id": None,
                "log_file": "/x/y.build.log",
                "log_tail": "VERIFY FAILED -- current left untouched"}), encoding="utf-8")
            await curator_login(client)
            r = await client.get("/gateway/curator/serve")
            assert r.status_code == 200
            assert "failed" in r.text
            assert "VERIFY FAILED" in r.text, "a failed reconcile must surface its log tail"
    run(_body())


def test_published_head_via_git_seam_on_shell_and_serve(tmp_path):
    """The server-side published HEAD comes from the injected git seam (the publish flow's runner). It
    is surfaced on EVERY shelled page by the context-bar drift chip AND on the serve screen's panel;
    with a seam returning a known short sha the page shows it, with a failing seam it shows
    'unavailable' and does NOT 500. (C43 FR2-1: the queue no longer carries the panel, but the drift
    chip carries the published HEAD hub-wide, so the queue page still reflects the seam.) FAILS IF: the
    git seam result is not reflected, or a git error 500s the page."""
    async def _body():
        # Seam that returns a fixed HEAD for rev-parse.
        def good_git(args, *, cwd, env=None):
            if args[:1] == ["rev-parse"]:
                return GitResult(returncode=0, stdout="feed123\n", stderr="")
            return GitResult(returncode=0, stdout="", stderr="")
        async with app_client(tmp_path, git_runner=good_git) as (client, _app, _gw, _cfg):
            await curator_login(client)
            for url in ("/gateway/curator/queue", "/gateway/curator/serve"):
                r = await client.get(url)
                assert r.status_code == 200, url
                assert "feed123" in r.text, url

        def bad_git(args, *, cwd, env=None):
            return GitResult(returncode=128, stdout="", stderr="dubious ownership")
        async with app_client(tmp_path, git_runner=bad_git) as (client, _app, _gw, _cfg):
            await curator_login(client)
            for url in ("/gateway/curator/queue", "/gateway/curator/serve"):
                r = await client.get(url)
                assert r.status_code == 200, url  # never 500
                assert "unavailable" in r.text, url
    run(_body())


# ---- CSP delivery + the queue-is-pure-queue invariant (strictPages blocks inline) ---------------

def test_queue_page_is_pure_queue_and_csp_clean(tmp_path):
    """C43 FR2-1 + CSP PIN. The queue page is PURELY the queue now (owner ruling, ratified
    2026-07-11): the inline serve-state panel is GONE — it does NOT reference serve-state.js and
    carries no serve-state panel id (that job moved to /gateway/curator/serve + the drift chip). It
    still carries the shared UI script and stays CSP-clean: Caddy serves every /gateway/* page under
    script-src 'self', so inline <script> blocks and inline on*= handlers are silently BLOCKED and any
    inline JS is dead code that only fails in production. FAILS IF: the serve panel leaks back onto the
    queue, or anyone re-inlines a script / adds an onclick-style attribute."""
    import re
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get("/gateway/curator/queue")
            assert r.status_code == 200
            html = r.text
            for m in re.finditer(r"<script\b[^>]*>", html):
                assert re.search(r"\bsrc\s*=", m.group(0)), \
                    f"inline <script> is dead under the CSP: {m.group(0)}"
            # The serve panel and its script must NOT be on the queue anymore (moved to /serve).
            assert 'src="/gateway/curator/serve-state.js"' not in html, \
                "the serve-state panel script must not ride the pure-queue page (it moved to /serve)"
            assert 'id="serve-state"' not in html, "the serve-state panel must be gone from the queue"
            assert 'src="/gateway/curator/ui.js"' in html
            handlers = re.findall(r"<[^>]*\son\w+\s*=", html)
            assert handlers == [], f"inline event handlers are dead under the CSP: {handlers}"
    run(_body())
    run(_body())


def test_no_page_renderer_emits_inline_handlers_or_scripts():
    """SOURCE-LEVEL CSP SWEEP: no gateway HTML-emitting module may contain an inline event-handler
    attribute (ANY on*= — onerror/ontoggle/onkeydown included, review S3) or an inline <script>
    block without src= (review S2) — all are dead under the strictPages CSP. Three handlers shipped
    that way and silently never ran until 2026-07-08; behaviours belong in CURATOR_UI_JS's
    data-attribute delegation and scripts belong behind the external routes. FAILS IF: a new inline
    handler or inline script block lands in any listed module — or a listed module is renamed away
    (coverage must fail loudly, not silently narrow)."""
    import re
    from pathlib import Path
    pkg = Path(__file__).resolve().parents[1]
    offenders = []
    for name in ("curatorpage.py", "metaedit.py", "statuspage.py", "uploader_keys.py", "app.py"):
        p = pkg / name
        assert p.exists(), f"CSP sweep target vanished (renamed?): {name} — update this sweep"
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"""\bon[a-z]{3,}\s*=\s*['"\\]""", line):
                offenders.append(f"{name}:{i} (handler): {line.strip()[:90]}")
            if re.search(r"<script(?![^>]*\bsrc\s*=)[^>]*>", line):
                offenders.append(f"{name}:{i} (inline <script>): {line.strip()[:90]}")
    assert offenders == [], "inline JS is dead under the CSP:\n" + "\n".join(offenders)


def test_c43_external_js_constants_are_raw_and_referenced_externally():
    """C43 Stage-1 CSP coverage (record D13): the new nav-shell + survey-hub behaviours ship as
    EXTERNAL route constants (script-src 'self' kills inline), and the pages that use them reference
    them by external <script src=…>, never inline. FAILS IF a C43 JS constant is removed/renamed
    (coverage silently narrows) or a page inlines its script instead of referencing the route. This
    NAMES the C43 constants so their coverage cannot quietly vanish."""
    import re
    from pathlib import Path

    from gateway import curatorpage
    # The new C43 external JS constants exist and are RAW JS (no <script> wrapper, no on*= handler).
    for const_name in ("CONTEXT_BAR_JS", "SURVEY_HUB_JS"):
        js = getattr(curatorpage, const_name)
        assert isinstance(js, str) and js.strip(), f"{const_name} vanished or empty"
        assert "<script" not in js, f"{const_name} must be raw JS, not <script>-wrapped"
        assert not re.search(r"""\bon[a-z]{3,}\s*=\s*['"]""", js), \
            f"{const_name} uses an inline on*= handler (dead under CSP) — use addEventListener"
    # The shell + hub reference the routes externally (src=), never inline.
    src = (Path(curatorpage.__file__)).read_text(encoding="utf-8")
    assert 'src="/gateway/curator/context-bar.js"' in src
    assert 'src="/gateway/curator/survey-hub.js"' in src


def test_rendered_forms_carry_the_delegated_data_attributes():
    """S1 PIN: the delegated behaviours only work if the RENDERED markup carries the data
    attributes — reverting them regresses silently otherwise (ui.js keeps serving handlers nothing
    triggers). Rendered where cheap (the serve panel), source-literal where the renderer needs a
    full fixture graph (Reject / Revoke / toggle). FAILS IF: any of the four migrated sites loses
    its data attribute in a refactor."""
    from pathlib import Path

    from gateway import curatorpage
    panel = curatorpage.render_serve_panel(
        published_head="abc1234", published_available=True, status=None, pending=False,
        csrf_token="tok")
    assert 'data-confirm="Request a rebuild on the next reconcile tick?"' in panel
    src = (Path(curatorpage.__file__)).read_text(encoding="utf-8")
    assert 'data-confirm="Reject this submission?"' in src
    assert 'data-confirm="Revoke this uploader key? This cannot be undone."' in src
    assert 'data-toggle-big="prev"' in src


def test_serve_state_js_route_serves_the_panel_script(tmp_path):
    """GET /gateway/curator/serve-state.js with a session returns the panel JS (javascript content
    type; contains the panel hooks); without a session it redirects to login (same gate as the
    page). FAILS IF: the route 404s (the page would load with no JS — 'Loading…' forever), serves
    the wrong content type, or is reachable without the session gate the rest of /gateway/curator
    has."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, _cfg):
            r_anon = await client.get("/gateway/curator/serve-state.js", follow_redirects=False)
            assert r_anon.status_code == 303, "unauthenticated must redirect to login like the page"
            await curator_login(client)
            r = await client.get("/gateway/curator/serve-state.js")
            assert r.status_code == 200
            assert "javascript" in r.headers["content-type"]
            assert "serve-state" in r.text and "build_report.json" in r.text
            assert "<script" not in r.text, "the route serves RAW JS, not an HTML-wrapped block"
    run(_body())


def test_ui_js_route_serves_shared_behaviours(tmp_path):
    """GET /gateway/curator/ui.js (loaded by EVERY curator page via the shell, INCLUDING the
    pre-session login page) returns the shared delegation JS: the data-confirm submit guard
    (Rebuild/Reject/Revoke confirms ride it) and the data-toggle-big click handler (the preview
    size toggle). Deliberately UNGATED (review C2): a session gate here 303s the login page's own
    script fetch into a nosniff console error on every login view; the content is a static
    public-repo constant. FAILS IF: the route 404s (every confirm/toggle silently dies again, the
    pre-2026-07-08 state), lacks either delegated behaviour, or regains a gate that breaks the
    login page."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, _cfg):
            r_anon = await client.get("/gateway/curator/ui.js", follow_redirects=False)
            assert r_anon.status_code == 200, "ui.js must be reachable pre-session (login page loads it)"
            assert "javascript" in r_anon.headers["content-type"]
            assert "data-confirm" in r_anon.text and "confirm(" in r_anon.text
            assert "data-toggle-big" in r_anon.text
            assert "<script" not in r_anon.text
    run(_body())
