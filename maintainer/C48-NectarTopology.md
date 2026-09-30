# C48: Nectar topology, a serving replica fed by publish (design record)

Owner rulings (2026-09-30): AusMT moves off the home box onto the owner's Nectar project as TWO
instances with separate roles, **ausmt-serve** (public) and **ausmt-curate** (tailnet only), with the
curation host publishing finished builds to the serving host by rsync. Serve comes first while the
home box keeps the curation role; curation is lifted to Nectar next; the box is retired last. This
record fixes the roles, the arithmetic that sizes them, the publish contract between them, the
cutover and its rollback, and what is still open. It extends C47 (the public bridge), whose two walls
and masked edge log carry over unchanged.

## D1. Current state (facts checked 2026-09-30)

* **The Nectar project** (custom bundle, from the owner's dashboard): 8 vCPU, 16 GB RAM, 3 instances,
  1 router, 2 floating IPs, 5 security groups, 200 GB object store, 2,000 SU budget. **There is no
  volume storage line in the allocation.**
* **The one instance**, `ausmt-test`: t3.xsmall (1 vCPU, 1 GB, 10 GB disk), availability zone
  QRIScloud, floating IP 203.101.226.191 on network `qld` (private 10.255.131.44 on `qld-data`),
  created 21 Jul 2026, image NeCTAR Ubuntu 24.04 LTS (Noble) amd64 v29, security groups `default`,
  `icmp`, `http` (80/tcp and 443/tcp from 0.0.0.0/0), no SSH rule. **It is the production front door
  today**: it runs `deploy/frontdoor` (Caddy, host network) and proxies over the tailnet to the home
  box's reader listener. There is no other VPS.
* **SU charging** (ARDC support pages, [flavours][flav] and [service units][su]): an instance consumes
  SU per hour by flavour whether busy, idle or shut down; only deletion stops it. t3.xsmall 0.014 SU/h
  (125/yr); m3.small 2 vCPU 4 GB 0.057 SU/h (500/yr); m3.medium 4 vCPU 8 GB 0.114 SU/h (1,000/yr);
  m3.large 8 vCPU 16 GB 0.228 SU/h (2,000/yr); m3.xlarge 16 vCPU 32 GB 0.457 SU/h (4,000/yr);
  p3.medium (preemptible) 4 vCPU 8 GB 0.029 SU/h; p3.xxlarge 16 vCPU 32 GB 0.114 SU/h. Flavour root
  disk: t3 10 GB, m3 30 GB. Volume storage is a separate per-availability-zone quota.
* **Measured on the box** (owner, 2026-09-30): `site-data/builds` 33G (five kept builds),
  `site-data/cache` 2.2G (the current 2048 MB cap), `basemap` 2.4G. Measured 2026-09-14: one build
  was about 2.9 GB at 4,961 station h5 files (h5 996M, edi 670M, bundles 543M, xml 424M, products
  105M, pages 93M). The corpus is now past 15,000 stations.

[flav]: https://support.ehelp.edu.au/support/solutions/articles/6000205341-nectar-flavors
[su]: https://support.ehelp.edu.au/support/solutions/articles/6000257054-service-units

## D2. Decision: two roles, one direction of trust

| | **ausmt-serve** | **ausmt-curate** |
|---|---|---|
| Public address | floating IP (the one ausmt-test holds today) | none |
| Security group | 80/tcp and 443/tcp from anywhere, nothing else | nothing inbound from the internet |
| Runs | the front-door Caddy (`deploy/frontdoor`) and the portal container, on one host, reader upstream `http://127.0.0.1:8445` | gateway, clamd, gw-runner, surveys-live, git-creds, the sqlite, reconcile and the build |
| Holds | the built tree on a Cinder volume at `/srv/ausmt` | everything the build and the curator workbench need |
| Never holds | a git write credential, the gateway, the sqlite, the build cache | a public listener |
| Flavour | m3.small first, m3.medium if serving needs it | m3.medium, or larger after a RAM amendment |
| Gets data by | publish from the curation host (D4) | curator publishes to surveys-live |

The serving host is the only machine on the internet and it holds nothing that is not already public
(the served tree) plus the TLS key. A compromise of it yields the public tree and the certificate; it
cannot push to the survey repository or read a submission, and it cannot reach the curation host over
the tailnet (the tailnet policy grants the serving tag no inbound path anywhere,
`deploy/nectar/acl-policy.hujson`). The instances also share the project's private network,
`qld-data`, which the tailnet policy does not govern; that path is closed by the security groups. An
OpenStack `default` group normally admits all ingress from its own members, so neither host carries
`default` or any group with a same-group ingress rule (runbook 3.1). The rules of the project's
`default` group are not in the D1 facts and are to be read in the dashboard. The curation host has no
public address and is reached only over the tailnet.

Serve holds no curation duty, so its first-boot and provisioning files install no curation timer and
never start the gateway profile (`deploy/tests/test_cloud_init_serve.py` pins both).

## D3. Quota and SU arithmetic

All figures below are the D1 facts added up; nothing is estimated.

| Stage | Instances | vCPU | RAM | SU per year |
|---|---|---|---|---|
| Today: ausmt-test | 1 | 1 | 1 GB | 125 |
| Serve first: ausmt-serve m3.small + ausmt-test (quiet period) | 2 | 3 | 5 GB | 625 |
| Serve alone after ausmt-test is deleted | 1 | 2 | 4 GB | 500 |
| Curate lifted: serve m3.small + curate m3.medium | 2 | 6 | 12 GB | 1,500 |
| Same, if ausmt-test still exists | 3 | 7 | 13 GB | 1,625 |
| serve m3.medium + curate m3.medium | 2 | 8 | 16 GB | 2,000 |
| serve m3.small + curate m3.large | 2 | 10 | 20 GB | 2,500 |

Readings:

* **The volume is the first blocker.** The allocation has no volume storage, and the m3 root disk is
  30 GB while the box's five kept builds alone measure 33G. The serving host cannot hold the tree until
  the amendment (D9) grants volume storage in QRIScloud, the availability zone ausmt-test and its
  floating IP live in.
* **Sizing the volume.** At the box's measured 33G for five builds (6.6 GB each on average; the size
  of any one build is not in the facts, so the runbook reads it with `du` before the first publish) plus
  the 2.4G basemap, the serving tree needs about 35 GB (33 + 2.4) before any hard-linking between builds (D4).
  The 100 GB request leaves room for the corpus to keep growing at five kept builds. The build cache
  (2.2G) stays on the curation host.
