"""RFC 6238 TOTP — the workbench's destructive-op second factor (C41 D2 owner amendment, 2026-07-11).

STDLIB ONLY, by design (C41: "the TOTP is stdlib by design"): hmac / hashlib / struct / base64 /
time / secrets — no new dependency. TOTP is RFC 6238 (HOTP-over-time, RFC 4226), SHA-1, 30-second
steps, a ±1-step verify window for box clock skew, per-curator secret.

The threat this closes (D2): the typed slug protects against a mistaken click; the second factor
protects against a STOLEN curator session — a different and worse threat. Because the secret lives
only in the gateway sqlite (never git, WAL-safe backed up), and verification is stdlib arithmetic,
the box needs no egress (the 2026-07-11 DNS-outage failure mode would not have locked deletion out —
an emailed code would have).

PURE FUNCTIONS: this module holds no state. Enrolment storage (the per-curator secret + the
replay-guard `last_used_step`) lives in gateway.db; the fail-closed verification POLICY (enrolled?
current? replayed? rate-limited?) lives in the route. This module only does the RFC arithmetic:
generate a secret, compute the code at a counter, and verify a presented code against the ±window
around `now`, returning the MATCHED STEP (so the caller can enforce single-use via last_used_step).

House posture: the code comparison is constant-time (hmac.compare_digest) so verification leaks no
timing oracle on how many digits matched; a malformed code is REJECTED (returns None), never raised.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time

# RFC 6238 defaults. SHA-1 is the RFC 6238 baseline and what every authenticator app (Google
# Authenticator, Aegis, 1Password, …) uses for a bare otpauth:// URI without an explicit algorithm —
# so a stdlib-only enrolment interoperates with the curator's phone with zero extra config.
_DIGITS = 6
_STEP_S = 30
_SECRET_BYTES = 20  # 160-bit secret == the RFC 6238 SHA-1 test-vector key length; ample entropy.


def generate_secret(*, nbytes: int = _SECRET_BYTES) -> str:
    """A fresh per-curator secret as an UNPADDED uppercase base32 string (the authenticator-app
    manual-entry format). `secrets.token_bytes` is the CSPRNG; base32 (RFC 4648) is what otpauth://
    and every authenticator expect. Padding `=` is stripped for a clean copy/paste — verify() re-pads
    on decode, so a stripped or user-typed (spaces, lowercase) secret still resolves."""
    raw = secrets.token_bytes(nbytes)
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def _decode_secret(secret: str) -> bytes:
    """Decode a base32 secret tolerantly: uppercase, strip spaces/padding the user or a URI may carry,
    then re-pad to a multiple of 8 so b32decode accepts it. Raises binascii.Error / ValueError on a
    genuinely malformed secret — the caller treats an undecodable secret as 'no valid enrolment'."""
    cleaned = secret.strip().replace(" ", "").upper()
    pad = (-len(cleaned)) % 8
    return base64.b32decode(cleaned + ("=" * pad))


def current_step(now: float | None = None, *, step_s: int = _STEP_S) -> int:
    """The RFC 6238 time-step counter T = floor(unix_time / step_s) (T0 = 0). Integer, monotone
    non-decreasing — the value the DB stores as last_used_step so a code can never be replayed within
    or across its validity window (a later deletion needs a step STRICTLY GREATER than the last used)."""
    unix = time.time() if now is None else now
    return int(unix) // step_s


def code_at(secret: str, counter: int, *, digits: int = _DIGITS) -> str:
    """HOTP(K, counter) (RFC 4226 §5.3): HMAC-SHA1 of the 8-byte big-endian counter under the secret,
    dynamic-truncated to `digits` decimal digits, zero-padded. TOTP is this with counter == the
    time-step. A negative counter is clamped to 0 (a ±window at step 0 must not pack a negative int)."""
    key = _decode_secret(secret)
    msg = struct.pack(">Q", max(counter, 0))
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % (10 ** digits)).zfill(digits)


def verify(code: str, secret: str, now: float | None = None, *, window: int = 1,
           digits: int = _DIGITS, step_s: int = _STEP_S) -> int | None:
    """Verify a presented `code` against the secret over [step-window, step+window] around `now`.
    Returns the MATCHED STEP (an int the caller compares to last_used_step for single-use/replay
    enforcement), or None if the code matches no step in the window OR is malformed.

    ±1 step (30 s) is the box clock-skew tolerance (D2). The comparison is constant-time
    (hmac.compare_digest) so no timing oracle reveals how close a wrong guess was. A malformed code
    (wrong length, non-digit, or an undecodable secret) is a clean None — never an exception — so the
    route returns a uniform 'wrong code' with nothing staged. On a match at multiple steps (cannot
    happen for distinct HOTP outputs, but defensive) the HIGHEST matching step is returned so the
    replay guard advances maximally."""
    presented = (code or "").strip().replace(" ", "")
    if len(presented) != digits or not presented.isdigit():
        return None
    try:
        step = current_step(now, step_s=step_s)
        matched: int | None = None
        # Walk low→high so the highest matching step wins (advances last_used_step maximally).
        for candidate in range(step - window, step + window + 1):
            if candidate < 0:
                continue
            expected = code_at(secret, candidate, digits=digits)
            if hmac.compare_digest(expected, presented):
                matched = candidate
        return matched
    except (ValueError, TypeError):
        # An undecodable secret (corrupt DB row) => treat as no match, fail closed. binascii.Error is
        # a ValueError subclass, so this catches a malformed base32 secret too.
        return None


def otpauth_uri(secret: str, *, account: str, issuer: str = "AusMT",
                digits: int = _DIGITS, step_s: int = _STEP_S) -> str:
    """The otpauth://totp/ provisioning URI (Key Uri Format) for MANUAL authenticator entry — no QR
    image dependency (D2: single-digit curator population; a QR needs an image lib the gateway does
    not carry). Issuer + account are percent-encoded; the secret is the bare base32. Algorithm/digits/
    period are stated explicitly so an app that does not assume the SHA-1/6/30 defaults still matches."""
    from urllib.parse import quote

    label = f"{quote(issuer)}:{quote(account)}"
    params = (f"secret={secret}&issuer={quote(issuer)}"
              f"&algorithm=SHA1&digits={digits}&period={step_s}")
    return f"otpauth://totp/{label}?{params}"
