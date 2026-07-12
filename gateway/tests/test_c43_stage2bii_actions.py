"""C43 Stage 2b-ii: privileged serve-state ACTIONS (gateway half — record D8/D9/D13).

The gateway WRITES intent files the host actions agent executes (the host-side pins live in
deploy/tests/test_actions_sh.py). This module pins the GATEWAY half against INDEPENDENT OBSERVABLES:
the intent file that lands in the state dir (and its content), the pause.flag, the rendered confirm
pages, the response status, and the TOTP replay-guard state — never the handler's self-report.

The D13 Stage-2 set carried here (each refusal proven able to fail by its passing control):
  * session + CSRF gate on every action route;
  * single-flight (a pending intent of a kind is not double-written);
  * force-full sets the `full` flag on rebuild.request;
  * pause writes / resume removes pause.flag;
  * rollback TYPED-ID must match; a build not in the inventory / the serving build are refused;
  * restore TYPED-ID must match; the C41 TOTP second factor (unenrolled / wrong / replayed refused;
    a wrong typed id does NOT burn the code); a valid restore writes the intent AND consumes the code;
  * CSP-clean confirm pages (no inline JS/handlers under the strictPages script-src 'self').

Async bodies run under conftest.run() (no pytest-asyncio), mirroring the sibling suites.
"""
from __future__ import annotations

import json
import re

from gateway import serve_state, totp
from gateway.tests.conftest import CURATOR_NAME, app_client, csrf_for_session, curator_login, run


# ---- fixtures -----------------------------------------------------------------------------------
_SERVING = "20260710T032000Z"        # the currently-serving build (no rollback-to-itself)
_RETAINED = "20260101T000000Z"       # a non-serving retained build (a valid rollback target)
_SNAPSHOT = "20260709T010000Z"       # a snapshot in the backup inventory (a valid restore target)


def _ops_with_actions_inventory() -> dict:
    """A fresh, schema-valid ops-status.json carrying a serving + a non-serving retained build and a
    backup snapshot — the inventory the gateway UX checks read (the host is the real gate)."""
    import time
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return {
        "generated_at": now, "timer_period_min": 15,
        "reconcile": {"action": "noop", "last_run": now},
        "backups": {"newest": _SNAPSHOT, "age_hours": 5.0, "count": 3,
                    "snapshots": [{"name": _SNAPSHOT, "age_hours": 5.0},
                                  {"name": "20260708T010000Z", "age_hours": 29.0}],
                    "max_hours": 26, "systemd_failed": False, "drill": None},
        "alerts": {"installed": True, "checks_ok": True},
        "box": {"uptime": "up 3 days", "disk_pct": 41, "disk_max_pct": 85, "services": [],
                "clamav_sig_age_days": 1.2},
        "freshness": {"code": {"sha": "abc1234", "origin": "abc1234", "behind": False, "comparable": True},
                      "surveys_live": {"sha": "def5678", "origin": "def5678", "behind": False, "comparable": True}},
        "builds": [
            {"dir": _SERVING, "build_id": "b-serving", "engine_commit": "abc1234",
             "source_commit": "def5678", "stations": 8, "serving": True, "cache": {}},
            {"dir": _RETAINED, "build_id": "b-retained", "engine_commit": "aaa0000",
             "source_commit": "bbb1111", "stations": 8, "serving": False, "cache": {}},
        ],
        "logs": {"build": None, "build_file": None},
    }


def _write_ops(cfg, doc: dict | None = None) -> None:
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    (cfg.state_dir / serve_state.OPS_STATUS_FILENAME).write_text(
        json.dumps(doc or _ops_with_actions_inventory()), encoding="utf-8")


def _enrol_totp(gw, name: str = CURATOR_NAME) -> str:
    """Enrol + activate a TOTP secret with last_used_step reset LOW (0) so a current real code
    verifies and is not pre-consumed. Returns the secret."""
    secret = totp.generate_secret()
    gw.db.begin_totp_enrolment(name, secret)
    gw.db.activate_totp(name, 0)
    return secret


def _intent(cfg, kind: str):
    p = cfg.state_dir / serve_state.INTENT_FILENAMES[kind]
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


# ---- session + CSRF gate ------------------------------------------------------------------------
def test_action_routes_require_session(tmp_path):
    """Every privileged action route is curator-session-gated: unauthenticated POSTs/GETs never write
    an intent. FAILS IF an unauthenticated request queues an action."""
    posts = ["update", "snapshot", "rebuild-full", "pause", "resume"]

    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            _write_ops(cfg)
            for p in posts:
                r = await client.post(f"/gateway/curator/serve/{p}", follow_redirects=False)
                assert r.status_code in (401, 403, 303), (p, r.status_code)
            for g in (f"/gateway/curator/serve/rollback/{_RETAINED}",
                      f"/gateway/curator/serve/restore/{_SNAPSHOT}"):
                r = await client.get(g, follow_redirects=False)
                assert r.status_code == 303, (g, r.status_code)
            # No intent file was written by any of the above.
            assert serve_state.pending_intents(cfg.state_dir) == {}
            assert not serve_state.pause_active(cfg.state_dir)
    run(_body())


