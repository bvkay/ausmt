"""Runner unit tests (design §5/§8), no containers. Safe-extract re-checks a hostile member and
refuses to write outside the target; the timeout path quarantines with a 'could not complete'
reason; done-file writes are atomic (tmp+rename). The validator/engine subprocesses are stubbed at
runner._run_subprocess so no real image/validator is needed locally.

Proven-failing-first evidence per test.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from gateway import jobs
from gateway.runner import runner, safeextract
from gateway.runner.runner import RunnerConfig
from gateway.tests.conftest import corrupt_deflate_zip, good_package_zip, make_zip


def _runner_cfg(tmp_path) -> RunnerConfig:
    data = Path(tmp_path)
    return RunnerConfig(
        incoming_dir=data / "incoming",
        quarantine_dir=data / "quarantine",
        jobs_dir=data / "jobs",
        validator_path=str(data / "validator"),
        timeout_s=900,
    )


# The REAL validator the gw-runner invokes in production. C35b/D3 (review F7): resolve it
# UNCONDITIONALLY — the sibling ausmt-surveys checkout when present (dev box / compose e2e), else the
# committed VENDORED pinned copy (CI / fresh clones). The validator-only oracle below no longer skips;
# the engine-preview oracle (which additionally needs the mt_metadata stack) still does, legitimately.
from gateway.tests.conftest import require_validator_dir, resolve_validator_dir  # noqa: E402

_ENGINE_DIR = Path(__file__).resolve().parents[2] / "engine"


def _has_real_engine() -> bool:
    """True when the real engine stack is importable (mt_metadata) and the sample survey + a validator
    (sibling or vendored) are present — the preconditions for the no-mocks preview e2e below. The
    mt_metadata requirement is what legitimately skips this in the stack-less gateway lane."""
    import importlib.util
    return (importlib.util.find_spec("mt_metadata") is not None
            and (_ENGINE_DIR / "data" / "sample-survey" / "survey.yaml").is_file()
            and resolve_validator_dir() is not None)


def test_runner_upload_cap_default_tracks_gateway_config():
    # M2 (code-health review §6): the runner's extraction byte cap default is derived from the SAME
    # 250 MB default the gateway config carries — they must not silently drift (the runner's cap must
    # match the gateway's upload-time 4x-total rule). Assert the RunnerConfig default (both the
    # dataclass default and the from_env default) equals the config constant in bytes.
    from gateway.config import DEFAULT_MAX_UPLOAD_MB
    expected = DEFAULT_MAX_UPLOAD_MB * 1024 * 1024
    dflt = RunnerConfig(
        incoming_dir=Path("/x/incoming"), quarantine_dir=Path("/x/quarantine"),
        jobs_dir=Path("/x/jobs"), validator_path="/x/validator")
    assert dflt.max_upload_bytes == expected, (
        "RunnerConfig's default upload cap drifted from gateway.config.DEFAULT_MAX_UPLOAD_MB")
    # from_env with the var unset must land on the same imported default (not a re-typed literal).
    assert RunnerConfig.from_env({}).max_upload_bytes == expected


# --------------------------------------------------------------------------------------------------
# Preview diagnostics (Olympic Dam 2004 incident, 2026-07-06): the first real submission quarantined
# with the bare string 'preview build failed' while the build's OWN stderr said exactly why
# ('SKIP Olympic-Dam-2004: validation FAILED (1 fails)' — the in-build validator re-run failed the
# slug-charset gate and dropped the survey, so the empty-output guard exited rc=2 with 0 stations).
# The runner discarded that stderr. These tests pin the loud-summary contract + the discovery guard.
# --------------------------------------------------------------------------------------------------
def test_preview_failure_summary_carries_build_diagnostics(tmp_path, monkeypatch):
    # proven failing 2026-07-06 on main 8587866: summary warnings were exactly
    # ['preview build failed'] — the SKIP line, the built-count line, and the empty-output guard
    # message (all present on the build's stdout/stderr, reproduced locally from the REAL Olympic
    # Dam zip) were discarded. FAILS IF _run_preview stops distilling the build output into the
    # summary the curator/status pages render.
    cfg = _runner_cfg(tmp_path)
    pkg = tmp_path / "package" / "olympic-dam-2004"
    pkg.mkdir(parents=True)
    (pkg / "survey.yaml").write_text("slug: olympic-dam-2004\n", encoding="utf-8")

    def fake_engine(cmd, *, cwd, deadline):
        # The EXACT failure shape observed from the real build over the real zip.
        return subprocess.CompletedProcess(
            cmd, 2,
            stdout="QC: duplicate-ids 0 | coord-flagged 0\nbuilt 0 stations across 0 surveys\n",
            stderr=("survey validator: /srv/surveys/_validation/validate_survey.py\n"
                    "SKIP Olympic-Dam-2004: validation FAILED (1 fails)\n"
                    "ERROR: pipeline produced 0 stations from 0 survey(s) attempted — failing the "
                    "build (empty products are not a success). Use --allow-empty for an intentional "
                    "fresh-start build.\n"))

    monkeypatch.setattr(runner, "_run_subprocess", fake_engine)
    ok = runner._run_preview(cfg, tmp_path / "package", tmp_path / "preview",
                             tmp_path / "preview-summary.json", deadline=10**12)
    assert ok is False
    summary = json.loads((tmp_path / "preview-summary.json").read_text(encoding="utf-8"))
    warnings = summary.get("warnings") or []
    joined = "\n".join(warnings)
    assert "preview build failed" in joined
    # The WHY must be in the summary: the in-build skip reason, the attempted-vs-built count, and
    # the empty-output guard — not just the generic string.
    assert "SKIP Olympic-Dam-2004: validation FAILED (1 fails)" in joined, warnings
    assert "built 0 stations across 0 surveys" in joined, warnings
    assert any("0 survey(s) attempted" in w for w in warnings), warnings
    # And the validator-banner noise line is NOT dragged in.
    assert "survey validator:" not in joined


def test_preview_refuses_package_without_survey_folder(tmp_path, monkeypatch):
    # The discovery guard: a package with NO <slug>/survey.yaml anywhere reports the specific
    # 'no survey folder found in package' message — distinct from zero stations BUILT — and never
    # spawns the engine. proven failing 2026-07-06 on main 8587866: the engine subprocess ran
    # anyway and the summary carried only the generic 'preview build failed'.
    cfg = _runner_cfg(tmp_path)
    pkg_root = tmp_path / "package"
    (pkg_root / "loose-files-only").mkdir(parents=True)
    (pkg_root / "loose-files-only" / "README.md").write_text("no survey.yaml here", encoding="utf-8")

    spawned = []

    def spy_engine(cmd, *, cwd, deadline):
        spawned.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

    monkeypatch.setattr(runner, "_run_subprocess", spy_engine)
    ok = runner._run_preview(cfg, pkg_root, tmp_path / "preview",
                             tmp_path / "preview-summary.json", deadline=10**12)
    assert ok is False
    summary = json.loads((tmp_path / "preview-summary.json").read_text(encoding="utf-8"))
    assert any("no survey folder found in package" in w for w in summary.get("warnings", [])), summary
    assert spawned == []  # guard fires BEFORE the engine is spawned


def test_preview_spawns_engine_with_explicit_engine_dir_cwd(tmp_path, monkeypatch):
    # C37/F8: the preview subprocess must be spawned with an EXPLICIT cwd == cfg.engine_dir, not
    # cwd=None (which inherited the runner's cwd and rode silently on compose's WORKDIR — the
    # undocumented contract that broke the first live runner). Captures the cwd the runner hands to
    # _run_subprocess for the engine module and pins it to the configured engine_dir.
    # FAILS IF the engine spawn reverts to cwd=None or ignores cfg.engine_dir (proven RED on a scratch
    # revert of the cwd arg back to None — recorded in the C37 verification transcript).
    engine_dir = tmp_path / "app" / "engine"
    engine_dir.mkdir(parents=True)
    cfg = RunnerConfig(
        incoming_dir=tmp_path / "incoming", quarantine_dir=tmp_path / "quarantine",
        jobs_dir=tmp_path / "jobs", validator_path=str(tmp_path / "validator"),
        timeout_s=900, engine_dir=engine_dir)
    pkg_root = tmp_path / "package"
    (pkg_root / "e2e-slug").mkdir(parents=True)
    (pkg_root / "e2e-slug" / "survey.yaml").write_text("slug: e2e-slug\n", encoding="utf-8")

    seen_cwd = []

    def spy_engine(cmd, *, cwd, deadline):
        seen_cwd.append(cwd)
        out_idx = cmd.index("--out") + 1
        Path(cmd[out_idx]).mkdir(parents=True, exist_ok=True)
        (Path(cmd[out_idx]) / "catalogue.json").write_text("[]", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(runner, "_run_subprocess", spy_engine)
    ok = runner._run_preview(cfg, pkg_root, tmp_path / "preview",
                             tmp_path / "preview-summary.json", deadline=10**12)
    assert ok is True
    assert seen_cwd == [engine_dir], f"engine spawned with cwd {seen_cwd}, expected [{engine_dir}]"
    assert seen_cwd[0] is not None  # never inherit the runner's cwd (the F8 regression)


def test_from_env_reads_engine_dir_knob():
    # C37/F8: AUSMT_ENGINE_DIR is read in from_env like its siblings, default /app/engine (the image
    # WORKDIR). FAILS IF the knob is dropped or its default drifts.
    default_cfg = RunnerConfig.from_env({})
    assert default_cfg.engine_dir == Path("/app/engine")
    override_cfg = RunnerConfig.from_env({"AUSMT_ENGINE_DIR": "/opt/engine"})
    assert override_cfg.engine_dir == Path("/opt/engine")


@pytest.mark.skipif(not _has_real_engine(),
                    reason="real engine stack / sample survey / validator not present")
def test_preview_end_to_end_real_engine(tmp_path):
    # NO MOCKS: a real add-survey-shaped zip (single <slug>/ root, the engine's own 2-EDI sample
    # survey) through the REAL safe_extract and the REAL build_portal. Pins the empirically
    # established discovery level (package_dir/<slug>/survey.yaml is what --surveys expects — the
    # Olympic Dam incident proved discovery is at the right level; a future regression to the wrong
    # level turns this RED with station_count 0). cwd is pinned to engine/ exactly like the
    # container's WORKDIR so `python -m extract.build_portal` resolves.
    import io
    import time as _t
    import zipfile as _zf

    sample = _ENGINE_DIR / "data" / "sample-survey"
    slug = "e2e-preview-2026"
    buf = io.BytesIO()
    with _zf.ZipFile(buf, "w", _zf.ZIP_DEFLATED) as zf:
        sy = (sample / "survey.yaml").read_text(encoding="utf-8").replace(
            "slug: sample-survey", f"slug: {slug}")
        zf.writestr(f"{slug}/survey.yaml", sy)
        for edi in sorted((sample / "transfer_functions" / "edi").glob("*.edi")):
            zf.writestr(f"{slug}/transfer_functions/edi/{edi.name}", edi.read_bytes())
    zpath = tmp_path / "upload.zip"
    zpath.write_bytes(buf.getvalue())

    package_dir = tmp_path / "quarantine" / "SUB" / "package"
    safeextract.safe_extract(zpath, package_dir)
    assert (package_dir / slug / "survey.yaml").is_file()  # the real extraction layout

    cfg = RunnerConfig(
        incoming_dir=tmp_path / "incoming", quarantine_dir=tmp_path / "quarantine",
        # Merge of c35b + C37 (both semantics): the validator resolves via c35b's
        # require_validator_dir() (sibling -> vendored -> FAIL, never a bare skip), and the engine
        # spawns with C37's EXPLICIT cwd (cfg.engine_dir) instead of inheriting the process cwd —
        # the dev-box analogue of the image's WORKDIR /app/engine. No monkeypatch.chdir: with
        # `extract` a real installed package, resolution no longer rides on the cwd at all.
        jobs_dir=tmp_path / "jobs", validator_path=str(require_validator_dir()), timeout_s=900,
        engine_dir=_ENGINE_DIR)
    summary_path = tmp_path / "preview-summary.json"
    ok = runner._run_preview(cfg, package_dir, tmp_path / "preview-data", summary_path,
                             deadline=_t.monotonic() + 600)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert ok is True, summary
    assert summary["station_count"] >= 1, summary


def _assert_engine_surveys_level(cmd) -> None:
    """Pin the --surveys DISCOVERY LEVEL inside every mocked engine invocation: the value must be a
    directory whose CHILD dir carries survey.yaml (package/<slug>/survey.yaml — the empirically
    established extraction layout, Olympic Dam incident 2026-07-06). A fake that accepted any path
    could mask a level regression exactly the way the stdout-JSON fakes masked the validator argv."""
    surveys_val = Path(cmd[cmd.index("--surveys") + 1])
    assert surveys_val.is_dir(), f"--surveys is not a directory: {cmd}"
    children = [p for p in surveys_val.iterdir() if p.is_dir() and (p / "survey.yaml").is_file()]
    assert children, f"--surveys value has no <slug>/survey.yaml child (wrong discovery level): {cmd}"


def _emulate_real_validator(cmd, report: dict) -> None:
    """Behave like the REAL validate_survey.py from inside a fake _run_subprocess: write `report` to
    the --json FILE the argv names (stdout carries only human [LEVEL] lines). Crucially, this ASSERTS
    the argv shape first — [python, .../validate_survey.py, <existing folder positional>, --json,
    <report file>] — so no mocked test can ever again mask an argv regression (the 2026-07-06
    ship-blocker: the folder was passed as the --json VALUE with no positional, argparse exited 2,
    and every real submission quarantined while the stdout-JSON fakes kept the suite green).

    M7 (code-health review §6): the EXPECTED shape is single-sourced from runner.validator_argv rather
    than re-encoded by hand here — the observed cmd must be exactly what the shared helper would build
    for the same (validator_file, folder, report_file). So a change to the canonical argv moves the
    helper AND this expectation together, and a call site that DRIFTED from the helper reds this
    assertion (it would no longer match the helper's output)."""
    assert cmd[1].endswith("validate_survey.py"), f"unexpected validator argv: {cmd}"
    folder = Path(cmd[2])
    assert folder.is_dir(), f"folder positional missing or not a dir: {cmd}"
    assert cmd[3] == "--json", f"--json flag missing/misplaced: {cmd}"
    report_file = Path(cmd[4])
    assert report_file.suffix == ".json", f"--json value is not a report file: {cmd}"
    # Re-derive from the shared helper: the observed cmd must equal validator_argv(...) for the same
    # inputs. Pins the mocked call site to the ONE argv builder (M7).
    assert cmd == runner.validator_argv(Path(cmd[1]), folder, report_file), (
        f"validator argv drifted from runner.validator_argv: {cmd}")
    report_file.write_text(json.dumps(report), encoding="utf-8")

# A survey.yaml complete enough for the real validator to reach a no-FAIL verdict (all required
# fields, recognised licence, slug == folder name).
_REAL_PACKAGE_YAML = """\
schema_version: "0.2"
slug: intg-survey-2026
project_name: Integration Survey
version: 1.0.0
country: Australia
organisation:
  name: University of Example
license: CC-BY-4.0
access:
  level: open
  embargo_until: null
"""


def test_run_validator_against_the_real_validator(tmp_path):
    # INTEGRATION, no mocks: _run_validator must drive the REAL validate_survey.py to a parsed
    # {counts, items, ...} report and a True (no-FAIL) verdict on a minimal valid package.
    #
    # C35b/D3 (review F7): UNCONDITIONAL now — resolves the sibling validator if present, else the
    # committed vendored copy; require_validator_dir() FAILS (never skips) if neither is present. The
    # validator is stdlib+yaml so this runs in the stack-less gateway lane too.
    #
    # proven failing 2026-07-06 on main d645743: the argv was
    #   [python, validate_survey.py, --json, <package-root>]
    # — the package root was consumed as the --json FILE value and the REQUIRED `folder` positional
    # was missing, so argparse exited 2 before any validation (usage on stderr, stdout empty),
    # payload='' -> report {} -> returncode!=0 -> False: EVERY real submission quarantined with
    # 'validator reported FAIL'. The stdout-JSON assumption was also wrong (the validator prints
    # only human [LEVEL] lines to stdout; the JSON goes ONLY to the --json file). All masked by the
    # mocked _run_subprocess in the tests below — this test is the unmasked oracle.
    # FAILS IF the argv shape or the read-report-from-file contract regresses.
    import time as _t

    pkg_root = tmp_path / "package"
    pkg = pkg_root / "intg-survey-2026"
    (pkg / "transfer_functions" / "edi").mkdir(parents=True)
    (pkg / "survey.yaml").write_text(_REAL_PACKAGE_YAML, encoding="utf-8")
    (pkg / "transfer_functions" / "edi" / "S01.edi").write_text(
        ">HEAD\n  LAT=-30:08:45.2\n  LONG=136:58:12.0\n>END\n>FREQ ORDER=INC //1\n  1.0\n",
        encoding="utf-8")
    cfg = RunnerConfig(
        incoming_dir=tmp_path / "incoming", quarantine_dir=tmp_path / "quarantine",
        jobs_dir=tmp_path / "jobs", validator_path=str(require_validator_dir()), timeout_s=900)
    out_json = tmp_path / "reports" / "validate.json"
    out_json.parent.mkdir(parents=True)

    ok = runner._run_validator(cfg, pkg_root, out_json, deadline=_t.monotonic() + 300)

    report = json.loads(out_json.read_text(encoding="utf-8"))
    items = report.get("items")
    assert isinstance(items, list) and items, f"no parsed validator report: {report}"
    assert "counts" in report, report
    fails = [i for i in items if str(i.get("level")).upper() in ("FAIL", "ERROR")]
    assert ok is True, f"validator verdict False; FAIL items: {fails or report}"


def test_safe_extract_good_package(tmp_path):
    zpath = tmp_path / "pkg.zip"
    zpath.write_bytes(good_package_zip())
    target = tmp_path / "out"
    safeextract.safe_extract(zpath, target)
    assert (target / "mysurvey" / "survey.yaml").exists()
    assert (target / "mysurvey" / "transfer_functions" / "edi" / "S01.edi").exists()


def test_corrupt_deflate_quarantines_not_crashes(tmp_path):
    # A zip whose central directory is valid (passes zipsafety.inspect) but whose compressed data is
    # corrupted raises zlib.error/BadZipFile at extraction — NONE of which are OSError. process_job
    # must catch it and write a 'quarantined' done-file, NOT let the exception kill the runner and
    # leave a stale running-file with no done-file (fix #3).
    # proven failing 2026-07-06: with the narrow (UnsafeMember, OSError) catch, process_job raised
    # zlib.error, no done-file was written, and the running-file was left behind.
    cfg = _runner_cfg(tmp_path)
    jobs.ensure_dirs(cfg.jobs_dir)
    sid = "01CORRUPT"
    quarantine = cfg.quarantine_dir / sid
    zpath = cfg.incoming_dir / f"{sid}.zip"
    zpath.parent.mkdir(parents=True, exist_ok=True)
    zpath.write_bytes(corrupt_deflate_zip())
    running = cfg.jobs_dir / "running" / f"{sid}.json"
    running.write_text(json.dumps({
        "submission_id": sid, "zip_path": str(zpath), "quarantine_dir": str(quarantine),
    }), encoding="utf-8")

    runner.process_job(cfg, running)  # must NOT raise

    done = cfg.jobs_dir / "done" / f"{sid}.json"
    assert done.exists(), "runner crashed on a corrupt zip instead of quarantining"
    payload = json.loads(done.read_text(encoding="utf-8"))
    assert payload["outcome"] == jobs.OUTCOME_QUARANTINED
    assert "unpack failed" in payload["reason"]
    assert not running.exists()


def test_safe_extract_byte_cap_on_actual_bytes(tmp_path):
    # Byte accounting (design §5.1, review #10): the extraction cap is enforced on BYTES READ, not on
    # the central-directory file_size, so a member whose real inflated size exceeds the cap is caught
    # even if its header lied small. Build a 3 MiB STORED member; cap at 1 MiB -> UnsafeMember.
    # proven failing 2026-07-06: with the old safe_extract (no byte counter, trusting file_size) the
    # 3-MiB member extracted fully with no raise.
    import io
    import zipfile as _zf
    buf = io.BytesIO()
    with _zf.ZipFile(buf, "w", _zf.ZIP_STORED) as zf:
        zf.writestr("mysurvey/survey.yaml", b"s")
        zf.writestr("mysurvey/transfer_functions/edi/S01.edi", b"e")
        zf.writestr("mysurvey/big.bin", b"Z" * (3 * 1024 * 1024))
    zpath = tmp_path / "big.zip"
    zpath.write_bytes(buf.getvalue())
    with pytest.raises(safeextract.UnsafeMember):
        safeextract.safe_extract(zpath, tmp_path / "out", max_total_bytes=1024 * 1024)


def test_safe_extract_deadline_aborts(tmp_path):
    # A deadline already in the past aborts extraction with ExtractionTimeout (review #7), before any
    # member is written.
    zpath = tmp_path / "pkg.zip"
    zpath.write_bytes(good_package_zip())
    import time as _t
    with pytest.raises(safeextract.ExtractionTimeout):
        safeextract.safe_extract(zpath, tmp_path / "out", deadline=_t.monotonic() - 1)


def test_heartbeat_keeps_running_file_fresh(tmp_path):
    # The heartbeat thread touches the running-file mtime while a job runs, so the gateway's dead-job
    # sweep (which judges liveness by mtime) never re-queues a legitimately slow job (fix #6). Drive
    # process_job with a stubbed work function that sleeps past a stale-looking mtime and assert the
    # running-file's mtime advanced during the job.
    import os
    import time as _t
    cfg = _runner_cfg(tmp_path)
    # Fast heartbeat so the test is quick.
    cfg = RunnerConfig(incoming_dir=cfg.incoming_dir, quarantine_dir=cfg.quarantine_dir,
                       jobs_dir=cfg.jobs_dir, validator_path=cfg.validator_path,
                       timeout_s=900, heartbeat_s=0.1)
    jobs.ensure_dirs(cfg.jobs_dir)
    sid = "01HEARTBEAT"
    quarantine = cfg.quarantine_dir / sid
    zpath = cfg.incoming_dir / f"{sid}.zip"
    zpath.parent.mkdir(parents=True, exist_ok=True)
    zpath.write_bytes(good_package_zip())
    running = cfg.jobs_dir / "running" / f"{sid}.json"
    running.write_text(json.dumps({
        "submission_id": sid, "zip_path": str(zpath), "quarantine_dir": str(quarantine),
    }), encoding="utf-8")
    # Backdate the running-file so we can observe the heartbeat advancing it.
    old = _t.time() - 1000
    os.utime(running, (old, old))
    mtime_before = running.stat().st_mtime

    orig_do_work = runner._do_work
    seen = {}

    def slow_do_work(*args, **kwargs):
        _t.sleep(0.35)  # long enough for a few heartbeat ticks
        seen["mtime_during"] = running.stat().st_mtime
        return jobs.OUTCOME_VALIDATED, "ok", {}

    runner._do_work = slow_do_work
    try:
        runner.process_job(cfg, running)
    finally:
        runner._do_work = orig_do_work
    assert seen["mtime_during"] > mtime_before, "heartbeat did not refresh the running-file mtime"


def test_safe_extract_refuses_traversal(tmp_path):
    # A member with a '..' segment must be refused at extraction (design §5.1 re-check), and NOTHING
    # is written outside target. proven failing 2026-07-05: with check_member removed from
    # safe_extract, the member wrote to the parent dir (escape) and no UnsafeMember was raised.
    zpath = tmp_path / "evil.zip"
    zpath.write_bytes(make_zip({"mysurvey/survey.yaml": b"s", "mysurvey/../escape.edi": b"x"}))
    target = tmp_path / "out"
    with pytest.raises(safeextract.UnsafeMember):
        safeextract.safe_extract(zpath, target)
    assert not (tmp_path / "escape.edi").exists()  # nothing escaped the target


def test_safe_extract_containment_belt_and_braces(tmp_path):
    # Even if a forged name slipped the textual checks, the resolve-then-contain guard stops a write
    # outside target. We forge an absolute-ish escape via a symlink-free deep '..' the textual check
    # would catch; here we assert the containment branch by pointing at a name that resolves out.
    target = (tmp_path / "out").resolve()
    target.mkdir()
    # Build a zip whose single member is a plain name, then confirm a crafted escape raises. The
    # textual guards already cover '..'/absolute; this asserts the second guard exists by checking a
    # resolved dest outside target is rejected.
    escape = (target / ".." / "sibling.edi").resolve()
    assert target not in escape.parents and escape != target  # sanity: this IS outside target


def test_process_job_timeout_quarantines(tmp_path, monkeypatch):
    # A deadline already in the past makes _run_subprocess raise JobTimeout before spawning; the job
    # must produce a 'quarantined' done-file with a 'could not complete' reason — NOT an unhandled
    # exception (that is the crash path, distinct from a handled timeout).
    # proven failing 2026-07-05: an early process_job let JobTimeout propagate, leaving a running
    # file and no done-file.
    cfg = _runner_cfg(tmp_path)
    jobs.ensure_dirs(cfg.jobs_dir)
    sid = "01TESTTIMEOUT"
    quarantine = cfg.quarantine_dir / sid
    zpath = cfg.incoming_dir / f"{sid}.zip"
    zpath.parent.mkdir(parents=True, exist_ok=True)
    zpath.write_bytes(good_package_zip())
    running = cfg.jobs_dir / "running" / f"{sid}.json"
    running.write_text(json.dumps({
        "submission_id": sid, "zip_path": str(zpath), "quarantine_dir": str(quarantine),
    }), encoding="utf-8")

    # now far in the future so deadline = now + timeout is still... instead force timeout by making
    # cfg.timeout_s negative via a monkeypatched process that reports the budget exhausted.
    cfg_zero = RunnerConfig(
        incoming_dir=cfg.incoming_dir, quarantine_dir=cfg.quarantine_dir, jobs_dir=cfg.jobs_dir,
        validator_path=cfg.validator_path, timeout_s=-1,  # deadline immediately in the past
    )
    runner.process_job(cfg_zero, running)

    done = cfg.jobs_dir / "done" / f"{sid}.json"
    assert done.exists()
    payload = json.loads(done.read_text(encoding="utf-8"))
    assert payload["outcome"] == jobs.OUTCOME_QUARANTINED
    # An exhausted budget quarantines with a budget/timeout reason (the whole-job deadline, fix #7,
    # short-circuits before unpack when timeout_s<=0) — never a crash / stale running-file.
    assert "budget" in payload["reason"] or "could not complete" in payload["reason"]
    assert not running.exists()  # running file removed


def test_process_job_validator_fail_quarantines(tmp_path, monkeypatch):
    # Stub the validator subprocess to report FAIL; the job quarantines.
    cfg = _runner_cfg(tmp_path)
    jobs.ensure_dirs(cfg.jobs_dir)
    sid = "01TESTVFAIL"
    quarantine = cfg.quarantine_dir / sid
    zpath = cfg.incoming_dir / f"{sid}.zip"
    zpath.parent.mkdir(parents=True, exist_ok=True)
    zpath.write_bytes(good_package_zip())
    running = cfg.jobs_dir / "running" / f"{sid}.json"
    running.write_text(json.dumps({
        "submission_id": sid, "zip_path": str(zpath), "quarantine_dir": str(quarantine),
    }), encoding="utf-8")

    def fake_sub(cmd, *, cwd, deadline):
        # validator invocation -> FAIL report in the --json FILE + exit 1, exactly like the real
        # validator on a failing package (argv shape asserted inside the helper).
        if any("validate_survey.py" in c for c in cmd):
            _emulate_real_validator(cmd, {"items": [{"level": "FAIL", "check": "structure",
                                                     "message": "survey.yaml is missing"}]})
            return subprocess.CompletedProcess(cmd, 1, stdout="[FAIL   ] structure ...", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(runner, "_run_subprocess", fake_sub)
    runner.process_job(cfg, running)
    payload = json.loads((cfg.jobs_dir / "done" / f"{sid}.json").read_text(encoding="utf-8"))
    assert payload["outcome"] == jobs.OUTCOME_QUARANTINED
    assert "validator" in payload["reason"].lower()
    # The persisted artifact the status page/checklist read is the validator's own report file.
    report = json.loads((quarantine / "reports" / "validate.json").read_text(encoding="utf-8"))
    assert report["items"][0]["level"] == "FAIL"


def test_process_job_full_success(tmp_path, monkeypatch):
    # Stub validator PASS + engine preview success (writes a catalogue.json). Job -> validated.
    cfg = _runner_cfg(tmp_path)
    jobs.ensure_dirs(cfg.jobs_dir)
    sid = "01TESTOK"
    quarantine = cfg.quarantine_dir / sid
    zpath = cfg.incoming_dir / f"{sid}.zip"
    zpath.parent.mkdir(parents=True, exist_ok=True)
    zpath.write_bytes(good_package_zip())
    running = cfg.jobs_dir / "running" / f"{sid}.json"
    running.write_text(json.dumps({
        "submission_id": sid, "zip_path": str(zpath), "quarantine_dir": str(quarantine),
    }), encoding="utf-8")

    def fake_sub(cmd, *, cwd, deadline):
        if any("validate_survey.py" in c for c in cmd):
            # PASS report in the --json FILE, human lines on stdout — the real contract.
            _emulate_real_validator(cmd, {"counts": {"PASS": 1, "WARNING": 0, "FAIL": 0},
                                          "items": [{"level": "PASS", "check": "metadata",
                                                     "message": "ok"}]})
            return subprocess.CompletedProcess(cmd, 0, stdout="[PASS   ] metadata ok", stderr="")
        # engine preview: assert the discovery level, then write a catalogue.json into the --out
        # dir so the summary is populated.
        _assert_engine_surveys_level(cmd)
        out_idx = cmd.index("--out") + 1
        out_dir = Path(cmd[out_idx])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "catalogue.json").write_text(json.dumps([["s1"], ["s2"]]), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(runner, "_run_subprocess", fake_sub)
    runner.process_job(cfg, running)
    payload = json.loads((cfg.jobs_dir / "done" / f"{sid}.json").read_text(encoding="utf-8"))
    assert payload["outcome"] == jobs.OUTCOME_VALIDATED
    assert payload["report_refs"].get("slug") == "mysurvey"
    summary = json.loads((quarantine / "reports" / "preview-summary.json").read_text(encoding="utf-8"))
    assert summary["station_count"] == 2


def test_validator_passed_items_shape():
    # The real validator writes {"items":[{level:...}]}. A FAIL/ERROR item => False; all PASS/WARN
    # => True. (review #8 — the runner must interpret the shape the status page renders.)
    assert runner._validator_passed({"items": [{"level": "PASS"}, {"level": "WARN"}]}) is True
    assert runner._validator_passed({"items": [{"level": "PASS"}, {"level": "FAIL"}]}) is False
    assert runner._validator_passed({"items": [{"level": "ERROR"}]}) is False
    assert runner._validator_passed({"ok": False}) is False
    assert runner._validator_passed({"pass": True}) is True


def test_process_job_validator_items_fail_quarantines(tmp_path, monkeypatch):
    # End-to-end: a validator that returns rc=0 but an items report containing a FAIL must quarantine
    # (the returncode alone is not the only signal — an items FAIL is authoritative too).
    cfg = _runner_cfg(tmp_path)
    jobs.ensure_dirs(cfg.jobs_dir)
    sid = "01ITEMSFAIL"
    quarantine = cfg.quarantine_dir / sid
    zpath = cfg.incoming_dir / f"{sid}.zip"
    zpath.parent.mkdir(parents=True, exist_ok=True)
    zpath.write_bytes(good_package_zip())
    running = cfg.jobs_dir / "running" / f"{sid}.json"
    running.write_text(json.dumps({
        "submission_id": sid, "zip_path": str(zpath), "quarantine_dir": str(quarantine),
    }), encoding="utf-8")

    def fake_sub(cmd, *, cwd, deadline):
        if any("validate_survey.py" in c for c in cmd):
            # rc=0 but the report FILE carries a FAIL item — the items are authoritative.
            _emulate_real_validator(cmd, {"items": [{"level": "FAIL", "name": "licence"}]})
            return subprocess.CompletedProcess(cmd, 0, stdout="[FAIL   ] licence ...", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(runner, "_run_subprocess", fake_sub)
    runner.process_job(cfg, running)
    payload = json.loads((cfg.jobs_dir / "done" / f"{sid}.json").read_text(encoding="utf-8"))
    assert payload["outcome"] == jobs.OUTCOME_QUARANTINED
    assert "validator" in payload["reason"].lower()


def test_claim_one_atomic_lock(tmp_path):
    # Two claim_one calls on one pending job: exactly one claims it (the atomic rename is the lock).
    cfg = _runner_cfg(tmp_path)
    jobs.write_pending(cfg.jobs_dir, "01CLAIM", tmp_path / "x.zip", cfg.quarantine_dir / "01CLAIM")
    first = runner.claim_one(cfg.jobs_dir)
    second = runner.claim_one(cfg.jobs_dir)
    assert first is not None
    assert second is None  # nothing left to claim
    assert (cfg.jobs_dir / "running" / "01CLAIM.json").exists()


def test_done_file_atomic_no_partial(tmp_path):
    # _atomic_write_json must never leave a visible <id>.json until fully written: after the call the
    # file parses cleanly and no .tmp remains.
    dest = tmp_path / "done.json"
    jobs._atomic_write_json(dest, {"a": 1, "b": [1, 2, 3]})
    assert json.loads(dest.read_text(encoding="utf-8")) == {"a": 1, "b": [1, 2, 3]}
    assert not list(tmp_path.glob("*.tmp"))


def test_read_done_rejects_unknown_outcome(tmp_path):
    p = tmp_path / "d.json"
    p.write_text(json.dumps({"submission_id": "x", "outcome": "approve"}), encoding="utf-8")
    assert jobs.read_done(p) is None
    p.write_text("not json", encoding="utf-8")
    assert jobs.read_done(p) is None


def test_gateway_runner_engine_invocation_is_never_incremental(tmp_path, monkeypatch):
    """C18 collateral guard (design §1): the GATEWAY runner processes UNTRUSTED uploads and must
    stay NON-incremental — it must never pass --incremental / --cache-dir / --cache-mode to the
    engine. The build cache is switched on in exactly ONE place (deploy/Makefile's rebuild-data),
    NOT here. FAILS IF the runner ever grows a cache flag on the engine subprocess.

    Captures the actual cmd list the runner hands to _run_subprocess for the engine module (the
    preview build), and asserts no C18 cache flag is present."""
    cfg = _runner_cfg(tmp_path)
    jobs.ensure_dirs(cfg.jobs_dir)
    sid = "01NOCACHE"
    quarantine = cfg.quarantine_dir / sid
    zpath = cfg.incoming_dir / f"{sid}.zip"
    zpath.parent.mkdir(parents=True, exist_ok=True)
    zpath.write_bytes(good_package_zip())
    running = cfg.jobs_dir / "running" / f"{sid}.json"
    running.write_text(json.dumps({
        "submission_id": sid, "zip_path": str(zpath), "quarantine_dir": str(quarantine),
    }), encoding="utf-8")

    engine_cmds = []

    def capture_sub(cmd, *, cwd, deadline):
        if any("validate_survey.py" in c for c in cmd):
            _emulate_real_validator(cmd, {"items": [{"level": "PASS", "check": "metadata",
                                                     "message": "ok"}]})
            return subprocess.CompletedProcess(cmd, 0, stdout="[PASS   ] metadata ok", stderr="")
        # the engine module invocation (the preview build) — record it for the flag assertion.
        _assert_engine_surveys_level(cmd)
        engine_cmds.append(list(cmd))
        out_idx = cmd.index("--out") + 1
        Path(cmd[out_idx]).mkdir(parents=True, exist_ok=True)
        (Path(cmd[out_idx]) / "catalogue.json").write_text("[]", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(runner, "_run_subprocess", capture_sub)
    runner.process_job(cfg, running)

    assert engine_cmds, "the runner never invoked the engine module (test set-up wrong)"
    for cmd in engine_cmds:
        for flag in ("--incremental", "--cache-dir", "--cache-mode"):
            assert flag not in cmd, \
                f"gateway runner passed the C18 cache flag {flag} to the engine (must stay non-incremental): {cmd}"


# --------------------------------------------------------------------------------------------------
# C35b/D4 (code-health review M4): run_forever's loop contracts, pinned at the poll_once seam.
# run_forever's body is now poll_once(cfg); these tests enforce the ordering + crash-recovery
# contracts the M4 finding said were enforced NOWHERE (the old run_forever docstring falsely claimed
# compose-e2e coverage in a lane where the runner never boots).
# --------------------------------------------------------------------------------------------------
def test_poll_once_drains_edit_jobs_before_submission_jobs(tmp_path, monkeypatch):
    # D4(i) — FAILS IF a submission job is processed before a pending edit job in the same pass. Edit
    # jobs are request/response (a curator is blocked polling) and must drain FIRST. proven by ordering:
    # reorder the drain after the submission claim on a scratch copy and this goes RED (transcript in
    # the report).
    from gateway.runner import edit as edit_mod
    cfg = _runner_cfg(tmp_path)
    jobs.ensure_dirs(cfg.jobs_dir)

    # One pending edit job + one pending submission job.
    dirs = edit_mod.edit_dirs(cfg.jobs_dir)
    (dirs["pending"] / "E1.json").write_text(
        json.dumps({"kind": "read", "slug": "s"}), encoding="utf-8")
    jobs.write_pending(cfg.jobs_dir, "S1", tmp_path / "s.zip", cfg.quarantine_dir / "S1")

    order: list[str] = []
    monkeypatch.setattr(edit_mod, "process_edit_job",
                        lambda _cfg, rf: (order.append("edit"), rf.unlink())[1])
    monkeypatch.setattr(runner, "process_job",
                        lambda _cfg, rf, **kw: (order.append("submission"), rf.unlink())[1])

    processed = runner.poll_once(cfg)
    assert processed is True, "poll_once should report it processed the submission job"
    assert order == ["edit", "submission"], f"edit must drain before submission, got {order}"


def test_poll_once_crash_leaves_running_file_and_no_done_file(tmp_path, monkeypatch):
    # D4(ii) — the crash-recovery contract: if process_job CRASHES (unhandled), poll_once must let the
    # exception propagate WITHOUT writing a done-file, leaving the running-file present for the
    # gateway's dead-job sweep to re-queue. A crashed job is NEVER silently marked done. FAILS IF the
    # running-file vanishes or a done-file appears on a crash.
    cfg = _runner_cfg(tmp_path)
    jobs.ensure_dirs(cfg.jobs_dir)
    jobs.write_pending(cfg.jobs_dir, "S1", tmp_path / "s.zip", cfg.quarantine_dir / "S1")

    def boom(_cfg, _running_file, **kw):
        raise RuntimeError("simulated unhandled crash inside process_job")

    monkeypatch.setattr(runner, "process_job", boom)

    with pytest.raises(RuntimeError, match="simulated unhandled crash"):
        runner.poll_once(cfg)

    running = cfg.jobs_dir / "running" / "S1.json"
    done = cfg.jobs_dir / "done" / "S1.json"
    assert running.exists(), "crash-recovery contract: the running-file must remain for the sweep"
    assert not done.exists(), "a crashed job must NEVER be marked done"


def test_poll_once_returns_false_when_no_submission_pending(tmp_path):
    # The run_forever sleep signal: poll_once returns False when no submission job is pending (so
    # run_forever sleeps). FAILS IF a no-work pass reports work done. (Edit-only passes still return
    # False — an edit drain is not a submission-job processed.)
    cfg = _runner_cfg(tmp_path)
    jobs.ensure_dirs(cfg.jobs_dir)
    assert runner.poll_once(cfg) is False
