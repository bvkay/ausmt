"""Runner-side station-removal tests (station/EDI removal through the curator UI).

These exercise gateway.runner.edit's new `list_stations` and `remove_stations` job kinds DIRECTLY
— the same in-suite-reaches-the-runner pattern as test_edit_runner.py. ruamel.yaml is a runner
(engine-image) dependency; these run wherever ruamel is installed.

A station is one .edi file under <slug>/transfer_functions/edi/. The survey.yaml carries NO station
manifest (verified: the station list IS the EDI files on disk — gateway/runner/intake._station_count
globs them, and the validator derives its count the same way), so a removal is: git rm the EDIs +
a semver-greater version bump + a required release note appended to release_notes. No survey.yaml
station-list field is touched.

Load-bearing tests (each states its failure criterion, Invariant 10):
  - listing enumerates the EDIs with their derived station ids;
  - remove validates a scratch copy WITHOUT the removed files (reuse of the merge scratch machinery,
    minus the removed EDIs — NOT a new validation path);
  - removing ALL stations is refused (at least one EDI must remain);
  - removing a file that vanished since the form rendered is refused (stale selection);
  - the version bumps and the release note lands in release_notes.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from gateway.runner import edit
from gateway.runner.runner import RunnerConfig

# A survey.yaml with several EDIs. The station list is the EDI files, not a yaml field.
MULTI_SURVEY = """\
schema_version: "0.2"
slug: multi-survey-2026
project_name: Multi Survey
version: 1.2.0
country: Australia
region: South Australia

access:
  level: open
  embargo_until: null
  contact: null

license: CC-BY-4.0

