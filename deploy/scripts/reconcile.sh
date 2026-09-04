#!/bin/sh
# AusMT serve reconcile agent. POSIX sh - no bashisms, shellcheck-clean. Runs ONE pass and
# exits; a systemd timer (deploy/systemd/ausmt-reconcile.timer) re-invokes it every ~15 min. The
# NCI end-state has a shell-less curator, so "run make rebuild-data by hand" is not an operation the
# responsible person can perform — this closes the published-not-served gap with no human in the loop
# (design).
#
# WHAT IT DOES (in order):
#   1. sync   — git -C surveys-live pull --ff-only. On failure: write status action=sync_failed and
#               exit 0 WITHOUT rebuilding (never build from a state we cannot fast-forward to).
#   1b. untracked-guard — if surveys-live has UNTRACKED entries under surveys/ (a leftover survey dir
#               the build would enumerate and SERVE, but git can never remove):
#               write status action=untracked_blocked naming the dirs, exit 1, DO NOT rebuild.
#   2. compare — built = source_commit from site-data/current/build.json; head = short HEAD of
#               surveys-live (matched to the STORED short-hash length by prefix). Missing/unreadable
#               build.json => treat as drift (rebuild), because we cannot prove what is served.
#   3. decide — if head != built OR a rebuild.request file exists: consume rebuild.request FIRST
#               (rm -f, at-most-once per run), then run the rebuild capturing all output to a
#               timestamped log under site-data/logs/ (pruned to newest 20). Else: noop.
#   4. status — write reconcile-status.json ATOMICALLY (tmp+mv) to the gateway state dir so the
#               curator panel can show the last outcome.
#
# EXIT CODE: 0 on noop / rebuilt / sync_failed (the timer must NOT flap on an operator-visible
# sync divergence or a normal no-op); 1 on action=failed (a build/verify failure) AND on
# action=untracked_blocked (a refused rebuild — both need an operator, neither self-heals), so a
# monitoring `systemctl status` surfaces them while a diverged checkout stays a quiet, panel-visible
# state.
#
# LOCK: flock -n on a lock file (default $AUSMT_DATA_DIR/reconcile.lock). If another run holds it,
# exit 0 SILENTLY without touching the status file (two overlapping ticks must not both build,;
# the second is a no-op, not an error). On a host without flock(1) the script still runs the pass
# WITHOUT the lock (a WARN to stderr) — the timer's 15-min cadence + the atomic rebuild swap bound
# the worst case to a redundant build, never a corrupt one. NCI note: the timer becomes a
# cron/PBS job of THIS SAME script — the script itself never assumes systemd.
#
# ENV (all documented in deploy/.env.example; the systemd unit's EnvironmentFile provides them):
#   AUSMT_DATA_DIR        (required) host root: site-data/ + surveys-live/ + gateway/state/ live under it
#   AUSMT_CODE_DIR        (required) this repo's checkout — locates deploy/ for `make rebuild-data`
#   AUSMT_RECONCILE_MAKE  (optional) override the rebuild command (test shim); default:
#                                    `make -C $AUSMT_CODE_DIR/deploy rebuild-data`
#   AUSMT_RECONCILE_LOCK  (optional) lock-file path override; default $AUSMT_DATA_DIR/reconcile.lock
#   AUSMT_RECONCILE_JOURNALCTL (optional) the journalctl command that asks the KERNEL journal whether
#                                    a failed rebuild was OOM-killed (test shim); default `journalctl`
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
# sync_failed forever, writing status into a directory nobody serves.
[ -d "$AUSMT_DATA_DIR" ] || { printf 'reconcile: AUSMT_DATA_DIR does not exist: %s (unmounted volume? typo in .env?)\n' "$AUSMT_DATA_DIR" >&2; exit 1; }

