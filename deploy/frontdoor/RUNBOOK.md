# Owner runbook — AusMT public bridge (C47)

The numbered, self-contained procedure to expose the AusMT reader at the public name via a VPS
front door on the tailnet, and to withdraw it again. Design + rationale: `maintainer/C47-PublicBridge.md`.

Canonical-name ruling (2026-08-18): the CANONICAL public name is `ausmt.auscope.org.au` (the
institutional AuScope name; its DNS record lives in a zone AuScope administers and already points at
the VPS). The retired personal name `ausmt.au` is kept, optionally, as a PERMANENT (301) redirect to
the canonical name with path and query preserved. In `.env` terms: `AUSMT_PUBLIC_NAME` is the
canonical name and `AUSMT_LEGACY_REDIRECT_NAME` is the legacy one (empty = serve the canonical name
only; install-frontdoor.sh renders the redirect site block out entirely in that case). With the
legacy name set the edge holds a certificate for EACH name, so expect TWO ACME issuances in the log.

**You (the owner) run every VPS / DNS / tailnet step personally.** The repo produces the files and this
runbook; nothing here is automated against your infrastructure. Topology in one line:

```
internet ──▶ VPS front door (public TLS, masked log) ──tailnet(WireGuard)──▶ box reader listener :8081
                                                                              (box: no inbound, no fw change)
```

Two independent walls keep the curator/admin workbench private while the public submission subset is
served. Both walls are allowlists of the SAME subset (the reader, `/data`, `GET /add-survey.html`, and
the four public gateway routes `POST /gateway/submit`, `POST /gateway/request-key`,
`GET /gateway/healthz`, `GET /gateway/status/*`): (1) the front door allows only that subset and refuses
every other `/gateway` path; (2) the box `:8081` listener proxies only the four public gateway routes to
the gateway container, refuses every other `/gateway` path itself, AND the tailnet ACL lets the VPS
reach only that listener's port (never the `:8080` workbench port). The Add Survey contribution flow is
public since the 2026-07-24 owner ruling; the curator workbench is not.

---

## 0. Prerequisites

- The box already runs the AusMT stack on the tailnet (per `deploy/README.md`).
- You have Tailscale admin access (to add a tag + ACL rule and mint an auth key).
- The DNS for each served name points (or can be pointed) at the VPS: the canonical
  `ausmt.auscope.org.au` record lives in a zone AuScope administers, and the legacy `ausmt.au`
  record (only if you keep the redirect) at your registrar.
- The capricorn-2010 `lead_investigator` citation-metadata fix is merged and built into the corpus
  the box currently serves (its serve-verification is step 7 — the content-clean gate, run BEFORE the
  DNS cutover).

---

## 1. Pull the box-side change and rebuild the portal image

The bridge adds a dedicated **public-subset listener** (`:8081`) to the box's Caddy (the second wall):
it serves the reader plus the Add Survey page, proxies only the four public gateway routes to the
gateway container, and refuses the rest of `/gateway`.

1.1  On the box, update the checkout to the branch/release carrying C47 and rebuild + restart the
     portal image so `:8081` is live:
```sh
cd <your ausmt-code checkout>
git pull                                   # or check out the C47 release tag
docker compose build portal                # bake the new Caddyfile into the portal image
mkdir -p "$AUSMT_DATA_DIR/logs/caddy"       # (already exists if C45 logging is on)
docker compose up -d portal
```
1.2  Confirm the `:8081` listener serves the public subset and refuses the workbench locally (loopback
     publish 127.0.0.1:8445 → container :8081):
```sh
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8445/                        # expect 200 (reader)
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8445/add-survey.html         # expect 200 (public page)
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8445/gateway/curator/queue   # expect 404 (walled)
# the four public gateway routes proxy to the gateway container -- with the gateway profile up:
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8445/gateway/healthz         # expect 200 (public)
```
The `404` on `/gateway/curator/*` is wall 2 proving itself: the listener refuses the workbench (it has
no route to it), while it proxies only the four public routes to the gateway container. If the gateway
profile is not up, `/gateway/healthz` returns `502` instead of `200` (the listener has the route, but
nothing is listening behind it yet); the `404` on the workbench is independent of the gateway state.

1.3  Expose the reader listener onto the tailnet on a dedicated port (raw TCP; TLS is the VPS's job,
     the tailnet hop is already WireGuard-encrypted):
```sh
sudo tailscale serve --bg --tcp=8445 tcp://127.0.0.1:8445
tailscale serve status                     # confirm :8445 → 127.0.0.1:8445 is listed
```
Get the box's tailnet IP for the ACL step: `tailscale ip -4` (a `100.x.y.z` address).

