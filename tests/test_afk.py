from agent.collectors.afk import AfkCollector


def make_afk(threshold_secs=120.0, start=1000.0):
    clock = {"t": start}
    last_activity = {"ts": start}
    locked = {"is_locked": False}
    new_states = []
    extends = []

    def on_new_state(info, ts):
        event_id = f"evt-{len(new_states)}"
        new_states.append((event_id, info["state"], ts))
        return event_id

    def on_extend(event_id, duration):
        extends.append((event_id, duration))
        return True

    afk = AfkCollector(
        get_last_activity_ts=lambda: last_activity["ts"],
        on_new_state=on_new_state,
        on_extend=on_extend,
        threshold_secs=threshold_secs,
        now_fn=lambda: clock["t"],
        is_locked_fn=lambda: locked["is_locked"],
    )
    return afk, clock, last_activity, new_states, extends, locked


def test_starts_active_when_recently_active():
    afk, clock, last_activity, new_states, extends, locked = make_afk()

    afk.poll_once(now=1000.0)

    assert new_states[0][1] == "active"


def test_transitions_to_afk_after_threshold_with_no_input():
    afk, clock, last_activity, new_states, extends, locked = make_afk(threshold_secs=120.0, start=1000.0)
    afk.poll_once(now=1000.0)  # active

    afk.poll_once(now=1125.0)  # 125s since last activity -> afk

    assert new_states[-1][1] == "afk"


def test_stays_active_while_input_keeps_arriving():
    afk, clock, last_activity, new_states, extends, locked = make_afk(threshold_secs=120.0, start=1000.0)
    afk.poll_once(now=1000.0)  # active

    last_activity["ts"] = 1050.0  # fresh input
    afk.poll_once(now=1060.0)

    assert new_states[-1][1] == "active"
    assert len(new_states) == 1  # coalesced, same "active" state throughout
    assert extends == [("evt-0", 60.0)]


def test_returns_to_active_when_input_resumes_after_afk():
    afk, clock, last_activity, new_states, extends, locked = make_afk(threshold_secs=120.0, start=1000.0)
    afk.poll_once(now=1000.0)  # active
    afk.poll_once(now=1200.0)  # afk (200s idle)

    last_activity["ts"] = 1300.0
    afk.poll_once(now=1305.0)  # active again

    assert [s[1] for s in new_states] == ["active", "afk", "active"]


def test_locked_overrides_recent_activity():
    afk, clock, last_activity, new_states, extends, locked = make_afk(threshold_secs=120.0, start=1000.0)
    afk.poll_once(now=1000.0)  # active

    locked["is_locked"] = True
    last_activity["ts"] = 1000.0  # activity is still "recent" -- locked must still win
    afk.poll_once(now=1005.0)

    assert new_states[-1][1] == "locked"


def test_returns_to_active_when_unlocked():
    afk, clock, last_activity, new_states, extends, locked = make_afk(threshold_secs=120.0, start=1000.0)
    afk.poll_once(now=1000.0)  # active

    locked["is_locked"] = True
    afk.poll_once(now=1005.0)  # locked

    locked["is_locked"] = False
    last_activity["ts"] = 1010.0
    afk.poll_once(now=1010.0)

    assert [s[1] for s in new_states] == ["active", "locked", "active"]
