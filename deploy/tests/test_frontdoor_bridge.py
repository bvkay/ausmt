"""C47 public bridge — front-door + box-side two-walls pins + log-shipping pins.

The bridge fronts the PUBLIC demo name from a VPS edge (deploy/frontdoor/) and proxies the reader — and,
since the 2026-07-24 owner ruling, the PUBLIC submission subset — to the box's dedicated public-subset
listener over the tailnet. The Add Survey contribution flow is public (an MT user who clicks Add Survey
must reach the page and lodge a survey); the curator/admin workbench stays refused. The load-bearing
properties are public (privacy) and security properties, so — per the standing rule — each is proven
with a RUNTIME pin against a REAL Caddy driving the SHIPPED directives (the PR #48 real-caddy harness
pattern), not a config-syntax assertion alone. Where a property can be made to FAIL, a red-proof
composes a deliberately mis-scoped config and asserts the pin catches it.

THE PUBLIC SUBSET (both walls are INDEPENDENT allowlists of exactly this set — read gateway/app.py):
  * GET  /add-survey.html (+ trailing slash) — the contribution page (served by the box reader).
  * POST /gateway/submit          — the direct-upload endpoint.
  * POST /gateway/request-key     — self-serve email key issuance.
  * GET  /gateway/healthz         — the liveness probe the page uses to reveal the Submit button.
  * GET  /gateway/status/*        — the capability-token submission-status page.
Every OTHER /gateway path (the entire curator/admin workbench) and any wrong-method hit on a public
route is refused — at wall 1 (front door) AND, independently, at wall 2 (the box listener behind the
port-scoped ACL). A breach needs BOTH walls to widen simultaneously.

Runtime legs run a real Caddy against stub upstreams (C47 deliverable 4):
  (i)    the public reader path-space reaches the box reader (a request reaches the reader stub);
  (ii)   the four public GATEWAY routes traverse frontdoor -> reader -> a GATEWAY stub end-to-end, and
         GET /add-survey.html is served by the reader — method-scoped, red-proven;
  (iii)  every non-public route class (and every wrong-method public route) REFUSES at wall 1 (404,
         never reaching the upstream) AND, independently, at wall 2 — red-proven both ways;
  (iv)   the masked access log applies to public-vhost traffic (peer /24-masked, sent XFF deleted) —
         red-proven against an unfiltered log block;
  (v)    /data carries CORS through the bridge, scoped to the /data handler.

Caddy legs skip where no caddy binary is on PATH (this dev box); CI installs caddy (gateway-ci.yml),
so they RUN there and never trip the skip tripwire — same gating as test_caddy_log_masking.py.
"""
from __future__ import annotations

import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_FRONTDOOR = _REPO / "deploy" / "frontdoor"
_FD_CADDY = _FRONTDOOR / "Caddyfile"
_BOX_CADDY = _REPO / "deploy" / "docker" / "caddy" / "Caddyfile"
_SHIP = _FRONTDOOR / "ship-frontdoor-logs.sh"
_SVC = _FRONTDOOR / "ausmt-frontdoor-logs.service"
_TIMER = _FRONTDOOR / "ausmt-frontdoor-logs.timer"
_DEPLOY_DIR = _REPO / "deploy"

_HAS_CADDY = shutil.which("caddy") is not None
_SH = shutil.which("sh") or shutil.which("bash")

# Representative NON-PUBLIC route classes enumerated from gateway/app.py: the bare /gateway, a curator
# GET page, a curator POST, a curator external-script asset, and a curator deep path — none may traverse
# either wall. (GET-form probes; the POST-only classes still 404 as a GET here, which is all we assert.)
_CURATOR_CLASSES = (
    "/gateway",
    "/gateway/curator/queue",
    "/gateway/curator/uploaders",
    "/gateway/curator/serve-state.js",
    "/gateway/curator/serve/build/deadbeef",
)
# The four public gateway routes hit with the WRONG verb — each must refuse (method-aware), (method,path).
_WRONG_METHOD_PUBLIC = (
    ("GET", "/gateway/submit"),
    ("GET", "/gateway/request-key"),
    ("POST", "/gateway/healthz"),
    ("POST", "/gateway/status/tok"),
)


# ==================================================================================================
# Helpers
# ==================================================================================================
def _fd_text() -> str:
    return _FD_CADDY.read_text(encoding="utf-8")


def _brace_match(text: str, open_at: int) -> str:
    """Return text[open_at .. matching close] inclusive, from the '{' at/after open_at."""
    i = text.index("{", open_at)
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
    raise AssertionError("unbalanced braces")


