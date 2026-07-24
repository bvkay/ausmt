# deploy/frontdoor — AusMT public bridge (C47)

The VPS **front door** that exposes the AusMT reader, and the public submission subset, at the public
demo name. Public traffic enters a small Sydney VPS (public IP, DNS at the registrar), which terminates
TLS, takes the masked access log, allows only the public subset, and reverse-proxies it to the box
**over the tailnet**. The box gets no inbound internet exposure and no firewall change. The
curator/admin workbench stays tailnet-only.

Since the 2026-07-24 owner ruling, the **Add Survey contribution flow is public** (an MT user who
clicks Add Survey must reach the page and lodge a survey): the public subset is the reader plus
`GET /add-survey.html`, `POST /gateway/submit`, `POST /gateway/request-key`, `GET /gateway/healthz`,
and `GET /gateway/status/*`. Every other `/gateway` path (the curator workbench) stays refused.

Design record + rationale (topology decision, rejected alternatives, invariants, verification,
rollback): `maintainer/C47-PublicBridge.md`. Step-by-step owner procedure: **`RUNBOOK.md`** in this dir.

## What's here

| File | Runs where | Purpose |
|------|-----------|---------|
| `Caddyfile` | VPS | Public edge: auto-TLS for the demo name, HTTP→HTTPS, masked access log (the analytics feed), a method-scoped **allowlist** of the public subset (`GET /add-survey.html`, `POST /gateway/submit`, `POST /gateway/request-key`, `GET /gateway/healthz`, `GET /gateway/status/*`) reverse-proxied to the box, and a deny-by-default `404` for every other `/gateway` path in both slash forms (wall 1). |
| `compose.yaml` | VPS | The one-service Caddy stack (host networking so it dials the box over the tailnet). |
| `.env.example` | VPS | The only place the public name + box upstream live (config-side; `.env` is gitignored). |
| `install-frontdoor.sh` | VPS | Single apply script: validate the Caddyfile against real Caddy, then `compose up -d`. |
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
