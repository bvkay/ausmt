# AusMT deployment runbook

Run the AusMT portal (and, optionally, the submission gateway) with Docker Compose on **any**
Linux, macOS, or WSL box with Docker. The portal is a Caddy-served static site fed by an on-demand
engine job container; the optional gateway adds an upload → scan → validate → curate → publish
pipeline. Images are pulled from GHCR; the `rebuild-data` pipeline (build → verify → atomic swap)
lives in `deploy/Makefile`.

> **One checkout, one location.** Everything below refers to your single checkout of this repo as
> **`$AUSMT_CODE_DIR`** — its location is your choice (`~/ausmt-code`, `/srv/ausmt/code`, wherever).
> Pick one, set it in `deploy/.env`, and use it everywhere. Running compose/`make` from a *second*,
> stale checkout is the single most confusing failure mode (you edit one tree and deploy another).
> To confirm which checkout is live at any time:
> ```sh
> git -C "$AUSMT_CODE_DIR" log -1        # the commit this deploy is actually running
> ```
> `make preflight` reports this for you.

---

## 1. Any-PC quickstart (no Tailscale, no special hardware)

This brings the **portal** up on `http://127.0.0.1:8443` on a fresh machine. The gateway and the
Tailscale exposure are separate, optional steps (sections 3 and "Expose to your tailnet").

```sh
# 0. Prereqs: Docker Engine + Docker Compose v2  (`docker compose version` works).

# 1. Clone both repos. AUSMT_CODE_DIR is wherever YOU put this repo — remember the path.
git clone <ausmt-url>          ~/ausmt-code            # this repo (engine/ gateway/ deploy/)
git clone <ausmt-surveys-url>  /srv/ausmt/surveys-live # the survey data the engine reads
export AUSMT_CODE_DIR=~/ausmt-code
cd "$AUSMT_CODE_DIR/deploy"

# 2. Configure: copy the template and set the two always-required vars.
cp .env.example .env
#   edit .env:  AUSMT_DATA_DIR=/srv/ausmt   OWNER=<the GHCR namespace the images were pushed under>

# 3. Preflight: read-only check that everything is in place (see "First-run checklist" for the
#    one-time host setup it will tell you to do — dirs, ownership, etc.).
make preflight

# 4. Pull images. NOTE the profiles: a bare `docker compose pull` misses the engine + gateway
#    images. Pull EVERYTHING:
docker compose --profile jobs --profile gateway pull
#    (on compose v2.24+ the shorthand `docker compose --profile "*" pull` does the same.)

# 5. First data build — the portal serves site-data/current, which does not exist until one build
#    has run. `make` reads AUSMT_DATA_DIR from the shell:
export AUSMT_DATA_DIR=/srv/ausmt
make rebuild-data

# 6. Start the always-on portal and smoke-test.
docker compose -f compose.yaml up -d
make smoke
```

Open **http://127.0.0.1:8443** — the AusMT map. That's the whole portal deploy. Everything past
here (gateway, curator, Tailscale) is optional.

### First-run checklist (one-time host setup)

`make preflight` will flag each of these with the exact fix command; here they are in one place.
The **ownership split is by WHO WRITES each subtree** — this is real, not ceremony (the first live
deploy hit `PermissionError: /out/builds` until it was set):

```sh
# --- site-data: the ONLY container-written portal tree, owned by the engine user (uid 10001) ---
sudo mkdir -p "$AUSMT_DATA_DIR/site-data"
sudo chown -R 10001:10001 "$AUSMT_DATA_DIR/site-data"

# --- surveys-live: clone as YOURSELF, leave ownership alone (chowning it to 10001 breaks git pull;
#     it is mounted read-only into containers, and git's world-readable perms are all they need) ---
git clone <ausmt-surveys-url> "$AUSMT_DATA_DIR/surveys-live"

# --- .env: the two required vars (portal). Add the gateway block only if you run the gateway. ---
cp "$AUSMT_CODE_DIR/deploy/.env.example" "$AUSMT_CODE_DIR/deploy/.env"
#   set AUSMT_DATA_DIR and OWNER (see .env.example for every variable, grouped + commented)
```