def _site_body(caddy_text: str, opener_re: str) -> str:
    """The INNER body (without the outer braces) of the site whose opener matches opener_re. The opener
    regex MUST end at the site's own opening brace, because a `{$ENV}` placeholder in the address line
    also contains braces — we brace-match from the site brace (m.end()-1), not the first '{'."""
    m = re.search(opener_re, caddy_text)
    assert m, f"could not find a site opener matching {opener_re!r}"
    brace_idx = caddy_text.index("{", m.end() - 1)  # the site's own opening brace
    block = _brace_match(caddy_text, brace_idx)
    return block[1:-1]  # strip outer { }


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _wait_port(port: int, timeout: float = 10.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError(f"port {port} never came up")


def _run_caddy(cfg_text: str, td: Path, name: str) -> subprocess.Popen:
    cfgpath = td / f"{name}.caddy"
    cfgpath.write_text(cfg_text, encoding="utf-8")
    v = subprocess.run(["caddy", "validate", "--adapter", "caddyfile", "--config", str(cfgpath)],
                       capture_output=True, text=True)
    assert v.returncode == 0, f"composed {name} config invalid:\n{v.stdout}\n{v.stderr}\n---\n{cfg_text}"
    return subprocess.Popen(["caddy", "run", "--adapter", "caddyfile", "--config", str(cfgpath)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _stub_cfg(port: int, tag: str = "STUB") -> str:
    # A stand-in upstream: echoes the path so a test can prove a request REACHED it. `tag` distinguishes
    # the READER stub (STUB) from the GATEWAY-container stub (GWSTUB) in the end-to-end compositions.
    return ("{\n\tadmin off\n\tauto_https off\n}\n"
            + f":{port} {{\n\trespond \"{tag} {{http.request.uri}}\" 200\n}}\n")


def _frontdoor_cfg(td: Path, listen_port: int, stub_port: int, *,
                   drop_gateway_deny: bool = False, unscope_submit_method: bool = False,
                   unfiltered_log: bool = False) -> tuple[str, Path]:
    """Compose a hermetic front-door config from the SHIPPED site body: rebind to :listen_port with
    auto_https off (no ACME), point the reverse_proxy at the local stub, and write the access log to a
    temp file. Optional mutations power the red-proofs."""
    body = _site_body(_fd_text(), r"\{\$AUSMT_PUBLIC_NAME\} \{")
    logpath = td / "access-frontdoor.json"
    body = re.sub(r"output file \S+", f"output file {logpath.as_posix()}", body)
    body = body.replace("{$AUSMT_BOX_READER_UPSTREAM}", f"127.0.0.1:{stub_port}")
    if drop_gateway_deny:
        # Remove the whole wall-1 deny-by-default: the `@nonpublic path ...` matcher line AND its
        # `handle @nonpublic { respond ... }` block — red-proof for (iii). Both must go together or
        # caddy validate rejects an undefined matcher reference. With it gone, a curator path falls
        # through the allow handles to the reader catch-all and REACHES the stub.
        m = re.search(r"\t@nonpublic path .*\n", body)
        assert m, "expected a `@nonpublic path` deny matcher line to remove"
        body = body[:m.start()] + body[m.end():]
        m2 = re.search(r"\thandle @nonpublic \{", body)
        assert m2, "expected a `handle @nonpublic` deny block to remove"
        bstart = body.index("{", m2.start())
        end = bstart + len(_brace_match(body, bstart))
        body = body[:m2.start()] + body[end:]
    if unscope_submit_method:
        # Drop the `method POST` scope from the @public_gw_submit allow matcher (leaving `path
        # /gateway/submit` any-method) — red-proof for the METHOD scope. A GET /gateway/submit then
        # matches the allow and LEAKS to the stub instead of refusing at the @nonpublic deny.
        body, n = re.subn(r"(@public_gw_submit \{\n)\t\tmethod POST\n", r"\1", body, count=1)
        assert n == 1, "expected the @public_gw_submit `method POST` line to unscope"
    if unfiltered_log:
        # Replace the `format filter { ... }` with a bare `format json` (no ip_mask, no header deletes)
        # — red-proof for (iv).
        m = re.search(r"\tformat filter \{", body)
        assert m, "expected a `format filter` block to replace"
        bstart = body.index("{", m.start())
        end = bstart + len(_brace_match(body, bstart))
        body = body[:m.start()] + "\tformat json" + body[end:]
    cfg = "{\n\tadmin off\n\tauto_https off\n}\n" + f":{listen_port} {{\n{body}\n}}\n"
    return cfg, logpath


def _req(port: int, path: str, *, method: str = "GET", headers: dict | None = None) -> tuple[int, str]:
    data = b"" if method in ("POST", "PUT", "PATCH") else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data,
                                 headers=headers or {}, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=5)
        return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def _get(port: int, path: str, headers: dict | None = None) -> tuple[int, str]:
    return _req(port, path, headers=headers)


def _get_full(port: int, path: str, headers: dict | None = None) -> tuple[int, dict, str]:
    """Like _get but also returns the response headers (case-insensitive dict) — needed to pin the
    CORS Access-Control-Allow-Origin header on /data responses."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers or {})
    try:
        r = urllib.request.urlopen(req, timeout=5)
        return r.status, dict(r.headers), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace")


def _box_reader_cfg(td: Path, port: int, *, gw_stub_port: int | None = None,
                    strip_acao: bool = False, widen_gateway: bool = False) -> str:
    """Compose a hermetic box public-subset-listener config from the SHIPPED :8081 site body: rebind to
    :port with auto_https off, point root/data at temp dirs seeded with a reader page + add-survey.html +
    a /data JSON, and (when gw_stub_port is given) point the four public gateway routes at a local
    GATEWAY stub instead of the unresolvable `gateway:8000`. Optional mutations power the red-proofs."""
    text = _BOX_CADDY.read_text(encoding="utf-8")
    m = re.search(r"^:8081 \{", text, re.MULTILINE)
    assert m, "the box Caddyfile must declare the :8081 public-subset listener"
    body = _brace_match(text, m.start())[1:-1]
    portal, data = td / "portal", td / "data"
    portal.mkdir(exist_ok=True)
    data.mkdir(exist_ok=True)
    (portal / "index.html").write_text("<h1>reader</h1>", encoding="utf-8")
    (portal / "add-survey.html").write_text("<h1>ADD SURVEY PAGE</h1>", encoding="utf-8")
    (data / "catalogue.json").write_text('{"ok":true}', encoding="utf-8")
    body = body.replace("/srv/portal", portal.as_posix()).replace("/srv/data/current", data.as_posix())
    if gw_stub_port is not None:
        body = body.replace("gateway:8000", f"127.0.0.1:{gw_stub_port}")
    if widen_gateway:
        # WIDEN the narrow @public_gw_submit allow to the whole /gateway subtree, any method — red-proof
        # for wall 2's narrow allowlist. A curator path then matches it and LEAKS to the gateway stub,
        # proving the exact-path + method scope is what keeps the workbench off this listener.
        body, n = re.subn(r"\t@public_gw_submit \{\n\t\tmethod POST\n\t\tpath /gateway/submit\n\t\}",
                          "\t@public_gw_submit {\n\t\tpath /gateway/*\n\t}", body, count=1)
        assert n == 1, "expected the @public_gw_submit matcher block to widen"
    if strip_acao:
        # Reproduce the PRE-CHANGE Caddyfile: remove the single /data ACAO header DIRECTIVE line (the
        # scoping comment above it is inert and may remain). red-proof for the CORS pins.
        body, n = re.subn(r'[^\n]*header Access-Control-Allow-Origin "\*"\n', "", body, count=1)
        assert n == 1, "expected exactly one /data ACAO header line to strip for the pre-change export"
    return "{\n\tadmin off\n\tauto_https off\n}\n" + f":{port} {{\n{body}\n}}\n"


def _stop(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


# ==================================================================================================
# Front-door config pins (always run — no caddy needed)
# ==================================================================================================
def test_frontdoor_masked_log_at_the_edge():
    """The front-door access log masks the client address at write time (ip_mask /24 + /48) and deletes
    every address/credential header — the SAME at-edge guarantee as the box C45 block, now the public
    analytics feed (C47 invariant c). FAILS IF the mask or any header-delete is missing."""
    body = _site_body(_fd_text(), r"\{\$AUSMT_PUBLIC_NAME\} \{")
    log = _brace_match(body, body.index("\tlog {"))
    assert re.search(r"request>remote_ip\s+ip_mask", log), "remote_ip must be ip_mask'd at the edge"
    assert re.search(r"request>client_ip\s+ip_mask", log), "client_ip must be ip_mask'd at the edge"
    assert re.search(r"ipv4\s+24", log) and re.search(r"ipv6\s+48", log), "masks must be /24 and /48"
    for hdr in ("Cookie", "Authorization", "Set-Cookie", "X-Forwarded-For", "X-Real-IP", "Forwarded", "Referer"):
        assert re.search(rf"request>headers>{re.escape(hdr)}\s+delete", log), f"{hdr} must be deleted"
    assert re.search(r"roll_keep_for\s+168h", log), "VPS-side retention must be 7 days (roll_keep_for 168h)"
    assert "access-frontdoor.json" in log, "the log file must be the distinct access-frontdoor.json name"


def test_frontdoor_does_not_trust_forwarded_addresses():
    """The VPS is the TRUE edge (no proxy in front — Cloudflare was rejected), so it must NOT set
    trusted_proxies: honouring a client X-Forwarded-For would let a caller spoof the logged client_ip.
    FAILS IF a trusted_proxies directive appears (defeating the masked-at-edge promise)."""
    text = _fd_text()
    # The DIRECTIVE (not a mention in a comment): a line beginning with optional tabs then the keyword.
    assert not re.search(r"^\s*trusted_proxies\b", text, re.MULTILINE), \
        "the front door must NOT trust forwarded addresses (it is the true edge; XFF would be spoofable)"


def test_frontdoor_allows_only_the_public_subset_explicitly():
    """WALL 1 (config level): the front door is an ALLOWLIST of exactly the five public entry points,
    each METHOD-SCOPED, with a deny-by-default `@nonpublic` 404 for everything else under /gateway (both
    slash forms) and non-GET add-survey. FAILS IF a public route's method scope is missing, an extra
    gateway route is allowed, the deny is not self-complete in both slash forms, or it is not a 404."""
    body = _site_body(_fd_text(), r"\{\$AUSMT_PUBLIC_NAME\} \{")

    def _matcher(name: str) -> str:
        return _brace_match(body, body.index(f"\t@{name} {{"))

    # The five public allow matchers exist, each scoped to the SHIPPED verb + path (read gateway/app.py).
    assert re.search(r"method GET", _matcher("public_add_survey")) and \
        re.search(r"path /add-survey\.html /add-survey\.html/", _matcher("public_add_survey")), \
        "add-survey.html must be a GET-only allow in both slash forms"
    assert re.search(r"method POST", _matcher("public_gw_submit")) and \
        re.search(r"path /gateway/submit\b", _matcher("public_gw_submit")), "submit must be POST-only"
    assert re.search(r"method POST", _matcher("public_gw_request_key")) and \
        re.search(r"path /gateway/request-key\b", _matcher("public_gw_request_key")), \
        "request-key must be POST-only"
    assert re.search(r"method GET", _matcher("public_gw_healthz")) and \
        re.search(r"path /gateway/healthz\b", _matcher("public_gw_healthz")), "healthz must be GET-only"
    assert re.search(r"method GET", _matcher("public_gw_status")) and \
        re.search(r"path /gateway/status/\*", _matcher("public_gw_status")), "status must be GET-only"

    # No OTHER gateway route is allowed: the only /gateway paths in an allow matcher are the four public
    # routes. Any `/gateway/curator` in an allow matcher would be a breach.
    for name in ("public_add_survey", "public_gw_submit", "public_gw_request_key",
                 "public_gw_healthz", "public_gw_status"):
        assert "/gateway/curator" not in _matcher(name), f"@{name} must not allow a curator path"

    # Deny-by-default is self-complete in both slash forms and is an explicit 404.
    m = re.search(r"@nonpublic path (.+)", body)
    assert m, "wall 1 must carry a `@nonpublic path` deny matcher"
    classes = m.group(1).split()
    for cls in ("/gateway", "/gateway/*", "/add-survey.html", "/add-survey.html/"):
        assert cls in classes, f"the deny matcher must be self-complete: {cls!r} missing; got {classes}"
    handle = _brace_match(body, body.index("\thandle @nonpublic {"))
    assert re.search(r"respond\b.*\b404", handle), "the @nonpublic handle must explicitly respond 404"
    assert "reverse_proxy {$AUSMT_BOX_READER_UPSTREAM}" in body, \
        "the reader must proxy to the box upstream env placeholder"


def test_frontdoor_tls_and_hsts_configured():
    """C47 invariant d (config level): the public name drives automatic HTTPS (a hostname site address,
    NO `auto_https off`) so a certificate issues and plain HTTP redirects; and HSTS is set once TLS is
    in force. The live cert issuance is verified in the owner runbook (needs real DNS + public IP).
    FAILS IF auto_https is disabled or HSTS is absent."""
    text = _fd_text()
    assert "{$AUSMT_PUBLIC_NAME}" in text, "the site address must be the public-name placeholder"
    # No ACTIVE `auto_https off` DIRECTIVE (a comment mentioning it is fine — the header comment warns
    # against adding one). A directive is a line whose first non-whitespace token is the keyword.
    assert not re.search(r"^\s*auto_https\s+off\b", text, re.MULTILINE), \
        "automatic HTTPS (cert + HTTP->HTTPS redirect) must stay ON — no active `auto_https off` directive"
    assert re.search(r"Strict-Transport-Security", text), "HSTS must be set (public TLS is in force)"


# ==================================================================================================
# Box-side wall-2 config pins (always run)
# ==================================================================================================
def test_box_reader_listener_allows_only_the_public_gateway_subset():
    """WALL 2 (config level): the box's :8081 listener is an INDEPENDENT allowlist of the SAME subset —
    it proxies ONLY the four public gateway routes to the gateway container (a narrow passthrough, NOT
    :8080's blanket `handle /gateway/*`), refuses every other /gateway path with an explicit 404, and
    serves the reader + /data + add-survey.html. FAILS IF a blanket gateway route leaks in, a public
    route loses its method scope, the deny is absent, or a reader/data/root/CSP directive is missing."""
    text = _BOX_CADDY.read_text(encoding="utf-8")
    m = re.search(r"^:8081 \{", text, re.MULTILINE)
    assert m, "the box Caddyfile must declare the :8081 public-subset listener (C47 wall 2)"
    block = _brace_match(text, m.start())

    # NO blanket gateway routing directive — only the four narrow, method-scoped public matchers proxy.
    # A `handle /gateway/*` (or `/gateway/curator`) reverse-proxy would breach wall 2.
    assert not re.search(r"^\s*handle\s+/gateway", block, re.MULTILINE), \
        "the listener must carry no blanket /gateway routing directive (only the narrow public routes)"
    assert "reverse_proxy gateway:8000" in block, \
        "the four public routes must proxy to the gateway container"

    def _matcher(name: str) -> str:
        return _brace_match(block, block.index(f"@{name} {{"))

    for name, verb, path in (("public_gw_submit", "POST", r"/gateway/submit\b"),
                             ("public_gw_request_key", "POST", r"/gateway/request-key\b"),
                             ("public_gw_healthz", "GET", r"/gateway/healthz\b"),
                             ("public_gw_status", "GET", r"/gateway/status/\*")):
        mb = _matcher(name)
        assert re.search(rf"method {verb}", mb) and re.search(rf"path {path}", mb), \
            f"@{name} must be {verb}-scoped on its exact path"
        assert "/gateway/curator" not in mb, f"@{name} must not allow a curator path"

    # Deny-by-default for every OTHER gateway path (both slash forms) + non-GET add-survey.
    dm = re.search(r"@nonpublic_gateway path (.+)", block)
    assert dm, "the listener must explicitly refuse the non-public gateway classes (self-standing wall)"
    for cls in ("/gateway", "/gateway/*"):
        assert cls in dm.group(1).split(), f"the gateway deny must be self-complete: {cls!r} missing"
    add_deny = _brace_match(block, block.index("@nonpublic_add_survey {"))
    assert "not method GET" in add_deny and "/add-survey.html" in add_deny, \
        "a non-GET /add-survey.html must be refused (GET falls through to file_server)"

    assert "handle_path /data/*" in block, "the listener must serve /data"
    assert "root * /srv/portal" in block, "the listener must serve the static portal (the reader)"
    assert "Content-Security-Policy" in block, "the listener must carry the portal CSP"
    # No `log` block on the listener — the masked log runs at the front door (invariant c).
    assert "\n\tlog {" not in block, "the listener must NOT log (the masked log is at the front door)"


def test_box_compose_publishes_reader_listener_loopback_only():
    """The :8081 listener is published LOOPBACK ONLY (127.0.0.1:8445:8081), fronted onto the tailnet by
    tailscale serve — never a bare/0.0.0.0 port. FAILS IF the bind widens beyond loopback."""
    compose = (_REPO / "deploy" / "compose.yaml").read_text(encoding="utf-8")
    assert re.search(r'"127\.0\.0\.1:8445:8081"', compose), \
        "the reader listener must be published loopback-only at 127.0.0.1:8445:8081"


# ==================================================================================================
# Runtime pins — real Caddy against stub upstreams (C47 deliverable 4)
# ==================================================================================================
@pytest.mark.skipif(not _HAS_CADDY, reason="no caddy binary on PATH — runtime pins run in CI (gateway-ci)")
def test_public_subset_traverses_frontdoor_reader_gateway_end_to_end():
    """(i)+(ii) RUNTIME, the whole bridge. frontdoor -> SHIPPED :8081 reader -> a GATEWAY stub: each of
    the four public gateway routes reaches the GATEWAY stub (200, echoed path) with its correct verb, and
    GET /add-survey.html is served by the reader's file_server (200). A general reader path also reaches
    the reader. FAILS IF any public route does not traverse end-to-end, or add-survey.html is not served."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        gw_port, box_port, fd_port = _free_port(), _free_port(), _free_port()
        gw = _run_caddy(_stub_cfg(gw_port, tag="GWSTUB"), td, "gwstub")
        box = _run_caddy(_box_reader_cfg(td, box_port, gw_stub_port=gw_port), td, "box-reader")
        cfg, _log = _frontdoor_cfg(td, fd_port, box_port)
        fd = _run_caddy(cfg, td, "frontdoor")
        try:
            _wait_port(gw_port); _wait_port(box_port); _wait_port(fd_port)
            # (i) a general reader path traverses to the reader (its file_server 404s a missing file —
            # proving it is reader static, not a gateway proxy).
            st, _ = _get(fd_port, "/some/reader/path")
            assert st in (200, 404), f"a reader path must be served by the reader, got {st}"
            # (ii) GET /add-survey.html served by the reader.
            st, body = _get(fd_port, "/add-survey.html")
            assert st == 200 and "ADD SURVEY PAGE" in body, f"add-survey.html not served: {st} {body!r}"
            # (ii) the four public gateway routes traverse end-to-end to the GATEWAY stub, each verb-correct.
            for method, path in (("POST", "/gateway/submit"), ("POST", "/gateway/request-key"),
                                 ("GET", "/gateway/healthz"), ("GET", "/gateway/status/abc123")):
                st, body = _req(fd_port, path, method=method)
                assert st == 200 and f"GWSTUB {path}" in body, \
                    f"{method} {path} must reach the gateway stub end-to-end, got {st} {body!r}"
        finally:
            _stop(fd); _stop(box); _stop(gw)


@pytest.mark.skipif(not _HAS_CADDY, reason="no caddy binary on PATH — runtime pins run in CI (gateway-ci)")
def test_wall1_refuses_nonpublic_independently_at_runtime():
    """(iii) RUNTIME, WALL 1 in isolation. The front door reverse-proxies to a FULLY PERMISSIVE echo
    stub (standing in for a box that would serve ANYTHING — i.e. wall 2 effectively removed), so any
    request that slips past wall 1 REACHES the stub. Every curator/admin class AND every wrong-method
    public route must still refuse at the front door (404, STUB never seen) — wall 1 holds on its own.
    FAILS IF any non-public request reaches the stub."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        stub_port, fd_port = _free_port(), _free_port()
        stub = _run_caddy(_stub_cfg(stub_port), td, "permissive-stub")
        cfg, _log = _frontdoor_cfg(td, fd_port, stub_port)
        fd = _run_caddy(cfg, td, "frontdoor")
        try:
            _wait_port(stub_port); _wait_port(fd_port)
            for path in _CURATOR_CLASSES:
                st, body = _get(fd_port, path)
                assert st == 404, f"{path} must refuse at wall 1, got {st}"
                assert "STUB" not in body, f"{path} must NOT reach the upstream through wall 1"
            for method, path in _WRONG_METHOD_PUBLIC + (("POST", "/add-survey.html"),):
                st, body = _req(fd_port, path, method=method)
                assert st == 404, f"{method} {path} (wrong verb) must refuse at wall 1, got {st}"
                assert "STUB" not in body, f"{method} {path} must NOT reach the upstream through wall 1"
            # Both slash forms of the PUBLIC add-survey GET traverse (they are the allowlisted subset).
            for path in ("/add-survey.html", "/add-survey.html/"):
                st, body = _get(fd_port, path)
                assert st == 200 and f"STUB {path}" in body, \
                    f"GET {path} is public and must traverse wall 1, got {st} {body!r}"
        finally:
            _stop(fd); _stop(stub)


@pytest.mark.skipif(not _HAS_CADDY, reason="no caddy binary on PATH — runtime pins run in CI (gateway-ci)")
def test_wall2_refuses_nonpublic_independently_at_runtime():
    """(iii) RUNTIME, WALL 2 in isolation. The SHIPPED :8081 listener run against a GATEWAY stub, with NO
    front door in front (wall 1 absent): the four public routes proxy to the gateway stub, but every
    curator/admin class AND every wrong-method public route refuses (404, GWSTUB never seen) — wall 2
    holds on its own. FAILS IF a non-public request reaches the gateway stub, or a public route does not."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        gw_port, box_port = _free_port(), _free_port()
        gw = _run_caddy(_stub_cfg(gw_port, tag="GWSTUB"), td, "gwstub")
        box = _run_caddy(_box_reader_cfg(td, box_port, gw_stub_port=gw_port), td, "box-reader")
        try:
            _wait_port(gw_port); _wait_port(box_port)
            # public routes proxy through wall 2 to the gateway stub
            for method, path in (("POST", "/gateway/submit"), ("GET", "/gateway/healthz"),
                                 ("GET", "/gateway/status/xyz")):
                st, body = _req(box_port, path, method=method)
                assert st == 200 and f"GWSTUB {path}" in body, \
                    f"{method} {path} must proxy through wall 2, got {st} {body!r}"
            # curator classes + wrong-method public routes refuse, never reaching the gateway stub
            for path in _CURATOR_CLASSES:
                st, body = _get(box_port, path)
                assert st == 404, f"{path} must refuse at wall 2, got {st}"
                assert "GWSTUB" not in body, f"{path} must NOT reach the gateway through wall 2"
            for method, path in _WRONG_METHOD_PUBLIC:
                st, body = _req(box_port, path, method=method)
                assert st == 404, f"{method} {path} (wrong verb) must refuse at wall 2, got {st}"
                assert "GWSTUB" not in body, f"{method} {path} must NOT reach the gateway through wall 2"
            # add-survey.html served locally by the reader; a non-GET add-survey refuses.
            st, body = _get(box_port, "/add-survey.html")
            assert st == 200 and "ADD SURVEY PAGE" in body, f"add-survey.html must be served, got {st}"
            st, _ = _req(box_port, "/add-survey.html", method="POST")
            assert st == 404, f"a non-GET /add-survey.html must refuse at wall 2, got {st}"
        finally:
            _stop(box); _stop(gw)


@pytest.mark.skipif(not _HAS_CADDY, reason="no caddy binary on PATH — runtime pins run in CI (gateway-ci)")
def test_wall1_deny_redproof():
    """(iii) RED-PROOF, wall 1. With the `@nonpublic` deny-by-default REMOVED from the shipped config, a
    curator path falls through the allow handles to the reader catch-all and REACHES the permissive stub
    (200) — proving the deny is load-bearing, not decoration. FAILS IF removing it does NOT leak."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        stub_port, fd_port = _free_port(), _free_port()
        stub = _run_caddy(_stub_cfg(stub_port), td, "permissive-stub")
        cfg, _log = _frontdoor_cfg(td, fd_port, stub_port, drop_gateway_deny=True)
        fd = _run_caddy(cfg, td, "frontdoor-nodeny")
        try:
            _wait_port(stub_port); _wait_port(fd_port)
            st, body = _get(fd_port, "/gateway/curator/queue")
            assert st == 200 and "STUB /gateway/curator/queue" in body, \
                "red-proof failed: a wall 1 with the deny removed should LEAK a curator path to the stub"
        finally:
            _stop(fd); _stop(stub)


@pytest.mark.skipif(not _HAS_CADDY, reason="no caddy binary on PATH — runtime pins run in CI (gateway-ci)")
def test_wall1_method_scope_redproof():
    """(iii) RED-PROOF, wall 1 method scope. With `method POST` dropped from the @public_gw_submit allow,
    a GET /gateway/submit now matches the allow and LEAKS to the stub (200) instead of refusing at the
    deny — proving the method scope is load-bearing. FAILS IF unscoping the verb does NOT leak."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        stub_port, fd_port = _free_port(), _free_port()
        stub = _run_caddy(_stub_cfg(stub_port), td, "permissive-stub")
        cfg, _log = _frontdoor_cfg(td, fd_port, stub_port, unscope_submit_method=True)
        fd = _run_caddy(cfg, td, "frontdoor-unscoped")
        try:
            _wait_port(stub_port); _wait_port(fd_port)
            st, body = _get(fd_port, "/gateway/submit")
            assert st == 200 and "STUB /gateway/submit" in body, \
                "red-proof failed: an unscoped submit allow should LEAK GET /gateway/submit to the stub"
        finally:
            _stop(fd); _stop(stub)


@pytest.mark.skipif(not _HAS_CADDY, reason="no caddy binary on PATH — runtime pins run in CI (gateway-ci)")
def test_wall2_narrow_scope_redproof():
    """(iii) RED-PROOF, wall 2. With the narrow @public_gw_submit allow WIDENED to the whole /gateway
    subtree (any method), a curator path now matches it and LEAKS to the gateway stub (200) — proving the
    exact-path + method scope is what keeps the workbench off this listener. FAILS IF widening does NOT
    leak (the narrow scope would then prove nothing)."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        gw_port, box_port = _free_port(), _free_port()
        gw = _run_caddy(_stub_cfg(gw_port, tag="GWSTUB"), td, "gwstub")
        box = _run_caddy(_box_reader_cfg(td, box_port, gw_stub_port=gw_port, widen_gateway=True),
                         td, "box-widened")
        try:
            _wait_port(gw_port); _wait_port(box_port)
            st, body = _get(box_port, "/gateway/curator/queue")
            assert st == 200 and "GWSTUB /gateway/curator/queue" in body, \
                "red-proof failed: a widened wall 2 passthrough should LEAK a curator path to the gateway"
        finally:
            _stop(box); _stop(gw)


@pytest.mark.skipif(not _HAS_CADDY, reason="no caddy binary on PATH — runtime pins run in CI (gateway-ci)")
def test_frontdoor_masks_public_traffic_at_runtime():
    """(iv) RUNTIME. A public request whose peer is 127.0.0.1 and which SENDS X-Forwarded-For:
    203.0.113.7 produces a front-door log line in which the peer is /24-masked (127.0.0.0) and the
    sent XFF appears NOWHERE (deleted). FAILS IF the full peer IP or the sent XFF survives in the log.
    This is the public privacy promise applied to the front-door analytics feed."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        stub_port, fd_port = _free_port(), _free_port()
        stub = _run_caddy(_stub_cfg(stub_port), td, "stub")
        cfg, logpath = _frontdoor_cfg(td, fd_port, stub_port)
        fd = _run_caddy(cfg, td, "frontdoor")
        try:
            _wait_port(stub_port); _wait_port(fd_port)
            _get(fd_port, "/", headers={"X-Forwarded-For": "203.0.113.7"})
            for _ in range(50):
                if logpath.is_file() and logpath.stat().st_size > 0:
                    break
                time.sleep(0.1)
            body = logpath.read_text(encoding="utf-8") if logpath.is_file() else ""
            assert body, "the front door wrote no access-log line"
            # The client-sent XFF must be deleted entirely (it appears nowhere).
            assert "203.0.113.7" not in body, f"the client-sent X-Forwarded-For leaked into the log: {body}"
            # The CLIENT-ADDRESS FIELDS must be /24-masked (127.0.0.1 -> 127.0.0.0). We check the fields
            # specifically, not the whole line: the Host header legitimately carries the connect target
            # (an IP here, the public name in production), which is not a client-privacy field.
            assert '"remote_ip":"127.0.0.1"' not in body, f"the full peer IP was not masked: {body}"
            assert '"client_ip":"127.0.0.1"' not in body, f"the full client IP was not masked: {body}"
            assert '"remote_ip":"127.0.0.0"' in body, f"the /24-masked peer IP is not in the log line: {body}"
        finally:
            _stop(fd); _stop(stub)


@pytest.mark.skipif(not _HAS_CADDY, reason="no caddy binary on PATH — runtime pins run in CI (gateway-ci)")
def test_frontdoor_masking_redproof():
    """(iv) RED-PROOF. With the `format filter` (ip_mask + header deletes) replaced by a bare
    `format json`, the SAME request leaks the full peer IP (127.0.0.1) AND the sent XFF (203.0.113.7)
    into the log — proving the masking filter is what keeps the promise, not the JSON encoder. FAILS IF
    an unfiltered log does NOT leak (which would mean the filter proves nothing)."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        stub_port, fd_port = _free_port(), _free_port()
        stub = _run_caddy(_stub_cfg(stub_port), td, "stub")
        cfg, logpath = _frontdoor_cfg(td, fd_port, stub_port, unfiltered_log=True)
        fd = _run_caddy(cfg, td, "frontdoor-unfiltered")
        try:
            _wait_port(stub_port); _wait_port(fd_port)
            _get(fd_port, "/", headers={"X-Forwarded-For": "203.0.113.7"})
            for _ in range(50):
                if logpath.is_file() and logpath.stat().st_size > 0:
                    break
                time.sleep(0.1)
            body = logpath.read_text(encoding="utf-8") if logpath.is_file() else ""
            assert body, "the unfiltered front door wrote no access-log line"
            assert "203.0.113.7" in body and '"remote_ip":"127.0.0.1"' in body, \
                "red-proof failed: an UNFILTERED log should leak both the peer IP and the sent XFF"
        finally:
            _stop(fd); _stop(stub)


# ==================================================================================================
# CORS on public data — runtime pins (feat/api-cors-geojson-honesty)
# ==================================================================================================
def _acao(headers: dict) -> str | None:
    """The Access-Control-Allow-Origin response header value, case-insensitively (urllib's header dict
    is case-insensitive, but be explicit)."""
    for k, v in headers.items():
        if k.lower() == "access-control-allow-origin":
            return v
    return None


@pytest.mark.skipif(not _HAS_CADDY, reason="no caddy binary on PATH — runtime pins run in CI (gateway-ci)")
def test_reader_data_carries_cors_but_gateway_does_not_at_runtime():
    """(a)+(b) RUNTIME. The SHIPPED :8081 listener serves a /data/*.json response WITH
    Access-Control-Allow-Origin: * (public read-only data is world-readable to browser JS), while the
    header is SCOPED to the /data handler only — a /gateway/* request (refused 404) and a non-/data
    reader page do NOT carry it. FAILS IF /data lacks ACAO, or ACAO leaks onto /gateway or a reader
    page (which would prove the header is not scoped to the /data handler)."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        rp = _free_port()
        proc = _run_caddy(_box_reader_cfg(td, rp), td, "reader-cors")
        try:
            _wait_port(rp)
            # (a) /data/*.json carries ACAO: *
            st, hdrs, _ = _get_full(rp, "/data/catalogue.json")
            assert st == 200, f"/data/catalogue.json must be served, got {st}"
            assert _acao(hdrs) == "*", f"/data must carry Access-Control-Allow-Origin: *, got {_acao(hdrs)!r}"
            # (b) /gateway/* (refused) does NOT carry ACAO — the header is scoped to the /data handler.
            st, hdrs, _ = _get_full(rp, "/gateway/curator/queue")
            assert st == 404, f"/gateway/* must refuse, got {st}"
            assert _acao(hdrs) is None, f"/gateway must NOT carry ACAO (scoped to /data), got {_acao(hdrs)!r}"
            # (b, cont.) a non-/data reader page must not carry ACAO either — scoping is to /data ONLY.
            st, hdrs, _ = _get_full(rp, "/index.html")
            assert _acao(hdrs) is None, f"a reader page must NOT carry ACAO (scoped to /data), got {_acao(hdrs)!r}"
        finally:
            _stop(proc)


@pytest.mark.skipif(not _HAS_CADDY, reason="no caddy binary on PATH — runtime pins run in CI (gateway-ci)")
def test_reader_data_cors_redproof():
    """(a) RED-PROOF. With the /data ACAO header STRIPPED from the shipped :8081 body (the PRE-CHANGE
    Caddyfile), /data/catalogue.json no longer carries Access-Control-Allow-Origin — proving the added
    header is what makes the data world-readable, not incidental. FAILS IF the pre-change config still
    carries ACAO (which would mean the pin proves nothing)."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        rp = _free_port()
        proc = _run_caddy(_box_reader_cfg(td, rp, strip_acao=True), td, "reader-nocors")
        try:
            _wait_port(rp)
            st, hdrs, _ = _get_full(rp, "/data/catalogue.json")
            assert st == 200, f"/data/catalogue.json must still be served pre-change, got {st}"
            assert _acao(hdrs) is None, \
                f"red-proof failed: the pre-change config should NOT carry ACAO on /data, got {_acao(hdrs)!r}"
        finally:
            _stop(proc)


@pytest.mark.skipif(not _HAS_CADDY, reason="no caddy binary on PATH — runtime pins run in CI (gateway-ci)")
def test_data_cors_rides_through_the_frontdoor_at_runtime():
    """(c) RUNTIME. Through the FULL front-door composition — the SHIPPED front-door site body reverse-
    proxying to the SHIPPED :8081 listener as its upstream — a public /data/*.json request comes
    back to the PUBLIC side carrying Access-Control-Allow-Origin: *, exactly as the CSP rides through.
    FAILS IF the front-door reverse_proxy strips the upstream's ACAO before it reaches the public client."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        box_port, fd_port = _free_port(), _free_port()
        box = _run_caddy(_box_reader_cfg(td, box_port), td, "box-reader")
        cfg, _log = _frontdoor_cfg(td, fd_port, box_port)
        fd = _run_caddy(cfg, td, "frontdoor-cors")
        try:
            _wait_port(box_port); _wait_port(fd_port)
            st, hdrs, _ = _get_full(fd_port, "/data/catalogue.json")
            assert st == 200, f"/data must be served through the front door, got {st}"
            assert _acao(hdrs) == "*", \
                f"the /data ACAO must ride through the front-door reverse_proxy to the public side, got {_acao(hdrs)!r}"
        finally:
            _stop(fd); _stop(box)


@pytest.mark.skipif(not _HAS_CADDY, reason="no caddy binary on PATH — runtime pins run in CI (gateway-ci)")
def test_data_cors_frontdoor_redproof():
    """(c) RED-PROOF. With the PRE-CHANGE reader upstream (ACAO stripped from the :8081 /data handler)
    behind the SHIPPED front door, the public-side /data response carries NO ACAO — proving the header
    the public client receives originates at the box reader and rides through, not from the front door.
    FAILS IF the public side still shows ACAO with a pre-change upstream (the pin would prove nothing)."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        box_port, fd_port = _free_port(), _free_port()
        box = _run_caddy(_box_reader_cfg(td, box_port, strip_acao=True), td, "box-nocors")
        cfg, _log = _frontdoor_cfg(td, fd_port, box_port)
        fd = _run_caddy(cfg, td, "frontdoor-nocors")
        try:
            _wait_port(box_port); _wait_port(fd_port)
            st, hdrs, _ = _get_full(fd_port, "/data/catalogue.json")
            assert st == 200, f"/data must be served through the front door pre-change, got {st}"
            assert _acao(hdrs) is None, \
                f"red-proof failed: a pre-change upstream should yield NO public-side ACAO, got {_acao(hdrs)!r}"
        finally:
            _stop(fd); _stop(box)


# ==================================================================================================
# Log-shipping systemd units (always run — pure text, like test_systemd_stats_unit)
# ==================================================================================================
def _lines(path: Path, key: str) -> list[str]:
    return [ln.strip()[len(key):] for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip().startswith(key)]


def test_ship_service_is_oneshot_operator_uid_with_placeholder_paths():
    """The shipping service is a Type=oneshot run as a NON-root, non-container operator uid, with the
    __ENV_FILE__/__DEPLOY_DIR__ placeholder idiom, running the ship script. FAILS IF it drops oneshot,
    runs as root/container uid, or hardcodes a path."""
    assert _lines(_SVC, "Type=") == ["oneshot"], "the shipper must be a oneshot"
    users = _lines(_SVC, "User=")
    assert users and users[0] not in ("root", "10001", "10002"), f"must run as the operator uid: {users}"
    assert _lines(_SVC, "EnvironmentFile=") == ["__ENV_FILE__"], "EnvironmentFile must be the placeholder"
    assert _lines(_SVC, "WorkingDirectory=") == ["__DEPLOY_DIR__"]
    execs = _lines(_SVC, "ExecStart=")
    assert execs and "ship-frontdoor-logs.sh" in execs[0], f"ExecStart must run the ship script: {execs}"
    assert "__DEPLOY_DIR__/frontdoor/ship-frontdoor-logs.sh" in execs[0]


def test_ship_service_documentation_resolves_to_the_runbook():
    """Documentation= must resolve (after the install sed fills __DEPLOY_DIR__) to an existing runbook,
    with no unresolved <placeholder> — the backup-unit bug. FAILS IF it carries a literal <...> or
    points at a non-existent file."""
    uris: list[str] = []
    for line in _SVC.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("Documentation="):
            uris.extend(s[len("Documentation="):].split())
    file_uris = [u for u in uris if u.startswith("file://")]
    assert file_uris, f"expected a file:// Documentation= URI; got {uris}"
    for uri in file_uris:
        assert "<" not in uri and ">" not in uri, f"unresolved <placeholder> in Documentation=: {uri!r}"
        resolved = uri[len("file://"):].replace("__DEPLOY_DIR__", _DEPLOY_DIR.as_posix())
        assert Path(resolved).is_file(), f"Documentation= must resolve to a real runbook; {resolved!r} missing"


def test_ship_timer_is_daily_persistent_and_before_the_fold():
    """The timer fires DAILY, is Persistent, and fires BEFORE the C45 fold (03:35) so each day's public
    logs are on the box when the aggregator reads them. FAILS IF it uses a sub-daily interval, drops
    Persistent, or is scheduled at/after 03:35."""
    cal = _lines(_TIMER, "OnCalendar=")
    assert cal and any(c.startswith("*-*-*") for c in cal), f"expected a daily OnCalendar: {cal}"
    assert _lines(_TIMER, "OnUnitActiveSec=") == [], "shipping is daily, not an interval timer"
    assert _lines(_TIMER, "Persistent=") == ["true"], "the timer must be Persistent"
    # Parse HH:MM and assert it is strictly before 03:35 (the ausmt-stats fold time).
    hhmm = None
    for c in cal:
        m = re.search(r"(\d{2}):(\d{2}):\d{2}", c)
        if m:
            hhmm = int(m.group(1)) * 60 + int(m.group(2))
    assert hhmm is not None and hhmm < 3 * 60 + 35, \
        f"the shipper must fire before the 03:35 C45 fold; got {cal}"


# ==================================================================================================
# Log-shipping script — real argument shape (mirrors test_pull_backup_sh, black-box via a shim)
# ==================================================================================================
@pytest.mark.skipif(_SH is None, reason="no POSIX sh/bash to run ship-frontdoor-logs.sh")
def test_ship_invokes_rsync_with_the_frontdoor_filter(tmp_path):
    """The shipper invokes rsync over ssh, copying ONLY the access-frontdoor* family, from the remote
    into the dest dir. Driven black-box with an rsync SHIM that records its argv. FAILS IF: rsync is not
    invoked, the include filter is not the front-door family, ssh is not the transport, or the
    remote/dest are not passed."""
    marker = tmp_path / "rsync.argv"
    shim = tmp_path / "rsync.sh"
    shim.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"" + marker.as_posix() + "\"\n", encoding="utf-8")
    shim.chmod(0o755)
    dest = tmp_path / "logs"
    env = {"PATH": __import__("os").environ["PATH"],
           "AUSMT_FRONTDOOR_LOG_REMOTE": "caddylog@ausmt-vps:/var/log/caddy",
           "AUSMT_FRONTDOOR_LOG_DEST": str(dest),
           "AUSMT_SHIP_RSYNC": f"sh {shim.as_posix()}",
           "AUSMT_SHIP_SSH": "ssh"}
    r = subprocess.run([_SH, str(_SHIP)], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    argv = marker.read_text(encoding="utf-8")
    assert "access-frontdoor*.json" in argv, f"rsync must filter to the front-door log family; argv={argv!r}"
    assert "--exclude=*" in argv or "--exclude" in argv, f"rsync must exclude everything else; argv={argv!r}"
    assert "-e ssh" in argv, f"rsync must tunnel over ssh; argv={argv!r}"
    assert "caddylog@ausmt-vps:/var/log/caddy/" in argv, f"the remote source must be passed; argv={argv!r}"
    assert f"{dest.as_posix()}/" in argv, f"the dest dir must be passed; argv={argv!r}"


@pytest.mark.skipif(_SH is None, reason="no POSIX sh/bash to run ship-frontdoor-logs.sh")
def test_ship_missing_remote_fails_loud(tmp_path):
    """No AUSMT_FRONTDOOR_LOG_REMOTE => rc!=0 with an actionable message BEFORE any rsync. FAILS IF it
    silently succeeds or shells out with an empty remote."""
    import os
    marker = tmp_path / "rsync.argv"
    shim = tmp_path / "rsync.sh"
    shim.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"" + marker.as_posix() + "\"\n", encoding="utf-8")
    shim.chmod(0o755)
    env = {"PATH": os.environ["PATH"],
           "AUSMT_FRONTDOOR_LOG_DEST": str(tmp_path / "logs"),
           "AUSMT_SHIP_RSYNC": f"sh {shim.as_posix()}"}
    r = subprocess.run([_SH, str(_SHIP)], capture_output=True, text=True, env=env)
    assert r.returncode != 0, "a missing remote must fail loudly"
    assert "REMOTE" in r.stderr or "remote" in r.stderr.lower()
    assert not marker.exists(), "must not invoke rsync with no remote configured"
