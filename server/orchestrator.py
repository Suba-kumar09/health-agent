"""Picks which single agent, if any, gets to message a device on a given
tick, then gates that choice through the Policy Engine before letting the
agent actually call its LLM.

Three agents compete for the same device on every tick:
  - Distraction Agent (server/goals.py)   -- on a keyword-matching site/app
  - Productivity Agent (server/productivity.py) -- idle too long
  - Notifier (server/wellbeing.py)        -- continuously active, no break

A device can only ever be in one of these three states at once EXCEPT
Distraction vs. Notifier, which can both be true simultaneously (being on a
distracting site still counts as "active" for afk purposes) -- hence the
explicit _PRIORITY order below: Distraction wins over Notifier when both
conditions are met, since "you're on YouTube" is more actionable than a
generic break reminder. Idle and Distraction/Notifier are mutually
exclusive by construction (idle requires afk state == "afk"; the other two
both require recent activity), but Idle is still ranked in the same list for
a single, explicit, easy-to-audit priority order rather than special-casing.

Distraction itself is content-aware, not just site-aware: a window/tab only
counts as a distraction if it matches DISTRACTION_KEYWORDS and does NOT also
match DISTRACTION_EXEMPT_KEYWORDS (e.g. a YouTube tab titled "Linear Algebra
Lecture 3" matches "youtube" but is exempted by "lecture") -- see
goals._is_distracting. Exempt content simply never fires anything; there is
no separate agent for it.

Each candidate check here is a cheap DB-only streak lookup (no LLM call) --
the LLM is only ever invoked for the one agent that actually wins routing
*and* clears the Policy Engine gate, via that agent's own generate_for_device.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from server import policy, productivity, wellbeing
from server.config import get_settings
from server.db import session_scope
from server.goals import continuous_distraction_streak, generate_distraction_reminder_for_device
from server.models import Device, Message
from server.wellbeing import generate_for_device

logger = logging.getLogger(__name__)

_DISTRACTION = "distraction"
_PRODUCTIVITY = "idle"
_NOTIFIER = "break"

# Order matters -- first match wins. See module docstring.
_PRIORITY = (_DISTRACTION, _PRODUCTIVITY, _NOTIFIER)


def _candidate(kind: str, session: Session, device: Device, settings) -> bool:
    """Cheap DB-only check: would this agent's streak condition currently
    fire, ignoring dedup/Policy Engine? True/False only, no LLM call."""
    if kind == _DISTRACTION:
        if not settings.distraction_enabled:
            return False
        streak = continuous_distraction_streak(
            session, device.device_id, settings.distraction_keywords, settings.distraction_exempt_keywords
        )
        return streak is not None and streak[0] >= settings.distraction_threshold_secs
    if kind == _PRODUCTIVITY:
        if not settings.productivity_enabled:
            return False
        streak = productivity.continuous_idle_streak(session, device.device_id)
        return streak is not None and streak[0] >= settings.productivity_idle_threshold_secs
    if kind == _NOTIFIER:
        if not settings.wellbeing_enabled:
            return False
        streak = wellbeing.continuous_active_streak(session, device.device_id)
        return streak is not None and streak[0] >= settings.wellbeing_break_threshold_secs
    raise ValueError(f"unknown agent kind: {kind}")  # pragma: no cover - programmer error


def _fire(kind: str, session: Session, device: Device, settings) -> Message | None:
    """Calls the winning agent's real generate_for_device -- this is where
    the LLM is actually invoked and, on success, a Message persisted."""
    if kind == _DISTRACTION:
        return generate_distraction_reminder_for_device(
            session,
            device,
            settings.wellbeing_model,
            settings.distraction_keywords,
            settings.distraction_exempt_keywords,
            settings.distraction_threshold_secs,
        )
    if kind == _PRODUCTIVITY:
        return productivity.generate_for_device(
            session,
            device,
            settings.wellbeing_model,
            settings.productivity_idle_threshold_secs,
            settings.distraction_exempt_keywords,
        )
    if kind == _NOTIFIER:
        return generate_for_device(
            session,
            device,
            settings.wellbeing_model,
            settings.wellbeing_break_threshold_secs,
        )
    raise ValueError(f"unknown agent kind: {kind}")  # pragma: no cover - programmer error


def route_device(session: Session, device: Device, settings) -> Message | None:
    """Picks the highest-priority agent whose condition is currently met,
    checks the Policy Engine, and -- only if both pass -- fires that agent.
    Returns the persisted Message, or None if nothing was sent (no agent's
    condition was met, the Policy Engine blocked it, or the winning agent's
    own dedup/LLM-failure check returned None).
    """
    winner = next((kind for kind in _PRIORITY if _candidate(kind, session, device, settings)), None)
    if winner is None:
        return None

    if settings.policy_enabled and not policy.is_allowed(
        session,
        device.device_id,
        settings.policy_cooldown_secs,
        settings.policy_daily_message_limit,
        settings.policy_quiet_hours_start,
        settings.policy_quiet_hours_end,
    ):
        return None

    return _fire(winner, session, device, settings)


def run_orchestrator_tick() -> None:
    """One pass over all enrolled devices. Per-device try/except mirrors the
    existing wellbeing/distraction ticks -- a bad device or a slow/unreachable
    LLM must not block the tick for the rest.
    """
    settings = get_settings()
    with session_scope() as session:
        devices = session.execute(select(Device)).scalars().all()
        for device in devices:
            try:
                route_device(session, device, settings)
            except Exception:
                logger.exception("Orchestrator tick failed for device %s", device.device_id)
