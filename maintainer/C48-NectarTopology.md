# C48: Nectar topology, a serving replica fed by publish (design record)

Owner rulings (2026-09-30): AusMT moves off the home box onto the owner's Nectar project as TWO
instances with separate roles, **ausmt-serve** (public) and **ausmt-curate** (tailnet only), with the
curation host publishing finished builds to the serving host by rsync. Serve comes first while the
home box keeps the curation role; curation is lifted to Nectar next; the box is retired last. This
record fixes the roles, the arithmetic that sizes them, the publish contract between them, the
cutover and its rollback, and what is still open. It extends C47 (the public bridge), whose two walls
and masked edge log carry over unchanged.

## D1. Current state (facts checked 2026-09-30; sizes, build memory and certificates 2026-10-02)

* **The Nectar project** (custom bundle, from the owner's dashboard): 8 vCPU, 16 GB RAM, 3 instances,
  1 router, 2 floating IPs, 5 security groups, 200 GB object store, 2,000 SU budget. **There is no
  volume storage line in the allocation.** The router and floating-IP lines are quota, not things
  that exist: on 2026-10-13 the dashboard showed no router and no private network, and the public
  address below is a fixed one ("Executed").
* **The one instance**, `ausmt-test`: t3.xsmall (1 vCPU, 1 GB, 10 GB disk), availability zone
  QRIScloud, fixed public address 203.101.226.191 on network `qld` (10.255.131.44 on `qld-data`),
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
  `site-data/cache` 2.2G (the 2048 MB cap main ships), `basemap` 2.4G.
* **One built tree, measured** (2026-10-02, 15,265 stations, an acceptance build of the live corpus
  summed file by file): **7.5 GB (7.0 GiB)**, of which MTH5 3.87 GB (station and survey files), xml
  1.47, edi 1.18, bundles 0.51, pages and products 0.47. About 3.6 GB of it is not MTH5 and is
  rewritten by every build. The 2026-09-14 figure, about 2.9 GB at 4,961 station h5 files (a count of files, not
  of stations), scaled linearly gives 2.9 × 15,265 / 4,961 = 8.9 GB, 19 per cent above the
  measurement; it is superseded.
* **The MTH5 build cache** (C18 A6): one cache generation measured 5.5 GB; the cap is ruled 16 GiB.
  Builds hardlink into the cache, so `site-data/cache` and `site-data/builds` must share one
  filesystem; across filesystems a hit falls back to a copy and every build carries its own MTH5.
* **Build memory on the box** (its own Linux `build_report.json`, the live build of 2026-09-28):
  parent peak 1,035 MiB, largest worker 438 MiB, 6 workers.

[flav]: https://support.ehelp.edu.au/support/solutions/articles/6000205341-nectar-flavors
[su]: https://support.ehelp.edu.au/support/solutions/articles/6000257054-service-units

## D2. Decision: two roles, one direction of trust

| | **ausmt-serve** | **ausmt-curate** |
|---|---|---|
| Public address | its own fixed address on `qld`; both public names point at it by DNS (D6) | its own fixed address, outbound only |
| Security group | 80/tcp and 443/tcp from anywhere, nothing else | no ingress rule: nothing inbound from the internet |
| Runs | the front-door Caddy (`deploy/frontdoor`) and the portal container, on one host, reader upstream `http://127.0.0.1:8445`, gateway upstream the curation host's reader listener (D12) | gateway, clamd, gw-runner, surveys-live, git-creds, the sqlite, reconcile and the build |
| Holds | the built tree on a Cinder volume at `/srv/ausmt` | everything the build and the curator workbench need, on its own Cinder volume at `/srv/ausmt` |
| Never holds | a git write credential, the gateway, the sqlite, the build cache | a public listener |
| Flavour | m3.small first, m3.medium if serving needs it | m3.medium with the build capped at 4g (D3), or larger after a RAM amendment |
| Gets data by | publish from the curation host (D4) | curator publishes to surveys-live |

The serving host is the only machine the internet can reach and it holds nothing that is not already public
(the served tree) plus the TLS key. A compromise of it yields the public tree and the certificate; it
cannot push to the survey repository or read a submission, and over the tailnet it reaches only the
curation host's reader listener on port 8445, whose wall 2 admits the same public subset the internet
reaches through the front door (D12; `deploy/nectar/acl-policy.hujson`, whose `tests` and `sshTests`
stanzas pin that grant and its refusals at every policy save; runbook 5.5 proves it from the serving
host after the join, because the entries are merged into a live policy the repository cannot see).
The instances also share the project's private network, `qld-data`, which the tailnet policy does
not govern; that path is closed by the security groups. An OpenStack `default` group normally admits
all ingress from its own members, so neither host carries
`default` or any group with a same-group ingress rule (runbook 3.1). The rules of the project's
`default` group are not in the D1 facts and are to be read in the dashboard. The curation host's
fixed address carries its outbound traffic only; no security group on it admits inbound traffic, so
it is reached only over the tailnet.

Serve holds no curation duty, so its first-boot and provisioning files install no curation timer and
never start the gateway profile (`deploy/tests/test_cloud_init_serve.py` pins both).

## D3. Quota and SU arithmetic

All figures below are the D1 facts added up, and the build memory read from build reports; nothing
is estimated.

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

* **The volume is the first blocker, for both hosts.** The allocation has no volume storage, and the
  m3 root disk is 30 GB. Neither host's data fits it at five kept builds, so the amendment (D9) asks
  for volume storage in QRIScloud, the availability zone ausmt-test lives in: one 100 GB volume per
  host. By owner ruling the serving host cut over on its root disk at one kept build ("Executed").
* **Sizing the serving volume.** One build is 7.5 GB (D1). Five kept builds take between 21.9 GB
  (7.5 + 4 × 3.6, when each later build links its h5 files to the one before and stores its 3.6 GB of
  non-MTH5 afresh) and 37.5 GB (5 × 7.5, when nothing links), plus the 2.4 GB basemap: at most
  39.9 GB. The 100 GB volume leaves room for the corpus to keep growing at five kept builds. The first
  publish sends the whole 7.5 GB (runbook 9.3).
* **Sizing the curation volume.** The curation host holds the kept builds plus one in progress, the
  MTH5 build cache, surveys-live, the basemap, the gateway state and the ClamAV database. Its
  site-data floor at 15,265 stations is about 28 GB (31 GB with a build in progress) before Ubuntu and the images,
  and about 48 GB with the cache at its 16 GiB cap (D1). The cache and the builds share one
  filesystem, the volume mounted at `/srv/ausmt`, because builds hardlink into the cache. The 100 GB
  curation volume holds that with room to grow; the 30 GB root disk does not.
* **m3.medium for both roles** spends the whole 8 vCPU / 16 GB quota and the whole 2,000 SU budget in
  one year, and it only fits once ausmt-test is deleted.
* **Build memory (measured).** The engine reads the footprint as the parent plus the worker count
  times the largest worker. The box's own Linux report (D1) gives 1,035 + 6 × 438 = 3,663 MiB at 6
  workers. A cold and a warm build of the 15,265-station corpus on a macOS host with 4 workers
  (engine `b362918`, surveys `7a1d756c`) gave 865.8 + 4 × 403.2 = 2,478.6 MiB and
  901.0 + 4 × 224.5 = 1,799.0 MiB. **An m3.medium (8 GB) holds the build.** These figures cover the
  build alone: the curation host's other containers (the gateway, clamd, gw-runner) are not in them.
* **Container ceilings on the curation host.** `deploy/compose.yaml` caps the build at
  `AUSMT_BUILD_MEM_LIMIT` (default 8g) and gw-runner at `AUSMT_GW_MEM_LIMIT` (default 4g), both
  sized for the box, and requires the two ceilings to sum below the host. On ausmt-curate
  `deploy/.env` sets `AUSMT_BUILD_MEM_LIMIT=4g`, which holds the measured 3,663 MiB with 433 MiB to
  spare, and `AUSMT_GW_MEM_LIMIT=2g`: 6 GiB of ceilings on an 8 GB host, leaving 2 GiB for the OS,
  the portal, the gateway and clamd. That is tight; a cold build and a large submission at the same
  moment can still press on it, and an m3.large removes the squeeze, which is the optional RAM
  line's other use.
* **A curation host larger than m3.medium** (m3.large), for more build workers than the build needs,
  does not fit the 8 vCPU / 16 GB quota beside any serving host: that is the optional RAM and vCPU
  line of the amendment. Serve m3.small plus curate m3.large is (0.057 + 0.228) × 8,760 = 2,497 SU a
  year, about 2,500, which spends the 2,000 SU budget in at most 9.6 months counted from a full
  budget; ausmt-test has drawn SU since 21 Jul 2026 and the serve-first stage draws more before the
  lift, so the real runway is shorter. That line needs an SU top-up of at least 500 a year beside it
  (D9).
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
beside `current` (`ts`, `build_id` and `source_commit` from the build's `build.json`, `received_at`,
and `sender`, the address the receive arrived from: the first word of `SSH_CLIENT`, else
`SSH_CONNECTION`, else `local`), then prunes: the `--keep` newest builds that carry a sidecar
survive (1 to 999, no leading zero), the build received and the build `current` points at when the
prune runs always survive, and a directory without a sidecar is never touched. Verify, swap, record
and prune run under `flock` on `site-data/.receive.lock`, so two receives (a reconcile publish and a
manual `make publish`) never overlap. `--current` names a build only while its directory exists, so a dangling `current` makes
the sender send again. A refused build leaves `current`, `published.json` and every other build as
they were. A re-run for the current build changes nothing but the prune, which runs on that path
too, so a keep lowered on the sender takes effect at the next tick while the replica already serves
the sender's current. A full volume is the one case no tick repairs: a new build's transfer fails
before any receive, so space is made by hand (runbook 15).

**One sender.** The receiver accepts any timestamp, older or newer, because a curator rollback
depends on it, so two hosts publishing to one replica would switch the public build every tick while
each reports `publish=ok`. `published.json` therefore names the sender, and with
`AUSMT_PUBLISH_SENDER` set in the serving host's `deploy/.env` the serve doctor WARNs when it names
any other. At the lift the old sender is disabled, not stopped, and its policy rule is dropped (D10).

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
and never reads `authorized_keys`. Those three are what the account can run over a command session.
Tailscale SSH also serves SFTP, in-process: it probes the login shell with `su -l <user> -c true`,
the gate refuses `true`, and tailscaled then serves SFTP itself as the account's uid without running
the gate. Over SFTP the account reads and writes what uid 10001 can, which on this host is
`site-data` and world-readable files. Owner ruling 2026-10-02 accepts that for phase one, while the
box is the sender: the writable tree is the one the account exists to replace and the serving host
holds no secret the account can reach, the TLS key sitting in a root-only Docker volume (D11,
question 2). What the gate does not police is the file names an rsync client
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
a pull of the portal image and the front door's caddy image, `make up`, then `install-frontdoor.sh`.
The pull is what moves the public SPA and wall 2, which are baked into the portal image: `make up`
alone pulls only a missing image, and GHCR carries only the moving tags `main` and `latest`. So the
deploy pass re-runs provisioning on the serving host before the box's pass (`deploy/README.md`,
"Update to a new image tag"), and the serve doctor prints the running portal image's RepoDigest.
Provisioning also carries `AUSMT_GATEWAY_UPSTREAM` from `deploy/.env` into the front door's `.env`
(D12). The GHCR images are public (an anonymous token got
HTTP 200 on the `ghcr.io/bvkay/ausmt-portal` tags list, checked 2026-09-30), so the serving host holds
no registry credential. The serving host has its own fixed public address from first boot (a
Classic Provider launch; the project has no router and no private network), which is its route to
the internet. Until its tailnet join it is reached there over SSH, through a temporary security
group admitting 22/tcp from the operator's address only, removed once the join is proved; from then
the internet reaches 80 and 443 only. The front-door doctor skips its two
tailnet-peer legs on a loopback upstream; `deploy/nectar/doctor-serve.sh` reports the whole serve
role in the doctor-box shape. Provisioning installs that doctor at `/usr/local/bin/ausmt-doctor-serve`,
outside the data volume, and refreshes it on every run; operators run `sudo ausmt-doctor-serve`
(both `.env` files are root-only). It also installs a `docker.service` drop-in,
`/etc/systemd/system/docker.service.d/ausmt-serve.conf`, with `RequiresMountsFor=/srv/ausmt` and
`After=tailscaled.service`: Docker never starts the stacks over empty bind sources on the root disk
or before the tailnet resolver the gateway upstream needs. With the volume absent there is therefore
no edge at all rather than an empty site behind a valid certificate.

