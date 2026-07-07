"""C31 runner-side edit tests (design §3.1/§3.2 + adversarial-review fixes). These exercise
gateway.runner.edit DIRECTLY — the same in-suite-reaches-the-runner pattern as test_runner.py.
ruamel.yaml is a runner (engine-image) dependency; these tests run wherever ruamel is installed
(the ausmt env locally; the engine lock in CI's full lane).

Load-bearing tests here:
  - the §3.1 round-trip fidelity proof (comments + unknown key byte-identical across an edit);
  - review FIX 3, the parser differential (patched "on"/"no"/"12:34:56" must re-read as STRINGS
    under PyYAML safe_load — the reader the validator and build_portal use);
  - review FIX 2, scratch containment (nothing the merge does may touch the surveys tree);
  - the jobs/edit/ queue mechanics (claim-by-rename, done-file results) that FIX 1 moved the
    transport onto.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gateway.runner import edit
from gateway.runner.runner import RunnerConfig

# A well-formed block-style survey.yaml with comments, an UNKNOWN custom key the form never models,
# a null field, and a block-scalar abstract. Mirrors the legitimate fidelity challenges of the real
# vulcan-2022 exemplar (comments + unknown keys + null + block scalar) WITHOUT its two source-level
# quirks that no YAML round-tripper preserves (manual intra-flow-map column alignment, and a
# pre-existing unquoted `LEMI (LC ISR, Lviv)` flow value whose internal comma any conformant parser —
# ruamel AND the PyYAML the validator uses — splits into a spurious key). See the residual note in
# edit._yaml() and the C31 report.
EXEMPLAR = """\
schema_version: "0.2"
slug: demo-survey-2026
project_name: Demo Survey            # human-readable name
version: 1.0.0
country: Australia
region: South Australia

organisation:
  name: University of Example
  ror: null                          # ROR URL when known

abstract: >
  A short paragraph describing the survey that a naive emitter would re-wrap but which
  must stay exactly as written, word for word, across the round trip.

identifiers:
  dataset_doi: null                  # none minted yet
  survey_pid: null

access:
  level: open
  embargo_until: null
  contact: null

license: CC-BY-4.0

