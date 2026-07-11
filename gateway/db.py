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
from collections.abc import Callable
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
class UploaderKey:
    """One issued uploader key (schema v2; `note` added in v3). key_sha256 is the ONLY copy of the
    secret; the plaintext is shown once at creation and never stored. A revoked key keeps its row
    (audit trail); active == revoked_utc IS NULL.

    `note` (schema v3, C43 D7): a free-text curator annotation (who the key is for, expiry intent).
    PII CONTAINMENT (D2.5): like every other column here it lives ONLY in this sqlite DB — it never
    enters a git-bound artifact (survey.yaml, a commit message, the publication ledger). A grep test
    pins its absence from the git-bound tree."""
    id: int
    name: str
    email: str | None
    key_sha256: str
    created_utc: str
    created_by: str
    revoked_utc: str | None
    revoked_by: str | None
    last_used_utc: str | None
    note: str | None = None

    @property
    def active(self) -> bool:
        return self.revoked_utc is None


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


class SchemaTooNew(Exception):
    """Raised when a DB was written by a NEWER build than this one (user_version > SCHEMA_VERSION).
    Fail-closed: an old binary must not silently open a forward-migrated DB and corrupt it."""


# Schema version, stamped in the DB header (PRAGMA user_version). v1 == the CREATE TABLE baseline in
# _init_schema. _MIGRATIONS holds (target_version, apply(conn)) steps for v2+; applied in order in one
# transaction.


def _migrate_v2_uploader_keys(conn: sqlite3.Connection) -> None:
    """v2 (feat/uploader-key-management): curator-managed uploader keys move the single shared
    AUSMT_SUBMIT_KEY out of env-only into the DB. Each row is ONE issued key: only its sha256 is
    stored (the plaintext is shown once at creation, never retrievable), plus who/when it was created
    and — when applicable — who/when it was revoked. A revoked row is NEVER deleted (audit trail; the
    created_by/revoked_by columns ARE the audit record for this table, mirroring how the git history
    is the audit record for C31 edits — no submissions-schema change, no separate audit table).
    IF NOT EXISTS so a re-run on a partially-migrated DB is idempotent."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS uploader_keys (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            email TEXT,
            key_sha256 TEXT NOT NULL UNIQUE,
            created_utc TEXT NOT NULL,
            created_by TEXT NOT NULL,
            revoked_utc TEXT,
            revoked_by TEXT,
            last_used_utc TEXT
        )
        """
    )


