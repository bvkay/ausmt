"""The serving-replica publish, end to end on one machine: deploy/scripts/publish.sh drives a REAL
rsync through deploy/nectar/publish-gate.sh into deploy/scripts/receive-build.sh.

Only the network is stood in for. The ssh command is a shim that does what sshd does for the publish
account: it drops the destination and runs the gate as a login shell with the words joined into one
command string. So the gate sees the server command line the local rsync really writes, and the
receiver verifies what rsync really wrote.

Fails if: a first publish does not end with the replica's current on the build and published.json
naming it; a second build whose unchanged file was rewritten with a new mtime is stored again
instead of hard-linked to the served copy; a re-run transfers anything; or the gate refuses the
command line the local rsync writes.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_PUBLISH = _REPO / "deploy" / "scripts" / "publish.sh"
_RECEIVE = _REPO / "deploy" / "scripts" / "receive-build.sh"
_GATE = _REPO / "deploy" / "nectar" / "publish-gate.sh"
_SH = shutil.which("sh")

pytestmark = [
    pytest.mark.skipif(_SH is None, reason="no POSIX sh to run the scripts"),
    pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks and hard links are not meaningful here"),
    pytest.mark.skipif(shutil.which("rsync") is None, reason="no rsync to transfer with"),
    pytest.mark.skipif(shutil.which("sha256sum") is None, reason="no sha256sum to write the sidecar"),
]

FIRST = "20260930T000000Z"
SECOND = "20260930T010000Z"

_SSH_SHIM = """#!/bin/sh
printf 'ssh %s\\n' "$*" >> "$SHIM_LOG"
while [ $# -gt 0 ]; do
  case "$1" in -l|-o|-p|-i) shift 2 ;; -*) shift ;; *) break ;; esac