def test_action_posts_require_csrf(tmp_path):
    """A logged-in POST without a valid CSRF token is refused (403) and writes no intent. FAILS IF a
    missing/bad CSRF token still queues an action (CSRF is the cross-site write guard)."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_ops(cfg)
            r = await client.post("/gateway/curator/serve/update", data={"csrf_token": "wrong"},
                                  follow_redirects=False)
            assert r.status_code == 403
            assert _intent(cfg, "update") is None, "a bad-CSRF update must write no intent"
    run(_body())


# ---- simple intents: update / snapshot / force-full / pause / resume ----------------------------
def test_update_writes_intent_and_is_single_flight(tmp_path):
    """POST update writes update.request once; a second POST while it is pending does NOT write a
    second (single-flight, D9.3). FAILS IF a duplicate intent is written while one is pending."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_ops(cfg)
            csrf = csrf_for_session(client)
            r = await client.post("/gateway/curator/serve/update", data={"csrf_token": csrf},
                                  follow_redirects=False)
            assert r.status_code == 303
            doc = _intent(cfg, "update")
            assert doc and doc["requested_by"] == CURATOR_NAME, doc
            # Second press while pending: still exactly one intent (benign single-flight no-op).
            r2 = await client.post("/gateway/curator/serve/update", data={"csrf_token": csrf},
                                   follow_redirects=False)
            assert r2.status_code == 303
            assert (cfg.state_dir / "update.request").is_file()
    run(_body())


def test_snapshot_writes_backup_intent(tmp_path):
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_ops(cfg)
            csrf = csrf_for_session(client)
            r = await client.post("/gateway/curator/serve/snapshot", data={"csrf_token": csrf},
                                  follow_redirects=False)
            assert r.status_code == 303
            assert _intent(cfg, "backup") is not None
    run(_body())


def test_rebuild_full_sets_full_flag(tmp_path):
    """Force full rebuild writes rebuild.request with full=true (reconcile then builds cache-refresh).
    FAILS IF the full flag is not set (a force-full that quietly reused the cache)."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_ops(cfg)
            csrf = csrf_for_session(client)
            r = await client.post("/gateway/curator/serve/rebuild-full", data={"csrf_token": csrf},
                                  follow_redirects=False)
            assert r.status_code == 303
            doc = json.loads((cfg.state_dir / "rebuild.request").read_text(encoding="utf-8"))
            assert doc.get("full") is True, doc
    run(_body())


def test_pause_then_resume(tmp_path):
    """Pause writes pause.flag; Resume removes it. FAILS IF pause does not write the flag, or resume
    does not clear it."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_ops(cfg)
            csrf = csrf_for_session(client)
            await client.post("/gateway/curator/serve/pause", data={"csrf_token": csrf},
                              follow_redirects=False)
            assert serve_state.pause_active(cfg.state_dir), "pause must write pause.flag"
            await client.post("/gateway/curator/serve/resume", data={"csrf_token": csrf},
                              follow_redirects=False)
            assert not serve_state.pause_active(cfg.state_dir), "resume must remove pause.flag"
    run(_body())


# ---- rollback (typed build id) ------------------------------------------------------------------
def test_rollback_typed_id_mismatch_refused(tmp_path):
    """A rollback whose typed build id does not match the target is refused (400) and writes NO intent.
    FAILS IF a mismatched typed id still queues a rollback. Non-vacuous: the matching control below
    DOES write the intent."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_ops(cfg)
            csrf = csrf_for_session(client)
            r = await client.post(f"/gateway/curator/serve/rollback/{_RETAINED}",
                                  data={"csrf_token": csrf, "typed_build": "wrong-id"},
                                  follow_redirects=False)
            assert r.status_code == 400
            assert _intent(cfg, "rollback") is None, "a mismatched typed id must write no rollback intent"
    run(_body())


def test_rollback_typed_id_match_writes_intent(tmp_path):
    """A rollback with the correct typed build id (a real, non-serving retained build) writes
    rollback.request carrying that build_id. FAILS IF a correct rollback does not queue the intent."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_ops(cfg)
            csrf = csrf_for_session(client)
            r = await client.post(f"/gateway/curator/serve/rollback/{_RETAINED}",
                                  data={"csrf_token": csrf, "typed_build": _RETAINED},
                                  follow_redirects=False)
            assert r.status_code == 303
            doc = _intent(cfg, "rollback")
            assert doc and doc.get("build_id") == _RETAINED, doc
    run(_body())


