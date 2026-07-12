# C43 — Curator Workbench (frozen design)

Owner directive (2026-07-10): per-station data view/edit is "quite hard — one long list with
fields"; collections have no curator UI at all; controls must be "expanded and made easier to use",
covering "all possible bases and scenarios". Sharpened by the NCI framing (owner, same day): Nirin
console access may be scarce — **the workbench could be the sole practical entry point** for
day-to-day operations, so its coverage boundary is drawn deliberately, not by accident.

The design ran as a four-round live mockup review (2026-07-10) and was **locked by the owner** at
v4. The approved mockup is archived at `maintainer-archive/C43-mockup-v4-approved.html` (operator
archive, outside this repo). This record is normative; the mockup is the visual reference it was
frozen from. Four freeze conditions attached by the architect are carried in D9–D12 and marked
**[FC-1]**..**[FC-4]**.

## D1. Current state (verified 2026-07-10, main @ 252a96f)

The gateway is a FastAPI app (`gateway/app.py:1367`, 1523 lines) whose pages are hand-assembled
strings — no template engine, no templates dir; the shared shell is a `string.Template` `_HEAD`
with inline CSS (`gateway/curatorpage.py:164`, `:50-75`), and all JS is served as same-origin
external route constants (`ui.js`, `serve-state.js`, `editor.js` — `app.py:1444-1462`) because the
CSP forbids inline script. The CSP is applied by Caddy, not the app
(`deploy/docker/caddy/Caddyfile:58-59`): `script-src 'self'` (no inline JS), `style-src` allows
`'unsafe-inline'` (which is what permits the inline `<style>` shell). What exists today:

* **Metadata editor** — one long form: a scalar panel + **11 structured section panels** + a
  CARE advanced-JSON panel + the bump/release-note tray, concatenated
  (`curatorpage.py:983-1021`; section specs `editor_form.py:46-113`). Everything submits at once.
* **Per-station view: ABSENT.** The only station-scoped page is the removal checkbox list
  (`app.py:1485`, handler `:825`).
* **Collections: built but invisible.** The engine rolls up `collection.id` across surveys
  (`engine/extract/build_portal.py:380-421`) and writes `collections.json` (`:2461`); the
  case/whitespace near-duplicate warning dies on build stderr (`:2458-2460`). The curator UI shows
  only the per-survey `collection` section panel — no rollup, no member list, no collision warning.
* **Serve panel** — published HEAD via injected git runner (`gateway/serve_state.py:100`),
  `reconcile-status.json` read (`:77`), and browser-side same-origin fetches of `/data/build.json` +
  `/data/build_report.json` — the gateway has **no site-data mount**. Exactly **one** intent file
  exists: `rebuild.request`, written atomically, content audit-only, host reconcile agent keys on
  existence and never parses it (`serve_state.py:30,44-48`). *(2026-07-11 owner ruling, ratified —
  FR2-1: the inline copy of this panel was REMOVED from the queue page; it lives only on the
  first-class `/gateway/curator/serve` screen now, with the ever-present drift chip carrying the
  published-HEAD glance. This removal is an owner decision, not architect judgment — the queue page
  is purely the queue.)*
* **Uploader keys** — mint/list/revoke with `created_utc` and `last_used_utc` already stored
  (`gateway/db.py:115-125`) **and rendered** (`curatorpage.py:1256-1257`). Missing: a free-text
  note, submission counts, an unused-key nudge.
* **Publish path** — gateway never parses YAML (`metaedit.py:1-7`); YAML round-trips only in the
  gw-runner (`gateway/runner/edit.py`), the validator verdict gates server-side with 409 on FAIL
  (`app.py:772-774`, `:927-929`), and git runs under `PUBLISH_LOCK` with fixed author + fail-closed
  rollback (`gateway/publish.py:45,49-50,350`).

## D2. Binding constraints (unchanged by C43, except the one D8 exception)

1. **C40 — the gateway gains no privileges.** No site-data mount, no docker socket, no host shell.
   Anything privileged rides the request-file pattern: the browser writes an intent file, a
   host-side systemd agent executes a fixed recipe.
2. **CSP `script-src 'self'`** — no inline JS on any `/gateway/*` page, ever. New JS = new external
   route constants, same as today.
3. **Publish-through-git** — every edit is a published commit with a version bump and a required
   release note; no drafts. Validator gate stays server-side.
4. **No-YAML-in-gateway** — the gateway process never parses or emits YAML; all survey.yaml work
   happens in gw-runner jobs.
5. **PII containment** — the gateway DB never enters any git repo. Key notes (D7) live in sqlite
   only.

## D3. Information architecture

Persistent left rail on every curator page: **Surveys**, **Collections** | Intake: **Submission
queue**, **Uploader keys** | Operations: **Serve state**. A context bar carries the breadcrumb, the
ever-present drift chip (`serving <build> · current|behind` + `published HEAD <sha>`), and the
Request-rebuild button. The scenario-coverage matrix (D11) is this record's checklist, **not a
shipped screen**. The submission queue keeps its proven review flow untouched (D6).

## D4. Survey hub

Route: one hub per survey, tabs **Overview & QA** (landing) / **Stations** / **Metadata** /
**History**. The hub replaces "one long list with fields" with task surfaces; QA lands first
because the commonest curator question is "is this survey healthy?".

**Overview & QA** — cards (serving/published counts, QA flag count, frame declaration, last build
time + engine sha), then **Needs attention**: every build_report warning/refusal rendered as an
actionable row — refused stations with their gate diagnosis and an inspect link, warning clusters
(e.g. a line-coherent quadrant cluster) grouped, metadata issues (e.g. an email address as citation
author) linking straight into the owning editor section. Refused stations stay in the published
package — withheld from serving only; the fix is custodian-side re-export and each row says so.
(Stage 1 renders each diagnosis inline and links to the existing station-removal list; the
drill-down "inspect" target activates in Stage 2 — no dangling links.)
A conditioning summary table lists honesty notes across served stations. Today all of this dies in
a build log; the QA tab is build_report made actionable.

