"""The box's serving rules for the two INDEX pages and for URL canonicalisation.

Three defects, all box-side, all proven here against a real Caddy over the SHIPPED directives.

  * /surveys and /collections had nothing to serve, so the front door 301'd both to the SPA root.
    The engine now emits pages/surveys/index.html and pages/collections/index.html; the box serves
    them at the bare paths from the same `current` root the entity pages use.
  * The @entityPage matcher is $-anchored, so /surveys/<slug>/ missed it, missed /data/*, missed
    the portal root and landed on 404.html: 2,653 URL variants that nothing on the site generates
    and that readers, mail clients and reference managers produce constantly. They 301 to the
    published slash-free form. The front door passes the slash form through byte-for-byte (pinned
    in test_frontdoor_pathurl_contract.py), which is exactly why the canonicalisation belongs here.
  * `redir /index.html / 301` dropped the query, so about.html's /index.html?tour=1 - the only
    documented entry point to the guided tour outside the intro panel - never started the tour.

The two listeners carry near-duplicate copies of the reader directives by design (the C47 bridge
pin enforces the no-drift rule), so every source pin below runs against BOTH, and the two
renditions of the new block are compared to each other directly.
"""
from __future__ import annotations

import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_BOX = _REPO / "deploy" / "docker" / "caddy" / "Caddyfile"

from test_frontdoor_bridge import _site_body  # noqa: E402  (house practice: shared harness helpers)

_CADDY = shutil.which("caddy")
_LISTENERS = (r"(?m)^:8080\s*\{", r"(?m)^:8081\s*\{")


def _bodies():
    text = _BOX.read_text(encoding="utf-8")
    return {opener: _site_body(text, opener) for opener in _LISTENERS}


# ==================================================================================================
# Source pins (always run)
# ==================================================================================================
def test_both_listeners_serve_the_two_index_pages():
    """FAILS IF either listener loses the bare-path handle for /surveys and /collections, or serves
    it from anywhere but the atomically swapped data root the entity pages already use."""
    for opener, body in _bodies().items():
        m = re.search(r"@indexPage path_regexp ip (\S+)", body)
        assert m, f"{opener}: no @indexPage matcher"
        assert m.group(1) == r"^/(surveys|collections)$", \
            f"{opener}: @indexPage must match the two bare prefixes exactly, got {m.group(1)}"
        block = re.search(r"handle @indexPage \{([\s\S]*?)\n\t\}", body)
        assert block, f"{opener}: no handle for @indexPage"
        assert "root * /srv/data/current" in block.group(1), \
            f"{opener}: the index pages ride the same current root as every other product"
        assert "rewrite * /pages/{re.ip.1}/index.html" in block.group(1), \
            f"{opener}: the bare path must rewrite to the emitted index document"
        assert "file_server" in block.group(1)


def test_both_listeners_canonicalise_the_trailing_slash_forms():
    """FAILS IF either listener loses the entity trailing-slash 301, the index alias 301, or lets
    either drop the query. The redirect must be permanent: these are published URL shapes."""
    for opener, body in _bodies().items():
        m = re.search(r"@entitySlash path_regexp esl (\S+)", body)
        assert m, f"{opener}: no @entitySlash matcher"
        assert m.group(1) == r"^/(surveys|stations|collections)/([A-Za-z0-9][A-Za-z0-9._-]*)/$", \
            f"{opener}: the slash matcher must mirror @entityPage's id class, got {m.group(1)}"
        assert "redir @entitySlash /{re.esl.1}/{re.esl.2}{ausmt_qs} 301" in body, \
            f"{opener}: the slash form must 301 to the published form with the query preserved"
        assert re.search(r"@indexAlias path_regexp ial \S+", body), f"{opener}: no @indexAlias"
        assert "redir @indexAlias /{re.ial.1}{ausmt_qs} 301" in body, \
            f"{opener}: /surveys/ and its index aliases must 301 to the bare published form"


