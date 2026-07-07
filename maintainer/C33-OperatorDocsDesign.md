# C33 — Operator Docs + Any-PC Docker Deploy (frozen design)

> **FROZEN from chief-architect spec 2026-07-06.** This file is the design record for contract
> C33. It captures the request and the seven requirements as the frozen scope; the
> implementation must match it. Deviations discovered during implementation are recorded in the
> Deviations section at the bottom, dated, with the reason.

## Request (verbatim)

> "we really need good docs for how to run the system, and that it could be used on any PC via
> docker."

## Origin

The requirements come from a **real deployment session on 2026-07-06**. An experienced operator, on
his own box, hit every defect below. Each is a defect this contract must fix in docs and, where
marked **[HARDEN]**, in deploy config.

## The seven requirements (frozen)

### 1. Two-checkout confusion
The old runbook said `/srv/ausmt/code` but the operator's live checkout was `~/ausmt-code`; a stale
second checkout served old `Makefile`/`compose` for hours.
**Fix:** docs declare ONE convention — a single checkout, location the operator's choice, referenced
everywhere as `$AUSMT_CODE_DIR` — plus a "which checkout is live" sanity check
(`git -C "$AUSMT_CODE_DIR" log -1`).

### 2. `docker compose pull` misses profile services
`docker compose pull` does NOT pull `build-runner` (`profiles: ["jobs"]`) or the `gateway`-profile
services.
**Fix:** document `docker compose --profile "*" pull` as the canonical image refresh. Verify the
flag works with the shipped compose; if not, fall back to documenting the explicit
`docker compose --profile jobs --profile gateway pull` (or direct `docker pull`) commands.

### 3. Variable whack-a-mole [HARDEN]
Compose `:?` guards on `AUSMT_SUBMIT_KEY` and `AUSMT_CODE_DIR` block EVERY compose command (even a
portal-only rebuild-data) until the gateway vars are set.
**Fix:** scope the guards so portal-only operation never requires gateway variables.
**Design constraint (why `:?`→`:-` is safe):** the gateway app ALREADY fail-closes at startup on a
missing/short `AUSMT_SUBMIT_KEY` (`gateway/config.py::fail_closed_startup`, called from
`create_app()` in `gateway/app.py:994` before the port binds), and `gw-runner` fails without its
mounts. So the compose-level `:?` on those two can safely become `:-` defaults (empty), with the
fail-closed behaviour documented as living in the **app layer**. `AUSMT_DATA_DIR` and `OWNER` stay
`:?` (every service needs them).
**Proof required:** `docker compose config` succeeds with ONLY `AUSMT_DATA_DIR`+`OWNER` set;
`--profile gateway config` still fails loudly at APP level when the key is missing (add/extend a
test or a documented verification step — do NOT weaken the app-level guards).

### 4. Scattered one-time host setup [HARDEN]
One-time host setup is scattered across the docs (chown 10001 site-data; mkdir+chown 10002 gateway
tree; `.env` vars; git-creds dir; curator/submit key generation).
**Fix:** a single "First run" checklist section AND a preflight script
`deploy/scripts/preflight.sh` (POSIX sh, runs on any Linux/macOS/WSL docker host) that checks and
**REPORTS (never mutates)**: docker+compose present; required vars set per selected profile; dirs
exist with correct ownership (10001/10002); images present; `surveys-live` is a git checkout; code
checkout current vs origin (warn only). Output: PASS/FAIL per check with the exact fix command for
each FAIL. Wire as `make preflight`.

### 5. Any-PC quickstart
A fresh-machine path with NO tailscale, NO EliteDesk specifics: clone both repos → `cp .env.example
.env` + set two vars → `make preflight` → pull images → `make rebuild-data` → open
`http://127.0.0.1:8443`. Tailscale becomes an OPTIONAL "expose to your tailnet" section; the
EliteDesk specifics become an appendix.
**Restructure `deploy/README.md` quickstart-first:**
1. Any-PC quickstart
2. Data operations (rebuild/sync, C18 cache behaviour incl. one-cold-rebuild-after-engine-update)
3. Gateway + curator (incl. C31 editor, submit/curator key generation, the C13 upload button
   appearing when the gateway is up)
4. Troubleshooting — encode tonight's REAL incidents as entries:
   - stuck-at-SCANNED ⇒ check `gw-runner` (`compose ps`/logs; the PYTHONPATH incident)
   - None-None build id ⇒ stale engine image/checkout
   - compose interpolation errors ⇒ missing vars table
   - `pull` missing services ⇒ item 2
   - CI-sample stray in surveys-live ⇒ `git clean -nd`
5. Architecture/ownership appendix (uid split, loopback-only rationale — keep the existing good
   content, reorganized).

