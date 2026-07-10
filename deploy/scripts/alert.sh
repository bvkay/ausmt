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
#     * action == "failed" (a build/verify failure — the C40 fail-closed state).
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
# Not-configured short-circuit: if AUSMT_ALERT_URL is unset/empty, print ONE loud note and exit 0.
# NEVER fake a ping, NEVER break the timer. This lets the units be installed before the operator has
# created the external check (the runbook order), without the timer flapping.
# --------------------------------------------------------------------------------------------------
if [ -z "$ALERT_URL" ]; then
  printf '%s alert: ALERTING NOT CONFIGURED -- AUSMT_ALERT_URL is unset/empty in the environment.\n' "$(date -u +%H:%M:%SZ)" >&2
  printf 'alert: create the external check + paste its ping URL into deploy/.env as AUSMT_ALERT_URL. See deploy/README.md "Alerting". No ping sent.\n' >&2
  exit 0
fi

# --------------------------------------------------------------------------------------------------
# Run every check (each appends to FAILURES; none of them exit — we want ALL failures in one alert).
# --------------------------------------------------------------------------------------------------
check_services
check_disk
check_reconcile
check_backup

# Strip the leading blank line add_failure introduces.
SUMMARY="$(printf '%s' "$FAILURES" | sed '/^$/d')"

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
