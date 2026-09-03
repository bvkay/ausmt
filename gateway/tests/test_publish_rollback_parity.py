"""Write-path parity pins for gateway/publish.py (section-3 workflow H: findings G5 + G6).

Two guarantees, proved over the REAL publish primitives with conftest.FakeGit against a real on-disk
surveys-live checkout (the seam test_station_removal_publish.py already uses). The sibling flow tests
monkeypatch the blocking commit wholesale, so they never enter publish.py and never ask either
question; these do.

G5 ROLLBACK PARITY. Every commit path must roll the working tree back on an error BELOW the
PublishError layer (an OSError from write_bytes/copytree, a subprocess failure from the injected git
runner), not only commit_collection_batch. An escaping error leaves surveys-live on the feature
branch with files already git-rm'd, and publish.preflight then refuses EVERY subsequent publish for
EVERY curator until an operator intervenes.

G6 AUDIT-TRAILER INJECTION. A control character in a curator note or curator name must not open a new
line in the commit subject/body: the git history IS the audit trail, so a forged `Approved-by:` line
would be indistinguishable from a real one. The guard lives in the body builders, so it holds for
every caller rather than only the route that remembers to check.

Failure criterion is in each test's docstring (Invariant 10).
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import subprocess
from pathlib import Path

import pytest

from gateway import publish
from gateway.tests.conftest import FakeGit

# The trailer an attacker wants standing on its own line in the audit record. Two distinct values so
# one assertion covers both injection points (the note and the curator name).
_FORGED_NOTE = "Approved-by: mallory"
_FORGED_NAME = "Approved-by: eve"
# The separators a multiline <textarea> can deliver. `\r` counts: str.splitlines breaks on it, so a
# downstream trailer reader can too.
_SEPARATORS = ["\n", "\r\n", "\r"]


def _seed_live(tmp_path: Path, slug: str = "demo-survey-2026",
               stations=("S01.edi", "S02.edi", "S03.edi")) -> Path:
    """A real surveys-live checkout with one published package, so the primitives run their genuine
    path/existence guards instead of being short-circuited."""
    pkg = tmp_path / "surveys-live" / "surveys" / slug
    edi = pkg / "transfer_functions" / "edi"
    edi.mkdir(parents=True)
    (pkg / "survey.yaml").write_text(f"slug: {slug}\nversion: 1.2.0\n", encoding="utf-8")
    for name in stations:
        (edi / name).write_text(f">HEAD\n  DATAID={name}\n>END\n", encoding="utf-8")
    return tmp_path / "surveys-live"


def _yaml_and_sha(slug: str = "demo-survey-2026") -> tuple[bytes, str]:
    new_yaml = f"slug: {slug}\nversion: 1.3.0\n".encode("utf-8")
    return new_yaml, hashlib.sha256(new_yaml).hexdigest()


def _break_write_bytes(monkeypatch, filename: str = "survey.yaml") -> None:
    """Make Path.write_bytes raise ENOSPC for one filename: the findings reproduction (a full disk
    mid-write is the cheapest real error that is not a PublishError)."""
    real_write = pathlib.Path.write_bytes

    def boom(self, data):
        if self.name == filename:
            raise OSError(28, "No space left on device")
        return real_write(self, data)

    monkeypatch.setattr(pathlib.Path, "write_bytes", boom)


class _RaisingGit(FakeGit):
    """FakeGit that raises a NON-PublishError once on one git verb: the git runner itself failing (a
    subprocess.TimeoutExpired from real_git_runner's 300 s bound, an OSError on exec). It raises only
    the first time, so the rollback the guard issues is still served."""

    def __init__(self, *, raise_on: str, exc: Exception):
        super().__init__()
        self._raise_on = raise_on
        self._exc = exc
        self._raised = False

    def __call__(self, args, *, cwd, env=None):
        if not self._raised and list(args[:1]) == [self._raise_on]:
            self._raised = True
            self.calls.append(list(args))
            raise self._exc
        return super().__call__(args, cwd=cwd, env=env)


def _assert_rolled_back(git: FakeGit) -> None:
    """The F3 pin shape (test_c43_stage3b.py:666-693), extended with the branch assertion: the tree
    went back to the captured pre-state AND HEAD is on main again, not left on the feature branch."""
    assert git.rolled_back, f"the error escaped without a rollback: {git.calls}"
    assert git.start_ref in git.reset_targets, f"no reset to the pre-state ref: {git.reset_targets}"
    assert git.branch == "main", f"HEAD left on {git.branch!r}, not back on main"
    assert any(c[:2] == ["branch", "-D"] for c in git.calls), "the feature branch was not deleted"


def _commit_messages(git: FakeGit) -> list[str]:
    """Every -m argument of every commit invocation: subject AND body. The whole message is the audit
    record, so a forged trailer in either half is a forged trailer."""
    out: list[str] = []
    for c in git.calls:
        if "commit" in c:
            out += [c[i + 1] for i, tok in enumerate(c) if tok == "-m" and i + 1 < len(c)]
    return out


def _assert_no_forged_trailer(git: FakeGit) -> None:
    """No injected trailer stands on its own line, and the note text survives collapsed (not dropped)
    so the audit record still says what the curator wrote."""
    msgs = _commit_messages(git)
    assert msgs, f"no commit was issued: {git.calls}"
    for msg in msgs:
        for line in msg.splitlines():
            assert not line.lstrip().startswith("Approved-by:"), \
                f"forged trailer stands on its own line: {msg!r}"
    # Runs of spaces are normalised for the survival check only: a CRLF collapses to TWO spaces, which
    # is the guard doing its job one character at a time, not a dropped note.
    joined = re.sub(r" +", " ", "\n".join(msgs))
    assert f"looks fine {_FORGED_NOTE}" in joined, f"the note was dropped, not collapsed: {joined!r}"
    assert f"curator1 {_FORGED_NAME}" in joined, f"the curator name was dropped: {joined!r}"


# --------------------------------------------------------------------------------------------------
# Rollback parity across all five commit paths
# --------------------------------------------------------------------------------------------------
def test_stage_and_commit_rolls_back_when_staging_raises_oserror(tmp_path, monkeypatch):
    """An OSError from the package copytree must still roll surveys-live back. FAILS IF the
    OSError escapes: HEAD is left on submit/<slug>-<id> with a half-copied package and rolled_back
    False, so preflight refuses every later publish for every curator. RED against `except
    PublishError:` alone, where the OSError propagates out of stage_and_commit untouched."""
    live = _seed_live(tmp_path)
    package_dir = tmp_path / "quarantine" / "sub-1" / "package"
    (package_dir / "new-survey-2026").mkdir(parents=True)
    (package_dir / "new-survey-2026" / "survey.yaml").write_text("slug: new-survey-2026\n",
                                                                 encoding="utf-8")
    git = FakeGit()
    pre = publish.preflight(git, live)

    def boom(*_a, **_k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(publish.shutil, "copytree", boom)
    with pytest.raises(publish.PublishError) as ei:
        publish.stage_and_commit(git, package_dir, live, "new-survey-2026", "sub-1", "curator1",
                                 "a decision note", pre, allow_overwrite=False)
    assert ei.value.phase == "stage-write", ei.value.phase
    _assert_rolled_back(git)


def test_commit_metadata_edit_rolls_back_when_the_yaml_write_raises_oserror(tmp_path, monkeypatch):
    """An OSError from the survey.yaml write must still roll surveys-live back. FAILS IF the
    OSError escapes: survey.yaml is left truncated by the partial write (write_bytes truncates first)
    with rolled_back False. RED against `except PublishError:` alone."""
    live = _seed_live(tmp_path)
    new_yaml, sha = _yaml_and_sha()
    git = FakeGit()
    pre = publish.preflight(git, live)
    _break_write_bytes(monkeypatch)
    with pytest.raises(publish.PublishError) as ei:
        publish.commit_metadata_edit(git, live, "demo-survey-2026", new_yaml, sha, "curator1",
                                     "an edit note", pre)
    assert ei.value.phase == "edit-write", ei.value.phase
    _assert_rolled_back(git)


def test_commit_station_removal_rolls_back_when_the_yaml_write_raises_oserror(tmp_path, monkeypatch):
    """The findings reproduction. The EDIs are git-rm'd BEFORE the survey.yaml write, so an
    escaping OSError leaves surveys-live on stationrm/<slug> with the station files already gone.
    FAILS IF the OSError escapes without a rollback. RED against `except PublishError:` alone."""
    live = _seed_live(tmp_path)
    new_yaml, sha = _yaml_and_sha()
    git = FakeGit()
    pre = publish.preflight(git, live)
    _break_write_bytes(monkeypatch)
    with pytest.raises(publish.PublishError) as ei:
        publish.commit_station_removal(git, live, "demo-survey-2026", new_yaml, ["S02.edi"], sha,
                                       "curator1", "withdrawn consent", pre)
    assert ei.value.phase == "removal-write", ei.value.phase
    # The tree was already mutated when the write failed, which is precisely why rollback is load-bearing.
    assert any(c[:1] == ["rm"] for c in git.calls), f"no git rm was issued: {git.calls}"
    _assert_rolled_back(git)


def test_commit_survey_removal_rolls_back_when_the_git_runner_raises(tmp_path):
    """The retire path has no write of its own, so its non-PublishError comes from the git runner
    (real_git_runner raises subprocess.TimeoutExpired on its 300 s bound, never a PublishError). FAILS
    IF it escapes: HEAD is left on retire/<slug> with the whole package already git-rm'd. RED against
    `except PublishError:` alone, where TimeoutExpired propagates out uncaught."""
    live = _seed_live(tmp_path)
    git = _RaisingGit(raise_on="rm",
                      exc=subprocess.TimeoutExpired(cmd=["git", "rm"], timeout=300))
    pre = publish.preflight(git, live)
    with pytest.raises(publish.PublishError) as ei:
        publish.commit_survey_removal(git, live, "demo-survey-2026", "curator1", "retired", pre)
    assert ei.value.phase == "retire-write", ei.value.phase
    _assert_rolled_back(git)


# --------------------------------------------------------------------------------------------------
# Control characters in a note/name cannot forge a commit trailer
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("sep", _SEPARATORS)
def test_metadata_edit_note_cannot_forge_a_commit_trailer(tmp_path, sep):
    """A newline in the edit note must not put `Approved-by:` on its own line in the commit the
    design calls the audit record. FAILS IF the forged trailer stands alone, or if the note is dropped
    instead of collapsed. RED against the raw f-string body builder."""
    live = _seed_live(tmp_path)
    new_yaml, sha = _yaml_and_sha()
    git = FakeGit()
    pre = publish.preflight(git, live)
    publish.commit_metadata_edit(git, live, "demo-survey-2026", new_yaml, sha,
                                 f"curator1{sep}{_FORGED_NAME}", f"looks fine{sep}{_FORGED_NOTE}",
                                 pre)
    _assert_no_forged_trailer(git)


@pytest.mark.parametrize("sep", _SEPARATORS)
def test_station_removal_note_cannot_forge_a_commit_trailer(tmp_path, sep):
    """The same guard on the station-removal note, whose textarea is equally multiline. FAILS IF
    the forged trailer stands alone, or if the note is dropped instead of collapsed. RED against the
    raw f-string body builder."""
    live = _seed_live(tmp_path)
    new_yaml, sha = _yaml_and_sha()
    git = FakeGit()
    pre = publish.preflight(git, live)
    publish.commit_station_removal(git, live, "demo-survey-2026", new_yaml, ["S02.edi"], sha,
                                   f"curator1{sep}{_FORGED_NAME}",
                                   f"looks fine{sep}{_FORGED_NOTE}", pre)
    _assert_no_forged_trailer(git)


@pytest.mark.parametrize("sep", _SEPARATORS)
def test_survey_retire_note_cannot_forge_a_commit_trailer(tmp_path, sep):
    """The same guard on the retire note, the most destructive of the three operations. FAILS IF
    the forged trailer stands alone, or if the note is dropped instead of collapsed. RED against the
    raw f-string body builder."""
    live = _seed_live(tmp_path)
    git = FakeGit()
    pre = publish.preflight(git, live)
    publish.commit_survey_removal(git, live, "demo-survey-2026", f"curator1{sep}{_FORGED_NAME}",
                                  f"looks fine{sep}{_FORGED_NOTE}", pre)
    _assert_no_forged_trailer(git)