**Gateway-only** one-time setup (skip unless you run the gateway — section 3):

```sh
# --- gateway tree: a NEW uid 10002, deliberately distinct from the engine's 10001 (a compromised
#     gateway must not touch published site-data even via a uid collision) ---
sudo mkdir -p "$AUSMT_DATA_DIR/gateway/incoming" "$AUSMT_DATA_DIR/gateway/quarantine" \
              "$AUSMT_DATA_DIR/gateway/jobs" "$AUSMT_DATA_DIR/gateway/state"
sudo chown -R 10002:10002 "$AUSMT_DATA_DIR/gateway"
# (gateway/clamav/ — the AV signature volume — is created by compose on first start; leave it
#  root-owned. Only the four dirs above are written by the 10002 services.)

# --- submit key (>= 16 chars) + curator keys, into deploy/.env ---
python3 -c "import secrets; print('AUSMT_SUBMIT_KEY=' + secrets.token_urlsafe(32))"
python3 -c "import secrets; print('curator1:' + secrets.token_urlsafe(32))"   # a curator name:key pair

# --- git-creds dir for the curator publish push (a deploy-key ssh dir, or a git credential file) ---
mkdir -p "$AUSMT_DATA_DIR/git-creds"   # populate with a deploy key / credential file, then:
#   set AUSMT_GIT_CREDS_DIR=$AUSMT_DATA_DIR/git-creds in deploy/.env
```

Then re-run `make preflight PROFILE=gateway` until it is all PASS (WARNs are advisory).

---

## 2. Data operations

### Rebuild the served data

```sh
export AUSMT_DATA_DIR=/srv/ausmt   # make reads this from the shell, not from .env
make rebuild-data
```

`rebuild-data` runs the C12 pipeline **entirely in-container as uid 10001**: build into a fresh
`builds/<timestamp>/` → `verify.py --data-dir` gate → atomic `current` swap (temp-symlink + `mv -T`,
a true rename so readers never see a missing/half `current`) → prune to the 5 newest builds. A
failed build or verify leaves `current` untouched and exits non-zero with the failed dir's path.
**Never hand-`ln` the `current` symlink from the host** — `site-data` belongs to the container user,
so a host-side swap gets `Permission denied` (exactly what the first real deploy hit after build +
verify had already passed).

### Sync the surveys checkout

```sh
make sync-surveys      # git pull --ff-only on $AUSMT_DATA_DIR/surveys-live
```

Fast-forward-only: it refuses (non-zero) rather than merging/rebasing if the local checkout has
diverged. Do this before `rebuild-data` when the surveys repo has moved.

### C18 incremental build cache

`rebuild-data` builds with `--incremental --cache-dir /out/cache --cache-mode rw` (the ONE place the
cache is on). A metadata-only edit reuses cached per-station products for every UNCHANGED station, so
only touched stations re-parse — a full ~8-min (national-scale ~30-min) rebuild drops to seconds for
a small change. Operator-relevant facts:

- **Bytes never change, only speed.** Every cache entry embeds a sha256 verified on read (a
  corrupt/tampered entry is deleted, counted in `build_provenance.json`, recomputed from source). A
  stale entry cannot exist by construction (the key is the source EDI content sha + salts).
  `verify.py` still runs full and byte-re-hashes the served tree before the swap. A CI test pins the
  warm build byte-identical to the build that populated its cache.
- **Location.** `${AUSMT_DATA_DIR}/site-data/cache/` — a **sibling** of `builds/`, owned by uid
  10001. It survives the `builds/` prune and the `current` swap, and is **safe to lose entirely**
  (one slow rebuild rebuilds it). Do NOT move it under `builds/` or `surveys-live/`.
- **One cold rebuild after an engine update (expected).** The cache salt includes the engine commit
  (`docker/engine.Dockerfile` bakes `ARG GIT_SHA` → `ENV AUSMT_ENGINE_COMMIT`; `deploy-images.yml`
  passes `github.sha`). After you `pull` a NEW engine image, the salt changes, so the FIRST
  `rebuild-data` runs full (cache miss on every station) and repopulates the cache; the next rebuild
  is fast again. This is correct, not a fault. A degenerate salt (unknown engine commit, or a dirty
  checkout) also disables the cache for that build — the log prints `note: C18 cache DISABLED …` and
  `build_provenance.json` records `cache.enabled:false` + the reason.
