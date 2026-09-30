"""The serving-replica receiver (deploy/scripts/receive-build.sh), run against a REAL site-data tree.

Nothing is shimmed: the script verifies real files against a real sidecar and renames a real
symlink, so every assertion reads the tree it leaves behind. The sidecar is written here with
hashlib in the sha256sum list format, independently of the sender, so the format is the contract
the two scripts share rather than whatever the sender happens to emit.

Fails if: a good build does not become current by a rename of a temporary symlink, or published.json
does not record it; a missing, extra, altered or symlinked file still reaches current; a re-run
changes anything; the prune deletes the served build, a build still in flight, or keeps more than
KEEP complete builds; or a name that is not a plain build timestamp reaches the filesystem.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "deploy" / "scripts" / "receive-build.sh"
_SH = shutil.which("sh")

pytestmark = [
    pytest.mark.skipif(_SH is None, reason="no POSIX sh to run receive-build.sh"),
    pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks are not meaningful here"),
    pytest.mark.skipif(shutil.which("sha256sum") is None, reason="no sha256sum to verify with"),
]

OLD = "20260929T000000Z"
NEW = "20260930T010203Z"


def _files(ts: str) -> dict[str, bytes]:
    return {
        "build.json": json.dumps({"build_id": f"bid-{ts}", "source_commit": f"sc{ts[:8]}",
                                  "engine_commit": "eng0001"}).encode(),
        "index.html": b"<!doctype html>\n",
        "data/stations.json": b"[]\n",
        "h5/survey a/ST01.h5": b"\x89HDF\r\n\x1a\n" + ts.encode(),
    }


def _sidecar(build: Path) -> str:
    rels = sorted(p.relative_to(build).as_posix() for p in build.rglob("*") if p.is_file())
    return "".join("%s  %s\n" % (hashlib.sha256((build / r).read_bytes()).hexdigest(), r)
                   for r in rels)


def _add_build(builds: Path, ts: str, *, sidecar: bool = True) -> Path:
    d = builds / ts
    for rel, body in _files(ts).items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
    if sidecar:
        (builds / f"{ts}.sha256").write_text(_sidecar(d), encoding="utf-8")
    return d


def _tree(tmp_path: Path) -> dict:
    data = tmp_path / "data"
    site = data / "site-data"
    builds = site / "builds"
    builds.mkdir(parents=True)
    _add_build(builds, OLD)
    _add_build(builds, NEW)
    os.symlink(f"builds/{OLD}", site / "current")
    env = dict(os.environ)
    env["AUSMT_DATA_DIR"] = str(data)
    env.pop("AUSMT_PUBLISH_KEEP", None)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    return {"data": data, "site": site, "builds": builds, "env": env}


def _run(tree: dict, *args: str, **env_extra: str) -> subprocess.CompletedProcess:
    env = dict(tree["env"])
    env.update(env_extra)
    return subprocess.run([_SH, str(_SCRIPT), *args], capture_output=True, text=True, env=env)


def _current(tree: dict) -> str:
    return os.readlink(tree["site"] / "current")


def _published(tree: dict) -> dict | None:
    p = tree["site"] / "published.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _assert_untouched(tree: dict, r: subprocess.CompletedProcess) -> None:
    assert r.returncode != 0, "a refused build must exit non-zero"
    assert _current(tree) == f"builds/{OLD}", "a refused build must leave current alone"
    assert _published(tree) is None, "a refused build must not record published.json"


def test_a_good_build_becomes_current_by_rename_and_is_recorded(tmp_path):
    """FAILS IF current is not a symlink to builds/<ts>, a temporary link is left behind or was
    moved INTO the previous build (what a mv without -T does to a symlink to a directory), or
    published.json does not carry the ts, the build's identity and the receive time."""
    tree = _tree(tmp_path)
    old_listing = sorted(p.name for p in (tree["builds"] / OLD).iterdir())
    r = _run(tree, NEW)
    assert r.returncode == 0, r.stderr
    assert (tree["site"] / "current").is_symlink()
    assert _current(tree) == f"builds/{NEW}"
    assert not [p.name for p in tree["site"].iterdir() if p.name.startswith("current.")]
    assert sorted(p.name for p in (tree["builds"] / OLD).iterdir()) == old_listing
    pub = _published(tree)
    assert pub["ts"] == NEW
    assert pub["build_id"] == f"bid-{NEW}"
    assert pub["source_commit"] == f"sc{NEW[:8]}"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", pub["received_at"]), pub


