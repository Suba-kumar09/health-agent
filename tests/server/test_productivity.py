from __future__ import annotations

import uuid

from server.models import Device, Event, Message
from server.productivity import continuous_idle_streak, generate_for_device


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
        db_session, device, ollama_url="http://unused", model="unused", idle_threshold_secs=threshold_secs
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


def test_continuous_idle_streak_none_with_no_afk_history(db_session):
    _make_device(db_session)
    assert continuous_idle_streak(db_session, "dev-1") is None


def test_continuous_idle_streak_none_when_currently_active(db_session):
    _make_device(db_session)
    _add_afk_event(db_session, "dev-1", ts=1000.0, state="active", duration=60.0)
    assert continuous_idle_streak(db_session, "dev-1") is None


def test_continuous_idle_streak_sums_consecutive_afk_rows(db_session):
    _make_device(db_session)
    _add_afk_event(db_session, "dev-1", ts=1000.0, state="afk", duration=100.0)
    _add_afk_event(db_session, "dev-1", ts=1100.0, state="afk", duration=200.0)
    _add_afk_event(db_session, "dev-1", ts=1300.0, state="afk", duration=50.0)

    result = continuous_idle_streak(db_session, "dev-1")

    assert result is not None
    total_secs, streak_start_ts = result
    assert total_secs == 350.0
    assert streak_start_ts == 1000.0


def test_continuous_idle_streak_stops_when_activity_resumed(db_session):
    _make_device(db_session)
    _add_afk_event(db_session, "dev-1", ts=1000.0, state="afk", duration=999.0)  # before resuming -- ignored
    _add_afk_event(db_session, "dev-1", ts=2000.0, state="active", duration=60.0)
    _add_afk_event(db_session, "dev-1", ts=2100.0, state="afk", duration=120.0)

    total_secs, streak_start_ts = continuous_idle_streak(db_session, "dev-1")

    assert total_secs == 120.0
    assert streak_start_ts == 2100.0


def test_generate_for_device_none_when_under_threshold(db_session):
    device = _make_device(db_session)
    _add_afk_event(db_session, "dev-1", ts=1000.0, state="afk", duration=60.0)

    assert _generate(db_session, device) is None


def test_generate_for_device_persists_message_over_threshold(db_session, monkeypatch):
    device = _make_device(db_session)
    _add_afk_event(db_session, "dev-1", ts=1000.0, state="afk", duration=1900.0)

    def fake_call_llm(prompt, ollama_url, model):
        return "you've been idle a while, come back!"

    monkeypatch.setattr("server.productivity.call_llm", fake_call_llm)

    result = _generate(db_session, device)

    assert result is not None
    assert result.text == "you've been idle a while, come back!"
    assert result.kind == "idle"
    stored = db_session.query(Message).filter_by(device_id="dev-1").one()
    assert stored.text == "you've been idle a while, come back!"


def test_generate_for_device_returns_none_on_llm_failure(db_session, monkeypatch):
    device = _make_device(db_session)
    _add_afk_event(db_session, "dev-1", ts=1000.0, state="afk", duration=1900.0)

    def _boom(prompt, ollama_url, model):
        raise ValueError("bad response")

    monkeypatch.setattr("server.productivity.call_llm", _boom)

    result = _generate(db_session, device)

    assert result is None
    assert db_session.query(Message).count() == 0


def test_generate_for_device_does_not_renotify_same_streak(db_session, monkeypatch):
    device = _make_device(db_session)
    _add_afk_event(db_session, "dev-1", ts=1000.0, state="afk", duration=1900.0)
    db_session.add(
        Message(
            message_id=str(uuid.uuid4()),
            device_id="dev-1",
            text="already told them",
            kind="idle",
            created_at=1500.0,
        )
    )
    db_session.commit()

    def fail_if_called(prompt, ollama_url, model):
        raise AssertionError("should not be called -- already notified this streak")

    monkeypatch.setattr("server.productivity.call_llm", fail_if_called)

    result = _generate(db_session, device)

    assert result is None
    assert db_session.query(Message).count() == 1


def test_generate_for_device_ignores_break_kind_messages_for_dedup(db_session, monkeypatch):
    # A "break" reminder sent for an earlier active streak must not suppress
    # a later, unrelated idle reminder -- the two kinds track independent
    # streaks (see Message.kind docstring in server/models.py).
    device = _make_device(db_session)
    _add_afk_event(db_session, "dev-1", ts=1000.0, state="afk", duration=1900.0)
    db_session.add(
        Message(
            message_id=str(uuid.uuid4()),
            device_id="dev-1",
            text="unrelated break reminder",
            kind="break",
            created_at=1999999999.0,
        )
    )
    db_session.commit()

    def fake_call_llm(prompt, ollama_url, model):
        return "idle reminder"

    monkeypatch.setattr("server.productivity.call_llm", fake_call_llm)

    result = _generate(db_session, device)

    assert result is not None
    assert result.text == "idle reminder"