- **Force a full re-verified rebuild** that still repopulates the cache: run the engine with
  `--cache-mode refresh` (e.g. after an engine upgrade you want re-verified from scratch). Size is
  capped by `AUSMT_CACHE_MAX_MB` (default 2048), pruned oldest-first per successful build.

### Update to a new image tag

```sh
# bump TAG in deploy/.env first if you pin to a release rather than "latest", then:
docker compose --profile jobs --profile gateway pull    # refresh ALL images (see troubleshooting)
docker compose -f compose.yaml up -d                    # recreate only what changed
make sync-surveys && make rebuild-data                  # if surveys moved / to serve the new engine
```

---

## 3. Gateway + curator (optional)

The submission gateway (contracts C10/C11) is an **optional profile** — the portal does not depend
on it. It adds upload → virus-scan → validate → preview → curator-review → commit+push, reachable
same-origin under `/gateway/*` (Caddy reverse-proxies it; no CSP/CORS change). Four services run
under the `gateway` profile: `gateway` (FastAPI), `clamd` (AV), `gw-runner` (the engine image
re-tasked as a no-network job runner), and the AV DB volume.

### Start / stop

```sh
docker compose -f compose.yaml --profile gateway up -d
```

A bare `docker compose up -d` (the portal) never starts these. `clamd` downloads its signature DB on
first start (give it a minute; until ready, uploads correctly hold at `RECEIVED`). Operator debug:
`curl 127.0.0.1:8444/gateway/healthz` (loopback); real traffic goes through Caddy at `/gateway/*`.

### The C13 upload button

When a gateway is running, the **Add Survey** page (`add-survey.html`) auto-detects it (a one-shot
same-origin `/gateway/healthz` probe) and shows a **Submit to AusMT** button that uploads the
validated package straight to `/gateway/submit` — no GitHub account needed. If the button is absent,
the gateway is not up/reachable (see troubleshooting). On a static-only deploy (no gateway) the page
hides it and the manual pull-request path stays the documented route. Testers authenticate with the
operator-issued `AUSMT_SUBMIT_KEY`, distributed **out-of-band, operator-to-tester** (it rides only
as the `X-AusMT-Submit-Key` header, never in the package or URL).

### Keys (submit + curator)

```sh
# submit key (>= 16 chars) — testers send it as X-AusMT-Submit-Key. The app REFUSES TO START if it
# is unset or < 16 chars (fail closed). Put it in deploy/.env as AUSMT_SUBMIT_KEY:
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# curator keys — comma-separated name:key pairs, each key >= 16 chars, into AUSMT_CURATOR_KEYS.
# Each authenticates a NAMED curator so every action is attributable. Until set, /gateway/curator/*
# returns 503 (the submit half works regardless).
python3 -c "import secrets; print('curator1:' + secrets.token_urlsafe(32))"
```

Both are real secrets — keep them out of git, never logged. A curator signs in once at
`/gateway/curator/` (POST their key); the server sets a `Secure; HttpOnly; SameSite=Strict` session
cookie (12 h). **Run the gateway single-worker** (the image's `python -m gateway` entrypoint already
does — do NOT add `--workers N`): the publish lock and crash reconciliation are in-process.

### Curator publish = commit + push only; the rebuild is a separate manual step

`Approve` (and the C31 metadata editor) writes the package into `surveys-live` git history and
pushes — **that is all**. `PUBLISHED` means *committed to surveys-live main and pushed, NOT yet on
the live map*. To serve it, run the rebuild by hand:

```sh
export AUSMT_DATA_DIR=/srv/ausmt
# (optional) make sync-surveys   # if the operator-side checkout differs from the gateway's
make rebuild-data
```

This is deliberate: the gateway never invokes the build, so it never needs a Docker socket (the C10
§0 no-socket invariant holds). The approved survey is already in git history and the rebuild picks it
up like any merged PR.

### surveys-live must be writable by uid 10002

