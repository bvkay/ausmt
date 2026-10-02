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
  `site-data/cache` 2.2G (the 2048 MB cap main ships), `basemap` 2.4G.
* **One built tree, measured** (2026-10-02, 15,265 stations, from the live products manifest and an
  acceptance build of the same corpus): **7.5 GB (7.0 GiB)**, of which h5 2.89 GB, bundles 1.50,
  xml 1.47, edi 1.18, pages and products 0.48. About 3.6 GB of it is non-MTH5 and is rewritten by
  every build. The 2026-09-14 figure, about 2.9 GB at 4,961 station h5 files (a count of files, not
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
| Public address | floating IP (the one ausmt-test holds today) | none |
| Security group | 80/tcp and 443/tcp from anywhere, nothing else | nothing inbound from the internet |
| Runs | the front-door Caddy (`deploy/frontdoor`) and the portal container, on one host, reader upstream `http://127.0.0.1:8445`, gateway upstream the curation host's reader listener (D12) | gateway, clamd, gw-runner, surveys-live, git-creds, the sqlite, reconcile and the build |
| Holds | the built tree on a Cinder volume at `/srv/ausmt` | everything the build and the curator workbench need, on its own Cinder volume at `/srv/ausmt` |
| Never holds | a git write credential, the gateway, the sqlite, the build cache | a public listener |
| Flavour | m3.small first, m3.medium if serving needs it | m3.medium with the build capped at 4g (D3), or larger after a RAM amendment |
| Gets data by | publish from the curation host (D4) | curator publishes to surveys-live |

The serving host is the only machine on the internet and it holds nothing that is not already public
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
`default` group are not in the D1 facts and are to be read in the dashboard. The curation host has no
public address and is reached only over the tailnet.

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
  for volume storage in QRIScloud, the availability zone ausmt-test and its floating IP live in: one
  100 GB volume per host.
* **Sizing the serving volume.** One build is 7.5 GB (D1). Five kept builds take between 21.9 GB
  (7.5 + 4 × 3.6, when each later build links its h5 files to the one before and stores its 3.6 GB of
  non-MTH5 afresh) and 37.5 GB (5 × 7.5, when nothing links), plus the 2.4 GB basemap: at most
  39.9 GB. The 100 GB volume leaves room for the corpus to keep growing at five kept builds. The first
  publish sends the whole 7.5 GB (runbook 9.3).
* **Sizing the curation volume.** The curation host holds the kept builds plus one in progress, the
  MTH5 build cache, surveys-live, the basemap, the gateway state and the ClamAV database. Its
  site-data floor today is about 28 GB (31 GB with a build in progress) before Ubuntu and the images,
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
  `AUSMT_BUILD_MEM_LIMIT` (default 8g, sized for the box) and gw-runner at a fixed 4g, and requires
  the two ceilings to sum below the host. On ausmt-curate `deploy/.env` sets
  `AUSMT_BUILD_MEM_LIMIT=4g`: 4,096 MiB holds the measured 3,663 MiB with 433 MiB to spare. With
  gw-runner's 4g the two ceilings then sum to 8 GiB, the whole of an m3.medium, not below it; the
  rule holds on m3.medium only with gw-runner's ceiling lowered as well (D11, question 4).
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
`make up`, then `install-frontdoor.sh`. Provisioning also carries `AUSMT_GATEWAY_UPSTREAM` from
`deploy/.env` into the front door's `.env` (D12). The GHCR images are public (an anonymous token got
HTTP 200 on the `ghcr.io/bvkay/ausmt-portal` tags list, checked 2026-09-30), so the serving host holds
no registry credential. Until its tailnet join the serving host is reached at the project's second
floating IP (D1 gives a quota of 2), associated at launch and released once the join is proved; from
then until the cutover it has no internet address and reaches the internet through the project
router's SNAT, checked before launch (runbook 3.0). The front-door doctor skips its two
tailnet-peer legs on a loopback upstream; `deploy/nectar/doctor-serve.sh` reports the whole serve role in the doctor-box shape.

The masked front-door log keeps flowing to the analytics fold on the curation host: the log account
`caddylog` exists on the serving host with `deploy/nectar/caddylog-gate.sh` as its login shell
(`rrsync -ro /var/log/caddy`, the forced command of `deploy/frontdoor/RUNBOOK.md` 5.2, applied at the
shell because Tailscale SSH never reads the key), and the box's `AUSMT_FRONTDOOR_LOG_REMOTE` moves to it
at cutover.

## D6. Cutover and rollback

The public name already resolves to 203.101.226.191, so the cutover moves the address, not DNS:

1. Copy the `caddy_data` volume from ausmt-test to ausmt-serve BEFORE the serving front door first
   starts, so the certificate travels and no ACME order is attempted for a name that does not yet
   point at the new host. Then finish provisioning, with `AUSMT_GATEWAY_UPSTREAM` naming the box's
   reader listener (D12).
2. Seed: the first publish from the box over the tailnet; `doctor-serve.sh` green, its gateway line
   included.
3. Check the serving host end to end on itself with `curl --resolve <name>:443:127.0.0.1`: the
   certificate, the reader, `/data`, the wall refusals, and `GET /gateway/healthz` (a probe that
   submits nothing) answering through to the box.
