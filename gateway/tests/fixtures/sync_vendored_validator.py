#!/usr/bin/env python3
"""C35b/D3 (code-health review F7) — refresh the vendored validator from the sibling ausmt-surveys.

The F7 oracles exercise the cross-repo validator contract. On CI and fresh clones the sibling
ausmt-surveys checkout is absent, so those oracles resolve to the VENDORED copy
(gateway/tests/fixtures/vendored_validation/validate_survey.py) instead of skipping. This script keeps
that vendored copy honest — the same generate-and-assert pattern contract/generate.py already owns:

  python gateway/tests/fixtures/sync_vendored_validator.py --write
      Copy the sibling's _validation/validate_survey.py over the vendored copy and rewrite the PIN
      (sha256 + the sibling's current commit). Run this when the sibling validator changes.

  python gateway/tests/fixtures/sync_vendored_validator.py --check
      Exit 1 if the vendored copy's sha256 disagrees with the PIN (drift INSIDE this monorepo — an
      accidental hand-edit of the vendored copy). This is what test_vendored_validator.py asserts too;
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
PIN = HERE / "vendored_validation" / "PIN"
# The sibling ausmt-surveys checkout, beside the monorepo root: repo-root is parents[3] of this file
# (fixtures -> tests -> gateway -> repo root), and the sibling sits next to it.
SIBLING_VALIDATION = HERE.parents[3] / "ausmt-surveys" / "_validation"
SIBLING_VALIDATOR = SIBLING_VALIDATION / "validate_survey.py"


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


def _pin_text(commit: str, sha: str) -> str:
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
        "# This PIN records the exact bytes vendored and where they came from. gateway/tests/\n"
        "# test_vendored_validator.py asserts the vendored file's sha256 == the sha256 below, so any drift\n"
        "# INSIDE this monorepo (an accidental edit to the vendored copy) fails loudly. To REFRESH from a newer\n"
        "# sibling, run gateway/tests/fixtures/sync_vendored_validator.py (it rewrites this PIN).\n"
        "#\n"
        "# The sha256 is of the LF-normalized bytes: the monorepo's `.gitattributes` (`* text=auto eol=lf`)\n"
        "# stores + checks out this file as LF on EVERY platform, and production runs the sibling's LF blob, so\n"
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
    )


def _sibling_commit() -> str:
    """The sibling ausmt-surveys HEAD commit (full sha), via git. Only called under --write."""
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(SIBLING_VALIDATION.parent),
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def do_write() -> int:
    if not SIBLING_VALIDATOR.is_file():
        print(f"sync FAILED: sibling validator not present at {SIBLING_VALIDATOR} — nothing to sync "
              "from (run this on a dev box with ausmt-surveys checked out beside the monorepo).")
        return 1
    # Normalize to LF before writing/pinning: the monorepo's `* text=auto eol=lf` stores + checks out
    # this file as LF everywhere, and production runs the sibling's LF blob. On a Windows dev box the
    # sibling checks out CRLF, so pinning the raw bytes would record a sha a fresh (LF) checkout never
    # matches. Writing LF here makes the vendored copy, the committed blob, and the PIN all agree.
    lf_bytes = SIBLING_VALIDATOR.read_bytes().replace(b"\r\n", b"\n")
    VENDORED.write_bytes(lf_bytes)
    sha = _sha256(VENDORED)
    commit = _sibling_commit()
    PIN.write_text(_pin_text(commit, sha), encoding="utf-8", newline="\n")
    print(f"synced vendored validator (LF-normalized): sha256={sha} source_commit={commit}")
    return 0


def do_check() -> int:
    if not VENDORED.is_file():
        print(f"check FAILED: vendored validator missing at {VENDORED}")
        return 1
    pin = read_pin()
    actual = _sha256(VENDORED)
    if actual != pin.get("sha256"):
        print(f"check FAILED: vendored validator drift — file sha256 {actual} != PIN "
              f"{pin.get('sha256')}. The vendored copy was edited without re-pinning; run --write from "
              "a dev box, or revert the edit.")
        return 1
    print(f"check OK: vendored validator matches PIN (sha256={actual}).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true",
                       help="copy the sibling validator over the vendored copy + rewrite the PIN")
    group.add_argument("--check", action="store_true",
                       help="exit 1 if the vendored copy's sha256 disagrees with the PIN")
    args = parser.parse_args(argv)
    if args.write:
        return do_write()
    return do_check()


if __name__ == "__main__":
    raise SystemExit(main())
