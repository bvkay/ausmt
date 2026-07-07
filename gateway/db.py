"""SQLite index for submissions (design §2). Directories are ground truth; this DB is the queryable
index and the audit log. WAL mode; the GATEWAY PROCESS IS THE ONLY WRITER (house rule — the runner
never touches the DB; it writes done-files that the gateway's poll loop ingests).

This is the ONLY place submitter PII (name/email/orcid) is stored. The PII grep test (design §8)
proves it appears nowhere else in the gw/ tree. transition() is the single mutation path for state:
it refuses illegal moves (states.ALLOWED) so no illegal transition can ever reach the audit log,
and it writes the transitions row in the SAME connection/commit as the state update so a state
change without its audit row is impossible.
"""
from __future__ import annotations

import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import states

# ULID would need a dep; a 26-char Crockford-base32 of (48-bit time + 80-bit random) is ULID-shaped
# and stdlib-only. The id is NOT a secret (the token is — design §2/§3); it is sortable-ish by the
# time prefix, which is all the design asks of it.
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


_ID_CHARS = frozenset(_CROCKFORD)


def new_id(now_ms: int | None = None) -> str:
    ms = int(time.time() * 1000) if now_ms is None else now_ms
    rand = secrets.randbits(80)
    value = (ms << 80) | rand
    out = []
    for _ in range(26):
        out.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(out))


def is_valid_id(value: str) -> bool:
    """True only for a 26-char string drawn entirely from the Crockford-base32 id charset (design
    C11 §3). Because that charset contains NO path separators, dots, or spaces, a valid id can never
    form `..`, an absolute path, or a traversal component — this is the load-bearing guard the
    curator/preview routes apply BEFORE any id reaches a filesystem path or a git branch name."""
    return len(value) == 26 and all(c in _ID_CHARS for c in value)


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass(frozen=True)
class Submission:
    id: str
    slug: str | None
    state: str
    created_utc: str
    updated_utc: str
    zip_sha256: str
    zip_bytes: int
    submitter_name: str
    submitter_email: str
    submitter_orcid: str | None
    token_hash: str


