"""Wire-contract models -- imported straight from the client's agent.sync.api,
not redefined, so the client and server can never drift on shape."""
from __future__ import annotations

from agent.sync.api import (
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
    "EnrollRequest",
    "EnrollResponse",
    "IngestEvent",
    "IngestRequest",
    "IngestResponse",
    "PendingMessage",
    "PendingMessagesResponse",
    "RateLimitResponse",
]
