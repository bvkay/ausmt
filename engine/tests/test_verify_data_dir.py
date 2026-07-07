"""C12: scripts/verify.py --data-dir mode — validate an EXISTING build output dir's mtcat.json +
manifest.json against their schemas + the manifest's on-disk integrity, WITHOUT rebuilding. This is
what deploy/Makefile's rebuild-data runs inside the container after build-runner writes a fresh
builds/<timestamp> dir: the default (self-building) verify.py invocation would just re-build a SECOND
copy, which is not what a post-build gate wants.

NON-VACUOUS (Invariant 10): the FAIL case doctors a real manifest row's sha256 after a real build (an
independent observable — the check must notice bytes-on-disk disagree with the manifest's own claim),
not a hand-authored, possibly-unrepresentative fixture.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SURVEYS = ROOT / "data"
VERIFY = ROOT / "scripts" / "verify.py"


def _build(tmp_path):
    out = tmp_path / "data"
    r = subprocess.run([sys.executable, "-m", "extract.build_portal", "--surveys", str(SURVEYS),
                        "--out", str(out), "--bundle-edi", "--no-validate"],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out


def _run_verify_data_dir(data_dir):
    r = subprocess.run([sys.executable, str(VERIFY), "--data-dir", str(data_dir)],
                       cwd=str(ROOT), capture_output=True, text=True)
    return r


def test_verify_data_dir_passes_on_fresh_build(tmp_path):
    out = _build(tmp_path)
    r = _run_verify_data_dir(out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "VERIFY: PASS" in r.stdout, r.stdout + r.stderr
    # --data-dir mode must NOT re-run the test suite or a fresh build (self-build invocation stays
    # untouched) — its only inputs are the already-built dir's own JSON.
    assert "== pytest ==" not in r.stdout


def test_verify_data_dir_fails_on_doctored_manifest(tmp_path):
    out = _build(tmp_path)
    man_path = out / "manifest.json"
    man = json.loads(man_path.read_text(encoding="utf-8"))
    arts = man["files"] + man["bundles"]
    assert arts, "expected at least one served artifact from the CC-BY sample survey"
    # doctor ONE row's recorded sha256 so it disagrees with the actual bytes on disk (a corrupted /
    # tampered manifest) -- the independent observable the check must catch.
    victim = arts[0]
    real_sha = hashlib.sha256((out / victim["url"]).read_bytes()).hexdigest()
    victim["sha256"] = "0" * 64
    assert victim["sha256"] != real_sha
    man_path.write_text(json.dumps(man))

    r = _run_verify_data_dir(out)
    assert r.returncode != 0, r.stdout + r.stderr
    assert "VERIFY: FAIL" in r.stdout, r.stdout + r.stderr


def test_verify_data_dir_requires_existing_dir():
    r = _run_verify_data_dir(Path("/no/such/build/dir/at/all"))
    assert r.returncode != 0
    assert "VERIFY: FAIL" in r.stdout or r.returncode != 0


def test_default_self_build_invocation_untouched():
    # --data-dir is a NEW, separate mode; the default (no flags) self-building invocation must not
    # have changed shape. -h output should mention both the pre-existing --surveys and the new
    # --data-dir so an operator can discover the mode without reading source.
    r = subprocess.run([sys.executable, str(VERIFY), "--help"], cwd=str(ROOT),
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert "--surveys" in r.stdout
    assert "--data-dir" in r.stdout
