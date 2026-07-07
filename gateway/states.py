"""The submission state machine (design C10 §2, extended by C11 §1). This module is data only —
no I/O — so the legal-transition set is one auditable table that both the DB layer and the property
test read.

    RECEIVED --clamd hit--> REJECTED_AV
    RECEIVED --clamd clean--> SCANNED --job--> VALIDATED
                                 \\--(fail paths)--> QUARANTINED
    clamd unreachable => stays RECEIVED

    C11 curator half (VALIDATED stops being terminal; v2 publish = commit-and-push ONLY, no build):
    VALIDATED --curator Approve--> PUBLISHING --git commit+push OK--> PUBLISHED (committed, not served)
    VALIDATED --curator Return--> RETURNED
    VALIDATED --curator Reject--> REJECTED
    PUBLISHING --(preflight/stage/commit/merge/push fail or crash)--> PUBLISH_FAILED
    PUBLISH_FAILED --curator retry--> PUBLISHING

Terminal states never transition out. Any transition not in ALLOWED is a bug; db.transition()
refuses it rather than writing a row, so an illegal move cannot enter the audit log.
"""
from __future__ import annotations

RECEIVED = "RECEIVED"
SCANNED = "SCANNED"
VALIDATED = "VALIDATED"
QUARANTINED = "QUARANTINED"
REJECTED_AV = "REJECTED_AV"

# C11 curator states (design §1).
RETURNED = "RETURNED"
REJECTED = "REJECTED"
PUBLISHING = "PUBLISHING"
PUBLISHED = "PUBLISHED"
PUBLISH_FAILED = "PUBLISH_FAILED"

ALL_STATES: frozenset[str] = frozenset({
    RECEIVED, SCANNED, VALIDATED, QUARANTINED, REJECTED_AV,
    RETURNED, REJECTED, PUBLISHING, PUBLISHED, PUBLISH_FAILED,
})

# Terminal = the submission is done advancing. VALIDATED is NO LONGER terminal (C11 §1 — curator
# actions reopen it). PUBLISHING/PUBLISH_FAILED are transient/recoverable working states, not
# terminal. RETURNED is terminal FOR THIS SUBMISSION (design §1: a revision is a fresh upload, which
# keeps the audit trail append-only) — the submitter cannot silently mutate a returned package.
TERMINAL: frozenset[str] = frozenset({QUARANTINED, REJECTED_AV, RETURNED, REJECTED, PUBLISHED})

# The ONLY legal moves. Note RECEIVED->RECEIVED is absent: a clamd-down hold is NOT a transition
# (no state change, no audit row) — the row simply stays put until the poll loop retries. IN_REVIEW
# (design §1, optional single-curator claim) is deliberately NOT implemented — the demo is
# single-curator, so the publish lock (publish.py) is the only concurrency guard needed and the
# extra state would be dead weight in the audit trail.
ALLOWED: frozenset[tuple[str, str]] = frozenset({
    (RECEIVED, SCANNED),
    (RECEIVED, REJECTED_AV),
    (SCANNED, VALIDATED),
    (SCANNED, QUARANTINED),
    # C11 curator transitions (design §1).
    (VALIDATED, PUBLISHING),
    (VALIDATED, RETURNED),
    (VALIDATED, REJECTED),
    (PUBLISHING, PUBLISHED),
    (PUBLISHING, PUBLISH_FAILED),
    (PUBLISH_FAILED, PUBLISHING),
})

# The states the curator queue lists (design §3): actionable work, newest first.
QUEUE_STATES: tuple[str, ...] = (VALIDATED, RETURNED, PUBLISH_FAILED)


def is_terminal(state: str) -> bool:
    return state in TERMINAL


def is_legal(from_state: str, to_state: str) -> bool:
    return (from_state, to_state) in ALLOWED
