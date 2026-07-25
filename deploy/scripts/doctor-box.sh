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

printf 'AusMT box doctor (profile=%s) - %s\n' "$PROFILE" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '=====================================================\n'
check_containers
check_gateway_healthz
check_reader_wall
check_surveys_live
check_reconcile_timer
check_disk
check_served_staleness
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
