# C35b — Real-git publish lane, vendored validator oracle, strict FakeGit, poll_once (frozen design)

From the 2026-07-07 code-health review: F6 (real_git_runner and the production git environment have
zero executing coverage anywhere; the rollback that guards the publication ledger has never run
against a real repository; the first live approve failed twice on real-git behaviours FakeGit cannot
represent), F7 (the 2026-07 argv-remediation oracles are skipif-gated on a dev-box-only sibling
checkout), M4 (run_forever's coverage claim is false; the loop's ordering and crash-recovery
contracts are enforced nowhere).

## D1. Real-git pytest lane — no network, no docker, no secrets
New gateway/tests/test_publish_real_git.py. Fixtures build, per test, a REAL repo pair in tmp_path:
surveys-live = `git init` + identity config + an initial commit on main; origin = `git init --bare`
+ `remote add`. The environment is HERMETIC: GIT_CONFIG_NOSYSTEM=1, GIT_CONFIG_GLOBAL -> a tmp file,
HOME -> tmp — the dev box's or CI runner's gitconfig must never leak in (that leakage class is
exactly what test_curator_publish.py:114's recorded 2026-07-06 failure was).
The full approve flow runs with git_runner=REAL real_git_runner (publish.py:86) — no FakeGit
anywhere in this file. Assertions, each with a mutation-proof (see Tests):
  a. commit lands on main in surveys-live; author/committer exactly "AusMT Gateway
     <gateway@ausmt.local>" (publish.py COMMIT_AUTHOR_*) regardless of ambient identity;
  b. the push ARRIVES: rev-parse HEAD in the bare origin equals the local commit;
  c. PII confinement: submitter name/email appear nowhere in the committed tree or commit message;
  d. preflight refusals fire with real git: dirty tree refuses; detached/non-main HEAD refuses;
  e. ROLLBACK (the never-executed core guarantee): a pre-receive hook on the bare origin exits 1 ->
     the push fails mid-sequence -> _rollback restores the captured ref+branch, the working tree is
     clean, surveys-live is back on main, and a SUBSEQUENT publish (hook removed) succeeds. The
     wedged-ledger scenario from the review (left on a submit branch, every later publish refusing)
     is the red state this test exists to prevent.
  f. the metadata-edit commit path (commit_metadata_edit) gets the same real-git treatment for its
     commit+push+rollback skeleton.
Hook portability: pre-receive as `#!/bin/sh` + `exit 1` — Git for Windows runs hooks under its own
sh; CI ubuntu likewise. No bashisms.

## D2. FakeGit goes strict — unmodeled verbs fail loudly
conftest.py FakeGit currently returns rc=0 for ANY unmodeled verb (push, merge, typo'd flag =
unconditional success). Its default branch becomes: raise AssertionError naming the argv — a test
that drives an unmodeled verb now fails until FakeGit models it CONSCIOUSLY. Sweep the suite: every
verb the existing tests actually drive gets an explicit minimal model (push included). The
psychology matters: extending FakeGit must be a deliberate act with the real lane (D1) as the
reference for what honest behaviour is.

## D3. Vendored validator oracle — the cross-repo contract becomes unconditionally executable
The F7 oracles (test_runner.py:205-243, test_edit_runner.py:439-480, test_validator_gate.py:68)
skip without a sibling ausmt-surveys checkout — no CI has one. Vendor a pinned copy:
gateway/tests/fixtures/vendored_validation/validate_survey.py + PIN file recording the source sha256
and the ausmt-surveys commit it came from (930ce6f today). A sync script
(gateway/tests/fixtures/sync_vendored_validator.py) refreshes it from the sibling when present and
rewrites the PIN — the contract.js generate-and-assert pattern this repo already owns. A pytest
asserts vendored-file sha == PIN sha (drift inside the monorepo fails loudly). The F7 oracles change
their resolution to: sibling checkout when present (dev box — tests the LIVE cross-repo pair), else
the vendored copy (CI and fresh clones — tests the PINNED contract), else FAIL (not skip): with the
vendored copy committed, "neither present" is a broken checkout, not a legitimate skip.
Rejected alternative (recorded): cross-repo CI clone with a PAT — needs an organisation secret (a repository-owner action)
and leaves fresh local clones oracle-less; the vendored pin covers both and drift is caught at sync.

### Amendment D3.1 (maintainer, 2026-07-07) — the environment enumeration fail-not-skip missed
Real CI went red on the c35b PR: the deploy-images PR leg failed the ENGINE IMAGE BUILD at
engine.Dockerfile's in-build `pytest -q tests` — test_validator_gate.py's oracle FAILED with "BROKEN
CHECKOUT" because the engine image ships NO gateway tree by design (its Dockerfile COPYs engine/ only;
/app/gateway does not exist), so the vendored copy is legitimately absent there. D3's fail-not-skip
rule had one legitimate environment it didn't enumerate. The resolution becomes a FOUR-arm enumeration:
  (i)   sibling ausmt-surveys checkout beside the repo root -> use it (LIVE cross-repo pair);
  (ii)  else the committed vendored copy under <root>/gateway/tests/fixtures -> use it (PINNED);
  (iii) else IF the gateway package tree itself is absent from the repo root (no <root>/gateway dir =
        not a monorepo checkout = the engine image's designed topology) -> SKIP with the exact reason
        "engine image build: gateway tree not shipped (designed topology; vendored oracle lives in
        gateway/tests)";
  (iv)  gateway tree PRESENT but the vendored fixture missing -> FAIL as before (a true broken checkout).
