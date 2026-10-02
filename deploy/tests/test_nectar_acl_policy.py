"""The tailnet policy entries for the Nectar hosts (deploy/nectar/acl-policy.hujson).

The file is merged into a live policy the repository cannot see, and Tailscale's stock policy
carries an allow-all rule, so a grant here proves nothing about what the serving host can reach.
The policy's own `tests` and `sshTests` stanzas are what Tailscale checks on every save of the
merged policy, and a save that breaks one is refused. These pins hold that the stanzas exist and
name the fence: the serving host reaches the curation host's reader port and is refused its SSH and
its workbench; curators reach the workbench on 443 and never the gateway's debug port 8444; the
publish and log accounts admit the box's node login without a sign-in check.

Read, never applied: the file is parsed as HuJSON (comments and trailing commas stripped) and the
stanzas are inspected as data.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_POLICY = _REPO / "deploy" / "nectar" / "acl-policy.hujson"


def _strip_comments(text: str) -> str:
    """HuJSON to JSON: drop // and /* */ comments outside strings, then trailing commas."""
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
        elif text.startswith("/*", i):
            i = text.index("*/", i) + 2
        else:
            out.append(c)
            i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def _policy() -> dict:
    return json.loads(_strip_comments(_POLICY.read_text(encoding="utf-8")))


def _tests_for(src: str) -> list[dict]:
    return [t for t in (_policy().get("tests") or []) if t.get("src") == src]


def test_the_policy_parses_as_hujson():
    assert isinstance(_policy().get("acls"), list)


def test_the_serving_host_reaches_the_reader_port_and_nothing_else_on_the_box():
    """FAILS IF no test pins the serving host's one grant, or if a leftover wide rule could
    give the only internet-facing host the box's SSH or its workbench without a save failing."""
    rows = _tests_for("tag:ausmt-serve")
    assert rows, "a tests entry must take tag:ausmt-serve as its source"
    accept = [d for t in rows for d in t.get("accept", [])]
    deny = [d for t in rows for d in t.get("deny", [])]
    assert "ausmt-box:8445" in accept, accept
    for dst in ("ausmt-box:22", "ausmt-box:443"):
        assert dst in deny, (dst, deny)


def test_curators_reach_the_workbench_and_never_the_gateway_debug_port():
    """FAILS IF no test pins the curators' grant on 443 and their refusal on 8444."""
    rows = _tests_for("group:curators")
    assert rows, "a tests entry must take group:curators as its source"
    accept = [d for t in rows for d in t.get("accept", [])]
    deny = [d for t in rows for d in t.get("deny", [])]
    assert "ausmt-box:443" in accept, accept
    assert "ausmt-box:8444" in deny, deny


def test_the_box_login_reaches_the_two_service_accounts_unattended():
    """FAILS IF no sshTests entry pins the phase-one publish rule: the box's node login admitted as
    publish and caddylog on the serving host without a sign-in check. Root is not pinned: that login
    is normally an administrator's, whose root sessions take the sign-in check rather than a deny."""
    rows = [t for t in (_policy().get("sshTests") or [])
            if t.get("src") == "<BOX_NODE_USER>" and "tag:ausmt-serve" in (t.get("dst") or [])]
    assert rows, "an sshTests entry must take the box's node login to tag:ausmt-serve"
    accept = [u for t in rows for u in t.get("accept", [])]
    assert {"publish", "caddylog"} <= set(accept), accept
