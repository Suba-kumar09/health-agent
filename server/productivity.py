"""Detects "you've been idle too long" moments from a device's `afk` events,
and turns them into a short LLM-generated reminder via a local Ollama
instance -- the mirror image of server/wellbeing.py, which watches for the
opposite condition (continuously *active*, no break).

`generate_for_device` is the entry point, called from the Orchestrator
(server/orchestrator.py) once it has decided this is the device's turn and
the Policy Engine has allowed it. Same failure-isolation contract as
wellbeing.generate_for_device: never raises, so one bad device or an
unreachable LLM can't break the tick for the rest.
"""
from __future__ import annotations

import logging

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.models import Device, Event, Message
from server.wellbeing import _STREAK_GAP_BREAK_SECS, call_llm

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = (
    "You are a caring accountability companion. Real activity tracking on this person's "
    "computer shows they have been idle, with no keyboard or mouse activity, for "
    "{minutes:.0f} minutes. Write ONE short, warm sentence checking in and nudging them "
    "back to work -- mention the {minutes:.0f} minutes specifically. Be concrete and "
    "direct, not vague encouragement.\n\n"
    "Your one-sentence reminder:"
)


def continuous_idle_streak(session: Session, device_id: str) -> tuple[float, float] | None:
    """(total_idle_secs, streak_start_ts) for `device_id`'s current unbroken
    idle streak, or None if it isn't currently mid-streak (latest afk state
    is "active", or there's no afk history yet).

    Same walk-backward-and-sum structure (and the same _STREAK_GAP_BREAK_SECS
    gap-break rule) as wellbeing.continuous_active_streak, but keyed on
    state == "afk" instead of "active".
    """
    afk_events = (
        session.execute(
            select(Event).where(Event.device_id == device_id, Event.collector == "afk").order_by(Event.ts.desc())
        )
        .scalars()
        .all()
    )
    if not afk_events or afk_events[0].data.get("state") != "afk":
        return None

    total = 0.0
    streak_start_ts = afk_events[0].ts
    prev_row_start: float | None = None
    for event in afk_events:
        if event.data.get("state") != "afk":
            break
        if prev_row_start is not None:
            gap = prev_row_start - (event.ts + (event.duration or 0.0))
            if gap > _STREAK_GAP_BREAK_SECS:
                break
        total += event.duration or 0.0
        streak_start_ts = event.ts
        prev_row_start = event.ts
    return total, streak_start_ts


def generate_for_device(
    session: Session,
    device: Device,
    ollama_url: str,
    model: str,
    idle_threshold_secs: float,
) -> Message | None:
    """Checks whether `device` has been continuously idle for at least
    `idle_threshold_secs`, and -- if it hasn't already been notified about
    this specific idle streak -- generates a check-in reminder grounded in
    the real idle-duration number. Returns None (logging a warning on an LLM
    failure) if there's nothing to send; never raises.
    """
    streak = continuous_idle_streak(session, device.device_id)
    if streak is None:
        return None
    total_secs, streak_start_ts = streak
    if total_secs < idle_threshold_secs:
        return None

    last_message = (
        session.execute(
            select(Message)
            .where(Message.device_id == device.device_id, Message.kind == "idle")
            .order_by(Message.created_at.desc())
        )
        .scalars()
        .first()
    )
    if last_message is not None and last_message.created_at >= streak_start_ts:
        return None  # already notified for this idle streak

    try:
        text = call_llm(_PROMPT_TEMPLATE.format(minutes=total_secs / 60), ollama_url, model)
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.warning("Productivity message generation failed for device %s: %s", device.device_id, exc)
        return None

    message = Message(device_id=device.device_id, text=text, kind="idle")
    session.add(message)
    session.flush()
    return message
