# C10 — Submission gateway: frozen security design (2026-07-05)

Status: **FROZEN for implementation.** This document fixes every security-relevant decision left
open by the review plan (Review_2026-07-05/07 §§1–3, 09 C10). Implementers do not re-litigate
these choices; if one proves unimplementable, stop and bring the conflict back here — do not
improvise around it. Scope is the C10 MVP: upload → scan → validate → preview → tokenised status.
Curator actions, git publication, and the add-survey upload button are C11/C13 and are OUT.

## 0. Invariants inherited (restated so the implementer cannot miss them)

- The gateway **never parses EDI or YAML content**. Its deepest inspection of submitted bytes is
  the zip central directory (names, sizes, attributes) — never file contents.
- All content parsing (validator, engine preview) happens in the **runner** container:
  no network, non-root, resource-capped, with only the quarantine tree mounted.
- Submitter PII (name/email/ORCID) lives **only** in the gateway SQLite DB. It never enters the
  package tree, reports, job files, logs, or git.
- Fail closed everywhere: clamd unreachable ⇒ nothing advances; validator unresolvable ⇒ job
  fails ⇒ QUARANTINED; ambiguity ⇒ reject.
- **No docker socket** is mounted into any service. Job dispatch is a shared directory.
- ≤ ~1,500 lines for `gateway/` excluding tests. Bigger means wrongly scoped — stop.

## 1. Topology (compose profile `gateway`)

| service | image | user | network | mounts |
|---|---|---|---|---|
| `gateway` | new `gateway.Dockerfile` (python-slim + fastapi/uvicorn) | 10002:10002 | compose-internal; published **127.0.0.1:8444→8000** | `gw/state` rw, `gw/incoming` rw, `gw/quarantine` **ro**, `gw/jobs` rw |
| `clamd` | `clamav/clamav:stable` (official) | image default | compose-internal only | its own signature volume |
| `gw-runner` | the existing **engine image** (mt_metadata already in it) | 10002:10002 (compose `user:` override) | **`network_mode: none`** | `gw/incoming` **ro**, `gw/quarantine` rw, `gw/jobs` rw; plus two **read-only** supply mounts (see note): `surveys-live` **ro** (the validator) and the repo's `gateway/` **ro** (the runner package); **no site-data, no state, no writable mount beyond quarantine/jobs** |

