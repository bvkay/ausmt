#!/usr/bin/env python3
"""CI skip tripwire (code-health review M5).

The engine suite gates the release, but ~20 of its files `pytest.importorskip("mt_metadata")`/
`("mth5")` at module top. If the pinned lock ever silently stopped installing that stack, those files
would ALL skip and the release gate would go green over a hollowed-out suite. No workflow accounted for
that. This tripwire does: it reads a `pytest -q -rs ...` report on stdin and FAILS if any skip's reason
is not on the allow-list below. It is deliberately tiny - a tripwire, not a framework.

The allow-list is the set of skips that are LEGITIMATE in the CI engine workflows, where the mt_metadata/
mth5 stack IS installed (pinned lock / engine image) but the sibling ausmt-surveys checkout is NOT
present. Both engine workflows (build-products.yml and deploy-images.yml's engine-full-tests) share this
exact environment, so the allow-list is the same for both:

  * "sibling ausmt-surveys/_validation not present"
        engine/tests/test_validator_gate.py::test_env_var_path_resolves_real_validator - the only test
        gated purely on a sibling ausmt-surveys checkout, which neither engine CI workflow has (the private
        repo is not cross-checked-out here; see build-products.yml's --no-validate note and
        engine.Dockerfile's `ENV AUSMT_VALIDATOR_PATH` block, which explains that the validator
        arrives at RUNTIME on a bind mount and is never baked into the image). LEGITIMATE: it is a
        dev-box-only cross-repo integration check.
        Empirically confirmed (verification): with the stack present and no sibling checkout, this
        is the ONE and ONLY skip the engine suite produces; every mt_metadata/mth5/yaml/jsonschema/
        _mth5 importorskip RUNS (all of those deps ARE in the CI lock / image).

A skip whose reason contains "mt_metadata not installed" / "mth5 not installed" / "could not import
'mt_metadata'" / "mth5/mt_metadata not installed" / "could not import 'yaml'" etc. is NOT on the list
on purpose: in these workflows those deps are present, so such a skip means the lock/image silently dropped
a core dependency - the exact failure this tripwire exists to catch.

Two independent checks (either one FAILS the tripwire):
  1. every parsed skip's reason must be on the allow-list; and
  2. the number of `SKIPPED [..] loc: reason` lines this script parsed must EQUAL the skip total in
     pytest's own summary line (`N passed, M skipped in ...`). This closes a silent-drop hole: if a
     skip line ever appears in a format this parser does not recognize (a pytest-version change, a
     wrapped reason, an unexpected path form), the counts DISAGREE and the tripwire fails loudly
     instead of quietly ignoring an unaccounted skip and passing green (Invariant 10: a check that
     cannot see part of its own input must not report PASS over it).

Usage (from the engine/ cwd, both workflows):
    pytest -q -rs tests | tee /tmp/pytest.out ; python tests/ci_check_skips.py < /tmp/pytest.out

a repeatable --allow flag lets a DIFFERENT workflow supply its own allow-list. Passing --allow at
least once (even `--allow ""`) REPLACES the built-in list entirely; passing it zero times keeps today's
behaviour (the engine built-in list below). The gateway workflow pipes its report through this with a
single `--allow ""` - i.e. NO substantive allow entries - so after D3 (which made the validator oracles
run via the vendored copy) the gateway suite's ONE legitimate skip (the mt_metadata-needing engine-
preview oracle) is the only entry it allows; every other skip fails the workflow:
    pytest -q -rs gateway/tests | python engine/tests/ci_check_skips.py \
        --allow "real engine stack / sample survey / validator not present"

Exit 0 iff every parsed skip matches an allow-list entry AND the parsed count equals pytest's own
skip total. Exit 1 on any unexpected skip OR any count mismatch.
"""
from __future__ import annotations

import argparse
import re
import sys

