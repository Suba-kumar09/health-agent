"""Detects "you've been idle too long" moments from a device's `afk` events,
and turns them into a short LLM-generated reminder via the OpenAI API -- the
mirror image of server/wellbeing.py, which watches for the opposite condition
(continuously *active*, no break).

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

from server.goals import _DISTRACTION_COLLECTORS, _distraction_label, _matches_keyword
from server.models import Device, Event, Message
from server.wellbeing import _STREAK_GAP_BREAK_SECS, call_llm

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = (
    "You are a direct productivity accountability companion. Real activity tracking on this "
    "person's computer shows they have been idle, with no keyboard or mouse activity, for "
    "{minutes:.0f} minutes. Write ONE short, firm sentence telling them to stop being idle and "
    "get back to work now -- mention the {minutes:.0f} minutes specifically. Do NOT suggest "
    "taking a break or resting; they are already idle, the goal is to get them working again. "
    "Be concrete and direct, not vague.\n\n"
    "Your one-sentence reminder:"
)

_PROMPT_TEMPLATE_STUDY_CONTEXT = (
    "You are a direct productivity accountability companion. Real activity tracking on this "
    "person's computer shows they have been idle, with no keyboard or mouse activity, for "
    "{minutes:.0f} minutes, while '{title}' was open on their screen -- likely something they were "
    "studying or learning from. Write ONE short sentence checking in: ask if they're still "
    "following along, or suggest an actual break if they've drifted off -- mention the "
    "{minutes:.0f} minutes and what was open, specifically. Be concrete, not vague.\n\n"
    "Your one-sentence check-in:"
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


def _current_study_context(session: Session, device_id: str, exempt_keywords: list[str]) -> str | None:
    """Label (title/url/app) of the most recent window_watcher/browser_bridge
    event for `device_id`, if it matches a study/exempt keyword -- None if
    there's no recent window event, or it isn't study-related. Deliberately
    just "most recent", not a continuous streak like goals.py's distraction
    detection -- this only needs to know what was likely on screen while the
    person went idle, not how long they'd been on it."""
    event = (
        session.execute(
            select(Event)
            .where(Event.device_id == device_id, Event.collector.in_(_DISTRACTION_COLLECTORS))
            .order_by(Event.ts.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if event is None or not _matches_keyword(event.data, exempt_keywords):
        return None
    return _distraction_label(event.data)


def generate_for_device(
    session: Session,
    device: Device,
    model: str,
    idle_threshold_secs: float,
    exempt_keywords: list[str],
) -> Message | None:
    """Checks whether `device` has been continuously idle for at least
    `idle_threshold_secs`, and -- if it hasn't already been notified about
    this specific idle streak -- generates a check-in reminder grounded in
    the real idle-duration number. If study/learning content (per
    `exempt_keywords`, the same list goals.py uses to exempt distraction
    detection) was open when they went idle, names it and asks if they're
    still following along instead of the generic "get back to work" wording.
    Returns None (logging a warning on an LLM failure) if there's nothing to
    send; never raises.
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

    study_label = _current_study_context(session, device.device_id, exempt_keywords)
    minutes = total_secs / 60
    prompt = (
        _PROMPT_TEMPLATE_STUDY_CONTEXT.format(minutes=minutes, title=study_label)
        if study_label
        else _PROMPT_TEMPLATE.format(minutes=minutes)
    )

    try:
        text = call_llm(prompt, model)
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.warning("Productivity message generation failed for device %s: %s", device.device_id, exc)
        return None

    message = Message(device_id=device.device_id, text=text, kind="idle")
    session.add(message)
    session.flush()
    return message