SURVEYS_LIVE="$AUSMT_DATA_DIR/surveys-live"
SITE_DATA="$AUSMT_DATA_DIR/site-data"
# build.json lives at the BUILD ROOT (the engine writes `out/build.json`; see build_portal.py).
# The /data/build.json URL the panel fetches maps to the SAME file because Caddy's handle_path
# STRIPS the /data prefix (deploy/docker/caddy/Caddyfile), so a data/ segment must NOT appear here.
# A phantom data/ segment in this path means build.json is never found,
# every tick reads as drift, and only missing dir permissions stop a rebuild-every-15-min loop.
BUILD_JSON="$SITE_DATA/current/build.json"
LOG_DIR="$SITE_DATA/logs"
STATE_DIR="$AUSMT_DATA_DIR/gateway/state"
REQUEST_FILE="$STATE_DIR/rebuild.request"
STATUS_FILE="$STATE_DIR/reconcile-status.json"
LOCK_FILE="${AUSMT_RECONCILE_LOCK:-$AUSMT_DATA_DIR/reconcile.lock}"
MAKE_CMD="${AUSMT_RECONCILE_MAKE:-make -C $AUSMT_CODE_DIR/deploy rebuild-data}"
JOURNALCTL="${AUSMT_RECONCILE_JOURNALCTL:-journalctl}"
# The curator "pause auto-rebuild" flag + the "serve this build"
# rollback pin: both host-written by the actions agent (deploy/scripts/actions.sh) / the gateway, and
# RESPECTED here (this agent never writes them). A FRESH pause.flag suppresses the drift rebuild; a
# pause older than PAUSE_EXPIRY_MIN is IGNORED (auto-expired — a stale flag never freezes serving
# forever, pause-expiry). rollback.pin holds reconcile off an auto-revert of a manual rollback
# until an explicit rebuild.request moves forward (rollback-repoints).
PAUSE_FLAG="$STATE_DIR/pause.flag"
ROLLBACK_PIN="$STATE_DIR/rollback.pin"
PAUSE_EXPIRY_MIN="${AUSMT_RECONCILE_PAUSE_EXPIRY_MIN:-360}"   # 6 h
BUILDS_DIR="$SITE_DATA/builds"
# How many build dirs to keep besides the one `current` points at. Matches the Makefile's own
# `ls -1t | tail -n +6` retention so the two cannot drift into different answers.
KEEP_BUILDS="${AUSMT_RECONCILE_KEEP_BUILDS:-5}"

now_utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# prune_builds: drop stale build dirs, ON ENTRY to every pass.
#
# WHY ON ENTRY. The Makefile prunes inside its SWAP step, which only runs after build AND verify both
# succeed. A rebuild that never finishes therefore leaves its half-written builds/<ts> behind forever.
# Observed live: TimeoutStartSec killing the rebuild at 60 minutes, once an hour, leaves each
# killed attempt's ~0.5 GB of partial products (bundled EDIs + per-station MTH5) with nothing to
# collect them. A run of failures must not become a disk leak, so the cleanup runs where it is reachable
# whatever the outcome — not only on the happy path.
#
# SAFETY. The build `current` points at is skipped UNCONDITIONALLY, before any retention arithmetic,
# so this can never delete what is being served. Newest-first, keep KEEP_BUILDS, drop the rest.
#
# IDENTIFYING THE SERVED BUILD is deliberately NOT just `readlink current`. In production `current` is
# a symlink (the Makefile's swap step makes one), but a layout where it is a plain directory — a test
# fixture, a hand-repaired box, a filesystem without symlinks — would leave readlink empty and every
# candidate unprotected, which is precisely the wrong way for this to fail. So: readlink first (cheap,
# exact), then fall back to matching build.json byte-for-byte against each candidate, and if NEITHER
# resolves, prune NOTHING and say so. Keeping stale dirs is recoverable; deleting the live build is not.
prune_builds() {
  [ -d "$BUILDS_DIR" ] || return 0
  # readlink gives e.g. "builds/20260810T010541Z"; keep only the final segment.
  _cur=$(readlink "$SITE_DATA/current" 2>/dev/null || true)
  _cur=${_cur##*/}
  if [ -z "$_cur" ] && [ -f "$BUILD_JSON" ]; then
    for _c in "$BUILDS_DIR"/*; do
      [ -d "$_c" ] && [ -f "$_c/build.json" ] || continue
      if cmp -s "$BUILD_JSON" "$_c/build.json"; then _cur=${_c##*/}; break; fi
    done
  fi
  if [ -z "$_cur" ]; then
    printf 'reconcile: cannot identify the served build (current is neither a resolvable symlink nor '
    printf 'matched by build.json) — skipping the build prune rather than risk deleting it\n'
    return 0
  fi
  ls -1t "$BUILDS_DIR" 2>/dev/null | { _n=0; while IFS= read -r _b; do
    [ -n "$_b" ] && [ -d "$BUILDS_DIR/$_b" ] || continue
    if [ -n "$_cur" ] && [ "$_b" = "$_cur" ]; then continue; fi   # never the served build
    _n=$((_n + 1))
    [ "$_n" -le "$KEEP_BUILDS" ] && continue
    printf 'reconcile: pruning stale build %s\n' "$_b"
    rm -rf -- "$BUILDS_DIR/$_b"
  done; }
}