- **Runner supply mounts (reconciled with implementation, review #14).** The engine image does NOT
  bake the validator — per ADR-001 `validate_survey.py` lives in the separate `ausmt-surveys` repo
  and is supplied at RUNTIME via a read-only bind mount (`surveys-live:/srv/surveys:ro`, exactly as
  `build-runner` already consumes it, located through `AUSMT_VALIDATOR_PATH`). The engine image also
  does not ship the `gateway/` package (it is the extraction engine, not the gateway), so the runner
  gets `${AUSMT_CODE_DIR}/gateway:/opt/gateway:ro` for its safe-extract + job-protocol code. Both are
  **read-only** and carry no writable/poison path: the runner still cannot reach the network, cannot
  write outside `quarantine/`+`jobs/`, and cannot touch site-data or state. The "nothing else" intent
  (no writable, no published-data, no network reachability) holds; these two read-only supply mounts
  are the mechanism by which the runner gets its validator + code without baking a second repo into
  the image.

- Host tree: `/srv/ausmt/gateway/{incoming,quarantine,jobs,state}` — **all owned `10002:10002`**
  (a NEW uid; 10001 stays the site-data/build identity so a compromised gateway stack cannot
  touch published data even via uid collision). Runbook gains:
  `sudo mkdir -p /srv/ausmt/gateway/{incoming,quarantine,jobs,state} && sudo chown -R 10002:10002 /srv/ausmt/gateway`.
- `gw-runner` gets compose resource caps: `mem_limit: 4g`, `cpus: 2`, `pids_limit: 256`,
  `read_only: true` rootfs + `tmpfs /tmp` (mt_metadata scratch).
- Public exposure: **through Caddy, same origin** — Caddyfile gains
  `handle_path /gateway/*` → `reverse_proxy gateway:8000` INSIDE the existing :8080 vhost.
  Result: no CSP change (connect-src 'self' already covers it), no CORS anywhere (the gateway
  sets no CORS headers and rejects preflight — same-origin only, by construction), no new
  tailscale serve path. The 127.0.0.1:8444 publish exists only for operator curl/debug.
- clamd is reached from `gateway` over the compose network (`clamd:3310`, INSTREAM). The
  runner cannot reach clamd (network none) — scanning is complete before any job is queued.

## 2. State machine (C10 subset) and ground truth

```
RECEIVED ──clamd hit──► REJECTED_AV            (raw zip deleted immediately; row + audit kept)
RECEIVED ──clamd clean─► SCANNED ──job:validate+preview──► VALIDATED
                            │  (unpack fails, validator FAIL, preview build fails,
                            │   job timeout/OOM, or second clamd sweep of unpacked tree hits)
                            ▼
                        QUARANTINED
clamd unreachable/stale ⇒ submission STAYS at RECEIVED ("scan pending" on status page).
```

- Directories are ground truth, SQLite is the index (recovery = rescan directories).
- Tables: `submissions(id TEXT PK, slug, state, created_utc, updated_utc, zip_sha256,
  zip_bytes, submitter_name, submitter_email, submitter_orcid, token_hash)` and
  `transitions(seq INTEGER PK, submission_id, from_state, to_state, actor, ts_utc, reason,
  report_ref)`. WAL mode; the **gateway process is the only DB writer** (the runner never
  touches the DB — it writes job-result JSON; the gateway's poll loop ingests results and
  performs the transition).
- `id` = ULID (sortable, non-guessable is NOT assumed — the token is the secret, not the id).

## 3. Authentication (every route)

- `POST /gateway/submit` requires header `X-AusMT-Submit-Key` == env `AUSMT_SUBMIT_KEY`
  (operator-issued to testers; compared via `hmac.compare_digest`; server refuses to start with
  it unset or < 16 chars). Tailnet position is transport, not authorisation.
- Upload response returns `{submission_id, status_url}` where `status_url` contains a
  **capability token**: 32 bytes from `secrets.token_urlsafe`, stored **sha256-hashed** in
  `submissions.token_hash`, shown exactly once. `GET /gateway/status/<token>` — path, never
  query string (query strings land in access logs). Unknown/invalid token ⇒ uniform 404 with
  identical body and timing (hash-then-lookup, no early exit).
- No cookies, no sessions, no user accounts in C10. Curator auth arrives with C11.
- **Exemption:** `GET /gateway/healthz` is unauthenticated by design — it is a liveness probe for
  the operator/compose that returns a fixed `{"ok": true}` and reveals nothing (no config, no
  counts, no submission data). "Every route authenticates" applies to routes that touch submission
  state or PII; the health probe deliberately does not, so that an unauthenticated liveness check
  works. This is the ONLY unauthenticated route.

## 4. Upload handling (`POST /gateway/submit`)

Multipart: `file` (zip) + fields `submitter_name`, `submitter_email` (required),
`submitter_orcid` (optional; checksum-validated if present — reuse the validator's algorithm,
reimplemented locally, NOT by importing validator code into the gateway).

Order of enforcement, all before any unpack:
1. `Content-Length` and streamed size ≤ `AUSMT_MAX_UPLOAD_MB` (default 250). Stream to
   `incoming/<id>.zip.part` in chunks (never whole-file in RAM), fsync, rename to
   `incoming/<id>.zip`. Overrun mid-stream ⇒ abort + delete part-file.
2. Disk headroom: refuse (503, `Retry-After`) unless free space on the gateway volume
   ≥ 3 × max-upload. In-flight cap: max `AUSMT_MAX_INFLIGHT` (default 8) submissions not yet
   terminal; per-key daily cap `AUSMT_MAX_PER_DAY` (default 25).
3. Central-directory checks (`zipfile` listing only — no extraction):
   - member count ≤ 2,000; declared uncompressed total ≤ 4 × max-upload;
   - per-member compression ratio ≤ 100:1 for members > 1 MiB compressed (zip-bomb);
   - reject: absolute paths, `..` anywhere, backslashes, names not matching
     `[A-Za-z0-9._ /-]+`, symlink/special external attributes, nested archive extensions
     (`.zip .tar .gz .tgz .bz2 .xz .7z .rar`), >1 `survey.yaml` at depth ≤ 2, zero `.edi`
     members, more than one top-level directory.
4. sha256 the zip; duplicate-content (same sha256, non-terminal state) ⇒ 409 pointing at the
   existing submission; slug is NOT parsed here (gateway doesn't read YAML) — slug lands in the
   DB later, from the validator report.
5. Row inserted (`RECEIVED`), audit row written, clamd INSTREAM scan of the zip:
   clean ⇒ `SCANNED` + job queued; hit ⇒ `REJECTED_AV`, zip deleted; clamd down ⇒ stays
   `RECEIVED`, retried by the poll loop.

## 5. Job protocol (`gw/jobs`, crash-only)

- Queue: gateway writes `jobs/pending/<id>.json` (tmp + rename) containing only
  `{submission_id, zip_path, quarantine_dir}` — no PII.
- Claim: runner loop renames `pending/<id>.json` → `running/<id>.json` (atomic same-fs rename =
  the lock). Runner then, inside its no-network container:
  1. safe-extracts the zip to `quarantine/<id>/package/` re-applying §4.3's rules per member
     during extraction (belt and braces, counting ACTUAL bytes read — not the central-directory
     file_size — against the extraction cap), with a hard wall-clock timeout (`AUSMT_JOB_TIMEOUT_S`,
     default 900) bounding the whole job. **Implementation note:** the timeout is enforced portably
     (a per-job deadline checked between phases + on each subprocess), NOT via SIGALRM — SIGALRM only
     interrupts the main thread and would not cleanly kill a runaway validator/engine *subprocess*.
     A heartbeat thread refreshes the running-file mtime so the gateway's dead-job sweep does not
     re-queue a legitimately slow (e.g. AusLAMP-national, ~1100 EDI) job;
  2. runs `validate_survey.py --json` (supplied via the `surveys-live` read-only bind mount, located
     through `AUSMT_VALIDATOR_PATH` per ADR-001 — NOT baked into the engine image; see §1's runner
     supply-mounts note) → `quarantine/<id>/reports/validate.json` (the validator writes
     `{"items":[...]}` — the status page renders those rows, absolute-path-stripped);
  3. runs the engine preview build of the single package →
     `quarantine/<id>/reports/preview-data/` + `preview-summary.json` (station count, types,
     coord flags, warnings);
  4. writes `jobs/done/<id>.json` `{outcome: validated|quarantined, reason, report_refs}` (tmp +
     rename) and removes `running/<id>.json`.
- Ingest: the gateway poll loop (asyncio task, every 5 s) consumes `done/*.json`, performs the
  DB transition + audit row, archives the job file into `quarantine/<id>/reports/`.
- Crash recovery: `running/<id>.json` older than 2 × timeout ⇒ gateway re-queues once, then
  `QUARANTINED` with reason "job died twice". A runner that reboots mid-job leaves only the
  stale running-file — no half-transitions (DB writes happen solely on ingest).
- The unpacked tree gets a second clamd sweep — performed by the **gateway** after ingest
  (clamdscan over `quarantine/<id>/package` via the clamd TCP INSTREAM per file, bounded count
  from §4.3) because the runner has no network. Hit ⇒ `QUARANTINED` (av_post_unpack).

## 6. Status page (`GET /gateway/status/<token>`)

Server-rendered single HTML template (stdlib `string.Template`, no framework, no JS, inline
style matching portal palette): state, timestamps, and — when present — the validator table
(PASS/WARN/FAIL rows), preview summary, and AV verdict. `QUARANTINED`/`REJECTED_AV` show reports
verbatim minus absolute paths. **Never** shows submitter fields back (a leaked status URL must
not leak PII). `Cache-Control: no-store`.

## 7. Config surface (env only, no config files)

`AUSMT_SUBMIT_KEY` (required) · `AUSMT_GW_DATA=/gw` · `AUSMT_MAX_UPLOAD_MB=250` ·
`AUSMT_MAX_INFLIGHT=8` · `AUSMT_MAX_PER_DAY=25` · `AUSMT_JOB_TIMEOUT_S=900` ·
`AUSMT_CLAMD_HOST=clamd` · `AUSMT_CLAMD_PORT=3310`. Secrets appear in no log line; startup
logs print config with the key redacted.

## 8. Test contract (proven-failing-first where a guard is the deliverable)

pytest + httpx (app in-process; clamd and runner faked at their seams):
- zip-slip member (`../evil`), absolute path, symlink attr, nested `.zip`, ratio bomb,
  member-count bomb, two survey.yamls, zero EDIs — each rejected at upload with distinct
  reasons, nothing written under `quarantine/`;
- oversize stream aborts mid-upload and leaves no `.part` file;
- clamd down ⇒ submission holds at RECEIVED and later advances when a fake clamd returns
  (poll retry); EICAR string via fake clamd ⇒ REJECTED_AV + zip gone;
- state machine property: only legal transitions possible; every transition = exactly one
  audit row; ingest of a forged/unknown `done/` file is logged and ignored;
- token: status URL from upload works; same token after DB wipe of the row ⇒ 404; wrong token
  ⇒ 404 with byte-identical body;
- PII: grep the whole `gw/` tree + job files + rendered status HTML for the submitter email
  fixture ⇒ zero hits outside the SQLite file;
- runner unit tests (no containers): safe-extract re-checks, SIGALRM timeout path, done-file
  atomicity.
CI compose job (real clamd + runner): submit the `_example` fixture package end-to-end ⇒
VALIDATED with populated reports; submit EICAR zip ⇒ REJECTED_AV. These are the Stage-2
acceptance scenarios from the roadmap.

## 9. Explicitly out of scope for C10

Curator queue/actions (C11) · git/publish (C11) · add-survey upload button (C13) · MTH5
uploads (D4) · CORS/cross-origin use · TLS (Caddy/tailscale own transport) · email
notifications · background threads beyond the one asyncio poll loop.

---

## Amendments (dated; the freeze discipline requires contradictions be recorded here, not ignored)

### A1 — 2026-07-07: invariant #6 (line budget) superseded; #1–#5 restated as binding

**What changed.** §0's final invariant — "≤ ~1,500 lines for `gateway/` excluding tests. Bigger
means wrongly scoped — stop." — was written for the C10 MVP scope (upload → scan → validate →
preview → status). The maintainer subsequently accepted four scope extensions, each with its own frozen
design: C11 (curator queue + git publish), C11b (PII acknowledge), C31 (metadata editor), plus
C13-adjacent server pieces. Measured at `a294b7b` (2026-07-07) the package is **4,692 non-test
lines**. The 2026-07-07 code-health review (finding F3) confirmed the breach carried no recorded
amendment — this section closes that gap. The budget is **retired**: it measured MVP scope, not a
security property, and pretending it still binds erodes the invariants beside it.

**What replaces it.** The property worth freezing was never the line count but the *mounted
surface*: the gw-runner container should carry only the job-protocol code it needs (runner/, job
files, zip safety) — today the **whole** `gateway/` package rides the read-only bind mount into
the network-none container, including curator-session, publish/git, and DB code. Cutting that seam
is queued (C37-adjacent); until it lands, treat "the runner mount is wider than necessary but
read-only, network-none, non-root" as the honest current state.

**What remains binding, verbatim, unweakened** — invariants #1–#5 of §0:
1. the gateway never parses EDI or YAML content (pinned by a source-assertion test since C31);
2. all content parsing happens in the runner container (no network, non-root, resource-capped);
3. submitter PII lives only in the gateway DB — never package tree, reports, job files, logs, or
   git (C11b added an *audited acknowledge* path for in-package generic-email hits; the
   submitter-email rule stays absolute);
4. fail closed everywhere;
5. **no docker socket in any service** — job dispatch stays a shared directory.

Any future reader finding one of #1–#5 contradicted in code should treat it as a defect or write
the amendment here — not conclude the list is aspirational.
