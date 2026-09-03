"""Canonical-name ruling (2026-08-18): the front door serves BOTH names, one canonical.

`ausmt.auscope.org.au` is the canonical public name; `ausmt.au` is an OPTIONAL legacy name whose only
job is a permanent (301) redirect to the canonical name with path and query preserved. The redirect is
a permanent contract, so this file pins it:

  * the legacy site block redirects with `redir https://{$AUSMT_PUBLIC_NAME}{uri} permanent` (301,
    never 302, `{uri}` carries path AND query);
  * the legacy block is REDIRECT-ONLY: no reverse_proxy, no log, no header directives (deliberately
    no HSTS there: the block is minimal and the canonical site sets HSTS once the client lands);
  * the masked access log lives on the CANONICAL block and ONLY there, so a redirect hop is never
    folded into the usage analytics as a visit;
  * THE EMPTY-VAR TRAP: Caddyfile `{$VAR}` interpolation cannot conditionally omit a site block; an
    unset legacy var leaves a block with an EMPTY address, a parse error, i.e. Caddy fails to start
    on exactly the deploy that has no legacy name. install-frontdoor.sh therefore templates the
    legacy block in or out between two marker lines and mounts the RENDERED file. Both renderings
    are pinned here: var set -> both site blocks; var empty -> exactly one site block and no trace
    of the legacy address.

The textual pins run everywhere (no caddy, no sh). Where a caddy binary is on PATH the renderings are
additionally proven against a REAL Caddy (`caddy validate` both ways, a live 301 with a deep path and
a query string, and a red-proof that the UNRENDERED file with the var unset really is a parse error).
CI installs caddy (gateway-ci.yml), so the runtime legs run there; on a caddy-less dev box the
textual render assertions stand in, same gating as test_frontdoor_bridge.py.
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
_INSTALL = _FRONTDOOR / "install-frontdoor.sh"
_DOCTOR = _FRONTDOOR / "doctor.sh"
_COMPOSE = _FRONTDOOR / "compose.yaml"
_ENV_EXAMPLE = _FRONTDOOR / ".env.example"

_HAS_CADDY = shutil.which("caddy") is not None

_MARK_OPEN = "# >>> legacy-redirect"
_MARK_CLOSE = "# <<< legacy-redirect"


# ==================================================================================================
# Helpers
# ==================================================================================================
def _fd_text() -> str:
    return _FD_CADDY.read_text(encoding="utf-8")


def _strip_legacy(text: str) -> str:
    """The empty-var rendering: delete every line from the opening marker to the closing marker,
    inclusive. This is the SAME range-delete install-frontdoor.sh applies with sed when
    AUSMT_LEGACY_REDIRECT_NAME is unset (sed '/^# >>> legacy-redirect/,/^# <<< legacy-redirect/d'),
    so what these pins prove about the stripped text holds for the shipped renderer's output.
    The sh-driven black-box run of the real script lives in test_install_frontdoor_reload_sh.py."""
    out: list[str] = []
    dropping = False
    for line in text.splitlines(keepends=True):
        if line.startswith(_MARK_OPEN):
            dropping = True
        if not dropping:
            out.append(line)
        if line.startswith(_MARK_CLOSE):
            dropping = False
    return "".join(out)


_PLACEHOLDER_TOKEN = re.compile(r"\{[^{}\s]+\}")


def _site_openers(text: str) -> list[str]:
    """The addresses of every TOP-LEVEL site block: a depth-0 non-comment line ending in '{' whose
    address part is non-empty (the global options block, a bare '{', is excluded). Brace depth is
    tracked over non-comment lines with PLACEHOLDER tokens removed first: `{$ENV}` in comments was
    already excluded, and a directive line like `map {http.request.uri} {dest} {` carries balanced
    placeholder braces beside ONE structural opener, so counting raw braces would inflate the depth
    permanently and hide every later site opener (the path-url contract lane added such lines)."""
    openers: list[str] = []
    depth = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if depth == 0 and line.endswith("{"):
            addr = line[:-1].strip()
            # A parenthesised address is a SNIPPET definition (e.g. `(box_upstream)`, the
            #  shared box transport), not a site block: Caddy expands it at import
            # sites and it binds no listener, so it is not a site opener.
            if addr and not (addr.startswith("(") and addr.endswith(")")):
                openers.append(addr)
        structural = _PLACEHOLDER_TOKEN.sub("", line)
        depth += structural.count("{") - structural.count("}")
    return openers


def _brace_match(text: str, open_at: int) -> str:
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


def _legacy_body(text: str) -> str:
    """The inner body of the legacy site block (without the outer braces)."""
    m = re.search(r"\{\$AUSMT_LEGACY_REDIRECT_NAME\} \{", text)
    assert m, "the Caddyfile must carry a {$AUSMT_LEGACY_REDIRECT_NAME} site block"
    block = _brace_match(text, m.end() - 1)
    return block[1:-1]


# ==================================================================================================
# Textual pins (always run)
# ==================================================================================================
def test_legacy_block_is_marker_delimited():
    """The legacy site block sits ENTIRELY between the two templating markers, so the installer's
    range-delete removes exactly the legacy block and nothing else. FAILS IF a marker is missing,
    duplicated, out of order, or the block leaks outside the marked range."""
    text = _fd_text()
    # LINE-ANCHORED, exactly like the renderer's sed ranges (/^# >>> .../): a mid-line mention of a
    # marker in a comment is inert to sed and must be inert here too.
    opens = [m.start() for m in re.finditer(rf"^{re.escape(_MARK_OPEN)}", text, re.MULTILINE)]
    closes = [m.start() for m in re.finditer(rf"^{re.escape(_MARK_CLOSE)}", text, re.MULTILINE)]
    assert len(opens) == 1, f"exactly one opening marker line, found {len(opens)}"
    assert len(closes) == 1, f"exactly one closing marker line, found {len(closes)}"
    o, c = opens[0], closes[0]
    assert o < c, "the opening marker must precede the closing marker"
    lm = re.search(r"\{\$AUSMT_LEGACY_REDIRECT_NAME\} \{", text)
    assert lm, "the legacy site block must exist"
    block_end = text.index("}", text.index("redir", lm.end()))
    assert o < lm.start() and block_end < c, (
        "the whole legacy block must sit between the markers, or the strip leaves fragments")
    # And the marked range must contain no OTHER site address: stripping it must never remove the
    # canonical block.
    assert "{$AUSMT_PUBLIC_NAME} {" not in text[o:c], (
        "the canonical site block must not be inside the marked range")


def test_legacy_redirect_is_permanent_and_preserves_path_and_query():
    """The redirect is a PERMANENT contract: `redir https://{$AUSMT_PUBLIC_NAME}{uri} permanent`.
    `permanent` renders a 301; a 302/temporary would tell crawlers the move is temporary. `{uri}`
    is Caddy's full request URI, path AND query, so a deep link like
    /data/mtcat.schema.json?x=1 keeps both halves. FAILS IF the status softens, the target host is
    hardcoded, or the `{uri}` passthrough is dropped."""
    body = _legacy_body(_fd_text())
    redirs = [ln.strip() for ln in body.splitlines() if ln.strip().startswith("redir")]
    assert len(redirs) == 1, f"exactly one redir directive expected, got {redirs}"
    assert redirs[0] == "redir https://{$AUSMT_PUBLIC_NAME}{uri} permanent", (
        f"the redirect must be permanent (301) to the canonical placeholder with {{uri}} preserved; "
        f"got {redirs[0]!r}")
    assert "temporary" not in body and " 302" not in body, "the redirect must never be temporary/302"


def test_legacy_block_is_redirect_only():
    """[A3] The legacy block carries NOTHING but the redir: no reverse_proxy (a legacy-name request
    must never reach the reader wall under the legacy identity), no log (see the analytics pin
    below), no header/HSTS (deliberate: the block is minimal; HSTS is the canonical site's job).
    FAILS IF any directive beyond the single redir appears."""
    body = _legacy_body(_fd_text())
    directives = [ln.strip().split()[0] for ln in body.splitlines()
                  if ln.strip() and not ln.strip().startswith("#")]
    assert directives == ["redir"], (
        f"the legacy block must contain exactly one directive (redir), got {directives}")


def test_only_the_canonical_block_logs():
    """ANALYTICS INVARIANT: the masked access log is taken on the CANONICAL block and only there. A
    log directive on the legacy block would fold every redirect hop into the usage analytics as a
    visit, double-counting every legacy hit. FAILS IF the file gains a second log block or the
    canonical one moves/disappears."""
    text = _fd_text()
    log_opens = [m.start() for m in re.finditer(r"^\tlog \{", text, re.MULTILINE)]
    assert len(log_opens) == 1, f"exactly ONE site-level log block expected, found {len(log_opens)}"
    # ... and it sits inside the canonical block, before the legacy marker range begins.
    canon = text.index("{$AUSMT_PUBLIC_NAME} {")
    assert canon < log_opens[0] < text.index(_MARK_OPEN), (
        "the one log block must live inside the canonical site block")
    assert "log" not in [ln.strip().split()[0] for ln in _legacy_body(text).splitlines()
                         if ln.strip() and not ln.strip().startswith("#")], (
        "the legacy block must not log")


def test_empty_var_rendering_has_exactly_one_site_block():
    """[A2] The empty-var rendering (the marker range deleted, exactly what install-frontdoor.sh
    does when AUSMT_LEGACY_REDIRECT_NAME is unset) must leave a config with EXACTLY ONE site block,
    the canonical one, and no trace of the legacy placeholder. An empty-address block would be a
    Caddy parse error on exactly the deploy that has no legacy name. FAILS IF the strip leaves a
    second (or empty-address) site block or any legacy reference behind."""
    stripped = _strip_legacy(_fd_text())
    openers = _site_openers(stripped)
    assert openers == ["{$AUSMT_PUBLIC_NAME}"], (
        f"the empty-var rendering must contain exactly the canonical site block, got {openers}")
    assert "AUSMT_LEGACY_REDIRECT_NAME" not in stripped, (
        "no legacy-name reference may survive the empty-var rendering")


def test_set_var_rendering_has_both_site_blocks_canonical_first():
    """[A2] The set-var rendering (the shipped file as-is) carries BOTH site blocks: the canonical
    reader block first, then the legacy redirect block. FAILS IF either address disappears or the
    order flips (the canonical block is the one the bridge tests brace-match first)."""
    openers = _site_openers(_fd_text())
    assert openers == ["{$AUSMT_PUBLIC_NAME}", "{$AUSMT_LEGACY_REDIRECT_NAME}"], (
        f"expected canonical then legacy site blocks, got {openers}")


def test_installer_templates_and_validates_the_rendered_file():
    """install-frontdoor.sh owns the rendering: it must strip the marker range when the legacy var
    is unset (the exact sed range-delete the textual pins model), write Caddyfile.rendered, validate
    THAT file, pass the legacy var through to validate, and name both hostnames in its closing log
    line. The black-box run of the real script lives in test_install_frontdoor_reload_sh.py (POSIX
    sh); these source pins run everywhere. FAILS IF the render step, the rendered-file validate, or
    the env passthrough is dropped."""
    src = _INSTALL.read_text(encoding="utf-8")
    assert "sed '/^# >>> legacy-redirect/,/^# <<< legacy-redirect/d'" in src, (
        "the installer must strip the marker range when the legacy var is unset")
    assert "Caddyfile.rendered" in src, "the installer must write the rendered Caddyfile"
    assert "Caddyfile.rendered:/etc/caddy/Caddyfile:ro" in src, (
        "caddy validate must run over the RENDERED file, not the tracked template")
    assert "-e AUSMT_LEGACY_REDIRECT_NAME" in src, (
        "validate must receive the legacy var so the set-var rendering resolves")
    assert "AUSMT_LEGACY_REDIRECT_NAME:-" in src, (
        "the legacy var is OPTIONAL: the installer must default it to empty, never die on it")


def test_compose_mounts_the_rendered_file_and_surfaces_the_legacy_var():
    """The container must serve the RENDERED Caddyfile (the tracked template would hit the empty-var
    parse error) and must receive AUSMT_LEGACY_REDIRECT_NAME with an empty default (optional, unlike
    the three required vars). FAILS IF the mount reverts to the tracked file or the var becomes
    required."""
    compose = _COMPOSE.read_text(encoding="utf-8")
    assert "./Caddyfile.rendered:/etc/caddy/Caddyfile:ro" in compose, (
        "compose must mount the rendered Caddyfile")
    assert "./Caddyfile:/etc/caddy/Caddyfile" not in compose, (
        "the tracked template must NOT be mounted directly (empty-var parse error)")
    assert re.search(r"AUSMT_LEGACY_REDIRECT_NAME:\s*\$\{AUSMT_LEGACY_REDIRECT_NAME:-\}", compose), (
        "the legacy var must be surfaced with an empty default (optional)")
    gitignore = (_REPO / "deploy" / ".gitignore").read_text(encoding="utf-8")
    assert "Caddyfile.rendered" in gitignore, (
        "the rendered file is a deploy artifact and must be gitignored")


def test_env_example_documents_both_names():
    """.env.example is the one config point: the canonical example is the AuScope name and the
    legacy var is documented as OPTIONAL with the ausmt.au example. FAILS IF either name example or
    the optional wording disappears."""
    env = _ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "AUSMT_PUBLIC_NAME=ausmt.auscope.org.au" in env, (
        "the canonical example must be the AuScope name")
    assert "AUSMT_LEGACY_REDIRECT_NAME" in env, "the legacy var must be documented"
    assert "AUSMT_LEGACY_REDIRECT_NAME=ausmt.au" in env, "the legacy example must be ausmt.au"
    assert re.search(r"(?i)optional", env), "the legacy var must be documented as optional"


def test_doctor_renders_before_hash_compare_and_checks_the_legacy_legs():
    """doctor.sh source pins: the running-config check must hash the container file against a FRESH
    render of the repo template (same marker strip), and the legacy legs must exist: a certificate
    check for the legacy name that FAILS (not warns) when missing, and an explicit HTTPS 301 leg
    (an https:// URL, so Caddy's automatic HTTP->HTTPS hop cannot be what passes). The behavioural
    proof is the sh-driven test_frontdoor_doctor_sh.py; these run everywhere. FAILS IF the render,
    either leg, or the https scheme is dropped."""
    src = _DOCTOR.read_text(encoding="utf-8")
    assert "sed '/^# >>> legacy-redirect/,/^# <<< legacy-redirect/d'" in src, (
        "the doctor must fresh-render the repo template for the hash compare")
    assert 'https://$legacy' in src, "the redirect leg must probe an explicit https:// URL"
    assert "/data/mtcat.schema.json" in src, (
        "the redirect leg must probe the old schema $id path, proving it keeps resolving")
    assert '"301"' in src, "the redirect leg must require a 301, not any redirect"
    assert "tls-legacy" in src, "the legacy certificate leg must exist"


# ==================================================================================================
# Runtime pins: a REAL Caddy over both renderings (run in CI; caddy-less boxes use the pins above)
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
    """A hermetic two-host composition of a RENDERING: resolve the name placeholders to test
    hostnames, bind both site blocks to ONE local port as http:// hosts (auto_https off, no ACME),
    point the reader at a local stub, and write the access log to a temp file. Host-header routing
    then selects the block, exactly as SNI/Host does in production."""
    text = text.replace("{$AUSMT_PUBLIC_NAME} {", f"http://canonical.test:{listen_port} {{")
    text = text.replace("{$AUSMT_LEGACY_REDIRECT_NAME} {", f"http://legacy.test:{listen_port} {{")
    # The redir target keeps its https:// scheme and now names the canonical test host.
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


def _get_noredirect(port: int, path: str, host: str) -> tuple[int, dict]:
    """GET without following redirects: urllib raises HTTPError on 3xx when no handler follows it
    (it only auto-follows via HTTPRedirectHandler on the default opener; a 301 to an https:// target
    on a dead port would error anyway, so catching the HTTPError IS the no-follow path here)."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={"Host": host})

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):  # noqa: ARG002
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    try:
        r = opener.open(req, timeout=5)
        return r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers)


