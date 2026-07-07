# POSIX sh, Linux-targeted (the EliteDesk deployment host — see deploy/README.md). Not tested
# against BSD/macOS make; every recipe line is plain sh, no GNU-make-only extensions beyond the
# ubiquitous $(VAR)/.PHONY that both GNU make and most POSIX makes accept.
#
# Run from the deploy/ directory (`cd deploy && make <target>`) or `make -C deploy <target>` —
# every compose invocation below is relative to this file's directory, matching the .env lookup
# `docker compose` does by default (a sibling .env next to the compose file it's given).

.PHONY: build up down rebuild-data smoke sync-surveys preflight

# C33: read-only host preflight. Checks docker/compose, required vars for the profile, dir
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

# C12: the real atomic rebuild pipeline. Build into a FRESH timestamped builds/<ts> dir (never reuse
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
# C18: this is the ONE place the incremental build cache is switched ON
# (--incremental --cache-dir /out/cache --cache-mode rw). The cache lives at /out/cache -- a SIBLING
# of /out/builds, so the `ls -1t | tail -n +6 | rm -rf` prune below (which runs INSIDE /out/builds)
# never touches it, and it survives the `mv -T current` swap. It only speeds a rebuild; it can never
# change output bytes (verify.py stays full/cache-blind, and the CI equivalence test pins that). The
# engine default is OFF and the gateway runner stays non-incremental; a degenerate salt (unknown
# engine commit, or a dirty checkout) silently disables the cache for that build. In production the
# salt is HEALTHY: docker/engine.Dockerfile bakes ARG GIT_SHA -> ENV AUSMT_ENGINE_COMMIT and
# deploy-images.yml passes github.sha, so a current image always resolves its engine commit (null
# commits once seen in the live box's build.json came from a stale pre-GIT_SHA-bake image -- pull a
# current image and the cache fires). Losing the cache dir costs one slow rebuild, nothing more.
# C18b (Amendment A3): the verify step passes --surveys (same root the build used) to ARM the
# cache-staleness digest gate -- served-product digest stamps vs live survey.yaml, cache-independent.
rebuild-data:
	@set -e; \
	DATA_DIR=$${AUSMT_DATA_DIR:?set AUSMT_DATA_DIR (see .env)}/site-data; \
	TS=$$(date -u +%Y%m%dT%H%M%SZ); \
	BUILD_REL="builds/$$TS"; \
	echo "rebuild-data: building into $$DATA_DIR/$$BUILD_REL"; \
	if ! docker compose -f compose.yaml --profile jobs run --rm build-runner \
	      --surveys /srv/surveys/surveys --out /out/$$BUILD_REL --bundle-edi \
	      --products /out/$$BUILD_REL/products \
	      --incremental --cache-dir /out/cache --cache-mode rw; then \
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

# Post-deploy smoke check: the portal serves 200s for the app shell and the generated catalogue.
smoke:
	curl -fsS http://localhost:8443/ > /dev/null && echo "OK: / (200)"
	curl -fsS http://localhost:8443/data/catalogue.json > /dev/null && echo "OK: /data/catalogue.json (200)"

# Fast-forward-only pull of the surveys-live checkout — refuses to run (and exits non-zero) if the
# local checkout has diverged (e.g. an operator's stray local edit), rather than silently merging
# or rebasing an unattended host checkout.
sync-surveys:
	git -C $${AUSMT_DATA_DIR:?set AUSMT_DATA_DIR (see .env)}/surveys-live pull --ff-only
