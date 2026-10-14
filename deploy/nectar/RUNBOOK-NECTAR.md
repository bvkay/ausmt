# Runbook: the Nectar serving replica (ausmt-serve)

The numbered procedure to stand up **ausmt-serve**, feed it from the box by publish, point the public
names at it by a DNS change, roll back if needed, and retire **ausmt-test**. Design and rationale:
`maintainer/C48-NectarTopology.md`. The front door itself is the C47 stack; its own runbook is
`deploy/frontdoor/RUNBOOK.md`.

**You run every remote step and type every credential.** Nothing in this repository contacts Nectar,
the box or the tailnet on its own, and no file here holds a secret. Where a step needs a credential
(a Tailscale auth key or login, a registry token, the dashboard) you type it on the host or in the
dashboard at that step.

```
internet ──▶ DNS A record ──▶ ausmt-serve: front door (Caddy, TLS, masked log) ──▶ portal :8445 (loopback)
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
  instead, and move to the volume when it is granted. The root disk can carry the cutover at one kept
  build (C48, "Executed").
- **Nectar gives each instance a fixed public address, and nothing floats.** The project has no
  router and no private network of its own; an instance launched on Classic Provider gets a fixed
  address on the `qld` network, kept for the instance's life and released when it is deleted. The
  cutover is therefore a DNS change: both public names' A records move from ausmt-test's address
  (203.101.226.191) to ausmt-serve's. `ausmt.auscope.org.au` is in AuScope's cPanel zone and is
  changed by AuScope's director on request; `ausmt.au` is at VentraIP and changed by the owner. Book
  the request for step 12 before you start.
- **The public submission routes stay live through the DNS change** (C48 D12). The serving host
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
> 7.5 GB. The serving instance keeps five builds, 5 x 7.5 = 37.5 GB at most, plus a 2.4 GB
> self-hosted basemap.
> The curation instance holds the builds, a build cache capped at 16 GiB that must share their
> filesystem, the survey repository and the submission state: about 28 GB at 15,265 stations and
> 48 GB with the
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
     confirm it reaches the curation host's port 8445 and nothing else; the stock policy's allow-all
     rule, if it is still there, shows up here.
2.2  Settings → Keys → Generate auth key, tagged `tag:ausmt-serve` (you will type it in step 5; do not
     paste it anywhere else).
2.3  A temporary admin path to ausmt-test, for steps 7, 12.1, 13.1 and 14.1. ausmt-test joined the tailnet as
     `ausmt-vps` without Tailscale SSH, and the front-door stanza admits only the box to its port 22,
     so add this rule to `acls` (you remove it in step 14.3):
```
{"action": "accept", "src": ["autogroup:admin"], "dst": ["tag:ausmt-frontdoor:22"]},
```
     ausmt-vps runs OpenSSH, so you log in there as `ubuntu` with your Nectar key pair:
     `ssh ubuntu@ausmt-vps`.

---

## 3. Launch ausmt-serve

3.0  Nothing to configure for the network. Network → Routers is empty and there is no private
     network: the instance reaches apt, GitHub, GHCR and the tailnet through its own fixed public
     address, which it holds from first boot. That is why both security groups of 3.1 go on before
     launch.
3.1  Compute → Instances → Launch Instance:
     - **Details:** name `ausmt-serve`, availability zone **QRIScloud** (where ausmt-test lives).
     - **Source:** image NeCTAR Ubuntu 24.04 LTS (Noble) amd64 (the current version).
     - **Flavour:** `m3.small` (C48 D2; m3.medium only if serving needs it).
     - **Networks:** **Classic Provider**, the only network the wizard offers. The instance shows its
       fixed public address under `qld`; an interface on `qld-data`, QRIScloud's storage network,
       arrives by itself.
     - **Security groups:** `http` (80/tcp and 443/tcp inbound) and a TEMPORARY group allowing 22/tcp
       from **your own address only** (call it `ssh`), removed in 5.4. Not `default`: an OpenStack
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
3.2  Bootstrap access. Note the fixed public address the instance shows under `qld`: it is the
     address step 8 gives the doctor and the address both public names point at from step 12. Log in
     as `ubuntu` at that address with your key pair, from the address the `ssh` group admits. Until
     step 12 no public name points at it.
3.3  Check first boot finished: `cloud-init status --wait` then `tailscale version`, `docker compose
     version`. Near the end of `/var/log/cloud-init-output.log`, just before cloud-init's own
     finished line, a line says the volume is not mounted yet; that is expected.

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
     (30 - 17.4) for Ubuntu, the Docker images and the logs. A proof serve can stretch the step 7
     to 12 window past the certificate's 30-day mark; step 7's slip clause then applies. Add
     `AUSMT_PUBLISH_KEEP=1` to the box's
     `deploy/.env` before step 9 (`make publish` and the reconcile unit both read it). Provisioning
     refuses a data root that is not a mount point, so the tree lives in a directory on the root disk,
     bind-mounted at `/srv/ausmt` in place of the volume line cloud-init wrote. cloud-init separates
     that line's fields with tabs and the fallback of 4.2 with spaces, so the patterns match either
     (`[[:space:]]`); `deploy/tests/test_runbook_nectar_fstab.py` runs this step's two `sed`
     commands on both:
```sh
sudo mkdir -p /var/lib/ausmt-proof /srv/ausmt
sudo sed -i 's|^LABEL=ausmt-data[[:space:]]|#&|' /etc/fstab         # park the volume line
echo '/var/lib/ausmt-proof /srv/ausmt none bind 0 0' | sudo tee -a /etc/fstab
sudo systemctl daemon-reload && sudo mount /srv/ausmt && mountpoint /srv/ausmt
```
     Run steps 5 to 11 on it, and step 12 too if the volume is still pending (C48, "Executed"). Move
     it to the volume once the volume is granted, before step 12 if you can: after step 12 the move
     stops the public site for the length of the copy, so pick a quiet hour. Create and label the
     volume as in 4.1 and 4.2 (stop before its `mount`), then, with Docker stopped so neither stack
     writes during the copy:
```sh
sudo systemctl stop docker.socket docker.service          # both stacks down
sudo mkdir -p /mnt/ausmt-new && sudo mount LABEL=ausmt-data /mnt/ausmt-new
sudo rsync -aH /var/lib/ausmt-proof/ /mnt/ausmt-new/      # -H keeps the links between builds
sudo umount /mnt/ausmt-new /srv/ausmt
sudo sed -i -e '\|^/var/lib/ausmt-proof[[:space:]]|d' -e 's|^#\(LABEL=ausmt-data[[:space:]]\)|\1|' /etc/fstab
sudo systemctl daemon-reload && sudo mount /srv/ausmt && mountpoint /srv/ausmt
sudo systemctl start docker                               # both stacks up
sudo ausmt-doctor-serve
```
     Once the doctor is clean, remove `AUSMT_PUBLISH_KEEP=1` from the box's `deploy/.env` (the
     default keeps 5) and `sudo rm -r /var/lib/ausmt-proof`. The certificate is not on the data tree
     (it is in Docker's `frontdoor_caddy_data` volume on the root disk), so the move does not touch it.

---

## 5. Join the tailnet

5.1  Join with the tagged auth key from step 2.2. The key goes into a root-only file and `tailscale
     up` reads it from there (`--authkey file:<path>`), so it never sits on a command line, in the
     shell history or in the sudo log; the file is destroyed straight after:
```sh
sudo sh -c 'umask 077; cat > /root/ts-authkey'      # paste the key, Enter, then Ctrl-D
sudo tailscale up --ssh --advertise-tags=tag:ausmt-serve --hostname ausmt-serve --authkey file:/root/ts-authkey
sudo shred -u /root/ts-authkey
```
     `tailscale up` never asks for a key. Without `--authkey` it prints a login URL instead; do not
     sign in there (the node would join as your own user). If you did, or the key went unused, revoke
     the key under Settings → Keys.
5.2  `tailscale status` shows the node with `tag:ausmt-serve`.
5.3  From your own tailnet device: `ssh ubuntu@ausmt-serve` (Tailscale SSH, with its sign-in check).
5.4  From the tailnet session of 5.3, remove the temporary `ssh` security group from the instance
     (Compute → Instances → `ausmt-serve` → Actions → Edit Security Groups). The public address stays:
     it is the host's own, and its only route to the internet. From here the internet reaches 80 and
     443 and nothing else, and you reach the host over the tailnet (Tailscale SSH).
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
Copying it first means the new front door starts with a valid certificate and, while that certificate
has more than 30 days left, places no ACME order for a name that still points at ausmt-test. Caddy
renews in the last third of a certificate's life, the last 30 days of a 90-day Let's Encrypt
certificate. The live certificate for ausmt.auscope.org.au runs 2026-08-17 to 2026-11-15, so its
renewal window opens about 2026-10-16; ausmt.au's runs 2026-09-19 to 2026-12-18. Inside the window
the serving host's Caddy tries to renew at start, the challenge reaches ausmt-test and fails, and the
failures count against the ACME account both hosts then share (its key travels in `caddy_data`).

**Steps 7 to 12 run back to back**, so the copied certificate never reaches its window on a host
that does not hold the address. Before copying, check the time left (30 days = 30 × 86,400 =
2,592,000 s):
```sh
for n in ausmt.auscope.org.au ausmt.au; do     # ausmt.au only if AUSMT_LEGACY_REDIRECT_NAME is set
  echo | openssl s_client -connect $n:443 -servername $n 2>/dev/null \
    | openssl x509 -noout -enddate -checkend 2592000
