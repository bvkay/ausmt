"""`make rebuild-data` takes the reconcile lock, so a manual rebuild and a timer tick never build at once.

reconcile.sh holds `flock -n` on its lock file (default $AUSMT_DATA_DIR/reconcile.lock) for a whole
pass, and its pass runs `make rebuild-data`. A rebuild started by hand took no lock, so a tick that
fired during it saw drift and started a second build into the same site-data. The target now takes
the same lock without waiting and refuses when it is held; a reconcile pass, which already holds it,
says so with AUSMT_RECONCILE_LOCK_HELD=1 and the target does not try to take it twice.

Driven through the real make with `flock` and `docker` replaced by recording stubs on PATH, so the
refusal is exercised on any host with make and sh; one leg holds the real lock where flock(1) exists.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_DEPLOY = _REPO / "deploy"
_MAKE = shutil.which("make")
_SH = shutil.which("sh")

pytestmark = [
    pytest.mark.skipif(_MAKE is None or _SH is None, reason="make and sh are needed to run the target"),
    pytest.mark.skipif(os.name == "nt", reason="POSIX shell stubs are not meaningful here"),
]

_RECORDER = '#!/bin/sh\nprintf "%s\\n" "$*" >> "$STUB_DIR/{name}.log"\nexit {rc}\n'


def _setup(tmp_path: Path, *, flock_rc: int | None) -> dict:
    """A data dir, a stub bin dir (docker always succeeds; flock exits flock_rc, or is absent when
    None and the host has none), and the env make runs with."""
    (tmp_path / "data" / "site-data").mkdir(parents=True)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stubs = {"docker": 0} if flock_rc is None else {"docker": 0, "flock": flock_rc}
    for name, rc in stubs.items():
        (bindir / name).write_text(_RECORDER.format(name=name, rc=rc), encoding="utf-8")
        (bindir / name).chmod(0o755)
    env = dict(os.environ)
    for var in ("AUSMT_RECONCILE_LOCK", "AUSMT_RECONCILE_LOCK_HELD"):
        env.pop(var, None)
    env.update({"PATH": f"{bindir}{os.pathsep}{env['PATH']}", "STUB_DIR": str(tmp_path),
                "AUSMT_DATA_DIR": str(tmp_path / "data")})
    return env


def _make(env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([_MAKE, "-s", "-C", str(_DEPLOY), "rebuild-data"],
                          capture_output=True, text=True, env=env)


def _calls(tmp_path: Path, name: str) -> list[str]:
    log = tmp_path / f"{name}.log"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def test_a_held_lock_refuses_the_rebuild_before_any_build_starts(tmp_path):
    """FAILS IF the target builds while another holder has the reconcile lock, or refuses without
    naming the lock it found held."""
    env = _setup(tmp_path, flock_rc=1)
    r = _make(env)
    assert r.returncode != 0, r.stdout + r.stderr
    assert _calls(tmp_path, "flock") == ["-n 9"], _calls(tmp_path, "flock")
    assert _calls(tmp_path, "docker") == [], "a refused rebuild must not start a build"
    lock = tmp_path / "data" / "reconcile.lock"
    assert "refused" in r.stderr.lower() and str(lock) in r.stderr, r.stderr


def test_a_free_lock_lets_the_rebuild_run_and_uses_the_reconcile_default_path(tmp_path):
    """FAILS IF the target takes no lock, takes it on a file other than reconcile.sh's default, or
    stops building when the lock is free."""
    env = _setup(tmp_path, flock_rc=0)
    r = _make(env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _calls(tmp_path, "flock") == ["-n 9"]
    assert (tmp_path / "data" / "reconcile.lock").exists(), "the lock is reconcile.sh's default file"
    assert _calls(tmp_path, "docker"), "a free lock must let the build run"


def test_the_lock_path_override_is_the_one_reconcile_reads(tmp_path):
    """FAILS IF the target ignores AUSMT_RECONCILE_LOCK, so on a host that moved reconcile's lock the
    two would lock different files."""
    env = _setup(tmp_path, flock_rc=0)
    env["AUSMT_RECONCILE_LOCK"] = str(tmp_path / "elsewhere.lock")
    assert _make(env).returncode == 0
    assert (tmp_path / "elsewhere.lock").exists()
    assert not (tmp_path / "data" / "reconcile.lock").exists()


def test_a_reconcile_pass_that_holds_the_lock_is_not_refused_by_its_own_lock(tmp_path):
    """FAILS IF the target tries to take the lock again inside a reconcile pass: a second open of
    the file is a second lock, which the pass's own lock would refuse."""
    env = _setup(tmp_path, flock_rc=1)
    env["AUSMT_RECONCILE_LOCK_HELD"] = "1"
    r = _make(env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _calls(tmp_path, "flock") == [], "the held lock must not be taken twice"
    assert _calls(tmp_path, "docker")


@pytest.mark.skipif(shutil.which("flock") is None, reason="flock(1) not available on this host")
def test_the_real_lock_held_by_another_process_refuses(tmp_path):
    """The same refusal against the real flock(1): another process holds the default lock file."""
    env = _setup(tmp_path, flock_rc=None)
    lock = tmp_path / "data" / "reconcile.lock"
    holder = subprocess.Popen(["flock", "-n", str(lock), "-c", "sleep 5"])
    try:
        time.sleep(0.5)
        r = _make(env)
        assert r.returncode != 0 and "refused" in r.stderr.lower(), r.stdout + r.stderr
        assert _calls(tmp_path, "docker") == []
    finally:
        holder.wait()
