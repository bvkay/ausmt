"""C35b/D3 (code-health review F7): the vendored validator is a PINNED contract copy.

The F7 oracles resolve to the vendored copy (gateway/tests/fixtures/vendored_validation/
validate_survey.py) on CI and fresh clones. This file guards that copy: its sha256 must equal the PIN,
so an accidental hand-edit of the vendored copy INSIDE this monorepo fails loudly (the same
generate-and-assert discipline contract/generate.py --check owns). Refresh from a newer sibling with
gateway/tests/fixtures/sync_vendored_validator.py --write.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_SYNC = _FIXTURES / "sync_vendored_validator.py"
_VENDORED_VALIDATOR = _FIXTURES / "vendored_validation" / "validate_survey.py"
_ORCID_VECTORS = _FIXTURES / "orcid_vectors.json"


def _load_sync():
    """Import the sync script as a module (it lives outside any package)."""
    spec = importlib.util.spec_from_file_location("sync_vendored_validator", _SYNC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_vendored_validator():
    """Import the committed vendored validate_survey.py so its orcid_checksum_ok can be exercised
    against the shared ORCID vectors (M2). Stdlib+optional-yaml only — imports in the gateway env."""
    spec = importlib.util.spec_from_file_location("vendored_validate_survey", _VENDORED_VALIDATOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_vendored_validator_matches_pin():
    # FAILS IF the vendored validate_survey.py's sha256 diverges from the PIN — i.e. someone edited the
    # vendored copy without re-pinning (drift inside the monorepo). This is the mutation-proof target
    # (corrupt one byte of the vendored copy -> this test goes RED; transcript in the report).
    sync = _load_sync()
    assert sync.VENDORED.is_file(), f"vendored validator missing at {sync.VENDORED}"
    assert sync.PIN.is_file(), f"PIN missing at {sync.PIN}"
    pin = sync.read_pin()
    actual = hashlib.sha256(sync.VENDORED.read_bytes()).hexdigest()
    assert actual == pin.get("sha256"), (
        f"vendored validator sha256 {actual} != PIN {pin.get('sha256')} — the vendored copy drifted; "
        "run sync_vendored_validator.py --write from a dev box, or revert the edit.")
    # The PIN also records provenance — sane shape so a broken PIN is caught here too.
    assert pin.get("source_commit"), "PIN missing source_commit"
    assert pin.get("source_repo") == "ausmt-surveys", pin


def test_sync_check_mode_agrees():
    # The CLI --check gate (a maintainer can run it by hand) must agree with the pytest assertion: the
    # committed vendored copy is in sync, so do_check() returns 0. FAILS IF the two accounting paths
    # disagree (a check that cannot fail when the file is corrupt would be vacuous).
    sync = _load_sync()
    assert sync.do_check() == 0


def test_validator_orcid_checksum_matches_shared_vectors():
    # M2 (code-health review §6): the validator's orcid_checksum_ok is the THIRD copy of the ISO 7064
    # MOD 11-2 checksum. Drive it over every validator-scoped vector in the SHARED oracle file — the
    # same file gateway/tests/test_orcid.py and the portal jsdom test consume. FAILS IF the validator's
    # copy diverges from the shared verdicts (the exact drift M2 closes). The validator's FORMAT
    # contract differs (URL accepted, bare form rejected), so we only assert the vectors whose
    # `applies_to` includes "validator" — the canonical-hyphenated set all three impls share.
    vv = _load_vendored_validator()
    vectors = [v for v in json.loads(_ORCID_VECTORS.read_text(encoding="utf-8"))["vectors"]
               if "validator" in v["applies_to"]]
    assert vectors, "no validator-scoped ORCID vectors — the shared file is empty or mis-scoped"
    mismatches = [(v["input"], v["valid"], vv.orcid_checksum_ok(v["input"]))
                  for v in vectors if vv.orcid_checksum_ok(v["input"]) != v["valid"]]
    assert not mismatches, (
        "vendored validator orcid_checksum_ok disagrees with orcid_vectors.json "
        f"(input, expected, got): {mismatches}")
