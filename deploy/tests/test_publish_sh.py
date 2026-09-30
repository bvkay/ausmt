"""The serving-replica sender (deploy/scripts/publish.sh): what it writes on the box, what it asks
rsync and ssh to do, and what it refuses.

Black box over `sh` with the shim pattern the reconcile and pull-backup suites use.
AUSMT_PUBLISH_RSYNC and AUSMT_PUBLISH_SSH point at shims that append their argv to one shared log
(so the ORDER of the transfer steps is observable) and answer the one question the sender asks the
receiver: which build is current there. Every assertion reads an independent observable: the shim
log, the sidecar on disk, the local current link, the exit code.

Fails if: the sidecar is missing, unsorted, wrong or inside the build; rsync is not asked for an
archive copy with --delete and a relative --link-dest into the receiver's builds dir; the swap on
the receiver is not the last step; a dry run touches anything; a current that is not a resolvable
symlink into builds/ is published; a failed transfer still reaches the receiver's swap; or a
re-run for a build the receiver already serves transfers anything.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "deploy" / "scripts" / "publish.sh"
_SH = shutil.which("sh")

pytestmark = [
    pytest.mark.skipif(_SH is None, reason="no POSIX sh to run publish.sh"),
    pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks and sh shims are not meaningful here"),
    pytest.mark.skipif(shutil.which("sha256sum") is None, reason="no sha256sum to write the sidecar"),
]

TS = "20260930T010203Z"
PREV = "20260929T000000Z"
TARGET = "publish@ausmt-serve"
# Upper case sorts before lower case under the C collation the sidecar is written in, and a space
# in a path must survive the list format; both are here so the order and the parsing are pinned.
FILES = {
    "build.json": b'{"build_id": "bid-1", "source_commit": "abc1234"}\n',
    "index.html": b"<!doctype html>\n",
    "data/stations.json": b"[]\n",
    "h5/survey a/ST01.h5": b"\x89HDF\r\n\x1a\n\x00\x01",
    "Z-upper.txt": b"z\n",
}

# One log for both shims, one line per call, arguments separated by the unit separator so an
# argument carrying a space stays one argument.
_RSYNC_SHIM = """#!/bin/sh
{ printf 'rsync'; for a in "$@"; do printf '\\037%s' "$a"; done; printf '\\n'; } >> "$SHIM_LOG"
if [ "${RSYNC_FAIL:-0}" = 1 ]; then echo 'rsync: connection unexpectedly closed' >&2; exit 12; fi
exit 0
"""
_SSH_SHIM = """#!/bin/sh
{ printf 'ssh'; for a in "$@"; do printf '\\037%s' "$a"; done; printf '\\n'; } >> "$SHIM_LOG"
case "$*" in
  *"receive-build.sh --current"*) printf '%s\\n' "${REMOTE_CURRENT-}"; exit 0 ;;
  *receive-build.sh*)
    if [ "${RECEIVE_FAIL:-0}" = 1 ]; then echo 'receive-build: verify FAILED' >&2; exit 1; fi
    exit 0 ;;
