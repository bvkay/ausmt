# POSIX sh, Linux-targeted (the EliteDesk deployment host — see deploy/README.md). Not tested
# against BSD/macOS make; every recipe line is plain sh, no GNU-make-only extensions beyond the
# ubiquitous $(VAR)/.PHONY that both GNU make and most POSIX makes accept.
#
# Run from the deploy/ directory (`cd deploy && make <target>`) or `make -C deploy <target>` —
# every compose invocation below is relative to this file's directory, matching the .env lookup
# `docker compose` does by default (a sibling .env next to the compose file it's given).

.PHONY: build up down rebuild-data cut-release smoke sync-surveys preflight reconcile refresh-pid-status doctor

# Read deploy/.env so `make` targets see the SAME truth `docker compose` does (compose
# auto-loads a sibling .env; make does not). `-include` => absent .env is not an error (portal-only /
# CI `docker compose config` paths never need it). `export` (no args) then forwards every make
# variable — including the .env ones just read — into each recipe's shell environment, so the
# reconcile script and the compose calls resolve AUSMT_DATA_DIR/AUSMT_CODE_DIR identically whether
# invoked from a login shell or the systemd timer (the "works interactively, fails from
# the timer" class). The shell-level `:?` guards in the recipes below still fire on an unset/empty
# value, so this widens where the vars COME FROM without weakening the fail-closed checks.
-include .env
export

# Ops-hardening: one-screen box health. Runs scripts/doctor-box.sh, which prints a labelled
# PASS/WARN/FAIL line per check (containers, gateway healthz, the reader wall on loopback, surveys-live
# git/perms/ACL, the reconcile timer, disk, served-vs-published staleness) and EXITS NON-ZERO if any
# check FAILs, so `make doctor` can gate a script or an alert. Select the gateway checks with
# `make doctor PROFILE=gateway` (default portal). Read-only; it never mutates anything. The VPS edge has
# its own doctor: deploy/frontdoor/doctor.sh (run on the VPS).
doctor:
	PROFILE=$${PROFILE:-portal} sh scripts/doctor-box.sh

# Read-only host preflight. Checks docker/compose, required vars for the profile, dir
# ownership (10001/10002), images, surveys-live-is-a-git-checkout, and code-checkout freshness —
# and REPORTS pass/fail with the exact fix command for each fail. It NEVER mutates anything.
# Select the gateway checks with `make preflight PROFILE=gateway` (default is portal-only).
preflight:
	AUSMT_PROFILE=$${PROFILE:-portal} sh scripts/preflight.sh

# Build both images locally from the repo checkout (dev-style; production pulls from GHCR instead
# — see compose.yaml). Requires compose.dev.yaml's build: contexts.
build:
	docker compose -f compose.yaml -f compose.dev.yaml build

# Start the always-on portal service (build-runner never starts here — it's profile "jobs").
up:
	docker compose -f compose.yaml up -d

down:
	docker compose -f compose.yaml down