# The signal trap. systemd's TimeoutStartSec SIGTERMs a rebuild that overruns, and the
# script had no handler: it died mid-build WITHOUT writing reconcile-status.json. Two consequences,
# both observed live — the curator panel kept showing the last CLEAN outcome while hours of rebuilds
# were failing, and the loop guard (which arms off a WRITTEN action=failed) never armed, so the timer
# retried every hour indefinitely. Recording the termination is what makes both self-correcting.
# TRAP_* carry what run_pass knows at the moment of the kill; they stay empty until it knows it.
TRAP_HEAD=""; TRAP_BUILT=""; TRAP_LOG=""
on_signal() {
  _sig="$1"
  printf 'reconcile: SIG%s received — recording action=failed before exit\n' "$_sig" >&2
  if [ "${DRY_RUN:-0}" -eq 0 ]; then
    _t=""
    [ -n "$TRAP_LOG" ] && [ -f "$TRAP_LOG" ] && _t=$(tail -n 25 "$TRAP_LOG" 2>/dev/null || true)
    write_status "failed" "$TRAP_HEAD" "$TRAP_BUILT" "$(read_build_id)" "$TRAP_LOG" \
"TERMINATED by SIG$_sig before the rebuild finished. The previous build is still being served.
If this repeats every run at the same interval, the rebuild needs longer than TimeoutStartSec in
ausmt-reconcile.service (a cold-cache rebuild of the full corpus has been measured at ~93 minutes).
--- last lines of ${TRAP_LOG:-<no log>} ---
$_t"
  fi
  exit 143    # 128 + SIGTERM, the conventional shell encoding of "killed by signal"
}
trap 'on_signal TERM' TERM
trap 'on_signal INT' INT
trap 'on_signal HUP' HUP

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
# outcome, so a pass that cannot report must not half-run. (A first install fails
# exactly here when the one-time ownership prep is skipped: site-data/ is uid-10001-owned and
# gateway/state/ is 10002-owned, and the symptom is three scattered errors mid-pass
# instead of one actionable line.) Probe with the same tmp name pattern the status writer uses.
# mktemp (not a hand-rolled `> file.tmp.$$`): the state dir is DELIBERATELY group-writable to the
# gateway's uid (README step 0b), and a predictable tmp name would let a compromised container
# pre-plant a symlink the redirect follows onto an operator-writable target. mktemp
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

# Force-full-rebuild: echo "1" iff rebuild.request carries a truthy `full` flag (the ONLY
# field reconcile ever parses from the request; the rest stays audit-only, existence-keyed). A full
# rebuild runs the engine in cache-REFRESH mode (recompute everything, no cache reuse). A missing/
# malformed request or a false flag => empty (=> default cache-rw). Never fails the script.
read_full_flag() {
  [ -f "$REQUEST_FILE" ] || return 0
  "$PY" - "$REQUEST_FILE" <<'PYEOF' 2>/dev/null || true
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        doc = json.load(fh)
    if isinstance(doc, dict) and doc.get("full") is True:
        print("1")
except Exception:
    pass
PYEOF
}