esac
exit 0
"""


def _write_build(builds: Path, ts: str, files: dict[str, bytes] = FILES) -> Path:
    d = builds / ts
    for rel, body in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
    return d


def _tree(tmp_path: Path) -> dict:
    data = tmp_path / "data"
    site = data / "site-data"
    builds = site / "builds"
    builds.mkdir(parents=True)
    build = _write_build(builds, TS)
    os.symlink(f"builds/{TS}", site / "current")
    rsync = tmp_path / "rsync-shim.sh"
    rsync.write_text(_RSYNC_SHIM, encoding="utf-8")
    ssh = tmp_path / "ssh-shim.sh"
    ssh.write_text(_SSH_SHIM, encoding="utf-8")
    log = tmp_path / "shim.log"
    env = dict(os.environ)
    env.update({
        "AUSMT_DATA_DIR": str(data),
        "AUSMT_PUBLISH_TARGET": TARGET,
        "AUSMT_PUBLISH_RSYNC": f"sh {rsync}",
        "AUSMT_PUBLISH_SSH": f"sh {ssh}",
        "SHIM_LOG": str(log),
        "REMOTE_CURRENT": PREV,
    })
    for key in ("AUSMT_PUBLISH_DATA_DIR", "AUSMT_PUBLISH_KEEP"):
        env.pop(key, None)
    return {"data": data, "site": site, "builds": builds, "build": build, "log": log, "env": env,
            "ssh": ssh}


def _run(tree: dict, *args: str, **env_extra: str) -> subprocess.CompletedProcess:
    env = dict(tree["env"])
    env.update(env_extra)
    return subprocess.run([_SH, str(_SCRIPT), *args], capture_output=True, text=True, env=env)


def _calls(tree: dict) -> list[list[str]]:
    if not tree["log"].exists():
        return []
    return [line.split("\x1f") for line in tree["log"].read_text(encoding="utf-8").splitlines()]


def _expected_sidecar(build: Path) -> str:
    rels = sorted(p.relative_to(build).as_posix() for p in build.rglob("*") if p.is_file())
    return "".join("%s  %s\n" % (hashlib.sha256((build / r).read_bytes()).hexdigest(), r)
                   for r in rels)


def test_sidecar_is_the_sorted_full_tree_sha256_list_beside_the_build(tmp_path):
    """The sidecar lands at builds/<ts>.sha256, OUTSIDE the build dir, one sha256sum line per file,
    relative paths, in C order. FAILS IF it is missing, lands inside the build (where it would be
    served and would list itself), carries a ./ or absolute path, or disagrees with the bytes."""
    tree = _tree(tmp_path)
    r = _run(tree)
    assert r.returncode == 0, r.stderr
    sidecar = tree["builds"] / f"{TS}.sha256"
    assert sidecar.is_file(), "the sidecar must be written beside the build dir"
    assert not any(p.suffix == ".sha256" for p in tree["build"].rglob("*")), \
        "nothing may be written inside the build dir"
    text = sidecar.read_text(encoding="utf-8")
    assert text == _expected_sidecar(tree["build"])
    paths = [line[66:] for line in text.splitlines()]
    assert paths == sorted(paths), "the list must be sorted by path in C order"
    assert not any(p.startswith(("./", "/")) for p in paths)


def test_rsync_is_an_archive_copy_with_delete_and_a_relative_link_dest(tmp_path):
    """The build goes over with -a --delete, hard-linking unchanged files against the receiver's
    current build through a RELATIVE --link-dest, into <remote data dir>/site-data/builds/<ts>/;
    the sidecar follows it. rsync links a file only when every preserved attribute matches, and a
    rebuild writes every file afresh with a new mtime, so the copy compares CONTENT (--checksum)
    and does not carry mtimes (--no-times after -a): a byte-identical file is then linked rather
    than stored again. FAILS IF --delete or the link-dest is missing, the link-dest is absolute,
    either destination is wrong, or mtimes decide what is linked."""
    tree = _tree(tmp_path)
    r = _run(tree)
    assert r.returncode == 0, r.stderr
    rsyncs = [c for c in _calls(tree) if c[0] == "rsync"]
    assert len(rsyncs) == 2, rsyncs
    body, side = rsyncs
    assert "-a" in body and "--delete" in body, body
    assert "--checksum" in body, body
    assert "--no-times" in body and body.index("--no-times") > body.index("-a"), body
    assert f"--link-dest=../{PREV}" in body, body
    assert "-e" in body and body[body.index("-e") + 1] == tree["env"]["AUSMT_PUBLISH_SSH"]
    assert body[-2] == f"{tree['build']}/", "the source must be the build's contents"
    assert body[-1] == f"{TARGET}:/srv/ausmt/site-data/builds/{TS}/"
    assert side[-2] == str(tree["builds"] / f"{TS}.sha256")
    assert side[-1] == f"{TARGET}:/srv/ausmt/site-data/builds/{TS}.sha256"


def test_the_remote_data_dir_and_keep_are_configurable(tmp_path):
    """AUSMT_PUBLISH_DATA_DIR moves both destinations; AUSMT_PUBLISH_KEEP reaches the receiver."""
    tree = _tree(tmp_path)
    r = _run(tree, AUSMT_PUBLISH_DATA_DIR="/data/replica", AUSMT_PUBLISH_KEEP="3")
    assert r.returncode == 0, r.stderr
    rsyncs = [c for c in _calls(tree) if c[0] == "rsync"]
    assert rsyncs[0][-1] == f"{TARGET}:/data/replica/site-data/builds/{TS}/"
    assert rsyncs[1][-1] == f"{TARGET}:/data/replica/site-data/builds/{TS}.sha256"
    receive = _calls(tree)[-1]
    assert receive[1:] == [TARGET, "receive-build.sh", "--keep", "3", TS], receive


def test_the_receiver_swap_is_the_last_step(tmp_path):
    """Order: ask the receiver for its current, send the build, send the sidecar, then run
    receive-build.sh <ts>. FAILS IF the swap is asked for before both transfers finished."""
    tree = _tree(tmp_path)
    r = _run(tree)
    assert r.returncode == 0, r.stderr
    calls = _calls(tree)
    assert [c[0] for c in calls] == ["ssh", "rsync", "rsync", "ssh"], calls
    assert calls[0][1:] == [TARGET, "receive-build.sh", "--current"]
    assert calls[-1][1:] == [TARGET, "receive-build.sh", "--keep", "5", TS]


def test_a_first_publish_has_no_link_dest(tmp_path):
    """A receiver with no current build has nothing to link against. FAILS IF a --link-dest is
    still passed (it would name a directory that does not exist)."""
    tree = _tree(tmp_path)
    r = _run(tree, REMOTE_CURRENT="")
    assert r.returncode == 0, r.stderr
    body = [c for c in _calls(tree) if c[0] == "rsync"][0]
    assert not any(a.startswith("--link-dest") for a in body), body


def test_dry_run_performs_nothing(tmp_path):
    """--dry-run names the build and the target and stops. FAILS IF it contacts the receiver, runs
    rsync or writes the sidecar."""
    tree = _tree(tmp_path)
    r = _run(tree, "--dry-run")
    assert r.returncode == 0, r.stderr
    assert _calls(tree) == [], "a dry run must not run rsync or ssh"
    assert not (tree["builds"] / f"{TS}.sha256").exists(), "a dry run must not write the sidecar"
    assert TS in r.stdout and TARGET in r.stdout


def test_a_current_that_is_not_a_symlink_is_refused(tmp_path):
    """A current that is a plain directory cannot name a build. FAILS IF anything is sent."""
    tree = _tree(tmp_path)
    (tree["site"] / "current").unlink()
    (tree["site"] / "current").mkdir()
    (tree["site"] / "current" / "build.json").write_text("{}", encoding="utf-8")
    r = _run(tree)
    assert r.returncode != 0
    assert "current" in r.stderr
    assert _calls(tree) == []
    assert not (tree["builds"] / f"{TS}.sha256").exists()


def test_a_dangling_or_foreign_current_is_refused(tmp_path):
    """A current pointing at a missing build, or outside builds/, is refused before any transfer."""
    for target in ("builds/20260101T000000Z", "../elsewhere/x", "/etc"):
        tree = _tree(tmp_path / target.replace("/", "_").replace(".", "d"))
        (tree["site"] / "current").unlink()
        os.symlink(target, tree["site"] / "current")
        r = _run(tree)
        assert r.returncode != 0, f"current -> {target} must be refused"
        assert _calls(tree) == [], target


def test_a_failing_rsync_exits_non_zero_and_never_calls_the_receiver(tmp_path):
    """FAILS IF the sender reports success, does not name the failed step, or asks the receiver to
    swap in a build whose transfer failed."""
    tree = _tree(tmp_path)
    r = _run(tree, RSYNC_FAIL="1")
    assert r.returncode != 0
    assert "rsync" in r.stderr and "step" in r.stderr, r.stderr
    receives = [c for c in _calls(tree) if c[0] == "ssh" and TS in c]
    assert receives == [], "a failed transfer must never reach receive-build.sh <ts>"


def test_a_failing_receiver_exits_non_zero_naming_the_step(tmp_path):
    tree = _tree(tmp_path)
    r = _run(tree, RECEIVE_FAIL="1")
    assert r.returncode != 0
    assert "receive" in r.stderr and "step" in r.stderr, r.stderr


def test_a_build_the_receiver_already_serves_is_a_no_op_success(tmp_path):
    """Idempotent: when the receiver's current already is <ts> nothing is hashed or sent. FAILS IF
    rsync runs, the receiver is asked to swap, or the sidecar is rewritten."""
    tree = _tree(tmp_path)
    r = _run(tree, REMOTE_CURRENT=TS)
    assert r.returncode == 0, r.stderr
    calls = _calls(tree)
    assert [c[0] for c in calls] == ["ssh"], calls
    assert not (tree["builds"] / f"{TS}.sha256").exists()


def test_an_unexpected_answer_from_the_receiver_is_refused(tmp_path):
    """The receiver's answer becomes a path argument, so it must be a build name or nothing."""
    tree = _tree(tmp_path)
    r = _run(tree, REMOTE_CURRENT="../../etc")
    assert r.returncode != 0
    assert [c[0] for c in _calls(tree)] == ["ssh"]


