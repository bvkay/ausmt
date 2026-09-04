"""The reusable request-body cap for the small-field PUBLIC routes (gateway.upload).

POST /gateway/submit has a whole module keeping a hostile body off the box; its sibling public route,
POST /gateway/request-key, reads a body that carries one email address and has no ceiling at any
layer (no middleware, and neither Caddy wall sets a body limit). starlette's Request.body joins
every chunk it is handed, and a Transfer-Encoding: chunked body declares no length, so the only bound
is RAM on a read_only container with a 64m tmpfs.

These tests drive the real helper over real starlette Request objects fed by a receive channel the
test controls, so "it aborted before buffering the rest" is an observable (chunks served), not an
inference from a return value.
"""
from __future__ import annotations

import json

import pytest
from starlette.requests import Request

from gateway.tests.conftest import app_client, run
from gateway.upload import SMALL_BODY_MAX_BYTES, UploadTooLarge, read_body_capped


class _Feed:
    """A receive channel that hands out one chunk per call and COUNTS how many it served. The count is
    the evidence that the cap fires as bytes arrive rather than after the whole body is in memory."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.served = 0

    async def __call__(self) -> dict:
        if self.served >= len(self._chunks):
            return {"type": "http.request", "body": b"", "more_body": False}
        chunk = self._chunks[self.served]
        self.served += 1
        return {"type": "http.request", "body": chunk, "more_body": self.served < len(self._chunks)}


def _request(chunks: list[bytes], content_type: str = "application/json") -> tuple[Request, _Feed]:
    feed = _Feed(chunks)
    scope = {"type": "http", "method": "POST", "path": "/gateway/request-key",
             "headers": [(b"content-type", content_type.encode("latin-1"))]}
    return Request(scope, feed), feed


def test_body_under_the_cap_is_returned_whole():
    """A real request-key body (one email address) passes through untouched.

    Scope: upload.read_body_capped's happy path. FAILS IF the cap truncates or rejects an ordinary
    body. RED before the helper existed: ImportError on gateway.upload.read_body_capped.
    """
    payload = json.dumps({"email": "someone@example.test"}).encode("utf-8")
    request, _feed = _request([payload])
    assert run(read_body_capped(request, SMALL_BODY_MAX_BYTES)) == payload


def test_body_exactly_at_the_cap_is_accepted():
    # A cap is a ceiling, not a strict inequality: the boundary byte is legitimate. FAILS IF an
    # off-by-one rejects a body of exactly max_bytes.
    payload = b"x" * 4096
    request, _feed = _request([payload])
    assert run(read_body_capped(request, 4096)) == payload


def test_oversize_chunked_body_is_refused_before_it_is_buffered():
    """The defect this helper exists for: a chunked body declares no Content-Length, so nothing but
    the running byte count can stop it. The refusal must land while the body is still arriving.

    Scope: upload.read_body_capped's mid-stream abort. FAILS IF the whole body is drained before the
    limit is signalled. RED before the helper existed: ImportError; against the route it protects, a
    128 MB chunked body returned HTTP 202 at +249 MB peak RSS.
    """
    chunk = b"y" * (64 * 1024)
    total_chunks = 512  # 32 MB offered
    request, feed = _request([chunk] * total_chunks)
    with pytest.raises(UploadTooLarge):
        run(read_body_capped(request, 64 * 1024))
    assert feed.served <= 4, (
        f"the cap drained {feed.served} of {total_chunks} chunks before refusing; it must abort as "
        "bytes arrive")


def test_capped_body_is_reused_by_the_handler_json_parse():
    """The cap must be a ONE-LINE change at a call site that already parses the body: the helper fills
    the same cache Request.body fills, so the handler's existing await request.json sees the
    capped bytes and no second read is attempted.

    Scope: upload.read_body_capped's body-cache handover (a starlette internal, pinned here so a
    starlette upgrade that moves the cache fails loudly instead of silently re-reading a consumed
    stream). FAILS IF a later .json raises or returns something other than the capped body.
    """
    payload = json.dumps({"email": "reuse@example.test"}).encode("utf-8")
    request, _feed = _request([payload])

    async def _body():
        assert await read_body_capped(request, SMALL_BODY_MAX_BYTES) == payload
        assert await request.json() == {"email": "reuse@example.test"}
    run(_body())


def test_capped_body_is_reused_by_the_handler_form_parse():
    # The request-key handler accepts BOTH encodings, so the urlencoded branch must survive the cap
    # Too. FAILS IF the capped read leaves .form with a consumed stream.
    payload = b"email=form%40example.test"
    request, _feed = _request([payload], content_type="application/x-www-form-urlencoded")

    async def _body():
        await read_body_capped(request, SMALL_BODY_MAX_BYTES)
        form = await request.form()
        assert form.get("email") == "form@example.test"
    run(_body())


def test_small_body_cap_is_generous_but_bounded():
    # The shipped default for a small-field public route: far above any honest body (one email
    # address), far below anything that matters to a 64m tmpfs. FAILS IF the default drifts into
    # either uselessness or a memory risk.
    assert 4 * 1024 <= SMALL_BODY_MAX_BYTES <= 256 * 1024


def test_route_refuses_oversize_body_mid_stream_and_stays_neutral_202(tmp_path):
    """Wired into the REAL route: POST /gateway/request-key must cap the body AS BYTES ARRIVE and
    still return the byte-identical neutral 202, so the endpoint cannot be turned into a memory
    amplifier (a 128 MB body measured +249 MB peak RSS, HTTP 202) and a too-large body stays
    indistinguishable from a bad one (a 413 here would be an enumeration oracle).

    Drives the app via the app_client/httpx harness the sibling request-key tests use, streaming the
    body as chunks through a counter: `served` is the evidence the refusal lands mid-stream rather
    than after the whole body is in memory (httpx's ASGITransport pulls one chunk per receive, so the
    count is the app's own read behaviour, not the transport's).

    Scope: the request_key route's read_body_capped wiring. FAILS IF the route drains the whole body
    before responding. RED before the app.py edit: await request.json reads every chunk first, so
    `served` reached all 512 (assertion seen: `assert 512 <= 4`).
    """
    async def _body():
        counter = {"served": 0}
        chunk = b"y" * (64 * 1024)
        total_chunks = 512  # 32 MB offered, every chunk past the 64 KiB SMALL_BODY_MAX_BYTES cap

        async def _stream():
            for _ in range(total_chunks):
                counter["served"] += 1
                yield chunk

        async with app_client(tmp_path) as (client, _app, gw, _cfg):
            # A bad email mints nothing and yields the byte-identical neutral 202: the reference the
            # oversize body must match exactly.
            ref = await client.post("/gateway/request-key", data={"email": "not-an-email"})
            assert ref.status_code == 202
            oversize = await client.post(
                "/gateway/request-key", content=_stream(),
                headers={"Content-Type": "application/json"})
            # (a) same neutral 202, byte for byte (no too-large vs bad-body oracle).
            assert oversize.status_code == 202
            assert oversize.content == ref.content, (
                "an oversize body must return the byte-identical neutral 202, not a distinct status")
            # (b) refused mid-stream, not read whole: the cap fires after a chunk or two.
            assert counter["served"] <= 4, (
                f"the route drained {counter['served']} of {total_chunks} chunks before responding; "
                "the cap must abort as bytes arrive, not after the whole body is buffered")
            # The neutral path minted nothing (same as a bad body).
            assert gw.db.list_uploader_keys() == []
    run(_body())
