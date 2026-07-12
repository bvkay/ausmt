#!/bin/sh
# AusMT external alerting agent. POSIX sh — one pass, timer-driven (deploy/systemd/ausmt-alert.timer
# fires it every 15 min). It runs the health checks below and reports the result to an EXTERNAL
# dead-man monitoring service (healthchecks.io class) via a single ping URL:
#   ALL checks OK  -> ping   $AUSMT_ALERT_URL            (a success/"alive" beat)
#   ANY check FAIL -> ping   $AUSMT_ALERT_URL/fail       with the failure summary as the body,
#                     then EXIT NONZERO so the failure is also journal-visible on the box.
#
# WHY A DEAD-MAN PING AND NOT A BOX-SENT EMAIL (design decision 2026-07-10, do not relitigate):
#   * The SERVICE routes the email (to the curator — ben@auscope.org.au today). The box holds NO SMTP
#     credentials and NO recipient config, so changing who is alerted is a DASHBOARD change at the
#     service — zero repo edits, zero box edits, nothing to redeploy.
#   * A fully DEAD box (power/network/kernel) can never send its own "I am dead" email. The monitoring
#     service detects that as an ABSENT ping (the check goes red when no beat arrives within its grace
#     window) — the one failure a box-sent email can never report. This script covers the "box is up
#     but a subsystem stalled" half; the service's absent-ping timeout covers the "box is gone" half.
#   * This repo ships the BOX SIDE ONLY. Creating the check + setting the alert email is a one-time
#     runbook step at the service (deploy/README.md "Alerting").
#
# SILENT-STALL MODES THIS CATCHES (all real or design-known):
#   * gw-runner crash-loop  -> "submissions stuck at SCANNED" (the 2026-07-06 incident) — the runner
#     has NO compose healthcheck by design, so a not-running / restart-looping runner is caught here by
#     STATE, the only observable compose exposes for it.
#   * a service down / unhealthy (portal, gateway, clamd have healthchecks; a failed rebuild leaves the
#     build-runner untouched but a wedged portal/gateway shows unhealthy here).
#   * a full disk (uploads + builds + the DB all live under $AUSMT_DATA_DIR).
#   * a stale / failed serve-reconcile pass (reconcile-status.json age + action).
#   * a stale or failed nightly backup (newest snapshot age + `systemctl is-failed`).
#
# NO SECRETS: the ONLY sensitive-ish value is the ping URL. It is confidential-ish (anyone who has it
# can spoof a beat) but NON-PRIVILEGED (it grants no access to the box or any data). It lives in
# deploy/.env — which is gitignored and password-manager-canonical — NEVER hardcoded here. Everything
# else is a public threshold. Nothing this script reads or sends contains PII or a credential.
#
# ENV (all documented in deploy/.env.example; the systemd unit's EnvironmentFile provides them):
#   AUSMT_ALERT_URL             (required to alert) the service ping URL. UNSET/EMPTY => this script
#                               prints ONE loud "alerting NOT configured" note and exits 0 — it never
#                               fakes a ping and never breaks the timer.
#   AUSMT_DATA_DIR              (required) host root: gateway/state/, backups/, site-data/ live under it
#   AUSMT_CODE_DIR              (required for the service check) this checkout; its deploy/ holds
#                               compose.yaml, so the compose ps runs from $AUSMT_CODE_DIR/deploy
#   AUSMT_ALERT_DISK_PCT        (default 85)  disk-usage %% of the $AUSMT_DATA_DIR filesystem that fails
#   AUSMT_ALERT_RECONCILE_MAX_MIN (default 45) reconcile-status.json older than this (min) fails
#   AUSMT_ALERT_BACKUP_MAX_H    (default 26)  newest backup snapshot older than this (hours) fails
#   AUSMT_ALERT_COMPOSE         (optional) override the `docker compose` command (a test shim hooks here)
#   AUSMT_ALERT_CURL            (optional) override the `curl` command (a test shim hooks here)
#
# Dependency-light on purpose: POSIX sh, coreutils, `docker compose`, and `curl`. python3/python is
# used ONLY to parse the two JSON inputs (compose ps + reconcile-status.json) — the same interpreter
# reconcile.sh/backup.sh already require on the deploy host; a fragile grep would misparse reordered
# JSON. Read it top to bottom.

set -u

# --------------------------------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------------------------------
ALERT_URL="${AUSMT_ALERT_URL:-}"
DISK_PCT_MAX="${AUSMT_ALERT_DISK_PCT:-85}"
RECONCILE_MAX_MIN="${AUSMT_ALERT_RECONCILE_MAX_MIN:-45}"
BACKUP_MAX_H="${AUSMT_ALERT_BACKUP_MAX_H:-26}"
COMPOSE_CMD="${AUSMT_ALERT_COMPOSE:-docker compose}"
CURL_CMD="${AUSMT_ALERT_CURL:-curl}"
# C43 S2b-ii (record D9.7): a curator pause of auto-rebuild that is active or slow-re-armed past this
# CUMULATIVE threshold flips the ops-floor Freshness/Serve card amber AND fails a check here — so an
# authenticated attacker (stolen session / curator-page XSS) cannot silently keep serving frozen
# forever by re-arming the pause once per expiry window (which would slip a single-flag age check).
PAUSE_MAX_H="${AUSMT_ALERT_PAUSE_MAX_H:-24}"

# C43 S2b-i: this timer is ALSO the ops-status.json writer (record D8/D15). Its cadence (the systemd
# ausmt-alert.timer period, ~15 min) is the staleness clock the curator ops floor reads: a file older
# than ~2 periods flips every dependent card STALE. Override only if you retimed the unit.
TIMER_PERIOD_MIN="${AUSMT_ALERT_PERIOD_MIN:-15}"
# The gateway state dir (10002-owned, group-writable to the operator — the same shared-group prep the
# reconcile agent uses) is where reconcile-status.json AND ops-status.json live. Empty when
# AUSMT_DATA_DIR is unset (we then skip the ops-status write, loudly, rather than write into /).
DATA_DIR_ROOT="${AUSMT_DATA_DIR:-}"
STATE_DIR="${DATA_DIR_ROOT:+$DATA_DIR_ROOT/gateway/state}"
OPS_STATUS_FILE="${STATE_DIR:+$STATE_DIR/ops-status.json}"
SITE_DATA="${DATA_DIR_ROOT:+$DATA_DIR_ROOT/site-data}"

