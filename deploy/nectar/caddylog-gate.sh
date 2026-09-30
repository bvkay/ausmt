#!/bin/sh
# AusMT log-account gate. POSIX sh, shellcheck-clean. Installed on the serving replica as
# /usr/local/bin/ausmt-caddylog-gate and set as the login shell of the caddylog account, through
# which the curation host pulls the masked front-door access log (deploy/frontdoor/
# ship-frontdoor-logs.sh). A Tailscale SSH session runs `<login shell> -c <command>` and never reads
# authorized_keys, so the forced command the front-door runbook puts on that key cannot be the
# control here; this gate is. It admits one thing, an rsync that SENDS, and hands it to rrsync -ro
# rooted at the log directory, which is how the forced command confines it.
#
# ENV
#   AUSMT_GATE_RRSYNC   the rrsync program (default rrsync, shipped with rsync); a test shim in the suite

set -u

RRSYNC_BIN="${AUSMT_GATE_RRSYNC:-rrsync}"
LOG_DIR=/var/log/caddy

refuse() { printf 'caddylog-gate: refused: %s\n' "$1" >&2; exit 1; }

if [ -n "${SSH_ORIGINAL_COMMAND:-}" ]; then
  cmd="$SSH_ORIGINAL_COMMAND"
else
  [ "${1:-}" = "-l" ] && shift
  if [ $# -eq 2 ] && [ "$1" = "-c" ]; then
    cmd="$2"
  else
    refuse "this account has no interactive shell"
  fi
fi
case "$cmd" in
  ''|*[!A-Za-z0-9\ ._=/-]*) refuse "not a read-only rsync of the log directory: $cmd" ;;
  "rsync --server --sender "*) ;;
  *) refuse "not a read-only rsync of the log directory: $cmd" ;;
esac
SSH_ORIGINAL_COMMAND="$cmd"
export SSH_ORIGINAL_COMMAND
# shellcheck disable=SC2086 # RRSYNC_BIN may be a word-split test shim.
exec $RRSYNC_BIN -ro "$LOG_DIR"