The publish flow stages/commits/pushes into `surveys-live`, so the gateway mounts it **read-write**
(it was read-only to `build-runner`). But the C10 note keeps `surveys-live` owned by **your** user
(chowning it to a container uid breaks your `git pull`). Give uid 10002 write access one of two ways:

- **Shared group (recommended):**
  `chgrp -R 10002 "$AUSMT_DATA_DIR/surveys-live" && chmod -R g+rws "$AUSMT_DATA_DIR/surveys-live"` —
  you still own the files and can `git pull`; the setgid bit keeps new files group-10002.
- **Dedicated gateway checkout:** give the gateway its own `surveys-live` owned by 10002, separate
  from your read-side checkout.

If uid 10002 cannot write, stage/commit fails → `PUBLISH_FAILED` (fail closed), never a partial
publish. The commit **author** is fixed in code (`AusMT Gateway <gateway@ausmt.local>`), never the
submitter.

### Curator publish credentials

The container's `git push` authenticates with **your own** credentials, mounted **read-only** — never
baked into the image or `.env`:

```sh
AUSMT_GIT_CREDS_DIR=/srv/ausmt/git-creds   # in deploy/.env; a deploy-key ssh dir (with known_hosts)
                                           # or a git credential file
```

Bind-mounted at `/srv/git-creds:ro`. Until set, compose validates against the committed
`git-creds.placeholder/` and any push fails → `PUBLISH_FAILED`. Do **not** put a token in `.env`.

### C31 curator metadata editor

The curator queue has an **Edit published metadata** link (`/gateway/curator/edit`): edit the
metadata subset of a published survey's `survey.yaml` (name/region/abstract/… — NOT the slug,
coordinates, or EDI-derived fields), preview the exact diff + a real validator verdict, and on
confirm commit+push through the **same fail-closed publish machinery** as an approve. Notes:

- **Committed ≠ served** — the edit lands in git history; run `make rebuild-data` to serve it (cheap
  for a metadata-only change).
- **The gw-runner does the parsing, not the gateway.** The gateway enqueues an edit job (a slug +
  form fields, never a path or PII); the gw-runner (engine image) claims it, round-trips the YAML
  with `ruamel.yaml` (preserving comments/unmodeled keys byte-for-byte), runs the validator, and
  writes the result. **The gw-runner must be up** for the editor to work; if it is down/busy, the
  edit page surfaces a retryable timeout (`AUSMT_EDIT_TIMEOUT_S`, default 120 s) — it never hangs.
- **Semver enforced:** a content change needs a semver-greater `version` bump + a release note; a
  no-op or non-greater version is refused.
- **No TOCTOU:** the confirm carries the sha256 of the previewed bytes; the gateway re-generates +
  re-hashes runner-side at commit, 409-ing on any mismatch.

### Gateway fail-closed behaviour (by design)

- **No/short submit key ⇒ no gateway.** The app refuses to start (`gateway/config.py`), before the
  port binds.
- **clamd unreachable / signatures stale ⇒ nothing advances.** Submissions hold at `RECEIVED`; a
  scan that cannot complete is never treated as clean.
- **Any parse/validation failure ⇒ `QUARANTINED`**, not published (a virus hit on the raw upload ⇒
  `REJECTED_AV`, zip deleted).
- **Directories are ground truth, the DB is the index.** Lose the sqlite state and the pipeline
  recovers by rescanning; the runner never writes the DB.
- **PII lives only in the sqlite DB** (`state/gateway.sqlite`) — never in packages, jobs, reports,
  the status page, or git. Back it up with `restic` alongside `site-data/`.

### PII handling (curator UI + source EDIs)

The curator detail view renders the submitter block (name/email/orcid) **only** inside authenticated
curator HTML; the public `/gateway/status/*` page never shows submitter fields. The checklist's PII
sweep greps built product + package for emails: a hit on the **submitter's own email** is an
**absolute** block (409, no override — that address is private by promise); a hit on **only other**
addresses (e.g. a historical `>INFO` contact in a source EDI — part of the archived record) is a
blocking FAIL the curator may **acknowledge** per-action (recorded in the audit trail as a
`PII-ACK (<n> file(s): …)` prefix, file names only). A mixed hit stays absolute. See
`maintainer/C11b-PiiAcknowledge.md`.