# oom_kills_since <since>: set OOM_KILLS to the kernel's out-of-memory KILL lines logged since <since>
# (a journalctl --since expression), oldest first, at most the last 5; empty when there were none. Never
# fails the script. ALSO sets OOM_JOURNAL_UNREADABLE: empty when the kernel journal was actually READ (so
# an empty answer is a real negative), else a one-line reason it was not, so the caller can say "an OOM
# kill cannot be excluded" instead of silently reporting a plain failure over an unread journal. Both
# are globals (not echoed) because a $(...) caller would run this in a subshell and lose the second one.
#
# WHY (incident, P350): the engine build was OOM-killed by the kernel five nights running
# ("Out of memory: Killed process 398616 (python) ... anon-rss:13740244kB ... UID:10001") and every one
# of them reached the operator as "rebuild FAILED (rc=2), see log tail". The log tail ends mid-survey
# with no error at all, because the process was killed, not failed: the truth was two layers down, in
# `journalctl -k`, and nobody looked there for a week. The kernel line names the process (python), the
# uid (10001, the engine container's user), and the size it had reached; that is the sentence that
# tells an operator what to do (more RAM or swap, or a corpus the engine can build in the RAM it has),
# so a failed rebuild now asks the kernel journal for its own build window and SAYS SO by name.
# `-k` is the kernel ring; `-o short-iso` gives an unambiguous UTC-able timestamp per line. Both the
# modern "Out of memory: Killed process" and the older "Out of memory: Kill process" wordings match, as
# does a docker memory-limit "Memory cgroup out of memory: Killed process".
#
# UNREADABLE is not only a non-zero exit. On modern systemd a user outside systemd-journal/adm whose OWN
# user journal is readable gets exit 0 and an EMPTY kernel view, with only a stderr hint ("You are
# currently not seeing messages from other users and the system ... Pass -q to turn off this notice");
# with -q that hint is gone too and the unread journal is indistinguishable from a quiet kernel. So: no
# -q, stderr is kept, and the hint (or "insufficient permissions" / "No journal files were found") means
# unreadable. A kill line that IS present wins over the hint (a partly readable journal that shows the
# kill is a positive answer).
OOM_KILLS=""
OOM_JOURNAL_UNREADABLE=""
oom_kills_since() {
  OOM_KILLS=""
  OOM_JOURNAL_UNREADABLE=""
  if ! command -v "$JOURNALCTL" >/dev/null 2>&1; then
    OOM_JOURNAL_UNREADABLE="no journalctl on this host"
    return 0
  fi
  _jout=$("$JOURNALCTL" -k --since "$1" --no-pager -o short-iso 2>&1)
  _jrc=$?
  OOM_KILLS=$(printf '%s\n' "$_jout" | grep -E 'ut of memory: Kill(ed)? process' | tail -n 5)
  if [ -n "$OOM_KILLS" ]; then
    return 0
  fi
  if [ "$_jrc" -ne 0 ]; then
    OOM_JOURNAL_UNREADABLE="journalctl -k exited $_jrc: $(printf '%s' "$_jout" | grep -v '^$' | head -n 2 | tr '\n' ' ')"
  elif printf '%s\n' "$_jout" | grep -qiE 'not seeing messages from|insufficient permissions|No journal files were found|Permission denied'; then
    OOM_JOURNAL_UNREADABLE="journalctl -k: $(printf '%s' "$_jout" | grep -iE 'not seeing messages from|insufficient permissions|No journal files were found|Permission denied' | head -n 1)"
  fi
  return 0
}

