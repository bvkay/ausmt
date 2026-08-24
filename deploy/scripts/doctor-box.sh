#!/bin/sh
# AusMT box doctor (ops-hardening O4) — one-screen health of the box (the EliteDesk that builds and
# serves the corpus). Invoked as `make doctor` (or `make doctor PROFILE=gateway`), or directly.
#
# Prints ONE labelled PASS / WARN / FAIL line per check and a final summary. Exits NON-ZERO if any check
# FAILs, so it can gate a script or an alert; a WARN alone does not fail the exit. No check aborts the
# run — every probe reports honestly and the script always reaches the summary.
#
# CHECKS:
#   1. containers up for the active profile (portal always; gateway/clamd/gw-runner when PROFILE=gateway)
#   2. gateway healthz (only when the gateway profile is active)
#   3. the box reader wall on loopback :8445 answers the public subset (200) and refuses the curator
#      workbench (404) — wall 2 proving itself locally
#   4. surveys-live is a clean git checkout, group-writable, with an ACL present (the recurring perms trap)
#   5. the serve-reconcile timer is installed, enabled, and has a recent last-run (the agent that should
#      serve a publish automatically — its absence is a live suspect for a stale wall)
#   6. disk headroom on the data dir
#   7. the served-build source_commit vs surveys-live HEAD (a staleness hint: served != published)
#   7b. TS-ROUTE KEY-SET PARITY: the committed deploy/frontdoor/ts-routes.map (the VPS's hand-off
#      table) and the SERVED /data/ts_access.json name the same (station, level) set. The table lives
#      on the VPS and the data here, so a withheld flip is suppressed only once the table is
#      regenerated, committed and installed - this is the line that says the two have not drifted
#   8. the kernel journal for out-of-memory KILLS in the last 24 h (incident 2026-08-15: the engine
#      build was OOM-killed five nights running and every one surfaced only as "rebuild FAILED"; the
#      kernel line naming the process, its uid and its size is the fact an operator needs, so this
#      check reads it and says it by name; WARN when the journal is unreadable, never a silent PASS)
#
# CONFIG (env; overridable for testability + portability):
#   AUSMT_DOCTOR_ENV        path to deploy/.env (default: ../.env relative to this script) — sources
#                           AUSMT_DATA_DIR, AUSMT_CODE_DIR, OWNER, TAG
#   AUSMT_DOCTOR_COMPOSE    compose file (default: deploy/compose.yaml)
#   PROFILE                 portal (default) or gateway — selects the gateway container + healthz checks
#   AUSMT_DOCTOR_DOCKER     docker command       (default: docker)
#   AUSMT_DOCTOR_CURL       curl command         (default: curl)
#   AUSMT_DOCTOR_SYSTEMCTL  systemctl command    (default: systemctl)
#   AUSMT_DOCTOR_GIT        git command          (default: git)
#   AUSMT_DOCTOR_GETFACL    getfacl command      (default: getfacl)
#   AUSMT_DOCTOR_READER_PORT the loopback reader/public-subset port (default: 8445)
#   AUSMT_DOCTOR_RECONCILE_TIMER the timer unit name (default: ausmt-reconcile.timer)
#   AUSMT_DOCTOR_DISK_WARN_PCT disk use percent that trips a WARN (default: 85)
#   AUSMT_DOCTOR_JOURNALCTL journalctl command (default: journalctl) - the kernel-journal OOM check
#   AUSMT_DOCTOR_PYTHON     python command (default: python3) - the ts-route key-set parity check
#   AUSMT_DOCTOR_OOM_SINCE  journalctl --since window for the OOM check (default: -24h)

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_DIR="$(cd "$HERE/.." && pwd)"

ENV_FILE="${AUSMT_DOCTOR_ENV:-$DEPLOY_DIR/.env}"
COMPOSE_FILE="${AUSMT_DOCTOR_COMPOSE:-$DEPLOY_DIR/compose.yaml}"
DOCKER="${AUSMT_DOCTOR_DOCKER:-docker}"
CURL="${AUSMT_DOCTOR_CURL:-curl}"
SYSTEMCTL="${AUSMT_DOCTOR_SYSTEMCTL:-systemctl}"
GIT="${AUSMT_DOCTOR_GIT:-git}"
GETFACL="${AUSMT_DOCTOR_GETFACL:-getfacl}"
READER_PORT="${AUSMT_DOCTOR_READER_PORT:-8445}"
RECONCILE_TIMER="${AUSMT_DOCTOR_RECONCILE_TIMER:-ausmt-reconcile.timer}"
DISK_WARN_PCT="${AUSMT_DOCTOR_DISK_WARN_PCT:-85}"
JOURNALCTL="${AUSMT_DOCTOR_JOURNALCTL:-journalctl}"
PYTHON="${AUSMT_DOCTOR_PYTHON:-python3}"
OOM_SINCE="${AUSMT_DOCTOR_OOM_SINCE:--24h}"
PROFILE="${PROFILE:-portal}"

