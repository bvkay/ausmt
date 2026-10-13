#!/bin/sh
# AusMT serving-replica receiver. POSIX sh, shellcheck-clean. Runs on the serving host as the
# account that owns site-data (uid 10001), reached over SSH through deploy/nectar/publish-gate.sh
# by deploy/scripts/publish.sh on the host that builds.
#
# USAGE
#   receive-build.sh [--keep N] <ts>   verify site-data/builds/<ts> against builds/<ts>.sha256, swap
#                                      current to it, record published.json, prune old builds
#   receive-build.sh --current         print the build name current points at (nothing when there
#                                      is no current yet)
#
# THE CONTRACT WITH THE SENDER. builds/<ts>.sha256 is the sha256sum list of every regular file in
# the build, relative paths, sorted in C order, written OUTSIDE the build directory so it is never
# served and never lists itself. The build is accepted only when the files on disk are exactly the
# listed files with exactly the listed hashes: a missing file, an unlisted file, a changed byte or
# any entry that is not a regular file or a directory refuses it. The sidecar travels after the
# build, so a directory with no sidecar is a transfer still in flight.
#
# INVARIANTS
#   * A refused build leaves current, published.json and every other build untouched, and exits
#     non-zero with the reason on stderr.
#   * current is swapped by renaming a temporary symlink over it (rename(2)), never by ln -sfn, which
#     unlinks first and leaves readers a window with no current. Caddy follows current per request.
#   * The prune keeps the KEEP newest builds that carry a sidecar, always keeps the build received
#     and the build current points at when the prune runs, and never touches a directory without a
#     sidecar. It runs on every accepted receive, the confirmation of an already-current build
#     included, so a keep depth lowered on the sender takes effect on the next publish and a full
#     disk is recovered without waiting for a new build.
#   * published.json records ts, build_id, source_commit, received_at and sender, the address the
#     receive arrived from (the first word of SSH_CLIENT, else of SSH_CONNECTION, else local), so a
#     replica fed by two hosts can be told apart.
#   * One receive at a time: verify, swap, record and prune run under flock(1) on
#     site-data/.receive.lock, so a second receive waits instead of pruning under the first.
#   * A build name reaches the filesystem only after it has matched the timestamp shape, and a keep
#     depth only after it has matched 1 to 999 with no leading zero.
#   * current names a build only while builds/<ts> is a directory; --current prints nothing for a
#     dangling current, so the sender sends the build again.
#
# ENV
#   AUSMT_DATA_DIR      data root holding site-data/ (default /srv/ausmt)
#   AUSMT_PUBLISH_KEEP  builds to keep when --keep is not given (default 5)
#
# EXIT: 0 accepted or already current; 1 refused or failed; 2 a malformed invocation.

set -u

DATA_DIR="${AUSMT_DATA_DIR:-/srv/ausmt}"
SITE="$DATA_DIR/site-data"
BUILDS="$SITE/builds"
KEEP="${AUSMT_PUBLISH_KEEP:-5}"

usage() {
  printf 'receive-build: %s\n' "$1" >&2
  printf 'usage: receive-build.sh [--keep N] <ts> | receive-build.sh --current\n' >&2
  exit 2
}
die() { printf 'receive-build: %s\n' "$*" >&2; exit 1; }

is_ts() {
  case "$1" in
    [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z) return 0 ;;
  esac
  return 1
}

MODE=receive
TS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --current) MODE=current; shift ;;
    --keep)
      [ $# -ge 2 ] || usage "--keep needs a number"
      KEEP="$2"; shift 2 ;;
    -*) usage "unknown option: $1" ;;
    *)
      [ -z "$TS" ] || usage "exactly one build name is accepted"
      TS="$1"; shift ;;
  esac
done
case "$KEEP" in
  [1-9]|[1-9][0-9]|[1-9][0-9][0-9]) ;;
  *) usage "the keep depth must be a whole number from 1 to 999: $KEEP" ;;
esac

