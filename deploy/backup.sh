#!/bin/sh
# AusMT on-box backup — a consistent snapshot of the ONLY irreplaceable bytes on the box.
#
# WHAT THIS BACKS UP (and, deliberately, what it does NOT):
#   IN  - gateway/state/gateway.sqlite  -- the ONE PII home + the audit trail (submitter PII,
#                                          uploader-key HASHES, the audit history). The single
#                                          genuinely irreplaceable file. Snapshotted CONSISTENTLY
#                                          because the gateway runs it in WAL mode (gateway/db.py sets
#                                          PRAGMA journal_mode=WAL): a raw `cp` of a live WAL DB can
#                                          miss committed transactions still in the -wal sidecar. A
#                                          correct hot backup copies the DB *through SQLite*, not the
#                                          filesystem (see snapshot_sqlite below).
#   IN  - gateway/state/reconcile-status.json + any OTHER non-secret file in the state dir -- small
#                                          operational metadata the box has no other copy of.
#   OUT - deploy/.env                    -- NEVER. The secrets live in the operator's PASSWORD MANAGER,
#                                          out of band. A backup that copied .env would put secrets in a
#                                          snapshot tree the Mac then pulls over the tailnet — exactly
#                                          the leak this design prevents. (See the secret-skip filter.)
#   OUT - surveys-live/                  -- NEVER here. Its backup IS GitHub (it is a git checkout of a
#                                          remote). A local copy adds nothing a `git clone` cannot give.
#   OUT - site-data/ , cache/            -- REGENERABLE with `make rebuild-data`. Not irreplaceable, so
#                                          not archived.
#
# WHY the DB never leaves this snapshot tree for a git repo (ausmt-surveys or any repo): the sqlite DB
# is the PII CONTAINMENT BOUNDARY. CI clones the surveys repo; anything committed there is effectively
# public. PII must never enter any git repo. This backup writes to a plain directory under the data
# root and is pulled OFF-box by deploy/scripts/pull-backup.sh — never git.
#
# OUTPUT LAYOUT:
#   $AUSMT_DATA_DIR/backups/<utc-ts>/                 one directory per snapshot (YYYYmmddTHHMMSSZ)
#   $AUSMT_DATA_DIR/backups/<utc-ts>/gateway.sqlite   the WAL-safe DB copy
#   $AUSMT_DATA_DIR/backups/<utc-ts>/reconcile-status.json + other non-secret state files
#   $AUSMT_DATA_DIR/backups/latest -> <newest-ts>     a symlink the Mac pull follows
#   Retention: the newest 14 snapshot directories are kept; older ones are pruned.
#
# WHO RUNS IT: the OPERATOR (via ausmt-backup.timer), who is in the shared group 10002 that owns the
# state dir with g+rwX,g+s (README ownership prep). Group-read lets the operator read the DB; the g+w
# lets SQLite create the -wal/-shm sidecars it needs to open a WAL DB (opening a WAL DB writes to the
# directory even for a read). If the state dir is not readable, this fails LOUDLY pointing at that prep.
#
# USAGE:
#   AUSMT_DATA_DIR=/srv/ausmt ./deploy/backup.sh [BACKUPS_DIR]
#     BACKUPS_DIR defaults to $AUSMT_BACKUP_DIR, else $AUSMT_DATA_DIR/backups.
#
# ENV OVERRIDES (all optional; defaults are the production values):
#   AUSMT_BACKUP_DIR       backups root (else $AUSMT_DATA_DIR/backups)
#   AUSMT_BACKUP_RETAIN    snapshots to keep (default 14)
#   AUSMT_BACKUP_SQLITE    the sqlite3 command (default `sqlite3`); a test/CI shim hooks here
#   AUSMT_GATEWAY_IMAGE    gateway image for the docker python-sqlite fallback (host has no sqlite3)
#   AUSMT_BACKUP_NO_DOCKER set to 1 to disable the docker fallback (used to test the hard refusal)
#
# Dependency-light on purpose: POSIX sh, coreutils, and EITHER a host `sqlite3` OR a runnable gateway
# image for the fallback. Read it top to bottom. Run ONE restore drill after installing it
# (deploy/scripts/restore-drill.sh): a backup that has never been restored is a hypothesis, not a
# backup. See deploy/README.md "Backups & restore".

set -eu

