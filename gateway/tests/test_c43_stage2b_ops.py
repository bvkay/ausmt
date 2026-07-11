"""C43 S2b-i: serve-state screen + operations floor (gateway half — record D8/D15).

The consumer side of the ops floor: the gateway reads ops-status.json SERVER-side (the
reconcile-status.json seam — serve_state.read_ops_status) and renders the first-class serve screen +
the read-only build-detail view. These pins prove the load-bearing behaviours against INDEPENDENT
OBSERVABLES (the rendered HTML, the staleness function's boolean, the response status), mirroring
test_serve_reconcile.py. Async bodies run under conftest.run() (no pytest-asyncio).

Failure criterion in each docstring (Invariant 10). No new skips — pure gateway stack.
"""
from __future__ import annotations

import calendar
import json
import re
import time

from gateway import curatorpage, serve_state
from gateway.tests.conftest import app_client, curator_login, run

_WARN = curatorpage._PALETTE["warn"]  # noqa: SLF001 -- the amber colour the freshness pin asserts on


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _fresh_ops(**over) -> dict:
    """A schema-valid, FRESH ops-status.json (generated now, healthy across the board). Individual
    tests override one top-level block to drive a single card/condition."""
    now = _now_iso()
    doc = {
        "generated_at": now, "timer_period_min": 15,
        "reconcile": {"action": "noop", "last_run": now, "sync_failed": False,
                      "sync_failed_streak": 0, "sync_failed_since": None},
        "backups": {"newest": "20260710T032000Z", "age_hours": 5.0, "count": 14,
                    "snapshots": [{"name": "20260710T032000Z", "age_hours": 5.0}],
                    "max_hours": 26, "systemd_failed": False, "drill": None},
        "alerts": {"installed": True, "checks_ok": True},
        "box": {"uptime": "up 3 days, 4 hours", "disk_pct": 41, "disk_max_pct": 85,
                "services": [{"name": "portal", "state": "running", "health": "healthy"}],
                "clamav_sig_age_days": 1.2},
        "freshness": {"code": {"sha": "abc1234", "origin": "abc1234", "behind": False, "comparable": True},
                      "surveys_live": {"sha": "def5678", "origin": "def5678", "behind": False, "comparable": True}},
        "builds": [{"dir": "20260710T032000Z", "build_id": "abc1234-def5678-2026-07-10T03:20:00Z",
                    "engine_commit": "abc1234", "source_commit": "def5678", "stations": 8, "serving": True,
                    "cache": {"enabled": True, "mode": "rw", "salt_fp": "cafef00dbeef",
                              "write_errors": 2, "read_errors": 3, "hits": 10, "misses": 0,
                              "degenerate": False, "reason": None}}],
        "logs": {"build": "line1\nBUILD OK\n", "build_file": "20260710T032000Z.build.log"},
    }
    doc.update(over)
    return doc


def _write_ops(cfg, doc: dict) -> None:
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    (cfg.state_dir / serve_state.OPS_STATUS_FILENAME).write_text(json.dumps(doc), encoding="utf-8")


def _write_reconcile(cfg, doc: dict) -> None:
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    (cfg.state_dir / serve_state.STATUS_FILENAME).write_text(json.dumps(doc), encoding="utf-8")


# --------------------------------------------------------------------------------------------------
# Unit: the staleness clock (mutation-proof — fresh vs stale vs missing/unparseable)
# --------------------------------------------------------------------------------------------------
def test_ops_status_stale_threshold_mutation_proof():
    """ops_status_stale is True beyond ~2 timer periods, False within, and STALE for a missing OR
    unparseable generated_at. FAILS IF: a within-window file reads stale, an over-window file reads
    fresh, or a missing/garbage timestamp is treated as fresh (stale data rendering as fresh is the
    exact failure the ops floor must never allow)."""
    gen = calendar.timegm(time.strptime("2026-07-11T00:00:00Z", "%Y-%m-%dT%H:%M:%SZ"))
    doc = {"generated_at": "2026-07-11T00:00:00Z", "timer_period_min": 15}
    assert serve_state.ops_status_stale(doc, now_epoch=gen + 15 * 60) is False   # 1 period -> fresh
    assert serve_state.ops_status_stale(doc, now_epoch=gen + 40 * 60) is True    # > 2 periods -> stale
    assert serve_state.ops_status_stale(None) is True                            # missing
    assert serve_state.ops_status_stale({"timer_period_min": 15}) is True         # no generated_at
    assert serve_state.ops_status_stale(
        {"generated_at": "not-a-timestamp", "timer_period_min": 15}) is True       # unparseable


