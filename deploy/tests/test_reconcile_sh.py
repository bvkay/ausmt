"""Serve-reconcile host agent (deploy/scripts/reconcile.sh) - decision-logic tests.

The reconcile agent is POSIX sh, so it is tested as a BLACK BOX through `sh` over a fake data tree
built under tmp_path: a real git origin + a tracking surveys-live checkout, a fabricated served
build.json, a gateway state dir, and a MAKE SHIM (AUSMT_RECONCILE_MAKE) that records its invocation
and — when the case needs a "successful rebuild" — rewrites build.json to the current HEAD so the
NEXT read sees the corpus advance. Every assertion is an INDEPENDENT OBSERVABLE (the shim's
invocation-marker file, the request file's existence, the status JSON's action, the process exit
code, the log file), never the script's own self-report.

Each test names its failure criterion in the docstring (Invariant 10). The cases:
  noop         head == built, no request  -> shim NOT invoked, action=noop, exit 0
  drift        head != built              -> shim invoked, action=rebuilt, log written + pruned, exit 0
  request      head == built + request    -> shim invoked, request consumed, action=rebuilt, exit 0
  sync_failed  diverged surveys-live      -> shim NOT invoked, action=sync_failed, exit 0
  failed       shim exits 1               -> action=failed, exit 1, log_tail populated
  dry-run      --dry-run on a drift        -> shim NOT invoked, NO status write, exit 0
  lock-held    a concurrent run holds flock -> second run exits 0, status untouched  (needs flock)

WINDOWS: there is no flock(1) here, so the lock-held case skipif's on its absence and is NOTED in the
report; ALL other cases run on this machine - reconcile.sh runs bare
(without the lock) when flock is missing, which does not change any non-lock decision.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]          # wt-c40/
_SCRIPT = _REPO / "deploy" / "scripts" / "reconcile.sh"

# The script and the test tree are driven through `sh` (Git Bash on Windows, /bin/sh on the deploy
# host). Skip the whole module if there is no POSIX sh to run it — the script is not a Python module.
_SH = shutil.which("sh") or shutil.which("bash")
pytestmark = pytest.mark.skipif(_SH is None, reason="no POSIX sh/bash to run reconcile.sh")

_HAS_FLOCK = shutil.which("flock") is not None
_HAS_GIT = shutil.which("git") is not None


def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert out.returncode == 0, f"git {args} failed in {cwd}: {out.stderr}"
    return out.stdout.strip()


def _make_tree(tmp_path: Path, *, source_commit: str | None, build_id: str = "bid-000") -> dict:
    """Build the fake data tree: a bare origin, a surveys-live checkout tracking it, a served
    build.json with the given source_commit (None => omit the key entirely / no build.json), an empty
    gateway state dir, and a make shim. Returns the paths + env the tests drive the script with."""
    data = tmp_path / "data"
    origin = tmp_path / "origin.git"
    surveys = data / "surveys-live"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    subprocess.run(["git", "clone", "-q", str(origin), str(surveys)], check=True,
                   capture_output=True, text=True)
    _git(surveys, "config", "user.email", "t@example.org")
    _git(surveys, "config", "user.name", "Test")
    (surveys / "a.txt").write_text("one\n", encoding="utf-8")
    _git(surveys, "add", "-A")
    _git(surveys, "commit", "-qm", "one")
    # Push so origin has the branch, and set upstream so `git pull --ff-only` has a tracking ref.
    branch = _git(surveys, "rev-parse", "--abbrev-ref", "HEAD")
    _git(surveys, "push", "-q", "origin", f"HEAD:{branch}")
    _git(surveys, "branch", f"--set-upstream-to=origin/{branch}")

    # build.json lives at the BUILD ROOT (current/build.json): the engine writes `out/build.json`
    # and Caddy's handle_path strips the /data URL prefix before the filesystem. The first install
    # failed because BOTH the script and this fixture assumed current/data/build.json -
    # a self-consistent test that validated the script against its own wrong assumption. The layout
    # here is now pinned to the ENGINE's write site by test_build_json_path_matches_engine_layout.
    site = data / "site-data" / "current"
    site.mkdir(parents=True, exist_ok=True)
    if source_commit is not None:
        (site / "build.json").write_text(json.dumps(
            {"build_id": build_id, "engine_commit": "eng0000", "source_commit": source_commit}),
            encoding="utf-8")
    (data / "gateway" / "state").mkdir(parents=True, exist_ok=True)

    # A make shim: it touches a marker file (proving it ran) and, when SHIM_REBUILD=1, rewrites
    # build.json to the CURRENT surveys-live HEAD short (7) with a fresh build_id — so the post-build
    # re-read sees the corpus advance (a real rebuild's effect). SHIM_FAIL=1 => exit 1 after logging.
    marker = tmp_path / "shim.invoked"
    shim = tmp_path / "shim.sh"
    shim.write_text(
        "#!/bin/sh\n"
        f'echo "SHIM args=$*"\n'
        f'echo invoked >> "{marker.as_posix()}"\n'
        'if [ "${SHIM_FAIL:-0}" = "1" ]; then echo "shim: simulated build failure" >&2; exit 1; fi\n'
        'if [ "${SHIM_REBUILD:-0}" = "1" ]; then\n'
        f'  NEWHEAD=$(git -C "{surveys.as_posix()}" rev-parse --short=7 HEAD)\n'
        f'  printf \'{{"build_id":"bid-rebuilt","engine_commit":"eng0000","source_commit":"%s"}}\' '
        f'"$NEWHEAD" > "{(site / "build.json").as_posix()}"\n'
        '  echo "shim: rewrote build.json to $NEWHEAD"\n'
        'fi\n',
        encoding="utf-8")
    shim.chmod(0o755)

    env = dict(os.environ)
    env["AUSMT_DATA_DIR"] = str(data)
    env["AUSMT_CODE_DIR"] = str(_REPO)
    env["AUSMT_RECONCILE_MAKE"] = f"sh {shim.as_posix()}"
    env["AUSMT_RECONCILE_LOCK"] = str(tmp_path / "reconcile.lock")
    # Ensure a WORKING python is discoverable as python3/python for the script's JSON reads. On this
    # dev box the bare `python3` can be a non-functional App-alias; prepend the running interpreter's
    # dir so the script's execution-probe finds a real one first.
    import sys
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")

    return {
        "data": data, "origin": origin, "surveys": surveys, "site": site,
        "state": data / "gateway" / "state", "marker": marker, "env": env, "branch": branch,
    }


def _run(tree: dict, *args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = dict(tree["env"])
    if env_extra:
        env.update(env_extra)
    return subprocess.run([_SH, str(_SCRIPT), *args], capture_output=True, text=True, env=env)


def _status(tree: dict) -> dict | None:
    f = tree["state"] / "reconcile-status.json"
    if not f.exists():
        return None
    return json.loads(f.read_text(encoding="utf-8"))


def _advance_head(tree: dict) -> str:
    """Commit a new revision on surveys-live AND push it to origin, then reset local one behind so a
    `git pull --ff-only` fast-forwards to it. Returns the new short HEAD (after the pull will land)."""
    surveys = tree["surveys"]
    (surveys / "b.txt").write_text("two\n", encoding="utf-8")
    _git(surveys, "add", "-A")
    _git(surveys, "commit", "-qm", "two")
    _git(surveys, "push", "-q", "origin", f"HEAD:{tree['branch']}")
    new_head = _git(surveys, "rev-parse", "--short=7", "HEAD")
    # Move the local branch back one so origin is strictly ahead -> pull --ff-only advances it.
    _git(surveys, "reset", "--hard", "HEAD~1")
    return new_head


def _commit_tracked_survey(tree: dict, name: str = "tracked-survey") -> None:
    """Add and COMMIT a survey dir under surveys-live/surveys/<name>/ (a tracked survey). Local stays
    ahead of origin, which a `git pull --ff-only` reports as 'Already up to date' (rc 0)."""
    surveys = tree["surveys"]
    (surveys / "surveys" / name).mkdir(parents=True, exist_ok=True)
    (surveys / "surveys" / name / "survey.yaml").write_text("version: 1\n", encoding="utf-8")
    _git(surveys, "add", "-A")
    _git(surveys, "commit", "-qm", f"survey {name}")


def _leave_untracked_survey(tree: dict, name: str = "test-2026") -> Path:
    """Leave an UNTRACKED survey dir under surveys-live/surveys/<name>/."""
    d = tree["surveys"] / "surveys" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "survey.yaml").write_text("version: 1\n", encoding="utf-8")
    return d


# --------------------------------------------------------------------------------------------------
# Untracked-survey-dir guard. The build enumerates the FILESYSTEM under
# surveys/, so a leftover UNTRACKED dir is served though git can never remove it. reconcile.sh must
# REFUSE the rebuild and record a distinct, dir-naming refusal state. RED-then-green pins.
# --------------------------------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_untracked_survey_dir_refuses_rebuild(tmp_path):
    """surveys-live has a tracked survey AND an UNTRACKED survey dir under surveys/ => the shim is
    NOT invoked (no build), the status action is 'untracked_blocked' naming the offending dir, and
    the script EXITS 1 so monitoring flags it. FAILS IF: reconcile builds anyway (the shim marker
    appears), or the refusal state does not name the dir, or it exits 0 and hides the
    misconfiguration."""
    tree = _make_tree(tmp_path, source_commit="deadbeef")  # built != HEAD => would otherwise rebuild
    _commit_tracked_survey(tree)
    _leave_untracked_survey(tree, "test-2026")
    r = _run(tree, env_extra={"SHIM_REBUILD": "1"})
    assert r.returncode == 1, f"a refused rebuild must exit 1; got {r.returncode}: {r.stderr}"
    assert not tree["marker"].exists(), "an untracked survey dir must REFUSE the rebuild (no shim)"
    st = _status(tree)
    assert st is not None and st["action"] == "untracked_blocked", st
    assert st["log_tail"] and "test-2026" in st["log_tail"], (
        f"the refusal must name the offending dir in log_tail; got {st!r}")
    assert "test-2026" in r.stderr, "the refusal must also name the dir on stderr (journal)"


@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_clean_survey_tree_still_rebuilds(tmp_path):
    """A surveys/ tree with ONLY tracked survey dirs (no untracked leftovers) + drift => the guard is
    transparent and the rebuild proceeds exactly as before. FAILS IF: the guard false-positives on a
    clean tree and blocks a legitimate rebuild (a regression to the reconcile behaviour)."""
    tree = _make_tree(tmp_path, source_commit="deadbeef")
    _commit_tracked_survey(tree)  # tracked only — nothing untracked under surveys/
    r = _run(tree, env_extra={"SHIM_REBUILD": "1"})
    assert r.returncode == 0, r.stderr
    assert tree["marker"].exists(), "a clean survey tree must still rebuild on drift"
    st = _status(tree)
    assert st is not None and st["action"] == "rebuilt", st


@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_untracked_dry_run_refuses_without_writing(tmp_path):
    """--dry-run on an untracked-dir tree => the shim is NOT invoked and NO status file is written (it
    only PRINTS the refusal), exit 0. FAILS IF: --dry-run writes the status file or invokes the build."""
    tree = _make_tree(tmp_path, source_commit="deadbeef")
    _commit_tracked_survey(tree)
    _leave_untracked_survey(tree, "test-2026")
    r = _run(tree, "--dry-run", env_extra={"SHIM_REBUILD": "1"})
    assert r.returncode == 0, r.stderr
    assert not tree["marker"].exists(), "--dry-run must NOT invoke the shim"
    assert _status(tree) is None, "--dry-run must NOT write the status file"
    assert "untracked_blocked" in r.stdout


# --------------------------------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_noop_when_head_equals_built(tmp_path):
    """head == built and no request file => the shim is NOT invoked, status action=noop, exit 0.
    FAILS IF: the script rebuilds when nothing changed (shim marker appears), or the action is not
    'noop', or the exit code is non-zero."""
    built = None  # set after we know HEAD
    tree = _make_tree(tmp_path, source_commit="placeholder")
    head = _git(tree["surveys"], "rev-parse", "--short=7", "HEAD")
    # Rewrite build.json so built == HEAD exactly.
    (tree["site"] / "build.json").write_text(json.dumps(
        {"build_id": "bid-noop", "engine_commit": "eng0000", "source_commit": head}), encoding="utf-8")
    del built
    r = _run(tree)
    assert r.returncode == 0, r.stderr
    assert not tree["marker"].exists(), "noop must NOT invoke the rebuild shim"
    st = _status(tree)
    assert st is not None and st["action"] == "noop"
    assert st["built"] == head and st["head"].startswith(head[:7])
    assert st["build_id"] == "bid-noop"


@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_drift_triggers_rebuild(tmp_path):
    """head != built => the shim IS invoked, status action=rebuilt, a build log is written, exit 0.
    FAILS IF: a real drift does not rebuild (no shim marker / action!=rebuilt), or no log file is
    recorded, or the exit code is non-zero."""
    tree = _make_tree(tmp_path, source_commit="deadbeef")  # built is a commit that is NOT our HEAD
    r = _run(tree, env_extra={"SHIM_REBUILD": "1"})
    assert r.returncode == 0, r.stderr
    assert tree["marker"].exists(), "drift must invoke the rebuild shim"
    st = _status(tree)
    assert st is not None and st["action"] == "rebuilt", st
    assert st["log_file"] and Path(st["log_file"]).is_file()
    assert st["build_id"] == "bid-rebuilt", "build_id must be re-read AFTER the rebuild"
    # The log dir got a *.build.log file.
    logs = list((tree["data"] / "site-data" / "logs").glob("*.build.log"))
    assert len(logs) == 1


@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_log_pruning_keeps_newest_20(tmp_path):
    """After a rebuild the logs/ dir is pruned to the newest 20 *.build.log. FAILS IF: an unbounded
    number of logs accumulates (pre-seed 25, run once => 21 would remain without the prune; the
    contract is <= 20 kept plus this run's = the prune trims to 20 total)."""
    tree = _make_tree(tmp_path, source_commit="deadbeef")
    logs_dir = tree["data"] / "site-data" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    # Pre-seed 25 stale logs with staggered mtimes so ls -1t has a stable order.
    for i in range(25):
        p = logs_dir / f"2020010{i:02d}T000000Z.build.log"
        p.write_text(f"stale {i}\n", encoding="utf-8")
        os.utime(p, (1_000_000 + i, 1_000_000 + i))
    r = _run(tree, env_extra={"SHIM_REBUILD": "1"})
    assert r.returncode == 0, r.stderr
    remaining = list(logs_dir.glob("*.build.log"))
    assert len(remaining) == 20, f"expected 20 logs after prune, got {len(remaining)}"


@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_request_file_triggers_rebuild_and_is_consumed(tmp_path):
    """head == built but a rebuild.request exists => the shim IS invoked AND the request file is
    consumed (removed) BEFORE the build, action=rebuilt. FAILS IF: the button's request is ignored
    (no shim marker), or the file is left behind (a storm on every subsequent tick)."""
    tree = _make_tree(tmp_path, source_commit="placeholder")
    head = _git(tree["surveys"], "rev-parse", "--short=7", "HEAD")
    (tree["site"] / "build.json").write_text(json.dumps(
        {"build_id": "bid-req", "engine_commit": "eng0000", "source_commit": head}), encoding="utf-8")
    req = tree["state"] / "rebuild.request"
    req.write_text(json.dumps({"requested_at": "2026-07-08T00:00:00Z", "requested_by": "curator1"}),
                   encoding="utf-8")
    r = _run(tree, env_extra={"SHIM_REBUILD": "1"})
    assert r.returncode == 0, r.stderr
    assert tree["marker"].exists(), "a present request file must invoke the rebuild shim"
    assert not req.exists(), "the request file must be consumed (removed) by the run"
    st = _status(tree)
    assert st is not None and st["action"] == "rebuilt"


@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_missing_build_json_treated_as_drift(tmp_path):
    """A missing/unreadable build.json => the script cannot prove what is served, so it treats it as
    DRIFT and rebuilds. FAILS IF: a missing build.json silently noops (a fresh box would never build)."""
    tree = _make_tree(tmp_path, source_commit=None)  # no build.json at all
    r = _run(tree, env_extra={"SHIM_REBUILD": "1"})
    assert r.returncode == 0, r.stderr
    assert tree["marker"].exists(), "missing build.json must be treated as drift and rebuild"
    st = _status(tree)
    assert st is not None and st["action"] == "rebuilt"


@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_sync_failed_when_diverged(tmp_path):
    """A surveys-live that cannot fast-forward (diverged local commit vs origin) => the shim is NOT
    invoked, status action=sync_failed, exit 0. FAILS IF: the script BUILDS from a state it could not
    sync (shim marker appears), or the action is not sync_failed, or it exits non-zero and flaps the
    timer. This is the 'never build from a state we cannot fast-forward to' guarantee."""
    tree = _make_tree(tmp_path, source_commit="deadbeef")
    surveys = tree["surveys"]
    # Diverge: origin gets a commit, local gets a DIFFERENT commit on top of the shared base -> a
    # non-fast-forward pull.
    (surveys / "origin_side.txt").write_text("o\n", encoding="utf-8")
    _git(surveys, "add", "-A")
    _git(surveys, "commit", "-qm", "origin-side")
    _git(surveys, "push", "-q", "origin", f"HEAD:{tree['branch']}")
    _git(surveys, "reset", "--hard", "HEAD~1")
    (surveys / "local_side.txt").write_text("l\n", encoding="utf-8")
    _git(surveys, "add", "-A")
    _git(surveys, "commit", "-qm", "local-side")  # now local and origin have diverged
    r = _run(tree)
    assert r.returncode == 0, f"sync_failed must NOT flap the timer (exit 0); got {r.returncode}: {r.stderr}"
    assert not tree["marker"].exists(), "a diverged sync must NOT rebuild"
    st = _status(tree)
    assert st is not None and st["action"] == "sync_failed", st


@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_failed_build_sets_failed_and_exit_1(tmp_path):
    """A rebuild whose make step exits non-zero => status action=failed, log_tail populated, and the
    script EXITS 1 (so monitoring flags it). FAILS IF: a failed build reports success, or exits 0
    (the timer would hide a broken build), or log_tail is empty."""
    tree = _make_tree(tmp_path, source_commit="deadbeef")
    r = _run(tree, env_extra={"SHIM_FAIL": "1"})
    assert r.returncode == 1, f"a failed build must exit 1; got {r.returncode}"
    assert tree["marker"].exists(), "the shim ran (and failed)"
    st = _status(tree)
    assert st is not None and st["action"] == "failed", st
    assert st["log_tail"] and "simulated build failure" in st["log_tail"]
    assert st["log_file"] and Path(st["log_file"]).is_file()


@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_failed_build_does_not_consume_leaves_no_crash_loop(tmp_path):
    """After a failed build the request file (if any) is ALREADY consumed, so the NEXT tick with no
    new drift is a noop — no crash-loop. FAILS IF: the request survives a failed build and re-triggers
    forever."""
    tree = _make_tree(tmp_path, source_commit="deadbeef")
    req = tree["state"] / "rebuild.request"
    req.write_text("{}", encoding="utf-8")
    r = _run(tree, env_extra={"SHIM_FAIL": "1"})
    assert r.returncode == 1
    assert not req.exists(), "request must be consumed even on a failed build (no storm)"


@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_dry_run_takes_no_action(tmp_path):
    """--dry-run on a real drift => the shim is NOT invoked, NO status file is written, exit 0. FAILS
    IF: --dry-run rebuilds, consumes the request, or writes the status file (it must only PRINT)."""
    tree = _make_tree(tmp_path, source_commit="deadbeef")
    req = tree["state"] / "rebuild.request"
    req.write_text("{}", encoding="utf-8")
    r = _run(tree, "--dry-run", env_extra={"SHIM_REBUILD": "1"})
    assert r.returncode == 0, r.stderr
    assert not tree["marker"].exists(), "--dry-run must NOT invoke the shim"
    assert _status(tree) is None, "--dry-run must NOT write the status file"
    assert req.exists(), "--dry-run must NOT consume the request file"
    assert "dry-run" in r.stdout.lower()


@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_ff_pull_advances_then_rebuilds(tmp_path):
    """End-to-end sync effect: origin is ahead by one commit; the run fast-forwards surveys-live to it
    and (because built now differs from the advanced HEAD) rebuilds. FAILS IF: the pull does not
    advance the checkout, or the advanced HEAD does not trigger the rebuild."""
    tree = _make_tree(tmp_path, source_commit="placeholder")
    head0 = _git(tree["surveys"], "rev-parse", "--short=7", "HEAD")
    # built == the CURRENT head so, pre-pull, it would be a noop; the pull advances HEAD -> drift.
    (tree["site"] / "build.json").write_text(json.dumps(
        {"build_id": "bid-ff", "engine_commit": "eng0000", "source_commit": head0}), encoding="utf-8")
    new_head = _advance_head(tree)
    assert new_head != head0
    r = _run(tree, env_extra={"SHIM_REBUILD": "1"})
    assert r.returncode == 0, r.stderr
    # The checkout fast-forwarded to origin's new commit.
    assert _git(tree["surveys"], "rev-parse", "--short=7", "HEAD") == new_head
    assert tree["marker"].exists(), "the advanced HEAD must trigger a rebuild"
    assert _status(tree)["action"] == "rebuilt"


def test_build_json_path_matches_engine_layout():
    """CROSS-ARTIFACT PIN: the script's BUILD_JSON path and the engine's
    write site must agree. The engine writes build.json at the BUILD ROOT (`out / "build.json"` in
    build_portal.py); Caddy's handle_path strips /data before the filesystem, so the /data/build.json
    URL maps to that same root file. FAILS IF: the script re-grows a data/ segment, or the engine
    moves its build.json write site without this pin (and therefore the script) being updated."""
    script = _SCRIPT.read_text(encoding="utf-8")
    assert 'BUILD_JSON="$SITE_DATA/current/build.json"' in script, \
        "reconcile.sh must read build.json at the build ROOT (current/build.json)"
    assert "current/data/build.json" not in script, \
        "the phantom data/ segment is the rebuild-loop bug"
    engine_src = (_REPO / "engine" / "extract" / "build_portal.py").read_text(encoding="utf-8")
    assert '(out / "build.json")' in engine_src, \
        "engine no longer writes build.json at the build root - update reconcile.sh AND this pin"


@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_loop_guard_holds_when_rebuild_never_yields_identity(tmp_path):
    """LOOP GUARD: no build.json + a 'successful' rebuild that STILL yields no build.json (the
    layout/permission-mismatch class) => the FIRST run rebuilds (action=rebuilt, built null); the
    SECOND run must NOT rebuild again — it holds with action=failed and exit 1. FAILS IF: the second
    run invokes the shim (the 15-minutely rebuild-forever loop this guard exists to prevent)."""
    tree = _make_tree(tmp_path, source_commit=None)   # no build.json, and the shim never creates one
    r1 = _run(tree)                                    # shim runs (exit 0) but writes no build.json
    assert r1.returncode == 0, r1.stderr
    assert tree["marker"].exists(), "first pass at this head is allowed to try a rebuild"
    st1 = _status(tree)
    assert st1 is not None and st1["action"] == "rebuilt" and not st1["built"]
    tree["marker"].unlink()
    r2 = _run(tree)
    assert r2.returncode == 1, "the guard must exit 1 so monitoring flags the structural mismatch"
    assert not tree["marker"].exists(), "the guard must NOT rebuild again at the same head"
    st2 = _status(tree)
    assert st2 is not None and st2["action"] == "failed"
    assert "structural mismatch" in r2.stderr


@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_loop_guard_rearmed_by_request_and_by_head_change(tmp_path):
    """The guard yields to deliberate intent: an explicit rebuild.request forces a fresh attempt, and
    a HEAD change re-arms normal behaviour. FAILS IF: a curator's button press is ignored while the
    guard holds, or a new publish stays un-built because the guard latched forever."""
    tree = _make_tree(tmp_path, source_commit=None)
    _run(tree)                        # attempt 1: rebuilt, no identity
    r_hold = _run(tree)               # guard holds
    assert r_hold.returncode == 1
    tree["marker"].unlink(missing_ok=True)
    # (a) explicit request => fresh attempt despite the hold
    (tree["state"] / "rebuild.request").write_text("{}", encoding="utf-8")
    r_req = _run(tree)
    assert tree["marker"].exists(), "an explicit rebuild.request must override the loop guard"
    assert r_req.returncode == 0
    # guard re-latches after that identity-less rebuild...
    tree["marker"].unlink()
    assert _run(tree).returncode == 1
    assert not tree["marker"].exists()
    # (b) ...and a HEAD change (a new publish) re-arms a normal rebuild attempt
    _advance_head(tree)
    r_head = _run(tree, env_extra={"SHIM_REBUILD": "1"})
    assert tree["marker"].exists(), "a new HEAD must release the guard"
    assert r_head.returncode == 0
    assert _status(tree)["action"] == "rebuilt"


@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_missing_data_dir_fails_early(tmp_path):
    """An AUSMT_DATA_DIR that does not exist (unmounted volume / .env typo) => rc=1 with one loud
    message, BEFORE any tree is fabricated. FAILS IF: the script mkdir-ps a phantom tree and settles
    into quiet sync_failed forever."""
    tree = _make_tree(tmp_path, source_commit="deadbeef")
    r = _run(tree, env_extra={"AUSMT_DATA_DIR": str(tmp_path / "not-mounted")})
    assert r.returncode == 1
    assert "does not exist" in r.stderr
    assert not (tmp_path / "not-mounted").exists(), "must not fabricate the data tree"
    assert not tree["marker"].exists()


@pytest.mark.skipif(os.name == "nt", reason="directory write-deny not enforceable via chmod on Windows")
@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_log_dir_exists_but_unwritable_fails_before_building(tmp_path):
    """logs/ EXISTS but is not writable (an ownership regression - `mkdir -p` alone would pass) =>
    fail before invoking the build, action=failed, rc=1, with the ownership-prep hint. FAILS IF: the
    writability probe is dropped and the failure only surfaces at the build redirect with no hint."""
    tree = _make_tree(tmp_path, source_commit="deadbeef")
    logs_dir = tree["data"] / "site-data" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.chmod(0o555)
    try:
        r = _run(tree, env_extra={"SHIM_REBUILD": "1"})
        assert r.returncode == 1
        assert not tree["marker"].exists(), "must NOT build when the log dir is unwritable"
        st = _status(tree)
        assert st is not None and st["action"] == "failed"
        assert "ownership prep" in r.stderr
    finally:
        logs_dir.chmod(0o755)


@pytest.mark.skipif(os.name == "nt", reason="directory write-deny not enforceable via chmod on Windows")
@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_state_dir_unwritable_fails_early_and_loud(tmp_path):
    """An unwritable gateway state dir (the missing one-time ownership prep) => the run fails EARLY
    with one actionable message and rc=1, BEFORE any sync/build. FAILS IF: the pass half-runs (shim
    invoked) or exits 0, hiding the misconfiguration."""
    tree = _make_tree(tmp_path, source_commit="deadbeef")
    state = tree["state"]
    state.chmod(0o555)
    try:
        r = _run(tree, env_extra={"SHIM_REBUILD": "1"})
        assert r.returncode == 1
        assert not tree["marker"].exists(), "nothing may run after the failed writability probe"
        assert "ownership prep" in r.stderr
    finally:
        state.chmod(0o755)


@pytest.mark.skipif(os.name == "nt", reason="directory write-deny not enforceable via chmod on Windows")
@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_log_dir_uncreatable_fails_before_building(tmp_path):
    """A logs/ dir that cannot be created (site-data not operator-writable — the other missing prep
    step) => fail BEFORE invoking the build, action=failed, rc=1. FAILS IF: the script builds a
    corpus it cannot log (undebuggable from the panel) or reports anything but failed."""
    tree = _make_tree(tmp_path, source_commit="deadbeef")
    site_data = tree["data"] / "site-data"
    site_data.chmod(0o555)
    try:
        r = _run(tree, env_extra={"SHIM_REBUILD": "1"})
        assert r.returncode == 1
        assert not tree["marker"].exists(), "must NOT build when the log dir cannot be created"
        st = _status(tree)
        assert st is not None and st["action"] == "failed"
        assert "log dir" in r.stderr
    finally:
        site_data.chmod(0o755)


@pytest.mark.skipif(not (_HAS_FLOCK and _HAS_GIT), reason="flock(1) not available on this host")
def test_lock_held_second_run_is_silent_noop(tmp_path):
    """A second reconcile run while the lock is held exits 0 WITHOUT touching the status file. FAILS
    IF: two runs both build (lock not honoured), or the second run rewrites/creates the status file.
    (skipif: no flock on this Windows dev box - noted in the report; the deploy host has flock.)"""
    tree = _make_tree(tmp_path, source_commit="deadbeef")
    lock = Path(tree["env"]["AUSMT_RECONCILE_LOCK"])
    # Hold the lock in a separate flock process for the duration of the second run.
    holder = subprocess.Popen(
        ["flock", "-n", str(lock), "-c", "sleep 3"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        import time
        time.sleep(0.3)  # let the holder acquire
        r = _run(tree, env_extra={"SHIM_REBUILD": "1"})
        assert r.returncode == 0
        assert not tree["marker"].exists(), "the locked-out run must NOT build"
        assert _status(tree) is None, "the locked-out run must NOT write the status file"
    finally:
        holder.terminate()
        holder.wait()


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits not meaningful on this filesystem")
@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_status_file_readable_by_gateway_uid(tmp_path):
    """The status file must be group/other-readable: its CONSUMER is the gateway container (uid
    10002) reading through the shared state dir, not the operator who wrote it. FAILS IF: the
    symlink-safe mktemp write ships its 0600 default again, so the file exists and the panel still
    reports no reconcile status."""
    tree = _make_tree(tmp_path, source_commit="placeholder")
    head = _git(tree["surveys"], "rev-parse", "--short=7", "HEAD")
    (tree["site"] / "build.json").write_text(json.dumps(
        {"build_id": "bid-mode", "engine_commit": "eng0000", "source_commit": head}),
        encoding="utf-8")
    r = _run(tree)
    assert r.returncode == 0, r.stderr
    mode = (tree["state"] / "reconcile-status.json").stat().st_mode
    assert mode & 0o044 == 0o044, (
        f"status file must be group+other readable for the gateway uid; mode is {oct(mode)}")


# --------------------------------------------------------------------------------------------------
# Stage 2b-ii: PAUSE auto-rebuild + ROLLBACK PIN. A fresh pause.flag suppresses the
# drift rebuild; a STALE flag (older than the expiry) is IGNORED (auto-expires); a rollback.pin holds
# reconcile off an auto-revert until an explicit rebuild.request moves forward. RED-then-green pins:
# each proves it can fail (the paused/pinned case does NOT rebuild; the expired/explicit case DOES).
# --------------------------------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_fresh_pause_flag_suppresses_drift_rebuild(tmp_path):
    """PAUSE PIN. With a FRESH pause.flag and drift (no rebuild.request), reconcile does
    NOT rebuild — action=paused, the make shim is NOT invoked, and the status exposes paused=true.
    FAILS IF a fresh pause still rebuilds on drift. Non-vacuous: the expiry test below (stale flag)
    DOES rebuild, so the flag — not a broken build path — is what suppresses it."""
    tree = _make_tree(tmp_path, source_commit="aaaaaaa")     # built != HEAD => drift
    _advance_head(tree)
    (tree["state"] / "pause.flag").write_text(
        json.dumps({"paused_at": "2026-07-12T00:00:00Z", "requested_by": "curator1"}), encoding="utf-8")
    r = _run(tree)
    assert r.returncode == 0, r.stderr
    assert not tree["marker"].exists(), "a fresh pause.flag must SUPPRESS the drift rebuild (shim not run)"
    st = _status(tree)
    assert st and st.get("action") == "paused", f"expected action=paused, got {st}"
    assert st.get("paused") is True, "reconcile status must expose the pause state"


@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_stale_pause_flag_is_expired_and_rebuilds(tmp_path):
    """PAUSE-EXPIRY PIN. A pause.flag OLDER than the expiry window is IGNORED - reconcile
    treats auto-rebuild as ACTIVE and rebuilds on drift. FAILS IF a stale pause flag still suppresses
    the rebuild (proven against a never-expire implementation). The flag's mtime is set 7 h old with a
    6 h expiry."""
    tree = _make_tree(tmp_path, source_commit="aaaaaaa")
    new_head = _advance_head(tree)
    flag = tree["state"] / "pause.flag"
    flag.write_text(json.dumps({"paused_at": "2026-07-11T00:00:00Z"}), encoding="utf-8")
    import time
    old = time.time() - 7 * 3600
    os.utime(flag, (old, old))                                # 7 h old, expiry default 360 min
    r = _run(tree, env_extra={"SHIM_REBUILD": "1", "AUSMT_RECONCILE_PAUSE_EXPIRY_MIN": "360"})
    assert r.returncode == 0, r.stderr
    assert tree["marker"].exists(), "a STALE pause.flag must NOT suppress the rebuild (auto-expired)"
    st = _status(tree)
    assert st and st.get("action") == "rebuilt", f"expected action=rebuilt after expiry, got {st}"
    assert st.get("pause_expired") is True, "status must mark the stale flag as expired"
    assert st.get("built", "").startswith(new_head[:7]), "the rebuild must have advanced the served commit"


@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_rollback_pin_holds_reconcile_off_auto_revert(tmp_path):
    """ROLLBACK-REPOINTS PIN (reconcile side). While a rollback.pin stands, reconcile must
    NOT auto-rebuild on drift (which would revert the manual rollback) — action=pinned, shim not run.
    FAILS IF a pinned rollback is silently reverted by the next tick."""
    tree = _make_tree(tmp_path, source_commit="aaaaaaa")     # served older build => drift vs HEAD
    _advance_head(tree)
    (tree["state"] / "rollback.pin").write_text(
        json.dumps({"pinned_build": "20260101T000000Z", "pinned_by": "curator1",
                    "pinned_at": "2026-07-12T00:00:00Z"}), encoding="utf-8")
    r = _run(tree)
    assert r.returncode == 0, r.stderr
    assert not tree["marker"].exists(), "a rollback.pin must HOLD reconcile off the auto-rebuild"
    st = _status(tree)
    assert st and st.get("action") == "pinned", f"expected action=pinned, got {st}"
    assert st.get("pinned") is True and st.get("pinned_build") == "20260101T000000Z", st


@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_explicit_rebuild_request_clears_rollback_pin(tmp_path):
    """A rollback.pin does NOT freeze serving forever: an explicit rebuild.request is a deliberate
    MOVE-FORWARD that clears the pin and rebuilds. FAILS IF a rebuild.request is ignored
    while pinned, or the pin survives the deliberate rebuild."""
    tree = _make_tree(tmp_path, source_commit="aaaaaaa")
    _advance_head(tree)
    pin = tree["state"] / "rollback.pin"
    pin.write_text(json.dumps({"pinned_build": "20260101T000000Z"}), encoding="utf-8")
    (tree["state"] / "rebuild.request").write_text("{}", encoding="utf-8")
    r = _run(tree, env_extra={"SHIM_REBUILD": "1"})
    assert r.returncode == 0, r.stderr
    assert tree["marker"].exists(), "an explicit rebuild.request must rebuild even while pinned"
    assert not pin.exists(), "the explicit move-forward must clear the rollback.pin"
    st = _status(tree)
    assert st and st.get("action") == "rebuilt", f"expected action=rebuilt, got {st}"
    assert st.get("pinned") is False, "the pin must be cleared after the deliberate rebuild"


@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_force_full_rebuild_flag_sets_cache_refresh(tmp_path):
    """FORCE-FULL PIN. A rebuild.request carrying `full: true` makes reconcile
    run the build in cache-REFRESH mode (AUSMT_BUILD_CACHE_MODE=refresh in the make environment); a
    plain request (no flag) leaves it at the default (empty => Makefile rw). FAILS IF the full flag does
    not reach the build's cache mode, or a plain request forces refresh. Observed via a make shim that
    records the env var it was invoked with."""
    tree = _make_tree(tmp_path, source_commit="aaaaaaa")
    _advance_head(tree)
    rec = tmp_path / "cache_mode.txt"
    make_shim = tmp_path / "make_cache_shim.sh"
    make_shim.write_text(
        "#!/bin/sh\n"
        f'printf "MODE=[%s]\n" "${{AUSMT_BUILD_CACHE_MODE:-<unset>}}" >> "{rec.as_posix()}"\n',
        encoding="utf-8")
    make_shim.chmod(0o755)
    env_extra = {"AUSMT_RECONCILE_MAKE": f"sh {make_shim.as_posix()}"}

    # full: true => refresh
    (tree["state"] / "rebuild.request").write_text('{"requested_by":"c1","full":true}', encoding="utf-8")
    _run(tree, env_extra=env_extra)
    # plain request => default (empty). The request itself forces a rebuild, so no new drift is needed.
    (tree["state"] / "rebuild.request").write_text('{"requested_by":"c1"}', encoding="utf-8")
    _run(tree, env_extra=env_extra)

    modes = [ln for ln in rec.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert modes[0] == "MODE=[refresh]", f"full:true must set cache-refresh, got {modes}"
    assert modes[1] in ("MODE=[]", "MODE=[<unset>]"), f"a plain request must NOT force refresh, got {modes}"


# ===================================================================================================
# Incident: systemd's TimeoutStartSec SIGTERMed a 60-minute-plus rebuild once an hour.
# The script had no signal handler and the Makefile prunes only after a SUCCESSFUL swap, so every
# killed attempt (a) wrote no status, leaving the curator panel showing the last CLEAN outcome and the
# loop guard unarmed, and (b) abandoned its half-written builds/<ts> forever.
# ===================================================================================================

def _seed_builds(tree: dict, names: list[str], served: str) -> Path:
    """Create builds/<name> dirs with strictly increasing mtimes (so `ls -1t` order is deterministic,
    newest LAST in `names`), and mark one of them as the SERVED build by giving it a byte-identical
    copy of current/build.json — which is how the script identifies it when `current` is not a
    resolvable symlink (MSYS `ln -s` silently makes a COPY on Windows, so the symlink path is not
    reliably exercisable here). Returns the builds dir."""
    import time
    bdir = tree["data"] / "site-data" / "builds"
    bdir.mkdir(parents=True, exist_ok=True)
    base = time.time() - 10_000
    for i, n in enumerate(names):
        d = bdir / n
        d.mkdir(exist_ok=True)
        (d / "filler.txt").write_text("x", encoding="utf-8")
        os.utime(d, (base + i * 60, base + i * 60))
    served_json = (tree["site"] / "build.json").read_bytes()
    (bdir / served / "build.json").write_bytes(served_json)
    # writing build.json bumped that dir's mtime; restore it so `ls -1t` order stays as declared
    idx = names.index(served)
    os.utime(bdir / served, (base + idx * 60, base + idx * 60))
    return bdir


def test_prune_runs_on_entry_even_when_the_pass_fails(tmp_path):
    """PRUNE-ON-ENTRY. Stale build dirs are collected at the START of every pass, so a RUN OF FAILURES
    cannot leak disk - the failure shape where an hourly killed rebuild left ~0.5 GB behind each
    time and the Makefile's own prune (inside the swap step) was never reached.
    FAILS IF a failing pass leaves more than KEEP_BUILDS build dirs behind, or prunes nothing at all."""
    tree = _make_tree(tmp_path, source_commit="aaaaaaa")
    _advance_head(tree)
    names = [f"2026081{i}T000000Z" for i in range(8)]     # 8 dirs, oldest first
    served = names[-1]                                    # the newest is the one being served
    bdir = _seed_builds(tree, names, served=served)
    assert len(list(bdir.iterdir())) == 8

    # The pass FAILS (shim exits 1) — the prune must still have happened, because it runs on entry.
    r = _run(tree, env_extra={"SHIM_FAIL": "1", "AUSMT_RECONCILE_KEEP_BUILDS": "3"})
    left = sorted(p.name for p in bdir.iterdir() if p.is_dir())
    assert _status(tree)["action"] == "failed", "precondition: this pass really did fail"
    # served (skipped, uncounted) + the 3 newest non-served
    expected = sorted([served] + names[-4:-1])
    assert left == expected, f"expected {expected} after a FAILED pass, got {left} (rc={r.returncode})"


def test_prune_never_deletes_the_build_being_served(tmp_path):
    """PRUNE SAFETY. The build `current` points at is skipped unconditionally, before any retention
    arithmetic — even when it is the OLDEST dir and far outside the keep window. Deleting it would
    take the portal down, which is strictly worse than keeping a few stale dirs.
    FAILS IF the served build is pruned."""
    tree = _make_tree(tmp_path, source_commit="aaaaaaa")
    _advance_head(tree)
    names = [f"2026082{i}T000000Z" for i in range(7)]
    served = names[0]                                     # the OLDEST — normally first to go
    bdir = _seed_builds(tree, names, served=served)

    _run(tree, env_extra={"SHIM_FAIL": "1", "AUSMT_RECONCILE_KEEP_BUILDS": "2"})
    left = sorted(p.name for p in bdir.iterdir() if p.is_dir())
    assert served in left, f"the SERVED build {served} was pruned - left={left}"
    expected = sorted([served] + names[-2:])              # served + the 2 newest
    assert left == expected, f"served + KEEP_BUILDS=2 newest expected {expected}, got {left}"


def test_prune_refuses_when_the_served_build_cannot_be_identified(tmp_path):
    """PRUNE FAIL-SAFE. If neither `current`'s symlink nor a build.json match identifies the served
    build, the prune does NOTHING and says why. Keeping stale directories is recoverable; deleting the
    live build takes the portal down.
    FAILS IF an unidentifiable layout still deletes build dirs, or does so silently."""
    tree = _make_tree(tmp_path, source_commit="aaaaaaa")
    _advance_head(tree)
    names = [f"2026083{i}T000000Z" for i in range(6)]
    bdir = tree["data"] / "site-data" / "builds"
    bdir.mkdir(parents=True, exist_ok=True)
    for n in names:                                       # NO build.json anywhere => unidentifiable
        (bdir / n).mkdir(exist_ok=True)

    r = _run(tree, env_extra={"SHIM_FAIL": "1", "AUSMT_RECONCILE_KEEP_BUILDS": "1"})
    left = sorted(p.name for p in bdir.iterdir() if p.is_dir())
    assert left == sorted(names), f"nothing may be pruned when the served build is unknown, lost: {set(names)-set(left)}"
    assert "cannot identify the served build" in (r.stdout + r.stderr), \
        "the refusal must be stated, not silent"


def test_sigterm_mid_build_records_failed_status(tmp_path):
    """SIGNAL TRAP. A pass killed mid-build (systemd TimeoutStartSec, or an operator stop) must still
    write reconcile-status.json with action=failed, naming the log and saying it was terminated.
    Without it the panel keeps showing the last clean outcome and the loop guard never arms, which is
    how the hourly retry loop stayed invisible for hours.
    FAILS IF no status is written, if the action is not `failed`, or if the detail does not say the run
    was terminated. Driven through a shell wrapper so a REAL SIGTERM is delivered on this box too,
    rather than skipping to CI."""
    tree = _make_tree(tmp_path, source_commit="aaaaaaa")
    _advance_head(tree)
    slow = tmp_path / "slow_shim.sh"
    slow.write_text("#!/bin/sh\necho 'shim: build started'\nsleep 30\n", encoding="utf-8")
    slow.chmod(0o755)
    logdir = tree["data"] / "site-data" / "logs"

    killer = tmp_path / "killer.sh"
    killer.write_text(
        "#!/bin/sh\n"
        f'sh "{_SCRIPT.as_posix()}" &\n'
        "p=$!\n"
        # wait (bounded) for the build log to appear => the build has started
        f'i=0; while [ $i -lt 150 ]; do ls "{logdir.as_posix()}"/*.build.log >/dev/null 2>&1 && break; '
        "i=$((i+1)); sleep 0.1; done\n"
        "sleep 0.5\n"
        "kill -TERM $p 2>/dev/null\n"
        "wait $p\n"
        'echo "rc=$?"\n',
        encoding="utf-8")
    killer.chmod(0o755)

    env = dict(tree["env"])
    env["AUSMT_RECONCILE_MAKE"] = f"sh {slow.as_posix()}"
    r = subprocess.run([_SH, str(killer)], capture_output=True, text=True, env=env, timeout=120)

    st = _status(tree)
    assert st is not None, f"a terminated pass wrote NO status at all\nstdout={r.stdout}\nstderr={r.stderr}"
    assert st["action"] == "failed", f"expected action=failed after SIGTERM, got {st['action']}"
    assert st.get("log_file"), "the status must name the build log so the failure is debuggable"
    tail = st.get("log_tail") or ""
    assert "TERMINATED by SIG" in tail, f"the detail must say the run was terminated, got: {tail[:200]!r}"
    assert "TimeoutStartSec" in tail, "the detail must point at the likely cause (the unit's timeout)"


# ---- kernel OOM kill named by name ------------------------------------------------------------------
# The engine build was OOM-killed by the kernel five nights running and every one reached the operator
# as "rebuild FAILED, see log tail" while the cause sat in `journalctl -k`. A failed rebuild must ask
# the kernel journal for ITS OWN build window and, when a kill is there, say so by name. Driven through
# a journalctl SHIM (AUSMT_RECONCILE_JOURNALCTL) that records the exact query it was asked and prints a
# real kernel line when SHIM_OOM=1, so the pin is on what the script ASKS and what it SAYS, never on the
# script's self-report.

_KERNEL_OOM_LINE = ("2026-08-15T02:41:07+0000 p350 kernel: Out of memory: Killed process 398616 (python) "
                    "total-vm:16632004kB, anon-rss:13740244kB, file-rss:0kB, shmem-rss:0kB, UID:10001 "
                    "pgtables:27404kB oom_score_adj:0")


def _journalctl_shim(tmp_path: Path) -> tuple[Path, Path]:
    """A journalctl stand-in: appends its argv to a query log, and prints the P350 kernel line (plus a
    non-OOM kernel line as noise) when SHIM_OOM=1, else nothing. Returns (shim, query_log)."""
    qlog = tmp_path / "journalctl.queries"
    shim = tmp_path / "journalctl.sh"
    shim.write_text(
        "#!/bin/sh\n"
        f'echo "$*" >> "{qlog.as_posix()}"\n'
        'if [ "${SHIM_OOM:-0}" = "1" ]; then\n'
        '  echo "2026-08-15T02:41:06+0000 p350 kernel: python invoked oom-killer: gfp_mask=0x140dca, order=0"\n'
        f'  echo "{_KERNEL_OOM_LINE}"\n'
        "fi\n"
        # SHIM_HINT=1: what modern journalctl does for a user OUTSIDE systemd-journal/adm whose own user
        # journal exists: exit 0, an EMPTY kernel view on stdout, only this notice on stderr (which -q
        # suppresses). SHIM_RC overrides the exit code (the older hard-denial shape).
        'if [ "${SHIM_HINT:-0}" = "1" ]; then\n'
        '  echo "-- No entries --"\n'
        '  echo "Hint: You are currently not seeing messages from other users and the system." >&2\n'
        '  echo "      Users in groups \'adm\', \'systemd-journal\' can see all messages." >&2\n'
        '  echo "      Pass -q to turn off this notice." >&2\n'
        "fi\n"
        'exit "${SHIM_RC:-0}"\n', encoding="utf-8")
    shim.chmod(0o755)
    return shim, qlog


@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_failed_build_oom_killed_is_named_by_name(tmp_path):
    """A failed rebuild whose build window holds a kernel OOM kill => the status says KILLED BY THE
    KERNEL FOR RUNNING OUT OF MEMORY, carries the kernel line itself, flags oom_kill=true, and STILL
    ends with the build log tail; the journal was asked for THIS build's window (-k, --since a UTC
    timestamp taken this run). FAILS IF: the failure is reported as a plain build failure (the incident),
    the kernel line is not shown, oom_kill is missing/false, the log tail is lost, or the script asked
    for the whole journal rather than the build window."""
    import datetime as _dt
    tree = _make_tree(tmp_path, source_commit="deadbeef")
    shim, qlog = _journalctl_shim(tmp_path)
    t0 = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
    r = _run(tree, env_extra={"SHIM_FAIL": "1", "SHIM_OOM": "1",
                              "AUSMT_RECONCILE_JOURNALCTL": f"{shim.as_posix()}"})
    assert r.returncode == 1, f"a failed build must still exit 1; got {r.returncode}"
    st = _status(tree)
    assert st is not None and st["action"] == "failed", st
    assert st.get("oom_kill") is True, f"status must flag the kill: {st}"
    tail = st.get("log_tail") or ""
    assert "KILLED BY THE KERNEL FOR RUNNING OUT OF MEMORY" in tail, tail[:300]
    assert "Killed process 398616 (python)" in tail and "anon-rss:13740244kB" in tail, tail
    assert "simulated build failure" in tail, "the build log tail must still follow the kernel lines"
    assert "KILLED BY THE KERNEL" in r.stderr, "the console line must name the cause too"
    # what was asked: the KERNEL journal (-k), since a UTC timestamp inside this run
    queries = qlog.read_text(encoding="utf-8").splitlines()
    assert queries, "the kernel journal was never consulted"
    q = queries[-1]
    assert "-k" in q.split() and "--since" in q.split(), q
    since = q.split("--since", 1)[1].split("--no-pager")[0].strip()
    when = _dt.datetime.strptime(since, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=_dt.timezone.utc)
    now = _dt.datetime.now(_dt.timezone.utc)
    assert t0 <= when <= now, f"--since must be this run's build start, got {since!r} (run began {t0})"


@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_failed_build_without_oom_is_a_plain_failure(tmp_path):
    """The journal was consulted but holds NO kill in the window => the ordinary failed status:
    oom_kill=false and a log_tail that is the build log, with no kernel wording. FAILS IF: an OOM is
    claimed without evidence (a false alarm sends an operator shopping for RAM), or oom_kill is absent."""
    tree = _make_tree(tmp_path, source_commit="deadbeef")
    shim, qlog = _journalctl_shim(tmp_path)
    r = _run(tree, env_extra={"SHIM_FAIL": "1", "AUSMT_RECONCILE_JOURNALCTL": f"{shim.as_posix()}"})
    assert r.returncode == 1
    st = _status(tree)
    assert st is not None and st["action"] == "failed", st
    assert st.get("oom_kill") is False, st
    tail = st.get("log_tail") or ""
    assert "simulated build failure" in tail
    assert "KILLED BY THE KERNEL" not in tail and "Out of memory" not in tail
    assert qlog.exists(), "the journal must still have been asked (a plain failure is a negative answer)"


@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_failed_build_with_no_journalctl_degrades_to_plain_failure(tmp_path):
    """No journalctl on the host (a non-systemd box, or the shim path does not exist) => the failure is
    still recorded exactly as before, oom_kill=false, exit 1. FAILS IF: a missing journalctl breaks or
    changes the failure path (the reporting must never depend on the diagnostic)."""
    tree = _make_tree(tmp_path, source_commit="deadbeef")
    r = _run(tree, env_extra={"SHIM_FAIL": "1",
                              "AUSMT_RECONCILE_JOURNALCTL": str(tmp_path / "no-such-journalctl")})
    assert r.returncode == 1
    st = _status(tree)
    assert st is not None and st["action"] == "failed" and st.get("oom_kill") is False, st
    assert "simulated build failure" in (st.get("log_tail") or "")


@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_failed_build_with_unreadable_journal_says_oom_not_ruled_out(tmp_path):
    """The REAL production shape of an unread journal: journalctl is present, the unit's user is outside
    systemd-journal/adm, so `journalctl -k` exits 0 with an EMPTY kernel view and only a stderr notice
    ("You are currently not seeing messages from other users and the system ... Pass -q to turn off
    this notice"). With -q, or with stderr thrown away, that is indistinguishable from a quiet kernel and
    the incident's OOM kill is recorded as a plain "rebuild FAILED" (exactly how it hid for a week). The
    failure must stay action=failed / oom_kill=false (nothing was SEEN), exit 1, keep the build log tail,
    but the detail must say the kernel journal could not be read, that an OOM kill CANNOT BE RULED OUT,
    and name the systemd-journal group fix; the console line must say so too; and the query must not
    pass -q. FAILS IF: the status is the plain failure with no such note, oom_kill is claimed true
    (nothing was seen), the log tail is lost, or -q is passed."""
    tree = _make_tree(tmp_path, source_commit="deadbeef")
    shim, qlog = _journalctl_shim(tmp_path)
    r = _run(tree, env_extra={"SHIM_FAIL": "1", "SHIM_HINT": "1",
                              "AUSMT_RECONCILE_JOURNALCTL": f"{shim.as_posix()}"})
    assert r.returncode == 1
    st = _status(tree)
    assert st is not None and st["action"] == "failed", st
    assert st.get("oom_kill") is False, f"nothing was seen, so oom_kill must not be claimed: {st}"
    tail = st.get("log_tail") or ""
    assert "KERNEL JOURNAL COULD NOT BE READ" in tail, tail[:400]
    assert "CANNOT BE" in tail and "RULED OUT" in tail, tail[:400]
    assert "not seeing messages from" in tail, "the detail must quote journalctl's own notice"
    assert "systemd-journal" in tail, "the detail must name the fix"
    assert "simulated build failure" in tail, "the build log tail must still follow the note"
    assert "KILLED BY THE KERNEL" not in tail, "an unread journal is not evidence of a kill"
    assert "NOT ruled out" in r.stderr and "systemd-journal" in r.stderr, r.stderr
    q = qlog.read_text(encoding="utf-8").splitlines()[-1].split()
    assert "-q" not in q, f"-q would suppress the only sign of an unread journal: {q}"


@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_failed_build_with_journalctl_denied_says_oom_not_ruled_out(tmp_path):
    """The older hard-denial shape: journalctl exits non-zero ("No journal files were opened due to
    insufficient permissions."). Same contract as the exit-0 hint: failed, oom_kill=false, note that a
    kill cannot be ruled out, log tail kept."""
    tree = _make_tree(tmp_path, source_commit="deadbeef")
    shim, _ = _journalctl_shim(tmp_path)
    r = _run(tree, env_extra={"SHIM_FAIL": "1", "SHIM_HINT": "1", "SHIM_RC": "1",
                              "AUSMT_RECONCILE_JOURNALCTL": f"{shim.as_posix()}"})
    assert r.returncode == 1
    st = _status(tree)
    assert st is not None and st["action"] == "failed" and st.get("oom_kill") is False, st
    tail = st.get("log_tail") or ""
    assert "KERNEL JOURNAL COULD NOT BE READ" in tail and "exited 1" in tail, tail[:400]
    assert "simulated build failure" in tail


@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_permission_hint_does_not_hide_a_visible_kill(tmp_path):
    """A partly readable journal (notice printed AND the kill line present) is a POSITIVE answer: the
    kill is named by name, oom_kill=true. FAILS IF: the notice downgrades a visible kill to "not ruled
    out"."""
    tree = _make_tree(tmp_path, source_commit="deadbeef")
    shim, _ = _journalctl_shim(tmp_path)
    r = _run(tree, env_extra={"SHIM_FAIL": "1", "SHIM_HINT": "1", "SHIM_OOM": "1",
                              "AUSMT_RECONCILE_JOURNALCTL": f"{shim.as_posix()}"})
    assert r.returncode == 1
    st = _status(tree)
    assert st is not None and st.get("oom_kill") is True, st
    tail = st.get("log_tail") or ""
    assert "KILLED BY THE KERNEL FOR RUNNING OUT OF MEMORY" in tail and "Killed process 398616 (python)" in tail
    assert "COULD NOT BE READ" not in tail
