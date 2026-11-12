from __future__ import annotations

import time
import uuid

from server.goals import continuous_distraction_streak, current_goal, generate_distraction_reminder_for_device
from server.models import Device, Employee, Event, Goal, Message

_KEYWORDS = ["youtube", "netflix"]


def _make_employee(db_session, employee_id: str = "emp-1", system_name: str = "test-laptop") -> Employee:
    employee = Employee(employee_id=employee_id, name="Test Person", system_name=system_name)
    db_session.add(employee)
    db_session.commit()
    return employee


def _make_device(db_session, device_id: str = "dev-1", employee_id: str | None = None) -> Device:
    device = Device(
        device_id=device_id,
        device_token_hash=f"hash-{device_id}",
        device_name="test-laptop",
        os="Windows",
        os_version="11",
        employee_id=employee_id,
    )
    db_session.add(device)
    db_session.commit()
    return device


def _add_window_event(db_session, device_id: str, ts: float, title: str, duration: float, collector="window_watcher"):
    event = Event(
        event_id=str(uuid.uuid4()),
        device_id=device_id,
        collector=collector,
        ts=ts,
        duration=duration,
        data={"app": "chrome.exe", "title": title},
        batch_id="batch-1",
    )
    db_session.add(event)
    db_session.commit()
    return event


def _generate(db_session, device, threshold_secs: float = 300):
    return generate_distraction_reminder_for_device(
        db_session,
        device,
        ollama_url="http://unused",
        model="unused",
        keywords=_KEYWORDS,
        threshold_secs=threshold_secs,
    )


def test_continuous_distraction_streak_none_with_no_events(db_session):
    _make_device(db_session)
    assert continuous_distraction_streak(db_session, "dev-1", _KEYWORDS) is None


def test_continuous_distraction_streak_none_when_latest_not_a_match(db_session):
    _make_device(db_session)
    _add_window_event(db_session, "dev-1", ts=1000.0, title="Some Video Title - YouTube", duration=60.0)
    _add_window_event(db_session, "dev-1", ts=1100.0, title="config.toml - Visual Studio Code", duration=60.0)
    assert continuous_distraction_streak(db_session, "dev-1", _KEYWORDS) is None


def test_continuous_distraction_streak_sums_consecutive_matching_rows(db_session):
    _make_device(db_session)
    _add_window_event(db_session, "dev-1", ts=1000.0, title="Hero Movie - YouTube", duration=100.0)
    _add_window_event(db_session, "dev-1", ts=1100.0, title="Hero Movie - YouTube", duration=200.0)
    _add_window_event(db_session, "dev-1", ts=1300.0, title="Hero Movie - YouTube", duration=50.0)

    result = continuous_distraction_streak(db_session, "dev-1", _KEYWORDS)

    assert result is not None
    total_secs, streak_start_ts, label = result
    assert total_secs == 350.0
    assert streak_start_ts == 1000.0
    assert label == "Hero Movie - YouTube"


def test_continuous_distraction_streak_stops_at_non_matching_row(db_session):
    _make_device(db_session)
    _add_window_event(db_session, "dev-1", ts=1000.0, title="config.toml - Visual Studio Code", duration=999.0)
    _add_window_event(db_session, "dev-1", ts=2000.0, title="Hero Movie - YouTube", duration=120.0)

    total_secs, streak_start_ts, label = continuous_distraction_streak(db_session, "dev-1", _KEYWORDS)

    assert total_secs == 120.0
    assert streak_start_ts == 2000.0


def test_continuous_distraction_streak_stops_at_a_large_gap(db_session):
    _make_device(db_session)
    _add_window_event(db_session, "dev-1", ts=1000.0, title="Hero Movie - YouTube", duration=50.0)
    _add_window_event(db_session, "dev-1", ts=1000.0 + 4 * 86400, title="Hero Movie - YouTube", duration=30.0)

    total_secs, streak_start_ts, _ = continuous_distraction_streak(db_session, "dev-1", _KEYWORDS)

    assert total_secs == 30.0
    assert streak_start_ts == 1000.0 + 4 * 86400


def test_continuous_distraction_streak_checks_browser_bridge_url_too(db_session):
    _make_device(db_session)
    event = Event(
        event_id=str(uuid.uuid4()),
        device_id="dev-1",
        collector="browser_bridge",
        ts=1000.0,
        duration=200.0,
        data={"url": "https://youtube.com/watch?v=1", "title": ""},
        batch_id="batch-1",
    )
    db_session.add(event)
    db_session.commit()

    result = continuous_distraction_streak(db_session, "dev-1", _KEYWORDS)

    assert result is not None
    assert result[0] == 200.0


def test_current_goal_none_without_employee(db_session):
    assert current_goal(db_session, None) is None


