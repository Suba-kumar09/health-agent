from __future__ import annotations

import uuid

from server.config import Settings
from server.models import Device, Event, Message
from server.orchestrator import route_device


def _settings(**overrides) -> Settings:
    base = dict(
        database_url="sqlite:///:memory:",
        max_request_bytes=1,
        rate_limit_window_secs=1,
        rate_limit_max_requests=1,
        enrollment_code_ttl_hours=1,
        wellbeing_enabled=True,
        openai_api_key="unused",
        openai_base_url="http://unused",
        wellbeing_model="unused",
        wellbeing_interval_secs=60,
        wellbeing_break_threshold_secs=1800,
        distraction_enabled=True,
        distraction_check_interval_secs=60,
        distraction_threshold_secs=1800,
        distraction_keywords=["youtube", "netflix"],
        distraction_exempt_keywords=["tutorial", "lecture", "course", "study"],
        productivity_enabled=True,
        productivity_idle_threshold_secs=1800,
        orchestrator_interval_secs=60,
        policy_enabled=True,
        policy_cooldown_secs=0,
        policy_daily_message_limit=50,
        policy_quiet_hours_start=0,
        policy_quiet_hours_end=0,
    )
    base.update(overrides)
    return Settings(**base)


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


def _add_afk_event(db_session, device_id: str, ts: float, state: str, duration: float):
    db_session.add(
        Event(
            event_id=str(uuid.uuid4()),
            device_id=device_id,
            collector="afk",
            ts=ts,
            duration=duration,
            data={"state": state},
            batch_id="batch-1",
        )
    )
    db_session.commit()


def _add_window_event(db_session, device_id: str, ts: float, title: str, duration: float):
    db_session.add(
        Event(
            event_id=str(uuid.uuid4()),
            device_id=device_id,
            collector="window_watcher",
            ts=ts,
            duration=duration,
            data={"app": "chrome.exe", "title": title},
            batch_id="batch-1",
        )
    )
    db_session.commit()


def test_no_agent_fires_with_no_activity(db_session, monkeypatch):
    device = _make_device(db_session)
    monkeypatch.setattr(
        "server.wellbeing.call_llm",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM should not be called")),
    )

    result = route_device(db_session, device, _settings())

    assert result is None
    assert db_session.query(Message).count() == 0


def test_notifier_fires_on_plain_active_streak(db_session, monkeypatch):
    device = _make_device(db_session)
    _add_afk_event(db_session, "dev-1", ts=1000.0, state="active", duration=1900.0)
    monkeypatch.setattr("server.wellbeing.call_llm", lambda *a, **k: "take a break")

    result = route_device(db_session, device, _settings())

    assert result is not None
    assert result.kind == "break"


def test_productivity_fires_on_idle_streak(db_session, monkeypatch):
    device = _make_device(db_session)
    _add_afk_event(db_session, "dev-1", ts=1000.0, state="afk", duration=1900.0)
    monkeypatch.setattr("server.productivity.call_llm", lambda *a, **k: "you idle?")

    result = route_device(db_session, device, _settings())

    assert result is not None
    assert result.kind == "idle"


def test_distraction_wins_over_notifier_when_both_conditions_met(db_session, monkeypatch):
    # Being on a keyword-matching site still counts as "active" for afk
    # purposes, so both Notifier's and Distraction's conditions can be true
    # at once -- Distraction must win per the documented priority order.
    device = _make_device(db_session)
    _add_afk_event(db_session, "dev-1", ts=1000.0, state="active", duration=1900.0)
    _add_window_event(db_session, "dev-1", ts=1000.0, title="YouTube - funny cats", duration=1900.0)
    monkeypatch.setattr(
        "server.wellbeing.call_llm",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("Notifier should not fire -- Distraction outranks it")),
    )
    monkeypatch.setattr("server.goals.call_llm", lambda *a, **k: "get back to work")

    result = route_device(db_session, device, _settings())

    assert result is not None
    assert result.kind == "distraction"


