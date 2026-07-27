"""Raw ASGI middleware: enforces a real 413 on oversized bodies (checked via
Content-Length before any body is read) and transparently decompresses
Content-Encoding: gzip requests so route handlers always see plain JSON --
the same behavior tests/mock_server.py implements inline, centralized here so
every route gets it. This is the one thing the mock never implements: a real
size limit.
"""
from __future__ import annotations

import gzip

from starlette.types import ASGIApp, Message, Receive, Scope, Send


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

        try:
            decompressed = gzip.decompress(body)
        except OSError:
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
