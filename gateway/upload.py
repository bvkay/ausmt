"""Bounded multipart intake. request.form() spools file parts to a
SpooledTemporaryFile that rolls over to tempfile.gettempdir() - a filesystem the /gw/incoming
headroom check does not measure — and starlette 1.3.1 does NOT apply max_part_size to file-part
bytes, so neither the Content-Length gate (absent under Transfer-Encoding: chunked) nor a
max_part_size argument bounds a hostile file part before it lands on disk.

This module closes that: it runs the multipart parser over a CAPPED stream wrapping request.stream()
that enforces the total-byte cap AS BYTES ARRIVE (chunked-safe, no Content-Length dependency) and
raises before the parser can spool more than the cap + framing overhead. It also pins the spool
directory to the measured incoming volume as PER-PARSE state (_PinnedSpoolParser), so nothing the
parser buffers escapes to an unmeasured /tmp even while several submits overlap.

read_body_capped() is the same guarantee for the small-field public routes that read a whole body
into memory instead of parsing multipart.
"""
from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.requests import Request

# Framing overhead allowance on top of the file bytes (boundaries, part headers, the small text
# fields). The cap the parser sees is max_upload_bytes + this; the AUTHORITATIVE per-file cap is
# re-checked when the file is streamed to disk in app.py.
_OVERHEAD_MARGIN = 1024 * 1024

# The default ceiling for a PUBLIC route whose body carries a field or two (read_body_capped). Far
# above any honest body and far below anything that matters on a read_only container with a 64m
# tmpfs, so an unauthenticated caller cannot turn a one-field endpoint into a memory amplifier.
SMALL_BODY_MAX_BYTES = 64 * 1024


class UploadTooLarge(Exception):
    """The request body exceeded the cap while streaming — before any spool grew unbounded."""


@dataclass
class ParsedForm:
    file: UploadFile | None
    fields: dict[str, str]


async def _capped_stream(request: Request, max_total: int) -> AsyncIterator[bytes]:
    """Yield body chunks from request.stream(), aborting the moment the running total exceeds
    max_total. This bounds a Transfer-Encoding: chunked body (which carries no Content-Length) and
    caps what the multipart parser can ever spool."""
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_total:
            raise UploadTooLarge()
        yield chunk


async def read_body_capped(request: Request, max_bytes: int = SMALL_BODY_MAX_BYTES) -> bytes:
    """Read a whole request body into memory under a hard byte cap, aborting AS BYTES ARRIVE.

    For the PUBLIC routes that carry a field or two rather than a file: starlette's Request.body()
    joins every chunk it is handed with no ceiling, and a Transfer-Encoding: chunked body declares no
    length, so without this the only bound is RAM. Raises UploadTooLarge the moment the running total
    exceeds max_bytes, before the overrun is retained.

    The bytes are also left in the cache Request.body() itself fills, so a caller's existing
    `await request.json()` / `await request.form()` reads the CAPPED body and the guard costs one
    line at the call site. That cache is a starlette internal, so test_request_key_limits.py pins the
    handover: a starlette release that moves it fails loudly here rather than silently re-reading a
    consumed stream."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            raise UploadTooLarge()
        chunks.append(chunk)
    body = b"".join(chunks)
    request._body = body  # noqa: SLF001 -- the same attribute Request.body() caches into
    return body


class _PinnedSpoolParser(MultiPartParser):
    """A MultiPartParser whose file parts spool onto a directory carried as PER-PARSE state.

    starlette builds each file part's SpooledTemporaryFile from the stdlib symbol in its own module
    namespace, passing no dir=, so a rollover lands in tempfile.gettempdir(): the volume the
    /gw/incoming headroom check does not measure. Redirecting that symbol would pin the spool per
    PROCESS across an await: with max_inflight submits overlapping, one parse's restore tears the pin
    out from under another, and the second parse lands exactly where this module exists to prevent.
    So the part is re-homed the instant starlette creates it, while it is still empty and still in
    memory, so no byte has been written and the swap is total."""

    def __init__(self, *args, spool_dir: Path, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        spool_dir.mkdir(parents=True, exist_ok=True)
        self._spool_dir = spool_dir

    def on_headers_finished(self) -> None:
        # super() first: its max_files/max_fields limits stay starlette's to enforce, so a future
        # release cannot lose a check to a copied-out method body.
        super().on_headers_finished()
        part = self._current_part.file
        if part is None:
            return  # a text field, not a file part, so nothing spools
        unpinned = part.file
        part.file = tempfile.SpooledTemporaryFile(max_size=self.spool_max_size,
                                                  dir=str(self._spool_dir))
        # starlette closes every part file it made if the parse fails; hand it the pinned one.
        try:
            self._files_to_close_on_error.remove(unpinned)
        except ValueError:  # pragma: no cover - starlette always registers the file it creates
            pass
        self._files_to_close_on_error.append(part.file)
        unpinned.close()


async def parse_capped(request: Request, max_upload_bytes: int, spool_dir: Path) -> ParsedForm:
    """Parse a multipart/form-data body under a hard total-byte cap, spooling only onto spool_dir.
    Raises UploadTooLarge if the body overruns; MultiPartException (mapped to 400 by the caller) on
    a malformed body. max_files/max_fields are tight (one file, a handful of text fields) so a
    part-count flood is refused too. Every parse carries its own spool directory, so concurrent
    submits cannot displace one another's pin."""
    max_total = max_upload_bytes + _OVERHEAD_MARGIN
    parser = _PinnedSpoolParser(
        request.headers,
        _capped_stream(request, max_total),
        max_files=1,
        max_fields=8,
        max_part_size=max_total,
        spool_dir=spool_dir,
    )
    form = await parser.parse()

    file_obj = None
    fields: dict[str, str] = {}
    for key, value in form.multi_items():
        if isinstance(value, UploadFile):
            if file_obj is None:
                file_obj = value
        else:
            fields[key] = value
    return ParsedForm(file=file_obj, fields=fields)


__all__ = ["SMALL_BODY_MAX_BYTES", "MultiPartException", "ParsedForm", "UploadTooLarge",
           "parse_capped", "read_body_capped"]
