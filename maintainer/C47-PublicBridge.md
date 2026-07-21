# C47 — Public demo bridge (design record)

Owner directive (2026-07-21): expose the AusMT reader at a public demo name (`ausmt.au`) ahead of the
later institutional migration (`ausmt.auscope.org.au`), **without** exposing the box to the internet
and **without** opening any curator/admin surface. The bridge must be minimal, verifiable, and fully
reversible — this is a demo, not the permanent home.

## D1. Current state (verified 2026-07-21, recon at main @ eec1b3b)

* **The box serves the reader AND the gateway from ONE port.** `deploy/docker/caddy/Caddyfile` `:8080`
  serves the static portal (index/about) + `/data/*` (the reader) AND reverse-proxies `/gateway/*` to
  the gateway container (`Caddyfile:164-166`). The gateway prefix carries the ENTIRE curator/admin
  surface — submission (`/gateway/submit`, `/gateway/status/...`, `/gateway/healthz`) and the whole
  curator workbench `/gateway/curator/*` (login, queue, publish, serve control, passkey enrolment, the
  analytics screen). Confirmed by enumerating the FastAPI routes: every mutation/admin path is under
  `/gateway/*`; the reader is portal-static + `/data/*`.
* **Exposure today is tailnet-only.** `:8080` is published loopback-only (`127.0.0.1:8443:8080`,
  `compose.yaml`) and fronted for tailnet devices by `tailscale serve --bg https / http://127.0.0.1:8443`
  (`deploy/README.md` "Expose to your tailnet"). Nothing binds a hostname — deliberately (config-side
  names only). There is no public port anywhere.
* **Masked access logging already exists at the box edge (C45).** The `:8080` `log` block writes JSON
  with the client address masked at write time (IPv4 /24, IPv6 /48) and every address/credential
  header deleted; the C45 aggregator (`deploy/scripts/aggregate_stats.py`, daily via
  `ausmt-stats.timer` at 03:35 UTC) folds `access*.json` under `$AUSMT_DATA_DIR/logs/caddy` into
  `stats.json`. The aggregator globs `access*.json` (`aggregate_stats.py:449`), so an additional
  masked log file dropped in that dir is folded automatically.
