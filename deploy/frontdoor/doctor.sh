#!/bin/sh
# AusMT front-door doctor (ops-hardening O4) — one-screen health of the VPS public edge.
#
# Runs ON THE VPS, from deploy/frontdoor/. Prints ONE labelled PASS / WARN / FAIL line per check and a
# final summary. Exits NON-ZERO if any check FAILs, so it can gate a script or a cron alert; a WARN
# alone does not fail the exit (it is a heads-up, e.g. a cert inside its renewal window). No check
# aborts the run — every probe reports honestly and the script always reaches the summary.
#
# The default run covers the whole edge:
#   1. frontdoor container is up
#   2. the RUNNING edge config matches a FRESH RENDER of the repo Caddyfile (install-frontdoor.sh
#      mounts Caddyfile.rendered, the repo template with the legacy redirect block templated in or
#      out on AUSMT_LEGACY_REDIRECT_NAME; this check re-renders the same way and hash-compares the
#      container-mounted file against it, catching the O1 stale-config trap: a template that changed
#      on disk while the container kept an old rendering / an uncommitted hand-edit on the VPS)
#   3. the box reader upstream is reachable over the tailnet (curl AUSMT_BOX_READER_UPSTREAM)
#   4. the public TLS certificate is present and not near expiry
#   4b. when AUSMT_LEGACY_REDIRECT_NAME is set: the LEGACY certificate is present and not near
#       expiry (a missing legacy certificate is a FAIL, not a WARN: the redirect contract is down),
#       and the legacy name answers the EXPLICIT HTTPS leg with a 301 to the canonical name, path
#       preserved (probed on /data/mtcat.schema.json, the pre-migration schema $id, so the old
#       identifier is proven to keep resolving; the https:// probe means Caddy's automatic
#       HTTP->HTTPS hop can never be what passes the check). When the var is unset both legacy legs
#       are SKIPPED, not failed.
#   5. tailscale is up and the box peer is visible
#   6. the zombie-process count is under the warn threshold (see the `zombies` subcommand for the kit)
#   7. disk headroom on the data path
#   8. the public DNS A record still resolves to THIS host
#
# SUBCOMMANDS:
#   ./doctor.sh            run the full report (default)
#   ./doctor.sh zombies    the O3 zombie-diagnosis kit: count Z-state processes, GROUP them by parent
#                          so the leaking parent is NAMED, and print the likely fixes. Read-only.
#
# CONFIG (env; every external command + path is overridable so the checks are testable and portable):
#   AUSMT_DOCTOR_ENV         path to the front-door .env (default: ./.env) - sources AUSMT_PUBLIC_NAME,
#                            AUSMT_BOX_READER_UPSTREAM and (optional) AUSMT_LEGACY_REDIRECT_NAME
#   AUSMT_DOCTOR_CADDYFILE   the repo Caddyfile to hash the running config against (default: ./Caddyfile)
#   AUSMT_DOCTOR_COMPOSE     the compose file (default: ./compose.yaml)
#   AUSMT_DOCTOR_DOCKER      the docker command            (default: docker)
#   AUSMT_DOCTOR_CURL        the curl command              (default: curl)
#   AUSMT_DOCTOR_TAILSCALE   the tailscale command         (default: tailscale)
#   AUSMT_DOCTOR_OPENSSL     the openssl command           (default: openssl)
#   AUSMT_DOCTOR_DIG         the DNS lookup command         (default: dig)
#   AUSMT_DOCTOR_PS          the ps command                (default: ps)
#   AUSMT_DOCTOR_DISK_PATH   the path to check for headroom (default: /var/lib/docker)
#   AUSMT_DOCTOR_ZOMBIE_WARN zombie count that trips a WARN (default: 50)
#   AUSMT_DOCTOR_CERT_WARN_DAYS  cert days-to-expiry that trips a WARN (default: 21)
#   AUSMT_DOCTOR_DISK_WARN_PCT   disk use percent that trips a WARN (default: 85)
#   AUSMT_DOCTOR_EXPECT_IP    the VPS public IP the DNS record should resolve to. If unset the DNS check
#                             WARNs (it cannot verify the target without knowing this host's public IP).

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"

