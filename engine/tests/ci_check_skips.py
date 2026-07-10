#!/usr/bin/env python3
"""CI skip tripwire (code-health review M5).

The engine suite gates the release, but ~20 of its files `pytest.importorskip("mt_metadata")`/
`("mth5")` at module top. If the pinned lock ever silently stopped installing that stack, those files
would ALL skip and the release gate would go green over a hollowed-out suite. No lane accounted for
that. This tripwire does: it reads a `pytest -q -rs ...` report on stdin and FAILS if any skip's reason
is not on the allow-list below. It is deliberately tiny — a tripwire, not a framework.

The allow-list is the set of skips that are LEGITIMATE in the CI engine lanes, where the mt_metadata/
mth5 stack IS installed (pinned lock / engine image) but the sibling ausmt-surveys checkout is NOT
present. Both engine lanes (build-products.yml and deploy-images.yml's engine-full-tests) share this
exact environment, so the allow-list is the same for both:

  * "sibling ausmt-surveys/_validation not present"
        engine/tests/test_validator_gate.py::test_env_var_path_resolves_real_validator — the only test
        gated purely on a sibling ausmt-surveys checkout, which neither engine CI lane has (the private
        repo is not cross-checked-out here; see build-products.yml's --no-validate note and
        engine.Dockerfile:133-134). LEGITIMATE: it is a dev-box-only cross-repo integration check.
        Empirically confirmed (C35a verification): with the stack present and no sibling checkout, this
        is the ONE and ONLY skip the engine suite produces; every mt_metadata/mth5/yaml/jsonschema/
        _mth5 importorskip RUNS (all of those deps ARE in the CI lock / image).

A skip whose reason contains "mt_metadata not installed" / "mth5 not installed" / "could not import
'mt_metadata'" / "mth5/mt_metadata not installed" / "could not import 'yaml'" etc. is NOT on the list
on purpose: in these lanes those deps are present, so such a skip means the lock/image silently dropped
a core dependency — the exact failure this tripwire exists to catch.

Two independent checks (either one FAILS the tripwire):
  1. every parsed skip's reason must be on the allow-list; and
  2. the number of `SKIPPED [..] loc: reason` lines this script parsed must EQUAL the skip total in
     pytest's own summary line (`N passed, M skipped in ...`). This closes a silent-drop hole: if a
     skip line ever appears in a format this parser does not recognize (a pytest-version change, a
     wrapped reason, an unexpected path form), the counts DISAGREE and the tripwire fails loudly
     instead of quietly ignoring an unaccounted skip and passing green (Invariant 10: a check that
     cannot see part of its own input must not report PASS over it).

Usage (from the engine/ cwd, both lanes):
    pytest -q -rs tests | tee /tmp/pytest.out ; python tests/ci_check_skips.py < /tmp/pytest.out

C35b/D5: a repeatable --allow flag lets a DIFFERENT lane supply its own allow-list. Passing --allow at
least once (even `--allow ""`) REPLACES the built-in list entirely; passing it zero times keeps today's
behaviour (the engine built-in list below). The gateway lane pipes its report through this with a
single `--allow ""` — i.e. NO substantive allow entries — so after D3 (which made the validator oracles
run via the vendored copy) the gateway suite's ONE legitimate skip (the mt_metadata-needing engine-
preview oracle) is the only entry it allows; every other skip fails the lane:
    pytest -q -rs gateway/tests | python engine/tests/ci_check_skips.py \
        --allow "real engine stack / sample survey / validator not present"

Exit 0 iff every parsed skip matches an allow-list entry AND the parsed count equals pytest's own
skip total. Exit 1 on any unexpected skip OR any count mismatch.
"""
from __future__ import annotations

import argparse
import re
import sys

# The ENGINE lanes' built-in allow-list. Each entry is a substring that must appear in a skip's reason
# for that skip to be allowed. Add an entry ONLY with a comment saying which test/lane produces it and
# why it is legitimate.
#
# C35b/D3 note: test_validator_gate.py::test_env_var_path_resolves_real_validator NO LONGER skips —
# D3 made it resolve to the committed vendored validator when the sibling is absent, so it RUNS in the
# engine lanes too. This entry is therefore DEFENSIVE now (it matches a skip the current suite does not
# emit); it is retained per the C35b/D5 amendment so an older checkout or a re-introduced sibling-gated
# skip stays allow-listed, and the accounting check below catches any genuinely unaccounted skip.
ALLOWED_SKIP_REASON_SUBSTRINGS = [
    "sibling ausmt-surveys/_validation not present",  # test_validator_gate.py — pre-D3 sibling gate (now defensive)
    # C35b/D3.1: test_validator_gate.py's oracle skips (exact reason below) when the gateway package
    # tree itself is absent from the repo root — legitimately reachable ONLY in the engine-image lanes
    # (the engine image COPYs engine/ only, so /app/gateway never exists: deploy-images' in-image
    # engine-full-tests run — the sole remaining engine-image pytest since C39 dropped the
    # in-Dockerfile duplicate — pipes through THIS tripwire). INERT on every checkout lane: a
    # monorepo checkout always has <root>/gateway, so there a missing vendored fixture FAILS the oracle
    # (D3.1 arm iv), never skips.
    "engine image build: gateway tree not shipped",   # test_validator_gate.py — D3.1 arm (iii), image lanes only
    # C25: test_convention_gates_realdata.py — the real-corpus convention-gate pins (the three
    # named USArray negative controls, the ccmt-2017 de-rotation acceptance, the AusLAMP-SA
    # custodian-twin proof) run only where the .audit/realdata harness exists (the dev box; the
    # corpus is not in the repo and not in any CI lane). Same dev-box-only class as the
    # sibling-validator skip above. The synthetic gate pins in test_convention_gates.py RUN
    # everywhere — this entry never excuses those.
    "realdata corpus not present (AUSMT_REALDATA unset)",
]

