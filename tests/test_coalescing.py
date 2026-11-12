from agent.collectors.coalescing import CoalescingStatePoller


def make_poller(extend_succeeds=True):
    events = []  # (info, ts) for new states
    extends = []  # (event_id, duration)

    def on_new_state(info, ts):
        event_id = f"evt-{len(events)}"
        events.append((event_id, info, ts))
        return event_id

    def on_extend(event_id, duration):
        extends.append((event_id, duration))
        return extend_succeeds() if callable(extend_succeeds) else extend_succeeds

    poller = CoalescingStatePoller(
        state_key_fn=lambda info: info.get("k") if info else None,
        on_new_state=on_new_state,
        on_extend=on_extend,
    )
    return poller, events, extends


def test_first_poll_creates_new_state():
    poller, events, extends = make_poller()

    poller.poll({"k": "a"}, now=100.0)

    assert len(events) == 1
    assert events[0][1] == {"k": "a"}
    assert extends == []


def test_repeated_identical_state_extends_not_recreates():
    poller, events, extends = make_poller()
    poller.poll({"k": "a"}, now=100.0)

    poller.poll({"k": "a"}, now=105.0)
    poller.poll({"k": "a"}, now=110.0)

    assert len(events) == 1
    assert extends == [("evt-0", 5.0), ("evt-0", 10.0)]


def test_state_change_finalizes_and_creates_new():
    poller, events, extends = make_poller()
    poller.poll({"k": "a"}, now=100.0)
    poller.poll({"k": "a"}, now=105.0)

    poller.poll({"k": "b"}, now=110.0)

    assert len(events) == 2
    assert events[1][1] == {"k": "b"}
    # no extend call for the new state itself
    assert extends == [("evt-0", 5.0)]


def test_none_info_clears_current_state_without_creating_event():
    poller, events, extends = make_poller()
    poller.poll({"k": "a"}, now=100.0)

    poller.poll(None, now=105.0)

    assert len(events) == 1  # no new event for the None state
    assert extends == []

    # Coming back to the same key "a" after a None gap creates a fresh event
    # (not an extend of the old one) since the current state was cleared.
    poller.poll({"k": "a"}, now=110.0)
    assert len(events) == 2


def test_extend_failure_starts_fresh_event_without_losing_the_state():
    """A frozen row (extend_duration returns False, e.g. already synced by an
    in-flight batch) must not silently swallow further duration for a state
    that's still ongoing -- a new event should start in its place."""
    events = []
    extend_results = iter([True, False, True])

    def on_new_state(info, ts):
        event_id = f"evt-{len(events)}"
        events.append((event_id, info, ts))
        return event_id

    def on_extend(event_id, duration):
        return next(extend_results)

    poller = CoalescingStatePoller(
        state_key_fn=lambda info: info.get("k") if info else None,
        on_new_state=on_new_state,
        on_extend=on_extend,
    )

    poller.poll({"k": "a"}, now=100.0)  # creates evt-0
    poller.poll({"k": "a"}, now=105.0)  # extend succeeds
    poller.poll({"k": "a"}, now=110.0)  # extend fails (row frozen) -> fresh event
    poller.poll({"k": "a"}, now=115.0)  # extend succeeds on the fresh event

    assert len(events) == 2
    assert events[1][1] == {"k": "a"}
    assert events[1][2] == 110.0


def test_frozen_row_starts_a_fresh_event_instead_of_going_dark():
    # Simulates a batch upload claiming the current row mid-streak (see
    # Storage.extend_duration's synced=0/batch_id IS NULL guard): on_extend
    # starts returning False even though the state itself hasn't changed.
    poller, events, extends = make_poller(extend_succeeds=False)
    poller.poll({"k": "a"}, now=100.0)

    poller.poll({"k": "a"}, now=105.0)

    assert len(events) == 2  # a fresh event was minted, not silently dropped
    assert events[1][1] == {"k": "a"}  # same state, new row
    assert extends == [("evt-0", 5.0)]  # the failed extend attempt is still recorded


def test_recovers_after_frozen_row_and_keeps_extending_the_new_one():
    calls = {"n": 0}

    def flaky_extend_succeeds():
        calls["n"] += 1
        return calls["n"] > 1  # first extend fails (frozen), rest succeed

    poller, events, extends = make_poller(extend_succeeds=flaky_extend_succeeds)
    poller.poll({"k": "a"}, now=100.0)

    poller.poll({"k": "a"}, now=105.0)  # extend fails -> fresh evt-1 starts at t=105
    poller.poll({"k": "a"}, now=115.0)  # extends evt-1 normally

    assert len(events) == 2
    assert extends[-1] == ("evt-1", 10.0)
