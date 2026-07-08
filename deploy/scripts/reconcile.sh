#!/bin/sh
# AusMT serve reconcile agent (C40). POSIX sh — no bashisms, shellcheck-clean. Runs ONE pass and
# exits; a systemd timer (deploy/systemd/ausmt-reconcile.timer) re-invokes it every ~15 min. The
# NCI end-state has a shell-less curator, so "run make rebuild-data by hand" is not an operation the
# responsible person can perform — this closes the published-not-served gap with no human in the loop
# (design C40 §1/§2).
#
# WHAT IT DOES (design §3, in order):
#   1. sync   — git -C surveys-live pull --ff-only. On failure: write status action=sync_failed and
#               exit 0 WITHOUT rebuilding (never build from a state we cannot fast-forward to, §4).
#   2. compare — built = source_commit from site-data/current/build.json; head = short HEAD of
#               surveys-live (matched to the STORED short-hash length by prefix). Missing/unreadable
#               build.json => treat as drift (rebuild), because we cannot prove what is served.
#   3. decide — if head != built OR a rebuild.request file exists: consume rebuild.request FIRST
#               (rm -f, at-most-once per run, §4), then run the rebuild capturing all output to a
#               timestamped log under site-data/logs/ (pruned to newest 20). Else: noop.
#   4. status — write reconcile-status.json ATOMICALLY (tmp+mv) to the gateway state dir so the
#               curator panel can show the last outcome (design §3).
#
# EXIT CODE: 0 on noop / rebuilt / sync_failed (the timer must NOT flap on an operator-visible
# sync divergence or a normal no-op); 1 ONLY on action=failed (a build/verify failure), so a
# monitoring `systemctl status` surfaces a genuinely broken build while a diverged checkout stays a
# quiet, panel-visible state.
#
# LOCK: flock -n on a lock file (default $AUSMT_DATA_DIR/reconcile.lock). If another run holds it,
# exit 0 SILENTLY without touching the status file (two overlapping ticks must not both build, §4;
# the second is a no-op, not an error). On a host without flock(1) the script still runs the pass
# WITHOUT the lock (a WARN to stderr) — the timer's 15-min cadence + the atomic rebuild swap bound
# the worst case to a redundant build, never a corrupt one. NCI note (§6): the timer becomes a
# cron/PBS job of THIS SAME script — the script itself never assumes systemd.
#
# ENV (all documented in deploy/.env.example; the systemd unit's EnvironmentFile provides them):
#   AUSMT_DATA_DIR        (required) host root: site-data/ + surveys-live/ + gateway/state/ live under it
#   AUSMT_CODE_DIR        (required) this repo's checkout — locates deploy/ for `make rebuild-data`
#   AUSMT_RECONCILE_MAKE  (optional) override the rebuild command (test shim); default:
#                                    `make -C $AUSMT_CODE_DIR/deploy rebuild-data`
#   AUSMT_RECONCILE_LOCK  (optional) lock-file path override; default $AUSMT_DATA_DIR/reconcile.lock
#
# FLAGS:
#   --dry-run  print the decision and take NO actions (no request-file consume, no build, no status
#              write); still exit 0. For an operator to see what the next tick would do.

set -u

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --once) : ;;  # implicit — the script always runs exactly one pass; accepted for symmetry
    *) printf 'reconcile: unknown argument: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

# ----- required env ------------------------------------------------------------------------------
: "${AUSMT_DATA_DIR:?set AUSMT_DATA_DIR (host root; see deploy/.env.example)}"
: "${AUSMT_CODE_DIR:?set AUSMT_CODE_DIR (this checkout; locates deploy/ for make)}"

# The data root must PRE-EXIST (mounts + ownership prep): fabricating any of it here would let an
# unmounted volume or a mistyped AUSMT_DATA_DIR produce a phantom tree that sits in quiet
# sync_failed forever, writing status into a directory nobody serves (review L4).
[ -d "$AUSMT_DATA_DIR" ] || { printf 'reconcile: AUSMT_DATA_DIR does not exist: %s (unmounted volume? typo in .env?)\n' "$AUSMT_DATA_DIR" >&2; exit 1; }

