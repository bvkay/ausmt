"""C40 serve-reconcile host agent (deploy/scripts/reconcile.sh) — decision-logic tests.

The reconcile agent is POSIX sh, so it is tested as a BLACK BOX through `sh` over a fake data tree
built under tmp_path: a real git origin + a tracking surveys-live checkout, a fabricated served
build.json, a gateway state dir, and a MAKE SHIM (AUSMT_RECONCILE_MAKE) that records its invocation
and — when the case needs a "successful rebuild" — rewrites build.json to the current HEAD so the
NEXT read sees the corpus advance. Every assertion is an INDEPENDENT OBSERVABLE (the shim's
invocation-marker file, the request file's existence, the status JSON's action, the process exit
code, the log file), never the script's own self-report.

Each test names its failure criterion in the docstring (Invariant 10). The cases (design C40 §3/§4,
brief note 6c):
  noop         head == built, no request  -> shim NOT invoked, action=noop, exit 0
  drift        head != built              -> shim invoked, action=rebuilt, log written + pruned, exit 0
  request      head == built + request    -> shim invoked, request consumed, action=rebuilt, exit 0
  sync_failed  diverged surveys-live      -> shim NOT invoked, action=sync_failed, exit 0
  failed       shim exits 1               -> action=failed, exit 1, log_tail populated
  dry-run      --dry-run on a drift        -> shim NOT invoked, NO status write, exit 0
  lock-held    a concurrent run holds flock -> second run exits 0, status untouched  (needs flock)

WINDOWS: there is no flock(1) here, so the lock-held case skipif's on its absence and is NOTED in the
report; ALL other cases run on this machine (the brief's requirement) — reconcile.sh runs bare
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
    # (2026-07-08) failed because BOTH the script and this fixture assumed current/data/build.json —
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
    import time
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
    timer. This is the §4 'never build from a state we cannot fast-forward to' guarantee."""
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


@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_build_json_path_matches_engine_layout():
    """CROSS-ARTIFACT PIN (the 2026-07-08 incident): the script's BUILD_JSON path and the engine's
    write site must agree. The engine writes build.json at the BUILD ROOT (`out / "build.json"` in
    build_portal.py); Caddy's handle_path strips /data before the filesystem, so the /data/build.json
    URL maps to that same root file. FAILS IF: the script re-grows a data/ segment, or the engine
    moves its build.json write site without this pin (and therefore the script) being updated."""
    script = _SCRIPT.read_text(encoding="utf-8")
    assert 'BUILD_JSON="$SITE_DATA/current/build.json"' in script, \
        "reconcile.sh must read build.json at the build ROOT (current/build.json)"
    assert "current/data/build.json" not in script, \
        "the phantom data/ segment is the exact 2026-07-08 rebuild-loop bug"
    engine_src = (_REPO / "engine" / "extract" / "build_portal.py").read_text(encoding="utf-8")
    assert '(out / "build.json")' in engine_src, \
        "engine no longer writes build.json at the build root — update reconcile.sh AND this pin"


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


@pytest.mark.skipif(os.name == "nt", reason="directory write-deny not enforceable via chmod on Windows")
@pytest.mark.skipif(not _HAS_GIT, reason="git required for the reconcile fake tree")
def test_state_dir_unwritable_fails_early_and_loud(tmp_path):
    """An unwritable gateway state dir (the missing one-time ownership prep) => the run fails EARLY
    with one actionable message and rc=1, BEFORE any sync/build. FAILS IF: the pass half-runs (shim
    invoked) or exits 0, hiding the misconfiguration (the 2026-07-08 scattered-errors symptom)."""
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
    (skipif: no flock on this Windows dev box — noted in the C40 report; the deploy host has flock.)"""
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
