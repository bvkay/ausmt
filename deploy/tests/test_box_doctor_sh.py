"""Box doctor (deploy/scripts/doctor-box.sh, ops-hardening O4).

Black-box over `sh` with a REAL git surveys-live tree (so the git/perms/staleness checks exercise real
git) plus stubs for docker/curl/systemctl. The load-bearing pins: the report is one labelled line per
check, the exit is non-zero iff any check FAILs, the reader wall PASSES only when the curator path
refuses (404) and FAILS on a breach (200), and the served-vs-HEAD comparison WARNs when the served build
is behind.

Skips on Windows / no POSIX sh / no git (platform + tool reasons, same class as the reconcile/preflight
suites). On the gateway-ci ubuntu lane git and sh are present, so it RUNS with nothing skipped and the
skip tripwire needs no allow entry.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_DOCTOR = _REPO / "deploy" / "scripts" / "doctor-box.sh"
_SH = shutil.which("sh") or shutil.which("bash")
_GIT = shutil.which("git")

pytestmark = [
    pytest.mark.skipif(_SH is None, reason="no POSIX sh/bash to run doctor-box.sh"),
    pytest.mark.skipif(_GIT is None, reason="git not present to build a surveys-live fixture"),
    pytest.mark.skipif(os.name == "nt", reason="POSIX sh stubs not meaningful on this filesystem"),
]

_DOCKER_STUB = """#!/bin/sh
case "$*" in
  *"ps --status running --services") printf 'portal\\ngateway\\nclamd\\n' ;;
  *) exit 0 ;;
esac
"""
_CURL_STUB = """#!/bin/sh
for a in "$@"; do url="$a"; done
case "$url" in
  *"/gateway/curator/queue") echo "${CURATOR_CODE:-404}" ;;
  *"/gateway/healthz") echo "${HEALTHZ_CODE:-200}" ;;
  *) echo 200 ;;
esac
"""
_SYSTEMCTL_STUB = """#!/bin/sh
case "$*" in
  "list-unit-files ausmt-reconcile.timer") echo "ausmt-reconcile.timer enabled enabled" ;;
  "is-enabled ausmt-reconcile.timer") echo enabled ;;
  *"LastTriggerUSec"*) echo "Fri 2026-07-25 09:45:00 UTC" ;;
  *) exit 0 ;;
