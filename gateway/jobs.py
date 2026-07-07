"""Job protocol over the shared jobs/ directory (design §5). Crash-only: every write is tmp+rename
so a reader never sees a half-written file, and a claim is an atomic same-fs rename (the lock).

Layout under jobs/:  pending/<id>.json  ->  running/<id>.json  ->  done/<id>.json
The gateway WRITES pending files and INGESTS done files. The runner claims pending->running and
writes done. No PII crosses this boundary — a pending job carries only ids and paths (house rule).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

# done-file outcomes (design §5.4). Anything else is treated as a malformed done-file and ignored
# with a log line (design §8 forged/unknown-done-file case), never advancing state.
OUTCOME_VALIDATED = "validated"
OUTCOME_QUARANTINED = "quarantined"
_VALID_OUTCOMES = frozenset({OUTCOME_VALIDATED, OUTCOME_QUARANTINED})


def ensure_dirs(jobs_dir: Path) -> None:
    for sub in ("pending", "running", "done"):
        (jobs_dir / sub).mkdir(parents=True, exist_ok=True)


def _atomic_write_json(path: Path, obj: dict) -> None:
    """tmp+fsync+rename so a partially-written job file is never visible to the peer. The tmp name
    is peer-invisible (it is not <id>.json) so a claim/ingest scan never races a half-written file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)


def write_pending(jobs_dir: Path, submission_id: str, zip_path: Path, quarantine_dir: Path) -> Path:
    """Queue a validate+preview job. Body is ids/paths only — NO PII (design §5)."""
    ensure_dirs(jobs_dir)
    body = {
        "submission_id": submission_id,
        "zip_path": str(zip_path),
        "quarantine_dir": str(quarantine_dir),
    }
    dest = jobs_dir / "pending" / f"{submission_id}.json"
    _atomic_write_json(dest, body)
    return dest


@dataclass(frozen=True)
class DoneFile:
    submission_id: str
    outcome: str
    reason: str
    report_refs: dict


def read_done(path: Path) -> DoneFile | None:
    """Parse a done-file. Returns None (caller logs + ignores, never transitions) if the file is
    unreadable, not JSON, or carries an outcome outside the known set — a forged/corrupt done-file
    must not be able to drive a state change (design §8)."""
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    sid = obj.get("submission_id")
    outcome = obj.get("outcome")
    if not isinstance(sid, str) or outcome not in _VALID_OUTCOMES:
        return None
    reason = obj.get("reason", "")
    refs = obj.get("report_refs", {})
    if not isinstance(reason, str) or not isinstance(refs, dict):
        return None
    return DoneFile(submission_id=sid, outcome=outcome, reason=reason, report_refs=refs)
