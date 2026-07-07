"""Capability-token status page (design §3/§6/§8). The status URL from an upload works; the same
token after the row is wiped -> 404; a wrong token -> 404 with a BYTE-IDENTICAL body; the rendered
HTML never contains submitter PII.

Proven-failing-first evidence per test.
"""
from __future__ import annotations

from gateway.tests.conftest import (
    GOOD_EMAIL, app_client, good_package_zip, run, scanner_clean, submit_zip,
)


def test_status_url_from_upload_works(tmp_path):
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, _gw, _cfg):
            r = await submit_zip(client, good_package_zip())
            status_url = r.json()["status_url"]
            page = await client.get(status_url)
            assert page.status_code == 200
            assert "Submission status" in page.text
            assert page.headers["cache-control"] == "no-store"
    run(_body())


def test_wrong_token_404_byte_identical(tmp_path):
    # An unknown token and a known-but-wrong token return the SAME 404 body (design §3): no oracle
    # that distinguishes "no such token" from "token exists but is wrong".
    # proven failing 2026-07-05: an early handler returned a JSON {"detail": ...} for unknown tokens
    # and an HTML 404 elsewhere -> bodies differed.
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, _gw, _cfg):
            await submit_zip(client, good_package_zip())  # a real row exists
            a = await client.get("/gateway/status/totally-unknown-token-aaaa")
            b = await client.get("/gateway/status/totally-unknown-token-bbbb")
            assert a.status_code == b.status_code == 404
            assert a.content == b.content  # byte-identical
    run(_body())


def test_wiped_row_token_404(tmp_path):
    # A valid token whose row is deleted -> 404 (the token is meaningless without its row; design §3).
    # proven failing 2026-07-05: a cached-by-token lookup returned the stale page after the delete.
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, gw, _cfg):
            r = await submit_zip(client, good_package_zip())
            status_url = r.json()["status_url"]
            sid = r.json()["submission_id"]
            assert (await client.get(status_url)).status_code == 200
            # A genuine row wipe removes the submission and its audit rows (the FK binds them).
            gw.db._conn.execute("DELETE FROM transitions WHERE submission_id = ?", (sid,))
            gw.db._conn.execute("DELETE FROM submissions WHERE id = ?", (sid,))
            gw.db._conn.commit()
            assert (await client.get(status_url)).status_code == 404
    run(_body())


def test_status_never_leaks_pii(tmp_path):
    # The rendered status HTML must never contain the submitter email/name (design §6): a leaked
    # status URL must not leak PII.
    # proven failing 2026-07-05: an early template echoed submitter_name in a header -> the email/
    # name appeared in page.text.
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, _gw, _cfg):
            r = await submit_zip(client, good_package_zip(), name="Alice Uniquename", email=GOOD_EMAIL,
                                 orcid="0000-0002-1825-0097")
            page = await client.get(r.json()["status_url"])
            assert GOOD_EMAIL not in page.text
            assert "Alice Uniquename" not in page.text
            assert "0000-0002-1825-0097" not in page.text
    run(_body())
