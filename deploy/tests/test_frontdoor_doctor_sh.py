"""VPS front-door doctor (deploy/frontdoor/doctor.sh, ops-hardening O4 + O3 zombie kit).

Black-box over `sh`. Every external command the doctor uses is overridable by an AUSMT_DOCTOR_* env var,
so the test points each at a tiny stub and drives the real report/exit/hash-compare/zombie-grouping logic
with no docker/tailscale/VPS. The load-bearing pins: the report is one labelled line per check, the exit
is non-zero iff any check FAILs, the config check PASSES on a hash match and FAILS on a mismatch (the O1
stale-config trap), and the zombie kit NAMES the top leaker by parent PID.

Skips on Windows / no POSIX sh (platform reason, same as the reconcile/preflight suites); RUNS with
nothing skipped on the gateway-ci ubuntu lane, so the skip tripwire needs no allow entry.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_DOCTOR = _REPO / "deploy" / "frontdoor" / "doctor.sh"
_SH = shutil.which("sh") or shutil.which("bash")

pytestmark = [
    pytest.mark.skipif(_SH is None, reason="no POSIX sh/bash to run doctor.sh"),
    pytest.mark.skipif(os.name == "nt", reason="POSIX sh stubs not meaningful on this filesystem"),
]

_DOCKER_STUB = """#!/bin/sh
case "$*" in
  *"ps -q frontdoor") echo cid ;;
  *"inspect -f"*) echo running ;;
  *"exec -T frontdoor sha256sum"*) echo "$FAKE_HASH  /etc/caddy/Caddyfile" ;;
  *) exit 0 ;;
esac
"""
_CURL_STUB = '#!/bin/sh\necho "${CURL_CODE:-200}"\n'
_TAILSCALE_STUB = '#!/bin/sh\ncase "$1" in status) echo "100.1.2.3 ausmt-box linux -"; exit 0;; esac\n'
_OPENSSL_STUB = """#!/bin/sh
case "$*" in
  *s_client*) echo CERT ;;
  *x509*enddate*) echo "notAfter=${CERT_ENDDATE:-Jul 25 12:00:00 2027 GMT}" ;;
esac
"""
_DIG_STUB = '#!/bin/sh\necho "${DIG_IP:-203.0.113.9}"\n'
# ps stub: emits fixture zombie rows for `-eo stat=,ppid=,comm=` and a parent name for `-o args= -p PID`.
_PS_STUB = """#!/bin/sh
case "$*" in
  *"-eo stat"*) printf '%b' "${PS_ROWS:-S 1 init\\n}" ;;
  *"-o args= -p 4242") echo "/usr/bin/leaky-parent --serve" ;;
  *"-o args= -p 9001") echo "ssh caddylog@ausmt-vps" ;;
  *) echo "" ;;
