from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.auth import resolve_device_dependency
from server.db import get_session
from server.models import Device, Message
from server.schemas import AckMessagesRequest, AckMessagesResponse, PendingMessage, PendingMessagesResponse

router = APIRouter()


@router.get("/v1/messages/pending", response_model=PendingMessagesResponse)
def pending_messages(
    device: Device = Depends(resolve_device_dependency),
    session: Session = Depends(get_session),
):
    """Returns this device's undelivered wellbeing messages WITHOUT marking
    them delivered -- the agent confirms each one via POST /v1/messages/ack
    only after it has actually shown the popup. Marking on fetch (the old
    behavior) lost a message forever whenever the popup failed to show, or
    whenever a second agent process polled first; now an un-acked message is
    simply returned again on the next poll (at-least-once delivery)."""
    rows = (
        session.execute(
            select(Message)
            .where(Message.device_id == device.device_id, Message.delivered_at.is_(None))
            .order_by(Message.created_at)
        )
        .scalars()
        .all()
    )
    return PendingMessagesResponse(
        messages=[PendingMessage(message_id=r.message_id, text=r.text, created_at=r.created_at) for r in rows]
    )


@router.post("/v1/messages/ack", response_model=AckMessagesResponse)
def ack_messages(
    body: AckMessagesRequest,
    device: Device = Depends(resolve_device_dependency),
    session: Session = Depends(get_session),
):
    """Marks the given messages delivered. Scoped to the caller's own device
    and idempotent -- unknown ids, another device's ids, and already-delivered
    ids are silently ignored rather than erroring, so a retried ack is safe."""
    if not body.message_ids:
        return AckMessagesResponse(acknowledged=0)
    rows = (
        session.execute(
            select(Message).where(
                Message.device_id == device.device_id,
                Message.message_id.in_(body.message_ids),
                Message.delivered_at.is_(None),
            )
        )
        .scalars()
        .all()
    )
    now = time.time()
    for row in rows:
        row.delivered_at = now
    session.commit()
    return AckMessagesResponse(acknowledged=len(rows))