The masked front-door log keeps flowing to the analytics fold on the curation host: the log account
`caddylog` exists on the serving host with `deploy/nectar/caddylog-gate.sh` as its login shell
(`rrsync -ro /var/log/caddy`, the forced command of `deploy/frontdoor/RUNBOOK.md` 5.2, applied at the
shell because Tailscale SSH never reads the key), and the box's `AUSMT_FRONTDOOR_LOG_REMOTE` moves to it
at cutover. Over SFTP, outside its gate as for the publish account (D4), it can read world-readable
files only. Its read of the log rests on a default ACL on `/var/log/caddy`, which is effective only
because the front-door Caddyfile writes its log files mode 0640: Caddy's default 0600 sets the ACL
mask to nothing. The serve doctor checks that `caddylog` can read the live log, and the runbook
checks ausmt-test's log the same way before the cutover (12.1), since it uses the same recipe.

## D6. Cutover and rollback

Nectar addresses are fixed per instance (D1), so the cutover is a DNS change: both public names' A
records, TTL 300 seconds, move from ausmt-test's address to the serving host's.

1. Copy the `caddy_data` volume from ausmt-test to ausmt-serve BEFORE the serving front door first
   starts, so the certificate travels, and do it while the certificate has more than 30 days left, so
   no ACME order is attempted for a name that does not yet point at the new host. Caddy renews in the
   last third of a certificate's life; the live certificate for the public name runs 2026-08-17 to
   2026-11-15, so its window opens about 2026-10-16 (ausmt.au: 2026-09-19 to 2026-12-18). Inside the
   window the copy waits until ausmt-test has renewed. Steps 1 to 4 run back to back. Then finish
   provisioning, with `AUSMT_GATEWAY_UPSTREAM` naming the box's reader listener (D12).
