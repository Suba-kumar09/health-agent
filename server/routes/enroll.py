from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from server.auth import EnrollmentError, enroll_device
from server.db import get_session
from server.schemas import EnrollRequest, EnrollResponse

router = APIRouter()


@router.post("/v1/enroll", response_model=EnrollResponse)
def enroll(payload: EnrollRequest, session: Session = Depends(get_session)):
    try:
        device, token = enroll_device(
            session,
            enrollment_code=payload.enrollment_code,
            device_name=payload.device_name,
            os=payload.os,
            os_version=payload.os_version,
        )
    except EnrollmentError:
        session.rollback()
        raise HTTPException(status_code=403) from None

    session.commit()
    return EnrollResponse(device_id=device.device_id, device_token=token)
