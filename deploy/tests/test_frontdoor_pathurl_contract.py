"""Path-URL contract, tier 1 (owner ruling 2026-08-18): the front door knows the three shapes.

/surveys/<slug>, /stations/<ausmt_id> and /collections/<id> are the PUBLISHED URL contract for the
portal's three entity kinds. Tier 1 maps each shape onto the SPA's hash route with a server-side
PERMANENT redirect in the CANONICAL site block:

    /surveys/<slug>       -> https://<canonical>/#/survey/<slug>
    /stations/<ausmt_id>  -> https://<canonical>/#/station/<ausmt_id>
    /collections/<id>     -> https://<canonical>/#/collection/<id>

The load-bearing properties, each pinned here:

  * MECHANISM: Caddy cannot substitute a captured path segment into a fragment with a plain
    `redir` matcher, so each shape is a `handle_path` (strips the prefix off BOTH the decoded and
    the raw escaped path before its body runs; a plain handle+`uri strip_prefix` would break
    because the default directive order runs redir BEFORE uri) whose redir target is rebuilt from
    two lazily-evaluated `map`s over the stripped URI: {ausmt_pathurl_rest} = the raw remainder
    without the query (the entity id, leading slash included, byte-for-byte, never decoded or
    re-encoded), {ausmt_qs} = "?<query>" when a query is present, else "".
  * QUERY DECISION (pinned, not accidental): queries on path-shaped links are PRESERVED onto the
    target BEFORE the fragment (/surveys/x?utm=1 -> /?utm=1#/survey/x). A query after the # would
    be swallowed into the fragment and break the route.
  * A BARE /surveys, /surveys/ (and the station/collection twins) redirects to the portal root,
    never to a broken empty-fragment URL.
  * 302/temporary is FORBIDDEN: these are published contracts, so `permanent` (301) only.
  * The redirects live in the CANONICAL block ABOVE the @nonpublic deny and do not disturb the
    walls, the masked log or the reader proxy (those keep their own pins in
    test_frontdoor_bridge.py / test_frontdoor_canonical_redirect.py).
  * The LEGACY chain stays two hops: legacy /surveys/x 301s to the canonical host with {uri}
    preserved (the legacy block), THEN the canonical block maps it into the fragment route.
  * A redirect hop at the canonical block DOES land in the masked access log (this block logs);
    the analytics exclusion of those 301 lines is pinned in test_aggregate_stats.py.

The textual pins run everywhere (no caddy, no sh). Where a caddy binary is on PATH the mechanism is
additionally proven against a REAL Caddy (live 301s for every shape, byte-preservation of an
escaped id, the query placement, the bare-prefix rule, the two-hop legacy chain, and a red-proof
that stripping the section makes /surveys/* fall through to the reader). CI installs caddy
(gateway-ci.yml), so the runtime legs run there; on a caddy-less dev box the textual pins stand in,
same gating as test_frontdoor_bridge.py.
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
_DOCTOR = _FRONTDOOR / "doctor.sh"
_RUNBOOK = _FRONTDOOR / "RUNBOOK.md"

_HAS_CADDY = shutil.which("caddy") is not None

_SECTION_OPEN = "# ---- PATH-URL CONTRACT"
_SECTION_CLOSE = "# ---- end path-url contract"

# (url prefix, fragment route prefix) for the three published shapes.
_SHAPES = (("surveys", "survey"), ("stations", "station"), ("collections", "collection"))

# The BARE prefixes and what the front door does with each. /surveys and /collections now have
# real index pages behind them (engine pages/<kind>/index.html, served by the box), so they pass
# through to the reader like any other portal path. /stations has no index BY RULING: 2,625
# noindex station pages are deliberately unadvertised and there is nothing to list, so the bare
# form keeps its 301 to the portal root.
_BARE_REDIRECTED = ("stations",)
_BARE_PASSTHROUGH = ("surveys", "collections")


# ==================================================================================================
# Helpers
# ==================================================================================================
def _fd_text() -> str:
    return _FD_CADDY.read_text(encoding="utf-8")


def _brace_match(text: str, open_at: int) -> str:
    """text[open_at .. matching close] inclusive, from the '{' at/after open_at. Char-wise depth is
    correct here even on placeholder-bearing lines: every {placeholder} self-balances."""
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


def _block_after(text: str, opener: str) -> str:
    """The brace-matched block opened by the LAST '{' on the line carrying `opener` (a map opener
    line carries placeholder braces before its structural one, so 'first { after index' would
    brace-match a placeholder instead)."""
    i = text.index(opener)
    line_end = text.index("\n", i)
    return _brace_match(text, text.rindex("{", i, line_end))


def _canonical_body(text: str) -> str:
    m = re.search(r"\{\$AUSMT_PUBLIC_NAME\} \{", text)
    assert m, "the canonical site block must exist"
    brace_idx = text.index("{", m.end() - 1)
    return _brace_match(text, brace_idx)[1:-1]


def _section(text: str) -> str:
    """The path-url contract section of the canonical body (banner to banner, inclusive)."""
    body = _canonical_body(text)
    o = body.index(_SECTION_OPEN)
    c = body.index(_SECTION_CLOSE)
    assert o < c, "the section banners must be in order"
    return body[o:body.index("\n", c) + 1]


def _strip_section(text: str) -> str:
    """The PRE-CHANGE composition: the whole path-url section removed (red-proof input)."""
    lines = text.splitlines(keepends=True)
    out, dropping = [], False
    for line in lines:
        if _SECTION_OPEN in line:
            dropping = True
        if not dropping:
            out.append(line)
        if _SECTION_CLOSE in line:
            dropping = False
    return "".join(out)


# ==================================================================================================
# Textual pins (always run)
# ==================================================================================================
def test_pathurl_section_sits_in_the_canonical_block_above_the_deny():
    """The redirect section is INSIDE the canonical site block, ABOVE the @nonpublic deny (a path
    link must map before the deny could see it) and outside the legacy render markers (both
    renderings keep it: the shapes are canonical surface). FAILS IF the section is missing, sits
    after the deny, or leaks into the legacy-templated range."""
    text = _fd_text()
    body = _canonical_body(text)
    assert _SECTION_OPEN in body and _SECTION_CLOSE in body, (
        "the canonical block must carry the path-url contract section")
    assert body.index(_SECTION_CLOSE) < body.index("@nonpublic path"), (
        "the path-url section must sit ABOVE the @nonpublic deny")
    legacy_range = text[text.index("# >>> legacy-redirect"):text.index("# <<< legacy-redirect")]
    assert _SECTION_OPEN not in legacy_range, (
        "the section must not sit inside the legacy-templated range (both renderings keep it)")


def test_pathurl_entity_shapes_pass_through_to_the_reader():
    """Tier 3: the three deep entity shapes carry NO redirect of their own - they fall through the
    handles to the box_upstream catch-all, and the box serves the prerendered landing page at the
    same URL. FAILS IF any entity handle_path (or any fragment redirect for the shapes) reappears,
    which would put the crawler-invisible hash route back in front of the landing pages."""
    section = _section(_fd_text())
    for prefix, frag in _SHAPES:
        assert f"handle_path /{prefix}/*" not in section, (
            f"/{prefix}/* must pass through to the reader (tier 3), not redirect")
        assert f"#/{frag}" not in section, (
            f"no fragment redirect for /{prefix}/* may remain in the section")
    body = _canonical_body(_fd_text())
    assert "import box_upstream" in _block_after(body, "handle {"), (
        "the catch-all the entity shapes fall through to must still proxy to the box")


def test_pathurl_only_the_stations_prefix_redirects_to_the_portal_root():
    """A bare /stations has nothing to list: station pages are noindex and deliberately
    unadvertised (2,625 templated documents), so the prefix keeps its 301 to the portal root, both
    slash forms, query preserved.

    /surveys and /collections are the OPPOSITE case now. They have real index pages, emitted by the
    engine and served by the box at those exact paths, so their front-door handles are GONE and the
    paths pass through to the reader like any other portal path. FAILS IF the stations handle loses
    a slash form or its root target, or if a bare handle reappears for a prefix that now has a
    page (which would 301 a served, canonical, indexable hub page into the SPA root)."""
    section = _section(_fd_text())
    for prefix in _BARE_REDIRECTED:
        m = re.search(rf"@{prefix}_bare path (.+)", section)
        assert m, f"missing @{prefix}_bare matcher"
        assert m.group(1).split() == [f"/{prefix}", f"/{prefix}/"], (
            f"@{prefix}_bare must cover exactly both slash forms, got {m.group(1)!r}")
        h = f"handle @{prefix}_bare {{"
        assert h in section, f"missing handle for @{prefix}_bare"
        h_body = _block_after(section, h)
        redirs = [ln.strip() for ln in h_body.splitlines() if ln.strip().startswith("redir")]
        assert redirs == ["redir https://{$AUSMT_PUBLIC_NAME}/{ausmt_qs} permanent"], (
            f"the bare /{prefix} form must redirect to the portal root, got {redirs}")
    for prefix in _BARE_PASSTHROUGH:
        assert f"@{prefix}_bare" not in section, (
            f"/{prefix} now serves an index page; its bare-prefix redirect must be gone")


def test_pathurl_mechanism_is_handle_path_plus_lazy_maps():
    """The mechanism pins: two lazily-evaluated maps over the (stripped) raw URI build the redirect
    target, and the strip is handle_path, never a bare handle+uri (the default directive order runs
    redir BEFORE uri inside a handle, so that formulation would redirect the UNSTRIPPED URI). FAILS
    IF either map (source, regex, or default) changes, or a shape regresses to a bare handle."""
    section = _section(_fd_text())
    rest_map = _block_after(section, "map {http.request.uri} {ausmt_pathurl_rest} {")
    assert re.search(r"~\^\(\[\^\?\]\*\)\s+\"\$\{1\}\"", rest_map), (
        "the rest map must capture the raw remainder up to the first '?' into ${1}")
    assert re.search(r"default\s+\"\"", rest_map), "the rest map must default to empty"
    qs_map = _block_after(section, "map {http.request.uri} {ausmt_qs} {")
    assert re.search(r"~\\\?\(\.\*\)\$\s+\"\?\$\{1\}\"", qs_map), (
        "the qs map must rebuild '?<query>' from the raw URI's query half")
    assert re.search(r"default\s+\"\"", qs_map), "the qs map must default to empty (no bare '?')"
    for prefix, _frag in _SHAPES:
        assert f"handle /{prefix}/*" not in section, (
            f"/{prefix}/* must use handle_path (a bare handle would redirect unstripped)")
        assert "uri strip_prefix" not in section, (
            "the strip must be handle_path's own, never a uri directive racing redir")


def test_doctor_carries_the_pathurl_leg():
    """doctor.sh source pins for the tier-3 leg: it probes the canonical name's
    /surveys/vulcan-2022 over explicit https with --resolve, demands the landing page's own
    rel=canonical at that exact URL (which proves the pass-through AND that the pages/ product
    served), and skips cleanly when the edge gives no response. The behavioural proof is sh-driven
    in test_frontdoor_doctor_sh.py; these run everywhere. FAILS IF the leg, the pinned slug, the
    canonical requirement, or the clean skip is dropped."""
    src = _DOCTOR.read_text(encoding="utf-8")
    assert 'slug="vulcan-2022"' in src, "the probe slug must be the pinned vulcan-2022"
    assert "https://$name/surveys/$slug" in src, "the leg must probe the path shape over https"
    leg = src.split("check_pathurl_redirect")[1].split("check_tailscale")[0]
    assert "canonical" in leg, "the pathurl leg must demand the landing page's canonical"
    assert "pathurl: skipped" in src, "an unreachable edge must skip cleanly, not FAIL"
    # The two HUB pages ride the SAME pages/ product and the same pass-through. They get their own
    # probes because they are the only tier-3 documents the front door had to STOP redirecting for:
    # a regressed bare-prefix handle would send them to the SPA root and nothing else would notice.
    assert 'for hub in surveys collections' in leg, \
        "the leg must probe both index pages, not only the entity shape"
    assert 'https://$name/$hub' in leg, "the hub probes must use the published bare paths"
    assert 'rel=\\"canonical\\" href=\\"https://$name/$hub\\"' in leg, \
        "each hub probe must demand that page's own canonical at its exact URL"
    # The status, read separately from the body: a reinstated bare-prefix handle answers 301 with
    # NO body, so a body-only probe reads it as an unreachable edge and skips green over the one
    # regression these probes exist for. The contract asks for 200 + rel=canonical; both halves are
    # pinned here so neither can be dropped back to the other.
    assert "%{http_code}" in leg, "the hub probes must read the status, not only the body"
    assert '"$hcode" != "200"' in leg, "any status but 200 must FAIL the hub leg"
    assert '"$hcode" = "000"' in leg, (
        "unreachable must be curl's 000, not an empty body (a 301 body is empty too)")


def test_runbook_documents_the_contract_and_the_tiers():
    """RUNBOOK pins: the three published shapes, tier 3 documented as LIVE with the served landing
    pages and the leak-posture note, tier 2 still documented as deferred with the no-URL-change
    promise, the bare-form and legacy-chain behaviour stated. FAILS IF the runbook loses any of
    them (the published contract must stay findable by the operator, and stale tier narration
    would misdirect an incident response)."""
    rb = _RUNBOOK.read_text(encoding="utf-8")
    for shape in ("/surveys/<slug>", "/stations/<ausmt_id>", "/collections/<id>"):
        assert shape in rb, f"the runbook must name the published shape {shape}"
    assert "Tier 3 (LIVE" in rb, "tier 3 must be documented as the live tier"
    assert "Tier 2 (deferred)" in rb, "tier 2 must remain documented as deferred"
    assert "No published URL changed" in rb and "no published URL changes" in rb, (
        "the runbook must state the URL contract held at tier 3 and holds for tier 2")
    assert "301s to the portal root" in rb, "the bare-form behaviour must be stated"
    assert "rel=canonical" in rb, "the doctor's canonical probe must be stated"
    assert "/surveys" in rb and "/collections" in rb and "index page" in rb, (
        "the runbook must state that the two bare prefixes now SERVE index pages")
    assert "/stations" in rb, "the runbook must state which bare prefix still redirects"


# ==================================================================================================
# Runtime pins: a REAL Caddy over the shipped composition (CI class; textual pins stand in locally)
# ==================================================================================================
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


def _hermetic(text: str, td: Path, listen_port: int, stub_port: int) -> tuple[str, Path]:
    """The same hermetic two-host composition as test_frontdoor_canonical_redirect.py: both site
    blocks bound to ONE local http port (Host-header routing selects the block exactly as SNI/Host
    does in production), the reader pointed at a local stub, the log to a temp file."""
    text = text.replace("{$AUSMT_PUBLIC_NAME} {", f"http://canonical.test:{listen_port} {{")
    text = text.replace("{$AUSMT_LEGACY_REDIRECT_NAME} {", f"http://legacy.test:{listen_port} {{")
    text = text.replace("{$AUSMT_PUBLIC_NAME}", "canonical.test")
    text = text.replace("{$AUSMT_BOX_READER_UPSTREAM}", f"127.0.0.1:{stub_port}")
    text = text.replace("{$AUSMT_ACME_EMAIL}", "test@example.org")
    logpath = td / "access-frontdoor.json"
    text = re.sub(r"output file \S+", f"output file {logpath.as_posix()}", text)
    text = text.replace("admin unix//run/caddy-admin.sock", "admin off")
    # The shipped Caddyfile `import`s the time-series route table at its VPS mount path, so a
    # hermetic composition must repoint it at a real file or the config will not adapt. An EMPTY
    # table is the right stand-in here: this suite is about the walls, not the hand-off routes
    # (deploy/tests/test_frontdoor_ts_routes.py covers those), and an empty table 404s every
    # /go/ts/ path exactly as a deploy publishing no routes does.
    _tsmap = td / "ts-routes.map"
    _tsmap.write_text("# hermetic fixture: no hand-off routes\n", encoding="utf-8")
    text = text.replace("import /etc/caddy/ts-routes.map", f"import {_tsmap.as_posix()}")
    text = text.replace("admin off\n", "admin off\n\tauto_https off\n", 1)
    return text, logpath


def _stub_cfg(port: int) -> str:
    return ("{\n\tadmin off\n\tauto_https off\n}\n"
            + f":{port} {{\n\trespond \"STUB {{http.request.uri}}\" 200\n}}\n")


def _run_caddy(cfg_text: str, td: Path, name: str) -> subprocess.Popen:
    cfgpath = td / f"{name}.caddy"
    cfgpath.write_text(cfg_text, encoding="utf-8")
    v = subprocess.run(["caddy", "validate", "--adapter", "caddyfile", "--config", str(cfgpath)],
                       capture_output=True, text=True)
    assert v.returncode == 0, f"composed {name} config invalid:\n{v.stdout}\n{v.stderr}\n---\n{cfg_text}"
    return subprocess.Popen(["caddy", "run", "--adapter", "caddyfile", "--config", str(cfgpath)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _stop(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _get_noredirect(port: int, path: str, host: str) -> tuple[int, str | None, str]:
    """(status, location-header-or-None, body) WITHOUT following redirects."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={"Host": host})

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):  # noqa: ARG002
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    try:
        r = opener.open(req, timeout=5)
        hdrs = dict(r.headers)
        body = r.read().decode("utf-8", "replace")
        st = r.status
    except urllib.error.HTTPError as e:
        hdrs = dict(e.headers)
        body = e.read().decode("utf-8", "replace")
        st = e.code
    loc = {k.lower(): v for k, v in hdrs.items()}.get("location")
    return st, loc, body


