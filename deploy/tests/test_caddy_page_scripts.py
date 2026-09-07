"""The generated survey pages load portal scripts (/src/fetchcmd.js, /src/fetchdialog.js,
/src/page-fetch.js) beside the SPA. Two Caddyfile facts make that safe, and both are pinned here
POSITIVELY: not that some exclusion is absent, but that the rule which reaches /src/*.js and the
rule which serves /surveys/<slug> under the strict CSP are the rules the config actually declares.

  * /src/*.js revalidates on every use on BOTH listeners. The @revalidate matcher is a block of
    `not path` exclusions and nothing else, so it matches every path it does not exclude; the pin
    evaluates those exclusions against /src/page-fetch.js the way Caddy would and requires a match,
    and requires the no-cache header directive on that matcher on each listener.
  * the strict CSP the pages are served under keeps script-src 'self' alone, and its matcher, also
    a block of `not path` exclusions, matches /surveys/<slug>: the pages carry no inline script
    (the engine's page test pins that), so no widening is ever needed here.

Where the caddy binary is available (it is on the box and in CI's live-validate leg), a third pin
adapts the Caddyfile and reads the two CSP values back out of the adapted JSON, which proves the
header lines are directives Caddy accepts rather than text that happens to match a regex.
"""
from __future__ import annotations

import fnmatch
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_BOX_CADDY = _REPO / "deploy" / "docker" / "caddy" / "Caddyfile"
_SCRIPTS = ("/src/fetchcmd.js", "/src/fetchdialog.js", "/src/page-fetch.js")
_PAGE = "/surveys/example-survey"


def _text() -> str:
    return _BOX_CADDY.read_text(encoding="utf-8")


def _blocks(name: str) -> list[str]:
    """Every declaration of the named matcher, in either Caddyfile form: the block form
    `@name { ... }` (one term per line) and the one-line form `@name <term>`. Each is returned as
    its terms, one per line, so the evaluation below reads both the same way."""
    text = _text()
    found = re.findall(r"^\t@%s \{(.*?)\n\t\}" % re.escape(name), text, re.S | re.M)
    found += re.findall(r"^\t@%s ((?!\{)[^\n]+)$" % re.escape(name), text, re.M)
    return found


def _matches(block: str, path: str) -> bool:
    """Whether a matcher block made only of `not path` lines matches `path` (Caddy's path matcher is
    a glob per pattern; `not` inverts the whole line). A block that carries any other term is
    refused, because this evaluation would then be a guess."""
    for raw in block.strip().splitlines():
        line = raw.strip()
        if not line:
            continue
        assert line.startswith("not path "), f"the matcher carries a term this pin cannot evaluate: {line!r}"
        patterns = line[len("not path "):].split()
        if any(fnmatch.fnmatchcase(path, p) for p in patterns):
            return False
    return True


def test_portal_scripts_fall_under_the_revalidate_rule_on_both_listeners():
    blocks = _blocks("revalidate")
    assert len(blocks) == 2, "one @revalidate rule per listener"
    for block in blocks:
        for script in _SCRIPTS:
            assert _matches(block, script), f"{script} must be reached by the revalidate rule: {block!r}"
        assert not _matches(block, "/vendor/leaflet.js"), "the long-lived vendor tree stays excluded"
    assert _text().count('header @revalidate Cache-Control "no-cache"') == 2, \
        "each listener must apply Cache-Control no-cache to the revalidate matcher"
    vendor = _blocks("vendorAssets")
    assert len(vendor) == 2
    for block in vendor:
        first = block.strip().splitlines()[0].strip()
        assert first.startswith("path ") and not any(
            fnmatch.fnmatchcase(s, p) for s in _SCRIPTS for p in first[len("path "):].split()), \
            "the long-lived vendor rule must not reach the portal scripts"


def test_survey_pages_are_served_under_the_strict_csp_with_script_src_self_alone():
    blocks = _blocks("strictPages")
    assert len(blocks) == 2, "one strict CSP matcher per listener"
    for block in blocks:
        assert _matches(block, _PAGE), f"/surveys/<slug> must fall under the strict CSP: {block!r}"
        assert not _matches(block, "/add-survey.html"), "add-survey keeps its own CSP"
    values = re.findall(r'header @strictPages Content-Security-Policy "([^"]*)"', _text())
    assert len(values) == 2, "one strict CSP header per listener"
    for csp in values:
        directives = {d.strip().split(" ")[0]: d.strip() for d in csp.split(";") if d.strip()}
        assert directives.get("script-src") == "script-src 'self'", \
            f"the strict CSP must keep script-src 'self' and nothing else, got {directives.get('script-src')!r}"


@pytest.mark.skipif(shutil.which("caddy") is None, reason="caddy binary not available")
def test_the_adapted_config_carries_the_strict_csp_as_a_real_header_directive(tmp_path):
    """`caddy adapt` turns the Caddyfile into the JSON Caddy runs; the two strict CSP values must
    come back out of it as header handlers, which a comment or a mistyped directive would not."""
    r = subprocess.run(["caddy", "adapt", "--config", str(_BOX_CADDY), "--adapter", "caddyfile"],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    cfg = json.loads(r.stdout)
    found = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("handler") == "headers":
                for k, v in ((node.get("response") or {}).get("set") or {}).items():
                    if k.lower() == "content-security-policy":
                        found.extend(v)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(cfg)
    strict = [v for v in found if "script-src 'self'" in v and "connect-src" not in v]
    assert len(strict) >= 2, f"the strict CSP must adapt into a header handler on each listener, got {found}"
    for v in strict:
        assert "'unsafe-inline'" not in v.split("script-src")[1].split(";")[0]