done
shift
AUSMT_DATA_DIR="$REPLICA" AUSMT_GATE_RECEIVE="sh $RECEIVE" exec sh "$GATE" -c "$*"
"""


def _write(build: Path, files: dict[str, bytes]) -> None:
    for rel, body in files.items():
        p = build / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)


def _setup(tmp_path: Path) -> dict:
    local = tmp_path / "box"
    replica = tmp_path / "replica"
    (local / "site-data" / "builds").mkdir(parents=True)
    (replica / "site-data" / "builds").mkdir(parents=True)
    shim = tmp_path / "ssh-shim.sh"
    shim.write_text(_SSH_SHIM, encoding="utf-8")
    log = tmp_path / "ssh.log"
    env = dict(os.environ)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    env.update({
        "AUSMT_DATA_DIR": str(local),
        "AUSMT_PUBLISH_TARGET": "publish@ausmt-serve",
        "AUSMT_PUBLISH_DATA_DIR": str(replica),
        "AUSMT_PUBLISH_SSH": f"sh {shim}",
        "REPLICA": str(replica),
        "RECEIVE": str(_RECEIVE),
        "GATE": str(_GATE),
        "SHIM_LOG": str(log),
    })
    for key in ("AUSMT_PUBLISH_RSYNC", "AUSMT_PUBLISH_KEEP", "SSH_ORIGINAL_COMMAND"):
        env.pop(key, None)
    return {"local": local, "replica": replica, "env": env, "log": log}


def _serve(t: dict, ts: str) -> None:
    cur = t["local"] / "site-data" / "current"
    if cur.is_symlink():
        cur.unlink()
    os.symlink(f"builds/{ts}", cur)


def _publish(t: dict) -> subprocess.CompletedProcess:
    return subprocess.run([_SH, str(_PUBLISH)], capture_output=True, text=True, env=t["env"])


def test_two_publishes_swap_the_replica_and_link_what_did_not_change(tmp_path):
    t = _setup(tmp_path)
    b1 = t["local"] / "site-data" / "builds" / FIRST
    _write(b1, {"build.json": b'{"build_id": "bid-1", "source_commit": "aaa1111"}\n',
                "index.html": b"one\n", "h5/survey/ST01.h5": b"\x89HDF unchanged bytes"})
    _serve(t, FIRST)
    r = _publish(t)
    assert r.returncode == 0, r.stdout + r.stderr
    rsite = t["replica"] / "site-data"
    assert os.readlink(rsite / "current") == f"builds/{FIRST}"
    assert json.loads((rsite / "published.json").read_text())["build_id"] == "bid-1"

    b2 = t["local"] / "site-data" / "builds" / SECOND
    _write(b2, {"build.json": b'{"build_id": "bid-2", "source_commit": "bbb2222"}\n',
                "index.html": b"two\n", "h5/survey/ST01.h5": b"\x89HDF unchanged bytes"})
    os.utime(b2 / "h5" / "survey" / "ST01.h5", (1_000_000_000, 1_000_000_000))
    _serve(t, SECOND)
    r = _publish(t)
    assert r.returncode == 0, r.stdout + r.stderr
    assert os.readlink(rsite / "current") == f"builds/{SECOND}"
    pub = json.loads((rsite / "published.json").read_text())
    assert pub["ts"] == SECOND and pub["source_commit"] == "bbb2222", pub
    old = rsite / "builds" / FIRST / "h5" / "survey" / "ST01.h5"
    new = rsite / "builds" / SECOND / "h5" / "survey" / "ST01.h5"
    assert old.stat().st_ino == new.stat().st_ino, "a byte-identical file must be hard-linked"
    assert (rsite / "builds" / SECOND / "index.html").read_bytes() == b"two\n"

    t["log"].write_text("", encoding="utf-8")
    r = _publish(t)
    assert r.returncode == 0, r.stdout + r.stderr
    calls = t["log"].read_text(encoding="utf-8").splitlines()
    assert len(calls) == 2 and "receive-build.sh --current" in calls[0], calls
    assert f"receive-build.sh --keep 5 {SECOND}" in calls[1], calls
    assert "nothing to send" in r.stdout


def test_a_receive_cut_off_after_its_swap_is_repaired_by_the_next_publish(tmp_path):
    """The replica swapped current and then lost the session before recording published.json. FAILS
    IF the next publish sees current and stops there, which leaves published.json stale for good."""
    t = _setup(tmp_path)
    b1 = t["local"] / "site-data" / "builds" / FIRST
    _write(b1, {"build.json": b'{"build_id": "bid-1"}\n', "index.html": b"one\n"})
    _serve(t, FIRST)
    assert _publish(t).returncode == 0
    rsite = t["replica"] / "site-data"
    (rsite / "published.json").unlink()
    r = _publish(t)
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads((rsite / "published.json").read_text())["ts"] == FIRST


def test_a_build_altered_on_the_replica_after_transfer_is_never_served(tmp_path):
    """The receiver verifies what arrived, not what the sender meant to send: a transfer that lands
    different bytes is refused and the replica keeps serving what it served."""
    t = _setup(tmp_path)
    b1 = t["local"] / "site-data" / "builds" / FIRST
    _write(b1, {"build.json": b'{"build_id": "bid-1"}\n', "index.html": b"one\n"})
    _serve(t, FIRST)
    assert _publish(t).returncode == 0
    b2 = t["local"] / "site-data" / "builds" / SECOND
    _write(b2, {"build.json": b'{"build_id": "bid-2"}\n', "index.html": b"two\n"})
    _serve(t, SECOND)
    side = t["local"] / "site-data" / "builds" / f"{SECOND}.sha256"
    shim = tmp_path / "rsync-tamper.sh"
    shim.write_text(
        "#!/bin/sh\n"
        'rsync "$@" || exit $?\n'
        'for a in "$@"; do last="$a"; done\n'
        f'case "$last" in *{SECOND}/) printf x >> "$REPLICA/site-data/builds/{SECOND}/index.html" ;; esac\n',
        encoding="utf-8")
    t["env"]["AUSMT_PUBLISH_RSYNC"] = f"sh {shim}"
    r = _publish(t)
    assert r.returncode != 0
    assert "receive" in r.stderr, r.stderr
    assert os.readlink(t["replica"] / "site-data" / "current") == f"builds/{FIRST}"
    assert side.exists()
