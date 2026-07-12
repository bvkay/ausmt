#!/bin/sh
# AusMT curator-workbench ACTIONS agent (C43 Stage 2b-ii, record D8/D9). POSIX sh — one pass, timer-
# driven (deploy/systemd/ausmt-actions.timer fires it every ~2 min). It is the HOST-SIDE half of the
# privileged-action lane: the gateway (which has NO shell, NO docker socket, NO site-data mount — the
# C40 trust boundary) writes an INTENT FILE into the shared gateway state dir; THIS agent, running as
# the operator uid that owns the code checkout and can drive `docker compose`, scans the state dir and
# executes a FIXED RECIPE for each recognised intent. The gateway can only ASK; the host decides and
# acts. (design C43 D8 "operations floor / actions"; D9 "request-file hardening spec".)
#
# THE D9 HARDENING (frozen — implemented in full here; the gateway-side checks are UX only, THIS is the
# real gate):
#   D9.1 Fixed-enum intents only. A closed allow-list of intent FILENAMES (update/backup/rollback/
#        restore .request). An unknown file in the state dir is IGNORED and audited, never executed.
#   D9.2 Host-side validation is the real gate. The rollback build id is validated against the REAL
#        retained-build inventory (site-data/builds/); the restore snapshot id against the REAL
#        snapshot list (backups/); ids must match a strict [A-Za-z0-9TZ._-] charset AND resolve to an
#        actual inventory entry BEFORE any use. No attacker-controllable string ever reaches a shell:
#        the recipes are fixed command sequences with allow-listed arguments only.
#   D9.3 Single-flight + rate limit. A host-side flock serialises the agent (one action at a time); at
#        most ONE privileged intent is executed per invocation (fixed priority), so two recipes can
#        never run concurrently. A per-kind cooldown refuses (and audits) a repeat request inside the
#        rate-limit window.
#   D9.4 Audit line per action — append-only actions-audit.log in the state dir carrying the intent
#        kind, the id (rollback/restore only), the requesting curator NAME, and the outcome.
#   D9.5 Typed confirmation for restore — the snapshot id the curator typed is carried in the intent
#        and re-checked here against the real snapshot list; a mismatch aborts (audited refused).
#   D9.6 update.request + restore.request are flagged for the pre-NCI hostile re-audit (see README).
#
# THE UPDATE RECIPE IS THE ONE BOUNDED C40 EXCEPTION (record D8, owner-ruled): `git pull --ff-only` on
# the code checkout + `docker compose pull` + `up -d` — the standing refresh recipe, NOTHING
# parameterised from the intent. Trust analysis (record D8): the recipe can only deploy what branch-
# protected main already built and published, i.e. the same bytes an operator deploys by hand. The
# intent's CONTENT is read ONLY for the audit's `by=` field (the requesting curator) — never for a
# command argument (the "update fixed-recipe" pin proves this by construction + a hostile-content pin).
#
# RECIPES (fixed; nothing parameterised except the two validated ids):
#   update    git -C CODE pull --ff-only ; COMPOSE pull ; COMPOSE up -d          (the C40 exception)
#   backup    invoke deploy/backup.sh                                            (existing snapshot)
#   rollback  atomic `current` symlink repoint to the named RETAINED build; write rollback.pin so the
#             reconcile tick does NOT auto-revert while the manual pin stands. NEVER rebuilds.
#   restore   stop gateway -> DRILL the snapshot FIRST (integrity + schema; a failing drill ABORTS with
#             the live DB byte-untouched) -> swap DB -> restart gateway. The whole sequence is audited.
#
# PAUSE is NOT handled here: pause.flag is a FLAG the reconcile agent (reconcile.sh) respects (skip
# auto-rebuild while fresh, auto-expire after 6 h), and whose persistence the alert agent (alert.sh)
# alarms on. This agent never reads it.
#
# ENV (documented in deploy/.env.example; the systemd unit's EnvironmentFile provides them):
#   AUSMT_DATA_DIR         (required) host root: site-data/ + backups/ + gateway/state/ live under it
#   AUSMT_CODE_DIR         (required for update) this repo's checkout — `git pull` + `compose` run here
#   AUSMT_ACTIONS_LOCK     (optional) lock-file path; default $AUSMT_DATA_DIR/actions.lock
#   AUSMT_ACTIONS_COMPOSE  (optional) override `docker compose` (test shim hook)
#   AUSMT_ACTIONS_GIT      (optional) override `git` (test shim hook)
#   AUSMT_ACTIONS_BACKUP   (optional) override the backup script (default $AUSMT_CODE_DIR/deploy/backup.sh)
#   AUSMT_ACTIONS_DRILL    (optional) override the restore-drill (default .../deploy/scripts/restore-drill.sh)
#   AUSMT_ACTIONS_RATELIMIT_S (optional) per-kind cooldown seconds (default 30); 0 disables
#   AUSMT_BACKUP_DIR       (optional) backups root (default $AUSMT_DATA_DIR/backups) — the snapshot list
#
# FLAGS:
#   --dry-run  print the decision and take NO actions (no consume, no recipe, no audit); exit 0.
#
# EXIT CODE: 0 on a clean pass (executed / refused-and-audited / nothing-to-do / lock-held); 1 only on
# a RECIPE that ran and FAILED (so `systemctl status` surfaces a failed update/backup/rollback/restore).