done
```
`Certificate will not expire` for each name: copy now. `Certificate will expire`: the window is open;
wait until ausmt-test has renewed (the end date moves about 90 days out) and copy after that. If
step 12 slips after the copy and the 30-day mark comes first, stop the front door on ausmt-serve
before that date (`sudo docker compose -f /srv/ausmt/code/deploy/frontdoor/compose.yaml down`), wait
for ausmt-test to renew, then repeat this step, `install-frontdoor.sh` as in step 8, and steps 10 to 12.

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
  `AUSMT_DOCTOR_EXPECT_IP` set to ausmt-serve's own fixed address from 3.2, never ausmt-test's
  (listed in `deploy/frontdoor/.env.example`). Leave
  `AUSMT_BOX_READER_UPSTREAM` as provisioning set it (`http://127.0.0.1:8445`).

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

Every step here runs on the box as the Unix user named by `User=` in `ausmt-reconcile.service`
(`systemctl show -p User ausmt-reconcile.service`), in a shell with the two paths `deploy/README.md`
exports:
```sh
export AUSMT_DATA_DIR=/srv/ausmt AUSMT_CODE_DIR=~/ausmt-code
```
`publish.sh` runs ssh with `BatchMode=yes`, which fails rather than asks on an unknown host key, so
the reconcile unit can publish only if that user's `known_hosts` already holds ausmt-serve's key.
The first command of 9.2, run as that user, is where you accept it; run as anyone else, step 11 shows
`publish=failed` at `ask-receiver`.

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
     serving host holds no secret the account can reach, and the `caddylog` account can read
     world-readable files only. So
     this step has no SFTP or port-forwarding probe. The ruling is revisited at the curate lift
     (C48 D11, question 2).
