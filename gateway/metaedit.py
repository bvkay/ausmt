"""C31 curator metadata-editor orchestration (gateway side). The gateway NEVER parses survey content
(C31 §0.1 / the C10 house rule, pinned by the §3.8 source-assertion test AND the subprocess
import-hygiene test): every yaml load/merge/emit/diff/validate happens in the gw-runner — the ENGINE
image, which is where ruamel lives — reached through the C10 file-queue pattern in its own
jobs/edit/ namespace. This module only writes job JSON, polls for the result JSON, and reads it
back; job files carry a SLUG and form values, never a filesystem path (the two containers mount
surveys-live at different paths) and never PII.

Adversarial-review FIX 1 (ship-blocker, 2026-07-06): the first implementation spawned
`sys.executable -m gateway.runner.edit` as a CHILD OF THE GATEWAY CONTAINER — whose image
deliberately has no ruamel — so every real curator edit would have 500'd in deployment (tests passed
only via an in-process seam). The queue below is the adjudicated replacement: the gateway enqueues,
the gw-runner service (engine image, already polling /gw/jobs) processes, the gateway polls the
result with a bounded timeout. The polling is BLOCKING by design and must never run on the event
loop: the sync form route runs in Starlette's threadpool, and the async preview/confirm handlers
call this seam via asyncio.to_thread (review FIX 4).
"""
from __future__ import annotations

import contextlib
import json
import shutil
import time
import uuid
from pathlib import Path

from . import jobs

# How long a leftover edit-queue entry (job, result, or scratch dir) may sit before the
# opportunistic janitor removes it. Generous: an hour-old edit artifact belongs to a request nobody
# is polling for any more (the gateway's bounded poll gave up long ago).
_STALE_AFTER_S = 3600.0

# The edit-queue namespace under jobs/ — must match gateway/runner/edit.py's EDIT_SUBDIR (kept as a
# literal here so this module never imports the runner package, which imports ruamel).
_EDIT_SUBDIR = "edit"


class EditRunnerError(Exception):
    """The runner could not produce a result in time (service down, job crashed without a result, or
    the runner is mid-validation of a long submission job). Curator-facing and retryable. Distinct
    from a refusal, which the runner returns as {ok:False, error}."""


def _edit_dirs(jobs_dir: Path) -> dict[str, Path]:
    root = jobs_dir / _EDIT_SUBDIR
    out = {name: root / name for name in ("pending", "running", "done", "scratch")}
    for p in out.values():
        p.mkdir(parents=True, exist_ok=True)
    return out


def purge_stale_edit_files(jobs_dir: Path, *, now: float | None = None) -> None:
    """Opportunistic janitor, called on each enqueue: remove edit-queue entries older than
    _STALE_AFTER_S (abandoned jobs/results from a timed-out request or a runner killed mid-job, and
    leaked scratch dirs). Best-effort — a failure to clean never blocks the current request."""
    now = time.time() if now is None else now
    for p in _edit_dirs(jobs_dir).values():
        for entry in sorted(p.iterdir()):
            try:
                if now - entry.stat().st_mtime < _STALE_AFTER_S:
                    continue
                if entry.is_dir():
                    shutil.rmtree(entry, ignore_errors=True)
                else:
                    entry.unlink(missing_ok=True)
            except OSError:
                continue


