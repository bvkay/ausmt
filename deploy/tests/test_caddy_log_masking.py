"""C45 D2/D5: access-log masked-at-edge config pin + the portal promise-text consistency pin.

The load-bearing privacy requirement is that the CLIENT ADDRESS IS MASKED AT WRITE TIME so a full IP
never touches disk. The ideal proof is a LIVE Caddy writing a log line whose address field is
truncated (red-then-green vs an unfiltered block). This dev/CI harness has no `caddy` binary, so:

  * the MASKING PIN is a CONFIG ASSERTION over the rendered Caddyfile (the ip_mask filter is present
    on the client-address fields with the /24 + /48 masks) — flagged CONFIG-ONLY;
  * a `caddy validate` leg runs IFF a caddy binary is on PATH (so a syntax slip in the log block reds
    in an environment that has caddy — CI, the box), else it skips;
  * the PROMISE-CONSISTENCY PIN checks the shipped portal/index.html text matches the logging
    behaviour keywords (truncate/mask at the edge, no cookies) and no longer makes the now-false
    absolute "no IPs stored" claim.

The live masked-log-LINE leg (start caddy, hit it, assert the on-disk line is truncated) is UBUNTU/CI
territory and is flagged for the wait-for-greens push block; the config assertion is the everywhere-
runnable guarantee that the masking directive actually ships.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_CADDYFILE = _REPO / "deploy" / "docker" / "caddy" / "Caddyfile"
_INDEX = _REPO / "portal" / "index.html"


def _caddyfile_text() -> str:
    return _CADDYFILE.read_text(encoding="utf-8")


def _log_block() -> str:
    """The text of the top-level `log { ... }` block (brace-matched). Fails the test if absent."""
    text = _caddyfile_text()
    m = re.search(r"\n\tlog \{", text)
    assert m is not None, "the Caddyfile must declare a `log` block for access logging (C45 D5)"
    start = m.start()
    # brace-match from the opening brace
    i = text.index("{", start)
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[start:j + 1]
    raise AssertionError("unbalanced braces in the Caddyfile log block")


def test_access_log_masks_client_address_at_edge():
    """MASKED-AT-EDGE CONFIG PIN (C45 D2). The Caddyfile access log applies Caddy's ip_mask filter to
    the client-address fields with the /24 (IPv4) + /48 (IPv6) masks, so a FULL IP never touches disk.
    FAILS IF the log block omits the mask on remote_ip/client_ip, or the mask widths are wrong
    (config-only in this harness; the caddy-validate leg + CI's live leg cover the runtime)."""
    block = _log_block()
    # ip_mask must be applied to BOTH the direct peer and the resolved client ip.
    assert re.search(r"request>remote_ip\s+ip_mask", block), \
        "remote_ip must be ip_mask'd (a full peer IP must never be logged)"
    assert re.search(r"request>client_ip\s+ip_mask", block), \
        "client_ip must be ip_mask'd (the resolved client IP must never be logged in full)"
    # The masks: IPv4 -> /24, IPv6 -> /48 (record D2).
    assert re.search(r"ipv4\s+24", block), "IPv4 must be masked to /24"
    assert re.search(r"ipv6\s+48", block), "IPv6 must be masked to /48"
    # No cookies / credentials logged (the promise: no cookies, no personal data).
    assert re.search(r"request>headers>Cookie\s+delete", block), "the Cookie header must be deleted"
    assert re.search(r"request>headers>Authorization\s+delete", block), \
        "the Authorization header must be deleted"
    # S1: every header that can carry a FULL client address must be deleted — behind a proxy the real
    # IP arrives unmasked in these, and the masked-at-edge promise would be false otherwise.
    for hdr in ("X-Forwarded-For", "X-Real-IP", "Forwarded", "Referer"):
        assert re.search(rf"request>headers>{re.escape(hdr)}\s+delete", block), \
            f"the {hdr} header must be deleted (it can carry the unmasked client IP/PII)"


def test_trusted_proxies_configured_for_real_client_masking():
    """S1 PIN. Caddy must trust the fronting proxy so `client_ip` is the REAL client (from the
    forwarded address) that ip_mask then masks — not the loopback proxy. The tailscale CGNAT range
    (100.64.0.0/10) must be trusted explicitly (it is NOT in private_ranges). FAILS IF trusted_proxies
    is absent or omits the CGNAT range (then the masked client_ip would be the proxy, and the true IP
    would leak via the now-deleted headers had they not been deleted — defence in depth needs both)."""
    text = _caddyfile_text()
    # Match the trusted_proxies DIRECTIVE line itself (not a mention in a comment) and assert the CGNAT
    # range is ON that line — removing it from the directive (while it survives in a comment) must red.
    m = re.search(r"^\s*trusted_proxies\s+static\s+(.+)$", text, re.MULTILINE)
    assert m, "trusted_proxies must be configured so client_ip is derived from the trusted forwarded address"
    directive_ranges = m.group(1)
    assert "100.64.0.0/10" in directive_ranges, \
        "the tailscale CGNAT range must be in the trusted_proxies directive (not in private_ranges)"


def test_access_log_has_rotation_and_7_day_retention():
    """RETENTION PIN (C45 D2). The log rolls and is retained ~7 days (Caddy's roll options — no
    logrotate/cron). FAILS IF rotation/retention config is absent."""
    block = _log_block()
    assert "output file" in block, "the log must write to a file on the logs volume"
    assert re.search(r"roll_keep_for\s+168h", block), \
        "retention must be 7 days (roll_keep_for 168h) — the raw log is a short debugging tail (D2)"
    assert re.search(r"roll_keep\s+\d+", block), "a bounded roll_keep must cap the number of rolled files"


def test_logs_volume_is_mounted_on_portal():
    """The portal service mounts a host-side logs volume so the access log persists off the container
    (and the later aggregator can read it). FAILS IF the mount is missing."""
    compose = (_REPO / "deploy" / "compose.yaml").read_text(encoding="utf-8")
    assert "/var/log/caddy" in compose, "the portal must mount a host volume at /var/log/caddy"
    assert re.search(r"/logs/caddy:/var/log/caddy", compose), \
        "the logs volume must live under the data root (\\$AUSMT_DATA_DIR/logs/caddy)"


def test_portal_promise_matches_logging_behaviour():
    """PROMISE-CONSISTENCY PIN (C45 D2/D6). The shipped portal/index.html privacy text matches the
    logging behaviour: it states IPs are TRUNCATED/MASKED at the edge, keeps only aggregate counts, and
    no cookies — and it no longer makes the now-FALSE absolute 'no IPs stored' claim. FAILS IF the
    public promise and the implementation diverge (a public commitment must not lie)."""
    text = _INDEX.read_text(encoding="utf-8").lower()
    assert "no ips stored" not in text, \
        "the absolute 'no IPs stored' claim is now false (a masked log line lands) — it must be amended"
    assert "truncate" in text or "mask" in text, "the promise must state IPs are truncated/masked at the edge"
    assert "/24" in text, "the promise should state the /24 truncation (honest specificity)"
    assert "no cookies" in text, "the promise must state no cookies"
    assert "aggregate" in text, "the promise must state only aggregate counts are kept"


@pytest.mark.skipif(shutil.which("caddy") is None,
                    reason="no caddy binary on PATH — masking is config-asserted; caddy validate runs in CI")
def test_caddyfile_validates_with_caddy():
    """LIVE-VALIDATE LEG (ubuntu/CI). `caddy validate` accepts the Caddyfile (the log block + ip_mask
    filter + trusted_proxies parse under the shipped Caddy). FAILS IF any is syntactically invalid for
    the installed Caddy version. Skips where caddy is absent (this dev box)."""
    r = subprocess.run(
        ["caddy", "validate", "--adapter", "caddyfile", "--config", str(_CADDYFILE)],
        capture_output=True, text=True)
    assert r.returncode == 0, f"caddy validate rejected the Caddyfile:\n{r.stdout}\n{r.stderr}"


def _extract_block(text: str, opener: str) -> str:
    """Brace-match a `<opener> {...}` block out of the real Caddyfile (so the runtime pin exercises the
    SHIPPED directives, not a re-typed copy)."""
    m = re.search(re.escape(opener) + r"\s*\{", text)
    assert m, f"could not find {opener!r} block in the Caddyfile"
    i = text.index("{", m.start())
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]         # the {...} including braces
    raise AssertionError("unbalanced braces")


