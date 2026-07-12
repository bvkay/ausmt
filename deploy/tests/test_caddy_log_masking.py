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
    filter parse under the shipped Caddy). FAILS IF the log block is syntactically invalid for the
    installed Caddy version. Skips where caddy is absent (this dev box)."""
    r = subprocess.run(
        ["caddy", "validate", "--adapter", "caddyfile", "--config", str(_CADDYFILE)],
        capture_output=True, text=True)
    assert r.returncode == 0, f"caddy validate rejected the Caddyfile:\n{r.stdout}\n{r.stderr}"