set -u

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --once) : ;;   # implicit — always one pass; accepted for symmetry with reconcile.sh
    *) printf 'actions: unknown argument: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

# ----- required env ------------------------------------------------------------------------------
: "${AUSMT_DATA_DIR:?set AUSMT_DATA_DIR (host root; see deploy/.env.example)}"
[ -d "$AUSMT_DATA_DIR" ] || { printf 'actions: AUSMT_DATA_DIR does not exist: %s (unmounted volume? typo in .env?)\n' "$AUSMT_DATA_DIR" >&2; exit 1; }

CODE_DIR="${AUSMT_CODE_DIR:-}"
STATE_DIR="$AUSMT_DATA_DIR/gateway/state"
SITE_DATA="$AUSMT_DATA_DIR/site-data"
BUILDS_DIR="$SITE_DATA/builds"
CURRENT_LINK="$SITE_DATA/current"
# The live gateway DB. AUSMT_ACTIONS_DB overrides it (default $STATE_DIR/gateway.sqlite) — used by the
# restore-abort test to exercise the staging-failure path (a DB path whose parent is missing makes the
# restore mktemp fail), and harmless in production (leave it unset).
DB="${AUSMT_ACTIONS_DB:-$STATE_DIR/gateway.sqlite}"
BACKUPS_DIR="${AUSMT_BACKUP_DIR:-$AUSMT_DATA_DIR/backups}"

AUDIT_LOG="$STATE_DIR/actions-audit.log"
ROLLBACK_PIN="$STATE_DIR/rollback.pin"
LAST_FILE="$STATE_DIR/.actions-last"          # per-kind last-exec epoch (operator-only; rate limit)
LOCK_FILE="${AUSMT_ACTIONS_LOCK:-$AUSMT_DATA_DIR/actions.lock}"

COMPOSE_CMD="${AUSMT_ACTIONS_COMPOSE:-docker compose}"
GIT_CMD="${AUSMT_ACTIONS_GIT:-git}"
BACKUP_CMD="${AUSMT_ACTIONS_BACKUP:-${CODE_DIR:+$CODE_DIR/deploy/backup.sh}}"
DRILL_CMD="${AUSMT_ACTIONS_DRILL:-${CODE_DIR:+$CODE_DIR/deploy/scripts/restore-drill.sh}}"
RATELIMIT_S="${AUSMT_ACTIONS_RATELIMIT_S:-30}"

# The four privileged intent files (fixed enum, D9.1). Ordered by PRIORITY — the agent executes the
# FIRST pending one per invocation (single-flight, D9.3): a destructive restore before a rollback
# before an update before a backup. rebuild.request + pause.flag are NOT in this set (reconcile owns
# them); any OTHER *.request in the state dir is UNKNOWN => ignored + audited (D9.1).
INTENT_UPDATE="update.request"
INTENT_BACKUP="backup.request"
INTENT_ROLLBACK="rollback.request"
INTENT_RESTORE="restore.request"

now_utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }
now_epoch() { date -u +%s 2>/dev/null || date +%s; }