FAILS=0
WARNS=0
pass() { printf 'PASS %s\n' "$*"; }
warn() { printf 'WARN %s\n' "$*"; WARNS=$((WARNS + 1)); }
fail() { printf 'FAIL %s\n' "$*"; FAILS=$((FAILS + 1)); }

if [ -f "$ENV_FILE" ]; then
	set -a
	# shellcheck disable=SC1090
	. "$ENV_FILE"
	set +a
fi

_reader_code() {
	# HTTP status from the loopback reader listener for a given path (empty on no response).
	$CURL -sS -o /dev/null -w '%{http_code}' --max-time 8 "http://127.0.0.1:$READER_PORT$1" 2>/dev/null
}

check_containers() {
	running="$($DOCKER compose -f "$COMPOSE_FILE" ps --status running --services 2>/dev/null)"
	if [ -z "$running" ]; then
		fail "containers: nothing running (docker compose up -d) for profile $PROFILE"
		return
	fi
	if printf '%s\n' "$running" | grep -qx portal; then
		pass "containers: portal is running"
	else
		fail "containers: portal is NOT running (the always-on reader service)"
	fi
	if [ "$PROFILE" = "gateway" ]; then
		for svc in gateway clamd; do
			if printf '%s\n' "$running" | grep -qx "$svc"; then
				pass "containers: $svc is running (gateway profile)"
			else
				fail "containers: $svc is NOT running (gateway profile is active)"
			fi
		done
	fi
}

check_gateway_healthz() {
	if [ "$PROFILE" != "gateway" ]; then
		return
	fi
	code="$(_reader_code /gateway/healthz)"
	if [ "$code" = "200" ]; then
		pass "gateway: /gateway/healthz answers 200 through the reader listener"
	else
		fail "gateway: /gateway/healthz -> ${code:-no-response} (expected 200 with the gateway profile up)"
	fi
}

check_reader_wall() {
	# Wall 2 spot-checks on the loopback public-subset listener: the public subset must serve, the
	# curator workbench must refuse.
	root="$(_reader_code /)"
	addsurvey="$(_reader_code /add-survey.html)"
	curator="$(_reader_code /gateway/curator/queue)"
	if [ "$root" = "200" ]; then
		pass "reader: / -> 200 (reader serving on :$READER_PORT)"
	else
		fail "reader: / -> ${root:-no-response} (the reader listener is not answering on :$READER_PORT)"
	fi
	if [ "$addsurvey" = "200" ]; then
		pass "reader: /add-survey.html -> 200 (public contribution page served)"
	else
		fail "reader: /add-survey.html -> ${addsurvey:-no-response} (expected 200, the public page)"
	fi
	if [ "$curator" = "404" ]; then
		pass "reader: /gateway/curator/queue -> 404 (wall 2 refuses the workbench)"
	else
		fail "reader: /gateway/curator/queue -> ${curator:-no-response} (expected 404 - WALL 2 BREACH if served)"
	fi
}

