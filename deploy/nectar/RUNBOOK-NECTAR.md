# Runbook: the Nectar serving replica (ausmt-serve)

The numbered procedure to stand up **ausmt-serve**, feed it from the box by publish, move the public
address onto it, roll back if needed, and retire **ausmt-test**. Design and rationale:
`maintainer/C48-NectarTopology.md`. The front door itself is the C47 stack; its own runbook is
`deploy/frontdoor/RUNBOOK.md`.

**You run every remote step and type every credential.** Nothing in this repository contacts Nectar,
the box or the tailnet on its own, and no file here holds a secret. Where a step needs a credential
(a Tailscale auth key or login, a registry token, the dashboard) you type it on the host or in the
dashboard at that step.

```
internet ──▶ 203.101.226.191 ──▶ ausmt-serve: front door (Caddy, TLS, masked log) ──▶ portal :8445 (loopback)
                                        ▲
             box (curates, builds) ─────┘ publish over the tailnet: rsync + receive-build.sh
```

---

## 0. Before you start

- **Decide the public submission routes (C48 D11, question 3) first.** The serving host runs no
  gateway, so after step 12 `POST /gateway/submit`, `POST /gateway/request-key`, `GET /gateway/healthz`
  and `GET /gateway/status/*` answer 502 at the public name until a decision lands. Steps 1 to 11 are
  safe to do before that decision; step 12 (the address move) is not, unless you accept the gap.
- The amendment in step 1 is approved: the allocation has no volume storage, and the tree does not fit
  the 30 GB m3 root disk (C48 D3).
- You have Tailscale admin access and the Nectar dashboard for the project.
- The box runs the stack per `deploy/README.md`, with the reconcile timer installed.

---

## 1. File the allocation amendment

In the Nectar dashboard: Allocations → My Requests → the project → Amend/Extend. Paste and adjust:

> **Volume storage: 100 GB in QRIScloud.** The project serves the AusMT magnetotelluric data portal
> (ausmt.auscope.org.au). We are moving the public serving role from a test instance onto a
> dedicated instance whose built data tree lives on a Cinder volume: five retained builds currently
> measure 33 GB and the self-hosted basemap 2.4 GB, which does not fit the 30 GB m3 root disk.
>
> **RAM 16 to 32 GB and vCPU 8 to 16.** The curation role (submission gateway, antivirus, the survey
> repository and the corpus build) moves to a separate, non-public instance. With two instances, the
> current 8 vCPU / 16 GB leaves nothing above m3.medium for it.
>
> **Service units:** a top-up only if the allocation runs past 12 months.
>
> **A second project member**, for continuity of operation.

Wait for approval before step 4 (the volume).

---

## 2. Tailnet policy

2.1  Tailscale admin console → Access controls. Merge the entries from
     `deploy/nectar/acl-policy.hujson` into the policy (never replace the policy). Fill the
     placeholders in the console: the tag administrator, each curator's login, the login that owns the
     box's node, the box's tailnet address (the `ausmt-box` alias the front-door stanza already has).
2.2  Settings → Keys → Generate auth key, tagged `tag:ausmt-serve` (you will type it in step 5; do not
     paste it anywhere else).
2.3  A temporary admin path to ausmt-test, for steps 7 and 14.1. ausmt-test joined the tailnet as
     `ausmt-vps` without Tailscale SSH, and the front-door stanza admits only the box to its port 22,
     so add this rule to `acls` (you remove it in step 14.3):
```
{"action": "accept", "src": ["autogroup:admin"], "dst": ["tag:ausmt-frontdoor:22"]},
```
     ausmt-vps runs OpenSSH, so you log in there as `ubuntu` with your Nectar key pair:
     `ssh ubuntu@ausmt-vps`.

---

## 3. Launch ausmt-serve

