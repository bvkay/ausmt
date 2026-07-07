# C11b — Curator-acknowledgeable PII sweep (flag-not-block for non-submitter emails)

**Status: FROZEN 2026-07-06 (chief-architect design). Implementation must not deviate without an
amendment recorded here first.** This is the tracked C11 follow-up: the shipped PII sweep
hard-blocks approve on ANY email in the built product, but C3 doctrine for *original-EDI `>INFO`
emails* is flag-not-block — a historical contact line in a source EDI is part of the record being
archived, not a leak the gateway created. C11b lets a named curator take responsibility for those,
without weakening the one invariant that must never bend.

## §0 The invariant that does not move

**The submitter's own email (the needle from the gateway DB) in any built artifact is a blocking
FAIL that NO acknowledgement can override.** That address exists only because the gateway promised
to keep it in sqlite; publishing it is the exact failure the C10/C11 confinement design exists to
prevent. Every other rule below is subordinate to this one, and the test suite must contain a test
that tries to acknowledge past a submitter-email hit and asserts the 409 — that test is the
contract.

## §1 Sweep classification (gateway/checklist.py)

`_grep_pii` currently returns on the FIRST hit with a single status. Rework it to scan the full
tree and return a structured result:

- `submitter_hits: list[str]` — file names (relative to the scanned root) where the DB needle
  matched. Submitter-needle matching is **case-insensitive by contract** (Amendment A1): a case
  variant of the submitter's email in an artifact is a submitter hit, never a generic one.
- `generic_hits: list[str]` — file names where the generic email regex matched (and the needle did
  not).
- Bound the *reporting*, not the scan: cap each list at 20 names + a "+N more" suffix in the
  detail string. Never echo any matched ADDRESS anywhere (unchanged no-echo rule — file names
  only).

Checklist mapping:
- Any `submitter_hits` → `FAIL`, `blocking=True`, **not acknowledgeable**. Detail names the files
  and says acknowledgement is not available for submitter PII.
- Only `generic_hits` → `FAIL`, `blocking=True`, `acknowledgeable=True`. Detail lists the files and
  tells the curator what acknowledging asserts (§3 wording).
- No hits → `PASS` exactly as today; empty trees → `NA` as today.

`Check` gains an additive field `acknowledgeable: bool = False`; only this case sets it. No other
check may become acknowledgeable in this contract (scope guard — in particular the validator-FAIL
and slug checks stay absolute).

## §2 Approve gate (gateway/app.py)

- The approve/retry POST gains an `ack_pii` form field, parsed with the same exact-affirmative
  rule as `confirm_overwrite` (`strip().lower() in ("1","yes","true","on")`, default DENY — a bare
  truthy string must not count).
- `_begin_publish` rule, replacing the current flat `has_blocking_fail` check:
  - any blocking FAIL with `acknowledgeable=False` → 409 (unchanged behaviour, includes every
    submitter-email hit).
  - blocking FAILs that are ALL `acknowledgeable=True` → 409 **unless** `ack_pii` is affirmative.
    The mandatory non-empty decision note already applies to every action; no separate note field.
- Acknowledgement is **per-action**: a retry from `PUBLISH_FAILED` re-evaluates and needs
  `ack_pii` again. Nothing about the ack persists on the submission row.
- Audit: when an acknowledged approve proceeds, the PUBLISHING transition reason is prefixed
  `PII-ACK (<n> file(s): <bounded list>): <curator note>` so the existing audit table records who
  acknowledged what, with no schema change. The public status page must not change at all —
  acknowledgement details are curator-only.

## §3 Curator UI (gateway/curatorpage.py)

- The PII checklist row renders the classified file lists (file names only).
- When (and only when) the PII row is acknowledgeable and no submitter hits exist, the approve
  form shows an unchecked checkbox wired to `ack_pii`, labelled to the effect of: *"I have opened
  each listed file and confirm every address is part of the original submitted records (e.g. an
  EDI `>INFO` contact line) and none is the submitter's private contact — publishing them is a
  deliberate curator decision."*