def test_both_listeners_preserve_the_query_on_the_index_html_redirect():
    """FAILS IF the /index.html canonical redirect drops the query again. about.html's guided-tour
    link is /index.html?tour=1 and the SPA reads the flag from location.search, so a bare target
    means the feature cannot be reached from its only documented entry point."""
    for opener, body in _bodies().items():
        assert "redir /index.html /{ausmt_qs} 301" in body, \
            f"{opener}: the /index.html alias must carry the query to the root"
        qs = re.search(r"map \{http\.request\.uri\} \{ausmt_qs\} \{([\s\S]*?)\n\t\}", body)
        assert qs, f"{opener}: the lazily-evaluated query map must be declared"
        assert re.search(r"~\\\?\(\.\*\)\$\s+\"\?\$\{1\}\"", qs.group(1)), \
            f"{opener}: the map must rebuild '?<query>' from the raw URI"
        assert re.search(r"default\s+\"\"", qs.group(1)), \
            f"{opener}: the map must default to empty, never a bare '?'"


def test_the_two_listeners_do_not_drift_on_the_new_directives():
    """The C47 no-drift rule applied to this module's own edit: the reader directives are a
    deliberate near-duplicate across the two listeners, so a fix applied to one and not the other
    would leave the public path (via :8081) behaving differently from the tailnet one. FAILS IF the
    two renditions of the canonicalisation block differ by so much as a byte."""
    bodies = _bodies()

    def _slice(body: str) -> str:
        start = body.index("map {http.request.uri} {ausmt_qs} {")
        end = body.index("@sitemapXml")
        return body[start:end]

    a, b = (_slice(bodies[o]) for o in _LISTENERS)
    assert a == b, "the :8080 and :8081 canonicalisation blocks have drifted apart"


# ==================================================================================================
# Runtime pins: a REAL Caddy over the shipped :8081 reader directives
# ==================================================================================================
def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _get(port: int, path: str) -> tuple[int, str | None, str]:
    """(status, location-header-or-None, body) WITHOUT following redirects."""
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):  # noqa: ARG002
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    try:
        r = opener.open(f"http://127.0.0.1:{port}{path}", timeout=5)
        hdrs, body, st = dict(r.headers), r.read().decode("utf-8", "replace"), r.status
    except urllib.error.HTTPError as e:
        hdrs, body, st = dict(e.headers), e.read().decode("utf-8", "replace"), e.code
    return st, {k.lower(): v for k, v in hdrs.items()}.get("location"), body


