"""Uploader-key helpers (schema v2, feat/uploader-key-management). Curator-managed submit keys move
the single shared AUSMT_SUBMIT_KEY out of env-only and into the gateway's SQLite, issued and revoked
by curators through the authenticated UI — so at the NCI/facility home, where the curator has no
shell, key rotation is a UI action, not a service restart.

A key is `ausmt_up_` + secrets.token_urlsafe(32): a high-entropy random token. Only its sha256 hex
digest is ever stored (mirroring the C10 submit-token / curator-session hashing); the plaintext is
returned to the curator EXACTLY once at creation and can never be retrieved again (lost => revoke +
create a new one). Because the key is high-entropy random, sha256 is the correct one-way store — no
KDF/salt is needed (there is nothing to brute-force), and lookups compare hex digests with
hmac.compare_digest so a stored-hash comparison is constant-time.

This module is pure functions (no I/O, no DB) so the mint/hash logic is unit-testable in isolation
and shared by app.py and the tests without importing the whole app.
"""
from __future__ import annotations

import hashlib
import secrets

# The visible prefix on every issued key. Purely cosmetic/operator-facing (lets a human recognise an
# AusMT uploader key at a glance and grep for a leaked one); it is part of the secret and part of the
# bytes that are hashed, so it adds no attackable structure.
KEY_PREFIX = "ausmt_up_"


def mint_key() -> str:
    """A fresh uploader key: the prefix + 32 bytes of urlsafe base64 randomness (~256 bits). Returned
    to the curator once; only key_hash(mint_key()) is stored."""
    return KEY_PREFIX + secrets.token_urlsafe(32)


def key_hash(key: str) -> str:
    """sha256 hex digest of the key bytes — the ONLY form stored. UTF-8 encode is unambiguous for the
    urlsafe-base64 charset the key uses."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