# current_name: the build name current points at, or nothing when current does not exist or its
# build directory is gone. A current that exists but is not a symlink to builds/<ts> cannot name a
# build, and every caller stops on it.
current_name() {
  if [ ! -e "$SITE/current" ] && [ ! -L "$SITE/current" ]; then
    return 0
  fi
  [ -L "$SITE/current" ] || die "$SITE/current is not a symlink, so it names no build; refusing to replace it"
  _t=$(readlink "$SITE/current")
  _n=${_t#builds/}
  if [ "$_t" != "builds/$_n" ] || ! is_ts "$_n"; then
    die "$SITE/current points at $_t, not at builds/<timestamp>; refusing to replace it"
  fi
  [ -d "$BUILDS/$_n" ] || return 0
  printf '%s\n' "$_n"
}

if [ "$MODE" = current ]; then
  [ -z "$TS" ] || usage "--current takes no build name"
  current_name
  exit 0
fi

[ -n "$TS" ] || usage "a build name is required"
is_ts "$TS" || usage "not a build timestamp (YYYYMMDDTHHMMSSZ): $TS"

# The wait is bounded so a stuck holder fails the next receive instead of hanging it. flock(1) is in
# util-linux on the serving host; without it the receive runs unlocked and says so.
LOCK="$SITE/.receive.lock"
if command -v flock >/dev/null 2>&1; then
  exec 9>>"$LOCK" || die "cannot open the lock file $LOCK"
  flock -w 900 9 || die "another receive held $LOCK too long; nothing was changed"
else
  printf 'receive-build: flock(1) not found; receiving without the lock\n' >&2
fi

PY=""
for _cand in python3 python; do
  if command -v "$_cand" >/dev/null 2>&1 && "$_cand" -c "import sys" >/dev/null 2>&1; then
    PY="$_cand"
    break
  fi
done
[ -n "$PY" ] || die "no working python3 on PATH (needed to read build.json and write published.json)"

BUILD="$BUILDS/$TS"
SIDECAR="$BUILDS/$TS.sha256"
if [ ! -d "$BUILD" ] || [ -L "$BUILD" ]; then
  die "no build directory $BUILD"
fi
CUR=$(current_name) || exit 1

# published_ts: the ts published.json records, or nothing.
published_ts() {
  [ -f "$SITE/published.json" ] || return 0
  "$PY" - "$SITE/published.json" <<'PYEOF' 2>/dev/null || true
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        ts = json.load(fh).get("ts")
    if isinstance(ts, str):
        print(ts)
except Exception:
    pass
PYEOF
}

# prune_builds <served>: delete every complete build (one that carries a sidecar) past the KEEP
# newest, except the build just received or confirmed and the build current names when the prune
# runs. A directory without a sidecar is a transfer in flight and is never touched.
prune_builds() {
  _live=$(current_name) || die "current changed shape; nothing pruned"
  ls -1 "$BUILDS" 2>/dev/null | LC_ALL=C sort -r | { n=0; while IFS= read -r side; do
    case "$side" in *.sha256) ;; *) continue ;; esac
    name=${side%.sha256}
    if ! is_ts "$name" || [ ! -d "$BUILDS/$name" ]; then
      continue
    fi
    n=$((n + 1))
    [ "$n" -le "$KEEP" ] && continue
    [ "$name" = "$1" ] && continue
    [ "$name" = "$_live" ] && continue
    printf 'receive-build: pruning builds/%s\n' "$name"
    rm -rf -- "${BUILDS:?}/$name" "${BUILDS:?}/$side"
  done; }
}

if [ "$CUR" = "$TS" ] && [ "$(published_ts)" = "$TS" ]; then
  printf 'receive-build: builds/%s is already current and recorded; nothing to swap\n' "$TS"
  prune_builds "$TS"
  exit 0
fi

[ -f "$SIDECAR" ] || die "no sidecar $SIDECAR, so builds/$TS is still in flight or was never sent"
[ -f "$BUILD/build.json" ] || die "builds/$TS carries no build.json, so its identity cannot be recorded"
"$PY" -c 'import json,sys; json.load(open(sys.argv[1], encoding="utf-8"))' "$BUILD/build.json" 2>/dev/null \
  || die "builds/$TS/build.json does not parse as JSON"

WORK=$(mktemp -d "${TMPDIR:-/tmp}/receive-build.XXXXXX") || die "cannot create a scratch directory"
trap 'rm -rf "$WORK"' EXIT
trap 'rm -rf "$WORK"; exit 143' TERM INT HUP

# ----- verify -------------------------------------------------------------------------------------
odd=$(cd "$BUILD" && find . ! -type f ! -type d | sed 's|^\./||' | head -n 20)
[ -z "$odd" ] || die "builds/$TS holds entries that are neither files nor directories (a symlink would serve whatever it points at): $(printf '%s' "$odd" | tr '\n' ' ')"