# Facts the check_* functions compute for the fail-ping ARE ALSO the ops-floor facts — hoisted into
# these globals as each check runs so the ops writer reuses them (one `docker compose ps`, one `df`).
OPS_PS_JSON=""
OPS_DISK_PCT=""
# C43 S2b-ii persistent-pause tracking (record D9.7). check_pause computes these ONCE (carrying the
# continuous-span first_seen forward from the previous ops-status.json) so BOTH the fail-ping and the
# ops-status.json pause fact use the same verdict.
OPS_PAUSE_ACTIVE=0
OPS_PAUSE_PAUSED_AT=""
OPS_PAUSE_FIRST_SEEN=""
OPS_PAUSE_CUMULATIVE_H=""
OPS_PAUSE_PERSISTENT=0

# The four long-running compose services this box monitors. build-runner is EXCLUDED on purpose: it is
# a one-shot job (compose profile "jobs") that is SUPPOSED to be absent between builds, so "not running"
# is its normal state — alerting on it would fire constantly. gw-runner IS included: it is long-running
# and its silent death is the headline failure mode (2026-07-06). Kept in sync with compose.yaml.
MONITORED_SERVICES="portal gateway clamd gw-runner"
# The services that HAVE a compose healthcheck (compose.yaml). gw-runner deliberately does NOT (see its
# comment there), so an EMPTY Health for gw-runner is expected, not a fault — we never fail it on Health,
# only on State. Any OTHER of these three reporting a non-empty, non-"healthy" Health is a fault.
HEALTHCHECKED_SERVICES="portal gateway clamd"

# Accumulate human-readable failure lines here (newline-separated). Empty at the end == all OK.
FAILURES=""

add_failure() {
  # Append one failure line. Leading newline is stripped at send time.
  FAILURES="$FAILURES
$1"
}

log() { printf '%s %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }

# Full ISO-8601 UTC (the EXACT format reconcile.sh writes into last_run) — the ops-status.json
# generated_at the gateway's staleness clock parses. Kept identical so both files parse the same way.
now_utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# python3/python for the two JSON parses. Probe by EXECUTION (a Windows dev box can have a non-functional
# `python3` App-Store shim), exactly as reconcile.sh does. Only the service + reconcile checks need it;
# if it is absent we still run the disk + backup checks and note the gap as a failure (fail loud, never
# silently skip a check).
PY=""
for _cand in python3 python; do
  if command -v "$_cand" >/dev/null 2>&1 && "$_cand" -c "import sys" >/dev/null 2>&1; then
    PY="$_cand"
    break
  fi
done

# --------------------------------------------------------------------------------------------------
# Check a: compose service health.
#   Reads `docker compose ps --format json` (run from $AUSMT_CODE_DIR/deploy with --profile gateway so
#   the gateway-profile services are in scope). For EACH monitored service, a fail line if it is:
#     * absent from the ps output entirely (not created / never came up), OR
#     * State != "running" (exited, restarting, dead, paused, created), OR
#     * (healthchecked services only) Health is present and not "healthy"/"starting", OR
#     * RestartCount present and > 0 while restarting (belt-and-braces crash-loop signal).
#   compose emits either a JSON ARRAY or newline-delimited objects depending on the compose version;
#   the python reader below tolerates both. Field names (Service, State, Health, RestartCount) are the
#   compose ps schema. A "restarting" State is the exact crash-loop signal for the healthcheck-less
#   gw-runner (README §4 "submissions stuck at SCANNED").
# --------------------------------------------------------------------------------------------------
check_services() {
  code_dir="${AUSMT_CODE_DIR:-}"
  if [ -z "$code_dir" ]; then
    add_failure "services: AUSMT_CODE_DIR unset -- cannot locate deploy/compose.yaml to check container health"
    return
  fi
  deploy_dir="$code_dir/deploy"
  if [ ! -f "$deploy_dir/compose.yaml" ]; then
    add_failure "services: no compose.yaml at $deploy_dir (AUSMT_CODE_DIR wrong?) -- cannot check container health"
    return
  fi
  if [ -z "$PY" ]; then
    add_failure "services: no working python3/python on PATH -- cannot parse 'docker compose ps' output"
    return
  fi

  # --profile gateway so gateway/clamd/gw-runner (all under that profile) are listed alongside portal.
  # shellcheck disable=SC2086 -- COMPOSE_CMD may be a multi-word command (e.g. `docker compose` or a shim).
  ps_json="$($COMPOSE_CMD --profile gateway ps --format json --all 2>/dev/null)"
  OPS_PS_JSON="$ps_json"   # hoist for the ops-status writer (the Box card's service list)
  if [ -z "$ps_json" ]; then
    # No output at all: the compose invocation itself failed (docker down? wrong dir?) — that IS a fault,
    # every monitored service is unaccounted for.
    add_failure "services: 'docker compose ps' returned nothing (docker daemon down, or wrong AUSMT_CODE_DIR/deploy) -- cannot confirm any service is running"
    return
  fi

  # The python reader emits ONE line per PROBLEM service: "<service>: <reason>". No output => all OK.
  # ps_json is passed via env (NOT a pipe): the python script itself is fed on stdin via the heredoc, so
  # stdin is already taken -- a `printf | python -` would collide the pipe with the heredoc.
  problems="$(AUSMT_PS_JSON="$ps_json" AUSMT_MON="$MONITORED_SERVICES" AUSMT_HC="$HEALTHCHECKED_SERVICES" "$PY" - <<'PYEOF' 2>/dev/null || true
import json, os

raw = os.environ.get("AUSMT_PS_JSON", "")
monitored = os.environ["AUSMT_MON"].split()
healthchecked = set(os.environ["AUSMT_HC"].split())

# compose emits EITHER a JSON array OR one JSON object per line (JSONL). Accept both.
records = []
stripped = raw.strip()
if stripped.startswith("["):
    try:
        records = json.loads(stripped)
    except Exception:
        records = []
else:
    for line in stripped.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except Exception:
            pass

by_service = {}
for rec in records:
    if not isinstance(rec, dict):
        continue
    name = rec.get("Service") or rec.get("Name") or ""
    if name:
        by_service[name] = rec

for svc in monitored:
    rec = by_service.get(svc)
    if rec is None:
        print(f"{svc}: not present in 'docker compose ps' (container not created / never started)")
        continue
    state = (rec.get("State") or "").lower()
    health = (rec.get("Health") or "").lower()
    if state != "running":
        # exited / restarting / dead / paused / created — all faults for a long-running service.
        exit_code = rec.get("ExitCode")
        extra = f" exit={exit_code}" if exit_code not in (None, "", 0) else ""
        print(f"{svc}: state={state or 'unknown'}{extra} (expected running)")
        continue
    # Running: for a healthchecked service, a present-and-not-healthy Health is a fault. "starting" is
    # the transient warm-up window (the compose start_period) — not yet a fault. gw-runner has no
    # healthcheck, so its Health is legitimately empty and never fails here.
    if svc in healthchecked and health and health not in ("healthy", "starting"):
        print(f"{svc}: health={health} (running but healthcheck failing)")
        continue
    # Belt: an explicit RestartCount, when compose exposes it, catches a container that is momentarily
    # "running" between crash-loop restarts.
    rc = rec.get("RestartCount")
    try:
        if rc is not None and int(rc) > 0 and state == "restarting":
            print(f"{svc}: restart-looping (RestartCount={rc})")
    except (TypeError, ValueError):
        pass
PYEOF
)"

  if [ -n "$problems" ]; then
    # One fail line per problem service, prefixed so the alert body reads clearly. A here-string via a
    # heredoc keeps the read loop in THIS shell (a `printf | while` would run the loop in a subshell and
    # lose the FAILURES appends).
    while IFS= read -r line; do
      [ -n "$line" ] || continue
      add_failure "service $line"
    done <<EOF
$problems
EOF
  fi
}

