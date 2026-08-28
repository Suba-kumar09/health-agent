import time

from agent.collectors.afk import AfkCollector


def make_afk(threshold_secs=120.0, start=1000.0):
    clock = {"t": start}
    last_activity = {"ts": start}
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
    )
    return afk, clock, last_activity, new_states, extends


def test_starts_active_when_recently_active():
    afk, clock, last_activity, new_states, extends = make_afk()

    afk.poll_once(now=1000.0)

    assert new_states[0][1] == "active"


def test_transitions_to_afk_after_threshold_with_no_input():
    afk, clock, last_activity, new_states, extends = make_afk(threshold_secs=120.0, start=1000.0)
    afk.poll_once(now=1000.0)  # active

    afk.poll_once(now=1125.0)  # 125s since last activity -> afk

    assert new_states[-1][1] == "afk"


def test_stays_active_while_input_keeps_arriving():
    afk, clock, last_activity, new_states, extends = make_afk(threshold_secs=120.0, start=1000.0)
    afk.poll_once(now=1000.0)  # active

    last_activity["ts"] = 1050.0  # fresh input
    afk.poll_once(now=1060.0)

    assert new_states[-1][1] == "active"
    assert len(new_states) == 1  # coalesced, same "active" state throughout
    assert extends == [("evt-0", 60.0)]


def test_returns_to_active_when_input_resumes_after_afk():
    afk, clock, last_activity, new_states, extends = make_afk(threshold_secs=120.0, start=1000.0)
    afk.poll_once(now=1000.0)  # active
    afk.poll_once(now=1200.0)  # afk (200s idle)

    last_activity["ts"] = 1300.0
    afk.poll_once(now=1305.0)  # active again

    assert [s[1] for s in new_states] == ["active", "afk", "active"]


def test_poll_loop_survives_a_failing_poll():
    # Regression test: an unhandled exception in poll_once() used to kill the
    # daemon polling thread silently, forever -- no crash, no log, and every
    # *other* collector kept running fine, which is exactly what made this so
    # hard to spot live. One real failing poll should not stop later ones.
    poll_count = {"n": 0}

    def flaky_get_last_activity_ts():
        poll_count["n"] += 1
        if poll_count["n"] == 1:
            raise RuntimeError("simulated poll failure")
        return time.time()

    afk = AfkCollector(
        get_last_activity_ts=flaky_get_last_activity_ts,
        on_new_state=lambda info, ts: "evt-0",
        on_extend=lambda event_id, duration: True,
        poll_interval_secs=0.01,
    )

    afk.start()
    try:
        deadline = time.time() + 2.0
        while poll_count["n"] < 3 and time.time() < deadline:
            time.sleep(0.01)
    finally:
        afk.stop()

    assert poll_count["n"] >= 3