# --------------------------------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------------------------------
: "${AUSMT_DATA_DIR:?set AUSMT_DATA_DIR (the host root holding gateway/state/ + site-data/)}"
BACKUPS_DIR="${1:-${AUSMT_BACKUP_DIR:-$AUSMT_DATA_DIR/backups}}"
RETAIN="${AUSMT_BACKUP_RETAIN:-14}"
SQLITE_CMD="${AUSMT_BACKUP_SQLITE:-sqlite3}"

# The gateway image, only for the sqlite fallback when the host has no sqlite3. Matches compose.yaml
# naming; override AUSMT_GATEWAY_IMAGE if your tag differs.
GATEWAY_IMAGE="${AUSMT_GATEWAY_IMAGE:-ghcr.io/${OWNER:-bvkay}/ausmt-gateway:${TAG:-latest}}"

STATE_DIR="$AUSMT_DATA_DIR/gateway/state"
DB="$STATE_DIR/gateway.sqlite"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/ausmt-backup.XXXXXX")"
# Clean the staging dir on any exit (success, error, or signal) — never leave a DB copy in /tmp.
trap 'rm -rf "$WORK"' EXIT INT TERM

log() { printf '%s %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }
die() { printf 'backup: ERROR: %s\n' "$*" >&2; exit 1; }

# --------------------------------------------------------------------------------------------------
# 0. Fail LOUD AND EARLY if the state dir is missing/unreadable (the missing one-time ownership prep).
#    The state dir is uid 10002-owned with the shared group 10002 g+rwX,g+s (README step 0b); the
#    operator is in that group. If we cannot read/list it, the backup cannot proceed — say so with the
#    one actionable next step instead of dribbling scattered errors later (the 2026-07-08 lesson).
# --------------------------------------------------------------------------------------------------
if [ ! -d "$STATE_DIR" ]; then
  die "gateway state dir does not exist: $STATE_DIR
      (unmounted volume? typo in AUSMT_DATA_DIR? portal-only box has no gateway state — nothing to back up.)
      See deploy/README.md \"Backups & restore\"."
fi
if ! ls "$STATE_DIR" >/dev/null 2>&1; then
  die "gateway state dir is not readable by $(id -un 2>/dev/null || echo '?'): $STATE_DIR
      One-time ownership prep is missing — the operator must be in group 10002 with g+rX on the state dir.
      See deploy/README.md \"Backups & restore\" ownership prep (step 0)."
fi

# --------------------------------------------------------------------------------------------------
# 1. Consistent sqlite snapshot (WAL-safe). The gateway may be LIVE while this runs.
# --------------------------------------------------------------------------------------------------
snapshot_sqlite() {
  dest="$1"
  if [ ! -f "$DB" ]; then
    log "no gateway DB at $DB (fresh box before first submission?) — snapshotting state files only."
    return 0
  fi

  # command -v on the FIRST word of SQLITE_CMD: it may be `sqlite3` or a `sh /path/shim.sh` override.
  sqlite_bin=${SQLITE_CMD%% *}
  if command -v "$sqlite_bin" >/dev/null 2>&1; then
    # Preferred: sqlite3's online .backup API takes a transactionally-consistent copy of a live WAL DB.
    log "snapshotting $DB via '$sqlite_bin' .backup"
    # shellcheck disable=SC2086 -- SQLITE_CMD may be a multi-word override (e.g. `sh shim.sh`).
    $SQLITE_CMD "$DB" ".backup '$dest'"
  elif [ "${AUSMT_BACKUP_NO_DOCKER:-0}" != "1" ] && command -v docker >/dev/null 2>&1; then
    # Fallback: no host sqlite3, but the gateway image ships Python (stdlib sqlite3 has the same online
    # backup API). Mount the DB read-only + a writable out-dir, run in-container as uid 10002 (the DB
    # owner) so the read succeeds under the ownership split.
    log "host sqlite3 not found — snapshotting via the gateway image's Python sqlite3 backup API"
    docker run --rm --user 10002:10002 \
      -v "$STATE_DIR:/db:ro" \
      -v "$WORK:/out" \
      --entrypoint python "$GATEWAY_IMAGE" -c \
      'import sqlite3; src=sqlite3.connect("file:/db/gateway.sqlite?mode=ro", uri=True); dst=sqlite3.connect("/out/gateway.sqlite.bak"); src.backup(dst); dst.close(); src.close(); print("ok")'
    mv "$WORK/gateway.sqlite.bak" "$dest"
  else
    die "neither sqlite3 ('$sqlite_bin') nor docker is available for a WAL-safe snapshot — refusing to
      raw-copy a live WAL DB (a raw cp can produce a torn snapshot). Install sqlite3 on the host, or run
      where the gateway image is available. See deploy/README.md \"Backups & restore\" troubleshooting."
  fi
}

# is_secret_name: true (exit 0) if the file name resembles a secret and must NEVER enter a snapshot.
# Belt-and-braces even though .env lives under deploy/ not the state dir: a future stray key file in
# the state dir must not silently ride along into a snapshot the Mac then pulls.
is_secret_name() {
  case "$1" in
    .env|*.env|*.key|*.pem|*.p12|*.pfx|*.pw|id_*|*secret*|*password*|*credential*|*.crt) return 0 ;;
    *) return 1 ;;
  esac
}

