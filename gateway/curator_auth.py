"""Curator authentication (design §2/§6). SEPARATE credential from the submit key: a comma-separated
`name:key` list in AUSMT_CURATOR_KEYS, so every curator action is attributable to a named actor in
the audit log. Fail closed — an unset or malformed AUSMT_CURATOR_KEYS means NO curator can be
authenticated and every curator route 503s (you cannot approve anything without a configured curator
identity).

Auth is a cookie session, not a header: the curator POSTs their key once to /login and the server
sets a `Secure; HttpOnly; SameSite=Strict` cookie holding a random 32-byte token, stored sha256-
hashed in curator_sessions (the raw token is NEVER stored — mirror of the C10 submit-token pattern).
HttpOnly keeps the secret out of page JS entirely.

Because auth is a cookie, every state-changing POST carries a CSRF token: a per-session value derived
(HMAC) from the session token, embedded as a hidden field in every form and compared constant-time
server-side. GET routes are side-effect-free and need none.

Keys and session tokens are SECRETS: they are never logged (config.redacted_items drops the raw
keys) and never rendered.
"""
from __future__ import annotations

import hashlib
import hmac
import threading
import time

# Minimum curator-key length. Each configured key must clear this or the whole config is malformed
# and curator routes fail closed — a short curator key is refused, not accepted-then-weak (design
# §2/§6, mirroring the submit-key floor).
_MIN_CURATOR_KEY_LEN = 16

# Cookie + form field names. The session cookie is the ONLY place the raw session token lives.
SESSION_COOKIE = "ausmt_curator_session"
CSRF_FIELD = "csrf_token"

# A fixed domain-separation label so the CSRF token (HMAC of the session token) can never collide
# with any other use of the same secret. The session token is the HMAC key; this is the message.
_CSRF_LABEL = b"ausmt-curator-csrf-v1"


class CuratorConfigError(Exception):
    """AUSMT_CURATOR_KEYS is unset or malformed. The caller (app) turns this into a 503 on every
    curator route — fail closed (design §2). Raised at PARSE time so a bad config surfaces as a
    uniform 503, never as a partially-usable auth surface."""


def parse_curator_keys(raw: str) -> dict[str, str]:
    """Parse `name:key,name:key` into {name: key}. Raises CuratorConfigError if the string is empty,
    has no valid pair, contains a malformed pair, a duplicate name, or a too-short key. Fail closed:
    ANY malformation rejects the WHOLE config (a half-parsed key map is worse than none)."""
    if not raw or not raw.strip():
        raise CuratorConfigError("AUSMT_CURATOR_KEYS is unset")
    out: dict[str, str] = {}
    for raw_pair in raw.split(","):
        pair = raw_pair.strip()
        if not pair:
            continue
        # split on the FIRST colon: a key may itself contain ':' (token_urlsafe never does, but a
        # human-chosen key might), the NAME may not — so split once from the left on the name.
        if ":" not in pair:
            raise CuratorConfigError(f"malformed curator pair (no ':'): {pair.split(':')[0]!r}")
        name, key = pair.split(":", 1)
        name = name.strip()
        if not name:
            raise CuratorConfigError("curator pair with empty name")
        if not name.replace("-", "").replace("_", "").isalnum():
            # The name lands in the audit log as actor "curator:<name>" and in a git branch/commit
            # body — constrain it to a safe charset so a name can never smuggle markup or a path.
            raise CuratorConfigError(f"curator name has disallowed characters: {name!r}")
        if name in out:
            raise CuratorConfigError(f"duplicate curator name: {name!r}")
        if len(key) < _MIN_CURATOR_KEY_LEN:
            raise CuratorConfigError(
                f"curator key for {name!r} shorter than {_MIN_CURATOR_KEY_LEN} chars")
        # Reject a duplicate KEY VALUE too (not just a duplicate name): two curators sharing a key
        # would mis-attribute actions (match_curator returns the last-configured name for that key),
        # so an action by one would be logged as the other. Fail closed on the ambiguity.
        if key in out.values():
            raise CuratorConfigError(f"curator key for {name!r} is reused by another curator")
        out[name] = key
    if not out:
        raise CuratorConfigError("AUSMT_CURATOR_KEYS parsed to no curators")
    return out


