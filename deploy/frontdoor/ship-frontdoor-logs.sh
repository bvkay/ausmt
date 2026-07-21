#!/bin/sh
# AusMT front-door log shipping (C47 deliverable 3). Runs ON THE BOX (systemd oneshot, fired by
# ausmt-frontdoor-logs.timer a few minutes AHEAD of the daily C45 fold). It PULLS the masked
# access-frontdoor*.json logs off the VPS over the tailnet into the box's Caddy log dir — the exact
# directory the C45 aggregator already globs (`access*.json`). Once landed, the daily ausmt-stats fold
# attributes the public downloads/visits/countries just as it does the box's own log.
#
# WHY PULL (box -> VPS), not push: the tailnet ACL grants the front-door tag reach ONLY to the box's
# reader port; it has no inbound path to the box. The box initiates this copy instead (box -> VPS:22),
# a separate ACL grant that never widens the front-door tag. Same trust model as pull-backup.sh.
#
# The masking already happened AT THE EDGE (the front-door Caddyfile) — this script moves bytes, it
# does not (and must not) see a full client IP; the lines it copies are already /24//48-masked.
#
# CONFIG (env or flags; flags win):
#   AUSMT_FRONTDOOR_LOG_REMOTE  (required)  user@vps:/path/to/caddy/logdir
#                                           e.g. caddylog@ausmt-vps:/var/log/caddy   Flag: --remote ...
#   AUSMT_FRONTDOOR_LOG_DEST    (optional)  local dir to land logs in.
#                                           [default $AUSMT_DATA_DIR/logs/caddy]     Flag: --dest ...
#
# TRANSPORT OVERRIDE (optional; for tests):
#   AUSMT_SHIP_RSYNC   the rsync command (default `rsync`)
#   AUSMT_SHIP_SSH     the ssh command rsync tunnels over (default `ssh`)
#
# See deploy/frontdoor/RUNBOOK.md ("Log shipping") for the ssh key + first-run verification.

set -eu

REMOTE="${AUSMT_FRONTDOOR_LOG_REMOTE:-}"
DEST="${AUSMT_FRONTDOOR_LOG_DEST:-}"
RSYNC_CMD="${AUSMT_SHIP_RSYNC:-rsync}"
SSH_CMD="${AUSMT_SHIP_SSH:-ssh}"

# ----- flags (override env) ----------------------------------------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    --remote) REMOTE="${2:?--remote needs a value}"; shift 2 ;;
    --dest)   DEST="${2:?--dest needs a value}"; shift 2 ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) printf 'ship-frontdoor-logs: unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done

die() { printf 'ship-frontdoor-logs: ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf '%s %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }

# ----- resolve DEST from AUSMT_DATA_DIR if not given ----------------------------------------------
if [ -z "$DEST" ]; then
  [ -n "${AUSMT_DATA_DIR:-}" ] || die "neither AUSMT_FRONTDOOR_LOG_DEST nor AUSMT_DATA_DIR is set — cannot place logs."
  DEST="$AUSMT_DATA_DIR/logs/caddy"
fi

# ----- validate config LOUDLY before touching the network ----------------------------------------
[ -n "$REMOTE" ] || die "AUSMT_FRONTDOOR_LOG_REMOTE not set (e.g. caddylog@ausmt-vps:/var/log/caddy) — see --help / RUNBOOK.md."
case "$REMOTE" in
  *:*) : ;;
  *) die "AUSMT_FRONTDOOR_LOG_REMOTE must be user@host:/path (has no ':'): $REMOTE" ;;
esac

# The aggregator reads this dir; create it if absent (matches the box's own logs/caddy mount path).
mkdir -p "$DEST"

# ----- pull the masked front-door logs over the tailnet ------------------------------------------
# rsync over ssh, copying ONLY the front-door access log family (access-frontdoor.json + its rolled
# siblings) so nothing else on the VPS log dir is dragged in and the box's own access.json is never
# touched. -a preserves times (idempotent re-copies are no-ops); -z compresses over the wire; the
# trailing slash on the remote path copies the DIRECTORY CONTENTS (filtered), not the dir itself.
# shellcheck disable=SC2086 -- RSYNC_CMD / SSH_CMD may be multi-word overrides (tests pass `sh shim.sh`).
log "pulling access-frontdoor logs from $REMOTE -> $DEST"
$RSYNC_CMD -az \
  -e "$SSH_CMD" \
  --include='access-frontdoor*.json' \
  --exclude='*' \
  "$REMOTE/" "$DEST/" \
  || die "rsync of front-door logs failed — check the tailnet, the ssh key, and the ACL (box -> VPS:22)."

log "front-door logs shipped; the daily ausmt-stats fold will pick them up from $DEST."
