"""install-frontdoor.sh in-place reload logic (ops-hardening O1).

Black-box over `sh`: a copy of the real install script is run in a tmp dir with a fabricated
.env/Caddyfile/compose.yaml and a PATH of stubs (docker, sudo) that record every docker invocation, so
the test drives the actual reload/fallback control flow without a real Docker or VPS. The three cases
the O1 design turns on:
  * already-running + reload OK  -> a `caddy reload` runs, NO restart;
  * already-running + reload FAILS -> a LOUD warning + a `compose restart frontdoor` fallback;
  * fresh (not running)          -> neither reload nor restart (up -d started it clean).

Skips on Windows / a host with no POSIX sh (the same platform reason the reconcile/preflight suites use);
on the gateway-ci ubuntu lane it RUNS with nothing skipped, so the skip tripwire needs no allow entry.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "deploy" / "frontdoor" / "install-frontdoor.sh"
_SH = shutil.which("sh") or shutil.which("bash")

pytestmark = [
    pytest.mark.skipif(_SH is None, reason="no POSIX sh/bash to run install-frontdoor.sh"),
    pytest.mark.skipif(os.name == "nt", reason="POSIX sh stubs not meaningful on this filesystem"),
]

# A docker stub: records argv to $STUB_LOG and behaves per the invocation. `ps -q frontdoor` prints a
# container id only when $STUB_RUNNING is set (already-running); `exec ... caddy reload` exits
# $STUB_RELOAD_RC; everything else succeeds.
_DOCKER_STUB = """#!/bin/sh
printf '%s\\n' "$*" >> "$STUB_LOG"
case "$*" in
  "compose version") exit 0 ;;
  *"ps -q frontdoor") [ -n "${STUB_RUNNING:-}" ] && printf 'stubcid123\\n'; exit 0 ;;
  *"caddy validate"*) exit 0 ;;
  *"up -d") exit 0 ;;
  *"exec -T frontdoor caddy reload"*) exit "${STUB_RELOAD_RC:-0}" ;;
  *"restart frontdoor") exit 0 ;;
  *) exit 0 ;;
esac
"""

_SUDO_STUB = "#!/bin/sh\nexit 0\n"  # no-op: skip the real `sudo mkdir -p /var/log/caddy`


def _setup(tmp_path: Path) -> tuple[Path, dict]:
    work = tmp_path / "frontdoor"
    work.mkdir()
    shutil.copy(_SCRIPT, work / "install-frontdoor.sh")
    (work / "Caddyfile").write_text("# stub\n", encoding="utf-8")
    (work / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    (work / ".env").write_text(
        "AUSMT_PUBLIC_NAME=ausmt.au\n"
        "AUSMT_BOX_READER_UPSTREAM=http://ausmt-box:8445\n"
        "AUSMT_ACME_EMAIL=x@y.org\n", encoding="utf-8")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "docker").write_text(_DOCKER_STUB, encoding="utf-8")
    (bindir / "sudo").write_text(_SUDO_STUB, encoding="utf-8")
    for f in ("docker", "sudo"):
        (bindir / f).chmod(0o755)
    log = tmp_path / "docker.log"
    env = dict(os.environ)
    env["PATH"] = f"{bindir}:{env['PATH']}"
    env["STUB_LOG"] = str(log)
    return work, env


def _run(work: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([_SH, str(work / "install-frontdoor.sh")],
                          capture_output=True, text=True, env=env, cwd=str(work))


def test_running_edge_reloads_in_place_no_restart(tmp_path):
    """Already-running + reload OK: a `caddy reload` must run and there must be NO restart (the whole
    point of O1 -- a graceful in-place reload, not a bounce). FAILS IF reload is skipped or a restart
    fires anyway."""
    work, env = _setup(tmp_path)
    env["STUB_RUNNING"] = "yes"
    env["STUB_RELOAD_RC"] = "0"
    r = _run(work, env)
    assert r.returncode == 0, f"installer failed: {r.stdout}\n{r.stderr}"
    calls = Path(env["STUB_LOG"]).read_text(encoding="utf-8")
    assert "caddy reload" in calls, f"a running edge must be reloaded in place; docker calls:\n{calls}"
    assert "restart frontdoor" not in calls, (
        f"a successful reload must NOT also restart; docker calls:\n{calls}")


def test_running_edge_reload_failure_falls_back_to_restart_loudly(tmp_path):
    """Already-running + reload FAILS: the installer must WARN loudly and fall back to a
    `compose restart frontdoor` so the new config still lands. FAILS IF there is no restart fallback or
    no loud warning."""
    work, env = _setup(tmp_path)
    env["STUB_RUNNING"] = "yes"
    env["STUB_RELOAD_RC"] = "1"
    r = _run(work, env)
    assert r.returncode == 0, f"installer should recover via restart: {r.stdout}\n{r.stderr}"
    calls = Path(env["STUB_LOG"]).read_text(encoding="utf-8")
    assert "caddy reload" in calls, "reload must be attempted first"
    assert "restart frontdoor" in calls, (
        f"a failed reload must fall back to a restart; docker calls:\n{calls}")
    assert "WARNING" in r.stderr, f"the fallback must be LOUD (WARNING on stderr); stderr:\n{r.stderr}"


def test_fresh_install_neither_reloads_nor_restarts(tmp_path):
    """Not running (fresh install): `up -d` starts the container against the current file, so there must
    be NO reload and NO restart. FAILS IF the installer reloads/restarts a container it just started."""
    work, env = _setup(tmp_path)
    env.pop("STUB_RUNNING", None)
    r = _run(work, env)
    assert r.returncode == 0, f"fresh install failed: {r.stdout}\n{r.stderr}"
    calls = Path(env["STUB_LOG"]).read_text(encoding="utf-8")
    assert "caddy reload" not in calls, f"a fresh install must not reload; docker calls:\n{calls}"
    assert "restart frontdoor" not in calls, f"a fresh install must not restart; docker calls:\n{calls}"
    assert "up -d" in calls, "a fresh install must still bring the stack up"
