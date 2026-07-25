#!/bin/sh
# AusMT public front door - single apply/install script (C47 public bridge). Runs ON THE VPS, from
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
# AUSMT_ACME_EMAIL.

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
[ -n "${AUSMT_PUBLIC_NAME:-}" ] || die "AUSMT_PUBLIC_NAME is empty in .env (the public demo name)."
[ -n "${AUSMT_BOX_READER_UPSTREAM:-}" ] || die "AUSMT_BOX_READER_UPSTREAM is empty in .env (the box reader upstream)."
[ -n "${AUSMT_ACME_EMAIL:-}" ] || die "AUSMT_ACME_EMAIL is empty in .env (ACME contact email)."

# ----- log directory the masked access log + the box-side shipper use ----------------------------
# Caddy writes /var/log/caddy/access-frontdoor.json here; ship-frontdoor-logs.sh (on the box) pulls it.
log "ensuring /var/log/caddy exists (masked access log destination)"
sudo mkdir -p /var/log/caddy

# ----- validate the shipped Caddyfile against a real Caddy ----------------------------------------
# Fail the deploy on any config slip BEFORE serving. Mount the log dir so the file-log writer opens
# cleanly during adapt, and pass the .env placeholders through.
log "validating Caddyfile against caddy:2-alpine"
docker run --rm \
	-e AUSMT_PUBLIC_NAME -e AUSMT_BOX_READER_UPSTREAM -e AUSMT_ACME_EMAIL \
	-v "$HERE/Caddyfile:/etc/caddy/Caddyfile:ro" \
	-v /var/log/caddy:/var/log/caddy \
	caddy:2-alpine caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile \
	|| die "caddy validate rejected the front-door Caddyfile - fix it before deploying."

# ----- apply the stack ----------------------------------------------------------------------------
# Was the edge ALREADY running before this apply? If so, a `compose up -d` that sees no image/compose
# change will NOT recreate the container, so a container that keeps a bind-mounted Caddyfile would go on
# serving the OLD config in memory (the 2026-07 stale-wall incident: the new Caddyfile validated, but the
# running edge never picked it up). We capture that state BEFORE `up -d` so we know whether an explicit
# reload is needed afterwards. `ps -q` prints the container id only when the service has a running
# container; empty => not running (fresh install), so no reload is needed (up -d starts it clean).
WAS_RUNNING=""
if [ -n "$(docker compose -f compose.yaml ps -q frontdoor 2>/dev/null)" ]; then
	WAS_RUNNING=yes
fi

log "starting the front-door stack (docker compose up -d)"
docker compose -f compose.yaml up -d

# ----- reload the RUNNING edge so a Caddyfile change actually takes effect (ops-hardening O1) -------
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
		printf 'install-frontdoor: WARNING: not fork - see the O3 zombie kit in RUNBOOK.md). Falling back\n' >&2
		printf 'install-frontdoor: WARNING: to a full restart so the new config still takes effect.\n' >&2
		printf '\n' >&2
		docker compose -f compose.yaml restart frontdoor \
			|| die "reload FAILED and restart FAILED - the edge may still serve the OLD config. Investigate on the VPS (docker compose -f compose.yaml ps; ./doctor.sh)."
		log "restart fallback complete - the edge now serves the shipped Caddyfile"
	fi
fi

log "done. Next: watch the certificate issue for $AUSMT_PUBLIC_NAME -"
log "  docker compose -f compose.yaml logs -f frontdoor    # look for a successful certificate obtain"
log "Then run the verification checklist in RUNBOOK.md (content check FIRST, then TLS, refuse checks, logs)."
