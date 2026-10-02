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
                                        ▲        │
                                        │        └─ 4 public /gateway routes ──▶ box reader :8445 (tailnet) ──▶ gateway
             box (curates, builds) ─────┘ publish over the tailnet: rsync + receive-build.sh
```

---

## 0. Before you start

- **The publish code is on `main` and the box runs it.** Step 6 clones `main` and runs
  `deploy/nectar/provision-serve.sh`, and step 9 runs `make publish` on the box; neither exists until
  the publish branch is merged. So, before step 1: the branch is merged into `main` and pushed; the
  GHCR images have been built from that commit; the box has been updated to that commit and its
  `TAG` by the usual pass (`deploy/README.md`, "Update to a new image tag"); and one green box build
  of that code has been served through ausmt-test for at least a day (`make doctor` clean, the public
  `/data/build.json` naming that build).
- **Hold engine and library changes from step 9 until step 12 is done.** A change that re-keys the
  MTH5 tier makes the next publish resend every h5 file, 2.89 GB of the 7.5 GB tree, in the middle of
  the cutover.
- **The amendment is filed in step 1 and its volume must be approved before step 4.** Steps 1 to 3 run
  while it is pending. If it is still pending at step 4, take the proof serve on the root disk (4A)
  instead, and move to the volume when it is granted; the address never moves onto the root disk.
- **The public submission routes stay live through the address move** (C48 D12). The serving host
  runs no gateway, so its front door sends `POST /gateway/submit`, `POST /gateway/request-key`,
  `GET /gateway/healthz` and `GET /gateway/status/*` to the box's reader listener over the tailnet
  (`AUSMT_GATEWAY_UPSTREAM`, step 8), exactly where ausmt-test sends them today.
- You have Tailscale admin access and the Nectar dashboard for the project.
- The box runs the stack per `deploy/README.md`, with the reconcile timer installed.

---

## 1. File the allocation amendment

In the Nectar dashboard: Allocations → My Requests → the project → Amend/Extend. Paste and adjust:

> **Volume storage: 200 GB in QRIScloud, as two 100 GB volumes.** The project serves the AusMT
> magnetotelluric data portal (ausmt.auscope.org.au). We are moving it from a test instance onto two
> instances, a public serving instance and a non-public curation instance, and neither one's data fits
> the 30 GB m3 root disk. One built data tree of the current corpus (15,265 stations) measures
> 7.5 GB. The serving instance keeps five builds, up to 37.5 GB, plus a 2.4 GB self-hosted basemap.
> The curation instance holds the builds, a build cache capped at 16 GiB that must share their
> filesystem, the survey repository and the submission state: about 28 GB today and 48 GB with the
> cache at its cap, before the operating system and container images. 100 GB each leaves room for the
> corpus to grow.
>
> **RAM 16 to 32 GB and vCPU 8 to 16.** Headroom to run the corpus build on a curation instance
> larger than m3.medium, with more workers, which the current 8 vCPU / 16 GB leaves no room for beside
> the serving instance.
>
> **Service units:** a top-up only if the allocation runs past 12 months.
>
> **A second project member**, for continuity of operation.

**The RAM and vCPU line is optional; include it or drop it when filing.** The build fits an m3.medium
(C48 D3), so the line buys only more build workers, and it buys a shape the SU line does not fund:
serve m3.small plus curate m3.large is (0.057 + 0.228) SU/h × 8,760 h = 2,497 SU a year, about 2,500
against the 2,000 budget. Kept, it needs the SU line changed to a top-up of at least 500 SU a year.
Dropped, curate runs on m3.medium and the volume line may be approved sooner on its own.

Steps 1 to 3 run while it is pending. Step 4 needs the volume, or the proof serve of 4A.

---

## 2. Tailnet policy

2.1  Tailscale admin console → Access controls. Merge the entries from
     `deploy/nectar/acl-policy.hujson` into the policy (never replace the policy). Fill the
     placeholders in the console: the tag administrator, each curator's login, the login that owns the
     box's node, the box's tailnet address (the `ausmt-box` alias the front-door stanza already has).
     Merge its `tests` and `sshTests` stanzas too, placeholders filled the same way: they pin what
     `tag:ausmt-serve` may and may not reach, and the console runs them on every save and refuses a
     policy that breaks them. Before saving, preview the rules for `tag:ausmt-serve` in the console and
     confirm it reaches the box on 8445 and nothing else; the stock policy's allow-all rule, if it is
     still there, shows up here.
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

3.0  Network → Routers → the project's router: an **External Network** set with **SNAT** enabled, and
     an interface on `qld-data`. ausmt-serve has no internet address of its own except the bootstrap
     one (3.2 to 5.4) and the public one (from step 12), so apt, GitHub, GHCR and Tailscale traffic
     leaves through this router's SNAT; so does ausmt-test's tailnet traffic once step 12 takes its
     address. If any of the three is missing, fix it in the dashboard before launching.
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
3.2  Bootstrap access. The public floating IP stays on ausmt-test until step 12, so ausmt-serve has
     only its private `qld-data` address. Give it the project's SECOND floating IP (the quota is 2,
     C48 D1) for the bootstrap: Network → Floating IPs → **Allocate IP to Project** (pool `qld`), then
     that row's Actions → **Associate** → the `ausmt-serve` port. Add a TEMPORARY rule to a new
     security group allowing 22/tcp from **your own address only**, attach it, and log in as `ubuntu`
     at the bootstrap address. You release both in step 5.4; the bootstrap address is never the
     public name's.
3.3  Check first boot finished: `cloud-init status --wait` then `tailscale version`, `docker compose
     version`. The last line of `/var/log/cloud-init-output.log` says the volume is not mounted yet;
     that is expected.

---

## 4. The data volume

4.1  Volumes → Volumes → Create Volume: name `ausmt-serve-data`, 100 GB (half the grant; the other
     half is ausmt-curate's, section 16), availability zone **QRIScloud**, no source. Then Actions →
     Manage Attachments → attach to `ausmt-serve`.
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

4A.  **While the amendment is pending: a proof serve on the root disk.** The m3 root disk is 30 GB.
     At `AUSMT_PUBLISH_KEEP=1` the replica holds one build and the basemap, 9.9 GB (7.5 + 2.4), plus
     a second build while a receive is in flight, at most another 7.5 GB, which leaves about 12.6 GB
     (30 - 17.4) for Ubuntu, the Docker images and the logs. Add `AUSMT_PUBLISH_KEEP=1` to the box's
     `deploy/.env` before step 9 (`make publish` and the reconcile unit both read it). Provisioning
     refuses a data root that is not a mount point, so the tree lives in a directory on the root disk,
     bind-mounted at `/srv/ausmt` in place of the volume line cloud-init wrote:
```sh
sudo mkdir -p /var/lib/ausmt-proof /srv/ausmt
sudo sed -i 's|^LABEL=ausmt-data |#&|' /etc/fstab                  # park the volume line
echo '/var/lib/ausmt-proof /srv/ausmt none bind 0 0' | sudo tee -a /etc/fstab
sudo systemctl daemon-reload && sudo mount /srv/ausmt && mountpoint /srv/ausmt
```
     Run steps 5 to 11 on it. Move it to the volume before step 12, once the volume is granted: create
     and label the volume as in 4.1 and 4.2 (stop before its `mount`), then, with Docker stopped so
     neither stack writes during the copy:
```sh
sudo systemctl stop docker.socket docker.service          # both stacks down
sudo mkdir -p /mnt/ausmt-new && sudo mount LABEL=ausmt-data /mnt/ausmt-new
sudo rsync -aH /var/lib/ausmt-proof/ /mnt/ausmt-new/      # -H keeps the links between builds
sudo umount /mnt/ausmt-new /srv/ausmt
sudo sed -i -e '\|^/var/lib/ausmt-proof |d' -e 's|^#\(LABEL=ausmt-data \)|\1|' /etc/fstab
sudo systemctl daemon-reload && sudo mount /srv/ausmt && mountpoint /srv/ausmt
sudo systemctl start docker                               # both stacks up
sudo ausmt-doctor-serve
```
     Once the doctor is clean, remove `AUSMT_PUBLISH_KEEP=1` from the box's `deploy/.env` (the
     default keeps 5) and `sudo rm -r /var/lib/ausmt-proof`. The certificate is not on the data tree
     (it is in Docker's `frontdoor_caddy_data` volume on the root disk), so the move does not touch it.

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
5.4  From the tailnet session of 5.3, remove the temporary SSH security group from the instance, then
     Network → Floating IPs → the bootstrap address → Actions → **Disassociate**, and **Release
     Floating IP** on the same row. From here until step 12 the host has no internet address: you reach
     it over the tailnet, and it reaches the internet through the router's SNAT (3.0). From step 12 it
     has 80 and 443 open to the internet and nothing else.
5.5  Prove the tailnet fence from the serving host's side. The policy is merged into a live policy
     this repository cannot see, so these are the evidence that nothing broader admits the serving
     host. On ausmt-serve:
```sh
B=<the box's MagicDNS name: the host in ausmt-test's AUSMT_BOX_READER_UPSTREAM>
nc -z -v -w 5 "$B" 22                                              # expect: timed out or refused, never "succeeded"
curl -sS -k -m 5 -o /dev/null -w '%{http_code}\n' "https://$B/gateway/curator/queue"
                                                                   # expect: 000 and a curl error (no connection)
curl -sS -m 5 -o /dev/null -w '%{http_code}\n' "http://$B:8445/"   # expect: 200 (the reader listener)
```
     If the box's port 22 connects or the queue path answers with any HTTP status, stop: a broader
     rule in the live policy admits the serving host. Find it in the console's rule preview for
     `tag:ausmt-serve` (2.1) and remove it, then run 5.5 again. If 8445 does not answer 200, check the
     `tag:ausmt-serve` rule of 2.1 and the box's `tailscale serve` reader port. Run 5.5 again after
     every policy change that touches these tags.

---

## 6. Provision

```sh
sudo git clone https://github.com/bvkay/ausmt.git /srv/ausmt/code
sudo sh /srv/ausmt/code/deploy/nectar/provision-serve.sh
```
The first run stops with exit 3 and names the two `.env` files to fill. **Do step 7 before filling
them**, so the front door never starts without the certificate.

The GHCR images are public: an anonymous token read the tags list of `ghcr.io/bvkay/ausmt-portal`
(HTTP 200) on 2026-09-30, and provisioning's own pull in step 8 is the first anonymous pull on this
host. This host holds no registry credential and needs no `docker login`.

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

- `/srv/ausmt/code/deploy/.env`: `OWNER` (the GHCR namespace), `TAG` (the tag the box runs) and
  `AUSMT_GATEWAY_UPSTREAM`, the box's reader listener: the value ausmt-test has as
  `AUSMT_BOX_READER_UPSTREAM` in its `deploy/frontdoor/.env` (the box's MagicDNS name and the
  tailscale-serve reader port). Provisioning copies it into `deploy/frontdoor/.env`.
- `/srv/ausmt/code/deploy/frontdoor/.env`: `AUSMT_PUBLIC_NAME=ausmt.auscope.org.au`,
  `AUSMT_LEGACY_REDIRECT_NAME` exactly as ausmt-test has it, `AUSMT_ACME_EMAIL`, and
  `AUSMT_DOCTOR_EXPECT_IP=203.101.226.191`. Leave `AUSMT_BOX_READER_UPSTREAM` as provisioning set it
  (`http://127.0.0.1:8445`).

```sh
sudo sh /srv/ausmt/code/deploy/nectar/provision-serve.sh     # now runs to the end
```
It fetches the basemap (a large download; set `AUSMT_SKIP_BASEMAP=1` and copy
`/srv/ausmt/basemap/*.pmtiles` from the box instead if you prefer), pulls the portal image and the
front door's caddy image, starts the portal with `make up`, then the front door with
`install-frontdoor.sh`. It also installs, on every run, two things that live
off the data volume: the serve doctor at `/usr/local/bin/ausmt-doctor-serve` (a copy of
`deploy/nectar/doctor-serve.sh`, run as `sudo ausmt-doctor-serve` because both `.env` files are
root-only), and the Docker boot ordering `/etc/systemd/system/docker.service.d/ausmt-serve.conf`
(`RequiresMountsFor=/srv/ausmt`, `After=tailscaled.service`; step 15, "The volume did not mount").

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
     The gate confines command sessions, and these two prove it. Tailscale SSH serves SFTP itself,
     in-process as the account, after the gate refuses its login-shell probe, so an SFTP session never
     reaches the gate. That is accepted for phase one by owner ruling 2026-10-02, while the box is the
     sender: the publish account's writable tree is `site-data`, the tree it exists to replace, the
     serving host holds no secret, and the `caddylog` account can read world-readable files only. So
     this step has no SFTP or port-forwarding probe. The ruling is revisited at the curate lift
     (C48 D11, question 2).
9.3  Publish by hand. The first run sends the whole build; read its size first, so you know what the
     upload will take:
```sh
du -sh "$AUSMT_DATA_DIR/site-data/current/"
cd "$AUSMT_CODE_DIR/deploy"
AUSMT_PUBLISH_TARGET=publish@ausmt-serve make publish ARGS=--dry-run
AUSMT_PUBLISH_TARGET=publish@ausmt-serve make publish
```
9.4  On ausmt-serve: `sudo ausmt-doctor-serve`. Expect PASS everywhere,
     the `gateway` line included: it asks this host's front door for `/gateway/healthz`, which the
     box answers. A `gateway` WARN means this host cannot reach the box's reader port: check the
     `tag:ausmt-serve` rule of step 2.1 and `AUSMT_GATEWAY_UPSTREAM`. The DNS and TLS lines pass
     already: the public name resolves to the address step 8 set as expected, and it still reaches
     ausmt-test, which presents the same certificate. Neither line tells the two hosts apart.

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
curl -sS $R -o /dev/null -w '%{http_code}\n' https://$N/gateway/healthz              # 200 (the box's gateway)
curl -sS $R -o /dev/null -w '%{http_code}\n' https://$N/gateway/submit               # 404 (GET is the wrong verb)
curl -sS $R https://$N/data/build.json                                               # the box's current build
echo | openssl s_client -connect 127.0.0.1:443 -servername $N 2>/dev/null | openssl x509 -noout -issuer -enddate
```
The `build.json` must name the same `build_id` and `source_commit` as the box's
`site-data/current/build.json`. None of these probes POSTs, so none submits or requests a key.

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

Only after steps 9 to 11 are green. The four public gateway routes stay live through the move: both
front doors send them to the box's reader listener.

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
      run the public checks of `deploy/frontdoor/RUNBOOK.md` step 9, and `sudo ausmt-doctor-serve` on
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
box → reconcile → publish → ausmt-serve with `publish` = `ok`, and `sudo ausmt-doctor-serve` is clean
apart from the known WARNs. ausmt-test costs 125 SU a year until it is deleted, shut down or not.

14.1  On ausmt-test (`ssh ubuntu@ausmt-vps`, by the rule of step 2.3):
      `cd <the checkout holding deploy/frontdoor> && sudo docker compose -f deploy/frontdoor/compose.yaml down`.
14.2  Compute → Instances → ausmt-test → Actions → **Delete Instance** → confirm.
14.3  Tailscale admin: remove the ausmt-test node, the `tag:ausmt-frontdoor` tag, its two ACL rules
      (`deploy/frontdoor/RUNBOOK.md` 10.3) and the temporary admin rule of step 2.3.

---

## 15. Day 2

- **Health:** `sudo ausmt-doctor-serve` on ausmt-serve. Provisioning installs it outside the data
  volume, so it still runs, and FAILs its volume line, when the volume is missing. The box's
  `reconcile-status.json` `publish` field and the alert timer cover the publish path.
- **Updates (the deploy pass):** `sudo sh /srv/ausmt/code/deploy/nectar/provision-serve.sh` on
  ausmt-serve, BEFORE the box's usual pass, so the public edge never lags what the box publishes (the
  table-before-data rule of the time-series routes). Both halves are written out in
  `deploy/README.md`, "Update to a new image tag". Provisioning fast-forwards the checkout,
  reinstalls the receiver, the gates, the doctor and the Docker drop-in, pulls the portal and caddy
  images, re-runs `make up` and `install-frontdoor.sh` (which reloads the running edge in place).
- **Image tag:** GHCR carries only the moving tags `main` and `latest`, so `TAG` names a tag, not an
  image, and keeping it equal to the box's does not by itself make the two hosts run the same portal.
  Pulling on both in the same deploy pass does: provisioning pulls before it starts anything, and
  `sudo ausmt-doctor-serve` prints the running portal image's RepoDigest. Compare it with the box's,
  `docker image inspect --format '{{index .RepoDigests 0}}' ghcr.io/<OWNER>/ausmt-portal:<TAG>`.
  A serve host whose portal image is older than the box's serves new builds through an old SPA and
  an old wall 2.
- **Host upgrades:** unattended upgrades apply security updates; a kernel update needs a reboot you
  schedule. The volume mounts by label (`nofail`), and Docker starts only after it is mounted and
  after `tailscaled` (the drop-in of step 8), so the containers come back with the tree under them and
  the tailnet resolver in place for the gateway upstream.
- **The volume did not mount.** With the volume absent Docker does not start, so there is no edge at
  all (the public name refuses connections) rather than an empty site behind a valid certificate.
  `sudo ausmt-doctor-serve` FAILs its volume line, and the box's next publish fails and fail-pings. If
  Docker was started by hand meanwhile, it laid empty root-owned stubs for its bind mounts under
  `/srv/ausmt` on the root disk. Recover:
```sh
sudo systemctl stop docker.socket docker.service              # both stacks down
mountpoint /srv/ausmt                                         # expect: is not a mountpoint
sudo find /srv/ausmt -mindepth 1 -maxdepth 3 -ls              # the stubs, if any
mountpoint -q /srv/ausmt || sudo find /srv/ausmt -mindepth 1 -delete
sudo mount /srv/ausmt && mountpoint /srv/ausmt                # if not: lsblk -f, and the volume's attachment
sudo systemctl start docker                                   # both stacks up
sudo ausmt-doctor-serve
```
  The stubs are removed while the volume is unmounted, because they sit on the root disk beneath the
  mount point; once the volume is mounted the same paths are the real tree.
- **Rolling the public site back to an older build:** do it on the box as a curator rollback. The
  pinned reconcile pass publishes the rolled-back build to the replica. A replica-only `make publish
  ARGS="--build <ts>"` is overwritten by the next reconcile pass, which publishes the box's current.
- **Retention:** the replica keeps the `AUSMT_PUBLISH_KEEP` newest complete builds (default 5, 1 to
  999, set on the sender), with current always among them. A build directory without a sidecar is an
  interrupted transfer; the doctor names it and you delete it once no publish is running.
- **Curators:** the tailnet policy grants `group:curators` port 443 on the curation host's tailnet
  name (the box in phase one) and nothing else. That is how curators reach the workbench today:
  `tailscale serve --bg https / http://127.0.0.1:8443` on the curation host publishes the portal
  listener under its MagicDNS name (`deploy/README.md`), and the portal listener proxies `/gateway/*`
  to the gateway. No new port or listener; 8444 is the gateway's loopback debug bind and is not
  granted (C48 D7).

---

## 16. Lifting curate

The curation role moves to **ausmt-curate** (m3.medium, which holds the build, C48 D3; no floating
IP, no security group that admits inbound traffic, `default` included; `tag:ausmt-curate`) and the box
retires. The order and what moves are in
`maintainer/C48-NectarTopology.md` D10; the publish contract does not change, only the sender's host
and `AUSMT_PUBLISH_TARGET` moving with it. The public gateway routes move with the curation role: set
`AUSMT_GATEWAY_UPSTREAM` in ausmt-serve's `deploy/.env` to ausmt-curate's reader listener and re-run
`provision-serve.sh`.