* **m3.medium for both roles** spends the whole 8 vCPU / 16 GB quota and the whole 2,000 SU budget in
  one year, and it only fits once ausmt-test is deleted.
* **A curation host larger than m3.medium** (m3.large) does not fit the 8 vCPU / 16 GB quota beside
  any serving host: that is the RAM and vCPU amendment. At 2,500 SU a year it spends the 2,000 SU
  budget in at most 9.6 months counted from a full budget; ausmt-test has drawn SU since 21 Jul 2026
  and the serve-first stage draws more before the lift, so the real runway is shorter. That is when
  the SU top-up in D9 applies.
* **Idle is not free.** A shut-down instance still consumes SU; only deletion stops it. ausmt-test
  costs its 125 SU a year until it is deleted after the quiet period (D6).

## D4. The publish contract

The curation host (the box, in the first stage) sends; the serving host receives. Three scripts and
one file format make the contract, and each side verifies what the other did.

**The sidecar.** `site-data/builds/<ts>.sha256`, BESIDE the build directory, never inside it (inside,
it would be served and would list itself): the `sha256sum` line of every regular file in the build,
relative paths, sorted in C order.

**The sender, `deploy/scripts/publish.sh`** (run by `make publish` and by `reconcile.sh`), stops at
the first failed step and names it:

1. *resolve-build*: `--build <ts>`, or the build `current` points at. A `current` that is a directory,
   a dangling link or a link out of `builds/` names no build and is refused; so is a build holding
   anything but regular files and directories (a symlink would serve whatever it points at).
2. *ask-receiver*: `receive-build.sh --current` over ssh. A receiver already serving `<ts>` is sent
   nothing and only asked to receive `<ts>` again (step 6): a no-op when its `published.json` agrees,
   and the repair of a receive cut off between its swap and its record.
3. *sidecar*: written beside the build.
4. *rsync-build*: `rsync -a --no-times --checksum --delete --link-dest=../<receiver's current>` into
   `<remote>/site-data/builds/<ts>/`. rsync hard-links a file only when every preserved attribute
   matches, and a rebuild rewrites every mtime, so with `-a` alone no file would ever be linked;
   comparing content and not carrying mtimes links every byte-identical file to the served copy. The
   mtime quick check is also unsafe here: in the round-trip test two same-size files written within one
   second were linked to the OLD bytes (the receiver refused the build, which is D4's second line of
   defence working, but the transfer was wrong).