if grep -qv '^[0-9a-f]\{64\}  ' "$SIDECAR"; then
  die "$SIDECAR has a line that is not <sha256><two spaces><path>"
fi
cut -c67- "$SIDECAR" | LC_ALL=C sort > "$WORK/listed"
(cd "$BUILD" && find . -type f | sed 's|^\./||' | LC_ALL=C sort) > "$WORK/present"
missing=$(LC_ALL=C comm -23 "$WORK/listed" "$WORK/present" | head -n 20)
extra=$(LC_ALL=C comm -13 "$WORK/listed" "$WORK/present" | head -n 20)
if [ -n "$missing" ] || [ -n "$extra" ]; then
  [ -z "$missing" ] || printf 'receive-build: listed but not present: %s\n' "$(printf '%s' "$missing" | tr '\n' ' ')" >&2
  [ -z "$extra" ] || printf 'receive-build: present but not listed: %s\n' "$(printf '%s' "$extra" | tr '\n' ' ')" >&2
  die "builds/$TS does not match its sidecar; current left at ${CUR:-<none>}"
fi
[ -s "$WORK/present" ] || die "builds/$TS holds no files"
(cd "$BUILD" && tr '\n' '\0' < "$WORK/present" | xargs -0 sha256sum --) > "$WORK/actual" \
  || die "hashing builds/$TS failed"
if ! cmp -s "$WORK/actual" "$SIDECAR"; then
  LC_ALL=C sort "$WORK/actual" > "$WORK/actual.sorted"
  LC_ALL=C sort "$SIDECAR" > "$WORK/sidecar.sorted"
  altered=$(LC_ALL=C comm -13 "$WORK/sidecar.sorted" "$WORK/actual.sorted" | cut -c67- | head -n 20)
  die "builds/$TS has files whose bytes differ from the sidecar: $(printf '%s' "$altered" | tr '\n' ' '); current left at ${CUR:-<none>}"
fi

# ----- swap ---------------------------------------------------------------------------------------
# mv -T is the GNU spelling of "rename onto this name even though it resolves to a directory"; where
# it does not exist the same rename(2) is made through os.replace. A plain mv would move the
# temporary link INTO the build current points at.
tmp="$SITE/current.tmp.$TS.$$"
rm -f "$tmp"
ln -s "builds/$TS" "$tmp" || die "cannot create the temporary link $tmp"
if ! mv -T "$tmp" "$SITE/current" 2>/dev/null; then
  if ! "$PY" -c 'import os,sys; os.replace(sys.argv[1], sys.argv[2])' "$tmp" "$SITE/current"; then
    rm -f "$tmp"
    die "the swap of current failed; current left at ${CUR:-<none>}"
  fi
fi

# ----- record -------------------------------------------------------------------------------------
rec=$(mktemp "$SITE/.published.json.XXXXXX") || die "current -> builds/$TS but published.json could not be written"
chmod 0644 "$rec"
# The sender is the address the SSH session arrived from; a receive run on the host itself is local.
sender=${SSH_CLIENT:-${SSH_CONNECTION:-}}
sender=${sender%% *}
[ -n "$sender" ] || sender=local
if ! AUSMT_RB_TS="$TS" AUSMT_RB_BUILD_JSON="$BUILD/build.json" AUSMT_RB_SENDER="$sender" \
     AUSMT_RB_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$PY" - > "$rec" <<'PYEOF'
import json, os
with open(os.environ["AUSMT_RB_BUILD_JSON"], encoding="utf-8") as fh:
    build = json.load(fh)
def text(key):
    v = build.get(key) if isinstance(build, dict) else None
    return v if isinstance(v, str) and v else None
print(json.dumps({
    "ts": os.environ["AUSMT_RB_TS"],
    "build_id": text("build_id"),
    "source_commit": text("source_commit"),
    "received_at": os.environ["AUSMT_RB_AT"],
    "sender": os.environ["AUSMT_RB_SENDER"],
}, indent=1))
PYEOF
then
  rm -f "$rec"
  die "current -> builds/$TS but published.json could not be written"
fi
if ! mv -f "$rec" "$SITE/published.json"; then
  rm -f "$rec"
  die "current -> builds/$TS but published.json could not be put in place"
fi
printf 'receive-build: current -> builds/%s (published.json recorded)\n' "$TS"

# ----- prune --------------------------------------------------------------------------------------
prune_builds "$TS"
exit 0
