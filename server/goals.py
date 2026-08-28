"""Detects continuous "distraction" (a foreground window/tab matching a
known entertainment keyword) and turns it into a short LLM-generated
reminder -- pulling in the employee's current goal/deadline when one exists,
but never requiring one. Mirrors server/wellbeing.py's shape; kept as a
separate module since it's a related-but-distinct concern.

`generate_distraction_reminder_for_device` is the entry point, called on a
timer from `server.main`'s lifespan-managed scheduler, same failure-isolation
contract as `wellbeing.generate_for_device`: a device that isn't currently
distracted, or an unreachable/slow LLM, must not block or crash the tick for
other devices.
"""
from __future__ import annotations

import logging
import time

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.models import Device, Event, Goal, Message
from server.wellbeing import _STREAK_GAP_BREAK_SECS, call_llm

logger = logging.getLogger(__name__)

_DISTRACTION_COLLECTORS = ("window_watcher", "browser_bridge")

_PROMPT_WITH_GOAL = (
    "You are a caring accountability companion. Real activity tracking on this "
    "person's computer shows they have been continuously on '{title}' for "
    "{minutes:.0f} minutes instead of working. Their stated goal today is: "
    "'{goal_text}', due in {remaining_minutes:.0f} minutes. Write ONE short, "
    "direct sentence telling them to get back to their goal now -- mention "
    "what they've been watching/doing, how long, and the goal or time "
    "remaining. Be concrete, not vague.\n\n"
    "Your one-sentence reminder:"
)

_PROMPT_NO_GOAL = (
    "You are a caring accountability companion. Real activity tracking on this "
    "person's computer shows they have been continuously on '{title}' for "
    "{minutes:.0f} minutes. Write ONE short, warm sentence suggesting they "
    "wrap up and get back to work -- mention what they've been watching/doing "
    "and how long, specifically. Be concrete, not vague.\n\n"
    "Your one-sentence reminder:"
)


def _matches_keyword(data: dict, keywords: list[str]) -> bool:
    haystack = " ".join(str(data.get(field, "")) for field in ("title", "url", "app")).lower()
    return any(keyword in haystack for keyword in keywords)


def _distraction_label(data: dict) -> str:
    return data.get("title") or data.get("url") or data.get("app") or "that"


def continuous_distraction_streak(
    session: Session, device_id: str, keywords: list[str]
) -> tuple[float, float, str] | None:
    """(total_distracted_secs, streak_start_ts, latest_label) for `device_id`'s
    current unbroken run of keyword-matching window/tab events, or None if
    the most recent window_watcher/browser_bridge event doesn't match.

    Same walk-backward-and-sum structure (and the same
    `_STREAK_GAP_BREAK_SECS` gap-break rule) as
    wellbeing.continuous_active_streak, but keyed on a keyword match against
    the event's title/url/app instead of an explicit afk state.
    """
    events = (
        session.execute(
            select(Event)
            .where(Event.device_id == device_id, Event.collector.in_(_DISTRACTION_COLLECTORS))
            .order_by(Event.ts.desc())
        )
        .scalars()
        .all()
    )
    if not events or not _matches_keyword(events[0].data, keywords):
        return None

    total = 0.0
    streak_start_ts = events[0].ts
    latest_label = _distraction_label(events[0].data)
    prev_row_start: float | None = None
    for event in events:
        if not _matches_keyword(event.data, keywords):
            break
        if prev_row_start is not None:
            gap = prev_row_start - (event.ts + (event.duration or 0.0))
            if gap > _STREAK_GAP_BREAK_SECS:
                break
        total += event.duration or 0.0
        streak_start_ts = event.ts
        prev_row_start = event.ts
    return total, streak_start_ts, latest_label


def current_goal(session: Session, employee_id: str | None) -> Goal | None:
    if employee_id is None:
        return None
    now = time.time()
    return (
        session.execute(
            select(Goal)
            .where(Goal.employee_id == employee_id, Goal.deadline_at > now)
            .order_by(Goal.created_at.desc())
        )
        .scalars()
        .first()
    )


def generate_distraction_reminder_for_device(
    session: Session,
    device: Device,
    ollama_url: str,
    model: str,
    keywords: list[str],
    threshold_secs: float,
) -> Message | None:
    """Checks whether `device` has been continuously on a distracting
    site/app for at least `threshold_secs`, regardless of whether an active
    goal exists -- a goal only changes the prompt's content, it is never a
    prerequisite for sending a reminder. Returns None (logging a warning on
    an LLM failure) if there's nothing to send; never raises.
    """
    streak = continuous_distraction_streak(session, device.device_id, keywords)
    if streak is None:
        return None
    total_secs, streak_start_ts, label = streak
    if total_secs < threshold_secs:
        return None

    last_message = (
        session.execute(
            select(Message)
            .where(Message.device_id == device.device_id, Message.kind == "distraction")
            .order_by(Message.created_at.desc())
        )
        .scalars()
        .first()
    )
    if last_message is not None and last_message.created_at >= streak_start_ts:
        return None  # already notified for this streak

    goal = current_goal(session, device.employee_id)
    minutes = total_secs / 60
    if goal is not None:
        remaining_minutes = max((goal.deadline_at - time.time()) / 60, 0.0)
        prompt = _PROMPT_WITH_GOAL.format(
            title=label, minutes=minutes, goal_text=goal.text, remaining_minutes=remaining_minutes
        )
    else:
        prompt = _PROMPT_NO_GOAL.format(title=label, minutes=minutes)

    try:
        text = call_llm(prompt, ollama_url, model)
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.warning("Distraction message generation failed for device %s: %s", device.device_id, exc)
        return None

    message = Message(device_id=device.device_id, text=text, kind="distraction")
    session.add(message)
    session.flush()
    return message
