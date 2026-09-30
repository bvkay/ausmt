"""The `make publish` target and the build prune that must share builds/ with the publish sidecars.

The pattern of test_makefile_build_flags.py: the recipe is parsed out of deploy/Makefile rather than
string-searched, so a word in a comment cannot satisfy a pin. One behavioural leg runs the real
target through make with the sender's transport shimmed, where a make is on PATH.

Fails if: publish is not a phony target; it runs without set -e or without the fail-closed guards
rebuild-data uses; it does not hand its arguments to scripts/publish.sh; or the rebuild-data prune
counts the sidecars beside the builds as builds, which would quietly halve the retention.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_MAKEFILE = _REPO / "deploy" / "Makefile"
_MAKE = shutil.which("make")


def _recipe(target: str) -> str:
    text = _MAKEFILE.read_text(encoding="utf-8")
    m = re.search(r"^%s:.*?$(?P<body>(?:\n(?:\t.*|)$)*)" % re.escape(target), text,
                  flags=re.M | re.S)
    assert m, f"deploy/Makefile no longer defines a {target} target"
    return m.group("body")


def test_publish_is_a_phony_target():
    phony = re.search(r"^\.PHONY:(.*)$", _MAKEFILE.read_text(encoding="utf-8"), flags=re.M)
    assert phony and "publish" in phony.group(1).split()


def test_publish_fails_closed_like_rebuild_data():
    body = _recipe("publish")
    assert body.lstrip().startswith("@set -e;"), body
    assert "AUSMT_DATA_DIR:?" in body, "an unset data dir must stop the recipe"
    assert "AUSMT_PUBLISH_TARGET:?" in body, "an unset target must stop the recipe"
    assert "scripts/publish.sh" in body and "$(ARGS)" in body, body


def test_the_rebuild_prune_counts_build_directories_and_takes_their_sidecars_along():
    body = _recipe("rebuild-data")
    swap = [line for line in body.splitlines() if "mv -T" in line]
    assert swap, "the rebuild-data swap step moved"
    step = swap[0]
    assert "ls -1td -- */" in step, "the prune must count build directories only"
    assert ".sha256" in step, "a pruned build must take its sidecar with it"


@pytest.mark.skipif(_MAKE is None, reason="no make on PATH to run the target")
@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks are not meaningful here")
def test_make_publish_runs_the_sender_and_its_guard_holds(tmp_path):
    site = tmp_path / "data" / "site-data"
    build = site / "builds" / "20260930T010203Z"
    build.mkdir(parents=True)
    (build / "build.json").write_text("{}", encoding="utf-8")
    os.symlink("builds/20260930T010203Z", site / "current")
    shim = tmp_path / "shim.sh"
    shim.write_text('#!/bin/sh\necho "$*" >> "$SHIM_LOG"\n', encoding="utf-8")
    env = dict(os.environ)
    env.update({"AUSMT_DATA_DIR": str(tmp_path / "data"),
                "AUSMT_PUBLISH_TARGET": "publish@ausmt-serve",
                "AUSMT_PUBLISH_RSYNC": f"sh {shim}", "AUSMT_PUBLISH_SSH": f"sh {shim}",
                "SHIM_LOG": str(tmp_path / "shim.log")})
    r = subprocess.run([_MAKE, "-s", "-C", str(_REPO / "deploy"), "publish", "ARGS=--dry-run"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "20260930T010203Z" in r.stdout
    assert not (tmp_path / "shim.log").exists(), "a dry run must not reach rsync or ssh"
    env.pop("AUSMT_PUBLISH_TARGET")
    r = subprocess.run([_MAKE, "-s", "-C", str(_REPO / "deploy"), "publish", "ARGS=--dry-run"],
                       capture_output=True, text=True, env=env)
    assert r.returncode != 0
    assert "AUSMT_PUBLISH_TARGET" in r.stderr


def test_the_env_template_documents_every_publish_variable():
    """The unit reads deploy/.env, so a variable the template does not carry is one an operator
    cannot find. FAILS IF any of the sender's variables is missing from deploy/.env.example."""
    text = (_REPO / "deploy" / ".env.example").read_text(encoding="utf-8")
    for var in ("AUSMT_PUBLISH_TARGET", "AUSMT_PUBLISH_DATA_DIR", "AUSMT_PUBLISH_KEEP",
                "AUSMT_PUBLISH_RSYNC", "AUSMT_PUBLISH_SSH", "AUSMT_RECONCILE_PUBLISH"):
        assert re.search(r"^#?\s*%s=" % var, text, flags=re.M), var
