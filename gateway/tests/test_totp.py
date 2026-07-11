"""Unit pins for gateway.totp — the RFC 6238 destructive-op second factor (C41 D2 / T1).

Failure criterion is in each test's docstring (Invariant 10). These are PURE-FUNCTION pins: no app,
no DB, no git — just the RFC arithmetic + the window/malformed policy verify() must enforce.

The RFC 6238 Appendix B test vectors are the load-bearing correctness pin: an independent, published
oracle (not a same-author round-trip), so a subtly wrong truncation/counter-packing goes RED against
real numbers rather than agreeing with itself. Appendix B lists SHA-1/256/512; the stdlib-only module
implements SHA-1 (the authenticator-app default), so the SHA-1 column is the vector set here — 8-digit
codes with the RFC's ASCII seed "12345678901234567890".
"""
from __future__ import annotations

import base64

from gateway import totp

# RFC 6238 Appendix B seed for SHA-1: the ASCII string "12345678901234567890" (20 bytes), base32'd
# to the manual-entry secret. This is the exact key the published vectors were computed against.
_RFC_SEED_ASCII = b"12345678901234567890"
_RFC_SECRET_B32 = base64.b32encode(_RFC_SEED_ASCII).decode("ascii").rstrip("=")

# (unix_time_seconds, expected 8-digit SHA-1 TOTP) — RFC 6238 Appendix B, SHA-1 rows.
_RFC_VECTORS = [
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
]


def test_rfc6238_appendix_b_sha1_vectors():
    """code_at() at the RFC time-step reproduces every RFC 6238 Appendix B SHA-1 vector exactly.
    FAILS IF the HMAC counter packing, dynamic truncation, or modulo is wrong (an independent oracle,
    not a self-consistency check)."""
    for unix_time, expected in _RFC_VECTORS:
        step = totp.current_step(unix_time)
        got = totp.code_at(_RFC_SECRET_B32, step, digits=8)
        assert got == expected, f"t={unix_time}: got {got!r}, RFC says {expected!r}"


def test_verify_accepts_the_rfc_vectors_via_now():
    """verify() (which walks the ±window around now) accepts each RFC vector at its own timestamp and
    returns the matching step. FAILS IF the end-to-end verify path disagrees with the raw code_at
    vectors (e.g. an off-by-one in the window centring)."""
    for unix_time, expected in _RFC_VECTORS:
        step = totp.verify(expected, _RFC_SECRET_B32, unix_time, window=1, digits=8)
        assert step == totp.current_step(unix_time), f"t={unix_time}: verify returned {step!r}"


def test_generate_secret_roundtrips_and_is_high_entropy():
    """A generated secret is decodable base32 and verifies a code computed from it; two secrets differ.
    FAILS IF generate_secret emits an undecodable/short/constant secret."""
    s1 = totp.generate_secret()
    s2 = totp.generate_secret()
    assert s1 != s2, "two generated secrets collided (not random)"
    # 20 bytes -> 32 base32 chars (no padding). Decodes cleanly through the tolerant decoder.
    assert len(base64.b32decode(s1 + "=" * ((-len(s1)) % 8))) == 20
    now = 1_700_000_000
    code = totp.code_at(s1, totp.current_step(now))
    assert totp.verify(code, s1, now) == totp.current_step(now)


def test_window_edges_accept_prev_and_next_step_but_reject_two_away():
    """A code from the PREVIOUS or NEXT 30 s step verifies (±1 clock-skew tolerance, D2); a code from
    TWO steps away is REFUSED. FAILS IF the window is wider or narrower than ±1 step. This is the
    mutation-proof for the window bound: shrinking to window=0 makes the ±1 asserts RED; widening to
    window=2 makes the two-away reject RED."""
    secret = totp.generate_secret()
    now = 1_700_000_000
    step = totp.current_step(now)
    prev_code = totp.code_at(secret, step - 1)
    next_code = totp.code_at(secret, step + 1)
    two_ahead = totp.code_at(secret, step + 2)
    assert totp.verify(prev_code, secret, now, window=1) == step - 1
    assert totp.verify(next_code, secret, now, window=1) == step + 1
    assert totp.verify(two_ahead, secret, now, window=1) is None
    # window=0 (no skew tolerance) accepts ONLY the current step.
    assert totp.verify(prev_code, secret, now, window=0) is None
    assert totp.verify(totp.code_at(secret, step), secret, now, window=0) == step


