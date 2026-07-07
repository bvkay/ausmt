# C31 — Curator metadata editor (edit survey.yaml through the pipeline)

**Status: FROZEN 2026-07-06 (chief-architect design). Implementation must not deviate without an
amendment recorded here first.**

The maintainer's request: "a page where it's easy to edit this information which flows through all the
steps." Today the only edit path for a published survey's metadata is the GitHub web editor + PR.
C31 adds an **Edit metadata** page to the C11 curator UI that loads a published survey's
`survey.yaml`, lets the curator edit the metadata subset, enforces the project's semver discipline
(1.0.1 metadata fix / 1.1.0 additions / 2.0.0 reprocessed — the documented convention), shows the
exact diff + a real validator verdict, and on confirm commits + pushes to surveys-live through the
existing fail-closed publish machinery. Committed ≠ served, exactly as C11: the operator's
`make rebuild-data` serves it (cheap for metadata edits once the C18 cache is live).

## §0 Invariants

1. **The gateway still never parses survey content** (C10 house rule). All yaml reading, merging,
   re-emission, and validation happen in the **runner** (the network-none engine image) via the
   existing C10 file-queue job pattern. The gateway handles only form fields, job files, JSON
   reports, diffs-as-text, and git.
2. **Round-trip fidelity**: survey.yamls carry meaningful hand-written comments and may carry
   fields the form does not know. The runner-side merge uses **ruamel.yaml round-trip mode**
   (new dependency in the ENGINE/runner requirements only — never the gateway): unknown keys and
   comments are preserved byte-for-byte; only the edited fields change. A test proves the diff of
   an edit touches nothing but the edited fields + version + release_notes.
3. **Versioning is enforced at the surface** (closes hostile-review E-2 gap (a)): every edit that
   changes content REQUIRES a version bump (semver-greater than current; default suggestion =
   patch bump; minor/major selectable) and a mandatory `release_notes` entry
   `{version, date: today, note}` appended by the merge. Content changed + version unchanged ⇒
   the confirm step is refused server-side. A no-op edit (nothing changed) is refused outright.
4. **Curator-authenticated, per-action**: session + CSRF exactly like the C11 action handlers;
   the commit message records `metadata edit by curator:<name>: <note>` — the git history IS the
   audit record (no DB schema change).
5. **Fail-closed git**: reuse `publish.py` primitives (`preflight`, `PUBLISH_LOCK`, `_rollback`,
   scrubbed env, fixed author) — clean+on-main preflight, single-flight, byte-exact rollback on
   any failure, push with the mounted credential. No Docker socket, no new states; the edit flow
   does not touch the submissions state machine.
6. **No TOCTOU between preview and commit**: the confirm POST carries the sha256 of the exact
   new-yaml bytes the curator saw in the diff; the gateway re-hashes the job artifact before
   committing and 409s on mismatch (job re-run or a concurrent edit invalidates the preview).
7. **Scope**: edits ONE survey.yaml at a time. EDIs, slug, `coordinate_resolution`,
   `geographic_extent`, and anything EDI-derived are NOT editable in v1. The public portal gets no
   edit surface (unauthenticated); contributors still go through PR/gateway submission.

## §1 Flow

1. Curator queue/detail gains an **Edit metadata** link per PUBLISHED survey (list from
   surveys-live's `surveys/<slug>/` directories — a directory listing, not content parsing).
2. **Open**: gateway writes a `read` edit-job (slug); the runner parses the survey.yaml and
   returns the editable-subset as JSON (+ the full current version string). Gateway renders a
   server-side form (curatorpage.py style, escaped) seeded with those values.
3. **Submit**: gateway writes a `merge` edit-job containing the changed fields + chosen bump +
   release note. Runner: ruamel round-trip load → apply field patch → semver/no-op checks → run
   the REAL surveys validator on the patched package → emit new yaml bytes + unified diff +
   validator report JSON.
4. **Preview**: gateway renders the unified diff (escaped, no truncation) + validator verdict.
   Validator FAIL ⇒ no confirm button AND server-side refusal (the 409 is the guarantee).
   WARNINGs display but do not block.
5. **Confirm**: POST with CSRF + the §0.6 content hash → gateway takes PUBLISH_LOCK, preflight,
   writes the new survey.yaml into surveys-live, commits, pushes; rollback on any failure. Page
   shows "committed — run make rebuild-data to serve" (C11 wording).

## §2 Editable field set (v1)

`project_name/name`, `region`, `abstract`, `organisation{name,ror}`, `lead_investigator` /
`principal_investigators[]` (with the either/or rule the engine enforces), `publications[]`,
`funding[]`, `identifiers{dataset_doi,related_publication,related_publication_doi,project,
project_raid,survey_pid}`, `collection{...}`, `processing{...}`, `instruments[]` (incl. `pid`),
`time_series{collection_pid,levels_available}`, `access{level,embargo_until,contact}`, `license`,
`care{...}`, plus the §0.3-managed `version` + `release_notes`. The form groups them like the
add-survey page; every rendered value escaped; ORCID/ROR format hints text-only (no live API calls
from the curator page in v1).

## §3 Tests (gateway + a small runner-side suite; proven-failing-first for behaviour changes)

1. Round-trip fidelity: a survey.yaml with comments + an unknown custom key; edit one field; the
   emitted yaml diff touches ONLY that field + version + release_notes (comments/unknown key
   byte-identical).
2. Semver gate: content change + same version ⇒ refused; version lower/equal ⇒ refused; no-op
   edit ⇒ refused; valid patch bump + note ⇒ proceeds and release_notes gains the entry.
3. Validator FAIL on the patched yaml ⇒ preview shows FAIL and confirm 409s server-side.
4. §0.6 hash pinning: tampered/stale hash ⇒ 409, nothing committed.
5. Git failure at push ⇒ byte-exact rollback, curator sees the error, surveys-live clean.
6. Session/CSRF on every route; access.level flip to `embargoed` round-trips (the next rebuild
   withholds — covered by existing engine tests, assert the yaml lands correctly).
7. Hostile field values (XSS in abstract/note) render inert in form, diff, and report.
8. Gateway never gains a yaml import (source assertion: `import yaml`/`ruamel` absent from
   gateway/ — the C10 rule pinned as a test).

## §4 Docs + scope guards

- deploy/README: one section (edit flow, committed-not-served, ruamel added to the engine image).
- maintainer/C11-CuratorDesign.md: Amendment line pointing here.
- ≤ ~450 net non-test lines across gateway/ + runner/. No portal changes, no new containers, no
  DB migration, no submissions-state-machine change. STOP and escalate if any of those look
  necessary.
