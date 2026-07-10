"""Exec-bit tripwire — every tracked shell script must be git mode 100755.

WHY THIS EXISTS (incident, 2026-07-10): the backup system shipped in PR #25 with everything under
deploy/scripts/ tracked at git mode 100644 (no executable bit) — restore-drill.sh, pull-backup.sh,
and the pre-existing preflight.sh. Direct invocation on the production box (`./deploy/scripts/…`) then
died with **exit 126** (permission denied / not executable). backup.sh itself was correctly 100755, so
the gap was invisible until an operator ran a script by path. This test makes that class of regression
red in CI instead of on the box.

FAILURE CRITERION (Invariant 10 — this test FAILS if): any *.sh file tracked in git (at minimum every
one under deploy/, checked recursively) has a git index mode other than 100755. A newly added shell
script committed at 100644 reds this lane; so does a `git update-index --chmod=-x` on any existing one.
It reads the mode from `git ls-files -s` (the authoritative tracked mode), NOT the working-tree stat —
because on Windows/MSYS the working-tree bit is meaningless but the git index mode is what actually
ships, and it was the index mode that was wrong on the box.

RUNS FROM REPO ROOT AND FROM A WORKTREE: the repo is located from THIS FILE's own path via
`git rev-parse --show-toplevel`, and `git ls-files` is invoked with that as cwd — so the test is
correct whether pytest is launched from the repo root, from deploy/, or from a linked worktree (a
worktree has its own toplevel; a plain `git ls-files` in the wrong cwd would list the wrong tree)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(_GIT is None, reason="git not on PATH to read tracked file modes")

# The repo root for THIS file, resolved from the file's own location so the test is worktree-safe and
# cwd-independent (parents[2] is the repo root: deploy/tests/test_exec_bits.py -> repo).
_HERE = Path(__file__).resolve()
_FALLBACK_ROOT = _HERE.parents[2]


def _toplevel() -> Path:
    """The git toplevel that owns this file (a worktree's own toplevel, not the main checkout's)."""
    r = subprocess.run(
        [_GIT, "-C", str(_HERE.parent), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True)
    if r.returncode != 0:
        return _FALLBACK_ROOT
    return Path(r.stdout.strip())


def _tracked_sh_modes(root: Path) -> dict[str, str]:
    """{path: mode} for every tracked *.sh file, read from `git ls-files -s` (the index mode that
    actually ships). `git ls-files -s` lines are: `<mode> <sha> <stage>\\t<path>`."""
    r = subprocess.run(
        [_GIT, "-C", str(root), "ls-files", "-s", "--", "*.sh"],
        capture_output=True, text=True)
    assert r.returncode == 0, f"git ls-files failed: {r.stderr}"
    modes: dict[str, str] = {}
    for line in r.stdout.splitlines():
        if not line.strip():
            continue
        meta, _, path = line.partition("\t")
        mode = meta.split()[0]
        modes[path] = mode
    return modes


def test_all_tracked_shell_scripts_are_executable():
    """Every tracked *.sh in the repo is git mode 100755. FAILS IF any is 100644 (the exit-126 trap
    from 2026-07-10). This is the whole-repo sweep; the deploy-only assertion below is the belt."""
    root = _toplevel()
    modes = _tracked_sh_modes(root)
    assert modes, "expected at least one tracked *.sh file; git ls-files returned none"
    not_exec = {p: m for p, m in modes.items() if m != "100755"}
    assert not_exec == {}, (
        "tracked shell scripts must be git mode 100755 (executable) — these are not, so a direct "
        f"`./<script>` invocation would exit 126 (the 2026-07-10 incident): {not_exec}")


def test_deploy_shell_scripts_are_executable():
    """Belt to the whole-repo sweep, scoped to deploy/ (the incident's subtree) so a deploy/scripts
    regression is unmissable in the failure message. FAILS IF any deploy/**/*.sh is not 100755."""
    root = _toplevel()
    modes = _tracked_sh_modes(root)
    deploy = {p: m for p, m in modes.items() if p.startswith("deploy/")}
    assert deploy, "expected tracked *.sh files under deploy/; found none"
    not_exec = {p: m for p, m in deploy.items() if m != "100755"}
    assert not_exec == {}, (
        "deploy/ shell scripts must be git mode 100755 — these are not (exit-126 on the box, "
        f"2026-07-10): {not_exec}")
