"""The serve-path tuning pins.

The measured defects these pins guard against coming back:

  * the front door spoke HTTP/1.1 to the box reader with default pooling, so the browser's 15
    parallel h2 streams funnelled into a staircase of upstream TTFBs (1.1s / 1.6s / 2.2s steps on
    a cold load). tailscale serve forwards :8445 as a RAW TCP tunnel (RUNBOOK: `--tcp=8445`), so
    h2c passes end to end once both ends agree: the reader listener accepts h2c and every
    front-door proxy to the box dials it through one shared snippet.
  * NO response carried Cache-Control, so browsers fell back to heuristic freshness and a reload
    served EVERYTHING (index.html included) from local cache with zero revalidation: after a
    rebuild swap a returning visitor could keep stale data and stale portal code for hours. The
    policy is explicit now: vendor/ is long-lived (those files change only by deliberate upgrade),
    everything else the portal serves revalidates on every use (no-cache; the etags already
    exist), and the gateway's proxied responses are left alone (FastAPI owns its own headers).
  * gzip-only encoding; core Caddy also ships zstd (brotli needs a plugin build, so zstd is the
    honest second encoding, ~15-20% smaller than gzip on the JSON payloads).

DEPLOY ORDER CONSTRAINT (documented in the RUNBOOK): the box ships first. The front-door snippet
dials h2c with no h1 fallback, so a front door updated before the box reader accepts h2c would
502 the whole site. Box litany (image carries the Caddyfile) THEN install-frontdoor.sh.

Static pins over the committed files plus a composed `caddy validate` over the new snippet, in
the house style of test_frontdoor_bridge (which owns the full bridge compositions).
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_BOX = _REPO / "deploy" / "docker" / "caddy" / "Caddyfile"
_FRONT = _REPO / "deploy" / "frontdoor" / "Caddyfile"
_DOCTOR = _REPO / "deploy" / "frontdoor" / "doctor.sh"

from test_frontdoor_bridge import _brace_match, _site_body  # noqa: E402  (house practice: shared harness helpers)

_CADDY = shutil.which("caddy")


def _box() -> str:
    return _BOX.read_text(encoding="utf-8")


def _front() -> str:
    return _FRONT.read_text(encoding="utf-8")


# ---- box reader: h2c ------------------------------------------------------------------------------

def test_box_reader_listener_accepts_h2c():
    """FAILS IF the :8081 reader listener does not accept h2c. The front-door transport dials h2c
    with no h1 fallback, so losing this line 502s the public site the next time the front door
    deploys. The pin demands a servers block SCOPED to :8081 carrying `protocols h1 h2c` (h1 kept:
    the compose healthcheck and any tailnet-direct curl are plain HTTP/1.1)."""
    m = re.search(r"servers\s+:8081\s*\{([^}]*)\}", _box())
    assert m, "no `servers :8081 { ... }` scoped options block in the box Caddyfile"
    assert re.search(r"protocols\s+h1\s+h2c", m.group(1)), \
        "the :8081 servers block must declare `protocols h1 h2c`"


def test_box_trusted_proxies_survive_the_server_split():
    """FAILS IF splitting the servers options into scoped blocks dropped trusted_proxies from either
    listener. The masking promise depends on client_ip derivation on BOTH listeners; scoped
    blocks do not inherit from an unscoped one, so each must carry the directive itself."""
    text = _box()
    for scope in (":8080", ":8081"):
        m = re.search(r"servers\s+" + re.escape(scope) + r"\s*\{([^}]*)\}", text)
        assert m, f"no scoped `servers {scope}` options block"
        assert "trusted_proxies" in m.group(1), f"servers {scope} lost trusted_proxies in the split"


# ---- both ends: zstd alongside gzip ---------------------------------------------------------------

def test_box_encodes_zstd_on_both_listeners():
    """FAILS IF either box vhost drops back to gzip-only (or loses encode entirely). The openers are
    line-anchored: a bare `:8080` pattern would first match the `servers :8080` options block."""
    text = _box()
    for opener in (r"(?m)^:8080\s*\{", r"(?m)^:8081\s*\{"):
        body = _site_body(text, opener)
        assert re.search(r"encode\s+zstd\s+gzip", body), \
            f"listener {opener} must `encode zstd gzip`"


def test_frontdoor_encodes_zstd():
    """FAILS IF the edge's own responses (redirects, walls, 404s) drop back to gzip-only."""
    assert re.search(r"encode\s+zstd\s+gzip", _front()), "front door must `encode zstd gzip`"


# ---- box reader: the cache policy -----------------------------------------------------------------