SURVEYS_LIVE="$AUSMT_DATA_DIR/surveys-live"
SITE_DATA="$AUSMT_DATA_DIR/site-data"
# build.json lives at the BUILD ROOT (the engine writes `out/build.json`; see build_portal.py C12).
# The /data/build.json URL the panel fetches maps to the SAME file because Caddy's handle_path
# STRIPS the /data prefix (deploy/docker/caddy/Caddyfile) — do NOT re-add a data/ segment here.
# The 2026-07-08 first install had a phantom data/ segment in this path: build.json was never found,
# every tick read as drift, and only missing dir permissions stopped a rebuild-every-15-min loop.
BUILD_JSON="$SITE_DATA/current/build.json"
LOG_DIR="$SITE_DATA/logs"
STATE_DIR="$AUSMT_DATA_DIR/gateway/state"
REQUEST_FILE="$STATE_DIR/rebuild.request"
STATUS_FILE="$STATE_DIR/reconcile-status.json"
LOCK_FILE="${AUSMT_RECONCILE_LOCK:-$AUSMT_DATA_DIR/reconcile.lock}"
MAKE_CMD="${AUSMT_RECONCILE_MAKE:-make -C $AUSMT_CODE_DIR/deploy rebuild-data}"

now_utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# python3 for the two structured reads (build.json parse, JSON-safe status write). Fragile grep
# would misparse a reordered/whitespace-varied JSON; python is on the deploy host (preflight/backup
# already rely on it). PROBE by execution, not just `command -v`: on a Windows dev box `python3` can
# resolve to a non-functional App-Store shim, so we pick the first candidate that actually runs.
PY=""
for _cand in python3 python; do
  if command -v "$_cand" >/dev/null 2>&1 && "$_cand" -c "import sys" >/dev/null 2>&1; then
    PY="$_cand"
    break
  fi
done
[ -n "$PY" ] || { printf 'reconcile: no working python3/python on PATH (needed to parse build.json)\n' >&2; exit 1; }

# Fail LOUD AND EARLY if the status file cannot be written: every non-dry pass ends by reporting its
# outcome, so a pass that cannot report must not half-run. (The 2026-07-08 first install failed
# exactly here — site-data/ is uid-10001-owned and gateway/state/ is 10002-owned, and the runbook
# was missing the one-time ownership prep — but the symptom was three scattered errors mid-pass
# instead of one actionable line.) Probe with the same tmp name pattern the status writer uses.
# mktemp (not a hand-rolled `> file.tmp.$$`): the state dir is DELIBERATELY group-writable to the
# gateway's uid (README step 0b), and a predictable tmp name would let a compromised container
# pre-plant a symlink the redirect follows onto an operator-writable target (review L5). mktemp
# creates O_EXCL with an unpredictable suffix — it can neither follow nor be raced.
if [ "$DRY_RUN" -eq 0 ]; then
  mkdir -p "$STATE_DIR" 2>/dev/null || true
  if ! _probe=$(mktemp "$STATE_DIR/.reconcile-probe.XXXXXX" 2>/dev/null); then
    printf 'reconcile: state dir not writable by %s: %s\n' "$(id -un 2>/dev/null || echo '?')" "$STATE_DIR" >&2
    printf 'reconcile: one-time ownership prep missing — see deploy/README.md "Serve reconcile" step 0\n' >&2
    exit 1
  fi
  rm -f "$_probe"
fi

# read_source_commit: echo the served build's source_commit, or empty if build.json is missing or
# unreadable/malformed (=> the caller treats it as drift). Never fails the script.
read_source_commit() {
  [ -f "$BUILD_JSON" ] || return 0
  "$PY" - "$BUILD_JSON" <<'PYEOF' 2>/dev/null || true
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        doc = json.load(fh)
    sc = doc.get("source_commit")
    if isinstance(sc, str) and sc:
        print(sc)
except Exception:
    pass
PYEOF
}

read_build_id() {
  [ -f "$BUILD_JSON" ] || return 0
  "$PY" - "$BUILD_JSON" <<'PYEOF' 2>/dev/null || true
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        doc = json.load(fh)
    bid = doc.get("build_id")
    if isinstance(bid, str) and bid:
        print(bid)
except Exception:
    pass
PYEOF
}

