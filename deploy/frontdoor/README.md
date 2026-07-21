# deploy/frontdoor — AusMT public bridge (C47)

The VPS **front door** that exposes the AusMT reader at the public demo name. Public traffic enters a
small Sydney VPS (public IP, DNS at the registrar), which terminates TLS, takes the masked access log,
refuses every non-public route, and reverse-proxies the reader to the box **over the tailnet**. The box
gets no inbound internet exposure and no firewall change. Curator/admin surfaces stay tailnet-only.

Design record + rationale (topology decision, rejected alternatives, invariants, verification,
rollback): `maintainer/C47-PublicBridge.md`. Step-by-step owner procedure: **`RUNBOOK.md`** in this dir.

## What's here

| File | Runs where | Purpose |
|------|-----------|---------|
| `Caddyfile` | VPS | Public edge: auto-TLS for the demo name, HTTP→HTTPS, masked access log (the analytics feed), explicit refusal of the non-public classes in both slash forms — `/gateway`, `/gateway/*`, `/add-survey.html`, `/add-survey.html/` (wall 1, self-complete), reverse-proxy of the reader to the box. |
| `compose.yaml` | VPS | The one-service Caddy stack (host networking so it dials the box over the tailnet). |
| `.env.example` | VPS | The only place the public name + box upstream live (config-side; `.env` is gitignored). |
| `install-frontdoor.sh` | VPS | Single apply script: validate the Caddyfile against real Caddy, then `compose up -d`. |
| `acl-policy.hujson` | Tailscale admin | The exact ACL stanza to paste: the dedicated `tag:ausmt-frontdoor` and the port-granular fence (reader port only) — wall 2. |
| `ship-frontdoor-logs.sh` | **box** | Pulls the masked front-door logs off the VPS over the tailnet into the dir the C45 aggregator reads. |
| `ausmt-frontdoor-logs.{service,timer}` | **box** | systemd oneshot+timer that runs the shipper daily, ahead of the C45 fold. |
| `RUNBOOK.md` | owner | The numbered go-live + verification + rollback procedure. |

## Two independent walls (why the box change exists)

The box serves the reader **and** the `/gateway/*` curator surface on one port (`:8080`). The tailnet
ACL is port-granular, so the C47 box change adds a dedicated reader-only listener (`:8081`, no gateway
route) that the VPS reaches on its own tailnet port. Even if the front-door config were mis-scoped, the
ACL cannot reach a gateway surface and the reader listener has none. Path-refusal at the front door is
the first wall; the gateway-less listener behind the port-scoped ACL is the second.

## Verification

Runtime pins live in `deploy/tests/test_frontdoor_bridge.py` (they run the shipped front-door
directives against a real Caddy + stub upstream: reader served, non-public classes refused, public
traffic masked — each red-proven against a deliberately mis-scoped config). They run in CI
(`gateway-ci.yml`, which installs Caddy).