2. Seed: the first publish from the box over the tailnet; `sudo ausmt-doctor-serve` green, its
   gateway line included.
3. Check the serving host end to end on itself with `curl --resolve <name>:443:127.0.0.1`: the
   certificate, the reader, `/data`, the wall refusals, and `GET /gateway/healthz` (a probe that
   submits nothing) answering through to the box.
4. Verify the serving host by name from off the tailnet without touching DNS
   (`curl --resolve <name>:443:<its address>`), then change both A records to its address. Proof of
   arrival is a request carrying a unique marker, found in the serving host's access log; a
   `build.json` check cannot tell the hosts apart, since both serve the same build.
5. Repoint the box's log pull at the serving host, after a last pull from ausmt-test whose live file
   is set aside under a name the stats fold still reads (both front doors write the same file name).
   A pull from ausmt-test just before the move, while its tailnet path is certain, leaves that last
   pull only the minutes around the move to collect.

The change has no gap. Until resolvers pick it up, for up to the TTL, visitors reach either host;
both serve the box's current build under the same certificate, and both send the four public gateway
routes to the box's reader listener (D12).

**Rollback is pointing the A records back at ausmt-test's address.** ausmt-test is left running and
untouched through a quiet period, still proxying to the box's reader listener, which keeps serving the
box's own current. It cannot renew while the names point away (the challenge reaches the serving
host), so its certificate
is good only until its own expiry, 2026-11-15 for the current one: the quiet period ends before that
date, and a rollback restarts ausmt-test's front door so that it renews at once. **ausmt-test is
deleted only after the quiet period**, and the rollback ends with it: deletion releases its fixed
address to the cloud, so both names must point at the serving host first, and the serving host's `caddy_data`
is in Docker's volume on its root disk, so a lost serving host after that means a new instance and a
fresh certificate. ausmt-test's tailnet tag and ACL entries go when it does. Procedure:
`deploy/nectar/RUNBOOK-NECTAR.md`.