# an unknown custom key the editor form does not model — must survive verbatim
custom_local_note: "keep me byte-for-byte"
"""


def _write_package(root: Path, slug: str = "demo-survey-2026",
                   yaml_text: str = EXEMPLAR) -> Path:
    pkg = root / "surveys" / slug
    (pkg / "transfer_functions" / "edi").mkdir(parents=True)
    with open(pkg / "survey.yaml", "w", encoding="utf-8", newline="") as fh:
        fh.write(yaml_text)
    (pkg / "transfer_functions" / "edi" / "S01.edi").write_text(
        ">HEAD\n  LAT=-30:08:45\n  LONG=136:58:12\n>FREQ\n", encoding="utf-8")
    return pkg


def _cfg(tmp_path: Path, *, validator_path: str = "") -> RunnerConfig:
    """A RunnerConfig whose surveys_root is the tmp surveys-live and whose jobs dir (scratch home)
    is OUTSIDE it — the same topology as the real gw-runner container."""
    return RunnerConfig(
        incoming_dir=tmp_path / "gw" / "incoming",
        quarantine_dir=tmp_path / "gw" / "quarantine",
        jobs_dir=tmp_path / "gw" / "jobs",
        validator_path=validator_path,
        surveys_root=tmp_path / "surveys-live",
    )


def _merge(cfg: RunnerConfig, slug: str = "demo-survey-2026", **overrides) -> dict:
    job = {"kind": "merge", "slug": slug, "patch": {"region": "Northern Territory"},
           "bump": "patch", "note": "Corrected region.", "today": "2026-07-06"}
    job.update(overrides)
    scratch = cfg.jobs_dir / "edit" / "scratch" / "t"
    return edit._dispatch_edit(cfg, job, scratch)


# --------------------------------------------------------------------------------------------------
# §0.2 / §3.1 round-trip fidelity
# --------------------------------------------------------------------------------------------------
def test_noop_round_trip_is_byte_identical():
    # The floor the whole design rests on: loading and re-emitting an UNEDITED well-formed
    # survey.yaml is byte-for-byte identical (comments, null tokens, block scalar, unknown key all
    # preserved). FAILS IF the ruamel config drops the `null` token, re-wraps, or reindents.
    raw = EXEMPLAR.encode("utf-8")
    assert edit._dump_bytes(edit._load_bytes(raw)) == raw


def test_round_trip_fidelity_edit_touches_only_field_version_notes(tmp_path):
    # §3.1: edit ONE field (region); the emitted diff touches ONLY region + version + the appended
    # release_notes entry. The comment lines and the unknown custom key are byte-identical.
    # proven-failing 2026-07-06 (design phase): with ruamel defaults the no-op diff already showed
    # spurious null->empty and re-wrap changes — the tuned _yaml() config is what makes this hold.
    _write_package(tmp_path / "surveys-live")
    result = _merge(_cfg(tmp_path))
    assert result["ok"] is True
    assert result["changed"] == ["region"]
    assert "-region: South Australia" in result["diff"]
    assert "+region: Northern Territory" in result["diff"]
    assert result["new_version"] == "1.0.1"
    new = result["new_yaml"]
    assert "release_notes:" in new
    assert "Corrected region." in new
    assert "# an unknown custom key the editor form does not model — must survive verbatim" in new
    assert 'custom_local_note: "keep me byte-for-byte"' in new
    assert "# human-readable name" in new
    assert "must stay exactly as written, word for word, across the round trip." in new
    # Nothing else changed: every original line EXCEPT the edited field (region) and the managed
    # version line is still present byte-for-byte.
    for line in EXEMPLAR.splitlines():
        if line.startswith(("region:", "version:")) or not line.strip():
            continue
        assert line in new, f"edit disturbed an untouched line: {line!r}"


def test_unknown_key_and_comments_survive_a_map_edit(tmp_path):
    _write_package(tmp_path / "surveys-live")
    result = _merge(
        _cfg(tmp_path),
        patch={"organisation": {"name": "University of Example",
                                "ror": "https://ror.org/00892tw58"}},
        bump="minor", note="Added ROR.")
    assert result["ok"] is True
    assert result["new_version"] == "1.1.0"
    assert "https://ror.org/00892tw58" in result["new_yaml"]
    assert 'custom_local_note: "keep me byte-for-byte"' in result["new_yaml"]


# --------------------------------------------------------------------------------------------------
# review FIX 3: the parser differential (ruamel emits, PyYAML reads)
# --------------------------------------------------------------------------------------------------
def test_patched_ambiguous_strings_reread_as_strings_under_pyyaml(tmp_path):
    # proven failing 2026-07-06 (pre-fix HEAD 4f4e999..a31fc8e): patched region "on" emitted as bare
    # `region: on` -> PyYAML safe_load read True (bool); name "no" -> False; abstract "12:34:56" ->
    # 45296 (YAML-1.1 sexagesimal int). ruamel's own re-read kept them strings, so the diff, the
    # §0.6 sha pin, and the confirm re-run all agreed and NO guard fired — the portal would have
    # served a bool/int the curator never wrote. FAILS IF quote_ambiguous stops quoting the
    # YAML-1.1-retypeable tokens.
    import base64

    import yaml as pyyaml

    _write_package(tmp_path / "surveys-live")
    result = _merge(_cfg(tmp_path),
                    patch={"region": "on", "name": "no", "abstract": "12:34:56"},
                    note="ambiguous scalars")
    assert result["ok"] is True
    emitted = base64.b64decode(result["new_yaml_b64"])
    reread = pyyaml.safe_load(emitted)
    assert reread["region"] == "on" and isinstance(reread["region"], str)
    assert reread["name"] == "no" and isinstance(reread["name"], str)
    assert reread["abstract"] == "12:34:56" and isinstance(reread["abstract"], str)
    # The release-note date is exactly the ISO shape PyYAML retypes to datetime.date — it must stay
    # a string too (the documented survey.yaml convention quotes it).
    entry = reread["release_notes"][-1]
    assert entry["date"] == "2026-07-06" and isinstance(entry["date"], str)
    assert isinstance(entry["version"], str)


def test_patched_ambiguous_map_keys_reread_as_strings_under_pyyaml(tmp_path):
    # Re-review finding (2026-07-06): quote_ambiguous recursed only over dict VALUES, so a curator-
    # supplied ambiguous KEY in a JSON-edited map ('on'/'no'/'12:34:56') emitted bare and PyYAML
    # retyped it (key True / False / 45296) while ruamel's re-read kept it a string — the same
    # differential as FIX 3, one axis over, with diff/sha-pin/confirm all self-consistently blind.
    # proven failing 2026-07-06 on pre-fix HEAD 0b7d386 (evidence in the fix commit).
    # FAILS IF the dict branch stops applying the quoting oracle to keys.
    import base64

    import yaml as pyyaml

    _write_package(tmp_path / "surveys-live")
    result = _merge(_cfg(tmp_path),
                    patch={"collection": {"on": "x", "no": "y", "12:34:56": "z",
                                          "id": "auslamp"}},
                    note="ambiguous keys")
    assert result["ok"] is True
    emitted = base64.b64decode(result["new_yaml_b64"])
    reread = pyyaml.safe_load(emitted)
    keys = set(reread["collection"].keys())
    assert keys == {"on", "no", "12:34:56", "id"}, keys
    for k in keys:
        assert isinstance(k, str)


def test_unambiguous_strings_stay_unquoted(tmp_path):
    # The quoting is surgical: a plain string that PyYAML reads back identically is NOT quoted, so
    # the diff stays minimal and matches the file's prevailing bare style.
    _write_package(tmp_path / "surveys-live")
    result = _merge(_cfg(tmp_path))  # region -> Northern Territory
    assert "+region: Northern Territory" in result["diff"]  # bare, not "+region: \"Northern...\""


def test_needs_quoting_semantics():
    # Quote iff PyYAML would NOT read the bare token back as the identical string. The oracle is
    # PyYAML itself (the downstream reader), not the YAML-1.1 spec: PyYAML deliberately does NOT
    # implement the spec's single-letter y/n booleans, so "y"/"n" correctly stay unquoted.
    for ambiguous in ("on", "off", "yes", "no", "true", "False", "null", "~",
                      "12:34:56", "2026-07-06", "1.5", "007", "", " padded ", "a: b", "x #c",
                      "line1\nline2"):
        assert edit._needs_quoting(ambiguous), ambiguous
    for plain in ("Northern Territory", "CC-BY-4.0", "University of Example", "1.0.1",
                  "LEMI-423", "open", "y", "n"):
        assert not edit._needs_quoting(plain), plain


# --------------------------------------------------------------------------------------------------
# review FIX 2: scratch containment — nothing the merge does may touch the surveys tree
# --------------------------------------------------------------------------------------------------
def test_merge_scratch_never_touches_surveys_tree(tmp_path):
    # proven failing 2026-07-06 (pre-fix HEAD): during validation the scratch copy lived at
    # surveys-live/surveys/_edit_patched/** (6 paths created inside the live tree; a concurrent
    # publish's `git add surveys` would stage them, and a leaked scratch would dirty every later
    # publish preflight — and the gw-runner's /srv/surveys mount is READ-ONLY, so it would also have
    # crashed outright in production). FAILS IF any file/dir is created OR left under surveys-live
    # by a merge, at validation time or after.
    surveys_live = tmp_path / "surveys-live"
    _write_package(surveys_live)
    cfg = _cfg(tmp_path, validator_path=str(tmp_path / "validator"))  # non-empty -> scratch machinery runs

    before = sorted(str(p.relative_to(surveys_live)) for p in surveys_live.rglob("*"))
    seen = {}
    orig = edit._run_validator

    def spy(validator_path, package_root):
        # Snapshot the surveys tree AT VALIDATION TIME (when the scratch copy exists) and record
        # where the copy actually lives.
        seen["during"] = sorted(str(p.relative_to(surveys_live)) for p in surveys_live.rglob("*"))
        seen["scratch_package"] = Path(package_root)
        return {"items": []}

    edit._run_validator = spy
    try:
        result = _merge(cfg)
    finally:
        edit._run_validator = orig

    assert result["ok"] is True
    after = sorted(str(p.relative_to(surveys_live)) for p in surveys_live.rglob("*"))
    assert seen["during"] == before, "scratch files appeared INSIDE surveys-live during validation"
    assert after == before, "the merge left files behind under surveys-live"
    # And the scratch copy lived where it belongs: under the runner's jobs/edit/scratch tree.
    scratch = seen["scratch_package"].resolve()
    assert (cfg.jobs_dir / "edit" / "scratch").resolve() in scratch.parents
    assert surveys_live.resolve() not in scratch.parents


def test_scratch_under_surveys_tree_is_refused(tmp_path):
    # Belt-and-braces: even if a caller wired a scratch dir under the surveys tree, the dispatch
    # refuses before any copy happens.
    surveys_live = tmp_path / "surveys-live"
    _write_package(surveys_live)
    cfg = _cfg(tmp_path, validator_path="x")
    with pytest.raises(edit.EditError) as exc:
        edit._dispatch_edit(cfg, {"kind": "merge", "slug": "demo-survey-2026",
                                  "patch": {"region": "X"}, "bump": "patch", "note": "n",
                                  "today": "2026-07-06"},
                            surveys_live / "surveys" / "scratch-here")
    assert "scratch" in str(exc.value)


# --------------------------------------------------------------------------------------------------
# §3.2 semver + no-op gates
# --------------------------------------------------------------------------------------------------
def test_non_semver_current_version_refused(tmp_path):
    # The semver-greater gate (C31 §0.3) fires when the CURRENT version is not strict semver: the
    # bump cannot be proven greater, so the merge refuses (fail closed) with a fix-it-via-PR hint.
    # (The explicit version override was removed per review FIX 6, so lower/equal targets are no
    # longer constructible through the interface; the comparator itself is pinned below.)
    _write_package(tmp_path / "surveys-live",
                   yaml_text=EXEMPLAR.replace("version: 1.0.0", "version: v2022-final"))
    with pytest.raises(edit.EditError) as exc:
        _merge(_cfg(tmp_path))
    assert "semver" in str(exc.value).lower() or "MAJOR.MINOR.PATCH" in str(exc.value)


def test_missing_bump_refused(tmp_path):
    _write_package(tmp_path / "surveys-live")
    with pytest.raises(edit.EditError) as exc:
        _merge(_cfg(tmp_path), bump="")
    assert "bump" in str(exc.value)


def test_noop_edit_refused(tmp_path):
    # §3.2: submitting the SAME values (no content change) is refused outright.
    _write_package(tmp_path / "surveys-live")
    with pytest.raises(edit.EditError) as exc:
        _merge(_cfg(tmp_path), patch={"region": "South Australia"})
    assert "no changes" in str(exc.value)


def test_valid_patch_bump_appends_release_note(tmp_path):
    _write_package(tmp_path / "surveys-live")
    result = _merge(_cfg(tmp_path), patch={"abstract": "A revised abstract paragraph."},
                    note="Clarified the abstract.")
    assert result["ok"] is True
    new = result["new_yaml"]
    assert "1.0.1" in new
    assert "Clarified the abstract." in new


def test_semver_helpers():
    # §3.2 comparator semantics: lower/equal/non-semver are all NOT greater (the merge-side gate).
    assert edit.parse_semver("1.2.3") == (1, 2, 3)
    assert edit.parse_semver("1.2") is None
    assert edit.parse_semver("1.2.x") is None
    assert edit.parse_semver("v1.2.3") is None
    assert edit.semver_greater("1.0.1", "1.0.0") is True
    assert edit.semver_greater("1.0.0", "1.0.0") is False   # equal => refused
    assert edit.semver_greater("0.9.9", "1.0.0") is False   # lower => refused
    assert edit.semver_greater("2.0.0", "1.9.9") is True
    assert edit.suggest_bump("1.2.3", "patch") == "1.2.4"
    assert edit.suggest_bump("1.2.3", "minor") == "1.3.0"
    assert edit.suggest_bump("1.2.3", "major") == "2.0.0"
    assert edit.suggest_bump("garbage", "patch") == "1.0.1"


# --------------------------------------------------------------------------------------------------
# read job + patch guards
# --------------------------------------------------------------------------------------------------
def test_read_job_returns_editable_subset(tmp_path):
    _write_package(tmp_path / "surveys-live")
    result = edit._dispatch_edit(_cfg(tmp_path), {"kind": "read", "slug": "demo-survey-2026"},
                                 tmp_path / "gw" / "jobs" / "edit" / "scratch" / "t")
    assert result["ok"] is True
    assert result["version"] == "1.0.0"
    assert result["fields"]["region"] == "South Australia"
    assert result["fields"]["organisation"]["name"] == "University of Example"
    # The unknown key is NOT in the editable subset (the form never models it) but survives on disk.
    assert "custom_local_note" not in result["fields"]


def test_unknown_slug_and_bad_slug_refused(tmp_path):
    _write_package(tmp_path / "surveys-live")
    cfg = _cfg(tmp_path)
    scratch = cfg.jobs_dir / "edit" / "scratch" / "t"
    with pytest.raises(edit.EditError):
        edit._dispatch_edit(cfg, {"kind": "read", "slug": "no-such-survey"}, scratch)
    with pytest.raises(edit.EditError) as exc:
        edit._dispatch_edit(cfg, {"kind": "read", "slug": "../escape"}, scratch)
    assert "slug" in str(exc.value)


def test_non_editable_field_in_patch_refused(tmp_path):
    _write_package(tmp_path / "surveys-live")
    with pytest.raises(edit.EditError) as exc:
        _merge(_cfg(tmp_path), patch={"slug": "hijacked"})
    assert "non-editable" in str(exc.value)


# --------------------------------------------------------------------------------------------------
# the jobs/edit/ file queue (review FIX 1's transport)
# --------------------------------------------------------------------------------------------------
def test_claim_edit_job_atomic_lock(tmp_path):
    # Mirror of runner.claim_one: exactly one claim succeeds; the file moves pending -> running.
    dirs = edit.edit_dirs(tmp_path / "jobs")
    (dirs["pending"] / "j1.json").write_text(json.dumps({"kind": "read", "slug": "s"}),
                                             encoding="utf-8")
    first = edit.claim_edit_job(tmp_path / "jobs")
    second = edit.claim_edit_job(tmp_path / "jobs")
    assert first is not None and first.parent.name == "running"
    assert second is None


def test_process_edit_job_writes_done_result(tmp_path):
    # A claimed read job produces a done/<id>.json result and removes the running file — the file
    # protocol the gateway's default seam polls (FIX 1).
    _write_package(tmp_path / "surveys-live")
    cfg = _cfg(tmp_path)
    dirs = edit.edit_dirs(cfg.jobs_dir)
    (dirs["pending"] / "abc123.json").write_text(
        json.dumps({"kind": "read", "slug": "demo-survey-2026"}), encoding="utf-8")
    claimed = edit.claim_edit_job(cfg.jobs_dir)
    edit.process_edit_job(cfg, claimed)
    assert not claimed.exists()
    result = json.loads((dirs["done"] / "abc123.json").read_text(encoding="utf-8"))
    assert result["ok"] is True and result["version"] == "1.0.0"


def test_process_edit_job_never_raises(tmp_path):
    # Refusals AND unexpected garbage both land as {ok:False} result files — an edit job is
    # request/response, so a missing result would strand the polling gateway until timeout.
    _write_package(tmp_path / "surveys-live")
    cfg = _cfg(tmp_path)
    dirs = edit.edit_dirs(cfg.jobs_dir)
    # (a) a curator-facing refusal (no-op edit)
    (dirs["pending"] / "r1.json").write_text(json.dumps({
        "kind": "merge", "slug": "demo-survey-2026",
        "patch": {"region": "South Australia"}, "bump": "patch", "note": "n",
        "today": "2026-07-06"}), encoding="utf-8")
    edit.process_edit_job(cfg, edit.claim_edit_job(cfg.jobs_dir))
    r1 = json.loads((dirs["done"] / "r1.json").read_text(encoding="utf-8"))
    assert r1["ok"] is False and "no changes" in r1["error"]
    # (b) a malformed job file (not JSON) -> generic internal error, no exception
    (dirs["pending"] / "r2.json").write_text("not json", encoding="utf-8")
    edit.process_edit_job(cfg, edit.claim_edit_job(cfg.jobs_dir))
    r2 = json.loads((dirs["done"] / "r2.json").read_text(encoding="utf-8"))
    assert r2["ok"] is False and "internal error" in r2["error"]


# --------------------------------------------------------------------------------------------------
# real-validator integration (the shipped validate_survey.py, run over the scratch copy)
# --------------------------------------------------------------------------------------------------
_VALID_PACKAGE_YAML = """\
schema_version: "0.2"
slug: intg-survey-2026
project_name: Integration Survey      # keep this comment
version: 1.0.0
country: Australia
region: South Australia
organisation:
  name: University of Example