9.3  Publish by hand. First the path: the seed must not ride a relay.
```sh
tailscale ping ausmt-serve     # expect the last line: pong from ausmt-serve (100.x.y.z) via <ip>:<port> in N ms
```
     A reply `via DERP(<region>)` on every attempt means the two hosts reach each other only through a
     Tailscale relay, which caps throughput: run `tailscale netcheck` on both and settle it before
     seeding. Nothing else reports this; the front-door doctor's direct-path leg is skipped on
     ausmt-serve, whose reader upstream is loopback.

     The first run sends the whole build, uncompressed: about 7.5 GB (`du -sh` prints about 7.0G, in
     GiB). 7.5 GB is 60 Gbit, so at the home uplink rate the seed takes at least:

| uplink | 60 Gbit at that rate |
|---|---|
| 10 Mbit/s | 6,000 s, 1 h 40 min |
| 20 Mbit/s | 3,000 s, 50 min |
| 50 Mbit/s | 1,200 s, 20 min |
| 100 Mbit/s | 600 s, 10 min |

```sh
du -sh "$AUSMT_DATA_DIR/site-data/current/"
cd "$AUSMT_CODE_DIR/deploy"
AUSMT_PUBLISH_TARGET=publish@ausmt-serve make publish ARGS=--dry-run
AUSMT_PUBLISH_TARGET=publish@ausmt-serve make publish
```
     **An interrupted publish resumes.** Run the same `make publish` again: the files that arrived
     stay in `builds/<ts>/` on the replica, `--checksum` skips them, and only the file in flight is
     sent again. If a newer box build has become current meanwhile, the re-run sends that one instead,
     and the interrupted directory, which has no sidecar, is left for you to delete (step 15,
     Retention).
