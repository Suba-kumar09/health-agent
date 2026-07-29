from __future__ import annotations

import json
import logging
import random
import secrets
import string
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agent.collectors.base import Collector
from agent.secrets import SecretStore

logger = logging.getLogger(__name__)

ALLOWED_ORIGIN_PREFIXES = ("chrome-extension://", "moz-extension://")
PAIRING_CODE_TTL_SECS = 300


def _generate_pairing_code() -> str:
    return "".join(random.SystemRandom().choice(string.digits) for _ in range(6))


class BrowserBridgeCollector(Collector):
    """Localhost HTTP endpoint the companion browser extension posts tab

    events to. Threat model: any open tab can fetch() localhost ports, so
    every write path requires the paired bearer token; the Origin allowlist
    (chrome-extension://* / moz-extension://*) is defense-in-depth on top of
    that, since ordinary web pages cannot spoof those schemes.
    """

    name = "browser_bridge"

    def __init__(
        self,
        secret_store: SecretStore,
        on_tab_event: Callable[[dict], None],
        host: str = "127.0.0.1",
        port: int = 0,
        now_fn: Callable[[], float] = time.time,
    ) -> None:
        self.secret_store = secret_store
        self.on_tab_event = on_tab_event
        self.host = host
        self.requested_port = port
        self.now_fn = now_fn
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._pairing_code: str | None = None
        self._pairing_expires_at: float = 0.0

    @property
    def paired_token(self) -> str | None:
        return self.secret_store.get("browser_bridge_token")

    @property
    def port(self) -> int | None:
        return self._server.server_address[1] if self._server else None

    def issue_pairing_code(self) -> str:
        """Generates a fresh one-time pairing code, valid for PAIRING_CODE_TTL_SECS.

        The user types this into the extension's options page -- it's the
        out-of-band channel that lets the extension prove it's the real
        companion, without the endpoint ever handing out the token to an
        unauthenticated fetch().
        """
        self._pairing_code = _generate_pairing_code()
        self._pairing_expires_at = self.now_fn() + PAIRING_CODE_TTL_SECS
        logger.info("Browser extension pairing code: %s (expires in %ds)", self._pairing_code, PAIRING_CODE_TTL_SECS)
        return self._pairing_code

    def unpair(self) -> None:
        """Clears the paired bearer token, invalidating any already-paired extension

        installs -- they'll get 401s on /tab-event until a new pairing code is
        issued and the extension re-pairs.
        """
        self.secret_store.delete("browser_bridge_token")
        logger.info("Browser extension unpaired -- previous token invalidated")

    def _consume_pairing_code(self, code: str) -> bool:
        if self._pairing_code is None or self.now_fn() > self._pairing_expires_at:
            return False
        if not secrets.compare_digest(code, self._pairing_code):
            return False
        self._pairing_code = None  # single use
        return True

    def start(self) -> None:
        collector = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                logger.debug("browser_bridge: " + fmt, *args)

            def _origin_allowed(self) -> bool:
                origin = self.headers.get("Origin", "")
                return origin.startswith(ALLOWED_ORIGIN_PREFIXES)

            def _read_json(self) -> dict:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b"{}"
                return json.loads(raw or b"{}")

            def _send_json(self, status: int, payload: dict) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                # A same-origin curl/httpx call never needs this, but a real
                # browser extension's fetch() is cross-origin (chrome-extension://
                # -> http://127.0.0.1:port) and silently discards the response
                # without it -- reflecting the already-validated Origin (never "*")
                # keeps this consistent with the Origin-allowlist model above.
                if self._origin_allowed():
                    self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", ""))
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self):  # noqa: N802 (stdlib handler naming)
                # CORS preflight: POST with a JSON body isn't a "simple request",
                # so browsers send this before every real POST above. Without a
                # response here, the browser never even attempts the POST --
                # curl/httpx don't enforce CORS, which is why they never hit this.
                if not self._origin_allowed():
                    self._send_json(403, {"error": "origin_not_allowed"})
                    return
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", ""))
                self.send_header("Access-Control-Allow-Methods", "POST")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_POST(self):  # noqa: N802 (stdlib handler naming)
                if not self._origin_allowed():
                    self._send_json(403, {"error": "origin_not_allowed"})
                    return

                if self.path == "/pair":
                    try:
                        body = self._read_json()
                    except json.JSONDecodeError:
                        self._send_json(400, {"error": "bad_request"})
                        return
                    if collector._consume_pairing_code(str(body.get("code", ""))):
                        token = secrets.token_urlsafe(32)
                        collector.secret_store.set("browser_bridge_token", token)
                        self._send_json(200, {"token": token})
                    else:
                        self._send_json(401, {"error": "invalid_or_expired_code"})
                    return

                if self.path == "/tab-event":
                    auth = self.headers.get("Authorization", "")
                    expected = collector.paired_token
                    if not expected or not secrets.compare_digest(auth, f"Bearer {expected}"):
                        self._send_json(401, {"error": "auth_failed"})
                        return
                    try:
                        body = self._read_json()
                    except json.JSONDecodeError:
                        self._send_json(400, {"error": "bad_request"})
                        return
                    collector.on_tab_event(body)
                    self._send_json(200, {"ok": True})
                    return

                if self.path == "/unpair":
                    # Requires the current token, same as /tab-event -- an unauthenticated
                    # caller (or an unrelated web page) must not be able to force an unpair.
                    auth = self.headers.get("Authorization", "")
                    expected = collector.paired_token
                    if not expected or not secrets.compare_digest(auth, f"Bearer {expected}"):
                        self._send_json(401, {"error": "auth_failed"})
                        return
                    collector.unpair()
                    self._send_json(200, {"ok": True})
                    return

                self._send_json(404, {"error": "not_found"})

        self._server = ThreadingHTTPServer((self.host, self.requested_port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info("browser_bridge listening on %s:%d", self.host, self.port)

        if self.paired_token is None:
            self.issue_pairing_code()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
