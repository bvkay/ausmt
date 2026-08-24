# deploy/frontdoor — AusMT public bridge (C47)

The VPS **front door** that exposes the AusMT reader, and the public submission subset, at the public
name. Public traffic enters a small Sydney VPS (public IP), which terminates TLS, takes the masked
access log, allows only the public subset, and reverse-proxies it to the box **over the tailnet**.
The box gets no inbound internet exposure and no firewall change. The curator/admin workbench stays
tailnet-only.

Canonical-name ruling (2026-08-18): the CANONICAL public name is `ausmt.auscope.org.au`
(`AUSMT_PUBLIC_NAME`); the retired `ausmt.au` may be kept as `AUSMT_LEGACY_REDIRECT_NAME`, a
redirect-only site block answering every request with a permanent 301 to the same path and query on
the canonical name. The legacy block carries no proxy, no log (the analytics feed counts a visit
once, on the canonical block) and no headers, and it is TEMPLATED by `install-frontdoor.sh`: with
the legacy var empty the block is rendered out entirely, because an empty `{$VAR}` site address
would be a Caddy parse error. The container mounts the rendered file (`Caddyfile.rendered`,
gitignored), never the tracked template.

Since the 2026-07-24 owner ruling, the **Add Survey contribution flow is public** (an MT user who
clicks Add Survey must reach the page and lodge a survey): the public subset is the reader plus
`GET /add-survey.html`, `POST /gateway/submit`, `POST /gateway/request-key`, `GET /gateway/healthz`,
and `GET /gateway/status/*`. Every other `/gateway` path (the curator workbench) stays refused.

Design record + rationale (topology decision, rejected alternatives, invariants, verification,
rollback): `maintainer/C47-PublicBridge.md`. Step-by-step owner procedure: **`RUNBOOK.md`** in this dir.

## What's here

| File | Runs where | Purpose |
|------|-----------|---------|
| `Caddyfile` | VPS | Public edge TEMPLATE: auto-TLS per served name, HTTP→HTTPS, masked access log (the analytics feed, canonical block only), a method-scoped **allowlist** of the public subset (`GET /add-survey.html`, `POST /gateway/submit`, `POST /gateway/request-key`, `GET /gateway/healthz`, `GET /gateway/status/*`) reverse-proxied to the box, a deny-by-default `404` for every other `/gateway` path in both slash forms (wall 1), and the marker-delimited legacy redirect block (permanent 301 to the canonical name; templated in or out by the installer). |
| `ts-routes.map` | VPS | **GENERATED, COMMITTED** Caddy map source: one line per published `/go/ts/<survey>/<station>/<level>` hand-off route and the NCI `fileServer` path it resolves to. Written by `deploy/scripts/gen_ts_routes.py` from the per-survey verified-resource registers; carries ONLY open-access, `review: verified`, non-level2 rows. Its MEMBERSHIP is the suppression - an unlisted path cannot produce a `Location`, so it `404`s by construction. A survey the generator cannot resolve drops its OWN routes and is recorded as an `# UNRESOLVED` line, so the table is always regenerable: a stale table is a stale access decision. Never hand-edit; regenerate and commit. |
| `compose.yaml` | VPS | The one-service Caddy stack (host networking so it dials the box over the tailnet); mounts `Caddyfile.rendered` and `ts-routes.map`. |
| `.env.example` | VPS | The only place the canonical name, optional legacy redirect name + box upstream live (config-side; `.env` is gitignored). |
| `install-frontdoor.sh` | VPS | Single apply script: render `Caddyfile.rendered` (legacy block in or out on the .env state), validate it against real Caddy, then `compose up -d` (+ in-place reload when already running). |
| `acl-policy.hujson` | Tailscale admin | The exact ACL stanza to paste: the dedicated `tag:ausmt-frontdoor` and the port-granular fence (reader port only) — wall 2. |
| `ship-frontdoor-logs.sh` | **box** | Pulls the masked front-door logs off the VPS over the tailnet into the dir the C45 aggregator reads. |
| `ausmt-frontdoor-logs.{service,timer}` | **box** | systemd oneshot+timer that runs the shipper daily, ahead of the C45 fold. |
| `RUNBOOK.md` | owner | The numbered go-live + verification + rollback procedure. |

## Two independent walls (why the box change exists)

The box serves the reader **and** the whole `/gateway/*` surface (submission plus the entire curator
workbench) on one port (`:8080`). The tailnet ACL is port-granular, so the C47 box change adds a
dedicated `:8081` listener that the VPS reaches on its own tailnet port. That listener is an
**independent allowlist of the same public subset**: it proxies only the four public gateway routes to
the gateway container and serves the reader plus the Add Survey page, refusing every other `/gateway`
path itself. So even if the front-door config were mis-scoped, the ACL cannot reach the `:8080`
workbench port, and the `:8081` listener has no route to the workbench either. The two walls are each an
allowlist of the same subset: the front door (wall 1) and the `:8081` listener behind the port-scoped
ACL (wall 2). A breach needs both to widen at once.

## Verification

Runtime pins live in `deploy/tests/test_frontdoor_bridge.py` (they run the shipped directives against a
real Caddy with stub upstreams: the reader served, the four public gateway routes traversing
frontdoor to reader to a gateway stub end-to-end, every curator class and every wrong-method public
route refused at wall 1 **and** independently at wall 2, public traffic masked, each red-proven against
a deliberately mis-scoped config). They run in CI (`gateway-ci.yml`, which installs Caddy).

`deploy/tests/test_frontdoor_ts_routes.py` does the same for the hand-off routes: it drives the real
generator over a fixture corpus carrying one row of every state, sweeps the generated table for any
trace of a withheld, `pending`, retired or level2 row, and drives the shipped directives against a
real Caddy - a mapped route `302`s to the exact percent-encoded NCI `Location`, a withheld station's
route `404`s, a bare `/go/ts/` `404`s, and a query never reaches the `Location`. Each negative
carries its resolving twin, so a dead matcher cannot pass as a pin.