* **A real-Caddy CI harness exists (PR #48 / C45).** `deploy/tests/test_caddy_log_masking.py` extracts
  the shipped log block, runs a real Caddy, and asserts a forwarded IP is truncated on disk;
  `gateway-ci.yml` installs Caddy so it runs (a skip tripwire fails the lane if it silently no-ops).
  This is the pattern C47's runtime pins reuse.

## D2. Topology decision (owner, 2026-07-21) — a VPS front door on the tailnet

**Decision:** public traffic flows `internet → a small Sydney VPS (public IP; DNS A/AAAA at the
registrar) running a public edge Caddy → over the tailnet (WireGuard) → the box's reader upstream`. The
VPS joins the tailnet under a **dedicated ACL tag** permitted to reach **only** the box's reader port.
The box gets **no inbound internet exposure and no firewall change**. Every curator/admin surface stays
tailnet-only exactly as today.

### Rejected alternatives (recorded per the directive)

* **Tailscale Funnel** — no custom-domain certificates. Funnel serves under a `*.ts.net` name only; the
  demo needs `ausmt.au`. Rejected.
* **Direct home port-forward** — exposes the home IP and is fragile behind CGNAT; also puts an internet
  listener on the box itself (the thing we are avoiding). Rejected.
* **Cloudflare in path** — third-party TLS termination, and client IPs arrive as request headers, which
  reopens the C45 masked-logging seam (the true client would arrive unmasked in a forwarded header at
  the point we take the analytics log). Rejected **as the demo path**, but noted as a LATER OPTIONAL
  bolt-on: if put in front, the front-door Caddy would need `trusted_proxies` scoped to Cloudflare's
  ranges and the masked-log filter would then mask the forwarded client — its seam implications
  (header-supplied client IPs, third-party TLS custody) must be documented and pinned before adopting.

## D3. The two walls (the load-bearing security design)

The public name must serve ONLY the reader; every curator/admin surface must be refused. Because the
box serves the reader and the gateway from the **same** port (D1) and a tailnet ACL is **port-granular**,
one control is not enough — a single mis-scoped front-door path rule would otherwise reach the gateway.
So the bridge stands up **two independent walls**:

* **Wall 1 — path refusal at the front door.** The VPS Caddyfile carries explicit `handle /gateway/* {
  respond 404 }` and `handle /add-survey.html { respond 404 }` blocks, ordered before the reader
  reverse-proxy, so a public caller is refused by an intentional deny, never by accidental routing.
* **Wall 2 — a gateway-less box listener behind a port-scoped ACL.** The box gains a small, dedicated
  **reader-only** Caddy listener (`:8081`, published loopback `127.0.0.1:8445`, fronted onto the tailnet
  by `tailscale serve --tcp=8445`). It serves the reader + `/data` and has **no `/gateway/*` route at
  all** (and refuses the non-public classes itself). The tailnet ACL grants `tag:ausmt-frontdoor` reach
  to **`ausmt-box:8445` and nothing else**. Even if the front-door config were mis-scoped, the ACL
  cannot reach the gateway's port and the reader listener has no gateway route to reach.

The reader listener is a deliberate near-duplicate of the `:8080` header/CSP/data/root directives, not
a snippet refactor: the `:8080` block is security-proven and this lane does not touch it. Drift between
the two is caught by a config pin (D6).

## D4. Analytics feed moves to the front door

The masked access log is the C45 analytics feed. Once public traffic terminates at the VPS, the box's
`:8081` reader listener only ever sees the VPS tailnet peer — a useless client address — so it does
**not** log. The **front door** takes the C45 masked log on the real public client, with the same
at-edge guarantees:

* The VPS is the TRUE edge (nothing in front — Cloudflare rejected, D2), so the front-door Caddy sets
  **no `trusted_proxies`**: `client_ip` is the genuine remote peer, which `ip_mask` truncates (/24,
  /48) at write time. A client-sent `X-Forwarded-For` (or `X-Real-IP`/`Forwarded`) is **deleted** so a
  caller cannot smuggle a full address into the log; `Cookie`/`Authorization`/`Set-Cookie`/`Referer`
  are deleted as before. A full IP never touches disk. VPS-side retention: rotated, 7 days
  (`roll_keep_for 168h`) — a short debugging tail.
* The front-door log is written to a **distinct** filename (`access-frontdoor.json`) and **shipped over
  the tailnet to the box** (D5) into `$AUSMT_DATA_DIR/logs/caddy`, where the C45 aggregator's
  `access*.json` glob folds it beside the box's own log — no aggregator change, no new metric.

## D5. Log shipping (box pulls, never push)

A box-side systemd oneshot+timer (`ausmt-frontdoor-logs.{service,timer}`, fires 03:25 UTC — after the
backup, before the 03:35 C45 fold) runs `ship-frontdoor-logs.sh`, an rsync-over-ssh **pull** of
`access-frontdoor*.json` from the VPS into the box log dir. Pull, not push, on purpose: the front-door
tag is granted **no inbound path to the box** (that is wall 2's whole point); the box initiates the
copy instead (`ausmt-box → tag:ausmt-frontdoor:22`), a separate ACL grant that never widens the
front-door tag. Same trust model, script shape, and "no hostname in git" discipline as the existing
off-box backup pull (`pull-backup.sh`). The masking already happened at the edge — the shipper moves
already-masked bytes and never sees a full client IP. The units ship in the front-door subtree
(`deploy/frontdoor/`) though they install on the box, because they are part of this deliverable.

## D6. Invariants

a. **The public name serves ONLY the reader + `/data`, via the front door.** No other route class is
   reachable at the public name.
b. **Every non-public route class is REFUSED at the front door (explicit deny) AND unreachable through
   the ACL fence** — the two walls of D3. A breach requires BOTH walls to fail simultaneously.
c. **The C45 masked logging runs AT THE FRONT DOOR on public traffic**, with the same at-edge masking
   guarantees (client address truncated at write time, address/credential headers deleted). That log
   is the analytics feed.
d. **TLS with automatic certificates for the public name; plain HTTP redirected** to HTTPS.
e. **Rollback withdraws public exposure entirely** — DNS record removal + front-door stack stop + ACL
   revoke — leaving the box's tailnet-only posture exactly as before.
f. **Corpus content-clean before DNS cutover** — the capricorn-2010 `lead_investigator`
   citation-metadata fix is serve-verified FIRST (the runbook's cutover gate, step 8.1), before the
   public name is relied upon.

## D7. Verification pins (failure criteria) — `deploy/tests/test_frontdoor_bridge.py`

Every public/privacy/security property has a **runtime** pin against a real Caddy driving the SHIPPED
directives against a stub upstream (the PR #48 harness pattern), red-proven where it can be made to
fail. Caddy legs run in CI (`gateway-ci.yml` installs Caddy); they skip only on a dev box without
caddy, never in CI, so they cannot silently no-op.

* **Reader served + non-public refused (runtime, i+ii):** a reader request reaches the stub (200);
  `/gateway/*` and `/add-survey.html` refuse at the front door (404) and never reach the stub.
  *Fails if* the reader is not served or a non-public class is proxied through. **Red-proof:** with the
  `/gateway/*` deny removed, the request leaks to the stub (200) — proving the deny is load-bearing.
* **Masked-at-edge on public traffic (runtime, iii):** a request whose peer is masked to `…0` and which
  sends `X-Forwarded-For: 203.0.113.7` yields a log line whose `remote_ip`/`client_ip` fields are the
  /24-masked form and in which the sent XFF appears **nowhere**. *Fails if* the full peer IP or the
  sent XFF survives. **Red-proof:** with the `filter` encoder replaced by a bare `json` encoder, both
  the full peer IP and the XFF leak — proving the filter is what keeps the promise.
* **Box wall-2 (runtime + config, iv):** the shipped `:8081` reader body run under a real Caddy serves
  the reader and REFUSES `/gateway/*`; a config pin asserts the listener has no gateway routing
  directive and no `log` block, and that the compose bind is loopback-only. *Fails if* a gateway route
  or a widened bind appears on the reader listener.
* **Front-door config pins:** the masked-log filter + masks + header-deletes are present; **no**
  `trusted_proxies` directive (the edge must not trust forwarded addresses); the non-public denies are
  explicit 404s; automatic HTTPS is not disabled and HSTS is set (invariant d at config level — live
  cert issuance is verified in the runbook, which needs real DNS + public IP).
* **Log-shipping unit pins:** the service is a oneshot on the operator uid with the
  `__DEPLOY_DIR__`/`__ENV_FILE__` placeholder idiom and a `Documentation=` that resolves to this
  subtree's runbook; the timer is daily, Persistent, and fires strictly **before** the 03:35 fold.
* **Log-shipping argument-shape pins:** driven black-box with an rsync shim, the shipper invokes rsync
  over ssh filtered to the `access-frontdoor*` family, passing the configured remote and dest; a
  missing remote fails loud before any rsync (the real argument shape, not a syntax assertion).

## D8. Rollback

Withdraw public exposure entirely (invariant e), owner-run: **(1)** remove the DNS A/AAAA record at the
registrar (ends public resolution — low TTL for a fast first cutover); **(2)** `docker compose -f
deploy/frontdoor/compose.yaml down` on the VPS (stops the edge); **(3)** revoke the two C47 ACL rules
and the `tag:ausmt-frontdoor` tagOwner in the Tailscale admin (the tag can then reach nothing);
**(4)** optionally box-side, `systemctl disable --now ausmt-frontdoor-logs.timer` and `tailscale serve
--tcp=8445 off`. The `:8081` listener is loopback-only and harmless if left; curator/admin access over
the tailnet is unaffected throughout. Full procedure: `deploy/frontdoor/RUNBOOK.md` §9.

## Provenance

Owner topology decision 2026-07-21 (VPS front door on the tailnet; Funnel / home port-forward /
Cloudflare-in-path rejected, Cloudflare noted as a later optional bolt-on). Recon 2026-07-21 at main @
eec1b3b (Caddyfile `:8080` reader+gateway split, loopback/tailscale-serve exposure, C45 masked log +
aggregator glob, the PR #48 real-Caddy harness — file:line cited in D1). Deliverables: the box-side
reader listener (wall 2), the `deploy/frontdoor/` VPS stack + ACL stanza, the log-shipping units, the
runtime pins (D7), and the owner runbook.