**Stations** — filterable station table (id, lat/lon, periods, quality chip) with a drill-down
panel: facts (position + C42 policy, period band, frame declaration, convention verdict,
dimensionality, median relative error, tipper presence, source file + sha256), then plots, then the
C42 coordinate-policy fieldset (exact / generalised / withheld — a change publishes a survey.yaml
edit like any other), Save policy, Remove station.

* **Plots (owner-ruled specifics):** ρa (xy/yx); **φxy on a 0…90 axis with the Q1 band shaded**;
  **φyx on a full +180…−180 axis with the Q3 band shaded**; out-of-quadrant points drawn **red**;
  each phase plot carries a **verdict footer strip beneath the plot** ("expect Q1 (0…90°) — in
  quadrant ✓" / "expect Q3 — out of quadrant ⚠") so captions are never overlapped; tipper |T| with
  Re Tzx / Re Tzy. Wrong-quadrant stations must be identifiable at a glance. *(2026-07-11 owner
  ruling supersedes the mockup: both phases on a single ±180 plot — φxy and φyx share one axis, both
  expected bands shaded, one verdict strip carrying both component verdicts.)*
* **Data path (owner-ruled):** station facts and curve data come **browser-side, same-origin from
  the served `/data` corpus** — the serve-panel pattern (`curatorpage.py:363`), zero new gateway
  privileges. A new site-data mount is rejected.
* **[FC-2] Served-vs-published lag is labelled on the panel itself** — "facts from build
  `<build_id>`; publish pending" whenever served ≠ published — not only via the global drift chip.

**Metadata** — the existing editor restructured into a sticky section TOC + one section shown at a
time, **per-section submit** ("only this section is submitted"), inline field-level validation
(e.g. the email-as-citation-author trap gets a field error with the fix spelled out), per-section
advanced-JSON override, and the commit tray (semver bump select + required release note + "Preview
diff & validate"). Preview shows the exact YAML diff + validator verdict before anything commits.

**History** — read-only git log of the survey's package via a runner read-job (the gateway already
mounts surveys-live for publish; the runner does the reading). Rename & retirement actions land
here only after the C41 record freezes — until then they stay operator recipes.

## D5. Collections console

Honest model: **there is no collection object** — the id lives in each member's survey.yaml; the
console is a projection plus a batch-edit choreographer. The rollup is computed via gw-runner
read-jobs over surveys-live (same seam as the edit list; no schema change, no new privilege).

* List: collection, member count, station count, status; **the case/whitespace near-duplicate
  warning surfaces here at edit time** (today: build stderr, `build_portal.py:2458-2460`), with a
  one-click "merge into <id>" that is just a batch edit over the minority members.
* Create collection; edit all details (title, id/slug, type, status, description) with fan-out
  disclosure: "changing the id rewrites N member survey.yamls — shown as one batched confirm."
* **Batch semantics (owner-ruled): ATOMIC.** Saving previews one combined diff across all member
  surveys, validator-checked per survey; **any member failing validation blocks the lot**; the
  batch lands as N commits with one shared release note. Add/remove member and rename ride the
  same choreography.

### D5-A. Design freeze (2026-07-12 — owner-approved preview)

Normative visual reference: **`maintainer-archive/C43-collections-preview-approved.html`** (owner
sign-off 2026-07-12, rendered in the shipped dark workbench system). This subsection is
design-authoritative for the Stage-3 contract(s); where it sharpens the bullets above, it governs.

**Grounding (verified 2026-07-12, engine at `origin/main` 69d1e27).** The `collection` block is
Model B — it lives redundantly in **each member's `survey.yaml`**: `id, title, type, status,
start_year, last_updated, description` (`engine/tests/test_collections.py:38-41`; facet
`build_portal.py:654-663`; rollup `:381-422`; near-dup `:425-433`; stderr-only warn `:2573-2575`).
The rollup takes programme-level fields **from the first member that declares them** — so divergence
is real and silent today. `collections.json[id].surveys` holds member **labels, not slugs** (the
labels-vs-slugs trap that broke the stations tab, hotfix #33). Validator: id `^[a-z0-9]+(-[a-z0-9]+)*$`
and status ∈ {active,completed,archived} are **WARNING-grade, non-blocking**
(`vendored_validation/validate_survey.py:399-411`); title/type/start_year/description unvalidated.
The nav rail deliberately omits Collections today (`curatorpage.py:1088-1096`).

**A1 — information architecture: TWO server-rendered views** (owner-approved; supersedes the
mockup's single stacked screen), mirroring the shipped Surveys-list → survey-hub pattern:
* **Index** `GET /gateway/curator/collections` — summary cards, the list table (Collection ·
  Type · Members · Stations · Status), **New collection…**, and the inconsistency bands (A4).
* **Detail** `GET /gateway/curator/collections/{id}` — the fan-out edit form, the membership
  manager (A3), and the staged-batch bar. Full-width (`.wrap wide`), dark, reusing the shipped
  design system verbatim (`.cards/.chip/.panel/tables/.opsband`-derived bands). Collections joins
  the rail under the Surveys group.

**A2 — controlled vocabularies (engine truth, corrects the mockup):**
* **type** = `programme | release | institutional | other` (the docs vocab,
  `docs/.../collection-ids.md`; the mockup's *campaign/compilation* are dropped). type is
  validator-unenforced, so the console's select IS the guardrail; **also update the docs if this
  ever changes.**
* **status** = `active | completed | archived` (the mockup's "complete" would silently null on
  build — out-of-vocab is dropped, `test_collections.py:71-84`).
* **description = the reader-facing programme abstract** (portal collection page); a first-class
  multi-line field, fanned out like the rest. `start_year` editable; `last_updated` is
  gateway-managed on any edit (not hand-typed).

**A3 — membership manager (owner directive 2026-07-12: "easy to remove and/or add surveys,
intuitive").** A two-column surface on the detail view:
* **Current members** — one row per member (resolved by **slug**, read live from surveys-live —
  NEVER the rollup's display labels), each with one-click **remove**; a staged removal is visibly
  struck through with undo.
* **Add surveys** — a **searchable** picker (the shipped stations-filter pattern) over surveys
  **not** already in this collection, each showing its current membership: `no collection` vs
  `in "<other-id>" → moves`. Adding a survey that already belongs elsewhere is a **move** (its
  `collection.id` is rewritten) and the picker says so before commit.
* Adds, removes, field edits and normalise/merge all **stage together** into ONE atomic batch; a
  staged-changes bar shows what is pending; nothing is written until Preview → Publish.

**A4 — the projection surfaces EVERY inconsistency (owner ruling: detect + one-click normalise).**
Two honesty seams, both with a one-click remedy that is just a staged batch over the outliers:
* **Id near-duplicates** — ids differing only by case/whitespace (the existing
  `_near_duplicate_collection_ids` check, moved off stderr onto the index band) → **Merge into
  "<id>"** (batch-edits the minority members' id).
* **Per-field divergence** — members of one id disagreeing on a field (title/status/type/…) →
  a band on the index and inline `◆` markers on the detail form + a **Declares** column in the
  member list naming the outliers → **Normalise** (batch-edits the ◆ members to the chosen value).

**A5 — create = assign to ≥1 survey.** A collection with no members cannot exist (no object), so
**New collection…** collects the details AND an initial member; it is a batch that sets the block
on the chosen survey(s).

**A6 — atomic batch choreography (the load-bearing, publish-path core).** Stage → **Preview
combined diff** → for every affected survey build the `collection`-block patch, **validate each**
(the `_run_validator` seam, `runner/edit.py:436-465`); commit only if **all** pass, as **N commits
(one per affected survey, each version-bumped) sharing one release note**, under `PUBLISH_LOCK`,
with **fail-closed rollback of the whole batch** if any commit fails mid-apply. Version-bump per
member is accepted churn — it is exactly the existing single-survey collection-section edit applied
N times (owner acknowledged 2026-07-12). D13 atomicity pin governs: **member N fails ⇒ ZERO commits
land** (red-proven).

**A7 — implementation split (de-risks the write path; read-job proven before writes ride it):**
* **Stage 3a — read-only projection:** the gw-runner collections read-job (returns, per id: the
  rollup fields + each member's raw declared values + n_stations + near-dup groups + per-field
  divergence), the index + detail **views**, the inconsistency bands, nav gains Collections. No
  writes. Delivers the "see collections / spot the collision" value immediately.
* **Stage 3b — atomic batch writes:** edit / add / remove / rename / merge / normalise / create,
  all via A6. Rides 3a's read-job. Carries the atomicity + rollback + CSP + executable-JS pins.

### D5-B. Stage-3a gate findings + published-source framing (2026-07-12)

The 3a read-only projection passed a 4-lens adversarial gate + independent verify. **Security lens
CLEAN** (every field value escaped; the `<img onerror>` probe title rendered inert in a real
browser; read-job read-only; unknown id → 404). The parity lens surfaced that the runner's
**light reimplementation of the rollup drifts from the engine's `_group_collections`** in edge
cases — the fragility inherent to parity-by-reimplementation. Resolution:

**Framing (architect decision).** The console is a **PUBLISHED-SOURCE projection, NOT a
served-portal mirror.** It reads the `survey.yaml`s at published HEAD — the *edit* truth (correct
for an editing tool) and the only view that can compute per-member divergence (the built
`collections.json` has already collapsed divergence to first-declarer). It may therefore legitimately
differ from the *served* build until the next rebuild — the same published-vs-served lag the drift
chip already carries. Copy says so ("rolled up from every published survey.yaml"; served may differ
until rebuild); `n_stations` is the **published EDI-file count**, labelled as such (the portal's is
the post-gate served count). **Pin 1 is narrowed to SAME-INPUT parity:** the runner's rollup logic
must equal `_group_collections` *given the same member set* — the achievable, meaningful invariant
(a built survey's contribution matches the portal); it does not claim to reproduce the build's drop
logic. Build-dropped members (0-station / validation-FAIL surveys still carrying a `collection.id`)
ARE included in the published-source view by design; a "not currently building" flag is a 3b/enrich
follow-up.

**Fixes (same-input logic drifts the panel caught — all red-then-green):**
* **F1 (material)** out-of-vocab status drop moved INSIDE the per-member fold (mirror
  `build_portal.py:399-400`) so nulling an invalid status re-opens the slot for a later member's
  valid value; parity fixture: invalid-status-first + valid-later ⇒ rollup = valid.
* **F2 (minor)** membership predicate → engine truthiness (`if coll.get('id')`, drop `id: 0`/`False`).
* **F3 (material)** malformed-YAML per-survey resilience: catch the ruamel `YAMLError` (not just
  `OSError`) and drop-and-continue that one survey, mirroring `build_portal.py:810-817` — one bad
  file must not blank the whole console; **negative-control pin** added.
* **F4** published-source copy + `n_stations` label; parity-pin claim narrowed to same-input.
* **F5** rollup-parity pin strengthened to exercise F1/F2 edges (non-vacuous — imports the real
  engine fn on the same member set).

**Future hardening (noted, deferred — engine-touch, out of 3a scope):** parity-by-reimplementation
is drift-prone; a shared single-source rollup module imported by both engine and runner would
prevent this class permanently.

### D5-C. Stage-3b (batch editor) gate findings + fixes (2026-07-12)

The 3b WRITE path passed a 4-lens adversarial gate + verify (8 confirmed, 2 refuted). **The core
choreography was sound** — atomicity gate before any git verb, confirm re-applies+re-validates under
`PUBLISH_LOCK` (does not trust the preview), `cid` sanitised into the branch name, per-survey scoped
`git add`, whole-batch rollback; and **no XSS** (browser-verified inert across editor/membership/
preview/confirm). The findings cluster in three design seams, fixed as F1-F6 (all red-then-green):

**Design clarifications (governing):**
* **`last_updated` is EXCLUDED from divergence detection** (drop it from the runner
  `_collection_divergence` loop AND `curatorpage._COLLECTION_FIELDS`/`_divergence_summary`), kept in
  `_COLLECTION_ROLLUP_FIELDS` for engine parity only. It is a gateway-managed per-member timestamp,
  NOT a curator-reconcilable programme field — stamping it on only the changed members (diff-minimal)
  otherwise makes the console permanently report "members disagree on last_updated" with a Normalise
  remedy that has no form field to fix it. (**F2, material.**)
* **Numeric fields preserve type.** The desired-state form round-trips values as strings, so the
  no-op check must be type-tolerant (`str(_plain(cur)) == str(new)` ⇒ unchanged) and the writer must
  NOT force-quote all-digit numerics (`start_year`), else every edit silently re-types `2003` →
  `"2003"`, emitting a spurious diff line and a spurious commit on an untouched member — breaking the
  D13 diff-minimality / N-commits pins. (**F1, material.**)
* **Publish re-enforces the A2 guardrails under the lock.** The confirm re-validates for validator
  FAIL, but MUST also re-enforce the console's own A2 controlled vocab (id matches
  `_COLLECTION_ID_RE`; type/status in-vocab) and reject control chars/newlines in `cid` and `note`
  BEFORE committing — the client-carried `spec_json` is untrusted (an authenticated curator can hand-
  edit it). Rationale: the git history IS the audit record; a newline-laden `cid` interpolated into
  the commit body forges fake `Curated-by:`/`Approved-by:` trailers, and an out-of-vocab id/status is
  only a WARNING to the validator so it would otherwise publish past the console's own guardrail.
  (**F4, closes the two security-injection findings.**)

**Remaining fixes:** **F3 (minor)** rollback catches non-`PublishError` (an `OSError` on
`write_bytes` mid-batch) — broaden the guard, roll the whole batch back, re-raise; never leave
surveys-live on the `collbatch/` branch with partial commits (main is already protected — the merge
is after the loop). **F5 (minor)** a rename records the NEW id in the commit subject/branch/body (or
old→new), not the stale URL cid. **F6 (minor)** a slug landing in BOTH set and remove is de-duped so
one survey never gets two ops in a batch.

**Round-2 re-gate (2026-07-12, executed hostile probes over the F1-F6 commit):** F2/F3/F5/F6 and
the F4 headline (no client string reaches the git audit record ungated) CONFIRMED-SAFE with
executed evidence; three residuals, fixed as R1-R3:
* **R1 (material)** — F1's type-tolerant no-op check and the divergence detector's type-sensitive
  bucketing disagree: members declaring `start_year: 2003` (int) vs `"2003"` (quoted) flag as
  divergent showing two IDENTICAL values, while Normalise no-ops (400 "No changes") — an
  un-clearable "Need attention", the same dead-end pathology F2 closed. Divergence bucketing must
  use THE SAME equality as the no-op check for numeric fields (normalise numeric-string declared
  values when keying).
* **R2 (minor)** — `start_year` gets real validation: the gateway form and the publish-time A2
  gate both require empty or `^[0-9]{4}$` (clear 400 otherwise). Kills the executed traps:
  `"2003²"` (isdigit-true, int()-ValueError → opaque internal error) and `"007"`→`7` /
  `"0000"`→`0` silent literal rewrites. The emission coercion keeps a defensive
  isdecimal+try/except regardless.
* **R3 (minor, data-integrity)** — the A2 gate's op-block id branch used `re.match` with `$`,
  which matches before a trailing newline: a crafted block id `"auslamp\n"` passed the gate and
  committed (executed end-to-end; phantom-collection split — NOT a trailer forge, the top-level
  cid path is gated). Every regex gate on this seam moves to fullmatch/`\A…\Z` semantics + the
  control-char guard; the same trailing-newline class is checked across the seam's other
  anchored-regex gates.
* **Process incident (architect's own):** a round-2 probe agent mutated the shared worktree
  mid-verification (F4 gate briefly neutered on disk, then restored; probe files left behind) —
  the S2a D14 class again. Worktree verified restored byte-identical to the commit; standing rule
  re-affirmed and now stated explicitly in every verification dispatch: hostile probes run ONLY
  in hermetic exports (`git archive`), never in shared worktrees.

## D6. Submission queue — review flow unchanged. Review → checklist → sandboxed preview →
approve/return/reject was production-proven 2026-07-08; C43 deliberately leaves that flow alone.
The queue gains the shared nav + drift chip (Stage 1) and one additive surface: a **read-only
quarantine view** (Stage 2) — inspect a quarantined submission's contents and refusal reason;
the quarantine read-mount is verified at contract time.

## D7. Uploader keys

Deltas over today's page (created/last-used already render — D1): a **free-text note** per key
(who it's for, expiry intent — sqlite only, never git), **submission counts** from the audit
trail, an explicit **unused-key nudge** (active · never used), revoked keys retained as visible
audit rows, and a rotation-runbook link on the page. Lifecycle stays mint → use → revoke with
re-mint for rotation; key material is hashes-only and deliberately uneditable. The mint banner
stays shown-once with transmission guidance (one-time-secret link or phone — never plain email).

## D8. Serve state — operations floor

The panel is promoted to a first-class screen: the existing cards (published HEAD, served build +
currency, last reconcile, corpus counts) plus:

* **Operations floor** — four cards fed by a host-written **`ops-status.json`** in the state dir
  (same pattern as `reconcile-status.json`). The writer is the existing alert timer **with its
  recipe extended**: it already gathers service health, disk, reconcile staleness, and backup
  freshness; the C43 delta adds the code-checkout facts and the retained-build inventory to what
  it emits — that inventory is produced by nothing today. Cards: **Backups** (snapshot age, retained count, last drill verdict,
  off-box pull state), **Alerts** (dead-man ping beating, recipient display — recipients are
  managed in the alerting-service dashboard, not on the box), **Box** (uptime, disk, service
  health, ClamAV signature age), **Code checkout** (sha vs origin/main, last pulled, staleness
  chip). A stale checkout or overdue backup flips its card amber — the same facts the email alerts
  fire on, visible before the email arrives.
* **Retained builds** — table of retained build dirs (inventory carried in `ops-status.json`) with
  **"serve this build…" = rollback**: an atomic `current` swap to an already-verified retained
  build via `rollback.request` — it never rebuilds, it repoints; the next reconcile tick shows the
  drift honestly and must not auto-revert while a manual pin is in place. Each served/retained
  build row links to a **build detail** view: the build log tail plus the C18-A4 cache-forensics
  counters (salt_fp, write_errors/read_errors) surfaced from the build products — exact field
  locations verified at Stage-2 contract time (`maintainer/C18-BuildCacheDesign.md`, Amendment A4).
* **Backup snapshots** — table with drill verdict and off-box state, plus the **guarded restore**
  (owner-ruled, drill-first destructive op): stop gateway → **drill the snapshot first** (integrity
  + schema; a failing drill aborts untouched) → swap DB → restart → log the whole sequence.
  Confirmation requires **typing the snapshot id**; the dialog states exactly which submissions
  (received after the snapshot) are erased. Disaster restore (dead box) remains console territory:
  if the box can't serve this page, no button can help.
* **Actions** — Update box…, Snapshot now, Force full rebuild… (flag on `rebuild.request`), Pause
  auto-rebuild (a flag file the reconcile timer respects; **auto-expires after 6 h**; resume is
  explicit) — each writes an intent file for the host agent; nothing gives the gateway a shell.
* **Log tails** — the host agent copies recent build/reconcile log tails into the state dir for
  read-only display.

**Update box — the one bounded C40 exception (owner-ruled).** It runs exactly the standing refresh
recipe — `git pull --ff-only` on the code checkout, then `compose pull` + `up -d` — nothing
parameterised, nothing else runnable. Trust analysis: the recipe can only deploy what
branch-protected main has already built and published, i.e. the same thing deployed by hand today;
the request is curator-authenticated, CSRF-bound, audit-logged, serialised under a lock. Rationale:
at NCI it turns every merge-day console session into a button. This is a deliberate amendment to
the C40 container-lifecycle boundary, bounded to this single fixed recipe.

## D9. [FC-1] Request-file hardening spec (normative for every new intent file)

`rebuild.request` today is existence-keyed and content-ignored — safe because it is unparameterised.
C43 adds new intents in two classes: **id-carrying** (`rollback.request`, `restore.request` — the
first parameterised intents in the system) and **fixed/unparameterised** (`update.request`,
`backup.request`, and the pause flag — `rebuild.request`-class plain files; an implementer must
not invent parameters for these). All MUST satisfy:

1. **Fixed-enum intents only.** The host agent acts on a closed allow-list of intent filenames; an
   unknown file in the state dir is logged and ignored, never executed.
2. **Host-side validation is the real gate** (gateway-side checks are UX only): the rollback build
   id is validated against the real retained-build inventory; the restore snapshot id against the
   real snapshot list; ids must match a strict `[A-Za-z0-9TZ_.-]`-class pattern before any use; no
   attacker-controllable string ever reaches a shell — fixed recipes with allow-listed arguments
   only.
3. **Single-flight + rate limit.** One privileged action at a time under a host-side lock; repeat
   requests within the window are refused and logged.
4. **Audit line per action** — append-only log in the state dir carrying intent, parameters,
   requesting **curator name**, and outcome.
5. **Typed confirmation for restore** — the snapshot id typed by the curator is carried in the
   intent and re-checked host-side; mismatch aborts.
6. **Pre-NCI hostile re-audit flag:** `update.request` and `restore.request` are explicitly flagged
   for the pre-NCI hostile re-audit — neither ships to an internet-facing deployment before that
   audit passes.
7. **Persistent-pause alarm.** A slow re-arm of the pause flag (once per expiry window) keeps
   auto-rebuild dead forever while passing rule 3's rate limit. The reconcile status must
   therefore expose pause state, and a pause active or re-armed beyond **24 h cumulative** flips
   the ops-floor card amber and enters the alert-timer facts — an authenticated attacker (stolen
   session, curator-page XSS) cannot silently keep serving frozen.

### D9-A. Stage-2b-ii implementation gate (2026-07-12 — executed hostile panel)

The privileged-actions lane (host agent `deploy/scripts/actions.sh` + gateway buttons + access-log
enablement) passed a 4-lens adversarial + verify panel. **The host gate held** under a
compromised-gateway threat model — ids are charset-filtered AND matched against the real inventory
(never a path built from the untrusted id), the recipes reach no shell, restore drills-first-aborts,
swaps are atomic, CSP holds (external JS only) and every echoed value (`_esc`) incl. the host-written
audit tail. 7 findings confirmed (1 blocking), fixed S1-S6 (red-then-green). Two would have shipped
broken — the discipline earned its cost:

* **S1 (BLOCKING, privacy) — the access log leaked the real client IP.** `ip_mask` masked
  `remote_ip`/`client_ip`, but Caddy's JSON encoder logs the full `request>headers` map, and behind
  tailscale-serve the true client IP arrives UNMASKED in `X-Forwarded-For`/`X-Real-IP` — making the
  public promise ("a full IP is never stored") FALSE. Fix: delete every non-UA header from the log
  filter (C45 D2 "no headers beyond UA") + `trusted_proxies` (tailscale CGNAT 100.64.0.0/10 +
  loopback) so `client_ip` is the masked REAL client. **A privacy commitment needs a REAL-caddy
  runtime pin** (XFF request → log line has no unmasked IP anywhere) — config-syntax assertion is
  insufficient; ships wait-for-greens + a box smoke.
* **S2 (material, correctness) — `docker compose -C <dir>` is invalid** (`-C` is a git flag). Every
  compose call in update/restore errored on real docker and fell back to bare compose in the wrong
  CWD — the privileged actions were broken on the real box, MASKED by the shim tests. Fix:
  `--project-directory`; pin the ARGUMENT SHAPE so a shim can't hide a real-flag error again.
* **S3 (material, availability) — restore left the gateway STOPPED** on the mktemp-fail path (the one
  post-stop abort that skipped `up -d gateway`) — downs the sole ops surface with no in-band recovery
  during a disaster restore. Fix: restart on every post-stop exit.
* **S4 (minor) — audit-line forging:** `audit()` stripped only CR/LF; attacker-controlled
  `requested_by` (+ ids on refusal paths) could inject `outcome=ok` tokens and unicode line
  separators (which `splitlines()` breaks on) into the audit record the D9 model relies on. Fix:
  `tr -dc '[:print:]'` + outcome-first/quoted so no forged token precedes the host-computed one.
* **S5 (minor) — frozen-state visibility:** the persistent-pause alarm keyed on flag PRESENCE not
  FRESHNESS (diverging from reconcile's honoring criterion), and a standing `rollback.pin` froze
  auto-rebuild forever with no expiry/alarm — both mean a box can serve-frozen more silently than
  rule 7 intends. Fix: alarm on freshness; give the pin the same continuous-`first_seen` alarm.
* **S6 (promise precision) — "only aggregate counts are kept" is ahead of reality** (the aggregator
  is the later C45-impl lane; masked logs are retained ~7 d now). Promise text amended to what is
  true today; final wording owner-reviewed.

Lesson re-affirmed: shim-based tests must ALSO pin the real argument shape (S2), and a public
privacy property needs a runtime pin against real infrastructure, not a config assertion (S1).

## D10. [FC-3] [FC-4] Staging — each stage ships alone through the normal lane process

Stage discipline is a freeze condition: **no stage absorbs the next**; each stage is its own
contract, tests, adversarial review, owner push.

* **Stage 1 (thin):** nav shell + context bar/drift chip on all pages; survey hub with the
  **Overview & QA tab** and the **sectioned Metadata tab** (TOC, per-section submit, commit tray);
  **[FC-4] the editor diff-minimal YAML fix folds in here** (old task #32: the editor's
  section-assembly re-emits with formatting drift while the removal path is surgical — make the
  editor emit like the removal already does), so per-section "empty = unchanged" is **visibly true
  in diffs**. Stations/History tabs appear as links to existing pages (removal list) or not at all.
  No collections, no ops actions.
* **Stage 2:** stations drill-down (served-fetch data path, plots, [FC-2] lag label) + operations
  floor (ops-status.json) + retained-builds rollback, build detail + log tails + the **read-only
  History tab** (git-log via runner read-job — the Stage-4 rename/retire actions do NOT ride
  along) + the **read-only quarantine view** (D6) + keys deltas (D7) — pulled forward per the NCI
  sole-entry framing — **plus the D9 hardening**; the privileged writes (Update box, restore) ship
  only with D9 complete, never partially.
* **Stage 3:** collections console (atomic batch choreography).
* **Stage 4:** C41/C42-gated actions as those records land (survey rename/retire in History;
  coordinate-policy binding once the C42 engine lane exists).

## D11. Coverage checklist (adopted from the owner-final scenario matrix, v4)

| Scenario | Surface | Disposition |
|---|---|---|
| Review/approve/return/reject a submission | Queue (unchanged) | shipping today |
| Fix one metadata field without touching the rest | Hub › Metadata, per-section patch | Stage 1 |
| Survey health at a glance; act on warnings | Hub › Overview & QA | Stage 1 |
| Inspect one station (coords, QA, frame, conditioning, curves) | Hub › Stations panel | Stage 2 |
| Understand why a station was refused; know the fix | QA rows + station panel diagnosis | Stages 1–2 |
| Remove stations (validation preview) | Hub › Stations (existing flow, rehomed) | shipping today |
| Coordinate policy: exact / generalised / withheld | Station panel + survey default | Stage 4 (C42) |
| Set/clear embargo with disclosure | Hub › Metadata › Access | Stage 1 (rehome) |
| See collections; fix case-collision before it splits a programme | Collections console | Stage 3 |
| Rename a collection / move members (atomic batch) | Collections console | Stage 3 |
| Mint/annotate/revoke keys; spot unused keys | Keys | Stage 2 (small) |
| Rename a survey (slug) with lineage | Hub › History | Stage 4 (C41) |
| Retire a survey | Hub › danger zone | Stage 4 (C41) |
| Audit trail (who/what/when/why) | Hub › History (read-only git log) | Stage 2 |
| Monitor drift; request rebuild | Drift chip everywhere + Serve state | shipping today |
| Rebuild forensics (cache, salt, errors — A4 counters) | Serve state › build detail | Stage 2 |
| Backups/alerts/box freshness in one place | Serve state › ops floor | Stage 2 |
| Roll back serving to a retained build | "serve this build" (rollback.request) | Stage 2 (D9) |
| Force full rebuild (ignore cache) | Request rebuild › full flag | Stage 2 |
| Snapshot on demand before a risky edit | Snapshot now (backup.request) | Stage 2 |
| Read build/reconcile log tails | Serve state › logs | Stage 2 |
| Inspect a quarantined submission | Queue › quarantine view | Stage 2 (verify mount at contract time) |
| Update the box (pull code + images, redeploy) | Update box… (fixed recipe) | Stage 2 (D8/D9) |
| Restore gateway DB from snapshot (drill-first) | Serve state › restore | Stage 2 (D9) |
| Pause auto-rebuild during a multi-edit session | Serve state › Actions (auto-expiring) | Stage 2 |
| ClamAV signature freshness | Serve state › Box card | Stage 2 |
| Add/replace station files in a published survey | correction-linked resubmission | future (C44-class) |
| Batch multi-survey ops (bulk publish/retire, corpus swaps) | batch actions | future (C44-class) |

## D12. The deliberate boundary (NCI sole-entry planning)

Intentionally **outside** the workbench: container lifecycle beyond the D8 fixed refresh recipe,
bootstrap-key rotation in `.env`, and dead-box disaster restore. These need facility VM-console
access — worth securing that access path once, up front, precisely so it never becomes an email
chain in an emergency. Everything inside the boundary rides the request-file pattern.

## D13. Verification requirements (Invariant 10 — each stage's contract carries these)

* **CSP sweep** extended to every new page/route: no inline `<script>`, no `on*` handlers
  (pattern: `gateway/tests/test_serve_reconcile.py:295-314`). FAILS IF any new surface ships
  inline JS.
* **Diff-minimality pin (Stage 1, #32):** a single-field edit produces a diff touching only that
  field's lines. Must be proven **failing on the current emitter first** (red-then-green). The
  existing no-op pin (unchanged submit → NO diff, `test_editor_form_flow.py`) stays green.
* **Per-section patch pin (Stage 1):** submitting section A never rewrites section B's bytes.
* **Atomicity pin (Stage 3):** a collection batch where member N fails validation lands **zero**
  commits.
* **Request-file pins (Stage 2):** host agent refuses an unknown intent enum; refuses a rollback id
  not in the inventory; refuses a restore whose typed id mismatches; every action writes its audit
  line. Each refusal case proven able to fail.
* **Pause-expiry pin (Stage 2):** with a pause flag older than 6 h, the reconcile timer treats
  auto-rebuild as ACTIVE and the flag as expired. FAILS IF a stale pause flag still suppresses
  reconcile — proven against a never-expire implementation first.
* **Persistent-pause pin (Stage 2):** a pause re-armed past the 24 h cumulative threshold surfaces
  in the reconcile-status/ops facts. FAILS IF a slow-drip re-pause stays invisible.
* **Rollback-repoints pin (Stage 2):** after a `rollback.request` naming a retained build,
  `current` points at that build dir and the build inventory is unchanged (no new build dir, no
  engine invocation). FAILS IF rollback triggers a rebuild or leaves `current` unswapped.
* **Update fixed-recipe pin (Stage 2):** the host agent executes the identical fixed refresh
  recipe regardless of `update.request` content — a request carrying unknown/extra fields is
  refused (or the fields provably ignored) and logged. FAILS IF request content can vary the
  executed commands.
* **Single-flight pin (Stage 2):** a second privileged intent arriving while one is in flight is
  refused and logged. FAILS IF two privileged recipes can run concurrently.
* **Lag-label pin (Stage 2):** with served ≠ published fixtures, the station panel shows the
  [FC-2] label.
* **No-YAML-in-gateway pin:** the gateway process still never imports a YAML parser.
* Standing lane rules apply unchanged: full CI-leg mirror before push-ready, authorship audit,
  content-verified merges.

## D14. Stage-2a hostile security review (2026-07-10) — D2 constraint outcomes

Adversarial review of the S2a curator surfaces (quarantine serving, history read-job, key notes,
stations JS) against the D2 binding constraints. Diff: 5 commits (d62a7f6…fb4514b).

**D2 constraints — verified UPHELD:**

* **D2.1 (gateway gains no privileges).** The Stations tab and history use existing surfaces: the
  stations JS reads the same-origin served `/data` corpus (no new mount); the history git read runs
  in the **runner** (which already mounts surveys-live read-only), not the gateway, via a `history`
  read-job — the gateway issues no new git verb. UPHELD.
* **D2.2 (CSP `script-src 'self'`).** STATIONS_JS ships as an external route constant
  (`/gateway/curator/stations.js`), no inline JS. Source sweep pins assert no `<script>` wrapper, no
  `on*=` handler, no `innerHTML`-with-data path (SVG built via `createElementNS`, all values via
  `textContent`). The quarantine file route serves untrusted submitter bytes under
  `default-src 'none'; sandbox` + `nosniff` + `Content-Disposition: attachment` (no filename → no
  CRLF-injection surface) + `application/octet-stream`. UPHELD.
* **D2.5 (PII containment — DB never enters git).** Key notes are sqlite-only; a pin
  (`test_key_note_absent_from_git_bound_artifacts`) greps surveys-live for a note needle and asserts
  absence. Quarantine list/detail expose id/slug/updated/reason only — **no submitter email**. UPHELD.

**Path containment (quarantine file route).** `root not in target.parents` on `resolve()`-d paths,
mirroring the preview sandbox. `is_valid_id` (26-char Crockford base32, no separators/dots) gates the
id before any path build. Symlinks are rejected at unpack (zipsafety S_IFLNK → ZipRejection) AND
`resolve()` dereferences any that exist so an out-of-root target 404s; the listing separately skips
`is_symlink()`. Traversal pin plants a real out-of-root file and confirms 404 (non-vacuous). SOUND.

**History read-job argv.** Slug is `_SLUG_RE`-validated (cannot start with `-`) before it reaches
`-C package_root`; the argv is fully hardcoded (read-only `log` verb + `-c safe.directory=<resolved
surveys_root>` + `--` pathspec); `-c safe.directory` is interpolated from a **resolved** path, not a
request field. An allowlist guard (`_HISTORY_READONLY_VERBS = {"log"}`) plus a mutation-proof pin
back the read-only assertion. Author/subject/body are `_esc`'d on render. SOUND.

**Residual items — ALL RESOLVED in the same lane's fix round (commits 03d5f2b/6594eb0/80384c1),
before any push:**

* Stations JS relative fetch URLs (would have 404'd the whole tab in deployment) → fixed: all
  fetches ride single-sourced absolute `dataUrl()`/`stationJsonUrl()`; pinned by an executable
  Node URL-construction test proven red against the pre-fix JS. The same fix round also corrected
  the JS `wrap180` truncated-`%` divergence from Python (found by the physics lens) and replaced
  the source-string parity pin with an executable Node parity pin — **standing rule from this
  lane: browser JS gets executable test coverage from the start; string pins alone are banned.**
* Uploader note length cap → fixed: note ≤ 2000 / name ≤ 120 / email ≤ 254, server-side REJECT
  with 400 (never silent truncation), pinned.
* Revoked-key note POST → the "by-design" docstring was overruled at the architect gate (D7 says
  read-only audit rows): route 409s on a revoked id + `AND revoked_utc IS NULL` in the DB layer,
  both guards independently pinned.

## D15. Stage-2b-i record amendments (serve-state promotion + operations floor, 2026-07-11)

Recorded per the freeze rule (D13/Invariant 10 amendment discipline, as D14 was). Stage 2b-i is the
**READ-ONLY** half of Stage 2: the serve panel becomes a first-class screen and the operations floor
lands, **without** any privileged intent file, the pause flag, or any action button — those are Stage
2b-ii, gated on the full D9 hardening. Two owner/incident-driven amendments to the frozen record:

### D8 amendment (operations floor — the ops-status.json writer + freshness + sync loudness)

Refines and supersedes the D8 "Operations floor" bullet where they differ:

* **The ops-status.json writer is the existing alert timer with its recipe EXTENDED** — not a new
  agent. `deploy/scripts/alert.sh` (on `ausmt-alert.timer`, every ~15 min) already gathers **service
  health, disk, reconcile staleness, and backup freshness**; the C43 delta ADDS, and emits into a
  host-written `ops-status.json` in the gateway state dir (the `reconcile-status.json` pattern —
  tmp+mv atomic, group-readable by the gateway container): **code-checkout sha vs its origin,
  surveys-live sha vs ITS origin, the retained-build inventory** (produced by nothing today), and
  **recent build/reconcile log tails copied into the state dir** (bounded, ~60 lines each) so a
  shell-less curator can read forensics the gateway has no mount to reach. The gateway reads this file
  **server-side** (exactly the `reconcile-status.json` seam — `gateway/serve_state.py`; no new mount,
  C40 intact).
* **The freshness card covers BOTH repos vs their origins**, not just the code checkout. Incident
  2026-07-11 (owner-experienced): a stale `surveys-live` sat **4+ h behind GitHub** while the drift
  chip read "current" — because the chip compares the *served* build against the *local* published
  HEAD, and both were the same (stale) local sha. The freshness card therefore shows **code checkout
  AND surveys-live**, each local sha vs its last-fetched origin ref, a behind repo flipping its row
  amber. (Honest labelling: the card reflects the last **successful** fetch; a fetch that never
  reaches origin is the sync-strip's job below — the two are complementary, and BOTH are required to
  make the incident visible.)
* **reconcile sync state is surfaced loudly on the ops floor.** A `sync_failed`/sync-error streak is
  a **first-class amber/red condition** — a loud band on the serve screen, driven by the fresh
  `reconcile-status.json` `action` (not gated behind ops-status staleness), enriched with the streak
  count/duration when derivable from ops-status. Incident-backed: the `sync_failed` **hid for 4 h**
  buried in `reconcile-status.json` while nothing on the curator surface said the box could not reach
  GitHub. A stale or missing `ops-status.json` (older than ~2 timer periods) makes every dependent
  card render an explicit **STALE** state — never last-known-good silently.

Still explicitly OUT of Stage 2b-i (Stage 2b-ii, per D8/D9): "serve this build…" rollback, the
guarded restore, Update-box, Snapshot-now, Force-full-rebuild, Pause auto-rebuild — every privileged
action and its intent file. The retained-builds table, build-detail (log tail + the C18-A4
cache-forensics counters), and the backup-snapshots table ship **read-only** here, with **no action
controls rendered at all** (omitted, not disabled placeholders).

### D4 amendment (stations-tab layout, as shipped — owner-final 2026-07-11)

The Stage-2a Stations tab shipped a **split layout**, owner-ruled final 2026-07-11: the station
**list on the LEFT** inside a fixed-height, independently scrollable container (a >300-station survey
scrolls within the list and never pushes the panel off-screen; the filter box sits above the scroll
region), the **data panel on the RIGHT**, and **panel-first stacking on narrow** viewports (the panel
is DOM-first so it stacks above the list at one column with no `order` needed). Codified so the
frozen record matches `gateway/curatorpage.py` `.stations-split` as deployed.

## Provenance

Mockup v4 approved and locked by the owner 2026-07-10 after four live review rounds; archived at
`maintainer-archive/C43-mockup-v4-approved.html`. Owner rulings incorporated: φyx on a full
+180…−180 axis with verdict strips beneath plots; atomic collection batches; served-fetch station
data path; Update-box as the bounded C40 exception; guarded drill-first DB restore; keys carry
creation dates (already true — D1) plus notes; ops floor covering backups, alerts, uptime, git
pull/version. Current-state map verified against main @ 252a96f the same day.
