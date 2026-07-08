"""Unit tests for publish.commit_station_removal — the git primitive that deletes station EDIs +
writes the version-bumped survey.yaml in one commit, with byte-exact rollback on any failure.

Driven through FakeGit (records every git invocation + models `rm`/`clean`/`reset` so the rollback
is provable) against a real on-disk surveys-live checkout. Independent observables: the git argv the
primitive issues, which files actually leave the working tree, and the survey.yaml bytes on disk.

Failure criterion is in each test's docstring (Invariant 10).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from gateway import publish
from gateway.tests.conftest import COMMIT_AUTHOR_MARKERS, FakeGit


def _seed_live(tmp_path: Path, slug: str = "multi-survey-2026",
               stations=("SA225.edi", "SA226.edi", "SA227.edi")) -> Path:
    pkg = tmp_path / "surveys-live" / "surveys" / slug
    edi = pkg / "transfer_functions" / "edi"
    edi.mkdir(parents=True)
    (pkg / "survey.yaml").write_text("slug: %s\nversion: 1.2.0\n" % slug, encoding="utf-8")
    for name in stations:
        (edi / name).write_text(">HEAD\n  DATAID=%s\n>END\n" % name, encoding="utf-8")
    return tmp_path / "surveys-live"


def _pre():
    return publish.PreState(ref="cafe0000000000000000000000000000000000ff", branch="main")


def test_commit_station_removal_git_rms_selected_and_writes_yaml(tmp_path):
    """The primitive git-rm's exactly the selected EDIs, writes the new survey.yaml, and commits with
    the gateway identity. FAILS IF a non-selected file is removed, the yaml is not written, or the
    commit is missing/mis-attributed."""
    live = _seed_live(tmp_path)
    new_yaml = b"slug: multi-survey-2026\nversion: 1.3.0\n"
    sha = hashlib.sha256(new_yaml).hexdigest()
    git = FakeGit()
    ref = publish.commit_station_removal(
        git, live, "multi-survey-2026", new_yaml, ["SA226.edi"], sha, "curator1",
        "withdrawn consent", _pre())
    assert ref  # a commit sha came back
    edi = live / "surveys" / "multi-survey-2026" / "transfer_functions" / "edi"
    assert not (edi / "SA226.edi").exists()          # removed
    assert (edi / "SA225.edi").exists()              # survivor untouched
    assert (edi / "SA227.edi").exists()
    assert (live / "surveys" / "multi-survey-2026" / "survey.yaml").read_bytes() == new_yaml
    # git rm was issued with the repo-relative EDI path.
    rm_calls = [c for c in git.calls if c[:1] == ["rm"]]
    assert rm_calls, "no git rm issued"
    assert any("surveys/multi-survey-2026/transfer_functions/edi/SA226.edi" in c for c in rm_calls)
    # committed with the gateway identity (never a submitter).
    commit = next(c for c in git.calls if "commit" in c)
    assert any(any(m in part for part in commit) for m in COMMIT_AUTHOR_MARKERS)


def test_commit_station_removal_hash_pin_rejects_stale_preview(tmp_path):
    """A mismatch between the previewed sha and the actual bytes 409s (PublishError) and writes
    nothing. FAILS IF stale bytes are committed."""
    live = _seed_live(tmp_path)
    new_yaml = b"slug: multi-survey-2026\nversion: 1.3.0\n"
    with pytest.raises(publish.PublishError) as exc:
        publish.commit_station_removal(
            FakeGit(), live, "multi-survey-2026", new_yaml, ["SA226.edi"],
            "0" * 64, "curator1", "x", _pre())
    assert exc.value.phase == "hash-pin"


def test_commit_station_removal_refuses_all_stations(tmp_path):
    """Selecting every EDI is refused at the publish gate too (defence in depth). FAILS IF the
    primitive would remove the last station."""
    live = _seed_live(tmp_path)
    new_yaml = b"slug: multi-survey-2026\nversion: 1.3.0\n"
    sha = hashlib.sha256(new_yaml).hexdigest()
    with pytest.raises(publish.PublishError) as exc:
        publish.commit_station_removal(
            git := FakeGit(), live, "multi-survey-2026", new_yaml,
            ["SA225.edi", "SA226.edi", "SA227.edi"], sha, "curator1", "x", _pre())
    assert "at least one" in exc.value.message.lower()
    # No EDI was actually removed (guard fires BEFORE any git rm).
    edi = live / "surveys" / "multi-survey-2026" / "transfer_functions" / "edi"
    assert (edi / "SA225.edi").exists()
    assert not any(c[:1] == ["rm"] for c in git.calls)


def test_commit_station_removal_refuses_vanished_file(tmp_path):
    """A selected file that vanished since the preview is refused (stale). FAILS IF a missing
    selection is silently skipped and the rest committed."""
    live = _seed_live(tmp_path)
    new_yaml = b"slug: multi-survey-2026\nversion: 1.3.0\n"
    sha = hashlib.sha256(new_yaml).hexdigest()
    with pytest.raises(publish.PublishError) as exc:
        publish.commit_station_removal(
            FakeGit(), live, "multi-survey-2026", new_yaml, ["GHOST.edi"], sha, "curator1", "x",
            _pre())
    assert exc.value.phase == "stale"


def test_commit_station_removal_rolls_back_on_push_fail(tmp_path):
    """A push failure rolls surveys-live back to the pre-state (reset --hard to pre.ref) and re-raises.
    FAILS IF a failed push leaves a half-applied removal without a rollback."""
    live = _seed_live(tmp_path)
    new_yaml = b"slug: multi-survey-2026\nversion: 1.3.0\n"
    sha = hashlib.sha256(new_yaml).hexdigest()
    git = FakeGit(fail_on={"push": (1, "remote rejected")})
    with pytest.raises(publish.PublishError) as exc:
        publish.commit_station_removal(
            git, live, "multi-survey-2026", new_yaml, ["SA226.edi"], sha, "curator1", "x", _pre())
    assert exc.value.phase == "git-push"
    assert git.rolled_back, "a push failure must trigger the byte-exact rollback"


def test_commit_station_removal_rejects_traversal_name(tmp_path):
    """A selected name with path parts / traversal is refused (never reaches git rm). FAILS IF a
    crafted name could escape the edi/ dir."""
    live = _seed_live(tmp_path)
    new_yaml = b"slug: multi-survey-2026\nversion: 1.3.0\n"
    sha = hashlib.sha256(new_yaml).hexdigest()
    with pytest.raises(publish.PublishError):
        publish.commit_station_removal(
            FakeGit(), live, "multi-survey-2026", new_yaml, ["../../etc/passwd"], sha, "curator1",
            "x", _pre())
