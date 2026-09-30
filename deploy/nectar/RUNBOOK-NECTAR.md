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
> repository and the corpus build) moves to a second, non-public instance. The corpus build is the
> memory-heavy step (the build is capped at 8 GB on the current host and has been measured past that),
> and running it beside the serving instance within the current 8 vCPU / 16 GB leaves no room for a
> flavour above m3.medium for the build.
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

---

## 3. Launch ausmt-serve

3.1  Compute → Instances → Launch Instance:
     - **Details:** name `ausmt-serve`, availability zone **QRIScloud** (where ausmt-test and its
       floating IP live).
     - **Source:** image NeCTAR Ubuntu 24.04 LTS (Noble) amd64 (the current version).
     - **Flavour:** `m3.small` (C48 D2; m3.medium only if serving needs it).
     - **Networks:** `qld-data`, the network ausmt-test's private address is on, so the floating IP on
       `qld` can be associated with it.
     - **Security groups:** `default` and `http` (80/tcp and 443/tcp only). Nothing else.
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
sudo mount /srv/ausmt                     # the fstab line cloud-init wrote (LABEL=ausmt-data)
mountpoint /srv/ausmt                     # expect: /srv/ausmt is a mountpoint
```

---

## 5. Join the tailnet

5.1  `sudo tailscale up --ssh --advertise-tags=tag:ausmt-serve --hostname ausmt-serve` and type the
     tagged auth key from step 2.2 when asked (or `--authkey` typed on the command line, then clear the
     shell history).
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

```sh
# on ausmt-test
sudo docker volume ls | grep caddy_data              # expect frontdoor_caddy_data
sudo docker run --rm -v frontdoor_caddy_data:/data:ro -v /tmp:/out caddy:2-alpine \
     tar -C /data -czf /out/caddy_data.tgz .
# from your own tailnet device: move the archive across, then delete every copy (it holds the TLS key)
scp ubuntu@<ausmt-test tailnet name>:/tmp/caddy_data.tgz . && scp caddy_data.tgz ubuntu@ausmt-serve:/tmp/
rm caddy_data.tgz ; ssh ubuntu@<ausmt-test tailnet name> sudo rm /tmp/caddy_data.tgz
# on ausmt-serve
sudo docker volume create frontdoor_caddy_data
sudo docker run --rm -v frontdoor_caddy_data:/data -v /tmp:/in:ro caddy:2-alpine \
     tar -C /data -xzf /in/caddy_data.tgz
sudo rm /tmp/caddy_data.tgz
```
Use the volume name `docker volume ls` shows on ausmt-test on both sides; the front door's compose
project is its directory, `frontdoor`, so on ausmt-serve the name is `frontdoor_caddy_data`.

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

9.1  On the box, as the operator, once: let the operator write the sidecar beside the builds.
```sh
sudo setfacl -m u:"$USER":rwx "$AUSMT_DATA_DIR/site-data/builds"
```
9.2  Prove the publish account and its gate from the box:
```sh
ssh publish@ausmt-serve receive-build.sh --current     # expect: nothing (no build yet), exit 0
ssh publish@ausmt-serve sh                              # expect: publish-gate: refused ..., exit 1
```
9.3  Publish by hand (the first run sends the whole build, about 6.6 GB going by the box's five
     builds at 33G):
```sh
cd "$AUSMT_CODE_DIR/deploy"
AUSMT_PUBLISH_TARGET=publish@ausmt-serve make publish ARGS=--dry-run
AUSMT_PUBLISH_TARGET=publish@ausmt-serve make publish
```
9.4  On ausmt-serve: `sh /srv/ausmt/code/deploy/nectar/doctor-serve.sh`. Expect PASS everywhere
     except the `gateway` WARN (the open question of step 0) and the front door's TLS or DNS lines
     that name the address still pointing at ausmt-test.

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
12.3  From any machine off the tailnet:
```sh
curl -sSI https://ausmt.auscope.org.au/ | head -1                   # HTTP/2 200
curl -sS https://ausmt.auscope.org.au/data/build.json               # the box's current build
```
      then the public checks of `deploy/frontdoor/RUNBOOK.md` step 9, and on ausmt-serve
      `doctor-serve.sh` (the DNS line now passes against `AUSMT_DOCTOR_EXPECT_IP`).
12.4  Repoint the masked-log pull on the box (`deploy/.env`), then ship once and check a file landed:
```sh
AUSMT_FRONTDOOR_LOG_REMOTE=caddylog@ausmt-serve:
sudo systemctl start ausmt-frontdoor-logs.service && ls -l "$AUSMT_DATA_DIR/logs/caddy/" | grep frontdoor
```

---

## 13. Rollback

Move the address back; nothing else is needed while ausmt-test is left running.

13.1  Network → Floating IPs → 203.101.226.191 → Disassociate, then Associate with the `ausmt-test`
      port. ausmt-test's front door still proxies to the box's reader listener, which still serves the
      box's own current.
13.2  Put the box's `AUSMT_FRONTDOOR_LOG_REMOTE` back to its ausmt-test value.
13.3  Optional: comment out `AUSMT_PUBLISH_TARGET` on the box to stop feeding the replica.

---

## 14. The quiet period, then delete ausmt-test

Leave ausmt-test running and untouched until you are satisfied; at the least, one new build has gone
box → reconcile → publish → ausmt-serve with `publish` = `ok`, and `doctor-serve.sh` is clean apart from
the known WARNs. ausmt-test costs 125 SU a year until it is deleted, shut down or not.

14.1  On ausmt-test: `sudo docker compose -f deploy/frontdoor/compose.yaml down`.
14.2  Compute → Instances → ausmt-test → Actions → **Delete Instance** → confirm.
14.3  Tailscale admin: remove the ausmt-test node, the `tag:ausmt-frontdoor` tag and its two ACL
      rules (`deploy/frontdoor/RUNBOOK.md` 10.3).

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
- **Retention:** the replica keeps `AUSMT_PUBLISH_KEEP` builds (default 5) plus current. A build
  directory without a sidecar is an interrupted transfer; `doctor-serve.sh` names it and you delete it
  once no publish is running.

---

## 16. Lifting curate

When the RAM and vCPU amendment is in place, the curation role moves to **ausmt-curate** (no floating
IP, no inbound rule, `tag:ausmt-curate`) and the box retires. The order and what moves are in
`maintainer/C48-NectarTopology.md` D10; the publish contract does not change, only the sender's host
and `AUSMT_PUBLISH_TARGET` moving with it.
