#!/bin/sh
# AusMT publish-account gate. POSIX sh, shellcheck-clean. Installed on the serving replica as
# /usr/local/bin/ausmt-publish-gate, and it is BOTH the login shell of the publish account (a
# Tailscale SSH session runs `<login shell> -c <command>`) and the forced command on that account's
# OpenSSH key (OpenSSH hands the client's words over in SSH_ORIGINAL_COMMAND). Either way a
# COMMAND SESSION on the account runs one of three commands:
#
#   receive-build.sh --current                  ask which build current names
#   receive-build.sh [--keep N] <ts>            verify, swap in, record and prune a sent build
#   rsync --server ... . <builds>/<ts>/         receive a build, or <builds>/<ts>.sha256 its sidecar
#
# where <builds> is $AUSMT_DATA_DIR/site-data/builds and <ts> is a build timestamp. Anything else,
# an interactive login included, is refused before any program runs.
#
# WHAT THIS BOUNDS AND WHAT IT DOES NOT. The gate confines command sessions only. Tailscale SSH
# serves SFTP itself, in-process and as the account: it probes the login shell with `true`, which
# this gate refuses, and then serves the SFTP session without ever running the gate. Over SFTP the
# account reads what uid 10001 can read and writes what uid 10001 can write. That holds while the
# box is the sender, because the account's only writable tree on this host is site-data, the tree it
# exists to replace, and the serving host holds no secret the account can read (the TLS key sits in
# a root-only Docker volume). The boundary is therefore the
# account itself, uid 10001, and its write set: a path outside site-data made writable by uid 10001
# is a path every publish login reaches. A sender on the private network can be held to an OpenSSH
# listener whose forced command confines SFTP too; Tailscale SSH owns the tailnet's port 22.
#
# Within a command session the gate gives the account no shell and no read path (an rsync --sender
# is refused), and it pins where a transfer is aimed. It does not police the file names an rsync
# client streams once the transfer runs: the rsync receiver trusts its client, as it does over any
# SSH login. The receiver's verification against the sidecar decides what is served.
#
# ENV
#   AUSMT_DATA_DIR       data root (default /srv/ausmt)
#   AUSMT_GATE_RSYNC     the rsync program (default rsync); a test shim in the suite
#   AUSMT_GATE_RECEIVE   the receiver (default /usr/local/bin/receive-build.sh); a test shim too

set -u

DATA_DIR="${AUSMT_DATA_DIR:-/srv/ausmt}"
BUILDS="$DATA_DIR/site-data/builds"
RSYNC_BIN="${AUSMT_GATE_RSYNC:-rsync}"
RECEIVE_BIN="${AUSMT_GATE_RECEIVE:-/usr/local/bin/receive-build.sh}"

refuse() { printf 'publish-gate: refused: %s\n' "$1" >&2; exit 1; }

is_ts() {
  case "$1" in
    [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z) return 0 ;;
  esac
  return 1
}

# A short-option word as rsync writes it for its server: letters, optionally followed by the
# e<capabilities> tail. The letters before that tail may not name an option that takes a value
# (B, M, T, f) or s, which moves the real arguments off the command line and out of this gate's view;
# nor K, k or L, which make the receiver follow a symlink rather than treat it as a link, so a planted
# link would carry a write past the pinned destination; nor b, which leaves backup files beside the
# tree that no sidecar lists. The publish sends none of them.
flag_ok() {
  case "$1" in --*|-) return 1 ;; -*) ;; *) return 1 ;; esac
  _body=${1#-}
  _pre=${_body%%e*}
  _rest=${_body#"$_pre"}
  case "$_pre" in *[!A-Za-z]*|*[BKLMTbfks]*) return 1 ;; esac
  case "$_rest" in
    '') return 0 ;;
    e*) case "${_rest#e}" in *[!.A-Za-z]*) return 1 ;; esac; return 0 ;;
  esac
  return 1
}

# ----- the command, from whichever entry delivered it ---------------------------------------------
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
[ -n "$cmd" ] || refuse "an empty command"
case "$cmd" in
  *[!A-Za-z0-9\ ._=/-]*) refuse "a character outside the three commands' alphabet: $cmd" ;;
esac

set -f
# shellcheck disable=SC2086 # the command is split into words on purpose; globbing is off.
set -- $cmd
set +f

case "$1" in
  receive-build.sh)
    shift
    case "$#:${1:-}" in
      1:--current) ;;
      1:*) is_ts "$1" || refuse "not a build timestamp: $1" ;;
      3:--keep)
        case "$2" in
          [1-9]|[1-9][0-9]|[1-9][0-9][0-9]) ;;
          *) refuse "not a keep depth from 1 to 999: $2" ;;
        esac
        is_ts "$3" || refuse "not a build timestamp: $3" ;;
      *) refuse "receive-build.sh takes --current, <ts>, or --keep N <ts>" ;;
    esac
    export AUSMT_DATA_DIR="$DATA_DIR"
    # shellcheck disable=SC2086 # RECEIVE_BIN may be a word-split test shim.
    exec $RECEIVE_BIN "$@"
    ;;
  rsync)
    shift
    [ "${1:-}" = "--server" ] || refuse "only an rsync server that receives is allowed"
    seen_dot=0
    dest=""
    link=""
    expect_link=0
    for w in "$@"; do
      if [ "$expect_link" -eq 1 ]; then
        link="$w"; expect_link=0
      elif [ "$seen_dot" -eq 1 ]; then
        [ -z "$dest" ] || refuse "more than one destination"
        dest="$w"
        continue
      else
        case "$w" in
          --server) ;;
          .) seen_dot=1 ;;
          --delete|--delete-before|--delete-during|--delete-delay|--delete-after|--dirs) ;;
          --link-dest) expect_link=1; continue ;;
          --link-dest=*) link="${w#--link-dest=}" ;;
          --*) refuse "rsync option not allowed here: $w" ;;
          *) flag_ok "$w" || refuse "rsync flags not allowed here: $w" ;;
        esac
      fi
      if [ -n "$link" ]; then
        if ! is_ts "${link#../}" || [ "$link" != "../${link#../}" ]; then
          refuse "a link-dest outside the sibling builds: $link"
        fi
        link=""
      fi
    done
    [ "$expect_link" -eq 0 ] || refuse "--link-dest without a directory"
    if [ "$seen_dot" -ne 1 ] || [ -z "$dest" ]; then
      refuse "no destination"
    fi
    rel=${dest#"$BUILDS"/}
    [ "$dest" = "$BUILDS/$rel" ] || refuse "a destination outside $BUILDS: $dest"
    case "$rel" in
      *.sha256) is_ts "${rel%.sha256}" || refuse "not a build sidecar: $rel" ;;
      */) is_ts "${rel%/}" || refuse "not a build directory: $rel" ;;
      *) is_ts "$rel" || refuse "not a build directory: $rel" ;;
    esac
    # shellcheck disable=SC2086 # RSYNC_BIN may be a word-split test shim.
    exec $RSYNC_BIN "$@"
    ;;
esac
refuse "not one of the three publish commands: $1"
