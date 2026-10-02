#!/bin/sh
# AusMT serving replica (ausmt-serve) provisioning. POSIX sh, shellcheck-clean. Runs as root on the
# serving host, from the checkout it keeps up to date:
#
#   sudo sh /srv/ausmt/code/deploy/nectar/provision-serve.sh
#
# IDEMPOTENT: every step checks before it acts, so re-running it after a `git pull` (or to finish a
# run that stopped at the .env step) converges on the same host. It contacts GitHub (the read-only
# clone), GHCR (image pulls) and the basemap source; it never holds a credential. Procedure and the
# steps around it: deploy/nectar/RUNBOOK-NECTAR.md. Design: maintainer/C48-NectarTopology.md.
#
# WHAT IT DOES, in order
#   1. refuses unless the data root is its own mounted volume (a tree laid on the root disk would
#      vanish behind the volume when it mounts)
#   2. clones the repository read-only over https at the code dir, or fast-forwards it
#   3. lays down the data tree with the ownership deploy/README.md gives it: site-data and
#      site-data/builds owned by uid 10001 (the only writer here is the publish account, which is
#      uid 10001), basemap and logs/caddy owned by root
#   4. installs the receiver and the two account gates, and makes each gate its account's login
#      shell: publish (uid 10001, receives builds) and caddylog (reads the masked front-door log);
#      installs the serve doctor at /usr/local/bin/ausmt-doctor-serve, outside the data volume
#   5. orders Docker after the data volume's mount and tailscaled (a docker.service drop-in, the
#      same one first boot writes), reloads systemd and enables Docker
#   6. renders deploy/.env from deploy/nectar/serve.env.example and deploy/frontdoor/.env from
#      deploy/frontdoor/.env.example with the reader upstream on loopback, the first time; carries
#      AUSMT_GATEWAY_UPSTREAM from deploy/.env into deploy/frontdoor/.env on every run; stops with
#      exit 3 while either still has a value to fill
#   7. fetches the self-hosted basemap when compose mounts one and it is not there yet
#   8. starts the portal (make up) and then the front door (install-frontdoor.sh)
#
# WHAT IT NEVER DOES: install a timer or unit of the curation role, start the gateway profile, or
# write a secret. The serve role receives builds; it does not build, back up or curate.
#
# ENV (all optional)
#   AUSMT_DATA_DIR      data root (default /srv/ausmt)
#   AUSMT_CODE_DIR      checkout (default $AUSMT_DATA_DIR/code)
#   AUSMT_REPO_URL      repository to clone (default https://github.com/bvkay/ausmt.git)
#   AUSMT_SKIP_BASEMAP  1 skips the basemap fetch (copy the files across instead)
#
# EXIT: 0 provisioned; 1 a step failed; 3 an .env still needs filling in.

set -eu

DATA_DIR="${AUSMT_DATA_DIR:-/srv/ausmt}"
CODE_DIR="${AUSMT_CODE_DIR:-$DATA_DIR/code}"
REPO_URL="${AUSMT_REPO_URL:-https://github.com/bvkay/ausmt.git}"