# The ENGINE workflows' built-in allow-list. Each entry is a substring that must appear in a skip's reason
# For that skip to be allowed. Add an entry ONLY with a comment saying which test/workflow produces it and
# why it is legitimate.
#
# Note: test_validator_gate.py::test_env_var_path_resolves_real_validator does NOT skip -
# Made it resolve to the committed vendored validator when the sibling is absent, so it RUNS in the
# Engine workflows too. This entry is therefore DEFENSIVE now (it matches a skip the current suite does not
# emit); it is retained per the amendment so an older checkout or a re-introduced sibling-gated
# skip stays allow-listed, and the accounting check below catches any genuinely unaccounted skip.
ALLOWED_SKIP_REASON_SUBSTRINGS = [
    "sibling ausmt-surveys/_validation not present",  # test_validator_gate.py — pre-D3 sibling gate (now defensive)
    # test_validator_gate.py's oracle skips (exact reason below) when the gateway package
    # Tree itself is absent from the repo root - legitimately reachable ONLY in the engine-image workflows
    # (the engine image COPYs engine/ only, so /app/gateway never exists: deploy-images' in-image
    # engine-full-tests run — the sole remaining engine-image pytest since C39 dropped the
    # In-Dockerfile duplicate - pipes through THIS tripwire). INERT on every checkout workflow: a
    # monorepo checkout always has <root>/gateway, so there a missing vendored fixture FAILS the oracle
    # (D3.1 arm iv), never skips.
    "engine image build: gateway tree not shipped",   # test_validator_gate.py, image builds only
    # test_mtcat_version_parity.py, the SAME designed-topology class as the entry above, for the
    # other tree the engine image does not ship. The MTCAT schema version has one source (the schema
    # title) and that module reads it back off every surface that restates it; four of those surfaces
    # are portal files (portal.config.yaml, config.js, data/mtcat.json, tools/gen_config.py) plus
    # version.js's sentinel, and engine.Dockerfile COPYs contract/ + engine/ and exactly one portal
    # File (the generated portal/src/contract.js), so in the image workflow those five do not exist. The
    # three tests that read them skip with the exact reason below; the ENGINE-side statements (schema
    # title, contract parser, generated _contract constant, the real build's emitted portal block,
    # build_portal.py's own literal guard) keep ASSERTING in the image, so the release gate still
    # Proves the image's internal coherence. INERT on the checkout workflows: build-products.yml checks
    # out the whole monorepo and its path filter names all five portal files, so there these tests RUN
    # (a checkout missing one of them fails the read rather than skipping; the guard opens as soon as
    # any pinned portal file is present).
    "engine image build: portal tree not shipped",    # test_mtcat_version_parity.py, image builds only
    # test_mtcat_version_parity.py again, the SAME designed-topology class, for the docs tree: the
    # ratified MTCAT 2.0 version machinery added a pin on the docs current-version display
    # (docs/docs/reference/index.md), and engine.Dockerfile does not COPY docs/ either, so in the
    # Image workflow that one test skips with the exact reason below. INERT on checkout workflows, where the
    # docs tree is always present and the pin asserts.
    "engine image build: docs tree not shipped",      # test_mtcat_version_parity.py docs pin, image builds only
    # Test_convention_gates_realdata.py - the real-corpus convention-gate pins (the three
    # named USArray negative controls, the ccmt-2017 de-rotation acceptance, the AusLAMP-SA
    # custodian-twin proof) run only where the .audit/realdata harness exists (the dev box; the
    # Corpus is not in the repo and not in any CI workflow). Same dev-box-only class as the
    # sibling-validator skip above. The synthetic gate pins in test_convention_gates.py RUN
    # everywhere — this entry never excuses those.
    "realdata corpus not present (AUSMT_REALDATA unset)",
    # test_edi_preflight.py's corpus-scale arm re-proves the predictor-versus-engine agreement over a
    # real directory of EDIs (the Western Gawler delivery, or the ausmt-surveys corpus) by running the
    # REAL mt_metadata reader per file and diffing it against the prediction. No CI workflow can supply
    # that input: build-products.yml checks out this monorepo only, and pointing the arm at the sibling
    # corpus would need the private-repo secret, which is unavailable on fork PRs. Same dev-box-only
    # class as the two entries above. The invariant is NOT unguarded in CI as a result: the 21
    # constructed adversarial cases in the same module assert the identical property against the real
    # reader on every run, so this entry excuses the scale of the proof, never the proof itself.
    "set AUSMT_PREFLIGHT_CORPUS to a directory of EDIs",
    # test_url_registry.py's real-build arm re-runs the slug/id freeze check against an actual BUILT
    # data tree (mtcat.json), named by AUSMT_URL_REGISTRY_DATA - a built corpus exists on the dev box
    # And on the deployed box, never in a CI engine workflow (the workflows build no corpus). Same
    # dev-box-only class as the three entries above. The freeze invariant is NOT unguarded in CI:
    # the fixture tests in the same module prove the checker's fail/pass/refuse behaviour on every
    # run, and the committed registry file itself is validated structurally; this entry excuses the
    # Real-corpus leg only. (Added when the path-URL contract module's first CI run tripped this
    # tripwire on the new skip - the tripwire working exactly as designed.)
    "AUSMT_URL_REGISTRY_DATA does not name a built data dir",
    # test_mtcat20_invariants.py's corpus arms: the zero-null/zero-empty + reference-invariant
    # scans over a REAL full-corpus build (AUSMT_MTCAT20_DATA) and the 1.2 -> 2.0 emitter
    # equivalence dict-test against a pre-2.0 baseline document (AUSMT_MTCAT20_BASELINE). A built
    # Corpus exists on the dev box and the deployed box, never in a CI engine workflow (the workflows
    # build no corpus). Same dev-box-only class as the entries above; the invariants are NOT
    # unguarded in CI - the same checks run against the committed fixtures and a real build of the
    # vendored fixture surveys on every run; these arms extend the identical assertions to corpus
    # scale.
    "AUSMT_MTCAT20_DATA does not name a built corpus data dir",
    "AUSMT_MTCAT20_BASELINE does not name a pre-2.0 corpus mtcat.json",
    # test_survey_metadata_invariants.py's corpus arm: the format-checked validation, zero-null /
    # zero-empty, identity-chain and projection-chain scans over every products/<slug>/
    # survey-metadata.json of a REAL full-corpus build (AUSMT_SURVEY_METADATA_DATA). Same dev-box-only
    # class as the two MTCAT 2.0 entries above; the invariants are NOT unguarded in CI - the same
    # checks run against the committed fixtures, two real builds of the vendored fixture surveys and
    # the 3-survey D8 corpus on every run; this arm extends the identical assertions to corpus scale.
    "AUSMT_SURVEY_METADATA_DATA does not name a built corpus data dir",
    # test_station_invariants.py's corpus arm: the identity-chain and schema scans over every
    # products/<slug>/<station>/station.json of a REAL full-corpus build (AUSMT_STATION_DATA). Same
    # dev-box-only class as the entries above; the invariants are NOT unguarded in CI - the identical
    # checks run over two real builds of the vendored fixture surveys and over the access-state corpus
    # on every run, and the chain checker is proven against planted violations; this arm extends them
    # to corpus scale.
    "AUSMT_STATION_DATA does not name a built corpus data dir",
    # test_station_invariants.py's two CI-guard pins read .github/workflows/build-products.yml, which
    # the engine image does not ship (engine.Dockerfile COPYs contract/ + engine/ and one portal file).
    # Same designed-topology class as the portal/docs entries above; INERT on every checkout workflow,
    # where the workflow is always present and both pins assert.
    "engine image build: workflow tree not shipped",
]