## D7. Curator access layering

Two more curators join with no new code in the gateway:

1. **Tailnet invite**, signed in with a passkey or institutional single sign-on at the Tailscale login
   (the first factor, and the only way to the curation host at all).
2. **`group:curators`** in the tailnet policy reaching the curation host's tailnet name on port 443
   only (`deploy/nectar/acl-policy.hujson`). That is how curators reach the workbench today:
   `tailscale serve --bg https / http://127.0.0.1:8443` on the curation host publishes the portal
   listener under its MagicDNS name on 443 (`deploy/README.md`), and the portal listener proxies
   `/gateway/*` to the gateway. No new port and no new listener; 8444 is the gateway's loopback debug
   bind and is never granted.
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

* **Volume storage: 200 GB in QRIScloud**, 100 GB for the serving host and 100 GB for the curation
  host. Blocks the serving host's volume (D3; the runbook's proof serve on the root disk can run
  first) and the lift (D10).
* **RAM 16 to 32 GB and vCPU 8 to 16, optional**, headroom for a curation instance larger than
  m3.medium running the corpus build with more workers. The build fits m3.medium (D3, build memory),
  and m3.medium for both roles already fills the quota (D3). Serve m3.small plus curate m3.large costs
  about 2,500 SU a year against the 2,000 budget, so the line goes in only with a top-up of at least
  500 SU a year beside it; the owner includes or drops it when filing, and the volume line alone may
  be approved sooner.