# write_status <action> <head> <built> <build_id> <log_file> [detail]: build reconcile-status.json in
# a temp file then mv it over the target — an atomic rename so the gateway panel never reads a
# half-written file. Values are passed as argv (never interpolated into the JSON) so a stray
# quote/backslash in a path or commit cannot break the document. log_tail is the last ~30 lines of the
# log on rebuilt/failed, else null — UNLESS the optional 6th arg `detail` is given, in which case it is
# used as log_tail verbatim (the untracked-dir refusal below has no build log; its offending-dir list
# IS the detail the panel/ops-floor should show).
write_status() {
  _action="$1"; _head="$2"; _built="$3"; _build_id="$4"; _log_file="$5"; _detail="${6:-}"
  mkdir -p "$STATE_DIR"
  # mktemp, same rationale as the probe above: O_EXCL + unpredictable name in a dir a
  # container uid can also write — never a predictable `.tmp.$$` a symlink could be planted at.
  _tmp=$(mktemp "$STATUS_FILE.tmp.XXXXXX" 2>/dev/null) || {
    printf 'reconcile: cannot create status tmp under %s\n' "$STATE_DIR" >&2; return 1; }
  # mktemp creates 0600 — but the status CONSUMER is the gateway CONTAINER (uid 10002) reading via
  # the shared state dir, so open it up before the rename. Without this the panel shows "no status
  # yet" while the file sits there operator-only (the panel regression: the symlink-safe
  # mktemp change silently revoked the group read the old umask-created tmp had). Status content is
  # non-secret operational metadata (actions, commits, log tail).
  chmod 0644 "$_tmp" || { printf 'reconcile: cannot chmod status tmp %s\n' "$_tmp" >&2; rm -f "$_tmp"; return 1; }
  AUSMT_RS_ACTION="$_action" AUSMT_RS_HEAD="$_head" AUSMT_RS_BUILT="$_built" \
  AUSMT_RS_BUILD_ID="$_build_id" AUSMT_RS_LOG_FILE="$_log_file" AUSMT_RS_DETAIL="$_detail" \
  AUSMT_RS_LAST_RUN="$(now_utc)" \
  AUSMT_RS_PAUSED="${PAUSED:-0}" AUSMT_RS_PAUSE_EXPIRED="${PAUSE_EXPIRED:-0}" \
  AUSMT_RS_PAUSE_SINCE="${PAUSE_SINCE:-}" \
  AUSMT_RS_PINNED="${PINNED:-0}" AUSMT_RS_PINNED_BUILD="${PINNED_BUILD:-}" \
  AUSMT_RS_OOM_KILL="${OOM_KILL:-0}" \
  "$PY" - > "$_tmp" <<'PYEOF'
import json, os
action = os.environ["AUSMT_RS_ACTION"]
log_file = os.environ.get("AUSMT_RS_LOG_FILE") or None
detail = os.environ.get("AUSMT_RS_DETAIL") or ""
log_tail = None
if detail:
    # A caller-supplied detail (the untracked-dir refusal) IS the log_tail — there is no build log.
    log_tail = detail
elif action in ("rebuilt", "failed") and log_file and os.path.isfile(log_file):
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
    # Pause and rollback-pin state, exposed on EVERY status write: the
    # reconcile status must surface pause state so an authenticated attacker cannot silently keep
    # serving frozen. paused == a FRESH pause.flag suppressing the drift rebuild; pause_expired ==
    # a stale flag that was IGNORED; pinned == a manual "serve this build" rollback pin standing.
    "paused": os.environ.get("AUSMT_RS_PAUSED") == "1",
    "pause_expired": os.environ.get("AUSMT_RS_PAUSE_EXPIRED") == "1",
    "pause_since": orval("AUSMT_RS_PAUSE_SINCE"),
    "pinned": os.environ.get("AUSMT_RS_PINNED") == "1",
    "pinned_build": orval("AUSMT_RS_PINNED_BUILD"),
    # True when a FAILED rebuild coincided with a kernel out-of-memory kill in its own build window
    # (oom_kills_since); the kernel lines themselves lead log_tail. False on every other outcome, so
    # a consumer (alert.sh, the ops floor) can name the cause without parsing prose.
    "oom_kill": os.environ.get("AUSMT_RS_OOM_KILL") == "1",
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
  # 0a. Collect stale build dirs FIRST, so the cleanup happens on every pass — including a pass that
  #     goes on to noop, fail, or be killed. See prune_builds for why this cannot live only after a
  #     successful swap. Cheap (a readlink, a listing) and never touches the served build.
  [ "$DRY_RUN" -eq 0 ] && prune_builds
  # 0. PAUSE + ROLLBACK-PIN state. Computed FIRST so EVERY status write below surfaces
  #    it (an authenticated attacker must not be able to keep serving frozen silently). PAUSED == a
  #    pause.flag within its expiry window (honoured); PAUSE_EXPIRED == a stale flag that is IGNORED
  # (auto-expired); PINNED == a manual "serve this build" rollback pin standing.
  PAUSED=0; PAUSE_EXPIRED=0; PAUSE_SINCE=""
  if [ -f "$PAUSE_FLAG" ]; then
    if [ -n "$(find "$PAUSE_FLAG" -maxdepth 0 -mmin "+$PAUSE_EXPIRY_MIN" 2>/dev/null)" ]; then
      PAUSE_EXPIRED=1                      # older than the expiry => auto-expired => IGNORED
    else
      PAUSED=1                             # within the expiry => honoured (suppress drift rebuild)
    fi
    PAUSE_SINCE=$(AUSMT_PF="$PAUSE_FLAG" "$PY" - <<'PYEOF' 2>/dev/null || true
import json, os
try:
    with open(os.environ["AUSMT_PF"], encoding="utf-8") as fh:
        d = json.load(fh)
    v = d.get("paused_at") if isinstance(d, dict) else None
    if isinstance(v, str) and v:
        print(v)
except Exception:
    pass
PYEOF
)
  fi
  PINNED=0; PINNED_BUILD=""
  if [ -f "$ROLLBACK_PIN" ]; then
    PINNED=1
    PINNED_BUILD=$(AUSMT_RP="$ROLLBACK_PIN" "$PY" - <<'PYEOF' 2>/dev/null || true
import json, os
try:
    with open(os.environ["AUSMT_RP"], encoding="utf-8") as fh:
        d = json.load(fh)
    v = d.get("pinned_build") if isinstance(d, dict) else None
    if isinstance(v, str) and v:
        print(v)
except Exception:
    pass
PYEOF
)
  fi

  # 1. SYNC: fast-forward-only pull. A diverged/blocked checkout must NOT be built from.
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

  # 1b. UNTRACKED-SURVEY-DIR GUARD (incident). The engine build enumerates the FILESYSTEM
  # under surveys-live/surveys/ (Makefile rebuild-data passes --surveys …/surveys/surveys), NOT git —
  # so a leftover UNTRACKED survey dir (a `test-2026` left on the box) is SERVED even though `git rm`/
  # pushes can never remove what was never tracked, and the drift compare below reads "current"
  # honestly-but-misleadingly. REFUSE to rebuild while such dirs exist: a rebuild would bake the
  # untracked content into the served corpus. This check lives DEPLOY-side, where git context exists —
  # the engine stays git-unaware by design. `git -C surveys-live status --porcelain` is the operator-
  # context idiom already used above (reconcile runs as the operator, not sudo); `?? ` lines are
  # untracked entries and --untracked-files=normal collapses an untracked dir to one entry. Scope to
  # the survey tree the build actually reads (surveys/). The original sin was SILENCE — this fails LOUD:
  # action=untracked_blocked (a distinct, panel-visible refusal state naming the dirs), exit 1 so
  # `systemctl status` flags it, and the alert timer's reconcile check fail-pings the curator.
  if [ -d "$SURVEYS_LIVE/surveys" ]; then
    untracked=$(git -C "$SURVEYS_LIVE" status --porcelain --untracked-files=normal -- surveys/ 2>/dev/null \
                  | sed -n 's/^?? //p')
    if [ -n "$untracked" ]; then
      offenders=$(printf '%s' "$untracked" | tr '\n' ' ' | sed 's/  */ /g; s/^ //; s/ $//')
      printf 'reconcile: REFUSING rebuild — surveys-live has UNTRACKED entr(y/ies) under surveys/: %s\n' "$offenders" >&2
      printf 'reconcile: the build enumerates the FILESYSTEM, so these WOULD be served though git cannot remove them. Remove (rm -rf) or commit+push them, then the next tick rebuilds.\n' >&2
      if [ "$DRY_RUN" -eq 1 ]; then
        printf 'reconcile: [dry-run] would write status action=untracked_blocked (no rebuild)\n'
        return 0
      fi
      head_short=$(git -C "$SURVEYS_LIVE" rev-parse --short HEAD 2>/dev/null || true)
      built_now=$(read_source_commit)
      _detail="REFUSED: untracked entr(y/ies) under surveys/ - the build enumerates the filesystem, so these would be SERVED though git cannot remove them: $offenders. Remove (rm -rf) or commit+push them, then the next tick rebuilds."
      write_status "untracked_blocked" "$head_short" "$built_now" "$(read_build_id)" "" "$_detail"
      return 1
    fi
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
  # which matches ANY built value - a false noop with a lying status. Near-unreachable
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
  full_rebuild=0
  if [ -f "$REQUEST_FILE" ]; then
    request_present=1
    [ "$(read_full_flag)" = "1" ] && full_rebuild=1     # the force-full-rebuild flag
  fi

  # LOOP GUARD (the class): an unreadable built-identity reads as drift, and a rebuild
  # SHOULD make build.json readable — so if the LAST pass already rebuilt (or already tripped this
  # guard) at this SAME head and the identity was STILL unreadable afterwards, something structural
  # (a layout or permission mismatch) is eating every rebuild. Do not burn one build per tick
  # forever: fail loudly and hold. Re-armed by any HEAD change or an explicit curator
  # rebuild.request (deliberate human intent always gets a fresh attempt). Side effect, accepted +
  # documented: a FAILED first build on a fresh box (no build.json yet) also holds instead of
  # retrying every 15 min — a deterministic build failure needs an operator, not a retry storm.
  # Known-and-accepted looseness: a sync_failed tick overwrites the status doc and
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

  # 2b. PAUSE. A FRESH pause.flag suppresses the DRIFT-triggered rebuild ("pause
  #     auto-rebuild during a multi-edit session"). An explicit rebuild.request is deliberate, not
  #     "auto", so it is honoured even while paused. A pause older than PAUSE_EXPIRY_MIN was already
  #     resolved to PAUSE_EXPIRED (ignored) in step 0 — a stale flag NEVER suppresses (pause-expiry pin).
  if [ "${PAUSED:-0}" -eq 1 ] && [ "$request_present" -eq 0 ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      printf 'reconcile: [dry-run] auto-rebuild PAUSED (fresh pause.flag) => would NOT rebuild\n'
      return 0
    fi
    _pd="auto-rebuild PAUSED by a curator pause.flag${PAUSE_SINCE:+ (since $PAUSE_SINCE)}; drift is not being rebuilt. Resume from the serve screen (or it auto-expires after ${PAUSE_EXPIRY_MIN} min)."
    write_status "paused" "$head" "$built" "$(read_build_id)" "" "$_pd"
    printf 'reconcile: auto-rebuild paused (fresh pause.flag) — head=%s built=%s, NOT rebuilding\n' "${head:-?}" "${built:-?}"
    return 0
  fi

  # 2c. ROLLBACK PIN (rollback-repoints). While a manual "serve this build" pin stands,
  #     reconcile must NOT auto-rebuild — that would revert the rollback the curator deliberately made.
  #     An explicit rebuild.request is a deliberate MOVE-FORWARD: it clears the pin and proceeds to
  #     build. Without a request, hold and report the pin honestly (drift is EXPECTED under a pin).
  if [ "${PINNED:-0}" -eq 1 ]; then
    if [ "$request_present" -eq 1 ]; then
      rm -f "$ROLLBACK_PIN"; PINNED=0; PINNED_BUILD=""
      printf 'reconcile: rollback pin cleared by an explicit rebuild.request — moving forward\n'
    else
      if [ "$DRY_RUN" -eq 1 ]; then
        printf 'reconcile: [dry-run] rollback pin present => would HOLD (no rebuild)\n'
        return 0
      fi
      _pd="serving a manually pinned build${PINNED_BUILD:+ (builds/$PINNED_BUILD)}; reconcile is holding and will NOT auto-rebuild. Press Request rebuild to move forward to the published HEAD."
      write_status "pinned" "$head" "$built" "$(read_build_id)" "" "$_pd"
      printf 'reconcile: rollback pin present (serving builds/%s) — holding, NOT rebuilding\n' "${PINNED_BUILD:-?}"
      return 0
    fi
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

  # Consume the request file BEFORE building (at-most-once per run): a request written mid-build
  # is picked up on the NEXT tick, never queued into a storm. Content is audit-only and never parsed.
  [ "$request_present" -eq 1 ] && rm -f "$REQUEST_FILE"

  # A rebuild we cannot log is a rebuild we cannot debug from the panel — fail loud BEFORE building
  # (site-data/ is uid-10001-owned; logs/ needs the one-time operator-owned prep, README step 0).
  # Probe WRITABILITY too, not just existence: an existing-but-unwritable logs/ passes `mkdir -p`
  # and would only surface at the build redirect, with make never launched.
  if ! mkdir -p "$LOG_DIR" 2>/dev/null || ! _lprobe=$(mktemp "$LOG_DIR/.probe.XXXXXX" 2>/dev/null); then
    printf 'reconcile: log dir %s cannot be created or is not writable — one-time ownership prep missing (deploy/README.md "Serve reconcile" step 0)\n' "$LOG_DIR" >&2
    write_status "failed" "$head" "$built" "$(read_build_id)" ""
    return 1
  fi
  rm -f "$_lprobe"
  log_file="$LOG_DIR/$(date -u +%Y%m%dT%H%M%SZ).build.log"
  # Force-full-rebuild: a `full` rebuild.request runs the engine in cache-REFRESH mode (the
  # Makefile reads AUSMT_BUILD_CACHE_MODE, defaulting to rw). Empty otherwise => the default cache-rw.
  if [ "$full_rebuild" -eq 1 ]; then
    _cache_mode="refresh"
    printf 'reconcile: %s => FULL rebuild (cache-refresh, no reuse), log: %s\n' "$reason" "$log_file"
  else
    _cache_mode=""
    printf 'reconcile: %s => rebuilding, log: %s\n' "$reason" "$log_file"
  fi

  # Run the rebuild, capturing stdout+stderr to the log. The make target is already atomic
  # (build -> verify -> swap current): a failure leaves the OLD build serving. The script runs
  # under `set -u` (not `-e`), so a non-zero make exit does NOT abort — we capture rc and still write
  # a status document either way.
  # Hand the signal trap everything it needs to write an honest status if systemd kills us mid-build:
  # without these it can still record action=failed, but not WHICH commits or WHICH log to look at.
  TRAP_HEAD="$head"; TRAP_BUILT="$built"; TRAP_LOG="$log_file"
  # The build window's opening edge, in the form journalctl --since accepts, so a failure can ask the
  # kernel journal about THIS build and not last week's (--since is inclusive to the second).
  build_started=$(date -u '+%Y-%m-%d %H:%M:%S UTC')
  # shellcheck disable=SC2086 -- MAKE_CMD is an intentional word-split command (default or shim).
  AUSMT_BUILD_CACHE_MODE="$_cache_mode" $MAKE_CMD > "$log_file" 2>&1
  rc=$?

  # Prune the log dir to the newest 20 *.build.log (operator forensics; never served — LOG_DIR is a
  # sibling of builds/, outside current/). ls -1t newest-first; delete everything past 20.
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
  # consumed, so there is no crash-loop. Exit 1 so `systemctl status`/monitoring flags it.
  # FIRST ask the kernel journal whether the build was OOM-KILLED in its own window (six "rebuild
  # FAILED, see log tail" reports have had a kernel kill two layers down as their cause).
  # If it was, say so BY NAME, kernel lines first, then the log tail; and flag oom_kill in the status.
  # If the journal could NOT be read by this user (journalctl present, no access), say THAT: a plain
  # "failed" over an unread journal is exactly how the incident hid for a week.
  oom_kills_since "$build_started"
  _oom="$OOM_KILLS"
  if [ -n "$_oom" ]; then
    _t=$(tail -n 25 "$log_file" 2>/dev/null || true)
    OOM_KILL=1
    write_status "failed" "$head" "$built" "$(read_build_id)" "$log_file" \
"KILLED BY THE KERNEL FOR RUNNING OUT OF MEMORY. The build did not fail on its own: the kernel's
out-of-memory killer terminated the build process (python, the engine container's uid 10001)
during this rebuild, so the box does not have enough free RAM for the current corpus. The previous
build is still being served. Kernel journal for this build window (since $build_started):
$_oom
What to do: check build_report.json peak_rss_mib on the last GOOD build for the trend; give the box
more RAM or a swap file as a bridge; and if a healthy build already needs most of the box, the
engine's per-station memory bound has regressed (engine/tests/test_build_memory.py).
--- last lines of $log_file ---
$_t"
    printf 'reconcile: rebuild FAILED (rc=%s): KILLED BY THE KERNEL for running out of memory (see the kernel lines in reconcile-status.json); old build still serving. Log: %s\n' "$rc" "$log_file" >&2
    return 1
  fi
  # journalctl is on the host but this user could not read the kernel journal (not in systemd-journal /
  # adm): the negative above is NOT evidence. Keep the ordinary failed status (oom_kill=false: nothing
  # was seen) but lead the detail with the fact that a kill cannot be excluded and how to make it
  # visible. A host with no journalctl at all (non-systemd, cron/PBS) keeps the plain path unchanged.
  if [ -n "$OOM_JOURNAL_UNREADABLE" ] && [ "$OOM_JOURNAL_UNREADABLE" != "no journalctl on this host" ]; then
    _t=$(tail -n 30 "$log_file" 2>/dev/null || true)
    write_status "failed" "$head" "$built" "$(read_build_id)" "$log_file" \
"rebuild FAILED (rc=$rc); the previous build is still being served.
NOTE: the KERNEL JOURNAL COULD NOT BE READ by this user ($OOM_JOURNAL_UNREADABLE),
so a kernel out-of-memory kill during this build CANNOT BE EXCLUDED: an unread journal is not
evidence, and an OOM-killed build reads as a plain failure. Add the user this agent runs as
($(id -un 2>/dev/null || echo '?')) to the systemd-journal group (deploy/README.md, 'Serve reconcile'
install step 0c) so the next failure can be named by cause.
--- last lines of $log_file ---
$_t"
    printf 'reconcile: rebuild FAILED (rc=%s); kernel journal unreadable by this user, an OOM kill cannot be excluded (add %s to systemd-journal). Old build still serving. Log: %s\n' "$rc" "$(id -un 2>/dev/null || echo '?')" "$log_file" >&2
    return 1
  fi
  write_status "failed" "$head" "$built" "$(read_build_id)" "$log_file"
  printf 'reconcile: rebuild FAILED (rc=%s) — old build still serving. Log: %s\n' "$rc" "$log_file" >&2
  return 1
}

# flock the whole pass on fd 9. -n => non-blocking: if the lock is held by a concurrent run, flock
# returns non-zero and we exit 0 immediately and SILENTLY (the status file is left untouched — the
# holding run owns this tick). run_pass runs in THIS shell while fd 9 is held, so the entire
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