def _migrate_v3_uploader_key_note(conn: sqlite3.Connection) -> None:
    """v3 (C43 D7): add a free-text `note` column to uploader_keys — a curator annotation (who the key
    is for, expiry intent). ADDITIVE-ONLY (the C43 lane invariant): a single `ALTER TABLE ... ADD
    COLUMN note TEXT`, which SQLite applies without rewriting the table and which defaults every
    existing row's note to NULL (rendered as "—"). No existing column is touched, no data migrated.

    Idempotency: unlike v2's `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ADD COLUMN` has no IF NOT
    EXISTS form, so a re-run on an already-migrated DB would raise "duplicate column name". The
    version stamp makes a re-run impossible in the normal path (a v3 DB reads user_version 3 and
    _migrate returns before applying anything), but this guard makes the step itself idempotent for
    the belt-and-braces partial-migration case v2's docstring calls out."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(uploader_keys)").fetchall()}
    if "note" not in cols:
        conn.execute("ALTER TABLE uploader_keys ADD COLUMN note TEXT")


SCHEMA_VERSION = 3
_MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (2, _migrate_v2_uploader_keys),
    (3, _migrate_v3_uploader_key_note),
]


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
        self._migrate()

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

    def _migrate(self) -> None:
        """Bring the DB header to SCHEMA_VERSION. A fresh or legacy-unstamped DB reads user_version 0
        (the _init_schema baseline == v1); we run every migration with target > current, in order, in
        one transaction, then stamp. A DB from a NEWER build (user_version > SCHEMA_VERSION) is refused
        (SchemaTooNew) rather than opened blind — forward-compat fail-closed."""
        with self._lock:
            current = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
            if current > SCHEMA_VERSION:
                raise SchemaTooNew(
                    f"DB {self.path} is at schema {current}; this build knows only {SCHEMA_VERSION}")
            if current >= SCHEMA_VERSION:
                return
            with self._conn:
                for target, apply in _MIGRATIONS:
                    if current < target <= SCHEMA_VERSION:
                        apply(self._conn)
                # PRAGMA user_version does not accept a bound parameter; SCHEMA_VERSION is a trusted int.
                self._conn.execute(f"PRAGMA user_version={int(SCHEMA_VERSION)}")

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
        uploader_name: str | None = None,
    ) -> None:
        """Insert a new RECEIVED row plus its opening audit transition (from_state NULL). Both in
        one transaction: a submission without an audit trail cannot exist.

        `uploader_name`, when a DB uploader key (schema v2) authenticated the submit, is recorded on
        the opening transition's reason so the audit trail attributes the upload to the named uploader
        (mirroring how submitter_name is captured) — no submissions-schema column is added for it. The
        env-bootstrap key path passes None (unchanged 'upload received')."""
        now = _utc_now()
        reason = "upload received"
        if uploader_name:
            reason = f"upload received (uploader:{uploader_name})"
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
                (submission_id, None, states.RECEIVED, actor, now, reason),
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

    # ---- uploader keys (schema v2 — curator-managed submit keys) --------------------------------

    def create_uploader_key(self, *, name: str, email: str | None, key_sha256: str,
                            created_by: str) -> int:
        """Insert one uploader-key row and return its id. Stores ONLY the sha256 of the key (the
        plaintext is shown once by the caller and never persisted). The UNIQUE(name) constraint makes
        a duplicate name raise sqlite3.IntegrityError, which the caller turns into a clear message —
        the DB is the single source of truth for uniqueness (no read-then-insert race)."""
        now = _utc_now()
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO uploader_keys (name, email, key_sha256, created_utc, created_by) "
                "VALUES (?,?,?,?,?)",
                (name, email, key_sha256, now, created_by),
            )
            return int(cur.lastrowid)

    def get_active_uploader_key_by_hash(self, key_sha256: str) -> UploaderKey | None:
        """Return the ACTIVE (revoked_utc IS NULL) uploader-key row whose key_sha256 matches, else
        None. The submit-auth lookup: a revoked or unknown key resolves to None so the caller returns
        the same 401 as a wrong env key (no oracle for which case it was)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM uploader_keys WHERE key_sha256 = ? AND revoked_utc IS NULL",
                (key_sha256,),
            ).fetchone()
        return self._row_to_uploader_key(row) if row else None

    def stamp_uploader_key_used(self, key_id: int) -> None:
        """Record last_used_utc = now on a successful DB-key submit (best-effort audit; a failure here
        must never fail the submit — the caller does not raise on it)."""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE uploader_keys SET last_used_utc = ? WHERE id = ?", (_utc_now(), key_id))

    def list_uploader_keys(self) -> list[UploaderKey]:
        """All uploader keys, active and revoked, newest first — the curator list page (revoked rows
        stay for the audit trail; there is no delete)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM uploader_keys ORDER BY id DESC").fetchall()
        return [self._row_to_uploader_key(r) for r in rows]

    def revoke_uploader_key(self, key_id: int, *, revoked_by: str) -> bool:
        """Set revoked_utc/revoked_by on an ACTIVE key. Returns True if a row was revoked, False if
        the id was unknown or already revoked (the WHERE guard makes a double-revoke a no-op, so the
        original revoker/time is never overwritten)."""
        now = _utc_now()
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE uploader_keys SET revoked_utc = ?, revoked_by = ? "
                "WHERE id = ? AND revoked_utc IS NULL",
                (now, revoked_by, key_id),
            )
            return cur.rowcount > 0

    def set_uploader_key_note(self, key_id: int, *, note: str) -> bool:
        """Set the free-text `note` on an ACTIVE uploader key (schema v3, C43 D7). Returns True if a
        row was updated; False for an unknown id OR a REVOKED key — record D7 rules a revoked key a
        READ-ONLY audit row, so its note is frozen at revocation time (fix-round F6, overruling the
        earlier 'editable audit context' reading; the `AND revoked_utc IS NULL` guard is the DB-level
        enforcement, belt-and-braces under the route's own state check). An empty string clears the
        note (stored as NULL so the page renders "—"). This never touches key material or the
        active/revoked state. PII containment: writes ONLY this sqlite column, never a git-bound
        path."""
        value = note.strip() or None
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE uploader_keys SET note = ? WHERE id = ? AND revoked_utc IS NULL",
                (value, key_id))
            return cur.rowcount > 0

    def get_uploader_key(self, key_id: int) -> UploaderKey | None:
        """One uploader key by id (active or revoked), else None — the route-level state check for the
        F6 revoked-immutability rule reads this before accepting a note update."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM uploader_keys WHERE id = ?", (key_id,)).fetchone()
        return self._row_to_uploader_key(row) if row else None

    def submission_counts_by_uploader(self) -> dict[str, int]:
        """Map uploader NAME -> number of submissions attributed to that key, derived from the AUDIT
        TRAIL (the opening transition's reason), never a new column. insert_submission writes the
        opening transition reason as `upload received (uploader:<name>)` for a DB-key submit (the
        env/bootstrap key writes the bare `upload received` with no uploader, so it is excluded here).
        This counts OPENING transitions (from_state IS NULL) whose reason carries an uploader tag — one
        per submission — so the tally is submissions-per-key straight from the existing audit data.

        The name is extracted from the exact reason format between `(uploader:` and the final `)`. A
        name containing `)` would be ambiguous, but uploader names are curator-chosen labels (e.g.
        `field-team-1`); the count is a best-effort operator aid, and a mis-parsed exotic name only
        mis-buckets that one key's count, never corrupts anything."""
        prefix = "upload received (uploader:"
        out: dict[str, int] = {}
        # The prefix is a fixed literal with no % or _ wildcard chars, so `prefix + "%"` is a safe
        # LIKE pattern (nothing to escape); the exact-parse below is the real filter, LIKE is only the
        # index-friendly prefilter.
        with self._lock:
            rows = self._conn.execute(
                "SELECT reason FROM transitions WHERE from_state IS NULL AND reason LIKE ?",
                (prefix + "%", ),
            ).fetchall()
        for row in rows:
            reason = row["reason"] or ""
            if reason.startswith(prefix) and reason.endswith(")"):
                name = reason[len(prefix):-1]
                out[name] = out.get(name, 0) + 1
        return out

    @staticmethod
    def _row_to_uploader_key(row: sqlite3.Row) -> UploaderKey:
        # `note` is a v3 column: guard the key access so a pre-migration row (or a test fixture built
        # against an older schema) degrades to None rather than raising a KeyError.
        keys = row.keys()
        return UploaderKey(
            id=row["id"], name=row["name"], email=row["email"], key_sha256=row["key_sha256"],
            created_utc=row["created_utc"], created_by=row["created_by"],
            revoked_utc=row["revoked_utc"], revoked_by=row["revoked_by"],
            last_used_utc=row["last_used_utc"],
            note=row["note"] if "note" in keys else None,
        )

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