3.1  Compute → Instances → Launch Instance:
     - **Details:** name `ausmt-serve`, availability zone **QRIScloud** (where ausmt-test and its
       floating IP live).
     - **Source:** image NeCTAR Ubuntu 24.04 LTS (Noble) amd64 (the current version).
     - **Flavour:** `m3.small` (C48 D2; m3.medium only if serving needs it).
     - **Networks:** `qld-data`, the network ausmt-test's private address is on, so the floating IP on
       `qld` can be associated with it.
     - **Security groups:** `http` only (80/tcp and 443/tcp inbound). Not `default`: an OpenStack
       `default` group normally admits all ingress from its own members, which would open every port
       of ausmt-serve to ausmt-test (and later ausmt-curate) over `qld-data`, outside the tailnet
       policy. Before launching, open Network → Security Groups → `http` → Manage Rules and confirm it
       carries the two Egress rules (IPv4 and IPv6, any protocol) a new group gets; without them the
       host cannot fetch packages or reach the tailnet. Also read `default`'s rules: an ingress rule
       whose Remote is the group `default` is the path this avoids.
     - **Key pair:** your usual Nectar key pair (for the bootstrap login only).
     - **Configuration → Customisation script:** paste `deploy/nectar/cloud-init-serve.yaml`. Its one
       placeholder takes the PUBLIC key of an OpenSSH publish key on the box; Tailscale SSH does not use
       it, so leave the placeholder as it is unless you publish over plain OpenSSH.
3.2  Bootstrap access: add a TEMPORARY rule to a new security group allowing 22/tcp from **your own
     address only**, attach it, and log in as `ubuntu`. You remove it in step 5.4.
3.3  Check first boot finished: `cloud-init status --wait` then `tailscale version`, `docker compose
     version`. The last line of `/var/log/cloud-init-output.log` says the volume is not mounted yet;
     that is expected.

---

## 4. The data volume

4.1  Volumes → Volumes → Create Volume: name `ausmt-serve-data`, 100 GB, availability zone
     **QRIScloud**, no source. Then Actions → Manage Attachments → attach to `ausmt-serve`.
4.2  On the host, find the new disk and label it. **Only ever on the new, empty volume:**
```sh
lsblk -f                                  # the new 100G disk with no FSTYPE, usually vdb
sudo mkfs.ext4 -L ausmt-data /dev/vdb     # replace vdb with what lsblk showed
grep ausmt-data /etc/fstab                # the line cloud-init wrote; if it is missing, see below
sudo mount /srv/ausmt
mountpoint /srv/ausmt                     # expect: /srv/ausmt is a mountpoint
```
     If `grep` prints nothing, add the line `deploy/nectar/cloud-init-serve.yaml` asks for, then mount:
```sh
echo 'LABEL=ausmt-data /srv/ausmt ext4 defaults,nofail,x-systemd.device-timeout=30s 0 2' | sudo tee -a /etc/fstab
sudo mkdir -p /srv/ausmt && sudo systemctl daemon-reload && sudo mount /srv/ausmt
```

---

## 5. Join the tailnet

5.1  Join with the tagged auth key from step 2.2, typed on the command line, then clear the shell
     history:
```sh
sudo tailscale up --ssh --advertise-tags=tag:ausmt-serve --hostname ausmt-serve --authkey <the key from 2.2>
history -c
```
     `tailscale up` never asks for a key. Without `--authkey` it prints a login URL instead; do not
     sign in there (the node would join as your own user). If you did, or the key went unused, revoke
     the key under Settings → Keys.
5.2  `tailscale status` shows the node with `tag:ausmt-serve`.
5.3  From your own tailnet device: `ssh ubuntu@ausmt-serve` (Tailscale SSH, with its sign-in check).
5.4  Remove the temporary SSH security group from the instance. From here on the host has 80 and 443
     open to the internet and nothing else.

---

## 6. Provision

```sh
sudo git clone https://github.com/bvkay/ausmt.git /srv/ausmt/code
sudo sh /srv/ausmt/code/deploy/nectar/provision-serve.sh
```
The first run stops with exit 3 and names the two `.env` files to fill. **Do step 7 before filling
them**, so the front door never starts without the certificate.

If the GHCR images are private, log in once with a read-only token you type: `sudo docker login
ghcr.io` (C48 D11, question 6).

---

## 7. Copy the certificate volume from ausmt-test

The certificate for the public name lives in the front door's `caddy_data` volume on ausmt-test.
Copying it first means the new front door starts with a valid certificate and never places an ACME
order for a name that still points at ausmt-test.

The archive holds the TLS private key, so it is readable by `ubuntu` alone at every hop and every copy
is deleted at the end. ausmt-test is reached by the temporary rule of step 2.3.