die() { printf 'provision-serve: ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf 'provision-serve: %s\n' "$*"; }

[ "$(id -u)" -eq 0 ] || die "run as root (sudo sh $0)"

# ----- 1. the volume ------------------------------------------------------------------------------
mountpoint -q "$DATA_DIR" \
  || die "$DATA_DIR is not a mount point. Attach the volume, label it ausmt-data and mount it first (RUNBOOK-NECTAR.md, the volume step)."

# ----- 2. the checkout ----------------------------------------------------------------------------
if [ -d "$CODE_DIR/.git" ]; then
  log "fast-forwarding $CODE_DIR"
  git -C "$CODE_DIR" pull --ff-only || die "git pull --ff-only failed in $CODE_DIR (a local edit on this host?)"
else
  log "cloning $REPO_URL into $CODE_DIR (read-only, https)"
  git clone "$REPO_URL" "$CODE_DIR" || die "git clone of $REPO_URL failed"
fi
DEPLOY="$CODE_DIR/deploy"

# ----- 3. the data tree ---------------------------------------------------------------------------
log "laying down the data tree under $DATA_DIR"
install -d -o 10001 -g 10001 -m 0755 "$DATA_DIR/site-data" "$DATA_DIR/site-data/builds"
install -d -o root -g root -m 0755 "$DATA_DIR/basemap" "$DATA_DIR/logs" "$DATA_DIR/logs/caddy"

# ----- 4. the receiver, the gates, the two accounts -----------------------------------------------
log "installing the receiver and the account gates"
install -o root -g root -m 0755 "$CODE_DIR/deploy/scripts/receive-build.sh" /usr/local/bin/receive-build.sh
install -o root -g root -m 0755 "$CODE_DIR/deploy/nectar/publish-gate.sh" /usr/local/bin/ausmt-publish-gate
install -o root -g root -m 0755 "$CODE_DIR/deploy/nectar/caddylog-gate.sh" /usr/local/bin/ausmt-caddylog-gate

getent group 10001 >/dev/null || groupadd -g 10001 ausmt
if ! id -u publish >/dev/null 2>&1; then
  useradd -u 10001 -g 10001 -M -d /var/lib/ausmt-publish -s /usr/sbin/nologin publish
fi
[ "$(id -u publish)" = 10001 ] || die "the publish account exists with uid $(id -u publish), not 10001, so it cannot write site-data"
install -d -o root -g root -m 0755 /var/lib/ausmt-publish
usermod -s /usr/local/bin/ausmt-publish-gate publish

if ! id -u caddylog >/dev/null 2>&1; then
  useradd -r -M -d /var/lib/ausmt-caddylog -s /usr/sbin/nologin caddylog
fi
install -d -o root -g root -m 0755 /var/lib/ausmt-caddylog
usermod -s /usr/local/bin/ausmt-caddylog-gate caddylog
mkdir -p /var/log/caddy
# Read-only for the log account, now and for every file Caddy rolls in later (the default ACL).
setfacl -R -m u:caddylog:rX /var/log/caddy
setfacl -d -m u:caddylog:rX /var/log/caddy

# The doctor has to answer when the volume did not mount, so it is copied onto the root disk.
install -o root -g root -m 0755 "$CODE_DIR/deploy/nectar/doctor-serve.sh" /usr/local/bin/ausmt-doctor-serve

# ----- 5. boot ordering ---------------------------------------------------------------------------
# Docker starts only once the data volume is mounted, so a boot without it leaves no edge at all
# rather than containers serving empty stubs on the root disk behind a valid certificate; and only
# after tailscaled, so the front door never dials the curation host before the tailnet resolves it.
# Unmounting the volume stops Docker with it. cloud-init-serve.yaml writes the same drop-in.
log "ordering Docker after the $DATA_DIR mount and tailscaled"
install -d -o root -g root -m 0755 /etc/systemd/system/docker.service.d
cat > /etc/systemd/system/docker.service.d/ausmt-serve.conf <<UNIT
[Unit]
RequiresMountsFor=$DATA_DIR
Wants=tailscaled.service
After=tailscaled.service
UNIT
chmod 0644 /etc/systemd/system/docker.service.d/ausmt-serve.conf
systemctl daemon-reload
systemctl enable --now docker || die "Docker did not start (systemctl status docker; is $DATA_DIR mounted?)"

# ----- 6. the two .env files ----------------------------------------------------------------------
if [ ! -f "$DEPLOY/.env" ]; then
  install -m 0600 "$DEPLOY/nectar/serve.env.example" "$DEPLOY/.env"
  log "wrote $DEPLOY/.env from deploy/nectar/serve.env.example"
fi
if [ ! -f "$DEPLOY/frontdoor/.env" ]; then
  install -m 0600 "$DEPLOY/frontdoor/.env.example" "$DEPLOY/frontdoor/.env"
  log "wrote $DEPLOY/frontdoor/.env from deploy/frontdoor/.env.example"
fi
# The reader shares this host with the front door, so the upstream is always the loopback reader
# listener; it is set here rather than left to the template, whose example names the tailnet box.
if grep -q '^AUSMT_BOX_READER_UPSTREAM=' "$DEPLOY/frontdoor/.env"; then
  sed -i 's#^AUSMT_BOX_READER_UPSTREAM=.*#AUSMT_BOX_READER_UPSTREAM=http://127.0.0.1:8445#' "$DEPLOY/frontdoor/.env"
else
  printf 'AUSMT_BOX_READER_UPSTREAM=http://127.0.0.1:8445\n' >> "$DEPLOY/frontdoor/.env"
fi
# The public gateway routes leave this host for the curation host's reader listener, named once in
# deploy/.env and carried into the front door's .env, where its compose file reads it.
gw="$(sed -n 's/^AUSMT_GATEWAY_UPSTREAM=//p' "$DEPLOY/.env" | tail -n 1)"
case "$gw" in
  ''|*REPLACE_WITH*) ;;
  *)
    if grep -q '^AUSMT_GATEWAY_UPSTREAM=' "$DEPLOY/frontdoor/.env"; then
      sed -i "s#^AUSMT_GATEWAY_UPSTREAM=.*#AUSMT_GATEWAY_UPSTREAM=$gw#" "$DEPLOY/frontdoor/.env"
    else
      printf 'AUSMT_GATEWAY_UPSTREAM=%s\n' "$gw" >> "$DEPLOY/frontdoor/.env"
    fi
    ;;