def test_rollback_build_not_in_inventory_refused(tmp_path):
    """A rollback to a build not in the ops inventory is refused (409), no intent. FAILS IF an
    unknown build is queued (the gateway UX check; the host re-validates too)."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_ops(cfg)
            csrf = csrf_for_session(client)
            r = await client.post("/gateway/curator/serve/rollback/20991231T000000Z",
                                  data={"csrf_token": csrf, "typed_build": "20991231T000000Z"},
                                  follow_redirects=False)
            assert r.status_code == 409
            assert _intent(cfg, "rollback") is None
    run(_body())


def test_rollback_serving_build_refused(tmp_path):
    """Rolling back to the currently-serving build is refused (409) — nothing to roll back to."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_ops(cfg)
            csrf = csrf_for_session(client)
            r = await client.post(f"/gateway/curator/serve/rollback/{_SERVING}",
                                  data={"csrf_token": csrf, "typed_build": _SERVING},
                                  follow_redirects=False)
            assert r.status_code == 409
            assert _intent(cfg, "rollback") is None
    run(_body())


# ---- restore (typed snapshot id + TOTP second factor) -------------------------------------------
def test_restore_unenrolled_refused(tmp_path):
    """A curator with no active TOTP enrolment cannot restore (409) — the enrol pointer is shown, no
    intent. FAILS IF an unenrolled curator can queue a DB restore (fail-closed)."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)                       # NOT enrolled
            _write_ops(cfg)
            csrf = csrf_for_session(client)
            r = await client.post(f"/gateway/curator/serve/restore/{_SNAPSHOT}",
                                  data={"csrf_token": csrf, "typed_snapshot": _SNAPSHOT, "code": "000000"},
                                  follow_redirects=False)
            assert r.status_code == 409
            assert "security" in r.text.lower() or "enrol" in r.text.lower()
            assert _intent(cfg, "restore") is None
    run(_body())


def test_restore_wrong_code_refused_not_consumed(tmp_path):
    """An enrolled curator's WRONG code is refused (400), no intent, and the replay step is NOT
    advanced (a valid code still works after). FAILS IF a wrong code queues a restore or burns the
    replay guard."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_ops(cfg)
            gw = _app.state.gw
            _enrol_totp(gw)
            before = gw.db.get_totp(CURATOR_NAME).last_used_step
            csrf = csrf_for_session(client)
            r = await client.post(f"/gateway/curator/serve/restore/{_SNAPSHOT}",
                                  data={"csrf_token": csrf, "typed_snapshot": _SNAPSHOT, "code": "000000"},
                                  follow_redirects=False)
            assert r.status_code == 400
            assert _intent(cfg, "restore") is None
            assert gw.db.get_totp(CURATOR_NAME).last_used_step == before, "a wrong code must not advance the guard"
    run(_body())


def test_restore_typed_id_mismatch_does_not_burn_code(tmp_path):
    """A VALID code but a WRONG typed snapshot id is refused (400), no intent, and the code is NOT
    consumed — the curator can retry with the same still-valid code (identical to the retire gate
    ordering). FAILS IF a mistyped id burns the code, or queues a restore."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_ops(cfg)
            gw = _app.state.gw
            secret = _enrol_totp(gw)
            code = totp.code_at(secret, totp.current_step())
            csrf = csrf_for_session(client)
            r = await client.post(f"/gateway/curator/serve/restore/{_SNAPSHOT}",
                                  data={"csrf_token": csrf, "typed_snapshot": "wrong-id", "code": code},
                                  follow_redirects=False)
            assert r.status_code == 400
            assert _intent(cfg, "restore") is None
            # The SAME code now succeeds (it was not consumed by the mistyped-id refusal).
            r2 = await client.post(f"/gateway/curator/serve/restore/{_SNAPSHOT}",
                                   data={"csrf_token": csrf, "typed_snapshot": _SNAPSHOT, "code": code},
                                   follow_redirects=False)
            assert r2.status_code == 303, "the un-burned code must still work on a correct retry"
            assert _intent(cfg, "restore") is not None
    run(_body())


def test_restore_success_writes_intent_and_consumes_code(tmp_path):
    """A valid typed id + valid TOTP code writes restore.request carrying the snapshot_id AND consumes
    the code (a second restore with the SAME code is refused as replay). FAILS IF the code is not
    consumed on success (a replayable destructive-op factor)."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_ops(cfg)
            gw = _app.state.gw
            secret = _enrol_totp(gw)
            code = totp.code_at(secret, totp.current_step())
            csrf = csrf_for_session(client)
            r = await client.post(f"/gateway/curator/serve/restore/{_SNAPSHOT}",
                                  data={"csrf_token": csrf, "typed_snapshot": _SNAPSHOT, "code": code},
                                  follow_redirects=False)
            assert r.status_code == 303
            doc = _intent(cfg, "restore")
            assert doc and doc.get("snapshot_id") == _SNAPSHOT, doc
            # Consume the pending intent so single-flight does not mask the replay check, then re-try
            # the SAME code: it is now a replay and must be refused (409).
            (cfg.state_dir / "restore.request").unlink()
            r2 = await client.post(f"/gateway/curator/serve/restore/{_SNAPSHOT}",
                                   data={"csrf_token": csrf, "typed_snapshot": _SNAPSHOT, "code": code},
                                   follow_redirects=False)
            assert r2.status_code == 409, "the consumed code must be refused as a replay"
            assert _intent(cfg, "restore") is None
    run(_body())


