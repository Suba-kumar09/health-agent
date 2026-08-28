from __future__ import annotations

import logging
from collections.abc import Callable

import httpx

from agent.sync.api import PendingMessagesResponse
from agent.sync.uploader import TokenProvider

logger = logging.getLogger(__name__)


class MessagesPoller:
    """Polls GET /v1/messages/pending and hands each new message's text to
    `on_message` (e.g. a tray notification) -- mirrors Uploader's shape
    (same token_provider/http_client wiring) but has no batching or backoff
    of its own since a missed poll just means the message shows up next tick."""

    def __init__(
        self,
        http_client: httpx.Client,
        server_url: str,
        token_provider: TokenProvider,
        on_message: Callable[[str], None],
    ) -> None:
        self.http_client = http_client
        self.server_url = server_url.rstrip("/")
        self.token_provider = token_provider
        self.on_message = on_message

    def poll_once(self) -> int:
        token = self.token_provider()
        if token == "unenrolled":
            return 0
        try:
            resp = self.http_client.get(
                f"{self.server_url}/v1/messages/pending",
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.RequestError as exc:
            logger.info("Message poll network error: %s", exc)
            return 0

        if resp.status_code != 200:
            logger.info("Message poll failed: HTTP %d", resp.status_code)
            return 0

        parsed = PendingMessagesResponse.model_validate(resp.json())
        for message in parsed.messages:
            self.on_message(message.text)
        return len(parsed.messages)
