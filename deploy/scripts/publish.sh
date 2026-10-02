#!/bin/sh
# AusMT serving-replica sender. POSIX sh, shellcheck-clean. Runs on the host that builds (the box
# today, the curation instance later) and hands one finished build to the serving replica, whose
# deploy/scripts/receive-build.sh verifies it and swaps it in. Invoked by `make publish` and by
# deploy/scripts/reconcile.sh at the end of a pass; see maintainer/C48-NectarTopology.md.
#
# WHAT ONE RUN DOES, in order, stopping at the first failure with the step named:
#   resolve-build  the build to send: --build <ts>, or the build current points at. current must be
#                  a symlink to builds/<ts>; a directory, a dangling link or a link out of builds/
#                  names no build and is refused. A build holding anything but regular files and
#                  directories is refused (a symlink would serve whatever it points at).
#   ask-receiver   ssh <target> receive-build.sh --current. A receiver already serving <ts> is sent
#                  nothing and only asked to receive <ts> again: a no-op when its published.json
#                  agrees, and the repair of a receive cut off between its swap and its record.
#   sidecar        write builds/<ts>.sha256 beside the build (never inside it): the sha256sum list of
#                  every file, relative paths, sorted in C order.
#   rsync-build    rsync -a --no-times --checksum --delete, with --link-dest=../<receiver's current>
#                  when it has one, into <remote>/site-data/builds/<ts>/. rsync links a file only when
#                  every preserved attribute matches and a rebuild rewrites every mtime, so content,
#                  not mtime, decides: a byte-identical file is hard-linked to the served copy.
#   rsync-sidecar  the sidecar to <remote>/site-data/builds/<ts>.sha256, AFTER the build, so the
#                  receiver can tell a finished transfer from one in flight.
#   receive        ssh <target> receive-build.sh --keep <n> <ts>: verify, swap, record, prune.
# The local current is only ever read. A failed transfer never reaches the receive step.
#
# ENV (deploy/.env.example documents each)
#   AUSMT_DATA_DIR          (required) local data root holding site-data/
#   AUSMT_PUBLISH_TARGET    (required) ssh destination of the receiver, e.g. publish@ausmt-serve
#   AUSMT_PUBLISH_DATA_DIR  data root on the receiver (default /srv/ausmt; the receiver's gate pins that
#                           path, so any other value is refused there)
#   AUSMT_PUBLISH_KEEP      builds the receiver keeps, 1 to 999 (default 5)
#   AUSMT_PUBLISH_RSYNC     the rsync command (default rsync); a test shim in the suite
#   AUSMT_PUBLISH_SSH       the ssh command, also handed to rsync -e (default ssh in batch mode, with
#                           a connect timeout and a keepalive that ends a session to a silent replica)
#
# FLAGS
#   --dry-run     resolve and check the build, print what would be sent, contact nothing, write nothing
#   --build <ts>  send this retained build instead of the one current points at
#
# EXIT: 0 published or already current; 1 a step failed; 2 a malformed invocation.

set -u

DRY_RUN=0
BUILD_TS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --build)
      [ $# -ge 2 ] || { printf 'publish: --build needs a build timestamp\n' >&2; exit 2; }
      BUILD_TS="$2"; shift 2 ;;
    -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
    *) printf 'publish: unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done

: "${AUSMT_DATA_DIR:?set AUSMT_DATA_DIR (local data root; see deploy/.env.example)}"
: "${AUSMT_PUBLISH_TARGET:?set AUSMT_PUBLISH_TARGET (ssh destination of the serving replica; see deploy/.env.example)}"
TARGET="$AUSMT_PUBLISH_TARGET"
REMOTE_DIR="${AUSMT_PUBLISH_DATA_DIR:-/srv/ausmt}"
KEEP="${AUSMT_PUBLISH_KEEP:-5}"
RSYNC="${AUSMT_PUBLISH_RSYNC:-rsync}"
SSH="${AUSMT_PUBLISH_SSH:-ssh -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=30 -o ServerAliveCountMax=4}"
SITE="$AUSMT_DATA_DIR/site-data"
BUILDS="$SITE/builds"

fail() { printf 'publish: FAILED at step %s: %s\n' "$1" "$2" >&2; exit 1; }

is_ts() {
  case "$1" in
    [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z) return 0 ;;
  esac
  return 1
}

case "$KEEP" in
  [1-9]|[1-9][0-9]|[1-9][0-9][0-9]) ;;
  *) fail resolve-build "AUSMT_PUBLISH_KEEP must be a whole number from 1 to 999: $KEEP" ;;
