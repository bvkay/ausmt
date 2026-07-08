"""Off-box pull agent (deploy/scripts/pull-backup.sh) — pull / prune / fail-loud tests.

pull-backup.sh runs on the operator's Mac (or any Linux laptop / cron) and pulls the `latest` snapshot
off the box over the tailnet. It is POSIX sh with NO personal hostnames baked in — everything comes
from env/flags. It shells out to ssh (to resolve what `latest` points to on the remote) and to
rsync-or-scp (to copy the snapshot). Those three commands are OVERRIDABLE so the tests can drive the
script black-box with SHIMS that record their invocation instead of touching a real host:
  AUSMT_PULL_SSH    resolve-latest transport (shim echoes a fixed snapshot name)
  AUSMT_PULL_RSYNC  the copy command (shim records argv + fabricates the destination tree)
  AUSMT_PULL_SCP    the fallback copy command

Every assertion is an INDEPENDENT OBSERVABLE — the shim's recorded-argv file, the destination tree the
shim created, the local retention count, the exit code, the stderr — never the script's self-report.
Each test names its failure criterion (Invariant 10). These run in CI on ubuntu (nothing skipped);
symlink/mode-only assertions skipif on Windows with a reason."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "deploy" / "scripts" / "pull-backup.sh"

_SH = shutil.which("sh") or shutil.which("bash")
pytestmark = pytest.mark.skipif(_SH is None, reason="no POSIX sh/bash to run pull-backup.sh")


def _shims(tmp_path: Path, *, snapshot="20260708T032000Z", ssh_fail=False, rsync_fail=False) -> dict:
    """Write ssh + rsync + scp shims. The ssh shim, invoked to resolve `latest`, echoes the snapshot
    name (or exits 1 to simulate an unreachable remote). The rsync/scp shims record their argv and
    fabricate the local destination dir the real copy would have produced."""
    ssh_marker = tmp_path / "ssh.argv"
    rsync_marker = tmp_path / "rsync.argv"
    scp_marker = tmp_path / "scp.argv"

    ssh = tmp_path / "ssh.sh"
    ssh.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$*" >> "{ssh_marker.as_posix()}"\n'
        + ("echo 'ssh: connection refused' >&2\nexit 255\n" if ssh_fail
           else f'printf "%s\\n" "{snapshot}"\n'),
        encoding="utf-8")
    ssh.chmod(0o755)

    # rsync/scp shim: last argv token is the local dest dir; create it + drop a fake gateway.sqlite so
    # the test sees a materialised snapshot. Records argv for the invocation assertions. @MARKER@ is a
    # placeholder (str.replace, not %-formatting, so the literal shell %s tokens are left alone).
    copy_body = (
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >> "@MARKER@"\n'
        + ("echo 'copy: no route to host' >&2\nexit 1\n" if rsync_fail else
           "# the destination dir is the LAST argument\n"
           "for a in \"$@\"; do dest=\"$a\"; done\n"
           "mkdir -p \"$dest\"\n"
           "printf 'db\\n' > \"$dest/gateway.sqlite\"\n"
           "printf '{}\\n' > \"$dest/reconcile-status.json\"\n"))
    rsync = tmp_path / "rsync.sh"
    rsync.write_text(copy_body.replace("@MARKER@", rsync_marker.as_posix()), encoding="utf-8")
    rsync.chmod(0o755)
    scp = tmp_path / "scp.sh"
    scp.write_text(copy_body.replace("@MARKER@", scp_marker.as_posix()), encoding="utf-8")
    scp.chmod(0o755)

    return {"ssh": ssh, "rsync": rsync, "scp": scp, "snapshot": snapshot,
            "ssh_marker": ssh_marker, "rsync_marker": rsync_marker, "scp_marker": scp_marker}


def _env(tmp_path: Path, shims: dict, *, remote="op@box:/srv/ausmt/backups",
         dest: Path | None = None, use_scp=False) -> tuple[dict, Path]:
    dest = dest or (tmp_path / "local-backups")
    env = dict(os.environ)
    env["AUSMT_BACKUP_REMOTE"] = remote
    env["AUSMT_BACKUP_DEST"] = str(dest)
    env["AUSMT_PULL_SSH"] = f"sh {shims['ssh'].as_posix()}"
    if use_scp:
        # Force the scp path by making rsync "unavailable": point AUSMT_PULL_RSYNC at a missing cmd.
        env["AUSMT_PULL_RSYNC"] = "definitely-not-rsync-xyz"
        env["AUSMT_PULL_SCP"] = f"sh {shims['scp'].as_posix()}"
    else:
        env["AUSMT_PULL_RSYNC"] = f"sh {shims['rsync'].as_posix()}"
        env["AUSMT_PULL_SCP"] = f"sh {shims['scp'].as_posix()}"
    return env, dest


def _run(env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([_SH, str(_SCRIPT), *args], capture_output=True, text=True, env=env)


def _snapshots(dest: Path) -> list[Path]:
    if not dest.exists():
        return []
    return sorted(p for p in dest.iterdir() if p.is_dir() and p.name != "latest")


# --------------------------------------------------------------------------------------------------

def test_pull_resolves_latest_and_copies_into_dest(tmp_path):
    """A pull resolves `latest` on the remote (via the ssh shim) then copies that snapshot into
    DEST/<snapshot>/ (via the rsync shim). FAILS IF: ssh is not consulted, rsync is not invoked, or the
    destination snapshot dir with the DB does not materialise."""
    shims = _shims(tmp_path)
    env, dest = _env(tmp_path, shims)
    r = _run(env)
    assert r.returncode == 0, r.stderr
    assert shims["ssh_marker"].exists(), "must ssh to resolve `latest`"
    assert shims["rsync_marker"].exists(), "must invoke rsync to copy the snapshot"
    snaps = _snapshots(dest)
    assert [p.name for p in snaps] == [shims["snapshot"]], snaps
    assert (dest / shims["snapshot"] / "gateway.sqlite").is_file()
    # The rsync invocation must reference the resolved snapshot on the remote, not the bare `latest`.
    argv = shims["rsync_marker"].read_text(encoding="utf-8")
    assert shims["snapshot"] in argv, f"rsync must pull the RESOLVED snapshot; argv={argv!r}"


def test_falls_back_to_scp_when_no_rsync(tmp_path):
    """With rsync unavailable, the script falls back to scp and still lands the snapshot. FAILS IF: the
    absence of rsync aborts the pull, or scp is never invoked."""
    shims = _shims(tmp_path)
    env, dest = _env(tmp_path, shims, use_scp=True)
    r = _run(env)
    assert r.returncode == 0, r.stderr
    assert shims["scp_marker"].exists(), "must fall back to scp when rsync is absent"
    assert (dest / shims["snapshot"] / "gateway.sqlite").is_file()


def test_prune_keeps_default_30(tmp_path):
    """With 35 pre-existing local snapshot dirs, a pull prunes to the newest 30 (29 old kept + this
    pull's = 30). FAILS IF: pruning does not run (>30) or over-prunes (<30)."""
    shims = _shims(tmp_path)
    env, dest = _env(tmp_path, shims)
    dest.mkdir(parents=True, exist_ok=True)
    for i in range(35):
        (dest / f"20200101T0000{i:02d}Z").mkdir()
    r = _run(env)
    assert r.returncode == 0, r.stderr
    assert len(_snapshots(dest)) == 30, f"expected 30 after prune, got {len(_snapshots(dest))}"


def test_retain_override(tmp_path):
    """A retention override (env AUSMT_BACKUP_RETAIN=5) keeps only the newest 5. FAILS IF: the override
    is ignored and the default 30 is used."""
    shims = _shims(tmp_path)
    env, dest = _env(tmp_path, shims)
    env["AUSMT_BACKUP_RETAIN"] = "5"
    dest.mkdir(parents=True, exist_ok=True)
    for i in range(10):
        (dest / f"20200101T0000{i:02d}Z").mkdir()
    r = _run(env)
    assert r.returncode == 0, r.stderr
    assert len(_snapshots(dest)) == 5, f"expected 5 after prune, got {len(_snapshots(dest))}"


def test_missing_remote_config_fails_loud(tmp_path):
    """No AUSMT_BACKUP_REMOTE => rc!=0 with an actionable message BEFORE any ssh/copy. FAILS IF: it
    silently succeeds or invokes the transport with an empty remote."""
    shims = _shims(tmp_path)
    env, _dest = _env(tmp_path, shims)
    del env["AUSMT_BACKUP_REMOTE"]
    r = _run(env)
    assert r.returncode != 0
    assert "REMOTE" in r.stderr or "remote" in r.stderr.lower()
    assert not shims["ssh_marker"].exists(), "must not ssh with no remote configured"


def test_unreachable_remote_fails_loud(tmp_path):
    """An ssh that cannot reach the box (resolve-latest fails) => rc!=0 with a clear message, and NO
    partial snapshot dir left behind. FAILS IF: the failure is swallowed (exit 0) or a copy is
    attempted against an unresolved `latest`."""
    shims = _shims(tmp_path, ssh_fail=True)
    env, dest = _env(tmp_path, shims)
    r = _run(env)
    assert r.returncode != 0, "an unreachable remote must fail"
    assert "unreachable" in r.stderr.lower() or "resolve" in r.stderr.lower() \
        or "reach" in r.stderr.lower()
    assert not shims["rsync_marker"].exists(), "must not copy when `latest` could not be resolved"
    assert _snapshots(dest) == [], "no snapshot dir may be left behind on a failed pull"


def test_copy_failure_is_reported(tmp_path):
    """A transport that resolves `latest` but fails the copy => rc!=0. FAILS IF: a failed copy is
    reported as success."""
    shims = _shims(tmp_path, rsync_fail=True)
    env, dest = _env(tmp_path, shims)
    r = _run(env)
    assert r.returncode != 0, "a failed copy must fail the run"