def test_the_local_current_is_never_touched(tmp_path):
    """Publishing reads the served build and writes only the sidecar beside it."""
    tree = _tree(tmp_path)
    before = {p: p.read_bytes() for p in tree["build"].rglob("*") if p.is_file()}
    r = _run(tree)
    assert r.returncode == 0, r.stderr
    assert os.readlink(tree["site"] / "current") == f"builds/{TS}"
    assert {p: p.read_bytes() for p in tree["build"].rglob("*") if p.is_file()} == before


def test_build_selects_a_build_that_is_not_current(tmp_path):
    """--build <ts> publishes a retained build (a replica rollback) and leaves current alone."""
    tree = _tree(tmp_path)
    older = _write_build(tree["builds"], PREV)
    r = _run(tree, "--build", PREV, REMOTE_CURRENT=TS)
    assert r.returncode == 0, r.stderr
    body = [c for c in _calls(tree) if c[0] == "rsync"][0]
    assert body[-2] == f"{older}/"
    assert f"--link-dest=../{TS}" in body
    assert _calls(tree)[-1][-1] == PREV
    assert os.readlink(tree["site"] / "current") == f"builds/{TS}"


def test_a_malformed_or_missing_build_name_is_refused(tmp_path):
    tree = _tree(tmp_path)
    for bad in ("../x", "2026", f"{TS}/..", "20260101T000000Z"):
        r = _run(tree, "--build", bad)
        assert r.returncode != 0, bad
    assert _calls(tree) == []