# write_status <action> <head> <built> <build_id> <log_file>: build reconcile-status.json in a temp
# file then mv it over the target — an atomic rename so the gateway panel never reads a half-written
# file. Values are passed as argv (never interpolated into the JSON) so a stray quote/backslash in a
# path or commit cannot break the document. log_tail is the last ~30 lines of the log on
# rebuilt/failed, else null.
write_status() {
  _action="$1"; _head="$2"; _built="$3"; _build_id="$4"; _log_file="$5"
  mkdir -p "$STATE_DIR"
  # mktemp, same rationale as the probe above (review L5): O_EXCL + unpredictable name in a dir a
  # container uid can also write — never a predictable `.tmp.$$` a symlink could be planted at.
  _tmp=$(mktemp "$STATUS_FILE.tmp.XXXXXX" 2>/dev/null) || {
    printf 'reconcile: cannot create status tmp under %s\n' "$STATE_DIR" >&2; return 1; }
  # mktemp creates 0600 — but the status CONSUMER is the gateway CONTAINER (uid 10002) reading via
  # the shared state dir, so open it up before the rename. Without this the panel shows "no status
  # yet" while the file sits there operator-only (the 2026-07-08 panel regression: the symlink-safe
  # mktemp change silently revoked the group read the old umask-created tmp had). Status content is
  # non-secret operational metadata (actions, commits, log tail).
  chmod 0644 "$_tmp"
  AUSMT_RS_ACTION="$_action" AUSMT_RS_HEAD="$_head" AUSMT_RS_BUILT="$_built" \
  AUSMT_RS_BUILD_ID="$_build_id" AUSMT_RS_LOG_FILE="$_log_file" AUSMT_RS_LAST_RUN="$(now_utc)" \
  "$PY" - > "$_tmp" <<'PYEOF'
import json, os
action = os.environ["AUSMT_RS_ACTION"]
log_file = os.environ.get("AUSMT_RS_LOG_FILE") or None
log_tail = None
if action in ("rebuilt", "failed") and log_file and os.path.isfile(log_file):
    try:
        with open(log_file, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
        log_tail = "\n".join(lines[-30:])
    except Exception:
        log_tail = None
def orval(name):
    v = os.environ.get(name)
    return v if v else None
doc = {
    "last_run": os.environ["AUSMT_RS_LAST_RUN"],
    "action": action,
    "head": orval("AUSMT_RS_HEAD"),
    "built": orval("AUSMT_RS_BUILT"),
    "build_id": orval("AUSMT_RS_BUILD_ID"),
    "log_file": log_file,
    "log_tail": log_tail,
}
print(json.dumps(doc, indent=1))
PYEOF
  mv -f "$_tmp" "$STATUS_FILE"
}

# ----- the one pass, under the lock --------------------------------------------------------------
# All decision logic lives in run_pass so flock can wrap the WHOLE body (sync..status) in a single
# critical section — never two builds at once. The caller below takes the lock on fd 9 and then
# calls run_pass IN-PROCESS while the fd is held (no re-exec); the fd closes on exit, releasing it.
run_pass() {
  # 1. SYNC: fast-forward-only pull. A diverged/blocked checkout must NOT be built from (§4).
  if ! sync_out=$(git -C "$SURVEYS_LIVE" pull --ff-only 2>&1); then
    printf 'reconcile: git pull --ff-only failed (surveys-live diverged?):\n%s\n' "$sync_out" >&2
    head_short=$(git -C "$SURVEYS_LIVE" rev-parse --short HEAD 2>/dev/null || true)
    built_now=$(read_source_commit)
    if [ "$DRY_RUN" -eq 1 ]; then
      printf 'reconcile: [dry-run] would write status action=sync_failed (no rebuild)\n'
      return 0
    fi
    write_status "sync_failed" "$head_short" "$built_now" "" ""
    return 0
  fi

  # 2. COMPARE: built = served source_commit; head = surveys-live short HEAD matched to the STORED
  # short-hash length by prefix (build.json may store --short=7 while a bare rev-parse --short may
  # yield a different width). Missing/empty built => DRIFT (we cannot prove what is served).
  built=$(read_source_commit)
  if [ -n "$built" ]; then
    hash_len=${#built}
    head=$(git -C "$SURVEYS_LIVE" rev-parse --short="$hash_len" HEAD 2>/dev/null || true)
  else
    head=$(git -C "$SURVEYS_LIVE" rev-parse --short HEAD 2>/dev/null || true)
  fi
  # An empty $head must never reach the prefix compare: `"$head"*` with head="" is the pattern `*`,
  # which matches ANY built value — a false noop with a lying status (review L3). Near-unreachable
  # (rev-parse failing right after a successful pull), but refuse loudly rather than guess.
  if [ -z "$head" ]; then
    printf 'reconcile: cannot resolve surveys-live HEAD in %s — refusing to compare or build\n' "$SURVEYS_LIVE" >&2
    if [ "$DRY_RUN" -eq 1 ]; then
      printf 'reconcile: [dry-run] would write status action=failed (unresolvable HEAD)\n'
      return 0
    fi
    write_status "failed" "" "$built" "$(read_build_id)" ""
    return 1
  fi

  request_present=0
  [ -f "$REQUEST_FILE" ] && request_present=1

  # LOOP GUARD (the 2026-07-08 class): an unreadable built-identity reads as drift, and a rebuild
  # SHOULD make build.json readable — so if the LAST pass already rebuilt (or already tripped this
  # guard) at this SAME head and the identity was STILL unreadable afterwards, something structural
  # (a layout or permission mismatch) is eating every rebuild. Do not burn one build per tick
  # forever: fail loudly and hold. Re-armed by any HEAD change or an explicit curator
  # rebuild.request (deliberate human intent always gets a fresh attempt). Side effect, accepted +
  # documented: a FAILED first build on a fresh box (no build.json yet) also holds instead of
  # retrying every 15 min — a deterministic build failure needs an operator, not a retry storm.
  # Known-and-accepted looseness (review L2): a sync_failed tick overwrites the status doc and
  # thereby the latch, so a flaky origin buys ONE extra rebuild attempt per connectivity blip —
  # bounded per-blip, and the status never lies about what happened.
  if [ -z "$built" ] && [ "$request_present" -eq 0 ]; then
    prev_guard=$(AUSMT_RG_STATUS="$STATUS_FILE" AUSMT_RG_HEAD="$head" "$PY" - <<'PYEOF' 2>/dev/null || true
import json, os
try:
    with open(os.environ["AUSMT_RG_STATUS"], encoding="utf-8") as fh:
        doc = json.load(fh)
    head = os.environ.get("AUSMT_RG_HEAD") or ""
    if (head and doc.get("action") in ("rebuilt", "failed")
            and not doc.get("built") and doc.get("head") == head):
        print("hold")
except Exception:
    pass
PYEOF
)
    if [ "$prev_guard" = "hold" ]; then
      printf 'reconcile: build identity STILL unreadable after a rebuild at head=%s — structural mismatch (layout/permissions); holding, NOT rebuilding every tick. Re-arm: fix + request a rebuild, or push a new commit. See README troubleshooting.\n' "$head" >&2
      if [ "$DRY_RUN" -eq 1 ]; then
        printf 'reconcile: [dry-run] loop guard would hold (status action=failed, no rebuild)\n'
        return 0
      fi
      write_status "failed" "$head" "" "" ""
      return 1
    fi
  fi

  drift=0
  # Empty built (no/unreadable build.json) => drift. Else compare by prefix in BOTH directions so a
  # stored 7-char vs a rev-parsed 8-char short of the SAME commit is not a false drift.
  if [ -z "$built" ]; then
    drift=1
  else
    case "$head" in
      "$built"*) : ;;                 # head starts with built (built is a shorter/equal prefix)
      *) case "$built" in
           "$head"*) : ;;             # built starts with head (head is the shorter prefix)
           *) drift=1 ;;
         esac ;;
    esac
  fi

  # 3. DECIDE
  if [ "$drift" -eq 0 ] && [ "$request_present" -eq 0 ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      printf 'reconcile: [dry-run] head=%s built=%s => noop\n' "${head:-?}" "${built:-?}"
      return 0
    fi
    write_status "noop" "$head" "$built" "$(read_build_id)" ""
    printf 'reconcile: up to date (head=%s built=%s) — noop\n' "${head:-?}" "${built:-?}"
    return 0
  fi

  reason="drift (head=$head != built=${built:-<none>})"
  [ "$request_present" -eq 1 ] && reason="rebuild.request present${built:+ (head=$head built=$built)}"
  if [ "$DRY_RUN" -eq 1 ]; then
    printf 'reconcile: [dry-run] %s => would rebuild (consume request, run: %s)\n' "$reason" "$MAKE_CMD"
    return 0
  fi

  # Consume the request file BEFORE building (at-most-once per run, §4): a request written mid-build
  # is picked up on the NEXT tick, never queued into a storm. Content is audit-only and never parsed.
  [ "$request_present" -eq 1 ] && rm -f "$REQUEST_FILE"

  # A rebuild we cannot log is a rebuild we cannot debug from the panel — fail loud BEFORE building
  # (site-data/ is uid-10001-owned; logs/ needs the one-time operator-owned prep, README step 0).
  # Probe WRITABILITY too, not just existence: an existing-but-unwritable logs/ passes `mkdir -p`
  # and would only surface at the build redirect, with make never launched (review L1).
  if ! mkdir -p "$LOG_DIR" 2>/dev/null || ! _lprobe=$(mktemp "$LOG_DIR/.probe.XXXXXX" 2>/dev/null); then
    printf 'reconcile: log dir %s cannot be created or is not writable — one-time ownership prep missing (deploy/README.md "Serve reconcile" step 0)\n' "$LOG_DIR" >&2
    write_status "failed" "$head" "$built" "$(read_build_id)" ""
    return 1
  fi
  rm -f "$_lprobe"
  log_file="$LOG_DIR/$(date -u +%Y%m%dT%H%M%SZ).build.log"
  printf 'reconcile: %s => rebuilding, log: %s\n' "$reason" "$log_file"

  # Run the rebuild, capturing stdout+stderr to the log. The make target is already atomic
  # (build -> verify -> swap current): a failure leaves the OLD build serving (§4). The script runs
  # under `set -u` (not `-e`), so a non-zero make exit does NOT abort — we capture rc and still write
  # a status document either way.
  # shellcheck disable=SC2086 -- MAKE_CMD is an intentional word-split command (default or shim).
  $MAKE_CMD > "$log_file" 2>&1
  rc=$?

  # Prune the log dir to the newest 20 *.build.log (operator forensics; never served — LOG_DIR is a
  # sibling of builds/, outside current/, §3). ls -1t newest-first; delete everything past 20.
  ( cd "$LOG_DIR" 2>/dev/null && ls -1t ./*.build.log 2>/dev/null | tail -n +21 | while IFS= read -r old; do
      rm -f -- "$old"
    done ) || true

  if [ "$rc" -eq 0 ]; then
    # Re-read head + build.json AFTER the swap: source_commit/build_id now reflect the just-built
    # corpus. head is re-derived so the status reports the commit we actually served.
    new_built=$(read_source_commit)
    if [ -n "$new_built" ]; then
      new_head=$(git -C "$SURVEYS_LIVE" rev-parse --short="${#new_built}" HEAD 2>/dev/null || true)
    else
      new_head=$(git -C "$SURVEYS_LIVE" rev-parse --short HEAD 2>/dev/null || true)
    fi
    write_status "rebuilt" "$new_head" "$new_built" "$(read_build_id)" "$log_file"
    printf 'reconcile: rebuild OK (now serving head=%s built=%s)\n' "${new_head:-?}" "${new_built:-?}"
    return 0
  fi

  # Build/verify failed: the atomic swap left the OLD build serving. Report failed + the log tail so
  # the panel shows why WITHOUT the operator needing shell access; the request file is already
  # consumed, so there is no crash-loop (§4). Exit 1 so `systemctl status`/monitoring flags it.
  write_status "failed" "$head" "$built" "$(read_build_id)" "$log_file"
  printf 'reconcile: rebuild FAILED (rc=%s) — old build still serving. Log: %s\n' "$rc" "$log_file" >&2
  return 1
}

# flock the whole pass on fd 9. -n => non-blocking: if the lock is held by a concurrent run, flock
# returns non-zero and we exit 0 immediately and SILENTLY (the status file is left untouched — the
# holding run owns this tick, §4). run_pass runs in THIS shell while fd 9 is held, so the entire
# sync..status critical section is inside the lock; the fd closes on process exit, releasing it.
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE" || { printf 'reconcile: cannot open lock file %s\n' "$LOCK_FILE" >&2; exit 1; }
  if ! flock -n 9; then
    exit 0
  fi
  run_pass
  exit $?
else
  printf 'reconcile: flock(1) not found — running WITHOUT a lock (timer cadence + atomic swap bound the risk)\n' >&2
  run_pass
  exit $?
fi