@pytest.mark.skipif(not _HAS_CADDY, reason="no caddy binary on PATH - runtime pins run in CI (gateway-ci)")
def test_caddy_validates_both_renderings():
    """[A2] RUNTIME. A real `caddy validate` accepts BOTH renderings: the set-var rendering (both
    blocks, placeholders resolved) and the empty-var rendering (legacy block stripped). FAILS IF
    either rendering is rejected."""
    with tempfile.TemporaryDirectory() as tmp:
        td = Path(tmp)
        port, stub = _free_port(), _free_port()
        for name, text in (("both", _fd_text()), ("stripped", _strip_legacy(_fd_text()))):
            cfg, _ = _hermetic(text, td, port, stub)
            p = td / f"validate-{name}.caddy"
            p.write_text(cfg, encoding="utf-8")
            v = subprocess.run(["caddy", "validate", "--adapter", "caddyfile", "--config", str(p)],
                               capture_output=True, text=True)
            assert v.returncode == 0, f"{name} rendering must validate:\n{v.stdout}\n{v.stderr}"


@pytest.mark.skipif(not _HAS_CADDY, reason="no caddy binary on PATH - runtime pins run in CI (gateway-ci)")
def test_unrendered_file_with_unset_var_is_a_parse_error():
    """[A2] RED-PROOF, the trap itself. The UNRENDERED template with AUSMT_LEGACY_REDIRECT_NAME
    unset leaves a site block with an EMPTY address, and a real Caddy must REJECT it. This is why
    the installer templates: were this to pass, the templating would be decoration. FAILS IF Caddy
    accepts the empty-address block."""
    import os
    with tempfile.TemporaryDirectory() as tmp:
        td = Path(tmp)
        # Resolve everything EXCEPT the legacy placeholder textually, then let caddy expand the
        # unset {$AUSMT_LEGACY_REDIRECT_NAME} to empty at parse time, exactly as on a real deploy.
        text = _fd_text()
        logpath = td / "access.json"
        text = re.sub(r"output file \S+", f"output file {logpath.as_posix()}", text)
        text = text.replace("admin unix//run/caddy-admin.sock", "admin off")
        p = td / "unrendered.caddy"
        p.write_text(text, encoding="utf-8")
        env = dict(os.environ)
        env.update({"AUSMT_PUBLIC_NAME": "canonical.test",
                    "AUSMT_BOX_READER_UPSTREAM": "127.0.0.1:9",
                    "AUSMT_ACME_EMAIL": "test@example.org"})
        env.pop("AUSMT_LEGACY_REDIRECT_NAME", None)
        v = subprocess.run(["caddy", "validate", "--adapter", "caddyfile", "--config", str(p)],
                           capture_output=True, text=True, env=env)
        assert v.returncode != 0, (
            "red-proof failed: the unrendered template with the legacy var unset should be a parse "
            "error (empty site address); if Caddy now accepts it, the templating premise changed")


