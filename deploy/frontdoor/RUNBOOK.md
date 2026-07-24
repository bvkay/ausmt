# Owner runbook — AusMT public bridge (C47)

The numbered, self-contained procedure to expose the AusMT reader at the public demo name via a VPS
front door on the tailnet, and to withdraw it again. Design + rationale: `maintainer/C47-PublicBridge.md`.

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
- You control the registrar DNS for the public demo name (e.g. `ausmt.au`).
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

5.1  On the VPS, create a restricted read-only account for the pull and a log dir:
```sh
sudo useradd -m -s /bin/sh caddylog
sudo mkdir -p /var/log/caddy
sudo setfacl -R -m u:caddylog:rX /var/log/caddy    # read-only for the puller (or use group perms)
```
5.2  Put the **box's** SSH public key into `caddylog@ausmt-vps:~/.ssh/authorized_keys` (generate a
     dedicated key on the box if needed). The box connects out to the VPS over the tailnet (allowed by
     the ACL rule from step 3.1).
5.3  On the box, set the remote in `deploy/.env`:
```sh
AUSMT_FRONTDOOR_LOG_REMOTE=caddylog@ausmt-vps:/var/log/caddy
```
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
AUSMT_PUBLIC_NAME=ausmt.au
AUSMT_BOX_READER_UPSTREAM=http://ausmt-box:8445
AUSMT_ACME_EMAIL=you@example.org
```
6.2  Apply (validates the Caddyfile, then brings the one service up):
```sh
cd deploy/frontdoor
./install-frontdoor.sh
```
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
curl -sk --resolve ausmt.au:443:<VPS_PUBLIC_IP> https://ausmt.au/data/catalogue.json | grep -i capricorn
```
**If the fix is not visibly served, STOP** — rebuild/serve the corrected corpus on the box (step 1) and
re-run this gate. Do NOT create the DNS record until this passes: the record invariant is content-clean
BEFORE DNS cutover, not after.

---

## 8. Create the DNS record at the registrar

8.1  At your registrar, create an **A** record for the public name → the VPS public IPv4 (and an
     **AAAA** → the VPS IPv6 if you have one). Low TTL (e.g. 300s) for the first cutover so a rollback
     propagates fast.
8.2  Wait for propagation: `dig +short ausmt.au` returns the VPS IP.

Once DNS resolves to the VPS, Caddy obtains the Let's Encrypt certificate automatically. Watch it:
```sh
docker compose -f deploy/frontdoor/compose.yaml logs -f frontdoor    # look for a certificate obtained
```

---

## 9. Verification checklist (post-cutover, in order)

The content-clean gate already passed pre-DNS (step 7); these confirm the public path itself.

9.1  **TLS issued + HTTP redirects.**
```sh
curl -sSI https://ausmt.au/ | head -1                       # expect HTTP/2 200
curl -sSI http://ausmt.au/  | grep -i location              # expect a 301/308 to https://
```

9.2  **Reader + /data served (and still content-clean on the PUBLIC path).**
```sh
curl -sS -o /dev/null -w '%{http_code}\n' https://ausmt.au/                      # 200
curl -sS -o /dev/null -w '%{http_code}\n' https://ausmt.au/data/catalogue.json   # 200
curl -s https://ausmt.au/data/catalogue.json | grep -i capricorn                 # re-confirm the fix serves publicly
```

9.3  **Wall checks from OUTSIDE (the public wall).** The public subset must be served; every other
     `/gateway` path (the curator workbench) must refuse.
```sh
# PUBLIC subset -- must be served:
curl -sS -o /dev/null -w '%{http_code}\n' https://ausmt.au/add-survey.html          # expect 200 (public page)
curl -sS -o /dev/null -w '%{http_code}\n' https://ausmt.au/add-survey.html/         # expect 200 (trailing slash)
curl -sS -o /dev/null -w '%{http_code}\n' https://ausmt.au/gateway/healthz          # expect 200 (public, gateway up)
# WALLED -- must refuse (the whole curator/admin workbench, in both slash forms):
curl -sS -o /dev/null -w '%{http_code}\n' https://ausmt.au/gateway                  # expect 404 (bare)
curl -sS -o /dev/null -w '%{http_code}\n' https://ausmt.au/gateway/curator/queue    # expect 404
curl -sS -o /dev/null -w '%{http_code}\n' https://ausmt.au/gateway/curator/         # expect 404
# method-aware: a public route hit with the WRONG verb still refuses:
curl -sS -o /dev/null -w '%{http_code}\n' https://ausmt.au/gateway/submit           # expect 404 (GET is wrong verb)
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
10.4  **Box-side (optional, fully reverts the box):** stop shipping and withdraw the reader port —
```sh
sudo systemctl disable --now ausmt-frontdoor-logs.timer
sudo tailscale serve --tcp=8445 off
```
     The `:8081` listener may stay (it is loopback-only and harmless) or be removed by reverting the
     C47 portal-image change. Curator/admin access over the tailnet is unaffected throughout.
