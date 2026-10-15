#!/usr/bin/env python3
"""Refresh the vendored validator from the sibling ausmt-surveys.

The validator oracles exercise the cross-repo validator contract. On CI and fresh clones the sibling
ausmt-surveys checkout is absent, so those oracles resolve to the VENDORED copy
(gateway/tests/fixtures/vendored_validation/validate_survey.py) instead of skipping. This script keeps
that vendored copy honest — the same generate-and-assert pattern contract/generate.py already owns:

  python gateway/tests/fixtures/sync_vendored_validator.py --write
      Copy the sibling's _validation/validate_survey.py and _validation/run_metadata_contract.py over
      the vendored copies and rewrite the PIN (each file's sha256 + the sibling's current commit). Run
      this when either sibling file changes.

  python gateway/tests/fixtures/sync_vendored_validator.py --check
      Exit 1 if either vendored file's sha256 disagrees with the PIN (drift INSIDE this monorepo, an
      accidental hand-edit of a vendored copy). This is what test_vendored_validator.py asserts too;
      the CLI form lets a maintainer run the same gate by hand. Does NOT need the sibling.

Requires an explicit --write/--check (no-args / an unknown flag prints usage and changes nothing), so a
stray argv can never silently rewrite the pin.
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent                       # gateway/tests/fixtures
VENDORED = HERE / "vendored_validation" / "validate_survey.py"
# The validator imports this module from its own directory and FAILs any package carrying
# run-metadata.csv without it, so the two files are vendored and pinned as a pair.
VENDORED_CONTRACT = HERE / "vendored_validation" / "run_metadata_contract.py"
PIN = HERE / "vendored_validation" / "PIN"
# The sibling ausmt-surveys checkout, beside the monorepo root: repo-root is parents[3] of this file
# (fixtures -> tests -> gateway -> repo root), and the sibling sits next to it.
SIBLING_VALIDATION = HERE.parents[3] / "ausmt-surveys" / "_validation"
SIBLING_VALIDATOR = SIBLING_VALIDATION / "validate_survey.py"
SIBLING_CONTRACT = SIBLING_VALIDATION / "run_metadata_contract.py"
# (vendored copy, sibling source, PIN sha256 key) for each pinned file.
PAIRS = ((VENDORED, SIBLING_VALIDATOR, "sha256"),
         (VENDORED_CONTRACT, SIBLING_CONTRACT, "contract_sha256"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_pin(pin_path: Path = PIN) -> dict[str, str]:
    """Parse the `key: value` PIN file ('#' comments ignored)."""
    fields: dict[str, str] = {}
    for raw in pin_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            fields[key.strip()] = val.strip()
    return fields


def _pin_text(commit: str, sha: str, contract_sha: str) -> str:
    """The PIN body, byte-stable so a --write that changed nothing is a no-op diff. Header comment kept
    in sync with the committed PIN (both are the SAME contract)."""
    return (
        "# C35b/D3 (code-health review F7) — vendored validator PIN.\n"
        "#\n"
        "# validate_survey.py in this directory is a PINNED COPY of the survey-package validator that lives in\n"
        "# the SIBLING ausmt-surveys repo (_validation/validate_survey.py). The gw-runner invokes that script\n"
        "# as a subprocess in production; the F7 oracles exercise the cross-repo contract. On CI and fresh\n"
        "# clones the sibling checkout is absent, so those oracles resolve to THIS vendored copy instead of\n"
        "# skipping — the contract stays unconditionally executable.\n"
        "#\n"
        "# run_metadata_contract.py is vendored beside it from the same sibling commit: the validator imports\n"
        "# it from its own directory and FAILs any package carrying run-metadata.csv when it is absent.\n"
        "#\n"
        "# This PIN records the exact bytes vendored and where they came from. gateway/tests/\n"
        "# test_vendored_validator.py asserts each vendored file's sha256 == its sha256 below, so any drift\n"
        "# INSIDE this monorepo (an accidental edit to a vendored copy) fails loudly. To REFRESH from a newer\n"
        "# sibling, run gateway/tests/fixtures/sync_vendored_validator.py (it rewrites this PIN).\n"
        "#\n"
        "# The sha256 is of the LF-normalized bytes: the monorepo's `.gitattributes` (`* text=auto eol=lf`)\n"
        "# stores + checks out these files as LF on EVERY platform, and production runs the sibling's LF blobs, so\n"
        "# the pin must record the LF form a fresh checkout actually sees (the source checks out CRLF on a\n"
        "# Windows dev box; sync_vendored_validator.py --write normalizes to LF before pinning).\n"
        "#\n"
        "# Fields are `key: value`, one per line, '#' comments ignored.\n"
        "\n"
        "source_repo: ausmt-surveys\n"
        "source_path: _validation/validate_survey.py\n"
        f"source_commit: {commit}\n"
        "line_endings: lf\n"
        f"sha256: {sha}\n"
        "contract_source_path: _validation/run_metadata_contract.py\n"
        f"contract_sha256: {contract_sha}\n"
    )


def _sibling_commit() -> str:
    """The sibling ausmt-surveys HEAD commit (full sha), via git. Only called under --write."""
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(SIBLING_VALIDATION.parent),
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def do_write() -> int:
    missing = [str(src) for _, src, _ in PAIRS if not src.is_file()]
    if missing:
        print(f"sync FAILED: sibling file(s) not present: {', '.join(missing)}. Nothing to sync from "
              "(run this on a dev box with ausmt-surveys checked out beside the monorepo).")
        return 1
    # Normalize to LF before writing/pinning: the monorepo's `* text=auto eol=lf` stores + checks out
    # these files as LF everywhere, and production runs the sibling's LF blobs. On a Windows dev box
    # the sibling checks out CRLF, so pinning the raw bytes would record a sha a fresh (LF) checkout
    # never matches. Writing LF here makes the vendored copies, the committed blobs, and the PIN agree.
    shas = {}
    for vendored, src, key in PAIRS:
        vendored.write_bytes(src.read_bytes().replace(b"\r\n", b"\n"))
        shas[key] = _sha256(vendored)
    commit = _sibling_commit()
    PIN.write_text(_pin_text(commit, shas["sha256"], shas["contract_sha256"]), encoding="utf-8",
                   newline="\n")
    print(f"synced vendored validator pair (LF-normalized): sha256={shas['sha256']} "
          f"contract_sha256={shas['contract_sha256']} source_commit={commit}")
    return 0


def do_check() -> int:
    pin = read_pin()
    failed = False
    for vendored, _, key in PAIRS:
        if not vendored.is_file():
            print(f"check FAILED: vendored file missing at {vendored}")
            failed = True
            continue
        actual = _sha256(vendored)
        if actual != pin.get(key):
            print(f"check FAILED: vendored {vendored.name} drift: file sha256 {actual} != PIN {key} "
                  f"{pin.get(key)}. The vendored copy was edited without re-pinning; run --write from "
                  "a dev box, or revert the edit.")
            failed = True
            continue
        print(f"check OK: vendored {vendored.name} matches PIN ({key}={actual}).")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true",
                       help="copy the sibling validator pair over the vendored copies + rewrite the PIN")
    group.add_argument("--check", action="store_true",
                       help="exit 1 if either vendored file's sha256 disagrees with the PIN")
    args = parser.parse_args(argv)
    if args.write:
        return do_write()
    return do_check()


if __name__ == "__main__":
    raise SystemExit(main())
