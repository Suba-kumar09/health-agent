"""Raw ASGI middleware: enforces a real 413 on oversized bodies (checked via
Content-Length before any body is read) and transparently decompresses
Content-Encoding: gzip requests so route handlers always see plain JSON --
the same behavior tests/mock_server.py implements inline, centralized here so
every route gets it. This is the one thing the mock never implements: a real
size limit.
"""
from __future__ import annotations

import zlib

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_GZIP_WBITS = zlib.MAX_WBITS | 16


class _GzipTooLarge(Exception):
    """Raised when decompressed output would exceed the configured cap."""


def _decompress_gzip_bounded(data: bytes, max_bytes: int) -> bytes:
    """Streaming gzip decompression that aborts once the output would exceed
    max_bytes, instead of gzip.decompress()'s single unbounded call.

    The Content-Length check only bounds the *compressed* size -- a small
    gzip payload can still expand far past that (a zip bomb) and blow up
    memory before a one-shot decompress() call would even return. Raises
    _GzipTooLarge if the limit is exceeded, or zlib.error if malformed.
    """
    decompressor = zlib.decompressobj(_GZIP_WBITS)
    out = bytearray()
    chunk = decompressor.decompress(data, max_bytes + 1)
    out += chunk
    while decompressor.unconsumed_tail and len(out) <= max_bytes:
        chunk = decompressor.decompress(decompressor.unconsumed_tail, max_bytes + 1 - len(out))
        out += chunk
    if len(out) > max_bytes:
        raise _GzipTooLarge
    out += decompressor.flush()
    if len(out) > max_bytes:
        raise _GzipTooLarge
    return bytes(out)


class GzipAndSizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        content_length = headers.get(b"content-length")
        if content_length is not None and int(content_length) > self.max_body_bytes:
            await _send_413(send)
            return

        if headers.get(b"content-encoding", b"").lower() != b"gzip":
            await self.app(scope, receive, send)
            return

        body = b""
        more_body = True
        while more_body:
            message = await receive()
            body += message.get("body", b"")
            more_body = message.get("more_body", False)
            if len(body) > self.max_body_bytes:
                # Covers the case where Content-Length was absent (chunked
                # transfer) so the check above never ran.
                await _send_413(send)
                return

        try:
            decompressed = _decompress_gzip_bounded(body, self.max_body_bytes)
        except _GzipTooLarge:
            await _send_413(send)
            return
        except zlib.error:
            # Malformed gzip: pass an empty body through and let the route's
            # own JSON validation produce the error, rather than this
            # middleware guessing at the right status code.
            decompressed = b""

        sent = False

        async def receive_decompressed() -> Message:
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": decompressed, "more_body": False}

        await self.app(scope, receive_decompressed, send)


async def _send_413(send: Send) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": b'{"detail":"payload too large"}'})
