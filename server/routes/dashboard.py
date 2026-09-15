"""Read-only endpoints for the dashboard/ frontend.

No auth/session system exists anywhere in this project yet (see CLAUDE.md) --
these endpoints reuse the same identification the /goal form already relies
on (server/routes/goals.py): a `system_name` query param matched
case-insensitively against Employee.system_name via
auth.resolve_employee_by_system_name, i.e. the machine's real hostname. This
is not authentication, just lookup, same as the existing form -- do not
treat it as a security boundary.
"""
from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.auth import resolve_employee_by_system_name
from server.db import get_session
from server.goals import current_goal
from server.models import Device, Event, Goal, Message
from server.productivity import continuous_idle_streak
from server.wellbeing import continuous_active_streak

router = APIRouter(prefix="/v1/me")

_DAY_SECS = 86400


class ActivitySegmentOut(BaseModel):
    state: Literal["active", "idle"]
    start_ts: float
    end_ts: float


class CurrentStreakOut(BaseModel):
    state: Literal["active", "idle"]
    started_at: float


class GoalOut(BaseModel):
    text: str
    created_at: float
    deadline_at: float


class NudgeMessageOut(BaseModel):
    message_id: str
    kind: str
    text: str
    created_at: float


class DashboardSummaryOut(BaseModel):
    device_name: str | None
    employee_name: str
    now: float
    today_segments: list[ActivitySegmentOut] = Field(default_factory=list)
    current_streak: CurrentStreakOut | None = None
    goal: GoalOut | None = None
    messages: list[NudgeMessageOut] = Field(default_factory=list)


class DayHistoryEntryOut(BaseModel):
    date: str
    active_secs: float
    idle_secs: float
    top_app: str | None


class GoalHistoryEntryOut(BaseModel):
    goal_id: str
    text: str
    created_at: float
    deadline_at: float


def _resolve_employee_or_404(session: Session, system_name: str):
    employee = resolve_employee_by_system_name(session, system_name)
    if employee is None:
        raise HTTPException(status_code=404, detail=f"system '{system_name}' is not a registered employee machine")
    return employee


def _latest_device(session: Session, employee_id: str) -> Device | None:
    return (
        session.execute(
            select(Device)
            .where(Device.employee_id == employee_id)
            .order_by(func.coalesce(Device.last_seen_at, Device.enrolled_at).desc())
            .limit(1)
        )
        .scalars()
        .first()
    )


@router.get("/summary", response_model=DashboardSummaryOut)
def get_summary(
    system_name: str = Query(...),
    session: Session = Depends(get_session),
) -> DashboardSummaryOut:
    employee = _resolve_employee_or_404(session, system_name)
    device = _latest_device(session, employee.employee_id)
    now = time.time()

    today_segments: list[ActivitySegmentOut] = []
    current_streak: CurrentStreakOut | None = None
    messages: list[NudgeMessageOut] = []

    if device is not None:
        window_start = now - _DAY_SECS
        afk_events = (
            session.execute(
                select(Event)
                .where(Event.device_id == device.device_id, Event.collector == "afk", Event.ts >= window_start)
                .order_by(Event.ts)
            )
            .scalars()
            .all()
        )
        today_segments = [
            ActivitySegmentOut(
                state="active" if e.data.get("state") == "active" else "idle",
                start_ts=e.ts,
                end_ts=e.ts + (e.duration or 0.0),
            )
            for e in afk_events
        ]

        active = continuous_active_streak(session, device.device_id)
        if active is not None:
            current_streak = CurrentStreakOut(state="active", started_at=active[1])
        else:
            idle = continuous_idle_streak(session, device.device_id)
            if idle is not None:
                current_streak = CurrentStreakOut(state="idle", started_at=idle[1])

        message_rows = (
            session.execute(
                select(Message).where(Message.device_id == device.device_id).order_by(Message.created_at.desc()).limit(10)
            )
            .scalars()
            .all()
        )
        messages = [
            NudgeMessageOut(message_id=m.message_id, kind=m.kind, text=m.text, created_at=m.created_at)
            for m in message_rows
        ]

    goal_row = current_goal(session, employee.employee_id)
    goal = (
        GoalOut(text=goal_row.text, created_at=goal_row.created_at, deadline_at=goal_row.deadline_at)
        if goal_row is not None
        else None
    )

    return DashboardSummaryOut(
        device_name=device.device_name if device is not None else None,
        employee_name=employee.name,
        now=now,
        today_segments=today_segments,
        current_streak=current_streak,
        goal=goal,
        messages=messages,
    )


@router.get("/history", response_model=list[DayHistoryEntryOut])
def get_history(
    system_name: str = Query(...),
    days: int = Query(14, ge=1, le=90),
    session: Session = Depends(get_session),
) -> list[DayHistoryEntryOut]:
    employee = _resolve_employee_or_404(session, system_name)
    device = _latest_device(session, employee.employee_id)

    today = datetime.now(UTC).date()
    day_list = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    by_day: dict[date, dict[str, float]] = {d: {"active": 0.0, "idle": 0.0} for d in day_list}
    top_app_secs: dict[date, dict[str, float]] = {d: {} for d in day_list}

    if device is not None:
        window_start = time.mktime(day_list[0].timetuple())
        afk_events = (
            session.execute(
                select(Event)
                .where(Event.device_id == device.device_id, Event.collector == "afk", Event.ts >= window_start)
            )
            .scalars()
            .all()
        )
        for e in afk_events:
            d = datetime.fromtimestamp(e.ts, tz=UTC).date()
            bucket = by_day.get(d)
            if bucket is None:
                continue
            key = "active" if e.data.get("state") == "active" else "idle"
            bucket[key] += e.duration or 0.0

        window_events = (
            session.execute(
                select(Event)
                .where(
                    Event.device_id == device.device_id,
                    Event.collector.in_(("window_watcher", "browser_bridge")),
                    Event.ts >= window_start,
                )
            )
            .scalars()
            .all()
        )
        for e in window_events:
            d = datetime.fromtimestamp(e.ts, tz=UTC).date()
            apps = top_app_secs.get(d)
            if apps is None:
                continue
            label = e.data.get("app") or e.data.get("title") or e.data.get("url")
            if not label:
                continue
            apps[label] = apps.get(label, 0.0) + (e.duration or 0.0)

    entries = []
    for d in day_list:
        apps = top_app_secs[d]
        top_app = max(apps, key=apps.get) if apps else None
        entries.append(
            DayHistoryEntryOut(
                date=d.isoformat(),
                active_secs=by_day[d]["active"],
                idle_secs=by_day[d]["idle"],
                top_app=top_app,
            )
        )
    return entries


@router.get("/goals", response_model=list[GoalHistoryEntryOut])
def get_goals(
    system_name: str = Query(...),
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[GoalHistoryEntryOut]:
    employee = _resolve_employee_or_404(session, system_name)
    rows = (
        session.execute(
            select(Goal).where(Goal.employee_id == employee.employee_id).order_by(Goal.created_at.desc()).limit(limit)
        )
        .scalars()
        .all()
    )
    return [
        GoalHistoryEntryOut(goal_id=g.goal_id, text=g.text, created_at=g.created_at, deadline_at=g.deadline_at)
        for g in rows
    ]