@pytest.fixture()
def edge():
    """A running hermetic edge (shipped composition) + reader stub; yields (port, logpath)."""
    if not _HAS_CADDY:
        pytest.skip("no caddy binary on PATH - runtime pins run in CI (gateway-ci)")
    with tempfile.TemporaryDirectory() as tmp:
        td = Path(tmp)
        stub_port, port = _free_port(), _free_port()
        stub = _run_caddy(_stub_cfg(stub_port), td, "stub")
        cfg, logpath = _hermetic(_fd_text(), td, port, stub_port)
        fd = _run_caddy(cfg, td, "frontdoor-pathurl")
        try:
            _wait_port(stub_port)
            _wait_port(port)
            yield port, logpath
        finally:
            _stop(fd)
            _stop(stub)


@pytest.mark.skipif(not _HAS_CADDY, reason="no caddy binary on PATH - runtime pins run in CI (gateway-ci)")
def test_pathurl_deep_ids_reach_the_reader_path_intact(edge):
    """RUNTIME, the tier-3 contract itself. Each published shape with a real deep id passes
    through to the reader with the path byte-for-byte intact, where the box serves the prerendered
    landing page. FAILS IF any shape redirects again, 404s at the edge, or mangles the path on the
    way to the reader."""
    port, _log = edge
    for path in ("/surveys/vulcan-2022",
                 "/stations/au.vulcan-2022.MBV07",
                 "/collections/auslamp"):
        st, _loc, body = _get_noredirect(port, path, host="canonical.test")
        assert st == 200, f"{path}: must pass through to the reader, got {st}"
        assert body == f"STUB {path}", f"{path}: must reach the reader path-intact, got {body!r}"