# --------------------------------------------------------------------------------------------------
# Check b: disk usage of the filesystem holding $AUSMT_DATA_DIR.
#   `df -P <dir>` (POSIX portable output) — read the Use%% column of the data row, strip the '%', and
#   fail if it is > AUSMT_ALERT_DISK_PCT. Uploads, builds, and the DB all land under $AUSMT_DATA_DIR, so
#   this is the filesystem whose exhaustion silently wedges the pipeline.
# --------------------------------------------------------------------------------------------------
check_disk() {
  data_dir="${AUSMT_DATA_DIR:-}"
  if [ -z "$data_dir" ]; then
    add_failure "disk: AUSMT_DATA_DIR unset -- cannot check the data filesystem"
    return
  fi
  if [ ! -d "$data_dir" ]; then
    add_failure "disk: AUSMT_DATA_DIR does not exist: $data_dir (unmounted volume? typo?)"
    return
  fi
  # -P => POSIX one-line-per-fs format; the 5th field of the data row is "NN%".
  used_pct="$(df -P "$data_dir" 2>/dev/null | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
  OPS_DISK_PCT="$used_pct"   # hoist for the ops-status writer (the Box card's disk gauge)
  if [ -z "$used_pct" ]; then
    add_failure "disk: could not read df output for $data_dir"
    return
  fi
  # Integer compare (df Use% is always an integer). Guard against a non-numeric df quirk.
  case "$used_pct" in
    ''|*[!0-9]*)
      add_failure "disk: unexpected df Use% value '$used_pct' for $data_dir"
      return ;;
  esac
  if [ "$used_pct" -gt "$DISK_PCT_MAX" ]; then
    add_failure "disk: $data_dir filesystem ${used_pct}% used (threshold ${DISK_PCT_MAX}%)"
  fi
}

# --------------------------------------------------------------------------------------------------
# Check c: serve-reconcile freshness (reconcile.sh writes $AUSMT_DATA_DIR/gateway/state/
#   reconcile-status.json every ~15 min; fields per reconcile.sh: last_run (ISO-8601 UTC
#   %Y-%m-%dT%H:%M:%SZ) + action). Fail if:
#     * the file is missing (the reconcile timer is not running / never wrote one) — WARN-class only on
#       a fresh install; here we treat absence as a fail because on a configured box the timer must run,
#     * last_run is older than AUSMT_ALERT_RECONCILE_MAX_MIN (the timer stalled), OR
#     * action == "failed" (a build/verify failure — the C40 fail-closed state), OR
#     * action == "untracked_blocked" (the reconcile agent REFUSED to rebuild because surveys-live has
#       untracked survey dirs the build would serve — incident 2026-07-11; needs an operator, no self-heal).
#   noop/rebuilt/sync_failed are all healthy timer outcomes (they exit 0) and do NOT fail here — a
#   sync_failed is an operator-visible panel state, not a monitoring alert (README §4).
# --------------------------------------------------------------------------------------------------
check_reconcile() {
  data_dir="${AUSMT_DATA_DIR:-}"
  [ -n "$data_dir" ] || { add_failure "reconcile: AUSMT_DATA_DIR unset -- cannot find reconcile-status.json"; return; }
  status_file="$data_dir/gateway/state/reconcile-status.json"
  if [ ! -f "$status_file" ]; then
    add_failure "reconcile: $status_file missing (reconcile timer not running, or no pass has completed yet)"
    return
  fi
  if [ -z "$PY" ]; then
    add_failure "reconcile: no working python3/python on PATH -- cannot parse reconcile-status.json"
    return
  fi
  # The reader prints a single reason line if the status is stale or failed, else nothing.
  reason="$(AUSMT_RS_MAX_MIN="$RECONCILE_MAX_MIN" "$PY" - "$status_file" <<'PYEOF' 2>/dev/null || true
import datetime, json, os, sys

path = sys.argv[1]
max_min = int(os.environ["AUSMT_RS_MAX_MIN"])
try:
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
except Exception as exc:
    print(f"reconcile-status.json unreadable/corrupt ({exc})")
    raise SystemExit(0)

action = doc.get("action")
last_run = doc.get("last_run")

if action == "failed":
    print(f"action=failed (last build/verify failed; last_run={last_run})")
    raise SystemExit(0)

if action == "untracked_blocked":
    # The reconcile agent REFUSED to rebuild: surveys-live has untracked survey dirs the build would
    # SERVE though git cannot remove them (incident 2026-07-11). This needs an operator and does not
    # self-heal, so it is an ALERT (unlike sync_failed, which is a transient panel state). The offending
    # names are carried in log_tail — surface them so the dead-man ping names the dir(s).
    detail = doc.get("log_tail") or "untracked survey dir(s) present"
    print(f"action=untracked_blocked - reconcile REFUSED the rebuild: {detail} (last_run={last_run})")
    raise SystemExit(0)

# Age check on last_run (ISO-8601 UTC, e.g. 2026-07-10T03:20:00Z — the format reconcile.sh writes).
if not last_run:
    print("no last_run timestamp in reconcile-status.json (never completed a pass?)")
    raise SystemExit(0)
try:
    ts = datetime.datetime.strptime(last_run, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=datetime.timezone.utc)
except Exception:
    print(f"unparseable last_run '{last_run}' in reconcile-status.json")
    raise SystemExit(0)
now = datetime.datetime.now(datetime.timezone.utc)
age_min = (now - ts).total_seconds() / 60.0
if age_min > max_min:
    print(f"stale: last_run {last_run} is {int(age_min)} min old (threshold {max_min} min) -- reconcile timer stalled?")
PYEOF
)"
  if [ -n "$reason" ]; then
    add_failure "reconcile: $reason"
  fi
}