9.4  On ausmt-serve: `sudo ausmt-doctor-serve`. Expect PASS everywhere but the DNS line, the
     `gateway` line included:
     it asks this host's front door for `/gateway/healthz`, which the box answers. A `gateway` WARN
     means this host cannot reach the box's reader port: check the `tag:ausmt-serve` rule of step 2.1
     and `AUSMT_GATEWAY_UPSTREAM`. The `sender` INFO line names the box's tailnet address (step 15).
     The DNS line FAILs until step 12, because the public name still resolves to ausmt-test, not to
     the address step 8 set; it is the line that turns green when the names move. The TLS line
     passes already: the public name reaches ausmt-test, which presents the same certificate.

---

## 10. Verify ausmt-serve before the DNS change

10.1 On ausmt-serve, against its own front door with the public name resolved to loopback, so the
     certificate, both walls and the served tree are checked before any visitor sees them:

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

10.2 From your own machine off the tailnet, by name against ausmt-serve's public address, without
     touching DNS. This proves the internet path, the `http` group and the copied certificate as a
     visitor will meet them after step 12:
```sh
A=<ausmt-serve's fixed public address, from 3.2>
curl -sSI --resolve ausmt.auscope.org.au:443:$A https://ausmt.auscope.org.au/ | head -1            # HTTP/2 200
curl -sS --resolve ausmt.auscope.org.au:443:$A https://ausmt.auscope.org.au/data/build.json        # the box's current build
curl -sSI --resolve ausmt.au:443:$A https://ausmt.au/ | grep -iE '^(HTTP|location)'                 # 301 to the main name
```
     The last line applies only when `AUSMT_LEGACY_REDIRECT_NAME` is set. A certificate error here
     means step 7's copy did not land; a timeout means the `http` group is missing from the instance.

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

## 12. Change DNS

Only after steps 9 to 11 are green. The cutover points both public names' A records at ausmt-serve's
fixed address. It has no gap: until resolvers pick up the change, for up to the record's TTL of
300 seconds, some visitors still reach ausmt-test and the rest ausmt-serve, and both front doors serve
the box's current build under the same certificate and send the four public gateway routes to the
box's reader listener. ausmt-test stays running and untouched; it is the rollback (step 13).

Book the change in advance: `ausmt.auscope.org.au` is in AuScope's cPanel zone for auscope.org.au
(nameservers ns1 and ns2.server-cpanel.com) and AuScope's director changes it on request. Send the
request with ausmt-serve's address, the time window and the rollback (the old address,
203.101.226.191) once steps 9 to 11 are green, and run 12.1 shortly before the window.

12.1  Before the change, the log account. The box's pull reads ausmt-test's log as `caddylog`, and
      Caddy creates its log files mode 0600 unless told otherwise, which masks a `caddylog` ACL out.
      On ausmt-test (`ssh ubuntu@ausmt-vps`):