@pytest.mark.skipif(not _HAS_CADDY, reason="no caddy binary on PATH - runtime pins run in CI (gateway-ci)")
def test_pathurl_query_rides_through_to_the_reader(edge):
    """RUNTIME, the query decision under tier 3. A decorated link (/surveys/x?<q>) passes through
    with its query intact - the reader's file_server ignores it, so the link neither breaks nor
    loses what its author wrote. FAILS IF the query is stripped or reordered on the way through."""
    port, _log = edge
    st, _loc, body = _get_noredirect(port, "/surveys/vulcan-2022?utm=1&v=1.2", host="canonical.test")
    assert st == 200
    assert body == "STUB /surveys/vulcan-2022?utm=1&v=1.2", body


@pytest.mark.skipif(not _HAS_CADDY, reason="no caddy binary on PATH - runtime pins run in CI (gateway-ci)")
def test_pathurl_bare_stations_lands_on_the_root_and_the_hubs_pass_through(edge):
    """RUNTIME, the no-id rule as it now stands. A bare /stations (both slash forms) 301s to the
    portal root, never to a broken empty-fragment URL, with its query preserved. A bare /surveys or
    /collections passes THROUGH to the reader with the path intact, because the reader serves an
    index page there. FAILS IF stations stops redirecting, or if a hub path is redirected at the
    edge (which would make the served index page unreachable from the public name)."""
    port, _log = edge
    for prefix in _BARE_REDIRECTED:
        for path in (f"/{prefix}", f"/{prefix}/"):
            st, loc, _ = _get_noredirect(port, path, host="canonical.test")
            assert st == 301, f"{path}: must 301, got {st}"
            assert loc == "https://canonical.test/", f"{path}: must land on the root, got {loc!r}"
    st, loc, _ = _get_noredirect(port, "/stations?utm=1", host="canonical.test")
    assert st == 301 and loc == "https://canonical.test/?utm=1", loc
    for prefix in _BARE_PASSTHROUGH:
        for path in (f"/{prefix}", f"/{prefix}/", f"/{prefix}?utm=1"):
            st, loc, body = _get_noredirect(port, path, host="canonical.test")
            assert st == 200 and loc is None, f"{path}: must pass through, got {st} {loc!r}"
            assert body == f"STUB {path}", f"{path}: must reach the reader intact, got {body!r}"


