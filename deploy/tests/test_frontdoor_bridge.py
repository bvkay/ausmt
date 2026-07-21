"""C47 public bridge — front-door runtime pins + box-side two-walls pins + log-shipping pins.

The bridge fronts the PUBLIC demo name from a VPS edge (deploy/frontdoor/) and proxies the reader to
the box's dedicated reader-only listener over the tailnet. The load-bearing properties are public
(privacy) and security properties, so — per the standing rule — each is proven with a RUNTIME pin
against a REAL Caddy driving the SHIPPED directives (the PR #48 real-caddy harness pattern), not a
config-syntax assertion alone. Where a property can be made to FAIL, a red-proof composes a
deliberately mis-scoped config and asserts the pin catches it.

Runtime legs run a real Caddy against a STUB upstream (C47 deliverable 4):
  (i)   the public vhost serves the reader path-space (a request reaches the stub reader);
  (ii)  the refused route classes (/gateway/*, /add-survey.html) REFUSE at the front door at runtime
        (404, never reach the stub) — red-proven against a config with the deny removed;
  (iii) the masked access log applies to public-vhost traffic (the peer IP is /24-masked and a
        client-sent X-Forwarded-For is deleted) — red-proven against an unfiltered log block;
  (iv)  the box-side reader listener (:8081) serves the reader and has NO /gateway route (wall 2).

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


def _stub_cfg(port: int) -> str:
    # A stand-in reader upstream: echoes the path so a test can prove a request REACHED it.
    return "{\n\tadmin off\n\tauto_https off\n}\n" + f":{port} {{\n\trespond \"STUB {{http.request.uri}}\" 200\n}}\n"


def _frontdoor_cfg(td: Path, listen_port: int, stub_port: int, *,
                   drop_gateway_deny: bool = False, unfiltered_log: bool = False) -> tuple[str, Path]:
    """Compose a hermetic front-door config from the SHIPPED site body: rebind to :listen_port with
    auto_https off (no ACME), point the reverse_proxy at the local stub, and write the access log to a
    temp file. Optional mutations power the red-proofs."""
    body = _site_body(_fd_text(), r"\{\$AUSMT_PUBLIC_NAME\} \{")
    logpath = td / "access-frontdoor.json"
    body = re.sub(r"output file \S+", f"output file {logpath.as_posix()}", body)
    body = body.replace("{$AUSMT_BOX_READER_UPSTREAM}", f"127.0.0.1:{stub_port}")
    if drop_gateway_deny:
        # Remove the `handle /gateway/* { respond ... }` block (the wall-1 deny) — red-proof for (ii).
        m = re.search(r"\thandle /gateway/\* \{", body)
        assert m, "expected a `handle /gateway/*` deny block to remove"
        bstart = body.index("{", m.start())
        end = bstart + len(_brace_match(body, bstart))
        body = body[:m.start()] + body[end:]
    if unfiltered_log:
        # Replace the `format filter { ... }` with a bare `format json` (no ip_mask, no header deletes)
        # — red-proof for (iii).
        m = re.search(r"\tformat filter \{", body)
        assert m, "expected a `format filter` block to replace"
        bstart = body.index("{", m.start())
        end = bstart + len(_brace_match(body, bstart))
        body = body[:m.start()] + "\tformat json" + body[end:]
    cfg = "{\n\tadmin off\n\tauto_https off\n}\n" + f":{listen_port} {{\n{body}\n}}\n"
    return cfg, logpath


def _get(port: int, path: str, headers: dict | None = None) -> tuple[int, str]:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers or {})
    try:
        r = urllib.request.urlopen(req, timeout=5)
        return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def _stop(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


# ==================================================================================================
# Config pins (always run — no caddy needed)
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


def test_frontdoor_refuses_nonpublic_route_classes_explicitly():
    """WALL 1 (config level): the front door carries an EXPLICIT deny (a 404 respond) for /gateway/* and
    /add-survey.html, placed as `handle` blocks so they match before the reader reverse_proxy. FAILS IF
    a deny is missing or is not an explicit refusal."""
    body = _site_body(_fd_text(), r"\{\$AUSMT_PUBLIC_NAME\} \{")
    gw = _brace_match(body, body.index("\thandle /gateway/* {"))
    assert re.search(r"respond\b.*\b404", gw), "/gateway/* must explicitly respond 404"
    add = _brace_match(body, body.index("\thandle /add-survey.html {"))
    assert re.search(r"respond\b.*\b404", add), "/add-survey.html must explicitly respond 404"
    # The reader catch-all proxies to the box upstream placeholder (config-side name, nothing in git).
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
def test_box_reader_listener_has_no_gateway_route():
    """WALL 2 (config level): the box's dedicated reader listener (:8081) serves the reader + /data and
    has NO /gateway route at all, and it refuses the non-public classes itself. FAILS IF a gateway
    reverse_proxy leaks into the reader listener, or the refusal/data/root directives are missing."""
    text = _BOX_CADDY.read_text(encoding="utf-8")
    m = re.search(r"^:8081 \{", text, re.MULTILINE)
    assert m, "the box Caddyfile must declare the :8081 reader-only listener (C47 wall 2)"
    block = _brace_match(text, m.start())
    assert "reverse_proxy gateway" not in block, \
        "the reader listener must NOT reverse_proxy to the gateway — that is the whole point of wall 2"
    # A gateway ROUTING DIRECTIVE (a `handle /gateway...` line), not a comment mentioning one. Comment
    # lines begin with '#', so a real directive is `handle` at the start of the (whitespace-stripped)
    # line — the "NO handle /gateway/* here" comment must NOT trip this.
    assert not re.search(r"^\s*handle\s+/gateway", block, re.MULTILINE), \
        "the reader listener must carry no /gateway routing directive"
    assert re.search(r"@nonpublic path .*?/gateway", block), \
        "the reader listener must explicitly refuse the non-public classes (self-standing wall)"
    assert "handle_path /data/*" in block, "the reader listener must serve /data"
    assert "root * /srv/portal" in block, "the reader listener must serve the static portal (the reader)"
    assert "Content-Security-Policy" in block, "the reader listener must carry the portal CSP"
    # No `log` block on the reader listener — the masked log runs at the front door (invariant c).
    assert "\n\tlog {" not in block, "the reader listener must NOT log (the masked log is at the front door)"


def test_box_compose_publishes_reader_listener_loopback_only():
    """The reader listener is published LOOPBACK ONLY (127.0.0.1:8445:8081), fronted onto the tailnet by
    tailscale serve — never a bare/0.0.0.0 port. FAILS IF the bind widens beyond loopback."""
    compose = (_REPO / "deploy" / "compose.yaml").read_text(encoding="utf-8")
    assert re.search(r'"127\.0\.0\.1:8445:8081"', compose), \
        "the reader listener must be published loopback-only at 127.0.0.1:8445:8081"


# ==================================================================================================
# Runtime pins — real Caddy against a stub upstream (C47 deliverable 4)
# ==================================================================================================
@pytest.mark.skipif(not _HAS_CADDY, reason="no caddy binary on PATH — runtime pins run in CI (gateway-ci)")
def test_frontdoor_serves_reader_and_refuses_gateway_at_runtime():
    """(i)+(ii) RUNTIME. Through a REAL front-door Caddy driving the SHIPPED site body against a stub
    reader: a reader request REACHES the stub (200, echoed path), while /gateway/* and /add-survey.html
    REFUSE at the front door (404) and NEVER reach the stub. FAILS IF the reader is not served, or a
    non-public class is proxied through."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        stub_port, fd_port = _free_port(), _free_port()
        stub = _run_caddy(_stub_cfg(stub_port), td, "stub")
        cfg, _log = _frontdoor_cfg(td, fd_port, stub_port)
        fd = _run_caddy(cfg, td, "frontdoor")
        try:
            _wait_port(stub_port); _wait_port(fd_port)
            # (i) reader served
            st, body = _get(fd_port, "/some/reader/path")
            assert st == 200 and "STUB /some/reader/path" in body, f"reader not served: {st} {body!r}"
            st, body = _get(fd_port, "/data/catalogue.json")
            assert st == 200 and "STUB /data/catalogue.json" in body, f"/data not served: {st} {body!r}"
            # (ii) non-public classes refuse at the front door, never reaching the stub
            st, body = _get(fd_port, "/gateway/curator/queue")
            assert st == 404, f"/gateway/* must refuse at the front door, got {st}"
            assert "STUB" not in body, "/gateway/* must NOT reach the reader stub"
            st, body = _get(fd_port, "/add-survey.html")
            assert st == 404, f"/add-survey.html must refuse at the front door, got {st}"
            assert "STUB" not in body, "/add-survey.html must NOT reach the reader stub"
        finally:
            _stop(fd); _stop(stub)


@pytest.mark.skipif(not _HAS_CADDY, reason="no caddy binary on PATH — runtime pins run in CI (gateway-ci)")
def test_frontdoor_refusal_redproof():
    """(ii) RED-PROOF. With the /gateway/* deny REMOVED from the shipped config, /gateway/* now reaches
    the stub (200) — proving the refusal pin genuinely discriminates (the deny is load-bearing, not
    decoration). FAILS IF removing the deny does NOT change behaviour (which would mean the pin proves
    nothing)."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        stub_port, fd_port = _free_port(), _free_port()
        stub = _run_caddy(_stub_cfg(stub_port), td, "stub")
        cfg, _log = _frontdoor_cfg(td, fd_port, stub_port, drop_gateway_deny=True)
        fd = _run_caddy(cfg, td, "frontdoor-misscoped")
        try:
            _wait_port(stub_port); _wait_port(fd_port)
            st, body = _get(fd_port, "/gateway/curator/queue")
            assert st == 200 and "STUB /gateway/curator/queue" in body, \
                "red-proof failed: a mis-scoped front door should LEAK /gateway/* to the stub"
        finally:
            _stop(fd); _stop(stub)


@pytest.mark.skipif(not _HAS_CADDY, reason="no caddy binary on PATH — runtime pins run in CI (gateway-ci)")
def test_frontdoor_masks_public_traffic_at_runtime():
    """(iii) RUNTIME. A public request whose peer is 127.0.0.1 and which SENDS X-Forwarded-For:
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
    """(iii) RED-PROOF. With the `format filter` (ip_mask + header deletes) replaced by a bare
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


@pytest.mark.skipif(not _HAS_CADDY, reason="no caddy binary on PATH — runtime pins run in CI (gateway-ci)")
def test_box_reader_listener_serves_reader_no_gateway_at_runtime():
    """(iv) RUNTIME (wall 2, box side). The SHIPPED :8081 reader-listener body, run against nothing but
    itself, serves a reader path (its own file_server 404s on a missing file — proving the route is
    reader static, not a gateway proxy) and REFUSES /gateway/* with the explicit 404. The key property:
    a /gateway/* request is REFUSED, never proxied. FAILS IF /gateway/* is anything but a refusal."""
    text = _BOX_CADDY.read_text(encoding="utf-8")
    m = re.search(r"^:8081 \{", text, re.MULTILINE)
    body = _brace_match(text, m.start())[1:-1]
    # Point root/data at an empty temp dir so file_server has a valid (if empty) root; we only assert
    # ROUTING (refuse vs serve), not file contents.
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "portal").mkdir(); (td / "data").mkdir()
        rp = _free_port()
        body2 = body.replace("/srv/portal", (td / "portal").as_posix()).replace(
            "/srv/data/current", (td / "data").as_posix())
        cfg = "{\n\tadmin off\n\tauto_https off\n}\n" + f":{rp} {{\n{body2}\n}}\n"
        proc = _run_caddy(cfg, td, "reader")
        try:
            _wait_port(rp)
            st, _ = _get(rp, "/gateway/curator/queue")
            assert st == 404, f"the reader listener must REFUSE /gateway/*, got {st}"
            st, _ = _get(rp, "/add-survey.html")
            assert st == 404, f"the reader listener must refuse /add-survey.html, got {st}"
            # A reader path resolves through file_server (404 on a missing file is fine — it proves the
            # route is static serving, NOT a gateway proxy that would 502/connect out).
            st, _ = _get(rp, "/index.html")
            assert st in (200, 404), f"a reader path must be served by file_server, got {st}"
        finally:
            _stop(proc)


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