def default_edit_runner(job: dict, jobs_dir: Path, *, timeout_s: float = 120.0,
                        poll_s: float = 0.2) -> dict:
    """The real seam: enqueue jobs/edit/pending/<id>.json (atomic tmp+rename) and poll
    jobs/edit/done/<id>.json until the gw-runner has processed it, with a bounded timeout. The done
    file is written atomically by the runner, so its appearance means it is complete; read + unlink
    and return the result dict. On timeout, best-effort-remove this job's queue entries and raise
    EditRunnerError (the pending unlink also covers the runner-down case, so a dead service does not
    accumulate a backlog it would burst-process on restart)."""
    dirs = _edit_dirs(jobs_dir)
    purge_stale_edit_files(jobs_dir)
    job_id = uuid.uuid4().hex
    done_path = dirs["done"] / f"{job_id}.json"
    jobs._atomic_write_json(dirs["pending"] / f"{job_id}.json", job)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if done_path.is_file():
            try:
                result = json.loads(done_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise EditRunnerError(f"unreadable edit result: {exc}") from exc
            finally:
                done_path.unlink(missing_ok=True)
            if not isinstance(result, dict):
                raise EditRunnerError("edit result was not an object")
            return result
        time.sleep(poll_s)
    for leftover in (dirs["pending"] / f"{job_id}.json", dirs["running"] / f"{job_id}.json",
                     done_path):
        with contextlib.suppress(OSError):
            leftover.unlink(missing_ok=True)
    raise EditRunnerError(
        f"the edit runner did not respond within {timeout_s:.0f}s — "
        "is the gw-runner service running (or busy validating a submission)?")


def list_published_slugs(surveys_live: Path | None) -> list[str]:
    """The PUBLISHED surveys editable in v1: the immediate child directories of surveys-live/surveys/
    that contain a survey.yaml (C31 §1.1 — a DIRECTORY LISTING, not content parsing; the survey.yaml
    presence check is a stat, not a load). Sorted so the order is deterministic across platforms
    (the CI OS-portability tripwire — an unsorted os.listdir differs Linux vs Windows)."""
    if surveys_live is None:
        return []
    root = surveys_live / "surveys"
    if not root.is_dir():
        return []
    slugs = [p.name for p in sorted(root.iterdir()) if p.is_dir() and (p / "survey.yaml").is_file()]
    return slugs


def package_root_for(surveys_live: Path, slug: str) -> Path:
    """The survey package directory in surveys-live for `slug`, THROUGH THE GATEWAY'S OWN MOUNT —
    used only for the existence/404 check and the final commit write. The slug is charset-validated
    by the caller (publish.validate_slug) before it reaches this path, so it cannot traverse. Job
    files never carry this path (the runner resolves the slug against its own mount)."""
    return surveys_live / "surveys" / slug


def make_read_job(slug: str) -> dict:
    return {"kind": "read", "slug": slug}


def make_merge_job(slug: str, patch: dict, bump: str, note: str, today: str) -> dict:
    """A merge edit-job. `bump` is the chosen kind (patch/minor/major); the runner resolves it to a
    concrete version from the current survey.yaml and enforces semver-greater (all version logic is
    runner-side, C31 §0.3). The dead explicit-version override was removed per review FIX 6."""
    return {
        "kind": "merge",
        "slug": slug,
        "patch": patch,
        "bump": bump,
        "note": note,
        "today": today,
    }


def make_history_job(slug: str) -> dict:
    """A `history` edit-job (C43 D6/S2a-2): the runner returns the READ-ONLY git log of the survey's
    package directory (version, release note, when, author). The runner OWNS the git read (record D4)
    so the gateway process issues no git verb for this; job carries only the slug."""
    return {"kind": "history", "slug": slug}


def make_collections_job() -> dict:
    """A `collections` edit-job (C43 D5-A / Stage 3a): a WHOLE-CORPUS read-only projection. The runner
    reads EVERY published survey.yaml's `collection` block (the runner is the only place YAML is
    parsed — C31 §0.1) and returns the rollup the portal shows readers (first-declarer programme
    fields) PLUS the two honesty seams the build only prints to stderr today: id near-duplicates and
    per-field divergence. Whole-corpus, so the job carries NO slug — the runner enumerates surveys-live
    from its own mount. READ-ONLY: same trust class as the history job (no git write, no mutation)."""
    return {"kind": "collections"}


def make_list_stations_job(slug: str) -> dict:
    """A list_stations edit-job: the runner enumerates the survey's EDI files (station list) + version.
    A directory listing, never a content parse — job carries only the slug."""
    return {"kind": "list_stations", "slug": slug}


def make_remove_stations_job(slug: str, filenames: list[str], bump: str, note: str,
                             today: str) -> dict:
    """A remove_stations edit-job: the runner refuses the unsafe cases, bumps the version, appends the
    release note, and validates a scratch copy WITHOUT the removed EDIs. `filenames` are bare EDI
    basenames the curator selected; the runner re-validates each against its own charset before it
    becomes a path component (it never trusts a field handed to it in a job file)."""
    return {
        "kind": "remove_stations",
        "slug": slug,
        "filenames": list(filenames),
        "bump": bump,
        "note": note,
        "today": today,
    }