@pytest.mark.skipif(not _HAS_CADDY, reason="no caddy binary on PATH - runtime pins run in CI (gateway-ci)")
def test_pathurl_id_rides_byte_for_byte(edge):
    """RUNTIME, the byte-preservation rule. The mechanism must not decode/re-encode the id: a
    percent-escaped request keeps its escapes in the Location verbatim (published ids are lowercase
    ASCII today, but the mechanism must not normalise), and a trailing slash after an id is
    preserved verbatim too (the published form carries none; nothing is trimmed or added). FAILS IF
    the remainder is decoded, re-encoded, or trimmed."""
    port, _log = edge
    st, _loc, body = _get_noredirect(port, "/stations/au.vulcan%2D2022.MBV07", host="canonical.test")
    assert st == 200
    assert body == "STUB /stations/au.vulcan%2D2022.MBV07", (
        f"the escaped id must reach the reader undecoded, got {body!r}")
    st, _loc, body = _get_noredirect(port, "/surveys/vulcan-2022/", host="canonical.test")
    assert st == 200
    assert body == "STUB /surveys/vulcan-2022/", (
        f"a trailing slash rides verbatim to the reader (which 404s it honestly), got {body!r}")


@pytest.mark.skipif(not _HAS_CADDY, reason="no caddy binary on PATH - runtime pins run in CI (gateway-ci)")
def test_pathurl_legacy_chain_ends_at_the_served_landing_page(edge):
    """RUNTIME, the legacy chain under tier 3. A legacy-name path link takes one 301 (the legacy
    block's host redirect with {uri} preserved, path AND query) and then the canonical host SERVES
    the landing page through the reader. FAILS IF the hop softens, drops the URI, or the chain
    stops short of the reader."""
    port, _log = edge
    st, loc, _ = _get_noredirect(port, "/surveys/vulcan-2022?v=1", host="legacy.test")
    assert st == 301, f"hop 1 must be a 301, got {st}"
    assert loc == "https://canonical.test/surveys/vulcan-2022?v=1", (
        f"hop 1 must preserve the path-shaped URI onto the canonical host, got {loc!r}")
    hop2_path = loc[len("https://canonical.test"):]
    st, _loc2, body = _get_noredirect(port, hop2_path, host="canonical.test")
    assert st == 200, f"hop 2 must serve the landing page through the reader, got {st}"
    assert body == "STUB /surveys/vulcan-2022?v=1", (
        f"the chain must end at the reader with path and query intact, got {body!r}")