* **An SU top-up only if the allocation runs past 12 months**, or at least 500 SU a year with the
  RAM line.
* **A second project member.**

The paste-ready text is in `deploy/nectar/RUNBOOK-NECTAR.md`.

## D10. What stays on the box until the curate lift, and the lift

**Stays on the box:** surveys-live and git-creds, the gateway, clamd and gw-runner, the sqlite, the
build and its cache, the reconcile timer (now publishing), backups and the restore drill, the stats
fold and the front-door log pull, the alert and actions timers, and the box's own portal (the curator
workbench over the tailnet, and ausmt-test's upstream through the quiet period).

**The lift, in order** (commands in runbook 16). Two rules govern it: one sender at every moment,
and no submission accepted on a host whose state is about to be copied.

1. **Create ausmt-curate** (m3.medium, D3; Classic Provider, so it has a fixed address that carries
   its outbound traffic: GitHub, GHCR, ClamAV updates, Tailscale; no security group that admits
   inbound traffic once joined, `default` and `http` included; `tag:ausmt-curate`), bootstrapped like
   the serving host through a temporary 22/tcp group from the operator's address (D5).
2. **Its volume**: 100 GB (D9), labelled and mounted at `/srv/ausmt`, holding the whole tree, so that
   `site-data/builds` and `site-data/cache` share one filesystem (D1, D3).
3. **Provision** with the full `deploy/README.md` checklist (gateway profile and the 10002 tree
   included, and the two `tailscale serve` publications: the reader port for the serving host's
   gateway routes, 443 for curators), `AUSMT_BUILD_MEM_LIMIT=4g` and `AUSMT_GW_MEM_LIMIT=2g` in its
   `deploy/.env` (D3), timers
   installed but disabled and the gateway profile down.
4. **Freeze submissions on the box, then take the final backup.** Stop the box's gateway (the four
   public routes answer an error, and the Add Survey page hides its Submit button), let gw-runner
   finish what it holds, stop the gateway profile, then
   `sudo systemctl disable --now ausmt-reconcile.timer ausmt-actions.timer ausmt-backup.timer`,
   remove `AUSMT_PUBLISH_TARGET` from the box's `deploy/.env`, and run `ausmt-backup.service` once.
   Disabled, not stopped: a stopped timer starts again at the box's next boot, and a second sender
   switches the public build every tick while each pass reports `publish=ok` (D4, one sender).
5. **Move the state**: the final snapshot's sqlite (the only home of submitter PII) and
   `gateway/{incoming,jobs,quarantine}` and the usage-statistics history
   (`gateway/state/{stats.json,daily_archive.jsonl}`), box to ausmt-curate directly over the tailnet, never through
   the serving host or any public host; encrypted first (`gpg --symmetric`) if it rests anywhere in
   between. Restore it through the restore-drill path.
6. **Publish from ausmt-curate, then reopen**: enable its timers with `AUSMT_PUBLISH_TARGET` set; watch
   one publish land, with `published.json` naming ausmt-curate as `sender`; set
   `AUSMT_PUBLISH_SENDER` and `AUSMT_GATEWAY_UPSTREAM` in the serving host's `deploy/.env` to
   ausmt-curate's address and reader listener and re-run its provisioning; bring ausmt-curate's
   gateway profile up, which reopens submissions there.
7. **Retire the box**: drop its phase-one rules from the tailnet policy (the `<BOX_NODE_USER>` ssh rule
   for `publish` and `caddylog`, and `ausmt-box` from the other three rules, and the box's entries in
   the `tests` and `sshTests` stanzas, which the console checks on every save), prove the fence again
   from the serving host against ausmt-curate (runbook 5.5), disable the box's remaining timers and
   take its stacks down.

## D11. Open questions

