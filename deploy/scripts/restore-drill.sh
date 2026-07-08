#!/bin/sh
# AusMT restore drill — the tested half of the backup story. Invariant 10: a backup that has never been
# restored is a hypothesis, not a backup. This proves a snapshot's gateway.sqlite is actually
# restorable WITHOUT touching production: it copies the DB to a scratch temp, opens it with sqlite3,
# and checks the things a real restore depends on.
#
# WHAT IT VERIFIES (each is a hard gate — any failure => loud message + non-zero exit):
#   1. the snapshot's gateway.sqlite exists and is a readable file
#   2. PRAGMA integrity_check == 'ok'         (the DB is not torn/corrupt — the WAL-safe copy worked)
#   3. the uploader_keys table EXISTS         (schema v2 — a restore into a v2 gateway needs it; a v1
#                                              DB would silently lose curator-managed keys)
# ...then PRINTS, for the operator to eyeball:
#   - the full table list
#   - the uploader_keys row count
#   - the newest submission created_utc (proves the audit history is present + queryable)
#
# WHEN TO RUN IT: once, right after installing the backup timer and taking the first backup (README
# "Backups & restore" tells you to). Then periodically — a quarterly drill catches a backup that
# quietly started producing garbage.
#
# USAGE:
#   ./deploy/scripts/restore-drill.sh [SNAPSHOT_DIR]
#     SNAPSHOT_DIR defaults to the `latest` snapshot under $AUSMT_BACKUP_DIR (else
#     $AUSMT_DATA_DIR/backups). Point it at any snapshot dir to drill an older one.
#
# ENV:
#   AUSMT_BACKUP_DIR   backups root (else $AUSMT_DATA_DIR/backups) — used to find `latest`
#   AUSMT_DATA_DIR     host root (used only to derive the default backups dir)
#   AUSMT_BACKUP_SQLITE  the sqlite3 command (default `sqlite3`)
#
# It NEVER writes to production: the DB is copied to a mktemp scratch that is removed on exit.

set -eu

SQLITE_CMD="${AUSMT_BACKUP_SQLITE:-sqlite3}"

die() { printf 'restore-drill: FAIL: %s\n' "$*" >&2; exit 1; }

# ----- locate the snapshot -----------------------------------------------------------------------
SNAPSHOT="${1:-}"
if [ -z "$SNAPSHOT" ]; then
  BACKUPS_DIR="${AUSMT_BACKUP_DIR:-${AUSMT_DATA_DIR:-}/backups}"
  [ -n "${AUSMT_BACKUP_DIR:-}${AUSMT_DATA_DIR:-}" ] || \
    die "no SNAPSHOT_DIR given and neither AUSMT_BACKUP_DIR nor AUSMT_DATA_DIR is set — cannot find 'latest'."
  if [ -L "$BACKUPS_DIR/latest" ]; then
    # Resolve the symlink target (relative -> under BACKUPS_DIR).
    tgt="$(readlink "$BACKUPS_DIR/latest")"
    case "$tgt" in
      /*) SNAPSHOT="$tgt" ;;
      *)  SNAPSHOT="$BACKUPS_DIR/$tgt" ;;
    esac
  elif [ -f "$BACKUPS_DIR/latest.txt" ]; then
    SNAPSHOT="$BACKUPS_DIR/$(cat "$BACKUPS_DIR/latest.txt")"
  else
    die "no 'latest' snapshot under $BACKUPS_DIR (no backup has run yet?). Pass a SNAPSHOT_DIR explicitly."
  fi
fi

[ -d "$SNAPSHOT" ] || die "snapshot dir does not exist: $SNAPSHOT"
DB="$SNAPSHOT/gateway.sqlite"
[ -f "$DB" ] || die "no gateway.sqlite in snapshot: $SNAPSHOT (an empty/portal-only snapshot cannot be restore-drilled)."

sqlite_bin=${SQLITE_CMD%% *}
command -v "$sqlite_bin" >/dev/null 2>&1 || \
  die "sqlite3 ('$sqlite_bin') not found — the drill needs it to run integrity_check. See deploy/README.md \"Backups & restore\" troubleshooting."

# ----- copy to scratch (never touch the snapshot itself) -----------------------------------------
WORK="$(mktemp -d "${TMPDIR:-/tmp}/ausmt-drill.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM
SCRATCH="$WORK/gateway.sqlite"
cp "$DB" "$SCRATCH"

# Tiny sqlite helper: run a query against the scratch DB, print result. `set -e` will abort on a
# non-zero sqlite exit unless we capture it, so callers that must inspect failure capture rc.
q() {
  # shellcheck disable=SC2086 -- SQLITE_CMD may be a multi-word override (e.g. `sh shim.sh`).
  $SQLITE_CMD "$SCRATCH" "$1"
}

printf 'restore-drill: drilling snapshot %s\n' "$SNAPSHOT"
printf 'restore-drill: DB copied to scratch (%s), running checks...\n' "$SCRATCH"

# ----- 1. integrity_check ------------------------------------------------------------------------
# integrity_check prints 'ok' on a clean DB, or one-or-more problem lines otherwise. A corrupt/garbage
# file may make sqlite exit non-zero instead — treat EITHER as failure. Capture rc under set -e.
if ! integ="$(q 'PRAGMA integrity_check;' 2>&1)"; then
  die "integrity_check could not run — the DB is unreadable/malformed:
      $integ
      This snapshot is CORRUPT and would NOT restore. Investigate backup.sh's sqlite path (host
      sqlite3 present? WAL-safe .backup used?). See deploy/README.md \"Backups & restore\"."
fi
if [ "$integ" != "ok" ]; then
  die "integrity_check did NOT return ok:
      $integ
      This snapshot is CORRUPT and would NOT restore. Do not rely on it."
fi
printf 'restore-drill: [ok] integrity_check\n'

# ----- 2. schema v2: uploader_keys table must exist ----------------------------------------------
has_uk="$(q "SELECT name FROM sqlite_master WHERE type='table' AND name='uploader_keys';" 2>/dev/null || true)"
if [ "$has_uk" != "uploader_keys" ]; then
  die "the uploader_keys table is MISSING (schema < v2):
      This DB predates curator-managed uploader keys. Restoring it into a v2 gateway would lose the
      managed keys. Back up from a v2 gateway, or migrate before relying on this snapshot.
      See gateway/db.py (_migrate_v2_uploader_keys) and deploy/README.md \"Backups & restore\"."
fi
printf 'restore-drill: [ok] uploader_keys table present (schema v2)\n'

# ----- 3. eyeball figures ------------------------------------------------------------------------
printf '\nrestore-drill: --- eyeball report (operator, confirm these look sane) ---\n'

printf 'tables:\n'
q ".tables" 2>/dev/null || q "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"

uk_count="$(q 'SELECT COUNT(*) FROM uploader_keys;' 2>/dev/null || echo '?')"
printf 'uploader_keys rows: %s\n' "$uk_count"

# Newest submission created_utc — proves the audit history restored + is queryable. Guarded: an empty
# submissions table (a brand-new box) prints '(none)' rather than failing the drill.
newest="$(q "SELECT COALESCE(MAX(created_utc), '(none)') FROM submissions;" 2>/dev/null || echo '(query failed)')"
printf 'newest submission created_utc: %s\n' "$newest"

printf '\nrestore-drill: PASS — snapshot %s is restorable (integrity ok, schema v2). Eyeball the figures above.\n' "$SNAPSHOT"
