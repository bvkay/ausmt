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
# submit key (>= 16 chars) — the BOOTSTRAP + CI upload key. Testers send it as X-AusMT-Submit-Key.
# The app REFUSES TO START if it is unset or < 16 chars (fail closed). Put it in deploy/.env as
# AUSMT_SUBMIT_KEY:
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

**Uploader keys are curator-managed in the UI.** Beyond the single bootstrap `AUSMT_SUBMIT_KEY`,
curators issue and revoke per-uploader submit keys from **Uploader keys** on the curator queue
(`/gateway/curator/uploaders`) — no shell needed, so this is the whole cockpit at a facility home
where the curator has no backend access. Each issued key (`ausmt_up_…`) is shown to the curator
**once** at creation and stored only as a sha256 hash; a lost key is revoked and re-created, never
retrieved. A submit is authorised by EITHER the env `AUSMT_SUBMIT_KEY` (bootstrap/CI, unchanged) OR
an active DB uploader key; a revoked or unknown key gets the same 401 as a wrong key. The gateway's
SQLite index now carries **schema v2** (the `uploader_keys` table); an existing v1 DB is migrated in
place on the next start (the migration is guarded — a DB from a newer build is refused, not opened).

### Curator publish = commit + push only; the rebuild is automatic (C40) — or manual

`Approve` (and the C31 metadata editor) writes the package into `surveys-live` git history and
pushes — **that is all**. `PUBLISHED` means *committed to surveys-live main and pushed, NOT yet on
the live map*. The gateway never invokes the build, so it never needs a Docker socket (the C10 §0
no-socket invariant holds).