- When submitter hits exist, no checkbox is rendered and the row states the block is absolute.
  The server-side 409 remains the guarantee either way (button/checkbox absence is UX only).
- All new rendered strings go through the module's existing escaping helpers; file names are
  submitter-derived input and must be escaped (add an XSS test with a hostile file name).

## §4 Tests (gateway suite; proven-failing-first for every behaviour change)

1. Generic email in the package, no ack → approve 409 listing the PII reason (current behaviour,
   now as an explicit regression test).
2. Generic email + `ack_pii=yes` + note → publish proceeds; the audit reason contains `PII-ACK`,
   the file name, and the curator note.
3. **Submitter email present + `ack_pii=yes` → 409.** The §0 contract test. Also the mixed case
   (submitter + generic hits) → 409 with ack.
4. `ack_pii` exact-token parsing: `""`, `"0"`, `"false"`, `"anything"` → deny; the four
   affirmatives → allow (mirror the confirm_overwrite test style).
5. Classification: needle-vs-generic separation; report capped at 20 names with `+N more`; the
   matched address string itself appears in NO output (checklist detail, HTML, audit reason).
6. Retry after an acknowledged-then-failed publish requires ack again.
7. Hostile file name (`<img src=x onerror=…>.edi`) renders inert in the detail page.
8. Public status page output is byte-identical for an acknowledged vs non-acknowledged submission
   in the same state.

## §5 Docs

- `maintainer/C11-CuratorDesign.md`: add a short "Amendment A1 (C11b)" section at the end pointing
  here — do not rewrite frozen sections.
- `deploy/README.md` C11 section: one paragraph on the acknowledge flow and its §0 limit.

## §6 Scope guards

- No DB schema change, no submit-path change, no new routes, no state-machine change (same
  transitions, same states). No portal changes. ≤ ~200 net non-test lines.
- If the implementation appears to require any of the above, STOP and escalate.

## Amendment A1 — adversarial-review fixes (2026-07-06, RELEASE-WITH-FIXES)

Two confirmed findings from the post-implementation adversarial review, both fixed
proven-failing-first on `feature/c11b-pii-ack`. The frozen sections above stand as written except
where this amendment tightens them.

**A1.1 — Submitter-needle matching is case-insensitive by contract (review finding 1, release-blocking).**
§1's needle test was byte-exact while the generic regex is case-insensitive, so a case variant of
the submitter's own address (`User@Example.com` in the DB, `user@example.com` in an artifact)
classified as a GENERIC hit — acknowledgeable — and `ack_pii` published the submitter's own email:
a §0 bypass, reproduced end-to-end by reviewers. The submitter classification now ASCII-lowercases
both the needle and the scanned bytes before the containment test (bytes-level; non-ASCII characters
fall back to byte-exact, never weaker than before). The generic regex and the no-echo rule are
unchanged. The §0 contract test now includes a case-variant case, plus a dedicated
both-orientations classification test.

**A1.2 — The public status page renders the decision note only for submitter-intended states
(finding 2, high).** The PII-ACK-prefixed reason lands on the VALIDATED→PUBLISHING transition, and
the public page rendered the LAST transition reason for ANY state with a truthy note — so during
the real PUBLISHING window the submitter-visible page showed `PII-ACK`, the flagged file names, and
the curator's private note, contradicting §2 ("the public status page must not change at all").
The public render is now gated by state: the note renders ONLY for QUARANTINED / REJECTED_AV /
RETURNED / REJECTED. PUBLISHING / PUBLISHED / PUBLISH_FAILED reasons (curator, audit, internal-git
text) never render publicly. This also closes the pre-existing public leak of raw curator notes and
git failure internals in the publish-cycle states — a deliberate strict improvement. The DB
`transitions.reason` is untouched (it remains the audit channel); only the public render is gated.
