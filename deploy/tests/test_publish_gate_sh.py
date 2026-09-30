"""The command gates of the two accounts the curation host reaches on the serving replica:
deploy/nectar/publish-gate.sh (the publish account) and deploy/nectar/caddylog-gate.sh (the log
account the front-door log pull reads through).

The gate is the login shell of the publish account on the serving replica and the forced command
on its key, so the one account the curation host reaches can do exactly three things: ask which
build is current, rsync INTO the builds directory, and run the receiver for a named build. OpenSSH
hands a forced command SSH_ORIGINAL_COMMAND; a login shell is invoked as `<shell> -c <command>`,
which is also how a Tailscale SSH session runs a command. Both entries are driven here.

Black box over `sh`: AUSMT_GATE_RSYNC and AUSMT_GATE_RECEIVE point at shims that record their argv,
so an allowed command is observed arriving intact and a refused one is observed never running.

Fails if: an allowed command is refused or mangled, or a command that could read from the replica
(--sender), write outside site-data/builds, climb out of it, chain a second command, or open a
shell reaches either program.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_GATE = _REPO / "deploy" / "nectar" / "publish-gate.sh"
_SH = shutil.which("sh")

pytestmark = [
    pytest.mark.skipif(_SH is None, reason="no POSIX sh to run the gate"),
    pytest.mark.skipif(os.name == "nt", reason="POSIX sh shims are not meaningful here"),
]

TS = "20260930T010203Z"
PREV = "20260929T000000Z"
BUILDS = "/srv/ausmt/site-data/builds"
_SHIM = """#!/bin/sh
{ printf '%s' "$SHIM_NAME"; for a in "$@"; do printf '\\037%s' "$a"; done; printf '\\n'; } >> "$SHIM_LOG"
exit 0
"""


def _env(tmp_path: Path) -> dict:
    shim = tmp_path / "shim.sh"
    shim.write_text(_SHIM, encoding="utf-8")
    env = dict(os.environ)
    env.pop("SSH_ORIGINAL_COMMAND", None)
    env.update({
        "AUSMT_DATA_DIR": "/srv/ausmt",
        "AUSMT_GATE_RSYNC": f"env SHIM_NAME=rsync sh {shim}",
        "AUSMT_GATE_RECEIVE": f"env SHIM_NAME=receive sh {shim}",
        "SHIM_LOG": str(tmp_path / "shim.log"),
    })
    return env


def _calls(tmp_path: Path) -> list[list[str]]:
    log = tmp_path / "shim.log"
    if not log.exists():
        return []
    return [line.split("\x1f") for line in log.read_text(encoding="utf-8").splitlines()]


def _as_shell(tmp_path: Path, command: str) -> subprocess.CompletedProcess:
    return subprocess.run([_SH, str(_GATE), "-c", command], capture_output=True, text=True,
                          env=_env(tmp_path))


def _as_forced(tmp_path: Path, command: str) -> subprocess.CompletedProcess:
    env = _env(tmp_path)
    env["SSH_ORIGINAL_COMMAND"] = command
    return subprocess.run([_SH, str(_GATE)], capture_output=True, text=True, env=env)


ALLOWED = [
    ("receive-build.sh --current", ["receive", "--current"]),
    (f"receive-build.sh {TS}", ["receive", TS]),
    (f"receive-build.sh --keep 5 {TS}", ["receive", "--keep", "5", TS]),
    (f"rsync --server -logDtpre.iLsfxCIvu --delete --link-dest ../{PREV} . {BUILDS}/{TS}/",
     ["rsync", "--server", "-logDtpre.iLsfxCIvu", "--delete", "--link-dest", f"../{PREV}", ".",
      f"{BUILDS}/{TS}/"]),
    (f"rsync --server -logDtpre.iLsfxCIvu --delete --link-dest=../{PREV} . {BUILDS}/{TS}/",
     ["rsync", "--server", "-logDtpre.iLsfxCIvu", "--delete", f"--link-dest=../{PREV}", ".",
      f"{BUILDS}/{TS}/"]),
    (f"rsync --server -logDtpre.iLsfxCIvu . {BUILDS}/{TS}.sha256",
     ["rsync", "--server", "-logDtpre.iLsfxCIvu", ".", f"{BUILDS}/{TS}.sha256"]),
]


@pytest.mark.parametrize("command,expected", ALLOWED)
def test_an_allowed_command_arrives_intact_as_a_login_shell(tmp_path, command, expected):
    r = _as_shell(tmp_path, command)
    assert r.returncode == 0, r.stderr
    assert _calls(tmp_path) == [expected]


@pytest.mark.parametrize("command,expected", ALLOWED)
def test_an_allowed_command_arrives_intact_as_a_forced_command(tmp_path, command, expected):
    r = _as_forced(tmp_path, command)
    assert r.returncode == 0, r.stderr
    assert _calls(tmp_path) == [expected]


REFUSED = [
    f"rsync --server --sender -logDtpre.iLsfxCIvu . {BUILDS}/{TS}/",
    "rsync --server -logDtpre.iLsfxCIvu . /etc/",
    "rsync --server -logDtpre.iLsfxCIvu . /srv/ausmt/site-data/current",
    f"rsync --server -logDtpre.iLsfxCIvu . {BUILDS}/../current/",
    f"rsync --server -logDtpre.iLsfxCIvu . {BUILDS}/{TS}/../../x",
    f"rsync --server -logDtpre.iLsfxCIvu --link-dest /etc . {BUILDS}/{TS}/",
    f"rsync --server -logDtpre.iLsfxCIvu --link-dest=../../x . {BUILDS}/{TS}/",
    f"rsync --server -logDtpre.iLsfxCIvu --backup-dir=/tmp/x . {BUILDS}/{TS}/",
    f"rsync --server -logDtpre.iLsfxCIvu --log-file=x . {BUILDS}/{TS}/",
    f"rsync --server -logDtpre.iLsfxCIvu . {BUILDS}/{TS}/; sh",
    f"rsync -logDtpre.iLsfxCIvu . {BUILDS}/{TS}/",
    "receive-build.sh ../../etc",
    f"receive-build.sh {TS} extra",
    "receive-build.sh --keep x " + TS,
    "receive-build.sh --keep 00 " + TS,
    "receive-build.sh --keep 1000 " + TS,
    "receive-build.sh --keep 99999999999999999999 " + TS,
    "receive-build.sh $(id)",
    "sh",
    "bash -i",
    "scp -t /srv/ausmt",
    "",
]


@pytest.mark.parametrize("command", REFUSED)
def test_a_command_outside_the_three_is_refused(tmp_path, command):
    r = _as_shell(tmp_path, command)
    assert r.returncode != 0, command
    assert _calls(tmp_path) == [], command
    r = _as_forced(tmp_path, command)
    assert r.returncode != 0, command
    assert _calls(tmp_path) == [], command


def test_an_interactive_login_is_refused(tmp_path):
    """No -c and no SSH_ORIGINAL_COMMAND is a shell being asked for. FAILS IF anything runs."""
    for argv in ([], ["-l"], ["-i"]):
        r = subprocess.run([_SH, str(_GATE), *argv], capture_output=True, text=True,
                           env=_env(tmp_path))
        assert r.returncode != 0, argv
    assert _calls(tmp_path) == []



# The log account. Its one job is the read-only pull of the masked front-door log, which rrsync -ro
# already confines to one directory; the gate's part is to be the login shell a Tailscale SSH
# session runs, hand rrsync the command the way a forced command would, and refuse a shell.
_CADDYLOG_GATE = _REPO / "deploy" / "nectar" / "caddylog-gate.sh"
_RRSYNC_SHIM = """#!/bin/sh
{ printf 'rrsync'; for a in "$@"; do printf '\\037%s' "$a"; done; printf '\\037%s\\n' "$SSH_ORIGINAL_COMMAND"; } >> "$SHIM_LOG"
exit 0
"""
PULL = "rsync --server --sender -logDtprze.iLsfxCIvu . ."


def _caddylog(tmp_path: Path, argv: list[str], forced: str | None = None):
    shim = tmp_path / "rrsync.sh"
    shim.write_text(_RRSYNC_SHIM, encoding="utf-8")
    env = dict(os.environ)
    env.pop("SSH_ORIGINAL_COMMAND", None)
    env.update({"AUSMT_GATE_RRSYNC": f"sh {shim}", "SHIM_LOG": str(tmp_path / "shim.log")})
    if forced is not None:
        env["SSH_ORIGINAL_COMMAND"] = forced
    return subprocess.run([_SH, str(_CADDYLOG_GATE), *argv], capture_output=True, text=True, env=env)


@pytest.mark.parametrize("entry", ["shell", "forced"])
def test_the_log_pull_reaches_rrsync_read_only_and_rooted(tmp_path, entry):
    r = (_caddylog(tmp_path, ["-c", PULL]) if entry == "shell"
         else _caddylog(tmp_path, [], forced=PULL))
    assert r.returncode == 0, r.stderr
    assert _calls(tmp_path) == [["rrsync", "-ro", "/var/log/caddy", PULL]]


@pytest.mark.parametrize("command", ["sh", "bash -i", "", "rsync --server -logDtpr . /tmp/x",
                                     "cat /etc/shadow", PULL + "; sh"])
def test_the_log_account_runs_nothing_but_the_pull(tmp_path, command):
    for r in (_caddylog(tmp_path, ["-c", command]), _caddylog(tmp_path, [], forced=command)):
        assert r.returncode != 0, command
    assert _calls(tmp_path) == [], command


def test_the_log_account_refuses_an_interactive_login(tmp_path):
    for argv in ([], ["-l"], ["-i"]):
        assert _caddylog(tmp_path, argv).returncode != 0, argv
    assert _calls(tmp_path) == []