# `pytest -rs` prints one line per skip: "SKIPPED [N] path:line: <reason>". The location token
# (path:line) is a single run of non-whitespace, so a GREEDY `\S+` captures it whole — including the
# trailing `:line` — and backtracks to the last `:` before the reason. Both CI (ubuntu, `/`) and a
# Windows dev box (`\`) keep the whole path in `\S`, so this matches either separator.
_SKIP_LINE = re.compile(r"^SKIPPED \[\d+\]\s+(?P<loc>\S+):\s*(?P<reason>.*)$")

# pytest's terminal summary line, e.g. "177 passed, 1 skipped in 180.00s", "1 skipped in 0.40s", or
# (with other outcomes present) "3 skipped, 5 passed in 1s". We read the authoritative skip TOTAL from
# it and reconcile against the lines we actually parsed. `\bskipped\b` allows the token to be followed
# by a comma or " in ..." without over-tight anchoring; the `\b` before the count keeps it from eating
# a digit out of a larger number.
_SUMMARY_SKIPPED = re.compile(r"\b(\d+)\s+skipped\b")


def _resolve_allow_list(allow_args: list[str] | None) -> list[str]:
    """The allow-list to enforce (C35b/D5). If --allow was passed at least once, it REPLACES the
    built-in list entirely (empty-string entries are dropped, so a single `--allow ""` yields an EMPTY
    allow-list — every skip fails); if it was never passed, use the engine built-in list."""
    if allow_args is None:
        return list(ALLOWED_SKIP_REASON_SUBSTRINGS)
    return [a for a in allow_args if a]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CI skip tripwire (M5/C35b-D5).")
    parser.add_argument(
        "--allow", action="append", default=None, metavar="SUBSTRING",
        help="allow-list entry (repeatable); passing it at least once REPLACES the built-in engine "
             "list. `--allow \"\"` yields an EMPTY allow-list so ANY skip fails (the gateway lane, minus "
             "its one legitimate skip passed explicitly). Omit entirely to keep the engine built-in list.")
    args = parser.parse_args(argv)
    allow_list = _resolve_allow_list(args.allow)

    text = sys.stdin.read()
    # A report this script cannot recognize as pytest output must FAIL, not pass (the same
    # Invariant-10 rule as check 2): an empty or truncated tee file would otherwise parse as
    # "0 skips = 0 reported" and go green. The wiring runs this only after a passing pytest, so a
    # legitimate report always carries a terminal summary token; its absence means broken plumbing.
    if not re.search(r"\b\d+\s+(passed|failed|skipped|xfailed|error)\b|no tests ran", text):
        print(
            "CI skip tripwire FAILED -- input does not look like a pytest report (no terminal "
            "summary line found). Empty or truncated output must not pass this gate; check the "
            "tee/redirect plumbing that feeds it."
        )
        return 1
    unexpected: list[str] = []
    parsed_skips = 0
    for line in text.splitlines():
        m = _SKIP_LINE.match(line.strip())
        if not m:
            continue
        parsed_skips += 1
        reason = m.group("reason").strip()
        if not any(sub in reason for sub in allow_list):
            unexpected.append(f"{m.group('loc')}: {reason}")

    # pytest's own skip total (last summary match wins; a run with no skips has no such token -> 0).
    summary_matches = _SUMMARY_SKIPPED.findall(text)
    reported_skips = int(summary_matches[-1]) if summary_matches else 0

    failed = False

    if unexpected:
        failed = True
        print("CI skip tripwire FAILED -- unexpected skip(s) not on the allow-list:")
        for u in unexpected:
            print(f"  UNEXPECTED SKIP: {u}")
        print("\nAllow-list in effect (add an entry with a justifying comment if a new skip is "
              "legitimate; this lane's list came from --allow if given, else the engine built-in):")
        for s in allow_list:
            print(f"  - {s!r}")
        if not allow_list:
            print("  (empty — this lane allows NO skips)")

    if parsed_skips != reported_skips:
        failed = True
        print(
            f"CI skip tripwire FAILED -- accounting mismatch: parsed {parsed_skips} SKIPPED line(s) "
            f"but pytest reported {reported_skips} skipped. A skip is unaccounted for (unrecognized "
            f"'-rs' line format?). Run pytest with -rs and inspect the short test summary; do NOT "
            f"pass this gate until every skip is parsed and allow-listed."
        )

    if failed:
        return 1

    print(f"CI skip tripwire OK -- {parsed_skips} skip(s), all on the allow-list (matches pytest's summary).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
