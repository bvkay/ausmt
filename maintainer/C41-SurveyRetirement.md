# C41 — Survey lifecycle, part A: retirement (frozen design); rename (deferred)

Owner directive (2026-07-11): a curator-side **Remove survey** action. APPROVED BY THE OWNER
2026-07-11 with one amendment (the deletion second factor — see D2); mechanism locked TOTP. Motivation, in the owner's
words, "this allows us to bypass the git issues on the box, and also makes it NCI future proof."
Sharpened: the gateway publish flow commits **into the box's own surveys-live checkout** (mounted
rw, `deploy/compose.yaml:198`) and pushes outward with operator credentials — it needs **no
inbound pull and no console**. The two paths that failed on 2026-07-11 (operator `git pull`
blocked by DNS, then by 10002-owned `.git/objects` dirs) are exactly the paths this action never
touches; the outbound publish direction kept working through both incidents. At NCI (sole-entry
framing, C43 D12) survey lifecycle without console access is structural, not convenience.

This record opens the C43 D11 gate ("Retire a survey | Hub › danger zone | Stage 4 — C41 record
first") for **retirement only**. Rename (part B) stays gated: it carries the id-continuity,
bookmark-lineage, and redirect questions this record deliberately does not answer.

## D1. Current state (verified 2026-07-11, main @ 9ad6b3e)

* No survey-level removal exists in the workbench. **Station** removal is production-proven and
  is the template: routes under `/gateway/curator/edit/{slug}/stations`, surgical `git rm` of
  exact files + version bump + required note, `PUBLISH_LOCK`, fixed author, fail-closed
  `_rollback` (`gateway/publish.py`), stale-selection refusal, all-stations refusal
  (`gateway/tests/test_station_removal_flow.py`).
* Whole-survey retirement today is an **operator recipe** — and the evidence against it is fresh:
  the corpus swap's `git rm -r auslamp-sa` went through an operator batch block, and the
  test-2026 rename-retirement done by hand left a **serving duplicate for a day** (both dirs
  present at the served commit), undetected until the workbench's own survey list surfaced it.
  Hand-retirement is exactly the error class a guarded button removes.
* The engine treats a missing survey dir as simply absent — the build enumerates what exists.
  (The empty-corpus edge is NOT verified — see D4, implementer stop-condition.)

## D2. Design

**Placement.** Survey hub → a **Danger zone** panel at the bottom of the **Metadata** tab
(collapsed `<details>`, visually separated). Destructive ops live beside the survey's editing
surface; History stays read-only. (The mockup's matrix row said "Hub › danger zone" without
pinning a tab; this pins it.)

**Flow.** `Remove survey…` → a server-rendered confirmation page (curator-session + CSRF, like
every publish step) that discloses exactly:
* what is deleted — the survey package (`<slug>/survey.yaml` + N station files, N stated);
* what happens to serving — **nothing until the next rebuild**; the drift chip and serve panel
  show the lag honestly; a Request-rebuild pointer sits on the confirmation result;
* what happens downstream — collections rollup recomputes (the member simply disappears);
  readers' bookmarks to the survey 404 at the next rebuild; any minted DOI keeps resolving to a
  dead entry until the custodian's DOI metadata is updated (stated, not solved — DOI hygiene is
  the custodian's, we disclose);
* the undo — see below.

Confirmation requires **typing the slug** (the guarded-destructive-op pattern from the C43 D8
restore design) plus a **required release note** (why retired — it becomes the commit message
body). Mismatch → 400, nothing staged.

**Second factor (owner amendment, 2026-07-11; mechanism locked TOTP same day).** Full deletion
additionally requires a **valid TOTP code** — the typed slug protects against mistakes; the
second factor protects against a stolen curator session, a different and worse threat. The
owner's initial mechanism proposal (emailed ~10-minute one-time key) was revised to TOTP on two
architect grounds the owner accepted: an emailed code returns a sending secret to the box
(violating the A3 no-SMTP posture) and depends on box egress — the exact failure mode of the
2026-07-11 DNS outage would have locked deletion out. TOTP design:

* **RFC 6238, stdlib-only** (hmac/hashlib/struct/base64/time — no new dependency), 30 s steps,
  ±1 step verify window (box clock skew tolerance), per-curator secret.
* **Storage**: per-curator TOTP secret in the gateway sqlite (schema migration, additive) — the
  DB is already the secrets/PII home: never in git, WAL-safe backed up, restore-drilled.
* **Enrolment**: curator-session-gated Security page showing the base32 secret + otpauth:// URI
  for manual authenticator entry (no QR-image dependency; single-digit curator population).
  **Re-enrolment/rotation requires the CURRENT code** — a session alone must never rotate the
  secret, else the second factor collapses into the first. Lost-authenticator recovery is a
  **console action** (delete the enrolment row on the box) — deliberately in the same D12
  boundary class as bootstrap-key rotation.
* **Verification**: fail-closed — deletion by an unenrolled curator is refused with an enrol
  pointer; wrong/absent code → 400, nothing staged; replay within the window rejected
  (last-used counter per curator); attempts rate-limited (the login-throttle pattern).
* **Shared mechanism**: this is the workbench's destructive-op second factor — the 2b-ii DB
  restore adopts the same module and requirement, and C41 part B (rename) inherits it. One
  enrolment, every dangerous button.

**Mechanics.** Generalise the station-removal publish machinery to survey scope: preflight clean
checkout → `git rm -r <slug>` → ONE commit (fixed author `AusMT Gateway`, note in body) →
ff-only merge → push, all under `PUBLISH_LOCK`, fail-closed `_rollback` on any step. No validator
run (there is nothing left to validate); no YAML touches the gateway process. Diff-minimality at
survey scope: the commit touches exactly the slug's paths and nothing else.

**The undo story (load-bearing property).** Publish-through-git makes retirement **reversible**:
`git revert <retirement-commit>` restores the package byte-identically, provenance intact. The
confirmation page says so ("this is reversible by git revert — ask the operator"), and the
History of other surveys is untouched. Retained builds additionally keep the last built artifacts
until pruned. This is why retirement needs no soft-delete state machine: git IS the soft delete.

**Refusals.**
* Typed-slug mismatch; missing note; CSRF/session failures — the standard gates.
* **Last-survey guard**: refusing to retire the final remaining survey IF an empty corpus breaks
  the build (implementer verifies which; see D4). If an empty corpus builds clean, no guard.
* No linkage to pending submissions is enforced (a submission targets its own new slug); noted as
  a non-goal, revisit if intake ever allows appending to existing surveys (O-7/C44).

**Explicitly out of scope** (deferred): rename/lineage (C41 part B), bulk retirement and
retire-with-replacement choreography (C44-class — the corpus-swap shape stays operator),
tombstone/redirect pages for retired slugs (portal-side, post-launch polish).

## D3. Trust analysis

No new privilege: the action rides the exact machinery every metadata edit and station removal
already uses (C40 intact — no new mounts, no shell, no intent files; this is a PUBLISH action,
not an ops action, so D9 request-file hardening does not apply). The blast radius of a hostile
or mistaken click is bounded by git: one revertable commit, serving unchanged until a rebuild,
and the **session + CSRF + valid TOTP second factor + typed-slug + release-note** gates in
front of it (the TOTP factor is the D2 owner amendment, 2026-07-11 — this gate list was written
before the amendment and is corrected here to name it: an enrolled curator's *current, un-replayed,
rate-limited* code is required in addition to the typed slug, so a stolen session alone cannot
retire a survey). The audit trail is the commit itself (author fixed, curator name in the note per
the publish convention).

## D4. Verification (Invariant 10 — implementation lane carries these)

* **E2E pin**: remove flow produces exactly one commit whose diff is `git rm -r` of exactly the
  slug's paths (nothing else — survey-scope diff-minimality), note in body, PUBLISH_LOCK held.
* **Rollback pins**: injected git failure at each step (the `test_curator_publish` parametrised
  pattern) → fail-closed, checkout restored, loud error.
* **Typed-slug mismatch pin** → 400, checkout untouched (assert clean status).
* **Disclosure pin**: the confirmation page states the station count and the
  serving-until-rebuild reality (render assertions).
* **Revert pin**: `git revert` of the retirement commit restores the package byte-identically
  (round-trip on a real fixture package).
* **Empty-corpus stop-condition**: the implementer BUILDS an empty surveys-live and reports:
  clean build → no guard; broken build → last-survey refusal implemented + pinned. Do not guess.
  **RESOLVED (C41-IMPL, 2026-07-11): BROKEN → last-survey guard implemented + pinned.** Evidence:
  the real engine build against an empty `surveys/` exits **2** — `"pipeline produced 0 stations
  from 0 survey(s) attempted — failing the build (empty products are not a success). Use
  --allow-empty ..."` (verbatim; `engine/tests/test_empty_build.py::test_empty_build_fails_without_allow_empty`
  pins the same rc=2). The PRODUCTION serve path does NOT pass `--allow-empty`: `deploy/Makefile`
  `rebuild-data` invokes `build-runner --surveys /srv/surveys/surveys --out … --bundle-edi
  --products … --incremental …` with no `--allow-empty`, and `reconcile.sh` runs exactly that make
  target. So retiring the LAST survey empties the corpus, the next rebuild fails, and the retired
  survey keeps serving off the last good build indefinitely — the precise silent-drift failure this
  record exists to remove. The gateway therefore REFUSES to retire the final remaining survey
  (published-slug count == 1 ⇒ 409, nothing staged), pinned in the retirement flow tests.
* House rules: engine-truth fixtures, mutation-proofs for pins guarding new behaviour, UI
  browser-verified at the architect gate before any push block (standing rule 2026-07-11).

## Provenance

Owner directive 2026-07-11 (in-session); C43 D11 matrix row "Retire a survey — Stage 4, C41
record first" — gate opened for retirement only. Incident evidence: test-2026 serving duplicate
(hand-retirement error class), 2026-07-11 inbound-pull failures (DNS, .git perms) vs the
outbound publish path's unbroken record. Rename remains gated pending part B.
