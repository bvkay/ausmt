"""The generated survey pages load portal scripts (/src/fetchcmd.js, /src/fetchdialog.js,
/src/page-fetch.js) beside the SPA. Two Caddyfile facts make that safe, and both are pinned here as
config assertions over the committed box Caddyfile (no caddy binary; test_caddy_log_masking runs the
live validate leg):

  * /src/*.js revalidates on every use on BOTH listeners. The @revalidate matcher is the default rule
    and excludes only vendor/, gateway and basemap, so a page that references a portal script never
    keeps a stale copy across a rebuild for longer than one conditional request.
  * the strict CSP the pages are served under keeps script-src 'self' and nothing else: the pages
    carry no inline script (the engine's page test pins that), so no widening is ever needed here.
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_BOX_CADDY = _REPO / "deploy" / "docker" / "caddy" / "Caddyfile"


def _text() -> str:
    return _BOX_CADDY.read_text(encoding="utf-8")


def test_portal_scripts_revalidate_on_both_listeners():
    text = _text()
    blocks = re.findall(r"@revalidate \{(.*?)\n\t\}", text, re.S)
    assert len(blocks) == 2, "one @revalidate rule per listener"
    for block in blocks:
        assert "not path /vendor/*" in block
        assert "/src" not in block, "the portal scripts must stay under the default revalidate rule"
    assert text.count('header @revalidate Cache-Control "no-cache"') == 2
    vendor = re.findall(r"@vendorAssets \{(.*?)\n\t\}", text, re.S)
    assert len(vendor) == 2
    for block in vendor:
        assert "/src" not in block, "the long-lived vendor rule must not reach the portal scripts"


def test_strict_pages_keep_script_src_self_alone():
    text = _text()
    values = re.findall(r'header @strictPages Content-Security-Policy "([^"]*)"', text)
    assert len(values) == 2, "one strict CSP per listener"
    for csp in values:
        directives = {d.strip().split(" ")[0]: d.strip() for d in csp.split(";") if d.strip()}
        assert directives.get("script-src") == "script-src 'self'", \
            f"the strict CSP must keep script-src 'self' and nothing else, got {directives.get('script-src')!r}"