# --------------------------------------------------------------------------------------------------
# Check d: nightly-backup freshness.
#   Newest snapshot dir under $AUSMT_BACKUP_DIR (else $AUSMT_DATA_DIR/backups) — dirs are named
#   <utc-ts> matching [0-9]*Z (backup.sh). Fail if the newest is older than AUSMT_ALERT_BACKUP_MAX_H,
#   or if `systemctl is-failed ausmt-backup.service` reports the unit failed. A MISSING backups dir on a
#   configured box is a WARN-class line (fresh install before the first backup) — still surfaced so the
#   operator knows the backup timer has not run, but phrased as a warning.
# --------------------------------------------------------------------------------------------------
check_backup() {
  data_dir="${AUSMT_DATA_DIR:-}"
  [ -n "$data_dir" ] || { add_failure "backup: AUSMT_DATA_DIR unset -- cannot find the backups dir"; return; }
  backups_dir="${AUSMT_BACKUP_DIR:-$data_dir/backups}"

  # systemd's own view of the last backup run, if systemctl exists (it will on the box; not on a Mac/CI).
  if command -v systemctl >/dev/null 2>&1; then
    if [ "$(systemctl is-failed ausmt-backup.service 2>/dev/null || true)" = "failed" ]; then
      add_failure "backup: systemd reports ausmt-backup.service FAILED (last nightly backup errored) -- check 'systemctl status ausmt-backup.service'"
    fi
  fi

  if [ ! -d "$backups_dir" ]; then
    # Fresh install before the first backup: a WARN, not a hard state (still surfaced so it is not
    # silently ignored). We add it as a failure line so it reaches the operator, prefixed WARN.
    add_failure "backup: WARN backups dir $backups_dir does not exist yet (no backup has run -- expected only on a fresh install; if the box has been up >1 day the backup timer is not installed)"
    return
  fi

  # Newest snapshot dir by name (UTC-timestamp names sort chronologically), matching backup.sh's glob.
  newest="$(find "$backups_dir" -mindepth 1 -maxdepth 1 -type d -name '[0-9]*Z' 2>/dev/null | sort -r | head -n 1)"
  if [ -z "$newest" ]; then
    add_failure "backup: no snapshot dirs under $backups_dir (backup timer installed but no successful backup yet)"
    return
  fi

  # Age of the newest snapshot dir in hours, from its mtime. `find -mmin` is the portable-enough test:
  # a dir NOT modified within the last (BACKUP_MAX_H*60) minutes is too old.
  max_min=$((BACKUP_MAX_H * 60))
  if [ -z "$(find "$newest" -maxdepth 0 -mmin "-$max_min" 2>/dev/null)" ]; then
    add_failure "backup: newest snapshot $(basename "$newest") is older than ${BACKUP_MAX_H}h -- the nightly backup has not run recently"
  fi
}