# --------------------------------------------------------------------------------------------------
# 2. Stage the snapshot into $WORK/snap, then atomically publish it as backups/<stamp>/.
# --------------------------------------------------------------------------------------------------
SNAP="$WORK/snap"
mkdir -p "$SNAP"

snapshot_sqlite "$SNAP/gateway.sqlite"

# Copy every OTHER top-level file in the state dir EXCEPT the DB (+ its sidecars) and anything secret.
# Directories under state/ are not walked: the only content the gateway keeps there is flat files
# (reconcile-status.json, rebuild.request, uploader-key data lives IN the DB). Skip the sqlite sidecars
# too — the .backup already captured a consistent DB; a stale -wal/-shm alongside it would only confuse
# a restore.
for f in "$STATE_DIR"/* "$STATE_DIR"/.[!.]*; do
  [ -e "$f" ] || continue          # the glob is literal when nothing matches
  [ -f "$f" ] || continue          # files only; no dirs
  name="$(basename "$f")"
  case "$name" in
    gateway.sqlite|gateway.sqlite-wal|gateway.sqlite-shm) continue ;;
  esac
  if is_secret_name "$name"; then
    log "skipping secret-looking state file: $name (never backed up)"
    continue
  fi
  cp "$f" "$SNAP/$name"
done

# The snapshot may contain PII (the DB) — lock it down before publishing it.
chmod 0700 "$SNAP"
[ -f "$SNAP/gateway.sqlite" ] && chmod 0600 "$SNAP/gateway.sqlite"

# --------------------------------------------------------------------------------------------------
# 3. Publish: move the staged snapshot into place, then repoint `latest`.
# --------------------------------------------------------------------------------------------------
mkdir -p "$BACKUPS_DIR"
DEST="$BACKUPS_DIR/$STAMP"
if [ -e "$DEST" ]; then
  # Two runs in the same UTC second (or a re-run) — refuse rather than clobber a prior snapshot.
  die "snapshot target already exists: $DEST (a run this same second?). Refusing to overwrite."
fi
mv "$SNAP" "$DEST"
log "wrote snapshot $DEST"

# `latest` symlink -> newest snapshot. Relative target so the link survives a move of BACKUPS_DIR.
# ln -sfn atomically replaces an existing link. Symlinks may be unavailable on some filesystems; if
# ln fails, fall back to a plain `latest` file recording the name (the pull script reads either).
if ln -sfn "$STAMP" "$BACKUPS_DIR/latest" 2>/dev/null; then
  log "latest -> $STAMP"
else
  printf '%s\n' "$STAMP" > "$BACKUPS_DIR/latest.txt"
  log "symlink unsupported here — wrote latest.txt -> $STAMP"
fi

# --------------------------------------------------------------------------------------------------
# 4. Prune: keep the newest $RETAIN snapshot directories. Names are UTC timestamps, so a lexical sort
#    is chronological. `latest` (a symlink) and latest.txt are not directories, so they are untouched.
# --------------------------------------------------------------------------------------------------
prune() {
  # List snapshot DIRS newest-first by name.
  all="$(find "$BACKUPS_DIR" -mindepth 1 -maxdepth 1 -type d -name '[0-9]*Z' 2>/dev/null | sort -r || true)"
  [ -n "$all" ] || return 0
  n=0
  printf '%s\n' "$all" | while IFS= read -r d; do
    [ -n "$d" ] || continue
    n=$((n + 1))
    if [ "$n" -gt "$RETAIN" ]; then
      log "pruning old snapshot: $(basename "$d")"
      rm -rf "$d"
    fi
  done
}
prune

log "done. Snapshots retained (newest first) in $BACKUPS_DIR:"
find "$BACKUPS_DIR" -mindepth 1 -maxdepth 1 -type d -name '[0-9]*Z' 2>/dev/null | sort -r | head -n "$RETAIN" || true
