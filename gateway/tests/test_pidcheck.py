"""IDCONS D4/D5 (identifier-consolidation, SPEC §5) — the curator DOI-resolution check (gateway side).

The alive-rule (SPEC §5.1) is the load-bearing semantics: only doi.org's OWN 404 is `unregistered`;
every other doi.org answer (200 / 30x redirect / 403 / 5xx) is `resolved`; a network failure is `error`.
These tests pin the pure classifier, the DOI/URL normalisation, the check() flow over a MOCKED opener
(NEVER the network — the build/CI stays offline), the not-a-DOI skip, and the session-gated endpoint.

The parity pin (test_alive_rule_parity_with_engine_tool) asserts the gateway's content-blind copy of the
alive-rule agrees with the engine refresh tool's copy over a shared table — the same drift the vendored-
validator PIN closes for the validator.
"""
from __future__ import annotations

import importlib.util
import urllib.error
from pathlib import Path

from gateway import pidcheck
from gateway.tests.conftest import app_client, curator_login, run


# ---- the pure alive-rule -------------------------------------------------------------------------

def test_classify_only_doi_org_404_is_unregistered():
    """SPEC §5.1: ONLY a 404 from doi.org is `unregistered`. FAILS IF a 404 is not caught."""
    assert pidcheck.classify(404, False) == pidcheck.STATUS_UNREGISTERED


def test_classify_registered_answers_are_resolved():
    """200 / 301 / 302 / 403 (T&F bot-block) / 500 all mean the DOI EXISTS -> resolved. FAILS IF a
    non-200 registered answer false-alarms as dead (the …2378132 incident the rule exists to prevent)."""
    for code in (200, 301, 302, 303, 403, 429, 500, 503):
        assert pidcheck.classify(code, False) == pidcheck.STATUS_RESOLVED, code


def test_classify_network_error_is_error():
    """A network/DNS/timeout failure is `error` (unknown; the portal links as today). FAILS IF a
    transport failure is misread as a DOI verdict."""
    assert pidcheck.classify(None, True) == pidcheck.STATUS_ERROR
    assert pidcheck.classify(None, False) == pidcheck.STATUS_ERROR


def test_normalise_doi_strips_resolver_prefixes():
    """A bare DOI and a full https://doi.org/ URL check the SAME target. FAILS IF the resolver prefix
    is not stripped (the HEAD would double the host)."""
    assert pidcheck.normalise_doi("10.25914/sv5r-zw68") == "10.25914/sv5r-zw68"
    assert pidcheck.normalise_doi("https://doi.org/10.25914/sv5r-zw68") == "10.25914/sv5r-zw68"
    assert pidcheck.normalise_doi("http://dx.doi.org/10.25914/sv5r-zw68") == "10.25914/sv5r-zw68"


def test_is_doi_heuristic():
    assert pidcheck.is_doi("10.25914/sv5r-zw68")
    assert pidcheck.is_doi("https://doi.org/10.1/x")
    assert not pidcheck.is_doi("hdl:1234/abc")
    assert not pidcheck.is_doi("https://example.org/dataset")


# ---- check() over a MOCKED opener (no network) ---------------------------------------------------

class _FakeResp:
    def __init__(self, code):
        self.status = code

    def getcode(self):
        return self.status


class _FakeOpener:
    """A urllib opener stand-in: `open` returns a fake response, raises HTTPError, or raises URLError,
    per the scripted behaviour — so check() exercises the real classify path with ZERO network."""

    def __init__(self, *, code=None, http_error=None, url_error=False):
        self._code = code
        self._http_error = http_error
        self._url_error = url_error

    def open(self, req, timeout=None):
        if self._url_error:
            raise urllib.error.URLError("dns")
        if self._http_error is not None:
            raise urllib.error.HTTPError(req.full_url, self._http_error, "err", {}, None)
        return _FakeResp(self._code)