esac
"""


def _bindir(tmp_path: Path) -> Path:
    b = tmp_path / "bin"
    b.mkdir()
    for name, body in (("docker", _DOCKER_STUB), ("curl", _CURL_STUB), ("tailscale", _TAILSCALE_STUB),
                       ("openssl", _OPENSSL_STUB), ("dig", _DIG_STUB), ("ps", _PS_STUB)):
        p = b / name
        p.write_text(body, encoding="utf-8")
        p.chmod(0o755)
    return b


def _env(tmp_path: Path, caddyfile: Path, **extra) -> dict:
    b = _bindir(tmp_path)
    envf = tmp_path / ".env"
    envf.write_text("AUSMT_PUBLIC_NAME=ausmt.au\nAUSMT_BOX_READER_UPSTREAM=http://ausmt-box:8445\n",
                    encoding="utf-8")
    env = dict(os.environ)
    env.update({
        "AUSMT_DOCTOR_DOCKER": str(b / "docker"),
        "AUSMT_DOCTOR_CURL": str(b / "curl"),
        "AUSMT_DOCTOR_TAILSCALE": str(b / "tailscale"),
        "AUSMT_DOCTOR_OPENSSL": str(b / "openssl"),
        "AUSMT_DOCTOR_DIG": str(b / "dig"),
        "AUSMT_DOCTOR_PS": str(b / "ps"),
        "AUSMT_DOCTOR_ENV": str(envf),
        "AUSMT_DOCTOR_CADDYFILE": str(caddyfile),
        "AUSMT_DOCTOR_COMPOSE": str(tmp_path / "compose.yaml"),
        "AUSMT_DOCTOR_DISK_PATH": "/",
        "AUSMT_DOCTOR_EXPECT_IP": "203.0.113.9",
    })
    env.update(extra)
    return env


def _run(env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([_SH, str(_DOCTOR), *args], capture_output=True, text=True, env=env)


def _caddyfile(tmp_path: Path, text: str = "# doctor test caddyfile\n") -> Path:
    p = tmp_path / "Caddyfile"
    p.write_text(text, encoding="utf-8")
    return p


def test_report_all_pass_is_labelled_and_exits_zero(tmp_path):
    """With every probe green the report must be one labelled PASS/WARN/FAIL line per check, end in a
    PASS RESULT, and exit 0. FAILS IF a check line is unlabelled or the exit is non-zero on an all-green
    run."""
    cf = _caddyfile(tmp_path)
    env = _env(tmp_path, cf, FAKE_HASH=hashlib.sha256(cf.read_bytes()).hexdigest())
    r = _run(env, "report")
    assert r.returncode == 0, f"all-green report should exit 0:\n{r.stdout}\n{r.stderr}"
    body = [ln for ln in r.stdout.splitlines()
            if ln and not ln.startswith("=") and not ln.startswith("AusMT front-door doctor")
            and not ln.startswith("RESULT")]
    assert body, "expected check lines"
    for ln in body:
        assert ln.split(" ", 1)[0] in ("PASS", "WARN", "FAIL"), f"unlabelled check line: {ln!r}"
    assert "FAIL" not in r.stdout, f"no check should FAIL on an all-green run:\n{r.stdout}"
    assert r.stdout.rstrip().splitlines()[-1].startswith("RESULT: PASS")


def test_config_hash_match_passes(tmp_path):
    """O1 trap, green side: when the container's mounted Caddyfile hashes EQUAL to the repo file, the
    config check PASSES. Proves the FAIL pin below is non-vacuous."""
    cf = _caddyfile(tmp_path)
    env = _env(tmp_path, cf, FAKE_HASH=hashlib.sha256(cf.read_bytes()).hexdigest())
    r = _run(env, "report")
    assert any(ln.startswith("PASS config:") for ln in r.stdout.splitlines()), (
        f"a matching config hash must PASS:\n{r.stdout}")


def test_config_hash_mismatch_fails_and_exits_nonzero(tmp_path):
    """O1 trap, red side: when the RUNNING container's Caddyfile hash DIFFERS from the repo file, the
    config check must FAIL and the whole run must exit non-zero (so it can gate an alert). FAILS IF a
    drifted running config is reported green."""
    cf = _caddyfile(tmp_path)
    env = _env(tmp_path, cf, FAKE_HASH="deadbeef" * 8)
    r = _run(env, "report")
    assert any(ln.startswith("FAIL config:") for ln in r.stdout.splitlines()), (
        f"a mismatched config hash must FAIL:\n{r.stdout}")
    assert r.returncode != 0, "any FAIL must make the doctor exit non-zero"
    assert r.stdout.rstrip().splitlines()[-1].startswith("RESULT: FAIL")


def test_zombie_kit_names_top_leaker_by_parent(tmp_path):
    """O3: the zombie kit must count Z-state procs and group them by PARENT PID with the heaviest parent
    at the top (the named leaker). Fixture: ppid 4242 has two zombies, ppid 9001 has one, so 4242 must
    lead. FAILS IF the kit does not aggregate by parent or does not surface the top parent first."""
    cf = _caddyfile(tmp_path)
    rows = "Z 4242 defunct-a\\nZ 4242 defunct-b\\nZ 9001 defunct-c\\nS 1 init\\n"
    env = _env(tmp_path, cf, PS_ROWS=rows)
    r = _run(env, "zombies")
    assert r.returncode == 0, f"the kit is read-only and should exit 0:\n{r.stdout}"
    assert "3" in r.stdout.splitlines()[2], f"expected a total count of 3 zombies:\n{r.stdout}"
    grouped = [ln for ln in r.stdout.splitlines() if "ppid=" in ln]
    assert grouped, f"expected grouped-by-parent lines:\n{r.stdout}"
    assert "4242" in grouped[0], f"the heaviest parent (4242, 2 zombies) must lead:\n{r.stdout}"
    assert "leaky-parent" in grouped[0], "the leaker's command line should be named"
    assert "init: true" in r.stdout, "the kit must list the container-PID-1 reaping fix"


def test_unknown_subcommand_exits_2(tmp_path):
    """Arg parsing: an unknown subcommand must exit 2 with a usage hint, not silently run the report."""
    cf = _caddyfile(tmp_path)
    r = _run(_env(tmp_path, cf), "wibble")
    assert r.returncode == 2, f"unknown subcommand must exit 2, got {r.returncode}"
    assert "unknown subcommand" in r.stderr


def test_upstream_down_fails(tmp_path):
    """A non-200 from the box reader must FAIL the upstream check and the run."""
    cf = _caddyfile(tmp_path)
    env = _env(tmp_path, cf, FAKE_HASH=hashlib.sha256(cf.read_bytes()).hexdigest(), CURL_CODE="502")
    r = _run(env, "report")
    assert any(ln.startswith("FAIL upstream:") for ln in r.stdout.splitlines()), (
        f"a 502 upstream must FAIL:\n{r.stdout}")
    assert r.returncode != 0
