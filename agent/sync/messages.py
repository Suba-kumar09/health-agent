from __future__ import annotations

import logging
from collections.abc import Callable

import httpx

from agent.sync.api import AckMessagesRequest, PendingMessagesResponse
from agent.sync.uploader import TokenProvider

logger = logging.getLogger(__name__)


class MessagesPoller:
    """Polls GET /v1/messages/pending, hands each new message's text to
    `on_message` (e.g. a tray/toast notification), then confirms the ones that
    were actually shown via POST /v1/messages/ack.

    The server only marks a message delivered when it is acked here, so a
    message whose popup failed (`on_message` returns False or raises) is simply
    returned again on the next poll instead of being lost. `on_message` may
    return None/True (shown) or False (couldn't show it; retry next poll).
    A message already shown by this process is never popped a second time --
    if only its ack failed, the next poll just re-sends the ack. Mirrors
    Uploader's shape (same token_provider/http_client wiring) but has no
    batching or backoff of its own since a missed poll just means it is
    retried next tick."""

    def __init__(
        self,
        http_client: httpx.Client,
        server_url: str,
        token_provider: TokenProvider,
        on_message: Callable[[str], bool | None],
    ) -> None:
        self.http_client = http_client
        self.server_url = server_url.rstrip("/")
        self.token_provider = token_provider
        self.on_message = on_message
        self._shown_ids: set[str] = set()

    def poll_once(self) -> int:
        token = self.token_provider()
        if token == "unenrolled":
            return 0
        headers = {"Authorization": f"Bearer {token}"}
        try:
            resp = self.http_client.get(f"{self.server_url}/v1/messages/pending", headers=headers)
        except httpx.RequestError as exc:
            logger.info("Message poll network error: %s", exc)
            return 0

        if resp.status_code != 200:
            logger.info("Message poll failed: HTTP %d", resp.status_code)
            return 0

        parsed = PendingMessagesResponse.model_validate(resp.json())
        to_ack: list[str] = []
        newly_shown = 0
        for message in parsed.messages:
            if message.message_id not in self._shown_ids:
                try:
                    shown = self.on_message(message.text) is not False
                except Exception:
                    logger.exception("Notification failed; will retry message %s next poll", message.message_id)
                    shown = False
                if not shown:
                    continue
                self._shown_ids.add(message.message_id)
                newly_shown += 1
            to_ack.append(message.message_id)

        if to_ack and self._ack(headers, to_ack):
            self._shown_ids.difference_update(to_ack)
        return newly_shown

    def _ack(self, headers: dict[str, str], message_ids: list[str]) -> bool:
        try:
            resp = self.http_client.post(
                f"{self.server_url}/v1/messages/ack",
                headers=headers,
                json=AckMessagesRequest(message_ids=message_ids).model_dump(),
            )
        except httpx.RequestError as exc:
            logger.info("Message ack network error (will retry next poll): %s", exc)
            return False
        if resp.status_code != 200:
            logger.info("Message ack failed: HTTP %d (will retry next poll)", resp.status_code)
            return False
        return True