1. **Per-file byte determinism.** How much `--link-dest` saves depends on how many files a rebuild
   writes byte-identical. A separate change makes the MTH5 tiers cache-reused, so unchanged station
   files keep their bytes across builds; after two publishes, `find builds/<ts> -type f -links +1 |
   wc -l` on the serving host counts the files the second build shares with the first.
2. **Tailscale SSH and the gates: closed for phase one by owner ruling 2026-10-02.** The gates rely
   on Tailscale SSH running the login shell with `-c`, and runbook 9.2 proves that on the real host
   (`receive-build.sh --current` answers, `sh` is refused). Tailscale SSH serves SFTP in-process,
   outside the gate (D4), and OpenSSH bound to the tailnet address cannot run beside
   `tailscale up --ssh`, which owns tailnet port 22. The ruling accepts SFTP for phase one, while the
   box is the sender: the publish account's writable tree is `site-data`, the tree it exists to
   replace, the serving host holds no secret the account can reach, and the `caddylog` account can
   read world-readable
   files only. The runbook's SFTP and port-forwarding probes are withdrawn; its `--current` and `sh`
   probes stay. **Revisit at the curate lift**, when the sender is a Nectar host on the private
   network and OpenSSH can bind there for the two service accounts (`Match User publish,caddylog`
   with `ForceCommand` to the gate, no forwarding, no TTY, no sftp subsystem). Tailscale stays for
   now; whether to run without it is a later question the owner has deferred.
3. **The box's reconcile prune.** `reconcile.sh` prunes stale builds on entry as the operator, and the
   build directories belong to uid 10001 with no group write, so on the box that prune can only remove
   what the operator owns. Not verified on the box; the Makefile's in-container prune is unaffected.
4. **Headroom on an m3.medium curation host.** Both container ceilings are knobs
   (`AUSMT_BUILD_MEM_LIMIT`, `AUSMT_GW_MEM_LIMIT`), and ausmt-curate sets 4g and 2g (D3), so the
   compose rule holds. What remains open is whether 2 GiB of headroom beside a cold build and a
   submission in flight is enough in practice; the first weeks of curate's own build reports and
   gw-runner logs answer it, and a larger flavour is the remedy.
5. **Releases on the replica.** The publish contract carries `site-data/builds/` only, and
   `make cut-release` writes `site-data/releases/`, a sibling of `builds/`, so a release never reaches
   the serving host. The public site serves no release today (`/data/releases/releases.json` answers
   404), so nothing is lost yet. Decide before the first release cut after the cutover whether
   releases are served, and if so how they reach the replica.

## D12. Decision: the public gateway routes follow the curation host

The Add Survey flow is public (C47 D3): `POST /gateway/submit`, `POST /gateway/request-key`,
`GET /gateway/healthz` and `GET /gateway/status/*`. The serving host runs no gateway, so the front door
gives exactly those four routes their own upstream, `AUSMT_GATEWAY_UPSTREAM`. On the serving host it
names the curation host's reader listener over the tailnet: while the box curates, the box's MagicDNS
name and tailscale-serve reader port, the value ausmt-test's front door uses as its reader upstream.
That listener's wall 2 already proxies exactly those four routes to its gateway and refuses every other
`/gateway` path, so the curation host keeps its own allowlist. Wall 1 allows exactly what it allowed
before; only the destination of the four routes changes.

* **Default.** Unset or empty, `install-frontdoor.sh` renders the variable as the reader upstream, so
  the box's front-door deployment adapts to the identical config.
  `deploy/tests/test_install_frontdoor_reload_sh.py` pins that identity with `caddy adapt`, and pins
  that a set value changes the upstream of exactly four routes and nothing else;
  `deploy/tests/test_frontdoor_bridge.py` drives the split against a real Caddy.
* **Reach.** The tailnet policy grants `tag:ausmt-serve` the curation host's port 8445 and no other
  port (`deploy/nectar/acl-policy.hujson`).
* **Cutover.** The routes stay live through the DNS change (D6).
* **Failure.** With the curation host unreachable the four routes answer an error at the public name
  and readers are unaffected. `doctor-serve.sh` probes `GET /gateway/healthz` through the front door
  and reports WARN, never FAIL, when it does not answer 200.
* **The lift** moves the variable to ausmt-curate's reader listener (D10).

## Executed