def test_box_cache_policy_on_both_listeners():
    """FAILS IF the explicit Cache-Control policy is missing from either vhost. Three-part pin per
    listener: vendor assets long-lived, a no-cache default for everything else the file server
    emits, and the no-cache matcher EXCLUDING /gateway so proxied FastAPI responses keep their own
    headers."""
    text = _box()
    for opener in (r"(?m)^:8080\s*\{", r"(?m)^:8081\s*\{"):
        body = _site_body(text, opener)
        assert re.search(r"path\s+/vendor/\*", body), f"{opener}: no vendor path matcher"
        assert re.search(r"Cache-Control\s+\"public,\s*max-age=2592000\"", body), \
            f"{opener}: vendor assets must carry a long-lived Cache-Control"
        assert re.search(r"Cache-Control\s+\"no-cache\"", body), \
            f"{opener}: the default surface must carry Cache-Control no-cache"
        nc = re.search(r"@revalidate\s*\{([^}]*)\}", body)
        assert nc, f"{opener}: no @revalidate matcher for the no-cache default"
        assert "/gateway" in nc.group(1) and "not" in nc.group(1), \
            f"{opener}: the no-cache matcher must exclude /gateway (FastAPI owns those headers)"
        assert "/vendor" in nc.group(1), \
            f"{opener}: the no-cache matcher must exclude /vendor (long-lived class)"


@pytest.mark.skipif(_CADDY is None, reason="no caddy binary to validate with")
def test_box_caddyfile_validates(tmp_path):
    """FAILS IF the box Caddyfile stops validating (the servers split and header matchers are new
    surface). `caddy validate` PROVISIONS the log writers, so the two /var/log/caddy paths are
    rewritten to a writable tmp dir first; that mechanical rewrite is the only difference from the
    committed file, so parse and provisioning stay genuinely gated."""
    logdir = tmp_path / "log"
    logdir.mkdir()
    rewritten = _box().replace("/var/log/caddy", str(logdir))
    p = tmp_path / "box.caddy"
    p.write_text(rewritten, encoding="utf-8")
    r = subprocess.run([_CADDY, "validate", "--adapter", "caddyfile", "--config", str(p)],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"box Caddyfile invalid:\n{r.stdout}\n{r.stderr}"


# ---- front door: one snippet wraps every box proxy ------------------------------------------------

def test_frontdoor_box_proxies_all_ride_the_snippet():
    """FAILS IF any proxy to the box reader bypasses the shared (box_upstream) snippet, or the
    snippet loses its h2c + keepalive transport. Six sites proxy to the box (five wall-1 allows +
    the catch-all); a bare `reverse_proxy {$AUSMT_BOX_READER_UPSTREAM}` would silently fall back
    to a fresh-connection HTTP/1.1 path and reintroduce the measured staircase."""
    text = _front()
    assert "reverse_proxy {$AUSMT_BOX_READER_UPSTREAM}\n" not in text.replace("\t", ""), \
        "a bare box reverse_proxy remains; every site must `import box_upstream`"
    assert len(re.findall(r"import\s+box_upstream", text)) == 6, \
        "expected exactly 6 `import box_upstream` sites (5 wall-1 allows + the catch-all)"
    m = re.search(r"\(box_upstream\)\s*\{", text)
    assert m, "no (box_upstream) snippet defined"
    snippet = _brace_match(text, text.index("{", m.end() - 1))
    assert re.search(r"versions\s+h2c\s+2", snippet), "snippet transport must pin `versions h2c 2`"
    assert "keepalive" in snippet, "snippet transport must pin keepalive reuse"


@pytest.mark.skipif(_CADDY is None, reason="no caddy binary to validate with")
def test_frontdoor_snippet_validates(tmp_path):
    """FAILS IF the snippet does not parse as real Caddy config. The full front-door file needs
    container mounts (/etc/caddy/ts-routes.map) so it is validated by the CI composer; this pins
    the NEW surface: the snippet text, verbatim from the committed file, composed into a minimal
    site and `caddy validate`d with the upstream env resolved."""
    text = _front()
    m = re.search(r"\(box_upstream\)\s*\{", text)
    assert m, "no (box_upstream) snippet defined"
    snippet = text[m.start():m.start() + len("(box_upstream) ") + len(
        _brace_match(text, text.index("{", m.end() - 1)))]
    cfg = ("{\n\tadmin off\n\tauto_https off\n}\n" + snippet +
           "\n:0 {\n\timport box_upstream\n}\n")
    p = tmp_path / "snippet.caddy"
    p.write_text(cfg, encoding="utf-8")
    import os
    env = dict(os.environ, AUSMT_BOX_READER_UPSTREAM="http://127.0.0.1:9")
    r = subprocess.run([_CADDY, "validate", "--adapter", "caddyfile", "--config", str(p)],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, f"box_upstream snippet invalid:\n{r.stdout}\n{r.stderr}\n---\n{cfg}"


# ---- doctor: the relay tripwire -------------------------------------------------------------------

def test_doctor_has_the_tailnet_path_leg():
    """FAILS IF doctor.sh loses the DERP-relay tripwire. The diagnosis found the VPS-box
    path silently relaying through DERP Sydney (multi-second TTFB outliers, throughput caps); the
    path regressing again must fail the routine doctor run, with the remediation named."""
    text = _DOCTOR.read_text(encoding="utf-8")
    assert "check_tailnet_path" in text, "doctor.sh must define check_tailnet_path"
    assert re.search(r"^\tcheck_tailnet_path", text, re.M), \
        "check_tailnet_path must run in the default report"
    assert "DERP" in text, "the FAIL line must name the DERP relay"
    assert "restart tailscaled" in text, "the FAIL line must carry the remediation"
