#!/bin/sh
# AusMT public front door - single apply/install script (public bridge). Runs ON THE VPS, from
# deploy/frontdoor/. It validates the shipped Caddyfile against a real Caddy (so a config slip fails
# LOUDLY before anything serves), ensures the log directory the shipper reads exists, then brings the
# one-service stack up. Idempotent: re-running it re-validates and re-applies compose (a no-op if
# nothing changed). Reversible: `docker compose -f compose.yaml down` withdraws the edge (see
# RUNBOOK.md rollback).
#
# PREREQUISITES (RUNBOOK.md does these first): the VPS is hardened + on the tailnet under the
# dedicated tag, the tailnet ACL stanza is pasted, and deploy/frontdoor/.env is filled in.
#
# CONFIG (deploy/frontdoor/.env - see .env.example): AUSMT_PUBLIC_NAME, AUSMT_BOX_READER_UPSTREAM,
# AUSMT_ACME_EMAIL, and optionally AUSMT_LEGACY_REDIRECT_NAME (the retired name kept as a permanent
# 301 to the canonical one; empty means no legacy site block is rendered at all).

set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

die() { printf 'install-frontdoor: ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf '%s %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }

# ----- preconditions -----------------------------------------------------------------------------
[ -f .env ] || die "deploy/frontdoor/.env is missing - copy .env.example, fill it in (see RUNBOOK.md)."
command -v docker >/dev/null 2>&1 || die "docker not found - install Docker + the compose plugin (RUNBOOK.md)."
docker compose version >/dev/null 2>&1 || die "the 'docker compose' plugin is not available."

# Load .env so the placeholders are set for the validate step below (compose loads it again itself).
set -a
# shellcheck disable=SC1091
. ./.env
set +a
[ -n "${AUSMT_PUBLIC_NAME:-}" ] || die "AUSMT_PUBLIC_NAME is empty in .env (the canonical public name)."
[ -n "${AUSMT_BOX_READER_UPSTREAM:-}" ] || die "AUSMT_BOX_READER_UPSTREAM is empty in .env (the box reader upstream)."
[ -n "${AUSMT_ACME_EMAIL:-}" ] || die "AUSMT_ACME_EMAIL is empty in .env (ACME contact email)."
# The legacy redirect name is OPTIONAL: empty is a valid, fully supported state (canonical only).
AUSMT_LEGACY_REDIRECT_NAME="${AUSMT_LEGACY_REDIRECT_NAME:-}"
export AUSMT_LEGACY_REDIRECT_NAME

# ----- render the Caddyfile (the legacy redirect block in or out) --------------------------------
# Caddyfile `{$VAR}` interpolation cannot conditionally omit a SITE BLOCK: with the legacy var
# unset, the legacy block's address would render EMPTY, a parse error, so Caddy would fail to start
# on exactly the deploy that has no legacy name. The installer therefore templates the block: the
# tracked Caddyfile carries it between the `# >>> legacy-redirect` / `# <<< legacy-redirect`
# markers, and this step writes Caddyfile.rendered (gitignored; compose mounts it) with the marked
# range kept (var set) or stripped (var empty). doctor.sh re-renders the same way for its
# running-config hash compare, so keep the two sed expressions identical.
if [ -n "$AUSMT_LEGACY_REDIRECT_NAME" ]; then
	log "rendering Caddyfile.rendered WITH the legacy redirect block ($AUSMT_LEGACY_REDIRECT_NAME -> $AUSMT_PUBLIC_NAME)"
	cp Caddyfile Caddyfile.rendered
else
	log "rendering Caddyfile.rendered WITHOUT the legacy redirect block (AUSMT_LEGACY_REDIRECT_NAME empty)"
	sed '/^# >>> legacy-redirect/,/^# <<< legacy-redirect/d' Caddyfile > Caddyfile.rendered
fi

# ----- log directory the masked access log + the box-side shipper use ----------------------------
# Caddy writes /var/log/caddy/access-frontdoor.json here; ship-frontdoor-logs.sh (on the box) pulls it.
log "ensuring /var/log/caddy exists (masked access log destination)"
sudo mkdir -p /var/log/caddy

# ----- the time-series hand-off table -------------------------------------------------------------
# ts-routes.map is GENERATED and COMMITTED (deploy/scripts/gen_ts_routes.py) and the Caddyfile
# `import`s it, so it is part of the config: validate below would fail on a missing import, and the
# edge would refuse to start. Its absence is a legitimate state (no verified routes published, or a
# deliberate rollback), so the installer creates an EMPTY table rather than dying - every /go/ts/
# path then 404s, which is exactly the withdrawal the RUNBOOK's rollback line describes.
if [ ! -f ts-routes.map ]; then
	log "no ts-routes.map present - writing an EMPTY table (every /go/ts/ path will 404)"
	printf '# no time-series hand-off routes published on this deploy.\n' > ts-routes.map
