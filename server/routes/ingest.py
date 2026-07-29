from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from server.auth import resolve_device_by_token
from server.config import get_settings
from server.db import get_session, insert_ignore_conflict
from server.models import Device, Event
from server.ratelimit import check_and_increment
from server.schemas import IngestRequest, IngestResponse

router = APIRouter()


def _resolve_device(authorization: str = Header(default=""), session: Session = Depends(get_session)) -> Device:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401)
    token = authorization[len("Bearer ") :]
    device = resolve_device_by_token(session, token)
    if device is None:
        raise HTTPException(status_code=401)
    return device


@router.post("/v1/ingest", response_model=IngestResponse)
def ingest(
    payload: IngestRequest,
    device: Device = Depends(_resolve_device),
    session: Session = Depends(get_session),
):
    # Prevents a token/device_id mismatch from writing events under the wrong device.
    if payload.device_id != device.device_id:
        raise HTTPException(status_code=401)

    settings = get_settings()
    limit = check_and_increment(
        session,
        device.device_id,
        settings.rate_limit_window_secs,
        settings.rate_limit_max_requests,
    )
    if not limit.allowed:
        session.commit()
        return JSONResponse(status_code=429, content={"retry_after": limit.retry_after})

    rows = [
        {
            "event_id": event.event_id,
            "device_id": device.device_id,
            "collector": event.collector,
            "ts": event.ts,
            "duration": event.duration,
            "data": event.data,
            "batch_id": payload.batch_id,
        }
        for event in payload.events
    ]
    inserted_ids = insert_ignore_conflict(session, Event.__table__, rows, ["event_id"])

    accepted = [row["event_id"] for row in rows if row["event_id"] in inserted_ids]
    duplicates = [row["event_id"] for row in rows if row["event_id"] not in inserted_ids]

    device.last_seen_at = time.time()
    session.commit()

    return IngestResponse(accepted=accepted, duplicates=duplicates)