@pytest.mark.skipif(not _HAS_CADDY, reason="no caddy binary on PATH - runtime pins run in CI (gateway-ci)")
def test_legacy_301_preserves_deep_path_and_query_and_writes_no_log():
    """RUNTIME, the redirect contract end-to-end. Against the set-var rendering: a legacy-host
    request to a DEEP path with a QUERY STRING (including the old schema $id path
    /data/mtcat.schema.json) answers 301 with Location carrying the SAME path and query on the
    canonical name; the redirect hop writes NO access-log line (analytics invariant), while a
    canonical-host request does. FAILS IF the status is not 301, either half of the URI is dropped,
    or the legacy hop lands in the log."""
    with tempfile.TemporaryDirectory() as tmp:
        td = Path(tmp)
        stub_port, port = _free_port(), _free_port()
        stub = _run_caddy(_stub_cfg(stub_port), td, "stub")
        cfg, logpath = _hermetic(_fd_text(), td, port, stub_port)
        fd = _run_caddy(cfg, td, "frontdoor-two-names")
        try:
            _wait_port(stub_port)
            _wait_port(port)
            for path in ("/data/mtcat.schema.json?v=1.2&fmt=json",
                         "/data/bundles/vulcan-2022-edi.zip?src=paper",
                         "/data/mtcat.schema.json",
                         "/"):
                st, hdrs = _get_noredirect(port, path, host="legacy.test")
                assert st == 301, f"{path}: the legacy hop must be a 301, got {st}"
                loc = {k.lower(): v for k, v in hdrs.items()}.get("location")
                assert loc == f"https://canonical.test{path}", (
                    f"{path}: Location must carry the same path and query on the canonical name, "
                    f"got {loc!r}")
            # Analytics invariant: the legacy hops above wrote NOTHING to the access log ...
            assert not (logpath.is_file() and logpath.stat().st_size > 0), (
                "a legacy redirect hop must not produce an access-log line")
            # ... while a canonical-host request does.
            st, _ = _get_noredirect(port, "/some/reader/path", host="canonical.test")
            assert st in (200, 404)
            for _ in range(50):
                if logpath.is_file() and logpath.stat().st_size > 0:
                    break
                time.sleep(0.1)
            assert logpath.is_file() and logpath.stat().st_size > 0, (
                "a canonical-host request must produce a masked access-log line")
        finally:
            _stop(fd)
            _stop(stub)