def test_a_missing_file_leaves_current_untouched(tmp_path):
    tree = _tree(tmp_path)
    (tree["builds"] / NEW / "data" / "stations.json").unlink()
    r = _run(tree, NEW)
    _assert_untouched(tree, r)
    assert "stations.json" in r.stderr + r.stdout


def test_an_extra_file_leaves_current_untouched(tmp_path):
    tree = _tree(tmp_path)
    (tree["builds"] / NEW / "stray.txt").write_text("x", encoding="utf-8")
    r = _run(tree, NEW)
    _assert_untouched(tree, r)
    assert "stray.txt" in r.stderr + r.stdout


def test_a_mismatching_file_leaves_current_untouched(tmp_path):
    """Same size, different bytes: only the hash can tell."""
    tree = _tree(tmp_path)
    p = tree["builds"] / NEW / "index.html"
    p.write_bytes(p.read_bytes().upper())
    r = _run(tree, NEW)
    _assert_untouched(tree, r)


def test_a_symlink_inside_the_build_is_refused(tmp_path):
    """Caddy follows a symlink in the served tree, so one would publish whatever it points at."""
    tree = _tree(tmp_path)
    build = tree["builds"] / NEW
    os.symlink("/etc/hosts", build / "hosts")
    (tree["builds"] / f"{NEW}.sha256").write_text(_sidecar(build), encoding="utf-8")
    r = _run(tree, NEW)
    _assert_untouched(tree, r)


def test_a_missing_sidecar_is_refused(tmp_path):
    tree = _tree(tmp_path)
    (tree["builds"] / f"{NEW}.sha256").unlink()
    r = _run(tree, NEW)
    _assert_untouched(tree, r)


def test_a_build_without_build_json_is_refused(tmp_path):
    """The served identity lives in build.json; a tree without one cannot be recorded or doctored."""
    tree = _tree(tmp_path)
    build = tree["builds"] / NEW
    (build / "build.json").unlink()
    (tree["builds"] / f"{NEW}.sha256").write_text(_sidecar(build), encoding="utf-8")
    r = _run(tree, NEW)
    _assert_untouched(tree, r)


def test_a_current_that_is_a_directory_is_refused(tmp_path):
    tree = _tree(tmp_path)
    (tree["site"] / "current").unlink()
    (tree["site"] / "current").mkdir()
    r = _run(tree, NEW)
    assert r.returncode != 0
    assert (tree["site"] / "current").is_dir() and not (tree["site"] / "current").is_symlink()


def test_a_re_run_is_an_idempotent_success(tmp_path):
    """FAILS IF the second run fails, moves current, or rewrites published.json."""
    tree = _tree(tmp_path)
    assert _run(tree, NEW).returncode == 0
    first = (tree["site"] / "published.json").read_bytes()
    r = _run(tree, NEW)
    assert r.returncode == 0, r.stderr
    assert _current(tree) == f"builds/{NEW}"
    assert (tree["site"] / "published.json").read_bytes() == first


def test_a_malformed_name_is_refused(tmp_path):
    tree = _tree(tmp_path)
    for bad in ("../etc", "2026", f"{NEW}/..", f"{NEW};rm", "", "--keep"):
        r = _run(tree, bad)
        assert r.returncode == 2, (bad, r.returncode, r.stderr)
        assert _current(tree) == f"builds/{OLD}"


def test_current_prints_the_served_build(tmp_path):
    tree = _tree(tmp_path)
    r = _run(tree, "--current")
    assert r.returncode == 0 and r.stdout.strip() == OLD
    (tree["site"] / "current").unlink()
    r = _run(tree, "--current")
    assert r.returncode == 0 and r.stdout.strip() == ""


def _stamps(n: int) -> list[str]:
    return ["202609%02dT000000Z" % day for day in range(1, n + 1)]


def test_the_prune_keeps_the_newest_complete_builds_and_every_build_in_flight(tmp_path):
    """KEEP=3: the three newest builds that carry a sidecar survive, and so does any directory
    WITHOUT a sidecar, which is a transfer still in flight. FAILS IF an in-flight directory is
    deleted, a pruned build leaves its sidecar behind, or more than KEEP complete builds remain."""
    tree = _tree(tmp_path)
    for ts in _stamps(7):
        _add_build(tree["builds"], ts)
    inflight = _add_build(tree["builds"], "20260801T000000Z", sidecar=False)
    r = _run(tree, "--keep", "3", NEW)
    assert r.returncode == 0, r.stderr
    dirs = sorted(p.name for p in tree["builds"].iterdir() if p.is_dir())
    assert dirs == sorted([inflight.name, OLD, "20260907T000000Z", NEW]), dirs
    sidecars = sorted(p.name for p in tree["builds"].iterdir() if p.suffix == ".sha256")
    assert sidecars == sorted(f"{d}.sha256" for d in dirs if d != inflight.name), sidecars