# The real atomic rebuild pipeline. Build into a FRESH timestamped builds/<ts> dir (never reuse
# or overwrite an existing one -- the timestamp is the collision-avoidance), verify that output dir
# in place (scripts/verify.py --data-dir, run INSIDE the build-runner container so it sees the same
# /out mount and Python/mt_metadata stack the build itself used), and ONLY on a clean verify swap the
# `current` symlink via temp-symlink + `mv -T` -- a true rename(2), so readers NEVER observe a
# missing or half-updated `current`. (`ln -sfn` is NOT atomic: it unlinks then re-creates, leaving a
# window with no symlink at all; Caddy follows `current` per-request through the whole-tree mount,
# so that window would 404 live traffic.) A failed build or a failed verify BOTH leave `current`
# untouched and exit
# non-zero, printing the failed dir's path so an operator can inspect it directly -- a bad build must
# never reach readers, and a failure must never be silent.
#
# set -e (not per-line `&&` chaining) so ANY failing step -- build, verify, or the prune -- aborts
# immediately with a non-zero exit; the "on failure, leave current untouched" guarantee falls out of
# ordering (the symlink swap is the LAST step) rather than explicit rollback logic.
#
# The swap + prune run INSIDE the build-runner container (as uid 10001), NOT on the host: site-data
# is owned by the container user (deploy/README.md ownership split), so a host-side ln/mv/rm as the
# operator gets Permission denied -- exactly what the first real deployment hit after the build and
# verify (both already in-container) succeeded. Everything that writes site-data now runs as the
# one uid that owns it. The relative symlink target "builds/<ts>" resolves identically inside the
# container (/out) and inside the portal container (/srv/data), so the swap stays live-atomic.
#
# This is the ONE place the incremental build cache is switched ON
# (--incremental --cache-dir /out/cache --cache-mode $CACHE_MODE, default rw). A curator
# "Force full rebuild" writes rebuild.request with a `full` flag; reconcile.sh reads it and sets
# AUSMT_BUILD_CACHE_MODE=refresh, so the engine recomputes everything (no cache reuse) for that one
# build. Unset => rw (today's behaviour, byte-identical). The cache lives at /out/cache -- a SIBLING
# of /out/builds, so the `ls -1t | tail -n +6 | rm -rf` prune below (which runs INSIDE /out/builds)
# never touches it, and it survives the `mv -T current` swap. It only speeds a rebuild; it can never
# change output bytes (verify.py stays full/cache-blind, and the CI equivalence test pins that). The
# engine default is OFF and the gateway runner stays non-incremental; a degenerate salt (unknown
# engine commit, or a dirty checkout) silently disables the cache for that build. In production the
# salt is HEALTHY: docker/engine.Dockerfile bakes ARG GIT_SHA -> ENV AUSMT_ENGINE_COMMIT and
# deploy-images.yml passes github.sha, so a current image always resolves its engine commit (null
# commits once seen in the live box's build.json came from a stale pre-GIT_SHA-bake image -- pull a
# current image and the cache fires). Losing the cache dir costs one slow rebuild, nothing more.
# The verify step passes --surveys (the same root the build used) to ARM the
# cache-staleness digest gate -- served-product digest stamps vs live survey.yaml, cache-independent.
# --survey-h5: tier-2 survey MTH5 bundles.
# --station-h5: tier-1 per-station MTH5 (h5/<slug>/<station>.h5).
# --ts-index: the per-survey verified-resource registers, read OFFLINE from the SAME root --surveys
# names (each register sits beside its survey.yaml). Without it the box publishes no ts_access.json,
# no has_time_series and no kind=time_series rows, while the front door goes on serving every
# /go/ts/ route in the committed table - the table AHEAD of the data, which doctor-box.sh's
# ts-parity leg reports as a FAIL. Fail-closed by design: a register the build cannot read stops the
# build rather than publishing the part of it that happened to parse.
# The engine image deliberately excludes portal/, so the portal.config.yaml flags cannot reach a box
# build; these CLI flags are the production enable and this line is their single source of truth. A
# producer enabled in the YAML alone is a no-op here, which has bitten twice, so
# deploy/tests/test_makefile_build_flags.py pins every producer flag against this line in both
# directions (present here, and a real option of the engine CLI).
rebuild-data:
	@set -e; \
	DATA_DIR=$${AUSMT_DATA_DIR:?set AUSMT_DATA_DIR (see .env)}/site-data; \
	TS=$$(date -u +%Y%m%dT%H%M%SZ); \
	BUILD_REL="builds/$$TS"; \
	CACHE_MODE=$${AUSMT_BUILD_CACHE_MODE:-rw}; \
	BUILD_WORKERS=$${AUSMT_BUILD_WORKERS:-auto}; \
	echo "rebuild-data: building into $$DATA_DIR/$$BUILD_REL (cache-mode=$$CACHE_MODE workers=$$BUILD_WORKERS)"; \
	if ! docker compose -f compose.yaml --profile jobs run --rm build-runner \
	      --surveys /srv/surveys/surveys --out /out/$$BUILD_REL --bundle-edi --survey-h5 --station-h5 \
	      --ts-index /srv/surveys/surveys \
	      --products /out/$$BUILD_REL/products \
	      --pid-status /out/cache/pid_status.json \
	      --workers $$BUILD_WORKERS \
	      --sitemap-base $${AUSMT_SITEMAP_BASE:-https://ausmt.auscope.org.au} \
	      --incremental --cache-dir /out/cache --cache-mode $$CACHE_MODE; then \
	  echo "rebuild-data: BUILD FAILED -- current left untouched. Inspect $$DATA_DIR/$$BUILD_REL" >&2; \
	  exit 1; \
	fi; \
	if ! docker compose -f compose.yaml --profile jobs run --rm --entrypoint python build-runner \
	      scripts/verify.py --data-dir /out/$$BUILD_REL --surveys /srv/surveys/surveys; then \
	  echo "rebuild-data: VERIFY FAILED -- current left untouched. Inspect $$DATA_DIR/$$BUILD_REL" >&2; \
	  exit 1; \
	fi; \
	if ! docker compose -f compose.yaml --profile jobs run --rm -e TS="$$TS" --entrypoint sh build-runner -c 'set -e; ln -s "builds/$$TS" "/out/current.tmp.$$TS"; mv -T "/out/current.tmp.$$TS" /out/current; cd /out/builds; ls -1t | tail -n +6 | while read -r old; do echo "rebuild-data: pruning old build $$old"; rm -rf -- "$$old"; done'; then \
	  echo "rebuild-data: SWAP FAILED -- inspect $$DATA_DIR (current still points at the previous build, if any)" >&2; \
	  exit 1; \
	fi; \
	echo "rebuild-data: current -> $$BUILD_REL"; \
	echo "rebuild-data: done"

# =================================================================================================
# THE QUARTERLY RELEASE RITUAL (cut-release)
# =================================================================================================
# Cut a CITABLE snapshot of the corpus: "AusMT Data Portal, Release 2026-Q3". Run it once a quarter,
# in this order, and never out of order:
#
#   1. make sync-surveys            fast-forward the surveys-live checkout to the corpus you intend
#                                   to freeze (the release's source_commit comes from THIS checkout)
#   2. make refresh-pid-status      refresh the DOI resolution cache BEFORE the build, so reserved-
#                                   but-404 DOIs render honestly in the bytes about to be frozen
#   3. make rebuild-data            build + verify + atomically swap `current`
#   4. make cut-release TAG=2026-Q3 NOTE="one line"
#   5. run the two `git -C .../surveys-live tag ...` commands the tool PRINTS. It never runs git:
#      tagging pushes to an authenticated remote, which a build container has no business
#      holding a credential for.
#
# WHAT IT DOES. Follows `current`, copies that build's mtcat.json / surveys.json / manifest.json and
# the whole bundles/ tree into /out/releases/<TAG>/, re-hashes every copied bundle against the
# download manifest's own sha256 claims (ANY mismatch fails the cut and leaves nothing behind),
# writes release.json (build id, both commits, corpus counts, per-file size+sha256), updates the
# newest-first /out/releases/releases.json index, and emits a DataCite Schema 4 record ready to
# submit unchanged. releases/ is a SIBLING of builds/, like cache/, so it survives both the
# rebuild-data prune and the `current` symlink swap.
#
# IT MINTS NOTHING. No network, no DataCite credentials. While the DOI is null the DataCite record
# deliberately carries no identifier at all. Once AuScope's ARDC/DataCite access lands and the DOI is
# minted, run the SAME target again with DOI= to stamp it back in:
#
#   make cut-release TAG=2026-Q3 DOI=10.xxxxx/yyyy      # backfill: rewrites release.json +
#                                                       # datacite.json only, never re-copies data
#
# A cut release is IMMUTABLE: re-cutting an existing TAG (without DOI=) is a hard error, because
# something may already cite it.
#
# TAG= is REQUIRED and is the RELEASE tag. Note the name collision: compose.yaml uses ${TAG:-latest}
# for the IMAGE tag, and this Makefile exports its variables into every recipe, so an unguarded run
# would ask Docker for `ausmt-engine:2026-Q3`. `env -u TAG` strips it for the compose call only, so
# compose resolves the image tag from its own sibling .env exactly as every other target does.
#
# Runs INSIDE the build-runner container (site-data at /out) for the same reason the rebuild-data
# swap does: site-data is owned by uid 10001, so a host-side write gets Permission denied. Uses
# --entrypoint python because the image entrypoint is build_portal and this is a different module.
# --surveys-live is passed the HOST path so the tag commands it prints are the exact commands run
# on the box, not container-internal paths.
cut-release:
	@set -e; \
	REL_TAG="$(TAG)"; \
	if [ -z "$$REL_TAG" ]; then \
	  echo "cut-release: set TAG=<release tag>, e.g. make cut-release TAG=2026-Q3" >&2; exit 2; \
	fi; \
	SURVEYS_LIVE="$${AUSMT_DATA_DIR:?set AUSMT_DATA_DIR (see .env)}/surveys-live"; \
	set -- --data /out --tag "$$REL_TAG" --surveys-live "$$SURVEYS_LIVE"; \
	if [ -n "$${DOI:-}" ]; then set -- "$$@" --doi "$$DOI"; fi; \
	if [ -n "$${NOTE:-}" ]; then set -- "$$@" --note "$$NOTE"; fi; \
	echo "cut-release: cutting release $$REL_TAG from the current build"; \
	env -u TAG docker compose -f compose.yaml --profile jobs run --rm --entrypoint python \
	  build-runner -m extract.cut_release "$$@"

# Refresh the DOI resolution cache. This is the ONLY thing that HEADs doi.org -
# the build itself stays OFFLINE and byte-reproducible, consuming /out/cache/pid_status.json if present.
# Run it EXPLICITLY as part of the release ritual (step 4), BEFORE `rebuild-data`, so a reserved-
# but-404 DOI (e.g. a freshly-minted NCI PID whose handle mapping is not yet live) renders as plain text
# rather than a dead link. Network-touching, so it runs OUTSIDE the deterministic build — a stale cache is
# an accepted cost of an offline build (the curator status chip is the always-live check). Writes into
# /out/cache (the SIBLING-of-/out/builds tier that survives the `current` swap and the build prune), so
# the very next `rebuild-data` picks it up. Uses --entrypoint python (the image entrypoint is build_portal;
# this runs a different engine script), same shape as the verify step above. As uid 10001 (owns /out).
refresh-pid-status:
	@set -e; \
	echo "refresh-pid-status: HEADing doi.org for every corpus DOI -> /out/cache/pid_status.json"; \
	docker compose -f compose.yaml --profile jobs run --rm --entrypoint python build-runner \
	  scripts/refresh_pid_status.py --surveys /srv/surveys/surveys --out /out/cache/pid_status.json; \
	echo "refresh-pid-status: done (the next rebuild-data consumes the cache)"

# Post-deploy smoke check: the portal serves 200s for the app shell and the generated catalogue.
smoke:
	curl -fsS http://localhost:8443/ > /dev/null && echo "OK: / (200)"
	curl -fsS http://localhost:8443/data/catalogue.json > /dev/null && echo "OK: /data/catalogue.json (200)"

# Fast-forward-only pull of the surveys-live checkout — refuses to run (and exits non-zero) if the
# local checkout has diverged (e.g. an operator's stray local edit), rather than silently merging
# or rebasing an unattended host checkout.
sync-surveys:
	git -C $${AUSMT_DATA_DIR:?set AUSMT_DATA_DIR (see .env)}/surveys-live pull --ff-only

# Run the serve-reconcile agent ONCE in the foreground (what the systemd timer runs every 15
# min — deploy/systemd/ausmt-reconcile.timer). Handy for a manual reconcile or to watch a rebuild
# decision live. Reads AUSMT_DATA_DIR + AUSMT_CODE_DIR from the environment (the `-include .env` +
# export above makes .env values visible here). `make reconcile ARGS=--dry-run` prints the decision
# without acting. The script itself exits 0 on noop/rebuilt/sync_failed and 1 only on a build failure.
reconcile:
	AUSMT_CODE_DIR=$${AUSMT_CODE_DIR:-$$(cd .. && pwd)} scripts/reconcile.sh $(ARGS)