def match_curator(keys: dict[str, str], presented_key: str) -> str | None:
    """Return the curator NAME whose configured key equals presented_key, comparing EVERY key with
    hmac.compare_digest (constant time — no early exit on the first char, so no timing oracle on
    which key matched, design §6). Returns None if none match. Presented_key is compared even when
    empty so the timing profile does not reveal 'a key was presented at all'."""
    matched: str | None = None
    for name, key in keys.items():
        # Compare ALL keys (do not break on first match) so total time does not depend on which key
        # matched or how many were checked before it.
        if hmac.compare_digest(key, presented_key):
            matched = name
    return matched


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def csrf_token_for(session_token: str) -> str:
    """Derive the per-session CSRF token as HMAC-SHA256(session_token, label). Deterministic from the
    session token, so the server re-derives it to check a form without storing a second value; an
    attacker without the (HttpOnly) session cookie cannot compute it (design §2 synchroniser token)."""
    return hmac.new(session_token.encode("utf-8"), _CSRF_LABEL, hashlib.sha256).hexdigest()


def csrf_ok(session_token: str, presented: str | None) -> bool:
    """Constant-time check that `presented` is the CSRF token for this session. A missing/empty token
    is a fail (compared against the real one so the reject is constant-time too)."""
    expected = csrf_token_for(session_token)
    return hmac.compare_digest(expected, presented or "")


class LoginRateLimiter:
    """Global (per-process) sliding-window login rate limit (design §6). No per-source trust on a
    tailnet, so the window is global: after `max_attempts` FAILED logins inside `window_s`, further
    login attempts are refused (429) until the window rolls off. A SUCCESSFUL login clears the counter.

    THREAD-SAFE: the login route is a sync `def` and runs in Starlette's threadpool, so many login
    POSTs execute concurrently. A bare blocked()->check-key->record_failure() sequence would let a
    burst of ~threadpool-size guesses all read 'not blocked' before any failure records. `evaluate()`
    runs the whole decision — blocked-check, key match, and the failure/success record — under ONE
    lock, so at most `max_attempts` wrong keys can reach the key comparison inside a window (mirrors
    db.py's lock-across-check-then-write rationale)."""

    def __init__(self, max_attempts: int, window_s: int):
        self.max_attempts = max_attempts
        self.window_s = window_s
        self._failures: list[float] = []
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_s
        self._failures = [t for t in self._failures if t > cutoff]

    def evaluate(self, keys: dict[str, str], presented_key: str,
                 now: float | None = None) -> tuple[str, str | None]:
        """Atomically: if blocked -> ('blocked', None); else match the key and, on a miss, record the
        failure -> ('denied', None); on a hit, clear the counter -> ('ok', name). The blocked check,
        the key comparison, and the record all happen under the lock so concurrent attempts cannot
        slip past the cap. Returns (outcome, curator_name)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            self._prune(now)
            if len(self._failures) >= self.max_attempts:
                return "blocked", None
            name = match_curator(keys, presented_key)
            if name is None:
                self._failures.append(now)
                return "denied", None
            self._failures = []  # a success clears the counter
            return "ok", name

    # blocked()/record_* kept for the unit tests that exercise the window mechanics directly; the
    # route uses evaluate() so the whole decision is atomic.
    def blocked(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            self._prune(now)
            return len(self._failures) >= self.max_attempts

    def record_failure(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            self._failures.append(now)
            self._prune(now)

    def record_success(self, now: float | None = None) -> None:
        with self._lock:
            self._failures = []


def is_session_expired(expires_utc: str, now_utc: str) -> bool:
    """String compare works because both are `YYYY-MM-DDTHH:MM:SSZ` (fixed-width, lexicographically
    ordered == chronologically ordered). Absolute expiry (design §6): a session past expires_utc is
    dead regardless of activity."""
    return now_utc >= expires_utc
