"""Head/serving hygiene pins (findability audit 2026-08-28): the duplicate-content redirect, the
HDF5 content type, and the branded 404.

  * /index.html served the same bytes as / with no canonical anywhere - the host's one
    duplicate-content pair. The alias 301s home now, and index.html itself carries the canonical.
  * .h5 has no extension entry Caddy resolves correctly (its table guesses application/mipc), so
    the server contradicted the survey pages' own JSON-LD encodingFormat
    (application/x-hdf5). An explicit matcher states the real type.
  * an unknown entity id returned a ZERO-BYTE 404: correct for crawlers, a dead end for a human
    following a stale link. handle_errors serves the branded portal/404.html WITH the 404 status
    preserved (file_server status 404), so crawl semantics are unchanged.

BOTH reader listeners carry all three: :8081 is what the public reaches through the front door,
:8080 is the tailnet-side twin, and the C47 discipline is that the two never drift.
"""
from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_BOX = _REPO / "deploy" / "docker" / "caddy" / "Caddyfile"
_404 = _REPO / "portal" / "404.html"
_INDEX = _REPO / "portal" / "index.html"

from test_frontdoor_bridge import _brace_match  # noqa: E402  (house practice: shared harness helpers)


def _listener_bodies():
    text = _BOX.read_text(encoding="utf-8")
    out = {}
    for port in (":8080", ":8081"):
        start = text.index(f"\n{port} {{") + 1
        out[port] = _brace_match(text, text.index("{", start))
    return out


def test_index_html_redirects_home_on_both_listeners():
    for port, body in _listener_bodies().items():
        assert "redir /index.html / 301" in body, f"{port} must 301 the /index.html alias home"


def test_h5_content_type_is_stated_on_both_listeners():
    for port, body in _listener_bodies().items():
        assert '@h5files path *.h5' in body and 'header @h5files Content-Type "application/x-hdf5"' in body, \
            f"{port} must state the real HDF5 type (Caddy's table guesses application/mipc)"


def test_the_branded_404_serves_with_the_status_preserved():
    for port, body in _listener_bodies().items():
        assert "handle_errors" in body and "rewrite * /404.html" in body, \
            f"{port} must serve the branded 404 page"
        assert "status 404" in body, \
            f"{port} must preserve the 404 status (a soft-200 would poison crawl hygiene)"
    page = _404.read_text(encoding="utf-8")
    assert 'content="noindex"' in page and 'href="/"' in page, \
        "the 404 page must stay out of the index and offer a way home"


def test_the_spa_root_declares_its_canonical():
    head = _INDEX.read_text(encoding="utf-8")[:8000]
    assert '<link rel="canonical" href="https://ausmt.auscope.org.au/">' in head, \
        "the SPA root must carry the canonical the entity pages already have"