def test_the_prune_never_deletes_the_build_current_points_at(tmp_path):
    """Receiving an OLDER build (a replica rollback) makes it current although it is not among the
    newest; the prune must keep it. AUSMT_PUBLISH_KEEP from the environment sets the depth."""
    tree = _tree(tmp_path)
    stamps = _stamps(6)
    for ts in stamps:
        _add_build(tree["builds"], ts)
    r = _run(tree, stamps[0], AUSMT_PUBLISH_KEEP="2")
    assert r.returncode == 0, r.stderr
    assert _current(tree) == f"builds/{stamps[0]}"
    dirs = sorted(p.name for p in tree["builds"].iterdir() if p.is_dir())
    assert dirs == sorted([stamps[0], "20260930T010203Z", "20260929T000000Z"]), dirs


def test_a_timestamp_with_no_build_directory_is_refused(tmp_path):
    """A well-formed name that names nothing under builds/ is refused before any swap. FAILS IF
    current moves or published.json is written."""
    tree = _tree(tmp_path)
    r = _run(tree, "20260101T000000Z")
    _assert_untouched(tree, r)
    assert "20260101T000000Z" in r.stderr


def test_a_refused_receive_prunes_nothing(tmp_path):
    """A refused build keeps its directory and sidecar, so an operator can read why; it is an
    ordinary complete build to the next successful receive and ages out with the rest. FAILS IF a
    refused receive prunes anything."""
    tree = _tree(tmp_path)
    for ts in _stamps(4):
        _add_build(tree["builds"], ts)
    (tree["builds"] / NEW / "stray.txt").write_text("x", encoding="utf-8")
    before = sorted(p.name for p in tree["builds"].iterdir())
    r = _run(tree, "--keep", "1", NEW)
    _assert_untouched(tree, r)
    assert sorted(p.name for p in tree["builds"].iterdir()) == before


def _shim_dir(tmp_path: Path) -> Path:
    d = tmp_path / "shim-bin"
    d.mkdir(exist_ok=True)
    return d


def _install(shim_dir: Path, name: str, body: str) -> None:
    p = shim_dir / name
    p.write_text(body, encoding="utf-8")
    p.chmod(0o755)


def _with_shims(tree: dict, shim_dir: Path) -> None:
    tree["env"]["PATH"] = str(shim_dir) + os.pathsep + tree["env"]["PATH"]


def test_the_prune_keeps_the_build_current_names_when_the_prune_runs(tmp_path):
    """A second writer repoints current at an old build between this receive's swap and its prune
    (the `date` of the record step stands in for it). FAILS IF the prune deletes the build current
    names at that moment, which leaves the public site serving a dangling link."""
    tree = _tree(tmp_path)
    stamps = _stamps(4)
    for ts in stamps:
        _add_build(tree["builds"], ts)
    shims = _shim_dir(tmp_path)
    _install(shims, "date",
             "#!/bin/sh\n"
             'rm -f "$SHIM_SITE/current"\n'
             'ln -s "builds/$SHIM_REPOINT" "$SHIM_SITE/current"\n'
             f'exec {shutil.which("date")} "$@"\n')
    _with_shims(tree, shims)
    r = _run(tree, "--keep", "2", NEW, SHIM_SITE=str(tree["site"]), SHIM_REPOINT=stamps[0])
    assert _current(tree) == f"builds/{stamps[0]}"
    assert (tree["builds"] / stamps[0]).is_dir(), r.stdout + r.stderr
    assert (tree["builds"] / f"{stamps[0]}.sha256").is_file()
    assert not (tree["builds"] / stamps[1]).exists(), "the prune must still age out the rest"


def test_current_names_nothing_when_its_build_is_gone(tmp_path):
    """A current whose build directory is missing serves nothing. FAILS IF --current still names it,
    which tells the sender the replica already serves that build and nothing is ever re-sent."""
    tree = _tree(tmp_path)
    shutil.rmtree(tree["builds"] / OLD)
    r = _run(tree, "--current")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == ""


def test_a_dangling_current_is_replaced_by_a_good_build(tmp_path):
    tree = _tree(tmp_path)
    shutil.rmtree(tree["builds"] / OLD)
    r = _run(tree, NEW)
    assert r.returncode == 0, r.stderr
    assert _current(tree) == f"builds/{NEW}"


