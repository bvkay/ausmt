#!/bin/sh
# AusMT deploy preflight (C33). READ-ONLY: this script CHECKS and REPORTS, it never creates,
# chowns, pulls, or edits anything. Every FAIL prints the exact command to fix it — you run it.
#
# Run it before `make rebuild-data` / `docker compose up` on any Linux, macOS, or WSL docker host.
#   cd "$AUSMT_CODE_DIR/deploy" && ./scripts/preflight.sh            # portal checks
#   AUSMT_PROFILE=gateway ./scripts/preflight.sh                     # + gateway checks
# or via the Makefile:  make preflight   /   make preflight PROFILE=gateway
#
# It loads deploy/.env (if present) the same way `docker compose` does, then checks:
#   docker + compose present; required vars set for the selected profile; the data dirs exist with
#   the right ownership (10001 site-data / 10002 gateway tree); images present; surveys-live is a
#   git checkout; the code checkout is current vs origin (warn only).
#
# Exit code: 0 if no FAIL (WARNs allowed), 1 if any FAIL. POSIX sh — no bashisms.

set -u

# ----- output helpers ------------------------------------------------------------------------------
# Colour only when stdout is a TTY (so `make preflight | tee log` stays clean).
if [ -t 1 ]; then
  C_PASS='\033[32m'; C_FAIL='\033[31m'; C_WARN='\033[33m'; C_DIM='\033[2m'; C_OFF='\033[0m'
else
  C_PASS=''; C_FAIL=''; C_WARN=''; C_DIM=''; C_OFF=''
fi

FAILS=0
WARNS=0

