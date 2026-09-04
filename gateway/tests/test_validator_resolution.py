"""Falsifiability pins for the validator-arm resolver in gateway/tests/conftest.py, and for the CI
step that decides which arm the cross-repo oracles run against.

resolve_validator_dir is one switch with two live arms: the LIVE sibling ausmt-surveys checkout when
present (dev box), else the committed vendored copy (CI and fresh clones). Until f359e0c the sibling
constant was anchored one level too high, so it pointed INSIDE the monorepo and arm (i) could not
fire on any machine for weeks. Nothing went red, because no test took the resolver as its subject:
every reference to it in this suite is a consumer. These pins take it as the subject, so the same
defect cannot ship silently twice: the sibling constant points outside the repo, a present sibling
wins, AUSMT_FORCE_VENDORED_VALIDATOR=1 flips the branch, an absent sibling falls back to the pinned
vendored copy, and neither present FAILS rather than skips (no same-author-mock fallback).

Style follows the engine's D3.1 falsifiability tests (engine/tests/test_validator_gate.py): drive the
REAL resolver over a monkeypatched SCRATCH topology, never over the real checkout, so each pin
asserts the same thing on a dev box (sibling present) as in CI (sibling absent).
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from gateway.tests import conftest as gwconftest

_REPO_ROOT = Path(gwconftest.__file__).resolve().parents[2]
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "gateway-ci.yml"
_FORCE_ENV = "AUSMT_FORCE_VENDORED_VALIDATOR"


def _scratch_topology(tmp_path, monkeypatch, *, sibling: bool, vendored: bool):
    """Point the resolver's two constants at a scratch tree, each arm present or absent by request,
    with the force flag cleared. The real checkout is never touched: it carries a sibling on a dev
    box and none in CI, so a pin reading it would be asserting a different thing in each place."""
    sib = tmp_path / "ausmt-surveys" / "_validation"
    ven = tmp_path / "vendored_validation"
    for directory, present in ((sib, sibling), (ven, vendored)):
        directory.mkdir(parents=True)
        if present:
            (directory / "validate_survey.py").write_text("# scratch validator\n", encoding="utf-8")
    monkeypatch.setattr(gwconftest, "SIBLING_VALIDATOR_DIR", sib)
    monkeypatch.setattr(gwconftest, "VENDORED_VALIDATOR_DIR", ven)
    monkeypatch.delenv(_FORCE_ENV, raising=False)
    return sib, ven


def test_sibling_validator_dir_is_outside_the_monorepo():
    """The sibling ausmt-surveys checkout sits BESIDE the monorepo, so SIBLING_VALIDATOR_DIR must not
    resolve under the repo root. FAILS IF the anchor slips back to the one-level-high form that
    shipped (parents[1]), which named a path inside the repo that no checkout can ever contain and so
    silenced the live-sibling arm everywhere. The vendored copy is the mirror image: committed, so it
    MUST live inside the repo and must be present."""
    assert not gwconftest.SIBLING_VALIDATOR_DIR.is_relative_to(_REPO_ROOT), (
        f"SIBLING_VALIDATOR_DIR resolves INSIDE the monorepo ({gwconftest.SIBLING_VALIDATOR_DIR}): "
        "the sibling checkout sits beside the repo, so this arm could never fire")
    assert gwconftest.SIBLING_VALIDATOR_DIR == _REPO_ROOT.parent / "ausmt-surveys" / "_validation"
    assert gwconftest.VENDORED_VALIDATOR_DIR.is_relative_to(_REPO_ROOT), (
        "the vendored copy is committed to THIS repo; a path outside it is not the pinned contract")
    assert (gwconftest.VENDORED_VALIDATOR_DIR / "validate_survey.py").is_file(), (
        "the vendored validator is committed, so its absence is a broken checkout")


def test_present_sibling_wins_over_the_vendored_copy(tmp_path, monkeypatch):
    """Arm (i): with both arms present and the force flag clear, the LIVE sibling wins - a dev box
    tests the real cross-repo pair, not a snapshot of it. FAILS IF the resolver returns the vendored
    copy, the state the suite was in (undetected) before f359e0c."""
    sib, _ven = _scratch_topology(tmp_path, monkeypatch, sibling=True, vendored=True)
    assert gwconftest.resolve_validator_dir() == sib, "a present sibling must win over the vendored copy"
    assert gwconftest.require_validator_dir() == sib


def test_force_vendored_flag_flips_the_branch(tmp_path, monkeypatch):
    """Arm (ii) by declaration: AUSMT_FORCE_VENDORED_VALIDATOR=1 selects the vendored copy even with a
    sibling present, which is how gateway-ci pins the oracles to the contract and how a dev box
    reproduces the CI arm. The comparison is EXACT: any other value leaves the sibling arm, so a
    stray '0' or 'true' cannot quietly re-point CI at whatever the surveys tip is that day."""
    sib, ven = _scratch_topology(tmp_path, monkeypatch, sibling=True, vendored=True)
    monkeypatch.setenv(_FORCE_ENV, "1")
    assert gwconftest.resolve_validator_dir() == ven, f"{_FORCE_ENV}=1 must force the vendored arm"
    for other in ("0", "true"):
        monkeypatch.setenv(_FORCE_ENV, other)
        assert gwconftest.resolve_validator_dir() == sib, (
            f"{_FORCE_ENV}={other!r} must NOT force the vendored arm: only the exact string '1' does")


def test_absent_sibling_falls_back_to_the_vendored_copy(tmp_path, monkeypatch):
    """Arm (ii) by fallback: with no sibling checkout - CI, and every fresh clone - the oracles run
    against the committed vendored copy. FAILS IF the fallback stops firing, which would take the
    oracles from the pinned contract to nothing at all."""
    _sib, ven = _scratch_topology(tmp_path, monkeypatch, sibling=False, vendored=True)
    assert gwconftest.resolve_validator_dir() == ven
    assert gwconftest.require_validator_dir() == ven


def test_neither_arm_present_fails_rather_than_skips(tmp_path, monkeypatch):
    """Both arms absent is a BROKEN CHECKOUT, never a legitimate skip: the vendored copy is
    committed. resolve_validator_dir returns None and require_validator_dir asserts, so the oracles
    go red instead of reverting to same-author mocks. FAILS IF either one starts
    skipping or returns a path that is not there."""
    _scratch_topology(tmp_path, monkeypatch, sibling=False, vendored=False)
    assert gwconftest.resolve_validator_dir() is None
    with pytest.raises(AssertionError) as excinfo:
        gwconftest.require_validator_dir()
    assert "BROKEN CHECKOUT" in str(excinfo.value)


# ------------------------------------------------------------------------------------------------
# The CI half of the same switch. gateway-ci clones the surveys sibling into exactly the directory
# this resolver treats as the sibling, so the arm the oracles run on is a property of the WORKFLOW,
# not only of conftest. These two pins hold the workflow to declaring the arm.
# ------------------------------------------------------------------------------------------------
def _ci_step_running(fragment: str) -> dict:
    """The one gateway-ci step whose `run` block contains `fragment`."""
    data = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    steps = data["jobs"]["gateway"]["steps"]
    matches = [s for s in steps if fragment in (s.get("run") or "")]
    assert len(matches) == 1, (
        f"expected exactly one gateway-ci step running {fragment!r}, found {len(matches)}")
    return matches[0]


def test_ci_pytest_step_declares_the_vendored_arm():
    """gateway-ci must CHOOSE the vendored arm, not inherit it from step order. The route-table gate
    later in the same job clones ausmt-surveys into the sibling directory, so without this env var
    the validator ~120 oracles compare against is decided by which step happens to run first, and a
    reorder would move them off the sha-pinned contract with nothing red. FAILS IF the pytest step
    stops setting AUSMT_FORCE_VENDORED_VALIDATOR=1."""
    step = _ci_step_running("python -m pytest -q -rs gateway/tests")
    assert str((step.get("env") or {}).get(_FORCE_ENV)) == "1", (
        f"the gateway-ci pytest step must set {_FORCE_ENV}=1 so the oracles run against the pinned "
        "vendored copy by intent, not because the sibling clone happens to come later in the job")


def test_ci_sibling_clone_lands_on_the_resolved_sibling_dir():
    """The coupling as an assertion rather than a comment: the route-table gate clones the surveys
    repo to $GITHUB_WORKSPACE/../ausmt-surveys, $GITHUB_WORKSPACE is the repo root, and that is
    exactly SIBLING_VALIDATOR_DIR's parent. FAILS IF either side moves without the other, so the
    next person to touch the clone path is told that it is the oracles' sibling they are moving."""
    step = _ci_step_running('DEST="$GITHUB_WORKSPACE/../ausmt-surveys"')
    assert "gen_ts_routes.py --check" in step["run"], (
        "the clone that lands on the oracles' sibling directory is the route-table drift gate")
    assert gwconftest.SIBLING_VALIDATOR_DIR.parent == _REPO_ROOT.parent / "ausmt-surveys", (
        "the CI clone target and the resolver's sibling directory have drifted apart")