4. Move the floating IP from ausmt-test to ausmt-serve in the dashboard (disassociate, associate).
5. Repoint the box's log pull at the serving host, after a last pull from ausmt-test whose live file
   is set aside under a name the stats fold still reads (both front doors write the same file name).

The four public gateway routes stay live through the move: before it ausmt-test sends them to the
box's reader listener, and after it ausmt-serve sends them to the same listener (D12).

**Rollback is moving the floating IP back.** ausmt-test is left running and untouched through a quiet
period, still proxying to the box's reader listener, which keeps serving the box's own current. Its
certificate may be older than the serving host's by then; it is still valid within its own renewal
window and Caddy renews it once the address is back. **ausmt-test is deleted only after the quiet
period**; its tailnet tag and ACL entries go with it. Procedure: `deploy/nectar/RUNBOOK-NECTAR.md`.

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

**The lift, in order:** create ausmt-curate (m3.medium, D3; no floating IP, no security group that
admits inbound traffic, `default` included; `tag:ausmt-curate`) and provision it with the full
`deploy/README.md` checklist (gateway profile and the 10002 tree included, and the two `tailscale
serve` publications: the reader port for the serving host's gateway routes, 443 for curators); restore
the sqlite from the newest backup through the restore-drill path; stop the box's reconcile, actions and
backup timers so there is one writer and one publisher; enable them on ausmt-curate with
`AUSMT_PUBLISH_TARGET` set; watch one publish land; set `AUSMT_GATEWAY_UPSTREAM` in the serving host's
`deploy/.env` to ausmt-curate's reader listener and re-run its provisioning; retire the box. The curation host has no
public address, so its outbound traffic (GitHub, GHCR, ClamAV updates, Tailscale) must leave through
the project router, whose external gateway, SNAT and `qld-data` interface are checked before the
serving host's launch (runbook 3.0).

## D11. Open questions

1. **Per-file byte determinism.** How much `--link-dest` saves depends on how many files a rebuild
   writes byte-identical. A separate change makes the MTH5 tiers cache-reused, so unchanged station
   files keep their bytes across builds; after two publishes, `find builds/<ts> -type f -links +1 |
   wc -l` on the serving host counts the files the second build shares with the first.
2. **Tailscale SSH and the gates.** The gates rely on Tailscale SSH running the login shell with `-c`.
   The runbook's first publish test from the box proves it on the real host (`receive-build.sh
   --current` answers, `sh` is refused). Two channels never start the login shell: the sftp subsystem
   and a port-forwarding channel. The `restrict` on the OpenSSH key does not apply on the Tailscale
   path, and whether Tailscale SSH serves either channel to a gated account is not verified here. The
   runbook (9.2) requires an `sftp` session and an `ssh -N -L` forward to both fail before the first
   publish. If either succeeds, the two service accounts move to OpenSSH bound to the tailnet address,
   with `Match User publish,caddylog` setting `ForceCommand` to the gate, `AllowTcpForwarding no`,
   `X11Forwarding no`, `PermitTTY no` and no sftp subsystem, and leave the Tailscale `ssh` rules.
3. **The box's reconcile prune.** `reconcile.sh` prunes stale builds on entry as the operator, and the
   build directories belong to uid 10001 with no group write, so on the box that prune can only remove
   what the operator owns. Not verified on the box; the Makefile's in-container prune is unaffected.
4. **gw-runner's ceiling on an m3.medium curation host.** `AUSMT_BUILD_MEM_LIMIT=4g` holds the
   measured build (D3), but gw-runner's ceiling is a fixed 4g in `deploy/compose.yaml`, so the two sum
   to the whole 8 GB host and the compose file's own rule (the two ceilings sum below the host) is not
   met. Settle before the lift: a lower gw-runner ceiling on the curation host (a compose change), or
   a larger curation flavour.

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
* **Cutover.** The routes stay live through the floating-IP move (D6).
* **Failure.** With the curation host unreachable the four routes answer an error at the public name
  and readers are unaffected. `doctor-serve.sh` probes `GET /gateway/healthz` through the front door
  and reports WARN, never FAIL, when it does not answer 200.
* **The lift** moves the variable to ausmt-curate's reader listener (D10).

## Provenance

Owner rulings 2026-09-30 (two roles and their contents, flavours, sequence, tailnet as identity layer,
curator layering, floating-IP cutover and rollback, the amendment, the continuity items). Architect
rulings 2026-09-30 (the public gateway routes' upstream, curator access on 443, GHCR visibility, the
build memory reading). Build memory from the cold and warm `build_report.json` of a 2026-09-30 macOS
build. Facts from
the owner's Nectar dashboard and the ARDC support pages, checked 2026-09-30; box measurements by the
owner 2026-09-30 and 2026-09-14. Deliverables: the sender and receiver, the two gates, `make publish`,
the reconcile publish step and status field, the publish alert, `deploy/nectar/` (cloud-init,
provisioning, the serve doctor, the tailnet policy entries, the runbook), the loopback leg of the
front-door doctor, and the pins listed in D4.