def test_no_agent_fires_for_exempt_study_content(db_session, monkeypatch):
    # A study-titled tab is exempt from Distraction, and there's no separate
    # agent for it -- it should simply stay silent, same as any other
    # non-distracting, non-idle, "just started being active" state.
    device = _make_device(db_session)
    _add_afk_event(db_session, "dev-1", ts=1000.0, state="active", duration=30.0)
    _add_window_event(db_session, "dev-1", ts=1000.0, title="Organic Chemistry Course - YouTube", duration=1900.0)
    monkeypatch.setattr(
        "server.goals.call_llm",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("Distraction should not fire -- title is exempt")),
    )

    result = route_device(db_session, device, _settings())

    assert result is None


def test_policy_engine_blocks_even_when_an_agent_would_fire(db_session, monkeypatch):
    device = _make_device(db_session)
    _add_afk_event(db_session, "dev-1", ts=1000.0, state="active", duration=1900.0)
    # A very recent prior message keeps the device inside cooldown.
    db_session.add(
        Message(
            message_id=str(uuid.uuid4()),
            device_id="dev-1",
            text="recent",
            kind="break",
            created_at=1_700_000_000.0,
        )
    )
    db_session.commit()
    monkeypatch.setattr(
        "server.wellbeing.call_llm",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("Policy Engine should have blocked this")),
    )

    result = route_device(
        db_session, device, _settings(policy_cooldown_secs=999_999_999)
    )

    assert result is None


def test_policy_engine_bypassed_when_policy_disabled(db_session, monkeypatch):
    device = _make_device(db_session)
    _add_afk_event(db_session, "dev-1", ts=1000.0, state="active", duration=1900.0)
    # A different-kind ("idle") message doesn't trip Notifier's own per-kind
    # dedup, only the Policy Engine's cross-agent cooldown -- isolates what
    # this test is actually checking (policy_enabled=False skips the gate).
    db_session.add(
        Message(
            message_id=str(uuid.uuid4()),
            device_id="dev-1",
            text="recent",
            kind="idle",
            created_at=1_700_000_000.0,
        )
    )
    db_session.commit()
    monkeypatch.setattr("server.wellbeing.call_llm", lambda *a, **k: "take a break")

    result = route_device(
        db_session, device, _settings(policy_enabled=False, policy_cooldown_secs=999_999_999)
    )

    assert result is not None
    assert result.kind == "break"


def test_disabled_agent_never_wins_routing(db_session, monkeypatch):
    device = _make_device(db_session)
    _add_afk_event(db_session, "dev-1", ts=1000.0, state="active", duration=1900.0)
    monkeypatch.setattr(
        "server.wellbeing.call_llm",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("wellbeing is disabled, should not fire")),
    )

    result = route_device(db_session, device, _settings(wellbeing_enabled=False))

    assert result is None


def test_unshown_recent_message_blocks_a_new_one(db_session, monkeypatch):
    import time

    device = _make_device(db_session)
    _add_afk_event(db_session, "dev-1", ts=1000.0, state="active", duration=1900.0)
    # Created a minute ago and never acked: the agent hasn't popped it yet.
    db_session.add(
        Message(
            message_id=str(uuid.uuid4()), device_id="dev-1", text="pending", kind="idle", created_at=time.time() - 60
        )
    )
    db_session.commit()
    monkeypatch.setattr(
        "server.wellbeing.call_llm",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not stack on an un-shown message")),
    )

    assert route_device(db_session, device, _settings()) is None


def test_abandoned_message_does_not_block_forever(db_session, monkeypatch):
    import time

    device = _make_device(db_session)
    _add_afk_event(db_session, "dev-1", ts=1000.0, state="active", duration=1900.0)
    db_session.add(
        Message(
            message_id=str(uuid.uuid4()), device_id="dev-1", text="stale", kind="idle", created_at=time.time() - 3600
        )
    )
    db_session.commit()
    monkeypatch.setattr("server.wellbeing.call_llm", lambda *a, **k: "take a break")

    result = route_device(db_session, device, _settings())

    assert result is not None and result.kind == "break"