5. *rsync-sidecar*: after the build, so a directory without a sidecar is a transfer in flight.
6. *receive*: `receive-build.sh --keep <n> <ts>`.

The local `current` is only ever read, and a failed transfer never reaches the receive step.

**The receiver, `deploy/scripts/receive-build.sh`**, accepts `<ts>` only when it is timestamp-shaped
and names an existing directory, then refuses the build unless the files on disk are exactly the
listed files with exactly the listed hashes (no missing, unlisted, altered or non-regular entry). It
swaps `current` the Makefile's way, a temporary symlink renamed over it (`mv -T`, or the same
`rename(2)` through Python where `mv -T` does not exist), never `ln -sfn`. It writes `published.json`
beside `current` (`ts`, `build_id` and `source_commit` from the build's `build.json`, `received_at`),
then prunes: the `--keep` newest builds that carry a sidecar survive (1 to 999, no leading zero),
the build received and the build `current` points at when the prune runs always survive, and a
directory without a sidecar is never touched. Verify, swap, record and prune run under `flock` on
`site-data/.receive.lock`, so two receives (a reconcile publish and a manual `make publish`) never
overlap. `--current` names a build only while its directory exists, so a dangling `current` makes
the sender send again. A refused build leaves `current`, `published.json` and every other build as
they were. A re-run for the current build is a no-op.

**Which uid receives.** `site-data` on the serving host is written by one uid only, 10001, exactly as
on the box (`deploy/README.md`, ownership split). The two candidates were a publish account in the
owning group, and running the receiver inside the portal container as uid 10001. Neither holds:

* *a group member* could create a build directory, but renaming `current` and pruning builds would
  depend on group write on every directory, and rsync `-a` carries the sender's modes, so that would
  rest on the sending host's umask rather than on anything the replica controls;
* *the container route* makes the publish account a docker user, which is root on the host, the
  opposite of a restricted account, and the portal mounts `site-data` read-only.

So the publish account **is** uid 10001 on the host (`useradd -u 10001`), with no docker access and
no shell: its login shell and its key's forced command are `deploy/nectar/publish-gate.sh`, which
admits `receive-build.sh --current`, `receive-build.sh [--keep N] <ts>` and an rsync server that
receives into `site-data/builds/<ts>/` or `<ts>.sha256`, and refuses everything else (an rsync
`--sender`, any other destination or option, a second command, an interactive login). The gate is the
login shell because the tailnet carries SSH as Tailscale SSH, which runs `<login shell> -c <command>`
and never reads `authorized_keys`. What the gate does not police is the file names an rsync client
streams once a receive is running; the account's own write set is the boundary there, and on this host
that is `site-data`, the tree the account exists to replace. The receiver's verification decides what
is served. No container writes `site-data` on the serving host, so uid 10001 has no other writer to
collide with.

**The sending side** writes the sidecar as the operator account, and `builds/` belongs to uid 10001
there too, so the operator needs a one-time write grant on that one directory (`deploy/README.md`,
Nectar serving replica). The build directories themselves are untouched by it.

**When reconcile publishes.** With `AUSMT_PUBLISH_TARGET` set, every pass that settles what the host
serves (`rebuilt`, `noop`, `paused`, `pinned`) publishes the served build before writing its status,
which gains `publish` (`ok`, `failed`, `skipped`) and `publish_detail`. The `noop` pass costs two ssh
round trips (ask, confirm) and is how a replica that missed a publish catches up; the `pinned` pass is how a curator
rollback reaches the public replica. A failed publish exits 1 and `alert.sh` fail-pings on it; the
local `current` is never touched.

Pins: `deploy/tests/test_publish_sh.py`, `test_receive_build_sh.py`, `test_publish_gate_sh.py`,
`test_publish_roundtrip_sh.py` (a real rsync through the gate into the receiver),
`test_reconcile_sh.py` (the publish step), `test_alert_sh.py`, `test_makefile_publish_target.py`.

## D5. The serving host

`deploy/nectar/cloud-init-serve.yaml` (first boot) and `deploy/nectar/provision-serve.sh`
(idempotent, root) build it: packages, Docker and compose, Tailscale, unattended upgrades, the volume
mounted by label at `/srv/ausmt` with `nofail`, the tree and its ownership from `deploy/README.md`, the
receiver and both gates, the two `.env` files (the reader upstream forced to loopback), the basemap,
`make up`, then `install-frontdoor.sh`. The front-door doctor skips its two tailnet-peer legs on a
loopback upstream; `deploy/nectar/doctor-serve.sh` reports the whole serve role in the doctor-box shape.

The masked front-door log keeps flowing to the analytics fold on the curation host: the log account
`caddylog` exists on the serving host with `deploy/nectar/caddylog-gate.sh` as its login shell
(`rrsync -ro /var/log/caddy`, the forced command of `deploy/frontdoor/RUNBOOK.md` 5.2, applied at the
shell because Tailscale SSH never reads the key), and the box's `AUSMT_FRONTDOOR_LOG_REMOTE` moves to it
at cutover.

## D6. Cutover and rollback

The public name already resolves to 203.101.226.191, so the cutover moves the address, not DNS:

1. Copy the `caddy_data` volume from ausmt-test to ausmt-serve BEFORE the serving front door first
   starts, so the certificate travels and no ACME order is attempted for a name that does not yet
   point at the new host. Then finish provisioning.
2. Seed: the first publish from the box over the tailnet; `doctor-serve.sh` green except the gateway
   WARN (D11, question 3).
3. Check the serving host end to end on itself with `curl --resolve <name>:443:127.0.0.1`: the
   certificate, the reader, `/data`, and the wall refusals.
4. Move the floating IP from ausmt-test to ausmt-serve in the dashboard (disassociate, associate).
5. Repoint the box's log pull at the serving host, after a last pull from ausmt-test whose live file
   is set aside under a name the stats fold still reads (both front doors write the same file name).

**Rollback is moving the floating IP back.** ausmt-test is left running and untouched through a quiet
period, still proxying to the box's reader listener, which keeps serving the box's own current. Its
certificate may be older than the serving host's by then; it is still valid within its own renewal
window and Caddy renews it once the address is back. **ausmt-test is deleted only after the quiet
period**; its tailnet tag and ACL entries go with it. Procedure: `deploy/nectar/RUNBOOK-NECTAR.md`.

## D7. Curator access layering

Two more curators join with no new code in the gateway:

1. **Tailnet invite**, signed in with a passkey or institutional single sign-on at the Tailscale login
   (the first factor, and the only way to the curation host at all).
2. **`group:curators`** in the tailnet policy reaching the curation host's port 8444 only
   (`deploy/nectar/acl-policy.hujson`). What answers there is D11 question 4; until it is decided a
   curator reaches nothing.
3. **A named entry in `AUSMT_CURATOR_KEYS`**, the key held in the shared vault, so every action is
   attributable.
4. **TOTP enrolment** on the gateway (the second factor it already enforces).

No WebAuthn is built into the gateway; the passkey lives at the tailnet login.

## D8. Continuity

Accepted by the owner, not built here:

* The production repositories, the GHCR images and the deploy key live under a personal GitHub account
  and move to the AuScope organisation. `AuScope/ausmt` exists as a mirror, 771 commits behind
  `bvkay/ausmt` as of 2026-09-30. The serve files clone `https://github.com/bvkay/ausmt.git` and pull
  images from the `OWNER` in `deploy/.env`; the move changes those two values.
* A second tailnet admin.
* Secrets in a shared vault (curator keys, the submit key, git-creds, the Tailscale auth keys).
* An encrypted copy of the sqlite backup snapshots in the 200 GB object store.

## D9. The amendment to file

* **Volume storage: 100 GB in QRIScloud.** Blocks the serving host (D3).
* **RAM 16 to 32 GB and vCPU 8 to 16**, justified by the separate curation instance running the corpus
  build (D3: m3.medium for both roles already fills the quota).
* **An SU top-up only if the allocation runs past 12 months.**
* **A second project member.**

The paste-ready text is in `deploy/nectar/RUNBOOK-NECTAR.md`.

## D10. What stays on the box until the curate lift, and the lift

**Stays on the box:** surveys-live and git-creds, the gateway, clamd and gw-runner, the sqlite, the
build and its cache, the reconcile timer (now publishing), backups and the restore drill, the stats
fold and the front-door log pull, the alert and actions timers, and the box's own portal (the curator
workbench over the tailnet, and ausmt-test's upstream through the quiet period).

**The lift, in order:** file the RAM amendment; create ausmt-curate (no floating IP, no security group
that admits inbound traffic, `default` included; `tag:ausmt-curate`) and provision it with the full `deploy/README.md` checklist (gateway profile and
the 10002 tree included); restore the sqlite from the newest backup through the restore-drill path;
stop the box's reconcile, actions and backup timers so there is one writer and one publisher; enable
them on ausmt-curate with `AUSMT_PUBLISH_TARGET` set; watch one publish land; retire the box. The
curation host has no public address, so its outbound traffic (GitHub, GHCR, ClamAV updates, Tailscale)
must leave through the project router. The D1 facts give one router but not its external gateway: check
Network → Routers that it has an external gateway set and `qld-data` attached before the lift.

## D11. Open questions

1. **Build peak RSS at 15,000 stations.** m3.medium has 8 GB in total. `build_report.json` records
   `peak_rss_mib` and `peak_rss_child_max_mib`; read them on the next box build before choosing the
   curation flavour.
2. **Per-file byte determinism.** How much `--link-dest` saves depends on how many files a rebuild
   writes byte-identical. A separate change makes the MTH5 tiers cache-reused, so unchanged station
   files keep their bytes across builds; after two publishes, `find builds/<ts> -type f -links +1 |
   wc -l` on the serving host counts the files the second build shares with the first.
3. **The public submission routes have no upstream on the serving host.** The Add Survey flow is
   public (C47 D3): `POST /gateway/submit`, `POST /gateway/request-key`, `GET /gateway/healthz` and
   `GET /gateway/status/*` are proxied by the reader listener to the gateway container, and the serving
   host runs no gateway, so after the IP move they answer 502 at the public name. `doctor-serve.sh`
   WARNs on it every run. The structural option that keeps the rulings is a second front-door upstream
   for exactly those four routes, over the tailnet to the curation host's reader listener (which
   already proxies exactly those four to its gateway), with one ACL grant `tag:ausmt-serve` to
   curate:8445. That changes wall 1 and its pins and needs a decision **before the floating IP moves**,
   or the public contribution flow is down from cutover to the decision.