The property that makes (iii) honest: on every monorepo checkout (CI runners, dev boxes, fresh clones)
the gateway dir exists, so arm (iii) is UNREACHABLE there — fail-not-skip is preserved everywhere the
F7 finding applied; only the image build (which cannot have a silent-drift problem for a file it never
ships) gets the skip. The gateway-tree probe anchors off the SAME module-level _repo_root() the
vendored path derives from (no second path convention), and _repo_root() is the monkeypatch seam the
two falsifiability tests use (scratch engine-only root -> must SKIP with the exact reason; scratch root
WITH gateway/ but no vendored fixture -> must FAIL). ci_check_skips.py's BUILT-IN allow-list gains the
new reason substring — legitimately reachable ONLY in the engine-image lanes (the Dockerfile in-build
pytest needs plain non-failure; deploy-images' in-image run pipes through the tripwire), inert on
checkout lanes.

## D4. poll_once extraction — run_forever's contracts become testable
gateway/runner/runner.py: extract the body of one poll pass into poll_once(cfg) (mirroring the
gateway app's own poll_once pattern); run_forever = while True { poll_once(cfg); sleep }. NO
behaviour change — pure extraction, byte-equivalent logic. Unit tests: (i) edit jobs drain BEFORE
submission jobs within one pass; (ii) a process_job crash leaves the running-file present and no
done-file (crash-recovery contract: the heartbeat/mtime machinery decides staleness, a crashed job
is never silently marked done); (iii) correct run_forever's false docstring (M4: it claims compose
e2e coverage in a lane where the runner never boots).

## D5. Loud skip accounting for the gateway lane
engine/tests/ci_check_skips.py gains a repeatable --allow flag (entries replace the built-in
allow-list when given; no flags = today's behaviour, engine allow-list). gateway-ci.yml pipes
`pytest -q -rs gateway/tests` through it with NO --allow entries: after D3 the gateway suite has
zero legitimate skips, so ANY skip fails the lane. The engine lanes keep their built-in entry.

### D5 amendment (maintainer, 2026-07-07) — the gateway lane's allow-list is NOT zero
The first real gateway-ci run (2026-07-07) went red on requirements-dev drift (edit.py's ruamel
import; fixed on c35a @ 0f7047b — requirements-dev.txt now carries ruamel.yaml + PyYAML). Re-verifying
in a CI-FAITHFUL fresh venv (venv + `pip install -r gateway/requirements-dev.txt`, NOT the conda env)
shows the gateway suite = 178 passed, 1 SKIPPED: test_runner.py's real-engine-preview oracle skips
because the gateway test env has no mt_metadata stack — LEGITIMATELY: installing the engine stack is
the engine lanes' job, not gateway-ci's.

So the gateway lane does NOT run with an empty allow-list. After D3 (vendored validator) the
sibling-VALIDATOR skips become runs-or-FAIL as designed (the validator is stdlib + mini_yaml, no
mt_metadata — it runs from the vendored copy even in the stack-less gateway venv), but the
real-engine-STACK skip (reason names the mt_metadata/engine-preview precondition) is legitimate in
gateway-ci and gets ONE --allow entry with a justifying comment. The set was enumerated EMPIRICALLY in
a fresh venv (not conda) post-D3 to confirm it is the only one; any other skip found is a finding, not
an allow-list entry.

### Binding verification rule (maintainer, 2026-07-07) — CI-parity means fresh venv
Any command claimed CI-parity for must be executed in a FRESH venv built from the WRITTEN requirements
file the workflow installs (`gateway/requirements-dev.txt`) — the conda env has drifted before (that
is what shipped the red) and will again. The D1 real-git lane and the D3 vendored-oracle tests are
verified in that fresh venv too. requirements-dev.txt itself is NOT touched here (the fix is on c35a
@ 0f7047b); the fresh-venv runs in THIS lane install ruamel.yaml + PyYAML manually on top, and the
merged result carries the fix. Base note: this branch's base 5f53804 is 3 commits behind the c35a head
(e41441f image-paths, 0f7047b requirements fix); no rebase — the merge after c35a inherits the fix.

## Tests must be able to fail
Mutation proofs required for D1 (on a scratch copy of publish.py, one at a time, suite must go RED):
author-identity mutation (drop the -c user.name config), rollback-elision (skip _rollback on push
failure -> test e must fail), PII mutation (write submitter email into the commit message -> test c
must fail). For D2: an intentionally-unmodeled verb in a scratch test must raise. For D3: corrupt
the vendored copy one byte -> PIN test fails; delete both sibling+vendored on a scratch copy ->
oracles FAIL (not skip). For D4: reorder edit-drain after submissions on a scratch copy -> test (i)
fails. Transcripts in the report.

---

## Verification results (as landed)
Environments: conda `ausmt` (has mt_metadata + the sibling ausmt-surveys checkout) AND a FRESH
CI-faithful venv (python 3.12 from `gateway/requirements-dev.txt` + ruamel.yaml/PyYAML = the c35a fix
applied manually; NO mt_metadata — mirrors gateway-ci.yml). AUSMT_FORCE_VENDORED_VALIDATOR=1 simulates
the CI no-sibling path on the dev box without touching the real sibling.

- Gateway suite: 179 (base) -> 192 passed in conda (+8 D1, +2 D3 vendored, +3 D4; 0 skips, sibling
  present). Fresh venv natural: 191 passed, 1 skipped. Fresh venv forced-vendored (true CI): 191
  passed, 1 skipped — the ONE skip is test_runner.py's real-engine-preview oracle (needs mt_metadata),
  the only D5 allow entry. The 3 validator oracles RUN via the vendored copy in the stack-less venv.
- Engine suite: 178 passed, 0 skips (the engine validator-gate oracle now runs via sibling/vendored
  instead of skipping — its old skip is gone; the engine built-in allow entry is now defensive).
- Portal suite: 19 passed, 3 skipped (pre-existing jsdom-gated, untouched by this lane).
- Ruff: gateway/ and engine/ both clean under the CI-pinned ruff==0.15.17 (vendored copy excluded).
- D5 gate end-to-end: fresh-venv gateway output piped through ci_check_skips.py --allow "real engine
  stack / sample survey / validator not present" => "1 skip(s), all on the allow-list", exit 0.

Cross-platform notes (dev box = Windows git 2.50; CI = ubuntu):
- D1 primitives are POSIX-portable: `git init`, `git init --bare`, `git branch -M main`, a
  `#!/bin/sh`+`exit 1` pre-receive hook (LF-written; runs under Git-for-Windows' bundled sh AND
  ubuntu /bin/sh). No /dev/null, no bashisms. The hook genuinely fired on Windows (the rollback test
  went through the real reject path). Hermetic env (GIT_CONFIG_NOSYSTEM/GLOBAL/HOME) proven to override
  a deliberately-wrong ambient identity.
- The vendored validator is committed as LF (the monorepo's `.gitattributes` `* text=auto eol=lf`);
  the PIN records the LF sha (841d1219…) == the staged-blob sha a fresh checkout gets on any platform.
  The source checks out CRLF on this Windows box; sync --write LF-normalizes before pinning.

Residual risk (only real CI can prove): the gateway-ci.yml `set -o pipefail` + tee + `<` redirect
sequence and the exact ubuntu `/bin/sh` hook execution are verified locally under Git-for-Windows sh /
Git Bash but not under a real ubuntu runner; the primitives are standard POSIX so the risk is low.

### D3.1 verification addendum (2026-07-07, fix-forward after the real-CI image-build red)
The pre-D3.1 red was REPRODUCED locally end-to-end: the engine tree copied to a scratch /app-shaped
root (engine/ only, no gateway dir, no sibling), pre-fix test file -> `1 failed` with the exact
"BROKEN CHECKOUT" AssertionError the image build logged; post-fix file in the identical topology ->
`5 passed, 1 skipped` with the exact D3.1 reason string, and that output PASSES the tripwire's
built-in allow-list (and correctly FAILS an empty `--allow ""` list — the entry is load-bearing).
Falsifiability tests (monkeypatched _repo_root seam) pin both new arms: engine-image topology ->
SKIP with the exact reason; monorepo root with gateway/ but no vendored fixture -> FAIL. On this
checkout the skip arm did NOT fire (oracle ran via sibling, and via vendored under
AUSMT_FORCE_VENDORED_VALIDATOR=1).
REMAINING residual: the actual engine-image build re-run on the c35b PR (deploy-images PR leg,
engine.Dockerfile in-build `pytest -q tests` at real /app topology) is the final proof — only real CI
can execute it.

## Merge order (recorded per contract)
C35a (fix/c35a-ci-truth @ 5f53804) FIRST, then C35b (fix/c35b-git-truth, stacked on 5f53804).
This branch is stacked directly on C35a's head; it must land after C35a.