# unknown key must survive verbatim
custom_local_note: "keep me byte-for-byte"
"""

STATIONS = ("SA225.edi", "SA226.edi", "SA227.edi")


def _write_multi(root: Path, slug: str = "multi-survey-2026",
                 yaml_text: str = MULTI_SURVEY, stations=STATIONS) -> Path:
    pkg = root / "surveys" / slug
    edi = pkg / "transfer_functions" / "edi"
    edi.mkdir(parents=True)
    with open(pkg / "survey.yaml", "w", encoding="utf-8", newline="") as fh:
        fh.write(yaml_text)
    for name in stations:
        (edi / name).write_text(">HEAD\n  DATAID=%s\n>END\n" % name, encoding="utf-8")
    return pkg


def _cfg(tmp_path: Path, *, validator_path: str = "") -> RunnerConfig:
    return RunnerConfig(
        incoming_dir=tmp_path / "gw" / "incoming",
        quarantine_dir=tmp_path / "gw" / "quarantine",
        jobs_dir=tmp_path / "gw" / "jobs",
        validator_path=validator_path,
        surveys_root=tmp_path / "surveys-live",
    )


def _dispatch(cfg: RunnerConfig, job: dict) -> dict:
    scratch = cfg.jobs_dir / "edit" / "scratch" / "t"
    return edit._dispatch_edit(cfg, job, scratch)


# ---- listing -------------------------------------------------------------------------------------

def test_list_stations_enumerates_edis_with_derived_ids(tmp_path):
    """A `list_stations` job returns one entry per EDI with its filename and derived station id
    (the filename stem), sorted deterministically. FAILS IF a station is missed, an extra non-EDI
    file leaks in, or the ordering is unstable."""
    pkg = _write_multi(tmp_path / "surveys-live")
    # A stray non-EDI file must NOT be listed as a station.
    (pkg / "transfer_functions" / "edi" / "notes.txt").write_text("x", encoding="utf-8")
    result = _dispatch(_cfg(tmp_path), {"kind": "list_stations", "slug": "multi-survey-2026"})
    assert result["ok"] is True
    names = [s["filename"] for s in result["stations"]]
    ids = [s["station_id"] for s in result["stations"]]
    assert names == ["SA225.edi", "SA226.edi", "SA227.edi"]
    assert ids == ["SA225", "SA226", "SA227"]
    assert result["version"] == "1.2.0"


# ---- removal -------------------------------------------------------------------------------------

def test_remove_stations_bumps_version_and_appends_note(tmp_path):
    """Removing one station bumps the version (minor by default for a content change) and appends a
    release_notes entry carrying the note. FAILS IF the version does not increase, the note is not
    recorded, or the removed set is wrong."""
    _write_multi(tmp_path / "surveys-live")
    result = _dispatch(_cfg(tmp_path), {
        "kind": "remove_stations", "slug": "multi-survey-2026",
        "filenames": ["SA226.edi"], "bump": "minor",
        "note": "Withdrawn consent for SA226.", "today": "2026-07-08"})
    assert result["ok"] is True
    assert result["removed"] == ["SA226.edi"]
    assert result["station_count_before"] == 3
    assert result["station_count_after"] == 2
    assert result["new_version"] == "1.3.0"
    new = result["new_yaml"]
    assert "release_notes:" in new
    assert "Withdrawn consent for SA226." in new
    # The survey.yaml station list is NOT a yaml field: nothing but version + release_notes changed.
    assert 'custom_local_note: "keep me byte-for-byte"' in new
    # The diff is over survey.yaml only (the EDI deletion is a git op, reported separately).
    assert "survey.yaml" in result["diff"]


def test_remove_all_stations_is_refused(tmp_path):
    """Selecting every EDI is refused — deleting a whole survey is a different operation; at least
    one station must remain. FAILS IF an all-stations removal is allowed to proceed."""
    _write_multi(tmp_path / "surveys-live")
    with pytest.raises(edit.EditError) as exc:
        _dispatch(_cfg(tmp_path), {
            "kind": "remove_stations", "slug": "multi-survey-2026",
            "filenames": list(STATIONS), "bump": "minor", "note": "all", "today": "2026-07-08"})
    assert "at least one" in str(exc.value).lower()


def test_remove_vanished_file_is_refused(tmp_path):
    """A selected file that no longer exists on disk (stale form) is refused with a clear error —
    never a half-removal. FAILS IF a missing selection is silently ignored and the removal proceeds
    for the rest."""
    _write_multi(tmp_path / "surveys-live")
    with pytest.raises(edit.EditError) as exc:
        _dispatch(_cfg(tmp_path), {
            "kind": "remove_stations", "slug": "multi-survey-2026",
            "filenames": ["SA226.edi", "GHOST.edi"], "bump": "minor",
            "note": "stale", "today": "2026-07-08"})
    msg = str(exc.value).lower()
    assert "ghost.edi" in msg or "no longer" in msg or "not found" in msg


def test_remove_empty_selection_is_refused(tmp_path):
    """An empty selection is refused (nothing to remove). FAILS IF a no-op removal is treated as a
    valid change and bumps the version for no reason."""
    _write_multi(tmp_path / "surveys-live")
    with pytest.raises(edit.EditError) as exc:
        _dispatch(_cfg(tmp_path), {
            "kind": "remove_stations", "slug": "multi-survey-2026",
            "filenames": [], "bump": "minor", "note": "none", "today": "2026-07-08"})
    assert "no station" in str(exc.value).lower() or "select" in str(exc.value).lower()


def test_remove_requires_a_note(tmp_path):
    """A removal requires a release note (the audit trail — who removed what and why). FAILS IF a
    blank note is accepted."""
    _write_multi(tmp_path / "surveys-live")
    with pytest.raises(edit.EditError) as exc:
        _dispatch(_cfg(tmp_path), {
            "kind": "remove_stations", "slug": "multi-survey-2026",
            "filenames": ["SA226.edi"], "bump": "minor", "note": "   ", "today": "2026-07-08"})
    assert "note" in str(exc.value).lower()


def test_remove_validates_scratch_without_the_removed_files(tmp_path):
    """The validator must run over a scratch copy that DOES NOT contain the removed EDIs — so a
    check that keys on the surviving station set sees the post-removal reality. FAILS IF the scratch
    copy still carries the removed file (the validator would validate the wrong package). Observes
    the tree the REAL validator subprocess is pointed at, by patching the lowest-level _run_validator
    seam and inspecting the on-disk scratch package it receives (an independent observable, not the
    runner's own metadata)."""
    _write_multi(tmp_path / "surveys-live")
    seen: dict = {}

    def _spy(validator_path: str, package_root: Path) -> dict:
        edi = package_root / "transfer_functions" / "edi"
        seen["files"] = sorted(p.name for p in edi.iterdir()) if edi.is_dir() else []
        seen["yaml"] = (package_root / "survey.yaml").read_text(encoding="utf-8")
        return {"items": [{"level": "PASS", "check": "structure", "message": "ok"}]}

    orig = edit._run_validator
    edit._run_validator = _spy
    try:
        result = _dispatch(_cfg(tmp_path, validator_path="/fake/validator"), {
            "kind": "remove_stations", "slug": "multi-survey-2026",
            "filenames": ["SA226.edi"], "bump": "minor",
            "note": "remove", "today": "2026-07-08"})
    finally:
        edit._run_validator = orig
    assert result["ok"] is True
    assert "SA226.edi" not in seen["files"]
    assert "SA225.edi" in seen["files"] and "SA227.edi" in seen["files"]
    # And the scratch survey.yaml carried the version bump (validating the real post-edit package).
    assert "1.3.0" in seen["yaml"]