4. **What curate:8444 serves.** On the box 8444 is the gateway's loopback debug bind; the workbench UI
   is the portal's full listener (127.0.0.1:8443, `tailscale serve` on 443 today). If curators are to
   reach the workbench UI on tailnet port 8444, the curation host fronts the full listener there
   (`tailscale serve --bg --https=8444 http://127.0.0.1:8443`); if 8444 means the gateway alone they
   get the API without the UI. The same holds in phase one: the policy grants curators `ausmt-box:8444`,
   and on the box 8444 is bound to `127.0.0.1` only (`deploy/compose.yaml`), so an invited curator
   reaches nothing until the owner runs that `tailscale serve` on the box or onboarding waits for the
   lift (runbook 15).
5. **Tailscale SSH and the gates.** The gates rely on Tailscale SSH running the login shell with `-c`.
   The runbook's first publish test from the box proves it on the real host (`receive-build.sh
   --current` answers, `sh` is refused). Two channels never start the login shell: the sftp subsystem
   and a port-forwarding channel. The `restrict` on the OpenSSH key does not apply on the Tailscale
   path, and whether Tailscale SSH serves either channel to a gated account is not verified here. The
   runbook (9.2) requires an `sftp` session and an `ssh -N -L` forward to both fail before the first
   publish. If either succeeds, the two service accounts move to OpenSSH bound to the tailnet address,
   with `Match User publish,caddylog` setting `ForceCommand` to the gate, `AllowTcpForwarding no`,
   `X11Forwarding no`, `PermitTTY no` and no sftp subsystem, and leave the Tailscale `ssh` rules.
6. **GHCR visibility.** If the images are private, the serving host needs a read-only registry
   credential, the one credential it would hold; public images need none.
7. **The box's reconcile prune.** `reconcile.sh` prunes stale builds on entry as the operator, and the
   build directories belong to uid 10001 with no group write, so on the box that prune can only remove
   what the operator owns. Not verified on the box; the Makefile's in-container prune is unaffected.

## Provenance

Owner rulings 2026-09-30 (two roles and their contents, flavours, sequence, tailnet as identity layer,
curator layering, floating-IP cutover and rollback, the amendment, the continuity items). Facts from
the owner's Nectar dashboard and the ARDC support pages, checked 2026-09-30; box measurements by the
owner 2026-09-30 and 2026-09-14. Deliverables: the sender and receiver, the two gates, `make publish`,
the reconcile publish step and status field, the publish alert, `deploy/nectar/` (cloud-init,
provisioning, the serve doctor, the tailnet policy entries, the runbook), the loopback leg of the
front-door doctor, and the pins listed in D4.