def test_malformed_codes_are_rejected_not_raised():
    """A wrong-length, non-digit, empty, or None code returns None (never raises), and a correct code
    with surrounding spaces is normalised and accepted. FAILS IF a malformed code raises (which would
    500 the route instead of a clean 'wrong code' refusal), or a spaced code is rejected."""
    secret = totp.generate_secret()
    now = 1_700_000_000
    good = totp.code_at(secret, totp.current_step(now))
    for bad in ("", "12345", "1234567", "abcdef", "12 34 5", None, "12345a"):
        assert totp.verify(bad, secret, now) is None, f"malformed code accepted: {bad!r}"
    # A valid code with incidental whitespace (paste artifact) still verifies.
    spaced = good[:3] + " " + good[3:]
    assert totp.verify(spaced, secret, now) == totp.current_step(now)


def test_wrong_code_is_refused():
    """A code that is valid-shaped but not the right value returns None. FAILS IF any 6-digit string
    is accepted (a broken comparison)."""
    secret = totp.generate_secret()
    now = 1_700_000_000
    good = totp.code_at(secret, totp.current_step(now))
    # Perturb the last digit to get a definitely-wrong but well-formed code.
    wrong = good[:-1] + str((int(good[-1]) + 1) % 10)
    assert wrong != good
    assert totp.verify(wrong, secret, now) is None


def test_undecodable_secret_fails_closed():
    """verify() against a corrupt (undecodable base32) secret returns None, never raises — a damaged
    DB row must fail CLOSED (no deletion), not 500. FAILS IF a bad secret raises out of verify."""
    now = 1_700_000_000
    assert totp.verify("000000", "!!!not base32!!!", now) is None


def test_empty_or_blank_secret_fails_closed():
    """verify() against an empty or whitespace-only secret returns None (F2). An empty base32 string
    decodes to b'' — a VALID HMAC key — so without the empty-secret guard verify() would compute an
    empty-key code and MATCH it. This pin is MUTATION-PROOF: it feeds verify() the exact code an
    empty-key HMAC produces, so removing the guard in _decode_secret makes verify() return the matched
    step (not None) and this goes RED. FAILS IF an empty/blank secret can gate anything."""
    import hashlib
    import hmac
    import struct

    now = 1_700_000_000
    step = totp.current_step(now)
    # The code an empty-key (b'') HMAC would produce at this step — the vulnerability if _decode_secret
    # were to accept "" -> b''. Reconstructs the RFC 4226 truncation over the empty key.
    digest = hmac.new(b"", struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    empty_key_code = str(truncated % 1_000_000).zfill(6)   # exactly code_at()'s truncation, digits=6
    # Even THIS code (which WOULD match an empty key) is refused, proving it is the guard, not luck.
    assert totp.verify(empty_key_code, "", now) is None
    assert totp.verify(empty_key_code, "   ", now) is None
    assert totp.verify("123456", "", now) is None


def test_otpauth_uri_shape():
    """The provisioning URI carries the bare secret, the issuer/account label, and explicit
    algorithm/digits/period so a non-defaulting authenticator still matches. FAILS IF the secret is
    mangled or the SHA-1/6/30 parameters are absent."""
    secret = totp.generate_secret()
    uri = totp.otpauth_uri(secret, account="curator1", issuer="AusMT")
    assert uri.startswith("otpauth://totp/AusMT:curator1?")
    assert f"secret={secret}" in uri
    assert "algorithm=SHA1" in uri and "digits=6" in uri and "period=30" in uri
    assert "issuer=AusMT" in uri
