"""Dashboard login: password hashing, sessions, and the FastAPI dependencies
that gate the /v1/me/* and /v1/admin/* endpoints.

Kept separate from server/auth.py on purpose -- that module authenticates
*devices* (the agent's bearer token); this one authenticates *people*
looking at the dashboard. Both send "Authorization: Bearer ...", but they
resolve against different tables (Device vs DashboardSession), so a device
token can never open the dashboard and a login token can never ingest events.

Passwords use stdlib PBKDF2-HMAC-SHA256 (no new dependency), stored as
"pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>". Session tokens are random
and only their sha256 is stored, same as device tokens.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from fastapi import Depends, Header, HTTPException
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from server.auth import hash_token
from server.db import get_session
from server.models import DashboardSession, Employee

_ALGORITHM = "pbkdf2_sha256"
_ITERATIONS = 600_000
ROLES = ("admin", "employee")


def hash_password(password: str, iterations: int = _ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{_ALGORITHM}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algorithm, iterations, salt_hex, digest_hex = stored.split("$")
        if algorithm != _ALGORITHM:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


# Burned when the login name doesn't exist, so a wrong name and a wrong
# password take the same time -- response timing can't be used to discover
# which names are real accounts.
_DUMMY_HASH = hash_password("not-a-real-password")


def find_login_account(session: Session, login: str) -> Employee | None:
    """An employee logs in with either their email or their computer's
    system name, both matched case-insensitively."""
    login = login.strip().lower()
    if not login:
        return None
    return session.execute(
        select(Employee).where(or_(func.lower(Employee.email) == login, func.lower(Employee.system_name) == login))
    ).scalars().first()


def authenticate(session: Session, login: str, password: str) -> Employee | None:
    employee = find_login_account(session, login)
    if employee is None or not employee.password_hash:
        verify_password(password, _DUMMY_HASH)
        return None
    return employee if verify_password(password, employee.password_hash) else None


def create_session(session: Session, employee: Employee, ttl_hours: int) -> str:
    """Persists a new session and returns its plaintext token (shown to the
    client exactly once). Also sweeps this employee's expired sessions."""
    now = time.time()
    session.execute(
        delete(DashboardSession).where(
            DashboardSession.employee_id == employee.employee_id, DashboardSession.expires_at <= now
        )
    )
    token = secrets.token_urlsafe(32)
    session.add(
        DashboardSession(
            token_hash=hash_token(token),
            employee_id=employee.employee_id,
            created_at=now,
            expires_at=now + ttl_hours * 3600,
        )
    )
    session.flush()
    return token


def revoke_session(session: Session, token: str) -> bool:
    result = session.execute(delete(DashboardSession).where(DashboardSession.token_hash == hash_token(token)))
    return (result.rowcount or 0) > 0


def resolve_session(session: Session, token: str) -> Employee | None:
    row = session.execute(
        select(DashboardSession).where(DashboardSession.token_hash == hash_token(token))
    ).scalar_one_or_none()
    if row is None or row.expires_at <= time.time():
        return None
    return session.get(Employee, row.employee_id)


def bearer_token(authorization: str) -> str | None:
    if not authorization.startswith("Bearer "):
        return None
    return authorization[len("Bearer ") :].strip() or None


def current_employee(
    authorization: str = Header(default=""), session: Session = Depends(get_session)
) -> Employee:
    """Dependency for any logged-in page: 401 if the token is missing,
    unknown, or expired (the dashboard then sends the user back to login)."""
    token = bearer_token(authorization)
    employee = resolve_session(session, token) if token else None
    if employee is None:
        raise HTTPException(status_code=401, detail="Please log in again.")
    return employee


def require_admin(employee: Employee = Depends(current_employee)) -> Employee:
    if employee.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can view the organization dashboard.")
    return employee
