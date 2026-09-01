"""Gatekeeper checked by the Orchestrator (server/orchestrator.py) right
before it lets a chosen agent actually call its LLM and send a message.

Deliberately answers one question only -- "is this device allowed to
receive any message right now" -- and knows nothing about which agent wants
to send or what it would say. Each agent's own dedup check (e.g.
wellbeing.generate_for_device's "already notified for this streak") stays in
that agent, since it depends on agent-specific state (streak boundaries);
this module only enforces the cross-agent rules that have to live in one
shared place: don't spam, don't message too often, don't message at night.
"""
from __future__ import annotations

import time
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.models import Message


def is_allowed(
    session: Session,
    device_id: str,
    cooldown_secs: float,
    daily_limit: int,
    quiet_hours_start: int,
    quiet_hours_end: int,
    now: float | None = None,
) -> bool:
    """True if a new message (of any kind) may be sent to `device_id` right
    now. `quiet_hours_start`/`quiet_hours_end` are local hours in [0, 24);
    pass equal values (e.g. 0, 0) to disable the quiet-hours check entirely.
    """
    now = time.time() if now is None else now

    if _in_quiet_hours(now, quiet_hours_start, quiet_hours_end):
        return False

    last_message = (
        session.execute(
            select(Message).where(Message.device_id == device_id).order_by(Message.created_at.desc())
        )
        .scalars()
        .first()
    )
    if last_message is not None and (now - last_message.created_at) < cooldown_secs:
        return False

    day_start = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    today_count = session.execute(
        select(func.count())
        .select_from(Message)
        .where(Message.device_id == device_id, Message.created_at >= day_start)
    ).scalar_one()
    if today_count >= daily_limit:
        return False

    return True


def _in_quiet_hours(now: float, start_hour: int, end_hour: int) -> bool:
    if start_hour == end_hour:
        return False  # disabled
    hour = datetime.fromtimestamp(now).hour
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour  # wraps past midnight, e.g. 22 -> 7
