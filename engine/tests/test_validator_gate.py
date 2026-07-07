"""C8: the survey validator gate must fail CLOSED, not open (CONTEXT: the sibling ausmt-surveys
pytest suite never ran in CI, so a fail-open validator merged untested — see
maintainer/ and build-products.yml). Three invariants pinned here:
  (a) --surveys without --no-validate and an unresolvable validator => main() returns non-zero
      (pre-fix this printed a WARNING and proceeded -- captured below as the pre-change evidence).
  (b) AUSMT_VALIDATOR_PATH pointing at the real ausmt-surveys/_validation resolves and is used.
  (c) --no-validate still builds (the explicit, documented opt-out survives).
Stack-less lane: no mt_metadata needed (validator resolution is stdlib-only import plumbing).
"""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "extract"))
sys.path.insert(0, str(REPO))
import build_portal  # noqa: E402

# C35b/D3 (review F7) + amendment D3.1 (2026-07-07, real-CI red on the engine image build): the
# validator resolves via the FOUR-arm environment enumeration recorded in
# maintainer/C35b-GitTruthDesign.md §D3.1. The validator is stdlib-only import plumbing here
# (_load_validator imports the module, no mt_metadata), so the vendored copy resolves in the
# stack-less engine lane too. Every probe anchors off ONE root, _repo_root() — no second path
# convention — and _repo_root() is the monkeypatch seam the D3.1 falsifiability tests use.

IMAGE_TOPOLOGY_SKIP_REASON = ("engine image build: gateway tree not shipped "
                              "(designed topology; vendored oracle lives in gateway/tests)")


def _repo_root() -> Path:
    """The repo root this checkout provides: engine/'s parent (= the monorepo root on a checkout;
    /app in the engine image, whose Dockerfile COPYs engine/ only). Module-level so the D3.1
    falsifiability tests can monkeypatch it to a scratch topology."""
    return REPO.parent


def _sibling_validator_dir() -> Path:
    return _repo_root().parent / "ausmt-surveys" / "_validation"


def _vendored_validator_dir() -> Path:
    return _repo_root() / "gateway" / "tests" / "fixtures" / "vendored_validation"


def _resolve_validator_dir() -> Path:
    """D3.1 resolution:
      (i)   sibling ausmt-surveys checkout -> use it (LIVE cross-repo pair, dev box);
      (ii)  else the committed vendored copy -> use it (PINNED contract, CI / fresh clones);
      (iii) else if the gateway package tree ITSELF is absent from the repo root -> SKIP: this is the
            engine image's designed topology (engine/ only, no /app/gateway — see engine.Dockerfile);
            the vendored oracle lives in gateway/tests, a tree the image never ships, so there is
            nothing to drift. On every monorepo checkout <root>/gateway exists, so this arm is
            UNREACHABLE there — fail-not-skip is preserved everywhere the F7 finding applied;
      (iv)  else (gateway tree present but the vendored fixture missing) -> FAIL: broken checkout."""
    import os
    sibling = _sibling_validator_dir()
    if (os.environ.get("AUSMT_FORCE_VENDORED_VALIDATOR") != "1"
            and (sibling / "validate_survey.py").is_file()):
        return sibling
    vendored = _vendored_validator_dir()
    if (vendored / "validate_survey.py").is_file():
        return vendored
    if not (_repo_root() / "gateway").is_dir():
        pytest.skip(IMAGE_TOPOLOGY_SKIP_REASON)
    raise AssertionError(
        "no validator available: neither the sibling ausmt-surveys/_validation checkout nor the "
        f"committed vendored copy at {vendored} was found, yet the gateway tree IS present at "
        f"{_repo_root() / 'gateway'} — a BROKEN CHECKOUT, not a legitimate skip "
        "(C35b/D3 amendment D3.1, review F7).")


def _empty_surveys(tmp_path):
    # An EMPTY --surveys dir + --allow-empty keeps this stack-less: discover_work finds zero
    # packages, process_edis (which hard-requires mt_metadata, build_portal.py:628) is never
    # called, so these tests isolate the validator-gate branch in main() from the extractor.
    d = tmp_path / "surveys"; d.mkdir()
    return d


def test_unresolvable_validator_fails_closed(tmp_path, monkeypatch):
    """No --no-validate + validator can't be found => non-zero exit (fail CLOSED). This is the
    behaviour the C8 contract changes; pre-fix, build_portal proceeded with only a stderr WARNING
    and returned 0 (captured verbatim in the implementation report, not re-asserted here since the
    old behaviour is being replaced, not kept as a branch)."""
    monkeypatch.setattr(build_portal, "_load_validator", lambda: None)
    out = tmp_path / "out"
    rc = build_portal.main(["--surveys", str(_empty_surveys(tmp_path)), "--out", str(out), "--allow-empty"])
    assert rc != 0, "validator-unresolvable + no --no-validate must fail closed, not warn-and-proceed"


