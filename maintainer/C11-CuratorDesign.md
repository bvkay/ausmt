# C11 — Curator UI + publish flow: frozen security design (2026-07-06)

Status: **FROZEN for implementation.** Extends the C10 gateway (maintainer/C10-GatewayDesign.md,
now on main). C11 adds the human review half: a curator queue, a per-submission detail view with
the report bundle + a sandboxed portal preview, live checklist checks, and the three curator
actions — **Approve** (→ git → rebuild → PUBLISHED) / **Return** / **Reject**. Implementers do not
re-litigate these decisions; if one proves unimplementable, stop and bring it back here. Scope is
the demo-mode publish flow (merge-to-main-and-push on the operator's own surveys-live checkout);
the GitHub-App merge path is Slice 6 and slots into the same approve step later.

## 0. Invariants inherited from C10 (restated — do not weaken)

- The gateway process **never parses EDI/YAML content**. Curator publish shells out to git and to
  the **C12 `make rebuild-data` target** — it does NOT reimplement the build, and it does NOT parse
  package contents itself.
- Submitter PII (name/email/orcid) lives **only** in the SQLite DB. It is shown to the CURATOR
  (that is the whole point of capturing it) but still never written into the package, the commit,
  the generated data, or the public status page.
- Fail closed: a git failure, a rebuild failure, or a verify failure must leave `site-data/current`
  and `surveys-live` **exactly as they were**, move the submission to `PUBLISH_FAILED`, and surface
  the log to the curator. A partial publish is never left behind.
- Directories + git history are ground truth; SQLite is the index and audit log. Every curator
  action is one `transitions` row with `actor = "curator:<name>"`.
- The gateway is the ONLY DB writer; publish work runs inside the gateway process (not the runner).

## 1. New state machine (extends C10 §2)

```
VALIDATED ──curator Approve──► PUBLISHING ──git+rebuild+verify OK──► PUBLISHED
    │                              │
    │ curator Return               │ (git push fail / rebuild fail / verify fail)
    ▼                              ▼
 RETURNED                     PUBLISH_FAILED ──curator retry──► PUBLISHING
    │ curator Reject
    ▼
 REJECTED
```

- New states: `IN_REVIEW` (optional claim — see §4; MAY be skipped for the single-curator demo),
  `RETURNED`, `REJECTED`, `PUBLISHING`, `PUBLISHED`, `PUBLISH_FAILED`.
- New ALLOWED transitions (added to states.ALLOWED, the single source of truth):
  `VALIDATED→PUBLISHING`, `VALIDATED→RETURNED`, `VALIDATED→REJECTED`,
  `PUBLISHING→PUBLISHED`, `PUBLISHING→PUBLISH_FAILED`, `PUBLISH_FAILED→PUBLISHING` (retry).
  (If IN_REVIEW is implemented: `VALIDATED→IN_REVIEW` and `IN_REVIEW→{PUBLISHING,RETURNED,REJECTED}`.)
- `VALIDATED` stops being terminal (C10 §2 note already anticipated this: "curator actions reopen
  VALIDATED"). `PUBLISHED`, `REJECTED` are terminal. `RETURNED` is terminal for THIS submission —
  a revision is a NEW upload (new id, new token), which keeps the audit trail append-only and means
  a returned submitter cannot silently mutate a package the curator already saw.
- `PUBLISHING` is a transient working state; a crash mid-publish leaves it there and the poll loop
  reconciles it (see §5.4) — never a silent stick.

## 2. Curator authentication (SEPARATE from the submit key)

- **Distinct credential.** Curator auth is NOT the submit key (that is issued to submitters). New
  env `AUSMT_CURATOR_KEYS` = comma-separated `name:key` pairs (e.g. `curator1:<32+ char secret>`), so
  each curator action is attributable to a named actor in the audit log. Keys are compared with
  `hmac.compare_digest` against each configured key; **fail closed** — if `AUSMT_CURATOR_KEYS` is
  unset or malformed, every curator route returns 503 and the queue is unreachable (you cannot
  approve anything without a configured curator identity). Submit-key config stays independent;
  neither can authenticate the other.
- **Cookie session, HttpOnly.** A curator POSTs their key once to `POST /gateway/curator/login`;
  the server sets a `Secure; HttpOnly; SameSite=Strict` cookie holding a random 32-byte session
  token (stored sha256-hashed in a new `curator_sessions` table with an absolute expiry, default
  12 h). Rationale: the curator UI is multi-page with form POSTs; a header-only scheme would force
  JS to attach the key to every request, putting the raw secret in page memory. HttpOnly cookie
  keeps it out of JS entirely. Every `/gateway/curator/*` route (except `login`) requires a valid
  unexpired session or returns 401 (API) / redirects to login (HTML).
- **CSRF.** Because auth is now a cookie, every state-changing curator POST (approve/return/reject/
  retry/logout) requires a CSRF token: a per-session random value embedded as a hidden field in
  every rendered form and compared (constant-time) server-side. A missing/mismatched token → 403,
  no action taken. GET routes are side-effect-free. (The submit endpoint is unaffected — it is
  header-authenticated, not cookie-authenticated, so it is not CSRF-eligible.)
- **Same-origin only, still no CORS.** Curator routes set no CORS headers; the cookie is
  SameSite=Strict so a cross-site form cannot drive an action even with a live session.
- Curator PII exposure is deliberate and bounded: submitter name/email/orcid render **only** inside
  authenticated `/gateway/curator/*` HTML, never on the public `/gateway/status/*` page.

## 3. Routes (all under /gateway/curator/, all session-gated except login)

| Method | Path | Purpose |
|---|---|---|
| GET | `/gateway/curator/` | login form if no session, else redirect to queue |
| POST | `/gateway/curator/login` | validate a curator key → set session cookie (rate-limited, see §6) |
| POST | `/gateway/curator/logout` | clear session (CSRF-protected) |
| GET | `/gateway/curator/queue` | list VALIDATED + RETURNED + PUBLISH_FAILED, newest first: id, age, submitter, slug, WARN count, state |
| GET | `/gateway/curator/submission/{id}` | detail: report bundle, live checklist (§4), submitter block, preview link, action forms w/ CSRF |
| GET | `/gateway/curator/preview/{id}/...` | sandboxed static preview of this submission's built product (§7) |
| POST | `/gateway/curator/submission/{id}/approve` | require decision note → PUBLISHING → publish (§5) |
| POST | `/gateway/curator/submission/{id}/return` | require note → RETURNED; note surfaces on the submitter status page |
| POST | `/gateway/curator/submission/{id}/reject` | require note → REJECTED |
| POST | `/gateway/curator/submission/{id}/retry` | PUBLISH_FAILED → PUBLISHING (re-run publish) |

- `{id}` is validated against the Crockford-base32 id charset before any filesystem use (no
  separators possible, so no path traversal — same guard the C10 done-file ingest already relies on).
- Every action POST requires a non-empty free-text `note` (design §4 of the plan: "with note").
  Empty note → 400, no transition. The note is recorded in the `transitions.reason` column.

## 4. Detail view: live checklist (machine half of curator-checklist.md)

Rendered from data already on disk — the gateway does NOT re-parse the package. Each check is
PASS/WARN/FAIL/NA computed from: the runner's `reports/validate.json` (`items[]`), the
`reports/preview-summary.json`, and the submission row. The machine-checkable subset of
docs/docs/developer/curator-checklist.md:
- CI/validator green (no FAIL in validate.json items) — FAIL blocks approve (see §5 guard).
- ClamAV ran (submission passed SCANNED; post-unpack sweep clean — both already recorded).
- slug present and equals the package folder (from validate.json).
- licence recognised + redistributable-consistent-with-access (from validate.json).
- coordinate flags resolved-or-acknowledged (no unexplained `info_anomalous_review` in the preview
  summary's coord_flags).
- **no submitter PII in the package** — a check that greps the built preview product + package tree
  for an email pattern (design §7 of the plan; the submitter's own email from the DB is the needle,
  plus a generic pattern). A hit is a FAIL and is surfaced loudly: publishing PII is the one thing
  the whole PII-confinement design exists to prevent.
- DOI/PID present or absence acknowledged (WARN if absent — informational, never blocks).
The human-judgment half (the rest of the checklist) renders as static reminders next to the
required decision-note box. **Approve is refused server-side (not just UI-hidden) if any BLOCKING
check is FAIL** — the button being absent is UX; the 409 on POST is the guarantee.

## 5. Approve → publish (commit to git; rebuild is a SEPARATE manual step)

**Deployment decision (2026-07-06, operator): demo mode = commit-and-push only; the operator runs
`make rebuild-data` by hand afterward.** This is deliberate and it makes the C10 §0 no-Docker-socket
invariant hold CLEANLY: the gateway never invokes the build, so it never needs the socket. The
gateway's publish job is exactly one thing — write the approved package into the surveys-live git
history (the publication ledger). What appears on the live map is produced by the operator's
existing `make rebuild-data` run, identical to how every merged survey PR reaches the box today.
`PUBLISHED` therefore means **committed to surveys-live main and pushed** — NOT yet served. The
curator/status UI says so explicitly: "Committed to surveys-live. Run `make rebuild-data` on the
server to serve it." Do not overstate it as live.

Runs in-process in the gateway, in a background task (the request returns immediately with
PUBLISHING and the curator watches the state), single-flight (a module-level asyncio.Lock: only ONE
publish at a time, because they all mutate the shared surveys-live checkout). Sequence, **fail-closed
at EVERY git step — the entire git sequence is wrapped so a failure at ANY point rolls surveys-live
back to the captured pre-state and lands PUBLISH_FAILED**:

1. **Guard + pre-flight.** Under the publish lock: re-check state == VALIDATED (or PUBLISH_FAILED for
   retry) and no blocking FAIL (server-side 409 otherwise). **Pre-flight ABORT** (→ PUBLISH_FAILED,
   nothing staged) if the surveys-live checkout is not clean-on-main: `git status --porcelain` must
   be empty AND HEAD on `main`. Capture the pre-state ref (`git rev-parse HEAD`) and the current
   branch name BEFORE any mutation. Transition VALIDATED→PUBLISHING (audit row, actor curator:<name>).
2. **Stage.** Copy `quarantine/<id>/package/` → `surveys-live/surveys/<slug>/`. The slug comes from
   validate.json (not submitter-spoofable into a path) and is re-validated against the slug charset
   before it touches a path OR a branch name. A pre-existing `<slug>/` is a version-bump/collision:
   the copy replaces the tree ONLY when the curator set an explicit overwrite confirmation on the
   action (parsed as an exact token, not `bool(any-nonempty-string)`); otherwise ABORT.
3. **Commit + merge + push, ALL inside the rollback guard.** `git checkout -B submit/<slug>-<id>`,
   `git add surveys`, commit with fixed author `AusMT Gateway <gateway@ausmt.local>` and the audit
   metadata in the body (submission id, curator, decision note) but **NEVER the submitter email**;
   `git checkout main`; `git merge --ff-only` the branch; `git push origin main`. A failure at ANY of
   these (dirty tree surfacing, hook rejection, non-ff, push rejection) ⇒ `_rollback`: `git reset
   --hard <pre-state ref>` AND `git checkout <captured original branch>` AND clean untracked staged
   files under surveys/ ⇒ surveys-live is byte-for-byte the pre-state ⇒ PUBLISH_FAILED. The pre-state
   ref/branch captured in step 1 (never re-derived from "whatever is currently checked out", which
   a prior failed publish could have left on a submit branch).
4. **Success.** PUBLISHING→PUBLISHED (committed+pushed). Do NOT invoke any build. Surface the
   "run make rebuild-data to serve" guidance on both the curator detail page and the submitter
   status page.

- **No rebuild seam in the gateway at all.** The `make rebuild-data`/Docker-socket path is removed
  from the gateway; the operator runbook (deploy/README.md) documents the post-approve rebuild step.
  (If a future non-demo mode wants one-click publish, that is a SEPARATE host-side publish-runner —
  the C10 job-runner pattern — NOT a socket in the gateway; noted for Slice 6, out of scope here.)

### 5.4 Crash / failure reconciliation
- A submission stuck in PUBLISHING with no live publish task (gateway restarted mid-publish) is
  detected by the poll loop and moved to PUBLISH_FAILED with reason "publish interrupted" — never
  hanging, never auto-retried (a half-done git state needs human eyes).
- PUBLISH_FAILED is recoverable: the curator retries (re-runs §5 from step 1 — the pre-flight clean
  check catches a genuinely dirty tree and refuses rather than compounding it). Because the git
  sequence is fully rolled back on any failure, a PUBLISH_FAILED submission leaves surveys-live
  clean, so a retry starts from a known-good state.
- The publish lock is released in a `finally` so a failed publish never wedges the queue.

### 5.5 Residual accepted for the demo (operator decision)
The gateway holds the operator's git push credential (via the configured credential helper /
read-only mount) so it can push to the surveys-live origin. A fully-compromised gateway could
therefore write that origin — the blast radius the C10 §7.5 "cannot alter published history" note
warned about. Accepted for the single-operator tailnet demo; the credential is push-only to one
repo, every publish is a branch commit with the audit trail, and rebuild-from-git is the recovery.
Slice 6's GitHub App (App-signed merges, no ambient push credential in the gateway) closes it.

## 6. Abuse / hardening specifics
- **Login brute-force:** per-source-independent (no source trust on a tailnet) global rate limit on
  `POST /login` — N failures (default 5) in a rolling window ⇒ 429 with backoff, logged. Constant-
  time key comparison already prevents a timing oracle on which key matched.
- **Session fixation:** the session token is server-generated on successful login only; a client
  cannot set its own. Logout deletes the row. Sessions carry an absolute expiry, not a sliding one.
- **No secret in logs:** curator keys and session tokens follow the C10 redaction rule — never
  logged, `redacted_items()` extended to drop `AUSMT_CURATOR_KEYS`.
- **Preview sandbox:** see §7 — the single largest new attack surface.
- **git as subprocess only:** explicit `env` (no ambient creds beyond the operator's configured
  credential helper), `cwd` pinned to surveys-live, no `shell=True`, arguments as a list. The slug
  is charset-validated before it reaches a path or a branch name.

## 7. Preview sandbox (the biggest new surface — REVISED after review)

The curator sees the built preview as the portal would render it — but the preview renders
UN-curated, submitter-derived data, and it must NOT be able to run in the curator's authenticated
origin. The live portal is already hardened to serve untrusted data (Stage-0 XSS discipline), but
the NEW risk is that here that data runs alongside a curator session cookie: a portal-XSS in the
preview would escalate from "defaced page" to "curator session/CSRF-token theft → forged approve".
So isolation, not just the portal's own escaping, is the control.

- **The preview iframe is null-origin sandboxed.** `<iframe sandbox="allow-scripts">` (allow-scripts
  so the portal JS renders the map/drawer; **NOT** `allow-same-origin`, so the framed document has an
  opaque origin and cannot read the curator cookie, the parent DOM, or make credentialed same-origin
  requests). This is the actual isolation mechanism — get the tokens right: `allow-scripts` WITHOUT
  `allow-same-origin`. (The first implementation had them inverted — `allow-same-origin` without
  `allow-scripts` — which both broke rendering AND removed the isolation.)
- **No unsandboxed escape hatch.** There is NO "open preview in a new tab" link (a top-level
  same-origin navigation to the preview would run the portal JS in the curator origin, defeating the
  iframe). "Full size" is a CSS expansion of the SAME sandboxed iframe, never a navigation.
- **Subresource authorization.** The opaque-origin iframe's own subresource fetches (catalogue.json
  etc.) are credential-less cross-origin, so they do NOT carry the curator cookie. The preview
  SUBTREE is therefore authorized by the unguessable submission id in the path (a ULID — the same
  id the session-gated detail page embeds), NOT by the session. This is acceptable because the
  preview-data is already **embargo-safe and PII-scrubbed**: it is built by the same engine that
  enforces the C1b embargo withholding (an embargoed submission's preview curves are already empty)
  and the C3 derived-product PII scrub. The curator DETAIL page that embeds the iframe stays
  session-gated. Residual (documented): a tailnet member who obtains a submission id can view its
  (embargo-safe, PII-scrubbed) preview without a curator session — bounded by the tailnet and the
  unguessable id.
- **Path containment + charset.** `{id}` validated against the Crockford-base32 charset FIRST; the
  requested sub-path resolved and confirmed under `quarantine/{id}/reports/preview-data/` (reuse the
  runner's containment helper); `..`/absolute/symlink/encoded-traversal/backslash/null → 404.
- **Response hygiene.** Served with `Content-Security-Policy: default-src 'self'` +
  `X-Content-Type-Options: nosniff`; content-type from an explicit **extension allow-list** (html,
  js, css, json, svg, png, woff2, …) — an unknown/other type under preview-data 404s rather than
  being served with a guessed type (closes the hostile-file-in-preview vector the first pass added
  correctly and which we keep).
- The portal shell is the SAME committed portal/ code, pointed at the preview data root — no forked
  portal, no new JS.

## 8. Test contract (proven-failing-first where a guard is the deliverable)
pytest + httpx, gateway process only (git + make faked at their seams via injected callables, same
pattern as the C10 clamd/runner seams):
- auth: no session ⇒ every curator route 401/redirect; wrong curator key ⇒ 401, rate-limited after
  N; valid key ⇒ session cookie set HttpOnly+SameSite; expired session ⇒ 401.
- CSRF: approve/return/reject POST without the token ⇒ 403, NO transition, NO git call.
- state machine: only the §1 transitions are legal (extend the C10 property test); a blocking-FAIL
  submission ⇒ approve POST 409, no PUBLISHING.
- publish happy path (faked git+make): VALIDATED→PUBLISHING→PUBLISHED, package staged into a temp
  surveys-live, commit author is the fixed gateway identity, submitter email absent from the commit
  message, audit rows complete with actor curator:<name>.
- publish fail paths: git push fails ⇒ local commit rolled back, state PUBLISH_FAILED, surveys-live
  clean (proven-failing without the rollback); rebuild returns non-zero ⇒ PUBLISH_FAILED, `current`
  untouched.
- reject/return: RETURNED/REJECTED recorded with note; a returned submission's note appears on the
  PUBLIC status page but its submitter block does NOT.
- PII: grep the full curator-preview served output + the produced commit for the submitter email
  fixture ⇒ zero hits in the commit and zero in any published artifact (present only in curator HTML
  + the DB).
- preview sandbox: `..`/absolute path under /preview/{id}/ ⇒ 404; unauthenticated ⇒ 401.
- reconciliation: a PUBLISHING row with no live task ⇒ poll loop moves it to PUBLISH_FAILED.
CI compose e2e (extends the C10 e2e, through Caddy): submit `_example` fixture → (curator logs in)
→ approve → assert the survey appears in a freshly built catalogue and audit rows are complete;
reject path leaves surveys-live clean.

## 9. Explicitly out of scope for C11
ORCID/GitHub-App login and App-driven merge (Slice 6) · multi-curator concurrent review workflow
beyond the single publish lock · email notifications to submitters (status page is pull-only) ·
editing package contents in the UI (a revision is a fresh upload) · the add-survey "Upload to
AusMT" button (that is C13) · any change to the download/serve path (C10/Stage-0 already own it).

## Amendment A1 (C11b) — curator-acknowledgeable PII sweep (2026-07-06)

The frozen sections above are unchanged. This amendment records one refinement to §4's PII check,
specified in full in **`maintainer/C11b-PiiAcknowledge.md`** (the authoritative frozen design).

The §4 PII sweep is no longer a flat "any email ⇒ absolute block". It now classifies each hit:

- The **submitter's own email** (the DB needle) in any built artifact stays an **absolute** blocking
  FAIL — approve returns 409 and **no acknowledgement can override it** (C11b §0, the contract).
- A hit on **only non-submitter** addresses (e.g. a historical `>INFO` contact line in a source EDI —
  part of the archived record, not a gateway-created leak) is a blocking FAIL a named curator **may
  acknowledge** via an exact-token `ack_pii` form field (same parsing rule as `confirm_overwrite`).
  The acknowledgement is **per-action** and is recorded as a `PII-ACK (<n> file(s): …): <note>`
  prefix on the PUBLISHING transition reason — no schema change, file names only, never an address.

No new routes, no state-machine change, no DB schema change: the same VALIDATED→PUBLISHING transition
carries the acknowledgement in its existing `reason` column, and the server-side 409 remains the
guarantee (the checkbox's presence/absence is UX only).

## Amendment A2 (C31) — curator metadata editor (2026-07-06)

The frozen sections above are unchanged. C31 adds an **Edit metadata** flow to this curator UI —
loading a PUBLISHED survey's `survey.yaml`, editing the metadata subset, and committing the change to
`surveys-live` through the §5 publish primitives — specified in full in
**`maintainer/C31-MetadataEditorDesign.md`** (the authoritative frozen design). It reuses this
contract's invariants verbatim: the gateway never parses survey content (the YAML round-trip/merge/
validate happens in the runner/engine image), fail-closed git with byte-exact rollback, session +
CSRF on every route, commit-and-push only (committed ≠ served — the operator's `make rebuild-data`
serves it). New routes under `/gateway/curator/edit/*`; no new state-machine transition (a metadata
edit does not touch the submissions state machine), no DB schema change (the git history is the audit
record).
