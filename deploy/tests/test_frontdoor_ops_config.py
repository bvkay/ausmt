"""Ops-hardening config pins (O1 admin socket, O2 boot-ordering drop-in).

Pure text + path resolution over the shipped files, so these RUN everywhere (no docker/systemd/sh
needed) and never trip the CI skip tripwire. They pin the config-side decisions the runbook documents:
the front-door edge exposes an admin endpoint on a UNIX SOCKET (so `caddy reload` works) and NOT a TCP
port (the original no-extra-port posture); and the boot-ordering drop-in orders Docker after tailscaled.
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_FD = _REPO / "deploy" / "frontdoor"
_FD_CADDY = _FD / "Caddyfile"
_DROPIN = _FD / "docker-after-tailscaled.conf"


def _noncomment_lines(text: str) -> list[str]:
    """Non-comment source lines, stripped. `admin` only appears in the global block, so scanning these
    directly avoids brace-matching (a `{$ENV}` token inside a header COMMENT would otherwise fool a
    first-brace matcher)."""
    return [ln.strip() for ln in text.splitlines() if not ln.strip().startswith("#")]


def test_frontdoor_admin_is_a_unix_socket_not_a_tcp_port():
    """The edge must reach `caddy reload` via an admin endpoint on a UNIX SOCKET (admin unix//...),
    NOT a TCP port and NOT `admin off`. A unix socket opens no network port (honouring the original
    no-extra-listening-port posture) while still letting install-frontdoor.sh reload the running config.
    FAILS IF the admin block reverts to `admin off` (reload could never work) or binds a TCP address
    (a new host/internet-reachable surface under network_mode: host)."""
    admin_lines = [ln for ln in _noncomment_lines(_FD_CADDY.read_text(encoding="utf-8"))
                   if re.match(r"^admin\b", ln)]
    assert admin_lines, "the global block must declare an admin directive (want a unix socket)"
    assert len(admin_lines) == 1, f"exactly one admin directive expected: {admin_lines}"
    admin = admin_lines[0]
    assert admin != "admin off", (
        "admin is off -- `caddy reload` cannot work, so the O1 in-place reload degrades to a restart on "
        "every deploy. Use a unix socket instead.")
    assert re.match(r"^admin\s+unix//", admin), (
        f"admin must be on a unix socket (admin unix//...), got: {admin!r}")
    # No TCP admin address (host:port or :port) -- that would open a listening port under host networking.
    assert not re.match(r"^admin\s+([0-9.]+)?:\d+", admin), (
        f"admin must NOT bind a TCP port (network_mode: host would expose it): {admin!r}")


def test_boot_ordering_dropin_orders_docker_after_tailscaled():
    """The docker.service drop-in must order the daemon AFTER tailscaled so the front-door container
    never starts before the tailnet resolver (the post-reboot 502 incident). FAILS IF the drop-in is
    missing the After=tailscaled.service ordering, or hard-Requires tailscaled (which would make a
    tailnet-less box unbootable -- Wants= is the intended soft dependency)."""
    assert _DROPIN.is_file(), f"the boot-ordering drop-in must exist at {_DROPIN}"
    text = _DROPIN.read_text(encoding="utf-8")
    unit = [ln.strip() for ln in text.splitlines() if not ln.strip().startswith("#")]
    assert "[Unit]" in unit, "the drop-in must carry a [Unit] section"
    assert any(ln == "After=tailscaled.service" for ln in unit), (
        "the drop-in must order docker After=tailscaled.service")
    assert not any(ln.startswith("Requires=") for ln in unit), (
        "the drop-in must NOT hard-Require tailscaled (a tailnet-less box must still boot); use Wants=")
    assert any(ln == "Wants=tailscaled.service" for ln in unit), (
        "the drop-in should Wants=tailscaled.service (soft dependency)")


def test_boot_ordering_dropin_has_no_em_dashes():
    """House rule: no em dashes in the shipped ops files' user-facing text."""
    assert "—" not in _DROPIN.read_text(encoding="utf-8"), "no em dashes in the drop-in"