```sh
# on ausmt-test (ssh ubuntu@ausmt-vps)
sudo docker volume ls | grep caddy_data              # expect frontdoor_caddy_data
sudo docker run --rm -v frontdoor_caddy_data:/data:ro -v /tmp:/out caddy:2-alpine \
     tar -C /data -czf /out/caddy_data.tgz .
sudo chown ubuntu: /tmp/caddy_data.tgz && sudo chmod 600 /tmp/caddy_data.tgz
# from your own tailnet device: move the archive across, then delete every copy
umask 077
scp ubuntu@ausmt-vps:/tmp/caddy_data.tgz . && scp caddy_data.tgz ubuntu@ausmt-serve:/tmp/
rm caddy_data.tgz ; ssh ubuntu@ausmt-vps rm /tmp/caddy_data.tgz
# on ausmt-serve
sudo docker volume create frontdoor_caddy_data
sudo docker run --rm -v frontdoor_caddy_data:/data -v /tmp:/in:ro caddy:2-alpine \
     tar -C /data -xzf /in/caddy_data.tgz
sudo rm /tmp/caddy_data.tgz
```
Use the volume name `docker volume ls` shows on ausmt-test on both sides; the front door's compose
project is its directory, `frontdoor`, so on ausmt-serve the name is `frontdoor_caddy_data`.

When step 8 starts the front door, compose warns that volume `frontdoor_caddy_data` already exists but
was not created by Docker Compose. That is expected, and the volume is used. Confirm the certificate
is in it with `sudo docker compose -f /srv/ausmt/code/deploy/frontdoor/compose.yaml exec frontdoor ls
/data/caddy/certificates`.

---

## 8. Fill the .env files and finish provisioning

- `/srv/ausmt/code/deploy/.env`: `OWNER` (the GHCR namespace) and `TAG` (the tag the box runs).
- `/srv/ausmt/code/deploy/frontdoor/.env`: `AUSMT_PUBLIC_NAME=ausmt.auscope.org.au`,
  `AUSMT_LEGACY_REDIRECT_NAME` exactly as ausmt-test has it, `AUSMT_ACME_EMAIL`, and
  `AUSMT_DOCTOR_EXPECT_IP=203.101.226.191`. Leave `AUSMT_BOX_READER_UPSTREAM` as provisioning set it
  (`http://127.0.0.1:8445`).

```sh
sudo sh /srv/ausmt/code/deploy/nectar/provision-serve.sh     # now runs to the end
```
It fetches the basemap (a large download; set `AUSMT_SKIP_BASEMAP=1` and copy
`/srv/ausmt/basemap/*.pmtiles` from the box instead if you prefer), starts the portal with `make up`,
then the front door with `install-frontdoor.sh`.

---

## 9. Seed: the first publish from the box

Every step here runs on the box as the operator account (the `User=` of the reconcile unit), in a shell
with the two paths `deploy/README.md` exports:
```sh
export AUSMT_DATA_DIR=/srv/ausmt AUSMT_CODE_DIR=~/ausmt-code
```

9.1  Once: let the operator write the sidecar beside the builds.
```sh
sudo setfacl -m u:"$USER":rwx "$AUSMT_DATA_DIR/site-data/builds"
```
9.2  Prove the publish account and its gate from the box:
```sh
ssh publish@ausmt-serve receive-build.sh --current     # expect: nothing (no build yet), exit 0
ssh publish@ausmt-serve sh                              # expect: publish-gate: refused ..., exit 1
```
     Then the two channels that do not start a login shell, so the gate never sees them. **Both must
     fail:**
```sh
sftp -b /dev/null publish@ausmt-serve                   # expect: a failure, no sftp session
ssh -N -o ExitOnForwardFailure=yes -L 18445:127.0.0.1:8445 publish@ausmt-serve &
sleep 3; curl -sS -m 5 http://127.0.0.1:18445/ ; kill %1 # expect: the ssh exited, curl cannot connect
```
     If either succeeds, the publish account is not confined to the gate over Tailscale SSH. Stop and
     settle C48 D11 question 5 before going on.
9.3  Publish by hand. The first run sends the whole build; read its size first, so you know what the
     upload will take:
