"""Employee dashboard endpoints ("My dashboard"). Every route requires a
logged-in dashboard session (server/dashboard_auth.py) and only ever returns
the logged-in employee's own data -- there is no parameter to ask for anyone
else's. Admins read other employees through /v1/admin/* instead.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from server.activity import build_segments, load_events, state_totals, window_totals
from server.config import get_settings
from server.dashboard_auth import current_employee
from server.dashboard_views import (
    HourOut,
    MessageOut,
    SegmentOut,
    StatusOut,
    TotalsOut,
    WindowOut,
    current_status,
    employee_devices,
    hour_blocks,
    local_midnight,
    recent_messages,
    segment_out,
    totals_out,
    window_out,
)
from server.db import get_session
from server.goals import current_goal
from server.models import Employee, Goal

router = APIRouter(prefix="/v1/me")


class GoalOut(BaseModel):
    text: str
    created_at: float
    deadline_at: float


class AppOut(BaseModel):
    app: str
    secs: float
    windows: list[WindowOut] = Field(default_factory=list)


class TodayOut(BaseModel):
    now: float
    day_start: float
    workday_secs: float
    employee_name: str
    device_name: str | None
    status: StatusOut
    totals: TotalsOut
    segments: list[SegmentOut]
    hours: list[HourOut]
    apps: list[AppOut]
    goal: GoalOut | None
    messages: list[MessageOut]


class DayOut(BaseModel):
    date: str  # YYYY-MM-DD, local
    day_start: float
    totals: TotalsOut
    top_windows: list[WindowOut]
    flagged_windows: list[WindowOut]


class SetGoalRequest(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    hours: float = Field(gt=0, le=24 * 14)


def _goal_out(goal: Goal | None) -> GoalOut | None:
    return GoalOut(text=goal.text, created_at=goal.created_at, deadline_at=goal.deadline_at) if goal else None


@router.get("/today", response_model=TodayOut)
def get_today(employee: Employee = Depends(current_employee), session: Session = Depends(get_session)) -> TodayOut:
    settings = get_settings()
    now = time.time()
    day_start = local_midnight(now)
    devices = employee_devices(session, employee.employee_id)
    device_ids = [d.device_id for d in devices]

    events = load_events(session, device_ids, day_start, now)
    segments = build_segments(
        events, day_start, now, settings.distraction_keywords, settings.distraction_exempt_keywords
    )
    status = current_status(
        devices[0] if devices else None,
        events,
        segments,
        now,
        settings.dashboard_offline_after_secs,
        settings.distraction_keywords,
        settings.distraction_exempt_keywords,
    )

    by_app: dict[str, AppOut] = {}
    for w in window_totals(segments):
        app = by_app.setdefault(w.app, AppOut(app=w.app, secs=0.0))
        app.secs += w.secs
        if len(app.windows) < 25:
            app.windows.append(window_out(w))
    apps = sorted(by_app.values(), key=lambda a: a.secs, reverse=True)
    for app in apps:
        app.secs = round(app.secs, 1)

    return TodayOut(
        now=now,
        day_start=day_start,
        workday_secs=settings.workday_hours * 3600,
        employee_name=employee.name,
        device_name=devices[0].device_name if devices else None,
        status=status,
        totals=totals_out(state_totals(segments)),
        segments=[segment_out(s) for s in segments],
        hours=hour_blocks(
            events, segments, day_start, now, settings.distraction_keywords, settings.distraction_exempt_keywords
        ),
        apps=apps[:10],
        goal=_goal_out(current_goal(session, employee.employee_id)),
        messages=recent_messages(session, device_ids, limit=20),
    )


@router.get("/week", response_model=list[DayOut])
def get_week(employee: Employee = Depends(current_employee), session: Session = Depends(get_session)) -> list[DayOut]:
    """The last 7 days including today, oldest first."""
    settings = get_settings()
    now = time.time()
    today = datetime.fromtimestamp(local_midnight(now))
    starts = [(today - timedelta(days=i)).timestamp() for i in range(6, -1, -1)]
    device_ids = [d.device_id for d in employee_devices(session, employee.employee_id)]
    events = load_events(session, device_ids, starts[0], now)

    days = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else now
        segments = build_segments(
            events, start, end, settings.distraction_keywords, settings.distraction_exempt_keywords
        )
        windows = window_totals(segments)
        days.append(
            DayOut(
                date=datetime.fromtimestamp(start).date().isoformat(),
                day_start=start,
                totals=totals_out(state_totals(segments)),
                top_windows=[window_out(w) for w in windows if not w.flag][:6],
                flagged_windows=[window_out(w) for w in windows if w.flag][:6],
            )
        )
    return days


@router.post("/goal", response_model=GoalOut)
def set_goal(
    body: SetGoalRequest, employee: Employee = Depends(current_employee), session: Session = Depends(get_session)
) -> GoalOut:
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Write what the goal is.")
    now = time.time()
    goal = Goal(employee_id=employee.employee_id, text=text, created_at=now, deadline_at=now + body.hours * 3600)
    session.add(goal)
    session.commit()
    return _goal_out(goal)
