"""C31 metadata-editor gateway-flow tests (design §3.2-§3.8). Driven through the real HTTP surface
(httpx in-process) with the C31 edit seam injected in-process (conftest.inproc_edit_runner) and the
publish git seam faked (conftest.FakeGit) — the same injected-seam discipline as the C10 clamd and
C11 git tests. Proven-failing-first where a behaviour change is the deliverable.

The load-bearing guarantees proved here: the §0.6 hash pin (stale/tampered hash ⇒ 409, nothing
committed), the validator-FAIL server-side refusal (§0.4/§3.3), session+CSRF on every route (§3.6),
hostile-value inertness (§3.7), and the §3.8 source assertion that the gateway package carries no
yaml/ruamel import.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

from gateway.tests.conftest import (
    FakeGit, app_client, csrf_for_session, curator_login, inproc_edit_runner, run,
    validator_fail, write_survey_live,
)


def _extract(body: str, field: str) -> str:
    m = re.search(rf'name="{field}" value="([^"]*)"', body)
    return html.unescape(m.group(1)) if m else ""


async def _preview(client, slug, csrf, **fields):
    data = {"csrf_token": csrf, "bump": "patch", "note": "an edit note", **fields}
    return await client.post(f"/gateway/curator/edit/{slug}/preview", data=data,
                             follow_redirects=False)


# --------------------------------------------------------------------------------------------------
# §3.6 session / CSRF on every route
# --------------------------------------------------------------------------------------------------
def test_edit_routes_require_session(tmp_path):
    async def _body():
        surveys_live = tmp_path / "surveys-live"
        write_survey_live(surveys_live)
        async with app_client(tmp_path, git_runner=FakeGit(), edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            # No login: GET pages redirect to login; POST routes 401.
            r = await client.get("/gateway/curator/edit", follow_redirects=False)
            assert r.status_code == 303
            r = await client.get("/gateway/curator/edit/demo-survey-2026", follow_redirects=False)
            assert r.status_code == 303
            r = await client.post("/gateway/curator/edit/demo-survey-2026/preview",
                                  data={"f_region": "X"}, follow_redirects=False)
            assert r.status_code == 401
            r = await client.post("/gateway/curator/edit/demo-survey-2026/confirm",
                                  data={"new_sha256": "x"}, follow_redirects=False)
            assert r.status_code == 401
    run(_body())


def test_edit_preview_rejects_bad_csrf(tmp_path):
    # proven-failing-first: without the csrf_ok gate a cross-site POST would drive a merge/preview.
    async def _body():
        surveys_live = tmp_path / "surveys-live"
        write_survey_live(surveys_live)
        async with app_client(tmp_path, git_runner=FakeGit(), edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.post("/gateway/curator/edit/demo-survey-2026/preview",
                                  data={"csrf_token": "wrong", "f_region": "X", "bump": "patch",
                                        "note": "n"}, follow_redirects=False)
            assert r.status_code == 403
    run(_body())


def test_confirm_rejects_bad_csrf_no_commit(tmp_path):
    async def _body():
        surveys_live = tmp_path / "surveys-live"
        write_survey_live(surveys_live)
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git, edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.post("/gateway/curator/edit/demo-survey-2026/confirm",
                                  data={"csrf_token": "wrong", "new_sha256": "abc",
                                        "patch_json": "{}", "bump": "patch", "note": "n"},
                                  follow_redirects=False)
            assert r.status_code == 403
            assert git.calls == []  # no git touched
    run(_body())


# --------------------------------------------------------------------------------------------------
# §1 the happy path (open -> preview -> confirm -> commit)
# --------------------------------------------------------------------------------------------------
def test_full_edit_flow_commits_and_preserves_fidelity(tmp_path):
    async def _body():
        surveys_live = tmp_path / "surveys-live"
        pkg = write_survey_live(surveys_live)
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git, edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)

            # list + form are seeded from the runner read-job.
            assert "demo-survey-2026" in (await client.get("/gateway/curator/edit")).text
            form = (await client.get("/gateway/curator/edit/demo-survey-2026")).text
            assert "South Australia" in form
            assert "current version 1.0.0" in form

            r = await _preview(client, "demo-survey-2026", csrf, f_region="Northern Territory")
            assert r.status_code == 200
            body = r.text
            assert "Northern Territory" in body                # the diff shows the change
            assert "new version 1.0.1" in body
            sha = _extract(body, "new_sha256")
            patch_json = _extract(body, "patch_json")
            assert sha and patch_json

            r = await client.post("/gateway/curator/edit/demo-survey-2026/confirm",
                                  data={"csrf_token": csrf, "new_sha256": sha,
                                        "patch_json": patch_json, "bump": "patch",
                                        "note": "an edit note"}, follow_redirects=False)
            assert r.status_code == 200
            assert "committed" in r.text.lower()

            # The file on disk changed to the new region + version, and the COMMENT + UNKNOWN key
            # survive byte-for-byte (the round-trip fidelity guarantee, through the real gateway seam).
            after = (pkg / "survey.yaml").read_text(encoding="utf-8")
            assert "region: Northern Territory" in after
            assert "version: 1.0.1" in after
            assert "# human-readable name" in after
            assert 'custom_local_note: "keep me byte-for-byte"' in after
            assert "release_notes:" in after

            # The commit used the fixed gateway author and the metadata-edit subject; the push ran.
            joined = " ".join(" ".join(c) for c in git.calls)
            assert "AusMT Gateway" in joined and "gateway@ausmt.local" in joined
            assert "metadata edit by curator:curator1" in joined
            assert ["push", "origin", "main"] in git.calls
    run(_body())


# --------------------------------------------------------------------------------------------------
# §3.6 access.level flip round-trips into the yaml
# --------------------------------------------------------------------------------------------------
def test_access_level_flip_lands_in_yaml(tmp_path):
    async def _body():
        surveys_live = tmp_path / "surveys-live"
        pkg = write_survey_live(surveys_live)
        async with app_client(tmp_path, git_runner=FakeGit(), edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            new_access = '{"level": "embargoed", "embargo_until": "2027-01-01", "contact": null}'
            r = await _preview(client, "demo-survey-2026", csrf, j_access=new_access)
            assert r.status_code == 200
            sha = _extract(r.text, "new_sha256")
            patch_json = _extract(r.text, "patch_json")
            note = _extract(r.text, "note")
            r = await client.post("/gateway/curator/edit/demo-survey-2026/confirm",
                                  data={"csrf_token": csrf, "new_sha256": sha,
                                        "patch_json": patch_json, "bump": "patch",
                                        "note": note}, follow_redirects=False)
            assert r.status_code == 200
            after = (pkg / "survey.yaml").read_text(encoding="utf-8")
            assert "level: embargoed" in after
            # FIX 3: the ISO date is double-quoted (a bare 2027-01-01 would be retyped to
            # datetime.date by the PyYAML readers downstream).
            assert 'embargo_until: "2027-01-01"' in after
    run(_body())


# --------------------------------------------------------------------------------------------------
# §3.3 validator FAIL blocks confirm (server-side 409)
# --------------------------------------------------------------------------------------------------
def test_validator_fail_shows_fail_and_confirm_409(tmp_path):
    # A validator FAIL on the patched yaml ⇒ the preview shows FAIL and NO confirm button, AND a
    # forced confirm POST 409s server-side (the button absence is UX; the 409 is the guarantee).
    async def _body():
        surveys_live = tmp_path / "surveys-live"
        write_survey_live(surveys_live)
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live,
                                                             validator_override=validator_fail),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            r = await _preview(client, "demo-survey-2026", csrf, f_region="Queensland")
            assert r.status_code == 200
            assert "FAIL" in r.text
            assert "Confirm &amp; commit" not in r.text   # no confirm button rendered
            sha = _extract(r.text, "new_sha256")
            # Even if a client forges the confirm POST, it 409s and nothing is committed.
            r = await client.post("/gateway/curator/edit/demo-survey-2026/confirm",
                                  data={"csrf_token": csrf, "new_sha256": sha or "x",
                                        "patch_json": '{"region": "Queensland"}', "bump": "patch",
                                        "note": "x"}, follow_redirects=False)
            assert r.status_code == 409
            # No MUTATING git — the FAIL guard is upstream of any commit. (The preview render now
            # reads surveys-live HEAD via `rev-parse --short HEAD` for the C43 drift chip, a benign
            # read the queue page already does; only commit/push/add/reset would be a violation.)
            mutating = [c for c in git.calls
                        if c and c[0] in ("commit", "push", "add", "reset", "rm", "merge",
                                          "checkout", "clean", "branch")]
            assert mutating == [], f"a mutating git op leaked past the FAIL guard: {mutating}"
    run(_body())


# --------------------------------------------------------------------------------------------------
# §3.4 hash pinning: tampered/stale hash ⇒ 409, nothing committed
# --------------------------------------------------------------------------------------------------
def test_stale_hash_confirm_409_no_commit(tmp_path):
    # proven-failing-first: without the §0.6 re-hash a stale preview would commit whatever bytes the
    # re-run merge produced, silently publishing content the curator never saw.
    async def _body():
        surveys_live = tmp_path / "surveys-live"
        write_survey_live(surveys_live)
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git, edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            r = await client.post("/gateway/curator/edit/demo-survey-2026/confirm",
                                  data={"csrf_token": csrf, "new_sha256": "deadbeef",
                                        "patch_json": '{"region": "Northern Territory"}',
                                        "bump": "patch", "note": "n"}, follow_redirects=False)
            assert r.status_code == 409
            assert "stale" in r.json()["detail"].lower()
            assert ["push", "origin", "main"] not in git.calls
    run(_body())


# --------------------------------------------------------------------------------------------------
# §3.5 git push fails ⇒ rollback, curator sees error, nothing pushed
# --------------------------------------------------------------------------------------------------
def test_push_failure_rolls_back(tmp_path):
    async def _body():
        surveys_live = tmp_path / "surveys-live"
        write_survey_live(surveys_live)
        git = FakeGit(fail_on={"push": (1, "remote rejected")})
        async with app_client(tmp_path, git_runner=git, edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            r = await _preview(client, "demo-survey-2026", csrf, f_region="Northern Territory")
            sha = _extract(r.text, "new_sha256")
            patch_json = _extract(r.text, "patch_json")
            note = _extract(r.text, "note")
            r = await client.post("/gateway/curator/edit/demo-survey-2026/confirm",
                                  data={"csrf_token": csrf, "new_sha256": sha,
                                        "patch_json": patch_json, "bump": "patch",
                                        "note": note}, follow_redirects=False)
            assert r.status_code == 409
            assert "publish failed" in r.json()["detail"].lower()
            # A rollback ran (reset --hard to the captured pre-state ref).
            assert git.rolled_back is True
    run(_body())


def test_preflight_dirty_tree_refuses(tmp_path):
    # A dirty surveys-live checkout aborts at pre-flight — no branch/commit/push, no file mangling.
    async def _body():
        surveys_live = tmp_path / "surveys-live"
        write_survey_live(surveys_live)
        git = FakeGit(dirty=True)
        async with app_client(tmp_path, git_runner=git, edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            r = await _preview(client, "demo-survey-2026", csrf, f_region="Northern Territory")
            sha = _extract(r.text, "new_sha256")
            patch_json = _extract(r.text, "patch_json")
            note = _extract(r.text, "note")
            r = await client.post("/gateway/curator/edit/demo-survey-2026/confirm",
                                  data={"csrf_token": csrf, "new_sha256": sha,
                                        "patch_json": patch_json, "bump": "patch",
                                        "note": note}, follow_redirects=False)
            assert r.status_code == 409
            assert "publish failed" in r.json()["detail"].lower()  # aborted at preflight, not hash
            assert ["push", "origin", "main"] not in git.calls
    run(_body())


# --------------------------------------------------------------------------------------------------
# §3.7 hostile field values render inert
# --------------------------------------------------------------------------------------------------
def test_xss_in_edit_renders_inert(tmp_path):
    async def _body():
        surveys_live = tmp_path / "surveys-live"
        write_survey_live(surveys_live)
        async with app_client(tmp_path, git_runner=FakeGit(), edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            payload = "<script>alert(1)</script>"
            r = await _preview(client, "demo-survey-2026", csrf,
                               f_region=payload, note=payload)
            assert r.status_code == 200
            # The raw script tag never appears unescaped in the diff or the report.
            assert "<script>alert(1)</script>" not in r.text
            assert "&lt;script&gt;" in r.text
    run(_body())


# --------------------------------------------------------------------------------------------------
# §3.2 no-op edit refused through the gateway
# --------------------------------------------------------------------------------------------------
def test_noop_edit_refused_via_gateway(tmp_path):
    async def _body():
        surveys_live = tmp_path / "surveys-live"
        write_survey_live(surveys_live)
        async with app_client(tmp_path, git_runner=FakeGit(), edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            # Submit region unchanged ⇒ the merge refuses, the form re-renders with the error.
            r = await _preview(client, "demo-survey-2026", csrf, f_region="South Australia")
            assert r.status_code == 200
            assert "no changes" in r.text.lower()
    run(_body())


def test_unknown_slug_404(tmp_path):
    async def _body():
        surveys_live = tmp_path / "surveys-live"
        write_survey_live(surveys_live)
        async with app_client(tmp_path, git_runner=FakeGit(), edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get("/gateway/curator/edit/no-such-survey", follow_redirects=False)
            assert r.status_code == 404
            # A traversal-shaped slug never touches a path (charset guard) — 404.
            r = await client.get("/gateway/curator/edit/..%2f..%2fetc", follow_redirects=False)
            assert r.status_code == 404
    run(_body())


# --------------------------------------------------------------------------------------------------
# §3.8 the gateway package never gains a yaml/ruamel import (the C10 house rule, pinned)
# --------------------------------------------------------------------------------------------------
def test_gateway_package_has_no_yaml_import():
    # Scan every gateway/*.py EXCEPT gateway/runner/ (the runner runs in the engine image, where yaml
    # lives by design). A yaml/ruamel import appearing in the gateway PROCESS's modules would break
    # the C10/C31 §0.1 house rule that the gateway never parses survey content.
    # FAILS IF any gateway (non-runner) module imports yaml or ruamel.
    import gateway
    root = Path(gateway.__file__).parent
    offenders = []
    pattern = re.compile(r"^\s*(?:import|from)\s+(?:yaml|ruamel)\b", re.M)
    for py in sorted(root.rglob("*.py")):
        rel = py.relative_to(root)
        if rel.parts and rel.parts[0] == "runner":
            continue  # the runner is the engine-image content-parser, not the gateway process
        if rel.parts and rel.parts[0] == "tests":
            continue  # tests import the runner edit module deliberately (it is not the gateway proc)
        if pattern.search(py.read_text(encoding="utf-8")):
            offenders.append(str(rel))
    assert offenders == [], f"gateway process modules import yaml/ruamel: {offenders}"


def test_curator_queue_links_to_editor(tmp_path):
    async def _body():
        surveys_live = tmp_path / "surveys-live"
        write_survey_live(surveys_live)
        async with app_client(tmp_path, git_runner=FakeGit(), edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get("/gateway/curator/queue")
            assert "/gateway/curator/edit" in r.text
    run(_body())


# --------------------------------------------------------------------------------------------------
# review FIX 1: the DEFAULT seam is the jobs/edit/ file queue processed by the gw-runner — never an
# in-gateway child process. Two executable proofs: (a) the real transport works end-to-end with the
# app's default seam and a separate runner loop playing the gw-runner role; (b) the gateway process's
# module surface never imports ruamel/yaml (the gateway image has no ruamel — an import would be the
# exact ModuleNotFoundError ship-blocker the review caught).
# --------------------------------------------------------------------------------------------------
def test_default_seam_flows_through_the_file_queue(tmp_path):
    # proven failing 2026-07-06 (pre-fix HEAD): the default seam spawned
    # `sys.executable -m gateway.runner.edit` — in deployment that child runs on the GATEWAY image's
    # Python, which has no ruamel, so every real edit 500'd. Here the app is built with
    # edit_runner=None (the DEFAULT seam) and a background thread runs the runner's claim/process
    # loop against the SAME jobs dir — exactly the gw-runner service's role. FAILS IF the default
    # seam stops using the queue (the thread would claim nothing and the request would time out).
    import threading
    import time as _t

    from gateway.runner import edit as edit_mod
    from gateway.runner.runner import RunnerConfig

    async def _body():
        surveys_live = tmp_path / "surveys-live"
        write_survey_live(surveys_live)
        async with app_client(tmp_path, git_runner=FakeGit(), edit_runner=None,
                              surveys_live_dir=surveys_live,
                              edit_timeout_s=30) as (client, _app, gw, cfg):
            runner_cfg = RunnerConfig(
                incoming_dir=cfg.incoming_dir, quarantine_dir=cfg.quarantine_dir,
                jobs_dir=cfg.jobs_dir, validator_path="", surveys_root=surveys_live)
            stop = threading.Event()
            claimed: list[str] = []

            def gw_runner_role():
                while not stop.is_set():
                    p = edit_mod.claim_edit_job(runner_cfg.jobs_dir)
                    if p is None:
                        _t.sleep(0.02)
                        continue
                    claimed.append(p.name)
                    edit_mod.process_edit_job(runner_cfg, p)

            thread = threading.Thread(target=gw_runner_role, daemon=True)
            thread.start()
            try:
                await curator_login(client)
                csrf = csrf_for_session(client)
                # read job over the queue (sync route -> threadpool -> blocking poll)
                r = await client.get("/gateway/curator/edit/demo-survey-2026")
                assert r.status_code == 200
                assert "South Australia" in r.text
                # merge job over the queue (async route -> asyncio.to_thread -> blocking poll)
                r = await _preview(client, "demo-survey-2026", csrf,
                                   f_region="Northern Territory")
                assert r.status_code == 200
                assert "Northern Territory" in r.text
                assert _extract(r.text, "new_sha256")
            finally:
                stop.set()
                thread.join(timeout=2)
            # Both jobs really crossed the queue: the runner-role thread claimed them.
            assert len(claimed) >= 2
            # And the queue is clean afterwards (results consumed, nothing pending/running).
            for sub in ("pending", "running", "done"):
                assert list((cfg.jobs_dir / "edit" / sub).glob("*.json")) == []
    run(_body())


def test_edit_runner_down_times_out_with_5xx_not_hang(tmp_path):
    # No gw-runner processing the queue: the bounded poll gives up at edit_timeout_s and the curator
    # gets a 500 (retryable), never an indefinite hang, and the abandoned pending job is removed.
    async def _body():
        surveys_live = tmp_path / "surveys-live"
        write_survey_live(surveys_live)
        async with app_client(tmp_path, git_runner=FakeGit(), edit_runner=None,
                              surveys_live_dir=surveys_live,
                              edit_timeout_s=1) as (client, _app, _gw, cfg):
            await curator_login(client)
            r = await client.get("/gateway/curator/edit/demo-survey-2026")
            assert r.status_code == 500
            assert list((cfg.jobs_dir / "edit" / "pending").glob("*.json")) == []
    run(_body())


def test_gateway_process_never_imports_ruamel_or_yaml():
    # The executable half of the §3.8 pin (review FIX 1): importing the gateway's ENTIRE process
    # surface (app + every module it pulls) must not load ruamel or yaml — the gateway image ships
    # neither, so any such import is a production ModuleNotFoundError. Run in a CLEAN subprocess so
    # this test's own environment (where the harness legitimately imports gateway.runner.edit)
    # cannot mask a violation.
    import subprocess
    import sys

    import gateway
    repo_root = Path(gateway.__file__).resolve().parents[1]
    code = (
        "import sys\n"
        "import gateway.app, gateway.metaedit, gateway.curatorpage, gateway.publish, "
        "gateway.jobs, gateway.config, gateway.db, gateway.states, gateway.curator_auth\n"
        "bad = [m for m in sys.modules if m == 'yaml' or m.startswith('yaml.') "
        "or m == 'ruamel' or m.startswith('ruamel.')]\n"
        "assert not bad, f'gateway process surface imported: {bad}'\n"
        "print('clean')\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          cwd=str(repo_root), timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert "clean" in proc.stdout