license: CC-BY-4.0
access:
  level: open
  embargo_until: null
custom_note: "unknown key survives"
"""

# C35b/D3 (review F7): resolve the validator UNCONDITIONALLY — sibling if present, else the committed
# vendored pinned copy; require_validator_dir() FAILS (never skips) if neither is present.
from gateway.tests.conftest import require_validator_dir  # noqa: E402


def test_merge_runs_the_real_validator(tmp_path):
    # Integration: run the merge with the REAL validate_survey.py (no override). Proves the actual
    # `validate_survey.py --json <file>` invocation + report interpretation work end-to-end over the
    # scratch copy. FAILS IF the invocation shape regresses (e.g. reading stdout instead of the
    # --json file) or the scratch plumbing breaks.
    surveys_live = tmp_path / "surveys-live"
    pkg = _write_package(surveys_live, slug="intg-survey-2026", yaml_text=_VALID_PACKAGE_YAML)
    (pkg / "README.md").write_text("# Integration Survey\n", encoding="utf-8")
    (pkg / "LICENSE.md").write_text("CC-BY-4.0\n", encoding="utf-8")
    (pkg / "transfer_functions" / "edi" / "S01.edi").write_text(
        ">HEAD\n  LAT=-30:08:45.2\n  LONG=136:58:12.0\n>END\n>FREQ ORDER=INC //1\n  1.0\n",
        encoding="utf-8")
    cfg = _cfg(tmp_path, validator_path=str(require_validator_dir()))
    result = _merge(cfg, slug="intg-survey-2026")
    assert result["ok"] is True
    assert isinstance(result["validator"].get("items"), list)
    assert len(result["validator"]["items"]) > 0
    assert result["has_fail"] is False, result["validator"]
    assert "# keep this comment" in result["new_yaml"]
    assert 'custom_note: "unknown key survives"' in result["new_yaml"]
    # And the surveys tree is untouched (FIX 2, against the real validator this time).
    assert not list(surveys_live.rglob("_edit_*"))


def test_merge_real_validator_flags_fail(tmp_path):
    # The real validator FAILs an out-of-enum access.level (a required, enumerated field), and the
    # merge reports has_fail=True — the signal the gateway turns into a confirm 409 (§0.4).
    # C35b/D3 (review F7): UNCONDITIONAL — sibling-or-vendored, FAILS if neither present.
    pkg = _write_package(tmp_path / "surveys-live", slug="intg-survey-2026",
                         yaml_text=_VALID_PACKAGE_YAML)
    (pkg / "transfer_functions" / "edi" / "S01.edi").write_text(
        ">HEAD\n  LAT=-30:08:45.2\n  LONG=136:58:12.0\n>END\n>FREQ ORDER=INC //1\n  1.0\n",
        encoding="utf-8")
    cfg = _cfg(tmp_path, validator_path=str(require_validator_dir()))
    result = _merge(cfg, slug="intg-survey-2026",
                    patch={"access": {"level": "nonsense", "embargo_until": None}},
                    note="bad level")
    assert result["ok"] is True
    assert result["has_fail"] is True
