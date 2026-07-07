"""Routing contract (security review #1). The FastAPI routes are registered UNDER /gateway/* and the
upload response emits a /gateway-prefixed status_url, so the Caddy ingress MUST preserve the prefix
(`handle`, not the prefix-stripping `handle_path`). A handle_path there 404s every request through
the production origin while the :8444 debug publish still works — the exact trap that shipped green.

The behavioral end-to-end guard is the gateway-e2e CI job (submits THROUGH Caddy). This file adds
the two local guards: the app's own route table is /gateway/*-prefixed, and the committed Caddyfile
uses a prefix-preserving directive for /gateway/*.
"""
from __future__ import annotations

import re
from pathlib import Path

from gateway.tests.conftest import app_client, run

_CADDYFILE = Path(__file__).resolve().parents[2] / "deploy" / "docker" / "caddy" / "Caddyfile"


def test_app_routes_are_gateway_prefixed(tmp_path):
    # Every non-default route the app serves starts with /gateway (submit/status/healthz). If a
    # future refactor drops the prefix, the Caddy `handle` (no strip) would then double-404 — this
    # pins the app side of the contract.
    async def _body():
        async with app_client(tmp_path) as (_client, app, _gw, _cfg):
            paths = {r.path for r in app.routes if getattr(r, "path", "").startswith("/gateway")}
            assert "/gateway/submit" in paths
            assert "/gateway/healthz" in paths
            assert any(p.startswith("/gateway/status") for p in paths)
    run(_body())


def test_status_url_is_gateway_prefixed(tmp_path):
    # The emitted status_url must carry /gateway so it resolves through the same-origin Caddy route.
    from gateway.tests.conftest import good_package_zip, scanner_clean, submit_zip

    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, _gw, _cfg):
            r = await submit_zip(client, good_package_zip())
            assert r.json()["status_url"].startswith("/gateway/status/")
    run(_body())


def test_caddyfile_preserves_gateway_prefix():
    # The Caddy ingress for /gateway/* MUST preserve the prefix (`handle`), NOT strip it
    # (`handle_path`). proven failing 2026-07-05: the original Caddyfile shipped `handle_path
    # /gateway/*`, which strips /gateway so the app (routes all /gateway/*) 404s every proxied
    # request — caught only because this assertion pins the directive.
    text = _CADDYFILE.read_text(encoding="utf-8")
    # Find the /gateway/* routing block's directive keyword.
    m = re.search(r"^\s*(handle_path|handle)\s+/gateway/\*\s*\{", text, re.MULTILINE)
    assert m is not None, "no /gateway/* routing block found in the Caddyfile"
    assert m.group(1) == "handle", (
        "Caddy must use `handle /gateway/*` (prefix preserved) — `handle_path` strips /gateway and "
        "404s every request the app serves under /gateway/*"
    )
    # And it must reverse-proxy to the gateway service.
    block = text[m.start():text.index("}", m.start())]
    assert "reverse_proxy gateway:8000" in block