# --------------------------------------------------------------------------------------------------
# Check e (C43 S2b-ii): PERSISTENT-PAUSE alarm (record D9.7).
#   The curator can pause auto-rebuild (pause.flag; reconcile auto-expires it after 6 h). A single
#   pause is fine. The threat is a SLOW RE-ARM — re-writing the flag once per expiry window keeps
#   auto-rebuild dead forever while every INDIVIDUAL flag stays "fresh" (a single-flag age check would
#   never fire). We defeat that by carrying a CONTINUOUS-SPAN first_seen forward from the previous
#   ops-status.json: as long as a pause.flag is present on each tick, first_seen persists across
#   re-arms, so cumulative = now - first_seen grows past the window and this fails LOUDLY.
#   A pause active/re-armed beyond PAUSE_MAX_H cumulative is a failure line AND an ops-floor amber fact.
# --------------------------------------------------------------------------------------------------
check_pause() {
  data_dir="${AUSMT_DATA_DIR:-}"
  [ -n "$data_dir" ] || return 0            # AUSMT_DATA_DIR gaps are already reported by other checks
  pause_flag="$data_dir/gateway/state/pause.flag"
  [ -f "$pause_flag" ] || return 0          # no pause => nothing to track (globals stay at defaults)
  OPS_PAUSE_ACTIVE=1
  [ -n "$PY" ] || return 0                  # cannot compute cumulative without python; the ops fact
                                            # still shows active, just not the persistence verdict
  # Compute: first_seen (carried from prev ops-status if it was already active, else now), the flag's
  # own paused_at, the cumulative hours, and the persistent verdict. Prints: first_seen|paused_at|hours|persistent
  line=$(AUSMT_PF="$pause_flag" AUSMT_PREV="${OPS_STATUS_FILE:-}" AUSMT_NOW="$(now_utc)" \
         AUSMT_MAX_H="$PAUSE_MAX_H" "$PY" - <<'PYEOF' 2>/dev/null || true
import datetime, json, os

def load(p):
    if not p or not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None

def parse(ts):
    if not isinstance(ts, str) or not ts:
        return None
    try:
        return datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except Exception:
        return None

now_s = os.environ["AUSMT_NOW"]
now = parse(now_s)
flag = load(os.environ.get("AUSMT_PF"))
paused_at = flag.get("paused_at") if isinstance(flag, dict) else None

prev = load(os.environ.get("AUSMT_PREV")) or {}
prev_pause = prev.get("pause") if isinstance(prev.get("pause"), dict) else {}
# Carry the continuous-span first_seen: only if the previous tick ALSO saw an active pause.
if prev_pause.get("active") and prev_pause.get("first_seen"):
    first_seen = prev_pause.get("first_seen")
else:
    first_seen = paused_at or now_s        # a fresh span starts now (or at the flag's own stamp)

fs = parse(first_seen)
hours = ""
persistent = 0
if fs is not None and now is not None:
    h = (now - fs).total_seconds() / 3600.0
    hours = f"{h:.1f}"
    try:
        if h > float(os.environ.get("AUSMT_MAX_H") or 24):
            persistent = 1
    except Exception:
        pass
print(f"{first_seen}|{paused_at or ''}|{hours}|{persistent}")
PYEOF
)
  if [ -n "$line" ]; then
    OPS_PAUSE_FIRST_SEEN=$(printf '%s' "$line" | cut -d'|' -f1)
    OPS_PAUSE_PAUSED_AT=$(printf '%s' "$line" | cut -d'|' -f2)
    OPS_PAUSE_CUMULATIVE_H=$(printf '%s' "$line" | cut -d'|' -f3)
    OPS_PAUSE_PERSISTENT=$(printf '%s' "$line" | cut -d'|' -f4)
  fi
  if [ "${OPS_PAUSE_PERSISTENT:-0}" = "1" ]; then
    add_failure "pause: auto-rebuild has been PAUSED for ${OPS_PAUSE_CUMULATIVE_H}h cumulative (threshold ${PAUSE_MAX_H}h) -- serving may be frozen. Resume auto-rebuild from the serve screen, or investigate a re-armed pause (stolen session / XSS). first_seen=${OPS_PAUSE_FIRST_SEEN}"
  fi
}

