#!/bin/sh
# AusMT serve doctor - one-screen health of the serving replica (ausmt-serve), the host that runs the
# front door and the portal container over a tree it receives by publish. Run it on that host from the
# checkout: `sh deploy/nectar/doctor-serve.sh`. Read-only; it never mutates anything.
#
# Prints ONE labelled PASS / WARN / FAIL line per check and a final summary, and EXITS NON-ZERO if any
# check FAILs, so it can gate a script or an alert; a WARN alone does not fail the exit. No check aborts
# the run: every probe reports and the script always reaches the summary.
#
# CHECKS
#   1. containers: the portal (deploy/compose.yaml) and the front door (deploy/frontdoor/compose.yaml)
#   2. listeners: the portal answers on 127.0.0.1:8443 and the reader on 127.0.0.1:8445
#   3. wall: the reader listener refuses the curator workbench (404), wall 2 proving itself here
#   4. gateway: this host runs no gateway; the front door sends the four public submission routes to
#      the curation host (AUSMT_GATEWAY_UPSTREAM in deploy/frontdoor/.env). GET /gateway/healthz
#      through the front door, by the public name pinned to loopback; anything but 200 is a WARN that
#      names the routes, since readers are served here either way
#   5. volume: the data root is its own mounted volume, never a directory on the root disk
#   6. disk: headroom on the data volume
#   7. current: a symlink to an existing builds/<ts>
#   8. build.json: the served build's identity parses
#   9. published: published.json names the build current points at, with its age and its lag (how
#      long after the build was made the replica swapped to it); absent or disagreeing is a WARN,
#      because the tree still serves but did not arrive by the publish path
#  10. builds: a build directory with no sidecar is a transfer that never completed and that no prune
#      removes; each one is named
#  11. frontdoor: deploy/frontdoor/doctor.sh, its FAIL and WARN lines relayed under this label
#
# CONFIG (env; every command and path is overridable so the checks are testable)
#   AUSMT_DOCTOR_ENV                deploy/.env (default: ../.env relative to this script); sources
#                                   AUSMT_DATA_DIR
#   AUSMT_DOCTOR_COMPOSE            the portal compose file (default: deploy/compose.yaml)
#   AUSMT_DOCTOR_FRONTDOOR_COMPOSE  the front-door compose file (default: deploy/frontdoor/compose.yaml)
#   AUSMT_DOCTOR_FRONTDOOR_ENV      the front-door .env (default: deploy/frontdoor/.env); read, never
#                                   sourced, for AUSMT_PUBLIC_NAME and AUSMT_GATEWAY_UPSTREAM
#   AUSMT_DOCTOR_FRONTDOOR          the front-door doctor command (default: sh deploy/frontdoor/doctor.sh)
#   AUSMT_DOCTOR_DOCKER             docker command (default: docker)
#   AUSMT_DOCTOR_CURL               curl command (default: curl)
#   AUSMT_DOCTOR_MOUNTPOINT         mountpoint command (default: mountpoint)
#   AUSMT_DOCTOR_PYTHON             python command (default: python3)
#   AUSMT_DOCTOR_DISK_WARN_PCT      disk use percent that trips a WARN (default: 85)

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_DIR="$(cd "$HERE/.." && pwd)"

ENV_FILE="${AUSMT_DOCTOR_ENV:-$DEPLOY_DIR/.env}"
COMPOSE_FILE="${AUSMT_DOCTOR_COMPOSE:-$DEPLOY_DIR/compose.yaml}"
FD_COMPOSE_FILE="${AUSMT_DOCTOR_FRONTDOOR_COMPOSE:-$DEPLOY_DIR/frontdoor/compose.yaml}"
FD_ENV_FILE="${AUSMT_DOCTOR_FRONTDOOR_ENV:-$DEPLOY_DIR/frontdoor/.env}"
FRONTDOOR="${AUSMT_DOCTOR_FRONTDOOR:-sh $DEPLOY_DIR/frontdoor/doctor.sh}"
DOCKER="${AUSMT_DOCTOR_DOCKER:-docker}"
CURL="${AUSMT_DOCTOR_CURL:-curl}"
MOUNTPOINT="${AUSMT_DOCTOR_MOUNTPOINT:-mountpoint}"
PYTHON="${AUSMT_DOCTOR_PYTHON:-python3}"
DISK_WARN_PCT="${AUSMT_DOCTOR_DISK_WARN_PCT:-85}"

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
DATA_DIR="${AUSMT_DATA_DIR:-}"
SITE="$DATA_DIR/site-data"

is_ts() {
	case "$1" in
		[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z) return 0 ;;
	esac
	return 1
}

_code() {
	# HTTP status from a loopback listener (empty on no response).
	# shellcheck disable=SC2086 # CURL may be a word-split override.
	$CURL -sS -o /dev/null -w '%{http_code}' --max-time 8 "http://127.0.0.1:$1$2" 2>/dev/null
}

