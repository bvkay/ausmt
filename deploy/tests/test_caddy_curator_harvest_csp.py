"""the contributor-credit model (curator DOI harvest) - Caddyfile CSP config-assertion pin.

The curator publications "Look up DOI" button runs the SAME client-side registry harvest the public Add
Survey page uses, so the curator metadata editor + survey hub pages need the SAME two citation hosts in
connect-src. This pins that the :8080 Caddyfile grants exactly api.crossref.org + api.datacite.org to the
curator edit/hub pages, that script-src STAYS 'self' there (no injection-vector widening), and that the
three CSP matchers stay MUTUALLY EXCLUSIVE (strictPages excludes the curator-harvest paths). A pure config
assertion over the rendered Caddyfile - no caddy binary needed (test_caddy_log_masking runs the live
`caddy validate` leg in CI).
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_CADDYFILE = _REPO / "deploy" / "docker" / "caddy" / "Caddyfile"


def _text() -> str:
    return _CADDYFILE.read_text(encoding="utf-8")


def _curator_harvest_csp() -> str:
    """The Content-Security-Policy value on the @curatorHarvestPages matcher (the header line's quoted
    string). Fails if the matcher/header is absent."""
    text = _text()
    assert "@curatorHarvestPages" in text, "the curator-harvest CSP matcher is missing from the Caddyfile"
    m = re.search(r'header @curatorHarvestPages Content-Security-Policy "([^"]*)"', text)
    assert m is not None, "the @curatorHarvestPages matcher has no CSP header"
    return m.group(1)


def test_curator_edit_and_hub_paths_are_the_harvest_scope():
    """The harvest CSP is scoped to the curator edit + hub paths (where the publications button lives)."""
    text = _text()
    m = re.search(r"@curatorHarvestPages path (.+)", text)
    assert m is not None, "the @curatorHarvestPages path matcher is missing"
    scope = m.group(1)
    assert "/gateway/curator/edit/*" in scope
    assert "/gateway/curator/survey/*" in scope


def test_harvest_pages_allow_the_two_citation_registries():
    """connect-src must allow api.crossref.org + api.datacite.org (the same two hosts the public Add
    Survey page uses) for the publications DOI harvest, else the curator harvest fetch is blocked in prod."""
    csp = _curator_harvest_csp()
    assert "https://api.crossref.org" in csp and "https://api.datacite.org" in csp, csp


def test_harvest_pages_allow_the_orcid_and_ror_lookup_hosts():
    """RED before the contributor-credit model CSP change: the People & credit panel's per-row "Look
    up" fetches pub.orcid.org (ORCID -> name) and api.ror.org (ROR -> org name) CLIENT-SIDE, so both must
    be in the curator-harvest connect-src, else the lookup is blocked in prod (it then degrades to a quiet
    note - but the allow-list is the intended path). The four-host allowlist is exactly these registries."""
    csp = _curator_harvest_csp()
    connect = csp.split("connect-src", 1)[1]
    assert "https://pub.orcid.org" in connect, csp
    assert "https://api.ror.org" in connect, csp
    assert ("connect-src 'self' https://api.crossref.org https://api.datacite.org "
            "https://pub.orcid.org https://api.ror.org") in csp, csp


def test_harvest_pages_keep_script_src_self():
    """The widening is connect-src ONLY - script-src STAYS 'self' (no inline, no injection vector), so the
    extra connect-src adds no exfiltration path on the authenticated workbench."""
    csp = _curator_harvest_csp()
    assert "script-src 'self'" in csp
    assert "'unsafe-inline'" not in csp.split("script-src", 1)[1].split(";", 1)[0]


def test_strict_pages_excludes_the_curator_harvest_paths():
    """MUTUAL EXCLUSIVITY: strictPages must NOT also match the curator-harvest paths (else two CSP headers
    ride the same response and Caddy's specificity ordering decides - the exact footgun the Caddyfile
    comment warns about). The strictPages matcher block carries a `not path` for those paths."""
    text = _text()
    m = re.search(r"@strictPages \{(.*?)\}", text, re.S)
    assert m is not None, "@strictPages must be a block matcher (multiple exclusions)"
    body = m.group(1)
    assert "not path /add-survey.html" in body
    assert "not path /gateway/curator/edit/* /gateway/curator/survey/*" in body


def test_strict_pages_csp_still_has_no_registry_connect_src():
    """The BLANKET strictPages CSP (every other page) must NOT carry the registry hosts - the widening is
    scoped to the harvest pages only. Guards against a copy-paste that widens the whole workbench."""
    text = _text()
    m = re.search(r'header @strictPages Content-Security-Policy "([^"]*)"', text)
    assert m is not None
    for host in ("api.crossref.org", "api.datacite.org", "pub.orcid.org", "api.ror.org"):
        assert host not in m.group(1), f"{host} must not widen the blanket strictPages CSP"