# --------------------------------------------------------------------------------------------------
# Route: staleness -> STALE cards (never last-known-good silently)
# --------------------------------------------------------------------------------------------------
def test_serve_page_stale_ops_renders_stale_never_last_known_good(tmp_path):
    """STALENESS PIN. An ops-status.json older than ~2 timer periods must flip the operations floor to
    an explicit STALE state — the last-known-good facts must NOT render as fresh. FAILS IF a stale
    file's healthy facts (e.g. the box uptime string) render as a live card, or the STALE banner is
    absent."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_ops(cfg, _fresh_ops(generated_at="2020-01-01T00:00:00Z"))   # ancient -> stale
            r = await client.get("/gateway/curator/serve")
            assert r.status_code == 200
            html = r.text
            assert "Operations floor is STALE" in html, "the STALE banner must render"
            assert "up 3 days, 4 hours" not in html, (
                "a STALE ops file must NOT render its last-known-good box facts as fresh")
            assert "cafef00dbeef" not in html, "STALE must not render last-known-good build forensics"
    run(_body())


def test_serve_page_missing_ops_is_stale_and_still_200(tmp_path):
    """A serve screen with NO ops-status.json at all (alert timer not installed) renders STALE and
    still 200s — never a 500. FAILS IF a missing ops file 500s the page or renders fresh cards."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            r = await client.get("/gateway/curator/serve")
            assert r.status_code == 200
            assert "Operations floor is STALE" in r.text
    run(_body())


# --------------------------------------------------------------------------------------------------
# Route: the sync_failed loud band (the incident, as a test) — driven by FRESH reconcile-status.json
# --------------------------------------------------------------------------------------------------
def test_sync_failed_renders_loud_band_incident_as_test(tmp_path):
    """SYNC_FAILED SURFACING PIN (record D15 — the incident as a test). A reconcile-status.json with
    action=sync_failed must render the LOUD sync band on the serve screen; a healthy noop must NOT.
    FAILS IF a sync_failed stays invisible (the 4-hour hidden failure) OR a noop renders the alarm."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_reconcile(cfg, {"action": "sync_failed", "last_run": "2026-07-11T03:00:00Z",
                                   "head": "abc1234", "built": "abc1234"})
            r = await client.get("/gateway/curator/serve")
            assert r.status_code == 200
            assert "SYNC FAILED" in r.text and "behind GitHub" in r.text, (
                "a sync_failed must render the loud band")
            # companion (mutation-proof): a noop reconcile must NOT render the alarm.
            _write_reconcile(cfg, {"action": "noop", "last_run": "2026-07-11T03:00:00Z"})
            r2 = await client.get("/gateway/curator/serve")
            assert "SYNC FAILED" not in r2.text, "a healthy noop must not render the sync-failed alarm"
    run(_body())


def test_sync_failed_streak_enrichment_from_ops(tmp_path):
    """When ops-status.json is FRESH and carries a sync_failed streak, the loud band names the streak
    (since + consecutive ticks). FAILS IF the streak enrichment is dropped despite a fresh ops file."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_reconcile(cfg, {"action": "sync_failed", "last_run": "2026-07-11T03:00:00Z"})
            _write_ops(cfg, _fresh_ops(reconcile={
                "action": "sync_failed", "last_run": "2026-07-11T03:00:00Z", "sync_failed": True,
                "sync_failed_streak": 5, "sync_failed_since": "2026-07-11T00:00:00Z"}))
            r = await client.get("/gateway/curator/serve")
            html = r.text
            assert "SYNC FAILED" in html
            assert "5 consecutive ticks" in html and "failing since 2026-07-11T00:00:00Z" in html
    run(_body())


