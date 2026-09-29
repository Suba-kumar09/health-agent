"""Response shapes and helpers shared by the employee (/v1/me) and admin
(/v1/admin) dashboard endpoints, so both views describe the same activity
the same way."""
from __future__ import annotations

import time
from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.activity import (
    DeviceEvents,
    Segment,
    WindowTotal,
    build_segments,
    clean_title,
    latest_window,
    window_totals,
)
from server.models import Device, Employee, Message


class WindowOut(BaseModel):
    app: str
    title: str | None  # None when an admin isn't allowed to see titles
    site: str | None
    flag: str | None  # the distraction keyword it matched, e.g. "youtube"
    secs: float = 0.0


class SegmentOut(BaseModel):
    state: str  # active | distraction | idle | locked
    start_ts: float
    end_ts: float
    windows: list[WindowOut] = Field(default_factory=list)


class TotalsOut(BaseModel):
    active: float = 0.0
    distraction: float = 0.0
    idle: float = 0.0
    locked: float = 0.0


class MessageOut(BaseModel):
    message_id: str
    kind: str
    text: str
    created_at: float
    label: str | None = None
    employee_id: str | None = None
    employee_name: str | None = None


class StatusOut(BaseModel):
    # active | distraction | idle | locked | offline | no_device
    status: str
    since: float | None = None
    last_seen_at: float | None = None
    on_screen: WindowOut | None = None


class HourOut(BaseModel):
    hour_start: float
    totals: TotalsOut
    windows: list[WindowOut] = Field(default_factory=list)


def hour_blocks(
    events: DeviceEvents,
    day_segments: list[Segment],
    day_start: float,
    now: float,
    keywords: list[str],
    exempt_keywords: list[str],
    show_titles: bool = True,
) -> list[HourOut]:
    """One entry per clock hour from `day_start` to now that had any activity.

    Time per state comes from clipping the whole day's segments, so the hours
    add up exactly to the day's totals. Windows are worked out per hour, so
    an hour only lists what was really on screen during it."""
    blocks: list[HourOut] = []
    hour = day_start
    while hour < now:
        end = min(hour + 3600, now)
        totals = {k: 0.0 for k in ("active", "distraction", "idle", "locked")}
        for seg in day_segments:
            overlap = min(seg.end, end) - max(seg.start, hour)
            if overlap > 0:
                totals[seg.state] += overlap
        if any(totals.values()):
            windows = window_totals(build_segments(events, hour, end, keywords, exempt_keywords))
            blocks.append(
                HourOut(
                    hour_start=hour,
                    totals=totals_out(totals),
                    windows=[window_out(w, show_titles) for w in windows[:15]],
                )
            )
        hour += 3600
    return blocks


def window_out(w: WindowTotal, show_titles: bool = True) -> WindowOut:
    return WindowOut(app=w.app, title=w.title if show_titles else None, site=w.site, flag=w.flag, secs=round(w.secs, 1))


def segment_out(seg: Segment, show_titles: bool = True, max_windows: int = 12) -> SegmentOut:
    return SegmentOut(
        state=seg.state,
        start_ts=seg.start,
        end_ts=seg.end,
        windows=[window_out(w, show_titles) for w in seg.top_windows()[:max_windows]],
    )


def totals_out(totals: dict[str, float]) -> TotalsOut:
    return TotalsOut(**{k: round(v, 1) for k, v in totals.items()})


def local_midnight(ts: float) -> float:
    return datetime.fromtimestamp(ts).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def employee_devices(session: Session, employee_id: str) -> list[Device]:
    """All of an employee's devices, most recently active first (an employee
    gets a new Device row each time a machine re-enrolls)."""
    return list(
        session.execute(
            select(Device)
            .where(Device.employee_id == employee_id)
            .order_by(func.coalesce(Device.last_seen_at, Device.enrolled_at).desc())
        )
        .scalars()
        .all()
    )


def current_status(
    device: Device | None,
    events: DeviceEvents,
    segments_today: list[Segment],
    now: float,
    offline_after_secs: float,
    keywords: list[str],
    exempt_keywords: list[str],
    show_titles: bool = True,
) -> StatusOut:
    if device is None:
        return StatusOut(status="no_device")

    window = latest_window(events, keywords, exempt_keywords)
    on_screen = (
        window_out(WindowTotal(window.app, window.title, window.site, window.flag), show_titles) if window else None
    )
    last_seen = device.last_seen_at
    if last_seen is None or now - last_seen > offline_after_secs:
        return StatusOut(status="offline", since=last_seen, last_seen_at=last_seen, on_screen=on_screen)

    raw = (events.afk[-1].data or {}).get("state") if events.afk else None
    if raw == "active":
        status = "distraction" if window is not None and window.flag else "active"
    elif raw == "locked":
        status = "locked"
    elif raw is None:
        status = "active" if window is not None else "idle"
    else:
        status = "idle"

    since = next((seg.start for seg in reversed(segments_today) if seg.state == status), last_seen)
    return StatusOut(status=status, since=since, last_seen_at=last_seen, on_screen=on_screen)


def recent_messages(
    session: Session, device_ids: list[str] | None, limit: int, show_titles: bool = True
) -> list[MessageOut]:
    """Latest messages, newest first. `device_ids=None` means every device
    (the admin feed); each row carries the employee it was sent to."""
    query = (
        select(Message, Employee)
        .join(Device, Device.device_id == Message.device_id)
        .outerjoin(Employee, Employee.employee_id == Device.employee_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    if device_ids is not None:
        if not device_ids:
            return []
        query = query.where(Message.device_id.in_(device_ids))
    return [
        MessageOut(
            message_id=m.message_id,
            kind=m.kind,
            # A distraction message usually names the tab it was about, so
            # hiding titles has to hide its text too.
            text=m.text if show_titles or m.kind != "distraction" else "Distraction reminder sent.",
            created_at=m.created_at,
            # Cleaned the same way as window titles, so a message's label
            # matches the timeline entry it was about.
            label=clean_title(m.label) if show_titles and m.label else None,
            employee_id=e.employee_id if e else None,
            employee_name=e.name if e else None,
        )
        for m, e in session.execute(query).all()
    ]


def now_ts() -> float:
    return time.time()