def test_check_resolved_doi():
    r = pidcheck.check("10.25914/live", opener=_FakeOpener(code=200))
    assert r["status"] == pidcheck.STATUS_RESOLVED
    assert r["label"] == "resolves"
    assert r["identifier"] == "10.25914/live"


def test_check_reserved_doi_404():
    """The vulcan case: doi.org 404s a reserved-but-not-yet-active NCI DOI -> reserved. FAILS IF a 404
    HTTPError is treated as a network error rather than the unregistered verdict."""
    r = pidcheck.check("10.25914/sv5r-zw68", opener=_FakeOpener(http_error=404))
    assert r["status"] == pidcheck.STATUS_UNREGISTERED
    assert "reserved" in r["label"]


def test_check_bot_blocked_publisher_403_is_resolved():
    """Taylor & Francis blocks bots with 403 AFTER doi.org's 30x — but we do not follow redirects, so
    doi.org's own answer is what we classify; even a direct 403 = resolved. FAILS IF 403 false-alarms."""
    r = pidcheck.check("10.1080/2378132", opener=_FakeOpener(http_error=403))
    assert r["status"] == pidcheck.STATUS_RESOLVED


def test_check_network_error():
    r = pidcheck.check("10.25914/x", opener=_FakeOpener(url_error=True))
    assert r["status"] == pidcheck.STATUS_ERROR
    assert r["label"] == "check failed"


def test_check_non_doi_is_skipped():
    """A Handle/URL/RAiD identifier has no doi.org target -> skipped (the chip says so). FAILS IF a
    non-DOI is HEADed against doi.org anyway."""
    r = pidcheck.check("https://hdl.handle.net/1234/abc", opener=_FakeOpener(code=200))
    assert r["status"] == pidcheck.STATUS_SKIPPED


# ---- the session-gated endpoint ------------------------------------------------------------------

def test_pid_check_endpoint_requires_session(tmp_path):
    """GET /gateway/curator/pid-check without a session redirects to login (303). FAILS IF the chip
    endpoint leaks to an unauthenticated caller."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, _cfg):
            r = await client.get("/gateway/curator/pid-check?identifier=10.1/x",
                                  follow_redirects=False)
            assert r.status_code == 303
    run(_body())


def test_pid_check_endpoint_returns_verdict(tmp_path, monkeypatch):
    """A logged-in curator gets a JSON verdict; the network is MOCKED (offline test). FAILS IF the
    endpoint does not return {status,label,identifier} or hits the real network."""
    async def _body():
        # Mock the transport so no real doi.org HEAD happens: doi.org answers 404 -> reserved.
        monkeypatch.setattr(pidcheck, "_head_status", lambda url, opener=None: (404, False))
        async with app_client(tmp_path) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get("/gateway/curator/pid-check?identifier=10.25914/sv5r-zw68")
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == pidcheck.STATUS_UNREGISTERED
            assert body["identifier"] == "10.25914/sv5r-zw68"
    run(_body())


def test_pid_check_endpoint_blank_identifier_is_400(tmp_path):
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get("/gateway/curator/pid-check?identifier=")
            assert r.status_code == 400
    run(_body())


# ---- parity pin: the alive-rule copies must agree ------------------------------------------------

_ENGINE_REFRESH_PY = Path(__file__).resolve().parents[2] / "engine" / "scripts" / "refresh_pid_status.py"


def _load_engine_refresh():
    spec = importlib.util.spec_from_file_location("_ausmt_engine_refresh_pid", _ENGINE_REFRESH_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_alive_rule_parity_with_engine_tool():
    """The gateway (content-blind) and the engine refresh tool each carry their OWN copy of the alive-rule
    (the gateway image cannot import engine/). They MUST agree — pinned here over a shared table, the same
    drift-guard the vendored-validator PIN gives the validator. FAILS IF the two classifiers diverge."""
    eng = _load_engine_refresh()
    cases = [(404, False), (200, False), (302, False), (403, False), (500, False),
             (None, True), (None, False)]
    for code, neterr in cases:
        assert pidcheck.classify(code, neterr) == eng.classify(code, neterr), (code, neterr)