check_surveys_live() {
	data="${AUSMT_DATA_DIR:-}"
	if [ -z "$data" ]; then
		warn "surveys-live: AUSMT_DATA_DIR unset in $ENV_FILE (cannot locate the checkout)"
		return
	fi
	sl="$data/surveys-live"
	if [ ! -d "$sl/.git" ]; then
		fail "surveys-live: $sl is not a git checkout (.git missing) - the reconcile agent cannot pull"
		return
	fi
	# Clean: no modified/untracked entries. An untracked survey dir is the incident-2026-07-11 class
	# (built + served but git can never remove it).
	dirty="$($GIT -C "$sl" status --porcelain 2>/dev/null)"
	if [ -z "$dirty" ]; then
		pass "surveys-live: git checkout is clean (no local edits or untracked entries)"
	else
		fail "surveys-live: checkout is DIRTY - local edits/untracked entries would be built + served: $(printf '%s' "$dirty" | tr '\n' ';' | head -c 160)"
	fi
	# Group-writable: the shared-group publish model. A .git that has lost g+w locks the operator out of
	# git pull after a gateway (uid 10002) publish (incident 2026-07-11).
	if [ -w "$sl/.git" ] && [ "$( (ls -ld "$sl/.git" 2>/dev/null | cut -c6) )" = "w" ]; then
		pass "surveys-live: .git is group-writable (shared-group publish model)"
	else
		fail "surveys-live: .git is NOT group-writable - a gateway publish will lock the operator out of git pull (git config core.sharedRepository group + chmod -R g+w)"
	fi
	shared="$($GIT -C "$sl" config core.sharedRepository 2>/dev/null)"
	if [ "$shared" = "group" ] || [ "$shared" = "1" ] || [ "$shared" = "true" ]; then
		pass "surveys-live: core.sharedRepository=group is set"
	else
		warn "surveys-live: core.sharedRepository is '${shared:-unset}' (want group - new git objects may drop g+w)"
	fi
	# ACL present: the recurring perms trap. A default group ACL keeps new files group-writable.
	if command -v "$GETFACL" >/dev/null 2>&1; then
		if $GETFACL -p "$sl" 2>/dev/null | grep -qE '^default:group:|^default:mask:'; then
			pass "surveys-live: a default group ACL is present on the checkout"
		else
			warn "surveys-live: no default group ACL on $sl (setfacl -R -d -m g::rwX to keep new files group-writable)"
		fi
	else
		warn "surveys-live: getfacl unavailable, cannot verify the default group ACL"
	fi
}

check_reconcile_timer() {
	# Installed + enabled.
	if ! $SYSTEMCTL list-unit-files "$RECONCILE_TIMER" >/dev/null 2>&1 \
		|| ! $SYSTEMCTL list-unit-files "$RECONCILE_TIMER" 2>/dev/null | grep -q "$RECONCILE_TIMER"; then
		fail "reconcile: $RECONCILE_TIMER is NOT installed - a publish will not be served automatically (install it, RUNBOOK/deploy README)"
		return
	fi
	enabled="$($SYSTEMCTL is-enabled "$RECONCILE_TIMER" 2>/dev/null)"
	if [ "$enabled" = "enabled" ]; then
		pass "reconcile: $RECONCILE_TIMER is installed and enabled"
	else
		fail "reconcile: $RECONCILE_TIMER is installed but NOT enabled (state=${enabled:-unknown}) - enable --now it"
	fi
	# Last-run: the timer's LastTriggerUSec, or the service's last result. A never-run timer is a suspect.
	lasttrig="$($SYSTEMCTL show "$RECONCILE_TIMER" -p LastTriggerUSec --value 2>/dev/null)"
	if [ -n "$lasttrig" ] && [ "$lasttrig" != "0" ] && [ "$lasttrig" != "n/a" ]; then
		pass "reconcile: last run was $lasttrig"
	else
		warn "reconcile: timer has no recorded last-run yet (fresh install, or it has never fired - watch it)"
	fi
}

check_disk() {
	path="${AUSMT_DATA_DIR:-/}"
	usep="$(df -P "$path" 2>/dev/null | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
	if [ -z "$usep" ]; then
		warn "disk: could not read usage for $path"
		return
	fi
	if [ "$usep" -ge "$DISK_WARN_PCT" ] 2>/dev/null; then
		warn "disk: $path is ${usep}% full (>= ${DISK_WARN_PCT}%)"
	else
		pass "disk: $path is ${usep}% full (under ${DISK_WARN_PCT}%)"
	fi
}