**The rebuild is now closed automatically by the C40 serve-reconcile timer** (see "Serve reconcile
(automatic rebuild)" below): once installed, it syncs `surveys-live` and rebuilds within ~15 min of a
publish, and a curator can pull it forward with the **Request rebuild** button on the queue page. The
serve-state panel on that page shows published HEAD vs served build, the last reconcile outcome, and
the per-survey build report — so a shell-less curator can see the whole state.

The manual path **remains valid** (for a box without the timer, or to force a rebuild now):

```sh
export AUSMT_DATA_DIR=/srv/ausmt
# (optional) make sync-surveys   # if the operator-side checkout differs from the gateway's
make rebuild-data
```

The approved survey is already in git history and the rebuild picks it up like any merged PR.

### surveys-live must be writable by uid 10002

The publish flow stages/commits/pushes into `surveys-live`, so the gateway mounts it **read-write**
(it was read-only to `build-runner`). But the C10 note keeps `surveys-live` owned by **your** user
(chowning it to a container uid breaks your `git pull`). Give uid 10002 write access one of two ways:

- **Shared group (recommended):**
  ```sh
  # 1. Group-own surveys-live by the gateway group, setgid so NEW files inherit that group:
  sudo chgrp -R 10002 "$AUSMT_DATA_DIR/surveys-live"
  sudo chmod -R g+rwXs "$AUSMT_DATA_DIR/surveys-live"
  # 2. THE PERMISSIONS TIME-BOMB (incident 2026-07-11 — do not skip this): tell git itself to create
  #    group-writable objects. The gateway publishes as uid 10002; without this, git's default 0444
  #    objects + 0755 object dirs are NOT group-writable, so YOU (in the shared group) progressively
  #    lose the ability to `git pull`/gc as the gateway writes new .git/objects dirs you cannot touch
  #    — the checkout then silently rots behind GitHub:
  git -C "$AUSMT_DATA_DIR/surveys-live" config core.sharedRepository group
  # 3. Make sure BOTH the gateway (uid 10002) and YOUR operator account are in group 10002 — the
  #    shared group only helps if both writers are members:
  getent group 10002 >/dev/null || sudo groupadd -g 10002 ausmtgw
  sudo usermod -aG "$(getent group 10002 | cut -d: -f1)" "$USER"    # then re-login (or `newgrp`)
  ```
  You still own the files and can `git pull`; the setgid bit keeps new files group-10002, and
  `core.sharedRepository=group` keeps every git-created object group-writable. **If you are already
  locked out** (a publish ran before step 2), re-apply the model to what git already wrote:
  `sudo chgrp -R 10002 "$AUSMT_DATA_DIR/surveys-live/.git" && sudo chmod -R g+rwX "$AUSMT_DATA_DIR/surveys-live/.git"`.
  `make preflight PROFILE=gateway` **checks this for you** and fails loudly (with the exact fix) if any
  `.git` entry has lost group-write — run it after the first publish to confirm the model held.
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

- **Committed ≠ served** — the edit lands in git history; the C40 reconcile timer serves it within a
  tick (or press **Request rebuild** / run `make rebuild-data` to serve it now — cheap for a
  metadata-only change).
- **The gw-runner does the parsing, not the gateway.** The gateway enqueues an edit job (a slug +
  form fields, never a path or PII); the gw-runner (engine image) claims it, round-trips the YAML
  with `ruamel.yaml` (preserving comments/unmodeled keys byte-for-byte), runs the validator, and
  writes the result. **The gw-runner must be up** for the editor to work; if it is down/busy, the
  edit page surfaces a retryable timeout (`AUSMT_EDIT_TIMEOUT_S`, default 120 s) — it never hangs.
- **Semver enforced:** a content change needs a semver-greater `version` bump + a release note; a
  no-op or non-greater version is refused.
- **No TOCTOU:** the confirm carries the sha256 of the previewed bytes; the gateway re-generates +
  re-hashes runner-side at commit, 409-ing on any mismatch.

### Serve reconcile (automatic rebuild) — C40

The **serve-reconcile agent** closes the "published ≠ served" gap so the shell-less curator never has
to run `make` by hand. A systemd timer runs `deploy/scripts/reconcile.sh` every ~15 min; each pass:

1. `git -C surveys-live pull --ff-only` (a diverged checkout ⇒ status `sync_failed`, **no** rebuild —
   never build from a state you cannot fast-forward to);
2. compares the served build's `source_commit` (from `site-data/current/build.json` — the build ROOT;
   the portal's `/data/build.json` URL maps to this same file because Caddy strips the `/data` prefix)
   against the `surveys-live` short HEAD;
3. on drift **or** a curator **Request rebuild** (a `rebuild.request` file), runs `make rebuild-data`
   (the already-atomic build → verify → swap), logging to `site-data/logs/<ts>.build.log`;
4. writes `gateway/state/reconcile-status.json` — the curator queue page's **serve-state panel**
   reads it (published HEAD vs served build, last outcome, the per-survey build report, a pending
   indicator, and the **Request rebuild** button).

The script itself never assumes systemd (on Gadi/NCI it becomes a cron/PBS job of the same script).

**Install (one-time):**

```sh
# 0. ONE-TIME OWNERSHIP PREP (the reconcile agent runs as the OPERATOR, but two of the dirs it
#    writes are container-owned — without this step the first pass fails with "Permission denied"
#    (the 2026-07-08 first install). The script also fails EARLY and loudly if this is missing.)
#    Guard first: if AUSMT_DATA_DIR is unset in THIS shell (it normally lives only in deploy/.env),
#    the paths below would silently resolve to the filesystem root and create /site-data there.
: "${AUSMT_DATA_DIR:?unset — export it first, or: set -a; . ./.env; set +a}"
#    a) the build-log dir (inside uid-10001-owned site-data; never served — outside current/):
sudo install -d -o "$USER" -g "$(id -gn)" "$AUSMT_DATA_DIR/site-data/logs"
#    b) group-write on the 10002-owned gateway state dir, so the operator can write
#       reconcile-status.json and consume rebuild.request while the gateway keeps ownership
#       (the same shared-group pattern the surveys-live publish setup uses, in the other direction):
getent group 10002 >/dev/null || sudo groupadd -g 10002 ausmtgw
sudo usermod -aG "$(getent group 10002 | cut -d: -f1)" "$USER"
sudo chmod g+rwX,g+s "$AUSMT_DATA_DIR/gateway/state"
#    then RE-LOGIN (or `newgrp`) so your interactive shell picks up the group; the systemd unit
#    picks it up automatically at its next start.

# 1. Make sure deploy/.env has AUSMT_DATA_DIR and AUSMT_CODE_DIR set (the timer reads them via
#    EnvironmentFile — they are NOT taken from your shell profile). `make preflight PROFILE=gateway`
#    confirms both.
# 2. Copy the units and edit the placeholders:
sudo cp deploy/systemd/ausmt-reconcile.service /etc/systemd/system/
sudo cp deploy/systemd/ausmt-reconcile.timer   /etc/systemd/system/
sudo sed -i \
  -e 's#__DEPLOY_DIR__#/srv/ausmt/code/deploy#g' \
  -e 's#__ENV_FILE__#/srv/ausmt/code/deploy/.env#g' \
  /etc/systemd/system/ausmt-reconcile.service
sudo sed -i 's#^User=ausmt#User=YOUR_OPERATOR_USER#' /etc/systemd/system/ausmt-reconcile.service
#    (the operator uid that owns the checkout and runs `docker compose` — the same user you run
#     `make rebuild-data` as by hand; NOT root)
# 3. Enable + start:
sudo systemctl daemon-reload
sudo systemctl enable --now ausmt-reconcile.timer

# 4. Verify:
systemctl list-timers ausmt-reconcile.timer            # shows the next scheduled run
sudo systemctl start ausmt-reconcile.service           # run one pass now (test)
cat "$AUSMT_DATA_DIR/gateway/state/reconcile-status.json"   # should show action=noop|rebuilt|…
```

To preview what a pass **would** do without acting: `make reconcile ARGS=--dry-run` (or
`deploy/scripts/reconcile.sh --dry-run`). Exit codes: `0` on `noop`/`rebuilt`/`sync_failed` (the
timer must not flap), `1` only on a genuine build `failed`.

> **Note on the lock:** the script serialises overlapping ticks with `flock -n` on
> `$AUSMT_DATA_DIR/reconcile.lock` (a second concurrent run exits 0 silently). On a host without
> `flock(1)` it runs the pass without the lock (a stderr WARN) — the 15-min cadence + the atomic swap
> bound the worst case to a redundant build, never a corrupt one.

### Gateway fail-closed behaviour (by design)

- **No/short submit key ⇒ no gateway.** The app refuses to start (`gateway/config.py`), before the
  port binds.
- **clamd unreachable ⇒ nothing advances.** Submissions hold at `RECEIVED`; a scan that cannot
  complete is never treated as clean (`gateway/clamd.py`: a connect error, a truncated reply, or any
  reply that is not a definite `OK`/`FOUND` raises `ScanError`, and the caller holds at `RECEIVED`).
  **Caveat — signature *staleness* is NOT enforced in code (verified):** `clamd.py` fails closed on an
  unreachable/unparseable daemon, but there is **no VERSION/DB-age check** anywhere in the gateway, so
  a clamd that is *reachable but serving stale signatures* WOULD scan and advance. In practice
  `freshclam` runs continuously inside the clamav image and the curator is a second human gate, so the
  exposure is thin — but the fail-closed guarantee is "unreachable ⇒ hold", not "stale ⇒ hold". (An
  age check on the signature DB surfaced in `/gateway/healthz` or `preflight` would close this; it is
  flagged for the maintainer, not a change in this deploy contract.)
- **Any parse/validation failure ⇒ `QUARANTINED`**, not published (a virus hit on the raw upload ⇒
  `REJECTED_AV`, zip deleted).
- **Directories are ground truth, the DB is the index.** Lose the sqlite state and the pipeline
  recovers by rescanning; the runner never writes the DB.
- **PII lives only in the sqlite DB** (`state/gateway.sqlite`) — never in packages, jobs, reports,
  the status page, or git. Back it up with **`deploy/backup.sh`** (a WAL-safe snapshot — see
  "Backups & restore"; do NOT raw-copy a live WAL DB).

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
| **`git pull` on `surveys-live` fails `Permission denied` / `insufficient permission for adding an object`** (incident 2026-07-11) | The gateway published as uid 10002 and created `.git/objects` dirs **without group-write** because `core.sharedRepository=group` was never set — you (in the shared group) can no longer write them. The checkout then silently falls behind GitHub (the serve-state Freshness card / sync strip flags this). | Set the model and re-apply it to what git already wrote: `git -C "$AUSMT_DATA_DIR/surveys-live" config core.sharedRepository group && sudo chgrp -R 10002 "$AUSMT_DATA_DIR/surveys-live/.git" && sudo chmod -R g+rwX "$AUSMT_DATA_DIR/surveys-live/.git"`. Confirm with `make preflight PROFILE=gateway` (§3 "surveys-live must be writable by uid 10002"). |
| **Portal serves but pages are empty / `current` missing** | No build has run yet (or the last build failed before the swap). | `make rebuild-data`; on failure it prints the failed `builds/<ts>` dir to inspect. `current` is only swapped after a clean verify. |
| **Host-side `ln`/`mv` on `current` gives `Permission denied`** | `site-data` is owned by uid 10001; you are not that user. | Don't swap by hand — `make rebuild-data` does the swap in-container as 10001. |
| **The C13 "Submit to AusMT" button never appears on Add Survey** | The gateway is not up/reachable, so the `/gateway/healthz` probe fails and the UI stays in manual-PR mode. | Bring the gateway up (section 3); `curl 127.0.0.1:8444/gateway/healthz` on the box; check Caddy is proxying `/gateway/*`. |
| **Two checkouts / edits not taking effect** | You are running compose/`make` from a *different* checkout than the one you edited. | `git -C "$AUSMT_CODE_DIR" log -1` and compare to where you ran the command; standardise on the single `$AUSMT_CODE_DIR`. `make preflight` reports the live checkout + its origin freshness. |
| **Curator pressed "Request rebuild" but nothing happens** | The **C40 reconcile timer is not installed** (the button only writes `gateway/state/rebuild.request`; the host timer is what consumes it). | `systemctl list-timers ausmt-reconcile.timer` — if it is not listed, install it (§3 "Serve reconcile"). Confirm `gateway/state/rebuild.request` exists (the button wrote it) and will be picked up on the next tick, or run `sudo systemctl start ausmt-reconcile.service` to consume it now. |
| **Serve-state panel shows `sync_failed`** | `git pull --ff-only` on `surveys-live` **diverged** — the local checkout has commits/edits not on origin, so it cannot fast-forward. The reconcile agent refuses to build from an un-syncable state (by design) and does **not** rebuild. | Inspect: `git -C "$AUSMT_DATA_DIR/surveys-live" status` and `git -C … log --oneline origin/main..HEAD`. Reconcile the divergence (usually a stray local edit — review, then `git -C … reset --hard origin/main` if the local commits are unwanted, or push them). The next tick then syncs + rebuilds. |
| **Serve-state panel shows `failed`** (old data still serving) | The rebuild `build`/`verify` step failed; the atomic swap left the **previous** build serving (correct fail-closed behaviour). | Read the `log_tail` in the panel (or the full `site-data/logs/<ts>.build.log`, path in `reconcile-status.json`). Same causes as a manual `rebuild-data` failure (see the rows above — stale/dirty image, a bad survey package). Fix the cause; the next drift/button press/tick retries. The request file is already consumed, so it does **not** crash-loop. |
| **Reconcile exits 1 with `state dir not writable` / `cannot create log dir`** | The **one-time ownership prep (install step 0) is missing**: `site-data/` is uid-10001-owned and `gateway/state/` is 10002-owned, so the operator's reconcile pass cannot write its log dir or status file. The script fails early and loudly rather than half-running (the 2026-07-08 first-install symptom). | Run install step 0 (the `install -d` + shared-group commands), re-login (group membership), then `sudo systemctl start ausmt-reconcile.service` to re-run the pass. |
| **Reconcile holds with `structural mismatch` (status `failed`, `built` null)** | The **loop guard** latched: a rebuild completed but `site-data/current/build.json` was *still* unreadable afterwards — a layout or permission mismatch is eating every rebuild, so the agent refuses to burn one build per tick forever. (Also latches after a failed *first* build on a fresh box — deliberate: a deterministic failure needs an operator, not a retry storm.) | Check `ls "$AUSMT_DATA_DIR/site-data/current/build.json"` exists and is readable, and read the last build log. After fixing, re-arm with the curator **Request rebuild** button (an explicit request always gets a fresh attempt) or the next real publish (HEAD change). |

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

### Monitoring (compose healthchecks + the operator loop)

`compose.yaml` ships a `healthcheck:` per long-running service. Each probes an **independent
observable**, uses only a binary that actually exists in that image, and can genuinely fail:

| Service | Check | Fails (=> `unhealthy`) when |
|---|---|---|
| `portal` | BusyBox `wget --spider http://127.0.0.1:8080/` | Caddy is down, the Caddyfile stopped adapting, or the process wedged. Probes `/` (not `/data/catalogue.json`) so a fresh box with no build yet is still healthy — an empty portal is a data state, not a portal fault. |
| `gateway` | stdlib `urllib` GET `/gateway/healthz` (no curl/wget in `python:3.12-slim`) | uvicorn died, the app crashed on bad config, or the event loop wedged. **Liveness only** — it does NOT check clamd, the runner, or the queue. |
| `clamd` | INSTREAM `PING`→`PONG` on `:3310` | clamd is not listening, or is up but still loading its signature DB (the daemon PONGs only once it can actually scan). Generous `start_period` covers the slow first `freshclam` + DB load. |

The gateway's `depends_on: clamd` uses **`condition: service_healthy`**, so on `up` the gateway waits
until clamd can scan rather than fail-closing every submission to `RECEIVED` while clamd loads.

**Serve-reconcile timer (C40).** The reconcile agent is a host **systemd timer/service**, not a
compose service, so it is monitored with systemd, not a compose healthcheck:

| What | Check |
|---|---|
| Timer is scheduled | `systemctl list-timers ausmt-reconcile.timer` (shows the next/last run) |
| Last pass result | `systemctl status ausmt-reconcile.service` — a non-zero exit (a `failed` build) shows here; `sync_failed`/`noop`/`rebuilt` all exit 0 |
| The state the curator sees | `cat "$AUSMT_DATA_DIR/gateway/state/reconcile-status.json"` — `action`, `head`, `built`, `build_id`, `log_file`, and (on a failure) `log_tail`; the curator queue page's serve-state panel renders the same file |
| Build forensics | `site-data/logs/<ts>.build.log` (newest 20 kept), the full captured build output for the pass |

**`gw-runner` has NO healthcheck — deliberately, not an oversight.** When idle the runner writes
nothing observable (its only liveness signal is touching a per-job running-file mtime *while a job
runs*), and a `python -c "import gateway.runner"` probe would spawn a fresh interpreter and prove only
that the module imports — a check that passes even when the long-lived loop has silently died. That is
exactly the vacuous "healthcheck that cannot fail" this repo forbids. A dead/crash-looping runner is
instead caught by (a) `restart: unless-stopped` making it visibly restart-loop in `docker compose ps`,
and (b) the operator-facing symptom **"submissions stuck at `SCANNED`"** (the Troubleshooting row in
§4). A meaningful in-container check needs a **global runner-heartbeat file** — a small change in
`gateway/runner/` — which is flagged for the maintainer rather than faked here.

**What healthchecks do NOT give you:** compose healthchecks flag a *container* as unhealthy but do not
alert anyone or restart a merely-`unhealthy` (vs exited) container. That gap is closed by the
**Alerting** section below — an `ausmt-alert.timer` that runs the checks the "minimum operator loop"
describes (`docker compose ps` for `unhealthy`/restarting, a disk check, plus reconcile + backup
freshness) and pings an external dead-man monitor that emails the curator. Install it; then the manual
loop is a backstop, not the only line of defence.

### Alerting

Compose healthchecks and the reconcile/backup timers all *detect* problems, but nothing on the box
**tells anyone** when one occurs — a `gw-runner` crash-loop ("submissions stuck at `SCANNED`", the
2026-07-06 incident), a full disk, a stalled reconcile, or a failed nightly backup can sit silent for
days. `deploy/scripts/alert.sh` (on `ausmt-alert.timer`, every 15 min) runs those checks and reports to
an **external dead-man monitor** (healthchecks.io or any equivalent), which routes the alert **email**.

**Why an external ping and not a box-sent email:** the box holds **no SMTP credentials and no recipient
config**, so changing *who* is alerted is a **dashboard change at the service** — no repo edit, no box
change, nothing to redeploy. And a fully **dead** box (power/network/kernel) can never send its own "I
am dead" email; the monitor detects that as an **absent ping** (the one failure a box-sent email can
never report). `alert.sh` covers "the box is up but a subsystem stalled"; the monitor's absent-ping
timeout covers "the box is gone".

