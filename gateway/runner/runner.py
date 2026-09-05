"""Runner loop. Claims pending jobs (atomic rename = lock), safe-extracts, runs the
validator and the engine preview build as SUBPROCESSES, writes a done-file, removes the running
file. Runs inside the engine image with no network, non-root, resource-capped.

The runner NEVER touches the gateway DB and never reads PII: a job file carries only ids and paths.
It invokes the validator/engine as subprocesses (never imports them into the gateway package) so
the two-gates-must-agree property holds at the same image pin the engine uses.

Timeout: a hard wall-clock cap around the whole job. On POSIX this is SIGALRM; the
cap is expressed through job_deadline() so the timeout PATH is unit-testable on any OS (a test
passes a deadline already in the past and asserts the job quarantines with a timeout reason) without
depending on signal delivery.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .. import jobs
from ..config import DEFAULT_MAX_UPLOAD_MB  # Single source of the 250 MB upload default
from .safeextract import ExtractionTimeout, cap_for, safe_extract

# Env pins. AUSMT_VALIDATOR_PATH is the same env the engine's _load_validator() reads;
# in the runner container it points at the in-image validator copy.
_DEFAULT_TIMEOUT_S = 900

# The >INFO pre-flight report, written beside validate.json so a curator can read the whole finding
# list, and the cap on how many of its sentences reach the status page. The Western Gawler delivery
# would otherwise put 246 lines on a page nobody then reads to the end; the rest are rolled into a
# count that points at the JSON.
PREFLIGHT_REPORT = "edi-preflight.json"
PREFLIGHT_ADVISORY_LINES = 12
# ... and the same reasoning applied to the artifact that lands on disk, which it was not at first.
# A finding carries one record per metadata value damaged on the way in, and the Western Gawler 312
# measure 35,880 of them: 1.68 MB, about 5.4 KB a file. The upload cap
# (DEFAULT_MAX_UPLOAD_MB x MAX_TOTAL_UNCOMPRESSED_FACTOR) allows roughly 13,500 EDIs of that size,
# so an unbounded report is a ~70 MB write into the quarantine volume. Nothing reads more than a
# few samples anyway (`_advisory_lines` and the CLI report both show three), so the persisted copy
# keeps the first few plus the true count, and SAYS it was truncated rather than quietly shrinking.
# The CLI keeps the full list: somebody running it has chosen the package and is not writing into a
# shared volume.
PREFLIGHT_REPORT_SAMPLES = 5


class JobTimeout(Exception):
    """The job exceeded its wall-clock budget. Quarantines with a 'could not complete' reason."""


@dataclass(frozen=True)
class RunnerConfig:
    incoming_dir: Path
    quarantine_dir: Path
    jobs_dir: Path
    validator_path: str
    engine_module: str = "extract.build_portal"
    # Working directory for the preview subprocess (`python -m extract.build_portal`). Passed
    # EXPLICITLY so module resolution never rides on the runner inheriting compose's WORKDIR (the
    # undocumented cwd contract removed). With `extract` now a real installed package the
    # spawn resolves regardless of cwd; this pin keeps the invocation self-describing rather than
    # env-topology-dependent. Default matches the engine image's WORKDIR (/app/engine).
    engine_dir: Path = Path("/app/engine")
    timeout_s: int = _DEFAULT_TIMEOUT_S
    # Heartbeat interval (fix #6). Well under any sane dead-job threshold (gateway uses 2x timeout),
    # so a live job's running-file mtime stays fresh between sweep passes.
    heartbeat_s: float = 30.0
    # Max upload size (bytes) — used only to derive the extraction byte cap (fix #10), which must
    # match the gateway's upload-time 4x-total rule. The MB default is IMPORTED from the gateway
    # config so it cannot drift from the gateway's own default.
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_MB * 1024 * 1024
    # Metadata-edit jobs: where THIS container sees the surveys-live checkout (compose mounts it
    # READ-ONLY at /srv/surveys — the same mount the validator ships in). Edit jobs carry a SLUG,
    # never a path (the gateway's mount path /srv/surveys-live differs from this container's), and
    # the runner resolves the package from here - mirroring the rule that the runner recomputes
    # paths from its own env and never trusts one handed to it in a job file.
    surveys_root: Path = Path("/srv/surveys")

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "RunnerConfig":
        env = os.environ if environ is None else environ
        data = Path(env.get("AUSMT_GW_DATA", "/gw"))
        job_timeout_s = int(env.get("AUSMT_JOB_TIMEOUT_S", str(_DEFAULT_TIMEOUT_S)))
        max_upload_mb = int(env.get("AUSMT_MAX_UPLOAD_MB", str(DEFAULT_MAX_UPLOAD_MB)))
        # Fail closed on a zeroed/negative override, IDENTICALLY to the gateway (config._RANGES floors
        # both of these at 1, and fail_closed_startup SystemExits on a breach). The runner reads the
        # SAME two knobs, and an int() with no floor would let a zeroed AUSMT_JOB_TIMEOUT_S
        # (every job times out instantly -> everything quarantines) or AUSMT_MAX_UPLOAD_MB (a zero
        # extraction byte-cap) through while the gateway rejected it - the runner crash-loops
        # honestly on a bad numeric knob instead.
        for _env_name, _value in (("AUSMT_JOB_TIMEOUT_S", job_timeout_s),
                                  ("AUSMT_MAX_UPLOAD_MB", max_upload_mb)):
            if _value < 1:
                raise SystemExit(
                    f"{_env_name} must be >= 1, got {_value} "
                    "(fail closed: an out-of-range knob breaks the runner silently)"
                )
        return cls(
            incoming_dir=data / "incoming",
            quarantine_dir=data / "quarantine",
            jobs_dir=data / "jobs",
            validator_path=env.get("AUSMT_VALIDATOR_PATH", "/srv/surveys/_validation"),
            engine_dir=Path(env.get("AUSMT_ENGINE_DIR", "/app/engine")),
            timeout_s=job_timeout_s,
            heartbeat_s=float(env.get("AUSMT_HEARTBEAT_S", "30")),
            max_upload_bytes=max_upload_mb * 1024 * 1024,
            surveys_root=Path(env.get("AUSMT_SURVEYS_ROOT", "/srv/surveys")),
        )


def claim_one(jobs_dir: Path) -> Path | None:
    """Claim a single pending job by renaming pending/<id>.json -> running/<id>.json. The atomic
    same-fs rename IS the lock: if two runners race, exactly one rename succeeds (the other gets
    FileNotFoundError and moves on). Returns the running-file path, or None if nothing to claim."""
    jobs.ensure_dirs(jobs_dir)
    pending = jobs_dir / "pending"
    running = jobs_dir / "running"
    for src in sorted(pending.glob("*.json")):
        dest = running / src.name
        try:
            os.replace(src, dest)
        except OSError:
            continue  # lost the race (or vanished) — try the next
        return dest
    return None


def _run_subprocess(cmd: list[str], *, cwd: Path | None, deadline: float,
                    env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run cmd with a timeout derived from the job deadline. Raises JobTimeout if the remaining
    budget is already gone or the process overruns it. Output is captured (never streamed to the
    runner's stdout, which could carry submitted bytes into logs).

    `env` is the COMPLETE child environment when given (None inherits this process's, the historical
    behaviour). Only the engine preview spawn passes it, to pin AUSMT_VALIDATOR_PATH; see
    _preview_env()."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise JobTimeout("job budget exhausted before subprocess start")
    try:
        return subprocess.run(  # noqa: PLW1510 -- returncode inspected by the caller
            cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True,
            timeout=remaining, env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise JobTimeout(f"subprocess exceeded budget: {cmd[0]}") from exc


def process_job(cfg: RunnerConfig, running_file: Path, *, now: float | None = None) -> None:
    """Execute one claimed job to a done-file. On ANY failure (unsafe extract, validator FAIL,
    preview build fail, timeout) the outcome is 'quarantined' with a reason — never an exception
    that leaves a stale running-file with no done-file (that is the crash-recovery path, distinct
    from a handled failure).

    A heartbeat thread touches the running-file's mtime every heartbeat_s while the job runs, so the
    gateway's dead-job sweep (which judges liveness by running-file mtime) never re-queues a
    legitimately SLOW job (fix #6 — AusLAMP-national builds are ~1100 EDIs and can run long). The
    whole job is still bounded by `deadline`, checked between phases and enforced on each subprocess
    (fix #7), so a genuine hang can't heartbeat forever: once past the deadline every phase refuses
    to start and the job quarantines."""
    body = json.loads(running_file.read_text(encoding="utf-8"))
    submission_id = body["submission_id"]
    zip_path = Path(body["zip_path"])
    quarantine_dir = Path(body["quarantine_dir"])
    deadline = (time.monotonic() if now is None else now) + cfg.timeout_s

    package_dir = quarantine_dir / "package"
    reports_dir = quarantine_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    heartbeat = _Heartbeat(running_file, cfg.heartbeat_s)
    heartbeat.start()
    try:
        outcome, reason, refs = _do_work(cfg, zip_path, package_dir, reports_dir, deadline)
    finally:
        heartbeat.stop()

    jobs._atomic_write_json(
        cfg.jobs_dir / "done" / f"{submission_id}.json",
        {"submission_id": submission_id, "outcome": outcome, "reason": reason, "report_refs": refs},
    )
    running_file.unlink(missing_ok=True)


class _Heartbeat:
    """Touches a file's mtime on a timer in a daemon thread. Bounds fix #6's liveness signal to the
    running-file the gateway sweep watches. Stops cleanly; a touch failure (file already gone) is
    swallowed — the job is ending anyway."""

    def __init__(self, path: Path, interval_s: float):
        self._path = path
        self._interval = max(0.1, interval_s)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=self._interval + 1.0)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                now = time.time()
                os.utime(self._path, (now, now))
            except OSError:
                return


def _do_work(cfg: RunnerConfig, zip_path: Path, package_dir: Path, reports_dir: Path,
             deadline: float) -> tuple[str, str, dict]:
    # Whole-job wall-clock bound (fix #7): the deadline is checked before EACH phase and enforced on
    # each subprocess, so a job can never run past cfg.timeout_s even outside a subprocess (a slow
    # extraction is aborted; a hung orchestration refuses the next phase). This is the portable
    # replacement for the design's SIGALRM.
    if time.monotonic() > deadline:
        return jobs.OUTCOME_QUARANTINED, "job budget exhausted before unpack", {}
    try:
        safe_extract(zip_path, package_dir,
                     max_total_bytes=cap_for(cfg.max_upload_bytes), deadline=deadline)
    except ExtractionTimeout as exc:
        return jobs.OUTCOME_QUARANTINED, f"unpack could not complete: {exc}", {}
    except Exception as exc:  # noqa: BLE001
        # ANY extraction failure quarantines — it must never crash the runner (leaving a stale
        # running-file and no done-file). safe_extract's own decompression (zipfile/zlib) raises
        # BadZipFile / zlib.error / EOFError on a crafted zip (lying file_size/CRC), NONE of which
        # are OSError; a narrow except let those kill process_job. A hostile package is exactly the
        # input that gets here, so the catch is deliberately broad — a handled quarantine, not a
        # crash. (UnsafeMember, the belt-and-braces re-check failure, is included.)
        return jobs.OUTCOME_QUARANTINED, f"unpack failed: {type(exc).__name__}: {exc}", {}

    # Generate LICENSE.md + README.md into the extracted package BEFORE the validator runs, so
    # a package that arrived without them carries them by the time the validator checks structure (the
    # two 'missing' WARNINGs flip to PASS in the SAME run) and the curator reviews/approves the COMPLETE
    # package. Best-effort: any failure here must NEVER quarantine an otherwise-valid package — the
    # validator remains the authority, and a package that stays without a generated file just keeps the
    # (correct) WARNING. So this is deliberately outside the quarantine-on-failure contract above.
    _generate_intake_files(package_dir)

    validate_json = reports_dir / "validate.json"
    try:
        vresult = _run_validator(cfg, package_dir, validate_json, deadline)
    except JobTimeout as exc:
        return jobs.OUTCOME_QUARANTINED, f"validation could not complete: {exc}", {}
    if vresult is False:
        return jobs.OUTCOME_QUARANTINED, "validator reported FAIL", {"validate": "reports/validate.json"}

    # The >INFO pre-flight (engine extract/edi_preflight.py). ADVISORY, never a gate: it says what an
    # EDI's >INFO block will do to the metadata AusMT can read, and a stray comma in a metadata field
    # must tell the submitter about it rather than refuse their data. It runs here, after the
    # validator has agreed the package is well formed, and its sentences ride into the preview
    # summary's `warnings`: the one surface BOTH the submitter status page and the curator's reports
    # panel already render, so nothing new has to be plumbed to either.
    advisories = _edi_preflight(package_dir, reports_dir)

    preview_dir = reports_dir / "preview-data"
    summary_path = reports_dir / "preview-summary.json"
    try:
        ok = _run_preview(cfg, package_dir, preview_dir, summary_path, deadline, advisories=advisories)
    except JobTimeout as exc:
        return jobs.OUTCOME_QUARANTINED, f"preview build could not complete: {exc}", {}
    if not ok:
        return jobs.OUTCOME_QUARANTINED, "engine preview build failed", {"validate": "reports/validate.json"}

    slug = _slug_from_package(package_dir)
    refs = {"validate": "reports/validate.json", "preview": "reports/preview-summary.json"}
    if (reports_dir / PREFLIGHT_REPORT).is_file():
        refs["edi_preflight"] = f"reports/{PREFLIGHT_REPORT}"
    if slug:
        refs["slug"] = slug
    return jobs.OUTCOME_VALIDATED, "validated + preview built", refs


def _run_validator(cfg: RunnerConfig, package_dir: Path, out_json: Path, deadline: float) -> bool:
    """Run `validate_survey.py <folder> --json <out_json>` against the single package and read the
    machine report back FROM THAT FILE. Returns True on PASS/WARN, False on FAIL. The validator
    lives in the surveys repo (bind-mounted at AUSMT_VALIDATOR_PATH); it is invoked as a subprocess,
    never imported.

    Invocation contract: the
    validator takes the package folder as a REQUIRED positional and `--json` takes an OUTPUT FILE
    path; its stdout carries only the human `[LEVEL] check message` lines — the machine-readable
    {counts, items, manifest} JSON goes ONLY to the --json file. The original implementation passed
    the folder as the --json VALUE (no positional at all), so argparse exited 2 before any
    validation ran, stdout was empty, and EVERY real submission quarantined with 'validator
    reported FAIL' — masked locally because these tests stub _run_subprocess. out_json doubles as
    the persisted reports/validate.json the status page + curator checklist read (same {items:[...]}
    shape as before — the validator's own file IS the artifact now). Fail closed: an absent or
    unparseable report file is a synthetic FAIL report (written so the artifact still exists for
    the curator), and a non-zero exit is False regardless."""
    validator_file = _validator_file(cfg.validator_path)
    target = _single_package_root(package_dir)
    proc = _run_subprocess(
        validator_argv(validator_file, target, out_json),  # The one canonical argv
        cwd=None, deadline=deadline,
    )
    try:
        report = json.loads(out_json.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise ValueError("validator report was not an object")
    except (OSError, ValueError) as exc:
        report = {"items": [{"level": "FAIL", "check": "validator",
                             "message": f"validator produced no readable JSON report ({exc})"}]}
        out_json.write_text(json.dumps(report), encoding="utf-8")
    if proc.returncode != 0:
        return False
    return _validator_passed(report)


def _validator_passed(report: dict) -> bool:
    """Interpret the validator report as PASS/WARN (True) or FAIL (False). The real validator writes
    {"items":[{level:...}]}; ANY item at level FAIL/ERROR is a failure. Fall back to explicit ok/pass
    booleans for other shapes. Default True only when the returncode was already 0 and nothing signals
    failure (fail-closed is enforced upstream by the returncode check and the parse-failure branch)."""
    if not isinstance(report, dict):
        return False
    items = report.get("items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                level = str(item.get("level") or item.get("status") or "").upper()
                if level in ("FAIL", "ERROR"):
                    return False
        return True
    if "ok" in report:
        return bool(report["ok"])
    if "pass" in report:
        return bool(report["pass"])
    return True


def _preview_env(cfg: RunnerConfig) -> dict[str, str]:
    """The child environment for the engine preview spawn: this process's environment PLUS an
    explicit AUSMT_VALIDATOR_PATH pinned to cfg.validator_path.

    The preview build runs the SAME validator gate again in-process (build_portal._load_validator),
    resolving it from AUSMT_VALIDATOR_PATH first and otherwise walking upward for a sibling
    ausmt-surveys checkout; if neither resolves it refuses to ingest unvalidated and exits rc=2. The
    runner already knows exactly which validator it gates on: cfg.validator_path, the same value
    _run_validator hands the validator subprocess. Handing it to the build makes the two gates agree
    BY CONSTRUCTION rather than by both happening to inherit the same ambient environment.

    On the box this is the value compose exports as AUSMT_VALIDATOR_PATH, which cfg.validator_path is
    read from, so the spawn is unchanged there. Off the box it is the difference between a preview
    build and a bare rc=2 'survey validator not found': the gateway test suite configures the runner
    with the vendored validator copy, which the build could not see because it was never told."""
    return {**os.environ, "AUSMT_VALIDATOR_PATH": str(cfg.validator_path)}


def _run_preview(cfg: RunnerConfig, package_dir: Path, preview_dir: Path, summary_path: Path,
                 deadline: float, *, advisories: list[str] | None = None) -> bool:
    """Run the engine preview build of the single package into preview_dir, then write a compact
    preview-summary.json (station count, types, coord flags, warnings). Returns True on success.

    The layout contract (established EMPIRICALLY from the Olympic Dam 2004 incident):
    safe-extract preserves the zip's single <slug>/ root, so package_dir/<slug>/survey.yaml is
    exactly the `--surveys <root>` shape build_portal's discover_work iterates — discovery is at the
    RIGHT level (the real 58-EDI package built 58/58 once its slug was valid). Two guards make a
    failure diagnosable instead of a bare 'preview build failed':

    - Discovery guard: no <slug>/survey.yaml under the root at all => refuse loudly BEFORE spawning
      the engine, with a message distinct from zero stations BUILT.
    - Loud failure summary: on a non-zero engine exit, distil the build's own stdout/stderr into the
      summary (attempted-vs-built line, in-build SKIP reasons, ERROR lines) — in the incident the
      build's stderr said precisely why ('SKIP Olympic-Dam-2004: validation FAILED (1 fails)': the
      in-build validator re-run failed the slug-charset gate and dropped the survey, empty-output
      guard exited rc=2) but the runner discarded it and the curator saw only the generic string."""
    advisories = list(advisories or [])
    surveys_root = package_dir
    survey_dirs = ([p for p in surveys_root.iterdir()
                    if p.is_dir() and (p / "survey.yaml").is_file()]
                   if surveys_root.exists() else [])
    if not survey_dirs:
        _write_summary(summary_path, {"station_count": 0, "warnings": [
            "no survey folder found in package (expected <slug>/survey.yaml under the package root)"]})
        return False
    preview_dir.mkdir(parents=True, exist_ok=True)
    proc = _run_subprocess(
        [sys.executable, "-m", cfg.engine_module,
         "--surveys", str(surveys_root), "--out", str(preview_dir), "--products", str(preview_dir / "products")],
        # Explicit cwd: spawn the engine module from cfg.engine_dir instead of inheriting the
        # runner's cwd. `extract` is an installed package so resolution does not NEED this, but
        # pinning it removes the silent dependence on compose's WORKDIR that once broke the runner.
        cwd=cfg.engine_dir, deadline=deadline,
        # Explicit validator pin (same rationale as the cwd above, one layer down): hand the build the
        # validator the runner is configured to gate on instead of letting it re-derive one.
        env=_preview_env(cfg),
    )
    if proc.returncode != 0:
        # The pre-flight advisories go in HERE too, and deliberately: a build that failed is exactly
        # when "246 of these 312 files need the >INFO repair" is the sentence somebody needs. They
        # follow the failure details, which stay first because existing consumers match on them.
        _write_summary(summary_path, {
            "station_count": 0,
            "warnings": _build_failure_details(proc.stdout, proc.stderr, str(package_dir)) + advisories})
        return False
    summary = _summarise_preview(preview_dir)
    summary["warnings"] = list(summary.get("warnings") or []) + advisories
    _write_summary(summary_path, summary)
    return True


def _build_failure_details(stdout: str, stderr: str, package_prefix: str,
                           max_lines: int = 8) -> list[str]:
    """Distil WHY a preview build failed into a bounded list of summary warnings: the generic marker
    first (existing consumers match on it), then the attempted-vs-built stdout line, then the first
    `max_lines` DISTINCT stderr lines (SKIP reasons, per-station errors, the empty-output guard).
    The validator-path banner is dropped (noise), and the package path prefix is scrubbed so a
    server-side absolute path never reaches the submitter-visible status page."""
    details = ["preview build failed"]
    built = next((ln.strip() for ln in stdout.splitlines()
                  if ln.strip().startswith("built ")), None)
    if built:
        details.append(built)
    seen: set[str] = set()
    extracted: list[str] = []
    for ln in stderr.splitlines():
        s = ln.strip().replace(package_prefix, "<package>")
        if not s or s.startswith("survey validator:"):
            continue
        if s not in seen:
            seen.add(s)
            extracted.append(s)
    details.extend(extracted[:max_lines])
    if len(extracted) > max_lines:
        details.append(f"... and {len(extracted) - max_lines} more distinct build messages")
    return details


def _summarise_preview(preview_dir: Path) -> dict:
    """Derive a compact summary from the engine's output. No PII: catalogue/manifest are generated
    science metadata, never submitter fields. The portal catalogue.json is a bare positional array
    of station rows (one row per station — see build_portal.py's CATALOGUE_COLUMNS contract), so its
    length is the station count. manifest.json carries surveys/bundles for a light types glance."""
    summary: dict = {"station_count": 0, "types": [], "coord_flags": [], "warnings": []}
    catalogue = _read_json(preview_dir / "catalogue.json")
    if isinstance(catalogue, list):
        summary["station_count"] = len(catalogue)
    elif isinstance(catalogue, dict):
        rows = catalogue.get("rows") or catalogue.get("stations") or []
        summary["station_count"] = len(rows) if isinstance(rows, list) else 0
    return summary


def _slug_from_package(package_dir: Path) -> str | None:
    """The single top-level directory name under the extracted package IS the slug (design: one
    top-level dir enforced at upload). Read from the directory layout, NOT by parsing survey.yaml —
    the runner stays content-blind about YAML."""
    try:
        entries = [p for p in package_dir.iterdir() if p.is_dir()]
    except OSError:
        return None
    return entries[0].name if len(entries) == 1 else None


def _single_package_root(package_dir: Path) -> Path:
    """The validator wants the package root (the dir holding survey.yaml). With one enforced
    top-level dir, that is <package_dir>/<slug>; fall back to package_dir itself."""
    dirs = [p for p in package_dir.iterdir() if p.is_dir()] if package_dir.exists() else []
    return dirs[0] if len(dirs) == 1 else package_dir


def _generate_intake_files(package_dir: Path) -> list[str]:
    """Generate LICENSE.md + README.md into the single extracted package root, best-effort.
    Returns the filenames actually written (for logging); NEVER raises - a generation failure must not
    quarantine an otherwise-valid package (the validator remains the authority, and the worst case is
    a package that keeps its correct 'file missing' WARNING). `intake` is imported lazily (it reaches
    the engine's _license_text leaf) so this module stays importable without the engine installed."""
    try:
        from . import intake  # lazy: keeps the runner importable in the stack-less gateway environment
        return intake.generate_intake_files(_single_package_root(package_dir))
    except Exception:  # noqa: BLE001 -- best-effort generation; a failure must not fail the job
        return []


def _import_preflight():
    """Resolve the engine's stdlib-only `edi_preflight` leaf, the same way `intake` resolves
    `_license_text`: on the engine image `extract` is an installed package, and a sibling
    checkout with engine/extract on sys.path resolves the bare name.

    This is an IMPORT, not a subprocess, and that is the deliberate exception the runner already
    makes once. The house rule exists so the runner never pulls the scientific stack (mt_metadata /
    mth5 / numpy) into itself; `edi_preflight` is stdlib-only by construction and pinned that way by
    its own test, so importing it costs nothing the rule is protecting against. Lazy, so the gateway
    test run can import this module with no engine present at all."""
    try:
        from extract.edi_preflight import advisory_summary, preflight_tree
    except ImportError:  # pragma: no cover - sibling-on-sys.path fallback (engine cwd / dev checkout)
        from edi_preflight import advisory_summary, preflight_tree  # type: ignore[no-redef]
    return preflight_tree, advisory_summary


def _edi_preflight(package_dir: Path, reports_dir: Path) -> list[str]:
    """Run the >INFO pre-flight over the extracted package, persist the full report beside the
    validator's, and return the BOUNDED advisory sentences for the preview summary.

    Best-effort in exactly the sense `_generate_intake_files` is: a failure here must NEVER change
    the outcome of a submission. The pre-flight is advice; a package whose advice could not be
    computed is still a package the validator passed, and quarantining it for that would be absurd.
    Returns [] on any failure, and [] for a package with nothing to report."""
    try:
        preflight_tree, advisory_summary = _import_preflight()
        report = preflight_tree(_single_package_root(package_dir))
        # The ADVICE is derived from the whole report, before anything is capped, so the sentences
        # and the summary counts are the real ones.
        advisories = advisory_summary(report, limit=PREFLIGHT_ADVISORY_LINES)
        (reports_dir / PREFLIGHT_REPORT).write_text(json.dumps(_bounded_report(report)),
                                                    encoding="utf-8")
        return advisories
    except Exception:  # noqa: BLE001 -- advisory only; a failure must not fail the job
        return []


def _bounded_report(report: dict) -> dict:
    """The pre-flight report with each finding's per-value list capped for persistence.

    Only `delimited_values` can grow with the data (one record per damaged value); the other two
    lists are bounded by the number of fields the module models. A capped finding carries the true
    count and a truncation flag, so the file is self-describing and reconciles against the summary
    totals, which are left exactly as computed."""
    findings = []
    for finding in report.get("findings", []):
        values = finding.get("delimited_values") or []
        if len(values) > PREFLIGHT_REPORT_SAMPLES:
            findings.append({**finding,
                             "delimited_values": values[:PREFLIGHT_REPORT_SAMPLES],
                             "delimited_values_total": len(values),
                             "delimited_values_truncated": True})
        else:
            findings.append(finding)
    return {**report, "findings": findings}


def _validator_file(validator_path: str) -> Path:
    p = Path(validator_path)
    return p if p.name == "validate_survey.py" else (p / "validate_survey.py")


def validator_argv(validator_file: Path, target_dir: Path, report_path: Path) -> list[str]:
    """The ONE canonical argv for invoking the surveys validator as a subprocess. Both the
    submission runner (_run_validator above) and the metadata-edit
    runner (edit._run_validator) go through this, so the invocation contract lives in exactly one
    place - no second, independently-assembled argv can drift and re-open the ship-blocker
    (the folder had been passed as the --json VALUE with no positional, argparse exited 2, every real
    submission quarantined).

    Canonical shape (the runner's positional-first form): the package folder is the REQUIRED
    positional and `--json` names the OUTPUT report file. edit.py must not assemble the flags
    --json-first (`--json <file> <folder>`); argparse accepts both, and a single form is the point:
    the positional-first order is the one the real-vendored-validator oracles pin. All args are
    stringified here so callers pass Paths and the whole subprocess contract is described in one line."""
    return [sys.executable, str(validator_file), str(target_dir), "--json", str(report_path)]


def _write_summary(path: Path, summary: dict) -> None:
    path.write_text(json.dumps(summary), encoding="utf-8")


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def poll_once(cfg: RunnerConfig) -> bool:
    """One poll pass: drain ALL pending edit jobs, then claim and
    process AT MOST ONE submission job. Returns True if a submission job was processed this pass,
    False if none was pending (so run_forever knows whether to sleep). Pure extraction of the old
    run_forever body - byte-equivalent logic, no behaviour change.

    Ordering contract: metadata-edit jobs (jobs/edit/*) are drained FIRST - they are
    request/response (a curator is blocked polling for the result) while submission jobs are batch.
    process_edit_job never raises (failures become {ok:False} result files), so the crash-recovery
    contract of the submission queue below is untouched.

    Crash-recovery contract: a process_job crash PROPAGATES out of this function WITHOUT writing a
    done-file, leaving the running-file present for the gateway's dead-job sweep to re-queue - distinct
    from a handled failure, which already wrote a 'quarantined' done-file inside process_job. This is
    the contract that had no test: it is now pinned by test_runner.py."""
    from . import edit as edit_mod  # lazy: keeps this module importable without ruamel

    while True:
        edit_claimed = edit_mod.claim_edit_job(cfg.jobs_dir)
        if edit_claimed is None:
            break
        edit_mod.process_edit_job(cfg, edit_claimed)
    claimed = claim_one(cfg.jobs_dir)
    if claimed is None:
        return False
    try:
        process_job(cfg, claimed)
    except Exception:  # noqa: BLE001 -- a crash here must leave the running-file for gateway recovery
        # Deliberately DO NOT write a done-file: an unhandled crash is the crash-recovery path
        # (gateway re-queues the stale running-file), distinct from a handled failure which already
        # wrote a 'quarantined' done-file inside process_job.
        raise
    return True


def run_forever(cfg: RunnerConfig, poll_interval_s: float = 2.0) -> None:  # pragma: no cover
    """The runner's main loop. run_forever is a thin driver over poll_once: each pass drains
    edit jobs then processes at most one submission job; when a pass processed nothing pending, sleep
    before the next. The loop's ordering and crash-recovery contracts live in poll_once, which IS
    unit-tested (test_runner.py) - the correction: this loop is NOT covered by any compose e2e that
    boots the runner, so the coverage claim the old docstring made was false; the contracts are pinned
    at the poll_once seam instead. The single-threaded known limitation stands: an edit
    job arriving MID submission-job waits for it; the gateway's bounded poll surfaces a retryable
    timeout to the curator."""
    while True:
        if not poll_once(cfg):
            time.sleep(poll_interval_s)
