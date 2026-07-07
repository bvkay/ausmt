"""C12: build identity. Every build writes <out>/build.json — {build_id, engine_commit,
source_commit, generated} — so a served portal can be traced to the engine + surveys commits that
produced it (the build<->data handshake the review flagged as missing). build_id is a plain
concatenation "<engine_commit>-<source_commit>-<generated>", but an unresolved commit segment is
now rendered as the literal string "unknown" (never the Python str(None) "None" — U2: the live
footer showed "None - None - <date>" on the first container deployment because a bare f-string
folded None straight into the join). source_commit is ALSO folded into build_provenance.json so the
one existing provenance document carries the handshake too, not just the new file.

U2: engine_commit also falls back to the AUSMT_ENGINE_COMMIT env var when git resolution yields
None — the engine image COPYs engine/ WITHOUT a .git directory, so _git_commit_at(HERE) is always
None inside a container; CI bakes the actual commit into that env var at image-build time (see
engine.Dockerfile's ARG GIT_SHA / ENV AUSMT_ENGINE_COMMIT and deploy-images.yml's build-arg).
Precedence: real git result first, then the env var, then the "unknown" placeholder.

NON-VACUOUS (Invariant 10): source_commit is asserted None for a --surveys root that is NOT inside a
git repo, and asserted EQUAL to the actual `git rev-parse --short HEAD` of a tmp_path git repo built
around a fixture survey copy for the git case — an independent observable (the git command's own
output), not a re-derivation of whatever the build computed internally.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")   # these builds process real EDIs (engine/data fixture) -> the
                                     # sole extractor stack is required, unlike test_empty_build.py's
                                     # zero-survey (--allow-empty) case which never reaches it.

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SURVEYS = ROOT / "data"          # data/sample-survey: the existing engine fixture survey package


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True)


def _build(surveys_dir, tmp_path, *extra):
    out = tmp_path / "data"
    r = subprocess.run([sys.executable, "-m", "extract.build_portal", "--surveys", str(surveys_dir),
                        "--out", str(out), "--no-validate", *extra],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out


def test_build_json_present_with_expected_keys_and_null_source_commit_outside_git(tmp_path):
    # SURVEYS (engine/data) is copied to a tmp dir that is NOT a git repo, so source_commit must be
    # None — proves the field is not fabricated when there is nothing to report.
    surveys_copy = tmp_path / "surveys_nogit"
    shutil.copytree(SURVEYS, surveys_copy)
    out = _build(surveys_copy, tmp_path)
    p = out / "build.json"
    assert p.exists(), "build.json missing"
    doc = json.loads(p.read_text(encoding="utf-8"))
    for k in ("build_id", "engine_commit", "source_commit", "generated"):
        assert k in doc, f"build.json missing key {k}"
    assert doc["source_commit"] is None, f"expected null source_commit outside a git repo, got {doc['source_commit']!r}"
    # U2: build_id renders a None source_commit as the WORD "unknown" in the join, never Python's
    # str(None) "None" (this is the exact live-footer bug: "None - None - <date>").
    assert "None" not in doc["build_id"], f"literal 'None' leaked into build_id: {doc['build_id']!r}"
    assert doc["build_id"] == f"{doc['engine_commit']}-unknown-{doc['generated']}"
    # build_provenance.json carries the SAME handshake field (the review's missing build<->data link)
    prov = json.loads((out / "build_provenance.json").read_text(encoding="utf-8"))
    assert prov["source_commit"] == doc["source_commit"]


def test_build_json_source_commit_matches_git_head_of_surveys_dir(tmp_path):
    # A REAL tmp git repo around a copy of the fixture survey: init + add + commit, then assert
    # build.json's source_commit equals the INDEPENDENTLY queried `git rev-parse --short HEAD` of
    # that repo -- not a re-derivation of the build's own internal state.
    surveys_copy = tmp_path / "surveys_git"
    shutil.copytree(SURVEYS, surveys_copy)
    _git(["init"], surveys_copy)
    _git(["config", "user.email", "test@example.com"], surveys_copy)
    _git(["config", "user.name", "Test"], surveys_copy)
    _git(["add", "-A"], surveys_copy)
    _git(["commit", "-m", "fixture snapshot"], surveys_copy)
    expected = _git(["rev-parse", "--short", "HEAD"], surveys_copy).stdout.strip()
    assert expected, "expected a resolvable short HEAD in the tmp git fixture repo"

    out = _build(surveys_copy, tmp_path)
    doc = json.loads((out / "build.json").read_text(encoding="utf-8"))
    assert doc["source_commit"] == expected, (doc["source_commit"], expected)
    prov = json.loads((out / "build_provenance.json").read_text(encoding="utf-8"))
    assert prov["source_commit"] == expected


def test_build_json_and_provenance_carry_served_tool_versions(tmp_path):
    """C32 §2: build.json AND build_provenance.json gain additive mt_metadata_version / mth5_version
    keys, read from the SINGLE lib_versions() source of truth. This build runs the real mt_metadata/mth5
    stack (pytest.importorskip at module top), so both keys must be present and match the imported
    library __version__ (an independent observable — not a re-read of the build's own output). FAILS if a
    key is missing or disagrees with the actually-installed library, or if the C12 build_id format drifted."""
    import mt_metadata
    import mth5
    surveys_copy = tmp_path / "surveys_ver"
    shutil.copytree(SURVEYS, surveys_copy)
    out = _build(surveys_copy, tmp_path)
    bj = json.loads((out / "build.json").read_text(encoding="utf-8"))
    prov = json.loads((out / "build_provenance.json").read_text(encoding="utf-8"))
    for doc, name in ((bj, "build.json"), (prov, "build_provenance.json")):
        assert doc.get("mt_metadata_version") == mt_metadata.__version__, \
            f"{name} mt_metadata_version {doc.get('mt_metadata_version')!r} != {mt_metadata.__version__!r}"
        assert doc.get("mth5_version") == mth5.__version__, \
            f"{name} mth5_version {doc.get('mth5_version')!r} != {mth5.__version__!r}"
    # additive only: the C12 identity fields + build_id string format are untouched by the version keys
    assert bj["build_id"] == f"{bj['engine_commit']}-unknown-{bj['generated']}", \
        "C32 version keys must not alter the C12 build_id string format"


def test_build_json_deterministic_aside_from_generated(tmp_path):
    # Two builds of the SAME (non-git) surveys dir must agree on build_id/engine_commit/source_commit
    # (only 'generated' — the wall-clock timestamp — may differ), so a build.json diff between two
    # runs of identical inputs is a pure timestamp bump, not a hidden nondeterminism.
    surveys_copy = tmp_path / "surveys_det"
    shutil.copytree(SURVEYS, surveys_copy)
    out1 = _build(surveys_copy, tmp_path / "b1")
    out2 = _build(surveys_copy, tmp_path / "b2")
    d1 = json.loads((out1 / "build.json").read_text(encoding="utf-8"))
    d2 = json.loads((out2 / "build.json").read_text(encoding="utf-8"))
    assert d1["engine_commit"] == d2["engine_commit"]
    assert d1["source_commit"] == d2["source_commit"]


# --- U2: engine_commit env fallback + "unknown" (never literal "None") ---------------------------
# These call build_identity() directly (unit-level, not a subprocess build) so git resolution can be
# monkeypatched to None regardless of whether this checkout happens to be a git repo -- the container
# scenario the bug came from (engine/ COPYed without .git, so _git_commit_at(HERE) is always None).

sys.path.insert(0, str(ROOT))   # ROOT = engine/ -- make `extract.build_portal` importable
import extract.build_portal as bp  # noqa: E402


def test_engine_commit_env_fallback_when_git_unavailable(tmp_path, monkeypatch):
    # FAILS PRE-FIX: build_identity() never consulted AUSMT_ENGINE_COMMIT at all, so with git
    # forced to None here engine_commit would stay None instead of picking up the env value --
    # exactly the containerised-build gap (no .git shipped in the image).
    monkeypatch.setattr(bp, "_git_commit_at", lambda cwd: None)
    monkeypatch.setenv("AUSMT_ENGINE_COMMIT", "cafef00d")
    doc = bp.build_identity(None)
    assert doc["engine_commit"] == "cafef00d", (
        f"expected env fallback 'cafef00d', got {doc['engine_commit']!r}")


def test_build_id_never_contains_literal_none_string(tmp_path, monkeypatch):
    # FAILS PRE-FIX: with git AND the env fallback both unresolved, the current code's plain
    # f"{engine_commit}-{source_commit}-{generated}" folds Python's None straight into the string,
    # producing "None-None-<ts>" -- the literal live-footer bug ("None - None - <date>"). Every
    # unresolved segment must render as the word "unknown" instead.
    monkeypatch.setattr(bp, "_git_commit_at", lambda cwd: None)
    monkeypatch.delenv("AUSMT_ENGINE_COMMIT", raising=False)
    doc = bp.build_identity(None)
    assert doc["engine_commit"] == "unknown", f"expected 'unknown', got {doc['engine_commit']!r}"
    assert doc["source_commit"] is None, "source_commit stays None (surveys_root=None -> no build)"
    assert "None" not in doc["build_id"], f"literal 'None' leaked into build_id: {doc['build_id']!r}"
    assert "unknown" in doc["build_id"], f"expected 'unknown' placeholder in build_id: {doc['build_id']!r}"


# --- C32 §2: lib_versions() is the ONE source of truth for served tool versions --------------------

def test_lib_versions_is_single_source_reused_by_cache_salt():
    """The same lib_versions() helper feeds BOTH the C18 cache salt and the C32 served version keys, so
    the two facts can never diverge. Sane shape: a dict whose keys, when present, are strings; and when
    the mt_metadata/mth5 stack IS installed (it is here — module-top importorskip) both keys resolve to
    the imported __version__. FAILS if the helper returns a non-dict, a non-string version, or disagrees
    with the actually-installed library."""
    import mt_metadata
    import mth5
    v = bp.lib_versions()
    assert isinstance(v, dict), f"lib_versions() must return a dict, got {type(v).__name__}"
    for k, val in v.items():
        assert isinstance(val, str) and val, f"version for {k!r} must be a non-empty string, got {val!r}"
    assert v.get("mt_metadata") == mt_metadata.__version__
    assert v.get("mth5") == mth5.__version__
