from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.auth import resolve_device_dependency
from server.db import get_session
from server.models import Device, Message
from server.schemas import PendingMessage, PendingMessagesResponse

router = APIRouter()


@router.get("/v1/messages/pending", response_model=PendingMessagesResponse)
def pending_messages(
    device: Device = Depends(resolve_device_dependency),
    session: Session = Depends(get_session),
):
    """Returns this device's undelivered wellbeing messages and marks them
    delivered in the same request -- at-most-once delivery is acceptable here
    (unlike /v1/ingest's event dedup, a missed or repeated notification isn't
    a correctness problem, just a UX one)."""
    rows = (
        session.execute(
            select(Message)
            .where(Message.device_id == device.device_id, Message.delivered_at.is_(None))
            .order_by(Message.created_at)
        )
        .scalars()
        .all()
    )
    now = time.time()
    for row in rows:
        row.delivered_at = now
    session.commit()

    return PendingMessagesResponse(
        messages=[PendingMessage(message_id=r.message_id, text=r.text, created_at=r.created_at) for r in rows]
    )