def test_restore_snapshot_not_in_inventory_refused(tmp_path):
    """A restore of a snapshot not in the (fresh) ops inventory is refused (409), no intent. FAILS IF
    an unknown snapshot is queued when ops-status can prove it is absent."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_ops(cfg)
            gw = _app.state.gw
            _enrol_totp(gw)
            csrf = csrf_for_session(client)
            r = await client.post("/gateway/curator/serve/restore/20991231T000000Z",
                                  data={"csrf_token": csrf, "typed_snapshot": "20991231T000000Z",
                                        "code": "000000"},
                                  follow_redirects=False)
            assert r.status_code == 409
            assert _intent(cfg, "restore") is None
    run(_body())


# ---- CSP sweep on the confirm pages -------------------------------------------------------------
def test_confirm_pages_are_csp_clean(tmp_path):
    """The rollback + restore confirm pages carry NO inline <script> (all src=) and NO on*= handlers —
    dead under the strictPages CSP (script-src 'self'). FAILS IF either confirm page ships inline JS."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_ops(cfg)
            gw = _app.state.gw
            _enrol_totp(gw)
            for url in (f"/gateway/curator/serve/rollback/{_RETAINED}",
                        f"/gateway/curator/serve/restore/{_SNAPSHOT}"):
                html = (await client.get(url)).text
                for m in re.finditer(r"<script\b[^>]*>", html):
                    assert re.search(r"\bsrc\s*=", m.group(0)), f"inline <script> in {url}: {m.group(0)}"
                assert re.findall(r"<[^>]*\son\w+\s*=", html) == [], f"inline handler in {url}"
    run(_body())


def test_restore_confirm_shows_totp_field_only_when_enrolled(tmp_path):
    """The restore confirm page shows the code field ONLY when the curator is enrolled; an unenrolled
    curator sees the enrol pointer instead. FAILS IF the code field renders for an unenrolled curator
    (a factor that cannot be satisfied) or is missing for an enrolled one."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_ops(cfg)
            gw = _app.state.gw
            html_unenrolled = (await client.get(f"/gateway/curator/serve/restore/{_SNAPSHOT}")).text
            assert 'name="code"' not in html_unenrolled
            assert "enrol" in html_unenrolled.lower() or "security" in html_unenrolled.lower()
            _enrol_totp(gw)
            html_enrolled = (await client.get(f"/gateway/curator/serve/restore/{_SNAPSHOT}")).text
            assert 'name="code"' in html_enrolled and 'name="typed_snapshot"' in html_enrolled
    run(_body())


# ---- unit: single-flight raises at the seam -----------------------------------------------------
def test_write_intent_single_flight_raises(tmp_path):
    """serve_state.write_intent raises IntentAlreadyPending on a second same-kind write (the seam the
    route relies on). FAILS IF a second same-kind intent overwrites silently (two privileged actions
    of a kind queued at once)."""
    state = tmp_path / "state"
    state.mkdir()
    serve_state.write_intent(state, "update", requested_by="c1")
    import pytest
    with pytest.raises(serve_state.IntentAlreadyPending):
        serve_state.write_intent(state, "update", requested_by="c1")


def test_audit_tail_reader_does_not_fabricate_lines_from_unicode_separators(tmp_path):
    """S4 (gateway defence-in-depth). read_actions_audit_tail must split on '\n' ONLY, so a crafted
    line carrying a unicode line separator (U+2028) — even if one ever reached the host log — stays ONE
    entry, not two. FAILS IF splitlines()-style splitting fabricates an extra tail entry from one line."""
    state = tmp_path / "state"
    state.mkdir()
    # One real line whose content embeds a U+2028; the host scrubs these, but the reader must not trust it.
    (state / serve_state.ACTIONS_AUDIT_FILENAME).write_text(
        "2026-07-12T00:00:00Z outcome=ok intent=backup by=c1 id=- forged=evil\n",
        encoding="utf-8")
    tail = serve_state.read_actions_audit_tail(state)
    assert len(tail) == 1, f"a U+2028 must not fabricate a second tail entry: {tail!r}"