```sh
sudo getfacl -p /var/log/caddy/access-frontdoor.json
```
      Expect a `user:caddylog:` entry (written `r-x` by the default ACL) with no `#effective:---`
      beside it. If the entry is missing or
      its effective right is `---`, the box's pull has been reading nothing from ausmt-test: note the
      gap (the box's `ausmt-frontdoor-logs` journal shows when it began), then grant the read on the
      files as they stand, which also recomputes the mask, so the remaining pulls carry the log:
```sh
sudo setfacl -m u:caddylog:r /var/log/caddy/access-frontdoor*.json
```
      ausmt-serve's front door writes its log files mode 0640, so the default ACL provisioning sets
      is effective there, and its doctor checks that `caddylog` can read the live log. Then, on the
      box, pull from ausmt-test now:
```sh
sudo systemctl start ausmt-frontdoor-logs.service
```
12.2  The main name. In AuScope's cPanel DNS zone, the A record `ausmt` changes from 203.101.226.191
      to ausmt-serve's address, TTL left at 300. The director makes the change; confirm the time it
      was saved.
12.3  The legacy name, only when `AUSMT_LEGACY_REDIRECT_NAME` is set. `ausmt.au` is an A record at
      VentraIP (nameservers ns1 to ns3.nameserver.net.au); change it to ausmt-serve's address in the
      same window, TTL 300. The front door answers the redirect name on its own certificate, which
      travelled in step 7, so the two names move together.
12.4  From any machine off the tailnet, wait until both names resolve to the new address:
```sh
dig +short ausmt.auscope.org.au ; dig +short ausmt.au      # ausmt-serve's address, twice
```
      then send a request only this check makes:
```sh
M=cutover-$(date +%s); echo $M
curl -sSI "https://ausmt.auscope.org.au/?check=$M" | head -1        # HTTP/2 200
```
      then on ausmt-serve prove it arrived there:
```sh
sudo grep -c "check=<the M printed above>" /var/log/caddy/access-frontdoor.json   # 1 or more
```
      The `build.json` check passes on either host (both serve the box's current build under the same
      certificate), and a resolver you asked is not the one every visitor uses, so only this log line
      proves that traffic arrives at ausmt-serve. Then
      run the public checks of `deploy/frontdoor/RUNBOOK.md` step 9, and `sudo ausmt-doctor-serve` on
      ausmt-serve.
12.5  Repoint the masked-log pull on the box, once at least 300 seconds (the TTL) have passed since
      12.2 and 12.3, so stragglers have stopped reaching ausmt-test. Both front doors write
      `access-frontdoor.json`, and the box keeps one copy of each name, so the first pull from
      ausmt-serve would overwrite what ausmt-test logged since the last pull, before the daily stats
      fold has read it. On the box:
```sh
sudo systemctl start ausmt-frontdoor-logs.service      # a last pull from ausmt-test, which now gets no traffic
cd "$AUSMT_DATA_DIR/logs/caddy"
mv access-frontdoor.json access-frontdoor-ausmt-test.json   # still read by the fold, never overwritten
```
      That last pull collects what ausmt-test logged between 12.1 and the change. ausmt-test keeps its
      own address and its tailnet path; if the pull fails, only those minutes are missing, because 12.1
      already pulled the rest.
      Then set `AUSMT_FRONTDOOR_LOG_REMOTE=caddylog@ausmt-serve:` in `deploy/.env`, pull once, and
      check that `access-frontdoor.json` is back (it can only have come from ausmt-serve):
```sh
sudo systemctl start ausmt-frontdoor-logs.service && ls -l access-frontdoor.json
```
      Delete `access-frontdoor-ausmt-test.json` once the fold has passed the day of the change.

---

## 13. Rollback

Point the names back; nothing else is needed while ausmt-test is left running.

13.1  Ask for the A record `ausmt` in AuScope's cPanel zone to go back to 203.101.226.191, and put
      `ausmt.au` at VentraIP back to the same address. With the TTL at 300 seconds, visitors move back
      within about five minutes, and both hosts answer meanwhile. ausmt-test's front door still proxies
      to the box's reader listener, which still serves the box's own current. Then, on ausmt-test
      (`ssh ubuntu@ausmt-vps`, by the rule of step 2.3):
```sh
sudo docker compose -f ~/ausmt/deploy/frontdoor/compose.yaml restart frontdoor   # ~/ausmt is the front-door checkout there
```
      While the names pointed at ausmt-serve, ausmt-test could not renew (the challenge reached
      ausmt-serve), and Caddy backs off between failed attempts; the restart makes it renew at once,
      now that the challenge reaches it, if its certificate is inside the window.
13.2  Keep what ausmt-serve logged, as in 12.5 the other way round: pull once more, move
      `access-frontdoor.json` aside as `access-frontdoor-ausmt-serve.json`, then put the box's
      `AUSMT_FRONTDOOR_LOG_REMOTE` back to its ausmt-test value.
13.3  Optional: comment out `AUSMT_PUBLISH_TARGET` on the box to stop feeding the replica.

---

## 14. The quiet period, then delete ausmt-test

Leave ausmt-test running and untouched until you are satisfied; at the least, one new build has gone
box → reconcile → publish → ausmt-serve with `publish` = `ok`, and `sudo ausmt-doctor-serve` is clean
apart from the known WARNs. ausmt-test costs 125 SU a year until it is deleted, shut down or not.

**End the quiet period before ausmt-test's certificate expires**, 2026-11-15 for the certificate it
holds today. ausmt-test cannot renew while the names point at ausmt-serve, so a rollback after that
date serves an expired certificate until 13.1's renewal succeeds. From about 2026-10-16 its Caddy
tries to renew and fails, and those failures count against the shared ACME account; serving is
unaffected, and deleting ausmt-test ends them.

**Rollback ends at 14.2.** Deleting ausmt-test releases its fixed address, 203.101.226.191, back to
the cloud, where another project can be given it. So both names must already point at ausmt-serve,
and once ausmt-test is gone there is no host to point them back to. The front door's `caddy_data` lives in Docker's volume on ausmt-serve's root disk, not on the data
volume, so a lost ausmt-serve after that point means a new instance by this runbook from step 3 and
a fresh certificate.

14.0  From a machine off the tailnet: `dig +short ausmt.auscope.org.au` and `dig +short ausmt.au`
      both print ausmt-serve's address, never 203.101.226.191. A name still pointing at the old
      address would follow it to whoever is given it next.
14.1  On ausmt-test (`ssh ubuntu@ausmt-vps`, by the rule of step 2.3):
      `cd ~/ausmt && sudo docker compose -f deploy/frontdoor/compose.yaml down` (`~/ausmt` is the
      front-door checkout on ausmt-test).
14.2  Compute → Instances → ausmt-test → Actions → **Delete Instance** → confirm. Its address goes
      with it.
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
  `deploy/README.md`, "Update to a new image tag", which also names the one release shape where the
  box pass runs first. Provisioning fast-forwards the checkout,
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
mountpoint -q /srv/ausmt || sudo rm -r /srv/ausmt/*           # only while unmounted
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
  999, set on the sender), with current always among them. It prunes on every receive, the
  confirmation a `noop` pass sends for the build it already serves included, so a keep lowered on
  the sender takes effect at the next reconcile tick. A build directory without a sidecar is an
  interrupted transfer; the doctor names it, no prune removes it, and you delete it once no publish
  is running.
- **A full data volume:** a new build's publish fails at `rsync-build`, before any receive or prune,
  and every tick retries into the same full disk and fail-pings; the public site keeps serving its
  current build. On ausmt-serve, make room by hand, then wait one tick:
```sh
cd /srv/ausmt/site-data
readlink current                                       # the build that must stay
ls -1d builds/*/ && ls -1 builds/*.sha256              # the builds, and which have a sidecar
sudo rm -r builds/<oldest ts> builds/<oldest ts>.sha256   # oldest non-current first, each with its sidecar
sudo rm -r builds/<ts>                                 # every directory without a sidecar
```
  If the volume is too small for the keep depth, lower `AUSMT_PUBLISH_KEEP` on the box as well.
- **The sender:** `published.json` records `sender`, the address the receive arrived from (the first
  word of `SSH_CLIENT`, else `SSH_CONNECTION`, else `local`). Set `AUSMT_PUBLISH_SENDER` in
  ausmt-serve's `deploy/.env` to the curation host's tailnet address (`tailscale ip -4` on the box in
  phase one) and the doctor WARNs whenever `published.json` names another sender. Two hosts
  publishing to one replica would otherwise switch the public build every tick while every pass
  reports `publish=ok`. It is optional; unset, nothing is compared. At the lift it changes to
  ausmt-curate's address (section 16).
- **Curators:** the tailnet policy grants `group:curators` port 443 on the curation host's tailnet
  name (the box in phase one) and nothing else. That is how curators reach the workbench today:
  `tailscale serve --bg https / http://127.0.0.1:8443` on the curation host publishes the portal
  listener under its MagicDNS name (`deploy/README.md`), and the portal listener proxies `/gateway/*`
  to the gateway. No new port or listener; 8444 is the gateway's loopback debug bind and is not
  granted (C48 D7).

---

## 16. Lifting curate

The curation role moves to **ausmt-curate** and the box retires. The design is
`maintainer/C48-NectarTopology.md` D10; the publish contract does not change, only the sender's host
and `AUSMT_PUBLISH_TARGET` moving with it. Set both container ceilings in 16.3 (C48 D3), and
revisit the access ruling of C48 D11 question 2, which names the lift as its review point. Two rules
govern the order: there is one sender at every moment, and no submission is accepted on a host whose
state is about to be copied.

16.1  **Launch** ausmt-curate as in step 3: m3.medium (it holds the build, C48 D3), availability zone
      QRIScloud, network Classic Provider, so it too has a fixed public address, which carries its
      outbound traffic (GitHub, GHCR, ClamAV updates, Tailscale). Security groups: a new group with no
      ingress rule (a new group carries only the two egress rules; call it `egress`) and the temporary
      `ssh` group of 3.1; never `http` or `default`. Bootstrap it as ausmt-serve was (3.2 to 5.4: the
      temporary group removed after the join), joining with an auth key tagged `tag:ausmt-curate`
      (as in 2.2) and `--advertise-tags=tag:ausmt-curate --hostname ausmt-curate`. From then nothing
      on the internet reaches it.
16.2  **The volume.** Volumes → Create Volume: `ausmt-curate-data`, 100 GB (the curation half of the
      grant), QRIScloud, attached to ausmt-curate. Label it and mount it at `/srv/ausmt` as in 4.2,
      with the same fstab line. Everything under `/srv/ausmt` lives on it, `site-data/builds` and
      `site-data/cache` included: builds hardlink into the cache, and across filesystems every cache
      hit becomes a copy. It holds about 28 GB of site-data at 15,265 stations (31 GB with a build in
      progress),
      about 48 GB with the cache at its 16 GiB cap, before Ubuntu and the images.
16.3  **Provision** by the full `deploy/README.md` checklist (the gateway profile, the 10002 tree,
      both `tailscale serve` publications: the reader port 8445 for ausmt-serve's gateway routes and
      443 for curators), with `AUSMT_BUILD_MEM_LIMIT=4g` and `AUSMT_GW_MEM_LIMIT=2g` in its
      `deploy/.env` (C48 D3) and its secrets
      typed from your password manager. Install the timers but leave them disabled, and leave the
      gateway profile down, until 16.6.
16.4  **Freeze submissions and take the final backup**, on the box:
```sh
cd "$AUSMT_CODE_DIR/deploy"
docker compose -f compose.yaml --profile gateway stop gateway    # the four public routes now answer an error
docker compose -f compose.yaml --profile gateway logs --tail 20 gw-runner   # repeat until it is idle
docker compose -f compose.yaml --profile gateway stop
sudo systemctl disable --now ausmt-reconcile.timer ausmt-actions.timer ausmt-backup.timer
sed -i '/^AUSMT_PUBLISH_TARGET=/d' .env                          # this host can never publish again
sudo systemctl start ausmt-backup.service                        # the final snapshot, after the freeze
```
      With the gateway stopped, the Add Survey page's healthz probe fails and it hides its Submit
      button. `disable --now`, not `stop`: a stopped timer starts again at the box's next boot, and
      two senders would switch the public build every tick while each pass reports `publish=ok`.
      From here until 16.7 the box's alert timer reports the stopped gateway and the idle reconcile;
      that is expected.
16.5  **Move the state**: the snapshot's sqlite (the only home of submitter PII), the gateway's
      `incoming`, `jobs` and `quarantine`, and the usage-statistics history (`state/stats.json` and
      `state/daily_archive.jsonl`, which the daily fold extends and nothing regenerates), box →
      ausmt-curate directly over the tailnet, which
      encrypts it in transit. Never route it through ausmt-serve or any other public host; if it has to
      rest anywhere between the two, encrypt it first (`gpg --symmetric`) and delete every copy after.
      The policy's administrator rule admits the box's owner to ausmt-curate for the `scp`, with
      Tailscale SSH's sign-in check; if the box's node is not owned by an administrator, relay the
      archive through your own tailnet device, encrypted first.
```sh
# on the box
umask 077
sudo tar -C "$AUSMT_DATA_DIR" -czf /tmp/ausmt-lift.tgz \
     backups/latest/gateway.sqlite gateway/incoming gateway/jobs gateway/quarantine \
     gateway/state/stats.json gateway/state/daily_archive.jsonl
sudo chown "$USER": /tmp/ausmt-lift.tgz
scp /tmp/ausmt-lift.tgz ubuntu@ausmt-curate:/tmp/ && rm /tmp/ausmt-lift.tgz
# on ausmt-curate, the gateway profile still down (the restore of deploy/README.md, "Real RESTORE procedure");
# AUSMT_CODE_DIR is ausmt-curate's checkout, exported as deploy/README.md has it
sudo tar -C /tmp -xzf /tmp/ausmt-lift.tgz && sudo rm /tmp/ausmt-lift.tgz
sudo sh "${AUSMT_CODE_DIR:?export AUSMT_CODE_DIR first}/deploy/scripts/restore-drill.sh" /tmp/backups/latest   # the copy is restorable
sudo rm -f /srv/ausmt/gateway/state/gateway.sqlite-wal /srv/ausmt/gateway/state/gateway.sqlite-shm
sudo cp /tmp/backups/latest/gateway.sqlite /srv/ausmt/gateway/state/gateway.sqlite
sudo cp -a /tmp/gateway/incoming /tmp/gateway/jobs /tmp/gateway/quarantine /srv/ausmt/gateway/
sudo cp -a /tmp/gateway/state/stats.json /tmp/gateway/state/daily_archive.jsonl /srv/ausmt/gateway/state/
sudo chown -R 10002:10002 /srv/ausmt/gateway/state /srv/ausmt/gateway/incoming \
     /srv/ausmt/gateway/jobs /srv/ausmt/gateway/quarantine
sudo rm -r /tmp/backups /tmp/gateway
```
16.6  **Publish from ausmt-curate, then reopen.** On ausmt-curate, as the `User=` of its reconcile
      unit, make the one-time sidecar grant of 9.1, accept ausmt-serve's host key once
      (`ssh publish@ausmt-serve receive-build.sh --current`, as in 9.2), add
      `AUSMT_PUBLISH_TARGET=publish@ausmt-serve` to `deploy/.env`, and enable the timers
      (`sudo systemctl enable --now ausmt-reconcile.timer ausmt-actions.timer ausmt-backup.timer`). The
      first pass builds cold, with an empty cache, and then publishes; watch `publish` read `ok` in its
      `reconcile-status.json` and, on ausmt-serve, `published.json` name ausmt-curate's tailnet address
      as `sender`. Then on ausmt-serve set `AUSMT_PUBLISH_SENDER` to that address and
      `AUSMT_GATEWAY_UPSTREAM` to ausmt-curate's reader listener in `deploy/.env`, and re-run
      `sudo sh /srv/ausmt/code/deploy/nectar/provision-serve.sh`. Bring ausmt-curate's gateway profile
      up (`make doctor PROFILE=gateway` clean) and, from off the tailnet,
      `curl -sS -o /dev/null -w '%{http_code}\n' https://ausmt.auscope.org.au/gateway/healthz` answers
      200: submissions are open again, on ausmt-curate. Point its `AUSMT_FRONTDOOR_LOG_REMOTE` at
      `caddylog@ausmt-serve:` and enable its stats, log-pull, alert and drill timers.
16.7  **Retire the box.** In the tailnet policy, drop the box's phase-one rules: the `<BOX_NODE_USER>`
      ssh rule for `publish` and `caddylog`, and `ausmt-box` from the curation-to-serve, serve-to-reader
      and curator rules, and the box's entries in the `tests` and `sshTests` stanzas, replaced by
      ausmt-curate's (`deploy/nectar/acl-policy.hujson` marks each; the console refuses a save whose
      tests no longer hold). Run 5.5 again from ausmt-serve
      with ausmt-curate's MagicDNS name for `B`. On the box, disable what is left
      (`sudo systemctl disable --now ausmt-alert.timer ausmt-stats.timer ausmt-drill.timer
      ausmt-frontdoor-logs.timer`) and take its stacks down. Curators now reach the workbench at
      ausmt-curate's MagicDNS name.