esac
todo=""
if grep -q 'REPLACE_WITH' "$DEPLOY/.env"; then
  todo="$todo $DEPLOY/.env ($(grep '=REPLACE_WITH' "$DEPLOY/.env" | cut -d= -f1 | tr '\n' ' ' | sed 's/ $//'))"
fi
for var in AUSMT_PUBLIC_NAME AUSMT_ACME_EMAIL; do
  if grep -Eq "^$var=\$" "$DEPLOY/frontdoor/.env"; then
    todo="$todo $DEPLOY/frontdoor/.env ($var)"
  fi
done
if [ -n "$todo" ]; then
  printf 'provision-serve: fill in, then re-run this script:%s\n' "$todo" >&2
  exit 3
fi

# ----- 7. the basemap -----------------------------------------------------------------------------
if grep -q '/basemap:/srv/basemap' "$DEPLOY/compose.yaml" && [ "${AUSMT_SKIP_BASEMAP:-0}" != 1 ]; then
  if [ -f "$DATA_DIR/basemap/world.pmtiles" ] && [ -f "$DATA_DIR/basemap/region.pmtiles" ]; then
    log "basemap already present under $DATA_DIR/basemap"
  else
    log "fetching the self-hosted basemap (fetch-basemap.sh; a large download)"
    AUSMT_DATA_DIR="$DATA_DIR" sh "$DEPLOY/scripts/fetch-basemap.sh" || die "fetch-basemap.sh failed"
  fi
fi

# ----- 8. the portal, then the front door ---------------------------------------------------------
log "starting the portal (make up)"
(cd "$DEPLOY" && make up) || die "make up failed (the GHCR images are public: check OWNER and TAG in $DEPLOY/.env)"
log "starting the front door (install-frontdoor.sh, reader upstream AUSMT_BOX_READER_UPSTREAM=http://127.0.0.1:8445)"
(cd "$DEPLOY/frontdoor" && sh ./install-frontdoor.sh) || die "install-frontdoor.sh failed"

log "done. Check the host with: sudo ausmt-doctor-serve"
log "the replica serves once the first publish arrives (RUNBOOK-NECTAR.md, seeding)"
