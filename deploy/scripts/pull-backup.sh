#!/bin/sh
# AusMT off-box backup pull. Runs on the OPERATOR'S MAC (or any Linux laptop / cron) and pulls the
# `latest` snapshot off the box over the tailnet, so the only irreplaceable bytes on the box exist on a
# SECOND machine. POSIX sh — NOTHING Mac-specific in here; the macOS side is only the launchd wrapper
# (deploy/launchd/com.ausmt.backup-pull.plist). No personal hostnames are baked in: everything is
# env/flags.
#
# WHAT IT DOES:
#   1. resolve — ssh to the remote and read what backups/latest points to (a `latest` symlink, else a
#                latest.txt file backup.sh writes when symlinks are unavailable). Fail LOUD if the
#                remote is unreachable — a silent no-op is how you discover, months later, that your
#                only off-box copy was never being made.
#   2. pull    — rsync (preferred) or scp the RESOLVED snapshot dir into $AUSMT_BACKUP_DEST/<snapshot>/.
#                We copy the resolved timestamp, never the bare `latest`, so the local copy is named by
#                the snapshot it actually is.
#   3. prune   — keep the newest N local snapshot dirs (default 30); remove older ones.
#
# CONFIG (env or flags; flags win):
#   AUSMT_BACKUP_REMOTE   (required)  user@host:/path/to/backups   e.g. op@ausmt-box:/srv/ausmt/backups
#                                     Flag: --remote user@host:/path
#   AUSMT_BACKUP_DEST     (required)  local directory to pull into.  Flag: --dest /path
#   AUSMT_BACKUP_RETAIN   (optional)  local snapshots to keep (default 30).  Flag: --retain N
#
# TRANSPORT OVERRIDES (optional; for tests / non-standard setups):
#   AUSMT_PULL_SSH    the ssh command (default `ssh`)
#   AUSMT_PULL_RSYNC  the rsync command (default `rsync`); if unavailable, falls back to scp
#   AUSMT_PULL_SCP    the scp command (default `scp`)
#
# This pulls PII (the gateway DB). Keep $AUSMT_BACKUP_DEST on an encrypted disk with tight perms — the
# script chmods what it creates to 0700, but the parent is yours to protect.
#
# See deploy/README.md "Backups & restore" for the launchd install + first-run verification.

set -eu

REMOTE="${AUSMT_BACKUP_REMOTE:-}"
DEST="${AUSMT_BACKUP_DEST:-}"
RETAIN="${AUSMT_BACKUP_RETAIN:-30}"
SSH_CMD="${AUSMT_PULL_SSH:-ssh}"
RSYNC_CMD="${AUSMT_PULL_RSYNC:-rsync}"
SCP_CMD="${AUSMT_PULL_SCP:-scp}"

# ----- flags (override env) ----------------------------------------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    --remote) REMOTE="${2:?--remote needs a value}"; shift 2 ;;
    --dest)   DEST="${2:?--dest needs a value}"; shift 2 ;;
    --retain) RETAIN="${2:?--retain needs a value}"; shift 2 ;;
    -h|--help)
      sed -n '2,30p' "$0"; exit 0 ;;
    *) printf 'pull-backup: unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done

die() { printf 'pull-backup: ERROR: %s\n' "$*" >&2; exit 1; }

# ----- validate config LOUDLY before touching the network ----------------------------------------
[ -n "$REMOTE" ] || die "AUSMT_BACKUP_REMOTE not set (e.g. op@ausmt-box:/srv/ausmt/backups) — see --help / README."
[ -n "$DEST" ] || die "AUSMT_BACKUP_DEST not set (a local directory to pull into) — see --help / README."

# Split REMOTE (user@host:/path) into the ssh target and the remote path. rsplit on the FIRST colon
# that follows the host — a scp/rsync remote is `[user@]host:path`; the path may itself contain no
# colon on a sane box, so split on the first ':'.
case "$REMOTE" in
  *:*) : ;;
  *) die "AUSMT_BACKUP_REMOTE must be user@host:/path (has no ':'): $REMOTE" ;;
esac
REMOTE_HOST="${REMOTE%%:*}"          # user@host
REMOTE_PATH="${REMOTE#*:}"           # /srv/ausmt/backups
[ -n "$REMOTE_HOST" ] || die "AUSMT_BACKUP_REMOTE has an empty host: $REMOTE"
[ -n "$REMOTE_PATH" ] || die "AUSMT_BACKUP_REMOTE has an empty path: $REMOTE"

