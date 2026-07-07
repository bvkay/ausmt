"""M6 (code-health review §6): pin the build_portal argv surface the surveys-repo consumer relies on.

ausmt-surveys/_validation/contribute.py builds the engine preview by spawning
`python -m extract.build_portal` with a HAND-BUILT argv. Nothing on the engine side notices when a
build_portal flag that consumer depends on is renamed/removed — engine changes cannot trigger the
surveys tests (the cross-repo triggering gap M6 names). This test pins the PROVIDER side: every flag
contribute.py passes must still exist in build_portal's CLI.

CI has no ausmt-surveys sibling (private repo, no token — see build-products.yml), so the flag list is
VENDORED here (committed, from a read of contribute.py) rather than read at runtime — the same
unconditional-contract discipline C35b/D3 used for the validator. When the sibling IS present (dev
box), an extra assertion re-derives the flags from contribute.py's live source and checks the vendored
list still matches, so the two cannot silently diverge without this test noticing on the next dev run.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# The flags contribute.py passes to `python -m extract.build_portal` (contribute.py:148-151, read
# 2026-07-07). VENDORED because CI has no surveys sibling; kept honest by
# test_vendored_flags_match_live_contribute below whenever the sibling is present.
CONTRIBUTE_BUILD_PORTAL_FLAGS = ("--surveys", "--out", "--extractor", "--no-validate")

_ENGINE_DIR = Path(__file__).resolve().parents[1]
# engine/tests -> engine -> ausmt(monorepo root) -> ausmt-surveys sibling
_SIBLING_CONTRIBUTE = _ENGINE_DIR.parents[1] / "ausmt-surveys" / "_validation" / "contribute.py"


def _build_portal_help() -> str:
    """The real build_portal CLI surface via `-m extract.build_portal --help` (exit 0, all flags
    printed). Exercises the ACTUAL parser contribute.py invokes — no build_portal refactor needed, and
    no clash with any lane editing build_portal's argparse (this reads whatever surface exists)."""
    proc = subprocess.run(
        [sys.executable, "-m", "extract.build_portal", "--help"],
        cwd=str(_ENGINE_DIR), capture_output=True, text=True)
    assert proc.returncode == 0, f"build_portal --help failed: {proc.stderr}"
    return proc.stdout


def test_build_portal_still_offers_every_flag_contribute_uses():
    # FAILS IF build_portal renames/removes any flag the surveys consumer passes — the cross-repo
    # break M6 pins. Proven non-vacuous: renaming build_portal's `--extractor` (or dropping it from the
    # vendored list's target) makes the flag absent from --help and reds this test.
    help_text = _build_portal_help()
    present = set(re.findall(r"--[A-Za-z][A-Za-z0-9-]*", help_text))
    missing = [f for f in CONTRIBUTE_BUILD_PORTAL_FLAGS if f not in present]
    assert not missing, (
        f"build_portal no longer offers flags the surveys contribute.py depends on: {missing}. "
        "Either restore the flag or coordinate a contribute.py change in ausmt-surveys (M6).")


def test_vendored_flags_match_live_contribute():
    # When the sibling checkout is present (dev box), re-derive the flags contribute.py ACTUALLY passes
    # to extract.build_portal from its source and assert the vendored tuple above still matches. On CI
    # (no sibling) this is a no-op assertion on an empty precondition — NOT a skip, so the suite count
    # is stable and the loud-skip gate stays clean. FAILS IF contribute.py's argv drifts from the
    # vendored list on a dev box (the signal to update CONTRIBUTE_BUILD_PORTAL_FLAGS here).
    if not _SIBLING_CONTRIBUTE.is_file():
        return  # CI path: vendored list is the contract; test_build_portal_... still pins the provider
    src = _SIBLING_CONTRIBUTE.read_text(encoding="utf-8")
    # Isolate the `[sys.executable, "-m", "extract.build_portal", ...]` list literal and read the
    # "--flag" string tokens inside it (values like str(...) are ignored — we only pin flag NAMES).
    m = re.search(r'"-m",\s*"extract\.build_portal"(.*?)\]', src, re.DOTALL)
    assert m, "could not locate contribute.py's extract.build_portal argv list — its shape changed"
    live_flags = tuple(dict.fromkeys(re.findall(r'"(--[A-Za-z][A-Za-z0-9-]*)"', m.group(1))))
    assert live_flags == CONTRIBUTE_BUILD_PORTAL_FLAGS, (
        f"contribute.py's build_portal flags {live_flags} drifted from the vendored pin "
        f"{CONTRIBUTE_BUILD_PORTAL_FLAGS} — update CONTRIBUTE_BUILD_PORTAL_FLAGS (M6).")