# ----- config + command handles ------------------------------------------------------------------
ENV_FILE="${AUSMT_DOCTOR_ENV:-$HERE/.env}"
CADDYFILE_REPO="${AUSMT_DOCTOR_CADDYFILE:-$HERE/Caddyfile}"
COMPOSE_FILE="${AUSMT_DOCTOR_COMPOSE:-$HERE/compose.yaml}"
DOCKER="${AUSMT_DOCTOR_DOCKER:-docker}"
CURL="${AUSMT_DOCTOR_CURL:-curl}"
TAILSCALE="${AUSMT_DOCTOR_TAILSCALE:-tailscale}"
OPENSSL="${AUSMT_DOCTOR_OPENSSL:-openssl}"
DIG="${AUSMT_DOCTOR_DIG:-dig}"
PS="${AUSMT_DOCTOR_PS:-ps}"
DISK_PATH="${AUSMT_DOCTOR_DISK_PATH:-/var/lib/docker}"
ZOMBIE_WARN="${AUSMT_DOCTOR_ZOMBIE_WARN:-50}"
CERT_WARN_DAYS="${AUSMT_DOCTOR_CERT_WARN_DAYS:-21}"
DISK_WARN_PCT="${AUSMT_DOCTOR_DISK_WARN_PCT:-85}"

FAILS=0
WARNS=0

pass() { printf 'PASS %s\n' "$*"; }
warn() { printf 'WARN %s\n' "$*"; WARNS=$((WARNS + 1)); }
fail() { printf 'FAIL %s\n' "$*"; FAILS=$((FAILS + 1)); }

# sha256 of a file, first field only, portable across coreutils (sha256sum) and BSD/macOS (shasum).
_sha256() {
	if command -v sha256sum >/dev/null 2>&1; then
		sha256sum "$1" 2>/dev/null | awk '{print $1}'
	elif command -v shasum >/dev/null 2>&1; then
		shasum -a 256 "$1" 2>/dev/null | awk '{print $1}'
	else
		printf ''
	fi
}

# Load AUSMT_PUBLIC_NAME + AUSMT_BOX_READER_UPSTREAM from the front-door .env if present (best effort;
# the checks that need them WARN honestly when a value is missing rather than dying).
if [ -f "$ENV_FILE" ]; then
	set -a
	# shellcheck disable=SC1090
	. "$ENV_FILE"
	set +a
fi

# =================================================================================================
# O3 zombie-diagnosis kit — count Z-state procs, GROUP by parent to NAME the leaker, list the fixes.
# =================================================================================================
# Shared by the `zombies` subcommand (full kit) and the default report's check 6 (count only). Reads
# ps once. Reaped zombies vanish, so a nonzero count means a parent that has not wait()ed for its dead
# children — the fix is almost always at that PARENT, which is why we group by it and print its command.
zombie_lines() {
	# stat ppid comm, no header. A zombie's state field starts with 'Z' (Linux) — the same on the VPS's
	# procps ps and BSD/macOS ps, so the filter is portable. Overridable ps for hermetic testing.
	$PS -eo stat=,ppid=,comm= 2>/dev/null | awk '$1 ~ /^Z/ {print $2, $3}'
}

zombie_count() {
	# grep -c always prints a count (0 when none) even though it exits 1 on no match, so capture it
	# directly — a `|| printf 0` fallback would DOUBLE-emit on the zero case.
	n="$(zombie_lines | grep -c . 2>/dev/null)"
	[ -n "$n" ] || n=0
	printf '%s' "$n"
}

zombie_kit() {
	printf 'AusMT front-door zombie-diagnosis kit (O3)\n'
	printf '===========================================\n'
	n="$(zombie_count)"
	printf 'Z-state (zombie) processes right now: %s  (warn threshold: %s)\n\n' "$n" "$ZOMBIE_WARN"
	if [ "$n" -eq 0 ] 2>/dev/null; then
		printf 'No zombies. Nothing to diagnose. (If the process table was exhausted earlier, a reboot\n'
		printf 'cleared it; re-run this after the next accumulation to catch the leaker in the act.)\n'
		return 0
	fi
	printf 'Zombies grouped by PARENT PID (the leaker is the parent with the most, at the top) - count, ppid, command:\n'
	# Tally zombies per PARENT pid (not per child), heaviest-first, so the TOP line NAMES the leaker: the
	# one parent accumulating defunct children because it never wait()s for them.
	zombie_lines | awk '{print $1}' | sort | uniq -c | sort -rn | while read -r count ppid; do
		# Resolve the parent's own command line for a human-readable name (best effort).
		pcmd="$($PS -o args= -p "$ppid" 2>/dev/null | head -c 100)"
		printf '  %5s  ppid=%-8s [parent: %s]\n' "$count" "$ppid" "${pcmd:-unknown}"
	done
	printf '\n'
	printf 'LIKELY FIXES (match the named parent above):\n'
	printf '  * If the parent is a CONTAINER PID-1 that does not reap (e.g. a shell/app run as pid 1 in\n'
	printf '    a container), add `init: true` to that service in compose.yaml so Docker inserts a\n'
	printf '    reaping init (tini) as pid 1. That is the usual front-door / gateway zombie source.\n'
	printf '  * If the parent is the log-shipping chain (ship-frontdoor-logs.sh / an ssh or rsync it\n'
	printf '    spawned via the timer), a wedged transfer can leave defunct children - check the\n'
	printf '    ausmt-frontdoor-logs timer for overlapping or stuck runs and bound it with a timeout.\n'
	printf '  * If the parent is a short-lived cron/timer helper, ensure it wait()s for its children or\n'
	printf '    runs under a supervisor that reaps.\n'
	printf '  * Verify per-parent: ps --ppid <ppid> -o pid,stat,comm   (the defunct children of that parent)\n'
	return 0
}