# --------------------------------------------------------------------------------------------------
# Route: both-repo freshness (behind -> amber; current -> green)
# --------------------------------------------------------------------------------------------------
def test_freshness_card_both_repos_behind_amber_current_green(tmp_path):
    """BOTH-REPO FRESHNESS PIN. The freshness card covers code checkout AND surveys-live; a behind
    repo renders an amber 'behind' marker, a current one does not. FAILS IF a behind surveys-live
    (the incident's stale-behind-GitHub) renders as current, or a fully-current pair renders behind."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            # surveys-live behind origin, code current.
            _write_ops(cfg, _fresh_ops(freshness={
                "code": {"sha": "aaa1111", "origin": "aaa1111", "behind": False, "comparable": True},
                "surveys_live": {"sha": "bbb2222", "origin": "ccc3333", "behind": True, "comparable": True}}))
            r = await client.get("/gateway/curator/serve")
            html = r.text
            assert ">behind</span>" in html, "a behind repo must render the amber behind marker"
            assert f"color:{_WARN}" in html, "the amber colour must be present on the behind row"
            assert "bbb2222" in html and "ccc3333" in html, "the behind row shows both shas"
            # fully current -> no behind marker in the freshness rows.
            _write_ops(cfg, _fresh_ops())
            r2 = await client.get("/gateway/curator/serve")
            assert ">behind</span>" not in r2.text, "a current pair must not render a behind marker"
            assert "— current" in r2.text, "current repos render a 'current' marker"
    run(_body())


# --------------------------------------------------------------------------------------------------
# Route: build detail renders the C18-A4 cache forensics (render side of the B4 producer pin)
# --------------------------------------------------------------------------------------------------
def test_build_detail_renders_a4_cache_counters(tmp_path):
    """BUILD-DETAIL RENDER PIN (B4). The build-detail view must render the C18-A4 cache forensics
    (salt_fp / write_errors / read_errors) from the ops-status inventory, and 'no such build' for an
    unknown ref (no filesystem access, no traversal). FAILS IF a counter is dropped, the salt_fp is
    not shown, or an unknown ref is not handled."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_ops(cfg, _fresh_ops())
            r = await client.get("/gateway/curator/serve/build/20260710T032000Z")
            assert r.status_code == 200
            html = r.text
            assert "cafef00dbeef" in html, "the salt_fp (C18-A4) must render"
            assert '<span class="fk">Write errors</span><span class="fv">2</span>' in html
            assert '<span class="fk">Read errors</span><span class="fv">3</span>' in html
            # unknown ref -> a 'no such build' page, never a 500 or a traversal.
            r2 = await client.get("/gateway/curator/serve/build/../../etc/passwd")
            assert r2.status_code in (200, 404)
            if r2.status_code == 200:
                assert "No such retained build" in r2.text
    run(_body())


def test_build_detail_stale_ops_is_stale(tmp_path):
    """A build-detail view over a STALE ops-status.json renders STALE, not last-known-good forensics.
    FAILS IF stale build forensics render as fresh."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_ops(cfg, _fresh_ops(generated_at="2020-01-01T00:00:00Z"))
            r = await client.get("/gateway/curator/serve/build/20260710T032000Z")
            assert r.status_code == 200
            assert "STALE" in r.text and "cafef00dbeef" not in r.text
    run(_body())


# --------------------------------------------------------------------------------------------------
# Session gate + read-only (no privileged action) + CSP
# --------------------------------------------------------------------------------------------------
def test_serve_routes_require_session(tmp_path):
    """Both serve routes are curator-session-gated: an unauthenticated GET redirects to login and
    never renders the floor. FAILS IF an unauthenticated request sees the operations floor."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            for url in ("/gateway/curator/serve", "/gateway/curator/serve/build/x"):
                r = await client.get(url, follow_redirects=False)
                assert r.status_code == 303, (url, r.status_code)
                assert "Operations floor" not in r.text
    run(_body())