def test_a_symlink_inside_the_build_is_refused_before_any_transfer(tmp_path):
    """A symlink in a served tree can point anywhere on the replica. FAILS IF it is sent."""
    tree = _tree(tmp_path)
    os.symlink("/etc/hosts", tree["build"] / "hosts")
    r = _run(tree)
    assert r.returncode != 0
    assert "hosts" in r.stderr
    assert _calls(tree) == []


def test_the_target_is_required(tmp_path):
    tree = _tree(tmp_path)
    env = dict(tree["env"])
    env.pop("AUSMT_PUBLISH_TARGET")
    r = subprocess.run([_SH, str(_SCRIPT)], capture_output=True, text=True, env=env)
    assert r.returncode != 0
    assert "AUSMT_PUBLISH_TARGET" in r.stderr
    assert _calls(tree) == []


def test_an_unwritable_builds_dir_is_named_before_any_transfer(tmp_path):
    """builds/ belongs to the engine uid, so the account that publishes needs the one-time write
    grant deploy/README.md describes before it can lay the sidecar beside a build. FAILS IF the
    receiver is contacted first, or the refusal does not name the sidecar step and the directory."""
    tree = _tree(tmp_path)
    if os.geteuid() == 0:
        pytest.skip("root writes through a 0555 directory")
    tree["builds"].chmod(0o555)
    try:
        r = _run(tree)
    finally:
        tree["builds"].chmod(0o755)
    assert r.returncode != 0
    assert "sidecar" in r.stderr and str(tree["builds"]) in r.stderr, r.stderr
    assert _calls(tree) == []
