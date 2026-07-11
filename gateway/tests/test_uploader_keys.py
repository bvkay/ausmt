"""Uploader keys (schema v2, feat/uploader-key-management): DB-backed, curator-managed submit keys.

The lane moves the single shared AUSMT_SUBMIT_KEY out of env-only into the gateway's SQLite so a
curator with no shell can issue and revoke keys through the authenticated UI. This file proves both
halves against independent observables:

  submit-auth  — the env key still authorises (bootstrap/CI unchanged); a freshly-created DB key
                 authorises AND stamps last_used_utc; a revoked key is rejected; an unknown key is
                 rejected — all with the SAME 401 the wrong-env-key path returns (no oracle).
  curator UI   — create returns the plaintext ONCE and the list page never shows it; a duplicate name
                 is refused; both POSTs require CSRF; the page 401s without a session; create/revoke
                 leave an audit record (created_by/revoked_by); the uploader email never leaks to the
                 public status page.

Failing-first evidence is in each test's docstring. Async bodies run under conftest.run() (no
pytest-asyncio), the established gateway pattern.
"""
from __future__ import annotations

import hashlib

from gateway import uploader_keys
from gateway.tests.conftest import (
    CURATOR_NAME, SUBMIT_KEY, app_client, csrf_for_session, curator_login,
    good_package_zip, run, scanner_clean, submit_zip,
)


# ---- key-mint / hash unit contract -------------------------------------------------------------

def test_mint_key_shape_and_hash_is_sha256():
    """A minted key carries the ausmt_up_ prefix and hashes to the sha256 hex digest of its own bytes
    (the only stored form). Fails if the prefix or the hash function drifts from the C10 token pattern."""
    key = uploader_keys.mint_key()
    assert key.startswith("ausmt_up_")
    assert uploader_keys.key_hash(key) == hashlib.sha256(key.encode("utf-8")).hexdigest()
    assert uploader_keys.mint_key() != uploader_keys.mint_key()  # random each time


# ---- submit auth: env key path unchanged -------------------------------------------------------

def test_env_submit_key_still_authorises(tmp_path):
    """The env AUSMT_SUBMIT_KEY authorises a submit exactly as before (bootstrap + CI e2e path). Fails
    if moving keys into the DB broke the env path the deploy-images e2e legs depend on."""
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, _gw, _cfg):
            r = await submit_zip(client, good_package_zip(), key=SUBMIT_KEY)
            assert r.status_code == 201
    run(_body())


# ---- submit auth: DB key path ------------------------------------------------------------------

def _issue_key(gw, *, name="uploader-a", email="up@example.org", by=CURATOR_NAME) -> tuple[str, int]:
    key = uploader_keys.mint_key()
    kid = gw.db.create_uploader_key(
        name=name, email=email, key_sha256=uploader_keys.key_hash(key), created_by=by)
    return key, kid


def test_db_key_authorises_and_stamps_last_used(tmp_path):
    """A freshly-created DB uploader key authorises a submit AND its last_used_utc is stamped. Fails if
    a DB key cannot submit, or if a successful DB-key submit does not record last_used_utc (the only
    per-key usage signal a shell-less curator has)."""
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, gw, _cfg):
            key, kid = _issue_key(gw)
            assert gw.db.get_active_uploader_key_by_hash(uploader_keys.key_hash(key)).last_used_utc is None
            r = await submit_zip(client, good_package_zip(), key=key)
            assert r.status_code == 201
            row = gw.db.list_uploader_keys()[0]
            assert row.id == kid
            assert row.last_used_utc is not None, "successful DB-key submit must stamp last_used_utc"
    run(_body())


def test_db_key_upload_records_uploader_in_audit_trail(tmp_path):
    """A DB-key submit attributes the upload to the named uploader in the submission's audit trail
    (the opening transition reason), following how submitter_name is recorded. Fails if the uploader
    name is not attributable from the audit log."""
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, gw, _cfg):
            key, _kid = _issue_key(gw, name="named-uploader")
            r = await submit_zip(client, good_package_zip(), key=key)
            assert r.status_code == 201
            sid = r.json()["submission_id"]
            opening = gw.db.transitions_for(sid)[0]
            assert "named-uploader" in (opening["reason"] or "")
    run(_body())