# `pytest -rs` prints one line per DISTINCT (location, reason): "SKIPPED [N] path:line: <reason>",
# where N is how many skips aggregated onto it (two tests skipping through one shared helper, e.g.
# the D3.1 validator seam, share the helper's location and land as [2]). The count is summed, never
# the lines, or an aggregated line undercounts against pytest's total. The location token
# (path:line) is a single run of non-whitespace, so a GREEDY `\S+` captures it whole — including the
# trailing `:line` — and backtracks to the last `:` before the reason. Both CI (ubuntu, `/`) and a
# Windows dev box (`\`) keep the whole path in `\S`, so this matches either separator.
_SKIP_LINE = re.compile(r"^SKIPPED \[(?P<n>\d+)\]\s+(?P<loc>\S+):\s*(?P<reason>.*)$")

# pytest's terminal summary line, e.g. "177 passed, 1 skipped in 180.00s", "1 skipped in 0.40s", or
# (with other outcomes present) "3 skipped, 5 passed in 1s". We read the authoritative skip TOTAL from
# it and reconcile against the lines we actually parsed. `\bskipped\b` allows the token to be followed
# by a comma or " in ..." without over-tight anchoring; the `\b` before the count keeps it from eating
# a digit out of a larger number.
_SUMMARY_SKIPPED = re.compile(r"\b(\d+)\s+skipped\b")


def _resolve_allow_list(allow_args: list[str] | None) -> list[str]:
    """The allow-list to enforce. If --allow was passed at least once, it REPLACES the
    built-in list entirely (empty-string entries are dropped, so a single `--allow ""` yields an EMPTY
    allow-list - every skip fails); if it was never passed, use the engine built-in list."""
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
        parsed_skips += int(m.group("n"))
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
            f"CI skip tripwire FAILED -- accounting mismatch: counted {parsed_skips} skip(s) across "
            f"the SKIPPED lines "
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
