from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class IngestEvent(BaseModel):
    event_id: str
    collector: str
    ts: float
    duration: float = 0.0
    data: dict[str, Any] = Field(default_factory=dict)


class IngestRequest(BaseModel):
    device_id: str
    agent_version: str
    os: str
    os_version: str
    batch_id: str
    sent_at: float
    events: list[IngestEvent]


class IngestResponse(BaseModel):
    accepted: list[str] = Field(default_factory=list)
    duplicates: list[str] = Field(default_factory=list)


class RateLimitResponse(BaseModel):
    retry_after: float


class EnrollRequest(BaseModel):
    """Contract only -- implemented in a later milestone."""

    enrollment_code: str
    device_name: str
    os: str
    os_version: str


class EnrollResponse(BaseModel):
    device_id: str
    device_token: str


IngestOutcome = Literal["ok", "auth_failed", "too_large", "rate_limited", "network_error"]


class PendingMessage(BaseModel):
    message_id: str
    text: str
    created_at: float


class PendingMessagesResponse(BaseModel):
    messages: list[PendingMessage] = Field(default_factory=list)