# compose <args...>: run `docker compose` against THIS deployment's compose file. Uses `-f <file>`
# (NOT `-C <dir>` — compose has no -C flag; that was a real-box breakage the shim masked, S2). `-f`
# also anchors the project directory to the file's parent, so .env loads from deploy/ regardless of
# the CWD (the systemd unit sets WorkingDirectory, but a manual run must work too). No fragile
# `|| bare` fallback — a compose error surfaces honestly.
compose() {
  # shellcheck disable=SC2086 -- COMPOSE_CMD may be multi-word (default `docker compose`/a test shim).
  $COMPOSE_CMD -f "$CODE_DIR/deploy/compose.yaml" "$@"
}

# python3/python for the JSON field reads. Probe by EXECUTION (a Windows dev box can carry a non-
# functional App-Store python3 shim), exactly as reconcile.sh/alert.sh do.
PY=""
for _cand in python3 python; do
  if command -v "$_cand" >/dev/null 2>&1 && "$_cand" -c "import sys" >/dev/null 2>&1; then
    PY="$_cand"; break
  fi
done

# read_field <file> <key>: echo the string value of top-level JSON key, or empty. Never fails the
# script; a malformed/absent file yields "". Used ONLY for audit metadata (requested_by) and the two
# VALIDATED ids (build_id/snapshot_id) — the id is re-validated against the real inventory before use.
read_field() {
  [ -n "$PY" ] || return 0
  [ -f "$1" ] || return 0
  AUSMT_AF_FILE="$1" AUSMT_AF_KEY="$2" "$PY" - <<'PYEOF' 2>/dev/null || true
import json, os
try:
    with open(os.environ["AUSMT_AF_FILE"], encoding="utf-8") as fh:
        doc = json.load(fh)
    v = doc.get(os.environ["AUSMT_AF_KEY"]) if isinstance(doc, dict) else None
    if isinstance(v, str) and v:
        print(v)
except Exception:
    pass
PYEOF
}

# _scrub <value>: return the value stripped of EVERYTHING that could forge an audit line under a
# compromised gateway (D9, S4). `LC_ALL=C tr -dc '[:print:]'` keeps ONLY ASCII printable bytes 0x20-
# 0x7E — dropping all C0/C1 control chars (\n\r\t\v\f) AND every byte of a multibyte UTF-8 sequence,
# so unicode line separators U+2028/U+2029 (which the gateway's splitlines-free reader also ignores)
# cannot survive. Then drop `=` so an attacker-controlled `by`/`id` can never inject a `key=value`
# token (e.g. a forged `outcome=ok`). Capped at 120 chars.
_scrub() {
  printf '%s' "$1" | LC_ALL=C tr -dc '[:print:]' | tr -d '=' | cut -c1-120
}

# audit <kind> <by> <id> <outcome>: append ONE line to the state-dir audit log (D9.4). The
# host-computed `outcome=` is written FIRST so a forged token in the attacker-controlled `by`/`id`
# fields can never PRECEDE the real outcome (defence-in-depth over the _scrub above). We hold the
# flock, and a single short append is atomic on POSIX. The log is group-readable (0644) so the
# gateway container (uid 10002, shared-group state dir) can render the tail (read-only). Never fails.
audit() {
  _kind="$1"; _by=$(_scrub "${2:-unknown}"); _id=$(_scrub "${3:--}"); _outcome="$4"
  [ -n "$_by" ] || _by="unknown"
  [ -n "$_id" ] || _id="-"
  # `outcome` is host-computed (never attacker-controlled), so it is not scrubbed — but strip newlines
  # defensively so a future outcome string can never break the one-line-per-action invariant.
  _outcome=$(printf '%s' "$_outcome" | tr -d '\n\r')
  mkdir -p "$STATE_DIR" 2>/dev/null || true
  printf '%s outcome=%s intent=%s by=%s id=%s\n' "$(now_utc)" "$_outcome" "$_kind" "$_by" "$_id" \
    >> "$AUDIT_LOG" 2>/dev/null || true
  chmod 0644 "$AUDIT_LOG" 2>/dev/null || true
}

