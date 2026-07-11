"""Deploy preflight (deploy/scripts/preflight.sh) — the shared-group permissions time-bomb check.

C43 S2b-i (B7): preflight gained a gateway-profile check that catches the incident-2026-07-11
lockout BEFORE it happens — a `surveys-live/.git` whose entries have lost the group-write bit means
the gateway (uid 10002) is creating foreign-owned, non-g+w object dirs the operator can no longer
`git pull`/gc, so the checkout silently rots behind GitHub.

Tested as a BLACK BOX through `sh` over a fabricated data tree: preflight does many other checks
(docker, images, …) that legitimately FAIL in this env, so these pins assert the SPECIFIC g+w
FAIL/PASS line in stdout (an independent observable), never the overall exit code. Each names its
failure criterion (Invariant 10).

POSIX mode bits: the whole file skips on Windows (no meaningful group-write bit — the existing
reconcile/backup suites use the same platform reason). On the gateway-ci ubuntu lane it RUNS with
nothing skipped, so the skip-tripwire needs no allow-list entry. git is NOT required: the fixtures
build a bare `.git/` dir by hand and set `core.sharedRepository` via `.git/config` text, so the pin
drives the perm-bit logic without a git binary.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "deploy" / "scripts" / "preflight.sh"
_SH = shutil.which("sh") or shutil.which("bash")

pytestmark = [
    pytest.mark.skipif(_SH is None, reason="no POSIX sh/bash to run preflight.sh"),
    pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits not meaningful on this filesystem"),
]

# The exact wording preflight.sh prints for the two outcomes (an independent observable, not a
# self-report the script could fake).
_FAIL_NEEDLE = "WITHOUT group-write"
_PASS_NEEDLE = "shared-group publish model in place"


def _make_tree(tmp_path: Path, *, git_entries_group_writable: bool,
               shared_repo_group: bool = False) -> Path:
    """A minimal $AUSMT_DATA_DIR the gateway-profile preflight will scan: site-data (10001 ownership
    is not assertable in a test, so those checks just fail harmlessly), a surveys-live checkout with a
    hand-built .git/ whose object dirs are EITHER all group-writable OR (the red case) not."""
    data = tmp_path / "data"
    (data / "site-data").mkdir(parents=True)
    surveys = data / "surveys-live"
    objects = surveys / ".git" / "objects" / "ab"
    objects.mkdir(parents=True)
    obj_file = objects / "0123456789abcdef"
    obj_file.write_text("x", encoding="utf-8")
    if shared_repo_group:
        (surveys / ".git" / "config").write_text(
            "[core]\n\trepositoryformatversion = 0\n\tsharedRepository = group\n", encoding="utf-8")
    else:
        (surveys / ".git" / "config").write_text(
            "[core]\n\trepositoryformatversion = 0\n", encoding="utf-8")
    if git_entries_group_writable:
        # Add the group-write bit to EVERY entry under .git (dirs + files) — the hardened state.
        for p in [surveys / ".git", *surveys.rglob("*")]:
            p.chmod(p.stat().st_mode | 0o020)
    else:
        # Strip the group-write bit from a real object dir (0755) — the un-hardened, incident state.
        objects.chmod(0o755)
        obj_file.chmod(0o444)
    return data


def _run_preflight(data_dir: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["AUSMT_DATA_DIR"] = str(data_dir)
    # OWNER etc. are unset — the other sections FAIL harmlessly; we only read the .git-perm line.
    return subprocess.run([_SH, str(_SCRIPT), "gateway"], capture_output=True, text=True, env=env)


def test_preflight_reds_on_non_group_writable_git(tmp_path):
    """RED PIN (B7). A surveys-live/.git with a non-group-writable object dir must make gateway-profile
    preflight FAIL with the incident-naming line — a gateway publish would lock the operator out of
    `git pull`. FAILS IF: the check passes an un-hardened .git (the shipped-blind state), or the FAIL
    line does not name the missing group-write."""
    data = _make_tree(tmp_path, git_entries_group_writable=False)
    r = _run_preflight(data)
    out = r.stdout + r.stderr
    assert _FAIL_NEEDLE in out, (
        f"preflight did not flag the non-g+w .git (incident lock-out) — output:\n{out}")
    assert "FAIL" in out and "core.sharedRepository group" in out, (
        f"the FAIL must carry the exact fix command — output:\n{out}")


def test_preflight_passes_on_group_writable_shared_repo_git(tmp_path):
    """GREEN PIN (B7). A surveys-live/.git that is fully group-writable with core.sharedRepository=group
    must PASS the shared-group check (the FAIL line absent). Proves the red pin above is non-vacuous —
    the same code path returns PASS once the model is in place. FAILS IF: a correctly-hardened .git
    still trips the g+w FAIL."""
    data = _make_tree(tmp_path, git_entries_group_writable=True, shared_repo_group=True)
    r = _run_preflight(data)
    out = r.stdout + r.stderr
    assert _FAIL_NEEDLE not in out, (
        f"a fully group-writable .git must not trip the g+w FAIL — output:\n{out}")
    assert _PASS_NEEDLE in out, (
        f"the shared-group PASS line must render for a hardened .git — output:\n{out}")