def test_serve_screen_renders_no_privileged_action(tmp_path):
    """Stage 2b-i is READ-ONLY: the serve screen must not render any privileged ACTION CONTROL
    (rollback/restore/update/backup/pause) — they are Stage 2b-ii, omitted (not disabled). Checks the
    real controls, not the explanatory prose: the ONLY form action allowed is the shipping C40
    /gateway/curator/rebuild (Request rebuild), and the only button label is 'Request rebuild'. FAILS
    IF a form posts to any other route, or a privileged action button leaks onto the screen."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_ops(cfg, _fresh_ops())
            html = (await client.get("/gateway/curator/serve")).text
            # Every <form> on the read-only screen may only post to the allowed C40 rebuild route.
            for action in re.findall(r'<form[^>]*\baction="([^"]*)"', html):
                assert action == "/gateway/curator/rebuild", (
                    f"a non-rebuild form action leaked onto the read-only serve screen: {action!r}")
            # Every server-rendered <button> may only be the Request-rebuild button.
            for label in re.findall(r"<button[^>]*>(.*?)</button>", html, re.DOTALL):
                assert "Request rebuild" in label, (
                    f"an unexpected action button leaked onto the read-only serve screen: {label!r}")
    run(_body())


def test_serve_page_and_build_detail_have_no_inline_js(tmp_path):
    """CSP SWEEP (record D13) extended to the new serve screen + build detail: no inline <script>
    (every <script> carries src=), no on*= handlers — both are dead under the strictPages CSP
    (script-src 'self'). FAILS IF either new surface ships inline JS."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, cfg):
            await curator_login(client)
            _write_ops(cfg, _fresh_ops())
            for url in ("/gateway/curator/serve", "/gateway/curator/serve/build/20260710T032000Z"):
                r = await client.get(url)
                assert r.status_code == 200, url
                html = r.text
                for m in re.finditer(r"<script\b[^>]*>", html):
                    assert re.search(r"\bsrc\s*=", m.group(0)), f"inline <script> in {url}: {m.group(0)}"
                handlers = re.findall(r"<[^>]*\son\w+\s*=", html)
                assert handlers == [], f"inline handlers in {url}: {handlers}"
    run(_body())


def test_freshness_chip_is_earned_never_defaulted():
    """FRESHNESS-CHIP FAIL-CLOSED PIN (architect gate finding, 2026-07-11). 'current' must be
    EARNED — both repos carrying a comparable sha — never reached by fallthrough. With freshness
    data absent/unparseable (schema skew, broken checkout) the chip pills 'unknown', because a
    floor that cannot see the repos must never claim they are current (the incident class was a
    lying 'current' chip). FAILS IF unavailable freshness renders the 'current' pill."""
    from gateway.curatorpage import _freshness_card
    # Unavailable: no sha on either repo (e.g. wrong-shaped ops-status from a version skew).
    card = _freshness_card({"freshness": {"code": {}, "surveys_live": {}}})
    assert ">unknown<" in card, "unavailable freshness must pill 'unknown'"
    assert ">current<" not in card, "unavailable freshness must NEVER pill 'current'"
    # Earned: both repos comparable and not behind.
    ok = {"sha": "9ad6b3e", "origin": "9ad6b3e", "behind": 0, "comparable": True}
    card = _freshness_card({"freshness": {"code": dict(ok), "surveys_live": dict(ok)}})
    assert ">current<" in card
    # Behind still wins over unknown.
    behind = {"sha": "b898f26", "origin": "bb7efe7", "behind": 3, "comparable": True}
    card = _freshness_card({"freshness": {"code": {}, "surveys_live": behind}})
    assert ">behind<" in card


def test_ops_status_stale_future_timestamp_is_stale():
    """FUTURE-TIMESTAMP FAIL-CLOSED PIN (verifier finding, 2026-07-11). A generated_at in the
    FUTURE (forward clock step on the box, then the timer dies) must be STALE — a negative age is
    doubt, not freshness; without this, the ops floor would render FRESH cards for the whole skew
    window, the exact silent-staleness the mechanism exists to prevent. FAILS IF a future-dated
    file renders fresh."""
    from gateway.serve_state import ops_status_stale
    base = {"timer_period_min": 15}
    now = 1_800_000_000.0
    import time as _t
    def iso(epoch):
        return _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime(epoch))
    # 1 second, 1 hour, 10 days in the future: all STALE.
    for ahead in (1, 3600, 864000):
        s = dict(base, generated_at=iso(now + ahead))
        assert ops_status_stale(s, now_epoch=now) is True, f"future +{ahead}s must be STALE"
    # Sanity: genuinely fresh (5 min old) stays fresh; over-window stays stale.
    assert ops_status_stale(dict(base, generated_at=iso(now - 300)), now_epoch=now) is False
    assert ops_status_stale(dict(base, generated_at=iso(now - 3600)), now_epoch=now) is True
