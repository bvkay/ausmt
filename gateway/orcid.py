"""ORCID checksum — ISO 7064 MOD 11-2 over the 16 digits (design §4).

Reimplemented here, NOT imported from the validator: the gateway must not import validator code
(house rule — the gateway never parses survey content, and the validator lives in the sibling
surveys repo, unavailable to the gateway image). This is the standard ORCID check-digit algorithm
(https://support.orcid.org/hc/en-us/articles/360006897674), a self-contained ~15-line function.

ORCID is OPTIONAL on upload; when present it is checksum-validated and a bad checksum rejects the
submission. An absent ORCID is fine — this module is only consulted when the field is non-empty.
"""
from __future__ import annotations

import re

# Accepts the canonical hyphenated form and a bare 16-char form; X is the only allowed non-digit
# and only in the final position (it encodes checksum value 10).
_ORCID_RE = re.compile(r"^(\d{4})-?(\d{4})-?(\d{4})-?(\d{3})([\dX])$")


def is_valid_orcid(value: str) -> bool:
    """True iff `value` is a syntactically well-formed ORCID whose MOD 11-2 check digit matches."""
    m = _ORCID_RE.match(value.strip())
    if not m:
        return False
    digits = "".join(m.groups())  # 16 chars: 15 digits + final check char
    total = 0
    for ch in digits[:-1]:
        total = (total + int(ch)) * 2
    remainder = total % 11
    result = (12 - remainder) % 11
    check = "X" if result == 10 else str(result)
    return check == digits[-1]