esac
# The receiver's gate admits one fixed builds path, so the remote root is a plain absolute path.
case "$REMOTE_DIR" in
  /*) ;;
  *) fail resolve-build "AUSMT_PUBLISH_DATA_DIR must be an absolute path: $REMOTE_DIR" ;;
esac
case "$REMOTE_DIR" in *[!A-Za-z0-9._/-]*|*..*) fail resolve-build "AUSMT_PUBLISH_DATA_DIR carries characters the receiver refuses: $REMOTE_DIR" ;; esac

# ----- resolve-build ------------------------------------------------------------------------------
if [ -n "$BUILD_TS" ]; then
  is_ts "$BUILD_TS" || fail resolve-build "not a build timestamp (YYYYMMDDTHHMMSSZ): $BUILD_TS"
  TS="$BUILD_TS"
else
  [ -L "$SITE/current" ] || fail resolve-build "$SITE/current is not a symlink, so it names no build to publish"
  cur_target=$(readlink "$SITE/current")
  TS=${cur_target#builds/}
  if [ "$cur_target" != "builds/$TS" ] || ! is_ts "$TS"; then
    fail resolve-build "$SITE/current points at $cur_target, not at builds/<timestamp>"
  fi
fi
BUILD="$BUILDS/$TS"
if [ ! -d "$BUILD" ] || [ -L "$BUILD" ]; then
  fail resolve-build "no build directory $BUILD"
fi
[ -f "$BUILD/build.json" ] || fail resolve-build "$BUILD carries no build.json"
odd=$(cd "$BUILD" && find . ! -type f ! -type d | sed 's|^\./||' | head -n 20)
[ -z "$odd" ] || fail resolve-build "$BUILD holds entries that are neither files nor directories: $(printf '%s' "$odd" | tr '\n' ' ')"
# A backslash or a newline in a path changes the sha256sum line format; no build writes one.
bad=$(cd "$BUILD" && find . -name '*\\*' | head -n 5)
[ -z "$bad" ] || fail resolve-build "$BUILD holds a path with a backslash: $(printf '%s' "$bad" | tr '\n' ' ')"
nl='
'
bad=$(cd "$BUILD" && find . -name "*$nl*" | head -n 5)
[ -z "$bad" ] || fail resolve-build "$BUILD holds a path with a newline"
[ -w "$BUILDS" ] || fail sidecar "$BUILDS is not writable by $(id -un 2>/dev/null || echo '?'), so the sidecar cannot be written beside the build (the one-time grant is in deploy/README.md, Nectar serving replica)"

DEST="$TARGET:$REMOTE_DIR/site-data/builds"
if [ "$DRY_RUN" -eq 1 ]; then
  printf 'publish: [dry-run] would publish builds/%s to %s/%s/ and its sidecar, then ask the receiver to keep %s builds\n' \
    "$TS" "$DEST" "$TS" "$KEEP"
  exit 0
fi

# ----- ask-receiver -------------------------------------------------------------------------------
# shellcheck disable=SC2086 # SSH and RSYNC are word-split commands (the default, or a test shim).
remote_cur=$($SSH "$TARGET" receive-build.sh --current) \
  || fail ask-receiver "ssh $TARGET receive-build.sh --current did not answer"
if [ -n "$remote_cur" ] && ! is_ts "$remote_cur"; then
  fail ask-receiver "the receiver answered something that is not a build name: $remote_cur"
fi
if [ "$remote_cur" = "$TS" ]; then
  printf 'publish: %s already serves builds/%s; nothing to send\n' "$TARGET" "$TS"
  # shellcheck disable=SC2086
  $SSH "$TARGET" receive-build.sh --keep "$KEEP" "$TS" \
    || fail receive "$TARGET serves builds/$TS but did not confirm it; ask it with receive-build.sh --current"
  exit 0
fi

# ----- sidecar ------------------------------------------------------------------------------------
WORK=$(mktemp -d "${TMPDIR:-/tmp}/publish.XXXXXX") || fail sidecar "cannot create a scratch directory"
trap 'rm -rf "$WORK"; rm -f "${side_tmp:-}"' EXIT
trap 'exit 143' TERM INT HUP
(cd "$BUILD" && find . -type f | sed 's|^\./||' | LC_ALL=C sort) > "$WORK/files" \
  || fail sidecar "cannot list $BUILD"
side_tmp=$(mktemp "$BUILDS/.$TS.sha256.XXXXXX") || fail sidecar "cannot create a file in $BUILDS"
(cd "$BUILD" && tr '\n' '\0' < "$WORK/files" | xargs -0 sha256sum --) > "$side_tmp" \
  || fail sidecar "hashing $BUILD failed"
if [ "$(wc -l < "$side_tmp")" -ne "$(wc -l < "$WORK/files")" ]; then
  fail sidecar "the hash list of $BUILD is shorter than its file list"
fi
chmod 0644 "$side_tmp"
mv -f "$side_tmp" "$BUILDS/$TS.sha256" || fail sidecar "cannot move the sidecar into place"
side_tmp=""
printf 'publish: sidecar builds/%s.sha256 lists %s files\n' "$TS" "$(wc -l < "$WORK/files" | tr -d ' ')"

# ----- rsync-build, rsync-sidecar -----------------------------------------------------------------
if [ -n "$remote_cur" ]; then
  set -- "--link-dest=../$remote_cur"
else
  set --
fi
printf 'publish: sending builds/%s to %s/%s/%s\n' "$TS" "$DEST" "$TS" "${remote_cur:+ (linking against builds/$remote_cur)}"
# shellcheck disable=SC2086
$RSYNC -a --no-times --checksum --delete "$@" -e "$SSH" "$BUILD/" "$DEST/$TS/" \
  || fail rsync-build "rsync of builds/$TS to $DEST/$TS/ failed"
# shellcheck disable=SC2086
$RSYNC -a --no-times --checksum -e "$SSH" "$BUILDS/$TS.sha256" "$DEST/$TS.sha256" \
  || fail rsync-sidecar "rsync of builds/$TS.sha256 to $DEST/$TS.sha256 failed"

# ----- receive ------------------------------------------------------------------------------------
# shellcheck disable=SC2086
$SSH "$TARGET" receive-build.sh --keep "$KEEP" "$TS" \
  || fail receive "the receiver refused or did not finish builds/$TS (a refusal leaves its current as it was, a receive cut off after its swap does not); ask it with receive-build.sh --current"
printf 'publish: %s now serves builds/%s\n' "$TARGET" "$TS"
exit 0