check_containers() {
	# shellcheck disable=SC2086
	portal="$($DOCKER compose -f "$COMPOSE_FILE" ps --status running --services 2>/dev/null)"
	# shellcheck disable=SC2086
	edge="$($DOCKER compose -f "$FD_COMPOSE_FILE" ps --status running --services 2>/dev/null)"
	if printf '%s\n' "$portal" | grep -qx portal; then
		pass "containers: portal is running"
	else
		fail "containers: portal is NOT running (make up in deploy/)"
	fi
	if printf '%s\n' "$edge" | grep -qx frontdoor; then
		pass "containers: frontdoor is running"
	else
		fail "containers: frontdoor is NOT running (./install-frontdoor.sh in deploy/frontdoor/)"
	fi
}

check_listeners() {
	for pair in "8443:the portal" "8445:the reader"; do
		port=${pair%%:*}
		what=${pair#*:}
		code="$(_code "$port" /)"
		if [ "$code" = "200" ]; then
			pass "listeners: $what answers 200 on 127.0.0.1:$port"
		else
			fail "listeners: $what on 127.0.0.1:$port -> ${code:-no-response} (expected 200)"
		fi
	done
}

check_wall() {
	code="$(_code 8445 /gateway/curator/queue)"
	if [ "$code" = "404" ]; then
		pass "wall: the reader listener refuses /gateway/curator/queue (404)"
	else
		fail "wall: WALL 2 BREACH, /gateway/curator/queue -> ${code:-no-response} on the reader listener (expected 404)"
	fi
}

_fd_var() {
	# The last value of $1 in the front-door .env, empty when absent. Read rather than sourced, so no
	# front-door setting leaks into this run or the front-door doctor it starts.
	[ -f "$FD_ENV_FILE" ] || return 0
	sed -n "s/^$1=//p" "$FD_ENV_FILE" | tail -n 1
}

check_gateway() {
	routes="POST /gateway/submit, POST /gateway/request-key, GET /gateway/healthz, GET /gateway/status/*"
	name="$(_fd_var AUSMT_PUBLIC_NAME)"
	if [ -z "$name" ]; then
		warn "gateway: AUSMT_PUBLIC_NAME unset in $FD_ENV_FILE, so the public gateway routes cannot be probed through the front door"
		return
	fi
	# shellcheck disable=SC2086 # CURL may be a word-split override.
	code="$($CURL -sS -o /dev/null -w '%{http_code}' --max-time 8 --resolve "$name:443:127.0.0.1" "https://$name/gateway/healthz" 2>/dev/null)"
	if [ "$code" = "200" ]; then
		pass "gateway: /gateway/healthz answers 200 through the front door"
	elif [ -z "$(_fd_var AUSMT_GATEWAY_UPSTREAM)" ]; then
		warn "gateway: /gateway/healthz -> ${code:-no-response}; AUSMT_GATEWAY_UPSTREAM is unset in $FD_ENV_FILE, so the front door sends $routes to this host's reader, which has no gateway; set it to the curation host's reader listener and re-run install-frontdoor.sh (readers are unaffected)"
	else
		warn "gateway: /gateway/healthz -> ${code:-no-response} through the front door; the curation host's reader listener ($(_fd_var AUSMT_GATEWAY_UPSTREAM)) is not answering, so $routes are down at the public name (readers are unaffected)"
	fi
}

check_volume() {
	if $MOUNTPOINT -q "$DATA_DIR" 2>/dev/null; then
		pass "volume: $DATA_DIR is its own mounted volume"
	else
		fail "volume: $DATA_DIR is NOT a mount point, so the tree sits on the root disk and would vanish behind the volume once it mounts (deploy/nectar/RUNBOOK-NECTAR.md, the volume step)"
	fi
	usep="$(df -P "$DATA_DIR" 2>/dev/null | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
	if [ -z "$usep" ]; then
		warn "disk: could not read usage for $DATA_DIR"
	elif [ "$usep" -ge "$DISK_WARN_PCT" ] 2>/dev/null; then
		warn "disk: $DATA_DIR is ${usep}% full (>= warn threshold ${DISK_WARN_PCT}%); lower AUSMT_PUBLISH_KEEP on the sender or grow the volume"
	else
		pass "disk: $DATA_DIR is ${usep}% full (under ${DISK_WARN_PCT}%)"
	fi
}

CUR_TS=""
check_current() {
	if [ ! -L "$SITE/current" ]; then
		if [ -e "$SITE/current" ]; then
			fail "current: $SITE/current is not a symlink, so no build can be swapped in over it"
		else
			fail "current: $SITE/current does not exist (no build has been received)"
		fi
		return
	fi
	target="$(readlink "$SITE/current")"
	name=${target#builds/}
	if [ "$target" != "builds/$name" ] || ! is_ts "$name" || [ ! -d "$SITE/builds/$name" ]; then
		fail "current: current -> $target, which is not an existing builds/<timestamp>"
		return
	fi
	CUR_TS="$name"
	pass "current -> builds/$name"
}

check_build_json() {
	[ -n "$CUR_TS" ] || return 0
	ident="$("$PYTHON" - "$SITE/builds/$CUR_TS/build.json" <<'PYEOF' 2>/dev/null
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    doc = json.load(fh)
print("build_id=%s source_commit=%s" % (doc.get("build_id"), doc.get("source_commit")))
PYEOF
)"
	if [ -n "$ident" ]; then
		pass "build.json: $ident"
	else
		fail "build.json: builds/$CUR_TS/build.json is missing or does not parse, so the served identity is unknown"
	fi
}

check_published() {
	[ -n "$CUR_TS" ] || return 0
	if [ ! -f "$SITE/published.json" ]; then
		warn "published.json: absent, so this replica has never taken a publish and current arrived by hand"
		return
	fi
	read_out="$(AUSMT_DS_CUR="$CUR_TS" "$PYTHON" - "$SITE/published.json" <<'PYEOF' 2>/dev/null
import datetime, json, os, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    doc = json.load(fh)
ts = doc.get("ts") or ""
at = doc.get("received_at") or ""
utc = datetime.timezone.utc
def span(seconds):
    m = int(seconds // 60)
    return "%dh%02dm" % (m // 60, m % 60) if m >= 60 else "%dm" % m
try:
    got = datetime.datetime.strptime(at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=utc)
    built = datetime.datetime.strptime(ts, "%Y%m%dT%H%M%SZ").replace(tzinfo=utc)
    now = datetime.datetime.now(utc)
    print("%s|%s|age %s, lag %s after the build" % (ts, at, span((now - got).total_seconds()),
                                                    span((got - built).total_seconds())))
except ValueError:
    print("%s|%s|age and lag unreadable" % (ts, at))
PYEOF
)"
	if [ -z "$read_out" ]; then
		warn "published.json: does not parse"
		return
	fi
	pts=${read_out%%|*}
	rest=${read_out#*|}
	at=${rest%%|*}
	span=${rest#*|}
	if [ "$pts" != "$CUR_TS" ]; then
		warn "published: published.json names builds/$pts but current is builds/$CUR_TS, so current was swapped outside the publish path"
	else
		pass "published: builds/$pts received $at ($span)"
	fi
}

check_inflight() {
	[ -d "$SITE/builds" ] || return 0
	found=0
	for d in "$SITE"/builds/*; do
		[ -d "$d" ] || continue
		name=${d##*/}
		is_ts "$name" || continue
		[ "$name" = "$CUR_TS" ] && continue
		if [ ! -f "$SITE/builds/$name.sha256" ]; then
			warn "builds: builds/$name has no sidecar, a transfer that never completed; no prune removes it, so delete it once no publish is running"
			found=1
		fi
	done
	[ "$found" -eq 1 ] || pass "builds: every retained build carries its sidecar"
}

check_frontdoor() {
	# The front-door doctor reads AUSMT_DOCTOR_ENV and AUSMT_DOCTOR_COMPOSE under the same names with
	# its own meaning (its .env, its compose file), so neither may leak into it from this run.
	# shellcheck disable=SC2086 # FRONTDOOR is a word-split command.
	out="$(cd "$DEPLOY_DIR/frontdoor" 2>/dev/null && env -u AUSMT_DOCTOR_ENV -u AUSMT_DOCTOR_COMPOSE $FRONTDOOR 2>&1)"
	rc=$?
	relayed=0
	while IFS= read -r line; do
		case "$line" in
			"FAIL "*) fail "frontdoor: ${line#FAIL }"; relayed=1 ;;
			"WARN "*) warn "frontdoor: ${line#WARN }" ;;
		esac
	done <<EOF
$out
EOF
	if [ "$rc" -eq 0 ]; then
		pass "frontdoor: the front-door doctor passes"
	elif [ "$relayed" -eq 0 ]; then
		fail "frontdoor: the front-door doctor exited $rc without a FAIL line"
	fi
}

printf 'AusMT serve doctor (serving replica) - %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '=====================================================\n'
check_containers
check_listeners
check_wall
check_gateway
if [ -z "$DATA_DIR" ]; then
	fail "config: AUSMT_DATA_DIR is not set in $ENV_FILE, so the data checks cannot run"
else
	check_volume
	check_current
	check_build_json
	check_published
	check_inflight
fi
check_frontdoor
printf '=====================================================\n'
if [ "$FAILS" -gt 0 ]; then
	printf 'RESULT: FAIL (%s failed, %s warned) - see deploy/nectar/RUNBOOK-NECTAR.md.\n' "$FAILS" "$WARNS"
	exit 1
fi
if [ "$WARNS" -gt 0 ]; then
	printf 'RESULT: PASS with %s warning(s) - no hard failure, but review the WARN lines.\n' "$WARNS"
	exit 0
fi
printf 'RESULT: PASS - the serving replica is healthy.\n'
exit 0