check_served_staleness() {
	data="${AUSMT_DATA_DIR:-}"
	if [ -z "$data" ]; then
		return
	fi
	bj="$data/site-data/current/build.json"
	sl="$data/surveys-live"
	if [ ! -f "$bj" ]; then
		warn "served: no build.json at $bj (nothing served yet, or current symlink missing)"
		return
	fi
	# source_commit is a short hash or null; pull it out without a JSON parser (staleness HINT only).
	served="$(grep -o '"source_commit"[[:space:]]*:[[:space:]]*"[^"]*"' "$bj" 2>/dev/null | sed 's/.*"\([^"]*\)"$/\1/')"
	generated="$(grep -o '"generated"[[:space:]]*:[[:space:]]*"[^"]*"' "$bj" 2>/dev/null | sed 's/.*"\([^"]*\)"$/\1/')"
	if [ -z "$served" ]; then
		warn "served: build.json has no source_commit (a --raw or non-git build) - cannot compare to HEAD (built ${generated:-unknown})"
		return
	fi
	head="$($GIT -C "$sl" rev-parse --short HEAD 2>/dev/null)"
	if [ -z "$head" ]; then
		warn "served: cannot read surveys-live HEAD to compare against the served commit $served"
		return
	fi
	# Prefix-compare in both directions (the stored short hash may be a different length than rev-parse).
	case "$head" in "$served"*) match=1 ;; *) case "$served" in "$head"*) match=1 ;; *) match=0 ;; esac ;; esac
	if [ "$match" = "1" ]; then
		pass "served: built commit $served matches surveys-live HEAD (built ${generated:-unknown})"
	else
		warn "served: built commit $served is BEHIND surveys-live HEAD $head - a publish has not been served yet (reconcile timer should catch it; built ${generated:-unknown})"
	fi
}

check_ts_route_parity() {
	# THE DRIFT THIS SHAPE CREATES, and the one line that catches it: the ROUTE TABLE lives on the VPS
	# (deploy/frontdoor/ts-routes.map, committed) while the DATA lives here, so a withheld flip is
	# suppressed only once the table is regenerated, committed and installed. Both renderings come from
	# ONE projection, so their (station, level) key sets must be EQUAL: a route that resolves for a
	# station the data does not publish is the R5 leak, and a published route that 404s is a broken
	# hand-off. Compared against the SERVED artifact on the reader port rather than a file on disk:
	# what is served is what the public gets.
	code_dir="${AUSMT_CODE_DIR:-}"
	if [ -z "$code_dir" ]; then
		warn "ts-parity: AUSMT_CODE_DIR unset in $ENV_FILE (cannot find the committed route table)"
		return
	fi
	map="$code_dir/deploy/frontdoor/ts-routes.map"
	if [ ! -f "$map" ]; then
		warn "ts-parity: no route table at $map - this checkout publishes no /go/ts/ hand-off routes"
		return
	fi
	tsa="$($CURL -sS --max-time 8 "http://127.0.0.1:$READER_PORT/data/ts_access.json" 2>/dev/null)"
	if [ -z "$tsa" ]; then
		# ts_access.json is emitted ONLY when non-empty, so its absence is a legitimate state (no
		# verified routes in this corpus). It is a FAIL only when the table claims routes anyway.
		if grep -q '^"/go/ts/' "$map" 2>/dev/null; then
			fail "ts-parity: the route table names routes but the reader serves no /data/ts_access.json - the table is AHEAD of the data (regenerate, or publish)"
		else
			pass "ts-parity: no hand-off routes published and none served (both empty)"
		fi
		return
	fi
	if ! command -v "$PYTHON" >/dev/null 2>&1; then
		warn "ts-parity: no $PYTHON on this host - cannot compare the route table to the served ts_access.json"
		return
	fi
	tmp_json="$(mktemp)" || { warn "ts-parity: mktemp failed (cannot stage the served artifact)"; return; }
	printf '%s' "$tsa" > "$tmp_json"
	out="$($PYTHON - "$map" "$tmp_json" 2>/dev/null <<'PY'
import json, sys
table = set()
for line in open(sys.argv[1], encoding="utf-8"):
    if not line.startswith('"/go/ts/'):
        continue
    p = line.split('" "')[0][1:].split("/")
    table.add(("au.%s.%s" % (p[3], p[4]), p[5]))
try:
    doc = json.load(open(sys.argv[2], encoding="utf-8"))
    served = {(aid, lvl) for aid, levels in doc.items() for lvl in levels}
except Exception as e:
    print("ERR %s" % e); raise SystemExit(0)
if table == served:
    print("OK %d" % len(table))
else:
    print("DIFF route-only=%s data-only=%s" % (sorted(table - served)[:3], sorted(served - table)[:3]))
PY
)"
	rm -f "$tmp_json"
	case "$out" in
		OK*) pass "ts-parity: route table and served ts_access.json name the same routes (${out#OK })" ;;
		DIFF*) fail "ts-parity: route table and served ts_access.json DISAGREE - ${out#DIFF } (regenerate the table with deploy/scripts/gen_ts_routes.py --write, ship it to the VPS FIRST, then publish)" ;;
		*) warn "ts-parity: could not compare the route table to the served ts_access.json (${out:-no output})" ;;
	esac
}