@pytest.mark.skipif(shutil.which("caddy") is None,
                    reason="no caddy binary — the masked-log-line pin is the ubuntu/CI leg (wait-for-greens)")
def test_real_caddy_masks_forwarded_client_ip_in_the_log():
    """S1 HEADLINE — REAL-CADDY RUNTIME PIN (ubuntu/CI, wait-for-greens). A request carrying
    `X-Forwarded-For: 203.0.113.7` through a running Caddy using the SHIPPED log filter + trusted_proxies
    writes a log line in which the full client IP appears NOWHERE — only the /24-masked form 203.0.113.0.
    FAILS IF 203.0.113.7 appears anywhere in the emitted JSON (fields OR headers). This is the property
    the public privacy promise rests on; a config-syntax pin alone is insufficient. Skips without caddy.

    Box smoke equivalent (run on the deployed box):
        curl -s -H 'X-Forwarded-For: 203.0.113.7' http://127.0.0.1:8443/ >/dev/null
        grep -c 203.0.113.7 $AUSMT_DATA_DIR/logs/caddy/access.json   # must be 0
        grep -c 203.0.113.0 $AUSMT_DATA_DIR/logs/caddy/access.json   # must be >= 1
    """
    import socket
    import tempfile
    import time
    import urllib.request

    text = _caddyfile_text()
    log_block = _extract_block(text, "\tlog")          # the shipped log {...}
    servers_block = _extract_block(text, "servers")    # the shipped trusted_proxies {...}

    # A free loopback port.
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()

    with tempfile.TemporaryDirectory() as td:
        logpath = Path(td) / "access.json"
        # Reuse the SHIPPED log block, but point its output at our temp file (swap the /var/log path).
        test_log_block = re.sub(r"output file \S+", f"output file {logpath.as_posix()}", log_block)
        cfg = (
            "{\n\tadmin off\n\tservers " + servers_block + "\n}\n"
            f":{port} {{\n\tlog " + test_log_block + "\n\trespond \"ok\" 200\n}}\n"
        )
        cfgpath = Path(td) / "Caddyfile"
        cfgpath.write_text(cfg, encoding="utf-8")
        # validate first for a clear failure if the composed config is bad
        v = subprocess.run(["caddy", "validate", "--adapter", "caddyfile", "--config", str(cfgpath)],
                           capture_output=True, text=True)
        assert v.returncode == 0, f"composed test Caddyfile invalid:\n{v.stdout}\n{v.stderr}\n---\n{cfg}"
        proc = subprocess.Popen(
            ["caddy", "run", "--adapter", "caddyfile", "--config", str(cfgpath)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            # wait for the port to accept
            for _ in range(100):
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.1)
            req = urllib.request.Request(f"http://127.0.0.1:{port}/",
                                         headers={"X-Forwarded-For": "203.0.113.7"})
            urllib.request.urlopen(req, timeout=5).read()
            # give the file writer a moment to flush the line
            for _ in range(50):
                if logpath.is_file() and logpath.stat().st_size > 0:
                    break
                time.sleep(0.1)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        body = logpath.read_text(encoding="utf-8") if logpath.is_file() else ""
        assert body, "caddy wrote no access-log line"
        assert "203.0.113.7" not in body, f"the FULL client IP leaked into the log line: {body}"
        assert "203.0.113.0" in body, f"the masked /24 client IP is not in the log line: {body}"