---

## 2. Provision the VPS (Sydney region, provider-agnostic)

2.1  Create the smallest VPS in a Sydney region with a public IPv4 (and IPv6 if offered). Note its
     public IP(s) for the DNS step.
2.2  Basic hardening (do this before anything else listens):
```sh
sudo apt-get update && sudo apt-get -y upgrade          # or your distro's equivalent
# key-only SSH: put your public key in ~/.ssh/authorized_keys, then:
sudo sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart ssh
```
2.3  Firewall: allow only what the edge needs from the internet — inbound tcp **80** and **443**
     (public web) and **22** (ssh, ideally restricted to your admin IPs or the tailnet). Everything
     else denied. Use the provider's security group and/or ufw. Tailscale brings its own encrypted
     path and needs no extra public inbound.
2.4  Install Docker + the compose plugin, and Tailscale:
```sh
curl -fsSL https://get.docker.com | sh
curl -fsSL https://tailscale.com/install.sh | sh
```

### 2N. Nectar Research Cloud variant (the owner's provider)

Nectar exposes OpenStack; the steps above map to the Nectar dashboard as follows (do these in place of a
generic provider's console, then continue at step 3).

2N.1  **Launch the instance** (Compute → Instances → Launch Instance): smallest flavour, a current
      Ubuntu LTS image, an **Australian availability zone**. Boot from image onto a small new volume.
2N.2  **Security group** (Network → Security Groups): a group allowing INBOUND tcp **80** and **443**
      only, from `0.0.0.0/0` — nothing else. Do **not** open **22** to the public; SSH stays closed on
      the public interface and you administer over the tailnet after the join step (step 4). Attach the
      group to the instance. *Bootstrap access* for the very first login (before Tailscale is up): use
      the Nectar web console (Compute → Instances → Console) to reach the shell, **or** temporarily add
      an SSH rule scoped to your own admin IP and remove it the moment the node has joined the tailnet.
2N.3  **Floating (public) IP** (Network → Floating IPs): allocate one to the project and associate it
      with the instance — this is the public IPv4 for the DNS step (step 8). Nectar floating IPs are
      IPv4 only, so create just an **A** record later (no AAAA).
2N.4  **Allocation:** a Nectar **project-trial** allocation is enough to stand the front door up. The
      front door is **stateless** (no corpus or state lives on it — everything stays on the box), so
      migrating to a full allocation later is simply a runbook re-run on a fresh instance: repeat
      steps 2–6, re-point the DNS A record (step 8) at the new floating IP, and tear the trial instance
      down (section 10). Nothing is lost in the move.

---

## 3. Add the dedicated tailnet tag + the ACL fence (Tailscale admin console)

3.1  Open the Tailscale admin console → **Access controls**. Merge the stanza from
     `deploy/frontdoor/acl-policy.hujson` into your policy. Fill the two placeholders:
     `<BOX_TAILNET_IP>` (from step 1.3) and `<ADMIN_OWNER>` (your admin user/group). Save.
     - This defines `tag:ausmt-frontdoor`, grants it reach to **`ausmt-box:8445` only** (the reader
       port — wall 2's fence), and separately lets the box pull logs (`ausmt-box → tag:ausmt-frontdoor:22`).
3.2  Mint a **tagged auth key**: Settings → Keys → Generate auth key → attach tag `tag:ausmt-frontdoor`
     (ephemeral optional; reusable if you may reprovision). Copy it.

---

## 4. Join the VPS to the tailnet under the dedicated tag

On the VPS:
```sh
sudo tailscale up --authkey <TAGGED_AUTH_KEY> --advertise-tags=tag:ausmt-frontdoor --hostname ausmt-vps
tailscale status                           # confirm the node is up and carries tag:ausmt-frontdoor
```
Verify the fence from the VPS **before** deploying anything. The positive leg confirms the reader port
is reachable; the negative leg must exercise the ACL against a surface the box **actually exposes on the
tailnet** — otherwise it proves nothing. The box's genuine curator surface on the tailnet is its
full-portal HTTPS listener, fronted by `tailscale serve --bg https` (step 1 topology / `deploy/README.md`
"Expose to your tailnet"): `https://ausmt-box/` on **:443**, which carries `/gateway/*`. That is what the
ACL must deny to this tag — the reader port `:8445` is the ONLY grant.
```sh
curl -sS -o /dev/null -w '%{http_code}\n' http://ausmt-box:8445/                        # expect 200 (reader port granted)
curl -sS -k --max-time 5 -o /dev/null -w '%{http_code}\n' \
     https://ausmt-box/gateway/curator/queue || echo BLOCKED                            # expect BLOCKED / timeout
```
The reader port answers. The full-portal HTTPS surface (`:443`, which carries `/gateway/*`) is a live
tailnet listener on the box, so the negative leg can ONLY be blocked by the ACL port-scope (8445 granted,
443 denied) — the block genuinely proves the fence, not a dead port. (`-k` skips cert validation: we are
testing REACHABILITY, and if the ACL denies, the TLS handshake never starts anyway.)

**What a FAILING result looks like:** any HTTP status printed on the second leg (200 / 301 / 401 / 404 —
*any* response instead of `BLOCKED`/timeout) means the front-door tag reached the box's `:443`
full-portal surface. The ACL is NOT port-scoped to the reader — **STOP**, fix the ACL (step 3.1) so
`tag:ausmt-frontdoor` reaches `ausmt-box:8445` and nothing else, and re-run this check before proceeding.
Wall 2's fence is not standing until this leg is blocked.

---

## 5. Set up log shipping (box pulls the masked front-door log)

5.1  On the VPS, create a restricted read-only account for the pull and a log dir. The account is never
     used interactively (the forced command in 5.2 is the real control), but it still needs a shell to
     exec that command:
```sh
sudo useradd -m -s /bin/sh caddylog
sudo mkdir -p /var/log/caddy
sudo setfacl -R -m u:caddylog:rX /var/log/caddy    # read-only for the puller (or use group perms)
```
5.2  Put the **box's** SSH public key into `caddylog@ausmt-vps:~/.ssh/authorized_keys` as a
     **forced-command, read-only** entry - NOT a bare key. The box only ever runs a read-only `rsync`
     of the log dir, so bind the key to exactly that:
```
command="rrsync -ro /var/log/caddy",no-pty,no-port-forwarding,no-agent-forwarding,no-X11-forwarding ssh-ed25519 AAAA...box-public-key... ausmt-box-log-pull
```
   `rrsync` is the restricted-rsync wrapper shipped with rsync (recent Debian/Ubuntu install it at
   `/usr/bin/rrsync`; older packages keep it gzipped under `/usr/share/doc/rsync/scripts/rrsync.gz`).
   `-ro` permits READ-ONLY transfers and confines every path to the `/var/log/caddy` subtree; the
   `no-pty,no-*-forwarding` options strip the interactive shell and every tunnelling capability.
   **Why this matters:** the VPS is the one internet-facing host in the topology. A bare
   `authorized_keys` entry would hand anyone who compromised the box (or lifted its pull key) an
   INTERACTIVE SHELL on that public VPS, plus port/agent forwarding back through it. The forced command
   reduces the key to "read the masked logs, nothing else" - pull-only, read-only, one directory - which
   is the entire trust the box needs (the same read-only pull model as `pull-backup.sh`). Generate a
   dedicated key on the box if it has none (`ssh-keygen -t ed25519 -f ~/.ssh/ausmt-log-pull`); the box
   connects OUT to the VPS over the tailnet (allowed by the ACL rule from step 3.1).
5.3  On the box, set the remote in `deploy/.env`. Because the forced command **roots `rrsync` at
     `/var/log/caddy`**, the pull path is interpreted RELATIVE to that root, so the remote is just the
     account with no path (ship-frontdoor-logs.sh appends the trailing slash, pulling the rooted dir).
     An absolute `.../var/log/caddy` here would resolve UNDER the root to a non-existent
     `/var/log/caddy/var/log/caddy` and the pull would silently transfer nothing:
```sh
AUSMT_FRONTDOOR_LOG_REMOTE=caddylog@ausmt-vps:
```
   The masked `access-frontdoor*.json` files sit at the root of `/var/log/caddy`, which is exactly what
   the `--include='access-frontdoor*.json'` filter in the ship script copies. Verify the pull end-to-end
   on first run (step 9.4) after the front door is serving.
5.4  Install the box-side shipping timer (fires 03:25 UTC, before the 03:35 C45 fold):
```sh
# edit the __DEPLOY_DIR__/__ENV_FILE__ placeholders + User= in the .service first (see the file header)
sudo cp deploy/frontdoor/ausmt-frontdoor-logs.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ausmt-frontdoor-logs.timer
```
(You can run it once now to test only after the front door is serving — step 9.4.)

---

## 6. Deploy the front-door stack on the VPS

6.1  Put the C47 `deploy/frontdoor/` subtree on the VPS (clone the repo or copy the subtree). In
     `deploy/frontdoor/`, create `.env` from `.env.example`:
```sh
AUSMT_PUBLIC_NAME=ausmt.auscope.org.au
AUSMT_LEGACY_REDIRECT_NAME=ausmt.au          # optional: empty = no legacy redirect block at all
AUSMT_BOX_READER_UPSTREAM=http://ausmt-box:8445
AUSMT_ACME_EMAIL=you@example.org
```
6.2  Apply (validates the Caddyfile, then brings the one service up):
```sh
cd deploy/frontdoor
./install-frontdoor.sh
```
The installer is safe to re-run for a config change (ops-hardening O1): if the edge is ALREADY running
it reloads the running container in place (`caddy reload`) so a Caddyfile edit takes effect immediately,
instead of leaving the old config serving (the 2026-07 stale-wall incident). The reload uses the admin
API on a unix socket in the container (no network port is opened). If the reload cannot run (the admin
socket is disabled, or the container cannot fork), the installer prints a LOUD warning and falls back to
`docker compose restart frontdoor`, which applies the config with a roughly one-second bounce (the ACME
certificate persists in the `caddy_data` volume, so no re-issue). Either way the running edge ends up on
the shipped Caddyfile. A first install (nothing running yet) just starts clean, no reload needed.

6.3  **Time-series hand-off routes** (`/go/ts/<survey>/<station>/<level>`). The edge answers these with
     a 302 to the file's one NCI THREDDS `fileServer` URL; AusMT hands the reader off and hosts nothing.
     The resolution lives in `ts-routes.map`, a GENERATED, COMMITTED table beside the Caddyfile that the
     Caddyfile `import`s, so it reaches the VPS the same way the Caddyfile does - `git pull` in this
     subtree, then `./install-frontdoor.sh`. There is no other path onto the VPS and no box-to-VPS push.

     **The table goes out BEFORE the data, always.** Its membership is the suppression: a station that
     stops being open has to lose its route first, so the order is table, then publish. Regenerate it in
     the repo (never on the VPS, and never by hand - every line is a published route):
```sh
python deploy/scripts/gen_ts_routes.py --write     # from the ausmt-surveys registers
python deploy/scripts/gen_ts_routes.py --check     # the gate: exit 1 if the table and registers disagree
```
     A survey whose registers the generator cannot resolve DROPS ITS OWN ROUTES and no others: it
     prints a loud `DROPPED` warning, records `# UNRESOLVED <survey>: <reason>` in the table itself,
     and every other survey keeps routing. That is deliberate. A route the table stops naming 404s,
     which is a broken hand-off; a table that cannot be regenerated at all leaves the PREVIOUS one
     serving, and a stale table is a stale ACCESS decision. So the hand-offs of one survey go offline
     rather than the suppression of every survey lagging. Treat an `UNRESOLVED` line as an incident:
     fix the register, regenerate, commit.
     Then on the VPS: `git pull`, `./install-frontdoor.sh`, `./doctor.sh`. The doctor's `ts-routes` leg
     must PASS on **both** its open-302 and its 404 probes before the data publish proceeds - a route
     the table does not name must produce no `Location` at all.

**Do not create the DNS record yet** — the content-clean gate (step 7) must pass FIRST, so DNS is only
created once the served corpus is proven clean (invariant f: content-clean BEFORE the DNS cutover). The
certificate also cannot issue until DNS points at the VPS, so the gate is verified against the box's
tailnet-served copy — the exact bytes the stateless front door will proxy. Proceed to step 7.

---

## 7. Content-clean gate — verify the served corpus BEFORE the DNS cutover

This gate runs **before** any DNS record exists, so there is never a public window of unverified
content. The front door is stateless — it proxies straight to the box reader at `ausmt-box:8445` — so
what the box serves there IS what the public will get. Verify the corpus is content-clean on that
tailnet-served copy, specifically that the capricorn-2010 `lead_investigator` citation-metadata fix is
live:
```sh
# from a tailnet device (or the VPS): hit the box reader copy directly — no DNS, no public cert needed
curl -s http://ausmt-box:8445/data/catalogue.json | grep -i capricorn     # the survey is served
# open the capricorn-2010 record in the portal (over the tailnet) and confirm the lead_investigator
# citation is correct in what is actually served
```
Optionally exercise the full front-door path before DNS by overriding the public name to the VPS IP for
one request (the public cert cannot issue yet, so `-k` accepts the temporary self-signed cert — this is
why it is only a supplementary check, not the gate):
```sh
curl -sk --resolve ausmt.auscope.org.au:443:<VPS_PUBLIC_IP> https://ausmt.auscope.org.au/data/catalogue.json | grep -i capricorn
```
**If the fix is not visibly served, STOP** — rebuild/serve the corrected corpus on the box (step 1) and
re-run this gate. Do NOT create the DNS record until this passes: the record invariant is content-clean
BEFORE DNS cutover, not after.

---

## 8. Create the DNS record at the registrar

8.1  Every SERVED name needs an **A** record pointing at the VPS public IPv4 (and an **AAAA** if you
     have IPv6). The canonical `ausmt.auscope.org.au` record lives in the AuScope-administered zone
     (verified pointing at the VPS 2026-08-18; ask AuScope IT for any change). The legacy `ausmt.au`
     record, if you keep the redirect, is at your registrar; low TTL (e.g. 300s) for a first cutover
     so a rollback propagates fast.
8.2  Wait for propagation: `dig +short ausmt.auscope.org.au` (and `dig +short ausmt.au` when the
     legacy redirect is kept) returns the VPS IP.

Once DNS resolves to the VPS, Caddy obtains the Let's Encrypt certificates automatically: ONE ACME
issuance per served name, so with the legacy redirect configured watch for TWO obtains. Watch it:
```sh
docker compose -f deploy/frontdoor/compose.yaml logs -f frontdoor    # look for a certificate obtained per name
```

---

## 9. Verification checklist (post-cutover, in order)

The content-clean gate already passed pre-DNS (step 7); these confirm the public path itself.

9.1  **TLS issued + HTTP redirects (canonical name).**
```sh
curl -sSI https://ausmt.auscope.org.au/ | head -1           # expect HTTP/2 200
curl -sSI http://ausmt.auscope.org.au/  | grep -i location  # expect a 301/308 to https://
```

9.2  **Reader + /data served (and still content-clean on the PUBLIC path).**
```sh
curl -sS -o /dev/null -w '%{http_code}\n' https://ausmt.auscope.org.au/                      # 200
curl -sS -o /dev/null -w '%{http_code}\n' https://ausmt.auscope.org.au/data/catalogue.json   # 200
curl -s https://ausmt.auscope.org.au/data/catalogue.json | grep -i capricorn     # re-confirm the fix serves publicly
```

9.2b **Legacy redirect leg (only when AUSMT_LEGACY_REDIRECT_NAME is set).** The legacy name must
     301 (permanent, never 302) to the canonical name with the path AND query preserved, on the
     HTTPS leg itself. The deep-path probe below is the pre-migration schema `$id`, so it also
     proves the old identifier keeps resolving. `./doctor.sh` runs the same 301 check as a gate.
```sh
# the https:// leg 301s with path + query preserved (Location shows both halves):
curl -sSI 'https://ausmt.au/data/mtcat.schema.json?v=1.2' | grep -iE '^(HTTP|location)'
#   expect: HTTP/2 301  and  location: https://ausmt.auscope.org.au/data/mtcat.schema.json?v=1.2
# following the hop lands on the canonical name with a 200:
curl -sS -o /dev/null -w '%{http_code} %{url_effective}\n' -L https://ausmt.au/data/mtcat.schema.json
#   expect: 200 https://ausmt.auscope.org.au/data/mtcat.schema.json
# plain-HTTP legacy traffic takes TWO hops by design (automatic HTTP->HTTPS on the legacy name,
# THEN the permanent 301 to the canonical name) - expected, not a misconfiguration:
curl -sSI http://ausmt.au/ | grep -i location               # hop 1: https://ausmt.au/
```

9.2c **Path-URL contract legs (tier 1, owner ruling 2026-08-18).** The three published shapes must
     each answer a permanent 301 into the portal's hash route on the canonical name. These are the
     PUBLISHED URL contract (`/surveys/<slug>`, `/stations/<ausmt_id>`, `/collections/<id>`), the
     form that goes into emails, talks, papers and programme pages. `./doctor.sh` runs the survey
     leg as a gate (pinned on vulcan-2022).
```sh
curl -sSI https://ausmt.auscope.org.au/surveys/vulcan-2022 | grep -iE '^(HTTP|location)'
#   expect: HTTP/2 301  and  location: https://ausmt.auscope.org.au/#/survey/vulcan-2022
curl -sSI https://ausmt.auscope.org.au/stations/au.vulcan-2022.MBV07 | grep -iE '^(HTTP|location)'
#   expect: HTTP/2 301  and  location: https://ausmt.auscope.org.au/#/station/au.vulcan-2022.MBV07
curl -sSI https://ausmt.auscope.org.au/collections/auslamp | grep -iE '^(HTTP|location)'
#   expect: HTTP/2 301  and  location: https://ausmt.auscope.org.au/#/collection/auslamp
# a query on a path-shaped link is preserved BEFORE the fragment, never eaten:
curl -sSI 'https://ausmt.auscope.org.au/surveys/vulcan-2022?utm=1' | grep -i location
#   expect: location: https://ausmt.auscope.org.au/?utm=1#/survey/vulcan-2022
# a bare prefix (no id) lands on the portal root, not a broken empty-fragment URL:
curl -sSI https://ausmt.auscope.org.au/surveys/ | grep -i location
#   expect: location: https://ausmt.auscope.org.au/
# a LEGACY-name path link takes two hops by design (host 301 with the path preserved, THEN the
# canonical block's fragment mapping) and ends at the hash route:
curl -sS -o /dev/null -w '%{http_code} %{url_effective}\n' -L 'https://ausmt.au/surveys/vulcan-2022'
```

9.3  **Wall checks from OUTSIDE (the public wall).** The public subset must be served; every other
     `/gateway` path (the curator workbench) must refuse.
```sh
# PUBLIC subset -- must be served:
curl -sS -o /dev/null -w '%{http_code}\n' https://ausmt.auscope.org.au/add-survey.html          # expect 200 (public page)
curl -sS -o /dev/null -w '%{http_code}\n' https://ausmt.auscope.org.au/add-survey.html/         # expect 200 (trailing slash)
curl -sS -o /dev/null -w '%{http_code}\n' https://ausmt.auscope.org.au/gateway/healthz          # expect 200 (public, gateway up)
# WALLED -- must refuse (the whole curator/admin workbench, in both slash forms):
curl -sS -o /dev/null -w '%{http_code}\n' https://ausmt.auscope.org.au/gateway                  # expect 404 (bare)
curl -sS -o /dev/null -w '%{http_code}\n' https://ausmt.auscope.org.au/gateway/curator/queue    # expect 404
curl -sS -o /dev/null -w '%{http_code}\n' https://ausmt.auscope.org.au/gateway/curator/         # expect 404
# method-aware: a public route hit with the WRONG verb still refuses:
curl -sS -o /dev/null -w '%{http_code}\n' https://ausmt.auscope.org.au/gateway/submit           # expect 404 (GET is wrong verb)
# a walled path through the LEGACY name 301s (redirect-only block: it never reaches the reader
# wall under the legacy identity; the refusal happens on the canonical name after the hop):
curl -sS -o /dev/null -w '%{http_code}\n' https://ausmt.au/gateway/curator/queue                # expect 301
```
     If a WALLED path returns anything but `404`, or the wrong-verb `/gateway/submit` is served, STOP
     and roll back (section 10): a wall is breached. If a PUBLIC path does not return `200`, the
     contribution flow is down (check the gateway profile is up and both walls are redeployed).

9.4  **Masked logs flowing + the fold picks them up.**
```sh
# on the VPS: a masked line landed (client address truncated, no full IP)
sudo tail -n1 /var/log/caddy/access-frontdoor.json
# on the box: ship once now, then confirm the file arrived where the aggregator reads it
sudo systemctl start ausmt-frontdoor-logs.service
ls -l "$AUSMT_DATA_DIR/logs/caddy/"            # access-frontdoor*.json present
# fold once and confirm the public counts appear in stats.json (the Analytics screen reads it)
sudo systemctl start ausmt-stats.service
```

The bridge is live once step 7 (pre-DNS gate) and 9.1–9.4 all pass.

---

## 9P. The path-URL contract (owner ruling 2026-08-18)

Path-shaped URLs are the PUBLISHED CONTRACT for the portal's three entity kinds:

```
/surveys/<slug>        -> the portal with that survey's view open
/stations/<ausmt_id>   -> the portal with that station's drawer open
/collections/<id>      -> the portal with that collection page open
```

Pre-DOI is the cheapest moment to fix URL shape forever: the shape is what gets published (emails,
talks, papers, programme pages, eventually DOI metadata and RAiD landing links); the machinery
behind it can upgrade without breaking a link.

**Tier 1 (LIVE, this stack):** the canonical site block 301s each shape into the SPA's hash route
(`/surveys/x` -> `/#/survey/x`, likewise station/collection). The redirects are canonical surface:
a legacy-name (`ausmt.au`) request to a path-shaped URL takes **two hops** by design - the legacy
block's host 301 with path and query preserved, then the canonical block's fragment mapping - while
a canonical-name request takes one. A query on a path-shaped link is preserved onto the target
**before the fragment** (`/surveys/x?utm=1` -> `/?utm=1#/survey/x`); a bare `/surveys` or
`/surveys/` (no id) lands on the portal root. The entity id itself rides byte-for-byte (the
mechanism never decodes or re-encodes it). All of it is `permanent` (301): these are contracts, so
`temporary`/302 may never appear. The redirect hop lands in the masked access log (the canonical
block logs); the analytics fold does NOT count it - aggregate_stats.py counts only the `/data/*`
download, visit and API paths plus the `/go/ts/` hand-offs, and admits no 301 in any counted class,
so a path-link visit is counted once, at the SPA boot that follows the hop (pinned in deploy/tests).

**Tier 2 (deferred): real SPA path routes.** The app is served AT the path, the router reads
`location.pathname`, and the pretty URL persists in the address bar instead of collapsing to the
hash form. Purely a portal/router upgrade behind the same shapes: **no published URL changes when
it comes** - the tier-1 redirects simply retire from mapping duty.

**Tier 3 (deferred, DOI time): prerendered per-entity landing pages** at the same paths, giving
each survey/station/collection real crawlable HTML (the build's own caveat names this: real
per-page SEO needs path-based routing + prerender). Again **no published URL changes when it
comes**: the paths stop redirecting and start serving, and every link ever published keeps
resolving.

The id vocabulary behind these URLs is FROZEN in `portal/data/url_registry.json` (every published
survey slug, station ausmt_id and collection id): an id that would move fails the registry check
with instructions to add a redirect entry and a dated registry note instead of renaming silently.

---

## 10. Rollback — withdraw public exposure entirely

Any one of these withdraws exposure; do all three for a full teardown. Order for a fast emergency
pull: DNS first (stops new public traffic), then stack, then ACL.

10.1  **Remove the DNS record** at the registrar (delete the A/AAAA for the public name). With the low
     TTL, public resolution stops within minutes. This alone ends public reachability.
10.2  **Stop the front-door stack** on the VPS:
```sh
docker compose -f deploy/frontdoor/compose.yaml down
```
10.3  **Revoke the ACL fence + tag:** in the Tailscale admin console, remove the two C47 acl rules and
     the `tag:ausmt-frontdoor` tagOwner (and delete/disable the VPS node). The front-door tag can then
     reach nothing.
10.1b **Withdraw the time-series hand-off routes only** (a targeted pull that leaves the site up):
     empty the route table and re-apply. Every `/go/ts/` path then 404s, because the map's `default ""`
     is what refuses an unlisted path - there is no separate switch to forget.
```sh
cd deploy/frontdoor && : > ts-routes.map && ./install-frontdoor.sh   # every /go/ts/ path now 404s
git checkout -- ts-routes.map && ./install-frontdoor.sh              # restore the published routes
```
10.4  **Box-side (optional, fully reverts the box):** stop shipping and withdraw the reader port —
```sh
sudo systemctl disable --now ausmt-frontdoor-logs.timer
sudo tailscale serve --tcp=8445 off
```
     The `:8081` listener may stay (it is loopback-only and harmless) or be removed by reverting the
     C47 portal-image change. Curator/admin access over the tailnet is unaffected throughout.

---

## 11. Boot ordering and the 502 recovery (ops-hardening O2)

**The incident.** After a VPS reboot the Docker daemon (and the `restart: unless-stopped` frontdoor
container) started BEFORE `tailscaled`. Caddy tried to resolve the box's tailnet MagicDNS upstream while
the tailnet resolver did not yet exist, the resolve failed and stuck, and the edge served 502 everywhere
until a manual `docker compose restart frontdoor`.

**The fix (install once).** A systemd drop-in orders the Docker daemon after `tailscaled`, so the
container never starts before the tailnet resolver is present:
```sh
sudo mkdir -p /etc/systemd/system/docker.service.d
sudo cp deploy/frontdoor/docker-after-tailscaled.conf /etc/systemd/system/docker.service.d/
sudo systemctl daemon-reload
systemctl show docker.service -p After | tr ' ' '\n' | grep tailscaled
```
The last line should print `tailscaled.service`, confirming the ordering. This removes the boot RACE at
its root. It does not make tailscaled a hard requirement (a box with no tailnet still boots), and a very
fast boot can still catch a brief resolve window, which is what the manual recovery below covers.

**Manual recovery (any time the edge is stuck on 502 from a dead upstream resolve):**
```sh
docker compose -f deploy/frontdoor/compose.yaml restart frontdoor
```
That one command re-resolves the upstream and clears the stuck state. Confirm with
`curl -sSI https://<public-name>/ | head -1` (expect `HTTP/2 200`) or `./doctor.sh` (section 12).

---

## 12. Doctor commands (ops-hardening O4) - troubleshooting on one screen

Two read-only doctors print one labelled `PASS` / `WARN` / `FAIL` line per check and a final summary,
and exit NON-ZERO if any check FAILs (so either can gate a script or a cron alert; a WARN alone does not
fail the exit). Neither mutates anything.

**On the VPS (the public edge):**
```sh
cd deploy/frontdoor
./doctor.sh
```
Covers: the frontdoor container is up; the RUNNING config matches a fresh render of the repo Caddyfile
(install-frontdoor.sh mounts the RENDERED file, legacy block in or out, so the doctor re-renders the
same way and hashes the container-mounted `/etc/caddy/Caddyfile` against that, catching the O1
stale-config trap and any uncommitted hand-edit); the box reader upstream answers over the tailnet; the
canonical TLS certificate is present with days-to-expiry (WARN inside the renewal window); when
`AUSMT_LEGACY_REDIRECT_NAME` is set, the LEGACY certificate too (missing = FAIL, the redirect contract
is down) plus the explicit HTTPS 301 leg (the legacy name must answer `https://.../data/mtcat.schema.json`
with a 301 to the same path on the canonical name; both legs are skipped cleanly when the var is
unset); the path-URL contract leg (`https://<canonical>/surveys/vulcan-2022` must 301 to
`/#/survey/vulcan-2022`; skipped cleanly if the edge gives no response at all, since the container
check already covers a down edge); the time-series hand-off table (the container-mounted `ts-routes.map`
must hash-match the repo copy, an OPEN route must 302 to the exact NCI `Location` the table names, and a
route the table does NOT name must 404 - set `AUSMT_DOCTOR_TS_WITHHELD_PATH` to a real suppressed
station's route once the corpus has one); tailscale is up and the box peer is visible; the zombie count is under threshold (section 13);
disk headroom; and the public DNS A record still resolves to this host (set `AUSMT_DOCTOR_EXPECT_IP`
to the VPS public IP to verify the target, otherwise that check WARNs). Every external command and
path is overridable by an `AUSMT_DOCTOR_*` env var (see the script header).

**On the box (the builder/server):**
```sh
make -C deploy doctor                 # portal profile
make -C deploy doctor PROFILE=gateway  # also checks the gateway container + healthz
```
Covers: containers up for the active profile; gateway healthz (gateway profile); the box reader wall on
loopback `:8445` serves the public subset (200) and refuses the curator workbench (404); surveys-live is a
clean git checkout, group-writable, with a default group ACL (the recurring perms trap); the
serve-reconcile timer is installed, enabled, and has a recent last-run (its absence is a live suspect when
a publish did not get served); disk headroom; the served build's `source_commit` versus surveys-live
HEAD (a staleness hint that a publish has not been served yet); and the TS-ROUTE KEY-SET PARITY - the
committed `ts-routes.map` and the served `ts_access.json` must name the same (station, level) set, so a
route can never resolve that the data does not publish, or a published route 404. That is the drift this
split-host shape creates: the table lives on the VPS and the data on the box, so a withheld flip is
suppressed only once the table is regenerated, committed and installed.

---

## 13. Zombie-process diagnosis kit (ops-hardening O3)

**The incident.** 1047 zombie (defunct) processes exhausted the VPS process table; a reboot cleared them
but the leaking parent was never identified, so they may re-accumulate. Reaped zombies vanish, so a
nonzero count means some PARENT process is not `wait()`ing for its dead children, and the fix belongs at
that parent.

**Run the kit on the VPS (read-only):**
```sh
cd deploy/frontdoor
./doctor.sh zombies
```
It counts Z-state processes, GROUPS them by parent PID (heaviest first, so the top line NAMES the leaker),
prints each parent's command line, and lists the likely fixes. To inspect one parent's defunct children
directly: `ps --ppid <ppid> -o pid,stat,comm`.

**Likely fixes, matched to the named parent:**
- If the parent is a CONTAINER PID-1 that does not reap (a shell or app running as pid 1 inside a
  container), add `init: true` to that service in the compose file so Docker inserts a reaping init (tini)
  as pid 1. This is the usual front-door / gateway zombie source.
- If the parent is the log-shipping chain (`ship-frontdoor-logs.sh` or an `ssh`/`rsync` it spawned via the
  timer), a wedged transfer can leave defunct children. Check the `ausmt-frontdoor-logs` timer for
  overlapping or stuck runs and bound it with a timeout.
- If the parent is a short-lived cron/timer helper, ensure it `wait()`s for its children or runs under a
  supervisor that reaps.

The default `./doctor.sh` report also carries a zombie count line and WARNs once the count crosses the
threshold (`AUSMT_DOCTOR_ZOMBIE_WARN`, default 50), pointing you back at `./doctor.sh zombies`.