**What it checks** (each threshold is an `AUSMT_ALERT_*` env var in `.env`; defaults shown):

| Check | Fails (=> fail ping) when |
|---|---|
| Service health | any of `portal`, `gateway`, `clamd`, `gw-runner` is not `running`, restart-looping, or (for the three with a healthcheck) `unhealthy`. `gw-runner` has **no** healthcheck by design, so it is caught by **state** — a `restarting` `gw-runner` is the "stuck at `SCANNED`" crash-loop. `build-runner` is **not** checked (it is a one-shot job, absent by design between builds). |
| Disk | the `$AUSMT_DATA_DIR` filesystem is over `AUSMT_ALERT_DISK_PCT`% used (**85**). |
| Serve reconcile | `gateway/state/reconcile-status.json` `last_run` is older than `AUSMT_ALERT_RECONCILE_MAX_MIN` min (**45** — three missed ticks), or `action=failed`. (`sync_failed`/`noop`/`rebuilt` are healthy outcomes and do **not** alert — they are panel states, see §4.) |
| Backup freshness | the newest `backups/<ts>/` snapshot is older than `AUSMT_ALERT_BACKUP_MAX_H` h (**26**), or `systemctl is-failed ausmt-backup.service` reports the unit failed. |

All OK => one success beat to the ping URL. Any failure => a ping to `<url>/fail` with the failure
lines as the body, **and** a non-zero exit so `journalctl -u ausmt-alert.service` shows it too.

