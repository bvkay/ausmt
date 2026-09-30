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