The serving replica went live on 2026-10-13 and 2026-10-14; the record of the session is
`AusMT_2026/HANDOVER-2026-10-14-NECTAR-CUTOVER-AND-HOUSE-STYLE.md` and the networking as found is
section 1A of `AusMT_2026/NECTAR-CUTOVER-CHECKLIST-2026-10-13.md`.

* **Networking as found (2026-10-13).** The project has no router and no private network. The launch
  wizard offers only Classic Provider, which gives an instance a fixed public address on `qld` and an
  interface on `qld-data`, QRIScloud's storage network. Nothing floats, so the designed address move
  was not available; the owner ruled the cutover a DNS change.
* **Addresses.** ausmt-serve: 203.101.226.53 (`qld-data` 10.255.137.28). ausmt-test: 203.101.226.191,
  released when the instance is deleted, which is due before 2026-11-15, its certificate's expiry.
* **Root disk (owner ruling 2026-10-13).** Phase one serves from ausmt-serve's 30 GB m3.small root
  disk at one kept build: the tree is the directory `/var/lib/ausmt-proof`, bind-mounted at
  `/srv/ausmt` (runbook 4A), with `AUSMT_PUBLISH_KEEP=1` in the box's `deploy/.env`. This overrides
  the runbook's earlier "never on the root disk"; the volume waits on the amendment (D9) and is
  needed before the curate lift. The root disk stood at 52 percent with one build on 2026-10-14.
* **Launch and seed (2026-10-13).** Security groups `http` and a temporary `ssh` group narrowed to
  the owner's address; tailnet policy merged and the fence proven (runbook 5.5); certificate volume
  copied, so the front door placed no ACME order; seed publish of 7.3 GiB in 87,637 files over a
  direct tailnet path, about an hour.
* **Tailnet policy, as merged.** The administrators' `check` SSH rule names the users `ubuntu` and
  `root`. The committed rule named `autogroup:nonroot`, which includes the gated `publish` and
  `caddylog` accounts; Tailscale applies the stricter action, so the policy's own `sshTests` refused
  the save. `deploy/nectar/acl-policy.hujson` now carries the merged form.
* **DNS change (2026-10-14, about 07:00 UTC).** Verified beforehand with `curl --resolve` against
  203.101.226.53. `ausmt.auscope.org.au` (AuScope's cPanel zone) was changed by AuScope's director on
  request and `ausmt.au` (VentraIP) by the owner, both to 203.101.226.53 at TTL 300. The marker
  request `cutover-1791961947` answered 200 and reached ausmt-serve's log; `sudo ausmt-doctor-serve`
  was all PASS at 07:13 UTC, its DNS line included. The box's log pull was repointed at 07:32 UTC.
  Rollback is both A records back to 203.101.226.191 while ausmt-test exists.
* **Log retention.** At `roll_keep 5` with a daily pull, exactly five rolls reached the box in 7 of
  the 24 daily windows from 20 September to 13 October, five being the cap, so rolls on those days
  were deleted before the pull. On 2026-10-14 the handover offered the owner an hourly systemd
  drop-in for the box's daily timer; it is not confirmed applied. The repository now ships the
  hourly timer and a roll depth of 49 (`deploy/frontdoor/README.md`, "Log retention and the pull
  cadence").

## Provenance

Owner rulings 2026-09-30 (two roles and their contents, flavours, sequence, tailnet as identity layer,
curator layering, floating-IP cutover and rollback, the amendment, the continuity items). Owner rulings
2026-10-13 (the DNS cutover in place of the floating-IP move, and the root-disk serve; "Executed").
Owner ruling 2026-10-02 (the service accounts' SFTP path over Tailscale SSH accepted for phase one, D4 and D11).
Measured 2026-10-02: the size of one build, the MTH5 cache generation, the box's Linux build memory
and the live certificate dates (D1). Architect
rulings 2026-09-30 (the public gateway routes' upstream, curator access on 443, GHCR visibility, the
build memory reading). Build memory from the cold and warm `build_report.json` of a 2026-09-30 macOS
build. Facts from
the owner's Nectar dashboard and the ARDC support pages, checked 2026-09-30; box measurements by the
owner 2026-09-30 and 2026-09-14. Deliverables: the sender and receiver, the two gates, `make publish`,
the reconcile publish step and status field, the publish alert, `deploy/nectar/` (cloud-init,
provisioning, the serve doctor, the tailnet policy entries, the runbook), the loopback leg of the
front-door doctor, and the pins listed in D4.
