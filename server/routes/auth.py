"""Dashboard login/logout endpoints (see server/dashboard_auth.py)."""
from __future__ import annotations

import threading
import time

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from server.config import get_settings
from server.dashboard_auth import authenticate, bearer_token, create_session, current_employee, revoke_session
from server.db import get_session
from server.models import Employee

router = APIRouter(prefix="/v1/auth")

# Simple per-login-name throttle against password guessing: after
# _MAX_FAILURES wrong attempts inside _WINDOW_SECS, that name is locked for the
# rest of the window. In-process memory is enough for the single server
# process this project runs (see agent/single_instance.py).
_MAX_FAILURES = 5
_WINDOW_SECS = 300.0
_failures: dict[str, list[float]] = {}
_failures_lock = threading.Lock()


def _recent_failures(key: str, now: float) -> list[float]:
    recent = [t for t in _failures.get(key, []) if now - t < _WINDOW_SECS]
    _failures[key] = recent
    return recent


class LoginRequest(BaseModel):
    login: str
    password: str


class AccountOut(BaseModel):
    employee_id: str
    name: str
    role: str
    email: str | None
    system_name: str


class LoginResponse(BaseModel):
    token: str
    account: AccountOut


def account_out(employee: Employee) -> AccountOut:
    return AccountOut(
        employee_id=employee.employee_id,
        name=employee.name,
        role=employee.role,
        email=employee.email,
        system_name=employee.system_name,
    )


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, session: Session = Depends(get_session)) -> LoginResponse:
    key = body.login.strip().lower()
    now = time.time()
    with _failures_lock:
        if len(_recent_failures(key, now)) >= _MAX_FAILURES:
            raise HTTPException(status_code=429, detail="Too many failed attempts. Wait 5 minutes and try again.")

    employee = authenticate(session, body.login, body.password)
    if employee is None:
        with _failures_lock:
            _failures.setdefault(key, []).append(now)
        # Same message whether the account or the password was wrong, so the
        # response doesn't reveal which login names exist.
        raise HTTPException(status_code=401, detail="That login and password don't match.")

    with _failures_lock:
        _failures.pop(key, None)
    token = create_session(session, employee, get_settings().dashboard_session_ttl_hours)
    session.commit()
    return LoginResponse(token=token, account=account_out(employee))


@router.post("/logout", status_code=204)
def logout(authorization: str = Header(default=""), session: Session = Depends(get_session)) -> None:
    token = bearer_token(authorization)
    if token:
        revoke_session(session, token)
        session.commit()


@router.get("/me", response_model=AccountOut)
def me(employee: Employee = Depends(current_employee)) -> AccountOut:
    return account_out(employee)