# --------------------------------------------------------------------------------------------------
# C43 S2b-i: write ops-status.json for the curator ops floor (record D8/D15). SEPARATE from the ping:
# it runs every pass — INCLUDING when alerting is unconfigured — because the ops floor must reflect
# box state before (and independently of) the external dead-man monitor being wired. Atomic (mktemp +
# chmod 0644 + mv, the reconcile.sh posture) so the gateway container (uid 10002, group-shared state
# dir) never reads a half-written file and can always read a complete one. Best-effort: ANY failure
# here is a warning, never a change to the pass's exit code (the ping is the timer's real contract).
#
# The facts, over what the checks already gather (service health / disk / reconcile / backup):
#   * freshness: code checkout AND surveys-live, each local short HEAD vs its last-fetched tracking
#     ref (@{u}). NO fetch here (a network side effect in the alert timer is itself a failure mode,
#     and a fetch that cannot reach origin is exactly the reconcile sync-strip's job) — so this
#     reflects the last SUCCESSFUL fetch; behind => the card's row goes amber. (Record D15: the two
#     signals are complementary — the sync strip catches "cannot reach origin", freshness catches
#     "reached it, but the checkout is behind".)
#   * reconcile sync state: action + a sync_failed STREAK (count + since), derived by carrying the
#     previous ops-status.json forward — so a 4-hour hidden sync_failed (incident 2026-07-11) reads
#     as "failing for N ticks since T", not a silent single line.
#   * retained-build inventory: each site-data/builds/<ts> dir's build.json (id/engine/source) +
#     build_report.json (stations) + build_provenance.json `cache` block (the C18-A4 forensics:
#     salt_fp / write_errors / read_errors) + a serving marker (== current symlink target).
#   * log tail: the newest site-data/logs/*.build.log, last 60 lines, copied into the file (the
#     gateway has no site-data mount — this is how a shell-less curator reads build forensics).
# --------------------------------------------------------------------------------------------------
write_ops_status() {
  # _checks_ok=1 when the run found no failures (the summary is empty); _installed=1 when a ping URL
  # is configured. Both are computed by the caller and passed in.
  _checks_ok="$1"; _installed="$2"

  if [ -z "$STATE_DIR" ] || [ ! -d "$STATE_DIR" ]; then
    printf '%s ops-status: state dir unavailable (%s) -- not writing ops-status.json\n' \
      "$(date -u +%H:%M:%SZ)" "${STATE_DIR:-<AUSMT_DATA_DIR unset>}" >&2
    return 0
  fi
  if [ -z "$PY" ]; then
    printf '%s ops-status: no python3/python -- not writing ops-status.json\n' "$(date -u +%H:%M:%SZ)" >&2
    return 0
  fi

  # ----- git freshness (NO fetch): local short HEAD vs last-fetched tracking ref, both repos -----
  _code_dir="${AUSMT_CODE_DIR:-}"
  _code_sha=""; _code_origin=""
  if [ -n "$_code_dir" ] && [ -e "$_code_dir/.git" ]; then
    _code_sha=$(git -C "$_code_dir" rev-parse --short HEAD 2>/dev/null || true)
    _code_origin=$(git -C "$_code_dir" rev-parse --short '@{u}' 2>/dev/null || true)
  fi
  _sl_dir="${DATA_DIR_ROOT:+$DATA_DIR_ROOT/surveys-live}"
  _sl_sha=""; _sl_origin=""
  if [ -n "$_sl_dir" ] && [ -e "$_sl_dir/.git" ]; then
    _sl_sha=$(git -C "$_sl_dir" rev-parse --short HEAD 2>/dev/null || true)
    _sl_origin=$(git -C "$_sl_dir" rev-parse --short '@{u}' 2>/dev/null || true)
  fi

  # ----- uptime (best-effort, box card) -----
  _uptime=""
  if command -v uptime >/dev/null 2>&1; then
    _uptime=$(uptime -p 2>/dev/null || true)
    [ -n "$_uptime" ] || _uptime=$(uptime 2>/dev/null | sed 's/^[[:space:]]*//' || true)
  fi

  # ----- systemd backup failure flag (reuse the check_backup signal) -----
  _backup_systemd_failed=0
  if command -v systemctl >/dev/null 2>&1; then
    [ "$(systemctl is-failed ausmt-backup.service 2>/dev/null || true)" = "failed" ] && _backup_systemd_failed=1
  fi

  _tmp=$(mktemp "$OPS_STATUS_FILE.tmp.XXXXXX" 2>/dev/null) || {
    printf '%s ops-status: cannot create tmp under %s -- not writing\n' "$(date -u +%H:%M:%SZ)" "$STATE_DIR" >&2
    return 0; }
  # 0644 so the gateway CONTAINER (uid 10002) can read it via the shared state dir (same rationale as
  # reconcile.sh's status writer — mktemp is 0600, the consumer is a different uid).
  chmod 0644 "$_tmp" 2>/dev/null || true

  AUSMT_OPS_NOW="$(now_utc)" \
  AUSMT_OPS_PERIOD_MIN="$TIMER_PERIOD_MIN" \
  AUSMT_OPS_PREV="$OPS_STATUS_FILE" \
  AUSMT_OPS_RECONCILE="${STATE_DIR}/reconcile-status.json" \
  AUSMT_OPS_BACKUPS_DIR="${AUSMT_BACKUP_DIR:-${DATA_DIR_ROOT:+$DATA_DIR_ROOT/backups}}" \
  AUSMT_OPS_BACKUP_MAX_H="$BACKUP_MAX_H" \
  AUSMT_OPS_BACKUP_SYSTEMD_FAILED="$_backup_systemd_failed" \
  AUSMT_OPS_ALERT_INSTALLED="$_installed" \
  AUSMT_OPS_CHECKS_OK="$_checks_ok" \
  AUSMT_OPS_DISK_PCT="$OPS_DISK_PCT" \
  AUSMT_OPS_DISK_MAX="$DISK_PCT_MAX" \
  AUSMT_OPS_PS_JSON="$OPS_PS_JSON" \
  AUSMT_OPS_UPTIME="$_uptime" \
  AUSMT_OPS_CLAMAV_DIR="${DATA_DIR_ROOT:+$DATA_DIR_ROOT/gateway/clamav}" \
  AUSMT_OPS_CODE_SHA="$_code_sha" AUSMT_OPS_CODE_ORIGIN="$_code_origin" \
  AUSMT_OPS_SL_SHA="$_sl_sha" AUSMT_OPS_SL_ORIGIN="$_sl_origin" \
  AUSMT_OPS_SITE_DATA="${SITE_DATA:-}" \
  AUSMT_OPS_PAUSE_ACTIVE="$OPS_PAUSE_ACTIVE" AUSMT_OPS_PAUSE_PAUSED_AT="$OPS_PAUSE_PAUSED_AT" \
  AUSMT_OPS_PAUSE_FIRST_SEEN="$OPS_PAUSE_FIRST_SEEN" AUSMT_OPS_PAUSE_CUMULATIVE_H="$OPS_PAUSE_CUMULATIVE_H" \
  AUSMT_OPS_PAUSE_PERSISTENT="$OPS_PAUSE_PERSISTENT" AUSMT_OPS_PAUSE_MAX_H="$PAUSE_MAX_H" \
  AUSMT_OPS_STATE_DIR="${STATE_DIR:-}" \
  "$PY" - > "$_tmp" <<'PYEOF'
import datetime, glob, json, os

def _b(name):
    return os.environ.get(name, "") == "1"

def _s(name):
    v = os.environ.get(name, "")
    return v if v else None

def _load(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None

def _prefix_eq(a, b):
    # Both are `git rev-parse --short` outputs; tolerate a length mismatch either direction.
    if not a or not b:
        return None                      # cannot judge without both sides
    return a.startswith(b) or b.startswith(a)

now = os.environ["AUSMT_OPS_NOW"]
prev = _load(os.environ.get("AUSMT_OPS_PREV"))

# ---- reconcile + sync_failed streak (carried forward from the previous ops-status.json) ----
rec = _load(os.environ.get("AUSMT_OPS_RECONCILE")) or {}
action = rec.get("action")
last_run = rec.get("last_run")
sync_failed = (action == "sync_failed")
prev_rec = (prev or {}).get("reconcile") or {}
if sync_failed:
    if prev_rec.get("sync_failed"):
        streak = int(prev_rec.get("sync_failed_streak") or 0) + 1
        since = prev_rec.get("sync_failed_since") or last_run
    else:
        streak = 1
        since = last_run
else:
    streak, since = 0, None
reconcile = {"action": action, "last_run": last_run, "sync_failed": sync_failed,
             "sync_failed_streak": streak, "sync_failed_since": since,
             "build_id": rec.get("build_id"), "built": rec.get("built"), "head": rec.get("head")}

# ---- backups ----
backups_dir = os.environ.get("AUSMT_OPS_BACKUPS_DIR") or ""
snaps = []
if backups_dir and os.path.isdir(backups_dir):
    for name in sorted(os.listdir(backups_dir), reverse=True):
        d = os.path.join(backups_dir, name)
        if os.path.isdir(d) and name[:1].isdigit() and name.endswith("Z"):
            snaps.append((name, d))
_now_ts = datetime.datetime.now().timestamp()
def _age_h(path):
    try:
        return round((_now_ts - os.path.getmtime(path)) / 3600.0, 1)
    except OSError:
        return None
newest = snaps[0] if snaps else None
# The snapshot table (B5): newest-first {name, age_hours}, capped (retention is ~14 on the box).
snap_list = [{"name": name, "age_hours": _age_h(d)} for name, d in snaps[:30]]
drill = _load(os.path.join(backups_dir, "latest-drill.json")) if backups_dir else None
backups = {"newest": newest[0] if newest else None,
           "age_hours": _age_h(newest[1]) if newest else None, "count": len(snaps),
           "snapshots": snap_list,
           "max_hours": int(os.environ.get("AUSMT_OPS_BACKUP_MAX_H") or 26),
           "systemd_failed": _b("AUSMT_OPS_BACKUP_SYSTEMD_FAILED"),
           "drill": drill}   # {"verdict":..,"at":..} if restore-drill writes one, else null

# ---- alerts (dead-man ping): installed + this run's self-check verdict ----
alerts = {"installed": _b("AUSMT_OPS_ALERT_INSTALLED"), "checks_ok": _b("AUSMT_OPS_CHECKS_OK")}

# ---- box: uptime / disk / services / clamav signature age ----
services = []
raw = os.environ.get("AUSMT_OPS_PS_JSON", "").strip()
records = []
if raw.startswith("["):
    try:
        records = json.loads(raw)
    except Exception:
        records = []
else:
    for line in raw.splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except Exception:
                pass
for r in records:
    if isinstance(r, dict):
        nm = r.get("Service") or r.get("Name")
        if nm:
            services.append({"name": nm, "state": (r.get("State") or "").lower(),
                             "health": (r.get("Health") or "").lower()})
services.sort(key=lambda s: s["name"])

clamav_age_days = None
cd = os.environ.get("AUSMT_OPS_CLAMAV_DIR") or ""
if cd and os.path.isdir(cd):
    newest_sig = None
    for pat in ("*.cvd", "*.cld"):
        for f in glob.glob(os.path.join(cd, pat)):
            try:
                m = os.path.getmtime(f)
            except OSError:
                continue
            if newest_sig is None or m > newest_sig:
                newest_sig = m
    if newest_sig is not None:
        clamav_age_days = round((datetime.datetime.now().timestamp() - newest_sig) / 86400.0, 1)

disk_pct = os.environ.get("AUSMT_OPS_DISK_PCT") or ""
box = {"uptime": _s("AUSMT_OPS_UPTIME"),
       "disk_pct": int(disk_pct) if disk_pct.isdigit() else None,
       "disk_max_pct": int(os.environ.get("AUSMT_OPS_DISK_MAX") or 85),
       "services": services, "clamav_sig_age_days": clamav_age_days}

# ---- freshness: BOTH repos, local short HEAD vs last-fetched tracking ref ----
def _fresh(sha_env, origin_env):
    sha = _s(sha_env); origin = _s(origin_env)
    eq = _prefix_eq(sha, origin)
    return {"sha": sha, "origin": origin,
            "behind": (eq is False), "comparable": (eq is not None)}
freshness = {"code": _fresh("AUSMT_OPS_CODE_SHA", "AUSMT_OPS_CODE_ORIGIN"),
             "surveys_live": _fresh("AUSMT_OPS_SL_SHA", "AUSMT_OPS_SL_ORIGIN")}

# ---- retained-build inventory + the C18-A4 cache forensics (build_provenance.json `cache`) ----
site_data = os.environ.get("AUSMT_OPS_SITE_DATA") or ""
builds = []
serving_dir = None
if site_data:
    cur = os.path.join(site_data, "current")
    try:
        serving_dir = os.path.basename(os.readlink(cur).rstrip("/")) if os.path.islink(cur) else \
            os.path.basename(os.path.realpath(cur).rstrip("/"))
    except OSError:
        serving_dir = None
    builds_root = os.path.join(site_data, "builds")
    if os.path.isdir(builds_root):
        for name in sorted(os.listdir(builds_root), reverse=True)[:10]:
            bdir = os.path.join(builds_root, name)
            if not os.path.isdir(bdir):
                continue
            bj = _load(os.path.join(bdir, "build.json")) or {}
            rep = _load(os.path.join(bdir, "build_report.json")) or {}
            prov = _load(os.path.join(bdir, "build_provenance.json")) or {}
            cache = prov.get("cache") if isinstance(prov.get("cache"), dict) else {}
            stations = None
            surveys = rep.get("surveys") if isinstance(rep.get("surveys"), dict) else None
            if surveys is not None:
                try:
                    stations = sum(int(s.get("stations_built") or 0) for s in surveys.values())
                except Exception:
                    stations = None
            builds.append({
                "dir": name,
                "build_id": bj.get("build_id"),
                "engine_commit": bj.get("engine_commit"),
                "source_commit": bj.get("source_commit"),
                "stations": stations,
                "serving": (name == serving_dir),
                # C18-A4 cache forensics live in build_provenance.json's top-level `cache` block —
                # NOT in build.json/build_report.json (verified against build_portal.py). Render what
                # exists; absent keys (a non-incremental build) stay null.
                "cache": {"enabled": cache.get("enabled"), "mode": cache.get("mode"),
                          "salt_fp": cache.get("salt_fp"),
                          "write_errors": cache.get("write_errors"),
                          "read_errors": cache.get("read_errors"),
                          "hits": cache.get("hits"), "misses": cache.get("misses"),
                          "degenerate": cache.get("degenerate"), "reason": cache.get("reason")},
            })

# ---- log tail: newest build log (site-data/logs/*.build.log), last 60 lines ----
logs = {"build": None, "build_file": None}
if site_data:
    logdir = os.path.join(site_data, "logs")
    cands = sorted(glob.glob(os.path.join(logdir, "*.build.log")), reverse=True)
    if cands:
        try:
            with open(cands[0], encoding="utf-8", errors="replace") as fh:
                logs["build"] = "\n".join(fh.read().splitlines()[-60:])
            logs["build_file"] = os.path.basename(cands[0])
        except OSError:
            pass

# ---- pause state (C43 S2b-ii, record D9.7): active + the continuous-span persistence verdict ----
def _f(name):
    v = os.environ.get(name, "")
    return v if v else None
pause = {"active": os.environ.get("AUSMT_OPS_PAUSE_ACTIVE", "") == "1",
         "paused_at": _f("AUSMT_OPS_PAUSE_PAUSED_AT"),
         "first_seen": _f("AUSMT_OPS_PAUSE_FIRST_SEEN"),
         "cumulative_hours": (float(os.environ["AUSMT_OPS_PAUSE_CUMULATIVE_H"])
                              if os.environ.get("AUSMT_OPS_PAUSE_CUMULATIVE_H", "").replace(".", "", 1).isdigit()
                              else None),
         "persistent": os.environ.get("AUSMT_OPS_PAUSE_PERSISTENT", "") == "1",
         "max_hours": int(os.environ.get("AUSMT_OPS_PAUSE_MAX_H") or 24)}

# ---- pending privileged intents + the actions audit tail (C43 S2b-ii, record D8/D9). Read-only
#      surfacing so the serve screen shows what is queued/in-flight and the recent action outcomes;
#      the gateway has no other view of the host actions agent's work. ----
state_dir = os.environ.get("AUSMT_OPS_STATE_DIR") or ""
intents = []
_KNOWN = ("update.request", "backup.request", "rollback.request", "restore.request")
if state_dir and os.path.isdir(state_dir):
    for _n in _KNOWN:
        if os.path.isfile(os.path.join(state_dir, _n)):
            intents.append(_n[:-len(".request")])   # "update"/"backup"/"rollback"/"restore"
audit_tail = []
if state_dir:
    _al = os.path.join(state_dir, "actions-audit.log")
    if os.path.isfile(_al):
        try:
            with open(_al, encoding="utf-8", errors="replace") as fh:
                audit_tail = [ln.rstrip("\n") for ln in fh.read().splitlines()][-40:]
        except OSError:
            pass
actions = {"pending": intents, "audit_tail": audit_tail}

doc = {"generated_at": now, "timer_period_min": int(os.environ.get("AUSMT_OPS_PERIOD_MIN") or 15),
       "reconcile": reconcile, "backups": backups, "alerts": alerts, "box": box,
       "freshness": freshness, "builds": builds, "logs": logs,
       "pause": pause, "actions": actions}
print(json.dumps(doc, indent=1))
PYEOF

  if [ -s "$_tmp" ]; then
    mv -f "$_tmp" "$OPS_STATUS_FILE" 2>/dev/null || { rm -f "$_tmp" 2>/dev/null || true; \
      printf '%s ops-status: mv into place failed\n' "$(date -u +%H:%M:%SZ)" >&2; }
  else
    rm -f "$_tmp" 2>/dev/null || true
    printf '%s ops-status: writer produced no output -- ops-status.json left unchanged\n' "$(date -u +%H:%M:%SZ)" >&2
  fi
}

# --------------------------------------------------------------------------------------------------
# Run every check (each appends to FAILURES; none of them exit — we want ALL failures in one alert).
# These run REGARDLESS of whether alerting is configured: their facts feed BOTH the ping (below) and
# the ops-status.json write (the curator ops floor is independent of the external dead-man monitor).
# --------------------------------------------------------------------------------------------------
check_services
check_disk
check_reconcile
check_backup
check_pause

# Strip the leading blank line add_failure introduces.
SUMMARY="$(printf '%s' "$FAILURES" | sed '/^$/d')"

# --------------------------------------------------------------------------------------------------
# C43 S2b-i: write the ops-status.json for the curator ops floor — EVERY pass, BEFORE the ping and
# BEFORE the not-configured short-circuit, so the floor reflects box state even on a box whose
# external monitor is not yet wired. Best-effort: it never changes the pass's exit code.
#   arg1 = checks_ok (1 when the summary is empty), arg2 = alert_installed (1 when a URL is set).
# --------------------------------------------------------------------------------------------------
if [ -z "$SUMMARY" ]; then _checks_ok=1; else _checks_ok=0; fi
if [ -n "$ALERT_URL" ]; then _alert_installed=1; else _alert_installed=0; fi
write_ops_status "$_checks_ok" "$_alert_installed"

# --------------------------------------------------------------------------------------------------
# Not-configured short-circuit: if AUSMT_ALERT_URL is unset/empty, print ONE loud note and exit 0.
# NEVER fake a ping, NEVER break the timer. This lets the units be installed before the operator has
# created the external check (the runbook order), without the timer flapping. (The ops-status.json
# write above already ran, so the curator floor is populated on an unconfigured box too.)
# --------------------------------------------------------------------------------------------------
if [ -z "$ALERT_URL" ]; then
  printf '%s alert: ALERTING NOT CONFIGURED -- AUSMT_ALERT_URL is unset/empty in the environment.\n' "$(date -u +%H:%M:%SZ)" >&2
  printf 'alert: create the external check + paste its ping URL into deploy/.env as AUSMT_ALERT_URL. See deploy/README.md "Alerting". No ping sent.\n' >&2
  exit 0
fi

if [ -z "$SUMMARY" ]; then
  # ALL OK — send the success beat. -f fails on HTTP >= 400, -sS is quiet but shows errors, -m 10 caps
  # the whole request, --retry 3 rides out a transient blip. A failed success-ping is itself a fault
  # (the box could not reach the monitor) — exit nonzero so the journal shows it, but the monitor's
  # own absent-ping timeout is the ultimate backstop.
  log "all checks OK — sending success ping"
  # shellcheck disable=SC2086 -- CURL_CMD may be a multi-word override (e.g. a test shim `sh shim.sh`).
  if $CURL_CMD -fsS -m 10 --retry 3 "$ALERT_URL" >/dev/null; then
    exit 0
  else
    printf 'alert: success ping to the monitor FAILED (curl error) -- the box could not reach %s. The monitor'"'"'s absent-ping timeout will catch this.\n' "$ALERT_URL" >&2
    exit 1
  fi
fi

# ONE OR MORE FAILURES — send the fail ping with the summary as the body, and exit nonzero so the
# failure is visible in `journalctl -u ausmt-alert.service` too.
log "checks FAILED — sending fail ping:"
printf '%s\n' "$SUMMARY" >&2
# shellcheck disable=SC2086 -- CURL_CMD may be a multi-word override (e.g. a test shim).
$CURL_CMD -fsS -m 10 --retry 3 --data-raw "$SUMMARY" "$ALERT_URL/fail" >/dev/null || \
  printf 'alert: fail ping to %s/fail could not be delivered (curl error) -- the monitor'"'"'s absent-ping timeout is the backstop.\n' "$ALERT_URL" >&2
exit 1
