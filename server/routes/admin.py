"""Admin dashboard endpoints ("Admin overview"). Every route requires a
logged-in session whose employee has role="admin" (server/dashboard_auth.py).

Window/tab titles are included only while ADMIN_SHOW_WINDOW_TITLES is on
(server/config.py); with it off, admins see app names and sites but never
what a title said.
"""
from __future__ import annotations

import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.activity import (
    build_segments,
    hourly_active,
    load_events,
    site_display_name,
    state_totals,
    window_totals,
)
from server.config import get_settings
from server.dashboard_auth import require_admin
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
from server.models import Employee

router = APIRouter(prefix="/v1/admin", dependencies=[Depends(require_admin)])

_TREND_HOURS = 24


def _trend_start(now: float) -> float:
    """Start of the 24 hourly trend buckets, on a whole hour, so the last
    bucket is the current (partial) hour and axis labels read 14:00, not 14:11.
    Rounded in local time: in a zone like IST (UTC+5:30) a UTC hour starts at :30."""
    hour_start = datetime.fromtimestamp(now).replace(minute=0, second=0, microsecond=0).timestamp()
    return hour_start - (_TREND_HOURS - 1) * 3600


class KpisOut(BaseModel):
    total: int
    active: int
    distraction: int
    idle: int  # idle + locked (away from the keyboard)
    offline: int  # agent not reporting, or never enrolled


class EmployeeRowOut(BaseModel):
    employee_id: str
    name: str
    email: str | None
    system_name: str
    role: str
    status: StatusOut
    last_active_at: float | None
    totals: TotalsOut


class TrendPointOut(BaseModel):
    hour_start: float
    active_secs: float


class SiteRowOut(BaseModel):
    employee_id: str
    employee_name: str
    title: str | None
    site: str | None
    secs: float


class SiteOut(BaseModel):
    keyword: str
    name: str
    secs: float
    rows: list[SiteRowOut] = Field(default_factory=list)


class OverviewOut(BaseModel):
    now: float
    day_start: float
    workday_secs: float
    show_titles: bool
    kpis: KpisOut
    employees: list[EmployeeRowOut]
    totals: TotalsOut
    trend: list[TrendPointOut]
    distracting_sites: list[SiteOut]
    messages: list[MessageOut]


class EmployeeDetailOut(EmployeeRowOut):
    show_titles: bool
    windows: list[WindowOut]
    segments: list[SegmentOut]
    hours: list[HourOut]
    messages: list[MessageOut]


class _Snapshot:
    """Everything the admin views need about one employee, computed once."""

    def __init__(self, session: Session, employee: Employee, now: float, settings):
        self.employee = employee
        self.devices = employee_devices(session, employee.employee_id)
        self.device_ids = [d.device_id for d in self.devices]
        day_start = local_midnight(now)
        self.day_start, self.now = day_start, now
        self.trend_start = _trend_start(now)
        events = load_events(session, self.device_ids, min(day_start, self.trend_start), now)
        self.events = events
        kw, ex = settings.distraction_keywords, settings.distraction_exempt_keywords
        self.segments_24h = build_segments(events, self.trend_start, now, kw, ex)
        self.segments_today = build_segments(events, day_start, now, kw, ex)
        self.status = current_status(
            self.devices[0] if self.devices else None,
            events,
            self.segments_today,
            now,
            settings.dashboard_offline_after_secs,
            kw,
            ex,
            show_titles=settings.admin_show_window_titles,
        )
        self.last_active_at = next(
            (s.end for s in reversed(self.segments_24h) if s.state in ("active", "distraction")), None
        )
        self.totals = state_totals(self.segments_today)
        self.windows = window_totals(self.segments_today)

    def row(self) -> EmployeeRowOut:
        e = self.employee
        return EmployeeRowOut(
            employee_id=e.employee_id,
            name=e.name,
            email=e.email,
            system_name=e.system_name,
            role=e.role,
            status=self.status,
            last_active_at=self.last_active_at,
            totals=totals_out(self.totals),
        )


@router.get("/overview", response_model=OverviewOut)
def overview(session: Session = Depends(get_session)) -> OverviewOut:
    settings = get_settings()
    show = settings.admin_show_window_titles
    now = time.time()
    employees = session.execute(select(Employee).order_by(Employee.name)).scalars().all()
    snaps = [_Snapshot(session, e, now, settings) for e in employees]

    kpis = KpisOut(total=len(snaps), active=0, distraction=0, idle=0, offline=0)
    org = {k: 0.0 for k in ("active", "distraction", "idle", "locked")}
    trend = [0.0] * _TREND_HOURS
    trend_start = _trend_start(now)
    sites: dict[str, SiteOut] = {}

    for snap in snaps:
        status = snap.status.status
        if status in ("active", "distraction"):
            setattr(kpis, status, getattr(kpis, status) + 1)
        elif status in ("idle", "locked"):
            kpis.idle += 1
        else:
            kpis.offline += 1
        for k, v in snap.totals.items():
            org[k] += v
        for i, secs in enumerate(hourly_active(snap.segments_24h, trend_start, _TREND_HOURS)):
            trend[i] += secs
        for w in snap.windows:
            if not w.flag:
                continue
            site = sites.setdefault(w.flag, SiteOut(keyword=w.flag, name=site_display_name(w.flag), secs=0.0))
            site.secs += w.secs
            site.rows.append(
                SiteRowOut(
                    employee_id=snap.employee.employee_id,
                    employee_name=snap.employee.name,
                    title=w.title if show else None,
                    site=w.site,
                    secs=round(w.secs, 1),
                )
            )

    for site in sites.values():
        site.secs = round(site.secs, 1)
        site.rows.sort(key=lambda r: r.secs, reverse=True)

    return OverviewOut(
        now=now,
        day_start=local_midnight(now),
        workday_secs=settings.workday_hours * 3600,
        show_titles=show,
        kpis=kpis,
        employees=[s.row() for s in snaps],
        totals=totals_out(org),
        trend=[
            TrendPointOut(hour_start=trend_start + i * 3600, active_secs=round(secs, 1))
            for i, secs in enumerate(trend)
        ],
        distracting_sites=sorted(sites.values(), key=lambda s: s.secs, reverse=True)[:8],
        messages=recent_messages(session, None, limit=20, show_titles=show),
    )


@router.get("/employees/{employee_id}", response_model=EmployeeDetailOut)
def employee_detail(employee_id: str, session: Session = Depends(get_session)) -> EmployeeDetailOut:
    settings = get_settings()
    show = settings.admin_show_window_titles
    employee = session.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=404, detail="No such employee.")
    snap = _Snapshot(session, employee, time.time(), settings)
    return EmployeeDetailOut(
        **snap.row().model_dump(),
        show_titles=show,
        windows=[window_out(w, show) for w in snap.windows[:40]],
        segments=[segment_out(s, show) for s in snap.segments_today],
        hours=hour_blocks(
            snap.events,
            snap.segments_today,
            snap.day_start,
            snap.now,
            settings.distraction_keywords,
            settings.distraction_exempt_keywords,
            show_titles=show,
        ),
        messages=recent_messages(session, snap.device_ids, limit=20, show_titles=show),
    )
