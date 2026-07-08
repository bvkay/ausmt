#!/bin/sh
# AusMT backup — consistent snapshot of the only irreplaceable state on the box.
#
# WHAT THIS BACKS UP (and why only this):
#   - gateway/state/gateway.sqlite  -- the ONLY PII home + the audit trail; the single genuinely
#                                      irreplaceable file. Snapshotted CONSISTENTLY (see below) because
#                                      it runs in WAL mode (gateway/db.py sets PRAGMA journal_mode=WAL),
#                                      so a raw `cp` of a live DB can miss committed transactions still
#                                      in the -wal sidecar. A correct hot backup copies the DB *through
#                                      SQLite*, not through the filesystem.
#   - deploy/.env                    -- the submit/curator secrets once the gateway is configured. Small,
#                                      not regenerable (you'd have to re-issue keys). Mode 0600 in the tar.
#   - surveys-live/                  -- the survey packages the gateway commits into. Reproducible from
#                                      its git remote, but a local copy means a restore does not depend on
#                                      the remote being reachable.
#   - site-data/current/{build.json,build_provenance.json}  -- build METADATA only. The built products
#                                      (portal JSON, bundled EDIs, zips) are REGENERABLE with
#                                      `make rebuild-data`, so they are deliberately NOT archived — only
#                                      the small provenance files that record which source commit + engine
#                                      built the currently-served corpus, so a restore knows what to rebuild.
#
# USAGE:
#   AUSMT_DATA_DIR=/srv/ausmt ./deploy/backup.sh [TARGET_DIR]
#     TARGET_DIR defaults to $AUSMT_BACKUP_DIR, else /srv/ausmt-backups.
#   Optional restic mode: set RESTIC_REPOSITORY (and RESTIC_PASSWORD / restic's own env). When set,
#   the same file set is handed to `restic backup` INSTEAD of tar (restic does its own retention via
#   `forget`, so the tar-side prune is skipped). Without it, plain date-stamped tarballs are written
#   and pruned to 7 daily / 4 weekly.
#
# This script is intentionally simple and dependency-light: POSIX sh, coreutils, tar, and EITHER a
# host `sqlite3` OR a runnable gateway image for the fallback snapshot. No cleverness — read it top to
# bottom. Run one RESTORE DRILL after installing it (see deploy/README.md "Backups & restore"):
# a backup that has never been restored is a hypothesis, not a backup.

set -eu

# --------------------------------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------------------------------
: "${AUSMT_DATA_DIR:?set AUSMT_DATA_DIR (the host root holding site-data/ + surveys-live/ + gateway/)}"
TARGET_DIR="${1:-${AUSMT_BACKUP_DIR:-/srv/ausmt-backups}}"

# The gateway image, only needed for the sqlite fallback path when the host has no sqlite3. Matches
# compose.yaml's naming; override AUSMT_GATEWAY_IMAGE in the environment if your tag differs.
GATEWAY_IMAGE="${AUSMT_GATEWAY_IMAGE:-ghcr.io/${OWNER:-bvkay}/ausmt-gateway:${TAG:-latest}}"

DB="$AUSMT_DATA_DIR/gateway/state/gateway.sqlite"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/ausmt-backup.XXXXXX")"
# Clean the staging dir on any exit (success, error, or signal) — never leave a DB copy in /tmp.
trap 'rm -rf "$WORK"' EXIT INT TERM