log() { printf '%s %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }

# ----- 1. resolve `latest` on the remote ---------------------------------------------------------
# Ask the remote what backups/latest resolves to. Prefer the symlink target (readlink); fall back to
# latest.txt (backup.sh writes it where symlinks are unavailable). A remote shell one-liner keeps this
# to a single ssh round-trip; it prints ONLY the bare snapshot name (basename), or nothing.
log "resolving latest on $REMOTE_HOST:$REMOTE_PATH"
# shellcheck disable=SC2086 -- SSH_CMD may be a multi-word override (e.g. `sh shim.sh`).
SNAPSHOT="$($SSH_CMD "$REMOTE_HOST" \
  "if [ -L '$REMOTE_PATH/latest' ]; then basename \"\$(readlink '$REMOTE_PATH/latest')\"; \
   elif [ -f '$REMOTE_PATH/latest.txt' ]; then cat '$REMOTE_PATH/latest.txt'; fi" 2>/dev/null || true)"
SNAPSHOT="$(printf '%s' "$SNAPSHOT" | tr -d '\r\n' | sed 's,.*/,,')"

if [ -z "$SNAPSHOT" ]; then
  die "could not resolve 'latest' on $REMOTE_HOST:$REMOTE_PATH — remote unreachable, or no backup has
      run yet (backups/latest missing). Check the tailnet is up and that ausmt-backup.timer has fired.
      See deploy/README.md \"Backups & restore\" troubleshooting."
fi
# Guard against a nonsense resolution (path traversal / empty-ish) — the name must look like a UTC ts.
case "$SNAPSHOT" in
  *[!0-9A-Za-z_-]*|"") die "resolved snapshot name looks wrong: '$SNAPSHOT' — refusing to pull it." ;;
esac
log "latest resolves to $SNAPSHOT"

# ----- 2. pull the resolved snapshot -------------------------------------------------------------
mkdir -p "$DEST"
chmod 0700 "$DEST" 2>/dev/null || true
LOCAL="$DEST/$SNAPSHOT"
REMOTE_SNAP="$REMOTE_HOST:$REMOTE_PATH/$SNAPSHOT"

rsync_bin=${RSYNC_CMD%% *}
if command -v "$rsync_bin" >/dev/null 2>&1; then
  log "pulling $REMOTE_SNAP -> $LOCAL via rsync"
  # -a preserve, -z compress, --partial resume a torn transfer. Trailing slash on the source so the
  # snapshot's CONTENTS land in $LOCAL (not $LOCAL/<snapshot>/).
  # shellcheck disable=SC2086 -- RSYNC_CMD may be a multi-word override.
  $RSYNC_CMD -az --partial "$REMOTE_SNAP/" "$LOCAL/" \
    || die "rsync of $REMOTE_SNAP failed (remote unreachable mid-pull? disk full?)."
else
  log "rsync ('$rsync_bin') not found — falling back to scp for $REMOTE_SNAP -> $LOCAL"
  mkdir -p "$LOCAL"
  # -r recurse the snapshot dir. scp's remote-glob semantics vary; copy the dir itself into a fresh
  # LOCAL so contents land predictably.
  # shellcheck disable=SC2086 -- SCP_CMD may be a multi-word override.
  $SCP_CMD -r "$REMOTE_SNAP/." "$LOCAL/" \
    || die "scp of $REMOTE_SNAP failed (remote unreachable mid-pull? disk full?)."
fi

# Sanity: the pull must have produced at least the DB (or, on a fresh pre-first-submission box, at
# least the status file). An empty LOCAL means the copy silently did nothing.
if [ ! -e "$LOCAL/gateway.sqlite" ] && [ ! -e "$LOCAL/reconcile-status.json" ]; then
  die "pulled snapshot $LOCAL is empty (no gateway.sqlite / reconcile-status.json) — the copy did nothing."
fi
chmod 0700 "$LOCAL" 2>/dev/null || true
log "pulled snapshot into $LOCAL"

# ----- 3. prune local copies to the newest $RETAIN ------------------------------------------------
all="$(find "$DEST" -mindepth 1 -maxdepth 1 -type d -name '[0-9]*Z' 2>/dev/null | sort -r || true)"
if [ -n "$all" ]; then
  n=0
  printf '%s\n' "$all" | while IFS= read -r d; do
    [ -n "$d" ] || continue
    n=$((n + 1))
    if [ "$n" -gt "$RETAIN" ]; then
      log "pruning old local snapshot: $(basename "$d")"
      rm -rf "$d"
    fi
  done
fi

log "done. Local snapshots (newest first) in $DEST:"
find "$DEST" -mindepth 1 -maxdepth 1 -type d -name '[0-9]*Z' 2>/dev/null | sort -r | head -n "$RETAIN" || true
