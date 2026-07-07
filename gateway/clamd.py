"""Async clamd INSTREAM client (design §1/§4/§5). Only the gateway talks to clamd — the runner has
network_mode none, so all scanning happens before a job is queued and again (second sweep) after
ingest, both from the gateway.

INSTREAM protocol: send `zINSTREAM\\0`, then repeated 4-byte-BE-length-prefixed chunks, then a
zero-length chunk to terminate; clamd replies `stream: OK\\0` or `stream: <sig> FOUND\\0`.

Fail-closed contract (design §0/§2): a connection error, a truncated reply, or any reply that is
neither a clean OK nor a definite FOUND is reported as UNAVAILABLE (ScanError), NOT as clean. The
caller holds the submission at RECEIVED on UNAVAILABLE and only advances on a definite OK.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

# 32 KiB stream chunks — well under clamd's default StreamMaxLength, small enough to bound memory.
_CHUNK = 32 * 1024
_CONNECT_TIMEOUT_S = 5.0
_SCAN_TIMEOUT_S = 120.0


class ScanError(Exception):
    """clamd unreachable, timed out, or gave an unparseable reply. Fail closed: the caller must NOT
    treat this as clean."""


@dataclass(frozen=True)
class ScanResult:
    clean: bool
    signature: str | None  # the matched signature name when not clean, else None


async def _instream(host: str, port: int, data: bytes) -> str:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=_CONNECT_TIMEOUT_S
        )
    except (OSError, asyncio.TimeoutError) as exc:
        raise ScanError(f"clamd connect failed: {exc}") from exc
    try:
        writer.write(b"zINSTREAM\0")
        for i in range(0, len(data), _CHUNK):
            chunk = data[i:i + _CHUNK]
            writer.write(len(chunk).to_bytes(4, "big") + chunk)
        writer.write((0).to_bytes(4, "big"))  # zero-length chunk terminates the stream
        await writer.drain()
        raw = await asyncio.wait_for(reader.readuntil(b"\0"), timeout=_SCAN_TIMEOUT_S)
    except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError) as exc:
        raise ScanError(f"clamd stream failed: {exc}") from exc
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
    return raw.decode("utf-8", "replace").strip("\0").strip()


async def scan_bytes(host: str, port: int, data: bytes) -> ScanResult:
    """Scan an in-memory buffer. Raises ScanError (fail closed) on any non-definite outcome."""
    reply = await _instream(host, port, data)
    # clamd replies "stream: OK" or "stream: Eicar-Test-Signature FOUND" or "stream: <x> ERROR".
    if reply.endswith("OK"):
        return ScanResult(clean=True, signature=None)
    if reply.endswith("FOUND"):
        body = reply.split(":", 1)[-1].strip()
        sig = body[:-len("FOUND")].strip() if body.endswith("FOUND") else body
        return ScanResult(clean=False, signature=sig or "unknown")
    raise ScanError(f"unexpected clamd reply: {reply!r}")


async def scan_file(host: str, port: int, path) -> ScanResult:
    # Files here are already size-capped by the upload guard (design §4.1), so reading the whole
    # capped zip to scan it is bounded; streaming from disk in chunks would not change the cap.
    data = await asyncio.to_thread(_read_bytes, path)
    return await scan_bytes(host, port, data)


def _read_bytes(path) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()