```sh
du -sh "$AUSMT_DATA_DIR/site-data/current/"
cd "$AUSMT_CODE_DIR/deploy"
AUSMT_PUBLISH_TARGET=publish@ausmt-serve make publish ARGS=--dry-run
AUSMT_PUBLISH_TARGET=publish@ausmt-serve make publish
```
9.4  On ausmt-serve: `sh /srv/ausmt/code/deploy/nectar/doctor-serve.sh`. Expect PASS everywhere
     except the `gateway` WARN (the open question of step 0). The DNS and TLS lines pass already: the
     public name resolves to the address step 8 set as expected, and it still reaches ausmt-test,
     which presents the same certificate. Neither line tells the two hosts apart.

---

## 10. Verify on ausmt-serve before the address moves

Everything below runs ON ausmt-serve against its own front door, with the public name resolved to
loopback, so the certificate, both walls and the served tree are checked before any visitor sees them.

```sh
N=ausmt.auscope.org.au
R="--resolve $N:443:127.0.0.1"
curl -sS $R -o /dev/null -w '%{http_code}\n' https://$N/                             # 200
curl -sS $R -o /dev/null -w '%{http_code}\n' https://$N/data/catalogue.json          # 200
curl -sS $R -o /dev/null -w '%{http_code}\n' https://$N/add-survey.html              # 200
curl -sS $R -o /dev/null -w '%{http_code}\n' https://$N/gateway/curator/queue        # 404 (walled)
curl -sS $R -o /dev/null -w '%{http_code}\n' https://$N/gateway/healthz              # 502 until step 0 is decided
curl -sS $R https://$N/data/build.json                                               # the box's current build
echo | openssl s_client -connect 127.0.0.1:443 -servername $N 2>/dev/null | openssl x509 -noout -issuer -enddate
```
The `build.json` must name the same `build_id` and `source_commit` as the box's
`site-data/current/build.json`.

---

## 11. Turn on the automatic publish