### 6. Complete `.env.example`
EVERY variable the compose/Makefile reads, grouped (required-always / gateway-profile /
optional-tuning like `AUSMT_CACHE_MAX_MB`, `AUSMT_EDIT_TIMEOUT_S`), a one-line comment each, and the
exact `python3 -c "import secrets; ..."` generators for the two keys.

## Scope guards (frozen)

- Compose changes limited to the `:?`→`:-` guard scoping in item 3. **No** service/volume/entrypoint
  changes.
- **No** engine/gateway/portal code changes.
- `scripts/verify.py` untouched.
- The preflight script is **read-only by design** (reports, never mutates).
- If item 3 turns out to need more than guard changes, **STOP and report**.
- Docs claims must match code behaviour EXACTLY (C4 doctrine: overclaiming docs are defects). Verify
  every documented command by running it or citing the code path.

## Verification plan (frozen)

- `docker compose config` runs are the compose-guard proof.
- shellcheck the preflight script if available, else careful POSIX review.
- Run the full engine + gateway + portal suites once to prove no collateral.

## Variable inventory (derived from the code, the compose file, and the Makefile)

Authoritative list of every `AUSMT_*` the running system reads, and where:

**Required always (portal + everything):**
- `AUSMT_DATA_DIR` — host root for `site-data` + `surveys-live` (compose mounts; Makefile
  `rebuild-data`/`sync-surveys` read it from the shell). Compose guard stays `:?`.
- `OWNER` — GHCR namespace for the images (`ghcr.io/${OWNER}/…`). Compose guard stays `:?`.
- `TAG` — image tag, defaults `latest` (`:-latest`). Not guarded.

**Gateway profile:**
- `AUSMT_SUBMIT_KEY` — submit key, ≥16 chars. App fail-closes (`config.py`). Compose guard
  `:?`→`:-` (item 3).
- `AUSMT_CODE_DIR` — checkout root; `gw-runner` bind-mounts `${AUSMT_CODE_DIR}/gateway`. `gw-runner`
  fails without the mount. Compose guard `:?`→`:-` (item 3).
- `AUSMT_CURATOR_KEYS` — curator `name:key` pairs. Already `:-` (curator routes 503 until set).
- `AUSMT_GIT_CREDS_DIR` — push-credential dir, mounted ro. Already `:-./git-creds.placeholder`.

**Optional tuning (env-only, engine or gateway reads directly, defaults in code):**
- `AUSMT_CACHE_MAX_MB` — C18 build-cache cap (default 2048; `engine/extract/cache.py`).
- `AUSMT_EDIT_TIMEOUT_S` — C31 editor poll timeout (default 120; `gateway/config.py`).
- `AUSMT_MAX_UPLOAD_MB` (250), `AUSMT_MAX_INFLIGHT` (8), `AUSMT_MAX_PER_DAY` (25),
  `AUSMT_JOB_TIMEOUT_S` (900), `AUSMT_CLAMD_HOST` (clamd), `AUSMT_CLAMD_PORT` (3310),
  `AUSMT_SESSION_TTL_S` (43200), `AUSMT_LOGIN_MAX_ATTEMPTS` (5), `AUSMT_LOGIN_WINDOW_S` (300),
  `AUSMT_HEARTBEAT_S` (30) — gateway/runner tuning, all defaulted in code.

**Container-internal (set in compose, NOT operator-facing — do not put in `.env`):**
`AUSMT_VALIDATOR_PATH`, `AUSMT_GW_DATA`, `AUSMT_SURVEYS_LIVE`, `AUSMT_SURVEYS_ROOT`,
`AUSMT_ENGINE_COMMIT`, `AUSMT_CONFIG`, `PYTHONPATH`. These are wired inside `compose.yaml`/images.

## Deviations from spec (dated)

- **2026-07-06 — compose-guard proof method.** The spec states docker is available on this box for
  `docker compose config`. The docker **engine** runs (WSL Ubuntu, v29.1.3) but the **compose CLI**
  (v2 plugin or v1 `docker-compose`) is not installed, and installing it requires an external
  binary download that is blocked in this environment. The `:?`→`:-` change is therefore proven by:
  (a) citing compose's documented interpolation semantics, (b) the repo's own CI
  (`.github/workflows/deploy-images.yml`) which runs the exact `docker compose config` /
  `--profile gateway config` proofs on every push, and (c) a self-contained Python interpolation
  checker (`deploy/scripts/check_compose_guards.py`) that implements compose's
  `${VAR:?}`/`${VAR:-}`/`${VAR:-default}` substitution rules and demonstrates, against the real
  `compose.yaml`, that with ONLY `AUSMT_DATA_DIR`+`OWNER` set the base config resolves after the
  change (and did NOT before). This is labelled a semantic check, not `docker compose config`
  output. The app-level `--profile gateway` fail-closed is proven by the existing gateway test
  suite (`gateway/tests/test_config.py`) — untouched, still green.