### Preview sandbox

The detail view iframes the already-built `quarantine/<id>/reports/preview-data/` inside a
**null-origin sandbox** (`<iframe sandbox="allow-scripts">` **without** `allow-same-origin`), so a
portal-XSS in the (un-curated) preview cannot read the curator cookie, the parent DOM, or make
credentialed requests. Preview bytes are served under `/gateway/curator/preview/{id}/*` with strict
`Content-Security-Policy: default-src 'self'` + `nosniff` + an extension allow-list, path-contained
(a `..`/absolute/encoded escape 404s). There is no "open in a new tab" link (that would run submitter
JS in the curator origin). preview-data is already embargo-safe + PII-scrubbed by the build engine.

---

## 4. Troubleshooting (real incidents)

| Symptom | Likely cause | What to do |
|---|---|---|
| **Submission stuck at `SCANNED`, never reaches `VALIDATED`/`QUARANTINED`** | The **gw-runner is not running or crash-looping** — it is what claims jobs, extracts, validates, and previews. (Incident 2026-07-06: the runner was configured with `PYTHONPATH=/opt/gateway` and could not `import gateway`; the correct value is `/opt`, the parent of the bind-mounted `/opt/gateway` package.) | `docker compose -f compose.yaml --profile gateway ps` — is `gw-runner` up? `docker compose ... logs gw-runner` — a `ModuleNotFoundError: gateway` means the `PYTHONPATH`/mount is wrong, or `AUSMT_CODE_DIR` is unset/points at the wrong tree so `${AUSMT_CODE_DIR}/gateway` did not mount. Confirm `$AUSMT_CODE_DIR/gateway/runner/` exists. |
| **Build id shows `None-None` / null engine commit in `build.json`** | A **stale engine image** (built before `ARG GIT_SHA` was baked) or a stale/dirty code checkout — the cache salt cannot resolve the engine commit, so caching self-disables and the build id is null. | `docker compose --profile jobs --profile gateway pull` a current image, confirm the live checkout (`git -C "$AUSMT_CODE_DIR" log -1`), then `make rebuild-data`. Verify `build_provenance.json` no longer says `cache.enabled:false`. |
| **`docker compose` errors: `required variable AUSMT_… is missing` / interpolation error** | A `${VAR:?}`-guarded variable is unset. After C33 only **`AUSMT_DATA_DIR`** and **`OWNER`** are hard-guarded (every service needs them); `AUSMT_SUBMIT_KEY`/`AUSMT_CODE_DIR` no longer block portal-only commands. | Set the named var in `deploy/.env` (see the grouped `.env.example`). `make preflight` lists exactly which required vars are missing for your profile. |
| **`docker compose pull` "worked" but the engine/gateway images are still old/missing** | `docker compose pull` only pulls services with **no profile** — i.e. just `portal`. `build-runner` (profile `jobs`) and the gateway services (profile `gateway`) are skipped. | Pull with the profiles: `docker compose --profile jobs --profile gateway pull` (or `docker compose --profile "*" pull` on compose v2.24+). `make preflight` flags any image missing locally. |
| **A CI sample / stray file appeared in `surveys-live` and got into a build** | A test/CI artifact (or a manual copy) left an untracked file in the read-side `surveys-live` checkout; the engine reads the whole tree. | Inspect before removing: `git -C "$AUSMT_DATA_DIR/surveys-live" clean -nd` (dry run) — review the list, then `git -C "$AUSMT_DATA_DIR/surveys-live" clean -fd` to remove untracked cruft. Re-run `make rebuild-data`. |
| **Portal serves but pages are empty / `current` missing** | No build has run yet (or the last build failed before the swap). | `make rebuild-data`; on failure it prints the failed `builds/<ts>` dir to inspect. `current` is only swapped after a clean verify. |
| **Host-side `ln`/`mv` on `current` gives `Permission denied`** | `site-data` is owned by uid 10001; you are not that user. | Don't swap by hand — `make rebuild-data` does the swap in-container as 10001. |
| **The C13 "Submit to AusMT" button never appears on Add Survey** | The gateway is not up/reachable, so the `/gateway/healthz` probe fails and the UI stays in manual-PR mode. | Bring the gateway up (section 3); `curl 127.0.0.1:8444/gateway/healthz` on the box; check Caddy is proxying `/gateway/*`. |
| **Two checkouts / edits not taking effect** | You are running compose/`make` from a *different* checkout than the one you edited. | `git -C "$AUSMT_CODE_DIR" log -1` and compare to where you ran the command; standardise on the single `$AUSMT_CODE_DIR`. `make preflight` reports the live checkout + its origin freshness. |