#### Set up the external check (one-time)

1. At [healthchecks.io](https://healthchecks.io) (or an equivalent), create a **check** with **period
   15 min** and **grace 10 min** (matches the timer cadence — a beat always lands inside the window).
2. Set the check's **alert email** to the curator: **`ben@auscope.org.au`** today. **Changing who is
   alerted later is a dashboard-only edit** — never a repo or box change.
3. Copy the check's **ping URL** and paste it into `deploy/.env` as `AUSMT_ALERT_URL`:
   ```sh
   # deploy/.env  (gitignored — this URL is confidential-ish but grants NO box/data access;
   #               keep it in your password manager alongside the other .env secrets)
   AUSMT_ALERT_URL=https://hc-ping.com/your-check-uuid
   ```
   If you install the units **before** doing this, `alert.sh` just prints a loud "alerting NOT
   configured" note and exits 0 — the timer will not flap.

#### Install the timer

Edit the `__PLACEHOLDER__` paths + `User=` in the `.service` (exactly like the backup/reconcile units —
systemd does not expand env vars in `ExecStart`/`WorkingDirectory`, so they are literal sed
placeholders), then install:

```sh
# In deploy/systemd/ausmt-alert.service, replace with YOUR absolute paths (the production box keeps the
# checkout under the operator's home, NOT /srv/ausmt/code — that path does not exist there):
#   __DEPLOY_DIR__ -> /home/<operator>/ausmt-code/deploy   __ENV_FILE__ -> /home/<operator>/ausmt-code/deploy/.env
# and set User= to the operator account (the same one that runs docker compose / backup.sh).
sudo cp deploy/systemd/ausmt-alert.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ausmt-alert.timer
systemctl list-timers ausmt-alert.timer          # confirm the next run
```

Cron equivalent (if you are not on systemd):
`*/15 * * * *  AUSMT_ALERT_URL=… AUSMT_DATA_DIR=/srv/ausmt AUSMT_CODE_DIR=/home/<operator>/ausmt-code /home/<operator>/ausmt-code/deploy/scripts/alert.sh`

#### Test it (both directions — do this, do not assume)

```sh
# 1. Success beat: run the pass now; the check should flip GREEN in the dashboard within a minute.
sudo systemctl start ausmt-alert.service
systemctl status ausmt-alert.service --no-pager     # expect exit 0, "all checks OK -- sending success ping"

# 2. Fail ping + EMAIL: stop a service, run the pass, confirm the dashboard goes RED and the curator
#    gets the email; then restore and re-beat green.
docker compose -f compose.yaml ps                    # note portal is up
docker compose -f compose.yaml stop portal
sudo systemctl start ausmt-alert.service             # expect a non-zero exit + a ping to <url>/fail
#    -> the dashboard shows the failure body ("service portal: ...") and emails ben@auscope.org.au
docker compose -f compose.yaml start portal
sudo systemctl start ausmt-alert.service             # back to green
```

A backup that has never been *tested* is a hypothesis — so is an alert path that has never *fired*.
Do step 2.

#### Troubleshooting

| Symptom | Cause → fix |
| --- | --- |
| `alert.sh`: "ALERTING NOT CONFIGURED … no ping sent" (exit 0) | `AUSMT_ALERT_URL` is unset/empty in the unit's `EnvironmentFile`. Create the external check and paste its ping URL into `deploy/.env` (above). Deliberate: the timer runs harmlessly until you do. |
| Dashboard shows the check **red / late** but the box is fine | The box could not reach the monitor (tailnet/DNS/outbound HTTPS blocked), or the timer is not running. Check `systemctl list-timers ausmt-alert.timer`, run `sudo systemctl start ausmt-alert.service` and read `journalctl -u ausmt-alert.service` — a "success ping … FAILED (curl error)" line means outbound HTTPS to the monitor is blocked. |
| Fail ping fires but names `services: … python … cannot parse` | `AUSMT_CODE_DIR` is unset/wrong (so `deploy/compose.yaml` is not found) or no `python3`/`python` is on the operator's PATH. Set `AUSMT_CODE_DIR` in `.env`; install python3. |
| Constant fail pings for `gw-runner` | The runner really is crash-looping (`docker compose --profile gateway ps` shows it `restarting`) — this is the alert working. Fix the runner (§4 "stuck at `SCANNED`" row: usually `PYTHONPATH`/`AUSMT_CODE_DIR`). |
| Fail pings for a **stale backup/reconcile** right after install | Expected until the first backup + reconcile pass has run. The backup line is `WARN`-class while `backups/` does not exist yet; it becomes a hard fail once the timer should have produced a snapshot. |

### Backups & restore

The backup story has three parts: **on-box snapshots** (`deploy/backup.sh` on a nightly timer),
an **off-box pull** to the operator's Mac (`deploy/scripts/pull-backup.sh` via a launchd agent), and a
**tested restore** (`deploy/scripts/restore-drill.sh`). Install the first, wire up the second, then run
the third — **a backup that has never been restored is a hypothesis, not a backup** (Invariant 10).

#### What is backed up — and what is deliberately NOT

`backup.sh` snapshots **only** the genuinely irreplaceable bytes on the box into
`$AUSMT_DATA_DIR/backups/<utc-ts>/`:

- `gateway/state/gateway.sqlite` → the **only** PII home and the audit trail (submitter PII,
  uploader-key **hashes**, the audit history). The single file nothing else can reconstruct.
  **Snapshotted CONSISTENTLY, not raw-copied** (WAL warning below).
- `gateway/state/reconcile-status.json` and any **other non-secret** file in the state dir — small
  operational metadata with no other copy.

What it **never** copies, and why:

- **`deploy/.env` → NEVER.** The submit/curator secrets are held **out of band in the operator's
  password manager**. A backup that copied `.env` would put live secrets into a snapshot tree the Mac
  then pulls over the tailnet — exactly the leak this design prevents. A name filter in `backup.sh`
  refuses `.env`, `*.key`, `*.pem`, `id_*`, `*secret*`, … from the state dir too, belt-and-braces.
- **`surveys-live/` → NEVER here.** It is a git checkout; **its backup is GitHub**. A local copy adds
  nothing a `git clone` cannot give back.
- **`site-data/` and `cache/` → NEVER.** They are **regenerable** with `make rebuild-data`. Not
  irreplaceable, so not archived.

> **WHY the DB must never go into `ausmt-surveys` (or any git repo).** The sqlite DB is the **PII
> containment boundary**. **CI clones the surveys repo**, so anything committed there is effectively
> public, and a PII leak into public git history is permanent. The DB backup therefore lands in a plain
> directory under the data root and is pulled off-box by `pull-backup.sh` — **never git**. Do not point
> any backup at a repo destination.

> **WAL WARNING.** `gateway/db.py` opens the DB in **WAL mode** (`PRAGMA journal_mode=WAL`). A raw file
> copy of a *live* WAL database can miss committed transactions still in the `-wal` sidecar, silently
> producing a torn snapshot. `backup.sh` copies the DB **through SQLite's online backup API**
> (`sqlite3 <db> ".backup <dest>"`), which is transactionally consistent even against a live writer.
> A host **`sqlite3` is therefore required** whenever a gateway DB exists — it is the one WAL-safe
> copier. There is **no docker/Python fallback** (an earlier one was removed 2026-07-10: it could not
> open a live WAL DB through a read-only mount, and could not write the operator-owned staging dir as
> the container uid — it failed both ways on the first real run). If `sqlite3` is missing, `backup.sh`
> refuses loudly rather than raw-copy; install it (`sudo apt-get install -y sqlite3`).

Retention: the newest **14** snapshot directories are kept on the box; `backups/latest` is a symlink to
the newest.

#### Ownership prep (one-time) — read this first

`backup.sh` runs as the **operator**, not as root or the gateway container. The state dir is uid
**10002**-owned with the shared group **10002** set `g+rwX,g+s` (the same one-time prep the reconcile
runbook describes — "Serve reconcile" step 0). The operator (`g3-i7`) must be **in group 10002**:

- **group-read** lets the operator read `gateway.sqlite`;
- **group-write** lets SQLite create the `-shm`/`-wal` sidecars it needs to *open* a WAL DB — opening a
  WAL DB writes to its directory even for a read, so `g+rwX` is required, not just `g+r`.

If this prep is missing, `backup.sh` fails **loudly and early** ("state dir is not readable … ownership
prep is missing") instead of producing a broken snapshot. Fix it before enabling the timer.

> **Watch item — sidecar perms after a compose recreation.** The `-shm`/`-wal` sidecars are minted
> **fresh** by the gateway whenever the container is recreated (`docker compose up -d` after an image
> bump). Depending on the gateway umask, the new sidecars may **drop the group-write bit** the
> operator's group-membership read path needs — so a backup that ran fine by hand can start failing on
> the next nightly. `backup.sh` now **preflights** this and dies naming the file with the fix
> (`sudo chmod g+rw <files>`), but the durable answer is to **re-check the first nightly run after any
> compose recreation** (or fix the gateway umask so new sidecars keep `g+rw`).

#### Install the nightly timer

Two one-time prerequisites first (both are preflighted by `backup.sh`, which now fails loudly and
early if either is missing — do them BEFORE the first `systemctl start`):

```sh
# 1. A host sqlite3 — the ONLY WAL-safe copier; there is no fallback. Without it `backup.sh` refuses.
sudo apt-get install -y sqlite3        # (dnf install -y sqlite / apk add sqlite / brew install sqlite)

# 2. Pre-create the backups dir owned by the OPERATOR. The data root (e.g. /srv/ausmt) is root-owned,
#    so backup.sh cannot mkdir the backups dir itself — without this the run dies at PUBLISH time,
#    AFTER a successful snapshot. Create it once (substitute the operator account for $USER if you run
#    this as a different user):
sudo install -d -o "$USER" -g "$(id -gn)" -m 0750 "$AUSMT_DATA_DIR/backups"
```

The timer then runs `backup.sh` once a day. Edit the `__PLACEHOLDER__` paths + `User=` in the
`.service` (exactly like the reconcile unit — systemd does not expand env vars in
`ExecStart`/`WorkingDirectory`, so they are literal sed placeholders), then install:

```sh
# In deploy/systemd/ausmt-backup.service, replace with YOUR absolute paths (the production box keeps
# the checkout under the operator's home, NOT /srv/ausmt/code — that path does not exist there):
#   __DEPLOY_DIR__ -> /home/<operator>/ausmt-code/deploy   __ENV_FILE__ -> /home/<operator>/ausmt-code/deploy/.env
# and set User= to the operator account. .env must define AUSMT_DATA_DIR.
sudo cp deploy/systemd/ausmt-backup.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ausmt-backup.timer
systemctl list-timers ausmt-backup.timer     # confirm the next run
sudo systemctl start ausmt-backup.service     # take one backup NOW to test
ls -l "$AUSMT_DATA_DIR/backups/"               # confirm a <utc-ts>/ dir + latest symlink appeared
```

Cron equivalent (if you are not on systemd):
`20 3 * * *  AUSMT_DATA_DIR=/srv/ausmt /home/<operator>/ausmt-code/deploy/backup.sh`

> **Watch item — a silently-failing nightly backup is exactly the kind of stall nobody notices.** The
> **Alerting** section's `ausmt-alert.timer` watches this for you: it fail-pings the curator if the
> newest snapshot is older than `AUSMT_ALERT_BACKUP_MAX_H` (26 h) **or** `systemctl is-failed
> ausmt-backup.service` reports the unit failed. Install alerting too, so a backup that quietly stops
> running does not go unnoticed until you need a restore.

#### Mac pull setup (off-box copy over the tailnet)

`pull-backup.sh` resolves `backups/latest` on the box over ssh, then rsyncs (scp fallback) that
snapshot into a local dir, pruning to the newest 30. Nothing Mac-specific lives in the script — the
macOS side is only the launchd wrapper. Config is env/flags; **no hostname is baked into git**.

Test it by hand first (over the tailnet, with your SSH key already set up):

```sh
AUSMT_BACKUP_REMOTE=op@ausmt-box:/srv/ausmt/backups \
AUSMT_BACKUP_DEST=$HOME/ausmt-backups \
  deploy/scripts/pull-backup.sh
ls -l $HOME/ausmt-backups/                     # a <utc-ts>/ dir with gateway.sqlite should appear
```

Then install the launchd agent so it runs daily:

```sh
# Edit deploy/launchd/com.ausmt.backup-pull.plist and replace every __PLACEHOLDER__:
#   __PULL_SCRIPT__ __REMOTE__ __DEST__ __LOG__ __HOUR__ __MINUTE__
cp deploy/launchd/com.ausmt.backup-pull.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.ausmt.backup-pull.plist
# (older macOS: launchctl load ~/Library/LaunchAgents/com.ausmt.backup-pull.plist)
launchctl kickstart -k gui/$(id -u)/com.ausmt.backup-pull   # run once now to verify
launchctl print gui/$(id -u)/com.ausmt.backup-pull | grep -E 'state|last exit'  # confirm it ran clean
tail ~/Library/Logs/ausmt-backup-pull.log      # (whatever __LOG__ you set)
```

#### Restore drill (run after the first backup, then periodically)

`restore-drill.sh` proves a snapshot is restorable **without touching production**: it copies the DB to
a scratch temp, runs `PRAGMA integrity_check`, asserts the schema-v2 `uploader_keys` table exists, and
prints the table list + uploader_keys count + newest submission timestamp for you to eyeball.

```sh
AUSMT_BACKUP_DIR=/srv/ausmt/backups deploy/scripts/restore-drill.sh          # drills `latest`
deploy/scripts/restore-drill.sh /srv/ausmt/backups/20260708T032000Z          # or a specific snapshot
```

**Failure criterion:** the drill **exits non-zero with a loud message** if the DB is missing, fails
`integrity_check` (corrupt/torn snapshot), or is missing the `uploader_keys` table (a pre-v2 DB a
restore would lose curator keys from). A zero exit + a sane eyeball report is the only "PASS". Run it
once right after the first backup, and quarterly thereafter.

#### Real RESTORE procedure (when you actually need it)

1. **Stop the gateway** so nothing writes the DB mid-restore:
   `docker compose -f compose.yaml --profile gateway down`.
2. **Pick a snapshot** (`/srv/ausmt/backups/latest/` or an older `<utc-ts>/`) and, if you are unsure it
   is good, **drill it first** (above).
3. **Restore the DB.** Delete any stale WAL sidecars so SQLite does not replay an old `-wal` over the
   restored file, then copy the snapshot's DB in:
   ```sh
   rm -f /srv/ausmt/gateway/state/gateway.sqlite-wal /srv/ausmt/gateway/state/gateway.sqlite-shm
   cp /srv/ausmt/backups/latest/gateway.sqlite /srv/ausmt/gateway/state/gateway.sqlite
   chown 10002:10002 /srv/ausmt/gateway/state/gateway.sqlite
   ```
4. **Restore `deploy/.env`** from your **password manager** (it is not, and must never be, in any
   backup). Restore `surveys-live/` by `git clone` if it was lost (GitHub is its backup).
5. **Rebuild the served products** — regenerable, not in the backup by design:
   `export AUSMT_DATA_DIR=/srv/ausmt; make rebuild-data`.
6. **Bring it back up** (`docker compose ... up -d`) and `make smoke`. Confirm the status of a known
   prior submission resolves — that proves the DB restore, not just the file copy.

Note the gateway's own recovery property still holds: **directories are ground truth, the DB is the
index** — lose only the sqlite state and the pipeline recovers by rescanning the on-disk trees
(README §3), so the DB backup mainly protects the **PII + audit history**, which rescanning cannot
reconstruct.

#### Troubleshooting

| Symptom | Cause → fix |
| --- | --- |
| `backup.sh`: "state dir is not readable … ownership prep is missing" | The operator is not in group 10002, or the state dir lacks `g+rX`. Run the one-time **ownership prep** above. |
| `backup.sh`: "host sqlite3 not found … refusing to raw-copy a live WAL DB" | No WAL-safe path. Install `sqlite3` on the host (`sudo apt-get install -y sqlite3`) — it is the ONLY WAL-safe copier and there is **no fallback**. Never work around this by raw-copying the DB. |
| `backup.sh`: "WAL sidecar(s) not writable … `sudo chmod g+rw`" | A `docker compose up -d` **recreation** minted fresh `-shm`/`-wal` sidecars that dropped the group-write bit the operator's read path needs. Run the printed `sudo chmod g+rw <files>` (or fix the gateway umask so new sidecars keep `g+rw`). **Re-check the first nightly run after any compose recreation.** |
| `backup.sh`: "backups dir does not exist and its parent is not writable … `sudo install -d`" | The backups dir was never pre-created and its parent (the data root) is root-owned, so `backup.sh` cannot create it. Run the printed `sudo install -d -o <operator> … -m 0750 <dir>` (the install-runbook prerequisite). |
| `pull-backup.sh`: "could not resolve 'latest' … remote unreachable" | The tailnet is down, SSH auth failed, or no backup has run yet (`backups/latest` missing). Check `tailscale status`, your SSH key, and `systemctl list-timers ausmt-backup.timer` on the box. |
| `restore-drill.sh`: "integrity_check did NOT return ok" | The snapshot is **corrupt** — it would not restore. Check `backup.sh` used the WAL-safe `.backup` (host `sqlite3` present?), then re-take and re-drill. Do not rely on that snapshot. |
| `restore-drill.sh`: "the uploader_keys table is MISSING (schema < v2)" | The DB predates curator-managed keys. Back up from a v2 gateway, or migrate first. |

---

### Usage analytics (C45)

AusMT records anonymous, aggregate usage — **downloads by survey / station / format**, **portal
visits**, and **downloads/visits by country** — for AuScope reporting and custodian conversations
("your survey was downloaded N times from M countries"). It is deliberately **not** ad-tech: no
cookies, no cross-site tracking, no per-user identity.

**How it works.** The portal container's Caddy writes a privacy-preserving access log (client IP
**masked at write time** — IPv4 → /24, IPv6 → /48 — so a full address never touches disk; the log
block ships in `deploy/docker/caddy/Caddyfile`). A daily host timer runs a stdlib-Python aggregator
(`deploy/scripts/aggregate_stats.py`) that folds each **complete** day of the log into a cumulative
`stats.json` in the gateway state dir, then the workbench **Analytics** screen
(`/gateway/curator/analytics`) renders it. `stats.json` carries **aggregates only** — counts and a
daily series — **never an address (masked or not) and never a user-agent**.

> **What it cannot report.** Per-station / per-survey *page views* are **not** server-countable: the
> portal is a hash-routed SPA that loads the corpus once and renders every station/survey view
> client-side with zero per-navigation request. This screen reports **downloads** (a real server
> request) and **whole-portal visits** (one `catalogue.json` fetch per SPA boot) — honestly, not page
> views. Per-dataset views would need a first-party beacon, a separate future decision.

**Raw-log retention.** The access log is Caddy's own rolled file with a **~7-day retention**
(`roll_keep_for 168h` in the Caddyfile) — the tail exists only for debugging. The aggregator runs
daily and the raw lines are **not** the database: once a day is folded into `stats.json` the log is no
longer needed, and the aggregator tolerates an already-rotated / absent log without error.

#### Country resolution — the db-ip CSV (operator chore)

Country is resolved from the masked address with the **db-ip.com "IP to Country Lite"** dataset —
**CC-BY-4.0, no account, no licence key** — read directly by a stdlib bisect (no `maxminddb`, no
`geoipupdate`, no MaxMind EULA). **A missing or unreadable CSV is not fatal**: every country simply
resolves to `unknown` and the aggregator still completes.

```sh
# One-time: create the dir and drop the monthly CSV in (download from
#   https://db-ip.com/db/download/ip-to-country-lite  — the CSV edition, CC-BY-4.0).
# Attribution is REQUIRED by CC-BY: it is carried in docs/ (operations/usage-analytics.md).
mkdir -p "$AUSMT_DATA_DIR/geoip"
mv ~/Downloads/dbip-country-lite-*.csv "$AUSMT_DATA_DIR/geoip/dbip-country-lite.csv"

# Monthly refresh: replace the same file. Stale data drifts slowly (countries rarely move), so a
# late refresh degrades gracefully rather than breaking anything. Override the path in .env with
# AUSMT_STATS_DBIP_CSV if you keep it elsewhere.
```

The CSV format is `start_ip,end_ip,country_code` per line (IPv4 and IPv6 ranges in one file) — exactly
what db-ip's Lite CSV ships. A small **fixture** CSV lives at
`deploy/tests/fixtures/dbip-country-lite.sample.csv` for the tests; **do not** use it in production.

#### Install the daily timer

```sh
# 1. Make sure deploy/.env has AUSMT_DATA_DIR (+ AUSMT_CODE_DIR) — the timer reads them via
#    EnvironmentFile, NOT your shell profile. The gateway state dir must already be group-writable to
#    the operator (the same ownership prep the reconcile/backup units need — see "Serve reconcile").
# 2. Copy the units and edit the placeholders (exactly like the alert/backup units):
sudo cp deploy/systemd/ausmt-stats.{service,timer} /etc/systemd/system/
# In deploy/systemd/ausmt-stats.service, replace with YOUR absolute paths:
#   __DEPLOY_DIR__ -> /home/<operator>/ausmt-code/deploy   __ENV_FILE__ -> /home/<operator>/ausmt-code/deploy/.env
# and set User= to the operator account (the same one that runs docker compose / backup.sh; NOT root).
sudo systemctl daemon-reload
sudo systemctl enable --now ausmt-stats.timer
systemctl list-timers ausmt-stats.timer          # confirm the next run (daily, 03:35 UTC + jitter)
sudo systemctl start ausmt-stats.service         # fold once NOW to test -> writes gateway/state/stats.json
```

Then open **Curator → Operations → Analytics**. Before the first fold it shows an honest empty state;
a `stats.json` older than ~2 aggregation periods (≈ 2 days) shows a **STALE** banner (the timer is not
running) rather than presenting old figures as live.

#### Troubleshooting

| Symptom | Cause → fix |
| --- | --- |
| Analytics screen shows "No usage analytics yet" | The `ausmt-stats` timer has not produced a `stats.json`. Install + start it (above); check `journalctl -u ausmt-stats.service`. |
| Analytics screen shows a **STALE** banner | The timer stopped, or no complete day has been folded since. Check `systemctl list-timers ausmt-stats.timer` and the service journal. |
| Every country shows as `unknown` | The db-ip CSV is missing/unreadable at `$AUSMT_DATA_DIR/geoip/dbip-country-lite.csv` (or `AUSMT_STATS_DBIP_CSV`). Place/refresh it (above). Counts are still correct; only the country split degrades. |
| Downloads counted but `unattributed` is high | The served `manifest.json` did not resolve those paths (a build/serve skew, or NCI-tier absolute URLs). Confirm `site-data/current/manifest.json` matches what is served. |

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
The EliteDesk-specific facts (its `/srv/ausmt` layout, its tailnet node name, its off-box backup
target) were the origin of the ownership split and loopback rationale documented above, and are
otherwise not required to run AusMT elsewhere.