On the box, add to `deploy/.env` (the reconcile unit reads it):
```sh
AUSMT_PUBLISH_TARGET=publish@ausmt-serve
```
The next reconcile pass publishes (a no-op when the replica already serves the box's current). Check:
```sh
python3 -m json.tool "$AUSMT_DATA_DIR/gateway/state/reconcile-status.json" | grep -E '"(action|publish|publish_detail)"'
```
`publish` must read `ok`. A `failed` pass exits 1, names the step in `publish_detail`, and the alert
timer fail-pings on it.

---

## 12. Move the floating IP

Only after steps 9 to 11 are green and step 0 is decided.

12.1  Network → Floating IPs → the row for **203.101.226.191** (mapped to ausmt-test) → Actions →
      **Disassociate** → confirm.
12.2  Same row → Actions → **Associate** → Port to be associated: the `ausmt-serve` port
      (10.255.x.x on qld-data) → **Associate**.
12.3  From any machine off the tailnet, send a request only this check makes:
```sh
M=cutover-$(date +%s); echo $M
curl -sSI "https://ausmt.auscope.org.au/?check=$M" | head -1        # HTTP/2 200
```
      then on ausmt-serve prove it arrived there:
```sh
sudo grep -c "check=<the M printed above>" /var/log/caddy/access-frontdoor.json   # 1 or more
```
      The DNS and `build.json` checks pass before and after the move alike (both hosts serve the box's
      current build under the same certificate), so only this log line proves the address moved. Then
      run the public checks of `deploy/frontdoor/RUNBOOK.md` step 9, and `doctor-serve.sh` on
      ausmt-serve.
12.4  Repoint the masked-log pull on the box. Both front doors write `access-frontdoor.json`, and the
      box keeps one copy of each name, so the first pull from ausmt-serve would overwrite what
      ausmt-test logged since the last pull, before the daily stats fold has read it. On the box:
```sh
sudo systemctl start ausmt-frontdoor-logs.service      # a last pull from ausmt-test, which now gets no traffic
cd "$AUSMT_DATA_DIR/logs/caddy"
mv access-frontdoor.json access-frontdoor-ausmt-test.json   # still read by the fold, never overwritten
```
      Then set `AUSMT_FRONTDOOR_LOG_REMOTE=caddylog@ausmt-serve:` in `deploy/.env`, pull once, and
      check that `access-frontdoor.json` is back (it can only have come from ausmt-serve):
```sh
sudo systemctl start ausmt-frontdoor-logs.service && ls -l access-frontdoor.json
```
      Delete `access-frontdoor-ausmt-test.json` once the fold has passed the day of the move.

---

## 13. Rollback

Move the address back; nothing else is needed while ausmt-test is left running.

13.1  Network → Floating IPs → 203.101.226.191 → Disassociate, then Associate with the `ausmt-test`
      port. ausmt-test's front door still proxies to the box's reader listener, which still serves the
      box's own current.
13.2  Keep what ausmt-serve logged, as in 12.4 the other way round: pull once more, move
      `access-frontdoor.json` aside as `access-frontdoor-ausmt-serve.json`, then put the box's
      `AUSMT_FRONTDOOR_LOG_REMOTE` back to its ausmt-test value.
13.3  Optional: comment out `AUSMT_PUBLISH_TARGET` on the box to stop feeding the replica.

---

## 14. The quiet period, then delete ausmt-test

Leave ausmt-test running and untouched until you are satisfied; at the least, one new build has gone
box → reconcile → publish → ausmt-serve with `publish` = `ok`, and `doctor-serve.sh` is clean apart from
the known WARNs. ausmt-test costs 125 SU a year until it is deleted, shut down or not.

14.1  On ausmt-test (`ssh ubuntu@ausmt-vps`, by the rule of step 2.3):
      `cd <the checkout holding deploy/frontdoor> && sudo docker compose -f deploy/frontdoor/compose.yaml down`.
14.2  Compute → Instances → ausmt-test → Actions → **Delete Instance** → confirm.
14.3  Tailscale admin: remove the ausmt-test node, the `tag:ausmt-frontdoor` tag, its two ACL rules
      (`deploy/frontdoor/RUNBOOK.md` 10.3) and the temporary admin rule of step 2.3.

---

## 15. Day 2

- **Health:** `sh /srv/ausmt/code/deploy/nectar/doctor-serve.sh` on ausmt-serve; the box's
  `reconcile-status.json` `publish` field and the alert timer cover the publish path.
- **Updates to the repo:** `sudo sh /srv/ausmt/code/deploy/nectar/provision-serve.sh` again. It
  fast-forwards the checkout, reinstalls the receiver and the gates, re-runs `make up` and
  `install-frontdoor.sh` (which reloads the running edge in place).
- **Image tag:** keep `TAG` in ausmt-serve's `deploy/.env` equal to the box's, then re-run
  provisioning.
- **Host upgrades:** unattended upgrades apply security updates; a kernel update needs a reboot you
  schedule. The containers restart on boot and the volume mounts by label (`nofail`: if it does not,
  `doctor-serve.sh` FAILs its volume line).
- **Rolling the public site back to an older build:** do it on the box as a curator rollback. The
  pinned reconcile pass publishes the rolled-back build to the replica. A replica-only `make publish
  ARGS="--build <ts>"` is overwritten by the next reconcile pass, which publishes the box's current.
- **Retention:** the replica keeps the `AUSMT_PUBLISH_KEEP` newest complete builds (default 5, 1 to
  999, set on the sender), with current always among them. A build directory without a sidecar is an
  interrupted transfer; `doctor-serve.sh` names it and you delete it once no publish is running.
- **Curators in phase one:** the tailnet policy grants `group:curators` port 8444 on the box, and on
  the box 8444 is the gateway's loopback bind (`127.0.0.1:8444` in `deploy/compose.yaml`), so an
  invited curator reaches nothing there. Either you decide to front the workbench on that port on the
  box (`sudo tailscale serve --bg --https=8444 http://127.0.0.1:8443`; C48 D11 question 4), or
  curator onboarding waits for the curate lift.

---

## 16. Lifting curate

When the RAM and vCPU amendment is in place, the curation role moves to **ausmt-curate** (no floating
IP, no security group that admits inbound traffic, `default` included; `tag:ausmt-curate`) and the box
retires. The order and what moves are in
`maintainer/C48-NectarTopology.md` D10; the publish contract does not change, only the sender's host
and `AUSMT_PUBLISH_TARGET` moving with it.