---

## 5. Architecture / ownership appendix

### uid split (why two container users)

- `site-data/` — the ONLY container-written portal tree → **uid 10001** (the `ausmt` user in
  `engine.Dockerfile`); `build-runner` and the `rebuild-data` in-container swap run as 10001.
- `gateway/{incoming,quarantine,jobs,state}` — the gateway/runner tree → **uid 10002**, a NEW uid
  deliberately distinct from 10001 so a compromised gateway stack cannot touch published `site-data`
  even via a uid collision. `gateway` and `gw-runner` run as 10002.
- `surveys-live/` — owned by **your** user, mounted read-only into `build-runner`/`gw-runner` and
  read-write into `gateway` (for publish). Keep your ownership so `git pull` works; grant 10002 write
  via a shared group or a dedicated checkout (section 3).

### Loopback-only publish + the ufw/Docker interaction

`compose.yaml` publishes the portal on `127.0.0.1:8443:8080` (and the gateway debug port on
`127.0.0.1:8444:8000`) — **never** widen these to a bare `8443:8080` or `0.0.0.0:…`. Docker's
iptables manipulation for published ports **bypasses ufw** regardless of any ufw rule, so the
loopback bind is the actual security boundary, not a firewall rule. The port is simply never
reachable from off-box via Docker's networking. Public exposure is exclusively through
`tailscale serve` (see below), which runs inside the tailnet's own encrypted overlay and opens no
new inbound port on the host's public interface.

The portal volume mounts the **whole** `site-data` tree (not `site-data/current`): a bind mount
resolves a symlink once at container start, so mounting the symlink would pin the container to the
build that was current at boot and defeat the atomic swap. Mounting the parent and pointing Caddy at
`/srv/data/current` means the symlink is followed per-request, so a host-side swap takes effect with
no restart.

### Backups

`restic` (assumed configured outside this contract) should cover:
- `${AUSMT_DATA_DIR}/site-data/` — the generated product tree (`current` + all `builds/<ts>/`; keep
  more than the latest — it's the rollback path). Includes the C18 `cache/` (safe to lose: a restore
  that drops it costs one slow rebuild).
- `${AUSMT_DATA_DIR}/surveys-live/` — reproducible via `git clone`, but a local backup avoids
  depending on the remote during a restore.
- `${AUSMT_DATA_DIR}/gateway/state/gateway.sqlite` — the ONLY PII home; back it up alongside
  `site-data/` if you run the gateway.
- `deploy/.env` — not secret if portal-only, but holds the submit/curator secrets once the gateway
  is configured; keep it safe and out of git.

Nothing here is a database needing a migration step: restoring `site-data/` + `docker compose up -d`
is sufficient.

---

## Expose to your tailnet (optional)

To reach the portal from other devices without a public port, front the loopback bind with
Tailscale:

```sh
tailscale serve --bg https / http://127.0.0.1:8443
tailscale serve status
```

Then hit `https://<this-node>.<tailnet>.ts.net/` from another tailnet device. This is the only
supported public-exposure path (see the loopback/ufw note above). Tailscale is **not** required for a
local or LAN-internal deploy.

---

## Appendix: the original EliteDesk deployment

The first production target was an HP EliteDesk on a tailnet, `AUSMT_DATA_DIR=/srv/ausmt`, exposed
via `tailscale serve`. Nothing above is EliteDesk-specific: the same steps run on any Docker host.
The EliteDesk-specific facts (its `/srv/ausmt` layout, its tailnet node name, its `restic` config)
were the origin of the ownership split and loopback rationale documented above, and are otherwise not
required to run AusMT elsewhere.
