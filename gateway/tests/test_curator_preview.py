"""Preview sandbox (design §7/§8): the biggest new attack surface.

Guards under test, each with a stated failure criterion + proven-failing evidence:
- iframe isolation: the detail page frames the preview with sandbox="allow-scripts" and NOT
  allow-same-origin (null origin — submitter JS cannot read the curator session/DOM); there is NO
  unsandboxed top-level navigation to the preview.
- path containment: `..`/absolute under /preview/{id}/ => 404 (fails if a traversal served a file
  outside preview-data).
- id-authorized (revised §7): a VALID submission id serves the embargo-safe preview WITHOUT a
  session (the null-origin iframe can't send the cookie); a nonexistent id => 404.
- strict CSP + nosniff on every served asset (fails if the CSP/nosniff header was absent).
- only allow-listed content types are served.
"""
from __future__ import annotations

import re

from gateway.tests.conftest import app_client, curator_login, run, seed_validated


def test_preview_iframe_is_null_origin_sandboxed(tmp_path):
    # review #8 / design §7: the iframe must be sandbox="allow-scripts" WITHOUT allow-same-origin
    # (opaque origin — the framed submitter JS cannot read the curator cookie/DOM or make credentialed
    # same-origin requests). Failure criterion: fails if allow-same-origin is present, or allow-scripts
    # is absent. proven failing 2026-07-06: the first pass had the tokens INVERTED
    # (sandbox="allow-same-origin", no allow-scripts) — same origin as the curator AND broken render.
    async def _body():
        async with app_client(tmp_path) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg)
            await curator_login(client)
            page = (await client.get(f"/gateway/curator/submission/{sid}")).text
            m = re.search(r'<iframe[^>]*\bsandbox="([^"]*)"', page)
            assert m is not None, "no sandboxed iframe in the detail page"
            tokens = m.group(1).split()
            assert "allow-scripts" in tokens, "iframe must allow-scripts so the portal renders"
            assert "allow-same-origin" not in tokens, (
                "iframe MUST NOT allow-same-origin — that puts submitter JS in the curator origin")
    run(_body())


def test_no_unsandboxed_navigation_to_preview(tmp_path):
    # review #8 / design §7: there must be NO anchor/link that top-level-navigates to the preview
    # (that would run submitter JS in the curator origin, escaping the frame). Failure criterion:
    # fails if the detail page contains an <a href> pointing at /preview/. proven failing 2026-07-06:
    # the first pass had an "open preview in a new tab" link (a target=_blank same-origin nav).
    async def _body():
        async with app_client(tmp_path) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg)
            await curator_login(client)
            page = (await client.get(f"/gateway/curator/submission/{sid}")).text
            # No <a ... href="...preview...">. The preview appears ONLY as an iframe src.
            anchors = re.findall(r'<a\b[^>]*href="([^"]*)"', page)
            assert not any("/preview/" in href for href in anchors), (
                "an anchor navigates to the preview — that escapes the sandbox")
    run(_body())


def test_preview_authorized_by_id_not_session(tmp_path):
    # Revised design §7: the preview SUBTREE is authorized by the unguessable submission id in the
    # path, NOT the curator session — because the null-origin sandboxed iframe that embeds it cannot
    # send the cookie (a session gate would 401 the preview's own subresource fetches, so it would
    # never render). Failure criterion: fails if a VALID id does NOT serve the preview without a
    # session, OR if a nonexistent (valid-charset) id serves anything.
    async def _body():
        from gateway import db as db_mod
        async with app_client(tmp_path) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg)
            # No login: a valid id serves the (embargo-safe, PII-scrubbed) preview.
            r = await client.get(f"/gateway/curator/preview/{sid}/index.html")
            assert r.status_code == 200
            assert "preview shell" in r.text
            csp = r.headers.get("content-security-policy", "")
            assert "default-src 'self'" in csp
            assert r.headers.get("x-content-type-options") == "nosniff"
            assert r.headers.get("cache-control") == "no-store"
            # A valid-charset id that resolves to NO submission serves nothing (404) — the id must be
            # real, not just well-formed, so a random ULID guess reveals nothing.
            ghost = db_mod.new_id()
            g = await client.get(f"/gateway/curator/preview/{ghost}/index.html")
            assert g.status_code == 404
    run(_body())


def test_path_traversal_is_404(tmp_path):
    # Failure criterion: fails if a `..` sub-path escapes preview-data and serves a file (e.g. the
    # submission's own validate.json a level up, or worse).
    # proven failing 2026-07-06: before the resolve()+containment check, /preview/{id}/../validate.json
    # resolved to reports/validate.json (outside preview-data) and was served 200.
    async def _body():
        async with app_client(tmp_path) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg)
            await curator_login(client)
            # A parent-escape sub-path. httpx would normalise a literal .. in the URL, so drive the
            # ASGI app with an already-decoded path via the raw request to prove the server-side
            # containment (not the client's normalisation) is what stops it.
            for attempt in ("..%2f..%2fvalidate.json", "..%2fvalidate.json"):
                r = await client.get(f"/gateway/curator/preview/{sid}/{attempt}")
                assert r.status_code == 404, f"traversal {attempt!r} was not contained"
            # A file that genuinely does not exist under preview-data is also 404.
            r = await client.get(f"/gateway/curator/preview/{sid}/nope.html")
            assert r.status_code == 404
    run(_body())


def test_invalid_id_is_404(tmp_path):
    # An id outside the Crockford charset never reaches a path (design §3/§7). Failure criterion:
    # fails if a non-charset id (with separators) was used to build a filesystem path.
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get("/gateway/curator/preview/not-a-valid-id/index.html")
            assert r.status_code == 404
            r2 = await client.get("/gateway/curator/submission/..%2f..%2fetc")
            assert r2.status_code in (404, 400)
    run(_body())


def test_unlisted_content_type_refused(tmp_path):
    # A file with an extension outside the allow-list is 404 rather than served with a guessed type
    # (design §7). Failure criterion: fails if a .exe/.bin under preview-data is served.
    async def _body():
        async with app_client(tmp_path) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg)
            preview = cfg.quarantine_dir / sid / "reports" / "preview-data"
            (preview / "payload.exe").write_bytes(b"MZ...")
            await curator_login(client)
            r = await client.get(f"/gateway/curator/preview/{sid}/payload.exe")
            assert r.status_code == 404
    run(_body())