log() { printf '%s %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }

# --------------------------------------------------------------------------------------------------
# 1. Consistent sqlite snapshot (WAL-safe). The gateway may be LIVE while this runs.
# --------------------------------------------------------------------------------------------------
snapshot_sqlite() {
  dest="$1"
  if [ ! -f "$DB" ]; then
    log "no gateway DB at $DB (portal-only deploy?) — skipping the sqlite snapshot."
    return 0
  fi

  if command -v sqlite3 >/dev/null 2>&1; then
    # Preferred: sqlite3's online .backup API takes a transactionally-consistent copy of a live WAL DB.
    log "snapshotting $DB via host sqlite3 .backup"
    sqlite3 "$DB" ".backup '$dest'"
  elif command -v docker >/dev/null 2>&1; then
    # Fallback: no host sqlite3, but the gateway image ships Python (stdlib sqlite3 has the same online
    # backup API). Mount the DB read-only + a writable out-dir, and run the backup in-container. Runs as
    # uid 10002 (the DB owner) so the read succeeds under the ownership split.
    log "host sqlite3 not found — snapshotting via the gateway image's Python sqlite3 backup API"
    docker run --rm --user 10002:10002 \
      -v "$AUSMT_DATA_DIR/gateway/state:/db:ro" \
      -v "$WORK:/out" \
      --entrypoint python "$GATEWAY_IMAGE" -c \
      'import sqlite3; src=sqlite3.connect("file:/db/gateway.sqlite?mode=ro", uri=True); dst=sqlite3.connect("/out/gateway.sqlite.bak"); src.backup(dst); dst.close(); src.close(); print("ok")'
    # docker wrote to $WORK/gateway.sqlite.bak; move it to the requested dest name.
    mv "$WORK/gateway.sqlite.bak" "$dest"
  else
    log "ERROR: neither sqlite3 nor docker is available for a WAL-safe snapshot — refusing to raw-copy a live WAL DB."
    return 1
  fi
}

# --------------------------------------------------------------------------------------------------
# 2. Stage the file set into $WORK/payload
# --------------------------------------------------------------------------------------------------
PAYLOAD="$WORK/payload"
mkdir -p "$PAYLOAD/gateway/state" "$PAYLOAD/deploy" "$PAYLOAD/site-data/current"

snapshot_sqlite "$PAYLOAD/gateway/state/gateway.sqlite"

# deploy/.env (secrets). Located relative to this script so it works regardless of CWD.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/.env" ]; then
  cp "$SCRIPT_DIR/.env" "$PAYLOAD/deploy/.env"
  chmod 0600 "$PAYLOAD/deploy/.env"
else
  log "no $SCRIPT_DIR/.env — skipping (portal-only or secrets kept elsewhere)."
fi

# surveys-live (the committed survey packages). Copy the whole tree if present.
if [ -d "$AUSMT_DATA_DIR/surveys-live" ]; then
  cp -a "$AUSMT_DATA_DIR/surveys-live" "$PAYLOAD/surveys-live"
else
  log "no $AUSMT_DATA_DIR/surveys-live — skipping."
fi

# site-data build METADATA only (products are regenerable via make rebuild-data).
for f in build.json build_provenance.json; do
  if [ -f "$AUSMT_DATA_DIR/site-data/current/$f" ]; then
    cp "$AUSMT_DATA_DIR/site-data/current/$f" "$PAYLOAD/site-data/current/$f"
  fi
done

# --------------------------------------------------------------------------------------------------
# 3a. restic mode (if configured) — hand the payload to restic, let restic own retention.
# --------------------------------------------------------------------------------------------------
if [ -n "${RESTIC_REPOSITORY:-}" ]; then
  if ! command -v restic >/dev/null 2>&1; then
    log "ERROR: RESTIC_REPOSITORY is set but restic is not installed."
    exit 1
  fi
  log "restic mode: backing up the payload to $RESTIC_REPOSITORY"
  restic backup --tag ausmt --host "$(hostname)" "$PAYLOAD"
  # Retention, restic-side (mirrors the tar prune policy below).
  log "restic forget: keeping 7 daily / 4 weekly"
  restic forget --tag ausmt --keep-daily 7 --keep-weekly 4 --prune
  log "restic backup complete."
  exit 0
fi

# --------------------------------------------------------------------------------------------------
# 3b. plain tar mode (default) — date-stamped tarball into TARGET_DIR.
# --------------------------------------------------------------------------------------------------
mkdir -p "$TARGET_DIR"
ARCHIVE="$TARGET_DIR/ausmt-backup-$STAMP.tar.gz"
log "writing $ARCHIVE"
# -C so paths inside the tar are relative (payload/... ), not absolute /tmp paths.
tar -czf "$ARCHIVE" -C "$WORK" payload
chmod 0600 "$ARCHIVE"   # it contains the sqlite PII DB + .env secrets
log "backup complete: $ARCHIVE"

# --------------------------------------------------------------------------------------------------
# 4. Retention prune: keep 7 daily + 4 weekly (tar mode only).
#    Simple + readable: keep the 7 newest by date, plus the newest archive from each of the last 4
#    ISO weeks. Everything else is removed. Filenames are ausmt-backup-YYYYmmddTHHMMSSZ.tar.gz, so a
#    lexical sort is a chronological sort.
# --------------------------------------------------------------------------------------------------
prune() {
  # List archives newest-first.
  all="$(ls -1 "$TARGET_DIR"/ausmt-backup-*.tar.gz 2>/dev/null | sort -r || true)"
  [ -n "$all" ] || return 0

  keep="$WORK/keep.txt"
  : > "$keep"

  # 7 most recent (daily).
  printf '%s\n' "$all" | head -n 7 >> "$keep"

  # Newest archive per ISO year-week, for the 4 most recent distinct weeks (weekly).
  seen_weeks=""
  weeks_kept=0
  for a in $all; do
    [ "$weeks_kept" -ge 4 ] && break
    # Extract the YYYYmmdd date from the filename and map to ISO year-week.
    base="$(basename "$a")"
    datepart="$(printf '%s' "$base" | sed -n 's/^ausmt-backup-\([0-9]\{8\}\)T.*$/\1/p')"
    [ -n "$datepart" ] || continue
    yw="$(date -u -d "$datepart" +%G-%V 2>/dev/null || echo "")"
    [ -n "$yw" ] || continue
    case " $seen_weeks " in
      *" $yw "*) : ;;                       # already kept this week's newest
      *) echo "$a" >> "$keep"; seen_weeks="$seen_weeks $yw"; weeks_kept=$((weeks_kept + 1)) ;;
    esac
  done

  # Remove any archive not in the keep list.
  for a in $all; do
    if ! grep -Fxq "$a" "$keep"; then
      log "pruning old backup: $(basename "$a")"
      rm -f "$a"
    fi
  done
}
prune

log "done. Retained backups in $TARGET_DIR:"
ls -1t "$TARGET_DIR"/ausmt-backup-*.tar.gz 2>/dev/null || true
