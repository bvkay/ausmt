# Owner runbook — AusMT public bridge (C47)

The numbered, self-contained procedure to expose the AusMT reader at the public demo name via a VPS
front door on the tailnet, and to withdraw it again. Design + rationale: `maintainer/C47-PublicBridge.md`.

**You (the owner) run every VPS / DNS / tailnet step personally.** The repo produces the files and this
runbook; nothing here is automated against your infrastructure. Topology in one line:

```
internet ──▶ VPS front door (public TLS, masked log) ──tailnet(WireGuard)──▶ box reader listener :8081
                                                                              (box: no inbound, no fw change)
```

Two independent walls keep every curator/admin surface private: (1) the front door explicitly refuses
`/gateway/*` and `/add-survey.html`; (2) the box reader listener has no gateway route AND the tailnet
ACL lets the VPS reach only the reader port.

---

## 0. Prerequisites

- The box already runs the AusMT stack on the tailnet (per `deploy/README.md`).
- You have Tailscale admin access (to add a tag + ACL rule and mint an auth key).
- You control the registrar DNS for the public demo name (e.g. `ausmt.au`).
- The capricorn-2010 `lead_investigator` citation-metadata fix is merged and built into the corpus
  the box currently serves (its serve-verification is step 8.1 — the cutover gate).

---

## 1. Pull the box-side change and rebuild the portal image

The bridge adds a dedicated **reader-only listener** (`:8081`) to the box's Caddy (the second wall).

1.1  On the box, update the checkout to the branch/release carrying C47 and rebuild + restart the
     portal image so `:8081` is live:
```sh
cd <your ausmt-code checkout>
git pull                                   # or check out the C47 release tag
docker compose build portal                # bake the new Caddyfile into the portal image
mkdir -p "$AUSMT_DATA_DIR/logs/caddy"       # (already exists if C45 logging is on)
docker compose up -d portal
```
1.2  Confirm the reader listener answers locally (loopback publish 127.0.0.1:8445 → container :8081):
```sh
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8445/            # expect 200
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8445/gateway/curator/queue  # expect 404
```
The `404` on `/gateway/*` is wall 2 proving itself: the reader listener has no gateway route.

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
Verify the fence from the VPS **before** deploying anything:
```sh
curl -sS -o /dev/null -w '%{http_code}\n' http://ausmt-box:8445/                       # expect 200 (reader reachable)
curl -sS --max-time 5 -o /dev/null -w '%{http_code}\n' http://ausmt-box:8443/ || echo BLOCKED   # expect BLOCKED/timeout
```
The reader port answers; the full-portal port (8443, which carries `/gateway/*`) is unreachable —
the ACL fence is doing its job.

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
(You can run it once now to test only after the front door is serving — step 8.5.)

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
**Do not create the DNS record yet** — the certificate cannot issue until DNS points at the VPS, but
you want the content check (step 8.1) to gate the cutover. Proceed to step 7.

---

## 7. Create the DNS record at the registrar

7.1  At your registrar, create an **A** record for the public name → the VPS public IPv4 (and an
     **AAAA** → the VPS IPv6 if you have one). Low TTL (e.g. 300s) for the first cutover so a rollback
     propagates fast.
7.2  Wait for propagation: `dig +short ausmt.au` returns the VPS IP.

Once DNS resolves to the VPS, Caddy obtains the Let's Encrypt certificate automatically. Watch it:
```sh
docker compose -f deploy/frontdoor/compose.yaml logs -f frontdoor    # look for a certificate obtained
```

---

## 8. Verification checklist (in order — 8.1 is the cutover gate)

8.1  **Content clean FIRST (the gate).** Before announcing/relying on the public name, confirm the
     corpus is content-clean on the SERVED site — specifically the capricorn-2010 `lead_investigator`
     citation-metadata fix is live in what the reader serves:
```sh
curl -s https://ausmt.au/data/catalogue.json | grep -i capricorn        # the survey is served
# open the capricorn-2010 record in the portal and confirm the lead_investigator citation is correct
```
     If the fix is not visibly served, STOP — rebuild/serve the corrected corpus on the box before
     going further. Do not expose stale citation metadata publicly.

8.2  **TLS issued + HTTP redirects.**
```sh
curl -sSI https://ausmt.au/ | head -1                       # expect HTTP/2 200
curl -sSI http://ausmt.au/  | grep -i location              # expect a 301/308 to https://
```

8.3  **Reader + /data served.**
```sh
curl -sS -o /dev/null -w '%{http_code}\n' https://ausmt.au/                      # 200
curl -sS -o /dev/null -w '%{http_code}\n' https://ausmt.au/data/catalogue.json   # 200
```

8.4  **Refuse checks from OUTSIDE (the public wall).**
```sh
curl -sS -o /dev/null -w '%{http_code}\n' https://ausmt.au/gateway/curator/queue   # expect 404
curl -sS -o /dev/null -w '%{http_code}\n' https://ausmt.au/gateway/healthz          # expect 404
curl -sS -o /dev/null -w '%{http_code}\n' https://ausmt.au/add-survey.html          # expect 404
```
     Every curator/admin/contribution surface must refuse. If any returns 200, STOP and roll back
     (section 9) — a wall is breached.

8.5  **Masked logs flowing + the fold picks them up.**
```sh
# on the VPS: a masked line landed (client address truncated, no full IP)
sudo tail -n1 /var/log/caddy/access-frontdoor.json
# on the box: ship once now, then confirm the file arrived where the aggregator reads it
sudo systemctl start ausmt-frontdoor-logs.service
ls -l "$AUSMT_DATA_DIR/logs/caddy/"            # access-frontdoor*.json present
# fold once and confirm the public counts appear in stats.json (the Analytics screen reads it)
sudo systemctl start ausmt-stats.service
```

The bridge is live once 8.1–8.5 all pass.

---

## 9. Rollback — withdraw public exposure entirely

Any one of these withdraws exposure; do all three for a full teardown. Order for a fast emergency
pull: DNS first (stops new public traffic), then stack, then ACL.

9.1  **Remove the DNS record** at the registrar (delete the A/AAAA for the public name). With the low
     TTL, public resolution stops within minutes. This alone ends public reachability.
9.2  **Stop the front-door stack** on the VPS:
```sh
docker compose -f deploy/frontdoor/compose.yaml down
```
9.3  **Revoke the ACL fence + tag:** in the Tailscale admin console, remove the two C47 acl rules and
     the `tag:ausmt-frontdoor` tagOwner (and delete/disable the VPS node). The front-door tag can then
     reach nothing.
9.4  **Box-side (optional, fully reverts the box):** stop shipping and withdraw the reader port —
```sh
sudo systemctl disable --now ausmt-frontdoor-logs.timer
sudo tailscale serve --tcp=8445 off
```
     The `:8081` listener may stay (it is loopback-only and harmless) or be removed by reverting the
     C47 portal-image change. Curator/admin access over the tailnet is unaffected throughout.
