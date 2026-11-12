from __future__ import annotations

import uuid

from server.models import Device, Message
from server.policy import is_allowed


def _make_device(db_session, device_id: str = "dev-1") -> Device:
    device = Device(
        device_id=device_id,
        device_token_hash="hash",
        device_name="test-laptop",
        os="Windows",
        os_version="11",
    )
    db_session.add(device)
    db_session.commit()
    return device


def _add_message(db_session, device_id: str, created_at: float, kind: str = "break"):
    message = Message(
        message_id=str(uuid.uuid4()), device_id=device_id, text="x", kind=kind, created_at=created_at
    )
    db_session.add(message)
    db_session.commit()
    return message


def test_allowed_with_no_prior_messages(db_session):
    _make_device(db_session)
    assert is_allowed(
        db_session, "dev-1", cooldown_secs=60, daily_limit=10, quiet_hours_start=0, quiet_hours_end=0,
        now=1_700_000_000.0,
    )


def test_blocked_within_cooldown_regardless_of_kind(db_session):
    # A "break" message's cooldown must also block a "distraction"/"idle"
    # message right after -- cooldown is a per-device, cross-agent rule.
    _make_device(db_session)
    _add_message(db_session, "dev-1", created_at=1_700_000_000.0, kind="break")

    allowed = is_allowed(
        db_session, "dev-1", cooldown_secs=60, daily_limit=10, quiet_hours_start=0, quiet_hours_end=0,
        now=1_700_000_030.0,  # 30s later, inside the 60s cooldown
    )

    assert allowed is False


def test_allowed_after_cooldown_elapses(db_session):
    _make_device(db_session)
    _add_message(db_session, "dev-1", created_at=1_700_000_000.0, kind="break")

    allowed = is_allowed(
        db_session, "dev-1", cooldown_secs=60, daily_limit=10, quiet_hours_start=0, quiet_hours_end=0,
        now=1_700_000_120.0,  # 120s later, past the 60s cooldown
    )

    assert allowed is True


def test_blocked_once_daily_limit_reached(db_session):
    _make_device(db_session)
    base = 1_700_000_000.0
    for i in range(3):
        _add_message(db_session, "dev-1", created_at=base + i)

    allowed = is_allowed(
        db_session, "dev-1", cooldown_secs=0, daily_limit=3, quiet_hours_start=0, quiet_hours_end=0,
        now=base + 100,
    )

    assert allowed is False


def test_daily_limit_resets_on_a_new_day(db_session):
    _make_device(db_session)
    # 3 messages "yesterday" (2023-11-14), far enough before `now` to fall on
    # a different local calendar day.
    yesterday = 1_699_900_000.0
    for i in range(3):
        _add_message(db_session, "dev-1", created_at=yesterday + i)

    allowed = is_allowed(
        db_session, "dev-1", cooldown_secs=0, daily_limit=3, quiet_hours_start=0, quiet_hours_end=0,
        now=1_700_000_000.0,  # a later day
    )

    assert allowed is True


def test_quiet_hours_disabled_when_start_equals_end(db_session):
    _make_device(db_session)
    # start == end (0, 0) means the check is off entirely, regardless of hour.
    allowed = is_allowed(
        db_session, "dev-1", cooldown_secs=0, daily_limit=10, quiet_hours_start=0, quiet_hours_end=0,
        now=1_700_000_000.0,
    )
    assert allowed is True


def test_blocked_during_quiet_hours_same_day_window(db_session):
    import datetime

    _make_device(db_session)
    # A timestamp at local hour 23 falls inside a 22-7 quiet window.
    now = datetime.datetime(2024, 1, 1, 23, 0, 0).timestamp()

    allowed = is_allowed(
        db_session, "dev-1", cooldown_secs=0, daily_limit=10, quiet_hours_start=22, quiet_hours_end=7, now=now
    )

    assert allowed is False


def test_allowed_outside_quiet_hours_window(db_session):
    import datetime

    _make_device(db_session)
    now = datetime.datetime(2024, 1, 1, 12, 0, 0).timestamp()

    allowed = is_allowed(
        db_session, "dev-1", cooldown_secs=0, daily_limit=10, quiet_hours_start=22, quiet_hours_end=7, now=now
    )

    assert allowed is True