esac
"""


def _git(sl: Path, *args: str) -> None:
    subprocess.run([_GIT, "-C", str(sl), *args], check=True, capture_output=True, text=True)


def _make_tree(tmp_path: Path, *, extra_commit: bool = False, dirty: bool = False) -> Path:
    """A data dir with a real surveys-live git checkout and a build.json whose source_commit is the FIRST
    commit's short hash. extra_commit advances HEAD past the served commit (staleness); dirty leaves an
    untracked file."""
    data = tmp_path / "data"
    sl = data / "surveys-live"
    (data / "site-data" / "current").mkdir(parents=True)
    sl.mkdir(parents=True)
    _git(sl, "init", "-q")
    _git(sl, "config", "user.email", "x@y.z")
    _git(sl, "config", "user.name", "x")
    _git(sl, "config", "core.sharedRepository", "group")
    (sl / "f1").write_text("a\n", encoding="utf-8")
    _git(sl, "add", "f1")
    _git(sl, "commit", "-qm", "one")
    served = subprocess.run([_GIT, "-C", str(sl), "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    # group-writable .git (the shared-group publish model the check asserts)
    subprocess.run(["chmod", "-R", "g+w", str(sl / ".git")], check=True)
    (data / "site-data" / "current" / "build.json").write_text(
        '{\n "build_id": "eng-%s-x",\n "source_commit": "%s",\n "generated": "2026-07-25T09:00:00Z"\n}\n'
        % (served, served), encoding="utf-8")
    if extra_commit:
        (sl / "f2").write_text("b\n", encoding="utf-8")
        _git(sl, "add", "f2")
        _git(sl, "commit", "-qm", "two")
    if dirty:
        (sl / "untracked-survey").write_text("x\n", encoding="utf-8")
    return data


def _env(tmp_path: Path, data: Path, **extra) -> dict:
    b = tmp_path / "bin"
    b.mkdir()
    for name, body in (("docker", _DOCKER_STUB), ("curl", _CURL_STUB), ("systemctl", _SYSTEMCTL_STUB)):
        p = b / name
        p.write_text(body, encoding="utf-8")
        p.chmod(0o755)
    envf = tmp_path / ".env"
    envf.write_text(f"AUSMT_DATA_DIR={data}\nAUSMT_CODE_DIR={tmp_path}\nOWNER=bvkay\nTAG=latest\n",
                    encoding="utf-8")
    env = dict(os.environ)
    env.update({
        "PROFILE": "gateway",
        "AUSMT_DOCTOR_DOCKER": str(b / "docker"),
        "AUSMT_DOCTOR_CURL": str(b / "curl"),
        "AUSMT_DOCTOR_SYSTEMCTL": str(b / "systemctl"),
        "AUSMT_DOCTOR_ENV": str(envf),
        "AUSMT_DOCTOR_COMPOSE": str(tmp_path / "compose.yaml"),
    })
    env.update(extra)
    return env


def _run(env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([_SH, str(_DOCTOR)], capture_output=True, text=True, env=env)


def test_report_all_pass_labelled_and_exit_zero(tmp_path):
    """A healthy box: every check line is labelled, the reader wall passes, and the run exits 0 (WARNs
    such as a missing default ACL are allowed and do not fail the exit)."""
    data = _make_tree(tmp_path)
    r = _run(_env(tmp_path, data))
    assert r.returncode == 0, f"a healthy box should exit 0:\n{r.stdout}\n{r.stderr}"
    assert "FAIL" not in r.stdout, f"no FAIL expected on a healthy box:\n{r.stdout}"
    body = [ln for ln in r.stdout.splitlines()
            if ln and not ln.startswith("=") and not ln.startswith("AusMT box doctor")
            and not ln.startswith("RESULT")]
    for ln in body:
        assert ln.split(" ", 1)[0] in ("PASS", "WARN", "FAIL"), f"unlabelled line: {ln!r}"
    assert any(ln.startswith("PASS reader: /gateway/curator/queue -> 404") for ln in body), (
        f"wall 2 curator refusal must PASS:\n{r.stdout}")


def test_wall_breach_curator_served_fails(tmp_path):
    """WALL 2 pin: if the curator path is SERVED (200) on the reader listener, the check must FAIL and
    the run must exit non-zero. FAILS IF a served workbench is reported green."""
    data = _make_tree(tmp_path)
    r = _run(_env(tmp_path, data, CURATOR_CODE="200"))
    assert any("WALL 2 BREACH" in ln and ln.startswith("FAIL") for ln in r.stdout.splitlines()), (
        f"a served curator path must FAIL as a wall breach:\n{r.stdout}")
    assert r.returncode != 0, "a wall breach must make the doctor exit non-zero"


def test_served_behind_head_warns(tmp_path):
    """Staleness hint: when surveys-live HEAD has advanced past the served source_commit, the served
    check must WARN (a publish has not been served yet)."""
    data = _make_tree(tmp_path, extra_commit=True)
    r = _run(_env(tmp_path, data))
    assert any(ln.startswith("WARN served:") and "BEHIND" in ln for ln in r.stdout.splitlines()), (
        f"a served build behind HEAD must WARN:\n{r.stdout}")


def test_dirty_surveys_live_fails(tmp_path):
    """An untracked entry under surveys-live (the incident-2026-07-11 class: built + served but git can
    never remove it) must FAIL the checkout-clean check and the run."""
    data = _make_tree(tmp_path, dirty=True)
    r = _run(_env(tmp_path, data))
    assert any(ln.startswith("FAIL surveys-live:") and "DIRTY" in ln for ln in r.stdout.splitlines()), (
        f"an untracked survey dir must FAIL the clean check:\n{r.stdout}")
    assert r.returncode != 0


def test_reconcile_timer_absent_fails(tmp_path):
    """The serve-reconcile timer is the agent that serves a publish automatically; if it is NOT installed
    the check must FAIL (its absence is a live suspect for a stale wall)."""
    data = _make_tree(tmp_path)
    # A systemctl stub that reports the timer as not installed.
    b = tmp_path / "bin2"
    b.mkdir()
    (b / "systemctl").write_text("#!/bin/sh\ncase \"$*\" in *list-unit-files*) exit 1;; *) exit 0;; esac\n",
                                 encoding="utf-8")
    (b / "systemctl").chmod(0o755)
    env = _env(tmp_path, data, AUSMT_DOCTOR_SYSTEMCTL=str(b / "systemctl"))
    r = _run(env)
    assert any(ln.startswith("FAIL reconcile:") and "NOT installed" in ln for ln in r.stdout.splitlines()), (
        f"an uninstalled reconcile timer must FAIL:\n{r.stdout}")
    assert r.returncode != 0
