"""Wire-contract models -- imported straight from the client's agent.sync.api,
not redefined, so the client and server can never drift on shape."""
from __future__ import annotations

from agent.sync.api import (
    AckMessagesRequest,
    AckMessagesResponse,
    EnrollRequest,
    EnrollResponse,
    IngestEvent,
    IngestRequest,
    IngestResponse,
    PendingMessage,
    PendingMessagesResponse,
    RateLimitResponse,
)

__all__ = [
    "AckMessagesRequest",
    "AckMessagesResponse",
    "EnrollRequest",
    "EnrollResponse",
    "IngestEvent",
    "IngestRequest",
    "IngestResponse",
    "PendingMessage",
    "PendingMessagesResponse",
    "RateLimitResponse",
]
