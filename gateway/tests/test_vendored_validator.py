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
from pathlib import Path

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_SYNC = _FIXTURES / "sync_vendored_validator.py"


def _load_sync():
    """Import the sync script as a module (it lives outside any package)."""
    spec = importlib.util.spec_from_file_location("sync_vendored_validator", _SYNC)
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
