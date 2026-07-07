"""M2 (code-health review §6): the ISO 7064 MOD 11-2 ORCID checksum is reimplemented three times
(gateway/orcid.py, portal/add-survey.html, the surveys validator). This is one of the three
consumers of the SHARED vector file gateway/tests/fixtures/orcid_vectors.json — divergence in any
copy goes red. Here we drive gateway.orcid.is_valid_orcid over every vector whose `applies_to`
includes "gateway".
"""
from __future__ import annotations

import json
from pathlib import Path

from gateway.orcid import is_valid_orcid

_VECTORS = Path(__file__).resolve().parent / "fixtures" / "orcid_vectors.json"


def _load_vectors():
    data = json.loads(_VECTORS.read_text(encoding="utf-8"))
    return data["vectors"]


def test_orcid_vectors_cover_gateway():
    # FAILS IF gateway.is_valid_orcid disagrees with the shared oracle on any gateway-scoped vector.
    # This is the mutation target: flip one `valid` in the JSON (or break the checksum in orcid.py)
    # and exactly the offending vector reds. Every impl is pinned to the SAME file, so the gateway,
    # the portal JS, and the validator cannot drift apart silently.
    vectors = [v for v in _load_vectors() if "gateway" in v["applies_to"]]
    assert vectors, "no gateway-scoped ORCID vectors found — the shared file is empty or mis-scoped"
    mismatches = [(v["input"], v["valid"], is_valid_orcid(v["input"]))
                  for v in vectors if is_valid_orcid(v["input"]) != v["valid"]]
    assert not mismatches, (
        "gateway.is_valid_orcid disagrees with orcid_vectors.json (input, expected, got): "
        f"{mismatches}")


def test_shared_vectors_have_the_three_required_kinds():
    # The file must actually EXERCISE valid ids, invalid-checksum ids, and malformed inputs (a vector
    # file of only-valid or only-invalid cases would be a vacuous oracle). FAILS IF any kind is absent.
    vectors = _load_vectors()
    assert any(v["valid"] for v in vectors), "no VALID ORCID vector"
    # invalid-checksum: well-formed 19-char hyphenated shape but valid=False (distinct from malformed)
    assert any(not v["valid"] and len(v["input"]) == 19 and v["input"].count("-") == 3
               for v in vectors), "no invalid-CHECKSUM (well-formed but wrong digit) vector"
    # malformed: not the canonical shape at all
    assert any(not v["valid"] and (v["input"] == "" or "-not" in v["input"] or v["input"] == "not-an-orcid"
                                   or len(v["input"].replace("-", "")) < 16)
               for v in vectors), "no MALFORMED vector"
