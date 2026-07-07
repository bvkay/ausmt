"""Safe zip extraction with per-member re-checks (design §5.1, belt-and-braces). The gateway already
ran zipsafety.inspect() before queueing; the runner re-applies the same rules AT EXTRACTION so a
member that somehow slips the central-directory pass cannot land outside the target tree. Every
resolved destination is confirmed to stay under the target root before a single byte is written.

Byte accounting (design §5.1, review #10): the total extracted size and each member's extracted
size are counted from the bytes ACTUALLY READ, never trusted from the central-directory file_size —
a lying header can't make extraction write more than the caps. A per-member or total overrun aborts
the whole extraction. A deadline (review #7) is checked as bytes flow so a slow/huge extraction is
bounded even though it runs no subprocess.

stdlib zipfile only — the runner is content-blind about EDI/YAML just like the gateway; this module
only moves bytes into place under a resolved, contained path.
"""
from __future__ import annotations

import time
import zipfile
from pathlib import Path

# Import the shared central-directory rules. The runner ships the whole gateway package in the
# engine image (the Dockerfile copies gateway/ in), so this import resolves the same code the
# gateway ran — one rule set, not two that could drift.
from ..zipsafety import MAX_TOTAL_UNCOMPRESSED_FACTOR, ZipRejection, check_member

# Extraction caps, computed from the same max-upload contract the gateway enforces. The total cap is
# 4x max-upload (matching zipsafety.inspect's declared-total rule); a single member may not exceed
# the total either. These are enforced on BYTES READ, so a forged file_size cannot beat them.
_READ_CHUNK = 1024 * 1024


class UnsafeMember(Exception):
    """A member resolved outside the target root, failed a re-check, or overran the byte caps. Aborts
    the whole extraction (the package is hostile) rather than skipping the one member."""


class ExtractionTimeout(Exception):
    """Extraction ran past the job deadline (review #7). The caller quarantines with a timeout
    reason, distinct from a hostile-member abort."""


def safe_extract(zip_path: Path, target: Path, *, max_total_bytes: int | None = None,
                 deadline: float | None = None) -> None:
    """Extract `zip_path` under `target`, re-checking every member, confirming containment, and
    counting extracted bytes against a total cap (default 4x the implied max-upload from the zip's
    own declared total is not trusted — pass max_total_bytes explicitly for the hard cap; None means
    no extra cap beyond containment, used by unit tests on tiny fixtures). Raises UnsafeMember on any
    safety violation or byte overrun; ExtractionTimeout if `deadline` (time.monotonic clock) passes.
    """
    target = target.resolve()
    target.mkdir(parents=True, exist_ok=True)
    total_written = 0
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if deadline is not None and time.monotonic() > deadline:
                raise ExtractionTimeout("extraction exceeded job budget")
            try:
                check_member(info)
            except ZipRejection as rej:
                raise UnsafeMember(str(rej)) from rej

            # Containment: resolve the destination and confirm it is target or a descendant. This
            # is the load-bearing guard — check_member already rejects `..`/absolute/backslash, but
            # resolving-then-comparing catches anything those textual checks miss (e.g. an odd
            # normalisation), so extraction can NEVER write outside target.
            dest = (target / info.filename).resolve()
            if dest != target and target not in dest.parents:
                raise UnsafeMember(f"member escapes target: {info.filename!r}")

            if info.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            member_written = 0
            with zf.open(info) as src, open(dest, "wb") as out:
                while True:
                    if deadline is not None and time.monotonic() > deadline:
                        raise ExtractionTimeout("extraction exceeded job budget")
                    block = src.read(_READ_CHUNK)
                    if not block:
                        break
                    member_written += len(block)
                    total_written += len(block)
                    # Enforce caps on ACTUAL bytes read — not the central-directory file_size. A
                    # member whose real inflated size exceeds the total cap (or the whole extraction
                    # exceeding it) is a bomb regardless of what its header claimed.
                    if max_total_bytes is not None:
                        if member_written > max_total_bytes:
                            raise UnsafeMember(f"member exceeds extraction cap: {info.filename!r}")
                        if total_written > max_total_bytes:
                            raise UnsafeMember("extracted total exceeds extraction cap")
                    out.write(block)


def cap_for(max_upload_bytes: int) -> int:
    """The hard total-extraction cap (4x max-upload), matching zipsafety.inspect's declared-total
    rule so the extraction-time check and the upload-time check agree."""
    return MAX_TOTAL_UNCOMPRESSED_FACTOR * max_upload_bytes