class IllegalTransition(Exception):
    """Raised when transition() is asked for a move not in states.ALLOWED. Surfaced (not swallowed)
    so a programming error is loud; the row and audit log are left untouched."""


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the DB is touched from the poll-loop task on the event-loop thread
        # AND from the status route, which runs in Starlette's threadpool (declared `def` so a burst
        # of GET /status does not block the loop — review #9). There is still exactly ONE writer
        # process. `_lock` serialises access across those threads (sqlite connections are not safe
        # for concurrent use even with check_same_thread=False); it is an RLock so a method that
        # calls another locked method (e.g. transition -> get) does not deadlock. A short busy
        # timeout covers the WAL reader/writer overlap.
        self._conn = sqlite3.connect(str(path), check_same_thread=False, timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS submissions (
                id TEXT PRIMARY KEY,
                slug TEXT,
                state TEXT NOT NULL,
                created_utc TEXT NOT NULL,
                updated_utc TEXT NOT NULL,
                zip_sha256 TEXT NOT NULL,
                zip_bytes INTEGER NOT NULL,
                submitter_name TEXT NOT NULL,
                submitter_email TEXT NOT NULL,
                submitter_orcid TEXT,
                token_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS transitions (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                submission_id TEXT NOT NULL REFERENCES submissions(id),
                from_state TEXT,
                to_state TEXT NOT NULL,
                actor TEXT NOT NULL,
                ts_utc TEXT NOT NULL,
                reason TEXT,
                report_ref TEXT
            );
            CREATE TABLE IF NOT EXISTS curator_sessions (
                session_hash TEXT PRIMARY KEY,
                curator_name TEXT NOT NULL,
                created_utc TEXT NOT NULL,
                expires_utc TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_transitions_sub ON transitions(submission_id);
            CREATE INDEX IF NOT EXISTS ix_submissions_token ON submissions(token_hash);
            CREATE INDEX IF NOT EXISTS ix_submissions_sha ON submissions(zip_sha256);
            """
        )
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---- inserts / lookups -------------------------------------------------------------------

    def insert_submission(
        self,
        *,
        submission_id: str,
        zip_sha256: str,
        zip_bytes: int,
        submitter_name: str,
        submitter_email: str,
        submitter_orcid: str | None,
        token_hash: str,
        actor: str = "gateway",
    ) -> None:
        """Insert a new RECEIVED row plus its opening audit transition (from_state NULL). Both in
        one transaction: a submission without an audit trail cannot exist."""
        now = _utc_now()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO submissions (id, slug, state, created_utc, updated_utc, zip_sha256, "
                "zip_bytes, submitter_name, submitter_email, submitter_orcid, token_hash) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (submission_id, None, states.RECEIVED, now, now, zip_sha256, zip_bytes,
                 submitter_name, submitter_email, submitter_orcid, token_hash),
            )
            self._conn.execute(
                "INSERT INTO transitions (submission_id, from_state, to_state, actor, ts_utc, reason) "
                "VALUES (?,?,?,?,?,?)",
                (submission_id, None, states.RECEIVED, actor, now, "upload received"),
            )

    def get(self, submission_id: str) -> Submission | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM submissions WHERE id = ?", (submission_id,)
            ).fetchone()
        return self._row_to_submission(row) if row else None

    def get_by_token_hash(self, token_hash: str) -> Submission | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM submissions WHERE token_hash = ?", (token_hash,)
            ).fetchone()
        return self._row_to_submission(row) if row else None

    def find_active_by_sha(self, zip_sha256: str) -> Submission | None:
        """A non-terminal submission with the same zip bytes (duplicate-content 409, design §4.4)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM submissions WHERE zip_sha256 = ?", (zip_sha256,)
            ).fetchall()
        for row in rows:
            sub = self._row_to_submission(row)
            if not states.is_terminal(sub.state):
                return sub
        return None

    def count_inflight(self) -> int:
        placeholders = ",".join("?" * len(states.TERMINAL))
        with self._lock:
            row = self._conn.execute(
                f"SELECT COUNT(*) AS n FROM submissions WHERE state NOT IN ({placeholders})",
                tuple(states.TERMINAL),
            ).fetchone()
        return int(row["n"])

    def count_today(self, day_prefix: str) -> int:
        """Submissions created on the given UTC day (YYYY-MM-DD prefix) for the per-day cap. Not
        per-key: C10 has a single submit key, so the daily cap is effectively global — the design's
        per-key wording collapses to this until multi-key issuance (C11+)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM submissions WHERE created_utc LIKE ?",
                (day_prefix + "%",),
            ).fetchone()
        return int(row["n"])

    def ids_in_state(self, state: str) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM submissions WHERE state = ?", (state,)
            ).fetchall()
        return [r["id"] for r in rows]

    def transitions_for(self, submission_id: str) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(
                "SELECT * FROM transitions WHERE submission_id = ? ORDER BY seq", (submission_id,)
            ).fetchall())

    def queue(self, states_wanted: tuple[str, ...]) -> list[Submission]:
        """Submissions in any of `states_wanted`, newest first (design §3 curator queue). ORDER BY
        the id descending: the id is time-prefixed (ULID-shaped), so descending id == newest first
        without a separate sort key."""
        placeholders = ",".join("?" * len(states_wanted))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM submissions WHERE state IN ({placeholders}) ORDER BY id DESC",
                tuple(states_wanted),
            ).fetchall()
        return [self._row_to_submission(r) for r in rows]

    # ---- curator sessions (C11 §2). Server-side store; the raw token lives only in the cookie. ----

    def create_session(self, session_hash: str, curator_name: str, ttl_s: int) -> None:
        """Store a new session row keyed by the sha256 of the raw token (mirrors token_hash: the raw
        secret is NEVER stored). Absolute expiry (design §6 — not sliding): created + ttl_s."""
        now = time.time()
        created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        expires = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + ttl_s))
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO curator_sessions (session_hash, curator_name, created_utc, expires_utc) "
                "VALUES (?,?,?,?)",
                (session_hash, curator_name, created, expires),
            )

    def get_session(self, session_hash: str) -> tuple[str, str] | None:
        """Return (curator_name, expires_utc) for a session, or None if unknown. Expiry is enforced
        by the CALLER against a clock it controls (testable), so this is a pure lookup."""
        with self._lock:
            row = self._conn.execute(
                "SELECT curator_name, expires_utc FROM curator_sessions WHERE session_hash = ?",
                (session_hash,),
            ).fetchone()
        return (row["curator_name"], row["expires_utc"]) if row else None

    def delete_session(self, session_hash: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM curator_sessions WHERE session_hash = ?", (session_hash,))

    def purge_expired_sessions(self, now_utc: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM curator_sessions WHERE expires_utc <= ?", (now_utc,))

    # ---- the single state-mutation path --------------------------------------------------------

    def transition(
        self,
        submission_id: str,
        to_state: str,
        *,
        actor: str,
        reason: str,
        report_ref: str | None = None,
        slug: str | None = None,
    ) -> None:
        """Move a submission to `to_state`, writing the audit row in the same commit. Refuses any
        move not in states.ALLOWED (raises IllegalTransition) BEFORE writing anything."""
        # Hold the lock across the read-check-then-write so a concurrent transition (or the status
        # route reading) cannot interleave between the legality check and the update.
        with self._lock:
            sub = self.get(submission_id)
            if sub is None:
                raise IllegalTransition(f"no such submission {submission_id!r}")
            if not states.is_legal(sub.state, to_state):
                raise IllegalTransition(
                    f"illegal transition {sub.state} -> {to_state} for {submission_id!r}")
            now = _utc_now()
            with self._conn:
                if slug is not None:
                    self._conn.execute(
                        "UPDATE submissions SET state=?, updated_utc=?, slug=? WHERE id=?",
                        (to_state, now, slug, submission_id),
                    )
                else:
                    self._conn.execute(
                        "UPDATE submissions SET state=?, updated_utc=? WHERE id=?",
                        (to_state, now, submission_id),
                    )
                self._conn.execute(
                    "INSERT INTO transitions (submission_id, from_state, to_state, actor, ts_utc, reason, report_ref) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (submission_id, sub.state, to_state, actor, now, reason, report_ref),
                )

    @staticmethod
    def _row_to_submission(row: sqlite3.Row) -> Submission:
        return Submission(
            id=row["id"], slug=row["slug"], state=row["state"], created_utc=row["created_utc"],
            updated_utc=row["updated_utc"], zip_sha256=row["zip_sha256"], zip_bytes=row["zip_bytes"],
            submitter_name=row["submitter_name"], submitter_email=row["submitter_email"],
            submitter_orcid=row["submitter_orcid"], token_hash=row["token_hash"],
        )