check_oom_kills() {
	# The kernel's own record of a process it killed for memory: `journalctl -k` lines of the form
	# "Out of memory: Killed process 398616 (python) total-vm:..., anon-rss:13740244kB, ... UID:10001".
	# Match the modern "Killed process", the older "Kill process" and a docker cgroup "Memory cgroup out
	# of memory" alike. FAIL (not WARN) when a kill is present: a build that cannot complete needs an
	# operator today, and this is the line that says what to do (RAM/swap, or the engine's memory bound
	# has regressed - see build_report.json peak_rss_mib and engine/tests/test_build_memory.py).
	if ! command -v "$JOURNALCTL" >/dev/null 2>&1; then
		warn "oom: no journalctl on this host - cannot check the kernel journal for out-of-memory kills (a killed build would surface only as 'rebuild FAILED')"
		return
	fi
	# No -q: on modern systemd a user outside systemd-journal/adm whose OWN journal is readable gets exit
	# 0 and an EMPTY kernel view, and the only sign is journalctl's stderr hint ("You are currently not
	# seeing messages from other users and the system ... Pass -q to turn off this notice"). With -q that
	# hint is suppressed and an unread journal is indistinguishable from a quiet kernel (a false PASS over
	# the very incident this check exists for). So stderr is kept and read: a non-zero exit OR the hint
	# means unreadable => WARN naming the fix. A kill line that IS present wins over the hint.
	out="$($JOURNALCTL -k --since "$OOM_SINCE" --no-pager -o short-iso 2>&1)"
	jrc=$?
	kills="$(printf '%s\n' "$out" | grep -E 'ut of memory: Kill(ed)? process' | tail -n 3)"
	if [ -n "$kills" ]; then
		n="$(printf '%s\n' "$kills" | grep -c .)"
		fail "oom: the KERNEL KILLED $n process(es) FOR RUNNING OUT OF MEMORY in the last ${OOM_SINCE#-} - a build that was running then did not fail, it was killed: $(printf '%s' "$kills" | tr '\n' ' | ')"
		return
	fi
	me="$(id -un 2>/dev/null || echo '?')"
	if [ "$jrc" -ne 0 ]; then
		warn "oom: cannot read the kernel journal (journalctl -k exited $jrc: $(printf '%s' "$out" | grep -v '^$' | head -n 2 | tr '\n' ' ')) - add this user to the systemd-journal group (sudo usermod -aG systemd-journal $me, then re-login) so OOM kills are visible here and to the reconcile agent"
		return
	fi
	if printf '%s\n' "$out" | grep -qiE 'not seeing messages from|insufficient permissions|No journal files were found|Permission denied'; then
		hint="$(printf '%s' "$out" | grep -iE 'not seeing messages from|insufficient permissions|No journal files were found|Permission denied' | head -n 1)"
		warn "oom: the kernel journal is NOT readable by this user (journalctl -k said: $hint) so an OOM kill would be INVISIBLE here - add this user to the systemd-journal group (sudo usermod -aG systemd-journal $me, then re-login) so OOM kills are visible here and to the reconcile agent"
		return
	fi
	pass "oom: no kernel out-of-memory kills in the last ${OOM_SINCE#-}"
}

printf 'AusMT box doctor (profile=%s) - %s\n' "$PROFILE" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '=====================================================\n'
check_containers
check_gateway_healthz
check_reader_wall
check_surveys_live
check_reconcile_timer
check_disk
check_served_staleness
check_ts_route_parity
check_oom_kills
printf '=====================================================\n'
if [ "$FAILS" -gt 0 ]; then
	printf 'RESULT: FAIL (%s failed, %s warned) - the box needs attention. See deploy/README.md.\n' "$FAILS" "$WARNS"
	exit 1
fi
if [ "$WARNS" -gt 0 ]; then
	printf 'RESULT: PASS with %s warning(s) - no hard failure, but review the WARN lines.\n' "$WARNS"
	exit 0
fi
printf 'RESULT: PASS - the box is healthy.\n'
exit 0
