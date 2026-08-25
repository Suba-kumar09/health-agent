from __future__ import annotations

import uuid

from server.models import Device, Event, Message
from server.wellbeing import continuous_active_streak, generate_for_device


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


def _generate(db_session, device, threshold_secs: float = 1800):
    return generate_for_device(
        db_session, device, ollama_url="http://unused", model="unused", break_threshold_secs=threshold_secs
    )


def _add_afk_event(db_session, device_id: str, ts: float, state: str, duration: float):
    event = Event(
        event_id=str(uuid.uuid4()),
        device_id=device_id,
        collector="afk",
        ts=ts,
        duration=duration,
        data={"state": state},
        batch_id="batch-1",
    )
    db_session.add(event)
    db_session.commit()
    return event


def test_continuous_active_streak_none_with_no_afk_history(db_session):
    _make_device(db_session)
    assert continuous_active_streak(db_session, "dev-1") is None


def test_continuous_active_streak_none_when_currently_afk(db_session):
    _make_device(db_session)
    _add_afk_event(db_session, "dev-1", ts=1000.0, state="afk", duration=60.0)
    assert continuous_active_streak(db_session, "dev-1") is None


def test_continuous_active_streak_sums_consecutive_active_rows(db_session):
    # Simulates a real streak split across sync-interval boundaries: several
    # "active" rows in a row, each closed out by a batch upload, before the
    # next poll opens a fresh one (see coalescing.py's extend_duration gate).
    _make_device(db_session)
    _add_afk_event(db_session, "dev-1", ts=1000.0, state="active", duration=100.0)
    _add_afk_event(db_session, "dev-1", ts=1100.0, state="active", duration=200.0)
    _add_afk_event(db_session, "dev-1", ts=1300.0, state="active", duration=50.0)

    result = continuous_active_streak(db_session, "dev-1")

    assert result is not None
    total_secs, streak_start_ts = result
    assert total_secs == 350.0
    assert streak_start_ts == 1000.0


def test_continuous_active_streak_stops_at_last_afk_break(db_session):
    _make_device(db_session)
    _add_afk_event(db_session, "dev-1", ts=1000.0, state="active", duration=999.0)  # before the break -- ignored
    _add_afk_event(db_session, "dev-1", ts=2000.0, state="afk", duration=60.0)
    _add_afk_event(db_session, "dev-1", ts=2100.0, state="active", duration=120.0)

    total_secs, streak_start_ts = continuous_active_streak(db_session, "dev-1")

    assert total_secs == 120.0
    assert streak_start_ts == 2100.0


def test_continuous_active_streak_stops_at_a_large_gap_between_active_rows(db_session):
    # Regression test: two "active" rows separated by a multi-day gap (e.g.
    # the agent wasn't running in between) must not be treated as one
    # unbroken streak, even though neither row is literally "afk" -- see
    # _STREAK_GAP_BREAK_SECS.
    _make_device(db_session)
    _add_afk_event(db_session, "dev-1", ts=1000.0, state="active", duration=50.0)  # days ago -- ignored
    _add_afk_event(db_session, "dev-1", ts=1000.0 + 4 * 86400, state="active", duration=30.0)

    total_secs, streak_start_ts = continuous_active_streak(db_session, "dev-1")

    assert total_secs == 30.0
    assert streak_start_ts == 1000.0 + 4 * 86400


def test_generate_for_device_none_when_under_threshold(db_session):
    device = _make_device(db_session)
    _add_afk_event(db_session, "dev-1", ts=1000.0, state="active", duration=60.0)

    assert _generate(db_session, device) is None


def test_generate_for_device_persists_message_over_threshold(db_session, monkeypatch):
    device = _make_device(db_session)
    _add_afk_event(db_session, "dev-1", ts=1000.0, state="active", duration=1900.0)

    def fake_call_llm(minutes, ollama_url, model):
        return "take a break, you've earned it!"

    monkeypatch.setattr("server.wellbeing.call_llm", fake_call_llm)

    result = _generate(db_session, device)

    assert result is not None
    assert result.text == "take a break, you've earned it!"
    stored = db_session.query(Message).filter_by(device_id="dev-1").one()
    assert stored.text == "take a break, you've earned it!"


def test_generate_for_device_returns_none_on_llm_failure(db_session, monkeypatch):
    device = _make_device(db_session)
    _add_afk_event(db_session, "dev-1", ts=1000.0, state="active", duration=1900.0)

    def _boom(minutes, ollama_url, model):
        raise ValueError("bad response")

    monkeypatch.setattr("server.wellbeing.call_llm", _boom)

    result = _generate(db_session, device)

    assert result is None
    assert db_session.query(Message).count() == 0


def test_generate_for_device_does_not_renotify_same_streak(db_session, monkeypatch):
    device = _make_device(db_session)
    _add_afk_event(db_session, "dev-1", ts=1000.0, state="active", duration=1900.0)
    db_session.add(
        Message(message_id=str(uuid.uuid4()), device_id="dev-1", text="already told them", created_at=1500.0)
    )
    db_session.commit()

    def fail_if_called(minutes, ollama_url, model):
        raise AssertionError("should not be called -- already notified this streak")

    monkeypatch.setattr("server.wellbeing.call_llm", fail_if_called)

    result = _generate(db_session, device)

    assert result is None
    assert db_session.query(Message).count() == 1


def test_generate_for_device_renotifies_after_a_new_break(db_session, monkeypatch):
    device = _make_device(db_session)
    # Notified for an earlier streak...
    db_session.add(
        Message(message_id=str(uuid.uuid4()), device_id="dev-1", text="earlier reminder", created_at=1500.0)
    )
    db_session.commit()
    # ...they took a break...
    _add_afk_event(db_session, "dev-1", ts=1600.0, state="afk", duration=300.0)
    # ...and started a fresh streak, now over threshold.
    _add_afk_event(db_session, "dev-1", ts=1900.0, state="active", duration=1900.0)

    def fake_call_llm(minutes, ollama_url, model):
        return "new streak reminder"

    monkeypatch.setattr("server.wellbeing.call_llm", fake_call_llm)

    result = _generate(db_session, device)

    assert result is not None
    assert result.text == "new streak reminder"