def test_revoked_key_rejected_same_as_wrong_env(tmp_path):
    """A revoked DB key is rejected with the SAME 401 body as a wrong env key — no oracle for which
    failure it was. Fails if a revoked key still authorises, or if its rejection differs from the
    wrong-key rejection."""
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, gw, _cfg):
            key, kid = _issue_key(gw)
            assert gw.db.revoke_uploader_key(kid, revoked_by=CURATOR_NAME) is True
            revoked = await submit_zip(client, good_package_zip(), key=key)
            wrong_env = await submit_zip(client, good_package_zip(), key="definitely-not-a-key-123456")
            assert revoked.status_code == 401
            assert revoked.status_code == wrong_env.status_code
            assert revoked.content == wrong_env.content  # byte-identical: no oracle
    run(_body())


def test_unknown_key_rejected(tmp_path):
    """A key that was never issued is rejected 401 (neither the env key nor any DB row). Fails if an
    unknown key is somehow accepted."""
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, _gw, _cfg):
            r = await submit_zip(client, good_package_zip(), key="ausmt_up_never-issued-000000000000")
            assert r.status_code == 401
    run(_body())


def test_db_unavailable_during_auth_fails_closed(tmp_path):
    """Fail-closed: if the DB lookup raises during a non-env-key auth, the submit is REJECTED, never
    silently bypassed. Fails if a DB error opens an auth hole (accepts, or 500-with-side-effects)."""
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, gw, _cfg):
            def _boom(_h):
                raise RuntimeError("db down")
            gw.db.get_active_uploader_key_by_hash = _boom  # type: ignore[method-assign]
            r = await submit_zip(client, good_package_zip(), key="ausmt_up_some-presented-key-000000")
            assert r.status_code == 401
    run(_body())


# ---- curator UI: list / create / revoke --------------------------------------------------------

def test_uploaders_page_401s_without_session(tmp_path):
    """GET /gateway/curator/uploaders without a curator session does not render the list — it
    redirects to login (303) like the other session-gated GET pages. Fails if the page is reachable
    unauthenticated."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, _cfg):
            r = await client.get("/gateway/curator/uploaders", follow_redirects=False)
            assert r.status_code in (303, 401)
    run(_body())


def test_create_returns_plaintext_once_then_never_listed(tmp_path):
    """Create shows the plaintext key ONCE with 'cannot be retrieved' wording; the list page shows the
    name/email/status but NEVER the plaintext or its hash. Fails if the plaintext is retrievable from
    the list (the whole show-once contract)."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, gw, _cfg):
            await curator_login(client)
            created = await client.post(
                "/gateway/curator/uploaders/create",
                data={"name": "field-team-1", "email": "field@example.org",
                      "csrf_token": csrf_for_session(client)},
                follow_redirects=False)
            assert created.status_code == 200
            # The one-time plaintext appears with a cannot-retrieve reminder.
            import re
            m = re.search(r"ausmt_up_[A-Za-z0-9_-]+", created.text)
            assert m is not None, "the plaintext key must be shown once on creation"
            plaintext = m.group(0)
            assert "cannot" in created.text.lower() and "revoke" in created.text.lower()
            # The list never carries the plaintext OR its hash.
            listing = await client.get("/gateway/curator/uploaders")
            assert listing.status_code == 200
            assert "field-team-1" in listing.text
            assert plaintext not in listing.text
            assert uploader_keys.key_hash(plaintext) not in listing.text
    run(_body())


def test_create_audit_records_curator(tmp_path):
    """Creation records the creating curator (created_by) — the in-table audit record for this table.
    Fails if create does not attribute the curator."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, gw, _cfg):
            await curator_login(client)
            r = await client.post(
                "/gateway/curator/uploaders/create",
                data={"name": "audit-me", "csrf_token": csrf_for_session(client)},
                follow_redirects=False)
            assert r.status_code == 200
            row = next(k for k in gw.db.list_uploader_keys() if k.name == "audit-me")
            assert row.created_by == CURATOR_NAME
    run(_body())


def test_duplicate_name_rejected(tmp_path):
    """A second create with an existing name is refused with a clear message and does NOT create a
    second row. Fails if a duplicate name silently creates a second key (ambiguous attribution)."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, gw, _cfg):
            await curator_login(client)
            csrf = csrf_for_session(client)
            first = await client.post("/gateway/curator/uploaders/create",
                                      data={"name": "dupe", "csrf_token": csrf},
                                      follow_redirects=False)
            assert first.status_code == 200
            second = await client.post("/gateway/curator/uploaders/create",
                                       data={"name": "dupe", "csrf_token": csrf},
                                       follow_redirects=False)
            assert second.status_code == 409
            assert "already" in second.text.lower() or "exist" in second.text.lower()
            assert len([k for k in gw.db.list_uploader_keys() if k.name == "dupe"]) == 1
    run(_body())