fi

# ----- validate the RENDERED Caddyfile against a real Caddy ---------------------------------------
# Fail the deploy on any config slip BEFORE serving. The rendered file is what the container mounts,
# so it is what gets validated. Mount the log dir so the file-log writer opens cleanly during adapt,
# the route table at the path the Caddyfile imports (validate reads the import, so an unmounted table
# fails here rather than at startup), and pass the .env placeholders through (the legacy var
# included, so the set-var rendering resolves).
log "validating Caddyfile.rendered against caddy:2-alpine"
docker run --rm \
	-e AUSMT_PUBLIC_NAME -e AUSMT_BOX_READER_UPSTREAM -e AUSMT_ACME_EMAIL -e AUSMT_LEGACY_REDIRECT_NAME \
	-v "$HERE/Caddyfile.rendered:/etc/caddy/Caddyfile:ro" \
	-v "$HERE/ts-routes.map:/etc/caddy/ts-routes.map:ro" \
	-v /var/log/caddy:/var/log/caddy \
	caddy:2-alpine caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile \
	|| die "caddy validate rejected the rendered front-door Caddyfile - fix it before deploying."

# ----- apply the stack ----------------------------------------------------------------------------
# Was the edge ALREADY running before this apply? If so, a `compose up -d` that sees no image/compose
# change will NOT recreate the container, so a container that keeps a bind-mounted Caddyfile would go on
# serving the OLD config in memory (the stale-wall failure mode: the new Caddyfile validates, but the
# running edge never picks it up). We capture that state BEFORE `up -d` so we know whether an explicit
# reload is needed afterwards. `ps -q` prints the container id only when the service has a running
# container; empty => not running (fresh install), so no reload is needed (up -d starts it clean).
WAS_RUNNING=""
if [ -n "$(docker compose -f compose.yaml ps -q frontdoor 2>/dev/null)" ]; then
	WAS_RUNNING=yes
fi

log "starting the front-door stack (docker compose up -d)"
docker compose -f compose.yaml up -d

# ----- reload the RUNNING edge so a Caddyfile change actually takes effect (ops-hardening) ----------
# If the edge was already running, `up -d` may have left the old process serving the old config. Reload
# it in place: `caddy reload` reads the admin address from the (unix-socket) admin block in the file and
# hot-swaps the config with no downtime. If the reload FAILS for ANY reason (admin disabled, or the
# process-table exhaustion we hit in the zombie incident where exec itself could not fork), fall back to
# a full `compose restart` with a LOUD warning - the config still lands, just with a ~1s bounce (certs
# persist in the caddy_data volume). A fresh install (WAS_RUNNING empty) skips this: up -d already
# started the container against the current file.
if [ -n "$WAS_RUNNING" ]; then
	log "edge was already running - reloading it in place so the new Caddyfile takes effect"
	if docker compose -f compose.yaml exec -T frontdoor caddy reload --config /etc/caddy/Caddyfile; then
		log "caddy reload OK - the running edge now serves the shipped Caddyfile"
	else
		printf '\n' >&2
		printf 'install-frontdoor: WARNING: caddy reload FAILED (admin disabled, or the container could\n' >&2
		printf 'install-frontdoor: WARNING: not fork - see the zombie kit in RUNBOOK.md). Falling back\n' >&2
		printf 'install-frontdoor: WARNING: to a full restart so the new config still takes effect.\n' >&2
		printf '\n' >&2
		docker compose -f compose.yaml restart frontdoor \
			|| die "reload FAILED and restart FAILED - the edge may still serve the OLD config. Investigate on the VPS (docker compose -f compose.yaml ps; ./doctor.sh)."
		log "restart fallback complete - the edge now serves the shipped Caddyfile"
	fi
fi

if [ -n "$AUSMT_LEGACY_REDIRECT_NAME" ]; then
	log "done. Serving canonical $AUSMT_PUBLIC_NAME with legacy $AUSMT_LEGACY_REDIRECT_NAME as a permanent 301 to it."
	log "Next: watch BOTH certificates issue (one ACME obtain per name) -"
else
	log "done. Serving canonical $AUSMT_PUBLIC_NAME (no legacy redirect name configured)."
	log "Next: watch the certificate issue for $AUSMT_PUBLIC_NAME -"
fi
log "  docker compose -f compose.yaml logs -f frontdoor    # look for a successful certificate obtain"
log "Then run the verification checklist in RUNBOOK.md (content check FIRST, then TLS, refuse checks, redirect leg, logs)."