# =================================================================================================
# Individual checks (default report)
# =================================================================================================
check_container_up() {
	cid="$($DOCKER compose -f "$COMPOSE_FILE" ps -q frontdoor 2>/dev/null)"
	if [ -z "$cid" ]; then
		fail "container: the frontdoor service has no running container (docker compose up -d)"
		return
	fi
	state="$($DOCKER inspect -f '{{.State.Status}}' "$cid" 2>/dev/null)"
	if [ "$state" = "running" ]; then
		pass "container: frontdoor is running ($state)"
	else
		fail "container: frontdoor is present but not running (state=${state:-unknown})"
	fi
}

check_running_config() {
	if [ ! -f "$CADDYFILE_REPO" ]; then
		warn "config: repo Caddyfile not found at $CADDYFILE_REPO (cannot hash-compare)"
		return
	fi
	# The container mounts the RENDERED Caddyfile (install-frontdoor.sh templates the legacy redirect
	# block in or out between the legacy-redirect markers), so the expected hash is a FRESH render of
	# the repo template under the current .env state, not the raw repo file. Keep this sed identical
	# to the installer's render step: the cross-check test drives both and fails on drift.
	tmp_render="$(mktemp)" || { warn "config: mktemp failed (cannot render the expected config)"; return; }
	if [ -n "${AUSMT_LEGACY_REDIRECT_NAME:-}" ]; then
		cat "$CADDYFILE_REPO" > "$tmp_render"
	else
		sed '/^# >>> legacy-redirect/,/^# <<< legacy-redirect/d' "$CADDYFILE_REPO" > "$tmp_render"
	fi
	want="$(_sha256 "$tmp_render")"
	rm -f "$tmp_render"
	if [ -z "$want" ]; then
		warn "config: no sha256 tool (sha256sum/shasum) available to hash-compare the config"
		return
	fi
	# Hash the file the RUNNING container has mounted at /etc/caddy/Caddyfile. busybox sha256sum ships in
	# caddy:2-alpine. First field is the digest.
	got="$($DOCKER compose -f "$COMPOSE_FILE" exec -T frontdoor sha256sum /etc/caddy/Caddyfile 2>/dev/null | awk '{print $1}')"
	if [ -z "$got" ]; then
		fail "config: could not read the running container's /etc/caddy/Caddyfile (is the edge up?)"
		return
	fi
	if [ "$got" = "$want" ]; then
		pass "config: running edge Caddyfile matches the rendered repo file (sha256 $(printf '%.12s' "$want")...)"
	else
		fail "config: running edge Caddyfile DIFFERS from the rendered repo file (running $got vs rendered $want) - re-run install-frontdoor.sh to re-render and reload"
	fi
}

check_upstream() {
	up="${AUSMT_BOX_READER_UPSTREAM:-}"
	if [ -z "$up" ]; then
		warn "upstream: AUSMT_BOX_READER_UPSTREAM unset in $ENV_FILE (cannot probe the box reader)"
		return
	fi
	code="$($CURL -sS -o /dev/null -w '%{http_code}' --max-time 8 "$up/data/catalogue.json" 2>/dev/null)"
	if [ "$code" = "200" ]; then
		pass "upstream: box reader answering over the tailnet ($up -> 200)"
	else
		fail "upstream: box reader NOT answering ($up -> ${code:-no-response}) - check tailscaled + the box (RUNBOOK section 11)"
	fi
}

