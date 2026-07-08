"""C35b/D1 (code-health review F6): the REAL-git publish lane.

F6: `real_git_runner` (publish.py:86) is the ONLY place the gateway executes the git binary, yet ALL
pytest coverage went through FakeGit — which (pre-C35b/D2) returned rc=0 for any unmodeled verb. The
sole real-git lane (curator-e2e) was F5-unrunnable. So the fail-closed rollback (publish.py _rollback)
— the core publication-ledger guarantee — had NEVER run against a real repository, and the first live
approve (Olympic Dam, 2026-07-06) failed twice on real-git behaviours FakeGit cannot represent.

This file drives the FULL approve flow (and the metadata-edit commit path) with
git_runner=publish.real_git_runner — NO FakeGit anywhere here — against a REAL repo pair built per
test in tmp_path: surveys-live (`git init` + identity + an initial commit on main) and a bare origin.

HERMETIC (no network, no docker, no secrets, no ambient identity leak): every git subprocess runs with
GIT_CONFIG_NOSYSTEM=1, GIT_CONFIG_GLOBAL -> a tmp file, HOME -> a tmp dir. The dev box's / CI runner's
~/.gitconfig can never leak in — that leakage class is exactly the recorded 2026-07-06 failure
(test_curator_publish.py:114). real_git_runner builds its subprocess env from scrubbed_env(), which
copies os.environ; monkeypatching os.environ (what the `hermetic_git_env` fixture does) is therefore
what those subprocesses actually see.

CROSS-PLATFORM: init a bare origin + a `#!/bin/sh` `exit 1` pre-receive hook per test; Git for Windows
runs hooks under its own bundled sh and CI ubuntu under /bin/sh — no bashisms, no /dev/null. Fast:
init+commit+bare per test, no sleeps (the app's settle_publish drives the async publish task).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from gateway import publish, states
from gateway.tests.conftest import (
    app_client, csrf_for_session, curator_login, run, seed_validated, settle_publish,
)


# --------------------------------------------------------------------------------------------------
# Real-git fixtures (idioms follow engine/tests/test_build_id.py's real-git pattern)
# --------------------------------------------------------------------------------------------------
def _git(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    """Run a real git command, check=True. Used only to BUILD/INSPECT the fixture repos — the code
    under test drives git through publish.real_git_runner, never through this helper."""
    return subprocess.run(["git", *args], cwd=str(cwd), env=env,
                          capture_output=True, text=True, check=True)


@pytest.fixture
def hermetic_git_env(tmp_path, monkeypatch) -> dict[str, str]:
    """Isolate git from any ambient config. Sets HOME / GIT_CONFIG_GLOBAL / GIT_CONFIG_NOSYSTEM on
    os.environ (so real_git_runner's scrubbed_env() copy carries them into every subprocess) AND
    returns a plain env dict for the fixture's own _git() build/inspect calls. A per-test global
    config sets init.defaultBranch=main so `git init` lands on main on any git version, and a throwaway
    default identity proves the publish OVERRIDES it (test a asserts the commit is the gateway identity
    regardless of this ambient one)."""
    home = tmp_path / "githome"
    home.mkdir()
    global_cfg = home / ".gitconfig"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_cfg))
    # A deliberately WRONG ambient identity + default branch, written into the isolated global config.
    env = _child_env(home, global_cfg)
    _git(["config", "--file", str(global_cfg), "init.defaultBranch", "main"], home, env)
    _git(["config", "--file", str(global_cfg), "user.name", "Ambient Dev"], home, env)
    _git(["config", "--file", str(global_cfg), "user.email", "ambient@dev.example"], home, env)
    return env


def _child_env(home: Path, global_cfg: Path) -> dict[str, str]:
    import os
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = str(global_cfg)
    return env


def _init_repo_pair(surveys_live: Path, origin: Path, env: dict[str, str]) -> str:
    """Build the real repo pair: surveys-live (init + initial commit on main) + a bare origin wired as
    'origin'. Returns the initial commit sha on main."""
    surveys_live.mkdir(parents=True, exist_ok=True)
    origin.mkdir(parents=True, exist_ok=True)
    _git(["init", "--bare"], origin, env)
    _git(["init"], surveys_live, env)
    _git(["branch", "-M", "main"], surveys_live, env)  # bulletproof: land on main regardless of default
    # A seed file so surveys-live has an initial commit + a surveys/ dir the stage step writes into.
    (surveys_live / "README.md").write_text("surveys-live\n", encoding="utf-8")
    (surveys_live / "surveys").mkdir(exist_ok=True)
    (surveys_live / "surveys" / ".gitkeep").write_text("", encoding="utf-8")
    _git(["add", "-A"], surveys_live, env)
    _git(["commit", "-m", "seed"], surveys_live, env)
    _git(["remote", "add", "origin", str(origin)], surveys_live, env)
    _git(["push", "-u", "origin", "main"], surveys_live, env)
    return _git(["rev-parse", "HEAD"], surveys_live, env).stdout.strip()


def _install_reject_hook(origin: Path) -> Path:
    """Write a portable pre-receive hook that ALWAYS rejects the push (exit 1). `#!/bin/sh` runs under
    Git-for-Windows' bundled sh and CI ubuntu's /bin/sh alike — no bashisms."""
    hook = origin / "hooks" / "pre-receive"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8", newline="\n")
    hook.chmod(0o755)
    return hook


def _committed_tree_text(surveys_live: Path, env: dict[str, str], ref: str = "HEAD") -> str:
    """All committed FILE CONTENTS at ref, concatenated — for a PII grep over the tree (not the
    working dir). `git grep` over the ref would also work; reading blobs is simplest + portable."""
    listing = _git(["ls-tree", "-r", "--name-only", ref], surveys_live, env).stdout.splitlines()
    parts = []
    for name in listing:
        parts.append(_git(["show", f"{ref}:{name}"], surveys_live, env).stdout)
    return "\n".join(parts)


def _commit_message(surveys_live: Path, env: dict[str, str], ref: str = "HEAD") -> str:
    return _git(["log", "-1", "--format=%B", ref], surveys_live, env).stdout


# --------------------------------------------------------------------------------------------------
# D1 assertions — the full approve flow on a REAL repo pair
# --------------------------------------------------------------------------------------------------
def test_real_git_commit_lands_on_main_with_gateway_identity(tmp_path, hermetic_git_env):
    # D1.a — FAILS IF: the approve does not reach PUBLISHED, the commit does not land on main, or the
    # author/committer identity is not the FIXED gateway identity (proves the publish's -c user.* config
    # OVERRIDES the ambient 'Ambient Dev' global identity the fixture deliberately set).
    env = hermetic_git_env

    async def _body():
        surveys_live = tmp_path / "surveys-live"
        origin = tmp_path / "origin.git"
        pre_ref = _init_repo_pair(surveys_live, origin, env)
        async with app_client(tmp_path, git_runner=publish.real_git_runner,
                              surveys_live_dir=surveys_live) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg, slug="demoslug")
            await curator_login(client)
            r = await client.post(f"/gateway/curator/submission/{sid}/approve",
                                  data={"note": "ok", "csrf_token": csrf_for_session(client)},
                                  follow_redirects=False)
            assert r.status_code == 303
            await settle_publish(gw, sid)
            assert gw.db.get(sid).state == states.PUBLISHED, gw.db.transitions_for(sid)[-1]

            head = _git(["rev-parse", "HEAD"], surveys_live, env).stdout.strip()
            assert head != pre_ref, "no new commit on main"
            branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], surveys_live, env).stdout.strip()
            assert branch == "main", f"ended on {branch!r}, not main"
            an = _git(["log", "-1", "--format=%an <%ae>"], surveys_live, env).stdout.strip()
            cn = _git(["log", "-1", "--format=%cn <%ce>"], surveys_live, env).stdout.strip()
            expected = f"{publish.COMMIT_AUTHOR_NAME} <{publish.COMMIT_AUTHOR_EMAIL}>"
            assert an == expected, f"author {an!r} != {expected!r}"
            assert cn == expected, f"committer {cn!r} != {expected!r}"
            # The staged package really landed in the tree.
            assert (surveys_live / "surveys" / "demoslug" / "survey.yaml").is_file()
    run(_body())


def test_real_git_push_arrives_at_bare_origin(tmp_path, hermetic_git_env):
    # D1.b — FAILS IF: the bare origin's main does not equal the local commit after publish (i.e. the
    # push did not actually ARRIVE). This is the observable a FakeGit rc=0 could never prove.
    env = hermetic_git_env

    async def _body():
        surveys_live = tmp_path / "surveys-live"
        origin = tmp_path / "origin.git"
        _init_repo_pair(surveys_live, origin, env)
        async with app_client(tmp_path, git_runner=publish.real_git_runner,
                              surveys_live_dir=surveys_live) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg, slug="arrives")
            await curator_login(client)
            await client.post(f"/gateway/curator/submission/{sid}/approve",
                              data={"note": "ok", "csrf_token": csrf_for_session(client)},
                              follow_redirects=False)
            await settle_publish(gw, sid)
            assert gw.db.get(sid).state == states.PUBLISHED
            local = _git(["rev-parse", "HEAD"], surveys_live, env).stdout.strip()
            remote = _git(["rev-parse", "main"], origin, env).stdout.strip()
            assert remote == local, f"push did not arrive: origin main {remote} != local {local}"
    run(_body())


def test_real_git_no_submitter_pii_in_tree_or_message(tmp_path, hermetic_git_env):
    # D1.c — THE PII guarantee against a real commit. FAILS IF the submitter name or email appears
    # anywhere in the committed tree contents OR the commit message. (Mutation-proved by writing the
    # submitter email into the commit body -> this must go RED; transcript in the report.)
    env = hermetic_git_env
    secret_email = "leak-canary-77@private.test"
    secret_name = "Verity Secretsmith"

    async def _body():
        surveys_live = tmp_path / "surveys-live"
        origin = tmp_path / "origin.git"
        _init_repo_pair(surveys_live, origin, env)
        async with app_client(tmp_path, git_runner=publish.real_git_runner,
                              surveys_live_dir=surveys_live) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg, slug="pii", email=secret_email, name=secret_name)
            await curator_login(client)
            await client.post(f"/gateway/curator/submission/{sid}/approve",
                              data={"note": "curated fine", "csrf_token": csrf_for_session(client)},
                              follow_redirects=False)
            await settle_publish(gw, sid)
            assert gw.db.get(sid).state == states.PUBLISHED
            msg = _commit_message(surveys_live, env)
            tree = _committed_tree_text(surveys_live, env)
            assert secret_email not in msg, "submitter email leaked into the commit message"
            assert secret_email not in tree, "submitter email leaked into the committed tree"
            assert secret_name not in msg, "submitter name leaked into the commit message"
            assert secret_name not in tree, "submitter name leaked into the committed tree"
    run(_body())


def test_real_git_preflight_refuses_dirty_tree(tmp_path, hermetic_git_env):
    # D1.d(i) — a genuinely dirty surveys-live checkout => preflight ABORT, PUBLISH_FAILED, nothing
    # staged. FAILS IF the publish proceeds on a dirty tree.
    env = hermetic_git_env

    async def _body():
        surveys_live = tmp_path / "surveys-live"
        origin = tmp_path / "origin.git"
        _init_repo_pair(surveys_live, origin, env)
        # Make the working tree genuinely dirty (an untracked+modified tracked file).
        (surveys_live / "README.md").write_text("surveys-live\nDIRTY EDIT\n", encoding="utf-8")
        async with app_client(tmp_path, git_runner=publish.real_git_runner,
                              surveys_live_dir=surveys_live) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg, slug="dirtyreal")
            await curator_login(client)
            await client.post(f"/gateway/curator/submission/{sid}/approve",
                              data={"note": "ok", "csrf_token": csrf_for_session(client)},
                              follow_redirects=False)
            await settle_publish(gw, sid)
            assert gw.db.get(sid).state == states.PUBLISH_FAILED
            assert "dirty" in gw.db.transitions_for(sid)[-1]["reason"].lower()
            assert not (surveys_live / "surveys" / "dirtyreal").exists()
    run(_body())


def test_real_git_preflight_refuses_non_main_head(tmp_path, hermetic_git_env):
    # D1.d(ii) — a checkout NOT on main (a stale submit branch left by a prior failed publish) =>
    # preflight ABORT. FAILS IF the publish proceeds off main.
    env = hermetic_git_env

    async def _body():
        surveys_live = tmp_path / "surveys-live"
        origin = tmp_path / "origin.git"
        _init_repo_pair(surveys_live, origin, env)
        _git(["checkout", "-b", "submit/stale"], surveys_live, env)  # leave HEAD off main
        async with app_client(tmp_path, git_runner=publish.real_git_runner,
                              surveys_live_dir=surveys_live) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg, slug="offmain")
            await curator_login(client)
            await client.post(f"/gateway/curator/submission/{sid}/approve",
                              data={"note": "ok", "csrf_token": csrf_for_session(client)},
                              follow_redirects=False)
            await settle_publish(gw, sid)
            assert gw.db.get(sid).state == states.PUBLISH_FAILED
            assert "main" in gw.db.transitions_for(sid)[-1]["reason"].lower()
    run(_body())


def test_real_git_rollback_restores_state_then_next_publish_succeeds(tmp_path, hermetic_git_env):
    # D1.e — THE never-executed core guarantee. A pre-receive hook on the bare origin exits 1 so the
    # PUSH fails mid-sequence; _rollback must restore the captured ref+branch, leave a CLEAN working
    # tree back on main, and a SUBSEQUENT publish (hook removed) must SUCCEED. This is the red state the
    # test exists to prevent: the wedged ledger (left on a submit branch, every later publish refusing).
    # FAILS IF after the failed push surveys-live is dirty / off main / at a moved ref, or the recovery
    # publish cannot proceed.
    env = hermetic_git_env

    async def _body():
        surveys_live = tmp_path / "surveys-live"
        origin = tmp_path / "origin.git"
        pre_ref = _init_repo_pair(surveys_live, origin, env)
        hook = _install_reject_hook(origin)
        async with app_client(tmp_path, git_runner=publish.real_git_runner,
                              surveys_live_dir=surveys_live) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg, slug="rollbackme")
            await curator_login(client)
            await client.post(f"/gateway/curator/submission/{sid}/approve",
                              data={"note": "ok", "csrf_token": csrf_for_session(client)},
                              follow_redirects=False)
            await settle_publish(gw, sid)
            # 1) The publish FAILED closed.
            assert gw.db.get(sid).state == states.PUBLISH_FAILED, gw.db.transitions_for(sid)[-1]
            # 2) surveys-live is byte-for-byte the pre-state: on main, at pre_ref, clean tree, and the
            #    staged tree is gone (rollback's `clean -fd -- surveys`).
            branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], surveys_live, env).stdout.strip()
            head = _git(["rev-parse", "HEAD"], surveys_live, env).stdout.strip()
            porcelain = _git(["status", "--porcelain"], surveys_live, env).stdout.strip()
            assert branch == "main", f"rollback left HEAD on {branch!r}, not main (wedged-ledger state)"
            assert head == pre_ref, f"rollback did not restore the pre-state ref ({head} != {pre_ref})"
            assert porcelain == "", f"rollback left a dirty tree: {porcelain!r}"
            assert not (surveys_live / "surveys" / "rollbackme").exists(), "staged tree survived rollback"
            # 3) Remove the hook and RETRY — the recovery must succeed (ledger not wedged).
            hook.unlink()
            r = await client.post(f"/gateway/curator/submission/{sid}/retry",
                                  data={"note": "retry after hook removed",
                                        "csrf_token": csrf_for_session(client)},
                                  follow_redirects=False)
            assert r.status_code == 303
            await settle_publish(gw, sid)
            assert gw.db.get(sid).state == states.PUBLISHED, gw.db.transitions_for(sid)[-1]
            remote = _git(["rev-parse", "main"], origin, env).stdout.strip()
            local = _git(["rev-parse", "HEAD"], surveys_live, env).stdout.strip()
            assert remote == local, "recovery publish did not push to origin"
    run(_body())


# --------------------------------------------------------------------------------------------------
# D1.f — the metadata-edit commit path (commit_metadata_edit) on a REAL repo pair
# --------------------------------------------------------------------------------------------------
def _seed_published_survey(surveys_live: Path, env: dict[str, str], slug: str,
                           yaml_text: str) -> None:
    """Commit an existing published survey into surveys-live/surveys/<slug>/survey.yaml on main, so the
    metadata-edit path has a survey to edit. Uses the fixture git (not the code under test)."""
    pkg = surveys_live / "surveys" / slug
    pkg.mkdir(parents=True, exist_ok=True)
    # write_bytes (not write_text): keep exact LF bytes on Windows too, so the rollback assertion can
    # compare against the byte-identical seed (write_text would translate \n -> \r\n on Windows).
    (pkg / "survey.yaml").write_bytes(yaml_text.encode("utf-8"))
    _git(["add", "-A"], surveys_live, env)
    _git(["commit", "-m", f"seed published {slug}"], surveys_live, env)
    _git(["push", "origin", "main"], surveys_live, env)


def test_real_git_metadata_edit_commits_and_pushes(tmp_path, hermetic_git_env):
    # D1.f(i) — commit_metadata_edit writes the confirmed yaml bytes, commits with the gateway identity,
    # and pushes to origin. FAILS IF the edited bytes are not committed, the identity is wrong, or the
    # push does not arrive.
    env = hermetic_git_env
    import hashlib

    surveys_live = tmp_path / "surveys-live"
    origin = tmp_path / "origin.git"
    _init_repo_pair(surveys_live, origin, env)
    _seed_published_survey(surveys_live, env, "edited", "slug: edited\nversion: 1.0.0\n")
    new_yaml = b"slug: edited\nversion: 1.0.1\n"
    sha = hashlib.sha256(new_yaml).hexdigest()

    pre = publish.preflight(publish.real_git_runner, surveys_live)
    new_ref = publish.commit_metadata_edit(
        publish.real_git_runner, surveys_live, "edited", new_yaml, sha,
        curator_name="curator1", note="bump version", pre=pre)

    assert new_ref, "commit_metadata_edit returned no ref"
    committed = (surveys_live / "surveys" / "edited" / "survey.yaml").read_bytes()
    assert committed == new_yaml, "edited yaml bytes not written"
    an = _git(["log", "-1", "--format=%an <%ae>"], surveys_live, env).stdout.strip()
    assert an == f"{publish.COMMIT_AUTHOR_NAME} <{publish.COMMIT_AUTHOR_EMAIL}>"
    remote = _git(["rev-parse", "main"], origin, env).stdout.strip()
    local = _git(["rev-parse", "HEAD"], surveys_live, env).stdout.strip()
    assert remote == local, "metadata-edit push did not arrive at origin"
    # ended clean on main
    assert _git(["rev-parse", "--abbrev-ref", "HEAD"], surveys_live, env).stdout.strip() == "main"
    assert _git(["status", "--porcelain"], surveys_live, env).stdout.strip() == ""


def test_real_git_metadata_edit_rollback_on_push_reject(tmp_path, hermetic_git_env):
    # D1.f(ii) — the metadata-edit commit+push+rollback SKELETON against real git: a pre-receive reject
    # rolls surveys-live back byte-for-byte (ref+branch, clean tree) and re-raises PublishError. FAILS
    # IF the edited bytes survive, the ref moved, or the tree is left dirty/off-main.
    env = hermetic_git_env
    import hashlib

    surveys_live = tmp_path / "surveys-live"
    origin = tmp_path / "origin.git"
    _init_repo_pair(surveys_live, origin, env)
    _seed_published_survey(surveys_live, env, "edited", "slug: edited\nversion: 1.0.0\n")
    pre_ref = _git(["rev-parse", "HEAD"], surveys_live, env).stdout.strip()
    _install_reject_hook(origin)

    new_yaml = b"slug: edited\nversion: 9.9.9\n"
    sha = hashlib.sha256(new_yaml).hexdigest()
    pre = publish.preflight(publish.real_git_runner, surveys_live)
    with pytest.raises(publish.PublishError) as ei:
        publish.commit_metadata_edit(
            publish.real_git_runner, surveys_live, "edited", new_yaml, sha,
            curator_name="curator1", note="doomed", pre=pre)
    assert ei.value.phase == "git-push"
    # Rolled back byte-for-byte.
    assert _git(["rev-parse", "HEAD"], surveys_live, env).stdout.strip() == pre_ref
    assert _git(["rev-parse", "--abbrev-ref", "HEAD"], surveys_live, env).stdout.strip() == "main"
    assert _git(["status", "--porcelain"], surveys_live, env).stdout.strip() == ""
    committed = (surveys_live / "surveys" / "edited" / "survey.yaml").read_bytes()
    assert committed == b"slug: edited\nversion: 1.0.0\n", "edited bytes survived a rolled-back edit"


# --------------------------------------------------------------------------------------------------
# D1.g — the station-removal commit path (commit_station_removal) on a REAL repo pair
# --------------------------------------------------------------------------------------------------
def _seed_published_survey_with_edis(surveys_live: Path, env: dict[str, str], slug: str,
                                     yaml_text: str, stations) -> None:
    """Commit a published survey WITH several EDIs into surveys-live on main, so the station-removal
    path has real files to git rm. Uses the fixture git (not the code under test)."""
    pkg = surveys_live / "surveys" / slug
    edi = pkg / "transfer_functions" / "edi"
    edi.mkdir(parents=True, exist_ok=True)
    (pkg / "survey.yaml").write_bytes(yaml_text.encode("utf-8"))
    for name in stations:
        (edi / name).write_bytes((">HEAD\n  DATAID=%s\n>END\n" % name).encode("utf-8"))
    _git(["add", "-A"], surveys_live, env)
    _git(["commit", "-m", f"seed published {slug} with edis"], surveys_live, env)
    _git(["push", "origin", "main"], surveys_live, env)


def test_real_git_station_removal_deletes_edis_and_pushes(tmp_path, hermetic_git_env):
    # D1.g(i) — commit_station_removal git-rms the selected EDIs, writes the version-bumped survey.yaml,
    # commits with the gateway identity, and pushes. FAILS IF the removed EDI is still in the committed
    # tree, a survivor was removed, the yaml was not updated, or the push did not arrive.
    env = hermetic_git_env
    import hashlib

    surveys_live = tmp_path / "surveys-live"
    origin = tmp_path / "origin.git"
    _init_repo_pair(surveys_live, origin, env)
    _seed_published_survey_with_edis(
        surveys_live, env, "multi", "slug: multi\nversion: 1.2.0\n",
        ("SA225.edi", "SA226.edi", "SA227.edi"))
    new_yaml = b"slug: multi\nversion: 1.3.0\n"
    sha = hashlib.sha256(new_yaml).hexdigest()

    pre = publish.preflight(publish.real_git_runner, surveys_live)
    new_ref = publish.commit_station_removal(
        publish.real_git_runner, surveys_live, "multi", new_yaml, ["SA226.edi"], sha,
        curator_name="curator1", note="withdrawn consent", pre=pre)

    assert new_ref, "commit_station_removal returned no ref"
    # The removed EDI is gone from the COMMITTED tree (not just the working dir), survivors remain.
    tree = _git(["ls-tree", "-r", "--name-only", "HEAD"], surveys_live, env).stdout
    assert "surveys/multi/transfer_functions/edi/SA226.edi" not in tree
    assert "surveys/multi/transfer_functions/edi/SA225.edi" in tree
    assert "surveys/multi/transfer_functions/edi/SA227.edi" in tree
    assert (surveys_live / "surveys" / "multi" / "survey.yaml").read_bytes() == new_yaml
    an = _git(["log", "-1", "--format=%an <%ae>"], surveys_live, env).stdout.strip()
    assert an == f"{publish.COMMIT_AUTHOR_NAME} <{publish.COMMIT_AUTHOR_EMAIL}>"
    remote = _git(["rev-parse", "main"], origin, env).stdout.strip()
    local = _git(["rev-parse", "HEAD"], surveys_live, env).stdout.strip()
    assert remote == local, "station-removal push did not arrive at origin"
    assert _git(["rev-parse", "--abbrev-ref", "HEAD"], surveys_live, env).stdout.strip() == "main"
    assert _git(["status", "--porcelain"], surveys_live, env).stdout.strip() == ""


def test_real_git_station_removal_rollback_on_push_reject(tmp_path, hermetic_git_env):
    # D1.g(ii) — a pre-receive reject rolls surveys-live back byte-for-byte: the git-rm'd EDI is
    # RESTORED, the yaml reverts, the ref/branch are the pre-state, the tree is clean. FAILS IF the
    # removal survives a rejected push (a half-removal in the publication ledger).
    env = hermetic_git_env
    import hashlib

    surveys_live = tmp_path / "surveys-live"
    origin = tmp_path / "origin.git"
    _init_repo_pair(surveys_live, origin, env)
    _seed_published_survey_with_edis(
        surveys_live, env, "multi", "slug: multi\nversion: 1.2.0\n",
        ("SA225.edi", "SA226.edi", "SA227.edi"))
    pre_ref = _git(["rev-parse", "HEAD"], surveys_live, env).stdout.strip()
    _install_reject_hook(origin)

    new_yaml = b"slug: multi\nversion: 9.9.9\n"
    sha = hashlib.sha256(new_yaml).hexdigest()
    pre = publish.preflight(publish.real_git_runner, surveys_live)
    with pytest.raises(publish.PublishError) as ei:
        publish.commit_station_removal(
            publish.real_git_runner, surveys_live, "multi", new_yaml, ["SA226.edi"], sha,
            curator_name="curator1", note="doomed", pre=pre)
    assert ei.value.phase == "git-push"
    # Rolled back byte-for-byte: HEAD/branch restored, tree clean, the removed EDI RESTORED.
    assert _git(["rev-parse", "HEAD"], surveys_live, env).stdout.strip() == pre_ref
    assert _git(["rev-parse", "--abbrev-ref", "HEAD"], surveys_live, env).stdout.strip() == "main"
    assert _git(["status", "--porcelain"], surveys_live, env).stdout.strip() == ""
    assert (surveys_live / "surveys" / "multi" / "transfer_functions" / "edi" / "SA226.edi").is_file(), \
        "the git-rm'd EDI must be restored on rollback"
    committed = (surveys_live / "surveys" / "multi" / "survey.yaml").read_bytes()
    assert committed == b"slug: multi\nversion: 1.2.0\n", "removal yaml survived a rolled-back removal"