@pytest.mark.parametrize("keep", ["00", "007", "1000", "99999999999999999999"])
def test_a_keep_depth_outside_1_to_999_is_refused(tmp_path, keep):
    """A leading zero or a depth the shell cannot compare turns the prune's keep test into an error,
    and every complete build but the received one is deleted. FAILS IF such a depth is accepted from
    the flag or from the environment."""
    tree = _tree(tmp_path)
    for ts in _stamps(3):
        _add_build(tree["builds"], ts)
    before = sorted(p.name for p in tree["builds"].iterdir())
    for r in (_run(tree, "--keep", keep, NEW), _run(tree, NEW, AUSMT_PUBLISH_KEEP=keep)):
        assert r.returncode == 2, (keep, r.returncode, r.stderr)
        assert _current(tree) == f"builds/{OLD}"
        assert sorted(p.name for p in tree["builds"].iterdir()) == before


_FLOCK_SHIM = """#!%s
import fcntl, sys, time
args = sys.argv[1:]
wait = None
if args[:1] == ["-w"]:
    wait, args = float(args[1]), args[2:]
fd = int(args[0])
deadline = None if wait is None else time.monotonic() + wait
while True:
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        break
    except BlockingIOError:
        if deadline is not None and time.monotonic() > deadline:
            sys.exit(1)
        time.sleep(0.05)
"""


def test_a_receive_waits_for_the_receive_lock(tmp_path):
    """Two receives never overlap: a second one waits on site-data/.receive.lock before it verifies,
    swaps or prunes. flock(1) is a shim on fcntl.flock so the test runs where util-linux does not.
    FAILS IF a receive swaps current while another holds the lock."""
    import fcntl
    import time
    tree = _tree(tmp_path)
    shims = _shim_dir(tmp_path)
    _install(shims, "flock", _FLOCK_SHIM % sys.executable)
    _with_shims(tree, shims)
    with open(tree["site"] / ".receive.lock", "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        proc = subprocess.Popen([_SH, str(_SCRIPT), NEW], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, env=tree["env"])
        try:
            time.sleep(1.5)
            assert proc.poll() is None, "the receive must wait while the lock is held"
            assert _current(tree) == f"builds/{OLD}"
        finally:
            fcntl.flock(held, fcntl.LOCK_UN)
        out, err = proc.communicate(timeout=60)
    assert proc.returncode == 0, err
    assert _current(tree) == f"builds/{NEW}"


def test_current_is_never_replaced_by_ln_force(tmp_path):
    """ln -sfn unlinks current before it links the new target, a window in which Caddy serves 404s.
    ln is a shim that records its argv. FAILS IF ln is ever run with -f or -n, or ever aimed at
    current itself rather than at a temporary name that is then renamed over it."""
    tree = _tree(tmp_path)
    shims = _shim_dir(tmp_path)
    log = tmp_path / "ln.log"
    _install(shims, "ln",
             "#!/bin/sh\n"
             '{ for a in "$@"; do printf \'%s\\037\' "$a"; done; printf \'\\n\'; } >> "$SHIM_LN_LOG"\n'
             f'exec {shutil.which("ln")} "$@"\n')
    _with_shims(tree, shims)
    r = _run(tree, NEW, SHIM_LN_LOG=str(log))
    assert r.returncode == 0, r.stderr
    assert _current(tree) == f"builds/{NEW}"
    calls = [line.rstrip("\x1f").split("\x1f") for line in log.read_text().splitlines()]
    assert calls, "the swap must create its temporary link with ln"
    current = str(tree["site"] / "current")
    for argv in calls:
        flags = "".join(a[1:] for a in argv if a.startswith("-") and not a.startswith("--"))
        assert "f" not in flags and "n" not in flags, argv
        assert argv[-1] != current, argv


def test_a_failed_record_rename_is_a_failure(tmp_path):
    """FAILS IF the receiver reports published.json recorded, and exits 0, when the rename that
    puts it in place failed."""
    tree = _tree(tmp_path)
    shims = _shim_dir(tmp_path)
    _install(shims, "mv",
             "#!/bin/sh\n"
             'for a in "$@"; do last="$a"; done\n'
             'case "$last" in */published.json) echo "mv: cannot move" >&2; exit 1 ;; esac\n'
             f'exec {shutil.which("mv")} "$@"\n')
    _with_shims(tree, shims)
    r = _run(tree, NEW)
    assert r.returncode != 0
    assert "published.json recorded" not in r.stdout
    assert _published(tree) is None