def test_create_requires_csrf(tmp_path):
    """Create without a valid CSRF token is 403 and creates nothing. Fails if a cross-site form can
    mint a key."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, gw, _cfg):
            await curator_login(client)
            r = await client.post("/gateway/curator/uploaders/create",
                                  data={"name": "no-csrf", "csrf_token": "wrong"},
                                  follow_redirects=False)
            assert r.status_code == 403
            assert [k for k in gw.db.list_uploader_keys() if k.name == "no-csrf"] == []
    run(_body())


def test_revoke_requires_csrf(tmp_path):
    """Revoke without a valid CSRF token is 403 and the key stays active. Fails if a cross-site form
    can revoke a key."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, gw, _cfg):
            await curator_login(client)
            _key, kid = _issue_key(gw)
            r = await client.post(f"/gateway/curator/uploaders/{kid}/revoke",
                                  data={"csrf_token": "wrong"}, follow_redirects=False)
            assert r.status_code == 403
            assert gw.db.list_uploader_keys()[0].active is True
    run(_body())


def test_revoke_sets_revoked_by_and_stays_listed(tmp_path):
    """Revoke sets revoked_utc/revoked_by (audit) and the row STAYS listed (no delete). Fails if a
    revoked key vanishes from the audit trail or is not attributed to the revoking curator."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, gw, _cfg):
            await curator_login(client)
            _key, kid = _issue_key(gw)
            r = await client.post(f"/gateway/curator/uploaders/{kid}/revoke",
                                  data={"csrf_token": csrf_for_session(client)},
                                  follow_redirects=False)
            assert r.status_code == 303
            row = gw.db.list_uploader_keys()[0]
            assert row.active is False
            assert row.revoked_by == CURATOR_NAME
            assert row.revoked_utc is not None
            listing = await client.get("/gateway/curator/uploaders")
            assert row.name in listing.text  # still shown for the audit trail
    run(_body())


def test_uploader_email_absent_from_public_status(tmp_path):
    """The uploader email is curator-only PII (same confinement as submitter email): it must never
    appear on the public status page. Fails if issuing a key with an email leaks it to /status."""
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, gw, _cfg):
            unique = "uploader-canary-5521@example.test"
            key, _kid = _issue_key(gw, name="canary-team", email=unique)
            r = await submit_zip(client, good_package_zip(), key=key)
            assert r.status_code == 201
            status = await client.get(r.json()["status_url"])
            assert status.status_code == 200
            assert unique not in status.text
    run(_body())


# ---- H2 (C43-S2a-HOTFIX): keys-page layout — full width, short datetimes, usable note editor ----
# Owner feedback (live box, 2026-07-11): "use the full width of the page, to spread out the issued
# keys table to make it easier to tell what is going on." The shipped page rendered inside the
# shell's 960px .wrap: the note textarea was a few characters wide and the Created/Last-used ISO
# datetimes wrapped over three lines.

def _nav():
    from gateway.curatorpage import NavContext
    return NavContext(active="uploaders", crumb="<b>Uploader keys</b>", published_head=None,
                      published_available=False, csrf="test-csrf-token")


def test_short_utc_canonical_and_verbatim_fallback():
    """H2 PIN (display shortener contract, the S2a-5 build-id posture). db._utc_now's canonical
    '%Y-%m-%dT%H:%M:%SZ' shape renders as 'YYYY-MM-DD HH:MM' (date + minutes); ANY other shape is
    returned VERBATIM, never mangled. FAILS IF the canonical form stops shortening (the three-line
    wrap comes back) or a non-canonical value is truncated/emptied (audit data silently lost)."""
    from gateway.curatorpage import short_utc
    assert short_utc("2026-07-08T07:49:12Z") == "2026-07-08 07:49"
    assert short_utc("2026-12-31T23:59:59Z") == "2026-12-31 23:59"
    # VERBATIM fallback — never mangled, never emptied.
    for odd in ("not-a-timestamp", "2026-07-08 07:49:12", "2026-07-08T07:49:12+00:00",
                "2026-07-08T07:49:12", ""):
        assert short_utc(odd) == odd, f"non-canonical {odd!r} must pass through verbatim"


def test_keys_page_wide_layout_short_datetimes_and_note_width():
    """H2 RENDER PIN. The rendered keys page carries (a) the wide-layout marker on its content wrap
    (the per-page variant — the shell's 960px measure is untouched elsewhere), (b) every stored
    datetime in the short 'YYYY-MM-DD HH:MM' form with the FULL ISO in a title attribute (hover
    keeps the audit precision; the cell stops wrapping over three lines), (c) a usable note editor
    (34ch textarea) that KEEPS the 2000 cap, and (d) no inline JS (CSP discipline unchanged).
    FAILS IF the wide marker is dropped, a raw ISO renders as visible cell text again, the title
    loses the full ISO, the textarea loses its width or its cap, or inline JS appears."""
    from gateway.curatorpage import render_uploaders
    from gateway.db import UploaderKey
    active = UploaderKey(id=1, name="field-team-1", email="ft1@example.org", key_sha256="h" * 64,
                         created_utc="2026-07-08T07:49:12Z", created_by="ben",
                         revoked_utc=None, revoked_by=None,
                         last_used_utc="2026-07-10T23:05:59Z", note=None)
    fresh = UploaderKey(id=2, name="fresh-key", email=None, key_sha256="h" * 64,
                        created_utc="2026-07-09T00:00:01Z", created_by="ben",
                        revoked_utc=None, revoked_by=None, last_used_utc=None, note=None)
    revoked = UploaderKey(id=3, name="old-key", email=None, key_sha256="h" * 64,
                          created_utc="2026-01-02T03:04:05Z", created_by="ben",
                          revoked_utc="2026-06-30T11:22:33Z", revoked_by="ben",
                          last_used_utc="2026-06-01T10:00:00Z", note="retired")
    html = render_uploaders(curator_name="ben", keys=[active, fresh, revoked],
                            csrf_token="tok", submission_counts={"field-team-1": 2}, nav=_nav())
    # (a) the wide-layout marker, on the content wrap.
    assert '<div class="wrap wide">' in html, "keys page must opt into the wide layout"
    # (b) short form + full-ISO title for created / last-used / revoked timestamps.
    for full, short in (("2026-07-08T07:49:12Z", "2026-07-08 07:49"),      # created (active)
                        ("2026-07-10T23:05:59Z", "2026-07-10 23:05"),      # last used (active)
                        ("2026-06-30T11:22:33Z", "2026-06-30 11:22")):     # revoked-at
        assert f'title="{full}"' in html, f"full ISO {full} must ride in a title attribute"
        assert f">{short}<" in html, f"short form {short} must be the visible text"
        assert f">{full}<" not in html, f"raw ISO {full} must not render as visible cell text"
    assert "never" in html  # a never-used key still says so in Last used
    # (c) the note editor is usable and still capped.
    assert "width:34ch" in html, "the note textarea must carry a usable width"
    assert 'maxlength="2000"' in html, "the 2000-char note cap must survive the layout change"
    # (d) CSP discipline: no inline <script>, no on*= handler in the rendered bytes.
    import re
    for m in re.finditer(r"<script\b[^>]*>", html):
        assert re.search(r"\bsrc\s*=", m.group(0)), f"inline <script> on the keys page: {m.group(0)}"
    assert re.findall(r"<[^>]*\son[a-z]{2,}\s*=", html) == [], "inline handler on the keys page"


def test_wide_layout_is_keys_page_only():
    """H2 SCOPE PIN (owner: widen the keys page, 'do not silently change every other page's
    measure'). Another _shell page (the queue) must NOT carry the wide marker — the default wrap
    measure is unchanged. FAILS IF the wide variant leaks into _shell's default."""
    from gateway.curatorpage import render_queue
    html = render_queue(curator_name="ben", rows=[], csrf_token="tok", serve_panel="", nav=_nav())
    assert '<div class="wrap">' in html, "the queue page must keep the default measure"
    assert 'class="wrap wide"' not in html, "the wide variant must not leak beyond the keys page"


def test_keys_page_served_wide_end_to_end(tmp_path):
    """H2 ROUTE PIN. The SERVED /gateway/curator/uploaders page (through the app + nav shell)
    carries the wide marker — the renderer pin above can't catch an app-side regression that stops
    passing nav (falling back to the chrome-less _page). FAILS IF the served bytes lose the wide
    wrap."""
    async def _body():
        async with app_client(tmp_path) as (client, _app, _gw, _cfg):
            await curator_login(client)
            page = await client.get("/gateway/curator/uploaders")
            assert page.status_code == 200
            assert '<div class="wrap wide">' in page.text
    run(_body())
