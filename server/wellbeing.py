"""Detects "you've been working continuously with no break" moments from a
device's `afk` events, and turns them into a short LLM-generated reminder via
a local Ollama instance.

`generate_for_device` is the entry point, called on a timer from
`server.main`'s lifespan-managed scheduler. It is deliberately
failure-tolerant -- a device that isn't mid-streak, or an unreachable/slow
LLM, must not block or crash the tick for other devices.
"""
from __future__ import annotations

import logging

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.models import Device, Event, Message

logger = logging.getLogger(__name__)

# If two consecutive "active" afk rows are separated by more than this, treat
# it as a break in the streak even though neither row is literally "afk" --
# a gap this large almost always means the agent simply wasn't running (the
# device was off, asleep, or the agent was restarted), not that someone
# worked continuously across it. Without this, a streak that started days
# ago across multiple separate agent sessions reads as one unbroken stretch,
# and (worse) permanently suppresses new messages once any message has ever
# been sent partway through it -- see generate_for_device's last_message
# check below.
_STREAK_GAP_BREAK_SECS = 600.0

_PROMPT_TEMPLATE = (
    "You are a caring wellbeing companion. Real activity tracking on this person's "
    "computer shows they have been continuously active, with no break, for "
    "{minutes:.0f} minutes. Write ONE short, warm sentence telling them to take a "
    "short break now -- mention the {minutes:.0f} minutes specifically, and that "
    "their body needs rest. Be concrete and direct, not vague encouragement.\n\n"
    "Your one-sentence reminder:"
)


def continuous_active_streak(session: Session, device_id: str) -> tuple[float, float] | None:
    """(total_active_secs, streak_start_ts) for `device_id`'s current unbroken
    active streak, or None if it isn't currently mid-streak (latest afk state
    is "afk", or there's no afk history yet).

    Summed across however many separate `afk` event rows the streak is split
    into -- each sync-interval tick "freezes" the in-progress row once a batch
    claims it (extend_duration only works on synced=0, batch_id IS NULL rows;
    see agent/collectors/coalescing.py), so a long real-world streak is not
    one long row, it's a consecutive run of same-state rows to sum.
    """
    afk_events = (
        session.execute(
            select(Event).where(Event.device_id == device_id, Event.collector == "afk").order_by(Event.ts.desc())
        )
        .scalars()
        .all()
    )
    if not afk_events or afk_events[0].data.get("state") != "active":
        return None

    total = 0.0
    streak_start_ts = afk_events[0].ts
    prev_row_start: float | None = None
    for event in afk_events:
        if event.data.get("state") != "active":
            break
        if prev_row_start is not None:
            gap = prev_row_start - (event.ts + (event.duration or 0.0))
            if gap > _STREAK_GAP_BREAK_SECS:
                break
        total += event.duration or 0.0
        streak_start_ts = event.ts
        prev_row_start = event.ts
    return total, streak_start_ts


def call_llm(minutes: float, ollama_url: str, model: str, timeout: float = 30.0) -> str:
    resp = httpx.post(
        f"{ollama_url.rstrip('/')}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "user", "content": _PROMPT_TEMPLATE.format(minutes=minutes)}],
            "stream": False,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"].strip()


def generate_for_device(
    session: Session,
    device: Device,
    ollama_url: str,
    model: str,
    break_threshold_secs: float,
) -> Message | None:
    """Checks whether `device` has been continuously active for at least
    `break_threshold_secs`, and -- if it hasn't already been notified about
    this specific streak -- generates a "take a break" reminder grounded in
    the real continuous-duration number. Returns None (logging a warning on
    an LLM failure) if there's nothing to send; never raises, so one bad
    device can't break the tick for the rest.
    """
    streak = continuous_active_streak(session, device.device_id)
    if streak is None:
        return None
    total_secs, streak_start_ts = streak
    if total_secs < break_threshold_secs:
        return None

    last_message = (
        session.execute(
            select(Message).where(Message.device_id == device.device_id).order_by(Message.created_at.desc())
        )
        .scalars()
        .first()
    )
    if last_message is not None and last_message.created_at >= streak_start_ts:
        return None  # already notified for this streak

    try:
        text = call_llm(total_secs / 60, ollama_url, model)
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.warning("Wellbeing message generation failed for device %s: %s", device.device_id, exc)
        return None

    message = Message(device_id=device.device_id, text=text)
    session.add(message)
    session.flush()
    return message