# Certificate presence + expiry for ONE name, shared by the canonical and legacy TLS legs. `label` is
# the check label the PASS/WARN/FAIL line carries ("tls" canonical, "tls-legacy" legacy). A missing
# certificate is a FAIL for BOTH names: for the canonical name the edge is down, for the legacy name
# the redirect contract (every old link, including the pre-migration schema $id) is down.
_check_cert_for() {
	label="$1"
	name="$2"
	# Pull the served leaf cert's notAfter via a local TLS handshake with SNI. -servername drives SNI so
	# Caddy serves the right cert; connecting to 127.0.0.1:443 keeps it on-box.
	notafter="$(printf '' | $OPENSSL s_client -connect 127.0.0.1:443 -servername "$name" 2>/dev/null \
		| $OPENSSL x509 -noout -enddate 2>/dev/null | sed 's/^notAfter=//')"
	if [ -z "$notafter" ]; then
		fail "$label: no certificate served for $name on :443 (not issued yet, or the edge is down)"
		return
	fi
	# notAfter looks like 'Jul 25 12:00:00 2026 GMT'. GNU date parses it with -d; BSD/macOS date needs
	# the explicit -jf format. Try GNU first, fall back to BSD, so the check runs on the Linux VPS AND a
	# macOS dev box.
	exp_epoch="$(date -u -d "$notafter" +%s 2>/dev/null || date -u -jf '%b %d %H:%M:%S %Y %Z' "$notafter" +%s 2>/dev/null)"
	now_epoch="$(date -u +%s)"
	if [ -z "$exp_epoch" ]; then
		warn "$label: certificate present for $name but its expiry date ($notafter) could not be parsed"
		return
	fi
	days=$(( (exp_epoch - now_epoch) / 86400 ))
	if [ "$days" -lt 0 ]; then
		fail "$label: certificate for $name has EXPIRED ($notafter)"
	elif [ "$days" -lt "$CERT_WARN_DAYS" ]; then
		warn "$label: certificate for $name expires in $days days ($notafter) - inside the renewal window"
	else
		pass "$label: certificate for $name valid, $days days to expiry ($notafter)"
	fi
}

check_tls() {
	name="${AUSMT_PUBLIC_NAME:-}"
	if [ -z "$name" ]; then
		warn "tls: AUSMT_PUBLIC_NAME unset in $ENV_FILE (cannot check the public certificate)"
		return
	fi
	_check_cert_for "tls" "$name"
}

check_tls_legacy() {
	legacy="${AUSMT_LEGACY_REDIRECT_NAME:-}"
	if [ -z "$legacy" ]; then
		# SKIPPED, not failed: an empty legacy var is the supported canonical-only deploy.
		pass "tls-legacy: skipped (AUSMT_LEGACY_REDIRECT_NAME unset - no legacy name is served)"
		return
	fi
	# A missing legacy certificate is a FAIL, not a WARN (_check_cert_for fails on absence): with no
	# cert the https:// leg of every legacy link is dead, so the redirect contract is not being kept.
	_check_cert_for "tls-legacy" "$legacy"
}

check_redirect() {
	legacy="${AUSMT_LEGACY_REDIRECT_NAME:-}"
	name="${AUSMT_PUBLIC_NAME:-}"
	if [ -z "$legacy" ]; then
		pass "redirect: skipped (AUSMT_LEGACY_REDIRECT_NAME unset - no legacy name is served)"
		return
	fi
	if [ -z "$name" ]; then
		warn "redirect: AUSMT_PUBLIC_NAME unset in $ENV_FILE (cannot verify the redirect target)"
		return
	fi
	# THE HTTPS LEG, EXPLICITLY: an https:// URL with SNI = the legacy name, resolved to this host.
	# Probing http:// would be answered by Caddy's AUTOMATIC HTTP->HTTPS hop (a redirect on any
	# hostname site), which would pass even if the legacy site block were missing; the https:// probe
	# is answered by the legacy block itself or not at all. The probe path is the pre-migration
	# schema $id (/data/mtcat.schema.json), so a PASS also proves the old identifier keeps resolving
	# with its path preserved.
	probe_path="/data/mtcat.schema.json"
	out="$($CURL -sS -o /dev/null -w '%{http_code} %{redirect_url}' --max-time 8 \
		--resolve "$legacy:443:127.0.0.1" "https://$legacy$probe_path" 2>/dev/null)"
	code="${out%% *}"
	loc="${out#* }"
	want="https://$name$probe_path"
	if [ "$code" = "301" ] && [ "$loc" = "$want" ]; then
		pass "redirect: https://$legacy$probe_path 301s to $want (permanent, path preserved)"
	else
		fail "redirect: https://$legacy$probe_path -> ${code:-no-response} ${loc:-no-location} (want 301 -> $want)"
	fi
}