def test_current_goal_none_when_no_goals(db_session):
    _make_employee(db_session)
    assert current_goal(db_session, "emp-1") is None


def test_current_goal_ignores_expired_goal(db_session):
    _make_employee(db_session)
    db_session.add(
        Goal(employee_id="emp-1", text="old goal", deadline_at=time.time() - 60, created_at=time.time() - 3600)
    )
    db_session.commit()
    assert current_goal(db_session, "emp-1") is None


def test_current_goal_returns_latest_active_goal(db_session):
    _make_employee(db_session)
    db_session.add(
        Goal(employee_id="emp-1", text="first goal", deadline_at=time.time() + 3600, created_at=time.time() - 100)
    )
    db_session.add(
        Goal(employee_id="emp-1", text="second goal", deadline_at=time.time() + 3600, created_at=time.time())
    )
    db_session.commit()

    goal = current_goal(db_session, "emp-1")

    assert goal is not None
    assert goal.text == "second goal"


def test_generate_none_when_under_threshold(db_session):
    device = _make_device(db_session)
    _add_window_event(db_session, "dev-1", ts=1000.0, title="Hero Movie - YouTube", duration=60.0)
    assert _generate(db_session, device) is None


def test_generate_persists_message_with_no_goal(db_session, monkeypatch):
    device = _make_device(db_session)  # no employee_id -- no goal possible
    _add_window_event(db_session, "dev-1", ts=1000.0, title="Hero Movie - YouTube", duration=400.0)

    captured_prompt = {}

    def fake_call_llm(prompt, ollama_url, model):
        captured_prompt["value"] = prompt
        return "stop watching hero movie and get back to work!"

    monkeypatch.setattr("server.goals.call_llm", fake_call_llm)

    result = _generate(db_session, device)

    assert result is not None
    assert result.kind == "distraction"
    assert result.text == "stop watching hero movie and get back to work!"
    assert "stated goal" not in captured_prompt["value"]  # no-goal prompt template, not the goal-aware one
    assert "Hero Movie - YouTube" in captured_prompt["value"]


def test_generate_persists_message_with_goal(db_session, monkeypatch):
    _make_employee(db_session)
    device = _make_device(db_session, employee_id="emp-1")
    db_session.add(
        Goal(employee_id="emp-1", text="finish the report", deadline_at=time.time() + 7200, created_at=time.time())
    )
    db_session.commit()
    _add_window_event(db_session, "dev-1", ts=time.time(), title="Hero Movie - YouTube", duration=400.0)

    captured_prompt = {}

    def fake_call_llm(prompt, ollama_url, model):
        captured_prompt["value"] = prompt
        return "come back and finish the report!"

    monkeypatch.setattr("server.goals.call_llm", fake_call_llm)

    result = _generate(db_session, device)

    assert result is not None
    assert "finish the report" in captured_prompt["value"]


def test_generate_returns_none_on_llm_failure(db_session, monkeypatch):
    device = _make_device(db_session)
    _add_window_event(db_session, "dev-1", ts=1000.0, title="Hero Movie - YouTube", duration=400.0)

    def _boom(prompt, ollama_url, model):
        raise ValueError("bad response")

    monkeypatch.setattr("server.goals.call_llm", _boom)

    result = _generate(db_session, device)

    assert result is None
    assert db_session.query(Message).count() == 0


def test_generate_does_not_renotify_same_streak(db_session, monkeypatch):
    device = _make_device(db_session)
    _add_window_event(db_session, "dev-1", ts=1000.0, title="Hero Movie - YouTube", duration=400.0)
    db_session.add(
        Message(
            message_id=str(uuid.uuid4()),
            device_id="dev-1",
            text="already told them",
            kind="distraction",
            created_at=1500.0,
        )
    )
    db_session.commit()

    def fail_if_called(prompt, ollama_url, model):
        raise AssertionError("should not be called -- already notified this streak")

    monkeypatch.setattr("server.goals.call_llm", fail_if_called)

    result = _generate(db_session, device)

    assert result is None
    assert db_session.query(Message).count() == 1


def test_break_message_does_not_suppress_distraction_message(db_session, monkeypatch):
    # Regression: kind must scope the dedup check -- an unrelated "break"
    # message must not suppress a "distraction" message for the same device.
    device = _make_device(db_session)
    _add_window_event(db_session, "dev-1", ts=1000.0, title="Hero Movie - YouTube", duration=400.0)
    db_session.add(
        Message(message_id=str(uuid.uuid4()), device_id="dev-1", text="take a break", kind="break", created_at=1500.0)
    )
    db_session.commit()

    monkeypatch.setattr("server.goals.call_llm", lambda prompt, ollama_url, model: "distraction reminder")

    result = _generate(db_session, device)

    assert result is not None
    assert result.text == "distraction reminder"
