from __future__ import annotations

import hashlib
import secrets
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.models import Device, EnrollmentCode


class EnrollmentError(Exception):
    """Raised when an enrollment code is missing, already used, or expired."""


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_device_token() -> str:
    return secrets.token_urlsafe(32)


def generate_enrollment_code() -> str:
    return secrets.token_urlsafe(16)


def resolve_device_by_token(session: Session, token: str) -> Device | None:
    token_hash = hash_token(token)
    return session.execute(select(Device).where(Device.device_token_hash == token_hash)).scalar_one_or_none()


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

    plaintext_token = generate_device_token()
    device = Device(
        device_token_hash=hash_token(plaintext_token),
        device_name=device_name,
        os=os,
        os_version=os_version,
        enrolled_at=now,
    )
    session.add(device)
    session.flush()

    row.used_at = now
    row.used_by_device_id = device.device_id

    return device, plaintext_token