# valid_id: 0 (true) iff the id is non-empty, matches the strict [A-Za-z0-9TZ._-] charset (D9.2), and
# is not a path-traversal token. This is a CHARSET pre-filter — the REAL gate is inventory membership
# (in_inventory below), so even a charset pass cannot escape the enumerated builds/backups roots.
valid_id() {
  _v="$1"
  [ -n "$_v" ] || return 1
  case "$_v" in
    .|..|*/*|*'\'*) return 1 ;;                 # no path separators, no dot-dirs
    *[!A-Za-z0-9TZ._-]*) return 1 ;;            # anything outside the allow-listed charset
    *) return 0 ;;
  esac
}

# in_inventory <root> <id>: 0 (true) iff <root>/<id> is a real directory listed under <root>. Enumerates
# the root and matches by EXACT name (never builds a path from the untrusted id and stats it blindly) —
# a hostile id that is not a real inventory entry simply does not match.
in_inventory() {
  _root="$1"; _want="$2"
  [ -d "$_root" ] || return 1
  for _e in "$_root"/*; do
    [ -d "$_e" ] || continue
    [ "$(basename "$_e")" = "$_want" ] && return 0
  done
  return 1
}

# rate_limited <kind>: 0 (true) iff <kind> ran less than RATELIMIT_S seconds ago (D9.3 repeat-request
# refusal). Reads the per-kind last-exec epoch from LAST_FILE ("<kind> <epoch>" lines). RATELIMIT_S=0
# disables. record_ran stamps it after a recipe runs.
rate_limited() {
  [ "${RATELIMIT_S:-0}" -gt 0 ] 2>/dev/null || return 1
  [ -f "$LAST_FILE" ] || return 1
  _prev=$(awk -v k="$1" '$1==k {print $2}' "$LAST_FILE" 2>/dev/null | tail -n 1)
  [ -n "$_prev" ] || return 1
  case "$_prev" in ''|*[!0-9]*) return 1 ;; esac
  _now=$(now_epoch)
  _age=$((_now - _prev))
  [ "$_age" -lt "$RATELIMIT_S" ] 2>/dev/null
}
record_ran() {
  _k="$1"; _now=$(now_epoch)
  mkdir -p "$STATE_DIR" 2>/dev/null || true
  _tmp=$(mktemp "$LAST_FILE.tmp.XXXXXX" 2>/dev/null) || return 0
  # keep other kinds' lines, replace this kind's
  { [ -f "$LAST_FILE" ] && awk -v k="$_k" '$1!=k' "$LAST_FILE"; printf '%s %s\n' "$_k" "$_now"; } \
    > "$_tmp" 2>/dev/null
  mv -f "$_tmp" "$LAST_FILE" 2>/dev/null || rm -f "$_tmp" 2>/dev/null || true
}

# ---- the recipes --------------------------------------------------------------------------------

# recipe_update: THE ONE BOUNDED C40 EXCEPTION (record D8). git pull --ff-only on the code checkout,
# then compose pull + up -d. NOTHING here is derived from the intent — the command sequence is
# constant (the "update fixed-recipe" pin asserts this by construction). Returns the recipe rc.
recipe_update() {
  [ -n "$CODE_DIR" ] || { printf 'actions: update needs AUSMT_CODE_DIR (the code checkout)\n' >&2; return 1; }
  [ -e "$CODE_DIR/.git" ] || { printf 'actions: update: %s is not a git checkout\n' "$CODE_DIR" >&2; return 1; }
  # git DOES take -C (it is a git checkout); compose does NOT — it goes through compose() (`-f`, S2).
  # shellcheck disable=SC2086 -- GIT_CMD may be multi-word (default `git`/a test shim).
  $GIT_CMD -C "$CODE_DIR" pull --ff-only || return 1
  compose pull || return 1
  compose up -d || return 1
  return 0
}

# recipe_backup: invoke the existing on-box snapshot (deploy/backup.sh). Fixed, unparameterised.
recipe_backup() {
  [ -n "$BACKUP_CMD" ] || { printf 'actions: backup needs AUSMT_CODE_DIR (locates deploy/backup.sh)\n' >&2; return 1; }
  # shellcheck disable=SC2086 -- BACKUP_CMD may be a multi-word override (e.g. `sh shim.sh`).
  $BACKUP_CMD
}

# recipe_rollback <build_id>: atomic `current` symlink repoint to a RETAINED build (record D8; the
# "rollback-repoints" pin). NEVER rebuilds — it only moves the pointer. The id is already charset- +
# inventory-validated by the caller. Writes rollback.pin so the reconcile tick does NOT auto-revert
# while the manual pin stands (record D13 rollback-repoints).
recipe_rollback() {
  _bid="$1"; _by="$2"
  _target="$BUILDS_DIR/$_bid"
  [ -d "$_target" ] || { printf 'actions: rollback target vanished: %s\n' "$_target" >&2; return 1; }
  # Atomic swap: create the new link under a temp name in the SAME dir, then rename over `current`
  # (mv -T on a symlink is atomic — the served path never observes a missing `current`). Relative
  # target (builds/<id>) so the link survives a move of site-data, mirroring the reconcile swap.
  _tmp="$CURRENT_LINK.actions.$$"
  rm -f "$_tmp" 2>/dev/null || true
  if ln -sfn "builds/$_bid" "$_tmp" 2>/dev/null && [ -L "$_tmp" ]; then
    mv -T "$_tmp" "$CURRENT_LINK" 2>/dev/null || mv -f "$_tmp" "$CURRENT_LINK" || { rm -f "$_tmp"; return 1; }
  else
    # Filesystem without symlinks (some SMB/MSYS mounts): fall back to a plain redirect file the
    # reconcile/serve code already tolerate — but on the real box `current` is a symlink, so this is
    # defence-in-depth, not the production path.
    rm -f "$_tmp" 2>/dev/null || true
    printf 'actions: rollback could not create a symlink for current -> builds/%s\n' "$_bid" >&2
    return 1
  fi
  # Record the manual pin so reconcile.sh holds (does not auto-rebuild/revert) until an explicit
  # rebuild.request moves forward or the pin is removed.
  _pintmp=$(mktemp "$ROLLBACK_PIN.tmp.XXXXXX" 2>/dev/null) || return 0
  chmod 0644 "$_pintmp" 2>/dev/null || true
  AUSMT_PIN_BUILD="$_bid" AUSMT_PIN_BY="$_by" AUSMT_PIN_AT="$(now_utc)" "$PY" - > "$_pintmp" 2>/dev/null <<'PYEOF'
import json, os
print(json.dumps({"pinned_build": os.environ["AUSMT_PIN_BUILD"],
                  "pinned_by": os.environ.get("AUSMT_PIN_BY") or None,
                  "pinned_at": os.environ["AUSMT_PIN_AT"]}, indent=1))
PYEOF
  if [ -s "$_pintmp" ]; then mv -f "$_pintmp" "$ROLLBACK_PIN" 2>/dev/null || rm -f "$_pintmp"; else rm -f "$_pintmp"; fi
  return 0
}

# recipe_restore <snapshot_id> <by>: the guarded, drill-first DB restore (record D8, owner-ruled). In
# ORDER: stop the gateway container -> DRILL the snapshot FIRST (a failing drill ABORTS with the live
# DB byte-untouched, then the gateway is restarted) -> swap the DB -> restart. Returns 0 on a completed
# swap, 1 on any failure; sets $RESTORE_OUTCOME to a human phrase for the audit line.
RESTORE_OUTCOME=""

# _gateway_start / _gateway_stop: bring the gateway container down/up via compose (`-f`, S2). Best-
# effort — a shim records the call in tests; a real failure to restart is bounded by compose's own
# `restart: unless-stopped`.
_gateway_stop()  { compose --profile gateway stop gateway 2>/dev/null || true; }
_gateway_start() { compose --profile gateway up -d gateway 2>/dev/null || true; }

recipe_restore() {
  _sid="$1"; _by="$2"
  _snap="$BACKUPS_DIR/$_sid"
  _snapdb="$_snap/gateway.sqlite"
  if [ ! -f "$_snapdb" ]; then
    # NOT yet stopped — safe to bail without a restart.
    RESTORE_OUTCOME="refused: snapshot has no gateway.sqlite"
    printf 'actions: restore: snapshot %s has no gateway.sqlite\n' "$_snap" >&2
    return 1
  fi
  # 1. Stop the gateway so nothing writes the live DB during the sequence. From HERE ON the gateway is
  #    DOWN, so EVERY exit path below MUST restart it (S3: the sole ops surface must never be left down,
  #    including on a disk/inode-exhaustion mktemp failure — that was the shipped bug).
  _gateway_stop
  # 2. DRILL FIRST. A failing drill ABORTS — the live DB is never touched (the "drill-fail aborts
  #    untouched" pin: live DB byte-identical after). Restart on the way out.
  # shellcheck disable=SC2086 -- DRILL_CMD may be a multi-word override.
  if ! $DRILL_CMD "$_snap" >/dev/null 2>&1; then
    RESTORE_OUTCOME="refused: drill FAILED — live DB untouched"
    printf 'actions: restore ABORTED — the snapshot failed the restore drill; the live DB was NOT touched.\n' >&2
    _gateway_start
    return 1
  fi
  # 3. Swap the DB atomically: copy the snapshot DB into the DB dir under a temp name, then mv -f over
  #    the live DB. Remove the -wal/-shm sidecars so the restored file is authoritative (a stale sidecar
  #    alongside a swapped DB would confuse SQLite on the next open — backup.sh's own note). ONE restart
  #    (step 4) runs on every post-stop path, so an early failure here can never leave the box stopped.
  _swap_rc=0
  _dbtmp=$(mktemp "$DB.restore.XXXXXX" 2>/dev/null)
  if [ -z "$_dbtmp" ]; then
    RESTORE_OUTCOME="failed: cannot stage restore tmp"; _swap_rc=1
  elif ! cp "$_snapdb" "$_dbtmp" 2>/dev/null; then
    rm -f "$_dbtmp" 2>/dev/null || true
    RESTORE_OUTCOME="failed: could not copy snapshot DB"; _swap_rc=1
  else
    chmod 0600 "$_dbtmp" 2>/dev/null || true
    rm -f "$DB-wal" "$DB-shm" 2>/dev/null || true
    if ! mv -f "$_dbtmp" "$DB" 2>/dev/null; then
      rm -f "$_dbtmp" 2>/dev/null || true
      RESTORE_OUTCOME="failed: could not swap DB"; _swap_rc=1
    fi
  fi
  # 4. Restart the gateway on EVERY post-stop exit (success OR any staging/copy/swap failure). This is
  #    the single restart the "restart in every exit path" invariant requires.
  _gateway_start
  if [ "$_swap_rc" -ne 0 ]; then
    return 1
  fi
  RESTORE_OUTCOME="ok: restored from $_sid"
  return 0
}

# ---- process ONE intent, under the lock ---------------------------------------------------------
# Fixed priority. Consume the intent FIRST (rm — at-most-once, so a failed/hostile recipe never loops),
# validate, execute, audit. Returns the pass exit code (0 clean / 1 recipe-failed).
process_one() {
  # Warn (and audit) any UNKNOWN *.request the gateway should never have written (D9.1) — but do NOT
  # touch pause.flag or rebuild.request (reconcile owns those). Best-effort visibility.
  for _f in "$STATE_DIR"/*.request; do
    [ -f "$_f" ] || continue
    _n=$(basename "$_f")
    case "$_n" in
      "$INTENT_UPDATE"|"$INTENT_BACKUP"|"$INTENT_ROLLBACK"|"$INTENT_RESTORE"|rebuild.request) : ;;
      *) audit "unknown" "-" "$_n" "ignored: not an allow-listed intent"
         printf 'actions: ignoring unknown intent file: %s\n' "$_n" >&2 ;;
    esac
  done

  # ----- RESTORE (highest priority) -----
  if [ -f "$STATE_DIR/$INTENT_RESTORE" ]; then
    _f="$STATE_DIR/$INTENT_RESTORE"
    _by=$(read_field "$_f" requested_by)
    _sid=$(read_field "$_f" snapshot_id)
    if [ "$DRY_RUN" -eq 1 ]; then printf 'actions: [dry-run] would RESTORE snapshot=%s\n' "${_sid:-?}"; return 0; fi
    rm -f "$_f"                                            # consume (at-most-once)
    if rate_limited restore; then audit restore "$_by" "$_sid" "refused: rate-limited"; return 0; fi
    if ! valid_id "$_sid"; then audit restore "$_by" "${_sid:-<empty>}" "refused: invalid snapshot id"; return 0; fi
    if ! in_inventory "$BACKUPS_DIR" "$_sid"; then audit restore "$_by" "$_sid" "refused: snapshot not in inventory"; return 0; fi
    record_ran restore
    if recipe_restore "$_sid" "$_by"; then audit restore "$_by" "$_sid" "${RESTORE_OUTCOME:-ok}"; return 0
    else audit restore "$_by" "$_sid" "${RESTORE_OUTCOME:-failed}"; return 1; fi
  fi

  # ----- ROLLBACK -----
  if [ -f "$STATE_DIR/$INTENT_ROLLBACK" ]; then
    _f="$STATE_DIR/$INTENT_ROLLBACK"
    _by=$(read_field "$_f" requested_by)
    _bid=$(read_field "$_f" build_id)
    if [ "$DRY_RUN" -eq 1 ]; then printf 'actions: [dry-run] would ROLLBACK to build=%s\n' "${_bid:-?}"; return 0; fi
    rm -f "$_f"
    if rate_limited rollback; then audit rollback "$_by" "$_bid" "refused: rate-limited"; return 0; fi
    if ! valid_id "$_bid"; then audit rollback "$_by" "${_bid:-<empty>}" "refused: invalid build id"; return 0; fi
    if ! in_inventory "$BUILDS_DIR" "$_bid"; then audit rollback "$_by" "$_bid" "refused: build id not in retained inventory"; return 0; fi
    record_ran rollback
    if recipe_rollback "$_bid" "$_by"; then audit rollback "$_by" "$_bid" "ok: current -> builds/$_bid (pinned)"; return 0
    else audit rollback "$_by" "$_bid" "failed: could not repoint current"; return 1; fi
  fi

  # ----- UPDATE -----
  if [ -f "$STATE_DIR/$INTENT_UPDATE" ]; then
    _f="$STATE_DIR/$INTENT_UPDATE"
    _by=$(read_field "$_f" requested_by)                  # AUDIT ONLY — never a command argument
    if [ "$DRY_RUN" -eq 1 ]; then printf 'actions: [dry-run] would UPDATE (git pull --ff-only + compose pull + up -d)\n'; return 0; fi
    rm -f "$_f"
    if rate_limited update; then audit update "$_by" "-" "refused: rate-limited"; return 0; fi
    record_ran update
    if recipe_update; then audit update "$_by" "-" "ok: pulled + redeployed"; return 0
    else audit update "$_by" "-" "failed: update recipe returned nonzero"; return 1; fi
  fi

  # ----- BACKUP (lowest priority) -----
  if [ -f "$STATE_DIR/$INTENT_BACKUP" ]; then
    _f="$STATE_DIR/$INTENT_BACKUP"
    _by=$(read_field "$_f" requested_by)
    if [ "$DRY_RUN" -eq 1 ]; then printf 'actions: [dry-run] would BACKUP (deploy/backup.sh)\n'; return 0; fi
    rm -f "$_f"
    if rate_limited backup; then audit backup "$_by" "-" "refused: rate-limited"; return 0; fi
    record_ran backup
    if recipe_backup; then audit backup "$_by" "-" "ok: snapshot taken"; return 0
    else audit backup "$_by" "-" "failed: backup.sh returned nonzero"; return 1; fi
  fi

  # Nothing pending.
  return 0
}

# ----- lock + run --------------------------------------------------------------------------------
# flock the whole pass on fd 9 (single-flight, D9.3): if a concurrent run holds it, exit 0 — the other
# run owns this tick, and NO second recipe starts (two privileged recipes can never run at once). On a
# host without flock(1) the pass runs bare (WARN): the one-privileged-intent-per-invocation structure
# above still guarantees no two recipes run within a single invocation, and the timer cadence bounds
# overlap; the atomic swaps bound the worst case.
if [ "$DRY_RUN" -eq 0 ]; then
  mkdir -p "$STATE_DIR" 2>/dev/null || true
fi
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE" || { printf 'actions: cannot open lock file %s\n' "$LOCK_FILE" >&2; exit 1; }
  if ! flock -n 9; then
    printf 'actions: another actions run is in flight (lock held) — skipping this tick\n' >&2
    exit 0
  fi
  process_one
  exit $?
else
  printf 'actions: flock(1) not found — running WITHOUT a lock (one-intent-per-run + timer cadence bound the risk)\n' >&2
  process_one
  exit $?
fi
