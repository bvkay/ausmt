"""Bounded multipart intake (design §4.1). request.form() spools file parts to a
SpooledTemporaryFile that rolls over to tempfile.gettempdir() — a filesystem the /gw/incoming
headroom check does not measure — and starlette 1.3.1 does NOT apply max_part_size to file-part
bytes, so neither the Content-Length gate (absent under Transfer-Encoding: chunked) nor a
max_part_size argument bounds a hostile file part before it lands on disk.

This module closes that: it runs the multipart parser over a CAPPED stream wrapping request.stream()
that enforces the total-byte cap AS BYTES ARRIVE (chunked-safe, no Content-Length dependency) and
raises before the parser can spool more than the cap + framing overhead. It also pins the spool
directory to the measured incoming volume via a SpooledTemporaryFile factory, so nothing the parser
buffers escapes to an unmeasured /tmp.
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


def _spool_factory(spool_dir: Path):
    """A MultiPartParser file-part factory that spools onto the MEASURED incoming volume instead of
    tempfile.gettempdir(). Same SpooledTemporaryFile the parser would use, but dir= is pinned so a
    rollover to disk lands where the headroom check can see it, not on the container overlay."""
    spool_dir.mkdir(parents=True, exist_ok=True)

    def _make(max_size: int = 1024 * 1024):
        return tempfile.SpooledTemporaryFile(max_size=max_size, dir=str(spool_dir))

    return _make


async def parse_capped(request: Request, max_upload_bytes: int, spool_dir: Path) -> ParsedForm:
    """Parse a multipart/form-data body under a hard total-byte cap, spooling only onto spool_dir.
    Raises UploadTooLarge if the body overruns; MultiPartException (mapped to 400 by the caller) on
    a malformed body. max_files/max_fields are tight (one file, a handful of text fields) so a
    part-count flood is refused too."""
    max_total = max_upload_bytes + _OVERHEAD_MARGIN
    parser = MultiPartParser(
        request.headers,
        _capped_stream(request, max_total),
        max_files=1,
        max_fields=8,
        max_part_size=max_total,
    )
    # Pin the spool location for the duration of this parse. starlette constructs the
    # SpooledTemporaryFile via the stdlib symbol imported into its module namespace, so redirect it
    # to our measured-volume factory and restore it after — no global side effect leaks out.
    import starlette.formparsers as _fp
    original = _fp.SpooledTemporaryFile
    _fp.SpooledTemporaryFile = _spool_factory(spool_dir)  # type: ignore[assignment]
    try:
        form = await parser.parse()
    finally:
        _fp.SpooledTemporaryFile = original  # type: ignore[assignment]

    file_obj = None
    fields: dict[str, str] = {}
    for key, value in form.multi_items():
        if isinstance(value, UploadFile):
            if file_obj is None:
                file_obj = value
        else:
            fields[key] = value
    return ParsedForm(file=file_obj, fields=fields)


__all__ = ["MultiPartException", "ParsedForm", "UploadTooLarge", "parse_capped"]