@pytest.fixture()
def reader(tmp_path):
    """The SHIPPED :8081 reader directives over a hermetic data/portal tree."""
    if _CADDY is None:
        pytest.skip("no caddy binary on PATH - runtime pins run in CI (gateway-ci)")
    data = tmp_path / "data" / "current"
    (data / "pages" / "surveys").mkdir(parents=True)
    (data / "pages" / "collections").mkdir(parents=True)
    (data / "pages" / "stations").mkdir(parents=True)
    (data / "pages" / "surveys" / "index.html").write_text("SURVEYS INDEX", encoding="utf-8")
    (data / "pages" / "collections" / "index.html").write_text("COLLECTIONS INDEX", encoding="utf-8")
    (data / "pages" / "surveys" / "vulcan-2022.html").write_text("SURVEY PAGE", encoding="utf-8")
    (data / "pages" / "stations" / "au.vulcan-2022.MBV07.html").write_text("STATION PAGE",
                                                                          encoding="utf-8")
    (data / "sitemap.xml").write_text("<urlset/>", encoding="utf-8")
    portal = tmp_path / "portal"
    portal.mkdir()
    (portal / "index.html").write_text("PORTAL ROOT", encoding="utf-8")
    (portal / "404.html").write_text("NOT FOUND", encoding="utf-8")
    (tmp_path / "basemap").mkdir()

    body = _site_body(_BOX.read_text(encoding="utf-8"), r"(?m)^:8081\s*\{")
    body = (body.replace("/srv/data/current", data.as_posix())
                .replace("/srv/portal", portal.as_posix())
                .replace("/srv/basemap", (tmp_path / "basemap").as_posix()))
    port = _free_port()
    cfg = "{\n\tadmin off\n\tauto_https off\n}\n" + f":{port} {{\n{body}\n}}\n"
    cfgpath = tmp_path / "reader.caddy"
    cfgpath.write_text(cfg, encoding="utf-8")
    v = subprocess.run([_CADDY, "validate", "--adapter", "caddyfile", "--config", str(cfgpath)],
                       capture_output=True, text=True)
    assert v.returncode == 0, f"composed reader config invalid:\n{v.stdout}\n{v.stderr}"
    proc = subprocess.Popen([_CADDY, "run", "--adapter", "caddyfile", "--config", str(cfgpath)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.05)
        yield port
    finally:
        proc.terminate()
        proc.wait(timeout=5)


@pytest.mark.skipif(_CADDY is None, reason="no caddy binary on PATH - runtime pins run in CI (gateway-ci)")
def test_runtime_bare_prefixes_serve_the_index_pages(reader):
    """RUNTIME. /surveys and /collections answer 200 with the emitted hub documents. FAILS IF
    either falls through to the portal file_server (which would 404 them, as it did)."""
    for path, want in (("/surveys", "SURVEYS INDEX"), ("/collections", "COLLECTIONS INDEX")):
        st, loc, body = _get(reader, path)
        assert st == 200, f"{path}: expected the index page, got {st} {loc!r}"
        assert body == want, f"{path}: served {body!r}"


@pytest.mark.skipif(_CADDY is None, reason="no caddy binary on PATH - runtime pins run in CI (gateway-ci)")
def test_runtime_entity_urls_stay_redirect_free_and_their_slash_form_canonicalises(reader):
    """RUNTIME, the whole trailing-slash contract in one pass: the published form is served with no
    redirect of its own, and the slash form 301s onto it (query preserved) and then serves. FAILS
    IF the published form grows a hop, or the slash form 404s as it did."""
    for path in ("/surveys/vulcan-2022", "/stations/au.vulcan-2022.MBV07"):
        st, loc, _ = _get(reader, path)
        assert st == 200 and loc is None, f"{path}: must serve directly, got {st} {loc!r}"
    st, loc, _ = _get(reader, "/surveys/vulcan-2022/")
    assert st == 301 and loc == "/surveys/vulcan-2022", f"got {st} {loc!r}"
    st, _loc, body = _get(reader, loc)
    assert st == 200 and body == "SURVEY PAGE", f"the canonical target must serve, got {st}"
    st, loc, _ = _get(reader, "/stations/au.vulcan-2022.MBV07/?utm=1")
    assert st == 301 and loc == "/stations/au.vulcan-2022.MBV07?utm=1", \
        f"the query must ride the canonicalisation, got {st} {loc!r}"


@pytest.mark.skipif(_CADDY is None, reason="no caddy binary on PATH - runtime pins run in CI (gateway-ci)")
def test_runtime_index_aliases_land_on_the_bare_published_form(reader):
    """RUNTIME. /surveys/ and the /surveys/index aliases 301 to /surveys, so the hub has ONE URL.
    FAILS IF an alias serves the document itself (a duplicate-content pair) or 404s."""
    for path in ("/surveys/", "/surveys/index", "/surveys/index.html", "/collections/"):
        st, loc, _ = _get(reader, path)
        want = "/collections" if path.startswith("/collections") else "/surveys"
        assert st == 301 and loc == want, f"{path}: expected 301 to {want}, got {st} {loc!r}"


@pytest.mark.skipif(_CADDY is None, reason="no caddy binary on PATH - runtime pins run in CI (gateway-ci)")
def test_runtime_index_html_redirect_preserves_the_query(reader):
    """RUNTIME, the guided-tour fix. /index.html?tour=1 must reach /?tour=1; a bare /index.html
    must still reach / with no dangling '?'. FAILS IF the query is dropped (the tour never starts)
    or a bare '?' is appended (a needless second URL for the root)."""
    st, loc, _ = _get(reader, "/index.html?tour=1")
    assert st == 301 and loc == "/?tour=1", f"got {st} {loc!r}"
    st, loc, _ = _get(reader, "/index.html")
    assert st == 301 and loc == "/", f"a bare alias must not gain a '?', got {st} {loc!r}"


@pytest.mark.skipif(_CADDY is None, reason="no caddy binary on PATH - runtime pins run in CI (gateway-ci)")
def test_runtime_an_unknown_entity_id_still_404s_honestly(reader):
    """FAILS IF the new matchers turn an unknown id into anything but an honest 404 on the branded
    page. The canonicalisation must not paper over a dead link."""
    st, _loc, body = _get(reader, "/surveys/does-not-exist")
    assert st == 404 and body == "NOT FOUND", f"got {st} {body!r}"