@pytest.mark.skipif(not _HAS_CADDY, reason="no caddy binary on PATH - runtime pins run in CI (gateway-ci)")
def test_pathurl_hop_lands_in_the_masked_access_log(edge):
    """RUNTIME, the analytics premise. Unlike the (unlogged) legacy block, the canonical block
    logs, so a tier-1 redirect hop DOES write a masked access-log line; the aggregator's exclusion
    of those 301 lines from every count is pinned in test_aggregate_stats.py. FAILS IF the hop
    stops being logged (the analytics decision would then rest on a false premise)."""
    port, logpath = edge
    _get_noredirect(port, "/surveys/vulcan-2022", host="canonical.test")
    for _ in range(50):
        if logpath.is_file() and logpath.stat().st_size > 0:
            break
        time.sleep(0.1)
    body = logpath.read_text(encoding="utf-8") if logpath.is_file() else ""
    assert "/surveys/vulcan-2022" in body, "the canonical-block redirect hop must be logged"


@pytest.mark.skipif(not _HAS_CADDY, reason="no caddy binary on PATH - runtime pins run in CI (gateway-ci)")
def test_pathurl_redproof_without_the_section_paths_fall_through():
    """RED-PROOF. With the whole path-url section STRIPPED (the pre-change canonical block), a
    /surveys deep link is NOT redirected: it falls through the handles to the reader catch-all and
    REACHES the stub, proving the section is load-bearing rather than decoration. FAILS IF the
    stripped composition still redirects (the pins above would then prove nothing)."""
    with tempfile.TemporaryDirectory() as tmp:
        td = Path(tmp)
        stub_port, port = _free_port(), _free_port()
        stub = _run_caddy(_stub_cfg(stub_port), td, "stub")
        cfg, _log = _hermetic(_strip_section(_fd_text()), td, port, stub_port)
        fd = _run_caddy(cfg, td, "frontdoor-nosection")
        try:
            _wait_port(stub_port)
            _wait_port(port)
            st, loc, body = _get_noredirect(port, "/surveys/vulcan-2022", host="canonical.test")
            assert st == 200 and "STUB /surveys/vulcan-2022" in body and loc is None, (
                "red-proof failed: without the section a path link should fall through to the "
                f"reader stub, got {st} {loc!r} {body!r}")
        finally:
            _stop(fd)
            _stop(stub)
