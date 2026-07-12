"""Deploy preflight (deploy/scripts/preflight.sh) — the untracked-survey-dir guard (#15).

Incident 2026-07-11: an UNTRACKED leftover dir (`test-2026`) under the box's surveys-live checkout was
SERVED for a day, because the engine build enumerates the FILESYSTEM under surveys/, not git — so a
`git rm`/push can never remove what was never tracked, and the reconcile drift chip read "current"
honestly-but-misleadingly. preflight now catches the same drift on a hand-inspection, LOUDLY, before a
rebuild.

Tested as a BLACK BOX through `sh` over a REAL git checkout (preflight does many other checks — docker,
images, ownership — that legitimately FAIL in this env, so these pins assert the SPECIFIC untracked
FAIL/PASS line in stdout, an independent observable, never the overall exit code). Each names its
failure criterion (Invariant 10).

UNLIKE the sibling test_preflight_sh.py (the g+w perm-bit check, which needs meaningful POSIX mode bits
and so skips on Windows), the untracked check is pure git-tracking logic and runs EVERYWHERE `sh` + a
real `git` exist — including a Windows dev box — so this module is NOT nt-skipped (standing rule: split
the everywhere-runnable half from the platform-dependent half). preflight's check reads the tracked
tree DISCOVERY-FREE (an explicit --git-dir ls-tree, per the d8837d0 lesson), so it is robust under sudo
against an operator-owned checkout too.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "deploy" / "scripts" / "preflight.sh"
_SH = shutil.which("sh") or shutil.which("bash")
_GIT = shutil.which("git")

pytestmark = [
    pytest.mark.skipif(_SH is None, reason="no POSIX sh/bash to run preflight.sh"),
    pytest.mark.skipif(_GIT is None, reason="git required to build the untracked-dir fixture"),
]

# The exact wording preflight.sh prints for the two outcomes (an independent observable).
_FAIL_NEEDLE = "UNTRACKED survey dir(s) the build would SERVE"
_PASS_NEEDLE = "no untracked dirs"


def _git(cwd: Path, *args: str) -> None:
    r = subprocess.run([_GIT, *args], cwd=str(cwd), capture_output=True, text=True)
    assert r.returncode == 0, f"git {args} failed in {cwd}: {r.stderr}"


def _make_tree(tmp_path: Path, *, leave_untracked: bool) -> Path:
    """$AUSMT_DATA_DIR with a REAL surveys-live checkout: one COMMITTED survey dir under surveys/, plus
    (the red case) one UNTRACKED leftover dir the build would enumerate. site-data exists so the earlier
    section runs; its ownership checks fail harmlessly (we only read the untracked line)."""
    data = tmp_path / "data"
    (data / "site-data").mkdir(parents=True)
    surveys = data / "surveys-live"
    surveys.mkdir(parents=True)
    _git(surveys, "init", "-q")
    _git(surveys, "config", "user.email", "t@example.org")
    _git(surveys, "config", "user.name", "Test")
    (surveys / "surveys" / "tracked-survey").mkdir(parents=True)
    (surveys / "surveys" / "tracked-survey" / "survey.yaml").write_text("version: 1\n", encoding="utf-8")
    _git(surveys, "add", "-A")
    _git(surveys, "commit", "-qm", "one")
    if leave_untracked:
        d = surveys / "surveys" / "test-2026"
        d.mkdir(parents=True)
        (d / "survey.yaml").write_text("version: 1\n", encoding="utf-8")
    return data


def _run_preflight(data_dir: Path) -> subprocess.CompletedProcess:
    import os
    env = dict(os.environ)
    env["AUSMT_DATA_DIR"] = str(data_dir)
    # OWNER etc. unset — the other sections FAIL harmlessly; we only read the untracked line. Portal
    # profile (the default): the untracked check runs for BOTH profiles, so no need to pass "gateway".
    return subprocess.run([_SH, str(_SCRIPT)], capture_output=True, text=True, env=env)


def test_preflight_reds_on_untracked_survey_dir(tmp_path):
    """RED PIN. A surveys-live/surveys/ with an UNTRACKED leftover dir must make preflight print the
    incident-naming FAIL line and name the dir — a rebuild would SERVE it though git cannot remove it.
    FAILS IF: preflight passes an untracked leftover (the shipped-blind 2026-07-11 state), or the FAIL
    line does not name the offending dir."""
    data = _make_tree(tmp_path, leave_untracked=True)
    r = _run_preflight(data)
    out = r.stdout + r.stderr
    assert _FAIL_NEEDLE in out, f"preflight did not flag the untracked survey dir — output:\n{out}"
    assert "test-2026" in out, f"the FAIL must name the offending dir — output:\n{out}"


def test_preflight_passes_on_clean_survey_tree(tmp_path):
    """GREEN PIN. A surveys/ tree with only TRACKED survey dirs must PASS the untracked check (the FAIL
    line absent, the PASS line present) — proving the red pin is non-vacuous: the same code path returns
    PASS once the leftover is gone. FAILS IF: a clean tree still trips the untracked FAIL."""
    data = _make_tree(tmp_path, leave_untracked=False)
    r = _run_preflight(data)
    out = r.stdout + r.stderr
    assert _FAIL_NEEDLE not in out, f"a clean survey tree must not trip the untracked FAIL — output:\n{out}"
    assert _PASS_NEEDLE in out, f"the clean-tree PASS line must render — output:\n{out}"