check_tailscale() {
	if ! $TAILSCALE status >/dev/null 2>&1; then
		fail "tailscale: not up (tailscale status failed) - the edge cannot reach the box"
		return
	fi
	# Derive the box peer name from the upstream (http://ausmt-box:8445 -> ausmt-box). Fall back to a
	# generic 'peer visible' check if we cannot.
	up="${AUSMT_BOX_READER_UPSTREAM:-}"
	peer="$(printf '%s' "$up" | sed -e 's#^[a-z]*://##' -e 's#[:/].*$##')"
	if [ -n "$peer" ]; then
		if $TAILSCALE status 2>/dev/null | grep -qi "$peer"; then
			pass "tailscale: up and the box peer ($peer) is visible"
		else
			fail "tailscale: up but the box peer ($peer) is NOT visible in the tailnet"
		fi
	else
		pass "tailscale: up (box peer name not derivable from upstream, skipped peer match)"
	fi
}

check_zombies() {
	n="$(zombie_count)"
	if [ "$n" -ge "$ZOMBIE_WARN" ] 2>/dev/null; then
		warn "zombies: $n Z-state processes (>= warn threshold $ZOMBIE_WARN) - run ./doctor.sh zombies to name the leaker"
	else
		pass "zombies: $n Z-state processes (under threshold $ZOMBIE_WARN)"
	fi
}

check_disk() {
	# df -P for portable one-line output; the Use% column, digits only.
	usep="$(df -P "$DISK_PATH" 2>/dev/null | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
	if [ -z "$usep" ]; then
		warn "disk: could not read usage for $DISK_PATH"
		return
	fi
	if [ "$usep" -ge "$DISK_WARN_PCT" ] 2>/dev/null; then
		warn "disk: $DISK_PATH is ${usep}% full (>= warn threshold ${DISK_WARN_PCT}%)"
	else
		pass "disk: $DISK_PATH is ${usep}% full (under ${DISK_WARN_PCT}%)"
	fi
}

check_dns() {
	name="${AUSMT_PUBLIC_NAME:-}"
	if [ -z "$name" ]; then
		warn "dns: AUSMT_PUBLIC_NAME unset in $ENV_FILE (cannot check the public A record)"
		return
	fi
	resolved="$($DIG +short A "$name" 2>/dev/null | grep -E '^[0-9]+\.' | head -n1)"
	if [ -z "$resolved" ]; then
		fail "dns: $name has no A record (public resolution is down, or the record was pulled)"
		return
	fi
	expect="${AUSMT_DOCTOR_EXPECT_IP:-}"
	if [ -z "$expect" ]; then
		warn "dns: $name resolves to $resolved (set AUSMT_DOCTOR_EXPECT_IP to this VPS's public IP to verify the target)"
	elif [ "$resolved" = "$expect" ]; then
		pass "dns: $name resolves to this host ($resolved)"
	else
		fail "dns: $name resolves to $resolved, NOT this host ($expect) - the record points elsewhere"
	fi
}

run_report() {
	printf 'AusMT front-door doctor (VPS edge) - %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
	printf '=====================================================\n'
	check_container_up
	check_running_config
	check_upstream
	check_tls
	check_tls_legacy
	check_redirect
	check_tailscale
	check_zombies
	check_disk
	check_dns
	printf '=====================================================\n'
	if [ "$FAILS" -gt 0 ]; then
		printf 'RESULT: FAIL (%s failed, %s warned) - the edge needs attention. See RUNBOOK.md.\n' "$FAILS" "$WARNS"
		return 1
	fi
	if [ "$WARNS" -gt 0 ]; then
		printf 'RESULT: PASS with %s warning(s) - no hard failure, but review the WARN lines.\n' "$WARNS"
		return 0
	fi
	printf 'RESULT: PASS - the edge is healthy.\n'
	return 0
}

# ----- dispatch ----------------------------------------------------------------------------------
case "${1:-report}" in
	report) run_report ;;
	zombies) zombie_kit ;;
	-h|--help) sed -n '2,50p' "$0" ;;
	*) printf 'doctor: unknown subcommand: %s (try: report | zombies | --help)\n' "$1" >&2; exit 2 ;;
esac
