from __future__ import annotations

import hashlib
import secrets
import time

from fastapi import Depends, Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.db import get_session
from server.models import Device, Employee, EnrollmentCode


class EnrollmentError(Exception):
    """Raised when an enrollment code is missing, already used, or expired,
    or when the enrolling machine's system name isn't a registered employee."""


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_device_token() -> str:
    return secrets.token_urlsafe(32)


def generate_enrollment_code() -> str:
    return secrets.token_urlsafe(16)


def resolve_device_by_token(session: Session, token: str) -> Device | None:
    token_hash = hash_token(token)
    return session.execute(select(Device).where(Device.device_token_hash == token_hash)).scalar_one_or_none()


def resolve_device_dependency(
    authorization: str = Header(default=""), session: Session = Depends(get_session)
) -> Device:
    """FastAPI dependency: bearer-token auth shared by every device-scoped route
    (ingest, messages, ...) -- kept in one place so they can't drift on the
    "missing/invalid Bearer token -> 401" behavior."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401)
    token = authorization[len("Bearer ") :]
    device = resolve_device_by_token(session, token)
    if device is None:
        raise HTTPException(status_code=401)
    return device


def resolve_employee_by_system_name(session: Session, system_name: str) -> Employee | None:
    # Case-insensitive: Windows hostnames are case-insensitive, and platform.node()
    # capitalization can vary from however an admin typed it into `add-employee`.
    return session.execute(
        select(Employee).where(func.lower(Employee.system_name) == system_name.lower())
    ).scalar_one_or_none()


def mint_enrollment_code(session: Session, ttl_hours: int, issued_for: str | None = None) -> EnrollmentCode:
    now = time.time()
    code = EnrollmentCode(
        code=generate_enrollment_code(),
        issued_for=issued_for,
        issued_at=now,
        expires_at=now + ttl_hours * 3600,
    )
    session.add(code)
    session.flush()
    return code


def enroll_device(
    session: Session,
    enrollment_code: str,
    device_name: str,
    os: str,
    os_version: str,
) -> tuple[Device, str]:
    """Validate a single-use enrollment code and create a new device.

    Returns (device, plaintext_token) -- the plaintext token is generated here
    and returned exactly once; only its sha256 hash is persisted.
    Raises EnrollmentError if the code doesn't exist, was already used, or has
    expired.
    """
    now = time.time()
    # with_for_update() closes a TOCTOU race: without it, two concurrent
    # requests for the same code can both read used_at=None before either
    # commits and both mint a device, breaking the single-use guarantee.
    # Mirrors the same lock-then-check pattern in ratelimit.check_and_increment.
    row = (
        session.execute(
            select(EnrollmentCode).where(EnrollmentCode.code == enrollment_code).with_for_update()
        )
        .scalar_one_or_none()
    )

    if row is None:
        raise EnrollmentError("unknown enrollment code")
    if row.used_at is not None:
        raise EnrollmentError("enrollment code already used")
    if row.expires_at <= now:
        raise EnrollmentError("enrollment code expired")

    # Gate on top of the enrollment code: the machine's hostname (device_name,
    # sent as platform.node()) must also match a registered employee's
    # system_name -- an enrollment code alone isn't sufficient to onboard an
    # unrecognized machine.
    employee = resolve_employee_by_system_name(session, device_name)
    if employee is None:
        raise EnrollmentError(f"system '{device_name}' is not a registered employee machine")

    plaintext_token = generate_device_token()
    device = Device(
        device_token_hash=hash_token(plaintext_token),
        device_name=device_name,
        os=os,
        os_version=os_version,
        enrolled_at=now,
        employee_id=employee.employee_id,
    )
    session.add(device)
    session.flush()

    row.used_at = now
    row.used_by_device_id = device.device_id

    return device, plaintext_token