def test_unresolvable_validator_via_bogus_env_path_fails_closed(tmp_path, monkeypatch):
    """AUSMT_VALIDATOR_PATH set but pointing nowhere real is a HARD error (never silently fall
    through to the bounded walk) -- distinct from the env var being unset entirely. This fires
    immediately in _load_validator (sys.exit, matching the codebase's existing hard-error style,
    e.g. the --canonical-dir mt_metadata-missing check) rather than main()'s own `return 2`, so it
    surfaces as SystemExit when main() is called in-process (a non-zero process exit either way)."""
    monkeypatch.setenv("AUSMT_VALIDATOR_PATH", str(tmp_path / "does-not-exist"))
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as ei:
        build_portal.main(["--surveys", str(_empty_surveys(tmp_path)), "--out", str(out), "--allow-empty"])
    assert "AUSMT_VALIDATOR_PATH" in str(ei.value), "must name the offending env var, not fail silently"


def test_no_validate_still_builds(tmp_path):
    """The explicit opt-out keeps working (now the ONLY way to build without the gate)."""
    out = tmp_path / "out"
    rc = build_portal.main(["--surveys", str(_empty_surveys(tmp_path)), "--out", str(out),
                            "--allow-empty", "--no-validate"])
    assert rc == 0, "--no-validate must still build cleanly"


def test_env_var_path_resolves_real_validator(tmp_path, monkeypatch):
    """AUSMT_VALIDATOR_PATH pointing at a real validator dir resolves and is used (both the directory
    form and the direct-file form are accepted). C35b/D3 + D3.1 (review F7): resolution is the four-arm
    enumeration in _resolve_validator_dir — sibling, else vendored, else SKIP only in the engine
    image's gateway-less topology (arm iii, unreachable on any monorepo checkout), else FAIL (a true
    broken checkout, arm iv)."""
    validator_dir = _resolve_validator_dir()  # skips ONLY in the engine-image topology (D3.1 iii)
    monkeypatch.setenv("AUSMT_VALIDATOR_PATH", str(validator_dir))
    v = build_portal._load_validator()
    assert v is not None and hasattr(v, "validate"), "env-var directory form did not resolve"

    monkeypatch.setenv("AUSMT_VALIDATOR_PATH", str(validator_dir / "validate_survey.py"))
    v2 = build_portal._load_validator()
    assert v2 is not None and hasattr(v2, "validate"), "env-var direct-file form did not resolve"

    out = tmp_path / "out"
    rc = build_portal.main(["--surveys", str(_empty_surveys(tmp_path)), "--out", str(out), "--allow-empty"])
    assert rc == 0, "a real, env-resolved validator must let a valid (empty) build proceed"


# --------------------------------------------------------------------------------------------------
# C35b/D3.1 falsifiability — both new arms of the environment enumeration must be reachable and
# distinct (Invariant 10: a skip arm that could swallow a real broken checkout would be vacuous).
# _repo_root() is the seam: point it at a scratch topology, never at the real tree.
# --------------------------------------------------------------------------------------------------
def test_d31_image_topology_skips_with_exact_reason(tmp_path, monkeypatch):
    """D3.1 arm (iii) — falsifiability (a): a scratch root shaped like the ENGINE IMAGE (/app: an
    engine tree, NO gateway dir, no sibling beside it) must SKIP with the exact D3.1 reason string,
    NOT fail. FAILS IF the resolver raises AssertionError (the pre-D3.1 image-build red) or skips with
    a different reason (the tripwire allow-list matches this exact substring)."""
    root = tmp_path / "app"
    (root / "engine" / "tests").mkdir(parents=True)
    monkeypatch.setattr(sys.modules[__name__], "_repo_root", lambda: root)
    with pytest.raises(pytest.skip.Exception) as ei:
        _resolve_validator_dir()
    assert IMAGE_TOPOLOGY_SKIP_REASON in str(ei.value), (
        f"skip fired with the wrong reason: {ei.value}")


def test_d31_gateway_present_vendored_missing_fails(tmp_path, monkeypatch):
    """D3.1 arm (iv) — falsifiability (b): a scratch MONOREPO root (gateway/ present) whose vendored
    fixture is missing must FAIL (broken checkout) — the skip arm must NOT swallow it. FAILS IF the
    resolver skips (or returns) instead of raising."""
    root = tmp_path / "repo"
    (root / "engine" / "tests").mkdir(parents=True)
    (root / "gateway").mkdir()
    monkeypatch.setattr(sys.modules[__name__], "_repo_root", lambda: root)
    with pytest.raises(AssertionError) as ei:
        _resolve_validator_dir()
    assert "BROKEN CHECKOUT" in str(ei.value)