pass() { printf "  ${C_PASS}PASS${C_OFF}  %s\n" "$1"; }
warn() { printf "  ${C_WARN}WARN${C_OFF}  %s\n" "$1"; WARNS=$((WARNS + 1)); [ $# -ge 2 ] && printf "        ${C_DIM}fix: %s${C_OFF}\n" "$2"; return 0; }
fail() { printf "  ${C_FAIL}FAIL${C_OFF}  %s\n" "$1"; FAILS=$((FAILS + 1)); [ $# -ge 2 ] && printf "        ${C_DIM}fix: %s${C_OFF}\n" "$2"; return 0; }
# NB: named `section`, not `head` — a function named `head` would shadow the external `head`
# command used in `docker --version | head -n1` below and corrupt its output.
section() { printf "\n%s\n" "$1"; }

# ----- locate ourselves + load .env like compose does ----------------------------------------------
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEPLOY_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
ENV_FILE="$DEPLOY_DIR/.env"

# PROFILE selection: env AUSMT_PROFILE, else arg 1, else "portal". "gateway" implies portal too.
PROFILE="${AUSMT_PROFILE:-${1:-portal}}"

printf "AusMT preflight — profile: %s\n" "$PROFILE"
printf "deploy dir:  %s\n" "$DEPLOY_DIR"

# Load .env WITHOUT executing it (values may contain spaces/specials; never `source` untrusted).
# Only KEY=VALUE lines; we do not expand — we just make them visible to the checks below.
if [ -f "$ENV_FILE" ]; then
  printf "env file:    %s\n" "$ENV_FILE"
  # shellcheck disable=SC2163
  while IFS= read -r line; do
    case "$line" in
      ''|\#*) continue ;;                       # blank / comment
      *=*)
        k=${line%%=*}
        v=${line#*=}
        # strip a single layer of surrounding quotes, if any
        case "$v" in \"*\") v=${v#\"}; v=${v%\"} ;; esac
        case "$v" in \'*\') v=${v#\'}; v=${v%\'} ;; esac
        # only export names that look like real env keys
        case "$k" in [A-Za-z_][A-Za-z0-9_]*) export "$k=$v" ;; esac
        ;;
    esac
  done < "$ENV_FILE"
else
  printf "env file:    %s (not found — using process env only)\n" "$ENV_FILE"
fi

# ----- 1. docker + compose present -----------------------------------------------------------------
section "[1] docker + compose"
if command -v docker >/dev/null 2>&1; then
  pass "docker on PATH ($(docker --version 2>/dev/null | head -n1))"
  if docker info >/dev/null 2>&1; then
    pass "docker daemon reachable"
  else
    fail "docker daemon not reachable" "start Docker (e.g. 'sudo systemctl start docker' or launch Docker Desktop) and re-run"
  fi
  if docker compose version >/dev/null 2>&1; then
    pass "docker compose v2 plugin ($(docker compose version --short 2>/dev/null))"
  elif command -v docker-compose >/dev/null 2>&1; then
    warn "only legacy docker-compose v1 found — the docs assume 'docker compose' (v2)" "install the compose v2 plugin: https://docs.docker.com/compose/install/"
  else
    fail "docker compose (v2) not found" "install the compose v2 plugin: https://docs.docker.com/compose/install/"
  fi
else
  fail "docker not on PATH" "install Docker Engine + compose v2: https://docs.docker.com/engine/install/"
fi

# ----- 2. required env vars for the selected profile -----------------------------------------------
section "[2] environment variables"

check_var_set() {   # name, fixhint
  eval "val=\${$1:-}"
  if [ -n "$val" ]; then
    pass "$1 is set"
  else
    fail "$1 is not set" "$2"
  fi
}
check_var_len() {   # name, minlen, fixhint
  eval "val=\${$1:-}"
  len=${#val}
  if [ -z "$val" ]; then
    fail "$1 is not set" "$3"
  elif [ "$len" -lt "$2" ]; then
    fail "$1 is set but < $2 chars (the app fail-closes on a short key)" "$3"
  else
    pass "$1 is set (>= $2 chars)"
  fi
}

# Always required (compose keeps :? on these — everything needs them).
check_var_set AUSMT_DATA_DIR "set AUSMT_DATA_DIR=/your/host/root in $ENV_FILE"
check_var_set OWNER          "set OWNER=<the GHCR namespace the images were pushed under> in $ENV_FILE"

if [ "$PROFILE" = "gateway" ]; then
  # Softened to :- in compose (C33) — the app/runner fail-close instead — but you STILL need them
  # to actually run the gateway. Preflight is where you catch that early.
  check_var_len AUSMT_SUBMIT_KEY 16 "generate one: python3 -c \"import secrets; print(secrets.token_urlsafe(32))\"  then set AUSMT_SUBMIT_KEY in $ENV_FILE"
  check_var_set AUSMT_CODE_DIR "set AUSMT_CODE_DIR=<this checkout's path> in $ENV_FILE (gw-runner mounts \$AUSMT_CODE_DIR/gateway)"
  if [ -n "${AUSMT_CURATOR_KEYS:-}" ]; then
    pass "AUSMT_CURATOR_KEYS is set (curator UI enabled)"
  else
    warn "AUSMT_CURATOR_KEYS is not set — the curator UI returns 503 until it is" "set name:key pairs (each key >=16 chars); generate: python3 -c \"import secrets; print(secrets.token_urlsafe(32))\""
  fi
  if [ -n "${AUSMT_GIT_CREDS_DIR:-}" ]; then
    if [ -d "${AUSMT_GIT_CREDS_DIR}" ]; then
      pass "AUSMT_GIT_CREDS_DIR is set and exists (curator publish push enabled)"
    else
      fail "AUSMT_GIT_CREDS_DIR is set but the dir does not exist" "point it at a dir holding a deploy key / git credential file, or unset it to use the placeholder (push then fails => PUBLISH_FAILED)"
    fi
  else
    warn "AUSMT_GIT_CREDS_DIR is not set — curator publish push fails (=> PUBLISH_FAILED) until set" "set AUSMT_GIT_CREDS_DIR=/path/to/git-creds in $ENV_FILE (see README 'Curator publish credentials')"
  fi
fi

# ----- 3. data dirs exist with the right ownership -------------------------------------------------
section "[3] host data tree + ownership"

owner_uid_of() {   # path -> uid (portable: try stat -c, then BSD stat -f, then ls -n)
  p="$1"
  if uid=$(stat -c '%u' "$p" 2>/dev/null); then printf '%s' "$uid"; return 0; fi
  if uid=$(stat -f '%u' "$p" 2>/dev/null); then printf '%s' "$uid"; return 0; fi
  # last resort: 3rd field of `ls -nd`
  ls -nd "$p" 2>/dev/null | awk 'NR==1{print $3}'
}

DATA_DIR="${AUSMT_DATA_DIR:-}"
if [ -z "$DATA_DIR" ]; then
  warn "skipping dir checks — AUSMT_DATA_DIR is unset (see [2])"
else
  SITE_DATA="$DATA_DIR/site-data"
  SURVEYS="$DATA_DIR/surveys-live"

  if [ -d "$SITE_DATA" ]; then
    uid=$(owner_uid_of "$SITE_DATA")
    if [ "$uid" = "10001" ]; then
      pass "$SITE_DATA exists and is owned by uid 10001 (engine user)"
    else
      fail "$SITE_DATA exists but is owned by uid ${uid:-?}, not 10001 (build-runner writes it as 10001)" "sudo chown -R 10001:10001 '$SITE_DATA'"
    fi
  else
    fail "$SITE_DATA does not exist" "sudo mkdir -p '$SITE_DATA' && sudo chown -R 10001:10001 '$SITE_DATA'"
  fi

  if [ -d "$SURVEYS" ]; then
    if [ -e "$SURVEYS/.git" ]; then
      pass "$SURVEYS exists and is a git checkout"
    else
      fail "$SURVEYS exists but is not a git checkout (engine reads survey packages from it)" "git clone <ausmt-surveys-url> '$SURVEYS'"
    fi
  else
    fail "$SURVEYS does not exist" "git clone <ausmt-surveys-url> '$SURVEYS'"
  fi

  # C43 S2b-i: the shared-group publish permissions time-bomb (incident 2026-07-11). The gateway
  # publishes into surveys-live as uid 10002; WITHOUT `core.sharedRepository=group`, git creates new
  # .git/objects dirs that are NOT group-writable, so the operator (in the shared group) eventually
  # cannot `git pull`/gc — the checkout silently rots behind origin. Catch the drift EARLY: any entry
  # under .git missing the group-write bit means the shared-group model is not (fully) in place. This
  # is gateway-only (the model applies to the publish path) and needs POSIX mode bits (a Windows dev
  # box has no meaningful group-write bit — the check simply does not run there).
  if [ "$PROFILE" = "gateway" ] && [ -d "$SURVEYS/.git" ]; then
    # `-perm -020` = "has the group-write bit"; the negation finds entries that LACK it.
    offender=$(find "$SURVEYS/.git" ! -perm -020 -print 2>/dev/null | head -n 1)
    # Read the config FILE directly, not via `git -C` repo discovery: discovery fails on a repo
    # git considers dubious (preflight under sudo sees an operator-owned checkout) and on minimal
    # .git trees, silently turning a hardened PASS into a WARN (post-merge CI red 2026-07-11 —
    # this check's first ubuntu execution; it skips on Windows dev boxes).
    shared=$(git config --file "$SURVEYS/.git/config" --get core.sharedRepository 2>/dev/null || true)
    if [ -n "$offender" ]; then
      fail "$SURVEYS/.git has entries WITHOUT group-write (e.g. $offender) — a gateway publish (uid 10002) creates foreign-owned, non-g+w object dirs and eventually locks the operator out of 'git pull' (incident 2026-07-11)" "git -C '$SURVEYS' config core.sharedRepository group && sudo chgrp -R 10002 '$SURVEYS/.git' && sudo chmod -R g+rwX '$SURVEYS/.git'   (see deploy/README.md 'surveys-live must be writable by uid 10002')"
    else
      case "$shared" in
        group|true|1|2|all|world|everybody)
          pass "$SURVEYS/.git is group-writable and core.sharedRepository=$shared (shared-group publish model in place)" ;;
        *)
          warn "$SURVEYS/.git is group-writable now, but core.sharedRepository is not 'group' — a future gateway publish may create non-g+w object dirs and re-arm the lockout" "git -C '$SURVEYS' config core.sharedRepository group" ;;
      esac
    fi
  fi

  if [ "$PROFILE" = "gateway" ]; then
    GW="$DATA_DIR/gateway"
    all_ok=1
    for sub in incoming quarantine jobs state; do
      d="$GW/$sub"
      if [ -d "$d" ]; then
        uid=$(owner_uid_of "$d")
        if [ "$uid" = "10002" ]; then
          pass "$d exists and is owned by uid 10002 (gateway user)"
        else
          fail "$d owned by uid ${uid:-?}, not 10002" "sudo chown -R 10002:10002 '$GW'"
          all_ok=0
        fi
      else
        fail "$d does not exist" "sudo mkdir -p '$GW/incoming' '$GW/quarantine' '$GW/jobs' '$GW/state' && sudo chown -R 10002:10002 '$GW'"
        all_ok=0
      fi
    done
    [ "$all_ok" = 1 ] || true
  fi
fi

# ----- 4. AUSMT_CODE_DIR/gateway present for gw-runner (gateway profile only) ----------------------
if [ "$PROFILE" = "gateway" ]; then
  section "[4] gateway package mount source"
  CODE_DIR="${AUSMT_CODE_DIR:-}"
  if [ -z "$CODE_DIR" ]; then
    warn "skipping — AUSMT_CODE_DIR is unset (see [2])"
  elif [ -f "$CODE_DIR/gateway/runner/__init__.py" ] || [ -d "$CODE_DIR/gateway/runner" ]; then
    pass "$CODE_DIR/gateway exists (gw-runner mounts it read-only)"
  else
    fail "$CODE_DIR/gateway is missing or not a gateway checkout" "set AUSMT_CODE_DIR to THIS repo's checkout root (the dir holding gateway/, engine/, deploy/)"
  fi
fi

# ----- 5. images present ---------------------------------------------------------------------------
section "[5] images"
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  OWN="${OWNER:-}"; TG="${TAG:-latest}"
  if [ -z "$OWN" ]; then
    warn "cannot check images — OWNER is unset (see [2])"
  else
    check_image() {   # repo, pullhint
      img="ghcr.io/$OWN/$1:$TG"
      if docker image inspect "$img" >/dev/null 2>&1; then
        pass "$img present locally"
      else
        fail "$img not present locally" "$2"
      fi
    }
    PULL_ALL="docker compose --profile jobs --profile gateway pull   # (or: docker compose --profile \"*\" pull on compose v2.24+)"
    check_image ausmt-portal "docker compose pull   # portal is the always-on service"
    check_image ausmt-engine "$PULL_ALL"
    if [ "$PROFILE" = "gateway" ]; then
      check_image ausmt-gateway "$PULL_ALL"
    fi
  fi
else
  warn "skipping image checks — docker daemon not reachable (see [1])"
fi

# ----- 6. code checkout current vs origin (WARN only) ----------------------------------------------
section "[6] code checkout freshness (warn only)"
# The "which checkout is live" sanity check: report exactly what this deploy is running from.
CODE_ROOT=$(CDPATH= cd -- "$DEPLOY_DIR/.." && pwd)
if [ -e "$CODE_ROOT/.git" ]; then
  headline=$(git -C "$CODE_ROOT" log -1 --oneline 2>/dev/null)
  printf "        ${C_DIM}live checkout: %s${C_OFF}\n" "$CODE_ROOT"
  printf "        ${C_DIM}HEAD: %s${C_OFF}\n" "$headline"
  if git -C "$CODE_ROOT" remote get-url origin >/dev/null 2>&1; then
    if git -C "$CODE_ROOT" fetch --quiet origin 2>/dev/null; then
      LOCAL=$(git -C "$CODE_ROOT" rev-parse @ 2>/dev/null)
      BASE=$(git -C "$CODE_ROOT" merge-base @ '@{u}' 2>/dev/null || echo "")
      REMOTE=$(git -C "$CODE_ROOT" rev-parse '@{u}' 2>/dev/null || echo "")
      if [ -z "$REMOTE" ]; then
        warn "no upstream tracking branch — cannot compare to origin" "git -C '$CODE_ROOT' branch --set-upstream-to=origin/<branch>"
      elif [ "$LOCAL" = "$REMOTE" ]; then
        pass "code checkout is up to date with origin"
      elif [ "$LOCAL" = "$BASE" ]; then
        warn "code checkout is BEHIND origin — you may be running a stale Makefile/compose" "git -C '$CODE_ROOT' pull --ff-only"
      else
        warn "code checkout has diverged from origin (local commits or force-push)" "reconcile with origin before deploying: git -C '$CODE_ROOT' status"
      fi
    else
      warn "could not fetch origin (offline?) — skipping freshness compare"
    fi
  else
    warn "no 'origin' remote configured — cannot check freshness"
  fi
else
  warn "$CODE_ROOT is not a git checkout — cannot verify freshness"
fi

# ----- summary -------------------------------------------------------------------------------------
section "----------------------------------------------------------------"
if [ "$FAILS" -eq 0 ]; then
  printf "${C_PASS}preflight: PASS${C_OFF} (%d warning(s))\n" "$WARNS"
  exit 0
else
  printf "${C_FAIL}preflight: %d FAIL(s)${C_OFF}, %d warning(s) — fix the FAILs above before deploying.\n" "$FAILS" "$WARNS"
  exit 1
fi
